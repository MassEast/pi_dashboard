# -*- coding: utf-8 -*-
"""Pixel art, drawn in code (no asset files): items, the bike, Lef, his
portrait, wheels, birds, the menu icon.

Every item sprite is painted at half resolution ("art pixels" of 2 world
units) and scaled up nearest-neighbour for the chunky 16-bit look. Its
silhouette is filled from the item's collision shapes and everything else is
clipped to it, then a 1-art-px dark outline is traced around it - so the
picture always shows exactly what collides (spec §3, §17).
"""

import math

import pygame

from .items import ITEMS_BY_ID

OUT = (24, 16, 30)  # outline ink
_CACHE = {}


def _cached(key, make):
    if key not in _CACHE:
        _CACHE[key] = make()
    return _CACHE[key]


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


class Canvas:
    """Half-resolution drawing surface in item-local units (y up)."""

    def __init__(self, bbox, art=2):
        minx, miny, maxx, maxy = bbox
        self.art = art
        self.minx = math.floor(minx / art) * art - art
        self.maxy = math.ceil(maxy / art) * art + art
        self.w = int((math.ceil(maxx / art) * art + art - self.minx) / art)
        self.h = int((self.maxy - (math.floor(miny / art) * art - art)) / art)
        self.surf = pygame.Surface((self.w, self.h), pygame.SRCALPHA)

    def pt(self, x, y):
        return (x - self.minx) / self.art, (self.maxy - y) / self.art

    def rect(self, x0, y0, x1, y1, c):
        ax, ay = self.pt(min(x0, x1), max(y0, y1))
        bx, by = self.pt(max(x0, x1), min(y0, y1))
        pygame.draw.rect(self.surf, c, (round(ax), round(ay), max(1, round(bx - ax)), max(1, round(by - ay))))

    def poly(self, pts, c, width=0):
        pygame.draw.polygon(self.surf, c, [self.pt(x, y) for x, y in pts], width)

    def circle(self, x, y, r, c, width=0):
        pygame.draw.circle(self.surf, c, [round(v) for v in self.pt(x, y)], max(1, round(r / self.art)), width)

    def line(self, x0, y0, x1, y1, c, width=1):
        pygame.draw.line(self.surf, c, self.pt(x0, y0), self.pt(x1, y1), width)

    def px(self, x, y, c):
        ax, ay = self.pt(x, y)
        if 0 <= ax < self.w and 0 <= ay < self.h:
            self.surf.set_at((int(ax), int(ay)), c)

    def shape(self, spec, c):
        kind = spec[0]
        if kind == "box":
            _, w, h, cx, cy = spec[:5]
            r = spec[5] if len(spec) > 5 else 0
            ax, ay = self.pt(cx - w / 2, cy + h / 2)
            pygame.draw.rect(self.surf, c, (round(ax), round(ay), round(w / self.art), round(h / self.art)),
                             border_radius=round(r / self.art))
        elif kind == "circle":
            _, r, cx, cy = spec
            self.circle(cx, cy, r, c)
        elif kind == "capsule":
            _, length, t, cx, cy = spec
            ax, ay = self.pt(cx - length / 2, cy + t / 2)
            pygame.draw.rect(self.surf, c, (round(ax), round(ay), round(length / self.art), round(t / self.art)),
                             border_radius=round(t / 2 / self.art))
        elif kind == "seg":
            _, x1, y1, x2, y2, r = spec
            self.line(x1, y1, x2, y2, c, max(1, round(2 * r / self.art)))
            self.circle(x1, y1, r, c)
            self.circle(x2, y2, r, c)
        else:
            self.poly(spec[1], c)

    def finish(self, clip_shapes=None, outline=OUT):
        """Clip to the silhouette, outline, scale up. Returns (surface,
        local centre of the surface)."""
        s = self.surf
        if clip_shapes is not None:
            sil = pygame.Surface(s.get_size(), pygame.SRCALPHA)
            keep = self.surf
            self.surf = sil
            for spec in clip_shapes:
                self.shape(spec, (255, 255, 255, 255))
            self.surf = keep
            s.blit(sil, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        if outline is not None:
            m = pygame.mask.from_surface(s, 8)
            inner = m.copy()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                inner = inner.overlap_mask(m, (dx, dy))
            edge = m.copy()
            edge.erase(inner, (0, 0))
            s.blit(edge.to_surface(setcolor=outline, unsetcolor=(0, 0, 0, 0)), (0, 0))
        big = pygame.transform.scale(s, (s.get_width() * self.art, s.get_height() * self.art))
        cx = self.minx + self.w * self.art / 2
        cy = self.maxy - self.h * self.art / 2
        return big, (cx, cy)


# ------------------------------------------------------------ item painters (details on top of the base fill)
def _bassbox(c):
    c.rect(-40, -50, 40, 50, (52, 52, 60))
    c.circle(0, -16, 32, (90, 90, 104))
    c.circle(0, -16, 28, (26, 26, 32))
    c.circle(0, -16, 21, (64, 64, 76))
    c.circle(0, -16, 8, (130, 130, 146))
    c.circle(-3, -13, 3, (190, 190, 200))
    c.circle(0, 34, 12, (90, 90, 104))
    c.circle(0, 34, 8, (30, 30, 36))
    c.circle(-2, 36, 3, (160, 160, 175))
    for x in (-46, 38):
        for y in (-56, 48):
            c.rect(x, y, x + 8, y + 8, (170, 170, 182))
    c.rect(-34, 20, -14, 26, (255, 110, 190))  # sticker
    c.rect(18, 46, 34, 50, (90, 230, 160))


def _flightcase(c):
    c.rect(-68, 26, 68, 32, (46, 46, 52))
    c.rect(-68, -32, 68, -26, (46, 46, 52))
    c.rect(-68, -2, 68, 2, (120, 122, 130))
    for x in (-68, 56):
        for y in (-32, 20):
            c.rect(x, y, x + 12, y + 12, (215, 215, 222))
    for x in (-46, 32):
        c.rect(x, -8, x + 14, 6, (86, 86, 94))
        c.rect(x + 4, -4, x + 10, 2, (200, 200, 205))
    c.rect(-16, 14, 16, 20, (40, 40, 44))
    for i, col in enumerate([(230, 50, 60), (250, 150, 40), (250, 220, 40), (60, 170, 90), (60, 110, 230), (150, 70, 200)]):
        c.rect(24, -20 + i * 2, 50, -18 + i * 2, col)


def _matekiste(c):
    for y in (-22, -6, 10):
        c.rect(-52, y, 52, y + 3, (196, 100, 18))
    c.rect(-20, 18, 20, 26, (120, 56, 8))
    c.rect(-52, 28, 52, 33, (250, 170, 70))
    c.circle(-28, -14, 9, (40, 70, 160))
    c.circle(-28, -14, 5, (250, 220, 90))
    for x in (12, 26, 40):
        c.rect(x, -26, x + 6, -2, (160, 80, 10))


def _powerbank(c):
    c.rect(-37, 16, 37, 22, (70, 96, 160))
    for i in range(4):
        c.rect(-28 + i * 8, 4, -24 + i * 8, 8, (90, 255, 140) if i < 3 else (40, 70, 60))
    c.poly([(8, 12), (16, 12), (10, 0), (18, 0), (4, -16), (8, -4), (0, -4)], (255, 214, 60))
    c.rect(28, -10, 34, -2, (20, 20, 30))
    c.rect(28, -18, 34, -14, (20, 20, 30))


def _tasche(c):
    c.rect(-62, 20, 62, 29, (90, 112, 60))
    for x in range(-50, 52, 8):
        c.rect(x, 22, x + 4, 24, (200, 200, 190))
    c.line(-40, 29, -26, 40, (60, 40, 30), 2)
    c.line(40, 29, 26, 40, (60, 40, 30), 2)
    c.rect(-40, -20, -6, 8, (110, 136, 74))
    c.rect(-40, 4, -6, 8, (80, 100, 52))
    c.circle(26, -6, 8, (255, 120, 190))
    c.rect(-62, -29, 62, -24, (70, 88, 46))


def _snackkiste(c):
    c.rect(-6, -31, 6, 31, (232, 212, 150))
    c.circle(-26, -4, 12, (220, 50, 50))
    c.circle(-26, -4, 7, (255, 210, 60))
    c.rect(18, -16, 40, 4, (250, 240, 220))
    c.rect(22, -12, 36, 0, (60, 160, 220))
    c.rect(-48, 26, 48, 31, (220, 182, 120))


def _lichtkoffer(c):
    c.rect(-58, 20, 58, 26, (60, 60, 66))
    c.rect(-58, -26, 58, -20, (60, 60, 66))
    for i, col in enumerate([(255, 60, 80), (80, 255, 120), (80, 140, 255), (255, 220, 60)]):
        c.circle(-30 + i * 16, 0, 5, col)
        c.px(-31 + i * 16, 2, (255, 255, 255))
    c.rect(30, -10, 50, 10, (250, 200, 0))
    c.poly([(30, -10), (40, -10), (30, 0)], (30, 30, 34))
    c.poly([(40, 10), (50, 10), (50, 0)], (30, 30, 34))


def _klapptisch(c):
    c.rect(-84, 31, 84, 35, (226, 190, 130))
    c.rect(-84, 23, 84, 25, (150, 110, 60))
    for x in (-72, 72):
        c.rect(x - 1, -35, x + 1, 23, (190, 190, 200))


def _decke(c):
    for i in range(-63, 63, 14):
        c.rect(i, -22, i + 7, 22, (226, 206, 160))
    c.rect(-34, -22, -26, 22, (80, 50, 40))
    c.rect(26, -22, 34, 22, (80, 50, 40))
    c.circle(52, 0, 14, (170, 60, 60))
    c.circle(52, 0, 8, (226, 206, 160))
    c.circle(52, 0, 3, (120, 40, 40))


def _pfandsack(c):
    for x, y, col in ((-22, -12, (60, 140, 70)), (0, -20, (130, 80, 40)), (20, -8, (60, 140, 70)), (-8, 8, (90, 170, 90))):
        c.rect(x - 7, y - 16, x + 7, y + 14, col)
        c.rect(x - 3, y + 14, x + 3, y + 22, col)
        c.rect(x - 4, y + 21, x + 4, y + 24, (240, 210, 60))
    c.rect(-12, 32, 12, 42, (160, 175, 200))
    c.line(-10, 34, 10, 40, (120, 130, 160), 1)
    c.rect(-40, 12, -30, 24, (240, 248, 255))


def _poitasche(c):
    c.rect(-31, 4, 31, 8, (255, 80, 200))
    c.rect(-31, -6, 31, -3, (120, 255, 120))
    c.circle(-14, 16, 6, (255, 150, 30))
    c.circle(10, 16, 6, (255, 150, 30))


def _kabelrolle(c):
    c.circle(0, 0, 34, (200, 92, 30))
    c.circle(0, 0, 28, (26, 26, 30))
    for r in (24, 19, 14):
        c.circle(0, 0, r, (60, 60, 70), 1)
    c.circle(0, 0, 9, (150, 150, 160))
    for a in (0, 2.1, 4.2):
        c.circle(math.cos(a) * 5, math.sin(a) * 5, 1.5, (60, 60, 70))
    c.rect(22, -6, 34, 6, (250, 210, 50))  # handle: shows the spin
    c.rect(-10, 26, 10, 32, (255, 120, 190))


def _isomatte(c):
    c.circle(0, 0, 27, (60, 150, 210))
    for r, off in ((21, 2), (15, 4), (9, 3)):
        c.circle(off, 0, r, (30, 90, 150), 1)
    c.rect(-4, -27, 4, 27, (220, 80, 60))


def _discokugel(c):
    cols = [(232, 232, 240), (176, 176, 196), (252, 252, 255), (140, 140, 165)]
    for i, y in enumerate(range(-26, 26, 6)):
        for j, x in enumerate(range(-26, 26, 6)):
            c.rect(x, y, x + 6, y + 6, cols[(i + j * 2) % 4])
    for x, y, col in ((-10, 12, (255, 120, 200)), (8, -6, (120, 220, 255)), (14, 14, (255, 240, 120))):
        c.rect(x, y, x + 4, y + 4, col)
    c.circle(-10, 12, 5, (255, 255, 255))


def _kabeltrommel(c):
    c.circle(0, 0, 48, (176, 124, 70))
    c.circle(0, 0, 41, (30, 30, 34))
    for r in (36, 31, 26, 21):
        c.circle(0, 0, r, (66, 66, 76), 1)
    c.circle(0, 0, 14, (196, 146, 90))
    for a in range(6):
        c.circle(math.cos(a) * 9, math.sin(a) * 9, 2, (90, 60, 30))
    c.rect(-6, 34, 6, 46, (250, 210, 40))
    c.rect(32, -6, 48, 6, (120, 80, 40))


def _dragonstaff(c):
    c.rect(-115, -7, 115, 7, (70, 50, 40))
    c.rect(-24, -7, 24, 7, (230, 70, 120))
    for x in range(-24, 24, 6):
        c.rect(x, -7, x + 2, 7, (40, 20, 40))
    for side in (-1, 1):
        for i in range(5):
            x = side * (88 + i * 5)
            c.rect(x - 2, -7, x + 2, 7, (90, 90, 96) if i % 2 else (50, 50, 56))
        c.px(side * 112, 3, (255, 150, 40))


def _teppich(c):
    c.rect(-125, -15, 125, 15, (150, 40, 54))
    for x in range(-110, 100, 20):
        c.poly([(x, -4), (x + 10, 6), (x + 20, -4), (x + 20, 0), (x + 10, 10), (x, 0)], (230, 180, 60))
    c.rect(-125, -15, 125, -11, (110, 26, 40))
    c.circle(112, 0, 13, (190, 70, 70))
    c.circle(112, 0, 7, (110, 26, 40))
    c.circle(112, 0, 2, (230, 180, 60))


def _staender(c):
    c.rect(-2, -40, 2, 70, (220, 220, 230))
    c.rect(-5, 30, 5, 38, (40, 40, 46))
    c.rect(-5, 64, 5, 70, (90, 90, 96))


def _stehlampe(c):
    c.rect(-2, -66, 2, 54, (210, 176, 80))
    c.rect(-32, 54, 32, 60, (220, 190, 130))
    for x in range(-28, 30, 8):
        c.rect(x, 54, x + 3, 57, (200, 120, 60))
    c.rect(-14, 74, 14, 80, (255, 248, 210))


def _stuhl(c):
    for y in (8, 24, 40, 56):
        c.rect(-29, y, -21, y + 2, (120, 70, 36))
    c.rect(-29, 1, 29, 3, (196, 130, 80))


def _pflanze(c):
    c.rect(-30, -16, 30, -10, (220, 120, 80))
    c.rect(-24, -36, 24, -32, (160, 70, 44))
    for x, y in ((-30, 24), (0, 34), (28, 20), (-14, 6), (16, 0)):
        c.circle(x, y, 13, (90, 180, 90))
        c.line(x - 8, y + 6, x + 6, y - 6, (30, 100, 50), 1)
        c.px(x + 4, y + 6, (40, 120, 60))
    c.rect(-2, -10, 2, 10, (40, 120, 60))


def _skateboard(c):
    c.rect(-62, 6, 62, 10, (40, 40, 44))
    c.rect(-50, 0, 50, 6, (240, 90, 170))
    c.rect(-20, 0, 20, 6, (255, 220, 60))


def _einkaufswagen(c):
    c.poly([(-50, -16), (56, -16), (70, 52), (-60, 52)], (206, 216, 226))
    for x in range(-56, 70, 10):
        c.line(x, -16, x + 6, 52, (130, 140, 156), 1)
    for y in range(-10, 52, 10):
        c.line(-62, y, 70, y, (130, 140, 156), 1)
    c.rect(-60, 46, 70, 52, (170, 180, 192))
    c.poly([(-62, 44), (-55, 44), (-74, 76), (-81, 76)], (210, 40, 40))
    c.rect(-50, -16, 56, -12, (150, 160, 172))


def _flamingo(c):
    c.poly([(-50, -30), (34, -30), (50, -16), (42, -2), (-40, -2), (-54, -16)], (255, 170, 210))
    c.rect(-30, -24, 20, -12, (255, 210, 230))
    c.circle(52, 60, 3, (30, 20, 30))
    c.poly([(56, 56), (64, 50), (58, 46)], (40, 30, 40))
    c.line(38, 0, 52, 46, (255, 150, 196), 2)


def _pfeffi(c):
    c.rect(-42, -19, 42, -2, (40, 140, 80))
    for i in range(6):
        x = -36 + i * 14
        c.rect(x, -2, x + 8, 12, (150, 230, 180))
        c.rect(x + 2, 12, x + 6, 19, (220, 220, 220))
    c.rect(-30, -14, 30, -8, (240, 250, 240))


def _trophaee(c):
    c.poly([(-16, 8), (16, 8), (30, 52), (-30, 52)], (240, 200, 60))
    c.rect(-22, 40, -14, 50, (255, 250, 200))
    c.rect(-23, -26, 23, -12, (70, 46, 30))
    c.rect(-10, -20, 10, -16, (220, 200, 120))
    c.circle(0, 30, 6, (255, 120, 190))


def _sofa(c):
    c.rect(-106, -46, 106, -2, (190, 150, 60))
    c.rect(-86, -2, 86, 38, (170, 128, 46))
    for x in range(-96, 100, 18):
        for y in (-34, -16, 10, 26):
            c.circle(x + (9 if y % 4 else 0), y, 3, (120, 70, 40))
    c.rect(-1, -2, 1, 38, (130, 92, 30))
    c.rect(-106, -46, 106, -40, (120, 80, 30))


def _lastenrad2(c):
    c.rect(-34, 34, -18, 40, (120, 70, 40))
    c.circle(-12, 4, 4, (255, 110, 190))
    c.circle(18, 10, 4, (90, 230, 160))


def _elefant(c):
    c.poly([(-92, -12), (74, -12), (94, 26), (70, 58), (-70, 58), (-98, 26)], (156, 156, 172))
    for x in (-60, -30, 0, 30):
        c.line(x, 0, x + 10, 30, (120, 120, 140), 1)
    c.poly([(74, 14), (96, 20), (96, 50), (80, 56)], (120, 120, 140))
    c.circle(104, 46, 3, (20, 20, 30))
    c.line(108, 26, 120, 12, (250, 250, 240), 2)
    for x in (-62, 46):
        for t in (-10, 0, 10):
            c.px(x + t, -54, (230, 230, 230))
    c.circle(-40, 40, 6, (255, 120, 190))  # Glitzer-Sticker, someone was here first


def _raver(c):
    c.rect(-15, -17, 15, 33, (30, 30, 36))
    c.poly([(-8, 20), (8, 20), (0, 6)], (90, 255, 160))
    c.circle(0, 48, 15, (232, 182, 140))
    c.rect(-15, 54, 15, 63, (255, 120, 200))
    c.rect(-10, 46, 10, 50, (20, 20, 24))


def _raver_legs(c):
    c.rect(-11, -71, 11, -13, (70, 90, 150))
    c.rect(-11, -71, 11, -64, (30, 30, 30))
    c.rect(-1, -60, 1, -13, (50, 66, 120))


def _raver_arm(c):
    c.rect(1, -16, 11, 28, (30, 30, 36))
    c.rect(1, -16, 11, -6, (232, 182, 140))


ITEM_ART = {  # sprite key -> (base colour, painter)
    "bassbox": ((40, 40, 46), _bassbox),
    "flightcase": ((176, 178, 186), _flightcase),
    "matekiste": ((232, 132, 32), _matekiste),
    "powerbank": ((44, 64, 116), _powerbank),
    "tasche": ((100, 124, 66), _tasche),
    "snackkiste": ((204, 164, 104), _snackkiste),
    "lichtkoffer": ((34, 34, 40), _lichtkoffer),
    "klapptisch": ((200, 160, 100), _klapptisch),
    "decke": ((190, 64, 64), _decke),
    "pfandsack": ((206, 220, 236), _pfandsack),
    "poitasche": ((30, 30, 36), _poitasche),
    "kabelrolle": ((200, 92, 30), _kabelrolle),
    "isomatte": ((60, 150, 210), _isomatte),
    "discokugel": ((200, 200, 215), _discokugel),
    "kabeltrommel": ((176, 124, 70), _kabeltrommel),
    "dragonstaff": ((70, 50, 40), _dragonstaff),
    "teppich": ((150, 40, 54), _teppich),
    "staender": ((60, 60, 68), _staender),
    "stehlampe": ((50, 46, 44), _stehlampe),
    "stuhl": ((156, 96, 54), _stuhl),
    "pflanze": ((200, 100, 66), _pflanze),
    "skateboard": ((240, 90, 170), _skateboard),
    "einkaufswagen": ((150, 160, 172), _einkaufswagen),
    "flamingo": ((255, 140, 190), _flamingo),
    "pfeffi": ((40, 140, 80), _pfeffi),
    "trophaee": ((240, 200, 60), _trophaee),
    "sofa": ((190, 150, 60), _sofa),
    "lastenrad2": ((26, 26, 30), _lastenrad2),
    "elefant": ((156, 156, 172), _elefant),
    "raver": ((30, 30, 36), _raver),
    "raver_legs": ((70, 90, 150), _raver_legs),
    "raver_arm": ((30, 30, 36), _raver_arm),
}


def _paint(shapes, art_key):
    from .items import shape_bbox
    boxes = [shape_bbox(s) for s in shapes]
    bb = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    c = Canvas(bb)
    base, painter = ITEM_ART.get(art_key, ((200, 80, 200), None))
    for s in shapes:
        c.shape(s, base)
    if painter is not None:
        painter(c)
    return c.finish(clip_shapes=shapes)


def item_sprite(defn):
    """(surface at zoom 1, local centre) of an item's main body."""
    return _cached(("item", defn["id"]), lambda: _paint(defn["shapes"], defn["sprite"]))


def part_sprite(defn, index):
    """(surface, local centre in the part body's frame) of a wheel/limb."""
    part = defn["parts"][index]

    def make():
        if part["kind"] == "wheel":
            return wheel_sprite(part["r"], light=defn["id"] == "skateboard")
        ax, ay = part["at"]
        shapes = [_shift(s, -ax, -ay) for s in part["shapes"]]
        return _paint(shapes, part["sprite"])
    return _cached(("part", defn["id"], index), make)


def _shift(spec, dx, dy):
    kind = spec[0]
    if kind in ("box", "circle", "capsule"):
        out = list(spec)
        i = 3 if kind != "circle" else 2
        out[i] += dx
        out[i + 1] += dy
        return tuple(out)
    if kind == "seg":
        _, x1, y1, x2, y2, r = spec
        return ("seg", x1 + dx, y1 + dy, x2 + dx, y2 + dy, r)
    return ("poly", [(x + dx, y + dy) for x, y in spec[1]])


def wheel_sprite(r, light=False):
    def make():
        c = Canvas((-r, -r, r, r))
        c.circle(0, 0, r, (240, 232, 200) if light else (30, 30, 34))
        if r > 12:
            c.circle(0, 0, r - 4, (160, 160, 172), 1)
            for a in range(4):
                ang = a * math.pi / 4
                c.line(-math.cos(ang) * (r - 4), -math.sin(ang) * (r - 4), math.cos(ang) * (r - 4), math.sin(ang) * (r - 4),
                       (120, 120, 130), 1)
        c.circle(0, 0, max(2, r // 3), (180, 180, 190) if not light else (90, 90, 96))
        c.rect(-1, r * 0.4, 1, r * 0.8, (255, 120, 190))  # valve/sticker: shows the spin
        return c.finish()
    return _cached(("wheel", r, light), make)


def item_icon(defn, box_w, box_h):
    """Whole item (incl. parts at rest) fitted into a box, nearest-neighbour."""
    def make():
        minx, miny, maxx, maxy = defn["bbox"]
        c = Canvas((minx, miny, maxx, maxy))
        s = pygame.Surface((c.w * 2, c.h * 2), pygame.SRCALPHA)
        img, (lx, ly) = item_sprite(defn)
        s.blit(img, img.get_rect(center=(lx - c.minx, c.maxy - ly)))
        for i, part in enumerate(defn.get("parts", ())):
            pimg, (plx, ply) = part_sprite(defn, i)
            ax, ay = part["at"]
            s.blit(pimg, pimg.get_rect(center=(ax + plx - c.minx, c.maxy - (ay + ply))))
        k = min(box_w / s.get_width(), box_h / s.get_height(), 1.0)
        return pygame.transform.scale(s, (max(1, int(s.get_width() * k)), max(1, int(s.get_height() * k))))
    return _cached(("icon", defn["id"], box_w, box_h), make)


# ------------------------------------------------------------ the bike
BIKE_BLACK = (28, 26, 32)
BIKE_HI = (70, 66, 80)


def bike_sprite():
    """The black DIY Lastenrad, exactly from the side, flat open deck in front
    (spec §4). Local frame = the bike body (kickstand foot at 0, 0)."""
    from . import config as C

    def make():
        c = Canvas((-236, -4, 152, 150))
        half = C.DECK_LEN / 2
        top, th = C.DECK_TOP, C.DECK_THICK
        rx, ry, rr = C.REAR_WHEEL
        fx, fy, fr = C.FRONT_WHEEL
        ry += C.WHEEL_LIFT
        fy += C.WHEEL_LIFT
        for (x, y, r) in ((rx, ry, rr), (fx, fy, fr)):
            c.circle(x, y, r, BIKE_BLACK)
            c.circle(x, y, r - 4, (96, 96, 108))
            c.circle(x, y, r - 6, (0, 0, 0, 0))
            for a in range(6):
                ang = a * math.pi / 6
                c.line(x - math.cos(ang) * (r - 6), y - math.sin(ang) * (r - 6), x + math.cos(ang) * (r - 6),
                       y + math.sin(ang) * (r - 6), (150, 150, 160), 1)
            c.circle(x, y, 4, (180, 180, 190))
        # frame: rear triangle, seat tube, long low beam to the head tube, deck rails
        hx = -half - 10  # head tube x (behind the deck)
        tubes = [
            ((rx, ry), (-170, 36)),  # chain stay
            ((rx, ry), (-186, 116)),  # seat stay
            ((-170, 36), (-186, 116)),  # seat tube
            ((-170, 36), (hx, 52)),  # down tube to the head
            ((-186, 112), (hx - 6, 116)),  # top tube
            ((hx, 52), (hx - 8, 128)),  # head tube / steerer, leaning back: nothing hangs over the deck
            ((hx, 52), (-half, top - th)),  # into the deck rails
            ((fx, fy), (fx - 10, top - th)),  # front fork
            ((-half + 10, top - th), (fx - 10, top - th)),  # rail under the deck
        ]
        for (x0, y0), (x1, y1) in tubes:
            c.line(x0, y0, x1, y1, BIKE_BLACK, 4)
        for (x0, y0), (x1, y1) in tubes[:5]:
            c.line(x0, y0 + 2, x1, y1 + 2, BIKE_HI, 1)
        c.line(fx - 10, top - th, fx + 10, top - th - 2, BIKE_BLACK, 3)
        # crank, chain, pedal
        c.circle(-170, 36, 9, BIKE_BLACK)
        c.circle(-170, 36, 5, (110, 110, 120))
        c.line(rx, ry + 3, -170, 44, (90, 90, 100), 1)
        c.line(rx, ry - 3, -170, 28, (90, 90, 100), 1)
        c.line(-170, 36, -160, 22, BIKE_BLACK, 2)
        c.rect(-166, 18, -152, 22, (60, 60, 66))
        # saddle + post, handlebar
        c.line(-186, 112, -190, 128, BIKE_BLACK, 3)
        c.poly([(-212, 128), (-178, 130), (-176, 136), (-206, 136)], (60, 40, 32))
        c.line(hx - 8, 128, hx - 26, 136, BIKE_BLACK, 3)
        c.rect(hx - 36, 132, hx - 24, 140, (80, 60, 140))  # grip tape
        # kickstand: the pivot the whole bike rocks on
        c.line(-14, top - th, -4, 0, BIKE_BLACK, 3)
        c.line(14, top - th, 4, 0, BIKE_BLACK, 3)
        c.rect(-10, -2, 10, 2, (60, 60, 66))
        # deck: plywood with black edge, exactly the collision box
        c.rect(-half, top - th, half, top, (128, 92, 60))
        c.rect(-half, top - 3, half, top, (168, 128, 84))
        c.rect(-half, top - th, half, top - th + 2, BIKE_BLACK)
        for x in range(int(-half) + 30, int(half), 48):
            c.px(x, top - 6, (90, 64, 40))
        # stickers
        c.rect(-178, 70, -164, 80, (255, 110, 190))
        c.rect(-208, 64, -196, 72, (90, 230, 160))
        c.rect(hx - 4, 86, hx + 8, 94, (255, 214, 60))
        c.circle(-60, top - 6, 3, (120, 180, 255))
        # a lamp up front, a bell at the bar
        c.rect(fx - 4, top - th - 8, fx + 6, top - th - 2, (250, 230, 120))
        c.circle(hx - 16, 134, 3, (220, 220, 60))
        return c.finish()
    return _cached("bike", make)


# ------------------------------------------------------------ Lef (spec §5)
SKIN = (232, 180, 138)
SKIN_SH = (196, 140, 104)
HAIR = (104, 66, 38)
HAIR_HI = (146, 98, 54)
VEST = (92, 104, 58)
VEST_SH = (68, 78, 42)
SHIRT = (226, 88, 150)
PANTS = (150, 134, 94)
PANTS_SH = (116, 102, 70)
BOOTS = (62, 42, 32)


def lef_sprite():
    """Lef, front facing, broad build, short slightly curly brown hair, vest
    and cargo pants with stuffed pockets. 26 x 50 art px at 3 units."""
    def make():
        s = pygame.Surface((28, 52), pygame.SRCALPHA)
        r = lambda x, y, w, h, col: pygame.draw.rect(s, col, (x, y, w, h))
        # boots + legs
        r(7, 46, 6, 5, BOOTS); r(15, 46, 6, 5, BOOTS)
        r(7, 32, 14, 15, PANTS)
        r(13, 38, 2, 9, PANTS_SH)
        r(3, 34, 6, 7, PANTS); r(19, 34, 6, 7, PANTS)  # bulging side pockets
        r(3, 34, 6, 1, PANTS_SH); r(19, 34, 6, 1, PANTS_SH)
        r(4, 31, 2, 3, (90, 255, 140)); r(22, 32, 1, 2, (255, 90, 190))  # glowstick, cable end
        r(9, 41, 3, 3, PANTS_SH); r(16, 41, 3, 3, PANTS_SH)
        # torso: shirt, vest with pockets, belt
        r(5, 16, 18, 16, VEST)
        r(11, 16, 6, 15, SHIRT)
        r(13, 19, 2, 2, (255, 220, 90))
        r(6, 20, 4, 4, VEST_SH); r(18, 20, 4, 4, VEST_SH)
        r(6, 25, 4, 4, VEST_SH); r(18, 25, 4, 4, VEST_SH)
        r(7, 21, 2, 2, (200, 190, 120)); r(19, 26, 2, 2, (120, 200, 255))  # stuff sticking out
        r(6, 31, 16, 2, (40, 30, 26)); r(13, 31, 2, 2, (200, 180, 90))
        # arms
        r(1, 17, 4, 6, SHIRT); r(23, 17, 4, 6, SHIRT)
        r(1, 23, 4, 8, SKIN); r(23, 23, 4, 8, SKIN)
        r(1, 30, 4, 3, SKIN_SH); r(23, 30, 4, 3, SKIN_SH)
        r(2, 26, 3, 1, (60, 200, 255))  # wristband
        # head
        r(12, 14, 4, 3, SKIN_SH)
        r(8, 4, 12, 11, SKIN)
        r(7, 8, 1, 3, SKIN); r(20, 8, 1, 3, SKIN)
        r(10, 9, 2, 2, (40, 28, 30)); r(16, 9, 2, 2, (40, 28, 30))
        r(10, 8, 2, 1, HAIR); r(16, 8, 2, 1, HAIR)
        r(12, 12, 4, 1, (180, 100, 90))
        r(9, 13, 10, 2, (176, 130, 96))  # stubble
        # curly hair
        for x, y in ((8, 2), (10, 1), (13, 1), (16, 1), (19, 2), (7, 4), (20, 4), (9, 3), (12, 2), (15, 2), (18, 3)):
            r(x, y, 3, 3, HAIR)
        for x, y in ((10, 2), (14, 2), (18, 3), (8, 5)):
            r(x, y, 1, 1, HAIR_HI)
        m = pygame.mask.from_surface(s)
        out = pygame.Surface((30, 54), pygame.SRCALPHA)
        out.blit(m.to_surface(setcolor=OUT, unsetcolor=(0, 0, 0, 0)), (0, 1))
        out.blit(m.to_surface(setcolor=OUT, unsetcolor=(0, 0, 0, 0)), (2, 1))
        out.blit(m.to_surface(setcolor=OUT, unsetcolor=(0, 0, 0, 0)), (1, 0))
        out.blit(m.to_surface(setcolor=OUT, unsetcolor=(0, 0, 0, 0)), (1, 2))
        out.blit(s, (1, 1))
        return pygame.transform.scale(out, (90, 162))
    return _cached("lef", make)


def lef_riding_sprite():
    """Lef seen from the side on the saddle, for the ride into the sunset."""
    def make():
        s = pygame.Surface((22, 34), pygame.SRCALPHA)
        r = lambda x, y, w, h, col: pygame.draw.rect(s, col, (x, y, w, h))
        r(6, 0, 9, 4, HAIR); r(5, 2, 3, 4, HAIR); r(14, 1, 3, 2, HAIR_HI)
        r(7, 3, 9, 8, SKIN); r(14, 6, 2, 2, (40, 28, 30)); r(15, 9, 2, 1, (180, 100, 90))
        r(5, 11, 11, 11, VEST); r(13, 11, 3, 10, SHIRT)
        r(13, 13, 8, 3, SHIRT); r(19, 13, 3, 3, SKIN)  # arm to the bar
        r(5, 21, 12, 5, PANTS); r(4, 22, 4, 5, PANTS_SH)
        r(14, 24, 4, 8, PANTS); r(14, 31, 6, 3, BOOTS)
        out = pygame.Surface((24, 36), pygame.SRCALPHA)
        m = pygame.mask.from_surface(s)
        for d in ((0, 1), (2, 1), (1, 0), (1, 2)):
            out.blit(m.to_surface(setcolor=OUT, unsetcolor=(0, 0, 0, 0)), d)
        out.blit(s, (1, 1))
        return pygame.transform.scale(out, (72, 108))
    return _cached("lef_ride", make)


def lef_portrait(size=84):
    """JRPG dialog portrait (spec §26/27)."""
    def make():
        s = pygame.Surface((28, 28))
        s.fill((40, 34, 90))
        for y in range(0, 28, 2):
            pygame.draw.line(s, (52, 44, 110), (0, y), (27, y))
        r = lambda x, y, w, h, col: pygame.draw.rect(s, col, (x, y, w, h))
        r(3, 21, 22, 7, VEST); r(11, 21, 6, 7, SHIRT); r(5, 23, 4, 3, VEST_SH); r(19, 23, 4, 3, VEST_SH)
        r(11, 18, 6, 4, SKIN_SH)
        r(7, 5, 14, 14, SKIN)
        r(6, 10, 1, 4, SKIN); r(21, 10, 1, 4, SKIN)
        r(9, 11, 3, 3, (255, 255, 255)); r(16, 11, 3, 3, (255, 255, 255))
        r(10, 12, 2, 2, (50, 34, 30)); r(17, 12, 2, 2, (50, 34, 30))
        r(9, 9, 3, 1, HAIR); r(16, 9, 3, 1, HAIR)
        r(12, 16, 4, 1, (190, 100, 90))
        r(8, 17, 12, 2, (190, 144, 108))
        for x, y in ((6, 3), (9, 2), (12, 1), (15, 1), (18, 2), (21, 4), (5, 6), (22, 6), (8, 4), (11, 3), (14, 3), (17, 3)):
            r(x, y, 3, 3, HAIR)
        for x, y in ((9, 3), (13, 2), (17, 3), (21, 5)):
            r(x, y, 1, 1, HAIR_HI)
        pygame.draw.rect(s, (250, 246, 255), s.get_rect(), 1)
        return pygame.transform.scale(s, (size, size))
    return _cached(("portrait", size), make)


# ------------------------------------------------------------ birds (screen space)
def bird_frames(kind):
    def make():
        frames = []
        body = {"taube": (130, 130, 146), "rabe": (30, 28, 36), "gans": (226, 226, 220)}[kind]
        wing = {"taube": (104, 104, 120), "rabe": (16, 14, 20), "gans": (190, 190, 186)}[kind]
        w = 14 if kind != "gans" else 18
        for up in (True, False):
            s = pygame.Surface((w, 10), pygame.SRCALPHA)
            pygame.draw.rect(s, body, (3, 4, w - 6, 3))
            pygame.draw.rect(s, body, (w - 4, 3, 3, 2))
            pygame.draw.rect(s, (240, 150, 30) if kind != "rabe" else (60, 60, 60), (w - 1, 4, 1, 1))
            if up:
                pygame.draw.polygon(s, wing, [(4, 4), (w // 2 + 1, 4), (w // 2 - 3, 0)])
            else:
                pygame.draw.polygon(s, wing, [(4, 6), (w // 2 + 1, 6), (w // 2 - 3, 10)])
            frames.append(pygame.transform.scale(s, (w * 2, 20)))
        return frames
    return _cached(("bird", kind), make)


# ------------------------------------------------------------ menu icon
def menu_icon_surface(size=32):
    """16 px icon for spiele.exe and the title bar: the black Lastenrad from
    the side with a Bassbox and a disco ball on its flat deck."""
    s = pygame.Surface((16, 16), pygame.SRCALPHA)
    ink = (24, 16, 30)
    pygame.draw.rect(s, (40, 40, 46), (8, 4, 4, 5))  # bassbox
    pygame.draw.rect(s, (110, 110, 124), (9, 6, 2, 2))
    pygame.draw.circle(s, (220, 220, 235), (5, 7), 2)  # disco ball
    s.set_at((4, 6), (255, 130, 200))
    pygame.draw.line(s, (168, 128, 84), (3, 9), (14, 9))  # deck
    pygame.draw.line(s, ink, (3, 10), (14, 10))
    pygame.draw.circle(s, ink, (13, 13), 2, 1)  # front wheel
    pygame.draw.circle(s, ink, (2, 12), 3, 1)  # rear wheel
    pygame.draw.line(s, ink, (2, 12), (4, 10))
    pygame.draw.line(s, ink, (1, 6), (2, 9))  # bar
    s.set_at((1, 5), (255, 130, 200))
    return pygame.transform.scale(s, (size, size))


def preload():
    """Paints every sprite once (so the first frame of a run doesn't stutter)."""
    bike_sprite()
    lef_sprite()
    for defn in ITEMS_BY_ID.values():
        item_sprite(defn)
        for i in range(len(defn.get("parts", ()))):
            part_sprite(defn, i)
