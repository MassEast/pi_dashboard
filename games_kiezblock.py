# -*- coding: utf-8 -*-
"""
KIEZBLOCK - tap-only score attack for the KiezOS 161 PLAY menu.

SUVs, Luxus-Vans, Poser-Sportwagen and (now and then) an A100-Betonmischer
drive down the Kiez street towards the Spielstraße at the bottom. Tap them
until they burst and turn into something useful (Hochbeet, Baum,
Tischtennisplatte, Zu-verschenken-Kiste, Plenum, ...), which hops onto the
sidewalk; the street slowly turns green. Every vehicle that reaches the
Spielstraße costs a heart, so does tapping a Lastenrad, a Kita-Bollerwagen
or a duck family. A golden Poller triggers KIEZBLOCK!: a Diagonalsperre
slams across the street and converts every car at once. Score is m²
entsiegelt, consecutive conversions build a combo multiplier.

Same interface as the party_games.py games (subclass of party_games._Game:
update(now) / draw(surf) / tap(x, y) -> None | "close" | "menu"), all
graphics drawn procedurally, all motion dt-based. Nothing in the top
HUD_HEIGHT px reacts to taps, which keeps the emergency-exit corner
(top-left 100x180 screen px = 100x144 under the 36 px title bar) free.
"""

import math
import random

import pygame

import kiezos as K
import party_games

INK = K.INK
WHITE = (255, 255, 255)
GLASS = (60, 70, 110)
GLASS_HI = (120, 140, 190)
TYRE = (28, 24, 34)
CHROME = (200, 200, 215)
HEADLIGHT = (255, 236, 140)
TAIL = (230, 40, 60)
WOOD = (176, 116, 62)
WOOD_DARK = (120, 74, 36)
LEAF = (70, 170, 70)
LEAF_HI = (120, 210, 90)
ASPHALT = (62, 54, 78)
ASPHALT_SPECK = (74, 66, 92)
PAVING = (168, 158, 190)
PAVING_LINE = (140, 128, 166)
CHALK = (245, 240, 255)
RED = (220, 40, 60)
GOLD = (255, 205, 60)

CELL = 4  # vehicle sprites: 1 cell = 4x4 screen px
SIDEWALK = 56
LANES = 4
HUD_HEIGHT = 144  # taps above this are ignored (emergency-exit corner, see docstring)
SPIELSTRASSE_HEIGHT = 74

# kind: hp, m² when converted, speed factor, bad (tap it) or good (don't), size in cells
KINDS = {
    "suv": dict(hp=2, m2=15, speed=1.0, bad=True, size=(18, 26)),
    "van": dict(hp=2, m2=18, speed=0.9, bad=True, size=(16, 28)),
    "sport": dict(hp=1, m2=10, speed=1.55, bad=True, size=(16, 24)),
    "panzer": dict(hp=3, m2=25, speed=0.8, bad=True, size=(20, 30)),
    "a100": dict(hp=9, m2=160, speed=0.42, bad=True, size=(44, 38)),
    "poller": dict(hp=1, m2=0, speed=0.85, bad=True, size=(12, 18)),
    "lastenrad": dict(hp=1, m2=5, speed=0.75, bad=False, size=(12, 24)),
    "kita": dict(hp=1, m2=5, speed=0.6, bad=False, size=(14, 24)),
    "enten": dict(hp=1, m2=5, speed=0.55, bad=False, size=(10, 28)),
}
SUV_PAINT = [((52, 50, 62), (70, 68, 82)), ((172, 172, 188), (200, 200, 214)), ((40, 56, 96), (58, 76, 120))]
PRODUCTS = ["hochbeet", "baum", "tischtennis", "verschenken", "plenum", "bank", "planschbecken"]
PRODUCT_LABEL = {
    "hochbeet": "HOCHBEET", "baum": "BAUM", "tischtennis": "TISCHTENNIS", "verschenken": "ZU VERSCHENKEN",
    "plenum": "PLENUM", "bank": "KIEZBANK", "planschbecken": "FREIBAD",
}

COMBO_SECONDS = 3.0  # combo runs out without a conversion for this long
COMBO_STEP = 5  # every 5 conversions in a row: multiplier +1
MAX_MULT = 5
COMBO_WORDS = {5: "GRÜNE WELLE!", 10: "ENTSIEGELT!", 15: "VERKEHRSWENDE!", 20: "AUTOFREI!!", 30: "KIEZ FÜR ALLE!",
               40: "DADA-WENDE!!!", 50: "UTOPIE!!!"}
HEARTS = 3
MAX_PARTICLES = 450
MAX_FRAME_SECONDS = 0.25  # longest frame that is caught up in sub-steps (see update())


class _Mover:
    def __init__(self, kind, lanes, x, y, speed, variant=0):
        spec = KINDS[kind]
        self.kind = kind
        self.lanes = lanes
        self.x = x  # center
        self.y = y  # top
        self.w, self.h = spec["size"][0] * CELL, spec["size"][1] * CELL
        self.speed = speed
        self.hp = self.max_hp = spec["hp"]
        self.bad = spec["bad"]
        self.variant = variant
        self.flash_until = 0.0
        self.squash_until = 0.0
        self.offended_until = 0.0  # good thing that got tapped: wobbles, can't be tapped again for a moment
        self.leaked = False
        self.einsicht = False  # dada: converts itself mid-street
        self.einsicht_at = None

    def rect(self):
        return pygame.Rect(int(self.x - self.w / 2), int(self.y), self.w, self.h)


# ------------------------------------------------------------------ sprites

_SPRITES = {}


def _cached(key, make):
    if key not in _SPRITES:
        _SPRITES[key] = make()
    return _SPRITES[key]


def _canvas(w, h):
    return pygame.Surface((w, h), pygame.SRCALPHA)


