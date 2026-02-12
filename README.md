# GameOne

Real-Time Strategy game built with Pygame. Mine resources, build a base, train an army, and destroy your opponent.

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
python game.py --host                              # Host a multiplayer game (port 7777)
python game.py --host 9999                         # Host on custom port
python game.py --join 192.168.1.5                  # Join a hosted game
python game.py --join 192.168.1.5 9999             # Join on custom port
```

### Options

| Flag | Description |
|------|-------------|
| `--ai <name>` | Select AI opponent profile. Available: `basic` (default), `defensive`, `aggressive`. Profiles are defined in `ai_profiles/`. |
| `--playforme` | Spectator mode where an AI controls the player side. |
| `--replay <file>` | Load and play back a recorded game replay. Controls: Space (pause), +/- (speed), click timeline to seek, ESC (quit). |
| `--host [port]` | Host a multiplayer game. Attempts UPnP port mapping. Default port: 7777. |
| `--join <ip> [port]` | Join a hosted multiplayer game at the given IP address. Default port: 7777. |

## Multiplayer

Peer-to-peer TCP/IP multiplayer for 2 players. One player hosts, the other connects using the host's IP address.

- The host plays the left side (green), the joiner plays the right side (orange)
- Both players share the same game simulation via lockstep command synchronization
- UPnP is attempted automatically; if it fails, the host may need to manually forward the port
