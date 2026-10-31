#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
LASTENRAVE SIMULATOR (lastenrave.exe): stacking-with-physics game for the
KiezOS 161 "Spiele" menu, a party_games._Game like STAPEL-TURM / PATRIAPUTT.

A Lastenrad rides through Berlin at night towards the Rave-Demo. Rave gear
hangs from a crane and swings above it (a real pendulum); a TAP drops the
piece, DRAGGING moves the crane trolley (the piece swings along and keeps
its momentum when dropped), DREHEN turns it by 90 degrees. Early pieces are
boxes (Lautsprecher, Bierkiste, Powerbank, Mischpult), later ones are
awkward (XXL-Pfeffi, Discokugel, Dragonstaff, Glitzer-Einhorn, Bauzaun-Deko,
Sperrmüll-Sofa, Einkaufswagen, Gummi-Flamingo).

Physics (own, cheap, no dependencies):
- Every piece has a sprite drawn in code; its bottom/top contact profile per
  4 px column and its centre of mass come from the sprite's mask. The pile is
  a heightmap of those columns, so pieces land on whatever is under them
  (a Discokugel only touches with a few columns, a Bauzaun with its feet).
- Static balance: when a piece lands, the load on every piece (its own mass
  plus a share of everything resting on it, applied where it rests) must have
  its centre of mass above that piece's contact span. A new piece that hangs
  over tips off (and may land lower or fall onto the street); a lower piece
  that gets overloaded makes the pile above it collapse = game over.
- Dynamics: the whole pile sways as one inverted pendulum strapped to the
  cargo box (Spanngurt spring + damping vs. the gravity torque of the pile's
  centre of mass). Off-centre pieces lean it, tall heavy piles get soft and
  finally unstable, landing impacts and the road (Kopfsteinpflaster jitter,
  Bordsteinkanten, Schlaglöcher, Tramschienen - all visible coming in from the
  right, the Raver*in calls them out) kick it. Exposed pieces slide (the
  Discokugel and the Einkaufswagen roll) when the lean exceeds their friction
  angle; a lean beyond TOPPLE rips the Spanngurt. Any piece on the street = over.

