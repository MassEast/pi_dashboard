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
import json
import locale
import logging
import math
import os
import random
import re
import socket
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
from uptime_store import append_uptime_event
from utils import get_stop_data

# Allow the system to manage blanking
os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "1"

# Use absolute path handling to be safe in autostart contexts
PATH = os.path.dirname(os.path.abspath(__file__)) + "/"
ICON_PATH = PATH + "icons/"
FONT_PATH = PATH + "fonts/"
LOG_PATH = PATH + "logs/"
UPTIME_LOG_PATH = PATH + "logs/"
EMOTION_LOG_PATH = PATH + "logs/"

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
    logger.warning("RPi.GPIO not available - PIR Sensor support disabled (must run on Raspberry Pi)")

theme_config = config["THEME"]

# Parse cleaning day config
days_map = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6
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

BVG_DEPARTURE_ID = config["BVG"]["DEPARTURE_ID"]
BVG_DIRECTION_ID_LEFT = config["BVG"]["DIRECTION_ID_LEFT"]
BVG_DIRECTION_ID_RIGHT = config["BVG"]["DIRECTION_ID_RIGHT"]
BVG_LINE = config["BVG"]["LINE"]
BVG_LOOKAHEAD_MIN = config["BVG"]["LOOKAHEAD_MIN"]
BVG_LOOKBACK_MIN = config["BVG"]["LOOKBACK_MIN"]

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
    schedule_emotion_prompt(source)
    threading.Thread(target=BVGUpdate.update_bvg_stop_information).start()
    logger.info("BVG update triggered immediately (out of cycle).")
    return True


class SimpleScheduler:
    """Simple, clean scheduler for weather and BVG updates"""

    def __init__(self):
        self.weather_timer = None
        self.bvg_timer = None
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

            # Schedule next cycle
            if self.running:
                self.weather_timer = threading.Timer(
                    config["TIMER"]["WEATHER_UPDATE"], weather_cycle
                )
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


# Global scheduler instance
scheduler = SimpleScheduler()

def safe_network_monitor():
    """
    Checks for internet connection.
    Only allows reboot if system has been up for >10 minutes to prevent boot loops and give time to
    SSH in.
    """

    global NETWORK_AVAILABLE

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
            except Exception:
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
EMOTION_SHUFFLED_OPTIONS = []
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
    resolved_color = color if isinstance(color, str) and EMOTION_COLOR_RE.match(color) else style["color"]
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

    return (
        EMOTION_LLM_PROMPT_TEMPLATE
        .replace("{{catalog_json}}", json.dumps(catalog, ensure_ascii=False))
        .replace("{{new_emotion_json}}", json.dumps({"name": new_emotion}, ensure_ascii=False))
    )


def _classify_custom_emotion(name):
    style = EMOTION_DEFAULT_STYLE.get(name, EMOTION_FALLBACK_STYLE)
    fallback = {"name": name, "emoji": style["emoji"], "color": style["color"], "insert_after": None}

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
        logger.info("🤖 LLM: Raw API response payload:\n%s", json.dumps(payload, ensure_ascii=False, indent=2))

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
        return {"emotion": normalized, "added": False, "duplicate": True, "reason": "default-options"}

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
        logger.info(f"✏️  Custom emotion: LLM corrected '{normalized}' → '{llm_name}' (already in catalog)")
        return {"emotion": llm_name, "added": False, "duplicate": True, "reason": "llm-catalog-correction"}

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
        logger.info(f"✏️  Custom emotion: Replaced '{old_emotion}' (usage={[left_usage, right_usage][replace_index]}) with '{llm_name}'")

    # Add to catalog with LLM-suggested emoji, color, and position
    _ensure_catalog_entry(
        llm_name,
        emoji=classification.get("emoji"),
        color=classification.get("color"),
        insert_after=classification.get("insert_after"),
    )

    EMOTION_CUSTOM_SLOTS = slots
    _persist_emotion_config(slots)
    logger.info(f"✏️  Custom emotion: Successfully added '{llm_name}' to catalog and persisted config")
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


def get_emotion_grid_columns(option_count):
    # Keep tap targets large while scaling from 8 to 16 emotions.
    if option_count <= 10:
        return 2
    if option_count <= 14:
        return 3
    return 4


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


# display settings from theme config
DISPLAY_WIDTH = int(config["DISPLAY"]["WIDTH"])
DISPLAY_HEIGHT = int(config["DISPLAY"]["HEIGHT"])

# the drawing area to place all text and img on
SURFACE_WIDTH = 240
SURFACE_HEIGHT = 320

SCALE = float(DISPLAY_WIDTH / SURFACE_WIDTH)
ZOOM = 1

FPS = config["DISPLAY"]["FPS"]
SHOW_FPS = config["DISPLAY"]["SHOW_FPS"]
AA = config["DISPLAY"]["AA"]
ANIMATION = config["DISPLAY"]["ANIMATION"]


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
        SURFACE_WIDTH = int(240 * ZOOM)
        SURFACE_HEIGHT = int(320 * ZOOM)
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

# the drawing area - everything will be drawn here before scaling and rendering on the display tft_surf
display_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
# dynamic surface for status bar updates and dynamic values like fps
dynamic_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
# exclusive surface for the time
time_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
# exclusive surface for the mouse/touch events
mouse_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
# surface for the weather data - will only be created once if the data is updated from the api
weather_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
# surface for the BVG departure data - will only be updated when the BVG API is called and delivers new data
bvg_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))

clock = pygame.time.Clock()

