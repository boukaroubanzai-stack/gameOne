"""Map editor for the RTS game. Launch with run_editor() or python map_editor.py."""

import copy
import os
import subprocess
import sys
import tempfile

import pygame

from settings import (
    WIDTH, HEIGHT, FPS, MAP_COLOR, HUD_HEIGHT,
    WORLD_W, WORLD_H, SCROLL_SPEED, SCROLL_EDGE,
    NAV_TILE_SIZE, BUILDING_ZONE_TC_RADIUS,
    TOWN_CENTER_SIZE, MINERAL_NODE_SIZE,
)
from map_format import save_map, load_map, default_map_data
from navigation import NavGrid, GRID_W, GRID_H, WALKABLE
from utils import get_font

# Editor colors
TERRAIN_COLOR = (90, 60, 30)
TERRAIN_BORDER_COLOR = (60, 40, 20)
TERRAIN_PREVIEW_COLOR = (90, 60, 30, 100)
GRID_COLOR = (50, 70, 50)
NAV_BLOCKED_COLOR = (200, 0, 0, 60)
NAV_WALKABLE_COLOR = (0, 200, 0, 30)
PLAYER_TC_COLOR = (0, 200, 0)
AI_TC_COLOR = (220, 140, 0)
PLAYER_MINERAL_COLOR = (255, 220, 50)
AI_MINERAL_COLOR = (220, 160, 30)
ZONE_COLOR_PLAYER = (0, 200, 0, 30)
ZONE_COLOR_AI = (220, 140, 0, 30)
TOOLBAR_BG = (40, 40, 40)
BUTTON_COLOR = (70, 70, 70)
BUTTON_HOVER = (100, 100, 100)
BUTTON_ACTIVE = (50, 120, 50)
BUTTON_TEXT_COLOR = (255, 255, 255)

SNAP = NAV_TILE_SIZE  # 32px grid snap


