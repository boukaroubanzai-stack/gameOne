# GameOne

Real-Time Strategy game built with Pygame. Mine resources, build a base, train an army, and destroy the AI opponent.

## Install

```bash
pip install -r requirements.txt
```

## Command Line

```bash
python game.py                                    # Normal game (basic AI)
python game.py --ai <name>                        # Select AI profile (basic, defensive, aggressive)
python game.py --playforme                         # Spectator mode: AI controls the player side
python game.py --replay replay/replay_file.json    # Replay viewer
```

### Options

| Flag | Description |
|------|-------------|
| `--ai <name>` | Select AI opponent profile. Available: `basic` (default), `defensive`, `aggressive`. Profiles are defined in `ai_profiles/`. |
| `--playforme` | Spectator mode where an AI controls the player side. |
| `--replay <file>` | Load and play back a recorded game replay. Controls: Space (pause), +/- (speed), click timeline to seek, ESC (quit). |
