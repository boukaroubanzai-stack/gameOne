import math
import random
import pygame
from resources import ResourceManager
from buildings import Barracks, Factory, TownCenter, DefenseTower, Watchguard
from units import Worker, Soldier, Tank
from minerals import MineralNode
from settings import (
    STARTING_WORKERS, AI_TC_POS, MINERAL_OFFSETS,
    WORLD_W, WORLD_H,
)

# Reuse AI mineral positions (right side of map, mirrored)
AI_MINERAL_POSITIONS = [(AI_TC_POS[0] - dx, AI_TC_POS[1] + dy) for dx, dy in MINERAL_OFFSETS]

AI_TINT_COLOR = (255, 140, 0)  # same as ai_player.py


def tint_surface(surface, tint_color, alpha=100):
    """Apply an orange tint overlay to a surface."""
    tinted = surface.copy()
    overlay = pygame.Surface(tinted.get_size(), pygame.SRCALPHA)
    overlay.fill((*tint_color, alpha))
    tinted.blit(overlay, (0, 0))
    return tinted


class RemotePlayer:
    """Replaces AIPlayer in multiplayer mode. Same data interface, no autonomous AI."""

    def __init__(self):
        self.resource_manager = ResourceManager()
        self.buildings = []
        self.units = []
        self.mineral_nodes = []

        # Tinted sprites
        self._sprites_tinted = False
        self._tinted_sprites = {}

        self._game_state = None  # set by GameState after init

        self._setup()

    def _setup(self):
        """Initialize remote player starting state (mirrors AIPlayer._setup)."""
        for x, y in AI_MINERAL_POSITIONS:
            self.mineral_nodes.append(MineralNode(x, y))

        tc = TownCenter(AI_TC_POS[0], AI_TC_POS[1])
        tc.team = "ai"
        self.buildings.append(tc)

        for i in range(STARTING_WORKERS):
            w = Worker(tc.rally_x + i * 25, tc.rally_y)
            w.team = "ai"
            self.units.append(w)

    def _ensure_tinted_sprites(self):
        if self._sprites_tinted:
            return
        self._sprites_tinted = True
        if Soldier.sprite:
            self._tinted_sprites["soldier"] = tint_surface(Soldier.sprite, AI_TINT_COLOR)
        if Tank.sprite:
            self._tinted_sprites["tank"] = tint_surface(Tank.sprite, AI_TINT_COLOR)
        if Worker.sprite:
            self._tinted_sprites["worker"] = tint_surface(Worker.sprite, AI_TINT_COLOR)
        if TownCenter.sprite:
            self._tinted_sprites["towncenter"] = tint_surface(TownCenter.sprite, AI_TINT_COLOR)
        if Barracks.sprite:
            self._tinted_sprites["barracks"] = tint_surface(Barracks.sprite, AI_TINT_COLOR)
        if Factory.sprite:
            self._tinted_sprites["factory"] = tint_surface(Factory.sprite, AI_TINT_COLOR)

    def _get_tinted_sprite(self, entity):
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

    def _handle_deploying_workers(self, dt):
        """Check for workers that have arrived at their deploy target."""
        for unit in self.units:
            if not isinstance(unit, Worker) or unit.state != "deploying" or unit.waypoints:
                continue
            if not unit.deploy_building:
                unit.deploy_building = True
                unit.deploy_build_timer = 0.0

            unit.deploy_build_timer += dt
            build_time = unit.deploy_building_class.build_time
            if unit.deploy_build_timer < build_time:
                continue

            bx, by = unit.deploy_target
            b = unit.deploy_building_class(bx, by)
            b.team = "ai"

            valid = True
            if b.rect.bottom > WORLD_H or b.rect.top < 0 or b.rect.left < 0 or b.rect.right > WORLD_W:
                valid = False
            if valid:
                for existing in self.buildings:
                    if b.rect.colliderect(existing.rect):
                        valid = False
                        break
            if valid:
                for node in self.mineral_nodes:
                    if not node.depleted and b.rect.colliderect(node.rect.inflate(10, 10)):
                        valid = False
                        break

            if valid:
                if self._game_state:
                    self._game_state.assign_building_id(b)
                self.buildings.append(b)
                if isinstance(b, Watchguard):
                    unit.hp = 0
                    continue
            else:
                self.resource_manager.deposit(unit.deploy_cost)

            unit.state = "idle"
            unit.deploy_building_class = None
            unit.deploy_target = None
            unit.deploy_cost = 0
            unit.deploy_build_timer = 0.0
            unit.deploy_building = False

    def _collides_with_other(self, unit, x, y, all_units):
        for other in all_units:
            if other is unit:
                continue
            dist = math.hypot(x - other.x, y - other.y)
            if dist < unit.size + other.size:
                return other
        return None

    def _place_unit_at_free_spot(self, unit, all_units):
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
                    if nx < unit.size or nx > WORLD_W - unit.size:
                        continue
                    if ny < unit.size or ny > WORLD_H - unit.size:
                        continue
                    if not self._collides_with_other(unit, nx, ny, all_units):
                        unit.x, unit.y = nx, ny
                        return

    def update(self, dt, player_units, player_buildings, all_units_for_collision):
        """Update remote player entities: production, combat, cleanup. No AI decisions."""
        self._ensure_tinted_sprites()
        self._handle_deploying_workers(dt)

        # Building production and tower combat
        for building in self.buildings:
            if isinstance(building, DefenseTower):
                building.combat_update(dt, player_units)
            else:
                new_unit = building.update(dt)
                if new_unit is not None:
                    new_unit.team = "ai"
                    if self._game_state:
                        self._game_state.assign_unit_id(new_unit)
                    self._place_unit_at_free_spot(new_unit, all_units_for_collision)
                    self.units.append(new_unit)

        # Auto-target: combat units attack player units in range
        for unit in self.units:
            if not unit.alive:
                continue

            if isinstance(unit, Worker):
                if unit.state != "idle":
                    unit.update_state(dt)
                continue

            if unit.attacking:
                target = unit.target_enemy
                if not target:
                    unit.attacking = False
                elif (hasattr(target, 'alive') and not target.alive) or \
                     (hasattr(target, 'hp') and target.hp <= 0):
                    unit.target_enemy = None
                    unit.attacking = False
                else:
                    if hasattr(target, 'size'):
                        tx, ty = target.x, target.y
                    else:
                        tx, ty = target.x + target.w // 2, target.y + target.h // 2
                    if unit.distance_to(tx, ty) <= unit.attack_range:
                        unit.try_attack(dt)
                    else:
                        unit.target_enemy = None
                        unit.attacking = False
                continue

            # Auto-target: find nearest player unit/building in range
            if isinstance(unit, (Soldier, Tank)):
                target = unit.find_target(player_units, player_buildings)
                if target:
                    unit.hunting_target = None
                    unit.target_enemy = target
                    unit.attacking = True
                    unit.fire_cooldown = 0.0
                    unit.try_attack(dt)
                    continue
                # Vision hunting
                if not unit.waypoints or unit.hunting_target:
                    if unit.hunting_target:
                        ht = unit.hunting_target
                        alive = (hasattr(ht, 'alive') and ht.alive) or \
                                (hasattr(ht, 'hp') and ht.hp > 0)
                        if alive:
                            if hasattr(ht, 'size'):
                                hx, hy = ht.x, ht.y
                            else:
                                hx, hy = ht.x + ht.w // 2, ht.y + ht.h // 2
                            dist = unit.distance_to(hx, hy)
                            if dist <= unit.vision_range:
                                unit.waypoints = [(hx, hy)]
                            else:
                                unit.hunting_target = None
                                unit.waypoints = []
                        else:
                            unit.hunting_target = None
                            unit.waypoints = []
                    else:
                        visible = unit.find_visible_target(player_units, player_buildings)
                        if visible:
                            unit.hunting_target = visible
                            if hasattr(visible, 'size'):
                                hx, hy = visible.x, visible.y
                            else:
                                hx, hy = visible.x + visible.w // 2, visible.y + visible.h // 2
                            unit.waypoints = [(hx, hy)]

        # Cleanup dead
        for u in self.units:
            if not u.alive and isinstance(u, Worker):
                u.cancel_mining()
                u.cancel_deploy()
        self.units = [u for u in self.units if u.alive]
        self.buildings = [b for b in self.buildings if b.hp > 0]
