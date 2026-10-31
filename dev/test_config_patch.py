#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Checks dev/config_patch.py: nested merge keeps untouched keys, replaces
lists, reports changes with secrets hidden, backs up, dry run writes nothing.

.venv/bin/python dev/test_config_patch.py
"""

import contextlib
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config_patch  # noqa: E402

d = tempfile.mkdtemp(prefix="config_patch_")
cfg, patch = os.path.join(d, "config.json"), os.path.join(d, "patch.json")
original = {"MOABEATS": {"ENABLED": True, "API_URL": "u", "DISPLAY_SECRET": "s"},
            "EMOTION": {"COOLDOWN_SECONDS": 600, "CATALOG": [1, 2]}, "THEME": "t"}
json.dump(original, open(cfg, "w"))
json.dump({"MOABEATS": {"PINNWAND_USER": "FlurPi", "PINNWAND_PASSWORD": "geheim"},
           "EMOTION": {"COOLDOWN_SECONDS": 1800},
           "NIGHT_MODE": {"ENABLED": True, "TINT": [255, 150, 90]}}, open(patch, "w"))

out = io.StringIO()
with contextlib.redirect_stdout(out):
    config_patch.main(cfg, patch, dry_run=True)
assert json.load(open(cfg)) == original, "dry run wrote"
assert "geheim" not in out.getvalue() and "PINNWAND_PASSWORD: <missing> -> ***" in out.getvalue(), out.getvalue()

with contextlib.redirect_stdout(out):
    changes = config_patch.main(cfg, patch)
merged = json.load(open(cfg))
assert merged["MOABEATS"] == {"ENABLED": True, "API_URL": "u", "DISPLAY_SECRET": "s", "PINNWAND_USER": "FlurPi", "PINNWAND_PASSWORD": "geheim"}
assert merged["EMOTION"] == {"COOLDOWN_SECONDS": 1800, "CATALOG": [1, 2]} and merged["THEME"] == "t"
assert merged["NIGHT_MODE"]["TINT"] == [255, 150, 90]
assert {c[0] for c in changes} == {"MOABEATS.PINNWAND_USER", "MOABEATS.PINNWAND_PASSWORD", "EMOTION.COOLDOWN_SECONDS", "NIGHT_MODE"}
backups = [f for f in os.listdir(d) if f.startswith("config.json.bak-")]
assert len(backups) == 1 and json.load(open(os.path.join(d, backups[0]))) == original
assert "EMOTION.COOLDOWN_SECONDS: 600 -> 1800" in out.getvalue()

with contextlib.redirect_stdout(io.StringIO()):
    assert config_patch.main(cfg, patch) == [], "second run must be a no-op"
print("All config_patch tests passed", flush=True)
