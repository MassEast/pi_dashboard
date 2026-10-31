#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless check of the PLAY menu and the party_games.py games:

- PLAY pill (GAMES.ENABLED, also covers MERZ) opens the "Spiele" menu, cards start MERZ / STAPEL-TURM /
  FLAPPY BVG, "Schließen" closes, emergency exit only off inside a game.
- STAPEL-TURM: perfect drop keeps the width, offset drop cuts it, a full
  miss ends the game, game-over taps are ignored for a moment, NOCHMAL/MENÜ.
- Highscores: every finished round is stored right away (JSON store in a
  temp dir), without a name; the Bestenliste shows all rounds, scrolls with
  ^ / v and opens at this round; "Name eintragen (optional)" opens the
  keyboard and adds the name; closing mid-entry keeps a typed name.
- FLAPPY BVG: no taps -> crashes into the street; a simple tapping bot gets
  through barriers (the physics are actually playable); x closes.
- MERZ: clock starts with the first throw (not a pill tap), the win opens
  the same Bestenliste (+ optional name), sorted by time (lower is better),
  NOCHMAL restarts MERZ, MENÜ goes back, closing mid-entry keeps the name;
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
    # Start -> Spiele: the favourites (game of the day first) + "Mehr Spiele...".
    P.GAMES_FEATURED = ["ENTEIGNEN!", "TIC-TAC-DADA", "KIEZ KAPERN", "PATRIAPUTT", "MERZ"]
    daily, featured, more = P.games_menu_split()
    order = [e[0] for e in [daily] + featured]
    assert sorted(order) == sorted(["ENTEIGNEN!", "TIC-TAC-DADA", "KIEZ KAPERN", "PATRIAPUTT", "merz"]), order
    more_keys = [e[0] for e in more]  # the rest, in registration order (other games get added over time)
    assert more_keys[:3] == ["STAPEL-TURM", "FLAPPY BVG", "KIEZBLOCK"], more
    import datetime
    picks = {P.games_menu_split(datetime.date(2026, 11, d))[0][0] for d in range(1, 6)}
    assert len(picks) == 5, "the game of the day rotates through all favourites"
    P.close_start_menu()
    P.draw_home()
    assert P.handle_tap(*P.START_BUTTON_RECT.center) and P.START_MENU_OPEN
    P.draw_home()
    assert P.handle_tap(*next(r for r, a in P.START_MENU_RECTS if a == "games_sub").center)
    P.draw_home()
    shot("00_start_spiele.png")
    sub = [a for _, a in P.START_MENU_RECTS if a.startswith("game:")]
    assert sub == [f"game:{k}" for k in order] + ["game:__more__"], sub
    for rect, action in P.START_MENU_RECTS:
        assert not rect.colliderect(exit_zone), f"{action} in the emergency-exit zone"
    assert P.handle_tap(*next(r for r, a in P.START_MENU_RECTS if a == "game:merz").center)
    assert P.MERZ_VISIBLE and not P.START_MENU_OPEN
    P.dismiss_merz_game("test")

    # spiele.exe (where a game's MENÜ button leads): game of the day, favourites, folder
    P.open_games_menu()
    assert P.emergency_exit_active(), "emergency exit must stay on in the menu"
    P.draw_home()
    P.draw_dashboard_overlays()
    shot("01_menu.png")
    keys = [key for _, key in P.GAMES_MENU_RECTS]
    assert keys == order + ["__more__"], keys
    for page in ("main", "more"):
        P.open_games_menu(page)
        P.draw_games_menu()
        for rect, key in P.GAMES_MENU_RECTS:
            assert not rect.colliderect(exit_zone), f"menu card {key} in the emergency-exit zone"
            assert not rect.colliderect(P.GAMES_MENU_CLOSE_RECT), f"menu card {key} overlaps Schließen"
            assert not (P.GAMES_MENU_BACK_RECT and rect.colliderect(P.GAMES_MENU_BACK_RECT)), f"{key} overlaps Zurück"
            assert 0 <= rect.left and rect.right <= P.DISPLAY_WIDTH
    # folder page: the rest + < Zurück
    P.open_games_menu()
    P.draw_games_menu()
    assert P.handle_tap(*P.GAMES_MENU_RECTS[-1][0].center) and P.GAMES_MENU_PAGE == "more"
    P.draw_home()
    P.draw_dashboard_overlays()
    shot("01b_menu_mehr.png")
    assert [key for _, key in P.GAMES_MENU_RECTS] == more_keys
    assert P.handle_tap(*P.GAMES_MENU_BACK_RECT.center) and P.GAMES_MENU_PAGE == "main"
    P.draw_games_menu()
    # Names fit the card (text starts 112 px in); record lines are cut with "...".
    for game_cls in list(party_games.GAMES) + [party_games.MerzResult]:
        card = P.GAMES_MENU_RECTS[0][0]
        assert 112 + P.K.font(22).size(game_cls.NAME)[0] < card.width - 8, f"{game_cls.NAME} name too long"

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


