# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Raspberry Pi kiosk dashboard (pygame, rendered to a touchscreen) showing weather, Berlin public
transit (BVG) departures, and a lightweight emotion-logging prompt for a shared flat, plus a small
Flask + vanilla-JS web dashboard for browsing the logged emotion/uptime history. Heavily inspired
by [WeatherPi_TFT](https://github.com/LoveBootCaptain/WeatherPi_TFT).

## Running

Layout: entry points at the top level (`PiDashboard.py`, `web_server.py`, `run_dashboard.sh`,
`pidashboard.desktop` - keep them there, the Pi's autostart copy and `config.json["THEME"]` point at
these paths), code in `games/` (one module per game, `games/party_games.py` = shared `_Game` base),
`kiosk/` (KiezOS drawing helpers, Pinnwand, BVG API), `stores/` (JSON logs shared by both processes),
headless tests in `tests/`, manual tools and `play_<game>.py` scripts in `dev/`. Modules import each
other package-qualified (`from games import party_games`, `from kiosk import kiezos as K`); scripts in
`tests/`/`dev/` put the repo root on `sys.path` first.

Tests: `tests/run_all.py [filter ...]` runs every `tests/test_*.py` headless (`SDL_VIDEODRIVER=dummy`,
one process each, assert-based, ~3 min) and prints a summary - run it before every commit.
`dev/check_pir_sensor.py` and `dev/llm_smoke_test.py` are manual smoke-test scripts (real hardware /
real LLM) - run them directly when touching PIR sensor or LLM-classification code.
`tests/test_kiezos_loop.py` runs the real `loop()` headless and drives it with posted touch events (Start
menu, games, detail views, blank/wake, PIR surprise -> emotion prompt); `dev/render_dashboard.py <dir>`
saves a screenshot of every screen (`--fake` renders the README's home screen with made-up data).
Run both after any UI change and look at the screenshots.

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

## Deploying to the Pi

Always `git commit` + `git push` here, then `git pull` on the Pi — never `scp` code changes
directly onto the Pi. The Pi is a `git@github.com:MassEast/pi_dashboard.git` checkout of this same
repo; `scp`ing files there creates an uncommitted, unpushed divergence between the Pi's disk, this
repo, and GitHub that's easy to lose track of and that a later `git pull` on the Pi will refuse to
apply (`... would be overwritten by merge`) until the stray files are dealt with by hand.

After `git pull` on the Pi, restart whichever process actually changed:
- `web_server.py` changes: safe to restart any time, invisible to whoever's using the kiosk
  display. It isn't managed by systemd, so a manual restart needs `setsid` (not just `nohup ... &`)
  to actually detach from the SSH session — otherwise it dies the moment the SSH connection closes:
  `sudo pkill -f 'web_server.py'; sudo setsid ./venv/bin/python3 web_server.py > /tmp/web_server_manual.log 2>&1 < /dev/null &`
- `PiDashboard.py` changes: restarting it is visible on the physical touchscreen (the display
  blanks/reloads) — don't restart it without confirming with Ju first, since someone may be looking
  at it. A full `sudo reboot` restarts both processes cleanly via the `pidashboard.desktop`
  autostart entry and is often simpler than manually managing the foregrounded process, but is
  even more visible/disruptive — same rule applies.
- `pidashboard.desktop` starts `PiDashboard.py` through `run_dashboard.sh`, which restarts it after
  a crash (exit code != 0) but not after the 5-tap emergency exit / ESC (exit 0), and gives up after
  more than 5 crashes in 10 minutes. So once that's deployed, a manual restart is just
  `pkill -f PiDashboard.py` (the wrapper starts it again) — launching a second copy by hand would
  run two dashboards.

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
  bottom of the file: each frame `draw_home()` draws the "KiezOS 161" desktop (a purple 90s-OS look:
  `uhr.exe`, `wetter.exe`, `bvg.exe`, `wg.txt` windows + a taskbar whose Start menu holds every other
  feature) straight onto `tft_surf` (static part cached, rebuilt every 2 s), then
  `draw_dashboard_overlays()` draws whatever popup/fullscreen view is open. All drawing helpers
  (bevels, windows, buttons, the self-drawn pixel icons, 7-segment clock, bus map) live in
  **`kiosk/kiezos.py`**; its palette comes from `themes/kiezos.json`'s `KIEZOS` block. The windows' x/o/_
  title buttons do dadaist things (message boxes, `sev.exe`, a "Bin gleich wieder da." note); o or a
  title-bar double-tap opens the detail views (`HOME_WINDOW`: wetter details, `karte.exe`, big clock).
  `karte.exe` is drawn from `config.json["BVG"]["MAP"]` (gitignored on purpose: it shows where the WG
  is); each BVG row also carries `label`/`landmark`. PIR wakes can show a surprise (`EGGS` config,
  1 in `ONE_IN`), the emotion prompt waits until it's closed. Touch
  input, PIR-sensor motion (via `RPi.GPIO`, optional — falls back gracefully off-Pi), display
  blank/wake (via `xset`), and the emotion-prompt state machine are all handled inline in that
  same loop via module-level globals (no class/state-object — this file is a single flat script,
  not a framework app).
- **`web_server.py`** — separate Flask process serving `web/` (static HTML/JS/CSS, no build step,
  Chart.js from a CDN) plus a small JSON API (`/api/emotions/raw`, `/api/emotions/bars`,
  `/api/emotions/catalog`, `/api/uptime`) that reads and aggregates the same store files
  `PiDashboard.py` writes to.
- **`stores/emotion_store.py`** / **`stores/uptime_store.py`** — the shared persistence layer: append-only JSON
  event logs (one file each) with a lock-protected read-modify-write-via-tmp-file-then-`os.replace`
  pattern for crash-safety, plus a corrupt-file quarantine/recovery path. `stores/emotion_store.py`'s
  store filename is parameterized (`store_file=` kwarg, defaulting to `STORE_FILE`) specifically so
  callers can point at an alternate/archived event log (e.g. `ARCHIVE_STORE_FILE`) without
  duplicating the read/aggregation logic.
- **`kiosk/bvg.py`** — thin wrapper around the BVG (Berlin transit) `v6.bvg.transport.rest` API,
  used only by `PiDashboard.py`.
- **MoaBeats integration** (optional, config-gated via `config.json["MOABEATS"]["ENABLED"]`) —
  `PiDashboard.py` polls an external MoaBeats WG-chores instance's `GET /api/display/status` and
  renders it two ways: a small always-on status band (`draw_moabeats_panel()`, with per-line
  scrolling instead of truncation for overflowing content) and one "Putzdienste" screen
  (`draw_chore_screen()`) listing `cleaning_chores` (Putzplan, not completed, due today or
  overdue). That screen is both the `CLEANING_DAY` screensaver (plus "IT'S CLEANING DAY, YAY!")
  and an overlay opened any day via Start -> Putzdienste. Chores with
  a checklist show `done/total` and open a detail screen on tap (`draw_chore_detail()`), which
  ticks/unticks sub-items via `PATCH /api/display/chores/{id}/checklist` — tick only, completing
  a chore stays in the app on purpose. `tests/test_moabeats_checklist.py` tests it headless against
  `tests/fake_moabeats_server.py`, which also runs standalone for a local look (point
  `MOABEATS.API_URL` at it; never test ticking against the real instance).
- **Spiele** — Start -> Spiele opens a submenu with the config `GAMES.FEATURED` games (one of them,
  rotating daily, as "Spiel des Tages", `games_menu_split()`) plus "Alle Spiele...", which opens the
  `spiele.exe` window (also where a game's MENÜ button leads): one scrollable list of all games
  (`games_menu_layout()`: daily, favourites, "Weitere Spiele" heading, the rest), scrolled by dragging
  or the scrollbar arrows; a card starts its game on finger-up without scrolling
  (`handle_games_menu_release()`, routed from MOUSEBUTTONUP). The games: MERZ
  (in `PiDashboard.py`) plus the party games, all behind one `GAMES` config section: STAPEL-TURM and
  FLAPPY BVG (`games/party_games.py`), ENTEIGNEN! (`games/enteignen.py`, swipe-to-cut), KIEZBLOCK
  (`games/kiezblock.py`), TIC-TAC-DADA (`games/tictacdada.py` + `games/tictacdada_lines.py`, 2 players with the
  WG's MoaBeats avatars; special lines naming real people only in config `GAMES.TICTACTOE`),
  PATRIAPUTT (`games/patriaputt.py`, brick-breaker), KIEZ KAPERN (`games/kiezkapern.py`, tap-to-drive
  Kiez sandbox), KIEZ-KURIER (`games/kiezkurier.py`, daily route puzzle seeded by the date, own
  `IDLE_TIMEOUT_SECONDS` class attribute read by `update_games_timeout()`) and LASTENRAD-SIMULATOR
  (`games/lastenrad/` package, pymunk physics, spec: docs/future_massive_prompt.txt (local only, gitignored);
  import guarded in PiDashboard so a missing pymunk only disables this game; `GAMES.LASTENRAD.DEBUG`
  shows its physics overlay). Shared `_Game` hooks: `score_key()` (one list per mode), `round_stored()`,
  `entry_image()` (tap a Bestenliste row to see its picture), `NAME_MAX`, `finger()` (raw multi-touch,
  routed from SDL FINGER events), `IDLE_TIMEOUT_SECONDS`; names typed within 2 min are pre-filled. Each is a `party_games._Game` subclass (`update(now)`, `draw(surf)`, `tap(x, y)`,
  optional `drag(x, y)`/`release()` — PiDashboard routes MOUSEMOTION with the finger down and
  MOUSEBUTTONUP to the active game) registered in `PiDashboard.py` with `party_games.GAMES.append`
  and its icon in `kiezos.ICON_MAKERS`. Every finished round (score, time, optional name) is kept via
  `stores/highscore_store.py` (`logs/game_highscores.json`); the KiezOS game-over dialog shows the whole,
  scrollable Bestenliste. Each game has a headless `tests/test_<game>.py`, most a `dev/play_<game>.py`.
- `kiosk/pinnwand.py` — pinnwand.exe: MoaBeats' "pinnwand" chat channel read/written via a guest account
  (config `MOABEATS.PINNWAND_USER/PASSWORD`), opened from the strip at the bottom of wg.txt;
  `tests/test_pinnwand.py` runs against `tests/fake_moabeats_server.py`.
- Night mode (config `NIGHT_MODE`): the finished frame is multiplied with a warm tint in the time
  window (`apply_night_mode()`, once per frame right before `display.update()`; `tests/test_night_mode.py`).
- Two built-in safety mechanisms exist specifically because this runs headless/unattended on a
  touchscreen with no keyboard: an emergency-exit corner tap (top-left corner, 5 rapid taps
  anywhere within the hitbox — deliberately generous, not pixel-exact, because real touchscreen
  taps land with real imprecision) that takes priority over the emotion overlays so it can never get
  swallowed by a popup — but is deliberately *off* while the AFM quiz, MERZ or a party game is open (all
  have their own X + idle timeout, and tapping their buttons near the corner quit the app by
  accident), and a no-internet auto-reboot in `safe_network_monitor()` that is rate
  limited (`NETWORK_REBOOT_COOLDOWN_SECONDS`) so a real upstream outage doesn't turn into a
  reboot loop.
