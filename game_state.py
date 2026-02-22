"""Core game state: entity management, update loop, collision avoidance, win/loss."""

import math
import random
import pygame
from resources import ResourceManager
from buildings import Barracks, Factory, TownCenter, DefenseTower, Watchguard, Radar, RepairCrane
from units import Worker, Soldier, Scout, Tank
from minerals import MineralNode, MINERAL_POSITIONS
from waves import WaveManager
from multiplayer_state import RemotePlayer
from commands import BUILDING_CLASSES, BUILDING_COSTS
from entity_helpers import (
    collides_with_other, place_unit_at_free_spot, handle_deploying_workers,
    entity_center, validate_attack_target, try_auto_target, update_vision_hunting,
)
from navigation import NavGrid
from settings import (
    WORLD_W, WORLD_H, STARTING_WORKERS,
    PLAYER_TC_POS,
    BUILDING_ZONE_TC_RADIUS, BUILDING_ZONE_BUILDING_RADIUS, WATCHGUARD_ZONE_RADIUS,
    SUPPLY_PER_TC, TANK_SUPPLY,
)


class GameState:
    def __init__(self, random_seed=None):
        self.resource_manager = ResourceManager()
        self.buildings = []
        self.units = []
        self.mineral_nodes = []
        self.selected_units = []
        self.selected_building = None
        self.placement_mode = None  # None, "barracks", "factory", "towncenter"
        self.wave_manager = WaveManager()
        self._next_unit_id = 0
        self._next_building_id = 0
        self._unit_by_net_id: dict[int, object] = {}
        self._building_by_net_id: dict[int, object] = {}
        self._cached_all_units = None  # rebuilt once per frame
        self.pending_deaths = []  # [(x, y, team, "unit"/"building")] for visual effects
        self.dying_units = []     # [(unit, timer)] fading dead player units
        self.dying_ai_units = []  # [(unit, timer)] fading dead AI units
        self.ai_player = RemotePlayer()
        self.game_over = False
        self.game_result = None  # "victory" or "defeat"
        self.chat_log = []        # list of {"team": str, "message": str, "time": float}
        self.nav_grid = NavGrid()
        self.terrain_rects = []
        if random_seed is not None:
            random.seed(random_seed)
            self.terrain_rects = self.nav_grid.generate_terrain(random_seed)

        self.ai_player._game_state = self
        self._setup_starting_state()

    def assign_unit_id(self, unit):
        unit.net_id = self._next_unit_id
        self._next_unit_id += 1
        self._unit_by_net_id[unit.net_id] = unit
        return unit

    def assign_building_id(self, building):
        building.net_id = self._next_building_id
        self._next_building_id += 1
        self._building_by_net_id[building.net_id] = building
        return building

    def get_unit_by_net_id(self, net_id, team="player"):
        """O(1) lookup by net_id."""
        unit = self._unit_by_net_id.get(net_id)
        if unit and unit.alive:
            return unit
        return None

    def get_building_by_net_id(self, net_id, team="player"):
        """O(1) lookup by net_id."""
        building = self._building_by_net_id.get(net_id)
        if building and building.hp > 0:
            return building
        return None

    def _setup_starting_state(self):
        # Place mineral nodes
        for x, y in MINERAL_POSITIONS:
            self.mineral_nodes.append(MineralNode(x, y))

        # Place starting Town Center
        tc = TownCenter(PLAYER_TC_POS[0], PLAYER_TC_POS[1])
        self.assign_building_id(tc)
        self.buildings.append(tc)

        # Spawn starting workers near the Town Center
        for i in range(STARTING_WORKERS):
            w = Worker(tc.rally_x + i * 25, tc.rally_y)
            self.assign_unit_id(w)
            self.units.append(w)

        # Mark starting buildings on nav grid
        self.nav_grid.mark_building(tc)

        # Assign net_ids to AI starting entities
        for b in self.ai_player.buildings:
            self.assign_building_id(b)
            self.nav_grid.mark_building(b)
        for u in self.ai_player.units:
            self.assign_unit_id(u)

    def snapshot_positions(self):
        """Save current unit positions for interpolation (called before tick commands)."""
        for u in self.units:
            u._prev_x = u.x
            u._prev_y = u.y
        for u in self.ai_player.units:
            u._prev_x = u.x
            u._prev_y = u.y
        for e in self.wave_manager.enemies:
            e._prev_x = e.x
            e._prev_y = e.y

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
        for node in self.mineral_nodes + self.ai_player.mineral_nodes:
            if not node.depleted and node.rect.collidepoint(pos):
                return node
        return None

    def get_units_in_rect(self, rect):
        return [u for u in self.units if rect.colliderect(u.rect)]

    # Multiplayer-aware selection helpers
    def get_local_unit_at(self, pos, local_team):
        units = self.units if local_team == "player" else self.ai_player.units
        for unit in reversed(units):
            if unit.rect.collidepoint(pos):
                return unit
        return None

    def get_local_building_at(self, pos, local_team):
        buildings = self.buildings if local_team == "player" else self.ai_player.buildings
        for building in reversed(buildings):
            if building.rect.collidepoint(pos):
                return building
        return None

    def get_local_units_in_rect(self, rect, local_team):
        units = self.units if local_team == "player" else self.ai_player.units
        return [u for u in units if rect.colliderect(u.rect)]

    def get_local_mineral_nodes(self, local_team):
        return self.mineral_nodes if local_team == "player" else self.ai_player.mineral_nodes

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

    def pathfind_to(self, sx, sy, gx, gy):
        """Compute A* path from (sx,sy) to (gx,gy). Returns waypoint list."""
        path = self.nav_grid.find_path(sx, sy, gx, gy)
        if path:
            return path
        return [(gx, gy)]

    # --- Supply / population cap ---

    @staticmethod
    def _unit_supply_cost(unit):
        """Return supply cost for a unit instance."""
        if isinstance(unit, Tank):
            return TANK_SUPPLY
        return 1  # Worker, Soldier, Scout

    @staticmethod
    def _unit_supply_cost_class(unit_class):
        """Return supply cost for a unit class."""
        if unit_class is Tank:
            return TANK_SUPPLY
        return 1

    def current_supply(self, team="player"):
        """Count total supply used by alive units + units in production queues."""
        units = self.units if team == "player" else self.ai_player.units
        buildings = self.buildings if team == "player" else self.ai_player.buildings
        total = 0
        for u in units:
            total += self._unit_supply_cost(u)
        for b in buildings:
            for unit_class, _ in b.production_queue:
                total += self._unit_supply_cost_class(unit_class)
        return total

    def max_supply(self, team="player"):
        """Count maximum supply from Town Centers."""
        buildings = self.buildings if team == "player" else self.ai_player.buildings
        tc_count = sum(1 for b in buildings if isinstance(b, TownCenter) and b.hp > 0)
        return tc_count * SUPPLY_PER_TC

    def supply_available(self, unit_class, team="player"):
        """Check if there's enough supply to train this unit type."""
        cost = self._unit_supply_cost_class(unit_class)
        return self.current_supply(team) + cost <= self.max_supply(team)

    # --- Unit formations ---

    @staticmethod
    def _calculate_formation_positions(target, units):
        """Calculate grid formation positions around target for a group of units."""
        n = len(units)
        if n <= 1:
            return [target] * n
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        avg_size = sum(u.size for u in units) / n
        spacing = avg_size * 3
        total_w = (cols - 1) * spacing
        total_h = (rows - 1) * spacing
        start_x = target[0] - total_w / 2
        start_y = target[1] - total_h / 2
        positions = []
        for i in range(n):
            row = i // cols
            col = i % cols
            px = start_x + col * spacing
            py = start_y + row * spacing
            positions.append((px, py))
        return positions

    def command_mine(self, node):
        # Check that at least one town center exists
        tc = self._find_nearest_town_center(node.x, node.y)
        if tc is None:
            return
        for unit in self.selected_units:
            if isinstance(unit, Worker):
                refund = unit.cancel_deploy()
                if refund > 0:
                    self.resource_manager.deposit(refund)
                unit.assign_to_mine(node, self.buildings, self.resource_manager)
                # Replace direct waypoint with pathfound waypoints
                path = self.pathfind_to(unit.x, unit.y, node.x, node.y)
                unit.waypoints = list(path)

    def is_in_placement_zone(self, x, y, team="player"):
        """Check if position (x, y) is within a valid building placement zone."""
        buildings = self.buildings if team == "player" else self.ai_player.buildings
        for b in buildings:
            if b.hp <= 0:
                continue
            cx, cy = b.x + b.w // 2, b.y + b.h // 2
            dist = math.hypot(x - cx, y - cy)
            if isinstance(b, TownCenter):
                if dist <= BUILDING_ZONE_TC_RADIUS:
                    return True
            elif isinstance(b, Watchguard):
                if dist <= WATCHGUARD_ZONE_RADIUS:
                    return True
            else:
                if dist <= BUILDING_ZONE_BUILDING_RADIUS:
                    return True
        return False

    def place_building(self, pos):
        x, y = pos
        # Determine building class from placement mode
        building_class = BUILDING_CLASSES.get(self.placement_mode)
        if not building_class:
            return False

        # Create temporary building for validation
        b = building_class(x, y)

        # Check building fits within world area
        if b.rect.bottom > WORLD_H or b.rect.top < 0:
            return False
        if b.rect.left < 0 or b.rect.right > WORLD_W:
            return False

        # Check not overlapping existing buildings (player + AI)
        for existing in self.buildings + self.ai_player.buildings:
            if b.rect.colliderect(existing.rect):
                return False

        # Check not overlapping mineral nodes (player + AI)
        for node in self.mineral_nodes + self.ai_player.mineral_nodes:
            if not node.depleted and b.rect.colliderect(node.rect.inflate(10, 10)):
                return False

        # Check terrain obstacles
        if not self.nav_grid.is_rect_clear(x, y, b.w, b.h):
            return False

        # Check placement zone
        center_x = x + b.w // 2
        center_y = y + b.h // 2
        if not self.is_in_placement_zone(center_x, center_y):
            return False

        # Need a selected worker that isn't already deploying
        workers = [u for u in self.selected_units
                   if isinstance(u, Worker) and u.alive and u.state != "deploying"]
        if not workers:
            return False

        cost = self._placement_cost()
        if not self.resource_manager.can_afford(cost):
            return False

        self.resource_manager.spend(cost)

        # Send closest worker to deploy
        closest = min(workers, key=lambda w: w.distance_to(center_x, center_y))
        closest.assign_to_deploy(building_class, (x, y), cost)

        self.placement_mode = None
        return True

    def _placement_cost(self):
        return BUILDING_COSTS.get(self.placement_mode, 0)

    def command_move(self, pos):
        positions = self._calculate_formation_positions(pos, self.selected_units)
        for unit, target in zip(self.selected_units, positions):
            if isinstance(unit, Worker):
                refund = unit.cancel_deploy()
                if refund > 0:
                    self.resource_manager.deposit(refund)
            path = self.pathfind_to(unit.x, unit.y, target[0], target[1])
            unit.set_target(path[0])
            for wp in path[1:]:
                unit.add_waypoint(wp)

    def command_queue_waypoint(self, pos):
        positions = self._calculate_formation_positions(pos, self.selected_units)
        for unit, target in zip(self.selected_units, positions):
            if isinstance(unit, Worker):
                refund = unit.cancel_deploy()
                if refund > 0:
                    self.resource_manager.deposit(refund)
            path = self.pathfind_to(unit.x, unit.y, target[0], target[1])
            for wp in path:
                unit.add_waypoint(wp)

    def _collides_with_other(self, unit, x, y):
        """Check if unit at position (x, y) would overlap any other unit."""
        all_units = self._cached_all_units or (self.units + self.wave_manager.enemies + self.ai_player.units)
        return collides_with_other(unit, x, y, all_units)

    def _move_unit_with_avoidance(self, unit, dt):
        """Move a unit toward its waypoint, steering around blocking units.

        Algorithm:
        1. Try direct path to waypoint.
        2. If blocked, try 6 steering angles (perpendicular + diagonals).
        3. If destination is blocked by a stationary unit on the *last* waypoint, stop adjacent.
        4. If stuck > 0.3s, try escape directions including backwards.
        5. If stuck > 0.6s, re-path to final destination.
        Two approaching moving units: higher net_id steers, lower waits briefly.
        """
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
        nx, ny = dx / dist, dy / dist
        px, py = -ny, nx  # perpendicular

        # Only stop at blocked destinations for the *final* waypoint
        is_final_wp = len(unit.waypoints) == 1

        if move >= dist:
            # Close enough to snap
            blocker = self._collides_with_other(unit, tx, ty)
            if not blocker:
                unit.x, unit.y = tx, ty
                unit.waypoints.pop(0)
            elif is_final_wp:
                # Final waypoint blocked — settle adjacent
                stop_dist = unit.size + blocker.size + 1
                # Try approach direction, then perpendicular offsets
                for sx, sy in [(nx, ny), (px, py), (-px, -py)]:
                    ax = blocker.x - sx * stop_dist
                    ay = blocker.y - sy * stop_dist
                    if not self._collides_with_other(unit, ax, ay):
                        unit.x, unit.y = ax, ay
                        break
                unit.waypoints.pop(0)
            else:
                # Intermediate waypoint blocked — skip it and move on
                unit.waypoints.pop(0)
            return

        # If stuck too long, skip current waypoint to make progress
        if unit.stuck_timer > 0.6:
            unit.waypoints.pop(0)
            unit.stuck_timer = 0.0
            unit.stuck = False
            return

        # If stuck, try escaping in many directions
        if unit.stuck:
            escape_dirs = [
                (px, py), (-px, -py),                                          # sides
                (nx * 0.7 + px * 0.7, ny * 0.7 + py * 0.7),                   # fwd-left
                (nx * 0.7 - px * 0.7, ny * 0.7 - py * 0.7),                   # fwd-right
                (-nx * 0.7 + px * 0.7, -ny * 0.7 + py * 0.7),                 # back-left
                (-nx * 0.7 - px * 0.7, -ny * 0.7 - py * 0.7),                 # back-right
                (-nx, -ny),                                                     # backwards
            ]
            for ex, ey in escape_dirs:
                elen = math.hypot(ex, ey)
                if elen > 0:
                    ex, ey = ex / elen, ey / elen
                esc_x = unit.x + ex * move
                esc_y = unit.y + ey * move
                if not self._collides_with_other(unit, esc_x, esc_y):
                    unit.x, unit.y = esc_x, esc_y
                    return
            return

        # Check if destination is blocked by a stationary unit (final wp only)
        if is_final_wp:
            dest_blocker = self._collides_with_other(unit, tx, ty)
            if dest_blocker and not (hasattr(dest_blocker, 'waypoints') and dest_blocker.waypoints):
                dist_to_blocker = math.hypot(unit.x - dest_blocker.x, unit.y - dest_blocker.y)
                stop_dist = unit.size + dest_blocker.size + 2
                if dist_to_blocker <= stop_dist + move:
                    bx = unit.x - dest_blocker.x
                    by = unit.y - dest_blocker.y
                    bdist = math.hypot(bx, by)
                    if bdist > 0:
                        unit.x = dest_blocker.x + (bx / bdist) * stop_dist
                        unit.y = dest_blocker.y + (by / bdist) * stop_dist
                    unit.waypoints.pop(0)
                    return

        # Try direct path
        new_x = unit.x + nx * move
        new_y = unit.y + ny * move
        blocker_on_path = self._collides_with_other(unit, new_x, new_y)
        if not blocker_on_path:
            unit.x, unit.y = new_x, new_y
            return

        # Two moving units approaching: lower net_id yields briefly (but still steers)
        blocker_moving = hasattr(blocker_on_path, 'waypoints') and blocker_on_path.waypoints
        if blocker_moving and (unit.net_id or 0) < (blocker_on_path.net_id or 0):
            # Lower ID tries to steer but doesn't hard-wait
            pass  # fall through to steering below

        # Try 6 steering directions: perp, diag-forward, diag-back
        steer_dirs = [
            (px, py), (-px, -py),                                   # perpendicular
            (nx * 0.7 + px * 0.7, ny * 0.7 + py * 0.7),            # fwd-left
            (nx * 0.7 - px * 0.7, ny * 0.7 - py * 0.7),            # fwd-right
            (nx * 0.3 + px * 0.95, ny * 0.3 + py * 0.95),          # wide-left
            (nx * 0.3 - px * 0.95, ny * 0.3 - py * 0.95),          # wide-right
        ]
        for sx, sy in steer_dirs:
            slen = math.hypot(sx, sy)
            if slen > 0:
                sx, sy = sx / slen, sy / slen
            alt_x = unit.x + sx * move
            alt_y = unit.y + sy * move
            if not self._collides_with_other(unit, alt_x, alt_y):
                unit.x, unit.y = alt_x, alt_y
                return

        # Completely blocked — stay put this frame (stuck timer will trigger escape)

    def _handle_deploying_workers(self, dt):
        """Check for player workers that have arrived at their deploy target."""
        handle_deploying_workers(
            self.units, self.buildings,
            self.buildings + self.ai_player.buildings,
            self.mineral_nodes + self.ai_player.mineral_nodes,
            self.resource_manager, self, None, dt,
        )

    def update(self, dt):
        """Main per-frame update. Order: deploy workers, player units (combat + movement),
        enemy movement, AI movement, stuck detection, building production, waves, AI think,
        dead removal, win/lose check."""
        if self.game_over:
            return

        # Handle deploying workers (create buildings when they arrive)
        self._handle_deploying_workers(dt)

        enemies = self.wave_manager.enemies
        # Combine wave enemies and AI units as hostile to player
        all_hostiles = enemies + self.ai_player.units
        # Cache combined unit list for collision checks (rebuilt each frame)
        self._cached_all_units = self.units + enemies + self.ai_player.units

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
                validate_attack_target(unit, dt)
            else:
                # Auto-target: when idle or hunting (but not player-issued move orders)
                if isinstance(unit, (Soldier, Scout, Tank)) and (not unit.waypoints or unit.hunting_target):
                    if try_auto_target(unit, dt, all_hostiles, self.ai_player.buildings):
                        unit.waypoints = []
                        continue
                    update_vision_hunting(unit, all_hostiles, self.ai_player.buildings)
                if unit.waypoints:
                    self._move_unit_with_avoidance(unit, dt)
                else:
                    unit.update(dt)

        # Update enemy movement with avoidance
        for enemy in enemies:
            if not enemy.attacking and enemy.waypoints:
                self._move_unit_with_avoidance(enemy, dt)

        # Update AI unit movement with avoidance
        for ai_unit in self.ai_player.units:
            if not ai_unit.alive:
                continue
            if isinstance(ai_unit, Worker) and ai_unit.state != "idle":
                if ai_unit.waypoints:
                    self._move_unit_with_avoidance(ai_unit, dt)
                continue
            if not ai_unit.attacking and ai_unit.waypoints:
                self._move_unit_with_avoidance(ai_unit, dt)

        # Update stuck detection for all units
        for unit in self._cached_all_units:
            if not unit.alive:
                continue
            moved = math.hypot(unit.x - unit._last_x, unit.y - unit._last_y)
            if unit.waypoints and not unit.attacking and moved < 0.1:
                unit.stuck_timer += dt
                if unit.stuck_timer >= 0.3:
                    unit.stuck = True
            else:
                unit.stuck_timer = 0.0
                unit.stuck = False
            unit._last_x = unit.x
            unit._last_y = unit.y

        # Update buildings (production + tower combat)
        for building in self.buildings:
            if isinstance(building, DefenseTower):
                building.combat_update(dt, all_hostiles)
            elif isinstance(building, RepairCrane):
                building.heal_update(dt, self.units)
            else:
                new_unit = building.update(dt)
                if new_unit is not None:
                    self.assign_unit_id(new_unit)
                    place_unit_at_free_spot(new_unit, self._cached_all_units)
                    self.units.append(new_unit)

        # Record wave enemy deaths before wave_manager cleanup
        for e in self.wave_manager.enemies:
            if not e.alive:
                self.pending_deaths.append((e.x, e.y, e.team, "unit"))

        # Update wave manager (spawning, enemy AI against player + AI player)
        self.wave_manager.update(dt, self.units, self.buildings)

        # Record AI deaths before ai_player.update() cleans them up
        for u in self.ai_player.units:
            if not u.alive:
                self.pending_deaths.append((u.x, u.y, u.team, "unit"))
                self.dying_ai_units.append((u, 0.6))
        for b in self.ai_player.buildings:
            if b.hp <= 0:
                self.pending_deaths.append((b.x + b.w // 2, b.y + b.h // 2, "ai", "building"))
                self.nav_grid.unmark_building(b)

        # Update AI player (simulation only — think() is called by game.py)
        self.ai_player.update_simulation(dt, self.units, self.buildings, self._cached_all_units)

        # Remove dead player units
        dead_units = [u for u in self.units if not u.alive]
        for u in dead_units:
            self.pending_deaths.append((u.x, u.y, u.team, "unit"))
            self.dying_units.append((u, 0.6))
            if u in self.selected_units:
                self.selected_units.remove(u)
                u.selected = False
            if isinstance(u, Worker):
                u.cancel_mining()
                u.cancel_deploy()
            if u.net_id is not None:
                self._unit_by_net_id.pop(u.net_id, None)
        self.units = [u for u in self.units if u.alive]

        # Remove dead buildings
        dead_buildings = [b for b in self.buildings if b.hp <= 0]
        for b in dead_buildings:
            self.pending_deaths.append((b.x + b.w // 2, b.y + b.h // 2, "player", "building"))
            if b is self.selected_building:
                self.selected_building = None
            if b.net_id is not None:
                self._building_by_net_id.pop(b.net_id, None)
            self.nav_grid.unmark_building(b)
        self.buildings = [b for b in self.buildings if b.hp > 0]

        # Tick dying unit fade timers
        self.dying_units = [(u, t - dt) for u, t in self.dying_units if t - dt > 0]
        self.dying_ai_units = [(u, t - dt) for u, t in self.dying_ai_units if t - dt > 0]

        # Clear cached list (will be rebuilt next frame)
        self._cached_all_units = None

        # Check win/lose conditions
        # Victory: AI has no buildings and no combat units left
        ai_alive_buildings = [b for b in self.ai_player.buildings if b.hp > 0]
        ai_alive_combat = [u for u in self.ai_player.units
                           if isinstance(u, (Soldier, Scout, Tank)) and u.alive]
        if not ai_alive_buildings and not ai_alive_combat:
            self.game_over = True
            self.game_result = "victory"
        elif self.wave_manager.is_defeat(self.units, self.buildings):
            self.game_over = True
            self.game_result = "defeat"

    def compute_sync_hash(self):
        """Compute a hash of game state for desync detection."""
        import hashlib
        h = hashlib.md5()
        # Unit counts and positions
        for u in sorted(self.units, key=lambda u: u.net_id or 0):
            h.update(f"{u.net_id}:{int(u.x)}:{int(u.y)}:{int(u.hp)}".encode())
        for u in sorted(self.ai_player.units, key=lambda u: u.net_id or 0):
            h.update(f"{u.net_id}:{int(u.x)}:{int(u.y)}:{int(u.hp)}".encode())
        # Building counts and HP
        for b in sorted(self.buildings, key=lambda b: b.net_id or 0):
            h.update(f"b{b.net_id}:{int(b.hp)}".encode())
        for b in sorted(self.ai_player.buildings, key=lambda b: b.net_id or 0):
            h.update(f"b{b.net_id}:{int(b.hp)}".encode())
        # Resources
        h.update(f"r:{self.resource_manager.amount}:{self.ai_player.resource_manager.amount}".encode())
        return h.hexdigest()[:8]
