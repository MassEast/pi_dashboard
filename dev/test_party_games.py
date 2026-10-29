#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless check of the PLAY menu and the party_games.py games:

- PLAY pill (GAMES.ENABLED, also covers MERZ) opens the "Spiele" menu, cards start MERZ / STAPEL-TURM /
  FLAPPY BVG, "Schließen" closes, emergency exit only off inside a game.
- STAPEL-TURM: perfect drop keeps the width, offset drop cuts it, a full
  miss ends the game, game-over taps are ignored for a moment, NOCHMAL/MENÜ.
- Highscores: a top-5 score asks for a name (on-screen keyboard), saves it
  to the JSON store (temp dir), the list keeps only 5, a score that doesn't
  make it skips the keyboard, closing mid-entry still saves (as ANONYM).
- FLAPPY BVG: no taps -> crashes into the street; a simple tapping bot gets
  through barriers (the physics are actually playable); x closes.
- MERZ: clock starts with the first throw (not a pill tap), the win opens
  the same name keyboard + Bestenliste, sorted by time (lower is better),
  NOCHMAL restarts MERZ, MENÜ goes back, closing mid-entry still saves;
  the banner stays MERZ_RESULT_DELAY_SECONDS before the panel, BURN rounds
  get a flame mark.
- Idle timeout and display blank close the game.