logger.info(
    f"display with {DISPLAY_WIDTH}px width and {DISPLAY_HEIGHT}px height is "
    f"set to {FPS} FPS with AA {AA}"
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
FONT_BIG_BOLD = pygame.font.Font(FONT_PATH + FONT_BOLD, BIG_SIZE)
DATE_FONT = pygame.font.Font(FONT_PATH + FONT_BOLD, DATE_SIZE)
CLOCK_FONT = pygame.font.Font(FONT_PATH + FONT_BOLD, CLOCK_SIZE)
CLEANING_FONT = pygame.font.Font(FONT_PATH + FONT_BOLD, 80)


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


class Particles(object):
    def __init__(self):
        self.size = int(20 * ZOOM)
        self.count = 20
        self.surf = pygame.Surface((self.size, self.size))

    def create_particle_list(self):

        particle_list = []

        for i in range(self.count):
            x = random.randrange(0, self.size)
            y = random.randrange(0, self.size)
            w = int(1 * ZOOM)
            h = random.randint(int(2 * ZOOM), int(3 * ZOOM))
            speed = random.choice([1, 2, 3])
            color = random.choice(COLOR_LIST)
            direct = random.choice([0, 0, 1])
            particle_list.append([x, y, w, h, speed, color, direct])
        return particle_list

    def move(self, surf, particle_list):
        # Process each snow flake in the list
        self.surf.fill(BACKGROUND)
        self.surf.set_colorkey(BACKGROUND)

        if not PRECIPTYPE == config["LOCALE"]["PRECIP_STR"]:

            for i in range(len(particle_list)):

                particle = particle_list[i]
                x, y, w, h, speed, color, direct = particle

                # Draw the snow flake
                if PRECIPTYPE == config["LOCALE"]["RAIN_STR"]:
                    pygame.draw.rect(self.surf, color, (x, y, w, h), 0)
                else:
                    pygame.draw.rect(self.surf, PRECIPCOLOR, (x, y, 2, 2), 0)

                # Move the snow flake down one pixel
                particle_list[i][1] += speed if PRECIPTYPE == config["LOCALE"]["RAIN_STR"] else 1
                if random.choice([True, False]):
                    if PRECIPTYPE == config["LOCALE"]["SNOW_STR"]:
                        particle_list[i][0] += 1 if direct else 0

                # If the snow flake has moved off the bottom of the screen
                if particle_list[i][1] > self.size:
                    # Reset it just above the top
                    y -= self.size
                    particle_list[i][1] = y
                    # Give it a new x position
                    x = random.randrange(0, self.size)
                    particle_list[i][0] = x

            surf.blit(self.surf, (int(130 * ZOOM), int(90 * ZOOM)))


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

            new_image = self.image.resize((width, height), Image.LANCZOS if AA else Image.BILINEAR)
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
        """Process weather data and create surface"""
        global WEATHER_JSON_DATA

        WEATHER_JSON_DATA = data
        WeatherUpdate.icon_path()

    @staticmethod
    def icon_path():

        global WEATHERICON, FORECASTICON_DAY_1, FORECASTICON_DAY_2, FORECASTICON_DAY_3, PRECIPTYPE, PRECIPCOLOR, UPDATING

        icon_extension = ".png"

        updated_list = []

        icon = WEATHER_JSON_DATA["current"]["data"][0]["weather"]["icon"]

        forecast_icon_1 = WEATHER_JSON_DATA["daily"]["data"][1]["weather"]["icon"]
        forecast_icon_2 = WEATHER_JSON_DATA["daily"]["data"][2]["weather"]["icon"]
        forecast_icon_3 = WEATHER_JSON_DATA["daily"]["data"][3]["weather"]["icon"]

        forecast = (
            str(icon),
            str(forecast_icon_1),
            str(forecast_icon_2),
            str(forecast_icon_3),
        )

        logger.debug(forecast)

        logger.debug(f"validating path: {forecast}")

        for icon in forecast:

            if os.path.isfile(ICON_PATH + icon + icon_extension):

                logger.debug(f"TRUE : {icon}")

                updated_list.append(icon)

            else:

                logger.warning(f"FALSE : {icon}")

                updated_list.append("unknown")

        WEATHERICON = updated_list[0]
        FORECASTICON_DAY_1 = updated_list[1]
        FORECASTICON_DAY_2 = updated_list[2]
        FORECASTICON_DAY_3 = updated_list[3]

        global PATH_ERROR

        if any("unknown" in s for s in updated_list):

            PATH_ERROR = True

        else:

            PATH_ERROR = False

        logger.info(f"update path for icons: {updated_list}")

        WeatherUpdate.get_precip_type()

    @staticmethod
    def get_precip_type():

        global WEATHER_JSON_DATA, PRECIPCOLOR, PRECIPTYPE

        pop = int(WEATHER_JSON_DATA["daily"]["data"][0]["pop"])
        rain = float(WEATHER_JSON_DATA["daily"]["data"][0]["precip"])
        snow = float(WEATHER_JSON_DATA["daily"]["data"][0]["snow"])

        if pop == 0:

            PRECIPTYPE = config["LOCALE"]["PRECIP_STR"]
            PRECIPCOLOR = GREEN

        else:

            if pop > 0 and rain > snow:

                PRECIPTYPE = config["LOCALE"]["RAIN_STR"]
                PRECIPCOLOR = BLUE

            elif pop > 0 and snow > rain:

                PRECIPTYPE = config["LOCALE"]["SNOW_STR"]
                PRECIPCOLOR = WHITE

        logger.info(f"update PRECIPPOP to: {pop} %")
        logger.info(f"update PRECIPTYPE to: {PRECIPTYPE}")
        logger.info(f"update PRECIPCOLOR to: {PRECIPCOLOR}")

        WeatherUpdate.create_surface()

    @staticmethod
    def create_surface():

        current_forecast = WEATHER_JSON_DATA["current"]["data"][0]
        daily_forecast = WEATHER_JSON_DATA["daily"]["data"]
        stats_data = WEATHER_JSON_DATA["stats"]

        summary_string = current_forecast["weather"]["description"]
        temp_out = str(int(current_forecast["temp"]))
        temp_out_unit = "°C" if METRIC else "°F"
        temp_out_string = str(temp_out + temp_out_unit)
        precip = WEATHER_JSON_DATA["daily"]["data"][0]["pop"]
        precip_string = str(f"{precip}%")

        today = daily_forecast[0]
        day_1 = daily_forecast[1]
        day_2 = daily_forecast[2]
        day_3 = daily_forecast[3]

        df_forecast = theme["DATE_FORMAT"]["FORECAST_DAY"]
        df_sun = theme["DATE_FORMAT"]["SUNRISE_SUNSET"]

        day_1_ts = time.mktime(time.strptime(day_1["datetime"], "%Y-%m-%d"))
        day_1_ts = convert_timestamp(day_1_ts, df_forecast)
        day_2_ts = time.mktime(time.strptime(day_2["datetime"], "%Y-%m-%d"))
        day_2_ts = convert_timestamp(day_2_ts, df_forecast)
        day_3_ts = time.mktime(time.strptime(day_3["datetime"], "%Y-%m-%d"))
        day_3_ts = convert_timestamp(day_3_ts, df_forecast)

        today_min_max_temp = f"({int(today['high_temp'])} | {int(today['low_temp'])})"
        day_1_min_max_temp = f"{int(day_1['high_temp'])} | {int(day_1['low_temp'])}"
        day_2_min_max_temp = f"{int(day_2['high_temp'])} | {int(day_2['low_temp'])}"
        day_3_min_max_temp = f"{int(day_3['high_temp'])} | {int(day_3['low_temp'])}"

        sunrise = convert_timestamp(today["sunrise_ts"], df_sun)
        sunset = convert_timestamp(today["sunset_ts"], df_sun)

        wind_direction = str(current_forecast["wind_cdir"])
        wind_speed = float(current_forecast["wind_spd"])
        wind_speed = wind_speed * 3.6 if METRIC else wind_speed
        wind_speed_unit = "km/h" if METRIC else "mph"
        wind_speed_string = str(f"{round(wind_speed, 1)} {wind_speed_unit}")

        global weather_surf, UPDATING

        new_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
        new_surf.fill(BACKGROUND)

        DrawImage(
            new_surf,
            images["wifi"],
            5,
            size=15,
            fillcolor=RED if CONNECTION_ERROR else GREEN,
        ).left()
        DrawString(new_surf, "weather", FONT_SUPER_TINY, MAIN_FONT, 18).left(-2)
        DrawString(new_surf, "API", FONT_SUPER_TINY, MAIN_FONT, 25).left(2)
        DrawImage(
            new_surf,
            images["refresh"],
            5,
            size=15,
            fillcolor=RED if REFRESH_ERROR else GREEN,
        ).right(8)
        DrawImage(
            new_surf,
            images["path"],
            5,
            size=15,
            fillcolor=RED if PATH_ERROR else GREEN,
        ).right(-5)

        DrawImage(new_surf, images[WEATHERICON], 43, size=100).center(2, 0, offset=10)

        if not ANIMATION:
            if PRECIPTYPE == config["LOCALE"]["RAIN_STR"]:

                DrawImage(new_surf, images["preciprain"], size=20).draw_position(pos=(130, 86))

            elif PRECIPTYPE == config["LOCALE"]["SNOW_STR"]:

                DrawImage(new_surf, images["precipsnow"], size=20).draw_position(pos=(130, 86))

        DrawImage(new_surf, images["sunrise"], 132, size=20).left()
        DrawImage(new_surf, images["sunset"], 152, size=20).left()

        draw_wind_layer(new_surf, current_forecast["wind_dir"], 142)

        draw_moon_layer(new_surf, int(132 * ZOOM), int(42 * ZOOM))

        DrawImage(new_surf, images[FORECASTICON_DAY_1], 210, size=50).center(3, 0)
        DrawImage(new_surf, images[FORECASTICON_DAY_2], 210, size=50).center(3, 1)
        DrawImage(new_surf, images[FORECASTICON_DAY_3], 210, size=50).center(3, 2)

        # draw all the strings
        if config["DISPLAY"]["SHOW_API_STATS"]:
            DrawString(
                new_surf, str(stats_data["calls_remaining"]), FONT_SMALL_BOLD, BLUE, 20
            ).right(offset=-5)

        # DrawString(new_surf, summary_string, FONT_SMALL_BOLD, VIOLET, 50).center(1, 0)
        # Ignoring the summary string for now (like "Scattered clouds")

        DrawString(new_surf, temp_out_string, FONT_BIG, ORANGE, 50).right(33)
        DrawString(new_surf, today_min_max_temp, FONT_TINY, MAIN_FONT, 64).right(-10)
        DrawString(new_surf, precip_string, FONT_BIG, PRECIPCOLOR, 84).right(10)
        # Ignoring the "Precipitation" label for now
        # DrawString(new_surf, PRECIPTYPE, FONT_SMALL_BOLD, PRECIPCOLOR, 140).right()

        DrawString(new_surf, sunrise, FONT_SMALL_BOLD, MAIN_FONT, 135).left(30)
        DrawString(new_surf, sunset, FONT_SMALL_BOLD, MAIN_FONT, 154).left(30)

        # DrawString(new_surf, wind_direction, FONT_SMALL_BOLD, MAIN_FONT, 250).center(
        #     3, 2
        # )
        DrawString(new_surf, wind_speed_string, FONT_SMALL_BOLD, MAIN_FONT, 154).center(3, 2)


        DrawString(new_surf, day_1_ts, FONT_SMALL_BOLD, ORANGE, 176).center(3, 0)
        DrawString(new_surf, day_2_ts, FONT_SMALL_BOLD, ORANGE, 176).center(3, 1)
        DrawString(new_surf, day_3_ts, FONT_SMALL_BOLD, ORANGE, 176).center(3, 2)

        DrawString(new_surf, day_1_min_max_temp, FONT_SMALL_BOLD, MAIN_FONT, 191).center(3, 0)
        DrawString(new_surf, day_2_min_max_temp, FONT_SMALL_BOLD, MAIN_FONT, 191).center(3, 1)
        DrawString(new_surf, day_3_min_max_temp, FONT_SMALL_BOLD, MAIN_FONT, 191).center(3, 2)


        weather_surf = new_surf

        logger.info(f"summary: {summary_string}")
        logger.info(f"temp out: {temp_out_string}")
        logger.info(f"{PRECIPTYPE}: {precip_string}")
        logger.info(f"icon: {WEATHERICON}")
        logger.info(
            f"forecast: "
            f"{day_1_ts} {day_1_min_max_temp} {FORECASTICON_DAY_1}; "
            f"{day_2_ts} {day_2_min_max_temp} {FORECASTICON_DAY_2}; "
            f"{day_3_ts} {day_3_min_max_temp} {FORECASTICON_DAY_3}"
        )
        logger.info(f"sunrise: {sunrise} ; sunset {sunset}")
        logger.info(f"WindSpeed: {wind_speed_string}")

        pygame.time.delay(1500)
        UPDATING = pygame.time.get_ticks() + 1500  # 1.5 seconds

        return weather_surf


class BVGUpdate(object):

    @staticmethod
    def update_bvg_stop_information():
        """Simple BVG update without self-scheduling"""
        global UPDATED_BVG_TIME, BVG_STOP_INFORMATION, BVG_AVAILABLE

        if DISPLAY_BLANK:
            return

        try:
            UPDATED_BVG_TIME, BVG_STOP_INFORMATION = get_stop_data(
                BVG_DEPARTURE_ID,
                BVG_DIRECTION_ID_LEFT,
                BVG_DIRECTION_ID_RIGHT,
                BVG_LINE,
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
        if UPDATED_BVG_TIME is not None:
            BVGUpdate.create_surface()
            logger.info("BVG surface created")

    @staticmethod
    def create_surface():
        global bvg_surf, UPDATED_BVG_TIME, BVG_STOP_INFORMATION
        new_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
        new_surf.fill(BACKGROUND)
        new_surf.set_colorkey(BACKGROUND)
        logger.info("Creating BVG surface")

        if len(BVG_STOP_INFORMATION) > 0:  # Make sure that API really gave something
            # Clear of cancelled stops
            if "cancelled" in BVG_STOP_INFORMATION.columns:
                BVG_STOP_INFORMATION = BVG_STOP_INFORMATION[~BVG_STOP_INFORMATION["cancelled"]]

            # Draw a line of bus information for direction to the left
            DrawImage(new_surf, images["arrow"], 262, size=13, fillcolor=RED, angle=90).left(-3)
            left_departure_times = []
            left_departure_delays = []
            # Print closest three connections for each direction
            if len(BVG_STOP_INFORMATION) and len(
                results_left := BVG_STOP_INFORMATION[
                    BVG_STOP_INFORMATION["direction_str"] == "left"
                ]
            ):
                departures_reported = 0
                for _, departure in results_left.iterrows():
                    if departures_reported >= 3:
                        break
                    delay = departure["delay"]
                    departure_time = departure['departure']
                    left_departure_times.append(departure_time)
                    left_departure_delays.append(delay)
                    departures_reported += 1

            DrawImage(new_surf, images["bus"], 263, size=10).left(10)  # (TODO): make this image variable here according to lane (resp. ask for it in the config file)
            DrawString(new_surf, BVG_LINE + ":", FONT_SMALL, ORANGE, 260).left(22)
            if left_departure_times:
                departure_x = int(68 * ZOOM)
                for index, departure_time in enumerate(left_departure_times):
                    if index > 0:
                        comma_surface = FONT_SMALL.render(",", True, ORANGE)
                        new_surf.blit(comma_surface, (departure_x, int(260 * ZOOM)))
                        departure_x += comma_surface.get_width()

                    departure_color = _delay_to_departure_text_color(left_departure_delays[index])
                    departure_surface = FONT_SMALL.render(departure_time, True, departure_color)
                    new_surf.blit(departure_surface, (departure_x, int(260 * ZOOM)))
                    departure_x += departure_surface.get_width()
                # DrawImage(new_surf, images["haltestelle"], 263, size=10).right(10)
            else:
                bvg_print = "none :("

                DrawString(new_surf, bvg_print, FONT_SMALL, ORANGE, 260).left(60)

            # Perform same stuff for the right direction
            DrawImage(new_surf, images["arrow"], 282, size=13, fillcolor=RED, angle=-90).left(-3)
            right_departure_times = []
            right_departure_delays = []
            DrawString(new_surf, BVG_LINE + ":", FONT_SMALL, ORANGE, 280).left(22)
            bvg_print = "none :("
            # Print closest two connections for each direction
            if len(BVG_STOP_INFORMATION) and len(
                results_right := BVG_STOP_INFORMATION[
                    BVG_STOP_INFORMATION["direction_str"] == "right"
                ]
            ):
                departures_reported = 0
                for _, departure in results_right.iterrows():
                    if departures_reported >= 3:
                        break
                    delay = departure["delay"]
                    departure_time = departure['departure']
                    right_departure_times.append(departure_time)
                    right_departure_delays.append(delay)
                    departures_reported += 1

            DrawImage(new_surf, images["bus"], 283, size=10).left(10)  # (TODO): make this image variable here according to lane (resp. ask for it in the config file)
            if right_departure_times:
                departure_x = int(68 * ZOOM)
                for index, departure_time in enumerate(right_departure_times):
                    if index > 0:
                        comma_surface = FONT_SMALL.render(",", True, ORANGE)
                        new_surf.blit(comma_surface, (departure_x, int(280 * ZOOM)))
                        departure_x += comma_surface.get_width()

                    departure_color = _delay_to_departure_text_color(right_departure_delays[index])
                    departure_surface = FONT_SMALL.render(departure_time, True, departure_color)
                    new_surf.blit(departure_surface, (departure_x, int(280 * ZOOM)))
                    departure_x += departure_surface.get_width()
                # DrawImage(new_surf, images["haltestelle"], 283, size=10).right(10)
            else:
                DrawString(new_surf, bvg_print, FONT_SMALL, ORANGE, 280).left(60)

        # Extra information
        ju_msg = "Ju likes you. Have a nice day!"
        if UPDATED_BVG_TIME is not None and UPDATED_BVG_TIME is not False:
            actuality_msg = "BVG API: {}".format(convert_timestamp(UPDATED_BVG_TIME, "%H:%M:%S"))
        else:
            actuality_msg = "BVG API: no data"
        emolog_msg = f"emolog/stats: {get_results_url()}"
        DrawString(new_surf, ju_msg, FONT_TINY, WHITE, 301).left()
        DrawImage(new_surf, images["refresh"], 302, size=10, fillcolor=YELLOW).right(55)
        DrawString(new_surf, actuality_msg, FONT_SUPER_TINY, WHITE, 304).right(-3)
        DrawString(new_surf, emolog_msg, FONT_SUPER_TINY, SWEET_PURPLE, 312).left()

        bvg_surf = new_surf

        pygame.time.delay(1500)

        return bvg_surf

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
    global EMOTION_SHUFFLED_OPTIONS, EMOTION_CUSTOM_SLOTS, EMOTION_KEYBOARD_VISIBLE
    global EMOTION_KEYBOARD_TEXT, EMOTION_CUSTOM_BUTTON_RECTS, EMOTION_KEYBOARD_RECTS
    global EMOTION_LAST_ACTIVITY_TS

    if not EMOTION_ENABLED or DISPLAY_BLANK:
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
    EMOTION_SHUFFLED_OPTIONS = get_emotion_prompt_options(max_count=16)
    random.shuffle(EMOTION_SHUFFLED_OPTIONS)
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
    dashboard_rect = pygame.Rect(FIT_SCREEN[0], FIT_SCREEN[1], SURFACE_WIDTH, SURFACE_HEIGHT)

    fog = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.SRCALPHA)
    fog.fill((0, 0, 0, 200))
    tft_surf.blit(fog, (0, 0))

    if EMOTION_MODAL_RECT is not None:
        card = EMOTION_MODAL_RECT.inflate(-int(EMOTION_MODAL_RECT.width * 0.08), -int(EMOTION_MODAL_RECT.height * 0.08))
    else:
        fallback = dashboard_rect.inflate(-int(dashboard_rect.width * 0.10), -int(dashboard_rect.height * 0.10))
        card = fallback

    pygame.draw.rect(tft_surf, WHITE, card, border_radius=16)
    pygame.draw.rect(tft_surf, DARK_GRAY, card, width=2, border_radius=16)

    title = FONT_SMALL_BOLD.render("Scan for results", True, BLACK)
    tft_surf.blit(title, title.get_rect(midtop=(card.centerx, card.top + 12)))

    url = get_results_url()
    qr_size = min(card.width - 36, card.height - 124)
    qr_surface = get_qr_surface(url, pixel_size=max(120, qr_size))
    qr_rect = qr_surface.get_rect(center=(card.centerx, card.centery + 12))
    tft_surf.blit(qr_surface, qr_rect)

    ip_text = FONT_TINY.render(url, True, BLACK)
    tft_surf.blit(ip_text, ip_text.get_rect(midbottom=(card.centerx, card.bottom - 26)))

    hint_text = FONT_SUPER_TINY.render("Tap anywhere to close", True, DARK_GRAY)
    tft_surf.blit(hint_text, hint_text.get_rect(midbottom=(card.centerx, card.bottom - 8)))


def draw_emotion_confirmation_overlay():
    if not EMOTION_CONFIRMATION_VISIBLE:
        return

    fog = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.SRCALPHA)
    fog.fill((0, 0, 0, 120))
    tft_surf.blit(fog, (0, 0))

    dashboard_rect = pygame.Rect(FIT_SCREEN[0], FIT_SCREEN[1], SURFACE_WIDTH, SURFACE_HEIGHT)

    message_lines = [line for line in EMOTION_CONFIRMATION_TEXT.splitlines() if line.strip()]
    if not message_lines:
        message_lines = [EMOTION_CONFIRMATION_TEXT]

    title_surface = FONT_SMALL_BOLD.render("Emotion saved", True, BLACK)
    message_surfaces = [FONT_TINY.render(line, True, DARK_GRAY) for line in message_lines]
    hint_surface = FONT_SUPER_TINY.render("Tap to close", True, DARK_GRAY)

    content_width = max(
        title_surface.get_width(),
        hint_surface.get_width(),
        max((surface.get_width() for surface in message_surfaces), default=0),
    )
    card_width = max(160, min(int(dashboard_rect.width * 0.92), content_width + 32))

    card_height = max(72, 58 + (len(message_lines) * 14))
    card = pygame.Rect(0, 0, card_width, card_height)
    card.center = (DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2)

    pygame.draw.rect(tft_surf, WHITE, card, border_radius=14)
    pygame.draw.rect(tft_surf, SWEET_PURPLE, card, width=2, border_radius=14)

    tft_surf.blit(title_surface, title_surface.get_rect(midtop=(card.centerx, card.top + 10)))

    message_top = card.top + 34
    line_gap = 2
    for index, message_surface in enumerate(message_surfaces):
        line_y = message_top + index * (message_surface.get_height() + line_gap)
        tft_surf.blit(message_surface, message_surface.get_rect(midtop=(card.centerx, line_y)))

    tft_surf.blit(hint_surface, hint_surface.get_rect(midbottom=(card.centerx, card.bottom - 8)))


