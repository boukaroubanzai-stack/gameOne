"""Main entry point: Pygame event loop, camera system, rendering, and replay viewer."""

import atexit
import pygame
import sys
import datetime
import settings
from settings import (
    WIDTH, HEIGHT, FPS, MAP_COLOR, MAP_HEIGHT, DRAG_BOX_COLOR,
    BARRACKS_SIZE, FACTORY_SIZE, TOWN_CENTER_SIZE, TOWER_SIZE, WATCHGUARD_SIZE,
    WORLD_W, WORLD_H, SCROLL_SPEED, SCROLL_EDGE,
    BUILDING_ZONE_TC_RADIUS, BUILDING_ZONE_BUILDING_RADIUS, WATCHGUARD_ZONE_RADIUS,
)
from utils import get_font, hp_bar_color, get_range_circle
from game_state import GameState
from hud import HUD
from minimap import Minimap
from units import Soldier, Tank, Worker, Yanuses
from buildings import Barracks, Factory, TownCenter, DefenseTower, Watchguard
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
        text_surf = get_font(22).render(self.text, True, self.color)
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
    global WIDTH, HEIGHT, MAP_HEIGHT
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

    # Parse multiplayer mode
    multiplayer_mode = None  # None, "host", "join"
    join_ip = None
    mp_port = 7777
    for i, arg in enumerate(sys.argv):
        if arg == "--host":
            multiplayer_mode = "host"
            if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
                mp_port = int(sys.argv[i + 1])
        elif arg == "--join" and i + 1 < len(sys.argv):
            multiplayer_mode = "join"
            join_ip = sys.argv[i + 1]
            if i + 2 < len(sys.argv) and sys.argv[i + 2].isdigit():
                mp_port = int(sys.argv[i + 2])

    # Parse AI profile selection
    ai_profile_name = "basic"
    for i, arg in enumerate(sys.argv):
        if arg == "--ai" and i + 1 < len(sys.argv):
            ai_profile_name = sys.argv[i + 1]
            break

    ai_profile = None
    if not multiplayer_mode:
        from ai_profiles import load_profile
        ai_profile = load_profile(ai_profile_name)

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    caption = "GameOne - Simple RTS"
    if playforme:
        caption += " [SPECTATOR]"
    elif multiplayer_mode == "host":
        caption += " [HOST]"
    elif multiplayer_mode == "join":
        caption += " [JOIN]"
    pygame.display.set_caption(caption)
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

    # Multiplayer connection phase
    net_session = None
    local_team = "player"
    net_cleanup = None
    if multiplayer_mode == "host":
        from network import NetworkHost, NetSession
        import random as _random
        net_host = NetworkHost(port=mp_port)
        net_host.start()
        net_cleanup = net_host.cleanup
        # Waiting screen
        waiting = True
        while waiting:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                    net_host.cleanup()
                    pygame.quit()
                    return
            if net_host.accept():
                waiting = False
            screen.fill((30, 30, 40))
            txt = get_font(36).render(f"Hosting on port {mp_port}... Waiting for peer.", True, (200, 200, 200))
            screen.blit(txt, (WIDTH // 2 - txt.get_width() // 2, HEIGHT // 2))
            pygame.display.flip()
            clock.tick(30)
        net_session = NetSession(net_host.connection, is_host=True)
        seed = _random.randint(0, 2**32)
        net_session.send_handshake(seed)
        if not net_session.wait_for_handshake_ack():
            print("Handshake failed!")
            net_host.cleanup()
            pygame.quit()
            return
        local_team = "player"
    elif multiplayer_mode == "join":
        from network import NetworkClient, NetSession
        net_client = NetworkClient(join_ip, port=mp_port)
        try:
            net_client.connect()
        except Exception as e:
            print(f"Failed to connect: {e}")
            pygame.quit()
            return
        net_session = NetSession(net_client.connection, is_host=False)
        if not net_session.wait_for_handshake():
            print("Handshake failed!")
            pygame.quit()
            return
        local_team = "ai"

    random_seed = net_session.random_seed if net_session else None
    state = GameState(ai_profile=ai_profile, multiplayer=(multiplayer_mode is not None), random_seed=random_seed)
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
    _local_rm = lambda: state.resource_manager if local_team == "player" else state.ai_player.resource_manager
    last_resource_amount = _local_rm().amount

    # Scroll direction flags (for keyboard scrolling)
    scroll_left = False
    scroll_right = False
    scroll_up = False
    scroll_down = False

    # Replay recorder (always active, atexit ensures save on any exit)
    recorder = ReplayRecorder()
    atexit.register(recorder.save)

    playforme_timer = 0.0  # auto-exit timer for playforme mode

    # Non-blocking net sync state
    net_waiting = False    # True while waiting for remote tick commands
    net_wait_start = 0.0   # time.time() when waiting started

    # Pre-import for multiplayer (avoid re-importing every frame)
    if net_session:
        import time as _time
        from commands import execute_command

    running = True
    try:
     while running:
        dt = clock.tick(FPS) / 1000.0
        sim_dt = dt if net_session else dt * 2

        # Auto-exit playforme after game over (give 2s for final frames)
        if playforme and state.game_over:
            playforme_timer += dt
            if playforme_timer > 2.0:
                running = False
                continue

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.VIDEORESIZE:
                WIDTH = event.w
                HEIGHT = event.h
                MAP_HEIGHT = HEIGHT - settings.HUD_HEIGHT
                settings.WIDTH = WIDTH
                settings.HEIGHT = HEIGHT
                settings.MAP_HEIGHT = MAP_HEIGHT
                screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
                minimap.resize()
                hud.resize()

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
                elif event.key in (pygame.K_b, pygame.K_f, pygame.K_t, pygame.K_d, pygame.K_g):
                    has_worker = any(isinstance(u, Worker) for u in state.selected_units)
                    if has_worker:
                        if event.key == pygame.K_b:
                            state.placement_mode = "barracks"
                        elif event.key == pygame.K_f:
                            state.placement_mode = "factory"
                        elif event.key == pygame.K_t:
                            state.placement_mode = "towncenter"
                        elif event.key == pygame.K_d:
                            state.placement_mode = "tower"
                        elif event.key == pygame.K_g:
                            state.placement_mode = "watchguard"
                    else:
                        floating_texts.append(FloatingText(
                            camera_x + WIDTH // 2, camera_y + MAP_HEIGHT // 2,
                            "Select a worker first!", (255, 80, 80)))
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
                        result = hud.handle_click(screen_pos, state, net_session=net_session, local_team=local_team)
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
                        if net_session:
                            # Find the closest worker to assign
                            from commands import execute_command, BUILDING_CLASSES, BUILDING_COSTS
                            building_type = state.placement_mode
                            cost = BUILDING_COSTS.get(building_type, 0)
                            local_rm = state.resource_manager if local_team == "player" else state.ai_player.resource_manager
                            if not local_rm.can_afford(cost):
                                resource_flash_timer = 0.5
                            else:
                                workers = [u for u in state.selected_units if isinstance(u, Worker)]
                                if workers:
                                    closest = min(workers, key=lambda w: (w.x - bx)**2 + (w.y - by)**2)
                                    net_session.queue_command({
                                        "cmd": "place_building",
                                        "building_type": building_type,
                                        "x": bx, "y": by,
                                        "worker_id": closest.net_id,
                                    })
                                    state.placement_mode = None
                        else:
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
                    if state.placement_mode:
                        state.placement_mode = None
                        continue
                    screen_pos = event.pos
                    if not state.selected_units:
                        continue

                    selected_ids = [u.net_id for u in state.selected_units]

                    # Check minimap right-click — set waypoint for selected units
                    mini_world = minimap.minimap_to_world(screen_pos)
                    if mini_world is not None:
                        mods = pygame.key.get_mods()
                        if net_session:
                            cmd_type = "queue_waypoint" if mods & pygame.KMOD_SHIFT else "move"
                            net_session.queue_command({
                                "cmd": cmd_type,
                                "unit_ids": selected_ids,
                                "x": mini_world[0], "y": mini_world[1],
                            })
                        else:
                            if mods & pygame.KMOD_SHIFT:
                                state.command_queue_waypoint(mini_world)
                            else:
                                state.command_move(mini_world)
                        move_markers.append(MoveMarker(mini_world[0], mini_world[1]))
                        continue

                    if hud.is_in_hud(screen_pos):
                        continue

                    # Convert to world coords
                    world_pos = _screen_to_world(screen_pos, camera_x, camera_y)
                    mods = pygame.key.get_mods()

                    # Check if right-clicked a damaged friendly unit or building (repair)
                    has_workers = any(isinstance(u, Worker) for u in state.selected_units)
                    repair_target = None
                    if has_workers:
                        # Check friendly units
                        if net_session:
                            clicked_unit = state.get_local_unit_at(world_pos, local_team)
                        else:
                            clicked_unit = state.get_unit_at(world_pos)
                        if clicked_unit and clicked_unit.alive and clicked_unit.hp < clicked_unit.max_hp and clicked_unit.team == local_team:
                            repair_target = clicked_unit
                        if not repair_target:
                            if net_session:
                                clicked_bld = state.get_local_building_at(world_pos, local_team)
                            else:
                                clicked_bld = state.get_building_at(world_pos)
                            if clicked_bld and clicked_bld.hp > 0 and clicked_bld.hp < clicked_bld.max_hp:
                                repair_target = clicked_bld
                    if repair_target:
                        if net_session:
                            worker_ids = [u.net_id for u in state.selected_units if isinstance(u, Worker)]
                            non_worker_ids = [u.net_id for u in state.selected_units if not isinstance(u, Worker)]
                            if worker_ids:
                                target_type = "unit" if hasattr(repair_target, 'size') else "building"
                                net_session.queue_command({
                                    "cmd": "repair",
                                    "worker_ids": worker_ids,
                                    "target_type": target_type,
                                    "target_id": repair_target.net_id,
                                })
                            if non_worker_ids:
                                net_session.queue_command({
                                    "cmd": "move",
                                    "unit_ids": non_worker_ids,
                                    "x": world_pos[0], "y": world_pos[1],
                                })
                        else:
                            for u in state.selected_units:
                                if isinstance(u, Worker):
                                    u.assign_to_repair(repair_target)
                                else:
                                    u.set_target(world_pos)
                        move_markers.append(MoveMarker(world_pos[0], world_pos[1]))

                    # Check if clicked on a mineral node (world coords)
                    elif (node := state.get_mineral_node_at(world_pos)):
                        if net_session:
                            local_nodes = state.get_local_mineral_nodes(local_team)
                            node_index = None
                            for idx, n in enumerate(local_nodes):
                                if n is node:
                                    node_index = idx
                                    break
                            if node_index is not None and has_workers:
                                worker_ids = [u.net_id for u in state.selected_units if isinstance(u, Worker)]
                                non_worker_ids = [u.net_id for u in state.selected_units if not isinstance(u, Worker)]
                                net_session.queue_command({
                                    "cmd": "mine",
                                    "unit_ids": worker_ids,
                                    "node_index": node_index,
                                })
                                if non_worker_ids:
                                    net_session.queue_command({
                                        "cmd": "move",
                                        "unit_ids": non_worker_ids,
                                        "x": world_pos[0], "y": world_pos[1],
                                    })
                            else:
                                net_session.queue_command({
                                    "cmd": "move",
                                    "unit_ids": selected_ids,
                                    "x": world_pos[0], "y": world_pos[1],
                                })
                        else:
                            if has_workers:
                                state.command_mine(node)
                                for u in state.selected_units:
                                    if not isinstance(u, Worker):
                                        u.set_target(world_pos)
                            else:
                                state.command_move(world_pos)
                        move_markers.append(MoveMarker(world_pos[0], world_pos[1]))
                    elif mods & pygame.KMOD_SHIFT:
                        if net_session:
                            net_session.queue_command({
                                "cmd": "queue_waypoint",
                                "unit_ids": selected_ids,
                                "x": world_pos[0], "y": world_pos[1],
                            })
                        else:
                            state.command_queue_waypoint(world_pos)
                        move_markers.append(MoveMarker(world_pos[0], world_pos[1]))
                    else:
                        if net_session:
                            net_session.queue_command({
                                "cmd": "move",
                                "unit_ids": selected_ids,
                                "x": world_pos[0], "y": world_pos[1],
                            })
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
                        if net_session:
                            units = state.get_local_units_in_rect(drag_rect, local_team)
                        else:
                            units = state.get_units_in_rect(drag_rect)
                        if units:
                            state.select_units(units)
                        else:
                            state.deselect_all()
                    else:
                        # Single click select (use world coords)
                        click_world = drag_start_world if drag_start_world else world_pos
                        if net_session:
                            unit = state.get_local_unit_at(click_world, local_team)
                        else:
                            unit = state.get_unit_at(click_world)
                        if unit:
                            state.select_unit(unit)
                        else:
                            if net_session:
                                building = state.get_local_building_at(click_world, local_team)
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
            # Mouse-edge scrolling
            mouse_x, mouse_y = pygame.mouse.get_pos()
            if mouse_x < SCROLL_EDGE:
                camera_x -= SCROLL_SPEED * dt
            elif mouse_x > WIDTH - SCROLL_EDGE:
                camera_x += SCROLL_SPEED * dt
            if mouse_y < SCROLL_EDGE:
                camera_y -= SCROLL_SPEED * dt
            elif mouse_y > HEIGHT - SCROLL_EDGE:
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
            # --- Multiplayer tick sync (non-blocking) ---
            if net_session:
                if net_waiting:
                    # Poll for remote commands without blocking
                    net_session.receive_and_process()
                    if not net_session.connected:
                        running = False
                    elif net_session.remote_tick_ready:
                        for cmd in net_session.local_commands:
                            execute_command(cmd, state, local_team)
                        for cmd in net_session.remote_commands:
                            execute_command(cmd, state, net_session.remote_team)
                        net_session.advance_tick()
                        net_waiting = False
                    elif _time.time() - net_wait_start > 5.0:
                        print("Peer timed out!")
                        running = False
                else:
                    net_session.increment_frame()
                    if net_session.is_tick_frame():
                        net_session.end_tick_and_send()
                        net_session.receive_and_process()
                        if not net_session.connected:
                            running = False
                        elif net_session.remote_tick_ready:
                            for cmd in net_session.local_commands:
                                execute_command(cmd, state, local_team)
                            for cmd in net_session.remote_commands:
                                execute_command(cmd, state, net_session.remote_team)
                            net_session.advance_tick()
                        else:
                            net_waiting = True
                            net_wait_start = _time.time()
                    else:
                        net_session.receive_and_process()
                        if not net_session.connected:
                            running = False

            # Only advance simulation when not waiting for remote peer
            if not net_waiting:
                state.update(sim_dt)
                if player_ai is not None:
                    player_ai.update(sim_dt, state, state.wave_manager.enemies, state.ai_player)
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
        current_amount = _local_rm().amount
        if current_amount > last_resource_amount:
            gained = int(current_amount - last_resource_amount)
            local_units = state.units if local_team == "player" else state.ai_player.units
            for u in local_units:
                if isinstance(u, Worker) and u.state == "moving_to_mine":
                    floating_texts.append(FloatingText(u.x, u.y - 20, f"+{gained}"))
                    break
            else:
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
            if unit.attacking and unit.target_enemy:
                _draw_attack_line(screen, int(unit.x) - cam_x, int(unit.y) - cam_y,
                                  unit.target_enemy, cam_x, cam_y, (255, 255, 0))

        # Draw AI player (buildings, units, mineral nodes) with camera offset
        _draw_ai_player_offset(screen, state.ai_player, cam_x, cam_y, visible_rect)

        # Draw enemies (with camera offset)
        for enemy in state.wave_manager.enemies:
            if visible_rect.collidepoint(int(enemy.x), int(enemy.y)):
                _draw_unit_offset(screen, enemy, cam_x, cam_y)
            if enemy.attacking and enemy.target_enemy:
                _draw_attack_line(screen, int(enemy.x) - cam_x, int(enemy.y) - cam_y,
                                  enemy.target_enemy, cam_x, cam_y, (255, 80, 80))

        # Draw disaster effects (with camera offset)
        disaster_mgr.draw(screen, cam_x, cam_y)

        # Draw placement zones when in placement mode
        if state.placement_mode:
            local_buildings = state.buildings if local_team == "player" else state.ai_player.buildings
            for b in local_buildings:
                if b.hp <= 0:
                    continue
                bcx = b.x + b.w // 2 - cam_x
                bcy = b.y + b.h // 2 - cam_y
                if isinstance(b, TownCenter):
                    radius = BUILDING_ZONE_TC_RADIUS
                elif isinstance(b, Watchguard):
                    radius = WATCHGUARD_ZONE_RADIUS
                else:
                    radius = BUILDING_ZONE_BUILDING_RADIUS
                # Only draw if the circle is at least partially on screen
                if bcx + radius < 0 or bcx - radius > WIDTH or bcy + radius < 0 or bcy - radius > MAP_HEIGHT:
                    continue
                screen.blit(_get_zone_surface(radius), (int(bcx - radius), int(bcy - radius)))

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
            valid = _is_placement_valid(ghost_rect_world, state, local_team=local_team)
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
            badge_text = get_font(18).render(str(len(state.selected_units)), True, (255, 255, 255))
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
                hp_text = get_font(20).render(f"HP: {building.hp}/{building.max_hp}", True, (255, 255, 255))
                hp_bg = pygame.Surface((hp_text.get_width() + 6, hp_text.get_height() + 4), pygame.SRCALPHA)
                hp_bg.fill((0, 0, 0, 160))
                screen.blit(hp_bg, (hover_screen[0] + 10, hover_screen[1] - 20))
                screen.blit(hp_text, (hover_screen[0] + 13, hover_screen[1] - 18))
                break

        # Draw HUD (fixed screen position, no camera offset)
        hud.draw(screen, state, resource_flash_timer, local_team=local_team)

        # Draw minimap (fixed screen position, pass camera position)
        minimap.draw(screen, state, camera_x, camera_y)

        # Paused overlay
        if paused:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 120))
            screen.blit(overlay, (0, 0))
            text = get_font(72).render("PAUSED", True, (255, 255, 100))
            text_rect = text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30))
            screen.blit(text, text_rect)
            sub = get_font(32).render("dbug.log written  |  Press ESC to resume", True, (200, 200, 200))
            sub_rect = sub.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 30))
            screen.blit(sub, sub_rect)

        # Game over overlay
        if state.game_over:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            screen.blit(overlay, (0, 0))
            if state.game_result == "victory":
                text = get_font(72).render("VICTORY!", True, (0, 255, 100))
            else:
                text = get_font(72).render("DEFEAT", True, (255, 60, 60))
            text_rect = text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30))
            screen.blit(text, text_rect)
            sub = get_font(32).render("Press ESC to quit", True, (200, 200, 200))
            sub_rect = sub.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 30))
            screen.blit(sub, sub_rect)

        # FPS counter (top-right corner)
        fps_text = get_font(18).render(f"{int(clock.get_fps())} f/s", True, (200, 200, 200))
        screen.blit(fps_text, (WIDTH - fps_text.get_width() - 10, 10))

        pygame.display.flip()
    finally:
        recorder.save()
        if net_session:
            net_session.close()
        if net_cleanup:
            net_cleanup()

    pygame.quit()
    sys.exit()


