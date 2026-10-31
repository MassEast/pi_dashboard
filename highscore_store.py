"""Every finished round of the party games (party_games.py) and MERZ, one
small JSON file in logs/: score, timestamp and an optional name, so the
Bestenliste shows everyone (also several rounds of the same person) and a
later statistic can show how people get better over the year. Same tmp-file
+ os.replace write and corrupt-file quarantine as quiz_store.py; one write
per finished round, one more if someone adds their name."""

import datetime
import json
import os
import shutil
import threading
import uuid

STORE_FILE = "game_highscores.json"
_STORE_LOCK = threading.Lock()


def _store_path(log_dir, store_file):
    return os.path.join(log_dir, store_file)


def _read_payload(file_path):
    if not os.path.exists(file_path):
        return {"version": 2, "games": {}}
    try:
        with open(file_path, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except json.JSONDecodeError:
        shutil.move(file_path, f"{file_path}.corrupt-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}")
        return {"version": 2, "games": {}}
    payload["version"] = 2  # v1 kept only a top 5; its entries are valid v2 entries without "id"
    return payload


def _write_payload(file_path, payload):
    tmp_path = f"{file_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as file_handle:
        # no indent: only then json uses its C encoder (4x faster). Every round is
        # kept, so the file only grows, and this runs on the UI thread at each game over.
        json.dump(payload, file_handle, ensure_ascii=False)
    os.replace(tmp_path, file_path)


def read_highscores(log_dir, store_file=STORE_FILE):
    """game name -> list of {id, name (None = no name given), score, ts_iso}, best first."""
    with _STORE_LOCK:
        return _read_payload(_store_path(log_dir, store_file))["games"]


def better(score, other, lower_is_better=False):
    return score < other if lower_is_better else score > other


def submit_result(log_dir, game, score, lower_is_better=False, extra=None, store_file=STORE_FILE):
    """Stores one finished round without a name (after equal scores: the older
    one keeps its place). Returns (all games' lists, 0-based place, entry id).
    lower_is_better for times (MERZ: seconds to win), extra = additional
    entry fields (MERZ: {"burn": True})."""
    os.makedirs(log_dir, exist_ok=True)
    file_path = _store_path(log_dir, store_file)
    entry = {"id": uuid.uuid4().hex[:12], "name": None, "score": score,
             "ts_iso": datetime.datetime.now().astimezone().isoformat()}
    entry.update(extra or {})
    with _STORE_LOCK:
        payload = _read_payload(file_path)
        entries = payload["games"].setdefault(game, [])
        place = next((i for i, e in enumerate(entries) if better(score, e["score"], lower_is_better)), len(entries))
        entries.insert(place, entry)
        _write_payload(file_path, payload)
    return payload["games"], place, entry["id"]


def set_name(log_dir, game, entry_id, name, store_file=STORE_FILE):
    """Adds the (optional) name to an already stored round. Returns all games' lists."""
    file_path = _store_path(log_dir, store_file)
    with _STORE_LOCK:
        payload = _read_payload(file_path)
        entry = next(e for e in payload["games"][game] if e.get("id") == entry_id)
        entry["name"] = name
        _write_payload(file_path, payload)
    return payload["games"]
