"""Heads-up display: resource counter, build buttons, unit/building info panel."""

import pygame
import settings
from utils import get_font
from units import Worker
from settings import (
    HUD_HEIGHT,
    HUD_BG, HUD_TEXT, BUTTON_COLOR, BUTTON_HOVER, BUTTON_TEXT,
    BARRACKS_COST, FACTORY_COST, TOWN_CENTER_COST, TOWER_COST, WATCHGUARD_COST, RADAR_COST,
    SOLDIER_COST, SCOUT_COST, TANK_COST, WORKER_COST,
    TOTAL_WAVES, FIRST_WAVE_DELAY, WAVE_INTERVAL,
)

# Accent colors for HUD buttons
BARRACKS_ACCENT = (140, 90, 50)
FACTORY_ACCENT = (90, 90, 120)
TOWN_CENTER_ACCENT = (60, 140, 60)
SOLDIER_ACCENT = (50, 120, 220)
TANK_ACCENT = (100, 100, 100)
WORKER_ACCENT = (180, 140, 60)
TOWER_ACCENT = (120, 120, 140)
WATCHGUARD_ACCENT = (140, 110, 60)
RADAR_ACCENT = (100, 160, 100)
SCOUT_ACCENT = (0, 180, 180)


class HUD:
    def __init__(self):
        self.buttons = {}
        self._init_buttons()

    @property
    def font(self):
        return get_font(24)

    @property
    def small_font(self):
        return get_font(18)

    def resize(self):
        self._init_buttons()

    def _init_buttons(self):
        btn_w, btn_h = 100, 36
        y = settings.MAP_HEIGHT + 15
        self.buttons = {
            "towncenter": pygame.Rect(280, y, btn_w, btn_h),
            "barracks": pygame.Rect(390, y, btn_w, btn_h),
            "factory": pygame.Rect(500, y, btn_w, btn_h),
            "tower": pygame.Rect(610, y, btn_w, btn_h),
            "watchguard": pygame.Rect(720, y, btn_w, btn_h),
            "radar": pygame.Rect(830, y, btn_w, btn_h),
            "train": pygame.Rect(940, y, 120, btn_h),
            "train_scout": pygame.Rect(1070, y, 120, btn_h),
        }

    def handle_click(self, pos, game_state, net_session=None, local_team="player"):
        if not self.is_in_hud(pos):
            return False

        has_worker = any(isinstance(u, Worker) for u in game_state.selected_units)
        if self.buttons["towncenter"].collidepoint(pos):
            if has_worker:
                game_state.placement_mode = "towncenter"
            return True
        if self.buttons["barracks"].collidepoint(pos):
            if has_worker:
                game_state.placement_mode = "barracks"
            return True
        if self.buttons["factory"].collidepoint(pos):
            if has_worker:
                game_state.placement_mode = "factory"
            return True
        if self.buttons["tower"].collidepoint(pos):
            if has_worker:
                game_state.placement_mode = "tower"
            return True
        if self.buttons["watchguard"].collidepoint(pos):
            if has_worker:
                game_state.placement_mode = "watchguard"
            return True
        if self.buttons["radar"].collidepoint(pos):
            if has_worker:
                game_state.placement_mode = "radar"
            return True
        if self.buttons["train"].collidepoint(pos):
            if game_state.selected_building:
                if net_session:
                    local_rm = game_state.resource_manager if local_team == "player" else game_state.ai_player.resource_manager
                    try:
                        _, cost, _ = game_state.selected_building.can_train()
                        if local_rm.can_afford(cost):
                            net_session.queue_command({
                                "cmd": "train_unit",
                                "building_id": game_state.selected_building.net_id,
                            })
                        else:
                            return "insufficient_funds"
                    except (NotImplementedError, TypeError):
                        return "insufficient_funds"
                else:
                    success = game_state.selected_building.start_production(game_state.resource_manager)
                    if not success:
                        return "insufficient_funds"
            return True
        if self.buttons["train_scout"].collidepoint(pos):
            from buildings import Barracks
            sb = game_state.selected_building
            if sb and isinstance(sb, Barracks):
                if net_session:
                    local_rm = game_state.resource_manager if local_team == "player" else game_state.ai_player.resource_manager
                    _, cost, _ = sb.can_train_scout()
                    if local_rm.can_afford(cost):
                        net_session.queue_command({
                            "cmd": "train_scout",
                            "building_id": sb.net_id,
                        })
                    else:
                        return "insufficient_funds"
                else:
                    success = sb.start_production_scout(game_state.resource_manager)
                    if not success:
                        return "insufficient_funds"
            return True
        return True

    def is_in_hud(self, pos):
        return pos[1] >= settings.MAP_HEIGHT

    def draw(self, surface, game_state, resource_flash_timer=0.0, local_team="player"):
        mouse_pos = pygame.mouse.get_pos()

        # HUD background
        hud_rect = pygame.Rect(0, settings.MAP_HEIGHT, settings.WIDTH, HUD_HEIGHT)
        pygame.draw.rect(surface, HUD_BG, hud_rect)
        pygame.draw.line(surface, (80, 80, 80), (0, settings.MAP_HEIGHT), (settings.WIDTH, settings.MAP_HEIGHT), 2)

        # Resources (flash red when insufficient funds)
        local_rm = game_state.resource_manager if local_team == "player" else game_state.ai_player.resource_manager
        res_text = f"Resources: {int(local_rm.amount)}"
        if resource_flash_timer > 0:
            # Flash between red and gold
            flash = int(resource_flash_timer * 10) % 2 == 0
            res_color = (255, 60, 60) if flash else (255, 215, 0)
        else:
            res_color = (255, 215, 0)
        surface.blit(self.font.render(res_text, True, res_color),
                     (15, settings.MAP_HEIGHT + 10))

        # Wave info + countdown timer
        wm = game_state.wave_manager
        wave_text = f"Wave: {wm.waves_completed}/{TOTAL_WAVES}"
        surface.blit(self.font.render(wave_text, True, (200, 200, 255)),
                     (15, settings.MAP_HEIGHT + 34))
        if not wm.wave_active and wm.current_wave < TOTAL_WAVES:
            # Show countdown to next wave
            remaining = wm.wave_delay - wm.wave_timer
            if remaining > 0:
                mins = int(remaining) // 60
                secs = int(remaining) % 60
                countdown_text = f"Next wave in: {mins}:{secs:02d}"
                countdown_color = (255, 200, 100) if remaining > 10 else (255, 80, 80)
                surface.blit(self.small_font.render(countdown_text, True, countdown_color),
                             (15, settings.MAP_HEIGHT + 56))
            else:
                surface.blit(self.small_font.render("Wave incoming!", True, (255, 80, 80)),
                             (15, settings.MAP_HEIGHT + 56))
        else:
            enemies_text = f"Enemies: {len(wm.enemies)}"
            surface.blit(self.small_font.render(enemies_text, True, (255, 150, 150)),
                         (15, settings.MAP_HEIGHT + 56))

        # Build buttons (with hotkey labels) — require worker selected + can afford
        has_worker = any(isinstance(u, Worker) for u in game_state.selected_units)
        self._draw_button(surface, self.buttons["towncenter"],
                          f"TC [T] ${TOWN_CENTER_COST}", TOWN_CENTER_ACCENT, mouse_pos,
                          has_worker and game_state.resource_manager.can_afford(TOWN_CENTER_COST))
        self._draw_button(surface, self.buttons["barracks"],
                          f"Barracks [B] ${BARRACKS_COST}", BARRACKS_ACCENT, mouse_pos,
                          has_worker and game_state.resource_manager.can_afford(BARRACKS_COST))
        self._draw_button(surface, self.buttons["factory"],
                          f"Factory [F] ${FACTORY_COST}", FACTORY_ACCENT, mouse_pos,
                          has_worker and game_state.resource_manager.can_afford(FACTORY_COST))
        self._draw_button(surface, self.buttons["tower"],
                          f"Tower [D] ${TOWER_COST}", TOWER_ACCENT, mouse_pos,
                          has_worker and game_state.resource_manager.can_afford(TOWER_COST))
        self._draw_button(surface, self.buttons["watchguard"],
                          f"Guard [G] ${WATCHGUARD_COST}", WATCHGUARD_ACCENT, mouse_pos,
                          has_worker and game_state.resource_manager.can_afford(WATCHGUARD_COST))
        self._draw_button(surface, self.buttons["radar"],
                          f"Radar [R] ${RADAR_COST}", RADAR_ACCENT, mouse_pos,
                          has_worker and game_state.resource_manager.can_afford(RADAR_COST))

        # Placement mode indicator
        if game_state.placement_mode:
            mode_text = f"Placing: {game_state.placement_mode.title()} (click map | ESC to cancel)"
            surface.blit(self.small_font.render(mode_text, True, (0, 255, 0)),
                         (15, settings.MAP_HEIGHT + 38))

        # Selected building info — positioned left of minimap
        minimap_left = settings.WIDTH - 200 - 8
        sb = game_state.selected_building
        if sb:
            info_x = minimap_left - 320
            surface.blit(self.font.render(f"Selected: {sb.label}", True, HUD_TEXT),
                         (info_x, settings.MAP_HEIGHT + 10))
            # Check if this is a DefenseTower (has combat attributes, no production)
            from buildings import DefenseTower
            if isinstance(sb, DefenseTower):
                # Show combat stats instead of train button
                surface.blit(self.small_font.render(
                    f"Damage: {sb.damage}  Rate: {sb.fire_rate}/s  Range: {sb.attack_range}",
                    True, HUD_TEXT), (info_x, settings.MAP_HEIGHT + 30))
                status = "Attacking" if sb.attacking else "Idle"
                status_color = (255, 150, 150) if sb.attacking else (150, 200, 150)
                surface.blit(self.small_font.render(f"Status: {status}", True, status_color),
                             (info_x, settings.MAP_HEIGHT + 48))
            else:
                # Train button
                unit_class, cost, _ = sb.can_train()
                train_label = f"Train {unit_class.name} ${cost}"
                can_afford = game_state.resource_manager.can_afford(cost)
                if unit_class.name == "Worker":
                    accent = WORKER_ACCENT
                elif unit_class.name == "Soldier":
                    accent = SOLDIER_ACCENT
                else:
                    accent = TANK_ACCENT
                self._draw_button(surface, self.buttons["train"],
                                  train_label, accent, mouse_pos, can_afford)
                # Scout train button (only for Barracks)
                from buildings import Barracks
                if isinstance(sb, Barracks):
                    scout_class, scout_cost, _ = sb.can_train_scout()
                    scout_label = f"Train {scout_class.name} ${scout_cost}"
                    scout_afford = game_state.resource_manager.can_afford(scout_cost)
                    self._draw_button(surface, self.buttons["train_scout"],
                                      scout_label, SCOUT_ACCENT, mouse_pos, scout_afford)
                # Queue info
                queue_len = len(sb.production_queue)
                if queue_len > 0:
                    prog = sb.production_progress
                    queue_text = f"Queue: {queue_len} | Progress: {int(prog * 100)}%"
                    surface.blit(self.small_font.render(queue_text, True, HUD_TEXT),
                                 (info_x, settings.MAP_HEIGHT + 58))

        # Selected units info
        elif game_state.selected_units:
            info_x = minimap_left - 320
            count = len(game_state.selected_units)
            if count == 1:
                u = game_state.selected_units[0]
                surface.blit(self.font.render(f"{u.name}", True, HUD_TEXT),
                             (info_x, settings.MAP_HEIGHT + 8))
                hp_color = (0, 200, 0) if u.hp > u.max_hp * 0.5 else (255, 200, 0) if u.hp > u.max_hp * 0.25 else (255, 60, 60)
                surface.blit(self.small_font.render(f"HP: {u.hp}/{u.max_hp}", True, hp_color),
                             (info_x, settings.MAP_HEIGHT + 30))
                surface.blit(self.small_font.render(f"Speed: {u.speed}", True, HUD_TEXT),
                             (info_x + 120, settings.MAP_HEIGHT + 30))
                if u.attack_range > 0:
                    surface.blit(self.small_font.render(f"Damage: {u.damage}  Rate: {u.fire_rate}/s  Range: {u.attack_range}", True, HUD_TEXT),
                                 (info_x, settings.MAP_HEIGHT + 48))
                    state_text = "Stuck" if u.stuck else "Attacking" if u.attacking else "Moving" if u.waypoints else "Idle"
                else:
                    # Worker-specific info
                    if isinstance(u, Worker):
                        state_label = u.state.replace("_", " ").title()
                        carry_text = f"Carrying: {u.carry_amount}" if u.carry_amount > 0 else ""
                        surface.blit(self.small_font.render(f"State: {state_label}  {carry_text}", True, HUD_TEXT),
                                     (info_x, settings.MAP_HEIGHT + 48))
                    state_text = "Stuck" if u.stuck else "Moving" if u.waypoints else "Idle"
                stuck_color = (255, 100, 100) if u.stuck else (150, 200, 150)
                surface.blit(self.small_font.render(f"Status: {state_text}", True, stuck_color),
                             (info_x, settings.MAP_HEIGHT + 66))
            else:
                surface.blit(self.font.render(f"Selected: {count} units", True, HUD_TEXT),
                             (info_x, settings.MAP_HEIGHT + 8))
                # Summarize group
                from units import Soldier, Scout, Tank
                soldiers = sum(1 for u in game_state.selected_units if isinstance(u, Soldier))
                scouts = sum(1 for u in game_state.selected_units if isinstance(u, Scout))
                tanks = sum(1 for u in game_state.selected_units if isinstance(u, Tank))
                workers = sum(1 for u in game_state.selected_units if isinstance(u, Worker))
                parts = []
                if soldiers: parts.append(f"{soldiers} Soldier{'s' if soldiers > 1 else ''}")
                if scouts: parts.append(f"{scouts} Scout{'s' if scouts > 1 else ''}")
                if tanks: parts.append(f"{tanks} Tank{'s' if tanks > 1 else ''}")
                if workers: parts.append(f"{workers} Worker{'s' if workers > 1 else ''}")
                surface.blit(self.small_font.render("  ".join(parts), True, HUD_TEXT),
                             (info_x, settings.MAP_HEIGHT + 30))
                avg_hp = sum(u.hp for u in game_state.selected_units) / count
                avg_max = sum(u.max_hp for u in game_state.selected_units) / count
                surface.blit(self.small_font.render(f"Avg HP: {int(avg_hp)}/{int(avg_max)}", True, HUD_TEXT),
                             (info_x, settings.MAP_HEIGHT + 48))

        # Controls help
        help_text = "T: TC | B: Barracks | F: Factory | D: Tower | G: Guard | R: Radar | P: Pause | LClick: Select | RClick: Move/Mine | ESC: Cancel"
        surface.blit(self.small_font.render(help_text, True, (120, 120, 120)),
                     (15, settings.MAP_HEIGHT + HUD_HEIGHT - 22))

    def _draw_button(self, surface, rect, text, accent_color, mouse_pos, enabled):
        if not enabled:
            color = (50, 50, 50)
            text_color = (100, 100, 100)
        elif rect.collidepoint(mouse_pos):
            color = BUTTON_HOVER
            text_color = BUTTON_TEXT
        else:
            color = BUTTON_COLOR
            text_color = BUTTON_TEXT

        pygame.draw.rect(surface, color, rect, border_radius=4)
        pygame.draw.rect(surface, accent_color, rect, 2, border_radius=4)
        label = self.small_font.render(text, True, text_color)
        label_rect = label.get_rect(center=rect.center)
        surface.blit(label, label_rect)
