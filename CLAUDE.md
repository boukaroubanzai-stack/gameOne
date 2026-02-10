# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Simple RTS (Real-Time Strategy) game built with plain Pygame. Players mine resources from mineral nodes using workers, place buildings, train combat units (soldiers, tanks), and defend against 10 waves of enemy "Yanuses" units that spawn from the bottom of the map. Win by destroying all 10 waves; lose if all player units and buildings are destroyed.

## Commands

```bash
pip install -r requirements.txt   # Install dependencies
python game.py                     # Run the game
```

## Architecture

- **game.py** — Main entry point. Pygame loop with event handling, update, and draw. All input logic (click, drag-select, keyboard hotkeys, placement mode, right-click mining) lives here. Draws attack lines, enemy units, and game-over overlay.
- **settings.py** — All constants: screen dimensions (1080x900), colors, unit/building stats (cost, HP, speed, size, train time, fire rate, damage, range), mineral node settings, wave system settings, asset paths.
- **resources.py** — `ResourceManager`: tracks amount, handles spending and deposits from workers. No passive income.
- **minerals.py** — `MineralNode` class with remaining amount, `mine()` method. 5 nodes at fixed positions. Drawn as blue diamond shapes.
- **assets/** — Sprite PNGs (soldier, tank, worker, yanuses, barracks, factory, towncenter) from Kenney.nl (CC0 license). Yanuses sprite is a red-tinted soldier.
- **units.py** — `Unit` base class with `Soldier`, `Tank`, `Worker`, and `Yanuses` subclasses. Units have waypoint-based movement, health bars, selection highlight, and combat attributes (fire_rate, damage, attack_range, team). `Worker` has a mining state machine. `Yanuses` has AI that seeks and attacks player units/buildings. Each subclass has a `load_assets()` classmethod called at startup.
- **buildings.py** — `Building` base class with `TownCenter`, `Barracks`, and `Factory` subclasses. Buildings have production queues with timers, spawn units at a rally point, and can be attacked/destroyed.
- **game_state.py** — `GameState` holds all game objects, selection state, placement mode, `WaveManager`, and game-over state. Handles combat targeting (auto-fire), dead unit/building removal, collision avoidance steering, and win/lose condition checks.
- **waves.py** — `WaveManager` handles spawning 10 waves of 3 Yanuses enemies from the bottom of the map with intervals. Tracks wave progression, enemy AI updates, and provides victory/defeat checks.
- **hud.py** — `HUD` draws the bottom bar: resource display, wave counter, build buttons (Town Center/Barracks/Factory), training button for selected building with queue progress, and selection info.

## Key Patterns

- Entities use PNG sprites from `assets/`, loaded via `load_assets()` classmethods called once after `pygame.init()` in `game.py`.
- `dt` (delta time in seconds) is passed through `update()` for frame-rate-independent movement and timers.
- Selection model: either `selected_units` (list) or `selected_building` (single), never both — `deselect_all()` clears both before any new selection.
- Building placement: `GameState.placement_mode` is set to "barracks"/"factory"/"towncenter", then `place_building()` checks bounds, overlap with buildings and mineral nodes, and cost before creating.
- Production: `Building.start_production()` deducts cost and enqueues; `Building.update(dt)` ticks the timer and returns a spawned unit or None; `GameState.update()` appends spawned units.
- Mining: `Worker.assign_to_mine(node, building, resource_mgr)` sets up the auto-mining loop. Worker walks to node, mines for `WORKER_MINE_TIME`, carries resources back to the Town Center, deposits, then repeats until the node is depleted. Right-clicking ground cancels mining.
- Combat: Units with `attack_range > 0` auto-fire at enemies in range, which stops their movement. Player can override by right-clicking to move. Enemies use `ai_update()` to seek and attack player entities.
- Collision avoidance: `_move_unit_with_avoidance()` steers moving units around blocking ones (tries direct, perpendicular, then diagonal paths).

## Controls

| Input | Action |
|-------|--------|
| T | Enter Town Center placement mode |
| B | Enter Barracks placement mode |
| F | Enter Factory placement mode |
| Left click (map) | Place building / select unit or building |
| Left drag | Box-select units |
| Right click (ground) | Move selected units (replaces path, cancels attack) |
| Right click (mineral node) | Send selected workers to mine |
| Shift + Right click | Add waypoint to path |
| Escape | Cancel placement / deselect / quit on game over |
