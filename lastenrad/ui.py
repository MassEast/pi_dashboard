# -*- coding: utf-8 -*-
"""SNES-JRPG style UI bits: navy windows with a light frame, chunky
buttons, outlined text, the rotate arrows, the dialog box with Lef's
portrait (spec §18, §26/27). All composed surfaces are cached."""

import math

import pygame

from . import sprites as S

NAVY_TOP = (44, 52, 142)
NAVY_LOW = (18, 20, 70)
FRAME = (236, 236, 255)
FRAME_SH = (120, 124, 190)
INK = (16, 10, 28)
GOLD = (255, 214, 72)
PINK = (255, 130, 200)
MINT = (110, 236, 170)
WHITE = (255, 255, 255)
DIM = (176, 180, 226)

_CACHE = {}


def _cached(key, make):
    if key not in _CACHE:
        if len(_CACHE) > 400:
            _CACHE.clear()
        _CACHE[key] = make()
    return _CACHE[key]


def box(surf, rect, pressed=False, tint=None):
    """A JRPG window (gradient fill, double frame)."""
    rect = pygame.Rect(rect)

    def make():
        s = pygame.Surface(rect.size, pygame.SRCALPHA)
        top, low = (tint or NAVY_TOP), (S.shade(tint, 0.45) if tint else NAVY_LOW)
        if pressed:
            top, low = low, top
        for y in range(rect.h):
            t = y / max(1, rect.h - 1)
            pygame.draw.line(s, tuple(int(top[i] + (low[i] - top[i]) * t) for i in range(3)), (0, y), (rect.w, y))
        pygame.draw.rect(s, INK, s.get_rect(), 2, border_radius=6)
        pygame.draw.rect(s, FRAME, s.get_rect().inflate(-4, -4), 2, border_radius=5)
        pygame.draw.rect(s, FRAME_SH, s.get_rect().inflate(-8, -8), 1, border_radius=4)
        return s
    surf.blit(_cached(("box", rect.size, pressed, tint), make), rect)
    return rect


def text(surf, fonts, s, size, color, bold=True, outline=True, **pos):
    """Text with a 1-2 px dark outline (readable over the park)."""
    def make():
        f = fonts.get(size, bold)
        inner = f.render(s, True, color)
        if not outline:
            return inner
        o = 2 if size >= 20 else 1
        dark = f.render(s, True, INK)
        img = pygame.Surface((inner.get_width() + 2 * o, inner.get_height() + 2 * o), pygame.SRCALPHA)
        for dx in (-o, 0, o):
            for dy in (-o, 0, o):
                if dx or dy:
                    img.blit(dark, (o + dx, o + dy))
        img.blit(inner, (o, o))
        return img
    img = _cached(("t", s, size, color, bold, outline), make)
    r = img.get_rect(**pos)
    surf.blit(img, r)
    return r


def fit(fonts, s, size, max_w, bold=True, min_size=11):
    while size > min_size and fonts.get(size, bold).size(s)[0] > max_w:
        size -= 1
    return size


def wrap(fonts, s, size, max_w, bold=True):
    f = fonts.get(size, bold)
    lines, line = [], ""
    for word in s.split():
        cand = f"{line} {word}".strip()
        if line and f.size(cand)[0] > max_w:
            lines.append(line)
            line = word
        else:
            line = cand
    if line:
        lines.append(line)
    return lines


def button(surf, fonts, rect, label, sub=None, size=24, enabled=True, tint=None, pressed=False):
    rect = box(surf, rect, pressed=pressed, tint=tint)
    col = WHITE if enabled else (130, 130, 170)
    if sub:
        text(surf, fonts, label, fit(fonts, label, size, rect.w - 24), col, center=(rect.centerx, rect.centery - 10))
        text(surf, fonts, sub, fit(fonts, sub, 14, rect.w - 24, bold=False), GOLD if enabled else DIM, bold=False,
             center=(rect.centerx, rect.centery + 17))
    else:
        text(surf, fonts, label, fit(fonts, label, size, rect.w - 16), col, center=rect.center)
    return rect


def rotate_arrow(surf, rect, direction, active=False):
    """Hold-to-rotate button: a round arrow (direction +1 = counter-clockwise)."""
    rect = box(surf, rect, pressed=active)
    cx, cy = rect.center
    r = min(rect.w, rect.h) // 2 - 10
    col = GOLD if active else WHITE
    a0, a1 = -0.9, 3.5  # counter-clockwise arc, mirrored for clockwise
    pts = [(math.cos(a0 + (a1 - a0) * k / 14) * r, -math.sin(a0 + (a1 - a0) * k / 14) * r) for k in range(15)]
    ex, ey = pts[-1]
    tx, ty = -math.sin(a1), -math.cos(a1)  # direction of travel at the end
    nx, ny = math.cos(a1), -math.sin(a1)
    head = [(ex + tx * 9, ey + ty * 9), (ex + nx * 7, ey + ny * 7), (ex - nx * 7, ey - ny * 7)]
    m = 1 if direction > 0 else -1
    pts = [(cx + m * x, cy + y) for x, y in pts]
    head = [(cx + m * x, cy + y) for x, y in head]
    pygame.draw.lines(surf, INK, False, pts, 7)
    pygame.draw.polygon(surf, INK, head)
    pygame.draw.lines(surf, col, False, pts, 3)
    pygame.draw.polygon(surf, col, [((x - cx) * 0.7 + cx + (head[0][0] - cx) * 0.3, (y - cy) * 0.7 + cy + (head[0][1] - cy) * 0.3)
                                    for x, y in head])
    return rect


def dialog_box(surf, fonts, rect, speaker, line, hint=None):
    """JRPG dialog: portrait left, name, 1-2 lines (spec §27)."""
    rect = box(surf, rect)
    pr = S.lef_portrait(rect.h - 20)
    surf.blit(pr, (rect.x + 10, rect.y + 10))
    tx = rect.x + 20 + pr.get_width()
    text(surf, fonts, speaker, 16, GOLD, topleft=(tx, rect.y + 10))
    for i, ln in enumerate(wrap(fonts, line, 17, rect.right - tx - 12)[:3]):
        text(surf, fonts, ln, 17, WHITE, bold=False, topleft=(tx, rect.y + 32 + i * 21))
    if hint:
        text(surf, fonts, hint, 13, DIM, bold=False, bottomright=(rect.right - 12, rect.bottom - 6))
    return rect
