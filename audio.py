"""Audio manager for the RTS game using pygame.mixer.

All sound assets are CC0-licensed (Creative Commons Zero / Public Domain):
  - attack.ogg        — Space Shoot Sounds by Robin Lamb (opengameart.org)
  - explosion.ogg     — 100 CC0 SFX by rubberduck (opengameart.org)
  - building_place.ogg— 100 CC0 SFX by rubberduck (opengameart.org)
  - mine.ogg          — 100 CC0 SFX by rubberduck (opengameart.org)
  - select.wav        — Interface Sounds by Kenney (kenney.nl, CC0)
  - click.wav         — Interface Sounds by Kenney (kenney.nl, CC0)
  - victory.wav       — Victory by Ogrebane (opengameart.org, CC0)
  - defeat.ogg        — Game Over Sound by Finnolia (opengameart.org, CC0)
  - music_ambient.ogg — EmptyCity by Danjocross (opengameart.org, CC0)

================================================================================
INTEGRATION GUIDE — calls to add in game.py
================================================================================

1. IMPORT (near top of game.py, after other imports ~line 26):
       from audio import AudioManager

2. INITIALISE (after pygame.init() in main(), ~line 204):
       audio = AudioManager()
       audio.play_music()  # Start background music

3. UNIT SELECTION — single click select (~line 791, after state.select_unit(unit)):
       audio.play_sound('select')

4. BOX SELECTION — drag select (~line 766, after state.select_units(units)):
       audio.play_sound('select')

5. BUILDING SELECTION (~line 802, after state.select_building(building)):
       audio.play_sound('select')

6. BUILDING PLACEMENT — successful placement:
   a) Single-player (~line 582, after state.place_building()):
       if state.place_building((bx, by)):
           audio.play_sound('building_place')
       else:
           resource_flash_timer = 0.5
      (Note: need to invert the existing `if not` check)
   b) Multiplayer (~line 574, after net_session.queue_command for place_building):
       audio.play_sound('building_place')

7. MINING COMMAND — right-click mineral node:
   a) Single-player (~line 717, after state.command_mine(node)):
       audio.play_sound('mine')
   b) Multiplayer (~line 699, after mine command queued):
       audio.play_sound('mine')

8. HUD BUTTON CLICK — in hud.py handle_click(), when a button is clicked:
   (Or simpler: in game.py ~line 526 where result = hud.handle_click(...)):
       result = hud.handle_click(screen_pos, state, ...)
       if result:
           audio.play_sound('click')

9. ATTACK — when a unit fires (in game_state.py update loop ~line 620-622,
   or in units.py try_attack() ~line 138-140):
   Best place: in the rendering loop in game.py where attack lines are drawn,
   since audio is rendering-side. Add near line 1011-1012:
       if unit.attacking and unit.target_enemy:
           audio.play_sound('attack')
   NOTE: To avoid sound spam, AudioManager rate-limits attack sounds to max
   every 150ms automatically.

10. DEATH/EXPLOSION — when a unit or building dies.
    In game_state.py ~line 730-746 (dead unit/building removal), or better,
    in game.py where particles are spawned for deaths. Add when a unit/building
    is removed:
        audio.play_sound('explosion')

11. VICTORY — game over screen (~line 1216):
        if state.game_result == "victory":
            audio.play_sound('victory')
            audio.stop_music()

12. DEFEAT — game over screen (~line 1218):
        else:
            audio.play_sound('defeat')
            audio.stop_music()
    NOTE: Victory/defeat should only play once. Use a flag like:
        if state.game_over and not game_over_sound_played:
            game_over_sound_played = True
            if state.game_result == "victory":
                audio.play_sound('victory')
            else:
                audio.play_sound('defeat')
            audio.stop_music()

13. DISASTER EVENTS (optional, in game.py or disasters.py):
    - Meteor explosion: audio.play_sound('explosion')
    - Lightning strike: audio.play_sound('attack')

================================================================================
"""

import os
import time
import pygame


# Sound file definitions: name -> filename
_SOUND_FILES = {
    'attack':         'attack.ogg',
    'explosion':      'explosion.ogg',
    'building_place': 'building_place.ogg',
    'mine':           'mine.ogg',
    'select':         'select.wav',
    'click':          'click.wav',
    'victory':        'victory.wav',
    'defeat':         'defeat.ogg',
}

