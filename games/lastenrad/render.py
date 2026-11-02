# -*- coding: utf-8 -*-
"""Drawing the world: parallax park/city backdrop (spec §20), ground, Lef,
the bike, items, dust/crash particles (spec §21/22), the debug overlay
(spec §37) and stack thumbnails (spec §31).

Pi budget: backdrop layers are pre-rendered and only re-composed when the
camera moved by a pixel; rotated/zoomed sprites are cached with quantised
angle and zoom (LRU); particles are plain rects (no per-frame alpha
surfaces).
"""

import math
import random
from collections import OrderedDict

import pygame

from . import config as C
from . import sprites as S
from .camera import Camera

SKY_TOP = (88, 140, 214)
SKY_LOW = (255, 200, 156)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ------------------------------------------------------------ backdrop layers (built once)
_LAYERS = {}
MARGIN = 220  # layers are wider than the screen for horizontal parallax


def _layer(key, make):
    if key not in _LAYERS:
        _LAYERS[key] = make()
    return _LAYERS[key]


def sky_surface():
    def make():
        s = pygame.Surface((C.W, C.H))
        for y in range(C.H):
            t = min(1.0, max(0.0, (y - 40) / 620))
            pygame.draw.line(s, _lerp(SKY_TOP, SKY_LOW, t * t), (0, y), (C.W, y))
        for i in range(70):  # a few stars/specks of dust up high, for the absurd heights
            s.set_at(((i * 131) % C.W, (i * 47) % 260 + 10), (180, 200, 240))
        return s
    return _layer("sky", make)


