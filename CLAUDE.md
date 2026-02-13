# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RTS (Real-Time Strategy) game built with Pygame. Two sides — player (left) and opponent (right) — mine resources, build bases, train armies, and fight. The opponent can be AI (single-player) or a remote human (multiplayer). Random natural disasters affect the entire map. Victory: destroy all opponent buildings and combat units. Defeat: lose all your units and buildings. Yanuses wave enemies exist but are currently disabled in `waves.py`.

## Commands

```bash
pip install -r requirements.txt        # Install dependencies (pygame>=2.5.0, miniupnpc>=2.0.0)
python game.py                          # Run the game (2x speed, basic AI)
python game.py --ai <name>              # Select AI profile (basic, defensive, aggressive)
python game.py --playforme              # Spectator mode: AI controls the player side
python game.py --replay replay/replay_YYYYMMDD_HHMMSS.json  # Replay viewer
python game.py --host                   # Host multiplayer game (port 7777)
python game.py --host 9999              # Host on custom port
python game.py --join <ip>              # Join multiplayer game
python game.py --join <ip> 9999         # Join on custom port
```

No tests, linting, or CI/CD exist. `gameplay.txt` is the game design spec.

## Architecture

### AI systems

- **ai_player.py (`AIPlayer`)** — The AI opponent on the right side of the map. Has its own `ResourceManager`, buildings, units, and mineral nodes. Draws with orange tint. Handles its own economy, building placement, unit training, combat targeting, scouting, attack waves, focus fire, and retreat logic. Configurable via AI profiles in `ai_profiles/`.
- **player_ai.py (`PlayerAI`)** — Only active in `--playforme` spectator mode. Controls the *player's* entities through the same `GameState` API a human would use.

### Multiplayer system

- **network.py** — UDP connection with reliable delivery layer (sequence numbers, piggybacked ACKs, 30ms retransmit), length-prefixed JSON message framing, UPnP port mapping via `miniupnpc`, `NetworkHost`/`NetworkClient` for connection setup, `NetSession` for lockstep tick management.
- **commands.py** — Serializable command definitions (move, queue_waypoint, mine, place_building, train_unit, repair) and `execute_command()` engine that applies commands to either team's entities.
- **multiplayer_state.py (`RemotePlayer`)** — Replaces `AIPlayer` in multiplayer. Same data interface (`.buildings`, `.units`, `.mineral_nodes`, `.resource_manager`) but no autonomous AI. All decisions come from the remote player's commands over the network.

**Lockstep model**: Both peers run the full simulation locally. Every 4 frames (~67ms at 60fps), both peers exchange command batches over UDP. Commands are executed on the same tick on both sides. Game runs at 1x speed in multiplayer (2x in single-player). **Input delay buffering**: commands are sent tagged for `current_tick + 1`, giving the network a full tick interval (~67ms) to deliver them before they're needed. Tick sync is **non-blocking**: if remote commands haven't arrived yet, the UI (rendering, input, camera) keeps running while simulation is paused. State vars `net_waiting` / `net_wait_start` in `game.py` track the wait across frames (5s timeout).

**Fog of war**: In multiplayer, opponent entities are only rendered when within **vision range** of the local player's units or buildings. Buildings have 500px default vision (or `attack_range` for DefenseTower). `_is_visible_to_team()` in `game.py` performs the check. Fog of war is rendering-only — the full simulation still runs on both peers for lockstep correctness.

**Entity identification**: All units and buildings have a `net_id` (sequential integer assigned by `GameState` counters). Both peers run the same counter in the same order, so IDs stay in sync. Mineral nodes use their list index. `GameState` maintains `_unit_by_net_id` / `_building_by_net_id` dicts for O(1) lookup.

**Host = "player" team (left side), Joiner = "ai" team (right side)**. Selection, placement zones, HUD resources, and input handling are all `local_team`-aware.

### Shared utilities (utils.py)

Centralised rendering helpers used across all drawing code:
- `get_font(size)` — cached font lookup (avoids per-frame `SysFont` creation).
- `tint_surface(surface, color)` — applies orange tint for AI/remote entities.
- `hp_bar_color(ratio)` — returns green/yellow/red based on HP ratio.
- `get_range_circle(radius)` — cached semi-transparent range circle surface.

### Core game loop (game.py)

`game.py` is the entry point containing the Pygame event loop, camera system, all drawing code, multiplayer connection phase, and the replay viewer. All rendering uses camera-offset helper functions (`_draw_unit_offset`, `_draw_building_offset`, etc.) — entities store world coordinates, drawing subtracts `(cam_x, cam_y)`.

Shared drawing helpers eliminate duplication: `_draw_attack_line()`, `_draw_health_bar()`, `_draw_worker_extras()`, `_draw_range_circle()`, `_get_zone_surface()`.

In multiplayer, input events generate command dicts queued via `net_session.queue_command()` instead of directly mutating game state. An FPS counter is displayed in the top-right corner.

### World & camera

- Viewport: 2000x1200 pixels (resizable). HUD: bottom 120px. Map area: top portion.
- World: 10000x5400 pixels, scrollable via mouse-edge or arrow keys.
- Camera clamped to world bounds. Earthquake disaster applies shake offset to camera.

### Game state flow

