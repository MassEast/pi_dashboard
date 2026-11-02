# -*- coding: utf-8 -*-
"""The physical world of a run: pymunk space, the bike on its kickstand,
the placed items, drop/tip detection, snapshots (Party reset, bot checks).

The bike is a dynamic body on a pivot at its kickstand foot (0, 0). Its
balance (spec §11) is a DampedRotarySpring whose torque_func is a nonlinear
"stand": stiff and tolerant up to config.HOLD_ANGLE, then giving way until
config.NO_RETURN_ANGLE, then nothing. The load acts on the deck through real
contacts, so lever arms, height and impacts all come from the physics. A
constraint (not a kinematic body) keeps pymunk's sleeping working: resting
stacks cost almost nothing.

The held item is never in the space: probe_ok() tests a pose with
shape_query, so a held item can't clip into anything (spec §8).
"""

import math

import pymunk

from . import config as C
from .items import ITEMS_BY_ID

GROUND_T, BIKE_T, ITEM_T = 1, 2, 3
CAT_GROUND, CAT_BIKE, CAT_ITEM = 0b001, 0b010, 0b100


def make_shape(body, spec, off=(0.0, 0.0)):
    """pymunk shape for one item shape spec, shifted by -off (part bodies
    have their origin at their hinge/axle)."""
    kind = spec[0]
    ox, oy = off
    if kind == "box":
        _, w, h, cx, cy = spec[:5]
        r = spec[5] if len(spec) > 5 else 0
        x0, y0, x1, y1 = cx - w / 2 + r - ox, cy - h / 2 + r - oy, cx + w / 2 - r - ox, cy + h / 2 - r - oy
        return pymunk.Poly(body, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], radius=r)
    if kind == "circle":
        _, r, cx, cy = spec
        return pymunk.Circle(body, r, (cx - ox, cy - oy))
    if kind == "capsule":
        _, length, t, cx, cy = spec
        half = length / 2 - t / 2
        return pymunk.Segment(body, (cx - half - ox, cy - oy), (cx + half - ox, cy - oy), t / 2)
    if kind == "seg":
        _, x1, y1, x2, y2, r = spec
        return pymunk.Segment(body, (x1 - ox, y1 - oy), (x2 - ox, y2 - oy), r)
    return pymunk.Poly(body, [(x - ox, y - oy) for x, y in spec[1]])


def _angular_damper(keep_per_second):
    def velocity_func(body, gravity, damping, dt):
        pymunk.Body.update_velocity(body, gravity, damping, dt)
        body.angular_velocity *= keep_per_second ** dt
    return velocity_func


def set_pose(body, x, y, angle):
    """Puts the body's local origin at (x, y) (pymunk rotates around the
    centre of gravity, so the angle goes first)."""
    body.angle = angle
    body.position = (x, y)


class Item:
    """One placed item: main body, hinged part bodies, who placed it."""

    def __init__(self, defn, uid, index, placer, t):
        self.defn = defn
        self.uid = uid
        self.index = index  # 0-based placement order
        self.placer = placer  # Party: player index
        self.placed_t = t
        self.landed = False  # touched the bike or the stack (counts as load from then on)
        self.lost = False  # touched the ground
        self.land_fx_t = None  # world time of the first landing (squash)
        self.gripping = False  # resting: friction boosted (see World._haft)
        self.rolls = bool({"round", "rolls"} & set(defn["tags"]))
        self.body = None
        self.parts = []  # (part def, body)
        self.shapes = []
        self.constraints = []

    def bodies(self):
        return [self.body] + [b for _, b in self.parts]

    def poses(self):
        return [(b.angle, *b.local_to_world((0, 0))) for b in self.bodies()]