def add_name(game, text, ok=True):
    """Game-over panel: "Name eintragen (optional)", type text (+ OK)."""
    game.draw(P.tft_surf)
    game.tap(*game.buttons["name"].center)
    assert game.name_entry
    game.draw(P.tft_surf)
    type_name(game, text, ok)
    game.draw(P.tft_surf)


def type_name(game, text, ok=True):
    for token in text:
        press(game, token)
    if ok:
        press(game, "ok")


def open_game(name):
    P.open_games_menu()
    P.draw_games_menu()
    if name not in [key for _, key in P.GAMES_MENU_RECTS]:  # not a favourite: in the folder
        P.handle_tap(*next(r for r, key in P.GAMES_MENU_RECTS if key == "__more__").center)
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
    assert game.state == "over" and not game.name_entry and game.place == 0, "round must be stored, no forced keyboard"
    assert party_games.best("STAPEL-TURM")["name"] is None, "stored without a name"

    # Taps right after game over do nothing (not even the name button).
    now = run_frames(game, now, 0.6)
    game.draw(P.tft_surf)
    game.tap(*game.buttons["name"].center)
    assert not game.name_entry, "name button hit within the game-over tap delay"
    now = run_frames(game, now, 0.5)
    add_name(game, "JUU", ok=False)
    for rect, token in game.key_rects:
        assert 0 < rect.left and rect.right < P.DISPLAY_WIDTH, token
    press(game, "back")
    game.draw(P.tft_surf)
    shot("04a_stack_name.png")
    press(game, "ok")
    assert not game.name_entry and game.place == 0 and game.named
    top = party_games.best("STAPEL-TURM")
    assert (top["name"], top["score"]) == ("JU", score), top
    game.draw(P.tft_surf)
    assert "name" not in game.buttons, "name already added"
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
    before = len(party_games.top_list(name))

    def finish(score, text=None):
        nonlocal now
        game.reset(now)
        game.tap(1, 400)
        game.score = score
        game.game_over("test")
        now = run_frames(game, now, 1.0)
        game.draw(P.tft_surf)
        if text:
            add_name(game, text)
        return game.place

    for score, text in ((5, "A"), (7, None), (3, "C"), (9, None), (4, "E"), (0, None), (5, "A")):
        finish(score, text)
    entries = party_games.top_list(name)
    scores = [e["score"] for e in entries]
    assert len(entries) == before + 7, "every round is kept, also 0 and repeats"
    assert scores == sorted(scores, reverse=True), scores
    assert [e["name"] for e in entries].count("A") == 2, "same person twice = twice in the list"
    assert sum(1 for e in entries if e["name"] is None) >= 3 and all(e["ts_iso"] and e["id"] for e in entries)

    # Tie: the older round keeps its place, the new one goes after it.
    place = finish(5)
    assert entries_names(name)[place - 2:place] == ["A", "A"], entries_names(name)

    # Many rounds: the list scrolls, opens at this round, ^ / v move it.
    for score in range(10, 40):
        finish(score)
    place = finish(20, "MITTE")
    assert party_games.top_list(name)[place]["name"] == "MITTE"
    assert game.list_top <= place < game.list_top + game.list_rows, "this round not visible"
    shot("09_leaderboard.png")
    top_before = game.list_top
    game.tap(*game.buttons["down"].center)
    assert game.list_top > top_before
    game.tap(*game.buttons["up"].center)
    game.tap(*game.buttons["up"].center)
    assert game.list_top < top_before
    game.draw(P.tft_surf)
    shot("09b_leaderboard_scrolled.png")

    # Persisted: a fresh load from disk sees the same list.
    in_memory = party_games.top_list(name)
    party_games.configure(party_games.LOG_DIR)
    assert party_games.top_list(name) == in_memory

    # Closed (x / idle) mid-entry: the typed name is kept; untyped stays anonym.
    finish(99)
    add_name(game, "ZU", ok=False)
    assert P.handle_tap(*P.GAME_TITLE_X.center) and not P.games_open()
    assert (party_games.best(name)["name"], party_games.best(name)["score"]) == ("ZU", 99)
    game = open_game(name)
    finish(100)
    assert P.handle_tap(*P.GAME_TITLE_X.center) and not P.games_open()
    assert party_games.best(name)["name"] is None and party_games.best(name)["score"] == 100

    # Menu card shows the all-time record.
    P.open_games_menu()
    P.draw_games_menu()
    shot("10_menu_alltime.png")
    P.close_games("test")
    print(f"HIGHSCORES: all {len(party_games.top_list(name))} rounds kept/optional name/scroll/persist/close ok", flush=True)


