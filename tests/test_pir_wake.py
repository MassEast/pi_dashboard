#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
PIR motion keeps the panel on: the X server blanks on its own idle timer
(touch only), so every motion must reset it - also while the app thinks the
display is on (bug until 2026-11-03: dark screen while people walked by).
On cleaning day motion is ignored (touch-only wake).

SDL_VIDEODRIVER=dummy .venv/bin/python tests/test_pir_wake.py
"""

import datetime
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PiDashboard as P  # noqa: E402

calls = []
P.os.system = lambda cmd: calls.append(cmd) or 0
P.schedule_emotion_prompt = lambda source: None
P.maybe_start_egg = lambda: None
P.threading.Thread = lambda target: type("T", (), {"start": lambda self: None})()
P.CLEANING_DAY = (datetime.date.today().weekday() + 1) % 7

# app thinks the display is on: X's idle timer must still be reset
P.DISPLAY_BLANK = False
P.on_motion_detected()
assert "xset s reset" in calls and "xset dpms force on" in calls, calls

# app blanked: motion wakes it (same xset calls via wake_display)
calls.clear()
P.DISPLAY_BLANK = True
P.on_motion_detected()
assert not P.DISPLAY_BLANK and "xset dpms force on" in calls, calls

# cleaning day: motion ignored
calls.clear()
P.CLEANING_DAY = datetime.date.today().weekday()
P.DISPLAY_BLANK = True
P.on_motion_detected()
assert P.DISPLAY_BLANK and not calls, calls
print("PIR WAKE: motion resets X idle timer while on, wakes when blank, ignored on cleaning day - passed", flush=True)
os._exit(0)