Simulated time, no real waiting. Screenshots go to a fresh temp dir (path
printed at the end). Run directly:
SDL_VIDEODRIVER=dummy venv/bin/python3 dev/test_party_games.py
"""

import os
import random
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import party_games  # noqa: E402
import PiDashboard as P  # noqa: E402

OUT_DIR = tempfile.mkdtemp(prefix="pidashboard_games_")
FRAME = 1.0 / 30
# Never touch the real logs/game_highscores.json.
party_games.configure(os.path.join(OUT_DIR, "logs"))


def shot(name):
    pygame.image.save(P.tft_surf, os.path.join(OUT_DIR, name))


def run_frames(game, now, seconds, on_frame=None):
    """Advance simulated time; stops early when the game ends meanwhile."""
    was_over = game.state == "over"
    for _ in range(int(seconds / FRAME)):
        now += FRAME
        game.update(now)
        if on_frame is not None:
            on_frame(game)
        if game.state == "over" and not was_over:
            break
    return now


def test_menu():
    P.DISPLAY_BLANK = False
    P.GAMES_ENABLED = True
    exit_zone = pygame.Rect(0, 0, P.EMERGENCY_EXIT_MAX_X, P.EMERGENCY_EXIT_MAX_Y)
    # Start -> Spiele opens the submenu with all three games.
    P.close_start_menu()
    P.draw_home()
    assert P.handle_tap(*P.START_BUTTON_RECT.center) and P.START_MENU_OPEN
    P.draw_home()
    assert P.handle_tap(*next(r for r, a in P.START_MENU_RECTS if a == "games_sub").center)
    P.draw_home()
    shot("00_start_spiele.png")
    sub = [a for _, a in P.START_MENU_RECTS if a.startswith("game:")]
    assert sub == ["game:STAPEL-TURM", "game:FLAPPY BVG", "game:merz"], sub
    for rect, action in P.START_MENU_RECTS:
        assert not rect.colliderect(exit_zone), f"{action} in the emergency-exit zone"
    assert P.handle_tap(*next(r for r, a in P.START_MENU_RECTS if a == "game:merz").center)
    assert P.MERZ_VISIBLE and not P.START_MENU_OPEN
    P.dismiss_merz_game("test")

    # spiele.exe (where a game's MENÜ button leads)
    P.open_games_menu()
    assert P.emergency_exit_active(), "emergency exit must stay on in the menu"
    P.draw_home()
    P.draw_dashboard_overlays()
    shot("01_menu.png")
    keys = [key for _, key in P.GAMES_MENU_RECTS]
    assert keys == ["STAPEL-TURM", "FLAPPY BVG", "merz"], keys
    for rect, key in P.GAMES_MENU_RECTS:
        assert not rect.colliderect(exit_zone), f"menu card {key} in the emergency-exit zone"
        assert not rect.colliderect(P.GAMES_MENU_CLOSE_RECT), f"menu card {key} overlaps Schließen"
        assert 0 <= rect.left and rect.right <= P.DISPLAY_WIDTH
    # Names and record lines fit the card (text starts 112 px in).
    for game_cls in list(party_games.GAMES) + [party_games.MerzResult]:
        card = P.GAMES_MENU_RECTS[0][0]
        assert 112 + P.K.font(22).size(game_cls.NAME)[0] < card.width - 8, f"{game_cls.NAME} name too long"
        assert 112 + P.K.font(15, False).size(party_games.record_line(game_cls))[0] < card.width - 8

    # Taps on empty menu space are swallowed, not passed to the dashboard.
    assert P.handle_tap(P.DISPLAY_WIDTH // 2, P.GAMES_MENU_CLOSE_RECT.top - 4)
    assert P.GAMES_MENU_OPEN

    # MERZ card: closes the menu, opens MERZ.
    merz_rect = next(r for r, key in P.GAMES_MENU_RECTS if key == "merz")
    assert P.handle_tap(*merz_rect.center)
    assert P.MERZ_VISIBLE and not P.games_open()
    P.dismiss_merz_game("test")

    # Schließen and the title bar's x.
    for close in ("GAMES_MENU_CLOSE_RECT", "GAMES_MENU_TITLE_X"):
        P.open_games_menu()
        P.draw_games_menu()
        assert P.handle_tap(*getattr(P, close).center)
        assert not P.games_open(), close

    # GAMES disabled: no Spiele in the Start menu (MERZ included, one flag for all games).
    P.GAMES_ENABLED = False
    assert "games_sub" not in [a for _, _, a in P._start_menu_items()]
    P.GAMES_ENABLED = True
    print("MENU: Start -> Spiele -> MERZ, spiele.exe -> MERZ/close ok, config gating ok", flush=True)


def press(game, token):
    game.tap(*next(r for r, t in game.key_rects if t == token).center)


def type_name(game, text, ok=True):
    for token in text:
        press(game, token)
    if ok:
        press(game, "ok")


def open_game(name):
    P.open_games_menu()
    P.draw_games_menu()
    rect = next(r for r, key in P.GAMES_MENU_RECTS if key == name)
    assert P.handle_tap(*rect.center)
    assert P.ACTIVE_GAME is not None and P.ACTIVE_GAME.NAME == name
    assert not P.emergency_exit_active(), "emergency exit must be off inside a game"
    return P.ACTIVE_GAME


def test_stack():
    game = open_game("STAPEL-TURM")
    now = game.last_tick
    game.draw(P.tft_surf)
    shot("02_stack_ready.png")
    # The first tap only starts (no drop yet).
    game.tap(P.DISPLAY_WIDTH // 2, P.DISPLAY_HEIGHT // 2)
    assert game.state == "play" and game.score == 0

    base_x, base_w, _ = game.floors[0]
    game.moving_x = base_x + 3  # within PERFECT_TOLERANCE
    game.tap(10, P.DISPLAY_HEIGHT // 2)
    assert game.score == 1 and game.floors[-1][:2] == (base_x, base_w), "perfect drop changed the floor"

    game.moving_x = base_x + 40
    game.tap(10, P.DISPLAY_HEIGHT // 2)
    assert game.score == 2 and abs(game.floors[-1][1] - (base_w - 40)) < 1e-6, game.floors[-1]
    assert game.debris, "cut-off part should fall"
    for _ in range(8):  # a few more, so the screenshot shows a tower
        top_x, top_w, _ = game.floors[-1]
        game.moving_x = top_x + random.choice((-1, 1)) * random.uniform(8, 18)
        game.tap(10, P.DISPLAY_HEIGHT // 2)
    now = run_frames(game, now, 0.4)
    game.draw(P.tft_surf)
    shot("03_stack_tower.png")
    assert game.state == "play"

    # Three perfect drops in a row grow the floor back.
    width_before = game.floors[-1][1]
    for _ in range(3):
        game.moving_x = game.floors[-1][0]
        game.tap(10, 400)
    assert game.floors[-1][1] > width_before, "perfect streak did not grow the floor"
    assert game.last_tick < game.grow_flash_until, "growing should be shown"
    game.draw(P.tft_surf)
    shot("03b_stack_grow.png")

    # Full miss -> game over, record set.
    top_x, top_w, _ = game.floors[-1]
    game.moving_x = top_x + top_w + 5
    score = game.score
    game.tap(10, P.DISPLAY_HEIGHT // 2)
    assert game.state == "over" and game.name_entry, "first score must ask for a name"

    # Taps right after game over do nothing (not even a key).
    now = run_frames(game, now, 0.6)
    game.draw(P.tft_surf)
    game.tap(*game.key_rects[0][0].center)
    assert game.name_text == "", "key hit within the game-over tap delay"
    now = run_frames(game, now, 0.5)
    game.draw(P.tft_surf)
    for rect, token in game.key_rects:
        assert 0 < rect.left and rect.right < P.DISPLAY_WIDTH, token
    type_name(game, "JUU", ok=False)
    press(game, "back")
    game.draw(P.tft_surf)
    shot("04a_stack_name.png")
    press(game, "ok")
    assert not game.name_entry and game.place == 0
    top = party_games.best("STAPEL-TURM")
    assert (top["name"], top["score"]) == ("JU", score), top
    game.draw(P.tft_surf)
    shot("04_stack_over.png")
    again = game.buttons["again"]
    for rect in game.buttons.values():
        assert P.DISPLAY_WIDTH > rect.right and rect.left > 0
    game.tap(*again.center)
    assert game.state == "ready" and game.score == 0 and len(game.floors) == 1

    # MENÜ from game over goes back to the menu.
    game.tap(1, 400)
    game.moving_x = P.DISPLAY_WIDTH * 2  # off the tower
    game.tap(1, 400)
    assert game.state == "over"
    now = run_frames(game, now, 1.0)
    game.draw(P.tft_surf)
    assert P.handle_tap(*game.buttons["menu"].move(0, P.GAME_TITLE_HEIGHT).center)
    assert P.GAMES_MENU_OPEN and P.ACTIVE_GAME is None
    P.draw_games_menu()
    shot("05_menu_with_record.png")
    P.close_games("test")
    print(f"STACK: perfect/cut/grow/miss/name ok, record {party_games.best('STAPEL-TURM')}", flush=True)


def test_highscores():
    name = "STAPEL-TURM"
    game = open_game(name)
    now = game.last_tick

    def finish(score, text):
        nonlocal now
        game.reset(now)
        game.tap(1, 400)
        game.score = score
        game.game_over("test")
        now = run_frames(game, now, 1.0)
        game.draw(P.tft_surf)
        if game.name_entry:
            type_name(game, text)
        return game.place

    for score, text in ((5, "A"), (7, "B"), (3, "C"), (9, "D"), (4, "E")):
        finish(score, text)
    scores = [e["score"] for e in party_games.top_list(name)]
    assert scores == sorted(scores, reverse=True) and len(scores) == 5, scores

    # Too low for the top 5: no keyboard, straight to the list.
    game.reset(now)
    game.tap(1, 400)
    game.score = scores[-1]  # a tie with the last place does not push it out
    game.game_over("test")
    assert not game.name_entry and game.place is None
    now = run_frames(game, now, 1.0)
    game.draw(P.tft_surf)
    assert "again" in game.buttons

    # Middle place, highlighted in the list.
    # List is now 13 (JU from test_stack), 9, 7, 5, 4 -> 8 lands on place 3.
    place = finish(8, "MITTE")
    assert place == 2 and party_games.top_list(name)[2]["name"] == "MITTE", party_games.top_list(name)
    game.draw(P.tft_surf)
    shot("09_leaderboard.png")

    # Persisted: a fresh load from disk sees the same list.
    in_memory = party_games.top_list(name)
    party_games.configure(party_games.LOG_DIR)
    assert party_games.top_list(name) == in_memory

    # Closed (x / idle) mid-entry: still saved, as ANONYM.
    game.reset(now)
    game.tap(1, 400)
    game.score = 99
    game.game_over("test")
    assert game.name_entry
    assert P.handle_tap(*P.GAME_TITLE_X.center) and not P.games_open()
    assert party_games.best(name)["name"] == "ANONYM" and party_games.best(name)["score"] == 99

    # Menu card shows the all-time record.
    P.open_games_menu()
    P.draw_games_menu()
    shot("10_menu_alltime.png")
    P.close_games("test")
    print(f"HIGHSCORES: top5/keyboard/skip/persist/close-saves ok: {party_games.top_list(name)}", flush=True)


def merz_win(seconds, burn=False):
    """Plays MERZ to a win in `seconds` (clock and hits faked) and opens the
    result panel, past its tap delay."""
    P.activate_merz_game()
    P.draw_merz_overlay()
    P.handle_merz_click(*P.MERZ_ACTION_RECTS["select_testicle"].center)
    assert P.MERZ_TIMER_STARTED_AT is None, "pill tap started the MERZ clock"
    P.handle_merz_click(P.DISPLAY_WIDTH // 2, P.DISPLAY_HEIGHT // 2)
    assert P.MERZ_TIMER_STARTED_AT is not None, "throw did not start the MERZ clock"
    P.MERZ_TIMER_STARTED_AT -= seconds
    P.MERZ_HITS = P.MERZ_WIN_HITS
    P.MERZ_BURN_SCORED = burn
    P.draw_merz_overlay()
    assert P.MERZ_EXPLODED and abs(P.MERZ_WIN_SECONDS - seconds) < 0.2, P.MERZ_WIN_SECONDS
    P.MERZ_EXPLODED_AT -= P.MERZ_WIN_TEXT_DELAY_SECONDS
    P.draw_merz_overlay()
    assert P.MERZ_RESULT is None, "result panel replaced the banner too early"
    if burn:
        shot("11a_merz_win_banner.png")
    P.MERZ_EXPLODED_AT -= P.MERZ_RESULT_DELAY_SECONDS
    P.draw_merz_overlay()
    result = P.MERZ_RESULT
    assert result is not None and result.state == "over"
    result.over_at -= party_games.GAME_OVER_TAP_DELAY_SECONDS
    P.draw_merz_overlay()
    return result


def test_merz_hud():
    P.activate_merz_game()
    P.draw_merz_overlay()
    P.handle_merz_click(P.DISPLAY_WIDTH // 2, P.DISPLAY_HEIGHT // 2)
    P.MERZ_TIMER_STARTED_AT -= 12.3
    P.MERZ_HITS = 23
    longest = max((t for t in P.MERZ_TAUNTS if "year" in t), key=lambda t: len(t["text"]))
    P.MERZ_TAUNT_TEXT, P.MERZ_TAUNT_META = longest["text"], f"{longest['year']}, {longest['source']}"
    P.MERZ_TAUNT_SHOWN_AT = P.time.time()
    P.MERZ_TAUNT_NEXT_AT = P.time.time() + 60
    P.MERZ_Y = P.DISPLAY_HEIGHT * P.MERZ_BOUNDS_TOP_FRACTION + P.MERZ_TOP_OFFSET
    P.MERZ_WANDER_TARGET_X, P.MERZ_WANDER_TARGET_Y = P.MERZ_X, P.MERZ_Y
    P.MERZ_NEXT_WANDER_AT = P.time.time() + 10
    P.draw_merz_overlay()
    P.MERZ_SCALE = P.MERZ_SCALE_MAX  # biggest sprite = least room above him
    P.draw_merz_overlay()
    shot("10b_merz_hud_long_quote.png")  # never covers him or the hits/timer row
    for taunt in P.MERZ_TAUNTS:
        lines = P._quiz_wrap_text(P.FONT_TINY, taunt["text"], int(P.DISPLAY_WIDTH * 0.62))
        bubble_h = len(lines) * P.FONT_TINY.get_height() + 16
        if "year" in taunt:
            bubble_h += P.FONT_SUPER_TINY.get_height() + 4
        assert P._merz_rect().top - 14 - bubble_h >= P.MERZ_HUD_BOTTOM + 6, f"bubble covers Merz or the HUD: {taunt['text'][:30]}"
    P.MERZ_TAUNT_TEXT, P.MERZ_TAUNT_META = "„Der Bundestag ist ja nun kein Zirkuszelt.“", "2025, maischberger"
    P.MERZ_Y = P.DISPLAY_HEIGHT * P.MERZ_BOUNDS_BOTTOM_FRACTION + P.MERZ_TOP_OFFSET
    P.MERZ_WANDER_TARGET_X, P.MERZ_WANDER_TARGET_Y = P.MERZ_X, P.MERZ_Y
    P.draw_merz_overlay()
    shot("10c_merz_hud_short_quote.png")
    hits_rect, time_rect = P._merz_hud_rects()
    assert 0 <= hits_rect.left and not time_rect.colliderect(P.MERZ_ACTION_RECTS["close"]), (hits_rect, time_rect)
    P.dismiss_merz_game("test")
    print("MERZ HUD: hits/timer row clear of the x", flush=True)


def merz_press(result, token):
    P.handle_merz_click(*next(r for r, t in result.key_rects if t == token).center)


def test_merz_highscores():
    name = party_games.MerzResult.NAME
    for seconds, text in ((40.0, "LANGSAM"), (25.0, "FIX"), (60.0, "OPA")):
        result = merz_win(seconds, burn=text == "LANGSAM")
        assert result.name_entry
        for token in text:
            merz_press(result, token)
        shot("11_merz_name_entry.png") if text == "FIX" else None
        merz_press(result, "ok")
        P.draw_merz_overlay()
    entries = party_games.top_list(name)
    assert [e["name"] for e in entries] == ["FIX", "LANGSAM", "OPA"], entries
    assert [bool(e.get("burn")) for e in entries] == [False, True, False], entries
    assert result.place == 2
    shot("12_merz_leaderboard.png")

    # NOCHMAL restarts MERZ itself.
    P.handle_merz_click(*result.buttons["again"].center)
    assert P.MERZ_VISIBLE and not P.MERZ_EXPLODED and P.MERZ_RESULT is None

    # Best time so far, tie with FIX keeps FIX first; MENÜ back to the menu.
    result = merz_win(25.0)
    merz_press(result, "J")
    merz_press(result, "ok")
    assert [e["name"] for e in party_games.top_list(name)][:2] == ["FIX", "J"]
    P.draw_merz_overlay()
    P.handle_merz_click(*result.buttons["menu"].center)
    assert not P.MERZ_VISIBLE and P.GAMES_MENU_OPEN
    P.draw_games_menu()
    shot("13_menu_merz_record.png")
    P.close_games("test")

    # Fill to 5, then a too-slow time skips the keyboard.
    for seconds in (70.0, 999.0):
        result = merz_win(seconds)
        if result.name_entry:
            merz_press(result, "ok")
    assert len(party_games.top_list(name)) == 5 and not result.name_entry and result.place is None

    # Closed (x) mid-entry: still saved, as ANONYM.
    result = merz_win(10.0)
    assert result.name_entry
    P.handle_merz_click(*P.MERZ_ACTION_RECTS["close"].center)
    assert not P.MERZ_VISIBLE
    assert party_games.best(name)["name"] == "ANONYM" and party_games.best(name)["score"] == 10.0
    print(f"MERZ HIGHSCORES: clock/time-sort/again/menu/close-saves ok: {party_games.top_list(name)}", flush=True)


def test_flappy():
    game = open_game("FLAPPY BVG")
    now = game.last_tick
    now = run_frames(game, now, 1.0)
    assert game.state == "ready", "bus must hover until the first tap"
    game.draw(P.tft_surf)
    shot("06_flappy_ready.png")

    # No more taps after the start: falls onto the street.
    game.tap(200, 400)
    assert game.puffs and game.last_tick < game.bubble_until, "flap should puff, start should talk"
    now = run_frames(game, now, 5.0)
    assert game.state == "over" and game.score == 0, (game.state, game.score)
    assert game.wheel is not None, "crash should lose a wheel"
    now = run_frames(game, now, 0.3)
    game.draw(P.tft_surf)
    shot("06b_flappy_bonk.png")
    now = run_frames(game, now, 1.5)
    assert abs(game.spin % 360 - 180) < 5, f"bus should end on its roof, spin {game.spin}"

    # Bot: tap whenever the bus sinks below the next gap's centre. If this
    # can't get through, the physics are too hard for humans too.
    now = run_frames(game, now, 1.0)
    game.draw(P.tft_surf)
    game.tap(*game.buttons["again"].center)
    game.tap(200, 400)
    random.seed(3)

    # Fake a pigeon right above the bus: its poop must splat on the bus.
    game.poops.append({"x": game.bus_x, "y": game.bus_y - 40, "vx": 0.0, "vy": 0.0})

    def bot(g):
        upcoming = [b for b in g.barriers if b["x"] + g.BARRIER_WIDTH > g.bus_x - g.BUS_W / 2]
        target = upcoming[0]["gap_y"] + 20 if upcoming else g.height * 0.45
        if g.bus_y > target and g.vy > -100:
            g.tap(200, 400)
        if g.score == 3 and not os.path.exists(os.path.join(OUT_DIR, "07_flappy_play.png")):
            g.draw(P.tft_surf)
            shot("07_flappy_play.png")

    now = run_frames(game, now, 60.0, on_frame=bot)
    assert game.splats, "poop above the bus did not hit it"
    print(f"FLAPPY: bot reached {game.score} Haltestellen ({game.state})", flush=True)
    assert game.score >= 15, f"bot only reached {game.score} - too hard?"

    # Crash it, game-over screen.
    game.bus_y = game.height
    now = run_frames(game, now, 1.5)
    assert game.state == "over"
    game.draw(P.tft_surf)
    shot("08_flappy_over.png")

    # x closes everything; tapping the top-left corner inside the game is a
    # flap, not an emergency-exit click.
    assert P.handle_tap(*P.GAME_TITLE_X.center)
    assert not P.games_open()
    print("FLAPPY: hover/fall/bot/close ok", flush=True)


def test_timeouts():
    open_game("FLAPPY BVG")
    P.GAMES_LAST_ACTIVITY_TS -= P.GAMES_IDLE_TIMEOUT_SECONDS + 1
    P.update_games_timeout()
    assert not P.games_open(), "idle timeout did not close the game"

    P.open_games_menu()
    P.DISPLAY_BLANK = True
    P.update_games_timeout()
    assert not P.games_open(), "display blank did not close the menu"
    P.DISPLAY_BLANK = False
    print("TIMEOUTS: idle + blank close ok", flush=True)


if __name__ == "__main__":
    test_menu()
    test_stack()
    test_flappy()
    test_highscores()
    test_merz_hud()
    test_merz_highscores()
    test_timeouts()
    print(f"ALL PASSED - screenshots in {OUT_DIR}", flush=True)
