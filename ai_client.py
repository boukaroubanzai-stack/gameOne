"""Headless AI client: connects to a hosted game and plays as the AI opponent via UDP."""

import os
import sys
import time
import random

# Headless pygame: no display or audio
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()
pygame.display.set_mode((1, 1))

from network import NetworkClient, NetSession
from game_state import GameState
from ai_player import AIPlayer
from disasters import DisasterManager
from commands import execute_command
from settings import WORLD_W, WORLD_H, FPS


def _sync_brain(brain, state):
    """Point the brain's entity refs at the RemotePlayer's live data."""
    brain.units = state.ai_player.units
    brain.buildings = state.ai_player.buildings
    brain.mineral_nodes = state.ai_player.mineral_nodes
    brain.resource_manager = state.ai_player.resource_manager


def main():
    # Parse CLI: ai_client.py <host_ip> [port] [--ai <profile>]
    if len(sys.argv) < 2:
        print("Usage: ai_client.py <host_ip> [port] [--ai <profile>]")
        sys.exit(1)

    host_ip = sys.argv[1]
    port = 7777
    ai_profile_name = "basic"

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--ai" and i + 1 < len(sys.argv):
            ai_profile_name = sys.argv[i + 1]
            i += 2
        elif sys.argv[i].isdigit():
            port = int(sys.argv[i])
            i += 1
        else:
            i += 1

    # Load AI profile
    from ai_profiles import load_profile
    ai_profile = load_profile(ai_profile_name)

    # Connect to host
    client = NetworkClient(host_ip, port=port)
    try:
        client.connect()
    except Exception as e:
        print(f"Failed to connect: {e}")
        sys.exit(1)

    net_session = NetSession(client.connection, is_host=False)
    if not net_session.wait_for_handshake():
        print("Handshake failed!")
        sys.exit(1)

    local_team = "ai"  # Joiner is always "ai" team

    # Create game state with shared random seed
    state = GameState(random_seed=net_session.random_seed)
    disaster_mgr = DisasterManager(WORLD_W, WORLD_H)

    # Create headless AI brain (no entities — synced from RemotePlayer)
    ai_brain = AIPlayer(profile=ai_profile, headless=True)
    _sync_brain(ai_brain, state)

    clock = pygame.time.Clock()
    net_waiting = False
    net_wait_start = 0.0

    # Jitter buffer: with 2-tick send-ahead, pre-populate ticks 0 and 1
    # so the first two ticks don't stall waiting for remote commands.
    net_session.remote_tick_ready = True
    net_session.remote_commands = []
    net_session.pending_remote[1] = []

    running = True
    try:
        while running:
            dt = clock.tick(FPS) / 1000.0
            sim_dt = dt  # Multiplayer runs at 1x speed

            pygame.event.pump()  # prevent event queue buildup

            # --- AI think (every non-waiting frame) ---
            if not net_waiting:
                _sync_brain(ai_brain, state)
                # Save random state so AI decisions don't desync deterministic simulation
                rng_state = random.getstate()
                ai_brain.think(sim_dt, state.units, state.buildings)
                random.setstate(rng_state)
                # Clean up stale tracking IDs
                alive_ids = {id(u) for u in ai_brain.units if u.alive}
                ai_brain._attacking_units &= alive_ids
                ai_brain._garrison_units &= alive_ids
                ai_brain._scouting_units &= alive_ids

            # Helper: execute commands in deterministic order (player first)
            def _execute_tick():
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

            # --- Multiplayer tick sync ---
            if net_waiting:
                net_session.receive_and_process()
                if not net_session.connected:
                    running = False
                elif net_session.remote_tick_ready:
                    _execute_tick()
                    net_session.advance_tick()
                    net_waiting = False
                elif time.time() - net_wait_start > 5.0:
                    print("Peer timed out!")
                    running = False
            else:
                net_session.increment_frame()
                if net_session.is_tick_frame():
                    # Drain AI commands and queue for network
                    for cmd in ai_brain.drain_commands():
                        net_session.queue_command(cmd)

                    # Compute sync hash before sending
                    net_session.sync_hash = state.compute_sync_hash()
                    net_session.end_tick_and_send()
                    net_session.receive_and_process()
                    if not net_session.connected:
                        running = False
                    elif net_session.remote_tick_ready:
                        _execute_tick()
                        net_session.advance_tick()
                    else:
                        net_waiting = True
                        net_wait_start = time.time()
                else:
                    net_session.receive_and_process()
                    if not net_session.connected:
                        running = False

            # --- Advance simulation when not waiting ---
            if not net_waiting:
                state.update(sim_dt)
                all_units = state.units + state.wave_manager.enemies + state.ai_player.units
                all_buildings = state.buildings + state.ai_player.buildings
                disaster_mgr.update(sim_dt, all_units, all_buildings)

            # Check game over
            if state.game_over:
                running = False
    finally:
        net_session.close()
        pygame.quit()


if __name__ == "__main__":
    main()
