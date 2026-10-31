#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless checks of KIEZ-KURIER (kiezkurier.py), instantiated directly (the
main agent registers it in PiDashboard's Spiele menu):
- daily generation for 60 consecutive dates: fast, deterministic per date,
  different across dates, exactly one solution (independent brute-force
  re-check), clue count / solver effort inside the quality window;
- ready screen -> LOS starts the timer; drawing by tap + drag (also fast
  swipes skipping cells), undo by dragging back, cut back by tapping a route
  cell, reset button;
- every illegal move refused (Baustelle, visited, Kreisel straight,
  Fahrradstraße turn, Einbahn against the arrow, Späti too early, far cell);
- solving with the solver's route wins, rolls, stores the time with the day
  (lower is better, "Heute Platz"), today's best shows up;
- closed mid-route -> WEITER resumes route + time, NEU starts over;
- nothing tappable in the emergency-exit box (game x < 100, y < 144).
Simulated time; highscores in a temp dir. Screenshots: scratch/game_mockups/kiezkurier/.

SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_kiezkurier.py
"""

import datetime
import os
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import pygame  # noqa: E402

import kiezos as K  # noqa: E402
import kiezkurier as KK  # noqa: E402
import party_games  # noqa: E402
import PiDashboard as P  # noqa: E402

OUT = os.path.join(REPO, "scratch", "game_mockups", "kiezkurier")
os.makedirs(OUT, exist_ok=True)
party_games.configure(tempfile.mkdtemp(prefix="kiezkurier_scores_"))
K.ICON_MAKERS["kiezkurier"] = KK.menu_icon_surface
FRAME = 1 / 20
GH = P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT
GAME_SURF = P.tft_surf.subsurface((0, P.GAME_TITLE_HEIGHT, P.DISPLAY_WIDTH, GH))
DAY = datetime.date(2026, 11, 7)
KK.today = lambda: DAY


def new_game(now=1000.0):
    game = KK.KiezKurierGame(P.DISPLAY_WIDTH, GH, P.FONT_PATH + P.FONT_MEDIUM, P.FONT_PATH + P.FONT_BOLD)
    game.show_close = False
    game.reset(now)
    return game


def shot(game, name):
    game.draw(GAME_SURF)
    K.game_title(P.tft_surf, game._exe(), game.ICON)
    pygame.image.save(P.tft_surf, os.path.join(OUT, name))


def frames(game, n=1):
    for _ in range(n):
        game.update(game.last_tick + FRAME)
        game.draw(GAME_SURF)


def started(now=1000.0):
    game = new_game(now)
    KK._RESUME = None
    game.reset(now)
    game.tap(240, 600)
    assert game.state == "play", game.state
    frames(game)
    return game


def center(cell):
    return KK.KiezKurierGame.cell_center(cell)


def tap_cell(game, cell):
    game.tap(*center(cell))
    frames(game)


def drag_cells(game, cells):
    for cell in cells:
        game.drag(*center(cell))
        frames(game)


def brute_force_count(p, limit=2):
    """Independent plain DFS (no pruning, no bitboards) to re-check uniqueness."""
    count = [0]
    free = {(r, c) for r in range(KK.ROWS) for c in range(KK.COLS) if p.is_free(r, c)}

    def rec(path, seen):
        if count[0] >= limit:
            return
        head = path[-1]
        if head == p.end:
            if len(path) == len(free):
                count[0] += 1
            return
        din = KK.direction(path[-2], head) if len(path) > 1 else None
        for d, (dr, dc) in enumerate(KK.DIR_RC):
            nxt = (head[0] + dr, head[1] + dc)
            if nxt in free and nxt not in seen and p.exit_ok(head, din, d):
                seen.add(nxt)
                path.append(nxt)
                rec(path, seen)
                path.pop()
                seen.discard(nxt)

    rec([p.start], {p.start})
    return count[0]


def test_generation():
    times, sigs = [], set()
    d0 = datetime.date(2026, 11, 1)
    for i in range(60):
        day = d0 + datetime.timedelta(days=i)
        KK._DAILY.clear()
        t = time.perf_counter()
        p = KK.daily_puzzle(day)
        times.append(time.perf_counter() - t)
        routes, nodes, finished = KK.solve(p, limit=3, budget=10 ** 6)
        assert finished and len(routes) == 1, (day, len(routes))
        assert routes[0] == p.solution
        assert len(p.solution) == p.total and p.solution[0] == p.start and p.solution[-1] == p.end
        assert KK.MIN_CLUES <= len(p.clues) <= KK.MAX_CLUES, (day, len(p.clues))
        assert KK.MIN_NODES <= p.nodes <= KK.MAX_NODES, (day, p.nodes)
        assert 1 <= len(p.blocked) <= 4 * KK.MAX_CUT
        assert p.start not in p.clues and p.end not in p.clues
        if i < 12:  # the brute force is slow-ish, a dozen days is plenty
            assert brute_force_count(p) == 1, day
        KK._DAILY.clear()
        q = KK.daily_puzzle(day)  # same day -> same puzzle
        assert (q.blocked, q.start, q.end, q.clues) == (p.blocked, p.start, p.end, p.clues), day
        sigs.add((tuple(p.blocked), p.start, p.end, tuple(sorted(p.clues.items(), key=str))))
    assert len(sigs) == 60, "every day a different puzzle"
    times.sort()
    mean_ms, max_ms = 1000 * sum(times) / len(times), 1000 * times[-1]
    print(f"generation: 60 days, mean {mean_ms:.0f} ms, max {max_ms:.0f} ms (dev machine)", flush=True)
    assert mean_ms < 60 and max_ms < 250, (mean_ms, max_ms)
    KK._DAILY.clear()
    return mean_ms, max_ms


def test_ready_and_corner():
    KK._RESUME = None
    game = new_game()
    shot(game, "01_ready_rules.png")
    for x, y in ((5, 5), (50, 60), (99, 143), (10, 140)):  # emergency box: nothing happens
        game.tap(x, y)
        assert game.state == "ready"
    game.tap(240, 600)
    assert game.state == "play"
    frames(game)
    # nothing tappable on the play screen inside the box either
    for rect in game.play_buttons.values():
        assert not rect.colliderect(pygame.Rect(0, 0, 100, 144)), rect
    assert KK.GRID_Y >= 144
    path_before = list(game.path)
    for x, y in ((5, 5), (60, 100), (99, 143)):
        game.tap(x, y)
        frames(game)
        assert game.path == path_before and not game.help_open
    # help overlay can't be closed from the corner, anywhere else closes it
    game.tap(*game.play_buttons["help"].center)
    assert game.help_open
    shot(game, "05_help_overlay.png")
    game.tap(50, 50)
    assert game.help_open
    game.tap(240, 400)
    assert not game.help_open


def test_draw_undo_reset():
    game = started()
    p = game.puzzle
    sol = p.solution
    assert game.path == [p.start] and game.elapsed < 0.1
    tap_cell(game, sol[0])  # finger on the wheel
    assert game.dragging
    drag_cells(game, sol[1:6])
    assert game.path == sol[:6], game.path
    drag_cells(game, [sol[4], sol[3]])  # drag back = undo
    assert game.path == sol[:4]
    game.release()
    tap_cell(game, sol[1])  # tap a route cell = cut back to it
    assert game.path == sol[:2] and game.dragging
    game.release()
    # fast swipe: one motion event jumps over several cells of a straight run
    game.tap(*center(game.head))
    i = 2
    while i < len(sol) - 1 and KK.direction(sol[i - 1], sol[i]) == KK.direction(sol[i], sol[i + 1]):
        i += 1
    if i >= 3:
        game.drag(*center(sol[i]))
        assert game.path == sol[:i + 1], (game.path, sol[:i + 1])
    game.release()
    e0 = game.elapsed
    frames(game, 40)
    assert abs(game.elapsed - e0 - 2.0) < 0.01, (e0, game.elapsed)
    shot(game, "02_drawing.png")
    game.tap(*game.play_buttons["reset"].center)
    assert game.path == [p.start]
    assert game.elapsed > 1.9  # reset doesn't stop the clock


def wrong_exits(p, i):
    """Free cells next to solution[i], not yet on the route there, that its clue forbids leaving to."""
    sol = p.solution
    return [nxt for d, nxt in KK._neighbours(*sol[i]) if p.is_free(*nxt) and nxt not in sol[:i + 1]
            and not p.exit_ok(sol[i], KK.direction(sol[i - 1], sol[i]), d)]


def find_case(predicate):
    """(day, puzzle, index i into the solution) of the first day/cell matching predicate."""
    for k in range(60):
        day = DAY + datetime.timedelta(days=k)
        p = KK.daily_puzzle(day)
        for i in range(1, len(p.solution) - 1):
            if predicate(p, i):
                return day, i
    raise AssertionError("no case found")


def test_refusals():
    global DAY
    game = started()
    p = game.puzzle
    sol = p.solution
    # Baustelle / far / visited
    nb = [(sol[0][0] + dr, sol[0][1] + dc) for dr, dc in KK.DIR_RC]
    blocked = [c for c in nb if 0 <= c[0] < KK.ROWS and 0 <= c[1] < KK.COLS and not p.is_free(*c)]
    if blocked:
        tap_cell(game, blocked[0])
        assert game.path == [p.start] and game.refused[1] == "blocked"
        shot(game, "04_refused.png")
    far = next(c for c in sol if abs(c[0] - p.start[0]) + abs(c[1] - p.start[1]) > 2)
    tap_cell(game, far)
    assert game.path == [p.start] and game.refused[1] == "far" and not game.dragging
    tap_cell(game, sol[0])
    drag_cells(game, sol[1:4])
    assert game.why_not(sol[1]) == "visited"
    game.release()

    # Each clue kind: find a day where the route reaches a clue cell, then try leaving it wrongly.
    original = DAY
    for kind in (KK.TURN, KK.STRAIGHT, "arrow"):
        def pred(p, i, kind=kind):
            clue = p.clues.get(p.solution[i])
            return (clue is not None and (clue == kind or (kind == "arrow" and isinstance(clue, int)))
                    and wrong_exits(p, i))
        day, i = find_case(pred)
        DAY = day
        KK.today = lambda: DAY
        g = started()
        sol = g.puzzle.solution
        g.path = list(sol[:i + 1])
        wrong = wrong_exits(g.puzzle, i)
        assert wrong, (kind, day)
        g.tap(*center(sol[i]))
        g.drag(*center(wrong[0]))
        assert g.path == sol[:i + 1], kind
        assert g.refused[1] == kind, (g.refused, kind)
        g.release()
    DAY = original
    KK.today = lambda: DAY

    # Späti too early
    day, i = find_case(lambda p, i: KK.KiezKurierGame._adjacent(p.solution[i], p.end) and i < len(p.solution) - 2
                       and p.exit_ok(p.solution[i], KK.direction(p.solution[i - 1], p.solution[i]),
                                     KK.direction(p.solution[i], p.end)))
    DAY = day
    KK.today = lambda: DAY
    g = started()
    g.path = list(g.puzzle.solution[:i + 1])
    g.tap(*center(g.head))
    g.drag(*center(g.puzzle.end))
    assert g.refused[1] == "early" and g.puzzle.end not in g.path
    assert "noch" in g.message[0]
    DAY = original
    KK.today = lambda: DAY


def test_win_and_store():
    KK._RESUME = None
    game = started(2000.0)
    sol = game.puzzle.solution
    tap_cell(game, sol[0])
    for cell in sol[1:-8]:
        game.drag(*center(cell))
        frames(game, 5)
    shot(game, "03_almost.png")
    for cell in sol[-8:]:
        game.drag(*center(cell))
        frames(game, 5)
    game.release()
    assert game.won_at is not None and game.state == "play"
    t = game.score
    assert abs(t - (2 + 5 * (len(sol) - 2)) * FRAME) < 0.11, (t, len(sol))
    frames(game, int(KK.WIN_ROLL_SECONDS * 0.5 / FRAME))
    shot(game, "06_win_roll.png")
    frames(game, int((KK.WIN_ROLL_SECONDS * 0.5 + 0.3) / FRAME))
    shot(game, "07_geliefert.png")
    frames(game, int(KK.WIN_BANNER_SECONDS / FRAME) + 2)
    assert game.state == "over"
    entry = next(e for e in party_games.top_list(KK.KiezKurierGame.NAME) if e["id"] == game.entry_id)
    assert entry["day"] == DAY.isoformat() and entry["score"] == t
    assert "Heute Platz 1/1" in game.over_text, game.over_text
    assert KK._RESUME is None
    frames(game, 20)
    shot(game, "08_bestenliste.png")

    # a slower second round today ranks 2nd (lower is better); an old day's round doesn't count for today
    party_games.HIGHSCORES, _, _ = party_games.highscore_store.submit_result(
        party_games.LOG_DIR, KK.KiezKurierGame.NAME, 1.0, True, {"day": "2026-01-01"})
    game2 = started(3000.0)
    game2.path = list(sol[:-1])
    game2.update(3000.0 + 300.0)
    game2.tap(*center(game2.head))
    game2.drag(*center(sol[-1]))
    assert game2.won_at is not None
    frames(game2, int((KK.WIN_ROLL_SECONDS + KK.WIN_BANNER_SECONDS) / FRAME) + 2)
    assert game2.state == "over" and "Heute Platz 2/2" in game2.over_text, game2.over_text
    today = KK.today_entries(KK.KiezKurierGame.NAME, DAY)
    assert [e["score"] for e in today] == sorted(e["score"] for e in today) and len(today) == 2
    g3 = new_game(4000.0)
    shot(g3, "09_ready_with_today.png")


def test_resume():
    KK._RESUME = None
    game = started(5000.0)
    sol = game.puzzle.solution
    tap_cell(game, sol[0])
    drag_cells(game, sol[1:10])
    game.release()
    game.update(5000.0 + 30.0)
    # closed (idle timeout / x): a new game object 2 min later offers WEITER
    g2 = new_game(5000.0 + 150.0)
    assert g2.resume is not None
    shot(g2, "10_ready_resume.png")
    g2.tap(*g2.ready_buttons["resume"].center)
    assert g2.state == "play" and g2.path == sol[:10] and 29.9 < g2.elapsed < 31, g2.elapsed
    g2.update(g2.last_tick + 1.0)
    assert 30.9 < g2.elapsed < 32
    # NEU STARTEN
    g3 = new_game(g2.last_tick + 10)
    g3.draw(GAME_SURF)
    g3.tap(*g3.ready_buttons["new"].center)
    assert g3.path == [g3.puzzle.start] and g3.elapsed == 0.0
    # too old -> no resume offer
    g3.tap(*center(sol[0]))
    g3.drag(*center(sol[1]))
    g4 = new_game(g3.last_tick + KK.RESUME_SECONDS + 5)
    assert g4.resume is None
    # another day -> no resume
    global DAY
    g5 = started(9000.0)
    g5.tap(*center(sol[0]))
    g5.drag(*center(g5.puzzle.solution[1]))
    DAY = DAY + datetime.timedelta(days=1)
    KK.today = lambda: DAY
    assert new_game(9010.0).resume is None
    DAY = DAY - datetime.timedelta(days=1)
    KK.today = lambda: DAY
    KK._RESUME = None


def test_perf():
    game = started()
    sol = game.puzzle.solution
    game.path = list(sol[:-1])
    frames(game, 3)
    t = time.perf_counter()
    for _ in range(100):
        frames(game)
    ms = (time.perf_counter() - t) * 10
    print(f"frame with a full route: {ms:.2f} ms (dev machine)", flush=True)
    assert ms < 8, ms
    return ms


def test_icon():
    img = KK.menu_icon_surface(80)
    assert img.get_size() == (80, 80)
    pygame.image.save(pygame.transform.scale(img, (160, 160)), os.path.join(OUT, "11_menu_icon.png"))


def test_dashboard_menu_and_timeout():
    """Registered in PiDashboard: reachable from spiele.exe (folder or
    favourites), and the longer idle timeout: thinking 61 s doesn't close it."""
    P.DISPLAY_BLANK = False
    P.open_games_menu()
    P.draw_games_menu()
    if KK.KiezKurierGame.NAME not in [k for _, k in P.GAMES_MENU_RECTS]:
        P.handle_tap(*next(r for r, k in P.GAMES_MENU_RECTS if k == "__more__").center)
        P.draw_games_menu()
    assert P.handle_tap(*next(r for r, k in P.GAMES_MENU_RECTS if k == KK.KiezKurierGame.NAME).center)
    assert isinstance(P.ACTIVE_GAME, KK.KiezKurierGame)
    P.GAMES_LAST_ACTIVITY_TS = time.time() - 61
    P.update_games_timeout()
    assert P.ACTIVE_GAME is not None, "closed after 61 s of thinking"
    P.GAMES_LAST_ACTIVITY_TS = time.time() - KK.KiezKurierGame.IDLE_TIMEOUT_SECONDS - 1
    P.update_games_timeout()
    assert not P.games_open(), "own idle timeout not applied"
    print("DASHBOARD: in spiele.exe, idle timeout 180 s instead of 60 s", flush=True)


mean_ms, max_ms = test_generation()
test_ready_and_corner()
test_draw_undo_reset()
test_refusals()
test_win_and_store()
test_resume()
ms = test_perf()
test_icon()
test_dashboard_menu_and_timeout()
print(f"All KIEZ-KURIER tests passed - generation mean {mean_ms:.0f} ms / max {max_ms:.0f} ms per day, "
      f"frame {ms:.2f} ms - screenshots in {OUT}", flush=True)
P.quit_all()
