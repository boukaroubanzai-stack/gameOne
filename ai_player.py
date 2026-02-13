"""AI opponent: economy, build order, military training, attack waves, focus fire."""

import math
import random
import pygame
from resources import ResourceManager
from buildings import Barracks, Factory, TownCenter, DefenseTower
from units import Worker, Soldier, Scout, Tank
from minerals import MineralNode
from settings import (
    WORLD_W, WORLD_H,
    BARRACKS_COST, FACTORY_COST, TOWN_CENTER_COST, TOWER_COST,
    SOLDIER_COST, TANK_COST, WORKER_COST,
    BARRACKS_SIZE, FACTORY_SIZE, TOWN_CENTER_SIZE, TOWER_SIZE,
    STARTING_WORKERS,
    MINERAL_OFFSETS, AI_TC_POS,
)


# AI mineral positions: TC position + shared offsets (mirrored, spread to the left)
AI_MINERAL_POSITIONS = [(AI_TC_POS[0] - dx, AI_TC_POS[1] + dy) for dx, dy in MINERAL_OFFSETS]

# AI tint color: orange/red overlay to distinguish from player
AI_TINT_COLOR = (255, 80, 0, 80)

# AI decision timers (seconds)
AI_THINK_INTERVAL = 1.0  # Reduced from 2.0 for more responsive behavior
AI_MAX_WORKERS = 8  # Increased from 6 for stronger economy

# Army composition targets
AI_SOLDIER_RATIO = 3  # 3 soldiers per 1 tank
AI_ATTACK_THRESHOLD = 6  # min combat units before first attack wave
AI_GARRISON_RATIO = 0.3  # keep 30% of army at base for defense
AI_RETREAT_RATIO = 0.3  # retreat when army is < 30% of enemy force
AI_RESOURCE_RESERVE = 100  # keep some resources for emergency replacements


from utils import tint_surface, get_font


