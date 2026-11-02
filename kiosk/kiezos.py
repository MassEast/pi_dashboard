# -*- coding: utf-8 -*-
"""
KiezOS 161: the purple 90s-desktop look of the dashboard. Plain pygame
drawing helpers (bevels, windows, buttons, self-drawn pixel icons, the
7-segment clock, the bus map) used by PiDashboard.py. Everything is drawn at
real screen pixels (480x800 portrait); text is JetBrains Mono rendered
without antialiasing for the crisp old-school look.

configure() must be called once (font dir, icon dir, the theme's "KIEZOS"
palette) before drawing anything.
"""

import math
import os

import pygame
import qrcode

W, H = 480, 800
FONT_DIR = ""
ICON_DIR = ""

INK = (34, 20, 52)  # icon outlines
SUN = (255, 208, 72)
SUN_RAY = (255, 150, 70)
CLOUD = (236, 230, 255)
CLOUD_SH = (186, 170, 230)
GREY = (150, 140, 180)
DROP = (110, 175, 255)
PINK = (255, 130, 200)
BVG_BUS = (149, 39, 110)  # BVG's bus-line badge purple

# UI palette, overridable from the theme's "KIEZOS" block (see configure())
F_FACE = (206, 196, 228)
F_LIGHT = (250, 246, 255)
F_DARK = (66, 50, 92)
F_INK = (20, 10, 30)
F_SEL = (90, 40, 150)
F_TIP = (255, 255, 214)
F_PAPER = (255, 255, 255)
F_ACCENT = (150, 30, 110)
F_LATE = (200, 20, 40)
DESK = (92, 58, 150)
DESK_DITHER = (110, 72, 170)
CLOCK_ON = (220, 160, 255)
CLOCK_OFF = (30, 14, 42)
SHADOW = (40, 20, 70)

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WD_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

_FONTS = {}
_CACHE = {}


def configure(font_dir, icon_dir, palette=None):
    global FONT_DIR, ICON_DIR
    FONT_DIR, ICON_DIR = font_dir, icon_dir
    for key, value in (palette or {}).items():
        globals()[key] = tuple(value)
    _CACHE.clear()


def font(size, bold=True):
    key = (size, bold)
    if key not in _FONTS:
        name = "JetBrainsMono-Bold.ttf" if bold else "JetBrainsMono-Medium.ttf"
        _FONTS[key] = pygame.font.Font(os.path.join(FONT_DIR, name), size)
    return _FONTS[key]


def t95(surf, s, size, pos, color=None, bold=True, anchor="topleft"):
    """KiezOS UI text: crisp, no antialiasing. Returns the drawn rect."""
    img = font(size, bold).render(s, False, F_INK if color is None else color)
    rect = img.get_rect(**{anchor: pos})
    surf.blit(img, rect)
    return rect


def wrap(s, size, max_width, bold=True):
    """Word wrap for t95 text; single words wider than max_width are cut."""
    f = font(size, bold)
    lines, cur = [], ""
    for word in s.split():
        cand = f"{cur} {word}".strip()
        if not cur or f.size(cand)[0] <= max_width:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    out = []
    for line in lines or [""]:
        while f.size(line)[0] > max_width and len(line) > 1:
            cut = len(line) - 1
            while cut > 1 and f.size(line[:cut])[0] > max_width:
                cut -= 1
            out.append(line[:cut])
            line = line[cut:]
        out.append(line)
    return out


def fit_size(s, max_width, sizes=(20, 18, 16, 14, 13, 12, 11), bold=True):
    for size in sizes:
        if font(size, bold).size(s)[0] <= max_width:
            return size
    return sizes[-1]


# ---------------------------------------------------------------- widgets

def bevel(surf, rect, sunken=False, face=None):
    rect = pygame.Rect(rect)
    pygame.draw.rect(surf, F_FACE if face is None else face, rect)
    a, b = (F_DARK, F_LIGHT) if sunken else (F_LIGHT, F_DARK)
    pygame.draw.line(surf, a, rect.topleft, (rect.right - 1, rect.top), 2)
    pygame.draw.line(surf, a, rect.topleft, (rect.left, rect.bottom - 1), 2)
    pygame.draw.line(surf, b, (rect.left, rect.bottom - 1), (rect.right - 1, rect.bottom - 1), 2)
    pygame.draw.line(surf, b, (rect.right - 1, rect.top), (rect.right - 1, rect.bottom - 1), 2)


def button(surf, rect, label, size=15, pressed=False, bold=True, enabled=True, face=None, color=None):
    rect = pygame.Rect(rect)
    bevel(surf, rect, sunken=pressed, face=face)
    if label:
        pos = rect.move(1, 1).center if pressed else rect.center
        if color is None:
            color = F_INK if enabled else (150, 140, 175)
        t95(surf, label, size, pos, color=color, anchor="center", bold=bold)
    return rect


def groupbox(surf, rect, title):
    pygame.draw.rect(surf, F_DARK, rect, 1)
    pygame.draw.rect(surf, F_LIGHT, pygame.Rect(rect).move(1, 1), 1)
    img = font(16).render(title, False, F_INK)
    pygame.draw.rect(surf, F_FACE, (rect.x + 8, rect.y - 10, img.get_width() + 8, 20))
    surf.blit(img, (rect.x + 12, rect.y - 11))


def tooltip(surf, rect):
    pygame.draw.rect(surf, F_TIP, rect)
    pygame.draw.rect(surf, F_INK, rect, 2)


def speech(surf, rect, lines, tail_to, size=16):
    """Comic/assistant balloon with a tail to a point."""
    pygame.draw.rect(surf, F_TIP, rect, border_radius=8)
    base = min(max(tail_to[0], rect.x + 16), rect.right - 32)
    below = tail_to[1] > rect.bottom
    y = rect.bottom - 2 if below else rect.top + 2
    pygame.draw.polygon(surf, F_TIP, [(base, y), (base + 18, y), tail_to])
    pygame.draw.rect(surf, F_INK, rect, 2, border_radius=8)
    d = 1 if below else -1
    pygame.draw.lines(surf, F_INK, False, [(base, y + d), tail_to, (base + 18, y + d)], 2)
    pygame.draw.line(surf, F_TIP, (base + 2, y), (base + 16, y), 3)
    for i, ln in enumerate(lines):
        t95(surf, ln, size, (rect.x + 10, rect.y + 8 + i * (size + 8)), bold=i == 0 and len(lines) == 1)


def line_badge(surf, line, pos, h=26, size=18):
    img = font(size).render(line, True, (255, 255, 255))
    r = pygame.Rect(0, 0, img.get_width() + 14, h)
    r.topleft = pos
    pygame.draw.rect(surf, BVG_BUS, r, border_radius=6)
    surf.blit(img, img.get_rect(center=r.center))
    return r


def _title_gradient(width, height=26):
    key = ("grad", width, height)
    if key not in _CACHE:
        s = pygame.Surface((width, height))
        for i in range(width):
            t = i / width
            pygame.draw.line(s, (int(70 + 110 * t), int(24 + 70 * t), int(120 + 100 * t)), (i, 0), (i, height - 1))
        _CACHE[key] = s
    return _CACHE[key]


