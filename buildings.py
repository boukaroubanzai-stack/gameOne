"""Building entities: TownCenter, Barracks, Factory, DefenseTower, Watchguard, Radar."""

import math
import os
import pygame
from settings import (
    BARRACKS_SIZE, FACTORY_SIZE, TOWN_CENTER_SIZE,
    BARRACKS_HP, FACTORY_HP, TOWN_CENTER_HP,
    BARRACKS_BUILD_TIME, FACTORY_BUILD_TIME, TOWN_CENTER_BUILD_TIME,
    SOLDIER_COST, SOLDIER_TRAIN_TIME,
    TANK_COST, TANK_TRAIN_TIME,
    WORKER_COST, WORKER_TRAIN_TIME,
    SELECT_COLOR, HEALTH_BAR_BG, HEALTH_BAR_FG,
    BARRACKS_SPRITE, FACTORY_SPRITE, TOWN_CENTER_SPRITE,
    TOWER_SIZE, TOWER_HP, TOWER_FIRE_RATE, TOWER_DAMAGE, TOWER_RANGE, TOWER_SPRITE, TOWER_BUILD_TIME,
    WATCHGUARD_SIZE, WATCHGUARD_HP, WATCHGUARD_ZONE_RADIUS, WATCHGUARD_BUILD_TIME, WATCHGUARD_SPRITE,
    RADAR_SIZE, RADAR_HP, RADAR_BUILD_TIME, RADAR_VISION, RADAR_SPRITE,
)
from units import Soldier, Tank, Worker


def _load_sprite(path, size):
    img = pygame.image.load(path).convert_alpha()
    return pygame.transform.smoothscale(img, size)


