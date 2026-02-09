# Screen
WIDTH = 1024
HEIGHT = 768
FPS = 60
HUD_HEIGHT = 120

# Map area (above HUD)
MAP_HEIGHT = HEIGHT - HUD_HEIGHT

# Colors
MAP_COLOR = (34, 85, 34)
HUD_BG = (40, 40, 40)
HUD_TEXT = (220, 220, 220)
SELECT_COLOR = (0, 255, 0)
DRAG_BOX_COLOR = (0, 255, 0)
HEALTH_BAR_BG = (80, 0, 0)
HEALTH_BAR_FG = (0, 200, 0)
BUTTON_COLOR = (70, 70, 70)
BUTTON_HOVER = (100, 100, 100)
BUTTON_TEXT = (255, 255, 255)

# Asset paths
import os
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
SOLDIER_SPRITE = os.path.join(ASSETS_DIR, "soldier.png")
TANK_SPRITE = os.path.join(ASSETS_DIR, "tank.png")
BARRACKS_SPRITE = os.path.join(ASSETS_DIR, "barracks.png")
FACTORY_SPRITE = os.path.join(ASSETS_DIR, "factory.png")
WORKER_SPRITE = os.path.join(ASSETS_DIR, "worker.png")
TOWN_CENTER_SPRITE = os.path.join(ASSETS_DIR, "towncenter.png")

# Resources
STARTING_RESOURCES = 50

# Mineral nodes
MINERAL_NODE_AMOUNT = 500
MINERAL_NODE_SIZE = 16  # radius
MINERAL_NODE_COLOR = (50, 150, 255)

# Worker
WORKER_COST = 15
WORKER_HP = 30
WORKER_SPEED = 80  # pixels per second
WORKER_SIZE = 12  # half-width
WORKER_TRAIN_TIME = 4.0  # seconds
WORKER_CARRY_CAPACITY = 10  # resources per trip
WORKER_MINE_TIME = 2.0  # seconds to fill up at a node
STARTING_WORKERS = 3

# Soldier
SOLDIER_COST = 25
SOLDIER_HP = 50
SOLDIER_SPEED = 120  # pixels per second
SOLDIER_SIZE = 16  # half-width
SOLDIER_TRAIN_TIME = 3.0  # seconds

# Tank
TANK_COST = 60
TANK_HP = 150
TANK_SPEED = 60  # pixels per second
TANK_SIZE = 20  # half-width
TANK_TRAIN_TIME = 6.0  # seconds

# Town Center
TOWN_CENTER_COST = 100
TOWN_CENTER_SIZE = (64, 64)

# Barracks
BARRACKS_COST = 50
BARRACKS_SIZE = (64, 64)

# Factory
FACTORY_COST = 80
FACTORY_SIZE = (64, 64)
