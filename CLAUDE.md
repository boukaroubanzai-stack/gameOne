# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RTS (Real-Time Strategy) game built with Pygame. Two sides — player (left) and AI opponent (right) — mine resources, build bases, train armies, and fight. Random natural disasters affect the entire map. Victory: destroy all AI buildings and combat units. Defeat: lose all player units and buildings. Yanuses wave enemies exist but are currently disabled in `waves.py`.

## Commands

```bash
pip install -r requirements.txt        # Install dependencies (pygame>=2.5.0)
python game.py                          # Run the game
python game.py --playforme              # Spectator mode: AI controls the player side (20x speed)
python game.py --replay replay/replay_YYYYMMDD_HHMMSS.json  # Replay viewer
```

No tests, linting, or CI/CD exist. `gameplay.txt` is the original game design spec.

## Architecture

### Two distinct AI systems

- **ai_player.py (`AIPlayer`)** — The AI opponent on the right side of the map. Has its own `ResourceManager`, buildings, units, and mineral nodes. Draws with orange tint. Handles its own economy, building placement, unit training, combat targeting, scouting, attack waves, focus fire, and retreat logic. Thinks every 1 second.
- **player_ai.py (`PlayerAI`)** — Only active in `--playforme` spectator mode. Controls the *player's* entities through the same `GameState` API a human would use. Same strategic logic (economy → military → attack phases) but operates on `state.buildings`/`state.units` instead of its own collections.

### Core game loop (game.py)

`game.py` is the entry point containing the Pygame event loop, camera system, all drawing code, and the replay viewer. All rendering uses camera-offset helper functions (`_draw_unit_offset`, `_draw_building_offset`, etc.) — entities store world coordinates, drawing subtracts `(cam_x, cam_y)`.

### World & camera

- Viewport: 2000x1200 pixels. HUD: bottom 120px. Map area: top 1080px.
- World: 10000x5400 pixels, scrollable via mouse-edge (30px margin) or arrow keys.
- Camera clamped to world bounds. Earthquake disaster applies shake offset to camera.

### Game state flow

`GameState` (game_state.py) orchestrates the update loop:
1. Player units: worker mining state machine, combat auto-targeting against `enemies + ai_player.units`, waypoint movement with collision avoidance.
2. Enemy (Yanuses) movement with avoidance.
3. AI unit movement with avoidance.
4. Stuck detection for all units (0.5s → stuck escape, 1.0s → give up waypoint).
5. Building production ticks + DefenseTower combat updates.
6. `WaveManager.update()` and `AIPlayer.update()`.
7. Dead unit/building removal, win/lose checks.

### Entity model

- **Units** (`units.py`): `Unit` base → `Soldier`, `Tank`, `Worker`, `Yanuses`. All have waypoint movement, HP, selection, combat attributes. `Worker` has a 5-state mining machine: `idle → moving_to_mine → waiting → mining → returning → moving_to_mine`. Only one worker can mine a node at a time.
- **Buildings** (`buildings.py`): `Building` base → `TownCenter`, `Barracks`, `Factory`, `DefenseTower`. Production buildings have queues with timers. `DefenseTower` has no production — instead has `combat_update()` for auto-targeting enemies in range.
- **Sprites**: PNG assets in `assets/`, loaded via `load_assets()` classmethods after `pygame.init()`. AI entities use `tint_surface()` (orange overlay) from `ai_player.py`. Note: `tower.png` is missing — `DefenseTower` uses fallback rendered graphics.

### Collision avoidance

`GameState._move_unit_with_avoidance()` handles all unit movement: tries direct path, then perpendicular/diagonal steering. When destination is blocked, stops adjacent. Two moving units yield by `id()` priority. Used for player units, enemies, and AI units alike.

### Disasters (disasters.py)

`DisasterManager` spawns random disasters every 45-90 seconds. Four types:
- **Meteor**: 0.5s warning → explosion (50 damage, 150px radius) with particles.
- **Earthquake**: 5s duration, screen shake, 10 damage to all buildings, 50% unit speed reduction (restored on end).
- **Lightning**: 8s, random bolt strikes every 1-2s (40 damage + 10 splash in 30px).
- **Toxic cloud**: 12s, drifts across map, 5 damage/sec in 200px radius.

### Replay system (replay.py)

`ReplayRecorder` captures state snapshots every 100ms as JSON lines in `replay/`. Always active via `atexit`. `ReplayPlayer` loads and plays back with speed control, timeline seeking, and pause. Proxy classes (`ReplayUnit`, `ReplayBuilding`, `ReplayNode`, `ReplayAIPlayer`, `ReplayState`) satisfy the drawing functions' attribute requirements.

### Mineral node distribution

Both player and AI use shared `MINERAL_OFFSETS` from settings. Player nodes: `PLAYER_TC_POS + offsets`. AI nodes: `AI_TC_POS - dx + dy` (mirrored). 10 nodes per side, 2500 resources each.

### Configuration (settings.py)

All game balance constants are centralized in `settings.py`: screen/world dimensions, unit costs and stats (HP, damage, speed, range, train time), building costs and HP, mineral node offsets and capacity, starting resources, FPS cap, colors, and asset paths. Modify this file to tweak game balance.

## Key Patterns

- `dt` (delta time in seconds) passed through all `update()` methods. `--playforme` mode uses `sim_dt = dt * 20` for fast simulation.
- Selection: either `selected_units` (list) or `selected_building` (single), never both — `deselect_all()` clears both.
- All coordinates are world-space. Screen↔world conversion via `_screen_to_world()` and camera offsets.
- `team` attribute on units/buildings: `"player"` or `"ai"`. Wave enemies use `"enemy"`.
- Debug: press P to pause and dump full game state to `dbug.log`.

## Controls

| Input | Action |
|-------|--------|
| T / B / F / D | Place Town Center / Barracks / Factory / Defense Tower |
| Left click | Place building / select unit or building / click minimap |
| Left drag | Box-select units / drag minimap to pan |
| Right click ground | Move selected units |
| Right click mineral node | Send selected workers to mine |
| Shift + Right click | Add waypoint |
| Arrow keys | Scroll camera |
| P | Pause + write dbug.log |
| ESC | Cancel placement / deselect / resume pause / quit on game over |

Replay viewer: Space (pause), +/- (speed), click timeline to seek, ESC (quit).
