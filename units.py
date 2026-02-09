import math
import pygame
from settings import (
    SOLDIER_HP, SOLDIER_SPEED, SOLDIER_SIZE,
    TANK_HP, TANK_SPEED, TANK_SIZE,
    WORKER_HP, WORKER_SPEED, WORKER_SIZE,
    WORKER_CARRY_CAPACITY, WORKER_MINE_TIME,
    SELECT_COLOR, HEALTH_BAR_BG, HEALTH_BAR_FG,
    SOLDIER_SPRITE, TANK_SPRITE, WORKER_SPRITE,
)


def _load_sprite(path, size):
    img = pygame.image.load(path).convert_alpha()
    return pygame.transform.smoothscale(img, size)


class Unit:
    sprite = None

    def __init__(self, x, y, hp, speed, size):
        self.x = float(x)
        self.y = float(y)
        self.hp = hp
        self.max_hp = hp
        self.speed = speed
        self.size = size
        self.selected = False
        self.waypoints = []

    def set_target(self, pos):
        self.waypoints = [pos]

    def add_waypoint(self, pos):
        self.waypoints.append(pos)

    def update(self, dt):
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
        pygame.draw.rect(surface, HEALTH_BAR_FG, (bx, by, fill_w, bar_h))


class Soldier(Unit):
    name = "Soldier"
    sprite = None

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(SOLDIER_SPRITE, (SOLDIER_SIZE * 2, SOLDIER_SIZE * 2))

    def __init__(self, x, y):
        super().__init__(x, y, SOLDIER_HP, SOLDIER_SPEED, SOLDIER_SIZE)


class Tank(Unit):
    name = "Tank"
    sprite = None

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(TANK_SPRITE, (TANK_SIZE * 2, TANK_SIZE * 2))

    def __init__(self, x, y):
        super().__init__(x, y, TANK_HP, TANK_SPEED, TANK_SIZE)


class Worker(Unit):
    name = "Worker"
    sprite = None

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(WORKER_SPRITE, (WORKER_SIZE * 2, WORKER_SIZE * 2))

    def __init__(self, x, y):
        super().__init__(x, y, WORKER_HP, WORKER_SPEED, WORKER_SIZE)
        self.state = "idle"  # "idle" | "moving_to_mine" | "mining" | "returning"
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
            # Normal movement
            super().update(dt)
            return

        if self.state == "moving_to_mine":
            super().update(dt)
            if not self.waypoints:
                # Arrived at node
                if self.assigned_node and not self.assigned_node.depleted:
                    self.state = "mining"
                    self.mine_timer = 0.0
                else:
                    self.cancel_mining()
            return

        if self.state == "mining":
            self.mine_timer += dt
            if self.mine_timer >= WORKER_MINE_TIME:
                # Done mining, pick up resources
                self.carry_amount = self.assigned_node.mine(WORKER_CARRY_CAPACITY)
                if self.carry_amount <= 0:
                    self.cancel_mining()
                    return
                # Head back to drop-off
                self.state = "returning"
                bld = self.drop_off_building
                self.waypoints = [(bld.x + bld.w // 2, bld.y + bld.h // 2)]
            return

        if self.state == "returning":
            super().update(dt)
            if not self.waypoints:
                # Arrived at drop-off, deposit
                if self.resource_manager and self.carry_amount > 0:
                    self.resource_manager.deposit(self.carry_amount)
                    self.carry_amount = 0
                # Go back to mine if node still has resources
                if self.assigned_node and not self.assigned_node.depleted:
                    self.state = "moving_to_mine"
                    self.waypoints = [(self.assigned_node.x, self.assigned_node.y)]
                else:
                    self.cancel_mining()
            return

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
