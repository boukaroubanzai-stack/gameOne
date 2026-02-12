import math
import random
from buildings import Barracks, Factory, TownCenter, DefenseTower
from units import Worker, Soldier, Tank
from settings import (
    WORLD_W, WORLD_H,
    BARRACKS_COST, FACTORY_COST, TOWN_CENTER_COST, TOWER_COST,
    SOLDIER_COST, TANK_COST, WORKER_COST,
    BARRACKS_SIZE, FACTORY_SIZE, TOWN_CENTER_SIZE, TOWER_SIZE,
)

# PlayerAI decision timers (seconds)
THINK_INTERVAL = 1.0
MAX_WORKERS = 8

# Army composition targets
SOLDIER_RATIO = 3  # 3 soldiers per 1 tank
ATTACK_THRESHOLD = 6  # min combat units before first attack wave
GARRISON_RATIO = 0.3  # keep 30% of army at base for defense
RETREAT_RATIO = 0.3  # retreat when army is < 30% of enemy force
RESOURCE_RESERVE = 100  # keep some resources for emergency replacements


class PlayerAI:
    """AI controller for the player side. Reads/writes state entities directly."""

    def __init__(self):
        self.think_timer = 0.0
        self.phase = "economy"  # "economy", "military", "attack", "defend"
        self.attack_sent = False
        self.attack_target = None

        # Attack wave tracking
        self._attacking_units = set()
        self._garrison_units = set()
        self._scout_sent = False
        self._scout_unit_id = None
        self._enemy_base_location = None
        self._last_attack_army_size = 0
        self._retreat_cooldown = 0.0
        self._buildings_lost_recently = 0
        self._last_building_count = 0

    # --- Helpers ---

    def _get_buildings(self, state):
        return [b for b in state.buildings if b.hp > 0]

    def _get_buildings_of_type(self, state, building_type):
        return [b for b in state.buildings if isinstance(b, building_type) and b.hp > 0]

    def _count_buildings_of_type(self, state, building_type):
        return sum(1 for b in state.buildings if isinstance(b, building_type) and b.hp > 0)

    def _find_town_center(self, state):
        for b in state.buildings:
            if isinstance(b, TownCenter) and b.hp > 0:
                return b
        return None

    def _count_workers(self, state):
        return sum(1 for u in state.units if isinstance(u, Worker) and u.alive)

    def _count_soldiers(self, state):
        return sum(1 for u in state.units if isinstance(u, Soldier) and u.alive)

    def _count_tanks(self, state):
        return sum(1 for u in state.units if isinstance(u, Tank) and u.alive)

    def _count_combat_units(self, state):
        return sum(1 for u in state.units if isinstance(u, (Soldier, Tank)) and u.alive)

    def _get_combat_units(self, state):
        return [u for u in state.units if isinstance(u, (Soldier, Tank)) and u.alive]

    def _get_base_center(self, state):
        alive = [b for b in state.buildings if b.hp > 0]
        if not alive:
            return (100, 280)
        cx = sum(b.x + b.w // 2 for b in alive) / len(alive)
        cy = sum(b.y + b.h // 2 for b in alive) / len(alive)
        return (cx, cy)

    # --- Economy ---

    def _find_best_mineral_node(self, state, worker):
        """Find the best mineral node, distributing workers across nodes."""
        node_counts = {}
        for node in state.mineral_nodes:
            if not node.depleted:
                node_counts[id(node)] = 0

        for u in state.units:
            if isinstance(u, Worker) and u.alive and u.assigned_node and not u.assigned_node.depleted:
                nid = id(u.assigned_node)
                if nid in node_counts:
                    node_counts[nid] = node_counts.get(nid, 0) + 1

        best_node = None
        best_score = float("inf")
        for node in state.mineral_nodes:
            if node.depleted:
                continue
            nid = id(node)
            count = node_counts.get(nid, 0)
            dist = math.hypot(worker.x - node.x, worker.y - node.y)
            score = count * 10000 + dist
            if score < best_score:
                best_score = score
                best_node = node
        return best_node

    def _assign_idle_workers(self, state):
        tc = self._find_town_center(state)
        if tc is None:
            return
        for unit in state.units:
            if isinstance(unit, Worker) and unit.alive:
                if unit.state == "idle":
                    node = self._find_best_mineral_node(state, unit)
                    if node:
                        unit.assign_to_mine(node, state.buildings, state.resource_manager)
                elif unit.state == "waiting":
                    # Worker stuck waiting — reassign to a different node
                    node = self._find_best_mineral_node(state, unit)
                    if node and node is not unit.assigned_node:
                        unit.cancel_mining()
                        unit.assign_to_mine(node, state.buildings, state.resource_manager)

    # --- Building placement ---

    def _find_building_placement(self, state, size):
        """Find a valid position near the player base."""
        tc = self._find_town_center(state)
        if tc:
            base_x, base_y = tc.x, tc.y
        else:
            base_x, base_y = self._get_base_center(state)
        bw, bh = size

        for _ in range(80):
            offset_x = random.randint(-300, 300)
            offset_y = random.randint(-250, 300)
            x = base_x + offset_x
            y = base_y + offset_y

            x = max(0, min(x, WORLD_W - bw))
            y = max(0, min(y, WORLD_H - bh))

            rect = __import__('pygame').Rect(x, y, bw, bh)

            # Check no overlap with player buildings
            overlap = False
            for b in state.buildings:
                if rect.colliderect(b.rect.inflate(20, 20)):
                    overlap = True
                    break

            # Check no overlap with AI buildings
            if not overlap:
                for b in state.ai_player.buildings:
                    if rect.colliderect(b.rect.inflate(20, 20)):
                        overlap = True
                        break

            # Check no overlap with player mineral nodes
            if not overlap:
                for node in state.mineral_nodes:
                    if not node.depleted and rect.colliderect(node.rect.inflate(20, 20)):
                        overlap = True
                        break

            # Check no overlap with AI mineral nodes
            if not overlap:
                for node in state.ai_player.mineral_nodes:
                    if not node.depleted and rect.colliderect(node.rect.inflate(20, 20)):
                        overlap = True
                        break

            if not overlap:
                return (x, y)
        return None

    def _try_place_building(self, state, building_class, cost, size):
        """Place a building by sending an idle worker to deploy it."""
        if not state.resource_manager.can_afford(cost):
            return False
        # Find an idle worker
        idle_workers = [u for u in state.units
                        if isinstance(u, Worker) and u.alive and u.state == "idle"]
        if not idle_workers:
            return False
        pos = self._find_building_placement(state, size)
        if pos is None:
            return False
        state.resource_manager.spend(cost)
        closest = min(idle_workers, key=lambda w: math.hypot(w.x - pos[0], w.y - pos[1]))
        closest.assign_to_deploy(building_class, pos, cost)
        return True

    def _try_train_unit(self, building, resource_mgr):
        unit_class, cost, train_time = building.can_train()
        if resource_mgr.spend(cost):
            building.production_queue.append((unit_class, train_time))
            return True
        return False

    # --- Strategic decision making ---

    def _think(self, state, enemies, ai_player):
        self._assign_idle_workers(state)

        # Track building losses
        current_count = len([b for b in state.buildings if b.hp > 0])
        if current_count < self._last_building_count:
            self._buildings_lost_recently += self._last_building_count - current_count
        self._last_building_count = current_count

        num_workers = self._count_workers(state)
        num_soldiers = self._count_soldiers(state)
        num_tanks = self._count_tanks(state)
        num_combat = num_soldiers + num_tanks
        num_barracks = self._count_buildings_of_type(state, Barracks)
        num_factories = self._count_buildings_of_type(state, Factory)
        num_town_centers = self._count_buildings_of_type(state, TownCenter)
        resources = state.resource_manager.amount

        # Count enemy forces (AI opponent + wave enemies)
        enemy_combat = sum(1 for u in ai_player.units if isinstance(u, (Soldier, Tank)) and u.alive)
        enemy_combat += len(enemies)

        self._update_phase(num_workers, num_combat, enemy_combat)
        self._manage_economy(state, num_workers, num_town_centers, resources)
        self._manage_buildings(state, num_barracks, num_factories, num_town_centers, num_combat, resources)
        self._manage_military(state, num_soldiers, num_tanks, num_barracks, num_factories, resources)
        self._manage_combat(state, enemies, ai_player, num_combat, enemy_combat)

    def _update_phase(self, num_workers, num_combat, enemy_combat):
        if self._buildings_lost_recently > 0:
            self.phase = "defend"
            return
        if num_workers < 4 and num_combat < 3:
            self.phase = "economy"
        elif num_combat < ATTACK_THRESHOLD:
            self.phase = "military"
        elif num_combat >= ATTACK_THRESHOLD:
            self.phase = "attack"
        else:
            self.phase = "military"

    def _manage_economy(self, state, num_workers, num_town_centers, resources):
        town_centers = self._get_buildings_of_type(state, TownCenter)
        desired_workers = MAX_WORKERS

        if num_workers < desired_workers:
            for tc in town_centers:
                if num_workers >= desired_workers:
                    break
                if len(tc.production_queue) < 2:
                    if state.resource_manager.can_afford(WORKER_COST):
                        self._try_train_unit(tc, state.resource_manager)
                        num_workers += 1

        if resources > TOWN_CENTER_COST + 200 and num_town_centers < 2 and num_workers >= 4:
            self._try_place_building(state, TownCenter, TOWN_CENTER_COST, TOWN_CENTER_SIZE)

    def _manage_buildings(self, state, num_barracks, num_factories, num_town_centers, num_combat, resources):
        # Build first Barracks ASAP
        if num_barracks == 0:
            self._try_place_building(state, Barracks, BARRACKS_COST, BARRACKS_SIZE)
            return

        # Second Barracks before Factory
        if num_barracks < 2 and resources >= BARRACKS_COST + RESOURCE_RESERVE:
            self._try_place_building(state, Barracks, BARRACKS_COST, BARRACKS_SIZE)

        # First Factory after 2 Barracks
        if num_barracks >= 2 and num_factories == 0 and resources >= FACTORY_COST + RESOURCE_RESERVE:
            self._try_place_building(state, Factory, FACTORY_COST, FACTORY_SIZE)

        # Expand production when rich and queues full
        if resources > 400:
            all_barracks = self._get_buildings_of_type(state, Barracks)
            all_queues_full = all(len(b.production_queue) >= 2 for b in all_barracks) if all_barracks else True
            if all_queues_full and num_barracks < 4:
                self._try_place_building(state, Barracks, BARRACKS_COST, BARRACKS_SIZE)

            all_factories = self._get_buildings_of_type(state, Factory)
            all_factory_queues_full = all(len(b.production_queue) >= 2 for b in all_factories) if all_factories else True
            if all_factory_queues_full and num_factories < 2 and num_factories > 0:
                self._try_place_building(state, Factory, FACTORY_COST, FACTORY_SIZE)

        # Build defense towers only when waves are active
        if state.wave_manager.wave_active and resources > 300 and num_barracks >= 1:
            num_towers = self._count_buildings_of_type(state, DefenseTower)
            if num_towers < 3:
                self._try_place_building(state, DefenseTower, TOWER_COST, TOWER_SIZE)

        # Rebuild destroyed buildings
        if self._buildings_lost_recently > 0 and resources >= BARRACKS_COST:
            if num_barracks == 0:
                if self._try_place_building(state, Barracks, BARRACKS_COST, BARRACKS_SIZE):
                    self._buildings_lost_recently = max(0, self._buildings_lost_recently - 1)
            if num_town_centers == 0:
                if self._try_place_building(state, TownCenter, TOWN_CENTER_COST, TOWN_CENTER_SIZE):
                    self._buildings_lost_recently = max(0, self._buildings_lost_recently - 1)
            if num_factories == 0 and num_barracks >= 1:
                if self._try_place_building(state, Factory, FACTORY_COST, FACTORY_SIZE):
                    self._buildings_lost_recently = max(0, self._buildings_lost_recently - 1)
            self._buildings_lost_recently = max(0, self._buildings_lost_recently - 1)

    def _manage_military(self, state, num_soldiers, num_tanks, num_barracks, num_factories, resources):
        reserve = RESOURCE_RESERVE if self.phase != "attack" else 50

        desired_soldiers = (num_tanks + 1) * SOLDIER_RATIO
        need_soldiers = num_soldiers < desired_soldiers

        all_barracks = self._get_buildings_of_type(state, Barracks)
        for barracks in all_barracks:
            if len(barracks.production_queue) < 3:
                if need_soldiers or num_tanks > 0:
                    if resources > SOLDIER_COST + reserve:
                        if self._try_train_unit(barracks, state.resource_manager):
                            resources = state.resource_manager.amount

        all_factories = self._get_buildings_of_type(state, Factory)
        for factory in all_factories:
            if len(factory.production_queue) < 2:
                if num_soldiers >= SOLDIER_RATIO or num_tanks == 0:
                    if resources > TANK_COST + reserve:
                        if self._try_train_unit(factory, state.resource_manager):
                            resources = state.resource_manager.amount

        # Aggressive queuing when rich
        if resources > 600:
            for barracks in all_barracks:
                if len(barracks.production_queue) < 5:
                    if state.resource_manager.can_afford(SOLDIER_COST):
                        self._try_train_unit(barracks, state.resource_manager)

    # --- Combat ---

    def _manage_combat(self, state, enemies, ai_player, num_combat, enemy_combat):
        if self._retreat_cooldown > 0:
            self._retreat_cooldown -= THINK_INTERVAL
            return

        # All hostile entities (AI opponent units + wave enemies)
        hostile_units = ai_player.units + enemies
        hostile_buildings = ai_player.buildings

        under_attack = self._check_defense(state, hostile_units)
        if under_attack:
            return

        resource_advantage = state.resource_manager.amount > 300
        effective_threshold = ATTACK_THRESHOLD
        if resource_advantage:
            effective_threshold = max(3, ATTACK_THRESHOLD - 2)

        # Scouting
        if not self._scout_sent and not self._enemy_base_location and num_combat >= 2:
            self._send_scout(state, hostile_units, hostile_buildings)

        # Attack
        if num_combat >= effective_threshold and not self.attack_sent:
            self._launch_attack(state, hostile_units, hostile_buildings, num_combat, enemy_combat)
        elif self.attack_sent:
            alive_attackers = sum(
                1 for u in state.units
                if isinstance(u, (Soldier, Tank)) and u.alive and id(u) in self._attacking_units
            )
            if alive_attackers < 2:
                self.attack_sent = False
                self._attacking_units.clear()
                self._scout_sent = False
                self._enemy_base_location = None
            elif enemy_combat > 0 and alive_attackers / max(enemy_combat, 1) < RETREAT_RATIO:
                self._retreat(state)
            # Check if attack target area is clear — find a new target
            elif self.attack_target:
                new_target = self._find_attack_target(hostile_units, hostile_buildings)
                if new_target and new_target != self.attack_target:
                    self.attack_target = new_target
                    for u in state.units:
                        if isinstance(u, (Soldier, Tank)) and u.alive and id(u) in self._attacking_units:
                            if not u.attacking and not u.waypoints:
                                spread = random.randint(-80, 80), random.randint(-80, 80)
                                u.set_target((new_target[0] + spread[0], new_target[1] + spread[1]))
                elif new_target is None:
                    self.attack_sent = False
                    self._attacking_units.clear()

    def _send_scout(self, state, hostile_units, hostile_buildings):
        for unit in state.units:
            if isinstance(unit, Soldier) and unit.alive and not unit.attacking:
                if id(unit) not in self._attacking_units:
                    target = None
                    for b in hostile_buildings:
                        if b.hp > 0:
                            target = (b.x + b.w // 2, b.y + b.h // 2)
                            break
                    if target is None:
                        # Scout toward the right (AI base side)
                        target = (WORLD_W - 200, WORLD_H // 2)
                    unit.set_target(target)
                    self._scout_sent = True
                    self._scout_unit_id = id(unit)
                    self._enemy_base_location = target
                    return

    def _launch_attack(self, state, hostile_units, hostile_buildings, num_combat, enemy_combat):
        target = self._find_attack_target(hostile_units, hostile_buildings)
        if target is None:
            return

        self.attack_target = target
        self.attack_sent = True

        combat_units = self._get_combat_units(state)
        num_to_send = max(3, int(len(combat_units) * (1.0 - GARRISON_RATIO)))

        combat_units.sort(key=lambda u: math.hypot(u.x - target[0], u.y - target[1]))

        sent = 0
        for unit in combat_units:
            if sent >= num_to_send:
                break
            if id(unit) == self._scout_unit_id:
                self._attacking_units.add(id(unit))
                sent += 1
                continue
            spread = random.randint(-80, 80), random.randint(-80, 80)
            unit.set_target((target[0] + spread[0], target[1] + spread[1]))
            self._attacking_units.add(id(unit))
            sent += 1

        self._garrison_units.clear()
        for unit in combat_units:
            if id(unit) not in self._attacking_units:
                self._garrison_units.add(id(unit))

        self._last_attack_army_size = sent

    def _find_attack_target(self, hostile_units, hostile_buildings):
        target = None
        best_priority = float("inf")

        for b in hostile_buildings:
            if b.hp <= 0:
                continue
            bx, by = b.x + b.w // 2, b.y + b.h // 2
            if isinstance(b, (Barracks, Factory)):
                priority = 0
            elif isinstance(b, TownCenter):
                priority = 1
            else:
                priority = 2
            # Prefer targets further right (AI base side)
            score = priority * 100000 - bx
            if score < best_priority:
                best_priority = score
                target = (bx, by)

        if target is None:
            for u in hostile_units:
                if u.alive:
                    target = (u.x, u.y)
                    break

        return target

    def _retreat(self, state):
        base = self._get_base_center(state)
        for unit in state.units:
            if isinstance(unit, (Soldier, Tank)) and unit.alive and id(unit) in self._attacking_units:
                unit.target_enemy = None
                unit.attacking = False
                unit.set_target(base)

        self.attack_sent = False
        self._attacking_units.clear()
        self._scout_sent = False
        self._enemy_base_location = None
        self._retreat_cooldown = 8.0

    def _check_defense(self, state, hostile_units):
        for b in state.buildings:
            if b.hp < b.max_hp:
                for hu in hostile_units:
                    if not hu.alive:
                        continue
                    bx, by = b.x + b.w // 2, b.y + b.h // 2
                    dist = math.hypot(hu.x - bx, hu.y - by)
                    if dist < 300:
                        for unit in state.units:
                            if isinstance(unit, (Soldier, Tank)) and unit.alive:
                                is_garrison = id(unit) in self._garrison_units
                                unit_to_base = math.hypot(unit.x - bx, unit.y - by)
                                if is_garrison or unit_to_base < 400:
                                    if not unit.attacking or id(unit) in self._garrison_units:
                                        unit.set_target((hu.x, hu.y))
                        return True
        return False

    def _apply_focus_fire(self, state):
        """Make attacking combat units focus the same target."""
        best_target = None
        lowest_hp = float("inf")

        for unit in state.units:
            if not isinstance(unit, (Soldier, Tank)) or not unit.alive:
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

        for unit in state.units:
            if not isinstance(unit, (Soldier, Tank)) or not unit.alive:
                continue
            if not unit.attacking:
                continue
            if unit.target_enemy is best_target:
                continue
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

    def _resend_idle_attackers(self, state):
        """Re-send attack-wave units that finished a fight but have no waypoints,
        and reinforce with newly spawned combat units."""
        if not self.attack_sent or not self.attack_target:
            return
        for unit in state.units:
            if not isinstance(unit, (Soldier, Tank)) or not unit.alive:
                continue
            if not unit.attacking and not unit.waypoints:
                if id(unit) in self._attacking_units:
                    # Known attacker idle — re-send to target
                    dist = math.hypot(unit.x - self.attack_target[0], unit.y - self.attack_target[1])
                    if dist > unit.attack_range:
                        spread = random.randint(-80, 80), random.randint(-80, 80)
                        unit.set_target((self.attack_target[0] + spread[0], self.attack_target[1] + spread[1]))
                elif id(unit) not in self._garrison_units:
                    # Newly spawned combat unit — reinforce ongoing attack
                    self._attacking_units.add(id(unit))
                    spread = random.randint(-80, 80), random.randint(-80, 80)
                    unit.set_target((self.attack_target[0] + spread[0], self.attack_target[1] + spread[1]))

    # --- Main update ---

    def update(self, dt, state, enemies, ai_player):
        """Called each frame from the game loop."""
        self.think_timer += dt
        if self.think_timer >= THINK_INTERVAL:
            self.think_timer = 0.0
            self._think(state, enemies, ai_player)
            self._apply_focus_fire(state)
            self._resend_idle_attackers(state)

        # Clean up stale IDs from tracking sets
        alive_ids = {id(u) for u in state.units if u.alive}
        self._attacking_units &= alive_ids
        self._garrison_units &= alive_ids
