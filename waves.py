import random
from units import Yanuses
from settings import (
    WIDTH, MAP_HEIGHT,
    TOTAL_WAVES, FIRST_WAVE_DELAY, WAVE_INTERVAL, YANUSES_PER_WAVE, YANUSES_SIZE,
)


class WaveManager:
    def __init__(self):
        self.current_wave = 0  # next wave to spawn (0-indexed)
        self.waves_completed = 0
        self.wave_timer = 0.0
        self.wave_delay = FIRST_WAVE_DELAY  # 60s before first wave
        self.enemies = []
        self.wave_active = False  # True when enemies from current wave are alive

    def spawn_wave(self):
        """Spawn a group of Yanuses at the bottom of the map. Each wave adds one more enemy."""
        count = YANUSES_PER_WAVE + self.current_wave  # wave 0 = 3, wave 1 = 4, etc.
        margin = YANUSES_SIZE * 2
        spacing = 60
        # Center the group horizontally
        start_x = random.randint(margin + 100, WIDTH - margin - 100)
        y = MAP_HEIGHT - margin
        for i in range(count):
            x = start_x + (i - count // 2) * spacing
            x = max(margin, min(x, WIDTH - margin))
            enemy = Yanuses(x, y)
            self.enemies.append(enemy)
        self.wave_active = True
        self.current_wave += 1

    def update(self, dt, player_units, buildings):
        """Update wave timer, spawn waves, update enemies, remove dead."""
        # Remove dead enemies
        self.enemies = [e for e in self.enemies if e.alive]

        # Check if current wave is cleared
        if self.wave_active and not self.enemies:
            self.waves_completed += 1
            self.wave_active = False
            self.wave_timer = 0.0

        # Spawn next wave
        if not self.wave_active and self.current_wave < TOTAL_WAVES:
            self.wave_timer += dt
            if self.wave_timer >= self.wave_delay:
                self.spawn_wave()
                self.wave_delay = WAVE_INTERVAL  # subsequent waves use normal interval

        # Update enemy AI
        for enemy in self.enemies:
            enemy.ai_update(dt, player_units, buildings)

    def is_victory(self):
        """Player wins when all 10 waves are completed and no enemies remain."""
        return self.waves_completed >= TOTAL_WAVES and not self.enemies

    def is_defeat(self, player_units, buildings):
        """Player loses when they have no units and no buildings left."""
        alive_units = [u for u in player_units if u.alive]
        alive_buildings = [b for b in buildings if b.hp > 0]
        return not alive_units and not alive_buildings