def title_buttons(rect):
    """Hitboxes of a home window's x / o / _ title buttons (drawn 20x20,
    tapped generously - real touchscreen taps land a few px off)."""
    bar = pygame.Rect(rect.x + 4, rect.y + 4, rect.w - 8, 26)
    out = {}
    for i, glyph in enumerate(["x", "o", "_"]):
        b = pygame.Rect(bar.right - 23 - i * 23, bar.y + 3, 20, 20)
        out[glyph] = b.inflate(4, 14)
    out["bar"] = bar
    return out


def _close_button(rect):
    bar = pygame.Rect(rect.x + 4, rect.y + 4, rect.w - 8, 26)
    return pygame.Rect(bar.right - 32, bar.y + 1, 30, 24)


def close_box(rect):
    """Hitbox of a popup window's single x (see window(buttons="x"))."""
    return _close_button(pygame.Rect(rect)).inflate(16, 16)


def window(surf, rect, title, icon=None, buttons="x"):
    """Win95-style window: bevelled frame, gradient title bar. buttons: "x"
    (popups: one x, hitbox close_box()), "xo_" (the home windows, hitboxes
    title_buttons()) or None. Returns the client area."""
    rect = pygame.Rect(rect)
    bevel(surf, rect)
    bar = pygame.Rect(rect.x + 4, rect.y + 4, rect.w - 8, 26)
    surf.blit(_title_gradient(bar.w), bar)
    tx = bar.x + 6
    if icon:
        surf.blit(menu_icon(icon, 20), (bar.x + 4, bar.y + 3))
        tx += 22
    max_w = bar.w - (tx - bar.x) - {"xo_": 72, "x": 38}.get(buttons, 6)
    t95(surf, title, fit_size(title, max_w, sizes=(16, 15, 14, 13)), (tx, bar.y + 13), color=(255, 255, 255), anchor="midleft")
    if buttons == "xo_":
        for i, glyph in enumerate(["x", "o", "_"]):
            button(surf, pygame.Rect(bar.right - 23 - i * 23, bar.y + 3, 20, 20), glyph, size=14)
    elif buttons == "x":
        button(surf, _close_button(rect), "x", size=16)
    return pygame.Rect(rect.x + 8, bar.bottom + 6, rect.w - 16, rect.bottom - bar.bottom - 12)


def dialog(surf, rect, title, icon=None, buttons="x"):
    """A window with a drop shadow, for popups over the desktop."""
    pygame.draw.rect(surf, SHADOW, pygame.Rect(rect).move(6, 6))
    return window(surf, rect, title, icon=icon, buttons=buttons)


def game_title(surf, title, icon):
    """Full-width title bar on top of a fullscreen game. Returns the x
    button's (generous) hitbox."""
    bar = pygame.Rect(0, 0, W, 36)
    bevel(surf, bar)
    surf.blit(_title_gradient(W - 6, 30), (3, 3))
    surf.blit(menu_icon(icon, 22), (8, 7))
    t95(surf, title, 16, (36, 18), color=(255, 255, 255), anchor="midleft")
    close = pygame.Rect(W - 44, 5, 38, 26)
    button(surf, close, "x", size=15)
    return close.inflate(10, 10)


