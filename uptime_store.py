import datetime
import json
import os
import shutil
import threading


STORE_FILE = "uptime.json"
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


def append_uptime_event(log_dir, event, source="unknown", reason=None, details=None):
    os.makedirs(log_dir, exist_ok=True)
    file_path = _store_path(log_dir)

    with _STORE_LOCK:
        try:
            payload = _safe_read_payload(file_path)
        except (json.JSONDecodeError, OSError):
            if os.path.exists(file_path):
                _recover_if_corrupt(file_path)
            payload = _default_payload()

        entry = {
            "event": event,
            "source": source,
            "ts_iso": _now_iso(),
        }
        if reason is not None:
            entry["reason"] = reason
        if details is not None:
            entry["details"] = details

        payload["events"].append(entry)
        _safe_write_payload(file_path, payload)

    return entry


def read_uptime_events(log_dir):
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


def _window_to_timedelta(window):
    if window == "24h":
        return datetime.timedelta(hours=24)
    if window == "7d":
        return datetime.timedelta(days=7)
    return datetime.timedelta(hours=24)


def _channel_summary(events, start, now, up_event, down_event, default_up=True):
    relevant_events = []
    for event in events:
        event_name = event.get("event")
        if event_name not in {up_event, down_event}:
            continue
        event_dt = _parse_iso(event.get("ts_iso"))
        if event_dt is None or event_dt > now:
            continue
        relevant_events.append((event_dt, event_name))

    relevant_events.sort(key=lambda item: item[0])

    state_is_up = default_up
    last_transition = start
    up_duration = datetime.timedelta(0)
    down_count = 0
    up_count = 0

    for event_dt, event_name in relevant_events:
        if event_dt < start:
            state_is_up = event_name == up_event
            continue

        if state_is_up:
            up_duration += event_dt - last_transition

        last_transition = event_dt

        if event_name == up_event:
            state_is_up = True
            up_count += 1
        else:
            state_is_up = False
            down_count += 1

    if state_is_up:
        up_duration += now - last_transition

    total_window = max((now - start).total_seconds(), 1.0)
    up_seconds = max(up_duration.total_seconds(), 0.0)
    uptime_pct = min(max((up_seconds / total_window) * 100.0, 0.0), 100.0)

    return {
        "uptime_seconds": round(up_seconds, 2),
        "uptime_pct": round(uptime_pct, 2),
        "up_events": up_count,
        "down_events": down_count,
    }


def build_uptime_summary(log_dir, windows=("24h", "7d")):
    now = datetime.datetime.now().astimezone()
    events = read_uptime_events(log_dir)

    windows_payload = {}
    for window in windows:
        window_delta = _window_to_timedelta(window)
        start = now - window_delta
        screen = _channel_summary(events, start, now, "screen_on", "screen_off", default_up=False)
        bvg = _channel_summary(events, start, now, "bvg_up", "bvg_down", default_up=True)
        weather = _channel_summary(events, start, now, "weather_up", "weather_down", default_up=True)
        internet = _channel_summary(events, start, now, "internet_up", "internet_down", default_up=True)

        days = max(window_delta.total_seconds() / 86400.0, 1.0)
        screen_active_hours = screen["uptime_seconds"] / 3600.0

        reboot_events = 0
        boot_events = 0
        failure_counts = {"internet": 0, "bvg": 0, "weather": 0}
        for event in events:
            event_dt = _parse_iso(event.get("ts_iso"))
            if event_dt is None or event_dt < start or event_dt > now:
                continue
            event_name = event.get("event")
            if event_name == "reboot_requested":
                reboot_events += 1
            elif event_name == "boot_started":
                boot_events += 1
            elif event_name == "internet_down":
                failure_counts["internet"] += 1
            elif event_name == "bvg_down":
                failure_counts["bvg"] += 1
            elif event_name == "weather_down":
                failure_counts["weather"] += 1

        windows_payload[window] = {
            "window": window,
            "screen": screen,
            "screen_active_hours": round(screen_active_hours, 2),
            "screen_avg_hours_per_day": round(screen_active_hours / days, 2),
            "bvg": bvg,
            "weather": weather,
            "internet": internet,
            "reboot_count": reboot_events,
            "boot_count": boot_events,
            "failure_counts": failure_counts,
        }

    return {
        "version": 1,
        "generated_at": now.isoformat(),
        "windows": windows_payload,
    }
