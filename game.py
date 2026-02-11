import pygame
import sys
import datetime
from settings import (
    WIDTH, HEIGHT, FPS, MAP_COLOR, MAP_HEIGHT, DRAG_BOX_COLOR,
    BARRACKS_SIZE, FACTORY_SIZE, TOWN_CENTER_SIZE,
)
from game_state import GameState
from hud import HUD
from minimap import Minimap
from units import Soldier, Tank, Worker, Yanuses
from buildings import Barracks, Factory, TownCenter


class MoveMarker:
    """Visual marker shown where a move command is issued."""
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

    def draw(self, surface):
        progress = self.timer / self.duration
        alpha = int(255 * (1 - progress))
        radius = int(8 + 12 * progress)
        color = (0, 255, 100)
        s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*color, alpha), (radius, radius), radius, 2)
        pygame.draw.line(s, (*color, alpha), (radius - 4, radius), (radius + 4, radius), 1)
        pygame.draw.line(s, (*color, alpha), (radius, radius - 4), (radius, radius + 4), 1)
        surface.blit(s, (self.x - radius, self.y - radius))


class FloatingText:
    """Floating text that rises and fades out."""
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

    def draw(self, surface):
        progress = self.timer / self.duration
        alpha = int(255 * (1 - progress))
        font = pygame.font.SysFont(None, 22)
        text_surf = font.render(self.text, True, self.color)
        text_surf.set_alpha(alpha)
        surface.blit(text_surf, (int(self.x), int(self.y)))


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
    minimap = Minimap()

    dragging = False
    drag_start = None
    drag_rect = None
    paused = False

    # UX state
    move_markers = []
    floating_texts = []
    resource_flash_timer = 0.0  # > 0 means resource counter is flashing
    last_resource_amount = state.resource_manager.amount

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

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click
                    pos = event.pos

                    # Check HUD first
                    if hud.is_in_hud(pos):
                        result = hud.handle_click(pos, state)
                        if result == "insufficient_funds":
                            resource_flash_timer = 0.5
                        continue

                    # Placement mode
                    if state.placement_mode:
                        size = _get_placement_size(state.placement_mode)
                        bx = pos[0] - size[0] // 2
                        by = pos[1] - size[1] // 2
                        if not state.place_building((bx, by)):
                            resource_flash_timer = 0.5
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
                        move_markers.append(MoveMarker(pos[0], pos[1]))
                    elif mods & pygame.KMOD_SHIFT:
                        state.command_queue_waypoint(pos)
                        move_markers.append(MoveMarker(pos[0], pos[1]))
                    else:
                        state.command_move(pos)
                        move_markers.append(MoveMarker(pos[0], pos[1]))

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
        if not paused:
            state.update(dt)

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
                # Fallback: show near HUD resource area
                floating_texts.append(FloatingText(80, MAP_HEIGHT - 10, f"+{gained}"))
        last_resource_amount = current_amount

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

        # Draw AI player (buildings, units, mineral nodes)
        state.ai_player.draw(screen)
        # Draw AI attack lines
        for ai_unit in state.ai_player.units:
            if ai_unit.attacking and ai_unit.target_enemy:
                t = ai_unit.target_enemy
                if hasattr(t, 'size'):
                    tx, ty = int(t.x), int(t.y)
                else:
                    tx, ty = t.x + t.w // 2, t.y + t.h // 2
                pygame.draw.line(screen, (255, 140, 0),
                                 (int(ai_unit.x), int(ai_unit.y)), (tx, ty), 1)

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

        # Draw placement ghost (green=valid, red=invalid)
        if state.placement_mode:
            mx, my = pygame.mouse.get_pos()
            size = _get_placement_size(state.placement_mode)
            sprite = _get_placement_sprite(state.placement_mode)
            ghost_rect = pygame.Rect(mx - size[0] // 2, my - size[1] // 2, size[0], size[1])
            valid = _is_placement_valid(ghost_rect, state)
            ghost_color = (0, 255, 0) if valid else (255, 50, 50)
            if sprite:
                ghost_surf = sprite.copy()
                ghost_surf.set_alpha(140)
                if not valid:
                    # Tint red for invalid placement
                    red_tint = pygame.Surface(ghost_surf.get_size(), pygame.SRCALPHA)
                    red_tint.fill((255, 0, 0, 80))
                    ghost_surf.blit(red_tint, (0, 0))
                screen.blit(ghost_surf, ghost_rect.topleft)
            pygame.draw.rect(screen, ghost_color, ghost_rect, 2)

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

        # Draw move-order markers
        for marker in move_markers:
            marker.draw(screen)

        # Draw floating texts
        for ft in floating_texts:
            ft.draw(screen)

        # Draw unit count badge near cursor when multiple units selected
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

        # Draw building HP on hover
        hover_pos = pygame.mouse.get_pos()
        for building in state.buildings:
            if building.rect.collidepoint(hover_pos):
                hp_font = pygame.font.SysFont(None, 20)
                hp_text = hp_font.render(f"HP: {building.hp}/{building.max_hp}", True, (255, 255, 255))
                hp_bg = pygame.Surface((hp_text.get_width() + 6, hp_text.get_height() + 4), pygame.SRCALPHA)
                hp_bg.fill((0, 0, 0, 160))
                screen.blit(hp_bg, (hover_pos[0] + 10, hover_pos[1] - 20))
                screen.blit(hp_text, (hover_pos[0] + 13, hover_pos[1] - 18))
                break

        # Draw HUD
        hud.draw(screen, state, resource_flash_timer)

        # Draw minimap
        minimap.draw(screen, state)

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


def _is_placement_valid(ghost_rect, state):
    """Check if a building can be placed at the ghost rect position."""
    if ghost_rect.bottom > MAP_HEIGHT or ghost_rect.top < 0:
        return False
    if ghost_rect.left < 0 or ghost_rect.right > WIDTH:
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


if __name__ == "__main__":
    main()
