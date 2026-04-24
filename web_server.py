import datetime
import json
import logging
import os
import socket

from flask import Flask, jsonify, request, send_from_directory

from emotion_store import build_bar_series, get_recent_events
from uptime_store import build_uptime_summary

PATH = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PATH, "config.json")
WEB_PATH = os.path.join(PATH, "web")

with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
    config = json.load(config_file)

if config.get("ENV") == "Pi":
    LOG_PATH = "/mnt/ramdisk/"
else:
    LOG_PATH = os.path.join(PATH, "logs")

UPTIME_LOG_PATH = os.path.join(PATH, "logs")
EMOTION_LOG_PATH = os.path.join(PATH, "logs")

os.makedirs(LOG_PATH, exist_ok=True)
os.makedirs(UPTIME_LOG_PATH, exist_ok=True)
os.makedirs(EMOTION_LOG_PATH, exist_ok=True)

handlers = [logging.StreamHandler()]
if config.get("LOG_TO_FILES", False):
    datetimenow = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    handlers.append(logging.FileHandler(os.path.join(LOG_PATH, f"web_server_{datetimenow}.log")))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=handlers,
    force=True,
)
logger = logging.getLogger(__name__)

web_cfg = config.get("WEB", {})

FALLBACK_STYLE = {"emoji": "?", "color": "#9ca3af"}


def _load_runtime_emotion_cfg():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
            runtime_cfg = json.load(config_file)
        return runtime_cfg.get("EMOTION", {})
    except (OSError, json.JSONDecodeError):
        return config.get("EMOTION", {})


def _build_emotion_catalog(emotion_cfg):
    catalog = emotion_cfg.get("CATALOG", [])
    if not isinstance(catalog, list):
        catalog = []

    normalized = []
    seen = set()
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip().lower()
        if not name or name in seen:
            continue
        normalized.append(
            {
                "name": name,
                "emoji": entry.get("emoji") or FALLBACK_STYLE["emoji"],
                "color": entry.get("color") or FALLBACK_STYLE["color"],
            }
        )
        seen.add(name)

    if normalized:
        return normalized

    emotions = emotion_cfg.get(
        "EMOTIONS",
        ["stressed", "wild", "relaxed", "sad", "angry", "happy", "anxious", "tired"],
    )
    return [
        {
            "name": str(name).strip().lower(),
            "emoji": FALLBACK_STYLE["emoji"],
            "color": FALLBACK_STYLE["color"],
        }
        for name in emotions
        if str(name).strip()
    ]


HOST = web_cfg.get("HOST", "0.0.0.0")
PORT = int(web_cfg.get("PORT", 8080))

app = Flask(__name__, static_folder=WEB_PATH, static_url_path="")


@app.route("/")
def index():
    return send_from_directory(WEB_PATH, "index.html")


@app.route("/app.js")
def app_js():
    return send_from_directory(WEB_PATH, "app.js")


@app.route("/styles.css")
def styles_css():
    return send_from_directory(WEB_PATH, "styles.css")


@app.route("/api/health")
def health():
    return jsonify({"ok": True})


@app.route("/api/emotions/raw")
def emotions_raw():
    limit = int(request.args.get("limit", 150))
    return jsonify({"events": get_recent_events(EMOTION_LOG_PATH, limit=limit)})


@app.route("/api/emotions/catalog")
def emotions_catalog():
    emotion_cfg = _load_runtime_emotion_cfg()
    return jsonify({"catalog": _build_emotion_catalog(emotion_cfg)})


@app.route("/api/emotions/bars")
def emotions_bars():
    window = request.args.get("window", "7d")
    if window not in {"today", "7d", "30d", "weekday", "hour", "emotion", "alltime"}:
        window = "7d"
    emotion_cfg = _load_runtime_emotion_cfg()
    emotions = [entry["name"] for entry in _build_emotion_catalog(emotion_cfg)]
    return jsonify(build_bar_series(EMOTION_LOG_PATH, emotions=emotions, window=window))


@app.route("/api/uptime")
def uptime():
    return jsonify(build_uptime_summary(UPTIME_LOG_PATH, windows=("24h", "7d")))


def _lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    lan_ip = _lan_ip()
    logger.info(f"Starting web server on {HOST}:{PORT}")
    logger.info(f"Local URL: http://127.0.0.1:{PORT}")
    logger.info(f"LAN URL: http://{lan_ip}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=False)
