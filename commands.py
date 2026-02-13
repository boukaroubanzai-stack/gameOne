"""Multiplayer command execution: translates network commands into game actions."""

import math
from units import Worker, Soldier, Scout, Tank
from buildings import Barracks, Factory, TownCenter, DefenseTower, Watchguard, Radar
from settings import (
    BARRACKS_COST, FACTORY_COST, TOWN_CENTER_COST, TOWER_COST, WATCHGUARD_COST,
    RADAR_COST,
)

BUILDING_CLASSES = {
    "barracks": Barracks,
    "factory": Factory,
    "towncenter": TownCenter,
    "tower": DefenseTower,
    "watchguard": Watchguard,
    "radar": Radar,
}

BUILDING_COSTS = {
    "barracks": BARRACKS_COST,
    "factory": FACTORY_COST,
    "towncenter": TOWN_CENTER_COST,
    "tower": TOWER_COST,
    "watchguard": WATCHGUARD_COST,
    "radar": RADAR_COST,
}


def execute_command(cmd, game_state, team):
    """Execute a command for the given team ('player' or 'ai')."""
    if team == "player":
        units = game_state.units
        buildings = game_state.buildings
        mineral_nodes = game_state.mineral_nodes
        resource_mgr = game_state.resource_manager
    else:
        units = game_state.ai_player.units
        buildings = game_state.ai_player.buildings
        mineral_nodes = game_state.ai_player.mineral_nodes
        resource_mgr = game_state.ai_player.resource_manager

    cmd_type = cmd["cmd"]

    if cmd_type == "move":
        target = (cmd["x"], cmd["y"])
        for uid in cmd["unit_ids"]:
            unit = _find_unit(units, uid)
            if unit:
                unit.set_target(target)

    elif cmd_type == "queue_waypoint":
        target = (cmd["x"], cmd["y"])
        for uid in cmd["unit_ids"]:
            unit = _find_unit(units, uid)
            if unit:
                unit.add_waypoint(target)

    elif cmd_type == "mine":
        node_idx = cmd["node_index"]
        if 0 <= node_idx < len(mineral_nodes):
            node = mineral_nodes[node_idx]
            for uid in cmd["unit_ids"]:
                unit = _find_unit(units, uid)
                if unit and isinstance(unit, Worker):
                    unit.assign_to_mine(node, buildings, resource_mgr)

    elif cmd_type == "place_building":
        building_type = cmd["building_type"]
        bx, by = cmd["x"], cmd["y"]
        worker_id = cmd["worker_id"]
        building_class = BUILDING_CLASSES.get(building_type)
        if not building_class:
            return
        cost = BUILDING_COSTS.get(building_type, 0)
        if not resource_mgr.can_afford(cost):
            return
        worker = _find_unit(units, worker_id)
        if worker and isinstance(worker, Worker):
            resource_mgr.spend(cost)
            worker.assign_to_deploy(building_class, (bx, by), cost)

    elif cmd_type == "train_unit":
        building_id = cmd["building_id"]
        building = _find_building(buildings, building_id)
        if building:
            building.start_production(resource_mgr)

    elif cmd_type == "train_scout":
        building_id = cmd["building_id"]
        building = _find_building(buildings, building_id)
        if building and hasattr(building, 'start_production_scout'):
            building.start_production_scout(resource_mgr)

    elif cmd_type == "chat":
        import time
        game_state.chat_log.append({
            "team": team,
            "message": cmd["message"],
            "time": time.time(),
        })
        return


    elif cmd_type == "attack":
        target_id = cmd["target_id"]
        target_type = cmd.get("target_type", "unit")
        # Find target in the opposing team
        if team == "ai":
            opp_units = game_state.units
            opp_buildings = game_state.buildings
        else:
            opp_units = game_state.ai_player.units
            opp_buildings = game_state.ai_player.buildings
        if target_type == "building":
            target = _find_building(opp_buildings, target_id)
        else:
            target = _find_unit(opp_units, target_id)
        if target:
            for uid in cmd["unit_ids"]:
                unit = _find_unit(units, uid)
                if unit:
                    if hasattr(target, 'size'):
                        unit.set_target((target.x, target.y))
                    else:
                        unit.set_target((target.x + target.w // 2, target.y + target.h // 2))
                    unit.target_enemy = target
                    unit.attacking = True

    elif cmd_type == "repair":
        target_type = cmd["target_type"]
        target_id = cmd["target_id"]
        if target_type == "unit":
            target = _find_unit(units, target_id)
        else:
            target = _find_building(buildings, target_id)
        if target:
            for wid in cmd["worker_ids"]:
                worker = _find_unit(units, wid)
                if worker and isinstance(worker, Worker):
                    worker.assign_to_repair(target)


def _find_unit(units, net_id):
    for u in units:
        if u.net_id == net_id:
            return u
    return None


def _find_building(buildings, net_id):
    for b in buildings:
        if b.net_id == net_id:
            return b
    return None
