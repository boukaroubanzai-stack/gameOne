import math
import random
import pygame
from resources import ResourceManager
from buildings import Barracks, Factory, TownCenter
from units import Worker, Soldier, Tank
from minerals import MineralNode, MINERAL_POSITIONS
from waves import WaveManager
from settings import (
    MAP_HEIGHT, WIDTH, STARTING_WORKERS,
    BARRACKS_COST, FACTORY_COST, TOWN_CENTER_COST,
)


class GameState:
    def __init__(self):
        self.resource_manager = ResourceManager()
        self.buildings = []
        self.units = []
        self.mineral_nodes = []
        self.selected_units = []
        self.selected_building = None
        self.placement_mode = None  # None, "barracks", "factory", "towncenter"
        self.wave_manager = WaveManager()
        self.game_over = False
        self.game_result = None  # "victory" or "defeat"

        self._setup_starting_state()

    def _setup_starting_state(self):
        # Place mineral nodes
        for x, y in MINERAL_POSITIONS:
            self.mineral_nodes.append(MineralNode(x, y))

        # Place starting Town Center
        tc = TownCenter(100, 280)
        self.buildings.append(tc)

        # Spawn starting workers near the Town Center
        for i in range(STARTING_WORKERS):
            w = Worker(tc.rally_x + i * 25, tc.rally_y)
            self.units.append(w)

    def deselect_all(self):
        for u in self.selected_units:
            u.selected = False
        self.selected_units = []
        if self.selected_building:
            self.selected_building.selected = False
            self.selected_building = None

    def select_unit(self, unit):
        self.deselect_all()
        unit.selected = True
        self.selected_units = [unit]

    def select_units(self, units):
        self.deselect_all()
        for u in units:
            u.selected = True
        self.selected_units = list(units)

    def select_building(self, building):
        self.deselect_all()
        building.selected = True
        self.selected_building = building

    def get_unit_at(self, pos):
        for unit in reversed(self.units):
            if unit.rect.collidepoint(pos):
                return unit
        return None

    def get_building_at(self, pos):
        for building in reversed(self.buildings):
            if building.rect.collidepoint(pos):
                return building
        return None

    def get_mineral_node_at(self, pos):
        for node in self.mineral_nodes:
            if not node.depleted and node.rect.collidepoint(pos):
                return node
        return None

    def get_units_in_rect(self, rect):
        return [u for u in self.units if rect.colliderect(u.rect)]

    def _find_nearest_town_center(self, x, y):
        best = None
        best_dist = float("inf")
        for b in self.buildings:
            if isinstance(b, TownCenter):
                dx = (b.x + b.w // 2) - x
                dy = (b.y + b.h // 2) - y
                d = dx * dx + dy * dy
                if d < best_dist:
                    best_dist = d
                    best = b
        return best

    def command_mine(self, node):
        tc = self._find_nearest_town_center(node.x, node.y)
        if tc is None:
            return
        for unit in self.selected_units:
            if isinstance(unit, Worker):
                unit.assign_to_mine(node, tc, self.resource_manager)

    def place_building(self, pos):
        x, y = pos
        if self.placement_mode == "barracks":
            b = Barracks(x, y)
        elif self.placement_mode == "factory":
            b = Factory(x, y)
        elif self.placement_mode == "towncenter":
            b = TownCenter(x, y)
        else:
            return False

        # Check building fits within map area
        if b.rect.bottom > MAP_HEIGHT or b.rect.top < 0:
            return False
        if b.rect.left < 0 or b.rect.right > WIDTH:
            return False

        # Check not overlapping existing buildings
        for existing in self.buildings:
            if b.rect.colliderect(existing.rect):
                return False

        # Check not overlapping mineral nodes
        for node in self.mineral_nodes:
            if not node.depleted and b.rect.colliderect(node.rect.inflate(10, 10)):
                return False

        cost = self._placement_cost()
        if self.resource_manager.spend(cost):
            self.buildings.append(b)
            self.placement_mode = None
            return True
        return False

    def _placement_cost(self):
        if self.placement_mode == "barracks":
            return BARRACKS_COST
        elif self.placement_mode == "factory":
            return FACTORY_COST
        elif self.placement_mode == "towncenter":
            return TOWN_CENTER_COST
        return 0

    def command_move(self, pos):
        for unit in self.selected_units:
            unit.set_target(pos)

    def command_queue_waypoint(self, pos):
        for unit in self.selected_units:
            unit.add_waypoint(pos)

    def _place_unit_at_free_spot(self, unit):
        """Nudge a newly spawned unit to a free spot if it overlaps an existing unit."""
        if not self._collides_with_other(unit, unit.x, unit.y):
            return
        # Spiral outward to find a free spot
        spacing = unit.size * 2
        for ring in range(1, 10):
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if abs(dx) != ring and abs(dy) != ring:
                        continue
                    nx = unit.x + dx * spacing
                    ny = unit.y + dy * spacing
                    if nx < unit.size or nx > WIDTH - unit.size:
                        continue
                    if ny < unit.size or ny > MAP_HEIGHT - unit.size:
                        continue
                    if not self._collides_with_other(unit, nx, ny):
                        unit.x, unit.y = nx, ny
                        return

    def _collides_with_other(self, unit, x, y):
        """Check if unit at position (x, y) would overlap any other unit."""
        all_units = self.units + self.wave_manager.enemies
        for other in all_units:
            if other is unit:
                continue
            dist = math.hypot(x - other.x, y - other.y)
            if dist < unit.size + other.size:
                return other
        return None

    def _move_unit_with_avoidance(self, unit, dt):
        """Move a unit toward its waypoint, steering around blocking units."""
        if not unit.waypoints:
            return
        tx, ty = unit.waypoints[0]
        dx = tx - unit.x
        dy = ty - unit.y
        dist = math.hypot(dx, dy)
        if dist < 2:
            unit.waypoints.pop(0)
            return

        move = unit.speed * dt
        if move >= dist:
            # Close enough to snap — check if destination is free
            blocker = self._collides_with_other(unit, tx, ty)
            if not blocker:
                unit.x, unit.y = tx, ty
                unit.waypoints.pop(0)
            else:
                # Destination blocked — try to stop near it
                nx, ny = dx / dist, dy / dist
                stop_dist = unit.size + blocker.size
                new_x = blocker.x - nx * stop_dist
                new_y = blocker.y - ny * stop_dist
                if not self._collides_with_other(unit, new_x, new_y):
                    unit.x, unit.y = new_x, new_y
                unit.waypoints.pop(0)
            return

        nx, ny = dx / dist, dy / dist
        new_x = unit.x + nx * move
        new_y = unit.y + ny * move

        # Check if the destination itself is occupied by a stationary unit
        blocker = self._collides_with_other(unit, tx, ty)
        if blocker:
            # If we're close enough to the blocker, stop next to it
            dist_to_blocker = math.hypot(unit.x - blocker.x, unit.y - blocker.y)
            stop_dist = unit.size + blocker.size + 2
            if dist_to_blocker <= stop_dist + move:
                # Place unit adjacent to the blocker
                bx = unit.x - blocker.x
                by = unit.y - blocker.y
                bdist = math.hypot(bx, by)
                if bdist > 0:
                    unit.x = blocker.x + (bx / bdist) * stop_dist
                    unit.y = blocker.y + (by / bdist) * stop_dist
                unit.waypoints.pop(0)
                return

        # If stuck, try moving left (perpendicular to facing direction) to get unstuck
        px, py = -ny, nx  # left direction relative to facing
        if unit.stuck:
            left_x = unit.x + px * move
            left_y = unit.y + py * move
            if not self._collides_with_other(unit, left_x, left_y):
                unit.x, unit.y = left_x, left_y
                return

        # Try direct path first
        blocker_on_path = self._collides_with_other(unit, new_x, new_y)
        if not blocker_on_path:
            unit.x, unit.y = new_x, new_y
            return

        # Blocked by another moving unit — lower-priority unit waits
        blocker_is_moving = hasattr(blocker_on_path, 'waypoints') and blocker_on_path.waypoints
        if blocker_is_moving and id(unit) < id(blocker_on_path):
            return  # wait for the higher-priority unit to steer around

        # Try steering around the blocker (perpendicular)
        for sign in (1, -1):
            alt_x = unit.x + px * move * sign
            alt_y = unit.y + py * move * sign
            if not self._collides_with_other(unit, alt_x, alt_y):
                unit.x, unit.y = alt_x, alt_y
                return

        # Try diagonals (45 degrees off the main direction)
        for sign in (1, -1):
            diag_x = unit.x + (nx * 0.5 + px * 0.5 * sign) * move
            diag_y = unit.y + (ny * 0.5 + py * 0.5 * sign) * move
            if not self._collides_with_other(unit, diag_x, diag_y):
                unit.x, unit.y = diag_x, diag_y
                return

        # Completely blocked from all directions — stay put this frame

    def update(self, dt):
        if self.game_over:
            return

        enemies = self.wave_manager.enemies

        # Update player units
        for unit in self.units:
            if isinstance(unit, Worker) and unit.state != "idle":
                # Worker mining state machine: handle movement with avoidance,
                # then let the worker check for state transitions
                if unit.waypoints:
                    self._move_unit_with_avoidance(unit, dt)
                # Run worker state logic (mining timer, deposits, etc.)
                # but skip the base movement since we already handled it
                unit.update_state(dt)
            elif unit.attacking:
                # Combat unit attacking — check target still valid
                target = unit.target_enemy
                if target and hasattr(target, 'alive') and not target.alive:
                    unit.target_enemy = None
                    unit.attacking = False
                elif target and hasattr(target, 'hp') and target.hp <= 0:
                    unit.target_enemy = None
                    unit.attacking = False
                else:
                    unit.try_attack(dt)
            else:
                # Auto-target: soldiers/tanks fire at enemies in range
                if isinstance(unit, (Soldier, Tank)):
                    target = unit.find_target(enemies)
                    if target:
                        unit.target_enemy = target
                        unit.attacking = True
                        unit.waypoints.clear()
                        unit.fire_cooldown = 0.0
                        unit.try_attack(dt)
                        continue
                if unit.waypoints:
                    self._move_unit_with_avoidance(unit, dt)
                else:
                    unit.update(dt)

        # Update enemy movement with avoidance
        for enemy in enemies:
            if not enemy.attacking and enemy.waypoints:
                self._move_unit_with_avoidance(enemy, dt)

        # Update stuck detection for all units
        all_units = self.units + enemies
        for unit in all_units:
            if not unit.alive:
                continue
            moved = math.hypot(unit.x - unit._last_x, unit.y - unit._last_y)
            if unit.waypoints and not unit.attacking and moved < 0.1:
                unit.stuck_timer += dt
                if unit.stuck_timer >= 0.5:
                    unit.stuck = True
            else:
                unit.stuck_timer = 0.0
                unit.stuck = False
            unit._last_x = unit.x
            unit._last_y = unit.y

        # Update buildings (production)
        for building in self.buildings:
            new_unit = building.update(dt)
            if new_unit is not None:
                self._place_unit_at_free_spot(new_unit)
                self.units.append(new_unit)

        # Update wave manager (spawning, enemy AI, dead removal)
        self.wave_manager.update(dt, self.units, self.buildings)

        # Remove dead player units
        dead_units = [u for u in self.units if not u.alive]
        for u in dead_units:
            if u in self.selected_units:
                self.selected_units.remove(u)
                u.selected = False
            # Release mining node if worker
            if isinstance(u, Worker):
                u.cancel_mining()
        self.units = [u for u in self.units if u.alive]

        # Remove dead buildings
        dead_buildings = [b for b in self.buildings if b.hp <= 0]
        for b in dead_buildings:
            if b is self.selected_building:
                self.selected_building = None
        self.buildings = [b for b in self.buildings if b.hp > 0]

        # Check win/lose conditions
        if self.wave_manager.is_victory():
            self.game_over = True
            self.game_result = "victory"
        elif self.wave_manager.is_defeat(self.units, self.buildings):
            self.game_over = True
            self.game_result = "defeat"