def draw_emotion_prompt_overlay():
    global EMOTION_MODAL_RECT, EMOTION_BUTTON_RECTS, EMOTION_ACTION_RECTS
    global EMOTION_CUSTOM_BUTTON_RECTS, EMOTION_KEYBOARD_RECTS

    if not EMOTION_PROMPT_VISIBLE:
        return

    fog = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.SRCALPHA)
    fog.fill((0, 0, 0, 170))
    tft_surf.blit(fog, (0, 0))

    dashboard_rect = pygame.Rect(FIT_SCREEN[0], FIT_SCREEN[1], SURFACE_WIDTH, SURFACE_HEIGHT)
    margin_x = int(dashboard_rect.width * 0.10)
    margin_y = int(dashboard_rect.height * 0.10)
    EMOTION_MODAL_RECT = pygame.Rect(
        dashboard_rect.left + margin_x,
        dashboard_rect.top + margin_y,
        dashboard_rect.width - 2 * margin_x,
        dashboard_rect.height - 2 * margin_y,
    )

    pygame.draw.rect(tft_surf, WHITE, EMOTION_MODAL_RECT, border_radius=16)
    pygame.draw.rect(tft_surf, DARK_GRAY, EMOTION_MODAL_RECT, width=2, border_radius=16)

    close_size = 28
    close_rect = pygame.Rect(
        EMOTION_MODAL_RECT.right - close_size - 10,
        EMOTION_MODAL_RECT.top + 10,
        close_size,
        close_size,
    )
    pygame.draw.rect(tft_surf, ORANGE, close_rect, border_radius=8)
    pygame.draw.rect(tft_surf, YELLOW, close_rect, width=2, border_radius=8)
    close_text = FONT_SMALL_BOLD.render("x", True, BLACK)
    tft_surf.blit(close_text, close_text.get_rect(center=close_rect.center))

    title_line_1_text = "Most prevalent emotion"
    title_line_2_text = "right now?"
    max_title_width = close_rect.left - EMOTION_MODAL_RECT.left - 22
    question_font = FONT_SMALL if FONT_SMALL.size(title_line_1_text)[0] <= max_title_width else FONT_TINY

    title_center_x = int((EMOTION_MODAL_RECT.left + close_rect.left - 8) / 2)
    title_line_1 = question_font.render(title_line_1_text, True, BLACK)
    title_line_2 = question_font.render(title_line_2_text, True, BLACK)
    title_line_1_rect = title_line_1.get_rect(midtop=(title_center_x, EMOTION_MODAL_RECT.top + 16))
    title_line_2_rect = title_line_2.get_rect(midtop=(title_center_x, title_line_1_rect.bottom + 2))
    tft_surf.blit(title_line_1, title_line_1_rect)
    tft_surf.blit(title_line_2, title_line_2_rect)

    inner_pad = 14
    button_area_top = title_line_2_rect.bottom + 12
    action_height = 44
    button_gap = 8
    action_y = EMOTION_MODAL_RECT.bottom - action_height - inner_pad
    action_width = EMOTION_MODAL_RECT.width - 2 * inner_pad

    EMOTION_BUTTON_RECTS = []
    EMOTION_CUSTOM_BUTTON_RECTS = []
    EMOTION_KEYBOARD_RECTS = []

    if EMOTION_KEYBOARD_VISIBLE:
        input_rect = pygame.Rect(
            EMOTION_MODAL_RECT.left + inner_pad,
            button_area_top,
            action_width,
            34,
        )
        pygame.draw.rect(tft_surf, (245, 245, 245), input_rect, border_radius=8)
        pygame.draw.rect(tft_surf, DARK_GRAY, input_rect, width=1, border_radius=8)

        typed = EMOTION_KEYBOARD_TEXT if EMOTION_KEYBOARD_TEXT else "type custom emotion"
        typed_color = BLACK if EMOTION_KEYBOARD_TEXT else DARK_GRAY
        typed_text = FONT_TINY.render(typed, True, typed_color)
        tft_surf.blit(typed_text, typed_text.get_rect(midleft=(input_rect.left + 8, input_rect.centery)))

        keys_area_top = input_rect.bottom + 8
        keys_area_bottom = action_y - 8
        keyboard_rows = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
        key_height = max(20, int((keys_area_bottom - keys_area_top - 5 * 6) / 4))

        row_y = keys_area_top
        for row_chars in keyboard_rows:
            chars = list(row_chars)
            gap = 6
            key_width = int((action_width - (len(chars) - 1) * gap) / len(chars))
            for idx, char in enumerate(chars):
                key_x = EMOTION_MODAL_RECT.left + inner_pad + idx * (key_width + gap)
                key_rect = pygame.Rect(key_x, row_y, key_width, key_height)
                pygame.draw.rect(tft_surf, SWEET_PURPLE, key_rect, border_radius=6)
                pygame.draw.rect(tft_surf, VIOLET, key_rect, width=1, border_radius=6)
                key_text = FONT_TINY.render(char, True, BLACK)
                tft_surf.blit(key_text, key_text.get_rect(center=key_rect.center))
                EMOTION_KEYBOARD_RECTS.append({"token": char, "rect": key_rect})
            row_y += key_height + 6

        fn_tokens = ["space", "back", "clear"]
        gap = 6
        fn_width = int((action_width - 2 * gap) / 3)
        for idx, token in enumerate(fn_tokens):
            fn_x = EMOTION_MODAL_RECT.left + inner_pad + idx * (fn_width + gap)
            fn_rect = pygame.Rect(fn_x, row_y, fn_width, key_height)
            pygame.draw.rect(tft_surf, (230, 230, 230), fn_rect, border_radius=6)
            pygame.draw.rect(tft_surf, DARK_GRAY, fn_rect, width=1, border_radius=6)
            fn_text = FONT_TINY.render(token, True, BLACK)
            tft_surf.blit(fn_text, fn_text.get_rect(center=fn_rect.center))
            EMOTION_KEYBOARD_RECTS.append({"token": token, "rect": fn_rect})

        cancel_rect = pygame.Rect(
            EMOTION_MODAL_RECT.left + inner_pad,
            action_y,
            int((action_width - button_gap) / 2),
            action_height,
        )
        save_rect = pygame.Rect(
            cancel_rect.right + button_gap,
            action_y,
            int((action_width - button_gap) / 2),
            action_height,
        )

        pygame.draw.rect(tft_surf, ORANGE, cancel_rect, border_radius=10)
        pygame.draw.rect(tft_surf, DARK_GRAY, cancel_rect, width=2, border_radius=10)
        pygame.draw.rect(tft_surf, GREEN, save_rect, border_radius=10)
        pygame.draw.rect(tft_surf, DARK_GRAY, save_rect, width=2, border_radius=10)

        cancel_text = FONT_SMALL_BOLD.render("Cancel", True, BLACK)
        save_text = FONT_SMALL_BOLD.render("Save", True, BLACK)
        tft_surf.blit(cancel_text, cancel_text.get_rect(center=cancel_rect.center))
        tft_surf.blit(save_text, save_text.get_rect(center=save_rect.center))

        EMOTION_ACTION_RECTS = {
            "close": close_rect,
            "keyboard_cancel": cancel_rect,
            "keyboard_save": save_rect,
        }
    else:
        custom_row_height = 38
        button_area_bottom = action_y - custom_row_height - 16
        options = EMOTION_SHUFFLED_OPTIONS if EMOTION_SHUFFLED_OPTIONS else get_emotion_prompt_options(max_count=16)
        columns = get_emotion_grid_columns(len(options))
        rows = max(1, math.ceil(len(options) / columns))

        button_width = int((EMOTION_MODAL_RECT.width - (2 * inner_pad) - ((columns - 1) * button_gap)) / columns)
        button_height = int((button_area_bottom - button_area_top - ((rows - 1) * button_gap)) / rows)

        for idx, emotion in enumerate(options):
            row = idx // columns
            col = idx % columns
            button_x = EMOTION_MODAL_RECT.left + inner_pad + col * (button_width + button_gap)
            button_y = button_area_top + row * (button_height + button_gap)
            button_rect = pygame.Rect(button_x, button_y, button_width, button_height)
            pygame.draw.rect(tft_surf, SWEET_PURPLE, button_rect, border_radius=10)
            pygame.draw.rect(tft_surf, VIOLET, button_rect, width=2, border_radius=10)

            label_font = fit_emotion_label_font(emotion, button_rect.width - 12)
            label = label_font.render(emotion, True, BLACK)
            label_rect = label.get_rect(center=button_rect.center)
            tft_surf.blit(label, label_rect)
            EMOTION_BUTTON_RECTS.append({"emotion": emotion, "rect": button_rect})

        custom_y = action_y - custom_row_height - 8
        custom_width = int((action_width - 3 * button_gap) / 4)
        custom_labels = [
            EMOTION_CUSTOM_SLOTS[0] if len(EMOTION_CUSTOM_SLOTS) > 0 else "",
            EMOTION_CUSTOM_SLOTS[1] if len(EMOTION_CUSTOM_SLOTS) > 1 else "",
            EMOTION_CUSTOM_SLOTS[2] if len(EMOTION_CUSTOM_SLOTS) > 2 else "",
            EMOTION_CUSTOM_TRIGGER_LABEL,
        ]

        for idx, label in enumerate(custom_labels):
            custom_x = EMOTION_MODAL_RECT.left + inner_pad + idx * (custom_width + button_gap)
            custom_rect = pygame.Rect(custom_x, custom_y, custom_width, custom_row_height)

            # Custom emotion slots use purple like the main emotion buttons.
            if idx < 3:
                if label:
                    fill_color = SWEET_PURPLE
                    border_color = VIOLET
                    text_color = BLACK
                else:
                    fill_color = (240, 240, 240)
                    border_color = DARK_GRAY
                    text_color = DARK_GRAY
            else:
                fill_color = (236, 236, 236)
                border_color = DARK_GRAY
                text_color = BLACK

            pygame.draw.rect(tft_surf, fill_color, custom_rect, border_radius=8)
            pygame.draw.rect(tft_surf, border_color, custom_rect, width=2, border_radius=8)
            display_label = label if label else ""
            custom_font = fit_emotion_label_font(display_label, custom_rect.width - 10)
            custom_text = custom_font.render(display_label, True, text_color)
            tft_surf.blit(custom_text, custom_text.get_rect(center=custom_rect.center))

            if idx < 3:
                if label:
                    EMOTION_CUSTOM_BUTTON_RECTS.append(
                        {"type": "slot", "emotion": label, "rect": custom_rect}
                    )
            else:
                EMOTION_CUSTOM_BUTTON_RECTS.append(
                    {"type": "trigger", "rect": custom_rect}
                )

        show_rect = pygame.Rect(EMOTION_MODAL_RECT.left + inner_pad, action_y, action_width, action_height)
        pygame.draw.rect(tft_surf, GREEN, show_rect, border_radius=10)
        pygame.draw.rect(tft_surf, DARK_GRAY, show_rect, width=2, border_radius=10)

        show_text = FONT_SMALL_BOLD.render("Show results", True, BLACK)
        tft_surf.blit(show_text, show_text.get_rect(center=show_rect.center))

        EMOTION_ACTION_RECTS = {"close": close_rect, "show_results": show_rect}

    if EMOTION_RESULTS_VISIBLE:
        draw_results_overlay()


