#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless checks of LASTENRAVE SIMULATOR (lastenrave.py), instantiated
directly (not through PiDashboard.py, which other people are editing; its
icon is registered here like PiDashboard.py will): ready screen, corner taps
ignored, tap starts; the crane swings, a tap drops, a drag moves the trolley
(and doesn't drop), DREHEN rotates; pieces land in the box / on each other
and score; a piece hanging over its support tips off; an overloaded lower
piece makes the pile collapse; a piece on the street, a too-big lean
(Spanngurt) and a sliding Discokugel end the round (stored in a temp
Bestenliste); road hazards kick the pile; the difficulty escalates (new
pieces unlock, more swing, faster bike, more hazards). Then bots play whole
rounds through the real input API: a casual one must lose early, a careful
one must clearly stack more. Simulated time; screenshots go to
scratch/game_mockups/lastenrave/.

SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_lastenrave.py
"""

import glob
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

import kiezos as K  # noqa: E402
import lastenrave as LR  # noqa: E402
import party_games  # noqa: E402

OUT = os.path.join(REPO, "scratch", "game_mockups", "lastenrave")
os.makedirs(OUT, exist_ok=True)
for old in glob.glob(os.path.join(OUT, "*.png")):
    os.remove(old)

pygame.init()
K.configure(os.path.join(REPO, "fonts") + "/", os.path.join(REPO, "icons") + "/",
            json.load(open(os.path.join(REPO, "themes", "kiezos.json")))["KIEZOS"])
K.ICON_MAKERS["lastenrave"] = LR.menu_icon_surface  # what PiDashboard.py will do
SCORES = tempfile.mkdtemp(prefix="lastenrave_scores_")
party_games.configure(SCORES)
TITLE_H = 36
SCREEN = pygame.Surface((K.W, K.H))
GH = K.H - TITLE_H
GAME_SURF = SCREEN.subsurface((0, TITLE_H, K.W, GH))
FRAME = 1 / 20
FONTS = (os.path.join(REPO, "fonts", "JetBrainsMono-Medium.ttf"), os.path.join(REPO, "fonts", "JetBrainsMono-Bold.ttf"))


def new_game(seed=1):
    random.seed(seed)
    g = LR.LastenraveGame(K.W, GH, *FONTS)
    g.show_close = False
    g.reset(1000.0)
    return g


def shot(g, name):
    g.draw(GAME_SURF)
    K.game_title(SCREEN, "lastenrave.exe", "lastenrave")
    pygame.image.save(SCREEN, os.path.join(OUT, name))


def frames(g, n):
    for _ in range(n):
        g.update(g.last_tick + FRAME)


def tap(g, x, y):
    r = g.tap(x, y)
    g.release()
    return r


def started(seed=1):
    g = new_game(seed)
    tap(g, 240, 500)
    assert g.state == "play"
    return g


def calm(g):
    """No road hazards, no swing: for isolated checks."""
    g.obstacles = []
    g.next_obstacle_s = 1e12
    if g.hang:
        g.hang["phi"] = g.hang["dphi"] = 0.0


def wait_hang(g, max_frames=60):
    for _ in range(max_frames):
        if g.hang is not None and not g.hang["entering"]:
            return g.hang
        frames(g, 1)
    raise AssertionError("no piece on the crane")


def hold_still(g, lx):
    """Parks the trolley so the hanging piece sits above pile-frame x = lx, no swing."""
    h = wait_hang(g)
    h["tx"] = h["target"] = LR.PIVOT_X + lx
    h["phi"] = h["dphi"] = h["tv"] = 0.0
    return h


def drop_at(g, lx, max_frames=60):
    """Drops the hanging piece straight above lx and waits until it settled."""
    hold_still(g, lx)
    n = len(g.pile)
    tap(g, 300, 400)
    assert g.hang is None and g.flying
    for _ in range(max_frames):
        frames(g, 1)
        if not g.flying:
            break
    return len(g.pile) > n


def set_next(g, key):
    """The piece on the crane becomes `key`."""
    h = wait_hang(g)
    h["key"], h["orient"], h["a"] = key, 0, LR.art(key, 0)


# ------------------------------------------------------------ checks
def test_art():
    for key in LR.KINDS:
        for o in range(4):
            a = LR.art(key, o)
            assert a.w % LR.COL == 0 and a.h % LR.COL == 0, (key, o, a.w, a.h)
            assert any(b is not None for b in a.bottom) and 0 < a.com_x < a.w and 0 < a.com_y < a.h
    ball = LR.art("discokugel")
    crate = LR.art("bierkiste")
    touching = lambda a: sum(1 for b in a.bottom if b is not None and b <= LR.CONTACT_TOL)  # noqa: E731
    assert touching(ball) < touching(crate) / 2, "a ball touches the ground with far fewer columns than a crate"
    zaun = LR.art("bauzaun")
    assert zaun.bottom[len(zaun.bottom) // 2] > 8, "the Bauzaun stands on its feet, the middle doesn't touch"
    assert LR.art("pfeffi", 1).w == LR.art("pfeffi").h, "rotating swaps width and height"
    icon = LR.menu_icon_surface(32)
    assert icon.get_size() == (32, 32)
    print(f"ART: {len(LR.KINDS)} pieces x 4 orientations, contact profiles + centre of mass ok", flush=True)


def test_start_and_corner():
    g = new_game()
    frames(g, 10)
    assert g.state == "ready"
    shot(g, "01_ready.png")
    for x, y in ((5, 5), (50, 100), (99, 143)):
        assert tap(g, x, y) is None and g.state == "ready", "corner taps never start"
    tap(g, 240, 500)
    assert g.state == "play" and g.hang is not None and g.hang["key"] == "lautsprecher"
    h = wait_hang(g)
    assert abs(h["tx"] - h["target"]) < 1
    # corner taps do nothing while playing either (no drop, no rotation)
    for x, y in ((5, 60), (80, 140)):
        assert tap(g, x, y) is None
        assert g.hang is not None and not g.flying
    # HUD taps outside DREHEN don't drop
    tap(g, 200, 20)
    assert g.hang is not None
    xs = []
    for _ in range(60):
        frames(g, 1)
        xs.append(g.hang_pos()[0])
    assert max(xs) - min(xs) > 30, f"the piece swings ({max(xs) - min(xs):.0f} px)"
    print(f"START: corner ignored, tap starts, piece swings {max(xs) - min(xs):.0f} px", flush=True)
    return g


def test_drag_rotate_drop():
    g = started(2)
    calm(g)
    h = hold_still(g, 0)
    x0 = h["tx"]
    g.tap(250, 400)
    for i in range(1, 9):
        g.drag(250 - i * 10, 400)
        frames(g, 1)
    g.release()
    assert g.hang is not None and not g.flying, "lifting the finger after a drag doesn't drop"
    assert abs(h["target"] - (x0 - 80)) < 1
    frames(g, 20)
    assert abs(h["tx"] - (x0 - 80)) < 2, "the trolley drives to the finger"
    assert abs(h["dphi"]) > 0.05 or abs(h["phi"]) > 0.02, "moving the trolley makes the piece swing"
    a0 = h["a"]
    tap(g, g.rot_rect.centerx, g.rot_rect.centery)
    assert h["orient"] == 1 and h["a"].w == a0.h and g.hang is not None
    for _ in range(3):
        tap(g, g.rot_rect.centerx, g.rot_rect.centery)
    assert h["orient"] == 0
    # momentum: a piece dropped mid-swing flies sideways
    h["tx"] = h["target"] = LR.PIVOT_X
    h["phi"], h["dphi"], h["tv"] = 0.0, 1.0, 0.0
    tap(g, 300, 400)
    f = g.flying[0]
    assert f.vx > 100, f"dropped mid-swing it keeps its momentum ({f.vx:.0f} px/s)"
    print(f"INPUT: drag moves the crane (no drop), DREHEN turns, tap drops with momentum vx={f.vx:.0f}", flush=True)


def test_landing_and_score():
    g = started(3)
    calm(g)
    shot(g, "02_first_piece.png")
    assert drop_at(g, 0)
    p = g.pile[0]
    assert g.score == 1 and p.in_box and p.bottom == LR.FLOOR_H, (g.score, p.bottom)
    assert g.hang is None
    frames(g, int(LR.SPAWN_DELAY / FRAME) + 25)
    calm(g)
    set_next(g, "bierkiste")
    assert drop_at(g, 0)
    q = g.pile[1]
    assert abs(q.bottom - (p.bottom + p.a.h)) < 1 + LR.CONTACT_TOL and p in q.supports, "lands on the speaker"
    assert g.score == 2
    print(f"LANDING: in the box (y={p.bottom:.0f}), on top (y={q.bottom:.0f}), score {g.score}", flush=True)


def stack(g, plan):
    """Places pieces directly (key, orient, left) - bypasses the crane."""
    out = []
    for key, orient, left in plan:
        p = g.put(key, orient, left)
        assert p is not None, (key, left)
        out.append(p)
    g.top_h = max(g.top_h, max(p.bottom + p.a.h for p in g.pile))
    return out


def test_tip_off():
    g = started(4)
    calm(g)
    stack(g, [("subwoofer", 0, -32), ("subwoofer", 0, -32)])
    frames(g, int(LR.SPAWN_DELAY / FRAME) + 25)
    calm(g)
    set_next(g, "mischpult")
    base = g.pile[-1]
    # far over the right edge of the top subwoofer: centre of mass outside the contact
    lx = base.left + base.a.w + LR.art("mischpult").w / 2 - 14
    hold_still(g, lx)
    tap(g, 300, 400)
    tipped = False
    for _ in range(80):
        frames(g, 1)
        tipped = tipped or any(f.spin for f in g.flying)
        if g.state == "over":
            break
    assert tipped, "a piece hanging over its support tips off"
    assert g.state == "over" and "MISCHPULT" in g.over_text, g.over_text
    entries = party_games.top_list(LR.LastenraveGame.NAME)
    assert entries and g.place is not None, "round stored in the Bestenliste"
    frames(g, 6)
    shot(g, "07_tipping_over.png")
    print(f"TIP-OFF: over the edge -> tips -> '{g.over_text}'", flush=True)


def test_collapse():
    g = started(5)
    calm(g)
    pf = stack(g, [("pfeffi", 0, -12)])[0]  # upright XXL-Pfeffi: tiny neck on top
    staff = stack(g, [("dragonstaff", 0, -60)])[0]
    assert pf in staff.supports and g.hangs_over(staff) == 0 and g.find_overloaded() is None, "staff balances on the neck"
    # a Subwoofer on the far end of the staff: fine for the staff itself, but the neck can't hold it
    frames(g, int(LR.SPAWN_DELAY / FRAME) + 25)
    calm(g)
    set_next(g, "lautsprecher")
    hold_still(g, 25)
    g.theta = g.omega = 0.0
    tap(g, 300, 400)
    for _ in range(60):
        frames(g, 1)
        g.theta = g.omega = 0.0
        if g.state == "over":
            break
    assert g.state == "over" and "Eingestürzt" in g.over_text, g.over_text
    assert g.debris, "the collapsed pieces fly off"
    frames(g, 4)
    shot(g, "08_collapse.png")
    print(f"COLLAPSE: overloaded lower piece -> '{g.over_text}'", flush=True)


def test_street_and_topple():
    g = started(6)
    calm(g)
    hold_still(g, -200)  # far left of the box
    tap(g, 300, 400)
    for _ in range(80):
        frames(g, 1)
        if g.state == "over":
            break
    assert g.state == "over" and "Straße" in g.over_text and g.score == 0
    frames(g, 30)
    shot(g, "09_over_dialog.png")
    # NOCHMAL only after the tap delay / dialog
    again = g.buttons["again"]
    assert g.tap(*again.center) is None and g.state == "ready"

    g = started(7)
    calm(g)
    stack(g, [("subwoofer", 0, -32), ("bierkiste", 0, -28), ("matekiste", 0, -24)])
    g.theta = LR.TOPPLE + 0.05
    g.omega = 1.0
    frames(g, 1)
    assert g.state == "over" and "Spanngurt" in g.over_text and len(g.debris) == 3 and not g.pile
    print("STREET/TOPPLE: piece on the street and a ripped Spanngurt end the round, NOCHMAL restarts", flush=True)


def test_slip():
    g = started(8)
    calm(g)
    stack(g, [("subwoofer", 0, -32), ("subwoofer", 0, -32)])
    ball = stack(g, [("discokugel", 0, -26)])[0]
    assert ball in g.exposed()
    x0 = ball.left
    g.hang = None
    g.spawn_at = 1e9
    for _ in range(4):  # lean held at 8 degrees: the ball rolls downhill
        g.theta, g.omega = math.radians(8), 0.0
        g._step_slip(FRAME)
    assert ball.left > x0 + 3, f"the Discokugel rolls ({ball.left - x0:.1f} px)"
    box = g.pile[1]
    assert box.left == -32, "a subwoofer (high friction, loaded) doesn't slide at 8 degrees"
    for _ in range(200):
        g.theta, g.omega = math.radians(8), 0.0
        g._step_slip(FRAME)
        g._step_tipping(FRAME)
        g._step_flying(FRAME)
        if g.state == "over":
            break
    assert g.state == "over" and "DISCOKUGEL" in g.over_text, g.over_text
    print("SLIP: the Discokugel rolls off a leaning pile and ends the round", flush=True)


def test_hazards_and_wobble():
    g = started(9)
    calm(g)
    stack(g, [("subwoofer", 0, -32), ("bierkiste", 0, -28)])
    g.obstacles = [{"x": g.road_s + LR.FRONT_X + 30, "kind": "loch", "len": 0.0, "hit": set(), "told": False}]
    g.theta = g.omega = 0.0
    frames(g, 1)
    hit = False
    for _ in range(40):
        frames(g, 1)
        if "f" in g.obstacles[0]["hit"] if g.obstacles else False:
            hit = True
            break
    assert hit and abs(g.omega) > 0.02, f"a Schlagloch kicks the pile (omega {g.omega:.3f})"
    # an off-centre piece leans the pile towards its side
    g = started(10)
    calm(g)
    stack(g, [("subwoofer", 0, -32)])
    stack(g, [("bierkiste", 0, -10)])  # sticks out to the right
    g.hang = None
    g.spawn_at = 1e9
    for _ in range(60):
        g._step_pile(FRAME)
    assert g.theta > math.radians(1), f"leans right ({math.degrees(g.theta):.1f} deg)"
    print(f"WOBBLE: Schlagloch kicks, off-centre load leans {math.degrees(g.theta):.1f} deg", flush=True)


def test_difficulty():
    g = started(11)
    random.seed(11)
    early = {g.pick_next() for _ in range(300)}
    assert all(LR.KINDS[k][5] == 0 for k in early), early
    g.score = 16
    late = {g.pick_next() for _ in range(400)}
    assert {"discokugel", "sofa", "einkaufswagen", "flamingo", "pfeffi"} <= late, late
    assert g.target_speed() > started(1).target_speed()
    # swing amplitude and trolley offset grow, hazards get more frequent and nastier
    amps = []
    for n in (0, 12):
        g = started(12)
        g.score = n
        g.hang = None
        g.spawn()
        amps.append(abs(g.hang["phi"]) * g.hang["L"])
    assert amps[1] > amps[0] * 2, amps
    kinds = {}
    for n in (0, 12):
        g = started(13)
        g.score = n
        g.road_s = 0.0
        g.next_obstacle_s = 700.0
        g.obstacles = []
        seen = {}
        for _ in range(400):
            g.road_s += 100
            g._step_road(0.0, hazards=True)
            for o in g.obstacles:
                seen[(o["x"], o["kind"])] = o
        kinds[n] = (len(seen), {o["kind"] for o in seen.values()})
    assert kinds[0][1] == {"kopf"} and {"loch", "tram", "kante"} <= kinds[12][1], kinds
    assert kinds[12][0] > kinds[0][0] * 1.4, kinds
    print(f"DIFFICULTY: start pool {sorted(early)}; at 16 also {sorted(late - early)}; swing {amps[0]:.0f}->{amps[1]:.0f} px; "
          f"hazards per 40 km of road {kinds[0][0]} -> {kinds[12][0]}", flush=True)


# ------------------------------------------------------------ bots
def crane_to(g, sx):
    """Drags the crane trolley to screen x = sx like a finger would."""
    d = sx - g.hang["target"]
    g.tap(240, 420)
    g.drag(240 + d + (30 if d < 0 else -30), 420)
    g.drag(240 + d, 420)
    g.release()


def candidate(g, key):
    """Best (orient, lx, bottom) for a careful player: stable even if the drop
    is a bit off, keeps the total centre of mass near the middle, low.
    Trial-places on the real pile."""
    best = None
    m, smx, _, _ = g.mass_moments()
    for orient in (0, 1):
        a = LR.art(key, orient)
        for lx in range(-64, 65, 4):
            ok, cost, bottom = True, None, 0.0
            for dx in (-6, 0, 6):
                p = g.put(key, orient, lx + dx - a.w / 2)
                if p is None:
                    ok = False
                    break
                ok = ok and g.hangs_over(p) == 0 and g.find_overloaded() is None
                if dx == 0:
                    bottom = p.bottom
                    com = (smx * 100 + p.mass * p.cx) / (m + p.mass)
                    cost = abs(com) * 2 + (p.bottom + p.a.h) * 0.25 + abs(lx) * 0.3
                g.remove(p)
            if ok and (best is None or cost < best[0]):
                best = (cost, orient, lx, bottom)
    return best


def bot_step(g, plan, careful, rnd):
    """One frame of a bot playing through the real input API. Returns the plan."""
    h = g.hang
    if h is None or h["entering"]:
        return plan
    if plan is None or plan["born"] != h["born"]:
        if careful:
            c = candidate(g, h["key"])
            orient, lx, bottom = c[1:] if c else (0, 0, 0.0)
            while h["orient"] != orient:
                tap(g, g.rot_rect.centerx, g.rot_rect.centery)
            crane_to(g, LR.PIVOT_X + lx)
            return {"born": h["born"], "lx": lx, "bottom": bottom}
        plan = {"born": h["born"], "wait": rnd.uniform(0.3, 2.0)}
        if rnd.random() < 0.5:  # roughly towards the box
            crane_to(g, LR.PIVOT_X + rnd.uniform(-40, 40))
        return plan
    if careful:
        mx, _, hits = g.predict()
        aim = g.to_screen(plan["lx"], plan["bottom"])[0]  # the spot moves with the pile's lean
        ahead = [o for o in g.obstacles if o["kind"] != "kopf" and 0 < o["x"] - g.road_s - LR.FRONT_X < 90]
        steady = abs(g.theta) < math.radians(3) and abs(g.omega) < 0.06
        if hits and abs(mx - aim) < 4 and not ahead and (steady or g.last_tick - h["born"] > 6):
            tap(g, 240, 420)
    elif g.last_tick - h["born"] > plan["wait"]:
        tap(g, 240, 420)
    return plan


def play_round(seed, careful, max_s=300, until_score=None):
    g = started(seed)
    rnd = random.Random(seed * 7)
    plan = None
    t0 = g.last_tick
    while g.state == "play" and g.last_tick - t0 < max_s and (until_score is None or g.score < until_score):
        plan = bot_step(g, plan, careful, rnd)
        frames(g, 1)
    return g


def test_bots():
    t0 = time.time()
    casual = [play_round(s, careful=False) for s in range(1, 11)]
    careful = [play_round(s, careful=True) for s in range(1, 11)]
    cs = [g.score for g in casual]
    gs = [g.score for g in careful]
    secs = [round(g.t) for g in careful]
    print(f"BOTS ({time.time() - t0:.0f} s): casual {cs} (median {statistics.median(cs)}), "
          f"careful {gs} (median {statistics.median(gs)}, round lengths {secs} s)", flush=True)
    for g in casual + careful:
        assert g.state == "over", "every round ends"
    assert statistics.median(cs) <= 7, "a casual player loses early"
    assert statistics.median(gs) >= statistics.median(cs) + 4 and max(gs) >= 12, "care and timing pay off clearly"
    return max(careful, key=lambda g: g.score)


def screenshots_midgame():
    """A mid and a late round of the careful bot, frozen for screenshots."""
    for name, target in (("03_midgame.png", 7), ("04_tall_pile.png", 14)):
        g = next(g for g in (play_round(s, True, until_score=target) for s in range(21, 60))
                 if g.state == "play" and g.score >= target)
        for _ in range(200):  # wait for a nice moment: piece on the crane, swinging
            frames(g, 1)
            if g.state != "play" or (g.hang is not None and not g.hang["entering"] and g.t - g.hang["born"] > 0.6):
                break
        shot(g, name)
        print(f"SHOT {name}: score {g.score}, height {g.top_h:.0f} px, lean {math.degrees(g.theta):.1f} deg", flush=True)


def test_new_piece_banner_and_perf():
    g = started(30)
    calm(g)
    g.score = 9
    g.seen = set(LR.KINDS) - {"discokugel"}
    g.next_key = "discokugel"
    g.hang = None
    g.spawn()
    frames(g, 8)
    assert any("NEU" in t[0] for t in g.texts)
    stack(g, [("subwoofer", 0, -32), ("bierkiste", 0, -28), ("lautsprecher", 0, -20)])
    g.obstacles = [{"x": g.road_s + 300, "kind": "kopf", "len": 300.0, "hit": set(), "told": True},
                   {"x": g.road_s + 640, "kind": "loch", "len": 0.0, "hit": set(), "told": False}]
    frames(g, 4)
    shot(g, "05_new_piece.png")
    # a busy frame stays cheap (Pi 4 at 20 FPS = 50 ms budget; a laptop is ~5-10x faster)
    g.score = 20
    stack(g, [("sofa", 0, -48), ("bauzaun", 0, -56), ("einkaufswagen", 0, -34), ("flamingo", 0, -24)])
    for _ in range(40):  # warm the rotation caches
        g.update(g.last_tick + FRAME)
        g.draw(GAME_SURF)
    t0 = time.perf_counter()
    n = 100
    for i in range(n):
        g.theta = math.radians(6 * math.sin(i / 8))
        g.update(g.last_tick + FRAME)
        g.draw(GAME_SURF)
    ms = (time.perf_counter() - t0) / n * 1000
    print(f"PERF: {ms:.2f} ms per update+draw with {len(g.pile)} pieces", flush=True)
    assert ms < 8, ms
    shot(g, "06_busy.png")


def main():
    t0 = time.time()
    test_art()
    test_start_and_corner()
    test_drag_rotate_drop()
    test_landing_and_score()
    test_tip_off()
    test_collapse()
    test_street_and_topple()
    test_slip()
    test_hazards_and_wobble()
    test_difficulty()
    test_new_piece_banner_and_perf()
    best = test_bots()
    screenshots_midgame()
    print(f"\nALL LASTENRAVE CHECKS PASSED in {time.time() - t0:.0f} s (best careful round: {best.score} Teile). "
          f"Screenshots: {OUT}", flush=True)


if __name__ == "__main__":
    main()