class AIPlayer:
    """Computer-controlled opponent that builds a base, trains units, and attacks."""

    def __init__(self, profile=None):
        if profile is None:
            profile = {}
        self.think_interval = profile.get("think_interval", AI_THINK_INTERVAL)
        self.max_workers = profile.get("max_workers", AI_MAX_WORKERS)
        self.soldier_ratio = profile.get("soldier_ratio", AI_SOLDIER_RATIO)
        self.attack_threshold = profile.get("attack_threshold", AI_ATTACK_THRESHOLD)
        self.garrison_ratio = profile.get("garrison_ratio", AI_GARRISON_RATIO)
        self.retreat_ratio = profile.get("retreat_ratio", AI_RETREAT_RATIO)
        self.resource_reserve = profile.get("resource_reserve", AI_RESOURCE_RESERVE)
        self.build_towers = profile.get("build_towers", False)
        self.max_towers = profile.get("max_towers", 0)

        self.resource_manager = ResourceManager()
        self.buildings = []
        self.units = []
        self.mineral_nodes = []

        # AI state
        self.think_timer = 0.0
        self.phase = "economy"  # "economy", "military", "attack", "defend"
        self.attack_sent = False
        self.attack_target = None

        # Attack wave tracking
        self._attacking_units = set()  # IDs of units currently on attack
        self._garrison_units = set()  # IDs of units assigned to garrison
        self._scout_sent = False
        self._scout_unit_id = None
        self._enemy_base_location = None  # discovered by scout
        self._last_attack_army_size = 0
        self._retreat_cooldown = 0.0  # prevent immediate re-attack after retreat
        self._buildings_lost_recently = 0  # track building losses for adaptive behavior
        self._last_building_count = 0

        # Tinted sprites (created after pygame init, on first update)
        self._sprites_tinted = False
        self._tinted_sprites = {}
        self._game_state = None  # set by GameState after init for net_id assignment

        self._setup()

    def _setup(self):
        """Set up AI starting state: mineral nodes, town center, workers."""
        # Create AI mineral nodes on the right side
        for x, y in AI_MINERAL_POSITIONS:
            self.mineral_nodes.append(MineralNode(x, y))

        # Place starting Town Center on the far right side of the world
        tc = TownCenter(AI_TC_POS[0], AI_TC_POS[1])
        tc.team = "ai"
        self.buildings.append(tc)
        self._last_building_count = 1

        # Spawn starting workers near the Town Center
        for i in range(STARTING_WORKERS):
            w = Worker(tc.rally_x + i * 25, tc.rally_y)
            w.team = "ai"
            self.units.append(w)

    def _ensure_tinted_sprites(self):
        """Create tinted versions of sprites for AI units/buildings."""
        if self._sprites_tinted:
            return
        self._sprites_tinted = True

        # Tint unit sprites
        if Soldier.sprite:
            self._tinted_sprites["soldier"] = tint_surface(Soldier.sprite, AI_TINT_COLOR)
        if Scout.sprite:
            self._tinted_sprites["scout"] = tint_surface(Scout.sprite, AI_TINT_COLOR)
        if Tank.sprite:
            self._tinted_sprites["tank"] = tint_surface(Tank.sprite, AI_TINT_COLOR)
        if Worker.sprite:
            self._tinted_sprites["worker"] = tint_surface(Worker.sprite, AI_TINT_COLOR)
        # Tint building sprites
        if TownCenter.sprite:
            self._tinted_sprites["towncenter"] = tint_surface(TownCenter.sprite, AI_TINT_COLOR)
        if Barracks.sprite:
            self._tinted_sprites["barracks"] = tint_surface(Barracks.sprite, AI_TINT_COLOR)
        if Factory.sprite:
            self._tinted_sprites["factory"] = tint_surface(Factory.sprite, AI_TINT_COLOR)
        if DefenseTower.sprite:
            self._tinted_sprites["tower"] = tint_surface(DefenseTower.sprite, AI_TINT_COLOR)

    def _get_tinted_sprite(self, entity):
        """Get the tinted sprite for an AI entity."""
        if isinstance(entity, Soldier):
            return self._tinted_sprites.get("soldier")
        elif isinstance(entity, Scout):
            return self._tinted_sprites.get("scout")
        elif isinstance(entity, Tank):
            return self._tinted_sprites.get("tank")
        elif isinstance(entity, Worker):
            return self._tinted_sprites.get("worker")
        elif isinstance(entity, TownCenter):
            return self._tinted_sprites.get("towncenter")
        elif isinstance(entity, Barracks):
            return self._tinted_sprites.get("barracks")
        elif isinstance(entity, Factory):
            return self._tinted_sprites.get("factory")
        elif isinstance(entity, DefenseTower):
            return self._tinted_sprites.get("tower")
        return None

    # --- Helper methods ---

    def _find_ai_town_center(self):
        """Find the first alive AI town center."""
        for b in self.buildings:
            if isinstance(b, TownCenter) and b.hp > 0:
                return b
        return None

    def _get_all_buildings_of_type(self, building_type):
        """Get all alive buildings of a given type."""
        return [b for b in self.buildings if isinstance(b, building_type) and b.hp > 0]

    def _count_buildings_of_type(self, building_type):
        return sum(1 for b in self.buildings if isinstance(b, building_type) and b.hp > 0)

    def _count_workers(self):
        return sum(1 for u in self.units if isinstance(u, Worker) and u.alive)

    def _count_soldiers(self):
        return sum(1 for u in self.units if isinstance(u, Soldier) and u.alive)

    def _count_tanks(self):
        return sum(1 for u in self.units if isinstance(u, Tank) and u.alive)

    def _count_combat_units(self):
        return sum(1 for u in self.units if isinstance(u, (Soldier, Scout, Tank)) and u.alive)

    def _get_combat_units(self):
        return [u for u in self.units if isinstance(u, (Soldier, Scout, Tank)) and u.alive]

    def _has_building(self, building_type):
        return any(isinstance(b, building_type) and b.hp > 0 for b in self.buildings)

    def _get_building(self, building_type):
        for b in self.buildings:
            if isinstance(b, building_type) and b.hp > 0:
                return b
        return None

    def _get_base_center(self):
        """Get the average center of all AI buildings (the 'base' location)."""
        alive_buildings = [b for b in self.buildings if b.hp > 0]
        if not alive_buildings:
            return (8000, 280)  # fallback to starting position
        cx = sum(b.x + b.w // 2 for b in alive_buildings) / len(alive_buildings)
        cy = sum(b.y + b.h // 2 for b in alive_buildings) / len(alive_buildings)
        return (cx, cy)

    # --- Worker and economy management ---

    def _find_best_mineral_node_for_worker(self, worker):
        """Find the best mineral node for a worker, distributing workers across nodes."""
        # Count workers assigned to each node
        node_worker_counts = {}
        for node in self.mineral_nodes:
            if node.depleted:
                continue
            node_worker_counts[id(node)] = 0

        for u in self.units:
            if isinstance(u, Worker) and u.alive and u.assigned_node and not u.assigned_node.depleted:
                nid = id(u.assigned_node)
                if nid in node_worker_counts:
                    node_worker_counts[nid] = node_worker_counts.get(nid, 0) + 1

        # Pick the node with fewest workers assigned (prefer closer if tied)
        best_node = None
        best_score = float("inf")
        for node in self.mineral_nodes:
            if node.depleted:
                continue
            nid = id(node)
            count = node_worker_counts.get(nid, 0)
            dist = math.hypot(worker.x - node.x, worker.y - node.y)
            # Score: primarily by worker count, secondarily by distance
            score = count * 10000 + dist
            if score < best_score:
                best_score = score
                best_node = node
        return best_node

    def _assign_idle_workers(self):
        """Send idle or stuck-waiting workers to mine, distributing across nodes."""
        tc = self._find_ai_town_center()
        if tc is None:
            return
        for unit in self.units:
            if isinstance(unit, Worker) and unit.alive:
                if unit.state == "idle":
                    node = self._find_best_mineral_node_for_worker(unit)
                    if node:
                        unit.assign_to_mine(node, self.buildings, self.resource_manager)
                elif unit.state == "waiting":
                    # Worker stuck waiting — reassign to a different node
                    node = self._find_best_mineral_node_for_worker(unit)
                    if node and node is not unit.assigned_node:
                        unit.cancel_mining()
                        unit.assign_to_mine(node, self.buildings, self.resource_manager)

    # --- Building placement ---

    def _find_building_placement(self, size):
        """Find a valid position to place a building near the AI base."""
        tc = self._find_ai_town_center()
        if tc is None:
            # Fallback: try to place near base center
            base_x, base_y = self._get_base_center()
        else:
            base_x = tc.x
            base_y = tc.y
        bw, bh = size

        # Wider search radius for better spacing
        for attempt in range(80):
            offset_x = random.randint(-300, 300)
            offset_y = random.randint(-250, 300)
            x = base_x + offset_x
            y = base_y + offset_y

            # Clamp to world bounds
            x = max(0, min(x, WORLD_W - bw))
            y = max(0, min(y, WORLD_H - bh))

            rect = pygame.Rect(x, y, bw, bh)

            # Check no overlap with existing AI buildings (larger buffer for spacing)
            overlap = False
            for b in self.buildings:
                if rect.colliderect(b.rect.inflate(20, 20)):
                    overlap = True
                    break

            # Check no overlap with AI mineral nodes
            if not overlap:
                for node in self.mineral_nodes:
                    if not node.depleted and rect.colliderect(node.rect.inflate(20, 20)):
                        overlap = True
                        break

            if not overlap:
                return (x, y)
        return None

    def _find_available_worker(self):
        """Find a worker available for building. Prefers idle, then mining workers."""
        idle = [u for u in self.units if isinstance(u, Worker) and u.alive and u.state == "idle"]
        if idle:
            return idle
        # Pull a mining worker if no idle ones
        mining = [u for u in self.units if isinstance(u, Worker) and u.alive
                  and u.state in ("moving_to_mine", "waiting", "mining", "returning")
                  and u.deploy_building_class is None]
        return mining

    def _try_place_building(self, building_class, cost, size):
        """Attempt to place a building by sending a worker to deploy it."""
        if not self.resource_manager.can_afford(cost):
            return False
        available_workers = self._find_available_worker()
        if not available_workers:
            return False
        pos = self._find_building_placement(size)
        if pos is None:
            return False
        self.resource_manager.spend(cost)
        closest = min(available_workers, key=lambda w: math.hypot(w.x - pos[0], w.y - pos[1]))
        closest.cancel_mining()
        closest.assign_to_deploy(building_class, pos, cost)
        return True

    def _place_tower_near_building(self):
        """Place a defense tower adjacent to a random existing building via worker deployment."""
        available_workers = self._find_available_worker()
        if not available_workers:
            return False
        # Pick buildings that don't already have a tower nearby
        non_tower_buildings = [b for b in self.buildings if b.hp > 0 and not isinstance(b, DefenseTower)]
        if not non_tower_buildings:
            return False
        existing_towers = [b for b in self.buildings if isinstance(b, DefenseTower) and b.hp > 0]
        random.shuffle(non_tower_buildings)
        tw, th = TOWER_SIZE
        for building in non_tower_buildings:
            # Skip buildings that already have a tower within 120px
            bx, by = building.x + building.w // 2, building.y + building.h // 2
            if any(math.hypot(bx - (t.x + tw // 2), by - (t.y + th // 2)) < 120 for t in existing_towers):
                continue
            # Try placing adjacent to this building
            offsets = [
                (building.w + 10, 0), (-tw - 10, 0),
                (0, building.h + 10), (0, -th - 10),
                (building.w + 10, building.h + 10), (-tw - 10, -th - 10),
            ]
            random.shuffle(offsets)
            for ox, oy in offsets:
                x = building.x + ox
                y = building.y + oy
                x = max(0, min(x, WORLD_W - tw))
                y = max(0, min(y, WORLD_H - th))
                rect = pygame.Rect(x, y, tw, th)
                overlap = False
                for b in self.buildings:
                    if rect.colliderect(b.rect.inflate(10, 10)):
                        overlap = True
                        break
                if not overlap:
                    for node in self.mineral_nodes:
                        if not node.depleted and rect.colliderect(node.rect.inflate(10, 10)):
                            overlap = True
                            break
                if not overlap:
                    if self.resource_manager.spend(TOWER_COST):
                        closest = min(available_workers, key=lambda w: math.hypot(w.x - x, w.y - y))
                        closest.cancel_mining()
                        closest.assign_to_deploy(DefenseTower, (x, y), TOWER_COST)
                        return True
            return False

    def _try_train_unit(self, building, resource_mgr):
        """Train a unit from a building if affordable."""
        unit_class, cost, train_time = building.can_train()
        if resource_mgr.spend(cost):
            building.production_queue.append((unit_class, train_time))
            return True
        return False

    # --- Strategic decision making ---

    def _think(self, player_units, player_buildings):
        """AI decision-making, called periodically."""
        # Always assign idle workers first
        self._assign_idle_workers()

        # Track building losses for adaptive behavior
        current_building_count = len([b for b in self.buildings if b.hp > 0])
        if current_building_count < self._last_building_count:
            self._buildings_lost_recently += self._last_building_count - current_building_count
        self._last_building_count = current_building_count

        # Determine current game state
        num_workers = self._count_workers()
        num_soldiers = self._count_soldiers()
        num_tanks = self._count_tanks()
        num_combat = num_soldiers + num_tanks
        num_barracks = self._count_buildings_of_type(Barracks)
        num_factories = self._count_buildings_of_type(Factory)
        num_town_centers = self._count_buildings_of_type(TownCenter)
        resources = self.resource_manager.amount

        # Count player forces for adaptive behavior
        player_combat = sum(1 for u in player_units if u.alive and isinstance(u, (Soldier, Scout, Tank)))

        # Determine phase based on game state
        self._update_phase(num_workers, num_combat, player_combat)

        # --- ECONOMY: Workers and Town Centers ---
        self._manage_economy(num_workers, num_town_centers, resources)

        # --- BUILD ORDER: Barracks first, then Factory, expand as needed ---
        self._manage_buildings(num_barracks, num_factories, num_town_centers, num_combat, resources)

        # --- MILITARY: Train combat units with proper ratios ---
        self._manage_military(num_soldiers, num_tanks, num_barracks, num_factories, resources)

        # --- ATTACK / DEFENSE ---
        self._manage_combat(player_units, player_buildings, num_combat, player_combat)

    def _update_phase(self, num_workers, num_combat, player_combat):
        """Determine what phase the AI should be in."""
        # If buildings were lost recently, go defensive
        if self._buildings_lost_recently > 0:
            self.phase = "defend"
            return

        # Early game: focus on economy
        if num_workers < 4 and num_combat < 3:
            self.phase = "economy"
        # Mid game: build military
        elif num_combat < self.attack_threshold:
            self.phase = "military"
        # Have enough army: attack
        elif num_combat >= self.attack_threshold:
            self.phase = "attack"
        else:
            self.phase = "military"

    def _manage_economy(self, num_workers, num_town_centers, resources):
        """Handle worker production and economy expansion."""
        town_centers = self._get_all_buildings_of_type(TownCenter)

        # Determine worker cap based on game state
        desired_workers = self.max_workers

        if num_workers < desired_workers:
            for tc in town_centers:
                if num_workers >= desired_workers:
                    break
                # Only queue if production queue is not full
                if len(tc.production_queue) < 2:
                    if self.resource_manager.can_afford(WORKER_COST):
                        self._try_train_unit(tc, self.resource_manager)
                        num_workers += 1  # account for queued

        # Build additional Town Center for faster worker production when rich
        if resources > TOWN_CENTER_COST + 200 and num_town_centers < 2 and num_workers >= 4:
            self._try_place_building(TownCenter, TOWN_CENTER_COST, TOWN_CENTER_SIZE)

    def _manage_buildings(self, num_barracks, num_factories, num_town_centers, num_combat, resources):
        """Handle build order: 2 Barracks -> Factory -> expand."""
        # Build first Barracks ASAP
        if num_barracks == 0:
            self._try_place_building(Barracks, BARRACKS_COST, BARRACKS_SIZE)
            return

        # Build second Barracks before Factory (soldiers are cheaper and faster)
        if num_barracks < 2 and resources >= BARRACKS_COST + self.resource_reserve:
            self._try_place_building(Barracks, BARRACKS_COST, BARRACKS_SIZE)

        # Build first Factory after 2 Barracks
        if num_barracks >= 2 and num_factories == 0 and resources >= FACTORY_COST + self.resource_reserve:
            self._try_place_building(Factory, FACTORY_COST, FACTORY_SIZE)

        # Expand production when queues are full and resources are high
        if resources > 400:
            all_barracks = self._get_all_buildings_of_type(Barracks)
            all_queues_full = all(len(b.production_queue) >= 2 for b in all_barracks) if all_barracks else True
            if all_queues_full and num_barracks < 4:
                self._try_place_building(Barracks, BARRACKS_COST, BARRACKS_SIZE)

            all_factories = self._get_all_buildings_of_type(Factory)
            all_factory_queues_full = all(len(b.production_queue) >= 2 for b in all_factories) if all_factories else True
            if all_factory_queues_full and num_factories < 2 and num_factories > 0:
                self._try_place_building(Factory, FACTORY_COST, FACTORY_SIZE)

        # Build defense towers near existing buildings
        if self.build_towers and num_barracks >= 1:
            num_towers = self._count_buildings_of_type(DefenseTower)
            if num_towers < self.max_towers and resources >= TOWER_COST + self.resource_reserve:
                self._place_tower_near_building()

        # Rebuild destroyed buildings (defensive behavior)
        if self._buildings_lost_recently > 0 and resources >= BARRACKS_COST:
            if num_barracks == 0:
                if self._try_place_building(Barracks, BARRACKS_COST, BARRACKS_SIZE):
                    self._buildings_lost_recently = max(0, self._buildings_lost_recently - 1)
            if num_town_centers == 0:
                if self._try_place_building(TownCenter, TOWN_CENTER_COST, TOWN_CENTER_SIZE):
                    self._buildings_lost_recently = max(0, self._buildings_lost_recently - 1)
            if num_factories == 0 and num_barracks >= 1:
                if self._try_place_building(Factory, FACTORY_COST, FACTORY_SIZE):
                    self._buildings_lost_recently = max(0, self._buildings_lost_recently - 1)
            # Decay building loss counter over time
            self._buildings_lost_recently = max(0, self._buildings_lost_recently - 1)

    def _manage_military(self, num_soldiers, num_tanks, num_barracks, num_factories, resources):
        """Train combat units maintaining a ~3:1 soldier:tank ratio."""
        # Determine how aggressive to be with spending
        reserve = self.resource_reserve if self.phase != "attack" else 50

        # Calculate desired ratio
        desired_soldiers = (num_tanks + 1) * self.soldier_ratio
        need_soldiers = num_soldiers < desired_soldiers

        # Train soldiers from all barracks
        all_barracks = self._get_all_buildings_of_type(Barracks)
        for barracks in all_barracks:
            if len(barracks.production_queue) < 3:  # Allow deeper queues
                if need_soldiers or num_tanks > 0:
                    if resources > SOLDIER_COST + reserve:
                        if self._try_train_unit(barracks, self.resource_manager):
                            resources = self.resource_manager.amount

        # Train tanks from all factories (less aggressively to maintain ratio)
        all_factories = self._get_all_buildings_of_type(Factory)
        for factory in all_factories:
            if len(factory.production_queue) < 2:
                # Only train tanks if we have enough soldiers to maintain ratio
                if num_soldiers >= self.soldier_ratio or num_tanks == 0:
                    if resources > TANK_COST + reserve:
                        if self._try_train_unit(factory, self.resource_manager):
                            resources = self.resource_manager.amount

        # If resources are very high, queue even more aggressively
        if resources > 600:
            for barracks in all_barracks:
                if len(barracks.production_queue) < 5:
                    if self.resource_manager.can_afford(SOLDIER_COST):
                        self._try_train_unit(barracks, self.resource_manager)

    def _manage_combat(self, player_units, player_buildings, num_combat, player_combat):
        """Handle attack waves, scouting, retreating, and defense."""
        # Handle retreat cooldown
        if self._retreat_cooldown > 0:
            self._retreat_cooldown -= self.think_interval
            return

        # DEFENSE: React to attacks on our buildings
        under_attack = self._check_defense(player_units)

        if under_attack:
            return  # Defense takes priority

        # Adaptive aggression: if we have many more resources, be aggressive
        resource_advantage = self.resource_manager.amount > 300

        # Determine attack threshold (lower if we have resource advantage)
        effective_threshold = self.attack_threshold
        if resource_advantage:
            effective_threshold = max(3, self.attack_threshold - 2)

        # SCOUTING: Send a scout before the main army
        if not self._scout_sent and not self._enemy_base_location and num_combat >= 2:
            self._send_scout(player_units, player_buildings)

        # ATTACK: Launch attack wave
        if num_combat >= effective_threshold and not self.attack_sent:
            self._launch_attack_wave(player_units, player_buildings, num_combat, player_combat)
        elif self.attack_sent:
            # Check if attack wave is spent
            alive_attackers = sum(
                1 for u in self.units
                if isinstance(u, (Soldier, Scout, Tank)) and u.alive and id(u) in self._attacking_units
            )
            if alive_attackers < 2:
                # Attack wave is spent, reset
                self.attack_sent = False
                self._attacking_units.clear()
                self._scout_sent = False
                self._enemy_base_location = None

            # Check if we should retreat (badly outnumbered)
            elif player_combat > 0 and alive_attackers / max(player_combat, 1) < self.retreat_ratio:
                self._retreat()

            # Check if attack target area is clear — find a new target
            elif self.attack_target:
                new_target = self._find_attack_target(player_units, player_buildings)
                if new_target and new_target != self.attack_target:
                    self.attack_target = new_target
                    # Re-send all idle attackers to the new target
                    for u in self.units:
                        if isinstance(u, (Soldier, Scout, Tank)) and u.alive and id(u) in self._attacking_units:
                            if not u.attacking and not u.waypoints:
                                spread = random.randint(-80, 80), random.randint(-80, 80)
                                u.set_target((new_target[0] + spread[0], new_target[1] + spread[1]))
                elif new_target is None:
                    # No more targets — victory, recall units
                    self.attack_sent = False
                    self._attacking_units.clear()

    def _send_scout(self, player_units, player_buildings):
        """Send a single fast unit to find the player's base."""
        for unit in self.units:
            if isinstance(unit, Soldier) and unit.alive and not unit.attacking:
                if id(unit) not in self._attacking_units:
                    # Send toward the player side of the map
                    target = None
                    for b in player_buildings:
                        if b.hp > 0:
                            target = (b.x + b.w // 2, b.y + b.h // 2)
                            break
                    if target is None:
                        # Scout toward left side of map
                        target = (200, WORLD_H // 2)

                    unit.set_target(target)
                    self._scout_sent = True
                    self._scout_unit_id = id(unit)
                    self._enemy_base_location = target
                    return

    def _launch_attack_wave(self, player_units, player_buildings, num_combat, player_combat):
        """Send an attack wave, keeping some units as garrison."""
        target = self._find_attack_target(player_units, player_buildings)
        if target is None:
            return

        self.attack_target = target
        self.attack_sent = True

        # Determine how many units to send (keep garrison at base)
        combat_units = self._get_combat_units()
        num_to_send = max(3, int(len(combat_units) * (1.0 - self.garrison_ratio)))

        # Sort by distance to target (send closest units first)
        combat_units.sort(key=lambda u: math.hypot(u.x - target[0], u.y - target[1]))

        sent = 0
        for unit in combat_units:
            if sent >= num_to_send:
                break
            if id(unit) == self._scout_unit_id:
                self._attacking_units.add(id(unit))
                sent += 1
                continue
            # Spread units around the target so they don't all pile on one pixel
            spread = random.randint(-80, 80), random.randint(-80, 80)
            unit.set_target((target[0] + spread[0], target[1] + spread[1]))
            self._attacking_units.add(id(unit))
            sent += 1

        # Remaining units are garrison
        self._garrison_units.clear()
        for unit in combat_units:
            if id(unit) not in self._attacking_units:
                self._garrison_units.add(id(unit))

        self._last_attack_army_size = sent

    def _find_attack_target(self, player_units, player_buildings):
        """Find the best target to attack: prioritize production buildings."""
        target = None
        best_priority = float("inf")

        for b in player_buildings:
            if b.hp <= 0:
                continue
            bx, by = b.x + b.w // 2, b.y + b.h // 2
            # Prioritize: Barracks/Factory first (cripple production), then TownCenter
            if isinstance(b, (Barracks, Factory)):
                priority = 0  # highest priority
            elif isinstance(b, TownCenter):
                priority = 1
            else:
                priority = 2
            # Among same priority, prefer closer to left (player side)
            score = priority * 100000 + bx
            if score < best_priority:
                best_priority = score
                target = (bx, by)

        if target is None:
            for u in player_units:
                if u.alive:
                    target = (u.x, u.y)
                    break

        return target

    def _retreat(self):
        """Pull attacking units back to base."""
        base = self._get_base_center()
        for unit in self.units:
            if isinstance(unit, (Soldier, Scout, Tank)) and unit.alive and id(unit) in self._attacking_units:
                unit.target_enemy = None
                unit.attacking = False
                unit.set_target(base)

        self.attack_sent = False
        self._attacking_units.clear()
        self._scout_sent = False
        self._enemy_base_location = None
        # Set retreat cooldown: wait before next attack, and build a bigger force
        self._retreat_cooldown = 8.0

    def _check_defense(self, player_units):
        """If AI buildings are under attack, pull nearby combat units to defend.
        Returns True if defense was triggered."""
        for b in self.buildings:
            if b.hp < b.max_hp:
                # Building damaged -- find nearby enemy
                for pu in player_units:
                    if not pu.alive:
                        continue
                    bx, by = b.x + b.w // 2, b.y + b.h // 2
                    dist = math.hypot(pu.x - bx, pu.y - by)
                    if dist < 300:  # Increased detection range from 200
                        # Pull garrison units and nearby idle units to defend
                        for unit in self.units:
                            if isinstance(unit, (Soldier, Scout, Tank)) and unit.alive:
                                is_garrison = id(unit) in self._garrison_units
                                unit_to_base = math.hypot(unit.x - bx, unit.y - by)
                                if is_garrison or unit_to_base < 400:
                                    if not unit.attacking or id(unit) in self._garrison_units:
                                        unit.set_target((pu.x, pu.y))
                        return True
        return False

    # --- Focus fire support ---

    def _apply_focus_fire(self, player_units, player_buildings):
        """Make all attacking AI combat units in range focus the same target."""
        best_target = None
        lowest_hp = float("inf")

        for unit in self.units:
            if not isinstance(unit, (Soldier, Scout, Tank)) or not unit.alive:
                continue
            if not unit.attacking or not unit.target_enemy:
                continue
            target = unit.target_enemy
            hp = target.hp if hasattr(target, 'hp') else float("inf")
            if hp > 0 and hp < lowest_hp:
                lowest_hp = hp
                best_target = target

        if best_target is None:
            return

        # Redirect other attacking units to this same target if in range
        for unit in self.units:
            if not isinstance(unit, (Soldier, Scout, Tank)) or not unit.alive:
                continue
            if not unit.attacking:
                continue
            if unit.target_enemy is best_target:
                continue
            # Check if the focus target is in range
            if hasattr(best_target, 'size'):
                tx, ty = best_target.x, best_target.y
            elif hasattr(best_target, 'w'):
                tx = best_target.x + best_target.w // 2
                ty = best_target.y + best_target.h // 2
            else:
                continue
            dist = unit.distance_to(tx, ty)
            if dist <= unit.attack_range * 1.5:
                unit.target_enemy = best_target

    # --- Collision avoidance ---

    def _collides_with_other(self, unit, x, y, all_units):
        """Check if unit at position (x, y) would overlap any other unit."""
        for other in all_units:
            if other is unit:
                continue
            dist = math.hypot(x - other.x, y - other.y)
            if dist < unit.size + other.size:
                return other
        return None

    def _place_unit_at_free_spot(self, unit, all_units):
        """Nudge a newly spawned unit to a free spot if it overlaps."""
        if not self._collides_with_other(unit, unit.x, unit.y, all_units):
            return
        spacing = unit.size * 2
        for ring in range(1, 10):
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if abs(dx) != ring and abs(dy) != ring:
                        continue
                    nx = unit.x + dx * spacing
                    ny = unit.y + dy * spacing
                    if nx < unit.size or nx > WORLD_W - unit.size:
                        continue
                    if ny < unit.size or ny > WORLD_H - unit.size:
                        continue
                    if not self._collides_with_other(unit, nx, ny, all_units):
                        unit.x, unit.y = nx, ny
                        return

    # --- Main update ---

    def _handle_deploying_workers(self, dt):
        """Check for AI workers that have arrived at their deploy target."""
        for unit in self.units:
            if not isinstance(unit, Worker) or unit.state != "deploying" or unit.waypoints:
                continue
            # Worker has arrived — start or continue building
            if not unit.deploy_building:
                unit.deploy_building = True
                unit.deploy_build_timer = 0.0

            unit.deploy_build_timer += dt
            build_time = unit.deploy_building_class.build_time
            if unit.deploy_build_timer < build_time:
                continue  # Still constructing

            # Construction complete
            bx, by = unit.deploy_target
            b = unit.deploy_building_class(bx, by)
            b.team = "ai"

            valid = True
            if b.rect.bottom > WORLD_H or b.rect.top < 0 or b.rect.left < 0 or b.rect.right > WORLD_W:
                valid = False
            if valid:
                for existing in self.buildings:
                    if b.rect.colliderect(existing.rect):
                        valid = False
                        break
            if valid:
                for node in self.mineral_nodes:
                    if not node.depleted and b.rect.colliderect(node.rect.inflate(10, 10)):
                        valid = False
                        break

            if valid:
                if self._game_state:
                    self._game_state.assign_building_id(b)
                self.buildings.append(b)
            else:
                self.resource_manager.deposit(unit.deploy_cost)

            unit.state = "idle"
            unit.deploy_building_class = None
            unit.deploy_target = None
            unit.deploy_cost = 0
            unit.deploy_build_timer = 0.0
            unit.deploy_building = False

    def update(self, dt, player_units, player_buildings, all_units_for_collision):
        """Update AI: think, produce, move units."""
        self._ensure_tinted_sprites()

        # Handle deploying workers (create buildings when they arrive)
        self._handle_deploying_workers(dt)

        # Periodic decision making
        self.think_timer += dt
        if self.think_timer >= self.think_interval:
            self.think_timer = 0.0
            self._think(player_units, player_buildings)
            # Apply focus fire after thinking
            self._apply_focus_fire(player_units, player_buildings)

        # Update building production and tower combat
        for building in self.buildings:
            if isinstance(building, DefenseTower):
                building.combat_update(dt, player_units)
            else:
                new_unit = building.update(dt)
                if new_unit is not None:
                    new_unit.team = "ai"
                    if self._game_state:
                        self._game_state.assign_unit_id(new_unit)
                    self._place_unit_at_free_spot(new_unit, all_units_for_collision)
                    self.units.append(new_unit)

        # Auto-target: AI combat units attack player units in range
        for unit in self.units:
            if not unit.alive:
                continue

            if isinstance(unit, Worker):
                # Workers just do their mining state machine
                if unit.state != "idle" and unit.waypoints:
                    # Movement handled by game_state avoidance system
                    pass
                if unit.state != "idle":
                    unit.update_state(dt)
                continue

            if unit.attacking:
                target = unit.target_enemy
                if not target:
                    unit.attacking = False
                elif (hasattr(target, 'alive') and not target.alive) or \
                     (hasattr(target, 'hp') and target.hp <= 0):
                    unit.target_enemy = None
                    unit.attacking = False
                else:
                    # Check target still in range
                    if hasattr(target, 'size'):
                        tx, ty = target.x, target.y
                    else:
                        tx, ty = target.x + target.w // 2, target.y + target.h // 2
                    if unit.distance_to(tx, ty) <= unit.attack_range:
                        unit.try_attack(dt)
                    else:
                        # Target moved out of range — disengage
                        unit.target_enemy = None
                        unit.attacking = False
                continue

            # Auto-target: find nearest player unit/building in range
            if isinstance(unit, (Soldier, Scout, Tank)):
                target = unit.find_target(player_units, player_buildings)
                if target:
                    unit.hunting_target = None
                    unit.target_enemy = target
                    unit.attacking = True
                    unit.fire_cooldown = 0.0
                    unit.try_attack(dt)
                    continue
                # Vision hunting: chase enemies visible but out of firing range
                if not unit.waypoints or unit.hunting_target:
                    if unit.hunting_target:
                        ht = unit.hunting_target
                        alive = (hasattr(ht, 'alive') and ht.alive) or \
                                (hasattr(ht, 'hp') and ht.hp > 0)
                        if alive:
                            if hasattr(ht, 'size'):
                                hx, hy = ht.x, ht.y
                            else:
                                hx, hy = ht.x + ht.w // 2, ht.y + ht.h // 2
                            dist = unit.distance_to(hx, hy)
                            if dist <= unit.vision_range:
                                unit.waypoints = [(hx, hy)]
                            else:
                                unit.hunting_target = None
                                unit.waypoints = []
                        else:
                            unit.hunting_target = None
                            unit.waypoints = []
                    else:
                        visible = unit.find_visible_target(player_units, player_buildings)
                        if visible:
                            unit.hunting_target = visible
                            if hasattr(visible, 'size'):
                                hx, hy = visible.x, visible.y
                            else:
                                hx, hy = visible.x + visible.w // 2, visible.y + visible.h // 2
                            unit.waypoints = [(hx, hy)]
                if not unit.waypoints and self.attack_target:
                    if id(unit) in self._attacking_units:
                        # Resume moving toward attack target after killing an enemy
                        dist = math.hypot(unit.x - self.attack_target[0], unit.y - self.attack_target[1])
                        if dist > unit.attack_range:
                            spread = random.randint(-80, 80), random.randint(-80, 80)
                            unit.set_target((self.attack_target[0] + spread[0], self.attack_target[1] + spread[1]))
                    elif self.attack_sent and id(unit) not in self._garrison_units:
                        # Newly spawned combat unit — reinforce ongoing attack
                        self._attacking_units.add(id(unit))
                        spread = random.randint(-80, 80), random.randint(-80, 80)
                        unit.set_target((self.attack_target[0] + spread[0], self.attack_target[1] + spread[1]))

        # Clean up stale IDs from tracking sets
        alive_ids = {id(u) for u in self.units if u.alive}
        self._attacking_units &= alive_ids
        self._garrison_units &= alive_ids

        # Remove dead AI units (release mining nodes / cancel deploy first)
        for u in self.units:
            if not u.alive and isinstance(u, Worker):
                u.cancel_mining()
                u.cancel_deploy()  # cost lost on death
        self.units = [u for u in self.units if u.alive]

        # Remove dead AI buildings
        self.buildings = [b for b in self.buildings if b.hp > 0]

    def draw(self, surface):
        """Draw all AI buildings and units with orange tint."""
        self._ensure_tinted_sprites()

        # Draw AI mineral nodes
        for node in self.mineral_nodes:
            node.draw(surface)

        # Draw AI buildings
        for building in self.buildings:
            tinted = self._get_tinted_sprite(building)
            if tinted:
                surface.blit(tinted, (building.x, building.y))
            else:
                building.draw(surface)
                continue
            # Draw health bar and label (same style as Building.draw but skip sprite)
            if building.selected:
                pygame.draw.rect(surface, (255, 120, 0), building.rect.inflate(6, 6), 2)
            # Health bar
            bar_w = building.w
            bar_h = 4
            bx, by = building.x, building.y - 8
            pygame.draw.rect(surface, (80, 0, 0), (bx, by, bar_w, bar_h))
            fill_w = int(bar_w * (building.hp / building.max_hp))
            pygame.draw.rect(surface, (255, 140, 0), (bx, by, fill_w, bar_h))
            # Label
            label = get_font(18).render(f"AI {building.label}", True, (255, 180, 100))
            label_rect = label.get_rect(center=(building.x + building.w // 2, building.y - 16))
            surface.blit(label, label_rect)
            # Production bar
            if building.production_queue:
                prog_y = building.y + building.h + 2
                pygame.draw.rect(surface, (60, 60, 60), (building.x, prog_y, building.w, 4))
                prog = building.production_progress
                pygame.draw.rect(surface, (255, 140, 0),
                                 (building.x, prog_y, int(building.w * prog), 4))

        # Draw AI units
        for unit in self.units:
            tinted = self._get_tinted_sprite(unit)
            if tinted:
                r = tinted.get_rect(center=(int(unit.x), int(unit.y)))
                surface.blit(tinted, r)
            else:
                unit.draw(surface)
                continue
            # Draw health bar
            bar_w = unit.size * 2
            bar_h = 3
            bx = unit.x - unit.size
            by = unit.y - unit.size - 6
            pygame.draw.rect(surface, (80, 0, 0), (bx, by, bar_w, bar_h))
            fill_w = int(bar_w * (unit.hp / unit.max_hp))
            pygame.draw.rect(surface, (255, 140, 0), (bx, by, fill_w, bar_h))
