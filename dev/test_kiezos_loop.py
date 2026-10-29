#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
End-to-end smoke test of the KiezOS 161 dashboard: runs PiDashboard.py's
real loop() (scheduler threads, event queue, timeouts, blanking) headless
and drives it with posted touch events from a second thread, the way the
touchscreen does: Start menu -> STAPEL-TURM -> x, Mehr... -> Zurück,
uhr.exe maximise, dada boxes, every popup's x, display blank + touch wake, a PIR wake with a
surprise (forced) followed by the emotion prompt, the 5-tap emergency exit
counter, then QUIT. Fails on any exception in the loop or a step whose
effect doesn't show up.

Nothing is written to the real stores: emotion logging is stubbed and the
highscores go to a temp copy. Uses live weather file/BVG/MoaBeats (read-only).

SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_kiezos_loop.py
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import traceback

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import PiDashboard as P  # noqa: E402
import party_games  # noqa: E402

LOGGED = []
P.append_emotion_event = lambda *a, **k: LOGGED.append(k) or k
os.system = lambda cmd: 0  # no xset on a laptop / in CI
scores = tempfile.mkdtemp(prefix="loop_scores_")
if os.path.exists(os.path.join(P.LOG_PATH, "game_highscores.json")):
    shutil.copy(os.path.join(P.LOG_PATH, "game_highscores.json"), scores)
party_games.configure(scores)
P.EMOTION_COOLDOWN_SECONDS = 0
P.GAMES_ENABLED = True

STEPS = []
FAILURE = []


def tap(pos):
    pos = pygame.Rect(pos).center if len(pos) == 4 else pos
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
    time.sleep(0.12)
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))
    time.sleep(0.35)  # a few frames, so the loop redraws (fresh hit rects)


def check(name, cond):
    STEPS.append(name)
    print(("ok   " if cond else "FAIL ") + name, flush=True)
    if not cond:
        FAILURE.append(name)


def driver():
    try:
        deadline = time.time() + 30  # the schedulers' first BVG/weather/MoaBeats fetches run first
        while P.START_BUTTON_RECT is None and time.time() < deadline:
            time.sleep(0.2)
        time.sleep(1.0)
        check("home drawn", P.START_BUTTON_RECT is not None and "mehr" in P.HOME_RECTS)

        tap(P.START_BUTTON_RECT)
        check("Start opens the menu", P.START_MENU_OPEN)
        tap(next(r for r, a in P.START_MENU_RECTS if a == "games_sub"))
        tap(next(r for r, a in P.START_MENU_RECTS if a == "game:STAPEL-TURM"))
        check("STAPEL-TURM running", P.ACTIVE_GAME is not None and P.ACTIVE_GAME.NAME == "STAPEL-TURM")
        check("emergency exit off in the game", not P.emergency_exit_active())
        for _ in range(3):
            tap((240, 500))
        tap(P.GAME_TITLE_X)
        check("title bar x closes the game", P.ACTIVE_GAME is None and not P.games_open())

        tap(P.HOME_RECTS["mehr"])
        check("Mehr... opens wetter details", P.HOME_WINDOW == "wetter")
        tap(P.HOME_WINDOW_RECTS["back"])
        check("< Zurück back home", P.HOME_WINDOW is None)
        tap(P.K.title_buttons(P.WIN_UHR)["o"])
        check("uhr.exe o maximises", P.HOME_WINDOW == "clock")
        tap((240, 400))
        check("tap restores the clock", P.HOME_WINDOW is None)
        bar = P.K.title_buttons(P.WIN_BVG)["bar"]
        pos = (bar.centerx, bar.centery)
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
        time.sleep(0.4)
        check("double-tap bvg.exe title opens karte", P.HOME_WINDOW == ("karte" if P.BVG_MAP else None))
        if P.HOME_WINDOW:
            tap(P.HOME_WINDOW_RECTS["back"])
        tap(P.K.title_buttons(P.WIN_WG)["x"])
        check("wg.txt x opens the dada box", P.DADA is not None and P.DADA["kind"] == "x_wg")
        tap(P.DADA_BUTTON_RECTS[1][0])  # Nein!
        check("Nein! closes it", P.DADA is None)

        # Popups have one x (no o/_), and it closes them.
        tap(P.K.title_buttons(P.WIN_UHR)["x"])
        tap(next(r for r, label in P.DADA_BUTTON_RECTS if label == "x"))
        check("dada box x closes it", P.DADA is None)
        tap(P.HOME_RECTS["mehr"])
        tap(P.HOME_WINDOW_RECTS["x"])
        check("wetter details x closes", P.HOME_WINDOW is None)
        P.open_games_menu()
        time.sleep(0.3)
        tap(P.GAMES_MENU_TITLE_X)
        check("spiele.exe x closes", not P.games_open())
        tap(P.K.title_buttons(P.WIN_BVG)["x"])
        check("bvg.exe x -> sev.exe", time.time() < P.SEV_UNTIL)
        tap(P.K.close_box(P.WIN_BVG))
        check("sev.exe x gives bvg.exe back", time.time() >= P.SEV_UNTIL)

        # Display blank (idle timeout) and touch wake.
        P.LAST_TOUCH_TIME = time.time() - P.DISPLAY_BLANK_AFTER - 1
        time.sleep(0.5)
        check("idle -> blank", P.DISPLAY_BLANK)
        tap((300, 400))
        check("touch wakes", not P.DISPLAY_BLANK)
        if P.EMOTION_PROMPT_VISIBLE:
            tap(P.EMOTION_ACTION_RECTS["cancel"])

        # PIR wake with a (forced) surprise, then the emotion prompt.
        P.EGGS_ENABLED, P.EGGS_ONE_IN = True, 1
        P.LAST_TOUCH_TIME = time.time() - P.DISPLAY_BLANK_AFTER - 1
        time.sleep(0.5)
        check("idle -> blank again", P.DISPLAY_BLANK)
        P.on_motion_detected()
        time.sleep(0.4)
        check("motion wake shows a surprise", P.EGG is not None and not P.DISPLAY_BLANK)
        check("emotion prompt waits for the surprise", not P.EMOTION_PROMPT_VISIBLE)
        tap((240, 300))
        check("tap closes the surprise", P.EGG is None)
        time.sleep(0.3)
        check("emotion prompt follows", P.EMOTION_PROMPT_VISIBLE)
        tap(P.EMOTION_ACTION_RECTS["cancel"])
        check("Cancel logs a skip", not P.EMOTION_PROMPT_VISIBLE and LOGGED and LOGGED[-1].get("skipped"))

        # Emergency exit: counts taps in the corner (4 only - 5 would quit).
        for _ in range(4):
            tap((30, 30))
        check("corner taps don't open anything", not P.dashboard_overlay_open() and not P.START_MENU_OPEN)
        check(f"fps {P.clock.get_fps():.1f} >= {P.FPS * 0.8:.0f}", P.clock.get_fps() >= P.FPS * 0.8)
    except Exception:
        traceback.print_exc()
        FAILURE.append("driver crashed")
    pygame.event.post(pygame.event.Event(pygame.QUIT))


threading.Thread(target=driver, daemon=True).start()
P.images = P.image_factory(P.ICON_PATH)
try:
    P.loop()
except SystemExit:
    pass
print(f"{len(STEPS) - len(FAILURE)}/{len(STEPS)} steps ok" + (f", FAILED: {FAILURE}" if FAILURE else ""), flush=True)
os._exit(1 if FAILURE else 0)
