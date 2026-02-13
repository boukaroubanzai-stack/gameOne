"""Minimap overlay: world-proportional map showing all entities and camera viewport."""

import pygame
import settings


# Minimap dimensions (world-proportional, don't change on resize)
MINIMAP_W = 200
MINIMAP_H = int(MINIMAP_W * settings.WORLD_H / settings.WORLD_W)
MINIMAP_MARGIN = 8

# Scale factors (world coords -> minimap coords)
SCALE_X = MINIMAP_W / settings.WORLD_W
SCALE_Y = MINIMAP_H / settings.WORLD_H

# Colors
BG_COLOR = (15, 40, 15, 180)
BORDER_COLOR = (160, 160, 160)
NODE_ACTIVE_COLOR = (50, 150, 255)
NODE_DEPLETED_COLOR = (80, 80, 80)
PLAYER_BUILDING_COLOR = (0, 200, 0)
PLAYER_UNIT_COLOR = (80, 255, 80)
SELECTED_UNIT_COLOR = (255, 255, 100)
ENEMY_COLOR = (255, 50, 50)
AI_BUILDING_COLOR = (255, 160, 0)
AI_UNIT_COLOR = (255, 200, 50)
VIEWPORT_COLOR = (255, 255, 255)


class Minimap:
    def __init__(self):
        self.surface = pygame.Surface((MINIMAP_W, MINIMAP_H), pygame.SRCALPHA)
        self._update_position()

    def _update_position(self):
        """Recalculate position based on current screen dimensions."""
        self.minimap_x = settings.WIDTH - MINIMAP_W - MINIMAP_MARGIN
        self.minimap_y = settings.MAP_HEIGHT + (settings.HUD_HEIGHT - MINIMAP_H) // 2
        self.rect = pygame.Rect(self.minimap_x, self.minimap_y, MINIMAP_W, MINIMAP_H)

    def resize(self):
        """Call after screen resize to update minimap position."""
        self._update_position()

    def _world_to_mini(self, wx, wy):
        """Convert world coordinates to minimap-local coordinates."""
        return int(wx * SCALE_X), int(wy * SCALE_Y)

    def handle_click(self, screen_pos):
        """If screen_pos is inside the minimap, return the world coords to center
        the camera on, otherwise return None."""
        if not self.rect.collidepoint(screen_pos):
            return None
        # Local position within the minimap
        lx = screen_pos[0] - self.minimap_x
        ly = screen_pos[1] - self.minimap_y
        # Convert to world coords and center the viewport
        world_x = lx / SCALE_X - settings.WIDTH / 2
        world_y = ly / SCALE_Y - settings.MAP_HEIGHT / 2
        return (world_x, world_y)

    def minimap_to_world(self, screen_pos):
        """Convert a screen position on the minimap to world coordinates.
        Returns (world_x, world_y) or None if pos is outside the minimap."""
        if not self.rect.collidepoint(screen_pos):
            return None
        lx = screen_pos[0] - self.minimap_x
        ly = screen_pos[1] - self.minimap_y
        world_x = lx / SCALE_X
        world_y = ly / SCALE_Y
        return (world_x, world_y)

    def draw(self, screen, game_state, camera_x=0, camera_y=0,
             local_team="player", fog_visible_fn=None, has_radar=False):
        """Draw minimap. If fog_visible_fn is provided, opponent entities are
        filtered through it. If has_radar is True, fog is disabled on minimap."""
        surf = self.surface
        surf.fill(BG_COLOR)

        if local_team == "player":
            my_units = game_state.units
            my_buildings = game_state.buildings
            my_nodes = game_state.mineral_nodes
            opp_units = getattr(game_state.ai_player, "units", [])
            opp_buildings = getattr(game_state.ai_player, "buildings", [])
            opp_nodes = getattr(game_state.ai_player, "mineral_nodes", [])
        else:
            my_units = getattr(game_state.ai_player, "units", [])
            my_buildings = getattr(game_state.ai_player, "buildings", [])
            my_nodes = getattr(game_state.ai_player, "mineral_nodes", [])
            opp_units = game_state.units
            opp_buildings = game_state.buildings
            opp_nodes = game_state.mineral_nodes

        # Own mineral nodes (always visible)
        for node in my_nodes:
            mx, my = self._world_to_mini(node.x, node.y)
            color = NODE_DEPLETED_COLOR if node.depleted else NODE_ACTIVE_COLOR
            pygame.draw.rect(surf, color, (mx - 2, my - 2, 4, 4))

        # Own buildings (always visible)
        my_bld_color = PLAYER_BUILDING_COLOR if local_team == "player" else AI_BUILDING_COLOR
        for b in my_buildings:
            bx, by = self._world_to_mini(b.x, b.y)
            bw = max(int(b.w * SCALE_X), 3)
            bh = max(int(b.h * SCALE_Y), 3)
            pygame.draw.rect(surf, my_bld_color, (bx, by, bw, bh))

        # Own units (always visible)
        my_unit_color = PLAYER_UNIT_COLOR if local_team == "player" else AI_UNIT_COLOR
        for u in my_units:
            ux, uy = self._world_to_mini(u.x, u.y)
            color = SELECTED_UNIT_COLOR if u.selected else my_unit_color
            pygame.draw.rect(surf, color, (ux - 1, uy - 1, 3, 3))

        # Opponent entities (filtered by fog unless radar active)
        opp_bld_color = AI_BUILDING_COLOR if local_team == "player" else PLAYER_BUILDING_COLOR
        opp_unit_color = AI_UNIT_COLOR if local_team == "player" else PLAYER_UNIT_COLOR
        for node in opp_nodes:
            if has_radar or (fog_visible_fn and fog_visible_fn(node.x, node.y)):
                mx, my = self._world_to_mini(node.x, node.y)
                color = NODE_DEPLETED_COLOR if node.depleted else NODE_ACTIVE_COLOR
                pygame.draw.rect(surf, color, (mx - 2, my - 2, 4, 4))
        for b in opp_buildings:
            bx_w = b.x + b.w * 0.5
            by_w = b.y + b.h * 0.5
            if has_radar or (fog_visible_fn and fog_visible_fn(bx_w, by_w)):
                bx, by = self._world_to_mini(b.x, b.y)
                bw = max(int(b.w * SCALE_X), 3)
                bh = max(int(b.h * SCALE_Y), 3)
                pygame.draw.rect(surf, opp_bld_color, (bx, by, bw, bh))
        for u in opp_units:
            if has_radar or (fog_visible_fn and fog_visible_fn(u.x, u.y)):
                ux, uy = self._world_to_mini(u.x, u.y)
                pygame.draw.rect(surf, opp_unit_color, (ux - 1, uy - 1, 3, 3))

        # Enemy units (Yanuses from wave manager — always visible)
        for e in game_state.wave_manager.enemies:
            ex, ey = self._world_to_mini(e.x, e.y)
            pygame.draw.rect(surf, ENEMY_COLOR, (ex - 1, ey - 1, 3, 3))

        # Draw viewport rectangle (shows current camera view)
        vx = int(camera_x * SCALE_X)
        vy = int(camera_y * SCALE_Y)
        vw = max(int(settings.WIDTH * SCALE_X), 1)
        vh = max(int(settings.MAP_HEIGHT * SCALE_Y), 1)
        pygame.draw.rect(surf, VIEWPORT_COLOR, (vx, vy, vw, vh), 1)

        # Fog overlay on minimap (dark areas outside vision, skipped if radar)
        if not has_radar:
            fog = pygame.Surface((MINIMAP_W, MINIMAP_H), pygame.SRCALPHA)
            fog.fill((0, 0, 0, 140))
            for u in my_units:
                vr = u.vision_range
                if vr > 0:
                    ux, uy = self._world_to_mini(u.x, u.y)
                    r = max(int(vr * SCALE_X), 1)
                    pygame.draw.circle(fog, (0, 0, 0, 0), (ux, uy), r)
            for b in my_buildings:
                vr = getattr(b, 'vision_range', 0)
                if vr <= 0:
                    vr = b.attack_range if hasattr(b, 'attack_range') and b.attack_range > 0 else 500
                bx, by = self._world_to_mini(b.x + b.w * 0.5, b.y + b.h * 0.5)
                r = max(int(vr * SCALE_X), 1)
                pygame.draw.circle(fog, (0, 0, 0, 0), (bx, by), r)
            surf.blit(fog, (0, 0))

        # Blit minimap surface onto screen
        screen.blit(surf, (self.minimap_x, self.minimap_y))

        # Border
        pygame.draw.rect(screen, BORDER_COLOR, self.rect, 1)
