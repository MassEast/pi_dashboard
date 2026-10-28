"""All-time top-N highscores per party game (party_games.py), one small JSON
file in logs/. Same tmp-file + os.replace write and corrupt-file quarantine
as quiz_store.py. Only written when someone actually gets into a top list,
so SD card writes stay rare."""

import datetime
import json
import os
import shutil
import threading

STORE_FILE = "game_highscores.json"
TOP_N = 5
_STORE_LOCK = threading.Lock()


def _store_path(log_dir, store_file):
    return os.path.join(log_dir, store_file)


def _read_payload(file_path):
    if not os.path.exists(file_path):
        return {"version": 1, "games": {}}
    try:
        with open(file_path, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except json.JSONDecodeError:
        shutil.move(file_path, f"{file_path}.corrupt-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}")
        return {"version": 1, "games": {}}
    return payload


def read_highscores(log_dir, store_file=STORE_FILE):
    """game name -> list of {name, score, ts_iso}, best first."""
    with _STORE_LOCK:
        return _read_payload(_store_path(log_dir, store_file))["games"]


def submit_highscore(log_dir, game, name, score, store_file=STORE_FILE):
    """Inserts the entry (after equal scores: the older one keeps its place),
    cuts the list to TOP_N, returns (all games' lists, 0-based place or None
    if it didn't make it)."""
    os.makedirs(log_dir, exist_ok=True)
    file_path = _store_path(log_dir, store_file)
    entry = {"name": name, "score": score, "ts_iso": datetime.datetime.now().astimezone().isoformat()}
    with _STORE_LOCK:
        payload = _read_payload(file_path)
        entries = payload["games"].setdefault(game, [])
        place = next((i for i, e in enumerate(entries) if score > e["score"]), len(entries))
        entries.insert(place, entry)
        del entries[TOP_N:]
        tmp_path = f"{file_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, indent=2, ensure_ascii=False)
        os.replace(tmp_path, file_path)
    return payload["games"], (place if place < TOP_N else None)
