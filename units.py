"""Unit entities: base Unit class, Soldier, Tank, Worker (mining/building), Yanuses."""

import math
import pygame
from settings import (
    SOLDIER_HP, SOLDIER_SPEED, SOLDIER_SIZE,
    SOLDIER_FIRE_RATE, SOLDIER_DAMAGE, SOLDIER_RANGE,
    SCOUT_HP, SCOUT_SPEED, SCOUT_SIZE,
    SCOUT_FIRE_RATE, SCOUT_DAMAGE, SCOUT_RANGE, SCOUT_VISION, SCOUT_SPRITE,
    TANK_HP, TANK_SPEED, TANK_SIZE,
    TANK_FIRE_RATE, TANK_DAMAGE, TANK_RANGE,
    WORKER_HP, WORKER_SPEED, WORKER_SIZE,
    WORKER_CARRY_CAPACITY, WORKER_MINE_TIME,
    YANUSES_HP, YANUSES_SPEED, YANUSES_SIZE,
    YANUSES_FIRE_RATE, YANUSES_DAMAGE, YANUSES_RANGE,
    YANUSES_SPRITE,
    SELECT_COLOR, HEALTH_BAR_BG, HEALTH_BAR_FG,
    SOLDIER_SPRITE, TANK_SPRITE, WORKER_SPRITE,
    MINERAL_NODE_SIZE,
)


def _load_sprite(path, size):
    img = pygame.image.load(path).convert_alpha()
    return pygame.transform.smoothscale(img, size)


class Unit:
    """Base class for all units. Handles movement, combat targeting, health, and drawing."""
    sprite = None

    def __init__(self, x, y, hp, speed, size, team="player",
                 fire_rate=0, damage=0, attack_range=0):
        self.x = float(x)
        self.y = float(y)
        self.hp = hp
        self.max_hp = hp
        self.speed = speed
        self.size = size
        self.selected = False
        self.waypoints = []
        # Combat attributes
        self.team = team
        self.fire_rate = fire_rate
        self.damage = damage
        self.attack_range = attack_range
        self.fire_cooldown = 0.0
        self.target_enemy = None
        self.attacking = False
        self.hunting_target = None  # enemy visible but out of firing range
        self.stance = "aggressive"  # "aggressive" or "defensive"
        self.net_id = None  # multiplayer entity ID
        # Stuck detection
        self.stuck = False
        self.stuck_timer = 0.0
        self._last_x = float(x)
        self._last_y = float(y)
        # Interpolation state (for smooth multiplayer rendering)
        self._prev_x = float(x)
        self._prev_y = float(y)

    @property
    def vision_range(self):
        return self.attack_range * 1.2

    @property
    def alive(self):
        return self.hp > 0

    def set_target(self, pos):
        self.target_enemy = None
        self.attacking = False
        self.hunting_target = None
        self.stuck = False
        self.stuck_timer = 0.0
        self.waypoints = [pos]

    def add_waypoint(self, pos):
        self.target_enemy = None
        self.attacking = False
        self.hunting_target = None
        self.stuck = False
        self.stuck_timer = 0.0
        self.waypoints.append(pos)

    def distance_to(self, other_x, other_y):
        return math.hypot(self.x - other_x, self.y - other_y)

    def find_target(self, enemies, buildings=None):
        """Find the closest enemy unit or building within attack range."""
        if self.attack_range <= 0:
            return None
        best = None
        best_dist = float("inf")
        for enemy in enemies:
            if not enemy.alive:
                continue
            dist = self.distance_to(enemy.x, enemy.y)
            if dist <= self.attack_range and dist < best_dist:
                best_dist = dist
                best = enemy
        if buildings:
            for b in buildings:
                if b.hp <= 0:
                    continue
                bx, by = b.x + b.w // 2, b.y + b.h // 2
                dist = self.distance_to(bx, by)
                if dist <= self.attack_range and dist < best_dist:
                    best_dist = dist
                    best = b
        return best

    def find_visible_target(self, enemies, buildings=None):
        """Find the closest enemy unit or building within vision range but outside attack range."""
        if self.vision_range <= 0:
            return None
        best = None
        best_dist = float("inf")
        for enemy in enemies:
            if not enemy.alive:
                continue
            dist = self.distance_to(enemy.x, enemy.y)
            if dist <= self.vision_range and dist > self.attack_range and dist < best_dist:
                best_dist = dist
                best = enemy
        if buildings:
            for b in buildings:
                if b.hp <= 0:
                    continue
                bx, by = b.x + b.w // 2, b.y + b.h // 2
                dist = self.distance_to(bx, by)
                if dist <= self.vision_range and dist > self.attack_range and dist < best_dist:
                    best_dist = dist
                    best = b
        return best

    def try_attack(self, dt):
        """Attempt to fire at the current target. Returns True if a shot was fired."""
        if not self.target_enemy or self.fire_rate <= 0:
            return False
        self.fire_cooldown -= dt
        if self.fire_cooldown <= 0:
            self.target_enemy.hp -= self.damage
            self.fire_cooldown = 1.0 / self.fire_rate
            return True
        return False

    def update(self, dt):
        if self.attacking:
            self.try_attack(dt)
            return
        if not self.waypoints:
            return
        tx, ty = self.waypoints[0]
        dx = tx - self.x
        dy = ty - self.y
        dist = math.hypot(dx, dy)
        if dist < 2:
            self.waypoints.pop(0)
            return
        move = self.speed * dt
        if move >= dist:
            self.x, self.y = tx, ty
            self.waypoints.pop(0)
        else:
            self.x += (dx / dist) * move
            self.y += (dy / dist) * move

    @property
    def rect(self):
        return pygame.Rect(
            self.x - self.size, self.y - self.size,
            self.size * 2, self.size * 2,
        )

    def draw(self, surface):
        if self.sprite:
            r = self.sprite.get_rect(center=(int(self.x), int(self.y)))
            surface.blit(self.sprite, r)
        self._draw_selection(surface)
        self._draw_health_bar(surface)

    def _draw_selection(self, surface):
        if self.selected:
            pygame.draw.rect(surface, SELECT_COLOR, self.rect.inflate(4, 4), 1)

    def _draw_health_bar(self, surface):
        from utils import hp_bar_color
        bar_w = self.size * 2
        bar_h = 3
        bx = self.x - self.size
        by = self.y - self.size - 6
        pygame.draw.rect(surface, HEALTH_BAR_BG, (bx, by, bar_w, bar_h))
        ratio = self.hp / self.max_hp
        fill_w = int(bar_w * ratio)
        pygame.draw.rect(surface, hp_bar_color(ratio), (bx, by, fill_w, bar_h))


