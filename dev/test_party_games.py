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
    P.tft_surf.fill(P.BLACK)
    P.draw_dashboard_overlays()
    assert P.PLAY_BUTTON_RECT is not None
    assert P.handle_tap(*P.PLAY_BUTTON_RECT.center)
    assert P.GAMES_MENU_OPEN
    assert P.emergency_exit_active(), "emergency exit must stay on in the menu"
    P.draw_dashboard_overlays()
    shot("01_menu.png")
    keys = [key for _, key in P.GAMES_MENU_RECTS]
    assert keys == ["merz", "STAPEL-TURM", "FLAPPY BVG"], keys
    exit_zone = pygame.Rect(0, 0, P.EMERGENCY_EXIT_MAX_X, P.EMERGENCY_EXIT_MAX_Y)
    for rect, key in P.GAMES_MENU_RECTS:
        assert not rect.colliderect(exit_zone), f"menu card {key} in the emergency-exit zone"
        assert not rect.colliderect(P.GAMES_MENU_CLOSE_RECT), f"menu card {key} overlaps Schließen"
        assert 0 <= rect.left and rect.right <= P.DISPLAY_WIDTH
    # Descriptions must end before the chevron (it sits ~40 px from the right).
    for key, name, description in P._games_menu_entries():
        text_right = P.GAMES_MENU_RECTS[0][0].left + 18 + P.CHORE_ITEM_FONT_SMALL.size(description)[0]
        assert text_right < P.GAMES_MENU_RECTS[0][0].right - 45, f"{key} description runs into the chevron"
        assert P.CHORE_NAME_FONTS[0].size(name)[0] < P.GAMES_MENU_RECTS[0][0].width - 80, f"{key} name too long"
    assert P.PLAY_BUTTON_RECT is None, "PLAY pill drawn over its own menu"

    # Taps on empty menu space are swallowed, not passed to the dashboard.
    assert P.handle_tap(P.DISPLAY_WIDTH // 2, P.GAMES_MENU_CLOSE_RECT.top - 4)
    assert P.GAMES_MENU_OPEN

    # MERZ card: closes the menu, opens MERZ.
    merz_rect = P.GAMES_MENU_RECTS[0][0]
    assert P.handle_tap(*merz_rect.center)
    assert P.MERZ_VISIBLE and not P.games_open()
    P.dismiss_merz_game("test")

    # Schließen.
    P.open_games_menu()
    P.draw_games_menu()
    assert P.handle_tap(*P.GAMES_MENU_CLOSE_RECT.center)
    assert not P.games_open()

    # GAMES disabled: no PLAY pill (MERZ included, one flag for all games).
    P.GAMES_ENABLED = False
    P.draw_play_button()
    assert P.PLAY_BUTTON_RECT is None
    P.GAMES_ENABLED = True
    print("MENU: PLAY -> menu -> MERZ/close ok, config gating ok", flush=True)


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
    assert P.handle_tap(*game.buttons["menu"].center)
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
    assert P.handle_tap(*game.close_rect.center) and not P.games_open()
    assert party_games.best(name)["name"] == "ANONYM" and party_games.best(name)["score"] == 99

    # Menu card shows the all-time record.
    P.open_games_menu()
    P.draw_games_menu()
    shot("10_menu_alltime.png")
    P.close_games("test")
    print(f"HIGHSCORES: top5/keyboard/skip/persist/close-saves ok: {party_games.top_list(name)}", flush=True)


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
    assert P.handle_tap(*game.close_rect.center)
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
    test_timeouts()
    print(f"ALL PASSED - screenshots in {OUT_DIR}", flush=True)