`GameState` (game_state.py) orchestrates the update loop:
1. Handle deploying workers (building construction timer).
2. Player units: worker mining/repair state machine, combat auto-targeting, waypoint movement with collision avoidance.
3. Enemy (Yanuses) movement with avoidance.
4. AI/Remote player unit movement with avoidance.
5. Stuck detection for all units (0.5s → stuck escape, 1.0s → give up waypoint).
6. Building production ticks + DefenseTower combat updates.
7. `WaveManager.update()` and `AIPlayer.update()` (or `RemotePlayer.update()` in multiplayer).
8. Dead unit/building removal, win/lose checks.

### Entity model

- **Units** (`units.py`): `Unit` base → `Soldier`, `Tank`, `Worker`, `Yanuses`. All have waypoint movement, HP, selection, combat attributes, `net_id`. `Worker` has states: `idle`, `moving_to_mine`, `waiting`, `mining`, `returning`, `deploying`, `repairing`. Workers can repair damaged entities at 5 HP/sec. Only one worker can mine a node at a time. Units have vision range (1.2x attack range) and hunt visible enemies.
- **Buildings** (`buildings.py`): `Building` base → `TownCenter`, `Barracks`, `Factory`, `DefenseTower`, `Watchguard`. Production buildings have queues with timers. `DefenseTower` has `combat_update()` for auto-targeting. `Watchguard` expands placement zone by 500px and consumes its builder worker. All buildings have `net_id` and `build_time` (construction takes time).
- **Building HP**: TownCenter=1000, Barracks=400, Factory=400, DefenseTower=1000, Watchguard=400.
- **Building placement**: Only within 500px of TownCenter/Watchguard or 100px of other buildings.
- **Sprites**: PNG assets in `assets/`, loaded via `load_assets()` classmethods after `pygame.init()`. AI/remote entities use `tint_surface()` (orange overlay). Note: `tower.png` is missing — `DefenseTower` uses fallback rendered graphics.

### Collision avoidance

`GameState._move_unit_with_avoidance()` handles all unit movement: tries direct path, then perpendicular/diagonal steering. When destination is blocked, stops adjacent. Two moving units yield by `net_id` priority. Used for player units, enemies, and AI units alike.

### Disasters (disasters.py)

`DisasterManager` spawns random disasters every 45-90 seconds. Four types:
- **Meteor**: 0.5s warning → explosion (50 damage, 150px radius) with particles.
- **Earthquake**: 5s duration, screen shake, 10 damage to all buildings, 50% unit speed reduction (restored on end).
- **Lightning**: 8s, random bolt strikes every 1-2s (40 damage + 10 splash in 30px).
- **Toxic cloud**: 12s, drifts across map, 5 damage/sec in 200px radius.

In multiplayer, disasters are deterministic via shared random seed.

### Replay system (replay.py)

`ReplayRecorder` captures state snapshots every 100ms as JSON lines in `replay/`. Always active via `atexit`. `ReplayPlayer` loads and plays back with speed control, timeline seeking, and pause.

### Mineral node distribution

Both player and AI use shared `MINERAL_OFFSETS` from settings. Player nodes: `PLAYER_TC_POS + offsets`. AI nodes: `AI_TC_POS - dx + dy` (mirrored). 10 nodes per side, 2500 resources each.

### Configuration (settings.py)

All game balance constants are centralized in `settings.py`: screen/world dimensions, unit costs and stats (HP, damage, speed, range, train time), building costs, HP, and build times, mineral node offsets and capacity, starting resources, FPS cap, colors, asset paths, multiplayer port, and tick interval.

## Key Patterns

- `dt` (delta time in seconds) passed through all `update()` methods. Single-player uses `sim_dt = dt * 2`. Multiplayer uses `sim_dt = dt` (1x speed for determinism).
- Fonts are cached via `utils.get_font(size)` — never create `pygame.font.SysFont` directly.
- HP bar colours use `utils.hp_bar_color(ratio)` — never inline the green/yellow/red logic.
- Range circles use `utils.get_range_circle(radius)` — cached SRCALPHA surfaces.
- `GameState._cached_all_units` is rebuilt once per frame for collision checks.
- Selection: either `selected_units` (list) or `selected_building` (single), never both — `deselect_all()` clears both.
- All coordinates are world-space. Screen↔world conversion via `_screen_to_world()` and camera offsets.
- `team` attribute on units/buildings: `"player"` or `"ai"`. Wave enemies use `"enemy"`.
- `local_team` variable in game.py: `"player"` for host/single-player, `"ai"` for joiner. Used for team-aware selection, placement, HUD, and commands.
- Debug: press P to pause and dump full game state to `dbug.log`.

## Controls

| Input | Action |
|-------|--------|
| T / B / F / D / G | Place Town Center / Barracks / Factory / Defense Tower / Watchguard |
| Left click | Place building / select unit or building / click minimap |
| Left drag | Box-select units / drag minimap to pan |
| Right click ground | Move selected units |
| Right click mineral node | Send selected workers to mine |
| Right click damaged friendly | Send selected workers to repair |
| Right click in placement mode | Cancel placement |
| Shift + Right click | Add waypoint |
| Arrow keys | Scroll camera |
| P | Pause + write dbug.log |
| ESC | Cancel placement / deselect / resume pause / quit on game over |

Replay viewer: Space (pause), +/- (speed), click timeline to seek, ESC (quit).
