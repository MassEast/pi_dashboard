#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless screenshot tour of the real KiezOS 161 dashboard: drives
PiDashboard.py's own draw/tap functions (exactly what loop() runs per frame)
through every screen and saves one PNG each - home, Start menu, detail
views, dada boxes, emotion prompt, QR dialogs, games, MERZ, AFM quiz,
Putzdienste, cleaning day, the PIR-wake surprises.

Live data: logs/latest_weather.json (STAGE mode; copy the Pi's
/mnt/ramdisk/latest_weather.json there), BVG departures, MoaBeats status
(read-only GET) if enabled in config.json. Never ticks anything.

--fake: made-up buses/WG/stops/Pinnwand instead (no BVG/MoaBeats calls):
home screen (also in night mode), pinnwand.exe and every game, for the
public README (images/kiezos_*.png). TIC-TAC-DADA shows its placeholder
faces, never the WG's profile pictures.

SDL_VIDEODRIVER=dummy .venv/bin/python dev/render_dashboard.py scratch/redesign/app
"""

import datetime
import os
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shutil  # noqa: E402

import pandas as pd  # noqa: E402
import pygame  # noqa: E402

import PiDashboard as P  # noqa: E402
import party_games  # noqa: E402

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
FAKE = "--fake" in sys.argv[1:]
OUT_DIR = ARGS[0] if ARGS else tempfile.mkdtemp(prefix="pidashboard_render_")
os.makedirs(OUT_DIR, exist_ok=True)
SHOTS = []


def frame():
    """One iteration of loop()'s awake branch."""
    P.update_kiez_timeouts()
    P.draw_home()
    P.draw_dashboard_overlays()


def shot(name, frames=1):
    for _ in range(frames):
        frame()
    path = os.path.join(OUT_DIR, f"{name}.png")
    pygame.image.save(P.tft_surf, path)
    SHOTS.append(path)
    print(f"wrote {path}", flush=True)


def tap(rect):
    pos = pygame.Rect(rect).center
    assert P.handle_tap(*pos), f"tap at {pos} not handled"
    frame()  # loop() redraws (and so refreshes every hit rect) before the next tap


def start_menu(action):
    """Open Start and tap the entry for action."""
    P.close_start_menu()
    frame()
    tap(P.START_BUTTON_RECT)
    frame()
    if action.startswith("game:"):
        tap(next(r for r, a in P.START_MENU_RECTS if a == "games_sub"))
        frame()
    tap(next(r for r, a in P.START_MENU_RECTS if a == action))


def game_shots(prefix):
    """Every party game after a few simulated seconds of random taps/swipes
    (simulated time: draw_active_game() would update with the wall clock)."""
    import random
    import tictacdada
    tictacdada.AVATARS = []  # placeholders, not the WG's pictures
    rng = random.Random(161)
    area = (0, P.GAME_TITLE_HEIGHT, P.DISPLAY_WIDTH, P.DISPLAY_HEIGHT - P.GAME_TITLE_HEIGHT)
    for i, cls in enumerate(party_games.GAMES):
        P.start_game(cls.NAME)
        game = P.ACTIVE_GAME
        sub = P.tft_surf.subsurface(area)
        game.draw(sub)  # hit rects exist after the first draw
        if "go" in getattr(game, "rects", {}):  # TIC-TAC-DADA: setup -> play, a few moves
            game.tap(*game.rects["go"].center)
            game.egg = None
            for cell in (4, 0, 2):
                game.draw(sub)
                game.tap(*game.rects[f"cell{cell}"].center)
            game.draw(sub)
            path = os.path.join(OUT_DIR, f"{prefix}{i:02d}_tic-tac-dada.png")
            pygame.image.save(P.tft_surf, path)
            P.K.game_title(P.tft_surf, "tic-tac-dada.exe", game.ICON)
            pygame.image.save(P.tft_surf, path)
            SHOTS.append(path)
            P.close_games("render")
            continue
        game.tap(240, 600)  # ready -> play
        for f in range(int(6.0 * 20)):
            game.update(game.last_tick + 0.05)
            if game.state == "over":
                break
            if f % 10 == 0:
                x, y = rng.randrange(60, 420), rng.randrange(250, 700)
                game.tap(x, y)
                for k in range(6):
                    game.drag(x + (k - 3) * 30, y - k * 10)
                game.release()
        game.draw(P.tft_surf.subsurface(area))
        P.K.game_title(P.tft_surf, cls.NAME.lower().replace("!", "") + ".exe", game.ICON)
        path = os.path.join(OUT_DIR, f"{prefix}{i:02d}_{cls.NAME.lower().replace('!', '').replace(' ', '_')}.png")
        pygame.image.save(P.tft_surf, path)
        SHOTS.append(path)
        print(f"wrote {path}", flush=True)
        P.close_games("render")


