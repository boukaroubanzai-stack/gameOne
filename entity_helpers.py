"""Shared entity helpers: collision, placement, deploying, combat targeting."""

import math
from buildings import Watchguard
from settings import WORLD_W, WORLD_H


def entity_center(entity):
    """Get center position of an entity (unit or building)."""
    if hasattr(entity, 'size'):
        return entity.x, entity.y
    return entity.x + entity.w // 2, entity.y + entity.h // 2


def collides_with_other(unit, x, y, all_units):
    """Check if unit at position (x, y) would overlap any other unit."""
    for other in all_units:
        if other is unit:
            continue
        dist = math.hypot(x - other.x, y - other.y)
        if dist < unit.size + other.size:
            return other
    return None


def place_unit_at_free_spot(unit, all_units):
    """Nudge a newly spawned unit to a free spot if it overlaps an existing unit."""
    if not collides_with_other(unit, unit.x, unit.y, all_units):
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
                if not collides_with_other(unit, nx, ny, all_units):
                    unit.x, unit.y = nx, ny
                    return


def handle_deploying_workers(units, target_buildings, check_buildings, check_mineral_nodes,
                             resource_manager, game_state, team, dt):
    """Handle workers in deploying state: build when arrived at target.

    Args:
        units: Unit list to iterate over.
        target_buildings: List to append new buildings to.
        check_buildings: Buildings to check for overlap collisions.
        check_mineral_nodes: Mineral nodes to check for overlap collisions.
        resource_manager: For refunding cost on failed placement.
        game_state: GameState for assign_building_id (can be None).
        team: Team string to assign to new buildings (None for player team).
        dt: Delta time.
    """
    from units import Worker

    for unit in units:
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
        if team:
            b.team = team

        valid = True
        if b.rect.bottom > WORLD_H or b.rect.top < 0 or b.rect.left < 0 or b.rect.right > WORLD_W:
            valid = False
        if valid:
            for existing in check_buildings:
                if b.rect.colliderect(existing.rect):
                    valid = False
                    break
        if valid:
            for node in check_mineral_nodes:
                if not node.depleted and b.rect.colliderect(node.rect.inflate(10, 10)):
                    valid = False
                    break

        if valid:
            if game_state:
                game_state.assign_building_id(b)
            target_buildings.append(b)
            if isinstance(b, Watchguard):
                unit.hp = 0
                continue
        else:
            resource_manager.deposit(unit.deploy_cost)

        unit.state = "idle"
        unit.deploy_building_class = None
        unit.deploy_target = None
        unit.deploy_cost = 0
        unit.deploy_build_timer = 0.0
        unit.deploy_building = False


# --- Combat auto-targeting helpers ---

def validate_attack_target(unit, dt):
    """Validate current attack target and try to attack if in range.

    Returns True if attack continues, False if disengaged.
    """
    target = unit.target_enemy
    if not target:
        unit.attacking = False
        return False
    if (hasattr(target, 'alive') and not target.alive) or \
       (hasattr(target, 'hp') and target.hp <= 0):
        unit.target_enemy = None
        unit.attacking = False
        return False
    tx, ty = entity_center(target)
    if unit.distance_to(tx, ty) <= unit.attack_range:
        unit.try_attack(dt)
        return True
    else:
        unit.target_enemy = None
        unit.attacking = False
        return False


def try_auto_target(unit, dt, enemy_units, enemy_buildings):
    """Try to auto-target an enemy in attack range.

    Returns True if engaged a new target.
    """
    target = unit.find_target(enemy_units, enemy_buildings)
    if target:
        unit.hunting_target = None
        unit.target_enemy = target
        unit.attacking = True
        unit.fire_cooldown = 0.0
        unit.try_attack(dt)
        return True
    return False


def update_vision_hunting(unit, enemy_units, enemy_buildings):
    """Check vision range for enemies to hunt. Updates unit waypoints."""
    if unit.waypoints and not unit.hunting_target:
        return
    if unit.hunting_target:
        ht = unit.hunting_target
        alive = (hasattr(ht, 'alive') and ht.alive) or \
                (hasattr(ht, 'hp') and ht.hp > 0)
        if alive:
            hx, hy = entity_center(ht)
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
        visible = unit.find_visible_target(enemy_units, enemy_buildings)
        if visible:
            unit.hunting_target = visible
            hx, hy = entity_center(visible)
            unit.waypoints = [(hx, hy)]
