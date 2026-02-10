# Screen
WIDTH = 2000
HEIGHT = 1200
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
MINERAL_NODE_AMOUNT = 2500
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
SOLDIER_COST = 100
SOLDIER_HP = 100
SOLDIER_SPEED = 120  # pixels per second
SOLDIER_SIZE = 16  # half-width
SOLDIER_TRAIN_TIME = 3.0  # seconds
SOLDIER_FIRE_RATE = 5.0  # shots per second
SOLDIER_DAMAGE = 10
SOLDIER_RANGE = SOLDIER_SIZE * 7  # firing range

# Tank
TANK_COST = 350
TANK_HP = 500
TANK_SPEED = SOLDIER_SPEED // 2  # twice as slow as soldier
TANK_SIZE = 20  # half-width
TANK_TRAIN_TIME = 6.0  # seconds
TANK_FIRE_RATE = 1.0  # shots per second
TANK_DAMAGE = 34
TANK_RANGE = TANK_SIZE * 7  # firing range

# Yanuses (enemy)
YANUSES_HP = 100
YANUSES_SPEED = 80
YANUSES_SIZE = 16
YANUSES_FIRE_RATE = 5.0
YANUSES_DAMAGE = 10
YANUSES_RANGE = YANUSES_SIZE * 7
YANUSES_SPRITE = os.path.join(ASSETS_DIR, "yanuses.png")

# Waves
TOTAL_WAVES = 10
FIRST_WAVE_DELAY = 120.0  # seconds before first wave (2 minutes)
WAVE_INTERVAL = 30.0  # seconds between waves
YANUSES_PER_WAVE = 3  # enemies per wave

# Town Center
TOWN_CENTER_COST = 100
TOWN_CENTER_SIZE = (64, 64)

# Barracks
BARRACKS_COST = 50
BARRACKS_SIZE = (64, 64)

# Factory
FACTORY_COST = 80
FACTORY_SIZE = (64, 64)
