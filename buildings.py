import pygame
from settings import (
    BARRACKS_SIZE, FACTORY_SIZE, TOWN_CENTER_SIZE,
    SOLDIER_COST, SOLDIER_TRAIN_TIME,
    TANK_COST, TANK_TRAIN_TIME,
    WORKER_COST, WORKER_TRAIN_TIME,
    SELECT_COLOR, HEALTH_BAR_BG, HEALTH_BAR_FG,
    BARRACKS_SPRITE, FACTORY_SPRITE, TOWN_CENTER_SPRITE,
)
from units import Soldier, Tank, Worker


def _load_sprite(path, size):
    img = pygame.image.load(path).convert_alpha()
    return pygame.transform.smoothscale(img, size)


class Building:
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
        bar_w = self.w
        bar_h = 4
        bx, by = self.x, self.y - 8
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
        # Label
        font = pygame.font.SysFont(None, 18)
        label = font.render(self.label, True, (255, 255, 255))
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

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(TOWN_CENTER_SPRITE, TOWN_CENTER_SIZE)

    def __init__(self, x, y):
        super().__init__(x, y, TOWN_CENTER_SIZE)

    def can_train(self):
        return (Worker, WORKER_COST, WORKER_TRAIN_TIME)


class Barracks(Building):
    label = "Barracks"
    sprite = None

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(BARRACKS_SPRITE, BARRACKS_SIZE)

    def __init__(self, x, y):
        super().__init__(x, y, BARRACKS_SIZE)

    def can_train(self):
        return (Soldier, SOLDIER_COST, SOLDIER_TRAIN_TIME)


class Factory(Building):
    label = "Factory"
    sprite = None

    @classmethod
    def load_assets(cls):
        cls.sprite = _load_sprite(FACTORY_SPRITE, FACTORY_SIZE)

    def __init__(self, x, y):
        super().__init__(x, y, FACTORY_SIZE)

    def can_train(self):
        return (Tank, TANK_COST, TANK_TRAIN_TIME)
