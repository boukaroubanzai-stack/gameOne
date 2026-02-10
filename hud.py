import pygame
from settings import (
    WIDTH, HEIGHT, HUD_HEIGHT, MAP_HEIGHT,
    HUD_BG, HUD_TEXT, BUTTON_COLOR, BUTTON_HOVER, BUTTON_TEXT,
    BARRACKS_COST, FACTORY_COST, TOWN_CENTER_COST,
    SOLDIER_COST, TANK_COST, WORKER_COST,
    TOTAL_WAVES,
)

# Accent colors for HUD buttons
BARRACKS_ACCENT = (140, 90, 50)
FACTORY_ACCENT = (90, 90, 120)
TOWN_CENTER_ACCENT = (60, 140, 60)
SOLDIER_ACCENT = (50, 120, 220)
TANK_ACCENT = (100, 100, 100)
WORKER_ACCENT = (180, 140, 60)


class HUD:
    def __init__(self):
        self.font = None
        self.small_font = None
        self.buttons = {}
        self._init_buttons()

    def _ensure_fonts(self):
        if self.font is None:
            self.font = pygame.font.SysFont(None, 24)
            self.small_font = pygame.font.SysFont(None, 18)

    def _init_buttons(self):
        btn_w, btn_h = 100, 36
        y = MAP_HEIGHT + 15
        self.buttons = {
            "towncenter": pygame.Rect(280, y, btn_w, btn_h),
            "barracks": pygame.Rect(390, y, btn_w, btn_h),
            "factory": pygame.Rect(500, y, btn_w, btn_h),
            "train": pygame.Rect(660, y, 120, btn_h),
        }

    def handle_click(self, pos, game_state):
        if not self.is_in_hud(pos):
            return False

        if self.buttons["towncenter"].collidepoint(pos):
            game_state.placement_mode = "towncenter"
            return True
        if self.buttons["barracks"].collidepoint(pos):
            game_state.placement_mode = "barracks"
            return True
        if self.buttons["factory"].collidepoint(pos):
            game_state.placement_mode = "factory"
            return True
        if self.buttons["train"].collidepoint(pos):
            if game_state.selected_building:
                game_state.selected_building.start_production(game_state.resource_manager)
            return True
        return True

    def is_in_hud(self, pos):
        return pos[1] >= MAP_HEIGHT

    def draw(self, surface, game_state):
        self._ensure_fonts()
        mouse_pos = pygame.mouse.get_pos()

        # HUD background
        hud_rect = pygame.Rect(0, MAP_HEIGHT, WIDTH, HUD_HEIGHT)
        pygame.draw.rect(surface, HUD_BG, hud_rect)
        pygame.draw.line(surface, (80, 80, 80), (0, MAP_HEIGHT), (WIDTH, MAP_HEIGHT), 2)

        # Resources
        res_text = f"Resources: {int(game_state.resource_manager.amount)}"
        surface.blit(self.font.render(res_text, True, (255, 215, 0)),
                     (15, MAP_HEIGHT + 10))

        # Wave info
        wm = game_state.wave_manager
        wave_text = f"Wave: {wm.waves_completed}/{TOTAL_WAVES}"
        surface.blit(self.font.render(wave_text, True, (200, 200, 255)),
                     (15, MAP_HEIGHT + 34))
        enemies_text = f"Enemies: {len(wm.enemies)}"
        surface.blit(self.small_font.render(enemies_text, True, (255, 150, 150)),
                     (15, MAP_HEIGHT + 56))

        # Build buttons
        self._draw_button(surface, self.buttons["towncenter"],
                          f"TC [T] ${TOWN_CENTER_COST}", TOWN_CENTER_ACCENT, mouse_pos,
                          game_state.resource_manager.can_afford(TOWN_CENTER_COST))
        self._draw_button(surface, self.buttons["barracks"],
                          f"Barracks [B] ${BARRACKS_COST}", BARRACKS_ACCENT, mouse_pos,
                          game_state.resource_manager.can_afford(BARRACKS_COST))
        self._draw_button(surface, self.buttons["factory"],
                          f"Factory [F] ${FACTORY_COST}", FACTORY_ACCENT, mouse_pos,
                          game_state.resource_manager.can_afford(FACTORY_COST))

        # Placement mode indicator
        if game_state.placement_mode:
            mode_text = f"Placing: {game_state.placement_mode.title()} (click map | ESC to cancel)"
            surface.blit(self.small_font.render(mode_text, True, (0, 255, 0)),
                         (15, MAP_HEIGHT + 38))

        # Selected building info
        sb = game_state.selected_building
        if sb:
            info_x = 630
            surface.blit(self.font.render(f"Selected: {sb.label}", True, HUD_TEXT),
                         (info_x, MAP_HEIGHT + 10))
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
            # Queue info
            queue_len = len(sb.production_queue)
            if queue_len > 0:
                prog = sb.production_progress
                queue_text = f"Queue: {queue_len} | Progress: {int(prog * 100)}%"
                surface.blit(self.small_font.render(queue_text, True, HUD_TEXT),
                             (info_x, MAP_HEIGHT + 58))

        # Selected units info
        elif game_state.selected_units:
            info_x = 630
            count = len(game_state.selected_units)
            if count == 1:
                u = game_state.selected_units[0]
                surface.blit(self.font.render(f"{u.name}", True, HUD_TEXT),
                             (info_x, MAP_HEIGHT + 8))
                hp_color = (0, 200, 0) if u.hp > u.max_hp * 0.5 else (255, 200, 0) if u.hp > u.max_hp * 0.25 else (255, 60, 60)
                surface.blit(self.small_font.render(f"HP: {u.hp}/{u.max_hp}", True, hp_color),
                             (info_x, MAP_HEIGHT + 30))
                surface.blit(self.small_font.render(f"Speed: {u.speed}", True, HUD_TEXT),
                             (info_x + 120, MAP_HEIGHT + 30))
                if u.attack_range > 0:
                    surface.blit(self.small_font.render(f"Damage: {u.damage}  Rate: {u.fire_rate}/s  Range: {u.attack_range}", True, HUD_TEXT),
                                 (info_x, MAP_HEIGHT + 48))
                    state_text = "Stuck" if u.stuck else "Attacking" if u.attacking else "Moving" if u.waypoints else "Idle"
                else:
                    # Worker-specific info
                    from units import Worker
                    if isinstance(u, Worker):
                        state_label = u.state.replace("_", " ").title()
                        carry_text = f"Carrying: {u.carry_amount}" if u.carry_amount > 0 else ""
                        surface.blit(self.small_font.render(f"State: {state_label}  {carry_text}", True, HUD_TEXT),
                                     (info_x, MAP_HEIGHT + 48))
                    state_text = "Stuck" if u.stuck else "Moving" if u.waypoints else "Idle"
                stuck_color = (255, 100, 100) if u.stuck else (150, 200, 150)
                surface.blit(self.small_font.render(f"Status: {state_text}", True, stuck_color),
                             (info_x, MAP_HEIGHT + 66))
            else:
                surface.blit(self.font.render(f"Selected: {count} units", True, HUD_TEXT),
                             (info_x, MAP_HEIGHT + 8))
                # Summarize group
                from units import Soldier, Tank, Worker
                soldiers = sum(1 for u in game_state.selected_units if isinstance(u, Soldier))
                tanks = sum(1 for u in game_state.selected_units if isinstance(u, Tank))
                workers = sum(1 for u in game_state.selected_units if isinstance(u, Worker))
                parts = []
                if soldiers: parts.append(f"{soldiers} Soldier{'s' if soldiers > 1 else ''}")
                if tanks: parts.append(f"{tanks} Tank{'s' if tanks > 1 else ''}")
                if workers: parts.append(f"{workers} Worker{'s' if workers > 1 else ''}")
                surface.blit(self.small_font.render("  ".join(parts), True, HUD_TEXT),
                             (info_x, MAP_HEIGHT + 30))
                avg_hp = sum(u.hp for u in game_state.selected_units) / count
                avg_max = sum(u.max_hp for u in game_state.selected_units) / count
                surface.blit(self.small_font.render(f"Avg HP: {int(avg_hp)}/{int(avg_max)}", True, HUD_TEXT),
                             (info_x, MAP_HEIGHT + 48))

        # Controls help
        help_text = "T: Town Center | B: Barracks | F: Factory | LClick: Select | RClick: Move/Mine | ESC: Cancel"
        surface.blit(self.small_font.render(help_text, True, (120, 120, 120)),
                     (15, MAP_HEIGHT + HUD_HEIGHT - 22))

    def _draw_button(self, surface, rect, text, accent_color, mouse_pos, enabled):
        self._ensure_fonts()
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
