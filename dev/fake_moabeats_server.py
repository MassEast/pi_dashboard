#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Local fake of the MoaBeats display API, for trying the cleaning-day chore
checklist screen without touching the real MoaBeats data:

- GET   /api/display/status
- PATCH /api/display/chores/{id}/checklist   body {"item": str, "done": bool}
        -> 200 {"id", "checklist"}, or 400 if the item doesn't exist

Accepts any Bearer token (no real secret needed). Used by
dev/test_moabeats_checklist.py, and standalone for a local look:
venv/bin/python3 dev/fake_moabeats_server.py [port]   (default 8765)
then point config.json["MOABEATS"]["API_URL"] at http://127.0.0.1:<port>.
"""

import copy
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SAMPLE_STATUS = {
    "overdue_chores": [],
    "shopping": [],
    "visits": [],
    "cleaning_chores": [
        {
            "id": 7,
            "name": "Bad",
            "full_name": "Badezimmer putzen",
            "assigned_to": "Ju",
            "checklist": [
                {"item": "Waschbecken", "done": True},
                {"item": "Toilette", "done": False},
                {"item": "Spiegel und Fliesen über dem Waschbecken abwischen, auch hinter der Armatur", "done": False},
            ],
        },
        {
            "id": 9,
            "name": "Küche",
            "full_name": "Küche komplett",
            "assigned_to": "Kim",
            "checklist": [
                {"item": "Kühlschrank ausräumen, alle Fächer und die Türdichtung feucht auswischen, abgelaufenes wegwerfen", "done": False},
                {"item": "Herd und Backofen", "done": False},
                {"item": "Arbeitsflächen", "done": True},
                {"item": "Spüle entkalken", "done": False},
                {"item": "Boden wischen", "done": False},
            ],
        },
        {"id": 8, "name": "Müll", "full_name": "Müll rausbringen", "assigned_to": "Alex", "checklist": []},
    ],
}

# Mutable server state - tests tweak it directly.
STATE = {
    "status": copy.deepcopy(SAMPLE_STATUS),
    "gets": 0,
    "patches": [],
    "patch_mode": "ok",  # "ok" | "400" (force a 400 on every PATCH)
}


class FakeMoaBeats(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if __name__ == "__main__":
            print(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else ''}", flush=True)

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        assert self.headers["Authorization"].startswith("Bearer "), self.headers["Authorization"]
        if self.path != "/api/display/status":
            self._send(404, {"detail": "not found"})
            return
        STATE["gets"] += 1
        self._send(200, STATE["status"])

    def do_PATCH(self):
        assert self.headers["Authorization"].startswith("Bearer "), self.headers["Authorization"]
        chore_id = int(self.path.split("/")[4])
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        STATE["patches"].append((chore_id, body, self.headers["Authorization"]))
        chore = next((c for c in STATE["status"]["cleaning_chores"] if c["id"] == chore_id), None)
        entry = None
        if chore is not None:
            entry = next((e for e in chore["checklist"] if e["item"] == body["item"]), None)
        if STATE["patch_mode"] == "400" or entry is None:
            self._send(400, {"detail": "item not found or chore completed"})
            return
        entry["done"] = body["done"]
        self._send(200, {"id": chore_id, "checklist": copy.deepcopy(chore["checklist"])})


def start(port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), FakeMoaBeats)
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = start(port)
    print(f"Fake MoaBeats on http://127.0.0.1:{server.server_port} - Ctrl+C to stop", flush=True)
    server.serve_forever()
