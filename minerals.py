import pygame
from settings import MINERAL_NODE_AMOUNT, MINERAL_NODE_SIZE, MINERAL_NODE_COLOR


# Fixed positions for 5 mineral nodes, spread across the map
MINERAL_POSITIONS = [
    (200, 100),
    (800, 80),
    (500, 300),
    (150, 500),
    (850, 450),
]


class MineralNode:
    def __init__(self, x, y, amount=MINERAL_NODE_AMOUNT):
        self.x = x
        self.y = y
        self.remaining = amount
        self.max_amount = amount
        self.mining_worker = None  # the worker currently mining this node

    @property
    def rect(self):
        return pygame.Rect(
            self.x - MINERAL_NODE_SIZE, self.y - MINERAL_NODE_SIZE,
            MINERAL_NODE_SIZE * 2, MINERAL_NODE_SIZE * 2,
        )

    @property
    def depleted(self):
        return self.remaining <= 0

    def mine(self, amount):
        taken = min(amount, self.remaining)
        self.remaining -= taken
        return taken

    def draw(self, surface):
        if self.depleted:
            # Grey out depleted nodes
            color = (80, 80, 80)
            alpha = 100
        else:
            color = MINERAL_NODE_COLOR
            alpha = 255

        # Draw crystal shape (diamond polygon)
        cx, cy = self.x, self.y
        s = MINERAL_NODE_SIZE
        points = [
            (cx, cy - s),       # top
            (cx + s, cy),       # right
            (cx, cy + s),       # bottom
            (cx - s, cy),       # left
        ]

        if self.depleted:
            surf = pygame.Surface((s * 2, s * 2), pygame.SRCALPHA)
            shifted = [(px - cx + s, py - cy + s) for px, py in points]
            pygame.draw.polygon(surf, (*color, alpha), shifted)
            surface.blit(surf, (cx - s, cy - s))
        else:
            pygame.draw.polygon(surface, color, points)
            # Bright highlight
            highlight = [(cx, cy - s + 3), (cx + s - 3, cy), (cx, cy - 2)]
            pygame.draw.polygon(surface, (130, 200, 255), highlight)

        # Remaining label
        font = pygame.font.SysFont(None, 16)
        label = font.render(str(self.remaining), True, (255, 255, 255))
        label_rect = label.get_rect(center=(cx, cy + s + 10))
        surface.blit(label, label_rect)