_MUSIC_FILE = 'music_ambient.ogg'

# Minimum interval (seconds) between repeated plays of the same sound
# to prevent audio spam (especially for rapid-fire attack sounds)
_RATE_LIMITS = {
    'attack':    0.15,
    'explosion': 0.10,
    'mine':      0.50,
}

_SOUNDS_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'sounds')


class AudioManager:
    """Manages all game audio: sound effects and background music.

    Usage:
        audio = AudioManager()          # Call after pygame.init()
        audio.play_sound('attack')      # Play a one-shot sound effect
        audio.play_music()              # Start looping background music
        audio.stop_music()              # Stop background music
        audio.set_volume(0.5)           # Master volume (0.0 - 1.0)
        audio.set_music_volume(0.3)     # Music volume (0.0 - 1.0)
        audio.set_sfx_volume(0.7)       # Sound effects volume (0.0 - 1.0)

    Handles missing files gracefully — no crashes if assets/sounds/ is incomplete.
    """

    def __init__(self):
        self._sounds = {}
        self._last_play_time = {}  # name -> timestamp of last play
        self._sfx_volume = 0.7
        self._music_volume = 0.3
        self._enabled = True
        self._music_playing = False

        # Initialise mixer if not already done
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            # Reserve channels: 0-7 for SFX, let pygame.mixer.music handle music
            pygame.mixer.set_num_channels(16)
        except pygame.error:
            print("[AudioManager] Warning: pygame.mixer init failed, audio disabled")
            self._enabled = False
            return

        # Load all sound effects
        for name, filename in _SOUND_FILES.items():
            path = os.path.join(_SOUNDS_DIR, filename)
            if os.path.exists(path):
                try:
                    snd = pygame.mixer.Sound(path)
                    snd.set_volume(self._sfx_volume)
                    self._sounds[name] = snd
                except pygame.error as e:
                    print(f"[AudioManager] Warning: Could not load {filename}: {e}")
            else:
                print(f"[AudioManager] Warning: Sound file not found: {path}")

    def play_sound(self, name):
        """Play a named sound effect. Rate-limited to prevent spam."""
        if not self._enabled:
            return
        sound = self._sounds.get(name)
        if not sound:
            return

        # Rate limiting
        now = time.monotonic()
        limit = _RATE_LIMITS.get(name, 0.0)
        if limit > 0:
            last = self._last_play_time.get(name, 0.0)
            if now - last < limit:
                return
        self._last_play_time[name] = now

        sound.play()

    def play_music(self):
        """Start looping background music."""
        if not self._enabled:
            return
        path = os.path.join(_SOUNDS_DIR, _MUSIC_FILE)
        if not os.path.exists(path):
            print(f"[AudioManager] Warning: Music file not found: {path}")
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self._music_volume)
            pygame.mixer.music.play(-1)  # Loop forever
            self._music_playing = True
        except pygame.error as e:
            print(f"[AudioManager] Warning: Could not play music: {e}")

    def stop_music(self):
        """Stop background music with a short fade-out."""
        if not self._enabled:
            return
        try:
            pygame.mixer.music.fadeout(1000)  # 1 second fade
            self._music_playing = False
        except pygame.error:
            pass

    def set_volume(self, volume):
        """Set master volume (0.0 - 1.0). Affects both SFX and music."""
        volume = max(0.0, min(1.0, volume))
        self.set_sfx_volume(volume)
        self.set_music_volume(volume * 0.4)  # Music quieter than SFX

    def set_sfx_volume(self, volume):
        """Set sound effects volume (0.0 - 1.0)."""
        self._sfx_volume = max(0.0, min(1.0, volume))
        for sound in self._sounds.values():
            sound.set_volume(self._sfx_volume)

    def set_music_volume(self, volume):
        """Set music volume (0.0 - 1.0)."""
        self._music_volume = max(0.0, min(1.0, volume))
        if self._enabled:
            try:
                pygame.mixer.music.set_volume(self._music_volume)
            except pygame.error:
                pass

    @property
    def enabled(self):
        return self._enabled

    @property
    def music_playing(self):
        return self._music_playing and self._enabled
