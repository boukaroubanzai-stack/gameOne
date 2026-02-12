"""Shared rendering utilities: font cache, surface tinting, HP bar colors, range circles."""

import pygame


# ---------------------------------------------------------------------------
# Font cache — avoids recreating pygame.font.SysFont every frame.
# ---------------------------------------------------------------------------
_font_cache: dict[int, pygame.font.Font] = {}


def get_font(size: int) -> pygame.font.Font:
    """Return a cached SysFont of the given *size*. Created on first use."""
    font = _font_cache.get(size)
    if font is None:
        font = pygame.font.SysFont(None, size)
        _font_cache[size] = font
    return font


# ---------------------------------------------------------------------------
# Surface tinting — used to distinguish AI/remote entities (orange overlay).
# ---------------------------------------------------------------------------

def tint_surface(surface: pygame.Surface, tint_color: tuple) -> pygame.Surface:
    """Return a copy of *surface* with a colour-multiply tint and orange overlay."""
    tinted = surface.copy()
    overlay = pygame.Surface(tinted.get_size(), pygame.SRCALPHA)
    overlay.fill(tint_color)
    tinted.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    orange_overlay = pygame.Surface(tinted.get_size(), pygame.SRCALPHA)
    orange_overlay.fill((255, 120, 40, 100))
    tinted.blit(orange_overlay, (0, 0))
    return tinted


# ---------------------------------------------------------------------------
# HP bar colour helper — green / yellow / red based on health ratio.
# ---------------------------------------------------------------------------

def hp_bar_color(ratio: float) -> tuple[int, int, int]:
    """Return (R, G, B) colour for a health bar given *ratio* (0.0 – 1.0)."""
    if ratio > 0.5:
        return (0, 200, 0)
    elif ratio > 0.25:
        return (255, 200, 0)
    return (255, 50, 50)


# ---------------------------------------------------------------------------
# Range circle cache — avoids recreating SRCALPHA surfaces every frame.
# ---------------------------------------------------------------------------
_range_circle_cache: dict[int, pygame.Surface] = {}


def get_range_circle(radius: int) -> pygame.Surface:
    """Return a cached semi-transparent range-circle surface of the given *radius*."""
    surf = _range_circle_cache.get(radius)
    if surf is None:
        diameter = radius * 2
        surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        pygame.draw.circle(surf, (100, 100, 140, 80), (radius, radius), radius, 1)
        _range_circle_cache[radius] = surf
    return surf
