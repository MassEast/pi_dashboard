#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless checks of ENTEIGNEN! (enteignen.py) inside PiDashboard's Spiele menu:
start via spiele.exe, first swipe starts the run, a swipe through money cuts
it (two halves, hit-stop, +1 point), a resting finger never cuts, the blade
bounces off protected things (-1 heart, dead until lifted), 3+ cuts in one
swipe = KIEZFEST combo + slow-mo, uncut money fills the Steuerflucht meter
(full = -1 heart), hearts come back for a 4+ combo / a cut streak / a boss,
losing all hearts ends the run and stores it in the Bestenliste, PiDashboard
routes MOUSEMOTION/MOUSEBUTTONUP to the game, and a busy frame stays cheap.

Bosses: DAS PATRIARCHAT appears at ~45 s (warning first), cuts break letters
out and juggle it up, letting it fall costs a heart (and it comes back),
breaking all letters = victory + bonus + heart. MIETENHAI AG (~3:00) splits
tower -> 2 GmbHs -> 4 Briefkastenfirmen, falling small pieces = +3
Steuerflucht. DAS KAPITAL (~5:00): its orbiting shield bonks, cuts through
the gaps hurt it and spill money.

Simulated time; highscores in a temp dir. Screenshots: scratch/game_mockups/slice/real/.

SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_enteignen.py
"""

import math
import os
import random
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import enteignen as E  # noqa: E402
import kiezos as K  # noqa: E402
import party_games  # noqa: E402
import PiDashboard as P  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scratch", "game_mockups", "slice", "real")
os.makedirs(OUT, exist_ok=True)
party_games.configure(tempfile.mkdtemp(prefix="enteignen_scores_"))
FRAME = 1 / 20
random.seed(161)  # waves/minions are random; keep the run reproducible


def shot(name):
    P.draw_active_game()
    pygame.image.save(P.tft_surf, os.path.join(OUT, name))


def frames(game, n):
    for _ in range(n):
        game.update(game.last_tick + FRAME)


def throw(game, kind, x, y, vx=0.0, vy=0.0):
    th = E._Thing(kind, x, y, vx, vy)
    th.spin = 0
    game.things.append(th)
    return th


def swipe(game, pts):
    game.tap(*pts[0])
    for p in pts[1:]:
        game.drag(*p)
    game.release()


def vswipe(game, x, y0, y1, step=20):
    """Vertical swipe from y0 up to y1."""
    swipe(game, [(x, y) for y in range(int(y0), int(y1) - 1, -step)])


def open_enteignen():
    P.open_games_menu()
    P.draw_games_menu()
    rect = next(r for r, key in P.GAMES_MENU_RECTS if key == E.EnteignenGame.NAME)
    assert rect.bottom < P.GAMES_MENU_CLOSE_RECT.top, "all games must fit spiele.exe"
    assert P.handle_tap(*rect.center)
    game = P.ACTIVE_GAME
    assert isinstance(game, E.EnteignenGame) and game.state == "ready"
    assert not P.emergency_exit_active()
    return game


def started():
    game = open_enteignen()
    swipe(game, [(240, 400)])
    assert game.state == "play"
    game.next_wave_at = game.next_rain_at = 1e9
    return game


def to_boss(game, at):
    """Jump the run clock to just before `at`, run into the warning and
    through it; returns the boss."""
    game.things.clear()
    game.play_t = at - 0.2
    game.next_wave_at = game.next_rain_at = 1e9
    frames(game, 6)
    assert game.boss_phase == "warn", game.boss_phase
    frames(game, 20)
    shot(f"b{game.boss_no + 1}_0_warn.png")
    frames(game, int(E.WARN_SECONDS / FRAME))
    assert game.boss_phase == "fight" and game.boss is not None
    game.next_minion_at = 1e9
    return game.boss


def test_play():
    P.images = P.image_factory(P.ICON_PATH)
    P.DISPLAY_BLANK = False
    P.open_games_menu()
    P.draw_games_menu()
    pygame.image.save(P.tft_surf, os.path.join(OUT, "00_spiele_menu.png"))
    game = open_enteignen()
    game.next_wave_at = 1e9  # no random waves while testing
    shot("01_start.png")

    # first touch starts the round, nothing is cut by it
    swipe(game, [(240, 400)])
    assert game.state == "play"
    game.next_wave_at = game.next_rain_at = 1e9

    # a resting / jittering finger never cuts
    coin = throw(game, "coin", 240, 300)
    game.tap(200, 300)
    for dx in (2, 4, 3, 5, 6, 4):
        game.drag(200 + dx, 300)
    game.release()
    assert coin in game.things and game.score == 0, "jitter cut"

    # a real swipe cuts: halves, hit-stop, +1 point
    swipe(game, [(160, 340), (200, 315), (240, 300), (280, 285), (320, 260)])
    assert coin not in game.things and len(game.halves) == 2 and game.freeze == E.HIT_STOP_FRAMES
    assert game.score == 1
    frames(game, 1)
    shot("02_tsching.png")
    frames(game, 40)
    assert not game.halves, "halves tumble off screen"

    # protected: blade bounces off, -1 heart, dead until lifted
    cat = throw(game, "cat", 240, 300)
    note = throw(game, "note", 330, 300)
    game.tap(150, 300)
    for x in range(170, 420, 20):
        game.drag(x, 300)
    assert game.lives == E.LIVES - 1 and cat in game.things and note in game.things, "blade must stop at the cat"
    frames(game, 2)
    shot("03_klonk.png")
    game.release()
    game.things.clear()
    frames(game, 40)

    # combo: 4 in one swipe = 4 + bonus, slow-mo, and the lost heart comes back
    for i, kind in enumerate(["bag", "miete", "ticker", "yacht"]):
        throw(game, kind, 80 + i * 105, 360)
    before = game.score
    swipe(game, [(20, 362)] + [(x, 360) for x in range(40, 470, 20)])
    assert not game.things and game.best_combo == 4 and game.t < game.slowmo_until
    assert game.score - before == 4 + E.combo_bonus(4), game.score - before
    assert game.lives == E.LIVES and game.heart_flies, "4+ combo gives a heart back"
    frames(game, 3)
    shot("04_combo.png")

    # mid-game with random waves, for a look
    game.next_wave_at = game.play_t
    frames(game, 40)
    shot("05_ingame.png")
    print(f"PLAY: cut/jitter/klonk/combo/heart ok, {game.score} Punkte", flush=True)
    P.close_games("test")


def test_steuerflucht_and_hearts():
    game = started()
    # uncut money falling back down fills the meter; minions/protected don't count
    throw(game, "cat", 200, game.height + 50, vy=200)
    throw(game, "zange", 260, game.height + 50, vy=200)
    frames(game, 2)
    assert game.flucht == 0
    for i in range(E.FLUCHT_MAX - 1):
        throw(game, "coin", 100 + i * 30, game.height + 50, vy=200)
    frames(game, 2)
    assert game.flucht == E.FLUCHT_MAX - 1 and game.lives == E.LIVES
    shot("07_steuerflucht.png")
    throw(game, "note", 240, game.height + 50, vy=200)
    frames(game, 2)
    assert game.flucht == 0 and game.lives == E.LIVES - 1, (game.flucht, game.lives)
    assert game.toast[0] == "steuerflucht.exe"

    # STREAK_HEART cuts in a row without a miss -> +1 heart
    game.streak = 0
    for i in range(E.STREAK_HEART):
        throw(game, "coin", 240, 300)
        swipe(game, [(150, 300), (200, 300), (260, 300), (320, 300)])
        frames(game, 5)
    assert game.lives == E.LIVES, game.lives
    print("STEUERFLUCHT: meter fills, full = -1 heart; streak heart ok", flush=True)

    # all hearts gone -> Kündigung, run lands in the Bestenliste
    for _ in range(E.LIVES):
        throw(game, "pfand", 240, 300)
        swipe(game, [(150, 300), (200, 300), (260, 300), (320, 300)])
        game.things.clear()
    frames(game, 6)
    assert game.state == "over" and game.over_text.startswith("Kündigung"), game.over_text
    assert party_games.best(E.EnteignenGame.NAME)["score"] == game.score
    frames(game, 20)
    shot("06_gameover.png")
    print(f"KÜNDIGUNG: '{game.over_text}', stored with {game.score} Punkte", flush=True)
    P.close_games("test")


def test_patriarchat():
    game = started()
    assert game.next_boss_at == E.BOSS_TIMES[0]
    game.play_t = 30.0
    frames(game, 2)
    assert game.boss_phase is None and game.boss is None, "no boss before ~45 s"
    boss = to_boss(game, E.BOSS_TIMES[0])
    assert isinstance(boss, E._Patriarchat) and boss.hp == boss.max_hp == len(E.PATRIARCHAT)
    frames(game, 22)
    shot("b1_1_entrance.png")

    def hit(i):
        b = boss.body
        b.x, b.y, b.vx, b.vy, b.angle, b.spin = 240, 430, 0.0, 0.0, 0.0, 0.0
        hp, score = boss.hp, game.score
        vswipe(game, 240 + boss._bx(i), 540, 320)
        assert boss.hp == hp - 1 and game.score > score, (i, boss.hp, hp)
        assert b.vy < -300, "a cut juggles it back up"
        frames(game, 8)  # past hit-stop + the hit cooldown

    for i in (0, 4, 7, 10):
        hit(i)
        assert not boss.alive[i], f"letter {i} must break out"
    assert not boss.cigar, "cigar drops at 75 % HP"
    game.next_minion_at = game.play_t
    frames(game, 30)
    game.next_minion_at = 1e9
    for _ in range(4):  # a minion wave can be a protected thing (15 %)
        if any(th.kind in E.MINIONS for th in game.things):
            break
        game.next_minion_at = game.play_t
        frames(game, 10)
    game.next_minion_at = 1e9
    assert any(th.kind in E.MINIONS for th in game.things), "minions fly during the fight"
    b = boss.body
    b.x, b.y, b.vx, b.vy = 240, 360, 0.0, -100.0
    shot("b1_2_midfight.png")

    # falling into the Kiez: -1 heart, it "vertagt sich" and comes back
    lives = game.lives
    b.y, b.vy = game.height + 75, 50.0
    frames(game, 1)
    assert game.lives == lives - 1 and b.down_at is not None
    frames(game, 34)
    assert b.down_at is None and b.vy < 0 and b.y > game.height - 250, "thrown up again from below"
    game.things.clear()

    # smash the rest -> victory, bonus, +1 heart, back to waves later
    before, lives = game.score, game.lives
    for i in [k for k, a in enumerate(boss.alive) if a]:
        hit(i)
    frames(game, E.HIT_STOP_FRAMES + 1)
    assert game.boss_phase == "victory" and game.boss is None and game.bosses_beaten == 1
    assert game.score - before >= E._Patriarchat.BONUS and game.lives == min(E.LIVES, lives + 1)
    frames(game, 14)
    shot("b1_3_victory.png")
    frames(game, int(E.VICTORY_SECONDS / FRAME) + 2)
    assert game.boss_phase is None and game.next_boss_at == E.BOSS_TIMES[1]
    print(f"PATRIARCHAT: appears at {E.BOSS_TIMES[0]:.0f} s, chip/juggle/fall/victory ok", flush=True)

    # ---- boss 2
    boss = to_boss(game, E.BOSS_TIMES[1])
    assert isinstance(boss, E._Mietenhai)
    frames(game, 22)
    shot("b2_1_entrance.png")

    def hit_piece(p, others_to=(60, 250)):
        for o in boss.pieces:
            o.vx = o.vy = 0.0
            o.angle = o.spin = 0.0
            o.down_at = None
            if o is not p:
                o.x, o.y = others_to
        p.x, p.y = 300, 430
        hp = boss.hp
        vswipe(game, 300, 600, 260)
        assert boss.hp == hp - 1, (p.kind, boss.hp, hp)

    tower = boss.pieces[0]
    for _ in range(boss.hp_of["ag"] - 1):
        hit_piece(tower)
        frames(game, 8)
    assert tower.crack == boss.hp_of["ag"] - 1
    hit_piece(tower)
    assert [p.kind for p in boss.pieces] == ["gmbh", "gmbh"], "the tower splits into two GmbHs"
    frames(game, 6)
    game.next_minion_at = game.play_t
    frames(game, 8)
    game.next_minion_at = 1e9
    shot("b2_2_midfight.png")
    hit_piece(boss.pieces[0], others_to=(380, 300))
    assert sorted(p.kind for p in boss.pieces) == ["box", "box", "gmbh"]
    hit_piece(next(p for p in boss.pieces if p.kind == "gmbh"), others_to=(100, 300))
    assert [p.kind for p in boss.pieces] == ["box"] * 4
    frames(game, 8)
    shot("b2_3_briefkaesten.png")
    box = boss.pieces[0]
    flucht = game.flucht
    box.y, box.vy = game.height + 70, 50.0
    frames(game, 1)
    assert game.flucht == flucht + 3 and box.down_at is not None, "a falling Briefkastenfirma flees: +3 Steuerflucht"
    for _ in range(80):  # (slow-mo from an incidental combo can stretch this)
        frames(game, 1)
        if box.down_at is None:
            break
    assert box.down_at is None and box.vy < 0, "the Briefkastenfirma is thrown back up"
    game.things.clear()
    while boss.pieces:
        hit_piece(boss.pieces[0], others_to=(240, 260))
    frames(game, E.HIT_STOP_FRAMES + 1)
    assert game.boss_phase == "victory" and game.bosses_beaten == 2 and game.flucht == 0, (game.boss_phase, game.bosses_beaten, game.flucht, game.lives, game.state)
    frames(game, 14)
    shot("b2_4_victory.png")
    frames(game, int(E.VICTORY_SECONDS / FRAME) + 2)
    print("MIETENHAI: tower -> GmbHs -> Briefkästen, Luxemburg-Steuerflucht, victory ok", flush=True)

    # ---- boss 3
    game.lives = E.LIVES
    boss = to_boss(game, E.BOSS_TIMES[2])
    assert isinstance(boss, E._Kapital)
    frames(game, int(E._Kapital.ENTER / FRAME) + 2)
    game.things.clear()
    shot("b3_1_entrance.png")

    # the shield: cutting an orbiting cat/bus/... = KLONK, -1 heart, pig unhurt
    th = boss.orbit[0]
    hp, lives = boss.hp, game.lives
    ang = math.atan2(th.y - boss.cy - 10, th.x - boss.cx)
    tx, ty = -math.sin(ang), math.cos(ang)  # tangent through the orbiter
    swipe(game, [(th.x - tx * k, th.y - ty * k) for k in range(-80, 81, 20)])
    assert game.lives == lives - 1 and boss.hp == hp and game.bounced
    frames(game, 12)

    def gap_hit():
        a = boss.phi + math.pi / len(boss.orbit)  # the middle of a gap between two orbiters
        cx, cy = boss.cx, boss.cy + 12
        pts = [(cx + math.cos(a) * r, cy + math.sin(a) * r) for r in range(240, -1, -20)]
        hp, things = boss.hp, len(game.things)
        swipe(game, pts)
        assert boss.hp == hp - 1, "a cut through the gap hurts it"
        assert len(game.things) > things, "a hit spills money"

    gap_hit()
    frames(game, 6)
    shot("b3_2_midfight.png")
    for _ in range(boss.hp - 1):
        frames(game, 8)
        game.things.clear()
        gap_hit()
    assert not boss.hat and not boss.monocle
    frames(game, 8)
    game.things.clear()
    gap_hit()
    frames(game, E.HIT_STOP_FRAMES + 1)
    assert game.boss_phase == "victory" and game.bosses_beaten == 3
    frames(game, 14)
    shot("b3_3_victory.png")
    frames(game, int(E.VICTORY_SECONDS / FRAME) + 2)
    assert game.boss_phase is None and game.next_boss_at == E._boss_time(3)
    assert E._boss_class(3) == (E._Patriarchat, 2), "after boss 3 they come back stronger"

    # performance: a busy boss frame (plaque, minions, halves, particles, stamps)
    game.play_t = game.next_boss_at - 0.1
    frames(game, int(E.WARN_SECONDS / FRAME) + 8)
    boss = game.boss
    assert isinstance(boss, E._Patriarchat) and boss.max_hp == 2 * len(E.PATRIARCHAT)
    for i in range(6):
        throw(game, "coin", 60 + i * 70, 250)
        throw(game, E._Patriarchat.MINIONS[i], 60 + i * 70, 480)
    swipe(game, [(20, 252)] + [(x, 250) for x in range(40, 470, 20)])
    t0 = time.perf_counter()
    for _ in range(50):
        game.update(game.last_tick + FRAME)
        game.draw(P.tft_surf.subsurface((0, P.GAME_TITLE_HEIGHT, P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT)))
    ms = (time.perf_counter() - t0) / 50 * 1000
    print(f"PERF: {ms:.1f} ms per busy boss frame on this machine", flush=True)
    assert ms < 25, ms
    print(f"KAPITAL: shield klonk, gap hits, money spill, victory ok; {game.score} Punkte", flush=True)
    P.close_games("test")


def test_combos():
    game = started()
    game.next_rain_at = 1e9
    # streak across swipes: x2 from 5 cuts in a row, "5er-Serie!", reset on an escape
    for i in range(E.STREAK_STEP):
        throw(game, "coin", 240, 300)
        swipe(game, [(150, 300), (200, 300), (260, 300), (320, 300)])
        frames(game, 4)
    assert game.streak == E.STREAK_STEP and game.mult() == 2 and game.serie[0] == "5er-Serie!"
    before = game.score
    throw(game, "coin", 240, 300)
    swipe(game, [(150, 300), (200, 300), (260, 300), (320, 300)])
    assert game.score - before == 2, "x2 multiplier"
    frames(game, 2)
    shot("08_serie.png")
    throw(game, "coin", 240, game.height + 50, vy=200)
    frames(game, 2)
    assert game.streak == 0 and game.mult() == 1, "an escape breaks the streak"
    throw(game, "coin", 240, 300)
    swipe(game, [(150, 300), (200, 300), (260, 300), (320, 300)])
    throw(game, "pfand", 240, 300)
    swipe(game, [(150, 300), (200, 300), (260, 300), (320, 300)])
    assert game.streak == 0, "a protected hit breaks the streak"
    game.things.clear()
    frames(game, 30)

    # GELDREGEN: 4-6 coins thrown one after another (not all at once, different heights);
    # a swipe that follows them still catches several = KIEZFEST
    game.streak = 0
    game._spawn_rain()
    assert not game.things and 4 <= len(game.rain_queue) <= 6, "thrown one after another"
    dues = [q[0] for q in game.rain_queue]
    assert max(dues) - min(dues) >= 0.45 and len({round(q[4]) for q in game.rain_queue}) > 1
    while game.rain_queue:
        frames(game, 1)
    rain = list(game.things)
    assert all(th.kind in ("coin", "note") for th in rain)
    while max(th.vy for th in rain) < -60:
        frames(game, 1)
    path = sorted((th.x, th.y) for th in rain)  # a skilled swipe: through each coin, left to right
    pts = []
    for (x0, y0), (x1, y1) in zip(path, path[1:]):
        pts += [(x0 + (x1 - x0) * k / 4, y0 + (y1 - y0) * k / 4) for k in range(4)]
    pts.append(path[-1])
    swipe(game, [(path[0][0] - 40, path[0][1])] + pts + [(path[-1][0] + 40, path[-1][1])])
    assert game.best_combo >= 3, game.best_combo
    assert game.combo_at == game.t and game.t < game.slowmo_until
    frames(game, 3)
    shot("09_geldregen_combo.png")
    print(f"COMBOS: streak x2/serie/reset ok, GELDREGEN {len(rain)} coins -> {game.best_combo}x KIEZFEST", flush=True)
    P.close_games("test")


def test_routing():
    # PiDashboard's event loop: MOUSEMOTION (finger down) -> drag, MOUSEBUTTONUP -> release
    game = started()
    throw(game, "gold", 240, 300)
    calls = []
    game.drag = lambda x, y, f=game.drag: (calls.append((x, y)), f(x, y))
    title = P.GAME_TITLE_HEIGHT
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(150, 300 + title), button=1))
    for x in (190, 230, 270, 310):
        pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=(x, 300 + title), rel=(40, 0), buttons=(1, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(310, 300 + title), button=1))
    for event in pygame.event.get():
        if event.type == pygame.MOUSEBUTTONDOWN:
            P.handle_tap(*event.pos)
        elif event.type == pygame.MOUSEMOTION and event.buttons[0]:
            P.ACTIVE_GAME.drag(event.pos[0], event.pos[1] - title)
        elif event.type == pygame.MOUSEBUTTONUP:
            P.ACTIVE_GAME.release()
    assert calls == [(190, 300), (230, 300), (270, 300), (310, 300)] and game.score == 1
    src = open(P.__file__).read()
    assert "ACTIVE_GAME.drag(event.pos[0], event.pos[1] - GAME_TITLE_HEIGHT)" in src and "ACTIVE_GAME.release()" in src
    print("ROUTING: motion/up reach the game", flush=True)
    P.close_games("test")


def test_qa_regressions():
    """Bugs found in the QA pass (2026-10-31), one assert block each."""
    game = started()
    surf = P.tft_surf.subsurface((0, P.GAME_TITLE_HEIGHT, P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT))
    # the streak WordArt goes when the streak breaks (it stayed up next to "Serie gerissen!")
    game.streak, game.serie = 25, ("25er-Serie!", game.t)
    game._break_streak()
    assert game.serie is None and game.streak == 0
    # "Serie gerissen!" is not hidden behind the boss bar window (y 92..152)
    game.streak, game.boss = 10, object()
    game._break_streak()
    assert game.popups[-1].text == "Serie gerissen!" and game.popups[-1].y > 152
    game.boss = None
    game.popups.clear()
    # big scores shrink instead of running into "Steuerflucht" (x >= 364) with x5 next to them
    for score in (12345, 1234567, 123456789):
        size = K.fit_size(str(score), E.SCORE_MAX_W, sizes=(34, 30, 26, 22, 18))
        w = E.outlined_image(str(score), size, E.GOLD).get_width() - 4
        mult_w = E.outlined_image("x5", 22, E.PINK).get_width()
        assert game.width // 2 + w / 2 + 8 + mult_w < 360, (score, size, w)
    game.score, game.streak = 123456789, 30
    game.draw(surf)
    game.score = game.streak = 0
    # no revive: a boss beaten in the frame the last heart went doesn't bring a heart back
    game.lives = 0
    game._gain_life(240, 400, "Boss besiegt!")
    assert game.lives == 0 and not game.heart_flies
    # and the blade is dead once the hearts are gone (cuts before the over frame scored)
    th = throw(game, "coin", 240, 300)
    swipe(game, [(150, 300), (200, 300), (260, 300), (320, 300)])
    assert th in game.things and game.score == 0, "no cuts with 0 hearts"
    frames(game, E.HIT_STOP_FRAMES + 2)
    assert game.state == "over"
    P.close_games("test")

    # victory popups: one column, no overlap (the heart lines ran into "Steuerflucht-Meter geleert")
    game = started()
    game.next_boss_at = game.play_t + 0.01
    frames(game, int(E.WARN_SECONDS / FRAME) + 4)
    assert game.boss_phase == "fight"
    game.lives, game.flucht = 1, 4
    game._victory()
    for age in (0.4, 0.9, 1.5):
        rects = []
        for p in game.popups:
            y = p.y - p.rise * max(0.0, age - p.delay)
            img = E.outlined_image(p.text, p.size, p.color)
            rects.append(img.get_rect(center=(int(p.x), int(y))).inflate(-4, -4))
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                assert not a.colliderect(b), (age, [p.text for p in game.popups])
    P.close_games("test")

    # DAS KAPITAL: its shield's top stays below the boss bar window (y 92..152), spilled money too
    game = started()
    game.boss_no = 2
    game.next_boss_at = game.play_t + 0.01
    frames(game, int(E.WARN_SECONDS / FRAME) + 4)
    boss = game.boss
    assert isinstance(boss, E._Kapital)
    for _ in range(int(30 / FRAME)):
        boss.step(FRAME)
        if boss.t > boss.ENTER:
            top = min(th.y - E._orbit_img(th.kind).get_height() / 2 for th in boss.orbit)
            assert top > 152, top
    apex = boss.cy - 500 ** 2 / (2 * E.GRAVITY)  # fastest spill
    assert apex > 100, apex
    P.close_games("test")

    # halves are cropped to their pixels (half the area to rotate every frame on the Pi)
    game = started()
    th = throw(game, "yacht", 240, 300)
    swipe(game, [(240, 200), (240, 240), (240, 280), (240, 320), (240, 360), (240, 400)])
    assert len(game.halves) == 2
    sprite = E._sprites()["yacht"]
    for h in game.halves:
        assert h.surf.get_width() * h.surf.get_height() <= sprite.get_width() * sprite.get_height() * 0.75
        assert h.surf.get_bounding_rect().size == h.surf.get_size()
    # the glowing cut edge is still there, only on the half's own pixels
    left = E.split_image(sprite, (sprite.get_width() / 2, 0), (0.0, 1.0), (-1.0, 0.0), 1)
    edge_x = sprite.get_width() // 2 - 1
    whites = [y for y in range(sprite.get_height()) if left.get_at((edge_x, y))[:3] == (255, 255, 255)]
    assert len(whites) > 10, whites
    assert all(left.get_at((x, y)).a == 0 for x in range(sprite.get_width() // 2 + 1, sprite.get_width()) for y in range(0, sprite.get_height(), 7))
    # flying things come from bounded rotation buckets, not a fresh rotate per frame
    a, b = E._Thing("coin", 0, 0, 0, 0), E._Thing("coin", 0, 0, 0, 0)
    a.angle, b.angle = 10.0, 11.5
    assert a.image() is b.image()
    print("QA: serie reset, HUD fit, no revive at 0 hearts, victory popups, KAPITAL below the bar, cheap halves ok", flush=True)
    P.close_games("test")


def _bot_targets(game):
    out = []
    b = game.boss
    if b is not None and game.boss_phase == "fight":
        if isinstance(b, E._Patriarchat):
            if b.body.down_at is None and b.body.vy > 0 and b.body.y > 380:
                out.append((b.body.x, b.body.y, 60))
        elif isinstance(b, E._Mietenhai):
            out += [(p.x, p.y, 40) for p in b.pieces if p.down_at is None and p.vy > 0 and p.y > 380]
        elif b.t > b.ENTER:
            out.append((b.cx, b.cy + 12, 50))
    out += [(th.x, th.y, th.r) for th in game.things if not th.protected and th.vy > -100 and 120 < th.y < game.height - 40]
    return out


def _bot_safe(game, a, b):
    shield = game.boss.orbit if isinstance(game.boss, E._Kapital) else []
    return not any(E._seg_circle_hit(a, b, (th.x, th.y), th.r + 12) for th in game.things + shield if th.protected)


def bot_run(seed, minutes, immortal, frame=FRAME):
    """A swiping bot through the real input API: cuts what it can reach,
    juggles bosses, avoids protected things. immortal: hearts topped up, to
    get through many boss cycles. Returns the game and per-frame ms."""
    random.seed(seed)
    game = started()
    game.next_wave_at, game.next_rain_at = 0.6, 12.0
    surf = P.tft_surf.subsurface((0, P.GAME_TITLE_HEIGHT, P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT))
    ms, cooldown = [], 0
    for _ in range(int(minutes * 60 / frame)):
        if game.state != "play":
            break
        if immortal:
            game.lives = max(game.lives, 2)
        t0 = time.perf_counter()
        targets = _bot_targets(game) if cooldown <= 0 else []
        if targets:
            x, y, r = random.choice(targets)
            ang = random.uniform(-0.6, 0.6)
            a = (x - math.cos(ang) * (r + 30), y - math.sin(ang) * (r + 30))
            b = (x + math.cos(ang) * (r + 30), y + math.sin(ang) * (r + 30))
            if _bot_safe(game, a, b):
                swipe(game, [(a[0] + (b[0] - a[0]) * k / 4, a[1] + (b[1] - a[1]) * k / 4) for k in range(5)])
                cooldown = 2
        cooldown -= 1
        game.update(game.last_tick + frame)
        game.draw(surf)
        ms.append((time.perf_counter() - t0) * 1000)
        assert 0 <= game.lives <= E.LIVES and 0 <= game.flucht < E.FLUCHT_MAX
        assert len(game.halves) < 80 and len(game.parts) < 1500
    return game, ms


def test_long_run():
    """15 min with many boss cycles (BOSS_REPEAT, levels 2-3), then extreme frame times."""
    t0 = time.time()
    game, ms = bot_run(4, 15, immortal=True)
    print(f"LONG RUN: {game.play_t:.0f} s, {game.bosses_beaten} bosses beaten (met {game.boss_no}), {game.score} Punkte, "
          f"frame mean {sum(ms) / len(ms):.2f} ms, p99 {sorted(ms)[int(len(ms) * 0.99)]:.2f} ms, max {max(ms):.1f} ms "
          f"({time.time() - t0:.0f} s wall)", flush=True)
    assert game.state == "play" and game.play_t > 600 and game.bosses_beaten >= 4, (game.play_t, game.bosses_beaten)
    assert sum(ms) / len(ms) < 3, "mean frame must stay far below 5 ms here (= 50 ms on a Pi)"
    P.close_games("test")
    for frame in (0.0005, 1.0):  # 2000 FPS and a 1 s stall per frame (update caps dt)
        game, _ = bot_run(5, 1, immortal=True, frame=frame)
        assert game.state == "play"
        P.close_games("test")
    game, _ = bot_run(6, 10, immortal=False)
    assert game.state == "over", "without help the bot loses"
    print(f"EXTREME DT ok; mortal bot lost after {game.play_t:.0f} s", flush=True)
    P.close_games("test")


test_play()
test_steuerflucht_and_hearts()
test_patriarchat()
test_combos()
test_routing()
test_qa_regressions()
test_long_run()
print(f"All ENTEIGNEN! tests passed - screenshots in {OUT}", flush=True)
P.quit_all()
