# -*- coding: utf-8 -*-
"""The item library (spec §13-16), pure data: a new item is one dict here
plus (optionally) a detail painter in sprites.py - no game logic changes.

Shapes are in item-local units, y up, origin = the item's centre:
  ("box", w, h, cx, cy[, corner_radius])
  ("circle", r, cx, cy)
  ("capsule", length, thickness, cx, cy)        horizontal, rounded ends
  ("seg", x1, y1, x2, y2, radius)              thin tube (bike frames)
  ("poly", [(x, y), ...])                       convex
The sprite silhouette is painted from exactly these shapes, so what you see
is what collides (spec §3).

parts: extra bodies hinged to the item -
  {"kind": "wheel", "at": (x, y), "r": r, "mass": m}            free axle (rolls)
  {"kind": "limb", "at": (x, y), "shapes": [...], "mass": m,
   "limits": (lo, hi), "sprite": key}                            ragdoll joint (spec §14)

difficulty 1 (big, flat, obvious) .. 5 (round/long/absurd/heavy), rarity =
relative weight, earliest = first item index it may appear at, tags: round,
long, rolls, wtf_a (absurd but stackable), wtf_b (absurd shape), person.
modes: which modes may draw it at random ("all" or a tuple); story levels
list their items explicitly.
"""

from . import config as C

ALL_MODES = ("endlos", "tages", "party")

