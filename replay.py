"""Replay system: record and play back game sessions."""

import json
import os
import datetime
import pygame


class ReplayRecorder:
    """Records game state snapshots for later replay."""

    def __init__(self):
        self.frames = []
        self.real_time = 0.0
        self.last_capture_time = -1.0
        self.capture_interval = 0.1  # 100ms = ~10 FPS recording
        self._saved = False

    def capture(self, dt, state):
        """Capture a snapshot if enough real time has elapsed."""
        self.real_time += dt
        if self.real_time - self.last_capture_time < self.capture_interval:
            return
        self.last_capture_time = self.real_time

        frame = {
            "t": round(self.real_time, 3),
            "units": self._snap_units(state.units),
            "buildings": self._snap_buildings(state.buildings),
            "minerals": self._snap_minerals(state.mineral_nodes),
            "resources": round(state.resource_manager.amount, 1),
            "enemies": self._snap_units(state.wave_manager.enemies),
            "ai_units": self._snap_units(state.ai_player.units),
            "ai_buildings": self._snap_buildings(state.ai_player.buildings),
            "ai_minerals": self._snap_minerals(state.ai_player.mineral_nodes),
            "ai_resources": round(state.ai_player.resource_manager.amount, 1),
            "wave": state.wave_manager.current_wave,
            "game_over": state.game_over,
            "game_result": state.game_result,
        }
        self.frames.append(frame)

    def _snap_units(self, units):
        out = []
        for u in units:
            d = {
                "type": u.name.lower(),
                "x": round(u.x, 1),
                "y": round(u.y, 1),
                "hp": u.hp,
                "max_hp": u.max_hp,
                "size": u.size,
                "team": u.team,
                "attacking": u.attacking,
            }
            if hasattr(u, "state"):
                d["state"] = u.state
            if hasattr(u, "carry_amount"):
                d["carry_amount"] = u.carry_amount
            out.append(d)
        return out

    def _snap_buildings(self, buildings):
        out = []
        for b in buildings:
            out.append({
                "type": b.label.lower().replace(" ", ""),
                "x": b.x,
                "y": b.y,
                "w": b.w,
                "h": b.h,
                "hp": b.hp,
                "max_hp": b.max_hp,
                "label": b.label,
                "queue_len": len(b.production_queue),
                "prod_progress": round(b.production_progress, 3),
            })
        return out

    def _snap_minerals(self, nodes):
        out = []
        for n in nodes:
            out.append({
                "x": n.x,
                "y": n.y,
                "remaining": n.remaining,
            })
        return out

    def save(self):
        """Write all frames to a JSON lines file in replay/ folder."""
        if self._saved or not self.frames:
            return None
        os.makedirs("replay", exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join("replay", f"replay_{ts}.json")
        with open(filename, "w") as f:
            for frame in self.frames:
                f.write(json.dumps(frame, separators=(",", ":")) + "\n")
        self._saved = True
        print(f"Replay saved: {filename} ({len(self.frames)} frames, {self.real_time:.1f}s)")
        return filename


# --- Proxy classes for replay rendering ---


class ReplayUnit:
    """Lightweight proxy satisfying _draw_unit_offset attribute requirements."""

    _SPRITE_MAP = {}

    @classmethod
    def init_sprites(cls):
        from units import Soldier, Tank, Worker, Yanuses
        cls._SPRITE_MAP = {
            "soldier": Soldier.sprite,
            "tank": Tank.sprite,
            "worker": Worker.sprite,
            "yanuses": Yanuses.sprite,
        }

    def __init__(self, data):
        self.x = data["x"]
        self.y = data["y"]
        self.hp = data["hp"]
        self.max_hp = data["max_hp"]
        self.size = data["size"]
        self.team = data.get("team", "player")
        self.attacking = data.get("attacking", False)
        self.target_enemy = None
        self.waypoints = []
        self.selected = False
        self.name = data["type"].capitalize()
        self.state = data.get("state", "idle")
        self.carry_amount = data.get("carry_amount", 0)
        self._type = data["type"]
        self.sprite = self._SPRITE_MAP.get(self._type)

    @property
    def alive(self):
        return self.hp > 0

    @property
    def rect(self):
        return pygame.Rect(
            self.x - self.size, self.y - self.size,
            self.size * 2, self.size * 2,
        )


class ReplayBuilding:
    """Lightweight proxy satisfying _draw_building_offset attribute requirements."""

    _SPRITE_MAP = {}

    @classmethod
    def init_sprites(cls):
        from buildings import TownCenter, Barracks, Factory, DefenseTower
        cls._SPRITE_MAP = {
            "towncenter": TownCenter.sprite,
            "barracks": Barracks.sprite,
            "factory": Factory.sprite,
            "tower": DefenseTower.sprite,
        }

    def __init__(self, data):
        self.x = data["x"]
        self.y = data["y"]
        self.w = data["w"]
        self.h = data["h"]
        self.hp = data["hp"]
        self.max_hp = data["max_hp"]
        self.label = data["label"]
        self.selected = False
        self._type = data["type"]
        self.sprite = self._SPRITE_MAP.get(self._type)
        self.production_queue = [None] * data.get("queue_len", 0)
        self.production_progress = data.get("prod_progress", 0.0)

    @property
    def rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h)


