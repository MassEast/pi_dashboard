#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
PATRIAPUTT (patriaputt.exe): brick-breaker roguelite for the KiezOS 161
"Spiele" menu, a party_games._Game like STAPEL-TURM / ENTEIGNEN!.

One continuous round, no levels: a wall of patriarchal STRUCTURES and
BEHAVIOURS (Sexismus, Pay Gap, Mansplaining ... never groups of people)
creeps down towards the rainbow PLENUM paddle, faster and tougher over time.
Every brick shows its hit points. If any brick reaches the red danger line
above the paddle: DURCHBRUCH, one of 3 hearts is gone and the bottom rows are
wiped. Special bricks: armoured HERRENCLUB (every hit does 1 damage, no
matter what), STAMMTISCH (breaks into two HAHA minions), glass-ceiling rows
(one pane breaks -> the whole row shatters in a chain, "KLIRR!"), and every
~55 s the PATRIARCHAT itself: a full-width two-row block with lots of HP
(beaten -> +1 heart back).

Broken bricks drop "Solidarität" gems that fall to the paddle (catch them,
a magnet helps near the paddle). Enough Solidarität = level-up: the game
pauses and offers 3 big cards - new BALL TYPES (Glitzerball, Streikball,
Soliball, Demo-Zug, Plenumsball, Brandbrief, Quotenball), the paddle's
Konfetti-Kanone, extra Discobälle, Wut im Bauch (+1 damage) or rarely a
heart; each type levels up to Lv3, and two maxed combos evolve (FEUERWERK,
GENERALSTREIK). A dropped ball comes back on the paddle and launches by itself,
but the wall jumps forward a bit (DROP_PUSH). Bots in dev/test_patriaputt.py: a casual player
loses in about 1-3 minutes, a good one survives clearly longer.

Input: PiDashboard.py passes the finger down as tap(), movement as drag()
and lifting as release(). The paddle sits under the finger while it's down,
a plain tap left/right glides it there, a tap on a card picks it. Hit-stop
counts frames; bricks, boss, balls, gems, paddle, HUD and text are cached
surfaces and the bricks live in a grid, so collision stays cheap with many
balls on a Pi 4 at 20 FPS.

