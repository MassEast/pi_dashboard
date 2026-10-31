#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Night mode (config NIGHT_MODE): the time window (also across midnight), and
that the warm tint is applied exactly once per frame on every screen: a
screen that doesn't redraw itself fully each frame would get darker every
frame (the multiply stacks up). Renders each screen twice in night mode and
compares the blue channel of the two frames. Saves night screenshots to
scratch/night_mode/ for a look.

SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_night_mode.py
"""

import datetime
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame  # noqa: E402

import party_games  # noqa: E402
import PiDashboard as P  # noqa: E402
import render_dashboard as R  # noqa: E402  (fake_data for a populated home screen)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scratch", "night_mode")
os.makedirs(OUT, exist_ok=True)
party_games.configure(tempfile.mkdtemp(prefix="night_scores_"))
P.append_emotion_event = lambda *a, **k: {}


def test_window():
    P.NIGHT_CONFIG = {"ENABLED": True, "FROM": "23:00", "TO": "07:00"}
    at = lambda h, m: datetime.datetime(2026, 10, 31, h, m)  # noqa: E731
    assert P.night_mode_active(at(23, 0)) and P.night_mode_active(at(2, 30)) and P.night_mode_active(at(6, 59))
    assert not P.night_mode_active(at(7, 0)) and not P.night_mode_active(at(15, 0)) and not P.night_mode_active(at(22, 59))
    P.NIGHT_CONFIG = {"ENABLED": True, "FROM": "13:00", "TO": "14:00"}
    assert P.night_mode_active(at(13, 30)) and not P.night_mode_active(at(14, 0))
    P.NIGHT_CONFIG = {"ENABLED": False, "FROM": "00:00", "TO": "23:59"}
    assert not P.night_mode_active(at(12, 0))
    print("WINDOW: night hours incl. across midnight, disabled = off", flush=True)


def blue_mean(surf):
    return pygame.transform.average_color(surf)[2]


def frame():
    P.update_kiez_timeouts()
    P.draw_home()
    P.draw_dashboard_overlays()
    P.apply_night_mode(P.tft_surf)


def check(name):
    frame()
    first = blue_mean(P.tft_surf)
    frame()
    second = blue_mean(P.tft_surf)
    pygame.image.save(P.tft_surf, os.path.join(OUT, f"{name}.png"))
    assert second > 0.8 * first, f"{name}: tint stacks up ({first:.0f} -> {second:.0f} blue)"
    return second


def test_every_screen():
    P.NIGHT_CONFIG = {"ENABLED": True, "FROM": "00:00", "TO": "23:59", "TINT": [255, 150, 90]}
    P.images = P.image_factory(P.ICON_PATH)
    P.DISPLAY_BLANK = False
    P.WeatherUpdate.read_json_and_process()
    R.fake_data()
    P.BVG_MAP = None  # fake bus rows don't match the real (gitignored) map
    checked = []
    check("home")
    checked.append("home")
    P.START_MENU_OPEN = True
    check("start")
    P.close_start_menu()
    for name in ("wetter", "clock") + (("karte",) if P.BVG_MAP else ()):
        P.open_home_window(name)
        check(f"window_{name}")
        P.close_home_window("test")
        checked.append(name)
    P.open_dada("x_wetter")
    check("dada")
    P.DADA = None
    P.EMOTION_LAST_PROMPT_TS = 0
    P.schedule_emotion_prompt("motion")
    P.activate_pending_emotion_prompt()
    check("mood")
    P.dismiss_emotion_prompt("test")
    P.open_games_menu()
    check("spiele_menu")
    for game_cls in party_games.GAMES:
        P.start_game(game_cls.NAME)
        check(f"game_{game_cls.NAME.lower().replace('!', '')}")
        checked.append(game_cls.NAME)
    P.close_games("test")
    P.activate_merz_game()
    check("merz")
    P.dismiss_merz_game("test")
    if P.PINNWAND is not None:
        P.open_home_window("pinnwand")
        check("pinnwand")
        P.close_home_window("test")
    P.SHUTDOWN_VISIBLE = True
    check("shutdown")
    P.SHUTDOWN_VISIBLE = False
    for kind in P.EGG_KINDS:
        P.EGG = kind
        P.EGG_UNTIL = 9e12
        check(f"egg_{kind}")
    P.EGG = None
    print(f"SCREENS: tint applied once per frame on {len(checked) + 8 + len(P.EGG_KINDS)} screens - pictures in {OUT}", flush=True)


test_window()
test_every_screen()
print("All night mode tests passed", flush=True)
P.quit_all()
