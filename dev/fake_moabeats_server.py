#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Local fake of the MoaBeats display API, for trying the cleaning-day chore
checklist screen without touching the real MoaBeats data:

- GET   /api/display/status
- PATCH /api/display/chores/{id}/checklist   body {"item": str, "done": bool}
        -> 200 {"id", "checklist"}, or 400 if the item doesn't exist

- POST  /api/auth/login   body {"name", "password"} -> {"access_token", "user"}
        (password "falsch" -> 401)
- GET   /api/messages?channel=pinnwand&limit=N   (pinnwand.exe)
- POST  /api/messages      body {"text", "channel"}
- GET   /api/users/public + /uploads/avatars/*.png   (TIC-TAC-DADA profile pictures)

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
    "logins": 0,
    "users": [{"id": 1, "name": "Kim", "avatar_url": "/uploads/avatars/kim.png"},
              {"id": 2, "name": "Sam", "avatar_url": "/uploads/avatars/sam.png"},
              {"id": 3, "name": "Robin", "avatar_url": None},
              {"id": 4, "name": "Alex", "avatar_url": "/uploads/avatars/broken.png"}],
    "avatar_png": b"",  # set by tests (a real PNG)
    "posts": [],
    "messages": [
        {"id": 1, "text": "Wer hat die Hafermilch leer gemacht? 😤", "created_at": "2026-10-29T18:02:00", "user": {"id": 2, "name": "Sam"}, "is_system": False},
        {"id": 2, "text": "Erinnerung: Bad putzen ist heute dran!", "created_at": "2026-10-30T07:00:00", "user": {"id": 1, "name": "Kim"}, "is_system": True},
        {"id": 3, "text": "Heute 20 Uhr Spieleabend in der Küche, alle eingeladen!", "created_at": "2026-10-30T16:43:00", "user": {"id": 3, "name": "Robin"}, "is_system": False},
        {"id": 4, "text": "Mo: Euer Flur ist der schönste in ganz Berlin", "created_at": "2026-10-30T21:08:00", "user": {"id": 9, "name": "FlurPi"}, "is_system": False},
        {"id": 5, "text": "🎉🎉", "created_at": "2026-10-30T21:10:00", "user": {"id": 1, "name": "Kim"}, "is_system": False},
    ],
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

    def _body(self):
        return json.loads(self.rfile.read(int(self.headers["Content-Length"])))

    def do_POST(self):
        if self.path == "/api/auth/login":
            body = self._body()
            STATE["logins"] += 1
            if body["password"] == "falsch":
                self._send(401, {"detail": "Falscher Name oder Passwort"})
                return
            self._send(200, {"access_token": "fake-jwt", "token_type": "bearer", "user": {"id": 9, "name": body["name"]}})
            return
        assert self.headers["Authorization"] == "Bearer fake-jwt", self.headers["Authorization"]
        assert self.path == "/api/messages", self.path
        body = self._body()
        STATE["posts"].append(body)
        msg = {"id": max(m["id"] for m in STATE["messages"]) + 1, "text": body["text"], "created_at": "2026-10-31T10:00:00",
               "user": {"id": 9, "name": "FlurPi"}, "is_system": False}
        STATE["messages"].append(msg)
        self._send(201, msg)

    def do_GET(self):
        if self.path == "/api/users/public":  # no auth, like MoaBeats' login screen
            self._send(200, STATE["users"])
            return
        if self.path.startswith("/uploads/avatars/"):
            if self.path.endswith("broken.png"):
                self._send(404, {"detail": "gone"})
                return
            data = STATE["avatar_png"]
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        assert self.headers["Authorization"].startswith("Bearer "), self.headers["Authorization"]
        if self.path.startswith("/api/messages?"):
            assert self.headers["Authorization"] == "Bearer fake-jwt"
            assert "channel=pinnwand" in self.path, self.path
            self._send(200, STATE["messages"][-30:])
            return
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
