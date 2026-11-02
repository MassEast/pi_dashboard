#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
The dashboard must still start when pymunk isn't installed (a Pi after git
pull, before pip install): LASTENRAD-SIMULATOR is left out, everything else
is there, the favourites menu still draws.

SDL_VIDEODRIVER=dummy .venv/bin/python tests/test_without_pymunk.py
"""

import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules["pymunk"] = None  # makes "import pymunk" raise ImportError

from games import party_games  # noqa: E402
import PiDashboard as P  # noqa: E402

names = [g.NAME for g in party_games.GAMES]
assert "LASTENRAD-SIMULATOR" not in names, names
assert {"ENTEIGNEN!", "KIEZ-KURIER", "TIC-TAC-DADA", "KIEZ KAPERN", "PATRIAPUTT"} <= set(names), names
party_games.configure(tempfile.mkdtemp(prefix="nopymunk_"))
P.images = P.image_factory(P.ICON_PATH)
P.DISPLAY_BLANK = False
P.open_games_menu()
P.draw_games_menu()
assert "LASTENRAD-SIMULATOR" not in [k for _, k in P.GAMES_MENU_RECTS]
print(f"WITHOUT PYMUNK: dashboard starts with {len(names)} games, LASTENRAD-SIMULATOR left out - passed", flush=True)
P.quit_all()
