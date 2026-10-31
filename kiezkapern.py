# -*- coding: utf-8 -*-
"""
KIEZ KAPERN (kiezkapern.exe): top-down open-city party game for the KiezOS 161
"Spiele" menu, a party_games._Game like ENTEIGNEN! / KIEZBLOCK.

A 3-minute "Schicht" on a Lastenrad in a fictional, procedural Kiez (64x64
tiles, no real map). Tap a point on the map: it snaps to the nearest road and
the bike pathfinds there (BFS on the tile grid). One context button (AKTION:
KAPERN!, LOCKERN, KIPPEN!, MALEN, AUFLADEN, ABTAUCHEN, RAUS, NAVI) and the
KLINGEL (scares pedestrians, confuses Hausverwaltungs-Bots) in a bottom bar.

Random chain of short missions: Lastenrad befreien (ROLLKAPITAL rack, then
bring it to the Hausprojekt), Soli-Suppe (pick up at the Soli-Küche, deliver
before the thermometer drops), Kran kippen (loosen 3 bolts, topple the
LUXUS-LOFTS crane), Werbung übermalen (paint.exe) and Pfand sammeln. Score =
Kiezkasse in cents.

The wanted level is the MIETSPIEGEL (0-5 little houses): kapern, kippen and
malen raise it, so does getting caught (bots, SCHNELLR drones, the Mietenhai
shark-SUV from 3 on, which can't pass Kiezblock bollards or park paths).
Hiding in a Späti ("Eine Mate, bitte."), riding through a Kiezblock, reaching
the Hausprojekt or simply losing the chasers lowers it. 5/5 = "Rausmodernisiert!".

Performance (Pi 4, ~20 FPS): the whole city is drawn once (art at half
resolution, scaled 2x, convert()ed), each frame blits only the visible window;
rotated sprites (16 steps) and their shadows, HUD, control bar, ticker text
and outlined labels are cached; chasers follow one BFS distance field from the
player (recomputed every 0.4 s, radius-limited) instead of pathing each.

The game surface is 480x764 (PiDashboard draws its 36 px title bar above).
Nothing tappable in x < 100, y < 144 (the emergency-exit corner): the HUD and
the minimap sit there. City, sprites and HUD are based on the approved mockups
in scratch/game_mockups/kiez_sandbox/ (kiez_city.py, mock_kiez.py).
"""

import math
import random
from collections import deque

import pygame

import kiezos as K
import party_games

# ------------------------------------------------------------------ layout (game surface coords)

W, H = 480, 764
TS = 24          # world tile size (px)
A = 2            # map art is drawn at half resolution and scaled up
SPR = 3          # sprite scale
AT = TS // A
N = 64           # tiles per side
PER = 9          # 2 road tiles + 7 block tiles
HUD = pygame.Rect(0, 0, W, 88)
VIEW = pygame.Rect(0, 88, W, 552)
TICKER = pygame.Rect(0, 640, W, 24)
CTRL = pygame.Rect(0, 664, W, 100)
NO_TAP = pygame.Rect(0, 0, 100, 144)      # emergency-exit corner (screen 100x180 minus the title bar)
MINI = pygame.Rect(6, VIEW.y + 6, 92, 92)
BELL_RECT = pygame.Rect(8, CTRL.y + 8, 104, 84)
ACT_RECT = pygame.Rect(W - 8 - 176, CTRL.y + 8, 176, 84)
MAX_FRAME_SECONDS = 0.25  # longest frame that is caught up in sub-steps (see update())
BILANZ_TAP_DELAY = 1.6  # s after the end before "Weiter" works
BANNER_TEXT_W = W - 116 - 24  # text width inside the mission/warning banner

# ------------------------------------------------------------------ tuning

SCHICHT_SECONDS = 180.0
BIKE_SPEED = 130.0       # px/s
BOT_SPEED = 78.0
SHARK_SPEED = 150.0      # faster than the bike: escape through bollards / park paths
DRONE_SPEED = 66.0
NEAR = 40                # px: "at" an action point
INVULN_SECONDS = 2.5
STUN_SECONDS = 0.5
LOSE_TRACK_SECONDS = 9.0
HIDE_DROP_SECONDS = 2.4
HAUSPROJEKT_COOLDOWN = 25.0
POLLER_COOLDOWN = 12.0
FIELD_EVERY = 0.4
FIELD_RADIUS = 30
SOUP_START, SOUP_MIN, SOUP_DROP = 75.0, 35.0, 1.1   # °C, °C, °C/s
PFAND_SECONDS = 45.0
BOTS = [0, 1, 2, 2, 3, 4]
DRONES = [0, 0, 1, 1, 2, 2]
SHARK_LEVEL = 3
PAINT_COLS, PAINT_ROWS = 6, 5

# ------------------------------------------------------------------ city tiles + palette

ROAD, WALK, HOUSE, PARK, PATH, WATER, BRIDGE, SITE = range(8)
BIKE_OK = {ROAD, PATH, BRIDGE}

ASPH = (62, 56, 82)
ASPH2 = (70, 63, 92)
LINE = (232, 226, 248)
WALKC = (164, 154, 186)
WALK2 = (148, 138, 172)
CURB = (112, 100, 134)
GRASS = (88, 162, 98)
GRASS2 = (104, 180, 110)
TREE = (50, 120, 76)
TREE2 = (82, 162, 98)
PATHC = (206, 186, 146)
WATERC = (64, 102, 196)
WATER2 = (100, 144, 228)
DIRT = (150, 112, 80)
DIRT2 = (126, 92, 66)
OUT = (46, 32, 58)
ROOFS = [(178, 86, 78), (162, 106, 86), (122, 114, 152), (188, 122, 94), (142, 82, 98), (106, 98, 130), (170, 96, 120)]
GLASS = (140, 214, 232)
GLASS2 = (204, 246, 252)
GOLD = (232, 186, 60)
SCOOT = (170, 225, 50)    # ROLLKAPITAL lime
SCOOT_D = (100, 150, 30)
DRONE = (255, 120, 40)    # SCHNELLR orange
SHARK = (52, 56, 74)
RED = (220, 40, 60)
WHITE = (255, 255, 255)
GREEN = (40, 160, 90)
RAINBOW = [(230, 50, 50), (250, 150, 40), (250, 230, 60), (60, 180, 80), (60, 110, 230), (150, 60, 200)]

BRIDGE_COLS = {9, 10, 36, 37, 54, 55}
RIVER = range(38, 45)
SPECIAL = {(2, 2): "park", (5, 1): "site", (4, 5): "glas", (1, 6): "park", (6, 2): "glas",
           (1, 1): "hausprojekt", (3, 1): "soli", (5, 6): "site", (0, 3): "park"}
POLLER = [((27, 24), (28, 24)), ((22, 18), (22, 19)), ((45, 13), (46, 13)), ((9, 30), (10, 30)), ((36, 51), (36, 52))]
SPAETIS = [(2, 0, "s"), (3, 3, "n"), (0, 2, "e"), (4, 3, "s"), (6, 6, "n"), (1, 5, "e")]
UBAHN = [(2, 1), (4, 0), (5, 3), (3, 6), (0, 5)]
SITES = [(5, 1), (5, 6)]
BILLBOARD_BLOCKS = [(2, 0), (6, 0), (4, 2), (1, 3), (6, 3), (2, 5), (5, 5), (4, 6)]
HAUSPROJEKT_DOOR = (14, 18)
SOLI_DOOR = (32, 10)
START_TILE = (22, 27)

ADS = [["BERLIN 2049", "Miete jetzt", "im Abo!"], ["LUXUS-LOFTS", "ab 14.900 €/m²"], ["ROLLKAPITAL", "Freiheit.", "Gemietet."],
       ["SCHNELLR", "9 Minuten.", "Oder nie."], ["BETONGOLD", "Ihr Kiez.", "Unser Gewinn."], ["MIETPREIS-", "BREMSE?", "LOL."],
       ["CO-LIVING", "6 m², Barista", "inklusive"], ["SMART HOME", "Heizung nur", "im Premium"]]
SOUP_PLACES = ["Kiezplenum", "Kältebus", "Nachbarschafts-Café", "Wagenplatz", "Mieter*innen-Treff", "Senior*innen-Treff",
               "Kita-Elternabend", "Kiezladen"]

TICKER_LINES = [
    "BERLIN 2049: Mietspiegel ab sofort in Echtzeit",
    "ROLLKAPITAL AG meldet Rekordgewinn, Fahrer*innen melden Rekordmüdigkeit",
    "SCHNELLR liefert jetzt auch Ihre Kündigung - in 9 Minuten",
    "BETONGOLD Immobilien: 'Wohnen ist ein Premium-Feature'",
    "Späti-Mate offiziell systemrelevant",
    "Hausverwaltungs-Bots finden die Heizung weiterhin nicht",
    "LUXUS-LOFTS: jetzt mit Blick auf andere LUXUS-LOFTS",
    "Wetter: heiter bis vergesellschaftet",
    "Kiezblock wirkt: SUV-Dichte sinkt, Spielstraßen-Dichte steigt",
]
BOT_LINES = ["Modernisierungsumlage!", "Mieterhöhung gem. §559!", "Ihr Antrag wurde abgelehnt.", "Eigenbedarf! Ganz echt!",
             "Heizung? Kostet extra.", "Bitte Ticket ziehen."]
SHARK_LINES = ["INDEX-MIETE! INDEX-MIETE!", "Platz da, Rendite!", "Ich muss nur kurz aufwerten!"]
DRONE_LINES = ["SCHNELLR scannt...", "Kiez wird bewertet.", "Lieferung: Ihre Kündigung."]
OVER_TIME = ["Schicht vorbei!", "Feierabend! Kiez gehalten.", "Schichtende. Solidarisch ausgestempelt."]


def block_kind(bx, by):
    if by == 4:
        return "river"
    return SPECIAL.get((bx, by), "altbau")


def soup_text(place):
    """HUD line while delivering soup (short enough for the HUD field at >= 15 px)."""
    return f"Suppe {'zur' if place.endswith('e') else 'zum'} {place}, solange warm!"


def ad_name(lines):
    """Brand of a billboard: its first line, a trailing hyphen joined with the next ("MIETPREIS-BREMSE?")."""
    name = lines[0]
    if name.endswith("-") and len(lines) > 1:
        name += lines[1]
    return name


def tile_center(tx, ty):
    return (tx + 0.5) * TS, (ty + 0.5) * TS


