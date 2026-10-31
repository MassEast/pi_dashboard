#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Play LASTENRAVE SIMULATOR (lastenrave.py) on the laptop: a real 480x800
window with the KiezOS title bar on top. Mouse = touchscreen: click = tap
(drops the piece), dragging with the button held moves the crane, DREHEN
turns the piece. Doesn't import PiDashboard.py (that starts schedulers /
network). Highscores go to a temp dir, never logs/. x in the title bar or Esc
quits, MENÜ restarts.

.venv/bin/python dev/play_lastenrave.py [--fps 20]
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
from lastenrave import LastenraveGame, menu_icon_surface  # noqa: E402

TITLE_H = 36  # = PiDashboard.GAME_TITLE_HEIGHT


def new_game(now):
    fonts = os.path.join(REPO, "fonts")
    game = LastenraveGame(K.W, K.H - TITLE_H, os.path.join(fonts, "JetBrainsMono-Medium.ttf"),
                          os.path.join(fonts, "JetBrainsMono-Bold.ttf"))
    game.show_close = False  # the title bar's x closes it, like on the Pi
    game.reset(now)
    return game


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fps", type=int, default=20, help="the Pi runs games at ~20 FPS")
    args = parser.parse_args()
    pygame.init()
    screen = pygame.display.set_mode((K.W, K.H))
    pygame.display.set_caption("KiezOS 161 - lastenrave.exe")
    K.configure(os.path.join(REPO, "fonts") + "/", os.path.join(REPO, "icons") + "/",
                json.load(open(os.path.join(REPO, "themes", "kiezos.json")))["KIEZOS"])
    K.ICON_MAKERS["lastenrave"] = menu_icon_surface  # what PiDashboard.py does
    log_dir = tempfile.mkdtemp(prefix="lastenrave_scores_")
    party_games.configure(log_dir)
    print(f"LASTENRAVE: highscores in {log_dir}", flush=True)
    clock = pygame.time.Clock()
    game = new_game(time.time())
    game_surf = screen.subsurface((0, TITLE_H, K.W, K.H - TITLE_H))
    close = pygame.Rect(K.W - 44, 5, 38, 26).inflate(10, 10)
    rounds, last_over, frames, slow = 0, None, 0, 0
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
                if y >= TITLE_H and game.tap(x, y - TITLE_H) == "menu":
                    game = new_game(time.time())
            elif event.type == pygame.MOUSEMOTION and event.buttons[0]:
                game.drag(event.pos[0], event.pos[1] - TITLE_H)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                game.release()
        t0 = time.perf_counter()
        game.update(time.time())
        if game.state == "over" and game.over_at != last_over:
            last_over = game.over_at
            rounds += 1
            print(f"Round {rounds}: {game.score} Teile, {game.top_h / 100:.1f} m, best streak {game.max_streak} "
                  f"- {game.over_text}", flush=True)
        game.draw(game_surf)
        close = K.game_title(screen, "lastenrave.exe", "lastenrave")
        frames += 1
        slow += (time.perf_counter() - t0) > 1 / args.fps
        if frames % (args.fps * 30) == 0:
            print(f"[{frames} frames] {slow} slower than {1000 // args.fps} ms", flush=True)
        pygame.display.flip()
        clock.tick(args.fps)


if __name__ == "__main__":
    main()