def test_v1_store():
    """A v1 file (the Pi's: top 5 with name/score/ts_iso, no id) still loads,
    keeps its entries and takes new rounds + names."""
    import json
    import highscore_store
    log_dir = tempfile.mkdtemp(prefix="v1_scores_")
    old = {"name": "ALT", "score": 12, "ts_iso": "2026-10-20T20:00:00+02:00"}
    with open(os.path.join(log_dir, highscore_store.STORE_FILE), "w") as f:
        json.dump({"version": 1, "games": {"STAPEL-TURM": [old]}}, f)
    games, place, entry_id = highscore_store.submit_result(log_dir, "STAPEL-TURM", 20)
    assert place == 0 and games["STAPEL-TURM"][1] == old
    games = highscore_store.set_name(log_dir, "STAPEL-TURM", entry_id, "NEU")
    assert [e["name"] for e in games["STAPEL-TURM"]] == ["NEU", "ALT"]
    games, place, _ = highscore_store.submit_result(log_dir, "STAPEL-TURM", 1)
    assert place == 2 and len(games["STAPEL-TURM"]) == 3
    print("V1 STORE: old top-5 entries kept, new rounds + names work", flush=True)


def test_over_dialog_all_games():
    """The shared game-over dialog for every registered game (+ MERZ):
    500 rounds, scores of every magnitude, max-length names with umlauts,
    v1 entries without id - buttons on screen, not overlapping, none in the
    emergency-exit corner; scrolling stops at both ends; the cached dialog
    is redrawn when it changes; the keyboard caps names and has umlauts."""
    import json
    import highscore_store
    log_dir = tempfile.mkdtemp(prefix="over_all_")
    fonts = (P.FONT_PATH + P.FONT_MEDIUM, P.FONT_PATH + P.FONT_BOLD)
    names = ["ÄÖÜ ÄÖÜ ÄÖ", "WWWWWWWWWW", None, "Ö"]
    classes = [c for c in party_games.GAMES if not getattr(c, "MENU_LINE", None)] + [party_games.MerzResult]
    assert len(classes) >= 3
    for cls in classes:
        merz = cls is party_games.MerzResult
        entries = [{"name": names[i % 4], "score": [0, 7, 12345, 19930000][i % 4] + (i * 0.37 if merz else 0),
                    "ts_iso": "2026-10-20T20:00:00+02:00", **({"id": f"x{i}"} if i % 2 else {})} for i in range(500)]
        entries.sort(key=lambda e: e["score"], reverse=not cls.LOWER_IS_BETTER)
        with open(os.path.join(log_dir, highscore_store.STORE_FILE), "w") as f:
            json.dump({"version": 2, "games": {cls.NAME: entries}}, f)
        party_games.configure(log_dir)
        if merz:
            game = cls(P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT, *fonts, 12345.67, 1000.0, burn=True)
            exit_zone = pygame.Rect(0, 0, P.EMERGENCY_EXIT_MAX_X, P.EMERGENCY_EXIT_MAX_Y)
        else:
            game = cls(P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT, *fonts)
            game.show_close = False
            game.reset(1000.0)
            game.score = 12345
            game.game_over("Verkehrsplanung von 1965 schlägt zurück. Und zwar richtig, mit Anlauf und allem.")
            game.bilanz = False  # KIEZ KAPERN shows its own Bilanz screen first
            exit_zone = pygame.Rect(0, 0, P.EMERGENCY_EXIT_MAX_X, P.EMERGENCY_EXIT_MAX_Y - P.GAME_TITLE_HEIGHT)
        surf = pygame.Surface((game.width, game.height))
        game._draw_over(surf)
        before = surf.copy()
        game.last_tick += party_games.GAME_OVER_TAP_DELAY_SECONDS + 0.01
        game._draw_over(surf)
        assert pygame.image.tobytes(surf, "RGB") != pygame.image.tobytes(before, "RGB"), f"{cls.NAME}: cache kept the disabled buttons"
        screen = surf.get_rect()
        for key, rect in game.buttons.items():
            assert screen.contains(rect), (cls.NAME, key, rect)
            assert not rect.colliderect(exit_zone), (cls.NAME, key)
            for other, rect2 in game.buttons.items():
                assert key == other or not rect.colliderect(rect2), (cls.NAME, key, other)
        assert {"again", "menu", "name", "up", "down"} <= set(game.buttons), (cls.NAME, game.buttons)
        assert game.list_top <= game.place < game.list_top + game.list_rows, f"{cls.NAME}: this round not visible"
        # scroll to both ends and past them
        for _ in range(60):
            game.tap(*game.buttons["up"].center)
            game._draw_over(surf)
        assert game.list_top == 0, (cls.NAME, game.list_top, game.buttons.get("up"), game.last_tick - game.over_at)
        top_pixels = pygame.image.tobytes(surf, "RGB")
        for _ in range(60):
            game.tap(*game.buttons["down"].center)
            game._draw_over(surf)
        assert game.list_top == game.list_max_top == 501 - game.list_rows, (cls.NAME, game.list_top)
        assert pygame.image.tobytes(surf, "RGB") != top_pixels, f"{cls.NAME}: cached dialog not redrawn after scrolling"
        shot(f"14_over_{cls.NAME.replace(' ', '_')}.png") if merz else None
        # keyboard: umlauts, max NAME_MAX_CHARS, keys clear of the exit corner
        game.tap(*game.buttons["name"].center)
        game._draw_over(surf)
        assert game.name_entry and {"Ä", "Ö", "Ü"} <= {t for _, t in game.key_rects}
        assert not any(r.colliderect(exit_zone) for r, _ in game.key_rects)
        assert all(screen.contains(r) for r, _ in game.key_rects)
        type_name(game, "ÖZLEMWWWWWWWW", ok=False)
        assert game.name_text == "ÖZLEMWWWWW" and len(game.name_text) == party_games.NAME_MAX_CHARS
        game._draw_over(surf)
        press(game, "ok")
        assert party_games.top_list(cls.NAME)[game.place]["name"] == "ÖZLEMWWWWW"
    # name-entry line: the unit once ("7.0 s", not "7.0 s Sekunden"), the label when there is no unit
    log = []
    orig = P.K.t95
    P.K.t95 = lambda surf, s, *a, **kw: log.append(s) or orig(surf, s, *a, **kw)
    try:
        for cls, want in ((party_games.MerzResult, "mit 12345.7 s"), (party_games.StackGame, "mit 12345 Stockwerke")):
            if cls is party_games.MerzResult:
                game = cls(P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT, *fonts, 12345.67, 1000.0)
            else:
                game = cls(P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT, *fonts)
                game.reset(1000.0)
                game.score = 12345
                game.game_over("x")
            game.name_entry = True
            log.clear()
            game._draw_over(pygame.Surface((game.width, game.height)))
            line = next(s for s in log if s.startswith("Platz "))
            assert line.endswith(want), line
    finally:
        P.K.t95 = orig
    with open(os.path.join(log_dir, highscore_store.STORE_FILE)) as f:
        assert f.read().count("\n") == 0, "store written compact (C json encoder)"
    party_games.configure(os.path.join(OUT_DIR, "logs"))
    print(f"OVER DIALOG: {len(classes)} games x 500 rounds - buttons/scroll/cache/keyboard/umlauts ok", flush=True)


