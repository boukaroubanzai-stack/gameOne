import math
import random
import pygame
from resources import ResourceManager
from buildings import Barracks, Factory, TownCenter
from units import Worker, Soldier, Tank
from minerals import MineralNode
from settings import (
    MAP_HEIGHT, WIDTH,
    BARRACKS_COST, FACTORY_COST, TOWN_CENTER_COST,
    SOLDIER_COST, TANK_COST, WORKER_COST,
    BARRACKS_SIZE, FACTORY_SIZE, TOWN_CENTER_SIZE,
    STARTING_WORKERS,
)


# AI mineral nodes on the right side of the map
AI_MINERAL_POSITIONS = [
    (1800, 100),
    (1200, 80),
    (1500, 300),
    (1850, 500),
    (1150, 450),
]

# AI tint color: orange/red overlay to distinguish from player
AI_TINT_COLOR = (255, 80, 0, 80)

# AI decision timers (seconds)
AI_THINK_INTERVAL = 2.0
AI_ATTACK_THRESHOLD = 5  # min combat units before attacking
AI_MAX_WORKERS = 6


def tint_surface(surface, tint_color):
    """Return a copy of the surface with a color tint overlay."""
    tinted = surface.copy()
    overlay = pygame.Surface(tinted.get_size(), pygame.SRCALPHA)
    overlay.fill(tint_color)
    tinted.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    # Add an orange overlay on top for visibility
    orange_overlay = pygame.Surface(tinted.get_size(), pygame.SRCALPHA)
    orange_overlay.fill((255, 120, 40, 100))
    tinted.blit(orange_overlay, (0, 0))
    return tinted