class Soldier(Unit):
    name = "Soldier"
    sprite = None

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(SOLDIER_SPRITE, (SOLDIER_SIZE * 2, SOLDIER_SIZE * 2))

    def __init__(self, x, y):
        super().__init__(x, y, SOLDIER_HP, SOLDIER_SPEED, SOLDIER_SIZE,
                         team="player", fire_rate=SOLDIER_FIRE_RATE,
                         damage=SOLDIER_DAMAGE, attack_range=SOLDIER_RANGE)


class Scout(Unit):
    name = "Scout"
    sprite = None

    @classmethod
    def load_assets(cls):
        try:
            cls.sprite = _load_sprite(SCOUT_SPRITE, (SCOUT_SIZE * 2, SCOUT_SIZE * 2))
        except (FileNotFoundError, pygame.error):
            # Fallback: create a simple colored circle sprite
            size = SCOUT_SIZE * 2
            cls.sprite = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(cls.sprite, (0, 200, 200), (SCOUT_SIZE, SCOUT_SIZE), SCOUT_SIZE)
            pygame.draw.circle(cls.sprite, (0, 255, 255), (SCOUT_SIZE, SCOUT_SIZE), SCOUT_SIZE, 2)

    def __init__(self, x, y):
        super().__init__(x, y, SCOUT_HP, SCOUT_SPEED, SCOUT_SIZE,
                         team="player", fire_rate=SCOUT_FIRE_RATE,
                         damage=SCOUT_DAMAGE, attack_range=SCOUT_RANGE)
        self._vision_range = SCOUT_VISION

    @property
    def vision_range(self):
        return self._vision_range


class Tank(Unit):
    name = "Tank"
    sprite = None

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(TANK_SPRITE, (TANK_SIZE * 2, TANK_SIZE * 2))

    def __init__(self, x, y):
        super().__init__(x, y, TANK_HP, TANK_SPEED, TANK_SIZE,
                         team="player", fire_rate=TANK_FIRE_RATE,
                         damage=TANK_DAMAGE, attack_range=TANK_RANGE)