class World:
    def __init__(self):
        self.space = space = pymunk.Space()
        space.gravity = (0.0, -C.GRAVITY)
        space.iterations = C.ITERATIONS
        space.damping = C.SPACE_DAMPING
        space.sleep_time_threshold = C.SLEEP_TIME
        space.idle_speed_threshold = C.IDLE_SPEED
        space.collision_slop = C.COLLISION_SLOP
        self.t = 0.0
        self._acc = 0.0
        self.items = []
        self._uid = 0
        self.body_item = {}
        self.fail = None  # ("drop", item) | ("tip", None), set once
        self.fail_t = None
        self.land_events = []  # (t, x, y, speed) for dust puffs, consumed by the renderer
        self.collapsed = False
        self._balance_dirty = True
        self.load_mass = 0.0
        self.load_height = 0.0
        self._probes = {}

        ground = pymunk.Segment(space.static_body, (-8000, -3), (8000, -3), 3)
        ground.friction = 0.9
        ground.collision_type = GROUND_T
        ground.filter = pymunk.ShapeFilter(categories=CAT_GROUND)
        space.add(ground)
        self.ground = ground

        bike = pymunk.Body(C.BIKE_MASS, C.BIKE_MOMENT)
        bike.position = (0, 0)
        half = C.DECK_LEN / 2
        deck = pymunk.Poly(bike, [(-half, C.DECK_TOP - C.DECK_THICK), (half, C.DECK_TOP - C.DECK_THICK),
                                  (half, C.DECK_TOP), (-half, C.DECK_TOP)])
        deck.friction = C.DECK_FRICTION
        deck.collision_type = BIKE_T
        deck.filter = pymunk.ShapeFilter(categories=CAT_BIKE, mask=CAT_ITEM)
        self.pivot = pymunk.PivotJoint(space.static_body, bike, (0, 0))
        self.pivot.collide_bodies = False
        self.spring = pymunk.DampedRotarySpring(space.static_body, bike, 0.0, 0.0, 0.0)
        self.spring.torque_func = self._stand_torque
        space.add(bike, deck, self.pivot, self.spring)
        self.bike, self.deck = bike, deck
        self._stiffness = 1.0
        self._damping = 0.0
        self._wobble_damping = 0.0

        space.on_collision(ITEM_T, GROUND_T, begin=self._on_ground)
        space.on_collision(ITEM_T, BIKE_T, begin=self._on_land)
        space.on_collision(ITEM_T, ITEM_T, begin=self._on_land)
        self.update_balance()

    # ------------------------------------------------------------ balance
    @property
    def tilt(self):
        return self.bike.angle

    def capacity(self):
        return C.BASE_HOLD_TORQUE + C.GRAVITY * self.load_mass * C.STAND_LEVER

    def _stand_torque(self, spring, rel):
        """Torque on the bike from the kickstand (rel = -tilt), see config."""
        a = abs(rel)
        cap = self.capacity()
        if a <= C.CATCH_ANGLE:
            mag = cap * C.CATCH_SHARE * a / C.CATCH_ANGLE
        elif a <= C.HOLD_ANGLE:
            mag = cap * (C.CATCH_SHARE + (1 - C.CATCH_SHARE) * (a - C.CATCH_ANGLE) / (C.HOLD_ANGLE - C.CATCH_ANGLE))
        elif a < C.NO_RETURN_ANGLE:
            mag = cap * (C.NO_RETURN_ANGLE - a) / (C.NO_RETURN_ANGLE - C.HOLD_ANGLE)
        else:
            mag = 0.0
        if a < C.NO_RETURN_ANGLE:
            fade = 1.0 if a <= C.HOLD_ANGLE else (C.NO_RETURN_ANGLE - a) / (C.NO_RETURN_ANGLE - C.HOLD_ANGLE)
            mag += C.HEIGHT_ASSIST * C.GRAVITY * self.load_mass * self.load_height * math.sin(a) * fade
        f = min(1.0, max(0.0, (a - C.CATCH_ANGLE) / (C.HOLD_ANGLE - C.CATCH_ANGLE)))  # less damping towards the limit
        anti = f * (self._damping - self._wobble_damping) * self.bike.angular_velocity
        return math.copysign(mag, rel) + anti

    def update_balance(self):
        """Spring damping for the current load (called when the load changes)."""
        landed = [it for it in self.items if it.landed and not it.lost]
        self.load_mass = sum(b.mass for it in landed for b in it.bodies())
        self.load_height = max(0.0, self.com()[1])
        moment = C.BIKE_MOMENT
        for it in landed:
            for b in it.bodies():
                cx, cy = b.local_to_world(b.center_of_gravity)
                moment += b.moment + b.mass * (cx * cx + cy * cy)
        self._stiffness = self.capacity() * C.CATCH_SHARE / C.CATCH_ANGLE + C.HEIGHT_ASSIST * C.GRAVITY * self.load_mass * self.load_height
        root = math.sqrt(self._stiffness * moment)
        self._damping = 2 * C.BALANCE_ZETA * root
        self._wobble_damping = 2 * C.WOBBLE_ZETA * root
        if not self.collapsed:
            self.spring.damping = self._damping
        self._balance_dirty = False

    # ------------------------------------------------------------ collisions
    def _items_of(self, arbiter):
        return [self.body_item[s.body] for s in arbiter.shapes if s.body in self.body_item]

    def _on_ground(self, arbiter, space, data):
        for item in self._items_of(arbiter):
            if not item.lost:
                item.lost = True
                self._balance_dirty = True

    def _on_land(self, arbiter, space, data):
        for item in self._items_of(arbiter):
            if not item.landed:
                item.landed = True
                item.land_fx_t = self.t
                self._balance_dirty = True
                cps = arbiter.contact_point_set.points
                if cps:
                    p = cps[0].point_a
                    self.land_events.append((self.t, p.x, p.y, abs(item.body.velocity.y)))

    # ------------------------------------------------------------ items
    def _new_item(self, defn, x, y, angle, placer, index=None):
        self._uid += 1
        item = Item(defn, self._uid, len(self.items) if index is None else index, placer, self.t)
        group = pymunk.ShapeFilter(group=self._uid, categories=CAT_ITEM)
        body = pymunk.Body()
        shapes = [make_shape(body, s) for s in defn["shapes"]]
        self._mass_shapes(shapes, defn["mass"])
        for s in shapes:
            s.friction = defn["friction"]
            s.elasticity = defn["restitution"]
            s.collision_type = ITEM_T
            s.filter = group
        if defn.get("angular_damping") is not None:
            body.velocity_func = _angular_damper(defn["angular_damping"])
        set_pose(body, x, y, angle)
        self.space.add(body, *shapes)
        item.body, item.shapes = body, list(shapes)
        self.body_item[body] = item
        for part in defn.get("parts", ()):
            pb = pymunk.Body()
            ax, ay = part["at"]
            if part["kind"] == "wheel":
                pshapes = [pymunk.Circle(pb, part["r"])]
            else:
                pshapes = [make_shape(pb, s, off=(ax, ay)) for s in part["shapes"]]
            self._mass_shapes(pshapes, part["mass"])
            for s in pshapes:
                s.friction = 1.0 if part["kind"] == "wheel" else defn["friction"]
                s.elasticity = 0.0
                s.collision_type = ITEM_T
                s.filter = group
            wx, wy = body.local_to_world((ax, ay))
            set_pose(pb, wx, wy, angle)
            joint = pymunk.PivotJoint(body, pb, (wx, wy))
            joint.collide_bodies = False
            cons = [joint]
            if part["kind"] == "limb":
                lo, hi = part["limits"]
                cons.append(pymunk.RotaryLimitJoint(body, pb, lo, hi))
                cons.append(pymunk.DampedRotarySpring(body, pb, 0.0, 2.0e5 * part["mass"], 4.0e3 * part["mass"]))
            self.space.add(pb, *pshapes, *cons)
            item.parts.append((part, pb))
            item.shapes += pshapes
            item.constraints += cons
            self.body_item[pb] = item
        self.items.append(item)
        return item

    @staticmethod
    def _mass_shapes(shapes, mass):
        areas = [max(1.0, s.area) for s in shapes]
        total = sum(areas)
        for s, a in zip(shapes, areas):
            s.mass = mass * a / total

    def place(self, defn, x, y, angle, placer=None):
        """Releases an item exactly at this pose, at rest (spec §7)."""
        return self._new_item(defn, x, y, angle, placer)

    def landed_items(self):
        return [it for it in self.items if it.landed and not it.lost]

    # ------------------------------------------------------------ the held item
    def _probe(self, defn):
        if defn["id"] not in self._probes:
            body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
            shapes = [make_shape(body, s) for s in defn["shapes"]]
            for part in defn.get("parts", ()):
                ax, ay = part["at"]
                if part["kind"] == "wheel":
                    shapes.append(pymunk.Circle(body, part["r"], (ax, ay)))
                else:
                    shapes += [make_shape(body, s) for s in part["shapes"]]
            self._probes[defn["id"]] = (body, shapes)
        return self._probes[defn["id"]]

    def probe_ok(self, defn, x, y, angle):
        """True if the item at this pose touches nothing (within PROBE_TOLERANCE)."""
        body, shapes = self._probe(defn)
        body.angle = angle
        body.position = (x, y)
        for s in shapes:
            s.cache_bb()
            for hit in self.space.shape_query(s):
                if any(p.distance < -C.PROBE_TOLERANCE for p in hit.contact_point_set.points):
                    return False
        return True

    def rest_y(self, defn, x, angle, gap=0.0):
        """Lowest free y for the item at x (scanning down from above the
        stack): where it would sit if lowered straight down. For bots/tests."""
        hi = self.top() + (defn["bbox"][3] - defn["bbox"][1]) + 60
        y = hi
        step = 16.0
        while y > -200 and self.probe_ok(defn, x, y - step, angle):
            y -= step
        lo = y - step
        for _ in range(8):
            mid = (y + lo) / 2
            if self.probe_ok(defn, x, mid, angle):
                y = mid
            else:
                lo = mid
        return y + gap

    # ------------------------------------------------------------ stepping
    def step(self, dt):
        self._acc += dt
        h = 1.0 / C.PHYSICS_HZ
        n = 0
        while self._acc >= h and n < C.MAX_SUBSTEPS:
            self.space.step(h)
            self.t += h
            self._acc -= h
            n += 1
        if n == C.MAX_SUBSTEPS:
            self._acc = 0.0
        if n:
            self._haft()
        if self._balance_dirty:
            self.update_balance()
        if self.fail is None:
            lost = next((it for it in self.items if it.lost), None)
            if lost is not None:
                self._set_fail("drop", lost)
            elif abs(self.bike.angle) > C.NO_RETURN_ANGLE:
                self._set_fail("tip", None)

    def _haft(self):
        """Resting items grip harder (round ones excepted: they must roll)."""
        for it in self.items:
            b = it.body
            if b.is_sleeping or it.rolls:
                continue
            resting = b.velocity.length < C.HAFT_SPEED and abs(b.angular_velocity) < C.HAFT_SPIN
            if resting != it.gripping:
                it.gripping = resting
                f = it.defn["friction"] * (C.HAFT_BOOST if resting else 1.0)
                for s in it.shapes:
                    s.friction = f

    def _set_fail(self, kind, item):
        self.fail = (kind, item)
        self.fail_t = self.t
        self.collapse()

    def collapse(self):
        """The stand lets go: no balance spring, the wheels hit the ground."""
        if self.collapsed:
            return
        self.collapsed = True
        self.space.remove(self.spring)
        wheels = []
        for wx, wy, r in (C.REAR_WHEEL, C.FRONT_WHEEL):
            w = pymunk.Circle(self.bike, r, (wx, wy + C.WHEEL_LIFT))
            w.friction = 0.9
            w.filter = pymunk.ShapeFilter(categories=CAT_BIKE, mask=CAT_GROUND | CAT_ITEM)
            wheels.append(w)
        self.space.add(*wheels)
        self.bike.activate()

    def boom(self, strength, rng):
        """Broforce part of the crash (spec §22): kick everything apart and
        let the bike go off its stand."""
        if self.pivot in self.space.constraints:
            self.space.remove(self.pivot)
        self.bike.apply_impulse_at_local_point((rng.uniform(-1, 1) * 2000 * strength, 4200 * strength), (0, C.DECK_TOP))
        self.bike.angular_velocity += rng.uniform(-1.5, 1.5) * strength
        for it in self.items:
            for b in it.bodies():
                b.activate()
                cx, _ = b.local_to_world(b.center_of_gravity)
                side = 1 if cx >= 0 else -1
                imp = C.CRASH_BOOM_IMPULSE * strength * b.mass
                b.apply_impulse_at_world_point((side * imp * rng.uniform(0.3, 1.2), imp * rng.uniform(0.6, 1.6)),
                                               b.local_to_world(b.center_of_gravity))
                b.angular_velocity += rng.uniform(-6, 6) * strength

    # ------------------------------------------------------------ stack metrics
    def top(self):
        """Highest point of the landed stack (at least the deck)."""
        top = C.DECK_TOP
        for it in self.landed_items():
            for s in it.shapes:
                top = max(top, s.bb.top)
        return top

    def extent(self):
        half = C.DECK_LEN / 2
        lo, hi = -half, half
        for it in self.landed_items():
            for s in it.shapes:
                lo, hi = min(lo, s.bb.left), max(hi, s.bb.right)
        return lo, hi

    def com(self):
        """(x, y, mass) of the landed load."""
        m = sx = sy = 0.0
        for it in self.landed_items():
            for b in it.bodies():
                x, y = b.local_to_world(b.center_of_gravity)
                m += b.mass
                sx += b.mass * x
                sy += b.mass * y
        return (sx / m, sy / m, m) if m else (0.0, C.DECK_TOP, 0.0)

    def load_torque(self):
        """Gravity torque of the landed load around the stand (debug overlay)."""
        x, _, m = self.com()
        return -m * C.GRAVITY * x

    def max_speed(self):
        return max((b.velocity.length for it in self.landed_items() for b in it.bodies()), default=0.0)

    # ------------------------------------------------------------ snapshots
    def snapshot(self, velocities=False):
        items = []
        for it in self.items:
            if it.lost:
                continue
            bodies = it.bodies()
            items.append((it.defn["id"], it.placer, it.index, it.landed, it.poses(),
                          [(tuple(b.velocity), b.angular_velocity) for b in bodies] if velocities else None))
        return {"bike": (self.bike.angle, self.bike.angular_velocity if velocities else 0.0), "items": items,
                "t": self.t}

    @classmethod
    def from_snapshot(cls, snap):
        world = cls()
        world.t = snap["t"]
        world.bike.angle, world.bike.angular_velocity = snap["bike"]
        for def_id, placer, index, landed, poses, vels in snap["items"]:
            a, x, y = poses[0]
            item = world._new_item(ITEMS_BY_ID[def_id], x, y, a, placer, index=index)
            item.landed = landed
            for (pa, px, py), b in zip(poses[1:], [b for _, b in item.parts]):
                set_pose(b, px, py, pa)
            if vels:
                for (v, w), b in zip(vels, item.bodies()):
                    b.velocity, b.angular_velocity = v, w
        world.update_balance()
        return world