class Building:
    """Base class for all buildings. Handles HP, selection, production queue, and drawing."""
    sprite = None

    def __init__(self, x, y, size, hp=200):
        self.x = x
        self.y = y
        self.w, self.h = size
        self.hp = hp
        self.max_hp = hp
        self.selected = False
        self.production_queue = []
        self.production_timer = 0.0
        self.rally_x = x + self.w // 2
        self.rally_y = y + self.h + 30
        self.net_id = None  # multiplayer entity ID

    @property
    def rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h)

    @property
    def center(self):
        return (self.x + self.w // 2, self.y + self.h // 2)

    def can_train(self):
        raise NotImplementedError

    def start_production(self, resource_mgr):
        unit_class, cost, train_time = self.can_train()
        if resource_mgr.spend(cost):
            self.production_queue.append((unit_class, train_time))
            return True
        return False

    def update(self, dt):
        if not self.production_queue:
            self.production_timer = 0.0
            return None

        self.production_timer += dt
        unit_class, train_time = self.production_queue[0]

        if self.production_timer >= train_time:
            self.production_queue.pop(0)
            self.production_timer = 0.0
            return unit_class(self.rally_x, self.rally_y)
        return None

    @property
    def production_progress(self):
        if not self.production_queue:
            return 0.0
        _, train_time = self.production_queue[0]
        return min(self.production_timer / train_time, 1.0)

    def draw(self, surface):
        if self.sprite:
            surface.blit(self.sprite, (self.x, self.y))
        if self.selected:
            pygame.draw.rect(surface, SELECT_COLOR, self.rect.inflate(6, 6), 2)
        # Health bar (color-coded)
        from utils import hp_bar_color, get_font
        bar_w = self.w
        bar_h = 4
        bx, by = self.x, self.y - 8
        pygame.draw.rect(surface, HEALTH_BAR_BG, (bx, by, bar_w, bar_h))
        ratio = self.hp / self.max_hp
        fill_w = int(bar_w * ratio)
        pygame.draw.rect(surface, hp_bar_color(ratio), (bx, by, fill_w, bar_h))
        # Label
        label = get_font(18).render(self.label, True, (255, 255, 255))
        label_rect = label.get_rect(center=(self.x + self.w // 2, self.y - 16))
        surface.blit(label, label_rect)
        # Production bar
        if self.production_queue:
            prog_y = self.y + self.h + 2
            pygame.draw.rect(surface, (60, 60, 60), (self.x, prog_y, self.w, 4))
            pygame.draw.rect(surface, (0, 180, 255),
                             (self.x, prog_y, int(self.w * self.production_progress), 4))


class TownCenter(Building):
    label = "Town Center"
    sprite = None
    build_time = TOWN_CENTER_BUILD_TIME

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(TOWN_CENTER_SPRITE, TOWN_CENTER_SIZE)

    def __init__(self, x, y):
        super().__init__(x, y, TOWN_CENTER_SIZE, hp=TOWN_CENTER_HP)

    def can_train(self):
        return (Worker, WORKER_COST, WORKER_TRAIN_TIME)


class Barracks(Building):
    label = "Barracks"
    sprite = None
    build_time = BARRACKS_BUILD_TIME

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(BARRACKS_SPRITE, BARRACKS_SIZE)

    def __init__(self, x, y):
        super().__init__(x, y, BARRACKS_SIZE, hp=BARRACKS_HP)

    def can_train(self):
        return (Soldier, SOLDIER_COST, SOLDIER_TRAIN_TIME)


class Factory(Building):
    label = "Factory"
    sprite = None
    build_time = FACTORY_BUILD_TIME

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(FACTORY_SPRITE, FACTORY_SIZE)

    def __init__(self, x, y):
        super().__init__(x, y, FACTORY_SIZE, hp=FACTORY_HP)

    def can_train(self):
        return (Tank, TANK_COST, TANK_TRAIN_TIME)


class DefenseTower(Building):
    label = "Tower"
    sprite = None
    build_time = TOWER_BUILD_TIME

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(TOWER_SPRITE, TOWER_SIZE)

    def __init__(self, x, y):
        super().__init__(x, y, TOWER_SIZE, hp=TOWER_HP)
        # Combat attributes
        self.fire_rate = TOWER_FIRE_RATE
        self.damage = TOWER_DAMAGE
        self.attack_range = TOWER_RANGE
        self.fire_cooldown = 0.0
        self.target_enemy = None
        self.attacking = False

    def can_train(self):
        # Tower does not train units; return a dummy to prevent crashes
        return (Worker, 0, 0)

    def start_production(self, resource_mgr):
        # Tower cannot produce units
        return False

    def find_target(self, enemies):
        """Find the closest enemy in range."""
        best = None
        best_dist = float("inf")
        cx, cy = self.center
        for enemy in enemies:
            if not enemy.alive:
                continue
            dist = math.hypot(cx - enemy.x, cy - enemy.y)
            if dist <= self.attack_range and dist < best_dist:
                best_dist = dist
                best = enemy
        return best

    def try_attack(self, dt):
        """Fire at target if cooldown allows."""
        if not self.target_enemy or self.fire_rate <= 0:
            return False
        self.fire_cooldown -= dt
        if self.fire_cooldown <= 0:
            self.target_enemy.hp -= self.damage
            self.fire_cooldown = 1.0 / self.fire_rate
            return True
        return False

    def combat_update(self, dt, enemies):
        """Called each frame to find targets and fire."""
        # Check if current target is still valid
        if self.target_enemy:
            alive = self.target_enemy.alive if hasattr(self.target_enemy, 'alive') else self.target_enemy.hp > 0
            if alive:
                cx, cy = self.center
                dist = math.hypot(cx - self.target_enemy.x, cy - self.target_enemy.y)
                if dist <= self.attack_range:
                    self.attacking = True
                    self.try_attack(dt)
                    return
            # Target dead or out of range
            self.target_enemy = None
            self.attacking = False

        # Find new target
        target = self.find_target(enemies)
        if target:
            self.target_enemy = target
            self.attacking = True
            self.fire_cooldown = 0.0
            self.try_attack(dt)
        else:
            self.attacking = False

    def update(self, dt):
        """Override: tower has no production, combat is handled by combat_update."""
        # No production logic needed
        pass

    def draw(self, surface):
        cx, cy = self.center
        if self.sprite:
            surface.blit(self.sprite, (self.x, self.y))
        else:
            # Fallback: grey square base
            pygame.draw.rect(surface, (120, 120, 130), (self.x, self.y, self.w, self.h))
            pygame.draw.rect(surface, (80, 80, 90), (self.x, self.y, self.w, self.h), 2)
            # Cannon barrel: line from center pointing toward target or upward
            if self.attacking and self.target_enemy:
                tx = self.target_enemy.x
                ty = self.target_enemy.y
                angle = math.atan2(ty - cy, tx - cx)
            else:
                angle = -math.pi / 2  # default: point up
            barrel_len = 20
            bx = cx + math.cos(angle) * barrel_len
            by = cy + math.sin(angle) * barrel_len
            pygame.draw.line(surface, (60, 60, 70), (cx, cy), (int(bx), int(by)), 4)
            # Small circle at cannon base
            pygame.draw.circle(surface, (90, 90, 100), (cx, cy), 6)

        # Selection highlight
        if self.selected:
            pygame.draw.rect(surface, SELECT_COLOR, self.rect.inflate(6, 6), 2)
            # Range circle when selected
            pygame.draw.circle(surface, (100, 100, 140, 80), (cx, cy), self.attack_range, 1)

        # Health bar
        from utils import hp_bar_color, get_font
        bar_w = self.w
        bar_h = 4
        bx_bar, by_bar = self.x, self.y - 8
        pygame.draw.rect(surface, HEALTH_BAR_BG, (bx_bar, by_bar, bar_w, bar_h))
        ratio = self.hp / self.max_hp
        fill_w = int(bar_w * ratio)
        pygame.draw.rect(surface, hp_bar_color(ratio), (bx_bar, by_bar, fill_w, bar_h))

        # Label
        label = get_font(18).render(self.label, True, (255, 255, 255))
        label_rect = label.get_rect(center=(cx, self.y - 16))
        surface.blit(label, label_rect)

        # Attack line when firing
        if self.attacking and self.target_enemy:
            target = self.target_enemy
            tx = target.x if hasattr(target, 'x') else target.x + target.w // 2
            ty = target.y if hasattr(target, 'size') else target.y + target.h // 2
            pygame.draw.line(surface, (255, 200, 50), (cx, cy), (int(tx), int(ty)), 2)


class Watchguard(Building):
    """Expands the building zone by 500px. Consumes the worker that builds it."""
    label = "Watchguard"
    sprite = None
    build_time = WATCHGUARD_BUILD_TIME
    zone_radius = WATCHGUARD_ZONE_RADIUS

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(WATCHGUARD_SPRITE, WATCHGUARD_SIZE)

    def __init__(self, x, y):
        super().__init__(x, y, WATCHGUARD_SIZE, hp=WATCHGUARD_HP)

    def can_train(self):
        return (Worker, 0, 0)

    def start_production(self, resource_mgr):
        return False

    def update(self, dt):
        pass


class Radar(Building):
    """Provides 5000px vision range. Removes fog of war from the minimap."""
    label = "Radar"
    sprite = None
    build_time = RADAR_BUILD_TIME
    vision_range = RADAR_VISION

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(RADAR_SPRITE, RADAR_SIZE)

    def __init__(self, x, y):
        super().__init__(x, y, RADAR_SIZE, hp=RADAR_HP)

    def can_train(self):
        return (Worker, 0, 0)

    def start_production(self, resource_mgr):
        return False

    def update(self, dt):
        pass

    def draw(self, surface):
        super().draw(surface)
        if self.selected:
            cx, cy = self.center
            pygame.draw.circle(surface, (100, 140, 100, 80), (cx, cy), self.vision_range, 1)