# --- Shared drawing helpers (eliminate duplication) ---

def _draw_attack_line(surface, attacker_sx, attacker_sy, target, cam_x, cam_y, color, width=1):
    """Draw a firing line from attacker screen-pos to target screen-pos."""
    if hasattr(target, 'size'):
        tx, ty = int(target.x) - cam_x, int(target.y) - cam_y
    else:
        tx, ty = target.x + target.w // 2 - cam_x, target.y + target.h // 2 - cam_y
    pygame.draw.line(surface, color, (attacker_sx, attacker_sy), (int(tx), int(ty)), width)


def _draw_health_bar(surface, x, y, width, height, hp, max_hp, bg=(80, 0, 0)):
    """Draw a colour-coded health bar (green > 50%, yellow > 25%, red below)."""
    pygame.draw.rect(surface, bg, (x, y, width, height))
    ratio = hp / max_hp if max_hp > 0 else 0
    fill_w = int(width * ratio)
    pygame.draw.rect(surface, hp_bar_color(ratio), (x, y, fill_w, height))


def _draw_worker_extras(surface, unit, sx, sy):
    """Draw worker overlays: carry dot, state text, deploy progress bar."""
    if unit.carry_amount > 0:
        pygame.draw.circle(surface, (255, 215, 0), (sx + unit.size, sy - unit.size), 4)
    if unit.selected and unit.state != "idle":
        state_text = unit.state.replace("_", " ")
        label = get_font(14).render(state_text, True, (200, 200, 200))
        surface.blit(label, (sx - unit.size, sy + unit.size + 2))
    if unit.state == "deploying" and unit.deploy_building and unit.deploy_building_class:
        build_time = unit.deploy_building_class.build_time
        progress = min(unit.deploy_build_timer / build_time, 1.0) if build_time > 0 else 1.0
        prog_w = unit.size * 3
        prog_h = 3
        px = sx - prog_w // 2
        py = sy + unit.size + 14
        pygame.draw.rect(surface, (60, 60, 60), (px, py, prog_w, prog_h))
        pygame.draw.rect(surface, (0, 180, 255), (px, py, int(prog_w * progress), prog_h))


