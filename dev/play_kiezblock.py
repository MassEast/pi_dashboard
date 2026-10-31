#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Play KIEZBLOCK (games_kiezblock.py) on the laptop: a real 480x800 window with
the KiezOS title bar on top, mouse clicks = touchscreen taps. Doesn't import
PiDashboard.py (that starts schedulers/network). Highscores go to a temp dir,
never logs/. x in the title bar or Esc quits, MENÜ restarts.

.venv/bin/python dev/play_kiezblock.py [--fps 20]
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
from games_kiezblock import KiezblockGame, menu_icon  # noqa: E402

TITLE_H = 36  # = PiDashboard.GAME_TITLE_HEIGHT


def setup():
    """pygame + kiezos fonts/palette like PiDashboard.py; highscores in a temp dir."""
    pygame.init()
    screen = pygame.display.set_mode((K.W, K.H))
    pygame.display.set_caption("KiezOS 161 - kiezblock.exe")
    K.configure(os.path.join(REPO, "fonts") + "/", os.path.join(REPO, "icons") + "/",
                json.load(open(os.path.join(REPO, "themes", "kiezos.json")))["KIEZOS"])
    log_dir = tempfile.mkdtemp(prefix="kiezblock_scores_")
    party_games.configure(log_dir)
    return screen, log_dir


def new_game(now):
    fonts = os.path.join(REPO, "fonts")
    game = KiezblockGame(K.W, K.H - TITLE_H, os.path.join(fonts, "JetBrainsMono-Medium.ttf"),
                         os.path.join(fonts, "JetBrainsMono-Bold.ttf"))
    game.show_close = False  # the title bar's x closes it, like on the Pi
    game.reset(now)
    return game


def draw_title(screen):
    """K.game_title() with this game's icon (K.menu_icon doesn't know it yet)."""
    close = K.game_title(screen, "kiezblock.exe", "games")
    screen.blit(menu_icon(22), (8, 7))
    return close


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fps", type=int, default=20, help="the Pi runs games at ~20-30 FPS")
    args = parser.parse_args()
    screen, log_dir = setup()
    print(f"KIEZBLOCK: highscores in {log_dir}", flush=True)
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
        game.update(time.time())
        if game.state == "over" and game.over_at != last_over:  # a round can also end inside tap()
            last_over = game.over_at
            rounds += 1
            print(f"Round {rounds}: {game.score} m², best combo {game.best_combo}, "
                  f"{game.conversions} conversions, {game.t:.0f} s", flush=True)
        game.draw(game_surf)
        close = draw_title(screen)
        pygame.display.flip()
        clock.tick(args.fps)


if __name__ == "__main__":
    main()
