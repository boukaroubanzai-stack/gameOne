"""Remote player proxy: replaces AIPlayer in multiplayer mode with no autonomous AI."""

import math
import random
import pygame
from resources import ResourceManager
from buildings import Barracks, Factory, TownCenter, DefenseTower, Watchguard, Radar
from units import Worker, Soldier, Scout, Tank
from minerals import MineralNode
from entity_helpers import (
    place_unit_at_free_spot, handle_deploying_workers,
    validate_attack_target, try_auto_target, update_vision_hunting,
)
from settings import (
    STARTING_WORKERS, AI_TC_POS, MINERAL_OFFSETS,
    WORLD_W, WORLD_H,
)

# Reuse AI mineral positions (right side of map, mirrored)
AI_MINERAL_POSITIONS = [(AI_TC_POS[0] - dx, AI_TC_POS[1] + dy) for dx, dy in MINERAL_OFFSETS]

AI_TINT_COLOR = (255, 140, 0)  # same as ai_player.py

from utils import TintedSpriteCache


class RemotePlayer:
    """Replaces AIPlayer in multiplayer mode. Same data interface, no autonomous AI."""

    def __init__(self):
        self.resource_manager = ResourceManager()
        self.buildings = []
        self.units = []
        self.mineral_nodes = []

        # Tinted sprites
        self._tinted_cache = TintedSpriteCache(AI_TINT_COLOR)

        self._game_state = None  # set by GameState after init

        self._setup()

    def _setup(self):
        """Initialize remote player starting state (mirrors AIPlayer._setup)."""
        for x, y in AI_MINERAL_POSITIONS:
            self.mineral_nodes.append(MineralNode(x, y))

        tc = TownCenter(AI_TC_POS[0], AI_TC_POS[1])
        tc.team = "ai"
        self.buildings.append(tc)

        for i in range(STARTING_WORKERS):
            w = Worker(tc.rally_x + i * 25, tc.rally_y)
            w.team = "ai"
            self.units.append(w)

    def _get_tinted_sprite(self, entity):
        return self._tinted_cache.get(entity)

    def _handle_deploying_workers(self, dt):
        """Check for workers that have arrived at their deploy target."""
        handle_deploying_workers(
            self.units, self.buildings,
            self.buildings, self.mineral_nodes,
            self.resource_manager, self._game_state, "ai", dt,
        )

    def think(self, dt, player_units, player_buildings):
        """No-op: remote player decisions come from network commands."""
        pass

    def drain_commands(self):
        """No-op: remote player has no local commands."""
        return []

    def update_simulation(self, dt, player_units, player_buildings, all_units_for_collision):
        """Update remote player entities: production, combat, cleanup. No AI decisions."""
        self._tinted_cache.ensure_ready()
        self._handle_deploying_workers(dt)

        # Building production and tower combat
        for building in self.buildings:
            if isinstance(building, DefenseTower):
                building.combat_update(dt, player_units)
            else:
                new_unit = building.update(dt)
                if new_unit is not None:
                    new_unit.team = "ai"
                    if self._game_state:
                        self._game_state.assign_unit_id(new_unit)
                    place_unit_at_free_spot(new_unit, all_units_for_collision)
                    self.units.append(new_unit)

        # Auto-target: combat units attack player units in range
        for unit in self.units:
            if not unit.alive:
                continue

            if isinstance(unit, Worker):
                if unit.state != "idle":
                    unit.update_state(dt)
                continue

            if unit.attacking:
                validate_attack_target(unit, dt)
                continue

            if isinstance(unit, (Soldier, Scout, Tank)):
                if try_auto_target(unit, dt, player_units, player_buildings):
                    continue
                update_vision_hunting(unit, player_units, player_buildings)

        # Cleanup dead
        for u in self.units:
            if not u.alive and isinstance(u, Worker):
                u.cancel_mining()
                u.cancel_deploy()
        self.units = [u for u in self.units if u.alive]
        self.buildings = [b for b in self.buildings if b.hp > 0]
