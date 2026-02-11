import atexit
import pygame
import sys
import datetime
from settings import (
    WIDTH, HEIGHT, FPS, MAP_COLOR, MAP_HEIGHT, DRAG_BOX_COLOR,
    BARRACKS_SIZE, FACTORY_SIZE, TOWN_CENTER_SIZE, TOWER_SIZE,
    WORLD_W, WORLD_H, SCROLL_SPEED, SCROLL_EDGE,
)
from game_state import GameState
from hud import HUD
from minimap import Minimap
from units import Soldier, Tank, Worker, Yanuses
from buildings import Barracks, Factory, TownCenter, DefenseTower
from disasters import DisasterManager
from player_ai import PlayerAI
from replay import (
    ReplayRecorder, ReplayPlayer, ReplayUnit, ReplayBuilding,
    ReplayNode, ReplayAIPlayer, ReplayState,
)


class MoveMarker:
    """Visual marker shown where a move command is issued (world coords)."""
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.timer = 0.0
        self.duration = 0.6

    @property
    def alive(self):
        return self.timer < self.duration

    def update(self, dt):
        self.timer += dt

    def draw(self, surface, cam_x, cam_y):
        sx = self.x - cam_x
        sy = self.y - cam_y
        progress = self.timer / self.duration
        alpha = int(255 * (1 - progress))
        radius = int(8 + 12 * progress)
        color = (0, 255, 100)
        s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*color, alpha), (radius, radius), radius, 2)
        pygame.draw.line(s, (*color, alpha), (radius - 4, radius), (radius + 4, radius), 1)
        pygame.draw.line(s, (*color, alpha), (radius, radius - 4), (radius, radius + 4), 1)
        surface.blit(s, (sx - radius, sy - radius))


class FloatingText:
    """Floating text that rises and fades out (world coords)."""
    def __init__(self, x, y, text, color=(255, 215, 0)):
        self.x = x
        self.y = y
        self.text = text
        self.color = color
        self.timer = 0.0
        self.duration = 1.0

    @property
    def alive(self):
        return self.timer < self.duration

    def update(self, dt):
        self.timer += dt
        self.y -= 30 * dt

    def draw(self, surface, cam_x, cam_y):
        progress = self.timer / self.duration
        alpha = int(255 * (1 - progress))
        font = pygame.font.SysFont(None, 22)
        text_surf = font.render(self.text, True, self.color)
        text_surf.set_alpha(alpha)
        surface.blit(text_surf, (int(self.x - cam_x), int(self.y - cam_y)))


def _write_debug_log(state):
    """Write full game state to dbug.log."""
    lines = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"=== DEBUG LOG - {now} ===")
    lines.append("")

    # Game status
    lines.append(f"Game Over: {state.game_over}  Result: {state.game_result}")
    lines.append(f"Resources: {state.resource_manager.amount:.1f}")
    lines.append(f"Placement Mode: {state.placement_mode}")
    lines.append("")

    # Wave info
    wm = state.wave_manager
    lines.append(f"--- WAVES ---")
    lines.append(f"Current Wave: {wm.current_wave}  Completed: {wm.waves_completed}")
    lines.append(f"Wave Active: {wm.wave_active}  Wave Timer: {wm.wave_timer:.1f}s")
    lines.append(f"Enemies Alive: {len(wm.enemies)}")
    lines.append("")

    # Buildings
    lines.append(f"--- BUILDINGS ({len(state.buildings)}) ---")
    for i, b in enumerate(state.buildings):
        queue_len = len(b.production_queue)
        lines.append(f"  [{i}] {b.label} at ({b.x}, {b.y}) HP={b.hp}/{b.max_hp} "
                      f"Queue={queue_len} Selected={b.selected}")
    lines.append("")

    # Player units
    lines.append(f"--- PLAYER UNITS ({len(state.units)}) ---")
    for i, u in enumerate(state.units):
        wp = len(u.waypoints)
        base = (f"  [{i}] {u.name} at ({u.x:.0f}, {u.y:.0f}) HP={u.hp}/{u.max_hp} "
                f"Speed={u.speed} WP={wp} Attacking={u.attacking} Stuck={u.stuck} "
                f"Selected={u.selected}")
        if isinstance(u, Worker):
            base += f" State={u.state} Carry={u.carry_amount}"
        if u.attack_range > 0:
            target_info = "None"
            if u.target_enemy:
                t = u.target_enemy
                target_info = f"{getattr(t, 'name', 'Building')} HP={t.hp}"
            base += f" Dmg={u.damage} Rate={u.fire_rate} Range={u.attack_range} Target={target_info}"
        lines.append(base)
    lines.append("")

    # Enemies
    lines.append(f"--- ENEMIES ({len(wm.enemies)}) ---")
    for i, e in enumerate(wm.enemies):
        wp = len(e.waypoints)
        target_info = "None"
        if e.target_enemy:
            t = e.target_enemy
            target_info = f"{getattr(t, 'name', 'Building')} HP={t.hp}"
        lines.append(f"  [{i}] {e.name} at ({e.x:.0f}, {e.y:.0f}) HP={e.hp}/{e.max_hp} "
                      f"WP={wp} Attacking={e.attacking} Stuck={e.stuck} Target={target_info}")
    lines.append("")

    # Mineral nodes
    lines.append(f"--- MINERAL NODES ({len(state.mineral_nodes)}) ---")
    for i, n in enumerate(state.mineral_nodes):
        miner = n.mining_worker
        miner_info = f"Worker at ({miner.x:.0f}, {miner.y:.0f})" if miner else "None"
        lines.append(f"  [{i}] ({n.x}, {n.y}) Remaining={n.remaining}/{n.max_amount} "
                      f"Depleted={n.depleted} Mining={miner_info}")
    lines.append("")
    lines.append("=== END DEBUG LOG ===")

    with open("dbug.log", "w") as f:
        f.write("\n".join(lines))


def _screen_to_world(screen_pos, cam_x, cam_y):
    """Convert screen coordinates to world coordinates."""
    return (screen_pos[0] + cam_x, screen_pos[1] + cam_y)