class AIPlayer:
    """Computer-controlled opponent that builds a base, trains units, and attacks."""

    def __init__(self):
        self.resource_manager = ResourceManager()
        self.buildings = []
        self.units = []
        self.mineral_nodes = []

        # AI state
        self.think_timer = 0.0
        self.phase = "economy"  # "economy", "build", "military", "attack"
        self.attack_sent = False
        self.attack_target = None

        # Tinted sprites (created after pygame init, on first update)
        self._sprites_tinted = False
        self._tinted_sprites = {}

        self._setup()

    def _setup(self):
        """Set up AI starting state: mineral nodes, town center, workers."""
        # Create AI mineral nodes on the right side
        for x, y in AI_MINERAL_POSITIONS:
            self.mineral_nodes.append(MineralNode(x, y))

        # Place starting Town Center on the right side
        tc = TownCenter(1800, 280)
        tc.team = "ai"
        self.buildings.append(tc)

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

    def _get_tinted_sprite(self, entity):
        """Get the tinted sprite for an AI entity."""
        if isinstance(entity, Soldier):
            return self._tinted_sprites.get("soldier")
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
        return None

    def _find_ai_town_center(self):
        """Find the first alive AI town center."""
        for b in self.buildings:
            if isinstance(b, TownCenter) and b.hp > 0:
                return b
        return None

    def _count_workers(self):
        return sum(1 for u in self.units if isinstance(u, Worker) and u.alive)

    def _count_combat_units(self):
        return sum(1 for u in self.units if isinstance(u, (Soldier, Tank)) and u.alive)

    def _has_building(self, building_type):
        return any(isinstance(b, building_type) and b.hp > 0 for b in self.buildings)

    def _get_building(self, building_type):
        for b in self.buildings:
            if isinstance(b, building_type) and b.hp > 0:
                return b
        return None

    def _find_available_mineral_node(self):
        """Find an AI mineral node that isn't fully occupied."""
        for node in self.mineral_nodes:
            if not node.depleted and node.mining_worker is None:
                return node
        # If all nodes have a worker, find one that's not depleted
        for node in self.mineral_nodes:
            if not node.depleted:
                return node
        return None

    def _assign_idle_workers(self):
        """Send idle workers to mine."""
        tc = self._find_ai_town_center()
        if tc is None:
            return
        for unit in self.units:
            if isinstance(unit, Worker) and unit.alive and unit.state == "idle":
                node = self._find_available_mineral_node()
                if node:
                    unit.assign_to_mine(node, tc, self.resource_manager)

    def _find_building_placement(self, size):
        """Find a valid position to place a building near the AI base."""
        tc = self._find_ai_town_center()
        if tc is None:
            return None
        base_x = tc.x
        base_y = tc.y
        bw, bh = size

        # Try positions in a grid around the town center
        for attempt in range(50):
            # Place buildings below and around the TC
            offset_x = random.randint(-200, 200)
            offset_y = random.randint(-150, 200)
            x = base_x + offset_x
            y = base_y + offset_y

            # Clamp to map bounds
            x = max(0, min(x, WIDTH - bw))
            y = max(0, min(y, MAP_HEIGHT - bh))

            rect = pygame.Rect(x, y, bw, bh)

            # Check no overlap with existing AI buildings
            overlap = False
            for b in self.buildings:
                if rect.colliderect(b.rect.inflate(10, 10)):
                    overlap = True
                    break

            # Check no overlap with AI mineral nodes
            if not overlap:
                for node in self.mineral_nodes:
                    if not node.depleted and rect.colliderect(node.rect.inflate(10, 10)):
                        overlap = True
                        break

            if not overlap:
                return (x, y)
        return None

    def _try_place_building(self, building_class, cost, size):
        """Attempt to place and pay for a building."""
        if not self.resource_manager.can_afford(cost):
            return False
        pos = self._find_building_placement(size)
        if pos is None:
            return False
        self.resource_manager.spend(cost)
        b = building_class(pos[0], pos[1])
        b.team = "ai"
        self.buildings.append(b)
        return True

    def _try_train_unit(self, building, resource_mgr):
        """Train a unit from a building if affordable."""
        unit_class, cost, train_time = building.can_train()
        if resource_mgr.spend(cost):
            building.production_queue.append((unit_class, train_time))
            return True
        return False

    def _think(self, player_units, player_buildings):
        """AI decision-making, called periodically."""
        # Always assign idle workers first
        self._assign_idle_workers()

        num_workers = self._count_workers()
        num_combat = self._count_combat_units()
        has_barracks = self._has_building(Barracks)
        has_factory = self._has_building(Factory)
        tc = self._find_ai_town_center()

        # ECONOMY: Train workers if we need more
        if num_workers < AI_MAX_WORKERS and tc and len(tc.production_queue) == 0:
            if self.resource_manager.can_afford(WORKER_COST):
                self._try_train_unit(tc, self.resource_manager)

        # BUILD: Build barracks first, then factory
        if not has_barracks:
            self._try_place_building(Barracks, BARRACKS_COST, BARRACKS_SIZE)
        elif not has_factory and self.resource_manager.amount >= FACTORY_COST + 50:
            self._try_place_building(Factory, FACTORY_COST, FACTORY_SIZE)

        # MILITARY: Train combat units
        barracks = self._get_building(Barracks)
        factory = self._get_building(Factory)
        if barracks and len(barracks.production_queue) < 2:
            if self.resource_manager.can_afford(SOLDIER_COST):
                self._try_train_unit(barracks, self.resource_manager)
        if factory and len(factory.production_queue) < 2:
            if self.resource_manager.can_afford(TANK_COST):
                self._try_train_unit(factory, self.resource_manager)

        # ATTACK: Send army when we have enough combat units
        if num_combat >= AI_ATTACK_THRESHOLD and not self.attack_sent:
            self._launch_attack(player_units, player_buildings)
        elif self.attack_sent and num_combat < 2:
            # Attack spent, reset and rebuild
            self.attack_sent = False

        # DEFENSE: Pull units back if our buildings are under attack
        self._check_defense(player_units)

    def _launch_attack(self, player_units, player_buildings):
        """Send all combat units to attack the player's base."""
        # Find a target: nearest player building or unit
        target = None
        best_dist = float("inf")

        # Prefer attacking player buildings
        for b in player_buildings:
            if b.hp > 0:
                bx, by = b.x + b.w // 2, b.y + b.h // 2
                d = bx  # Prefer leftmost (player side)
                if d < best_dist:
                    best_dist = d
                    target = (bx, by)

        if target is None:
            for u in player_units:
                if u.alive:
                    target = (u.x, u.y)
                    break

        if target is None:
            return

        self.attack_target = target
        self.attack_sent = True

        for unit in self.units:
            if isinstance(unit, (Soldier, Tank)) and unit.alive and not unit.attacking:
                unit.set_target(target)

    def _check_defense(self, player_units):
        """If AI buildings are under attack, pull combat units back to defend."""
        for b in self.buildings:
            if b.hp < b.max_hp:
                # Building damaged -- find nearby enemy
                for pu in player_units:
                    if not pu.alive:
                        continue
                    bx, by = b.x + b.w // 2, b.y + b.h // 2
                    dist = math.hypot(pu.x - bx, pu.y - by)
                    if dist < 200:
                        # Pull combat units to defend
                        for unit in self.units:
                            if isinstance(unit, (Soldier, Tank)) and unit.alive:
                                if not unit.attacking:
                                    unit.set_target((pu.x, pu.y))
                        return

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
                    if nx < unit.size or nx > WIDTH - unit.size:
                        continue
                    if ny < unit.size or ny > MAP_HEIGHT - unit.size:
                        continue
                    if not self._collides_with_other(unit, nx, ny, all_units):
                        unit.x, unit.y = nx, ny
                        return

    def update(self, dt, player_units, player_buildings, all_units_for_collision):
        """Update AI: think, produce, move units."""
        self._ensure_tinted_sprites()

        # Periodic decision making
        self.think_timer += dt
        if self.think_timer >= AI_THINK_INTERVAL:
            self.think_timer = 0.0
            self._think(player_units, player_buildings)

        # Update building production
        for building in self.buildings:
            new_unit = building.update(dt)
            if new_unit is not None:
                new_unit.team = "ai"
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
                if target and hasattr(target, 'alive') and not target.alive:
                    unit.target_enemy = None
                    unit.attacking = False
                elif target and hasattr(target, 'hp') and target.hp <= 0:
                    unit.target_enemy = None
                    unit.attacking = False
                else:
                    unit.try_attack(dt)
                continue

            # Auto-target: find nearest player unit/building in range
            if isinstance(unit, (Soldier, Tank)):
                target = unit.find_target(player_units, player_buildings)
                if target:
                    unit.target_enemy = target
                    unit.attacking = True
                    unit.waypoints.clear()
                    unit.fire_cooldown = 0.0
                    unit.try_attack(dt)

        # Remove dead AI units
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
            font = pygame.font.SysFont(None, 18)
            label = font.render(f"AI {building.label}", True, (255, 180, 100))
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
