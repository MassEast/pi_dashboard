#!/bin/bash
# Starts PiDashboard.py and restarts it after a crash (non-zero exit code).
# The 5-tap emergency exit and ESC end with exit code 0: then it stays closed
# on purpose. More than 5 crashes within 10 minutes: give up instead of
# looping (something's really broken - check ~/.cache/lxsession/LXDE-pi/run.log).
# Started by pidashboard.desktop (XDG autostart).

cd "$(dirname "$0")"
crashes=()
while true; do
    ./venv/bin/python3 PiDashboard.py
    code=$?
    if [ "$code" -eq 0 ]; then
        echo "PiDashboard exited normally (emergency exit / ESC) - not restarting"
        exit 0
    fi
    now=$(date +%s)
    recent=()
    for t in "${crashes[@]}"; do
        [ $((now - t)) -lt 600 ] && recent+=("$t")
    done
    crashes=("${recent[@]}" "$now")
    echo "$(date '+%F %T') PiDashboard crashed (exit code $code), crash ${#crashes[@]} in 10 min"
    if [ "${#crashes[@]}" -gt 5 ]; then
        echo "Too many crashes - giving up"
        exit "$code"
    fi
    sleep 3
done
