#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless checks of TIC-TAC-DADA (tictacdada.py) inside PiDashboard's Spiele
menu: setup (re-roll never picks the other's picture, X/O toggle), a won
round (gold line, Urteil with a win line, loser starts NOCHMAL), a draw
(draw winner, Einspruch), the special line in its configured round, every
dada surprise (holiday cell, Feld 10, melting, §4b swap, X close button),
"Andere Leute" / Menü, nothing tappable in the emergency-exit corner, and
MoaBeats profile pictures from dev/fake_moabeats_server.py (a broken one is
skipped). Simulated time. Screenshots: scratch/game_mockups/tictactoe/real/.

SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_tictacdada.py
"""

import io
import os
import sys
import tempfile
import threading

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame  # noqa: E402

import fake_moabeats_server as fake  # noqa: E402
import party_games  # noqa: E402
import PiDashboard as P  # noqa: E402
import tictacdada as T  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scratch", "game_mockups", "tictactoe", "real")
os.makedirs(OUT, exist_ok=True)
party_games.configure(tempfile.mkdtemp(prefix="ttt_scores_"))


def render():
    """draw_active_game() without its update(time.time()) (we run simulated time)."""
    game = P.ACTIVE_GAME
    game.draw(P.tft_surf.subsurface((0, P.GAME_TITLE_HEIGHT, P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT)))
    P.K.game_title(P.tft_surf, "tic-tac-dada.exe", game.ICON)


def shot(name):
    render()
    pygame.image.save(P.tft_surf, os.path.join(OUT, name))


def frame(game, seconds=0.05):
    game.update(game.last_tick + seconds)
    render()


def tap(game, key):
    game.tap(*game.rects[key].center)
    frame(game)


def open_game():
    P.open_games_menu()
    P.draw_games_menu()
    rect = next(r for r, key in P.GAMES_MENU_RECTS if key == T.TicTacDadaGame.NAME)
    assert P.handle_tap(*rect.center)
    game = P.ACTIVE_GAME
    assert isinstance(game, T.TicTacDadaGame) and game.state == "setup"
    frame(game)
    return game


def play(game, cells):
    for i in cells:
        tap(game, f"cell{i}")


def test_avatars():
    server = fake.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    img = pygame.Surface((40, 30))
    img.fill((200, 60, 120))
    buf = io.BytesIO()
    pygame.image.save(img, buf, "x.png")
    fake.STATE["avatar_png"] = buf.getvalue()
    T.load_avatars(f"http://127.0.0.1:{server.server_port}")
    names = [n for n, _ in T.AVATARS]
    assert names == ["Kim", "Sam"], names  # Robin has no picture, Alex's is broken
    assert all(s.get_size() == (16, 16) for _, s in T.AVATARS)
    server.shutdown()
    T.AVATARS = []  # the rest of the test uses the placeholders
    print("AVATARS: MoaBeats pictures pixelated, missing/broken skipped", flush=True)


def test_setup_and_win():
    P.images = P.image_factory(P.ICON_PATH)
    P.DISPLAY_BLANK = False
    game = open_game()
    shot("01_setup.png")
    for _ in range(20):
        tap(game, "roll1")
        assert game.players[0] != game.players[1]
    tap(game, "xo")
    assert game.classic and game.name(0) == "Spieler*in X"
    tap(game, "faces")
    assert not game.classic
    # emergency-exit corner (screen x<100, y<180 = game y<144): nothing to hit, in every state
    corner = pygame.Rect(0, 0, 100, 180 - P.GAME_TITLE_HEIGHT)
    assert not any(r.colliderect(corner) for r in game.rects.values()), game.rects
    tap(game, "go")
    assert game.state == "play" and game.round_no == 1
    game.egg = None
    frame(game)
    assert not any(r.colliderect(corner) for r in game.rects.values())
    shot("02_spiel.png")
    play(game, [0, 1, 4, 2])  # X: 0, 4 ; O: 1, 2
    tap(game, "cell8")  # X wins on the diagonal
    assert game.state == "win_anim" and game.winner == 0 and game.wins == [1, 0]
    frame(game, 0.35)
    shot("03_sieg_animation.png")
    frame(game, 0.5)
    assert game.state == "result" and game.line
    game.tap(*game.rects["again"].center)
    assert game.state == "result", "tap within the result delay"
    frame(game, 1.0)
    shot("04_urteil.png")
    line = game.line
    tap(game, "again")
    assert game.state == "play" and game.turn == 1, "loser starts"
    print(f"SETUP+WIN: roll/toggle/corner/win line/loser starts ok - '{line}'", flush=True)
    return game


def test_draw(game):
    game.egg = None
    play(game, [0, 1, 2, 4, 3, 5, 7, 6, 8])  # O starts: O0 X1 O2 X4 O3 X5 O7 X6 O8 -> no line
    assert game.state == "draw" and game.draw_winner, game.board
    frame(game, 1.0)
    shot("05_unentschieden.png")
    tap(game, "einspruch")
    assert game.einspruch in T.EINSPRUCH
    shot("05b_einspruch.png")
    tap(game, "again")
    assert game.state == "play"
    print("DRAW: draw winner + Einspruch ok", flush=True)


def test_special_round(game):
    T.SPECIAL_LINES = {"ROUNDS": [4, 4], "WIN": ["{winner}, Oma wäre stolz auf dich."], "PLAY": ["Oma freut sich."]}
    game.special_round = game.round_no
    game.egg = None
    first = game.turn
    play(game, [0, 3, 1, 4, 2])
    assert game.winner == first and game.line == f"{game.name(first)}, Oma wäre stolz auf dich.", game.line
    frame(game, 1.0)
    frame(game, 1.0)  # past the result tap delay
    shot("06_spezialspruch.png")
    tap(game, "again")
    game.egg = None
    play(game, [0, 3, 1, 4, 2])
    assert "Oma" not in game.line, "special line only once per session"
    T.SPECIAL_LINES = {}
    frame(game, 1.0)
    frame(game, 1.0)
    tap(game, "again")
    print("SPECIAL: configured round gets the special line, once", flush=True)


def test_eggs(game):
    # holiday cell: blocked for 2 moves
    game.new_round(0)
    game.egg, game.egg_at = "urlaub", 1
    tap(game, "cell0")
    cell = game.holiday[0]
    tap(game, f"cell{cell}")
    assert game.board[cell] is None and game.bubble, "holiday cell must refuse"
    shot("07_egg_urlaub.png")
    # Feld 10: costs the turn
    game.new_round(0)
    game.egg, game.egg_at = "feld10", 1
    tap(game, "cell4")
    turn = game.turn
    shot("08_egg_feld10.png")
    tap(game, "feld10")
    assert game.turn != turn and "feld10" not in game.rects
    # melting picture (cosmetic)
    game.new_round(0)
    game.egg, game.egg_at = "melt", 1
    tap(game, "cell4")
    assert game.melt_cell == 4
    frame(game, 2.5)
    shot("09_egg_schmelzen.png")
    play(game, [0, 8])
    assert game.board[4] == 0, "melting doesn't change the board"
    # §4b: all marks swap sides
    game.new_round(0)
    game.egg, game.egg_at = "swap", 3
    play(game, [0, 1, 4])
    assert game.dialog == "swap"
    shot("10_egg_regel_4b.png")
    # hit rects = the drawn buttons (were 36 px too high: only a 6 px strip of "Na gut" worked)
    drawn = P.K.msgbox(pygame.Surface((game.width, game.height)), "schirine.exe", "ok",
                       ["Regel §4b tritt in Kraft:", "", "Alle Steine tauschen", "die Seiten.", "Viel Glück!"], ["Na gut", "Einspruch"])
    assert (game.rects["ok"], game.rects["einspruch_swap"], game.rects["swap_x"]) == (drawn[0][0], drawn[1][0], drawn[2][0])
    tap(game, "einspruch_swap")
    assert game.board[0] == 1 and game.board[1] == 0 and game.board[4] == 1 and game.dialog is None
    game.new_round(0)  # the msgbox's x swaps too (no dead x)
    game.egg, game.egg_at = "swap", 3
    play(game, [0, 1, 4])
    tap(game, "swap_x")
    assert game.dialog is None and game.board[0] == 1
    # X close button (classic)
    game.classic = True
    game.new_round(0)
    game.egg, game.egg_at = "x_close", 1
    tap(game, "cell4")
    assert game.close_cell == 4
    tap(game, "cell4")
    assert game.dialog == "close"
    shot("11_egg_x_schliessen.png")
    tap(game, "auch_ja")
    assert game.board[4] == 0 and game.close_cell is None
    game.new_round(0)  # the dialog's own x: also "the X stays"
    game.egg, game.egg_at = "x_close", 1
    tap(game, "cell4")
    tap(game, "cell4")
    assert game.dialog == "close" and game.rects["close_x"].collidepoint(P.K.close_box(pygame.Rect(30, 178, game.width - 60, 230)).center)  # cell 4 is low: dialog on top
    tap(game, "close_x")
    assert game.dialog is None and game.board[4] == 0
    game.classic = False
    print("EGGS: urlaub/feld10/melt/§4b/x-close ok", flush=True)


class TextLog:
    """Records every K.t95 text rect while drawing (for overflow checks)."""

    def __enter__(self):
        self.items, self._orig = [], P.K.t95

        def t95(surf, s, size, pos, color=None, bold=True, anchor="topleft"):
            r = self._orig(surf, s, size, pos, color, bold, anchor)
            self.items.append((s, r))
            return r
        P.K.t95 = t95
        return self

    def __exit__(self, *exc):
        P.K.t95 = self._orig


def test_long_names(game):
    """MoaBeats names have no length limit: every win line, the draw dialog,
    Feld 10 and the status texts with 30-char names - nothing cut off,
    nothing outside its box, no text lost."""
    T.AVATARS = [("Prinzessin Lillifee von Moabit", T.placeholder_avatars()[0][1]),
                 ("Bartholomäus-Friedrich Wilhel", T.placeholder_avatars()[1][1])]
    game.reset(game.last_tick)
    game.players = [0, 1]
    corner = pygame.Rect(0, 0, 100, 180 - P.GAME_TITLE_HEIGHT)
    surf = pygame.Surface((game.width, game.height))
    note = pygame.Rect(16 + 96, 44 + 44, 448 - 98, 52)  # _draw_verdict: inner.x + 96, inner.y + 44
    for p in (0, 1):
        for raw in T.WIN_LINES:
            game.new_round(0)
            game.board = [p, p, p, 1 - p, 1 - p, None, None, None, None]
            game.winner, game.win_cells, game.state, game.result_at = p, (0, 1, 2), "result", 0.0
            game.line = raw.format(winner=game.name(p), loser=game.name(1 - p))
            with TextLog() as log:
                game.draw(surf)
            in_note = [s for s, r in log.items if r.colliderect(note)]
            assert all(note.contains(r) for s, r in log.items if r.colliderect(note)), game.line
            assert "".join(in_note).replace(" ", "") == game.line.replace(" ", ""), (game.line, in_note)
            assert all(surf.get_rect().contains(r) for s, r in log.items), game.line
            assert not any(r.colliderect(corner) for r in game.rects.values())
    title, size = T._verdict_title_fit(game.name(0), 448 - 96 - 8)
    assert T._wordart_width(title, size) <= 448 - 104 and size >= 19 and title.endswith(". GEWINNT!"), (title, size)
    shot("12_lange_namen_urteil.png")
    # draw dialog: up to 3 comment lines, all above the Menü button
    long_play = "Oma sagt: Jedes Spiel zählt, und heute zählt es doppelt. Danke fürs Spielen, ihr Lieben, wirklich."
    for dw in T.DRAW_WINNERS + [("DIE", "OMA", long_play, "heart")]:
        for einspruch in [None] + T.EINSPRUCH:
            game.new_round(0)
            game.state, game.result_at, game.draw_winner, game.einspruch = "draw", 0.0, dw, einspruch
            with TextLog() as log:
                game.draw(surf)
            want = game._comment_lines(einspruch or dw[2], game.width - 56 - 16 - 24)[1]
            comment = [r for s, r in log.items if s in want]
            assert len(comment) == len(want) <= 3 and comment[-1].bottom <= game.rects["menu"].top - 4, (dw, want)
            assert "".join(want).replace(" ", "") == (einspruch or dw[2]).replace(" ", "") or want[-1].endswith("..."), want
            assert not any(r.colliderect(corner) for r in game.rects.values())
    shot("13_lange_namen_unentschieden.png")
    # play status (normal, Feld 10 next to it, melting) and NOCHMAL label: inside their boxes
    for egg in (None, "feld10", "melt"):
        game.new_round(0)
        game.egg, game.egg_at = egg, 1
        game.wins, game.round_no = [12, 10], 123
        frame(game)
        tap(game, "cell4")
        with TextLog() as log:
            game.draw(surf)
        box = pygame.Rect(16, 610, 316 if egg == "feld10" else game.width - 32, 100)
        texts = [(s, r) for s, r in log.items if r.colliderect(box) and r.top < box.bottom - 8]
        assert texts and all(box.contains(r) for s, r in texts), (egg, texts)
        assert all(surf.get_rect().contains(r) for s, r in log.items), egg
        if egg == "feld10":
            shot("14_lange_namen_feld10.png")
    for raw in ("{}", "NOCHMAL  ({} fängt an)", "{} ist dran."):
        for size_set in ((20, 18, 16), (18, 17, 16, 15, 14)):
            text, size = T.fit_named(raw, game.name(1), 300, size_set)
            assert P.K.font(size).size(text)[0] <= 300 and size in size_set, (text, size)
    T.AVATARS = []
    game.reset(game.last_tick)
    game.new_round(0)
    frame(game)
    print("LONG NAMES: all win lines/draws/status texts fit, nothing lost", flush=True)


def test_menu(game):
    game.new_round(0)
    game.egg = None
    play(game, [0, 3, 1, 4, 2])
    frame(game, 1.0)
    frame(game, 1.0)
    tap(game, "others")
    assert game.state == "setup" and game.wins == [0, 0] and game.round_no == 0
    tap(game, "go")
    game.egg = None
    play(game, [0, 3, 1, 4, 2])
    frame(game, 1.0)
    frame(game, 1.0)
    assert P.handle_tap(*game.rects["menu"].move(0, P.GAME_TITLE_HEIGHT).center)
    assert P.GAMES_MENU_OPEN and P.ACTIVE_GAME is None
    P.draw_games_menu()
    pygame.image.save(P.tft_surf, os.path.join(OUT, "00_spiele_menu.png"))
    assert party_games.best(T.TicTacDadaGame.NAME) is None, "no Bestenliste for TIC-TAC-DADA"
    P.close_games("test")
    print("MENU: Andere Leute resets the session, Menü back to spiele.exe", flush=True)


test_avatars()
g = test_setup_and_win()
test_draw(g)
test_special_round(g)
test_eggs(g)
test_long_names(g)
test_menu(g)
print(f"All TIC-TAC-DADA tests passed - screenshots in {OUT}", flush=True)
P.quit_all()
