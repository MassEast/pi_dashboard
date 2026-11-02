# -*- coding: utf-8 -*-
"""LASTENRAD-SIMULATOR (lastenrad-simulator.exe): the game object
PiDashboard drives, a party_games._Game.

Flow: own title menu (Tagesladung / Endlos / Story Modus / Party Modus /
Highscores) -> a Run -> crash spectacle -> the shared KiezOS Bestenliste
(one per mode, with a stack picture per entry). A Run holds everything of a
round (pymunk world, camera, director, party state) and survives closing the
game for config.RESUME_SECONDS (module-level _RESUME), so a kiosk idle
timeout never throws away a tower.

Input: the current item is dragged out of the top bar with one finger (tap
-> drag -> release), released exactly where it is (no snapping). Rotation:
two fingers via finger() (relative angle change only), plus - deviation
from spec §6, because SDL finger events on the rotated Pi display are
unverified - two small hold-to-rotate buttons in the bar that turn the held
item (with a second finger) or the next item before it is picked up, with
free angles and no raster.
"""

import math
import os
import random

import pygame

from games import party_games
from . import config as C
from . import modes as M
from . import render as R
from . import sprites as S
from . import ui as U
from .camera import Camera
from .physics import World

# A closed run waiting to be resumed: {"run": Run, "saved_at": wall time}.
_RESUME = None

OVER_LINES_DROP = ["Runtergefallen. Rave abgesagt.", "Das war's mit der Statik.", "Schwerkraft: 1, Rave: 0.",
                   "Alles im Gebüsch.", "Pfand verteilt sich im Park."]
OVER_LINES_TIP = ["Das Rad liegt im Gras.", "Umgekippt. Mit Stil.", "Der Ständer gibt auf.",
                  "Kippt. Kippt? KIPPT."]
WIN_LINES = ["Geliefert! Der Rave kann kommen.", "Angekommen. Ohne Verluste!", "Lef fährt in den Sonnenuntergang."]


def fmt_time(seconds):
    s = max(0.0, seconds)
    return f"{int(s) // 60}:{s % 60:04.1f}"


def thumb_dir():
    return os.path.join(party_games.LOG_DIR, "lastenrad_thumbs")


def rotated_bottom(defn, angle):
    """Lowest y of the item's bbox corners at this angle (item-local)."""
    minx, miny, maxx, maxy = defn["bbox"]
    ca, sa = math.cos(angle), math.sin(angle)
    return min(x * sa + y * ca for x in (minx, maxx) for y in (miny, maxy))


def rotated_extent(defn, angle):
    minx, miny, maxx, maxy = defn["bbox"]
    ca, sa = math.cos(angle), math.sin(angle)
    xs = [x * ca - y * sa for x in (minx, maxx) for y in (miny, maxy)]
    ys = [x * sa + y * ca for x in (minx, maxx) for y in (miny, maxy)]
    return min(xs), min(ys), max(xs), max(ys)