def test_outlined_and_barrier_cache():
    """The cached outlined text sits exactly where the plain text did; the
    cached FLAPPY barrier is the striped one."""
    game = party_games.StackGame(P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT,
                                 P.FONT_PATH + P.FONT_MEDIUM, P.FONT_PATH + P.FONT_BOLD)
    surf = pygame.Surface((game.width, game.height))
    for pos in ({"midtop": (240, 60)}, {"topleft": (12, 14)}, {"center": (100, 300)}):
        rect = game._draw_outlined(surf, "1234", 64, (255, 255, 255), **pos)
        assert rect == game.fonts.get(64, True).render("1234", True, (0, 0, 0)).get_rect(**pos), (pos, rect)
    body = party_games.FlappyGame._barrier_body(74, 300)
    assert body.get_size() == (74, 300) and body.get_at((37, 150))[:3] in ((255, 255, 255), (220, 30, 30))
    assert party_games.FlappyGame._barrier_body(74, 300) is body, "barrier not cached"
    print("CACHES: outlined text position, barrier body ok", flush=True)


def entries_names(name):
    return [e["name"] for e in party_games.top_list(name)]


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
    for seconds, text in ((40.0, "LANGSAM"), (25.0, "FIX"), (60.0, None)):
        result = merz_win(seconds, burn=text == "LANGSAM")
        assert not result.name_entry and result.entry_id
        P.draw_merz_overlay()
        if text:
            P.handle_merz_click(*result.buttons["name"].center)
            assert result.name_entry
            P.draw_merz_overlay()
            for token in text:
                merz_press(result, token)
            shot("11_merz_name_entry.png") if text == "FIX" else None
            merz_press(result, "ok")
        P.draw_merz_overlay()
    entries = party_games.top_list(name)
    assert [e["name"] for e in entries] == ["FIX", "LANGSAM", None], entries
    assert [bool(e.get("burn")) for e in entries] == [False, True, False], entries
    assert result.place == 2
    shot("12_merz_leaderboard.png")

    # NOCHMAL restarts MERZ itself.
    P.handle_merz_click(*result.buttons["again"].center)
    assert P.MERZ_VISIBLE and not P.MERZ_EXPLODED and P.MERZ_RESULT is None

    # Same time as FIX keeps FIX first; MENÜ back to the menu.
    result = merz_win(25.0)
    assert [e["name"] for e in party_games.top_list(name)][:2] == ["FIX", None]
    P.draw_merz_overlay()
    P.handle_merz_click(*result.buttons["menu"].center)
    assert not P.MERZ_VISIBLE and P.GAMES_MENU_OPEN
    P.draw_games_menu()
    shot("13_menu_merz_record.png")
    P.close_games("test")

    # Slow times are kept too.
    for seconds in (70.0, 999.0):
        merz_win(seconds)
    assert len(party_games.top_list(name)) == 6 and party_games.top_list(name)[-1]["score"] == 999.0

    # Closed (x) mid-entry: the typed name is kept.
    result = merz_win(10.0)
    P.draw_merz_overlay()
    P.handle_merz_click(*result.buttons["name"].center)
    P.draw_merz_overlay()
    merz_press(result, "J")
    P.handle_merz_click(*P.MERZ_ACTION_RECTS["close"].center)
    assert not P.MERZ_VISIBLE
    assert (party_games.best(name)["name"], party_games.best(name)["score"]) == ("J", 10.0)
    print(f"MERZ HIGHSCORES: all rounds kept/time-sort/again/menu/optional name ok", flush=True)


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
    test_v1_store()
    test_over_dialog_all_games()
    test_outlined_and_barrier_cache()
    test_merz_hud()
    test_merz_highscores()
    test_timeouts()
    print(f"ALL PASSED - screenshots in {OUT_DIR}", flush=True)