Score = pieces stacked. Rotated sprites are cached per whole degree, the
backdrop/HUD/text are cached surfaces, so a frame stays cheap on a Pi 4.
dev/test_lastenrave.py (headless checks + bots), dev/play_lastenrave.py (window).
"""

import math
import random

import pygame

import kiezos as K
import party_games

# ------------------------------------------------------------ tuning
COL = 4  # heightmap column width (px)
HALF_SPAN = 320  # the heightmap covers pile-frame x in [-HALF_SPAN, HALF_SPAN)
NCOLS = 2 * HALF_SPAN // COL
NONE_H = -1e9  # column with nothing to stand on
FALL_G = 1500.0  # px/s^2 for falling pieces and the crane pendulum
CONTACT_TOL = 1.5  # px: columns this close to the landing height touch the piece
STAB_TOL = 5.0  # px a load's centre of mass may hang over its contact span
WALL_H, FLOOR_H = 40, 6  # cargo box walls / floor (pile frame, y up from the box bottom)
BOX_IN, BOX_OUT = 68, 76  # interior / outer half width of the box

HUD_H = 44
BEAM_Y = HUD_H + 10  # crane beam
HOOK_GAP = 10  # hook to the piece's top
ROAD_OFF = 64  # road top = height - ROAD_OFF
PIVOT_X = 262  # box bottom centre (screen x)
PIVOT_ABOVE_ROAD = 36
REAR_X, FRONT_X, WHEEL_R = 112, 384, 19
TOP_SCREEN_Y = 390  # the camera keeps the pile top at least this low on screen
DROP_H = 130  # a hanging piece's bottom this far above the pile top
MIN_ROPE = 90
ENTER_SPEED = 900.0  # px/s the trolley drives in with a new piece
TROLLEY_SPEED = 650.0
TROLLEY_ACC = 1100.0  # px/s^2: a smooth crane, the piece still swings along
PEND_DAMP = 0.16
SPAWN_DELAY = 0.45
AUTO_DROP = 8.0  # the crane lets go by itself after this long
TAP_MOVE = 14  # px a finger may move and still count as a tap (= drop)
AMP0, AMP_PER, MAX_AMP = 40.0, 4.0, 110.0  # swing amplitude (px) by score
PARK_SPREAD = 9.0  # px per point the trolley parks off-centre (up to MAX_PARK)
MAX_PARK = 80.0

# pile dynamics; lengths in units of 100 px, angles in rad
G_TORQUE = 10.0
K0, K_PER_ITEM = 150.0, 70.0  # Spanngurt stiffness: base + per stacked piece
I0 = 3.0  # inertia of box + bike share
DAMP_REL = 0.16  # damping as a fraction of critical
TOPPLE = math.radians(27)
SLIP_SPEED = 12.0  # px/s per degree over a piece's friction angle
IMPACT = 0.5  # landing kick
TIP_V = 140.0  # px/s a piece slides off the edge it hangs over
KICKS = {"loch": 0.42, "kante": 0.5, "tram": 0.3}  # base accel pulses of road features
COBBLE_A, COBBLE_EVERY = 0.07, 0.08
OBSTACLE_FROM = {"kopf": 0, "kante": 2, "loch": 4, "tram": 7}
WIND_FROM = 10
TIERS = [0, 4, 9, 15]  # score from which tier 0..3 pieces come
MAX_PARTICLES = 80

# ------------------------------------------------------------ colours
INK = K.INK
WHITE = (255, 255, 255)
PINK = (255, 120, 200)
HOT = (255, 70, 170)
GOLD = (255, 208, 72)
MINT = (130, 230, 170)
LILAC = (190, 150, 255)
ORANGE = (255, 150, 70)
RED = (220, 50, 60)
STEEL = (170, 170, 195)
WOOD, WOOD_D, WOOD_L = (176, 112, 58), (112, 66, 34), (214, 156, 92)
RAINBOW = [(230, 40, 50), (255, 140, 0), (255, 225, 0), (0, 160, 70), (40, 90, 230), (130, 40, 170)]

# ------------------------------------------------------------ the gear
# key -> label, logical size (drawn x2), mass, friction angle (deg), roll factor, tier, quip
KINDS = {
    "lautsprecher": ("LAUTSPRECHER", (20, 26), 3.0, 15, 1.0, 0, "Ohne Bass kein Protest."),
    "bierkiste": ("BIERKISTE", (28, 20), 4.0, 14, 1.0, 0, "Pfand ist Solidarität."),
    "powerbank": ("POWERBANK", (18, 8), 1.0, 16, 1.0, 0, "Strom für die Lichterkette."),
    "mischpult": ("MISCHPULT", (32, 10), 2.0, 14, 1.0, 0, "Die DJ*ane braucht Platz!"),
    "matekiste": ("MATEKISTE", (26, 20), 3.5, 14, 1.0, 0, "Koffein für die Afterhour."),
    "subwoofer": ("SUBWOOFER", (32, 30), 6.0, 16, 1.0, 1, "Schwer. Aber der Bass!"),
    "nebelmaschine": ("NEBELMASCHINE", (34, 14), 3.0, 13, 1.0, 1, "Schwerpunkt? Schief."),
    "pfeffi": ("XXL-PFEFFI", (12, 40), 2.0, 9, 1.0, 1, "Oben schmal. DREHEN?"),
    "discokugel": ("DISCOKUGEL", (26, 28), 2.0, 3, 3.0, 2, "Rollt. Natürlich rollt sie."),
    "dragonstaff": ("DRAGONSTAFF", (60, 10), 1.0, 10, 1.0, 2, "Lang, dünn, brennt."),
    "einhorn": ("GLITZER-EINHORN", (36, 30), 1.0, 8, 1.0, 2, "Wiegt nix, wackelt viel."),
    "bauzaun": ("BAUZAUN-DEKO", (56, 32), 3.0, 12, 1.0, 2, "Vom Straßenrand befreit."),
    "sofa": ("SPERRMÜLL-SOFA", (48, 22), 7.0, 16, 1.0, 3, "Zu verschenken: Chillout-Area."),
    "einkaufswagen": ("EINKAUFSWAGEN", (34, 30), 3.0, 4, 2.0, 3, "Hat Rollen. Leider."),
    "flamingo": ("GUMMI-FLAMINGO", (24, 44), 1.0, 6, 1.0, 3, "Pink, prall, kippelig."),
}

OBSTACLE_LINES = {
    "kopf": ["Kopfsteinpflaster...", "Rüttelpiste!", "Altbau-Kiez, ey."],
    "kante": ["Bordstein! Festhalten!", "Achtung, Kante!"],
    "loch": ["Schlagloch!", "Loch! Loch! LOCH!"],
    "tram": ["Tramschienen, ey!", "Vorsicht, Schienen!"],
}
START_LINES = ["Auf zur Rave-Demo!", "Bass einladen, los!", "Wir sind die Demo!"]
PERFECT_LINES = ["SAUBER!", "GAFFA HÄLT!", "PRÄZISE!", "SCHÖN MITTIG!"]
OVER_BUBBLES = ["Neeein!", "Rave abgesagt...", "Mein Bass!", "Das war's dann."]


def canvas(w, h):
    return pygame.Surface((w, h), pygame.SRCALPHA)


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def col_of(left):
    return int(round((left + HALF_SPAN) / COL))


def col_x(j):
    return j * COL - HALF_SPAN


# ------------------------------------------------------------ cached text
_TEXT = {}


def otext(text, size, color, thick=2):
    """Cached outlined KiezOS text (ink outline), reads on any background."""
    key = (text, size, color, thick)
    s = _TEXT.get(key)
    if s is None:
        if len(_TEXT) > 300:
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


def outlined(surf, text, size, color, pos, anchor="center", thick=2):
    s = otext(text, size, color, thick)
    r = s.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
    surf.blit(s, r)
    return r


# ------------------------------------------------------------ pixel art (logical px, scaled x2)
def _r(s, c, x, y, w, h):
    pygame.draw.rect(s, c, (x, y, w, h))


def _box(s, c, x, y, w, h):
    """Filled rect with an ink outline."""
    _r(s, INK, x, y, w, h)
    _r(s, c, x + 1, y + 1, w - 2, h - 2)


def _d_lautsprecher(s):
    _box(s, (44, 38, 58), 0, 0, 20, 26)
    _r(s, (62, 54, 80), 2, 2, 16, 22)
    pygame.draw.circle(s, INK, (10, 7), 4)
    pygame.draw.circle(s, (160, 150, 190), (10, 7), 3)
    pygame.draw.circle(s, INK, (10, 7), 1)
    pygame.draw.circle(s, INK, (10, 17), 7)
    pygame.draw.circle(s, (130, 120, 160), (10, 17), 6)
    pygame.draw.circle(s, (64, 56, 84), (10, 17), 4)
    pygame.draw.circle(s, (210, 200, 240), (10, 17), 1)
    s.set_at((16, 3), PINK)


def _crate(s, w, body, dark, neck, cap):
    for i in range(w // 4 - 1):
        x = 3 + i * 4
        _r(s, neck, x, 1, 2, 4)
        _r(s, cap, x, 0, 2, 1)
    _box(s, body, 0, 5, w, 15)
    _r(s, dark, 1, 16, w - 2, 3)
    _r(s, INK, w // 2 - 4, 8, 8, 3)
    for x in range(4, w - 3, 6):
        _r(s, shade(body, 1.15), x, 12, 3, 2)


def _d_bierkiste(s):
    _crate(s, 28, (196, 48, 58), (150, 30, 40), (110, 62, 22), (235, 205, 70))


def _d_matekiste(s):
    _crate(s, 26, (245, 175, 40), (200, 130, 20), (120, 70, 25), (255, 120, 40))


def _d_powerbank(s):
    _box(s, (60, 90, 170), 0, 0, 18, 8)
    for x in (3, 5, 7):
        _r(s, (120, 255, 150), x, 3, 1, 2)
    _r(s, (30, 30, 40), 14, 3, 2, 2)


def _d_mischpult(s):
    _box(s, (150, 150, 172), 0, 2, 32, 8)
    for x, c in ((3, HOT), (7, GOLD), (11, MINT), (24, HOT), (28, LILAC)):
        _r(s, INK, x, 0, 2, 2)
        s.set_at((x, 0), c)
    for x in (15, 18, 21):
        _r(s, INK, x, 4, 1, 5)
        _r(s, WHITE, x - 1, 5 + (x % 3), 3, 1)
    pygame.draw.circle(s, (60, 60, 80), (6, 6), 2)
    pygame.draw.circle(s, (60, 60, 80), (27, 6), 2)


def _d_subwoofer(s):
    _box(s, (34, 30, 44), 0, 0, 32, 30)
    _r(s, (52, 46, 66), 2, 2, 28, 26)
    pygame.draw.circle(s, INK, (16, 14), 11)
    pygame.draw.circle(s, (120, 110, 150), (16, 14), 10)
    pygame.draw.circle(s, (70, 62, 92), (16, 14), 8)
    pygame.draw.circle(s, (40, 36, 54), (16, 14), 5)
    pygame.draw.circle(s, (200, 190, 230), (15, 13), 1)
    _r(s, HOT, 2, 26, 28, 2)


def _d_nebelmaschine(s):
    _box(s, (110, 110, 132), 0, 0, 26, 14)
    _r(s, (150, 150, 172), 1, 1, 24, 2)
    for y in (5, 8, 11):
        _r(s, (70, 70, 90), 3, y, 12, 1)
    _r(s, RED, 19, 5, 3, 3)
    _box(s, (165, 165, 182), 25, 5, 9, 5)
    _r(s, WHITE, 32, 6, 1, 3)


def _d_pfeffi(s):
    green, light = (40, 165, 95), (120, 220, 150)
    pygame.draw.polygon(s, INK, [(3, 2), (8, 2), (8, 10), (11, 15), (11, 39), (0, 39), (0, 15), (3, 10)])
    pygame.draw.polygon(s, green, [(4, 3), (7, 3), (7, 11), (10, 15), (10, 38), (1, 38), (1, 15), (4, 11)])
    _r(s, (220, 40, 50), 4, 0, 4, 3)
    _r(s, INK, 3, 0, 1, 3)
    _r(s, INK, 8, 0, 1, 3)
    _r(s, WHITE, 1, 22, 10, 9)
    _r(s, green, 3, 24, 2, 2)
    _r(s, green, 6, 26, 3, 3)
    _r(s, light, 2, 16, 1, 5)


def _d_discokugel(s):
    _r(s, INK, 12, 0, 2, 4)
    cx, cy, r = 13, 15, 12
    pygame.draw.circle(s, INK, (cx, cy), r + 1)
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                tile = (x // 3 + y // 3) % 3
                c = [(150, 150, 180), (190, 190, 215), (230, 230, 250)][tile]
                if x % 3 == 0 or y % 3 == 0:
                    c = (110, 110, 140)
                s.set_at((x, y), c)
    for p, c in (((8, 10), WHITE), ((16, 18), PINK), ((10, 20), (140, 220, 255)), ((18, 9), WHITE)):
        s.set_at(p, c)


def _flame(s, x0):
    pygame.draw.polygon(s, ORANGE, [(x0, 7), (x0 + 1, 1), (x0 + 3, 4), (x0 + 5, 0), (x0 + 7, 4), (x0 + 8, 8), (x0 + 4, 9)])
    pygame.draw.polygon(s, GOLD, [(x0 + 2, 7), (x0 + 3, 4), (x0 + 5, 3), (x0 + 6, 7)])


def _d_dragonstaff(s):
    _r(s, INK, 6, 4, 48, 3)
    _r(s, (210, 210, 230), 7, 5, 46, 1)
    for x0 in (0, 52):
        _flame(s, x0)
        _r(s, INK, x0 + 2, 5, 5, 3)
        _r(s, (90, 60, 40), x0 + 3, 6, 3, 1)


def _d_einhorn(s):
    body, spot = (255, 242, 252), (255, 160, 215)
    for x in (8, 13, 22, 27):
        _box(s, body, x, 20, 4, 10)
    pygame.draw.ellipse(s, INK, (4, 9, 26, 15))
    pygame.draw.ellipse(s, body, (5, 10, 24, 13))
    pygame.draw.polygon(s, INK, [(22, 15), (26, 3), (34, 3), (34, 9), (30, 10), (29, 17)])
    pygame.draw.polygon(s, body, [(23, 14), (27, 4), (33, 4), (33, 8), (29, 9), (28, 15)])
    pygame.draw.polygon(s, GOLD, [(30, 4), (35, 0), (32, 5)])
    s.set_at((31, 5), INK)
    for i, c in enumerate(RAINBOW):
        _r(s, c, 24 - i // 2, 5 + i * 2, 2, 2)
        _r(s, c, 1, 11 + i, 4, 1)
    for p in ((10, 14), (16, 17), (20, 12)):
        _r(s, spot, p[0], p[1], 3, 2)


def _d_bauzaun(s):
    mesh = (185, 185, 200)
    for i in range(-30, 60, 5):
        pygame.draw.line(s, mesh, (2 + i, 25), (2 + i + 24, 1))
    clear = canvas(56, 32)
    clear.blit(s, (0, 0))
    s.fill((0, 0, 0, 0))
    s.blit(clear, (0, 0), (2, 0, 52, 26))
    pygame.draw.rect(s, INK, (2, 0, 52, 26), 2)
    pygame.draw.rect(s, (215, 215, 230), (3, 1, 50, 24), 1)
    _box(s, (255, 130, 195), 10, 8, 36, 9)
    for x in range(13, 44, 4):
        _r(s, WHITE, x, 11, 2, 3)
    for x0 in (0, 44):
        _box(s, (178, 168, 152), x0, 25, 12, 7)
        _r(s, (140, 130, 115), x0 + 1, 29, 10, 2)


def _d_sofa(s):
    cover, light, dark = (215, 115, 50), (245, 155, 75), (150, 70, 30)
    _r(s, INK, 3, 19, 3, 3)
    _r(s, INK, 42, 19, 3, 3)
    for x0 in (7, 18, 29):
        pygame.draw.ellipse(s, INK, (x0, 0, 13, 14))
        pygame.draw.ellipse(s, cover, (x0 + 1, 1, 11, 12))
        s.set_at((x0 + 4, 4), dark)
        s.set_at((x0 + 8, 7), dark)
    _box(s, cover, 0, 11, 48, 9)
    _box(s, light, 7, 11, 34, 5)
    for x0 in (0, 40):
        pygame.draw.rect(s, INK, (x0, 5, 8, 15), border_radius=3)
        pygame.draw.rect(s, light, (x0 + 1, 6, 6, 13), border_radius=2)
    for x in range(9, 40, 6):
        s.set_at((x, 17), dark)


def _d_einkaufswagen(s):
    wire = (200, 205, 220)
    pygame.draw.polygon(s, INK, [(5, 2), (33, 2), (29, 18), (9, 18)])
    pygame.draw.polygon(s, (120, 125, 150), [(6, 3), (32, 3), (28, 17), (10, 17)])
    for x in range(9, 32, 4):
        pygame.draw.line(s, wire, (x, 3), (x - 1 if x < 20 else x - 2, 17))
    for y in (7, 12):
        pygame.draw.line(s, wire, (6 + y // 4, y), (32 - y // 4, y))
    pygame.draw.line(s, INK, (0, 0), (6, 4), 2)
    _r(s, RED, 0, 0, 2, 2)
    pygame.draw.line(s, INK, (9, 21), (30, 21), 2)
    pygame.draw.line(s, INK, (11, 18), (8, 24), 2)
    pygame.draw.line(s, INK, (28, 18), (28, 24), 2)
    for x in (8, 28):
        pygame.draw.circle(s, INK, (x, 26), 3)
        s.set_at((x, 26), (150, 150, 170))


def _d_flamingo(s):
    pink, dark = (255, 120, 190), (220, 70, 150)
    pygame.draw.ellipse(s, INK, (1, 26, 22, 18))
    pygame.draw.ellipse(s, pink, (2, 27, 20, 16))
    pygame.draw.ellipse(s, dark, (5, 31, 11, 7))
    pygame.draw.lines(s, INK, False, [(16, 29), (17, 20), (11, 13), (11, 6)], 5)
    pygame.draw.lines(s, pink, False, [(16, 29), (17, 20), (11, 13), (11, 6)], 3)
    pygame.draw.circle(s, INK, (12, 5), 5)
    pygame.draw.circle(s, pink, (12, 5), 4)
    pygame.draw.polygon(s, INK, [(15, 4), (22, 7), (20, 9), (15, 7)])
    pygame.draw.polygon(s, WHITE, [(16, 5), (19, 6), (16, 6)])
    s.set_at((12, 4), INK)
    _r(s, WHITE, 6, 29, 3, 2)


DRAW = {
    "lautsprecher": _d_lautsprecher, "bierkiste": _d_bierkiste, "powerbank": _d_powerbank,
    "mischpult": _d_mischpult, "matekiste": _d_matekiste, "subwoofer": _d_subwoofer,
    "nebelmaschine": _d_nebelmaschine, "pfeffi": _d_pfeffi, "discokugel": _d_discokugel,
    "dragonstaff": _d_dragonstaff, "einhorn": _d_einhorn, "bauzaun": _d_bauzaun, "sofa": _d_sofa,
    "einkaufswagen": _d_einkaufswagen, "flamingo": _d_flamingo,
}


class Art:
    """A piece's sprite in one orientation plus its contact profile: per
    COL-wide column the height of its lowest (bottom) and highest (top) pixel
    above the bounding box bottom (None = empty column), and its centre of
    mass (com_x from the left, com_y from the bottom)."""

    def __init__(self, surf):
        self.surf = surf
        self.w, self.h = surf.get_size()
        m = pygame.mask.from_surface(surf)
        self.bottom, self.top = [], []
        for c in range((self.w + COL - 1) // COL):
            lo = hi = None
            for x in range(c * COL, min(self.w, (c + 1) * COL)):
                ys = [y for y in range(self.h) if m.get_at((x, y))]
                if ys:
                    b, t = self.h - 1 - ys[-1], self.h - ys[0]
                    lo = b if lo is None else min(lo, b)
                    hi = t if hi is None else max(hi, t)
            self.bottom.append(lo)
            self.top.append(hi)
        cx, cy = m.centroid()
        self.com_x = cx + 0.5
        self.com_y = self.h - cy - 0.5


_ART = {}
_ROT = {}


def art(key, orient=0):
    a = _ART.get((key, orient))
    if a is None:
        if orient == 0:
            lw, lh = KINDS[key][1]
            s = canvas(lw, lh)
            DRAW[key](s)
            s = pygame.transform.scale(s, (lw * 2, lh * 2))
        else:
            s = pygame.transform.rotate(art(key, 0).surf, -90 * orient)
        a = Art(s)
        _ART[(key, orient)] = a
    return a


def rotated(surf_key, surf, deg):
    """surf rotated clockwise by whole degrees, cached."""
    if deg == 0:
        return surf
    key = (surf_key, deg)
    r = _ROT.get(key)
    if r is None:
        if len(_ROT) > 1200:
            _ROT.clear()
        r = pygame.transform.rotate(surf, -deg)
        _ROT[key] = r
    return r


def fit_icon(key, box):
    """A piece's sprite scaled to fit a box x box square (cached)."""
    k = ("fit", key, box)
    r = _ROT.get(k)
    if r is None:
        a = art(key)
        f = min(box / a.w, box / a.h)
        r = pygame.transform.scale(a.surf, (max(1, int(a.w * f)), max(1, int(a.h * f))))
        _ROT[k] = r
    return r


