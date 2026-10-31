#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless checks of PATRIAPUTT (patriaputt.py), instantiated directly
(not registered in PiDashboard's Spiele menu yet): ready -> tap starts and
the ball launches by itself; the paddle follows drag and plain taps; the
wall advances continuously and new rows slide in; a brick at the danger line
costs a heart (3x -> over -> Bestenliste, tap delay respected); breaking
bricks drops Solidarität gems, catching them levels up, the game pauses for
3 cards and a tapped card applies; every ball type / upgrade does its thing;
special bricks (armour, Stammtisch minions, glass chain); the PATRIARCHAT
boss arrives on schedule, takes damage and gives a heart back when beaten;
a busy frame stays cheap. Then bots play whole rounds through the real input
API: a casual one must lose within ~1-3 min, a good one survive longer.
Simulated time; highscores in a temp dir. Screenshots: scratch/game_mockups/patriarchat/real/.

SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_patriaputt.py
"""

import glob
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
import party_games  # noqa: E402
import patriaputt as PK  # noqa: E402
import PiDashboard as P  # noqa: E402

OUT = os.path.join(REPO, "scratch", "game_mockups", "patriarchat", "real")
os.makedirs(OUT, exist_ok=True)
for old in glob.glob(os.path.join(OUT, "*.png")):  # screenshots of the old level-based version
    os.remove(old)
party_games.configure(tempfile.mkdtemp(prefix="patriaputt_scores_"))
FRAME = 1 / 20
GH = P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT
GAME_SURF = P.tft_surf.subsurface((0, P.GAME_TITLE_HEIGHT, P.DISPLAY_WIDTH, GH))


def new_game(seed=1):
    random.seed(seed)
    game = PK.PatriaputtGame(P.DISPLAY_WIDTH, GH, P.FONT_PATH + P.FONT_MEDIUM, P.FONT_PATH + P.FONT_BOLD)
    game.show_close = False
    game.reset(1000.0)
    return game


def shot(game, name):
    game.draw(GAME_SURF)
    K.game_title(P.tft_surf, "patriaputt.exe", "games")
    P.tft_surf.blit(PK.menu_icon_surface(22), (8, 7))
    pygame.image.save(P.tft_surf, os.path.join(OUT, name))


def frames(game, n):
    for _ in range(n):
        game.update(game.last_tick + FRAME)


def started(seed=1, x=240):
    game = new_game(seed)
    game.tap(x, 500)
    game.release()
    assert game.state == "play"
    return game


def clear_wall(game):
    for k in list(game.bricks):
        game._remove(k)
    game.chain = []


def put(game, kind, label, r, slot, span, hp, rows=1):
    return game._add(PK.Brick(kind, label, r, slot, span, hp, rows))


def row_at(game, y):
    """Grid row whose top is closest to screen y."""
    return round((y - game.wall_y) / PK.ROW_STEP)


def fly(game, x, y, dx, dy, kind="disco"):
    """One ball of `kind`, flying."""
    b = PK.Ball(kind, x, y)
    b.set_dir(dx, dy)
    game._reload(b)
    game.balls = [b]
    return b


def hold_wall(game):
    """Stop the advance and new rows (for isolated checks)."""
    game.streik_until = 1e9
    game.next_boss_at = 1e9


def test_basics():
    game = new_game()
    assert game.state == "ready"
    frames(game, 2)
    shot(game, "01_start.png")
    game.tap(300, 500)
    game.release()
    assert game.state == "play" and abs(game.paddle_x - 300) < 1 and game.balls[0].stuck
    frames(game, int(PK.LAUNCH_DELAY / FRAME) + 2)
    assert not game.balls[0].stuck, "the ball launches by itself"
    print("START: tap starts, ball launches by itself", flush=True)

    game.drag(100, 650)
    assert abs(game.paddle_x - 100) < 1
    game.release()
    game.tap(400, 300)
    frames(game, 3)
    assert abs(game.paddle_x - 400) < 1, game.paddle_x
    game.drag(-50, 650)
    assert game.paddle_x == game.paddle_w / 2
    print("PADDLE: follows drag and taps, clamped", flush=True)

    # continuous advance: the wall moves down and new rows appear on top
    y0, top0, n0 = game.wall_y, game.top_row, game.rows_spawned
    frames(game, 200)  # 10 s
    assert game.wall_y > y0 + 40 and game.top_row < top0 and game.rows_spawned > n0, (game.wall_y, y0)
    v0 = game.wall_speed()
    game.play_t += 60
    assert game.wall_speed() > v0, "the wall speeds up over time"
    game.play_t -= 60
    print(f"WALL: advanced {game.wall_y - y0:.0f} px in 10 s, {game.rows_spawned - n0} new rows, speeds up", flush=True)

    # dropped ball: gone for a moment, then back on the paddle, launches again
    b = game.balls[0]
    b.stuck = False
    b.y, b.dy = game.height + 30, 1.0
    y = game.wall_y
    frames(game, 1)
    assert b.stuck and b in game.balls and game.wall_y >= y + PK.DROP_PUSH, "dropped: the wall jumps forward"
    frames(game, int((PK.RESPAWN_SECONDS + PK.LAUNCH_DELAY) / FRAME) + 2)
    assert not b.stuck
    print("BALL LOST: wall jumps forward, ball comes back and launches by itself", flush=True)


def test_bricks_and_special():
    game = started()
    hold_wall(game)
    clear_wall(game)
    r = row_at(game, 300)
    k = put(game, "normal", "PAY GAP", r, 2, 2, 2)
    rect = game.brick_rect(k)
    before = game.score
    b = fly(game, rect.centerx, rect.bottom + 40, 0, -1)
    frames(game, 4)
    assert k.hp == 1 and b.dy > 0 and game.score > before, "hit: -1 HP, bounce, points"
    fly(game, rect.centerx, rect.bottom + 40, 0, -1)
    frames(game, 4)
    assert not k.alive and game.gems, "broken -> Solidarität gem"
    # armour: every hit does 1, even with Wut im Bauch
    game.wut = 2
    a = put(game, "armor", "HERRENCLUB", r, 0, 2, 5)
    rect = game.brick_rect(a)
    fly(game, rect.centerx, rect.bottom + 40, 0, -1)
    frames(game, 4)
    assert a.hp == 4, a.hp
    game.wut = 0
    # Stammtisch breaks into two HAHA minions
    st = put(game, "stammtisch", "STAMMTISCH", r + 2, 4, 2, 1)
    rect = game.brick_rect(st)
    fly(game, rect.centerx, rect.bottom + 40, 0, -1)
    frames(game, 4)
    minions = [game.grid.get((r + 2, 4)), game.grid.get((r + 2, 5))]
    assert not st.alive and all(m is not None and m.kind == "minion" for m in minions), minions
    # glass: one pane -> the whole row shatters in a chain
    clear_wall(game)
    gr = row_at(game, 250)
    panes = [put(game, "glass", "GLAS", gr, s, 1, 1) for s in range(6)]
    rect = game.brick_rect(panes[0])
    fly(game, rect.centerx, rect.bottom + 30, 0, -1)
    frames(game, 3)
    assert not panes[0].alive and game.freeze >= 0
    frames(game, 12)
    assert not any(p.alive for p in panes), "glass row shatters in a chain"
    print("BRICKS: HP/points/gem, armour 1 per hit, Stammtisch -> 2 HAHA, glass chain", flush=True)


def test_danger_and_over():
    game = started()
    game.next_boss_at = 1e9
    frames(game, 20)
    hearts = game.hearts
    lowest = max(game.brick_rect(b).bottom for b in game.bricks)
    game.wall_y += game.danger_y - lowest - 30  # bring the wall right above the line
    frames(game, 2)
    shot(game, "05_near_danger.png")
    assert game.hearts == hearts
    game.wall_y += 40
    frames(game, 1)
    assert game.hearts == hearts - 1 and game.banner[0] == "DURCHBRUCH!"
    lowest = max((game.brick_rect(b).bottom for b in game.bricks), default=0)
    assert lowest < game.danger_y - 2 * PK.ROW_STEP, "bottom rows wiped"
    print("DANGER: line costs a heart, bottom rows wiped", flush=True)
    while game.state == "play":
        frames(game, 8)
        lowest = max((game.brick_rect(b).bottom for b in game.bricks), default=game.danger_y - 100)
        game.wall_y += game.danger_y - lowest + 5
        frames(game, 1)
    assert game.hearts == 0 and game.state == "over"
    entry = party_games.best(PK.PatriaputtGame.NAME)
    assert entry is not None and entry["score"] == game.score
    frames(game, 20)
    game.draw(GAME_SURF)
    again = game.buttons["again"]
    game.over_at = game.last_tick
    assert game.tap(*again.center) is None and game.state == "over", "tap delay"
    frames(game, int(party_games.GAME_OVER_TAP_DELAY_SECONDS / FRAME) + 2)
    shot(game, "06_gameover.png")
    game.tap(*again.center)
    assert game.state == "ready"
    print(f"OVER: 3 breaches -> over, stored ({PK.fmt(entry['score'])}), tap delay ok, NOCHMAL -> ready", flush=True)


def test_xp_and_cards():
    game = started()
    hold_wall(game)
    frames(game, 15)
    # a gem falls onto the paddle -> XP
    game.gems = [PK.Gem(game.paddle_x, game.paddle_y - 200, 3)]
    for _ in range(40):
        frames(game, 1)
    assert not game.gems and game.xp == 3, game.xp
    # enough XP -> pause + 3 cards; a finger still down can't pick right away
    game._gain_xp(game.xp_next)
    frames(game, 1)
    assert game.cards is not None and len(game.cards) == 3 and game.player_lv == 2
    y, play_t = game.wall_y, game.play_t
    game.streik_until = -1
    frames(game, 10)
    assert game.wall_y == y and game.play_t == play_t, "paused while choosing"
    shot(game, "03_levelup_cards.png")
    kind, rect = game.cards[1]
    game.cards_at = game.t
    game.tap(*rect.center)
    assert game.cards is not None, "card tap delay"
    frames(game, int(PK.CARD_TAP_DELAY / FRAME) + 1)
    game.tap(*rect.center)
    assert game.cards is None and game.lv[kind] == 1, kind
    print(f"XP: gem caught, level-up pauses for 3 cards, picked {kind}", flush=True)


def test_ball_types():
    def setup(seed=3):
        game = started(seed)
        hold_wall(game)
        clear_wall(game)
        return game

    # Glitzerball damages neighbours
    game = setup()
    game.lv["glitzer"] = 1
    r = row_at(game, 300)
    mid = put(game, "normal", "SEXISMUS", r, 2, 2, 5)
    left = put(game, "normal", "RASSISMUS", r, 0, 2, 5)
    rect = game.brick_rect(mid)
    fly(game, rect.left + 12, rect.bottom + 30, 0, -1, "glitzer")
    frames(game, 4)
    assert mid.hp == 4 and left.hp == 4, (mid.hp, left.hp)
    # Streikball freezes the wall
    game = setup()
    game.streik_until = -1
    game.lv["streik"] = 1
    k = put(game, "normal", "SEXISMUS", row_at(game, 300), 2, 2, 5)
    rect = game.brick_rect(k)
    fly(game, rect.centerx, rect.bottom + 30, 0, -1, "streik")
    frames(game, 4)
    assert game.t < game.streik_until and game.wall_speed() == 0
    y = game.wall_y
    frames(game, 5)
    assert game.wall_y == y
    # Soliball splits on the paddle
    game = setup()
    game.lv["soli"] = 2
    b = fly(game, game.paddle_x, game.paddle_y - 30, 0, 1, "soli")
    frames(game, 3)
    minis = [m for m in game.balls if m.mini]
    assert b.dy < 0 and len(minis) == 2
    game.balls = minis  # without the Soliball itself, nobody makes new ones
    frames(game, int(PK.MINI_SECONDS / FRAME) + 5)
    assert not any(m.mini for m in game.balls), "minis expire"
    # Demo-Zug pierces a whole column
    game = setup()
    game.lv["demo"] = 1
    r = row_at(game, 380)
    col = [put(game, "normal", "SEXISMUS", r - i, 2, 2, 1) for i in range(3)]
    rect = game.brick_rect(col[0])
    b = fly(game, rect.centerx, rect.bottom + 20, 0, -1, "demo")
    frames(game, 8)
    assert not any(k.alive for k in col), "pierced the whole column"
    # Konfetti-Kanone shoots from the paddle
    game = setup()
    game.lv["konfetti"] = 1
    k = put(game, "normal", "SEXISMUS", row_at(game, 300), 2, 2, 3)
    game.paddle_x = game.paddle_target = game.brick_rect(k).centerx
    game.balls = []
    frames(game, 30)
    assert k.hp < 3, "konfetti hit"
    # Plenumsball jumps to the next brick
    game = setup()
    game.lv["plenum"] = 1
    r = row_at(game, 300)
    a = put(game, "normal", "SEXISMUS", r, 2, 2, 5)
    far = put(game, "normal", "RASSISMUS", r + 3, 4, 2, 5)  # below-right: reachable without passing through a
    rect = game.brick_rect(a)
    b = fly(game, rect.centerx + 20, rect.bottom + 50, 0, -1, "plenum")
    frames(game, 3)
    assert a.hp == 4 and b.home == 1 and b.dx > 0 and b.dy > 0, (b.dx, b.dy, b.home)
    for _ in range(30):
        frames(game, 1)
        if far.hp < 5:
            break
    assert far.hp == 4, "homed in on the other brick"
    # Brandbrief: damage over time
    game = setup()
    game.lv["brand"] = 1
    k = put(game, "normal", "SEXISMUS", row_at(game, 300), 2, 2, 6)
    rect = game.brick_rect(k)
    fly(game, rect.centerx, rect.bottom + 30, 0, -1, "brand")
    frames(game, 4)
    game.balls = []
    hp = k.hp
    frames(game, 70)
    assert hp - k.hp == 3, (hp, k.hp)
    # Quotenball: double damage on armour/boss
    game = setup()
    game.lv["quote"] = 1
    a = put(game, "armor", "HERRENCLUB", row_at(game, 300), 2, 2, 9)
    rect = game.brick_rect(a)
    fly(game, rect.centerx, rect.bottom + 30, 0, -1, "quote")
    frames(game, 4)
    assert a.hp == 7, a.hp
    # Wut im Bauch, extra disco, heart, evolutions
    game = setup()
    n = len(game.balls)
    for kind in ("wut", "disco"):
        game._pick(kind)
    assert game.wut == 1 and len(game.balls) == n + 1
    game.hearts = 2
    game._pick("herz")
    assert game.hearts == 3
    game.lv.update({"glitzer": 3, "brand": 1, "streik": 3, "demo": 1})
    offers = set()
    for _ in range(30):
        offers |= set(game.offer())
    assert {"feuerwerk", "generalstreik"} <= offers
    game.lv["feuerwerk"] = 1
    r = row_at(game, 300)
    mid = put(game, "normal", "SEXISMUS", r, 2, 2, 9)
    left = put(game, "normal", "RASSISMUS", r, 0, 2, 9)
    rect = game.brick_rect(mid)
    fly(game, rect.left + 12, rect.bottom + 30, 0, -1, "glitzer")
    frames(game, 4)
    assert left.fire_until > game.t, "Feuerwerk: glitter ignites"
    print("BALLS: glitzer splash, streik freeze, soli split, demo pierce, konfetti, plenum homing, brand DoT, quote x2, "
          "wut/disco/herz, evolutions", flush=True)


def test_boss():
    game = started(5)
    game.next_boss_at = game.play_t
    frames(game, 200)
    assert game.boss is not None and game.boss.rows == 2 and game.boss.span == 6
    boss = game.boss
    rect = game.brick_rect(boss)
    for k in list(game.bricks):  # clear the way below it
        if k is not boss and game.brick_rect(k).top > rect.top:
            game._remove(k)
    hp = boss.hp
    b = fly(game, 240, rect.bottom + 60, 0.1, -1, "quote")
    game.lv["quote"] = 1
    frames(game, 6)
    assert boss.hp == hp - 2 and game.boss_damage_total == 2, (hp, boss.hp)
    for i, kind in enumerate(("glitzer", "brand", "demo")):
        game.lv[kind] = 1
        nb = PK.Ball(kind, 80 + i * 150, rect.bottom + 120)
        nb.set_dir(0.3, -1)
        game.balls.append(nb)
    game._ignite(boss)
    game.lv["konfetti"] = 2
    frames(game, 6)
    shot(game, "04_boss.png")
    game.hearts = 2
    game._damage(boss, boss.hp)
    assert game.boss is None and game.boss_kills == 1 and game.hearts == 3 and game.banner[0] == "PATRIAPUTT!"
    print("BOSS: arrives as 2x6 block, quote x2 on it, kill -> +1 heart", flush=True)
    del b


def test_perf():
    game = started(9)
    game.next_boss_at = 1e9
    frames(game, 600)
    game.hearts = 99
    for kind in ("glitzer", "soli", "brand", "demo", "plenum", "quote", "streik"):
        game._pick(kind)
    game.lv.update({"soli": 3, "konfetti": 3, "glitzer": 2})
    clear_wall(game)  # a full, tough wall (as after ~2 min) with a boss on top
    game.play_t = 120.0
    game.wall_y, game.top_row = float(PK.HUD_H + 6), 0
    for r in range(2, 12):
        game._spawn_row(r)
    game._spawn_boss(0)
    for k in game.bricks[::4]:
        game._ignite(k)
    frames(game, 20)
    t0 = time.perf_counter()
    n = 60
    for i in range(n):
        for b in game.balls:  # nobody drops out
            if b.y > game.paddle_y - 30:
                b.set_dir(b.dx, -abs(b.dy))
        game.update(game.last_tick + FRAME)
        game.draw(GAME_SURF)
        if game.cards is not None:
            game._pick(game.cards[0][0])
    ms = (time.perf_counter() - t0) / n * 1000
    print(f"PERF: {ms:.1f} ms per busy frame ({len(game.balls)} balls, {len(game.bricks)} bricks, {len(game.parts)} particles, "
          f"{len(game.gems)} gems) on this machine", flush=True)
    assert ms < 25, ms
    return ms


# ------------------------------------------------------------ bots

# Casual bot: sees the screen LAG_FRAMES late (reaction + Pi touch lag), moves
# the finger at most FINGER_SPEED px/s, misjudges each descent by AIM_SD px
# (+ AIM_SD_PER_PX per px of sideways travel), only watches a ball once it is
# below WATCH_Y, now and then looks away (LAPSE), ignores gems and picks a
# random card. Good bot: tracks perfectly, steers for gems when no ball is
# coming and picks the first ball-type card.
LAG_FRAMES = 4
FINGER_SPEED = 650.0
AIM_SD = 30.0
AIM_SD_PER_PX = 0.12
WATCH_Y = 330
LAPSE = 0.04


def predict_x(game, b):
    if b.dy <= 0:
        return b.x
    t = (game.paddle_y - b.r - b.y) / b.dy
    x = b.x + b.dx * t
    lo, hi = b.r, game.width - b.r
    span = hi - lo
    x = (x - lo) % (2 * span)
    return lo + (x if x <= span else 2 * span - x)


def play_round(seed, good, max_seconds=420.0, shots=False):
    game = started(seed)
    finger = 240.0
    aim_err = 0.0
    lapse = False
    last_dy = {}
    seen = []
    while game.state == "play" and game.play_t < max_seconds:
        if game.cards is not None:
            if game.t - game.cards_at >= PK.CARD_TAP_DELAY:
                kinds = [k for k, _ in game.cards]
                pick = next((k for k in kinds if k in PK.BALL_KINDS), kinds[0]) if good else random.choice(kinds)
                game.tap(*dict(game.cards)[pick].center)
                game.release()
            frames(game, 1)
            continue
        live = [b for b in game.balls if not b.stuck and not b.mini]
        down = [b for b in live if b.dy > 0]
        if down:
            b = max(down, key=lambda b: b.y)
            if last_dy.get(id(b), 0) <= 0:
                travel = abs(predict_x(game, b) - b.x)
                aim_err = random.gauss(0, AIM_SD + AIM_SD_PER_PX * travel) if not good else random.uniform(-35, 35)
                lapse = not good and random.random() < LAPSE
            target = predict_x(game, b) + aim_err
            if not good and (b.y < WATCH_Y or lapse):
                target = finger + (target - finger) * 0.25
            if good and b.y < game.paddle_y - 250 and game.gems:  # time to grab a gem
                target = max(game.gems, key=lambda g: g.y).x
        elif good and game.gems:
            target = max(game.gems, key=lambda g: g.y).x
        else:
            target = finger
        for b in live:
            last_dy[id(b)] = b.dy
        if good:
            finger = target
        else:
            seen.append(target)
            target = seen[-LAG_FRAMES] if len(seen) >= LAG_FRAMES else finger
            del seen[:-LAG_FRAMES]
            step = FINGER_SPEED * FRAME
            finger += max(-step, min(step, target - finger))
        game.drag(finger, 650)
        frames(game, 1)
        if shots and game.play_t > 75 and len(game.balls) >= 3 and game.cards is None and game.boss is None:
            shots = False
            shot(game, "02_midgame.png")
    return game


def test_bots():
    casual = [play_round(100 + s, good=False) for s in range(10)]
    good = [play_round(200 + s, good=True, shots=(s == 0)) for s in range(5)]
    for name, games in (("casual", casual), ("good", good)):
        for g in games:
            print(f"BOT {name:6s}: {g.play_t:5.0f} s, state {g.state}, Lv{g.player_lv}, score {PK.fmt(g.score)}, "
                  f"boss dmg {g.boss_damage_total} (kills {g.boss_kills}), balls {sum(1 for b in g.balls if not b.mini)}, "
                  f"picked {','.join(g.picked)}", flush=True)
    c = statistics.median(g.play_t for g in casual)
    gd = statistics.median(g.play_t for g in good)
    print(f"BOT: casual median {c:.0f} s (min {min(g.play_t for g in casual):.0f}, max {max(g.play_t for g in casual):.0f}), "
          f"good median {gd:.0f} s", flush=True)
    assert all(g.state == "over" for g in casual), "casual bot must lose"
    assert 60 <= c <= 180, c
    assert gd > 1.4 * c, (gd, c)
    return c, gd


def test_qa_regressions():
    """Bugs found in the QA pass (2026-10-31), one assert block each."""
    game = started(3)
    clear_wall(game)
    game.wall_y, game.top_row = float(PK.HUD_H + 6), 0
    # a ball in the 6 px gap between two bricks rattled down it: 5 hits a frame
    left = game._add(PK.Brick("normal", "SEXISMUS", 8, 0, 2, 99))
    right = game._add(PK.Brick("normal", "PAY GAP", 8, 2, 2, 99))
    gap_x = (game.brick_rect(left).right + game.brick_rect(right).left) / 2
    b = game.balls[0]
    b.stuck, b.x, b.y = False, gap_x, game.brick_rect(left).bottom + 2
    b.set_dir(0.05, -1.0)
    hits = []
    game._ball_hit = lambda ball, k, pos, f=game._ball_hit: (hits.append(k), f(ball, k, pos))
    game._move_ball(b, 60)
    assert len(hits) <= 1 and b.dy > 0, ("must bounce off the bottom, not rattle up the gap", len(hits))
    # wedged at the screen edge (6 px between brick and wall): bounces, stays on screen
    clear_wall(game)
    edge = game._add(PK.Brick("normal", "SEXISMUS", 8, 4, 2, 99))
    hits.clear()
    b.x, b.y = game.width - b.r, game.brick_rect(edge).bottom + 2
    b.set_dir(0.9, -0.3)
    for _ in range(10):
        game._move_ball(b, 20)
        assert b.r <= b.x <= game.width - b.r, b.x
    assert len(hits) <= 2, len(hits)
    # the wall jumped onto a ball (DROP_PUSH): it drops out below, not stuck between two rows
    clear_wall(game)
    upper = game._add(PK.Brick("normal", "SEXISMUS", 6, 2, 2, 99))
    lower = game._add(PK.Brick("armor", "HERRENCLUB", 7, 2, 2, 99))
    hits.clear()
    b.x, b.y = game.brick_rect(upper).centerx, game.brick_rect(upper).bottom + 3
    b.set_dir(0.1, 1.0)
    for _ in range(5):
        game._move_ball(b, 20)
    assert b.y - b.r >= game.brick_rect(lower).bottom - 1 and len(hits) <= 2, (b.y, len(hits))
    del game._ball_hit
    # every brick label stays readable with 2-3 digit HP (MANSPREADING / WAR IMMER SO / HAHA vanished)
    for label in PK.NORMAL_LABELS + ["STAMMTISCH", "HERRENCLUB"]:
        for hp in (17, 123):
            w = PK.FULL_W
            box_w = max(22, K.font(16).size(str(hp))[0] + 8)
            room = (w + 1 - 5 - box_w) - 1 - 6
            assert K.font(PK.LABEL_SIZES[-1]).size(label)[0] <= room or PK.BRICKS[label][1], (label, hp)
    assert K.font(PK.LABEL_SIZES[-1]).size("HAHA")[0] <= (PK.HALF_W + 1 - 5 - 28) - 1 - 6, "HAHA with 2-digit HP"
    # HUD: a big score shrinks instead of running into "Lv"
    game.score, game.player_lv = 123456789, 123
    game.draw(GAME_SURF)
    lv_left = game.width // 2 - 48 - 6 - K.font(16).size("Lv123")[0]
    sizes = (22, 20, 18, 16, 14)
    size = K.fit_size(PK.fmt(game.score), lv_left - 20, sizes=sizes)
    assert 12 + K.font(size).size(PK.fmt(game.score))[0] < lv_left - 4
    # cards: every description line fits its card; the heart card has no level tag
    for kind, (name, color, descs, max_lv) in PK.CARDS.items():
        for lines in descs:
            for line in lines:
                size = K.fit_size(line, 460 - 10 - (20 + 4 + 104 + 12), sizes=(15, 14, 13, 12), bold=False)
                assert K.font(size, False).size(line)[0] <= 460 - 10 - 140, (kind, line)
    # picking a card stamps something sensible ("Noch ein Discoball" stamped "NOCH!")
    for kind in PK.CARDS:
        game._pick(kind)
        assert game.stamp[0] != "NOCH!" and len(game.stamp[0]) <= 18, game.stamp[0]
    game.hearts = 1
    game._open_cards()
    game.cards = [(k, pygame.Rect(20, 230 + i * 142, game.width - 40, 128)) for i, k in enumerate(["herz", "wut", "disco"])]
    game._cards_surf = None
    game.draw(GAME_SURF)
    strip = game.cards[0][1]
    c = (strip.x + 4 + 52, strip.y + 4 + 60)
    assert game._cards_surf.get_at(c)[:3] == PK.RED, "heart visible on the pink strip"
    shot(game, "qa_cards_herz.png")
    game.cards = None
    # boss: HP line between name and bar, the bar never overflows
    clear_wall(game)
    game._spawn_boss(0)
    game.boss.hp = game.boss.max_hp + 50
    game.draw(GAME_SURF)
    shot(game, "qa_boss.png")
    print("QA: gap/edge/wedge collisions, brick labels, HUD fit, cards, stamps, boss layout ok", flush=True)


def test_long_run():
    """15 min, hearts topped up: no stuck balls, bounded lists, cheap frames; extreme frame times."""
    for seed, minutes, frame in ((7, 15, FRAME), (8, 2, 0.0005), (9, 2, 1.0)):
        game = started(seed)
        hits = [0]
        game._ball_hit = lambda ball, k, pos, f=game._ball_hit: (hits.__setitem__(0, hits[0] + 1), f(ball, k, pos))
        worst, ms = 0, []
        for _ in range(int(minutes * 60 / FRAME)):
            game.hearts = HEARTS_FULL
            if game.cards is not None and game.t - game.cards_at >= PK.CARD_TAP_DELAY:
                game.tap(*random.choice(game.cards)[1].center)
                game.release()
            live = [b for b in game.balls if not b.stuck and not b.mini and b.dy > 0]
            if live:
                b = max(live, key=lambda b: b.y)
                game.drag(predict_x(game, b) + random.uniform(-30, 30), 650)
            hits[0] = 0
            t0 = time.perf_counter()
            game.update(game.last_tick + frame)
            game.draw(GAME_SURF)
            ms.append((time.perf_counter() - t0) * 1000)
            worst = max(worst, hits[0] / max(1, sum(1 for b in game.balls if not b.stuck)))
            assert game.state == "play"
            assert all(b.stuck or (b.r - 1 <= b.x <= game.width - b.r + 1 and b.y >= PK.HUD_H) for b in game.balls)
            assert len(game.balls) <= PK.MAX_BALLS + 8 and len(game.parts) <= PK.MAX_PARTICLES and len(game.gems) < 200
        print(f"LONG RUN dt {frame}: {game.play_t:.0f} s, score {PK.fmt(game.score)}, kills {game.boss_kills}, breaches {game.breaches}, "
              f"frame mean {statistics.mean(ms):.2f} ms max {max(ms):.1f} ms", flush=True)
        if frame == FRAME:
            assert game.play_t > 600 and game.boss_kills >= 1
            assert statistics.mean(ms) < 3


HEARTS_FULL = PK.HEARTS


test_basics()
test_bricks_and_special()
test_danger_and_over()
test_xp_and_cards()
test_ball_types()
test_boss()
ms = test_perf()
test_qa_regressions()
test_long_run()
c, gd = test_bots()
print(f"All PATRIAPUTT tests passed - busy frame {ms:.1f} ms, casual bot median {c:.0f} s, good bot median {gd:.0f} s - "
      f"screenshots in {OUT}", flush=True)
P.quit_all()