def handle_emotion_popup_click(mx, my):
    global EMOTION_RESULTS_VISIBLE, EMOTION_KEYBOARD_VISIBLE, EMOTION_KEYBOARD_TEXT

    if EMOTION_CONFIRMATION_VISIBLE:
        dismiss_emotion_confirmation("tap")
        return True

    if not EMOTION_PROMPT_VISIBLE:
        return False

    touch_emotion_prompt_activity()

    if EMOTION_RESULTS_VISIBLE:
        EMOTION_RESULTS_VISIBLE = False
        return True

    close_rect = EMOTION_ACTION_RECTS.get("close")
    if close_rect and close_rect.collidepoint((mx, my)):
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


def _apply_departure_delay(departure_time, delay_minutes):
    try:
        parts = departure_time.split(":")
        if len(parts) != 2:
            return departure_time

        hours = int(parts[0])
        minutes = int(parts[1]) + int(delay_minutes)

        while minutes >= 60:
            hours += 1
            minutes -= 60
        while minutes < 0:
            hours -= 1
            minutes += 60

        hours %= 24
        return f"{hours:02d}:{minutes:02d}"
    except (TypeError, ValueError, IndexError):
        return departure_time


def _delay_to_departure_text_color(delay_minutes):
    try:
        delay_minutes = max(0, int(delay_minutes))
    except (TypeError, ValueError):
        delay_minutes = 0

    if delay_minutes <= 0:
        return ORANGE

    # Fade from orange to red as the delay grows, with 8 minutes mapping to full red.
    ratio = min(delay_minutes, 8) / 8.0
    return (
        int(round(ORANGE[0] + (RED[0] - ORANGE[0]) * ratio)),
        int(round(ORANGE[1] + (RED[1] - ORANGE[1]) * ratio)),
        int(round(ORANGE[2] + (RED[2] - ORANGE[2]) * ratio)),
    )


