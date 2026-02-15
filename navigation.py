"""Navigation grid with A* pathfinding, path smoothing, and terrain generation."""

import heapq
import random
from settings import WORLD_W, WORLD_H, NAV_TILE_SIZE, PLAYER_TC_POS, AI_TC_POS, MINERAL_OFFSETS


GRID_W = WORLD_W // NAV_TILE_SIZE  # 312
GRID_H = WORLD_H // NAV_TILE_SIZE  # 168

# Tile values
WALKABLE = 0
TERRAIN = 1
BUILDING = 2

# 8 directions: (dx, dy, cost*10) — use x10 integer costs for determinism
#   cardinal = 10, diagonal = 14 (approx sqrt(2)*10)
_DIRS = [
    (1, 0, 10), (-1, 0, 10), (0, 1, 10), (0, -1, 10),
    (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14),
]

_MAX_EXPANSIONS = 10000


class NavGrid:
    def __init__(self):
        self.grid = bytearray(GRID_W * GRID_H)
        self._static_grid = bytearray(GRID_W * GRID_H)
        self.terrain_rects = []  # [(x, y, w, h)] world coords for rendering

    # --- Grid access ---

    def _idx(self, gx, gy):
        return gy * GRID_W + gx

    def get(self, gx, gy):
        if 0 <= gx < GRID_W and 0 <= gy < GRID_H:
            return self.grid[self._idx(gx, gy)]
        return TERRAIN  # out of bounds = blocked

    def _set(self, gx, gy, val):
        if 0 <= gx < GRID_W and 0 <= gy < GRID_H:
            self.grid[self._idx(gx, gy)] = val

    # --- World <-> grid conversion ---

    @staticmethod
    def world_to_grid(wx, wy):
        return int(wx) // NAV_TILE_SIZE, int(wy) // NAV_TILE_SIZE

    @staticmethod
    def grid_to_world(gx, gy):
        return gx * NAV_TILE_SIZE + NAV_TILE_SIZE // 2, gy * NAV_TILE_SIZE + NAV_TILE_SIZE // 2

    # --- Building mark/unmark ---

    def _tile_range(self, x, y, w, h, pad=0):
        """Convert world rect to grid tile range, clamped to grid bounds. Always returns ints."""
        x1 = int(max(0, int(x - pad) // NAV_TILE_SIZE))
        y1 = int(max(0, int(y - pad) // NAV_TILE_SIZE))
        x2 = int(min(GRID_W - 1, int(x + w + pad) // NAV_TILE_SIZE))
        y2 = int(min(GRID_H - 1, int(y + h + pad) // NAV_TILE_SIZE))
        return x1, y1, x2, y2

    def mark_building(self, building):
        """Mark tiles under a building as BUILDING (with padding for unit radius)."""
        x1, y1, x2, y2 = self._tile_range(building.x, building.y, building.w, building.h, pad=20)
        for gy in range(y1, y2 + 1):
            for gx in range(x1, x2 + 1):
                self._set(gx, gy, BUILDING)

    def unmark_building(self, building):
        """Restore tiles under a building to their static terrain state."""
        x1, y1, x2, y2 = self._tile_range(building.x, building.y, building.w, building.h, pad=20)
        for gy in range(y1, y2 + 1):
            for gx in range(x1, x2 + 1):
                idx = self._idx(gx, gy)
                self.grid[idx] = self._static_grid[idx]

    # --- Terrain validation for building placement ---

    def is_rect_clear(self, x, y, w, h):
        """Check if a world-space rectangle is free of terrain obstacles."""
        x1, y1, x2, y2 = self._tile_range(x, y, w, h)
        for gy in range(y1, y2 + 1):
            for gx in range(x1, x2 + 1):
                if self._static_grid[self._idx(gx, gy)] == TERRAIN:
                    return False
        return True

    # --- Terrain generation ---

    def generate_terrain(self, seed):
        """Generate mirror-symmetric terrain obstacles. Returns list of (x,y,w,h) rects."""
        rng = random.Random(seed)

        # Exclusion zones (world coords): 600px around TCs, mineral positions
        exclusions = []
        exclusions.append((PLAYER_TC_POS[0], PLAYER_TC_POS[1], 600))
        exclusions.append((AI_TC_POS[0], AI_TC_POS[1], 600))
        for dx, dy in MINERAL_OFFSETS:
            mx = PLAYER_TC_POS[0] + dx
            my = PLAYER_TC_POS[1] + dy
            exclusions.append((mx, my, 200))
            mx2 = AI_TC_POS[0] - dx
            my2 = AI_TC_POS[1] + dy
            exclusions.append((mx2, my2, 200))

        def in_exclusion(rx, ry, rw, rh):
            # Check if rect center is within any exclusion circle
            cx, cy = rx + rw // 2, ry + rh // 2
            for ex, ey, er in exclusions:
                if (cx - ex) ** 2 + (cy - ey) ** 2 < (er + max(rw, rh) // 2) ** 2:
                    return True
            return False

        rects = []
        num_clusters = rng.randint(8, 15)
        half_w = WORLD_W // 2

        for _ in range(num_clusters):
            # Generate cluster in left half
            cx = rng.randint(200, half_w - 200)
            cy = rng.randint(200, WORLD_H - 200)
            num_rects = rng.randint(1, 4)

            for _ in range(num_rects):
                w = rng.randint(64, 256)
                h = rng.randint(64, 192)
                # Offset from cluster center
                ox = rng.randint(-100, 100)
                oy = rng.randint(-100, 100)
                rx = max(0, min(cx + ox - w // 2, half_w - w))
                ry = max(0, min(cy + oy - h // 2, WORLD_H - h))

                if not in_exclusion(rx, ry, w, h):
                    rects.append((rx, ry, w, h))
                    # Mirror to right half
                    mirror_x = WORLD_W - rx - w
                    rects.append((mirror_x, ry, w, h))

        # Mark terrain on grid
        for rx, ry, rw, rh in rects:
            gx1 = max(0, rx // NAV_TILE_SIZE)
            gy1 = max(0, ry // NAV_TILE_SIZE)
            gx2 = min(GRID_W - 1, (rx + rw) // NAV_TILE_SIZE)
            gy2 = min(GRID_H - 1, (ry + rh) // NAV_TILE_SIZE)
            for gy in range(gy1, gy2 + 1):
                for gx in range(gx1, gx2 + 1):
                    self._set(gx, gy, TERRAIN)

        # Connectivity check: BFS from player TC to AI TC
        pg = self.world_to_grid(PLAYER_TC_POS[0] + 32, PLAYER_TC_POS[1] + 32)
        ag = self.world_to_grid(AI_TC_POS[0] + 32, AI_TC_POS[1] + 32)
        if not self._bfs_connected(pg, ag):
            # Remove obstacles until connected
            while rects and not self._bfs_connected(pg, ag):
                # Remove last pair (one + its mirror)
                rects.pop()
                if rects:
                    rects.pop()
                # Rebuild grid
                self.grid = bytearray(GRID_W * GRID_H)
                for rx, ry, rw, rh in rects:
                    gx1 = max(0, rx // NAV_TILE_SIZE)
                    gy1 = max(0, ry // NAV_TILE_SIZE)
                    gx2 = min(GRID_W - 1, (rx + rw) // NAV_TILE_SIZE)
                    gy2 = min(GRID_H - 1, (ry + rh) // NAV_TILE_SIZE)
                    for gy in range(gy1, gy2 + 1):
                        for gx in range(gx1, gx2 + 1):
                            self._set(gx, gy, TERRAIN)

        # Save static grid (terrain only, no buildings yet)
        self._static_grid[:] = self.grid
        self.terrain_rects = rects
        return rects

    def _bfs_connected(self, start, goal):
        """Check if start and goal grid cells are connected via walkable tiles."""
        if self.get(start[0], start[1]) != WALKABLE or self.get(goal[0], goal[1]) != WALKABLE:
            return False
        visited = set()
        visited.add(start)
        queue = [start]
        qi = 0
        while qi < len(queue):
            cx, cy = queue[qi]
            qi += 1
            if (cx, cy) == goal:
                return True
            for dx, dy, _ in _DIRS:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) not in visited and 0 <= nx < GRID_W and 0 <= ny < GRID_H:
                    if self.get(nx, ny) == WALKABLE:
                        visited.add((nx, ny))
                        queue.append((nx, ny))
        return False

    # --- A* pathfinding ---

    def find_path(self, sx, sy, gx, gy):
        """A* from world coords (sx,sy) to (gx,gy). Returns list of world coord waypoints.
        Returns None if no path found. Returns partial path if max expansions exceeded."""
        start = self.world_to_grid(sx, sy)
        goal = self.world_to_grid(gx, gy)

        # If start is blocked, find nearest walkable
        if self.get(start[0], start[1]) != WALKABLE:
            start = self._nearest_walkable(start[0], start[1])
            if start is None:
                return None

        # If goal is blocked, find nearest walkable to goal
        if self.get(goal[0], goal[1]) != WALKABLE:
            goal = self._nearest_walkable(goal[0], goal[1])
            if goal is None:
                return None

        if start == goal:
            return [(gx, gy)]

        # A* with octile distance heuristic (x10 integer math)
        open_heap = []  # (f_cost, counter, gx, gy)
        counter = 0
        g_cost = {start: 0}
        came_from = {start: None}
        best_h = _octile_dist(start[0], start[1], goal[0], goal[1])
        best_node = start

        h = _octile_dist(start[0], start[1], goal[0], goal[1])
        heapq.heappush(open_heap, (h, counter, start[0], start[1]))
        counter += 1

        expansions = 0
        while open_heap and expansions < _MAX_EXPANSIONS:
            f, _, cx, cy = heapq.heappop(open_heap)
            current = (cx, cy)

            if current == goal:
                return self._reconstruct_path(came_from, goal, gx, gy)

            cur_g = g_cost.get(current)
            if cur_g is None:
                continue
            # Skip stale entries
            if f > cur_g + _octile_dist(cx, cy, goal[0], goal[1]) + 1:
                continue

            expansions += 1

            for dx, dy, cost in _DIRS:
                nx, ny = cx + dx, cy + dy
                if nx < 0 or nx >= GRID_W or ny < 0 or ny >= GRID_H:
                    continue
                if self.grid[ny * GRID_W + nx] != WALKABLE:
                    continue
                # No diagonal corner-cutting
                if dx != 0 and dy != 0:
                    if self.grid[cy * GRID_W + (cx + dx)] != WALKABLE:
                        continue
                    if self.grid[(cy + dy) * GRID_W + cx] != WALKABLE:
                        continue

                new_g = cur_g + cost
                neighbor = (nx, ny)
                old_g = g_cost.get(neighbor)
                if old_g is None or new_g < old_g:
                    g_cost[neighbor] = new_g
                    h = _octile_dist(nx, ny, goal[0], goal[1])
                    heapq.heappush(open_heap, (new_g + h, counter, nx, ny))
                    counter += 1
                    came_from[neighbor] = current
                    if h < best_h:
                        best_h = h
                        best_node = neighbor

        # Partial path to closest node
        if best_node != start:
            return self._reconstruct_path(came_from, best_node, gx, gy)
        return None

    def _nearest_walkable(self, gx, gy):
        """Find nearest walkable tile to (gx, gy) via expanding rings."""
        for r in range(1, 20):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if abs(dx) != r and abs(dy) != r:
                        continue
                    nx, ny = gx + dx, gy + dy
                    if 0 <= nx < GRID_W and 0 <= ny < GRID_H:
                        if self.grid[ny * GRID_W + nx] == WALKABLE:
                            return (nx, ny)
        return None

    def _reconstruct_path(self, came_from, end, final_wx, final_wy):
        """Reconstruct and smooth the A* path, ending at exact world coords."""
        path = []
        node = end
        while node is not None:
            path.append(node)
            node = came_from[node]
        path.reverse()

        # Smooth path (greedy pull-string)
        smoothed = [path[0]]
        i = 0
        while i < len(path) - 1:
            # Find farthest visible node from path[i]
            farthest = i + 1
            for j in range(len(path) - 1, i, -1):
                if self._line_of_sight(path[i][0], path[i][1], path[j][0], path[j][1]):
                    farthest = j
                    break
            smoothed.append(path[farthest])
            i = farthest

        # Convert to world coords
        waypoints = []
        for gi, (gx, gy) in enumerate(smoothed):
            if gi == len(smoothed) - 1:
                # Last waypoint: use exact destination
                waypoints.append((final_wx, final_wy))
            elif gi > 0:  # skip start position
                wx, wy = self.grid_to_world(gx, gy)
                waypoints.append((wx, wy))

        return waypoints if waypoints else [(final_wx, final_wy)]

    def _line_of_sight(self, x0, y0, x1, y1):
        """Bresenham's line check on the grid. Returns True if clear."""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x1 > x0 else -1
        sy = 1 if y1 > y0 else -1
        err = dx - dy
        cx, cy = x0, y0

        while True:
            if self.get(cx, cy) != WALKABLE:
                return False
            if cx == x1 and cy == y1:
                return True
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                cx += sx
            if e2 < dx:
                err += dx
                cy += sy


def _octile_dist(x0, y0, x1, y1):
    """Octile distance heuristic (x10 integer)."""
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    return 10 * (dx + dy) + (14 - 20) * min(dx, dy)
