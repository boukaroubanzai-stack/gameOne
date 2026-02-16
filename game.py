"""Main entry point: Pygame event loop, camera system, rendering, and replay viewer."""

import atexit
import pygame
import sys
import datetime
import settings
from settings import (
    WIDTH, HEIGHT, FPS, MAP_COLOR, MAP_HEIGHT, DRAG_BOX_COLOR,
    BARRACKS_SIZE, FACTORY_SIZE, TOWN_CENTER_SIZE, TOWER_SIZE, WATCHGUARD_SIZE, RADAR_SIZE,
    WORLD_W, WORLD_H, SCROLL_SPEED, SCROLL_EDGE,
    BUILDING_ZONE_TC_RADIUS, BUILDING_ZONE_BUILDING_RADIUS, WATCHGUARD_ZONE_RADIUS,
)
from utils import get_font, hp_bar_color, get_range_circle, tint_surface
from particles import ParticleManager
from game_state import GameState
from hud import HUD
from minimap import Minimap
from units import Soldier, Scout, Tank, Worker, Yanuses
from buildings import Barracks, Factory, TownCenter, DefenseTower, Watchguard, Radar
from disasters import DisasterManager
from audio import AudioManager
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
    spectator_mode = False
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
        elif arg == "--spectate" and i + 1 < len(sys.argv):
            multiplayer_mode = "spectate"
            join_ip = sys.argv[i + 1]
            spectator_mode = True
            if i + 2 < len(sys.argv) and sys.argv[i + 2].isdigit():
                mp_port = int(sys.argv[i + 2])

    # Parse AI profile selection
    ai_profile_name = "basic"
    for i, arg in enumerate(sys.argv):
        if arg == "--ai" and i + 1 < len(sys.argv):
            ai_profile_name = sys.argv[i + 1]
            break

    # Default mode: auto-host with AI subprocess (unless explicit --host/--join)
    auto_ai = False
    ai_proc = None
    if not multiplayer_mode:
        multiplayer_mode = "host"
        auto_ai = True

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    caption = "GameOne - Simple RTS"
    if spectator_mode:
        caption += " [SPECTATING]"
    elif playforme:
        caption += " [SPECTATOR]"
    elif multiplayer_mode == "host" and not auto_ai:
        caption += " [HOST]"
    elif multiplayer_mode == "join":
        caption += " [JOIN]"
    pygame.display.set_caption(caption)
    clock = pygame.time.Clock()

    # Audio
    audio = AudioManager()
    audio.play_music()
    game_over_sound_played = False

    # Load sprite assets (must happen after pygame.init())
    Soldier.load_assets()
    Scout.load_assets()
    Tank.load_assets()
    Worker.load_assets()
    Yanuses.load_assets()
    Barracks.load_assets()
    Factory.load_assets()
    TownCenter.load_assets()
    DefenseTower.load_assets()
    Watchguard.load_assets()
    Radar.load_assets()

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
        # Launch AI subprocess if auto_ai
        if auto_ai:
            import subprocess, os
            ai_proc = subprocess.Popen([
                sys.executable,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_client.py"),
                "127.0.0.1", str(mp_port),
                "--ai", ai_profile_name,
            ])
        # Waiting screen
        waiting = True
        while waiting:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                    if ai_proc:
                        ai_proc.terminate()
                        ai_proc.wait(timeout=2)
                    net_host.cleanup()
                    pygame.quit()
                    return
            if net_host.accept():
                waiting = False
            screen.fill((30, 30, 40))
            if auto_ai:
                txt = get_font(36).render("Starting AI...", True, (200, 200, 200))
            else:
                txt = get_font(36).render(f"Hosting on port {mp_port}... Waiting for peer.", True, (200, 200, 200))
            screen.blit(txt, (WIDTH // 2 - txt.get_width() // 2, HEIGHT // 2))
            pygame.display.flip()
            clock.tick(30)
        net_session = NetSession(net_host.connection, is_host=True)
        # Set up spectator relay if a spectator connected during waiting
        if net_host.spectator_connection:
            net_session.spectator_conn = net_host.spectator_connection
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
    elif multiplayer_mode == "spectate":
        from network import NetworkClient, NetSession
        # Spectator connects on port+1 (separate socket from main game)
        net_client = NetworkClient(join_ip, port=mp_port + 1)
        try:
            net_client.connect(spectator=True)
        except Exception as e:
            print(f"Failed to connect as spectator: {e}")
            pygame.quit()
            return
        net_session = NetSession(net_client.connection, is_host=False)
        net_session.is_spectator = True
        if not net_session.wait_for_handshake():
            print("Handshake failed!")
            pygame.quit()
            return
        local_team = "player"  # Spectator views from player perspective

    random_seed = net_session.random_seed if net_session else None
    state = GameState(random_seed=random_seed)
    hud = HUD()
    minimap = Minimap()
    disaster_mgr = DisasterManager(WORLD_W, WORLD_H)
    player_ai = PlayerAI() if playforme else None

    # Camera position (top-left corner of the viewport in world coords)
    # Center viewport on the local player's town center
    if local_team == "player":
        tc = state.buildings[0] if state.buildings else None
    else:
        tc = state.ai_player.buildings[0] if state.ai_player.buildings else None
    if tc:
        camera_x = float(max(0, min(tc.x + tc.w // 2 - WIDTH // 2, WORLD_W - WIDTH)))
        camera_y = float(max(0, min(tc.y + tc.h // 2 - MAP_HEIGHT // 2, WORLD_H - MAP_HEIGHT)))
    else:
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
    particle_mgr = ParticleManager()
    prev_hps = {}  # id(entity) -> hp, for damage number detection
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

    # QOL state
    control_groups = {}        # key: int 1-9, value: list of unit refs
    attack_move_mode = False   # True when 'A' pressed waiting for click
    last_click_time = 0.0      # for double-click detection
    last_click_unit = None     # unit clicked last time (for double-click)
    last_group_tap = {}        # key: group_num, value: timestamp for double-tap detection

    # Chat input state (multiplayer only)
    chat_input_active = False
    chat_input_text = ""

    # Desync detection display
    desync_warning_timer = 0.0  # counts down from 3s when desync detected

    # Pre-import commands (used for both AI and multiplayer command execution)
    from commands import execute_command
    if net_session:
        import time as _time
        # Jitter buffer: with 2-tick send-ahead, pre-populate ticks 0 and 1
        # so the first two ticks don't stall waiting for remote commands.
        net_session.remote_tick_ready = True
        net_session.remote_commands = []
        net_session.pending_remote[1] = []

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

            # Spectator mode: only allow camera movement, pause, and quit
            if spectator_mode:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_p:
                        paused = True
                        _write_debug_log(state)
                    elif event.key == pygame.K_LEFT:
                        scroll_left = True
                    elif event.key == pygame.K_RIGHT:
                        scroll_right = True
                    elif event.key == pygame.K_UP:
                        scroll_up = True
                    elif event.key == pygame.K_DOWN:
                        scroll_down = True
                    elif event.key == pygame.K_s:
                        if audio.music_playing:
                            audio.stop_music()
                        else:
                            audio.play_music()
                elif event.type == pygame.KEYUP:
                    if event.key == pygame.K_LEFT:
                        scroll_left = False
                    elif event.key == pygame.K_RIGHT:
                        scroll_right = False
                    elif event.key == pygame.K_UP:
                        scroll_up = False
                    elif event.key == pygame.K_DOWN:
                        scroll_down = False
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

            # Chat input mode: capture all keyboard input for the chat box
            if chat_input_active:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        if chat_input_text.strip() and net_session:
                            import time as _chat_send_time
                            # Send chat directly (not through lockstep)
                            net_session.conn.send_message({
                                "type": "chat",
                                "team": local_team,
                                "message": chat_input_text.strip(),
                            })
                            # Add to local chat log immediately
                            state.chat_log.append({
                                "team": local_team,
                                "message": chat_input_text.strip(),
                                "time": _chat_send_time.time(),
                            })
                        chat_input_active = False
                        chat_input_text = ""
                    elif event.key == pygame.K_ESCAPE:
                        chat_input_active = False
                        chat_input_text = ""
                    elif event.key == pygame.K_BACKSPACE:
                        chat_input_text = chat_input_text[:-1]
                    else:
                        if event.unicode and len(chat_input_text) < 100:
                            chat_input_text += event.unicode
                continue

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if attack_move_mode:
                        attack_move_mode = False
                    elif state.placement_mode:
                        state.placement_mode = None
                    else:
                        state.deselect_all()
                elif event.key in (pygame.K_b, pygame.K_f, pygame.K_t, pygame.K_d, pygame.K_g, pygame.K_r):
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
                        elif event.key == pygame.K_r:
                            state.placement_mode = "radar"
                    else:
                        floating_texts.append(FloatingText(
                            camera_x + WIDTH // 2, camera_y + MAP_HEIGHT // 2,
                            "Select a worker first!", (255, 80, 80)))
                # Multiplayer chat (Enter) and shared vision (V)
                elif event.key == pygame.K_RETURN and net_session:
                    chat_input_active = True
                    chat_input_text = ""
                # Arrow key scrolling
                elif event.key == pygame.K_LEFT:
                    scroll_left = True
                elif event.key == pygame.K_RIGHT:
                    scroll_right = True
                elif event.key == pygame.K_UP:
                    scroll_up = True
                elif event.key == pygame.K_DOWN:
                    scroll_down = True
                elif event.key == pygame.K_s:
                    if audio.music_playing:
                        audio.stop_music()
                        floating_texts.append(FloatingText(
                            camera_x + WIDTH // 2, camera_y + MAP_HEIGHT // 2,
                            "Music OFF", (200, 200, 200)))
                    else:
                        audio.play_music()
                        floating_texts.append(FloatingText(
                            camera_x + WIDTH // 2, camera_y + MAP_HEIGHT // 2,
                            "Music ON", (200, 200, 200)))
                elif event.key == pygame.K_v and not net_session:
                    # Toggle stance for selected combat units
                    toggled = 0
                    for u in state.selected_units:
                        if isinstance(u, (Soldier, Scout, Tank)):
                            u.stance = "defensive" if u.stance == "aggressive" else "aggressive"
                            toggled += 1
                    if toggled:
                        new_stance = state.selected_units[0].stance if state.selected_units else "aggressive"
                        floating_texts.append(FloatingText(
                            camera_x + WIDTH // 2, camera_y + MAP_HEIGHT // 2,
                            f"Stance: {new_stance}", (100, 200, 255)))

                # --- QOL: Control groups (Ctrl+1-9 assign, 1-9 recall) ---
                elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
                                   pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8, pygame.K_9):
                    group_num = event.key - pygame.K_0
                    mods = pygame.key.get_mods()
                    if mods & pygame.KMOD_CTRL:
                        # Assign current selection to control group
                        if state.selected_units:
                            control_groups[group_num] = list(state.selected_units)
                            floating_texts.append(FloatingText(
                                camera_x + WIDTH // 2, camera_y + 30,
                                f"Group {group_num} set ({len(state.selected_units)})", (100, 200, 255)))
                    else:
                        # Recall control group
                        if group_num in control_groups:
                            alive_units = [u for u in control_groups[group_num] if u.alive]
                            control_groups[group_num] = alive_units
                            if alive_units:
                                state.select_units(alive_units)
                                # Double-tap: center camera on group
                                now = pygame.time.get_ticks() / 1000.0
                                if group_num in last_group_tap and now - last_group_tap[group_num] < 0.3:
                                    avg_x = sum(u.x for u in alive_units) / len(alive_units)
                                    avg_y = sum(u.y for u in alive_units) / len(alive_units)
                                    camera_x = max(0, min(avg_x - WIDTH // 2, WORLD_W - WIDTH))
                                    camera_y = max(0, min(avg_y - MAP_HEIGHT // 2, WORLD_H - MAP_HEIGHT))
                                last_group_tap[group_num] = now

                # --- QOL: Attack-move mode (A key) ---
                elif event.key == pygame.K_a:
                    if state.selected_units and not state.placement_mode:
                        has_combat = any(u.attack_range > 0 for u in state.selected_units)
                        if has_combat:
                            attack_move_mode = True

                # --- QOL: Idle worker (. key) ---
                elif event.key == pygame.K_PERIOD:
                    local_units = state.units if local_team == "player" else state.ai_player.units
                    idle_workers = [u for u in local_units if isinstance(u, Worker) and u.alive and u.state == "idle"]
                    if idle_workers:
                        worker = idle_workers[0]
                        state.select_unit(worker)
                        camera_x = max(0, min(worker.x - WIDTH // 2, WORLD_W - WIDTH))
                        camera_y = max(0, min(worker.y - MAP_HEIGHT // 2, WORLD_H - MAP_HEIGHT))

                # --- QOL: Tab cycle buildings of same type ---
                elif event.key == pygame.K_TAB:
                    if state.selected_building:
                        sb = state.selected_building
                        sb_type = type(sb)
                        local_buildings = state.buildings if local_team == "player" else state.ai_player.buildings
                        same_type = [b for b in local_buildings if isinstance(b, sb_type) and b.hp > 0]
                        if len(same_type) > 1:
                            idx = same_type.index(sb) if sb in same_type else -1
                            next_b = same_type[(idx + 1) % len(same_type)]
                            state.select_building(next_b)
                            camera_x = max(0, min(next_b.x + next_b.w // 2 - WIDTH // 2, WORLD_W - WIDTH))
                            camera_y = max(0, min(next_b.y + next_b.h // 2 - MAP_HEIGHT // 2, WORLD_H - MAP_HEIGHT))

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
                        if result and result != "insufficient_funds":
                            audio.play_sound('click')
                        if result == "insufficient_funds":
                            resource_flash_timer = 0.5
                        elif isinstance(result, tuple) and result[0] == "idle_worker":
                            worker = result[1]
                            camera_x = max(0, min(worker.x - WIDTH // 2, WORLD_W - WIDTH))
                            camera_y = max(0, min(worker.y - MAP_HEIGHT // 2, WORLD_H - MAP_HEIGHT))
                        continue

                    # Convert to world coords for map interactions
                    world_pos = _screen_to_world(screen_pos, camera_x, camera_y)

                    # --- QOL: Attack-move click ---
                    if attack_move_mode and state.selected_units:
                        attack_move_mode = False
                        selected_ids = [u.net_id for u in state.selected_units]
                        if net_session:
                            net_session.queue_command({
                                "cmd": "move",
                                "unit_ids": selected_ids,
                                "x": world_pos[0], "y": world_pos[1],
                            })
                        else:
                            state.command_move(world_pos)
                        # Mark combat units as attack-moving
                        for u in state.selected_units:
                            if u.attack_range > 0:
                                u.attack_move = True
                        move_markers.append(MoveMarker(world_pos[0], world_pos[1]))
                        continue

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
                    attack_move_mode = False  # Cancel attack-move on right click
                    if state.placement_mode:
                        state.placement_mode = None
                        continue
                    screen_pos = event.pos

                    # --- QOL: Rally point — right-click with building selected ---
                    if not state.selected_units and state.selected_building:
                        sb = state.selected_building
                        if hasattr(sb, 'rally_x'):
                            if not hud.is_in_hud(screen_pos):
                                world_pos = _screen_to_world(screen_pos, camera_x, camera_y)
                                sb.rally_x = world_pos[0]
                                sb.rally_y = world_pos[1]
                                move_markers.append(MoveMarker(world_pos[0], world_pos[1]))
                        continue

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
                        # Clear attack-move flag on normal move
                        for u in state.selected_units:
                            u.attack_move = False
                        move_markers.append(MoveMarker(world_pos[0], world_pos[1]))

                elif event.button == 2:  # Middle click — minimap ping
                    ping_world = minimap.minimap_to_world(event.pos)
                    if ping_world:
                        minimap.add_ping(ping_world[0], ping_world[1])

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
                            audio.play_sound('select')
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
                            # --- QOL: Double-click to select all same type on screen ---
                            import time as _click_time
                            now = _click_time.time()
                            if (last_click_unit is not None and type(unit) is type(last_click_unit)
                                    and now - last_click_time < 0.3):
                                vis = pygame.Rect(cam_x, cam_y, WIDTH, MAP_HEIGHT)
                                local_units = state.units if local_team == "player" else state.ai_player.units
                                same_type = [u for u in local_units if type(u) is type(unit) and u.alive
                                             and vis.collidepoint(int(u.x), int(u.y))]
                                if same_type:
                                    state.select_units(same_type)
                                last_click_unit = None
                                last_click_time = 0.0
                            else:
                                state.select_unit(unit)
                                last_click_unit = unit
                                last_click_time = now
                            audio.play_sound('select')
                        else:
                            last_click_unit = None
                            last_click_time = 0.0
                            if net_session:
                                building = state.get_local_building_at(click_world, local_team)
                            else:
                                building = state.get_building_at(click_world)
                            if building:
                                state.select_building(building)
                                audio.play_sound('select')
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
                global _interp_t

                # Helper to execute commands after tick ready
                def _execute_tick_commands():
                    state.snapshot_positions()
                    if spectator_mode:
                        # Spectator: execute both teams' commands separately
                        p_cmds = getattr(net_session, '_spectator_player_cmds', [])
                        a_cmds = getattr(net_session, '_spectator_ai_cmds', [])
                        for cmd in p_cmds:
                            execute_command(cmd, state, "player")
                        for cmd in a_cmds:
                            execute_command(cmd, state, "ai")
                    else:
                        # Always execute player commands first for determinism
                        if local_team == "player":
                            player_cmds = net_session.local_commands
                            ai_cmds = net_session.remote_commands
                        else:
                            player_cmds = net_session.remote_commands
                            ai_cmds = net_session.local_commands
                        for cmd in player_cmds:
                            execute_command(cmd, state, "player")
                        for cmd in ai_cmds:
                            execute_command(cmd, state, "ai")
                        # Relay to spectator if host
                        if net_session.spectator_conn:
                            net_session.relay_to_spectator(
                                net_session.current_tick,
                                player_cmds,
                                ai_cmds,
                            )

                if spectator_mode:
                    # Spectator: never sends, only receives
                    net_session.receive_and_process()
                    if not net_session.connected:
                        running = False
                    elif net_session.remote_tick_ready:
                        _execute_tick_commands()
                        net_session.advance_tick()
                        net_waiting = False
                    # No timeout for spectator — just keep waiting
                elif net_waiting:
                    # Poll for remote commands without blocking
                    net_session.receive_and_process()
                    if not net_session.connected:
                        running = False
                    elif net_session.remote_tick_ready:
                        _execute_tick_commands()
                        net_session.advance_tick()
                        net_waiting = False
                    elif _time.time() - net_wait_start > 5.0:
                        print("Peer timed out!")
                        running = False
                else:
                    net_session.increment_frame()
                    if net_session.is_tick_frame():
                        # Compute sync hash before sending
                        net_session.sync_hash = state.compute_sync_hash()
                        net_session.sync_hash_tick = net_session.current_tick
                        # Check against remote hash for same tick
                        remote = net_session.remote_sync_hashes.pop(net_session.current_tick, None)
                        if remote is not None and remote != net_session.sync_hash:
                            net_session.desync_detected = True
                        net_session.end_tick_and_send()
                        net_session.receive_and_process()
                        if not net_session.connected:
                            running = False
                        elif net_session.remote_tick_ready:
                            _execute_tick_commands()
                            net_session.advance_tick()
                        else:
                            net_waiting = True
                            net_wait_start = _time.time()
                    else:
                        net_session.receive_and_process()
                        if not net_session.connected:
                            running = False

                # Drain chat messages from network
                for chat_msg in net_session.chat_messages:
                    state.chat_log.append({
                        "team": chat_msg.get("team", net_session.remote_team),
                        "message": chat_msg.get("message", ""),
                        "time": _time.time(),
                    })
                net_session.chat_messages.clear()

                # Desync warning timer
                if net_session.desync_detected:
                    desync_warning_timer = 3.0
                    net_session.desync_detected = False
                if desync_warning_timer > 0:
                    desync_warning_timer -= dt

                # Check for late spectator connections (host only)
                if net_session.is_host and not net_session.spectator_conn:
                    try:
                        net_host.accept()  # polls spectator socket
                        if net_host.spectator_connection:
                            net_session.spectator_conn = net_host.spectator_connection
                    except Exception:
                        pass

                # Compute interpolation fraction between ticks
                _interp_t = (net_session.frame_counter % net_session.tick_interval) / net_session.tick_interval

            # Only advance simulation when not waiting for remote peer
            if not net_waiting:
                # PlayerAI think phase: generate commands (--playforme only)
                if player_ai is not None:
                    player_ai.think(sim_dt, state, state.wave_manager.enemies, state.ai_player)
                    for cmd in player_ai.drain_commands():
                        net_session.queue_command(cmd)

                state.update(sim_dt)

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

        # Process pending deaths → spawn particles + sound
        for dx, dy, team, kind in state.pending_deaths:
            if kind == "building":
                particle_mgr.spawn_building_death(dx, dy)
            else:
                particle_mgr.spawn_death(dx, dy, team)
            audio.play_sound('explosion')
        state.pending_deaths.clear()

        # Spawn damage numbers by detecting HP decreases
        curr_hps = {}
        all_entities = (state.units + state.ai_player.units +
                        state.wave_manager.enemies +
                        state.buildings + state.ai_player.buildings)
        for e in all_entities:
            eid = id(e)
            hp = e.hp
            curr_hps[eid] = hp
            if eid in prev_hps and hp < prev_hps[eid]:
                dmg = int(prev_hps[eid] - hp)
                if hasattr(e, 'w'):  # building
                    ex, ey = e.x + e.w // 2, e.y + e.h // 2
                else:
                    ex, ey = e.x, e.y
                particle_mgr.spawn_damage_number(ex, ey, dmg)
        prev_hps = curr_hps

        particle_mgr.update(dt)
        minimap.update_pings(dt)

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

        # Draw terrain obstacles
        for rx, ry, rw, rh in state.terrain_rects:
            ox = rx - cam_x
            oy = ry - cam_y
            if -rw < ox < WIDTH and -rh < oy < MAP_HEIGHT:
                pygame.draw.rect(screen, (60, 50, 40), (ox, oy, rw, rh))
                pygame.draw.rect(screen, (45, 38, 30), (ox, oy, rw, rh), 2)

        # Helper to check if a world-space rect is visible on screen
        visible_rect = pygame.Rect(cam_x - 100, cam_y - 100, WIDTH + 200, MAP_HEIGHT + 200)

        # Fog of war: opponent entities only visible within vision range
        if local_team == "player":
            my_units, my_buildings = state.units, state.buildings
            my_nodes = state.mineral_nodes
        else:
            my_units, my_buildings = state.ai_player.units, state.ai_player.buildings
            my_nodes = state.ai_player.mineral_nodes

        # Draw own mineral nodes (always visible)
        for node in my_nodes:
            if visible_rect.collidepoint(node.x, node.y):
                _draw_mineral_node_offset(screen, node, cam_x, cam_y)

        # Draw own buildings (always visible)
        for building in my_buildings:
            if visible_rect.colliderect(building.rect):
                _draw_building_offset(screen, building, cam_x, cam_y)

        # Draw construction ghosts for deploying workers (both teams)
        for u in state.units + state.ai_player.units:
            if isinstance(u, Worker) and u.state == "deploying" and u.deploy_building and u.deploy_building_class:
                _draw_construction_ghost(screen, u, cam_x, cam_y)

        # Draw own units (always visible)
        for unit in my_units:
            ix, iy = _interp_unit_pos(unit)
            if visible_rect.collidepoint(int(ix), int(iy)):
                _draw_unit_offset(screen, unit, cam_x, cam_y)
            if unit.attacking and unit.target_enemy:
                _draw_attack_line(screen, int(ix) - cam_x, int(iy) - cam_y,
                                  unit.target_enemy, cam_x, cam_y, (255, 255, 0))

        # Draw opponent entities (only if within vision range of own units/buildings)
        if spectator_mode:
            # Spectator sees everything — no fog filtering
            _draw_ai_player_offset(screen, state.ai_player, cam_x, cam_y, visible_rect)
        elif local_team == "player":
            _draw_ai_player_offset(screen, state.ai_player, cam_x, cam_y, visible_rect,
                                   fog_units=my_units, fog_buildings=my_buildings)
        else:
            # Opponent is state.units/buildings/mineral_nodes — draw with fog filter + orange tint
            for node in state.mineral_nodes:
                if visible_rect.collidepoint(node.x, node.y) and \
                   (_is_visible_to_team(node.x, node.y, my_units, my_buildings)):
                    _draw_mineral_node_offset(screen, node, cam_x, cam_y)
            for building in state.buildings:
                if visible_rect.colliderect(building.rect):
                    bx = building.x + building.w * 0.5
                    by = building.y + building.h * 0.5
                    if _is_visible_to_team(bx, by, my_units, my_buildings):
                        ox = building.x - cam_x
                        oy = building.y - cam_y
                        tinted = _get_opponent_tinted(building.sprite) if building.sprite else None
                        if tinted:
                            screen.blit(tinted, (ox, oy))
                        else:
                            _draw_building_offset(screen, building, cam_x, cam_y)
                            continue
                        _draw_health_bar(screen, ox, oy - 8, building.w, 4,
                                         building.hp, building.max_hp)
                        label = get_font(18).render(building.label, True, (255, 180, 100))
                        label_rect = label.get_rect(center=(ox + building.w // 2, oy - 16))
                        screen.blit(label, label_rect)
                        if building.production_queue:
                            prog_y = oy + building.h + 2
                            pygame.draw.rect(screen, (60, 60, 60),
                                             (ox, prog_y, building.w, 4))
                            prog = building.production_progress
                            pygame.draw.rect(screen, (0, 180, 255),
                                             (ox, prog_y, int(building.w * prog), 4))
            for unit in state.units:
                ix, iy = _interp_unit_pos(unit)
                if visible_rect.collidepoint(int(ix), int(iy)) and \
                   (_is_visible_to_team(ix, iy, my_units, my_buildings)):
                    sx = int(ix) - cam_x
                    sy = int(iy) - cam_y
                    tinted = _get_opponent_tinted(unit.sprite) if unit.sprite else None
                    if tinted:
                        r = tinted.get_rect(center=(sx, sy))
                        screen.blit(tinted, r)
                    else:
                        _draw_unit_offset(screen, unit, cam_x, cam_y)
                        continue
                    _draw_health_bar(screen, sx - unit.size, sy - unit.size - 6,
                                     unit.size * 2, 3, unit.hp, unit.max_hp)
                    if isinstance(unit, Worker):
                        _draw_worker_extras(screen, unit, sx, sy)
                if unit.attacking and unit.target_enemy:
                    _draw_attack_line(screen, int(ix) - cam_x, int(iy) - cam_y,
                                      unit.target_enemy, cam_x, cam_y, (255, 140, 0))

        # Draw enemies (with camera offset)
        for enemy in state.wave_manager.enemies:
            ex, ey = _interp_unit_pos(enemy)
            if visible_rect.collidepoint(int(ex), int(ey)):
                _draw_unit_offset(screen, enemy, cam_x, cam_y)
            if enemy.attacking and enemy.target_enemy:
                _draw_attack_line(screen, int(ex) - cam_x, int(ey) - cam_y,
                                  enemy.target_enemy, cam_x, cam_y, (255, 80, 80))

        # Draw dying units (fade-out animation)
        for unit, timer in state.dying_units:
            _draw_dying_unit(screen, unit, timer, cam_x, cam_y)
        for unit, timer in state.dying_ai_units:
            _draw_dying_unit(screen, unit, timer, cam_x, cam_y)

        # Draw disaster effects (with camera offset)
        disaster_mgr.draw(screen, cam_x, cam_y)

        # Draw particles and damage numbers (with camera offset)
        particle_mgr.draw(screen, cam_x, cam_y)

        # Fog of war dark overlay (skip for spectator — they see everything)
        if not spectator_mode:
            fog_surf = pygame.Surface((WIDTH, MAP_HEIGHT), pygame.SRCALPHA)
            fog_surf.fill((0, 0, 0, 140))
            for u in my_units:
                vr = u.vision_range
                if vr > 0:
                    ux, uy = _interp_unit_pos(u)
                    sx = int(ux) - cam_x
                    sy = int(uy) - cam_y
                    pygame.draw.circle(fog_surf, (0, 0, 0, 0), (sx, sy), int(vr))
            for b in my_buildings:
                vr = _get_building_vision(b)
                bx = int(b.x + b.w * 0.5) - cam_x
                by = int(b.y + b.h * 0.5) - cam_y
                pygame.draw.circle(fog_surf, (0, 0, 0, 0), (bx, by), int(vr))
            screen.blit(fog_surf, (0, 0))

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
                ux, uy = _interp_unit_pos(unit)
                points = [(int(ux) - cam_x, int(uy) - cam_y)] + \
                         [(int(wx) - cam_x, int(wy) - cam_y) for wx, wy in unit.waypoints]
                if len(points) >= 2:
                    pygame.draw.lines(screen, (255, 255, 0), False, points, 1)
                for wx, wy in unit.waypoints:
                    pygame.draw.circle(screen, (255, 255, 0),
                                       (int(wx) - cam_x, int(wy) - cam_y), 3, 1)

        # --- QOL: Rally point visualization ---
        if state.selected_building and hasattr(state.selected_building, 'rally_x'):
            sb = state.selected_building
            bcx = int(sb.x + sb.w // 2) - cam_x
            bcy = int(sb.y + sb.h // 2) - cam_y
            rx = int(sb.rally_x) - cam_x
            ry = int(sb.rally_y) - cam_y
            rally_surf = pygame.Surface((WIDTH, MAP_HEIGHT), pygame.SRCALPHA)
            pygame.draw.line(rally_surf, (0, 200, 255, 160), (bcx, bcy), (rx, ry), 2)
            pygame.draw.circle(rally_surf, (0, 200, 255, 200), (rx, ry), 6, 2)
            pygame.draw.line(rally_surf, (0, 200, 255, 200), (rx, ry - 6), (rx, ry + 6), 1)
            screen.blit(rally_surf, (0, 0))

        # --- QOL: Attack-move cursor indicator ---
        if attack_move_mode:
            amx, amy = pygame.mouse.get_pos()
            am_surf = pygame.Surface((24, 24), pygame.SRCALPHA)
            pygame.draw.circle(am_surf, (255, 60, 60, 180), (12, 12), 10, 2)
            pygame.draw.line(am_surf, (255, 60, 60, 180), (12, 4), (12, 20), 2)
            pygame.draw.line(am_surf, (255, 60, 60, 180), (4, 12), (20, 12), 2)
            screen.blit(am_surf, (amx - 12, amy - 12))
            am_text = get_font(16).render("Attack Move", True, (255, 100, 100))
            screen.blit(am_text, (amx + 14, amy - 8))

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
        has_radar = any(isinstance(b, Radar) for b in my_buildings)
        fog_fn = lambda ex, ey: _is_visible_to_team(ex, ey, my_units, my_buildings)
        minimap.draw(screen, state, camera_x, camera_y,
                     local_team=local_team, fog_visible_fn=fog_fn, has_radar=has_radar)

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
            if not game_over_sound_played:
                game_over_sound_played = True
                audio.stop_music()
                audio.play_sound('victory' if state.game_result == "victory" else 'defeat')
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

        # Chat messages (top-left corner, multiplayer only)
        if net_session and state.chat_log:
            import time as _chat_time
            now = _chat_time.time()
            recent = [m for m in state.chat_log[-5:] if now - m["time"] < 8.0]
            chat_y = 30
            for msg in recent:
                age = now - msg["time"]
                alpha = 255 if age < 5.0 else int(255 * (1.0 - (age - 5.0) / 3.0))
                alpha = max(0, min(255, alpha))
                if msg["team"] == "system":
                    color = (200, 200, 100)
                    prefix = ""
                elif msg["team"] == local_team:
                    color = (100, 200, 255)
                    prefix = "You: "
                else:
                    color = (255, 160, 80)
                    prefix = "Opponent: "
                text_surf = get_font(20).render(f"{prefix}{msg['message']}", True, color)
                text_surf.set_alpha(alpha)
                bg = pygame.Surface((text_surf.get_width() + 8, text_surf.get_height() + 4), pygame.SRCALPHA)
                bg.fill((0, 0, 0, int(120 * alpha / 255)))
                screen.blit(bg, (8, chat_y - 2))
                screen.blit(text_surf, (12, chat_y))
                chat_y += text_surf.get_height() + 4

        # Chat input box
        if chat_input_active:
            input_y = MAP_HEIGHT - 30 if MAP_HEIGHT > 40 else 10
            box_w = min(400, WIDTH - 20)
            box_bg = pygame.Surface((box_w, 26), pygame.SRCALPHA)
            box_bg.fill((0, 0, 0, 180))
            screen.blit(box_bg, (10, input_y))
            pygame.draw.rect(screen, (100, 200, 255), (10, input_y, box_w, 26), 1)
            prompt = get_font(18).render(f"Chat: {chat_input_text}_", True, (255, 255, 255))
            screen.blit(prompt, (14, input_y + 3))

        # Desync warning (top-center, red)
        if net_session and desync_warning_timer > 0:
            desync_text = get_font(28).render("DESYNC DETECTED", True, (255, 50, 50))
            desync_rect = desync_text.get_rect(center=(WIDTH // 2, 20))
            desync_bg = pygame.Surface((desync_text.get_width() + 12, desync_text.get_height() + 6), pygame.SRCALPHA)
            desync_bg.fill((0, 0, 0, 180))
            screen.blit(desync_bg, (desync_rect.x - 6, desync_rect.y - 3))
            screen.blit(desync_text, desync_rect)

        # Spectator label (top-center)
        if spectator_mode:
            spec_text = get_font(24).render("SPECTATING", True, (200, 200, 100))
            spec_rect = spec_text.get_rect(center=(WIDTH // 2, 50 if desync_warning_timer > 0 else 20))
            spec_bg = pygame.Surface((spec_text.get_width() + 10, spec_text.get_height() + 4), pygame.SRCALPHA)
            spec_bg.fill((0, 0, 0, 140))
            screen.blit(spec_bg, (spec_rect.x - 5, spec_rect.y - 2))
            screen.blit(spec_text, spec_rect)

        # FPS counter (top-right corner)
        fps_text = get_font(18).render(f"{int(clock.get_fps())} f/s", True, (200, 200, 200))
        screen.blit(fps_text, (WIDTH - fps_text.get_width() - 10, 10))

        pygame.display.flip()
    finally:
        recorder.save()
        if auto_ai and ai_proc:
            ai_proc.terminate()
            try:
                ai_proc.wait(timeout=2)
            except Exception:
                ai_proc.kill()
        if net_session:
            net_session.close()
        if net_cleanup:
            net_cleanup()

    pygame.quit()
    sys.exit()


# --- Fog of war visibility check ---

_FOW_BUILDING_VISION = 500  # default vision range for buildings

def _get_building_vision(b):
    """Return vision range for a building. Radar has explicit vision_range,
    DefenseTower uses attack_range, others use default 500px."""
    if hasattr(b, 'vision_range') and b.vision_range > 0:
        return b.vision_range
    if hasattr(b, 'attack_range') and b.attack_range > 0:
        return b.attack_range
    return _FOW_BUILDING_VISION

def _is_visible_to_team(ex, ey, friendly_units, friendly_buildings):
    """Check if world position (ex, ey) is within vision range of any friendly entity."""
    for u in friendly_units:
        vr = u.vision_range
        if vr > 0 and (u.x - ex) ** 2 + (u.y - ey) ** 2 <= vr * vr:
            return True
    for b in friendly_buildings:
        vr = _get_building_vision(b)
        bx = b.x + b.w * 0.5
        by = b.y + b.h * 0.5
        if (bx - ex) ** 2 + (by - ey) ** 2 <= vr * vr:
            return True
    return False


# --- Interpolation state for smooth multiplayer rendering ---
_interp_t = 1.0  # 0..1 fraction between prev and current tick positions


def _interp_unit_pos(unit):
    """Return interpolated (x, y) for a unit based on _interp_t."""
    t = _interp_t
    if t >= 1.0:
        return unit.x, unit.y
    return unit._prev_x + (unit.x - unit._prev_x) * t, unit._prev_y + (unit.y - unit._prev_y) * t


# --- Shared drawing helpers (eliminate duplication) ---

def _draw_attack_line(surface, attacker_sx, attacker_sy, target, cam_x, cam_y, color, width=1):
    """Draw a firing line from attacker screen-pos to target screen-pos."""
    if hasattr(target, 'size'):
        ix, iy = _interp_unit_pos(target)
        tx, ty = int(ix) - cam_x, int(iy) - cam_y
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


_opponent_tint_cache = {}

def _get_opponent_tinted(sprite):
    """Return orange-tinted version of a sprite, cached by sprite id."""
    key = id(sprite)
    if key not in _opponent_tint_cache:
        _opponent_tint_cache[key] = tint_surface(sprite, (255, 200, 160))
    return _opponent_tint_cache[key]


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
    ix, iy = _interp_unit_pos(unit)
    sx = int(ix) - cam_x
    sy = int(iy) - cam_y

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

    # Stance indicator for defensive units
    if hasattr(unit, 'stance') and unit.stance == "defensive":
        from utils import get_font
        d_label = get_font(12).render("D", True, (100, 150, 255))
        surface.blit(d_label, (sx - d_label.get_width() // 2, sy - unit.size - 18))

    _draw_health_bar(surface, sx - unit.size, sy - unit.size - 6,
                     unit.size * 2, 3, unit.hp, unit.max_hp, HEALTH_BAR_BG)

    if isinstance(unit, Worker):
        _draw_worker_extras(surface, unit, sx, sy)


def _draw_construction_ghost(surface, worker, cam_x, cam_y):
    """Draw a translucent ghost of the building being constructed by a deploying worker."""
    bclass = worker.deploy_building_class
    tx, ty = worker.deploy_target
    temp = bclass(tx, ty)
    ox = tx - cam_x
    oy = ty - cam_y
    # Translucent building rectangle
    ghost_surf = pygame.Surface((temp.w, temp.h), pygame.SRCALPHA)
    color = (100, 180, 255, 80) if worker.team == "player" else (255, 180, 100, 80)
    ghost_surf.fill(color)
    surface.blit(ghost_surf, (ox, oy))
    pygame.draw.rect(surface, (*color[:3], 160), (ox, oy, temp.w, temp.h), 2)
    # Label
    label = get_font(16).render(temp.label, True, (*color[:3], 160))
    label_rect = label.get_rect(center=(ox + temp.w // 2, oy + temp.h // 2))
    surface.blit(label, label_rect)
    # Progress bar below ghost
    build_time = bclass.build_time
    progress = min(worker.deploy_build_timer / build_time, 1.0) if build_time > 0 else 1.0
    bar_y = oy + temp.h + 2
    pygame.draw.rect(surface, (60, 60, 60), (ox, bar_y, temp.w, 4))
    pygame.draw.rect(surface, (0, 180, 255), (ox, bar_y, int(temp.w * progress), 4))


_DEATH_TIMER_MAX = 0.6


def _draw_dying_unit(surface, unit, timer, cam_x, cam_y):
    """Draw a dying unit fading out over its death timer."""
    alpha = int(255 * (timer / _DEATH_TIMER_MAX))
    sx = int(unit.x) - cam_x
    sy = int(unit.y) - cam_y
    if unit.sprite:
        temp = unit.sprite.copy()
        temp.set_alpha(alpha)
        r = temp.get_rect(center=(sx, sy))
        surface.blit(temp, r)
    else:
        size = unit.size
        circ_surf = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
        c = getattr(unit, 'color', (200, 200, 200))
        pygame.draw.circle(circ_surf, (*c, alpha), (size, size), size)
        surface.blit(circ_surf, (sx - size, sy - size))


def _draw_ai_player_offset(surface, ai_player, cam_x, cam_y, visible_rect,
                           fog_units=None, fog_buildings=None):
    """Draw all AI player entities with camera offset and orange tint.

    If fog_units/fog_buildings are provided, only draw entities visible to those
    friendly entities (fog of war for multiplayer).
    """
    ai_player._tinted_cache.ensure_ready()
    fog = fog_units is not None

    # AI mineral nodes
    for node in ai_player.mineral_nodes:
        if visible_rect.collidepoint(node.x, node.y):
            if fog and not _is_visible_to_team(node.x, node.y, fog_units, fog_buildings):
                continue
            _draw_mineral_node_offset(surface, node, cam_x, cam_y)

    # AI buildings
    for building in ai_player.buildings:
        if not visible_rect.colliderect(building.rect):
            continue
        if fog:
            bx = building.x + building.w * 0.5
            by = building.y + building.h * 0.5
            if not _is_visible_to_team(bx, by, fog_units, fog_buildings):
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
        ix, iy = _interp_unit_pos(unit)
        if not visible_rect.collidepoint(int(ix), int(iy)):
            continue
        if fog and not _is_visible_to_team(ix, iy, fog_units, fog_buildings):
            continue
        sx = int(ix) - cam_x
        sy = int(iy) - cam_y
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
            aix, aiy = _interp_unit_pos(ai_unit)
            if fog and not _is_visible_to_team(aix, aiy, fog_units, fog_buildings):
                continue
            _draw_attack_line(surface, int(aix) - cam_x, int(aiy) - cam_y,
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
    elif mode == "radar":
        return RADAR_SIZE
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
    elif mode == "radar":
        return Radar.sprite
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
    Scout.load_assets()
    Tank.load_assets()
    Worker.load_assets()
    Yanuses.load_assets()
    Barracks.load_assets()
    Factory.load_assets()
    TownCenter.load_assets()
    DefenseTower.load_assets()
    Watchguard.load_assets()
    Radar.load_assets()

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