class Worker(Unit):
    name = "Worker"
    sprite = None

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(WORKER_SPRITE, (WORKER_SIZE * 4, WORKER_SIZE * 4))

    def __init__(self, x, y):
        super().__init__(x, y, WORKER_HP, WORKER_SPEED, WORKER_SIZE)
        self._vision_range = SOLDIER_RANGE * 1.2  # same vision as soldiers
        self.state = "idle"  # "idle" | "moving_to_mine" | "waiting" | "mining" | "returning" | "deploying" | "repairing"
        self.assigned_node = None
        self.drop_off_building = None
        self.buildings_list = None
        self.carry_amount = 0
        self.mine_timer = 0.0
        self.resource_manager = None
        # Deploying state
        self.deploy_building_class = None
        self.deploy_target = None
        self.deploy_cost = 0
        self.deploy_build_timer = 0.0
        self.deploy_building = False  # True when worker has arrived and is constructing
        # Repair state
        self.repair_target = None
        self.repair_rate = 5  # HP per second
    @property
    def vision_range(self):
        return self._vision_range

    def _find_closest_town_center(self):
        """Find the closest alive TownCenter from the buildings list."""
        if not self.buildings_list:
            return None
        from buildings import TownCenter
        best = None
        best_dist = float("inf")
        for b in self.buildings_list:
            if isinstance(b, TownCenter) and b.hp > 0:
                cx, cy = b.x + b.w // 2, b.y + b.h // 2
                d = math.hypot(self.x - cx, self.y - cy)
                if d < best_dist:
                    best_dist = d
                    best = b
        return best

    def assign_to_mine(self, node, buildings_list, resource_manager):
        self.assigned_node = node
        self.buildings_list = buildings_list
        self.drop_off_building = None
        self.resource_manager = resource_manager
        self.state = "moving_to_mine"
        self.carry_amount = 0
        self.mine_timer = 0.0
        self.waypoints = [(node.x, node.y)]

    def cancel_mining(self):
        # Release node if we were the one mining it
        if self.assigned_node and self.assigned_node.mining_worker is self:
            self.assigned_node.mining_worker = None
        self.state = "idle"
        self.assigned_node = None
        self.drop_off_building = None
        self.buildings_list = None
        self.carry_amount = 0
        self.mine_timer = 0.0

    def assign_to_deploy(self, building_class, target_pos, cost):
        """Send worker to deploy a building at target position."""
        self.cancel_mining()
        self.state = "deploying"
        self.deploy_building_class = building_class
        self.deploy_target = target_pos
        self.deploy_cost = cost
        self.deploy_build_timer = 0.0
        self.deploy_building = False
        self.waypoints = [target_pos]

    def cancel_deploy(self):
        """Cancel deployment. Returns the cost to refund, or 0."""
        if self.state != "deploying":
            return 0
        cost = self.deploy_cost
        self.state = "idle"
        self.deploy_building_class = None
        self.deploy_target = None
        self.deploy_cost = 0
        self.deploy_build_timer = 0.0
        self.deploy_building = False
        return cost

    def assign_to_repair(self, target):
        """Send worker to repair a damaged unit or building."""
        self.cancel_mining()
        self.cancel_deploy()
        self.cancel_repair()
        self.repair_target = target
        self.state = "repairing"
        if hasattr(target, 'size'):
            # Unit target
            self.waypoints = [(target.x, target.y)]
        else:
            # Building target
            cx, cy = target.x + target.w // 2, target.y + target.h // 2
            self.waypoints = [(cx, cy)]

    def cancel_repair(self):
        if self.state != "repairing":
            return
        self.state = "idle"
        self.repair_target = None

    def set_target(self, pos):
        self.cancel_mining()
        self.cancel_deploy()
        self.cancel_repair()
        self.waypoints = [pos]

    def add_waypoint(self, pos):
        if self.state not in ("idle", "deploying", "repairing"):
            self.cancel_mining()
        if self.state == "deploying":
            self.cancel_deploy()
        if self.state == "repairing":
            self.cancel_repair()
        self.waypoints.append(pos)

    def update(self, dt):
        if self.state == "idle":
            super().update(dt)
            return
        # For non-idle states, do movement + state logic together
        if self.state in ("moving_to_mine", "returning"):
            super().update(dt)
        self.update_state(dt)

    def _ensure_drop_off_building(self):
        """Ensure drop_off_building is alive, or find the closest TC."""
        if self.drop_off_building and self.drop_off_building.hp > 0:
            return True
        self.drop_off_building = self._find_closest_town_center()
        return self.drop_off_building is not None

    def update_state(self, dt):
        """Run the worker state machine.

        States: idle -> moving_to_mine -> waiting -> mining -> returning -> (loop)
                idle -> deploying (building construction)
                idle -> repairing (unit/building repair)
        Called by GameState after movement is handled via collision avoidance.
        """
        if self.state == "moving_to_mine":
            # Check if any town center exists to deliver to
            if not self._ensure_drop_off_building():
                self.cancel_mining()
                return
            # Check if close enough to the node (arrival or blocked nearby)
            if not self.assigned_node or self.assigned_node.depleted:
                self.cancel_mining()
                return
            dx = self.x - self.assigned_node.x
            dy = self.y - self.assigned_node.y
            near_node = (dx * dx + dy * dy) < (self.size + MINERAL_NODE_SIZE + 4) ** 2
            arrived = not self.waypoints or near_node
            if arrived:
                self.waypoints.clear()
                if self.assigned_node.mining_worker is None:
                    self.assigned_node.mining_worker = self
                    self.state = "mining"
                    self.mine_timer = 0.0
                else:
                    self.state = "waiting"

        elif self.state == "waiting":
            if not self._ensure_drop_off_building():
                self.cancel_mining()
                return
            if not self.assigned_node or self.assigned_node.depleted:
                self.cancel_mining()
            elif self.assigned_node.mining_worker is None:
                # Node freed up — claim it and start mining
                self.assigned_node.mining_worker = self
                self.state = "mining"
                self.mine_timer = 0.0
            elif not self.assigned_node.mining_worker.alive:
                # Mining worker died — release the node and claim it
                self.assigned_node.mining_worker = self
                self.state = "mining"
                self.mine_timer = 0.0

        elif self.state == "mining":
            # Check if any town center exists to deliver to
            if not self._ensure_drop_off_building():
                if self.assigned_node and self.assigned_node.mining_worker is self:
                    self.assigned_node.mining_worker = None
                self.cancel_mining()
                return
            self.mine_timer += dt
            if self.mine_timer >= WORKER_MINE_TIME:
                self.carry_amount = self.assigned_node.mine(WORKER_CARRY_CAPACITY)
                # Release the node
                self.assigned_node.mining_worker = None
                if self.carry_amount <= 0:
                    self.cancel_mining()
                    return
                # Find the closest town center for delivery
                self.drop_off_building = self._find_closest_town_center()
                if not self.drop_off_building:
                    self.cancel_mining()
                    return
                self.state = "returning"
                bld = self.drop_off_building
                # Target the nearest edge of the building, not the center
                cx, cy = bld.x + bld.w // 2, bld.y + bld.h // 2
                # Clamp worker position to building rect to find closest edge point
                edge_x = max(bld.x, min(self.x, bld.x + bld.w))
                edge_y = max(bld.y, min(self.y, bld.y + bld.h))
                # If worker is inside building rect, use the center bottom
                if edge_x == self.x and edge_y == self.y:
                    edge_x, edge_y = cx, bld.y + bld.h
                self.waypoints = [(edge_x, edge_y)]

        elif self.state == "returning":
            # Check if drop-off building was destroyed — try to find another TC
            bld = self.drop_off_building
            if not bld or bld.hp <= 0:
                self.drop_off_building = self._find_closest_town_center()
                bld = self.drop_off_building
                if not bld:
                    self.cancel_mining()
                    return
                # Redirect to the new TC
                cx, cy = bld.x + bld.w // 2, bld.y + bld.h // 2
                edge_x = max(bld.x, min(self.x, bld.x + bld.w))
                edge_y = max(bld.y, min(self.y, bld.y + bld.h))
                if edge_x == self.x and edge_y == self.y:
                    edge_x, edge_y = cx, bld.y + bld.h
                self.waypoints = [(edge_x, edge_y)]
            bld_rect = bld.rect.inflate(self.size * 2, self.size * 2)
            near_building = bld_rect.collidepoint(int(self.x), int(self.y))
            if near_building or not self.waypoints:
                self.waypoints.clear()
                if self.resource_manager and self.carry_amount > 0:
                    self.resource_manager.deposit(self.carry_amount)
                    self.carry_amount = 0
                if self.assigned_node and not self.assigned_node.depleted:
                    self.state = "moving_to_mine"
                    self.waypoints = [(self.assigned_node.x, self.assigned_node.y)]
                else:
                    self.cancel_mining()

        elif self.state == "repairing":
            target = self.repair_target
            # Check target still valid
            if target is None:
                self.cancel_repair()
                return
            target_alive = target.alive if hasattr(target, 'alive') else target.hp > 0
            if not target_alive:
                self.cancel_repair()
                return
            target_max = target.max_hp if hasattr(target, 'max_hp') else getattr(target, 'max_hp', target.hp)
            if target.hp >= target_max:
                self.cancel_repair()
                return
            # Get target position
            if hasattr(target, 'size'):
                tx, ty = target.x, target.y
            else:
                tx, ty = target.x + target.w // 2, target.y + target.h // 2
            dist = math.hypot(self.x - tx, self.y - ty)
            repair_range = self.size + (target.size if hasattr(target, 'size') else max(target.w, target.h) // 2) + 10
            if dist <= repair_range:
                # In range — repair
                self.waypoints.clear()
                heal = self.repair_rate * dt
                target.hp = min(target_max, target.hp + heal)
                if target.hp >= target_max:
                    self.cancel_repair()
            else:
                # Move toward target (update waypoint to track moving units)
                self.waypoints = [(tx, ty)]

    def draw(self, surface):
        super().draw(surface)
        # Draw carry indicator
        if self.carry_amount > 0:
            pygame.draw.circle(surface, (255, 215, 0),
                               (int(self.x + self.size), int(self.y - self.size)),
                               4)
        # Draw state indicator
        if self.selected and self.state != "idle":
            from utils import get_font
            state_text = self.state.replace("_", " ")
            label = get_font(14).render(state_text, True, (200, 200, 200))
            surface.blit(label, (self.x - self.size, self.y + self.size + 2))


class Yanuses(Unit):
    """Enemy soldier-like unit that spawns from the bottom of the map."""
    name = "Yanuses"
    sprite = None

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(YANUSES_SPRITE, (YANUSES_SIZE * 2, YANUSES_SIZE * 2))

    def __init__(self, x, y):
        super().__init__(x, y, YANUSES_HP, YANUSES_SPEED, YANUSES_SIZE,
                         team="enemy", fire_rate=YANUSES_FIRE_RATE,
                         damage=YANUSES_DAMAGE, attack_range=YANUSES_RANGE)
        self.move_target = None  # where the AI wants to go

    def ai_update(self, dt, player_units, buildings):
        """Enemy AI: attack nearest target in range, or walk toward nearest target."""
        # If currently attacking, keep firing
        if self.attacking and self.target_enemy:
            # Check target still alive and in range
            if hasattr(self.target_enemy, 'alive'):
                target_alive = self.target_enemy.alive
            else:
                target_alive = self.target_enemy.hp > 0
            if target_alive:
                tx = self.target_enemy.x if hasattr(self.target_enemy, 'x') else self.target_enemy.x + self.target_enemy.w // 2
                ty = self.target_enemy.y if hasattr(self.target_enemy, 'size') else self.target_enemy.y + self.target_enemy.h // 2
                dist = self.distance_to(tx, ty)
                if dist <= self.attack_range:
                    self.try_attack(dt)
                    return
            # Target dead or out of range
            self.target_enemy = None
            self.attacking = False

        # Find a target to attack
        target = self.find_target(player_units, buildings)
        if target:
            self.target_enemy = target
            self.attacking = True
            self.waypoints = []
            self.fire_cooldown = 0.0
            self.try_attack(dt)
            return

        # No target in range — move toward nearest player entity
        best = None
        best_dist = float("inf")
        for u in player_units:
            if u.alive:
                d = self.distance_to(u.x, u.y)
                if d < best_dist:
                    best_dist = d
                    best = (u.x, u.y)
        for b in buildings:
            if b.hp > 0:
                bx, by = b.x + b.w // 2, b.y + b.h // 2
                d = self.distance_to(bx, by)
                if d < best_dist:
                    best_dist = d
                    best = (bx, by)
        if best and (not self.waypoints or self.move_target != best):
            self.move_target = best
            self.waypoints = [best]

    def draw(self, surface):
        if self.sprite:
            r = self.sprite.get_rect(center=(int(self.x), int(self.y)))
            surface.blit(self.sprite, r)
        else:
            # Fallback: red circle
            pygame.draw.circle(surface, (200, 50, 50), (int(self.x), int(self.y)), self.size)
        self._draw_health_bar(surface)