# ------------------------------------------------------------ static sprites
_SPR = {}


def _cached(key, make):
    if key not in _SPR:
        _SPR[key] = make()
    return _SPR[key]


def box_surfaces():
    """Cargo box: (back, front) - the back (dark inside) is drawn behind the
    pieces, the slatted front over them, so pieces in the box peek through."""
    def make():
        w, h = 2 * BOX_OUT, WALL_H
        back = canvas(w, h)
        _r(back, INK, 0, 0, w, h)
        _r(back, (60, 34, 24), 2, 2, w - 4, h - 4)
        for x in range(10, w - 6, 14):
            _r(back, (74, 44, 30), x, 2, 2, h - 4)
        front = canvas(w, h)
        for y0, hh in ((0, 9), (17, 7), (31, 9)):
            _r(front, INK, 0, y0, w, hh)
            _r(front, WOOD, 1, y0 + 1, w - 2, hh - 2)
            _r(front, WOOD_L, 1, y0 + 1, w - 2, 1)
        for x0 in (0, w - 9):
            _r(front, INK, x0, 0, 9, h)
            _r(front, WOOD_D, x0 + 1, 1, 7, h - 2)
        for i, c in enumerate(RAINBOW):  # rainbow sticker on the middle slat
            _r(front, c, 100 + i * 5, 18, 5, 5)
        label = K.font(13).render("RAVE-DEMO", False, WHITE)
        front.blit(label, (16, 31 + (9 - label.get_height()) // 2 + 1))
        return back, front
    return _cached("box", make)


def sky_surface(w, h):
    def make():
        s = pygame.Surface((w, h))
        top, bottom = (24, 10, 48), (92, 40, 120)
        for y in range(h):
            t = y / h
            s.fill(tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)), (0, y, w, 1))
        rnd = random.Random(7)
        for _ in range(70):
            x, y = rnd.randrange(w), rnd.randrange(int(h * 0.75))
            c = rnd.choice([(230, 220, 255), (255, 200, 240), (180, 170, 230)])
            s.fill(c, (x, y, 2 if rnd.random() < 0.3 else 1, 2 if rnd.random() < 0.3 else 1))
        pygame.draw.circle(s, (255, 240, 200), (400, 120), 26)  # moon
        pygame.draw.circle(s, (24 + 10, 10 + 6, 48 + 10), (412, 112), 22)
        return s
    return _cached(("sky", w, h), make)


def skyline_surface():
    """Far layer: Plattenbau silhouettes + Fernsehturm, 960 wide (tiles)."""
    def make():
        w, h = 960, 240
        s = canvas(w, h)
        rnd = random.Random(3)
        far = (58, 30, 92)
        x = 0
        while x < w:
            bw, bh = rnd.randrange(50, 90), rnd.randrange(70, 170)
            _r(s, far, x, h - bh, bw - 4, bh)
            for wy in range(h - bh + 8, h - 6, 12):
                for wx in range(x + 5, x + bw - 10, 9):
                    if rnd.random() < 0.22:
                        _r(s, (255, 210, 120), wx, wy, 4, 5)
            x += bw
        tx = 610
        pygame.draw.line(s, far, (tx, h), (tx, 20), 8)
        pygame.draw.circle(s, far, (tx, 70), 20)
        pygame.draw.line(s, far, (tx, 20), (tx, 0), 3)
        s.fill((255, 60, 60), (tx - 1, 0, 3, 3))
        return s
    return _cached("skyline", make)