ITEMS = [
    # ---------------------------------------------------------------- early, big, obvious
    dict(id="bassbox", name="Bassbox", sprite="bassbox", shapes=[("box", 92, 112, 0, 0)],
         mass=5.0, friction=1.0, restitution=0.0, difficulty=1, rarity=1.4, earliest=0, tags=()),
    dict(id="flightcase", name="Flightcase", sprite="flightcase", shapes=[("box", 136, 64, 0, 0)],
         mass=4.0, friction=0.95, restitution=0.0, difficulty=1, rarity=1.3, earliest=0, tags=()),
    dict(id="matekiste", name="Mate-Kiste", sprite="matekiste", shapes=[("box", 104, 66, 0, 0)],
         mass=4.0, friction=1.0, restitution=0.0, difficulty=1, rarity=1.3, earliest=0, tags=()),
    dict(id="powerbank", name="Fette Powerbank", sprite="powerbank", shapes=[("box", 74, 44, 0, 0)],
         mass=3.0, friction=0.95, restitution=0.0, difficulty=1, rarity=0.9, earliest=0, tags=()),
    dict(id="tasche", name="Große Tasche", sprite="tasche", shapes=[("box", 124, 58, 0, 0, 10)],
         mass=3.0, friction=1.0, restitution=0.0, difficulty=1, rarity=1.0, earliest=0, tags=()),
    dict(id="snackkiste", name="Snackkiste", sprite="snackkiste", shapes=[("box", 96, 62, 0, 0)],
         mass=2.0, friction=1.0, restitution=0.0, difficulty=1, rarity=1.0, earliest=0, tags=()),
    dict(id="lichtkoffer", name="Lichtkoffer", sprite="lichtkoffer", shapes=[("box", 116, 52, 0, 0)],
         mass=3.0, friction=0.95, restitution=0.0, difficulty=1, rarity=1.0, earliest=0, tags=()),
    dict(id="klapptisch", name="Klapptisch", sprite="klapptisch",
         shapes=[("box", 168, 12, 0, 29), ("box", 10, 58, -72, -6), ("box", 10, 58, 72, -6)],
         mass=2.5, friction=1.0, restitution=0.0, difficulty=2, rarity=1.0, earliest=4, tags=("long",)),
    dict(id="decke", name="Gerollte Decke", sprite="decke", shapes=[("capsule", 126, 44, 0, 0)],
         mass=1.5, friction=1.0, restitution=0.0, difficulty=2, rarity=1.0, earliest=1, tags=()),
    dict(id="pfandsack", name="Pfandsack", sprite="pfandsack",
         shapes=[("poly", [(-30, -42), (30, -42), (46, -20), (46, 18), (26, 42), (-26, 42), (-46, 18), (-46, -20)])],
         mass=3.0, friction=1.0, restitution=0.0, difficulty=2, rarity=1.0, earliest=3, tags=()),
    dict(id="poitasche", name="Poi-Tasche", sprite="poitasche", shapes=[("box", 62, 44, 0, 0, 8)],
         mass=1.0, friction=1.0, restitution=0.0, difficulty=2, rarity=0.8, earliest=3, tags=()),
    # ---------------------------------------------------------------- round things roll
    dict(id="kabelrolle", name="Die gute Kabelrolle", sprite="kabelrolle", shapes=[("circle", 34, 0, 0)],
         mass=3.0, friction=0.95, restitution=0.05, angular_damping=C.ROLLING_ANGULAR_DAMPING,
         difficulty=3, rarity=1.0, earliest=7, tags=("round",)),
    dict(id="isomatte", name="Isomatte", sprite="isomatte", shapes=[("circle", 27, 0, 0)],
         mass=1.0, friction=1.0, restitution=0.0, angular_damping=C.ROLLING_ANGULAR_DAMPING,
         difficulty=3, rarity=0.8, earliest=8, tags=("round",)),
    dict(id="discokugel", name="Discokugel", sprite="discokugel", shapes=[("circle", 26, 0, 0)],
         mass=1.5, friction=0.5, restitution=0.25, angular_damping=0.85,
         difficulty=4, rarity=0.9, earliest=9, tags=("round",)),
    dict(id="kabeltrommel", name="Kabeltrommel XXL", sprite="kabeltrommel", shapes=[("circle", 48, 0, 0)],
         mass=5.0, friction=0.95, restitution=0.0, angular_damping=C.ROLLING_ANGULAR_DAMPING,
         difficulty=4, rarity=0.6, earliest=10, tags=("round",)),
    # ---------------------------------------------------------------- long, levers, platforms
    dict(id="dragonstaff", name="Dragonstaff", sprite="dragonstaff", shapes=[("capsule", 230, 14, 0, 0)],
         mass=1.2, friction=1.0, restitution=0.0, difficulty=3, rarity=0.8, earliest=6, tags=("long",)),
    dict(id="teppich", name="Langer Teppich", sprite="teppich", shapes=[("capsule", 250, 30, 0, 0)],
         mass=3.0, friction=1.0, restitution=0.0, difficulty=3, rarity=0.9, earliest=5, tags=("long",)),
    dict(id="staender", name="Boxenständer", sprite="staender",
         shapes=[("poly", [(-42, -60), (42, -60), (6, -22), (-6, -22)]), ("box", 10, 112, 0, 14)],
         mass=1.5, friction=1.0, restitution=0.0, difficulty=4, rarity=0.7, earliest=7, tags=("long",)),
    dict(id="stehlampe", name="Stehlampe", sprite="stehlampe",
         shapes=[("box", 54, 10, 0, -72), ("box", 8, 122, 0, -6), ("poly", [(-32, 54), (32, 54), (20, 84), (-20, 84)])],
         mass=2.0, friction=1.0, restitution=0.0, difficulty=4, rarity=0.7, earliest=8, tags=("long",)),
    # ---------------------------------------------------------------- awkward shapes
    dict(id="stuhl", name="Stuhl", sprite="stuhl",
         shapes=[("box", 58, 10, 0, -2), ("box", 8, 64, -25, 33), ("box", 8, 44, 25, -29), ("box", 8, 44, -25, -29)],
         mass=2.0, friction=1.0, restitution=0.0, difficulty=3, rarity=0.9, earliest=5, tags=()),
    dict(id="pflanze", name="Monstera", sprite="pflanze",
         shapes=[("poly", [(-24, -50), (24, -50), (30, -10), (-30, -10)]),
                 ("poly", [(-48, -10), (48, -10), (54, 18), (30, 48), (-30, 48), (-54, 18)])],
         mass=2.5, friction=1.0, restitution=0.0, difficulty=3, rarity=0.8, earliest=6, tags=()),
    dict(id="skateboard", name="Skateboard", sprite="skateboard", shapes=[("capsule", 124, 10, 0, 5)],
         parts=[{"kind": "wheel", "at": (-40, -8), "r": 8, "mass": 0.15},
                {"kind": "wheel", "at": (40, -8), "r": 8, "mass": 0.15}],
         mass=1.2, friction=0.95, restitution=0.0, difficulty=4, rarity=0.7, earliest=8, tags=("rolls",)),
    dict(id="einkaufswagen", name="Einkaufswagen", sprite="einkaufswagen",
         shapes=[("poly", [(-50, -16), (56, -16), (70, 52), (-60, 52)]),
                 ("poly", [(-62, 44), (-55, 44), (-74, 76), (-81, 76)]),
                 ("box", 6, 26, -40, -29), ("box", 6, 26, 46, -29)],
         parts=[{"kind": "wheel", "at": (-40, -44), "r": 10, "mass": 0.2},
                {"kind": "wheel", "at": (46, -44), "r": 10, "mass": 0.2}],
         mass=4.0, friction=0.95, restitution=0.0, difficulty=5, rarity=0.7, earliest=9, tags=("rolls",)),
    dict(id="flamingo", name="Flamingo-Lufttier", sprite="flamingo",
         shapes=[("poly", [(-56, -36), (40, -36), (58, -16), (48, 4), (-46, 4), (-62, -16)]),
                 ("seg", 38, 0, 52, 46, 7), ("circle", 11, 48, 56)],
         mass=0.8, friction=0.6, restitution=0.35, difficulty=4, rarity=0.6, earliest=11, tags=("wtf_b",)),
    # ---------------------------------------------------------------- WTF (spec §14): rare
    dict(id="pfeffi", name="12er Pfeffi", sprite="pfeffi", shapes=[("box", 84, 38, 0, 0)],
         mass=1.8, friction=1.0, restitution=0.0, difficulty=1, rarity=0.6, earliest=C.WTF_EARLIEST, tags=("wtf_a",)),
    dict(id="trophaee", name="Fundtrophäe", sprite="trophaee",
         shapes=[("poly", [(-16, 8), (16, 8), (30, 52), (-30, 52)]), ("box", 10, 20, 0, -2), ("box", 46, 14, 0, -19)],
         mass=1.5, friction=1.0, restitution=0.0, difficulty=3, rarity=0.5, earliest=C.WTF_EARLIEST, tags=("wtf_a",)),
    dict(id="sofa", name="Sperrmüll-Sofa", sprite="sofa",
         shapes=[("box", 212, 44, 0, -24), ("box", 172, 40, 0, 18), ("box", 26, 24, -93, 8), ("box", 26, 24, 93, 8)],
         mass=6.0, friction=1.0, restitution=0.0, difficulty=4, rarity=0.5, earliest=14, tags=("wtf_a",)),
    dict(id="lastenrad2", name="Noch ein Lastenrad", sprite="lastenrad2",
         shapes=[("seg", -56, -22, 0, -22, 3), ("seg", -56, -22, -24, 32, 3), ("seg", 0, -22, -24, 32, 3),
                 ("seg", -24, 32, 36, 32, 3), ("seg", 0, -22, 36, 32, 3), ("seg", 36, 32, 56, -22, 3),
                 ("box", 26, 7, -26, 37), ("seg", 36, 32, 30, 48, 3)],
         parts=[{"kind": "wheel", "at": (-56, -22), "r": 23, "mass": 0.5},
                {"kind": "wheel", "at": (56, -22), "r": 23, "mass": 0.5}],
         mass=3.5, friction=0.95, restitution=0.0, difficulty=5, rarity=0.35, earliest=18, tags=("wtf_b", "rolls")),
    dict(id="elefant", name="Warum ein Elefant?", sprite="elefant",
         shapes=[("poly", [(-92, -12), (74, -12), (94, 26), (70, 58), (-70, 58), (-98, 26)]),
                 ("poly", [(70, 6), (116, 18), (118, 56), (86, 64)]), ("seg", 114, 16, 122, -42, 8),
                 ("box", 30, 46, -62, -33), ("box", 30, 46, 46, -33)],
         mass=8.0, friction=1.0, restitution=0.0, difficulty=5, rarity=0.3, earliest=20, tags=("wtf_b",)),
    dict(id="raver", name="Afterhour-Zombie", sprite="raver",
         shapes=[("box", 30, 50, 0, 8), ("circle", 15, 0, 48)],
         parts=[{"kind": "limb", "at": (0, -14), "shapes": [("box", 22, 58, 0, -42)], "mass": 1.2,
                 "limits": (-1.3, 1.3), "sprite": "raver_legs"},
                {"kind": "limb", "at": (0, 26), "shapes": [("box", 10, 44, 6, 6)], "mass": 0.4,
                 "limits": (-2.6, 2.6), "sprite": "raver_arm"}],
         mass=2.2, friction=1.0, restitution=0.0, difficulty=5, rarity=0.25, earliest=C.PERSON_EARLIEST,
         tags=("person", "wtf_b")),
]

