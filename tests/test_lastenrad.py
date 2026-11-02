#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless checks of LASTENRAD-SIMULATOR (lastenrad/), instantiated directly
(the main agent registers it in PiDashboard's Spiele menu). Simulated time,
highscores + stack pictures in a temp dir (never logs/). Screenshots of every
state: scratch/game_mockups/lastenrad/.

Covers: the data-driven item library; drag -> release exactly where let go
(no snapping); a held item never clipping into others; placed items can't be
grabbed; round items and the Einkaufswagen (on its wheels) roll; bike tilt
grows with an off-centre load and passes the point of no return; a drop is
game over only after the crash spectacle; two-finger rotation via finger()
and the hold-to-rotate buttons; moderate camera zoom; parallax houses only
from ~15 items; Tagesladung deterministic per date; Party elimination +
reset; Story level win with a time score; thumbnails stored and shown;
resume after closing; nothing tappable in the emergency-exit corner; frame
times; balance bots (careless / novice / good).

SDL_VIDEODRIVER=dummy .venv/bin/python tests/test_lastenrad.py
.venv/bin/python tests/test_lastenrad.py --bots 16     # balance statistics only (multi-process)
"""

import argparse
import datetime
import json
import math
import os
import random
import statistics
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import pygame  # noqa: E402

from kiosk import kiezos as K  # noqa: E402
from games import party_games  # noqa: E402
from games import lastenrad  # noqa: E402
from games.lastenrad import config as C  # noqa: E402
from games.lastenrad import game as G  # noqa: E402
from games.lastenrad import modes as M  # noqa: E402
from games.lastenrad import render as R  # noqa: E402
from games.lastenrad import sprites as S  # noqa: E402
from games.lastenrad.items import ITEMS_BY_ID, shape_bbox  # noqa: E402
from games.lastenrad.physics import World  # noqa: E402

OUT = os.path.join(REPO, "scratch", "game_mockups", "lastenrad")
TITLE_H = 36
FRAME = 1 / 30
DAY = datetime.date(2026, 11, 7)


# ------------------------------------------------------------ bots (also used for balance tuning)
def settle(w, max_s=2.5, min_s=0.6):
    t0 = w.t
    while w.t - t0 < max_s:
        w.step(1 / 30)
        if w.fail:
            return
        if w.t - t0 > min_s and w.max_speed() < 4:
            return


def _angles_for(d):
    minx, miny, maxx, maxy = d["bbox"]
    out = [0.0]
    if maxy - miny > 1.25 * (maxx - minx):
        out += [math.pi / 2, -math.pi / 2]
    if d["id"] in ("stuhl", "klapptisch", "einkaufswagen", "lastenrad2", "skateboard", "stehlampe", "staender",
                   "trophaee", "pflanze"):
        out.append(math.pi)
    return out


def _try(snap, d, x, a, edge_k):
    c = World.from_snapshot(snap)
    y = c.rest_y(d, x, a) + 3
    it = c.place(d, x, y, a)
    settle(c, 2.4, 1.2)
    if c.fail or c.max_speed() > 6:
        return None
    px, py = it.body.local_to_world((0, 0))
    if math.hypot(px - x, py - y) > 22 or abs(it.body.angle - a) > 0.35:
        return None  # tumbled into place: that's not a placement
    bottom = min(sh.bb.bottom for sh in it.shapes)
    cx, _, _ = c.com()
    ix = it.body.local_to_world(it.body.center_of_gravity)[0]
    return bottom + abs(math.degrees(c.tilt)) * 25 + abs(cx) * 0.4 + max(0.0, abs(ix) - 85) * edge_k


def _lookahead(w, d, rng, step, angles, pick_top, noise, anoise, gap, robust, edge_k):
    """Simulates candidate spots on copies of the world; a spot counts if it
    also holds when off by +-robust px. Picks one of the pick_top best, then
    places it with hand noise."""
    snap = w.snapshot(velocities=True)
    lo, hi = w.extent()
    xs = [x for x in range(int(lo) - 10, int(hi) + 11, step) if -175 <= x <= 175]
    scored = []
    for a in angles:
        for x in xs:
            rs = [_try(snap, d, x + dx, a, edge_k) for dx in ((0, -robust, robust) if robust else (0,))]
            if all(r is not None for r in rs):
                scored.append((rs[0], x, a))
    scored.sort()
    if scored:
        _, x, a = rng.choice(scored[:pick_top])
    else:
        x, a = rng.choice(xs), 0.0
    x += rng.gauss(0, noise)
    a += rng.gauss(0, anoise)
    return x, w.rest_y(d, x, a) + gap(rng), a


def bot_careless(w, d, rng):
    """Drops anywhere on the deck, a bit crooked, from up to 60 px."""
    x = rng.uniform(-110, 110)
    a = rng.gauss(0, 0.12)
    return x, w.rest_y(d, x, a) + rng.uniform(10, 60), a


def bot_novice(w, d, rng):
    """Sees which spots are safe, no strategy, no rotation, sloppy hands."""
    return _lookahead(w, d, rng, 24, [0.0], 3, 7, 0.04, lambda r: r.uniform(5, 25), 16, 2.5)


def bot_good(w, d, rng):
    """Best robust spot incl. rotations (turns chairs/tables/carts upside down), steady hands;
    round things get wedged into valleys (fine grid, small margin)."""
    if "round" in d["tags"]:
        return _lookahead(w, d, rng, 6, [0.0], 1, 1.5, 0.0, lambda r: 2, 3, 0.0)
    return _lookahead(w, d, rng, 18, _angles_for(d), 1, 4, 0.02, lambda r: 3, 7, 0.0)


BOTS = {"careless": bot_careless, "novice": bot_novice, "good": bot_good}


def bot_run(bot, seed, cap=120):
    """Items stacked before something fell / the bike tipped."""
    rng = random.Random(seed)
    w = World()
    director = M.Director(f"bot{seed}")
    for n in range(cap):
        d = director.get(n)
        x, y, a = bot(w, d, rng)
        w.place(d, x, y, a)
        settle(w)
        if w.fail:
            return n, w.fail[0]
    return cap, None


def _bot_worker(args):
    name, seed, cap = args
    return name, seed, bot_run(BOTS[name], seed, cap)


def bot_stats(seeds, cap=120):
    from multiprocessing import Pool
    jobs = [(name, s, cap) for name in ("careless", "novice", "good") for s in range(seeds)]
    res = {name: [] for name in BOTS}
    tips = 0
    t0 = time.time()
    with Pool(min(10, os.cpu_count() or 4)) as pool:
        for i, (name, seed, (n, kind)) in enumerate(pool.imap_unordered(_bot_worker, jobs)):
            res[name].append(n)
            tips += kind == "tip"
            print(f"[bots {i + 1}/{len(jobs)}] {name} seed {seed}: {n} items ({kind}) - {time.time() - t0:.0f}s", flush=True)
    print("\nBALANCE (items stacked before the first drop/tip):")
    for name, r in res.items():
        r.sort()
        print(f"  {name:8s} median {statistics.median(r):5.1f}  mean {statistics.mean(r):5.1f}  min {r[0]}  max {r[-1]}  {r}")
    print(f"  bike tip-overs: {tips} of {len(jobs)} runs", flush=True)
    return res


# ------------------------------------------------------------ game harness
def setup():
    pygame.init()
    screen = pygame.display.set_mode((480, 800))
    K.configure(os.path.join(REPO, "fonts") + "/", os.path.join(REPO, "icons") + "/",
                json.load(open(os.path.join(REPO, "themes", "kiezos.json")))["KIEZOS"])
    K.ICON_MAKERS["lastenrad"] = lastenrad.menu_icon_surface
    party_games.configure(tempfile.mkdtemp(prefix="lastenrad_scores_"))
    M.today = lambda: DAY
    os.makedirs(OUT, exist_ok=True)
    return screen


SCREEN = None
GAME_SURF = None


def new_game(now=1000.0):
    g = lastenrad.LastenradGame(480, 800 - TITLE_H, os.path.join(REPO, "fonts", "JetBrainsMono-Medium.ttf"),
                                os.path.join(REPO, "fonts", "JetBrainsMono-Bold.ttf"))
    g.show_close = False
    g.reset(now)
    return g


def frames(g, n=1):
    for _ in range(n):
        g.update(g.last_tick + FRAME)
        g.draw(GAME_SURF)


def shot(g, name):
    g.draw(GAME_SURF)
    K.game_title(SCREEN, "lastenrad-simulator.exe", "lastenrad")
    pygame.image.save(SCREEN, os.path.join(OUT, name))


def tap_ui(g, key):
    g.draw(GAME_SURF)
    r = g.ui_rects[key]
    assert g.tap(*r.center) is None
    frames(g)


BOXES = ["flightcase", "matekiste", "snackkiste", "lichtkoffer", "powerbank", "tasche"] * 10


def start(g, mode, boxes=True):
    """Starts a run from the menu; boxes=True swaps in a fixed sequence of
    plain boxes (checks that need a stack that stays put)."""
    G._RESUME = None
    g.reset(g.last_tick)
    tap_ui(g, {M.ENDLOS: "endlos", M.TAGES: "tages"}[mode])
    assert g.state == "play" and g.screen == "play" and g.run.mode == mode
    if boxes:
        g.run.director = M.Director(None, fixed=BOXES)


def slot_center(g):
    g.draw(GAME_SURF)
    return g.ui_rects["slot"].x + 46, 26


def drag_place(g, x, y, steps=12, release=True):
    """Grabs the current item from the bar and drags it to screen (x, y)."""
    sx, sy = slot_center(g)
    g.tap(sx, sy)
    assert g.hold is not None, "item not grabbed"
    for k in range(1, steps + 1):
        g.drag(sx + (x - sx) * k / steps, sy + (y - sy) * k / steps)
        frames(g)
    if release:
        g.release()
        frames(g)


def place_world(g, x_world, y_gap=3.0, angle=0.0):
    """Places the current item like a careful player would: lowered onto the
    stack at x (world), through the game's own release path."""
    run = g.run
    d = run.current()
    y = run.world.rest_y(d, x_world, angle) + y_gap
    run.release(d, x_world, y, angle)


def wait(g, seconds):
    frames(g, int(seconds / FRAME))


# ------------------------------------------------------------ checks
def check_items():
    assert 20 <= len(ITEMS_BY_ID) <= 40, len(ITEMS_BY_ID)
    for d in ITEMS_BY_ID.values():
        for key in ("id", "name", "sprite", "shapes", "mass", "friction", "restitution", "angular_damping", "difficulty",
                    "rarity", "tags", "earliest", "modes", "bbox"):
            assert key in d, (d["id"], key)
        img, _ = S.item_sprite(d)
        boxes = [shape_bbox(sh) for sh in d["shapes"]]
        minx, miny = min(b[0] for b in boxes), min(b[1] for b in boxes)
        maxx, maxy = max(b[2] for b in boxes), max(b[3] for b in boxes)
        assert img.get_width() >= (maxx - minx) * 0.9 and img.get_height() >= (maxy - miny) * 0.6, d["id"]
        w = World()  # every item alone on the deck stays there
        w.place(d, 0, w.rest_y(d, 0, 0) + 2, 0)
        settle(w, 3.0)
        assert w.fail is None, (d["id"], w.fail)
    kinds = {s[0] for d in ITEMS_BY_ID.values() for s in d["shapes"]}
    assert {"box", "circle", "capsule", "poly"} <= kinds, kinds
    assert any("person" in d["tags"] for d in ITEMS_BY_ID.values()) and any(d.get("parts") for d in ITEMS_BY_ID.values())
    sizes = [(d["bbox"][2] - d["bbox"][0]) for d in ITEMS_BY_ID.values()]
    assert statistics.median(sizes) >= 0.3 * C.DECK_LEN, "items should be big (spec §13)"
    print(f"items: {len(ITEMS_BY_ID)} load, paint and sit still alone on the deck; median width {statistics.median(sizes):.0f}")


def check_drag_release():
    g = new_game()
    start(g, M.ENDLOS)
    shot(g, "02_start.png")
    d = g.run.current()
    drag_place(g, 250, 450, release=False)
    shot(g, "03_holding.png")
    h = dict(g.hold)
    cam = g.run.cam
    wx, wy = cam.to_world(250, 450)
    assert abs(h["x"] - wx) < 1e-6, (h["x"], wx)  # exactly under the finger in x, lifted above it in y
    assert h["y"] > wy
    g.release()
    item = g.run.world.items[-1]
    ox, oy = item.body.local_to_world((0, 0))
    assert item.defn is d and abs(ox - h["x"]) < 1e-6 and abs(oy - h["y"]) < 1e-6 and abs(item.body.angle - h["angle"]) < 1e-9
    assert item.body.velocity.length == 0
    frames(g, 45)
    shot(g, "04_placed.png")
    # no snapping: releasing 23 px further right lands 23 px further right
    g2 = new_game()
    start(g2, M.ENDLOS)
    drag_place(g2, 273, 450)
    ox2 = g2.run.world.items[-1].body.local_to_world((0, 0))[0]
    assert abs((ox2 - ox) - 23 / cam.zoom) < 1e-6, (ox, ox2)
    # releasing back over the bar puts it back (not placed, not lost)
    drag_place(g2, 200, 30)
    assert len(g2.run.world.items) == 1 and g2.run.placed == 1
    print("drag: released exactly at the held pose, at rest, no snapping; back over the bar = not placed")


def check_no_clipping():
    g = new_game()
    start(g, M.ENDLOS)
    place_world(g, 0)
    wait(g, 1.5)
    w = g.run.world
    sx, sy = slot_center(g)
    g.tap(sx, sy)
    target = g.run.cam.to_screen(0, C.DECK_TOP)  # straight down through the placed item onto the deck
    for k in range(1, 40):
        g.drag(target[0], sy + (target[1] + 40 - sy) * k / 39)
        frames(g)
        h = g.hold
        assert w.probe_ok(h["defn"], h["x"], h["y"], h["angle"]), f"held item clips at step {k}"
    assert h["y"] > w.items[0].body.position.y  # it stopped on top
    for k in range(30):  # sideways along the top, rotating at the same time
        g.drag(target[0] - 60 + 4 * k, target[1] + 40)
        g._rotate_hold(0.03)
        frames(g)
        h = g.hold
        assert w.probe_ok(h["defn"], h["x"], h["y"], h["angle"]), f"held item clips while sliding ({k})"
    g.release()
    print("held item: never clips while dragged through / along the stack or rotated")


def check_not_grabbable():
    g = new_game()
    start(g, M.ENDLOS)
    place_world(g, 0)
    wait(g, 1.0)
    it = g.run.world.items[0]
    before = it.body.local_to_world((0, 0))
    px, py = g.run.cam.to_screen(*before)
    g.tap(px, py)
    assert g.hold is None
    g.drag(px + 80, py - 80)
    frames(g, 10)
    g.release()
    after = it.body.local_to_world((0, 0))
    assert math.hypot(after[0] - before[0], after[1] - before[1]) < 1.0 and len(g.run.world.items) == 1
    print("placed items: can't be grabbed or moved")


def _tilted_world(side=1):
    """A bike tilted ~2-3 deg (heavy load at one end)."""
    w = World()
    for k in range(2):
        d = ITEMS_BY_ID["bassbox"]
        w.place(d, side * 98, w.rest_y(d, side * 98, 0) + 2, 0)
        settle(w, 2.0)
    assert abs(w.tilt) > math.radians(1.2), math.degrees(w.tilt)
    return w


def check_rolling():
    w = _tilted_world()
    disco = ITEMS_BY_ID["discokugel"]
    ball = w.place(disco, -60, w.rest_y(disco, -60, 0) + 1, 0)
    w2 = _tilted_world()
    pb = w2.place(ITEMS_BY_ID["powerbank"], -60, w2.rest_y(ITEMS_BY_ID["powerbank"], -60, 0) + 1, 0)
    for _ in range(30):
        w.step(1 / 30)
        w2.step(1 / 30)
    bx = ball.body.local_to_world((0, 0))[0]
    assert bx > -60 + 15 and abs(ball.body.angle) > 0.5, (bx, ball.body.angle)  # rolled downhill, spinning
    assert abs(pb.body.local_to_world((0, 0))[0] + 60) < 3
    print(f"round: Discokugel rolled {bx + 60:.0f} px down the tilted deck (spun {math.degrees(-ball.body.angle):.0f} deg), "
          "a Powerbank stayed")

    cart = ITEMS_BY_ID["einkaufswagen"]
    w = _tilted_world()
    c1 = w.place(cart, -40, w.rest_y(cart, -40, 0) + 1, 0)
    w2 = _tilted_world()
    c2 = w2.place(cart, -40, w2.rest_y(cart, -40, math.pi) + 1, math.pi)
    for _ in range(60):
        w.step(1 / 30)
        w2.step(1 / 30)
    x1 = c1.body.local_to_world((0, 0))[0] + 40
    x2 = c2.body.local_to_world((0, 0))[0] + 40
    wheel_spin = abs(c1.parts[0][1].angle - c1.body.angle)
    assert x1 > 20 and wheel_spin > 1.0 and x2 < 8, (x1, wheel_spin, x2)  # x1: rolls until it bumps the Bassboxes; x2: just settles
    print(f"Einkaufswagen: on its wheels rolled {x1:.0f} px (wheels spun {math.degrees(wheel_spin):.0f} deg), "
          f"upside down {x2:.1f} px")


def check_tilt():
    w = World()
    tilts = []
    for k in range(12):
        d = ITEMS_BY_ID["flightcase"]
        w.place(d, 90, w.rest_y(d, 90, 0) + 2, 0)
        t0 = w.t
        while w.t - t0 < 2.5 and not w.fail:
            w.step(1 / 30)
        tilts.append(-w.tilt)
        if w.fail:
            break
    assert w.fail is not None and w.fail[0] == "tip", (w.fail, [round(math.degrees(t), 1) for t in tilts])
    held = tilts[:-1]
    assert all(b > a for a, b in zip(held, held[1:])), [round(math.degrees(t), 2) for t in tilts]
    assert held[0] < math.radians(2.0) and held[-1] > C.CATCH_ANGLE, [round(math.degrees(t), 2) for t in tilts]
    print("tilt: grows with the off-centre load "
          f"({', '.join(f'{math.degrees(t):.1f}' for t in held)} deg), then past the point of no return -> tip "
          f"after {len(tilts)} Flightcases")


def check_crash_then_over():
    g = new_game()
    start(g, M.ENDLOS)
    for x in (-40, 50, 0):
        place_world(g, x)
        wait(g, 1.2)
    # the 4th item is dropped beside the bike, onto the grass
    d = g.run.current()
    g.run.release(d, 260, 60, 0.0)
    for _ in range(30):
        frames(g)
        if g.run.phase == "crash":
            break
    assert g.run.phase == "crash" and g.state == "play", (g.run.phase, g.state)
    crash_at = g.last_tick
    frames(g, 8)
    shot(g, "08_crash.png")
    while g.state != "over":
        frames(g)
        assert g.last_tick - crash_at < 10
    crash_s = g.last_tick - crash_at
    assert crash_s >= C.CRASH_SECONDS - 0.1
    assert g.score == 3, g.score  # the dropped one doesn't count
    frames(g, 30)
    shot(g, "09_result.png")
    assert g.entry_id is not None and party_games.top_list(g.score_key())[0]["score"] == 3
    print(f"drop: crash spectacle for {crash_s:.1f} s, then the Bestenliste (score 3)")
    return g


def check_rotation():
    g = new_game()
    start(g, M.ENDLOS)
    drag_place(g, 240, 420, release=False)
    a0 = g.hold["angle"]
    g.finger("down", 1, 240, 440)
    g.finger("down", 2, 340, 440)
    for k in range(1, 7):  # second finger moves 30 deg clockwise around the first (on screen)
        ang = math.radians(5 * k)
        g.finger("move", 2, 240 + 100 * math.cos(ang), 440 + 100 * math.sin(ang))
        frames(g)
    assert abs((g.hold["angle"] - a0) + math.radians(30)) < 1e-6, math.degrees(g.hold["angle"] - a0)
    g.finger("move", 1, 200, 400)  # moving both by the same amount doesn't rotate
    g.finger("move", 2, 240 + 100 * math.cos(math.radians(30)) - 40, 440 + 100 * math.sin(math.radians(30)) - 40)
    assert abs((g.hold["angle"] - a0) + math.radians(30)) < 1e-6
    g.finger("up", 2, 0, 0)
    g.finger("up", 1, 0, 0)
    # second finger on a rotate button while holding
    a1 = g.hold["angle"]
    r = g.ui_rects["rot_l"]
    g.finger("down", 1, 240, 420)
    g.finger("down", 3, *r.center)
    frames(g, 15)
    g.finger("up", 3, 0, 0)
    assert abs(g.hold["angle"] - a1 - C.ROTATE_SPEED * 15 * FRAME) < 0.02, math.degrees(g.hold["angle"] - a1)
    g.release()
    g.finger("up", 1, 0, 0)
    frames(g)
    # single finger: hold the button, the next item turns before it's picked up
    r = g.ui_rects["rot_r"]
    g.tap(*r.center)
    frames(g, 12)
    shot(g, "05_rotate_button.png")
    g.release()
    na = g.run.next_angle
    assert abs(na + C.ROTATE_SPEED * 12 * FRAME) < 0.02, math.degrees(na)
    drag_place(g, 300, 300, release=False)
    assert abs(g.hold["angle"] - na) < 1e-9
    g.release()
    print(f"rotation: two fingers turned the held item by exactly -30 deg; button with a 2nd finger and "
          f"single-finger button before pickup ({math.degrees(na):.0f} deg) work, free angles")


def check_camera_and_parallax():
    g = new_game()
    start(g, M.ENDLOS, boxes=False)
    g.run.director = M.Director("camera-check")  # a fixed real sequence
    rng = random.Random(3)
    houses_at = None
    zooms = []
    for n in range(26):
        d = g.run.current()
        x, y, a = bot_good(g.run.world, d, rng)
        g.run.release(d, x, y, a)
        wait(g, 2.0)
        if g.run.phase != "play":
            break
        zooms.append(g.run.cam.zoom)
        if n == 2:
            assert g.run.cam.zoom > 0.97, g.run.cam.zoom
            assert not R.Renderer.houses_visible(g.run.cam.rise)
        if n == 9:
            shot(g, "06_stack10.png")
        if houses_at is None and R.Renderer.houses_visible(g.run.cam.rise):
            houses_at = n + 1
            shot(g, f"07_houses_{n + 1}.png")
        top_y = g.run.cam.to_screen(0, g.run.world.top())[1]
        assert top_y > C.BAR_H + 60, f"stack top out of reach at item {n + 1}: y={top_y:.0f}"
    if g.run.phase == "play":
        shot(g, f"07b_stack{len(zooms)}.png")
    assert houses_at is not None and 12 <= houses_at <= 22, houses_at
    assert min(zooms) >= C.MIN_ZOOM and zooms[2] > 0.97
    steps = [abs(b - a) for a, b in zip(zooms, zooms[1:])]
    assert max(steps) < 0.08, steps  # no abrupt zoom
    print(f"camera: zoom {zooms[2]:.2f} after 3 items, {zooms[-1]:.2f} after {len(zooms)}; stack top always reachable; "
          f"houses appear at item {houses_at}")


def check_tagesladung():
    a = [M.Director(M.day_seed(DAY), M.TAGES).get(i)["id"] for i in range(40)]
    b = [M.Director(M.day_seed(DAY), M.TAGES).get(i)["id"] for i in range(40)]
    c = [M.Director(M.day_seed(DAY + datetime.timedelta(days=1)), M.TAGES).get(i)["id"] for i in range(40)]
    assert a == b and a != c
    g1, g2 = new_game(), new_game()
    start(g1, M.TAGES, boxes=False)
    start(g2, M.TAGES, boxes=False)
    s1 = [g1.run.director.get(i)["id"] for i in range(25)]
    s2 = [g2.run.director.get(i)["id"] for i in range(25)]
    assert s1 == s2 == a[:25]
    g1.run.director = M.Director(None, fixed=BOXES)
    first = [ITEMS_BY_ID[i] for i in a[:C.SAFE_ITEMS]]
    assert all(d["difficulty"] == 1 for d in first)
    wtf_first = next((i for i, x in enumerate(a) if {"wtf_a", "wtf_b"} & set(ITEMS_BY_ID[x]["tags"])), 99)
    assert wtf_first >= C.WTF_EARLIEST
    # today's results like KIEZ-KURIER: "Heute Platz"
    place_world(g1, 0)
    wait(g1, 1.0)
    g1.run.release(g1.run.current(), 260, 60, 0.0)
    while g1.state != "over":
        frames(g1)
    assert "Heute Platz 1/1" in g1.over_text and party_games.top_list(g1.score_key())[0]["day"] == DAY.isoformat()
    print(f"Tagesladung: same sequence for the same date (seed), different the next day; safe start, "
          f"first WTF item at #{wtf_first + 1}; result says '{g1.over_text}'")


def check_party():
    g = new_game()
    G._RESUME = None
    g.reset(g.last_tick)
    tap_ui(g, "party")
    shot(g, "11_party_setup.png")
    tap_ui(g, "n3")
    tap_ui(g, "go")
    g.run.director = M.Director(None, fixed=BOXES)
    run = g.run
    assert run.players == ["Spieler*in 1", "Spieler*in 2", "Spieler*in 3"] and run.turn == 0
    before = len(party_games.HIGHSCORES)
    place_world(g, -40)  # Spieler*in 1
    wait(g, 1.5)
    assert run.turn == 1
    place_world(g, 40)  # Spieler*in 2
    wait(g, 1.5)
    assert run.turn == 2
    snap_items = len(run.world.items)
    run.release(run.current(), 260, 60, 0.0)  # Spieler*in 3 throws it on the grass
    for _ in range(20):
        frames(g)
    assert run.phase == "out" and run.out_player == 2
    shot(g, "12_party_out.png")
    wait(g, C.PARTY_OUT_SECONDS + 0.3)
    run = g.run
    assert run.phase == "play" and run.alive == [True, True, False] and run.turn == 0
    assert len(run.world.items) == snap_items and run.world.fail is None
    g.draw(GAME_SURF)
    shot(g, "13_party_reset.png")
    place_world(g, 0)  # Spieler*in 1
    wait(g, 1.5)
    assert run.turn == 1
    run.release(run.current(), -330, 60, 0.0)  # Spieler*in 2 drops it
    wait(g, C.PARTY_OUT_SECONDS + 0.6)
    assert g.screen == "msg" and "Spieler*in 1 gewinnt" in g.msg[0], (g.screen, g.msg)
    shot(g, "14_party_winner.png")
    assert len(party_games.HIGHSCORES) == before  # no Bestenliste for parties
    tap_ui(g, "again")
    assert g.run.mode == M.PARTY and len(g.run.players) == 3
    print("party: turns in the bar, the placer of the falling item is out, stack reset to before their item, "
          "last one standing wins, no highscore")


def check_story():
    g = new_game()
    G._RESUME = None
    g.reset(g.last_tick)
    tap_ui(g, "story")
    assert g.screen == "intro"
    shot(g, "15_story_intro.png")
    for _ in M.LEVELS[0].intro:
        g.tap(240, 700)
        frames(g)
    assert g.screen == "play" and g.run.level is M.LEVELS[0] and not g.run.timer_on
    wait(g, 1.0)
    assert g.run.elapsed == 0.0  # the clock starts with the first touch
    losses = 0
    for seed in range(1, 9):
        rng = random.Random(seed)
        drag_place(g, g.run.cam.to_screen(0, 0)[0], 470)  # first Bassbox to the middle of the deck
        assert g.run.timer_on
        for n in range(1, len(M.LEVELS[0].items)):
            d = g.run.current()
            x, y, a = bot_good(g.run.world, d, rng)
            g.run.release(d, x, y, a)
            wait(g, 1.6)
            if g.run.phase not in ("play", "settle"):
                break
        if g.run.phase in ("play", "settle"):
            break
        while g.screen != "msg":  # a drop = level lost (no Bestenliste entry), NOCHMAL restarts it
            frames(g)
        losses += 1
        if losses == 1:
            shot(g, "15b_story_lost.png")
        assert party_games.top_list(M.score_key(g.NAME, M.STORY, "rave1")) == []
        tap_ui(g, "again")
        assert g.screen == "play" and g.run.level is M.LEVELS[0] and g.run.placed == 0
    assert g.run.phase == "settle"
    frames(g, 30)
    shot(g, "16_story_settle.png")
    while g.run.phase == "settle":
        frames(g)
    assert g.run.phase == "ride"
    frames(g, 50)
    shot(g, "17_story_ride.png")
    while g.state != "over":
        frames(g)
    assert isinstance(g.score, float) and g.LOWER_IS_BETTER and g.score_key().endswith("STORY rave1")
    assert g.format_score(g.score).count(":") == 1
    frames(g, 30)
    shot(g, "18_story_result.png")
    print(f"story: intro, clock from the first touch, 8 fixed items, {losses} lost tries (NOCHMAL), then 3 s hold, ride-off, "
          f"best time {g.format_score(g.score)}")


def check_thumbnails(g_over):
    g = g_over
    path = os.path.join(G.thumb_dir(), f"{g.entry_id}.png")
    assert os.path.exists(path)
    img = pygame.image.load(path)
    assert img.get_width() == C.THUMB_W and os.path.getsize(path) < 120_000, (img.get_size(), os.path.getsize(path))
    g2 = new_game()
    entry = party_games.top_list(g.score_key())[0]
    pic = g2.entry_image(entry)
    assert pic is not None and pic.get_width() == C.THUMB_W
    assert g2.entry_image({"id": "nope", "score": 1}) is None
    probe = pygame.Surface((200, 30))
    probe.fill((255, 255, 255))
    g2._draw_entry_mark(probe, entry, 190, 15)
    assert probe.get_at((182, 15))[:3] != (255, 255, 255)  # the little photo mark
    # the result list opens it on tap
    for rect, e in g.row_rects:
        if e.get("id") == g.entry_id:
            g.tap(*rect.center)
            break
    assert g.viewing is not None
    frames(g)
    shot(g, "10_result_picture.png")
    g.tap(240, 400)
    # Highscores screen from the menu, with the picture
    g3 = new_game()
    tap_ui(g3, "scores")
    shot(g3, "19_highscores.png")
    tap_ui(g3, "row0")
    assert g3.viewing is not None
    shot(g3, "20_highscores_picture.png")
    print(f"thumbnails: {img.get_width()}x{img.get_height()} PNG ({os.path.getsize(path) // 1024} KB) per entry, "
          "shown from the result list and the Highscores screen")


def check_resume():
    G._RESUME = None
    g = new_game(5000.0)
    start(g, M.ENDLOS)
    place_world(g, -30)
    wait(g, 1.0)
    place_world(g, 40)
    wait(g, 1.0)
    run = g.run
    del g  # PiDashboard drops the object on close (idle timeout, x, display blank)
    g = new_game(5000.0 + 120)
    assert g.screen == "resume"
    shot(g, "21_resume.png")
    tap_ui(g, "resume")
    assert g.run is run and g.screen == "play" and len(run.world.items) == 2
    frames(g, 10)
    g = new_game(g.last_tick + 60)
    tap_ui(g, "new")
    assert g.screen == "menu" and G._RESUME is None
    g = new_game(9000.0)
    start(g, M.ENDLOS)
    place_world(g, 0)
    frames(g, 5)
    g = new_game(9000.0 + C.RESUME_SECONDS + 60)
    assert g.screen == "menu"
    assert lastenrad.LastenradGame.IDLE_TIMEOUT_SECONDS == 600
    print("resume: a closed run waits (WEITER restores the same world, NEU STARTEN drops it), expires after "
          f"{C.RESUME_SECONDS // 60} min")


def check_corner():
    def no_buttons_in_box(g, where):
        g.draw(GAME_SURF)
        rects = list(g.ui_rects.values()) if g.state != "over" else list(g.buttons.values()) + [r for r, _ in g.row_rects]
        box = pygame.Rect(0, 0, C.CORNER[0], C.CORNER[1])
        bad = [r for r in rects if r.colliderect(box)]
        assert not bad, (where, bad)
        before = (g.screen, g.state, g.run is not None)
        g.tap(50, 70)
        frames(g)
        assert (g.screen, g.state, g.run is not None) == before, where

    g = new_game()
    no_buttons_in_box(g, "menu")
    tap_ui(g, "party")
    no_buttons_in_box(g, "party_setup")
    g = new_game()
    tap_ui(g, "story")
    g.draw(GAME_SURF)
    assert not any(r.colliderect(pygame.Rect(0, 0, *C.CORNER)) for k, r in g.ui_rects.items() if k != "next")
    g = new_game()
    tap_ui(g, "scores")
    no_buttons_in_box(g, "highscores")
    g = new_game()
    start(g, M.ENDLOS)
    frames(g)
    box = pygame.Rect(0, 0, *C.CORNER)
    assert not any(r.colliderect(box) for r in g.ui_rects.values()), g.ui_rects  # play bar
    place_world(g, 0)
    wait(g, 1)
    g.run.release(g.run.current(), 260, 60, 0.0)
    while g.state != "over":
        frames(g)
    frames(g, 40)
    no_buttons_in_box(g, "result")
    g = new_game(20000.0)
    start(g, M.ENDLOS)
    place_world(g, 0)
    frames(g, 3)
    g = new_game(20010.0)
    no_buttons_in_box(g, "resume")
    print("corner: nothing tappable at game x<100, y<144 on menu, party setup, intro, highscores, result, resume, play bar")


def check_debug_overlay():
    g = new_game()
    start(g, M.ENDLOS)
    for x in (-50, 50, 0):
        place_world(g, x)
        wait(g, 0.6)
    C.DEBUG = True
    frames(g, 5)
    shot(g, "22_debug.png")
    C.DEBUG = False
    print("debug overlay: shapes, COM, angle, torque, FPS render")


def check_frame_times():
    """60+ bodies: physics + drawing per frame (the Pi 4 is ~10x slower)."""
    g = new_game()
    start(g, M.ENDLOS)
    w = g.run.world
    pb = ITEMS_BY_ID["powerbank"]
    for layer in range(15):  # four exactly aligned columns: 60 items that stay put
        for col in range(4):
            x = -112.5 + col * 75
            w.place(pb, x, C.DECK_TOP + 22 + layer * 44.5, 0)
        settle(w, 0.6, 0.2)
    cart = ITEMS_BY_ID["einkaufswagen"]
    w.place(cart, 0, w.rest_y(cart, 0, math.pi) + 2, math.pi)
    settle(w, 2.0)
    assert w.fail is None, w.fail
    bodies = sum(len(it.bodies()) for it in w.items)
    assert bodies >= 60, bodies
    g.run.placed = len(w.items)
    wait(g, 3.0)
    shot(g, "23_perf_stack.png")

    def measure(label, k=90, wake=False):
        upd = drw = 0.0
        worst = 0.0
        for i in range(k):
            if wake and i % 30 == 0:
                for it in w.items:
                    it.body.activate()
            t0 = time.perf_counter()
            g.update(g.last_tick + FRAME)
            t1 = time.perf_counter()
            g.draw(GAME_SURF)
            t2 = time.perf_counter()
            upd += t1 - t0
            drw += t2 - t1
            worst = max(worst, t2 - t0)
        print(f"frame time ({label}, {bodies} bodies, {len(w.items)} items): update {upd / k * 1000:.2f} ms + "
              f"draw {drw / k * 1000:.2f} ms = {(upd + drw) / k * 1000:.2f} ms avg, worst {worst * 1000:.1f} ms "
              f"(Pi 4 ~10x: ~{(upd + drw) / k * 10000:.0f} ms)", flush=True)
        return (upd + drw) / k

    resting = measure("resting, sleeping")
    awake = measure("all awake", wake=True)
    drag_place(g, 240, 200, release=False)
    holding = measure("holding an item")
    g.release()
    assert w.fail is None and g.run.phase == "play"
    assert resting < 0.008 and awake < 0.012 and holding < 0.010, (resting, awake, holding)
    return resting, awake, holding


def check_menu_shots():
    g = new_game()
    shot(g, "01_menu.png")
    tap_ui(g, "scores")
    tap_ui(g, M.TAGES)
    shot(g, "19b_highscores_tages.png")


def main():
    global SCREEN, GAME_SURF
    parser = argparse.ArgumentParser()
    parser.add_argument("--bots", type=int, default=0, help="only run the balance bots with this many seeds each")
    args = parser.parse_args()
    if args.bots:
        bot_stats(args.bots)
        return
    random.seed(7)
    SCREEN = setup()
    GAME_SURF = SCREEN.subsurface((0, TITLE_H, 480, 800 - TITLE_H))
    t0 = time.time()
    check_items()
    check_menu_shots()
    check_drag_release()
    check_no_clipping()
    check_not_grabbable()
    check_rolling()
    check_tilt()
    g_over = check_crash_then_over()
    check_thumbnails(g_over)
    check_rotation()
    check_camera_and_parallax()
    check_tagesladung()
    check_party()
    check_story()
    check_resume()
    check_corner()
    check_debug_overlay()
    times = check_frame_times()
    print("bot sanity (2 seeds each):", flush=True)
    for name in ("careless", "novice", "good"):
        r = [bot_run(BOTS[name], s, 60)[0] for s in range(2)]
        print(f"  {name}: {r}", flush=True)
    print(f"\nALL LASTENRAD CHECKS PASSED in {time.time() - t0:.0f} s; frame times resting/awake/holding "
          f"{times[0] * 1000:.2f}/{times[1] * 1000:.2f}/{times[2] * 1000:.2f} ms; screenshots in {OUT}")


if __name__ == "__main__":
    main()
