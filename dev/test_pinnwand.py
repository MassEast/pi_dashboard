#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless checks of pinnwand.exe (pinnwand.py + its PiDashboard wiring)
against dev/fake_moabeats_server.py - never the real MoaBeats chat:
login, fetch (bot reminders hidden, emoji dropped, guest names parsed),
unread badge, open via wg.txt, typing on the keyboard (name + text), send,
wrong password stops retrying (MoaBeats would lock the account).

SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_pinnwand.py [screenshot_dir]
"""

import os
import sys
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame  # noqa: E402

import fake_moabeats_server as fake  # noqa: E402
import PiDashboard as P  # noqa: E402
import pinnwand  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else None
server = fake.start()
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{server.server_port}"


def shot(name):
    if OUT:
        os.makedirs(OUT, exist_ok=True)
        pygame.image.save(P.tft_surf, os.path.join(OUT, f"{name}.png"))


def frame():
    P.update_kiez_timeouts()
    P.draw_home()
    P.draw_dashboard_overlays()


def tap(rect):
    assert P.handle_tap(*pygame.Rect(rect).center), rect
    frame()


def wait(cond, seconds=5):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        time.sleep(0.05)
    assert cond()


def test_parse():
    assert pinnwand.clean("Hallo 🎉 WG ❤️!") == "Hallo WG !"
    assert pinnwand.strip_author({"author": "Gast", "guest": True}) == "Gast"
    assert pinnwand.strip_author({"author": "Oma", "guest": True}) == "Oma (Gast)"
    assert pinnwand.strip_author({"author": "Sam", "guest": False}) == "Sam"
    pw = pinnwand.Pinnwand(URL, "FlurPi", "x")
    assert pw.fetch()
    msgs = pw.messages
    assert [m["id"] for m in msgs] == [1, 3, 4], "bot reminder (2) and emoji-only (5) hidden"
    assert msgs[0]["text"] == "Wer hat die Hafermilch leer gemacht?"
    assert (msgs[2]["author"], msgs[2]["text"], msgs[2]["guest"]) == ("Mo", "Euer Flur ist der schönste in ganz Berlin", True)
    assert pw.unread() == 0, "first fetch only sets the baseline"
    print("PARSE: reminder + emoji-only hidden, guest name parsed", flush=True)


def test_wrong_password_stops():
    before = fake.STATE["logins"]
    pw = pinnwand.Pinnwand(URL, "FlurPi", "falsch")
    assert not pw.fetch() and not pw.fetch()
    assert fake.STATE["logins"] == before + 1, "retried a wrong password"
    assert pw.error == "Login fehlgeschlagen"
    print("LOGIN: wrong password tried once, then stops", flush=True)


def test_offline():
    """No network (the Pi's wifi down): fetch fails quietly, shows the error,
    keeps retrying (no login lock), and the window still draws."""
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listens there now
    pw = pinnwand.Pinnwand(f"http://127.0.0.1:{port}", "FlurPi", "x")
    assert not pw.fetch() and not pw.login_failed
    assert pw.error == "Keine Verbindung zu MoaBeats"
    assert not pw.fetch() and not pw.login_failed, "a connection error must not stop retrying"
    P.PINNWAND = pw
    P.images = P.image_factory(P.ICON_PATH)
    P.DISPLAY_BLANK = False
    P.HOME_CACHE_KEY = None
    frame()
    P.open_home_window("pinnwand")
    frame()
    shot("0_offline")
    P.close_home_window("test")
    print("OFFLINE: no connection -> error shown, keeps retrying, window draws", flush=True)


def test_extremes():
    """Long unbroken words, max-length names/texts, many messages: wrapped
    inside the bubbles/fields, nothing drawn past the window."""
    import datetime
    now = datetime.datetime.now()
    pw = pinnwand.Pinnwand(URL, "FlurPi", "x")
    pw.login_failed = True  # no fetch: keep the made-up messages
    long_word = "https://example.org/" + "x" * 70
    msgs = [{"id": i, "author": "W" * pinnwand.NAME_MAX if i % 3 == 0 else "Kim", "guest": i % 3 == 0,
             "text": (long_word if i % 2 else "Wort " * 40).strip(), "ts": now - datetime.timedelta(days=30 - i)}
            for i in range(pinnwand.FETCH_LIMIT)]
    pw.messages, pw.loaded, pw.seen_id = msgs, True, 0
    P.PINNWAND = pw
    P.images = P.image_factory(P.ICON_PATH)
    P.DISPLAY_BLANK = False
    P.HOME_CACHE_KEY = None
    frame()
    shot("5_extrem_home")
    P.open_home_window("pinnwand")
    frame()
    shot("5_extrem_neueste")
    pw.scroll = pw.max_scroll
    frame()
    shot("5_extrem_aelteste")
    assert pw.max_scroll > 0
    pw.compose = {"name": "W" * pinnwand.NAME_MAX, "text": "M" * pinnwand.TEXT_MAX, "field": "name", "shift": False}
    frame()
    shot("5_extrem_schreiben")
    pw.compose = None
    P.close_home_window("test")
    print("EXTREMES: long words/names/texts, 30 messages render", flush=True)


def test_dashboard_flow():
    P.PINNWAND = pinnwand.Pinnwand(URL, "FlurPi", "x")
    P.PINNWAND.fetch()
    P.images = P.image_factory(P.ICON_PATH)
    P.DISPLAY_BLANK = False
    P.HOME_CACHE_KEY = None
    frame()
    assert "pinnwand" in P.HOME_RECTS
    shot("1_home")

    # someone in the WG writes -> badge
    fake.STATE["messages"].append({"id": 20, "text": "Pizza ist da!", "created_at": "2026-10-31T09:00:00",
                                   "user": {"id": 2, "name": "Sam"}, "is_system": False})
    P.PINNWAND.fetch()
    assert P.PINNWAND.unread() == 1
    P.HOME_CACHE_KEY = None
    frame()
    shot("1b_home_neu")

    tap(P.HOME_RECTS["pinnwand"])
    assert P.HOME_WINDOW == "pinnwand" and P.PINNWAND.unread() == 0
    wait(lambda: not P.PINNWAND.fetching)
    frame()
    shot("2_pinnwand")

    tap(P.PINNWAND.rects["field"])
    assert P.PINNWAND.compose is not None
    keys = lambda: {t: r for r, t in P.PINNWAND.rects["c_keys"]}  # noqa: E731
    tap(P.PINNWAND.rects["c_name"])
    for ch in "oma":
        tap(keys()[ch.upper() if P.PINNWAND.compose["shift"] else ch])
    tap(P.PINNWAND.rects["c_text"])
    for ch in "hallo wg":
        tap(keys()[" " if ch == " " else (ch.upper() if P.PINNWAND.compose["shift"] else ch)])
    tap(keys()["!"])
    assert P.PINNWAND.compose["name"] == "Oma", P.PINNWAND.compose
    assert P.PINNWAND.compose["text"] == "Hallo wg!", P.PINNWAND.compose
    shot("3_schreiben")

    tap(P.PINNWAND.rects["c_send"])
    wait(lambda: not P.PINNWAND.sending)
    assert fake.STATE["posts"][-1] == {"text": "Oma: Hallo wg!", "channel": "pinnwand"}, fake.STATE["posts"]
    assert P.PINNWAND.compose is None
    frame()
    assert P.PINNWAND.messages[-1]["author"] == "Oma"
    shot("4_gesendet")

    # emergency-exit corner: nothing of pinnwand.exe is tappable there
    for x in range(0, P.EMERGENCY_EXIT_MAX_X, 10):
        for y in range(0, P.EMERGENCY_EXIT_MAX_Y, 10):
            assert not P.PINNWAND.tap(x, y), (x, y)

    tap(P.PINNWAND.rects["back"])
    assert P.HOME_WINDOW is None and not P.PINNWAND.is_open
    print("FLOW: wg.txt -> pinnwand.exe -> name + text typed -> sent as 'Oma: ...' -> back", flush=True)


tests = [test_parse, test_wrong_password_stops, test_offline, test_extremes, test_dashboard_flow]
for t in tests:
    t()
print(f"All {len(tests)} tests passed", flush=True)
P.quit_all()