def _pixel_cloud(s, x, y, w, col, sh):
    for i in range(0, w, 14):
        r = 12 + (i * 7) % 9
        pygame.draw.circle(s, col, (x + i, y - r // 3), r)
    pygame.draw.rect(s, col, (x - 8, y - 6, w + 10, 14))
    pygame.draw.rect(s, sh, (x - 8, y + 6, w + 10, 3))


def clouds_surface():
    def make():
        s = pygame.Surface((C.W + 2 * MARGIN, 700), pygame.SRCALPHA)
        rng = random.Random(4)
        for i in range(9):
            _pixel_cloud(s, rng.randint(0, C.W + 2 * MARGIN - 120), 40 + i * 70 + rng.randint(-20, 20), rng.randint(60, 140),
                         (255, 244, 236), (232, 200, 196))
        return s
    return _layer("clouds", make)


def tower_surface():
    """Fernsehturm silhouette, far away and hazy."""
    def make():
        col, hi = (132, 142, 178), (160, 168, 200)
        s = pygame.Surface((60, 400), pygame.SRCALPHA)
        pygame.draw.rect(s, col, (28, 0, 3, 70))
        pygame.draw.rect(s, (220, 60, 60), (28, 0, 3, 4))
        pygame.draw.rect(s, (230, 230, 240), (26, 40, 7, 6))
        pygame.draw.circle(s, col, (30, 92), 22)
        pygame.draw.circle(s, hi, (24, 86), 7)
        pygame.draw.rect(s, (120, 130, 166), (10, 96, 40, 6))
        pygame.draw.polygon(s, col, [(25, 110), (35, 110), (40, 400), (20, 400)])
        pygame.draw.line(s, hi, (27, 112), (23, 400), 1)
        return s
    return _layer("tower", make)


def skyline_surface():
    def make():
        w = C.W + 2 * MARGIN
        s = pygame.Surface((w, 620), pygame.SRCALPHA)
        rng = random.Random(7)
        x = 0
        col = (150, 156, 192)
        win = (176, 182, 214)
        while x < w:
            bw, bh = rng.randint(30, 70), rng.randint(40, 150)
            pygame.draw.rect(s, col, (x, 120 - bh + 60, bw, 620))
            if rng.random() < 0.3:  # a Plattenbau
                for wy in range(180 - bh + 4, 620, 10):
                    for wx in range(x + 4, x + bw - 4, 8):
                        s.set_at((wx, wy), win)
            if rng.random() < 0.2:
                pygame.draw.rect(s, col, (x + bw // 2, 120 - bh + 30, 3, 30))  # antenna/crane
            x += bw + rng.randint(-6, 4)
        return s
    return _layer("skyline", make)


HOUSE_COLS = [(236, 196, 150), (214, 150, 140), (180, 196, 170), (240, 220, 170), (196, 176, 210), (230, 170, 120),
              (170, 186, 214)]


def houses_surface():
    """Berliner Altbau row: facades, windows, roofs, chimneys, a rainbow flag."""
    def make():
        w = C.W + 2 * MARGIN
        s = pygame.Surface((w, 720), pygame.SRCALPHA)
        rng = random.Random(11)
        x = 0
        while x < w:
            bw = rng.randint(70, 120)
            top = rng.randint(20, 70)
            col = rng.choice(HOUSE_COLS)
            dark = S.shade(col, 0.78)
            pygame.draw.rect(s, col, (x, top, bw, 720))
            pygame.draw.rect(s, dark, (x, top, 3, 720))
            roof = rng.choice([(120, 70, 66), (92, 92, 104), (140, 86, 70)])
            pygame.draw.polygon(s, roof, [(x - 4, top + 2), (x + bw + 4, top + 2), (x + bw - 10, top - 22), (x + 10, top - 22)])
            if rng.random() < 0.7:
                cx = x + rng.randint(14, bw - 20)
                pygame.draw.rect(s, (120, 76, 70), (cx, top - 34, 8, 16))
            for fy in range(top + 18, 720, 46):
                for wx in range(x + 12, x + bw - 18, 24):
                    lit = rng.random() < 0.18
                    pygame.draw.rect(s, (255, 226, 140) if lit else (70, 84, 110), (wx, fy, 12, 22))
                    pygame.draw.rect(s, (250, 246, 236), (wx - 2, fy - 3, 16, 3))
                    if rng.random() < 0.12:  # a balcony with plants
                        pygame.draw.rect(s, dark, (wx - 4, fy + 22, 20, 4))
                        pygame.draw.rect(s, (80, 160, 80), (wx - 2, fy + 16, 6, 6))
            if rng.random() < 0.25:
                fx = x + bw // 2
                pygame.draw.line(s, (60, 50, 50), (fx, top + 30), (fx, top + 4), 2)
                for i, c in enumerate([(230, 50, 60), (250, 150, 40), (250, 220, 40), (60, 170, 90), (60, 110, 230), (150, 70, 200)]):
                    pygame.draw.rect(s, c, (fx + 1, top + 4 + i * 3, 22, 3))
            x += bw
        return s
    return _layer("houses", make)


def trees_surface():
    """The park: a dense canopy, trunks, bushes, a fence along the path."""
    def make():
        w = C.W + 2 * MARGIN
        s = pygame.Surface((w, 640), pygame.SRCALPHA)
        rng = random.Random(3)
        greens = [(52, 110, 64), (70, 136, 70), (96, 160, 80), (128, 186, 96)]
        trunks = []
        x = -20
        while x < w + 20:
            trunks.append((x, rng.randint(0, 70), rng.randint(70, 110)))
            x += rng.randint(60, 100)
        back = (40, 86, 54)  # a dense back canopy: nothing of the city shows through at the start
        for bx in range(-20, w + 40, 30):
            pygame.draw.circle(s, back, (bx, 62 + (bx * 37) % 30), 44)
        pygame.draw.rect(s, back, (0, 80, w, 640))
        for tx, ty, r in trunks:
            pygame.draw.rect(s, (88, 64, 50), (tx - 6, ty + r, 13, 640))
            pygame.draw.rect(s, (70, 50, 40), (tx - 6, ty + r, 4, 640))
        for layer, col in enumerate(greens):
            for tx, ty, r in trunks:
                for k in range(6):
                    a = k * 1.1 + layer
                    rr = int(r * (0.55 - layer * 0.08))
                    cx = tx + int(math.cos(a) * r * 0.55)
                    cy = ty + r + int(math.sin(a) * r * 0.45) - layer * 8
                    pygame.draw.circle(s, col, (cx, cy), rr)
        for y in range(0, 640, 3):  # dithered shade at the canopy's lower half
            for xx in range((y // 3) % 2, w, 4):
                if s.get_at((xx, y))[:3] == greens[0]:
                    s.set_at((xx, y), (44, 96, 56))
        base = 402  # ground line (GROUND_SCREEN_Y - TREE_TOP_Y)
        pygame.draw.rect(s, (60, 120, 66), (0, base - 46, w, 640))
        for bx in range(0, w, 36):  # bushes
            r = 20 + (bx * 13) % 14
            pygame.draw.circle(s, (64, 128, 68), (bx, base - 40), r)
            pygame.draw.circle(s, (86, 152, 80), (bx - 6, base - 46), r // 2)
            if (bx // 36) % 5 == 2:
                pygame.draw.circle(s, (255, 120, 190), (bx + 6, base - 50), 3)
        for fx in range(0, w, 18):  # fence
            pygame.draw.rect(s, (110, 86, 66), (fx, base - 34, 4, 30))
        pygame.draw.rect(s, (110, 86, 66), (0, base - 28, w, 3))
        pygame.draw.rect(s, (110, 86, 66), (0, base - 14, w, 3))
        return s
    return _layer("trees", make)


def grass_tile(zq):
    """Front grass blades (hides the wheel bottoms when the bike rocks)."""
    def make():
        h = max(4, int(14 * zq))
        s = pygame.Surface((64, h), pygame.SRCALPHA)
        rng = random.Random(5)
        for x in range(0, 64, 2):
            bh = rng.randint(h // 3, h)
            col = (70, 150, 70) if x % 6 else (104, 180, 90)
            pygame.draw.rect(s, col, (x, h - bh, 2, bh))
        return s
    return _layer(("grass", zq), make)


# ------------------------------------------------------------ particles
class Particles:
    def __init__(self):
        self.items = []  # [x, y, vx, vy, life, color, size] world coords

    def dust(self, x, y, speed, rng):
        n = 3 + min(6, int(speed / 120))
        for i in range(n):
            side = -1 if i % 2 else 1
            self.items.append([x, y + 2, side * rng.uniform(40, 120), rng.uniform(30, 110), rng.uniform(0.25, 0.45),
                               rng.choice([(236, 226, 200), (200, 186, 160), (250, 246, 236)]), 4])

    def crash(self, x, y, n, rng, spread=1.0):
        cols = [(255, 120, 190), (90, 230, 160), (255, 214, 60), (120, 180, 255), (250, 250, 250), (70, 150, 80),
                (130, 80, 40)]
        for _ in range(n):
            a = rng.uniform(0.1, math.pi - 0.1)
            v = rng.uniform(250, 900) * spread
            self.items.append([x + rng.uniform(-30, 30), y + rng.uniform(-20, 40), math.cos(a) * v, math.sin(a) * v,
                               rng.uniform(0.8, 2.2), rng.choice(cols), rng.choice((4, 6, 6, 8))])

    def step(self, dt):
        for p in self.items:
            p[4] -= dt
            p[3] -= C.GRAVITY * 0.7 * dt
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            if p[1] < 0:
                p[1], p[3], p[2] = 0, -p[3] * 0.35, p[2] * 0.6
        self.items = [p for p in self.items if p[4] > 0]

    def draw(self, surf, cam):
        for x, y, _, _, life, col, size in self.items:
            sx, sy = cam.to_screen(x, y)
            sz = max(2, int(size * cam.zoom))
            surf.fill(col, (int(sx) - sz // 2, int(sy) - sz // 2, sz, sz))


# ------------------------------------------------------------ the renderer
class Renderer:
    def __init__(self):
        self._cache = OrderedDict()  # (key, angle_q, zoom_q, squash) -> surface
        self._bg = pygame.Surface((C.W, C.H))
        self._bg_key = None
        self.birds = []  # [kind, x, y, vx, phase]
        self._bird_timer = {}
        self.rng = random.Random(1)

    # ---- sprite cache
    def _transformed(self, key, img, angle, zoom, squash=1.0, step=C.ANGLE_STEP):
        aq = round(angle / step)
        zq = round(zoom / C.ZOOM_STEP)
        ck = (key, aq, zq, squash)
        surf = self._cache.get(ck)
        if surf is None:
            z = zq * C.ZOOM_STEP
            w, h = img.get_size()
            scaled = pygame.transform.scale(img, (max(1, round(w * z)), max(1, round(h * z * squash))))
            surf = pygame.transform.rotate(scaled, math.degrees(aq * step)) if aq else scaled
            self._cache[ck] = surf
            if len(self._cache) > C.ITEM_CACHE:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(ck)
        return surf

    def _blit_body(self, surf, cam, key, img_lc, body_pos, angle, dx=0.0, squash=1.0, step=C.ANGLE_STEP):
        """Draws a sprite whose local centre lc sits at body_pos(lc)."""
        img, lc = img_lc
        wx, wy = body_pos(lc)
        sx, sy = cam.to_screen(wx + dx, wy)
        out = self._transformed(key, img, angle, cam.zoom, squash, step)
        r = out.get_rect(center=(int(sx), int(sy)))
        if r.right >= 0 and r.left < C.W and r.bottom >= 0 and r.top < C.H:
            surf.blit(out, r)

    # ---- backdrop
    def backdrop(self, surf, cam, dt=0.0):
        rise = max(0.0, cam.rise)
        xoff = -(cam.x - (C.VIEW_LEFT + C.W / 2)) * cam.zoom
        key = (int(rise), int(xoff))
        if key != self._bg_key:
            self._bg_key = key
            bg = self._bg
            bg.blit(sky_surface(), (0, 0))

            def place(img, factor, top, hx=1.0):
                x = -MARGIN + max(-MARGIN, min(MARGIN, xoff * factor * hx))
                y = top + rise * factor
                if y < C.H:
                    bg.blit(img, (int(x), int(y)))

            sun_y = 470 + rise * 0.03
            pygame.draw.circle(bg, (255, 236, 170), (380, int(sun_y)), 34)
            pygame.draw.circle(bg, (255, 250, 220), (380, int(sun_y)), 26)
            place(clouds_surface(), C.CLOUD_FACTOR, -200)
            tower = tower_surface()
            ty = C.TOWER_TIP_Y + rise * C.TOWER_FACTOR
            if ty < C.H:
                bg.blit(tower, (int(330 + xoff * C.TOWER_FACTOR), int(ty)))
            place(skyline_surface(), C.SKYLINE_FACTOR, C.SKYLINE_TOP_Y - 60)
            place(houses_surface(), C.HOUSE_FACTOR, C.HOUSE_TOP_Y - 20)
            place(trees_surface(), C.TREE_FACTOR, C.TREE_TOP_Y)
        surf.blit(self._bg, (0, 0))
        self._birds(surf, rise, dt)

    @staticmethod
    def houses_visible(rise):
        """Do the roofs peek over the canopy yet? (spec §20: from ~15 items)"""
        return C.HOUSE_TOP_Y + rise * C.HOUSE_FACTOR < C.TREE_TOP_Y + rise * C.TREE_FACTOR - 6

    def _birds(self, surf, rise, dt):
        for kind, lo, hi, every in C.BIRDS:
            if lo <= rise <= hi:
                t = self._bird_timer.get(kind, every * 0.3) - dt
                if t <= 0:
                    t = every * self.rng.uniform(0.7, 1.3)
                    left = self.rng.random() < 0.5
                    n = 1 if kind == "taube" else (2 if kind == "rabe" else 5)
                    y0 = self.rng.uniform(C.BAR_H + 30, 330)
                    for i in range(n):
                        dx, dy = (i * 26, abs(i - n // 2) * 12) if kind == "gans" else (i * 30, i * 8)
                        x = -40 - dx if left else C.W + 40 + dx
                        self.birds.append([kind, x, y0 + dy, (1 if left else -1) * self.rng.uniform(50, 90), self.rng.random()])
                self._bird_timer[kind] = t
        for b in self.birds:
            b[1] += b[3] * dt
            b[4] += dt * 4
            frame = S.bird_frames(b[0])[int(b[4]) % 2]
            if b[3] < 0:
                frame = pygame.transform.flip(frame, True, False)
            surf.blit(frame, (int(b[1]), int(b[2])))
        self.birds = [b for b in self.birds if -120 < b[1] < C.W + 120]

    # ---- ground, Lef, bike, items
    def ground(self, surf, cam):
        _, gy = cam.to_screen(0, 0)
        gy = int(gy)
        if gy >= C.H:
            return
        z = cam.zoom
        pygame.draw.rect(surf, (86, 156, 72), (0, gy, C.W, C.H - gy))
        pygame.draw.rect(surf, (120, 186, 90), (0, gy, C.W, max(2, int(4 * z))))
        path = gy + int(16 * z)
        pygame.draw.rect(surf, (214, 192, 146), (0, path, C.W, int(30 * z)))
        pygame.draw.rect(surf, (186, 164, 120), (0, path + int(30 * z) - 3, C.W, 3))
        for i in range(0, C.W + 40, 26):  # pebbles, world-attached
            wx = math.floor(cam.to_world(0, 0)[0] / 26) * 26 + i / z
            sx, _ = cam.to_screen(wx, 0)
            surf.fill((176, 156, 116), (int(sx), path + int((7 + (int(wx) * 7) % 17) * z), 4, 2))

    def grass_front(self, surf, cam):
        _, gy = cam.to_screen(0, 0)
        if gy >= C.H + 20:
            return
        zq = round(cam.zoom / 0.1) * 0.1
        tile = grass_tile(zq)
        x0 = -(cam.to_world(0, 0)[0] * cam.zoom) % 64 - 64
        y = int(gy) - tile.get_height() + int(3 * cam.zoom)
        for x in range(int(x0), C.W, 64):
            surf.blit(tile, (x, y))

    def lef(self, surf, cam, riding=False):
        if riding:
            return
        img = S.lef_sprite()
        out = self._transformed("lef", img, 0.0, cam.zoom)
        sx, sy = cam.to_screen(C.LEF_X, 0)
        surf.blit(out, out.get_rect(midbottom=(int(sx), int(sy) + int(2 * cam.zoom))))

    def bike(self, surf, cam, world, dx=0.0):
        b = world.bike
        self._blit_body(surf, cam, "bike", S.bike_sprite(), b.local_to_world, b.angle, dx=dx, step=math.radians(0.25))

    def items(self, surf, cam, world, dx=0.0):
        t = world.t
        for it in world.items:
            squash = 1.0
            if it.land_fx_t is not None and 0 <= t - it.land_fx_t < 0.16:
                squash = 0.9 if t - it.land_fx_t < 0.08 else 0.95
            for i, (part, pb) in enumerate(it.parts):
                self._blit_body(surf, cam, ("part", it.defn["id"], i), S.part_sprite(it.defn, i), pb.local_to_world, pb.angle, dx)
            b = it.body
            self._blit_body(surf, cam, ("item", it.defn["id"]), S.item_sprite(it.defn), b.local_to_world, b.angle, dx, squash)

    def held(self, surf, cam, defn, x, y, angle):
        ca, sa = math.cos(angle), math.sin(angle)

        def to_world(p):
            return x + p[0] * ca - p[1] * sa, y + p[0] * sa + p[1] * ca
        for i, part in enumerate(defn.get("parts", ())):
            self._blit_body(surf, cam, ("part", defn["id"], i), S.part_sprite(defn, i),
                            lambda lc, a=part["at"]: to_world((a[0] + lc[0], a[1] + lc[1])), angle)
        self._blit_body(surf, cam, ("item", defn["id"]), S.item_sprite(defn), to_world, angle)

    def motion_lines(self, surf, cam, world):
        w = world.bike.angular_velocity
        if abs(w) < 0.22 or world.collapsed:
            return
        for side in (-1, 1):
            ex, ey = world.bike.local_to_world((side * C.DECK_LEN / 2, C.DECK_TOP + 18))
            sx, sy = cam.to_screen(ex, ey)
            d = -side * w  # deck end moving up (+) or down
            off = 10 if d > 0 else -10
            for k in range(2):
                pygame.draw.line(surf, (255, 255, 255), (sx + side * (8 + k * 8), sy + off + k * 6),
                                 (sx + side * (8 + k * 8), sy + off * 2.4 + k * 6), 2)

    def draw_world(self, surf, world, cam, dt=0.0, held=None, particles=None, ride=None):
        """Backdrop, ground, Lef, bike, items, held item, particles, grass.
        ride = (dx, lef_on_bike) while Lef rides off (render-only shift)."""
        self.backdrop(surf, cam, dt)
        self.ground(surf, cam)
        dx = ride[0] if ride else 0.0
        self.lef(surf, cam, riding=bool(ride))
        self.bike(surf, cam, world, dx)
        if ride:
            img = S.lef_riding_sprite()
            out = self._transformed("lefride", img, world.bike.angle, cam.zoom)
            wx, wy = world.bike.local_to_world((-196, 170))
            sx, sy = cam.to_screen(wx + dx, wy)
            surf.blit(out, out.get_rect(center=(int(sx), int(sy))))
        self.items(surf, cam, world, dx)
        if held is not None:
            self.held(surf, cam, *held)
        if particles is not None:
            particles.draw(surf, cam)
        self.motion_lines(surf, cam, world)
        self.grass_front(surf, cam)

    # ---- debug overlay (spec §37)
    def debug(self, surf, world, cam, font, fps):
        col = (0, 255, 120)
        for shape in world.space.shapes:
            body = shape.body
            if body is world.space.static_body:
                continue
            c = (255, 80, 80) if body.is_sleeping else col
            if hasattr(shape, "get_vertices"):
                pts = [cam.to_screen(*body.local_to_world(v)) for v in shape.get_vertices()]
                pygame.draw.polygon(surf, c, pts, 1)
            elif hasattr(shape, "a") and hasattr(shape, "b"):
                a, b = cam.to_screen(*body.local_to_world(shape.a)), cam.to_screen(*body.local_to_world(shape.b))
                pygame.draw.line(surf, c, a, b, max(1, int(shape.radius * 2 * cam.zoom)))
            else:
                p = cam.to_screen(*body.local_to_world(shape.offset))
                pygame.draw.circle(surf, c, (int(p[0]), int(p[1])), max(1, int(shape.radius * cam.zoom)), 1)
        x, y, m = world.com()
        if m:
            sx, sy = cam.to_screen(x, y)
            pygame.draw.line(surf, (255, 255, 0), (sx - 8, sy), (sx + 8, sy), 2)
            pygame.draw.line(surf, (255, 255, 0), (sx, sy - 8), (sx, sy + 8), 2)
        px, py = cam.to_screen(0, 0)
        pygame.draw.circle(surf, (255, 255, 0), (int(px), int(py)), 4)
        sleeping = sum(1 for it in world.items if it.body.is_sleeping)
        lines = [f"FPS {fps:4.1f}", f"Rad {math.degrees(world.tilt):+5.2f} deg  w {world.bike.angular_velocity:+.2f}",
                 f"Drehmoment {world.load_torque() / 1e6:+.2f}M / max {world.capacity() / 1e6:.2f}M",
                 f"Last {world.load_mass:.1f}  Teile {len(world.items)}  schlafen {sleeping}",
                 f"Zoom {cam.zoom:.2f}  Rise {cam.rise:.0f}"]
        for i, ln in enumerate(lines):
            img = font.render(ln, True, (0, 255, 120), (0, 0, 0))
            surf.blit(img, (4, C.BAR_H + 90 + i * 16))  # below Lef's dialog box


def thumbnail(renderer, world):
    """The whole stack, fitted, as a small picture (spec §31)."""
    cam = Camera()
    top = world.top()
    lo, hi = world.extent()
    lo = min(lo, C.LEF_X - 40)
    zoom = min(1.0, (C.H - 90) / (top + 70), (C.W - 30) / (hi - lo))
    cam.zoom = zoom
    cam.x = (lo + hi) / 2
    cam.y = 0.0  # ground at the bottom; zoom already fits the top
    big = pygame.Surface((C.W, C.H))
    keep = renderer.birds
    renderer.birds = []
    renderer.draw_world(big, world, cam)
    renderer.birds = keep
    renderer._bg_key = None
    h = round(C.H * C.THUMB_W / C.W)
    return pygame.transform.smoothscale(big, (C.THUMB_W, h))
