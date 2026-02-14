"""Particle effects: death explosions, damage numbers, and visual feedback."""

import math
import random
import pygame
from utils import get_font

# LRU-style cache for fading particle surfaces keyed by (size, color, alpha)
_particle_cache: dict[tuple, pygame.Surface] = {}
_PARTICLE_CACHE_MAX = 512


class Particle:
    """A single particle that moves, shrinks, and fades over its lifetime."""
    __slots__ = ('x', 'y', 'vx', 'vy', 'lifetime', 'max_lifetime', 'color', 'size')

    def __init__(self, x, y, vx, vy, lifetime, color, size):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.lifetime = lifetime
        self.max_lifetime = lifetime
        self.color = color
        self.size = size

    @property
    def alive(self):
        return self.lifetime > 0


class DamageNumber:
    """Floating damage text that rises and fades out."""
    __slots__ = ('x', 'y', 'text', 'color', 'timer', 'duration')

    def __init__(self, x, y, amount, color=(255, 80, 80)):
        self.x = x
        self.y = y
        self.text = str(amount)
        self.color = color
        self.timer = 0.0
        self.duration = 0.8

    @property
    def alive(self):
        return self.timer < self.duration


class ParticleManager:
    """Manages all particle effects and damage numbers."""

    def __init__(self):
        self.particles = []
        self.damage_numbers = []

    def spawn_death(self, x, y, team):
        """Spawn death particles for a unit. Color based on team."""
        if team == "player":
            base_colors = [(100, 200, 100), (60, 160, 60), (80, 255, 80)]
        elif team == "ai":
            base_colors = [(255, 160, 60), (255, 120, 40), (200, 100, 30)]
        else:  # enemy
            base_colors = [(200, 60, 60), (255, 80, 80), (180, 40, 40)]
        count = random.randint(8, 12)
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(40, 120)
            vx = math.cos(angle) * speed
            vy = math.sin(angle) * speed
            lifetime = random.uniform(0.4, 0.8)
            color = random.choice(base_colors)
            size = random.uniform(2, 4)
            self.particles.append(Particle(x, y, vx, vy, lifetime, color, size))

    def spawn_building_death(self, x, y):
        """Spawn larger explosion particles for a destroyed building."""
        colors = [(255, 100, 20), (255, 160, 40), (255, 60, 20),
                  (200, 200, 200), (180, 180, 180)]
        count = random.randint(15, 20)
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(30, 150)
            vx = math.cos(angle) * speed
            vy = math.sin(angle) * speed
            lifetime = random.uniform(0.6, 1.2)
            color = random.choice(colors)
            size = random.uniform(3, 6)
            self.particles.append(Particle(x, y, vx, vy, lifetime, color, size))

    def spawn_damage_number(self, x, y, amount, color=(255, 80, 80)):
        """Spawn a floating damage number."""
        # Slight random x offset to avoid stacking
        ox = random.uniform(-10, 10)
        self.damage_numbers.append(DamageNumber(x + ox, y - 15, amount, color))

    def update(self, dt):
        """Update all particles and damage numbers, remove expired ones."""
        for p in self.particles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vy += 80 * dt  # gravity
            p.lifetime -= dt

        self.particles = [p for p in self.particles if p.alive]

        for dn in self.damage_numbers:
            dn.timer += dt
            dn.y -= 40 * dt

        self.damage_numbers = [dn for dn in self.damage_numbers if dn.alive]

    def draw(self, surface, cam_x, cam_y):
        """Draw all particles and damage numbers with camera offset."""
        for p in self.particles:
            sx = int(p.x - cam_x)
            sy = int(p.y - cam_y)
            ratio = p.lifetime / p.max_lifetime
            cur_size = max(1, int(p.size * ratio))
            if ratio >= 0.95:
                # Full alpha — draw directly onto surface (no allocation)
                pygame.draw.circle(surface, p.color, (sx, sy), cur_size)
            else:
                # Fading — need alpha surface; use cache by (size, color, alpha)
                alpha = int(255 * ratio)
                key = (cur_size, p.color, alpha)
                cached = _particle_cache.get(key)
                if cached is None:
                    diameter = cur_size * 2
                    cached = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
                    if cur_size <= 2:
                        cached.fill((*p.color, alpha))
                    else:
                        pygame.draw.circle(cached, (*p.color, alpha), (cur_size, cur_size), cur_size)
                    if len(_particle_cache) < _PARTICLE_CACHE_MAX:
                        _particle_cache[key] = cached
                surface.blit(cached, (sx - cur_size, sy - cur_size))

        for dn in self.damage_numbers:
            sx = int(dn.x - cam_x)
            sy = int(dn.y - cam_y)
            progress = dn.timer / dn.duration
            alpha = int(255 * (1 - progress))
            text_surf = get_font(20).render(dn.text, True, dn.color)
            text_surf.set_alpha(alpha)
            surface.blit(text_surf, (sx - text_surf.get_width() // 2, sy))
