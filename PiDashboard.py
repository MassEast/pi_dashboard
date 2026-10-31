#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# MIT License
#
# Copyright (c) 2016 LoveBootCaptain (Stephan Ansorge)
# Additional changes (c) 2025 MassEast
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import datetime
import glob
import hashlib
import json
import locale
import logging
import math
import os
import random
import re
import socket
import subprocess
import sys
import threading
import uuid
import pandas as pd
import time

import pygame
import pygame.gfxdraw
import requests
from PIL import Image, ImageDraw
import qrcode

from emotion_store import append_emotion_event, read_emotion_events
from quiz_store import read_quiz_results, submit_quiz_result
from uptime_store import append_uptime_event, last_channel_is_up
from utils import get_stop_data
import kiezos as K
import party_games
import pinnwand
import enteignen
import games_kiezblock
import tictacdada
import patriaputt
import kiezkapern
import kiezkurier
import lastenrave

# Allow the system to manage blanking
os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "1"

# Use absolute path handling to be safe in autostart contexts
PATH = os.path.dirname(os.path.abspath(__file__)) + "/"
ICON_PATH = PATH + "icons/"
FONT_PATH = PATH + "fonts/"
LOG_PATH = PATH + "logs/"
UPTIME_LOG_PATH = PATH + "logs/"
EMOTION_LOG_PATH = PATH + "logs/"
QUIZ_LOG_PATH = PATH + "logs/"
GAMES_LOG_PATH = PATH + "logs/"  # party_games all-time highscores

# Load config file
config_data = open(PATH + "config.json").read()
config = json.loads(config_data)

# Create logger
logger = logging.getLogger(__package__)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger.setLevel(logging.INFO)

# Create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# Create file handler and set level to info
# for file path, get starting time in nice str format
datetimenow = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
fh = logging.FileHandler(os.path.join(LOG_PATH, f"{datetimenow}.log"))
fh.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# add formatter to ch
ch.setFormatter(formatter)
fh.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(ch)
if config["LOG_TO_FILES"]:
    logger.addHandler(fh)

# PIR Sensor - try to import RPi.GPIO if on Raspberry Pi
try:
    import RPi.GPIO as GPIO

    GPIO_AVAILABLE = True
    logger.info("RPi.GPIO imported successfully - PIR Sensor support enabled")
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning(
        "RPi.GPIO not available - PIR Sensor support disabled (must run on Raspberry Pi)"
    )

theme_config = config["THEME"]

# Parse cleaning day config
days_map = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}
cleaning_day_name = config.get("CLEANING_DAY", "Monday")
CLEANING_DAY = days_map.get(cleaning_day_name, 0)
logger.info(f"Cleaning day set to {cleaning_day_name} ({CLEANING_DAY})")

theme_settings = open(PATH + theme_config).read()
theme = json.loads(theme_settings)

SERVER = config["WEATHERBIT_URL"]
HEADERS = {}
WEATHERBIT_COUNTRY = config["WEATHERBIT_COUNTRY"]
WEATHERBIT_LANG = config["WEATHERBIT_LANGUAGE"]
WEATHERBIT_POSTALCODE = config["WEATHERBIT_POSTALCODE"]
WEATHERBIT_HOURS = config["WEATHERBIT_HOURS"]
WEATHERBIT_DAYS = config["WEATHERBIT_DAYS"]
METRIC = config["LOCALE"]["METRIC"]

locale.setlocale(locale.LC_ALL, (config["LOCALE"]["ISO"], "UTF-8"))

BVG_ROWS = config["BVG"]["ROWS"]
BVG_LOOKAHEAD_MIN = config["BVG"]["LOOKAHEAD_MIN"]
BVG_LOOKBACK_MIN = config["BVG"]["LOOKBACK_MIN"]
# The Kiez map behind bvg.exe's "Karte..." (screen pixels, see
# kiezos.draw_map) - lives only in the gitignored config.json since it shows
# where the WG is; no MAP = no "Karte..." button.
BVG_MAP = config["BVG"].get("MAP")

# icon rotation angle (degrees) per row "icon" value; "double_left" is drawn
# as two overlapping left arrows since there's no dedicated double-arrow asset
BVG_ROW_ICON_ANGLES = {"up": 0, "down": 180, "left": 90, "right": -90}

# MoaBeats (WG chores/shopping/visits) integration - see docs/PI_HANDOVER.md in
# the moabeatstastic repo for the API contract. Disabled/missing config block
# means this whole feature is skipped, no crash.
MOABEATS_STATUS = {"overdue_chores": [], "cleaning_chores": [], "shopping": [], "visits": []}
MOABEATS_STATUS_LOCK = threading.Lock()
# Cleaning-day chore checklist detail screen (tap a chore row on the
# cleaning-day fullscreen) - see open_chore_detail(). Only ticks/unticks
# sub-items via PATCH; completing a chore stays in the MoaBeats app on purpose.
CHORE_DETAIL_ID = None  # id of the open chore, None = list view
CHORE_DETAIL_SNAPSHOT = None  # last seen chore dict, keeps the header if the chore vanishes
CHORE_DETAIL_SESSION = 0  # bumped on every open, so stale worker results are dropped
CHORE_DETAIL_LAST_ACTIVITY_TS = 0.0
CHORE_DETAIL_IDLE_TIMEOUT_SECONDS = 60
CHORE_DETAIL_PENDING_ITEM = None  # item text whose PATCH is in flight
CHORE_DETAIL_REFRESHING = False
CHORE_DETAIL_ERROR = None
CHORE_DETAIL_ROW_RECTS = []  # [(rect, item_dict)] from the last draw
CHORE_DETAIL_BACK_RECT = None
CLEANING_CHORE_ROW_RECTS = []  # [(rect, chore_id, has_checklist)] list rows from the last draw
# Same chore list as a fullscreen overlay on the awake dashboard, opened via
# the "PUTZEN" pill (any day) - see open_chore_list().
CHORE_LIST_OPEN = False
CHORE_BUTTON_RECT = None
CHORE_LIST_CLOSE_RECT = None
CHORE_LIST_TITLE_X = None  # putzdienste.exe's title bar x (same as "Schließen")
CHORE_DETAIL_TITLE_X = None  # the detail window's title bar x (same as "< Zurück")

emotion_cfg = config.get("EMOTION", {})
EMOTION_ENABLED = emotion_cfg.get("ENABLED", True)
EMOTION_COOLDOWN_SECONDS = int(emotion_cfg.get("COOLDOWN_SECONDS", 1800))
EMOTION_CONFIRMATION_SECONDS = int(emotion_cfg.get("CONFIRMATION_SECONDS", 5))
EMOTION_OPTIONS = emotion_cfg.get(
    "EMOTIONS",
    ["stressed", "wild", "relaxed", "sad", "angry", "happy", "anxious", "tired"],
)
EMOTION_CUSTOM_TRIGGER_LABEL = "custom"
EMOTION_CUSTOM_SLOT_COUNT = 3
EMOTION_KEYBOARD_MAX_CHARS = 18
EMOTION_CONFIG_PATH = PATH + "config.json"
EMOTION_DEFAULT_CATALOG_PATH = PATH + "web/emotion_catalog.defaults.json"
EMOTION_LLM_CFG = emotion_cfg.get("LLM", {})
EMOTION_LLM_ENABLED = bool(EMOTION_LLM_CFG.get("ENABLED", False))
EMOTION_LLM_API_KEY = EMOTION_LLM_CFG.get("API_KEY", "")
EMOTION_LLM_MODEL = EMOTION_LLM_CFG.get("MODEL", "claude-3-5-haiku-latest")
EMOTION_LLM_URL = EMOTION_LLM_CFG.get("URL", "https://api.anthropic.com/v1/messages")
EMOTION_LLM_PROMPT_TEMPLATE = EMOTION_LLM_CFG.get(
    "PROMPT_TEMPLATE",
    (
        "You classify emotions for a dashboard and determine their order on a sentiment spectrum.\\n"
        "Return only JSON with keys: name, emoji, color, insert_after.\\n"
        "- name: lowercase emotion label (keep user wording unless clearly wrong)\\n"
        "- emoji: a single emoji (must be unique in catalog)\\n"
        "- color: hex format like #a1b2c3 (green=positive, blue/gray=neutral, red=negative)\\n"
        "- insert_after: emotion name to insert after in the catalog, or null to insert at the very beginning of the catalog. Use this to maintain sentiment order.\\n"
        "\\nCatalog is ordered by sentiment spectrum (most positive → most negative).\\n"
        "Positioning guidance: Determine where the new emotion fits. Return 'insert_after' as the emotion name to place after, or null to insert at the very beginning of the catalog.\\n"
        "\\nSentiment reference: green=positive (grateful, happy, excited), blue/gray=neutral (proud, focused, relaxed, wild, curious, bored, tired), orange/red=negative (anxious, angry, sad, stressed).\\n"
        "\\nCurrent catalog (in order from most positive to most negative):\\n{{catalog_json}}\\n"
        "\\nNew emotion to classify:\\n{{new_emotion_json}}"
    ),
)
EMOTION_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _load_fallback_style_from_config():
    try:
        fallback = config.get("EMOTION", {}).get("FALLBACK_STYLE", {})
        if isinstance(fallback, dict) and "emoji" in fallback and "color" in fallback:
            return fallback
    except Exception:
        pass
    return {"emoji": "?", "color": "#9ca3af"}


EMOTION_FALLBACK_STYLE = _load_fallback_style_from_config()


def _load_default_style_from_shared_catalog():
    try:
        with open(EMOTION_DEFAULT_CATALOG_PATH, "r", encoding="utf-8") as defaults_file:
            catalog = json.load(defaults_file)
    except (OSError, json.JSONDecodeError):
        catalog = []

    defaults = {}
    if isinstance(catalog, list):
        for entry in catalog:
            if not isinstance(entry, dict):
                continue
            name = " ".join(str(entry.get("name", "")).strip().lower().split())
            emoji = entry.get("emoji")
            color = entry.get("color")
            if not name or not isinstance(emoji, str) or not isinstance(color, str):
                continue
            if not EMOTION_COLOR_RE.match(color):
                continue
            defaults[name] = {"emoji": emoji, "color": color}

    if defaults:
        return defaults

    return {
        "happy": {"emoji": "😊", "color": "#16a34a"},
        "relaxed": {"emoji": "😌", "color": "#0ea5e9"},
        "sad": {"emoji": "😢", "color": "#ef4444"},
        "stressed": {"emoji": "😰", "color": "#dc2626"},
        "don't know": {"emoji": "🤷", "color": "#9ca3af"},
    }


EMOTION_DEFAULT_STYLE = _load_default_style_from_shared_catalog()
EMOTION_UNKNOWN_OPTION = "don't know"

web_cfg = config.get("WEB", {})
WEB_ENABLED = web_cfg.get("ENABLED", True)
WEB_HOST = web_cfg.get("HOST", "0.0.0.0")
WEB_PORT = int(web_cfg.get("PORT", 8080))
UPTIME_ENABLED = bool(config.get("LOG_UPTIME", False))


def record_uptime_event(event, source="unknown", reason=None, details=None):
    if not UPTIME_ENABLED:
        return None

    try:
        return append_uptime_event(
            UPTIME_LOG_PATH,
            event,
            source=source,
            reason=reason,
            details=details,
        )
    except Exception as uptime_ex:
        logger.warning(f"Failed to record uptime event {event}: {uptime_ex}")
        return None


NETWORK_AVAILABLE = True
BVG_AVAILABLE = True
WEATHER_AVAILABLE = True


def wake_display(source, reason=None):
    global DISPLAY_BLANK

    if not DISPLAY_BLANK:
        return False

    DISPLAY_BLANK = False
    record_uptime_event("screen_on", source=source, reason=reason)
    logger.info(f"Display woken up by {source}")
    os.system("xset s reset")
    os.system("xset dpms force on")
    if source == "motion":
        maybe_start_egg()
    schedule_emotion_prompt(source)
    threading.Thread(target=BVGUpdate.update_bvg_stop_information).start()
    logger.info("BVG update triggered immediately (out of cycle).")
    return True


class SimpleScheduler:
    """Simple, clean scheduler for weather and BVG updates"""

    def __init__(self):
        self.weather_timer = None
        self.bvg_timer = None
        self.moabeats_timer = None
        self.running = True

    def start_weather_updates(self):
        """Start weather update cycle - combines API call and data processing"""
        if self.weather_timer:
            self.weather_timer.cancel()

        def weather_cycle():
            if not self.running or DISPLAY_BLANK:
                # Reschedule for later if display is blank
                if self.running:
                    self.weather_timer = threading.Timer(60, weather_cycle)  # Check again in 1 min
                    self.weather_timer.start()
                return

            try:
                # Do complete weather update in one cycle
                WeatherUpdate.update_and_process()
                logger.info("Weather cycle completed successfully")
            except Exception as e:
                logger.error(f"Weather cycle failed: {e}")

            # Schedule next cycle. update_and_process() swallows connection errors
            # internally (falls back to the cached JSON, flips WEATHER_AVAILABLE) rather
            # than raising, so a failed fetch looks identical to a successful one here
            # unless we check WEATHER_AVAILABLE - without this, a transient failure (e.g.
            # DNS not ready yet at boot) would wait out the full WEATHER_UPDATE interval
            # (30 min) before retrying instead of self-healing quickly like BVG does.
            if self.running:
                retry_delay = 60 if not WEATHER_AVAILABLE else config["TIMER"]["WEATHER_UPDATE"]
                self.weather_timer = threading.Timer(retry_delay, weather_cycle)
                self.weather_timer.start()

        # Start the cycle
        weather_cycle()

    def start_bvg_updates(self):
        """Start BVG update cycle"""
        if self.bvg_timer:
            self.bvg_timer.cancel()

        def bvg_cycle():
            if not self.running or DISPLAY_BLANK:
                # Reschedule for later if display is blank
                if self.running:
                    self.bvg_timer = threading.Timer(60, bvg_cycle)  # Check again in 1 min
                    self.bvg_timer.start()
                return

            BVGUpdate.update_bvg_stop_information()

            # Schedule next cycle
            if self.running:
                self.bvg_timer = threading.Timer(config["TIMER"]["BVG_UPDATE"], bvg_cycle)
                self.bvg_timer.start()

        # Start the cycle
        bvg_cycle()

    def start_moabeats_updates(self):
        """Start MoaBeats (WG chores/shopping/visits) poll cycle.

        Pauses while DISPLAY_BLANK, same as weather/BVG - except on
        CLEANING_DAY, when the blanked screen is actually showing the
        fullscreen chore reminder (kept forced-on via `xset s reset` in
        loop(), see the CLEANING_DAY branch), so it needs to keep polling
        to stay current through the day instead of freezing on whatever it
        last fetched before blanking.
        """
        if not config.get("MOABEATS", {}).get("ENABLED", False):
            return

        if self.moabeats_timer:
            self.moabeats_timer.cancel()

        interval = config["MOABEATS"].get("POLL_INTERVAL", 300)

        def cycle():
            if not self.running:
                return

            is_cleaning_day = datetime.datetime.today().weekday() == CLEANING_DAY
            if DISPLAY_BLANK and not is_cleaning_day:
                # Reschedule for later, same as weather/BVG - reminder isn't
                # showing right now, no point spending an API call on it.
                self.moabeats_timer = threading.Timer(60, cycle)
                self.moabeats_timer.start()
                return

            _moabeats_fetch_status()
            self.moabeats_timer = threading.Timer(interval, cycle)
            self.moabeats_timer.start()

        cycle()

    def stop_all(self):
        """Clean shutdown of all timers"""
        logger.info("Stopping scheduler - cancelling all timers")
        self.running = False

        if self.weather_timer:
            self.weather_timer.cancel()
            logger.info("Weather timer cancelled")
        if self.bvg_timer:
            self.bvg_timer.cancel()
            logger.info("BVG timer cancelled")
        if self.moabeats_timer:
            self.moabeats_timer.cancel()
            logger.info("MoaBeats timer cancelled")


# Global scheduler instance
scheduler = SimpleScheduler()

NETWORK_REBOOT_MARKER = LOG_PATH + "last_network_reboot"
NETWORK_REBOOT_COOLDOWN_SECONDS = 7200  # don't reboot for no-internet more than once per 2h


def safe_network_monitor():
    """
    Checks for internet connection.
    Only allows reboot if system has been up for >10 minutes to prevent boot loops and give time to
    SSH in. During an extended outage, only reboots once per NETWORK_REBOOT_COOLDOWN_SECONDS -
    rebooting the Pi does nothing for a router/ISP outage, so hammering it every 10 minutes for
    the whole outage just adds pointless SD card wear.
    """

    global NETWORK_AVAILABLE

    # NETWORK_AVAILABLE always starts True on process boot, regardless of what it
    # was before this restart - including restarts caused by this very monitor's
    # own no-internet reboot. If the last event we ever logged was internet_down,
    # that gap must be closed explicitly here; otherwise it silently stays "open"
    # until some unrelated, much-later internet_down/internet_up pair closes it,
    # making that later outage's duration look like it started days earlier than
    # it did. Runs immediately (not after the 10min safety delay below) since it
    # only ever logs, never reboots.
    if not last_channel_is_up(UPTIME_LOG_PATH, "internet_up", "internet_down", default_up=True):
        try:
            requests.get("https://www.google.com", timeout=5)
            record_uptime_event(
                "internet_up",
                source="network_monitor",
                reason="google.com reachable after restart",
            )
            NETWORK_AVAILABLE = True
        except Exception:
            NETWORK_AVAILABLE = False

    logger.info("Network monitor started - 10min safety delay initiated...")
    time.sleep(600)

    while True:
        try:
            # Check connection using a reliable host (Google DNS)
            requests.get("https://www.google.com", timeout=5)
            # If we get here, internet is fine
            if not NETWORK_AVAILABLE:
                record_uptime_event(
                    "internet_up",
                    source="network_monitor",
                    reason="google.com reachable",
                )
                NETWORK_AVAILABLE = True
                retry_fallback_emotion_classifications()
        except Exception:
            if NETWORK_AVAILABLE:
                record_uptime_event(
                    "internet_down",
                    source="network_monitor",
                    reason="google.com unreachable",
                )
                NETWORK_AVAILABLE = False
            logger.warning("Network check failed. Retrying in 30s...")
            time.sleep(30)
            try:
                requests.get("https://www.google.com", timeout=5)
                if not NETWORK_AVAILABLE:
                    record_uptime_event(
                        "internet_up",
                        source="network_monitor",
                        reason="google.com reachable after retry",
                    )
                    NETWORK_AVAILABLE = True
                    retry_fallback_emotion_classifications()
            except Exception:
                last_reboot_age = None
                if os.path.exists(NETWORK_REBOOT_MARKER):
                    last_reboot_age = time.time() - os.path.getmtime(NETWORK_REBOOT_MARKER)

                if (
                    last_reboot_age is not None
                    and last_reboot_age < NETWORK_REBOOT_COOLDOWN_SECONDS
                ):
                    logger.warning(
                        f"Network still down, but already rebooted for this {int(last_reboot_age)}s ago "
                        f"(cooldown {NETWORK_REBOOT_COOLDOWN_SECONDS}s) - skipping reboot this cycle."
                    )
                else:
                    logger.error("Network definitively down. REBOOTING SYSTEM.")
                    if not DISPLAY_BLANK:
                        record_uptime_event(
                            "screen_off",
                            source="network_monitor",
                            reason="system_reboot_requested",
                        )
                    record_uptime_event(
                        "reboot_requested",
                        source="network_monitor",
                        reason="no_internet_connection",
                    )
                    open(NETWORK_REBOOT_MARKER, "w").close()
                    # Sync logs before rebooting
                    if config["LOG_TO_FILES"]:
                        os.system("sync")
                    os.system("sudo reboot")

        # Check every 10 minutes
        time.sleep(600)


# Start the monitor in a background thread
monitor_thread = threading.Thread(target=safe_network_monitor, daemon=True)
monitor_thread.start()
# ---------------------------

UPDATED_BVG_TIME = None
BVG_STOP_INFORMATION = pd.DataFrame(
    columns=["type", "line", "departure", "delay", "direction", "direction_str", "cancelled"]
)

LAST_TOUCH_TIME = time.time()
LAST_MOTION_DETECTED_TIME = time.time()
DISPLAY_BLANK_AFTER = config["TIMER"]["DISPLAY_BLANK"]
DISPLAY_BLANK = False

# Secret corner-tap gesture that plays a random local video clip full-screen.
# Not wired to anything public - DIR points at a gitignored folder that
# only exists locally (see media/ in .gitignore).
SECRET_VIDEO_CONFIG = config.get("SECRET_VIDEO", {})
SECRET_VIDEO_ENABLED = SECRET_VIDEO_CONFIG.get("ENABLED", False)
# Resolved against PATH (script dir), matching every other config-relative
# path in this file (config.json, THEME, ...) - NOT the process's cwd, which
# for the autostarted process is $HOME, not the repo dir.
SECRET_VIDEO_DIR = os.path.join(PATH, SECRET_VIDEO_CONFIG.get("DIR", ""))
SECRET_VIDEO_PLAYER_CMD = SECRET_VIDEO_CONFIG.get(
    "PLAYER_CMD", ["mpv", "--fullscreen", "--really-quiet", "--no-osc"]
)
# Always appended (not user-configurable): handles tap-to-quit and
# hold-to-scrub, see mpv_touch_input.lua. Kept out of PLAYER_CMD so its path
# can be resolved against PATH here rather than baked as a fragile relative
# string in config.json.
SECRET_VIDEO_SCRIPT_ARG = f"--script={PATH}mpv_touch_input.lua"
SECRET_VIDEO_GESTURE_TIMEOUT_SECONDS = SECRET_VIDEO_CONFIG.get("GESTURE_TIMEOUT_SECONDS", 3)
# Order of corners that must be tapped in sequence to trigger playback.
SECRET_VIDEO_GESTURE_SEQUENCE = ["TL", "TR", "BR", "BL"]
secret_video_gesture_progress = 0
secret_video_gesture_last_tap_ts = 0.0
secret_video_last_path = None
# Shuffled "bag" of clips not yet played this cycle - refilled once exhausted
# so every clip is seen once before any repeats (see play_secret_video()).
secret_video_queue = []

# "atzig fotzig mausig" personality quiz (inspired by
# https://atzigfotzigmausig.de/quiz, questions are original) - a TEST button
# opens name entry -> fake biometric scan -> QUIZ_LENGTH random questions ->
# a ternary-plot results screen showing every past participant's dot.
QUIZ_CONFIG = config.get("QUIZ", {})
QUIZ_ENABLED = QUIZ_CONFIG.get("ENABLED", False)

# WLAN QR button next to the clock - tap it to show a scannable WIFI:
# connect QR code for the household's actual wifi, instead of reading the
# password out to every guest. See README for what these keys are for.
WIFI_CONFIG = config.get("WIFI", {})
WIFI_ENABLED = WIFI_CONFIG.get("ENABLED", False)
WIFI_SSID = WIFI_CONFIG.get("SSID", "")
WIFI_PASSWORD = WIFI_CONFIG.get("PASSWORD", "")

# PLAY pill (under WIFI) opens a games menu: MERZ plus the tap-only party
# games in party_games.py. One config section for all of them.
#
# "Merz Leck Eier" - dadaist easter-egg minigame. Tap-to-throw
# eggs/testicles at a pixel-caricature of the chancellor, who wanders/dodges.
# Taunt lines mix his own on-record quotes (sourced, see MERZ_TAUNTS below)
# with plain silly reaction lines - no scoreboard/persistence, just a live
# hit counter for the current session.
GAMES_CONFIG = config.get("GAMES", {})
GAMES_ENABLED = GAMES_CONFIG.get("ENABLED", False)
party_games.GAMES.append(enteignen.EnteignenGame)  # swipe game: needs drag()/release(), see the event loop
party_games.GAMES.append(games_kiezblock.KiezblockGame)
K.ICON_MAKERS["kiezblock"] = games_kiezblock.menu_icon
party_games.GAMES.append(tictacdada.TicTacDadaGame)
K.ICON_MAKERS["tictacdada"] = tictacdada.menu_icon
party_games.GAMES.append(patriaputt.PatriaputtGame)  # brick-breaker: paddle follows drag()
K.ICON_MAKERS["patriaputt"] = patriaputt.menu_icon_surface
party_games.GAMES.append(kiezkapern.KiezKapernGame)  # tap-to-drive Kiez sandbox
K.ICON_MAKERS["kiezkapern"] = kiezkapern.menu_icon
party_games.GAMES.append(kiezkurier.KiezKurierGame)  # daily route puzzle: drag()/release() draw the route
K.ICON_MAKERS["kiezkurier"] = kiezkurier.menu_icon_surface
party_games.GAMES.append(lastenrave.LastenraveGame)  # crane stacking: tap drops, drag() moves the crane
K.ICON_MAKERS["lastenrave"] = lastenrave.menu_icon_surface
# Special win lines (may name real flatmates) live in the gitignored config only.
tictacdada.SPECIAL_LINES = GAMES_CONFIG.get("TICTACTOE", {}).get("SPECIAL_LINES", {})
for _line in tictacdada.SPECIAL_LINES.get("WIN", []):  # config boundary: fail at start, not at a win
    try:
        _line.format(winner="X", loser="O")
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(f"GAMES.TICTACTOE.SPECIAL_LINES.WIN: only {{winner}} and {{loser}} allowed, got {_line!r}") from e

# pinnwand.exe: MoaBeats' Pinnwand chat via its own guest account (pinnwand.py).
_MB = config.get("MOABEATS", {})
PINNWAND = (pinnwand.Pinnwand(_MB["API_URL"], _MB["PINNWAND_USER"], _MB["PINNWAND_PASSWORD"], _MB.get("PINNWAND_POLL_INTERVAL", 60))
            if _MB.get("ENABLED", False) and _MB.get("PINNWAND_USER") else None)
PINNWAND_IDLE_TIMEOUT_SECONDS = 150  # typing takes guests a while
GAMES_IDLE_TIMEOUT_SECONDS = GAMES_CONFIG.get("IDLE_TIMEOUT_SECONDS", 60)
# spiele.exe shows only these (config order; one of them is "Spiel des Tages",
# rotating daily) plus a "Mehr Spiele..." folder with the rest: a clear "play
# THIS now" instead of a 100-in-1 game box. Names = game NAMEs, "MERZ" for MERZ.
GAMES_FEATURED = GAMES_CONFIG.get("FEATURED", ["ENTEIGNEN!", "KIEZ-KURIER", "LASTENRAVE", "TIC-TAC-DADA", "KIEZ KAPERN", "PATRIAPUTT"])
party_games.configure(GAMES_LOG_PATH)
# Frame rate while a game is open - the dashboard's own DISPLAY.FPS is
# kept low (10 on the Pi) to save CPU, which makes taps/throws feel laggy
# in the games. All game motion is dt-based, so only smoothness changes.
GAMES_FPS = GAMES_CONFIG.get("FPS", 30)
QUIZ_LENGTH = 13
QUIZ_NAME_MAX_CHARS = 16
QUIZ_SCAN_SECONDS = 8.0  # of actual held time, not wall-clock (see QUIZ_SCAN_HELD)
# Resets on every tap (see handle_quiz_click) - too low and people get kicked
# out mid-question while still reading/deciding, not actually idle.
QUIZ_IDLE_TIMEOUT_SECONDS = QUIZ_CONFIG.get("IDLE_TIMEOUT_SECONDS", 90)
# Frame rate while the AFM test is open (any stage) - smoother drag-panning
# on the results triangle than the dashboard's own low DISPLAY.FPS.
QUIZ_FPS = QUIZ_CONFIG.get("FPS", 20)
# Each question has exactly 3 options, one per axis - order within a question
# is intentionally varied so the axis can't be guessed from button position.
QUIZ_QUESTION_BANK = [
    {
        "text": "Jemand schneidet dir an der Kasse die Schlange. Du...",
        "options": [
            {"label": "sagst nix, ärgerst dich innerlich", "axis": "mausig"},
            {"label": "motzt direkt drauf los", "axis": "atzig"},
            {"label": "fragst keck, ob sie's eilig haben", "axis": "fotzig"},
        ],
    },
    {
        "text": "Dein Putzplan-Status laut MoaBeats?",
        "options": [
            {"label": "längst erledigt, heimlich", "axis": "mausig"},
            {"label": "mach ich wenn ich Bock hab", "axis": "atzig"},
            {"label": "verhandle meinen Dienst gegen Gefallen", "axis": "fotzig"},
        ],
    },
    {
        "text": "Wie flirtest du?",
        "options": [
            {"label": "gar nicht, ich werd rot", "axis": "mausig"},
            {"label": "direkt fragen", "axis": "atzig"},
            {"label": "doppeldeutige Kommentare", "axis": "fotzig"},
        ],
    },
    {
        "text": "Dein Ton in der WG-Gruppe?",
        "options": [
            {"label": 'Herzchen und "passt das für alle?"', "axis": "mausig"},
            {"label": "CAPS LOCK und viele Ausrufezeichen", "axis": "atzig"},
            {"label": "Ironie mit Emojis, viel Subtext", "axis": "fotzig"},
        ],
    },
    {
        "text": "Ein Kompliment bekommst du.",
        "options": [
            {"label": "guckst weg, murmelst danke", "axis": "mausig"},
            {"label": '"ich weiß"', "axis": "atzig"},
            {"label": "gibst es doppelt zurück", "axis": "fotzig"},
        ],
    },
    {
        "text": "Sex-/Dating-Storys im Gruppenchat - dein Beitrag?",
        "options": [
            {"label": "liest nur mit", "axis": "mausig"},
            {"label": "postet unkommentiert ein Meme dazu", "axis": "atzig"},
            {"label": "liefert die detaillierteste Story im Chat", "axis": "fotzig"},
        ],
    },
    {
        "text": "Du merkst, der Herd ist noch an - 2 Straßen weiter.",
        "options": [
            {"label": "Panik, sofort umdrehen", "axis": "mausig"},
            {"label": "whatever, wird schon", "axis": "atzig"},
            {
                "label": "postest in der WG-Gruppe, dass es eine Belohnung gibt, wer den Herd rettet",
                "axis": "fotzig",
            },
        ],
    },
    {
        "text": "Dein Statement zum heutigen Test hier?",
        "options": [
            {"label": '"musste mich überreden lassen"', "axis": "mausig"},
            {"label": '"wollt ich eh grad machen"', "axis": "atzig"},
            {"label": '"hab schon 3 Freund*innen reingezogen"', "axis": "fotzig"},
        ],
    },
    # --- Candidates ported from atzigfotzigmausig.de/quiz, axis mapping is our own
    # editorial guess (the site doesn't expose its mapping to the client) - pick
    # a subset together and drop the rest, see chat for context.
    {
        "text": "Wer ist dein*e Kindheitsheld*in?",
        "options": [
            {"label": "Balu (Das Dschungelbuch)", "axis": "mausig"},
            {"label": "Rémy (Ratatouille)", "axis": "atzig"},
            {"label": "Pippi Langstrumpf", "axis": "fotzig"},
        ],
    },
    {
        "text": "Wenn in Berlin, clubbe ich hier.",
        "options": [
            {"label": "Sisyphos", "axis": "mausig"},
            {"label": "Berghain", "axis": "atzig"},
            {"label": "KitKatClub", "axis": "fotzig"},
        ],
    },
    {
        "text": "Dein Celebrity Crush?",
        "options": [
            {"label": "Tom Holland", "axis": "mausig"},
            {"label": "Margot Robbie", "axis": "atzig"},
            {"label": "Harry Styles", "axis": "fotzig"},
        ],
    },
    {
        "text": "Wie kommst du von A nach B?",
        "options": [
            {"label": "Spazieren", "axis": "mausig"},
            {"label": "E-Roller", "axis": "atzig"},
            {"label": "Uber", "axis": "fotzig"},
        ],
    },
    {
        "text": "Was ist am ehesten dein Lieblingsessen?",
        "options": [
            {"label": "Pfannkuchen", "axis": "mausig"},
            {"label": "Bratwurst", "axis": "atzig"},
            {"label": "Sushi", "axis": "fotzig"},
        ],
    },
    {
        "text": "Dein nächster Urlaub geht...",
        "options": [
            {"label": "ins Allgäu", "axis": "mausig"},
            {"label": "auf Malle", "axis": "atzig"},
            {"label": "nach Marseille", "axis": "fotzig"},
        ],
    },
    {
        "text": "Was machst du Sonntags?",
        "options": [
            {"label": "Babysitten", "axis": "mausig"},
            {"label": "Auskatern", "axis": "atzig"},
            {"label": "Sektbrunch", "axis": "fotzig"},
        ],
    },
    {
        "text": "Sport deiner Wahl?",
        "options": [
            {"label": "Pilates", "axis": "mausig"},
            {"label": "Ballsport", "axis": "atzig"},
            {"label": "Reiten", "axis": "fotzig"},
        ],
    },
    {
        "text": "Welches Spaßgetränk trinkst du am liebsten?",
        "options": [
            {"label": "Voelkel Biozischhh", "axis": "mausig"},
            {"label": "Club Mate", "axis": "atzig"},
            {"label": "Iced Matcha Latte", "axis": "fotzig"},
        ],
    },
    {
        "text": "Diese Blumen bekomme ich am liebsten geschenkt.",
        "options": [
            {"label": "Tulpen", "axis": "mausig"},
            {"label": "Lilien", "axis": "atzig"},
            {"label": "Fleischfressende Pflanze", "axis": "fotzig"},
        ],
    },
    {
        "text": "Hier hatte ich das letzte Mal Sex.",
        "options": [
            {"label": "Zu Hause im Bett", "axis": "mausig"},
            {"label": "Im Auto", "axis": "atzig"},
            {"label": "Auf der Clubtoilette", "axis": "fotzig"},
        ],
    },
    {
        "text": "Was zockst du am liebsten?",
        "options": [
            {"label": "Animal Crossing", "axis": "mausig"},
            {"label": "GTA", "axis": "atzig"},
            {"label": "Sims", "axis": "fotzig"},
        ],
    },
    {
        "text": "Das kaufe ich beim Baumarkt.",
        "options": [
            {"label": "Ohrenschutz", "axis": "mausig"},
            {"label": "Bohrhammer", "axis": "atzig"},
            {"label": "ein Seil", "axis": "fotzig"},
        ],
    },
    {
        "text": "Reality-TV gucke ich...",
        "options": [
            {"label": "Love is Blind", "axis": "mausig"},
            {"label": "Berlin - Tag & Nacht", "axis": "atzig"},
            {"label": "Too Hot to Handle", "axis": "fotzig"},
        ],
    },
    {
        "text": "Was machst du, wenn der Kontrolleur kommt?",
        "options": [
            {"label": "ich zeig natürlich mein Ticket", "axis": "mausig"},
            {"label": "ich binde meine Schnürsenkel um zu sprinten", "axis": "atzig"},
            {"label": "ich rede mich gekonnt raus", "axis": "fotzig"},
        ],
    },
    {
        "text": "Das will ich mir im Kino ansehen.",
        "options": [
            {"label": "Zootopia 2", "axis": "mausig"},
            {"label": "Die Odyssee", "axis": "atzig"},
            {"label": "Wuthering Heights (Sturmhöhe)", "axis": "fotzig"},
        ],
    },
    {
        "text": "Das nimmst du dir aus der Backwarenabteilung.",
        "options": [
            {"label": "Bio Sauerteigweck", "axis": "mausig"},
            {"label": "Schoggokrossong", "axis": "atzig"},
            {"label": "Eclair", "axis": "fotzig"},
        ],
    },
    {
        "text": "Beim ersten Date tust du am liebsten...",
        "options": [
            {"label": "Spaziergang im Park", "axis": "mausig"},
            {"label": "Macker im Billard abziehen", "axis": "atzig"},
            {"label": "Cocktailbar", "axis": "fotzig"},
        ],
    },
    {
        "text": "Welches Kleidungsstück passt zu deinem Stil?",
        "options": [
            {"label": "gestrickter Pullover", "axis": "mausig"},
            {"label": "Jeans", "axis": "atzig"},
            {"label": "Croptop", "axis": "fotzig"},
        ],
    },
    {
        "text": "Welche Schuhe ziehst du an?",
        "options": [
            {"label": "Loafers", "axis": "mausig"},
            {"label": "Dr. Martens", "axis": "atzig"},
            {"label": "Cowboy Boots", "axis": "fotzig"},
        ],
    },
    {
        "text": "Deine Rolle im Gruppenprojekt?",
        "options": [
            {"label": '"welches Gruppenprojekt?"', "axis": "mausig"},
            {"label": "ich mach alles", "axis": "atzig"},
            {"label": "yappen", "axis": "fotzig"},
        ],
    },
    {
        "text": "Wen hörst du am liebsten?",
        "options": [
            {"label": "Mark Forster", "axis": "mausig"},
            {"label": "SSIO", "axis": "atzig"},
            {"label": "Mama Ikkimel", "axis": "fotzig"},
        ],
    },
    {
        "text": "Einkaufsladen of choice?",
        "options": [
            {"label": "dm", "axis": "mausig"},
            {"label": "Netto", "axis": "atzig"},
            {"label": "Bioladen", "axis": "fotzig"},
        ],
    },
    {
        "text": "Welches Musikgenre hast du zuletzt gehört?",
        "options": [
            {"label": "Pop oder R&B", "axis": "mausig"},
            {"label": "Metal oder Techno", "axis": "atzig"},
            {"label": "Jazz oder Klassik", "axis": "fotzig"},
        ],
    },
    {
        "text": "Beziehungsstatus?",
        "options": [
            {"label": "langjährige Beziehung", "axis": "mausig"},
            {"label": "Single", "axis": "atzig"},
            {"label": "F+ oder Situationship", "axis": "fotzig"},
        ],
    },
    {
        "text": "Wo bist du im Club?",
        "options": [
            {"label": "ich passe auf die Getränke auf", "axis": "mausig"},
            {"label": "vorne links, wo die Musik am besten schallert", "axis": "atzig"},
            {"label": "ich lege auf, na klar", "axis": "fotzig"},
        ],
    },
    {
        "text": "Was ist dein meistbenutztes Emoji?",
        "options": [
            {"label": "keine Emojis", "axis": "mausig"},
            {
                "icons": ["quiz_emoji_hug", "quiz_emoji_point_right", "quiz_emoji_point_left"],
                "axis": "atzig",
            },
            {"icons": ["quiz_emoji_devil", "quiz_emoji_heart_fire"], "axis": "fotzig"},
        ],
    },
]
# Cycled one-at-a-time during the fake "biometric" scan animation - purely
# decorative, not real analysis of anything.
QUIZ_SCAN_MESSAGES = [
    "ANALYSIERE MUNDWINKEL-ASYMMETRIE...",
    "MESSE SCHNAPPATMUNGS-FREQUENZ...",
    "KALIBRIERE AURA-SÄTTIGUNG...",
    "MESSE DAUMENDRUCK IN NEWTON...",
    "INTERPOLIERE VIBE...",
    "VIBE ZU GROSS FÜR INT32 - RUNDE AB...",
    "PRÜFE KAFFEEBEDARF...",
    "ENTSCHLÜSSLE HANDSCHRIFT DER SEELE...",
    "SYNCHRONISIERE MIT MOND...",
    "ZÄHLE INNERE DÄMONEN...",
    "FRAGE NACHBAR*INNEN OB DAS OK IST...",
    "BIOMETRIE: 87% MENSCH, 13% VIBES...",
    "FINGERABDRUCK ERKANNT: 3.5 DAUMEN...",
    "STARTE PERSÖNLICHKEITS-ROULETTE...",
]
QUIZ_AXIS_COLOR = {"mausig": (110, 160, 255), "atzig": (255, 90, 90), "fotzig": (255, 150, 60)}

# QUIZ_STAGE: None (inactive) -> "name" -> "scan" -> "question" -> "results".
QUIZ_STAGE = None
QUIZ_LAST_ACTIVITY_TS = 0.0
# Emergency-exit corner hitbox (5 taps quits the app, see loop()) - shared
# constants so overlays can keep their buttons out of it: a button placed
# in this zone turns "tap it a few times" into quitting the app.
EMERGENCY_EXIT_MAX_X = 100
EMERGENCY_EXIT_MAX_Y = 180
QUIZ_BUTTON_RECT = None
QUIZ_NAME_TEXT = ""
QUIZ_NAME_RECTS = []
QUIZ_NAME_ACTION_RECTS = {}
QUIZ_SCAN_OPENED_AT = 0.0
# Hold-to-scan: progress and animation only advance while a finger is held
# down on the thumbprint icon (see draw_quiz_scan_stage()); released time
# doesn't count and doesn't reset progress, it just pauses.
QUIZ_SCAN_HELD = False
QUIZ_SCAN_HELD_SECONDS = 0.0
QUIZ_SCAN_LAST_TICK = 0.0
QUIZ_SCAN_THUMB_CENTER = None
QUIZ_SCAN_THUMB_RADIUS = 0
QUIZ_MATRIX_FONT = None
QUIZ_MATRIX_COLUMNS = []
# Shuffled per scan session in start_quiz_scan() - QUIZ_SCAN_MESSAGES itself
# stays in its declared order, otherwise every scan cycles the exact same
# messages in the exact same order starting from index 0.
QUIZ_SCAN_MESSAGES_SESSION = []
QUIZ_QUESTIONS = []
QUIZ_QUESTION_INDEX = 0
QUIZ_ANSWER_RECTS = []
QUIZ_VOTES = {"mausig": 0, "atzig": 0, "fotzig": 0}
QUIZ_OWN_RESULT = None
QUIZ_ALL_RESULTS = []
# Other participants' names only show while their dot is held down, to keep
# the triangle from turning into label soup - see draw_quiz_results_stage()
# and the "results" branch of handle_quiz_click()/the MOUSEBUTTONUP handler.
QUIZ_RESULTS_DOT_HITBOXES = []
# Keyed by the dot's rounded screen position, not name - identical scores
# from different people land on the exact same pixel and would otherwise
# render as one indistinguishable dot; grouping by position lets the hold
# label list every name sharing that point instead of hiding all but one.
QUIZ_RESULTS_HELD_KEY = None
QUIZ_RESULTS_ACTION_RECTS = {}
# Zoom on the results triangle via the +/- buttons, pan by dragging. The
# view center is stored in *unzoomed* screen coordinates, so it stays valid
# as the zoom level changes - see draw_quiz_results_stage().
QUIZ_RESULTS_ZOOM = 1.0
QUIZ_RESULTS_ZOOM_MAX = 8.0
QUIZ_RESULTS_VIEW_CENTER = None
QUIZ_RESULTS_VIEW = None  # {"plot_center", "center", "zoom", "plot_rect"} from the last draw
# Press on empty plot space: dragging pans the zoomed view (see
# handle_quiz_results_motion()); a plain tap does nothing.
QUIZ_RESULTS_DRAG = None  # {"start": (x, y), "center": view center at press, "moved": bool}
QUIZ_RESULTS_DRAG_THRESHOLD_PX = 8

WIFI_BUTTON_RECT = None
WIFI_QR_VISIBLE = False
WIFI_QR_OPENED_AT = 0.0
WIFI_QR_AUTO_CLOSE_SECONDS = 20

# --- PLAY menu / party games state ---
PLAY_BUTTON_RECT = None
GAMES_MENU_OPEN = False
GAMES_MENU_RECTS = []  # (rect, key) - key "merz" or a party_games class NAME
GAMES_MENU_PAGE = "main"  # "main" (Spiel des Tages + favourites) or "more" (the folder)
GAMES_MENU_BACK_RECT = None
GAMES_MENU_CLOSE_RECT = None
GAMES_MENU_TITLE_X = None
ACTIVE_GAME = None  # a running party_games game object
GAMES_LAST_ACTIVITY_TS = 0.0

# --- MERZ minigame state ---
MERZ_VISIBLE = False
MERZ_LAST_ACTIVITY_TS = 0.0
MERZ_ACTION_RECTS = {}
MERZ_PROJECTILE_KIND = "egg"  # or "testicle", flipped via the in-game toggle
MERZ_HITS = 0
MERZ_WIN_HITS = 69
MERZ_EXPLODED = False  # True once MERZ_WIN_HITS is reached - see the win/replay flow
MERZ_EXPLODED_AT = 0.0  # set the instant MERZ_EXPLODED flips True, see MERZ_WIN_TEXT_DELAY_SECONDS
# The banner/replay-button text used to appear the same frame as the burst,
# which meant it covered up the egg/testicle/flame particles flying out of
# him before you'd even seen them go off - hold it back a couple seconds so
# the burst itself is the first thing visible.
MERZ_WIN_TEXT_DELAY_SECONDS = 2.0
# How long the "MERZ HAT EIER GELECKT!" banner stays before the result panel
# (name entry / Bestenliste) replaces it.
MERZ_RESULT_DELAY_SECONDS = 3.0
# All-time top 5 by time (party_games.MerzResult, lower is better): the clock
# starts with the first throw/flame, not when the game opens, so reading
# the taunts before starting doesn't cost anything.
MERZ_TIMER_STARTED_AT = None
MERZ_WIN_SECONDS = 0.0
MERZ_RESULT = None  # party_games.MerzResult once the win banner delay passed
MERZ_EXPLOSION_PARTICLES = []  # each: {x, y, vx, vy, kind, started_at}
MERZ_FLAME_PARTICLES = []  # each: {x, y, vx, vy, started_at} - see MERZ_FLAME_LIFETIME_SECONDS
MERZ_FLAME_LIFETIME_SECONDS = 1.0
# A magazine per projectile kind rather than one shared pool, so running out
# of eggs doesn't also block testicles - full capacity 10, regenerating
# continuously (not a discrete reload timer/event) at one shot every 5s
# (was 60s/10 = 6s/shot originally, then briefly 15s/10 = 1.5s/shot which
# felt too twitchy - see MERZ_AMMO_HIT_REFUND below for the other way to
# get ammo back faster than passive regen).
MERZ_AMMO_MAX = 10.0
MERZ_AMMO_REGEN_PER_SEC = 1.0 / 5.0
MERZ_AMMO_HIT_REFUND = 1.0  # landing a hit refunds the shot that scored it
MERZ_AMMO = {"egg": MERZ_AMMO_MAX, "testicle": MERZ_AMMO_MAX}
# Easter egg: tapping the ammo pills EIER, KLÖTEN x3, EIER, KLÖTEN x2
# ("1312") in quick succession unlocks a hidden "BURN" pill in the middle -
# a flamethrower with no ammo limit, firing for as long as the finger is
# held down (see handle_merz_click()/handle_merz_release()). Only lasts for
# the current game - every new game, including "NOCHMAL SPIELEN", resets it.
MERZ_BURN_COMBO = ["egg", "testicle", "testicle", "testicle", "egg", "testicle", "testicle"]
MERZ_BURN_COMBO_MAX_GAP_SECONDS = 1.2  # max pause between two combo taps
MERZ_BURN_COMBO_TAPS = []  # recent pill taps: (kind, ts)
MERZ_BURN_UNLOCKED = False
MERZ_BURN_HELD = False
MERZ_BURN_PARTICLES = []  # each: {x, y, vx, vy, started_at, lifetime}
MERZ_BURN_SPAWN_PER_SEC = 55.0
MERZ_BURN_SPAWN_CARRY = 0.0  # fractional spawn count carried between frames
MERZ_BURN_SPEED = 430.0  # px/sec
# Every flame particle that reaches him scores (Ju's call - BURN is the
# secret fast lane; such rounds get a flame mark in the Bestenliste, see
# MERZ_BURN_SCORED).
MERZ_BURN_SCORED = False  # any flame hit this round
# Position is in the overlay's own coordinate space (DISPLAY_WIDTH/HEIGHT,
# it's drawn full-bleed over tft_surf, not scaled through the 240x400
# dashboard surface like the rest of the UI). Both axes wander between
# bounds set in draw_merz_overlay() once it knows the actual screen size -
# X and Y are both the sprite's CENTER, not its top-left.
MERZ_X = 0.0
MERZ_Y = 0.0
MERZ_WANDER_TARGET_X = None
MERZ_WANDER_TARGET_Y = None
MERZ_WANDER_SPEED = 55.0  # px/sec
# Fractions of DISPLAY_HEIGHT, not px - shared between update_merz_game()'s
# idle wander and handle_merz_click()'s dodge-reroute so both always agree
# on how high/low he's allowed to go, regardless of screen aspect ratio.
# Top is low enough that even the longest quote's bubble fits above his head
# (it may cover the hits/timer row, but never him - asserted in
# dev/test_party_games.py); bottom keeps him clear of the building.
MERZ_BOUNDS_TOP_FRACTION = 0.36
MERZ_BOUNDS_BOTTOM_FRACTION = 0.52
# The whole scene below the KiezOS title bar + hits/timer row sits this much
# lower, so even the longest quote's bubble clamps below the HUD.
MERZ_TOP_OFFSET = 80
MERZ_HUD_BOTTOM = 80
MERZ_NEXT_WANDER_AT = 0.0
MERZ_DODGE_UNTIL = 0.0
MERZ_HIT_FLINCH_UNTIL = 0.0
MERZ_LAST_TICK = 0.0
# Landing a hit visibly shrinks him (harder target, escalating difficulty),
# regrowing back to full size over a few unharmed seconds - clamped at
# both ends so hits can't make him disappear and idle time can't make him
# balloon past his starting size. MAX is also just his overall render
# size - the native sprite (see icons/merz_sprite.png) felt too big.
MERZ_SCALE = 1.0  # actual value set from MERZ_SCALE_MAX in activate_merz_game()
MERZ_SCALE_MAX = 0.62
MERZ_SCALE_MIN = 0.36
MERZ_SCALE_SHRINK_STEP = 0.05  # per hit
MERZ_SCALE_REGROW_PER_SEC = 0.04
MERZ_PROJECTILES = []  # each: {start:(x,y), target:(x,y), started_at, duration, kind}
MERZ_SPLATS = []  # each: {pos, started_at, kind: "hit"/"miss", text}
# Background gag, non-interactive (not a throw target, just flavor) - a
# private jet occasionally crosses behind him with a small speech bubble
# of its own, referencing the well-documented contrast between Merz's
# self-described "Mittelschicht"/normal-earner self-image and his actual
# wealth/private jet use (e.g. the 2025 Sylt-wedding private jet story -
# https://hamburg.t-online.de/region/hamburg/id_100027208/lindner-hochzeit-friedrich-merz-steuert-eigenen-privatjet-nach-sylt-und-erntet-shitstorm.html).
# The jet's own line is an original joke, not presented as something he
# said - same "no citation shown" convention as the non-quote MERZ_TAUNTS.
MERZ_JETS = []  # each: {x, y, direction, speed, phase: "cruise"/"climb"}
MERZ_NEXT_JET_AT = 0.0
MERZ_JET_TEXT = "ICH BIN EIN NORMALVERDIENER-PRIVATJET!"
# Shared between update_merz_game()'s actual movement and _draw_merz_jet()'s
# rotation angle, which needs to match the real velocity to look right.
MERZ_JET_CLIMB_VX_FACTOR = 0.7
MERZ_JET_CLIMB_VY_FACTOR = 0.5
MERZ_TAUNT_TEXT = None
MERZ_TAUNT_META = None  # "year, source" line for real quotes, None for reaction lines
MERZ_TAUNT_SHOWN_AT = 0.0
MERZ_TAUNT_NEXT_AT = 0.0
MERZ_TAUNT_DISPLAY_SECONDS = 8.0  # was 4.5 - too short to actually read/dodge-throw at leisure
# Shuffle-bag, not a fresh random.choice() each time - pure random picks
# from a small list feel repetitive/biased even though they aren't (Ju
# noticed "Stadtbild" seemingly showing up a lot - it wasn't a bug, just
# small-sample variance, but cycling through a shuffled order guarantees
# no immediate repeats and evens out the short-term distribution, which
# actually fixes the felt problem regardless of whether the old approach
# was "truly" biased).
MERZ_TAUNT_BAG = []

# Real, on-record statements kept verbatim (only trimmed with a leading/
# trailing "..." where shortened for bubble length, never paraphrased or
# reworded), mixed with plain non-factual reaction lines for game texture -
# the two look the same in the speech bubble on purpose (it's a joke), but
# only entries with a "year"/"source" are presented as actual quotes (see
# draw_merz_overlay(), rendered as a smaller line under the quote itself).
# Independently re-verified (date/venue, not just wording) before shipping:
#  - „...die kleinen Paschas, da mal etwas zurechtweisen.“ - full sentence:
#    "Und dann wollen sie diese Kinder zur Ordnung rufen und die Folge ist,
#    dass die Väter in den Schulen erscheinen und sich das verbitten.
#    Insbesondere wenn es sich um Lehrerinnen handelt, dass sie ihre Söhne,
#    die kleinen Paschas, da mal etwas zurechtweisen." - "Markus Lanz"
#    (ZDF), 11.01.2023 -
#    https://politik.watson.de/unterhaltung/politik/566805846-nach-pascha-aussage-bei-markus-lanz-heftige-kritik-an-friedrich-merz
#  - „Wir erleben mittlerweile einen Sozialtourismus dieser Flüchtlinge nach
#    Deutschland...“ - full: "...nach Deutschland, zurück in die Ukraine,
#    nach Deutschland, zurück in die Ukraine." - Bild TV, 26.09.2022 (not
#    2023 - initially misdated, corrected after re-verification) -
#    https://www.tagesspiegel.de/politik/nach-aussage-zu-sozialtourismus-faeser-wirft-merz-stimmungsmache-gegen-fluchtlinge-aus-ukraine-vor-8687668.html
#  - „Die sitzen beim Arzt und lassen sich die Zähne neu machen.“ - WELT
#    TALK, 27.09.2023 -
#    https://www.tagesspiegel.de/politik/erbarmlicher-populismus-merz-erntet-heftige-kritik-fur-aussage-uber-asylbewerber-beim-zahnarzt-10540855.html
#  - „...wir haben natürlich immer im Stadtbild noch dieses Problem...“ -
#    full: "...und deswegen ist der Bundesinnenminister ja auch dabei,
#    jetzt in sehr großem Umfang auch Rückführungen zu ermöglichen und
#    durchzuführen." - Pressekonferenz mit MP Dietmar Woidke, 14.10.2025,
#    triggered nationwide protests -
#    https://www.stuttgarter-zeitung.de/inhalt.friedrich-merz-stadtbild-aussage-wortlaut-mhsd.c674d7a6-52bd-4cbf-a68a-12f1700128fc.html
# A second research pass added 3 more (a candidate 5th, the 2001 Wowereit
# "coming out" remark, was found but is NOT included - the source itself
# flagged the exact wording as not independently confirmed verbatim
# against the original BUNTE interview, only reconstructed from two
# secondary sources quoting it slightly differently from each other):
#  - „...müssten sich einer gewachsenen, freiheitlichen deutschen
#    Leitkultur anpassen.“ - Bundestagsrede, 16.10.2000, restated in a
#    Welt guest essay 25.10.2000 -
#    https://www.bpb.de/themen/parteien/sprache-und-politik/42726/das-missglueckte-wort/
#  - „...solange es nicht Kinder betrifft – an der Stelle ist für mich
#    allerdings eine absolute Grenze erreicht...“ - BILD Live ("Die
#    richtigen Fragen"), September 2020, on being asked about a gay
#    chancellor -
#    https://www.handelsblatt.com/politik/deutschland/cdu-politiker-merz-sorgt-mit-aussage-ueber-homosexualitaet-fuer-kritik/26205700.html
#  - „Der Bundestag ist ja nun kein Zirkuszelt.“ - ARD "maischberger",
#    01.07.2025, defending the Bundestag not flying the rainbow flag for
#    CSD - https://www.zdfheute.de/politik/merz-regenbogenfahne-bundestag-zirkuszelt-100.html
# A third pass (2026-10-28) added 3 from 2026 (an October remark at the
# Arbeitgebertag about Bärbel Bas was left out on purpose - too close to
# her stepping down over a death in the family):
#  - „Kein Bundeskanzler vor mir hat so etwas ertragen müssen.“ - SPIEGEL
#    interview, published 29.04.2026, on social-media attacks -
#    https://nius.de/politik/merz-beschwert-sich-kritik-social-media (same
#    wording in https://www.l-iz.de/leben/gesellschaft/2026/04/kommentar-hoeren-wir-da-ein-mimimi-herr-merz-655618)
#  - „Diese ewige Nörgelei, ... ich bin es einfach leid.“ - ZDF
#    Sommerinterview, 19.07.2026 -
#    https://www.t-online.de/nachrichten/deutschland/innenpolitik/id_101350580/bundeskanzler-friedrich-merz-faehrt-aus-der-haut-bin-es-einfach-leid-.html
#  - „...Nöler, Nörgler, empörte Berufskritiker: Wegtreten!“ - full:
#    "Kulturpessimisten, Untergangspropheten, Nöler, Nörgler, empörte
#    Berufskritiker: Wegtreten!" - CDU-Landesparteitag NRW (Düsseldorf),
#    2026, exact date not confirmed - same t-online article, and
#    https://apollo-news.net/merz-nennt-kritiker-seines-reformkurses-noeler-und-untergangspropheten-diese-sollen-wegtreten/
MERZ_TAUNTS = [
    {
        "text": "„...die kleinen Paschas, da mal etwas zurechtweisen.“",
        "year": "2023",
        "source": "Markus Lanz",
    },
    {
        "text": "„Wir erleben mittlerweile einen Sozialtourismus dieser Flüchtlinge nach Deutschland...“",
        "year": "2022",
        "source": "Bild TV",
    },
    {
        "text": "„Die sitzen beim Arzt und lassen sich die Zähne neu machen.“",
        "year": "2023",
        "source": "WELT TALK",
    },
    {
        "text": "„...wir haben natürlich immer im Stadtbild noch dieses Problem...“",
        "year": "2025",
        "source": "Pressekonferenz",
    },
    {
        "text": "„...einer gewachsenen, freiheitlichen deutschen Leitkultur anpassen.“",
        "year": "2000",
        "source": "Bundestagsrede",
    },
    {
        "text": "„...solange es nicht Kinder betrifft – an der Stelle ist für mich allerdings eine absolute Grenze erreicht...“",
        "year": "2020",
        "source": "BILD Live",
    },
    {
        "text": "„Der Bundestag ist ja nun kein Zirkuszelt.“",
        "year": "2025",
        "source": "maischberger",
    },
    {
        "text": "„Kein Bundeskanzler vor mir hat so etwas ertragen müssen.“",
        "year": "2026",
        "source": "SPIEGEL",
    },
    {
        "text": "„Diese ewige Nörgelei, diese ewige Nölerei, dieses Schlechtreden, dieses Kaputtreden unseres Landes – ich darf mir das bei solchen Gelegenheiten auch mal erlauben – ich bin es einfach leid.“",
        "year": "2026",
        "source": "ZDF-Sommerinterview",
    },
    {
        "text": "„...Nöler, Nörgler, empörte Berufskritiker: Wegtreten!“",
        "year": "2026",
        "source": "CDU-Landesparteitag",
    },
    {"text": "IHR SEID ZU FAUL!!!"},
    {"text": "MEINE FRISUR!!"},
    {"text": "HÖRT SOFORT AUF DAMIT!"},
    {"text": "ICH BIN DER KANZLER!!"},
]

# Pixel-grid caricature, drawn as filled squares (see draw_merz_sprite).
# Hand-drawn pixel-grid attempts (checked against reference photos, twice)
# still didn't read as him clearly enough, so the sprite is now derived
# from a real photo instead: downsampled + palette-quantized + scaled back
# up with nearest-neighbor for the blocky look. See
# dev/generate_merz_sprite.py for the exact crop/settings and the source
# photo's license (an EU-owned press photo that explicitly permits
# derivative works - deliberately not the alternative candidate photo,
# whose White House source explicitly forbids manipulation).
MERZ_SPRITE_PATH = ICON_PATH + "merz_sprite.png"
MERZ_SPRITE_IMG = None  # lazily loaded on first use, see _get_merz_sprite_img()


def _get_merz_sprite_img():
    """Loads/caches the sprite lazily rather than at module import time -
    pygame.image.load(...).convert() needs a display surface to already
    exist, and this module defines MERZ globals before tft_surf is
    created further down the file."""
    global MERZ_SPRITE_IMG
    if MERZ_SPRITE_IMG is None:
        MERZ_SPRITE_IMG = pygame.image.load(MERZ_SPRITE_PATH).convert_alpha()
    return MERZ_SPRITE_IMG

EMOTION_LAST_PROMPT_TS = 0.0
EMOTION_PROMPT_VISIBLE = False
EMOTION_PROMPT_OPENED_AT = 0.0
EMOTION_PROMPT_SOURCE = "unknown"
EMOTION_ACTIVE_PROMPT_ID = None
EMOTION_RESULTS_VISIBLE = False
EMOTION_CONFIRMATION_VISIBLE = False
EMOTION_CONFIRMATION_TEXT = ""
EMOTION_CONFIRMATION_OPENED_AT = 0.0
EMOTION_PENDING_TRIGGER = None
EMOTION_PENDING_LOCK = threading.Lock()
EMOTION_MODAL_RECT = None
EMOTION_BUTTON_RECTS = []
EMOTION_ACTION_RECTS = {}
EMOTION_QR_SURFACE = None
EMOTION_QR_URL_CACHE = None
# Footer "emolog/stats: <url>" text is clickable to pop the same results QR
# standalone (outside the emotion-prompt flow) - see handle_emolog_footer_click().
EMOLOG_FOOTER_RECT = None
EMOLOG_QR_OPENED_AT = 0.0
EMOLOG_QR_AUTO_CLOSE_SECONDS = 20
EMOTION_SHUFFLED_ROWS = []  # mood.exe's grid: one list per mood family, rows and items shuffled
EMOTION_CUSTOM_SLOTS = []
EMOTION_CUSTOM_BUTTON_RECTS = []
EMOTION_KEYBOARD_VISIBLE = False
EMOTION_KEYBOARD_TEXT = ""
EMOTION_KEYBOARD_RECTS = []
EMOTION_LAST_ACTIVITY_TS = 0.0
EMOTION_CATALOG = []


def _normalize_emotion_label(label):
    if not isinstance(label, str):
        return ""
    compact = " ".join(label.strip().lower().split())
    return compact[:EMOTION_KEYBOARD_MAX_CHARS]


def _ensure_unknown_option():
    global EMOTION_OPTIONS

    normalized = []
    for emotion in EMOTION_OPTIONS:
        cleaned = _normalize_emotion_label(str(emotion))
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)

    if EMOTION_UNKNOWN_OPTION not in normalized:
        normalized.append(EMOTION_UNKNOWN_OPTION)

    EMOTION_OPTIONS = normalized


def _load_custom_slots_from_config():
    slots = config.get("EMOTION", {}).get("CUSTOM_SLOTS", [])
    if not isinstance(slots, list):
        return []

    cleaned_slots = []
    for slot in slots:
        cleaned = _normalize_emotion_label(slot)
        if cleaned and cleaned not in EMOTION_DEFAULT_STYLE and cleaned not in cleaned_slots:
            cleaned_slots.append(cleaned)
        if len(cleaned_slots) >= EMOTION_CUSTOM_SLOT_COUNT:
            break

    return cleaned_slots


def _build_catalog_from_config():
    catalog = config.get("EMOTION", {}).get("CATALOG", [])
    if not isinstance(catalog, list):
        catalog = []

    normalized = []
    seen = set()
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        name = _normalize_emotion_label(entry.get("name"))
        if not name or name in seen:
            continue
        style = EMOTION_DEFAULT_STYLE.get(name, EMOTION_FALLBACK_STYLE)
        normalized.append(
            {
                "name": name,
                "emoji": entry.get("emoji") or style["emoji"],
                "color": entry.get("color") or style["color"],
            }
        )
        seen.add(name)

    if not normalized:
        for name in EMOTION_OPTIONS:
            style = EMOTION_DEFAULT_STYLE.get(name, EMOTION_FALLBACK_STYLE)
            normalized.append({"name": name, "emoji": style["emoji"], "color": style["color"]})

    return normalized


def _emotion_names_from_catalog(catalog):
    return [entry["name"] for entry in catalog]


def _ensure_catalog_entry(name, emoji=None, color=None, insert_after=None):
    global EMOTION_CATALOG

    normalized = _normalize_emotion_label(name)
    if not normalized:
        return
    if any(entry.get("name") == normalized for entry in EMOTION_CATALOG):
        return

    style = EMOTION_DEFAULT_STYLE.get(normalized, EMOTION_FALLBACK_STYLE)
    resolved_emoji = emoji or style["emoji"]
    resolved_color = (
        color if isinstance(color, str) and EMOTION_COLOR_RE.match(color) else style["color"]
    )
    new_entry = {"name": normalized, "emoji": resolved_emoji, "color": resolved_color}

    # Determine insertion position based on insert_after.
    # null means insert at the very beginning of the ordered catalog.
    if insert_after is None:
        EMOTION_CATALOG.insert(0, new_entry)
        return

    if insert_after:
        insert_after_norm = _normalize_emotion_label(insert_after)
        for idx, entry in enumerate(EMOTION_CATALOG):
            if entry.get("name") == insert_after_norm:
                EMOTION_CATALOG.insert(idx + 1, new_entry)
                return

    # If insert_after is not found, append to end as a safe fallback.
    EMOTION_CATALOG.append(new_entry)


def _extract_first_json_block(payload_text):
    if not isinstance(payload_text, str):
        return None
    payload_text = payload_text.strip()
    try:
        return json.loads(payload_text)
    except json.JSONDecodeError:
        pass

    start = payload_text.find("{")
    end = payload_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(payload_text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _build_llm_classification_prompt(new_emotion):
    catalog = [
        {
            "name": entry.get("name"),
            "emoji": entry.get("emoji"),
            "color": entry.get("color"),
        }
        for entry in EMOTION_CATALOG
    ]

    return EMOTION_LLM_PROMPT_TEMPLATE.replace(
        "{{catalog_json}}", json.dumps(catalog, ensure_ascii=False)
    ).replace("{{new_emotion_json}}", json.dumps({"name": new_emotion}, ensure_ascii=False))


def _classify_custom_emotion(name):
    style = EMOTION_DEFAULT_STYLE.get(name, EMOTION_FALLBACK_STYLE)
    fallback = {
        "name": name,
        "emoji": style["emoji"],
        "color": style["color"],
        "insert_after": None,
    }

    if not EMOTION_LLM_ENABLED or not EMOTION_LLM_API_KEY:
        return fallback

    try:
        prompt = _build_llm_classification_prompt(name)
        logger.info(f"🤖 LLM: Classifying custom emotion '{name}'")
        logger.info("🤖 LLM: Prompt used:\n%s", prompt)

        response = requests.post(
            EMOTION_LLM_URL,
            headers={
                "content-type": "application/json",
                "x-api-key": EMOTION_LLM_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            timeout=8,
            json={
                "model": EMOTION_LLM_MODEL,
                "max_tokens": 200,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        logger.info(
            "🤖 LLM: Raw API response payload:\n%s",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

        llm_text = ""
        if isinstance(payload.get("content"), list) and payload["content"]:
            llm_text = payload["content"][0].get("text", "")
        logger.info("🤖 LLM: Raw model answer:\n%s", llm_text)

        parsed = _extract_first_json_block(llm_text)
        if not isinstance(parsed, dict):
            logger.info("🤖 LLM: JSON parse check failed, using fallback")
            logger.info("🤖 LLM: Parse check details - extracted JSON block: missing or invalid")
            return fallback

        logger.info("🤖 LLM: Parsed JSON:\n%s", json.dumps(parsed, ensure_ascii=False, indent=2))

        required_fields = ("name", "emoji", "color", "insert_after")
        missing_fields = [field for field in required_fields if field not in parsed]
        if missing_fields:
            logger.info("🤖 LLM: JSON check - missing fields: %s", missing_fields)
        else:
            logger.info("🤖 LLM: JSON check - all required fields present")

        llm_name = _normalize_emotion_label(parsed.get("name")) or name
        emoji = parsed.get("emoji") or fallback["emoji"]
        color = parsed.get("color")
        color_valid = isinstance(color, str) and EMOTION_COLOR_RE.match(color)
        if not color_valid:
            color = fallback["color"]
        insert_after = parsed.get("insert_after") or None

        logger.info(
            f"🤖 LLM: Final classification - name='{llm_name}' emoji='{emoji}' "
            f"color='{color}' insert_after='{insert_after}'"
        )
        logger.info(
            "🤖 LLM: Validation summary - name_normalized=%s emoji_present=%s color_valid=%s insert_after=%s",
            llm_name == _normalize_emotion_label(parsed.get("name")),
            bool(emoji),
            bool(color_valid),
            insert_after,
        )

        return {"name": llm_name, "emoji": emoji, "color": color, "insert_after": insert_after}
    except Exception as llm_ex:
        logger.info(f"🤖 LLM: Classification failed for '{name}': {llm_ex}, using fallback")
        return fallback


def retry_fallback_emotion_classifications():
    """
    Re-run LLM classification for catalog entries stuck on EMOTION_FALLBACK_STYLE ("?" / gray) -
    most commonly because the LLM call in _classify_custom_emotion failed for lack of internet at
    the moment someone typed a new custom emotion. Called from safe_network_monitor() whenever
    internet comes back up, so those emojis get backfilled automatically instead of staying wrong
    until someone notices and fixes them by hand.
    """
    if not EMOTION_LLM_ENABLED or not EMOTION_LLM_API_KEY:
        return

    stuck_entries = [
        entry
        for entry in EMOTION_CATALOG
        if entry.get("name") != EMOTION_UNKNOWN_OPTION
        and entry.get("emoji") == EMOTION_FALLBACK_STYLE["emoji"]
        and entry.get("color") == EMOTION_FALLBACK_STYLE["color"]
    ]
    if not stuck_entries:
        return

    logger.info(
        f"🤖 LLM: Internet back up - retrying classification for {len(stuck_entries)} "
        f"emotion(s) stuck on fallback style: {[entry['name'] for entry in stuck_entries]}"
    )

    # This runs inside safe_network_monitor(), whose own try/except is reserved for judging
    # whether the network itself is up (it drives the auto-reboot logic) - an unrelated failure
    # here (e.g. disk write) must not get misread as "network still down".
    try:
        changed = False
        for entry in stuck_entries:
            classification = _classify_custom_emotion(entry["name"])
            if (
                classification["emoji"] == EMOTION_FALLBACK_STYLE["emoji"]
                and classification["color"] == EMOTION_FALLBACK_STYLE["color"]
            ):
                logger.info(f"🤖 LLM: '{entry['name']}' still classifies to fallback style, leaving as-is")
                continue
            entry["emoji"] = classification["emoji"]
            entry["color"] = classification["color"]
            changed = True
            logger.info(f"🤖 LLM: Backfilled '{entry['name']}' -> {entry['emoji']} {entry['color']}")

        if changed:
            _persist_emotion_config(EMOTION_CUSTOM_SLOTS)
    except Exception as retry_ex:
        logger.warning(f"🤖 LLM: Fallback-emoji retry pass failed: {retry_ex}")


def touch_emotion_prompt_activity():
    global EMOTION_LAST_ACTIVITY_TS
    EMOTION_LAST_ACTIVITY_TS = time.time()


def _persist_emotion_config(custom_slots):
    global emotion_cfg

    config.setdefault("EMOTION", {})
    config["EMOTION"]["CUSTOM_SLOTS"] = custom_slots
    config["EMOTION"]["CATALOG"] = EMOTION_CATALOG
    emotion_cfg = config["EMOTION"]

    with open(EMOTION_CONFIG_PATH, "w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=4)


def _get_emotion_usage_counts():
    usage = {}
    for event in read_emotion_events(EMOTION_LOG_PATH):
        if event.get("skipped"):
            continue
        emotion = _normalize_emotion_label(event.get("emotion"))
        if not emotion:
            continue
        usage[emotion] = usage.get(emotion, 0) + 1
    return usage


def _upsert_custom_slot(label):
    global EMOTION_CUSTOM_SLOTS

    normalized = _normalize_emotion_label(label)
    if not normalized:
        logger.info(f"✏️  Custom emotion: Normalization failed for '{label}'")
        return None

    # Check if it exists in default options
    if normalized in EMOTION_OPTIONS:
        logger.info(f"✏️  Custom emotion: '{normalized}' already in default options")
        return {
            "emotion": normalized,
            "added": False,
            "duplicate": True,
            "reason": "default-options",
        }

    # Check if it's already in custom slots
    if normalized in EMOTION_CUSTOM_SLOTS:
        logger.info(f"✏️  Custom emotion: '{normalized}' already in custom slots")
        return {"emotion": normalized, "added": False, "duplicate": True, "reason": "custom-slot"}

    # Check if it already exists in catalog
    if any(entry.get("name") == normalized for entry in EMOTION_CATALOG):
        logger.info(f"✏️  Custom emotion: '{normalized}' already in catalog")
        return {"emotion": normalized, "added": False, "duplicate": True, "reason": "catalog"}

    logger.info(f"✏️  Custom emotion: New emotion '{normalized}', classifying with LLM...")

    # It's truly new - classify it to get LLM suggestions (including potential spelling corrections)
    classification = _classify_custom_emotion(normalized)

    # LLM might have corrected/normalized the name to something else
    llm_name = classification.get("name", normalized)

    # Check if the LLM-suggested name already exists in catalog
    if any(entry.get("name") == llm_name for entry in EMOTION_CATALOG):
        # LLM corrected it to an existing emotion - use that instead (don't modify slots)
        logger.info(
            f"✏️  Custom emotion: LLM corrected '{normalized}' → '{llm_name}' (already in catalog)"
        )
        return {
            "emotion": llm_name,
            "added": False,
            "duplicate": True,
            "reason": "llm-catalog-correction",
        }

    # Truly new emotion - add to slots with the (possibly corrected) LLM name
    slots = list(EMOTION_CUSTOM_SLOTS)
    if len(slots) < EMOTION_CUSTOM_SLOT_COUNT:
        slots.append(llm_name)
        logger.info(f"✏️  Custom emotion: Added '{llm_name}' to custom slots (total: {len(slots)})")
    else:
        usage = _get_emotion_usage_counts()
        left_usage = usage.get(slots[0], 0)
        right_usage = usage.get(slots[1], 0)
        replace_index = 0 if left_usage <= right_usage else 1
        old_emotion = slots[replace_index]
        slots[replace_index] = llm_name
        logger.info(
            f"✏️  Custom emotion: Replaced '{old_emotion}' (usage={[left_usage, right_usage][replace_index]}) with '{llm_name}'"
        )

    # Add to catalog with LLM-suggested emoji, color, and position
    _ensure_catalog_entry(
        llm_name,
        emoji=classification.get("emoji"),
        color=classification.get("color"),
        insert_after=classification.get("insert_after"),
    )

    EMOTION_CUSTOM_SLOTS = slots
    _persist_emotion_config(slots)
    logger.info(
        f"✏️  Custom emotion: Successfully added '{llm_name}' to catalog and persisted config"
    )
    return {"emotion": llm_name, "added": True, "duplicate": False, "reason": "new"}


def _apply_emotion_keyboard_token(token):
    global EMOTION_KEYBOARD_TEXT

    touch_emotion_prompt_activity()

    if token == "back":
        EMOTION_KEYBOARD_TEXT = EMOTION_KEYBOARD_TEXT[:-1]
        return
    if token == "clear":
        EMOTION_KEYBOARD_TEXT = ""
        return
    if token == "space":
        if EMOTION_KEYBOARD_TEXT and len(EMOTION_KEYBOARD_TEXT) < EMOTION_KEYBOARD_MAX_CHARS:
            EMOTION_KEYBOARD_TEXT += " "
        return
    if len(EMOTION_KEYBOARD_TEXT) < EMOTION_KEYBOARD_MAX_CHARS:
        EMOTION_KEYBOARD_TEXT += token


def _submit_custom_emotion():
    global EMOTION_KEYBOARD_TEXT, EMOTION_KEYBOARD_VISIBLE

    label = _normalize_emotion_label(EMOTION_KEYBOARD_TEXT)
    if not label:
        logger.info(f"✏️  Custom emotion: Empty/invalid input, keyboard dismissed")
        EMOTION_KEYBOARD_VISIBLE = False
        EMOTION_KEYBOARD_TEXT = ""
        return

    logger.info(f"✏️  Custom emotion: User submitted '{label}'")
    selected = _upsert_custom_slot(label)
    EMOTION_KEYBOARD_VISIBLE = False
    EMOTION_KEYBOARD_TEXT = ""
    if selected:
        handle_emotion_choice(emotion=selected.get("emotion"), skipped=False)
        if selected.get("duplicate"):
            show_emotion_confirmation_message(
                f"Emotion '{selected.get('emotion')}' logged,\nbut not added\nas duplicate"
            )


def get_emotion_prompt_options(max_count=16):
    options = [str(emotion).strip() for emotion in EMOTION_OPTIONS if str(emotion).strip()]
    if not options:
        options = ["happy"]
    return options[:max_count]


# mood.exe groups the buttons into one row per mood family (config EMOTION.GROUPS
# overrides), so a mood is quick to find; rows and the moods in them are still
# shuffled every time against position bias in the stats.
EMOTION_GROUPS = emotion_cfg.get("GROUPS", [
    ["happy", "excited", "energized", "wild"],
    ["grateful", "relaxed", "proud", "focused"],
    ["curious", "bored", "tired", "don't know"],
    ["anxious", "stressed", "angry", "sad"],
])


def shuffled_emotion_rows(options):
    """options grouped by EMOTION_GROUPS (leftovers, e.g. new catalog entries,
    in rows of 4), row order and order within each row shuffled."""
    rows = [[e for e in group if e in options] for group in EMOTION_GROUPS]
    grouped = {e for row in rows for e in row}
    rest = [e for e in options if e not in grouped]
    rows += [rest[i:i + 4] for i in range(0, len(rest), 4)]
    rows = [row for row in rows if row]
    for row in rows:
        random.shuffle(row)
    random.shuffle(rows)
    return rows


def fit_emotion_label_font(emotion, max_width):
    for font in (FONT_SMALL, FONT_TINY, FONT_SUPER_TINY):
        if font.size(emotion)[0] <= max_width:
            return font
    return FONT_SUPER_TINY


EMOTION_CATALOG = _build_catalog_from_config()
EMOTION_OPTIONS = [
    name for name in _emotion_names_from_catalog(EMOTION_CATALOG) if name in EMOTION_DEFAULT_STYLE
]
if not EMOTION_OPTIONS:
    EMOTION_OPTIONS = list(EMOTION_DEFAULT_STYLE.keys())
_ensure_unknown_option()
_ensure_catalog_entry(EMOTION_UNKNOWN_OPTION)
EMOTION_CUSTOM_SLOTS = _load_custom_slots_from_config()

try:
    # if you do local development you can add a mock server (e.g. from postman.io our your homebrew solution)
    # simple add this variables to your config.json to save api-requests
    # or to create your own custom test data for your own dashboard views)
    if config["ENV"] == "DEV":
        SERVER = config["MOCKSERVER_URL"]
        WEATHERBIT_IO_KEY = config["WEATHERBIT_DEV_KEY"]
        HEADERS = {"X-Api-Key": f'{config["MOCKSERVER_API_KEY"]}'}

    elif config["ENV"] == "STAGE":
        WEATHERBIT_IO_KEY = config["WEATHERBIT_DEV_KEY"]
        # Note: In this mode, we are not using any weather updates from API,
        #  but instead simply showing the latest data from
        #  logs/latest_weather.json.

    elif config["ENV"] == "Pi":
        LOG_PATH = "/mnt/ramdisk/"
        WEATHERBIT_IO_KEY = config["WEATHERBIT_IO_KEY"]

    logger.info(f"STARTING IN {config['ENV']} MODE")


except Exception as e:
    logger.warning(e)
    quit()


record_uptime_event(
    "boot_started",
    source="startup",
    reason=config.get("ENV", "unknown"),
    details={"display_blank_after": DISPLAY_BLANK_AFTER},
)
record_uptime_event(
    "screen_on",
    source="startup",
    reason="booted_visible",
)


pygame.display.init()
pygame.mixer.quit()
pygame.font.init()
pygame.mouse.set_visible(config["DISPLAY"]["MOUSE"])
pygame.display.set_caption("PiDashboard")


def quit_all():
    pygame.display.quit()
    pygame.quit()

    logger.info("Shutting down - stopping scheduler")

    # Stop the new scheduler
    scheduler.stop_all()

    # Cleanup GPIO
    if GPIO_AVAILABLE:
        try:
            GPIO.cleanup()
            logger.info("GPIO cleanup completed")
        except Exception as e:
            logger.error(f"Error during GPIO cleanup: {e}")

    sys.exit()


def secret_video_corner_for_click(mx, my):
    """Return which physical corner (TL/TR/BR/BL) a click landed in, or None.

    Mirrors the generous top-left emergency-exit hitbox (see the corner-tap
    handling in loop()) to all four corners so the same touch imprecision
    tolerance applies.
    """
    corner_w, corner_h = 100, 180
    if mx < corner_w and my < corner_h:
        return "TL"
    if mx > DISPLAY_WIDTH - corner_w and my < corner_h:
        return "TR"
    if mx > DISPLAY_WIDTH - corner_w and my > DISPLAY_HEIGHT - corner_h:
        return "BR"
    if mx < corner_w and my > DISPLAY_HEIGHT - corner_h:
        return "BL"
    return None


def handle_secret_video_gesture_tap(corner):
    """Advance the secret TL->TR->BR->BL corner sequence; play video on completion.

    Deliberately non-blocking of normal click handling (unlike the emergency
    exit tap) so it never swallows a legitimate tap on real UI near a corner.
    """
    global secret_video_gesture_progress, secret_video_gesture_last_tap_ts

    if not SECRET_VIDEO_ENABLED or corner is None:
        return

    now = time.time()
    if (
        secret_video_gesture_progress
        and now - secret_video_gesture_last_tap_ts > SECRET_VIDEO_GESTURE_TIMEOUT_SECONDS
    ):
        secret_video_gesture_progress = 0

    expected = SECRET_VIDEO_GESTURE_SEQUENCE[secret_video_gesture_progress]
    if corner == expected:
        secret_video_gesture_progress += 1
        secret_video_gesture_last_tap_ts = now
        if secret_video_gesture_progress == len(SECRET_VIDEO_GESTURE_SEQUENCE):
            secret_video_gesture_progress = 0
            play_secret_video()
    elif corner == SECRET_VIDEO_GESTURE_SEQUENCE[0]:
        secret_video_gesture_progress = 1
        secret_video_gesture_last_tap_ts = now
    else:
        secret_video_gesture_progress = 0


def play_secret_video():
    global secret_video_last_path, secret_video_queue

    clips = sorted(glob.glob(os.path.join(SECRET_VIDEO_DIR, "*.mp4")))
    # template.mp4 is a committed placeholder so the feature works out of the
    # box on a fresh clone - exclude it from the pool once real clips exist.
    real_clips = [c for c in clips if os.path.basename(c) != "template.mp4"]
    clips = real_clips or clips
    if not clips:
        logger.warning(f"Secret video gesture triggered but no clips found in: {SECRET_VIDEO_DIR}")
        return

    # Shuffled playthrough: refill and reshuffle the bag once it's exhausted
    # (or once the clip pool on disk has changed), so every clip plays once
    # before any repeats instead of pure random.choice() clustering.
    if not secret_video_queue or not set(secret_video_queue) <= set(clips):
        secret_video_queue = clips.copy()
        random.shuffle(secret_video_queue)
        # Avoid an immediate repeat across the bag boundary (last clip of the
        # previous cycle landing first in the new one).
        if len(secret_video_queue) > 1 and secret_video_queue[-1] == secret_video_last_path:
            secret_video_queue[-1], secret_video_queue[0] = (
                secret_video_queue[0],
                secret_video_queue[-1],
            )

    video_path = secret_video_queue.pop()
    secret_video_last_path = video_path

    logger.info(f"Secret video gesture completed - playing {os.path.basename(video_path)}")
    wake_display("secret_video_gesture", reason="secret_video_gesture")

    # xset's blank/dpms idle timers run at the X-server level, independent of
    # this (blocked) loop, so a video longer than DISPLAY_BLANK with no touch
    # input would otherwise blank mid-playback. Suspend them for the duration.
    os.system("xset s off")
    os.system("xset -dpms")
    try:
        subprocess.run([*SECRET_VIDEO_PLAYER_CMD, SECRET_VIDEO_SCRIPT_ARG, video_path], check=False)
    except FileNotFoundError:
        logger.error(f"Video player command not found: {SECRET_VIDEO_PLAYER_CMD[0]}")
    finally:
        os.system(f"xset s {DISPLAY_BLANK_AFTER} {DISPLAY_BLANK_AFTER}")
        os.system(f"xset dpms {DISPLAY_BLANK_AFTER} {DISPLAY_BLANK_AFTER} {DISPLAY_BLANK_AFTER}")

    logger.info("Secret video playback finished")


# display settings from theme config
DISPLAY_WIDTH = int(config["DISPLAY"]["WIDTH"])
DISPLAY_HEIGHT = int(config["DISPLAY"]["HEIGHT"])

# the drawing area to place all text and img on
# 3:5 to match our actual 480x800 portrait panel (240x320 was 3:4, which left
# 80px blank above and below after scaling - see FIT_SCREEN below)
SURFACE_WIDTH = 240
SURFACE_HEIGHT = 400

SCALE = float(DISPLAY_WIDTH / SURFACE_WIDTH)
ZOOM = 1

FPS = config["DISPLAY"]["FPS"]
SHOW_FPS = config["DISPLAY"]["SHOW_FPS"]


# correction for 1:1 displays like hyperpixel4 square
if DISPLAY_WIDTH / DISPLAY_HEIGHT == 1:
    logger.info(f"square display configuration detected")
    square_width = int(DISPLAY_WIDTH / float(4 / 3))
    SCALE = float(square_width / SURFACE_WIDTH)

    logger.info(f"scale and display correction caused by square display")
    logger.info(f"DISPLAY_WIDTH: {square_width} new SCALE: {SCALE}")

# check if a landscape display is configured
if DISPLAY_WIDTH > DISPLAY_HEIGHT:
    logger.info(f"landscape display configuration detected")
    SCALE = float(DISPLAY_HEIGHT / SURFACE_HEIGHT)

    logger.info(f"scale and display correction caused by landscape display")
    logger.info(f"DISPLAY_HEIGHT: {DISPLAY_HEIGHT} new SCALE: {SCALE}")

# zoom the application surface rendering to display size scale
if SCALE != 1:
    ZOOM = SCALE

    if DISPLAY_HEIGHT < SURFACE_HEIGHT:
        logger.info("screen smaller as surface area - zooming smaller")
        SURFACE_HEIGHT = DISPLAY_HEIGHT
        SURFACE_WIDTH = int(SURFACE_HEIGHT / (4 / 3))
        logger.info(f"surface correction caused by small display")
        if DISPLAY_WIDTH == DISPLAY_HEIGHT:
            logger.info("small and square")
            ZOOM = round(ZOOM, 2)
        else:
            ZOOM = round(ZOOM, 1)
        logger.info(f"zoom correction caused by small display")
    else:
        logger.info("screen bigger as surface area - zooming bigger")
        SURFACE_WIDTH = int(SURFACE_WIDTH * ZOOM)
        SURFACE_HEIGHT = int(SURFACE_HEIGHT * ZOOM)
        logger.info(f"surface correction caused by bigger display")

    logger.info(f"SURFACE_WIDTH: {SURFACE_WIDTH} SURFACE_HEIGHT: {SURFACE_HEIGHT} ZOOM: {ZOOM}")

FIT_SCREEN = (
    int((DISPLAY_WIDTH - SURFACE_WIDTH) / 2),
    int((DISPLAY_HEIGHT - SURFACE_HEIGHT) / 2),
)

# the real display surface
tft_surf = pygame.display.set_mode(
    (DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.NOFRAME if config["ENV"] == "Pi" else 0
)

clock = pygame.time.Clock()

logger.info(
    f"display with {DISPLAY_WIDTH}px width and {DISPLAY_HEIGHT}px height is "
    f"set to {FPS} FPS"
)

BACKGROUND = tuple(theme["COLOR"]["BACKGROUND"])
MAIN_FONT = tuple(theme["COLOR"]["MAIN_FONT"])
BLACK = tuple(theme["COLOR"]["BLACK"])
DARK_GRAY = tuple(theme["COLOR"]["DARK_GRAY"])
WHITE = tuple(theme["COLOR"]["WHITE"])
RED = tuple(theme["COLOR"]["RED"])
GREEN = tuple(theme["COLOR"]["GREEN"])
BLUE = tuple(theme["COLOR"]["BLUE"])
LIGHT_BLUE = tuple((BLUE[0], 210, BLUE[2]))
DARK_BLUE = tuple((BLUE[0], 100, 255))
SWEET_PURPLE = (196, 150, 255)
YELLOW = tuple(theme["COLOR"]["YELLOW"])
ORANGE = tuple(theme["COLOR"]["ORANGE"])
VIOLET = tuple(theme["COLOR"]["VIOLET"])
COLOR_LIST = [BLUE, LIGHT_BLUE, DARK_BLUE]

FONT_MEDIUM = theme["FONT"]["MEDIUM"]
FONT_BOLD = theme["FONT"]["BOLD"]
DATE_SIZE = int(theme["FONT"]["DATE_SIZE"] * ZOOM)
CLOCK_SIZE = int(theme["FONT"]["CLOCK_SIZE"] * ZOOM)
SUPER_TINY_SIZE = int(theme["FONT"]["SUPER_TINY_SIZE"] * ZOOM)
TINY_SIZE = int(theme["FONT"]["TINY_SIZE"] * ZOOM)
SMALL_SIZE = int(theme["FONT"]["SMALL_SIZE"] * ZOOM)
BIG_SIZE = int(theme["FONT"]["BIG_SIZE"] * ZOOM)

FONT_SUPER_TINY = pygame.font.Font(FONT_PATH + FONT_MEDIUM, SUPER_TINY_SIZE)
FONT_TINY = pygame.font.Font(FONT_PATH + FONT_MEDIUM, TINY_SIZE)
FONT_SMALL = pygame.font.Font(FONT_PATH + FONT_MEDIUM, SMALL_SIZE)
FONT_SMALL_BOLD = pygame.font.Font(FONT_PATH + FONT_BOLD, SMALL_SIZE)
FONT_BIG = pygame.font.Font(FONT_PATH + FONT_MEDIUM, BIG_SIZE)
# Between TINY and SMALL (closer to SMALL) - used for BVG departure times,
# which needed to shrink from SMALL to fit 4 rows horizontally but were
# unreadable at TINY.
FONT_BUS_TIME = pygame.font.Font(
    FONT_PATH + FONT_MEDIUM, int(TINY_SIZE + (SMALL_SIZE - TINY_SIZE) * 0.65)
)
FONT_BIG_BOLD = pygame.font.Font(FONT_PATH + FONT_BOLD, BIG_SIZE)
MERZ_HUD_FONT = pygame.font.Font(FONT_PATH + FONT_BOLD, int(SMALL_SIZE * 0.75))  # MERZ hits/timer pills
DATE_FONT = pygame.font.Font(FONT_PATH + FONT_BOLD, DATE_SIZE)
CLOCK_FONT = pygame.font.Font(FONT_PATH + FONT_BOLD, CLOCK_SIZE)
CLEANING_FONT = pygame.font.Font(FONT_PATH + FONT_BOLD, 40)
# Chore list rendered below the big CLEANING_FONT headline on the cleaning-day
# fullscreen - same fixed-px (not ZOOM-scaled) convention as CLEANING_FONT,
# since both draw directly onto tft_surf at physical display resolution.
CLEANING_CHORE_FONT = pygame.font.Font(FONT_PATH + FONT_MEDIUM, 32)
# Chore checklist detail screen, same fixed-px convention.
CHORE_ITEM_FONT = pygame.font.Font(FONT_PATH + FONT_MEDIUM, 28)
CHORE_ITEM_FONT_SMALL = pygame.font.Font(FONT_PATH + FONT_MEDIUM, 22)
CHORE_ITEM_FONT_BOLD = pygame.font.Font(FONT_PATH + FONT_BOLD, 28)
# Chore names on the list cards, largest that fits next to the progress.
CHORE_PROGRESS_FONT_SMALL = pygame.font.Font(FONT_PATH + FONT_BOLD, 20)
CHORE_NAME_FONTS = [pygame.font.Font(FONT_PATH + FONT_BOLD, size) for size in (30, 26, 22, 18)]
# Sub-item sizes tried largest-first until the whole checklist fits, see
# _layout_chore_rows().
CHORE_ITEM_FONTS = [pygame.font.Font(FONT_PATH + FONT_MEDIUM, size) for size in (28, 24, 21, 18, 16)]
# Detail-screen title sizes, largest that fits the chore name on one line
# (real names like "Baddienst 2 (mit Badewanne)" don't at 40 px).
K.configure(FONT_PATH, ICON_PATH, theme.get("KIEZOS"))

CHORE_TITLE_FONTS = [CLEANING_FONT] + [pygame.font.Font(FONT_PATH + FONT_BOLD, size) for size in (34, 30, 26)]


WEATHERICON = "unknown"

FORECASTICON_DAY_1 = "unknown"
FORECASTICON_DAY_2 = "unknown"
FORECASTICON_DAY_3 = "unknown"

CONNECTION_ERROR = True
REFRESH_ERROR = True
PATH_ERROR = True
PRECIPTYPE = "NULL"
PRECIPCOLOR = WHITE

CONNECTION = False
READING = False
UPDATING = False

WEATHER_JSON_DATA = {}


def image_factory(image_path):
    result = {}
    for img in os.listdir(image_path):
        image_id = img.split(".")[0]
        if image_id == "":
            pass
        else:
            result[image_id] = Image.open(image_path + img)
    return result


class DrawString:
    def __init__(self, surf, string: str, font, color, y: int):
        """
        :param string: the input string
        :param font: the fonts object
        :param color: a rgb color tuple
        :param y: the y position where you want to render the text
        """
        self.string = string
        self.font = font
        self.color = color
        self.y = int(y * ZOOM)
        self.size = self.font.size(self.string)
        self.surf = surf

    def left(self, offset=0):
        """
        :param offset: define some offset pixel to move strings a little bit more left (default=0)
        """

        x = int(10 * ZOOM + (offset * ZOOM))

        self.draw_string(x)

    def right(self, offset=0):
        """
        :param offset: define some offset pixel to move strings a little bit more right (default=0)
        """

        x = int((SURFACE_WIDTH - self.size[0] - (10 * ZOOM)) - (offset * ZOOM))

        self.draw_string(x)

    def center(self, parts, part, offset=0):
        """
        :param parts: define in how many parts you want to split your display
        :param part: the part in which you want to render text (first part is 0, second is 1, etc.)
        :param offset: define some offset pixel to move strings a little bit (default=0)
        """

        x = int(
            (
                (((SURFACE_WIDTH / parts) / 2) + ((SURFACE_WIDTH / parts) * part))
                - (self.size[0] / 2)
            )
            + (offset * ZOOM)
        )

        self.draw_string(x)

    def draw_string(self, x):
        """
        takes x and y from the functions above and render the fonts
        """

        self.surf.blit(self.font.render(self.string, True, self.color), (x, self.y))


class DrawImage:
    def __init__(self, surf, image=Image, y=None, size=None, fillcolor=None, angle=None):
        """
        :param image: image from the image_factory()
        :param y: the y-position of the image you want to render
        """
        self.image = image
        if y:
            self.y = int(y * ZOOM)

        self.img_size = self.image.size
        self.size = int(size * ZOOM)
        self.angle = angle
        self.surf = surf

        if angle:
            self.image = self.image.rotate(self.angle, resample=Image.BICUBIC)

        if size:
            width, height = self.image.size
            if width >= height:
                width, height = (self.size, int(self.size / width * height))
            else:
                width, height = (int(self.size / width * height), self.size)

            new_image = self.image.resize((width, height), Image.LANCZOS)
            self.image = new_image
            self.img_size = new_image.size

        self.fillcolor = fillcolor

        self.image = pygame.image.fromstring(self.image.tobytes(), self.image.size, self.image.mode)

    @staticmethod
    def fill(surface, fillcolor: tuple):
        """converts the color on an mono colored icon"""
        surface.set_colorkey(BACKGROUND)
        w, h = surface.get_size()
        r, g, b = fillcolor
        for x in range(w):
            for y in range(h):
                a: int = surface.get_at((x, y))[3]
                # removes some distortion from scaling/zooming
                if a > 5:
                    color = pygame.Color(r, g, b, a)
                    surface.set_at((x, y), color)

    def left(self, offset=0):
        """
        :param offset: define some offset pixel to move image a little bit more left(default=0)
        """

        x = int(10 * ZOOM + (offset * ZOOM))

        self.draw_image(x)

    def right(self, offset=0):
        """
        :param offset: define some offset pixel to move image a little bit more right (default=0)
        """

        x = int((SURFACE_WIDTH - self.img_size[0] - 10 * ZOOM) - (offset * ZOOM))

        self.draw_image(x)

    def center(self, parts, part, offset=0):
        """
        :param parts: define in how many parts you want to split your display
        :param part: the part in which you want to render text (first part is 0, second is 1, etc.)
        :param offset: define some offset pixel to move strings a little bit (default=0)
        """

        x = int(
            (
                (((SURFACE_WIDTH / parts) / 2) + ((SURFACE_WIDTH / parts) * part))
                - (self.img_size[0] / 2)
            )
            + (offset * ZOOM)
        )

        self.draw_image(x)

    def draw_middle_position_icon(self):

        position_x = int(
            (SURFACE_WIDTH - ((SURFACE_WIDTH / 3) / 2) - (self.image.get_rect()[2] / 2))
        )

        position_y = int((self.y - (self.image.get_rect()[3] / 2)))

        self.draw_image(draw_x=position_x, draw_y=position_y)

    def draw_position(self, pos: tuple):
        x, y = pos
        if y == 0:
            y += 1
        self.draw_image(draw_x=int(x * ZOOM), draw_y=int(y * ZOOM))

    def draw_absolut_position(self, pos: tuple):
        x, y = pos
        if y == 0:
            y += 1
        self.draw_image(draw_x=int(x), draw_y=int(y))

    def draw_image(self, draw_x, draw_y=None):
        """
        takes x from the functions above and the y from the class to render the image
        """

        if self.fillcolor:

            surface = self.image
            self.fill(surface, self.fillcolor)

            if draw_y:
                self.surf.blit(surface, (int(draw_x), int(draw_y)))
            else:
                self.surf.blit(surface, (int(draw_x), self.y))
        else:
            if draw_y:
                self.surf.blit(self.image, (int(draw_x), int(draw_y)))
            else:
                self.surf.blit(self.image, (int(draw_x), self.y))


class WeatherUpdate(object):

    @staticmethod
    def update_and_process():
        """Complete weather update cycle - API call + data processing + surface creation"""
        global CONNECTION_ERROR, REFRESH_ERROR, CONNECTION, READING, UPDATING, WEATHER_AVAILABLE

        # Skip if display is blank or in STAGE mode
        if DISPLAY_BLANK or config["ENV"] == "STAGE":
            # In STAGE mode, just read the existing JSON file
            if config["ENV"] == "STAGE":
                WeatherUpdate.read_json_and_process()
            return

        CONNECTION = pygame.time.get_ticks() + 1500  # 1.5 seconds

        try:
            # Step 1: Fetch new data from API
            current_endpoint = f"{SERVER}/current"
            daily_endpoint = f"{SERVER}/forecast/daily"
            stats_endpoint = f"{SERVER}/subscription/usage"
            units = "M" if METRIC else "I"

            logger.info(f"connecting to server: {SERVER}")

            options = str(
                f"&postal_code={WEATHERBIT_POSTALCODE}"
                f"&country={WEATHERBIT_COUNTRY}"
                f"&lang={WEATHERBIT_LANG}"
                f"&units={units}"
            )

            current_request_url = str(f"{current_endpoint}?key={WEATHERBIT_IO_KEY}{options}")
            daily_request_url = str(
                f"{daily_endpoint}?key={WEATHERBIT_IO_KEY}{options}&days={WEATHERBIT_DAYS}"
            )
            stats_request_url = str(f"{stats_endpoint}?key={WEATHERBIT_IO_KEY}")

            current_data = requests.get(current_request_url, headers=HEADERS, timeout=10).json()
            daily_data = requests.get(daily_request_url, headers=HEADERS, timeout=10).json()
            stats_data = requests.get(stats_request_url, headers=HEADERS, timeout=10).json()

            data = {"current": current_data, "daily": daily_data, "stats": stats_data}

            # Step 2: Save to file
            with open(LOG_PATH + "latest_weather.json", "w+") as outputfile:
                json.dump(data, outputfile, indent=2, sort_keys=True)

            logger.info("json file saved")
            CONNECTION_ERROR = False
            if not WEATHER_AVAILABLE:
                record_uptime_event(
                    "weather_up",
                    source="weather_update",
                    reason="weatherbit request succeeded",
                )
                WEATHER_AVAILABLE = True

            # Step 3: Process the data immediately
            WeatherUpdate.process_data(data)

        except (
            requests.HTTPError,
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.JSONDecodeError,
        ) as update_ex:
            CONNECTION_ERROR = True
            if WEATHER_AVAILABLE:
                record_uptime_event(
                    "weather_down",
                    source="weather_update",
                    reason=str(update_ex),
                )
                WEATHER_AVAILABLE = False
            logger.warning(
                f"Failed updating latest_weather.json. weatherbit connection ERROR: {update_ex}"
            )

            # Fallback: try to read existing file
            try:
                WeatherUpdate.read_json_and_process()
            except Exception as fallback_ex:
                logger.error(f"Fallback read also failed: {fallback_ex}")

    @staticmethod
    def read_json_and_process():
        """Read JSON file and process data"""
        global WEATHER_JSON_DATA, REFRESH_ERROR, READING

        READING = pygame.time.get_ticks() + 1500  # 1.5 seconds

        try:
            data = open(LOG_PATH + "latest_weather.json").read()
            new_json_data = json.loads(data)
            logger.info("json file read by module")

            REFRESH_ERROR = False
            WeatherUpdate.process_data(new_json_data)

        except IOError as read_ex:
            REFRESH_ERROR = True
            logger.warning(f"ERROR - json file read by module: {read_ex}")

    @staticmethod
    def process_data(data):
        """Keep the new Weatherbit data and refresh the Open-Meteo rain
        forecast for its location every RAIN_REFRESH_SECONDS."""
        global WEATHER_JSON_DATA

        WEATHER_JSON_DATA = data
        current = data["current"]["data"][0]
        logger.info(f"weather: {current['temp']} {current['weather']['description']} (code {current['weather']['code']})")
        if RAIN_FORECAST is None or time.time() - RAIN_FORECAST["fetched_at"] > RAIN_REFRESH_SECONDS:
            _update_rain_forecast(current["lat"], current["lon"])


class BVGUpdate(object):

    @staticmethod
    def update_bvg_stop_information():
        """Simple BVG update without self-scheduling"""
        global UPDATED_BVG_TIME, BVG_STOP_INFORMATION, BVG_AVAILABLE

        if DISPLAY_BLANK:
            return

        try:
            UPDATED_BVG_TIME, BVG_STOP_INFORMATION = get_stop_data(
                BVG_ROWS,
                BVG_LOOKAHEAD_MIN,
                BVG_LOOKBACK_MIN,
            )
            logger.info("BVG data updated successfully")
            if not BVG_AVAILABLE:
                record_uptime_event(
                    "bvg_up",
                    source="bvg_update",
                    reason="bvg request succeeded",
                )
                BVG_AVAILABLE = True
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as update_ex:
            UPDATED_BVG_TIME = False
            if BVG_AVAILABLE:
                record_uptime_event(
                    "bvg_down",
                    source="bvg_update",
                    reason=str(update_ex),
                )
                BVG_AVAILABLE = False
            logger.error(f"BVG cycle failed: BVG Connection ERROR: {update_ex}")
        except Exception as e:
            UPDATED_BVG_TIME = False
            if BVG_AVAILABLE:
                record_uptime_event(
                    "bvg_down",
                    source="bvg_update",
                    reason=str(e),
                )
                BVG_AVAILABLE = False
            logger.error(f"BVG cycle failed: Unexpected error in BVG update: {e}")


# Not using strftime("%a") here since LOCALE.ISO drives the system locale
# (currently "en_GB") and the WG panel's own labels (ZU TUN/ZU KAUFEN/ZU
# BESUCH) are German regardless of that setting.
GERMAN_WEEKDAYS_ABBR = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _format_visit_date(iso_date):
    dt = datetime.datetime.fromisoformat(iso_date)
    return f"{GERMAN_WEEKDAYS_ABBR[dt.weekday()]}, {dt.strftime('%-d.%-m.')}"


def _moabeats_fetch_status():
    """Poll MoaBeats' /api/display/status and update MOABEATS_STATUS in place.
    Returns True on success (the chore detail screen shows a failure)."""
    global MOABEATS_STATUS
    cfg = config.get("MOABEATS", {})
    if not cfg.get("ENABLED", False):
        return False
    try:
        resp = requests.get(
            cfg["API_URL"].rstrip("/") + "/api/display/status",
            headers={"Authorization": f"Bearer {cfg['DISPLAY_SECRET']}"},
            timeout=8,
        )
        if resp.status_code == 200:
            with MOABEATS_STATUS_LOCK:
                MOABEATS_STATUS = resp.json()
            return True
        logger.error(f"MoaBeats status fetch returned HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"MoaBeats status fetch failed: {e}")
    return False


def _find_cleaning_chore(chore_id):
    with MOABEATS_STATUS_LOCK:
        for chore in MOABEATS_STATUS.get("cleaning_chores", []):
            if chore.get("id") == chore_id:
                return chore
    return None


def _chore_progress_text(checklist):
    return f"{sum(1 for entry in checklist if entry['done'])}/{len(checklist)}"


def _start_chore_refresh():
    """New session + one background status refetch, so ticks made on phones
    since the last poll show up."""
    global CHORE_DETAIL_SESSION, CHORE_DETAIL_LAST_ACTIVITY_TS, CHORE_DETAIL_PENDING_ITEM
    global CHORE_DETAIL_ERROR, CHORE_DETAIL_REFRESHING

    CHORE_DETAIL_SESSION += 1
    CHORE_DETAIL_LAST_ACTIVITY_TS = time.time()
    CHORE_DETAIL_PENDING_ITEM = None
    CHORE_DETAIL_ERROR = None
    CHORE_DETAIL_REFRESHING = True
    threading.Thread(target=_chore_detail_refresh_worker, args=(CHORE_DETAIL_SESSION,), daemon=True).start()


def open_chore_detail(chore_id):
    """Open the checklist detail screen (refetches the status once)."""
    global CHORE_DETAIL_ID, CHORE_DETAIL_SNAPSHOT

    CHORE_DETAIL_ID = chore_id
    CHORE_DETAIL_SNAPSHOT = _find_cleaning_chore(chore_id)
    logger.info(f"Chore detail opened: {chore_id}")
    _start_chore_refresh()


def open_chore_list():
    """Open the chore list overlay from Start -> Putzdienste (refetches the status once)."""
    global CHORE_LIST_OPEN

    CHORE_LIST_OPEN = True
    logger.info("Chore list overlay opened")
    _start_chore_refresh()


def close_chore_list(reason):
    global CHORE_LIST_OPEN, CHORE_LIST_CLOSE_RECT, CLEANING_CHORE_ROW_RECTS, CHORE_DETAIL_ERROR

    if not CHORE_LIST_OPEN:
        return
    close_chore_detail(reason)
    logger.info(f"Chore list overlay closed ({reason})")
    CHORE_LIST_OPEN = False
    CHORE_LIST_CLOSE_RECT = None
    CLEANING_CHORE_ROW_RECTS = []
    CHORE_DETAIL_ERROR = None  # don't carry a stale error onto the screensaver


def close_chore_detail(reason):
    global CHORE_DETAIL_ID, CHORE_DETAIL_ROW_RECTS, CHORE_DETAIL_BACK_RECT

    if CHORE_DETAIL_ID is None:
        return
    logger.info(f"Chore detail closed ({reason})")
    CHORE_DETAIL_ID = None
    CHORE_DETAIL_ROW_RECTS = []
    CHORE_DETAIL_BACK_RECT = None


def update_chore_screen_timeout():
    """Called every frame from loop(): close after CHORE_DETAIL_IDLE_TIMEOUT_SECONDS
    without a tap, or once the screen it sits on isn't what's showing anymore
    (the overlay on the awake dashboard, the detail on the cleaning screen)."""
    if CHORE_LIST_OPEN:
        if DISPLAY_BLANK:
            close_chore_list("display-blank")
        elif time.time() - CHORE_DETAIL_LAST_ACTIVITY_TS > CHORE_DETAIL_IDLE_TIMEOUT_SECONDS:
            close_chore_list("idle-timeout")
        return
    if CHORE_DETAIL_ID is None:
        return
    if not DISPLAY_BLANK or datetime.datetime.today().weekday() != CLEANING_DAY:
        close_chore_detail("cleaning-screen-gone")
    elif time.time() - CHORE_DETAIL_LAST_ACTIVITY_TS > CHORE_DETAIL_IDLE_TIMEOUT_SECONDS:
        close_chore_detail("idle-timeout")


def _chore_detail_refresh_worker(session):
    global CHORE_DETAIL_REFRESHING, CHORE_DETAIL_ERROR

    ok = _moabeats_fetch_status()
    if session != CHORE_DETAIL_SESSION:
        return
    if not ok:
        CHORE_DETAIL_ERROR = "Aktualisieren fehlgeschlagen"
    CHORE_DETAIL_REFRESHING = False


def _chore_detail_toggle_worker(session, chore_id, item, done):
    """PATCH one checklist item; on success the response's checklist replaces
    the chore's checklist in MOABEATS_STATUS. On a 400 (item edited away in
    the app, or chore already completed) the whole status is reloaded."""
    global CHORE_DETAIL_PENDING_ITEM, CHORE_DETAIL_ERROR

    cfg = config["MOABEATS"]
    error = None
    try:
        resp = requests.patch(
            cfg["API_URL"].rstrip("/") + f"/api/display/chores/{chore_id}/checklist",
            headers={"Authorization": f"Bearer {cfg['DISPLAY_SECRET']}"},
            json={"item": item, "done": done},
            timeout=8,
        )
        if resp.status_code == 200:
            checklist = resp.json()["checklist"]
            with MOABEATS_STATUS_LOCK:
                for chore in MOABEATS_STATUS.get("cleaning_chores", []):
                    if chore.get("id") == chore_id:
                        chore["checklist"] = checklist
            logger.info(f"Chore {chore_id} checklist: {item!r} -> done={done}")
        else:
            logger.error(f"Chore {chore_id} checklist PATCH returned HTTP {resp.status_code}: {resp.text[:200]}")
            # 400: item edited away in the app / chore already completed;
            # 404: chore deleted in the app. Either way: reload, show fresh state.
            if resp.status_code in (400, 404):
                error = "Nicht gespeichert – Liste wurde geändert"
                if not _moabeats_fetch_status():
                    error = "Nicht gespeichert, Neuladen fehlgeschlagen"
            else:
                error = f"Nicht gespeichert (HTTP {resp.status_code})"
    except requests.RequestException as e:
        logger.error(f"Chore {chore_id} checklist PATCH failed: {e}")
        error = "Nicht gespeichert – keine Verbindung"
    finally:
        if session == CHORE_DETAIL_SESSION:
            CHORE_DETAIL_PENDING_ITEM = None
    if session == CHORE_DETAIL_SESSION:
        CHORE_DETAIL_ERROR = error


def get_lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def get_results_url():
    host = WEB_HOST
    if host in ("0.0.0.0", "::", ""):
        host = get_lan_ip()
    return f"http://{host}:{WEB_PORT}"


def schedule_emotion_prompt(source):
    global EMOTION_PENDING_TRIGGER

    if not EMOTION_ENABLED:
        return

    now = time.time()
    with EMOTION_PENDING_LOCK:
        if EMOTION_PENDING_TRIGGER is not None or EMOTION_PROMPT_VISIBLE:
            return
        if now - EMOTION_LAST_PROMPT_TS < EMOTION_COOLDOWN_SECONDS:
            return
        EMOTION_PENDING_TRIGGER = source


def activate_pending_emotion_prompt():
    global EMOTION_PENDING_TRIGGER, EMOTION_PROMPT_VISIBLE, EMOTION_PROMPT_OPENED_AT
    global EMOTION_PROMPT_SOURCE, EMOTION_LAST_PROMPT_TS, EMOTION_ACTIVE_PROMPT_ID
    global EMOTION_RESULTS_VISIBLE, EMOTION_BUTTON_RECTS, EMOTION_ACTION_RECTS
    global EMOTION_SHUFFLED_ROWS, EMOTION_CUSTOM_SLOTS, EMOTION_KEYBOARD_VISIBLE
    global EMOTION_KEYBOARD_TEXT, EMOTION_CUSTOM_BUTTON_RECTS, EMOTION_KEYBOARD_RECTS
    global EMOTION_LAST_ACTIVITY_TS

    if not EMOTION_ENABLED or DISPLAY_BLANK or QUIZ_STAGE is not None or EGG is not None:
        return

    with EMOTION_PENDING_LOCK:
        if EMOTION_PENDING_TRIGGER is None or EMOTION_PROMPT_VISIBLE:
            return
        source = EMOTION_PENDING_TRIGGER
        EMOTION_PENDING_TRIGGER = None

    EMOTION_PROMPT_VISIBLE = True
    EMOTION_RESULTS_VISIBLE = False
    EMOTION_PROMPT_OPENED_AT = time.time()
    EMOTION_LAST_PROMPT_TS = EMOTION_PROMPT_OPENED_AT
    EMOTION_LAST_ACTIVITY_TS = EMOTION_PROMPT_OPENED_AT
    EMOTION_PROMPT_SOURCE = source
    EMOTION_ACTIVE_PROMPT_ID = str(uuid.uuid4())
    EMOTION_BUTTON_RECTS = []
    EMOTION_ACTION_RECTS = {}
    EMOTION_CUSTOM_BUTTON_RECTS = []
    EMOTION_KEYBOARD_RECTS = []
    EMOTION_KEYBOARD_VISIBLE = False
    EMOTION_KEYBOARD_TEXT = ""
    EMOTION_CUSTOM_SLOTS = _load_custom_slots_from_config()
    EMOTION_SHUFFLED_ROWS = shuffled_emotion_rows(get_emotion_prompt_options(max_count=16))
    logger.info(f"Emotion prompt activated (source={source})")


def dismiss_emotion_prompt(reason):
    global EMOTION_PROMPT_VISIBLE, EMOTION_RESULTS_VISIBLE, EMOTION_BUTTON_RECTS
    global EMOTION_ACTION_RECTS, EMOTION_MODAL_RECT, EMOTION_CUSTOM_BUTTON_RECTS
    global EMOTION_KEYBOARD_VISIBLE, EMOTION_KEYBOARD_TEXT, EMOTION_KEYBOARD_RECTS

    if not EMOTION_PROMPT_VISIBLE and not EMOTION_RESULTS_VISIBLE:
        return

    EMOTION_PROMPT_VISIBLE = False
    EMOTION_RESULTS_VISIBLE = False
    EMOTION_BUTTON_RECTS = []
    EMOTION_CUSTOM_BUTTON_RECTS = []
    EMOTION_KEYBOARD_RECTS = []
    EMOTION_ACTION_RECTS = {}
    EMOTION_KEYBOARD_VISIBLE = False
    EMOTION_KEYBOARD_TEXT = ""
    EMOTION_MODAL_RECT = None
    logger.info(f"Emotion prompt dismissed ({reason})")


def show_emotion_confirmation(emotion):
    global EMOTION_CONFIRMATION_VISIBLE, EMOTION_CONFIRMATION_TEXT, EMOTION_CONFIRMATION_OPENED_AT

    EMOTION_CONFIRMATION_TEXT = f"Emotion '{emotion}' logged"
    EMOTION_CONFIRMATION_OPENED_AT = time.time()
    EMOTION_CONFIRMATION_VISIBLE = True
    logger.info(f"Emotion confirmation shown: {EMOTION_CONFIRMATION_TEXT}")


def show_emotion_confirmation_message(message):
    global EMOTION_CONFIRMATION_VISIBLE, EMOTION_CONFIRMATION_TEXT, EMOTION_CONFIRMATION_OPENED_AT

    EMOTION_CONFIRMATION_TEXT = message
    EMOTION_CONFIRMATION_OPENED_AT = time.time()
    EMOTION_CONFIRMATION_VISIBLE = True
    logger.info(f"Emotion confirmation shown: {EMOTION_CONFIRMATION_TEXT}")


def dismiss_emotion_confirmation(reason):
    global EMOTION_CONFIRMATION_VISIBLE, EMOTION_CONFIRMATION_TEXT, EMOTION_CONFIRMATION_OPENED_AT

    if not EMOTION_CONFIRMATION_VISIBLE:
        return

    EMOTION_CONFIRMATION_VISIBLE = False
    EMOTION_CONFIRMATION_TEXT = ""
    EMOTION_CONFIRMATION_OPENED_AT = 0.0
    logger.info(f"Emotion confirmation dismissed ({reason})")


def handle_emotion_choice(emotion=None, skipped=False):
    payload = append_emotion_event(
        EMOTION_LOG_PATH,
        emotion=emotion,
        skipped=skipped,
        source=EMOTION_PROMPT_SOURCE,
        prompt_id=EMOTION_ACTIVE_PROMPT_ID,
    )
    logger.info(f"Emotion event logged: {payload}")
    dismiss_emotion_prompt("user-selection")
    if emotion and not skipped:
        show_emotion_confirmation(emotion)


def get_qr_surface(url, pixel_size=210):
    global EMOTION_QR_SURFACE, EMOTION_QR_URL_CACHE

    if EMOTION_QR_URL_CACHE == url and EMOTION_QR_SURFACE is not None:
        return EMOTION_QR_SURFACE

    qr_builder = qrcode.QRCode(version=1, box_size=8, border=2)
    qr_builder.add_data(url)
    qr_builder.make(fit=True)
    qr_image = qr_builder.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_image = qr_image.resize((pixel_size, pixel_size), Image.BILINEAR)
    qr_surface = pygame.image.fromstring(qr_image.tobytes(), qr_image.size, qr_image.mode)

    EMOTION_QR_URL_CACHE = url
    EMOTION_QR_SURFACE = qr_surface
    return qr_surface


def draw_results_overlay():
    """Mood stats: QR code to the web dashboard (from the emotion prompt's
    "Show results" or Start -> Stimmung & Stats). Any tap closes. mood.exe
    is English on purpose: the emotion names are English (they're the
    stored data), so its text matches them."""
    url = get_results_url()
    _draw_qr_dialog("mood.exe - Results", "stats", "Mood stats", url,
                    [url, "All moods & uptime in your browser"])


def _draw_qr_dialog(title, icon, heading, data, lines):
    win = pygame.Rect(40, 150, DISPLAY_WIDTH - 80, 500)
    inner = K.dialog(tft_surf, win, title, icon=icon)
    K.t95(tft_surf, heading, 20, (inner.centerx, inner.y + 4), anchor="midtop")
    box = pygame.Rect(inner.centerx - 130, inner.y + 40, 260, 260)
    K.bevel(tft_surf, box, sunken=True, face=K.F_PAPER)
    tft_surf.blit(K.qr95(data, 244), (box.x + 8, box.y + 8))
    for i, line in enumerate(lines):
        size = K.fit_size(line, inner.w - 8, sizes=(17, 16, 15, 14, 13))
        K.t95(tft_surf, line, size, (inner.centerx, box.bottom + 14 + i * 24), anchor="midtop", bold=i == 0)
    K.button(tft_surf, pygame.Rect(inner.centerx - 60, inner.bottom - 44, 120, 42), "OK", size=17)


def draw_emotion_confirmation_overlay():
    if not EMOTION_CONFIRMATION_VISIBLE:
        return

    lines = [line for line in EMOTION_CONFIRMATION_TEXT.splitlines() if line.strip()] or [EMOTION_CONFIRMATION_TEXT]
    logged = re.fullmatch(r"Emotion '(.+)' logged", EMOTION_CONFIRMATION_TEXT)
    height = 200 if logged else 170 + 24 * len(lines)
    win = pygame.Rect(50, (DISPLAY_HEIGHT - height) // 2, DISPLAY_WIDTH - 100, height)
    inner = K.dialog(tft_surf, win, "mood.exe", icon="heart")
    tft_surf.blit(K.menu_icon("ok", 48), (inner.x + 6, inner.y + 10))
    text_w = inner.w - 72
    if logged:
        K.t95(tft_surf, "Thanks! Logged:", 17, (inner.x + 66, inner.y + 10))
        name = logged.group(1)
        K.t95(tft_surf, name, K.fit_size(name, text_w, sizes=(22, 18, 15, 13)), (inner.x + 66, inner.y + 36), color=K.F_ACCENT)
        y = inner.y + 70
    else:
        y = inner.y + 10
        for line in lines:
            K.t95(tft_surf, line, K.fit_size(line, text_w, sizes=(17, 16, 15, 14)), (inner.x + 66, y))
            y += 24
        y += 6
    K.t95(tft_surf, "Ju likes you.", 16, (inner.x + 66, y), color=K.F_DARK, bold=False)
    K.button(tft_surf, pygame.Rect(inner.right - 100, inner.bottom - 40, 100, 38), "OK", size=16)


def _emotion_color(name):
    for entry in EMOTION_CATALOG:
        if entry.get("name") == name and EMOTION_COLOR_RE.match(str(entry.get("color", ""))):
            return pygame.Color(entry["color"])
    return pygame.Color(EMOTION_FALLBACK_STYLE.get("color", "#9ca3af"))


def draw_emotion_prompt_overlay():
    """mood.exe: emotion buttons, 3 custom slots + "custom...", then
    "Show results" / "Cancel" (= skip, like the title bar's x). The
    "custom..." keyboard replaces the grid inside the same window."""
    global EMOTION_MODAL_RECT, EMOTION_BUTTON_RECTS, EMOTION_ACTION_RECTS
    global EMOTION_CUSTOM_BUTTON_RECTS, EMOTION_KEYBOARD_RECTS

    if not EMOTION_PROMPT_VISIBLE:
        return

    EMOTION_BUTTON_RECTS = []
    EMOTION_CUSTOM_BUTTON_RECTS = []
    EMOTION_KEYBOARD_RECTS = []

    if EMOTION_KEYBOARD_VISIBLE:
        EMOTION_MODAL_RECT = pygame.Rect(8, 150, DISPLAY_WIDTH - 16, 560)
        inner = K.dialog(tft_surf, EMOTION_MODAL_RECT, "mood.exe - Custom mood", icon="heart")
        K.t95(tft_surf, "How do you feel? Your own word:", 16, (inner.x + 4, inner.y + 4))
        at_char_limit = len(EMOTION_KEYBOARD_TEXT) >= EMOTION_KEYBOARD_MAX_CHARS
        field = pygame.Rect(inner.x, inner.y + 34, inner.w, 50)
        K.textfield(tft_surf, field, EMOTION_KEYBOARD_TEXT, "custom mood", warn=at_char_limit)
        # Typing is hard-capped at EMOTION_KEYBOARD_MAX_CHARS (see _apply_emotion_keyboard_token) -
        # show the counter so hitting that cap is visible instead of keys silently doing nothing.
        K.t95(tft_surf, f"{len(EMOTION_KEYBOARD_TEXT)}/{EMOTION_KEYBOARD_MAX_CHARS}", 15,
              (field.right - 8, field.centery), color=K.F_LATE if at_char_limit else K.F_DARK, bold=False, anchor="midright")
        keys = K.keyboard95(tft_surf, pygame.Rect(inner.x, inner.y + 96, inner.w, 330),
                            ["qwertzuiop", "asdfghjkl", "yxcvbnm"],
                            [("Space", "space", 0.5), ("<-", "back", 0.22), ("Clear", "clear", 0.28)])
        EMOTION_KEYBOARD_RECTS = [{"token": token, "rect": rect} for rect, token in keys]
        half = (inner.w - 8) // 2
        cancel_rect = K.button(tft_surf, pygame.Rect(inner.x, inner.bottom - 56, half, 54), "Cancel", size=18)
        save_rect = K.button(tft_surf, pygame.Rect(inner.x + half + 8, inner.bottom - 56, half, 54), "Save", size=19)
        EMOTION_ACTION_RECTS = {
            "close": K.close_box(EMOTION_MODAL_RECT),
            "keyboard_cancel": cancel_rect,
            "keyboard_save": save_rect,
        }
        return

    EMOTION_MODAL_RECT = pygame.Rect(14, 120, DISPLAY_WIDTH - 28, 540)
    inner = K.dialog(tft_surf, EMOTION_MODAL_RECT, "mood.exe", icon="heart")
    tft_surf.blit(K.menu_icon("quiz", 44), (inner.x + 6, inner.y + 6))
    K.t95(tft_surf, "Most prevalent emotion", 18, (inner.x + 62, inner.y + 6))
    K.t95(tft_surf, "right now?", 18, (inner.x + 62, inner.y + 30))

    rows = EMOTION_SHUFFLED_ROWS or shuffled_emotion_rows(get_emotion_prompt_options(max_count=16))
    columns = max(map(len, rows))
    gap = 8
    grid = pygame.Rect(inner.x + 4, inner.y + 66, inner.w - 8, 4 * (72 + gap) - gap)
    bw = (grid.w - (columns - 1) * gap) // columns
    bh = min(72, (grid.h - (len(rows) - 1) * gap) // len(rows))
    icon = 32 if bh >= 64 else 24
    for r, row in enumerate(rows):
        # one mood family per row; shorter rows are centred
        row_left = grid.x + (grid.w - (len(row) * bw + (len(row) - 1) * gap)) // 2
        for col, emotion in enumerate(row):
            rect = pygame.Rect(row_left + col * (bw + gap), grid.y + r * (bh + gap), bw, bh)
            K.button(tft_surf, rect, "")
            swatch = pygame.Rect(rect.x + 7, rect.y + 7, 9, 9)
            pygame.draw.rect(tft_surf, _emotion_color(emotion), swatch)
            pygame.draw.rect(tft_surf, K.F_INK, swatch, 1)
            tft_surf.blit(K.emotion_icon(emotion, icon), (rect.centerx - icon // 2, rect.y + 5))
            K.t95(tft_surf, emotion, K.fit_size(emotion, rect.w - 10, sizes=(17, 16, 15, 14)), (rect.centerx, rect.bottom - 6), anchor="midbottom")
            EMOTION_BUTTON_RECTS.append({"emotion": emotion, "rect": rect})

    cy = grid.bottom + 10
    cw = (grid.w - 3 * gap) // 4
    for idx in range(4):
        rect = pygame.Rect(grid.x + idx * (cw + gap), cy, cw, 42)
        if idx == 3:
            K.button(tft_surf, rect, "custom...", size=16)
            EMOTION_CUSTOM_BUTTON_RECTS.append({"type": "trigger", "rect": rect})
        elif idx < len(EMOTION_CUSTOM_SLOTS) and EMOTION_CUSTOM_SLOTS[idx]:
            label = EMOTION_CUSTOM_SLOTS[idx]
            K.button(tft_surf, rect, label, size=K.fit_size(label, rect.w - 8, sizes=(16, 15, 14, 13)))
            EMOTION_CUSTOM_BUTTON_RECTS.append({"type": "slot", "emotion": label, "rect": rect})
        else:
            K.bevel(tft_surf, rect, sunken=True, face=K.F_PAPER)

    by = cy + 56
    show_rect = K.button(tft_surf, pygame.Rect(inner.x + 4, by, inner.w - 136, 44), "Show results", size=17)
    cancel_rect = K.button(tft_surf, pygame.Rect(inner.right - 124, by, 120, 44), "Cancel", size=17)
    EMOTION_ACTION_RECTS = {
        "close": K.close_box(EMOTION_MODAL_RECT),
        "cancel": cancel_rect,
        "show_results": show_rect,
    }


def handle_emotion_popup_click(mx, my):
    global EMOTION_RESULTS_VISIBLE, EMOTION_KEYBOARD_VISIBLE, EMOTION_KEYBOARD_TEXT

    if EMOTION_CONFIRMATION_VISIBLE:
        dismiss_emotion_confirmation("tap")
        return True

    if not EMOTION_PROMPT_VISIBLE and not EMOTION_RESULTS_VISIBLE:
        return False

    touch_emotion_prompt_activity()

    if EMOTION_RESULTS_VISIBLE:
        # Also covers the standalone footer-triggered QR (EMOTION_PROMPT_VISIBLE
        # False, EMOTION_RESULTS_VISIBLE True) - tap anywhere closes it there too.
        EMOTION_RESULTS_VISIBLE = False
        return True

    for name in ("close", "cancel"):
        rect = EMOTION_ACTION_RECTS.get(name)
        if rect and rect.collidepoint((mx, my)):
            handle_emotion_choice(skipped=True)
            return True

    if EMOTION_KEYBOARD_VISIBLE:
        cancel_rect = EMOTION_ACTION_RECTS.get("keyboard_cancel")
        if cancel_rect and cancel_rect.collidepoint((mx, my)):
            EMOTION_KEYBOARD_VISIBLE = False
            EMOTION_KEYBOARD_TEXT = ""
            return True

        save_rect = EMOTION_ACTION_RECTS.get("keyboard_save")
        if save_rect and save_rect.collidepoint((mx, my)):
            _submit_custom_emotion()
            return True

        for key_button in EMOTION_KEYBOARD_RECTS:
            if key_button["rect"].collidepoint((mx, my)):
                _apply_emotion_keyboard_token(key_button["token"])
                return True
        return True

    for button in EMOTION_BUTTON_RECTS:
        if button["rect"].collidepoint((mx, my)):
            handle_emotion_choice(emotion=button["emotion"], skipped=False)
            return True

    for custom_button in EMOTION_CUSTOM_BUTTON_RECTS:
        if not custom_button["rect"].collidepoint((mx, my)):
            continue
        if custom_button["type"] == "slot":
            emotion = custom_button.get("emotion")
            if emotion:
                handle_emotion_choice(emotion=emotion, skipped=False)
            return True

        if custom_button["type"] == "trigger":
            EMOTION_KEYBOARD_VISIBLE = True
            EMOTION_KEYBOARD_TEXT = ""
            return True

    show_rect = EMOTION_ACTION_RECTS.get("show_results")
    if show_rect and show_rect.collidepoint((mx, my)):
        EMOTION_RESULTS_VISIBLE = True
        return True

    return True


def handle_emotion_keyboard_keydown(event):
    global EMOTION_KEYBOARD_VISIBLE, EMOTION_KEYBOARD_TEXT

    if not EMOTION_PROMPT_VISIBLE or not EMOTION_KEYBOARD_VISIBLE:
        return False

    touch_emotion_prompt_activity()

    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
        _submit_custom_emotion()
        return True
    if event.key == pygame.K_ESCAPE:
        EMOTION_KEYBOARD_VISIBLE = False
        EMOTION_KEYBOARD_TEXT = ""
        return True
    if event.key == pygame.K_BACKSPACE:
        _apply_emotion_keyboard_token("back")
        return True
    if event.key == pygame.K_SPACE:
        _apply_emotion_keyboard_token("space")
        return True

    token = (event.unicode or "").lower()
    if token and (token.isalnum() or token in {"-", "_"}):
        _apply_emotion_keyboard_token(token)
        return True

    return False


def on_motion_detected():
    """Callback function triggered when motion is detected by PIR sensor"""
    global LAST_TOUCH_TIME, LAST_MOTION_DETECTED_TIME, DISPLAY_BLANK

    # On cleaning day we keep PIR wake disabled so the reminder remains readable when someone walks by.
    # Touch still wakes the dashboard, which keeps access intentional and avoids accidental dismissals.
    if datetime.datetime.today().weekday() == CLEANING_DAY:
        logger.info("PIR motion ignored on cleaning day (touch-only wake mode)")
        return

    logger.info("🚨 PIR Sensor: Motion detected - waking display")
    LAST_MOTION_DETECTED_TIME = time.time()  # Update motion timestamp
    LAST_TOUCH_TIME = time.time()  # Reset touch timer
    if DISPLAY_BLANK:
        wake_display("motion", reason="pir_sensor")


def get_brightness():
    current_time = time.time()
    current_time = int(convert_timestamp(current_time, "%H"))

    return 25 if current_time >= 20 or current_time <= 5 else 100


def convert_timestamp(timestamp, param_string):
    """
    :param timestamp: takes a normal integer unix timestamp
    :param param_string: use the default convert timestamp to timestring options
    :return: a converted string from timestamp
    """
    timestring = str(
        datetime.datetime.fromtimestamp(int(timestamp)).astimezone().strftime(param_string)
    )

    return timestring


def draw_wifi_qr_overlay():
    # Standard WIFI: QR payload format - a phone's camera app offers to join
    # the network directly from this, no typing the password out loud.
    _draw_qr_dialog("wlan.exe", "wifi", "WLAN verbinden", f"WIFI:T:WPA;S:{WIFI_SSID};P:{WIFI_PASSWORD};;",
                    [f"SSID: {WIFI_SSID}"])


def handle_wifi_qr_click(mx, my):
    global WIFI_QR_VISIBLE

    if not WIFI_QR_VISIBLE:
        return False
    WIFI_QR_VISIBLE = False
    return True


def games_open():
    """The PLAY menu or one of the party_games games (not MERZ, that has
    its own MERZ_VISIBLE) is on screen."""
    return GAMES_MENU_OPEN or ACTIVE_GAME is not None


def _games_menu_entries():
    """(key, title, description) for every game, menu order."""
    entries = [("merz", "MERZ LECK EIER", "Eier auf den Kanzler werfen")]
    return entries + [(game.NAME, game.NAME, game.DESCRIPTION) for game in party_games.GAMES]


def games_menu_split(today=None):
    """(game of the day, other favourites, folder) as (key, name, icon, record class)
    entries. The game of the day rotates through the favourites by date."""
    entries = [(g.NAME, g.NAME, g.ICON, g) for g in party_games.GAMES]
    entries.append(("merz", "MERZ", "merz", party_games.MerzResult))
    by_name = {name: e for e in entries for name in (e[1],)}
    featured = [by_name[n] for n in GAMES_FEATURED if n in by_name]
    more = [e for e in entries if e not in featured]
    if not featured:
        return None, [], more
    day = (today or datetime.date.today()).toordinal() % len(featured)
    return featured[day], featured[:day] + featured[day + 1:], more


def open_games_menu(page="main"):
    global GAMES_MENU_OPEN, ACTIVE_GAME, GAMES_LAST_ACTIVITY_TS, GAMES_MENU_PAGE
    GAMES_MENU_PAGE = page
    GAMES_MENU_OPEN = True
    ACTIVE_GAME = None
    GAMES_LAST_ACTIVITY_TS = time.time()
    logger.info("Games menu opened")


def close_games(reason):
    global GAMES_MENU_OPEN, ACTIVE_GAME, GAMES_MENU_RECTS, GAMES_MENU_CLOSE_RECT
    if not games_open():
        return
    if ACTIVE_GAME is not None:
        ACTIVE_GAME.save_name()  # closed mid name entry: keep the highscore
        logger.info(f"Game {ACTIVE_GAME.NAME} closed ({reason}), score {ACTIVE_GAME.score}")
    else:
        logger.info(f"Games menu closed ({reason})")
    GAMES_MENU_OPEN = False
    ACTIVE_GAME = None
    GAMES_MENU_RECTS = []
    GAMES_MENU_CLOSE_RECT = None


def start_game(key):
    global GAMES_MENU_OPEN, ACTIVE_GAME, GAMES_LAST_ACTIVITY_TS, GAMES_MENU_RECTS
    GAMES_MENU_OPEN = False
    GAMES_MENU_RECTS = []
    if key == "merz":
        activate_merz_game()
        return
    game_cls = next(g for g in party_games.GAMES if g.NAME == key)
    ACTIVE_GAME = game_cls(
        DISPLAY_WIDTH, DISPLAY_HEIGHT - GAME_TITLE_HEIGHT, FONT_PATH + FONT_MEDIUM, FONT_PATH + FONT_BOLD
    )
    ACTIVE_GAME.show_close = False  # the KiezOS title bar's x closes it
    ACTIVE_GAME.reset(time.time())
    GAMES_LAST_ACTIVITY_TS = time.time()
    logger.info(f"Game {key} started")


def update_games_timeout():
    """Called every frame: close the menu/game on display blank or idle."""
    if not games_open():
        return
    if DISPLAY_BLANK:
        close_games("display-blank")
    elif time.time() - GAMES_LAST_ACTIVITY_TS > (getattr(ACTIVE_GAME, "IDLE_TIMEOUT_SECONDS", None) or GAMES_IDLE_TIMEOUT_SECONDS):
        close_games("idle-timeout")


def draw_games_menu():
    """spiele.exe: the game of the day (big, highlighted), the other favourites
    and a "Mehr Spiele..." folder; the folder page lists the rest."""
    global GAMES_MENU_RECTS, GAMES_MENU_CLOSE_RECT, GAMES_MENU_TITLE_X, GAMES_MENU_BACK_RECT

    if not GAMES_MENU_OPEN:
        return

    win = pygame.Rect(16, 150, DISPLAY_WIDTH - 32, 604)  # down to the taskbar; the top stays out of the emergency corner
    daily, featured, more = games_menu_split()
    folder = GAMES_MENU_PAGE == "more" or daily is None
    inner = K.dialog(tft_surf, win, "spiele.exe" + (" - Mehr Spiele" if folder else ""), icon="folder" if folder else "games")
    GAMES_MENU_TITLE_X = K.close_box(win)
    hint = "Noch mehr Spaß. Oder Prokrastination." if folder else "Doppeltippen... ach, einmal reicht."
    K.t95(tft_surf, hint, 15, (inner.x + 4, inner.y + 2), color=K.F_DARK, bold=False)
    if folder:
        entries = more
    else:
        entries = [daily] + featured
        if more:
            names = ", ".join(e[1] for e in more)
            entries.append(("__more__", "Mehr Spiele...", "folder", names))
    rects = []
    y = inner.y + 28
    gap = 8
    n = len(entries) + (0.25 if not folder else 0)  # the game of the day gets a bit more height
    entry_h = min(104, int((inner.bottom - 48 - y) / n) - gap)
    for i, (key, name, icon, record) in enumerate(entries):
        top_pick = not folder and i == 0
        h = int(entry_h * 1.25) if top_pick else entry_h
        rect = pygame.Rect(inner.x, y, inner.w, h)
        K.button(tft_surf, rect, "")
        if top_pick:
            pygame.draw.rect(tft_surf, K.F_SEL, rect.inflate(-8, -8))
        icon_size = min(80, h - 16)
        image = K.merz_sprite(icon_size) if icon == "merz" else K.menu_icon(icon, icon_size)
        tft_surf.blit(image, image.get_rect(center=(rect.x + 54, rect.centery)))
        ink = (255, 255, 255) if top_pick else K.F_INK
        sub = (255, 230, 150) if top_pick else K.F_DARK
        line = record if isinstance(record, str) else party_games.record_line(record)
        if top_pick:  # three lines in the taller card: label, name, record
            K.t95(tft_surf, "SPIEL DES TAGES:", 15, (rect.x + 112, rect.centery - 31), color=(255, 208, 72))
        K.t95(tft_surf, name, 22, (rect.x + 112, rect.centery - 14 if top_pick else rect.centery - 24), color=ink)
        while K.font(16, False).size(line)[0] > rect.right - 8 - (rect.x + 112):
            line = line[:-4] + "..."
        K.t95(tft_surf, line, 16, (rect.x + 112, rect.centery + 13 if top_pick else rect.centery + 6), color=sub, bold=False)
        rects.append((rect, key))
        y += h + gap
    GAMES_MENU_CLOSE_RECT = K.button(tft_surf, pygame.Rect(inner.right - 130, inner.bottom - 40, 130, 40), "Schließen", size=16)
    GAMES_MENU_BACK_RECT = K.button(tft_surf, pygame.Rect(inner.x, inner.bottom - 40, 130, 40), "< Zurück", size=16) if folder and daily else None
    GAMES_MENU_RECTS = rects


GAME_TITLE_HEIGHT = 36
GAME_TITLE_X = pygame.Rect(DISPLAY_WIDTH - 44, 5, 38, 26).inflate(10, 10)  # = what K.game_title() returns


def draw_active_game():
    """The running party game below a KiezOS title bar (its x closes it)."""
    global GAME_TITLE_X
    if ACTIVE_GAME is None:
        return
    ACTIVE_GAME.update(time.time())
    ACTIVE_GAME.draw(tft_surf.subsurface((0, GAME_TITLE_HEIGHT, DISPLAY_WIDTH, DISPLAY_HEIGHT - GAME_TITLE_HEIGHT)))
    exe = ACTIVE_GAME.NAME.lower().replace(" ", "-").replace("!", "") + ".exe"
    GAME_TITLE_X = K.game_title(tft_surf, exe, ACTIVE_GAME.ICON)


def handle_games_menu_click(mx, my):
    global GAMES_LAST_ACTIVITY_TS
    if not GAMES_MENU_OPEN:
        return False
    GAMES_LAST_ACTIVITY_TS = time.time()
    for rect in (GAMES_MENU_CLOSE_RECT, GAMES_MENU_TITLE_X):
        if rect and rect.collidepoint((mx, my)):
            close_games("close-button")
            return True
    if GAMES_MENU_BACK_RECT and GAMES_MENU_BACK_RECT.collidepoint((mx, my)):
        open_games_menu("main")
        return True
    for rect, key in GAMES_MENU_RECTS:
        if rect.collidepoint((mx, my)):
            if key == "__more__":
                open_games_menu("more")
            else:
                start_game(key)
            return True
    return True  # modal: swallow every other tap


def handle_game_click(mx, my):
    global GAMES_LAST_ACTIVITY_TS
    if ACTIVE_GAME is None:
        return False
    GAMES_LAST_ACTIVITY_TS = time.time()
    if GAME_TITLE_X and GAME_TITLE_X.collidepoint((mx, my)):
        close_games("close-button")
        return True
    if my < GAME_TITLE_HEIGHT:
        return True
    action = ACTIVE_GAME.tap(mx, my - GAME_TITLE_HEIGHT)
    if action == "close":
        close_games("close-button")
    elif action == "menu":
        open_games_menu()
    return True


def activate_merz_game():
    global MERZ_VISIBLE, MERZ_HITS, MERZ_PROJECTILES, MERZ_SPLATS
    global MERZ_TAUNT_TEXT, MERZ_TAUNT_META, MERZ_TAUNT_NEXT_AT, MERZ_LAST_ACTIVITY_TS
    global MERZ_X, MERZ_Y, MERZ_WANDER_TARGET_X, MERZ_WANDER_TARGET_Y, MERZ_NEXT_WANDER_AT
    global MERZ_DODGE_UNTIL, MERZ_HIT_FLINCH_UNTIL, MERZ_LAST_TICK, MERZ_SCALE
    global MERZ_JETS, MERZ_NEXT_JET_AT, MERZ_TAUNT_BAG
    global MERZ_EXPLODED, MERZ_EXPLODED_AT, MERZ_EXPLOSION_PARTICLES, MERZ_FLAME_PARTICLES, MERZ_AMMO
    global MERZ_BURN_HELD, MERZ_BURN_PARTICLES, MERZ_BURN_COMBO_TAPS, MERZ_BURN_UNLOCKED
    global MERZ_PROJECTILE_KIND, MERZ_TIMER_STARTED_AT, MERZ_WIN_SECONDS, MERZ_RESULT, MERZ_BURN_SCORED

    if (
        not GAMES_ENABLED
        or DISPLAY_BLANK
        or EMOTION_PROMPT_VISIBLE
        or EMOTION_RESULTS_VISIBLE
        or QUIZ_STAGE is not None
        or WIFI_QR_VISIBLE
    ):
        return

    now = time.time()
    MERZ_VISIBLE = True
    MERZ_HITS = 0
    MERZ_PROJECTILES = []
    MERZ_SPLATS = []
    MERZ_TAUNT_TEXT = None
    MERZ_TAUNT_META = None
    MERZ_TAUNT_NEXT_AT = now
    MERZ_LAST_ACTIVITY_TS = now
    MERZ_LAST_TICK = now
    MERZ_X = DISPLAY_WIDTH / 2
    MERZ_Y = DISPLAY_HEIGHT * MERZ_BOUNDS_TOP_FRACTION + MERZ_TOP_OFFSET
    MERZ_WANDER_TARGET_X = None
    MERZ_WANDER_TARGET_Y = None
    MERZ_NEXT_WANDER_AT = now
    MERZ_DODGE_UNTIL = 0.0
    MERZ_HIT_FLINCH_UNTIL = 0.0
    MERZ_SCALE = MERZ_SCALE_MAX
    MERZ_JETS = []
    MERZ_NEXT_JET_AT = now + random.uniform(4.0, 9.0)
    MERZ_TAUNT_BAG = []
    MERZ_EXPLODED = False
    MERZ_EXPLODED_AT = 0.0
    MERZ_EXPLOSION_PARTICLES = []
    MERZ_FLAME_PARTICLES = []
    MERZ_AMMO = {"egg": MERZ_AMMO_MAX, "testicle": MERZ_AMMO_MAX}
    MERZ_TIMER_STARTED_AT = None
    MERZ_WIN_SECONDS = 0.0
    MERZ_RESULT = None
    MERZ_BURN_SCORED = False
    MERZ_BURN_HELD = False
    MERZ_BURN_PARTICLES = []
    MERZ_BURN_COMBO_TAPS = []
    MERZ_BURN_UNLOCKED = False  # every new game (incl. replay) needs the combo again
    if MERZ_PROJECTILE_KIND == "burn":
        MERZ_PROJECTILE_KIND = "egg"
    logger.info("Merz game activated")


def dismiss_merz_game(reason):
    global MERZ_VISIBLE, MERZ_ACTION_RECTS, MERZ_BURN_HELD

    if not MERZ_VISIBLE:
        return
    if MERZ_RESULT is not None:
        MERZ_RESULT.save_name()  # closed mid name entry: keep the highscore
    MERZ_VISIBLE = False
    MERZ_ACTION_RECTS = {}
    MERZ_BURN_HELD = False
    logger.info(f"Merz game dismissed ({reason})")


def _merz_sprite_size():
    native_w, native_h = _get_merz_sprite_img().get_size()
    return int(native_w * MERZ_SCALE), int(native_h * MERZ_SCALE)


def _merz_rect():
    width, height = _merz_sprite_size()
    return pygame.Rect(int(MERZ_X - width / 2), int(MERZ_Y - height / 2), width, height)


def _merz_projectile_pos(proj, now):
    t = min(1.0, (now - proj["started_at"]) / proj["duration"])
    sx, sy = proj["start"]
    tx, ty = proj["target"]
    arc_height = 40 + 0.25 * abs(tx - sx)
    x = sx + (tx - sx) * t
    y = sy + (ty - sy) * t - arc_height * math.sin(math.pi * t)
    return x, y, t


def update_merz_game(now, bounds_left, bounds_right, bounds_top, bounds_bottom):
    global MERZ_X, MERZ_Y, MERZ_WANDER_TARGET_X, MERZ_WANDER_TARGET_Y
    global MERZ_NEXT_WANDER_AT, MERZ_LAST_TICK, MERZ_SCALE
    global MERZ_HITS, MERZ_PROJECTILES, MERZ_SPLATS, MERZ_HIT_FLINCH_UNTIL
    global MERZ_TAUNT_TEXT, MERZ_TAUNT_META, MERZ_TAUNT_NEXT_AT, MERZ_TAUNT_BAG
    global MERZ_JETS, MERZ_NEXT_JET_AT
    global MERZ_AMMO, MERZ_EXPLODED, MERZ_EXPLODED_AT, MERZ_EXPLOSION_PARTICLES, MERZ_FLAME_PARTICLES
    global MERZ_BURN_PARTICLES, MERZ_BURN_SPAWN_CARRY, MERZ_BURN_SCORED, MERZ_BURN_HELD
    global MERZ_LAST_ACTIVITY_TS, MERZ_WIN_SECONDS

    dt = max(0.0, min(0.2, now - MERZ_LAST_TICK))  # clamp so a stall can't teleport him
    MERZ_LAST_TICK = now

    for kind in MERZ_AMMO:
        MERZ_AMMO[kind] = min(MERZ_AMMO_MAX, MERZ_AMMO[kind] + MERZ_AMMO_REGEN_PER_SEC * dt)

    if MERZ_EXPLODED:
        # Game's over - nothing left to update but the burst itself
        # settling/fading. Everything else (wander, taunts, jets,
        # projectiles) stays exactly as it was at the moment of victory.
        gravity = 260.0
        still_particles = []
        for p in MERZ_EXPLOSION_PARTICLES:
            p["vy"] += gravity * dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            if now - p["started_at"] < 2.2 and p["y"] < DISPLAY_HEIGHT + 40:
                still_particles.append(p)
        MERZ_EXPLOSION_PARTICLES = still_particles

        # Flames don't fall - no gravity, just drag (so the burst slows
        # down rather than flying off forever) plus a little buoyancy (so
        # they lick upward like real fire) - and fade out on a fixed
        # lifetime rather than leaving the screen.
        drag = 2.2
        buoyancy = 70.0
        still_flames = []
        for p in MERZ_FLAME_PARTICLES:
            p["vx"] *= max(0.0, 1.0 - drag * dt)
            p["vy"] = p["vy"] * max(0.0, 1.0 - drag * dt) - buoyancy * dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            if now - p["started_at"] < MERZ_FLAME_LIFETIME_SECONDS:
                still_flames.append(p)
        MERZ_FLAME_PARTICLES = still_flames
        return

    # Idle wander: pick a new random (x, y) target together once both are
    # reached (a single shared timer, not two independent ones, so he
    # picks a new spot to head toward as one motion rather than each axis
    # retargeting at a different moment), moving faster for a while after
    # a throw lands nearby (the "dodge" reaction, see handle_merz_click()).
    x_arrived = MERZ_WANDER_TARGET_X is None or abs(MERZ_X - MERZ_WANDER_TARGET_X) < 2
    y_arrived = MERZ_WANDER_TARGET_Y is None or abs(MERZ_Y - MERZ_WANDER_TARGET_Y) < 2
    if x_arrived and y_arrived and now >= MERZ_NEXT_WANDER_AT:
        MERZ_WANDER_TARGET_X = random.uniform(bounds_left, bounds_right)
        MERZ_WANDER_TARGET_Y = random.uniform(bounds_top, bounds_bottom)
        MERZ_NEXT_WANDER_AT = now + random.uniform(1.0, 2.5)

    speed = MERZ_WANDER_SPEED * (2.4 if now < MERZ_DODGE_UNTIL else 1.0)
    step = speed * dt
    if MERZ_WANDER_TARGET_X is not None:
        if MERZ_X < MERZ_WANDER_TARGET_X:
            MERZ_X = min(MERZ_WANDER_TARGET_X, MERZ_X + step)
        else:
            MERZ_X = max(MERZ_WANDER_TARGET_X, MERZ_X - step)
    if MERZ_WANDER_TARGET_Y is not None:
        if MERZ_Y < MERZ_WANDER_TARGET_Y:
            MERZ_Y = min(MERZ_WANDER_TARGET_Y, MERZ_Y + step)
        else:
            MERZ_Y = max(MERZ_WANDER_TARGET_Y, MERZ_Y - step)

    # Regrow toward full size while unharmed - a hit shrinks him instantly
    # (below), this just slowly undoes that over a few seconds of peace.
    if MERZ_SCALE < MERZ_SCALE_MAX:
        MERZ_SCALE = min(MERZ_SCALE_MAX, MERZ_SCALE + MERZ_SCALE_REGROW_PER_SEC * dt)

    merz_rect = _merz_rect().inflate(6, 6)  # slightly forgiving hitbox
    still_flying = []
    for proj in MERZ_PROJECTILES:
        x, y, t = _merz_projectile_pos(proj, now)
        if merz_rect.collidepoint((x, y)):
            MERZ_HITS += 1
            MERZ_SCALE = max(MERZ_SCALE_MIN, MERZ_SCALE - MERZ_SCALE_SHRINK_STEP)
            MERZ_SPLATS.append({"pos": (x, y), "started_at": now, "kind": "hit"})
            MERZ_HIT_FLINCH_UNTIL = now + 0.4
            MERZ_AMMO[proj["kind"]] = min(
                MERZ_AMMO_MAX, MERZ_AMMO[proj["kind"]] + MERZ_AMMO_HIT_REFUND
            )
            continue  # resolved - drop the projectile
        if t >= 1.0:
            MERZ_SPLATS.append({"pos": proj["target"], "started_at": now, "kind": "miss"})
            continue  # resolved - drop the projectile
        still_flying.append(proj)
    MERZ_PROJECTILES = still_flying

    # Flamethrower stream (BURN easter egg): spawn from the same nozzle
    # point throws start from, aimed at wherever the finger currently is
    # (pygame's mouse position follows touch drags), with a little spread.
    if MERZ_BURN_HELD:
        MERZ_LAST_ACTIVITY_TS = now  # holding fire counts as activity
        tx, ty = pygame.mouse.get_pos()
        sx, sy = DISPLAY_WIDTH / 2, DISPLAY_HEIGHT - 10
        dist = max(40.0, math.hypot(tx - sx, ty - sy))
        base_angle = math.atan2(ty - sy, tx - sx)
        MERZ_BURN_SPAWN_CARRY += MERZ_BURN_SPAWN_PER_SEC * dt
        while MERZ_BURN_SPAWN_CARRY >= 1.0:
            MERZ_BURN_SPAWN_CARRY -= 1.0
            angle = base_angle + random.uniform(-0.09, 0.09)
            speed = MERZ_BURN_SPEED * random.uniform(0.85, 1.15)
            MERZ_BURN_PARTICLES.append(
                {
                    "x": sx,
                    "y": sy,
                    "vx": math.cos(angle) * speed,
                    "vy": math.sin(angle) * speed,
                    "started_at": now,
                    # Burns out a bit past the finger, not forever.
                    "lifetime": dist / MERZ_BURN_SPEED * random.uniform(1.0, 1.3),
                }
            )
    else:
        MERZ_BURN_SPAWN_CARRY = 0.0

    still_burning = []
    for p in MERZ_BURN_PARTICLES:
        p["x"] += p["vx"] * dt
        p["y"] += p["vy"] * dt
        if merz_rect.collidepoint((p["x"], p["y"])):
            # Absorbed - flames don't pass through him; each one scores.
            if MERZ_HITS < MERZ_WIN_HITS:
                MERZ_HITS += 1
                MERZ_BURN_SCORED = True
                MERZ_SCALE = max(MERZ_SCALE_MIN, MERZ_SCALE - MERZ_SCALE_SHRINK_STEP)
                MERZ_SPLATS.append({"pos": (p["x"], p["y"]), "started_at": now, "kind": "hit"})
                MERZ_HIT_FLINCH_UNTIL = now + 0.4
            continue
        if now - p["started_at"] < p["lifetime"]:
            still_burning.append(p)
    MERZ_BURN_PARTICLES = still_burning

    if MERZ_HITS >= MERZ_WIN_HITS:
        MERZ_EXPLODED = True
        MERZ_EXPLODED_AT = now
        MERZ_WIN_SECONDS = round(now - MERZ_TIMER_STARTED_AT, 1)
        logger.info(f"Merz game won in {MERZ_WIN_SECONDS:.1f}s")
        MERZ_PROJECTILES = []
        MERZ_JETS = []
        MERZ_BURN_PARTICLES = []
        MERZ_BURN_HELD = False
        for _ in range(40):
            angle = random.uniform(0, 2 * math.pi)
            spd = random.uniform(60, 220)
            MERZ_EXPLOSION_PARTICLES.append(
                {
                    "x": MERZ_X,
                    "y": MERZ_Y,
                    "vx": math.cos(angle) * spd,
                    "vy": math.sin(angle) * spd - 60,  # slight upward bias
                    "kind": random.choice(("egg", "testicle")),
                    "started_at": now,
                }
            )
        for _ in range(28):
            angle = random.uniform(0, 2 * math.pi)
            spd = random.uniform(40, 180)
            MERZ_FLAME_PARTICLES.append(
                {
                    "x": MERZ_X,
                    "y": MERZ_Y,
                    "vx": math.cos(angle) * spd,
                    "vy": math.sin(angle) * spd,
                    "started_at": now,
                }
            )
        return
    MERZ_SPLATS = [s for s in MERZ_SPLATS if now - s["started_at"] < 0.6]

    if now >= MERZ_TAUNT_NEXT_AT:
        if MERZ_TAUNT_TEXT is not None:
            MERZ_TAUNT_TEXT = None
            MERZ_TAUNT_META = None
            MERZ_TAUNT_NEXT_AT = now + random.uniform(2.0, 4.0)
        else:
            if not MERZ_TAUNT_BAG:
                MERZ_TAUNT_BAG = list(MERZ_TAUNTS)
                random.shuffle(MERZ_TAUNT_BAG)
            taunt = MERZ_TAUNT_BAG.pop()
            MERZ_TAUNT_TEXT = taunt["text"]
            MERZ_TAUNT_META = (
                f"{taunt['year']}, {taunt['source']}" if "year" in taunt else None
            )
            MERZ_TAUNT_NEXT_AT = now + MERZ_TAUNT_DISPLAY_SECONDS

    # At most one at a time - a background gag, not a swarm. Cruises in
    # mostly horizontally first, then noses up into a climb (like an
    # actual takeoff) until it's off-screen. Deliberately slow so both the
    # jet shape and its speech bubble stay readable during the crossing.
    if not MERZ_JETS and now >= MERZ_NEXT_JET_AT:
        direction = random.choice((-1, 1))
        start_x = -50 if direction == 1 else DISPLAY_WIDTH + 50
        MERZ_JETS.append(
            {
                "x": float(start_x),
                "y": random.uniform(55, DISPLAY_HEIGHT * MERZ_BOUNDS_TOP_FRACTION - 25),
                "direction": direction,
                "speed": random.uniform(20, 26),
                "phase": "cruise",
                # Keeps cruising well past screen-center before climbing,
                # so most of the crossing is flat/level and easy to read -
                # the climb is just the exit, not most of the flight.
                "climb_at_x": DISPLAY_WIDTH / 2 + direction * random.uniform(60, 140),
            }
        )
        MERZ_NEXT_JET_AT = now + random.uniform(18, 32)

    still_flying_jets = []
    for jet in MERZ_JETS:
        if jet["phase"] == "cruise":
            jet["x"] += jet["direction"] * jet["speed"] * dt
            if (jet["direction"] > 0 and jet["x"] >= jet["climb_at_x"]) or (
                jet["direction"] < 0 and jet["x"] <= jet["climb_at_x"]
            ):
                jet["phase"] = "climb"
        else:
            jet["x"] += jet["direction"] * jet["speed"] * MERZ_JET_CLIMB_VX_FACTOR * dt
            jet["y"] -= jet["speed"] * MERZ_JET_CLIMB_VY_FACTOR * dt
        if jet["y"] > -60 and -80 <= jet["x"] <= DISPLAY_WIDTH + 80:
            still_flying_jets.append(jet)
    MERZ_JETS = still_flying_jets


def _draw_merz_jet(jet):
    """Small vector silhouette (not pixel-art like the Merz sprite itself
    - a plane shape is simple enough to draw directly, no photo needed),
    rotated to face its current direction of travel so it visibly noses
    up during the climb phase instead of always looking level."""
    x, y = jet["x"], jet["y"]
    heading = math.atan2(
        -jet["speed"] * MERZ_JET_CLIMB_VY_FACTOR if jet["phase"] == "climb" else 0,
        jet["direction"]
        * (jet["speed"] * MERZ_JET_CLIMB_VX_FACTOR if jet["phase"] == "climb" else jet["speed"]),
    )
    cos_h, sin_h = math.cos(heading), math.sin(heading)

    def rotate(local_points):
        return [
            (x + lx * cos_h - ly * sin_h, y + lx * sin_h + ly * cos_h) for lx, ly in local_points
        ]

    body_color = (235, 235, 240)
    outline = (110, 110, 120)
    fuselage = rotate([(16, 0), (6, -5), (-16, -5), (-22, 0), (-16, 5), (6, 5)])
    wing_top = rotate([(1, -4), (-9, -19), (-3, -4)])
    wing_bottom = rotate([(1, 4), (-9, 19), (-3, 4)])
    tail_fin = rotate([(-16, -5), (-21, -15), (-11, -5)])
    for shape in (tail_fin, wing_bottom, fuselage, wing_top):
        pygame.draw.polygon(tft_surf, body_color, shape)
        pygame.draw.polygon(tft_surf, outline, shape, width=1)
    for wx, wy in rotate([(6, -2), (-2, -2), (-9, -2)]):
        pygame.draw.circle(tft_surf, outline, (int(wx), int(wy)), 1)

    if not (0 <= x <= DISPLAY_WIDTH):
        return  # still off-screen (spawn/despawn margin) - no bubble yet

    bubble_font = FONT_SUPER_TINY
    lines = _quiz_wrap_text(bubble_font, MERZ_JET_TEXT, 130)
    line_height = bubble_font.get_height()
    padding = 4
    bubble_width = max(bubble_font.size(line)[0] for line in lines) + 2 * padding
    bubble_height = len(lines) * line_height + 2 * padding
    bubble_left = min(max(int(x) - bubble_width // 2, 4), DISPLAY_WIDTH - bubble_width - 4)
    bubble_rect = pygame.Rect(bubble_left, int(y) + 14, bubble_width, bubble_height)
    pygame.draw.rect(tft_surf, WHITE, bubble_rect, border_radius=5)
    pygame.draw.rect(tft_surf, (90, 90, 90), bubble_rect, width=1, border_radius=5)
    for i, line in enumerate(lines):
        line_surf = bubble_font.render(line, True, (60, 60, 60))
        tft_surf.blit(
            line_surf,
            line_surf.get_rect(
                midtop=(bubble_rect.centerx, bubble_rect.top + padding + i * line_height)
            ),
        )


def _draw_merz_flame(x, y):
    """Small stacked-triangle flame icon, not an emoji glyph - same reason
    the rest of the UI avoids unicode emoji through a text font (see
    draw_play_button()'s docstring): the font has no emoji glyphs."""
    outer = [(x, y - 14), (x - 7, y + 6), (x + 7, y + 6)]
    mid = [(x, y - 8), (x - 4, y + 6), (x + 4, y + 6)]
    inner = [(x, y - 3), (x - 2, y + 6), (x + 2, y + 6)]
    pygame.draw.polygon(tft_surf, (200, 40, 10), outer)
    pygame.draw.polygon(tft_surf, ORANGE, mid)
    pygame.draw.polygon(tft_surf, YELLOW, inner)


def _draw_merz_flame_particle(x, y, life_frac):
    """One burst flame, drawn on its own per-pixel-alpha surface so it can
    fade out (life_frac: 1.0 = just spawned, 0.0 = about to be removed) -
    same stacked-triangle shape as _draw_merz_flame() but shrinking/fading
    instead of a fixed-size solid icon."""
    _draw_merz_flame_shape(x, y, 6 + 8 * life_frac, int(255 * life_frac))


def _draw_merz_flame_shape(x, y, size, alpha):
    alpha = max(0, min(255, alpha))
    surf_size = int(size * 2.4)
    surf = pygame.Surface((surf_size, surf_size), pygame.SRCALPHA)
    cx = cy = surf_size / 2
    outer = [(cx, cy - size), (cx - size * 0.5, cy + size * 0.45), (cx + size * 0.5, cy + size * 0.45)]
    mid = [(cx, cy - size * 0.6), (cx - size * 0.3, cy + size * 0.45), (cx + size * 0.3, cy + size * 0.45)]
    inner = [(cx, cy - size * 0.25), (cx - size * 0.15, cy + size * 0.45), (cx + size * 0.15, cy + size * 0.45)]
    pygame.draw.polygon(surf, (200, 40, 10, alpha), outer)
    pygame.draw.polygon(surf, (*ORANGE, alpha), mid)
    pygame.draw.polygon(surf, (*YELLOW, alpha), inner)
    tft_surf.blit(surf, (x - surf_size / 2, y - surf_size / 2))


def _draw_merz_explosion(now):
    """Win screen: the hit-burst particles and outward-flying flames
    (spawned once in update_merz_game() when MERZ_HITS reaches
    MERZ_WIN_HITS) plus a banner - drawn every frame while MERZ_EXPLODED is
    True, replacing the normal sprite/throw UI entirely (see
    draw_merz_overlay()). The banner is held back MERZ_WIN_TEXT_DELAY_SECONDS
    so it doesn't immediately cover up the burst it's celebrating, and
    MERZ_RESULT_DELAY_SECONDS later the party_games.MerzResult panel (name
    entry, Bestenliste) replaces it."""
    global MERZ_RESULT
    for p in MERZ_EXPLOSION_PARTICLES:
        _draw_merz_projectile(p["x"], p["y"], p["kind"])
    for p in MERZ_FLAME_PARTICLES:
        life_frac = max(0.0, 1.0 - (now - p["started_at"]) / MERZ_FLAME_LIFETIME_SECONDS)
        _draw_merz_flame_particle(p["x"], p["y"], life_frac)

    if now - MERZ_EXPLODED_AT < MERZ_WIN_TEXT_DELAY_SECONDS:
        return
    if now - MERZ_EXPLODED_AT >= MERZ_WIN_TEXT_DELAY_SECONDS + MERZ_RESULT_DELAY_SECONDS:
        if MERZ_RESULT is None:
            MERZ_RESULT = party_games.MerzResult(
                DISPLAY_WIDTH, DISPLAY_HEIGHT, FONT_PATH + FONT_MEDIUM, FONT_PATH + FONT_BOLD,
                MERZ_WIN_SECONDS, now, burn=MERZ_BURN_SCORED,
            )
        MERZ_RESULT.update(now)
        MERZ_RESULT.draw(tft_surf)
        return

    title_font = FONT_BIG_BOLD
    title_lines = _quiz_wrap_text(title_font, "MERZ HAT EIER GELECKT!", int(DISPLAY_WIDTH * 0.8))
    line_height = title_font.get_height()
    banner_width = max(title_font.size(line)[0] for line in title_lines) + 40
    banner_height = len(title_lines) * line_height + 20
    banner_rect = pygame.Rect(0, 0, banner_width, banner_height)
    banner_rect.center = (DISPLAY_WIDTH // 2, int(DISPLAY_HEIGHT * 0.3))
    pygame.draw.rect(tft_surf, (255, 244, 214), banner_rect, border_radius=14)
    pygame.draw.rect(tft_surf, ORANGE, banner_rect, width=3, border_radius=14)
    for i, line in enumerate(title_lines):
        line_surf = title_font.render(line, True, (180, 40, 10))
        tft_surf.blit(
            line_surf,
            line_surf.get_rect(midtop=(banner_rect.centerx, banner_rect.top + 10 + i * line_height)),
        )
    _draw_merz_flame(banner_rect.left - 16, banner_rect.centery)
    _draw_merz_flame(banner_rect.right + 16, banner_rect.centery)

    sub_text = FONT_SMALL_BOLD.render(f"{MERZ_WIN_HITS} TREFFER IN {MERZ_WIN_SECONDS:.1f} s!", True, WHITE)
    sub_bg = sub_text.get_rect(midtop=(DISPLAY_WIDTH // 2, banner_rect.bottom + 12)).inflate(16, 8)
    pygame.draw.rect(tft_surf, (30, 30, 30), sub_bg, border_radius=8)
    tft_surf.blit(sub_text, sub_text.get_rect(center=sub_bg.center))


# Drawn at 1/MERZ_REICHSTAG_PIXEL_SIZE resolution and scaled up
# nearest-neighbour, to match the pixelated Merz sprite (1 = smooth, with a
# readable inscription - Ju picked the pixel look).
MERZ_REICHSTAG_PIXEL_SIZE = 3
_MERZ_REICHSTAG_CACHE = {}  # (width, ground_y) -> (pre-rendered surface, top)


def _draw_reichstag(ground_y):
    """Reichstag backdrop sitting on the lawn: sandstone front with the four
    corner towers, the columned portico with "DEM DEUTSCHEN VOLKE" under
    its pediment, the glass dome on top and flags on the towers. Static,
    so it's rendered once and cached."""
    key = (DISPLAY_WIDTH, ground_y)
    if key not in _MERZ_REICHSTAG_CACHE:
        _MERZ_REICHSTAG_CACHE[key] = _render_reichstag(ground_y)
    surf, top = _MERZ_REICHSTAG_CACHE[key]
    tft_surf.blit(surf, (0, top))


def _render_reichstag(ground_y):
    k = MERZ_REICHSTAG_PIXEL_SIZE
    w = DISPLAY_WIDTH
    height = 190  # dome top down to the lawn
    top = ground_y - height
    surf = pygame.Surface((w // k, height // k), pygame.SRCALPHA)

    def y(v):  # px above the lawn -> surface row
        return (height - v) / k

    def rect(color, x0, x1, y_top, y_bottom=0):
        pygame.draw.rect(surf, color, pygame.Rect(x0 * w / k, y(y_top), (x1 - x0) * w / k + 1, (y_top - y_bottom) / k + 1))

    stone, stone_dark, stone_light = (200, 184, 150), (160, 144, 114), (222, 208, 176)
    window, glass, glass_line = (80, 84, 100), (200, 230, 245), (120, 150, 170)

    # Glass dome (behind everything else) on its drum.
    cx = w / 2 / k
    rect(stone_dark, 0.40, 0.60, 128, 100)
    dome = pygame.Rect(0, 0, 0.26 * w / k, 110 / k)
    dome.center = (cx, y(128))
    pygame.draw.ellipse(surf, glass, dome)
    pygame.draw.ellipse(surf, glass_line, dome, width=max(1, 2 // k))
    for i in range(1, 6):  # meridians
        rib = dome.inflate(-dome.width * i / 6, 0)
        pygame.draw.ellipse(surf, glass_line, rib, width=1)
    for v in (140, 152, 164):  # rings, clipped to the dome's outline
        half = dome.width / 2 * math.sqrt(max(0.0, 1 - ((y(v) - dome.centery) / (dome.height / 2)) ** 2))
        pygame.draw.line(surf, glass_line, (cx - half, y(v)), (cx + half, y(v)))
    rect(stone_dark, 0.36, 0.64, 130, 100)  # hides the dome's lower half
    pygame.draw.rect(surf, glass, pygame.Rect(cx - 3 / k, y(186), 6 / k + 1, 4 / k + 1))  # lantern

    # Main block with two window rows.
    rect(stone, 0.06, 0.94, 96)
    rect(stone_dark, 0.06, 0.94, 100, 94)  # cornice
    rect(stone_dark, 0.06, 0.94, 14)  # plinth
    for row_top in (80, 50):
        for i in range(14):
            x0 = 0.19 + i * 0.045
            if 0.33 < x0 < 0.64:
                continue  # portico in front
            rect(window, x0, x0 + 0.022, row_top, row_top - 18)

    # Corner towers.
    for x0 in (0.02, 0.84):
        rect(stone_light, x0, x0 + 0.14, 120)
        rect(stone_dark, x0 - 0.005, x0 + 0.145, 124, 116)
        rect(stone_dark, x0, x0 + 0.14, 14)
        for row_top in (104, 80, 50):
            rect(window, x0 + 0.035, x0 + 0.06, row_top, row_top - 16)
            rect(window, x0 + 0.08, x0 + 0.105, row_top, row_top - 16)
        # Flag: black / red / gold.
        pole_x = x0 + 0.07
        rect(stone_dark, pole_x, pole_x + 0.004, 160, 124)
        for i, color in enumerate(((20, 20, 20), (220, 0, 0), (255, 204, 0))):
            rect(color, pole_x + 0.004, pole_x + 0.07, 160 - i * 6, 154 - i * 6)

    # Portico: pediment, inscription band, six columns, steps.
    left, right = 0.33, 0.67
    rect(stone_light, left, right, 108, 90)
    pygame.draw.polygon(
        surf, stone_light, [(left * w / k, y(108)), (right * w / k, y(108)), (cx, y(132))]
    )
    pygame.draw.polygon(
        surf, stone_dark, [(left * w / k, y(108)), (right * w / k, y(108)), (cx, y(132))], width=1
    )
    if k == 1:
        label = pygame.font.Font(FONT_PATH + FONT_BOLD, 9).render("DEM DEUTSCHEN VOLKE", True, (90, 80, 60))
        surf.blit(label, label.get_rect(center=(cx, y(99))))
    else:
        rect((120, 108, 84), left + 0.04, right - 0.04, 101, 97)  # inscription as a line
    rect(stone_dark, left, right, 90, 86)
    for i in range(6):
        x0 = left + 0.02 + i * (right - left - 0.06) / 5
        rect(stone_light, x0, x0 + 0.022, 86, 14)
        rect(stone_dark, x0 + 0.017, x0 + 0.022, 86, 14)  # shadow side
    rect(window, left + 0.03, right - 0.03, 70, 14)  # dark hall behind the columns
    for i in range(6):  # columns again, in front of the dark hall
        x0 = left + 0.02 + i * (right - left - 0.06) / 5
        rect(stone_light, x0, x0 + 0.022, 86, 14)
        rect(stone_dark, x0 + 0.017, x0 + 0.022, 86, 14)
    for i, (x0, x1) in enumerate(((0.30, 0.70), (0.31, 0.69), (0.32, 0.68))):
        rect(stone_dark if i % 2 else stone, x0, x1, 14 - i * 4, 10 - i * 4)

    if k > 1:
        surf = pygame.transform.scale(surf, (surf.get_width() * k, surf.get_height() * k))
    return surf, top


def _merz_hud_rects():
    """Hits and timer, side by side under the title bar. Fixed widths so
    they don't jitter while the numbers change."""
    hits_rect = pygame.Rect(DISPLAY_WIDTH // 2 - 118, 44, 110, 36)
    time_rect = pygame.Rect(DISPLAY_WIDTH // 2 + 8, 44, 110, 36)
    return hits_rect, time_rect


def _draw_merz_hud(seconds):
    """Sunken KiezOS display fields, purple digits like uhr.exe."""
    hits_rect, time_rect = _merz_hud_rects()
    for rect, text in ((hits_rect, f"{MERZ_HITS}/{MERZ_WIN_HITS}"), (time_rect, f"{seconds:.1f} s")):
        K.bevel(tft_surf, rect, sunken=True, face=(30, 14, 50))
        K.t95(tft_surf, text, 20, rect.center, color=K.CLOCK_ON, anchor="center")


def _draw_merz_sprite(expression):
    """No facial-expression variants (there's only ever one source photo,
    unlike the old hand-drawn grid which could swap a mouth row) - "hit"
    instead gets a small impact-star overlay near the frame."""
    rect = _merz_rect()
    # blit() positions by rect but never scales to it - the image itself
    # has to be resized to the current (hit-shrink/regrow) scale first.
    img = pygame.transform.smoothscale(_get_merz_sprite_img(), rect.size)
    tft_surf.blit(img, rect)  # transparent-background cutout, no card border

    if expression == "hit":
        for dx, dy in ((-8, -6), (10, -2), (2, -12)):
            star_center = (rect.left + dx, rect.top + dy)
            star_points = []
            for i in range(8):
                angle = math.pi / 4 * i
                r = 6 if i % 2 == 0 else 2.5
                star_points.append(
                    (star_center[0] + r * math.cos(angle), star_center[1] + r * math.sin(angle))
                )
            pygame.draw.polygon(tft_surf, YELLOW, star_points)
            pygame.draw.polygon(tft_surf, ORANGE, star_points, width=1)


def _draw_merz_projectile(x, y, kind):
    cx, cy = int(x), int(y)
    if kind == "egg":
        # A plain ellipse reads as a blob at small sizes - eggs are
        # tapered (narrower top, rounder bottom), so build the outline
        # from two overlapping circles of different radii instead.
        shell = (250, 245, 225)
        outline = (150, 130, 90)
        top_r, bottom_r = 6, 9
        top_c, bottom_c = (cx, cy - 5), (cx, cy + 4)
        pygame.draw.circle(tft_surf, shell, top_c, top_r)
        pygame.draw.circle(tft_surf, shell, bottom_c, bottom_r)
        pygame.draw.polygon(
            tft_surf,
            shell,
            [
                (top_c[0] - top_r, top_c[1]),
                (bottom_c[0] - bottom_r, bottom_c[1]),
                (bottom_c[0] + bottom_r, bottom_c[1]),
                (top_c[0] + top_r, top_c[1]),
            ],
        )
        pygame.draw.circle(tft_surf, outline, top_c, top_r, width=1)
        pygame.draw.circle(tft_surf, outline, bottom_c, bottom_r, width=1)
        pygame.draw.circle(tft_surf, WHITE, (cx - 3, cy - 6), 2)  # shine
    else:
        skin = (222, 178, 150)
        pygame.draw.circle(tft_surf, skin, (cx - 6, cy), 8)
        pygame.draw.circle(tft_surf, skin, (cx + 6, cy), 8)
        pygame.draw.circle(tft_surf, DARK_GRAY, (cx - 6, cy), 8, width=1)
        pygame.draw.circle(tft_surf, DARK_GRAY, (cx + 6, cy), 8, width=1)


def _draw_merz_speech_bubble():
    if not MERZ_TAUNT_TEXT:
        return
    mouth_x = int(MERZ_X)
    bubble_font = FONT_TINY
    meta_font = FONT_SUPER_TINY
    max_width = int(DISPLAY_WIDTH * 0.62)
    lines = _quiz_wrap_text(bubble_font, MERZ_TAUNT_TEXT, max_width)
    line_height = bubble_font.get_height()
    text_width = max(bubble_font.size(line)[0] for line in lines)

    # Real quotes carry a "year, source" citation, rendered smaller below
    # the quote itself (see MERZ_TAUNTS/MERZ_TAUNT_META) - plain reaction
    # lines have no metadata and skip this entirely.
    meta_height = 0
    if MERZ_TAUNT_META:
        meta_height = meta_font.get_height() + 4
        text_width = max(text_width, meta_font.size(MERZ_TAUNT_META)[0])

    padding = 8
    bubble_width = text_width + 2 * padding
    bubble_height = len(lines) * line_height + meta_height + 2 * padding

    # Anchored above the sprite's own top edge, not the mouth (which sits
    # inside the photo) - anchoring the box at the mouth put most of the
    # bubble on top of the image instead of above it. The tail points at
    # the top of his head rather than the actual mouth, so it doesn't
    # spear down across the picture itself.
    # Always above him (below would block the throws), even if a long quote
    # then covers the hits/timer row while he's up there.
    sprite_top = _merz_rect().top
    bubble_left = min(max(mouth_x - bubble_width // 2, 6), DISPLAY_WIDTH - bubble_width - 6)
    bubble_bottom = sprite_top - 14
    bubble_top = max(bubble_bottom - bubble_height, MERZ_HUD_BOTTOM + 6)  # never under the title bar/HUD
    bubble_rect = pygame.Rect(bubble_left, bubble_top, bubble_width, bubble_height)

    pygame.draw.rect(tft_surf, WHITE, bubble_rect, border_radius=8)
    pygame.draw.rect(tft_surf, BLACK, bubble_rect, width=2, border_radius=8)
    # No tail once the clamped bubble reaches down over his head - it would
    # point upwards through the text.
    tail_tip = (mouth_x, sprite_top + 6)
    tail_base_x = min(max(mouth_x, bubble_rect.left + 10), bubble_rect.right - 10)
    if bubble_rect.bottom < tail_tip[1]:
        pygame.draw.polygon(
            tft_surf,
            WHITE,
            [(tail_base_x - 6, bubble_rect.bottom), (tail_base_x + 6, bubble_rect.bottom), tail_tip],
        )
        pygame.draw.polygon(
            tft_surf,
            BLACK,
            [(tail_base_x - 6, bubble_rect.bottom), tail_tip, (tail_base_x + 6, bubble_rect.bottom)],
            width=1,
        )

    for i, line in enumerate(lines):
        line_surf = bubble_font.render(line, True, BLACK)
        tft_surf.blit(
            line_surf,
            line_surf.get_rect(
                midtop=(bubble_rect.centerx, bubble_rect.top + padding + i * line_height)
            ),
        )

    if MERZ_TAUNT_META:
        meta_surf = meta_font.render(MERZ_TAUNT_META, True, DARK_GRAY)
        tft_surf.blit(
            meta_surf,
            meta_surf.get_rect(
                midtop=(bubble_rect.centerx, bubble_rect.top + padding + len(lines) * line_height + 4)
            ),
        )


def draw_merz_overlay():
    global MERZ_ACTION_RECTS

    if not MERZ_VISIBLE:
        return

    now = time.time()
    ground_y = int(DISPLAY_HEIGHT * 0.82)
    bounds_left = 40
    bounds_right = DISPLAY_WIDTH - 40
    # Kept well above the ground/building backdrop and below the top-corner
    # UI (hit counter, close button) regardless of screen aspect ratio -
    # bounds_top isn't right at the very top edge on purpose, so he can't
    # wander up into/behind that UI.
    bounds_top = DISPLAY_HEIGHT * MERZ_BOUNDS_TOP_FRACTION + MERZ_TOP_OFFSET
    bounds_bottom = DISPLAY_HEIGHT * MERZ_BOUNDS_BOTTOM_FRACTION + MERZ_TOP_OFFSET
    update_merz_game(now, bounds_left, bounds_right, bounds_top, bounds_bottom)

    tft_surf.fill((150, 200, 235))  # sky
    pygame.draw.rect(tft_surf, (90, 150, 90), (0, ground_y, DISPLAY_WIDTH, DISPLAY_HEIGHT - ground_y))

    _draw_reichstag(ground_y)

    for jet in MERZ_JETS:  # behind him, background gag only
        _draw_merz_jet(jet)

    if MERZ_EXPLODED:
        seconds = MERZ_WIN_SECONDS
    elif MERZ_TIMER_STARTED_AT is None:
        seconds = 0.0
    else:
        seconds = now - MERZ_TIMER_STARTED_AT
    _draw_merz_hud(seconds)

    if MERZ_EXPLODED:
        _draw_merz_explosion(now)
        MERZ_ACTION_RECTS = {"close": K.game_title(tft_surf, "merz.exe", "merz")}
        return

    expression = "neutral"
    if now < MERZ_HIT_FLINCH_UNTIL:
        expression = "hit"
    elif now < MERZ_DODGE_UNTIL:
        expression = "dodge"
    _draw_merz_sprite(expression)

    for proj in MERZ_PROJECTILES:
        x, y, _ = _merz_projectile_pos(proj, now)
        _draw_merz_projectile(x, y, proj["kind"])

    # Flamethrower stream: small and solid at the nozzle, growing and
    # fading as it travels - the reverse of the win-burst flames.
    for p in MERZ_BURN_PARTICLES:
        age_frac = min(1.0, (now - p["started_at"]) / p["lifetime"])
        _draw_merz_flame_shape(p["x"], p["y"], 5 + 13 * age_frac, int(255 * (1.0 - age_frac**3)))

    for splat in MERZ_SPLATS:
        age = now - splat["started_at"]
        fade = max(0.0, 1.0 - age / 0.6)
        radius = int(4 + 14 * (age / 0.6))
        color = YELLOW if splat["kind"] == "hit" else DARK_GRAY
        splat_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(splat_surf, (*color, int(255 * fade)), (radius, radius), radius, width=2)
        tft_surf.blit(splat_surf, (splat["pos"][0] - radius, splat["pos"][1] - radius))

    # Two plain-text (not emoji - see draw_play_button()'s docstring on why)
    # selectable pills side by side, the active one filled in - picking
    # which of the two you're currently throwing, not a throw trigger
    # itself (that used to be one button labelled "WIRF: ...", which read
    # like it was the thing you tap to throw). Ammo count shown per pill
    # (a magazine each, see MERZ_AMMO) - dimmed when that kind is empty,
    # still tappable to switch to it but throwing it does nothing until it
    # regenerates. Built bottom-up (button row first, hint text positioned
    # off its actual top) so the hint can't end up overlapping the buttons
    # regardless of font metrics.
    def _ammo_label(name, kind):
        count = MERZ_AMMO[kind]
        if count < 1.0:
            # Empty - show seconds left until the next shot regenerates
            # instead of a static "(0)" that gives no sense of when
            # tapping will work again.
            wait_s = math.ceil((1.0 - count) / MERZ_AMMO_REGEN_PER_SEC)
            return f"{name} (0, {wait_s}s)"
        return f"{name} ({int(count)})"

    egg_rect = pygame.Rect(30, DISPLAY_HEIGHT - 58, 200, 50)
    testicle_rect = pygame.Rect(DISPLAY_WIDTH - 230, DISPLAY_HEIGHT - 58, 200, 50)
    buttons_top = egg_rect.top
    pills = [(egg_rect, "egg"), (testicle_rect, "testicle")]
    # Hidden BURN button (see MERZ_BURN_COMBO), centered just above the
    # EIER/KLÖTEN row once unlocked - three side by side don't fit the 480px
    # portrait screen with the ammo counts in the labels.
    if MERZ_BURN_UNLOCKED:
        burn_rect = pygame.Rect(DISPLAY_WIDTH // 2 - 90, buttons_top - 62, 180, 50)
        pills.append((burn_rect, "burn"))
        buttons_top = burn_rect.top

    for rect, kind in pills:
        selected = MERZ_PROJECTILE_KIND == kind
        if kind == "burn":
            K.bevel(tft_surf, rect, sunken=selected, face=(255, 196, 120) if selected else (255, 230, 200))
            K.t95(tft_surf, "BURN", 24, rect.move(1, 1).center if selected else rect.center, color=(180, 40, 10), anchor="center")
            for fx in (rect.x + 22, rect.right - 22):  # little pixel flames
                cy = rect.centery
                pygame.draw.polygon(tft_surf, (255, 120, 30), [(fx - 8, cy + 12), (fx - 6, cy - 4), (fx - 1, cy + 2), (fx + 1, cy - 14), (fx + 6, cy), (fx + 8, cy + 12)])
                pygame.draw.polygon(tft_surf, (255, 220, 80), [(fx - 4, cy + 12), (fx - 1, cy + 2), (fx + 2, cy - 4), (fx + 4, cy + 12)])
            continue
        label = _ammo_label("EIER" if kind == "egg" else "KLÖTEN", kind)
        K.button(tft_surf, rect, label, size=K.fit_size(label, rect.w - 12, sizes=(22, 19, 16)),
                 pressed=selected, enabled=MERZ_AMMO[kind] >= 1.0)

    # Lightweight hint, not a button - tapping anywhere on screen throws,
    # this just explains that once, it doesn't do anything itself.
    hint = "Halten, um zu brennen!" if MERZ_PROJECTILE_KIND == "burn" else "Tippe irgendwo, um zu werfen!"
    hint_text = FONT_SUPER_TINY.render(hint, True, (60, 60, 60))
    tft_surf.blit(
        hint_text, hint_text.get_rect(midbottom=(DISPLAY_WIDTH // 2, buttons_top - 12))
    )

    # Drawn last/on top of everything, including the hits/timer row - he can
    # wander close enough to the top that the row would otherwise sit in
    # front of (and obscure) the bubble.
    _draw_merz_speech_bubble()

    MERZ_ACTION_RECTS = {"close": K.game_title(tft_surf, "merz.exe", "merz")}
    for rect, kind in pills:
        MERZ_ACTION_RECTS[f"select_{kind}"] = rect


def _merz_register_pill_tap(kind, now):
    """Feed one EIER/KLÖTEN pill tap into the BURN combo detector - unlocks
    and selects BURN once the last len(MERZ_BURN_COMBO) taps match it with
    no gap longer than MERZ_BURN_COMBO_MAX_GAP_SECONDS."""
    global MERZ_BURN_COMBO_TAPS, MERZ_BURN_UNLOCKED, MERZ_PROJECTILE_KIND

    if MERZ_BURN_COMBO_TAPS and now - MERZ_BURN_COMBO_TAPS[-1][1] > MERZ_BURN_COMBO_MAX_GAP_SECONDS:
        MERZ_BURN_COMBO_TAPS = []
    MERZ_BURN_COMBO_TAPS = (MERZ_BURN_COMBO_TAPS + [(kind, now)])[-len(MERZ_BURN_COMBO):]
    if [k for k, _ in MERZ_BURN_COMBO_TAPS] == MERZ_BURN_COMBO:
        MERZ_BURN_COMBO_TAPS = []
        MERZ_BURN_UNLOCKED = True
        MERZ_PROJECTILE_KIND = "burn"
        logger.info("Merz game: BURN unlocked")


def handle_merz_release():
    global MERZ_BURN_HELD
    MERZ_BURN_HELD = False


def handle_merz_click(mx, my):
    global MERZ_PROJECTILE_KIND, MERZ_PROJECTILES, MERZ_LAST_ACTIVITY_TS, MERZ_AMMO
    global MERZ_WANDER_TARGET_X, MERZ_WANDER_TARGET_Y, MERZ_NEXT_WANDER_AT, MERZ_DODGE_UNTIL
    global MERZ_BURN_HELD, MERZ_TIMER_STARTED_AT

    if not MERZ_VISIBLE:
        return False

    MERZ_LAST_ACTIVITY_TS = time.time()

    close_rect = MERZ_ACTION_RECTS.get("close")
    if close_rect and close_rect.collidepoint((mx, my)):
        dismiss_merz_game("close-button")
        return True

    if MERZ_EXPLODED:
        # Won - only the result panel (name keyboard, NOCHMAL/MENÜ) does
        # anything now, throwing is moot until he's reborn.
        action = MERZ_RESULT.tap(mx, my) if MERZ_RESULT is not None else None
        if action == "again":
            activate_merz_game()
        elif action == "menu":
            dismiss_merz_game("menu-button")
            open_games_menu()
        elif action == "close":  # its x hitbox is a bit bigger than MERZ's own
            dismiss_merz_game("close-button")
        return True

    for kind in ("egg", "testicle", "burn"):
        rect = MERZ_ACTION_RECTS.get(f"select_{kind}")
        if rect and rect.collidepoint((mx, my)):
            MERZ_PROJECTILE_KIND = kind
            if kind != "burn":
                # May flip MERZ_PROJECTILE_KIND straight to "burn".
                _merz_register_pill_tap(kind, time.time())
            return True

    if MERZ_TIMER_STARTED_AT is None:
        MERZ_TIMER_STARTED_AT = time.time()  # first throw/flame starts the clock

    if MERZ_PROJECTILE_KIND == "burn":
        MERZ_BURN_HELD = True  # stream runs in update_merz_game() until release
        return True

    if MERZ_AMMO[MERZ_PROJECTILE_KIND] < 1.0:
        return True  # empty magazine for this kind - tap swallowed, nothing thrown

    now = time.time()
    MERZ_AMMO[MERZ_PROJECTILE_KIND] -= 1.0
    start = (DISPLAY_WIDTH / 2, DISPLAY_HEIGHT - 10)
    MERZ_PROJECTILES.append(
        {
            "start": start,
            "target": (mx, my),
            "started_at": now,
            "duration": random.uniform(0.6, 0.8),
            "kind": MERZ_PROJECTILE_KIND,
        }
    )

    # If the throw looks like it'll land near him, he tries to juke out of
    # the way (in both directions now that he wanders vertically too) -
    # reroute his wander target away from the incoming spot and speed him
    # up for a bit (see the MERZ_DODGE_UNTIL check in update_merz_game()).
    # Not guaranteed: sometimes he just eats it.
    if math.hypot(mx - MERZ_X, my - MERZ_Y) < 80 and random.random() < 0.7:
        away_x = -1 if mx >= MERZ_X else 1
        away_y = -1 if my >= MERZ_Y else 1
        jump = random.uniform(70, 140)
        bounds_left, bounds_right = 40, DISPLAY_WIDTH - 40
        bounds_top = DISPLAY_HEIGHT * MERZ_BOUNDS_TOP_FRACTION + MERZ_TOP_OFFSET
        bounds_bottom = DISPLAY_HEIGHT * MERZ_BOUNDS_BOTTOM_FRACTION + MERZ_TOP_OFFSET
        MERZ_WANDER_TARGET_X = min(max(MERZ_X + away_x * jump, bounds_left), bounds_right)
        MERZ_WANDER_TARGET_Y = min(max(MERZ_Y + away_y * jump * 0.5, bounds_top), bounds_bottom)
        MERZ_NEXT_WANDER_AT = now
        MERZ_DODGE_UNTIL = now + 0.5

    return True


def _moabeats_scroll_offset(max_offset):
    """Time-based (no per-line state to track) ping-pong phase for an
    overflowing MoaBeats panel line: pause at the start, scroll left to
    reveal the cut-off tail, pause there, scroll back to the start (instead
    of snapping), repeat. Self-corrects on its own if the content changes
    mid-cycle since there's no stored state to go stale.
    """
    if max_offset <= 0:
        return 0

    scroll_speed = 30 * ZOOM  # px/sec
    pause = 2.0  # seconds held at each end
    scroll_duration = max_offset / scroll_speed
    cycle = 2 * pause + 2 * scroll_duration

    t = time.time() % cycle
    if t < pause:
        return 0
    t -= pause
    if t < scroll_duration:
        return t * scroll_speed
    t -= scroll_duration
    if t < pause:
        return max_offset
    t -= pause
    return max_offset - t * scroll_speed


def draw_cleaning_day_screen():
    """The always-on cleaning-day screensaver (shown instead of the blanked
    display) - the same "Putzdienste" screen the PUTZEN pill opens."""
    draw_chore_screen()


def draw_chore_overlay():
    """The "Putzdienste" screen on the awake dashboard, opened via PUTZEN."""
    if CHORE_LIST_OPEN:
        draw_chore_screen()


def draw_chore_screen():
    """One screen for both entry points: putzdienste.exe with the chore list
    (or the detail screen), "Schließen" at the bottom, and on cleaning day the
    "IT'S CLEANING DAY, YAY!" WordArt on top - in the (non-tappable)
    emergency-exit band, everything tappable sits below it."""
    global CLEANING_CHORE_ROW_RECTS, CHORE_LIST_CLOSE_RECT, CHORE_LIST_TITLE_X

    CLEANING_CHORE_ROW_RECTS = []
    tft_surf.blit(K.desktop(), (0, 0))
    if CHORE_DETAIL_ID is not None:
        draw_chore_detail()
        return

    cleaning_day = datetime.datetime.today().weekday() == CLEANING_DAY
    top = 16
    if cleaning_day:
        for x, y in [(30, 30), (440, 40), (80, 150), (410, 150), (240, 18)]:
            pygame.draw.line(tft_surf, K.SUN, (x - 8, y), (x + 8, y), 2)
            pygame.draw.line(tft_surf, K.SUN, (x, y - 8), (x, y + 8), 2)
        K.wordart(tft_surf, "IT'S CLEANING", 42, (DISPLAY_WIDTH // 2, 62))
        K.wordart(tft_surf, "DAY, YAY!", 50, (DISPLAY_WIDTH // 2, 128))
        top = EMERGENCY_EXIT_MAX_Y + 6
    if not config.get("MOABEATS", {}).get("ENABLED", False):
        # No MoaBeats: nothing to list - just the cleaning-day headline
        # (only the screensaver gets here; Putzdienste isn't in the Start menu without it).
        CHORE_LIST_CLOSE_RECT = None
        CHORE_LIST_TITLE_X = None
        return

    with_taskbar = CHORE_LIST_OPEN and not DISPLAY_BLANK
    win = pygame.Rect(8, top, DISPLAY_WIDTH - 16, DISPLAY_HEIGHT - top - (48 if with_taskbar else 8))
    inner = K.window(tft_surf, win, "putzdienste.exe", icon="broom")
    CHORE_LIST_TITLE_X = K.close_box(win)
    # Exactly what the API's cleaning_chores holds (moabeatstastic
    # backend/routes/display.py): Putzplan chores, not completed, due today
    # or overdue. No per-chore due date in the payload, so this describes
    # the whole list rather than marking single chores as overdue.
    K.t95(tft_surf, "Heute fällig oder überfällig", 16, (inner.x + 4, inner.y + 2), color=K.F_DARK, bold=False)
    CHORE_LIST_CLOSE_RECT = K.button(tft_surf, pygame.Rect(inner.right - 150, inner.bottom - 52, 150, 52), "Schließen", size=17)
    lv = pygame.Rect(inner.x, max(inner.y + 24, EMERGENCY_EXIT_MAX_Y + 4), inner.w, 0)
    lv.height = inner.bottom - 60 - lv.y
    K.bevel(tft_surf, lv, sunken=True, face=K.F_PAPER)

    with MOABEATS_STATUS_LOCK:
        has_chores = bool(MOABEATS_STATUS.get("cleaning_chores"))
    if has_chores:
        _draw_chore_list(lv.y + 4, lv.bottom - 4)
    elif not (CHORE_LIST_OPEN and CHORE_DETAIL_REFRESHING):
        K.t95(tft_surf, "Nichts fällig oder überfällig", 18, lv.center, color=K.F_DARK, anchor="center")

    # The list-level refetch only happens when opened via the Start menu;
    # the screensaver has no refresh/error state of its own.
    status = None
    if CHORE_LIST_OPEN and CHORE_DETAIL_ERROR:
        status, status_color = CHORE_DETAIL_ERROR, K.F_LATE
    elif CHORE_LIST_OPEN and CHORE_DETAIL_REFRESHING:
        status, status_color = "Aktualisiere...", K.F_DARK
    if status:
        for i, line in enumerate(K.wrap(status, 15, inner.w - 166, bold=False)[:2]):
            K.t95(tft_surf, line, 15, (inner.x + 4, inner.bottom - 50 + i * 20), color=status_color, bold=False)

    if with_taskbar:
        K.taskbar(tft_surf, datetime.datetime.now(), _weather_kind(), tasks=[("broom", "putzdienste")])


def _draw_chevron(center, size, color):
    x, y = center
    pygame.draw.polygon(tft_surf, color, [(x - size // 2, y - size), (x + size // 2, y), (x - size // 2, y + size)])


def _draw_chore_list(top, bottom):
    """Chore rows from top to bottom; fills CLEANING_CHORE_ROW_RECTS. No
    done/not-done marker: cleaning_chores from the API is already filtered
    to not-yet-completed chores only. Chores with a checklist are raised
    buttons (name + assignee left, progress + bar + chevron right) and open
    the detail screen on tap; chores without one are flat since tapping them
    does nothing."""
    with MOABEATS_STATUS_LOCK:
        cleaning_chores = list(MOABEATS_STATUS.get("cleaning_chores", []))

    # Sanity cap against a pathological API response, same pattern as
    # _moabeats_wg_lines()'s overdue_chores[:10] - bounds the render loop.
    cleaning_chores = cleaning_chores[:15]
    if not cleaning_chores:
        return

    left, right = 20, DISPLAY_WIDTH - 20
    more_height = 22
    gap = 6
    # Height adapts to the chore count (76 px for a few, down to 44 px).
    row_h = max(44, min(76, (bottom - top + gap) // len(cleaning_chores) - gap))
    two_line = row_h >= 64  # assignee on its own line under the name
    right_width = 170  # progress text + bar + chevron
    text_left = left + 50
    text_width = right - right_width - text_left

    y = top
    for index, chore in enumerate(cleaning_chores):
        is_last = index == len(cleaning_chores) - 1
        if y + row_h > bottom - (0 if is_last else more_height):
            K.t95(tft_surf, f"+{len(cleaning_chores) - index} weitere in der App", 16, (DISPLAY_WIDTH // 2, y + 2), color=K.F_DARK, bold=False, anchor="midtop")
            break
        checklist = chore.get("checklist", [])
        card = pygame.Rect(left, y, right - left, row_h)
        if checklist:
            K.button(tft_surf, card, "")
        tft_surf.blit(K.menu_icon("broom", 32), (card.x + 8, card.centery - 16))

        name = chore["name"]
        assignee = chore.get("assigned_to") or ""
        if two_line and assignee:
            K.t95(tft_surf, name, K.fit_size(name, text_width, sizes=(19, 17, 15)), (text_left, card.centery - 20))
            K.t95(tft_surf, assignee, 16, (text_left, card.centery + 3), color=K.F_DARK, bold=False)
        else:
            label = f"{name} ({assignee})" if assignee else name
            K.t95(tft_surf, label, K.fit_size(label, text_width, sizes=(19, 17, 15, 14)), (text_left, card.centery), anchor="midleft")

        # Without a checklist the chore itself is the one "item": always 0/1
        # here (cleaning_chores only holds uncompleted chores), and no
        # chevron - tapping it does nothing, completing stays in the app.
        if checklist:
            done = sum(1 for entry in checklist if entry["done"])
            total = len(checklist)
            _draw_chevron((card.right - 18, card.centery), 8, K.F_INK)
        else:
            done, total = 0, 1
        bar = pygame.Rect(card.right - 150, card.centery + 2, 110, 18 if row_h >= 56 else 12)
        K.t95(tft_surf, f"{done}/{total}", 15, (bar.right, bar.y - 2), anchor="bottomright")
        K.progress95(tft_surf, bar, done, total)
        CLEANING_CHORE_ROW_RECTS.append((card, chore["id"], bool(checklist)))
        y += row_h + gap


def _draw_check_box(rect, done, pending):
    K.bevel(tft_surf, rect, sunken=True, face=K.F_PAPER)
    if pending:
        pygame.draw.rect(tft_surf, K.SUN, rect, 3)
        return
    if done:
        # Drawn tick - the bundled fonts aren't guaranteed to have a check glyph.
        points = [
            (rect.left + rect.width * 0.22, rect.top + rect.height * 0.52),
            (rect.left + rect.width * 0.42, rect.top + rect.height * 0.74),
            (rect.left + rect.width * 0.80, rect.top + rect.height * 0.26),
        ]
        pygame.draw.lines(tft_surf, K.F_INK, False, points, 4)


CHORE_ITEM_PAREN_URL_RE = re.compile(r"\s*\((?:siehe\s+|see\s+)?https?://[^)\s]*\)", re.IGNORECASE)
CHORE_ITEM_URL_RE = re.compile(r"https?://\S+")


def _chore_item_display_text(item):
    """Item text as shown on the kiosk: links stripped (useless on a
    touchscreen, e.g. "Abfluss reinigen (siehe https://...)").
    Display only - the PATCH must send the exact original item text."""
    text = CHORE_ITEM_PAREN_URL_RE.sub("", item)
    text = CHORE_ITEM_URL_RE.sub("", text)
    return " ".join(text.split()) or item


def _wrap_text_hard(font, text, max_width):
    """Word wrap that also breaks single words wider than max_width (URLs in
    real checklist items) by character instead of letting them overflow."""
    lines = []
    for line in _quiz_wrap_text(font, text, max_width):
        while font.size(line)[0] > max_width:
            cut = len(line) - 1
            while cut > 1 and font.size(line[:cut])[0] > max_width:
                cut -= 1
            lines.append(line[:cut])
            line = line[cut:]
        lines.append(line)
    return lines


def _layout_chore_rows(checklist, text_width, available_height, gap):
    """Largest item font at which every sub-item fits fully wrapped (no
    ellipsis) with every row still a big touch target. Returns (font,
    [(lines, row_height)]). If even the smallest size overflows, the caller
    shows as many rows as fit plus "+N weitere"."""
    min_row_height = 52
    max_row_height = 84
    for font in CHORE_ITEM_FONTS:
        layout = []
        for entry in checklist:
            lines = _wrap_text_hard(font, _chore_item_display_text(entry["item"]), text_width)
            layout.append((lines, max(min_row_height, len(lines) * font.get_linesize() + 16)))
        spare = available_height - sum(height for _, height in layout) - gap * (len(layout) - 1)
        if spare >= 0:
            # Short items get tall rows only out of space that's left over, so
            # they never force the long ones down to a smaller font.
            extra = spare // max(1, len(layout))
            return font, [(lines, max(height, min(max_row_height, height + extra))) for lines, height in layout]
    # Nothing fits: smallest font, minimum row height, caller truncates rows.
    return font, [(lines, max(min_row_height, len(lines) * font.get_linesize() + 16)) for lines, _ in layout]


def draw_chore_detail():
    """Checklist detail screen: header (chore name + assignee + progress),
    one big tappable row per sub-item, error/status line, "< Zurück".
    Rows start inside the emergency-exit band - the exit is off on this
    screen (emergency_exit_active())."""
    global CHORE_DETAIL_SNAPSHOT, CHORE_DETAIL_ROW_RECTS, CHORE_DETAIL_BACK_RECT, CHORE_DETAIL_TITLE_X

    chore = _find_cleaning_chore(CHORE_DETAIL_ID)
    if chore is not None:
        CHORE_DETAIL_SNAPSHOT = chore
    header = CHORE_DETAIL_SNAPSHOT or {}
    checklist = chore.get("checklist", []) if chore is not None else []

    win = pygame.Rect(0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT)
    inner = K.window(tft_surf, win, f"putzdienste.exe - {header.get('name') or '?'}", icon="broom")
    CHORE_DETAIL_TITLE_X = K.close_box(win)
    y = inner.y + 2
    title = header.get("full_name") or header.get("name") or "?"
    for line in K.wrap(title, 18, inner.w - 8)[:2]:
        K.t95(tft_surf, line, 18, (inner.x + 4, y))
        y += 24
    K.t95(tft_surf, header.get("assigned_to") or "niemand zugeteilt", 16, (inner.x + 4, y + 2), color=K.F_DARK, bold=False)
    y += 26
    if checklist:
        done = sum(1 for entry in checklist if entry["done"])
        K.progress95(tft_surf, pygame.Rect(inner.x + 4, y, inner.w - 80, 22), done, len(checklist))
        K.t95(tft_surf, _chore_progress_text(checklist), 16, (inner.right - 4, y + 2), anchor="topright")
        y += 30

    CHORE_DETAIL_BACK_RECT = K.button(tft_surf, pygame.Rect(inner.right - 130, inner.bottom - 52, 130, 52), "< Zurück", size=17)
    lv = pygame.Rect(inner.x, y + 4, inner.w, inner.bottom - 60 - y - 4)
    K.bevel(tft_surf, lv, sunken=True, face=K.F_PAPER)

    CHORE_DETAIL_ROW_RECTS = []
    if chore is None:
        K.t95(tft_surf, "Nicht mehr offen", 20, (lv.centerx, lv.centery - 14), anchor="center")
        K.t95(tft_surf, "(in der App erledigt?)", 16, (lv.centerx, lv.centery + 16), color=K.F_DARK, bold=False, anchor="center")
    else:
        gap = 4
        box_size = 32
        text_left_offset = 12 + box_size + 14
        text_width = lv.w - text_left_offset - 12
        rows_top, rows_bottom = lv.y + 4, lv.bottom - 4
        font, layout = _layout_chore_rows(checklist, text_width, rows_bottom - rows_top, gap)
        more_height = 22
        row_y = rows_top
        shown = 0
        for index, (entry, (lines, row_height)) in enumerate(zip(checklist, layout)):
            is_last = index == len(checklist) - 1
            if row_y + row_height > rows_bottom - (0 if is_last else more_height):
                break
            row_rect = pygame.Rect(lv.x + 4, row_y, lv.w - 8, row_height)
            pending = entry["item"] == CHORE_DETAIL_PENDING_ITEM
            if pending:
                pygame.draw.rect(tft_surf, (255, 246, 200), row_rect)
            if index:
                pygame.draw.line(tft_surf, (226, 218, 244), (row_rect.x + 6, row_rect.y - gap // 2), (row_rect.right - 6, row_rect.y - gap // 2))
            box = pygame.Rect(row_rect.left + 8, row_rect.centery - box_size // 2, box_size, box_size)
            _draw_check_box(box, entry["done"], pending)
            color = K.F_DARK if entry["done"] and not pending else K.F_INK
            text_top = row_rect.centery - len(lines) * font.get_linesize() // 2
            for line_index, line in enumerate(lines):
                tft_surf.blit(font.render(line, False, color), (row_rect.left + text_left_offset, text_top + line_index * font.get_linesize()))
            CHORE_DETAIL_ROW_RECTS.append((row_rect, entry))
            row_y += row_height + gap
            shown += 1
        if shown < len(checklist):
            # Only when even the smallest font can't fit everything.
            K.t95(tft_surf, f"+{len(checklist) - shown} weitere in der App", 16, (lv.centerx, row_y + 2), color=K.F_DARK, bold=False, anchor="midtop")

    if CHORE_DETAIL_ERROR:
        status, status_color = CHORE_DETAIL_ERROR, K.F_LATE
    elif CHORE_DETAIL_PENDING_ITEM is not None:
        status, status_color = "Speichere...", K.F_ACCENT
    elif CHORE_DETAIL_REFRESHING:
        status, status_color = "Aktualisiere...", K.F_DARK
    else:
        # Completing/handing over is deliberately app-only (no button here).
        status, status_color = "Hier abhaken, erledigen in App", K.F_DARK
    for i, line in enumerate(K.wrap(status, 16, inner.w - 146, bold=False)[:2]):
        K.t95(tft_surf, line, 16, (inner.x + 4, inner.bottom - 48 + i * 22), color=status_color, bold=False)


def handle_cleaning_chore_list_click(mx, my):
    """Tap on a chore row on the cleaning-day fullscreen opens its detail
    screen (chores with a checklist) or does nothing (without one) - either
    way it doesn't wake the dashboard, people tap rows expecting the chore.
    Taps anywhere else still fall through to the normal touch wake - except
    on the "PUTZEN" overlay, which swallows every tap (dashboard behind it)."""
    global CHORE_DETAIL_LAST_ACTIVITY_TS

    if CHORE_DETAIL_ID is not None:
        return False
    on_cleaning_screen = DISPLAY_BLANK and datetime.datetime.today().weekday() == CLEANING_DAY
    if not (CHORE_LIST_OPEN or on_cleaning_screen):
        return False
    if any(rect and rect.collidepoint((mx, my)) for rect in (CHORE_LIST_CLOSE_RECT, CHORE_LIST_TITLE_X)):
        if CHORE_LIST_OPEN:
            close_chore_list("close")
        else:
            wake_display("touch", reason="chore_screen_close")
        return True
    if CHORE_LIST_OPEN:
        CHORE_DETAIL_LAST_ACTIVITY_TS = time.time()
    for rect, chore_id, has_checklist in CLEANING_CHORE_ROW_RECTS:
        if rect.collidepoint((mx, my)):
            if has_checklist:
                open_chore_detail(chore_id)
            return True
    return CHORE_LIST_OPEN


def handle_chore_detail_click(mx, my):
    """Swallows every tap while the detail screen is open (a stray tap must
    not wake the dashboard behind it). One PATCH in flight at a time."""
    global CHORE_DETAIL_LAST_ACTIVITY_TS, CHORE_DETAIL_PENDING_ITEM, CHORE_DETAIL_ERROR

    if CHORE_DETAIL_ID is None:
        return False
    CHORE_DETAIL_LAST_ACTIVITY_TS = time.time()
    if any(rect and rect.collidepoint((mx, my)) for rect in (CHORE_DETAIL_BACK_RECT, CHORE_DETAIL_TITLE_X)):
        close_chore_detail("back")
        return True
    if CHORE_DETAIL_PENDING_ITEM is not None:
        return True
    for rect, entry in CHORE_DETAIL_ROW_RECTS:
        if rect.collidepoint((mx, my)):
            CHORE_DETAIL_PENDING_ITEM = entry["item"]
            CHORE_DETAIL_ERROR = None
            threading.Thread(
                target=_chore_detail_toggle_worker,
                args=(CHORE_DETAIL_SESSION, CHORE_DETAIL_ID, entry["item"], not entry["done"]),
                daemon=True,
            ).start()
            return True
    return True


def _quiz_wrap_text(font, text, max_width):
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or font.size(candidate)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _quiz_apply_keyboard_token(token):
    global QUIZ_NAME_TEXT

    if token == "back":
        QUIZ_NAME_TEXT = QUIZ_NAME_TEXT[:-1]
    elif token == "clear":
        QUIZ_NAME_TEXT = ""
    elif token == "space":
        if QUIZ_NAME_TEXT and len(QUIZ_NAME_TEXT) < QUIZ_NAME_MAX_CHARS:
            QUIZ_NAME_TEXT += " "
    elif len(QUIZ_NAME_TEXT) < QUIZ_NAME_MAX_CHARS:
        QUIZ_NAME_TEXT += token


def activate_quiz():
    """Opens the quiz at the name-entry stage - manually triggered by the
    TEST button only, independent of the emotion-prompt system (but yields
    to it if it happens to already be open, and vice versa - see the
    QUIZ_STAGE check added to activate_pending_emotion_prompt())."""
    global QUIZ_STAGE, QUIZ_NAME_TEXT, QUIZ_NAME_RECTS, QUIZ_NAME_ACTION_RECTS, QUIZ_LAST_ACTIVITY_TS

    if (
        not QUIZ_ENABLED
        or DISPLAY_BLANK
        or EMOTION_PROMPT_VISIBLE
        or EMOTION_RESULTS_VISIBLE
        or MERZ_VISIBLE
        or games_open()
    ):
        return

    QUIZ_STAGE = "name"
    QUIZ_NAME_TEXT = ""
    QUIZ_NAME_RECTS = []
    QUIZ_NAME_ACTION_RECTS = {}
    QUIZ_LAST_ACTIVITY_TS = time.time()
    logger.info("Quiz activated")


def show_quiz_results_only():
    """Entry point for "Nur Ergebnisse anzeigen" on the name stage - skips
    straight to the results triangle without taking the quiz, so there's no
    own-result dot, just everyone else's stored results."""
    global QUIZ_STAGE, QUIZ_OWN_RESULT, QUIZ_ALL_RESULTS, QUIZ_LAST_ACTIVITY_TS

    QUIZ_OWN_RESULT = None
    QUIZ_ALL_RESULTS = read_quiz_results(QUIZ_LOG_PATH)
    _quiz_results_reset_zoom()
    QUIZ_STAGE = "results"
    QUIZ_LAST_ACTIVITY_TS = time.time()


def start_quiz_scan():
    global QUIZ_STAGE, QUIZ_SCAN_OPENED_AT, QUIZ_MATRIX_COLUMNS
    global QUIZ_QUESTIONS, QUIZ_QUESTION_INDEX, QUIZ_VOTES, QUIZ_ANSWER_RECTS
    global QUIZ_SCAN_HELD, QUIZ_SCAN_HELD_SECONDS, QUIZ_SCAN_LAST_TICK
    global QUIZ_SCAN_MESSAGES_SESSION

    QUIZ_STAGE = "scan"
    QUIZ_SCAN_OPENED_AT = time.time()
    QUIZ_SCAN_HELD = False
    QUIZ_SCAN_HELD_SECONDS = 0.0
    QUIZ_SCAN_LAST_TICK = time.time()
    QUIZ_MATRIX_COLUMNS = []
    QUIZ_SCAN_MESSAGES_SESSION = list(QUIZ_SCAN_MESSAGES)
    random.shuffle(QUIZ_SCAN_MESSAGES_SESSION)
    selected_questions = random.sample(QUIZ_QUESTION_BANK, min(QUIZ_LENGTH, len(QUIZ_QUESTION_BANK)))
    QUIZ_QUESTIONS = []
    for q in selected_questions:
        # Shuffle a copy so the axis isn't always in the same answer slot -
        # QUIZ_QUESTION_BANK itself must stay untouched, it's reused every quiz.
        shuffled_options = list(q["options"])
        random.shuffle(shuffled_options)
        QUIZ_QUESTIONS.append({"text": q["text"], "options": shuffled_options})
    QUIZ_QUESTION_INDEX = 0
    QUIZ_VOTES = {"mausig": 0, "atzig": 0, "fotzig": 0}
    QUIZ_ANSWER_RECTS = []


def handle_quiz_scan_release():
    global QUIZ_SCAN_HELD
    QUIZ_SCAN_HELD = False


def _quiz_results_zoom_to(zoom, center):
    global QUIZ_RESULTS_ZOOM, QUIZ_RESULTS_VIEW_CENTER, QUIZ_RESULTS_HELD_KEY
    QUIZ_RESULTS_ZOOM = min(max(zoom, 1.0), QUIZ_RESULTS_ZOOM_MAX)
    QUIZ_RESULTS_VIEW_CENTER = center
    QUIZ_RESULTS_HELD_KEY = None  # dot keys are screen positions, stale after a zoom


def _quiz_results_reset_zoom():
    global QUIZ_RESULTS_ZOOM, QUIZ_RESULTS_VIEW_CENTER, QUIZ_RESULTS_VIEW, QUIZ_RESULTS_DRAG
    QUIZ_RESULTS_ZOOM = 1.0
    QUIZ_RESULTS_VIEW_CENTER = None
    QUIZ_RESULTS_VIEW = None
    QUIZ_RESULTS_DRAG = None


def _quiz_results_dot_radius(count):
    """Shared-position dots grow with the number of people on them (area
    roughly proportional to count), capped so a big cluster can't swallow
    its neighbours."""
    return min(12, int(round(4 * math.sqrt(count))))


def handle_quiz_results_motion(mx, my):
    """Finger drag on empty plot space pans the zoomed view (no-op at 1x -
    the whole triangle is already visible)."""
    global QUIZ_RESULTS_VIEW_CENTER, QUIZ_LAST_ACTIVITY_TS

    drag = QUIZ_RESULTS_DRAG
    if drag is None:
        return
    dx, dy = mx - drag["start"][0], my - drag["start"][1]
    if not drag["moved"] and math.hypot(dx, dy) < QUIZ_RESULTS_DRAG_THRESHOLD_PX:
        return
    drag["moved"] = True
    QUIZ_LAST_ACTIVITY_TS = time.time()
    if QUIZ_RESULTS_ZOOM > 1.0:
        # Content follows the finger; draw_quiz_results_stage() clamps it.
        QUIZ_RESULTS_VIEW_CENTER = (
            drag["center"][0] - dx / QUIZ_RESULTS_ZOOM,
            drag["center"][1] - dy / QUIZ_RESULTS_ZOOM,
        )


def handle_quiz_results_release():
    global QUIZ_RESULTS_HELD_KEY, QUIZ_RESULTS_DRAG
    QUIZ_RESULTS_HELD_KEY = None
    QUIZ_RESULTS_DRAG = None


def handle_quiz_answer(axis):
    global QUIZ_STAGE, QUIZ_QUESTION_INDEX, QUIZ_VOTES, QUIZ_OWN_RESULT, QUIZ_ALL_RESULTS

    QUIZ_VOTES[axis] += 1
    QUIZ_QUESTION_INDEX += 1

    if QUIZ_QUESTION_INDEX < len(QUIZ_QUESTIONS):
        return

    result = submit_quiz_result(
        QUIZ_LOG_PATH,
        QUIZ_NAME_TEXT.strip() or "anonym",
        QUIZ_VOTES["mausig"],
        QUIZ_VOTES["atzig"],
        QUIZ_VOTES["fotzig"],
    )
    logger.info(f"Quiz result logged: {result}")
    QUIZ_OWN_RESULT = result
    QUIZ_ALL_RESULTS = read_quiz_results(QUIZ_LOG_PATH)
    _quiz_results_reset_zoom()
    QUIZ_STAGE = "results"


def dismiss_quiz(reason):
    global QUIZ_STAGE, QUIZ_NAME_TEXT, QUIZ_NAME_RECTS, QUIZ_NAME_ACTION_RECTS
    global QUIZ_QUESTIONS, QUIZ_QUESTION_INDEX, QUIZ_ANSWER_RECTS, QUIZ_OWN_RESULT
    global QUIZ_RESULTS_HELD_KEY, QUIZ_RESULTS_ACTION_RECTS

    if QUIZ_STAGE is None:
        return

    QUIZ_STAGE = None
    QUIZ_NAME_TEXT = ""
    QUIZ_NAME_RECTS = []
    QUIZ_NAME_ACTION_RECTS = {}
    QUIZ_QUESTIONS = []
    QUIZ_QUESTION_INDEX = 0
    QUIZ_ANSWER_RECTS = []
    QUIZ_OWN_RESULT = None
    QUIZ_RESULTS_HELD_KEY = None
    QUIZ_RESULTS_ACTION_RECTS = {}
    _quiz_results_reset_zoom()
    logger.info(f"Quiz dismissed ({reason})")


def draw_quiz_name_stage(card):
    global QUIZ_NAME_RECTS, QUIZ_NAME_ACTION_RECTS

    K.t95(tft_surf, "Wer bist du?", 24, (card.x + 4, card.y + 4))
    K.t95(tft_surf, "Der AFM-Test: atzig, fotzig oder mausig?", 16, (card.x + 4, card.y + 40), color=K.F_DARK, bold=False)
    K.textfield(tft_surf, pygame.Rect(card.x, card.y + 76, card.w, 50), QUIZ_NAME_TEXT, "Name eintippen")
    keys = K.keyboard95(tft_surf, pygame.Rect(card.x, card.y + 140, card.w, 300),
                        ["qwertzuiop", "asdfghjkl", "yxcvbnm"],
                        [("Leer", "space", 0.5), ("<-", "back", 0.22), ("Löschen", "clear", 0.28)])
    QUIZ_NAME_RECTS = [{"token": token, "rect": rect} for rect, token in keys]

    # >1, not >0 - single-character names like "q" are too likely to collide
    # with someone else's (or a future guest's) real name, and since retakes
    # under an identical name now merge into one averaged entry (see
    # quiz_store.submit_quiz_result), a collision would silently blend two
    # different people's results together.
    start_enabled = len(QUIZ_NAME_TEXT.strip()) > 1
    start_rect = K.button(tft_surf, pygame.Rect(card.x, card.y + 460, card.w, 56), "Los geht's  >", size=20, enabled=start_enabled)

    # Skip taking the quiz entirely and just look at the results triangle -
    # a link rather than a button, tap target padded out for touch.
    link = K.t95(tft_surf, "Nur Ergebnisse anzeigen", 17, (card.x + 4, card.y + 540), color=(60, 40, 200), bold=False)
    pygame.draw.line(tft_surf, (60, 40, 200), (link.left, link.bottom + 1), (link.right, link.bottom + 1), 1)

    QUIZ_NAME_ACTION_RECTS = {
        "close": QUIZ_TITLE_X,
        "start": start_rect if start_enabled else None,
        "results_only": link.inflate(24, 24),
    }


def _draw_fingerprint_icon(surf, center, radius, color, width=2):
    """Nested partial loops with a small deterministic per-ring wobble
    (not per-frame random, so the shape holds still rather than jittering)
    and a gap at the bottom, roughly like a real fingerprint's ridge lines
    and delta point - a lot more convincing than plain concentric circles."""
    cx, cy = center
    ring_count = 6
    for ring in range(ring_count):
        base_r = radius * (1 - ring / (ring_count + 0.5))
        if base_r <= 3:
            continue
        points = []
        steps = 28
        for step in range(steps + 1):
            degrees = -100 + 200 * step / steps  # ~160deg gap at the bottom
            angle = math.radians(degrees)
            wobble = 2.2 * math.sin(ring * 1.6 + degrees * 0.08)
            r = base_r + wobble
            x = cx + r * math.sin(angle)
            y = cy - r * math.cos(angle) * 1.2  # taller than wide, like a real print
            points.append((x, y))
        pygame.draw.lines(surf, color, False, points, width)


def draw_quiz_scan_stage():
    """Dadaist fake "biometric" scan - pure decoration, not real analysis of
    anything. Progress and the rain animation only advance while
    QUIZ_SCAN_HELD is True (finger held on the thumbprint icon) - released
    time pauses both without losing progress. See handle_quiz_click() (sets
    QUIZ_SCAN_HELD True on a press inside the thumbprint circle) and
    handle_quiz_scan_release() (MOUSEBUTTONUP anywhere sets it False)."""
    global QUIZ_MATRIX_FONT, QUIZ_MATRIX_COLUMNS, QUIZ_SCAN_HELD_SECONDS
    global QUIZ_SCAN_LAST_TICK, QUIZ_SCAN_THUMB_CENTER, QUIZ_SCAN_THUMB_RADIUS

    now = time.time()
    dt = max(0.0, now - QUIZ_SCAN_LAST_TICK)
    QUIZ_SCAN_LAST_TICK = now
    if QUIZ_SCAN_HELD:
        QUIZ_SCAN_HELD_SECONDS = min(QUIZ_SCAN_SECONDS, QUIZ_SCAN_HELD_SECONDS + dt)

    tft_surf.fill(BLACK)
    dashboard_rect = pygame.Rect(0, 36, DISPLAY_WIDTH, DISPLAY_HEIGHT - 36)  # below the title bar

    if QUIZ_MATRIX_FONT is None:
        QUIZ_MATRIX_FONT = pygame.font.SysFont("monospace", max(8, int(12 * ZOOM)))

    glyph_w = QUIZ_MATRIX_FONT.size("A")[0] or 8
    line_h = QUIZ_MATRIX_FONT.get_height()
    trail_len = 7
    column_count = max(1, dashboard_rect.width // glyph_w)
    # ASCII only - a pygame Font/SysFont on the Pi can silently fail to
    # render non-ASCII glyphs (bit us with emoji in the question bank).
    matrix_chars = "01ATZIGFOTZIGMAUSIG#$%&@*+-<>/\\"

    if len(QUIZ_MATRIX_COLUMNS) != column_count:
        QUIZ_MATRIX_COLUMNS = [
            {
                "y": float(random.randint(dashboard_rect.top - 400, dashboard_rect.bottom)),
                "chars": [random.choice(matrix_chars) for _ in range(trail_len)],
            }
            for _ in range(column_count)
        ]

    for col in range(column_count):
        column = QUIZ_MATRIX_COLUMNS[col]
        x = dashboard_rect.left + col * glyph_w
        if QUIZ_SCAN_HELD:
            column["y"] += 14 * ZOOM
            column["chars"].insert(0, random.choice(matrix_chars))
            del column["chars"][trail_len:]
            if column["y"] > dashboard_rect.bottom:
                column["y"] = float(dashboard_rect.top - trail_len * line_h)
        for i, char in enumerate(column["chars"]):
            y = column["y"] - i * line_h
            if y < dashboard_rect.top - line_h or y > dashboard_rect.bottom:
                continue
            fade = max(0.0, 1.0 - i / trail_len)
            color = (int(40 * fade), int(255 * fade), int(120 * fade))
            glyph = QUIZ_MATRIX_FONT.render(char, True, color)
            tft_surf.blit(glyph, (x, int(y)))

    scan_green = (140, 255, 180)
    progress = QUIZ_SCAN_HELD_SECONDS / QUIZ_SCAN_SECONDS

    if QUIZ_SCAN_HELD_SECONDS >= QUIZ_SCAN_SECONDS:
        prompt = "SCAN ABGESCHLOSSEN"
    elif QUIZ_SCAN_HELD:
        # Slow enough to actually read - was cycling every 0.6s, now 2.2s.
        messages = QUIZ_SCAN_MESSAGES_SESSION or QUIZ_SCAN_MESSAGES
        prompt = messages[int(QUIZ_SCAN_HELD_SECONDS / 2.2) % len(messages)]
    elif QUIZ_SCAN_HELD_SECONDS > 0:
        prompt = "PAUSIERT - DAUMEN WIEDER AUFLEGEN"
    else:
        prompt = "DAUMEN UNTEN AUF DER FLÄCHE SCANNEN"

    # Progress bar up top - a ring around the fingerprint looked nice but a
    # real thumb covers it while scanning, so the fill/percent live here
    # instead, always visible.
    bar_margin = 16
    bar_height = int(14 * ZOOM)
    bar_rect = pygame.Rect(
        dashboard_rect.left + bar_margin,
        dashboard_rect.top + 12,
        dashboard_rect.width - 2 * bar_margin,
        bar_height,
    )
    pygame.draw.rect(tft_surf, (25, 60, 40), bar_rect, border_radius=bar_height // 2)
    fill_width = int(bar_rect.width * min(progress, 1.0))
    if fill_width > 0:
        fill_rect = pygame.Rect(bar_rect.left, bar_rect.top, fill_width, bar_rect.height)
        pygame.draw.rect(tft_surf, scan_green, fill_rect, border_radius=bar_height // 2)
    pygame.draw.rect(tft_surf, scan_green, bar_rect, width=1, border_radius=bar_height // 2)

    pct_surf = FONT_TINY.render(f"{int(progress * 100)}%", True, scan_green)
    pct_rect = pct_surf.get_rect(midtop=(dashboard_rect.centerx, bar_rect.bottom + 4))
    tft_surf.blit(pct_surf, pct_rect)

    # Cycling status message below the bar, big - this is the thing meant to
    # actually be read. The static "BIOMETRISCHER SCAN" label is a small
    # footer caption at the bottom instead.
    message_font = FONT_SMALL
    message_lines = _quiz_wrap_text(message_font, prompt, dashboard_rect.width - 16)
    message_line_h = message_font.get_height()
    message_top = pct_rect.bottom + 8
    for i, line in enumerate(message_lines):
        line_surf = message_font.render(line, True, scan_green)
        tft_surf.blit(
            line_surf,
            line_surf.get_rect(center=(dashboard_rect.centerx, message_top + i * message_line_h)),
        )
    message_bottom = message_top + len(message_lines) * message_line_h

    # Fake fingerprint the participant must hold to keep the scan running -
    # a real icon (Twemoji, see README credits) rather than a hand-drawn
    # approximation, tinted to match the scan's green/held-state color.
    thumb_radius = int(46 * ZOOM)
    thumb_center = (
        dashboard_rect.centerx,
        max(dashboard_rect.centery + int(10 * ZOOM), message_bottom + thumb_radius + 26),
    )
    QUIZ_SCAN_THUMB_CENTER = thumb_center
    QUIZ_SCAN_THUMB_RADIUS = thumb_radius
    ridge_color = scan_green if QUIZ_SCAN_HELD else (70, 160, 100)

    fingerprint_img = images.get("quiz_fingerprint")
    if fingerprint_img is not None:
        icon_diameter = thumb_radius * 2.2
        DrawImage(
            tft_surf, fingerprint_img, size=icon_diameter / ZOOM, fillcolor=ridge_color
        ).draw_absolut_position(
            (thumb_center[0] - icon_diameter / 2, thumb_center[1] - icon_diameter / 2)
        )
    else:
        _draw_fingerprint_icon(tft_surf, thumb_center, thumb_radius, ridge_color)

    title_surf = FONT_SUPER_TINY.render("BIOMETRISCHER SCAN", True, (90, 180, 130))
    tft_surf.blit(
        title_surf,
        title_surf.get_rect(midbottom=(dashboard_rect.centerx, dashboard_rect.bottom - 8)),
    )


def draw_quiz_question_stage(card):
    global QUIZ_ANSWER_RECTS

    if QUIZ_QUESTION_INDEX >= len(QUIZ_QUESTIONS):
        return

    question = QUIZ_QUESTIONS[QUIZ_QUESTION_INDEX]
    K.progress95(tft_surf, pygame.Rect(card.x, card.y, card.w, 22), QUIZ_QUESTION_INDEX + 1, len(QUIZ_QUESTIONS))
    K.t95(tft_surf, f"zufällig aus {len(QUIZ_QUESTION_BANK)} Fragen ausgewählt", 14, (card.x + 2, card.y + 30), color=K.F_DARK, bold=False)

    size = 21
    lines = K.wrap(question["text"], size, card.w - 8)
    while len(lines) > 4 and size > 15:
        size -= 2
        lines = K.wrap(question["text"], size, card.w - 8)
    y = card.y + 56
    for line in lines:
        K.t95(tft_surf, line, size, (card.x + 4, y))
        y += size + 9

    top = max(card.y + 140, y + 10)
    gap = 14
    button_h = (card.bottom - top - 2 * gap) // 3
    QUIZ_ANSWER_RECTS = []
    for idx, option in enumerate(question["options"]):
        rect = pygame.Rect(card.x, top + idx * (button_h + gap), card.w, button_h)
        K.button(tft_surf, rect, "")
        radio = (rect.x + 28, rect.centery)
        pygame.draw.circle(tft_surf, K.F_DARK, radio, 12)
        pygame.draw.circle(tft_surf, K.F_PAPER, radio, 10)
        if "icons" in option:
            icon_px = min(rect.height - 16, 48)
            icon_gap = 14
            start_x = rect.x + 54
            for i, icon_key in enumerate(option["icons"]):
                # Prefer a local-only iOS-style override (gitignored,
                # proprietary Apple artwork - never committed) over the
                # CC-BY Twemoji version everyone else's clone falls back to.
                icon_img = images.get(f"{icon_key}_ios") or images.get(icon_key)
                if icon_img is None:
                    continue
                DrawImage(tft_surf, icon_img, size=icon_px / ZOOM).draw_absolut_position(
                    (start_x + i * (icon_px + icon_gap), rect.centery - icon_px / 2)
                )
        else:
            label_size = 17
            label_lines = K.wrap(option["label"], label_size, rect.w - 70)
            while len(label_lines) * (label_size + 6) > rect.h - 10 and label_size > 12:
                label_size -= 1
                label_lines = K.wrap(option["label"], label_size, rect.w - 70)
            text_top = rect.centery - len(label_lines) * (label_size + 6) // 2
            for i, line in enumerate(label_lines):
                K.t95(tft_surf, line, label_size, (rect.x + 54, text_top + i * (label_size + 6)))
        QUIZ_ANSWER_RECTS.append({"axis": option["axis"], "rect": rect})


def draw_quiz_results_stage(card):
    global QUIZ_RESULTS_ACTION_RECTS

    inner_pad = 10
    # Bottom button row (+, -, Schließen) under the plot; the window's title
    # bar x closes too (handle_quiz_click). Zoom buttons are bottom-left,
    # far from the top-left emergency-exit corner (off in the quiz anyway).
    buttons_y = card.bottom - 44
    QUIZ_RESULTS_ACTION_RECTS = {
        "close_button": K.button(tft_surf, pygame.Rect(card.right - 150, buttons_y, 150, 44), "Schließen", size=17)
    }
    K.t95(tft_surf, "Dein Ergebnis im AFM Test", 20, (card.x + 4, card.y + 2))
    title_rect = pygame.Rect(card.left, card.top + 2, card.width, 30)
    K.bevel(tft_surf, pygame.Rect(card.x, title_rect.bottom + 2, card.w, buttons_y - 34 - title_rect.bottom), sunken=True, face=K.F_PAPER)
    card = pygame.Rect(card.x, card.y, card.w, buttons_y - 8 - card.y)

    hint_font = FONT_SUPER_TINY
    hint_lines = _quiz_wrap_text(
        hint_font,
        "+/- zoomt, Ziehen verschiebt, Punkt halten zeigt Namen",
        card.width - 2 * inner_pad,
    )
    hint_line_h = hint_font.get_height()
    hint_rect = pygame.Rect(
        card.left,
        card.bottom - 6 - len(hint_lines) * hint_line_h,
        card.width,
        len(hint_lines) * hint_line_h,
    )

    # The triangle fills the full card width - only a thin vertical strip is
    # reserved top/bottom for the ATZIG/MAUSIG/FOTZIG labels, which hang
    # outside the triangle right at each corner. MAUSIG/FOTZIG are nudged
    # inward (toward center) rather than hanging further out past the base
    # corners, so they don't need horizontal margin too and can't clip past
    # the card's left/right edge.
    axis_label_font = FONT_SMALL_BOLD
    # MAUSIG/FOTZIG need more room than ATZIG: a dot landing right on the
    # bl/br corner (e.g. a 100% mausig or fotzig result) draws its own
    # name tag just below itself, in the same spot the label would
    # otherwise sit - so those two get pushed further down/inward.
    top_label_gap = 6
    bottom_label_gap = 34
    corner_shift = 50
    area_left = card.left + inner_pad
    area_right = card.right - inner_pad
    area_top = title_rect.bottom + axis_label_font.get_height() + top_label_gap
    area_bottom = hint_rect.top - axis_label_font.get_height() - bottom_label_gap
    area_width = area_right - area_left
    area_height = area_bottom - area_top

    side = min(area_width, area_height / (math.sqrt(3) / 2))
    height = side * (math.sqrt(3) / 2)
    center_x = (area_left + area_right) / 2
    top_y = area_top + (area_height - height) / 2
    base_y = top_y + height

    # Unzoomed ("base") geometry - everything below is computed in these
    # coordinates first, then mapped through to_screen() for the current
    # zoom. At zoom 1 with the default center, to_screen() is the identity,
    # so the unzoomed layout is exactly what it was before zoom existed.
    base_top = (center_x, top_y)
    base_bl = (center_x - side / 2, base_y)
    base_br = (center_x + side / 2, base_y)
    plot_center = (center_x, (top_y + base_y) / 2)
    plot_rect = pygame.Rect(
        card.left + 2, title_rect.bottom + 2, card.width - 4, hint_rect.top - title_rect.bottom - 4
    )

    global QUIZ_RESULTS_VIEW_CENTER, QUIZ_RESULTS_VIEW
    zoom = QUIZ_RESULTS_ZOOM
    if zoom <= 1.0 or QUIZ_RESULTS_VIEW_CENTER is None:
        QUIZ_RESULTS_VIEW_CENTER = plot_center
    # Keep the view center inside the triangle's bounding box, so zooming
    # in near an edge can't scroll the whole triangle out of view.
    view_center = (
        min(max(QUIZ_RESULTS_VIEW_CENTER[0], base_bl[0]), base_br[0]),
        min(max(QUIZ_RESULTS_VIEW_CENTER[1], top_y), base_y),
    )
    QUIZ_RESULTS_VIEW_CENTER = view_center
    QUIZ_RESULTS_VIEW = {
        "plot_center": plot_center,
        "center": view_center,
        "zoom": zoom,
        "plot_rect": plot_rect,
    }

    def to_screen(point):
        return (
            plot_center[0] + (point[0] - view_center[0]) * zoom,
            plot_center[1] + (point[1] - view_center[1]) * zoom,
        )

    top_vertex = to_screen(base_top)
    bl_vertex = to_screen(base_bl)
    br_vertex = to_screen(base_br)

    # Everything inside the plot (triangle, axis labels, dots) is clipped
    # to the plot area so a zoomed-in view can't paint over the title,
    # hint or card border. Held-name labels are drawn after the clip is
    # lifted, see below.
    tft_surf.set_clip(plot_rect)

    triangle_fill = (240, 228, 255)
    pygame.draw.polygon(tft_surf, triangle_fill, [top_vertex, bl_vertex, br_vertex])
    pygame.draw.polygon(tft_surf, VIOLET, [top_vertex, bl_vertex, br_vertex], width=3)

    centroid = (
        (top_vertex[0] + bl_vertex[0] + br_vertex[0]) / 3,
        (top_vertex[1] + bl_vertex[1] + br_vertex[1]) / 3,
    )
    for vertex in (top_vertex, bl_vertex, br_vertex):
        pygame.draw.line(tft_surf, SWEET_PURPLE, centroid, vertex, 1)
    pygame.draw.circle(tft_surf, SWEET_PURPLE, (int(centroid[0]), int(centroid[1])), 2)

    atzig_label = axis_label_font.render("ATZIG", True, QUIZ_AXIS_COLOR["atzig"])
    tft_surf.blit(
        atzig_label, atzig_label.get_rect(midbottom=(top_vertex[0], top_vertex[1] - top_label_gap))
    )
    mausig_label = axis_label_font.render("MAUSIG", True, QUIZ_AXIS_COLOR["mausig"])
    tft_surf.blit(
        mausig_label,
        mausig_label.get_rect(
            midtop=(bl_vertex[0] + corner_shift, bl_vertex[1] + bottom_label_gap)
        ),
    )
    fotzig_label = axis_label_font.render("FOTZIG", True, QUIZ_AXIS_COLOR["fotzig"])
    tft_surf.blit(
        fotzig_label,
        fotzig_label.get_rect(
            midtop=(br_vertex[0] - corner_shift, br_vertex[1] + bottom_label_gap)
        ),
    )

    def ternary_point(mausig, atzig, fotzig):
        total = mausig + atzig + fotzig
        if total <= 0:
            return to_screen((center_x, (base_top[1] + base_bl[1]) / 2))
        fm, fa, ff = mausig / total, atzig / total, fotzig / total
        x = base_bl[0] * fm + base_br[0] * ff + base_top[0] * fa
        y = base_bl[1] * fm + base_br[1] * ff + base_top[1] * fa
        return to_screen((x, y))

    global QUIZ_RESULTS_DOT_HITBOXES
    QUIZ_RESULTS_DOT_HITBOXES = []

    # One entry per name now (see submit_quiz_result - retakes are averaged
    # in place, not appended), but different people can still land on the
    # exact same point by scoring identically. Group by rounded *screen*
    # position so coincident dots draw once, bigger the more people share
    # it, instead of silently hiding one another, and so holding the point
    # lists every name there - grouping after the zoom transform means
    # near-identical results that share a pixel at 1x split apart once
    # zoomed in.
    own_id = QUIZ_OWN_RESULT.get("id") if QUIZ_OWN_RESULT else None
    position_groups = {}
    for entry in QUIZ_ALL_RESULTS:
        if own_id is not None and entry.get("id") == own_id:
            continue  # own marker drawn separately, always visible
        x, y = ternary_point(entry.get("mausig", 0), entry.get("atzig", 0), entry.get("fotzig", 0))
        key = (int(x), int(y))
        group = position_groups.setdefault(key, {"pos": (x, y), "names": []})
        group["names"].append(entry.get("name", "?"))

    held_group = None
    for key, group in position_groups.items():
        x, y = group["pos"]
        if not plot_rect.collidepoint((x, y)):
            continue  # zoomed out of view - not drawn, not holdable
        radius = _quiz_results_dot_radius(len(group["names"]))
        pygame.draw.circle(tft_surf, SWEET_PURPLE, (int(x), int(y)), radius)
        pygame.draw.circle(tft_surf, VIOLET, (int(x), int(y)), radius, width=1)
        QUIZ_RESULTS_DOT_HITBOXES.append(
            {"key": key, "names": group["names"], "pos": (x, y), "radius": radius}
        )
        if key == QUIZ_RESULTS_HELD_KEY:
            held_group = group

    # Own result: always visible, unmistakable - a big red dot, clearly
    # bigger than the other participants' small purple dots.
    if QUIZ_OWN_RESULT:
        x, y = ternary_point(
            QUIZ_OWN_RESULT.get("mausig", 0),
            QUIZ_OWN_RESULT.get("atzig", 0),
            QUIZ_OWN_RESULT.get("fotzig", 0),
        )
        own_radius = 9
        pygame.draw.circle(tft_surf, RED, (int(x), int(y)), own_radius)
        pygame.draw.circle(tft_surf, BLACK, (int(x), int(y)), own_radius, width=2)
        name_surf = FONT_TINY.render(QUIZ_OWN_RESULT.get("name", "?"), True, BLACK)
        name_rect = name_surf.get_rect(midtop=(int(x), int(y) + own_radius + 4))
        pygame.draw.rect(tft_surf, WHITE, name_rect.inflate(6, 4), border_radius=4)
        pygame.draw.rect(tft_surf, RED, name_rect.inflate(6, 4), width=1, border_radius=4)
        tft_surf.blit(name_surf, name_rect)

    tft_surf.set_clip(None)

    # Held-dot name label goes on top of *everything* (other dots, count
    # badges, the own-result marker) - it used to be drawn inside the dot
    # loop, so every dot drawn after it in the loop landed on top of the
    # label and made the name hard to read in crowded areas. Wrapped to the
    # card width and kept inside the card.
    if held_group is not None:
        x, y = held_group["pos"]
        label_lines = _quiz_wrap_text(FONT_TINY, ", ".join(held_group["names"]), card.width - 30)
        line_h = FONT_TINY.get_height()
        label_w = max(FONT_TINY.size(line)[0] for line in label_lines)
        box = pygame.Rect(0, 0, label_w + 10, len(label_lines) * line_h + 6)
        label_gap = _quiz_results_dot_radius(len(held_group["names"])) + 6
        box.midtop = (int(x), int(y) + label_gap)
        if box.bottom > hint_rect.top:  # no room below the dot - flip above it
            box.midbottom = (int(x), int(y) - label_gap)
        box.clamp_ip(card.inflate(-8, -8))
        pygame.draw.rect(tft_surf, WHITE, box, border_radius=4)
        pygame.draw.rect(tft_surf, VIOLET, box, width=2, border_radius=4)
        for i, line in enumerate(label_lines):
            line_surf = FONT_TINY.render(line, True, BLACK)
            tft_surf.blit(line_surf, line_surf.get_rect(midtop=(box.centerx, box.top + 3 + i * line_h)))

    # Zoom buttons, top-RIGHT of the plot area (empty space beside the
    # ATZIG apex at 1x). Not top-left: that's inside the emergency-exit
    # corner (EMERGENCY_EXIT_MAX_X/Y), and tapping "+" 5 times quit the app.
    # "+" zooms around the current view center, "-" steps back out. Big
    # enough to hit reliably on the touchscreen.
    zoom_in_rect = pygame.Rect(card.left, buttons_y, 52, 44)
    zoom_out_rect = pygame.Rect(zoom_in_rect.right + 8, buttons_y, 52, 44)
    K.button(tft_surf, zoom_in_rect, "+", size=22, enabled=zoom < QUIZ_RESULTS_ZOOM_MAX)
    K.button(tft_surf, zoom_out_rect, "-", size=22, enabled=zoom > 1.0)
    if zoom > 1.0:
        K.t95(tft_surf, f"{zoom:g}x", 15, (zoom_out_rect.right + 10, zoom_out_rect.centery), color=K.F_DARK, anchor="midleft")
    QUIZ_RESULTS_ACTION_RECTS["zoom_in"] = zoom_in_rect
    QUIZ_RESULTS_ACTION_RECTS["zoom_out"] = zoom_out_rect

    for i, line in enumerate(hint_lines):
        line_surf = hint_font.render(line, True, DARK_GRAY)
        tft_surf.blit(
            line_surf, line_surf.get_rect(midtop=(card.centerx, hint_rect.top + i * hint_line_h))
        )


QUIZ_TITLE_X = None


def draw_quiz_overlay():
    """afm-test.exe: name / question / results in a fullscreen KiezOS window;
    the scan stage keeps its matrix look, below a title bar."""
    global QUIZ_TITLE_X
    if QUIZ_STAGE is None:
        return

    if QUIZ_STAGE == "scan":
        draw_quiz_scan_stage()
        QUIZ_TITLE_X = K.game_title(tft_surf, "afm-test.exe - Biometrischer Scan", "quiz")
        return

    tft_surf.blit(K.desktop(), (0, 0))
    frame = pygame.Rect(0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT - 40)
    if QUIZ_STAGE == "name":
        title = "afm-test.exe - Wer bist du?"
    elif QUIZ_STAGE == "question":
        title = f"afm-test.exe - Frage {min(QUIZ_QUESTION_INDEX + 1, len(QUIZ_QUESTIONS))}/{len(QUIZ_QUESTIONS)}"
    else:
        title = "afm-test.exe - Ergebnis"
    card = K.window(tft_surf, frame, title, icon="quiz")
    QUIZ_TITLE_X = K.close_box(frame)
    K.taskbar(tft_surf, datetime.datetime.now(), _weather_kind(), tasks=[("quiz", "afm-test.exe")])

    if QUIZ_STAGE == "name":
        draw_quiz_name_stage(card)
    elif QUIZ_STAGE == "question":
        draw_quiz_question_stage(card)
    elif QUIZ_STAGE == "results":
        draw_quiz_results_stage(card)


def handle_quiz_click(mx, my):
    global QUIZ_SCAN_HELD, QUIZ_LAST_ACTIVITY_TS, QUIZ_RESULTS_HELD_KEY, QUIZ_RESULTS_DRAG

    if QUIZ_STAGE is None:
        return False

    QUIZ_LAST_ACTIVITY_TS = time.time()

    if QUIZ_TITLE_X and QUIZ_TITLE_X.collidepoint((mx, my)):
        dismiss_quiz("close-button")
        return True

    if QUIZ_STAGE == "scan":
        if QUIZ_SCAN_THUMB_CENTER is not None:
            cx, cy = QUIZ_SCAN_THUMB_CENTER
            if ((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5 <= QUIZ_SCAN_THUMB_RADIUS:
                QUIZ_SCAN_HELD = True
        return True  # swallow all other taps - not skippable, only holdable

    if QUIZ_STAGE == "results":
        close_rect = QUIZ_RESULTS_ACTION_RECTS.get("close_button")
        if close_rect and close_rect.collidepoint((mx, my)):
            dismiss_quiz("close-button")
            return True
        # No tap-anywhere-closes here (unlike the other quiz overlays) -
        # missing a dot by a few px used to close the whole screen, which
        # made holding a dot to see its name basically unusable. Closing is
        # only via the X button now, or the 30s idle timeout.
        zoom_in_rect = QUIZ_RESULTS_ACTION_RECTS.get("zoom_in")
        if zoom_in_rect and zoom_in_rect.collidepoint((mx, my)):
            _quiz_results_zoom_to(QUIZ_RESULTS_ZOOM * 2, QUIZ_RESULTS_VIEW_CENTER)
            return True
        zoom_out_rect = QUIZ_RESULTS_ACTION_RECTS.get("zoom_out")
        if zoom_out_rect and zoom_out_rect.collidepoint((mx, my)):
            _quiz_results_zoom_to(QUIZ_RESULTS_ZOOM / 2, QUIZ_RESULTS_VIEW_CENTER)
            return True
        for hitbox in QUIZ_RESULTS_DOT_HITBOXES:
            hx, hy = hitbox["pos"]
            if ((mx - hx) ** 2 + (my - hy) ** 2) ** 0.5 <= max(12, hitbox["radius"] + 4):
                QUIZ_RESULTS_HELD_KEY = hitbox["key"]
                return True
        # Missed every dot: start a press on empty space - pans the view if
        # the finger moves, does nothing if it's lifted in place (zooming is
        # only via the +/- buttons).
        view = QUIZ_RESULTS_VIEW
        if view and view["plot_rect"].collidepoint((mx, my)):
            QUIZ_RESULTS_DRAG = {"start": (mx, my), "center": view["center"], "moved": False}
        return True

    if QUIZ_STAGE == "name":
        close_rect = QUIZ_NAME_ACTION_RECTS.get("close")
        if close_rect and close_rect.collidepoint((mx, my)):
            dismiss_quiz("cancel")
            return True

        start_rect = QUIZ_NAME_ACTION_RECTS.get("start")
        if start_rect and start_rect.collidepoint((mx, my)):
            start_quiz_scan()
            return True

        results_only_rect = QUIZ_NAME_ACTION_RECTS.get("results_only")
        if results_only_rect and results_only_rect.collidepoint((mx, my)):
            show_quiz_results_only()
            return True

        for key_button in QUIZ_NAME_RECTS:
            if key_button["rect"].collidepoint((mx, my)):
                _quiz_apply_keyboard_token(key_button["token"])
                return True
        return True

    if QUIZ_STAGE == "question":
        for answer in QUIZ_ANSWER_RECTS:
            if answer["rect"].collidepoint((mx, my)):
                handle_quiz_answer(answer["axis"])
                return True
        return True

    return True


# ---------------------------------------------------------------- KiezOS 161 home
# The awake dashboard is a purple 90s desktop (drawing helpers in kiezos.py):
# uhr.exe, wetter.exe, bvg.exe and wg.txt windows, a taskbar with a Start
# menu that holds everything else (games, AFM quiz, Putzdienste, WLAN QR,
# Stimmung & Stats, the Herunterfahren gag). The windows' x / o / _ title
# buttons do dadaist things; o (or a double-tap on the title bar) opens the
# window's detail view.

# uhr.exe is a borderless LED strip flush with the top (no title bar: a tap
# on it maximises), the rest 4 px margin and gaps; the taskbar starts at y=760.
WIN_UHR = pygame.Rect(0, 0, 480, 124)
WIN_WETTER = pygame.Rect(4, 128, 472, 156)
WIN_BVG = pygame.Rect(4, 288, 472, 296)
WIN_WG = pygame.Rect(4, 588, 472, 168)
HOME_WINDOWS = {"uhr": WIN_UHR, "wetter": WIN_WETTER, "bvg": WIN_BVG, "wg": WIN_WG}
HOME_WINDOW_TITLES = {"uhr": "uhr.exe", "wetter": "wetter.exe", "bvg": "bvg.exe", "wg": "wg.txt"}
HOME_WINDOW_ICONS = {"uhr": "clock", "wetter": "weather", "bvg": "bus", "wg": "note"}

START_MENU_OPEN = False
START_SUBMENU_OPEN = False
START_MENU_RECTS = []  # [(rect, action)] from the last draw, submenu entries first
START_BUTTON_RECT = None
HOME_RECTS = {}  # "mehr", "karte" -> rect from the last home draw
HOME_WINDOW = None  # fullscreen detail view: "wetter" | "karte" | "clock"
HOME_WINDOW_RECTS = {}  # "back", "x", "o", "_" of the open detail view
HOME_WINDOW_LAST_ACTIVITY_TS = 0.0
HOME_WINDOW_IDLE_TIMEOUT_SECONDS = 60
DADA = None  # {"kind": ..., "opened_at": ts} - a title-button x message box
DADA_BUTTON_RECTS = []  # [(rect, label)]
DADA_AUTO_CLOSE_SECONDS = 20
SEV_UNTIL = 0.0  # bvg.exe's x: sev.exe replaces the window until then
SEV_SECONDS = 4.0
MINIMIZED = {}  # window -> ts it pops back up ("_": "Bin gleich wieder da.")
MINIMIZED_SECONDS = 3.0
TITLE_TAP = (None, 0.0)  # (window, ts) of the last single title-bar tap
TITLE_DOUBLE_TAP_SECONDS = 0.6
SHUTDOWN_VISIBLE = False
SHUTDOWN_OPENED_AT = 0.0
SHUTDOWN_AUTO_CLOSE_SECONDS = 15
HOME_CACHE = None  # the static part of the home screen, rebuilt every 2 s
HOME_CACHE_KEY = None

# Rain forecast for "Regen ab ..." + the 12 h chart: Open-Meteo's hourly
# precipitation_probability (free, no key) - Weatherbit's free tier has no
# hourly forecast within its daily call budget.
RAIN_FORECAST = None  # {"time": ["YYYY-MM-DDTHH:MM", ...], "prob": [...], "fetched_at": ts}
RAIN_REFRESH_SECONDS = 20 * 60

# PIR-wake surprises: 1 in EGGS_ONE_IN motion wakes shows one of these
# (never the same twice in a row) instead of the plain dashboard; a tap or
# EGG_SECONDS closes it and the emotion prompt (if due) comes after.
EGGS_CONFIG = config.get("EGGS", {})
EGGS_ENABLED = EGGS_CONFIG.get("ENABLED", False)
EGGS_ONE_IN = max(1, int(EGGS_CONFIG.get("ONE_IN", 5)))
EGG_SECONDS = 10.0
EGG_KINDS = ["assistant", "peek", "bluescreen0", "bluescreen1", "bluescreen2", "update"]
EGG = None
EGG_LAST = None
EGG_UNTIL = 0.0
EGG_RECTS = {}

BLUESCREENS = [
    ["Ein schwerwiegender Ausnahme-", "fehler 0E ist bei 0028:C0FFEE", "im Kühlschrank aufgetreten.", "",
     "* Einmal tippen, um den", "  Joghurt zu entsorgen.", "* Zweimal tippen, um die", "  WG neu zu starten."],
    ["SPUELMASCHINE.SYS hat einen", "Fehler verursacht: Geschirr", "seit 3 Tagen nicht ausgeräumt.", "",
     "* Tippen, um es jemand anderem", "  zuzuschieben.", "* Oder einfach selbst machen", "  (nicht empfohlen)."],
    ["MERZ.EXE reagiert nicht.", "", "Das Programm ist es einfach", "leid und hat sich beendet.", "",
     "* Tippen zum Wegtreten.", "* Nörgeln wird protokolliert."],
]

DADA_BOXES = {
    "x_uhr": ("uhr.exe", "clock", ["Wollen Sie die Zeit", "wirklich beenden?"], ["Ja", "Auch ja"], False),
    "x_uhr_2": ("uhr.exe", "clock", ["Die Zeit läuft weiter."], ["OK"], False),
    "x_wetter": ("wetter.exe", "weather", ["Das Wetter kann nicht", "geschlossen werden.", "", "Bitte öffnen Sie ein Fenster."], ["OK"], False),
    "x_wg": ("wg.txt", "note", ["Willst du die WG", "wirklich beenden? :(("], ["Ja, ich zieh aus", "Nein!"], True),
    "x_wg_2": ("wg.txt", "note", ["Kündigungsfrist: 3 Monate.", "Der Putzplan gilt bis dahin", "weiter."], ["Mist"], False),
}
# message box -> {button label: next message box (None = close)}
DADA_NEXT = {
    "x_uhr": {"Ja": "x_uhr_2", "Auch ja": "x_uhr_2"},
    "x_wg": {"Ja, ich zieh aus": "x_wg_2"},
}


def _update_rain_forecast(lat, lon):
    global RAIN_FORECAST
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "timezone": "auto",
                "hourly": "precipitation_probability",
                "forecast_hours": 14,
            },
            timeout=10,
        )
        response.raise_for_status()
        hourly = response.json()["hourly"]
        RAIN_FORECAST = {
            "time": hourly["time"],
            "prob": [p or 0 for p in hourly["precipitation_probability"]],
            "fetched_at": time.time(),
        }
        logger.info("Open-Meteo rain forecast updated")
    except (requests.RequestException, KeyError, ValueError) as rain_ex:
        logger.warning(f"Open-Meteo rain forecast failed: {rain_ex}")


def _rain_view(now):
    """(hours, probs) for the next 12 full hours from the current one."""
    if not RAIN_FORECAST:
        return [], []
    this_hour = now.replace(minute=0, second=0, microsecond=0)
    hours, probs = [], []
    for stamp, prob in zip(RAIN_FORECAST["time"], RAIN_FORECAST["prob"]):
        if datetime.datetime.fromisoformat(stamp) >= this_hour:
            hours.append(int(stamp[11:13]))
            probs.append(prob)
    return hours[:12], probs[:12]


def _weather_now():
    """(current, daily) from the last Weatherbit data, or (None, [])."""
    if not WEATHER_JSON_DATA:
        return None, []
    return WEATHER_JSON_DATA["current"]["data"][0], WEATHER_JSON_DATA["daily"]["data"]


def _weather_kind():
    current, _ = _weather_now()
    if current is None:
        return None
    return K.kind_of(current["weather"]["code"], current.get("pod", "d"))


def _bvg_rows_view(now):
    """One dict per configured BVG row: line, icon, label, landmark and the
    next 3 departures as minutes from now (delay included) + their delays."""
    info = BVG_STOP_INFORMATION
    rows = []
    for spec in BVG_ROWS:
        deps = []
        if isinstance(info, pd.DataFrame) and len(info) and "row_id" in info.columns:
            for _, dep in info[info["row_id"] == spec["id"]].iterrows():
                if dep.get("cancelled", False):
                    continue
                hh, mm = map(int, dep["departure"].split(":"))
                planned = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if (planned - now).total_seconds() > 12 * 3600:  # across midnight
                    planned -= datetime.timedelta(days=1)
                elif (now - planned).total_seconds() > 12 * 3600:
                    planned += datetime.timedelta(days=1)
                delay = int(dep["delay"])
                mins = math.floor((planned + datetime.timedelta(minutes=delay) - now).total_seconds() / 60)
                if mins >= 0:
                    deps.append((mins, delay))
        deps = sorted(deps)[:3]
        rows.append({
            "id": spec["id"],
            "line": spec["line"],
            "icon": spec.get("icon", "up"),
            "label": spec.get("label", spec["line"]),
            "landmark": spec.get("landmark", "bus"),
            "mins": [m for m, _ in deps],
            "delays": [d for _, d in deps],
        })
    return rows


def _moabeats_wg_lines():
    """wg.txt lines: [(prefix, content)] for TUN / KAUFEN / BESUCH (only the
    non-empty ones), or [("", idle message)] when there's nothing."""
    if not config.get("MOABEATS", {}).get("ENABLED", False):
        return [("", "Ju likes you. Have a nice day!")]

    with MOABEATS_STATUS_LOCK:
        status = dict(MOABEATS_STATUS)

    # Sanity caps against a pathological API response (e.g. 30 overdue chores
    # at once) - overflow itself is handled by scrolling (_draw_wg_line).
    todo_items = []
    for chore in status.get("overdue_chores", [])[:10]:
        label = chore["name"]
        if chore.get("assigned_to"):
            label += f" ({chore['assigned_to']})"
        todo_items.append(label)

    shopping_items = [item["name"] for item in status.get("shopping", [])]  # API already caps at 3

    visit_items = []
    for visit in status.get("visits", [])[:10]:
        start_date = _format_visit_date(visit["start"])
        end_date = _format_visit_date(visit["end"])
        label = visit["guest"]
        if visit.get("hosts"):
            label += f" bei {visit['hosts'][0]}"
        if visit["end"] == visit["start"]:
            label += f" am {start_date}"
        else:
            label += f" von {start_date} bis {end_date}"
        visit_items.append(label)

    lines = []
    if todo_items:
        lines.append(("TUN: ", ", ".join(todo_items)))
    if shopping_items:
        lines.append(("KAUFEN: ", ", ".join(shopping_items)))
    if visit_items:
        lines.append(("BESUCH: ", ", ".join(visit_items)))
    if lines:
        return lines

    idle_messages = [
        "WG läuft. Alles gut.",
        "Nichts zu tun, schön!",
        "Sauber, entspannt, kein Stress.",
        "Alles erledigt. Hörmi ist stolz.",
    ]
    day_hash = hashlib.md5(datetime.datetime.now().strftime("%Y-%m-%d").encode()).hexdigest()
    return [("", idle_messages[int(day_hash, 16) % len(idle_messages)])]


def _draw_wg_line(prefix, content, y, x_left, max_width):
    """One wg.txt line: the "TUN: "-style prefix stays put, only the content
    after it scrolls (clipped) when it's wider than the window, so nothing is
    ever permanently hidden - see _moabeats_scroll_offset()."""
    f = K.font(16, False)
    prefix_rect = K.t95(tft_surf, prefix, 16, (x_left, y), bold=False) if prefix else pygame.Rect(x_left, y, 0, 0)
    content_x = x_left + prefix_rect.width
    content_max_width = max_width - prefix_rect.width
    content_width = f.size(content)[0]
    if content_width <= content_max_width:
        K.t95(tft_surf, content, 16, (content_x, y), bold=False)
        return
    offset = _moabeats_scroll_offset(content_width - content_max_width)
    previous_clip = tft_surf.get_clip()
    tft_surf.set_clip(pygame.Rect(content_x, y - 2, content_max_width, 24))
    K.t95(tft_surf, content, 16, (content_x - offset, y), bold=False)
    tft_surf.set_clip(previous_clip)


def _draw_pinnwand_strip(surf, inner, now):
    """wg.txt's bottom: newest Pinnwand message + the Pinnwand button (always
    there, so guests can write too). Returns the tappable rect (whole strip)."""
    strip = pygame.Rect(inner.x + 4, inner.bottom - 54, inner.w - 8, 50)
    for x in range(strip.x, strip.right, 6):  # dotted rule, like a txt file
        pygame.draw.line(surf, (180, 170, 205), (x, strip.y - 3), (x + 2, strip.y - 3))
    btn = pygame.Rect(strip.right - 150, strip.y + 4, 150, 44)
    surf.blit(pinnwand.pin_icon(24), (strip.x + 2, strip.y + 6))
    msg = PINNWAND.preview()
    text_w = btn.x - strip.x - 40
    if msg is None:
        K.t95(surf, "Pinnwand der WG", 15, (strip.x + 30, strip.y + 5))
        K.t95(surf, PINNWAND.error or "Lädt...", 16, (strip.x + 30, strip.y + 25), color=K.F_DARK, bold=False)
    else:
        author = pinnwand.strip_author(msg)
        head = f"{author}, {pinnwand.when(msg['ts'], now)}:"
        K.t95(surf, head, K.fit_size(head, text_w, sizes=(15, 14, 13)), (strip.x + 30, strip.y + 5),
              color=K.F_SEL if msg["guest"] else PINNWAND._author_color(msg["author"]))
        lines = K.wrap(msg["text"], 16, text_w - 30, bold=False)
        K.t95(surf, lines[0] + ("..." if len(lines) > 1 else ""), 16, (strip.x + 30, strip.y + 25), bold=False)
    K.bevel(surf, btn)
    unread = PINNWAND.unread()
    if unread:
        K.t95(surf, "Pinnwand", 16, (btn.x + 10, btn.centery), anchor="midleft")
        badge = pygame.Rect(btn.right - 40, btn.centery - 11, 32, 22)
        pygame.draw.rect(surf, K.F_LATE, badge)
        K.t95(surf, str(min(unread, 99)), 15, badge.center, color=(255, 255, 255), anchor="center")
    else:
        K.t95(surf, "Pinnwand >", 16, (btn.centerx, btn.y + 4), anchor="midtop")
        K.t95(surf, "lesen & schreiben", 13, (btn.centerx, btn.bottom - 5), color=K.F_DARK, bold=False, anchor="midbottom")
    return strip


def _clock_layout():
    """uhr.exe's 7-segment digits (the date sits right of them): digit xs,
    colon centre x, digit top, digit width and height."""
    dh = WIN_UHR.h - 24
    dw = int(dh * 0.66)
    gap, colon = 20, 36
    x0 = WIN_UHR.x + 18
    xs = [x0, x0 + dw + gap, x0 + 2 * dw + gap + colon, x0 + 3 * dw + 2 * gap + colon]
    return xs, x0 + 2 * dw + gap + colon // 2, WIN_UHR.y + 12, dw, dh


def _home_tasks():
    return [(HOME_WINDOW_ICONS[name], HOME_WINDOW_TITLES[name]) for name in MINIMIZED]


def _draw_home_static(surf, now):
    """Everything on the home screen except the clock colon and the wg.txt
    lines (those change every frame); also fills HOME_RECTS."""
    global HOME_RECTS, START_BUTTON_RECT
    surf.blit(K.desktop(), (0, 0))
    rects = {}

    if "uhr" not in MINIMIZED:
        K.bevel(surf, WIN_UHR, sunken=True, face=(16, 6, 24))
        xs, _, dy, dw, dh = _clock_layout()
        for x, ch in zip(xs, now.strftime("%H%M")):
            K.seven_seg(surf, ch, x, dy, dw, dh)
        date_x = (xs[3] + dw + WIN_UHR.right) // 2
        K.t95(surf, K.WD_SHORT[now.weekday()], 26, (date_x, WIN_UHR.centery - 4), color=K.CLOCK_ON, anchor="midbottom")
        K.t95(surf, now.strftime("%d.%m."), 19, (date_x, WIN_UHR.centery + 4), color=K.CLOCK_ON, anchor="midtop")

    if "wetter" not in MINIMIZED:
        inner = K.window(surf, WIN_WETTER, "wetter.exe", icon="weather", buttons="xo_")
        current, daily = _weather_now()
        if current is None:
            K.t95(surf, "Wetter lädt...", 18, (inner.x + 8, inner.y + 8))
        else:
            kind = _weather_kind()
            unit = "°C" if METRIC else "°F"
            surf.blit(K.weather_icon(kind, 96), (inner.x + 2, inner.y + 4))
            K.t95(surf, f"{round(current['temp'])}{unit}", 40, (inner.x + 108, inner.y - 2))
            K.t95(surf, K.QUIRKY_DESC[kind], 17, (inner.x + 110, inner.y + 46), bold=False)
            today = daily[0]
            K.t95(surf, f"{round(today['min_temp'])}° bis {round(today['max_temp'])}°", 16, (inner.x + 110, inner.y + 70), color=K.F_DARK, bold=False)
        hours, probs = _rain_view(now)
        graph = pygame.Rect(inner.right - 160, inner.y + 2, 158, 78)
        K.rain_chart(surf, graph, hours, probs)
        K.t95(surf, "Regen 12h", 14, (graph.x + 6, graph.y + 3), color=K.F_DARK, bold=False)
        msg, wet = K.rain_summary(hours, probs)
        K.t95(surf, msg, 17, (inner.x + 4, inner.bottom - 24), color=K.F_ACCENT if wet else K.F_INK)
        rects["mehr"] = K.button(surf, pygame.Rect(inner.right - 110, inner.bottom - 30, 108, 30), "Mehr...")

    if "bvg" not in MINIMIZED:
        if time.time() < SEV_UNTIL:
            _draw_sev(surf, WIN_BVG)
        else:
            rects.update(_draw_bvg_window(surf, now))

    if "wg" not in MINIMIZED:
        inner = K.window(surf, WIN_WG, "wg.txt - Editor", icon="note", buttons="xo_")
        K.bevel(surf, inner, sunken=True, face=K.F_PAPER)
        if PINNWAND is not None:
            rects["pinnwand"] = _draw_pinnwand_strip(surf, inner, now)

    for name in MINIMIZED:
        _draw_minimized_note(surf, HOME_WINDOWS[name])

    START_BUTTON_RECT = K.taskbar(surf, now, _weather_kind(), start_pressed=START_MENU_OPEN, tasks=_home_tasks())
    HOME_RECTS = rects


def _draw_bvg_window(surf, now):
    inner = K.window(surf, WIN_BVG, "bvg.exe", icon="bus", buttons="xo_")
    lv = pygame.Rect(inner.x, inner.y, inner.w, inner.h - 38)
    K.bevel(surf, lv, sunken=True, face=K.F_PAPER)
    hx = [lv.x + 2, lv.x + 120, lv.x + 312, lv.right - 2]
    for i, label in enumerate(["Linie", "Richtung", "Abfahrt"]):
        b = pygame.Rect(hx[i], lv.y + 2, hx[i + 1] - hx[i], 22)
        K.bevel(surf, b)
        K.t95(surf, label, 15, (b.x + 6, b.y + 2))
    rows = _bvg_rows_view(now)
    row_h = min(46, (lv.h - 28) // max(1, len(rows)))
    soonest = min(range(len(rows)), key=lambda i: rows[i]["mins"][0] if rows[i]["mins"] else 999) if rows else None
    y = lv.y + 26
    for i, row in enumerate(rows):
        rr = pygame.Rect(lv.x + 2, y, lv.w - 4, row_h)
        if i == soonest and row["mins"]:  # "selected" row = next bus overall
            pygame.draw.rect(surf, (226, 214, 250), rr)
            pygame.draw.rect(surf, K.F_SEL, rr, 1)
        surf.blit(K.arrow_icon(row["icon"], 22, (120, 70, 200)), (rr.x + 4, rr.centery - 11))
        K.line_badge(surf, row["line"], (rr.x + 34, rr.centery - 13), size=16)
        surf.blit(K.landmark_icon(row["landmark"], 42), (hx[1] + 2, rr.centery - 21))
        K.t95(surf, row["label"], K.fit_size(row["label"], hx[2] - hx[1] - 54, sizes=(18, 17, 16, 14)), (hx[1] + 50, rr.centery - 10))
        first, rest = K.mins_text(row["mins"])
        color = K.due_color(row["delays"][0]) if row["mins"] else K.F_DARK
        K.t95(surf, first, 18, (hx[2] + 6, rr.y + 3), color=color)
        if rest:
            K.t95(surf, f"dann {rest}", K.fit_size(f"dann {rest}", hx[3] - hx[2] - 10, sizes=(15, 14, 13)), (hx[2] + 6, rr.y + 25), color=K.F_DARK, bold=False)
        y += row_h
    status = pygame.Rect(inner.x, inner.bottom - 32, 250, 30)
    K.bevel(surf, status, sunken=True)
    _draw_bvg_stand(surf, status)
    rects = {}
    if BVG_MAP:
        kb = pygame.Rect(inner.right - 126, inner.bottom - 32, 126, 32)
        K.bevel(surf, kb)
        surf.blit(K.menu_icon("map", 20), (kb.x + 8, kb.y + 6))
        K.t95(surf, "Karte...", 17, (kb.x + 34, kb.centery), anchor="midleft")
        rects["karte"] = kb
    return rects


def bvg_data_stale():
    """True when the departures are older than two update cycles (at least
    90 s): the minutes count down from the timetable, but delays may have
    changed since, so bvg.exe shows the Stand in red instead of looking fine."""
    if not UPDATED_BVG_TIME:
        return True
    return time.time() - UPDATED_BVG_TIME > max(90, 2 * config["TIMER"]["BVG_UPDATE"])


def _draw_bvg_stand(surf, status):
    """bvg.exe's / karte.exe's status field: "Stand hh:mm:ss", red when stale."""
    if not UPDATED_BVG_TIME:
        text = "Keine Verbindung zur BVG"
    elif bvg_data_stale():
        text = f"Stand {convert_timestamp(UPDATED_BVG_TIME, '%H:%M')} - veraltet!"
    else:
        text = f"Stand {convert_timestamp(UPDATED_BVG_TIME, '%H:%M:%S')}"
    stale = bvg_data_stale()
    K.t95(surf, text, K.fit_size(text, status.w - 14, sizes=(15, 14, 13), bold=stale), (status.x + 8, status.centery),
          color=K.F_LATE if stale else K.F_DARK, bold=stale, anchor="midleft")


def _draw_sev(surf, rect):
    """bvg.exe's x: the window gets replaced by sev.exe for a few seconds."""
    inner = K.window(surf, rect, "sev.exe", icon="bus")
    K.t95(surf, "bvg.exe wurde durch", 17, (inner.x + 8, inner.y + 10))
    K.t95(surf, "Schienenersatzverkehr", 17, (inner.x + 8, inner.y + 34), color=K.F_ACCENT)
    K.t95(surf, "ersetzt.", 17, (inner.x + 8, inner.y + 58))
    K.t95(surf, "Ersatzbusse werden gesucht...", 16, (inner.x + 8, inner.y + 110), color=K.F_DARK, bold=False)
    done = min(10, int((time.time() - (SEV_UNTIL - SEV_SECONDS)) / SEV_SECONDS * 10) + 1)
    K.progress95(surf, pygame.Rect(inner.x + 8, inner.y + 134, inner.w - 16, 24), done, 12)
    K.t95(surf, "Verbleibende Zeit: ca. 2 Jahre", 16, (inner.x + 8, inner.y + 170), color=K.F_DARK, bold=False)
    surf.blit(K.menu_icon("bus", 64), (inner.right - 74, inner.y + 8))


def _draw_minimized_note(surf, rect):
    """A window's _: it drops into the taskbar and leaves a note until it pops back."""
    surf.blit(K.desktop(), rect, rect)
    note = pygame.Rect(rect.centerx - 110, rect.y + min(20, max(4, (rect.h - 110) // 2)), 220, min(110, rect.h - 8))
    pygame.draw.rect(surf, K.SHADOW, note.move(5, 5))
    pygame.draw.rect(surf, (255, 236, 120), note)
    pygame.draw.polygon(surf, (230, 205, 80), [(note.right - 24, note.bottom), (note.right, note.bottom - 24), (note.right, note.bottom)])
    pygame.draw.rect(surf, K.PINK, (note.centerx - 30, note.y - 6, 60, 14))  # tape
    K.t95(surf, "Bin gleich", 22, (note.centerx, note.centery - 14), anchor="center")
    K.t95(surf, "wieder da.", 22, (note.centerx, note.centery + 16), anchor="center")


def _kiez_fullscreen_open():
    """Something that covers the whole home screen is open, so there's no
    point drawing the home screen underneath it."""
    return (
        MERZ_VISIBLE
        or ACTIVE_GAME is not None
        or QUIZ_STAGE is not None
        or CHORE_LIST_OPEN
        or SHUTDOWN_VISIBLE
        or HOME_WINDOW is not None
        or (EGG is not None and EGG not in ("assistant", "peek", "hilfe"))
    )


def draw_home():
    """The awake KiezOS desktop: cached static part (rebuilt every 2 s or
    when its layout changes), then the blinking clock colon and the
    (scrolling) wg.txt lines, then the Start menu and dada message boxes.
    Fullscreen views (wetter/karte/clock detail) replace it entirely."""
    global HOME_CACHE, HOME_CACHE_KEY
    now = datetime.datetime.now()
    if HOME_WINDOW is not None:
        draw_home_window(now)
        return
    if _kiez_fullscreen_open():
        return

    key = (int(time.time() // 2), tuple(MINIMIZED), time.time() < SEV_UNTIL, START_MENU_OPEN)
    if HOME_CACHE is None or key != HOME_CACHE_KEY:
        if HOME_CACHE is None:
            HOME_CACHE = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT))
        _draw_home_static(HOME_CACHE, now)
        HOME_CACHE_KEY = key
    tft_surf.blit(HOME_CACHE, (0, 0))

    if "uhr" not in MINIMIZED:
        # 1 Hz blinking colon, like an old LED alarm clock
        colon_on = int(time.time() * 2) % 2 == 0
        _, cx, dy, _, dh = _clock_layout()
        for cy in (dy + dh // 3, dy + 2 * dh // 3):
            pygame.draw.rect(tft_surf, K.CLOCK_ON if colon_on else K.CLOCK_OFF, (cx - 4, cy - 4, 8, 8))

    if "wg" not in MINIMIZED:
        inner = pygame.Rect(WIN_WG.x + 8, WIN_WG.y + 36, WIN_WG.w - 16, WIN_WG.h - 42)
        previous_clip = tft_surf.get_clip()
        tft_surf.set_clip(inner.inflate(-4, -4))
        for index, (prefix, content) in enumerate(_moabeats_wg_lines()[:3]):
            _draw_wg_line(prefix, content, inner.y + 2 + index * 23, inner.x + 8, inner.w - 16)
        tft_surf.set_clip(previous_clip)

    if START_MENU_OPEN:
        draw_start_menu()
    if DADA is not None:
        draw_dada()


def _start_menu_items():
    items = []
    if GAMES_ENABLED:
        items.append(("games", "Spiele", "games_sub"))
    if QUIZ_ENABLED:
        items.append(("quiz", "AFM-Quiz", "quiz"))
    if config.get("MOABEATS", {}).get("ENABLED", False):
        items.append(("broom", "Putzdienste", "putz"))
    if WIFI_ENABLED:
        items.append(("wifi", "WLAN-Zugang", "wifi"))
    items.append(("stats", "Stimmung & Stats", "stats"))
    items.append((None, None, None))
    items.append(("power", "Herunterfahren...", "shutdown"))
    return items


def draw_start_menu():
    global START_MENU_RECTS
    items = _start_menu_items()
    height = 12 + sum(9 if icon is None else 46 for icon, _, _ in items)
    menu = pygame.Rect(4, DISPLAY_HEIGHT - 38 - height, 254, height)
    K.bevel(tft_surf, menu)
    side = pygame.Rect(menu.x + 3, menu.y + 3, 30, menu.h - 6)
    for i in range(side.h):  # vertical gradient banner
        t = i / side.h
        pygame.draw.line(tft_surf, (int(150 - 90 * t), int(80 - 56 * t), int(210 - 90 * t)), (side.x, side.y + i), (side.right - 1, side.y + i))
    vt = pygame.transform.rotate(K.font(18).render("KiezOS 161", False, (255, 255, 255)), 90)
    tft_surf.blit(vt, vt.get_rect(midbottom=(side.centerx, side.bottom - 8)))

    rects = []
    games_row = None
    iy = menu.y + 6
    for icon, label, action in items:
        if icon is None:
            pygame.draw.line(tft_surf, K.F_DARK, (side.right + 6, iy + 3), (menu.right - 6, iy + 3))
            pygame.draw.line(tft_surf, K.F_LIGHT, (side.right + 6, iy + 4), (menu.right - 6, iy + 4))
            iy += 9
            continue
        r = pygame.Rect(side.right + 4, iy, menu.right - side.right - 9, 44)
        selected = action == "games_sub" and START_SUBMENU_OPEN
        if selected:
            pygame.draw.rect(tft_surf, K.F_SEL, r)
            games_row = r
        tft_surf.blit(K.menu_icon(icon, 32), (r.x + 4, r.y + 6))
        color = (255, 255, 255) if selected else K.F_INK
        K.t95(tft_surf, label, 16, (r.x + 44, r.y + 12), color=color)
        if action == "games_sub":
            pygame.draw.polygon(tft_surf, color, [(r.right - 14, r.y + 15), (r.right - 7, r.y + 22), (r.right - 14, r.y + 29)])
        rects.append((r.inflate(0, 2), action))
        iy += 46

    submenu = []
    if START_SUBMENU_OPEN and games_row is not None:
        daily, featured, more = games_menu_split()
        entries = [(key, icon, name) for key, name, icon, _ in ([daily] if daily else []) + featured]
        if more:
            entries.append(("__more__", "folder", "Mehr Spiele..."))
        sm = pygame.Rect(menu.right - 4, games_row.y - 4, 216, len(entries) * 46 + 10)
        K.bevel(tft_surf, sm)
        for j, (key, icon, label) in enumerate(entries):
            r = pygame.Rect(sm.x + 4, sm.y + 5 + j * 46, sm.w - 8, 44)
            tft_surf.blit(K.menu_icon(icon, 32), (r.x + 4, r.y + 6))
            K.t95(tft_surf, label, 16, (r.x + 44, r.y + 12))
            submenu.append((r, f"game:{key}"))
    START_MENU_RECTS = submenu + rects


def close_start_menu():
    global START_MENU_OPEN, START_SUBMENU_OPEN, START_MENU_RECTS
    START_MENU_OPEN = False
    START_SUBMENU_OPEN = False
    START_MENU_RECTS = []


def _start_menu_action(action):
    global START_SUBMENU_OPEN, WIFI_QR_VISIBLE, WIFI_QR_OPENED_AT
    global EMOTION_RESULTS_VISIBLE, EMOLOG_QR_OPENED_AT, SHUTDOWN_VISIBLE, SHUTDOWN_OPENED_AT
    logger.info(f"Start menu: {action}")
    if action == "games_sub":
        START_SUBMENU_OPEN = not START_SUBMENU_OPEN
        return
    close_start_menu()
    if action == "game:__more__":
        open_games_menu("more")
    elif action.startswith("game:"):
        start_game(action[len("game:"):])
    elif action == "quiz":
        activate_quiz()
    elif action == "putz":
        open_chore_list()
    elif action == "wifi":
        WIFI_QR_VISIBLE = True
        WIFI_QR_OPENED_AT = time.time()
    elif action == "stats":
        EMOTION_RESULTS_VISIBLE = True
        EMOLOG_QR_OPENED_AT = time.time()
    elif action == "shutdown":
        SHUTDOWN_VISIBLE = True
        SHUTDOWN_OPENED_AT = time.time()


def open_home_window(name):
    global HOME_WINDOW, HOME_WINDOW_LAST_ACTIVITY_TS
    if name == "karte" and not BVG_MAP:
        return
    HOME_WINDOW = name
    HOME_WINDOW_LAST_ACTIVITY_TS = time.time()
    if name == "pinnwand":
        PINNWAND.opened()
    logger.info(f"Home window opened: {name}")


def close_home_window(reason):
    global HOME_WINDOW, HOME_WINDOW_RECTS
    if HOME_WINDOW is None:
        return
    logger.info(f"Home window {HOME_WINDOW} closed ({reason})")
    if HOME_WINDOW == "pinnwand":
        PINNWAND.closed()
    HOME_WINDOW = None
    HOME_WINDOW_RECTS = {}


def draw_home_window(now):
    """Fullscreen detail views: wetter.exe - Details, karte.exe, uhr.exe maximised."""
    global HOME_WINDOW_RECTS
    tft_surf.blit(K.desktop(), (0, 0))
    frame = pygame.Rect(0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT - 40)
    rects = {"x": K.close_box(frame)}
    if HOME_WINDOW == "wetter":
        inner = K.window(tft_surf, frame, "wetter.exe - Details", icon="weather")
        _draw_weather_details(inner, now)
        rects["back"] = K.button(tft_surf, pygame.Rect(inner.right - 122, inner.bottom - 36, 122, 36), "< Zurück", size=16)
        K.t95(tft_surf, "Quelle: Weatherbit + Open-Meteo", 13, (inner.x + 4, inner.bottom - 18), color=K.F_DARK, bold=False, anchor="midleft")
        tasks = [("weather", "wetter.exe")]
    elif HOME_WINDOW == "pinnwand":
        inner = K.window(tft_surf, frame, "pinnwand.exe - WG-Chat", icon="note")
        PINNWAND.draw(tft_surf, inner, now)
        rects["back"] = PINNWAND.rects["back"]
        tasks = [("note", "pinnwand.exe")]
    elif HOME_WINDOW == "karte":
        inner = K.window(tft_surf, frame, "karte.exe - Kiez", icon="map")
        mb = pygame.Rect(inner.x, inner.y - 2, inner.w, 22)
        for item, x in zip(["Datei", "Ansicht", "Busse", "?"], [0, 56, 130, 192]):
            K.t95(tft_surf, item, 15, (mb.x + 6 + x, mb.y + 2), bold=False)
        area = pygame.Rect(inner.x, mb.bottom + 2, inner.w, inner.h - 60)
        K.draw_map(tft_surf, area, BVG_MAP, {row["id"]: row for row in _bvg_rows_view(now)})
        status = pygame.Rect(inner.x, inner.bottom - 34, inner.w - 130, 32)
        K.bevel(tft_surf, status, sunken=True)
        _draw_bvg_stand(tft_surf, status)
        rects["back"] = K.button(tft_surf, pygame.Rect(inner.right - 122, inner.bottom - 34, 122, 34), "< Zurück", size=16)
        tasks = [("map", "karte.exe")]
    else:  # "clock": hours over minutes, tap anywhere to restore
        inner = K.window(tft_surf, frame, f"uhr.exe - {K.WEEKDAYS[now.weekday()]}, {now.strftime('%d.%m.%Y')}", icon="clock")
        K.bevel(tft_surf, inner, sunken=True, face=(16, 6, 24))
        hhmm = now.strftime("%H%M")
        dw, dh, gap = 190, 300, 30
        x0 = inner.centerx - dw - gap // 2
        for row in range(2):
            for col in range(2):
                K.seven_seg(tft_surf, hhmm[row * 2 + col], x0 + col * (dw + gap), inner.y + 30 + row * (dh + 50), dw, dh)
        colon_on = int(time.time() * 2) % 2 == 0
        for cx in (inner.centerx - 60, inner.centerx + 60):  # the colon, lying down between hours and minutes
            pygame.draw.rect(tft_surf, K.CLOCK_ON if colon_on else K.CLOCK_OFF, (cx - 8, inner.y + 30 + dh + 17, 16, 16))
        rects["back"] = frame
        tasks = [("clock", "uhr.exe")]
    K.taskbar(tft_surf, now, _weather_kind(), tasks=tasks)
    HOME_WINDOW_RECTS = rects


def _draw_weather_details(inner, now):
    current, daily = _weather_now()
    if current is None:
        K.t95(tft_surf, "Wetter lädt...", 20, (inner.x + 8, inner.y + 12))
        return
    kind = _weather_kind()
    unit = "°C" if METRIC else "°F"
    wind = current["wind_spd"] * 3.6 if METRIC else current["wind_spd"]
    wind_unit = "km/h" if METRIC else "mph"

    g = pygame.Rect(inner.x + 4, inner.y + 12, inner.w - 8, 146)
    K.groupbox(tft_surf, g, "Jetzt")
    tft_surf.blit(K.weather_icon(kind, 112), (g.x + 8, g.y + 18))
    K.t95(tft_surf, f"{round(current['temp'])}{unit}", 44, (g.x + 132, g.y + 10))
    K.t95(tft_surf, K.QUIRKY_DESC[kind], 18, (g.x + 134, g.y + 64))
    K.t95(tft_surf, f"gefühlt {round(current['app_temp'])}°", 16, (g.x + 134, g.y + 90), color=K.F_DARK, bold=False)
    K.t95(tft_surf, f"Wind {round(wind)} {wind_unit} {current['wind_cdir']}", 16, (g.x + 134, g.y + 113), color=K.F_DARK, bold=False)
    K.t95(tft_surf, f"Luft {round(current['rh'])}%", 16, (g.right - 12, g.y + 90), color=K.F_DARK, bold=False, anchor="topright")
    K.t95(tft_surf, f"UV {round(current['uv'])}", 16, (g.right - 12, g.y + 113), color=K.F_DARK, bold=False, anchor="topright")

    g = pygame.Rect(inner.x + 4, g.bottom + 18, inner.w - 8, 196)
    K.groupbox(tft_surf, g, "Regen, nächste 12 Stunden")
    hours, probs = _rain_view(now)
    msg, wet = K.rain_summary(hours, probs)
    K.t95(tft_surf, msg, 17, (g.x + 12, g.y + 14), color=K.F_ACCENT if wet else K.F_INK)
    K.rain_chart(tft_surf, pygame.Rect(g.x + 10, g.y + 42, g.w - 20, g.h - 52), hours, probs, labels=True)

    g = pygame.Rect(inner.x + 4, g.bottom + 18, inner.w - 8, 96)
    K.groupbox(tft_surf, g, "Sonne & Mond")
    today = daily[0]
    rise = convert_timestamp(today["sunrise_ts"], theme["DATE_FORMAT"]["SUNRISE_SUNSET"])
    sunset = convert_timestamp(today["sunset_ts"], theme["DATE_FORMAT"]["SUNRISE_SUNSET"])
    tft_surf.blit(K.sunrise_icon(48), (g.x + 10, g.y + 22))
    K.t95(tft_surf, rise, 20, (g.x + 62, g.y + 24))
    K.t95(tft_surf, "auf", 15, (g.x + 62, g.y + 50), color=K.F_DARK, bold=False)
    tft_surf.blit(K.sunrise_icon(48), (g.x + 152, g.y + 22))
    K.t95(tft_surf, sunset, 20, (g.x + 204, g.y + 24))
    K.t95(tft_surf, "unter", 15, (g.x + 204, g.y + 50), color=K.F_DARK, bold=False)
    lunation = float(today.get("moon_phase_lunation", 0.5))
    tft_surf.blit(K.moon_phase(lunation, 48), (g.x + 300, g.y + 22))
    K.t95(tft_surf, K.moon_name(lunation), 15, (g.x + 352, g.y + 36))

    g = pygame.Rect(inner.x + 4, g.bottom + 18, inner.w - 8, 176)
    K.groupbox(tft_surf, g, "Nächste Tage")
    cw = (g.w - 20 - 2 * 8) // 3
    for i, day in enumerate(daily[1:4]):
        c = pygame.Rect(g.x + 10 + i * (cw + 8), g.y + 16, cw, g.h - 26)
        K.bevel(tft_surf, c, sunken=True, face=K.F_PAPER)
        dt = datetime.datetime.strptime(day["valid_date"], "%Y-%m-%d")
        K.t95(tft_surf, K.WEEKDAYS[dt.weekday()], 17, (c.centerx, c.y + 6), anchor="midtop")
        tft_surf.blit(K.weather_icon(K.kind_of(day["weather"]["code"]), 64), (c.centerx - 32, c.y + 28))
        K.t95(tft_surf, f"{round(day['max_temp'])}° / {round(day['min_temp'])}°", 17, (c.centerx, c.y + 94), anchor="midtop")
        K.t95(tft_surf, f"Regen {day['pop']}%", 15, (c.centerx, c.y + 118), color=K.F_DARK, bold=False, anchor="midtop")


def draw_dada():
    global DADA_BUTTON_RECTS
    title, icon, lines, buttons, wide = DADA_BOXES[DADA["kind"]]
    DADA_BUTTON_RECTS = K.msgbox(tft_surf, title, icon, lines, buttons, wide=wide)


def open_dada(kind):
    global DADA
    DADA = {"kind": kind, "opened_at": time.time()}


def _home_title_action(window_name, glyph):
    """The x / o / _ of a home window. o opens its detail view, x and _ are
    dadaist (see DADA_BOXES, sev.exe, the "Bin gleich wieder da." note)."""
    global SEV_UNTIL
    logger.info(f"Home window {window_name}: title button {glyph}")
    if glyph == "_":
        MINIMIZED[window_name] = time.time() + MINIMIZED_SECONDS
    elif glyph == "o":
        if window_name == "uhr":
            open_home_window("clock")
        elif window_name == "wetter":
            open_home_window("wetter")
        elif window_name == "bvg":
            open_home_window("karte")
        elif config.get("MOABEATS", {}).get("ENABLED", False):
            open_chore_list()
    elif window_name == "bvg":
        SEV_UNTIL = time.time() + SEV_SECONDS
    else:
        open_dada({"uhr": "x_uhr", "wetter": "x_wetter", "wg": "x_wg"}[window_name])


def handle_home_click(mx, my):
    """Taps on the awake KiezOS desktop (Start menu, dada boxes, the home
    windows and their detail views). Runs last in handle_tap()."""
    global HOME_WINDOW_LAST_ACTIVITY_TS, START_MENU_OPEN, TITLE_TAP, DADA, SEV_UNTIL
    if DISPLAY_BLANK or dashboard_overlay_open():
        return False

    if HOME_WINDOW is not None:
        HOME_WINDOW_LAST_ACTIVITY_TS = time.time()
        if HOME_WINDOW == "pinnwand" and PINNWAND.tap(mx, my):  # its own buttons, scrolling, compose dialog
            return True
        for name in ("back", "x", "_"):
            rect = HOME_WINDOW_RECTS.get(name)
            if rect and rect.collidepoint((mx, my)):
                close_home_window(name)
                return True
        return True

    if DADA is not None:
        for rect, label in DADA_BUTTON_RECTS:
            if rect.collidepoint((mx, my)):
                follow = DADA_NEXT.get(DADA["kind"], {}).get(label)
                if follow:
                    open_dada(follow)
                else:
                    DADA = None
                return True
        return True

    if START_MENU_OPEN:
        for rect, action in START_MENU_RECTS:
            if rect.collidepoint((mx, my)):
                _start_menu_action(action)
                return True
        close_start_menu()  # tap outside closes it
        return True

    if START_BUTTON_RECT and START_BUTTON_RECT.collidepoint((mx, my)):
        START_MENU_OPEN = True
        return True

    if time.time() < SEV_UNTIL and "bvg" not in MINIMIZED and K.close_box(WIN_BVG).collidepoint((mx, my)):
        SEV_UNTIL = 0  # sev.exe's x gives bvg.exe back
        return True
    if "uhr" not in MINIMIZED and WIN_UHR.collidepoint((mx, my)):
        # No title bar: a tap on the clock maximises it. Not inside the
        # emergency-exit corner, where taps count towards quitting.
        if mx >= EMERGENCY_EXIT_MAX_X or my >= EMERGENCY_EXIT_MAX_Y:
            _home_title_action("uhr", "o")
        return True
    for name, win in HOME_WINDOWS.items():
        if name == "uhr" or name in MINIMIZED or (name == "bvg" and time.time() < SEV_UNTIL):
            continue
        buttons = K.title_buttons(win)
        for glyph in ("x", "o", "_"):
            if buttons[glyph].collidepoint((mx, my)):
                _home_title_action(name, glyph)
                return True
        # Double-tap on the title bar = o, like Win95. Not inside the
        # emergency-exit corner, where taps count towards quitting.
        if buttons["bar"].inflate(0, 8).collidepoint((mx, my)) and mx >= EMERGENCY_EXIT_MAX_X:
            last_window, last_ts = TITLE_TAP
            if last_window == name and time.time() - last_ts < TITLE_DOUBLE_TAP_SECONDS:
                TITLE_TAP = (None, 0.0)
                _home_title_action(name, "o")
            else:
                TITLE_TAP = (name, time.time())
            return True

    if HOME_RECTS.get("mehr") and HOME_RECTS["mehr"].collidepoint((mx, my)):
        open_home_window("wetter")
        return True
    if HOME_RECTS.get("karte") and HOME_RECTS["karte"].collidepoint((mx, my)):
        open_home_window("karte")
        return True
    if HOME_RECTS.get("pinnwand") and HOME_RECTS["pinnwand"].collidepoint((mx, my)):
        open_home_window("pinnwand")
        return True
    return False


def update_kiez_timeouts():
    """Called every frame: auto-close/expire the KiezOS bits."""
    global DADA, SHUTDOWN_VISIBLE, EGG
    now = time.time()
    for name, until in list(MINIMIZED.items()):
        if now >= until:
            del MINIMIZED[name]
    if DISPLAY_BLANK:
        close_start_menu()
        close_home_window("display-blank")
        DADA = None
        SHUTDOWN_VISIBLE = False
        EGG = None
        return
    idle_limit = PINNWAND_IDLE_TIMEOUT_SECONDS if HOME_WINDOW == "pinnwand" else HOME_WINDOW_IDLE_TIMEOUT_SECONDS
    if HOME_WINDOW is not None and now - HOME_WINDOW_LAST_ACTIVITY_TS > idle_limit:
        close_home_window("idle-timeout")
    if DADA is not None and now - DADA["opened_at"] > DADA_AUTO_CLOSE_SECONDS:
        DADA = None
    if SHUTDOWN_VISIBLE and now - SHUTDOWN_OPENED_AT > SHUTDOWN_AUTO_CLOSE_SECONDS:
        SHUTDOWN_VISIBLE = False
    if EGG is not None and now > EGG_UNTIL:
        logger.info(f"Egg {EGG} timed out")
        EGG = None


def draw_shutdown():
    if not SHUTDOWN_VISIBLE:
        return
    tft_surf.fill((8, 4, 14))
    w = DISPLAY_WIDTH
    y = 280
    for line in ("Sie können KiezOS 161", "jetzt NICHT", "ausschalten."):
        K.t95(tft_surf, line, 24, (w // 2, y), color=(255, 160, 70), anchor="midtop")
        y += 36
    K.t95(tft_surf, "Merz hat es verboten.", 16, (w // 2, y + 24), color=(200, 170, 255), bold=False, anchor="midtop")
    K.heart(tft_surf, (w // 2 - 70, y + 82), 3, K.PINK)
    K.t95(tft_surf, "Ju likes you", 16, (w // 2 - 50, y + 72), color=(200, 170, 255), bold=False)
    K.t95(tft_surf, "(tippen zum Zurückkehren)", 15, (w // 2, DISPLAY_HEIGHT - 40), color=(110, 90, 140), bold=False, anchor="midtop")


def handle_shutdown_click(mx, my):
    global SHUTDOWN_VISIBLE
    if not SHUTDOWN_VISIBLE:
        return False
    SHUTDOWN_VISIBLE = False
    return True


# ---------------------------------------------------------------- PIR-wake surprises

def maybe_start_egg():
    """Called on a motion wake: 1 in EGGS_ONE_IN chance of a surprise."""
    global EGG, EGG_LAST, EGG_UNTIL
    if not EGGS_ENABLED or random.randrange(EGGS_ONE_IN) != 0:
        return
    EGG = random.choice([kind for kind in EGG_KINDS if kind != EGG_LAST])
    EGG_LAST = EGG
    EGG_UNTIL = time.time() + EGG_SECONDS
    logger.info(f"Egg: {EGG}")


def draw_egg():
    global EGG_RECTS
    if EGG is None:
        return
    EGG_RECTS = {}
    w, h = DISPLAY_WIDTH, DISPLAY_HEIGHT
    if EGG in ("assistant", "hilfe"):
        if EGG == "assistant":
            K.speech(tft_surf, pygame.Rect(226, 420, 246, 160),
                     ["Es sieht so aus, als", "wolltest du Bus fahren.", "Nimm lieber einen", "Privatjet."], (414, 650))
            EGG_RECTS["hilfe"] = K.button(tft_surf, pygame.Rect(358, 538, 102, 30), "Hilfe!", size=16).inflate(8, 14)
            K.button(tft_surf, pygame.Rect(238, 538, 112, 30), "Wegtreten", size=16)
        else:
            K.speech(tft_surf, pygame.Rect(226, 450, 246, 120), ["Hilfe gibt es nur", "für Unternehmen."], (414, 650), size=16)
            K.button(tft_surf, pygame.Rect(238, 528, 112, 30), "Wegtreten", size=16)
        merz = K.merz_sprite(152)  # 4 px per cell
        tft_surf.blit(merz, (w - merz.get_width() - 4, h - 40 - merz.get_height()))
    elif EGG == "peek":
        merz = K.merz_sprite(190)  # peeks in from the right edge
        tft_surf.blit(merz, (w - int(merz.get_width() * 0.62), 400))
        K.speech(tft_surf, pygame.Rect(196, 352, 180, 40), ["Psst... Merz!"], (w - int(merz.get_width() * 0.5), 462))
    elif EGG.startswith("bluescreen"):
        tft_surf.fill((60, 20, 120))
        title = pygame.Rect(w // 2 - 80, 200, 160, 28)
        pygame.draw.rect(tft_surf, K.F_FACE, title)
        K.t95(tft_surf, "KiezOS 161", 18, title.center, color=(60, 20, 120), anchor="center")
        for i, line in enumerate(BLUESCREENS[int(EGG[-1])]):
            K.t95(tft_surf, line, 17, (28, 260 + i * 28), color=(255, 255, 255), bold=False)
        cursor = "_" if int(time.time() * 2) % 2 == 0 else " "
        K.t95(tft_surf, f"Tippen zum Fortfahren {cursor}", 17, (w // 2, 560), color=(255, 255, 255), anchor="midtop")
    elif EGG == "update":
        tft_surf.blit(K.desktop(), (0, 0))
        inner = K.dialog(tft_surf, pygame.Rect(30, 250, w - 60, 250), "KiezOS 161 Update", icon="power")
        K.t95(tft_surf, "Update 3 von 69 wird installiert...", 16, (inner.x + 8, inner.y + 10))
        K.t95(tft_surf, "Bitte den Kühlschrank nicht öffnen", 16, (inner.x + 8, inner.y + 38), bold=False)
        K.t95(tft_surf, "und den Pi nicht ausschalten.", 16, (inner.x + 8, inner.y + 60), bold=False)
        bar = pygame.Rect(inner.x + 8, inner.y + 100, inner.w - 16, 30)
        K.bevel(tft_surf, bar, sunken=True, face=K.F_PAPER)
        blocks = 6 + int((EGG_SECONDS - (EGG_UNTIL - time.time())) / 2)  # creeps, never finishes
        for i in range(min(blocks, (bar.w - 8) // 16)):
            pygame.draw.rect(tft_surf, K.F_SEL, (bar.x + 4 + i * 16, bar.y + 4, 13, bar.h - 8))
        K.t95(tft_surf, "Verbleibend: ca. 4 Legislaturperioden", 15, (inner.x + 8, inner.y + 144), color=K.F_DARK, bold=False)
        K.button(tft_surf, pygame.Rect(inner.right - 110, inner.bottom - 34, 110, 32), "Abbrechen", size=16)
        K.taskbar(tft_surf, datetime.datetime.now(), _weather_kind())


def handle_egg_click(mx, my):
    """Any tap closes a surprise; the Merz assistant's Hilfe! answers first."""
    global EGG, EGG_UNTIL
    if EGG is None:
        return False
    if EGG == "assistant" and EGG_RECTS.get("hilfe") and EGG_RECTS["hilfe"].collidepoint((mx, my)):
        EGG = "hilfe"
        EGG_UNTIL = time.time() + EGG_SECONDS
        return True
    logger.info(f"Egg {EGG} closed (tap)")
    EGG = None
    return True


def draw_fps():
    K.t95(tft_surf, str(int(clock.get_fps())), 16, (DISPLAY_WIDTH - 140, DISPLAY_HEIGHT - 32), color=K.F_LATE)


def dashboard_overlay_open():
    """Any popup/fullscreen overlay above the KiezOS home screen (whose own
    Start menu, detail views and dada boxes are handled by handle_home_click)."""
    return (
        EMOTION_PROMPT_VISIBLE
        or EMOTION_RESULTS_VISIBLE
        or EMOTION_CONFIRMATION_VISIBLE
        or QUIZ_STAGE is not None
        or WIFI_QR_VISIBLE
        or MERZ_VISIBLE
        or games_open()
        or CHORE_LIST_OPEN
        or SHUTDOWN_VISIBLE
        or EGG is not None
    )


def handle_tap(mx, my):
    """All tap handlers after the emergency exit, in priority order; True if
    one of them consumed the tap (otherwise loop() wakes a blank display).
    Overlay handlers swallow every tap while their overlay is open."""
    # Cleaning-day fullscreen (display "blank"): chore rows open the
    # checklist detail screen instead of waking the dashboard. Early, so
    # stale rects of the hidden dashboard can't steal these taps.
    return (
        handle_egg_click(mx, my)
        or handle_shutdown_click(mx, my)
        or handle_chore_detail_click(mx, my)
        or handle_cleaning_chore_list_click(mx, my)
        or handle_emotion_popup_click(mx, my)
        or handle_quiz_click(mx, my)
        or handle_wifi_qr_click(mx, my)
        or handle_merz_click(mx, my)
        or handle_game_click(mx, my)
        or handle_games_menu_click(mx, my)
        or handle_home_click(mx, my)
    )


def emergency_exit_active():
    """The 5-tap top-left emergency exit is off inside the AFM quiz, the MERZ
    game and the chore checklist detail screen: all tap-heavy, full-screen,
    with their own close button and idle timeout, so the escape hatch is
    never needed there - but repeatedly tapping a control near the corner
    (the quiz "+" zoom button, 2026-10-09) quit the app by accident. The
    detail screen needs that band for rows: real checklists have 8 items.
    Same for the party games (flappy is "tap anywhere"); the PLAY menu
    itself keeps it."""
    return (
        QUIZ_STAGE is None
        and not MERZ_VISIBLE
        and ACTIVE_GAME is None
        and CHORE_DETAIL_ID is None
    )


def draw_dashboard_overlays():
    """Popups and fullscreen views on top of the KiezOS home screen."""
    draw_emotion_prompt_overlay()
    draw_emotion_confirmation_overlay()
    if EMOTION_RESULTS_VISIBLE:
        draw_results_overlay()

    draw_quiz_overlay()
    if WIFI_QR_VISIBLE:
        draw_wifi_qr_overlay()
    draw_merz_overlay()
    draw_games_menu()
    draw_active_game()
    draw_chore_overlay()
    draw_shutdown()
    draw_egg()


# Night mode: the screen is the hallway's light at night, so it stays bright
# but warm/reddish instead of going dark (config NIGHT_MODE).
NIGHT_CONFIG = config.get("NIGHT_MODE", {})


def night_mode_active(now=None):
    if not NIGHT_CONFIG.get("ENABLED", False):
        return False
    t = (now or datetime.datetime.now()).strftime("%H:%M")
    start, end = NIGHT_CONFIG.get("FROM", "23:00"), NIGHT_CONFIG.get("TO", "07:00")
    return start <= t or t < end if start > end else start <= t < end


def apply_night_mode(surf):
    """Multiplies the finished frame with the warm tint (once per frame,
    right before display.update(): every screen redraws fully each frame)."""
    if night_mode_active():
        surf.fill(tuple(NIGHT_CONFIG.get("TINT", [255, 150, 90])), special_flags=pygame.BLEND_MULT)


def _load_tictacdada_avatars():
    """TIC-TAC-DADA's MoaBeats profile pictures, once at start (placeholders
    stay if MoaBeats can't be reached)."""
    try:
        tictacdada.load_avatars(config["MOABEATS"]["API_URL"])
    except Exception as e:
        logger.error(f"TIC-TAC-DADA avatars not loaded: {e}")


def loop():
    global GAMES_LAST_ACTIVITY_TS  # refreshed by game drags in the event loop
    # Start the new scheduler
    scheduler.start_weather_updates()
    scheduler.start_bvg_updates()
    scheduler.start_moabeats_updates()
    if GAMES_ENABLED and config.get("MOABEATS", {}).get("ENABLED", False):
        threading.Thread(target=_load_tictacdada_avatars, daemon=True).start()
    if PINNWAND is not None:
        PINNWAND.start_polling(lambda: not DISPLAY_BLANK)

    # Set X11 display power management settings
    # Sync OS blanking with app blanking timer
    blank_seconds = config["TIMER"]["DISPLAY_BLANK"]
    logger.info(f"Setting up X11 display power management to {blank_seconds}s...")
    os.system(f"xset s {blank_seconds} {blank_seconds}")
    os.system(f"xset dpms {blank_seconds} {blank_seconds} {blank_seconds}")

    last_xset_reset = 0
    running = True

    # PIR Sensor setup - using RPi.GPIO directly
    logger.info("Initializing PIR Motion Sensor...")
    pir_config = config.get("PIR_SENSOR", {})
    is_pir_enabled = pir_config.get("ENABLED", True) and GPIO_AVAILABLE
    pir_gpio_pin = pir_config.get("GPIO_PIN", 17)
    last_pir_state = 0

    if is_pir_enabled and GPIO_AVAILABLE:
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(pir_gpio_pin, GPIO.IN)
            logger.info(f"✓ PIR Sensor initialized on GPIO{pir_gpio_pin}")

            def pir_monitor_loop():
                """Monitor PIR sensor in background thread"""
                nonlocal last_pir_state, is_pir_enabled
                # HC-SR505 has ~8 sec trigger time, use slightly longer debounce
                debounce = 2.0  # Reduced: allow faster re-triggering
                last_motion_time = 0
                pir_reads = 0  # Debug counter

                logger.info(f"PIR Monitor started: GPIO{pir_gpio_pin}, debounce={debounce}s")

                while running and is_pir_enabled:
                    try:
                        current_state = GPIO.input(pir_gpio_pin)
                        pir_reads += 1

                        # Debug: Log every 100 reads
                        if pir_reads % 100 == 0:
                            logger.debug(f"PIR state check #{pir_reads}: {current_state}")

                        # Detect rising edge (motion attempt)
                        if current_state == 1 and last_pir_state == 0:
                            current_time = time.time()
                            logger.debug(f"PIR rising edge detected at {current_time}")

                            # Apply debounce timing
                            if current_time - last_motion_time > debounce:
                                logger.info("✓ Motion detected by PIR! (debounce passed)")
                                on_motion_detected()
                                last_motion_time = current_time
                            else:
                                logger.debug(f"Motion ignored (within debounce window)")

                        # Falling edge: log state change
                        elif current_state == 0 and last_pir_state == 1:
                            logger.debug("PIR falling edge")

                        last_pir_state = current_state
                        time.sleep(0.1)
                    except Exception as e:
                        logger.error(f"PIR monitoring error: {e}")
                        time.sleep(1)

            # Start PIR monitoring in background thread
            pir_thread = threading.Thread(target=pir_monitor_loop, daemon=True)
            pir_thread.start()
            logger.info("PIR Sensor monitoring started")

        except Exception as e:
            logger.error(f"Failed to initialize PIR Sensor: {e}")
            is_pir_enabled = False
    else:
        if not GPIO_AVAILABLE:
            logger.info("PIR Sensor disabled (GPIO not available - not on Raspberry Pi?)")
        else:
            logger.info("PIR Sensor disabled in config")

    # Counter for emergency exit
    exit_clicks = 0

    while running:
        global DISPLAY_BLANK, EMOTION_RESULTS_VISIBLE, QUIZ_STAGE, WIFI_QR_VISIBLE

        if QUIZ_STAGE == "scan" and QUIZ_SCAN_HELD_SECONDS >= QUIZ_SCAN_SECONDS:
            QUIZ_STAGE = "question"
        if (
            QUIZ_STAGE is not None
            and time.time() - QUIZ_LAST_ACTIVITY_TS > QUIZ_IDLE_TIMEOUT_SECONDS
        ):
            dismiss_quiz("idle-timeout")

        activate_pending_emotion_prompt()
        if (
            EMOTION_CONFIRMATION_VISIBLE
            and time.time() - EMOTION_CONFIRMATION_OPENED_AT > EMOTION_CONFIRMATION_SECONDS
        ):
            dismiss_emotion_confirmation("timeout")
        # Standalone footer-triggered QR only (the prompt's own "show results"
        # QR is closed by dismiss_emotion_prompt() instead, e.g. on timeout).
        if (
            EMOTION_RESULTS_VISIBLE
            and not EMOTION_PROMPT_VISIBLE
            and time.time() - EMOLOG_QR_OPENED_AT > EMOLOG_QR_AUTO_CLOSE_SECONDS
        ):
            EMOTION_RESULTS_VISIBLE = False
        if WIFI_QR_VISIBLE and time.time() - WIFI_QR_OPENED_AT > WIFI_QR_AUTO_CLOSE_SECONDS:
            WIFI_QR_VISIBLE = False
        if MERZ_VISIBLE and (
            DISPLAY_BLANK or time.time() - MERZ_LAST_ACTIVITY_TS > GAMES_IDLE_TIMEOUT_SECONDS
        ):
            dismiss_merz_game("display-blank" if DISPLAY_BLANK else "idle-timeout")
        update_chore_screen_timeout()
        update_games_timeout()
        update_kiez_timeouts()
        if DISPLAY_BLANK and EMOTION_PROMPT_VISIBLE:
            dismiss_emotion_prompt("display-blank")
        elif EMOTION_PROMPT_VISIBLE:
            if (
                not EMOTION_KEYBOARD_VISIBLE
                and time.time() - EMOTION_LAST_ACTIVITY_TS > DISPLAY_BLANK_AFTER
            ):
                dismiss_emotion_prompt("timeout")

        if not DISPLAY_BLANK:
            draw_home()
            draw_dashboard_overlays()
            if SHOW_FPS:
                draw_fps()
            apply_night_mode(tft_surf)
            pygame.display.update()

        elif datetime.datetime.today().weekday() == CLEANING_DAY:
            draw_cleaning_day_screen()

            pygame.display.update()

            if time.time() - last_xset_reset > 60:
                # When it's cleaning day, keep display always on :)
                # Reset the system idle timer to prevent screen blanking (set via xset s)
                os.system("xset s reset")
                last_xset_reset = time.time()

        for event in pygame.event.get():

            if event.type == pygame.QUIT:
                running = False
                quit_all()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                # The event's own position, not pygame.mouse.get_pos() (the
                # *current* cursor): at 10 FPS several fast taps can queue up
                # within one frame, and get_pos() would attribute all of them
                # to the last tap's position (e.g. EIER, KLÖTEN tapped quickly
                # both landing on KLÖTEN).
                mx, my = event.pos
                logger.info(f"Screen pressed at: ({mx}, {my})")
                global LAST_TOUCH_TIME
                LAST_TOUCH_TIME = time.time()

                # Secret corner-tap gesture (TL -> TR -> BR -> BL) that plays a
                # local video file full-screen. Tracked passively - never
                # swallows the click - so it can't interfere with real UI
                # near the other three corners.
                handle_secret_video_gesture_tap(secret_video_corner_for_click(mx, my))

                # Emergency exit logic - takes priority over the emotion
                # overlays (popup, keyboard, confirmation), so it can never get
                # swallowed by them. Check if click is in top-left corner.
                # Box is deliberately generous (not 50x50): on the real DSI touchscreen,
                # taps aimed at the physical corner land anywhere up to (85, 160) due to
                # touch calibration imprecision (measured 2026-07-08).
                # Except inside the AFM quiz, the MERZ game and the chore
                # checklist detail screen - see emergency_exit_active().
                if (
                    emergency_exit_active()
                    and mx < EMERGENCY_EXIT_MAX_X
                    and my < EMERGENCY_EXIT_MAX_Y
                ):
                    exit_clicks += 1
                    logger.info(f"Emergency exit click: {exit_clicks}/5")
                    if exit_clicks >= 5:
                        logger.info("Emergency exit triggered!")
                        running = False
                        quit_all()
                    continue
                else:
                    exit_clicks = 0  # Reset if they click elsewhere
                # ----------------------------

                if handle_tap(mx, my):
                    continue

                if DISPLAY_BLANK:
                    logger.info("Going from idle to active.")
                    wake_display("touch", reason="screen_touch")


            elif event.type == pygame.MOUSEBUTTONUP:
                # Only meaningful during two quiz stages: "scan" (lifting
                # stops the hold-thumbprint progress, see
                # draw_quiz_scan_stage()) and "results" (lifting hides
                # whichever other participant's name was being held).
                if QUIZ_STAGE == "scan":
                    handle_quiz_scan_release()
                elif QUIZ_STAGE == "results":
                    handle_quiz_results_release()
                if MERZ_VISIBLE:
                    handle_merz_release()  # stops the BURN flamethrower stream
                if ACTIVE_GAME is not None:
                    ACTIVE_GAME.release()  # ENTEIGNEN!: end of a swipe

            elif event.type == pygame.MOUSEMOTION:
                # Only used to pan the zoomed AFM results triangle by drag.
                if QUIZ_STAGE == "results":
                    handle_quiz_results_motion(*event.pos)
                # Party games see the finger moving while it's down (ENTEIGNEN!'s blade);
                # every event's own position, so fast swipes keep all their points.
                if ACTIVE_GAME is not None and event.buttons[0]:
                    GAMES_LAST_ACTIVITY_TS = time.time()
                    ACTIVE_GAME.drag(event.pos[0], event.pos[1] - GAME_TITLE_HEIGHT)

            elif event.type == pygame.KEYDOWN:

                if handle_emotion_keyboard_keydown(event):
                    continue

                if event.key == pygame.K_ESCAPE:
                    running = False
                    quit_all()

                elif event.key == pygame.K_SPACE:
                    shot_time = convert_timestamp(time.time(), "%Y-%m-%d %H-%M-%S")
                    pygame.image.save(tft_surf, f"screenshot-{shot_time}.png")
                    logger.info(f"Screenshot created at {shot_time}")

        if not DISPLAY_BLANK and time.time() - LAST_TOUCH_TIME > DISPLAY_BLANK_AFTER:
            logger.info("Screen (likely/hopefully) blanked. Switching to idle.")
            record_uptime_event(
                "screen_off",
                source="idle_timeout",
                reason=f"display_blank_after={DISPLAY_BLANK_AFTER}",
            )
            DISPLAY_BLANK = True

        # do it as often as FPS configured (30 FPS recommend for particle
        #  simulation, 15 runs fine too, 60 is overkill)
        if MERZ_VISIBLE or games_open():
            clock.tick(GAMES_FPS)
        elif QUIZ_STAGE is not None:
            clock.tick(QUIZ_FPS)
        else:
            clock.tick(FPS)

    quit_all()


if __name__ == "__main__":

    try:

        images = image_factory(ICON_PATH)

        loop()

    except KeyboardInterrupt:

        quit_all()
