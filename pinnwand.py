#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
pinnwand.exe: MoaBeats' "pinnwand" chat channel on the FlurPi, so guests
passing by can read it and write into it. Logs in as one MoaBeats guest
account (config MOABEATS.PINNWAND_USER / PINNWAND_PASSWORD) and uses the same
API as the app: POST /api/auth/login, GET + POST /api/messages. A guest can
add a name; it goes in front of the text ("Oma Erna: ..."). Bot reminders
(is_system) are hidden and emoji dropped (the pixel font has none).

Network calls run in background threads; draw()/tap() run on the pygame
thread. PiDashboard.py opens it as HOME_WINDOW "pinnwand" and draws the
wg.txt preview strip via preview()/unread().
"""

import datetime
import logging
import re
import threading
import time

import pygame
import requests

import kiezos as K

CHANNEL = "pinnwand"
FETCH_LIMIT = 30
TEXT_MAX = 200
NAME_MAX = 20
STATUS_SECONDS = 6
KEY_ROWS = ["1234567890", "qwertzuiopü", "asdfghjklöä", "yxcvbnm,.?!"]
GUEST_FACE = (226, 214, 250)
OTHER_FACE = K.F_TIP
AUTHOR_COLORS = [(150, 30, 110), (40, 90, 170), (30, 120, 60), (170, 90, 20), (120, 40, 170), (20, 110, 120)]

_EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿⬀-⯿︀-️‍⃣]")
_NAMED = re.compile(r"^([^:\n]{1,%d}): (.+)$" % NAME_MAX, re.S)

logger = logging.getLogger()


def strip_author(msg):
    """Author line for wg.txt: guests get "(Gast)", but not "Gast (Gast)"."""
    if msg["guest"] and msg["author"] != "Gast":
        return f"{msg['author']} (Gast)"
    return msg["author"]


def clean(text):
    """Drop emoji, squash the whitespace they leave."""
    return re.sub(r"[ \t]+", " ", _EMOJI.sub("", text)).strip()


def _local(iso):
    """API timestamps are UTC (naive or with offset) -> local naive."""
    ts = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    return ts.astimezone().replace(tzinfo=None)


def when(ts, now):
    days = (now.date() - ts.date()).days
    if days == 0:
        return ts.strftime("%H:%M")
    if days == 1:
        return "gestern " + ts.strftime("%H:%M")
    return ts.strftime("%d.%m.")


class LoginFailed(Exception):
    pass


class Pinnwand:
    def __init__(self, api_url, user, password, poll_seconds=60):
        self.url = api_url.rstrip("/")
        self.user = user
        self.password = password
        self.poll_seconds = poll_seconds
        self.lock = threading.Lock()
        self.token = None
        self.messages = []  # [{"id", "author", "text", "ts", "guest"}], oldest first
        self.seen_id = None  # newest id when pinnwand.exe was last open
        self.loaded = False
        self.error = None
        self.login_failed = False  # wrong password: stop retrying (MoaBeats locks the account)
        self.fetching = False
        self.sending = False
        self.is_open = False
        # UI state (pygame thread)
        self.compose = None  # {"name", "text", "field", "shift"}
        self.scroll = 0  # px scrolled up from the newest message
        self.max_scroll = 0
        self.status = None  # (text, color, until)
        self.rects = {}

    # ------------------------------------------------------------ network

    def _login(self):
        resp = requests.post(self.url + "/api/auth/login", json={"name": self.user, "password": self.password}, timeout=8)
        if resp.status_code in (401, 403, 404, 422, 429):
            self.login_failed = True
            raise LoginFailed(f"login as {self.user} returned HTTP {resp.status_code}")
        resp.raise_for_status()
        self.token = resp.json()["access_token"]

    def _request(self, method, path, **kwargs):
        for attempt in range(2):
            if self.token is None:
                self._login()
            resp = requests.request(method, self.url + path, headers={"Authorization": f"Bearer {self.token}"}, timeout=8, **kwargs)
            if resp.status_code == 401 and attempt == 0:
                self.token = None  # expired: log in again once
                continue
            resp.raise_for_status()
            return resp.json()

    def _parse(self, data):
        out = []
        for m in data:
            if m.get("is_system"):
                continue
            text = clean(m["text"])
            if m.get("has_photo") or m.get("image_url"):
                text = (text + " [Foto]").strip()
            if not text:
                continue
            guest = m["user"]["name"] == self.user
            author = m["user"]["name"]
            if guest:
                named = _NAMED.match(text)
                author, text = (named.group(1).strip(), named.group(2)) if named else ("Gast", text)
            out.append({"id": m["id"], "author": author, "text": text, "ts": _local(m["created_at"]), "guest": guest})
        return out

    def fetch(self):
        """Blocking: latest messages of the channel. Returns True on success."""
        if self.login_failed:
            return False
        try:
            msgs = self._parse(self._request("GET", "/api/messages", params={"channel": CHANNEL, "limit": FETCH_LIMIT}))
        except Exception as e:
            logger.error(f"Pinnwand fetch failed: {e}")
            with self.lock:
                self.error = "Login fehlgeschlagen" if self.login_failed else "Keine Verbindung zu MoaBeats"
            return False
        with self.lock:
            self.messages = msgs
            self.loaded = True
            self.error = None
            if msgs and (self.seen_id is None or self.is_open):
                self.seen_id = msgs[-1]["id"]
        return True

    def refresh(self):
        """Fetch in the background (no-op if one is already running)."""
        with self.lock:
            if self.fetching:
                return
            self.fetching = True

        def run():
            try:
                self.fetch()
            finally:
                self.fetching = False
        threading.Thread(target=run, daemon=True).start()

    def start_polling(self, is_awake):
        """Poll every poll_seconds while the display is awake."""
        def loop():
            while True:
                if is_awake():
                    self.refresh()
                time.sleep(self.poll_seconds)
        threading.Thread(target=loop, daemon=True).start()

    def _send(self, name, text):
        full = f"{name}: {text}" if name else text
        try:
            self._request("POST", "/api/messages", json={"text": full, "channel": CHANNEL})
        except Exception as e:
            logger.error(f"Pinnwand send failed: {e}")
            self.status = ("Senden fehlgeschlagen. Nochmal?", K.F_LATE, time.time() + STATUS_SECONDS)
            self.sending = False
            return
        logger.info(f"Pinnwand: guest message sent ({len(full)} chars)")
        self.fetch()
        self.compose = None
        self.scroll = 0
        self.status = ("Gesendet! Steht jetzt in der WG-App.", K.F_SEL, time.time() + STATUS_SECONDS)
        self.sending = False

    # ------------------------------------------------------------ state

    def unread(self):
        with self.lock:
            if self.seen_id is None:
                return 0
            return sum(1 for m in self.messages if m["id"] > self.seen_id and not m["guest"])

    def preview(self):
        """Newest message for wg.txt, or None."""
        with self.lock:
            return self.messages[-1] if self.messages else None

    def opened(self):
        self.is_open = True
        self.compose = None
        self.scroll = 0
        self.status = None
        with self.lock:
            if self.messages:
                self.seen_id = self.messages[-1]["id"]
        self.refresh()

    def closed(self):
        self.is_open = False
        self.compose = None

    # ------------------------------------------------------------ drawing

    def _author_color(self, name):
        return AUTHOR_COLORS[sum(map(ord, name)) % len(AUTHOR_COLORS)]

    def _bubble_lines(self, msg, width):
        return K.wrap(msg["text"], 17, width - 20, bold=False)

    def draw(self, surf, inner, now):
        """pinnwand.exe's client area (the window frame is PiDashboard's)."""
        rects = {}
        surf.blit(_pin_icon(36), (inner.x + 2, inner.y + 2))
        K.t95(surf, "Pinnwand", 20, (inner.x + 44, inner.y))
        K.t95(surf, "Der Haupt-Chat der WG. Gäste dürfen mitlesen", 14, (inner.x + 44, inner.y + 24), color=K.F_DARK, bold=False)

        area = pygame.Rect(inner.x, inner.y + 48, inner.w - 30, inner.h - 48 - 140)
        self._draw_chat(surf, area, now, rects)

        y = area.bottom + 10
        K.t95(surf, "Du schreibst als Gast. Alle in der WG lesen mit.", 14, (inner.x + 2, y), color=K.F_DARK, bold=False)
        field = pygame.Rect(inner.x, y + 22, inner.w - 128, 52)
        K.textfield(surf, field, "", "Schreib was an die WG...")
        rects["field"] = field
        rects["senden"] = K.button(surf, pygame.Rect(field.right + 8, field.y, 120, 52), "Senden", size=18)

        st = pygame.Rect(inner.x, inner.bottom - 36, inner.w - 130, 34)
        K.bevel(surf, st, sunken=True)
        if self.status and time.time() < self.status[2]:
            text, color = self.status[:2]
        elif self.error:
            text, color = self.error, K.F_LATE
        else:
            text, color = ("Lädt..." if not self.loaded else f"{len(self.messages)} Nachrichten"), K.F_DARK
        K.t95(surf, text, K.fit_size(text, st.w - 14, sizes=(15, 14, 13)), (st.x + 8, st.centery), color=color, bold=False, anchor="midleft")
        rects["back"] = K.button(surf, pygame.Rect(inner.right - 122, inner.bottom - 36, 122, 36), "< Zurück", size=16)

        if self.compose is not None:
            self._draw_compose(surf, rects)
        self.rects = rects

    def _draw_chat(self, surf, area, now, rects):
        K.bevel(surf, area, sunken=True, face=K.F_PAPER)
        with self.lock:
            msgs = list(self.messages)
        bw = area.w - 70
        heights = [26 + 22 * len(self._bubble_lines(m, bw)) + 10 for m in msgs]
        total = sum(heights) + 12 * len(msgs) + 8
        self.max_scroll = max(0, total - area.h)
        self.scroll = max(0, min(self.scroll, self.max_scroll))

        clip = surf.get_clip()
        surf.set_clip(area.inflate(-4, -4))
        if not msgs:
            text = self.error or ("Noch keine Nachrichten." if self.loaded else "Pinnwand lädt...")
            K.t95(surf, text, 17, area.center, color=K.F_LATE if self.error else K.F_DARK, anchor="center")
        y = area.bottom - 8 + self.scroll
        for msg, h in zip(reversed(msgs), reversed(heights)):
            y -= h
            if y > area.bottom:
                y -= 12
                continue
            if y + h < area.y:
                break
            guest = msg["guest"]
            r = pygame.Rect(area.right - 10 - bw if guest else area.x + 10, y, bw, h)
            pygame.draw.rect(surf, GUEST_FACE if guest else OTHER_FACE, r)
            pygame.draw.rect(surf, K.F_SEL if guest else (190, 180, 120), r, 1)
            label = f"{msg['author']} (FlurPi)" if guest else msg["author"]
            stamp = when(msg["ts"], now)
            stamp_w = K.font(14, False).size(stamp)[0]
            K.t95(surf, label, K.fit_size(label, bw - stamp_w - 30, sizes=(15, 14, 13)), (r.x + 10, r.y + 5),
                  color=K.F_SEL if guest else self._author_color(msg["author"]))
            K.t95(surf, stamp, 14, (r.right - 10, r.y + 6), color=K.F_DARK, bold=False, anchor="topright")
            for i, line in enumerate(self._bubble_lines(msg, bw)):
                K.t95(surf, line, 17, (r.x + 10, r.y + 28 + i * 22), bold=False)
            y -= 12
        surf.set_clip(clip)

        # Win95 scrollbar: ^ older, v newer
        sb = pygame.Rect(area.right + 2, area.y, 26, area.h)
        K.bevel(surf, sb, sunken=True, face=(226, 218, 240))
        rects["up"] = K.button(surf, pygame.Rect(sb.x, sb.y, 26, 44), "^", size=16, enabled=self.scroll < self.max_scroll)
        rects["down"] = K.button(surf, pygame.Rect(sb.x, sb.bottom - 44, 26, 44), "v", size=16, enabled=self.scroll > 0)
        track = pygame.Rect(sb.x, sb.y + 44, 26, sb.h - 88)
        thumb_h = track.h if total <= area.h else max(30, track.h * area.h // total)
        frac = 1 - (self.scroll / self.max_scroll if self.max_scroll else 0)
        K.bevel(surf, pygame.Rect(sb.x, track.y + int((track.h - thumb_h) * frac), 26, thumb_h))
        # widen the arrows' hitboxes to the left, into the chat
        rects["up"] = rects["up"].inflate(24, 8).move(-12, 0)
        rects["down"] = rects["down"].inflate(24, 8).move(-12, 0)
        rects["chat"] = area

    def _draw_compose(self, surf, rects):
        c = self.compose
        win = pygame.Rect(8, 96, K.W - 16, 640)
        inner = K.dialog(surf, win, "pinnwand.exe - Nachricht", icon="note")
        rects["c_close"] = K.close_box(win)
        K.t95(surf, "Name", 16, (inner.x + 2, inner.y + 4))
        K.t95(surf, "(optional)", 13, (inner.x + 2, inner.y + 24), color=K.F_DARK, bold=False)
        nf = pygame.Rect(inner.x + 100, inner.y + 2, inner.w - 100, 44)
        self._field(surf, nf, c["name"], "z.B. Oma Erna", c["field"] == "name", 18)
        rects["c_name"] = nf
        mf = pygame.Rect(inner.x, inner.y + 54, inner.w, 98)
        self._field(surf, mf, c["text"], "Was willst du der WG sagen?", c["field"] == "text", 18, multiline=True)
        K.t95(surf, f"{len(c['text'])}/{TEXT_MAX}", 14, (mf.right - 8, mf.bottom - 6),
              color=K.F_LATE if len(c["text"]) >= TEXT_MAX else K.F_DARK, bold=False, anchor="bottomright")
        rects["c_text"] = mf
        rows = [r.upper() if c["shift"] else r for r in KEY_ROWS]
        kb = pygame.Rect(inner.x, mf.bottom + 12, inner.w, inner.bottom - 70 - mf.bottom - 12)
        rects["c_keys"] = _keyboard(surf, kb, rows, [("abc" if c["shift"] else "ABC", "shift", 0.18), ("Leertaste", " ", 0.46),
                                                     ("<-", "back", 0.16), (":-)", ":-)", 0.2)])
        half = (inner.w - 8) // 2
        rects["c_cancel"] = K.button(surf, pygame.Rect(inner.x, inner.bottom - 56, half, 54), "Abbrechen", size=18)
        can_send = bool(c["text"].strip()) and not self.sending
        label = "Sende..." if self.sending else "An die WG senden"
        rects["c_send"] = K.button(surf, pygame.Rect(inner.x + half + 8, inner.bottom - 56, half, 54), label, size=17, enabled=can_send)

    def _field(self, surf, rect, value, placeholder, active, size, multiline=False):
        K.bevel(surf, rect, sunken=True, face=K.F_PAPER)
        if active:
            pygame.draw.rect(surf, K.F_SEL, rect, 2)
        if not value:
            K.t95(surf, placeholder, 16, (rect.x + 10, rect.y + (10 if multiline else rect.h // 2 - 10)), color=(160, 150, 185), bold=False)
            r = pygame.Rect(rect.x + 8, rect.y + (8 if multiline else rect.h // 2 - 12), 0, 24)
        else:
            lines = K.wrap(value, size, rect.w - 24, bold=False) if multiline else [value]
            if value.endswith(" ") and multiline:
                lines[-1] += " "
            lines = lines[-3:] if multiline else lines
            top = rect.y + 8 if multiline else rect.centery - 12
            for i, line in enumerate(lines):
                r = K.t95(surf, line, size, (rect.x + 10, top + i * 24), bold=False)
        if active and int(time.time() * 2) % 2 == 0:
            pygame.draw.line(surf, K.F_INK, (r.right + 3, r.y + 2), (r.right + 3, r.y + 22), 2)

    # ------------------------------------------------------------ taps

    def tap(self, x, y):
        """True if pinnwand.exe used the tap; False lets PiDashboard handle
        < Zurück / the window's x."""
        pos = (x, y)
        r = self.rects
        if self.compose is not None:
            c = self.compose
            if self.sending:
                return True
            if r["c_close"].collidepoint(pos) or r["c_cancel"].collidepoint(pos):
                self.compose = None
            elif r["c_send"].collidepoint(pos):
                text = c["text"].strip()
                if text:
                    self.sending = True
                    threading.Thread(target=self._send, args=(c["name"].strip(), text), daemon=True).start()
            elif r["c_name"].collidepoint(pos):
                c["field"] = "name"
                c["shift"] = not c["name"]
            elif r["c_text"].collidepoint(pos):
                c["field"] = "text"
                c["shift"] = not c["text"]
            else:
                for rect, token in r["c_keys"]:
                    if rect.collidepoint(pos):
                        self._key(token)
                        break
            return True  # modal
        if r.get("up") and r["up"].collidepoint(pos):
            self.scroll += r["chat"].h * 2 // 3
            return True
        if r.get("down") and r["down"].collidepoint(pos):
            self.scroll = max(0, self.scroll - r["chat"].h * 2 // 3)
            return True
        if (r.get("field") and r["field"].collidepoint(pos)) or (r.get("senden") and r["senden"].collidepoint(pos)):
            self.compose = {"name": "", "text": "", "field": "text", "shift": True}
            self.status = None
            return True
        return False

    def _key(self, token):
        c = self.compose
        key = c["field"]
        limit = TEXT_MAX if key == "text" else NAME_MAX
        if token == "shift":
            c["shift"] = not c["shift"]
            return
        if token == "back":
            c[key] = c[key][:-1]
            c["shift"] = not c[key]
            return
        if len(c[key]) + len(token) > limit:
            return
        c[key] += token
        if c["shift"] and token.isalpha():
            c["shift"] = False
        if key == "text" and token in ".?!":
            c["shift"] = False  # next letter after ". " gets it via space below
        if key == "text" and token == " " and c[key].rstrip()[-1:] in (".", "?", "!"):
            c["shift"] = True


def _keyboard(surf, rect, rows, fn):
    """keyboard95 for rows of different length (11 keys incl. umlauts).
    Returns [(rect, token)]; letters are their own token."""
    keys = []
    gap = 5
    n_rows = len(rows) + 1
    kh = (rect.h - gap * (n_rows - 1)) // n_rows
    most = max(map(len, rows))
    kw = (rect.w - gap * (most - 1)) // most
    for r, row in enumerate(rows):
        x = rect.x + (rect.w - (len(row) * kw + (len(row) - 1) * gap)) // 2
        for ch in row:
            k = pygame.Rect(x, rect.y + r * (kh + gap), kw, kh)
            K.button(surf, k, ch.upper(), size=17)
            keys.append((k, ch))
            x += kw + gap
    y = rect.y + len(rows) * (kh + gap)
    x = rect.x
    avail = rect.w - gap * (len(fn) - 1)
    for i, (label, token, frac) in enumerate(fn):
        w = int(avail * frac) if i < len(fn) - 1 else rect.right - x
        k = pygame.Rect(x, y, w, kh)
        K.button(surf, k, label, size=16)
        keys.append((k, token))
        x += w + gap
    return keys


def _pin_icon(size):
    def make():
        s = pygame.Surface((16, 16), pygame.SRCALPHA)
        pygame.draw.circle(s, (230, 40, 90), (8, 5), 4)
        pygame.draw.circle(s, K.F_INK, (8, 5), 4, 1)
        pygame.draw.rect(s, (255, 150, 180), (6, 3, 2, 2))
        pygame.draw.rect(s, (180, 30, 70), (5, 8, 7, 2))
        pygame.draw.line(s, K.INK, (8, 10), (8, 15))
        return pygame.transform.scale(s, (size, size))
    return K._cached(("pin", size), make)


def pin_icon(size):
    return _pin_icon(size)
