import datetime
import json
import os
import shutil
import threading
import uuid

STORE_FILE = "emotions.json"
_STORE_LOCK = threading.Lock()


def _store_path(log_dir):
    return os.path.join(log_dir, STORE_FILE)


def _default_payload():
    return {"version": 1, "events": []}


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
    if "events" not in payload or not isinstance(payload["events"], list):
        payload["events"] = []
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


def append_emotion_event(log_dir, emotion=None, skipped=False, source="unknown", prompt_id=None):
    os.makedirs(log_dir, exist_ok=True)
    file_path = _store_path(log_dir)

    with _STORE_LOCK:
        try:
            payload = _safe_read_payload(file_path)
        except (json.JSONDecodeError, OSError):
            if os.path.exists(file_path):
                _recover_if_corrupt(file_path)
            payload = _default_payload()

        event = {
            "emotion": emotion,
            "prompt_id": prompt_id or str(uuid.uuid4()),
            "skipped": bool(skipped),
            "source": source,
            "ts_iso": _now_iso(),
        }
        payload["events"].append(event)
        _safe_write_payload(file_path, payload)

    return event


def read_emotion_events(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    file_path = _store_path(log_dir)

    with _STORE_LOCK:
        try:
            payload = _safe_read_payload(file_path)
        except (json.JSONDecodeError, OSError):
            if os.path.exists(file_path):
                _recover_if_corrupt(file_path)
            payload = _default_payload()
            _safe_write_payload(file_path, payload)

    return payload["events"]


def _parse_iso(value):
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _window_start(now, window):
    if window == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "30d":
        return now - datetime.timedelta(days=30)
    if window == "alltime":
        return datetime.datetime.min.replace(tzinfo=now.tzinfo)
    return now - datetime.timedelta(days=7)


def build_bar_series(log_dir, emotions, window="7d"):
    now = datetime.datetime.now().astimezone()

    events = read_emotion_events(log_dir)
    filtered = []
    for event in events:
        event_dt = _parse_iso(event.get("ts_iso"))
        if event_dt is None:
            continue
        if event_dt > now:
            continue
        if window in {"weekday", "hour", "emotion"} or event_dt >= _window_start(now, window):
            filtered.append((event_dt, event))

    if window == "today":
        labels = [f"{hour:02d}:00" for hour in range(24)]
        key_fn = lambda dt: dt.strftime("%H:00")
    elif window == "hour":
        labels = [f"{hour:02d}:00" for hour in range(24)]
        key_fn = lambda dt: dt.strftime("%H:00")
    elif window == "weekday":
        labels = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        key_fn = lambda dt: labels[dt.weekday()]
    elif window == "alltime":
        # For all time, generate labels based on data range
        if filtered:
            earliest = min(dt for dt, _ in filtered)
            latest = max(dt for dt, _ in filtered)
            current = earliest.replace(hour=0, minute=0, second=0, microsecond=0)
            labels = []
            while current <= latest:
                labels.append(current.strftime("%Y-%m-%d"))
                current += datetime.timedelta(days=1)
        else:
            labels = []
        key_fn = lambda dt: dt.strftime("%Y-%m-%d")
    else:
        days = 30 if window == "30d" else 7
        labels = [
            (now - datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in reversed(range(days))
        ]
        key_fn = lambda dt: dt.strftime("%Y-%m-%d")

    base_emotions = [emotion for emotion in emotions if emotion]
    extra_counts = {}
    for _, event in filtered:
        if event.get("skipped"):
            continue
        emotion = event.get("emotion")
        if not emotion or emotion in base_emotions:
            continue
        extra_counts[emotion] = extra_counts.get(emotion, 0) + 1

    extra_emotions = sorted(extra_counts.keys(), key=lambda item: (-extra_counts[item], item))
    ordered_emotions = [*base_emotions, *extra_emotions]

    series = {emotion: [0] * len(labels) for emotion in ordered_emotions}
    label_to_index = {label: idx for idx, label in enumerate(labels)}
    event_times = {emotion: {label: [] for label in labels} for emotion in ordered_emotions}

    for event_dt, event in filtered:
        if event.get("skipped"):
            continue
        emotion = event.get("emotion")
        if emotion not in series:
            continue
        label = key_fn(event_dt)
        idx = label_to_index.get(label)
        if idx is None:
            continue
        series[emotion][idx] += 1
        event_times[emotion][label].append(event_dt.astimezone().strftime("%Y-%m-%d %H:%M"))

    total = sum(sum(values) for values in series.values())
    return {
        "labels": labels,
        "series": series,
        "event_times": event_times,
        "total": total,
        "window": window,
    }


def get_recent_events(log_dir, limit=150):
    events = read_emotion_events(log_dir)
    sorted_events = sorted(events, key=lambda item: item.get("ts_iso", ""), reverse=True)
    return sorted_events[:limit]