def draw_time_layer():
    timestamp = time.time()

    date_day_string = convert_timestamp(timestamp, theme["DATE_FORMAT"]["DATE"])
    date_time_string = convert_timestamp(timestamp, theme["DATE_FORMAT"]["TIME"])

    logger.debug(f"Day: {date_day_string}")
    logger.debug(f"Time: {date_time_string}")

    DrawString(time_surf, date_day_string, DATE_FONT, MAIN_FONT, 0).center(1, 0)
    DrawString(time_surf, date_time_string, CLOCK_FONT, MAIN_FONT, 15).center(1, 0)


def draw_moon_layer(surf, y, size):
    # based on @miyaichi's fork -> great idea :)
    _size = 1000
    dt = datetime.datetime.fromtimestamp(WEATHER_JSON_DATA["daily"]["data"][0]["ts"])
    moon_age = (
        ((dt.year - 11) % 19) * 11 + [0, 2, 0, 2, 2, 4, 5, 6, 7, 8, 9, 10][dt.month - 1] + dt.day
    ) % 30

    image = Image.new("RGBA", (_size + 2, _size + 2))
    draw = ImageDraw.Draw(image)

    radius = int(_size / 2)

    # draw full moon
    draw.ellipse([(1, 1), (_size, _size)], fill=WHITE)

    # draw dark side of the moon
    theta = moon_age / 14.765 * math.pi
    sum_x = sum_length = 0

    for _y in range(-radius, radius, 1):
        alpha = math.acos(_y / radius)
        x = radius * math.sin(alpha)
        length = radius * math.cos(theta) * math.sin(alpha)

        if moon_age < 15:
            start = (radius - x, radius + _y)
            end = (radius + length, radius + _y)
        else:
            start = (radius - length, radius + _y)
            end = (radius + x, radius + _y)

        draw.line((start, end), fill=DARK_GRAY)

        sum_x += 2 * x
        sum_length += end[0] - start[0]

    logger.debug(
        f"moon phase age: {moon_age} percentage: {round(100 - (sum_length / sum_x) * 100, 1)}"
    )

    image = image.resize((size, size))
    image = pygame.image.fromstring(image.tobytes(), image.size, image.mode)

    x = (SURFACE_WIDTH / 2) - (size / 2)

    surf.blit(image, (x, y))


