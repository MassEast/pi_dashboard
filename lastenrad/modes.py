# -*- coding: utf-8 -*-
"""Modes (spec §23-29), kept apart from the game loop: which items come in
which order, what counts as the score, which Bestenliste.

- Director: the difficulty director (spec §24). The sequence depends only on
  the seed and the item index, never on timing, so Tagesladung (date seed)
  is identical for the whole WG and Story levels are fixed lists.
- Story levels are plain data (spec §25): fixed item list and order, texts,
  optional conditions. Only one short demo level for now.
"""

import datetime
import random
from dataclasses import dataclass, field

from . import config as C
from .items import ITEMS_BY_ID

ENDLOS, TAGES, STORY, PARTY = "endlos", "tages", "story", "party"
LABELS = {ENDLOS: "Endlos", TAGES: "Tagesladung", STORY: "Story Modus", PARTY: "Party Modus"}


def today():
    """Tagesladung day (tests replace this)."""
    return datetime.date.today()


def day_seed(day):
    return f"lastenrad-tagesladung-{day.isoformat()}"


class Director:
    """Item n of a run: early big and stable, then rounder, longer, heavier,
    weirder; WTF items rare, people very rare and late."""

    def __init__(self, seed, mode=ENDLOS, fixed=None):
        self.rng = random.Random(seed)
        self.mode = mode
        self.fixed = list(fixed) if fixed is not None else None
        self.seq = []

    def get(self, n):
        """Item dict number n (0-based), or None when a fixed list ran out."""
        if self.fixed is not None:
            return ITEMS_BY_ID[self.fixed[n]] if n < len(self.fixed) else None
        while len(self.seq) <= n:
            self.seq.append(self._pick(len(self.seq)))
        return ITEMS_BY_ID[self.seq[n]]

    def _pick(self, n):
        rng = self.rng
        pool = [d for d in ITEMS_BY_ID.values() if self.mode in d["modes"] and d["earliest"] <= n]
        if n >= C.PERSON_EARLIEST and rng.random() < C.PERSON_CHANCE:
            people = [d for d in pool if "person" in d["tags"]]
            if people:
                return rng.choice(people)["id"]
        if n >= C.WTF_EARLIEST and rng.random() < C.WTF_CHANCE:
            wtf = [d for d in pool if ("wtf_a" in d["tags"] or "wtf_b" in d["tags"]) and "person" not in d["tags"]]
            if wtf:
                return self._weighted(wtf)["id"]
        normal = [d for d in pool if not ({"wtf_a", "wtf_b", "person"} & set(d["tags"]))]
        if n < C.SAFE_ITEMS:
            normal = [d for d in normal if d["difficulty"] == 1]
        recent = self.seq[-2:]
        normal = [d for d in normal if d["id"] not in recent] or normal
        if self.seq and "round" in ITEMS_BY_ID[self.seq[-1]]["tags"]:
            normal = [d for d in normal if "round" not in d["tags"]] or normal
        target = 1.0 + n / C.DIFFICULTY_RAMP
        weights = []
        for d in normal:
            dist = abs(d["difficulty"] - min(target, 4.6))
            easier = d["difficulty"] < target
            weights.append(d["rarity"] / (1.0 + dist * (0.7 if easier else 1.6)))
        return rng.choices(normal, weights)[0]["id"]

    def _weighted(self, items):
        return self.rng.choices(items, [d["rarity"] for d in items])[0]


@dataclass
class Level:
    """A deterministic story level (spec §25): same items, same order, same
    texts every time, so best times are comparable."""

    id: str
    title: str
    items: list
    intro: list  # [(speaker, line), ...] JRPG boxes before the level (spec §26/27)
    outro: list = field(default_factory=list)
    conditions: dict = field(default_factory=dict)  # later: e.g. {"no_round_on_deck": True}


LEVELS = [
    Level(
        id="rave1",
        title="Der erste Lastenrad-Rave",
        items=["bassbox", "flightcase", "klapptisch", "decke", "matekiste", "kabelrolle", "lichtkoffer", "discokugel"],
        intro=[
            ("Lef", "Heute Abend: der erste Lastenrad-Rave. Im Park. Ohne Genehmigung."),
            ("Lef", "Acht Sachen, ein Rad, eine Fahrt. Wer braucht schon Statik?"),
            ("Lef", "Nix darf runterfallen. Die Uhr läuft ab dem ersten Anfassen."),
        ],
        outro=[("Lef", "Hält. Hält? HÄLT! Ab in den Sonnenuntergang.")],
    ),
]
LEVELS_BY_ID = {lv.id: lv for lv in LEVELS}

# Lef's dry one-liners (spec §27), system only for now: shown rarely during a run.
LEF_LINES = [
    "Da passt noch 'ne Box drauf.",
    "Wer braucht schon Statik?",
    "Physik ist auch nur 'ne Meinung.",
    "Langsam. Oder schnell. Hauptsache oben.",
    "Das Rad hat schon Schlimmeres gesehen.",
]
LEF_LINE_EVERY = 9  # items between two lines


def score_key(name, mode, level=None):
    """One Bestenliste per mode (Endlos = the game's main list)."""
    if mode == ENDLOS:
        return name
    if mode == TAGES:
        return f"{name} TAGESLADUNG"
    if mode == STORY:
        return f"{name} STORY {level}"
    return None


def party_players(n):
    return [f"Spieler*in {i + 1}" for i in range(n)]