def houses_surface():
    """Near layer: Altbau fronts with a Späti, 960 wide (tiles)."""
    def make():
        w, h = 960, 200
        s = canvas(w, h)
        rnd = random.Random(11)
        x = 0
        i = 0
        while x < w:
            bw = rnd.randrange(110, 160)
            c = rnd.choice([(80, 50, 110), (96, 56, 120), (72, 44, 96), (104, 64, 112)])
            top = h - rnd.randrange(150, 196)
            _r(s, c, x, top, bw - 2, h - top)
            _r(s, shade(c, 0.8), x, top, bw - 2, 6)
            for wy in range(top + 18, h - 50, 34):
                for wx in range(x + 12, x + bw - 26, 30):
                    lit = rnd.random() < 0.35
                    _r(s, (255, 214, 130) if lit else (44, 28, 64), wx, wy, 14, 20)
                    _r(s, shade(c, 0.7), wx - 2, wy + 20, 18, 3)
            if i % 3 == 1:  # Späti
                _r(s, (40, 24, 56), x + 10, h - 46, bw - 22, 46)
                _r(s, (255, 230, 150), x + 16, h - 40, bw - 34, 22)
                sign = K.font(14).render("SPÄTI 24/7", False, (255, 90, 190))
                _r(s, INK, x + 10, h - 64, bw - 22, 18)
                s.blit(sign, (x + 10 + (bw - 22 - sign.get_width()) // 2, h - 64))
            else:
                _r(s, (44, 28, 64), x + bw // 2 - 12, h - 40, 24, 40)
            x += bw
            i += 1
        return s
    return _cached("houses", make)


def road_tiles():
    """(asphalt, cobbles) road strips of 160 x ROAD_OFF px."""
    def make():
        asphalt = pygame.Surface((160, ROAD_OFF))
        asphalt.fill((52, 46, 66))
        _r(asphalt, (90, 84, 104), 0, 0, 160, 5)
        _r(asphalt, (120, 114, 136), 0, 0, 160, 2)
        rnd = random.Random(5)
        for _ in range(40):
            asphalt.set_at((rnd.randrange(160), rnd.randrange(8, ROAD_OFF)), (66, 60, 82))
        _r(asphalt, (230, 225, 240), 20, 38, 50, 4)
        cobble = pygame.Surface((160, ROAD_OFF))
        cobble.fill((40, 34, 50))
        _r(cobble, (90, 84, 104), 0, 0, 160, 5)
        for row, y in enumerate(range(6, ROAD_OFF, 10)):
            for x in range(-10 + (row % 2) * 7, 160, 14):
                c = rnd.choice([(96, 88, 110), (108, 100, 122), (86, 78, 100)])
                pygame.draw.rect(cobble, c, (x + 1, y + 1, 12, 8), border_radius=3)
                cobble.set_at((x + 4, y + 2), (140, 132, 156))
        return asphalt, cobble
    return _cached("road", make)


def beam_surface(w):
    def make():
        s = pygame.Surface((w, 10))
        s.fill(GOLD)
        for x in range(-10, w, 18):
            pygame.draw.polygon(s, INK, [(x, 10), (x + 8, 10), (x + 18, 0), (x + 10, 0)])
        pygame.draw.rect(s, INK, (0, 0, w, 10), 1)
        return s
    return _cached(("beam", w), make)


def menu_icon_surface(size=32):
    """16px menu/title icon: a cargo bike with a speaker and a disco ball in
    the box. Pure drawing, no fonts, so kiezos.menu_icon can call it any time."""
    s = canvas(16, 16)
    for cx in (3, 12):  # wheels
        pygame.draw.circle(s, INK, (cx, 13), 2)
        s.set_at((cx, 13), (170, 170, 200))
    pygame.draw.line(s, INK, (3, 13), (6, 9))
    pygame.draw.line(s, INK, (6, 12), (12, 12))
    pygame.draw.rect(s, INK, (6, 7, 9, 5))  # box
    pygame.draw.rect(s, WOOD, (7, 8, 7, 3))
    pygame.draw.rect(s, INK, (7, 2, 4, 5))  # speaker
    pygame.draw.rect(s, (90, 80, 120), (8, 3, 2, 3))
    s.set_at((8, 4), PINK)
    pygame.draw.circle(s, INK, (13, 5), 2)  # disco ball
    s.set_at((13, 5), WHITE)
    s.set_at((12, 4), (190, 190, 215))
    pygame.draw.line(s, INK, (4, 6), (5, 9))  # rider
    s.set_at((4, 5), (255, 214, 90))
    s.set_at((3, 4), PINK)
    s.set_at((4, 4), PINK)
    s.set_at((1, 2), GOLD)  # music notes
    s.set_at((2, 1), GOLD)
    s.set_at((15, 1), MINT)
    return pygame.transform.scale(s, (size, size))


# ------------------------------------------------------------ pile pieces
BOX = "box"  # supporter sentinel for the cargo box


class Piece:
    """A stacked piece in the pile frame (origin = box bottom centre, y up):
    left edge and bottom in px."""

    def __init__(self, key, orient, left, bottom):
        self.key = key
        self.orient = orient
        self.a = art(key, orient)
        self.left = float(left)
        self.bottom = float(bottom)
        self.mass = KINDS[key][2]
        self.supports = {}  # supporter (Piece or BOX) -> (x0, x1) contact range on it
        self.span = (0.0, 0.0)
        self.in_box = False
        self.leaning = False  # rests against a taller neighbour: never tips by itself

    @property
    def cx(self):
        return self.left + self.a.com_x

    @property
    def cy(self):
        return self.bottom + self.a.com_y


class Flying:
    """A piece in the air (screen coords, bottom centre)."""

    def __init__(self, key, orient, x, y, vx, vy, fresh, ang=0.0):
        self.key, self.orient, self.a = key, orient, art(key, orient)
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.fresh = fresh  # a newly dropped piece (scores when it lands)
        self.ang = ang
        self.spin = 0.0
        self.age = 0.0


class Debris:
    def __init__(self, surf_key, surf, x, y, vx, vy, ang, spin):
        self.surf_key, self.surf = surf_key, surf
        self.x, self.y, self.vx, self.vy, self.ang, self.spin = x, y, vx, vy, ang, spin


# ------------------------------------------------------------ the game
class LastenraveGame(party_games._Game):
    NAME = "LASTENRAVE"
    ICON = "lastenrave"
    DESCRIPTION = "Rave-Gear aufs Lastenrad"
    READY_TEXT = "Tippen zum Losfahren"
    SCORE_LABEL = "Teile gestapelt"

    def reset(self, now):
        super().reset(now)
        self.t = 0.0
        self.road_top = self.height - ROAD_OFF
        self.pivot_y0 = self.road_top - PIVOT_ABOVE_ROAD
        self.rot_rect = pygame.Rect(self.width - 122, 4, 116, HUD_H - 8)
        self.pile = []
        self.flying = []
        self.tipping = []  # {p, side, fresh, age}: sliding off an edge
        self.debris = []
        self.parts = []
        self.texts = []  # [text, x, y, color, size, t_end, rise]
        self.theta = 0.0
        self.omega = 0.0
        self.cam = 0.0
        self.road_s = 0.0
        self.speed = 0.0
        self.bike_dy = 0.0
        self.bike_vy = 0.0
        self.wheel_dy = {"r": 0.0, "f": 0.0}
        self.obstacles = []
        self.next_obstacle_s = 700.0
        self.cobble_t = 0.0
        self.slip_boost_until = -1.0
        self.next_gust = None
        self.hang = None
        self.next_key = "lautsprecher"
        self.recent = []
        self.seen = set()
        self.spawn_at = None
        self.finger = None
        self.streak = 0
        self.max_streak = 0
        self.top_h = float(WALL_H)
        self.bubble = None  # (text, t_end)
        self.over_t = None
        self.over_reason = ""
        self.rot_flash = -1.0
        self._head = None
        self._hud = None
        self._hud_key = None
        self._ready = None
        box = [NONE_H] * NCOLS
        own = [None] * NCOLS
        for j in range(NCOLS):
            x = col_x(j) + COL / 2
            if -BOX_OUT <= x < BOX_OUT:
                box[j] = FLOOR_H if -BOX_IN <= x < BOX_IN else WALL_H
                own[j] = BOX
        self.box_hm, self.box_own = box, own
        self.hm, self.own = list(box), list(own)

    # ---- geometry --------------------------------------------------------
    def pivot(self):
        return PIVOT_X, self.pivot_y0 + self.cam + self.bike_dy

    def to_pile(self, sx, sy):
        px, py = self.pivot()
        dx, dy = sx - px, py - sy
        c, s = math.cos(self.theta), math.sin(self.theta)
        return dx * c - dy * s, dx * s + dy * c

    def to_screen(self, lx, ly):
        px, py = self.pivot()
        c, s = math.cos(self.theta), math.sin(self.theta)
        return px + lx * c + ly * s, py - (-lx * s + ly * c)

    def cam_target(self):
        return max(0.0, self.top_h - (self.pivot_y0 - TOP_SCREEN_Y))

    # ---- heightmap / balance ---------------------------------------------
    def rebuild_hm(self, skip=None):
        hm, own = list(self.box_hm), list(self.box_own)
        for p in self.pile:
            if p is not skip:
                self._stamp(p, hm, own)
        return hm, own

    @staticmethod
    def _stamp(p, hm, own):
        j0 = col_of(p.left)
        for c, top in enumerate(p.a.top):
            j = j0 + c
            if top is not None and 0 <= j < NCOLS and p.bottom + top > hm[j]:
                hm[j] = p.bottom + top
                own[j] = p

    @staticmethod
    def landing(a, left, hm):
        """Height the piece's bottom comes to rest at, or None (nothing below)."""
        j0 = col_of(left)
        best = None
        for c, b in enumerate(a.bottom):
            j = j0 + c
            if b is None or j < 0 or j >= NCOLS or hm[j] <= NONE_H:
                continue
            y = hm[j] - b
            if best is None or y > best:
                best = y
        return best

    @staticmethod
    def contacts(p, hm, own):
        """Supporters {Piece|BOX: (x0, x1)} and the overall contact span, or ({}, None)."""
        j0 = col_of(p.left)
        sup = {}
        lo = hi = None
        for c, b in enumerate(p.a.bottom):
            j = j0 + c
            if b is None or j < 0 or j >= NCOLS or hm[j] <= NONE_H:
                continue
            if hm[j] - b >= p.bottom - CONTACT_TOL:
                x0 = col_x(j)
                x1 = x0 + COL
                r = sup.get(own[j])
                sup[own[j]] = (x0, x1) if r is None else (min(r[0], x0), max(r[1], x1))
                lo = x0 if lo is None else min(lo, x0)
                hi = x1 if hi is None else max(hi, x1)
        return sup, (None if lo is None else (lo, hi))

    @staticmethod
    def is_in_box(p):
        return p.bottom < WALL_H - 1 and p.left >= -BOX_IN - 1 and p.left + p.a.w <= BOX_IN + 1

    @staticmethod
    def hangs_over(p):
        """Side (-1/1) the piece tips to on its own, or 0 if it stands."""
        if p.in_box or p.leaning:
            return 0
        if p.span is None:
            return 1 if p.cx > 0 else -1
        lo, hi = p.span
        if p.cx < lo - STAB_TOL:
            return -1
        if p.cx > hi + STAB_TOL:
            return 1
        return 0

    def find_overloaded(self):
        """Lowest piece whose load - itself plus a share of everything resting
        on it, applied where it rests - has its centre of mass outside its
        contact span: (piece, side) or None."""
        load = {id(p): [p.mass, p.mass * p.cx] for p in self.pile}
        bad = None
        for p in sorted(self.pile, key=lambda q: -q.bottom):
            m, mx = load[id(p)]
            com = mx / m
            if not p.in_box and not p.leaning and p.span is not None:
                lo, hi = p.span
                if com < lo - STAB_TOL or com > hi + STAB_TOL:
                    bad = (p, 1 if com > hi else -1)
            share = m / max(1, len(p.supports))
            for s, (x0, x1) in p.supports.items():
                if s is not BOX:
                    ls = load[id(s)]
                    ls[0] += share
                    ls[1] += share * min(max(com, x0), x1)
        return bad

    def above(self, p):
        """p and everything (transitively) resting on it."""
        group, todo = [p], [p]
        while todo:
            q = todo.pop()
            for r in self.pile:
                if q in r.supports and r not in group:
                    group.append(r)
                    todo.append(r)
        return group

    def exposed(self):
        loaded = set()
        for p in self.pile:
            for s in p.supports:
                if s is not BOX:
                    loaded.add(id(s))
        return [p for p in self.pile if id(p) not in loaded and not p.in_box]

    def put(self, key, orient, left):
        """Puts a piece straight onto the pile at pile-frame x = left (landing
        height from the heightmap). Used by landing and by the tests.
        Returns the Piece, or None if nothing is below it."""
        a = art(key, orient)
        left = col_x(col_of(left))
        land = self.landing(a, left, self.hm)
        if land is None:
            return None
        p = Piece(key, orient, left, land)
        p.supports, span = self.contacts(p, self.hm, self.own)
        p.span = span
        p.in_box = self.is_in_box(p)
        self.pile.append(p)
        self._stamp(p, self.hm, self.own)
        self.top_h = max(self.top_h, p.bottom + p.a.h)
        return p

    def remove(self, p):
        self.pile.remove(p)
        self.hm, self.own = self.rebuild_hm()
        for q in self.pile:  # pieces it supported lose that contact
            q.supports.pop(p, None)
        self.top_h = max([WALL_H] + [q.bottom + q.a.h for q in self.pile])

    # ---- pile dynamics ------------------------------------------------------
    def mass_moments(self):
        """(total mass, sum m*x, sum m*y, inertia) in 100 px units."""
        m = smx = smy = inertia = 0.0
        for p in self.pile:
            x, y = p.cx / 100.0, p.cy / 100.0
            m += p.mass
            smx += p.mass * x
            smy += p.mass * y
            inertia += p.mass * (x * x + y * y)
        return m, smx, smy, inertia + I0

    def stiffness(self):
        return K0 + K_PER_ITEM * len(self.pile)

    def kick(self, a):
        """Horizontal acceleration pulse of the bike base (bump, jolt, gust)."""
        _, _, smy, inertia = self.mass_moments()
        self.omega += a * (0.3 + smy) / inertia

    def _step_pile(self, dt):
        _, smx, smy, inertia = self.mass_moments()
        k = self.stiffness()
        keff = max(k - G_TORQUE * smy, k * 0.15)
        damp = DAMP_REL * 2.0 * math.sqrt(keff * inertia)
        subs = 4
        h = dt / subs
        for _ in range(subs):
            c, s = math.cos(self.theta), math.sin(self.theta)
            torque = G_TORQUE * (smx * c + smy * s) - k * self.theta - damp * self.omega
            self.omega += torque / inertia * h
            self.theta += self.omega * h

    # ---- input ---------------------------------------------------------------
    def tap(self, x, y):
        if x < 100 and y < 144:  # emergency-exit corner: nothing tappable here
            return None
        if self.show_close and self.close_rect.collidepoint((x, y)):
            return "close"
        if self.state == "play":
            if self.rot_rect.collidepoint((x, y)):
                self.rotate()
                return None
            if y < HUD_H:
                return None
            grab = (self.hang["target"] - x) if self.hang else 0.0
            self.finger = {"x0": x, "y0": y, "grab": grab, "moved": False}
            return None
        return super().tap(x, y)

    def drag(self, x, y):
        f = self.finger
        if self.state != "play" or f is None:
            return
        if not f["moved"] and abs(x - f["x0"]) + abs(y - f["y0"]) > TAP_MOVE:
            f["moved"] = True
        if f["moved"] and self.hang is not None:
            h = self.hang
            h["entering"] = False
            h["target"] = max(30.0, min(self.width - 30.0, x + f["grab"]))

    def release(self):
        f, self.finger = self.finger, None
        if self.state == "play" and f is not None and not f["moved"]:
            self.drop()

    def rotate(self):
        if self.hang is None:
            return
        h = self.hang
        h["orient"] = (h["orient"] + 1) % 4
        h["a"] = art(h["key"], h["orient"])
        self.rot_flash = self.t + 0.25

    def drop(self):
        h = self.hang
        if h is None:
            return
        ix, iy = self.hang_pos()
        vx = h["tv"] + h["L"] * math.cos(h["phi"]) * h["dphi"]
        vy = -h["L"] * math.sin(h["phi"]) * h["dphi"]
        self.flying.append(Flying(h["key"], h["orient"], ix, iy, vx, vy, fresh=True))
        self.hang = None

    # ---- flow ------------------------------------------------------------------
    def start(self):
        self.speed = self.target_speed()
        self.bubble = (random.choice(START_LINES), self.t + 2.2)
        self.spawn()

    def target_speed(self):
        return min(185.0, 85.0 + 5.0 * self.score)

    def unlocked(self):
        return [k for k, v in KINDS.items() if TIERS[v[5]] <= self.score]

    def pick_next(self):
        pool = self.unlocked()
        fresh = [k for k in pool if k not in self.seen and k != self.next_key]
        if fresh and random.random() < 0.6:
            return random.choice(fresh)
        newest = max(KINDS[k][5] for k in pool)
        choices = [k for k in pool if self.recent[-2:].count(k) < 2 and k != self.next_key] or pool
        weights = [3 if KINDS[k][5] == newest and newest > 0 else 1 for k in choices]
        return random.choices(choices, weights)[0]

    def spawn(self):
        key = self.next_key
        self.next_key = self.pick_next()
        self.recent = (self.recent + [key])[-4:]
        a = art(key, 0)
        top_screen = self.pivot_y0 + self.cam_target() - self.top_h
        bottom = top_screen - DROP_H
        L = max(MIN_ROPE, bottom - a.h - HOOK_GAP - BEAM_Y - 8)
        n = self.score
        amp = min(MAX_AMP, AMP0 + AMP_PER * n)
        park = PIVOT_X + random.uniform(-1, 1) * min(MAX_PARK, PARK_SPREAD * n)
        self.hang = {"key": key, "orient": 0, "a": a, "tx": self.width + 60.0, "target": park, "tv": 0.0,
                     "phi": amp / L * random.choice((-1, 1)), "dphi": 0.0, "L": L, "born": self.t, "entering": True}
        if key not in self.seen:
            self.seen.add(key)
            if len(self.seen) > 1:
                self.say(f"NEU: {KINDS[key][0]}!", GOLD, 24, y=BEAM_Y + 40, life=2.4, rise=0)
                self.say(KINDS[key][6], WHITE, 17, y=BEAM_Y + 70, life=2.4, rise=0)
        self.spawn_at = None

    def hang_pos(self):
        """Screen bottom centre of the hanging piece."""
        h = self.hang
        hook_y = BEAM_Y + 8 + h["L"] * math.cos(h["phi"])
        return h["tx"] + h["L"] * math.sin(h["phi"]), hook_y + HOOK_GAP + h["a"].h

    def predict(self):
        """Where the hanging piece would land if dropped now (momentum
        included, pile frozen, tilt ignored): screen (x, y, lands_on_pile)."""
        h = self.hang
        a = h["a"]
        ix, iy = self.hang_pos()
        vx = h["tv"] + h["L"] * math.cos(h["phi"]) * h["dphi"]
        vy = -h["L"] * math.sin(h["phi"]) * h["dphi"]
        py = self.pivot()[1]
        mx = ix
        for _ in range(3):  # fall time depends on the surface where it ends up
            surface = self.landing(a, mx - PIVOT_X - a.w / 2, self.hm)
            drop = max(0.0, py - (surface if surface is not None else -40.0) - iy)
            tf = (-vy + math.sqrt(vy * vy + 2 * FALL_G * drop)) / FALL_G
            mx = ix + vx * tf
        surface = self.landing(a, mx - PIVOT_X - a.w / 2, self.hm)
        return mx, int(py - (surface if surface is not None else -20)), surface is not None

    def say(self, text, color, size, x=None, y=None, life=1.0, rise=40.0):
        self.texts.append([text, self.width / 2 if x is None else x, y, color, size, self.t + life, rise])

    # ---- simulation ------------------------------------------------------------
    def step(self, dt):
        self.t += dt
        if self.state == "ready":
            self.speed = 80.0
            self._step_road(dt, hazards=False)
            return
        if self.state == "over":
            self.speed = max(0.0, self.speed - 160 * dt)
            self._step_road(dt, hazards=False)
            self._step_flying(dt)
            self._step_fx(dt)
            self.theta *= max(0.0, 1 - 4 * dt)
            return
        self.speed += (self.target_speed() - self.speed) * min(1.0, dt)
        self._step_road(dt, hazards=True)
        self._step_pile(dt)
        if abs(self.theta) > TOPPLE:
            self.topple()
            return
        self._step_slip(dt)
        self._step_tipping(dt)
        if self.state != "play":
            return
        self._step_hang(dt)
        self._step_flying(dt)
        if self.state != "play":
            return
        self._step_wind()
        if self.hang is None and not self.flying and not self.tipping:
            if self.spawn_at is None:
                self.spawn_at = self.t + SPAWN_DELAY
            elif self.t >= self.spawn_at:
                self.spawn()
        self.cam += (self.cam_target() - self.cam) * min(1.0, 3 * dt)
        self._step_fx(dt)

    def _step_road(self, dt, hazards):
        self.road_s += self.speed * dt
        self.bike_vy += (-140 * self.bike_dy - 12 * self.bike_vy) * dt
        self.bike_dy += self.bike_vy * dt
        for w in self.wheel_dy:
            self.wheel_dy[w] *= max(0.0, 1 - 10 * dt)
        if not hazards:
            return
        n = self.score
        while self.next_obstacle_s < self.road_s + self.width + 260:
            kinds = [k for k, s in OBSTACLE_FROM.items() if s <= n]
            kind = random.choice(kinds)
            o = {"x": self.next_obstacle_s, "kind": kind, "len": 0.0, "hit": set(), "told": False}
            if kind == "kopf":
                o["len"] = random.uniform(120, 220 + 14 * n)
            self.obstacles.append(o)
            if kind == "tram":
                self.obstacles.append({"x": o["x"] + 26, "kind": kind, "len": 0.0, "hit": set(), "told": True})
            gap = max(230.0, 720.0 - 28.0 * n)
            self.next_obstacle_s += o["len"] + gap + random.uniform(0, gap * 0.6)
        scale = 1.0 + 0.035 * n
        on_cobbles = False
        for o in self.obstacles:
            sx = o["x"] - self.road_s
            if not o["told"] and sx < self.width + 40:
                o["told"] = True
                if self.bubble is None or self.t > self.bubble[1] - 0.6:
                    self.bubble = (random.choice(OBSTACLE_LINES[o["kind"]]), self.t + 1.6)
            for wheel, wx in (("f", FRONT_X), ("r", REAR_X)):
                if o["kind"] == "kopf":
                    if sx <= wx <= sx + o["len"]:
                        on_cobbles = True
                elif wheel not in o["hit"] and sx <= wx:
                    o["hit"].add(wheel)
                    s = KICKS[o["kind"]] * scale
                    # front wheel up: the bike pitches back, the pile is thrown back; rear: forward
                    self.kick((-1 if wheel == "f" else 0.8) * s)
                    self.omega += 0.6 * s * self.theta  # a jolt makes any lean worse
                    self.bike_vy -= 120 * s
                    self.wheel_dy[wheel] = -8 * s if o["kind"] != "loch" else 7 * s
                    self.slip_boost_until = self.t + 0.25
        if on_cobbles and self.t >= self.cobble_t:
            self.cobble_t = self.t + COBBLE_EVERY
            self.kick(random.uniform(-1, 1) * COBBLE_A * scale)
            self.bike_dy = random.uniform(-2, 2)
            self.wheel_dy["f"] = random.uniform(-3, 0)
            self.wheel_dy["r"] = random.uniform(-3, 0)
        self.obstacles = [o for o in self.obstacles if o["x"] + o["len"] - self.road_s > -60]

    def _step_hang(self, dt):
        h = self.hang
        if h is None:
            return
        if self.t - h["born"] > AUTO_DROP:
            self.drop()
            return
        if h["entering"]:
            h["tx"] = max(h["target"], h["tx"] - ENTER_SPEED * dt)
            h["entering"] = h["tx"] > h["target"]
            acc = 0.0
            h["tv"] = 0.0
        else:
            # accel-limited trolley: brakes in time to stop at the target
            gap = h["target"] - h["tx"]
            want = math.copysign(min(TROLLEY_SPEED, math.sqrt(2 * TROLLEY_ACC * abs(gap)), abs(gap) * 12.0), gap)
            v = h["tv"] + max(-TROLLEY_ACC * dt, min(TROLLEY_ACC * dt, want - h["tv"]))
            acc = (v - h["tv"]) / max(dt, 1e-3)
            h["tv"] = v
            h["tx"] += v * dt
        subs = 3
        sd = dt / subs
        for _ in range(subs):
            h["dphi"] += (-(FALL_G / h["L"]) * math.sin(h["phi"]) - acc / h["L"] * math.cos(h["phi"]) - PEND_DAMP * h["dphi"]) * sd
            h["phi"] += h["dphi"] * sd

    def _step_wind(self):
        if self.score < WIND_FROM:
            return
        if self.next_gust is None:
            self.next_gust = self.t + random.uniform(4, 8)
        elif self.t >= self.next_gust:
            self.next_gust = self.t + random.uniform(5, 9)
            d = random.choice((-1, 1))
            if self.hang is not None:
                self.hang["dphi"] += d * 0.5
            self.kick(d * 0.12)
            self.say("WINDBÖE!" if d > 0 else "<- WINDBÖE", LILAC, 22, y=BEAM_Y + 110, life=1.2, rise=0)

    def _step_flying(self, dt):
        for f in list(self.flying):
            f.age += dt
            f.vy += FALL_G * dt
            old_x = f.x
            f.x += f.vx * dt
            f.y += f.vy * dt
            f.ang += f.spin * dt
            if self.state != "play":
                if f.y > self.height + 200:
                    self.flying.remove(f)
                continue
            lx, ly = self.to_pile(f.x, f.y)
            left = lx - f.a.w / 2
            land = self.landing(f.a, left, self.hm)
            if land is not None and f.vx and land > ly + f.vy * dt + 2:
                # drifted sideways into something taller: bump off it instead of jumping on top
                f.x = old_x
                f.vx *= -0.25
                lx, ly = self.to_pile(f.x, f.y)
                left = lx - f.a.w / 2
                land = self.landing(f.a, left, self.hm)
            if land is not None and ly <= land and f.vy > 0:
                self.flying.remove(f)
                self._land(f, left)
                if self.state != "play":
                    return
            elif ly < -30:
                self.flying.remove(f)
                self.flying.append(f)  # keeps falling as part of the over animation
                self.game_over(f"{KINDS[f.key][0]} liegt auf der Straße!")
                return

    def _land(self, f, left):
        p = self.put(f.key, f.orient, left)
        if p is None:  # snapping to the column grid moved it off the edge
            self.flying.append(f)
            return
        side = self.hangs_over(p)
        if side:
            # hangs over its support: slides/tips off that edge, may still land lower
            self.remove(p)
            self.tipping.append({"p": p, "side": side, "fresh": f.fresh, "age": 0.0})
            self.say("KIPPT!", ORANGE, 22, *self.to_screen(p.cx, p.bottom + p.a.h + 16), life=0.8)
            return
        self._settled(p, f.fresh, f.vy)

    def _settled(self, p, fresh, vy):
        """A piece came to rest in the pile: collapse check, landing kick, score."""
        bad = self.find_overloaded()
        if bad is not None:
            self.collapse(*bad)
            return
        _, _, _, inertia = self.mass_moments()
        self.omega += IMPACT * p.mass * (p.cx / 100.0) * min(1.5, max(0.3, vy / 600.0)) / inertia
        self._dust(p)
        if not fresh:
            return
        self.score += 1
        sups = [s for s in p.supports]
        target = sum(0.0 if s is BOX else s.left + s.a.w / 2 for s in sups) / max(1, len(sups))
        if abs(p.cx - target) <= 6:
            self.streak += 1
            self.max_streak = max(self.max_streak, self.streak)
            self.omega *= 0.5
            text = random.choice(PERFECT_LINES) + (f" x{self.streak}" if self.streak > 1 else "")
            self.say(text, MINT, 26, *self.to_screen(p.cx, p.bottom + p.a.h + 34), life=0.9)
        else:
            self.streak = 0
            self.say("+1", GOLD, 26, *self.to_screen(p.cx, p.bottom + p.a.h + 24), life=0.7)
        if self.score in TIERS[1:]:
            self.say("NEUES ZEUG!", PINK, 22, y=BEAM_Y + 140, life=1.5, rise=0)

    def _step_slip(self, dt):
        lean = math.degrees(self.theta)
        boost = 0.6 if self.t < self.slip_boost_until else 1.0
        for p in self.exposed():
            slip, roll = KINDS[p.key][3], KINDS[p.key][4]
            over = abs(lean) - slip * boost
            if over <= 0:
                continue
            dx = math.copysign(SLIP_SPEED * over * roll * dt, lean)
            if self._slide(p, dx) and self.state != "play":
                return

    def _slide(self, p, dx):
        """Moves an exposed piece sideways. Returns True if it fell off its support."""
        hm, own = self.rebuild_hm(skip=p)
        new_left = p.left + dx
        j0 = col_of(new_left)
        for c, b in enumerate(p.a.bottom):
            j = j0 + c
            if b is not None and 0 <= j < NCOLS and hm[j] - b > p.bottom + 1:
                return False  # bumps into something taller
        old = p.left
        p.left = new_left
        sup, span = self.contacts(p, hm, own)
        if span is None or not (span[0] - STAB_TOL <= p.cx <= span[1] + STAB_TOL):
            self.remove(p)
            self.tipping.append({"p": p, "side": 1 if dx > 0 else -1, "fresh": False, "age": 0.0})
            self.say("RUTSCHT!", ORANGE, 22, *self.to_screen(p.cx, p.bottom + p.a.h + 16), life=0.8)
            return True
        p.supports, p.span = sup, span
        self.hm, self.own = self.rebuild_hm()
        return False

    def _readd(self, p, leaning=False):
        p.supports, p.span = self.contacts(p, self.hm, self.own)
        p.in_box = self.is_in_box(p)
        p.leaning = leaning
        self.pile.append(p)
        self._stamp(p, self.hm, self.own)
        self.top_h = max(self.top_h, p.bottom + p.a.h)

    def _step_tipping(self, dt):
        """Pieces hanging over an edge slide off it at their height; once
        nothing is under them they fall (and may land lower). Resting again on
        something, or leaning against a taller neighbour, puts them back."""
        for tp in list(self.tipping):
            p, side = tp["p"], tp["side"]
            tp["age"] += dt
            new_left = p.left + side * TIP_V * dt
            j0 = col_of(new_left)
            if any(b is not None and 0 <= j0 + c < NCOLS and self.hm[j0 + c] - b > p.bottom + 1
                   for c, b in enumerate(p.a.bottom)):
                self.tipping.remove(tp)
                self._readd(p, leaning=True)
                self._settled(p, tp["fresh"], 0.0)
            else:
                p.left = new_left
                _, span = self.contacts(p, self.hm, self.own)
                if span is None:
                    self.tipping.remove(tp)
                    x, y = self.to_screen(p.left + p.a.w / 2, p.bottom)
                    f = Flying(p.key, p.orient, x, y, side * TIP_V, 0.0, tp["fresh"],
                               ang=math.degrees(self.theta) + self.tip_angle(tp))
                    f.spin = side * 220.0
                    self.flying.append(f)
                elif span[0] - STAB_TOL <= p.cx <= span[1] + STAB_TOL:
                    self.tipping.remove(tp)
                    self._readd(p)
                    self._settled(p, tp["fresh"], 0.0)
            if self.state != "play":
                return

    @staticmethod
    def tip_angle(tp):
        return tp["side"] * min(28.0, tp["age"] * 140.0)

    def _to_debris(self, p, vx, vy, spin):
        x, y = self.to_screen(p.left + p.a.w / 2, p.bottom + p.a.h / 2)
        self.debris.append(Debris((p.key, p.orient), p.a.surf, x, y, vx, vy, math.degrees(self.theta), spin))

    def collapse(self, p, side):
        for q in self.above(p):
            self._to_debris(q, side * random.uniform(60, 200), -random.uniform(60, 260), side * random.uniform(90, 300))
            self.pile.remove(q)
        self.hm, self.own = self.rebuild_hm()
        self.game_over(f"Eingestürzt! Zu viel auf {KINDS[p.key][0]}.")

    def topple(self):
        side = 1 if self.theta > 0 else -1
        for q in list(self.pile):
            self._to_debris(q, side * random.uniform(120, 260) + self.omega * q.cy * 0.8, -random.uniform(0, 200),
                            side * random.uniform(60, 240))
        self.pile = []
        self.hm, self.own = list(self.box_hm), list(self.box_own)
        self.game_over("Spanngurt gerissen! Alles auf der Straße.")

    def game_over(self, text):
        self.over_t = self.t
        self.over_reason = text
        self.hang = None
        self.finger = None
        for f in self.flying:  # whatever's in the air keeps falling
            f.spin = f.spin or random.choice((-1, 1)) * 200.0
        for tp in self.tipping:
            self._to_debris(tp["p"], tp["side"] * TIP_V, 0.0, tp["side"] * 200.0)
        self.tipping = []
        self.bubble = (random.choice(OVER_BUBBLES), self.t + 2.5)
        super().game_over(text)

    def _dust(self, p):
        x, y = self.to_screen(p.cx, p.bottom)
        for _ in range(8):
            if len(self.parts) < MAX_PARTICLES:
                self.parts.append([x + random.uniform(-p.a.w / 2, p.a.w / 2), y, random.uniform(-80, 80),
                                   random.uniform(-120, -20), 0.45, random.choice([WHITE, PINK, GOLD])])

    def _step_fx(self, dt):
        for d in self.debris:
            d.vy += FALL_G * dt
            d.x += d.vx * dt
            d.y += d.vy * dt
            d.ang += d.spin * dt
        self.debris = [d for d in self.debris if d.y < self.height + 150]
        for pa in self.parts:
            pa[0] += pa[2] * dt
            pa[1] += pa[3] * dt
            pa[3] += 500 * dt
            pa[4] -= dt
        self.parts = [pa for pa in self.parts if pa[4] > 0]
        for tx in self.texts:
            tx[2] = (tx[2] if tx[2] is not None else BEAM_Y + 60) - tx[6] * dt
        self.texts = [tx for tx in self.texts if tx[5] > self.t]

    # ---- drawing ---------------------------------------------------------------
    def draw(self, surf):
        self._draw_scene(surf)
        self._draw_hud(surf)
        if self.state == "ready":
            self._draw_ready(surf)
        elif self.state == "over":
            if self.t - self.over_t < 1.4:
                K.wordart(surf, "RAVE VORBEI!", 42, (self.width // 2, 250), wave=7)
            else:
                self._draw_over(surf)

    def _draw_scene(self, surf):
        w = self.width
        surf.blit(sky_surface(w, self.height), (0, 0))
        far, near = skyline_surface(), houses_surface()
        fy = self.road_top - far.get_height() - 70 + int(self.cam * 0.35)
        ny = self.road_top - near.get_height() + int(self.cam)
        for img, y, k in ((far, fy, 0.15), (near, ny, 0.5)):
            if y < self.height:
                off = -int(self.road_s * k) % img.get_width()
                surf.blit(img, (off - img.get_width(), y))
                surf.blit(img, (off, y))
        self._draw_road(surf)
        self._draw_bike(surf)
        self._draw_pile(surf)
        for f in self.flying:
            img = rotated((f.key, f.orient), f.a.surf, int(round(f.ang)) % 360)
            surf.blit(img, img.get_rect(center=(int(f.x), int(f.y - f.a.h / 2))))
        for d in self.debris:
            img = rotated(d.surf_key, d.surf, (int(d.ang) // 6 * 6) % 360)
            surf.blit(img, img.get_rect(center=(int(d.x), int(d.y))))
        for pa in self.parts:
            surf.fill(pa[5], (int(pa[0]), int(pa[1]), 4, 4))
        self._draw_crane(surf)
        for text, x, y, color, size, _, _ in self.texts:
            outlined(surf, text, size, color, (x, y if y is not None else BEAM_Y + 60))
        self._draw_bubble(surf)

    def _draw_road(self, surf):
        y = self.road_top + int(self.cam)
        if y >= self.height:
            return
        asphalt, cobble = road_tiles()
        off = -int(self.road_s) % 160
        for x in range(off - 160, self.width, 160):
            surf.blit(asphalt, (x, y))
        for o in self.obstacles:
            sx = int(o["x"] - self.road_s)
            if sx > self.width or sx + o["len"] < -40:
                continue
            kind = o["kind"]
            if kind == "kopf":
                clip = surf.get_clip()
                surf.set_clip(pygame.Rect(sx, y, int(o["len"]), ROAD_OFF).clip(clip))
                for x in range(sx - (sx % 160) - 160, sx + int(o["len"]) + 160, 160):
                    surf.blit(cobble, (x, y))
                surf.set_clip(clip)
            elif kind == "loch":
                pygame.draw.ellipse(surf, INK, (sx - 4, y - 2, 34, 12))
                pygame.draw.ellipse(surf, (20, 10, 30), (sx - 2, y, 30, 8))
            elif kind == "kante":
                pygame.draw.rect(surf, INK, (sx, y - 9, 16, 11))
                pygame.draw.rect(surf, (170, 165, 185), (sx + 1, y - 8, 14, 9))
            elif kind == "tram":
                pygame.draw.rect(surf, INK, (sx, y - 4, 12, 6))
                pygame.draw.rect(surf, (200, 200, 220), (sx + 1, y - 4, 10, 2))
        # warning triangles for hazards just off-screen right
        for o in self.obstacles:
            sx = o["x"] - self.road_s
            if self.width < sx < self.width + 250:
                if int(self.t * 4) % 2 == 0:
                    tx = self.width - 26
                    ty = min(y - 30, self.height - 40)
                    pygame.draw.polygon(surf, INK, [(tx, ty - 16), (tx + 18, ty + 14), (tx - 18, ty + 14)])
                    pygame.draw.polygon(surf, GOLD, [(tx, ty - 11), (tx + 13, ty + 11), (tx - 13, ty + 11)])
                    surf.fill(INK, (tx - 1, ty - 4, 3, 8))
                    surf.fill(INK, (tx - 1, ty + 6, 3, 3))
                break

    def _draw_bike(self, surf):
        base = self.road_top + int(self.cam)
        if base - 150 > self.height:
            return
        by = int(self.bike_dy)
        rw = (REAR_X, base - WHEEL_R + int(self.wheel_dy["r"]))
        fw = (FRONT_X, base - WHEEL_R + int(self.wheel_dy["f"]))
        frame = (90, 230, 200)
        y0 = base - PIVOT_ABOVE_ROAD + by  # box bottom
        # frame: rear hub -> under the box -> front hub, seat post, handlebar
        pygame.draw.lines(surf, INK, False, [rw, (196, y0 + 6), (PIVOT_X + BOX_OUT, y0 + 6), fw], 7)
        pygame.draw.lines(surf, frame, False, [rw, (196, y0 + 6), (PIVOT_X + BOX_OUT, y0 + 6), fw], 3)
        seat = (150, y0 - 42)
        crank = (156, base - 22 + by)
        for a, b in ((rw, seat), (crank, seat), (crank, rw), ((180, y0 + 4), (178, y0 - 44))):
            pygame.draw.line(surf, INK, a, b, 6)
            pygame.draw.line(surf, frame, a, b, 2)
        pygame.draw.line(surf, INK, (170, y0 - 46), (186, y0 - 46), 6)
        pygame.draw.rect(surf, INK, (seat[0] - 12, seat[1] - 5, 24, 7), border_radius=3)
        for c in (rw, fw):
            pygame.draw.circle(surf, INK, c, WHEEL_R)
            pygame.draw.circle(surf, (140, 130, 170), c, WHEEL_R - 5)
            pygame.draw.circle(surf, (40, 26, 60), c, WHEEL_R - 7)
            a0 = self.road_s / WHEEL_R
            for i in range(3):
                a = a0 + i * math.pi / 3
                dx, dy = math.cos(a) * (WHEEL_R - 7), math.sin(a) * (WHEEL_R - 7)
                pygame.draw.line(surf, (170, 160, 200), (c[0] - dx, c[1] - dy), (c[0] + dx, c[1] + dy), 1)
            pygame.draw.circle(surf, (200, 200, 220), c, 3)
        # rider: legs pedalling, glitter top, pink bucket hat, shades
        hip = (seat[0] + 2, seat[1] - 6)
        pa = self.road_s / 22.0
        for k, col in ((math.pi, (30, 22, 44)), (0.0, (50, 36, 70))):
            foot = (crank[0] + math.cos(pa + k) * 12, crank[1] + math.sin(pa + k) * 12)
            mid = ((hip[0] + foot[0]) / 2 + 13, (hip[1] + foot[1]) / 2 - 6)
            pygame.draw.lines(surf, col, False, [hip, mid, foot], 7)
            pygame.draw.rect(surf, INK, (foot[0] - 5, foot[1] - 2, 11, 5))
        shoulder = (hip[0] + 12, hip[1] - 38)
        pygame.draw.line(surf, INK, hip, shoulder, 15)
        pygame.draw.line(surf, LILAC, hip, shoulder, 11)
        for gx, gy in ((4, -10), (8, -22), (2, -28), (10, -32)):
            surf.fill(WHITE, (hip[0] + gx, hip[1] + gy, 2, 2))
        pygame.draw.lines(surf, INK, False, [shoulder, (shoulder[0] + 12, shoulder[1] + 16), (182, y0 - 47)], 6)
        pygame.draw.lines(surf, (255, 205, 160), False, [shoulder, (shoulder[0] + 12, shoulder[1] + 16), (182, y0 - 47)], 2)
        head = (shoulder[0] + 4, shoulder[1] - 14)
        pygame.draw.circle(surf, INK, head, 11)
        pygame.draw.circle(surf, (255, 205, 160), head, 9)
        pygame.draw.rect(surf, INK, (head[0] - 2, head[1] - 3, 13, 5))  # shades
        pygame.draw.rect(surf, INK, (head[0] - 15, head[1] - 9, 30, 5))  # bucket hat brim
        pygame.draw.rect(surf, PINK, (head[0] - 14, head[1] - 8, 28, 3))
        pygame.draw.rect(surf, INK, (head[0] - 9, head[1] - 18, 18, 11))
        pygame.draw.rect(surf, PINK, (head[0] - 8, head[1] - 17, 16, 9))
        surf.fill(MINT, (head[0] - 6, head[1] - 14, 3, 3))
        self._head = head

    def _draw_pile(self, surf):
        deg = int(round(math.degrees(self.theta)))
        back, front = box_surfaces()
        bc = self.to_screen(0, WALL_H / 2)
        img = rotated("box-back", back, deg)
        surf.blit(img, img.get_rect(center=(int(bc[0]), int(bc[1]))))
        for p in self.pile:
            c = self.to_screen(p.left + p.a.w / 2, p.bottom + p.a.h / 2)
            img = rotated((p.key, p.orient), p.a.surf, deg)
            surf.blit(img, img.get_rect(center=(int(c[0]), int(c[1]))))
        for tp in self.tipping:
            p = tp["p"]
            c = self.to_screen(p.left + p.a.w / 2, p.bottom + p.a.h / 2 + abs(self.tip_angle(tp)) * 0.3)
            img = rotated((p.key, p.orient), p.a.surf, int(deg + self.tip_angle(tp)) % 360)
            surf.blit(img, img.get_rect(center=(int(c[0]), int(c[1]))))
        img = rotated("box-front", front, deg)
        surf.blit(img, img.get_rect(center=(int(bc[0]), int(bc[1]))))
        # music notes from the speakers
        if self.state == "play" and any(p.key in ("lautsprecher", "subwoofer") for p in self.pile):
            for i in range(3):
                ph = (self.t * 0.7 + i / 3) % 1.0
                nx = PIVOT_X - 60 + i * 60 + math.sin(self.t * 3 + i) * 10
                ny = self.pivot()[1] - self.top_h - 10 - ph * 70
                col = [GOLD, PINK, MINT][i]
                surf.fill(INK, (int(nx) - 1, int(ny) - 1, 8, 7))
                surf.fill(col, (int(nx), int(ny), 6, 5))
                surf.fill(col, (int(nx) + 4, int(ny) - 12, 2, 12))
                surf.fill(col, (int(nx) + 4, int(ny) - 12, 6, 2))

    def _draw_crane(self, surf):
        surf.blit(beam_surface(self.width), (0, BEAM_Y - 10))
        h = self.hang
        if h is None:
            return
        tx = int(h["tx"])
        pygame.draw.rect(surf, INK, (tx - 16, BEAM_Y - 2, 32, 12))
        pygame.draw.rect(surf, (150, 150, 175), (tx - 15, BEAM_Y - 1, 30, 10))
        ix, iy = self.hang_pos()
        a = h["a"]
        hook = (int(ix), int(iy - a.h - HOOK_GAP))
        pygame.draw.line(surf, INK, (tx, BEAM_Y + 9), hook, 4)
        pygame.draw.line(surf, STEEL, (tx, BEAM_Y + 9), hook, 2)
        pygame.draw.circle(surf, STEEL, hook, 4, 2)
        top = int(iy - a.h)
        pygame.draw.line(surf, STEEL, hook, (int(ix - a.w / 2 + 4), top), 1)
        pygame.draw.line(surf, STEEL, hook, (int(ix + a.w / 2 - 4), top), 1)
        surf.blit(a.surf, (int(ix - a.w / 2), top))
        mx, my, hits = self.predict()
        color = MINT if hits else RED
        for k in range(1, 9):
            t = k / 9
            px, py = ix + (mx - ix) * t, iy + (my - iy) * t
            surf.fill(color, (int(px) - 1, int(py) - 1, 3, 3))
        pygame.draw.polygon(surf, INK, [(mx - 9, my - 12), (mx + 9, my - 12), (mx, my - 1)])
        pygame.draw.polygon(surf, color, [(mx - 6, my - 10), (mx + 6, my - 10), (mx, my - 3)])
        outlined(surf, KINDS[h["key"]][0], 16, WHITE, (ix, top - 26))
        left = AUTO_DROP - (self.t - h["born"])
        if left < 3:
            outlined(surf, str(int(left) + 1), 30, RED, (ix, iy - a.h / 2))

    def _draw_bubble(self, surf):
        if self.bubble is None or self.t > self.bubble[1]:
            return
        head = self._head
        text = self.bubble[0]
        tw = K.font(16).size(text)[0]
        if head is None or head[1] > self.height - 10:
            rect = pygame.Rect(0, 0, tw + 22, 34)
            rect.midbottom = (self.width // 2, self.height - 8)
            K.tooltip(surf, rect)
            K.t95(surf, text, 16, rect.center, anchor="center")
            return
        rect = pygame.Rect(0, 0, tw + 22, 34)
        rect.bottomleft = (max(6, head[0] - 70), head[1] - 34)
        rect.right = min(rect.right, self.width - 6)
        if rect.top < HUD_H + 70:
            rect.top = HUD_H + 70
        K.speech(surf, rect, [text], (head[0] + 2, head[1] - 14), size=16)

    def _draw_hud(self, surf):
        key = (self.score, int(self.top_h / 10), self.next_key, self.state == "play", self.t < self.rot_flash)
        if key != self._hud_key:
            self._hud_key = key
            if self._hud is None:
                self._hud = pygame.Surface((self.width, HUD_H))
            h = self._hud
            K.bevel(h, pygame.Rect(0, 0, self.width, HUD_H))
            r = K.t95(h, str(self.score), 26, (12, HUD_H // 2), anchor="midleft")
            K.t95(h, "Teile", 15, (r.right + 6, HUD_H // 2 - 8), color=K.F_DARK, bold=False, anchor="midleft")
            meters = f"{max(0.0, self.top_h - WALL_H) / 100:.1f} m".replace(".", ",")
            K.t95(h, meters, 15, (r.right + 6, HUD_H // 2 + 9), color=K.F_ACCENT, anchor="midleft")
            K.t95(h, "Nächstes:", 15, (146, HUD_H // 2), color=K.F_DARK, bold=False, anchor="midleft")
            well = pygame.Rect(244, 4, 90, HUD_H - 8)
            K.bevel(h, well, sunken=True, face=(40, 20, 64))
            icon = fit_icon(self.next_key, HUD_H - 14)
            h.blit(icon, icon.get_rect(center=well.center))
            K.button(h, self.rot_rect, "DREHEN", size=17, pressed=self.t < self.rot_flash,
                     enabled=self.state == "play")
        surf.blit(self._hud, (0, 0))

    def _draw_ready(self, surf):
        if self._ready is None:
            self._ready = self._render_ready()
        img, pos = self._ready
        surf.blit(img, pos)
        if int(self.last_tick * 2) % 2 == 0:
            outlined(surf, self.READY_TEXT, 24, GOLD, (self.width // 2, pos[1] + img.get_height() + 22))

    def _render_ready(self):
        w = self.width
        top = HUD_H + 22
        win = pygame.Rect(0, 0, w - 28, 508)
        s = pygame.Surface((win.w + 6, win.h + 6), pygame.SRCALPHA)
        inner = K.dialog(s, win, "lastenrave.exe - anleitung.txt", icon=self.ICON, buttons=None)
        K.wordart(s, "LASTENRAVE", 40, (inner.centerx, inner.y + 30), wave=5)
        K.t95(s, "SIMULATOR", 18, (inner.centerx, inner.y + 66), color=K.F_ACCENT, anchor="center")
        y = inner.y + 88
        for line in ["Belad das Lastenrad für die", "Rave-Demo, Raver*in!"]:
            K.t95(s, line, 16, (inner.centerx, y), anchor="midtop")
            y += 22
        box = pygame.Rect(inner.x + 4, y + 16, inner.w - 8, 100)
        K.groupbox(s, box, "So geht's:")
        for i, (a, b) in enumerate([("Tippen", "Teil fallen lassen"), ("Ziehen", "Kran fahren"),
                                    ("DREHEN", "Teil um 90° drehen")]):
            K.t95(s, a, 16, (box.x + 12, box.y + 16 + i * 26))
            K.t95(s, b, 16, (box.x + 110, box.y + 16 + i * 26), bold=False)
        box = pygame.Rect(inner.x + 4, box.bottom + 22, inner.w - 8, 112)
        K.groupbox(s, box, "Physik, leider echt:")
        for i, line in enumerate(["Mittig stapeln, schwer nach unten.", "Was übersteht, kippt runter.",
                                  "Schlaglöcher lassen alles wackeln.", "Teil auf der Straße = Rave vorbei."]):
            K.t95(s, line, 15, (box.x + 12, box.y + 16 + i * 23), bold=False)
        row = ["lautsprecher", "bierkiste", "subwoofer", "pfeffi", "discokugel", "einhorn", "sofa"]
        cw = (inner.w - 8) // len(row)
        for i, k in enumerate(row):
            icon = fit_icon(k, 46)
            s.blit(icon, icon.get_rect(midbottom=(inner.x + 4 + cw * i + cw // 2, box.bottom + 60)))
        K.t95(s, party_games.record_line(type(self)), 15, (inner.centerx, inner.bottom - 4), color=K.F_DARK,
              bold=False, anchor="midbottom")
        return s, (14, top)