Look based on the approved mockup scratch/game_mockups/patriarchat/mock_patriarchat.py
(its drawing code is reused below).
"""

import math
import random

import pygame

import kiezos as K
import party_games

# ------------------------------------------------------------ tuning
HEARTS = 3
BALL_R, MINI_R = 9, 6
BALL_SPEED = 430.0  # px/s, + BALL_SPEED_RAMP per second played, up to + MAX_BALL_RAMP
BALL_SPEED_RAMP = 0.5
MAX_BALL_RAMP = 90.0
WALL_SPEED = 6.0  # px/s the wall creeps down at the start ...
WALL_SPEED_RAMP = 0.12  # ... + this per second played ...
MAX_WALL_SPEED = 34.0  # ... up to this
BOSS_WALL_FACTOR = 0.8  # the heavy PATRIARCHAT slows the wall a bit
PADDLE_W, PADDLE_H = 116, 22
PADDLE_MAX_SPEED = 2600.0  # px/s the paddle glides to a plain tap (a drag moves it directly)
MAX_BOUNCE_DEG = 62
MIN_DY = 0.28
SUBSTEP_PX = 6
RESPAWN_SECONDS = 1.0  # a dropped ball is gone this long ...
LAUNCH_DELAY = 0.6  # ... then sits on the paddle this long and launches by itself
MAX_BALLS = 16
MINI_SECONDS = 5.0
FIRST_BOSS_AT, BOSS_EVERY = 40.0, 55.0
BOSS_HP, BOSS_HP_PER_KILL = 80, 60
GLASS_FROM, GLASS_EVERY = 15.0, 8  # glass rows from 15 s on, every ~8th row
XP_FIRST, XP_GROWTH = 8, 1.5
GEM_SPEED, MAGNET_RANGE = 170.0, 110
MAGNET_SIDE = 40  # px beside the paddle the magnet reaches
DROP_PUSH = 10  # px the wall jumps forward when a ball is dropped
CARD_TAP_DELAY = 0.45  # a finger still dragging when the cards pop up doesn't pick one
CARD_AUTO_PICK = 15.0
MAX_PARTICLES = 260

# ------------------------------------------------------------ layout (game surface, 480 x 764)
HUD_H = 44
GAP = 6
FULL_W = 152  # 3 columns
HALF_W = (FULL_W - GAP) // 2  # 6 half slots
BRICK_H, ROW_STEP = 32, 38

# ------------------------------------------------------------ colours (from the mockup)
INK = K.INK
WHITE = (255, 255, 255)
PINK = K.PINK
HOT = (255, 70, 170)
GOLD, GOLD_D = (255, 208, 72), (200, 140, 30)
MINT, MINT_D = (130, 230, 170), (40, 140, 90)
LILAC = (190, 150, 255)
SKY = (120, 200, 255)
ORANGE = (255, 150, 70)
RED = (230, 50, 70)
GLASS, GLASS_L = (170, 225, 255), (235, 250, 255)
BROWN, BROWN_D = (150, 95, 55), (100, 60, 35)
NAVY = (40, 50, 110)
STEEL = (120, 120, 140)
ICE = (190, 235, 255)
RAINBOW = [(230, 40, 50), (255, 140, 0), (255, 225, 0), (0, 160, 70), (40, 90, 230), (130, 40, 170)]

# label -> (colour, icon or None, line shown when it breaks)
BRICKS = {
    "SEXISMUS": (PINK, None, "SEXISMUS ABGESCHAFFT!"),
    "RASSISMUS": (ORANGE, None, "RASSISMUS ZERLEGT!"),
    "KLASSISMUS": (GOLD, "coin", "KLASSISMUS GEKIPPT!"),
    "MANSPLAINING": (LILAC, None, "DANKE, WUSSTEN WIR SCHON!"),
    "HERRENWITZ": (MINT, "bubble", "HAHA. NEIN."),
    "ABLEISMUS": (SKY, "stairs", "RAMPE GEBAUT!"),
    "PAY GAP": (GOLD, "payslip", "LOHNLÜCKE GESCHLOSSEN!"),
    "CATCALLING": (PINK, None, "CATCALLING ABGEPFIFFEN!"),
    "MANSPREADING": (ORANGE, None, "BEINE ZUSAMMEN, BRO!"),
    "QUEERFEIND": (LILAC, None, "QUEERFEINDLICHKEIT? TSCHÜSS!"),
    "ALPHA-MIC": (SKY, "mic", "MIKRO AUS!"),
    "WAR IMMER SO": (ORANGE, None, "WAR. JETZT NICHT MEHR."),
    "GRILLZANGE": (GOLD, "tongs", "GRILLZANGE ABGEGEBEN!"),
    "CARE: 0 €": (PINK, None, "CARE-ARBEIT BEZAHLT!"),
    # special bricks
    "STAMMTISCH": (MINT, "beer", "STAMMTISCH AUFGELÖST!"),
    "HERRENCLUB": (STEEL, "hat", "HERRENCLUB GESCHLOSSEN!"),
    "HAHA": ((200, 245, 215), None, "HAHA. NEIN."),
}
NORMAL_LABELS = [k for k in BRICKS if k not in ("STAMMTISCH", "HERRENCLUB", "HAHA")]

# Upgrade cards. kind -> (name, colour, [description lines per level 1..3], max level)
CARDS = {
    "glitzer": ("Glitzerball", PINK, [["Platzt bei jedem Treffer in Glitzer:", "Steine daneben kriegen 1 Schaden."],
                                      ["Glitzer fliegt weiter:", "größerer Radius."],
                                      ["Extra-Glitzer:", "2 Schaden im Umkreis."]], 3),
    "streik": ("Streikball", GOLD, [["Treffer = STREIK: die Wand", "steht 1,5 s still (alle 8 s)."],
                                    ["Längerer Streik:", "2,5 s, alle 7 s."],
                                    ["Unbefristeter Streik:", "3,5 s, alle 6 s."]], 3),
    "soli": ("Soliball", MINT, [["Teilt sich bei jedem Plenum-", "Kontakt: +1 Mini-Ball für 5 s."],
                                ["Mehr Solidarität:", "+2 Mini-Bälle pro Kontakt."],
                                ["Massenbewegung:", "+3 Mini-Bälle pro Kontakt."]], 3),
    "demo": ("Demo-Zug", RED, [["Zieht durch 3 Steine durch,", "bevor er abprallt."],
                               ["Größere Demo:", "zieht durch 5 Steine."],
                               ["Großdemo:", "zieht durch 8 Steine."]], 3),
    "plenum": ("Plenumsball", LILAC, [["Springt nach einem Treffer", "direkt zum nächsten Stein (2x)."],
                                       ["Längeres Plenum:", "springt 4x weiter."],
                                       ["Open End:", "springt 6x weiter."]], 3),
    "brand": ("Brandbrief", ORANGE, [["Steckt Steine in Brand:", "1 Schaden pro Sekunde, 3 s lang."],
                                      ["Wütenderer Brief:", "brennt 5 s lang."],
                                      ["Flächenbrand:", "Feuer springt auf Nachbarsteine."]], 3),
    "quote": ("Quotenball", HOT, [["Doppelter Schaden gegen das", "PATRIARCHAT und Herrenclubs."],
                                  ["Mehr Quote:", "dreifacher Schaden dort."],
                                  ["Parität:", "vierfacher Schaden dort."]], 3),
    "konfetti": ("Konfetti-Kanone", SKY, [["Das Plenum schießt automatisch", "Konfetti nach oben (1/s)."],
                                           ["Schnellere Kanone:", "1,5 Schuss pro Sekunde."],
                                           ["Doppelrohr:", "2 Schüsse, 2 pro Sekunde."]], 3),
    "disco": ("Noch ein Discoball", (200, 200, 220), [["Ein Ball mehr im Spiel.", "Mehr Bälle, mehr Party."]] * 3, 3),
    "wut": ("Wut im Bauch", RED, [["Alle Bälle machen", "+1 Schaden."]] * 2, 2),
    "herz": ("Kiez-Solidarität", PINK, [["Die Nachbarschaft hilft:", "+1 Herz zurück."]], 99),
    "feuerwerk": ("FEUERWERK", GOLD, [["Evolution! Glitzerball Lv3 +", "Brandbrief: Glitzer zündet an."]], 1),
    "generalstreik": ("GENERALSTREIK", GOLD, [["Evolution! Streik Lv3 + Demo:", "Streik x2 lang, Steine nehmen x2."]], 1),
}
PICK_STAMPS = {"disco": "DISCOBALL", "konfetti": "KONFETTI", "herz": "SOLIDARITÄT"}  # long card names, shorter stamps
BALL_KINDS = ("glitzer", "streik", "soli", "demo", "plenum", "brand", "quote")  # cards that add a ball
TRAILS = {"disco": (255, 160, 220), "glitzer": (255, 120, 210), "streik": (255, 220, 120), "soli": (160, 255, 200),
          "demo": (255, 120, 120), "plenum": (200, 170, 255), "brand": (255, 170, 80), "quote": (255, 110, 200),
          "mini": (220, 255, 235)}

BOSS_QUIPS = [
    "Das wird man doch noch sagen dürfen!",
    "Früher war alles besser!",
    "Not all men!",
    "Lächel doch mal!",
    "Das war schon immer so!",
    "Jetzt mal nicht hysterisch!",
]
BREACH_LINES = ["Das Patriarchat rückt vor!", "Die Decke drückt!", "Zu spät, Genoss*in!"]
OVER_LINES = ["DURCHBRUCH!", "Plenum überrannt!", "Vertagt!"]


# ------------------------------------------------------------ basics (from the mockup)

def canvas(w, h):
    return pygame.Surface((w, h), pygame.SRCALPHA)


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def fmt(n):
    return f"{n:,}".replace(",", ".")


_TEXT = {}


def otext(text, size, color, thick=2):
    """Cached outlined KiezOS text (ink outline), reads on any background."""
    key = (text, size, color, thick)
    s = _TEXT.get(key)
    if s is None:
        if len(_TEXT) > 400:
            _TEXT.clear()
        f = K.font(size)
        img = f.render(text, False, color)
        ol = f.render(text, False, K.F_INK)
        s = canvas(img.get_width() + 2 * thick, img.get_height() + 2 * thick)
        for dx in range(-thick, thick + 1):
            for dy in range(-thick, thick + 1):
                if dx or dy:
                    s.blit(ol, (thick + dx, thick + dy))
        s.blit(img, (thick, thick))
        _TEXT[key] = s
    return s


def outlined(surf, text, size, color, center, thick=2, anchor="center"):
    s = otext(text, size, color, thick)
    r = s.get_rect(**{anchor: (int(center[0]), int(center[1]))})
    surf.blit(s, r)
    return r


def star(s, c, r, fill, rot=0.0):
    pts = []
    for i in range(8):
        a = math.radians(rot + i * 45)
        rr = r if i % 2 == 0 else r * 0.35
        pts.append((c[0] + math.cos(a) * rr, c[1] + math.sin(a) * rr))
    pygame.draw.polygon(s, fill, pts)


_STAMPS = {}


def stamp_image(text, angle, size=28, red=(20, 140, 80)):
    """Rubber stamp with a light rim (from the mockup), cached."""
    key = (text, angle, size, red)
    if key not in _STAMPS:
        rim = (255, 236, 240)
        f = K.font(size)
        im, rm = f.render(text, False, red), f.render(text, False, rim)
        w, h = im.get_width() + 28, im.get_height() + 18
        st = canvas(w, h)
        pygame.draw.rect(st, rim, (0, 0, w, h), 8, border_radius=6)
        pygame.draw.rect(st, red, (2, 2, w - 4, h - 4), 4, border_radius=5)
        x = (w - im.get_width()) // 2
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            st.blit(rm, (x + dx, 9 + dy))
        st.blit(im, (x, 9))
        st.blit(im, (x + 1, 9))
        rnd = random.Random(text)
        for _ in range(w * h // 60):
            p = (rnd.randrange(w), rnd.randrange(h))
            if st.get_at(p)[:3] == red:
                st.set_at(p, rim)
        _STAMPS[key] = pygame.transform.rotate(st, angle)
    return _STAMPS[key]


# ------------------------------------------------------------ pixel icons (16x16, from the mockup)

def _ico(kind):
    s = canvas(16, 16)
    if kind == "tie":
        pygame.draw.polygon(s, NAVY, [(6, 1), (10, 1), (9, 4), (7, 4)])
        pygame.draw.polygon(s, NAVY, [(7, 4), (9, 4), (11, 12), (8, 15), (5, 12)])
        pygame.draw.polygon(s, INK, [(6, 1), (10, 1), (9, 4), (11, 12), (8, 15), (5, 12), (7, 4)], 1)
        for y in (6, 9, 12):
            pygame.draw.line(s, GOLD, (6, y + 1), (9, y - 1))
    elif kind == "hat":
        pygame.draw.rect(s, (30, 25, 40), (4, 2, 8, 9))
        pygame.draw.rect(s, RED, (4, 8, 8, 2))
        pygame.draw.rect(s, (30, 25, 40), (1, 11, 14, 3))
        pygame.draw.rect(s, (110, 100, 130), (5, 3, 1, 4))
    elif kind == "mic":
        pygame.draw.rect(s, (90, 90, 100), (5, 1, 6, 8), border_radius=3)
        for y in (3, 5, 7):
            pygame.draw.line(s, (170, 170, 185), (6, y), (9, y))
        pygame.draw.arc(s, INK, (3, 4, 10, 9), math.pi, 2 * math.pi, 1)
        pygame.draw.line(s, INK, (8, 12), (8, 14))
        pygame.draw.line(s, INK, (5, 14), (11, 14))
        pygame.draw.rect(s, INK, (5, 1, 6, 8), 1, border_radius=3)
    elif kind == "beer":
        pygame.draw.rect(s, GOLD, (3, 4, 8, 10))
        pygame.draw.rect(s, WHITE, (3, 2, 8, 3))
        pygame.draw.rect(s, INK, (3, 2, 8, 12), 1)
        pygame.draw.rect(s, INK, (11, 6, 3, 6), 1)
        pygame.draw.line(s, GOLD_D, (5, 6), (5, 12))
        pygame.draw.line(s, GOLD_D, (8, 6), (8, 12))
    elif kind == "tongs":
        pygame.draw.line(s, (180, 180, 195), (2, 14), (12, 2), 2)
        pygame.draw.line(s, (180, 180, 195), (2, 14), (14, 5), 2)
        pygame.draw.line(s, BROWN, (2, 14), (5, 11), 3)
        pygame.draw.rect(s, (200, 60, 40), (11, 1, 4, 3))
    elif kind == "stairs":
        pts = [(1, 15), (1, 12), (5, 12), (5, 8), (9, 8), (9, 4), (13, 4), (13, 1), (15, 1), (15, 15)]
        pygame.draw.polygon(s, (180, 170, 190), pts)
        pygame.draw.polygon(s, INK, pts, 1)
        pygame.draw.line(s, RED, (1, 3), (8, 10), 2)
        pygame.draw.line(s, RED, (8, 3), (1, 10), 2)
    elif kind == "payslip":
        pygame.draw.rect(s, WHITE, (2, 1, 12, 14))
        pygame.draw.rect(s, INK, (2, 1, 12, 14), 1)
        for y in (4, 6):
            pygame.draw.line(s, (150, 150, 170), (4, y), (11, y))
        pygame.draw.rect(s, RED, (4, 9, 8, 4))
        pygame.draw.line(s, WHITE, (5, 11), (6, 11))
        pygame.draw.line(s, WHITE, (8, 10), (10, 12))
        pygame.draw.line(s, WHITE, (10, 10), (8, 12))
    elif kind == "bubble":
        pygame.draw.rect(s, WHITE, (1, 2, 14, 9), border_radius=3)
        pygame.draw.polygon(s, WHITE, [(4, 10), (4, 14), (8, 10)])
        pygame.draw.rect(s, INK, (1, 2, 14, 9), 1, border_radius=3)
        for x in (4, 7, 10):
            pygame.draw.rect(s, INK, (x, 6, 2, 2))
    elif kind == "coin":
        pygame.draw.circle(s, GOLD, (8, 8), 7)
        pygame.draw.circle(s, INK, (8, 8), 7, 1)
        pygame.draw.circle(s, GOLD_D, (8, 8), 5, 1)
        pygame.draw.line(s, GOLD_D, (8, 4), (8, 12), 2)
    elif kind == "fist":
        pygame.draw.rect(s, PINK, (6, 11, 5, 4))
        pygame.draw.rect(s, PINK, (3, 3, 10, 9), border_radius=2)
        pygame.draw.rect(s, INK, (3, 3, 10, 9), 1, border_radius=2)
        for x in (5, 8, 10):
            pygame.draw.line(s, INK, (x, 3), (x, 6))
        pygame.draw.line(s, INK, (3, 7), (9, 7))
        pygame.draw.line(s, INK, (6, 11), (6, 15))
        pygame.draw.line(s, INK, (10, 11), (10, 15))
    elif kind == "picket":
        pygame.draw.line(s, BROWN, (8, 9), (8, 15), 2)
        pygame.draw.rect(s, WHITE, (1, 1, 14, 9))
        pygame.draw.rect(s, INK, (1, 1, 14, 9), 1)
        pygame.draw.line(s, RED, (3, 4), (12, 4), 2)
        pygame.draw.line(s, RED, (3, 7), (9, 7), 1)
    elif kind == "banner":
        pygame.draw.line(s, BROWN, (2, 2), (2, 15), 2)
        pygame.draw.line(s, BROWN, (13, 2), (13, 15), 2)
        pygame.draw.rect(s, PINK, (2, 3, 12, 7))
        pygame.draw.rect(s, INK, (2, 3, 12, 7), 1)
        pygame.draw.line(s, WHITE, (4, 6), (11, 6), 2)
    elif kind == "venus":
        pygame.draw.circle(s, HOT, (8, 6), 5, 2)
        pygame.draw.line(s, HOT, (8, 10), (8, 15), 2)
        pygame.draw.line(s, HOT, (5, 13), (11, 13), 2)
    elif kind == "glitter":  # Glitzerbombe: round bomb, fuse, sparkles
        pygame.draw.circle(s, INK, (7, 10), 6)
        pygame.draw.circle(s, (150, 60, 200), (7, 10), 5)
        s.set_at((5, 8), WHITE); s.set_at((6, 8), WHITE); s.set_at((5, 9), WHITE)
        s.set_at((8, 12), HOT); s.set_at((4, 11), GOLD); s.set_at((9, 9), SKY)
        pygame.draw.line(s, BROWN, (10, 5), (12, 2))
        for p, c in (((13, 1), GOLD), ((14, 3), HOT), ((12, 0), WHITE), ((15, 1), SKY)):
            s.set_at(p, c)
    return s


_ICONS = {}


def icon(kind, size):
    key = (kind, size)
    if key not in _ICONS:
        _ICONS[key] = pygame.transform.scale(_ico(kind), (size, size))
    return _ICONS[key]


def menu_icon_surface(size=32):
    """16px menu/title icon: three bricks (one cracked), a disco ball and the
    rainbow PLENUM paddle, scaled nearest-neighbour. Pure drawing, no fonts,
    so kiezos.menu_icon can call it any time."""
    s = canvas(16, 16)
    for (x, y), c in (((1, 1), PINK), ((8, 1), LILAC), ((1, 5), GOLD)):
        pygame.draw.rect(s, INK, (x, y, 7, 4))
        pygame.draw.rect(s, c, (x + 1, y + 1, 5, 2))
    pygame.draw.line(s, INK, (9, 3), (11, 2))  # crack in the lilac brick
    pygame.draw.line(s, INK, (11, 2), (12, 4))
    for p in ((8, 7), (9, 9)):  # flying shards
        s.set_at(p, LILAC)
    pygame.draw.rect(s, INK, (10, 6, 5, 5))  # disco ball
    pygame.draw.rect(s, (170, 170, 200), (11, 7, 3, 3))
    s.set_at((11, 7), WHITE); s.set_at((13, 9), WHITE); s.set_at((12, 8), PINK)
    for p in ((10, 6), (14, 6), (10, 10), (14, 10)):  # round-ish corners
        s.set_at(p, (0, 0, 0, 0))
    for i, c in enumerate([(230, 40, 50), (255, 225, 0), (40, 90, 230)]):  # rainbow paddle
        pygame.draw.line(s, c, (3, 12 + i), (12, 12 + i))
    pygame.draw.rect(s, INK, (2, 11, 12, 5), 1)
    return pygame.transform.scale(s, (size, size))


# ------------------------------------------------------------ pre-rendered sprites

_SPR = {}


def _cached(key, make):
    if key not in _SPR:
        _SPR[key] = make()
    return _SPR[key]


def cracks(s, r, n, seed):
    rnd = random.Random(seed)
    for i in range(n):
        x = r.x + 2 if i % 2 == 0 else r.right - 3
        y = rnd.randrange(r.y + 4, r.bottom - 4)
        d = 1 if i % 2 == 0 else -1
        for _ in range(3):
            nx, ny = x + d * rnd.randint(4, 12), y + rnd.randint(-8, 8)
            nx = max(r.x + 2, min(r.right - 3, nx))
            ny = max(r.y + 2, min(r.bottom - 3, ny))
            pygame.draw.line(s, INK, (x, y), (nx, ny), 2)
            x, y = nx, ny


def _draw_brick(s, r, label, color, ico=None, pips=0, crack=0, size=15):
    pygame.draw.rect(s, INK, r.inflate(2, 2))
    pygame.draw.rect(s, color, r)
    pygame.draw.line(s, shade(color, 1.25), (r.x, r.y), (r.right - 1, r.y), 3)
    pygame.draw.line(s, shade(color, 1.25), (r.x, r.y), (r.x, r.bottom - 1), 3)
    pygame.draw.line(s, shade(color, 0.6), (r.x, r.bottom - 2), (r.right - 1, r.bottom - 2), 3)
    pygame.draw.line(s, shade(color, 0.6), (r.right - 2, r.y), (r.right - 2, r.bottom - 1), 3)
    if label:
        tw = K.font(size).size(label)[0]
        if ico and tw + 30 <= r.w - 8:
            x0 = r.centerx - (tw + 26) // 2
            s.blit(icon(ico, 22), (x0, r.centery - 11))
            K.t95(s, label, size, (x0 + 26, r.centery), anchor="midleft")
        else:
            K.t95(s, label, size, r.center, anchor="center")
    for i in range(pips):  # extra hits left
        pygame.draw.rect(s, INK, (r.right - 10 - i * 8, r.y + 5, 5, 5))
    if crack:
        cracks(s, r, crack, label + str(crack))


def paddle_surface(w, label):
    def make():
        s = canvas(w + 4, PADDLE_H + 4)
        r = pygame.Rect(2, 2, w, PADDLE_H)
        pygame.draw.rect(s, INK, r.inflate(4, 4), border_radius=6)
        stripe = r.h / 6
        for i, c in enumerate(RAINBOW):
            pygame.draw.rect(s, c, (r.x, r.y + int(i * stripe), r.w, int(stripe) + 1))
        pygame.draw.rect(s, WHITE, (r.x + 2, r.y + 1, r.w - 4, 2))
        outlined(s, label, 15, WHITE, r.center, thick=1)
        return s
    return _cached(("paddle", w, label), make)


def disco_frames(r=BALL_R):
    """4 frames of a spinning disco ball (facets twinkle, highlight moves)."""
    def make():
        frames = []
        for f in range(4):
            s = canvas(2 * r + 6, 2 * r + 6)
            c = (r + 3, r + 3)
            pygame.draw.circle(s, INK, c, r + 1)
            pygame.draw.circle(s, (200, 200, 220), c, r)
            rnd = random.Random(f)
            for dx in range(-r, r, 4):
                for dy in range(-r, r, 4):
                    if dx * dx + dy * dy < r * r:
                        k = (dx + dy + f * 4) % 8 == 0
                        col = WHITE if k else (150, 150, 190)
                        if rnd.random() < 0.12:
                            col = rnd.choice([PINK, SKY, GOLD])
                        s.fill(col, (c[0] + dx, c[1] + dy, 3, 3))
            star(s, (c[0] - r // 2 + (f % 2), c[1] - r // 2), 5, WHITE, f * 12)
            frames.append(s)
        return frames
    return _cached(("disco", r), make)


def capsule_surface(label, color, ico):
    def make():
        tw = K.font(15).size(label)[0]
        w, h = tw + 42, 30
        s = canvas(w + 4, h + 4)
        r = pygame.Rect(2, 2, w, h)
        pygame.draw.rect(s, INK, r.inflate(4, 4), border_radius=15)
        pygame.draw.rect(s, color, r, border_radius=15)
        pygame.draw.rect(s, shade(color, 1.3), (r.x + 8, r.y + 3, r.w - 16, 4), border_radius=2)
        s.blit(icon(ico, 22), (r.x + 6, r.centery - 11))
        K.t95(s, label, 15, (r.x + 32, r.centery + 1), anchor="midleft")
        return s
    if len(_SPR) > 600:
        _SPR.clear()
    return _cached(("capsule", label, color, ico), make)


def backdrop(w, h, seed=4):
    """Night sky in KiezOS purple + a faint Plattenbau skyline (mockup)."""
    def make():
        s = pygame.Surface((w, h))
        for y in range(h):
            t = y / h
            s.fill((int(34 + 40 * t), int(16 + 22 * t), int(64 + 60 * t)), (0, y, w, 1))
        rnd = random.Random(seed)
        for _ in range(60):
            s.fill((190, 170, 235), (rnd.randrange(w), rnd.randrange(h), 2, 2))
        for x, bw, bh in [(0, 80, 150), (70, 60, 210), (130, 100, 120), (230, 80, 180), (300, 70, 110), (360, 120, 200)]:
            r = pygame.Rect(x, h - bh, bw, bh)
            pygame.draw.rect(s, (54, 32, 92), r)
            for wy in range(r.y + 10, r.bottom - 6, 14):
                for wx in range(r.x + 8, r.right - 8, 12):
                    s.fill((120, 90, 60) if rnd.random() < 0.3 else (46, 28, 80), (wx, wy, 5, 6))
        return s
    return _cached(("backdrop", w, h, seed), make)


def glow_surface(radius=150):
    """Soft white radial glow for the glass shatter / boss hits."""
    def make():
        g = canvas(2 * radius, 2 * radius)
        for k, a in ((1.0, 18), (0.73, 22), (0.47, 30), (0.24, 50)):
            pygame.draw.circle(g, (230, 245, 255, a), (radius, radius), int(radius * k))
        return g
    return _cached(("glow", radius), make)


def solid_surface(w, h, color):
    return _cached(("solid", w, h, color), lambda: _filled(w, h, color))


def _filled(w, h, color):
    s = pygame.Surface((w, h))
    s.fill(color)
    return s


# ------------------------------------------------------------ game sprites

def _clear_if_big():
    if len(_SPR) > 900:
        _SPR.clear()


LABEL_SIZES = (15, 14, 13, 12)


def brick_surface(kind, label, w, h, hp, max_hp):
    """A brick (+1 px ink border) with its HP number; cracks as it loses HP."""
    def make():
        color, ico, _ = BRICKS[label]
        s = pygame.Surface((w + 2, h + 2))
        r = pygame.Rect(1, 1, w, h)
        _draw_brick(s, r, "", color)
        if kind == "armor":  # steel plate: dark rim + rivets
            pygame.draw.rect(s, (70, 70, 90), r, 3)
            for x in (r.x + 5, r.right - 6):
                for y in (r.y + 5, r.bottom - 6):
                    pygame.draw.rect(s, (220, 220, 235), (x - 1, y - 1, 3, 3))
        num = str(hp)
        box = pygame.Rect(0, 0, max(22, K.font(16).size(num)[0] + 8), h - 10)
        box.midright = (r.right - 5, r.centery)
        pygame.draw.rect(s, INK, box)
        K.t95(s, num, 16, box.center, color=WHITE if kind != "armor" else GOLD, anchor="center")
        room = box.left - r.x - 6
        tw = K.font(15).size(label)[0]
        size = K.fit_size(label, room, sizes=LABEL_SIZES)  # long label + 3-digit HP: smaller, never gone
        if ico and tw + 26 <= room:
            x0 = r.x + 3 + (room - tw - 26) // 2
            s.blit(icon(ico, 22), (x0, r.centery - 11))
            K.t95(s, label, 15, (x0 + 26, r.centery), anchor="midleft", color=WHITE if kind == "armor" else None)
        elif K.font(size).size(label)[0] <= room:
            K.t95(s, label, size, (r.x + 3 + room // 2, r.centery), anchor="center", color=WHITE if kind == "armor" else None)
        elif ico:
            s.blit(icon(ico, 22), (r.x + 3 + room // 2 - 11, r.centery - 11))
        crack = int(3 * (1 - hp / max_hp)) if max_hp > 1 else 0
        if crack:
            cracks(s, pygame.Rect(r.x, r.y, box.left - r.x, r.h), crack, label + str(crack))
        return s
    _clear_if_big()
    return _cached(("brick", kind, label, w, h, hp, max_hp), make)


def glass_surface(w, h, hp):
    def make():
        g = canvas(w, h)
        g.fill((*GLASS, 150))
        pygame.draw.line(g, (*GLASS_L, 230), (6, h - 6), (22, 6), 3)
        pygame.draw.line(g, (*GLASS_L, 200), (16, h - 6), (28, 10), 1)
        pygame.draw.rect(g, (220, 245, 255), (0, 0, w, h), 2)
        if hp > 1:
            K.t95(g, str(hp), 16, (w - 14, h // 2), color=NAVY, anchor="center")
        return g
    return _cached(("glass", w, h, hp), make)


def boss_surface(w, h, name):
    def make():
        s = pygame.Surface((w + 2, h + 2))
        r = pygame.Rect(1, 1, w, h)
        _draw_brick(s, r, "", (120, 110, 140))
        for x in range(r.x + 10, r.right - 10, 26):  # pillars
            pygame.draw.line(s, (95, 85, 115), (x, r.y + 6), (x, r.bottom - 8), 2)
        outlined(s, name, 28 if len(name) < 13 else 24, WHITE, (r.centerx, r.y + 17))  # leaves room for the HP line
        s.blit(icon("hat", 36), (r.x + 12, r.y + 8))
        s.blit(icon("tie", 36), (r.right - 48, r.y + 8))
        return s
    return _cached(("boss", w, h, name), make)


def ball_frames(kind, r):
    """2 frames per ball type: a coloured, outlined pixel ball with its pattern."""
    def make():
        frames = []
        for f in range(2):
            d = 2 * r + 6
            s = canvas(d, d)
            c = (r + 3, r + 3)
            body = {"glitzer": PINK, "streik": GOLD, "soli": MINT, "demo": RED, "plenum": WHITE, "brand": ORANGE,
                    "quote": LILAC, "mini": (230, 255, 240), "konfetti": SKY}[kind]
            pygame.draw.circle(s, INK, c, r + 1)
            pygame.draw.circle(s, body, c, r)
            if kind == "plenum":
                for i, col in enumerate(RAINBOW):
                    y = c[1] - r + int(i * 2 * r / 6)
                    pygame.draw.rect(s, col, (c[0] - r, y, 2 * r, int(2 * r / 6) + 1))
                mask = canvas(d, d)
                pygame.draw.circle(mask, (255, 255, 255, 255), c, r)
                s.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
                pygame.draw.circle(s, INK, c, r + 1, 2)
            elif kind == "glitzer":
                for i in range(5):
                    a = i * 1.26 + f * 0.6
                    s.fill(WHITE if i % 2 else GOLD, (c[0] + int(math.cos(a) * r * 0.55) - 1, c[1] + int(math.sin(a) * r * 0.55) - 1, 3, 3))
            elif kind == "streik":
                for k in range(-r, r, 6):
                    pygame.draw.line(s, INK, (c[0] + k + f * 3, c[1] + r), (c[0] + k + r + f * 3, c[1] - r), 2)
                pygame.draw.circle(s, INK, c, r + 1, 2)
            elif kind == "soli":
                pygame.draw.line(s, WHITE, (c[0] - 4, c[1]), (c[0] + 4, c[1]), 3)
                pygame.draw.line(s, WHITE, (c[0], c[1] - 4), (c[0], c[1] + 4), 3)
            elif kind == "demo":
                pygame.draw.rect(s, WHITE, (c[0] - r, c[1] - 2, 2 * r, 4))
                pygame.draw.circle(s, INK, c, r + 1, 2)
            elif kind == "brand":
                pts = [(c[0], c[1] - r + 2 + f), (c[0] + 5, c[1] + 2), (c[0], c[1] + 6), (c[0] - 5, c[1] + 2)]
                pygame.draw.polygon(s, GOLD, pts)
            elif kind == "quote":
                pygame.draw.circle(s, HOT, (c[0], c[1] - 2), 4, 2)
                pygame.draw.line(s, HOT, (c[0], c[1] + 2), (c[0], c[1] + 7), 2)
            elif kind == "konfetti":
                for i, col in enumerate([PINK, GOLD, MINT, WHITE]):
                    s.fill(col, (c[0] - 5 + (i % 2) * 6, c[1] - 5 + (i // 2) * 6, 4, 4))
            if r >= 8:
                s.fill(WHITE, (c[0] - r // 2, c[1] - r // 2, 3, 3))
            frames.append(s)
        return frames
    if kind == "disco":
        return disco_frames(r)
    return _cached(("ball", kind, r), make)


def gem_surface(size):
    """Solidarität gem: a pink-mint diamond with a light rim, 3 sizes."""
    def make():
        s = canvas(size + 4, size + 4)
        c = (size // 2 + 2, size // 2 + 2)
        pts = [(c[0], 2), (size + 2, c[1]), (c[0], size + 2), (2, c[1])]
        pygame.draw.polygon(s, INK, [(x + (1 if x > c[0] else -1 if x < c[0] else 0), y + (1 if y > c[1] else -1 if y < c[1] else 0)) for x, y in pts])
        pygame.draw.polygon(s, MINT, pts)
        pygame.draw.polygon(s, (210, 255, 230), [(c[0], 4), (size, c[1]), (c[0], c[1])])
        pygame.draw.polygon(s, MINT_D, [(c[0], size), (2 + 2, c[1]), (c[0], c[1])])
        s.fill(WHITE, (c[0] - 1, 5, 2, 2))
        return s
    return _cached(("gem", size), make)


def fog_surface(w, h, alpha=170):
    def make():
        f = canvas(w, h)
        f.fill((20, 0, 40, alpha))
        return f
    return _cached(("fog", w, h, alpha), make)


def danger_glow(w):
    def make():
        g = canvas(w, 40)
        for y in range(40):
            pygame.draw.line(g, (255, 40, 70, int(110 * (1 - y / 40))), (0, 39 - y), (w, 39 - y))
        return g
    return _cached(("danger", w), make)


# ------------------------------------------------------------ objects

class Ball:
    __slots__ = ("kind", "x", "y", "dx", "dy", "r", "mini", "life", "stuck", "hidden_until", "launch_at",
                 "pierce", "home", "ignore", "trail", "offset")

    def __init__(self, kind, x, y, mini=False):
        self.kind, self.x, self.y = kind, x, y
        self.dx, self.dy = 0.0, -1.0
        self.r = MINI_R if mini else BALL_R
        self.mini = mini
        self.life = MINI_SECONDS
        self.stuck = False
        self.hidden_until = 0.0
        self.launch_at = 0.0
        self.pierce = 0
        self.home = 0
        self.ignore = None
        self.trail = []
        self.offset = random.uniform(-14, 14)

    def set_dir(self, dx, dy):
        n = math.hypot(dx, dy) or 1.0
        dx, dy = dx / n, dy / n
        if abs(dy) < MIN_DY:
            dy = MIN_DY if dy >= 0 else -MIN_DY
            dx = math.copysign(math.sqrt(1 - dy * dy), dx if dx else 1.0)
        self.dx, self.dy = dx, dy


class Brick:
    __slots__ = ("kind", "label", "r", "slot", "span", "rows", "hp", "max_hp", "fire_until", "fire_tick",
                 "flash_until", "wobble_until", "alive")

    def __init__(self, kind, label, r, slot, span, hp, rows=1):
        self.kind, self.label = kind, label
        self.r, self.slot, self.span, self.rows = r, slot, span, rows
        self.hp = self.max_hp = hp
        self.fire_until = -1.0
        self.fire_tick = 0.0
        self.flash_until = -1.0
        self.wobble_until = -1.0
        self.alive = True


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "color", "size", "life", "age", "kind", "g", "rot", "spin", "pts")

    def __init__(self, x, y, vx, vy, color, size, life, kind="frag", g=900.0):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.color, self.size, self.life, self.age, self.kind, self.g = color, size, life, 0.0, kind, g
        self.rot = random.uniform(0, 6.28)
        self.spin = random.uniform(-12, 12)
        self.pts = None
        if kind == "shard":
            self.pts = [(random.uniform(0.5, 1.0) * size, i * 2.094 + random.uniform(-0.5, 0.5)) for i in range(3)]

    def step(self, dt):
        self.age += dt
        self.vy += self.g * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.rot += self.spin * dt

    def draw(self, surf, ox, oy):
        x, y = self.x + ox, self.y + oy
        if self.kind == "frag":
            s = self.size
            r = (int(x) - s // 2, int(y) - s // 3, s, max(3, s * 2 // 3))
            pygame.draw.rect(surf, self.color, r)
            pygame.draw.rect(surf, INK, r, 1)
        elif self.kind == "shard":
            pts = [(x + math.cos(a + self.rot) * d, y + math.sin(a + self.rot) * d) for d, a in self.pts]
            pygame.draw.polygon(surf, GLASS, pts)
            pygame.draw.polygon(surf, GLASS_L, pts, 2)
        elif self.kind == "glitter":
            if (self.age * 12 + self.size) % 2 < 1.4:
                if self.size >= 6:
                    star(surf, (x, y), self.size, self.color, math.degrees(self.rot))
                else:
                    surf.fill(self.color, (int(x), int(y), self.size, max(2, self.size // 2 + 1)))
        else:  # spark
            v = math.hypot(self.vx, self.vy) or 1.0
            k = 0.04 * v
            pygame.draw.line(surf, self.color, (x, y), (x - self.vx / v * k, y - self.vy / v * k), 2)


class Popup:
    __slots__ = ("text", "x", "y", "color", "size", "life", "rise", "age")

    def __init__(self, text, x, y, color, size, life=0.9, rise=50.0):
        self.text, self.x, self.y, self.color, self.size = text, x, y, color, size
        self.life, self.rise = life, rise
        self.age = 0.0

    def step(self, dt):
        self.age += dt
        self.y -= self.rise * dt


class Gem:
    __slots__ = ("x", "y", "vx", "vy", "value", "age")

    def __init__(self, x, y, value):
        self.x, self.y, self.value = x, y, value
        self.vx, self.vy = random.uniform(-60, 60), random.uniform(-160, -60)
        self.age = 0.0


# ------------------------------------------------------------ the game

class PatriaputtGame(party_games._Game):
    NAME = "PATRIAPUTT"
    ICON = "patriaputt"
    DESCRIPTION = "Smash the Patriarchy"
    READY_TEXT = "Tippen zum Starten"
    SCORE_LABEL = "Punkte"
    SCORE_UNIT = ""

    @staticmethod
    def format_score(score):
        return fmt(score)

    # ---- setup --------------------------------------------------------
    def reset(self, now):
        super().reset(now)
        self.paddle_y = self.height - 74
        self.danger_y = self.paddle_y - 56
        self.t = 0.0  # game clock (runs during hit-stop and card picks, for effects)
        self.play_t = 0.0  # survival clock: drives the difficulty
        self.freeze = 0
        self.shake = 0.0
        self.flash = 0.0
        self.red_until = -1.0
        self.hearts = HEARTS
        self.balls = []
        self.bricks = []
        self.grid = {}
        self.wall_y = float(HUD_H + 6)  # screen y of grid row 0
        self.top_row = 0
        self.rows_spawned = 0
        self.next_glass_row = GLASS_EVERY
        self.boss = None
        self.next_boss_at = FIRST_BOSS_AT
        self.boss_kills = 0
        self.boss_damage_total = 0
        self.quip = None
        self.quip_ready = 0.0
        self.paddle_x = self.width / 2
        self.paddle_target = self.width / 2
        self.paddle_w = float(PADDLE_W)
        self.paddle_bump_until = -1.0
        self.lv = {}  # upgrade kind -> level
        self.wut = 0
        self.streik_until = -1.0
        self.streik_ready = 0.0
        self.konfetti_next = 0.0
        self.shots = []  # [x, y]
        self.gems = []
        self.xp = 0
        self.xp_next = XP_FIRST
        self.player_lv = 1
        self.pending_levelups = 0
        self.cards = None  # [(kind, rect)] while the level-up choice is open
        self.cards_at = 0.0
        self._cards_surf = None
        self.chain = []  # (time, brick) glass panes about to shatter
        self._in_chain = False
        self.parts = []
        self.popups = []
        self.stamp = None  # (text, angle, red, born)
        self.banner = None  # (wordart, sub, sub2, born)
        self.headline = None
        self.headline_ready = 0.0
        self.hitstop_ready = 0.0
        self.tap_pos = (self.width / 2, self.paddle_y)
        self.counts = {}
        self.picked = []
        self.breaches = 0
        self.over_at_t = 0.0
        self._hud_key = None
        self._hud = None
        self._start_surf = None

    def start(self):
        self.paddle_x = self.paddle_target = float(self.tap_pos[0])
        self._clamp_target()
        self.paddle_x = self.paddle_target
        for r in range(5):
            self._spawn_row(r)
        self.top_row = 0
        b = Ball("disco", self.paddle_x, self.paddle_y - BALL_R)
        self._park(b, hidden=0.0)
        self.balls = [b]

    # ---- grid ---------------------------------------------------------
    def slot_x(self, slot):
        return GAP + (slot // 2) * (FULL_W + GAP) + (slot % 2) * (HALF_W + GAP)

    def brick_rect(self, b):
        x = self.slot_x(b.slot)
        w = {1: HALF_W, 2: FULL_W}.get(b.span, self.width - 2 * GAP)
        h = BRICK_H + ROW_STEP * (b.rows - 1)
        return pygame.Rect(x, int(self.wall_y + b.r * ROW_STEP), w, h)

    def _add(self, b):
        self.bricks.append(b)
        for r in range(b.r, b.r + b.rows):
            for s in range(b.slot, b.slot + b.span):
                self.grid[(r, s)] = b
        return b

    def _remove(self, b):
        b.alive = False
        if b in self.bricks:
            self.bricks.remove(b)
        for r in range(b.r, b.r + b.rows):
            for s in range(b.slot, b.slot + b.span):
                if self.grid.get((r, s)) is b:
                    del self.grid[(r, s)]
        if b is self.boss:
            self.boss = None

    def _cell(self, x, y):
        r = math.floor((y - self.wall_y) / ROW_STEP)
        col = max(0, min(2, int((x - GAP) // (FULL_W + GAP))))
        half = 0 if x - (GAP + col * (FULL_W + GAP)) < FULL_W / 2 else 1
        return r, 2 * col + half

    def _near(self, x, y):
        r0, s0 = self._cell(x, y)
        out = []
        for r in (r0 - 1, r0, r0 + 1):
            for s in (s0 - 1, s0, s0 + 1):
                b = self.grid.get((r, s))
                if b is not None and b not in out:
                    out.append(b)
        return out

    def _spawn_row(self, r):
        """A new row of the wall at grid row r (tougher the longer the round lasts)."""
        t = self.play_t
        self.rows_spawned += 1
        if t >= GLASS_FROM and self.rows_spawned >= self.next_glass_row:
            self.next_glass_row = self.rows_spawned + GLASS_EVERY + random.randint(-1, 2)
            hp = 1 if t < 100 else 2
            for s in range(6):
                self._add(Brick("glass", "GLAS", r, s, 1, hp))
            return
        empty = max(0.08, 0.3 - t / 450)
        base = 1 + int(t / 15)
        for col in range(3):
            if random.random() < empty:
                continue
            hp = base + random.randint(0, 1 + int(t / 30))
            roll = random.random()
            if roll < 0.14:  # two half bricks
                for half in range(2):
                    if random.random() < 0.8:
                        self._add(Brick("minion", "HAHA", r, 2 * col + half, 1, max(1, hp // 2)))
            elif roll < 0.14 + min(0.16, 0.04 + t / 1200):
                self._add(Brick("armor", "HERRENCLUB", r, 2 * col, 2, 3 + hp + int(t / 30)))
            elif roll < 0.38:
                self._add(Brick("stammtisch", "STAMMTISCH", r, 2 * col, 2, hp + 1))
            else:
                self._add(Brick("normal", random.choice(NORMAL_LABELS), r, 2 * col, 2, hp))

    def _spawn_boss(self, r):
        self.boss = self._add(Brick("boss", "PATRIARCHAT", r, 0, 6, BOSS_HP + BOSS_HP_PER_KILL * self.boss_kills, rows=2))
        self.next_boss_at = self.play_t + BOSS_EVERY
        self.banner = ("ACHTUNG!", "Das PATRIARCHAT rückt an.", "Zerschlag es, bevor es unten ist!", self.t)
        self.quip = ("Ich bin wieder da!" if self.boss_kills else "Hier ändert sich gar nix!", self.t + 2.0)

    def boss_name(self):
        return "PATRIARCHAT" if self.boss_kills == 0 else f"PATRIARCHAT {self.boss_kills + 1}.0"

    # ---- input --------------------------------------------------------
    def tap(self, x, y):
        self.tap_pos = (x, y)
        return super().tap(x, y)

    def play_tap(self):
        if self.cards is not None:
            if self.t - self.cards_at >= CARD_TAP_DELAY:
                hit = next((k for k, rect in self.cards if rect.collidepoint(self.tap_pos)), None)
                if hit:
                    self._pick(hit)
            return
        self.paddle_target = float(self.tap_pos[0])
        self._clamp_target()

    def drag(self, x, y):
        if self.state != "play" or self.cards is not None:
            return
        self.paddle_target = float(x)
        self._clamp_target()
        self.paddle_x = self.paddle_target

    def release(self):
        """Balls launch by themselves - nothing to do when the finger lifts."""

    def _clamp_target(self):
        half = self.paddle_w / 2
        self.paddle_target = max(half, min(self.width - half, self.paddle_target))

    # ---- helpers ------------------------------------------------------
    def wall_speed(self):
        if self.t < self.streik_until:
            return 0.0
        v = min(MAX_WALL_SPEED, WALL_SPEED + WALL_SPEED_RAMP * self.play_t)
        return v * (BOSS_WALL_FACTOR if self.boss else 1.0)

    def ball_speed(self):
        return BALL_SPEED + min(MAX_BALL_RAMP, BALL_SPEED_RAMP * self.play_t)

    def _add_parts(self, parts):
        self.parts.extend(parts)
        if len(self.parts) > MAX_PARTICLES:
            del self.parts[: len(self.parts) - MAX_PARTICLES]

    def _hitstop(self, frames, force=False):
        if force or self.t >= self.hitstop_ready:
            self.freeze = max(self.freeze, frames)
            self.hitstop_ready = self.t + 0.35

    def _popup(self, text, x, y, color=WHITE, size=16, life=0.9, rise=50.0):
        x = max(70, min(self.width - 70, x))
        self.popups.append(Popup(text, x, y, color, size, life, rise))
        if len(self.popups) > 12:
            del self.popups[0]

    def _park(self, b, hidden=RESPAWN_SECONDS):
        """Ball goes onto the paddle (after `hidden` s) and launches by itself."""
        b.stuck = True
        b.hidden_until = self.t + hidden
        b.launch_at = self.t + hidden + LAUNCH_DELAY
        b.trail = []
        b.pierce = 0
        b.ignore = None

    def _launch(self, b):
        b.stuck = False
        a = random.uniform(-0.4, 0.4)
        b.set_dir(math.sin(a), -math.cos(a))
        self._reload(b)

    def _reload(self, b):
        b.pierce = (0, 3, 5, 8)[self.lv.get("demo", 0)] if b.kind == "demo" else 0
        b.home = (0, 2, 4, 6)[self.lv.get("plenum", 0)] if b.kind == "plenum" else 0

    # ---- simulation ---------------------------------------------------
    def step(self, dt):
        self.t += dt
        if self.freeze > 0:  # hit-stop: the world holds still
            self.freeze -= 1
            self.flash *= 0.7
            return
        if self.state == "ready":
            return
        for o in self.parts:
            o.step(dt)
        for p in self.popups:
            p.step(dt)
        self.parts = [p for p in self.parts if p.age < p.life and p.y < self.height + 40]
        self.popups = [p for p in self.popups if p.age < p.life]
        self.shake *= 0.62
        self.flash *= 0.55
        if self.state != "play":
            return
        if self.cards is not None:  # level-up choice: everything waits
            if self.t - self.cards_at >= CARD_AUTO_PICK:
                self._pick(self.cards[0][0])
            return
        self.play_t += dt
        self._step_paddle(dt)
        self._step_wall(dt)
        if self.state != "play":
            return
        self._step_chain()
        self._step_fire(dt)
        speed = self.ball_speed()
        for b in list(self.balls):
            if b.stuck:
                b.x = self.paddle_x + b.offset
                b.y = self.paddle_y - b.r
                if self.t >= b.launch_at:
                    self._launch(b)
                continue
            if b.mini:
                b.life -= dt
            self._move_ball(b, speed * dt)
            b.trail.append((b.x, b.y))
            if len(b.trail) > 4:
                b.trail.pop(0)
            if b.y - b.r > self.height or (b.mini and b.life <= 0):
                if b.mini:
                    self.balls.remove(b)
                else:  # dropped: the wall uses the gap
                    self._park(b)
                    self.wall_y += DROP_PUSH
                    self._popup("Lücke! Die Wand rückt nach.", self.width / 2, self.danger_y + 40, (255, 140, 160), 15, life=1.0, rise=10)
        self._step_konfetti(dt)
        self._step_gems(dt)
        if self.pending_levelups and self.cards is None:
            self.pending_levelups -= 1
            self._open_cards()

    def _step_paddle(self, dt):
        step = PADDLE_MAX_SPEED * dt
        d = self.paddle_target - self.paddle_x
        self.paddle_x += max(-step, min(step, d))
        half = self.paddle_w / 2
        self.paddle_x = max(half, min(self.width - half, self.paddle_x))

    def _step_wall(self, dt):
        self.wall_y += self.wall_speed() * dt
        # keep the wall topped up: new rows slide in under the HUD
        while self.wall_y + self.top_row * ROW_STEP > HUD_H + 6 - ROW_STEP + 1:
            if self.boss is None and self.play_t >= self.next_boss_at:
                self.top_row -= 2
                self._spawn_boss(self.top_row)
            else:
                self.top_row -= 1
                self._spawn_row(self.top_row)
        lowest = max((self.brick_rect(b).bottom for b in self.bricks), default=0)
        if lowest >= self.danger_y:
            self._breach()

    def _breach(self):
        """A brick reached the danger line: -1 heart, the bottom rows are wiped."""
        self.hearts -= 1
        self.breaches += 1
        self.red_until = self.t + 0.6
        self.shake = 16
        self._hitstop(6, force=True)
        limit = self.danger_y - 3 * ROW_STEP
        for b in list(self.bricks):
            r = self.brick_rect(b)
            if r.bottom > limit or b is self.boss and r.bottom > limit - ROW_STEP:
                self._remove(b)
                self._add_parts([Particle(random.uniform(r.left, r.right), random.uniform(r.top, r.bottom), random.uniform(-200, 200),
                                          random.uniform(-300, 50), (110, 90, 120), random.randint(6, 12), random.uniform(0.6, 1.0))
                                 for _ in range(6)])
        if self.hearts <= 0:
            secs = int(self.play_t)
            self.game_over(f"{random.choice(OVER_LINES)} {secs // 60}:{secs % 60:02d} durchgehalten")
            return
        self.banner = ("DURCHBRUCH!", random.choice(BREACH_LINES), f"-1 Herz, noch {self.hearts}", self.t)

    def _move_ball(self, b, dist):
        n = max(1, int(math.ceil(dist / SUBSTEP_PX)))
        step = dist / n
        r = b.r
        for _ in range(n):
            b.x += b.dx * step
            b.y += b.dy * step
            if b.x < r:
                b.x = r
                b.set_dir(abs(b.dx), b.dy)
            elif b.x > self.width - r:
                b.x = self.width - r
                b.set_dir(-abs(b.dx), b.dy)
            if b.y < HUD_H + r:
                b.y = HUD_H + r
                b.set_dir(b.dx, abs(b.dy))
            if b.dy > 0 and self._paddle_hit(b):
                continue
            if b.ignore is not None and (not b.ignore.alive or not self._overlaps(b, self.brick_rect(b.ignore))):
                b.ignore = None
            for k in self._near(b.x, b.y):
                if k is b.ignore:
                    continue
                rect = self.brick_rect(k)
                if not self._overlaps(b, rect):
                    continue
                if b.pierce > 0 and k.kind != "boss":  # Demo-Zug: straight through
                    b.pierce -= 1
                    b.ignore = k
                    self._ball_hit(b, k, (b.x, b.y))
                    if b.pierce == 0:
                        self.headline = ("DEMO-ZUG RAUSCHT DURCH!", self.t)
                    break
                self._collide(b, rect, k)
                self._ball_hit(b, k, (b.x, b.y))
                if b.home > 0:
                    self._home(b, k)
                break

    @staticmethod
    def _overlaps(b, rect):
        return PatriaputtGame._overlaps_at(b.x, b.y, b.r, rect)

    @staticmethod
    def _overlaps_at(x, y, r, rect):
        cx = min(max(x, rect.left), rect.right)
        cy = min(max(y, rect.top), rect.bottom)
        return (x - cx) ** 2 + (y - cy) ** 2 < r * r

    def _fits(self, b, x, y, hit):
        """Is there room for ball b at (x, y): inside the play field, touching no brick but `hit`?"""
        if x < b.r or x > self.width - b.r or y < HUD_H + b.r:
            return False
        for k in self._near(x, y):
            if k is not hit and self._overlaps_at(x, y, b.r, self.brick_rect(k)):
                return False
        return True

    def _collide(self, b, rect, hit):
        """Push the ball out of rect and reflect it: along the shallower axis,
        unless the ball doesn't fit there (the 6 px between two bricks, rows
        or a brick and the screen edge) - then along the other one. Before,
        a ball in such a gap rattled along it, hitting both sides every
        substep (5 hits a frame). Fits nowhere (the wall jumped onto it after
        a drop): it drops out below the bricks it's stuck in."""
        r = b.r
        pen_x = min(b.x + r - rect.left, rect.right - (b.x - r))
        pen_y = min(b.y + r - rect.top, rect.bottom - (b.y - r))
        side_x = rect.left - r if b.x < rect.centerx else rect.right + r
        side_y = rect.top - r if b.y < rect.centery else rect.bottom + r
        fit_x = self._fits(b, side_x, b.y, hit)
        fit_y = self._fits(b, b.x, side_y, hit)
        if fit_x and (pen_x < pen_y or not fit_y):
            b.x = side_x
            b.set_dir(-abs(b.dx) if side_x < rect.centerx else abs(b.dx), b.dy)
        elif fit_y:
            b.y = side_y
            b.set_dir(b.dx, -abs(b.dy) if side_y < rect.centery else abs(b.dy))
        else:
            y = rect.bottom + r
            for _ in range(40):
                k = next((k for k in self._near(b.x, y) if self._overlaps_at(b.x, y, r, self.brick_rect(k))), None)
                if k is None:
                    break
                y = self.brick_rect(k).bottom + r
            b.y = y
            b.set_dir(b.dx, abs(b.dy))

    def _home(self, b, hit):
        """Plenumsball: jump straight on to the nearest other brick."""
        best, best_d = None, 1e9
        wall = self.brick_rect(hit).inflate(2 * b.r - 2, 2 * b.r - 2)
        for k in self.bricks:
            if k is hit or not k.alive:
                continue
            c = self.brick_rect(k).center
            if wall.clipline((b.x, b.y), c):  # not back through the brick it just hit
                continue
            d = (c[0] - b.x) ** 2 + (c[1] - b.y) ** 2
            if d < best_d:
                best, best_d = k, d
        if best is not None:
            c = self.brick_rect(best).center
            b.set_dir(c[0] - b.x, c[1] - b.y)
            b.home -= 1

    def _paddle_hit(self, b):
        w = self.paddle_w
        left = self.paddle_x - w / 2
        if not (self.paddle_y - b.r <= b.y <= self.paddle_y + PADDLE_H * 0.6 and left - b.r <= b.x <= left + w + b.r):
            return False
        off = max(-1.0, min(1.0, (b.x - self.paddle_x) / (w / 2 + b.r)))
        a = math.radians(off * MAX_BOUNCE_DEG)
        b.y = self.paddle_y - b.r
        b.set_dir(math.sin(a), -math.cos(a))
        self.paddle_bump_until = self.t + 0.1
        self._reload(b)
        if b.kind == "soli" and not b.mini:
            n = self.lv.get("soli", 1)
            for i in range(n):
                if len(self.balls) >= MAX_BALLS:
                    break
                m = Ball("mini", b.x, b.y, mini=True)
                a2 = a + (i + 1) * 0.35 * (1 if i % 2 == 0 else -1)
                m.set_dir(math.sin(a2), -math.cos(a2))
                self.balls.append(m)
        return True

    # ---- damage -------------------------------------------------------
    def _dmg(self, b, k):
        base = 1 + self.wut
        if b is not None and b.mini:
            base = 1
        if b is not None and b.kind == "quote" and k.kind in ("boss", "armor"):
            return base * (1 + self.lv.get("quote", 1))
        if k.kind == "armor":
            return 1
        if self.lv.get("generalstreik") and self.t < self.streik_until:
            base *= 2
        return base

    def _ball_hit(self, b, k, pos):
        self._damage(k, self._dmg(b, k))
        kind = b.kind
        if kind == "glitzer":
            self._glitter(pos, k)
        elif kind == "brand":
            self._ignite(k)
        elif kind == "streik" and self.t >= self.streik_ready:
            lvl = self.lv.get("streik", 1)
            dur = (0, 1.5, 2.5, 3.5)[lvl] * (2 if self.lv.get("generalstreik") else 1)
            self.streik_until = self.t + dur
            self.streik_ready = self.t + (0, 8, 7, 6)[lvl]
            self.stamp = ("STREIK!", 5, (200, 120, 0), self.t)
            self.headline = ("Die Wand steht still!", self.t)
        if k.kind == "boss":
            self._hitstop(1)
            self.shake = max(self.shake, 5)
            if self.t >= self.quip_ready and random.random() < 0.5:
                self.quip = (random.choice(BOSS_QUIPS), self.t + 1.4)
                self.quip_ready = self.t + 3.5

    def _glitter(self, pos, hit):
        lvl = self.lv.get("glitzer", 1)
        radius = (0, 75, 100, 100)[lvl]
        dmg = 2 if lvl >= 3 else 1
        for k in list(self.bricks):
            if k is hit or not k.alive:
                continue
            rect = self.brick_rect(k)
            cx = min(max(pos[0], rect.left), rect.right)
            cy = min(max(pos[1], rect.top), rect.bottom)
            if (cx - pos[0]) ** 2 + (cy - pos[1]) ** 2 <= radius * radius:
                self._damage(k, dmg)
                if self.lv.get("feuerwerk"):
                    self._ignite(k)
        self._add_parts([Particle(pos[0], pos[1], random.uniform(-1, 1) * radius * 3, random.uniform(-1, 1) * radius * 3,
                                  random.choice(RAINBOW + [PINK, WHITE, GOLD]), random.randint(3, 7), 0.35, "glitter", g=200)
                         for _ in range(10)])

    def _ignite(self, k):
        if not k.alive:
            return
        dur = (3.0 if self.lv.get("brand", 1) < 2 else 5.0) + 0.1  # 3 / 5 ticks of 1 damage
        if k.fire_until < self.t:
            k.fire_tick = self.t + 1.0
        k.fire_until = max(k.fire_until, self.t + dur)

    def _step_fire(self, dt):
        for k in list(self.bricks):
            if k.fire_until > self.t and self.t >= k.fire_tick:
                k.fire_tick += 1.0
                self._damage(k, 1)

    def _damage(self, k, n):
        if not k.alive:
            return
        k.hp -= n
        k.flash_until = self.t + 0.06
        k.wobble_until = self.t + 0.15
        self.score += 10 * n
        if k.kind == "boss":
            self.boss_damage_total += n
        if k.hp <= 0:
            self._break(k)

    def _break(self, k):
        rect = self.brick_rect(k)
        self._remove(k)
        cx, cy = rect.center
        self.score += 25 * k.max_hp
        self.counts[k.label] = self.counts.get(k.label, 0) + 1
        if k.kind == "boss":
            self._kill_boss(rect)
            return
        if k.kind == "glass":
            self._shatter(k, rect)
        else:
            color = BRICKS[k.label][0]
            self._add_parts([Particle(cx + random.uniform(-rect.w / 2, rect.w / 2), cy + random.uniform(-10, 10), random.uniform(-240, 240),
                                      random.uniform(-320, 60), random.choice([color, color, shade(color, 1.2), WHITE]),
                                      random.randint(6, 12), random.uniform(0.5, 0.9)) for _ in range(10 if k.span == 2 else 5)])
            self.shake = max(self.shake, 4)
            if self.t >= self.headline_ready:
                self.headline = (BRICKS[k.label][2], self.t)
                self.headline_ready = self.t + 1.4
        if k.fire_until > self.t and self.lv.get("brand", 0) >= 3:  # Flächenbrand
            for n in self._near(cx, cy):
                self._ignite(n)
        if k.kind == "stammtisch":  # falls apart into two HAHA minions
            for half in range(2):
                self._add(Brick("minion", "HAHA", k.r, k.slot + half, 1, max(1, k.max_hp // 2)))
        self.gems.append(Gem(cx, cy, max(1, min(6, k.max_hp))))

    def _shatter(self, k, rect):
        self._add_parts([Particle(rect.centerx + random.uniform(-25, 25), rect.centery, random.uniform(-260, 260),
                                  random.uniform(-200, 240), GLASS, random.randint(7, 14), random.uniform(0.6, 1.0), "shard", g=700)
                         for _ in range(6)])
        if not self.chain and not self._in_chain:  # the first pane: hit-stop, flash, KLIRR
            self._hitstop(2, force=True)
            self.flash = max(self.flash, 70)
            self.shake = max(self.shake, 8)
            self._popup("KLIRR!", rect.centerx, rect.centery + 30, GLASS_L, 24, life=0.8)
        for s in (k.slot - 1, k.slot + 1):  # the whole row goes, pane by pane
            n = self.grid.get((k.r, s))
            if n is not None and n.kind == "glass" and all(n is not c[1] for c in self.chain):
                self.chain.append((self.t + 0.07, n))

    def _step_chain(self):
        due = [c for c in self.chain if self.t >= c[0]]
        self.chain = [c for c in self.chain if self.t < c[0]]
        self._in_chain = True
        for _, n in due:
            if n.alive:
                self._damage(n, n.hp)
        self._in_chain = False
        if due and not self.chain:
            self.banner = ("KLIRR!", "GLÄSERNE DECKE DURCHBROCHEN", "", self.t)

    def _kill_boss(self, rect):
        self.boss_kills += 1
        self.score += 2000 * self.boss_kills
        self._hitstop(8, force=True)
        self.shake = 18
        self.flash = 200
        self.quip = None
        extra = self.hearts < HEARTS
        self.hearts = min(HEARTS, self.hearts + 1)
        self.banner = ("PATRIAPUTT!", f"+{fmt(2000 * self.boss_kills)}" + ("   +1 Herz" if extra else ""),
                       "Es wankt nicht mehr. Es fällt.", self.t)
        self._add_parts([Particle(random.uniform(rect.left, rect.right), random.uniform(rect.top, rect.bottom), random.uniform(-300, 300),
                                  random.uniform(-400, 200), (120, 110, 140), random.randint(8, 16), random.uniform(0.8, 1.4))
                         for _ in range(30)])
        self._add_parts([Particle(random.uniform(0, self.width), random.uniform(rect.top, rect.bottom), random.uniform(-200, 200),
                                  random.uniform(-500, 0), random.choice(RAINBOW + [PINK, WHITE, GOLD]), random.randint(3, 8),
                                  random.uniform(1.0, 1.6), "glitter", g=420) for _ in range(70)])
        for i in range(8):
            self.gems.append(Gem(rect.left + (i + 0.5) * rect.w / 8, rect.centery, 5))

    def _step_konfetti(self, dt):
        lvl = self.lv.get("konfetti", 0)
        if lvl and self.t >= self.konfetti_next:
            self.konfetti_next = self.t + (0, 1.0, 0.67, 0.5)[lvl]
            xs = (self.paddle_x - self.paddle_w / 2 + 10, self.paddle_x + self.paddle_w / 2 - 10) if lvl >= 3 else (self.paddle_x,)
            for x in xs:
                self.shots.append([x, float(self.paddle_y - 4), random.choice([PINK, GOLD, MINT, SKY, WHITE])])
        for s in list(self.shots):
            s[1] -= 720 * dt
            hit = next((k for k in self._near(s[0], s[1]) if self.brick_rect(k).collidepoint(s[0], s[1])), None)
            if hit is not None:
                self.shots.remove(s)
                self._damage(hit, 1 + self.wut if hit.kind != "armor" else 1)
                self._add_parts([Particle(s[0], s[1], random.uniform(-120, 120), random.uniform(0, 160), s[2], 4, 0.35, "glitter", g=300)
                                 for _ in range(3)])
            elif s[1] < HUD_H:
                self.shots.remove(s)

    def _step_gems(self, dt):
        left = self.paddle_x - self.paddle_w / 2 - 6
        right = self.paddle_x + self.paddle_w / 2 + 6
        for g in list(self.gems):
            g.age += dt
            g.vy = min(GEM_SPEED, g.vy + 500 * dt)
            g.vx *= 0.9
            if g.y > self.paddle_y - MAGNET_RANGE and abs(g.x - self.paddle_x) < self.paddle_w / 2 + MAGNET_SIDE:  # magnet
                g.vx = (self.paddle_x - g.x) * 6
                g.vy = max(g.vy, 260)
            g.x += g.vx * dt
            g.y += g.vy * dt
            if self.paddle_y - 8 <= g.y <= self.paddle_y + PADDLE_H and left <= g.x <= right:
                self.gems.remove(g)
                self._gain_xp(g.value)
                self._add_parts([Particle(g.x, self.paddle_y, random.uniform(-120, 120), random.uniform(-240, -80), MINT, 4, 0.4, "glitter", g=500)
                                 for _ in range(4)])
            elif g.y > self.height + 10:
                self.gems.remove(g)

    def _gain_xp(self, n):
        self.xp += n
        while self.xp >= self.xp_next:
            self.xp -= self.xp_next
            self.xp_next = int(self.xp_next * XP_GROWTH + 2)
            self.player_lv += 1
            self.pending_levelups += 1

    # ---- upgrades -----------------------------------------------------
    def offer(self):
        pool = []
        for kind, (_, _, _, max_lv) in CARDS.items():
            lvl = self.lv.get(kind, 0)
            if lvl >= max_lv:
                continue
            if kind == "herz":
                if self.hearts < HEARTS:
                    pool.append((kind, 1))
            elif kind == "feuerwerk":
                if self.lv.get("glitzer", 0) >= 3 and self.lv.get("brand", 0) >= 1:
                    pool.append((kind, 8))
            elif kind == "generalstreik":
                if self.lv.get("streik", 0) >= 3 and self.lv.get("demo", 0) >= 1:
                    pool.append((kind, 8))
            elif kind in BALL_KINDS:
                pool.append((kind, 4 if lvl == 0 else 3))
            else:
                pool.append((kind, 2))
        out = []
        while pool and len(out) < 3:
            kind = random.choices([p[0] for p in pool], [p[1] for p in pool])[0]
            out.append(kind)
            pool = [p for p in pool if p[0] != kind]
        return out

    def _open_cards(self):
        kinds = self.offer()
        if not kinds:
            return
        top = 230
        self.cards = [(k, pygame.Rect(20, top + i * 142, self.width - 40, 128)) for i, k in enumerate(kinds)]
        self.cards_at = self.t
        self._cards_surf = None

    def _pick(self, kind):
        lvl = self.lv.get(kind, 0) + 1
        self.lv[kind] = lvl
        self.picked.append(kind)
        if kind in BALL_KINDS and lvl == 1:
            b = Ball(kind, self.paddle_x, self.paddle_y - BALL_R)
            self._park(b, hidden=0.0)
            self.balls.append(b)
        elif kind == "disco":
            b = Ball("disco", self.paddle_x, self.paddle_y - BALL_R)
            self._park(b, hidden=0.0)
            self.balls.append(b)
        elif kind == "wut":
            self.wut += 1
        elif kind == "herz":
            self.hearts = min(HEARTS, self.hearts + 1)
        self.cards = None
        self._cards_surf = None
        self.stamp = (PICK_STAMPS.get(kind, CARDS[kind][0].upper()) + "!", -4, (20, 140, 80), self.t)

    # ---- drawing ------------------------------------------------------
    def draw(self, surf):
        if self.state == "ready":
            self._draw_start(surf)
            return
        sh = self.shake
        ox, oy = (random.uniform(-sh, sh), random.uniform(-sh, sh)) if sh > 0.5 else (0, 0)
        surf.blit(backdrop(self.width, self.height), (0, 0))
        self._draw_danger(surf)
        frozen = self.t < self.streik_until
        for k in self.bricks:
            self._blit_brick(surf, k, ox, oy, frozen)
        for g in self.gems:
            img = gem_surface(12 if g.value < 2 else (16 if g.value < 5 else 20))
            surf.blit(img, img.get_rect(center=(int(g.x + ox), int(g.y + oy))))
        for x, y, col in self.shots:
            pygame.draw.rect(surf, INK, (int(x) - 3, int(y) - 6, 7, 12))
            pygame.draw.rect(surf, col, (int(x) - 2, int(y) - 5, 5, 10))
        self._draw_paddle(surf)
        self._draw_balls(surf, ox, oy)
        for p in self.parts:
            p.draw(surf, ox, oy)
        self._draw_texts(surf)
        if self.flash > 3:
            fl = solid_surface(self.width, self.height, WHITE)
            fl.set_alpha(int(min(170, self.flash)))
            surf.blit(fl, (0, 0))
        if self.t < self.red_until:
            pygame.draw.rect(surf, (230, 30, 60), (0, 0, self.width, self.height), 12)
        self._draw_hud(surf)
        if self.cards is not None and self.state == "play":
            self._draw_cards(surf)
        if self.state == "over":
            if self.t - self.over_at_t < 0.8:
                K.wordart(surf, "DURCHBRUCH!", 46, (self.width // 2, self.height // 2 - 40), wave=7)
            else:
                self._draw_over(surf)

    def game_over(self, text):
        self.over_at_t = self.t
        super().game_over(text)

    def _draw_danger(self, surf):
        lowest = max((self.brick_rect(b).bottom for b in self.bricks), default=0)
        gap = self.danger_y - lowest
        near = gap < 2 * ROW_STEP
        if near:
            surf.blit(danger_glow(self.width), (0, self.danger_y - 40))
        col = (255, 60, 90) if not near or int(self.t * 6) % 2 == 0 else (255, 200, 210)
        for x in range(0, self.width, 20):
            pygame.draw.line(surf, col, (x, self.danger_y), (x + 11, self.danger_y), 3)
        if near and int(self.t * 3) % 2 == 0:
            outlined(surf, "ACHTUNG: GLEICH DURCHBRUCH!", 16, (255, 120, 140), (self.width // 2, self.danger_y + 18))

    def _blit_brick(self, surf, k, ox, oy, frozen):
        r = self.brick_rect(k).move(ox, oy)
        if r.bottom < HUD_H:
            return
        if self.t < k.wobble_until and k.kind != "boss":
            r = r.move(int(math.sin(self.t * 80) * 2), 0)
        if self.t < k.flash_until and k.kind not in ("glass", "boss"):
            pygame.draw.rect(surf, INK, r.inflate(2, 2))
            pygame.draw.rect(surf, WHITE, r)
        elif k.kind == "glass":
            surf.blit(glass_surface(r.w, r.h, k.hp), r)
        elif k.kind == "boss":
            surf.blit(boss_surface(r.w, r.h, self.boss_name()), (r.x - 1, r.y - 1))
            frac = max(0.0, min(1.0, k.hp / k.max_hp))
            bar = pygame.Rect(r.x + 60, r.bottom - 16, r.w - 120, 9)
            pygame.draw.rect(surf, INK, bar.inflate(4, 4))
            pygame.draw.rect(surf, (70, 40, 60), bar)
            pygame.draw.rect(surf, RED, (bar.x, bar.y, int(bar.w * frac), bar.h))
            outlined(surf, f"{k.hp} HP", 15, WHITE, (r.centerx, bar.top - 11))
            if self.t < k.flash_until:  # hit: white rim instead of a white block (it gets hit a lot)
                pygame.draw.rect(surf, WHITE, r.inflate(4, 4), 3)
        else:
            surf.blit(brick_surface(k.kind, k.label, r.w, r.h, max(1, k.hp), k.max_hp), (r.x - 1, r.y - 1))
        if frozen:
            pygame.draw.rect(surf, ICE, r.inflate(2, 2), 3)
            for x in range(r.x + 8, r.right - 4, 18):
                pygame.draw.polygon(surf, ICE, [(x, r.bottom), (x + 6, r.bottom), (x + 3, r.bottom + 6)])
        if k.fire_until > self.t:
            for i, fx in enumerate((r.x + 12, r.centerx, r.right - 34)):
                h = 10 + int(4 * math.sin(self.t * 20 + i * 2))
                pygame.draw.polygon(surf, ORANGE, [(fx - 6, r.y + 4), (fx, r.y + 4 - h), (fx + 6, r.y + 4)])
                pygame.draw.polygon(surf, GOLD, [(fx - 3, r.y + 4), (fx, r.y + 6 - h // 2), (fx + 3, r.y + 4)])

    def _draw_paddle(self, surf):
        w = int(self.paddle_w)
        img = paddle_surface(w, "PLENUM")
        y = self.paddle_y + (3 if self.t < self.paddle_bump_until else 0)
        surf.blit(img, (int(self.paddle_x - w / 2) - 2, y - 2))
        if self.lv.get("konfetti"):  # little cannon(s) on the banner
            lvl = self.lv["konfetti"]
            xs = (self.paddle_x - w / 2 + 10, self.paddle_x + w / 2 - 10) if lvl >= 3 else (self.paddle_x,)
            for x in xs:
                pygame.draw.rect(surf, INK, (int(x) - 5, y - 9, 10, 10))
                pygame.draw.rect(surf, SKY, (int(x) - 3, y - 7, 6, 7))

    def _draw_balls(self, surf, ox, oy):
        f = int(self.t * 8) % 2
        for b in self.balls:
            if b.stuck and self.t < b.hidden_until:
                continue
            col = TRAILS[b.kind]
            for i, (tx, ty) in enumerate(b.trail[:-1]):
                pygame.draw.circle(surf, col, (int(tx + ox), int(ty + oy)), max(2, b.r // 3 + i))
            frames = ball_frames(b.kind, b.r)
            img = frames[(f + int(self.t * 10)) % len(frames)] if b.kind == "disco" else frames[f]
            surf.blit(img, img.get_rect(center=(int(b.x + ox), int(b.y + oy))))
            if b.pierce > 0 and not b.stuck:  # Demo-Zug: little banner flag behind it
                pygame.draw.line(surf, WHITE, (b.x + ox, b.y + oy), (b.x - b.dx * 22 + ox, b.y - b.dy * 22 + oy), 2)

    def _draw_texts(self, surf):
        w = self.width
        banner_up = self.banner and self.t - self.banner[3] < 1.7 and self.state == "play"
        if self.headline and self.t - self.headline[1] < 1.3 and not banner_up:
            outlined(surf, self.headline[0], 18, GOLD, (w // 2, self.danger_y - 30))
        for p in self.popups:
            outlined(surf, p.text, p.size, p.color, (p.x, p.y))
        if self.stamp and self.t - self.stamp[3] < 1.0:
            text, angle, red, born = self.stamp
            img = stamp_image(text, angle, 28, red)
            age = self.t - born
            if age < 0.12:
                k = 1.0 + (0.12 - age) * 5
                img = pygame.transform.scale(img, (int(img.get_width() * k), int(img.get_height() * k)))
            surf.blit(img, img.get_rect(center=(w // 2, self.danger_y - 90)))
        if banner_up:
            text, sub, sub2, born = self.banner
            age = self.t - born
            size = 50 if len(text) < 10 else 40
            y = self.height // 2 - 20 + int(max(0.0, 0.15 - age) * 300)
            K.wordart(surf, text, size, (w // 2, y), wave=6)
            if sub:
                outlined(surf, sub, 18, (225, 245, 255), (w // 2, y + 54))
            if sub2:
                outlined(surf, sub2, 16, GOLD, (w // 2, y + 80))
        if self.quip and self.t < self.quip[1] and self.boss is not None:
            br = self.brick_rect(self.boss)
            text = self.quip[0]
            tw = K.font(15).size(text)[0]
            r = pygame.Rect(0, 0, tw + 22, 34)
            r.midtop = (w // 2 + 30, br.bottom + 22)
            r.clamp_ip(pygame.Rect(4, HUD_H, w - 8, self.height))
            K.speech(surf, r, [text], (w // 2, br.bottom - 4), size=15)
        if self.state == "play" and self.play_t < 8:
            outlined(surf, "<  ziehen  >", 16, (230, 210, 255), (w // 2, self.height - 30), thick=1)

    def _draw_hud(self, surf):
        key = (self.score, self.hearts, self.player_lv, self.xp, self.xp_next)
        if key != self._hud_key:
            self._hud_key = key
            if self._hud is None:
                self._hud = pygame.Surface((self.width, HUD_H))
            h = self._hud
            K.bevel(h, pygame.Rect(0, 0, self.width, HUD_H))
            bar = pygame.Rect(self.width // 2 - 48, 15, 120, 14)
            lv = K.t95(h, f"Lv{self.player_lv}", 16, (bar.left - 6, 22), anchor="midright", color=K.F_ACCENT)
            score = fmt(self.score)
            K.t95(h, score, K.fit_size(score, lv.left - 8 - 12, sizes=(22, 20, 18, 16, 14)), (12, 22), anchor="midleft")
            K.bevel(h, bar.inflate(4, 4), sunken=True, face=K.F_PAPER)
            pygame.draw.rect(h, MINT, (bar.x, bar.y, int(bar.w * min(1.0, self.xp / self.xp_next)), bar.h))
            gem = gem_surface(12)
            h.blit(gem, gem.get_rect(center=(bar.right + 14, 22)))
            for i in range(HEARTS):
                K.heart(h, (self.width - 88 + i * 30, 15), 3, PINK if i < self.hearts else (150, 130, 170))
        surf.blit(self._hud, (0, 0))

    def _draw_cards(self, surf):
        if self._cards_surf is None:
            self._cards_surf = canvas(self.width, self.height)
            s = self._cards_surf
            s.blit(fog_surface(self.width, self.height), (0, 0))
            K.wordart(s, "LEVEL UP!", 50, (self.width // 2, 130), wave=7)
            outlined(s, "Wähl eine Verstärkung, Genoss*in:", 18, WHITE, (self.width // 2, 196))
            for kind, rect in self.cards:
                name, color, descs, max_lv = CARDS[kind]
                lvl = self.lv.get(kind, 0) + 1
                pygame.draw.rect(s, K.SHADOW, rect.move(6, 6))
                K.bevel(s, rect)
                strip = pygame.Rect(rect.x + 4, rect.y + 4, 104, rect.h - 8)
                pygame.draw.rect(s, shade(color, 0.55), strip)
                pygame.draw.rect(s, color, strip.inflate(-8, -8))
                self._card_icon(s, kind, strip.center)
                tag = "NEU!" if lvl == 1 and 1 < max_lv < 99 and kind not in ("disco", "wut") else (f"Lv{lvl}" if 1 < max_lv < 99 else "")
                if kind in ("feuerwerk", "generalstreik"):
                    tag = "EVOLUTION"
                x = strip.right + 12
                K.t95(s, name, 20, (x, rect.y + 12))
                if tag:
                    K.t95(s, tag, 15, (rect.right - 10, rect.y + 16), color=K.F_LATE if tag in ("NEU!", "EVOLUTION") else K.F_ACCENT,
                          anchor="topright")
                for i, line in enumerate(descs[min(lvl, len(descs)) - 1]):
                    size = K.fit_size(line, rect.right - 10 - x, sizes=(15, 14, 13, 12), bold=False)
                    K.t95(s, line, size, (x, rect.y + 50 + i * 24), bold=False)
                if max_lv > 1 and max_lv < 99:
                    for i in range(max_lv):
                        pip = pygame.Rect(x + i * 20, rect.bottom - 18, 14, 8)
                        pygame.draw.rect(s, K.F_ACCENT if i < lvl else K.F_DARK, pip, 0 if i < lvl else 1)
        surf.blit(self._cards_surf, (0, 0))
        if self.t - self.cards_at >= CARD_TAP_DELAY and int(self.t * 2) % 2 == 0:
            outlined(surf, "Karte antippen!", 18, GOLD, (self.width // 2, self.height - 44))

    def _card_icon(self, s, kind, center):
        if kind in BALL_KINDS:
            img = pygame.transform.scale(ball_frames(kind, BALL_R)[0], (72, 72))
        elif kind == "disco":
            img = pygame.transform.scale(disco_frames(BALL_R)[0], (72, 72))
        elif kind == "konfetti":
            img = pygame.transform.scale(ball_frames("konfetti", BALL_R)[0], (72, 72))
        elif kind == "herz":  # ink-outlined red heart: a pink one vanished on the pink strip
            for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
                K.heart(s, (center[0] + dx, center[1] - 4 + dy), 6, INK)
            K.heart(s, (center[0], center[1] - 4), 6, RED)
            return
        elif kind == "wut":
            img = icon("fist", 64)
        elif kind == "feuerwerk":
            img = pygame.transform.scale(ball_frames("glitzer", BALL_R)[0], (72, 72))
            star(s, (center[0] + 30, center[1] - 30), 14, ORANGE)
        else:
            img = pygame.transform.scale(ball_frames("streik", BALL_R)[0], (72, 72))
        s.blit(img, img.get_rect(center=center))

    def _draw_start(self, surf):
        if self._start_surf is None:
            self._start_surf = pygame.Surface((self.width, self.height))
            self._render_start(self._start_surf)
        surf.blit(self._start_surf, (0, 0))
        K.button(surf, pygame.Rect(self.width // 2 - 130, 636, 260, 54), "LOS GEHT'S!", size=20,
                 pressed=int(self.last_tick * 2) % 2 == 1)
        px = self.width // 2 + int(math.sin(self.last_tick * 1.6) * 60)
        surf.blit(paddle_surface(PADDLE_W, "PLENUM"), (px - PADDLE_W // 2 - 2, 712))
        hop = abs(math.sin(self.last_tick * 5)) * 8
        ball = disco_frames()[int(self.last_tick * 10) % 4]
        surf.blit(ball, ball.get_rect(center=(px, 712 - BALL_R - 1 - hop)))

    def _render_start(self, s):
        w = self.width
        s.blit(backdrop(self.width, self.height), (0, 0))
        K.wordart(s, "PATRIAPUTT", 44, (w // 2, 62), wave=7)
        K.t95(s, "Das Patriarchat rückt vor.", 17, (w // 2, 118), color=WHITE, anchor="center")
        K.t95(s, "Zerschlag es, bevor es unten ist!", 17, (w // 2, 142), color=WHITE, anchor="center")
        win = pygame.Rect(14, 168, w - 28, 456)
        inner = K.dialog(s, win, "anleitung.txt", icon="note", buttons=None)
        K.groupbox(s, pygame.Rect(inner.x + 4, inner.y + 16, inner.w - 8, 136), "Die Wand:")
        bw = (inner.w - 34) // 2
        for i, (kind, label, hp) in enumerate([("normal", "MANSPLAINING", 3), ("armor", "HERRENCLUB", 9),
                                               ("stammtisch", "STAMMTISCH", 4), ("normal", "PAY GAP", 2)]):
            r = pygame.Rect(inner.x + 12 + (i % 2) * (bw + 10), inner.y + 32 + (i // 2) * 42, bw, BRICK_H)
            s.blit(brick_surface(kind, label, r.w, r.h, hp, hp), (r.x - 1, r.y - 1))
        K.t95(s, "Zahl = Treffer. Rote Linie erreicht", 15, (inner.x + 12, inner.y + 116), bold=False)
        K.t95(s, "= -1 Herz. 3 Herzen.", 15, (inner.x + 12, inner.y + 134), bold=False)
        K.groupbox(s, pygame.Rect(inner.x + 4, inner.y + 172, inner.w - 8, 154), "Solidarität sammeln:")
        g = gem_surface(20)
        s.blit(g, (inner.x + 14, inner.y + 190))
        K.t95(s, "fällt aus Steinen -> fangen", 15, (inner.x + 44, inner.y + 201), anchor="midleft", bold=False)
        K.t95(s, "Level-up = neuer Ball:", 15, (inner.x + 14, inner.y + 226))
        for i, kind in enumerate(BALL_KINDS):
            img = pygame.transform.scale(ball_frames(kind, BALL_R)[0], (40, 40))
            s.blit(img, (inner.x + 14 + i * 58, inner.y + 250))
        K.t95(s, "Glitzer Streik Soli Demo Plenum Brand Quote", 15, (inner.x + 12, inner.y + 300), bold=False)
        K.t95(s, "Ziehen = Plenum bewegen.", 16, (inner.x + 12, inner.y + 342))
        K.t95(s, "1 Spieler*in, 3 Herzen, 0 Kompromisse.", 15, (inner.x + 12, inner.y + 368), color=K.F_ACCENT)
        K.t95(s, "Alle ~1 Min: das PATRIARCHAT selbst.", 15, (inner.x + 12, inner.y + 390), bold=False)
        outlined(s, party_games.record_line(type(self)), 15, GOLD, (w // 2, self.height - 13))
