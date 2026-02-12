# Screen (viewport)
WIDTH = 2000
HEIGHT = 1200
FPS = 60
HUD_HEIGHT = 120

# Map area (above HUD) — this is the visible viewport height
MAP_HEIGHT = HEIGHT - HUD_HEIGHT

# World size (the full scrollable map)
WORLD_W = 10000
WORLD_H = 5400

# Camera scrolling
SCROLL_SPEED = 800  # pixels per second
SCROLL_EDGE = 30    # pixels from screen edge to trigger scroll

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

# Mineral offsets from Town Center — shared by both player and AI
# (dx, dy) pairs; player uses +dx, AI uses -dx (mirrored)
MINERAL_OFFSETS = [
    (250, -80),
    (200, 220),
    (500, -80),
    (500, 520),
    (800, 120),
    (1000, 70),
    (800, 720),
    (1200, -30),
    (1400, -130),
    (1500, 320),
]

# Starting Town Center positions
PLAYER_TC_POS = (100, 280)
AI_TC_POS = (8000, 280)

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
TOWN_CENTER_HP = 1000
TOWN_CENTER_BUILD_TIME = 15.0

# Barracks
BARRACKS_COST = 50
BARRACKS_SIZE = (64, 64)
BARRACKS_HP = 400
BARRACKS_BUILD_TIME = 5.0

# Factory
FACTORY_COST = 80
FACTORY_SIZE = (64, 64)
FACTORY_HP = 400
FACTORY_BUILD_TIME = 10.0

# Defense Tower
TOWER_COST = 300
TOWER_SIZE = (48, 48)
TOWER_HP = 1000
TOWER_FIRE_RATE = 1.5  # shots per second (between soldier and tank)
TOWER_DAMAGE = 25
TOWER_RANGE = 200  # pixels, large range
TOWER_SPRITE = os.path.join(ASSETS_DIR, "tower.png")  # will use fallback if missing
TOWER_BUILD_TIME = 5.0

# Watchguard
WATCHGUARD_COST = 200
WATCHGUARD_SIZE = (48, 48)
WATCHGUARD_HP = 400
WATCHGUARD_BUILD_TIME = 3.0
WATCHGUARD_ZONE_RADIUS = 500  # expands building area by 500px

# Building placement zones
BUILDING_ZONE_TC_RADIUS = 500      # can place within 500px of a Town Center
BUILDING_ZONE_BUILDING_RADIUS = 100  # can place within 100px of any other building

# Multiplayer
MULTIPLAYER_PORT = 7777
TICK_INTERVAL = 4  # lockstep tick every N frames