class MapEditor:
    def __init__(self, filepath=None):
        self.filepath = filepath
        if filepath:
            self.map_data = load_map(filepath)
        else:
            self.map_data = default_map_data()

        self.terrain_rects = [tuple(r) for r in self.map_data["terrain_rects"]]
        self.player_tc = list(self.map_data["starting_positions"]["player"]["tc_pos"])
        self.ai_tc = list(self.map_data["starting_positions"]["ai"]["tc_pos"])
        self.player_minerals = [list(o) for o in self.map_data["starting_positions"]["player"]["mineral_offsets"]]
        self.ai_minerals = [list(o) for o in self.map_data["starting_positions"]["ai"]["mineral_offsets"]]
        self.mineral_amount = self.map_data.get("mineral_amount", 2500)
        self.symmetry = True

        # Camera
        self.cam_x = 0.0
        self.cam_y = 0.0

        # Tools
        self.current_tool = "terrain"
        self.drawing = False
        self.draw_start = None

        # Undo/redo
        self.undo_stack = []
        self.redo_stack = []

        # Grid/nav display
        self.show_grid = True
        self.show_nav = False
        self.nav_grid = NavGrid()
        self._rebuild_nav()

        # Connectivity
        self.connected = True

        # Scroll flags
        self.scroll_left = False
        self.scroll_right = False
        self.scroll_up = False
        self.scroll_down = False

        # Screen dimensions (may change on resize)
        self.width = WIDTH
        self.height = HEIGHT
        self.map_height = HEIGHT - HUD_HEIGHT

        # Selection for erase highlight
        self.hovered_rect_idx = -1

        # Help overlay
        self.show_help = False

    def _screen_to_world(self, screen_pos):
        return (screen_pos[0] + self.cam_x, screen_pos[1] + self.cam_y)

    def _world_to_screen(self, world_pos):
        return (world_pos[0] - self.cam_x, world_pos[1] - self.cam_y)

    def _snap(self, val):
        return int(val) // SNAP * SNAP

    def _snap_pos(self, wx, wy):
        return (self._snap(wx), self._snap(wy))

    def _push_undo(self):
        state = (
            [tuple(r) for r in self.terrain_rects],
            [list(m) for m in self.player_minerals],
            [list(m) for m in self.ai_minerals],
            list(self.player_tc),
            list(self.ai_tc),
        )
        self.undo_stack.append(state)
        self.redo_stack.clear()

    def _undo(self):
        if not self.undo_stack:
            return
        # Save current state for redo
        current = (
            [tuple(r) for r in self.terrain_rects],
            [list(m) for m in self.player_minerals],
            [list(m) for m in self.ai_minerals],
            list(self.player_tc),
            list(self.ai_tc),
        )
        self.redo_stack.append(current)
        state = self.undo_stack.pop()
        self.terrain_rects = list(state[0])
        self.player_minerals = list(state[1])
        self.ai_minerals = list(state[2])
        self.player_tc = list(state[3])
        self.ai_tc = list(state[4])
        self._rebuild_nav()

    def _redo(self):
        if not self.redo_stack:
            return
        current = (
            [tuple(r) for r in self.terrain_rects],
            [list(m) for m in self.player_minerals],
            [list(m) for m in self.ai_minerals],
            list(self.player_tc),
            list(self.ai_tc),
        )
        self.undo_stack.append(current)
        state = self.redo_stack.pop()
        self.terrain_rects = list(state[0])
        self.player_minerals = list(state[1])
        self.ai_minerals = list(state[2])
        self.player_tc = list(state[3])
        self.ai_tc = list(state[4])
        self._rebuild_nav()

    def _rebuild_nav(self):
        self.nav_grid = NavGrid()
        self.nav_grid.load_terrain(self.terrain_rects, self.player_tc, self.ai_tc)
        # Check connectivity
        pg = self.nav_grid.world_to_grid(self.player_tc[0] + 32, self.player_tc[1] + 32)
        ag = self.nav_grid.world_to_grid(self.ai_tc[0] + 32, self.ai_tc[1] + 32)
        self.connected = self.nav_grid._bfs_connected(pg, ag)

    def _build_map_data(self):
        return {
            "version": 1,
            "name": self.map_data.get("name", "Custom"),
            "author": self.map_data.get("author", ""),
            "world_size": [WORLD_W, WORLD_H],
            "terrain_rects": [list(r) for r in self.terrain_rects],
            "starting_positions": {
                "player": {
                    "tc_pos": list(self.player_tc),
                    "mineral_offsets": [list(o) for o in self.player_minerals],
                    "starting_resources": self.map_data["starting_positions"]["player"].get("starting_resources", 50),
                    "starting_workers": self.map_data["starting_positions"]["player"].get("starting_workers", 3),
                },
                "ai": {
                    "tc_pos": list(self.ai_tc),
                    "mineral_offsets": [list(o) for o in self.ai_minerals],
                    "starting_resources": self.map_data["starting_positions"]["ai"].get("starting_resources", 50),
                    "starting_workers": self.map_data["starting_positions"]["ai"].get("starting_workers", 3),
                },
            },
            "mineral_amount": self.mineral_amount,
            "symmetry": "mirror_x" if self.symmetry else "none",
        }

    def _save(self):
        if not self.filepath:
            self.filepath = os.path.join("maps", "custom_map.map.json")
        data = self._build_map_data()
        save_map(self.filepath, data)

    def _load_file(self, filepath):
        try:
            self.map_data = load_map(filepath)
            self.filepath = filepath
            self.terrain_rects = [tuple(r) for r in self.map_data["terrain_rects"]]
            self.player_tc = list(self.map_data["starting_positions"]["player"]["tc_pos"])
            self.ai_tc = list(self.map_data["starting_positions"]["ai"]["tc_pos"])
            self.player_minerals = [list(o) for o in self.map_data["starting_positions"]["player"]["mineral_offsets"]]
            self.ai_minerals = [list(o) for o in self.map_data["starting_positions"]["ai"]["mineral_offsets"]]
            self.mineral_amount = self.map_data.get("mineral_amount", 2500)
            self.undo_stack.clear()
            self.redo_stack.clear()
            self._rebuild_nav()
        except Exception as e:
            print(f"Failed to load map: {e}")

    def _test_play(self):
        """Save to temp file and launch game."""
        data = self._build_map_data()
        fd, tmppath = tempfile.mkstemp(suffix=".map.json", prefix="editor_test_")
        os.close(fd)
        save_map(tmppath, data)
        game_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.py")
        subprocess.Popen([sys.executable, game_py, "--map", tmppath])

    def _new_map(self):
        self._push_undo()
        self.map_data = default_map_data()
        self.filepath = None
        self.terrain_rects = []
        self.player_tc = list(self.map_data["starting_positions"]["player"]["tc_pos"])
        self.ai_tc = list(self.map_data["starting_positions"]["ai"]["tc_pos"])
        self.player_minerals = [list(o) for o in self.map_data["starting_positions"]["player"]["mineral_offsets"]]
        self.ai_minerals = [list(o) for o in self.map_data["starting_positions"]["ai"]["mineral_offsets"]]
        self.mineral_amount = self.map_data.get("mineral_amount", 2500)
        self._rebuild_nav()

    def _find_rect_at(self, wx, wy):
        """Return index of terrain rect containing world point, or -1."""
        for i, (rx, ry, rw, rh) in enumerate(self.terrain_rects):
            if rx <= wx < rx + rw and ry <= wy < ry + rh:
                return i
        return -1

    def _find_mirror_rect(self, rect):
        """Find the mirror of a rect in the list. Returns index or -1."""
        rx, ry, rw, rh = rect
        mx = WORLD_W - rx - rw
        for i, (ex, ey, ew, eh) in enumerate(self.terrain_rects):
            if abs(ex - mx) < 2 and abs(ey - ry) < 2 and abs(ew - rw) < 2 and abs(eh - rh) < 2:
                return i
        return -1

    def _mineral_world_pos(self, tc_pos, offset):
        """Get world position of a mineral node given tc_pos and offset."""
        return (tc_pos[0] + offset[0], tc_pos[1] + offset[1])

    def _find_nearest_mineral(self, wx, wy, minerals, tc_pos):
        """Find index of nearest mineral to world pos. Returns (idx, dist) or (-1, inf)."""
        best_idx = -1
        best_dist = float("inf")
        for i, off in enumerate(minerals):
            mx, my = self._mineral_world_pos(tc_pos, off)
            d = (wx - mx) ** 2 + (wy - my) ** 2
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx, best_dist ** 0.5

    def _list_map_files(self):
        """List .map.json files in maps/ directory."""
        maps_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maps")
        if not os.path.isdir(maps_dir):
            return []
        files = []
        for f in sorted(os.listdir(maps_dir)):
            if f.endswith(".map.json"):
                files.append(os.path.join(maps_dir, f))
        return files

    # --- Main loop ---

    def run(self, screen, clock):
        running = True
        # File picker state
        file_picker_open = False
        file_picker_files = []
        file_picker_scroll = 0

        while running:
            dt = clock.tick(FPS) / 1000.0

            # --- Events ---
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    break

                if event.type == pygame.VIDEORESIZE:
                    self.width = event.w
                    self.height = event.h
                    self.map_height = self.height - HUD_HEIGHT
                    screen = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)
                    continue

                if event.type == pygame.KEYDOWN:
                    if file_picker_open:
                        if event.key == pygame.K_ESCAPE:
                            file_picker_open = False
                        continue

                    mods = pygame.key.get_mods()
                    ctrl = mods & pygame.KMOD_CTRL

                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_LEFT:
                        self.scroll_left = True
                    elif event.key == pygame.K_RIGHT:
                        self.scroll_right = True
                    elif event.key == pygame.K_UP:
                        self.scroll_up = True
                    elif event.key == pygame.K_DOWN:
                        self.scroll_down = True
                    elif ctrl and event.key == pygame.K_s:
                        self._save()
                    elif ctrl and event.key == pygame.K_l:
                        file_picker_files = self._list_map_files()
                        file_picker_open = True
                        file_picker_scroll = 0
                    elif ctrl and event.key == pygame.K_t:
                        self._test_play()
                    elif ctrl and event.key == pygame.K_n:
                        self._new_map()
                    elif ctrl and event.key == pygame.K_z:
                        self._undo()
                    elif ctrl and event.key == pygame.K_y:
                        self._redo()
                    elif not ctrl:
                        if event.key == pygame.K_t:
                            self.current_tool = "terrain"
                        elif event.key == pygame.K_e:
                            self.current_tool = "erase"
                        elif event.key == pygame.K_n:
                            self.current_tool = "mineral"
                        elif event.key == pygame.K_1:
                            self.current_tool = "tc_player"
                        elif event.key == pygame.K_2:
                            self.current_tool = "tc_ai"
                        elif event.key == pygame.K_s:
                            self.current_tool = "select"
                        elif event.key == pygame.K_g:
                            self.show_grid = not self.show_grid
                        elif event.key == pygame.K_v:
                            self.show_nav = not self.show_nav
                        elif event.key == pygame.K_m:
                            self.symmetry = not self.symmetry
                        elif event.key == pygame.K_h:
                            self.show_help = not self.show_help

                elif event.type == pygame.KEYUP:
                    if event.key == pygame.K_LEFT:
                        self.scroll_left = False
                    elif event.key == pygame.K_RIGHT:
                        self.scroll_right = False
                    elif event.key == pygame.K_UP:
                        self.scroll_up = False
                    elif event.key == pygame.K_DOWN:
                        self.scroll_down = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    sx, sy = event.pos

                    # File picker click
                    if file_picker_open:
                        if event.button == 1:
                            # Check if clicking a file entry
                            picker_x = self.width // 2 - 200
                            picker_y = 100
                            picker_w = 400
                            row_h = 30
                            for i, fpath in enumerate(file_picker_files):
                                ry = picker_y + 40 + i * row_h - file_picker_scroll
                                if picker_x <= sx < picker_x + picker_w and ry <= sy < ry + row_h:
                                    self._load_file(fpath)
                                    file_picker_open = False
                                    break
                            # Close button area (click outside)
                            if sy < picker_y or sy > picker_y + 40 + len(file_picker_files) * row_h + 20:
                                file_picker_open = False
                        elif event.button == 4:  # scroll up
                            file_picker_scroll = max(0, file_picker_scroll - 30)
                        elif event.button == 5:  # scroll down
                            file_picker_scroll += 30
                        continue

                    # Toolbar click
                    if sy >= self.map_height:
                        self._handle_toolbar_click(sx, sy)
                        continue

                    wx, wy = self._screen_to_world((sx, sy))

                    if event.button == 1:
                        if self.current_tool == "terrain":
                            self.drawing = True
                            self.draw_start = self._snap_pos(wx, wy)
                        elif self.current_tool == "erase":
                            idx = self._find_rect_at(wx, wy)
                            if idx >= 0:
                                self._push_undo()
                                removed = self.terrain_rects[idx]
                                del self.terrain_rects[idx]
                                if self.symmetry:
                                    mirror_idx = self._find_mirror_rect(removed)
                                    if mirror_idx >= 0:
                                        del self.terrain_rects[mirror_idx]
                                self._rebuild_nav()
                        elif self.current_tool == "mineral":
                            self._push_undo()
                            # Place mineral as offset from nearest TC
                            dp = ((wx - self.player_tc[0]) ** 2 + (wy - self.player_tc[1]) ** 2) ** 0.5
                            da = ((wx - self.ai_tc[0]) ** 2 + (wy - self.ai_tc[1]) ** 2) ** 0.5
                            if dp <= da:
                                off = [int(wx - self.player_tc[0]), int(wy - self.player_tc[1])]
                                self.player_minerals.append(off)
                                if self.symmetry:
                                    ai_off = [int(-off[0]), int(off[1])]
                                    self.ai_minerals.append(ai_off)
                            else:
                                off = [int(wx - self.ai_tc[0]), int(wy - self.ai_tc[1])]
                                self.ai_minerals.append(off)
                                if self.symmetry:
                                    player_off = [int(-off[0]), int(off[1])]
                                    self.player_minerals.append(player_off)
                        elif self.current_tool == "tc_player":
                            self._push_undo()
                            self.player_tc = [self._snap(wx), self._snap(wy)]
                            self._rebuild_nav()
                        elif self.current_tool == "tc_ai":
                            self._push_undo()
                            self.ai_tc = [self._snap(wx), self._snap(wy)]
                            self._rebuild_nav()

                    elif event.button == 3:  # Right click
                        if self.current_tool == "mineral":
                            # Remove nearest mineral
                            pi, pd = self._find_nearest_mineral(wx, wy, self.player_minerals, self.player_tc)
                            ai, ad = self._find_nearest_mineral(wx, wy, self.ai_minerals, self.ai_tc)
                            if pd < ad and pd < 50:
                                self._push_undo()
                                removed_off = self.player_minerals[pi]
                                del self.player_minerals[pi]
                                if self.symmetry:
                                    mirror_off = [-removed_off[0], removed_off[1]]
                                    for j, ao in enumerate(self.ai_minerals):
                                        if abs(ao[0] - mirror_off[0]) < 5 and abs(ao[1] - mirror_off[1]) < 5:
                                            del self.ai_minerals[j]
                                            break
                            elif ad < 50:
                                self._push_undo()
                                removed_off = self.ai_minerals[ai]
                                del self.ai_minerals[ai]
                                if self.symmetry:
                                    mirror_off = [-removed_off[0], removed_off[1]]
                                    for j, po in enumerate(self.player_minerals):
                                        if abs(po[0] - mirror_off[0]) < 5 and abs(po[1] - mirror_off[1]) < 5:
                                            del self.player_minerals[j]
                                            break

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1 and self.drawing:
                        self.drawing = False
                        if self.draw_start:
                            sx_s, sy_s = event.pos
                            wx2, wy2 = self._screen_to_world((sx_s, sy_s))
                            ex, ey = self._snap(wx2), self._snap(wy2)
                            sx_w, sy_w = self.draw_start

                            x = min(sx_w, ex)
                            y = min(sy_w, ey)
                            w = abs(ex - sx_w)
                            h = abs(ey - sy_w)

                            # Minimum size
                            if w >= SNAP and h >= SNAP:
                                self._push_undo()
                                self.terrain_rects.append((x, y, w, h))
                                if self.symmetry:
                                    mx = WORLD_W - x - w
                                    self.terrain_rects.append((mx, y, w, h))
                                self._rebuild_nav()
                        self.draw_start = None

            if not running:
                break

            # --- Camera scrolling ---
            mouse_x, mouse_y = pygame.mouse.get_pos()
            if mouse_x < SCROLL_EDGE:
                self.cam_x -= SCROLL_SPEED * dt
            elif mouse_x > self.width - SCROLL_EDGE:
                self.cam_x += SCROLL_SPEED * dt
            if mouse_y < SCROLL_EDGE:
                self.cam_y -= SCROLL_SPEED * dt
            elif mouse_y > self.map_height - SCROLL_EDGE and mouse_y < self.map_height:
                self.cam_y += SCROLL_SPEED * dt

            if self.scroll_left:
                self.cam_x -= SCROLL_SPEED * dt
            if self.scroll_right:
                self.cam_x += SCROLL_SPEED * dt
            if self.scroll_up:
                self.cam_y -= SCROLL_SPEED * dt
            if self.scroll_down:
                self.cam_y += SCROLL_SPEED * dt

            self.cam_x = max(0, min(self.cam_x, WORLD_W - self.width))
            self.cam_y = max(0, min(self.cam_y, WORLD_H - self.map_height))

            # --- Update hovered rect for erase tool ---
            if self.current_tool == "erase":
                mwx, mwy = self._screen_to_world((mouse_x, mouse_y))
                self.hovered_rect_idx = self._find_rect_at(mwx, mwy)
            else:
                self.hovered_rect_idx = -1

            # --- Drawing ---
            self._draw(screen, file_picker_open, file_picker_files, file_picker_scroll)

            pygame.display.flip()

    def _handle_toolbar_click(self, sx, sy):
        """Handle click in the toolbar area."""
        buttons = self._get_toolbar_buttons()
        for name, rect in buttons:
            if rect.collidepoint(sx, sy):
                if name == "Terrain":
                    self.current_tool = "terrain"
                elif name == "Erase":
                    self.current_tool = "erase"
                elif name == "Mineral":
                    self.current_tool = "mineral"
                elif name == "Player TC":
                    self.current_tool = "tc_player"
                elif name == "AI TC":
                    self.current_tool = "tc_ai"
                elif name == "Select":
                    self.current_tool = "select"
                elif name == "Grid":
                    self.show_grid = not self.show_grid
                elif name == "Nav":
                    self.show_nav = not self.show_nav
                elif name == "Mirror":
                    self.symmetry = not self.symmetry
                elif name == "Save":
                    self._save()
                elif name == "Test":
                    self._test_play()
                elif name == "New":
                    self._new_map()
                elif name == "Undo":
                    self._undo()
                elif name == "Redo":
                    self._redo()
                break

    def _get_toolbar_buttons(self):
        """Return list of (name, pygame.Rect) for toolbar buttons."""
        buttons = []
        names = [
            "Terrain", "Erase", "Mineral", "Player TC", "AI TC", "Select",
            "|",
            "Grid", "Nav", "Mirror",
            "|",
            "Save", "Test", "New",
            "|",
            "Undo", "Redo",
        ]
        bw = 80
        bh = 32
        pad = 4
        x = 10
        y = self.map_height + 10
        for name in names:
            if name == "|":
                x += 10
                continue
            buttons.append((name, pygame.Rect(x, y, bw, bh)))
            x += bw + pad
        return buttons

    def _draw(self, screen, file_picker_open, file_picker_files, file_picker_scroll):
        """Draw the entire editor frame."""
        # Background
        screen.fill(MAP_COLOR)

        # Clip to map area
        map_clip = pygame.Rect(0, 0, self.width, self.map_height)
        screen.set_clip(map_clip)

        cx, cy = self.cam_x, self.cam_y

        # Grid
        if self.show_grid:
            # Vertical lines
            start_gx = int(cx) // SNAP * SNAP
            for gx in range(start_gx, int(cx + self.width) + SNAP, SNAP):
                sx = gx - cx
                pygame.draw.line(screen, GRID_COLOR, (sx, 0), (sx, self.map_height), 1)
            # Horizontal lines
            start_gy = int(cy) // SNAP * SNAP
            for gy in range(start_gy, int(cy + self.map_height) + SNAP, SNAP):
                sy = gy - cy
                pygame.draw.line(screen, GRID_COLOR, (0, sy), (self.width, sy), 1)

        # Buildable zone circles (semi-transparent)
        for tc_pos, color in [(self.player_tc, ZONE_COLOR_PLAYER), (self.ai_tc, ZONE_COLOR_AI)]:
            zone_surf = pygame.Surface((BUILDING_ZONE_TC_RADIUS * 2, BUILDING_ZONE_TC_RADIUS * 2), pygame.SRCALPHA)
            pygame.draw.circle(zone_surf, color, (BUILDING_ZONE_TC_RADIUS, BUILDING_ZONE_TC_RADIUS), BUILDING_ZONE_TC_RADIUS)
            sx = tc_pos[0] + TOWN_CENTER_SIZE[0] // 2 - BUILDING_ZONE_TC_RADIUS - cx
            sy = tc_pos[1] + TOWN_CENTER_SIZE[1] // 2 - BUILDING_ZONE_TC_RADIUS - cy
            screen.blit(zone_surf, (sx, sy))

        # Terrain rects
        for i, (rx, ry, rw, rh) in enumerate(self.terrain_rects):
            sx = rx - cx
            sy = ry - cy
            r = pygame.Rect(sx, sy, rw, rh)
            color = TERRAIN_COLOR
            if i == self.hovered_rect_idx:
                color = (180, 80, 40)  # highlight for erase
            pygame.draw.rect(screen, color, r)
            pygame.draw.rect(screen, TERRAIN_BORDER_COLOR, r, 2)

        # Nav overlay
        if self.show_nav:
            nav_surf = pygame.Surface((SNAP, SNAP), pygame.SRCALPHA)
            # Calculate visible grid range
            gx_start = max(0, int(cx) // SNAP)
            gy_start = max(0, int(cy) // SNAP)
            gx_end = min(GRID_W, int(cx + self.width) // SNAP + 2)
            gy_end = min(GRID_H, int(cy + self.map_height) // SNAP + 2)
            for gy in range(gy_start, gy_end):
                for gx in range(gx_start, gx_end):
                    val = self.nav_grid.get(gx, gy)
                    if val != WALKABLE:
                        nav_surf.fill(NAV_BLOCKED_COLOR)
                        screen.blit(nav_surf, (gx * SNAP - cx, gy * SNAP - cy))

        # Terrain drag preview
        if self.drawing and self.draw_start:
            mouse_pos = pygame.mouse.get_pos()
            mwx, mwy = self._screen_to_world(mouse_pos)
            ex, ey = self._snap(mwx), self._snap(mwy)
            sx_w, sy_w = self.draw_start
            x = min(sx_w, ex)
            y = min(sy_w, ey)
            w = abs(ex - sx_w)
            h = abs(ey - sy_w)
            if w > 0 and h > 0:
                preview = pygame.Surface((w, h), pygame.SRCALPHA)
                preview.fill(TERRAIN_PREVIEW_COLOR)
                screen.blit(preview, (x - cx, y - cy))
                pygame.draw.rect(screen, TERRAIN_BORDER_COLOR, pygame.Rect(x - cx, y - cy, w, h), 2)
                # Mirror preview
                if self.symmetry:
                    mx = WORLD_W - x - w
                    screen.blit(preview, (mx - cx, y - cy))
                    pygame.draw.rect(screen, TERRAIN_BORDER_COLOR, pygame.Rect(mx - cx, y - cy, w, h), 2)

        # TC positions
        tc_w, tc_h = TOWN_CENTER_SIZE
        for tc_pos, color, label in [
            (self.player_tc, PLAYER_TC_COLOR, "P"),
            (self.ai_tc, AI_TC_COLOR, "AI"),
        ]:
            r = pygame.Rect(tc_pos[0] - cx, tc_pos[1] - cy, tc_w, tc_h)
            pygame.draw.rect(screen, color, r)
            pygame.draw.rect(screen, (255, 255, 255), r, 2)
            txt = get_font(24).render(label, True, (255, 255, 255))
            screen.blit(txt, (r.centerx - txt.get_width() // 2, r.centery - txt.get_height() // 2))

        # Mineral nodes
        for off in self.player_minerals:
            mx, my = self._mineral_world_pos(self.player_tc, off)
            sx_m = int(mx - cx)
            sy_m = int(my - cy)
            pygame.draw.circle(screen, PLAYER_MINERAL_COLOR, (sx_m, sy_m), MINERAL_NODE_SIZE)
            pygame.draw.circle(screen, (255, 255, 255), (sx_m, sy_m), MINERAL_NODE_SIZE, 1)

        for off in self.ai_minerals:
            mx, my = self._mineral_world_pos(self.ai_tc, off)
            sx_m = int(mx - cx)
            sy_m = int(my - cy)
            pygame.draw.circle(screen, AI_MINERAL_COLOR, (sx_m, sy_m), MINERAL_NODE_SIZE)
            pygame.draw.circle(screen, (255, 255, 255), (sx_m, sy_m), MINERAL_NODE_SIZE, 1)

        # World border
        border_rect = pygame.Rect(-cx, -cy, WORLD_W, WORLD_H)
        pygame.draw.rect(screen, (200, 200, 200), border_rect, 2)

        # Reset clip
        screen.set_clip(None)

        # --- Toolbar ---
        toolbar_rect = pygame.Rect(0, self.map_height, self.width, HUD_HEIGHT)
        pygame.draw.rect(screen, TOOLBAR_BG, toolbar_rect)
        pygame.draw.line(screen, (80, 80, 80), (0, self.map_height), (self.width, self.map_height), 2)

        mouse_pos = pygame.mouse.get_pos()
        buttons = self._get_toolbar_buttons()

        # Tool-to-button name mapping for active highlighting
        tool_to_btn = {
            "terrain": "Terrain",
            "erase": "Erase",
            "mineral": "Mineral",
            "tc_player": "Player TC",
            "tc_ai": "AI TC",
            "select": "Select",
        }
        active_btn = tool_to_btn.get(self.current_tool, "")

        # Toggle button states
        toggle_states = {
            "Grid": self.show_grid,
            "Nav": self.show_nav,
            "Mirror": self.symmetry,
        }

        for name, rect in buttons:
            hovered = rect.collidepoint(mouse_pos)
            is_active = (name == active_btn) or toggle_states.get(name, False)
            if is_active:
                color = BUTTON_ACTIVE
            elif hovered:
                color = BUTTON_HOVER
            else:
                color = BUTTON_COLOR
            pygame.draw.rect(screen, color, rect, border_radius=4)
            pygame.draw.rect(screen, (120, 120, 120), rect, 1, border_radius=4)
            txt = get_font(20).render(name, True, BUTTON_TEXT_COLOR)
            screen.blit(txt, (rect.centerx - txt.get_width() // 2, rect.centery - txt.get_height() // 2))

        # Status line (below buttons)
        status_y = self.map_height + 50
        # Tool name
        tool_txt = get_font(22).render(f"Tool: {self.current_tool}", True, (200, 200, 200))
        screen.blit(tool_txt, (10, status_y))

        # Connectivity indicator
        conn_x = 220
        conn_color = (0, 200, 0) if self.connected else (200, 0, 0)
        pygame.draw.circle(screen, conn_color, (conn_x, status_y + 10), 8)
        conn_txt = get_font(22).render("Connected" if self.connected else "Disconnected", True, conn_color)
        screen.blit(conn_txt, (conn_x + 14, status_y))

        # Map name
        map_name = os.path.basename(self.filepath) if self.filepath else "(unsaved)"
        name_txt = get_font(22).render(f"Map: {map_name}", True, (200, 200, 200))
        screen.blit(name_txt, (conn_x + 180, status_y))

        # Symmetry indicator
        sym_txt = get_font(22).render(f"Symmetry: {'ON' if self.symmetry else 'OFF'}", True, (200, 200, 200))
        screen.blit(sym_txt, (conn_x + 450, status_y))

        # Terrain count
        count_txt = get_font(22).render(f"Rects: {len(self.terrain_rects)}", True, (200, 200, 200))
        screen.blit(count_txt, (conn_x + 630, status_y))

        # Mineral count
        min_txt = get_font(22).render(
            f"Minerals: P={len(self.player_minerals)} AI={len(self.ai_minerals)}",
            True, (200, 200, 200)
        )
        screen.blit(min_txt, (conn_x + 780, status_y))

        # Hotkey hints
        hint_y = self.map_height + 78
        hints = "T:Terrain  E:Erase  N:Mineral  1:PlayerTC  2:AITC  G:Grid  V:Nav  M:Mirror  Ctrl+S:Save  Ctrl+Z:Undo  Ctrl+Y:Redo  Ctrl+T:Test  Ctrl+N:New  Ctrl+L:Load"
        hint_txt = get_font(18).render(hints, True, (140, 140, 140))
        screen.blit(hint_txt, (10, hint_y))

        # Undo/redo count
        ur_txt = get_font(18).render(f"Undo: {len(self.undo_stack)}  Redo: {len(self.redo_stack)}", True, (140, 140, 140))
        screen.blit(ur_txt, (10, hint_y + 20))

        # --- Help overlay ---
        if self.show_help:
            self._draw_help(screen)

        # --- File picker overlay ---
        if file_picker_open:
            self._draw_file_picker(screen, file_picker_files, file_picker_scroll)

    def _draw_help(self, screen):
        """Draw help overlay with all controls."""
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))

        font = get_font(22)
        title_font = get_font(28)
        section_font = get_font(24)
        lh = 26  # line height

        panel_w, panel_h = 700, 620
        px = self.width // 2 - panel_w // 2
        py = self.height // 2 - panel_h // 2

        pygame.draw.rect(screen, (40, 40, 50), (px, py, panel_w, panel_h), border_radius=10)
        pygame.draw.rect(screen, (100, 140, 200), (px, py, panel_w, panel_h), 2, border_radius=10)

        y = py + 12
        title = title_font.render("Map Editor Help  (H to close)", True, (100, 180, 255))
        screen.blit(title, (px + panel_w // 2 - title.get_width() // 2, y))
        y += 40

        sections = [
            ("Tools", [
                ("T", "Terrain — click+drag to draw cliff rects"),
                ("E", "Erase — click on a terrain rect to delete"),
                ("N", "Mineral — left click to place, right click to remove"),
                ("1", "Player TC — click to set player start position"),
                ("2", "AI TC — click to set AI start position"),
                ("S", "Select — inspect objects"),
            ]),
            ("Toggles", [
                ("G", "Toggle grid lines (32px)"),
                ("V", "Toggle nav grid overlay (red = blocked)"),
                ("M", "Toggle mirror symmetry"),
                ("H", "Toggle this help screen"),
            ]),
            ("File Operations", [
                ("Ctrl+S", "Save map"),
                ("Ctrl+L", "Load map (file picker)"),
                ("Ctrl+N", "New blank map"),
                ("Ctrl+T", "Test play — save and launch game"),
                ("Ctrl+Z", "Undo"),
                ("Ctrl+Y", "Redo"),
            ]),
            ("Camera", [
                ("Arrow keys", "Scroll the viewport"),
                ("Mouse edges", "Scroll when cursor near screen edge"),
                ("ESC", "Exit editor"),
            ]),
        ]

        col1_x = px + 20
        col2_x = px + 140

        for section_name, entries in sections:
            sec = section_font.render(section_name, True, (200, 220, 255))
            screen.blit(sec, (col1_x, y))
            y += lh + 4
            for key, desc in entries:
                key_surf = font.render(key, True, (255, 220, 100))
                desc_surf = font.render(desc, True, (200, 200, 200))
                screen.blit(key_surf, (col1_x + 10, y))
                screen.blit(desc_surf, (col2_x, y))
                y += lh
            y += 8

    def _draw_file_picker(self, screen, files, scroll):
        """Draw file picker overlay."""
        # Dim background
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        screen.blit(overlay, (0, 0))

        picker_w = 400
        picker_x = self.width // 2 - picker_w // 2
        picker_y = 100
        row_h = 30
        picker_h = 40 + len(files) * row_h + 20

        # Background
        pygame.draw.rect(screen, (50, 50, 50), (picker_x, picker_y, picker_w, picker_h), border_radius=8)
        pygame.draw.rect(screen, (120, 120, 120), (picker_x, picker_y, picker_w, picker_h), 2, border_radius=8)

        # Title
        title = get_font(26).render("Load Map", True, (255, 255, 255))
        screen.blit(title, (picker_x + picker_w // 2 - title.get_width() // 2, picker_y + 8))

        # File entries
        mouse_pos = pygame.mouse.get_pos()
        for i, fpath in enumerate(files):
            ry = picker_y + 40 + i * row_h - scroll
            if ry < picker_y + 36 or ry > picker_y + picker_h - 10:
                continue
            fname = os.path.basename(fpath)
            entry_rect = pygame.Rect(picker_x + 10, ry, picker_w - 20, row_h - 2)
            hovered = entry_rect.collidepoint(mouse_pos)
            color = BUTTON_HOVER if hovered else (60, 60, 60)
            pygame.draw.rect(screen, color, entry_rect, border_radius=4)
            txt = get_font(22).render(fname, True, (220, 220, 220))
            screen.blit(txt, (entry_rect.x + 8, entry_rect.y + 4))

        if not files:
            no_txt = get_font(22).render("No maps found in maps/", True, (180, 180, 180))
            screen.blit(no_txt, (picker_x + 20, picker_y + 50))


def run_editor(filepath=None):
    """Launch the map editor. If filepath given, load that map."""
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    pygame.display.set_caption("Map Editor")
    clock = pygame.time.Clock()

    editor = MapEditor(filepath)
    editor.run(screen, clock)
    pygame.quit()


if __name__ == "__main__":
    fp = None
    if len(sys.argv) > 1:
        fp = sys.argv[1]
    run_editor(fp)
