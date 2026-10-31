#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Soak check for a kiosk that runs for weeks: starts every game (and MERZ)
ROUNDS times, plays a few simulated seconds with random taps/swipes, closes
it, draws home in between, and checks that memory (RSS) stops growing after
the first rounds (module-level caches fill once, then stay). Prints progress
and the RSS per round.

SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_soak.py [rounds]
"""

import os
import random
import resource
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import party_games  # noqa: E402
import PiDashboard as P  # noqa: E402

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
party_games.configure(tempfile.mkdtemp(prefix="soak_scores_"))
P.append_emotion_event = lambda *a, **k: {}
P.images = P.image_factory(P.ICON_PATH)
P.DISPLAY_BLANK = False
rng = random.Random(7)
area = (0, P.GAME_TITLE_HEIGHT, P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT)


def rss_mb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / (1024 * 1024) if sys.platform == "darwin" else r / 1024  # bytes on macOS, KiB on Linux


def play(cls, seconds=8.0):
    P.start_game(cls.NAME)
    game = P.ACTIVE_GAME
    sub = P.tft_surf.subsurface(area)
    game.draw(sub)
    for f in range(int(seconds * 20)):
        game.update(game.last_tick + 0.05)
        if f % 7 == 0:
            x, y = rng.randrange(0, 480), rng.randrange(150, 760)
            game.tap(x, y)
            for k in range(5):
                game.drag(x + rng.randrange(-60, 60), y + rng.randrange(-60, 60))
            game.release()
        game.draw(sub)
        if game.state == "over":
            game.reset(game.last_tick)
    P.close_games("soak")


start = time.time()
history = []
for r in range(ROUNDS):
    for cls in party_games.GAMES:
        play(cls)
    P.activate_merz_game()
    for _ in range(20):
        P.handle_tap(rng.randrange(60, 420), rng.randrange(200, 700))
        P.draw_dashboard_overlays()
    P.dismiss_merz_game("soak")
    P.HOME_CACHE_KEY = None
    P.draw_home()
    history.append(rss_mb())
    print(f"round {r + 1}/{ROUNDS}: max RSS {history[-1]:.0f} MB ({time.time() - start:.0f} s)", flush=True)

warm = history[min(4, len(history) - 1)]
growth = history[-1] - warm
print(f"RSS after warm-up {warm:.0f} MB, at the end {history[-1]:.0f} MB, growth {growth:.0f} MB over {ROUNDS} rounds", flush=True)
assert growth < 40, f"memory keeps growing: +{growth:.0f} MB"
print("SOAK passed", flush=True)
P.quit_all()