_SHAPE_KINDS = {"box", "circle", "capsule", "seg", "poly"}


def _validate(item):
    for key in ("id", "name", "sprite", "shapes", "mass", "difficulty", "rarity", "earliest"):
        if key not in item:
            raise ValueError(f"lastenrad item {item.get('id')!r}: missing {key!r}")
    for shape in item["shapes"] + [s for p in item.get("parts", ()) for s in p.get("shapes", ())]:
        if shape[0] not in _SHAPE_KINDS:
            raise ValueError(f"lastenrad item {item['id']!r}: unknown shape {shape[0]!r}")
    if len(item["name"]) > 20:
        raise ValueError(f"lastenrad item {item['id']!r}: name too long for the bar ({item['name']!r})")


def load_items():
    """id -> item dict with defaults filled in (validated once at import)."""
    out = {}
    for raw in ITEMS:
        _validate(raw)
        item = dict(friction=C.DEFAULT_FRICTION, restitution=0.0, angular_damping=None, parts=(), tags=(),
                    modes=ALL_MODES)
        item.update(raw)
        if item["id"] in out:
            raise ValueError(f"lastenrad item id {item['id']!r} twice")
        item["bbox"] = bbox(item)
        out[item["id"]] = item
    return out


def shape_bbox(shape):
    kind = shape[0]
    if kind == "box":
        _, w, h, cx, cy = shape[:5]
        return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    if kind == "circle":
        _, r, cx, cy = shape
        return cx - r, cy - r, cx + r, cy + r
    if kind == "capsule":
        _, length, t, cx, cy = shape
        return cx - length / 2, cy - t / 2, cx + length / 2, cy + t / 2
    if kind == "seg":
        _, x1, y1, x2, y2, r = shape
        return min(x1, x2) - r, min(y1, y2) - r, max(x1, x2) + r, max(y1, y2) + r
    xs, ys = [p[0] for p in shape[1]], [p[1] for p in shape[1]]
    return min(xs), min(ys), max(xs), max(ys)


def bbox(item):
    """(minx, miny, maxx, maxy) of the item incl. its parts at rest."""
    boxes = [shape_bbox(s) for s in item["shapes"]]
    for part in item.get("parts", ()):
        ax, ay = part["at"]
        if part["kind"] == "wheel":
            boxes.append((ax - part["r"], ay - part["r"], ax + part["r"], ay + part["r"]))
        else:
            boxes += [shape_bbox(s) for s in part["shapes"]]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


ITEMS_BY_ID = load_items()
