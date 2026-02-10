import pygame
import sys
from settings import (
    WIDTH, HEIGHT, FPS, MAP_COLOR, MAP_HEIGHT, DRAG_BOX_COLOR,
    BARRACKS_SIZE, FACTORY_SIZE, TOWN_CENTER_SIZE,
)
from game_state import GameState
from hud import HUD
from units import Soldier, Tank, Worker, Yanuses
from buildings import Barracks, Factory, TownCenter


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("GameOne - Simple RTS")
    clock = pygame.time.Clock()

    # Load sprite assets (must happen after pygame.init())
    Soldier.load_assets()
    Tank.load_assets()
    Worker.load_assets()
    Yanuses.load_assets()
    Barracks.load_assets()
    Factory.load_assets()
    TownCenter.load_assets()

    state = GameState()
    hud = HUD()

    dragging = False
    drag_start = None
    drag_rect = None

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            # When game is over, only allow quit and ESC
            if state.game_over:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
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

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click
                    pos = event.pos

                    # Check HUD first
                    if hud.is_in_hud(pos):
                        hud.handle_click(pos, state)
                        continue

                    # Placement mode
                    if state.placement_mode:
                        size = _get_placement_size(state.placement_mode)
                        bx = pos[0] - size[0] // 2
                        by = pos[1] - size[1] // 2
                        state.place_building((bx, by))
                        continue

                    # Start drag select
                    dragging = True
                    drag_start = pos
                    drag_rect = None

                elif event.button == 3:  # Right click
                    pos = event.pos
                    if hud.is_in_hud(pos) or not state.selected_units:
                        continue

                    mods = pygame.key.get_mods()

                    # Check if clicked on a mineral node
                    node = state.get_mineral_node_at(pos)
                    if node:
                        # Send workers to mine, move non-workers normally
                        has_workers = any(isinstance(u, Worker) for u in state.selected_units)
                        if has_workers:
                            state.command_mine(node)
                            # Move non-workers to the node area
                            for u in state.selected_units:
                                if not isinstance(u, Worker):
                                    u.set_target(pos)
                        else:
                            state.command_move(pos)
                    elif mods & pygame.KMOD_SHIFT:
                        state.command_queue_waypoint(pos)
                    else:
                        state.command_move(pos)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1 and dragging:
                    dragging = False
                    pos = event.pos

                    if drag_rect and (drag_rect.w > 5 or drag_rect.h > 5):
                        # Box select
                        units = state.get_units_in_rect(drag_rect)
                        if units:
                            state.select_units(units)
                        else:
                            state.deselect_all()
                    else:
                        # Single click select
                        click_pos = drag_start if drag_start else pos
                        unit = state.get_unit_at(click_pos)
                        if unit:
                            state.select_unit(unit)
                        else:
                            building = state.get_building_at(click_pos)
                            if building:
                                state.select_building(building)
                            else:
                                state.deselect_all()

                    drag_start = None
                    drag_rect = None

            elif event.type == pygame.MOUSEMOTION:
                if dragging and drag_start:
                    mx, my = event.pos
                    sx, sy = drag_start
                    x = min(sx, mx)
                    y = min(sy, my)
                    w = abs(mx - sx)
                    h = abs(my - sy)
                    drag_rect = pygame.Rect(x, y, w, h)

        # Update
        state.update(dt)

        # Draw
        screen.fill(MAP_COLOR)

        # Draw grid lines for visual reference
        for gx in range(0, WIDTH, 64):
            pygame.draw.line(screen, (30, 75, 30), (gx, 0), (gx, MAP_HEIGHT), 1)
        for gy in range(0, MAP_HEIGHT, 64):
            pygame.draw.line(screen, (30, 75, 30), (0, gy), (WIDTH, gy), 1)

        # Draw mineral nodes
        for node in state.mineral_nodes:
            node.draw(screen)

        # Draw buildings
        for building in state.buildings:
            building.draw(screen)

        # Draw units
        for unit in state.units:
            unit.draw(screen)
            # Draw attack line when unit is firing
            if unit.attacking and unit.target_enemy:
                t = unit.target_enemy
                if hasattr(t, 'size'):
                    tx, ty = int(t.x), int(t.y)
                else:
                    tx, ty = t.x + t.w // 2, t.y + t.h // 2
                pygame.draw.line(screen, (255, 255, 0),
                                 (int(unit.x), int(unit.y)), (tx, ty), 1)

        # Draw enemies
        for enemy in state.wave_manager.enemies:
            enemy.draw(screen)
            # Draw attack line when enemy is firing
            if enemy.attacking and enemy.target_enemy:
                t = enemy.target_enemy
                if hasattr(t, 'size'):
                    tx, ty = int(t.x), int(t.y)
                else:
                    tx, ty = t.x + t.w // 2, t.y + t.h // 2
                pygame.draw.line(screen, (255, 80, 80),
                                 (int(enemy.x), int(enemy.y)), (tx, ty), 1)

        # Draw placement ghost
        if state.placement_mode:
            mx, my = pygame.mouse.get_pos()
            size = _get_placement_size(state.placement_mode)
            sprite = _get_placement_sprite(state.placement_mode)
            ghost_rect = pygame.Rect(mx - size[0] // 2, my - size[1] // 2, size[0], size[1])
            if sprite:
                ghost_surf = sprite.copy()
                ghost_surf.set_alpha(140)
                screen.blit(ghost_surf, ghost_rect.topleft)
            pygame.draw.rect(screen, (0, 255, 0), ghost_rect, 1)

        # Draw drag selection box
        if dragging and drag_rect:
            pygame.draw.rect(screen, DRAG_BOX_COLOR, drag_rect, 1)

        # Draw waypoint paths for selected units
        for unit in state.selected_units:
            if unit.waypoints:
                points = [(int(unit.x), int(unit.y))] + \
                         [(int(wx), int(wy)) for wx, wy in unit.waypoints]
                if len(points) >= 2:
                    pygame.draw.lines(screen, (255, 255, 0), False, points, 1)
                for wx, wy in unit.waypoints:
                    pygame.draw.circle(screen, (255, 255, 0), (int(wx), int(wy)), 3, 1)

        # Draw HUD
        hud.draw(screen, state)

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

    pygame.quit()
    sys.exit()


def _get_placement_size(mode):
    if mode == "barracks":
        return BARRACKS_SIZE
    elif mode == "factory":
        return FACTORY_SIZE
    elif mode == "towncenter":
        return TOWN_CENTER_SIZE
    return (64, 64)


def _get_placement_sprite(mode):
    if mode == "barracks":
        return Barracks.sprite
    elif mode == "factory":
        return Factory.sprite
    elif mode == "towncenter":
        return TownCenter.sprite
    return None


if __name__ == "__main__":
    main()
