#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
KIEZ-KURIER (kiez-kurier.exe): the daily Lastenrad route puzzle of the
KiezOS 161 "Spiele" menu, a party_games._Game like PATRIAPUTT.

One puzzle per day, generated from the local date, so it changes at midnight
and is the same for everyone in the WG - people compare solve times.

The rules (also on the "Wie geht's?" screen):
- Drag the Lastenrad from the KOLLEKTIV to the SPÄTI in one route that uses
  every free street cell exactly once.
- BAUSTELLE: closed.
- KREISEL: you have to turn here.
- FAHRRADSTRASSE: straight through, no turning.
- EINBAHNSTRASSE: you may come in from anywhere, but must leave in the
  arrow's direction.
The clues only talk about the route's local shape (turn / straight / exit
direction) - no numbers, no visiting order. Moves that break a rule on the
spot are refused with a little message, the global "every street once" is
the actual puzzle.

Generation (seeded by the ISO date, ~20 ms mean / <100 ms max per day on a
dev Mac, so a few 100 ms on a Pi; nothing at import, cached per day): a
random Hamiltonian path on the 6x7 grid (serpentine + backbite moves), twice
a few cells cut off its ends as Baustellen and backbitten on; then clues are
added where a second solution differs from the planted one until the solver
(bitboard DFS with dead-end, clue and connectivity pruning and a node budget,
so the result doesn't depend on machine speed) proves it unique, then
redundant clues are removed down to MIN_CLUES. A variant outside the quality
window (clue count, solver effort) is skipped for the next seed variant.

Closing the game mid-route (x, the 60 s games idle timeout) keeps the route
and time in memory for RESUME_SECONDS: the start screen then offers WEITER.

Input: PiDashboard.py passes the finger down as tap(), movement as drag()
and lifting as release(). Dragging back over the route undoes it, tapping a
route cell cuts the route back to there.
"""

import datetime
import math
import random

import pygame

import kiezos as K
import party_games

# ------------------------------------------------------------ puzzle tuning
ROWS, COLS = 7, 6  # portrait grid
BACKBITE_MOVES = 300
MAX_CUT = 2  # Baustellen: up to this many cells cut off each end of the route, twice (see random_route)
MIN_CLUES, MAX_CLUES = 5, 10
MIN_NODES, MAX_NODES = 80, 800  # solver nodes to prove uniqueness: fewer = just follow forced moves, more = too much trial and error
NODE_BUDGET = 3000  # per solver call; over budget = variant rejected
MAX_VARIANTS = 40

UP, RIGHT, DOWN, LEFT = 0, 1, 2, 3
DIR_RC = ((-1, 0), (0, 1), (1, 0), (0, -1))

TURN, STRAIGHT = "turn", "straight"  # clue kinds; an arrow clue is the int exit direction


def today():
    """Puzzle day (tests replace this)."""
    return datetime.date.today()


# ------------------------------------------------------------ bitboard helpers
# Cell (r, c) = bit r * W + c with one padding column, so shifting by 1 never
# wraps into the next row.
W = COLS + 1
VALID = sum(1 << (r * W + c) for r in range(ROWS) for c in range(COLS))
SHIFT = (-W, 1, W, -1)  # bit offset per direction


def bit(r, c):
    return 1 << (r * W + c)


def _popcount(m):
    return bin(m).count("1")


# ------------------------------------------------------------ solver
class Puzzle:
    """free cells, start/end (r, c), clues {(r, c): TURN | STRAIGHT | dir}."""

    def __init__(self, blocked, start, end, clues, solution=None, day=None):
        self.blocked = list(blocked)
        self.start, self.end = start, end
        self.clues = dict(clues)
        self.solution = solution  # planted route, list of (r, c)
        self.day = day
        self.free = VALID & ~sum(bit(r, c) for r, c in self.blocked)
        self.total = _popcount(self.free)

    def is_free(self, r, c):
        return 0 <= r < ROWS and 0 <= c < COLS and self.free & bit(r, c) != 0

    def exit_ok(self, cell, din, d):
        """May the route leave `cell` (entered moving din, None = start) in direction d?"""
        clue = self.clues.get(cell)
        if clue is None or din is None:
            return True
        if clue == TURN:
            return d != din
        if clue == STRAIGHT:
            return d == din
        return d == clue


def solve(p, limit=2, budget=NODE_BUDGET):
    """Up to `limit` complete routes start -> end. Returns (routes, nodes, finished)
    - finished False if the node budget ran out first.

    Bitboard DFS. After every step the rest must stay possible: no remaining
    cell (but the end) with fewer than 2 ways in/out, clue cells still able to
    turn / go straight / leave along their arrow, everything left reachable;
    and a neighbour of the head with exactly 2 ways must be the next step."""
    clue_at = {}
    turn_m = straight_m = 0
    arrow_m = [0, 0, 0, 0]
    for (r, c), clue in p.clues.items():
        clue_at[r * W + c] = clue
        if clue == TURN:
            turn_m |= bit(r, c)
        elif clue == STRAIGHT:
            straight_m |= bit(r, c)
        else:
            arrow_m[clue] |= bit(r, c)
    a_up, a_right, a_down, a_left = arrow_m
    end_i = p.end[0] * W + p.end[1]
    end_b = 1 << end_i
    free = p.free
    total = p.total
    nb_mask = {}
    for i in range(ROWS * W):
        if free >> i & 1:
            nb_mask[i] = ((1 << i << 1) | (1 << i >> 1) | (1 << i << W) | (1 << i >> W)) & free
    routes = []
    nodes = [0]
    path = [p.start[0] * W + p.start[1]]

    def check(head, visited):
        """-1 = dead, else the forced next cell or None."""
        rem = free & ~visited
        avail = rem | (1 << head)
        # bit x of up_av is set if the cell above x is available, etc.
        up_av, down_av, left_av, right_av = avail << W, avail >> W, avail << 1, avail >> 1
        n1, n2, n3, n4 = up_av & rem, down_av & rem, left_av & rem, right_av & rem
        two = (n1 & n2) | (n1 & n3) | (n1 & n4) | (n2 & n3) | (n2 & n4) | (n3 & n4)
        if (rem & ~end_b) & ~two:
            return -1
        if rem & straight_m & ~((up_av & down_av) | (left_av & right_av)):
            return -1
        if rem & turn_m & ~((up_av | down_av) & (left_av | right_av)):
            return -1
        r_up, r_down, r_left, r_right = rem << W, rem >> W, rem << 1, rem >> 1  # exit target still free
        if rem & ((a_up & ~r_up) | (a_down & ~r_down) | (a_left & ~r_left) | (a_right & ~r_right)):
            return -1
        reach = 1 << head
        while True:
            nxt = (reach | (reach << 1) | (reach >> 1) | (reach << W) | (reach >> W)) & avail
            if nxt == reach:
                break
            reach = nxt
        if reach & rem != rem:
            return -1
        forced = None
        m = nb_mask[head] & rem & ~end_b
        while m:
            low = m & -m
            m ^= low
            i = low.bit_length() - 1
            if bin(nb_mask[i] & avail).count("1") == 2:
                if forced is not None:
                    return -1
                forced = i
        return forced

    def rec(head, din, visited, count, forced):
        nodes[0] += 1
        if nodes[0] > budget:
            return True
        if head == end_i:
            if count == total:
                routes.append(list(path))
                return len(routes) >= limit
            return False
        clue = clue_at.get(head)
        for d in range(4):
            if din is not None and clue is not None:
                if clue == TURN:
                    if d == din:
                        continue
                elif clue == STRAIGHT:
                    if d != din:
                        continue
                elif d != clue:
                    continue
            t = head + SHIFT[d]
            if t < 0 or (forced is not None and t != forced):
                continue
            tb = 1 << t
            if not free & tb or visited & tb:
                continue
            nv = visited | tb
            if t == end_i:
                if count + 1 != total:
                    continue
                f = None
            else:
                f = check(t, nv)
                if f == -1:
                    continue
            path.append(t)
            stop = rec(t, d, nv, count + 1, f)
            path.pop()
            if stop:
                return True
        return False

    start_i = path[0]
    rec(start_i, None, 1 << start_i, 1, check(start_i, 1 << start_i))
    out = [[(i // W, i % W) for i in route] for route in routes]
    return out, nodes[0], nodes[0] <= budget


# ------------------------------------------------------------ generation
def _neighbours(r, c):
    for d, (dr, dc) in enumerate(DIR_RC):
        rr, cc = r + dr, c + dc
        if 0 <= rr < ROWS and 0 <= cc < COLS:
            yield d, (rr, cc)


def direction(a, b):
    return DIR_RC.index((b[0] - a[0], b[1] - a[1]))


def backbite(path, rng, moves):
    """Random backbite moves on a Hamiltonian path of the cells in `path`
    (each keeps it Hamiltonian, only the ends wander)."""
    for _ in range(moves):
        if rng.random() < 0.5:
            path.reverse()
        pos = {cell: i for i, cell in enumerate(path)}
        options = [cell for _, cell in _neighbours(*path[-1]) if pos.get(cell, len(path)) < len(path) - 2]
        if options:
            j = pos[rng.choice(options)]
            path[j + 1:] = path[j + 1:][::-1]
    return path


def random_route(rng):
    """(blocked cells, planted route): a random Hamiltonian path of the full
    grid, then twice: cut 0-MAX_CUT cells off each end as Baustellen and
    backbite on, so Baustellen and ends end up spread out."""
    path = [(r, c if r % 2 == 0 else COLS - 1 - c) for r in range(ROWS) for c in range(COLS)]
    path = backbite(path, rng, BACKBITE_MOVES)
    blocked = []
    for _ in range(2):
        a, b = rng.choice([(a, b) for a in range(MAX_CUT + 1) for b in range(MAX_CUT + 1) if 1 <= a + b])
        blocked += path[:a] + path[len(path) - b:]
        path = backbite(path[a:len(path) - b], rng, BACKBITE_MOVES // 3)
    return blocked, path


def shape(route, i):
    """(entry dir, exit dir) of route[i]; entry None at the start, exit None at the end."""
    din = direction(route[i - 1], route[i]) if i > 0 else None
    dout = direction(route[i], route[i + 1]) if i + 1 < len(route) else None
    return din, dout


def _clue_against(planted, other, rng):
    """A clue on a cell where `other` leaves differently than `planted` (excludes `other`)."""
    pi = {cell: i for i, cell in enumerate(planted)}
    oi = {cell: i for i, cell in enumerate(other)}
    cand = []
    for cell, i in pi.items():
        if i == 0 or i == len(planted) - 1:
            continue
        pin, pout = shape(planted, i)
        oin, oout = shape(other, oi[cell])
        if oout is None or (pin, pout) == (oin, oout):
            continue
        p_turn, o_turn = pin != pout, oin != oout if oin is not None else None
        if o_turn is not None and p_turn != o_turn:
            cand.append((cell, TURN if p_turn else STRAIGHT))
            cand.append((cell, TURN if p_turn else STRAIGHT))  # prefer the shape clues 2:1
        if pout != oout:
            cand.append((cell, pout))
    return rng.choice(cand) if cand else None


def generate(day, variant):
    """Puzzle of one seed variant, or None if it's not good enough."""
    rng = random.Random(f"kiezkurier-{day.isoformat()}-{variant}")
    blocked, planted = random_route(rng)
    p = Puzzle(blocked, planted[0], planted[-1], {}, solution=planted, day=day)
    # Add clues until the planted route is the only one.
    for _ in range(3 * MAX_CLUES):
        routes, nodes, finished = solve(p)
        if not finished:
            return None
        others = [rt for rt in routes if rt != planted]
        if not others:
            break
        clue = _clue_against(planted, others[0], rng)
        if clue is None:
            return None
        p.clues[clue[0]] = clue[1]
    else:
        return None
    # Remove clues that aren't needed anymore (random order).
    keys = list(p.clues)
    rng.shuffle(keys)
    for cell in keys:
        if len(p.clues) <= MIN_CLUES:  # a few redundant clues keep it friendly
            break
        clue = p.clues.pop(cell)
        routes, nodes, finished = solve(p)
        if not finished or len(routes) != 1:
            p.clues[cell] = clue
    routes, nodes, finished = solve(p)
    if not finished or len(routes) != 1 or not MIN_CLUES <= len(p.clues) <= MAX_CLUES or not MIN_NODES <= nodes <= MAX_NODES:
        return None
    kinds = {TURN if v == TURN else STRAIGHT if v == STRAIGHT else "arrow" for v in p.clues.values()}
    if len(kinds) < 2:
        return None
    p.nodes = nodes
    p.variant = variant
    return p


_DAILY = {}


def daily_puzzle(day):
    """The puzzle of a day (cached; deterministic, same on every start)."""
    if day not in _DAILY:
        for variant in range(MAX_VARIANTS):
            p = generate(day, variant)
            if p is not None:
                break
        else:
            raise RuntimeError(f"no KIEZ-KURIER puzzle for {day} in {MAX_VARIANTS} variants")
        _DAILY.clear()
        _DAILY[day] = p
    return _DAILY[day]


# ------------------------------------------------------------ look & layout (game surface, 480 x 764)
CELL = 70
SIGN = 48  # clue sign size in a cell
GRID_X, GRID_Y = (480 - COLS * CELL) // 2, 150  # top of the grid stays below the emergency-exit box (y < 144)
STREET = (236, 230, 250)
STREET_DONE = (255, 236, 246)
KERB = (190, 176, 222)
BLOCK = (92, 58, 150)  # the houses between the streets
ROUTE = K.PINK
ROUTE_WIN = (255, 208, 72)
SIGN_BLUE = (30, 84, 196)
BAU_RED, BAU_WHITE = (226, 50, 40), (250, 246, 240)
OK_GREEN = (40, 170, 90)
WHITE = (255, 255, 255)

EPOCH = datetime.date(2026, 10, 31)  # Tour #1
RESUME_SECONDS = 600  # closed mid-route (idle timeout, x): the route waits this long
REFUSE_FLASH = 0.45
WIN_ROLL_SECONDS = 1.6  # the wheel rolls the finished route ...
WIN_BANNER_SECONDS = 1.2  # ... then GELIEFERT! ... then the Bestenliste

STATUS_IDLE = [
    "Das Rad will zum Späti.",
    "Kein Stress. Doch: Stoppuhr.",
    "Lastenrad > SUV.",
    "Klingeln ist kostenlos.",
]
REFUSE_TEXT = {
    "blocked": "Baustelle. Seit 2019. Da geht nix.",
    "visited": "Da warst du schon - jede Straße nur 1x!",
    TURN: "Am Kreisel musst du abbiegen!",
    STRAIGHT: "Fahrradstraße: geradeaus durch!",
    "arrow": "Einbahnstraße! Nur in Pfeilrichtung raus.",
    "early": "Späti hat noch zu - erst alle Straßen!",
    "far": "Fang am Rad an, Feld für Feld ziehen.",
}
WIN_LINES = [
    "Mate geliefert!",
    "Der Späti dankt.",
    "Kiez versorgt!",
    "Ohne Auto. Mit Stil.",
]

# Our resumable route: {"day", "path", "elapsed", "saved_at"} (in memory only).
_RESUME = None


def fmt_time(seconds):
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def tour_number(day):
    return (day - EPOCH).days + 1


def day_label(day):
    return f"{K.WD_SHORT[day.weekday()]} {day.day:02d}.{day.month:02d}."


def today_entries(name, day):
    """Today's rounds from the Bestenliste, fastest first."""
    return [e for e in party_games.top_list(name) if e.get("day") == day.isoformat()]


# ------------------------------------------------------------ cached sprites
_SPR = {}


def _cached(key, make):
    if key not in _SPR:
        _SPR[key] = make()
    return _SPR[key]


def _arrow_poly(cx, cy, length, width, d):
    """Arrow pointing in direction d (0 up, 1 right, 2 down, 3 left), centred."""
    h, w, head = length / 2, width / 2, length * 0.42
    pts = [(-w * 0.45, h), (w * 0.45, h), (w * 0.45, -h + head), (w, -h + head), (0, -h), (-w, -h + head), (-w * 0.45, -h + head)]
    a = d * math.pi / 2
    ca, sa = math.cos(a), math.sin(a)
    return [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts]


def sign_surface(kind, size):
    """Clue sign: TURN = blue Kreisel sign, STRAIGHT = blue Fahrradstraße
    sign (bike), an int = blue Einbahnstraße plate with arrow, "blocked" =
    Baustelle barrier. Drawn at 3x and smoothscaled for clean edges."""
    def make():
        big = size * 3
        s = pygame.Surface((big, big), pygame.SRCALPHA)
        c = big // 2
        if kind == "blocked":
            bw, bh = int(big * 0.9), int(big * 0.34)
            bar = pygame.Rect(0, 0, bw, bh)
            bar.center = (c, int(big * 0.42))
            stripes = pygame.Surface(bar.size, pygame.SRCALPHA)
            stripes.fill(BAU_WHITE)
            for x in range(-bh, bw + bh, bh):
                pygame.draw.polygon(stripes, BAU_RED, [(x, bh), (x + bh // 2, bh), (x + bh, 0), (x + bh // 2, 0)])
            s.blit(stripes, bar)
            pygame.draw.rect(s, K.INK, bar, max(3, big // 30))
            for lx in (bar.x + bw // 6, bar.right - bw // 6):  # legs
                pygame.draw.line(s, K.INK, (lx, bar.bottom), (lx - big // 12, int(big * 0.9)), max(4, big // 24))
                pygame.draw.line(s, K.INK, (lx, bar.bottom), (lx + big // 12, int(big * 0.9)), max(4, big // 24))
            pygame.draw.circle(s, (255, 180, 40), (bar.x + bw // 6, bar.y - big // 14), big // 14)  # blinker
            pygame.draw.circle(s, K.INK, (bar.x + bw // 6, bar.y - big // 14), big // 14, max(2, big // 60))
        elif isinstance(kind, int):  # Einbahnstraße plate, long side along the arrow
            long, short = int(big * 0.94), int(big * 0.5)
            plate = pygame.Rect(0, 0, short, long) if kind in (UP, DOWN) else pygame.Rect(0, 0, long, short)
            plate.center = (c, c)
            pygame.draw.rect(s, WHITE, plate, border_radius=big // 14)
            pygame.draw.rect(s, SIGN_BLUE, plate.inflate(-big // 18, -big // 18), border_radius=big // 18)
            pygame.draw.rect(s, K.INK, plate, max(3, big // 40), border_radius=big // 14)
            pygame.draw.polygon(s, WHITE, _arrow_poly(c, c, long * 0.78, short * 0.62, kind))
        else:
            r = int(big * 0.46)
            pygame.draw.circle(s, WHITE, (c, c), r)
            pygame.draw.circle(s, SIGN_BLUE, (c, c), int(r * 0.9))
            pygame.draw.circle(s, K.INK, (c, c), r, max(3, big // 40))
            if kind == TURN:  # three arrows chasing each other in a circle
                rr = r * 0.55
                lw = max(4, big // 13)
                for k in range(3):
                    a0 = k * 2 * math.pi / 3 + 0.35
                    pts = [(c + rr * math.cos(a0 + t * 0.12), c + rr * math.sin(a0 + t * 0.12)) for t in range(12)]
                    pygame.draw.lines(s, WHITE, False, pts, lw)
                    a1 = a0 + 11 * 0.12
                    tip = (c + rr * math.cos(a1 + 0.45), c + rr * math.sin(a1 + 0.45))
                    side = [(c + (rr + lw * 1.2) * math.cos(a1), c + (rr + lw * 1.2) * math.sin(a1)),
                            (c + (rr - lw * 1.2) * math.cos(a1), c + (rr - lw * 1.2) * math.sin(a1))]
                    pygame.draw.polygon(s, WHITE, [tip] + side)
            else:  # STRAIGHT: Fahrradstraße bike
                lw = max(4, big // 22)
                wr = int(r * 0.3)
                wl, wrx, wy = c - int(r * 0.42), c + int(r * 0.42), c + int(r * 0.2)
                for x in (wl, wrx):
                    pygame.draw.circle(s, WHITE, (x, wy), wr, lw)
                seat, bar_ = (c - int(r * 0.12), c - int(r * 0.3)), (c + int(r * 0.28), c - int(r * 0.36))
                pedal = (c, wy)
                pygame.draw.lines(s, WHITE, False, [(wl, wy), seat, pedal, (wl, wy)], lw)
                pygame.draw.lines(s, WHITE, False, [pedal, (c + int(r * 0.22), c - int(r * 0.18)), (wrx, wy)], lw)
                pygame.draw.line(s, WHITE, seat, (c + int(r * 0.22), c - int(r * 0.18)), lw)
                pygame.draw.line(s, WHITE, (c + int(r * 0.22), c - int(r * 0.18)), bar_, lw)
                pygame.draw.line(s, WHITE, (seat[0] - lw * 2, seat[1]), (seat[0] + lw, seat[1]), lw)
        return pygame.transform.smoothscale(s, (size, size))
    return _cached(("sign", kind, size), make)


def place_surface(kind, size):
    """Start KOLLEKTIV (house with rainbow flag) / end SPÄTI (shop, 24/7) icon."""
    def make():
        big = size * 3
        s = pygame.Surface((big, big), pygame.SRCALPHA)
        lw = max(3, big // 40)
        if kind == "start":
            body = pygame.Rect(int(big * 0.18), int(big * 0.42), int(big * 0.64), int(big * 0.46))
            pygame.draw.rect(s, (255, 214, 90), body)
            roof = [(body.x - big // 14, body.y), (body.centerx, int(big * 0.14)), (body.right + big // 14, body.y)]
            pygame.draw.polygon(s, (226, 80, 120), roof)
            pygame.draw.polygon(s, K.INK, roof, lw)
            pygame.draw.rect(s, K.INK, body, lw)
            door = pygame.Rect(0, 0, big // 6, big // 4)
            door.midbottom = body.midbottom
            pygame.draw.rect(s, K.INK, door)
            px = body.right - big // 10
            pygame.draw.line(s, K.INK, (px, int(big * 0.3)), (px, int(big * 0.02)), lw)
            for i, col in enumerate([(230, 40, 50), (255, 150, 40), (255, 225, 0), (40, 170, 90), (40, 90, 230), (150, 60, 200)]):
                pygame.draw.rect(s, col, (px, int(big * 0.03) + i * big // 40, big // 4, big // 40 + 1))
        else:
            body = pygame.Rect(int(big * 0.12), int(big * 0.3), int(big * 0.76), int(big * 0.58))
            pygame.draw.rect(s, (120, 220, 230), body)
            pygame.draw.rect(s, K.INK, body, lw)
            awning = pygame.Rect(body.x - big // 20, body.y - big // 10, body.w + big // 10, big // 6)
            for i in range(6):
                col = (226, 50, 40) if i % 2 == 0 else WHITE
                pygame.draw.rect(s, col, (awning.x + i * awning.w // 6, awning.y, awning.w // 6 + 1, awning.h))
            pygame.draw.rect(s, K.INK, awning, lw)
            win = pygame.Rect(body.x + big // 12, body.y + big // 6, body.w // 2 - big // 12, body.h // 2)
            pygame.draw.rect(s, (255, 250, 200), win)
            pygame.draw.rect(s, K.INK, win, lw)
            for i in range(3):  # Mate bottles in the window
                bx = win.x + big // 30 + i * win.w // 3
                pygame.draw.rect(s, (255, 170, 40), (bx, win.bottom - big // 7, big // 22, big // 7 - lw))
            door = pygame.Rect(body.right - big // 4, body.bottom - big // 3, big // 6, big // 3)
            pygame.draw.rect(s, K.INK, door)
            pygame.draw.circle(s, (255, 214, 90), (door.right - big // 30, door.centery), big // 50)
        return pygame.transform.smoothscale(s, (size, size))
    return _cached(("place", kind, size), make)


def menu_icon_surface(size=32):
    """16px menu/title icon: a mini street map with a pink route snaking from
    a little house to a shop, scaled nearest-neighbour. No fonts."""
    s = pygame.Surface((16, 16), pygame.SRCALPHA)
    s.fill(BLOCK)
    for i in range(3):
        for j in range(3):
            pygame.draw.rect(s, STREET, (1 + j * 5, 1 + i * 5, 4, 4))
    route = [(3, 3), (13, 3), (13, 8), (3, 8), (3, 13), (13, 13)]
    pygame.draw.lines(s, ROUTE, False, route, 2)
    pygame.draw.rect(s, (255, 214, 90), (1, 1, 4, 4))  # Kollektiv
    s.set_at((3, 1), (226, 80, 120))
    pygame.draw.rect(s, (120, 220, 230), (11, 11, 4, 4))  # Späti
    pygame.draw.line(s, (226, 50, 40), (11, 11), (14, 11))
    pygame.draw.circle(s, K.INK, (13, 13), 2, 1)  # the wheel
    return pygame.transform.scale(s, (size, size))


# ------------------------------------------------------------ the game
class KiezKurierGame(party_games._Game):
    NAME = "KIEZ-KURIER"
    IDLE_TIMEOUT_SECONDS = 180  # thinking isn't idling (PiDashboard's GAMES idle timeout is 60 s)
    ICON = "kiezkurier"
    DESCRIPTION = "Das tägliche Lastenrad-Rätsel"
    SCORE_LABEL = "Zeit"
    SCORE_UNIT = ""
    LOWER_IS_BETTER = True

    @staticmethod
    def format_score(score):
        return fmt_time(score)

    # ---- setup --------------------------------------------------------
    def reset(self, now):
        super().reset(now)
        self.day = today()
        self.puzzle = daily_puzzle(self.day)
        self.path = [self.puzzle.start]
        self.started_at = now
        self.base_elapsed = 0.0
        self.elapsed = 0.0
        self.dragging = False
        self.drag_pos = None
        self.help_open = False
        self.refused = None  # (cell, reason, time)
        self.message = None  # (text, until)
        self.won_at = None
        self.resume = None
        if (_RESUME is not None and _RESUME["day"] == self.day and len(_RESUME["path"]) > 1
                and 0 <= now - _RESUME["saved_at"] <= RESUME_SECONDS):
            self.resume = _RESUME
        self.ready_buttons = {}
        self.play_buttons = {}
        self._static = None
        self._ready_surf = None
        self._help_surf = None

    def start(self):
        """First tap on the ready screen (without a route to resume)."""
        self._begin(None)

    def _begin(self, resume):
        global _RESUME
        self.state = "play"
        self.started_at = self.last_tick
        if resume is not None:
            self.path = list(resume["path"])
            self.base_elapsed = resume["elapsed"]
        else:
            self.path = [self.puzzle.start]
            self.base_elapsed = 0.0
            _RESUME = None
        self.elapsed = self.base_elapsed
        self.resume = None
        self._save()

    def _save(self):
        global _RESUME
        if self.state == "play" and self.won_at is None:
            _RESUME = {"day": self.day, "path": list(self.path), "elapsed": self.elapsed, "saved_at": self.last_tick}

    # ---- geometry -----------------------------------------------------
    @staticmethod
    def cell_rect(cell):
        return pygame.Rect(GRID_X + cell[1] * CELL, GRID_Y + cell[0] * CELL, CELL, CELL)

    @staticmethod
    def cell_center(cell):
        return GRID_X + cell[1] * CELL + CELL // 2, GRID_Y + cell[0] * CELL + CELL // 2

    @staticmethod
    def cell_at(x, y):
        c, r = (x - GRID_X) // CELL, (y - GRID_Y) // CELL
        if 0 <= r < ROWS and 0 <= c < COLS:
            return int(r), int(c)
        return None

    @property
    def head(self):
        return self.path[-1]

    def remaining(self):
        return self.puzzle.total - len(self.path)

    # ---- input --------------------------------------------------------
    def tap(self, x, y):
        self.tap_pos = (x, y)
        if self.state == "ready":
            return self._ready_tap(x, y)
        return super().tap(x, y)

    def _ready_tap(self, x, y):
        if self.show_close and self.close_rect.collidepoint((x, y)):
            return "close"
        if x < 100 and y < 144:  # emergency-exit box: never a button
            return None
        if self.resume is not None:
            hit = next((k for k, r in self.ready_buttons.items() if r.collidepoint((x, y))), None)
            if hit == "resume":
                self._begin(self.resume)
            elif hit == "new":
                self._begin(None)
            return None
        self.start()
        return None

    def play_tap(self):
        x, y = self.tap_pos
        if self.won_at is not None:
            return
        if self.help_open:
            if not (x < 100 and y < 144):
                self.help_open = False
            return
        hit = next((k for k, r in self.play_buttons.items() if r.collidepoint((x, y))), None)
        if hit == "help":
            self.help_open = True
            self.dragging = False
            return
        if hit == "reset":
            self.path = [self.puzzle.start]
            self.dragging = False
            self._say("Zurück zum Kollektiv. Neue Runde, neues Glück.")
            self._save()
            return
        cell = self.cell_at(x, y)
        if cell is None:
            return
        self.drag_pos = (x, y)
        if cell in self.path:
            del self.path[self.path.index(cell) + 1:]
            self.dragging = True
            self._save()
        elif self._adjacent(self.head, cell):
            self.dragging = self.try_move(cell)
        else:
            self.dragging = False
            self._refuse(cell, "far")

    def drag(self, x, y):
        if self.state != "play" or not self.dragging or self.help_open or self.won_at is not None:
            return
        x0, y0 = self.drag_pos
        steps = max(1, int(math.hypot(x - x0, y - y0) / (CELL / 4)))
        for k in range(1, steps + 1):  # fast swipes: walk every cell on the way
            cell = self.cell_at(x0 + (x - x0) * k / steps, y0 + (y - y0) * k / steps)
            if cell is None or cell == self.head:
                continue
            if len(self.path) >= 2 and cell == self.path[-2]:
                self.path.pop()
                self._save()
            elif self._adjacent(self.head, cell):
                fresh = self.refused is None or self.refused[0] != cell or self.last_tick - self.refused[2] > REFUSE_FLASH
                if fresh:  # don't re-refuse (and re-flash) the same cell on every motion event
                    self.try_move(cell)
            if self.won_at is not None:
                break
        self.drag_pos = (x, y)

    def release(self):
        self.dragging = False

    @staticmethod
    def _adjacent(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1

    def why_not(self, cell):
        """None if the route may go from its head to the adjacent `cell`, else the reason."""
        p = self.puzzle
        if not p.is_free(*cell):
            return "blocked"
        if cell in self.path:
            return "visited"
        d = direction(self.head, cell)
        din = direction(self.path[-2], self.head) if len(self.path) >= 2 else None
        if not p.exit_ok(self.head, din, d):
            clue = p.clues[self.head]
            return clue if clue in (TURN, STRAIGHT) else "arrow"
        if cell == p.end and len(self.path) + 1 < p.total:
            return "early"
        return None

    def try_move(self, cell):
        reason = self.why_not(cell)
        if reason is not None:
            self._refuse(cell, reason)
            return False
        self.path.append(cell)
        self._save()
        if cell == self.puzzle.end and len(self.path) == self.puzzle.total:
            self._win()
        return True

    def _refuse(self, cell, reason):
        self.refused = (cell, reason, self.last_tick)
        text = REFUSE_TEXT[reason]
        if reason == "early":
            text = f"Späti hat noch zu - noch {self.remaining()} Straßen!"
        self._say(text, 2.2)

    def _say(self, text, seconds=2.0):
        self.message = (text, self.last_tick + seconds)

    def _win(self):
        global _RESUME
        self.won_at = self.last_tick
        self.elapsed = self.base_elapsed + (self.last_tick - self.started_at)
        self.score = round(self.elapsed, 1)
        self.dragging = False
        self.help_open = False
        _RESUME = None

    # ---- frame --------------------------------------------------------
    def step(self, dt):
        if self.state != "play":
            return
        if self.won_at is None:
            self.elapsed = self.base_elapsed + (self.last_tick - self.started_at)
            if _RESUME is not None:
                _RESUME["elapsed"] = self.elapsed
                _RESUME["saved_at"] = self.last_tick
        elif self.last_tick - self.won_at >= WIN_ROLL_SECONDS + WIN_BANNER_SECONDS:
            self.game_over(random.choice(WIN_LINES))

    def game_over(self, text):
        super().game_over(text)
        entries = today_entries(self.NAME, self.day)
        mine = next(i for i, e in enumerate(entries) if e.get("id") == self.entry_id)
        self.over_text = f"{text} Heute Platz {mine + 1}/{len(entries)}"

    def _entry_extra(self):
        return {"day": self.day.isoformat()}

    def _draw_entry_mark(self, surf, entry, x, y):
        if entry.get("day") == self.day.isoformat():  # today's puzzle: little pink "H"eute tab
            r = pygame.Rect(0, 0, 18, 18)
            r.midright = (x, y)
            pygame.draw.rect(surf, ROUTE, r, border_radius=4)
            pygame.draw.rect(surf, K.INK, r, 1, border_radius=4)
            K.t95(surf, "H", 13, r.center, color=K.INK, anchor="center")

    # ---- drawing ------------------------------------------------------
    def draw(self, surf):
        if self.state == "ready":
            self._draw_ready_screen(surf)
            return
        if self.help_open:  # route can't change while the rules are open: one cached picture
            if self._help_surf is None:
                self._help_surf = self._static_layer().copy()
                self._draw_route(self._help_surf)
                self._draw_status(self._help_surf)
                self._draw_rules(self._help_surf, help_mode=True)
            surf.blit(self._help_surf, (0, 0))
            self._draw_hud_live(surf)
            return
        self._help_surf = None
        surf.blit(self._static_layer(), (0, 0))
        self._draw_hud_live(surf)
        self._draw_route(surf)
        self._draw_status(surf)
        if self.won_at is not None and self.state == "play" and self.last_tick - self.won_at >= WIN_ROLL_SECONDS:
            box = pygame.Rect(30, GRID_Y + ROWS * CELL // 2 - 90, self.width - 60, 170)
            inner = K.dialog(surf, box, "lieferschein.txt", icon=self.ICON, buttons=None)
            K.wordart(surf, "GELIEFERT!", 40, (inner.centerx, inner.y + 34), wave=6)
            K.t95(surf, f"in {fmt_time(self.score)}", 30, (inner.centerx, inner.y + 98), anchor="center")
        if self.state == "over":
            self._draw_over(surf)

    def _background(self):
        bg = K.desktop().subsurface((0, 36, self.width, self.height)).copy()
        return bg

    def _static_layer(self):
        """Desktop, HUD frame, the map window with the board, the buttons."""
        if self._static is None:
            s = self._background()
            p = self.puzzle
            hud = pygame.Rect(8, 6, self.width - 16, 92)
            K.bevel(s, hud)
            K.t95(s, f"TOUR #{tour_number(self.day)}", 24, (hud.x + 12, hud.y + 10))
            K.t95(s, day_label(self.day), 18, (hud.x + 12, hud.y + 42), color=K.F_DARK)
            K.t95(s, f"{p.total} Straßen", 15, (hud.x + 12, hud.y + 66), color=K.F_DARK, bold=False)
            win = pygame.Rect(GRID_X - 12, GRID_Y - 40, COLS * CELL + 24, ROWS * CELL + 52)
            K.window(s, win, "kiezplan.txt - Kollektiv -> Späti", icon=self.ICON, buttons=None)
            board = pygame.Rect(GRID_X - 4, GRID_Y - 4, COLS * CELL + 8, ROWS * CELL + 8)
            pygame.draw.rect(s, BLOCK, board)
            pygame.draw.rect(s, K.F_DARK, board, 2)
            for r in range(ROWS):
                for c in range(COLS):
                    rect = self.cell_rect((r, c)).inflate(-6, -6)
                    if not p.is_free(r, c):
                        pygame.draw.rect(s, (70, 44, 110), rect, border_radius=6)
                        img = sign_surface("blocked", CELL - 22)
                        s.blit(img, img.get_rect(center=rect.center))
                        continue
                    pygame.draw.rect(s, STREET, rect, border_radius=6)
                    pygame.draw.rect(s, KERB, rect, 2, border_radius=6)
            bottom = win.bottom + 6
            half = (self.width - 16 - 8) // 2
            self.play_buttons = {
                "help": pygame.Rect(8, self.height - 62, half, 54),
                "reset": pygame.Rect(8 + half + 8, self.height - 62, half, 54),
            }
            K.button(s, self.play_buttons["help"], "Wie geht's?", size=18)
            K.button(s, self.play_buttons["reset"], "Von vorn", size=18)
            self.status_rect = pygame.Rect(8, bottom, self.width - 16, self.play_buttons["help"].y - bottom - 6)
            self._static = s
        return self._static

    def _draw_hud_live(self, surf):
        """Timer (7-segment, like uhr.exe) and today's best."""
        txt = fmt_time(self.score if self.won_at is not None else self.elapsed)
        dw, dh, gap = 24, 42, 7
        width = (len(txt) - 1) * (dw + gap) + 12
        lcd = pygame.Rect(0, 0, width + 20, dh + 16)
        lcd.topright = (self.width - 18, 14)
        K.bevel(surf, lcd, sunken=True, face=K.CLOCK_OFF)
        x, y = lcd.x + 10, lcd.y + 8
        for ch in txt:
            if ch == ":":
                if self.won_at is not None or int(self.last_tick * 2) % 2 == 0:
                    pygame.draw.rect(surf, K.CLOCK_ON, (x, y + 11, 5, 5))
                    pygame.draw.rect(surf, K.CLOCK_ON, (x, y + 27, 5, 5))
                x += 12
                continue
            K.seven_seg(surf, ch, x, y, dw, dh)
            x += dw + gap
        entries = today_entries(self.NAME, self.day)
        line = (f"Heute best: {fmt_time(entries[0]['score'])} {party_games.entry_name(entries[0])}" if entries
                else "Heute noch niemand durch")
        K.t95(surf, party_games._fit(K.font(14, False), line, 250), 14, (self.width - 18, 82), color=K.F_DARK, bold=False,
              anchor="midright")

    def _draw_route(self, surf):
        p = self.puzzle
        done = set(self.path)
        win = self.won_at is not None
        # visited streets get a warm tint, clue signs + start/end on top
        for cell in self.path:
            pygame.draw.rect(surf, STREET_DONE, self.cell_rect(cell).inflate(-10, -10), border_radius=5)
        pts = [self.cell_center(c) for c in self.path]
        col = ROUTE_WIN if win else ROUTE
        if len(pts) >= 2:
            pygame.draw.lines(surf, K.INK, False, pts, 24)
            for q in pts:
                pygame.draw.circle(surf, K.INK, q, 12)
            pygame.draw.lines(surf, col, False, pts, 16)
            for q in pts:
                pygame.draw.circle(surf, col, q, 8)
        for cell, clue in p.clues.items():
            img = sign_surface(clue, SIGN)
            cx, cy = self.cell_center(cell)
            surf.blit(img, img.get_rect(center=(cx, cy)))
            if cell in done and cell != self.head:
                ox, oy = cx + 23, cy - 23
                pygame.draw.circle(surf, OK_GREEN, (ox, oy), 9)
                pygame.draw.circle(surf, K.INK, (ox, oy), 9, 2)
                pygame.draw.lines(surf, WHITE, False, [(ox - 5, oy), (ox - 1, oy + 4), (ox + 5, oy - 5)], 3)
        for kind, cell in (("start", p.start), ("end", p.end)):
            img = place_surface(kind, 46)
            cx, cy = self.cell_center(cell)
            surf.blit(img, img.get_rect(center=(cx, cy - 6)))
            label = "KOLLEKTIV" if kind == "start" else "SPÄTI"
            K.t95(surf, label, 11 if kind == "start" else 13, (cx, cy + 25), color=K.INK, anchor="center")
        if self.refused is not None and self.last_tick - self.refused[2] < REFUSE_FLASH:
            rect = self.cell_rect(self.refused[0]).inflate(-4, -4)
            pygame.draw.rect(surf, K.F_LATE, rect, 5, border_radius=7)
        self._draw_wheel(surf)

    def _wheel_pos(self):
        """Centre and roll angle of the wheel: at the route's head, or rolling
        the whole finished route after a win."""
        pts = [self.cell_center(c) for c in self.path]
        if self.won_at is None or len(pts) < 2:
            return pts[-1], len(pts) * 0.9, (pts[-1][0] - pts[-2][0]) if len(pts) >= 2 else 1
        t = min(1.0, (self.last_tick - self.won_at) / WIN_ROLL_SECONDS)
        f = t * (len(pts) - 1)
        i = min(int(f), len(pts) - 2)
        k = f - i
        a, b = pts[i], pts[i + 1]
        return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k), f * 0.9, b[0] - a[0]

    def _draw_wheel(self, surf):
        """The friend's dadaist wheel: one wheel, a spoke cross that rolls
        with the route, a pink flag on a stick."""
        (cx, cy), angle, dx = self._wheel_pos()
        cx, cy = int(cx), int(cy)
        r = 21
        flip = -1 if dx < 0 else 1
        pygame.draw.line(surf, K.INK, (cx, cy), (cx - flip * 10, cy - 38), 3)  # flag stick
        flag = [(cx - flip * 10, cy - 38), (cx - flip * 30, cy - 32), (cx - flip * 10, cy - 26)]
        pygame.draw.polygon(surf, ROUTE, flag)
        pygame.draw.polygon(surf, K.INK, flag, 2)
        pygame.draw.circle(surf, K.INK, (cx, cy), r)
        pygame.draw.circle(surf, (210, 205, 225), (cx, cy), r - 6)
        a = angle * flip
        for k in range(4):
            ang = a + k * math.pi / 4
            ex, ey = math.cos(ang) * (r - 6), math.sin(ang) * (r - 6)
            pygame.draw.line(surf, K.F_DARK, (cx - ex, cy - ey), (cx + ex, cy + ey), 2)
        pygame.draw.circle(surf, ROUTE, (cx, cy), 5)
        pygame.draw.circle(surf, K.INK, (cx, cy), 5, 1)

    def _draw_status(self, surf):
        rect = self.status_rect
        K.tooltip(surf, rect)
        if self.won_at is not None:
            text = "Geliefert! Der Späti klatscht."
        elif self.message is not None and self.last_tick < self.message[1]:
            text = self.message[0]
        elif len(self.path) == 1:
            text = "Zieh das Rad mit dem Finger los!"
        else:
            n = self.remaining()
            text = f"Noch {n} Straße{'' if n == 1 else 'n'} bis zum Späti. " + STATUS_IDLE[int(self.last_tick / 6) % len(STATUS_IDLE)]
        lines = K.wrap(text, 16, rect.w - 20)[:2]
        y = rect.centery - (len(lines) * 20) // 2
        for ln in lines:
            K.t95(surf, ln, 16, (rect.x + 10, y), color=K.F_INK, bold=False)
            y += 20

    # ---- rules / ready screen ------------------------------------------
    def _draw_ready_screen(self, surf):
        if self._ready_surf is None:
            s = self._background()
            self._draw_rules(s, help_mode=False)
            self._ready_surf = s
        surf.blit(self._ready_surf, (0, 0))
        if self.resume is None and int(self.last_tick * 2) % 2 == 0:
            K.t95(surf, "Tippen zum Losfahren - Stoppuhr läuft dann!", 15, (self.width // 2, self.height - 34),
                  color=WHITE, anchor="center")

    def _draw_rules(self, surf, help_mode):
        """Wie geht's?: the rules with the real signs, today's solvers, and
        LOS / WEITER / NEU (ready) or "Weiter rätseln" (help during play)."""
        top = 6 if not help_mode else 104
        bottom = self.height - (66 if not help_mode else 70)
        win = pygame.Rect(10, top, self.width - 20, bottom - top)
        inner = K.dialog(surf, win, f"{self._exe()} - Wie geht's?", icon=self.ICON, buttons=None)
        y = inner.y + 4
        if not help_mode:
            K.wordart(surf, "KIEZ-KURIER", 34, (inner.centerx, y + 26), wave=5)
            y += 58
            K.t95(surf, f"Das tägliche Lastenrad-Rätsel  ·  Tour #{tour_number(self.day)}  ·  {day_label(self.day)}", 14,
                  (inner.centerx, y), color=K.F_ACCENT, anchor="midtop")
            y += 26
        for ln in K.wrap("Fahr vom KOLLEKTIV zum SPÄTI: eine Route, durch JEDE freie Straße genau einmal. "
                         "Finger aufs Rad und ziehen.", 17, inner.w - 16):
            K.t95(surf, ln, 17, (inner.x + 8, y))
            y += 23
        y += 8
        rows = [
            ("blocked", "Baustelle", "gesperrt. Wie immer."),
            (TURN, "Kreisel", "hier musst du abbiegen."),
            (STRAIGHT, "Fahrradstraße", "hier geradeaus durch."),
            (RIGHT, "Einbahnstraße", "raus nur in Pfeilrichtung (rein egal)."),
        ]
        for kind, name, rule in rows:
            box = pygame.Rect(inner.x + 8, y, 52, 52)
            pygame.draw.rect(surf, STREET, box, border_radius=6)
            pygame.draw.rect(surf, KERB, box, 2, border_radius=6)
            img = sign_surface(kind, 44)
            surf.blit(img, img.get_rect(center=box.center))
            K.t95(surf, name, 18, (box.right + 12, y + 3))
            lines = K.wrap(rule, 15, inner.right - box.right - 20, bold=False)
            for i, ln in enumerate(lines[:2]):
                K.t95(surf, ln, 15, (box.right + 12, y + 26 + i * 18), color=K.F_DARK, bold=False)
            y += 62
        y += 2
        for ln in K.wrap("Zurückziehen = rückgängig. Jeden Tag ein neues Rätsel, für die ganze WG dasselbe - "
                         "die schnellste Zeit gewinnt.", 15, inner.w - 16, bold=False):
            K.t95(surf, ln, 15, (inner.x + 8, y), color=K.F_DARK, bold=False)
            y += 19
        y += 8
        entries = today_entries(self.NAME, self.day)
        gb = pygame.Rect(inner.x + 2, y + 10, inner.w - 4, 0)
        if entries:
            lines = [(f"{i + 1}. {party_games._fit(K.font(15), party_games.entry_name(e), gb.w - 120)}", fmt_time(e["score"]))
                     for i, e in enumerate(entries[:2])]
            more = len(entries) - 2
            lines.append((f"Schon {len(entries)}x geliefert" + (f" (+{more} weitere)" if more > 0 else ""), ""))
        else:
            lines = [(ln, "") for ln in K.wrap("Heute noch niemand geliefert - sei die erste Rätsler*in!", 15, gb.w - 20)]
        gb.h = 24 + 19 * len(lines)
        K.groupbox(surf, gb, "Bestenliste heute")
        for i, (left, right) in enumerate(lines):
            K.t95(surf, left, 15, (gb.x + 10, gb.y + 14 + i * 19), color=K.F_INK)
            if right:
                K.t95(surf, right, 15, (gb.right - 10, gb.y + 14 + i * 19), color=K.F_INK, anchor="topright")
        btn_y = inner.bottom - 58
        self.ready_buttons = {}
        if help_mode:
            K.button(surf, pygame.Rect(inner.x, btn_y, inner.w, 58), "Weiter rätseln", size=20)
        elif self.resume is not None:
            half = (inner.w - 8) // 2
            self.ready_buttons["resume"] = K.button(surf, pygame.Rect(inner.x, btn_y, half, 58),
                                                    f"WEITER ({fmt_time(self.resume['elapsed'])})", size=18)
            self.ready_buttons["new"] = K.button(surf, pygame.Rect(inner.x + half + 8, btn_y, half, 58), "NEU STARTEN", size=18)
        else:
            K.button(surf, pygame.Rect(inner.x, btn_y, inner.w, 58), "LOS!", size=24)
