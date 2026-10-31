#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Play KIEZ KAPERN (kiezkapern.py) on the laptop: a real 480x800 window with the
KiezOS title bar on top, mouse button down = touchscreen tap (dragging with the
button held = drag(), used by paint.exe). Doesn't import PiDashboard.py (that
starts schedulers/network). Highscores go to a temp dir, never logs/. x in the
title bar or Esc quits, MENÜ starts a fresh round.

.venv/bin/python dev/play_kiezkapern.py [--fps 20]
"""

import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import pygame  # noqa: E402

import kiezos as K  # noqa: E402
import party_games  # noqa: E402
import kiezkapern  # noqa: E402

TITLE_H = 36  # = PiDashboard.GAME_TITLE_HEIGHT


def setup():
    """pygame + kiezos fonts/palette like PiDashboard.py; highscores in a temp dir."""
    pygame.init()
    screen = pygame.display.set_mode((K.W, K.H))
    pygame.display.set_caption("KiezOS 161 - kiezkapern.exe")
    K.configure(os.path.join(REPO, "fonts") + "/", os.path.join(REPO, "icons") + "/",
                json.load(open(os.path.join(REPO, "themes", "kiezos.json")))["KIEZOS"])
    K.ICON_MAKERS["kiezkapern"] = kiezkapern.menu_icon  # PiDashboard.py registers it the same way
    log_dir = tempfile.mkdtemp(prefix="kiezkapern_scores_")
    party_games.configure(log_dir)
    return screen, log_dir


def new_game(now):
    fonts = os.path.join(REPO, "fonts")
    game = kiezkapern.KiezKapernGame(K.W, K.H - TITLE_H, os.path.join(fonts, "JetBrainsMono-Medium.ttf"),
                                     os.path.join(fonts, "JetBrainsMono-Bold.ttf"))
    game.show_close = False  # the title bar's x closes it, like on the Pi
    game.reset(now)
    return game


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fps", type=int, default=20, help="the Pi runs games at ~20 FPS")
    args = parser.parse_args()
    screen, log_dir = setup()
    print(f"KIEZ KAPERN: highscores in {log_dir}", flush=True)
    clock = pygame.time.Clock()
    game = new_game(time.time())
    game_surf = screen.subsurface((0, TITLE_H, K.W, K.H - TITLE_H))
    close = pygame.Rect(K.W - 44, 5, 38, 26).inflate(10, 10)
    rounds = 0
    last_over = None
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                print(f"Bye. {rounds} rounds, Bestenliste: {party_games.top_list(game.NAME)[:5]}", flush=True)
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                x, y = event.pos
                if close.collidepoint((x, y)):
                    print(f"Bye. {rounds} rounds.", flush=True)
                    return
                if y < TITLE_H:
                    continue
                if game.tap(x, y - TITLE_H) == "menu":
                    game = new_game(time.time())
            elif event.type == pygame.MOUSEMOTION and event.buttons[0]:
                game.drag(event.pos[0], event.pos[1] - TITLE_H)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                game.release()
        game.update(time.time())
        if game.state == "over" and game.over_at != last_over:
            last_over = game.over_at
            rounds += 1
            c = game.counts
            print(f"Round {rounds}: {game.over_text} Kiezkasse {kiezkapern.fmt_eur(game.score)}, "
                  f"Mietspiegel max {game.max_level}/5, Räder {c['rad']}, Suppen {c['suppe']}, Kräne {c['kran']}, "
                  f"Wände {c['malen']}, Pfand {c['pfand']}, Hai abgehängt {c['hai']}, erwischt {c['erwischt']}", flush=True)
        game.draw(game_surf)
        close = K.game_title(screen, "kiezkapern.exe", game.ICON)
        pygame.display.flip()
        clock.tick(args.fps)


if __name__ == "__main__":
    main()