def draw_wind_layer(surf, angle, y):
    # center the wind direction icon and circle on surface
    DrawImage(surf, images["circle"], y, size=20, fillcolor=WHITE).draw_middle_position_icon()
    DrawImage(
        surf, images["arrow"], y, size=20, fillcolor=RED, angle=-angle
    ).draw_middle_position_icon()

    logger.debug(f"wind direction: {angle}")


def draw_statusbar():
    global CONNECTION, READING, UPDATING

    if CONNECTION:
        DrawImage(dynamic_surf, images["wifi"], 5, size=15, fillcolor=BLUE).left()
        if pygame.time.get_ticks() >= CONNECTION:
            CONNECTION = None

    if UPDATING:
        DrawImage(dynamic_surf, images["refresh"], 5, size=15, fillcolor=BLUE).right(8)
        if pygame.time.get_ticks() >= UPDATING:
            UPDATING = None

    if READING:
        DrawImage(dynamic_surf, images["path"], 5, size=15, fillcolor=BLUE).right(-5)
        if pygame.time.get_ticks() >= READING:
            READING = None
def draw_fps():
    DrawString(dynamic_surf, str(int(clock.get_fps())), FONT_SMALL_BOLD, RED, 20).left()


# TODO: make this useful for touch events
def draw_event(color=RED):

    pos = pygame.mouse.get_pos()

    size = 20
    radius = int(size / 2)
    new_pos = (
        int(pos[0] - FIT_SCREEN[0] - (radius * ZOOM)),
        int(pos[1] - FIT_SCREEN[1] - (radius * ZOOM)),
    )
    DrawImage(mouse_surf, images["circle"], size=size, fillcolor=color).draw_absolut_position(
        new_pos
    )


