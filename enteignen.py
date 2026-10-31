#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
ENTEIGNEN! (enteignen.exe): swipe-to-cut party game for the KiezOS 161
"Spiele" menu, a party_games._Game like STAPEL-TURM / FLAPPY BVG.

Money and luxury fly up from the bottom (€ coins, 500er, money bags, a DAX
ticker, RENDITE signs, MIETE +30% letters, gold, the yacht GIER, a private
jet). Swiping through one splits it along the actual swipe line: two halves
with a glowing fresh-cut edge tumble away. 1 point per cut, 3+ cuts in one
swipe = KIEZFEST (combo_bonus() extra + slow-mo). Protected things (the
neighbours' cat, the BVG bus, the Späti, a Pfandflasche) must not be cut: the
blade bounces off ("KLONK!") and one of three Kündigungsschutz hearts is gone.

A round is a survival run until the hearts are gone. Uncut money that falls
back down is Steuerflucht: it fills a meter (FLUCHT_MAX), a full meter costs
a heart. Hearts come back for good play: a 4+ KIEZFEST, STREAK_HEART cuts in
a row without a miss, every boss beaten. Waves get denser over time.

Bosses (BOSS_TIMES, then every BOSS_REPEAT s, one level stronger per cycle),
announced by a warning box, with a Win95 health-bar window:
- DAS PATRIARCHAT (~0:45): a stone plaque, juggled by cutting it; each cut
  breaks a letter out. Hitting the ground: -1 heart, it comes back. Minions:
  Grillzange, Protein-Shaker, ALPHA-Mikro, Krawatte, V12-Schlüssel, Bizeps-
  Sticker, Herrenwitz, Zigarre.
- MIETENHAI AG (~3:00): hydra tower -> 2 Tochter-GmbHs -> 4 Briefkasten-
  firmen, all juggled; small pieces falling = +3 Steuerflucht.
- DAS KAPITAL (~5:00): hovering golden piggy bank shielded by orbiting
  protected things; hits through the gaps spill money, it spits Mieterhöhungen.

The cut is juicy on purpose: 3-frame hit-stop, white flash, slash + glint,
"TSCHING!", sparks, screen shake, a rubber stamp ("ENTEIGNET",
"MIETE -50%", ...) slamming in between the halves, the points popup.

Input: PiDashboard.py passes the finger down as tap() (-> press), finger
movement as drag() and lifting as release(). A cut needs the finger to move
>= MIN_CUT_SEGMENT px since the last blade point (not a speed: on the Pi a
frame's touch events arrive in one burst, so their timestamps say nothing),
so a resting finger never cuts. Hit-stop counts frames, so it looks the same
at any frame rate. Big sprites (bosses) are rotated through _RotCache and
all HUD/popup text is pre-rendered (outlined_image) to hold 20 FPS on a Pi.
Based on the mockup scratch/game_mockups/slice/mock_slice.py.
"""

import math
import random

import pygame

import kiezos as K
import party_games

LIVES = 3
GRAVITY = 620.0  # px/s^2 for flying things (floaty arcs, readable at 20 FPS)
HALF_GRAVITY = 900.0
SCALE = 3  # every sprite is a small canvas scaled x3, nearest neighbour
KIEZ_H = 74  # Kiez strip at the bottom of the game area
MIN_CUT_SEGMENT = 10  # px the finger must move for a blade segment to cut
BLADE_SECONDS = 0.18  # how long the blade trail stays visible
HIT_STOP_FRAMES = 3
SLOWMO_SECONDS = 1.2
SLOWMO_FACTOR = 0.35

INK = K.INK
GOLD, GOLD_D, GOLD_L = (255, 208, 72), (200, 140, 30), (255, 240, 170)
GREEN, GREEN_D, GREEN_L = (110, 200, 130), (40, 120, 70), (190, 240, 190)
RED, RED_D = (230, 60, 80), (150, 20, 40)
WHITE = (255, 255, 255)
PINK = K.PINK
LILAC = (160, 90, 230)
BLUE = (110, 175, 255)
KHAKI = (222, 196, 130)
GREY_D, GREY_L = (100, 90, 110), (210, 205, 220)
ORANGE = (255, 150, 70)
BROWN = (130, 85, 55)
SAFE = (90, 255, 160)


# ------------------------------------------------------------ pixel sprites

def _canvas(w, h):
    return pygame.Surface((w, h), pygame.SRCALPHA)


def _tiny(s, text, size, pos, color, anchor="center"):
    img = K.font(size).render(text, False, color)
    s.blit(img, img.get_rect(**{anchor: pos}))


def _up(s):
    return pygame.transform.scale(s, (s.get_width() * SCALE, s.get_height() * SCALE))


def _ocircle(s, c, r, fill):
    pygame.draw.circle(s, INK, c, r + 1)
    pygame.draw.circle(s, fill, c, r)


def _spr_coin():
    s = _canvas(24, 24)
    _ocircle(s, (12, 12), 10, GOLD)
    pygame.draw.circle(s, GOLD_D, (12, 12), 8, 1)
    pygame.draw.arc(s, GOLD_D, (3, 3, 19, 19), math.pi * 1.25, math.pi * 1.9, 2)
    _tiny(s, "€", 14, (12, 12), GOLD_D)
    for p in [(6, 7), (7, 6), (6, 8), (8, 5)]:
        s.set_at(p, GOLD_L)
    return _up(s)


def _spr_note():
    s = _canvas(36, 20)
    pygame.draw.rect(s, INK, (0, 0, 36, 20))
    pygame.draw.rect(s, GREEN, (1, 1, 34, 18))
    pygame.draw.rect(s, GREEN_D, (3, 3, 30, 14), 1)
    pygame.draw.circle(s, GREEN_L, (11, 10), 5)
    pygame.draw.circle(s, GREEN_D, (11, 10), 5, 1)
    _tiny(s, "€", 9, (11, 10), GREEN_D)
    _tiny(s, "500", 9, (25, 10), GREEN_D)
    return _up(s)


def _spr_bag():
    s = _canvas(26, 30)
    body = [(9, 9), (17, 9), (23, 18), (24, 25), (20, 29), (6, 29), (2, 25), (3, 18)]
    pygame.draw.polygon(s, KHAKI, body)
    pygame.draw.polygon(s, INK, body, 1)
    pygame.draw.polygon(s, KHAKI, [(8, 2), (18, 2), (16, 8), (10, 8)])
    pygame.draw.polygon(s, INK, [(8, 2), (18, 2), (16, 8), (10, 8)], 1)
    pygame.draw.line(s, RED_D, (8, 9), (18, 9), 2)
    _tiny(s, "$", 15, (13, 20), GREEN_D)
    for p in [(6, 20), (6, 21), (7, 18)]:
        s.set_at(p, (245, 230, 190))
    return _up(s)


def _spr_ticker():
    s = _canvas(34, 26)
    pygame.draw.rect(s, INK, (0, 0, 34, 26))
    pygame.draw.rect(s, (200, 195, 215), (1, 1, 32, 24))
    pygame.draw.rect(s, (16, 24, 30), (3, 3, 28, 16))
    pts = [(4, 16), (8, 14), (11, 15), (15, 11), (18, 12), (22, 8), (25, 9), (29, 4)]
    pygame.draw.lines(s, (90, 255, 120), False, pts, 1)
    pygame.draw.polygon(s, (90, 255, 120), [(29, 3), (30, 7), (26, 5)])
    _tiny(s, "DAX", 8, (4, 2), (90, 255, 120), anchor="topleft")
    pygame.draw.rect(s, (130, 120, 150), (14, 20, 6, 3))
    pygame.draw.rect(s, INK, (10, 23, 14, 2))
    return _up(s)


def _spr_rendite():
    s = _canvas(42, 22)
    pygame.draw.rect(s, INK, (0, 0, 42, 22))
    pygame.draw.rect(s, WHITE, (1, 1, 40, 20))
    pygame.draw.rect(s, RED, (1, 1, 40, 8))
    _tiny(s, "RENDITE", 8, (21, 5), WHITE)
    _tiny(s, "+12%", 10, (17, 15), RED_D)
    pygame.draw.polygon(s, (40, 160, 90), [(34, 11), (38, 17), (30, 17)])
    return _up(s)


def _spr_miete():
    s = _canvas(36, 26)
    pygame.draw.rect(s, INK, (0, 0, 36, 26))
    pygame.draw.rect(s, (250, 246, 236), (1, 1, 34, 24))
    pygame.draw.lines(s, (200, 190, 175), False, [(1, 1), (18, 12), (34, 1)], 1)
    _tiny(s, "MIETE", 8, (18, 13), INK)
    _tiny(s, "+30%", 10, (18, 20), RED)
    pygame.draw.rect(s, LILAC, (27, 3, 6, 5))
    return _up(s)


def _spr_gold():
    s = _canvas(30, 16)
    pts = [(5, 1), (25, 1), (29, 15), (1, 15)]
    pygame.draw.polygon(s, GOLD, pts)
    pygame.draw.polygon(s, INK, pts, 1)
    pygame.draw.polygon(s, GOLD_L, [(6, 2), (24, 2), (25, 5), (5, 5)])
    _tiny(s, "999", 8, (15, 10), GOLD_D)
    return _up(s)


def _spr_yacht():
    s = _canvas(44, 26)
    pygame.draw.line(s, INK, (20, 1), (20, 14), 1)
    pygame.draw.polygon(s, WHITE, [(21, 2), (34, 13), (21, 13)])
    pygame.draw.polygon(s, INK, [(21, 2), (34, 13), (21, 13)], 1)
    pygame.draw.rect(s, WHITE, (10, 10, 12, 5))
    pygame.draw.rect(s, INK, (10, 10, 12, 5), 1)
    pygame.draw.rect(s, BLUE, (12, 12, 3, 2))
    pygame.draw.rect(s, BLUE, (17, 12, 3, 2))
    hull = [(1, 15), (43, 15), (37, 24), (6, 24)]
    pygame.draw.polygon(s, WHITE, hull)
    pygame.draw.line(s, (40, 60, 160), (4, 19), (40, 19), 2)
    pygame.draw.polygon(s, INK, hull, 1)
    _tiny(s, "GIER", 7, (24, 22), (40, 60, 160))
    return _up(s)


def _spr_jet():
    s = _canvas(48, 22)
    body = [(2, 11), (8, 7), (38, 7), (46, 11), (38, 15), (8, 15)]
    pygame.draw.polygon(s, WHITE, body)
    pygame.draw.polygon(s, INK, body, 1)
    pygame.draw.polygon(s, WHITE, [(6, 7), (2, 1), (8, 1), (13, 7)])
    pygame.draw.polygon(s, INK, [(6, 7), (2, 1), (8, 1), (13, 7)], 1)
    pygame.draw.polygon(s, GREY_L, [(18, 13), (28, 13), (20, 21), (14, 21)])
    pygame.draw.polygon(s, INK, [(18, 13), (28, 13), (20, 21), (14, 21)], 1)
    pygame.draw.line(s, GOLD, (8, 12), (40, 12), 1)
    for x in range(16, 36, 4):
        pygame.draw.rect(s, BLUE, (x, 9, 2, 2))
    pygame.draw.polygon(s, (60, 70, 110), [(40, 8), (45, 11), (40, 11)])
    _tiny(s, "$", 8, (5, 4), GOLD_D)
    return _up(s)


def _spr_cat():
    s = _canvas(28, 26)
    pygame.draw.line(s, INK, (22, 23), (26, 14), 4)
    pygame.draw.line(s, ORANGE, (22, 23), (26, 14), 2)
    body = [(6, 12), (18, 12), (22, 18), (22, 25), (4, 25), (4, 18)]
    pygame.draw.polygon(s, ORANGE, body)
    pygame.draw.polygon(s, INK, body, 1)
    _ocircle(s, (12, 9), 7, ORANGE)
    for ear in ([(5, 6), (6, 0), (10, 3)], [(14, 3), (18, 0), (19, 6)]):
        pygame.draw.polygon(s, ORANGE, ear)
        pygame.draw.polygon(s, INK, ear, 1)
    pygame.draw.circle(s, ORANGE, (12, 9), 6)
    for x in (9, 15):
        pygame.draw.rect(s, INK, (x - 1, 7, 2, 3))
    s.set_at((12, 11), PINK)
    pygame.draw.line(s, INK, (11, 12), (13, 12))
    for y in (16, 19, 22):
        pygame.draw.line(s, (220, 110, 40), (8, y), (11, y))
    pygame.draw.rect(s, (60, 130, 255), (8, 15, 9, 2))  # collar
    s.set_at((12, 17), GOLD)
    return _up(s)


def _spr_spaeti():
    s = _canvas(34, 32)
    pygame.draw.rect(s, INK, (1, 8, 32, 24))
    pygame.draw.rect(s, (240, 230, 210), (2, 9, 30, 22))
    for i in range(8):
        pygame.draw.polygon(s, RED if i % 2 == 0 else WHITE, [(1 + i * 4, 8), (5 + i * 4, 8), (5 + i * 4, 12), (1 + i * 4, 12)])
    pygame.draw.rect(s, INK, (1, 8, 32, 5), 1)
    pygame.draw.rect(s, INK, (3, 0, 28, 8))
    pygame.draw.rect(s, (40, 40, 60), (4, 1, 26, 6))
    _tiny(s, "SPÄTI", 7, (17, 4), (255, 230, 90))
    pygame.draw.rect(s, (120, 200, 255), (4, 15, 14, 10))
    pygame.draw.rect(s, INK, (4, 15, 14, 10), 1)
    for x, c in [(6, (60, 170, 80)), (9, (200, 120, 40)), (12, (230, 60, 80)), (15, (60, 170, 80))]:
        pygame.draw.rect(s, c, (x, 19, 2, 5))
    pygame.draw.rect(s, BROWN, (22, 16, 8, 15))
    pygame.draw.rect(s, INK, (22, 16, 8, 15), 1)
    s.set_at((28, 23), GOLD)
    return _up(s)


def _spr_pfand():
    s = _canvas(14, 34)
    bottle = [(5, 0), (9, 0), (9, 8), (12, 13), (12, 33), (2, 33), (2, 13), (5, 8)]
    pygame.draw.polygon(s, (60, 160, 90), bottle)
    pygame.draw.polygon(s, INK, bottle, 1)
    pygame.draw.rect(s, (230, 220, 160), (3, 17, 9, 9))
    _tiny(s, "0,25", 6, (7, 21), INK)
    pygame.draw.line(s, (150, 230, 170), (4, 14), (4, 30))
    return _up(s)


# ------------------------------------------------------------ minion sprites
# Boss 1's minions: objects of a masculinity our bubble rolls its eyes at
# (things and habits, never people). Boss 2's: what a Mietenhai sends.

STEEL, STEEL_D, STEEL_L = (178, 186, 205), (100, 108, 132), (236, 240, 250)
NIGHT = (44, 36, 56)
EMOJI, EMOJI_D = (255, 205, 60), (220, 150, 40)
PAPER = (250, 246, 236)


def _label(up, text, size, center, color, bold=True):
    """Crisp screen-resolution text on an already upscaled sprite (center in
    canvas px): tiny canvas fonts turn to mush when scaled x3."""
    img = K.font(size, bold).render(text, False, color)
    r = img.get_rect(center=(int(center[0] * SCALE), int(center[1] * SCALE)))
    up.blit(img, r)
    up.blit(img, r.move(1, 0))  # extra bold, closer to the chunky pixels
    return up


def _thick(s, a, b, w, fill):
    """Line with an INK outline, for metal rods."""
    pygame.draw.line(s, INK, a, b, w + 2)
    pygame.draw.line(s, fill, a, b, w)


def _spr_zange():
    """Grillzange with a sausage: the Grillmeister's sceptre."""
    s = _canvas(40, 18)
    pygame.draw.circle(s, INK, (3, 9), 3, 1)  # hanging ring
    _thick(s, (12, 8), (33, 3), 2, STEEL)
    _thick(s, (12, 10), (33, 15), 2, STEEL)
    for p in [(14, 7), (20, 6), (26, 4)]:
        s.set_at(p, STEEL_L)
    for x, y in [(33, 2), (35, 3), (33, 16), (35, 15)]:  # scalloped tips
        pygame.draw.rect(s, INK, (x, y, 2, 2))
    pygame.draw.rect(s, INK, (5, 6, 9, 7))
    pygame.draw.rect(s, BROWN, (6, 7, 7, 5))
    pygame.draw.line(s, (170, 115, 75), (6, 7), (12, 7))
    sausage = pygame.Rect(29, 5, 11, 8)
    pygame.draw.ellipse(s, INK, sausage)
    pygame.draw.ellipse(s, (205, 95, 60), sausage.inflate(-2, -2))
    for x in (32, 35):  # grill marks
        pygame.draw.line(s, (110, 40, 30), (x, 7), (x + 2, 11))
    s.set_at((31, 7), (255, 170, 130))
    return _up(s)


def _spr_shaker():
    """Protein-Shaker XXL with a flip cap and a lightning bolt."""
    s = _canvas(18, 32)
    pygame.draw.rect(s, INK, (3, 1, 12, 7))
    pygame.draw.rect(s, NIGHT, (4, 2, 10, 5))
    pygame.draw.rect(s, INK, (10, 0, 4, 3))
    pygame.draw.rect(s, (240, 60, 90), (11, 0, 2, 2))
    body = [(2, 7), (15, 7), (14, 31), (3, 31)]
    pygame.draw.polygon(s, (60, 80, 170), body)
    pygame.draw.polygon(s, INK, body, 1)
    pygame.draw.rect(s, (150, 255, 90), (3, 12, 11, 9))
    pygame.draw.line(s, INK, (3, 11), (14, 11))
    pygame.draw.line(s, INK, (3, 21), (14, 21))
    pygame.draw.polygon(s, EMOJI, [(9, 22), (6, 27), (8, 27), (7, 30), (11, 25), (9, 25), (10, 22)])
    for y in range(9, 30, 3):  # scale marks
        s.set_at((13, y), (190, 200, 255))
    pygame.draw.line(s, (120, 140, 230), (4, 23), (4, 29))
    return _label(_up(s), "XXL", 15, (8.7, 16.3), INK)


def _spr_mikro():
    """The ALPHA podcast microphone, ON AIR."""
    s = _canvas(26, 34)
    head = pygame.Rect(7, 1, 12, 17)
    pygame.draw.rect(s, INK, head, border_radius=6)
    pygame.draw.rect(s, (80, 76, 96), head.inflate(-2, -2), border_radius=5)
    for y in range(4, 16, 2):
        pygame.draw.line(s, (130, 125, 150), (9, y), (16, y))
    pygame.draw.line(s, STEEL_L, (9, 3), (9, 8))
    pygame.draw.rect(s, INK, (7, 17, 12, 3))
    pygame.draw.rect(s, GOLD, (8, 18, 10, 1))
    pygame.draw.rect(s, INK, (10, 20, 6, 5))
    pygame.draw.rect(s, (60, 56, 76), (11, 20, 4, 4))
    pygame.draw.line(s, INK, (13, 25), (13, 31), 2)
    pygame.draw.rect(s, INK, (6, 31, 14, 3))
    tag = pygame.Rect(1, 21, 24, 9)
    pygame.draw.rect(s, INK, tag)
    pygame.draw.rect(s, (225, 30, 50), tag.inflate(-2, -2))
    pygame.draw.circle(s, (255, 60, 60), (21, 4), 2)  # ON AIR light
    s.set_at((21, 3), (255, 200, 200))
    return _label(_up(s), "ALPHA", 15, (13, 25.5), WHITE)


def _spr_krawatte():
    """Krawatte with diagonal club stripes and a bit of shirt collar."""
    s = _canvas(18, 34)
    for wing in ([(2, 1), (8, 3), (5, 8)], [(16, 1), (10, 3), (13, 8)]):
        pygame.draw.polygon(s, WHITE, wing)
        pygame.draw.polygon(s, INK, wing, 1)
    blade = [(7, 7), (11, 7), (14, 26), (9, 32), (4, 26)]
    stripes = _canvas(18, 34)
    pygame.draw.polygon(stripes, RED, blade)
    for k in range(-20, 40, 5):
        pygame.draw.line(stripes, GOLD, (0, k), (18, k + 12), 2)
    mask = _canvas(18, 34)
    pygame.draw.polygon(mask, WHITE, blade)
    stripes.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    s.blit(stripes, (0, 0))
    pygame.draw.polygon(s, INK, blade, 1)
    knot = [(6, 2), (12, 2), (11, 7), (7, 7)]
    pygame.draw.polygon(s, RED_D, knot)
    pygame.draw.polygon(s, INK, knot, 1)
    s.set_at((8, 3), (255, 120, 130))
    return _up(s)


def _spr_schluessel():
    """Sportwagen-Schlüssel: V12 fob with a key blade."""
    s = _canvas(34, 20)
    pygame.draw.circle(s, INK, (4, 10), 4)
    pygame.draw.circle(s, STEEL, (4, 10), 3)
    pygame.draw.circle(s, (0, 0, 0, 0), (4, 10), 2)
    blade = [(24, 8), (33, 8), (33, 10), (31, 12), (29, 10), (27, 12), (24, 12)]
    pygame.draw.polygon(s, STEEL, blade)
    pygame.draw.polygon(s, INK, blade, 1)
    fob = pygame.Rect(7, 2, 18, 16)
    pygame.draw.rect(s, INK, fob, border_radius=5)
    pygame.draw.rect(s, NIGHT, fob.inflate(-2, -2), border_radius=4)
    pygame.draw.line(s, (110, 100, 130), (10, 4), (20, 4))
    pygame.draw.circle(s, (230, 40, 50), (12, 13), 2)
    pygame.draw.circle(s, (120, 110, 140), (19, 13), 2)
    return _label(_up(s), "V12", 15, (16, 8), GOLD)


_BIZEPS = [
    "..............oooooo......",
    ".............oyyywyyo.....",
    "............oyywyyyyyo....",
    "...........oyyyyyyyyyo....",
    "...........ooooyyyyyyo....",
    "...........oyyyyyyyyyo....",
    "...........ooooyyyyyyo....",
    "...........oyyyyyyyyyo....",
    "............ooooyyyyyo....",
    "..............oyyyyydo....",
    "..............oyyyyydo....",
    ".......oooo...oyyyyydo....",
    ".....ooyyyyoo.oyyyyydo....",
    "....oyywwyyyyooyyyyydo....",
    "...oywwyyyyyyyyyyyyydo....",
    "..oywyyyyyyyyyyyyyyydo....",
    "..oyyyyyyyyyyyyyyyyydo....",
    ".oyyyyyyyyyyyyyyyyydo.....",
    ".oyyyyyyyyyyyyyyyyydo.....",
    "oyyyddyyyyyyyyyyyydo......",
    "oyddddddyyyyyyyyddo.......",
    "oddddddddddddddddo........",
    ".ooooooooooooooooo........",
]


def _spr_bizeps():
    """Bizeps-Emoji as a die-cut sticker (white border, slight shadow)."""
    cols = {"o": INK, "y": EMOJI, "d": EMOJI_D, "w": (255, 248, 200)}
    art = _canvas(len(_BIZEPS[0]), len(_BIZEPS))
    for y, row in enumerate(_BIZEPS):
        for x, ch in enumerate(row):
            if ch in cols:
                art.set_at((x, y), cols[ch])
    s = _canvas(art.get_width() + 6, art.get_height() + 6)
    border = pygame.mask.from_surface(art).to_surface(setcolor=WHITE, unsetcolor=(0, 0, 0, 0))
    shadow = pygame.mask.from_surface(art).to_surface(setcolor=(30, 16, 50, 160), unsetcolor=(0, 0, 0, 0))
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if abs(dx) + abs(dy) <= 3:
                s.blit(shadow, (3 + dx + 1, 3 + dy + 1))
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if abs(dx) + abs(dy) <= 3:
                s.blit(border, (3 + dx, 3 + dy))
    s.blit(art, (3, 3))
    return _up(s)


def _spr_witz():
    """Herrenwitz speech bubble: "Kennste den...?"."""
    s = _canvas(44, 28)
    pygame.draw.polygon(s, INK, [(8, 17), (4, 27), (17, 17)])
    pygame.draw.rect(s, INK, (1, 1, 42, 18), border_radius=6)
    pygame.draw.rect(s, WHITE, (2, 2, 40, 16), border_radius=5)
    pygame.draw.polygon(s, WHITE, [(9, 17), (6, 24), (15, 17)])
    up = _up(s)
    _label(up, "Kennste", 16, (22, 6.3), INK)
    return _label(up, "den...?", 16, (22, 13.3), (200, 30, 60))


def _spr_zigarre():
    """Zigarre with a gold band, glowing tip and a smoke curl."""
    s = _canvas(40, 16)
    body = pygame.Rect(4, 7, 33, 7)
    pygame.draw.rect(s, INK, body, border_radius=3)
    pygame.draw.rect(s, (150, 92, 55), body.inflate(-2, -2), border_radius=2)
    for x in range(8, 34, 5):
        pygame.draw.line(s, (110, 64, 36), (x, 8), (x + 2, 12))
    pygame.draw.line(s, (190, 130, 85), (6, 9), (34, 9))
    pygame.draw.rect(s, RED_D, (26, 8, 5, 5))
    pygame.draw.rect(s, GOLD, (27, 8, 3, 5))
    pygame.draw.rect(s, (190, 185, 195), (2, 8, 3, 5))
    pygame.draw.rect(s, (255, 110, 50), (1, 9, 2, 3))
    s.set_at((1, 10), GOLD_L)
    for p in [(3, 6), (2, 5), (2, 4), (3, 3), (4, 2), (4, 1), (6, 0), (5, 3), (6, 4)]:
        s.set_at(p, (215, 210, 230))
    return _up(s)


def _spr_eigenbedarf():
    """Kündigung wegen Eigenbedarf, with a red seal."""
    s = _canvas(34, 30)
    sheet = [(1, 1), (27, 1), (33, 7), (33, 29), (1, 29)]
    pygame.draw.polygon(s, PAPER, sheet)
    pygame.draw.polygon(s, INK, sheet, 1)
    pygame.draw.polygon(s, (215, 205, 190), [(27, 1), (27, 7), (33, 7)])
    pygame.draw.polygon(s, INK, [(27, 1), (27, 7), (33, 7)], 1)
    pygame.draw.rect(s, (215, 30, 50), (2, 4, 24, 7))
    pygame.draw.circle(s, RED_D, (27, 24), 4)
    pygame.draw.circle(s, (240, 70, 80), (27, 24), 3)
    s.set_at((26, 23), (255, 170, 170))
    up = _up(s)
    _label(up, "KÜNDIGUNG", 13, (14, 7.6), WHITE)
    _label(up, "Eigen-", 15, (12.5, 15.5), INK)
    return _label(up, "bedarf", 15, (12.5, 21.5), INK)


def _spr_abstand():
    """An old flat key with a price tag: "Abstand 9.999 €" for a used kitchen."""
    s = _canvas(46, 22)
    pygame.draw.circle(s, INK, (5, 7), 5)
    pygame.draw.circle(s, GOLD, (5, 7), 4)
    pygame.draw.circle(s, (0, 0, 0, 0), (5, 7), 2)
    pygame.draw.rect(s, INK, (9, 5, 13, 4))
    pygame.draw.rect(s, GOLD, (9, 6, 12, 2))
    pygame.draw.rect(s, INK, (17, 8, 5, 5))
    pygame.draw.rect(s, GOLD_D, (18, 9, 3, 3))
    pygame.draw.line(s, INK, (21, 8), (22, 11))  # string
    tag = [(24, 4), (45, 4), (45, 21), (24, 21), (21, 12)]
    pygame.draw.polygon(s, PAPER, tag)
    pygame.draw.polygon(s, INK, tag, 1)
    s.set_at((24, 12), INK)
    up = _up(s)
    _label(up, "ABSTAND", 12, (34.5, 8.3), INK)
    return _label(up, "9.999€", 15, (34.5, 15.8), (215, 30, 50))


def _spr_lofts():
    """Makler sign on a post: LUXUS-LOFTS ab 1,2 Mio."""
    s = _canvas(46, 30)
    pygame.draw.rect(s, INK, (21, 19, 4, 11))
    pygame.draw.rect(s, BROWN, (22, 19, 2, 11))
    board = pygame.Rect(1, 1, 44, 19)
    pygame.draw.rect(s, INK, board)
    pygame.draw.rect(s, NIGHT, board.inflate(-2, -2))
    pygame.draw.rect(s, GOLD, board.inflate(-4, -4), 1)
    up = _up(s)
    _label(up, "LUXUS-LOFTS", 15, (23, 7.3), GOLD)
    return _label(up, "ab 1,2 Mio", 15, (23, 14), WHITE)


# ------------------------------------------------------------ boss sprites

STONE, STONE_L, STONE_D = (176, 166, 190), (218, 210, 228), (122, 110, 140)
FRESH = (232, 226, 240)  # freshly broken stone
CRACK = (58, 44, 74)
BRASS, BRASS_D = (232, 178, 70), (120, 80, 30)

PATRIARCHAT = "PATRIARCHAT"
P_BW, P_BH = 10, 15  # letter block size (canvas px)
P_X0, P_TOP = 16, 18  # first block x, top of the plaque (canvas px)
P_W, P_H = 2 * P_X0 + P_BW * len(PATRIARCHAT), 62


def _crown(s, x, y):
    """17x10 crown, top-left at (x, y)."""
    pts = [(x, y + 9), (x, y + 2), (x + 4, y + 5), (x + 8, y), (x + 12, y + 5), (x + 16, y + 2), (x + 16, y + 9)]
    pygame.draw.polygon(s, GOLD, pts)
    pygame.draw.polygon(s, INK, pts, 1)
    pygame.draw.rect(s, GOLD_D, (x + 1, y + 7, 15, 2))
    for px, c in [(x + 4, RED), (x + 8, BLUE), (x + 12, RED)]:
        pygame.draw.rect(s, c, (px - 1, y + 7, 2, 2))
    for px, py in [(x, y + 1), (x + 8, y - 1), (x + 16, y + 1)]:
        s.set_at((px, py), GOLD_L)
    pygame.draw.line(s, GOLD_L, (x + 2, y + 6), (x + 6, y + 6))


def _plaque_tie(s, cx, y):
    knot = [(cx - 3, y), (cx + 3, y), (cx + 2, y + 4), (cx - 2, y + 4)]
    blade = [(cx - 2, y + 4), (cx + 2, y + 4), (cx + 5, y + 15), (cx, y + 19), (cx - 5, y + 15)]
    pygame.draw.polygon(s, RED, blade)
    for k in (6, 10, 14):
        pygame.draw.line(s, GOLD, (cx - 4, y + k), (cx + 4, y + k + 3))
        pygame.draw.line(s, GOLD, (cx - 4, y + k + 1), (cx + 4, y + k + 4))
    pygame.draw.polygon(s, INK, blade, 1)
    pygame.draw.polygon(s, RED_D, knot)
    pygame.draw.polygon(s, INK, knot, 1)


def _letter_block(i, ch, crack, broken_left, broken_right, rnd):
    """One stone block of the PATRIARCHAT plaque with its carved gold letter."""
    b = _canvas(P_BW, P_BH + 6)  # + molding above/below
    pygame.draw.rect(b, STONE_D, (0, 0, P_BW, 3))  # top molding
    pygame.draw.line(b, STONE_L, (0, 0), (P_BW - 1, 0))
    pygame.draw.rect(b, STONE, (0, 3, P_BW, P_BH))
    pygame.draw.line(b, STONE_L, (0, 3), (P_BW - 1, 3))
    pygame.draw.line(b, STONE_D, (0, P_BH + 2), (P_BW - 1, P_BH + 2))
    pygame.draw.rect(b, STONE_D, (0, P_BH + 3, P_BW, 3))  # bottom molding
    pygame.draw.line(b, (90, 80, 105), (0, P_BH + 5), (P_BW - 1, P_BH + 5))
    for _ in range(5):  # stone grain
        b.set_at((rnd.randrange(1, P_BW - 1), rnd.randrange(4, P_BH + 2)), (160, 150, 176))
    glyph = K.font(13).render(ch, False, BRASS)
    shadow = K.font(13).render(ch, False, BRASS_D)
    r = glyph.get_rect(center=(P_BW // 2, 3 + P_BH // 2))
    b.blit(shadow, r.move(1, 1))
    b.blit(glyph, r)
    hl = K.font(13).render(ch, False, GOLD_L)  # top-left highlight: one row of light on the letter
    b.blit(hl, r.move(0, 0), area=pygame.Rect(0, 0, r.w, r.h // 2 - 2))
    b.blit(glyph, r.move(0, 1), area=pygame.Rect(0, 1, r.w, r.h))
    if i % 1 == 0 and i > 0 and not broken_left:
        pygame.draw.line(b, STONE_D, (0, 4), (0, P_BH + 1))  # mortar joint
    if crack >= 1:
        pts = [(rnd.randrange(2, P_BW - 2), 3)]
        for y in range(6, P_BH + 4, 3):
            pts.append((max(1, min(P_BW - 2, pts[-1][0] + rnd.choice((-2, -1, 1, 2)))), y))
        pygame.draw.lines(b, CRACK, False, pts)
        for p in pts[1:-1:2]:
            b.set_at((min(P_BW - 1, p[0] + 1), p[1]), FRESH)
    if crack >= 2:
        y = rnd.randrange(6, P_BH)
        pygame.draw.lines(b, CRACK, False, [(0, y), (3, y + 1), (5, y - 1), (P_BW - 1, y + 2)])
    for side, broken in ((0, broken_left), (P_BW - 1, broken_right)):
        if broken:  # chunky fresh break where the neighbour was knocked out
            y = 0
            while y < P_BH + 6:
                bite, run = rnd.choice((0, 1, 2, 2, 3)), rnd.choice((2, 3, 4))
                for yy in range(y, min(P_BH + 6, y + run)):
                    xs = range(0, bite) if side == 0 else range(P_BW - bite, P_BW)
                    for x in xs:
                        b.set_at((x, yy), (0, 0, 0, 0))
                    b.set_at((bite if side == 0 else P_BW - 1 - bite, yy), FRESH)
                y += run
    return b


def patriarchat_canvas(alive, cracks, cigar=True, crown=True):
    """The plaque at canvas scale (x1). alive / cracks per letter."""
    s = _canvas(P_W, P_H)
    n = len(PATRIARCHAT)
    blocks = []
    for i, ch in enumerate(PATRIARCHAT):
        if not alive[i]:
            continue
        rnd = random.Random(i * 7 + cracks[i] * 101)
        bl = _letter_block(i, ch, cracks[i], i > 0 and not alive[i - 1], i < n - 1 and not alive[i + 1], rnd)
        blocks.append((P_X0 + i * P_BW, bl))
    # INK outline around the whole remaining shape
    shape = _canvas(P_W, P_H)
    for x, bl in blocks:
        shape.blit(bl, (x, P_TOP))
    m = pygame.mask.from_surface(shape)
    outline = m.to_surface(setcolor=INK, unsetcolor=(0, 0, 0, 0))
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        s.blit(outline, (dx, dy))
    mid = n // 2
    if alive[mid] or alive[mid - 1]:  # "DAS" cartouche and the crown sit on the middle
        cart = _cartouche()
        pygame.draw.rect(s, INK, cart)
        pygame.draw.rect(s, STONE_D, cart.inflate(-2, -2))
        pygame.draw.line(s, STONE_L, (cart.x + 1, cart.y + 1), (cart.right - 2, cart.y + 1))
        if crown:
            _crown(s, cart.centerx - 8, cart.y - 10)
        _plaque_tie(s, P_X0 + mid * P_BW + P_BW // 2, P_TOP + P_BH + 4)
    s.blit(shape, (0, 0))
    if cigar and alive[-1]:
        cx = P_X0 + n * P_BW
        body = pygame.Rect(cx - 1, P_TOP + 9, 15, 5)
        pygame.draw.rect(s, INK, body, border_radius=2)
        pygame.draw.rect(s, (150, 92, 55), body.inflate(-2, -2))
        pygame.draw.rect(s, GOLD, (cx + 3, P_TOP + 10, 2, 3))
        pygame.draw.rect(s, (190, 185, 195), (cx + 12, P_TOP + 10, 2, 3))
        s.set_at((cx + 14, P_TOP + 11), (255, 110, 50))
    return s


def _cartouche():
    mid = len(PATRIARCHAT) // 2
    return pygame.Rect(P_X0 + mid * P_BW - 7, P_TOP - 8, 24, 9)


def patriarchat_image(alive, cracks, cigar=True, crown=True):
    up = _up(patriarchat_canvas(alive, cracks, cigar, crown))
    mid = len(PATRIARCHAT) // 2
    if alive[mid] or alive[mid - 1]:
        c = _cartouche()
        _label(up, "DAS", 16, (c.centerx, c.centery + 0.5), GOLD)
    return up


def patriarchat_block_image(i, crack=0):
    """One knocked-out letter block (x3), for the flying debris."""
    return _up(_letter_block(i, PATRIARCHAT[i], crack, False, False, random.Random(i)))


def _shark_teeth(s, x0, x1, y, h, down=True):
    for x in range(x0, x1, 3):
        tri = [(x, y), (x + 3, y), (x + 1.5, y + h if down else y - h)]
        pygame.draw.polygon(s, WHITE, tri)


def _mietenhai_tower(crack):
    """MIETENHAI AG: glass tower with a shark fin, eyes and a toothy lobby."""
    s = _canvas(34, 64)
    fin = [(9, 15), (13, 9), (19, 4), (26, 0), (24, 6), (25, 11), (27, 15)]  # dorsal fin on the roof
    pygame.draw.polygon(s, (120, 130, 160), fin)
    pygame.draw.polygon(s, INK, fin, 1)
    pygame.draw.lines(s, (190, 200, 225), False, [(13, 12), (18, 7), (23, 3)])
    pygame.draw.polygon(s, (90, 98, 130), [(24, 7), (25, 11), (26, 14), (21, 14)])
    pygame.draw.rect(s, INK, (5, 7, 1, 8))  # antenna
    pygame.draw.rect(s, (255, 70, 80), (4, 5, 3, 2))
    y0 = 15
    body = pygame.Rect(2, y0, 30, 49)
    pygame.draw.rect(s, INK, body)
    pygame.draw.rect(s, (82, 96, 140), body.inflate(-2, -2))
    pygame.draw.rect(s, (110, 130, 180), (3, y0 + 1, 6, 47))  # lit side
    sign = pygame.Rect(4, y0 + 2, 26, 7)
    pygame.draw.rect(s, INK, sign)
    pygame.draw.rect(s, (30, 40, 70), sign.inflate(-2, -2))
    for row in range(5):  # window grid (some lit)
        for col in range(4):
            x, y = 5 + col * 7, y0 + 11 + row * 5
            lit = (row * 3 + col) % 5 == 0
            pygame.draw.rect(s, (255, 220, 120) if lit else (150, 180, 230), (x, y, 5, 3))
            s.set_at((x, y), WHITE if not lit else GOLD_L)
    for ex, flip in ((10, 1), (24, -1)):  # angry eyes over the lobby
        pygame.draw.rect(s, WHITE, (ex - 3, y0 + 36, 6, 4))
        pygame.draw.rect(s, INK, (ex - 1 + flip, y0 + 37, 2, 3))
        pygame.draw.line(s, INK, (ex - 4, y0 + 34 + (flip < 0) * 2), (ex + 3, y0 + 34 + (flip > 0) * 2), 2)
    mouth = pygame.Rect(5, y0 + 41, 24, 7)
    pygame.draw.rect(s, (110, 20, 40), mouth)
    pygame.draw.rect(s, INK, mouth, 1)
    _shark_teeth(s, 6, 27, y0 + 42, 3)
    _shark_teeth(s, 7, 27, y0 + 47, 3, down=False)
    rnd = random.Random(5)
    for _ in range(crack):  # broken glass
        x, y = rnd.randrange(5, 28), rnd.randrange(y0 + 11, y0 + 35)
        pygame.draw.lines(s, WHITE, False, [(x, y), (x + 2, y + 2), (x + 1, y + 4), (x + 3, y + 6)])
        pygame.draw.line(s, INK, (x + 1, y), (x + 3, y + 2))
    return _label(_up(s), "HAI AG", 16, (17, y0 + 5.5), GOLD)


def _mietenhai_gmbh(crack):
    """Tochter-GmbH: a smaller office block with a little fin."""
    s = _canvas(24, 34)
    pygame.draw.polygon(s, INK, [(9, 6), (14, 0), (15, 6)])
    pygame.draw.polygon(s, (120, 130, 160), [(11, 6), (14, 2), (14, 6)])
    body = pygame.Rect(1, 6, 22, 28)
    pygame.draw.rect(s, INK, body)
    pygame.draw.rect(s, (96, 104, 150), body.inflate(-2, -2))
    sign = pygame.Rect(3, 8, 18, 6)
    pygame.draw.rect(s, (30, 40, 70), sign)
    for row in range(2):
        for col in range(3):
            pygame.draw.rect(s, (150, 180, 230), (4 + col * 6, 16 + row * 4, 4, 2))
    for ex in (7, 16):
        pygame.draw.rect(s, WHITE, (ex - 2, 25, 4, 3))
        s.set_at((ex, 26), INK)
        s.set_at((ex - 1, 26), INK)
    pygame.draw.line(s, INK, (4, 24), (9, 25))
    pygame.draw.line(s, INK, (14, 25), (19, 24))
    pygame.draw.rect(s, (110, 20, 40), (5, 29, 14, 4))
    _shark_teeth(s, 5, 18, 29, 2)
    if crack:
        pygame.draw.lines(s, WHITE, False, [(6, 15), (8, 18), (7, 21)])
    return _label(_up(s), "GmbH", 15, (12, 11), GOLD)


def _mietenhai_box():
    """Briefkastenfirma: a letterbox with a palm-tree sticker and "Ltd."."""
    s = _canvas(20, 24)
    pygame.draw.rect(s, INK, (9, 17, 3, 7))
    pygame.draw.rect(s, GREY_D, (10, 17, 1, 7))
    box = pygame.Rect(1, 1, 18, 17)
    pygame.draw.rect(s, INK, box, border_radius=3)
    pygame.draw.rect(s, (90, 150, 210), box.inflate(-2, -2), border_radius=2)
    pygame.draw.rect(s, INK, (4, 4, 12, 2))  # slot
    pygame.draw.line(s, (160, 205, 245), (3, 7), (3, 15))
    pygame.draw.rect(s, GOLD_L, (12, 14, 6, 2))  # island + palm sticker
    pygame.draw.lines(s, BROWN, False, [(15, 14), (15, 11), (14, 9)])
    for p in [(11, 9), (12, 8), (13, 8), (15, 8), (16, 8), (17, 9), (14, 7), (12, 10), (16, 10)]:
        s.set_at(p, (60, 200, 90))
    return _label(_up(s), "Ltd.", 14, (7, 11.5), WHITE)


def _pig_canvas(crack, hurt, hat=True, monocle=True):
    """DAS KAPITAL: a smug golden piggy bank with top hat and monocle."""
    s = _canvas(64, 50)
    body = pygame.Rect(8, 14, 48, 30)
    for lx in (14, 22, 40, 48):  # legs
        pygame.draw.rect(s, INK, (lx - 3, 38, 7, 10))
        pygame.draw.rect(s, GOLD_D, (lx - 2, 39, 5, 8))
    pygame.draw.ellipse(s, INK, body.inflate(2, 2))
    pygame.draw.ellipse(s, GOLD, body)
    pygame.draw.ellipse(s, GOLD_D, (14, 34, 38, 10))  # belly shade
    pygame.draw.ellipse(s, GOLD, (12, 29, 42, 12))
    pygame.draw.arc(s, GOLD_L, (12, 16, 30, 18), math.pi * 0.45, math.pi * 0.95, 2)
    for p in [(24, 18), (25, 18), (26, 18), (20, 20)]:
        s.set_at(p, WHITE)
    pygame.draw.rect(s, INK, (34, 14, 11, 3))  # coin slot
    pygame.draw.line(s, GOLD_D, (35, 17), (44, 17))

    tail = [(56, 26), (60, 24), (61, 21), (59, 20), (58, 22)]
    pygame.draw.lines(s, INK, False, tail, 2)
    snout = pygame.Rect(1, 24, 12, 10)
    pygame.draw.ellipse(s, INK, snout)
    pygame.draw.ellipse(s, (255, 226, 140), snout.inflate(-2, -2))
    pygame.draw.rect(s, INK, (4, 27, 2, 3))
    pygame.draw.rect(s, INK, (8, 27, 2, 3))
    ear = [(16, 17), (19, 8), (25, 15)]
    pygame.draw.polygon(s, GOLD, ear)
    pygame.draw.polygon(s, INK, ear, 1)
    pygame.draw.polygon(s, GOLD_D, [(18, 15), (19, 11), (22, 15)])
    ex, ey = 16, 22
    if hurt:  # > < squeezed eye
        pygame.draw.lines(s, INK, False, [(ex - 2, ey - 2), (ex + 1, ey), (ex - 2, ey + 2)], 1)
    else:  # smug half-closed eye
        pygame.draw.rect(s, WHITE, (ex - 2, ey - 1, 5, 3))
        pygame.draw.rect(s, INK, (ex - 1, ey, 2, 2))
        pygame.draw.line(s, INK, (ex - 3, ey - 2), (ex + 3, ey - 2), 2)  # heavy lid
    if monocle:
        pygame.draw.circle(s, INK, (ex, ey), 5, 1)
        pygame.draw.circle(s, GOLD_L, (ex, ey), 4, 1)
        for i in range(5):  # chain
            s.set_at((ex + 3 + i, ey + 5 + i * 2 // 2), GOLD_L if i % 2 else INK)
    if hat:
        pygame.draw.rect(s, INK, (19, 11, 20, 4))  # brim
        pygame.draw.rect(s, NIGHT, (20, 12, 18, 2))
        pygame.draw.rect(s, INK, (22, 0, 14, 12))
        pygame.draw.rect(s, NIGHT, (23, 1, 12, 10))
        pygame.draw.rect(s, (215, 30, 50), (23, 8, 12, 2))  # band
        pygame.draw.line(s, (90, 80, 110), (24, 2), (24, 7))
        _tiny(s, "$", 7, (29, 5), GOLD)
    rnd = random.Random(9)
    for _ in range(crack):  # porcelain-gold cracks
        x, y = rnd.randrange(22, 52), rnd.randrange(19, 38)
        pts = [(x, y)]
        for _ in range(4):
            pts.append((pts[-1][0] + rnd.choice((-2, -1, 1, 2)), pts[-1][1] + rnd.choice((1, 2))))
        pygame.draw.lines(s, (110, 70, 20), False, pts)
        for p in pts[1::2]:
            s.set_at((p[0] + 1, p[1]), GOLD_L)
    if hurt:
        for p in [(4, 20), (2, 19), (6, 18)]:  # sweat drops
            s.set_at(p, BLUE)
    return s


def kapital_image(crack, hurt, hat=True, monocle=True):
    up = _up(_pig_canvas(crack, hurt, hat, monocle))
    _label(up, "KAPITAL", 16, (36.3, 33.3), GOLD_L)  # embossed: light rim, dark face
    return _label(up, "KAPITAL", 16, (36, 33), GOLD_D)


# ------------------------------------------------------------ boss rewards

def _reward_cafe():
    """Frauen*-Café: pink awning, coffee in the window, a ♀ on the door."""
    s = _canvas(46, 30)
    pygame.draw.rect(s, INK, (1, 7, 44, 23))
    pygame.draw.rect(s, (205, 165, 235), (2, 8, 42, 21))
    pygame.draw.rect(s, INK, (0, 0, 46, 8))
    pygame.draw.rect(s, (60, 30, 80), (1, 1, 44, 6))

    for i in range(11):
        pygame.draw.polygon(s, PINK if i % 2 == 0 else WHITE, [(1 + i * 4, 8), (5 + i * 4, 8), (5 + i * 4, 12), (3 + i * 4, 13), (1 + i * 4, 12)])
    pygame.draw.line(s, INK, (1, 8), (45, 8))
    win = pygame.Rect(4, 15, 22, 11)
    pygame.draw.rect(s, INK, win)
    pygame.draw.rect(s, (255, 230, 160), win.inflate(-2, -2))
    pygame.draw.rect(s, WHITE, (8, 20, 6, 5))  # cup
    pygame.draw.rect(s, INK, (8, 20, 6, 5), 1)
    pygame.draw.rect(s, INK, (14, 21, 2, 2), 1)
    for p in [(10, 18), (11, 17), (12, 18), (11, 16)]:
        s.set_at(p, (150, 120, 140))
    pygame.draw.rect(s, (60, 170, 80), (19, 21, 5, 4))  # plant
    pygame.draw.rect(s, BROWN, (20, 24, 3, 1))
    door = pygame.Rect(31, 14, 11, 15)
    pygame.draw.rect(s, INK, door)
    pygame.draw.rect(s, (150, 70, 200), door.inflate(-2, -2))
    pygame.draw.circle(s, WHITE, (36, 19), 2, 1)  # ♀
    pygame.draw.line(s, WHITE, (36, 21), (36, 25))
    pygame.draw.line(s, WHITE, (34, 23), (38, 23))
    for i, x in enumerate(range(3, 44, 4)):  # string lights
        s.set_at((x, 14 if i % 2 else 13), [GOLD, PINK, BLUE][i % 3])
    return _label(_up(s), "FRAUEN*CAFÉ", 15, (23, 4), (255, 190, 230))


def _reward_haus():
    """Hausprojekt: Altbau with banners, a rainbow flag and balcony plants."""
    s = _canvas(34, 32)
    pygame.draw.polygon(s, INK, [(0, 6), (6, 0), (28, 0), (34, 6)])
    pygame.draw.polygon(s, (190, 80, 70), [(2, 6), (7, 1), (27, 1), (32, 6)])
    pygame.draw.rect(s, INK, (1, 6, 32, 26))
    pygame.draw.rect(s, (255, 200, 150), (2, 7, 30, 25))
    for row, y in enumerate((9, 16, 23)):
        for col, x in enumerate((5, 13, 21, 27)):
            if row == 1:
                continue
            pygame.draw.rect(s, INK, (x - 1, y - 1, 5, 6))
            pygame.draw.rect(s, (255, 230, 140) if (row + col) % 3 == 0 else (120, 150, 210), (x, y, 3, 4))
    banner = pygame.Rect(2, 15, 30, 7)
    pygame.draw.rect(s, INK, banner)
    pygame.draw.rect(s, WHITE, banner.inflate(-2, -2))
    pygame.draw.line(s, INK, (3, 8), (3, 14))  # flag from a window
    for i, c in enumerate([(230, 50, 60), (255, 150, 50), (255, 225, 70), (70, 180, 90), (70, 120, 230), (150, 70, 200)]):
        pygame.draw.line(s, c, (4, 8 + i), (8, 8 + i))
    for x in (4, 12, 20, 28):  # balcony plants
        pygame.draw.rect(s, (60, 170, 80), (x, 28, 3, 2))
        s.set_at((x + 1, 27), PINK)
    pygame.draw.rect(s, INK, (14, 27, 6, 5))
    pygame.draw.rect(s, BROWN, (15, 28, 4, 4))
    return _label(_up(s), "BLEIBT!", 15, (17, 18.6), (215, 30, 50))


def _reward_garten():
    """Kiezgarten: raised beds, sunflowers, a tomato plant and a sign."""
    s = _canvas(46, 30)
    for x in (4, 38):  # sunflowers
        pygame.draw.line(s, (60, 150, 70), (x, 8), (x, 24), 2)
        pygame.draw.circle(s, INK, (x, 6), 5)
        pygame.draw.circle(s, GOLD, (x, 6), 4)
        pygame.draw.circle(s, BROWN, (x, 6), 2)
        s.set_at((x + 2, 14), (60, 150, 70))
        s.set_at((x - 2, 16), (60, 150, 70))
    sign = pygame.Rect(9, 3, 28, 8)
    pygame.draw.rect(s, INK, sign)
    pygame.draw.rect(s, (220, 180, 120), sign.inflate(-2, -2))
    pygame.draw.rect(s, INK, (22, 11, 2, 7))
    for bx in (8, 25):  # raised beds with veg
        pygame.draw.rect(s, INK, (bx, 21, 14, 8))
        pygame.draw.rect(s, (170, 110, 65), (bx + 1, 22, 12, 6))
        pygame.draw.line(s, (120, 75, 40), (bx + 1, 25), (bx + 12, 25))
        for k in range(3):
            pygame.draw.rect(s, (70, 180, 90), (bx + 2 + k * 4, 17, 3, 4))
            s.set_at((bx + 3 + k * 4, 18), (230, 50, 60) if bx == 8 else (255, 150, 50))
    pygame.draw.rect(s, INK, (0, 28, 46, 2))
    return _label(_up(s), "KIEZGARTEN", 13, (23, 7.2), (30, 100, 55))


_SPRITES = {}
_GOODS = {}  # boss rewards, shown in the victory window


def _sprites():
    if not _SPRITES:
        for k, f in [("coin", _spr_coin), ("note", _spr_note), ("bag", _spr_bag), ("ticker", _spr_ticker),
                     ("rendite", _spr_rendite), ("miete", _spr_miete), ("gold", _spr_gold), ("yacht", _spr_yacht),
                     ("jet", _spr_jet), ("cat", _spr_cat), ("spaeti", _spr_spaeti), ("pfand", _spr_pfand),
                     ("zange", _spr_zange), ("shaker", _spr_shaker), ("mikro", _spr_mikro), ("krawatte", _spr_krawatte),
                     ("schluessel", _spr_schluessel), ("bizeps", _spr_bizeps), ("witz", _spr_witz),
                     ("zigarre", _spr_zigarre), ("eigenbedarf", _spr_eigenbedarf), ("abstand", _spr_abstand),
                     ("lofts", _spr_lofts)]:
            _SPRITES[k] = f()
        _SPRITES["bus"] = K.landmark_icon("bus", 96)
        for k, f in [("cafe", _reward_cafe), ("haus", _reward_haus), ("garten", _reward_garten)]:
            _GOODS[k] = f()
    return _SPRITES


# kind -> (stamp, spawn weight)
MONEY = {
    "coin": ("ENTEIGNET", 30),
    "note": ("ENTEIGNET", 22),
    "bag": ("ENTEIGNET", 14),
    "miete": ("MIETE -50%", 14),
    "rendite": ("GEDECKELT", 9),
    "ticker": ("KURSSTURZ", 7),
    "gold": ("ENTEIGNET", 6),
    "yacht": ("VERGESELL-SCHAFTET", 2),
    "jet": ("BLEIBT AM BODEN", 1),
}
# Boss minions: kind -> stamp. Not money, so they don't count for
# Steuerflucht when they fall back down.
MINIONS = {
    "zange": "DEKONSTRUIERT",
    "shaker": "DEKONSTRUIERT",
    "mikro": "ABGEMELDET",
    "krawatte": "LOCKER GEMACHT",
    "schluessel": "AUTOFREI!",
    "bizeps": "TOXISCH? WEG.",
    "witz": "NICHT LUSTIG",
    "zigarre": "AUSGEDRÜCKT",
    "eigenbedarf": "WIDERSPRUCH!",
    "abstand": "ABGELEHNT",
    "lofts": "BESETZT!",
}
PROTECTED = {
    "cat": ("katze.exe", ["Die Katze von nebenan", "ist kein Kapital."], "FAUCH!"),
    "bus": ("bvg.exe", ["Der Bus gehört", "uns allen."], "TÜT TÜT!"),
    "spaeti": ("späti.exe", ["Finger weg vom Späti!", "Der hat bis 3 auf."], "HEY!"),
    "pfand": ("pfand.exe", ["Das sind jemandes", "25 Cent!"], "KLIRR?!"),
}


# ------------------------------------------------------------ geometry

def _clip_halfplane(poly, p, n, side):
    """Sutherland-Hodgman: the part of poly with side * n.(q - p) >= 0."""
    def f(q):
        return side * ((q[0] - p[0]) * n[0] + (q[1] - p[1]) * n[1])
    out = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        fa, fb = f(a), f(b)
        if fa >= 0:
            out.append(a)
        if (fa >= 0) != (fb >= 0):
            t = fa / (fa - fb)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _seg_circle_hit(a, b, c, r):
    """Closest point on segment ab to c, if within r, else None."""
    ab = (b[0] - a[0], b[1] - a[1])
    l2 = ab[0] ** 2 + ab[1] ** 2
    if l2 == 0:
        return None
    t = max(0.0, min(1.0, ((c[0] - a[0]) * ab[0] + (c[1] - a[1]) * ab[1]) / l2))
    q = (a[0] + ab[0] * t, a[1] + ab[1] * t)
    return q if math.dist(q, c) < r else None


def split_image(img, p, d, n, side):
    """Pixels of img on one side of the line through p (direction d, normal
    n), with a glowing fresh-cut edge along the line."""
    w, h = img.get_size()
    other = _clip_halfplane([(0, 0), (w, 0), (w, h), (0, h)], p, n, -side)
    half = img.copy()
    if len(other) >= 3:
        pygame.draw.polygon(half, (0, 0, 0, 0), other)
    # the glowing edge: three lines along the cut, kept only where the half has
    # pixels (drawn + masked in C - a per-pixel Python loop cost ~1 ms per half on a Mac)
    reach = math.hypot(w, h)
    edge = _canvas(w, h)
    for k, col in ((3, (255, 200, 240)), (2, (255, 250, 200)), (1, (255, 255, 255))):
        ox, oy = n[0] * side * k, n[1] * side * k
        pygame.draw.line(edge, col, (p[0] - d[0] * reach + ox, p[1] - d[1] * reach + oy),
                         (p[0] + d[0] * reach + ox, p[1] + d[1] * reach + oy), 2 if k < 3 else 1)
    inside = pygame.mask.from_surface(half).to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
    edge.blit(inside, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    half.blit(edge, (0, 0))
    return half


# ------------------------------------------------------------ objects

ROT_STEP = 8  # degrees: flying things are drawn from rotation buckets (rotating every sprite every frame is the Pi's hotspot)
_ROT = {}


def _rotated(kind, angle):
    """A sprite rotated to the nearest ROT_STEP bucket, cached (bounded)."""
    b = int(round(angle / ROT_STEP)) % (360 // ROT_STEP)
    img = _ROT.get((kind, b))
    if img is None:
        if len(_ROT) > 500:
            _ROT.clear()
        img = _ROT[(kind, b)] = pygame.transform.rotate(_sprites()[kind], b * ROT_STEP)
    return img


class _Thing:
    def __init__(self, kind, x, y, vx, vy):
        self.kind = kind
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.angle = random.uniform(-20, 20)
        # text-heavy sprites spin less (nearest-neighbour rotation makes text jaggy)
        texty = ("miete", "rendite", "ticker", "spaeti", "witz", "eigenbedarf", "abstand", "lofts", "mikro", "shaker", "schluessel")
        self.spin = random.uniform(-40, 40) if kind in texty else random.uniform(-110, 110)
        self.protected = kind in PROTECTED
        self.r = 0.42 * math.hypot(*_sprites()[kind].get_size())
        self.dodge = 0.0  # protected things wobble after the blade bounced off
        self.immune_swipe = -1  # spilled by a boss hit: the same swipe can't cut it

    def image(self):
        return _rotated(self.kind, self.angle)

    def step(self, dt):
        self.vy += GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.angle += self.spin * dt
        self.dodge = max(0.0, self.dodge - dt)


class _Half:
    def __init__(self, surf, x, y, vx, vy, spin):
        self.surf, self.x, self.y, self.vx, self.vy, self.spin = surf, x, y, vx, vy, spin
        self.angle = 0.0

    def step(self, dt):
        self.vy += HALF_GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.angle += self.spin * dt

    def draw(self, surf, off):
        img = pygame.transform.rotate(self.surf, self.angle)
        surf.blit(img, img.get_rect(center=(self.x + off[0], self.y + off[1])))


class _Particle:
    def __init__(self, x, y, vx, vy, color, size, life, kind="sq", g=700.0):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.color, self.size, self.life, self.age, self.kind, self.g = color, size, life, 0.0, kind, g

    def step(self, dt):
        self.age += dt
        self.vy += self.g * dt
        self.vx *= 0.98
        self.x += self.vx * dt
        self.y += self.vy * dt

    def draw(self, surf, off):
        k = 1 - self.age / self.life
        if k <= 0:
            return
        x, y = int(self.x + off[0]), int(self.y + off[1])
        s = max(2, int(self.size * (0.5 + 0.5 * k)))
        if self.kind == "spark":  # streak along the velocity
            v = math.hypot(self.vx, self.vy) or 1
            length = 0.05 * v
            pygame.draw.line(surf, self.color, (x, y), (x - self.vx / v * length, y - self.vy / v * length), max(2, s // 2))
        elif self.kind == "flower":
            for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
                pygame.draw.rect(surf, self.color, (x + dx - 2, y + dy - 2, 4, 4))
            pygame.draw.rect(surf, GOLD, (x - 2, y - 2, 4, 4))
        else:
            pygame.draw.rect(surf, self.color, (x - s // 2, y - s // 2, s, s))
            pygame.draw.rect(surf, INK, (x - s // 2, y - s // 2, s, s), 1)


class _Popup:
    def __init__(self, text, x, y, color, size, life=0.9, rise=60, delay=0.0):
        self.text, self.x, self.y, self.color, self.size = text, x, y, color, size
        self.life, self.rise, self.delay = life, rise, delay
        self.age = 0.0

    def step(self, dt):
        self.age += dt
        if self.age > self.delay:
            self.y -= self.rise * dt


# ------------------------------------------------------------ drawing helpers

_OUTLINED = {}


def outlined_image(text, size, color, thick=2):
    """Text with an INK outline, pre-rendered once (the HUD and popups redraw
    the same few strings every frame; 24 blits per string is too much on a Pi)."""
    key = (text, size, color, thick)
    img = _OUTLINED.get(key)
    if img is None:
        if len(_OUTLINED) > 400:
            _OUTLINED.clear()
        f = K.font(size)
        fg = f.render(text, False, color)
        ol = f.render(text, False, K.F_INK)
        img = _canvas(fg.get_width() + 2 * thick, fg.get_height() + 2 * thick)
        for dx in range(-thick, thick + 1):
            for dy in range(-thick, thick + 1):
                if dx or dy:
                    img.blit(ol, (thick + dx, thick + dy))
        img.blit(fg, (thick, thick))
        _OUTLINED[key] = img
    return img


def outlined(s, text, size, color, center, thick=2, anchor="center"):
    img = outlined_image(text, size, color, thick)
    r = img.get_rect(**{anchor: (int(center[0]), int(center[1]))})
    s.blit(img, r)
    return r.inflate(-2 * thick, -2 * thick)


def _star(s, c, length, width, fill, rim, rot=0.0):
    """4-point glint star, long arm along rot (degrees)."""
    a = math.radians(rot)
    u = (math.cos(a), -math.sin(a))
    v = (-u[1], u[0])
    cx, cy = c
    q = width * 0.3
    pts = [(cx + u[0] * length, cy + u[1] * length), (cx + v[0] * q + u[0] * q, cy + v[1] * q + u[1] * q),
           (cx + v[0] * width, cy + v[1] * width), (cx + v[0] * q - u[0] * q, cy + v[1] * q - u[1] * q),
           (cx - u[0] * length, cy - u[1] * length), (cx - v[0] * q - u[0] * q, cy - v[1] * q - u[1] * q),
           (cx - v[0] * width, cy - v[1] * width), (cx - v[0] * q + u[0] * q, cy - v[1] * q + u[1] * q)]
    if rim:
        pygame.draw.polygon(s, rim, pts)
        pygame.draw.polygon(s, fill, [(cx + (x - cx) * 0.7, cy + (y - cy) * 0.7) for x, y in pts])
    else:
        pygame.draw.polygon(s, fill, pts)


_STAMPS = {}


def _stamp_image(text, angle):
    """Red rubber stamp with a light rim, readable on white letters and dark sky."""
    key = (text, angle)
    if key not in _STAMPS:
        lines = text.split("-") if len(text) > 12 else [text]
        lines = [ln + ("-" if i < len(lines) - 1 else "") for i, ln in enumerate(lines)]
        red, rim = (225, 25, 55), (255, 236, 240)
        f = K.font(24)
        imgs = [f.render(ln, False, red) for ln in lines]
        rims = [f.render(ln, False, rim) for ln in lines]
        w = max(i.get_width() for i in imgs) + 28
        h = sum(i.get_height() for i in imgs) + 18
        st = _canvas(w, h)
        pygame.draw.rect(st, rim, (0, 0, w, h), 8, border_radius=6)
        pygame.draw.rect(st, red, (2, 2, w - 4, h - 4), 4, border_radius=5)
        y = 9
        for im, rm in zip(imgs, rims):
            x = (w - im.get_width()) // 2
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                st.blit(rm, (x + dx, y + dy))
            st.blit(im, (x, y))
            st.blit(im, (x + 1, y))  # extra-bold ink
            y += im.get_height()
        rnd = random.Random(text)  # worn rubber: a few holes in the ink
        for _ in range(w * h // 60):
            p = (rnd.randrange(w), rnd.randrange(h))
            if st.get_at(p)[:3] == red:
                st.set_at(p, rim)
        _STAMPS[key] = pygame.transform.rotate(st, angle)
    return _STAMPS[key]


_BACKDROPS = {}


def _backdrop(w, h):
    """Berlin at dusk in KiezOS purple: Fernsehturm + Plattenbau silhouettes."""
    if (w, h) not in _BACKDROPS:
        s = pygame.Surface((w, h))
        for y in range(h):
            t = y / h
            s.fill((int(36 + 60 * t), int(18 + 34 * t), int(70 + 80 * t)), (0, y, w, 1))
        rnd = random.Random(4)
        for _ in range(50):
            s.fill((200, 180, 240), (rnd.randrange(w), rnd.randrange(int(h * 0.5)), 2, 2))
        base = h - KIEZ_H
        sil = (58, 36, 100)
        pygame.draw.rect(s, sil, (352, base - 400, 6, 400))  # Fernsehturm
        pygame.draw.circle(s, sil, (355, base - 300), 22)
        pygame.draw.rect(s, sil, (354, base - 470, 2, 80))
        s.fill((255, 120, 160), (354, base - 471, 3, 3))
        for x, bw, bh in [(0, 90, 170), (80, 70, 230), (150, 110, 140), (250, 90, 200), (330, 70, 120), (390, 90, 210)]:
            r = pygame.Rect(x, base - bh, bw, bh)
            pygame.draw.rect(s, (66, 42, 112), r)
            for wy in range(r.y + 10, r.bottom - 6, 14):
                for wx in range(r.x + 8, r.right - 8, 12):
                    lit = rnd.random() < 0.35
                    s.fill(((255, 210, 110) if rnd.random() < 0.7 else (150, 190, 255)) if lit else (52, 32, 90), (wx, wy, 5, 6))
        # the street at the bottom
        pygame.draw.rect(s, (70, 55, 95), (0, base, w, KIEZ_H))
        pygame.draw.rect(s, (120, 100, 150), (0, base, w, 6))
        for x in range(0, w, 24):
            pygame.draw.line(s, (90, 72, 120), (x, base + 6), (x, h))
        _BACKDROPS[(w, h)] = s
    return _BACKDROPS[(w, h)]


# ------------------------------------------------------------ run pacing

FLUCHT_MAX = 10  # uncut money that falls back down fills the Steuerflucht meter; full = -1 heart
STREAK_HEART = 15  # cuts in a row without letting money escape -> +1 heart
STREAK_STEP = 5  # every 5 cuts in a row: points multiplier +1 (up to STREAK_MAX_MULT), "5er-Serie!"
STREAK_MAX_MULT = 5
RAIN_GAP = (10.0, 15.0)  # a GELDREGEN (row of 4-6 coins/notes, made for one big swipe) every so often
COMBO_HEART = 4  # a KIEZFEST of 4+ in one swipe -> +1 heart
BOSS_TIMES = (45.0, 180.0, 300.0)  # then a boss every BOSS_REPEAT s, one level stronger per cycle
BOSS_REPEAT = 110.0
BOSS_GAP = 30.0  # at least this long between a victory and the next boss
BOSS_CALM = 3.0  # normal waves stop this long before a boss, so the screen clears
WARN_SECONDS = 2.6
VICTORY_SECONDS = 4.4
BOSS_GRAVITY = 520.0
BOSS_HIT_COOLDOWN = 0.2


def combo_bonus(n):
    """Extra points for n cuts in one swipe: 3 -> +3, 4 -> +8, 5 -> +15."""
    return n * (n - 2)


def _boss_time(no):
    return BOSS_TIMES[no] if no < len(BOSS_TIMES) else BOSS_TIMES[-1] + (no - len(BOSS_TIMES) + 1) * BOSS_REPEAT


def _boss_class(no):
    """(class, level) of the no-th boss of a run (0-based)."""
    return (_Patriarchat, _Mietenhai, _Kapital)[no % 3], no // 3 + 1


def _clock(seconds):
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


# ------------------------------------------------------------ boss geometry

def _dir(a, b):
    d = (b[0] - a[0], b[1] - a[1])
    length = math.hypot(*d) or 1.0
    d = (d[0] / length, d[1] / length)
    return d, (-d[1], d[0])


def _seg_box(a, b, box):
    """Liang-Barsky: (t0, t1) of segment ab inside box (x0, y0, x1, y1), or None."""
    x0, y0, x1, y1 = box
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)
    return t0, t1


def _to_local(p, c, angle):
    """Screen point -> coords in a sprite centred at c and rotated by angle (pygame degrees, ccw)."""
    a = math.radians(angle)
    dx, dy = p[0] - c[0], p[1] - c[1]
    return dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)


def _to_screen(q, c, angle):
    a = math.radians(angle)
    return c[0] + q[0] * math.cos(a) + q[1] * math.sin(a), c[1] - q[0] * math.sin(a) + q[1] * math.cos(a)


def _hit_box(a, b, c, angle, box):
    """Local midpoint of where segment ab crosses a rotated box, or None."""
    la, lb = _to_local(a, c, angle), _to_local(b, c, angle)
    t = _seg_box(la, lb, box)
    if t is None:
        return None
    tm = (t[0] + t[1]) / 2
    return la[0] + (lb[0] - la[0]) * tm, la[1] + (lb[1] - la[1]) * tm


class _RotCache:
    """Rotated copies of a big sprite in 3-degree steps (rotating a 400 px
    plaque every frame is too slow on a Pi)."""

    def __init__(self, step=3):
        self.step, self.d = step, {}

    def get(self, key, img, angle):
        b = int(round(angle / self.step)) * self.step
        k = (key, b)
        if k not in self.d:
            if len(self.d) > 60:
                self.d.clear()
            self.d[k] = pygame.transform.rotate(img, b)
        return self.d[k]


def _white_of(img):
    return pygame.mask.from_surface(img).to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))


def _safe_ring(surf, center, r, t):
    """Dashed green ring: "geschützt"."""
    rect = pygame.Rect(0, 0, 2 * r, 2 * r)
    rect.center = (int(center[0]), int(center[1]))
    for i in range(12):
        a0 = i * math.pi / 6 + t * 2
        pygame.draw.arc(surf, SAFE, rect, a0, a0 + 0.3, 3)


class _Body:
    """Something heavy that gets juggled by cutting it: gravity, wall
    bounces, a wobble that springs back to level (text stays readable)."""

    def __init__(self, x, y, half_w, gravity):
        self.x, self.y, self.vx, self.vy = x, y, 0.0, 0.0
        self.angle, self.spin = 0.0, 0.0
        self.half_w, self.g = half_w, gravity
        self.down_at = None  # fell out at the bottom: waits, then gets thrown up again

    def toss(self, apex_y, min_rise=60.0):
        self.vy = -math.sqrt(2 * self.g * max(min_rise, self.y - apex_y))

    def knock(self, d, local_x, width, apex_y):
        """A cut from below: back up to about apex_y, pushed towards the
        middle, spun by where it was hit."""
        self.toss(apex_y, 110.0)
        self.vx = max(-150.0, min(150.0, self.vx * 0.3 + d[0] * 90 + (width / 2 - self.x) * 0.7))
        self.spin += local_x / max(40.0, self.half_w) * 110 + random.uniform(-25, 25)

    def step(self, dt, width):
        self.vy += self.g * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        lo, hi = 4 + self.half_w, width - 4 - self.half_w
        if lo >= hi:
            self.x = width / 2
        elif self.x < lo or self.x > hi:
            self.x = max(lo, min(hi, self.x))
            self.vx = -self.vx * 0.7
        self.spin -= self.angle * 5 * dt
        self.spin *= max(0.0, 1 - 1.2 * dt)
        self.angle = max(-35.0, min(35.0, self.angle + self.spin * dt))


class _Boss:
    NAME = ""  # big name in the warning box
    EXE = ""  # title of its health-bar window
    TOAST = ""  # title of its "-1 heart" toast
    WARN = []  # lines in the warning box
    WIN = ("", "")  # victory WordArt
    REWARD = ("", "")  # (Kiez good, label) floating down after the victory
    BONUS = 0
    MINIONS = []
    MINION_GAP = (2.0, 2.8)
    SAYINGS = []
    STAMPS = ["ENTEIGNET"]

    def __init__(self, game, level):
        self.g, self.level = game, level
        self.t = 0.0  # boss clock
        self.hp = self.max_hp = 1
        self.hit_at = -9.0
        self.lost_at, self.lost_from = -9.0, 0
        self.stamp_i = 0
        self.say, self.say_at = None, -9.0
        self.next_say = 1.2
        self.last_swipe = -1

    @classmethod
    def title(cls, level):
        return cls.NAME + ("" if level == 1 else f" {level}.0")

    def damage(self):
        self.lost_from, self.lost_at = self.hp, self.t
        self.hp = max(0, self.hp - 1)
        self.hit_at = self.t

    def next_stamp(self):
        s = self.STAMPS[self.stamp_i % len(self.STAMPS)]
        self.stamp_i += 1
        return s

    def talk(self, sayings=None):
        if self.t >= self.next_say:
            self.say, self.say_at = random.choice(sayings or self.SAYINGS), self.t
            self.next_say = self.t + random.uniform(4.0, 6.0)

    def shout(self, text):
        self.say, self.say_at = text, self.t
        self.next_say = self.t + random.uniform(3.5, 5.0)

    def draw_say(self, surf, anchor):
        if not self.say or self.t - self.say_at > 2.0 or anchor is None:
            return
        tw = K.font(16).size(self.say)[0]
        r = pygame.Rect(0, 0, tw + 22, 38)
        r.midbottom = (int(anchor[0]) + 40, int(anchor[1]) - 22)
        r.clamp_ip(pygame.Rect(4, 158, self.g.width - 8, self.g.height - 240))
        tail = (int(anchor[0]), int(anchor[1]))
        if r.collidepoint(tail) or abs(tail[1] - r.centery) < 24:
            tail = (r.centerx - 20, r.bottom + 16)
        K.speech(surf, r, [self.say], tail, size=16)

    def center(self):
        return self.g.width / 2, self.g.height / 2


# ---- boss 1: DAS PATRIARCHAT -------------------------------------------

class _Patriarchat(_Boss):
    """A heavy stone plaque. Every cut knocks it back up and breaks the hit
    letter out; it must never hit the ground (-1 heart, then it comes back)."""

    NAME = "DAS PATRIARCHAT"
    EXE = "patriarchat.exe reagiert nicht mehr"
    TOAST = "patriarchat.exe"
    WARN = ["Immer wieder draufschneiden,", "Buchstabe für Buchstabe -", "nicht runterfallen lassen!"]
    WIN = ("PATRIARCHAT", "ZERSCHLAGEN!")
    REWARD = ("cafe", "Frauen*-Café")
    BONUS = 50
    MINIONS = ["zange", "shaker", "mikro", "krawatte", "schluessel", "bizeps", "witz", "zigarre"]
    SAYINGS = ["Das war schon immer so!", "Jetzt hab dich nicht so!", "Lass mich das mal erklären...",
               "Früher war alles besser!", "War doch nur ein Witz!", "Männer weinen nicht!", "Ein echter Mann grillt!"]
    STAMPS = ["ZERSCHLAGEN", "QUOTE!", "EQUAL PAY", "NEIN HEISST NEIN", "ABGESCHAFFT", "GLEICH-BERECHTIGT", "CARE-ARBEIT ZÄHLT"]
    APEX = 260

    def __init__(self, game, level):
        super().__init__(game, level)
        n = len(PATRIARCHAT)
        self.alive, self.cracks = [True] * n, [0] * n
        self.per = 1 if level == 1 else 2  # hits per letter
        self.lhp = [self.per] * n
        self.hp = self.max_hp = n * self.per
        self.cigar = self.crown = True
        self.version = 0
        self._img = {}
        self.rot = _RotCache()
        self.body = _Body(game.width / 2, game.height + 110, self._span()[1], BOSS_GRAVITY * (1 + 0.1 * (level - 1)))
        self.body.toss(self.APEX)
        self.body.spin = random.choice((-40.0, 40.0))
        self.smoke_at = 0.0
        self.next_say = 0.6

    # geometry in screen px relative to the image centre
    def _bx(self, i):
        return (P_X0 + i * P_BW + P_BW / 2) * SCALE - P_W * SCALE / 2

    def _by(self):
        return (P_TOP + (P_BH + 6) / 2) * SCALE - P_H * SCALE / 2

    def _span(self):
        idx = [i for i, a in enumerate(self.alive) if a] or [len(self.alive) // 2]
        x0 = self._bx(idx[0]) - P_BW * SCALE / 2
        x1 = self._bx(idx[-1]) + P_BW * SCALE / 2
        return (x0, x1), max(abs(x0), abs(x1))

    def _box(self):
        (x0, x1), _ = self._span()
        y0 = P_TOP * SCALE - P_H * SCALE / 2
        return x0 - 12, y0 - 14, x1 + 12, y0 + (P_BH + 6) * SCALE + 14

    def image(self):
        if self.version not in self._img:
            self._img.clear()
            img = patriarchat_image(self.alive, self.cracks, self.cigar, self.crown)
            self._img[self.version] = (img, _white_of(img))
        return self._img[self.version]

    def center(self):
        return self.body.x, self.body.y

    def step(self, dt):
        self.t += dt
        b, g = self.body, self.g
        if b.down_at is not None:
            if self.t - b.down_at > 1.5:  # "vertagt sich" - and is back
                b.down_at = None
                b.x, b.y, b.vx = g.width / 2 + random.uniform(-40, 40), g.height + 110, 0.0
                b.angle, b.spin = 0.0, random.choice((-40.0, 40.0))
                b.toss(self.APEX)
                self.shout("Ich bin noch nicht fertig!")
            return
        b.step(dt, g.width)
        if b.vy > 0 and b.y - 70 > g.height:
            b.down_at = self.t
            self.say = None
            g._lose_life(self.TOAST, ["Vertagt sich nur -", "kommt gleich wieder!"])
            return
        if self.cigar and self.t >= self.smoke_at:  # cigar smoke
            self.smoke_at = self.t + 0.12
            tip = _to_screen(((P_X0 + len(PATRIARCHAT) * P_BW + 14) * SCALE - P_W * SCALE / 2,
                              (P_TOP + 11) * SCALE - P_H * SCALE / 2), (b.x, b.y), b.angle)
            g.parts.append(_Particle(tip[0], tip[1] - 4, random.uniform(-20, 30), random.uniform(-60, -30),
                                     random.choice([(215, 210, 230), (180, 172, 200)]), 7, 1.1, g=-40))
        self.talk()

    def blade(self, a, b_):
        b, g = self.body, self.g
        if b.down_at is not None or self.hp <= 0 or self.t - self.hit_at < BOSS_HIT_COOLDOWN or g.swipe_id == self.last_swipe:
            return None
        q = _hit_box(a, b_, (b.x, b.y), b.angle, self._box())
        if q is None:
            return None
        self.last_swipe = g.swipe_id
        n = len(PATRIARCHAT)
        i = min((k for k in range(n) if self.alive[k]), key=lambda k: abs(self._bx(k) - q[0]))
        bx, by = _to_screen((self._bx(i), self._by()), (b.x, b.y), b.angle)
        self.damage()
        self.lhp[i] -= 1
        d, _ = _dir(a, b_)
        if self.lhp[i] <= 0:  # the letter breaks out and flies off in two halves
            self.alive[i] = False
            img = pygame.transform.rotate(patriarchat_block_image(i, self.cracks[i]), b.angle)
            g._split(img, bx, by, b.vx, b.vy, a, b_)
            for k in (i - 1, i + 1):
                if 0 <= k < n and self.alive[k]:
                    self.cracks[k] = min(2, self.cracks[k] + 1)
            for _ in range(18):  # stone dust
                g.parts.append(_Particle(bx, by, random.uniform(-260, 260), random.uniform(-320, 60),
                                         random.choice([STONE, STONE_L, STONE_D, BRASS]), random.randint(5, 9), random.uniform(0.5, 1.0)))
        else:
            self.cracks[i] = 2
        if self.cigar and self.hp <= self.max_hp * 0.75:
            self.cigar = False
            g.halves.append(_Half(pygame.transform.rotozoom(_SPRITES["zigarre"], 0, 0.7), b.x + b.half_w, b.y, 160, -260, 300))
            self.shout("Meine Zigarre!")
        if self.crown and self.hp <= self.max_hp * 0.45:
            self.crown = False
            c = _canvas(18, 12)
            _crown(c, 0, 1)
            g.halves.append(_Half(_up(c), b.x, b.y - 80, random.choice((-1, 1)) * 140, -380, 420))
            self.shout("Meine Krone?!")
        self.version += 1
        b.half_w = self._span()[1]
        b.knock(d, q[0], g.width, self.APEX)
        g._boss_hit(a, b_, bx, by, 40, self.next_stamp(), 5 * self.level)
        return "hit"

    def draw(self, surf, off):
        b = self.body
        if b.down_at is not None:
            return
        img, white = self.image()
        key = self.version
        if self.t - self.hit_at < 0.07:
            img, key = white, ("w", self.version)
        img = self.rot.get(key, img, b.angle)
        surf.blit(img, img.get_rect(center=(b.x + off[0], b.y + off[1])))

    def anchor(self):
        b = self.body
        return None if b.down_at is not None else (b.x + 30, b.y - 70)


# ---- boss 2: MIETENHAI AG -----------------------------------------------

_PIECE = {  # kind -> (apex y, gravity factor, local hitbox half extents (x, top, bottom))
    "ag": (250, 1.0, (52, 54, 96)),
    "gmbh": (290, 0.92, (38, 36, 52)),
    "box": (320, 0.85, (32, 38, 20)),
}


class _Piece(_Body):
    def __init__(self, kind, hp, x, y, gravity):
        super().__init__(x, y, _PIECE[kind][2][0], gravity * _PIECE[kind][1])
        self.kind, self.hp, self.crack = kind, hp, 0
        self.last_swipe, self.hit_at = -1, -9.0

    def box(self):
        hx, top, bottom = _PIECE[self.kind][2]
        return -hx - 10, -top - 10, hx + 10, bottom + 8


class _Mietenhai(_Boss):
    """Hydra: the tower takes a few cuts, then falls apart into two Tochter-
    GmbHs, each into two Briefkastenfirmen. Every piece is juggled; the
    tower hitting the ground costs a heart, small pieces flee to Luxemburg
    (+3 Steuerflucht) and get thrown back."""

    NAME = "MIETENHAI AG"
    EXE = "mietenhai_ag.exe wird vergesellschaftet"
    TOAST = "mietenhai_ag.exe"
    WARN = ["Schnitte zerlegen die Holding", "in Tochterfirmen - alle zerlegen!", "Was runterfällt, flieht."]
    WIN = ("MIETENHAI", "VERGESELLSCHAFTET!")
    REWARD = ("haus", "Hausprojekt")
    BONUS = 100
    MINIONS = ["eigenbedarf", "abstand", "lofts"]
    MINION_GAP = (2.6, 3.4)
    SAYINGS = ["Die Miete ist marktüblich!", "Eigenbedarf!", "Wir modernisieren!", "Möbliert = ohne Deckel!",
               "Ist doch nur eine Holding!", "Rendite ist kein Verbrechen!"]
    BOX_SAYINGS = ["Briefkasten in Luxemburg!", "Ich bin nur eine Adresse!", "Steuern? Nie gehört."]
    STAMPS = ["ENTEIGNET", "MIETENDECKEL", "VERGESELL-SCHAFTET"]

    def __init__(self, game, level):
        super().__init__(game, level)
        self.hp_of = {"ag": 3 + (level - 1), "gmbh": 1 + (level - 1), "box": 1}
        self.hp = self.max_hp = self.hp_of["ag"] + 2 * self.hp_of["gmbh"] + 4 * self.hp_of["box"]
        self.grav = BOSS_GRAVITY * (1 + 0.1 * (level - 1))
        tower = _Piece("ag", self.hp_of["ag"], game.width / 2, game.height + 140, self.grav)
        tower.toss(_PIECE["ag"][0])
        tower.spin = 30.0
        self.pieces = [tower]
        self._img = {}
        self.rot = _RotCache()

    def image(self, p):
        key = (p.kind, p.crack)
        if key not in self._img:
            img = {"ag": lambda: _mietenhai_tower(min(3, p.crack)), "gmbh": lambda: _mietenhai_gmbh(min(1, p.crack)),
                   "box": _mietenhai_box}[p.kind]()
            self._img[key] = (img, _white_of(img))
        return self._img[key]

    def center(self):
        if self.pieces:
            return self.pieces[0].x, self.pieces[0].y
        return super().center()

    def step(self, dt):
        self.t += dt
        g = self.g
        for p in self.pieces:
            if p.down_at is not None:
                if self.t - p.down_at > (1.5 if p.kind == "ag" else 1.0):
                    p.down_at = None
                    p.x, p.y, p.vx, p.angle, p.spin = random.uniform(120, g.width - 120), g.height + 100, 0.0, 0.0, 40.0
                    p.toss(_PIECE[p.kind][0])
                continue
            p.step(dt, g.width)
            if p.vy > 0 and p.y - 60 > g.height:
                p.down_at = self.t
                if p.kind == "ag":
                    g._lose_life(self.TOAST, ["Taucht nur ab -", "kommt gleich wieder!"])
                else:
                    g._add_flucht(3, p.x, "AB NACH LUXEMBURG!")
        if any(p.kind == "ag" for p in self.pieces):
            self.talk()
        else:
            self.talk(self.BOX_SAYINGS if any(p.kind == "box" for p in self.pieces) else None)

    def blade(self, a, b):
        g = self.g
        hit = False
        for p in list(self.pieces):
            if p.down_at is not None or p.last_swipe == g.swipe_id or self.t - p.hit_at < BOSS_HIT_COOLDOWN:
                continue
            q = _hit_box(a, b, (p.x, p.y), p.angle, p.box())
            if q is None:
                continue
            hit = True
            p.last_swipe, p.hit_at = g.swipe_id, self.t
            p.hp -= 1
            self.damage()
            d, _ = _dir(a, b)
            pts = {"ag": 5, "gmbh": 4, "box": 3}[p.kind] * self.level
            if p.hp > 0:
                p.crack += 1
                p.knock(d, q[0], g.width, _PIECE[p.kind][0])
                stamp = self.next_stamp()
            else:
                self.pieces.remove(p)
                img = pygame.transform.rotate(self.image(p)[0], p.angle)
                g._split(img, p.x, p.y, p.vx, p.vy, a, b)
                child = {"ag": "gmbh", "gmbh": "box"}.get(p.kind)
                stamp = {"ag": "ZERSCHLAGEN", "gmbh": "AUFGELÖST", "box": "AUFGEFLOGEN"}[p.kind]
                if child:
                    for side in (-1, 1):
                        c = _Piece(child, self.hp_of[child], p.x + side * 30, p.y, self.grav)
                        c.vx = side * 170 + p.vx * 0.3
                        c.toss(_PIECE[child][0], 140.0)
                        c.spin = side * 90.0
                        c.last_swipe = g.swipe_id  # the rest of this swipe can't chain into them
                        self.pieces.append(c)
                    if child == "gmbh":
                        self.shout("Ich hab ja noch Töchter!")
                    else:
                        self.shout("Ab nach Luxemburg!")
            g._boss_hit(a, b, p.x, p.y, 40, stamp, pts)
        return "hit" if hit else None

    def draw(self, surf, off):
        for p in self.pieces:
            if p.down_at is not None:
                continue
            img, white = self.image(p)
            key = (p.kind, p.crack)
            if self.t - p.hit_at < 0.07:
                img, key = white, ("w",) + key
            img = self.rot.get(key, img, p.angle)
            surf.blit(img, img.get_rect(center=(p.x + off[0], p.y + off[1])))

    def anchor(self):
        live = [p for p in self.pieces if p.down_at is None]
        if not live:
            return None
        p = live[0]
        return p.x + 20, p.y - _PIECE[p.kind][2][1]


# ---- boss 3: DAS KAPITAL ------------------------------------------------

_ORBIT_IMG = {}


def _orbit_img(kind):
    if kind not in _ORBIT_IMG:
        _ORBIT_IMG[kind] = pygame.transform.rotozoom(_sprites()[kind], 0, 0.72)
    return _ORBIT_IMG[kind]


def _hat_img():
    s = _canvas(20, 16)
    pygame.draw.rect(s, INK, (0, 11, 20, 4))
    pygame.draw.rect(s, NIGHT, (1, 12, 18, 2))
    pygame.draw.rect(s, INK, (3, 0, 14, 12))
    pygame.draw.rect(s, NIGHT, (4, 1, 12, 10))
    pygame.draw.rect(s, (215, 30, 50), (4, 8, 12, 2))
    return _up(s)


class _Kapital(_Boss):
    """A golden piggy bank hovering mid-screen, shielded by the protected
    things orbiting it (cut them: KLONK, -1 heart). Every hit through a gap
    spills money, and it keeps spitting Mieterhöhungen: whatever money falls
    back down uncut is Steuerflucht."""

    NAME = "DAS KAPITAL"
    EXE = "kapital.exe: schwerer Ausnahmefehler"
    TOAST = "kapital.exe"
    WARN = ["Katze, Bus, Späti & Pfand", "schützen es: durch die Lücken", "schneiden! Geld auffangen!"]
    WIN = ("KAPITAL", "ENTEIGNET!")
    REWARD = ("garten", "Kiezgarten")
    BONUS = 150
    SAYINGS = ["Too big to fail!", "Das regelt der Markt!", "Leistung muss sich lohnen!", "Trickle-down kommt gleich!",
               "Ich bin systemrelevant!", "Wer hat, dem wird gegeben!"]
    STAMPS = ["UMVERTEILT", "VERMÖGENS-STEUER", "ENTEIGNET", "GEMEINWOHL", "ERBSCHAFTS-STEUER"]
    RADIUS = 150
    ENTER = 1.8

    def __init__(self, game, level):
        super().__init__(game, level)
        self.hp = self.max_hp = 8 + 4 * (level - 1)
        kinds = ["cat", "bus", "spaeti", "pfand"] + (["cat"] if level > 1 else [])
        self.orbit = []
        for k in kinds:
            th = _Thing(k, 0, 0, 0, 0)
            th.r *= 0.72
            self.orbit.append(th)
        self.phi, self.dir, self.flipped = 0.0, 1, False
        self.cx, self.cy = game.width / 2, -160.0
        self.kick = [0.0, 0.0]
        self.hurt_until = -9.0
        self.next_spit = 3.0
        self.hat = self.monocle = True
        self._img = {}
        self.next_say = 1.0
        self._place(0.0)

    def image(self):
        crack = int((1 - self.hp / self.max_hp) * 6)
        key = (crack, self.t < self.hurt_until, self.hat, self.monocle)
        if key not in self._img:
            img = kapital_image(crack, key[1], self.hat, self.monocle)
            self._img[key] = (img, _white_of(img))
        return self._img[key]

    def center(self):
        return self.cx, self.cy

    def _place(self, dt):
        w, T = self.g.width, self.t
        x = w / 2 + 55 * math.sin(0.55 * T)
        y = 365 + 35 * math.sin(0.9 * T)  # orbit top stays below the boss bar window
        if T < self.ENTER:  # floats down from above
            k = T / self.ENTER
            y = -160 + (y + 160) * (1 - (1 - k) ** 3)
        decay = math.exp(-6 * dt)
        self.kick = [self.kick[0] * decay, self.kick[1] * decay]
        self.cx, self.cy = x + self.kick[0], y + self.kick[1]
        n = len(self.orbit)
        for i, th in enumerate(self.orbit):
            ang = self.phi + 2 * math.pi * i / n
            th.x, th.y = self.cx + self.RADIUS * math.cos(ang), self.cy + 10 + self.RADIUS * math.sin(ang)
            th.dodge = max(0.0, th.dodge - dt)

    def step(self, dt):
        self.t += dt
        speed = 0.7 + 0.2 * (self.level - 1) + 0.8 * (1 - self.hp / self.max_hp)
        if not self.flipped and self.hp <= self.max_hp / 2:
            self.dir, self.flipped = -self.dir, True
            self.shout("Plan B: Lobbyarbeit!")
        self.phi += self.dir * speed * dt
        self._place(dt)
        if self.t >= self.next_spit:  # spits Mieterhöhungen and Rendite: money to catch
            self.next_spit = self.t + random.uniform(2.6, 3.4) * (0.6 + 0.4 * self.hp / self.max_hp)
            kind = random.choice(["miete", "miete", "rendite", "note"])
            th = _Thing(kind, self.cx - 90, self.cy + 10, random.uniform(-200, 60), -random.uniform(260, 380))
            self.g.things.append(th)
            if kind == "miete" and random.random() < 0.5:
                self.shout("Mieterhöhung!")
        if self.t > self.ENTER:
            self.talk()

    def blade(self, a, b):
        g = self.g
        if self.t < self.ENTER or self.hp <= 0:
            return None
        for th in self.orbit:
            q = _seg_circle_hit(a, b, (th.x, th.y), th.r)
            if q is not None:
                g._bonk(th, q)
                self.shout("Schön beschützt!")
                return "bonk"
        if g.swipe_id == self.last_swipe or self.t - self.hit_at < BOSS_HIT_COOLDOWN:
            return None
        if _seg_circle_hit(a, b, (self.cx, self.cy + 12), 70) is None:
            return None
        self.last_swipe = g.swipe_id
        self.damage()
        d, _ = _dir(a, b)
        self.kick = [d[0] * 34, d[1] * 34]
        self.hurt_until = self.t + 0.35
        for _ in range(min(4, 1 + self.level)):  # spills money: cut it or it's Steuerflucht
            kind = random.choice(["coin", "coin", "note", "gold"])
            th = _Thing(kind, self.cx + random.uniform(-30, 30), self.cy, random.uniform(-200, 200), -random.uniform(360, 500))
            th.immune_swipe = g.swipe_id
            g.things.append(th)
        if self.monocle and self.hp <= self.max_hp * 0.7:
            self.monocle = False
            for _ in range(10):
                g.parts.append(_Particle(self.cx - 48, self.cy - 10, random.uniform(-200, 50), random.uniform(-300, 0), GOLD_L, 6, 0.6))
        if self.hat and self.hp <= self.max_hp * 0.4:
            self.hat = False
            g.halves.append(_Half(_hat_img(), self.cx, self.cy - 70, random.choice((-1, 1)) * 150, -420, 380))
            self.shout("Mein Zylinder!")
        if self.hp <= 0:  # piggy bank shatters: two halves and a rain of gold
            img = self.image()[0]
            g._split(img, self.cx, self.cy, 0, 0, a, b)
            for _ in range(70):
                g.parts.append(_Particle(self.cx, self.cy, random.uniform(-420, 420), random.uniform(-650, -100),
                                         random.choice([GOLD, GOLD_L, GOLD_D, WHITE]), random.randint(6, 10), random.uniform(1.0, 1.8), g=600))
        g._boss_hit(a, b, self.cx, self.cy, 70, self.next_stamp(), 6 * self.level)
        return "hit"

    def draw(self, surf, off):
        cx, cy = self.cx + off[0], self.cy + 10 + off[1]
        if self.t > self.ENTER * 0.6:  # the shield's orbit, dotted
            for i in range(36):
                ang = i * math.pi / 18 + self.phi * 0.5
                surf.fill(SAFE, (cx + self.RADIUS * math.cos(ang) - 2, cy + self.RADIUS * math.sin(ang) - 2, 4, 4))
        if self.hp > 0:
            img, white = self.image()
            if self.t - self.hit_at < 0.07:
                img = white
            surf.blit(img, img.get_rect(center=(self.cx + off[0], self.cy + off[1])))
        for th in self.orbit:
            img = _orbit_img(th.kind)
            _safe_ring(surf, (th.x + off[0], th.y + off[1]), int(th.r + 8), self.g.t)
            dx = math.sin(self.g.t * 60) * 5 if th.dodge > 0 else 0
            surf.blit(img, img.get_rect(center=(th.x + off[0] + dx, th.y + off[1])))

    def anchor(self):
        return self.cx - 40, self.cy - 70


# ------------------------------------------------------------ the game

class EnteignenGame(party_games._Game):
    NAME = "ENTEIGNEN!"
    ICON = "enteignen"
    READY_TEXT = "Einmal wischen zum Starten"
    SCORE_LABEL = "Punkte"
    SCORE_UNIT = ""

    @staticmethod
    def format_score(score):
        return str(int(score))

    def reset(self, now):
        super().reset(now)
        _sprites()
        self.things, self.halves, self.parts, self.popups = [], [], [], []
        self.blade = []  # [(x, y, t)] of the current swipe, newest last
        self.t = 0.0  # game clock (keeps running in hit-stop and slow-mo, for effects)
        self.play_t = 0.0  # survival clock (slow-mo slows it down too)
        self.lives = LIVES
        self.lost_life_at = -9.0
        self.freeze = 0  # hit-stop frames left
        self.flash = 0.0
        self.shake = 0.0
        self.slowmo_until = -1.0
        self.combo_text = None
        self.combo_at = -9.0
        self.slashes, self.glints, self.stamps = [], [], []
        self.toast = None  # (title, lines, born)
        self.klonk = None  # (x, y, born, thing)
        self.swipe_hits = 0
        self.swipe_id = 0
        self.bounced = False
        self.next_wave_at = 0.6
        self.cuts = 0
        self.streak = 0  # cuts since money last escaped / the blade hit something protected
        self.serie = None  # (WordArt text, born) of the last streak milestone
        self.next_rain_at = 12.0
        self.rain_queue = []  # [(due play_t, kind, x, vx, vy)]: GELDREGEN throws one after another
        self.best_combo = 0
        self.tap_pos = None
        self.flucht = 0  # Steuerflucht meter, 0..FLUCHT_MAX
        self.flucht_at = -9.0
        self.flucht_pop_at = -9.0
        self.boss = None
        self.boss_phase = None  # None, "warn", "fight", "victory"
        self.phase_at = 0.0  # play_t when the phase began
        self.boss_no = 0  # bosses met so far
        self.bosses_beaten = 0
        self.next_boss_at = _boss_time(0)
        self.next_minion_at = 0.0
        self.victory = None  # (wordart lines, born)
        self.heart_flies = []  # [(x, y, born)] hearts flying up into the HUD

    # ---- input --------------------------------------------------------
    def tap(self, x, y):
        self.tap_pos = (x, y)
        return super().tap(x, y)

    def start(self):
        self.press(*self.tap_pos)

    def play_tap(self):
        self.press(*self.tap_pos)

    def press(self, x, y):
        self.blade = [(x, y, self.t)]
        self.swipe_hits = 0
        self.swipe_id += 1
        self.bounced = False

    def drag(self, x, y):
        if self.state != "play" or self.bounced or self.lives <= 0:  # bounced: dead until lifted; 0 hearts: over at the next frame
            return
        if not self.blade:
            self.press(x, y)
            return
        a = self.blade[-1]
        if math.dist(a[:2], (x, y)) < MIN_CUT_SEGMENT:
            return  # a resting/jittering finger doesn't cut
        self.blade.append((x, y, self.t))
        for th in list(self.things):
            if th.immune_swipe == self.swipe_id:
                continue
            q = _seg_circle_hit(a[:2], (x, y), (th.x, th.y), th.r)
            if q is None:
                continue
            if th.protected:
                self._bonk(th, q)
                self.bounced = True
                return
            self._cut(th, a[:2], (x, y))
        if self.boss is not None and self.boss_phase == "fight":
            if self.boss.blade(a[:2], (x, y)) == "bonk":
                self.bounced = True

    def release(self):
        if self.state == "play" and self.swipe_hits >= 3:
            self._combo(self.swipe_hits)
        self.swipe_hits = 0
        self.blade = []

    # ---- events -------------------------------------------------------
    def _split(self, img, cx, cy, vx, vy, a, b):
        """img (centred at cx, cy) falls apart along the line a-b: two halves
        with glowing fresh-cut edges fly apart. Returns the cut point,
        direction and normal."""
        d, n = _dir(a, b)
        w, h = img.get_size()
        off = (cx - w / 2, cy - h / 2)
        t = (cx - a[0]) * d[0] + (cy - a[1]) * d[1]
        cpt = (a[0] + d[0] * t, a[1] + d[1] * t)  # point of the cut line closest to the centre
        p = (cpt[0] - off[0], cpt[1] - off[1])
        for side in (1, -1):
            surf = split_image(img, p, d, n, side)
            m = pygame.mask.from_surface(surf)
            if m.count() < 6:
                continue
            # only the visible pixels, so the per-frame rotation of a half stays cheap on a Pi
            box = surf.get_bounding_rect()
            piece = surf.subsurface(box).copy()
            mx, my = box.center
            sep = 210 + random.uniform(0, 60)
            self.halves.append(_Half(
                piece, off[0] + mx + n[0] * side * 10, off[1] + my + n[1] * side * 10,
                vx * 0.4 + n[0] * side * sep + d[0] * 90, vy * 0.3 + n[1] * side * sep - 120,
                side * random.uniform(240, 420) * (1 if d[0] >= 0 else -1)))
        return cpt, d, n

    def _cut_fx(self, cpt, d, n, x, y, r, stamp, pts, stamp_always=False):
        """Points + the juice of a cut: hit-stop, flash, slash, glint,
        TSCHING, stamp, "+1" popup, sparks. Returns True for the swipe's first cut."""
        self.cuts += 1
        self.streak += 1
        pts *= self.mult()
        self.score += pts
        self.swipe_hits += 1
        first = self.swipe_hits == 1
        self.freeze = HIT_STOP_FRAMES
        self.flash = 60.0
        self.shake = 7.0
        self.slashes.append((cpt, d, 2.6 * r + 140, self.t))
        up = -1 if n[1] < 0 else 1  # the normal pointing up the screen
        tsching_at = (cpt[0] - n[0] * up * (r + 34), cpt[1] - n[1] * up * (r + 34)) if first else None
        self.glints.append((cpt[0], cpt[1], math.degrees(math.atan2(-d[1], d[0])), self.t, tsching_at))
        if first or stamp_always:
            self.stamps.append((stamp, x, y, self.t, random.choice([-14, -9, 10, 13])))
        self.popups.append(_Popup(f"+{pts}", x, y - r - 4, GOLD, 26 if pts > 1 else 22, delay=0.18))
        for _ in range(22):  # gold + paper bits flying along the blade
            ang = math.atan2(d[1], d[0]) + random.uniform(-0.9, 0.9)
            v = random.uniform(200, 620)
            self.parts.append(_Particle(cpt[0], cpt[1], math.cos(ang) * v, math.sin(ang) * v - 120,
                                        random.choice([GOLD, GOLD_L, WHITE, GREEN, PINK]), random.randint(5, 9),
                                        random.uniform(0.5, 0.9)))
        for _ in range(10 if first else 4):  # white sparks across the cut
            side = random.choice((1, -1))
            ang = math.atan2(n[1] * side, n[0] * side) + random.uniform(-0.5, 0.5)
            v = random.uniform(400, 800)
            r0 = random.uniform(8, 50)  # pre-spread so the frozen frame already shows a burst
            self.parts.append(_Particle(cpt[0] + math.cos(ang) * r0, cpt[1] + math.sin(ang) * r0,
                                        math.cos(ang) * v, math.sin(ang) * v, WHITE, 8, 0.25, "spark", g=0))
        if self.streak % STREAK_STEP == 0:
            self.serie = (f"{self.streak}er-Serie!", self.t)
        if self.streak % STREAK_HEART == 0:
            self._gain_life(x, y, f"{STREAK_HEART} am Stück!")
        return first

    def mult(self):
        """Points multiplier of the current streak: x2 from 5 in a row, x3 from 10, ..."""
        return min(STREAK_MAX_MULT, 1 + self.streak // STREAK_STEP)

    def _break_streak(self):
        if self.streak >= STREAK_STEP:
            y = 172 if self.boss is not None else 92  # not behind the boss bar window (y 92..152)
            self.popups.append(_Popup("Serie gerissen!", self.width / 2, y, (255, 120, 140), 17, life=1.2, rise=10))
        self.streak = 0
        self.serie = None  # "25er-Serie!" must not stay up next to "Serie gerissen!"

    def _cut(self, th, a, b):
        self.things.remove(th)
        cpt, d, n = self._split(th.image(), th.x, th.y, th.vx, th.vy, a, b)
        minion = th.kind in MINIONS
        stamp = MINIONS[th.kind] if minion else MONEY[th.kind][0]
        self._cut_fx(cpt, d, n, th.x, th.y, th.r, stamp, 2 if minion else 1, stamp_always=minion)

    def _boss_hit(self, a, b, x, y, r, stamp, pts):
        d, n = _dir(a, b)
        t = (x - a[0]) * d[0] + (y - a[1]) * d[1]
        self._cut_fx((a[0] + d[0] * t, a[1] + d[1] * t), d, n, x, y, r, stamp, pts, stamp_always=True)
        self.shake = 11.0

    def _lose_life(self, title, lines):
        self.lives -= 1
        self.lost_life_at = self.t
        self.shake = 14.0
        self._break_streak()
        self.toast = (title, lines, self.t)

    def _gain_life(self, x, y, why, rise=40):
        if self.lives >= LIVES or self.lives <= 0:  # 0: the run is over, a boss beaten in the same frame doesn't revive it
            return
        self.lives += 1
        self.heart_flies.append((x, y, self.t, self.lives - 1))
        self.popups.append(_Popup("+1 Kündigungsschutz", x, y - 40, PINK, 20, life=1.6, rise=rise))
        self.popups.append(_Popup(why, x, y - 14, WHITE, 16, life=1.6, rise=rise))

    def _add_flucht(self, n, x, text="STEUERFLUCHT!"):
        self.flucht += n
        self.flucht_at = self.t
        self._break_streak()
        if self.t - self.flucht_pop_at > 0.35:
            self.flucht_pop_at = self.t
            px = max(130, min(self.width - 130, x))
            self.popups.append(_Popup(text, px, self.height - KIEZ_H - 26, (255, 90, 110), 17, life=1.1, rise=50))
        if self.flucht >= FLUCHT_MAX:
            self.flucht = 0
            self._lose_life("steuerflucht.exe", ["Zu viel Geld ist in", "Steueroasen verschwunden!"])

    def _bonk(self, th, q):
        th.dodge = 0.5
        th.vx += 140 if q[0] < th.x else -140
        th.vy -= 160
        title, lines, _ = PROTECTED[th.kind]
        self._lose_life(title, lines)
        self.freeze = HIT_STOP_FRAMES + 1
        self.klonk = (q[0], q[1], self.t, th)
        for _ in range(16):
            ang = random.uniform(0, 2 * math.pi)
            v = random.uniform(300, 650)
            self.parts.append(_Particle(q[0], q[1], math.cos(ang) * v, math.sin(ang) * v,
                                        random.choice([ORANGE, GOLD, WHITE]), 8, 0.3, "spark", g=0))

    def _combo(self, n):
        self.best_combo = max(self.best_combo, n)
        self.combo_text = f"{n}x UMVERTEILT!"
        self.combo_at = self.t
        self.slowmo_until = self.t + SLOWMO_SECONDS
        self.flash = 140.0
        bonus = combo_bonus(n)
        self.score += bonus
        self.popups.append(_Popup(f"+{bonus} KIEZFEST", self.width / 2, 260 if self.boss else 200, (90, 255, 120), 26, life=1.6, rise=20))
        for _ in range(50):
            ang = random.uniform(0, 2 * math.pi)
            v = random.uniform(150, 500)
            self.parts.append(_Particle(self.width / 2, 190, math.cos(ang) * v, math.sin(ang) * v - 100,
                                        random.choice([PINK, LILAC, GOLD, BLUE, GREEN, WHITE]), random.randint(5, 8), 1.4))
        if n >= COMBO_HEART:
            self._gain_life(self.width / 2, 330, f"{n}er-KIEZFEST!")

    def _victory(self):
        b = self.boss
        self.bosses_beaten += 1
        self.boss_no += 1
        bonus = b.BONUS * b.level
        self.score += bonus
        self.boss_phase, self.phase_at = "victory", self.play_t
        self.victory = (b.WIN, b.REWARD, self.t)
        self.freeze = 10
        self.flash = 230.0
        self.shake = 18.0
        cx, cy = b.center()
        w = self.width
        self.popups.append(_Popup(f"+{bonus} BOSS-BONUS", w / 2, 520, GOLD, 30, life=2.6, rise=14, delay=0.3))
        # one column under the reward window, all rising slowly: 520 bonus, 572/598 heart, 632 meter
        if self.flucht:
            self.flucht = 0
            self.popups.append(_Popup("Steuerflucht-Meter geleert", w / 2, 632, (90, 255, 160), 17, life=2.4, rise=14, delay=0.6))
        self._gain_life(w / 2, 612, "Boss besiegt!", rise=14)
        for _ in range(140):  # confetti from the top
            self.parts.append(_Particle(random.uniform(0, w), random.uniform(-80, 0), random.uniform(-80, 80), random.uniform(40, 220),
                                        random.choice([PINK, LILAC, GOLD, BLUE, GREEN, WHITE, ORANGE]), random.randint(5, 8),
                                        random.uniform(2.5, 4.0), g=160))
        for _ in range(60):
            ang = random.uniform(0, 2 * math.pi)
            v = random.uniform(200, 600)
            self.parts.append(_Particle(cx, cy, math.cos(ang) * v, math.sin(ang) * v - 150,
                                        random.choice([PINK, GOLD, WHITE, LILAC]), random.randint(6, 9), 1.6))
        self.boss = None

    # ---- simulation ---------------------------------------------------
    def _throw(self, kind):
        x = random.uniform(70, self.width - 70)
        peak = random.uniform(0.42, 0.78) * self.height  # how high above the bottom it flies
        vy = -math.sqrt(2 * GRAVITY * peak)
        vx = (self.width / 2 - x) * random.uniform(0.15, 0.6) + random.uniform(-40, 40)
        self.things.append(_Thing(kind, x, self.height + 40, vx, vy))

    def _spawn_wave(self):
        """1-3 things thrown up from below the Kiez; more, more often and more
        protected stuff the longer the run goes (after the 3rd boss: more)."""
        k = min(1.0, self.play_t / 120.0)
        e = min(1.0, max(0.0, self.play_t - 300.0) / 240.0)  # escalation after boss 3
        sizes = [1, 1, 1, 2, 2] if k < 0.4 else [1, 1, 2, 2, 3] if e < 0.3 else [1, 2, 2, 3, 3]
        protected_chance = 0.10 + 0.07 * k + 0.07 * e
        kinds = list(MONEY)
        weights = [MONEY[m][1] for m in kinds]
        for _ in range(random.choice(sizes)):
            self._throw(random.choice(list(PROTECTED)) if random.random() < protected_chance else random.choices(kinds, weights)[0])
        self.next_wave_at = self.play_t + random.uniform(1.6, 2.1) - 0.5 * k - 0.3 * e

    def _spawn_rain(self):
        """GELDREGEN: 4-6 coins/notes thrown one after another (0.15-0.35 s
        apart) from a loose row, with different heights and drift: they fly
        as a group, so a well-timed (or curved) swipe catches several, but
        it's not a free straight line through all of them (Ju: combos
        shouldn't be too easy)."""
        n = random.randint(4, 6)
        gap = 62
        x0 = random.uniform(70 + gap * (n - 1) / 2, self.width - 70 - gap * (n - 1) / 2)
        base_vy = -math.sqrt(2 * GRAVITY * random.uniform(0.5, 0.62) * self.height)
        vx = random.uniform(-30, 30)
        due = self.play_t
        order = list(range(n)) if random.random() < 0.5 else list(range(n))[::-1]
        for i in order:
            x = x0 + (i - (n - 1) / 2) * gap + random.uniform(-14, 14)
            self.rain_queue.append((due, random.choice(["coin", "coin", "note"]), x, vx + random.uniform(-25, 25),
                                    base_vy * random.uniform(0.9, 1.06)))
            due += random.uniform(0.15, 0.35)
        self.popups.append(_Popup("GELDREGEN!", self.width / 2, self.height - KIEZ_H - 40, GOLD, 26, life=1.2, rise=60))
        self.next_rain_at = self.play_t + random.uniform(*RAIN_GAP)
        self.next_wave_at = max(self.next_wave_at, self.play_t + 1.6)

    def _spawn_minions(self):
        b = self.boss
        for _ in range(random.choice([1, 1, 2] if b.level == 1 else [1, 2, 2])):
            self._throw(random.choice(list(PROTECTED)) if random.random() < 0.1 else random.choice(b.MINIONS))
        self.next_minion_at = self.play_t + random.uniform(*b.MINION_GAP)

    def _boss_clock(self, dt):
        if self.boss_phase is None:
            if self.play_t >= self.next_boss_at:
                self.boss_phase, self.phase_at = "warn", self.play_t
                self.shake = 12.0
        elif self.boss_phase == "warn":
            age = self.play_t - self.phase_at
            self.shake = max(self.shake, 5.0 * (1 - age / WARN_SECONDS))  # rumble
            if age >= WARN_SECONDS:
                cls, level = _boss_class(self.boss_no)
                self.boss = cls(self, level)
                self.boss_phase = "fight"
                self.next_minion_at = self.play_t + 3.0
        elif self.boss_phase == "fight":
            self.boss.step(dt)
            if self.boss.hp <= 0:
                self._victory()
            elif self.boss.MINIONS and self.play_t >= self.next_minion_at:
                self._spawn_minions()
        elif self.play_t - self.phase_at >= VICTORY_SECONDS:  # victory over: back to waves
            self.boss_phase = None
            self.victory = None
            self.next_boss_at = max(_boss_time(self.boss_no), self.play_t + BOSS_GAP)
            self.next_wave_at = self.play_t + 0.5
            self.next_rain_at = self.play_t + 4.0

    def step(self, dt):
        self.t += dt
        if self.freeze > 0:  # hit-stop: the world holds still, only the flash fades
            self.freeze -= 1
            self.flash *= 0.6
            return
        if self.state == "ready":
            return
        dt *= SLOWMO_FACTOR if self.t < self.slowmo_until else 1.0
        if self.state == "play":
            self.play_t += dt
            self._boss_clock(dt)
            if self.boss_phase is None and self.play_t < self.next_boss_at - BOSS_CALM:
                if self.play_t >= self.next_rain_at:
                    self._spawn_rain()
                elif self.play_t >= self.next_wave_at:
                    self._spawn_wave()
        for item in [q for q in self.rain_queue if self.play_t >= q[0]]:  # GELDREGEN throws that are due
            self.rain_queue.remove(item)
            th = _Thing(item[1], item[2], self.height + 40, item[3], item[4])
            th.spin *= 0.4
            self.things.append(th)
        for o in self.things + self.halves + self.parts + self.popups:
            o.step(dt)
        self.flash *= 0.55
        self.shake *= 0.6
        keep = []
        for th in self.things:
            if th.vy > 0 and th.y > self.height + 60:
                if self.state == "play" and th.kind in MONEY:  # uncut money got away
                    self._add_flucht(1, th.x)
            else:
                keep.append(th)
        self.things = keep
        self.parts = [p for p in self.parts if p.age < p.life]
        self.popups = [p for p in self.popups if p.age < p.delay + p.life]
        self.halves = [h for h in self.halves if h.y < self.height + 160]
        self.blade = [b for b in self.blade if self.t - b[2] < BLADE_SECONDS]
        self.heart_flies = [h for h in self.heart_flies if self.t - h[2] < 0.9]
        if self.state == "play" and self.lives <= 0:
            self.game_over(f"Kündigung nach {_clock(self.play_t)}!")

    def _entry_extra(self):
        return {"bosses": self.bosses_beaten, "seconds": int(self.play_t)}

    def _draw_entry_mark(self, surf, entry, x, y):
        for i in range(min(3, entry.get("bosses", 0))):  # a little gold star per boss beaten
            _star(surf, (x - 8 - i * 16, y), 9, 4, GOLD, None)

    # ---- drawing ------------------------------------------------------
    def draw(self, surf):
        off = (random.uniform(-1, 1) * self.shake, random.uniform(-1, 1) * self.shake)
        surf.blit(_backdrop(self.width, self.height), (0, 0))
        if self.boss is not None:
            self.boss.draw(surf, off)
        for th in self.things:
            if th.protected:
                _safe_ring(surf, (th.x + off[0], th.y + off[1]), int(th.r + 8), self.t)
            img = th.image()
            dx = math.sin(self.t * 60) * 5 if th.dodge > 0 else 0
            surf.blit(img, img.get_rect(center=(th.x + off[0] + dx, th.y + off[1])))
        self._draw_blade(surf)
        for h in self.halves:
            h.draw(surf, off)
        for p in self.parts:
            p.draw(surf, off)
        self._draw_cut_fx(surf, off)
        if self.boss is not None and self.state == "play":
            self.boss.draw_say(surf, self.boss.anchor())
        for p in self.popups:
            if p.age >= p.delay:
                outlined(surf, p.text, p.size, p.color, (p.x, p.y), thick=2)
        if self.t < self.slowmo_until:
            surf.blit(_slowmo_tint(self.width, self.height), (0, 0))
            outlined(surf, ">> ZEITLUPE <<", 15, (220, 160, 255), (self.width // 2, self.height - KIEZ_H - 18))
        if self.combo_text and self.t - self.combo_at < 1.6:
            K.wordart(surf, self.combo_text, 42, (self.width // 2, 200 if self.boss else 140), wave=7)
        elif self.serie and self.t - self.serie[1] < 1.2:
            K.wordart(surf, self.serie[0], 36, (self.width // 2, 200 if self.boss else 140), wave=5)
        self._draw_klonk(surf, off)
        self._draw_victory(surf)
        if self.flash > 2:
            fl = _white(self.width, self.height)
            fl.set_alpha(int(min(230, self.flash)))
            surf.blit(fl, (0, 0))
        if self.t - self.lost_life_at < 0.5:
            pygame.draw.rect(surf, (230, 30, 60), (0, 0, self.width, self.height), 10)
        if self.state == "ready":
            self._draw_start(surf)
            return
        self._draw_hud_bar(surf)
        self._draw_boss_bar(surf)
        self._draw_warn(surf)
        self._draw_toast(surf)
        if self.state == "over":
            self._draw_over(surf)

    def _draw_blade(self, surf):
        pts = [(x, y) for x, y, _ in self.blade]
        if len(pts) < 2:
            return
        n = len(pts)
        for col, scale in ((PINK, 1.0), (WHITE, 0.45)):  # tapered ribbon, pink rim, white core
            left, right = [], []
            for i, p in enumerate(pts):
                q = pts[i + 1] if i + 1 < n else p
                o = pts[i - 1] if i > 0 else p
                dx, dy = q[0] - o[0], q[1] - o[1]
                length = math.hypot(dx, dy) or 1
                w = (2 + 14 * (i / (n - 1))) * scale
                left.append((p[0] - dy / length * w, p[1] + dx / length * w))
                right.append((p[0] + dy / length * w, p[1] - dx / length * w))
            pygame.draw.polygon(surf, col, left + right[::-1])
        _star(surf, pts[-1], 18, 6, WHITE, None)

    def _draw_cut_fx(self, surf, off):
        for c, d, length, born in self.slashes:
            age = self.t - born
            if age > 0.35:
                continue
            k = 1 - age / 0.35
            a = (c[0] - d[0] * length / 2 + off[0], c[1] - d[1] * length / 2 + off[1])
            b = (c[0] + d[0] * length / 2 + off[0], c[1] + d[1] * length / 2 + off[1])
            n = (-d[1], d[0])
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            for col, ww in ((PINK, 7 * k + 6), (WHITE, 7 * k + 2)):  # lens-shaped slash
                pygame.draw.polygon(surf, col, [a, (mid[0] + n[0] * ww / 2, mid[1] + n[1] * ww / 2), b,
                                                (mid[0] - n[0] * ww / 2, mid[1] - n[1] * ww / 2)])
        for x, y, ang, born, txt_at in self.glints:
            age = self.t - born
            if age > 0.3:
                continue
            k = 1 - age / 0.3
            _star(surf, (x + off[0], y + off[1]), int(56 * k + 10), int(18 * k + 4), WHITE, PINK, rot=ang)
            if txt_at:
                outlined(surf, "TSCHING!", 32, GOLD, (txt_at[0] + off[0], txt_at[1] + off[1]), thick=3)
        for text, x, y, born, ang in self.stamps:
            age = self.t - born - 0.15  # slams in once the halves have parted
            if age < 0 or age > 0.9:
                continue
            img = _stamp_image(text, ang)
            scale = 1.0 + max(0.0, 0.1 - age) * 5
            if scale != 1.0:
                img = pygame.transform.scale(img, (int(img.get_width() * scale), int(img.get_height() * scale)))
            if age > 0.6:
                img = img.copy()
                img.set_alpha(int(255 * (0.9 - age) / 0.3))
            r = img.get_rect(center=(x + off[0], y + off[1] + 6))
            r.clamp_ip(pygame.Rect(0, 0, self.width, self.height))
            surf.blit(img, r)
        self.slashes = [s for s in self.slashes if self.t - s[3] <= 0.35]
        self.glints = [g for g in self.glints if self.t - g[3] <= 0.3]
        self.stamps = [s for s in self.stamps if self.t - s[3] <= 1.1]

    def _draw_klonk(self, surf, off):
        if not self.klonk or self.t - self.klonk[2] >= 0.6:
            return
        x, y, _, th = self.klonk
        _star(surf, (x + off[0], y + off[1]), 46, 30, ORANGE, INK)
        outlined(surf, "KLONK!", 34, ORANGE, (x + off[0], y + 70 + off[1]), thick=3)
        say = PROTECTED[th.kind][2]
        r = pygame.Rect(0, 0, K.font(18).size(say)[0] + 24, 38)
        r.midbottom = (th.x + 60, th.y - th.r - 18)
        top = 158 if self.boss is not None else 80  # below the HUD / the boss bar window
        r.clamp_ip(pygame.Rect(0, top, self.width, self.height - top))
        K.speech(surf, r, [say], (th.x + 10, th.y - th.r + 4), size=18)

    def _draw_victory(self, surf):
        if not self.victory:
            return
        (l1, l2), (good, label), born = self.victory
        age = self.t - born
        cy = 230
        surf.blit(_rays(self.width, int(age / 0.12) % 2), (0, cy - self.width // 2))
        drop = int(-60 * max(0.0, 0.25 - age) / 0.25)
        K.wordart(surf, l1, 46, (self.width // 2, cy - 30 + drop), wave=6)
        size = min(44, int((self.width - 40) / (0.6 * len(l2))))
        K.wordart(surf, l2, size, (self.width // 2, cy + 28 - drop), wave=6)
        if age > 0.5:  # what the Kiez got out of it: a window, clearly not something to cut
            img = _GOODS[good]
            r = pygame.Rect(0, 0, 300, img.get_height() + 74)
            r.midtop = (self.width // 2, 320)
            inner = K.dialog(surf, r, "neu_im_kiez.txt", icon="note", buttons=None)
            surf.blit(img, img.get_rect(midtop=(inner.centerx, inner.y + 4)))
            K.t95(surf, label, 17, (inner.centerx, inner.bottom - 12), anchor="center", color=K.F_ACCENT)

    def _draw_toast(self, surf):
        if not self.toast or self.t - self.toast[2] >= 1.5 or self.state != "play":
            return
        title, lines, _ = self.toast
        r = pygame.Rect(30, self.height - KIEZ_H - 150, self.width - 60, 120)
        inner = K.dialog(surf, r, title, icon="power", buttons=None)
        surf.blit(_warn_icon(), (inner.x + 6, inner.y + 10))
        for i, ln in enumerate(lines):
            K.t95(surf, ln, 17, (inner.x + 58, inner.y + 10 + i * 22))
        K.t95(surf, "-1 Kündigungsschutz", 15, (inner.x + 58, inner.y + 58), color=K.F_LATE)

    def _draw_warn(self, surf):
        """"Achtung: Boss im Anflug" box + blinking red frame before a boss."""
        if self.boss_phase != "warn" or self.state != "play":
            return
        cls, level = _boss_class(self.boss_no)
        if int(self.t * 6) % 2 == 0:
            pygame.draw.rect(surf, (230, 30, 60), (0, 0, self.width, self.height), 8)
        r = pygame.Rect(24, 250, self.width - 48, 196)
        inner = K.dialog(surf, r, "Achtung: Boss im Anflug!", icon="power", buttons=None)
        surf.blit(_warn_icon(), (inner.x + 6, inner.y + 8))
        K.t95(surf, cls.title(level), K.fit_size(cls.title(level), inner.w - 70, sizes=(24, 22, 20)), (inner.x + 58, inner.y + 14), color=K.F_LATE)
        for i, ln in enumerate(cls.WARN):
            K.t95(surf, ln, 16, (inner.x + 14, inner.y + 62 + i * 24))
        bar = pygame.Rect(inner.x + 14, inner.bottom - 26, inner.w - 28, 20)
        progress95(surf, bar, (self.play_t - self.phase_at) / WARN_SECONDS, BOSS_RED)

    def _draw_boss_bar(self, surf):
        """Health bar of the boss in a little Win95 window ("reagiert nicht mehr")."""
        b = self.boss
        if b is None or self.state != "play":
            return
        r = pygame.Rect(10, 92, self.width - 20, 60)
        inner = K.window(surf, r, b.EXE, icon="power", buttons=None)
        bar = pygame.Rect(inner.x, inner.y, inner.w, inner.h)
        blink = b.lost_from if b.t - b.lost_at < 0.4 and int(b.t * 16) % 2 == 0 else b.hp
        progress95(surf, bar, b.hp / b.max_hp, BOSS_RED, blink / b.max_hp)

    def _draw_hud_bar(self, surf):
        w = self.width
        score = str(self.score)
        r = outlined(surf, score, K.fit_size(score, SCORE_MAX_W, sizes=(34, 30, 26, 22, 18)), GOLD, (w // 2, 28), thick=2)
        if self.mult() > 1:  # streak multiplier next to the score
            outlined(surf, f"x{self.mult()}", 22, PINK, (r.right + 8, 30), anchor="midleft")
        outlined(surf, "Punkte", 15, WHITE, (w // 2, 56))
        for i in range(LIVES):  # hearts (one flying in is drawn by the flight, not yet here)
            flying = any(h[3] == i for h in self.heart_flies)
            K.heart(surf, (w - 100 + i * 32, 18), 3, PINK if i < self.lives and not flying else (90, 70, 110))
        for x0, y0, born, slot in self.heart_flies:  # heart flies from where it was won into its HUD slot
            k = min(1.0, (self.t - born) / 0.9)
            e = 1 - (1 - k) ** 2
            tx, ty = w - 100 + slot * 32, 18
            x, y = x0 + (tx - x0) * e, y0 + (ty - y0) * e - math.sin(k * math.pi) * 90
            K.heart(surf, (int(x), int(y)), 3 if k > 0.8 else 5, PINK)
        # Steuerflucht meter: uncut money that fell back down; full = -1 heart
        hot = self.t - self.flucht_at < 0.4
        outlined(surf, "Steuerflucht", 15, (255, 120, 140) if hot else WHITE, (w - 6, 30), anchor="topright")
        bar = pygame.Rect(w - 138, 50, 130, 18)
        progress95(surf, bar, self.flucht / FLUCHT_MAX, BOSS_RED, cells=FLUCHT_MAX)
        if hot:
            pygame.draw.rect(surf, (255, 90, 110), bar.inflate(4, 4), 2)
        rec = party_games._fit(K.font(12), party_games.record_line(type(self), short=True), 150)
        outlined(surf, rec, 12, WHITE, (w - 6, 70), anchor="topright")
        outlined(surf, _clock(self.play_t), 24, WHITE, (58, 24))
        if self.boss_phase in ("warn", "fight"):
            if int(self.t * 3) % 2 == 0:
                outlined(surf, "BOSSKAMPF!", 15, (255, 110, 130), (58, 50))
        elif self.boss_phase == "victory":
            outlined(surf, "ZERSCHLAGEN!", 15, GOLD, (64, 50))
        else:
            left = self.next_boss_at - self.play_t
            hot = left < 10 and int(self.t * 4) % 2 == 0
            outlined(surf, f"Boss in {_clock(math.ceil(left))}", 15, (255, 110, 130) if hot else WHITE, (64, 50))

    def _draw_start(self, surf):
        w = self.width
        K.wordart(surf, "ENTEIGNEN!", 54, (w // 2, 70), wave=8)
        K.t95(surf, "Schneid das Kapital klein -", 17, (w // 2, 124), color=WHITE, anchor="center")
        K.t95(surf, "der Kiez kriegt die Stücke.", 17, (w // 2, 148), color=WHITE, anchor="center")
        win = pygame.Rect(24, 176, w - 48, 470)
        inner = K.dialog(surf, win, "anleitung.txt", icon="note", buttons=None)
        K.groupbox(surf, pygame.Rect(inner.x + 4, inner.y + 16, inner.w - 8, 130), "Wischen durch:")
        x = inner.x + 14
        for k in ["coin", "bag", "miete", "jet"]:
            img = pygame.transform.rotozoom(_SPRITES[k], 0, 0.8 if k != "jet" else 0.7)
            surf.blit(img, img.get_rect(midleft=(x, inner.y + 76)))
            x += img.get_width() + 14
        K.t95(surf, "Geld, Rendite, Yachten, Mieterhöhungen", 15, (inner.x + 14, inner.y + 120), bold=False)
        K.groupbox(surf, pygame.Rect(inner.x + 4, inner.y + 166, inner.w - 8, 128), "NICHT schneiden:")
        x = inner.x + 20
        for k in ["cat", "bus", "spaeti", "pfand"]:
            img = pygame.transform.rotozoom(_SPRITES[k], 0, 0.7)
            pygame.draw.circle(surf, (60, 200, 120), (x + img.get_width() // 2, inner.y + 224), int(max(img.get_size()) / 2 + 4), 2)
            surf.blit(img, img.get_rect(midleft=(x, inner.y + 224)))
            x += img.get_width() + 24
        K.t95(surf, "Katze, Bus, Späti, Pfand: geschützt!", 15, (inner.x + 14, inner.y + 268), bold=False)
        y = inner.y + 304
        for text, color in [("Geld fallen lassen füllt Steuerflucht.", None),
                            ("Meter voll oder Katze & Co. = -1 Herz.", None),
                            ("Alle Herzen weg = Kündigung.", K.F_LATE),
                            ("Ab 0:45 kommen BOSSE. Zerschlagen!", K.F_ACCENT),
                            ("Serie ohne Fehler = Punkte x2..x5", K.F_ACCENT)]:
            K.t95(surf, text, 15, (inner.x + 14, y), color=color)
            y += 22
        if int(self.last_tick * 2) % 2 == 0:
            outlined(surf, self.READY_TEXT, 20, WHITE, (w // 2, 676), thick=2)
        outlined(surf, party_games.record_line(type(self)), 15, GOLD, (w // 2, 710))


BOSS_RED = (215, 25, 50)
SCORE_MAX_W = 150  # px for the HUD score: with "x5" next to it, it must stay clear of "Steuerflucht" (x >= 364)


def progress95(surf, rect, frac, color, ghost=None, cells=None):
    """Win95 progress bar (like kiezos.progress95, in a given colour). ghost:
    a higher fraction drawn in white (the cells a hit just took). cells: a
    fixed cell count instead of 12 px cells."""
    K.bevel(surf, rect, sunken=True, face=K.F_PAPER)
    inner_w = rect.w - 8
    if cells:
        cw = inner_w / cells
        n, g = round(frac * cells), round((ghost or 0) * cells)
        for i in range(max(n, g)):
            pygame.draw.rect(surf, color if i < n else WHITE if ghost else color, (rect.x + 4 + i * cw, rect.y + 3, cw - 2, rect.h - 6))
        return
    total = int(inner_w / 12)
    n, g = int(math.ceil(total * max(0.0, min(1.0, frac)))), int(math.ceil(total * min(1.0, ghost or 0)))
    for i in range(max(n, g)):
        pygame.draw.rect(surf, color if i < n else (255, 236, 240), (rect.x + 4 + i * 12, rect.y + 3, 9, rect.h - 6))
    if ghost is not None and g > n:
        pygame.draw.rect(surf, K.F_INK, (rect.x + 4 + n * 12 - 1, rect.y + 2, 1, rect.h - 4))


_WARN = []


def _warn_icon():
    if not _WARN:
        warn = _canvas(16, 16)
        pygame.draw.polygon(warn, GOLD, [(8, 1), (15, 14), (1, 14)])
        pygame.draw.polygon(warn, K.F_INK, [(8, 1), (15, 14), (1, 14)], 1)
        pygame.draw.rect(warn, K.F_INK, (7, 5, 2, 5))
        pygame.draw.rect(warn, K.F_INK, (7, 11, 2, 2))
        _WARN.append(pygame.transform.scale(warn, (40, 40)))
    return _WARN[0]


_RAYS = {}


def _rays(w, phase):
    """Victory sunburst, two pre-rendered phases (alternating = spinning)."""
    key = (w, phase)
    if key not in _RAYS:
        s = _canvas(w, w)
        c = w // 2
        n = 16
        for i in range(n):
            a0 = (i + phase * 0.5) * 2 * math.pi / n
            a1 = a0 + math.pi / n
            pygame.draw.polygon(s, (255, 220, 120, 70) if i % 2 else (255, 140, 210, 70),
                                [(c, c), (c + c * math.cos(a0), c + c * math.sin(a0)), (c + c * math.cos(a1), c + c * math.sin(a1))])
        _RAYS[key] = s
    return _RAYS[key]


_TINTS = {}


def _slowmo_tint(w, h):
    if (w, h) not in _TINTS:
        tint = _canvas(w, h)
        tint.fill((60, 0, 90, 70))
        for y in range(0, h, 4):
            pygame.draw.line(tint, (20, 0, 40, 60), (0, y), (w, y))
        _TINTS[(w, h)] = tint
    return _TINTS[(w, h)]


_WHITES = {}


def _white(w, h):
    if (w, h) not in _WHITES:
        s = pygame.Surface((w, h))
        s.fill(WHITE)
        _WHITES[(w, h)] = s
    return _WHITES[(w, h)]
