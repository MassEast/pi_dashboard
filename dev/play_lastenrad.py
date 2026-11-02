#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Play LASTENRAD-SIMULATOR (lastenrad/) on the laptop: a real 480x800 window
with the KiezOS title bar on top. Mouse = touchscreen: press on the item in
the top bar and drag it onto the bike, release to let go. Rotate the held
item with Q / E (stands in for the second finger), or hold the round-arrow
buttons in the bar (they turn the next item before you pick it up). D
toggles the debug overlay. Doesn't import PiDashboard.py (that starts
schedulers / network). Highscores go to a temp dir, never logs/. x in the
title bar or Esc quits; closing and reopening (R) tests the WEITER resume.

.venv/bin/python dev/play_lastenrad.py [--fps 30] [--debug]
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

from kiosk import kiezos as K  # noqa: E402
from games import party_games  # noqa: E402
from games.lastenrad import LastenradGame, menu_icon_surface  # noqa: E402
from games.lastenrad import config as C  # noqa: E402

TITLE_H = 36  # = PiDashboard.GAME_TITLE_HEIGHT


def new_game(now):
    fonts = os.path.join(REPO, "fonts")
    game = LastenradGame(K.W, K.H - TITLE_H, os.path.join(fonts, "JetBrainsMono-Medium.ttf"),
                         os.path.join(fonts, "JetBrainsMono-Bold.ttf"))
    game.show_close = False  # the title bar's x closes it, like on the Pi
    game.reset(now)
    return game


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fps", type=int, default=30, help="PiDashboard runs games at GAMES.FPS (30)")
    parser.add_argument("--debug", action="store_true", help="collision shapes, COM, tilt, torque, FPS")
    args = parser.parse_args()
    C.DEBUG = args.debug
    pygame.init()
    screen = pygame.display.set_mode((K.W, K.H))
    pygame.display.set_caption("KiezOS 161 - lastenrad-simulator.exe")
    K.configure(os.path.join(REPO, "fonts") + "/", os.path.join(REPO, "icons") + "/",
                json.load(open(os.path.join(REPO, "themes", "kiezos.json")))["KIEZOS"])
    K.ICON_MAKERS["lastenrad"] = menu_icon_surface  # what PiDashboard.py does
    log_dir = tempfile.mkdtemp(prefix="lastenrad_scores_")
    party_games.configure(log_dir)
    print(f"LASTENRAD: highscores in {log_dir}. Drag from the bar, Q/E rotate, D debug, R close+reopen, Esc quit",
          flush=True)
    clock = pygame.time.Clock()
    game = new_game(time.time())
    game_surf = screen.subsurface((0, TITLE_H, K.W, K.H - TITLE_H))
    close = pygame.Rect(K.W - 44, 5, 38, 26).inflate(10, 10)
    frames, slow, worst, last_over = 0, 0, 0.0, None
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                print(f"Bye. Bestenliste Endlos: {party_games.top_list(game.NAME)[:5]}", flush=True)
                return
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_q, pygame.K_e):
                game.key_rotate(1 if event.key == pygame.K_q else -1)
            elif event.type == pygame.KEYUP and event.key in (pygame.K_q, pygame.K_e):
                game.key_rotate(0)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_d:
                C.DEBUG = not C.DEBUG
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                game = new_game(time.time())  # like PiDashboard closing and reopening the game
                print("Closed and reopened (resume slot test).", flush=True)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                x, y = event.pos
                if close.collidepoint((x, y)):
                    print("Bye.", flush=True)
                    return
                if y >= TITLE_H:
                    game.tap(x, y - TITLE_H)
            elif event.type == pygame.MOUSEMOTION and event.buttons[0]:
                game.drag(event.pos[0], event.pos[1] - TITLE_H)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                game.release()
        t0 = time.perf_counter()
        game.update(time.time())
        game.draw(game_surf)
        close = K.game_title(screen, "lastenrad-simulator.exe", "lastenrad")
        dt = time.perf_counter() - t0
        worst = max(worst, dt)
        if game.state == "over" and game.over_at != last_over:
            last_over = game.over_at
            print(f"Round over: {game.format_score(game.score)} ({game.mode}) - {game.over_text}", flush=True)
        frames += 1
        slow += dt > 1 / args.fps
        if frames % (args.fps * 30) == 0:
            print(f"[{frames} frames] {slow} slower than {1000 // args.fps} ms, worst {worst * 1000:.1f} ms", flush=True)
            worst = 0.0
        pygame.display.flip()
        clock.tick(args.fps)


if __name__ == "__main__":
    main()