def create_scaled_surf(surf, aa=False):
    if aa:
        scaled_surf = pygame.transform.smoothscale(surf, (SURFACE_WIDTH, SURFACE_HEIGHT))
    else:
        scaled_surf = pygame.transform.scale(surf, (SURFACE_WIDTH, SURFACE_HEIGHT))

    return scaled_surf


def loop():
    # Start the new scheduler
    scheduler.start_weather_updates()
    scheduler.start_bvg_updates()

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
        global DISPLAY_BLANK

        activate_pending_emotion_prompt()
        if EMOTION_CONFIRMATION_VISIBLE and time.time() - EMOTION_CONFIRMATION_OPENED_AT > EMOTION_CONFIRMATION_SECONDS:
            dismiss_emotion_confirmation("timeout")
        if DISPLAY_BLANK and EMOTION_PROMPT_VISIBLE:
            dismiss_emotion_prompt("display-blank")
        elif EMOTION_PROMPT_VISIBLE:
            if not EMOTION_KEYBOARD_VISIBLE and time.time() - EMOTION_LAST_ACTIVITY_TS > DISPLAY_BLANK_AFTER:
                dismiss_emotion_prompt("timeout")

        if not DISPLAY_BLANK:

            tft_surf.fill(BACKGROUND)

            # fill the actual main surface
            display_surf.fill(BACKGROUND)

            # blit the image/weather
            display_surf.blit(weather_surf, (0, 0))
            # blit BVG layer on top
            display_surf.blit(bvg_surf, (0, 0))

            # pygame.draw.line(tft_surf, ORANGE, (0, 299), (240, 299), 1) # Doesn't scale well

            # fill the dynamic layer, make it transparent and use draw functions
            #  that write to that surface; then also blit it on top
            dynamic_surf.fill(BACKGROUND)
            dynamic_surf.set_colorkey(BACKGROUND)

            draw_statusbar()

            if SHOW_FPS:
                draw_fps()

            if ANIMATION:
                my_particles.move(dynamic_surf, my_particles_list)

            # finally take the dynamic surface and blit it to the main surface
            display_surf.blit(dynamic_surf, (0, 0))

            # now do the same for the time layer so it did not interfere with the other layers
            # fill the layer and make it transparent as well
            time_surf.fill(BACKGROUND)
            time_surf.set_colorkey(BACKGROUND)

            # draw the time to the main layer
            draw_time_layer()
            display_surf.blit(time_surf, (0, 0))

            # # draw the mouse events
            # mouse_surf.fill(BACKGROUND)
            # mouse_surf.set_colorkey(BACKGROUND)
            # draw_event(WHITE)

            # display_surf.blit(mouse_surf, (0, 0))

            # finally take the main surface and blit it to the tft surface
            tft_surf.blit(create_scaled_surf(display_surf, aa=AA), FIT_SCREEN)

            draw_emotion_prompt_overlay()
            draw_emotion_confirmation_overlay()

            # update the display with all surfaces merged into the main one
            pygame.display.update()

        elif datetime.datetime.today().weekday() == CLEANING_DAY:
            tft_surf.fill(BLACK)

            msg1 = CLEANING_FONT.render("IT'S", True, WHITE)
            rect1 = msg1.get_rect(center=(DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2 - 135))
            tft_surf.blit(msg1, rect1)

            msg2 = CLEANING_FONT.render("CLEANING", True, WHITE)
            rect2 = msg2.get_rect(center=(DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2 - 45))
            tft_surf.blit(msg2, rect2)

            msg3 = CLEANING_FONT.render("DAY,", True, WHITE)
            rect3 = msg3.get_rect(center=(DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2 + 45))
            tft_surf.blit(msg3, rect3)

            msg4 = CLEANING_FONT.render("YAY!", True, WHITE)
            rect4 = msg4.get_rect(center=(DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2 + 135))
            tft_surf.blit(msg4, rect4)

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
                mx, my = pygame.mouse.get_pos()
                logger.info(f"Screen pressed at: ({mx}, {my})")
                global LAST_TOUCH_TIME
                LAST_TOUCH_TIME = time.time()

                if handle_emotion_popup_click(mx, my):
                    continue

                # Emergrency Exit logic
                # Check if click is in top-left corner (50x50 pixels)
                if mx < 50 and my < 50:
                    exit_clicks += 1
                    logger.info(f"Emergency exit click: {exit_clicks}/5")
                    if exit_clicks >= 5:
                        logger.info("Emergency exit triggered!")
                        running = False
                        quit_all()
                else:
                    exit_clicks = 0 # Reset if they click elsewhere
                # ----------------------------

                if DISPLAY_BLANK:
                    logger.info("Going from idle to active.")
                    wake_display("touch", reason="screen_touch")

                # Maybe need to use "stats": "calls_count": "28", "calls_remaining": 27,
                #  answer from API here to decide whether to do new weather
                #  call right away (because there is only 50 calls in a day...)
                # (BVG is no problem, free 100 calls per minute :))

                if pygame.MOUSEBUTTONDOWN:
                    draw_event()

            elif event.type == pygame.KEYDOWN:

                if handle_emotion_keyboard_keydown(event):
                    continue

                if event.key == pygame.K_ESCAPE:
                    running = False
                    quit_all()

                elif event.key == pygame.K_SPACE:
                    shot_time = convert_timestamp(time.time(), "%Y-%m-%d %H-%M-%S")
                    pygame.image.save(display_surf, f"screenshot-{shot_time}.png")
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
        clock.tick(FPS)

    quit_all()


if __name__ == "__main__":

    try:

        if ANIMATION:
            my_particles = Particles()
            my_particles_list = my_particles.create_particle_list()

        images = image_factory(ICON_PATH)

        loop()

    except KeyboardInterrupt:

        quit_all()
