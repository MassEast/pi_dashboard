#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Smoke test for the internet-outage aggregation logic in uptime_store.py.

Regression guard for a real bug: safe_network_monitor() in PiDashboard.py resets
NETWORK_AVAILABLE to True on every process restart, so during a prolonged outage
where it keeps self-rebooting (see NETWORK_REBOOT_COOLDOWN_SECONDS), it logs a
fresh internet_down event each time it comes back up and finds the network still
dead - one real outage ends up as many internet_down events in uptime.json.
_channel_summary and build_internet_outage_log must collapse those repeats into
a single outage. Run directly with python3, not part of an automated suite -
this repo has no test runner.
"""

import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uptime_store  # noqa: E402


def _iso(dt):
    return dt.isoformat()


def _build_reboot_loop_events(base):
    """
    One real outage, 3 hours long, where the network monitor re-detects it as
    still-down after each self-reboot - the exact shape seen in the field.
    """
    return [
        {"event": "internet_down", "ts_iso": _iso(base)},
        {"event": "internet_down", "ts_iso": _iso(base + datetime.timedelta(minutes=15))},
        {"event": "internet_down", "ts_iso": _iso(base + datetime.timedelta(hours=2, minutes=5))},
        {"event": "internet_up", "ts_iso": _iso(base + datetime.timedelta(hours=3))},
    ]


def test_channel_summary_collapses_reboot_loop():
    now = datetime.datetime.now().astimezone()
    start = now - datetime.timedelta(hours=24)
    base = start + datetime.timedelta(hours=1)
    events = _build_reboot_loop_events(base)

    summary = uptime_store._channel_summary(
        events, start, now, "internet_up", "internet_down", default_up=True
    )

    assert summary["down_events"] == 1, f"expected 1 collapsed outage, got {summary['down_events']}"
    assert summary["up_events"] == 1, f"expected 1 recovery, got {summary['up_events']}"

    expected_downtime_hours = 3.0
    assert abs(summary["downtime_hours"] - expected_downtime_hours) < 0.01, (
        f"expected ~{expected_downtime_hours}h downtime, got {summary['downtime_hours']}h"
    )
    print("PASS: _channel_summary collapses a reboot-loop into one outage")


def test_channel_summary_counts_genuinely_separate_outages():
    now = datetime.datetime.now().astimezone()
    start = now - datetime.timedelta(hours=24)
    base = start + datetime.timedelta(hours=1)

    events = [
        {"event": "internet_down", "ts_iso": _iso(base)},
        {"event": "internet_up", "ts_iso": _iso(base + datetime.timedelta(minutes=30))},
        {"event": "internet_down", "ts_iso": _iso(base + datetime.timedelta(hours=5))},
        {"event": "internet_up", "ts_iso": _iso(base + datetime.timedelta(hours=5, minutes=10))},
    ]

    summary = uptime_store._channel_summary(
        events, start, now, "internet_up", "internet_down", default_up=True
    )

    assert summary["down_events"] == 2, f"expected 2 separate outages, got {summary['down_events']}"
    assert summary["up_events"] == 2, f"expected 2 recoveries, got {summary['up_events']}"
    print("PASS: _channel_summary still counts genuinely separate outages individually")


def test_build_internet_outage_log_merges_and_reports_full_span():
    with tempfile.TemporaryDirectory() as log_dir:
        now = datetime.datetime.now().astimezone()
        base = now - datetime.timedelta(hours=20)
        events = _build_reboot_loop_events(base)
        uptime_store._safe_write_payload(
            uptime_store._store_path(log_dir), {"version": 1, "events": events}
        )

        outages = uptime_store.build_internet_outage_log(log_dir, window="24h")

        assert len(outages) == 1, f"expected 1 merged outage in the drilldown, got {len(outages)}"
        outage = outages[0]
        assert outage["start_iso"] == _iso(base), "outage should start at the first down event, not a later re-detect"
        assert outage["end_iso"] == _iso(base + datetime.timedelta(hours=3))
        assert outage["ongoing"] is False
        assert abs(outage["duration_seconds"] - 3 * 3600) < 1
        print("PASS: build_internet_outage_log reports one outage spanning first-down to eventual recovery")


def test_build_internet_outage_log_marks_ongoing_outage():
    with tempfile.TemporaryDirectory() as log_dir:
        now = datetime.datetime.now().astimezone()
        down_start = now - datetime.timedelta(hours=1)
        events = [{"event": "internet_down", "ts_iso": _iso(down_start)}]
        uptime_store._safe_write_payload(
            uptime_store._store_path(log_dir), {"version": 1, "events": events}
        )

        outages = uptime_store.build_internet_outage_log(log_dir, window="24h")

        assert len(outages) == 1
        assert outages[0]["ongoing"] is True
        assert outages[0]["end_iso"] is None
        print("PASS: build_internet_outage_log marks a still-open outage as ongoing")


def test_window_to_timedelta_has_30d():
    delta = uptime_store._window_to_timedelta("30d")
    assert delta == datetime.timedelta(days=30), f"expected 30 days, got {delta}"
    print("PASS: '30d' window maps to 30 days")


def test_build_uptime_summary_default_windows_include_30d():
    with tempfile.TemporaryDirectory() as log_dir:
        summary = uptime_store.build_uptime_summary(log_dir)
        assert set(summary["windows"].keys()) == {"24h", "7d", "30d"}, summary["windows"].keys()
    print("PASS: build_uptime_summary defaults to 24h/7d/30d windows")


def test_internet_outages_route():
    # web_server.py reads config.json and hits the real logs/ dir at import time, so
    # only run this against the actual Flask app, not a mocked one.
    try:
        import web_server
    except ModuleNotFoundError as exc:
        print(f"SKIP: test_internet_outages_route ({exc}; run inside venv/)")
        return

    client = web_server.app.test_client()

    response = client.get("/api/uptime/internet_outages")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["window"] == "30d", "default window should be 30d"
    assert isinstance(payload["outages"], list)

    response = client.get("/api/uptime/internet_outages?window=bogus")
    assert response.get_json()["window"] == "30d", "invalid window should fall back to 30d, not error"

    response = client.get("/api/uptime/internet_outages?window=24h")
    assert response.get_json()["window"] == "24h"

    response = client.get("/api/uptime")
    windows = response.get_json()["windows"]
    assert set(windows.keys()) == {"24h", "7d", "30d"}, "the main /api/uptime route must also expose 30d"
    print("PASS: /api/uptime/internet_outages route validates window param and /api/uptime exposes 30d")


if __name__ == "__main__":
    tests = [
        test_channel_summary_collapses_reboot_loop,
        test_channel_summary_counts_genuinely_separate_outages,
        test_build_internet_outage_log_merges_and_reports_full_span,
        test_build_internet_outage_log_marks_ongoing_outage,
        test_window_to_timedelta_has_30d,
        test_build_uptime_summary_default_windows_include_30d,
        test_internet_outages_route,
    ]

    failures = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL: {test.__name__}: {exc}")

    print()
    if failures:
        print(f"{failures}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"All {len(tests)} tests passed")