class ReplayNode:
    """Lightweight proxy satisfying _draw_mineral_node_offset attribute requirements."""

    def __init__(self, data):
        self.x = data["x"]
        self.y = data["y"]
        self.remaining = data["remaining"]

    @property
    def depleted(self):
        return self.remaining <= 0

    @property
    def rect(self):
        from settings import MINERAL_NODE_SIZE
        return pygame.Rect(
            self.x - MINERAL_NODE_SIZE, self.y - MINERAL_NODE_SIZE,
            MINERAL_NODE_SIZE * 2, MINERAL_NODE_SIZE * 2,
        )


class ReplayAIPlayer:
    """Proxy AI player providing tinted sprite support for replay rendering."""

    _class_sprites_tinted = False
    _class_tinted_sprites = {}

    def __init__(self, units, buildings, mineral_nodes):
        self.units = units
        self.buildings = buildings
        self.mineral_nodes = mineral_nodes

    def _ensure_tinted_sprites(self):
        if ReplayAIPlayer._class_sprites_tinted:
            return
        ReplayAIPlayer._class_sprites_tinted = True
        from units import Soldier, Tank, Worker
        from buildings import TownCenter, Barracks, Factory
        from utils import tint_surface
        from ai_player import AI_TINT_COLOR
        sprite_map = {
            "soldier": Soldier.sprite,
            "tank": Tank.sprite,
            "worker": Worker.sprite,
            "towncenter": TownCenter.sprite,
            "barracks": Barracks.sprite,
            "factory": Factory.sprite,
        }
        for key, sprite in sprite_map.items():
            if sprite:
                ReplayAIPlayer._class_tinted_sprites[key] = tint_surface(sprite, AI_TINT_COLOR)

    def _get_tinted_sprite(self, entity):
        return ReplayAIPlayer._class_tinted_sprites.get(entity._type)


class _WaveManagerProxy:
    """Minimal wave manager proxy for minimap compatibility."""
    def __init__(self, enemies):
        self.enemies = enemies


class ReplayState:
    """Minimal game state proxy for minimap compatibility during replay."""

    def __init__(self, units, buildings, minerals, enemies, ai_player):
        self.units = units
        self.buildings = buildings
        self.mineral_nodes = minerals
        self.ai_player = ai_player
        self.wave_manager = _WaveManagerProxy(enemies)


class ReplayPlayer:
    """Loads a replay file and provides frame data for playback."""

    def __init__(self, filename):
        self.frames = []
        with open(filename, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.frames.append(json.loads(line))
        if not self.frames:
            raise ValueError(f"Empty replay file: {filename}")
        self.total_time = self.frames[-1]["t"]
        self.elapsed = 0.0
        self.speed = 1.0
        self.frame_index = 0
        self.paused = False

    def update(self, dt):
        """Advance playback time."""
        if self.paused:
            return
        self.elapsed += dt * self.speed
        self.elapsed = max(0, min(self.elapsed, self.total_time))
        # Advance frame index forward
        while (self.frame_index < len(self.frames) - 1
               and self.frames[self.frame_index + 1]["t"] <= self.elapsed):
            self.frame_index += 1
        # Handle backwards seeking
        while self.frame_index > 0 and self.frames[self.frame_index]["t"] > self.elapsed:
            self.frame_index -= 1

    def get_frame(self):
        return self.frames[self.frame_index]

    def adjust_speed(self, delta):
        self.speed = max(0.25, min(self.speed + delta, 100.0))

    def seek_ratio(self, ratio):
        """Seek to a position (0.0 to 1.0) in the replay."""
        self.elapsed = max(0, min(ratio, 1.0)) * self.total_time
        self.frame_index = 0
        while (self.frame_index < len(self.frames) - 1
               and self.frames[self.frame_index + 1]["t"] <= self.elapsed):
            self.frame_index += 1