def main():
    # Check for replay mode
    replay_file = None
    for i, arg in enumerate(sys.argv):
        if arg == "--replay" and i + 1 < len(sys.argv):
            replay_file = sys.argv[i + 1]
            break
    if replay_file:
        _replay_main(replay_file)
        return

    playforme = "--playforme" in sys.argv

    # Parse AI profile selection
    ai_profile_name = "basic"
    for i, arg in enumerate(sys.argv):
        if arg == "--ai" and i + 1 < len(sys.argv):
            ai_profile_name = sys.argv[i + 1]
            break

    from ai_profiles import load_profile
    ai_profile = load_profile(ai_profile_name)

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("GameOne - Simple RTS" + (" [SPECTATOR]" if playforme else ""))
    clock = pygame.time.Clock()

    # Load sprite assets (must happen after pygame.init())
    Soldier.load_assets()
    Tank.load_assets()
    Worker.load_assets()
    Yanuses.load_assets()
    Barracks.load_assets()
    Factory.load_assets()
    TownCenter.load_assets()
    DefenseTower.load_assets()

    state = GameState(ai_profile=ai_profile)
    hud = HUD()
    minimap = Minimap()
    disaster_mgr = DisasterManager(WORLD_W, WORLD_H)
    player_ai = PlayerAI() if playforme else None

    # Camera position (top-left corner of the viewport in world coords)
    camera_x = 0.0
    camera_y = 0.0

    dragging = False
    drag_start = None       # screen coords of drag start
    drag_start_world = None  # world coords of drag start
    drag_rect = None         # world-space rect for selection
    drag_rect_screen = None  # screen-space rect for drawing
    paused = False

    # UX state
    move_markers = []
    floating_texts = []
    resource_flash_timer = 0.0  # > 0 means resource counter is flashing
    last_resource_amount = state.resource_manager.amount

    # Scroll direction flags (for keyboard scrolling)
    scroll_left = False
    scroll_right = False
    scroll_up = False
    scroll_down = False

    # Replay recorder (always active, atexit ensures save on any exit)
    recorder = ReplayRecorder()
    atexit.register(recorder.save)

    playforme_timer = 0.0  # auto-exit timer for playforme mode

    running = True
    try:
     while running:
        dt = clock.tick(FPS) / 1000.0
        sim_dt = dt * 20 if playforme else dt * 2

        # Auto-exit playforme after game over (give 2s for final frames)
        if playforme and state.game_over:
            playforme_timer += dt
            if playforme_timer > 2.0:
                running = False
                continue

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            # When game is over, only allow quit and ESC
            if state.game_over:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                continue

            # Debug pause: P to pause + write log, ESC to resume
            if event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                paused = True
                _write_debug_log(state)
                continue
            if paused:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    paused = False
                continue

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if state.placement_mode:
                        state.placement_mode = None
                    else:
                        state.deselect_all()
                elif event.key == pygame.K_b:
                    state.placement_mode = "barracks"
                elif event.key == pygame.K_f:
                    state.placement_mode = "factory"
                elif event.key == pygame.K_t:
                    state.placement_mode = "towncenter"
                elif event.key == pygame.K_d:
                    state.placement_mode = "tower"
                # Arrow key scrolling
                elif event.key == pygame.K_LEFT:
                    scroll_left = True
                elif event.key == pygame.K_RIGHT:
                    scroll_right = True
                elif event.key == pygame.K_UP:
                    scroll_up = True
                elif event.key == pygame.K_DOWN:
                    scroll_down = True

            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_LEFT:
                    scroll_left = False
                elif event.key == pygame.K_RIGHT:
                    scroll_right = False
                elif event.key == pygame.K_UP:
                    scroll_up = False
                elif event.key == pygame.K_DOWN:
                    scroll_down = False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click
                    screen_pos = event.pos

                    # Check minimap click — move viewport
                    mini_result = minimap.handle_click(screen_pos)
                    if mini_result is not None:
                        camera_x = max(0, min(mini_result[0], WORLD_W - WIDTH))
                        camera_y = max(0, min(mini_result[1], WORLD_H - MAP_HEIGHT))
                        continue

                    # Check HUD first (screen coords)
                    if hud.is_in_hud(screen_pos):
                        result = hud.handle_click(screen_pos, state)
                        if result == "insufficient_funds":
                            resource_flash_timer = 0.5
                        continue

                    # Convert to world coords for map interactions
                    world_pos = _screen_to_world(screen_pos, camera_x, camera_y)

                    # Placement mode
                    if state.placement_mode:
                        size = _get_placement_size(state.placement_mode)
                        bx = world_pos[0] - size[0] // 2
                        by = world_pos[1] - size[1] // 2
                        if not state.place_building((bx, by)):
                            resource_flash_timer = 0.5
                        continue

                    # Start drag select
                    dragging = True
                    drag_start = screen_pos
                    drag_start_world = world_pos
                    drag_rect = None
                    drag_rect_screen = None

                elif event.button == 3:  # Right click
                    screen_pos = event.pos
                    if hud.is_in_hud(screen_pos) or not state.selected_units:
                        continue

                    # Convert to world coords
                    world_pos = _screen_to_world(screen_pos, camera_x, camera_y)
                    mods = pygame.key.get_mods()

                    # Check if clicked on a mineral node (world coords)
                    node = state.get_mineral_node_at(world_pos)
                    if node:
                        # Send workers to mine, move non-workers normally
                        has_workers = any(isinstance(u, Worker) for u in state.selected_units)
                        if has_workers:
                            state.command_mine(node)
                            # Move non-workers to the node area
                            for u in state.selected_units:
                                if not isinstance(u, Worker):
                                    u.set_target(world_pos)
                        else:
                            state.command_move(world_pos)
                        move_markers.append(MoveMarker(world_pos[0], world_pos[1]))
                    elif mods & pygame.KMOD_SHIFT:
                        state.command_queue_waypoint(world_pos)
                        move_markers.append(MoveMarker(world_pos[0], world_pos[1]))
                    else:
                        state.command_move(world_pos)
                        move_markers.append(MoveMarker(world_pos[0], world_pos[1]))

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1 and dragging:
                    dragging = False
                    screen_pos = event.pos
                    world_pos = _screen_to_world(screen_pos, camera_x, camera_y)

                    if drag_rect and (drag_rect.w > 5 or drag_rect.h > 5):
                        # Box select (drag_rect is in world coords)
                        units = state.get_units_in_rect(drag_rect)
                        if units:
                            state.select_units(units)
                        else:
                            state.deselect_all()
                    else:
                        # Single click select (use world coords)
                        click_world = drag_start_world if drag_start_world else world_pos
                        unit = state.get_unit_at(click_world)
                        if unit:
                            state.select_unit(unit)
                        else:
                            building = state.get_building_at(click_world)
                            if building:
                                state.select_building(building)
                            else:
                                state.deselect_all()

                    drag_start = None
                    drag_start_world = None
                    drag_rect = None
                    drag_rect_screen = None

            elif event.type == pygame.MOUSEMOTION:
                # Minimap drag: hold left button and drag on minimap to pan
                if pygame.mouse.get_pressed()[0] and minimap.rect.collidepoint(event.pos):
                    mini_result = minimap.handle_click(event.pos)
                    if mini_result is not None:
                        camera_x = max(0, min(mini_result[0], WORLD_W - WIDTH))
                        camera_y = max(0, min(mini_result[1], WORLD_H - MAP_HEIGHT))
                    continue
                if dragging and drag_start_world:
                    # Build drag rect in world coords
                    mx_w, my_w = _screen_to_world(event.pos, camera_x, camera_y)
                    sx_w, sy_w = drag_start_world
                    x = min(sx_w, mx_w)
                    y = min(sy_w, my_w)
                    w = abs(mx_w - sx_w)
                    h = abs(my_w - sy_w)
                    drag_rect = pygame.Rect(int(x), int(y), int(w), int(h))
                    # Also build screen-space rect for drawing
                    smx, smy = event.pos
                    ssx, ssy = drag_start
                    sx = min(ssx, smx)
                    sy = min(ssy, smy)
                    sw = abs(smx - ssx)
                    sh = abs(smy - ssy)
                    drag_rect_screen = pygame.Rect(sx, sy, sw, sh)

        # --- Camera scrolling ---
        if not paused and not state.game_over:
            # Mouse-edge scrolling (only when mouse is in map area)
            mouse_x, mouse_y = pygame.mouse.get_pos()
            if mouse_y < MAP_HEIGHT:
                if mouse_x < SCROLL_EDGE:
                    camera_x -= SCROLL_SPEED * dt
                elif mouse_x > WIDTH - SCROLL_EDGE:
                    camera_x += SCROLL_SPEED * dt
                if mouse_y < SCROLL_EDGE:
                    camera_y -= SCROLL_SPEED * dt
                elif mouse_y > MAP_HEIGHT - SCROLL_EDGE:
                    camera_y += SCROLL_SPEED * dt

            # Keyboard scrolling
            if scroll_left:
                camera_x -= SCROLL_SPEED * dt
            if scroll_right:
                camera_x += SCROLL_SPEED * dt
            if scroll_up:
                camera_y -= SCROLL_SPEED * dt
            if scroll_down:
                camera_y += SCROLL_SPEED * dt

            # Clamp camera to world bounds
            camera_x = max(0, min(camera_x, WORLD_W - WIDTH))
            camera_y = max(0, min(camera_y, WORLD_H - MAP_HEIGHT))

        # Integer camera offset for drawing (apply earthquake shake)
        shake_x, shake_y = disaster_mgr.shake_offset
        cam_x = int(camera_x) + shake_x
        cam_y = int(camera_y) + shake_y

        # Update
        if not paused:
            state.update(sim_dt)
            # Update player AI (spectator mode)
            if player_ai is not None:
                player_ai.update(sim_dt, state, state.wave_manager.enemies, state.ai_player)
            # Update disasters (affects all units and buildings on the map)
            all_units_for_disaster = state.units + state.wave_manager.enemies + state.ai_player.units
            all_buildings_for_disaster = state.buildings + state.ai_player.buildings
            disaster_mgr.update(sim_dt, all_units_for_disaster, all_buildings_for_disaster)
            recorder.capture(dt, state)

        # Update UX effects
        for m in move_markers:
            m.update(dt)
        move_markers = [m for m in move_markers if m.alive]
        for ft in floating_texts:
            ft.update(dt)
        floating_texts = [ft for ft in floating_texts if ft.alive]
        if resource_flash_timer > 0:
            resource_flash_timer = max(0, resource_flash_timer - dt)

        # Detect resource deposits (floating text)
        current_amount = state.resource_manager.amount
        if current_amount > last_resource_amount:
            gained = int(current_amount - last_resource_amount)
            # Find a worker that just deposited (state == "moving_to_mine" means just finished returning)
            for u in state.units:
                if isinstance(u, Worker) and u.state == "moving_to_mine":
                    floating_texts.append(FloatingText(u.x, u.y - 20, f"+{gained}"))
                    break
            else:
                # Fallback: show near HUD resource area (use world coords at current camera)
                floating_texts.append(FloatingText(cam_x + 80, cam_y + MAP_HEIGHT - 10, f"+{gained}"))
        last_resource_amount = current_amount

        # --- Draw ---
        screen.fill(MAP_COLOR)

        # Draw grid lines for visual reference (only visible ones)
        grid_start_x = (cam_x // 64) * 64
        grid_start_y = (cam_y // 64) * 64
        for gx in range(int(grid_start_x), cam_x + WIDTH + 64, 64):
            sx = gx - cam_x
            if 0 <= sx <= WIDTH:
                pygame.draw.line(screen, (30, 75, 30), (sx, 0), (sx, MAP_HEIGHT), 1)
        for gy in range(int(grid_start_y), cam_y + MAP_HEIGHT + 64, 64):
            sy = gy - cam_y
            if 0 <= sy <= MAP_HEIGHT:
                pygame.draw.line(screen, (30, 75, 30), (0, sy), (WIDTH, sy), 1)

        # Helper to check if a world-space rect is visible on screen
        visible_rect = pygame.Rect(cam_x - 100, cam_y - 100, WIDTH + 200, MAP_HEIGHT + 200)

        # Draw mineral nodes (with camera offset)
        for node in state.mineral_nodes:
            if visible_rect.collidepoint(node.x, node.y):
                _draw_mineral_node_offset(screen, node, cam_x, cam_y)

        # Draw buildings (with camera offset)
        for building in state.buildings:
            if visible_rect.colliderect(building.rect):
                _draw_building_offset(screen, building, cam_x, cam_y)

        # Draw units (with camera offset)
        for unit in state.units:
            if visible_rect.collidepoint(int(unit.x), int(unit.y)):
                _draw_unit_offset(screen, unit, cam_x, cam_y)
            # Draw attack line when unit is firing
            if unit.attacking and unit.target_enemy:
                t = unit.target_enemy
                if hasattr(t, 'size'):
                    tx, ty = int(t.x) - cam_x, int(t.y) - cam_y
                else:
                    tx, ty = t.x + t.w // 2 - cam_x, t.y + t.h // 2 - cam_y
                pygame.draw.line(screen, (255, 255, 0),
                                 (int(unit.x) - cam_x, int(unit.y) - cam_y), (tx, ty), 1)

        # Draw AI player (buildings, units, mineral nodes) with camera offset
        _draw_ai_player_offset(screen, state.ai_player, cam_x, cam_y, visible_rect)

        # Draw enemies (with camera offset)
        for enemy in state.wave_manager.enemies:
            if visible_rect.collidepoint(int(enemy.x), int(enemy.y)):
                _draw_unit_offset(screen, enemy, cam_x, cam_y)
            # Draw attack line when enemy is firing
            if enemy.attacking and enemy.target_enemy:
                t = enemy.target_enemy
                if hasattr(t, 'size'):
                    tx, ty = int(t.x) - cam_x, int(t.y) - cam_y
                else:
                    tx, ty = t.x + t.w // 2 - cam_x, t.y + t.h // 2 - cam_y
                pygame.draw.line(screen, (255, 80, 80),
                                 (int(enemy.x) - cam_x, int(enemy.y) - cam_y), (tx, ty), 1)

        # Draw disaster effects (with camera offset)
        disaster_mgr.draw(screen, cam_x, cam_y)

        # Draw placement ghost (green=valid, red=invalid) — follows mouse in screen space
        if state.placement_mode:
            mx, my = pygame.mouse.get_pos()
            # World position of the ghost
            world_mx, world_my = _screen_to_world((mx, my), camera_x, camera_y)
            size = _get_placement_size(state.placement_mode)
            sprite = _get_placement_sprite(state.placement_mode)
            # Ghost rect in world coords for validation
            ghost_rect_world = pygame.Rect(
                world_mx - size[0] // 2, world_my - size[1] // 2, size[0], size[1])
            valid = _is_placement_valid(ghost_rect_world, state)
            ghost_color = (0, 255, 0) if valid else (255, 50, 50)
            # Draw at screen position
            ghost_rect_screen = pygame.Rect(mx - size[0] // 2, my - size[1] // 2, size[0], size[1])
            if sprite:
                ghost_surf = sprite.copy()
                ghost_surf.set_alpha(140)
                if not valid:
                    red_tint = pygame.Surface(ghost_surf.get_size(), pygame.SRCALPHA)
                    red_tint.fill((255, 0, 0, 80))
                    ghost_surf.blit(red_tint, (0, 0))
                screen.blit(ghost_surf, ghost_rect_screen.topleft)
            pygame.draw.rect(screen, ghost_color, ghost_rect_screen, 2)

        # Draw drag selection box (screen coords)
        if dragging and drag_rect_screen:
            pygame.draw.rect(screen, DRAG_BOX_COLOR, drag_rect_screen, 1)

        # Draw waypoint paths for selected units (with camera offset)
        for unit in state.selected_units:
            if unit.waypoints:
                points = [(int(unit.x) - cam_x, int(unit.y) - cam_y)] + \
                         [(int(wx) - cam_x, int(wy) - cam_y) for wx, wy in unit.waypoints]
                if len(points) >= 2:
                    pygame.draw.lines(screen, (255, 255, 0), False, points, 1)
                for wx, wy in unit.waypoints:
                    pygame.draw.circle(screen, (255, 255, 0),
                                       (int(wx) - cam_x, int(wy) - cam_y), 3, 1)

        # Draw move-order markers (world coords, offset by camera)
        for marker in move_markers:
            marker.draw(screen, cam_x, cam_y)

        # Draw floating texts (world coords, offset by camera)
        for ft in floating_texts:
            ft.draw(screen, cam_x, cam_y)

        # Draw unit count badge near cursor when multiple units selected (screen coords)
        if len(state.selected_units) > 1:
            cmx, cmy = pygame.mouse.get_pos()
            badge_font = pygame.font.SysFont(None, 18)
            badge_text = badge_font.render(str(len(state.selected_units)), True, (255, 255, 255))
            badge_w = badge_text.get_width() + 8
            badge_h = badge_text.get_height() + 4
            badge_rect = pygame.Rect(cmx + 14, cmy - 2, badge_w, badge_h)
            pygame.draw.rect(screen, (0, 120, 0), badge_rect, border_radius=3)
            pygame.draw.rect(screen, (0, 200, 0), badge_rect, 1, border_radius=3)
            screen.blit(badge_text, (badge_rect.x + 4, badge_rect.y + 2))

        # Draw building HP on hover (convert mouse to world coords for hit test)
        hover_screen = pygame.mouse.get_pos()
        hover_world = _screen_to_world(hover_screen, camera_x, camera_y)
        for building in state.buildings:
            if building.rect.collidepoint(hover_world):
                hp_font = pygame.font.SysFont(None, 20)
                hp_text = hp_font.render(f"HP: {building.hp}/{building.max_hp}", True, (255, 255, 255))
                hp_bg = pygame.Surface((hp_text.get_width() + 6, hp_text.get_height() + 4), pygame.SRCALPHA)
                hp_bg.fill((0, 0, 0, 160))
                screen.blit(hp_bg, (hover_screen[0] + 10, hover_screen[1] - 20))
                screen.blit(hp_text, (hover_screen[0] + 13, hover_screen[1] - 18))
                break

        # Draw HUD (fixed screen position, no camera offset)
        hud.draw(screen, state, resource_flash_timer)

        # Draw minimap (fixed screen position, pass camera position)
        minimap.draw(screen, state, camera_x, camera_y)

        # Paused overlay
        if paused:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 120))
            screen.blit(overlay, (0, 0))
            big_font = pygame.font.SysFont(None, 72)
            small_font = pygame.font.SysFont(None, 32)
            text = big_font.render("PAUSED", True, (255, 255, 100))
            text_rect = text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30))
            screen.blit(text, text_rect)
            sub = small_font.render("dbug.log written  |  Press ESC to resume", True, (200, 200, 200))
            sub_rect = sub.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 30))
            screen.blit(sub, sub_rect)

        # Game over overlay
        if state.game_over:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            screen.blit(overlay, (0, 0))
            big_font = pygame.font.SysFont(None, 72)
            small_font = pygame.font.SysFont(None, 32)
            if state.game_result == "victory":
                text = big_font.render("VICTORY!", True, (0, 255, 100))
            else:
                text = big_font.render("DEFEAT", True, (255, 60, 60))
            text_rect = text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30))
            screen.blit(text, text_rect)
            sub = small_font.render("Press ESC to quit", True, (200, 200, 200))
            sub_rect = sub.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 30))
            screen.blit(sub, sub_rect)

        pygame.display.flip()
    finally:
        recorder.save()

    pygame.quit()
    sys.exit()


