import math
import pygame
from settings import (
    SOLDIER_HP, SOLDIER_SPEED, SOLDIER_SIZE,
    SOLDIER_FIRE_RATE, SOLDIER_DAMAGE, SOLDIER_RANGE,
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
        # Stuck detection
        self.stuck = False
        self.stuck_timer = 0.0
        self._last_x = float(x)
        self._last_y = float(y)

    @property
    def alive(self):
        return self.hp > 0

    def set_target(self, pos):
        self.target_enemy = None
        self.attacking = False
        self.stuck = False
        self.stuck_timer = 0.0
        self.waypoints = [pos]

    def add_waypoint(self, pos):
        self.target_enemy = None
        self.attacking = False
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
        bar_w = self.size * 2
        bar_h = 3
        bx = self.x - self.size
        by = self.y - self.size - 6
        pygame.draw.rect(surface, HEALTH_BAR_BG, (bx, by, bar_w, bar_h))
        fill_w = int(bar_w * (self.hp / self.max_hp))
        hp_ratio = self.hp / self.max_hp
        if hp_ratio > 0.5:
            bar_color = (0, 200, 0)
        elif hp_ratio > 0.25:
            bar_color = (255, 200, 0)
        else:
            bar_color = (255, 50, 50)
        pygame.draw.rect(surface, bar_color, (bx, by, fill_w, bar_h))


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
        cls.sprite = _load_sprite(WORKER_SPRITE, (WORKER_SIZE * 2, WORKER_SIZE * 2))

    def __init__(self, x, y):
        super().__init__(x, y, WORKER_HP, WORKER_SPEED, WORKER_SIZE)
        self.state = "idle"  # "idle" | "moving_to_mine" | "waiting" | "mining" | "returning"
        self.assigned_node = None
        self.drop_off_building = None
        self.carry_amount = 0
        self.mine_timer = 0.0
        self.resource_manager = None

    def assign_to_mine(self, node, drop_off_building, resource_manager):
        self.assigned_node = node
        self.drop_off_building = drop_off_building
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
        self.carry_amount = 0
        self.mine_timer = 0.0

    def set_target(self, pos):
        self.cancel_mining()
        self.waypoints = [pos]

    def add_waypoint(self, pos):
        if self.state != "idle":
            self.cancel_mining()
        self.waypoints.append(pos)

    def update(self, dt):
        if self.state == "idle":
            super().update(dt)
            return
        # For non-idle states, do movement + state logic together
        if self.state in ("moving_to_mine", "returning"):
            super().update(dt)
        self.update_state(dt)

    def update_state(self, dt):
        """Run mining state transitions (called by game_state when movement is handled externally)."""
        if self.state == "moving_to_mine":
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
            if not self.assigned_node or self.assigned_node.depleted:
                self.cancel_mining()
            elif self.assigned_node.mining_worker is None:
                # Node freed up — claim it and start mining
                self.assigned_node.mining_worker = self
                self.state = "mining"
                self.mine_timer = 0.0

        elif self.state == "mining":
            self.mine_timer += dt
            if self.mine_timer >= WORKER_MINE_TIME:
                self.carry_amount = self.assigned_node.mine(WORKER_CARRY_CAPACITY)
                # Release the node
                self.assigned_node.mining_worker = None
                if self.carry_amount <= 0:
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
            # Deposit when close to the building edge
            bld = self.drop_off_building
            if bld:
                bld_rect = bld.rect.inflate(self.size * 2, self.size * 2)
                near_building = bld_rect.collidepoint(int(self.x), int(self.y))
            else:
                near_building = not self.waypoints
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

    def draw(self, surface):
        super().draw(surface)
        # Draw carry indicator
        if self.carry_amount > 0:
            pygame.draw.circle(surface, (255, 215, 0),
                               (int(self.x + self.size), int(self.y - self.size)),
                               4)
        # Draw state indicator
        if self.selected and self.state != "idle":
            font = pygame.font.SysFont(None, 14)
            state_text = self.state.replace("_", " ")
            label = font.render(state_text, True, (200, 200, 200))
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
