import pygame
from resources import ResourceManager
from buildings import Barracks, Factory, TownCenter
from units import Worker
from minerals import MineralNode, MINERAL_POSITIONS
from settings import (
    MAP_HEIGHT, WIDTH, STARTING_WORKERS,
    BARRACKS_COST, FACTORY_COST, TOWN_CENTER_COST,
)


class GameState:
    def __init__(self):
        self.resource_manager = ResourceManager()
        self.buildings = []
        self.units = []
        self.mineral_nodes = []
        self.selected_units = []
        self.selected_building = None
        self.placement_mode = None  # None, "barracks", "factory", "towncenter"

        self._setup_starting_state()

    def _setup_starting_state(self):
        # Place mineral nodes
        for x, y in MINERAL_POSITIONS:
            self.mineral_nodes.append(MineralNode(x, y))

        # Place starting Town Center
        tc = TownCenter(100, 280)
        self.buildings.append(tc)

        # Spawn starting workers near the Town Center
        for i in range(STARTING_WORKERS):
            w = Worker(tc.rally_x + i * 25, tc.rally_y)
            self.units.append(w)

    def deselect_all(self):
        for u in self.selected_units:
            u.selected = False
        self.selected_units = []
        if self.selected_building:
            self.selected_building.selected = False
            self.selected_building = None

    def select_unit(self, unit):
        self.deselect_all()
        unit.selected = True
        self.selected_units = [unit]

    def select_units(self, units):
        self.deselect_all()
        for u in units:
            u.selected = True
        self.selected_units = list(units)

    def select_building(self, building):
        self.deselect_all()
        building.selected = True
        self.selected_building = building

    def get_unit_at(self, pos):
        for unit in reversed(self.units):
            if unit.rect.collidepoint(pos):
                return unit
        return None

    def get_building_at(self, pos):
        for building in reversed(self.buildings):
            if building.rect.collidepoint(pos):
                return building
        return None

    def get_mineral_node_at(self, pos):
        for node in self.mineral_nodes:
            if not node.depleted and node.rect.collidepoint(pos):
                return node
        return None

    def get_units_in_rect(self, rect):
        return [u for u in self.units if rect.colliderect(u.rect)]

    def _find_nearest_town_center(self, x, y):
        best = None
        best_dist = float("inf")
        for b in self.buildings:
            if isinstance(b, TownCenter):
                dx = (b.x + b.w // 2) - x
                dy = (b.y + b.h // 2) - y
                d = dx * dx + dy * dy
                if d < best_dist:
                    best_dist = d
                    best = b
        return best

    def command_mine(self, node):
        tc = self._find_nearest_town_center(node.x, node.y)
        if tc is None:
            return
        for unit in self.selected_units:
            if isinstance(unit, Worker):
                unit.assign_to_mine(node, tc, self.resource_manager)

    def place_building(self, pos):
        x, y = pos
        if self.placement_mode == "barracks":
            b = Barracks(x, y)
        elif self.placement_mode == "factory":
            b = Factory(x, y)
        elif self.placement_mode == "towncenter":
            b = TownCenter(x, y)
        else:
            return False

        # Check building fits within map area
        if b.rect.bottom > MAP_HEIGHT or b.rect.top < 0:
            return False
        if b.rect.left < 0 or b.rect.right > WIDTH:
            return False

        # Check not overlapping existing buildings
        for existing in self.buildings:
            if b.rect.colliderect(existing.rect):
                return False

        # Check not overlapping mineral nodes
        for node in self.mineral_nodes:
            if not node.depleted and b.rect.colliderect(node.rect.inflate(10, 10)):
                return False

        cost = self._placement_cost()
        if self.resource_manager.spend(cost):
            self.buildings.append(b)
            self.placement_mode = None
            return True
        return False

    def _placement_cost(self):
        if self.placement_mode == "barracks":
            return BARRACKS_COST
        elif self.placement_mode == "factory":
            return FACTORY_COST
        elif self.placement_mode == "towncenter":
            return TOWN_CENTER_COST
        return 0

    def command_move(self, pos):
        for unit in self.selected_units:
            unit.set_target(pos)

    def command_queue_waypoint(self, pos):
        for unit in self.selected_units:
            unit.add_waypoint(pos)

    def update(self, dt):
        for unit in self.units:
            unit.update(dt)
        for building in self.buildings:
            new_unit = building.update(dt)
            if new_unit is not None:
                self.units.append(new_unit)