# --- Camera-offset drawing helpers ---

def _draw_mineral_node_offset(surface, node, cam_x, cam_y):
    """Draw a mineral node with camera offset."""
    from settings import MINERAL_NODE_SIZE, MINERAL_NODE_COLOR

    if node.depleted:
        color = (80, 80, 80)
        alpha = 100
    else:
        color = MINERAL_NODE_COLOR
        alpha = 255

    cx, cy = node.x - cam_x, node.y - cam_y
    s = MINERAL_NODE_SIZE
    points = [
        (cx, cy - s),
        (cx + s, cy),
        (cx, cy + s),
        (cx - s, cy),
    ]

    if node.depleted:
        surf = pygame.Surface((s * 2, s * 2), pygame.SRCALPHA)
        shifted = [(px - cx + s, py - cy + s) for px, py in points]
        pygame.draw.polygon(surf, (*color, alpha), shifted)
        surface.blit(surf, (cx - s, cy - s))
    else:
        pygame.draw.polygon(surface, color, points)
        highlight = [(cx, cy - s + 3), (cx + s - 3, cy), (cx, cy - 2)]
        pygame.draw.polygon(surface, (130, 200, 255), highlight)

    font = pygame.font.SysFont(None, 16)
    label = font.render(str(node.remaining), True, (255, 255, 255))
    label_rect = label.get_rect(center=(cx, cy + s + 10))
    surface.blit(label, label_rect)


