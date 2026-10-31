#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless check for the cleaning-day chore checklist detail screen in
PiDashboard.py, against a local fake MoaBeats server (never the real one -
config.json's MOABEATS block is overridden):

- list rows show "done/total" and only chores with a checklist are tappable
- opening the detail screen refetches /api/display/status once
- tapping an item PATCHes it (auth header + body) and the screen follows the response
- a 400 shows a red "Nicht gespeichert" line and reloads the fresh list
- a network error shows a red line too
- "Zurück" and the 60 s idle timeout close it; nothing tappable sits in the
  emergency-exit corner
- Start -> Putzdienste opens the same list as an overlay on the awake dashboard
- with any overlay open, taps on the KiezOS desktop (Start, title buttons,
  Mehr..., Karte...) never start another feature underneath

Renders screenshots to a fresh temp dir (path printed at the end). Run directly:
SDL_VIDEODRIVER=dummy venv/bin/python3 dev/test_moabeats_checklist.py
"""

import datetime
import os
import sys
import tempfile
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame  # noqa: E402

import PiDashboard as P  # noqa: E402
import fake_moabeats_server  # noqa: E402

OUT_DIR = tempfile.mkdtemp(prefix="pidashboard_checklist_")
SECRET = "test-secret"

FAKE = fake_moabeats_server.STATE
# Own data, independent of the server's SAMPLE_STATUS (asserts below depend on it).
FAKE["status"] = {
    "overdue_chores": [],
    "shopping": [],
    "visits": [],
    "cleaning_chores": [
        {
            "id": 7,
            "name": "Bad",
            "full_name": "Badezimmer putzen",
            "assigned_to": "Ju",
            "checklist": [
                {"item": "Waschbecken", "done": True},
                {"item": "Toilette", "done": False},
                {"item": "Spiegel und Fliesen über dem Waschbecken abwischen, auch hinter der Armatur", "done": False},
            ],
        },
        {"id": 8, "name": "Müll", "full_name": "Müll rausbringen", "assigned_to": "Kim", "checklist": []},
    ],
}


def wait_idle():
    deadline = time.time() + 5
    while P.CHORE_DETAIL_PENDING_ITEM is not None or P.CHORE_DETAIL_REFRESHING:
        assert time.time() < deadline, "worker thread did not finish"
        time.sleep(0.02)


def tap_item(text):
    rect = next(r for r, e in P.CHORE_DETAIL_ROW_RECTS if e["item"] == text)
    assert P.handle_chore_detail_click(*rect.center)


# What may sit in the outermost pixel columns: the desktop or a window frame.
EDGE_COLORS = {P.K.DESK, P.K.DESK_DITHER, P.K.F_FACE, P.K.F_LIGHT, P.K.F_DARK, P.K.SHADOW}


def shot(name, check_edges=True):
    pygame.image.save(P.tft_surf, os.path.join(OUT_DIR, name))
    if check_edges:
        # Chore screens keep a margin: anything else in the outermost pixel
        # columns is text running off the 480 px screen.
        for x in (0, P.DISPLAY_WIDTH - 1):
            for y in range(0, P.DISPLAY_HEIGHT, 2):
                assert tuple(P.tft_surf.get_at((x, y))[:3]) in EDGE_COLORS, f"{name}: content at screen edge ({x}, {y})"


def test_checklist_detail():
    server = fake_moabeats_server.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api_url = f"http://127.0.0.1:{server.server_port}"
    P.config["MOABEATS"] = {"ENABLED": True, "API_URL": api_url, "DISPLAY_SECRET": SECRET}
    P.CLEANING_DAY = datetime.datetime.today().weekday()
    P.DISPLAY_BLANK = True
    exit_zone = pygame.Rect(0, 0, P.EMERGENCY_EXIT_MAX_X, P.EMERGENCY_EXIT_MAX_Y)

    # Regression: stale desktop hit rects (Start button, last drawn while
    # awake) must not swallow taps on the blank/cleaning screen (no wake).
    P.START_BUTTON_RECT = pygame.Rect(0, P.DISPLAY_HEIGHT - 40, 110, 40)
    assert not P.handle_home_click(20, P.DISPLAY_HEIGHT - 20)
    assert not P.START_MENU_OPEN

    assert P._moabeats_fetch_status()
    P.draw_cleaning_day_screen()
    shot("1_list.png")
    assert [(cid, has) for _, cid, has in P.CLEANING_CHORE_ROW_RECTS] == [(7, True), (8, False)]
    # A chore without a checklist: tap is swallowed (no wake), no detail screen.
    muell_rect = P.CLEANING_CHORE_ROW_RECTS[1][0]
    assert P.handle_cleaning_chore_list_click(*muell_rect.center)
    assert P.CHORE_DETAIL_ID is None and P.DISPLAY_BLANK
    assert P._chore_progress_text(FAKE["status"]["cleaning_chores"][0]["checklist"]) == "1/3"
    cards = [r for r, _, _ in P.CLEANING_CHORE_ROW_RECTS]
    for i, rect in enumerate(cards):
        assert not rect.colliderect(exit_zone)
        assert rect.height >= 44 and rect.left >= 0 and rect.right <= P.DISPLAY_WIDTH
        assert all(not rect.colliderect(other) for other in cards[i + 1:]), "chore cards overlap"
    assert cards[-1].bottom < P.CHORE_LIST_CLOSE_RECT.top

    # Screensaver "Schließen" wakes the dashboard (and closes nothing else).
    # wake_display() kicks off a BVG refresh thread that needs the real app's
    # icon set (only built under __main__) - not under test here.
    P.BVGUpdate.update_bvg_stop_information = staticmethod(lambda: None)
    P.draw_cleaning_day_screen()
    assert P.handle_cleaning_chore_list_click(*P.CHORE_LIST_CLOSE_RECT.center)
    assert not P.DISPLAY_BLANK, "Schließen on the screensaver did not wake"
    P.DISPLAY_BLANK = True
    P.draw_cleaning_day_screen()

    # Open: refetches the status once.
    gets_before = FAKE["gets"]
    FAKE["status"]["cleaning_chores"][0]["checklist"][1]["done"] = True  # "ticked on a phone"
    row_rect = P.CLEANING_CHORE_ROW_RECTS[0][0]
    assert P.handle_cleaning_chore_list_click(*row_rect.center)
    assert P.CHORE_DETAIL_ID == 7
    wait_idle()
    assert FAKE["gets"] == gets_before + 1
    assert P._find_cleaning_chore(7)["checklist"][1]["done"], "phone tick not picked up on open"
    P.draw_cleaning_day_screen()
    shot("2_detail_opened.png")
    assert len(P.CHORE_DETAIL_ROW_RECTS) == 3
    # Rows may use the corner band: the emergency exit is off on this screen.
    assert not P.emergency_exit_active()
    assert not P.CHORE_DETAIL_BACK_RECT.colliderect(exit_zone)
    for rect in [r for r, _ in P.CHORE_DETAIL_ROW_RECTS] + [P.CHORE_DETAIL_BACK_RECT]:
        assert rect.height >= 52, "touch target too small"
    assert P.CHORE_DETAIL_ERROR is None

    # Tick: PATCH with the right body, screen follows the response.
    long_item = FAKE["status"]["cleaning_chores"][0]["checklist"][2]["item"]
    tap_item(long_item)
    assert P.CHORE_DETAIL_PENDING_ITEM == long_item
    P.draw_cleaning_day_screen()
    shot("3_saving.png")
    wait_idle()
    assert FAKE["patches"][-1] == (7, {"item": long_item, "done": True}, f"Bearer {SECRET}")
    assert all(e["done"] for e in P._find_cleaning_chore(7)["checklist"])
    assert P.CHORE_DETAIL_ERROR is None

    # Untick.
    tap_item("Waschbecken")
    wait_idle()
    assert FAKE["patches"][-1] == (7, {"item": "Waschbecken", "done": False}, f"Bearer {SECRET}")
    assert not P._find_cleaning_chore(7)["checklist"][0]["done"]
    P.draw_cleaning_day_screen()
    shot("4_after_toggles.png")

    # 400 (item edited away in the app): red line + fresh list from the server.
    FAKE["patch_mode"] = "400"
    FAKE["status"]["cleaning_chores"][0]["checklist"] = [
        {"item": "Waschbecken", "done": False},
        {"item": "Dusche", "done": False},
    ]
    tap_item("Toilette")
    wait_idle()
    assert P.CHORE_DETAIL_ERROR.startswith("Nicht gespeichert"), P.CHORE_DETAIL_ERROR
    assert [e["item"] for e in P._find_cleaning_chore(7)["checklist"]] == ["Waschbecken", "Dusche"]
    P.draw_cleaning_day_screen()
    shot("5_error_400.png")
    assert [e["item"] for _, e in P.CHORE_DETAIL_ROW_RECTS] == ["Waschbecken", "Dusche"]
    FAKE["patch_mode"] = "ok"

    # A successful tap clears the error again.
    tap_item("Dusche")
    wait_idle()
    assert P.CHORE_DETAIL_ERROR is None

    # Chore completed in the app meanwhile (400 + gone from the status).
    FAKE["patch_mode"] = "400"
    completed = FAKE["status"]["cleaning_chores"].pop(0)
    tap_item("Waschbecken")
    wait_idle()
    assert P.CHORE_DETAIL_ERROR.startswith("Nicht gespeichert")
    P.draw_cleaning_day_screen()
    shot("6_completed_in_app.png")
    assert P.CHORE_DETAIL_ROW_RECTS == [], "rows of a vanished chore must not be tappable"
    FAKE["status"]["cleaning_chores"].insert(0, completed)
    FAKE["patch_mode"] = "ok"
    assert P._moabeats_fetch_status()

    # Network error: red line.
    P.config["MOABEATS"]["API_URL"] = "http://127.0.0.1:9"  # discard port, nothing listens
    P.draw_cleaning_day_screen()
    tap_item("Waschbecken")
    wait_idle()
    assert "keine Verbindung" in P.CHORE_DETAIL_ERROR, P.CHORE_DETAIL_ERROR
    P.draw_cleaning_day_screen()
    shot("7_error_network.png")
    P.config["MOABEATS"]["API_URL"] = api_url

    # Taps outside controls are swallowed (no dashboard wake behind it).
    assert P.handle_chore_detail_click(P.DISPLAY_WIDTH // 2, 50)
    assert P.CHORE_DETAIL_ID == 7

    # Zurück.
    assert P.handle_chore_detail_click(*P.CHORE_DETAIL_BACK_RECT.center)
    assert P.CHORE_DETAIL_ID is None
    P.draw_cleaning_day_screen()
    assert P.CLEANING_CHORE_ROW_RECTS, "back on the list"

    # Idle timeout.
    P.open_chore_detail(7)
    wait_idle()
    P.update_chore_screen_timeout()
    assert P.CHORE_DETAIL_ID == 7
    P.CHORE_DETAIL_LAST_ACTIVITY_TS = time.time() - P.CHORE_DETAIL_IDLE_TIMEOUT_SECONDS - 1
    P.update_chore_screen_timeout()
    assert P.CHORE_DETAIL_ID is None, "idle timeout did not close"

    # Not cleaning day / dashboard awake: rows aren't tappable, detail closes.
    P.open_chore_detail(7)
    wait_idle()
    P.DISPLAY_BLANK = False
    P.update_chore_screen_timeout()
    assert P.CHORE_DETAIL_ID is None
    assert not P.handle_cleaning_chore_list_click(*row_rect.center)
    P.DISPLAY_BLANK = True

    # Long checklist: rows stay big, don't run into the status/back area,
    # and the rest is announced as "+N weitere" instead of silently cut.
    FAKE["status"]["cleaning_chores"][0]["checklist"] = [
        {"item": f"Punkt {i + 1}", "done": i % 3 == 0} for i in range(12)
    ]
    assert P._moabeats_fetch_status()
    P.open_chore_detail(7)
    wait_idle()
    P.CHORE_DETAIL_ERROR = "Nicht gespeichert – Liste wurde geändert"  # longest message, must wrap on screen
    P.draw_cleaning_day_screen()
    shot("8_long_list.png")
    rows = [r for r, _ in P.CHORE_DETAIL_ROW_RECTS]
    assert 0 < len(rows) < 12 and all(r.height >= 52 for r in rows)
    assert rows[-1].bottom < P.CHORE_DETAIL_BACK_RECT.top
    print(f"CHECKLIST: long list shows {len(rows)}/12 rows + '+{12 - len(rows)} weitere'", flush=True)
    P.close_chore_detail("test")

    # Long item texts: all shown, fully wrapped (smaller font), never cut with "…".
    long_text = "Kühlschrank ausräumen, alle Fächer und die Türdichtung feucht auswischen, abgelaufenes wegwerfen"
    FAKE["status"]["cleaning_chores"][0]["checklist"] = [
        {"item": f"{i + 1}. {long_text}", "done": False} for i in range(5)
    ]
    assert P._moabeats_fetch_status()
    P.open_chore_detail(7)
    wait_idle()
    P.draw_cleaning_day_screen()
    shot("9_long_texts.png")
    assert len(P.CHORE_DETAIL_ROW_RECTS) == 5, "long texts pushed rows off screen"
    font, layout = P._layout_chore_rows(
        FAKE["status"]["cleaning_chores"][0]["checklist"], 300, 400, 8
    )
    assert all(" ".join(lines) == e["item"] for (lines, _), e in zip(layout, FAKE["status"]["cleaning_chores"][0]["checklist"]))
    P.close_chore_detail("test")

    # Start -> Putzdienste on the awake dashboard; the Start button and its
    # menu stay clear of the emergency-exit corner.
    P.DISPLAY_BLANK = False
    P.QUIZ_ENABLED = True
    P.draw_home()
    assert not P.START_BUTTON_RECT.colliderect(exit_zone)
    assert P.handle_tap(*P.START_BUTTON_RECT.center) and P.START_MENU_OPEN
    P.draw_home()
    for rect, action in P.START_MENU_RECTS:
        assert not rect.colliderect(exit_zone), f"Start menu entry {action} in the emergency-exit corner"
    pygame.image.save(P.tft_surf, os.path.join(OUT_DIR, "10_start_menu.png"))
    putz = next(r for r, a in P.START_MENU_RECTS if a == "putz")

    FAKE["status"]["cleaning_chores"][0]["checklist"] = [
        {"item": "Waschbecken", "done": False},
        {"item": "Toilette", "done": True},
    ]
    gets_before = FAKE["gets"]
    assert P.handle_tap(*putz.center)
    assert P.CHORE_LIST_OPEN and not P.START_MENU_OPEN
    wait_idle()
    assert FAKE["gets"] == gets_before + 1, "overlay open did not refetch"
    P.draw_chore_overlay()
    shot("11_overlay_list.png")
    assert [(cid, has) for _, cid, has in P.CLEANING_CHORE_ROW_RECTS] == [(7, True), (8, False)]
    for rect in [r for r, _, _ in P.CLEANING_CHORE_ROW_RECTS] + [P.CHORE_LIST_CLOSE_RECT]:
        assert not rect.colliderect(exit_zone)
    # Müll row and empty space: swallowed, overlay stays, no detail.
    assert P.handle_cleaning_chore_list_click(*P.CLEANING_CHORE_ROW_RECTS[1][0].center)
    assert P.handle_cleaning_chore_list_click(P.DISPLAY_WIDTH // 2, 150)
    assert P.CHORE_LIST_OPEN and P.CHORE_DETAIL_ID is None
    # Bad -> detail, tick, Zurück lands back on the overlay list.
    assert P.handle_cleaning_chore_list_click(*P.CLEANING_CHORE_ROW_RECTS[0][0].center)
    assert P.CHORE_DETAIL_ID == 7
    wait_idle()
    P.draw_chore_overlay()
    tap_item("Waschbecken")
    wait_idle()
    assert FAKE["patches"][-1][:2] == (7, {"item": "Waschbecken", "done": True})
    P.update_chore_screen_timeout()
    assert P.CHORE_DETAIL_ID == 7, "detail on the overlay must survive the awake dashboard"
    P.draw_chore_overlay()
    assert P.handle_chore_detail_click(*P.CHORE_DETAIL_BACK_RECT.center)
    assert P.CHORE_LIST_OPEN and P.CHORE_DETAIL_ID is None
    P.draw_chore_overlay()
    assert P.handle_cleaning_chore_list_click(*P.CHORE_LIST_CLOSE_RECT.center)
    assert not P.CHORE_LIST_OPEN
    # Idle timeout and display blank close the overlay.
    P.open_chore_list()
    wait_idle()
    P.CHORE_DETAIL_LAST_ACTIVITY_TS = time.time() - P.CHORE_DETAIL_IDLE_TIMEOUT_SECONDS - 1
    P.update_chore_screen_timeout()
    assert not P.CHORE_LIST_OPEN
    P.open_chore_list()
    wait_idle()
    P.DISPLAY_BLANK = True
    P.update_chore_screen_timeout()
    assert not P.CHORE_LIST_OPEN
    P.DISPLAY_BLANK = False
    # No chores (e.g. not cleaning day): says so instead of an empty screen.
    saved = FAKE["status"]["cleaning_chores"]
    FAKE["status"]["cleaning_chores"] = []
    P.open_chore_list()
    wait_idle()
    P.draw_chore_overlay()
    shot("12_overlay_empty.png")
    assert P.CLEANING_CHORE_ROW_RECTS == []
    P.close_chore_list("test")
    FAKE["status"]["cleaning_chores"] = saved
    P.DISPLAY_BLANK = True

    # MoaBeats off: the screensaver is just the cleaning-day headline.
    P.config["MOABEATS"]["ENABLED"] = False
    P.draw_cleaning_day_screen()
    shot("14_moabeats_disabled.png")
    assert P.CLEANING_CHORE_ROW_RECTS == [] and P.CHORE_LIST_CLOSE_RECT is None
    P.config["MOABEATS"]["ENABLED"] = True

    server.shutdown()
    print(f"CHECKLIST: {len(FAKE['patches'])} PATCHes, {FAKE['gets']} status GETs against the fake server", flush=True)


# Same length/shape as the WG's real checklists (2026-10-26: up to 8 items,
# ~190-char items, long chore names, a link) - made-up text, public repo.
REAL_SHAPED_CHORES = [
    {"id": 101, "name": "Bad 1", "full_name": "Badezimmer oben (mit Dusche)", "assigned_to": "A", "checklist": [
        "Ablagen", "Toilette", "Waschbecken und Duschwanne schrubben/entkalken (rot&blau)",
        "Abfluss reinigen (siehe https://www.example.com/watch?v=abcdefghijk)", "Handtuch tauschen",
        "Staubsaugen", "benutzte Tücher/Schwämme (rot&blau) auswaschen", "Blumen gießen"]},
    {"id": 102, "name": "Bad 2", "full_name": "Badezimmer unten (mit Wanne)", "assigned_to": "B", "checklist": [
        "Ablagen", "Toilette", "Spiegelschrank", "Waschbecken und Wanne entkalken", "Handtuch tauschen",
        "Staubsaugen", "benutzte Tücher/Schwämme (rot&blau) auswaschen", "Blumen gießen"]},
    {"id": 103, "name": "Flur", "full_name": "Flurdienst", "assigned_to": "C", "checklist": [
        "Alle gemeinsamen Räume staubsaugen & feucht wischen (nicht zu nass; Pfützen gleich wieder aufwischen!)",
        "Garderobe aufräumen",
        "Gesammelte Badvorleger & Küchentücher aus dem großen Bad bei 60° waschen, aufhängen und wenn wieder "
        "trocken abnehmen (meistens 1-2 Waschgänge nötig)",
        "Staubsauger leeren und sauber machen (Filter raus, unter lauwarmem Wasser ausspülen, gut ausdrücken, "
        "trocknen lassen)",
        "Auffangbehälter vom Staubsauger draußen ausklopfen"]},
    {"id": 104, "name": "Küche", "full_name": "Küchendienst", "assigned_to": "D", "checklist": [
        "Arbeitsplatte", "Schranktüren", "Kochfeld", "Esstisch", "Spülbecken", "Tücher & Schwämme auskochen/tauschen (blau&grün)",
        "Staubsaugen", "Blumen gießen"]},
]


def test_real_checklists_fit():
    """Every sub-item of real-sized checklists is on screen (no "+N weitere"),
    nothing runs off the edge, links are hidden, and the emergency exit is
    off while the detail screen uses the corner band for rows."""
    P.config["MOABEATS"]["ENABLED"] = True
    P.CLEANING_DAY = datetime.datetime.today().weekday()
    P.DISPLAY_BLANK = True
    P.MOABEATS_STATUS = {"cleaning_chores": [
        dict(c, checklist=[{"item": i, "done": n % 2 == 0} for n, i in enumerate(c["checklist"])])
        for c in REAL_SHAPED_CHORES
    ]}
    assert P.emergency_exit_active()
    for chore in REAL_SHAPED_CHORES:
        P.CHORE_DETAIL_ID, P.CHORE_DETAIL_SNAPSHOT = chore["id"], None
        P.CHORE_DETAIL_REFRESHING, P.CHORE_DETAIL_ERROR = False, None
        assert not P.emergency_exit_active(), "emergency exit must be off on the detail screen"
        P.draw_cleaning_day_screen()
        shot(f"real_{chore['id']}.png")
        assert len(P.CHORE_DETAIL_ROW_RECTS) == len(chore["checklist"]), (
            f"{chore['full_name']}: {len(P.CHORE_DETAIL_ROW_RECTS)}/{len(chore['checklist'])} rows shown"
        )
        assert all(r.height >= 52 for r, _ in P.CHORE_DETAIL_ROW_RECTS)
        # Rows keep the original item text (PATCH needs it exactly).
        assert [e["item"] for _, e in P.CHORE_DETAIL_ROW_RECTS] == chore["checklist"]
    P.CHORE_DETAIL_ID = None
    assert P._chore_item_display_text(REAL_SHAPED_CHORES[0]["checklist"][3]) == "Abfluss reinigen"
    print(f"REAL: all {sum(len(c['checklist']) for c in REAL_SHAPED_CHORES)} sub-items of "
          f"{len(REAL_SHAPED_CHORES)} real checklists on screen", flush=True)


def test_no_tap_through_overlays():
    """Regression for the whole class: with any overlay open, a tap where
    the KiezOS desktop has a control (Start, the windows' x/o/_, Mehr...,
    Karte...) must not start that feature underneath - it either belongs to
    the overlay or closes it. (The old pills had exactly this bug: PUTZEN
    through the emotion prompt, AFM through the WiFi QR.)"""
    P.DISPLAY_BLANK = False
    P.WIFI_ENABLED = P.GAMES_ENABLED = P.QUIZ_ENABLED = True
    P.config["MOABEATS"]["ENABLED"] = True
    P.close_start_menu()
    P.draw_home()  # desktop rects as drawn with nothing open
    targets = {"Start": P.START_BUTTON_RECT.copy(), "Mehr": P.HOME_RECTS["mehr"].copy()}
    if "karte" in P.HOME_RECTS:
        targets["Karte"] = P.HOME_RECTS["karte"].copy()
    for name, win in P.HOME_WINDOWS.items():
        for glyph, rect in P.K.title_buttons(win).items():
            if glyph != "bar":
                targets[f"{name} {glyph}"] = rect.copy()

    def reset():
        P.EMOTION_PROMPT_VISIBLE = P.EMOTION_RESULTS_VISIBLE = P.EMOTION_CONFIRMATION_VISIBLE = False
        P.QUIZ_STAGE = None
        P.WIFI_QR_VISIBLE = P.MERZ_VISIBLE = P.CHORE_LIST_OPEN = P.SHUTDOWN_VISIBLE = False
        P.CHORE_DETAIL_ID = P.EGG = P.DADA = None
        P.MINIMIZED.clear()
        P.SEV_UNTIL = 0.0
        P.close_games("test-reset")
        P.close_start_menu()
        P.close_home_window("test-reset")

    def features():
        return {
            "quiz": P.QUIZ_STAGE is not None, "wifi": P.WIFI_QR_VISIBLE, "merz": P.MERZ_VISIBLE,
            "games": P.GAMES_MENU_OPEN or P.ACTIVE_GAME is not None,
            "chores": P.CHORE_LIST_OPEN, "results": P.EMOTION_RESULTS_VISIBLE,
            "start": P.START_MENU_OPEN, "window": P.HOME_WINDOW is not None, "dada": P.DADA is not None,
            "minimized": bool(P.MINIMIZED), "sev": P.SEV_UNTIL > time.time(),
        }

    overlays = {
        "emotion prompt": lambda: setattr(P, "EMOTION_PROMPT_VISIBLE", True),
        "wifi qr": lambda: setattr(P, "WIFI_QR_VISIBLE", True),
        "stats qr": lambda: setattr(P, "EMOTION_RESULTS_VISIBLE", True),
        "chore overlay": lambda: setattr(P, "CHORE_LIST_OPEN", True),
        "games menu": P.open_games_menu,
        "shutdown gag": lambda: setattr(P, "SHUTDOWN_VISIBLE", True),
        "egg": lambda: setattr(P, "EGG", "bluescreen0"),
    }
    checked = 0
    for overlay_name, open_overlay in overlays.items():
        for target_name, rect in targets.items():
            reset()
            open_overlay()
            P.tft_surf.fill(P.BLACK)
            P.draw_home()
            P.draw_dashboard_overlays()
            if overlay_name == "chore overlay":
                wait_idle()
            # Not dismiss_emotion_prompt()/a choice: those would log a real event.
            if overlay_name == "emotion prompt":
                P.EMOTION_ACTION_RECTS = {}
                P.EMOTION_BUTTON_RECTS = P.EMOTION_CUSTOM_BUTTON_RECTS = []
            if overlay_name == "games menu" and any(r.collidepoint(rect.center) for r, _ in P.GAMES_MENU_RECTS):
                continue  # lands on one of spiele.exe's own entries: starting that game is the point
            before = features()
            P.handle_tap(*rect.center)
            after = features()
            # Allowed: the open overlay closing itself. Not allowed: any
            # other feature turning on.
            started = [k for k in after if after[k] and not before[k]]
            assert not started, f"{target_name} tap through {overlay_name} started {started}"
            checked += 1
    reset()
    print(f"TAP-THROUGH: {checked} desktop taps across {len(overlays)} overlays, none leaked", flush=True)


if __name__ == "__main__":
    test_checklist_detail()
    test_real_checklists_fit()
    test_no_tap_through_overlays()
    print(f"ALL PASSED - screenshots in {OUT_DIR}", flush=True)