class Run:
    """One round: world, camera, the item sequence and the mode's state."""

    def __init__(self, mode, seed, level=None, players=None, day=None):
        self.mode = mode
        self.seed = seed
        self.level = level
        self.day = day
        self.world = World()
        self.cam = Camera()
        self.particles = R.Particles()
        self.director = M.Director(seed, mode if mode != M.STORY else M.ENDLOS,
                                   fixed=level.items if level is not None else None)
        self.rng = random.Random(f"{seed}-fx")
        self.next_index = 0  # the item waiting in the bar
        self.placed = 0
        self.next_angle = 0.0  # its rotation before pickup (fallback buttons)
        self.last_release_t = None
        self.last_placer = None
        self.elapsed = 0.0  # Story: time since the first touch
        self.timer_on = False
        self.phase = "play"  # play | settle (story) | crash | ride (story won) | out (party)
        self.phase_t = 0.0
        self.boomed = False
        self.shake_until = 0.0
        self.thumb = None
        self.score = 0
        self.result_text = ""
        self.players = M.party_players(players) if players else None
        self.alive = [True] * len(self.players) if players else None
        self.turn = 0
        self.out_player = None
        self.snap_before = None  # Party: the stack before the last placement
        self.lef_line = None  # (text, until world time)

    # ---- items
    def current(self):
        return self.director.get(self.next_index)

    def upcoming(self, k):
        return [self.director.get(self.next_index + i) for i in range(1, k + 1)]

    def remaining(self):
        return len(self.level.items) - self.placed if self.level is not None else None

    def can_grab(self):
        return self.phase == "play" and self.current() is not None

    def release(self, defn, x, y, angle):
        if self.players:
            self.snap_before = self.world.snapshot()
            self.last_placer = self.turn
        self.world.place(defn, x, y, angle, placer=self.turn if self.players else None)
        self.placed += 1
        self.next_index += 1
        self.next_angle = 0.0
        self.last_release_t = self.world.t
        if self.players:
            self.turn = self.next_alive(self.turn)
        if self.mode in (M.ENDLOS, M.TAGES) and self.placed % M.LEF_LINE_EVERY == 0:
            self.lef_line = (self.rng.choice(M.LEF_LINES), self.world.t + 3.0)
        if self.level is not None and self.current() is None:
            self.timer_on = False
            self.phase, self.phase_t = "settle", self.world.t

    def next_alive(self, i):
        n = len(self.players)
        for k in range(1, n + 1):
            j = (i + k) % n
            if self.alive[j]:
                return j
        return i

    # ---- time
    def update(self, dt):
        """Returns an event once: "crash" (just failed), "crash_done",
        "won" (story held 3 s), "ride_done", "out_done"."""
        w = self.world
        if self.timer_on and self.phase == "play":
            self.elapsed += dt
        w.step(dt)
        self.particles.step(dt)
        for t, x, y, speed in w.land_events:
            self.particles.dust(x, y, speed, self.rng)
        w.land_events.clear()
        if self.phase in ("play", "settle") and w.fail is not None:
            return self._fail()
        if self.phase == "settle" and w.t - self.phase_t >= C.STORY_SETTLE_SECONDS:
            self.phase, self.phase_t = "ride", w.t
            return "won"
        if self.phase == "crash":
            if not self.boomed and w.t - self.phase_t >= C.CRASH_BOOM_DELAY:
                self.boomed = True
                n = self.placed
                strength = 0.25 if n < C.CRASH_BOOM_FROM else min(2.4, 0.55 + n / 22)
                w.boom(strength, self.rng)
                x, y, _ = w.com()
                self.particles.crash(x, y, 18 + min(90, n * 4), self.rng, spread=0.6 + strength * 0.4)
                self.shake_until = w.t + 0.25 + 0.25 * strength
            if w.t - self.phase_t >= self.crash_seconds():
                self.phase = "done"
                return "crash_done"
        if self.phase == "out" and w.t - self.phase_t >= C.PARTY_OUT_SECONDS:
            return "out_done"
        if self.phase == "ride" and w.t - self.phase_t >= C.STORY_RIDE_SECONDS:
            self.phase = "done"
            return "ride_done"
        return None

    def crash_seconds(self):
        return min(C.CRASH_MAX_SECONDS, C.CRASH_SECONDS + C.CRASH_EXTRA_PER_ITEM * self.placed)

    def _fail(self):
        w = self.world
        kind, _ = w.fail
        recent = self.last_release_t is not None and w.t - self.last_release_t <= C.BLAME_SECONDS
        self.score = self.placed - (1 if recent else 0)
        self.result_text = random.choice(OVER_LINES_TIP if kind == "tip" else OVER_LINES_DROP)
        self.timer_on = False
        self.phase_t = w.t
        if self.players:
            self.phase = "out"
            self.out_player = self.last_placer
            self.alive[self.out_player] = False
            x, y, _ = w.com()
            self.particles.crash(x, y, 30, self.rng, spread=0.7)
        else:
            self.phase = "crash"
        return "crash"

    def party_restore(self):
        """Back to the stack from before the eliminated player's item."""
        self.world = World.from_snapshot(self.snap_before)
        self.particles = R.Particles()
        self.turn = self.next_alive(self.out_player)
        self.phase = "play"
        self.out_player = None
        self.last_release_t = None

    def winner(self):
        alive = [i for i, a in enumerate(self.alive) if a]
        return alive[0] if len(alive) == 1 else None