def fake_pinnwand():
    """Made-up Pinnwand messages (no MoaBeats calls)."""
    import pinnwand
    now = datetime.datetime.now()
    P.PINNWAND = pinnwand.Pinnwand("http://127.0.0.1:9", "FlurPi", "x")
    msgs = [("Kim", "Wer hat meine Hafermilch leer gemacht?", False, 95),
            ("Sam", "Ich wars. Kauf morgen neue, versprochen", False, 80),
            ("Oma Erna", "Danke fürs Übernachten, ihr Lieben!", True, 40),
            ("Robin", "Plenum heute um 20 Uhr in der Küche", False, 12)]
    P.PINNWAND.messages = [{"id": i, "author": a, "text": t, "guest": g, "ts": now - datetime.timedelta(minutes=m)}
                           for i, (a, t, g, m) in enumerate(msgs)]
    P.PINNWAND.loaded = True
    P.PINNWAND.seen_id = 2
    P.PINNWAND.login_failed = True  # never fetch (would replace the made-up messages)


def fake_data():
    """Made-up departures/WG for the public README."""
    now = datetime.datetime.now()
    labels = [("Schlossplatz", "palace", "142", "double_left"), ("Gartenstr.", "garden", "142", "left"),
              ("Tierpark", "zoo", "142", "up"), ("Strandbad", "lake", "69", "down")]
    P.BVG_ROWS = [{"id": f"row-{i}", "line": line, "icon": icon, "label": label, "landmark": lm}
                  for i, (label, lm, line, icon) in enumerate(labels)]
    deps = {"row-0": [(3, 0), (13, 0), (23, 0)], "row-1": [(7, 0), (17, 0), (27, 0)],
            "row-2": [(1, 0), (11, 0), (21, 0)], "row-3": [(9, 6), (29, 0)]}
    rows = []
    for row_id, items in deps.items():
        for mins, delay in items:
            planned = now + datetime.timedelta(minutes=mins - delay, seconds=59)
            rows.append({"row_id": row_id, "departure": planned.strftime("%H:%M"), "delay": delay, "cancelled": False})
    P.BVG_STOP_INFORMATION = pd.DataFrame(rows)
    P.UPDATED_BVG_TIME = time.time()
    day = lambda k: (now + datetime.timedelta(days=k)).date().isoformat()  # noqa: E731
    P.config.setdefault("MOABEATS", {})["ENABLED"] = True
    P.MOABEATS_STATUS = {
        "overdue_chores": [{"name": "Altglas", "assigned_to": "Kim"}],
        "shopping": [{"name": "Hafermilch"}, {"name": "Klopapier"}, {"name": "Kaffee"}],
        "visits": [{"guest": "Oma Erna", "hosts": ["Sam"], "start": day(2), "end": day(4)}],
        "cleaning_chores": [],
    }