def _draw_range_circle(surface, cx, cy, radius):
    """Draw a cached semi-transparent range circle centered at (cx, cy)."""
    r = int(radius)
    circle_surf = get_range_circle(r)
    surface.blit(circle_surf, (cx - r, cy - r))


_zone_cache: dict[int, pygame.Surface] = {}

def _get_zone_surface(radius):
    """Return a cached semi-transparent placement zone circle."""
    surf = _zone_cache.get(radius)
    if surf is None:
        surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(surf, (100, 200, 100, 30), (radius, radius), radius)
        pygame.draw.circle(surf, (100, 200, 100, 60), (radius, radius), radius, 1)
        _zone_cache[radius] = surf
    return surf


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

    font = get_font(16)
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
            _draw_range_circle(surface, cx_t, cy_t, building.attack_range)
        if building.attacking and building.target_enemy:
            _draw_attack_line(surface, int(cx_t), int(cy_t), building.target_enemy, cam_x, cam_y, (255, 200, 50), 2)
        _draw_health_bar(surface, ox, oy - 8, building.w, 4, building.hp, building.max_hp, HEALTH_BAR_BG)
        label = get_font(18).render(building.label, True, (255, 255, 255))
        label_rect = label.get_rect(center=(int(cx_t), oy - 16))
        surface.blit(label, label_rect)
        return

    if building.sprite:
        surface.blit(building.sprite, (ox, oy))
    if building.selected:
        r = pygame.Rect(ox, oy, building.w, building.h)
        pygame.draw.rect(surface, SELECT_COLOR, r.inflate(6, 6), 2)
    _draw_health_bar(surface, ox, oy - 8, building.w, 4, building.hp, building.max_hp, HEALTH_BAR_BG)
    label = get_font(18).render(building.label, True, (255, 255, 255))
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
        if unit.attack_range > 0:
            _draw_range_circle(surface, sx, sy, unit.attack_range)

    _draw_health_bar(surface, sx - unit.size, sy - unit.size - 6,
                     unit.size * 2, 3, unit.hp, unit.max_hp, HEALTH_BAR_BG)

    if isinstance(unit, Worker):
        _draw_worker_extras(surface, unit, sx, sy)


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
        if building.selected:
            from settings import SELECT_COLOR
            r = pygame.Rect(ox, oy, building.w, building.h)
            pygame.draw.rect(surface, SELECT_COLOR, r.inflate(6, 6), 2)
        _draw_health_bar(surface, ox, oy - 8, building.w, 4, building.hp, building.max_hp)
        label = get_font(18).render(building.label, True, (255, 180, 100))
        label_rect = label.get_rect(center=(ox + building.w // 2, oy - 16))
        surface.blit(label, label_rect)
        if building.production_queue:
            prog_y = oy + building.h + 2
            pygame.draw.rect(surface, (60, 60, 60), (ox, prog_y, building.w, 4))
            prog = building.production_progress
            pygame.draw.rect(surface, (0, 180, 255),
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
        if unit.selected:
            from settings import SELECT_COLOR
            sel_rect = pygame.Rect(sx - unit.size - 2, sy - unit.size - 2,
                                   unit.size * 2 + 4, unit.size * 2 + 4)
            pygame.draw.rect(surface, SELECT_COLOR, sel_rect, 1)
            if unit.attack_range > 0:
                _draw_range_circle(surface, sx, sy, unit.attack_range)
        _draw_health_bar(surface, sx - unit.size, sy - unit.size - 6,
                         unit.size * 2, 3, unit.hp, unit.max_hp)
        if isinstance(unit, Worker):
            _draw_worker_extras(surface, unit, sx, sy)

    # AI attack lines
    for ai_unit in ai_player.units:
        if ai_unit.attacking and ai_unit.target_enemy:
            _draw_attack_line(surface, int(ai_unit.x) - cam_x, int(ai_unit.y) - cam_y,
                              ai_unit.target_enemy, cam_x, cam_y, (255, 140, 0))


def _get_placement_size(mode):
    if mode == "barracks":
        return BARRACKS_SIZE
    elif mode == "factory":
        return FACTORY_SIZE
    elif mode == "towncenter":
        return TOWN_CENTER_SIZE
    elif mode == "tower":
        return TOWER_SIZE
    elif mode == "watchguard":
        return WATCHGUARD_SIZE
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
    elif mode == "watchguard":
        return Watchguard.sprite
    return None


def _is_placement_valid(ghost_rect, state, local_team="player"):
    """Check if a building can be placed at the ghost rect position (world coords)."""
    if ghost_rect.bottom > WORLD_H or ghost_rect.top < 0:
        return False
    if ghost_rect.left < 0 or ghost_rect.right > WORLD_W:
        return False
    for existing in state.buildings:
        if ghost_rect.colliderect(existing.rect):
            return False
    for existing in state.ai_player.buildings:
        if ghost_rect.colliderect(existing.rect):
            return False
    for node in state.mineral_nodes:
        if not node.depleted and ghost_rect.colliderect(node.rect.inflate(10, 10)):
            return False
    for node in state.ai_player.mineral_nodes:
        if not node.depleted and ghost_rect.colliderect(node.rect.inflate(10, 10)):
            return False
    local_rm = state.resource_manager if local_team == "player" else state.ai_player.resource_manager
    cost = state._placement_cost()
    if not local_rm.can_afford(cost):
        return False
    has_worker = any(isinstance(u, Worker) and u.alive and u.state != "deploying"
                     for u in state.selected_units)
    if not has_worker:
        return False
    center_x = ghost_rect.centerx
    center_y = ghost_rect.centery
    if not state.is_in_placement_zone(center_x, center_y, team=local_team):
        return False
    return True


def _replay_main(filename):
    """Run the replay viewer."""
    global WIDTH, HEIGHT, MAP_HEIGHT
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
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
            elif event.type == pygame.VIDEORESIZE:
                WIDTH = event.w
                HEIGHT = event.h
                MAP_HEIGHT = HEIGHT - settings.HUD_HEIGHT
                settings.WIDTH = WIDTH
                settings.HEIGHT = HEIGHT
                settings.MAP_HEIGHT = MAP_HEIGHT
                screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
                minimap.resize()
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
        if mouse_x < SCROLL_EDGE:
            camera_x -= SCROLL_SPEED * dt
        elif mouse_x > WIDTH - SCROLL_EDGE:
            camera_x += SCROLL_SPEED * dt
        if mouse_y < SCROLL_EDGE:
            camera_y -= SCROLL_SPEED * dt
        elif mouse_y > HEIGHT - SCROLL_EDGE:
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
            big_font = get_font(72)
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

    font = get_font(24)
    small_font = get_font(18)

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