class LastenradGame(party_games._Game):
    NAME = "LASTENRAD-SIMULATOR"
    ICON = "lastenrad"
    DESCRIPTION = "Stapeln, balancieren, Rave retten"
    SCORE_LABEL = "Sachen gestapelt"
    NAME_MAX = 15  # spec §30
    IDLE_TIMEOUT_SECONDS = C.IDLE_TIMEOUT_SECONDS  # §32 compromise: runs also survive closing (resume)

    @staticmethod
    def format_score(score):
        return fmt_time(score) if isinstance(score, float) else str(score)

    # ------------------------------------------------------------ setup
    def reset(self, now):
        super().reset(now)
        if not hasattr(self, "renderer"):
            self.renderer = R.Renderer()
            self._thumbs = {}
            self._menu_bg = None
            self._fps = []
        self.screen = "menu"
        self.run = None
        self.hold = None  # {"defn", "x", "y", "angle", "fx", "fy", "fy0"}
        self.fingers = {}
        self.rot_ref = None
        self.finger_rot = None  # (finger id, direction) of a second finger on a rotate button
        self.button_rot = 0  # first finger holding a rotate button
        self.key_rot = 0  # dev/play_lastenrad.py: Q/E
        self.ui_rects = {}
        self.party_n = 3
        self.intro_step = 0
        self.hs_mode = M.ENDLOS
        self.hs_top = 0
        self.msg = None  # (title, lines) for story loss / party winner
        self._dt = 0.0
        self._last_wall = None
        self._set_mode_labels(M.ENDLOS)
        if _RESUME is not None and 0 <= now - _RESUME["saved_at"] <= C.RESUME_SECONDS and _RESUME["run"].phase in ("play", "settle"):
            self.screen = "resume"

    def _set_mode_labels(self, mode):
        self.mode = mode
        if mode == M.STORY:
            self.SCORE_LABEL, self.SCORE_UNIT, self.LOWER_IS_BETTER = "Zeit", "", True
        else:
            self.SCORE_LABEL, self.SCORE_UNIT, self.LOWER_IS_BETTER = "Sachen gestapelt", "", False

    def score_key(self):
        level = self.run.level.id if self.run is not None and self.run.level is not None else None
        return M.score_key(self.NAME, self.mode, level)

    def _entry_extra(self):
        extra = {"mode": self.mode}
        if self.mode == M.TAGES:
            extra["day"] = self.run.day.isoformat()
        return extra

    # ------------------------------------------------------------ starting runs
    def start_run(self, mode, level=None, players=None):
        global _RESUME
        _RESUME = None
        self._set_mode_labels(mode)
        day = M.today() if mode == M.TAGES else None
        seed = M.day_seed(day) if mode == M.TAGES else (level.id if level is not None else random.random())
        self.run = Run(mode, seed, level=level, players=players, day=day)
        self.hold = None
        self.state = "play"
        self.screen = "play"
        self.score = 0
        self._over_key = None
        if mode in (M.ENDLOS, M.TAGES):
            self.run.lef_line = (random.choice(M.LEF_LINES[:2]), 2.6)

    def again(self):
        run = self.run
        if run is None:
            return None
        if run.mode == M.PARTY:
            self.start_run(M.PARTY, players=len(run.players))
        else:
            self.start_run(run.mode, level=run.level)
        return None

    def to_menu(self):
        self.state = "ready"
        self.screen = "menu"
        self.run = None
        self.hold = None
        self.viewing = None
        self._menu_bg = None

    # ------------------------------------------------------------ input
    def tap(self, x, y):
        if self.show_close and self.close_rect.collidepoint((x, y)):
            return "close"
        if self.state == "over":
            hit = next((k for k, r in self.buttons.items() if r.collidepoint((x, y))), None)
            ready = self.last_tick - self.over_at >= party_games.GAME_OVER_TAP_DELAY_SECONDS
            if hit == "menu" and ready and not self.name_entry and self.viewing is None:
                self.to_menu()
                return None
            return super().tap(x, y)
        if self.screen == "play":
            self._play_down(x, y)
            return None
        if x < C.CORNER[0] and y < C.CORNER[1]:  # PiDashboard's emergency-exit box: never a button
            return None
        hit = next((k for k, r in self.ui_rects.items() if r.collidepoint((x, y))), None)
        handler = getattr(self, f"_tap_{self.screen}")
        handler(hit, x, y)
        return None

    def _tap_menu(self, hit, x, y):
        if hit == "tages":
            self.start_run(M.TAGES)
        elif hit == "endlos":
            self.start_run(M.ENDLOS)
        elif hit == "story":
            self.screen, self.intro_step = "intro", 0
            self._set_mode_labels(M.STORY)
            self.run = Run(M.STORY, M.LEVELS[0].id, level=M.LEVELS[0])
        elif hit == "party":
            self.screen = "party_setup"
        elif hit == "scores":
            self.screen, self.hs_top, self.viewing = "highscores", 0, None

    def _tap_resume(self, hit, x, y):
        global _RESUME
        if hit == "resume":
            self.run = _RESUME["run"]
            _RESUME = None
            self._set_mode_labels(self.run.mode)
            self.state, self.screen = "play", "play"
            self.hold = None
            self.run.cam.snap(self.run.world.top(), self.run.world.extent())
        elif hit == "new":
            _RESUME = None
            self.screen = "menu"

    def _tap_party_setup(self, hit, x, y):
        if hit and hit.startswith("n"):
            self.party_n = int(hit[1:])
        elif hit == "go":
            self.start_run(M.PARTY, players=self.party_n)
        elif hit == "back":
            self.screen = "menu"

    def _tap_intro(self, hit, x, y):
        if hit == "back":
            self.to_menu()
            return
        self.intro_step += 1
        if self.intro_step >= len(self.run.level.intro):
            self.start_run(M.STORY, level=self.run.level)

    def _tap_highscores(self, hit, x, y):
        if self.viewing is not None:
            self.viewing = None
            return
        if hit in (M.ENDLOS, M.TAGES, M.STORY):
            self.hs_mode, self.hs_top = hit, 0
        elif hit == "up":
            self.hs_top = max(0, self.hs_top - 6)
        elif hit == "down":
            self.hs_top += 6
        elif hit == "back":
            self.screen = "menu"
        elif hit and hit.startswith("row"):
            entry = self._hs_entries()[int(hit[3:])]
            picture = self.entry_image(entry)
            if picture is not None:
                self._set_mode_labels(self.hs_mode)
                self.viewing = (entry, picture)

    def _tap_msg(self, hit, x, y):
        if hit == "again":
            self.again()
        elif hit == "menu":
            self.to_menu()

    def _bar_hit(self, x, y):
        return next((k for k, r in self.ui_rects.items() if k in ("slot", "rot_l", "rot_r") and r.collidepoint((x, y))), None)

    def _play_down(self, x, y):
        run = self.run
        hit = self._bar_hit(x, y)
        if hit in ("rot_l", "rot_r"):
            self.button_rot = 1 if hit == "rot_l" else -1
            return
        if run.phase == "intro":
            return
        # The item waits in the bar: grab it there (generous: the whole left part of the bar).
        if hit == "slot" and self.hold is None and run.can_grab():
            defn = run.current()
            self.hold = {"defn": defn, "angle": run.next_angle, "fx": x, "fy": y, "fy0": y}
            wx, wy = self._hold_target(x, y)
            self.hold["x"], self.hold["y"] = wx, wy
            if run.level is not None:
                run.timer_on = True

    def drag(self, x, y):
        if self.hold is not None:
            self.hold["fx"], self.hold["fy"] = x, y
            self._move_hold()

    def release(self):
        self.button_rot = 0
        if self.hold is None or self.run is None:
            return
        hold, self.hold = self.hold, None
        self.rot_ref = None
        if hold["fy"] < C.BAR_H or not self.run.can_grab():
            return  # back into the bar: not placed (loslassen über der Leiste = zurücklegen)
        self.run.release(hold["defn"], hold["x"], hold["y"], hold["angle"])

    def finger(self, kind, finger_id, x, y):
        """Second finger: two-finger rotation of the held item (relative
        angle between the fingers only), or a rotate button."""
        if kind == "down":
            self.fingers[finger_id] = (x, y)
            if len(self.fingers) >= 2 and self.screen == "play":
                hit = self._bar_hit(x, y)
                if hit in ("rot_l", "rot_r"):
                    self.finger_rot = (finger_id, 1 if hit == "rot_l" else -1)
                else:
                    self.rot_ref = self._finger_angle()
        elif kind == "move":
            if finger_id not in self.fingers:
                return
            self.fingers[finger_id] = (x, y)
            if self.hold is not None and self.finger_rot is None and self.rot_ref is not None and len(self.fingers) >= 2:
                a = self._finger_angle()
                d = (a - self.rot_ref + math.pi) % (2 * math.pi) - math.pi
                self.rot_ref = a
                self._rotate_hold(-d)  # screen angles run clockwise, world angles counter-clockwise
        else:
            self.fingers.pop(finger_id, None)
            if self.finger_rot is not None and self.finger_rot[0] == finger_id:
                self.finger_rot = None
            if len(self.fingers) < 2:
                self.rot_ref = None
            elif self.finger_rot is None:
                self.rot_ref = self._finger_angle()

    def _finger_angle(self):
        (x0, y0), (x1, y1) = list(self.fingers.values())[:2]
        return math.atan2(y1 - y0, x1 - x0)

    def key_rotate(self, direction):
        """Desktop play script: hold Q/E to rotate (like the bar buttons)."""
        self.key_rot = direction

    # ------------------------------------------------------------ the held item
    def _lift(self, fy, fy0):
        """How far (px) the item floats above the finger: 0 in the bar, full
        GRAB_LIFT + half its height once the finger travelled ~120 px down."""
        return max(0.0, min(1.0, (fy - fy0) / 120.0))

    def _hold_target(self, fx, fy):
        h = self.hold
        cam = self.run.cam
        wx, wy = cam.to_world(fx, fy)
        k = self._lift(fy, h["fy0"])
        bottom = rotated_bottom(h["defn"], h["angle"])
        return wx, wy + k * (C.GRAB_LIFT / cam.zoom - bottom)

    def _move_hold(self):
        """Follow the finger; never into anything (spec §8): slide along or
        stop at contact."""
        h = self.hold
        w = self.run.world
        tx, ty = self._hold_target(h["fx"], h["fy"])
        d, a = h["defn"], h["angle"]
        if w.probe_ok(d, tx, ty, a):
            h["x"], h["y"] = tx, ty
            return
        px, py = h["x"], h["y"]
        if not w.probe_ok(d, px, py, a):
            self._unstick()
            px, py = h["x"], h["y"]
        for cx, cy in ((tx, py), (px, ty)):
            if w.probe_ok(d, cx, cy, a):
                px, py = cx, cy
                break
        lo, hi = 0.0, 1.0  # furthest free point on the way to the target
        for _ in range(C.PROBE_STEPS):
            mid = (lo + hi) / 2
            if w.probe_ok(d, px + (tx - px) * mid, py + (ty - py) * mid, a):
                lo = mid
            else:
                hi = mid
        h["x"], h["y"] = px + (tx - px) * lo, py + (ty - py) * lo

    def _unstick(self):
        """The wobbling stack moved into the held item: lift it out."""
        h = self.hold
        w = self.run.world
        for dy in range(4, 400, 4):
            if w.probe_ok(h["defn"], h["x"], h["y"] + dy, h["angle"]):
                h["y"] += dy
                return

    def _rotate_hold(self, d):
        h = self.hold
        w = self.run.world
        a = h["angle"] + d
        if w.probe_ok(h["defn"], h["x"], h["y"], a):
            h["angle"] = a
            return
        for dy in range(3, 40, 3):
            if w.probe_ok(h["defn"], h["x"], h["y"] + dy, a):
                h["angle"], h["y"] = a, h["y"] + dy
                return

    # ------------------------------------------------------------ frame
    def update(self, now):
        if self._last_wall is not None and now > self._last_wall:
            self._fps.append(now - self._last_wall)
            del self._fps[:-30]
        self._last_wall = now
        dt = max(0.0, min(party_games.MAX_DT_SECONDS, now - self.last_tick))
        self._dt = dt
        super().update(now)

    def step(self, dt):
        global _RESUME
        run = self.run
        if run is not None and self.screen == "msg":  # the crash keeps tumbling behind the dialog
            run.world.step(dt)
            run.particles.step(dt)
            return
        if run is None or self.screen not in ("play", "over"):
            return
        rot = self.key_rot or self.button_rot or (self.finger_rot[1] if self.finger_rot else 0)
        if rot:
            if self.hold is not None:
                self._rotate_hold(rot * C.ROTATE_SPEED * dt)
            elif run.can_grab():
                run.next_angle += rot * C.ROTATE_SPEED * dt
        event = run.update(dt)
        w = run.world
        if self.hold is not None:
            if not run.can_grab():
                self.hold = None
            else:
                self._move_hold()  # the camera may have moved under the finger
        held_box = None
        if self.hold is not None:
            h = self.hold
            ex = rotated_extent(h["defn"], h["angle"])
            l, t = run.cam.to_screen(h["x"] + ex[0], h["y"] + ex[3])
            r, b = run.cam.to_screen(h["x"] + ex[2], h["y"] + ex[1])
            held_box = (l, t, r, b)
        run.cam.update(dt, w.top(), w.extent(), held_box)
        if event == "crash":
            self.hold = None
            run.thumb = R.thumbnail(self.renderer, w)
            _RESUME = None
        elif event == "crash_done":
            if run.mode == M.STORY:
                self.msg = ("Level verloren", [run.result_text, "Ein Drop = Level verloren. Nochmal?"])
                self.screen, self.state = "msg", "ready"
            else:
                self.score = run.score
                self.game_over(run.result_text)
        elif event == "won":
            run.thumb = R.thumbnail(self.renderer, w)
            _RESUME = None
        elif event == "ride_done":
            self.score = round(run.elapsed, 1)
            self.game_over(random.choice(WIN_LINES))
        elif event == "out_done":
            winner = run.winner()
            if winner is not None:
                self.msg = (f"{run.players[winner]} gewinnt!", ["Alle anderen haben was runtergeworfen.",
                                                                f"{run.placed} Sachen sind auf dem Rad gelandet."])
                self.screen, self.state = "msg", "ready"
            else:
                run.party_restore()
        if self.screen == "play" and run.phase in ("play", "settle"):
            _RESUME = {"run": run, "saved_at": self.last_tick}

    def game_over(self, text):
        super().game_over(text)
        if self.mode == M.TAGES:
            day = self.run.day.isoformat()
            entries = [e for e in party_games.top_list(self.score_key()) if e.get("day") == day]
            mine = next((i for i, e in enumerate(entries) if e.get("id") == self.entry_id), None)
            if mine is not None:
                self.over_text = f"{text} Heute Platz {mine + 1}/{len(entries)}"
        self.screen = "over"

    # ------------------------------------------------------------ pictures (spec §31)
    def round_stored(self, entry_id):
        if self.run is None or self.run.thumb is None or entry_id is None:
            return
        os.makedirs(thumb_dir(), exist_ok=True)
        pygame.image.save(self.run.thumb, os.path.join(thumb_dir(), f"{entry_id}.png"))
        self._thumbs[entry_id] = self.run.thumb

    def _thumb_path(self, entry):
        return os.path.join(thumb_dir(), f"{entry.get('id')}.png")

    def entry_image(self, entry):
        eid = entry.get("id")
        if eid is None:
            return None
        if eid not in self._thumbs:
            path = self._thumb_path(entry)
            self._thumbs[eid] = pygame.image.load(path) if os.path.exists(path) else None
        return self._thumbs[eid]

    def _draw_entry_mark(self, surf, entry, x, y):
        if self.entry_image(entry) is not None:  # a tiny photo: the row opens the stack picture
            r = pygame.Rect(0, 0, 18, 14)
            r.midright = (x, y)
            pygame.draw.rect(surf, (90, 150, 220), r)
            pygame.draw.rect(surf, (90, 170, 80), (r.x, r.bottom - 5, r.w, 5))
            pygame.draw.rect(surf, (20, 20, 20), (r.centerx - 2, r.y + 3, 4, 7))
            pygame.draw.rect(surf, (20, 10, 30), r, 1)
            x = r.left - 4
        if entry.get("day") and self.run is not None and self.run.day is not None and entry["day"] == self.run.day.isoformat():
            r = pygame.Rect(0, 0, 16, 16)
            r.midright = (x, y)
            pygame.draw.rect(surf, U.PINK, r, border_radius=4)
            pygame.draw.rect(surf, U.INK, r, 1, border_radius=4)
            U.text(surf, self.fonts, "H", 12, U.INK, outline=False, center=r.center)

    # ------------------------------------------------------------ drawing
    def draw(self, surf):
        if self.screen in ("play", "over") and self.run is not None:
            self._draw_play(surf)
            if self.state == "over" and self.last_tick - self.over_at > 0.5:
                self._draw_over(surf)
            return
        getattr(self, f"_draw_{self.screen}")(surf)

    def _draw_play(self, surf):
        run = self.run
        w = run.world
        held = (self.hold["defn"], self.hold["x"], self.hold["y"], self.hold["angle"]) if self.hold else None
        ride = None
        if run.phase in ("ride", "done") and run.level is not None:
            t = w.t - run.phase_t
            ride = (max(0.0, t - 0.6) ** 2 * 120, True)
        self.renderer.draw_world(surf, w, run.cam, self._dt, held=None, particles=run.particles, ride=ride)
        if C.DEBUG:
            fps = len(self._fps) / max(1e-6, sum(self._fps)) if self._fps else 0.0
            self.renderer.debug(surf, w, run.cam, self.fonts.get(13, False), fps)
        if w.t < run.shake_until:
            k = int(6 * (run.shake_until - w.t) / 0.5) + 2
            surf.scroll(run.rng.randint(-k, k), run.rng.randint(-k, k))
        self._draw_bar(surf)
        if held is not None:  # over the bar while it's still up there
            self.renderer.held(surf, run.cam, *held)
        self._draw_overlays(surf)

    def _draw_bar(self, surf):
        run = self.run
        bar = pygame.Rect(0, 0, C.W, C.BAR_H)
        U.box(surf, bar)
        f = self.fonts
        # left: counter / remaining / whose turn
        if run.players:
            U.text(surf, f, "Am Zug:", 13, U.DIM, bold=False, topleft=(10, 8))
            name = run.players[run.turn] if run.phase == "play" else run.players[run.out_player or run.turn]
            U.text(surf, f, name.replace("Spieler*in ", "Sp.*in "), 17, U.GOLD, topleft=(10, 26))
            U.text(surf, f, f"{sum(run.alive)} im Spiel", 12, U.DIM, bold=False, topleft=(10, 46))
        elif run.level is not None:
            U.text(surf, f, f"Noch {run.remaining()}", 20, U.GOLD, topleft=(10, 6))
            U.text(surf, f, "Sachen", 13, U.DIM, bold=False, topleft=(10, 30))
            U.text(surf, f, fmt_time(run.elapsed), 14, U.WHITE, topleft=(10, 46))
        else:
            U.text(surf, f, str(run.placed), 30, U.GOLD, topleft=(10, 2))
            U.text(surf, f, "Sachen", 13, U.DIM, bold=False, topleft=(10, 34))
            U.text(surf, f, "gestapelt" if run.mode == M.ENDLOS else "heute", 12, U.DIM, bold=False, topleft=(10, 48))
        # current item (grab it here) + its name, then two dimmer previews
        slot = pygame.Rect(100, 5, 92, 42)
        cur = run.current()
        if cur is not None and self.hold is None and run.phase == "play":
            icon = S.item_icon(cur, 84, 40)
            if run.next_angle:
                icon = pygame.transform.rotate(icon, math.degrees(round(run.next_angle / C.ANGLE_STEP) * C.ANGLE_STEP))
                k = min(1.0, 88 / icon.get_width(), 42 / icon.get_height())
                if k < 1.0:
                    icon = pygame.transform.scale(icon, (int(icon.get_width() * k), int(icon.get_height() * k)))
            surf.blit(icon, icon.get_rect(center=slot.center))
            name = cur["name"]
            U.text(surf, f, name, U.fit(f, name, 14, 220), U.WHITE, topleft=(100, 47))
        elif cur is not None and self.hold is not None:
            U.text(surf, f, cur["name"], U.fit(f, cur["name"], 14, 220), U.MINT, topleft=(100, 47))
        elif run.level is not None and cur is None:
            U.text(surf, f, "Alles drauf!", 14, U.MINT, topleft=(100, 47))
        x = 200
        for nxt in run.upcoming(2):
            if nxt is None:
                continue
            ic = S.item_icon(nxt, 52, 30)
            dim = ic.copy()
            dim.fill((150, 150, 170, 255), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(dim, dim.get_rect(center=(x + 28, 24)))
            x += 62
        self.ui_rects = {"slot": pygame.Rect(100, 0, 226, C.BAR_H),
                         "rot_l": pygame.Rect(340, 6, 64, C.BAR_H - 12),
                         "rot_r": pygame.Rect(410, 6, 64, C.BAR_H - 12)}
        rot = self.key_rot or self.button_rot or (self.finger_rot[1] if self.finger_rot else 0)
        U.rotate_arrow(surf, self.ui_rects["rot_l"], 1, active=rot > 0)
        U.rotate_arrow(surf, self.ui_rects["rot_r"], -1, active=rot < 0)

    def _draw_overlays(self, surf):
        run = self.run
        w = run.world
        f = self.fonts
        if run.lef_line is not None and w.t < run.lef_line[1] and run.phase == "play":
            U.dialog_box(surf, f, pygame.Rect(10, C.BAR_H + 8, C.W - 20, 74), "Lef", run.lef_line[0])
        if run.placed == 0 and self.hold is None and run.phase == "play" and (run.lef_line is None or w.t >= run.lef_line[1]):
            if int(self.last_tick * 2) % 2 == 0:
                U.text(surf, f, "Zieh das Teil von oben aufs Rad!", 18, U.WHITE, center=(C.W // 2, C.BAR_H + 120))
        if run.phase == "settle":
            left = C.STORY_SETTLE_SECONDS - (w.t - run.phase_t)
            n = max(1, math.ceil(left))
            frac = left - math.floor(left)
            U.text(surf, f, "Hält es...?", 22, U.WHITE, center=(C.W // 2, C.BAR_H + 70))
            U.text(surf, f, str(n), int(48 + 30 * frac), U.GOLD, center=(C.W // 2, C.BAR_H + 130))
        elif run.phase in ("ride", "done") and run.level is not None:
            U.text(surf, f, "HÄLT!", 44, U.MINT, center=(C.W // 2, C.BAR_H + 100))
            U.text(surf, f, fmt_time(run.elapsed), 26, U.WHITE, center=(C.W // 2, C.BAR_H + 150))
        elif run.phase == "out" and run.out_player is not None:
            box = U.box(surf, pygame.Rect(30, 200, C.W - 60, 120), tint=(150, 40, 80))
            U.text(surf, f, f"{run.players[run.out_player]}", 26, U.GOLD, center=(box.centerx, box.y + 38))
            U.text(surf, f, "fliegt raus!", 26, U.WHITE, center=(box.centerx, box.y + 76))
        elif run.phase == "crash" and w.t - run.phase_t < 1.6:
            k = min(1.0, (w.t - run.phase_t) * 5)
            U.text(surf, f, "RUMMS!" if w.fail[0] == "drop" else "KIPPT!", int(30 + 26 * k), U.GOLD, center=(C.W // 2, C.BAR_H + 110))

    # ---- menu-type screens
    def _menu_backdrop(self):
        """The park with the empty bike and Lef, rendered once."""
        if self._menu_bg is None:
            s = pygame.Surface((C.W, C.H))
            self.renderer.draw_world(s, World(), Camera())
            self.renderer._bg_key = None
            self._menu_bg = s
        return self._menu_bg

    def _logo(self, surf, y=18):
        U.text(surf, self.fonts, "LASTENRAD", 46, U.GOLD, center=(C.W // 2 + 30, y + 30))
        U.text(surf, self.fonts, "- SIMULATOR -", 24, U.PINK, center=(C.W // 2 + 30, y + 74))
        U.text(surf, self.fonts, "Stapeln für den Rave. Ohne Statik.", 14, U.WHITE, bold=False, center=(C.W // 2 + 30, y + 102))

    def _draw_menu(self, surf):
        surf.blit(self._menu_backdrop(), (0, 0))
        self._logo(surf)
        f = self.fonts
        day = M.today().isoformat()
        tages = [e for e in party_games.top_list(M.score_key(self.NAME, M.TAGES)) if e.get("day") == day]
        tsub = (f"Heute best: {tages[0]['score']} ({party_games.entry_name(tages[0])}) · {len(tages)}x"
                if tages else "Gleiche Ladung für die ganze WG")
        top = party_games.best(self.NAME)
        esub = f"Rekord: {top['score']} ({party_games.entry_name(top)})" if top else "So viel wie geht"
        lv = M.LEVELS[0]
        sbest = party_games.best(M.score_key(self.NAME, M.STORY, lv.id))
        ssub = f"{lv.title}" + (f" · {fmt_time(sbest['score'])}" if sbest else "")
        rows = [("tages", "Tagesladung", tsub), ("endlos", "Endlos", esub), ("story", "Story Modus", ssub),
                ("party", "Party Modus", "2-6 Leute, ein Rad, wer's runterwirft, fliegt")]
        self.ui_rects = {}
        y = 152
        for key, label, sub in rows:
            self.ui_rects[key] = U.button(surf, f, pygame.Rect(40, y, C.W - 80, 66), label, sub)
            y += 74
        self.ui_rects["scores"] = U.button(surf, f, pygame.Rect(150, y + 2, 180, 40), "Highscores", size=17)

    def _draw_resume(self, surf):
        surf.blit(self._menu_backdrop(), (0, 0))
        self._logo(surf)
        f = self.fonts
        run = _RESUME["run"] if _RESUME is not None else None
        box = U.box(surf, pygame.Rect(30, 170, C.W - 60, 250))
        U.text(surf, f, "Da steht noch dein Rad!", 22, U.GOLD, center=(box.centerx, box.y + 34))
        if run is not None:
            what = f"{M.LABELS[run.mode]}: {run.placed} Sachen drauf"
            U.text(surf, f, what, 17, U.WHITE, bold=False, center=(box.centerx, box.y + 72))
        U.text(surf, f, "Weiterstapeln oder neu anfangen?", 15, U.DIM, bold=False, center=(box.centerx, box.y + 100))
        half = (box.w - 48) // 2
        self.ui_rects = {
            "resume": U.button(surf, f, pygame.Rect(box.x + 16, box.y + 140, half, 80), "WEITER", tint=(40, 130, 90)),
            "new": U.button(surf, f, pygame.Rect(box.x + 32 + half, box.y + 140, half, 80), "NEU STARTEN", size=19),
        }

    def _draw_party_setup(self, surf):
        surf.blit(self._menu_backdrop(), (0, 0))
        self._logo(surf)
        f = self.fonts
        box = U.box(surf, pygame.Rect(20, 150, C.W - 40, 380))
        U.text(surf, f, "Party Modus", 26, U.GOLD, center=(box.centerx, box.y + 32))
        lines = ["Reihum legt jede*r genau ein Teil aufs Rad.",
                 "Fällt danach was runter oder kippt das Rad, fliegt raus, wer zuletzt gelegt hat.",
                 "Das Rad wird zurückgesetzt, die anderen machen weiter. Wer übrig bleibt, gewinnt."]
        y = box.y + 62
        for ln in lines:
            for part in U.wrap(f, ln, 15, box.w - 40, bold=False):
                U.text(surf, f, part, 15, U.WHITE, bold=False, topleft=(box.x + 20, y))
                y += 20
            y += 4
        U.text(surf, f, "Wie viele spielen mit?", 18, U.GOLD, center=(box.centerx, y + 18))
        self.ui_rects = {}
        bw = (box.w - 40 - 4 * 8) // 5
        for i, n in enumerate(range(C.PARTY_MIN, C.PARTY_MAX + 1)):
            r = pygame.Rect(box.x + 20 + i * (bw + 8), y + 40, bw, 64)
            self.ui_rects[f"n{n}"] = U.button(surf, f, r, str(n), size=28, pressed=n == self.party_n,
                                              tint=(150, 60, 140) if n == self.party_n else None)
        half = (box.w - 48) // 2
        self.ui_rects["back"] = U.button(surf, f, pygame.Rect(box.x + 16, box.bottom - 74, half, 58), "Zurück", size=20)
        self.ui_rects["go"] = U.button(surf, f, pygame.Rect(box.x + 32 + half, box.bottom - 74, half, 58), "LOS!",
                                       tint=(40, 130, 90))

    def _draw_intro(self, surf):
        surf.blit(self._menu_backdrop(), (0, 0))
        f = self.fonts
        lv = self.run.level
        title = U.box(surf, pygame.Rect(110, 150, C.W - 130, 70))
        U.text(surf, f, "Level 1", 14, U.DIM, bold=False, center=(title.centerx, title.y + 20))
        U.text(surf, f, lv.title, U.fit(f, lv.title, 20, title.w - 20), U.GOLD, center=(title.centerx, title.y + 46))
        speaker, line = lv.intro[min(self.intro_step, len(lv.intro) - 1)]
        rect = pygame.Rect(8, C.H - 140, C.W - 16, 130)
        U.dialog_box(surf, f, rect, speaker, line, hint="Tippen: weiter  >")
        self.ui_rects = {"next": rect, "back": U.button(surf, f, pygame.Rect(C.W - 150, 236, 130, 44), "Zurück", size=16)}

    def _hs_entries(self):
        key = M.score_key(self.NAME, self.hs_mode, M.LEVELS[0].id)
        return party_games.top_list(key)

    def _draw_highscores(self, surf):
        surf.blit(self._menu_backdrop(), (0, 0))
        self._logo(surf)
        f = self.fonts
        box = U.box(surf, pygame.Rect(12, 150, C.W - 24, C.H - 162))
        self.ui_rects = {}
        tw = (box.w - 32) // 3
        for i, (key, label) in enumerate(((M.ENDLOS, "Endlos"), (M.TAGES, "Tagesladung"), (M.STORY, "Story"))):
            r = pygame.Rect(box.x + 12 + i * (tw + 4), box.y + 12, tw, 44)
            self.ui_rects[key] = U.button(surf, f, r, label, size=16, pressed=key == self.hs_mode,
                                          tint=(150, 60, 140) if key == self.hs_mode else None)
        entries = self._hs_entries()
        story = self.hs_mode == M.STORY
        list_rect = pygame.Rect(box.x + 12, box.y + 66, box.w - 24 - 52, box.h - 66 - 70)
        pygame.draw.rect(surf, (10, 10, 40), list_rect)
        pygame.draw.rect(surf, U.FRAME_SH, list_rect, 1)
        rows = (list_rect.h - 8) // 34
        self.hs_top = max(0, min(self.hs_top, max(0, len(entries) - rows)))
        if not entries:
            U.text(surf, f, "Noch keine Runden", 17, U.DIM, bold=False, center=list_rect.center)
        today = M.today().isoformat()
        for i in range(self.hs_top, min(len(entries), self.hs_top + rows)):
            e = entries[i]
            r = pygame.Rect(list_rect.x + 4, list_rect.y + 4 + (i - self.hs_top) * 34, list_rect.w - 8, 32)
            if self.hs_mode == M.TAGES and e.get("day") == today:
                pygame.draw.rect(surf, (60, 40, 110), r)
            U.text(surf, f, f"{i + 1}.", 16, U.DIM, bold=False, midleft=(r.x + 6, r.centery))
            score = fmt_time(e["score"]) if story else str(e["score"])
            sr = U.text(surf, f, score, 17, U.GOLD, midright=(r.right - 8, r.centery))
            name = party_games.entry_name(e)
            if self.hs_mode == M.TAGES and e.get("day"):
                name += f"  {e['day'][8:10]}.{e['day'][5:7]}."
            U.text(surf, f, party_games._fit(f.get(16, True), name, sr.left - r.x - 90), 16, U.WHITE, midleft=(r.x + 44, r.centery))
            if self.entry_image(e) is not None:
                mark = pygame.Rect(0, 0, 18, 14)
                mark.midright = (sr.left - 8, r.centery)
                pygame.draw.rect(surf, (90, 150, 220), mark)
                pygame.draw.rect(surf, (90, 170, 80), (mark.x, mark.bottom - 5, mark.w, 5))
                pygame.draw.rect(surf, U.INK, mark, 1)
            self.ui_rects[f"row{i}"] = r
        half = (list_rect.h - 8) // 2
        self.ui_rects["up"] = U.button(surf, f, pygame.Rect(list_rect.right + 6, list_rect.y, 44, half), "^", size=20)
        self.ui_rects["down"] = U.button(surf, f, pygame.Rect(list_rect.right + 6, list_rect.bottom - half, 44, half), "v", size=20)
        self.ui_rects["back"] = U.button(surf, f, pygame.Rect(box.centerx - 90, box.bottom - 62, 180, 50), "Zurück", size=18)
        if story:
            U.text(surf, f, M.LEVELS[0].title, 13, U.DIM, bold=False, midbottom=(box.centerx, list_rect.bottom + 2 + 0))
        if self.viewing is not None:
            self._draw_picture(surf)

    def _draw_msg(self, surf):
        if self.run is not None:
            self._draw_play_frozen(surf)
        f = self.fonts
        title, lines = self.msg
        box = U.box(surf, pygame.Rect(24, 170, C.W - 48, 300))
        U.text(surf, f, title, U.fit(f, title, 26, box.w - 30), U.GOLD, center=(box.centerx, box.y + 40))
        y = box.y + 80
        for ln in lines:
            for part in U.wrap(f, ln, 16, box.w - 40, bold=False):
                U.text(surf, f, part, 16, U.WHITE, bold=False, center=(box.centerx, y))
                y += 22
        half = (box.w - 48) // 2
        self.ui_rects = {"again": U.button(surf, f, pygame.Rect(box.x + 16, box.bottom - 86, half, 70), "NOCHMAL"),
                         "menu": U.button(surf, f, pygame.Rect(box.x + 32 + half, box.bottom - 86, half, 70), "MENÜ")}

    def _draw_play_frozen(self, surf):
        run = self.run
        self.renderer.draw_world(surf, run.world, run.cam, self._dt, particles=run.particles)
