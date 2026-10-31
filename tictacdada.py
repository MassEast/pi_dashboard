#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
TIC-TAC-DADA (tic-tac-dada.exe): two-player tic-tac-toe on one screen for
the KiezOS 161 "Spiele" menu, a party_games._Game (no score, so no
Bestenliste; the spiele.exe card shows MENU_LINE instead of a record).

- "Wer spielt?": both players already have a random profile picture from
  the WG's MoaBeats app (load_avatars(), pixelated to 16x16 so they match
  the KiezOS pixel look; placeholders if MoaBeats is off/unreachable). Each
  can re-roll ("Neu würfeln", never the other's picture); "X / O" switches
  to classic marks. One tap on LOS! starts.
- The marks are the pictures. A win draws a gold line through the row, then
  "schirine.exe - Urteil" with a win line from tictacdada_lines.WIN_LINES (a
  shuffled bag, no repeat until all were shown); once per play session, in a
  random round between SPECIAL_LINES.ROUNDS, a special line from config
  replaces it. A draw goes to someone who didn't play (DRAW_WINNERS bag).
  NOCHMAL: the loser (after a draw: the other player) starts.
- Dada: in about 1 of 3 rounds one surprise: a cell goes on holiday for 2
  moves, a crooked "Feld 10 (Beta)" appears (tapping it costs the turn), a
  picture melts (cosmetic), the SchirIne swaps all marks (§4b), or in X/O
  mode an X turns into a Win95 close button ("wirklich schließen?").
"""

import functools
import io
import logging
import math
import random

import pygame
import requests

import kiezos as K
import party_games
from tictacdada_lines import DRAW_WINNERS, WIN_LINES

logger = logging.getLogger()

P1 = (225, 60, 160)  # player colours: frame around a mark, X / O colour
P2 = (40, 140, 230)
PCOL = (P1, P2)
WIN_GLOW = (255, 236, 140)
GOLD = (255, 208, 72)
CELL, GAP = 140, 6
BOARD = pygame.Rect(24, 160, 3 * CELL + 2 * GAP, 3 * CELL + 2 * GAP)
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
DADA_ONE_IN = 3
WIN_ANIM_SECONDS = 0.7
RESULT_TAP_DELAY_SECONDS = 0.8
EGGS = ["urlaub", "feld10", "melt", "swap", "x_close"]
EINSPRUCH = [
    "Abgelehnt. Die SchirIne hat Feierabend.",
    "Weitergeleitet ans Amt für Kreuze und Kreise. Bearbeitungszeit 6-8 Wochen.",
    "Stattgegeben. Ändert aber nichts.",
    "Das Plenum vertagt sich.",
    "Einspruch wurde kompostiert.",
]
SPECIAL_LINES = {}  # config GAMES.TICTACTOE.SPECIAL_LINES: {"ROUNDS": [a, b], "WIN": [...], "PLAY": [...]}


# ------------------------------------------------------------------ avatars
# Placeholders: 16x16 pixel art, given as left halves (8 chars) mirrored to 16.

_CAT = ["........", ".k......", ".kk.....", ".kpk....", ".kppkkkk", ".koooooo", "kooooooo", "kowgoooo",
        "kowkoooo", "kooooooo", "kwwoooop", "kwwwooww", ".kwwwkww", "..kwwwww", "...kkkkk", "........"]
_PLACEHOLDERS = [
    ("Katze", (150, 205, 255), _CAT, {"k": K.INK, "o": (245, 150, 60), "p": K.PINK, "w": (255, 255, 255), "g": (60, 170, 80)}),
    ("Frosch", (255, 190, 225),
     ["........", "........", "..kkk...", ".kwwwk..", ".kwkwkkk", ".kwwwkgg", "kgkkkggg", "kggggggg",
      "kggggggg", "kgpggggg", "kggkkkkk", "kggggggg", ".kgggggg", "..kkkkkk", "........", "........"],
     {"k": K.INK, "w": (255, 255, 255), "g": (110, 200, 80), "p": K.PINK}),
    ("Kaktus", (255, 225, 120),
     [".......f", "......kf", ".....kcc", ".....kcd", "..k..kck", ".kck.kcd", ".kcckkcc", "..kccccd",
      "...kkkcc", ".....kcd", ".....kcc", "..kkkkkk", "..kttttt", "...ktttt", "...ktttt", "....kkkk"],
     {"k": K.INK, "c": (90, 180, 90), "d": (50, 130, 60), "t": (200, 100, 60), "f": K.PINK}),
    ("Toaster", (170, 230, 200),
     ["........", "...kk...", "..kbbk..", "..kbbk..", ".kkkkkkk", "ksssssss", "kswsssss", "kswsssss",
      "ksskssss", "ksssssss", "ksssksss", "ksssskkk", "ksssssss", "kddddddd", ".kk.....", "........"],
     {"k": K.INK, "s": (200, 200, 215), "w": (255, 255, 255), "d": (120, 120, 140), "b": (215, 160, 90)}),
    ("Sonnenschein", (200, 170, 250),
     ["........", ".....kkk", "...kkyyy", "..kyyyyy", ".kyyyyyy", ".kyyyyyy", "kykkkkkk", "kykkwkkk",
      "kyykkkkk", "kyyyyyyy", "kyyyyyyy", ".kykyyyy", ".kyykkkk", "..kyyyyy", "...kkyyy", ".....kkk"],
     {"k": K.INK, "y": (255, 215, 60), "w": (255, 255, 255)}),
    ("Nachtkatze", (255, 170, 110), _CAT, {"k": K.INK, "o": (55, 45, 70), "p": K.PINK, "w": (240, 240, 250), "g": (250, 210, 60)}),
    ("Gespenst", (175, 215, 255),
     ["........", ".....kkk", "...kkwww", "..kwwwww", ".kwwwwww", ".kwwkkww", ".kwwkkww", "kwwwwwww",
      "kwbwwwkk", "kwwwwwkk", "kwwwwwww", "kwwwwwww", "kwwwwwww", "kwwkwwwk", "kwk.kwk.", "kk...k.."],
     {"k": K.INK, "w": (255, 255, 255), "b": K.PINK}),
    ("Robo", (255, 215, 190),
     [".......k", ".......r", "......kk", "..kkkkkk", ".kgggggg", ".kgkkggg", ".kgkcggg", ".kgkkggg",
      ".kgggggg", ".kgkrkrk", ".kgggggg", "..kkkkkk", "....kkgg", "..kkgggg", ".kgggggg", ".kgggggg"],
     {"k": K.INK, "g": (170, 175, 200), "c": (80, 230, 240), "r": (230, 60, 80)}),
]


def _placeholder16(entry):
    _, bg, half, pal = entry
    s = pygame.Surface((16, 16))
    s.fill(bg)
    for y, row in enumerate(half):
        for x, ch in enumerate(row + row[::-1]):
            if ch in pal:
                s.set_at((x, y), pal[ch])
    return s


_FOGS = {}  # (w, h, alpha) -> dimming surface for the dialogs
AVATARS = []  # [(name, 16x16 surface)] - MoaBeats pictures once load_avatars() ran


def placeholder_avatars():
    return [(e[0], _placeholder16(e)) for e in _PLACEHOLDERS]


def pixelate(img):
    """Centre square of a profile picture, down to 16x16."""
    w, h = img.get_size()
    side = min(w, h)
    square = pygame.Surface((side, side), pygame.SRCALPHA, 32)  # smoothscale needs 24/32 bit (palette PNGs aren't)
    square.fill((255, 255, 255))
    square.blit(img, (-(w - side) // 2, -(h - side) // 2))
    return pygame.transform.smoothscale(square, (16, 16))


def load_avatars(api_url):
    """Blocking (run it in a thread): the WG's MoaBeats profile pictures
    (GET /api/users/public, no login, used by the app's own login screen),
    each downloaded and pixelated. Sets AVATARS; keeps the placeholders if
    fewer than 2 pictures come back. Per-picture failures are logged and
    skipped (one broken upload must not cost everyone else's)."""
    global AVATARS
    base = api_url.rstrip("/")
    users = requests.get(base + "/api/users/public", timeout=8)
    users.raise_for_status()
    loaded = []
    for user in users.json():
        if not user.get("avatar_url"):
            continue
        url = user["avatar_url"] if user["avatar_url"].startswith("http") else base + user["avatar_url"]
        try:
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            loaded.append((user["name"], pixelate(pygame.image.load(io.BytesIO(resp.content)))))
        except Exception as e:
            logger.error(f"TIC-TAC-DADA: avatar of {user['name']} skipped: {e}")
    if len(loaded) >= 2:
        AVATARS = loaded
    logger.info(f"TIC-TAC-DADA: {len(loaded)} MoaBeats avatars loaded")


def menu_icon(size):
    s = pygame.Surface((16, 16), pygame.SRCALPHA)
    pygame.draw.rect(s, (255, 255, 255), (0, 0, 16, 16))
    for v in (5, 10):
        pygame.draw.line(s, K.INK, (v, 1), (v, 14))
        pygame.draw.line(s, K.INK, (1, v), (14, v))
    pygame.draw.line(s, P1, (1, 1), (3, 3))
    pygame.draw.line(s, P1, (3, 1), (1, 3))
    pygame.draw.line(s, P1, (12, 12), (14, 14))
    pygame.draw.line(s, P1, (14, 12), (12, 14))
    pygame.draw.rect(s, P2, (6, 6, 4, 4), 1)
    pygame.draw.rect(s, K.INK, (0, 0, 16, 16), 1)
    return pygame.transform.scale(s, (size, size))


def _pixel_art(rows, pal, cell):
    s = pygame.Surface((len(rows[0]) * cell, len(rows) * cell), pygame.SRCALPHA)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in pal:
                pygame.draw.rect(s, pal[ch], (x * cell, y * cell, cell, cell))
    return s


_FRIDGE = ["kkkkkkkkkkkk", "kwwwwwwwwwwk", "kwwwwwwwwhwk", "kwwwwwwwwhwk", "kwwwwwwwwwwk", "kkkkkkkkkkkk",
           "kwwwwwwwwwwk", "kwwkwwwwkwwk", "kwwwwwwwwhwk", "kwwkwwwwkhwk", "kwwwkkkkwhwk", "kwwwwwwwwhwk",
           "kwmwwwwwwwwk", "kwmmwwwwwwwk", "kwwwwwwwwwwk", "kwwwwwwwwwwk", "kkkkkkkkkkkk", ".kk......kk."]
_FRIDGE_PAL = {"k": K.INK, "w": (235, 240, 250), "h": (150, 150, 170), "m": K.PINK}
_PALM = ["......gg.gg.", "....ggggggg.", "...gg.gbggg.", "..g...b..gg.", "......b.....", ".....b......",
         ".....b......", ".....b......", "....b.......", "....b.......", "ssssbsssssss", "ssssssssssss"]
_PALM_PAL = {"g": (60, 170, 80), "b": (150, 100, 60), "s": (245, 215, 130)}
_CONE = ["....kk....", "...kok....", "...kook...", "..kwwwk...", "..kooook..", ".kwwwwwwk.", ".koooooook", "kkkkkkkkkk"]
_CONE = [r[:5] + r[4::-1] for r in _CONE]
_CONE_PAL = {"k": K.INK, "o": (255, 120, 40), "w": (255, 255, 255)}


def _star(surf, c, r, color):
    pts = []
    for k in range(16):
        rad = r if k % 2 == 0 else r * 0.38
        a = k * math.pi / 8
        pts.append((c[0] + rad * math.cos(a), c[1] + rad * math.sin(a)))
    pygame.draw.polygon(surf, color, pts)
    pygame.draw.polygon(surf, K.F_INK, pts, 2)


def _wordart_width(s, size):
    """Width of K.wordart(s, size): letters rendered one by one, + 8 px extrusion."""
    f = K.font(size)
    return sum(f.size(ch)[0] for ch in s) + 8


@functools.lru_cache(maxsize=256)  # called every frame with the same few names
def fit_named(fmt, name, max_width, sizes, bold=True):
    """(text, size) of fmt.format(name) at the biggest of `sizes` that fits;
    if none does, the name gets cut ("Prinzessin Lillif.") until it fits at
    the smallest. MoaBeats names have no length limit."""
    for cut in range(len(name), 0, -1):
        text = fmt.format(name if cut == len(name) else name[:cut].rstrip(" -.,") + ".")
        size = next((s for s in sizes if K.font(s, bold).size(text)[0] <= max_width), None)
        if size is not None:
            return text, size
    return text, sizes[-1]


@functools.lru_cache(maxsize=64)
def _verdict_title_fit(name, width):
    full = name.upper()
    sizes = (26, 22, 19)  # smaller WordArt gets illegible: cut the name instead
    for cut in range(len(full), 0, -1):
        title = f"{full if cut == len(full) else full[:cut].rstrip(' -.,') + '.'} GEWINNT!"
        size = next((s for s in sizes if _wordart_width(title, s) <= width), None)
        if size is not None:
            return title, size
    return title, sizes[-1]


def _bag(items):
    """Endless shuffled bag: every item once before any repeats."""
    while True:
        items = list(items)
        random.shuffle(items)
        yield from items


_WIN_BAG = _bag(WIN_LINES)
_DRAW_BAG = _bag(DRAW_WINNERS)


def cell_rect(i):
    return pygame.Rect(BOARD.x + (i % 3) * (CELL + GAP), BOARD.y + (i // 3) * (CELL + GAP), CELL, CELL)


def winner_cells(board):
    for line in LINES:
        a, b, c = (board[i] for i in line)
        if a is not None and a == b == c:
            return line
    return None


# ------------------------------------------------------------------ the game

class TicTacDadaGame(party_games._Game):
    NAME = "TIC-TAC-DADA"
    ICON = "tictacdada"
    MENU_LINE = "2 Spieler*innen, 1 SchirIne"

    def reset(self, now):
        super().reset(now)
        self.avatars = AVATARS or placeholder_avatars()
        self.state = "setup"  # setup -> play -> win_anim -> result | draw
        self.players = random.sample(range(len(self.avatars)), 2)
        self.classic = False
        self.wins = [0, 0]
        self.round_no = 0
        rounds = SPECIAL_LINES.get("ROUNDS")
        self.special_round = random.randint(*rounds) if rounds else None
        self.rects = {}
        self._scaled = {}
        # round fields (set for real by new_round())
        self.board, self.moves, self.turn, self.winner, self.win_cells = [None] * 9, 0, 0, None, None
        self.egg, self.egg_live, self.dialog, self.note, self.bubble = None, False, None, None, None
        self.holiday, self.feld10_until, self.melt_cell, self.melt_t, self.close_cell = None, -1, None, 0.0, None

    # ---- helpers ----------------------------------------------------
    def name(self, p):
        return f"Spieler*in {'XO'[p]}" if self.classic else self.avatars[self.players[p]][0]

    def avatar(self, p, cell):
        key = (self.players[p], cell)
        if key not in self._scaled:
            self._scaled[key] = pygame.transform.scale(self.avatars[self.players[p]][1], (16 * cell, 16 * cell))
        return self._scaled[key]

    def framed_avatar(self, surf, p, center, cell, color=None):
        img = self.avatar(p, cell)
        r = img.get_rect(center=center)
        pygame.draw.rect(surf, color or PCOL[p], r.inflate(10, 10))
        pygame.draw.rect(surf, K.F_INK, r.inflate(10, 10), 2)
        surf.blit(img, r)
        pygame.draw.rect(surf, K.F_INK, r, 2)
        return r

    def _special(self, kind):
        lines = SPECIAL_LINES.get(kind)
        if lines and self.round_no == self.special_round:
            return random.choice(lines)
        return None

    # ---- rounds -----------------------------------------------------
    def new_round(self, starter):
        self.state = "play"
        self.round_no += 1
        self.board = [None] * 9
        self.starter = starter
        self.turn = starter
        self.moves = 0
        self.win_cells = None
        self.winner = None
        self.result_at = 0.0
        self.line = ""
        self.draw_winner = None
        self.einspruch = None
        self.bubble = None  # (lines, anchor, until)
        self.note = None  # extra status line after a dada moment
        eggs = [e for e in EGGS if (e != "x_close" or self.classic) and (e != "melt" or not self.classic)]
        self.egg = random.choice(eggs) if random.random() < 1 / DADA_ONE_IN else None
        self.egg_at = random.randint(1, 4) if self.egg != "swap" else random.randint(3, 5)
        self.egg_live = False
        self.holiday = None  # (cell, until_move)
        self.feld10_until = -1
        self.melt_cell = None
        self.melt_t = 0.0
        self.close_cell = None
        self.dialog = None  # "swap" | "close" | None

    def _start_egg(self):
        empty = [i for i in range(9) if self.board[i] is None]
        mine = [i for i in range(9) if self.board[i] is not None]
        self.egg_live = True
        if self.egg == "urlaub" and len(empty) > 2:
            self.holiday = (random.choice(empty), self.moves + 2)
        elif self.egg == "feld10":
            self.feld10_until = self.moves + 3
        elif self.egg == "melt" and mine:
            self.melt_cell = random.choice(mine)
            self.melt_at = self.last_tick
            self.note = ("Hitzewarnung im Flur!", ("{} schmilzt. Zählt trotzdem.", self.name(self.board[self.melt_cell])))
        elif self.egg == "swap" and mine:
            self.dialog = "swap"
        elif self.egg == "x_close":
            xs = [i for i in mine if self.board[i] == 0]
            if xs:
                self.close_cell = random.choice(xs)
        else:
            self.egg_live = False

    def _place(self, i):
        self.board[i] = self.turn
        self.moves += 1
        cells = winner_cells(self.board)
        if cells:
            self._win(self.turn, cells)
            return
        if all(c is not None for c in self.board):
            self._draw()
            return
        self.turn = 1 - self.turn
        self.note = None if self.egg != "melt" or self.melt_cell is None else self.note
        if self.egg and not self.egg_live and self.moves >= self.egg_at:
            self._start_egg()

    def _win(self, p, cells):
        self.winner, self.win_cells = p, cells
        self.wins[p] += 1
        self.state = "win_anim"
        self.result_at = self.last_tick
        loser = self.name(1 - p)
        self.line = (self._special("WIN") or next(_WIN_BAG)).format(winner=self.name(p), loser=loser)

    def _draw(self):
        self.state = "draw"
        self.result_at = self.last_tick
        article, champ, comment, icon = next(_DRAW_BAG)
        special = self._special("PLAY")
        self.draw_winner = (article, champ, special or comment, icon)

    # ---- input ------------------------------------------------------
    def tap(self, x, y):
        pos = (x, y)
        # last drawn = on top (dialogs and buttons are drawn over the board)
        hit = next((k for k, r in reversed(self.rects.items()) if r.collidepoint(pos)), None)
        if self.state == "setup":
            return self._setup_tap(hit)
        if self.state in ("result", "draw"):
            if self.last_tick - self.result_at < RESULT_TAP_DELAY_SECONDS:
                return None
            if hit == "again":
                self.new_round(1 - self.winner if self.winner is not None else 1 - self.starter)
            elif hit == "others":
                self.reset(self.last_tick)
            elif hit == "menu":
                return "menu"
            elif hit == "einspruch" and self.einspruch is None:
                self.einspruch = random.choice(EINSPRUCH)
            return None
        if self.state != "play":
            return None
        if self.dialog == "swap":
            if hit in ("ok", "einspruch_swap", "swap_x"):
                self.board = [None if c is None else 1 - c for c in self.board]
                self.dialog = None
                self.note = ("Regel §4b angewendet.", "Einspruch abgelehnt." if hit == "einspruch_swap" else "Alles getauscht.")
            return None
        if self.dialog == "close":
            if hit in ("ja", "auch_ja", "close_x"):
                self.dialog = None
                self.close_cell = None
                self.note = ("Das X bleibt.", "Es hat Kündigungsschutz.")
            return None
        if hit == "feld10":
            self.note = ("Feld 10 dankt für deinen Besuch.", "Zug verbraucht. Zählt nicht.")
            self.turn = 1 - self.turn
            self.feld10_until = -1
            return None
        if hit and hit.startswith("cell"):
            i = int(hit[4:])
            if self.close_cell == i:
                self.dialog = "close"
            elif self.holiday and self.holiday[0] == i and self.moves < self.holiday[1]:
                self.bubble = (["Dieses Feld ist leider", "gerade im Urlaub.", "Zurück in 2 Zügen. Postkarte folgt."],
                               cell_rect(i).midbottom, self.last_tick + 3)
            elif self.board[i] is None:
                self._place(i)
        return None

    def _setup_tap(self, hit):
        if hit in ("roll0", "roll1"):
            p = int(hit[-1])
            if self.classic:
                self.players.reverse()  # "X <-> O tauschen"
            elif len(self.avatars) > 2:
                self.players[p] = random.choice([i for i in range(len(self.avatars)) if i not in self.players])
        elif hit == "faces":
            self.classic = False
        elif hit == "xo":
            self.classic = True
        elif hit == "go":
            self.new_round(0)
        return None

    def step(self, dt):
        if self.state == "win_anim" and self.last_tick - self.result_at >= WIN_ANIM_SECONDS:
            self.state = "result"
            self.result_at = self.last_tick
        if self.melt_cell is not None:  # by elapsed time: update() caps dt
            self.melt_t = min(1.0, (self.last_tick - self.melt_at) / 2.5)

    # ---- drawing ----------------------------------------------------
    def draw(self, surf):
        self.rects = {}
        surf.blit(K.desktop(), (0, 0), pygame.Rect(0, 36, self.width, self.height))
        if self.state == "setup":
            self._draw_setup(surf)
            return
        if self.state == "result":
            self._draw_verdict(surf)
        else:
            self._draw_scoreboard(surf)
        glow = self.win_cells if self.state in ("win_anim", "result") else ()
        self._draw_board(surf, glow)
        if self.state == "win_anim":
            t = min(1.0, (self.last_tick - self.result_at) / WIN_ANIM_SECONDS)
            tip = self._win_line(surf, t)
            for k, (dx, dy) in enumerate([(-40, -70), (-80, -20), (-120, -90)]):
                _star(surf, (tip[0] + dx, tip[1] + dy), 12 - 2 * k, (255, 255, 255))
            self._status(surf, [("DREI IN EINER REIHE!", True), ("Die SchirIne pfeift...", False)], self.winner)
            self._statusbar(surf, [(f"Zug {self.moves}", 90), ("SchirIne: pfeift", 170), (f"Runde {self.round_no}", 120)])
        elif self.state == "result":
            self._win_line(surf, 1.0)
            self._draw_result_buttons(surf)
        elif self.state == "draw":
            self._statusbar(surf, [(f"Zug {self.moves}", 90), ("SchirIne: ratlos", 170), (f"Runde {self.round_no}", 120)])
            self._draw_draw(surf)
        else:
            self._draw_play_status(surf)

    def _draw_setup(self, surf):
        w = self.width
        win = pygame.Rect(12, 10, w - 24, self.height - 22)
        inner = K.window(surf, win, "Wer spielt?", buttons=None)
        K.t95(surf, "Zwei Leute, ein Bildschirm.", 17, (inner.centerx, inner.y + 10), anchor="midtop")
        sub = "X gegen O, ganz klassisch." if self.classic else "Gesichter werden zugelost."
        K.t95(surf, sub, 16, (inner.centerx, inner.y + 34), anchor="midtop", color=K.F_DARK, bold=False)
        for p in (0, 1):
            box = pygame.Rect(inner.x + 8, inner.y + 76 + p * 250, inner.w - 16, 190)
            K.groupbox(surf, box, f"Spieler*in {p + 1}" + ("  (fängt an)" if p == 0 else ""))
            cx, cy = box.x + 92, box.centery + 6
            if self.classic:
                pic = pygame.Rect(0, 0, 144, 144)
                pic.center = (cx, cy)
                K.bevel(surf, pic, sunken=True, face=K.F_PAPER)
                self._xo(surf, p, (cx, cy), 44)
                nm, line = self.name(p), "klassisch, langweilig"
            else:
                self.framed_avatar(surf, p, (cx, cy), 9)
                nm, line = self.name(p), "aus MoaBeats gezogen" if AVATARS else "Ersatzbild (MoaBeats offline)"
            tx = box.x + 184
            nm, nm_size = fit_named("{}", nm, box.right - tx - 8, (26, 22, 18, 16))
            K.t95(surf, nm, nm_size, (tx, box.y + 30))
            K.t95(surf, line, K.fit_size(line, box.right - tx - 8, sizes=(15, 14, 13), bold=False), (tx, box.y + 66), color=K.F_DARK, bold=False)
            btn = pygame.Rect(tx, box.bottom - 82, box.right - tx - 12, 64)
            self.rects[f"roll{p}"] = K.button(surf, btn, "X <-> O tauschen" if self.classic else "Neu würfeln", size=17 if self.classic else 19)
        K.wordart(surf, "gegen", 24, (inner.centerx, inner.y + 294), wave=4)
        ty = inner.y + 548
        K.t95(surf, "Spielsteine:", 17, (inner.x + 10, ty + 24), anchor="midleft")
        seg_w = (inner.right - 8 - (inner.x + 150)) // 2
        a = pygame.Rect(inner.x + 150, ty, seg_w, 50)
        b = pygame.Rect(a.right, ty, seg_w, 50)
        self.rects["faces"] = K.button(surf, a, "Gesichter", size=17, pressed=not self.classic, face=(236, 228, 252) if not self.classic else None)
        self.rects["xo"] = K.button(surf, b, "X / O", size=17, pressed=self.classic, face=(236, 228, 252) if self.classic else None)
        go = pygame.Rect(inner.x + 8, inner.bottom - 82, inner.w - 16, 76)
        K.button(surf, go, "")
        pygame.draw.rect(surf, K.F_INK, go, 2)
        K.wordart(surf, "LOS!", 36, go.center, wave=3)
        self.rects["go"] = go

    def _xo(self, surf, p, c, d):
        if p == 0:
            for off in (-1, 1):
                pygame.draw.line(surf, K.F_INK, (c[0] - d, c[1] - off * d), (c[0] + d, c[1] + off * d), 24)
                pygame.draw.line(surf, P1, (c[0] - d, c[1] - off * d), (c[0] + d, c[1] + off * d), 16)
        else:
            pygame.draw.circle(surf, K.F_INK, c, d + 4, 24)
            pygame.draw.circle(surf, P2, c, d, 16)

    def _draw_scoreboard(self, surf):
        win = pygame.Rect(8, 8, self.width - 16, 140)
        inner = K.window(surf, win, "spielstand.txt", buttons=None)
        for p in (0, 1):
            plate = pygame.Rect(inner.x + 4 + p * (inner.w // 2 + 4), inner.y + 4, inner.w // 2 - 12, inner.h - 8)
            active = p == self.turn and self.state == "play"
            K.bevel(surf, plate, sunken=active, face=(236, 228, 252) if active else K.F_FACE)
            if active:
                pygame.draw.rect(surf, PCOL[p], plate, 3)
            cx = plate.x + 46
            if self.classic:
                K.t95(surf, "XO"[p], 54, (cx, plate.centery), color=PCOL[p], anchor="center")
            else:
                self.framed_avatar(surf, p, (cx, plate.centery), 4)
            nm, nm_size = fit_named("{}", self.name(p), plate.w - 92, (22, 20, 18, 16, 14))
            K.t95(surf, nm, nm_size, (plate.x + 86, plate.y + 12))
            K.t95(surf, f"Siege: {self.wins[p]}", 16, (plate.x + 86, plate.y + 42), color=K.F_DARK, bold=False)
            if active:
                K.t95(surf, "< dran", 16, (plate.x + 86, plate.y + 64), color=PCOL[p])

    def _draw_board(self, surf, glow):
        K.bevel(surf, BOARD.inflate(16, 16), sunken=True, face=K.F_DARK)
        for i, m in enumerate(self.board):
            r = cell_rect(i)
            holiday = self.holiday and self.holiday[0] == i and self.moves < self.holiday[1] and self.state == "play"
            if holiday:
                self._draw_holiday(surf, r)
            elif m is None:
                K.button(surf, r, "")
            elif self.close_cell == i and self.state == "play":
                K.bevel(surf, r, sunken=True, face=K.F_PAPER)
                K.button(surf, r.inflate(-24, -24), "x", size=72, color=P1)
            elif self.melt_cell == i and not self.classic:
                K.bevel(surf, r, sunken=True, face=K.F_PAPER)
                self._draw_melted(surf, i, m)
            else:
                K.bevel(surf, r, sunken=True, face=WIN_GLOW if i in glow else K.F_PAPER)
                if self.classic:
                    self._xo(surf, m, r.center, 40)
                else:
                    self.framed_avatar(surf, m, r.center, 7)
            if i in glow:
                pygame.draw.rect(surf, GOLD, r.inflate(4, 4), 5)
            self.rects[f"cell{i}"] = r

    def _draw_holiday(self, surf, r):
        K.bevel(surf, r, sunken=True, face=(150, 210, 255))
        pygame.draw.rect(surf, (60, 140, 220), (r.x + 2, r.y + 84, r.w - 4, 20))
        palm = _pixel_art(_PALM, _PALM_PAL, 9)
        surf.blit(palm, palm.get_rect(midbottom=(r.centerx + 6, r.bottom - 2)))
        pygame.draw.circle(surf, GOLD, (r.x + 26, r.y + 26), 13)
        sign = pygame.Rect(r.x + 6, r.bottom - 34, 72, 24)
        pygame.draw.rect(surf, (255, 255, 255), sign)
        pygame.draw.rect(surf, K.F_INK, sign, 2)
        K.t95(surf, "URLAUB", 15, sign.center, color=K.F_LATE, anchor="center")

    def _draw_melted(self, surf, i, m):
        r = cell_rect(i)
        grid = self.avatars[self.players[m]][1]
        drips = [0, 1, 2, 3, 3, 2, 4, 9, 6, 3, 2, 2, 5, 11, 4, 1]
        ds = tuple(int(d * self.melt_t) for d in drips)
        key = ("melt", self.players[m], ds)  # the picture only changes when a drip grows a pixel
        if key not in self._scaled:
            out = pygame.Surface((16, 16 + max(drips)), pygame.SRCALPHA)
            for x, d in enumerate(ds):
                for y in range(16 + d):
                    sy = y if y < 7 else 7 + int((y - 7) * 9 / (9 + d))
                    if sy < 16:
                        out.set_at((x, y), grid.get_at((x, sy)))
            self._scaled[key] = pygame.transform.scale(out, (16 * 7, out.get_height() * 7))
        img = self._scaled[key]
        pos = img.get_rect(midtop=(r.centerx, r.y + 14))
        pygame.draw.rect(surf, PCOL[m], (pos.x - 5, pos.y - 5, pos.w + 10, 74))
        pygame.draw.rect(surf, K.F_INK, (pos.x - 5, pos.y - 5, pos.w + 10, 74), 2)
        clip = surf.get_clip()
        surf.set_clip(BOARD.inflate(16, 16))
        surf.blit(img, pos)
        surf.set_clip(clip)

    def _win_line(self, surf, t):
        a, b = self.win_cells[0], self.win_cells[2]
        ca, cb = pygame.Vector2(cell_rect(a).center), pygame.Vector2(cell_rect(b).center)
        d = (cb - ca).normalize()
        start, end = ca - d * 54, cb + d * 54
        tip = start + (end - start) * t
        for w, col in ((26, K.F_INK), (16, GOLD), (6, (255, 250, 210))):
            pygame.draw.line(surf, col, start, tip, w)
            pygame.draw.circle(surf, col, start, w // 2)
            pygame.draw.circle(surf, col, tip, w // 2)
        _star(surf, tip, 26, (255, 250, 210))
        return tip

    def _status(self, surf, lines, who=None, width=None):
        box = pygame.Rect(16, 610, width or self.width - 32, 100)
        K.tooltip(surf, box)
        x = box.x + 14
        if who is not None:
            if self.classic:
                K.t95(surf, "XO"[who], 40, (box.x + 34, box.centery), color=PCOL[who], anchor="center")
            else:
                self.framed_avatar(surf, who, (box.x + 38, box.centery), 3)
            x = box.x + 76
        y = box.centery - (len(lines) * 26) // 2 + 2
        for j, (txt, bold) in enumerate(lines):
            # txt: a string, or (fmt, name) when it contains a player's name (cut if too long)
            fmt, name = txt if isinstance(txt, tuple) else (txt.replace("{", "{{").replace("}", "}}"), "")
            sizes = (18, 17, 16, 15, 14) if bold else (16, 15, 14, 13)
            txt, size = fit_named(fmt, name, box.right - x - 8, sizes, bold=bold) if name else (fmt.format(), None)
            if size is None:
                size = K.fit_size(txt, box.right - x - 8, sizes=sizes, bold=bold)
                txt = party_games._fit(K.font(size, bold), txt, box.right - x - 8)
            K.t95(surf, txt, size, (x, y + j * 26), bold=bold)

    def _statusbar(self, surf, fields):
        bar = pygame.Rect(0, self.height - 40, self.width, 40)
        pygame.draw.rect(surf, K.F_FACE, bar)
        pygame.draw.line(surf, K.F_LIGHT, (0, bar.y + 1), (self.width, bar.y + 1), 2)
        x = 4
        for label, w in fields:
            f = pygame.Rect(x, bar.y + 5, w, 31)
            K.bevel(surf, f, sunken=True)
            K.t95(surf, label, K.fit_size(label, w - 12, sizes=(15, 14, 13)), (f.x + 8, f.centery), anchor="midleft", bold=False)
            x = f.right + 4

    def _draw_play_status(self, surf):
        feld10 = self.moves < self.feld10_until
        width = 316 if feld10 else None  # room for the taped-on Feld 10 tile
        if self.note:
            self._status(surf, [(self.note[0], True), (self.note[1], False)], self.turn, width)
        else:
            self._status(surf, [(("{} ist dran.", self.name(self.turn)), True), ("Tip: Tippe ein freies Feld.", False)], self.turn, width)
        egg_label = {"urlaub": "Feld im Urlaub", "feld10": "Felder: 10 (?)", "melt": "Flur: 31 °C", "swap": "SchirIne: übermütig",
                     "x_close": "Fenster: 1 zu viel"}.get(self.egg) if self.egg_live else None
        self._statusbar(surf, [(f"Zug {self.moves + 1}", 90), (egg_label or "SchirIne: wach", 200), (f"Runde {self.round_no}", 120)])
        if feld10:
            tile = pygame.Surface((112, 112), pygame.SRCALPHA)
            K.button(tile, tile.get_rect(), "")
            K.t95(tile, "10", 44, (56, 46), anchor="center", color=K.F_ACCENT)
            K.t95(tile, "(Beta)", 16, (56, 88), anchor="center", color=K.F_DARK, bold=False)
            tile = pygame.transform.rotate(tile, 11)
            for y in range(588, 614, 6):
                pygame.draw.line(surf, (190, 180, 160), (380, y), (420, y + 4), 4)  # tape
            rect = tile.get_rect(center=(400, 658))
            surf.blit(tile, rect)
            self.rects["feld10"] = rect.inflate(-10, -10)
        if self.bubble and self.last_tick < self.bubble[2]:
            K.speech(surf, pygame.Rect(16, 610, self.width - 32, 100), self.bubble[0], self.bubble[1], size=17)
        if self.dialog == "swap":
            self._fog(surf, 110)
            buttons = K.msgbox(surf, "schirine.exe", "ok", ["Regel §4b tritt in Kraft:", "", "Alle Steine tauschen", "die Seiten.", "Viel Glück!"],
                               ["Na gut", "Einspruch"])
            # its x (last) does what "Na gut" does: the SchirIne doesn't take no for an answer
            self.rects.update({"swap_x": buttons[2][0], "ok": buttons[0][0], "einspruch_swap": buttons[1][0]})
        elif self.dialog == "close":
            self._fog(surf, 100)
            r = cell_rect(self.close_cell)
            K.bevel(surf, r, sunken=True, face=K.F_PAPER)
            K.button(surf, r.inflate(-24, -24), "x", size=72, color=P1)
            win = pygame.Rect(30, 178, self.width - 60, 230) if r.y > 300 else pygame.Rect(30, 400, self.width - 60, 230)
            inner = K.dialog(surf, win, "spielfeld.exe", icon="games")
            self.rects["close_x"] = K.close_box(win)  # closing the dialog doesn't close the X either
            K.t95(surf, "Möchten Sie dieses X", 18, (inner.centerx, inner.y + 18), anchor="midtop")
            K.t95(surf, "wirklich schließen?", 18, (inner.centerx, inner.y + 44), anchor="midtop")
            K.t95(surf, "Ungespeicherte Kreuze gehen verloren.", 15, (inner.centerx, inner.y + 80), anchor="midtop", color=K.F_DARK, bold=False)
            self.rects["ja"] = K.button(surf, pygame.Rect(inner.centerx - 156, inner.bottom - 64, 150, 56), "Ja", size=19)
            self.rects["auch_ja"] = K.button(surf, pygame.Rect(inner.centerx + 6, inner.bottom - 64, 150, 56), "Auch ja", size=19)

    def _fog(self, surf, alpha):
        key = (self.width, self.height, alpha)
        if key not in _FOGS:  # a full-screen alpha surface per frame is slow on the Pi
            _FOGS[key] = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            _FOGS[key].fill((30, 12, 50, alpha))
        surf.blit(_FOGS[key], (0, 0))

    def _draw_verdict(self, surf):
        win = pygame.Rect(8, 8, self.width - 16, 140)
        inner = K.window(surf, win, "schirine.exe - Urteil", icon="ok", buttons=None)
        p = self.winner
        if self.classic:
            av = pygame.Rect(0, 0, 70, 70)
            av.center = (inner.x + 50, inner.y + 52)
            K.t95(surf, "XO"[p], 54, av.center, color=PCOL[p], anchor="center")
        else:
            av = self.framed_avatar(surf, p, (inner.x + 50, inner.y + 52), 4)
        cone = _pixel_art(_CONE, _CONE_PAL, 4)
        surf.blit(cone, cone.get_rect(midbottom=(av.centerx + 6, av.top + 6)))
        # Title and note share the space right of the picture (inner.x + 96 on).
        area = pygame.Rect(inner.x + 96, inner.y, inner.right - inner.x - 96, inner.h)
        self._verdict_title(surf, self.name(p), area.inflate(-8, 0), inner.y + 21)
        self._verdict_note(surf, pygame.Rect(area.x, inner.y + 44, area.w - 2, 52), self.line)

    @staticmethod
    def _verdict_title(surf, name, area, cy):
        """"<NAME> GEWINNT!" as WordArt, shrunk (and the name cut, for very
        long MoaBeats names) to fit `area`'s width; centred in it."""
        title, size = _verdict_title_fit(name, area.w)
        K.wordart(surf, title, size, (area.centerx, cy), wave=3 if size > 19 else 2)

    @staticmethod
    @functools.lru_cache(maxsize=64)
    def _note_lines(line, width):
        """(size, label, lines) for a verdict note: biggest size whose wrap
        fits (16/15: 2 lines, 14/13: 3); at 13 the last line is cut with "..."."""
        label, rest = ("Preis:", line[len("Preis:"):].strip()) if line.startswith("Preis:") else ("", line)
        for size, max_lines in ((16, 2), (15, 2), (14, 3), (13, 3)):
            lw = K.font(size, True).size(label + " ")[0] if label else 0
            # wrap the first line narrower (label in front), the rest full width
            words, lines = rest.split(), []
            while words:
                avail = width - (lw if not lines else 0)
                cur = words.pop(0)
                while words and K.font(size, False).size(f"{cur} {words[0]}")[0] <= avail:
                    cur = f"{cur} {words.pop(0)}"
                lines.extend(K.wrap(cur, size, avail, bold=False))  # a single word wider than the note is cut
            if len(lines) <= max_lines:
                return size, label, lw, lines
        lines = lines[:max_lines]
        lines[-1] = party_games._fit(K.font(13, False), lines[-1] + " ...", width)
        return 13, label, lw, lines

    def _verdict_note(self, surf, note, line):
        pygame.draw.rect(surf, K.SHADOW, note.move(3, 3))
        pygame.draw.rect(surf, K.F_TIP, note)
        pygame.draw.rect(surf, K.F_INK, note, 1)
        size, label, lw, lines = self._note_lines(line, note.w - 14)
        f = K.font(size, False)
        pitch = size + (4 if len(lines) <= 2 else 2)
        top = note.centery - (len(lines) * pitch) // 2
        for i, ln in enumerate(lines):
            x = note.centerx - ((lw if i == 0 else 0) + f.size(ln)[0]) // 2
            if i == 0 and label:
                K.t95(surf, label, size, (x, top), color=K.F_ACCENT)
                x += lw
            K.t95(surf, ln, size, (x, top + i * pitch), bold=False)

    def _draw_result_buttons(self, surf):
        ready = self.last_tick - self.result_at >= RESULT_TAP_DELAY_SECONDS
        again = pygame.Rect(16, 610, self.width - 32, 64)
        label, size = fit_named("NOCHMAL  ({} fängt an)", self.name(1 - self.winner), again.w - 20, (20, 18, 16))
        self.rects["again"] = K.button(surf, again, label, size=size, enabled=ready)
        half = (self.width - 32 - 8) // 2
        self.rects["others"] = K.button(surf, pygame.Rect(16, 682, half, 64), "Andere Leute", size=18, enabled=ready)
        self.rects["menu"] = K.button(surf, pygame.Rect(16 + half + 8, 682, half, 64), "Menü", size=18, enabled=ready)

    @staticmethod
    @functools.lru_cache(maxsize=64)
    def _comment_lines(text, width):
        """(size, lines) of a draw comment / Einspruch: at most 3 lines, shrunk
        before cut (config PLAY lines can be long)."""
        for size in (16, 15, 14):
            lines = K.wrap(text, size, width, bold=False)
            if len(lines) <= 3:
                return size, lines
        return 14, lines[:2] + [party_games._fit(K.font(14, False), lines[2] + " ...", width)]

    def _draw_draw(self, surf):
        self._fog(surf, 150)
        win = pygame.Rect(28, 160, self.width - 56, 470)
        inner = K.dialog(surf, win, "schirine.exe", icon="ok", buttons=None)
        article, champ, comment, icon = self.draw_winner
        if icon == "fridge":
            img = _pixel_art(_FRIDGE, _FRIDGE_PAL, 8)
        elif icon == "sun":
            img = K.weather_icon("sun", 112)
        elif icon in ("bus", "lake", "garden"):
            img = K.landmark_icon(icon, 112)
        else:
            img = K.menu_icon(icon, 112)
        fr = surf.blit(img, (inner.x + 16, inner.y + 18))
        _star(surf, (fr.right + 4, fr.top + 6), 12, GOLD)
        _star(surf, (fr.left - 2, fr.top + 60), 9, (255, 255, 255))
        x = fr.right + 22
        K.t95(surf, "Unentschieden.", 18, (x, inner.y + 20))
        K.t95(surf, "Der Sieg geht", 17, (x, inner.y + 60), bold=False)
        K.t95(surf, "daher an:", 17, (x, inner.y + 84), bold=False)
        K.t95(surf, article, 22, (x, inner.y + 120), color=K.F_ACCENT)
        K.t95(surf, champ, K.fit_size(champ, inner.right - x - 8, sizes=(22, 20, 18)), (x, inner.y + 146), color=K.F_ACCENT)
        size, lines = self._comment_lines(self.einspruch or comment, inner.w - 24)
        for i, ln in enumerate(lines):  # between the champ (ends ~inner.y + 172) and Menü (inner.bottom - 132)
            K.t95(surf, ln, size, (inner.centerx, inner.y + 192 + i * (size + 6)), anchor="midtop", bold=False,
                  color=K.F_LATE if self.einspruch else K.F_INK)
        ready = self.last_tick - self.result_at >= RESULT_TAP_DELAY_SECONDS
        bw = (inner.w - 24) // 2
        self.rects["again"] = K.button(surf, pygame.Rect(inner.x + 8, inner.bottom - 72, bw, 64), "Nochmal", size=19, enabled=ready)
        self.rects["einspruch"] = K.button(surf, pygame.Rect(inner.x + 16 + bw, inner.bottom - 72, bw, 64), "Einspruch!", size=19,
                                           enabled=ready and self.einspruch is None)
        self.rects["menu"] = K.button(surf, pygame.Rect(inner.x + 8, inner.bottom - 132, inner.w - 16, 52), "Menü", size=17, enabled=ready)
