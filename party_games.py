#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Tap-only party minigames for the kiosk's PLAY menu (MERZ lives in
PiDashboard.py itself, these two are self-contained):

- StackGame ("STAPEL-TURM"): a Plattenbau floor slides left/right, tap to
  drop it on the tower; whatever hangs over is cut off and falls.
- FlappyGame ("FLAPPY BVG"): tap to make a BVG bus hop through gaps between
  Baustellen barriers.

Each game is one object PiDashboard.py drives every frame: update(now),
draw(surf), tap(x, y) -> None | "close" | "menu". All motion is dt-based,
so the frame rate only changes smoothness. Scores are not persisted - just a
"Rekord heute" kept in memory (RECORDS), which resets at midnight and on an
app restart.
"""

import datetime
import math
import random

import pygame

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (150, 150, 150)
BVG_YELLOW = (240, 215, 0)
CLOSE_ORANGE = (255, 140, 0)
PANEL_BG = (25, 25, 32)
BUTTON_PURPLE = (196, 150, 255)

# Ignore taps right after a game over, so frantic tapping doesn't hit
# "NOCHMAL" by accident before people even saw the score.
GAME_OVER_TAP_DELAY_SECONDS = 0.8
# Cap per-frame dt: a stall (SD card, network thread) must not teleport the
# bus into a barrier.
MAX_DT_SECONDS = 0.05

# name -> (date, best score) - "Rekord heute", memory only.
RECORDS = {}


def record_today(name):
    entry = RECORDS.get(name)
    if entry is None or entry[0] != datetime.date.today():
        return 0
    return entry[1]


def _submit_score(name, score):
    """Returns True if score is a new record for today."""
    if score > record_today(name):
        RECORDS[name] = (datetime.date.today(), score)
        return True
    return False


class _Fonts:
    def __init__(self, regular_path, bold_path):
        self.regular_path = regular_path
        self.bold_path = bold_path
        self._cache = {}

    def get(self, size, bold=False):
        key = (size, bold)
        if key not in self._cache:
            self._cache[key] = pygame.font.Font(self.bold_path if bold else self.regular_path, size)
        return self._cache[key]


class _Game:
    """Shared ready -> play -> over flow, HUD, close button and game-over panel."""

    NAME = ""
    READY_TEXT = "Tippen zum Starten"
    SCORE_LABEL = "Punkte"

    def __init__(self, width, height, regular_font_path, bold_font_path):
        self.width = width
        self.height = height
        self.fonts = _Fonts(regular_font_path, bold_font_path)
        self.close_rect = pygame.Rect(width - 54, 10, 44, 44)
        self.reset(0.0)

    def reset(self, now):
        self.state = "ready"
        self.score = 0
        self.last_tick = now
        self.over_at = 0.0
        self.new_record = False
        self.over_text = ""
        self.buttons = {}

    def tap(self, x, y):
        """Returns "close", "menu" or None (tap used by the game)."""
        if self.close_rect.collidepoint((x, y)):
            return "close"
        if self.state == "over":
            if self.last_tick - self.over_at < GAME_OVER_TAP_DELAY_SECONDS:
                return None
            if "again" in self.buttons and self.buttons["again"].collidepoint((x, y)):
                self.reset(self.last_tick)
            elif "menu" in self.buttons and self.buttons["menu"].collidepoint((x, y)):
                return "menu"
            return None
        if self.state == "ready":
            self.state = "play"
            self.start()
            return None
        self.play_tap()
        return None

    def update(self, now):
        dt = max(0.0, min(MAX_DT_SECONDS, now - self.last_tick))
        self.last_tick = now
        self.step(dt)

    def game_over(self, text):
        self.state = "over"
        self.over_at = self.last_tick
        self.over_text = text
        self.new_record = _submit_score(self.NAME, self.score)

    # Subclass hooks
    def start(self):
        pass

    def play_tap(self):
        raise NotImplementedError

    def step(self, dt):
        raise NotImplementedError

    def draw(self, surf):
        raise NotImplementedError

    # Shared drawing
    def _text(self, surf, text, size, color, bold=True, **pos):
        rendered = self.fonts.get(size, bold).render(text, True, color)
        rect = rendered.get_rect(**pos)
        surf.blit(rendered, rect)
        return rect

    def _draw_outlined(self, surf, text, size, color, **pos):
        """Big numbers/text over a busy background: black outline."""
        font = self.fonts.get(size, True)
        inner = font.render(text, True, color)
        outline = font.render(text, True, BLACK)
        rect = inner.get_rect(**pos)
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2)):
            surf.blit(outline, rect.move(dx, dy))
        surf.blit(inner, rect)
        return rect

    def _draw_hud(self, surf):
        if self.state != "ready":
            self._draw_outlined(surf, str(self.score), 64, WHITE, midtop=(self.width // 2, 60))
        record = record_today(self.NAME)
        self._draw_outlined(surf, f"Rekord heute: {record}", 18, WHITE, topleft=(12, 14))
        pygame.draw.rect(surf, CLOSE_ORANGE, self.close_rect, border_radius=10)
        pygame.draw.rect(surf, BVG_YELLOW, self.close_rect, width=2, border_radius=10)
        self._text(surf, "x", 28, BLACK, center=self.close_rect.center)

    def _draw_ready(self, surf):
        self._draw_outlined(surf, self.NAME, 44, WHITE, center=(self.width // 2, int(self.height * 0.22)))
        blink = int(self.last_tick * 2) % 2 == 0
        if blink:
            self._draw_outlined(surf, self.READY_TEXT, 26, BVG_YELLOW, center=(self.width // 2, int(self.height * 0.30)))

    def _draw_over(self, surf):
        fog = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        fog.fill((0, 0, 0, 150))
        surf.blit(fog, (0, 0))

        panel = pygame.Rect(0, 0, self.width - 60, 380)
        panel.center = (self.width // 2, self.height // 2)
        pygame.draw.rect(surf, PANEL_BG, panel, border_radius=18)
        pygame.draw.rect(surf, BUTTON_PURPLE, panel, width=3, border_radius=18)

        y = panel.top + 24
        for line in _wrap(self.fonts.get(28, True), self.over_text, panel.width - 40):
            y = self._text(surf, line, 28, BVG_YELLOW, midtop=(panel.centerx, y)).bottom + 2
        y = self._text(surf, str(self.score), 72, WHITE, midtop=(panel.centerx, y + 6)).bottom
        self._text(surf, self.SCORE_LABEL, 20, GRAY, bold=False, midtop=(panel.centerx, y))
        record_line = "NEUER REKORD!" if self.new_record else f"Rekord heute: {record_today(self.NAME)}"
        self._text(
            surf, record_line, 22, BUTTON_PURPLE if self.new_record else WHITE, midtop=(panel.centerx, y + 32)
        )

        ready = self.last_tick - self.over_at >= GAME_OVER_TAP_DELAY_SECONDS
        button_w = (panel.width - 60) // 2
        again = pygame.Rect(panel.left + 20, panel.bottom - 90, button_w, 70)
        menu = pygame.Rect(again.right + 20, again.top, button_w, 70)
        for rect, label, fill in ((again, "NOCHMAL", BVG_YELLOW), (menu, "MENÜ", BUTTON_PURPLE)):
            pygame.draw.rect(surf, fill if ready else GRAY, rect, border_radius=12)
            self._text(surf, label, 26, BLACK, center=rect.center)
        self.buttons = {"again": again, "menu": menu}


def _wrap(font, text, max_width):
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and font.size(candidate)[0] > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


class StackGame(_Game):
    NAME = "STAPEL-TURM"
    DESCRIPTION = "Plattenbau hochstapeln"
    READY_TEXT = "Tippen zum Absetzen"
    SCORE_LABEL = "Stockwerke"

    FLOOR_HEIGHT = 36
    # Within this many px of the floor below counts as a perfect drop: snapped
    # exactly on top, nothing cut off. Fingers on a laggy touchscreen aren't
    # pixel-exact, so be generous.
    PERFECT_TOLERANCE = 7
    # After this many perfect drops in a row the floor grows back a bit.
    PERFECT_STREAK_TO_GROW = 3
    GROW_PX = 12
    START_SPEED = 170.0  # px/s
    SPEED_PER_FLOOR = 9.0
    MAX_SPEED = 520.0
    GRAVITY = 1400.0
    WINDOW_SPACING = 24  # windows sit on a world-x grid, so cut floors keep lining up

    def reset(self, now):
        super().reset(now)
        base_w = int(self.width * 0.6)
        # Floors: (x, width, color) bottom to top; floor 0 is the base.
        self.floors = [((self.width - base_w) / 2, base_w, (110, 110, 125))]
        self.moving_x = 0.0
        self.moving_dir = 1
        self.debris = []  # each: {x, y, w, vy, color}
        self.camera = 0.0  # world px scrolled down so the tower top stays in view
        self.perfect_streak = 0
        self.perfect_flash_until = 0.0
        self.perfect_text = ""

    def _floor_color(self, level):
        color = pygame.Color(0)
        color.hsva = ((level * 23) % 360, 55, 92, 100)
        return (color.r, color.g, color.b)

    def _speed(self):
        return min(self.MAX_SPEED, self.START_SPEED + self.SPEED_PER_FLOOR * self.score)

    def _ground_y(self):
        return int(self.height * 0.88)

    def _floor_top(self, level):
        """Screen y of a floor's top edge (level 0 = base)."""
        return self._ground_y() - (level + 1) * self.FLOOR_HEIGHT + self.camera

    def start(self):
        self._spawn_moving()

    def _spawn_moving(self):
        width = self.floors[-1][1]
        # Alternate sides, start just off the edge of the screen.
        self.moving_dir = 1 if len(self.floors) % 2 else -1
        self.moving_x = -width * 0.5 if self.moving_dir == 1 else self.width - width * 0.5

    def play_tap(self):
        top_x, top_w, _ = self.floors[-1]
        x, w = self.moving_x, top_w
        level = len(self.floors)
        color = self._floor_color(level)
        offset = x - top_x
        if abs(offset) <= self.PERFECT_TOLERANCE:
            self.perfect_streak += 1
            new_x, new_w = top_x, top_w
            if self.perfect_streak >= self.PERFECT_STREAK_TO_GROW:
                grow = min(self.GROW_PX, int(self.width * 0.6) - new_w)
                new_x -= grow / 2
                new_w += grow
            self.perfect_flash_until = self.last_tick + 0.7
            self.perfect_text = "PERFEKT!" if self.perfect_streak < 3 else f"PERFEKT x{self.perfect_streak}!"
        else:
            self.perfect_streak = 0
            left = max(x, top_x)
            right = min(x + w, top_x + top_w)
            if right <= left:
                # Missed completely: the whole floor falls.
                self.debris.append({"x": x, "level": level, "w": w, "vy": 0.0, "dy": 0.0, "color": color})
                self.game_over(random.choice(STACK_OVER_LINES))
                return
            new_x, new_w = left, right - left
            # The cut-off part falls.
            if x < top_x:
                cut_x, cut_w = x, top_x - x
            else:
                cut_x, cut_w = top_x + top_w, x + w - (top_x + top_w)
            self.debris.append({"x": cut_x, "level": level, "w": cut_w, "vy": 0.0, "dy": 0.0, "color": color})
        self.floors.append((new_x, new_w, color))
        self.score += 1
        self._spawn_moving()

    def step(self, dt):
        if self.state == "play":
            width = self.floors[-1][1]
            self.moving_x += self.moving_dir * self._speed() * dt
            # Bounce between the edges, the floor may stick out halfway.
            if self.moving_x + width * 0.5 > self.width:
                self.moving_x = self.width - width * 0.5
                self.moving_dir = -1
            elif self.moving_x < -width * 0.5:
                self.moving_x = -width * 0.5
                self.moving_dir = 1

        for piece in self.debris:
            piece["vy"] += self.GRAVITY * dt
            piece["dy"] += piece["vy"] * dt
        self.debris = [p for p in self.debris if p["dy"] < self.height * 2]

        # Keep the next floor's slot around 40% screen height.
        target = max(0.0, (len(self.floors) + 1) * self.FLOOR_HEIGHT - (self._ground_y() - self.height * 0.40))
        self.camera += (target - self.camera) * min(1.0, dt * 6)

    def _draw_floor(self, surf, x, top, w, color):
        rect = pygame.Rect(int(x), int(top), max(1, int(round(w))), self.FLOOR_HEIGHT)
        if rect.bottom < 0 or rect.top > self.height:
            return
        pygame.draw.rect(surf, color, rect)
        pygame.draw.rect(surf, tuple(int(c * 0.6) for c in color), rect, width=2)
        # Plattenbau windows on a fixed world-x grid.
        window_w, window_h = 12, 14
        first = int(math.ceil((rect.left + 4) / self.WINDOW_SPACING)) * self.WINDOW_SPACING
        for wx in range(first, rect.right - window_w - 3, self.WINDOW_SPACING):
            lit = (wx // self.WINDOW_SPACING + int(top - self.camera) // self.FLOOR_HEIGHT) % 3 == 0
            pygame.draw.rect(surf, (255, 230, 140) if lit else (40, 45, 70), (wx, rect.top + 11, window_w, window_h))

    def draw(self, surf):
        surf.fill((18, 22, 45))
        for i in range(40):  # fixed pseudo-random stars
            sx = (i * 97) % self.width
            sy = (i * 53) % int(self.height * 0.7)
            surf.set_at((sx, sy), (200, 200, 230))
            surf.set_at((sx + 1, sy), (200, 200, 230))
        ground_top = self._ground_y() + self.camera
        if ground_top < self.height:
            pygame.draw.rect(surf, (45, 55, 45), (0, ground_top, self.width, self.height - ground_top))

        for level, (x, w, color) in enumerate(self.floors):
            self._draw_floor(surf, x, self._floor_top(level), w, color)
        for piece in self.debris:
            self._draw_floor(surf, piece["x"], self._floor_top(piece["level"]) + piece["dy"], piece["w"], piece["color"])
        if self.state == "play":
            level = len(self.floors)
            self._draw_floor(surf, self.moving_x, self._floor_top(level), self.floors[-1][1], self._floor_color(level))

        if self.last_tick < self.perfect_flash_until:
            self._draw_outlined(surf, self.perfect_text, 34, BVG_YELLOW, center=(self.width // 2, int(self.height * 0.25)))

        self._draw_hud(surf)
        if self.state == "ready":
            self._draw_ready(surf)
        elif self.state == "over" and self.last_tick - self.over_at > 0.5:
            self._draw_over(surf)


class FlappyGame(_Game):
    NAME = "FLAPPY BVG"
    DESCRIPTION = "Bus durch die Baustellen"
    READY_TEXT = "Tippen zum Abfahren"
    SCORE_LABEL = "Haltestellen"

    GRAVITY = 1500.0  # px/s²
    FLAP_VY = -500.0
    MAX_FALL_VY = 750.0
    BARRIER_WIDTH = 74
    START_GAP = 230
    MIN_GAP = 175
    GAP_SHRINK_PER_POINT = 3
    BARRIER_SPACING = 270  # px between barriers
    START_SPEED = 165.0
    SPEED_PER_POINT = 3.0
    MAX_SPEED = 255.0
    # Max vertical jump between two consecutive gaps: a bus can only climb
    # so fast between barriers, bigger jumps were unbeatable.
    MAX_GAP_SHIFT = 170
    BUS_W, BUS_H = 64, 34
    STREET_HEIGHT = 80

    def reset(self, now):
        super().reset(now)
        self.bus_x = self.width * 0.28
        self.bus_y = self.height * 0.42
        self.vy = 0.0
        self.barriers = []  # each: {x, gap_y (center), gap, scored}
        self.scroll = 0.0  # total distance, for the parallax/street dashes
        self._bus_surf = None

    def _street_top(self):
        return self.height - self.STREET_HEIGHT

    def _speed(self):
        return min(self.MAX_SPEED, self.START_SPEED + self.SPEED_PER_POINT * self.score)

    def _spawn_barrier(self, x):
        gap = max(self.MIN_GAP, self.START_GAP - self.GAP_SHRINK_PER_POINT * self.score)
        # Keep the gap clear of the HUD (score) at the top and the street.
        low = 150 + gap / 2
        high = self._street_top() - 40 - gap / 2
        if self.barriers:
            previous = self.barriers[-1]["gap_y"]
            low, high = max(low, previous - self.MAX_GAP_SHIFT), min(high, previous + self.MAX_GAP_SHIFT)
        self.barriers.append({"x": x, "gap_y": random.uniform(low, high), "gap": gap, "scored": False})

    def start(self):
        self._spawn_barrier(self.width + 60)
        self.vy = self.FLAP_VY

    def play_tap(self):
        self.vy = self.FLAP_VY

    def _bus_rect(self):
        # A bit smaller than the drawn bus - forgiving hitbox.
        return pygame.Rect(
            int(self.bus_x - self.BUS_W / 2 + 6), int(self.bus_y - self.BUS_H / 2 + 5), self.BUS_W - 12, self.BUS_H - 10
        )

    def _barrier_rects(self, barrier):
        top_h = barrier["gap_y"] - barrier["gap"] / 2
        bottom_y = barrier["gap_y"] + barrier["gap"] / 2
        return (
            pygame.Rect(int(barrier["x"]), 0, self.BARRIER_WIDTH, int(top_h)),
            pygame.Rect(int(barrier["x"]), int(bottom_y), self.BARRIER_WIDTH, int(self._street_top() - bottom_y)),
        )

    def step(self, dt):
        if self.state == "ready":
            self.bus_y = self.height * 0.42 + math.sin(self.last_tick * 3) * 10
            self.scroll += self.START_SPEED * dt
            return
        if self.state == "over":
            # Bus drops onto the street.
            if self.bus_y + self.BUS_H / 2 < self._street_top():
                self.vy = min(self.MAX_FALL_VY, self.vy + self.GRAVITY * dt)
                self.bus_y = min(self._street_top() - self.BUS_H / 2, self.bus_y + self.vy * dt)
            return

        speed = self._speed()
        self.scroll += speed * dt
        self.vy = min(self.MAX_FALL_VY, self.vy + self.GRAVITY * dt)
        self.bus_y += self.vy * dt
        if self.bus_y < self.BUS_H / 2:
            self.bus_y = self.BUS_H / 2
            self.vy = 0.0

        for barrier in self.barriers:
            barrier["x"] -= speed * dt
            if not barrier["scored"] and barrier["x"] + self.BARRIER_WIDTH < self.bus_x - self.BUS_W / 2:
                barrier["scored"] = True
                self.score += 1
        self.barriers = [b for b in self.barriers if b["x"] + self.BARRIER_WIDTH > -10]
        if self.barriers[-1]["x"] < self.width + 60 - self.BARRIER_SPACING:
            self._spawn_barrier(self.barriers[-1]["x"] + self.BARRIER_SPACING)

        bus = self._bus_rect()
        if bus.bottom >= self._street_top():
            self.game_over(random.choice(FLAPPY_OVER_LINES))
            return
        for barrier in self.barriers:
            if any(bus.colliderect(r) for r in self._barrier_rects(barrier)):
                self.vy = 0.0
                self.game_over(random.choice(FLAPPY_OVER_LINES))
                return

    def _get_bus_surf(self):
        if self._bus_surf is None:
            s = pygame.Surface((self.BUS_W, self.BUS_H + 6), pygame.SRCALPHA)
            body = pygame.Rect(0, 0, self.BUS_W, self.BUS_H - 2)
            pygame.draw.rect(s, BVG_YELLOW, body, border_radius=7)
            pygame.draw.rect(s, (60, 50, 0), body, width=2, border_radius=7)
            # Window band and windshield (front = right).
            pygame.draw.rect(s, (40, 50, 70), (6, 5, self.BUS_W - 22, 11), border_radius=3)
            pygame.draw.rect(s, (40, 50, 70), (self.BUS_W - 13, 5, 9, 15), border_radius=3)
            for wx in range(16, self.BUS_W - 16, 12):
                pygame.draw.line(s, BVG_YELLOW, (wx, 5), (wx, 15), 2)
            label = self.fonts.get(11, True).render("BVG", True, BLACK)
            s.blit(label, label.get_rect(center=(self.BUS_W // 2 - 6, 24)))
            for cx in (14, self.BUS_W - 15):
                pygame.draw.circle(s, (25, 25, 25), (cx, self.BUS_H - 2), 6)
                pygame.draw.circle(s, GRAY, (cx, self.BUS_H - 2), 2)
            self._bus_surf = s
        return self._bus_surf

    def _draw_barrier(self, surf, rect, cap_at_bottom):
        if rect.height <= 0:
            return
        stripe = 22
        clip = surf.get_clip()
        surf.set_clip(rect)
        surf.fill(WHITE, rect)
        # Diagonal red/white Baustellen stripes.
        for i in range(-rect.height // stripe - 2, rect.width // stripe + rect.height // stripe + 2):
            x0 = rect.left + i * stripe * 2
            pygame.draw.polygon(
                surf,
                (220, 30, 30),
                [(x0, rect.bottom), (x0 + stripe, rect.bottom), (x0 + stripe + rect.height, rect.top), (x0 + rect.height, rect.top)],
            )
        surf.set_clip(clip)
        pygame.draw.rect(surf, (60, 20, 20), rect, width=2)
        # Warning lamp on the end next to the gap.
        lamp_y = rect.bottom - 8 if cap_at_bottom else rect.top + 8
        lamp_on = int(self.last_tick * 3) % 2 == 0
        pygame.draw.circle(surf, (255, 170, 0) if lamp_on else (120, 80, 0), (rect.centerx, lamp_y), 7)

    def _draw_backdrop(self, surf):
        surf.fill((150, 200, 235))
        street_top = self._street_top()
        # Parallax skyline incl. Fernsehturm, scrolling slowly.
        far = self.scroll * 0.2
        skyline_color = (120, 150, 180)
        block_w = 60
        offset = -(far % block_w)
        for i in range(int(self.width / block_w) + 2):
            bx = offset + i * block_w
            h = 60 + ((i + int(far // block_w)) * 37) % 90
            pygame.draw.rect(surf, skyline_color, (bx, street_top - h, block_w - 6, h))
        tower_x = self.width * 1.3 - (far * 0.5) % (self.width * 1.6)
        pygame.draw.line(surf, skyline_color, (tower_x, street_top), (tower_x, street_top - 300), 8)
        pygame.draw.circle(surf, skyline_color, (int(tower_x), int(street_top - 250)), 22)
        pygame.draw.line(surf, skyline_color, (tower_x, street_top - 300), (tower_x, street_top - 350), 3)
        # Street with dashes.
        pygame.draw.rect(surf, (70, 70, 75), (0, street_top, self.width, self.STREET_HEIGHT))
        pygame.draw.rect(surf, (110, 110, 115), (0, street_top, self.width, 6))
        dash_offset = -(self.scroll % 60)
        for i in range(int(self.width / 60) + 2):
            dx = dash_offset + i * 60
            pygame.draw.rect(surf, WHITE, (dx, street_top + self.STREET_HEIGHT // 2, 30, 5))

    def draw(self, surf):
        self._draw_backdrop(surf)
        for barrier in self.barriers:
            top, bottom = self._barrier_rects(barrier)
            self._draw_barrier(surf, top, cap_at_bottom=True)
            self._draw_barrier(surf, bottom, cap_at_bottom=False)
        angle = max(-25.0, min(60.0, self.vy / 12.0)) if self.state != "ready" else 0.0
        bus = pygame.transform.rotate(self._get_bus_surf(), -angle)
        surf.blit(bus, bus.get_rect(center=(int(self.bus_x), int(self.bus_y))))

        self._draw_hud(surf)
        if self.state == "ready":
            self._draw_ready(surf)
        elif self.state == "over" and self.last_tick - self.over_at > 0.5:
            self._draw_over(surf)


STACK_OVER_LINES = [
    "Eingestürzt!",
    "Baustopp!",
    "Statiker sagt nein.",
    "Abriss genehmigt.",
    "Das wird nix mit der Miete.",
]

FLAPPY_OVER_LINES = [
    "Störung im Betriebsablauf!",
    "Bitte zurückbleiben!",
    "Ersatzverkehr eingerichtet.",
    "Dieser Bus endet hier.",
    "Fahrt fällt aus.",
]

GAMES = [StackGame, FlappyGame]
