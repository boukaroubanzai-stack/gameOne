"""Natural disaster system: meteor, earthquake, lightning, toxic cloud effects."""

import random
import math
import pygame

# Try to import world dimensions from settings, with fallbacks
try:
    from settings import WORLD_W, WORLD_H
except ImportError:
    try:
        from settings import WIDTH, MAP_HEIGHT
        WORLD_W = WIDTH
        WORLD_H = MAP_HEIGHT
    except ImportError:
        WORLD_W = 2000
        WORLD_H = 1080


class DisasterManager:
    """Manages random natural disasters that affect all units and buildings."""

    def __init__(self, world_w=None, world_h=None):
        self.world_w = world_w if world_w is not None else WORLD_W
        self.world_h = world_h if world_h is not None else WORLD_H
        self.active_disasters = []
        self.disaster_timer = 0.0
        self.next_disaster_time = random.uniform(45, 90)
        self.shake_offset = (0, 0)
        # Track which units/buildings already took one-time damage per disaster
        self._damage_applied = {}
        # Disaster id counter
        self._next_id = 0
        # Reusable drawing surfaces keyed by name
        self._surfaces: dict[str, pygame.Surface] = {}

    def _gen_id(self):
        self._next_id += 1
        return self._next_id

    # ------------------------------------------------------------------
    # Spawning
    # ------------------------------------------------------------------

    def _spawn_random_disaster(self):
        dtype = random.choice(["meteor", "earthquake", "lightning", "toxic_cloud"])
        if dtype == "meteor":
            self._spawn_meteor()
        elif dtype == "earthquake":
            self._spawn_earthquake()
        elif dtype == "lightning":
            self._spawn_lightning()
        elif dtype == "toxic_cloud":
            self._spawn_toxic_cloud()

    def _spawn_meteor(self):
        margin = 150
        x = random.uniform(margin, self.world_w - margin)
        y = random.uniform(margin, self.world_h - margin)
        did = self._gen_id()
        disaster = {
            "type": "meteor",
            "id": did,
            "timer": 0.0,
            "duration": 2.0,
            "x": x,
            "y": y,
            "radius": 150,
            "warning_duration": 0.5,
            "damage": 50,
            "phase": "warning",
            "particles": [],
        }
        self.active_disasters.append(disaster)
        self._damage_applied[did] = set()

    def _spawn_earthquake(self):
        did = self._gen_id()
        disaster = {
            "type": "earthquake",
            "id": did,
            "timer": 0.0,
            "duration": 5.0,
            "x": self.world_w / 2,
            "y": self.world_h / 2,
            "phase": "active",
            "building_damage_applied": False,
            "slowed_units": set(),
            "ripple_radius": 0.0,
        }
        self.active_disasters.append(disaster)

    def _spawn_lightning(self):
        did = self._gen_id()
        disaster = {
            "type": "lightning",
            "id": did,
            "timer": 0.0,
            "duration": 8.0,
            "x": 0,
            "y": 0,
            "phase": "active",
            "strike_timer": 0.0,
            "next_strike": random.uniform(1.0, 2.0),
            "bolts": [],  # list of active bolt visuals
        }
        self.active_disasters.append(disaster)

    def _spawn_toxic_cloud(self):
        margin = 200
        x = random.uniform(margin, self.world_w - margin)
        y = random.uniform(margin, self.world_h - margin)
        angle = random.uniform(0, 2 * math.pi)
        did = self._gen_id()
        disaster = {
            "type": "toxic_cloud",
            "id": did,
            "timer": 0.0,
            "duration": 12.0,
            "x": x,
            "y": y,
            "radius": 200,
            "drift_dx": math.cos(angle) * 20,
            "drift_dy": math.sin(angle) * 20,
            "damage_per_sec": 5,
            "phase": "active",
            "pulse_timer": 0.0,
        }
        self.active_disasters.append(disaster)

    # ------------------------------------------------------------------
    # Per-type update logic
    # ------------------------------------------------------------------

    def _update_meteor(self, d, dt, all_units, all_buildings):
        t = d["timer"]
        if t < d["warning_duration"]:
            d["phase"] = "warning"
        elif t < d["duration"] - 0.3:
            d["phase"] = "active"
            # Apply one-time explosion damage
            dmg_set = self._damage_applied.get(d["id"], set())
            for u in all_units:
                uid = id(u)
                if uid not in dmg_set:
                    ux = getattr(u, "x", None)
                    uy = getattr(u, "y", None)
                    if ux is not None and uy is not None:
                        dist = math.hypot(ux - d["x"], uy - d["y"])
                        if dist <= d["radius"]:
                            hp = getattr(u, "hp", None)
                            if hp is not None:
                                u.hp -= d["damage"]
                            dmg_set.add(uid)
            for b in all_buildings:
                bid = id(b)
                if bid not in dmg_set:
                    bx = getattr(b, "x", None)
                    by = getattr(b, "y", None)
                    if bx is not None and by is not None:
                        dist = math.hypot(bx - d["x"], by - d["y"])
                        if dist <= d["radius"]:
                            hp = getattr(b, "hp", None)
                            if hp is not None:
                                b.hp -= d["damage"]
                            dmg_set.add(bid)
            self._damage_applied[d["id"]] = dmg_set
            # Generate particles
            if len(d["particles"]) < 30:
                for _ in range(3):
                    angle = random.uniform(0, 2 * math.pi)
                    speed = random.uniform(40, 120)
                    d["particles"].append({
                        "x": d["x"],
                        "y": d["y"],
                        "dx": math.cos(angle) * speed,
                        "dy": math.sin(angle) * speed,
                        "life": random.uniform(0.3, 1.0),
                        "max_life": 1.0,
                        "size": random.uniform(3, 8),
                    })
        else:
            d["phase"] = "fading"

        # Update particles
        for p in d["particles"]:
            p["x"] += p["dx"] * dt
            p["y"] += p["dy"] * dt
            p["life"] -= dt
        d["particles"] = [p for p in d["particles"] if p["life"] > 0]

    def _update_earthquake(self, d, dt, all_units, all_buildings):
        d["phase"] = "active"
        t = d["timer"]

        # Screen shake — intensity fades toward the end
        progress = t / d["duration"]
        intensity = max(0, 1.0 - progress) * 8
        sx = random.uniform(-intensity, intensity)
        sy = random.uniform(-intensity, intensity)
        self.shake_offset = (int(sx), int(sy))

        # Ripple radius expands outward
        d["ripple_radius"] = min(t * 300, max(self.world_w, self.world_h))

        # Building damage — apply once
        if not d["building_damage_applied"]:
            for b in all_buildings:
                hp = getattr(b, "hp", None)
                if hp is not None:
                    b.hp -= 10
            d["building_damage_applied"] = True

        # Slow all units by 50% (reduce speed, restore when done)
        for u in all_units:
            uid = id(u)
            if uid not in d["slowed_units"]:
                speed = getattr(u, "speed", None)
                if speed is not None:
                    u._pre_earthquake_speed = u.speed
                    u.speed = u.speed * 0.5
                    d["slowed_units"].add(uid)

    def _update_lightning(self, d, dt, all_units, all_buildings):
        d["phase"] = "active"
        d["strike_timer"] += dt

        # Tick bolt visuals
        for bolt in d["bolts"]:
            bolt["life"] -= dt
        d["bolts"] = [b for b in d["bolts"] if b["life"] > 0]

        # Time for a new strike?
        if d["strike_timer"] >= d["next_strike"]:
            d["strike_timer"] = 0.0
            d["next_strike"] = random.uniform(1.0, 2.0)

            # Pick a target among all units
            if all_units:
                target = random.choice(all_units)
                tx = getattr(target, "x", None)
                ty = getattr(target, "y", None)
                if tx is not None and ty is not None:
                    # Direct hit damage
                    hp = getattr(target, "hp", None)
                    if hp is not None:
                        target.hp -= 40

                    # Splash damage
                    for u in all_units:
                        if u is target:
                            continue
                        ux = getattr(u, "x", None)
                        uy = getattr(u, "y", None)
                        if ux is not None and uy is not None:
                            dist = math.hypot(ux - tx, uy - ty)
                            if dist <= 30:
                                u_hp = getattr(u, "hp", None)
                                if u_hp is not None:
                                    u.hp -= 10

                    # Generate bolt segments for visual
                    segments = self._generate_bolt_segments(tx, ty)
                    d["bolts"].append({
                        "x": tx,
                        "y": ty,
                        "segments": segments,
                        "life": 0.3,
                        "max_life": 0.3,
                    })

    def _generate_bolt_segments(self, target_x, target_y):
        """Create a jagged lightning bolt from top of screen to target."""
        segments = []
        x = target_x + random.uniform(-30, 30)
        y = 0
        steps = random.randint(6, 10)
        step_y = target_y / steps
        for i in range(steps):
            nx = target_x + random.uniform(-20, 20) if i < steps - 1 else target_x
            ny = y + step_y
            segments.append(((x, y), (nx, ny)))
            x, y = nx, ny
        return segments

    def _update_toxic_cloud(self, d, dt, all_units, all_buildings):
        t = d["timer"]
        if t < d["duration"] - 2.0:
            d["phase"] = "active"
        else:
            d["phase"] = "fading"

        # Drift
        d["x"] += d["drift_dx"] * dt
        d["y"] += d["drift_dy"] * dt

        # Clamp to world bounds
        d["x"] = max(0, min(self.world_w, d["x"]))
        d["y"] = max(0, min(self.world_h, d["y"]))

        # Pulse animation
        d["pulse_timer"] += dt

        # Damage per second to units inside
        if d["phase"] == "active":
            damage = d["damage_per_sec"] * dt
            for u in all_units:
                ux = getattr(u, "x", None)
                uy = getattr(u, "y", None)
                if ux is not None and uy is not None:
                    dist = math.hypot(ux - d["x"], uy - d["y"])
                    if dist <= d["radius"]:
                        hp = getattr(u, "hp", None)
                        if hp is not None:
                            u.hp -= damage

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup_disaster(self, d):
        """Restore any state changed by a disaster."""
        if d["type"] == "earthquake":
            # Restore unit speeds
            for uid in d["slowed_units"]:
                # We can't reverse by uid alone; we need the actual objects.
                # This is handled below in a second pass.
                pass
            self.shake_offset = (0, 0)
        # Remove damage tracking
        self._damage_applied.pop(d.get("id"), None)

    def restore_earthquake_speeds(self, all_units):
        """Call after earthquake ends to restore speeds.
        The manager calls this automatically, but it can also be called externally."""
        for u in all_units:
            pre_speed = getattr(u, "_pre_earthquake_speed", None)
            if pre_speed is not None:
                u.speed = pre_speed
                del u._pre_earthquake_speed

    def update(self, dt, all_units, all_buildings):
        """Tick all active disasters and potentially spawn a new one."""
        # Reset shake every frame; earthquake will set it if active
        self.shake_offset = (0, 0)

        # Advance spawn timer
        self.disaster_timer += dt
        if self.disaster_timer >= self.next_disaster_time:
            self.disaster_timer = 0.0
            self.next_disaster_time = random.uniform(45, 90)
            self._spawn_random_disaster()

        # Update each active disaster
        finished = []
        for disaster in self.active_disasters:
            disaster["timer"] += dt
            dtype = disaster["type"]

            if dtype == "meteor":
                self._update_meteor(disaster, dt, all_units, all_buildings)
            elif dtype == "earthquake":
                self._update_earthquake(disaster, dt, all_units, all_buildings)
            elif dtype == "lightning":
                self._update_lightning(disaster, dt, all_units, all_buildings)
            elif dtype == "toxic_cloud":
                self._update_toxic_cloud(disaster, dt, all_units, all_buildings)

            if disaster["timer"] >= disaster["duration"]:
                finished.append(disaster)

        for d in finished:
            # Restore earthquake speeds before removing
            if d["type"] == "earthquake":
                self.restore_earthquake_speeds(all_units)
            self._cleanup_disaster(d)
            self.active_disasters.remove(d)

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def _get_reusable_surface(self, key, w, h):
        """Get or create a reusable SRCALPHA surface, resizing if needed."""
        surf = self._surfaces.get(key)
        if surf is None or surf.get_width() < w or surf.get_height() < h:
            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            self._surfaces[key] = surf
        return surf

    def draw(self, surface, camera_x=0, camera_y=0):
        """Draw all active disaster effects, accounting for camera offset."""
        for d in self.active_disasters:
            dtype = d["type"]
            if dtype == "meteor":
                self._draw_meteor(surface, d, camera_x, camera_y)
            elif dtype == "earthquake":
                self._draw_earthquake(surface, d, camera_x, camera_y)
            elif dtype == "lightning":
                self._draw_lightning(surface, d, camera_x, camera_y)
            elif dtype == "toxic_cloud":
                self._draw_toxic_cloud(surface, d, camera_x, camera_y)

    def _draw_meteor(self, surface, d, cx, cy):
        sx = int(d["x"] - cx)
        sy = int(d["y"] - cy)
        t = d["timer"]

        if d["phase"] == "warning":
            # Growing dark shadow circle + crosshair on single surface
            progress = t / d["warning_duration"]
            radius = int(d["radius"] * progress)
            if radius > 0:
                alpha = int(80 * progress)
                diameter = radius * 2
                warn_surf = self._get_reusable_surface("meteor_warn", diameter, diameter)
                warn_surf.fill((0, 0, 0, 0))
                pygame.draw.circle(warn_surf, (30, 0, 0, alpha), (radius, radius), radius)
                cross_alpha = int(200 * progress)
                pygame.draw.line(warn_surf, (200, 50, 0, cross_alpha), (radius, 0), (radius, diameter), 2)
                pygame.draw.line(warn_surf, (200, 50, 0, cross_alpha), (0, radius), (diameter, radius), 2)
                surface.blit(warn_surf, (sx - radius, sy - radius))

        elif d["phase"] == "active":
            explosion_progress = (t - d["warning_duration"]) / (d["duration"] - d["warning_duration"] - 0.3)
            explosion_progress = min(1.0, max(0.0, explosion_progress))
            radius = int(d["radius"] * (0.3 + 0.7 * explosion_progress))
            alpha = int(180 * (1.0 - explosion_progress))
            if radius > 0:
                diameter = radius * 2
                glow = self._get_reusable_surface("meteor_glow", diameter, diameter)
                glow.fill((0, 0, 0, 0))
                pygame.draw.circle(glow, (255, 100, 0, alpha), (radius, radius), radius)
                core_r = max(1, int(radius * 0.4))
                pygame.draw.circle(glow, (255, 220, 50, min(255, alpha + 50)), (radius, radius), core_r)
                surface.blit(glow, (sx - radius, sy - radius))

        elif d["phase"] == "fading":
            fade_progress = (t - (d["duration"] - 0.3)) / 0.3
            fade_progress = min(1.0, max(0.0, fade_progress))
            radius = int(d["radius"] * (1.0 - fade_progress * 0.3))
            alpha = int(120 * (1.0 - fade_progress))
            if alpha > 0 and radius > 0:
                diameter = radius * 2
                glow = self._get_reusable_surface("meteor_fade", diameter, diameter)
                glow.fill((0, 0, 0, 0))
                pygame.draw.circle(glow, (200, 60, 0, alpha), (radius, radius), radius)
                surface.blit(glow, (sx - radius, sy - radius))

        # Draw particles directly
        for p in d["particles"]:
            px = int(p["x"] - cx)
            py = int(p["y"] - cy)
            life_ratio = max(0, p["life"] / p["max_life"])
            size = max(1, int(p["size"] * life_ratio))
            r = min(255, 200 + int(55 * random.random()))
            g = int(120 * life_ratio)
            pygame.draw.circle(surface, (r, g, 0), (px, py), size)

    def _draw_earthquake(self, surface, d, cx, cy):
        # Brown/grey ripple expanding outward
        progress = d["timer"] / d["duration"]
        ripple_r = int(d["ripple_radius"])
        if ripple_r <= 0:
            return
        center_x = int(d["x"] - cx)
        center_y = int(d["y"] - cy)
        alpha = int(50 * (1.0 - progress))
        if alpha <= 0:
            return
        # Draw all 3 ripple rings onto a single surface
        max_r = ripple_r
        max_thickness = 4
        surf_size = max_r * 2 + max_thickness * 2
        if surf_size <= 0:
            return
        ring_surf = self._get_reusable_surface("eq_rings", surf_size, surf_size)
        ring_surf.fill((0, 0, 0, 0))
        center = surf_size // 2
        for i in range(3):
            r = max(1, ripple_r - i * 60)
            if r <= 0:
                continue
            ring_alpha = max(0, alpha - i * 15)
            if ring_alpha <= 0:
                continue
            thickness = max(1, 4 - i)
            pygame.draw.circle(ring_surf, (140, 120, 80, ring_alpha), (center, center), r, thickness)
        surface.blit(ring_surf, (center_x - center, center_y - center))

    def _draw_lightning(self, surface, d, cx, cy):
        for bolt in d["bolts"]:
            life_ratio = max(0, bolt["life"] / bolt["max_life"])
            # Flash overlay — reuse a single cached full-screen surface
            if life_ratio > 0.7:
                sw, sh = surface.get_size()
                flash = self._get_reusable_surface("lightning_flash", sw, sh)
                flash_alpha = int(40 * (life_ratio - 0.7) / 0.3)
                flash.fill((255, 255, 255, flash_alpha))
                surface.blit(flash, (0, 0))

            # Draw bolt segments directly
            for seg in bolt["segments"]:
                p1 = (int(seg[0][0] - cx), int(seg[0][1] - cy))
                p2 = (int(seg[1][0] - cx), int(seg[1][1] - cy))
                pygame.draw.line(surface, (180, 180, 255), p1, p2, 5)
                pygame.draw.line(surface, (255, 255, 255), p1, p2, 2)

            # Strike point glow
            bx = int(bolt["x"] - cx)
            by = int(bolt["y"] - cy)
            glow_r = int(30 * life_ratio)
            if glow_r > 0:
                diameter = glow_r * 2
                glow = self._get_reusable_surface("lightning_glow", diameter, diameter)
                glow.fill((0, 0, 0, 0))
                pygame.draw.circle(glow, (200, 200, 255, int(150 * life_ratio)), (glow_r, glow_r), glow_r)
                surface.blit(glow, (bx - glow_r, by - glow_r))

    def _draw_toxic_cloud(self, surface, d, cx, cy):
        sx = int(d["x"] - cx)
        sy = int(d["y"] - cy)
        base_radius = d["radius"]

        # Pulse effect
        pulse = math.sin(d["pulse_timer"] * 2.5) * 0.1  # +/-10% size
        radius = int(base_radius * (1.0 + pulse))

        # Fade alpha based on phase
        if d["phase"] == "fading":
            fade_t = d["timer"] - (d["duration"] - 2.0)
            alpha_mult = max(0, 1.0 - fade_t / 2.0)
        else:
            alpha_mult = min(1.0, d["timer"] / 1.0)

        base_alpha = int(70 * alpha_mult)
        if base_alpha <= 0 or radius <= 0:
            return

        # Draw cloud layers + wisps onto a single reusable surface
        wisp_r = max(1, int(radius * 0.25))
        total_size = (radius + wisp_r) * 2
        cloud_surf = self._get_reusable_surface("toxic_cloud", total_size, total_size)
        cloud_surf.fill((0, 0, 0, 0))
        center = total_size // 2
        for i in range(4):
            layer_r = max(1, radius - i * 30)
            layer_alpha = min(255, base_alpha + i * 15)
            g = 150 + i * 25
            b_val = 50 - i * 10
            pygame.draw.circle(cloud_surf, (80, min(255, g), max(0, b_val), layer_alpha),
                               (center, center), layer_r)

        # Edge wisps
        wisp_alpha = int(40 * alpha_mult)
        if wisp_alpha > 0:
            num_wisps = 6
            for i in range(num_wisps):
                angle = (d["pulse_timer"] * 0.5 + i * (2 * math.pi / num_wisps))
                wisp_dist = radius * 0.8
                wx = center + int(math.cos(angle) * wisp_dist)
                wy = center + int(math.sin(angle) * wisp_dist)
                pygame.draw.circle(cloud_surf, (100, 200, 50, wisp_alpha), (wx, wy), wisp_r)

        surface.blit(cloud_surf, (sx - center, sy - center))

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def has_active_disaster(self, dtype=None):
        """Check if any disaster (or a specific type) is currently active."""
        if dtype is None:
            return len(self.active_disasters) > 0
        return any(d["type"] == dtype for d in self.active_disasters)

    def force_disaster(self, dtype):
        """Force spawn a specific disaster type (useful for testing)."""
        if dtype == "meteor":
            self._spawn_meteor()
        elif dtype == "earthquake":
            self._spawn_earthquake()
        elif dtype == "lightning":
            self._spawn_lightning()
        elif dtype == "toxic_cloud":
            self._spawn_toxic_cloud()
