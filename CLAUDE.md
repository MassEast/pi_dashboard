# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Raspberry Pi kiosk dashboard (pygame, rendered to a touchscreen) showing weather, Berlin public
transit (BVG) departures, and a lightweight emotion-logging prompt for a shared flat, plus a small
Flask + vanilla-JS web dashboard for browsing the logged emotion/uptime history. Heavily inspired
by [WeatherPi_TFT](https://github.com/LoveBootCaptain/WeatherPi_TFT).

## Running

No test suite or linter/build step exists in this repo. `dev/test_pir_sensor.py` and
`dev/llm_smoke_test.py` are manual smoke-test scripts, not an automated suite — run them directly
with `python3` when touching PIR sensor or LLM-classification code.

Setup:
```bash
python3 -m venv venv && source venv/bin/activate
pip3 install -r requirements.txt
cp example.config.json config.json   # then edit config.json — see below
```

Run both processes (they are independent, not managed by one entrypoint):
```bash
python3 web_server.py &     # Flask dashboard, default port 8080
python3 PiDashboard.py      # pygame kiosk app, needs a display (DISPLAY=:0 on the Pi)
```

On the actual Pi, both are autostarted together via `pidashboard.desktop` (XDG autostart entry,
copied to `~/.config/autostart/`), which backgrounds `web_server.py` and foregrounds
`PiDashboard.py`. There is no systemd service — autostart is entirely through the X11/LXDE session
starting that one `.desktop` entry on login.

That `.desktop` entry doesn't redirect `PiDashboard.py`'s stdout/stderr, so when `LOG_TO_FILES` is
`false` (the default — file logging is off by default to spare the SD card), console output isn't
lost, it just isn't in `logs/*.log` either: it goes wherever the X11 session routes autostart-app
output, which for the standard LXDE-pi session is `~/.cache/lxsession/LXDE-pi/run.log`. Check that
file, not `logs/`, when debugging runtime behavior on-device with file logging off.

`config.json["ENV"]` toggles Pi-specific behavior (e.g. `"Pi"` routes the weather cache to
`/mnt/ramdisk` instead of `logs/` to reduce SD card writes; anything else, e.g. `"STAGE"`, is for
local/laptop development).

## Configuration

- `config.json` is gitignored (real API keys, BVG stop IDs, wifi-adjacent secrets never belong in
  the repo) — `example.config.json` is the template to copy from and the reference for what keys
  exist.
- Visual theme (colors, date/time formats) is a *separate* file under `themes/`, referenced by
  path from `config.json["THEME"]`. Don't confuse theme config with app config — colors/fonts go
  in the theme file, everything else (API keys, timers, feature toggles) goes in `config.json`.
- The emotion catalog (`config.json["EMOTION"]["CATALOG"]`) is the source of truth for emotion
  order/emoji/color, editable without code changes — see `dev/add-custom-emotions-plan.md` for the
  design rationale (custom emotions typed on-device get LLM-classified into this catalog, with a
  deterministic `?`/gray fallback if the LLM is disabled or fails).

## Architecture

Two independent long-running Python processes, both reading the same `config.json` and the same
`logs/` directory, but otherwise not talking to each other directly — they only share state
through the JSON files in `logs/`:

- **`PiDashboard.py`** — the pygame kiosk app. One large `while running` loop in `loop()` at the
  bottom of the file: builds up layered `pygame.Surface`s (weather, BVG, dynamic/particles, time,
  emotion overlays) each frame, composites them onto `tft_surf`, and blits to the display. Touch
  input, PIR-sensor motion (via `RPi.GPIO`, optional — falls back gracefully off-Pi), display
  blank/wake (via `xset`), and the emotion-prompt state machine are all handled inline in that
  same loop via module-level globals (no class/state-object — this file is a single flat script,
  not a framework app).
- **`web_server.py`** — separate Flask process serving `web/` (static HTML/JS/CSS, no build step,
  Chart.js from a CDN) plus a small JSON API (`/api/emotions/raw`, `/api/emotions/bars`,
  `/api/emotions/catalog`, `/api/uptime`) that reads and aggregates the same store files
  `PiDashboard.py` writes to.
- **`emotion_store.py`** / **`uptime_store.py`** — the shared persistence layer: append-only JSON
  event logs (one file each) with a lock-protected read-modify-write-via-tmp-file-then-`os.replace`
  pattern for crash-safety, plus a corrupt-file quarantine/recovery path. `emotion_store.py`'s
  store filename is parameterized (`store_file=` kwarg, defaulting to `STORE_FILE`) specifically so
  callers can point at an alternate/archived event log (e.g. `ARCHIVE_STORE_FILE`) without
  duplicating the read/aggregation logic.
- **`utils.py`** — thin wrapper around the BVG (Berlin transit) `v6.bvg.transport.rest` API,
  used only by `PiDashboard.py`.
- Two built-in safety mechanisms exist specifically because this runs headless/unattended on a
  touchscreen with no keyboard: an emergency-exit corner tap (top-left corner, 5 rapid taps
  anywhere within the hitbox — deliberately generous, not pixel-exact, because real touchscreen
  taps land with real imprecision) that always takes priority over any overlay so it can never get
  swallowed by a popup, and a no-internet auto-reboot in `safe_network_monitor()` that is rate
  limited (`NETWORK_REBOOT_COOLDOWN_SECONDS`) so a real upstream outage doesn't turn into a
  reboot loop.
