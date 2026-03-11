"""Map file save/load module for RTS game maps."""

import json
import os

from settings import (
    WORLD_W, WORLD_H,
    PLAYER_TC_POS, AI_TC_POS,
    MINERAL_OFFSETS, MINERAL_NODE_AMOUNT,
    STARTING_RESOURCES, STARTING_WORKERS,
)

# Required top-level fields and their expected types
_REQUIRED_FIELDS = {
    "version": int,
    "name": str,
    "world_size": list,
    "terrain_rects": list,
    "starting_positions": dict,
}

# Optional fields with default values
_OPTIONAL_DEFAULTS = {
    "author": "",
    "mineral_amount": MINERAL_NODE_AMOUNT,
    "symmetry": "mirror_x",
}


def default_map_data():
    """Return default map data matching the current hardcoded layout."""
    return {
        "version": 1,
        "name": "Default",
        "author": "",
        "world_size": [WORLD_W, WORLD_H],
        "terrain_rects": [],
        "starting_positions": {
            "player": {
                "tc_pos": list(PLAYER_TC_POS),
                "mineral_offsets": [list(o) for o in MINERAL_OFFSETS],
                "starting_resources": STARTING_RESOURCES,
                "starting_workers": STARTING_WORKERS,
            },
            "ai": {
                "tc_pos": list(AI_TC_POS),
                "mineral_offsets": [list(o) for o in MINERAL_OFFSETS],
                "starting_resources": STARTING_RESOURCES,
                "starting_workers": STARTING_WORKERS,
            },
        },
        "mineral_amount": MINERAL_NODE_AMOUNT,
        "symmetry": "mirror_x",
    }


def save_map(filepath, map_data):
    """Save map data to a JSON file. Creates parent directories if needed."""
    dirpath = os.path.dirname(filepath)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(map_data, f, indent=2)
        f.write("\n")


def load_map(filepath):
    """Load a map from a JSON file. Validates required fields and fills defaults."""
    with open(filepath, "r") as f:
        data = json.load(f)
    validate_map(data)
    # Fill optional defaults
    for key, default in _OPTIONAL_DEFAULTS.items():
        if key not in data:
            data[key] = default
    return data


def validate_map(data):
    """Validate map data structure and contents.

    Raises ValueError with a descriptive message on invalid data.
    """
    if not isinstance(data, dict):
        raise ValueError("Map data must be a dict")

    # Check required fields and types
    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
        if not isinstance(data[field], expected_type):
            raise ValueError(
                f"Field '{field}' must be {expected_type.__name__}, "
                f"got {type(data[field]).__name__}"
            )

    # Validate version
    if data["version"] != 1:
        raise ValueError(f"Unsupported map version: {data['version']}")

    # Validate world_size
    ws = data["world_size"]
    if len(ws) != 2 or not all(isinstance(v, (int, float)) and v > 0 for v in ws):
        raise ValueError("world_size must be [width, height] with positive values")

    # Validate terrain_rects
    for i, rect in enumerate(data["terrain_rects"]):
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise ValueError(f"terrain_rects[{i}] must be [x, y, w, h]")
        if not all(isinstance(v, (int, float)) for v in rect):
            raise ValueError(f"terrain_rects[{i}] values must be numbers")

    # Validate starting_positions
    sp = data["starting_positions"]
    for team in ("player", "ai"):
        if team not in sp:
            raise ValueError(f"starting_positions missing '{team}'")
        team_data = sp[team]
        if not isinstance(team_data, dict):
            raise ValueError(f"starting_positions.{team} must be a dict")
        if "tc_pos" not in team_data:
            raise ValueError(f"starting_positions.{team} missing 'tc_pos'")
        tc = team_data["tc_pos"]
        if not isinstance(tc, (list, tuple)) or len(tc) != 2:
            raise ValueError(f"starting_positions.{team}.tc_pos must be [x, y]")

        # Fill team-level defaults
        if "mineral_offsets" not in team_data:
            team_data["mineral_offsets"] = [list(o) for o in MINERAL_OFFSETS]
        if "starting_resources" not in team_data:
            team_data["starting_resources"] = STARTING_RESOURCES
        if "starting_workers" not in team_data:
            team_data["starting_workers"] = STARTING_WORKERS

    # Check terrain rects don't overlap TC positions
    for rect in data["terrain_rects"]:
        rx, ry, rw, rh = rect
        for team in ("player", "ai"):
            tc = sp[team]["tc_pos"]
            tx, ty = tc[0], tc[1]
            # TC is 64x64 — check if terrain rect overlaps the TC footprint
            if (rx < tx + 64 and rx + rw > tx and
                    ry < ty + 64 and ry + rh > ty):
                raise ValueError(
                    f"Terrain rect [{rx}, {ry}, {rw}, {rh}] overlaps "
                    f"{team} Town Center at {tc}"
                )