def main():
    P.append_emotion_event = lambda *a, **k: {"tour": "not logged"}  # never write into the real store
    scores = tempfile.mkdtemp(prefix="tour_scores_")  # closing a game saves its score: use a copy
    if not FAKE and os.path.exists(os.path.join(P.LOG_PATH, "game_highscores.json")):  # fake: empty lists
        shutil.copy(os.path.join(P.LOG_PATH, "game_highscores.json"), scores)
    party_games.configure(scores)
    P.images = P.image_factory(P.ICON_PATH)
    P.DISPLAY_BLANK = False
    P.WeatherUpdate.read_json_and_process()
    if FAKE:
        fake_data()
        fake_pinnwand()
        shot("home")
        P.open_home_window("pinnwand")
        shot("pinnwand")
        P.close_home_window("render")
        night = P.NIGHT_CONFIG
        P.NIGHT_CONFIG = {"ENABLED": True, "FROM": "00:00", "TO": "23:59", "TINT": [255, 150, 90]}
        frame()
        P.apply_night_mode(P.tft_surf)
        pygame.image.save(P.tft_surf, os.path.join(OUT_DIR, "night.png"))
        P.NIGHT_CONFIG = night
        game_shots("game_")
        return
    P.BVGUpdate.update_bvg_stop_information()
    if P.config.get("MOABEATS", {}).get("ENABLED", False):
        P._moabeats_fetch_status()

    # home + Start menu
    shot("01_home")
    tap(P.START_BUTTON_RECT)
    shot("02_start")
    tap(next(r for r, a in P.START_MENU_RECTS if a == "games_sub"))
    shot("02b_start_spiele")
    P.close_start_menu()

    # detail views: Mehr..., Karte..., uhr.exe's o
    tap(P.HOME_RECTS["mehr"])
    shot("03_wetter")
    tap(P.HOME_WINDOW_RECTS["back"])
    if "karte" in P.HOME_RECTS:
        tap(P.HOME_RECTS["karte"])
        shot("04_karte")
        tap(P.HOME_WINDOW_RECTS["back"])
    tap((360, 60, 1, 1))  # tap on the clock
    shot("05_uhr_max")
    tap((200, 400, 1, 1))
    assert P.HOME_WINDOW is None

    # dada title buttons
    tap(P.K.title_buttons(P.WIN_WETTER)["x"])
    shot("11_dada_wetter_x")
    tap(P.DADA_BUTTON_RECTS[0][0])
    tap(P.K.title_buttons(P.WIN_WG)["x"])
    shot("12_dada_wg_x")
    tap(P.DADA_BUTTON_RECTS[0][0])
    shot("12b_dada_wg_ja")
    tap(P.DADA_BUTTON_RECTS[0][0])
    tap(P.K.title_buttons(P.WIN_BVG)["x"])
    shot("13_dada_bvg_sev")
    P.SEV_UNTIL = 0
    tap(P.K.title_buttons(P.WIN_WETTER)["_"])
    shot("14_dada_minimiert")
    P.MINIMIZED.clear()

    # emotion prompt (what a motion wake opens), keyboard, confirmation, stats QR
    P.EMOTION_LAST_PROMPT_TS = 0
    P.schedule_emotion_prompt("motion")
    P.activate_pending_emotion_prompt()
    shot("20_stimmung")
    trigger = next(b for b in P.EMOTION_CUSTOM_BUTTON_RECTS if b["type"] == "trigger")
    tap(trigger["rect"])
    for token in "verkatert":
        tap(next(k["rect"] for k in P.EMOTION_KEYBOARD_RECTS if k["token"] == token))
    shot("21_stimmung_eigene")
    tap(P.EMOTION_ACTION_RECTS["keyboard_cancel"])
    tap(P.EMOTION_ACTION_RECTS["show_results"])
    shot("22_stimmung_ergebnisse")
    tap((240, 400, 1, 1))
    tap(P.EMOTION_ACTION_RECTS["cancel"])  # skip (logged as skipped, like the x)
    assert not P.EMOTION_PROMPT_VISIBLE
    P.show_emotion_confirmation("happy")
    shot("23_stimmung_danke")
    tap((240, 400, 1, 1))

    start_menu("stats")
    shot("24_stats_qr")
    tap((240, 400, 1, 1))
    if P.WIFI_ENABLED:
        start_menu("wifi")
        shot("25_wlan_qr")
        tap((240, 400, 1, 1))

    # pinnwand.exe (read-only GET, if configured)
    if P.PINNWAND is not None:
        P.PINNWAND.fetch()
        P.open_home_window("pinnwand")
        shot("15_pinnwand")
        P.close_home_window("render")

    # games
    if P.GAMES_ENABLED:
        P.open_games_menu()
        shot("30_spiele")
        tap(P.GAMES_MENU_CLOSE_RECT)
        start_menu("game:__more__")  # Start -> Spiele -> Mehr Spiele... = the spiele.exe folder
        shot("30b_spiele_mehr")
        tap(P.GAMES_MENU_CLOSE_RECT)
        assert not P.games_open()
        game_shots("31_")
        start_menu("game:merz")
        P.MERZ_HITS = 23
        P.MERZ_TIMER_STARTED_AT = time.time() - 12.4
        P.MERZ_TAUNT_BAG = [max(P.MERZ_TAUNTS, key=lambda t: len(t["text"]))]  # the longest quote
        shot("33_merz", frames=3)
        P.MERZ_BURN_UNLOCKED = True
        P.MERZ_PROJECTILE_KIND = "burn"
        shot("33b_merz_burn")
        tap(P.MERZ_ACTION_RECTS["close"])
        assert not P.MERZ_VISIBLE

    # AFM quiz
    if P.QUIZ_ENABLED:
        start_menu("quiz")
        for token in "kim":
            tap(next(k["rect"] for k in P.QUIZ_NAME_RECTS if k["token"] == token))
        shot("40_afm_name")
        tap(P.QUIZ_NAME_ACTION_RECTS["start"])
        P.QUIZ_SCAN_HELD = True
        for _ in range(20):
            P.QUIZ_SCAN_LAST_TICK = time.time() - 0.15
            frame()
        shot("41_afm_scan")
        P.QUIZ_STAGE = "question"
        shot("42_afm_frage")
        P.show_quiz_results_only()
        shot("43_afm_ergebnis")
        tap(P.QUIZ_RESULTS_ACTION_RECTS["close_button"])
        assert P.QUIZ_STAGE is None

    # Putzdienste + cleaning day (read-only: no tick taps)
    if P.config.get("MOABEATS", {}).get("ENABLED", False):
        start_menu("putz")
        P.CHORE_DETAIL_REFRESHING = False
        shot("50_putzdienste")
        rows = [r for r, _, has in P.CLEANING_CHORE_ROW_RECTS if has]
        if rows:
            tap(rows[0])
            P.CHORE_DETAIL_REFRESHING = False
            shot("51_putz_checkliste")
            tap(P.CHORE_DETAIL_BACK_RECT)
        tap(P.CHORE_LIST_CLOSE_RECT)
        assert not P.CHORE_LIST_OPEN
    P.DISPLAY_BLANK = True
    P.draw_cleaning_day_screen()
    pygame.image.save(P.tft_surf, os.path.join(OUT_DIR, "52_putztag.png"))
    SHOTS.append(os.path.join(OUT_DIR, "52_putztag.png"))
    P.DISPLAY_BLANK = False

    # Herunterfahren + PIR-wake surprises
    start_menu("shutdown")
    shot("60_herunterfahren")
    tap((240, 400, 1, 1))
    for kind in P.EGG_KINDS:
        P.EGG, P.EGG_UNTIL = kind, time.time() + P.EGG_SECONDS
        shot(f"61_egg_{kind}")
        if kind == "assistant":
            tap(P.EGG_RECTS["hilfe"])
            shot("61_egg_hilfe")
        tap((240, 300, 1, 1))
        assert P.EGG is None
    print(f"{len(SHOTS)} screenshots in {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
    P.quit_all()