def _eyes(s, y, xl, xr, ew=3, angry=True):
    """Cartoon eyes in the windshield, pupils looking forward (down)."""
    for x in (xl, xr):
        pygame.draw.rect(s, WHITE, (x, y, ew, 3))
        pygame.draw.rect(s, INK, (x + ew // 2, y + 1, 1 if ew < 4 else 2, 2))
    if angry:
        pygame.draw.line(s, INK, (xl - 1, y - 2), (xl + ew - 1, y - 1))
        pygame.draw.line(s, INK, (xr + ew, y - 2), (xr, y - 1))


def _car_cells(kind, variant):
    r = lambda s, x, y, w, h, c: pygame.draw.rect(s, c, (x, y, w, h))  # noqa: E731
    if kind == "suv":
        body, roof = SUV_PAINT[variant % len(SUV_PAINT)]
        s = _canvas(18, 26)
        for tx, ty in ((0, 4), (16, 4), (0, 18), (16, 18)):
            r(s, tx, ty, 2, 5, TYRE)
        r(s, 1, 0, 16, 26, INK)
        r(s, 2, 1, 14, 24, body)
        r(s, 3, 1, 3, 1, TAIL); r(s, 12, 1, 3, 1, TAIL)
        r(s, 3, 3, 12, 3, GLASS); r(s, 4, 3, 2, 1, GLASS_HI)
        r(s, 3, 7, 12, 9, roof)
        r(s, 3, 8, 12, 1, INK); r(s, 3, 14, 12, 1, INK)  # roof rack
        r(s, 3, 17, 12, 4, GLASS)
        _eyes(s, 17, 4, 11)
        r(s, 2, 21, 14, 4, body); r(s, 8, 21, 2, 3, roof)
        r(s, 2, 24, 3, 1, HEADLIGHT); r(s, 13, 24, 3, 1, HEADLIGHT)
        r(s, 3, 25, 12, 1, CHROME)  # bull bar
        r(s, 0, 15, 1, 2, body); r(s, 17, 15, 1, 2, body)  # mirrors
        return s
    if kind == "van":
        s = _canvas(16, 28)
        for tx, ty in ((0, 3), (14, 3), (0, 20), (14, 20)):
            r(s, tx, ty, 2, 5, TYRE)
        r(s, 1, 0, 14, 28, INK)
        r(s, 2, 1, 12, 26, (236, 234, 242))
        r(s, 3, 2, 10, 16, (250, 248, 255))
        r(s, 2, 19, 12, 1, (180, 176, 196))
        r(s, 3, 21, 10, 3, GLASS)
        _eyes(s, 21, 4, 9, angry=False)
        pygame.draw.line(s, INK, (4, 20), (6, 20)); pygame.draw.line(s, INK, (9, 20), (11, 20))  # smug brows
        r(s, 2, 24, 12, 3, (236, 234, 242))
        r(s, 2, 26, 3, 1, HEADLIGHT); r(s, 11, 26, 3, 1, HEADLIGHT)
        return s
    if kind == "sport":
        s = _canvas(16, 24)
        for tx, ty in ((0, 3), (14, 3), (0, 17), (14, 17)):
            r(s, tx, ty, 2, 4, TYRE)
        r(s, 1, 1, 14, 23, INK)
        r(s, 2, 2, 12, 21, (225, 40, 50))
        r(s, 6, 2, 1, 21, WHITE); r(s, 9, 2, 1, 21, WHITE)  # racing stripes
        r(s, 0, 0, 16, 2, INK); r(s, 1, 0, 14, 1, (90, 90, 100))  # spoiler
        r(s, 4, 5, 8, 2, GLASS)
        r(s, 4, 7, 8, 5, (180, 30, 40))
        r(s, 3, 12, 10, 3, GLASS)
        _eyes(s, 12, 4, 9)
        r(s, 2, 22, 3, 1, HEADLIGHT); r(s, 11, 22, 3, 1, HEADLIGHT)
        return s
    if kind == "panzer":
        s = _canvas(20, 30)
        body, roof = (44, 58, 46), (60, 76, 60)
        for tx, ty in ((0, 4), (18, 4), (0, 20), (18, 20)):
            r(s, tx, ty, 2, 6, TYRE)
        r(s, 1, 0, 18, 30, INK)
        r(s, 2, 1, 16, 28, body)
        r(s, 7, 0, 6, 2, TYRE)  # spare wheel
        r(s, 3, 4, 14, 3, GLASS)
        r(s, 3, 8, 14, 11, roof)
        r(s, 5, 9, 10, 7, (26, 26, 30)); r(s, 6, 10, 8, 1, (60, 60, 70))  # roof box
        r(s, 3, 19, 14, 4, GLASS)
        _eyes(s, 19, 4, 12, ew=4)
        pygame.draw.line(s, INK, (3, 17), (8, 18)); pygame.draw.line(s, INK, (16, 17), (11, 18))
        r(s, 2, 23, 16, 5, body)
        for vx in (6, 9, 12):
            r(s, vx, 24, 2, 3, roof)
        r(s, 2, 27, 3, 2, HEADLIGHT); r(s, 15, 27, 3, 2, HEADLIGHT)
        r(s, 2, 29, 16, 1, CHROME); r(s, 4, 28, 12, 1, CHROME)
        return s
    if kind == "a100":
        s = _canvas(44, 38)
        for tx, ty in ((0, 4), (42, 4), (0, 14), (42, 14), (0, 28), (42, 28)):
            r(s, tx, ty, 2, 6, TYRE)
        r(s, 1, 0, 42, 38, INK)
        r(s, 2, 1, 40, 24, (90, 86, 100))
        pygame.draw.ellipse(s, (176, 172, 186), (4, 1, 36, 23))
        for i in range(-4, 8):  # drum stripes
            pygame.draw.line(s, (240, 140, 30), (4 + i * 6, 23), (12 + i * 6, 1), 2)
        pygame.draw.ellipse(s, INK, (4, 1, 36, 23), 1)
        r(s, 2, 25, 40, 12, (240, 140, 30))
        r(s, 4, 29, 36, 4, GLASS)
        _eyes(s, 29, 9, 29, ew=6)
        pygame.draw.line(s, INK, (8, 27), (15, 28)); pygame.draw.line(s, INK, (36, 27), (29, 28))
        r(s, 3, 36, 5, 1, HEADLIGHT); r(s, 36, 36, 5, 1, HEADLIGHT); r(s, 16, 35, 12, 2, CHROME)
        return s
    if kind == "poller":
        s = _canvas(12, 18)
        r(s, 3, 1, 6, 16, INK)
        for i in range(7):
            r(s, 4, 2 + i * 2, 4, 2, GOLD if i % 2 == 0 else WHITE)
        r(s, 2, 0, 8, 2, INK); r(s, 3, 0, 6, 1, (255, 240, 150))
        r(s, 1, 16, 10, 2, INK); r(s, 2, 16, 8, 1, (120, 110, 140))
        return s
    if kind == "lastenrad":
        s = _canvas(12, 24)
        r(s, 5, 0, 2, 4, TYRE)
        r(s, 5, 8, 2, 4, (80, 80, 96))
        r(s, 3, 4, 6, 3, (230, 90, 170)); r(s, 2, 6, 1, 4, (230, 90, 170)); r(s, 9, 6, 1, 4, (230, 90, 170))
        pygame.draw.ellipse(s, (60, 40, 30), (4, 4, 4, 4))  # head, top-down
        r(s, 1, 10, 10, 1, INK)
        r(s, 1, 11, 10, 9, INK); r(s, 2, 12, 8, 7, WOOD)
        r(s, 4, 13, 4, 4, (170, 110, 60)); r(s, 3, 13, 1, 3, (110, 70, 40)); r(s, 8, 13, 1, 3, (110, 70, 40))  # dog
        s.set_at((5, 14), INK); s.set_at((6, 14), INK); r(s, 5, 16, 2, 1, (60, 30, 30))
        r(s, 5, 20, 2, 4, TYRE)
        return s
    if kind == "kita":
        s = _canvas(14, 24)
        r(s, 1, 1, 12, 17, INK); r(s, 2, 2, 10, 15, (220, 60, 70))
        caps = [(255, 208, 72), (110, 175, 255), (255, 130, 200), (120, 210, 90), (190, 140, 250), (255, 150, 70)]
        for i, cap in enumerate(caps):
            cx, cy = 3 + (i % 2) * 5, 3 + (i // 2) * 5
            r(s, cx, cy, 4, 4, cap); s.set_at((cx + 1, cy + 1), WHITE)
        r(s, 0, 3, 1, 3, TYRE); r(s, 13, 3, 1, 3, TYRE); r(s, 0, 12, 1, 3, TYRE); r(s, 13, 12, 1, 3, TYRE)
        r(s, 7, 18, 1, 2, INK)
        r(s, 3, 20, 8, 3, (90, 170, 160))
        pygame.draw.ellipse(s, (200, 120, 60), (5, 19, 4, 4))
        return s
    if kind == "enten":
        s = _canvas(10, 28)
        for y in (1, 6, 11):
            pygame.draw.ellipse(s, (255, 220, 70), (3, y, 4, 4)); r(s, 4, y + 4, 2, 1, (240, 140, 30))
        pygame.draw.ellipse(s, INK, (0, 14, 10, 11))
        pygame.draw.ellipse(s, WHITE, (1, 15, 8, 9))
        pygame.draw.ellipse(s, (235, 235, 245), (3, 21, 4, 4))
        r(s, 4, 25, 2, 2, (240, 140, 30)); s.set_at((3, 22), INK); s.set_at((6, 22), INK)
        r(s, 2, 17, 1, 4, (200, 200, 215)); r(s, 7, 17, 1, 4, (200, 200, 215))
        return s
    raise ValueError(kind)


def _damage(s, level, seed):
    """Cracks, dents and a sweat drop on a scaled sprite, more per level."""
    rnd = random.Random(seed)
    w, h = s.get_size()
    for _ in range(level * 3):
        x, y = rnd.randint(10, w - 10), rnd.randint(12, h - 12)
        pts = [(x, y)]
        for _ in range(3):
            x += rnd.randint(-10, 10)
            y += rnd.randint(-9, 9)
            pts.append((x, y))
        pygame.draw.lines(s, WHITE, False, pts, 2)
    for _ in range(level * 2):
        pygame.draw.circle(s, (0, 0, 0, 90), (rnd.randint(10, w - 10), rnd.randint(10, h - 10)), rnd.randint(4, 7))
    pygame.draw.circle(s, K.DROP, (w - 10, 12), 4)
    pygame.draw.polygon(s, K.DROP, [(w - 14, 11), (w - 6, 11), (w - 10, 3)])


def vehicle_sprite(kind, variant=0, damage=0):
    def make():
        s = pygame.transform.scale(_car_cells(kind, variant), (KINDS[kind]["size"][0] * CELL, KINDS[kind]["size"][1] * CELL))
        if kind == "van":
            label = pygame.transform.rotate(K.font(15).render("LOFTS", False, K.F_ACCENT), 90)
            s.blit(label, label.get_rect(center=(s.get_width() // 2, 40)))
        elif kind == "a100":
            plate = pygame.Rect(0, 0, 76, 30)
            plate.center = (s.get_width() // 2, 48)
            pygame.draw.rect(s, (255, 220, 60), plate)
            pygame.draw.rect(s, INK, plate, 3)
            K.t95(s, "A100", 22, plate.center, color=INK, anchor="center")
        if damage:
            _damage(s, damage, hash((kind, variant)) & 0xFFFF)
        return s
    return _cached(("veh", kind, variant, damage), make)


def _silhouette(sprite, color):
    """One-colour copy of a (cached!) sprite: hit flash, shadow."""
    return _cached(("silhouette", id(sprite), color),
                   lambda: pygame.mask.from_surface(sprite).to_surface(setcolor=color, unsetcolor=(0, 0, 0, 0)))


def _white(sprite):
    return _silhouette(sprite, WHITE)


def _product_cells(kind):
    s = _canvas(16, 16)
    r = lambda x, y, w, h, c: pygame.draw.rect(s, c, (x, y, w, h))  # noqa: E731
    if kind == "hochbeet":
        for x, c in ((3, LEAF), (6, LEAF_HI), (9, LEAF), (12, LEAF_HI)):
            r(x, 3, 2, 6, c); r(x - 1, 4, 1, 2, c); r(x + 2, 5, 1, 2, c)
        pygame.draw.circle(s, (230, 50, 60), (5, 3), 2); pygame.draw.circle(s, K.SUN, (11, 2), 2); s.set_at((11, 2), WOOD_DARK)
        r(1, 8, 14, 7, INK); r(2, 9, 12, 5, WOOD); r(2, 11, 12, 1, WOOD_DARK)
    elif kind == "baum":
        r(4, 13, 8, 2, (120, 110, 140))
        r(7, 9, 2, 5, WOOD_DARK)
        pygame.draw.circle(s, INK, (8, 6), 6); pygame.draw.circle(s, LEAF, (8, 6), 5); pygame.draw.circle(s, LEAF_HI, (6, 4), 2)
        s.set_at((10, 7), (230, 50, 60)); s.set_at((5, 8), (230, 50, 60))
    elif kind == "tischtennis":
        r(2, 12, 1, 3, INK); r(13, 12, 1, 3, INK)
        r(1, 3, 14, 10, INK); r(2, 4, 12, 8, (40, 140, 100))
        r(2, 7, 12, 2, CHROME); r(8, 4, 1, 8, WHITE)
        pygame.draw.circle(s, WHITE, (5, 5), 1)
    elif kind == "verschenken":
        r(4, 3, 2, 5, (110, 175, 255)); r(9, 1, 3, 7, (255, 130, 200)); r(9, 1, 3, 1, K.SUN)  # book, lamp
        r(1, 7, 14, 8, INK); r(2, 8, 12, 6, (205, 160, 100)); r(0, 7, 4, 2, (205, 160, 100)); r(12, 7, 4, 2, (205, 160, 100))
        r(4, 10, 8, 1, INK); r(4, 12, 6, 1, INK)  # "ZU VERSCHENKEN" scribble
    elif kind == "plenum":
        cols = [(255, 130, 200), (110, 175, 255), K.SUN, LEAF_HI, (190, 140, 250), (255, 150, 70)]
        for i, c in enumerate(cols):
            a = i * math.pi / 3
            x, y = int(8 + math.cos(a) * 5.5), int(8 + math.sin(a) * 5.5)
            r(x - 1, y - 1, 3, 3, INK); s.set_at((x, y), c)
        r(6, 6, 4, 4, WHITE); r(7, 7, 2, 1, INK); r(7, 8, 1, 1, INK)  # flipchart
    elif kind == "bank":
        r(2, 4, 3, 3, (230, 120, 70)); r(2, 2, 3, 2, LEAF)  # flower pot
        r(1, 8, 14, 1, INK); r(1, 9, 14, 2, WOOD); r(1, 11, 14, 2, WOOD_DARK); r(2, 13, 1, 2, INK); r(13, 13, 1, 2, INK)
        r(10, 4, 3, 3, (230, 120, 70)); r(10, 2, 3, 2, (255, 130, 200))
    elif kind == "planschbecken":
        pygame.draw.circle(s, INK, (8, 8), 7); pygame.draw.circle(s, WHITE, (8, 8), 6); pygame.draw.circle(s, K.DROP, (8, 8), 5)
        r(9, 6, 3, 3, (255, 220, 70)); s.set_at((12, 7), (240, 140, 30))
        r(4, 9, 2, 1, WHITE)
    return s


def product_sprite(kind, size=48):
    return _cached(("prod", kind, size), lambda: pygame.transform.scale(_product_cells(kind), (size, size)))


def menu_icon(size=32):
    """16px menu/title icon (an SUV with a sprout on its roof), scaled."""
    def make():
        s = _canvas(16, 16)
        pygame.draw.rect(s, INK, (3, 3, 10, 13)); pygame.draw.rect(s, SUV_PAINT[0][1], (4, 4, 8, 11))
        pygame.draw.rect(s, GLASS, (4, 11, 8, 2)); s.set_at((5, 11), WHITE); s.set_at((10, 11), WHITE)
        pygame.draw.rect(s, HEADLIGHT, (4, 14, 2, 1)); pygame.draw.rect(s, HEADLIGHT, (10, 14, 2, 1))
        pygame.draw.line(s, LEAF, (8, 9), (8, 3)); pygame.draw.rect(s, LEAF_HI, (5, 1, 3, 2)); pygame.draw.rect(s, LEAF, (9, 2, 3, 2))
        pygame.draw.circle(s, K.PINK, (8, 2), 1)
        return pygame.transform.scale(s, (size, size))
    return _cached(("menu", size), make)


HAND = ["..XX......", ".XwwX.....", ".XwwX.....", ".XwwXXX...", ".XwwXwwXX.", "XXwwXwwXwX", "XwwwwwwwwX",
        "XwwwwwwwwX", ".XwwwwwwwX", ".XwwwwwwX.", "..XwwwwwX.", "..XXXXXX.."]


def _hand(size):
    def make():
        s = _canvas(10, 12)
        for y, row in enumerate(HAND):
            for x, ch in enumerate(row):
                if ch != ".":
                    s.set_at((x, y), INK if ch == "X" else WHITE)
        return pygame.transform.scale(s, (10 * size // 12, size))
    return _cached(("hand", size), make)


# ------------------------------------------------------------------ text lines

DRIVE_LINES = {
    "suv": ["Ich muss nur kurz!", "Zweite Reihe ist auch 'ne Reihe.", "Kita ist 300 m weit! Zu Fuß?!",
            "Ist doch ein E-SUV!", "Das ist meine Freiheit!", "Ich zahl doch Kfz-Steuer!", "Wo soll ich denn parken?!"],
    "van": ["Exklusive Lofts! Ab 1,2 Mio!", "Ihr Kiez wird aufgewertet!", "Eigenbedarf! Ganz bestimmt!",
            "Möbliert auf Zeit, 39 m², 1.900 €"],
    "sport": ["BRÖÖÖÖM!", "0 auf 100 in der Spielstraße!", "Hab's eilig! Wohin? Egal!", "Guck mal, mein Auspuff!"],
    "panzer": ["Brauch ich für den Wochenmarkt.", "Passt locker in die Lücke!", "Offroad! Bis zum Bioladen."],
    "a100": ["Nur noch EIN Bauabschnitt!", "Beton ist auch Natur!", "Planung von 1965! Zeitlos!"],
}
LEAK_LINES = ["Ich wohn hier seit 3 Wochen!", "Nur kurz Warnblinker!", "Ich hab's doch eilig!", "Hier war doch Parkplatz?!"]
PENALTY_LINES = {
    "lastenrad": ["Ey! Ich bin die Lösung!", "Fahrrad ist nicht das Problem!"],
    "kita": ["Erzieher*in: HALLO?!", "Kita-Ausflug! Finger weg!"],
    "enten": ["QUAK! Enten haben Vorfahrt!", "Die Quak*innen protestieren!"],
}
PRODUCT_LINES = ["Ich war mal ein SUV.", "Endlich Wurzeln!", "Ich bin jetzt Allmende.", "Mir geht's viel besser so.",
                 "Kein Benzin mehr. Nur Gießkanne.", "Ich fühl mich so... entschleunigt."]
PLENUM_LINE = "Wir müssen das erst ausdiskutieren."
EINSICHT_LINE = "Ich... wär lieber ein Baum."
OVER_LINES = ["Stau bis Spandau.", "Spielstraße zugeparkt!", "Die Autolobby gewinnt. Heute noch.",
              "Verkehrsplanung von 1965 schlägt zurück.", "Parkplatz-Notstand ausgerufen!"]


class KiezblockGame(party_games._Game):
    NAME = "KIEZBLOCK"
    ICON = "kiezblock"
    DESCRIPTION = "SUVs zu Hochbeeten tippen"
    READY_TEXT = "Tippen zum Starten!"
    SCORE_LABEL = "m² entsiegelt"
    SCORE_UNIT = " m²"

    @staticmethod
    def format_score(score):
        return f"{score:,}".replace(",", ".")

    @staticmethod
    def icon(size):
        return menu_icon(size)

    # ------------------------------------------------------------ state
    def reset(self, now):
        super().reset(now)
        self.lane_w = (self.width - 2 * SIDEWALK) / LANES
        self.play_bottom = self.height - SPIELSTRASSE_HEIGHT
        self.t = 0.0  # play time, stops during freeze frames
        self.movers = []
        self.particles = []  # [x, y, vx, vy, life, max_life, color, size]
        self.rings = []  # [x, y, age, max_age, color, max_r]
        self.popups = []  # dict text, x, y, age, color, size
        self.ghosts = []  # white silhouettes of converted vehicles popping: [sprite, cx, cy, age]
        self.flying = []  # products hopping to the sidewalk: dict kind, x0, y0, slot, age
        self.slots = [None] * (2 * self._slots_per_side())
        self.next_slot = 0
        self.bubble = None  # dict text, mover or pos, until
        self.next_bubble_at = now + 2.5
        self.hearts = HEARTS
        self.combo = 0
        self.best_combo = 0
        self.last_convert_t = -99.0
        self.conversions = 0
        self.spawn_in = 0.3
        self.next_poller_at = 17.0
        self.next_boss_at = 38.0
        self.boss_warn_until = 0.0
        self.freeze_until = 0.0
        self.shake_until = 0.0
        self.shake_amp = 0
        self.flash_until = 0.0
        self.flash_color = WHITE
        self.wordart = None  # (text, start)
        self.kiezblock = None  # dict start, queue
        self.kiezblock_count = 0
        self.leak_flash_until = 0.0
        self.taps = 0
        self._tap_xy = (0, 0)
        self._bg_key = None
        self._bg = None
        self._text_cache = {}
        self.bubble_rect = None  # last drawn speech bubble (for dev/test_kiezblock.py)

    def _slots_per_side(self):
        return int((self.height - SPIELSTRASSE_HEIGHT - HUD_HEIGHT - 8) // 54)

    def _slot_pos(self, i):
        per = self._slots_per_side()
        side, row = divmod(i, per)
        x = SIDEWALK // 2 if side == 0 else self.width - SIDEWALK // 2
        return x, HUD_HEIGHT + 32 + row * 54

    def lane_x(self, lane):
        return SIDEWALK + self.lane_w * (lane + 0.5)

    def multiplier(self):
        return 1 + min(MAX_MULT - 1, self.combo // COMBO_STEP)

    def update(self, now):
        """party_games caps a frame at MAX_DT_SECONDS, so below 20 FPS the cars crawl and the
        difficulty curve stretches. Up to MAX_FRAME_SECONDS of a slow frame are simulated in
        MAX_DT_SECONDS sub-steps instead (no car skips past a tap); longer stalls are dropped."""
        dt = max(0.0, min(MAX_FRAME_SECONDS, now - self.last_tick))
        self.last_tick = now
        while dt > 1e-9:
            h = min(party_games.MAX_DT_SECONDS, dt)
            self.step(h)
            dt -= h

    # ------------------------------------------------------------ input
    def tap(self, x, y):
        self._tap_xy = (x, y)
        if self.state == "ready" and y < HUD_HEIGHT:
            return None  # the HUD (and the emergency-exit corner) never reacts
        return super().tap(x, y)

    def start(self):
        self.t = 0.0
        self.spawn_in = 0.2
        self._say_at("Liebe Nachbar*innen: LOS!", (self.width // 2, HUD_HEIGHT + 60), 1.6)

    def play_tap(self):
        x, y = self._tap_xy
        if y < HUD_HEIGHT:
            return
        self.taps += 1
        target = self._pick(x, y)
        if target is None:
            self._burst(x, y, 6, [(110, 100, 130), (150, 140, 170)], speed=90, size=4)
            return
        if target.bad:
            self._hit(target, x, y)
        else:
            self._penalty(target)

    def _pick(self, x, y):
        live = [m for m in reversed(self.movers) if not m.leaked and m.y + m.h > HUD_HEIGHT]
        for m in live:
            if m.bad and m.rect().collidepoint(x, y):
                return m
        for m in live:
            if not m.bad and m.rect().collidepoint(x, y) and self.last_tick >= m.offended_until:
                return m
        # Fingers on a touchscreen land a bit off: generous margin for cars only.
        for m in live:
            if m.bad and m.rect().inflate(16, 16).collidepoint(x, y):
                return m
        return None

    def tappable_bad(self):
        """Centers of the vehicles a player should tap (for bots/tests)."""
        return [m for m in self.movers if m.bad and not m.leaked and m.y + m.h > HUD_HEIGHT + 30]

    # ------------------------------------------------------------ actions
    def _freeze(self, seconds):
        self.freeze_until = max(self.freeze_until, self.last_tick + seconds)

    def _shake(self, seconds, amp):
        if self.last_tick + seconds > self.shake_until or amp > self.shake_amp:
            self.shake_until = self.last_tick + seconds
            self.shake_amp = amp

    def _flash(self, seconds, color=WHITE):
        self.flash_until = self.last_tick + seconds
        self.flash_color = color

    def _hit(self, m, x, y):
        if m.kind == "poller":
            self.movers.remove(m)
            self._start_kiezblock(m)
            return
        m.hp -= 1
        m.flash_until = self.last_tick + 0.07
        m.squash_until = self.last_tick + 0.12
        m.y -= 6
        self._burst(x, y, 8, [WHITE, GLASS_HI, HEADLIGHT], speed=220, size=4)
        self.rings.append([x, y, 0.0, 0.18, WHITE, 26])
        if m.hp <= 0:
            self._convert(m)
        else:
            self._freeze(0.035)
            self._shake(0.08, 3)
            self.popups.append(dict(text=random.choice(["KLONK!", "DONG!", "PLONK!", "BÄM!"]), x=x, y=y - 30, age=0.0,
                                    color=WHITE, size=20))

    def _convert(self, m, chain=False, einsicht=False):
        if m in self.movers:
            self.movers.remove(m)
        cx, cy = m.x, m.y + m.h / 2
        boss = m.kind == "a100"
        self.conversions += 1
        self.combo += 1
        self.best_combo = max(self.best_combo, self.combo)
        self.last_convert_t = self.t
        mult = self.multiplier()
        points = KINDS[m.kind]["m2"] * mult
        self.score += points
        body = {"suv": SUV_PAINT[m.variant % len(SUV_PAINT)][0], "van": (236, 234, 242), "sport": (225, 40, 50),
                "panzer": (44, 58, 46), "a100": (240, 140, 30)}.get(m.kind, (90, 86, 100))
        self.ghosts.append([_white(vehicle_sprite(m.kind, m.variant)), cx, cy, 0.0])
        n = 44 if boss else 22
        self._burst(cx, cy, n, [body, body, (40, 36, 50), GLASS_HI], speed=380 if boss else 300, size=10)
        self._burst(cx, cy, n // 2 + 6, [LEAF, LEAF_HI], speed=200, size=5)
        self._burst(cx, cy, 10, [K.PINK, K.SUN, WHITE], speed=160, size=4)
        self.rings.append([cx, cy, 0.0, 0.3, LEAF_HI, 90 if boss else 60])
        label = f"+{points} m²"
        self.popups.append(dict(text=label, x=cx, y=cy - 10, age=0.0, color=K.SUN, size=24 if not boss else 30))
        if mult > 1:
            self.popups.append(dict(text=f"x{mult}", x=cx + 40, y=cy + 18, age=0.0, color=K.PINK, size=20))
        product = "planschbecken" if boss else ("baum" if einsicht else random.choice(PRODUCTS[:-1]))
        self._fly_product(product, cx, cy)
        if boss:
            self._burst(cx, cy, 50, [K.DROP, WHITE, (170, 210, 255)], speed=420, size=8)
            for i, color in enumerate((K.DROP, WHITE, (170, 210, 255))):
                self.rings.append([cx, cy, -0.08 * i, 0.45, color, 150 + 40 * i])
            self._freeze(0.32)
            self._flash(0.14)
            self._shake(0.5, 10)
            self._wordart("FREIBAD!")
            self._say_at("Juhu! Arschbombe!", (cx, cy + 120), 2.0)
        elif einsicht:
            self._freeze(0.2)
            self._shake(0.2, 5)
            self._wordart("EINSICHT!")
        elif not chain:
            self._freeze(0.06)
            self._shake(0.14, 5)
            if product == "plenum" and random.random() < 0.6:
                self._say_at(PLENUM_LINE, (cx, cy), 2.4)
            elif random.random() < 0.2:
                self._say_at(random.choice(PRODUCT_LINES), (cx, cy), 2.0)
        word = COMBO_WORDS.get(self.combo) or ("UNAUFHALTBAR!" if self.combo > 50 and self.combo % 10 == 0 else None)
        if word and not boss and not einsicht and self.kiezblock is None:
            self._wordart(word)
            self._flash(0.06, (200, 255, 200))

    def _fly_product(self, kind, x, y):
        slot = self.next_slot
        self.next_slot = (self.next_slot + 1) % len(self.slots)
        self.slots[slot] = None  # the oldest one makes room
        self.flying.append(dict(kind=kind, x0=x, y0=y, slot=slot, age=0.0))

    def _penalty(self, m):
        m.offended_until = self.last_tick + 1.2
        self._lose_heart(m.x, m.y + m.h / 2)
        self._say(m, random.choice(PENALTY_LINES[m.kind]), 2.2)
        self.popups.append(dict(text="AUA!" if m.kind != "enten" else "QUAK!", x=m.x, y=m.y - 10, age=0.0, color=RED, size=24))
        if m.kind == "enten":
            self._burst(m.x, m.y + m.h / 2, 14, [WHITE, (255, 220, 70)], speed=150, size=4)

    def _lose_heart(self, x, y):
        self.hearts -= 1
        if self.combo >= COMBO_STEP:
            self.popups.append(dict(text="Combo weg", x=self.width // 2, y=HUD_HEIGHT + 40, age=0.0, color=WHITE, size=18))
        self.combo = 0
        self._shake(0.35, 9)
        self._flash(0.1, (255, 80, 90))
        self._freeze(0.08)
        self.leak_flash_until = self.last_tick + 0.6
        if self.hearts <= 0:
            self._shake(0.6, 12)
            self._wordart("STAU!")
            self.game_over(random.choice(OVER_LINES))

    def _start_kiezblock(self, poller):
        self.kiezblock_count += 1
        self.kiezblock = dict(start=self.t, done=0, queue=sorted((m for m in self.movers if m.bad and not m.leaked),
                                                       key=lambda m: -m.y))
        self._freeze(0.25)
        self._flash(0.16)
        self._shake(0.45, 11)
        self._wordart("KIEZBLOCK!")
        self._burst(poller.x, poller.y + poller.h / 2, 30, [GOLD, WHITE, K.PINK], speed=360, size=6)
        self.rings.append([poller.x, poller.y + poller.h / 2, 0.0, 0.4, GOLD, 160])
        good = [m for m in self.movers if not m.bad]
        if good:
            self._say(random.choice(good), "Endlich Ruhe!", 2.0)

    def _wordart(self, text):
        self.wordart = (text, self.last_tick)

    def _say(self, mover, text, seconds):
        self.bubble = dict(text=text, mover=mover, pos=None, until=self.last_tick + seconds)

    def _say_at(self, text, pos, seconds):
        self.bubble = dict(text=text, mover=None, pos=pos, until=self.last_tick + seconds)

    def _burst(self, x, y, n, colors, speed=200, size=5):
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            v = random.uniform(0.3, 1.0) * speed
            life = random.uniform(0.35, 0.8)
            self.particles.append([x, y, math.cos(a) * v, math.sin(a) * v, life, life, random.choice(colors),
                                   random.randint(max(2, size - 2), size)])
        if len(self.particles) > MAX_PARTICLES:
            del self.particles[: len(self.particles) - MAX_PARTICLES]

    # ------------------------------------------------------------ simulation
    def step(self, dt):
        if self.last_tick < self.freeze_until:
            return  # freeze frame: everything holds still
        self._step_fx(dt)
        if self.state != "play":
            return
        self.t += dt
        self._spawn(dt)
        self._move(dt)
        if self.kiezblock is not None:
            kb = self.kiezblock
            # one car every 0.07 s, front ones first
            while kb["queue"] and self.state == "play" and self.t - kb["start"] >= 0.07 * kb["done"]:
                m = kb["queue"].pop(0)
                kb["done"] += 1
                if m not in self.movers:
                    continue
                if m.kind == "a100":
                    m.hp = max(1, m.hp - 4)
                    m.flash_until = self.last_tick + 0.1
                else:
                    self._convert(m, chain=True)
                    self._shake(0.1, 6)
            if not kb["queue"] and self.t - kb["start"] > 1.4:
                self.kiezblock = None
        if self.combo and self.t - self.last_convert_t > COMBO_SECONDS:
            if self.combo >= COMBO_STEP:
                self.popups.append(dict(text="Combo vorbei", x=self.width // 2, y=HUD_HEIGHT + 40, age=0.0, color=WHITE, size=18))
            self.combo = 0
        if self.bubble is None and self.last_tick >= self.next_bubble_at:
            talkers = [m for m in self.movers if m.bad and m.kind in DRIVE_LINES and HUD_HEIGHT + 40 < m.y < self.play_bottom - 200]
            if talkers:
                m = random.choice(talkers)
                self._say(m, random.choice(DRIVE_LINES[m.kind]), 2.2)
            self.next_bubble_at = self.last_tick + random.uniform(3.0, 5.5)

    def _step_fx(self, dt):
        drag = 0.9 ** (dt * 30)
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[2] *= drag
            p[3] *= drag
            p[4] -= dt
        self.particles = [p for p in self.particles if p[4] > 0]
        for ring in self.rings:
            ring[2] += dt
        self.rings = [r for r in self.rings if r[2] < r[3]]
        for g in self.ghosts:
            g[3] += dt
        self.ghosts = [g for g in self.ghosts if g[3] < 0.16]
        for popup in self.popups:
            popup["age"] += dt
            popup["y"] -= 55 * dt
        self.popups = [p for p in self.popups if p["age"] < 0.9]
        for f in self.flying:
            f["age"] += dt
            if f["age"] >= 0.45:
                self.slots[f["slot"]] = (f["kind"], self.last_tick)
                sx, sy = self._slot_pos(f["slot"])
                self._burst(sx, sy, 8, [LEAF, LEAF_HI, K.PINK], speed=120, size=4)
        self.flying = [f for f in self.flying if f["age"] < 0.45]
        if self.bubble is not None and (self.last_tick > self.bubble["until"] or
                                        (self.bubble["mover"] is not None and self.bubble["mover"] not in self.movers
                                         and self.state == "play")):
            self.bubble = None

    def _difficulty(self):
        base_speed = min(265.0, 78.0 + 1.6 * self.t)
        interval = max(0.34, 1.25 - 0.0115 * self.t)
        return base_speed, interval

    def _free(self, lane, gap=14):
        tops = [m.y for m in self.movers if lane in m.lanes]
        return not tops or min(tops) >= HUD_HEIGHT + gap

    def _spawn(self, dt):
        self.spawn_in -= dt
        if self.spawn_in > 0:
            return
        base_speed, interval = self._difficulty()
        if self.t >= self.next_boss_at:
            pairs = [i for i in range(LANES - 1) if self._free(i, 60) and self._free(i + 1, 60)]
            if pairs:
                i = random.choice(pairs)
                m = self._add("a100", (i, i + 1), (self.lane_x(i) + self.lane_x(i + 1)) / 2, base_speed * KINDS["a100"]["speed"])
                self.next_boss_at = self.t + 42.0
                self.boss_warn_until = self.last_tick + 2.0
                self._say(m, random.choice(DRIVE_LINES["a100"]), 2.5)
                self.spawn_in = interval * 1.5
            else:
                self.spawn_in = 0.1
            return
        free = [i for i in range(LANES) if self._free(i)]
        if not free:
            self.spawn_in = 0.1
            return
        lane = random.choice(free)
        if self.t >= self.next_poller_at:
            self._add("poller", (lane,), self.lane_x(lane), base_speed * KINDS["poller"]["speed"])
            self.next_poller_at = self.t + random.uniform(22.0, 30.0)
            self.spawn_in = interval
            return
        kind = self._pick_kind()
        speed = base_speed * KINDS[kind]["speed"] * random.uniform(0.9, 1.1)
        if not KINDS[kind]["bad"]:
            speed = max(55.0, min(speed, 120.0))
        m = self._add(kind, (lane,), self.lane_x(lane), speed, variant=random.randrange(3))
        if kind == "suv" and self.t > 10 and random.random() < 1 / 25:
            m.einsicht = True
        self.spawn_in = interval * random.uniform(0.8, 1.2)

    def _pick_kind(self):
        t = self.t
        weights = {"suv": 6.0}
        if t > 6:
            weights["sport"] = 2.0
        if t > 14:
            weights["van"] = 2.5
        if t > 26:
            weights["panzer"] = 1.5 + min(2.0, (t - 26) / 30)
        if t > 9:
            good = min(2.6, 1.0 + (t - 9) / 25)
            for kind in ("lastenrad", "kita", "enten"):
                weights[kind] = good
        kinds = list(weights)
        return random.choices(kinds, [weights[k] for k in kinds])[0]

    def _add(self, kind, lanes, x, speed, variant=0):
        m = _Mover(kind, lanes, x, 0, speed, variant)
        m.y = HUD_HEIGHT - m.h
        self.movers.append(m)
        return m

    def _move(self, dt):
        moved = []
        for m in sorted(self.movers, key=lambda m: -m.y):
            limit = None
            for lead in moved:
                if lead.y > m.y and set(lead.lanes) & set(m.lanes):
                    cap = lead.y - 10 - m.h
                    limit = cap if limit is None else min(limit, cap)
            speed = m.speed
            if m.einsicht and m.einsicht_at is not None:
                speed = 0.0
            new_y = m.y + speed * dt
            if limit is not None and new_y > limit and not m.leaked:
                new_y = max(m.y, limit)  # queue up behind the one in front, never roll back
            m.y = new_y
            moved.append(m)
            if m.einsicht and m.einsicht_at is None and m.y > HUD_HEIGHT + 120:
                m.einsicht_at = self.t
                self._say(m, EINSICHT_LINE, 1.6)
            if m.einsicht_at is not None and self.t - m.einsicht_at > 1.3:
                self._convert(m, einsicht=True)
                continue
            if not m.leaked and m.y + m.h >= self.play_bottom + 14:
                m.leaked = True
                if m.bad and m.kind != "poller":
                    self.popups.append(dict(text="HUUUP!", x=m.x, y=self.play_bottom - 20, age=0.0, color=RED, size=30))
                    self._say(m, random.choice(LEAK_LINES), 1.8)
                    self._lose_heart(m.x, self.play_bottom)
                    if self.state != "play":
                        return
                elif not m.bad:
                    gift = KINDS[m.kind]["m2"] * self.multiplier()
                    self.score += gift
                    self.popups.append(dict(text=f"Danke! +{gift}", x=m.x, y=self.play_bottom - 10, age=0.0,
                                            color=LEAF_HI, size=18))
        self.movers = [m for m in self.movers if m.y < self.height + 10]

    # ------------------------------------------------------------ drawing
    def _otext(self, surf, s, size, color, outline=INK, **pos):
        """Crisp KiezOS text with a 2 px outline (cached), for text over the street."""
        key = (s, size, color, outline)
        img = self._text_cache.get(key)
        if img is None:
            f = K.font(size)
            inner = f.render(s, False, color)
            out = f.render(s, False, outline)
            img = pygame.Surface((inner.get_width() + 4, inner.get_height() + 4), pygame.SRCALPHA)
            for dx, dy in ((0, 0), (2, 0), (4, 0), (0, 2), (4, 2), (0, 4), (2, 4), (4, 4)):
                img.blit(out, (dx, dy))
            img.blit(inner, (2, 2))
            if len(self._text_cache) > 300:
                self._text_cache.clear()
            self._text_cache[key] = img
        rect = img.get_rect(**pos)
        surf.blit(img, rect)
        return rect

    def _background(self):
        level = min(48, self.conversions)
        if self._bg_key == level:
            return self._bg
        base = _cached(("street", self.width, self.height), self._make_street)
        bg = base.copy()
        rnd = random.Random(161)
        for i in range(level):
            x = rnd.randint(SIDEWALK + 6, self.width - SIDEWALK - 6)
            y = rnd.randint(HUD_HEIGHT + 10, self.play_bottom - 10)
            if i % 3 == 0:  # crack with grass
                pts = [(x, y), (x + rnd.randint(-14, 14), y + 10), (x + rnd.randint(-14, 14), y + 22)]
                pygame.draw.lines(bg, (40, 34, 52), False, pts, 3)
            for j in range(3):
                pygame.draw.line(bg, LEAF if j % 2 else LEAF_HI, (x + j * 3 - 3, y), (x + j * 3 - 4 + j, y - 6 - j * 2), 2)
            if i % 4 == 1:
                pygame.draw.circle(bg, K.PINK if i % 8 == 1 else K.SUN, (x + 4, y - 9), 3)
        self._bg_key, self._bg = level, bg
        return bg

    def _make_street(self):
        s = pygame.Surface((self.width, self.height))
        s.fill(ASPHALT)
        rnd = random.Random(7)
        for _ in range(900):
            s.set_at((rnd.randrange(self.width), rnd.randrange(self.height)), ASPHALT_SPECK)
        for i in range(1, LANES):
            x = int(SIDEWALK + self.lane_w * i)
            for y in range(HUD_HEIGHT, self.play_bottom, 44):
                pygame.draw.rect(s, (150, 140, 175), (x - 2, y + 10, 4, 22))
        for x0 in (0, self.width - SIDEWALK):
            pygame.draw.rect(s, PAVING, (x0, 0, SIDEWALK, self.height))
            for y in range(0, self.height, 18):
                pygame.draw.line(s, PAVING_LINE, (x0, y), (x0 + SIDEWALK, y))
                off = 9 if (y // 18) % 2 else 0
                for x in range(x0 + off, x0 + SIDEWALK, 18):
                    pygame.draw.line(s, PAVING_LINE, (x, y), (x, y + 18))
        pygame.draw.rect(s, K.F_DARK, (SIDEWALK - 4, 0, 4, self.height))
        pygame.draw.rect(s, K.F_DARK, (self.width - SIDEWALK, 0, 4, self.height))
        # Spielstraße: lighter asphalt, chalk drawings.
        top = self.play_bottom
        pygame.draw.rect(s, (96, 84, 120), (SIDEWALK, top, self.width - 2 * SIDEWALK, SPIELSTRASSE_HEIGHT))
        for x in range(SIDEWALK, self.width - SIDEWALK, 24):  # dashed chalk line
            pygame.draw.rect(s, CHALK, (x, top, 14, 4))
        hop = [(0, 0), (0, 1), (1, 1), (0, 2)]  # Himmel und Hölle
        for cx, cy in hop:
            pygame.draw.rect(s, CHALK, (SIDEWALK + 14 + cy * 26, top + 12 + cx * 24 + (12 if cy % 2 == 0 else 0) - 12, 26, 24), 2)
        K.t95(s, "SPIELSTRASSE", 18, (self.width // 2 + 26, top + 26), color=CHALK, anchor="center")
        K.heart(s, (self.width // 2 - 40, top + 52), 2, K.PINK)
        pygame.draw.circle(s, K.SUN, (self.width - SIDEWALK - 30, top + 50), 10, 2)
        for a in range(8):
            ang = a * math.pi / 4
            p = (self.width - SIDEWALK - 30, top + 50)
            pygame.draw.line(s, K.SUN, (p[0] + math.cos(ang) * 13, p[1] + math.sin(ang) * 13),
                             (p[0] + math.cos(ang) * 18, p[1] + math.sin(ang) * 18), 2)
        # blue "Spielstraße" signs on both sidewalks
        for x0 in (6, self.width - SIDEWALK + 6):
            sign = pygame.Rect(x0, top + 6, 44, 34)
            pygame.draw.rect(s, (110, 110, 130), (sign.centerx - 2, sign.bottom, 4, 30))
            pygame.draw.rect(s, WHITE, sign)
            pygame.draw.rect(s, (40, 90, 200), sign.inflate(-4, -4))
            pygame.draw.circle(s, WHITE, (sign.x + 14, sign.y + 13), 4)
            pygame.draw.rect(s, WHITE, (sign.x + 11, sign.y + 17, 6, 9))
            pygame.draw.circle(s, WHITE, (sign.x + 31, sign.y + 24), 5, 2)  # ball
        return s

    def _draw_mover(self, surf, m):
        damage = m.max_hp - m.hp if m.kind not in ("poller", "a100") else 0
        if m.kind == "a100":
            damage = min(2, (m.max_hp - m.hp) * 3 // m.max_hp)
        sprite = vehicle_sprite(m.kind, m.variant, min(2, damage))
        rect = m.rect()
        surf.blit(_silhouette(sprite, (36, 30, 46)), rect.move(5, 6))  # shadow
        if m.kind == "poller":
            pulse = 0.5 + 0.5 * math.sin(self.last_tick * 8)
            r = int(38 + 8 * pulse)
            pygame.draw.circle(surf, (255, 220, 90), rect.center, r, 4)
            pygame.draw.circle(surf, (255, 245, 180), rect.center, r - 8, 2)
            for i in range(4):
                a = self.last_tick * 3 + i * math.pi / 2
                sx, sy = rect.centerx + math.cos(a) * (r + 6), rect.centery + math.sin(a) * (r + 6)
                pygame.draw.line(surf, WHITE, (sx - 5, sy), (sx + 5, sy), 2)
                pygame.draw.line(surf, WHITE, (sx, sy - 5), (sx, sy + 5), 2)
        flash = _white(sprite) if self.last_tick < m.flash_until else None
        if self.last_tick < m.squash_until:
            size = (int(m.w * 1.14), int(m.h * 0.88))
            sprite = pygame.transform.scale(sprite, size)
            flash = pygame.transform.scale(flash, size) if flash is not None else None
            rect = sprite.get_rect(center=rect.center)
        if self.last_tick < m.offended_until:
            rect = rect.move(int(math.sin(self.last_tick * 40) * 5), 0)
        surf.blit(sprite, rect)
        if flash is not None:
            surf.blit(flash, rect)
        if not m.bad and m.kind != "poller":
            K.heart(surf, (rect.centerx, rect.top - 8), 2, K.PINK)
        if m.kind == "a100":
            bar = pygame.Rect(rect.x + 20, rect.y - 16, rect.w - 40, 12)
            pygame.draw.rect(surf, INK, bar)
            pygame.draw.rect(surf, (240, 60, 60), (bar.x + 2, bar.y + 2, int((bar.w - 4) * m.hp / m.max_hp), bar.h - 4))

    def _draw_hud(self, surf):
        hud = pygame.Rect(0, 0, self.width, HUD_HEIGHT)
        K.bevel(surf, hud)
        lcd = pygame.Rect(8, 8, 300, 82)
        K.bevel(surf, lcd, sunken=True, face=K.CLOCK_OFF)
        K.t95(surf, "m² entsiegelt", 15, (lcd.x + 10, lcd.y + 6), color=(170, 130, 210), bold=False)
        K.t95(surf, self.format_score(self.score), 44, (lcd.x + 10, lcd.bottom - 4), color=K.CLOCK_ON, anchor="bottomleft")
        box = pygame.Rect(318, 8, self.width - 326, 82)
        K.bevel(surf, box, sunken=True, face=K.F_PAPER)
        K.t95(surf, "Spielstraße", 15, (box.centerx, box.y + 6), color=K.F_DARK, anchor="midtop", bold=False)
        lost_shake = self.last_tick < self.leak_flash_until
        for i in range(HEARTS):
            cx = box.x + 26 + i * (box.w - 52) // (HEARTS - 1)
            alive = i < self.hearts
            dx = int(math.sin(self.last_tick * 50) * 3) if lost_shake and i == self.hearts else 0
            K.heart(surf, (cx + dx, box.y + 52), 4, K.PINK if alive else (190, 180, 205))
        # combo row: multiplier badge, combo timer bar, record
        mult = self.multiplier()
        badge = pygame.Rect(8, 98, 64, 38)
        K.bevel(surf, badge, face=K.PINK if mult > 1 else K.F_FACE)
        K.t95(surf, f"x{mult}", 22, badge.center, color=WHITE if mult > 1 else K.F_DARK, anchor="center")
        bar = pygame.Rect(80, 98, 190, 38)
        K.bevel(surf, bar, sunken=True, face=K.F_PAPER)
        if self.combo and self.state == "play":
            left = max(0.0, 1.0 - (self.t - self.last_convert_t) / COMBO_SECONDS)
            fill = pygame.Rect(bar.x + 3, bar.y + 3, int((bar.w - 6) * left), bar.h - 6)
            pygame.draw.rect(surf, (200, 150, 255) if left > 0.3 else (255, 120, 150), fill)
        K.t95(surf, f"Combo {self.combo}" if self.combo else "Combo -", 17, bar.center, anchor="center")
        rec = party_games.best(self.NAME)
        rec_text = f"Rekord {self.format_score(rec['score'])}" if rec else "Rekord -"
        K.t95(surf, rec_text, 15, (self.width - 10, 104), color=K.F_DARK, anchor="topright")
        if rec:
            K.t95(surf, party_games.entry_name(rec)[:10], 15, (self.width - 10, 122), color=K.F_DARK, anchor="topright",
                  bold=False)
        if self.show_close:
            pygame.draw.rect(surf, party_games.CLOSE_ORANGE, self.close_rect)
            K.t95(surf, "x", 24, self.close_rect.center, anchor="center")

    def _draw_bubble(self, surf):
        b = self.bubble
        if b["mover"] is not None:
            m = b["mover"]
            anchor = (int(m.x), int(max(HUD_HEIGHT + 8, m.y + 6)))
        else:
            anchor = (int(b["pos"][0]), int(b["pos"][1]))
        area = pygame.Rect(4, HUD_HEIGHT + 4, self.width - 8, self.height - HUD_HEIGHT - 8)

        def box(max_w):
            lines = K.wrap(b["text"], 16, max_w)
            return lines, pygame.Rect(0, 0, max(K.font(16).size(ln)[0] for ln in lines) + 22, len(lines) * 24 + 12)

        lines, rect = box(300)
        rect.midbottom = (anchor[0], anchor[1] - 14)
        rect.clamp_ip(area)
        if rect.bottom > anchor[1] - 6:
            car = b["mover"].rect() if b["mover"] is not None else None
            if car is not None:
                # no room above the car (just entering under the HUD): beside it, not over it -
                # the bubble used to cover the very car (or A100) the player has to tap
                room_r, room_l = area.right - car.right - 12, car.left - 12 - area.left
                right = room_r >= room_l
                lines, rect = box(max(100, min(300, max(room_r, room_l) - 22)))
                y = max(car.top, HUD_HEIGHT) + 30
                if right:
                    rect.topleft = (car.right + 12, y)
                else:
                    rect.topright = (car.left - 12, y)
                rect.clamp_ip(area)
                anchor = (car.right - 6 if right else car.left + 6, min(rect.bottom + 14, self.height - 4))
            else:
                rect.top = anchor[1] + 30
        K.speech(surf, rect, lines, anchor, size=16)
        self.bubble_rect = rect

    def _draw_kiezblock_barrier(self, surf):
        kb = self.kiezblock
        age = self.t - kb["start"]
        p = min(1.0, age / 0.2)
        a = (SIDEWALK - 10, self.play_bottom - 60)
        b = (self.width - SIDEWALK + 10, HUD_HEIGHT + 60)
        end = (a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p)
        pygame.draw.line(surf, INK, a, end, 30)
        pygame.draw.line(surf, RED, a, end, 22)
        n = int(14 * p)
        for i in range(n):
            t0, t1 = i / 14, (i + 0.5) / 14
            pygame.draw.line(surf, WHITE, (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                             (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1), 22)
        for i in range(1, 4):  # planters on the barrier
            if i / 4 <= p:
                cx, cy = a[0] + (b[0] - a[0]) * i / 4, a[1] + (b[1] - a[1]) * i / 4
                surf.blit(product_sprite("hochbeet", 48), (int(cx) - 24, int(cy) - 34))

    def _draw_ready_panel(self, surf):
        K.wordart(surf, "KIEZBLOCK!", 46, (self.width // 2, HUD_HEIGHT + 62), wave=7)
        win = pygame.Rect(22, HUD_HEIGHT + 118, self.width - 44, 392)
        inner = K.dialog(surf, win, "anleitung.txt", buttons=None)
        pygame.draw.rect(surf, K.F_PAPER, inner)
        K.t95(surf, "Liebe Nachbar*innen,", 17, (inner.x + 12, inner.y + 8))
        # row 1: tap the SUV -> Hochbeet
        y = inner.y + 40
        suv = vehicle_sprite("suv", 0)
        small = _cached(("suv-small",), lambda: pygame.transform.scale(suv, (54, 78)))
        phase = (self.last_tick % 1.6) / 1.6
        sx = inner.x + 30
        pygame.draw.rect(surf, ASPHALT, (inner.x + 10, y - 6, 92, 92))
        if phase < 0.55:
            surf.blit(small, (sx, y))
            press = 0.3 < phase < 0.45
            if press:
                surf.blit(_white(small), (sx, y))
            surf.blit(_hand(46), (sx + 26, y + (34 if press else 44)))
        else:
            k = min(1.0, (phase - 0.55) * 6)
            prod = product_sprite("hochbeet", 48 + int(12 * k))
            surf.blit(prod, prod.get_rect(center=(sx + 27, y + 40)))
            for i in range(8):
                a = i * math.pi / 4
                pygame.draw.rect(surf, LEAF if i % 2 else K.PINK,
                                 (sx + 27 + math.cos(a) * 40 * k, y + 40 + math.sin(a) * 40 * k, 6, 6))
        K.t95(surf, "Autos antippen,", 17, (inner.x + 118, y + 14))
        K.t95(surf, "bis sie zu Beeten", 17, (inner.x + 118, y + 38))
        K.t95(surf, "werden!", 17, (inner.x + 118, y + 62))
        # row 2: don't tap these
        y += 104
        pygame.draw.line(surf, K.F_FACE, (inner.x + 10, y - 10), (inner.right - 10, y - 10), 2)
        x = inner.x + 16
        pygame.draw.rect(surf, ASPHALT, (inner.x + 10, y - 2, 160, 86))
        for kind in ("lastenrad", "kita", "enten"):
            spr = vehicle_sprite(kind)
            small = _cached(("good-small", kind), lambda spr=spr: pygame.transform.scale(spr, (spr.get_width() * 3 // 4, spr.get_height() * 3 // 4)))
            rect = small.get_rect(midtop=(x + 24, y + 4))
            surf.blit(small, rect)
            x += 52
        cross = pygame.Rect(inner.x + 10, y, 160, 82)
        pygame.draw.line(surf, RED, cross.topleft, cross.bottomright, 6)
        pygame.draw.line(surf, RED, cross.bottomleft, cross.topright, 6)
        K.t95(surf, "Die hier", 17, (inner.x + 186, y + 14))
        K.t95(surf, "NICHT!", 22, (inner.x + 186, y + 40), color=RED)
        # row 3: Spielstraße hearts
        y += 104
        pygame.draw.line(surf, K.F_FACE, (inner.x + 10, y - 10), (inner.right - 10, y - 10), 2)
        for i in range(3):
            K.heart(surf, (inner.x + 30 + i * 34, y + 30), 3, K.PINK)
        K.t95(surf, "Nix in die", 17, (inner.x + 136, y + 8))
        K.t95(surf, "Spielstraße lassen!", 17, (inner.x + 136, y + 32))
        K.t95(surf, "Goldener Poller = ???", 15, (inner.x + 12, inner.bottom - 26), color=K.F_DARK, bold=False)
        if int(self.last_tick * 2) % 2 == 0:
            self._otext(surf, self.READY_TEXT, 24, K.SUN, center=(self.width // 2, win.bottom + 34))

    def draw(self, surf):
        surf.blit(self._background(), (0, 0))
        for i, slot in enumerate(self.slots):
            if slot is None:
                continue
            kind, since = slot
            age = self.last_tick - since
            bounce = int(abs(math.sin(age * 12)) * 10 * max(0.0, 1 - age * 2.5))
            x, y = self._slot_pos(i)
            spr = product_sprite(kind, 48)
            surf.blit(spr, spr.get_rect(center=(x, y - bounce)))
        for m in self.movers:
            self._draw_mover(surf, m)
        if self.kiezblock is not None:
            self._draw_kiezblock_barrier(surf)
        for f in self.flying:
            k = f["age"] / 0.45
            sx, sy = self._slot_pos(f["slot"])
            x = f["x0"] + (sx - f["x0"]) * k
            y = f["y0"] + (sy - f["y0"]) * k - math.sin(k * math.pi) * 110
            spr = product_sprite(f["kind"], 48 + 8 * int(5 * math.sin(k * math.pi)))
            surf.blit(spr, spr.get_rect(center=(int(x), int(y))))
        for sprite, gx, gy, age in self.ghosts:
            k = age / 0.16
            ghost = pygame.transform.scale(sprite, (int(sprite.get_width() * (1 + 0.5 * k)), int(sprite.get_height() * (1 + 0.5 * k))))
            ghost.set_alpha(int(255 * (1 - k)))
            surf.blit(ghost, ghost.get_rect(center=(int(gx), int(gy))))
        for ring in self.rings:
            if ring[2] < 0:
                continue
            k = ring[2] / ring[3]
            pygame.draw.circle(surf, ring[4], (int(ring[0]), int(ring[1])), max(2, int(ring[5] * k)), max(1, int(6 * (1 - k)) + 1))
        for p in self.particles:
            size = max(1, int(p[7] * (p[4] / p[5]) + 1))
            surf.fill(p[6], (int(p[0]), int(p[1]), size, size))
        if self.last_tick < self.leak_flash_until:
            k = (self.leak_flash_until - self.last_tick) / 0.6
            pygame.draw.rect(surf, RED, (SIDEWALK, self.play_bottom, self.width - 2 * SIDEWALK, SPIELSTRASSE_HEIGHT),
                             max(1, int(8 * k)))
        for popup in self.popups:
            self._otext(surf, popup["text"], popup["size"], popup["color"], center=(int(popup["x"]), int(popup["y"])))
        if self.bubble is not None and self.state != "ready":
            self._draw_bubble(surf)
        if self.last_tick < self.boss_warn_until and int(self.last_tick * 6) % 2 == 0:
            band = pygame.Rect(0, HUD_HEIGHT + 4, self.width, 40)
            pygame.draw.rect(surf, RED, band)
            K.t95(surf, "ACHTUNG: A100-WEITERBAU!", 20, band.center, color=WHITE, anchor="center")
        self._draw_hud(surf)
        if self.wordart is not None:
            text, since = self.wordart
            age = self.last_tick - since
            if age < 1.1:
                pop = max(0.0, 1 - age / 0.15)
                size = 36 + 4 * int(pop * 4)
                K.wordart(surf, text, size, (self.width // 2, int(HUD_HEIGHT + 120 - age * 20)), wave=6)
            else:
                self.wordart = None
        if self.state == "ready":
            self._draw_ready_panel(surf)
        elif self.state == "over" and self.last_tick - self.over_at > 1.2:
            self._draw_over(surf)
        if self.last_tick < self.flash_until:
            flash = _cached(("flash", self.width, self.height, self.flash_color), lambda: self._make_flash(self.flash_color))
            surf.blit(flash, (0, 0))
        if self.last_tick < self.shake_until:
            # shake the street only: scrolling the whole surface smeared a stale band of the
            # HUD / dialog along the edges and shook the score display
            amp = self.shake_amp
            surf.subsurface((0, HUD_HEIGHT, self.width, self.height - HUD_HEIGHT)).scroll(
                random.randint(-amp, amp), random.randint(-amp, amp))

    def _make_flash(self, color):
        s = pygame.Surface((self.width, self.height))
        s.fill(color)
        s.set_alpha(150)
        return s
