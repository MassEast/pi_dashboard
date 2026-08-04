import datetime
import json
import os
import shutil
import threading
import uuid

STORE_FILE = "quiz_results.json"
_STORE_LOCK = threading.Lock()


def _store_path(log_dir, store_file=STORE_FILE):
    return os.path.join(log_dir, store_file)


def _default_payload():
    return {"version": 1, "results": []}


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat()


def _safe_read_payload(file_path):
    if not os.path.exists(file_path):
        return _default_payload()

    with open(file_path, "r", encoding="utf-8") as file_handle:
        data = file_handle.read().strip()
        if not data:
            return _default_payload()
        payload = json.loads(data)

    if not isinstance(payload, dict):
        return _default_payload()
    if "results" not in payload or not isinstance(payload["results"], list):
        payload["results"] = []
    if "version" not in payload:
        payload["version"] = 1
    return payload


def _safe_write_payload(file_path, payload):
    tmp_path = f"{file_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2, sort_keys=True)
    os.replace(tmp_path, file_path)


def _recover_if_corrupt(file_path):
    backup_path = f"{file_path}.corrupt-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.move(file_path, backup_path)
    return backup_path


def submit_quiz_result(log_dir, name, mausig, atzig, fotzig, store_file=STORE_FILE):
    """Stores one participant's raw per-axis vote counts as a new entry -
    retakes under the same name add another dot (with its own id) rather
    than replacing the previous one, so the results triangle can show each
    person's full spread across repeat takes."""
    os.makedirs(log_dir, exist_ok=True)
    file_path = _store_path(log_dir, store_file)
    normalized_name = " ".join(name.strip().split())

    with _STORE_LOCK:
        try:
            payload = _safe_read_payload(file_path)
        except (json.JSONDecodeError, OSError):
            if os.path.exists(file_path):
                _recover_if_corrupt(file_path)
            payload = _default_payload()

        result = {
            "id": uuid.uuid4().hex,
            "name": normalized_name,
            "mausig": mausig,
            "atzig": atzig,
            "fotzig": fotzig,
            "ts_iso": _now_iso(),
        }
        payload["results"].append(result)
        _safe_write_payload(file_path, payload)

    return result


def read_quiz_results(log_dir, store_file=STORE_FILE):
    os.makedirs(log_dir, exist_ok=True)
    file_path = _store_path(log_dir, store_file)

    with _STORE_LOCK:
        try:
            payload = _safe_read_payload(file_path)
        except (json.JSONDecodeError, OSError):
            if os.path.exists(file_path):
                _recover_if_corrupt(file_path)
            payload = _default_payload()
            _safe_write_payload(file_path, payload)

    return payload["results"]
