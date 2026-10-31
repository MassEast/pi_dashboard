#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless check of KIEZBLOCK (games_kiezblock.py), simulated time, no real
waiting:

- ready -> play -> over; taps in the HUD (incl. the emergency-exit corner,
  top-left 100x180 screen px) never do anything, in any state.
- hitting: SUV needs 2 taps (KLONK + freeze frame), conversion scores m² x
  combo multiplier, spawns particles/ring/popup, the product hops onto the
  sidewalk; a 5-combo shows WordArt; the combo runs out after COMBO_SECONDS.
- tapping a Lastenrad costs a heart; a car reaching the Spielstraße costs a
  heart; 0 hearts -> game over, stored in the Bestenliste (temp dir), taps
  ignored for GAME_OVER_TAP_DELAY_SECONDS, then NOCHMAL restarts.
- golden Poller -> KIEZBLOCK converts every car; the A100 boss -> FREIBAD.
- bots: an idle player loses fast, a decent bot (limited taps/s, reaction
  delay, sometimes misses) survives a fun-length round (30-150 s).
- performance: 100 busy frames of draw() are cheap.

Screenshots go to scratch/game_mockups/kiezblock/ (gitignored).
SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_kiezblock.py
"""

import json
import os
import random
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import pygame  # noqa: E402

import games_kiezblock as G  # noqa: E402
import kiezos as K  # noqa: E402
import party_games  # noqa: E402

OUT_DIR = os.path.join(REPO, "scratch", "game_mockups", "kiezblock")
os.makedirs(OUT_DIR, exist_ok=True)
FRAME = 1.0 / 20  # the Pi's game frame rate
TITLE_H = 36
EXIT_W, EXIT_H = 100, 180  # PiDashboard.EMERGENCY_EXIT_MAX_X/Y (screen px)

pygame.init()
SCREEN = pygame.display.set_mode((K.W, K.H))
K.configure(os.path.join(REPO, "fonts") + "/", os.path.join(REPO, "icons") + "/",
            json.load(open(os.path.join(REPO, "themes", "kiezos.json")))["KIEZOS"])
LOG_DIR = tempfile.mkdtemp(prefix="kiezblock_test_")
party_games.configure(LOG_DIR)  # never touch logs/
GAME_SURF = SCREEN.subsurface((0, TITLE_H, K.W, K.H - TITLE_H))


def new_game(now=1000.0):
    fonts = os.path.join(REPO, "fonts")
    game = G.KiezblockGame(K.W, K.H - TITLE_H, os.path.join(fonts, "JetBrainsMono-Medium.ttf"),
                           os.path.join(fonts, "JetBrainsMono-Bold.ttf"))
    game.show_close = False
    game.reset(now)
    return game


def shot(game, name):
    game.draw(GAME_SURF)
    K.game_title(SCREEN, "kiezblock.exe", "games")
    SCREEN.blit(G.menu_icon(22), (8, 7))
    pygame.image.save(SCREEN, os.path.join(OUT_DIR, name))


def run(game, now, seconds, on_frame=None):
    for _ in range(int(round(seconds / FRAME))):
        now += FRAME
        game.update(now)
        if on_frame is not None:
            on_frame(game, now)
    return now


def place(game, kind, lane, y, variant=0):
    """Puts a mover on the street at game-surface y (top), no spawning."""
    m = G._Mover(kind, (lane,) if kind != "a100" else (lane, lane + 1),
                 game.lane_x(lane) if kind != "a100" else (game.lane_x(lane) + game.lane_x(lane + 1)) / 2,
                 y, 0.0, variant)
    game.movers.append(m)
    return m


def center(m):
    r = m.rect()
    return r.centerx, r.centery


def quiet(game):
    """No spawning/bubbles: deterministic scenes."""
    game.spawn_in = 1e9
    game.next_bubble_at = 1e18


def corner_points():
    """Grid over the emergency-exit corner, in game-surface coordinates."""
    return [(x, y - TITLE_H) for x in range(0, EXIT_W, 9) for y in range(TITLE_H, EXIT_H, 9)]


def test_ready_and_corner():
    game = new_game()
    run(game, 1000.0, 0.6)
    shot(game, "01_start.png")
    assert G.HUD_HEIGHT + TITLE_H >= EXIT_H, "HUD must cover the emergency-exit corner"
    for x, y in corner_points():
        assert game.tap(x, y) is None and game.state == "ready", f"corner tap {x},{y} started the game"
    game.tap(240, 500)
    assert game.state == "play"
    quiet(game)
    car = place(game, "suv", 0, G.HUD_HEIGHT - 40)  # sticking out under the HUD, right in the corner column
    for x, y in corner_points():
        game.tap(x, y)
    assert car.hp == 2 and game.hearts == G.HEARTS and game.taps == 0, "corner tap reached the game"
    print("READY/CORNER: start screen, corner + HUD never tappable ok", flush=True)


def test_hit_convert_combo():
    game = new_game()
    game.tap(240, 500)
    quiet(game)
    now = game.last_tick
    suv = place(game, "suv", 1, 300)
    hx, hy = center(suv)
    game.tap(hx, hy)
    assert suv.hp == 1 and suv in game.movers, "SUV should need 2 taps"
    assert game.freeze_until > now and game.particles and game.rings, "hit feedback missing"
    frozen_t = game.t
    game.update(now + 0.01)
    assert game.t == frozen_t, "freeze frame should hold the simulation"
    now = run(game, now, 0.1)
    game.tap(*center(suv))
    assert suv not in game.movers and game.conversions == 1 and game.score == G.KINDS["suv"]["m2"]
    assert game.flying and any(p["text"].startswith("+15") for p in game.popups)
    now = run(game, now, 0.7)
    assert any(s is not None for s in game.slots), "product should land on the sidewalk"

    # 5 conversions in a row: WordArt + multiplier x2 for the 6th
    for i in range(4):
        m = place(game, "sport", i, 260 + i * 20)
        game.tap(*center(m))
        now = run(game, now, 0.1)
    assert game.combo == 5 and game.multiplier() == 2
    assert game.wordart is not None and game.wordart[0] == G.COMBO_WORDS[5]
    shot(game, "03_combo_wordart.png")
    before = game.score
    m = place(game, "sport", 2, 400)
    game.tap(*center(m))
    assert game.score - before == 2 * G.KINDS["sport"]["m2"], "multiplier not applied"
    now = run(game, now, G.COMBO_SECONDS + 0.3)
    assert game.combo == 0, "combo should run out"
    # a miss does nothing bad
    hearts = game.hearts
    game.tap(240, 600)
    assert game.hearts == hearts
    print("HIT/COMBO: 2-tap SUV, freeze frame, m² x multiplier, WordArt, combo timeout ok", flush=True)


def test_penalties_and_over():
    game = new_game()
    game.tap(240, 500)
    quiet(game)
    now = game.last_tick
    bike = place(game, "lastenrad", 2, 350)
    game.tap(*center(bike))
    assert game.hearts == G.HEARTS - 1 and game.bubble is not None, "tapping a Lastenrad must cost a heart"
    game.tap(*center(bike))
    assert game.hearts == G.HEARTS - 1, "offended Lastenrad can't be tapped twice in a row"
    now = run(game, now, 0.3)
    shot(game, "05_dada_lastenrad.png")
    # Cars reaching the Spielstraße
    for lane in (0, 3):
        car = place(game, "suv", lane, game.play_bottom - G.KINDS["suv"]["size"][1] * G.CELL + 10)
        car.speed = 100.0
    now = run(game, now, 0.3)
    assert game.state == "over", "two leaked cars with 2 hearts left should end the round"
    entries = party_games.top_list(game.NAME)
    assert entries and game.entry_id is not None, "round not stored"
    # taps right after game over are ignored
    game.draw(GAME_SURF)
    game.tap(240, 400)
    assert game.state == "over"
    now = run(game, now, 1.5)
    game.draw(GAME_SURF)
    assert "again" in game.buttons
    assert game.tap(*game.buttons["again"].center) is None and game.state == "ready"
    print("PENALTY/OVER: Lastenrad + leaks cost hearts, round stored, tap delay, NOCHMAL ok", flush=True)


def test_kiezblock_and_boss():
    game = new_game()
    game.tap(240, 500)
    quiet(game)
    now = game.last_tick
    cars = [place(game, k, i, 220 + i * 70, variant=i) for i, k in enumerate(["suv", "van", "panzer", "sport"])]
    ducks = place(game, "enten", 1, 470)
    poller = place(game, "poller", 2, 520)
    now = run(game, now, 0.1)
    shot(game, "02_mid_game.png")
    game.tap(*center(poller))
    assert game.kiezblock is not None and game.wordart[0] == "KIEZBLOCK!"
    now = run(game, now, 0.35)
    shot(game, "04_kiezblock.png")
    now = run(game, now, 0.6)
    assert not any(c in game.movers for c in cars), "KIEZBLOCK should convert every car"
    assert ducks in game.movers and game.hearts == G.HEARTS, "ducks must survive KIEZBLOCK"

    boss = place(game, "a100", 1, 300)
    hits = 0
    while boss in game.movers:
        game.tap(*center(boss))
        hits += 1
        now = run(game, now, 0.1)
        assert hits <= G.KINDS["a100"]["hp"]
    assert game.wordart[0] == "FREIBAD!" and hits == G.KINDS["a100"]["hp"]
    now = run(game, now, 0.05)
    shot(game, "06_freibad_boss.png")
    print("KIEZBLOCK/BOSS: poller clears cars, spares ducks; A100 -> FREIBAD ok", flush=True)


def test_einsicht():
    random.seed(3)
    game = new_game()
    game.tap(240, 500)
    quiet(game)
    now = game.last_tick
    m = place(game, "suv", 2, G.HUD_HEIGHT + 100)
    m.speed = 80.0
    m.einsicht = True
    now = run(game, now, 1.0)
    assert game.bubble is not None and game.bubble["text"] == G.EINSICHT_LINE
    shot(game, "05b_dada_einsicht.png")
    now = run(game, now, 1.5)
    assert m not in game.movers and game.conversions == 1
    print("EINSICHT: SUV converts itself ok", flush=True)


def bot_round(skill, seed, max_seconds=400):
    """skill: taps per second the bot can do (0 = idle). Reaction delay, 8%
    misses, never taps good things on purpose. Returns (seconds, game)."""
    random.seed(seed)
    game = new_game()
    game.tap(240, 500)
    now = game.last_tick
    state = {"next_tap": now + 0.4}

    def on_frame(g, t):
        if skill <= 0 or g.state != "play" or t < state["next_tap"]:
            return
        targets = g.tappable_bad()
        if not targets:
            return
        posters = [m for m in targets if m.kind == "poller"]
        m = posters[0] if posters else max(targets, key=lambda m: m.y + m.h)  # closest to the Spielstraße
        x, y = center(m)
        if random.random() < 0.08:
            x += random.choice((-1, 1)) * 60  # sloppy finger
        g.tap(x, y)
        state["next_tap"] = t + 1.0 / skill + random.uniform(0.0, 0.12)

    start = now
    for _ in range(int(max_seconds / FRAME)):
        now += FRAME
        game.update(now)
        on_frame(game, now)
        if game.state == "over":
            break
    return now - start, game


def test_bots():
    idle_s, _ = bot_round(0, 1)
    results = [bot_round(skill, seed) for skill in (3.0, 4.5) for seed in (1, 2, 3)]
    for (secs, g), skill in zip(results, (3.0, 3.0, 3.0, 4.5, 4.5, 4.5)):
        print(f"  bot {skill}/s: {secs:5.1f} s, {g.score} m², {g.conversions} conv, best combo {g.best_combo},"
              f" kiezblocks {g.kiezblock_count}", flush=True)
    print(f"  idle: {idle_s:.1f} s", flush=True)
    assert idle_s < 25, "doing nothing should lose quickly"
    mids = [s for s, _ in results[:3]]
    goods = [s for s, _ in results[3:]]
    assert 25 < sum(mids) / 3 < 150, f"3 taps/s bot round length {mids} outside the fun range"
    assert sum(goods) / 3 > sum(mids) / 3, "a faster player should last longer"
    assert all(s < 400 for s in goods), "a 4.5 taps/s bot should still lose eventually"

    # Game over of the best round: STAU! first, then the Bestenliste; type a name on the keyboard.
    secs, game = max(results, key=lambda r: r[1].score)
    now = run(game, game.last_tick, 0.25)
    shot(game, "06b_stau.png")
    now = run(game, now, 1.2)
    game.draw(GAME_SURF)
    game.tap(*game.buttons["name"].center)
    assert game.name_entry
    game.draw(GAME_SURF)
    keys = {token: rect for rect, token in game.key_rects}
    for ch in "KIM":
        game.tap(*keys[ch].center)
    game.tap(*keys["ok"].center)
    assert party_games.best(game.NAME)["name"] == "KIM", party_games.best(game.NAME)
    shot(game, "07_game_over_bestenliste.png")
    print("BOTS: idle loses fast, decent bots get fun-length rounds ok", flush=True)


def test_performance():
    game = new_game()
    game.tap(240, 500)
    quiet(game)
    now = game.last_tick
    for lane in range(4):
        for row in range(4):
            place(game, ["suv", "van", "panzer", "lastenrad"][(lane + row) % 4], lane, 160 + row * 130, variant=row)
    for _ in range(10):
        game._burst(240, 400, 40, [G.LEAF, G.WHITE], speed=300)
    game.conversions = 48
    game.slots = [("hochbeet", now - 5)] * len(game.slots)
    game.combo = 7
    game._wordart("VERKEHRSWENDE!")
    game.draw(GAME_SURF)  # warm caches
    t0 = time.perf_counter()
    for i in range(100):
        now += FRAME
        game.last_tick = now
        game.draw(GAME_SURF)
    per_frame = (time.perf_counter() - t0) / 100 * 1000
    print(f"PERF: busy frame draw {per_frame:.2f} ms ({len(game.particles)} particles, {len(game.movers)} movers)", flush=True)
    assert per_frame < 8.0, f"draw() too slow: {per_frame:.1f} ms/frame on a laptop (Pi ~5-8x slower)"


def test_bubble_and_shake_regressions():
    """Regressions: a bubble of a car just entering under the HUD (e.g. the A100's line) was drawn
    over that car; the screen shake scrolled the whole surface and smeared the HUD."""
    game = new_game()
    game.tap(240, 500)
    quiet(game)
    now = game.last_tick
    for lane in (0, 2):
        boss = place(game, "a100", lane, G.HUD_HEIGHT - 100)
        game._say(boss, G.DRIVE_LINES["a100"][0], 2.5)
        game.draw(GAME_SURF)
        car = boss.rect().clip(pygame.Rect(0, G.HUD_HEIGHT, game.width, game.height))
        assert not game.bubble_rect.colliderect(car), f"bubble covers the A100 (lane {lane})"
        assert game.bubble_rect.top >= G.HUD_HEIGHT and game.bubble_rect.bottom <= game.height
        game.movers.remove(boss)
    shot(game, "08_bubble_beside_a100.png")
    game.bubble = None
    game.shake_until, game.shake_amp = 0.0, 0
    game.draw(GAME_SURF)
    calm = GAME_SURF.subsurface((0, 0, game.width, G.HUD_HEIGHT)).copy()
    random.seed(1)
    game._shake(1.0, 12)
    game.draw(GAME_SURF)
    shaken = GAME_SURF.subsurface((0, 0, game.width, G.HUD_HEIGHT))
    assert pygame.image.tobytes(calm, "RGB") == pygame.image.tobytes(shaken, "RGB"), "shake must leave the HUD alone"
    # below 20 FPS the street keeps real time (sub-steps), a stall is dropped after 0.25 s
    t0 = game.t
    for _ in range(10):
        now += 0.1
        game.update(now)
    assert abs(game.t - t0 - 1.0) < 1e-6, game.t - t0
    game.update(now + 5.0)
    assert abs(game.t - t0 - 1.25) < 1e-6
    print("BUBBLE/SHAKE/SLOW FRAMES: bubble beside entering cars, HUD steady, 10 FPS keeps real time ok", flush=True)


if __name__ == "__main__":
    test_ready_and_corner()
    test_hit_convert_combo()
    test_penalties_and_over()
    test_kiezblock_and_boss()
    test_einsicht()
    test_bubble_and_shake_regressions()
    test_bots()
    test_performance()
    print(f"ALL PASSED - screenshots in {OUT_DIR}", flush=True)