def tile_of(x, y):
    return int(x // TS), int(y // TS)


def fmt_eur(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}{cents // 100:,}".replace(",", ".") + f",{cents % 100:02d} €"


def _up(s, k=A):
    return pygame.transform.scale(s, (s.get_width() * k, s.get_height() * k))


def _canvas(w, h):
    return pygame.Surface((w, h), pygame.SRCALPHA)


def _pattern(rows, pal, k=A):
    s = _canvas(len(rows[0]), len(rows))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in pal:
                s.set_at((x, y), pal[ch])
    return _up(s, k)


# ------------------------------------------------------------------ the city (drawn once)

class City:
    def __init__(self, seed=161):
        self.rng = random.Random(seed)
        self.grid = [[self._tile(x, y) for x in range(N)] for y in range(N)]
        self.poller = {t for pair in POLLER for t in pair}
        self.car = {(x, y) for y in range(N) for x in range(N)
                    if self.grid[y][x] in (ROAD, BRIDGE) and (x, y) not in self.poller}
        self.walk = [(x, y) for y in range(N) for x in range(N) if self.grid[y][x] == WALK]
        self.spaeti_doors = [self._door(bx, by, side) for bx, by, side in SPAETIS]
        for t in self.spaeti_doors + [HAUSPROJEKT_DOOR, SOLI_DOOR, START_TILE]:
            assert t in self.car, t
        self.billboards = []
        for bx, by in BILLBOARD_BLOCKS:
            tile = (bx * PER + 8, by * PER + 2)
            road = (tile[0], tile[1] - 1)
            assert self.at(*tile) == WALK and road in self.car, (tile, road)
            self.billboards.append((tile, road))
        self.surf = None
        self.mini = None

    @staticmethod
    def _door(bx, by, side):
        return {"s": (bx * PER + 5, by * PER + PER), "n": (bx * PER + 5, by * PER + 1),
                "e": (bx * PER + PER, by * PER + 5), "w": (bx * PER + 1, by * PER + 5)}[side]

    def _tile(self, x, y):
        if y in RIVER:
            return BRIDGE if x in BRIDGE_COLS else WATER
        if x % PER < 2 or y % PER < 2:
            return ROAD
        bx, by = x // PER, y // PER
        lx, ly = x % PER - 2, y % PER - 2
        kind = block_kind(bx, by)
        if kind == "park" and (lx == 3 or ly == 3):
            return PATH
        if lx in (0, 6) or ly in (0, 6):
            return WALK
        return {"park": PARK, "site": SITE}.get(kind, HOUSE)

    def at(self, tx, ty):
        if 0 <= tx < N and 0 <= ty < N:
            return self.grid[ty][tx]
        return HOUSE

    def bikeable(self, tx, ty):
        return self.at(tx, ty) in BIKE_OK

    # ---- drawing (once)
    def build(self):
        rng = self.rng
        art = pygame.Surface((N * AT, N * AT))
        art.fill(ASPH)
        for _ in range(9000):
            art.set_at((rng.randrange(N * AT), rng.randrange(N * AT)), ASPH2)
        self._road_marks(art)
        for by in range(8):
            for bx in range(8):
                x0, y0 = (bx * PER + 2) * AT, (by * PER + 2) * AT
                if x0 >= N * AT or y0 >= N * AT:
                    continue
                kind = block_kind(bx, by)
                if kind != "river":
                    getattr(self, "_draw_" + kind)(art, x0, y0)
        self._river(art)
        self.mini = pygame.transform.smoothscale(art, (88, 88))
        surf = _up(art)
        self._labels(surf)
        if pygame.display.get_surface() is not None:
            surf = surf.convert()
            self.mini = self.mini.convert()
        self.surf = surf
        return self

    def _road_marks(self, art):
        span = N * AT
        for k in range(0, 8):
            c = (k * PER + 1) * AT
            for p in range(0, span, 12):
                if p // AT % PER >= 2:
                    pygame.draw.line(art, LINE, (c, p + 2), (c, p + 7))
                    pygame.draw.line(art, LINE, (p + 2, c), (p + 7, c))
        for k in range(1, 8):
            for m in range(1, 8):
                x, y = k * PER * AT, m * PER * AT
                if (k + m) % 2:
                    for i in range(0, 24, 4):
                        pygame.draw.rect(art, LINE, (x + i, y - 5, 2, 4))
                        pygame.draw.rect(art, LINE, (x + i, y + 25, 2, 4))

    def _walk(self, art, x0, y0):
        r = pygame.Rect(x0, y0, 7 * AT, 7 * AT)
        pygame.draw.rect(art, WALKC, r)
        for x in range(r.x, r.right, 4):
            for y in range(r.y, r.bottom, 4):
                if (x + y) % 8 == 0:
                    art.set_at((x, y), WALK2)
        pygame.draw.rect(art, CURB, r, 1)
        for i in range(1, 7, 2):
            for (tx, ty) in ((x0 + i * AT + 6, y0 + 6), (x0 + i * AT + 6, r.bottom - 6),
                             (x0 + 6, y0 + i * AT + 6), (r.right - 6, y0 + i * AT + 6)):
                if self.rng.random() < 0.55:
                    self._tree(art, tx, ty, 4)

    def _tree(self, art, cx, cy, r):
        pygame.draw.circle(art, (40, 30, 56), (cx + 1, cy + 1), r + 1)
        pygame.draw.circle(art, TREE, (cx, cy), r)
        pygame.draw.circle(art, TREE2, (cx - 1, cy - 1), max(1, r - 2))
        if self.rng.random() < 0.2:
            art.set_at((cx + 1, cy), K.PINK)

    def _house(self, art, rect, color, horizontal):
        pygame.draw.rect(art, color, rect)
        dark = tuple(max(0, c - 40) for c in color)
        light = tuple(min(255, c + 30) for c in color)
        if horizontal:
            pygame.draw.line(art, dark, (rect.x, rect.centery), (rect.right - 1, rect.centery))
            pygame.draw.line(art, light, (rect.x, rect.y + 1), (rect.right - 1, rect.y + 1))
        else:
            pygame.draw.line(art, dark, (rect.centerx, rect.y), (rect.centerx, rect.bottom - 1))
            pygame.draw.line(art, light, (rect.x + 1, rect.y), (rect.x + 1, rect.bottom - 1))
        for _ in range(self.rng.randint(1, 3)):
            px = self.rng.randrange(rect.x + 2, rect.right - 3)
            py = self.rng.randrange(rect.y + 2, rect.bottom - 3)
            if self.rng.random() < 0.6:
                pygame.draw.rect(art, (70, 50, 60), (px, py, 2, 2))
            else:
                pygame.draw.rect(art, (150, 200, 240), (px, py, 3, 2))
        pygame.draw.rect(art, OUT, rect, 1)

    def _perimeter(self, art, x0, y0, colors=None):
        rng = self.rng
        ix, iy, s, t = x0 + AT, y0 + AT, 5 * AT, 20
        pick = (lambda: rng.choice(colors)) if colors else (lambda: rng.choice(ROOFS))
        for yy in (iy, iy + s - t):
            x = ix
            while x < ix + s:
                w = min(rng.choice((16, 20, 24)), ix + s - x)
                if ix + s - x - w < 10:
                    w = ix + s - x
                self._house(art, pygame.Rect(x, yy, w, t), pick(), True)
                x += w
        for xx in (ix, ix + s - t):
            self._house(art, pygame.Rect(xx, iy + t, t, s - 2 * t), pick(), False)
        court = pygame.Rect(ix + t, iy + t, s - 2 * t, s - 2 * t)
        pygame.draw.rect(art, (120, 134, 110), court)
        self._tree(art, court.centerx, court.centery, 5)
        pygame.draw.rect(art, (60, 60, 80), (court.x + 1, court.bottom - 5, 4, 4))
        pygame.draw.rect(art, (40, 120, 60), (court.x + 6, court.bottom - 5, 4, 4))
        return court

    def _draw_altbau(self, art, x0, y0):
        self._walk(art, x0, y0)
        self._perimeter(art, x0, y0)

    def _draw_hausprojekt(self, art, x0, y0):
        self._walk(art, x0, y0)
        court = self._perimeter(art, x0, y0, colors=[(240, 120, 190), (90, 200, 200), (240, 200, 70), (160, 100, 230)])
        for i, c in enumerate(RAINBOW):  # banner on the roof
            pygame.draw.line(art, c, (x0 + AT + 4, y0 + AT + 6 + i), (x0 + AT + 40, y0 + AT + 6 + i))
        pygame.draw.rect(art, (70, 200, 120), court.inflate(-6, -6))

    def _draw_soli(self, art, x0, y0):
        self._walk(art, x0, y0)
        self._perimeter(art, x0, y0)
        self._house(art, pygame.Rect(x0 + AT, y0 + AT, 60, 20), (210, 70, 110), True)

    def _draw_glas(self, art, x0, y0):
        self._walk(art, x0, y0)
        r = pygame.Rect(x0 + AT, y0 + AT, 5 * AT, 5 * AT)
        pygame.draw.rect(art, GLASS, r)
        for x in range(r.x, r.right, 6):
            pygame.draw.line(art, (110, 180, 205), (x, r.y), (x, r.bottom - 1))
        for y in range(r.y, r.bottom, 6):
            pygame.draw.line(art, (110, 180, 205), (r.x, y), (r.right - 1, y))
        for i in range(0, 50, 9):
            pygame.draw.line(art, GLASS2, (r.x + i, r.bottom - 2), (r.x + i + 18, r.bottom - 20), 2)
        pygame.draw.rect(art, (60, 140, 230), (r.right - 20, r.y + 4, 16, 8))
        pygame.draw.rect(art, OUT, r, 1)

    def _draw_site(self, art, x0, y0):
        self._walk(art, x0, y0)
        r = pygame.Rect(x0 + AT, y0 + AT, 5 * AT, 5 * AT)
        pygame.draw.rect(art, DIRT, r)
        for _ in range(140):
            art.set_at((self.rng.randrange(r.x, r.right), self.rng.randrange(r.y, r.bottom)), DIRT2)
        pygame.draw.rect(art, (100, 74, 56), r.inflate(-24, -24))
        for x in range(r.x, r.right, 4):
            pygame.draw.line(art, WHITE, (x, r.y), (x + 1, r.y))
            pygame.draw.line(art, RED, (x + 2, r.y), (x + 3, r.y))
            pygame.draw.line(art, WHITE, (x, r.bottom - 1), (x + 1, r.bottom - 1))
        for y in range(r.y, r.bottom, 4):
            pygame.draw.line(art, WHITE, (r.x, y), (r.x, y + 1))
            pygame.draw.line(art, WHITE, (r.right - 1, y), (r.right - 1, y + 1))
        for i in range(3):
            pygame.draw.rect(art, (170, 170, 190), (r.x + 4, r.y + 4 + i * 3, 10, 2))

    def _draw_park(self, art, x0, y0):
        r = pygame.Rect(x0, y0, 7 * AT, 7 * AT)
        pygame.draw.rect(art, GRASS, r)
        for _ in range(260):
            art.set_at((self.rng.randrange(r.x, r.right), self.rng.randrange(r.y, r.bottom)), GRASS2)
        pygame.draw.rect(art, PATHC, (x0 + 3 * AT + 1, y0, AT - 2, 7 * AT))
        pygame.draw.rect(art, PATHC, (x0, y0 + 3 * AT + 1, 7 * AT, AT - 2))
        pygame.draw.ellipse(art, WATERC, (x0 + 50, y0 + 50, 26, 18))
        pygame.draw.ellipse(art, WATER2, (x0 + 54, y0 + 53, 10, 4))
        for _ in range(9):
            tx, ty = self.rng.randrange(x0 + 4, x0 + 80), self.rng.randrange(y0 + 4, y0 + 80)
            if abs(tx - (x0 + 42)) > 8 and abs(ty - (y0 + 42)) > 8 and not (x0 + 46 < tx < x0 + 80 and y0 + 46 < ty < y0 + 72):
                self._tree(art, tx, ty, self.rng.randint(4, 7))
        pygame.draw.rect(art, (130, 90, 60), (x0 + 14, y0 + 46, 10, 3))

    def _river(self, art):
        y0, y1 = RIVER[0] * AT, (RIVER[-1] + 1) * AT
        pygame.draw.rect(art, WATERC, (0, y0, N * AT, y1 - y0))
        for _ in range(500):
            x, y = self.rng.randrange(N * AT), self.rng.randrange(y0 + 3, y1 - 3)
            pygame.draw.line(art, WATER2, (x, y), (x + 3, y))
        for y in (y0, y1 - 2):
            pygame.draw.rect(art, (140, 128, 160), (0, y, N * AT, 2))
        for x in BRIDGE_COLS:
            if x % PER == 0:
                b = pygame.Rect(x * AT - 2, y0 - 2, 2 * AT + 4, y1 - y0 + 4)
                pygame.draw.rect(art, (36, 26, 50), b.move(2, 2))
                pygame.draw.rect(art, ASPH, b)
                pygame.draw.rect(art, (190, 180, 210), (b.x, b.y, 2, b.h))
                pygame.draw.rect(art, (190, 180, 210), (b.right - 2, b.y, 2, b.h))
                for p in range(b.y, b.bottom, 12):
                    pygame.draw.line(art, LINE, (b.centerx, p + 2), (b.centerx, p + 7))
        bx, by = 20 * AT, y0 + 26  # a party boat
        pygame.draw.ellipse(art, (240, 240, 250), (bx, by, 40, 14))
        pygame.draw.rect(art, K.PINK, (bx + 8, by + 3, 22, 8))
        for i, c in enumerate(RAINBOW):
            pygame.draw.line(art, c, (bx + 9, by + 4 + i), (bx + 28, by + 4 + i))

    def _labels(self, surf):
        for (a, b) in POLLER:  # Kiezblock bollards: bikes yes, SUVs no
            for tx, ty in (a, b):
                for i in range(3):
                    if a[1] == b[1]:
                        cx, cy = tx * TS + 4 + i * 8, ty * TS + 12
                    else:
                        cx, cy = tx * TS + 12, ty * TS + 4 + i * 8
                    pygame.draw.circle(surf, OUT, (cx + 1, cy + 2), 4)
                    pygame.draw.circle(surf, WHITE, (cx, cy), 3)
                    pygame.draw.circle(surf, RED, (cx, cy), 1)

        def sign(text, center, fg, bg):
            img = K.font(15).render(text, False, fg)
            r = img.get_rect(center=center).inflate(8, 4)
            pygame.draw.rect(surf, OUT, r.move(2, 2))
            pygame.draw.rect(surf, bg, r)
            pygame.draw.rect(surf, OUT, r, 1)
            surf.blit(img, img.get_rect(center=r.center))
        for bx, by, side in SPAETIS:
            x0, y0 = (bx * PER + 2) * TS, (by * PER + 2) * TS
            cx, cy = {"s": (x0 + 84, y0 + 6.5 * TS), "n": (x0 + 84, y0 + 0.5 * TS),
                      "e": (x0 + 6.5 * TS, y0 + 84), "w": (x0 + 0.5 * TS, y0 + 84)}[side]
            for i in range(6):
                c = K.PINK if i % 2 else (255, 230, 90)
                if side in "ns":
                    pygame.draw.rect(surf, c, (cx - 36 + i * 12, cy - 12 if side == "s" else cy, 12, 12))
                else:
                    pygame.draw.rect(surf, c, (cx - 12 if side == "e" else cx, cy - 36 + i * 12, 12, 12))
            sign("SPÄTI", (cx, cy), (255, 230, 90), (60, 30, 90))
        for bx, by in UBAHN:
            x0, y0 = (bx * PER + 2) * TS, (by * PER + 2) * TS
            r = pygame.Rect(x0 + 2, y0 + 2, 22, 22)
            pygame.draw.rect(surf, (30, 70, 170), r)
            pygame.draw.rect(surf, WHITE, r, 2)
            K.t95(surf, "U", 15, r.center, color=WHITE, anchor="center")
        named = {"hausprojekt": ("HAUSPROJEKT", WHITE, (150, 40, 130)),
                 "soli": ("SOLI-KÜCHE", WHITE, (200, 50, 90)),
                 "glas": ("BETONGOLD", GOLD, (30, 30, 40))}
        for (bx, by), kind in SPECIAL.items():
            if kind in named:
                text, fg, bg = named[kind]
                sign(text, ((bx * PER + 2) * TS + 84, (by * PER + 2) * TS + 84), fg, bg)

    # ---- pathing
    def nearest_bikeable(self, tx, ty):
        if self.bikeable(tx, ty):
            return tx, ty
        for r in range(1, 8):
            best = None
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) == r and self.bikeable(tx + dx, ty + dy):
                        d = dx * dx + dy * dy
                        if best is None or d < best[0]:
                            best = (d, tx + dx, ty + dy)
            if best:
                return best[1], best[2]
        return None

    def path(self, start, goal):
        """BFS over bike tiles; returns world waypoints (corners only)."""
        if not self.bikeable(*start):
            start = self.nearest_bikeable(*start)
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == goal:
                break
            x, y = cur
            for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nxt not in prev and self.bikeable(*nxt):
                    prev[nxt] = cur
                    q.append(nxt)
        if goal not in prev:
            return []
        out, cur = [], goal
        while cur is not None:
            out.append(cur)
            cur = prev[cur]
        out.reverse()
        pts = [out[0]]
        for i in range(1, len(out) - 1):
            a, b, c = out[i - 1], out[i], out[i + 1]
            if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
                pts.append(b)
        pts.append(out[-1])
        return [tile_center(*p) for p in pts[1:]] if len(out) > 1 else [tile_center(*goal)]

    def car_field(self, seeds, radius=FIELD_RADIUS):
        """BFS distance over car tiles (roads, bridges, no bollards) from seeds."""
        dist = {s: 0 for s in seeds}
        q = deque(seeds)
        while q:
            cur = q.popleft()
            d = dist[cur] + 1
            if d > radius:
                continue
            x, y = cur
            for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nxt not in dist and nxt in self.car:
                    dist[nxt] = d
                    q.append(nxt)
        return dist


_CITY = None


def city():
    global _CITY
    if _CITY is None:
        _CITY = City().build()
    return _CITY


# ------------------------------------------------------------------ sprites (cached)

_SPR = {}


def _cached(key, make):
    if key not in _SPR:
        _SPR[key] = make()
    return _SPR[key]


def bike_sprite(cargo="box", hair=(255, 120, 200), jacket=(160, 90, 230)):
    """Lastenrad (Long John) top-down, nose up. 10x18 art px x3."""
    def make():
        rows = ["....kk....", "....kk....", ".kkkkkkkk.", ".kbbbbbbk.", ".kbccccbk.", ".kbccccbk.",
                ".kbbbbbbk.", ".kkkkkkkk.", "....kk....", "kgg.kk.ggk", ".kjjhhjjk.", ".jjhhhhjj.",
                ".jjjhhjjj.", "..jjjjjj..", "...jjjj...", "....kk....", "....kk....", "....kk...."]
        cc = {"box": (200, 150, 90), "pot": (190, 190, 210), "bottles": (90, 170, 90), "paint": K.PINK, "lime": SCOOT}[cargo]
        s = _pattern(rows, {"k": OUT, "b": (180, 120, 70), "c": cc, "g": (240, 200, 160), "j": jacket, "h": hair}, SPR)
        if cargo == "pot":
            pygame.draw.rect(s, (120, 120, 140), (9, 14, 12, 3))
        elif cargo == "bottles":
            for x in (8, 14, 20):
                pygame.draw.circle(s, (40, 110, 50), (x, 15), 3)
        elif cargo == "paint":
            for i, c in enumerate(RAINBOW[:4]):
                pygame.draw.rect(s, c, (8 + i * 4, 12, 3, 8))
        elif cargo == "lime":
            pygame.draw.rect(s, SCOOT_D, (9, 13, 12, 2))
        return s
    return _cached(("bike", cargo, hair, jacket), make)


def locked_bike_sprite():
    """ROLLKAPITAL Lastenrad without rider, lime."""
    def make():
        rows = ["....kk....", "....kk....", ".kkkkkkkk.", ".kbbbbbbk.", ".kbccccbk.", ".kbccccbk.",
                ".kbbbbbbk.", ".kkkkkkkk.", "....kk....", "kgg.kk.ggk", "....kk....", "...kssk...",
                "...kssk...", "....kk....", "....kk....", "....kk....", "....kk....", "....kk...."]
        return _pattern(rows, {"k": OUT, "b": SCOOT, "c": SCOOT_D, "g": (200, 200, 210), "s": (40, 40, 50)}, SPR)
    return _cached("lockedbike", make)


def scooter_sprite():
    return _cached("scooter", lambda: _pattern(["k..k", ".kk.", ".cc.", ".cc.", ".cc.", ".cc.", ".cc.", ".cc.", ".kk.", ".kk."],
                                               {"k": OUT, "c": SCOOT}, SPR))


def suv_sprite():
    """The Mietenhai: luxury SUV with shark fin, teeth grille, gold euro. Nose up."""
    def make():
        s = _canvas(18, 30)
        pygame.draw.rect(s, OUT, (0, 1, 18, 29), border_radius=4)
        pygame.draw.rect(s, SHARK, (1, 2, 16, 27), border_radius=4)
        pygame.draw.rect(s, (90, 96, 120), (2, 3, 14, 5))
        for i in range(7):
            pygame.draw.polygon(s, WHITE, [(2 + i * 2, 1), (4 + i * 2, 1), (3 + i * 2, 4)])
        s.set_at((1, 3), RED)
        s.set_at((16, 3), RED)
        pygame.draw.rect(s, (40, 60, 110), (2, 9, 14, 4))
        pygame.draw.rect(s, (80, 86, 108), (3, 13, 12, 10))
        pygame.draw.polygon(s, (30, 32, 44), [(9, 12), (11, 19), (9, 22)])
        pygame.draw.polygon(s, (120, 126, 150), [(9, 12), (10, 18), (9, 20)])
        pygame.draw.rect(s, (40, 60, 110), (3, 23, 12, 3))
        pygame.draw.polygon(s, SHARK, [(4, 29), (1, 30), (6, 27)])
        pygame.draw.polygon(s, SHARK, [(14, 29), (17, 30), (12, 27)])
        K._px(s, [".XX", "X..", "XX.", "X..", ".XX"], 8, 4, GOLD)
        return pygame.transform.scale(s, (45, 75))
    return _cached("suv", make)


def drone_sprite(frame=0):
    def make():
        s = _canvas(14, 14)
        pygame.draw.line(s, OUT, (2, 2), (11, 11), 2)
        pygame.draw.line(s, OUT, (11, 2), (2, 11), 2)
        for cx, cy in ((2, 2), (11, 2), (2, 11), (11, 11)):
            pygame.draw.circle(s, (210, 210, 230), (cx, cy), 2)
            pygame.draw.circle(s, OUT, (cx, cy), 2, 1)
            if frame:
                pygame.draw.line(s, WHITE, (cx - 2, cy), (cx + 2, cy))
            else:
                pygame.draw.line(s, WHITE, (cx, cy - 2), (cx, cy + 2))
        pygame.draw.rect(s, OUT, (4, 4, 6, 6))
        pygame.draw.rect(s, DRONE, (5, 5, 4, 4))
        s.set_at((7, 7), WHITE)
        return _up(s, SPR)
    return _cached(("drone", frame), make)


def bot_sprite():
    """Hausverwaltungs-Bot: box on treads with a paragraph screen."""
    def make():
        s = _canvas(12, 14)
        pygame.draw.rect(s, OUT, (0, 2, 12, 12))
        pygame.draw.rect(s, (180, 180, 200), (1, 3, 10, 10))
        pygame.draw.rect(s, (30, 40, 60), (2, 4, 8, 6))
        K._px(s, [".XX", "X..", ".X.", "..X", "XX."], 4, 4, (120, 255, 160))
        pygame.draw.line(s, OUT, (6, 2), (6, 0))
        s.set_at((6, 0), RED)
        pygame.draw.rect(s, OUT, (0, 11, 12, 3))
        return _up(s, SPR)
    return _cached("bot", make)


def ped_sprite(i):
    hair = [(255, 120, 200), (80, 210, 220), (250, 220, 90), (40, 30, 40), (150, 90, 50), (170, 120, 240), (120, 220, 120)]
    jacket = [(160, 90, 230), (60, 180, 160), (230, 90, 90), (250, 170, 60), (90, 120, 230), (40, 40, 60)]

    def make():
        s = _canvas(8, 6)
        pygame.draw.ellipse(s, OUT, (0, 1, 8, 5))
        pygame.draw.ellipse(s, jacket[i % len(jacket)], (1, 2, 6, 3))
        pygame.draw.circle(s, OUT, (4, 2), 2)
        pygame.draw.rect(s, hair[(i * 3) % len(hair)], (3, 1, 2, 2))
        return _up(s, SPR)
    return _cached(("ped", i % 12), make)


def bottle_sprite():
    return _cached("bottle", lambda: _pattern([".k.", ".g.", "kgk", "kgk", "kwk", "kgk", "kkk"],
                                              {"k": OUT, "g": (60, 160, 80), "w": (230, 240, 230)}, SPR))


def crane_sprite():
    """Top-down tower crane, pivot = centre."""
    def make():
        s = _canvas(110, 18)
        pygame.draw.rect(s, (100, 100, 110), (2, 5, 14, 8))
        pygame.draw.rect(s, OUT, (2, 5, 14, 8), 1)
        pygame.draw.rect(s, OUT, (16, 7, 92, 4))
        pygame.draw.rect(s, (250, 200, 40), (16, 8, 92, 2))
        for x in range(18, 106, 5):
            pygame.draw.line(s, OUT, (x, 7), (x + 3, 10))
        pygame.draw.rect(s, OUT, (40, 3, 12, 12))
        pygame.draw.rect(s, (250, 200, 40), (41, 4, 10, 10))
        pygame.draw.line(s, OUT, (41, 4), (50, 13))
        pygame.draw.line(s, OUT, (50, 4), (41, 13))
        pygame.draw.line(s, OUT, (96, 11), (96, 16))
        pygame.draw.rect(s, RED, (94, 15, 5, 3))
        return _up(s)
    return _cached("crane", make)


def billboard_sprite(lines, bg=WHITE, fg=RED, w=104, h=58):
    def make():
        s = pygame.Surface((w, h + 8), pygame.SRCALPHA)
        pygame.draw.rect(s, OUT, (w // 2 - 3, h - 2, 6, 10))
        pygame.draw.rect(s, OUT, (0, 0, w, h))
        pygame.draw.rect(s, bg, (3, 3, w - 6, h - 6))
        lh = 16
        y0 = (h - lh * len(lines)) // 2
        for i, ln in enumerate(lines):
            size = K.fit_size(ln, w - 10, sizes=(15, 14, 13, 12, 11))
            K.t95(s, ln, size, (w // 2, y0 + i * lh + lh // 2), color=fg, anchor="center")
        return s
    return _cached(("bb", tuple(lines), bg, fg, w, h), make)


def mural_sprite(w=104, h=58):
    def make():
        s = pygame.Surface((w, h + 8), pygame.SRCALPHA)
        pygame.draw.rect(s, OUT, (w // 2 - 3, h - 2, 6, 10))
        pygame.draw.rect(s, OUT, (0, 0, w, h))
        for i, c in enumerate(RAINBOW):
            pygame.draw.rect(s, c, (3, 3 + i * (h - 6) // 6, w - 6, (h - 6) // 6 + 1))
        K.t95(s, "KIEZ", 15, (w // 2, 18), color=WHITE, anchor="center")
        K.t95(s, "BLEIBT!", 15, (w // 2, 38), color=WHITE, anchor="center")
        K.heart(s, (w - 14, 10), 1, K.PINK)
        return s
    return _cached(("mural", w, h), make)


def garden_sprite():
    """What a toppled LUXUS-LOFTS site turns into (120x120 world px)."""
    def make():
        s = pygame.Surface((120, 120), pygame.SRCALPHA)
        s.fill(GRASS)
        rng = random.Random(7)
        for _ in range(160):
            s.set_at((rng.randrange(120), rng.randrange(120)), GRASS2)
        for i in range(3):
            r = pygame.Rect(12 + i * 34, 64, 26, 44)
            pygame.draw.rect(s, (130, 90, 60), r)
            pygame.draw.rect(s, OUT, r, 2)
            for k in range(6):
                c = [K.PINK, (250, 230, 60), (230, 80, 80), WHITE][(i + k) % 4]
                pygame.draw.circle(s, (60, 150, 80), (r.x + 6 + (k % 2) * 13, r.y + 7 + (k // 2) * 13), 5)
                pygame.draw.circle(s, c, (r.x + 6 + (k % 2) * 13, r.y + 6 + (k // 2) * 13), 2)
        pygame.draw.rect(s, OUT, (0, 0, 120, 120), 2)
        return s
    return _cached("garden", make)


def house_pip(on, size=26):
    def make():
        s = _canvas(12, 12)
        col = K.F_LATE if on else K.F_FACE
        pygame.draw.polygon(s, OUT, [(0, 6), (6, 0), (11, 6)])
        pygame.draw.rect(s, OUT, (1, 5, 10, 7))
        pygame.draw.polygon(s, col, [(2, 5), (6, 1), (9, 5)])
        pygame.draw.rect(s, col, (2, 6, 8, 5))
        if on:
            K._px(s, [".XX", "X..", "XX.", "X..", ".XX"], 4, 6, WHITE)
        else:
            pygame.draw.rect(s, (150, 140, 175), (5, 8, 2, 3))
        return pygame.transform.scale(s, (size, size))
    return _cached(("pip", on, size), make)


def bell_icon(size):
    def make():
        s = _canvas(16, 16)
        pygame.draw.polygon(s, OUT, [(8, 1), (13, 6), (14, 12), (2, 12), (3, 6)])
        pygame.draw.polygon(s, K.SUN, [(8, 2), (12, 6), (13, 11), (3, 11), (4, 6)])
        pygame.draw.circle(s, OUT, (8, 14), 2)
        pygame.draw.line(s, WHITE, (6, 5), (5, 9))
        return pygame.transform.scale(s, (size, size))
    return _cached(("bell", size), make)


def warn_icon(size):
    def make():
        s = _canvas(16, 16)
        pygame.draw.polygon(s, K.SUN, [(8, 1), (15, 14), (1, 14)])
        pygame.draw.polygon(s, K.F_INK, [(8, 1), (15, 14), (1, 14)], 1)
        pygame.draw.rect(s, K.F_INK, (7, 5, 2, 5))
        pygame.draw.rect(s, K.F_INK, (7, 11, 2, 2))
        return pygame.transform.scale(s, (size, size))
    return _cached(("warn", size), make)


def menu_icon(size=32):
    """16px menu/title icon: a pink-ridered Lastenrad (side view) with a € box, scaled."""
    def make():
        s = _canvas(16, 16)
        for cx in (3, 12):  # wheels
            pygame.draw.circle(s, K.INK, (cx, 12), 3)
            pygame.draw.circle(s, (200, 200, 215), (cx, 12), 1)
        pygame.draw.rect(s, K.INK, (0, 5, 8, 6))  # cargo box
        pygame.draw.rect(s, SCOOT, (1, 6, 6, 4))
        K._px(s, [".X", "X.", ".X"], 3, 6, OUT)
        pygame.draw.line(s, K.INK, (7, 10), (12, 10))  # frame
        pygame.draw.line(s, K.INK, (10, 10), (11, 6))
        pygame.draw.rect(s, (160, 90, 230), (10, 4, 3, 4))  # rider
        pygame.draw.rect(s, K.PINK, (10, 1, 3, 3))
        pygame.draw.line(s, K.INK, (12, 5), (14, 7))
        return pygame.transform.scale(s, (size, size))
    return _cached(("menu", size), make)


_ROT = {}


def rotated(key, surf, angle_deg):
    """(sprite, shadow) rotated in 16 steps, cached (rotating per frame is too slow on a Pi)."""
    step = int(round(angle_deg / 22.5)) % 16
    k = (key, step)
    if k not in _ROT:
        img = pygame.transform.rotate(surf, -step * 22.5)
        _ROT[k] = (img, _shadow(img))
    return _ROT[k]


def _shadow(img):
    sh = img.copy()
    sh.fill((20, 10, 30, 110), special_flags=pygame.BLEND_RGBA_MIN)
    return sh


def shadowed(key, surf):
    k = ("sh", key)
    if k not in _ROT:
        _ROT[k] = (surf, _shadow(surf))
    return _ROT[k]


_TXT = {}


def otext(surf, text, size, color, center, outline=OUT):
    """Outlined pixel text (cached: 8 outline blits are too many per frame)."""
    key = (text, size, color, outline)
    img = _TXT.get(key)
    if img is None:
        if len(_TXT) > 400:
            _TXT.clear()
        f = K.font(size)
        inner = f.render(text, False, color)
        ol = f.render(text, False, outline)
        img = _canvas(inner.get_width() + 4, inner.get_height() + 4)
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            img.blit(ol, (2 + dx, 2 + dy))
        img.blit(inner, (2, 2))
        _TXT[key] = img
    r = img.get_rect(center=(int(center[0]), int(center[1])))
    surf.blit(img, r)
    return r


def _label_img(text, fg, bg, size):
    """Tooltip-style label with a drop shadow (cached: no font render per frame)."""
    def make():
        img = K.font(size).render(text, False, fg)
        w, h = img.get_width() + 10, img.get_height() + 6
        s = _canvas(w + 2, h + 2)
        pygame.draw.rect(s, OUT, (2, 2, w, h))
        pygame.draw.rect(s, bg, (0, 0, w, h))
        pygame.draw.rect(s, OUT, (0, 0, w, h), 2)
        s.blit(img, img.get_rect(center=(w // 2, h // 2)))
        return s
    return _cached(("label", text, fg, bg, size), make)


def _label_box(surf, text, center, fg=None, bg=None, size=15, area=None):
    """Draws a label centred on center (kept inside area if given); returns its rect."""
    img = _label_img(text, fg or K.F_INK, bg or K.F_TIP, size)
    r = img.get_rect(center=(int(center[0]), int(center[1])))
    if area is not None:
        r.clamp_ip(area)
    surf.blit(img, r)
    return r


# ------------------------------------------------------------------ moving things

class Mob:
    """A chaser: "bot" / "shark" drive along the car distance field, "drone" flies."""

    def __init__(self, kind, x, y):
        self.kind = kind
        self.x, self.y = x, y
        self.way = None  # next tile-centre waypoint
        self.prev = None
        self.heading = 0.0
        self.stun_until = 0.0
        self.stuck = False
        self.lost_counted = False
        self.chase_t = 0.0
        self.phase = random.uniform(0, 6)

    @property
    def speed(self):
        return {"bot": BOT_SPEED, "shark": SHARK_SPEED, "drone": DRONE_SPEED}[self.kind]


class Ped:
    def __init__(self, tile, i, rng):
        self.x, self.y = tile_center(*tile)
        self.i = i
        self.dir = rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
        self.hop_until = 0.0
        self.goal = None


# ------------------------------------------------------------------ the game

class KiezKapernGame(party_games._Game):
    NAME = "KIEZ KAPERN"
    ICON = "kiezkapern"
    DESCRIPTION = "3-Minuten-Schicht im Kiez"
    READY_TEXT = "Tippen zum Losfahren"
    SCORE_LABEL = "Kiezkasse"
    SCORE_UNIT = ""

    @staticmethod
    def format_score(score):
        return fmt_eur(score)

    @staticmethod
    def icon(size):
        return menu_icon(size)

    # ------------------------------------------------------------ state
    def reset(self, now):
        super().reset(now)
        self.city = city()
        self.rng = random.Random()
        self.t = 0.0          # game clock (runs always, for effects)
        self.schicht = 0.0    # shift clock (stops in freeze frames)
        self.x, self.y = tile_center(*START_TILE)
        self.heading = 0.0
        self.path = []
        self.target = None
        self.cam = [self.x - VIEW.w / 2, self.y - VIEW.h / 2]
        self._clamp_cam()
        self.level = 0
        self.level_arrow = None   # ("up"|"down", until)
        self.mobs = []
        self.field = {}
        self.next_field_t = 0.0
        self.next_spawn_t = 0.0
        self.unseen = 0.0
        self.invuln_until = 0.0
        self.stun_until = 0.0
        self.hidden = None        # Späti door tile while hiding
        self.hide_next_drop = 0.0
        self.hp_cooldown_until = 0.0
        self.poller_cd = {}
        self.bell_cd_until = 0.0
        self.bell_ring_until = 0.0
        self.pressed = None       # ("bell"|"act", until)
        self.ped_rng = random.Random()  # own stream: pedestrians must not shift the missions' / chasers' rng
        self.peds = [Ped(self.ped_rng.choice(self.city.walk), i, self.ped_rng) for i in range(70)]
        self.parts = []           # [x, y, vx, vy, age, life, color, size, g]
        self.popups = []          # [text, x, y, age, life, color, size]
        self.wordart = None       # (text, born, size)
        self.banner = None        # (title, text, born, seconds)
        self.bubble = None        # (lines, mob_or_xy, until)
        self.next_bubble_t = 4.0
        self.freeze_until = 0.0
        self.shake = 0.0
        self.flash = None         # (color, until, seconds)
        self.ticker_queue = []
        self.ticker_text = self._ticker_line()
        self.ticker_off = 0.0
        self.mission = None
        self.next_mission_t = 0.0
        self.mission_bag = []
        self.missions_started = 0
        self.toppled = set()
        self.topple_t = {}
        self.painted = set()
        self.ads = {i: ADS[i % len(ADS)] for i in range(len(self.city.billboards))}
        self.paint = None         # paint.exe state while open
        self.counts = {"rad": 0, "suppe": 0, "kran": 0, "malen": 0, "pfand": 0, "hai": 0, "erwischt": 0, "mate": 0}
        self.max_level = 0
        self.rausmod = False
        self.bilanz = False
        self.end_at = 0.0
        self.arrow_rect = None    # tap area of the target arrow (+ its label), set while drawing
        self.arrow_label = None
        self.bubble_rect = None
        self.tap_pos = (0, 0)
        self._hud_key = None
        self._hud = None
        self._ctrl_key = None
        self._ctrl = None
        self._title_bg = None
        self.shark_warned = False

    def update(self, now):
        """party_games caps a frame at MAX_DT_SECONDS, so below 20 FPS the whole game (and the
        3-minute Schicht) runs in slow motion. Instead: up to MAX_FRAME_SECONDS of a slow frame
        are simulated in MAX_DT_SECONDS sub-steps (nothing teleports through a chaser); longer
        stalls are still dropped."""
        dt = max(0.0, min(MAX_FRAME_SECONDS, now - self.last_tick))
        self.last_tick = now
        while dt > 1e-9:
            h = min(party_games.MAX_DT_SECONDS, dt)
            self.step(h)
            dt -= h

    # ------------------------------------------------------------ helpers
    def _clamp_cam(self):
        self.cam[0] = min(max(self.cam[0], 0), N * TS - VIEW.w)
        self.cam[1] = min(max(self.cam[1], 0), N * TS - VIEW.h)

    def to_screen(self, wx, wy):
        return int(wx - self.cam[0] + VIEW.x), int(wy - self.cam[1] + VIEW.y)

    def to_world(self, sx, sy):
        return sx - VIEW.x + self.cam[0], sy - VIEW.y + self.cam[1]

    def bike_tile(self):
        return tile_of(self.x, self.y)

    def _ticker_line(self):
        return "+++ " + random.choice(TICKER_LINES) + " +++"

    def news(self, text):
        self.ticker_queue.append("+++ " + text + " +++")

    def _popup(self, text, x, y, color=K.SUN, size=20, life=1.1):
        for _ in range(8):  # don't print over a live popup nearby: stack above it
            hit = next((p for p in self.popups if abs(p[1] - x) < 110 and abs(p[2] - y) < 22), None)
            if hit is None:
                break
            y = hit[2] - 24
        self.popups.append([text, x, y, 0.0, life, color, size])

    def _burst(self, x, y, n, colors, speed=200, size=5, life=0.7, g=300.0):
        for _ in range(n):
            a = self.rng.uniform(0, 2 * math.pi)
            v = self.rng.uniform(speed * 0.3, speed)
            self.parts.append([x, y, math.cos(a) * v, math.sin(a) * v - speed * 0.3, 0.0,
                               self.rng.uniform(life * 0.6, life), self.rng.choice(colors), size, g])
        if len(self.parts) > 320:
            del self.parts[:len(self.parts) - 320]

    def _freeze(self, seconds):
        self.freeze_until = max(self.freeze_until, self.t + seconds)

    def _flash(self, color, seconds=0.25):
        self.flash = (color, self.t + seconds, seconds)

    def _press(self, which):
        self.pressed = (which, self.t + 0.15)

    def add_cash(self, cents, x=None, y=None):
        self.score = max(0, self.score + cents)
        if x is not None:
            self._popup(("+" if cents >= 0 else "") + fmt_eur(cents), x, y - 30, K.SUN if cents >= 0 else (255, 120, 140), 22)

    def route_to_tile(self, tile):
        goal = self.city.nearest_bikeable(*tile)
        if goal is None:
            return False
        self.path = self.city.path(self.bike_tile(), goal)
        self.target = tile_center(*goal) if self.path else None
        return bool(self.path)

    # ------------------------------------------------------------ Mietspiegel
    def set_level(self, new, why=None):
        new = max(0, min(5, new))
        if new == self.level:
            return
        up = new > self.level
        self.level = new
        self.max_level = max(self.max_level, new)
        self.level_arrow = ("up" if up else "down", self.t + 2.0)
        self.unseen = 0.0
        if why:
            self._popup(why, self.x, self.y - 56, (255, 120, 140) if up else (120, 255, 160), 18, 1.5)
        if up and new >= SHARK_LEVEL and not self.shark_warned:
            self.shark_warned = True
            self.banner = ("WARNUNG", "MIETENHAI IM KIEZ", self.t, 2.6)
            self.news("WARNUNG: Mietenhai im Kiez gesichtet. Poller bereithalten.")
        if new < SHARK_LEVEL:
            self.shark_warned = False
        if new >= 5 and self.state == "play":
            self.rausmod = True
            self._flash((230, 30, 60), 0.5)
            self.shake = 14
            self._freeze(0.6)
            self.path = []
            self.news("Wieder eine WG rausmodernisiert. BETONGOLD jubelt, der Kiez nicht.")
            self.game_over("Rausmodernisiert!")

    def caught(self, mob):
        if self.t < self.invuln_until or self.hidden:
            return
        self.counts["erwischt"] += 1
        self.invuln_until = self.t + INVULN_SECONDS
        self.stun_until = self.t + STUN_SECONDS
        self.path = []
        self.shake = 10
        self._freeze(0.12)
        self._flash((255, 60, 90), 0.2)
        text = {"bot": "MIETERHÖHUNG!", "drone": "GESCANNT!", "shark": "INDEX-MIETE!"}[mob.kind]
        self._burst(self.x, self.y, 16, [RED, WHITE, K.SUN], speed=260)
        if mob.kind == "drone":
            self.mobs.remove(mob)
        else:
            mob.stun_until = self.t + (3.0 if mob.kind == "shark" else 2.0)
        self.set_level(self.level + 1, text)

    # ------------------------------------------------------------ input
    def tap(self, x, y):
        self.tap_pos = (x, y)
        if NO_TAP.collidepoint(x, y):
            return None  # emergency-exit corner: never reacts, in any state
        if self.state == "over" and self.bilanz:
            if self.last_tick - self.end_at >= BILANZ_TAP_DELAY:
                self.bilanz = False
                # the Bestenliste's NOCHMAL / MENÜ sit right where "Weiter" was: restart party_games'
                # tap delay so a double tap doesn't skip the list (and the name entry)
                self.over_at = self.last_tick
            return None
        if self.state == "ready" and y < 144:
            return None
        return super().tap(x, y)

    def start(self):
        self.t = 0.0
        self.schicht = 0.0
        self.next_mission_t = 0.4
        self.news("Schichtbeginn! Liebe Nachbar*innen: Der Kiez gehört uns.")

    def play_tap(self):
        x, y = self.tap_pos
        if self.paint is not None:
            self._paint_tap(x, y, tap=True)
            return
        if BELL_RECT.collidepoint(x, y):
            self._press("bell")
            self.ring()
            return
        if ACT_RECT.collidepoint(x, y):
            self._press("act")
            self.action()
            return
        if not VIEW.collidepoint(x, y) or MINI.inflate(8, 8).collidepoint(x, y):
            return
        if self.hidden:
            self.leave_spaeti()
        if self.arrow_rect and self.arrow_rect.collidepoint(x, y) and self.mission:
            self.route_to_tile(tile_of(*self.mission["target"]))
            return
        wx, wy = self.to_world(x, y)
        self.route_to_tile(tile_of(wx, wy))

    def drag(self, x, y):
        if self.state == "play" and self.paint is not None:
            self._paint_tap(x, y, tap=False)

    # ------------------------------------------------------------ context action
    def action_label(self):
        """(label, sub, enabled, kind) of the AKTION button right now."""
        if self.hidden:
            return "RAUS", "weiterfahren", True, "raus"
        if self.paint is not None:
            return "MALEN", "auf die Wand!", False, None
        m = self.mission
        if m:
            k, ph = m["kind"], m["phase"]
            if k == "rad" and ph == "find" and self._near(m["target"]):
                return "KAPERN!", f"Schloss {m['lock']}/3", True, "kapern"
            if k == "suppe" and ph == "pickup" and self._near(m["target"]):
                return "AUFLADEN", "Suppe einladen", True, "aufladen"
            if k == "kran" and ph == "bolts":
                for i, (b, done) in enumerate(zip(m["bolts"], m["loose"])):
                    if not done and self._near(tile_center(*b)):
                        return "LOCKERN", f"Schraube {sum(m['loose']) + 1}/3", True, ("lockern", i)
            if k == "kran" and ph == "tip" and any(self._near(tile_center(*b)) for b in m["bolts"]):
                return "KIPPEN!", "Kran umlegen", True, "kippen"
            if k == "malen" and ph == "go" and self._near(m["target"]):
                return "MALEN", "paint.exe", True, "malen"
        if self.level > 0:  # at 0 hiding would only cost a Mate: keep NAVI on the button
            for door in self.city.spaeti_doors:
                if self._near(tile_center(*door)):
                    return "ABTAUCHEN", "Eine Mate, bitte", True, ("spaeti", door)
        if m and m.get("target"):
            return "NAVI", "Route zum Ziel", True, "navi"
        return "NAVI", "kein Ziel", False, None

    def _near(self, pos, r=NEAR):
        return (self.x - pos[0]) ** 2 + (self.y - pos[1]) ** 2 <= r * r

    def action(self):
        label, _, enabled, kind = self.action_label()
        if not enabled:
            return
        m = self.mission
        if kind == "raus":
            self.leave_spaeti()
        elif kind == "navi":
            self.route_to_tile(tile_of(*m["target"]))
        elif kind == "kapern":
            m["lock"] += 1
            self.path = []
            self.shake = 4
            tx, ty = m["rack"]
            self._burst(tx, ty, 10, [K.SUN, WHITE, SCOOT], speed=220, size=4)
            if m["lock"] >= 3:
                self._freeze(0.2)
                self.shake = 8
                self._flash(WHITE, 0.15)
                self.wordart = ("BEFREIT!", self.t, 52)
                self._burst(tx, ty, 30, [SCOOT, K.PINK, WHITE, K.SUN], speed=320)
                self.counts["rad"] += 1
                m["phase"] = "bring"
                m["target"] = tile_center(*HAUSPROJEKT_DOOR)
                m["text"] = "Lastenrad ins Hausprojekt bringen!"
                self.news("ROLLKAPITAL vermisst ein Lastenrad. Der Kiez nicht.")
                self.set_level(self.level + 1, "Mietspiegel +1")
            else:
                self._popup(f"KNACK! {m['lock']}/3", tx, ty - 40, WHITE, 18, 0.8)
        elif kind == "aufladen":
            self.path = []
            m["phase"] = "deliver"
            m["temp"] = SOUP_START
            m["target"] = tile_center(*m["dest"])
            m["text"] = soup_text(m["place"])
            self._burst(self.x, self.y - 10, 10, [WHITE, (230, 230, 240)], speed=90, g=-80)
            self._popup("Suppe an Bord!", self.x, self.y - 40, WHITE, 18)
        elif isinstance(kind, tuple) and kind[0] == "lockern":
            i = kind[1]
            m["loose"][i] = True
            self.path = []
            bx, by = tile_center(*m["bolts"][i])
            self.shake = 5
            self._burst(bx, by, 14, [(200, 200, 215), K.SUN, WHITE], speed=240, size=4)
            n = sum(m["loose"])
            self._popup(f"KNARZ! {n}/3", bx, by - 36, WHITE, 18)
            if n == 3:
                m["phase"] = "tip"
                m["text"] = "3/3 Schrauben locker: Kran KIPPEN!"
            else:
                m["text"] = f"LUXUS-LOFTS-Kran: {n}/3 Schrauben locker"
                m["target"] = self._next_bolt(m)
        elif kind == "kippen":
            self.topple()
        elif kind == "malen":
            self.path = []
            self.open_paint()
        elif isinstance(kind, tuple) and kind[0] == "spaeti":
            self.enter_spaeti(kind[1])

    def ring(self):
        if self.t < self.bell_cd_until:
            return
        self.bell_cd_until = self.t + 2.5
        self.bell_ring_until = self.t + 0.6
        self._popup("KLING KLING!", self.x, self.y - 44, K.SUN, 18, 0.8)
        for p in self.peds:
            if (p.x - self.x) ** 2 + (p.y - self.y) ** 2 < 130 ** 2:
                p.hop_until = self.t + 0.5
        for mob in self.mobs:
            if mob.kind == "bot" and (mob.x - self.x) ** 2 + (mob.y - self.y) ** 2 < 150 ** 2:
                mob.stun_until = max(mob.stun_until, self.t + 1.8)
                self._popup("?!", mob.x, mob.y - 30, WHITE, 20, 0.9)

    # ------------------------------------------------------------ Späti
    def enter_spaeti(self, door):
        self.hidden = door
        self.path = []
        self.x, self.y = tile_center(*door)
        self.hide_next_drop = self.t + HIDE_DROP_SECONDS
        self.counts["mate"] += 1
        self.bubble = (["Eine Mate, bitte."], (self.x, self.y), self.t + 2.2)
        if self.score >= 100:
            self.add_cash(-100, self.x, self.y)
        else:
            self._popup("Geht aufs Haus!", self.x, self.y - 30, WHITE, 18)

    def leave_spaeti(self):
        self.hidden = None
        self.invuln_until = max(self.invuln_until, self.t + 1.0)

    # ------------------------------------------------------------ missions
    def _random_tile(self, lo, hi, ok=None):
        bt = self.bike_tile()
        cands = [t for t in self.city.car if lo <= abs(t[0] - bt[0]) + abs(t[1] - bt[1]) <= hi and (ok is None or ok(t))]
        return self.rng.choice(sorted(cands))

    def _walk_side(self, tile):
        """A sidewalk tile next to a road tile (where a rack can stand), or None (crossings, bridges)."""
        return next(((tile[0] + dx, tile[1] + dy) for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                     if self.city.at(tile[0] + dx, tile[1] + dy) == WALK), None)

    def _next_bolt(self, m):
        open_bolts = [b for b, done in zip(m["bolts"], m["loose"]) if not done]
        b = min(open_bolts, key=lambda b: (tile_center(*b)[0] - self.x) ** 2 + (tile_center(*b)[1] - self.y) ** 2)
        return tile_center(*b)

    def new_mission(self, kind=None):
        if kind is None:
            if self.missions_started == 0:
                kind = "rad"
            else:
                if not self.mission_bag:
                    self.mission_bag = ["suppe", "rad", "kran", "malen", "pfand"]
                    self.rng.shuffle(self.mission_bag)
                kind = self.mission_bag.pop()
                if kind == "kran" and len(self.toppled) == len(SITES):
                    kind = "pfand"
                if kind == "malen" and len(self.painted) == len(self.city.billboards):
                    kind = "suppe"
                if self.mission and kind == self.mission["kind"] and self.mission_bag:
                    kind = self.mission_bag.pop()
        self.missions_started += 1
        m = {"kind": kind, "born": self.schicht}
        if kind == "rad":
            # only road tiles with a sidewalk next to them: on a crossing the rack stood on the road
            # and the bike parked right on top of it
            tile = self._random_tile(10, 20, ok=lambda t: self._walk_side(t) is not None)
            side = self._walk_side(tile)
            m.update(phase="find", lock=0, target=tile_center(*tile), rack=tile_center(*side),
                     text="Lastenrad von ROLLKAPITAL befreien!", icon="ok")
        elif kind == "suppe":
            dest = self._soup_dest()
            m.update(phase="pickup", target=tile_center(*SOLI_DOOR), dest=dest, place=self.rng.choice(SOUP_PLACES),
                     text="Soli-Suppe in der SOLI-KÜCHE abholen", icon="heart")
        elif kind == "kran":
            site = min((s for s in SITES if s not in self.toppled),
                       key=lambda s: abs(s[0] * PER + 5 - self.bike_tile()[0]) + abs(s[1] * PER + 5 - self.bike_tile()[1]))
            bx, by = site
            bolts = [(bx * PER + 4, by * PER + 1), (bx * PER + PER, by * PER + 6), (bx * PER + 6, by * PER + PER)]
            m.update(phase="bolts", site=site, bolts=bolts, loose=[False] * 3, icon="power",
                     text="LUXUS-LOFTS-Kran: 3 Schrauben lockern")
            m["target"] = self._next_bolt(m)
        elif kind == "malen":
            free = [i for i in range(len(self.city.billboards)) if i not in self.painted]
            bt = self.bike_tile()
            i = min(free, key=lambda i: abs(abs(self.city.billboards[i][1][0] - bt[0]) + abs(self.city.billboards[i][1][1] - bt[1]) - 14))
            m.update(phase="go", board=i, target=tile_center(*self.city.billboards[i][1]), icon="note",
                     text="Werbung übermalen: " + ad_name(self.ads[i]))
        elif kind == "pfand":
            bt = self.bike_tile()
            tiles = self.rng.sample(sorted(t for t in self.city.car if 3 <= abs(t[0] - bt[0]) + abs(t[1] - bt[1]) <= 11), 6)
            m.update(phase="collect", bottles=[tile_center(*t) for t in tiles], got=0, icon="note",
                     text="Pfand sammeln: 0/6 Flaschen")
            m["target"] = self._nearest_bottle(m)
        self.mission = m
        self.banner = ("NEUE MISSION", m["text"], self.t, 2.0)

    def _soup_dest(self):
        bt = SOLI_DOOR
        cands = [t for t in self.city.car if 22 <= abs(t[0] - bt[0]) + abs(t[1] - bt[1]) <= 34]
        return self.rng.choice(cands)

    def _nearest_bottle(self, m):
        if not m["bottles"]:
            return None
        return min(m["bottles"], key=lambda b: (b[0] - self.x) ** 2 + (b[1] - self.y) ** 2)

    def complete_mission(self, reward, word, news):
        m = self.mission
        self.counts[m["kind"]] += 1 if m["kind"] != "rad" else 0
        self.add_cash(reward, self.x, self.y)
        self.wordart = (word, self.t, 48 if len(word) < 10 else 38)
        self._freeze(0.15)
        self.shake = max(self.shake, 6)
        self._burst(self.x, self.y, 36, [K.PINK, K.SUN, (120, 255, 160), WHITE, (160, 90, 230)], speed=340, life=1.0)
        self.news(news)
        self.mission = None
        self.next_mission_t = self.schicht + 1.6

    def fail_mission(self, why):
        self.banner = ("MISSION VERPASST", why, self.t, 2.0)
        self.mission = None
        self.next_mission_t = self.schicht + 1.6

    def topple(self):
        m = self.mission
        bx, by = m["site"]
        cx, cy = (bx * PER + 2) * TS + 84, (by * PER + 2) * TS + 84
        self.toppled.add(m["site"])
        self.topple_t[m["site"]] = self.t
        self.path = []
        self._freeze(0.35)
        self.shake = 16
        self._flash(WHITE, 0.3)
        for _ in range(30):  # dust
            a = self.rng.uniform(0, 2 * math.pi)
            r = self.rng.uniform(0, 70)
            self.parts.append([cx + math.cos(a) * r, cy + math.sin(a) * r, math.cos(a) * 60, math.sin(a) * 60, 0.0,
                               self.rng.uniform(0.8, 1.6), self.rng.choice([(210, 196, 180), (180, 160, 140)]), 14, -10.0])
        self._burst(cx, cy, 30, [(250, 200, 40), OUT, WHITE], speed=380, size=6, life=1.0, g=600)
        # pay first: if +2 means 5/5 the round ends right here, and the stored result must include the crane
        self.complete_mission(1500, "KIPPT!", "EILMELDUNG: Kran der LUXUS-LOFTS umgekippt. Hier entsteht: ein Gemeinschaftsgarten.")
        self.wordart = ("KIPPT!", self.t, 56)
        self.bubble = (["Hier entsteht:", "ein Gemeinschaftsgarten."], (cx, cy), self.t + 2.6)
        self.set_level(self.level + 2, "Mietspiegel +2")

    # ------------------------------------------------------------ paint.exe
    def _paint_layout(self):
        win = pygame.Rect(16, VIEW.y + 8, W - 32, VIEW.h - 16)
        inner = pygame.Rect(win.x + 8, win.y + 36, win.w - 16, win.h - 42)
        tools = pygame.Rect(inner.x, inner.y, inner.w, 46)
        canvas = pygame.Rect(inner.x + 6, tools.bottom + 10, inner.w - 12, 330)
        return win, inner, tools, canvas

    def open_paint(self):
        m = self.mission
        _, _, _, canvas = self._paint_layout()
        ad = pygame.Surface(canvas.size)
        ad.fill(WHITE)
        lines = self.ads[m["board"]]
        pygame.draw.rect(ad, GLASS, (24, 40, 110, canvas.h - 56))
        for y in range(44, canvas.h - 20, 12):
            pygame.draw.line(ad, (110, 180, 205), (24, y), (133, y))
        pygame.draw.rect(ad, OUT, (24, 40, 110, canvas.h - 56), 2)
        for i, ln in enumerate(lines):
            size = K.fit_size(ln, canvas.w - 170, sizes=(30, 26, 22, 18))
            K.t95(ad, ln, size, ((canvas.w + 140) // 2, 60 + i * 52), color=GOLD if i == 0 else OUT, anchor="center")
        K.t95(ad, "Investor*innen willkommen", 15, ((canvas.w + 140) // 2, canvas.h - 28), color=OUT, anchor="center", bold=False)
        mural = pygame.Surface(canvas.size)
        for i, c in enumerate(RAINBOW):
            pygame.draw.rect(mural, c, (0, i * canvas.h // 6, canvas.w, canvas.h // 6 + 1))
        sun = K.weather_icon("sun", 96)
        mural.blit(sun, (16, 16))
        K.t95(mural, "KIEZ", 44, (canvas.w - 30, 120), color=WHITE, anchor="topright")
        K.t95(mural, "BLEIBT!", 44, (canvas.w - 30, 176), color=WHITE, anchor="topright")
        K.heart(mural, (60, canvas.h - 60), 6, K.PINK)
        self.paint = {"ad": ad, "mural": mural, "comp": ad.copy(), "cells": set(), "done_at": None, "color": 5}

    def _paint_tap(self, x, y, tap):
        p = self.paint
        win, inner, tools, canvas = self._paint_layout()
        if tap and K.close_box(win).collidepoint(x, y):
            self.paint = None
            return
        if p["done_at"] is not None:
            return
        if tap and tools.collidepoint(x, y):
            p["color"] = max(0, min(7, (x - tools.x - 8) // 52))
            return
        if not canvas.collidepoint(x, y):
            return
        cw, ch = canvas.w / PAINT_COLS, canvas.h / PAINT_ROWS
        cx, cy = int((x - canvas.x) // cw), int((y - canvas.y) // ch)
        cells = [(cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)] if tap else [(cx, cy)]
        new = 0
        for c in cells:
            if 0 <= c[0] < PAINT_COLS and 0 <= c[1] < PAINT_ROWS and c not in p["cells"]:
                if not tap and new:
                    break
                p["cells"].add(c)
                new += 1
                r = pygame.Rect(int(c[0] * cw), int(c[1] * ch), int(cw) + 1, int(ch) + 1)
                p["comp"].blit(p["mural"], r, area=r)
        if new:
            self.score += 20 * new
            col = (RAINBOW + [K.PINK, WHITE])[p["color"]]
            for _ in range(6):  # screen-space splashes (10th field marks them as such)
                a = self.rng.uniform(0, 2 * math.pi)
                v = self.rng.uniform(60, 180)
                self.parts.append([x, y, math.cos(a) * v, math.sin(a) * v - 60, 0.0, 0.5, self.rng.choice([col, WHITE]), 5, 300.0, "screen"])
        if len(p["cells"]) == PAINT_COLS * PAINT_ROWS:
            p["done_at"] = self.t

    # ------------------------------------------------------------ simulation
    def step(self, dt):
        self.t += dt
        self.ticker_off += 70 * dt
        if self.state == "ready":
            return
        self._step_fx(dt)
        if self.state == "over":
            return
        if self.t < self.freeze_until:
            return
        self.schicht += dt
        if self.schicht >= SCHICHT_SECONDS:
            self.path = []
            self.game_over(self.rng.choice(OVER_TIME))
            return
        if self.paint is not None:
            p = self.paint
            if p["done_at"] is not None and self.t - p["done_at"] > 0.9:
                m = self.mission
                self.painted.add(m["board"])
                self.paint = None
                self.complete_mission(400, "KIEZ BLEIBT!", "Werbefläche verschwunden. Wand jetzt schöner. ROLLKAPITAL prüft rechtliche Schritte.")
                self.set_level(self.level + 1, "Mietspiegel +1")  # after paying: 5/5 here ends the round
            return
        if self.mission is None and self.schicht >= self.next_mission_t:
            self.new_mission()
        self._step_bike(dt)
        self._step_places()
        self._step_mission(dt)
        self._step_mobs(dt)
        if self.state != "play":  # caught at 4/5: the round ended, Mietspiegel stays at 5
            return
        self._step_peds(dt)
        self._step_level(dt)
        # camera: smooth follow
        k = min(1.0, dt * 5)
        self.cam[0] += (self.x - VIEW.w / 2 - self.cam[0]) * k
        self.cam[1] += (self.y - VIEW.h / 2 + 30 - self.cam[1]) * k
        self._clamp_cam()

    def _step_fx(self, dt):
        for p in self.parts:
            p[4] += dt
            p[3] += p[8] * dt
            p[0] += p[2] * dt
            p[1] += p[3] * dt
        self.parts = [p for p in self.parts if p[4] < p[5]]
        for p in self.popups:
            p[3] += dt
            p[2] -= 40 * dt
        self.popups = [p for p in self.popups if p[3] < p[4]]
        self.shake *= max(0.0, 1 - dt * 8)
        if self.shake < 0.5:
            self.shake = 0.0
        if self.ticker_queue and self.ticker_off > self._ticker_w() + 40:
            self.ticker_text = self.ticker_queue.pop(0)
            self.ticker_off = 0.0
        elif self.ticker_off > self._ticker_w() + 360:
            self.ticker_text = self._ticker_line()
            self.ticker_off = 0.0

    def _step_bike(self, dt):
        if self.hidden or self.t < self.stun_until:
            return
        step = BIKE_SPEED * dt
        while self.path and step > 0:
            px, py = self.path[0]
            d = math.hypot(px - self.x, py - self.y)
            if d <= step:
                self.x, self.y = px, py
                self.path.pop(0)
                step -= d
            else:
                self.heading = math.degrees(math.atan2(px - self.x, -(py - self.y)))
                self.x += (px - self.x) / d * step
                self.y += (py - self.y) / d * step
                step = 0
        if not self.path:
            self.target = None

    def _step_places(self):
        """Hausprojekt and Kiezblock bollards lower the Mietspiegel."""
        if self.level > 0 and self.t >= self.hp_cooldown_until and self._near(tile_center(*HAUSPROJEKT_DOOR), 44):
            self.hp_cooldown_until = self.t + HAUSPROJEKT_COOLDOWN
            self.wordart = ("SOLIDARITÄT!", self.t, 40)
            self._burst(self.x, self.y, 24, [K.PINK, (90, 200, 200), K.SUN, (160, 100, 230)], speed=300)
            self.set_level(self.level - 2, "Hausprojekt: -2")
            self.news("Hausprojekt hält zusammen. Hausverwaltung verliert die Spur.")
        bt = self.bike_tile()
        if bt in self.city.poller and self.level > 0 and self.t >= self.poller_cd.get(bt, 0.0):
            for pair in POLLER:
                if bt in pair:
                    for t in pair:
                        self.poller_cd[t] = self.t + POLLER_COOLDOWN
            self._popup("KIEZBLOCK!", self.x, self.y - 70, (120, 255, 160), 24, 1.2)
            self._burst(self.x, self.y, 14, [WHITE, RED, (120, 255, 160)], speed=220)
            self.set_level(self.level - 1, "Mietspiegel -1")

    def _step_mission(self, dt):
        m = self.mission
        if m is None:
            return
        k = m["kind"]
        if k == "rad" and m["phase"] == "bring" and self._near(m["target"], 44):
            self.complete_mission(800, "ANGEKOMMEN!", "Ein Lastenrad mehr für alle. ROLLKAPITAL-Aktie fällt um 0,0001 %.")
        elif k == "suppe" and m["phase"] == "deliver":
            m["temp"] -= SOUP_DROP * dt
            if self._near(m["target"], 44):
                reward = 400 + int(m["temp"]) * 10
                self.complete_mission(reward, "LECKER!", f"Soli-Suppe mit {int(m['temp'])} °C angekommen. Nachbar*innen satt und solidarisch.")
            elif m["temp"] < SOUP_MIN:
                self.fail_mission("Suppe kalt. Nächstes Mal schneller!")
        elif k == "pfand":
            for b in list(m["bottles"]):
                if self._near(b, 30):
                    m["bottles"].remove(b)
                    m["got"] += 1
                    self.add_cash(50, b[0], b[1])
                    self._burst(b[0], b[1], 8, [(60, 160, 80), WHITE], speed=160, size=4)
            m["text"] = f"Pfand sammeln: {m['got']}/6 Flaschen"
            m["target"] = self._nearest_bottle(m)
            left = PFAND_SECONDS - (self.schicht - m["born"])
            if not m["bottles"]:
                self.complete_mission(300, "PFANDTASTISCH!", "Pfand-Kollektiv meldet Rekord. Getränkemarkt-Konzern meldet Fassungslosigkeit.")
            elif left <= 0:
                self.fail_mission("Pfand-Zeit vorbei. Die Flaschen finden andere.")
        elif k == "kran" and m["phase"] == "bolts":
            m["target"] = self._next_bolt(m)

    def _player_seeds(self):
        bt = self.bike_tile()
        if bt in self.city.car:
            return [bt]
        x, y = bt
        return [t for t in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if t in self.city.car]

    def _step_mobs(self, dt):
        if self.t >= self.next_field_t:
            self.next_field_t = self.t + FIELD_EVERY
            seeds = [] if self.hidden else self._player_seeds()
            self.field = self.city.car_field(seeds) if seeds else {}
        # spawn / despawn to match the level
        if self.t >= self.next_spawn_t:
            self.next_spawn_t = self.t + 1.2
            want = {"shark": 1 if self.level >= SHARK_LEVEL else 0, "bot": BOTS[self.level], "drone": DRONES[self.level]}
            for kind, n in want.items():
                have = [mb for mb in self.mobs if mb.kind == kind]
                if len(have) < n:
                    self._spawn(kind)
                    break
                if len(have) > n:
                    far = max(have, key=lambda mb: (mb.x - self.x) ** 2 + (mb.y - self.y) ** 2)
                    self.mobs.remove(far)
                    self._burst(far.x, far.y, 10, [(200, 200, 215), WHITE], speed=120)
                    if kind == "shark":
                        self.news("Mietenhai fährt beleidigt zum Golfplatz.")
                    break
        for mob in list(self.mobs):
            if self.t < mob.stun_until:
                continue
            if mob.kind == "drone":
                self._fly(mob, dt)
            else:
                self._drive(mob, dt)
            r = {"bot": 24, "drone": 24, "shark": 30}[mob.kind]
            if not self.hidden and (mob.x - self.x) ** 2 + (mob.y - self.y) ** 2 < r * r:
                self.caught(mob)
                if self.state != "play":
                    return

    def _spawn(self, kind):
        bt = self.bike_tile()
        view = pygame.Rect(self.cam[0] - 30, self.cam[1] - 30, VIEW.w + 60, VIEW.h + 60)
        lo, hi = (10, 16) if kind != "shark" else (12, 18)
        cands = [t for t in self.city.car if lo <= max(abs(t[0] - bt[0]), abs(t[1] - bt[1])) <= hi
                 and not view.collidepoint(tile_center(*t))]
        if not cands:
            return
        tx, ty = self.rng.choice(cands)
        self.mobs.append(Mob(kind, *tile_center(tx, ty)))

    def _fly(self, mob, dt):
        if self.hidden:
            tx, ty = self.x + math.cos(self.t + mob.phase) * 140, self.y + math.sin(self.t + mob.phase) * 140
        else:
            tx, ty = self.x, self.y
        d = math.hypot(tx - mob.x, ty - mob.y)
        if d > 1:
            s = min(d, mob.speed * dt)
            mob.x += (tx - mob.x) / d * s
            mob.y += (ty - mob.y) / d * s

    def _drive(self, mob, dt):
        step = mob.speed * dt
        cur = tile_of(mob.x, mob.y)
        # the shark is stuck exactly when the bike can't be reached by car (park path, Späti)
        mob.stuck = mob.kind == "shark" and not self.field
        if mob.stuck:
            step = 0
        for _ in range(4):
            if step <= 0:
                break
            if mob.way is None:
                mob.way = self._choose_way(mob)
                if mob.way is None:
                    break
            wx, wy = mob.way
            d = math.hypot(wx - mob.x, wy - mob.y)
            if d <= step:
                mob.x, mob.y = wx, wy
                mob.prev = cur
                cur = tile_of(wx, wy)
                mob.way = None
                step -= d
            else:
                mob.heading = math.degrees(math.atan2(wx - mob.x, -(wy - mob.y)))
                mob.x += (wx - mob.x) / d * step
                mob.y += (wy - mob.y) / d * step
                step = 0
        if mob.kind == "shark":
            near = (mob.x - self.x) ** 2 + (mob.y - self.y) ** 2 < 360 ** 2
            if mob.stuck and near and not mob.lost_counted:
                mob.lost_counted = True
                self.counts["hai"] += 1
                self.bubble = (["Kein Durchkommen?!"], mob, self.t + 1.8)
                self._popup("ABGEHÄNGT!", self.x, self.y - 60, (120, 255, 160), 22, 1.3)
                self.news("Kiezblock wirkt: Mietenhai steckt an Pollern fest.")
            elif not mob.stuck:
                # a new escape only counts once it really chased again for a while
                mob.chase_t += dt if near else 0.0
                if mob.chase_t > 3.0:
                    mob.lost_counted = False
            if mob.stuck:
                mob.chase_t = 0.0

    def _choose_way(self, mob):
        cur = tile_of(mob.x, mob.y)
        x, y = cur
        nbrs = [t for t in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if t in self.city.car]
        f = self.field
        if cur in f and f:
            here = f[cur]
            better = [t for t in nbrs if t in f and f[t] < here]
            if better:
                best = min(f[t] for t in better)
                return tile_center(*self.rng.choice([t for t in better if f[t] == best]))
            if here == 0:
                return (self.x, self.y) if mob.kind == "bot" and not self.hidden else None
            return None
        options = [t for t in nbrs if t != mob.prev] or nbrs
        if f:  # bike reachable but out of the field radius: head roughly towards it
            if options and self.rng.random() < 0.8:
                return tile_center(*min(options, key=lambda t: (tile_center(*t)[0] - self.x) ** 2 + (tile_center(*t)[1] - self.y) ** 2))
        elif mob.kind == "shark":
            return None  # no route to the bike (park path, Späti): it sits there and fumes
        return tile_center(*self.rng.choice(options)) if options else None

    def _step_peds(self, dt):
        cam = pygame.Rect(self.cam[0] - 100, self.cam[1] - 100, VIEW.w + 200, VIEW.h + 200)
        for p in self.peds:
            if not cam.collidepoint(p.x, p.y):
                continue
            if p.goal is None:
                tx, ty = tile_of(p.x, p.y)
                options = [d for d in ((1, 0), (-1, 0), (0, 1), (0, -1)) if self.city.at(tx + d[0], ty + d[1]) == WALK]
                if not options:
                    continue
                if p.dir not in options or self.ped_rng.random() < 0.15:
                    p.dir = self.ped_rng.choice(options)
                p.goal = tile_center(tx + p.dir[0], ty + p.dir[1])
            gx, gy = p.goal
            d = math.hypot(gx - p.x, gy - p.y)
            s = 22 * dt * (3 if self.t < p.hop_until else 1)
            if d <= s:
                p.x, p.y = gx, gy
                p.goal = None
            else:
                p.x += (gx - p.x) / d * s
                p.y += (gy - p.y) / d * s

    def _step_level(self, dt):
        if self.hidden:
            if self.level > 0 and self.t >= self.hide_next_drop:
                self.hide_next_drop = self.t + HIDE_DROP_SECONDS
                self.set_level(self.level - 1, "Mate wirkt: -1")
            return
        if self.level == 0:
            self.unseen = 0.0
            return
        close = any((mb.x - self.x) ** 2 + (mb.y - self.y) ** 2 < 260 ** 2 and not mb.stuck for mb in self.mobs)
        if close:
            self.unseen = 0.0
        else:
            self.unseen += dt
            if self.unseen >= LOSE_TRACK_SECONDS:
                self.set_level(self.level - 1, "Spur verloren: -1")
        # now and then a chaser says something
        if self.t >= self.next_bubble_t:
            self.next_bubble_t = self.t + self.rng.uniform(3.5, 6.0)
            vis = [mb for mb in self.mobs if VIEW.collidepoint(self.to_screen(mb.x, mb.y))]
            if vis:
                mb = self.rng.choice(vis)
                lines = {"bot": BOT_LINES, "shark": SHARK_LINES, "drone": DRONE_LINES}[mb.kind]
                self.bubble = ([self.rng.choice(lines)], mb, self.t + 1.8)

    # ------------------------------------------------------------ drawing
    def draw(self, surf):
        if self.state == "ready":
            self._draw_ready(surf)
            return
        ox = oy = 0
        if self.shake:
            ox, oy = random.uniform(-1, 1) * self.shake, random.uniform(-1, 1) * self.shake
        cam = pygame.Rect(int(self.cam[0] + ox), int(self.cam[1] + oy), VIEW.w, VIEW.h)
        cam.clamp_ip(pygame.Rect(0, 0, N * TS, N * TS))
        self._cx, self._cy = cam.x, cam.y
        surf.blit(self.city.surf, VIEW.topleft, area=cam)
        clip = surf.get_clip()
        surf.set_clip(VIEW)
        self._draw_world(surf, cam)
        surf.set_clip(clip)
        self._draw_overlays(surf)
        self._draw_hud(surf)
        self._draw_ticker(surf)
        self._draw_controls(surf)
        if self.paint is not None:
            self._draw_paint(surf)
        if self.flash and self.t < self.flash[1]:
            fl = _cached(("flash", self.flash[0]), lambda: self._make_flash(self.flash[0]))
            fl.set_alpha(int(180 * (self.flash[1] - self.t) / self.flash[2]))
            surf.blit(fl, VIEW.topleft)
        if self.state == "over":
            age = self.last_tick - self.end_at
            if age < 1.4:
                text = "RAUSMODERNISIERT!" if self.rausmod else "SCHICHT VORBEI!"
                K.wordart(surf, text, 38 if self.rausmod else 44, (W // 2, VIEW.y + 150), wave=6)
            elif self.bilanz:
                self._draw_bilanz(surf)
            else:
                self._draw_over(surf)

    def _make_flash(self, color):
        s = pygame.Surface(VIEW.size)
        s.fill(color)
        return s

    def game_over(self, text):
        super().game_over(text)
        self.end_at = self.last_tick  # over_at gets reset when the Bilanz is closed (see tap())
        self.bilanz = True
        self.paint = None

    def _ws(self, wx, wy):
        return int(wx - self._cx + VIEW.x), int(wy - self._cy + VIEW.y)

    def _put(self, surf, img, sh, wx, wy, sh_off=(3, 4)):
        sx, sy = self._ws(wx, wy)
        r = img.get_rect(center=(sx, sy))
        if sh is not None:
            surf.blit(sh, r.move(*sh_off))
        surf.blit(img, r)
        return r

    def _draw_world(self, surf, cam):
        vis = cam.inflate(160, 160)
        m = self.mission
        # gardens / toppled cranes / standing cranes
        for site in SITES:
            bx, by = site
            cx, cy = (bx * PER + 2) * TS + 84, (by * PER + 2) * TS + 84
            if not vis.collidepoint(cx, cy):
                continue
            if site in self.toppled:
                k = min(1.0, (self.t - self.topple_t.get(site, -9)) / 0.9)
                if k >= 0.6:
                    surf.blit(garden_sprite(), garden_sprite().get_rect(center=self._ws(cx, cy)))
                start = 90 * (by % 2)
                ease = k * k  # falls slowly, then fast
                img, sh = rotated("crane", crane_sprite(), start + (35 - start) * ease)
                sh_off = (int(5 + 20 * (1 - ease)), int(7 + 26 * (1 - ease)))  # high = long shadow
                self._put(surf, img, sh, cx + 20 * ease, cy + 30 * ease, sh_off)
            else:
                ang = 20 * math.sin(self.t * 0.4 + bx)
                if m and m["kind"] == "kran" and m["phase"] == "tip":
                    ang += math.sin(self.t * 18) * 4
                img, sh = rotated("crane", crane_sprite(), ang * 1.0 + 90 * (by % 2))
                self._put(surf, img, sh, cx, cy, (10, 14))
        # billboards
        for i, (tile, road) in enumerate(self.city.billboards):
            wx, wy = tile_center(*tile)
            if not vis.collidepoint(wx, wy):
                continue
            img = mural_sprite() if i in self.painted else billboard_sprite(self.ads[i], bg=(20, 20, 30) if i % 2 else WHITE,
                                                                             fg=(120, 255, 200) if i % 2 else RED)
            sx, sy = self._ws(wx, wy - 22)
            surf.blit(img, img.get_rect(center=(sx, sy)))
        # mission things
        if m:
            self._draw_mission_world(surf, vis, m)
        # pedestrians
        for p in self.peds:
            if vis.collidepoint(p.x, p.y):
                hop = int(abs(math.sin((p.hop_until - self.t) * 12)) * 10) if self.t < p.hop_until else 0
                img = ped_sprite(p.i)
                sx, sy = self._ws(p.x + (p.i % 3 - 1) * 6, p.y + (p.i % 2) * 6 - 3)
                surf.blit(img, img.get_rect(center=(sx, sy - hop)))
        # path + target
        if self.path and not self.hidden:
            prev = (self.x, self.y)
            for q in self.path:
                d = math.hypot(q[0] - prev[0], q[1] - prev[1])
                n = int(d // 16)
                for i in range(1, n + 1):
                    px = prev[0] + (q[0] - prev[0]) * i / n
                    py = prev[1] + (q[1] - prev[1]) * i / n
                    sx, sy = self._ws(px, py)
                    if VIEW.collidepoint(sx, sy):
                        pygame.draw.rect(surf, OUT, (sx - 3, sy - 3, 6, 6))
                        pygame.draw.rect(surf, WHITE, (sx - 2, sy - 2, 4, 4))
                prev = q
            if self.target:
                sx, sy = self._ws(*self.target)
                r = 14 + int(4 * math.sin(self.t * 6))
                pygame.draw.circle(surf, OUT, (sx, sy), r + 2, 4)
                pygame.draw.circle(surf, K.PINK, (sx, sy), r, 3)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    pygame.draw.line(surf, K.PINK, (sx + dx * (r - 6), sy + dy * (r - 6)), (sx + dx * (r + 8), sy + dy * (r + 8)), 3)
        # the bike
        cargo = "box"
        if m:
            cargo = {"suppe": "pot" if m["phase"] == "deliver" else "box", "pfand": "bottles", "malen": "paint",
                     "rad": "lime" if m["phase"] == "bring" else "box"}.get(m["kind"], "box")
        blink = 0 < self.invuln_until - self.t <= INVULN_SECONDS and int(self.t * 12) % 2 == 0
        if self.hidden:
            img, sh = rotated(("bike", cargo), bike_sprite(cargo), 90)
            self._put(surf, img, sh, self.x - 30, self.y - 4)
        elif not blink:
            img, sh = rotated(("bike", cargo), bike_sprite(cargo), self.heading)
            self._put(surf, img, sh, self.x, self.y)
        if m and m["kind"] == "suppe" and m["phase"] == "deliver" and not self.hidden:
            sx, sy = self._ws(self.x, self.y)
            for i in range(3):
                k = (self.t * 1.5 + i / 3) % 1
                pygame.draw.circle(surf, (250, 250, 255), (sx - 4 + int(math.sin(k * 6 + i) * 4), sy - 20 - int(k * 26)), 3 + int(k * 3))
        if self.t < self.bell_ring_until:
            sx, sy = self._ws(self.x, self.y)
            k = 1 - (self.bell_ring_until - self.t) / 0.6
            pygame.draw.circle(surf, K.SUN, (sx, sy), int(20 + k * 110), 3)
        # chasers
        frame = int(self.t * 10) % 2
        for mob in self.mobs:
            if not vis.collidepoint(mob.x, mob.y):
                continue
            stunned = self.t < mob.stun_until
            if mob.kind == "bot":
                wob = int(math.sin(self.t * 14 + mob.phase) * 2)
                img, sh = shadowed("bot", bot_sprite())
                r = self._put(surf, img, sh, mob.x, mob.y + wob)
            elif mob.kind == "shark":
                img, sh = rotated("suv", suv_sprite(), mob.heading)
                r = self._put(surf, img, sh, mob.x, mob.y, (4, 6))
                if mob.stuck or stunned:
                    for i in range(3):
                        k = (self.t * 1.2 + i / 3) % 1
                        pygame.draw.circle(surf, (230, 230, 240), (r.centerx - 10 + i * 10, r.top - int(k * 26)), 5 + int(k * 4))
            else:
                bob = int(math.sin(self.t * 5 + mob.phase) * 4)
                img, sh = shadowed(("drone", frame), drone_sprite(frame))
                sx, sy = self._ws(mob.x, mob.y)
                surf.blit(sh, sh.get_rect(center=(sx + 10, sy + 18)))
                r = img.get_rect(center=(sx, sy - 8 + bob))
                surf.blit(img, r)
                if not self.hidden:  # scan cone towards the bike
                    pygame.draw.line(surf, DRONE, r.center, (r.centerx, r.bottom + 6), 2)
            if stunned or (self.hidden and mob.kind == "bot"):
                otext(surf, "?", 20, WHITE, (r.right + 4, r.top - 6))
        # particles + popups
        for p in self.parts:
            if len(p) > 9:
                continue
            k = 1 - p[4] / p[5]
            s = max(2, int(p[7] * (0.5 + 0.5 * k)))
            sx, sy = self._ws(p[0], p[1])
            if p[7] >= 10:
                pygame.draw.circle(surf, p[6], (sx, sy), s)
            else:
                surf.fill(p[6], (sx - s // 2, sy - s // 2, s, s))
        for text, x, y, age, life, color, size in self.popups:
            sx, sy = self._ws(x, y)
            otext(surf, text, size, color, (sx, sy))

    def _draw_mission_world(self, surf, vis, m):
        k = m["kind"]
        pulse = int(abs(math.sin(self.t * 4)) * 8)
        if k == "rad" and m["phase"] == "find":
            tx, ty = m["rack"]
            for i in range(4):
                img, sh = shadowed("scooter", scooter_sprite())
                self._put(surf, img, sh, tx - 30 + i * 14, ty + 4)
            shake = int(math.sin(self.t * 40) * 2) if m["lock"] else 0
            img, sh = shadowed("lockedbike", locked_bike_sprite())
            r = self._put(surf, img, sh, tx + 34 + shake, ty)
            pygame.draw.rect(surf, OUT, (r.centerx - 6, r.centery - 2, 12, 10))  # padlock
            pygame.draw.rect(surf, K.SUN, (r.centerx - 5, r.centery - 1, 10, 8))
            pygame.draw.arc(surf, OUT, (r.centerx - 5, r.centery - 10, 10, 12), 0, math.pi, 2)
            # label on the far side of the rack, never on the road where the bike stops to KAPERN
            above = m["rack"][1] < m["target"][1]
            sx, sy = self._ws(tx, ty - 44 if above else ty + 44)
            _label_box(surf, "ROLLKAPITAL", (sx, sy), fg=(30, 40, 10), bg=SCOOT, size=15)
        elif k == "kran":
            for b, done in zip(m["bolts"], m["loose"]):
                sx, sy = self._ws(*tile_center(*b))
                pygame.draw.circle(surf, OUT, (sx, sy), 14)
                if done:
                    pygame.draw.circle(surf, (110, 220, 130), (sx, sy), 12)
                    pygame.draw.lines(surf, WHITE, False, [(sx - 6, sy), (sx - 1, sy + 5), (sx + 7, sy - 5)], 3)
                else:
                    pygame.draw.circle(surf, (200, 200, 215), (sx, sy), 12)
                    for a in range(6):
                        ang = a * math.pi / 3 + self.t
                        pygame.draw.circle(surf, OUT, (sx + int(math.cos(ang) * 8), sy + int(math.sin(ang) * 8)), 2)
                    pygame.draw.circle(surf, OUT, (sx, sy), 4)
        elif k == "pfand":
            for bx, by in m["bottles"]:
                img, sh = shadowed("bottle", bottle_sprite())
                self._put(surf, img, sh, bx, by - pulse // 2)
        if m.get("target") and not (k == "pfand"):
            sx, sy = self._ws(*m["target"])
            pts = [(sx, sy - 22 - pulse), (sx - 12, sy - 40 - pulse), (sx + 12, sy - 40 - pulse)]
            pygame.draw.polygon(surf, OUT, [(x + 2, y + 2) for x, y in pts])
            pygame.draw.polygon(surf, K.PINK, pts)
            pygame.draw.polygon(surf, OUT, pts, 2)
            if k == "suppe" and m["phase"] == "deliver":
                _label_box(surf, m["place"], (sx, sy - 58 - pulse), size=15, area=VIEW)

    def _banner_lines(self):
        """The mission/warning banner's text lines (1, or 2 if it doesn't fit at 15 px) or None."""
        if not (self.banner and self.t - self.banner[2] < self.banner[3] and self.state == "play"):
            return None
        text = self.banner[1]
        if K.font(15).size(text)[0] <= BANNER_TEXT_W:
            return [text]
        return K.wrap(text, 15, BANNER_TEXT_W)[:2]

    def _banner_rect(self):
        lines = self._banner_lines()
        if lines is None:
            return None
        return pygame.Rect(108, VIEW.y + 8, W - 116, 66 if len(lines) == 1 else 88)

    def _draw_overlays(self, surf):
        m = self.mission
        self.arrow_rect = None
        self.arrow_label = None
        self.bubble_rect = None
        # minimap
        K.bevel(surf, MINI, sunken=True)
        surf.blit(self.city.mini, (MINI.x + 2, MINI.y + 2))
        k = 88 / (N * TS)
        pygame.draw.rect(surf, WHITE, (MINI.x + 2 + self._cx * k, MINI.y + 2 + self._cy * k, VIEW.w * k, VIEW.h * k), 1)
        dots = [(tile_center(*HAUSPROJEKT_DOOR), (90, 220, 140))]
        if m and m.get("target"):
            dots.append((m["target"], K.PINK))
        dots += [((mb.x, mb.y), RED) for mb in self.mobs if mb.kind == "shark"]
        dots.append(((self.x, self.y), WHITE))
        for (wx, wy), col in dots:
            c = (int(MINI.x + 2 + wx * k), int(MINI.y + 2 + wy * k))
            pygame.draw.circle(surf, OUT, c, 4)
            pygame.draw.circle(surf, col, c, 3)
        # speech bubble
        if self.bubble and self.t < self.bubble[2] and self.state == "play":
            lines, who, _ = self.bubble
            wx, wy = (who.x, who.y) if isinstance(who, Mob) else who
            if isinstance(who, Mob) and who not in self.mobs:
                self.bubble = None
            else:
                tx, ty = self._ws(wx, wy - 20)
                w = max(K.font(15).size(ln)[0] for ln in lines) + 22
                h = 14 + 23 * len(lines)
                r = pygame.Rect(0, 0, w, h)
                r.midbottom = (tx + 30, ty - 26)
                banner = self._banner_rect()
                top = banner.bottom + 6 if banner else VIEW.y + 4
                r.clamp_ip(pygame.Rect(104, top, W - 108, VIEW.bottom - 4 - top))
                if r.collidepoint(tx, ty):  # no room above the speaker: hang the bubble below it
                    r.top = min(ty + 30, VIEW.bottom - 4 - h)
                K.speech(surf, r, lines, (tx, ty), size=15)
                self.bubble_rect = r
        # banners: mission / warning
        lines = self._banner_lines()
        if lines is not None:
            title, text, born, secs = self.banner
            win = self._banner_rect()
            inner = K.dialog(surf, win, title, icon="power" if title == "WARNUNG" else "note", buttons=None)
            col = K.F_LATE if title in ("WARNUNG", "MISSION VERPASST") else K.F_INK
            if title == "WARNUNG" and int(self.t * 6) % 2:
                col = K.F_ACCENT
            if len(lines) == 1:
                size = K.fit_size(text, BANNER_TEXT_W, sizes=(17, 16, 15))
                K.t95(surf, text, size, (inner.centerx, inner.centery + 1), color=col, anchor="center")
            else:
                for i, ln in enumerate(lines):
                    K.t95(surf, ln, 15, (inner.centerx, inner.centery + 1 + (i * 2 - 1) * 11), color=col, anchor="center")
        # target arrow last: on top of bubbles (it moves below the banner by itself)
        if m and m.get("target") and self.state == "play":
            sx, sy = self._ws(*m["target"])
            if not VIEW.inflate(-60, -60).collidepoint(sx, sy):
                self._edge_arrow(surf, sx, sy, m["target"])
        if self.hidden and self.state == "play":
            _label_box(surf, "Untergetaucht. Mate läuft.", (W // 2 + 40, VIEW.bottom - 24), size=15)
        if self.wordart and self.t - self.wordart[1] < 1.3 and self.state == "play":
            text, born, size = self.wordart
            age = self.t - born
            pop = 6 if age < 0.12 else 0
            K.wordart(surf, text, size + pop, (W // 2 + 30, VIEW.y + 135 - int(age * 14)), wave=5)

    def _edge_arrow(self, surf, sx, sy, target):
        cx, cy = VIEW.center
        ang = math.atan2(sy - cy, sx - cx)
        inner = VIEW.inflate(-70, -70)
        t = min(abs((inner.w / 2) / math.cos(ang)) if math.cos(ang) else 9e9,
                abs((inner.h / 2) / math.sin(ang)) if math.sin(ang) else 9e9)
        ax, ay = cx + math.cos(ang) * t, cy + math.sin(ang) * t
        if ax < 130 and ay < MINI.bottom + 40:  # keep it out of the minimap / emergency corner
            ax = 130
        banner = self._banner_rect()
        if banner and banner.inflate(40, 40).collidepoint(ax, ay):  # not hidden under the mission banner
            ay = banner.bottom + 30
        pts = [(ax + math.cos(ang) * 22, ay + math.sin(ang) * 22),
               (ax + math.cos(ang + 2.4) * 18, ay + math.sin(ang + 2.4) * 18),
               (ax + math.cos(ang - 2.4) * 18, ay + math.sin(ang - 2.4) * 18)]
        pygame.draw.polygon(surf, OUT, [(x + 2, y + 2) for x, y in pts])
        pygame.draw.polygon(surf, K.PINK, pts)
        pygame.draw.polygon(surf, OUT, pts, 2)
        meters = int(math.hypot(target[0] - self.x, target[1] - self.y) * 0.4 / 10) * 10
        img = _label_img(f"Ziel {meters} m", K.F_INK, K.F_TIP, 15)
        # label next to the arrow (towards the centre), never on top of it
        dist = 30 + abs(math.cos(ang)) * img.get_width() / 2 + abs(math.sin(ang)) * img.get_height() / 2
        r = img.get_rect(center=(int(ax - math.cos(ang) * dist), int(ay - math.sin(ang) * dist)))
        top = banner.bottom + 4 if banner else VIEW.y + 8
        r.clamp_ip(pygame.Rect(104, top, W - 112, VIEW.bottom - 8 - top))
        surf.blit(img, r)
        self.arrow_label = r
        self.arrow_at = (int(ax), int(ay))
        self.arrow_rect = pygame.Rect(0, 0, 70, 70)
        self.arrow_rect.center = (int(ax), int(ay))
        self.arrow_rect.union_ip(r)

    def _draw_hud(self, surf):
        left = max(0, SCHICHT_SECONDS - self.schicht)
        m = self.mission
        thermo = None
        if m and m["kind"] == "suppe" and m["phase"] == "deliver":
            thermo = int(m["temp"])
        mtext = m["text"] if m else "Warte auf die nächste Mission..."
        if m and m["kind"] == "pfand":
            mtext += f" ({max(0, int(PFAND_SECONDS - (self.schicht - m['born'])))} s)"
        arrow = self.level_arrow[0] if self.level_arrow and self.t < self.level_arrow[1] else None
        key = (self.level, self.score, int(math.ceil(left)), thermo, mtext, arrow, m["icon"] if m else "note")
        if key != self._hud_key:
            self._hud_key = key
            if self._hud is None:
                self._hud = pygame.Surface(HUD.size).convert() if pygame.display.get_surface() else pygame.Surface(HUD.size)
            s = self._hud
            K.bevel(s, pygame.Rect(0, 0, *HUD.size))
            K.t95(s, "MIETSPIEGEL", 15, (8, 5))
            for i in range(5):
                s.blit(house_pip(i < self.level, 26), (8 + i * 29, 25))
            if arrow:
                x, y = 160, 38
                pts = [(x, y - 9), (x + 9, y + 6), (x - 9, y + 6)] if arrow == "up" else [(x, y + 9), (x + 9, y - 6), (x - 9, y - 6)]
                pygame.draw.polygon(s, K.F_LATE if arrow == "up" else (30, 150, 80), pts)
                pygame.draw.polygon(s, OUT, pts, 1)
            box = pygame.Rect(184, 4, 120, 46)
            K.bevel(s, box, sunken=True, face=K.F_PAPER)
            K.t95(s, "Kiezkasse", 15, (box.x + 6, box.y + 3), color=K.F_DARK, bold=False)
            cash = fmt_eur(self.score)
            K.t95(s, cash, K.fit_size(cash, box.w - 10, sizes=(18, 16, 15)), (box.right - 6, box.bottom - 3), anchor="bottomright", color=K.F_ACCENT)
            tbox = pygame.Rect(310, 4, 162, 46)
            if thermo is None:
                K.bevel(s, tbox, sunken=True, face=K.CLOCK_OFF)
                K.t95(s, "Schicht", 15, (tbox.x + 6, tbox.y + 3), color=(170, 140, 210), bold=False)
                sec = int(math.ceil(left))
                K.t95(s, f"{sec // 60}:{sec % 60:02d}", 22, (tbox.right - 8, tbox.bottom - 2), anchor="bottomright",
                      color=K.CLOCK_ON if left > 20 else (255, 110, 130))
            else:
                K.bevel(s, tbox, sunken=True, face=K.F_PAPER)
                K.t95(s, f"Suppe {thermo}°C", 15, (tbox.x + 6, tbox.y + 3), color=K.F_ACCENT if thermo > 45 else K.F_LATE)
                sec = int(math.ceil(left))
                K.t95(s, f"{sec // 60}:{sec % 60:02d}", 15, (tbox.right - 6, tbox.y + 3), anchor="topright", color=K.F_DARK, bold=False)
                bar = pygame.Rect(tbox.x + 6, tbox.y + 22, tbox.w - 12, 20)
                K.bevel(s, bar, sunken=True, face=K.F_PAPER)
                frac = max(0.0, min(1.0, (thermo - SOUP_MIN) / (SOUP_START - SOUP_MIN)))
                fw = int((bar.w - 8) * frac)
                for i in range(0, fw, 2):
                    t = i / max(1, bar.w - 8)
                    pygame.draw.line(s, (int(90 + 160 * t), int(140 - 80 * t), int(230 - 180 * t)), (bar.x + 4 + i, bar.y + 4), (bar.x + 4 + i, bar.bottom - 5), 2)
            field = pygame.Rect(8, 54, W - 16, 30)
            K.bevel(s, field, sunken=True, face=K.F_TIP)
            s.blit(K.menu_icon(m["icon"] if m else "note", 20), (field.x + 6, field.y + 5))
            K.t95(s, mtext, K.fit_size(mtext, field.w - 40, sizes=(16, 15, 14, 13, 12)), (field.x + 32, field.centery), anchor="midleft")
        surf.blit(self._hud, HUD.topleft)

    def _ticker_w(self):
        return self._ticker_img().get_width()

    def _ticker_img(self):
        return _cached(("ticker", self.ticker_text), lambda: K.font(15).render(self.ticker_text, False, (255, 230, 90)))

    def _draw_ticker(self, surf):
        pygame.draw.rect(surf, (24, 12, 36), TICKER)
        pygame.draw.line(surf, K.F_SEL, TICKER.topleft, TICKER.topright, 2)
        tag = pygame.Rect(0, TICKER.y, 132, TICKER.h)
        clip = surf.get_clip()
        lane = pygame.Rect(tag.right + 4, TICKER.y, W - tag.right - 4, TICKER.h)
        surf.set_clip(lane)
        img = self._ticker_img()
        surf.blit(img, img.get_rect(midleft=(W - int(self.ticker_off), TICKER.centery + 1)))
        surf.set_clip(clip)
        pygame.draw.rect(surf, K.F_ACCENT, tag)
        K.t95(surf, "KIEZFUNK 161", 15, tag.center, color=WHITE, anchor="center")

    def _draw_controls(self, surf):
        label, sub, enabled, kind = self.action_label() if self.state == "play" else ("AKTION", "", False, None)
        pressed = self.pressed[0] if self.pressed and self.t < self.pressed[1] else None
        bell_ready = self.t >= self.bell_cd_until
        if self.paint is not None:
            hint = ("Tipp/wisch auf die", "Wand = malen")
        elif self.state != "play":
            hint = ("Schicht", "vorbei")
        elif self.hidden:
            hint = ("Bots suchen", "woanders")
        elif any(mb.kind == "shark" for mb in self.mobs):
            hint = ("Poller & Parks:", "Hai muss draußen")
        elif kind == "navi" or kind is None:
            hint = ("Tipp auf die Karte:", "dahin fahren")
        elif isinstance(kind, tuple) and kind[0] == "spaeti":
            hint = ("Späti: abtauchen,", "Mietspiegel sinkt")
        else:
            hint = ("Rad steht am Ziel:", "AKTION drücken!")
        key = (label, sub, enabled, hint, pressed, bell_ready)
        if key != self._ctrl_key:
            self._ctrl_key = key
            if self._ctrl is None:
                self._ctrl = pygame.Surface(CTRL.size).convert() if pygame.display.get_surface() else pygame.Surface(CTRL.size)
            s = self._ctrl
            K.bevel(s, pygame.Rect(0, 0, *CTRL.size))
            bell = BELL_RECT.move(0, -CTRL.y)
            K.button(s, bell, "", pressed=pressed == "bell")
            s.blit(bell_icon(36), (bell.centerx - 18, bell.y + 8))
            K.t95(s, "KLINGEL", 15, (bell.centerx, bell.bottom - 10), anchor="midbottom", color=K.F_INK if bell_ready else (150, 140, 175))
            act = ACT_RECT.move(0, -CTRL.y)
            hot = enabled and label != "NAVI"
            K.button(s, act, "", face=(255, 200, 230) if hot else None, pressed=pressed == "act")
            K.t95(s, label, K.fit_size(label, act.w - 16, sizes=(24, 22, 20, 18)), (act.centerx, act.y + 30),
                  anchor="center", color=K.F_ACCENT if enabled else (150, 140, 175))
            K.t95(s, sub, K.fit_size(sub, act.w - 12, sizes=(15, 14, 13)), (act.centerx, act.bottom - 12), anchor="midbottom", color=K.F_DARK, bold=False)
            mid = pygame.Rect(bell.right + 6, 12, act.x - bell.right - 12, 76)
            for i, ln in enumerate(hint):
                K.t95(s, ln, K.fit_size(ln, mid.w, sizes=(15, 14, 13, 12)), (mid.centerx, mid.y + 10 + i * 22), anchor="midtop", color=K.F_DARK, bold=i == 0)
        surf.blit(self._ctrl, CTRL.topleft)
        if self.state == "play" and enabled and label not in ("NAVI",) and int(self.t * 3) % 2 == 0:
            pygame.draw.rect(surf, K.PINK, ACT_RECT.inflate(6, 6), 3)

    def _draw_paint(self, surf):
        p = self.paint
        win, inner, tools, canvas = self._paint_layout()
        K.dialog(surf, win, "paint.exe - werbung.bmp", icon="note")
        K.bevel(surf, tools)
        for i, c in enumerate(RAINBOW + [K.PINK, WHITE]):
            r = pygame.Rect(tools.x + 8 + i * 52, tools.y + 4, 44, 38)
            K.bevel(surf, r, sunken=i == p["color"], face=c)
        K.bevel(surf, canvas.inflate(8, 8), sunken=True)
        surf.blit(p["comp"], canvas.topleft)
        n = len(p["cells"])
        total = PAINT_COLS * PAINT_ROWS
        pct = int(100 * n / total)
        K.t95(surf, f"Wand {pct}% bunt", 16, (inner.x + 4, canvas.bottom + 14))
        K.progress95(surf, pygame.Rect(inner.x + 168, canvas.bottom + 10, inner.w - 172, 26), n, total)
        K.t95(surf, "Tippen oder wischen = malen", 15, (inner.centerx, canvas.bottom + 52), anchor="midtop", color=K.F_DARK)
        K.t95(surf, "+0,20 € je Fleck · Kiez gegen Konzern", 15, (inner.centerx, inner.bottom - 6), anchor="midbottom", color=K.F_DARK, bold=False)
        for pp in self.parts:
            if len(pp) > 9:
                surf.fill(pp[6], (int(pp[0]) - 3, int(pp[1]) - 3, 6, 6))
        if p["done_at"] is not None:
            K.wordart(surf, "FERTIG!", 44, (canvas.x + 290, canvas.y + 62), wave=6)  # top right is free on the mural

    # ------------------------------------------------------------ start screen
    def _draw_ready(self, surf):
        if self._title_bg is None:
            bg = pygame.Surface((W, H))
            bg.blit(self.city.surf, (0, 0), area=pygame.Rect(30 * TS - W // 2, 16 * TS - 360, W, H))
            fog = pygame.Surface((W, H), pygame.SRCALPHA)
            fog.fill((40, 16, 70, 150))
            bg.blit(fog, (0, 0))
            big = pygame.transform.rotate(pygame.transform.scale(bike_sprite("paint"), (90, 162)), -20)
            shark = pygame.transform.rotate(pygame.transform.scale(suv_sprite(), (84, 140)), -20)
            self._title_art = (big, shark)
            self._title_bg = bg.convert() if pygame.display.get_surface() else bg
        surf.blit(self._title_bg, (0, 0))
        big, shark = self._title_art
        bob = int(math.sin(self.last_tick * 3) * 6)
        K.wordart(surf, "KIEZ", 64, (W // 2 + 40, 76), wave=6)
        K.wordart(surf, "KAPERN", 64, (W // 2 + 20, 152), wave=6)
        _label_box(surf, "Die Stadt gehört allen. Hol sie dir zurück.", (W // 2, 214), size=15)
        surf.blit(big, big.get_rect(center=(130, 330 + bob)))
        surf.blit(shark, shark.get_rect(center=(380, 360 - bob)))
        K.speech(surf, pygame.Rect(236, 236, 224, 58), ["INDEX-MIETE!", "INDEX-MIETE!"], (360, 300), size=15)
        win = pygame.Rect(22, 430, W - 44, 322)
        inner = K.dialog(surf, win, "start.exe", icon="games", buttons=None)
        play = K.button(surf, pygame.Rect(inner.x + 8, inner.y + 6, inner.w - 16, 70), "", face=(255, 200, 230))
        K.t95(surf, "LOSFAHREN", 26, (play.centerx, play.y + 26), anchor="center", color=K.F_ACCENT)
        K.t95(surf, "3-Minuten-Schicht im Kiez", 15, (play.centerx, play.bottom - 10), anchor="midbottom", color=K.F_DARK, bold=False)
        gb = pygame.Rect(inner.x + 4, play.bottom + 18, inner.w - 8, 148)
        K.groupbox(surf, gb, "So geht's")
        lines = [("Tipp auf die Karte: Rad fährt hin.", True), ("AKTION: kapern, kippen, malen.", False),
                 ("Mietspiegel 5/5 = rausmodernisiert!", True), ("Runter: Späti, Kiezblock, Hausprojekt.", False),
                 ("KLINGEL verwirrt Bots.", False)]
        for i, (ln, bold) in enumerate(lines):
            K.t95(surf, ln, K.fit_size(ln, gb.w - 20, sizes=(15, 14, 13)), (gb.x + 10, gb.y + 14 + i * 26),
                  color=K.F_LATE if i == 2 else K.F_INK, bold=bold)
        K.t95(surf, party_games.record_line(type(self)), 15, (inner.centerx, inner.bottom - 4), anchor="midbottom", color=K.F_DARK, bold=False)
        if int(self.last_tick * 2) % 2 == 0:
            otext(surf, self.READY_TEXT, 20, WHITE, (W // 2, 406))

    # ------------------------------------------------------------ Bilanz
    def _draw_bilanz(self, surf):
        fog = _cached("fog", lambda: self._make_fog())
        surf.blit(fog, (0, 0))
        win = pygame.Rect(18, 14, W - 36, H - 28)
        title = "kuendigung.txt" if self.rausmod else "bilanz.txt - Schicht vorbei!"
        inner = K.dialog(surf, win, title, icon="power" if self.rausmod else "stats", buttons=None)
        y = inner.y + 6
        if self.rausmod:
            surf.blit(warn_icon(48), (inner.x + 8, y + 4))
            K.t95(surf, "RAUSMODERNISIERT!", 22, (inner.x + 68, y + 4), color=K.F_LATE)
            K.t95(surf, "Deine WG wird jetzt", 16, (inner.x + 68, y + 34))
            K.t95(surf, "Co-Living mit Barista.", 16, (inner.x + 68, y + 56))
            y += 86
        K.t95(surf, "In die Kiezkasse:", 16, (inner.centerx, y), anchor="midtop")
        K.wordart(surf, fmt_eur(self.score), 48, (inner.centerx, y + 56), wave=4)
        gb = pygame.Rect(inner.x + 4, y + 104, inner.w - 8, 186)
        K.groupbox(surf, gb, "Umverteilt:")
        c = self.counts
        items = [(crane_sprite(), f"{c['kran']} Kran gekippt" if c["kran"] == 1 else f"{c['kran']} Kräne gekippt"),
                 (bottle_sprite(), f"{c['pfand']}x Pfand-Runde"),
                 (bike_sprite("pot"), f"{c['suppe']} Suppen warm" if c["suppe"] != 1 else "1 Suppe warm"),
                 (suv_sprite(), f"{c['hai']}x Hai abgehängt"),
                 (locked_bike_sprite(), f"{c['rad']} Räder befreit" if c["rad"] != 1 else "1 Rad befreit"),
                 (mural_sprite(), f"{c['malen']} Wände bunt" if c["malen"] != 1 else "1 Wand bunt"),
                 (bot_sprite(), f"{c['erwischt']}x erwischt"),
                 (None, f"{c['mate']}x Mate im Späti")]
        for i, (img, text) in enumerate(items):
            x = gb.x + 10 + (i % 2) * (gb.w // 2)
            yy = gb.y + 18 + (i // 2) * 42
            if img is not None:
                key = ("bil", id(img))
                sm = _cached(key, lambda img=img: pygame.transform.scale(img, (max(1, int(img.get_width() * 32 / max(img.get_size()))),
                                                                                  max(1, int(img.get_height() * 32 / max(img.get_size()))))))
                surf.blit(sm, sm.get_rect(center=(x + 16, yy + 16)))
            else:
                pygame.draw.rect(surf, (230, 150, 40), (x + 10, yy + 4, 12, 24))
                pygame.draw.rect(surf, OUT, (x + 10, yy + 4, 12, 24), 2)
            K.t95(surf, text, K.fit_size(text, gb.w // 2 - 50, sizes=(15, 14, 13)), (x + 38, yy + 16), anchor="midleft")
        y = gb.bottom + 12
        if self.rausmod:
            K.t95(surf, "Mietspiegel 5/5. Nächstes Mal: Späti!", 15, (inner.x + 6, y), color=K.F_LATE)
        else:
            K.t95(surf, f"Mietspiegel am Ende: {self.level}/5. Kiez hält.", 15, (inner.x + 6, y), color=(30, 140, 80))
        K.t95(surf, f"Höchster Mietspiegel: {self.max_level}/5", 15, (inner.x + 6, y + 24), color=K.F_DARK, bold=False)
        btn = pygame.Rect(inner.x + 10, inner.bottom - 70, inner.w - 20, 62)
        entries = party_games.top_list(self.NAME)
        rows = max(1, min(5, (btn.top - 10 - (y + 82) - 6) // 30))  # as many as fit above the button
        top = list(enumerate(entries))[:rows]
        if self.place is not None and self.place >= rows:  # this round always shows, as the last row
            top[-1] = (self.place, entries[self.place])
        K.t95(surf, "Bestenliste", 17, (inner.x + 6, y + 56))
        lst = pygame.Rect(inner.x + 4, y + 82, inner.w - 8, 6 + 30 * max(1, len(top)))
        K.bevel(surf, lst, sunken=True, face=K.F_PAPER)
        for row, (i, e) in enumerate(top):
            r = pygame.Rect(lst.x + 4, lst.y + 4 + row * 30, lst.w - 8, 28)
            mine = i == self.place
            if mine:
                pygame.draw.rect(surf, K.F_SEL, r)
            col = WHITE if mine else K.F_INK
            name = party_games.entry_name(e) + (" (du)" if mine and not e.get("name") else "")
            K.t95(surf, f"{i + 1}.  {name}", 16, (r.x + 8, r.centery), anchor="midleft", color=col)
            K.t95(surf, fmt_eur(e["score"]), 16, (r.right - 8, r.centery), anchor="midright", color=col)
        ready = self.last_tick - self.end_at >= BILANZ_TAP_DELAY
        K.button(surf, btn, "Weiter: Name & Nochmal" if ready else "...", size=18, face=(255, 200, 230) if ready else None,
                 color=K.F_ACCENT if ready else None)
        self.bilanz_rects = (lst, btn)  # for dev/test_kiezkapern.py

    def _make_fog(self):
        fog = pygame.Surface((W, H), pygame.SRCALPHA)
        fog.fill((30, 10, 50, 150))
        return fog