def desktop():
    """The dithered purple desktop (cached, copy before drawing on it)."""
    if "desk" not in _CACHE:
        s = pygame.Surface((W, H))
        s.fill(DESK)
        for y in range(0, H, 4):
            for x in range((y // 4) % 2 * 2, W, 4):
                s.set_at((x, y), DESK_DITHER)
        _CACHE["desk"] = s
    return _CACHE["desk"]


def taskbar(surf, now, weather_kind, start_pressed=False, tasks=()):
    """Bottom taskbar: Start button, task buttons, tray (weather, heart,
    time). Returns the Start button's rect."""
    bar = pygame.Rect(0, H - 40, W, 40)
    pygame.draw.rect(surf, F_FACE, bar)
    pygame.draw.line(surf, F_LIGHT, (0, bar.y + 1), (W, bar.y + 1), 2)
    start = pygame.Rect(4, bar.y + 5, 100, 31)
    bevel(surf, start, sunken=start_pressed)
    surf.blit(menu_icon("heart", 24), (start.x + 6, start.y + 3))
    t95(surf, "Start", 17, (start.x + 34, start.y + 5))
    x = start.right + 6
    for icon, label in tasks:
        b = pygame.Rect(x, bar.y + 5, 140, 31)
        bevel(surf, b, sunken=True, face=(226, 218, 244))
        surf.blit(menu_icon(icon, 20), (b.x + 6, b.y + 5))
        t95(surf, label, fit_size(label, 104, sizes=(15, 14, 13)), (b.x + 30, b.y + 7))
        x = b.right + 4
    tray = pygame.Rect(W - 116, bar.y + 5, 112, 31)
    bevel(surf, tray, sunken=True)
    if weather_kind:
        surf.blit(weather_icon(weather_kind, 22), (tray.x + 6, tray.y + 4))
    heart(surf, (tray.x + 44, tray.centery), 2, PINK)
    t95(surf, now.strftime("%H:%M"), 17, (tray.right - 8, tray.y + 6), anchor="topright")
    return start.inflate(4, 8)


def progress95(surf, rect, done, total):
    bevel(surf, rect, sunken=True, face=F_PAPER)
    if total:
        n = int((rect.w - 8) / 12 * done / total)
        for i in range(n):
            pygame.draw.rect(surf, F_SEL, (rect.x + 4 + i * 12, rect.y + 3, 9, rect.h - 6))


def textfield(surf, rect, value, placeholder="", warn=False):
    bevel(surf, rect, sunken=True, face=F_PAPER)
    if warn:
        pygame.draw.rect(surf, F_LATE, rect, 2)
    if value:
        size = fit_size(value, rect.w - 30, sizes=(20, 18, 16, 14))
        r = t95(surf, value, size, (rect.x + 10, rect.centery), anchor="midleft")
        pygame.draw.line(surf, F_INK, (r.right + 3, rect.y + 8), (r.right + 3, rect.bottom - 8), 2)  # caret
    else:
        t95(surf, placeholder, 17, (rect.x + 10, rect.centery), color=(160, 150, 185), bold=False, anchor="midleft")


def keyboard95(surf, rect, rows, fn):
    """Win95 'Bildschirmtastatur': bevelled keys, last row = function keys.
    rows: strings of single-char keys; fn: [(label, token, width_fraction)].
    Returns [(rect, token)]."""
    keys = []
    n_rows = len(rows) + 1
    gap = 5
    kh = (rect.h - gap * (n_rows - 1)) // n_rows
    kw = (rect.w - gap * 9) // 10
    for r, row in enumerate(rows):
        x = rect.x + (rect.w - (len(row) * kw + (len(row) - 1) * gap)) // 2
        for ch in row:
            k = pygame.Rect(x, rect.y + r * (kh + gap), kw, kh)
            button(surf, k, ch.upper(), size=17)
            keys.append((k, ch))
            x += kw + gap
    y = rect.y + len(rows) * (kh + gap)
    x = rect.x
    avail = rect.w - gap * (len(fn) - 1)
    for i, (label, token, frac) in enumerate(fn):
        w_ = int(avail * frac) if i < len(fn) - 1 else rect.right - x
        k = pygame.Rect(x, y, w_, kh)
        button(surf, k, label, size=16)
        keys.append((k, token))
        x += w_ + gap
    return keys


def qr95(data, size):
    key = ("qr", data, size)
    if key not in _CACHE:
        q = qrcode.QRCode(version=1, box_size=1, border=1)
        q.add_data(data)
        q.make(fit=True)
        m = q.get_matrix()
        s = pygame.Surface((len(m), len(m)))
        s.fill((255, 255, 255))
        for y, row in enumerate(m):
            for x, v in enumerate(row):
                if v:
                    s.set_at((x, y), F_INK)
        _CACHE[key] = pygame.transform.scale(s, (size, size))
    return _CACHE[key]


def msgbox(surf, title, icon, lines, buttons, wide=False):
    """Win95 message box with a pixel "!" triangle, centred on screen.
    Returns [(rect, label)] of its buttons, then (close_box, "x")."""
    h = 150 + 24 * len(lines)
    win = pygame.Rect(30, (H - h) // 2 - 20, W - 60, h)
    inner = dialog(surf, win, title, icon=icon)
    warn = pygame.Surface((16, 16), pygame.SRCALPHA)
    pygame.draw.polygon(warn, SUN, [(8, 1), (15, 14), (1, 14)])
    pygame.draw.polygon(warn, F_INK, [(8, 1), (15, 14), (1, 14)], 1)
    pygame.draw.rect(warn, F_INK, (7, 5, 2, 5))
    pygame.draw.rect(warn, F_INK, (7, 11, 2, 2))
    surf.blit(pygame.transform.scale(warn, (48, 48)), (inner.x + 8, inner.y + 10))
    for i, ln in enumerate(lines):
        t95(surf, ln, 17, (inner.x + 70, inner.y + 14 + i * 24))
    bw = 180 if wide else 120
    total = len(buttons) * bw + (len(buttons) - 1) * 12
    out = []
    for i, label in enumerate(buttons):
        r = pygame.Rect(inner.centerx - total // 2 + i * (bw + 12), inner.bottom - 46, bw, 42)
        button(surf, r, label, size=16)
        out.append((r, label))
    out.append((close_box(win), "x"))
    return out


def wordart(surf, s, size, center, wave=6):
    """90s WordArt: per-letter wave, extruded shadow, purple->pink gradient fill."""
    key = ("wordart", s, size, wave)
    if key not in _CACHE:
        f = font(size)
        letters = [f.render(ch, False, (255, 255, 255)) for ch in s]
        total = sum(l.get_width() for l in letters)
        lh = letters[0].get_height()
        art = pygame.Surface((total + 8, lh + 2 * wave + 8), pygame.SRCALPHA)
        x = 0
        for i, l in enumerate(letters):
            y = wave + int(math.sin(i * 0.7) * wave)
            mask = pygame.mask.from_surface(l)
            for k in range(6, 0, -1):  # extrusion
                sh = mask.to_surface(setcolor=(40 + k * 6, 14, 70 + k * 6), unsetcolor=(0, 0, 0, 0))
                art.blit(sh, (x + k, y + k))
            grad = pygame.Surface(l.get_size(), pygame.SRCALPHA)
            for gy in range(l.get_height()):
                t = gy / max(1, l.get_height() - 1)
                pygame.draw.line(grad, (int(255 - 60 * t), int(220 - 120 * t), int(120 + 135 * t)), (0, gy), (l.get_width(), gy))
            grad.blit(mask.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0)), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            art.blit(grad, (x, y))
            x += l.get_width()
        _CACHE[key] = art
    art = _CACHE[key]
    surf.blit(art, art.get_rect(center=center))


SEG = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
       "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"}


def seven_seg(surf, digit, x, y, w, h, on=None, off=None):
    on = CLOCK_ON if on is None else on
    off = CLOCK_OFF if off is None else off
    t = max(6, w // 6)
    g = 3  # gap between segments

    def hseg(x1, x2, cy):
        return [(x1, cy), (x1 + t // 2, cy - t // 2), (x2 - t // 2, cy - t // 2), (x2, cy),
                (x2 - t // 2, cy + t // 2), (x1 + t // 2, cy + t // 2)]

    def vseg(cx, y1, y2):
        return [(cx, y1), (cx + t // 2, y1 + t // 2), (cx + t // 2, y2 - t // 2), (cx, y2),
                (cx - t // 2, y2 - t // 2), (cx - t // 2, y1 + t // 2)]

    l, r, top, mid, bot = x + t // 2, x + w - t // 2, y + t // 2, y + h // 2, y + h - t // 2
    segs = {"a": hseg(l + g, r - g, top), "g": hseg(l + g, r - g, mid), "d": hseg(l + g, r - g, bot),
            "f": vseg(l, top + g, mid - g), "b": vseg(r, top + g, mid - g),
            "e": vseg(l, mid + g, bot - g), "c": vseg(r, mid + g, bot - g)}
    for name, pts in segs.items():
        pygame.draw.polygon(surf, on if name in SEG.get(digit, "") else off, pts)


# ---------------------------------------------------------------- weather + bus helpers

def kind_of(code, pod="d"):
    """Weatherbit weather code -> one of our icon kinds."""
    code = int(code)
    if 200 <= code < 300:
        return "thunder"
    if 300 <= code < 600:
        return "rain"
    if 600 <= code < 700:
        return "snow"
    if 700 <= code < 800:
        return "fog"
    if code == 800:
        return "sun" if pod == "d" else "moon"
    if code in (801, 802):
        return "partly" if pod == "d" else "moon"
    return "cloud"


QUIRKY_DESC = {
    "sun": "Sonne satt!", "moon": "Mondschein", "partly": "Ein paar Wölkchen",
    "cloud": "Grau in grau", "rain": "Schirm mit!", "snow": "Schnee!!", "thunder": "Es rumst",
    "fog": "Suppe draußen",
}


def rain_summary(hours, probs):
    """hours: [int hour of day], probs: [percent] for the coming hours."""
    if not hours:
        return "Regenradar schläft", False
    for h, p in zip(hours, probs):
        if p >= 40:
            return f"Regen ab {h} Uhr", True
    return f"bis {(hours[-1] + 1) % 24} Uhr trocken", False


def rain_chart(surf, rect, hours, probs, labels=False):
    bevel(surf, rect, sunken=True, face=F_PAPER)
    n = len(probs)
    if not n:
        return
    pad_l = 42 if labels else 8
    pad_b = 22 if labels else 8
    top = rect.y + (10 if labels else 18)
    plot_h = rect.bottom - pad_b - top
    bw = (rect.w - pad_l - 8) / n
    if labels:
        for pct in (0, 50, 100):
            y = rect.bottom - pad_b - int(pct / 100 * plot_h)
            pygame.draw.line(surf, (226, 218, 244), (rect.x + pad_l, y), (rect.right - 6, y))
            t95(surf, f"{pct}%", 13, (rect.x + pad_l - 4, y), color=F_DARK, bold=False, anchor="midright")
    for i, (h, p) in enumerate(zip(hours, probs)):
        bh = max(2, int(p / 100 * plot_h))
        x = int(rect.x + pad_l + i * bw)
        pygame.draw.rect(surf, (60, 80, 200) if p >= 40 else (140, 150, 230), (x + 1, rect.bottom - pad_b - bh, max(1, int(bw) - 3), bh))
        if labels and i % 2 == 0:
            t95(surf, f"{h}h", 13, (x + bw / 2, rect.bottom - pad_b + 3), color=F_DARK, bold=False, anchor="midtop")


def due_color(delay):
    """A late bus's time gets redder, full red at 8 min (like the old
    _delay_to_departure_text_color)."""
    t = min(max(delay, 0), 8) / 8
    return tuple(round(a + (b - a) * t) for a, b in zip(F_ACCENT, F_LATE))


def mins_text(mins):
    if not mins:
        return "keine", ""
    first = "jetzt" if mins[0] <= 0 else f"{mins[0]} min"
    return first, ", ".join(str(m) for m in mins[1:])


def haltestelle(surf, pos, line):
    """German bus stop sign: green H on a yellow disc, on a pole, with the line below."""
    x, y = pos
    pygame.draw.line(surf, F_INK, (x, y), (x, y + 30), 3)
    pygame.draw.circle(surf, F_INK, (x, y), 13)
    pygame.draw.circle(surf, (250, 210, 50), (x, y), 11)
    t95(surf, "H", 15, (x, y + 1), color=(20, 120, 60), anchor="center")
    r = pygame.Rect(0, 0, 34, 16)
    r.midtop = (x, y + 16)
    pygame.draw.rect(surf, BVG_BUS, r)
    t95(surf, line, 11, r.center, color=(255, 255, 255), anchor="center")


def draw_map(surf, area, m, rows):
    """The karte.exe map from config BVG.MAP into area (clipped). m: the MAP
    dict (screen pixels), rows: {row_id: {line, label, landmark, mins, delays}}.
    Water first, then streets (all edges, then all surfaces, so crossings
    merge), bridges, dotted bus routes, landmarks with their row's tooltip,
    the home and the stop signs."""
    bevel(surf, area, sunken=True, face=(242, 238, 252))
    clip = surf.get_clip()
    surf.set_clip(area.inflate(-4, -4))
    for x in range(area.x, area.right, 24):
        pygame.draw.line(surf, (234, 228, 248), (x, area.y), (x, area.bottom))
    for y in range(area.y, area.bottom, 24):
        pygame.draw.line(surf, (234, 228, 248), (area.x, y), (area.right, y))

    def thick(points, col, w_):
        pygame.draw.lines(surf, col, False, points, w_)
        for p in points[1:-1]:
            pygame.draw.circle(surf, col, p, w_ // 2)

    water, wave = (168, 200, 250), (120, 160, 235)
    for wtr in m.get("WATER", []):
        if "ellipse" in wtr:
            pygame.draw.ellipse(surf, water, wtr["ellipse"])
            continue
        pts = wtr["line"]
        thick(pts, water, wtr.get("width", 34))
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            for k in range(0, 100, 34):
                cx, cy = x1 + (x2 - x1) * k / 100, y1 + (y2 - y1) * k / 100
                pygame.draw.lines(surf, wave, False, [(cx - 7, cy + 2), (cx, cy - 2), (cx + 7, cy + 2)], 2)

    streets = m.get("STREETS", [])
    for col, extra in ((F_INK, 2), (F_PAPER, 0)):
        for st in streets:
            thick(st["line"], col, 2 * (st.get("half_width", 22) + extra))
    for st in streets:  # centre dashes, stopping short of each segment's end
        if not st.get("dashes"):
            continue
        margin = st.get("half_width", 22) + 8
        for (x1, y1), (x2, y2) in zip(st["line"], st["line"][1:]):
            ln = math.hypot(x2 - x1, y2 - y1)
            ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
            for k in range(0, int(ln - margin), 24):
                pygame.draw.line(surf, (200, 190, 225), (x1 + ux * k, y1 + uy * k), (x1 + ux * (k + 12), y1 + uy * (k + 12)), 2)

    for br in m.get("BRIDGES", []):
        # straight span between two points of a street over water: shadow on
        # the water, stone parapets with posts on both sides, deck in between
        (ax, ay), (bx, by) = br["from"], br["to"]
        half = br.get("half_width", 22)
        c = ((ax + bx) / 2, (ay + by) / 2)
        ln = math.hypot(bx - ax, by - ay)
        u = ((bx - ax) / ln, (by - ay) / ln)
        n = (-u[1], u[0])
        span = int(ln * 0.4)

        def at(a, b):
            return (c[0] + u[0] * a + n[0] * b, c[1] + u[1] * a + n[1] * b)
        pygame.draw.polygon(surf, (130, 165, 230), [at(-span, half + 4), at(span, half + 4), at(span + 6, half + 10), at(-span + 6, half + 10)])
        pygame.draw.polygon(surf, F_PAPER, [at(-span, -half), at(span, -half), at(span, half), at(-span, half)])
        for side in (-1, 1):
            o, i_ = side * (half + 6), side * (half + 1)
            pygame.draw.polygon(surf, F_FACE, [at(-span, i_), at(span, i_), at(span, o), at(-span, o)])
            pygame.draw.polygon(surf, F_INK, [at(-span, i_), at(span, i_), at(span, o), at(-span, o)], 2)
            for k in range(-span, span + 1, 17):
                pygame.draw.rect(surf, F_INK, pygame.Rect(0, 0, 7, 7).move(*[int(v) - 3 for v in at(k, (o + i_) / 2)]))

    for route in m.get("ROUTES", []):  # dotted bus route
        for (x1, y1), (x2, y2) in zip(route, route[1:]):
            n = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / 10))
            for k in range(n):
                pygame.draw.circle(surf, BVG_BUS, (x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n), 2)
    surf.set_clip(clip)

    for lm in m.get("LANDMARKS", []):
        row = rows[lm["row"]]
        surf.blit(landmark_icon(row["landmark"], lm.get("icon_size", 80)), lm["icon_pos"])
        rect = pygame.Rect(lm["label"])
        pygame.draw.line(surf, F_INK, lm["leader"][0], lm["leader"][1], 2)
        tooltip(surf, rect)
        b = line_badge(surf, row["line"], (rect.x + 8, rect.y + 6), h=24, size=16)
        t95(surf, row["label"], fit_size(row["label"], rect.right - b.right - 14, sizes=(18, 17, 15)), (b.right + 8, rect.y + 8))
        first, rest = mins_text(row["mins"])
        r1 = t95(surf, first, 18, (rect.x + 10, rect.y + 34), color=due_color(row["delays"][0]) if row["mins"] else F_DARK)
        if rest:
            t95(surf, f"dann {rest}", 16, (r1.right + 8, rect.y + 37), color=F_DARK, bold=False)

    home = m.get("HOME")
    if home:
        (hx, hy), size = home["pos"], home.get("size", 50)
        surf.blit(landmark_icon("home", size), (hx, hy))
        for i, ln in enumerate(home.get("label", [])):
            t95(surf, ln, 15, (hx + size // 2, hy + size + 2 + i * 18), color=(140, 60, 220), anchor="midtop")
    for stop in m.get("STOPS", []):
        haltestelle(surf, stop["pos"], rows[stop["row"]]["line"])


# ---------------------------------------------------------------- quirky pixel icons
# Drawn on a small canvas without antialiasing, then scaled up nearest-neighbour.

def _canvas(n=32):
    return pygame.Surface((n, n), pygame.SRCALPHA)


def _cached(key, make):
    if key not in _CACHE:
        _CACHE[key] = make()
    return _CACHE[key]


def _sun(s, cx, cy, r, shades=True):
    for i in range(8):
        a = i * math.pi / 4
        p1 = (cx + math.cos(a) * (r + 2), cy + math.sin(a) * (r + 2))
        p2 = (cx + math.cos(a) * (r + 5), cy + math.sin(a) * (r + 5))
        pygame.draw.line(s, SUN_RAY, p1, p2, 2)
    pygame.draw.circle(s, INK, (cx, cy), r + 1)
    pygame.draw.circle(s, SUN, (cx, cy), r)
    if shades:
        pygame.draw.rect(s, INK, (cx - r + 2, cy - 2, r - 2, 3))
        pygame.draw.rect(s, INK, (cx + 1, cy - 2, r - 2, 3))
        pygame.draw.line(s, INK, (cx - r + 1, cy - 2), (cx + r - 1, cy - 2))
        pygame.draw.line(s, INK, (cx - 2, cy + 3), (cx + 2, cy + 3))
        s.set_at((cx - 3, cy + 2), INK)
        s.set_at((cx + 3, cy + 2), INK)
        s.set_at((cx - r + 2, cy + 2), PINK)
        s.set_at((cx + r - 2, cy + 2), PINK)


def _cloud(s, x, y, w, fill=CLOUD, shade=CLOUD_SH, face="smile"):
    h = w // 2
    blobs = [(x + w * 0.3, y + h * 0.55, h * 0.45), (x + w * 0.55, y + h * 0.4, h * 0.55),
             (x + w * 0.78, y + h * 0.62, h * 0.38)]
    for bx, by, br in blobs:
        pygame.draw.circle(s, INK, (int(bx), int(by)), int(br) + 1)
    pygame.draw.rect(s, INK, (x + w * 0.12 - 1, y + h * 0.55, w * 0.78 + 2, h * 0.45 + 1), border_radius=3)
    for bx, by, br in blobs:
        pygame.draw.circle(s, fill, (int(bx), int(by)), int(br))
    pygame.draw.rect(s, fill, (x + w * 0.12, y + h * 0.55, w * 0.78, h * 0.45), border_radius=3)
    pygame.draw.line(s, shade, (x + w * 0.16, y + h - 1), (x + w * 0.86, y + h - 1), 2)
    ex, ey = int(x + w * 0.42), int(y + h * 0.62)
    if face == "smile":
        s.set_at((ex, ey), INK); s.set_at((ex, ey + 1), INK)
        s.set_at((ex + 6, ey), INK); s.set_at((ex + 6, ey + 1), INK)
        pygame.draw.line(s, INK, (ex + 2, ey + 3), (ex + 4, ey + 3))
        s.set_at((ex - 2, ey + 2), PINK); s.set_at((ex + 8, ey + 2), PINK)
    elif face == "sleepy":
        pygame.draw.line(s, INK, (ex - 1, ey + 1), (ex + 1, ey + 1))
        pygame.draw.line(s, INK, (ex + 5, ey + 1), (ex + 7, ey + 1))
        pygame.draw.line(s, INK, (ex + 2, ey + 4), (ex + 4, ey + 4))
    elif face == "sad":
        s.set_at((ex, ey), INK); s.set_at((ex + 6, ey), INK)
        pygame.draw.line(s, INK, (ex + 2, ey + 4), (ex + 4, ey + 4))
        s.set_at((ex + 1, ey + 5), INK); s.set_at((ex + 5, ey + 5), INK)
        s.set_at((ex, ey + 2), DROP)
    elif face == "angry":
        pygame.draw.line(s, INK, (ex - 1, ey - 1), (ex + 1, ey))
        pygame.draw.line(s, INK, (ex + 5, ey), (ex + 7, ey - 1))
        s.set_at((ex, ey + 1), INK); s.set_at((ex + 6, ey + 1), INK)
        pygame.draw.line(s, INK, (ex + 1, ey + 4), (ex + 5, ey + 4))


def _weather_icon(kind):
    s = _canvas(32)
    if kind == "sun":
        _sun(s, 16, 16, 9)
    elif kind == "moon":
        pygame.draw.circle(s, INK, (15, 16), 11)
        pygame.draw.circle(s, (255, 236, 160), (15, 16), 10)
        pygame.draw.circle(s, (0, 0, 0, 0), (21, 12), 9)
        pygame.draw.line(s, INK, (8, 16), (11, 16))
        s.set_at((9, 20), PINK)
        pygame.draw.polygon(s, PINK, [(6, 8), (14, 5), (4, 0)])  # nightcap
        pygame.draw.circle(s, CLOUD, (4, 1), 2)
        for zx, zy in [(22, 22), (26, 17)]:
            pygame.draw.lines(s, CLOUD, False, [(zx, zy), (zx + 3, zy), (zx, zy + 3), (zx + 3, zy + 3)])
    elif kind == "partly":
        _sun(s, 20, 11, 7)
        _cloud(s, 1, 12, 26, face="smile")
    elif kind == "cloud":
        _cloud(s, 7, 3, 22, fill=GREY, shade=(110, 100, 140), face="sleepy")
        _cloud(s, 1, 11, 26, face="sleepy")
    elif kind == "rain":
        _cloud(s, 2, 2, 28, fill=(200, 192, 230), face="sad")
        for dx, dy in [(8, 20), (14, 23), (20, 20), (26, 24), (11, 27)]:
            pygame.draw.line(s, DROP, (dx, dy), (dx - 1, dy + 3), 2)
    elif kind == "snow":
        _cloud(s, 2, 2, 28, face="smile")
        for dx, dy in [(8, 22), (15, 26), (22, 22), (27, 27)]:
            pygame.draw.line(s, CLOUD, (dx - 1, dy), (dx + 1, dy)); pygame.draw.line(s, CLOUD, (dx, dy - 1), (dx, dy + 1))
    elif kind == "thunder":
        _cloud(s, 2, 2, 28, fill=GREY, shade=(100, 90, 130), face="angry")
        pygame.draw.polygon(s, SUN, [(16, 17), (11, 25), (15, 25), (12, 31), (20, 22), (16, 22), (19, 17)])
    elif kind == "fog":
        for i, y in enumerate((9, 14, 19, 24)):
            pygame.draw.line(s, CLOUD if i % 2 else CLOUD_SH, (4 + 3 * (i % 2), y), (27 - 2 * (i % 2), y), 3)
    return s


def weather_icon(kind, size):
    return _cached(("weather", kind, size), lambda: pygame.transform.scale(_weather_icon(kind), (size, size)))


def sunrise_icon(size):
    def make():
        s = _canvas(32)
        _sun(s, 16, 22, 7, shades=False)
        pygame.draw.rect(s, (0, 0, 0, 0), (0, 25, 32, 7))
        pygame.draw.line(s, INK, (2, 25), (29, 25), 2)
        return pygame.transform.scale(s, (size, size))
    return _cached(("sunrise", size), make)


def _landmark_icon(kind):
    s = _canvas(32)
    if kind == "garden":  # tree, fence, flowers
        pygame.draw.rect(s, (120, 80, 60), (14, 18, 4, 10))
        for cx, cy, r in [(16, 11, 9), (10, 15, 6), (22, 15, 6)]:
            pygame.draw.circle(s, INK, (cx, cy), r + 1)
        for cx, cy, r in [(16, 11, 9), (10, 15, 6), (22, 15, 6)]:
            pygame.draw.circle(s, (110, 200, 130), (cx, cy), r)
        for p in [(13, 8), (19, 12), (11, 16), (21, 7)]:
            s.set_at(p, (170, 240, 170))
        s.set_at((18, 9), PINK); s.set_at((12, 12), PINK)
        for x in range(2, 31, 4):
            pygame.draw.line(s, CLOUD_SH, (x, 25), (x, 30))
        pygame.draw.line(s, CLOUD_SH, (1, 27), (30, 27))
        for fx in (5, 25):
            pygame.draw.circle(s, PINK, (fx, 23), 1)
    elif kind == "palace":  # revue palace: wide front, arches, neon star
        pygame.draw.rect(s, INK, (1, 11, 30, 19))
        pygame.draw.rect(s, (210, 200, 235), (2, 12, 28, 17))
        for i in range(6):
            x = 4 + i * 4
            pygame.draw.rect(s, (90, 60, 140), (x, 17, 3, 12))
            pygame.draw.circle(s, (90, 60, 140), (x + 1, 17), 1)
        pygame.draw.rect(s, PINK, (6, 13, 20, 2))
        pygame.draw.polygon(s, SUN, [(16, 2), (18, 7), (23, 7), (19, 10), (20, 14), (16, 11), (12, 14), (13, 10), (9, 7), (14, 7)])
    elif kind == "zoo":  # elephant with a bow
        pygame.draw.ellipse(s, INK, (5, 9, 22, 16))
        pygame.draw.ellipse(s, (170, 165, 200), (6, 10, 20, 14))
        pygame.draw.circle(s, INK, (25, 13), 6)
        pygame.draw.circle(s, (170, 165, 200), (25, 13), 5)
        pygame.draw.ellipse(s, (140, 130, 180), (18, 9, 6, 9))
        pygame.draw.lines(s, (170, 165, 200), False, [(29, 15), (30, 21), (28, 24)], 3)
        for lx in (8, 13, 18, 22):
            pygame.draw.rect(s, (170, 165, 200), (lx, 22, 3, 6))
            pygame.draw.line(s, INK, (lx, 28), (lx + 2, 28))
        s.set_at((26, 12), INK)
        pygame.draw.polygon(s, PINK, [(20, 7), (23, 5), (23, 9)])
        pygame.draw.polygon(s, PINK, [(20, 7), (17, 5), (17, 9)])
        pygame.draw.line(s, INK, (5, 14), (2, 18))
    elif kind == "lake":  # water + duck
        pygame.draw.ellipse(s, INK, (0, 12, 32, 18))
        pygame.draw.ellipse(s, (90, 140, 230), (1, 13, 30, 16))
        for wx, wy in [(5, 22), (19, 25), (22, 17)]:
            pygame.draw.lines(s, (170, 210, 255), False, [(wx, wy), (wx + 2, wy - 1), (wx + 4, wy)])
        pygame.draw.ellipse(s, SUN, (9, 14, 10, 6))
        pygame.draw.circle(s, SUN, (17, 12), 3)
        pygame.draw.line(s, SUN_RAY, (19, 12), (21, 12), 2)
        s.set_at((17, 11), INK)
    elif kind == "home":  # WG: purple roof, heart window
        pygame.draw.polygon(s, INK, [(2, 15), (16, 2), (30, 15)])
        pygame.draw.polygon(s, (160, 90, 230), [(4, 14), (16, 4), (28, 14)])
        pygame.draw.rect(s, INK, (5, 14, 22, 16))
        pygame.draw.rect(s, (240, 232, 255), (6, 15, 20, 14))
        pygame.draw.rect(s, (90, 60, 140), (18, 20, 5, 9))
        pygame.draw.rect(s, (150, 200, 255), (8, 18, 7, 6))
        pygame.draw.circle(s, PINK, (10, 20), 1); pygame.draw.circle(s, PINK, (13, 20), 1)
        pygame.draw.polygon(s, PINK, [(9, 21), (14, 21), (11, 23)])
    elif kind == "bus":  # BVG-yellow bus, side view
        pygame.draw.rect(s, INK, (1, 9, 30, 17), border_radius=3)
        pygame.draw.rect(s, (250, 210, 50), (2, 10, 28, 15), border_radius=3)
        for x in range(4, 26, 6):
            pygame.draw.rect(s, (120, 180, 230), (x, 12, 4, 5))
        pygame.draw.rect(s, (120, 180, 230), (26, 12, 3, 8))
        pygame.draw.line(s, (160, 90, 230), (2, 20), (29, 20), 2)
        for wx in (8, 23):
            pygame.draw.circle(s, INK, (wx, 26), 3)
            pygame.draw.circle(s, GREY, (wx, 26), 1)
    return s


def landmark_icon(kind, size):
    return _cached(("landmark", kind, size), lambda: pygame.transform.scale(_landmark_icon(kind), (size, size)))


def arrow_icon(direction, size, color):
    def make():
        s = _canvas(16)
        pygame.draw.polygon(s, color, [(8, 1), (14, 9), (10, 9), (10, 15), (6, 15), (6, 9), (2, 9)])
        angle = {"up": 0, "left": 90, "double_left": 90, "down": 180, "right": -90}.get(direction, 0)
        s = pygame.transform.rotate(s, angle)
        if direction == "double_left":
            d = _canvas(16)
            small = pygame.transform.scale(s, (11, 11))
            d.blit(small, (0, 2)); d.blit(small, (6, 2))
            s = d
        return pygame.transform.scale(s, (size, size))
    return _cached(("arrow", direction, size, color), make)


def heart(surf, center, scale, color):
    def make():
        h = _canvas(8)
        for y, row in enumerate([".XX.XX.", "XXXXXXX", "XXXXXXX", ".XXXXX.", "..XXX..", "...X..."]):
            for x, ch in enumerate(row):
                if ch == "X":
                    h.set_at((x, y), color)
        return pygame.transform.scale(h, (8 * scale, 8 * scale))
    h = _cached(("heart", scale, color), make)
    surf.blit(h, h.get_rect(center=(center[0] + scale // 2, center[1] + scale)))


MERZ_GRID = (28, 38)  # icons/merz_sprite.png is a 28x38 pixel-art grid at 6 px/cell (dev/generate_merz_sprite.py)


def merz_sprite(height):
    """Integer-scaled so the pixel art stays crisp: whole px per grid cell."""
    def make():
        img = pygame.image.load(os.path.join(ICON_DIR, "merz_sprite.png")).convert_alpha()
        if height < MERZ_GRID[1]:
            return pygame.transform.smoothscale(img, (int(img.get_width() * height / img.get_height()), height))
        grid = pygame.transform.scale(img, MERZ_GRID)
        cell = max(1, round(height / MERZ_GRID[1]))
        return pygame.transform.scale(grid, (MERZ_GRID[0] * cell, MERZ_GRID[1] * cell))
    return _cached(("merz", height), make)


def _menu_icon(kind):
    s = _canvas(16)
    if kind == "enteignen":  # ENTEIGNEN!: a € coin with a pink cut through it
        pygame.draw.circle(s, INK, (8, 8), 7); pygame.draw.circle(s, SUN, (8, 8), 6)
        pygame.draw.rect(s, (200, 140, 30), (6, 5, 4, 1)); pygame.draw.rect(s, (200, 140, 30), (6, 10, 4, 1))
        pygame.draw.rect(s, (200, 140, 30), (5, 6, 1, 4)); pygame.draw.rect(s, (200, 140, 30), (4, 7, 4, 1))
        pygame.draw.line(s, (255, 255, 255), (1, 14), (14, 1), 2); pygame.draw.line(s, PINK, (2, 15), (15, 2), 1)
    elif kind == "games":  # joystick
        pygame.draw.rect(s, INK, (2, 10, 12, 5)); pygame.draw.rect(s, (160, 90, 230), (3, 11, 10, 3))
        pygame.draw.line(s, INK, (8, 10), (8, 4), 2); pygame.draw.circle(s, PINK, (8, 3), 3)
        s.set_at((11, 12), SUN)
    elif kind == "folder":  # "Mehr Spiele...": a yellow 95 folder
        pygame.draw.rect(s, INK, (1, 3, 7, 3)); pygame.draw.rect(s, INK, (1, 5, 14, 10))
        pygame.draw.rect(s, (255, 208, 72), (2, 4, 5, 2)); pygame.draw.rect(s, (255, 208, 72), (2, 6, 12, 8))
        pygame.draw.rect(s, (255, 236, 150), (2, 6, 12, 1))
    elif kind == "stack":  # STAPEL-TURM
        for i, c in enumerate([(255, 130, 200), (160, 90, 230), (110, 175, 255), (255, 208, 72)]):
            pygame.draw.rect(s, INK, (3 + (i % 2), 12 - i * 3, 10, 3)); pygame.draw.rect(s, c, (4 + (i % 2), 12 - i * 3, 8, 2))
    elif kind == "quiz":  # AFM: speech bubble with "?"
        pygame.draw.rect(s, INK, (1, 1, 14, 11)); pygame.draw.rect(s, (255, 255, 255), (2, 2, 12, 9))
        pygame.draw.polygon(s, INK, [(4, 12), (8, 12), (4, 15)])
        for y, row in enumerate([".XXX.", "X...X", "...X.", "..X..", ".....", "..X.."]):
            for x, ch in enumerate(row):
                if ch == "X":
                    s.set_at((x + 6, y + 3), (160, 30, 120))
    elif kind == "broom":  # Putzen
        pygame.draw.line(s, (150, 100, 60), (12, 1), (6, 9), 2)
        pygame.draw.polygon(s, SUN, [(3, 9), (9, 9), (11, 15), (1, 15)])
        pygame.draw.polygon(s, INK, [(3, 9), (9, 9), (11, 15), (1, 15)], 1)
        s.set_at((13, 12), DROP); s.set_at((14, 9), DROP)
    elif kind == "wifi":
        for r, c in [(7, (160, 90, 230)), (5, (190, 140, 250)), (3, PINK)]:
            pygame.draw.arc(s, c, (8 - r, 12 - r, 2 * r, 2 * r), math.pi / 4, 3 * math.pi / 4, 2)
        pygame.draw.circle(s, INK, (8, 12), 1)
    elif kind == "stats":
        pygame.draw.rect(s, (255, 255, 255), (1, 1, 14, 14)); pygame.draw.rect(s, INK, (1, 1, 14, 14), 1)
        for i, (hgt, c) in enumerate([(4, PINK), (8, (160, 90, 230)), (6, DROP), (10, (110, 200, 130))]):
            pygame.draw.rect(s, c, (3 + i * 3, 13 - hgt, 2, hgt))
    elif kind == "power":
        pygame.draw.circle(s, (220, 60, 90), (8, 8), 7); pygame.draw.circle(s, (255, 255, 255), (8, 8), 4, 1)
        pygame.draw.line(s, (220, 60, 90), (8, 2), (8, 6), 3); pygame.draw.line(s, (255, 255, 255), (8, 2), (8, 7))
    elif kind == "clock":
        pygame.draw.circle(s, INK, (8, 8), 7); pygame.draw.circle(s, (255, 255, 255), (8, 8), 6)
        pygame.draw.line(s, INK, (8, 8), (8, 4)); pygame.draw.line(s, INK, (8, 8), (11, 9))
    elif kind == "map":
        pygame.draw.polygon(s, (255, 255, 255), [(1, 3), (6, 1), (10, 3), (15, 1), (15, 13), (10, 15), (6, 13), (1, 15)])
        pygame.draw.polygon(s, INK, [(1, 3), (6, 1), (10, 3), (15, 1), (15, 13), (10, 15), (6, 13), (1, 15)], 1)
        pygame.draw.line(s, PINK, (3, 11), (12, 5), 2); pygame.draw.circle(s, (160, 30, 120), (12, 5), 2)
    elif kind == "note":
        pygame.draw.rect(s, (255, 255, 255), (3, 1, 11, 14)); pygame.draw.rect(s, INK, (3, 1, 11, 14), 1)
        for y in (5, 8, 11):
            pygame.draw.line(s, DROP, (5, y), (11, y))
    elif kind == "heart":
        for y, row in enumerate(["", "", "", "..XX...XX..", ".XXXX.XXXX.", ".XXXXXXXXX.", "..XXXXXXX..", "...XXXXX...", "....XXX....", ".....X....."]):
            for x, ch in enumerate(row):
                if ch == "X":
                    s.set_at((x + 2, y + 1), PINK)
    elif kind == "ok":
        pygame.draw.circle(s, (40, 160, 90), (8, 8), 7)
        pygame.draw.lines(s, (255, 255, 255), False, [(4, 8), (7, 11), (12, 5)], 2)
    return s


# Icons drawn by game modules themselves (kind -> fn(size)), registered by
# PiDashboard.py so kiezos never imports a game.
ICON_MAKERS = {}


def menu_icon(kind, size=32):
    """16px KiezOS menu/title icons, scaled up nearest-neighbour."""
    if kind in ICON_MAKERS:
        return _cached(("menu-extra", kind, size), lambda: ICON_MAKERS[kind](size))
    if kind in ("bus", "zoo", "home", "lake", "garden", "palace"):
        return landmark_icon(kind, size)
    if kind == "weather":
        return weather_icon("partly", size)
    if kind == "merz":
        return _cached(("menu-merz", size), lambda: _merz_menu_icon(size))
    return _cached(("menu", kind, size), lambda: pygame.transform.scale(_menu_icon(kind), (size, size)))


def _px(s, pattern, x0, y0, color):
    """Draw a small "X" pixel pattern (list of strings) at x0, y0."""
    for y, row in enumerate(pattern):
        for x, ch in enumerate(row):
            if ch == "X":
                s.set_at((x0 + x, y0 + y), color)


FACE = (255, 214, 90)
FACE_SH = (235, 170, 50)
MOUTH = (150, 40, 70)
TEAR = DROP
RED_FACE = (255, 120, 90)


def _face(s, fill=FACE):
    pygame.draw.circle(s, INK, (8, 8), 7)
    pygame.draw.circle(s, fill, (8, 8), 6)
    pygame.draw.arc(s, FACE_SH if fill == FACE else (0, 0, 0, 60), (2, 2, 13, 13), math.pi * 1.1, math.pi * 1.9, 1)


def _emotion_icon(name):
    """16px mood.exe faces, one per catalog emotion; unknown (custom) ones get a "?" face."""
    s = _canvas(16)
    dots = lambda y=6: (s.set_at((5, y), INK), s.set_at((10, y), INK), s.set_at((5, y + 1), INK), s.set_at((10, y + 1), INK))  # noqa: E731
    smile = lambda: _px(s, ["X.....X", ".X...X.", "..XXX.."], 4, 9, MOUTH)  # noqa: E731
    if name == "happy":
        _face(s); dots(); smile()
    elif name == "excited":  # star eyes, open mouth
        _face(s)
        for x in (5, 10):
            _px(s, [".X.", "XXX", ".X."], x - 1, 5, (230, 60, 140))
        pygame.draw.rect(s, MOUTH, (5, 9, 6, 3)); pygame.draw.rect(s, (255, 130, 160), (6, 11, 4, 1))
    elif name == "energized":  # lightning bolt
        pts = [(9, 0), (3, 9), (7, 9), (5, 15), (13, 6), (9, 6), (11, 0)]
        pygame.draw.polygon(s, SUN, pts); pygame.draw.polygon(s, INK, pts, 1)
    elif name == "wild":  # party hat + confetti
        _face(s); dots(7); _px(s, ["X....X", ".XXXX."], 5, 10, MOUTH)
        pygame.draw.polygon(s, (160, 90, 230), [(9, 0), (6, 4), (12, 4)]); s.set_at((9, 0), PINK)
        for p, c in (((1, 2), PINK), ((14, 3), DROP), ((1, 13), SUN), ((14, 12), (90, 200, 90))):
            s.set_at(p, c)
    elif name == "grateful":  # ^^ eyes + heart
        _face(s)
        for x in (4, 9):
            _px(s, [".X.", "X.X"], x, 6, INK)
        smile()
        _px(s, ["XX.XX", "XXXXX", ".XXX.", "..X.."], 11, 0, PINK)
    elif name == "relaxed":  # closed eyes, small smile
        _face(s)
        _px(s, ["XX....XX"], 4, 7, INK); _px(s, ["X...X", ".XXX."], 6, 10, MOUTH)
    elif name == "proud":  # sunglasses + smirk
        _face(s)
        pygame.draw.rect(s, INK, (3, 5, 10, 1)); pygame.draw.rect(s, INK, (3, 6, 4, 2)); pygame.draw.rect(s, INK, (9, 6, 4, 2))
        s.set_at((4, 6), (120, 120, 160)); s.set_at((10, 6), (120, 120, 160))
        _px(s, ["....X", "XXXX."], 6, 10, MOUTH)
    elif name == "focused":  # bullseye
        for r, c in ((7, INK), (6, (255, 255, 255)), (5, (220, 40, 60)), (3, (255, 255, 255)), (2, (220, 40, 60))):
            pygame.draw.circle(s, c, (8, 8), r)
        pygame.draw.line(s, INK, (8, 8), (15, 1)); s.set_at((14, 1), (150, 100, 60))
    elif name == "curious":  # one big eye (monocle) + "?"
        _face(s); s.set_at((5, 6), INK); s.set_at((5, 7), INK)
        pygame.draw.circle(s, INK, (10, 7), 2, 1); s.set_at((10, 7), INK)
        _px(s, ["XXX"], 6, 11, MOUTH)
        _px(s, ["XX", "..X", ".X", "", ".X"], 13, 0, (160, 90, 230))
    elif name == "bored":  # half-closed eyes, flat mouth
        _face(s)
        _px(s, ["XXX..XXX", ".X....X."], 3, 6, INK); _px(s, ["XXXX"], 6, 11, MOUTH)
    elif name == "tired":  # closed eyes, open mouth, Zzz
        _face(s)
        _px(s, ["XX...XX"], 3, 7, INK); pygame.draw.rect(s, MOUTH, (6, 10, 3, 3))
        _px(s, ["XXX", "..X", ".X.", "XXX"], 12, 0, DROP)
    elif name == "don't know":  # shrug face with "?"s
        _face(s); dots(); _px(s, ["XXXX"], 6, 11, MOUTH)
        for x0, c in ((0, (160, 90, 230)), (13, PINK)):
            _px(s, ["XX", "..X", ".X", "", ".X"], x0, 0, c)
    elif name == "anxious":  # wide eyes, wavy mouth, sweat drop
        _face(s)
        for x in (4, 9):
            pygame.draw.rect(s, (255, 255, 255), (x, 5, 3, 3)); s.set_at((x + 1, 6), INK)
        _px(s, [".X.X.", "X.X.X"], 5, 10, MOUTH)
        _px(s, [".X", "XX", "XX"], 13, 3, TEAR)
    elif name == "stressed":  # spiral eyes, jagged mouth, sweat
        _face(s, (255, 190, 120))
        for x in (5, 10):
            _px(s, ["XXX", "X.X", "X.."], x - 1, 5, INK)
        _px(s, ["X.X.X", ".X.X."], 5, 10, MOUTH)
        _px(s, [".X", "XX"], 1, 3, TEAR); _px(s, [".X", "XX"], 14, 5, TEAR)
    elif name == "angry":  # red face, brows
        _face(s, RED_FACE)
        _px(s, ["XX....XX", "..X..X.."], 3, 4, INK); dots(7)
        _px(s, [".XXXX.", "X....X"], 5, 10, MOUTH)
    elif name == "sad":  # frown + tear
        _face(s); dots()
        _px(s, ["..XXX..", ".X...X.", "X.....X"], 4, 10, MOUTH)
        _px(s, ["X", "X", "XX"], 4, 8, TEAR)
    else:
        _face(s, (200, 200, 220))
        _px(s, [".XXX.", "X...X", "...X.", "..X..", ".....", "..X.."], 6, 4, INK)
    return s


def emotion_icon(name, size=32):
    return _cached(("emotion", name, size), lambda: pygame.transform.scale(_emotion_icon(name), (size, size)))


def _merz_menu_icon(size):
    s = _canvas(size)
    m = merz_sprite(size)
    s.blit(m, m.get_rect(center=(size // 2, size // 2)))
    return s


def moon_phase(lunation, size):
    def make():
        s = _canvas(32)
        pygame.draw.circle(s, INK, (16, 16), 13)
        pygame.draw.circle(s, (255, 236, 160), (16, 16), 12)
        if lunation >= 0.5:
            off = int(24 * (1 - 2 * (lunation - 0.5)))
        else:
            off = -int(24 * (1 - 2 * lunation))
        dark = _canvas(32)
        pygame.draw.circle(dark, (60, 44, 90), (16, 16), 12)
        pygame.draw.circle(dark, (0, 0, 0, 0), (16 - off, 16), 12)
        s.blit(dark, (0, 0))
        s.set_at((12, 13), (220, 200, 130)); s.set_at((14, 20), (220, 200, 130))
        return pygame.transform.scale(s, (size, size))
    return _cached(("moon", round(lunation, 2), size), make)


def moon_name(lunation):
    if lunation < 0.03 or lunation > 0.97:
        return "Neumond"
    if abs(lunation - 0.5) < 0.03:
        return "Vollmond"
    return "zunehmend" if lunation < 0.5 else "abnehmend"
