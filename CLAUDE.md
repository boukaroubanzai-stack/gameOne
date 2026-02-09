# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Simple RTS (Real-Time Strategy) game built with plain Pygame. Players mine resources from mineral nodes using workers, place buildings, train units (workers, soldiers, tanks), and move them around. No combat yet — movement only.

## Commands

```bash
pip install -r requirements.txt   # Install dependencies
python game.py                     # Run the game
```

## Architecture

- **game.py** — Main entry point. Pygame loop with event handling, update, and draw. All input logic (click, drag-select, keyboard hotkeys, placement mode, right-click mining) lives here.
- **settings.py** — All constants: screen dimensions, colors, unit/building stats (cost, HP, speed, size, train time), mineral node settings, asset paths.
- **resources.py** — `ResourceManager`: tracks amount, handles spending and deposits from workers. No passive income.
- **minerals.py** — `MineralNode` class with remaining amount, `mine()` method. 5 nodes at fixed positions. Drawn as blue diamond shapes.
- **assets/** — Sprite PNGs (soldier, tank, worker, barracks, factory, towncenter) from Kenney.nl (CC0 license).
- **units.py** — `Unit` base class with `Soldier`, `Tank`, and `Worker` subclasses. Units have waypoint-based movement, health bars, selection highlight. `Worker` has a mining state machine (idle → moving_to_mine → mining → returning → repeat). Each subclass has a `load_assets()` classmethod called at startup.
- **buildings.py** — `Building` base class with `TownCenter`, `Barracks`, and `Factory` subclasses. Buildings have production queues with timers, spawn units at a rally point. `TownCenter` trains Workers, `Barracks` trains Soldiers, `Factory` trains Tanks. Each subclass has `load_assets()`.
- **game_state.py** — `GameState` holds all game objects (buildings, units, mineral_nodes, resource_manager), selection state, and placement mode. Provides hit-testing (`get_unit_at`, `get_building_at`, `get_mineral_node_at`, `get_units_in_rect`), the `place_building` flow, and `command_mine` for worker mining assignment. Game starts with 1 Town Center, 3 workers, 5 mineral nodes, and 50 resources.
- **hud.py** — `HUD` draws the bottom bar: resource display, build buttons (Town Center/Barracks/Factory), training button for selected building with queue progress, and selection info.

## Key Patterns

- Entities use PNG sprites from `assets/`, loaded via `load_assets()` classmethods called once after `pygame.init()` in `game.py`.
- `dt` (delta time in seconds) is passed through `update()` for frame-rate-independent movement and timers.
- Selection model: either `selected_units` (list) or `selected_building` (single), never both — `deselect_all()` clears both before any new selection.
- Building placement: `GameState.placement_mode` is set to "barracks"/"factory"/"towncenter", then `place_building()` checks bounds, overlap with buildings and mineral nodes, and cost before creating.
- Production: `Building.start_production()` deducts cost and enqueues; `Building.update(dt)` ticks the timer and returns a spawned unit or None; `GameState.update()` appends spawned units.
- Mining: `Worker.assign_to_mine(node, building, resource_mgr)` sets up the auto-mining loop. Worker walks to node, mines for `WORKER_MINE_TIME`, carries resources back to the Town Center, deposits, then repeats until the node is depleted. Right-clicking ground cancels mining.

## Controls

| Input | Action |
|-------|--------|
| T | Enter Town Center placement mode |
| B | Enter Barracks placement mode |
| F | Enter Factory placement mode |
| Left click (map) | Place building / select unit or building |
| Left drag | Box-select units |
| Right click (ground) | Move selected units (replaces path) |
| Right click (mineral node) | Send selected workers to mine |
| Shift + Right click | Add waypoint to path |
| Escape | Cancel placement / deselect |