def _draw_building_offset(surface, building, cam_x, cam_y):
    """Draw a building with camera offset."""
    import math as _math
    from settings import SELECT_COLOR, HEALTH_BAR_BG
    ox = building.x - cam_x
    oy = building.y - cam_y

    # DefenseTower has special drawing (cannon barrel, range circle)
    if isinstance(building, DefenseTower):
        cx_t = ox + building.w // 2
        cy_t = oy + building.h // 2
        if building.sprite:
            surface.blit(building.sprite, (ox, oy))
        else:
            # Fallback: grey square base
            pygame.draw.rect(surface, (120, 120, 130), (ox, oy, building.w, building.h))
            pygame.draw.rect(surface, (80, 80, 90), (ox, oy, building.w, building.h), 2)
            # Cannon barrel
            if building.attacking and building.target_enemy:
                tx = building.target_enemy.x - cam_x
                ty = building.target_enemy.y - cam_y
                angle = _math.atan2(ty - cy_t, tx - cx_t)
            else:
                angle = -_math.pi / 2
            barrel_len = 20
            bx_t = cx_t + _math.cos(angle) * barrel_len
            by_t = cy_t + _math.sin(angle) * barrel_len
            pygame.draw.line(surface, (60, 60, 70), (int(cx_t), int(cy_t)), (int(bx_t), int(by_t)), 4)
            pygame.draw.circle(surface, (90, 90, 100), (int(cx_t), int(cy_t)), 6)
        if building.selected:
            r = pygame.Rect(ox, oy, building.w, building.h)
            pygame.draw.rect(surface, SELECT_COLOR, r.inflate(6, 6), 2)
            # Range circle
            range_surf = pygame.Surface((building.attack_range * 2, building.attack_range * 2), pygame.SRCALPHA)
            pygame.draw.circle(range_surf, (100, 100, 140, 80),
                               (building.attack_range, building.attack_range), building.attack_range, 1)
            surface.blit(range_surf, (int(cx_t - building.attack_range), int(cy_t - building.attack_range)))
        # Attack line
        if building.attacking and building.target_enemy:
            t = building.target_enemy
            if hasattr(t, 'size'):
                tx, ty = int(t.x) - cam_x, int(t.y) - cam_y
            else:
                tx, ty = t.x + t.w // 2 - cam_x, t.y + t.h // 2 - cam_y
            pygame.draw.line(surface, (255, 200, 50), (int(cx_t), int(cy_t)), (int(tx), int(ty)), 2)
        # Health bar
        bar_w = building.w
        bar_h = 4
        bx, by = ox, oy - 8
        pygame.draw.rect(surface, HEALTH_BAR_BG, (bx, by, bar_w, bar_h))
        fill_w = int(bar_w * (building.hp / building.max_hp))
        hp_ratio = building.hp / building.max_hp
        if hp_ratio > 0.5:
            bar_color = (0, 200, 0)
        elif hp_ratio > 0.25:
            bar_color = (255, 200, 0)
        else:
            bar_color = (255, 50, 50)
        pygame.draw.rect(surface, bar_color, (bx, by, fill_w, bar_h))
        # Label
        font = pygame.font.SysFont(None, 18)
        label = font.render(building.label, True, (255, 255, 255))
        label_rect = label.get_rect(center=(int(cx_t), oy - 16))
        surface.blit(label, label_rect)
        return

    if building.sprite:
        surface.blit(building.sprite, (ox, oy))
    if building.selected:
        r = pygame.Rect(ox, oy, building.w, building.h)
        pygame.draw.rect(surface, SELECT_COLOR, r.inflate(6, 6), 2)
    # Health bar
    bar_w = building.w
    bar_h = 4
    bx, by = ox, oy - 8
    pygame.draw.rect(surface, HEALTH_BAR_BG, (bx, by, bar_w, bar_h))
    fill_w = int(bar_w * (building.hp / building.max_hp))
    hp_ratio = building.hp / building.max_hp
    if hp_ratio > 0.5:
        bar_color = (0, 200, 0)
    elif hp_ratio > 0.25:
        bar_color = (255, 200, 0)
    else:
        bar_color = (255, 50, 50)
    pygame.draw.rect(surface, bar_color, (bx, by, fill_w, bar_h))
    # Label
    font = pygame.font.SysFont(None, 18)
    label = font.render(building.label, True, (255, 255, 255))
    label_rect = label.get_rect(center=(ox + building.w // 2, oy - 16))
    surface.blit(label, label_rect)
    # Production bar
    if building.production_queue:
        prog_y = oy + building.h + 2
        pygame.draw.rect(surface, (60, 60, 60), (ox, prog_y, building.w, 4))
        pygame.draw.rect(surface, (0, 180, 255),
                         (ox, prog_y, int(building.w * building.production_progress), 4))


def _draw_unit_offset(surface, unit, cam_x, cam_y):
    """Draw a unit with camera offset."""
    from settings import SELECT_COLOR, HEALTH_BAR_BG
    sx = int(unit.x) - cam_x
    sy = int(unit.y) - cam_y

    if unit.sprite:
        r = unit.sprite.get_rect(center=(sx, sy))
        surface.blit(unit.sprite, r)

    # Selection highlight
    if unit.selected:
        sel_rect = pygame.Rect(sx - unit.size - 2, sy - unit.size - 2,
                               unit.size * 2 + 4, unit.size * 2 + 4)
        pygame.draw.rect(surface, SELECT_COLOR, sel_rect, 1)

    # Health bar
    bar_w = unit.size * 2
    bar_h = 3
    bx = sx - unit.size
    by = sy - unit.size - 6
    pygame.draw.rect(surface, HEALTH_BAR_BG, (bx, by, bar_w, bar_h))
    fill_w = int(bar_w * (unit.hp / unit.max_hp))
    hp_ratio = unit.hp / unit.max_hp
    if hp_ratio > 0.5:
        bar_color = (0, 200, 0)
    elif hp_ratio > 0.25:
        bar_color = (255, 200, 0)
    else:
        bar_color = (255, 50, 50)
    pygame.draw.rect(surface, bar_color, (bx, by, fill_w, bar_h))

    # Worker-specific drawing
    if isinstance(unit, Worker):
        if unit.carry_amount > 0:
            pygame.draw.circle(surface, (255, 215, 0),
                               (sx + unit.size, sy - unit.size), 4)
        if unit.selected and unit.state != "idle":
            font = pygame.font.SysFont(None, 14)
            state_text = unit.state.replace("_", " ")
            label = font.render(state_text, True, (200, 200, 200))
            surface.blit(label, (sx - unit.size, sy + unit.size + 2))


def _draw_ai_player_offset(surface, ai_player, cam_x, cam_y, visible_rect):
    """Draw all AI player entities with camera offset and orange tint."""
    ai_player._ensure_tinted_sprites()

    # AI mineral nodes
    for node in ai_player.mineral_nodes:
        if visible_rect.collidepoint(node.x, node.y):
            _draw_mineral_node_offset(surface, node, cam_x, cam_y)

    # AI buildings
    for building in ai_player.buildings:
        if not visible_rect.colliderect(building.rect):
            continue
        ox = building.x - cam_x
        oy = building.y - cam_y
        tinted = ai_player._get_tinted_sprite(building)
        if tinted:
            surface.blit(tinted, (ox, oy))
        else:
            _draw_building_offset(surface, building, cam_x, cam_y)
            continue
        # Health bar and label
        if building.selected:
            r = pygame.Rect(ox, oy, building.w, building.h)
            pygame.draw.rect(surface, (255, 120, 0), r.inflate(6, 6), 2)
        bar_w = building.w
        bar_h = 4
        bx, by = ox, oy - 8
        pygame.draw.rect(surface, (80, 0, 0), (bx, by, bar_w, bar_h))
        fill_w = int(bar_w * (building.hp / building.max_hp))
        pygame.draw.rect(surface, (255, 140, 0), (bx, by, fill_w, bar_h))
        font = pygame.font.SysFont(None, 18)
        label = font.render(f"AI {building.label}", True, (255, 180, 100))
        label_rect = label.get_rect(center=(ox + building.w // 2, oy - 16))
        surface.blit(label, label_rect)
        if building.production_queue:
            prog_y = oy + building.h + 2
            pygame.draw.rect(surface, (60, 60, 60), (ox, prog_y, building.w, 4))
            prog = building.production_progress
            pygame.draw.rect(surface, (255, 140, 0),
                             (ox, prog_y, int(building.w * prog), 4))

    # AI units
    for unit in ai_player.units:
        if not visible_rect.collidepoint(int(unit.x), int(unit.y)):
            continue
        sx = int(unit.x) - cam_x
        sy = int(unit.y) - cam_y
        tinted = ai_player._get_tinted_sprite(unit)
        if tinted:
            r = tinted.get_rect(center=(sx, sy))
            surface.blit(tinted, r)
        else:
            _draw_unit_offset(surface, unit, cam_x, cam_y)
            continue
        # Health bar
        bar_w = unit.size * 2
        bar_h = 3
        bx = sx - unit.size
        by = sy - unit.size - 6
        pygame.draw.rect(surface, (80, 0, 0), (bx, by, bar_w, bar_h))
        fill_w = int(bar_w * (unit.hp / unit.max_hp))
        pygame.draw.rect(surface, (255, 140, 0), (bx, by, fill_w, bar_h))

    # AI attack lines
    for ai_unit in ai_player.units:
        if ai_unit.attacking and ai_unit.target_enemy:
            t = ai_unit.target_enemy
            if hasattr(t, 'size'):
                tx, ty = int(t.x) - cam_x, int(t.y) - cam_y
            else:
                tx, ty = t.x + t.w // 2 - cam_x, t.y + t.h // 2 - cam_y
            pygame.draw.line(surface, (255, 140, 0),
                             (int(ai_unit.x) - cam_x, int(ai_unit.y) - cam_y), (tx, ty), 1)


def _get_placement_size(mode):
    if mode == "barracks":
        return BARRACKS_SIZE
    elif mode == "factory":
        return FACTORY_SIZE
    elif mode == "towncenter":
        return TOWN_CENTER_SIZE
    elif mode == "tower":
        return TOWER_SIZE
    return (64, 64)


def _get_placement_sprite(mode):
    if mode == "barracks":
        return Barracks.sprite
    elif mode == "factory":
        return Factory.sprite
    elif mode == "towncenter":
        return TownCenter.sprite
    elif mode == "tower":
        return DefenseTower.sprite
    return None


def _is_placement_valid(ghost_rect, state):
    """Check if a building can be placed at the ghost rect position (world coords)."""
    if ghost_rect.bottom > WORLD_H or ghost_rect.top < 0:
        return False
    if ghost_rect.left < 0 or ghost_rect.right > WORLD_W:
        return False
    for existing in state.buildings:
        if ghost_rect.colliderect(existing.rect):
            return False
    # Check overlap with AI buildings too
    for existing in state.ai_player.buildings:
        if ghost_rect.colliderect(existing.rect):
            return False
    for node in state.mineral_nodes:
        if not node.depleted and ghost_rect.colliderect(node.rect.inflate(10, 10)):
            return False
    # Check overlap with AI mineral nodes
    for node in state.ai_player.mineral_nodes:
        if not node.depleted and ghost_rect.colliderect(node.rect.inflate(10, 10)):
            return False
    cost = state._placement_cost()
    if not state.resource_manager.can_afford(cost):
        return False
    return True


def _replay_main(filename):
    """Run the replay viewer."""
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("GameOne - Replay")
    clock = pygame.time.Clock()

    # Load sprite assets (must happen after pygame.init())
    Soldier.load_assets()
    Tank.load_assets()
    Worker.load_assets()
    Yanuses.load_assets()
    Barracks.load_assets()
    Factory.load_assets()
    TownCenter.load_assets()
    DefenseTower.load_assets()

    # Init replay proxy sprites
    ReplayUnit.init_sprites()
    ReplayBuilding.init_sprites()

    player = ReplayPlayer(filename)
    minimap = Minimap()

    camera_x = 0.0
    camera_y = 0.0
    scroll_left = scroll_right = scroll_up = scroll_down = False
    timeline_dragging = False

    # Cache: only rebuild proxies when frame changes
    last_frame_index = -1
    units = []
    buildings = []
    minerals = []
    enemies = []
    ai_proxy = None
    replay_state = None
    frame = player.get_frame()

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    player.paused = not player.paused
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    player.adjust_speed(1.0)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    player.adjust_speed(-1.0)
                elif event.key == pygame.K_LEFT:
                    scroll_left = True
                elif event.key == pygame.K_RIGHT:
                    scroll_right = True
                elif event.key == pygame.K_UP:
                    scroll_up = True
                elif event.key == pygame.K_DOWN:
                    scroll_down = True
            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_LEFT:
                    scroll_left = False
                elif event.key == pygame.K_RIGHT:
                    scroll_right = False
                elif event.key == pygame.K_UP:
                    scroll_up = False
                elif event.key == pygame.K_DOWN:
                    scroll_down = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Minimap click
                mini_result = minimap.handle_click(event.pos)
                if mini_result is not None:
                    camera_x = max(0, min(mini_result[0], WORLD_W - WIDTH))
                    camera_y = max(0, min(mini_result[1], WORLD_H - MAP_HEIGHT))
                else:
                    # Timeline seek
                    _handle_timeline_seek(event.pos, player)
                    timeline_dragging = True
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                timeline_dragging = False
            elif event.type == pygame.MOUSEMOTION:
                if timeline_dragging:
                    _handle_timeline_seek(event.pos, player)
                elif pygame.mouse.get_pressed()[0] and minimap.rect.collidepoint(event.pos):
                    mini_result = minimap.handle_click(event.pos)
                    if mini_result is not None:
                        camera_x = max(0, min(mini_result[0], WORLD_W - WIDTH))
                        camera_y = max(0, min(mini_result[1], WORLD_H - MAP_HEIGHT))

        # Camera scrolling
        mouse_x, mouse_y = pygame.mouse.get_pos()
        if mouse_y < MAP_HEIGHT:
            if mouse_x < SCROLL_EDGE:
                camera_x -= SCROLL_SPEED * dt
            elif mouse_x > WIDTH - SCROLL_EDGE:
                camera_x += SCROLL_SPEED * dt
            if mouse_y < SCROLL_EDGE:
                camera_y -= SCROLL_SPEED * dt
            elif mouse_y > MAP_HEIGHT - SCROLL_EDGE:
                camera_y += SCROLL_SPEED * dt
        if scroll_left:
            camera_x -= SCROLL_SPEED * dt
        if scroll_right:
            camera_x += SCROLL_SPEED * dt
        if scroll_up:
            camera_y -= SCROLL_SPEED * dt
        if scroll_down:
            camera_y += SCROLL_SPEED * dt
        camera_x = max(0, min(camera_x, WORLD_W - WIDTH))
        camera_y = max(0, min(camera_y, WORLD_H - MAP_HEIGHT))
        cam_x = int(camera_x)
        cam_y = int(camera_y)

        # Update replay
        player.update(dt)
        frame = player.get_frame()

        # Rebuild proxy objects only when frame changes
        if player.frame_index != last_frame_index:
            last_frame_index = player.frame_index
            units = [ReplayUnit(d) for d in frame.get("units", [])]
            buildings = [ReplayBuilding(d) for d in frame.get("buildings", [])]
            minerals = [ReplayNode(d) for d in frame.get("minerals", [])]
            enemies = [ReplayUnit(d) for d in frame.get("enemies", [])]
            ai_units = [ReplayUnit(d) for d in frame.get("ai_units", [])]
            ai_buildings = [ReplayBuilding(d) for d in frame.get("ai_buildings", [])]
            ai_minerals = [ReplayNode(d) for d in frame.get("ai_minerals", [])]
            ai_proxy = ReplayAIPlayer(ai_units, ai_buildings, ai_minerals)
            replay_state = ReplayState(units, buildings, minerals, enemies, ai_proxy)

        # --- Draw ---
        screen.fill(MAP_COLOR)

        # Grid lines
        grid_start_x = (cam_x // 64) * 64
        grid_start_y = (cam_y // 64) * 64
        for gx in range(int(grid_start_x), cam_x + WIDTH + 64, 64):
            sx = gx - cam_x
            if 0 <= sx <= WIDTH:
                pygame.draw.line(screen, (30, 75, 30), (sx, 0), (sx, MAP_HEIGHT), 1)
        for gy in range(int(grid_start_y), cam_y + MAP_HEIGHT + 64, 64):
            sy = gy - cam_y
            if 0 <= sy <= MAP_HEIGHT:
                pygame.draw.line(screen, (30, 75, 30), (0, sy), (WIDTH, sy), 1)

        visible_rect = pygame.Rect(cam_x - 100, cam_y - 100, WIDTH + 200, MAP_HEIGHT + 200)

        # Draw mineral nodes
        for node in minerals:
            if visible_rect.collidepoint(node.x, node.y):
                _draw_mineral_node_offset(screen, node, cam_x, cam_y)

        # Draw buildings
        for building in buildings:
            if visible_rect.colliderect(building.rect):
                _draw_building_offset(screen, building, cam_x, cam_y)

        # Draw units
        for unit in units:
            if visible_rect.collidepoint(int(unit.x), int(unit.y)):
                _draw_unit_offset(screen, unit, cam_x, cam_y)

        # Draw AI player entities
        if ai_proxy:
            _draw_ai_player_offset(screen, ai_proxy, cam_x, cam_y, visible_rect)

        # Draw enemies
        for enemy in enemies:
            if visible_rect.collidepoint(int(enemy.x), int(enemy.y)):
                _draw_unit_offset(screen, enemy, cam_x, cam_y)

        # Game over overlay
        if frame.get("game_over"):
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            screen.blit(overlay, (0, 0))
            big_font = pygame.font.SysFont(None, 72)
            if frame.get("game_result") == "victory":
                text = big_font.render("VICTORY!", True, (0, 255, 100))
            else:
                text = big_font.render("DEFEAT", True, (255, 60, 60))
            text_rect = text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30))
            screen.blit(text, text_rect)

        # Replay overlay (speed, timeline, controls)
        _draw_replay_overlay(screen, player, frame)

        # Minimap
        if replay_state:
            minimap.draw(screen, replay_state, camera_x, camera_y)

        pygame.display.flip()

    pygame.quit()
    sys.exit()


def _handle_timeline_seek(pos, player):
    """Seek the replay player if pos is within the timeline bar area."""
    bar_x = 300
    bar_y = MAP_HEIGHT + 20
    bar_w = WIDTH - 400
    bar_h = 16
    if bar_y - 5 <= pos[1] <= bar_y + bar_h + 5 and bar_x <= pos[0] <= bar_x + bar_w:
        ratio = (pos[0] - bar_x) / bar_w
        player.seek_ratio(ratio)


def _draw_replay_overlay(screen, player, frame):
    """Draw the replay HUD: speed, timeline, wave/resource info, controls."""
    from settings import HUD_BG

    # Bottom bar background
    bar_rect = pygame.Rect(0, MAP_HEIGHT, WIDTH, HEIGHT - MAP_HEIGHT)
    pygame.draw.rect(screen, HUD_BG, bar_rect)

    font = pygame.font.SysFont(None, 24)
    small_font = pygame.font.SysFont(None, 18)

    # Speed indicator
    speed_text = f"Speed: {player.speed:.1f}x"
    if player.paused:
        speed_text += "  [PAUSED]"
    surf = font.render(speed_text, True, (220, 220, 220))
    screen.blit(surf, (20, MAP_HEIGHT + 10))

    # Time position (mm:ss format)
    minutes = int(player.elapsed) // 60
    seconds = int(player.elapsed) % 60
    total_min = int(player.total_time) // 60
    total_sec = int(player.total_time) % 60
    time_text = f"{minutes}:{seconds:02d} / {total_min}:{total_sec:02d}"
    surf = font.render(time_text, True, (220, 220, 220))
    screen.blit(surf, (20, MAP_HEIGHT + 40))

    # Timeline bar
    bar_x = 300
    bar_y = MAP_HEIGHT + 20
    bar_w = WIDTH - 400
    bar_h = 16
    pygame.draw.rect(screen, (60, 60, 60), (bar_x, bar_y, bar_w, bar_h))
    progress = player.elapsed / player.total_time if player.total_time > 0 else 0
    fill_w = int(bar_w * progress)
    pygame.draw.rect(screen, (0, 180, 255), (bar_x, bar_y, fill_w, bar_h))
    pygame.draw.rect(screen, (100, 100, 100), (bar_x, bar_y, bar_w, bar_h), 1)
    # Playhead marker
    pygame.draw.rect(screen, (255, 255, 255), (bar_x + fill_w - 2, bar_y - 3, 4, bar_h + 6))

    # Wave and resource info
    wave = frame.get("wave", 0)
    resources = frame.get("resources", 0)
    info_text = f"Wave: {wave}  |  Resources: {int(resources)}"
    surf = font.render(info_text, True, (255, 215, 0))
    screen.blit(surf, (20, MAP_HEIGHT + 70))

    # AI resources
    ai_resources = frame.get("ai_resources", 0)
    ai_text = f"AI: {int(ai_resources)}"
    surf = font.render(ai_text, True, (255, 180, 100))
    screen.blit(surf, (250, MAP_HEIGHT + 70))

    # Controls help
    help_text = "+/- Speed  |  Space Pause  |  Click timeline to seek  |  ESC Quit"
    surf = small_font.render(help_text, True, (140, 140, 140))
    screen.blit(surf, (bar_x, MAP_HEIGHT + 50))


if __name__ == "__main__":
    main()
