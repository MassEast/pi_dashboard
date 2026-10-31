#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless checks of KIEZ KAPERN (kiezkapern.py), simulated time (20 FPS steps):

- ready: corner taps do nothing, a tap starts the Schicht; corner/minimap taps
  never do anything while playing either.
- tap on the map: snaps to a road, the Lastenrad pathfinds there and arrives.
- every mission type can be completed: Lastenrad befreien (KAPERN! x3, bring it
  to the Hausprojekt), Soli-Suppe (AUFLADEN, deliver warm; also: gets cold ->
  failed), Kran kippen (3x LOCKERN, KIPPEN!), Werbung übermalen (paint.exe),
  Pfand sammeln.
- Mietspiegel: missions raise it, Hausprojekt / Kiezblock bollards / Späti
  hiding lower it, getting caught raises it; from 3 on the Mietenhai spawns and
  chases; a bike deep in a park leaves it stuck ("abgehängt").
- 5/5 -> "Rausmodernisiert!" -> game over, stored in the Bestenliste (temp
  dir); end of Schicht -> over, stored too; Bilanz -> tap -> Bestenliste.
- performance: a busy frame (level 4: bots, drones, shark, particles) stays
  far below 25 ms on the laptop (prints ms).

Screenshots: scratch/game_mockups/kiez_sandbox/real/ (gitignored).
SDL_VIDEODRIVER=dummy .venv/bin/python dev/test_kiezkapern.py
"""

import os
import statistics
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import pygame  # noqa: E402

import PiDashboard as P  # noqa: E402  (configures pygame display + kiezos)
import kiezkapern as KK  # noqa: E402
import kiezos as K  # noqa: E402
import party_games  # noqa: E402

OUT = os.path.join(REPO, "scratch", "game_mockups", "kiez_sandbox", "real")
os.makedirs(OUT, exist_ok=True)
party_games.configure(tempfile.mkdtemp(prefix="kiezkapern_scores_"))
K.ICON_MAKERS["kiezkapern"] = KK.menu_icon
FRAME = 0.05
SCREEN = pygame.Surface((480, 800))
GAME_SURF = SCREEN.subsurface((0, 36, 480, 764))


def new_game():
    g = KK.KiezKapernGame(480, 764, P.FONT_PATH + P.FONT_MEDIUM, P.FONT_PATH + P.FONT_BOLD)
    g.show_close = False
    g.reset(0.0)
    g.rng.seed(5)
    return g


def frames(g, n):
    for _ in range(n):
        g.update(g.last_tick + FRAME)


def shot(g, name):
    g.draw(GAME_SURF)
    K.game_title(SCREEN, "kiezkapern.exe", "kiezkapern")
    pygame.image.save(SCREEN, os.path.join(OUT, name))


def drive_to(g, pos, max_s=40.0, r=KK.NEAR - 6):
    """Route (like NAVI / a map tap) until the bike is within r px of pos."""
    t0 = g.schicht
    while (g.x - pos[0]) ** 2 + (g.y - pos[1]) ** 2 > r * r:
        assert g.state == "play", g.over_text
        assert g.schicht - t0 < max_s, f"bike stuck at {g.bike_tile()} -> {KK.tile_of(*pos)}"
        if not g.path:
            assert g.route_to_tile(KK.tile_of(*pos)), "no path"
        frames(g, 1)


def press_act(g, expect=None):
    if expect is not None:
        label = g.action_label()[0]
        assert label == expect, (label, expect)
    assert g.tap(*KK.ACT_RECT.center) is None
    frames(g, 2)


def fresh_mission(g, kind):
    g.mission = None
    g.new_mission(kind)
    frames(g, 1)
    return g.mission


def test_ready_and_start(g):
    shot(g, "01_start.png")
    for xy in [(10, 10), (60, 100), (99, 143)]:
        g.tap(*xy)
        frames(g, 2)
        assert g.state == "ready", "corner tap must not start"
    g.tap(240, 600)
    assert g.state == "play"
    frames(g, 12)
    assert g.mission is not None and g.mission["kind"] == "rad", g.mission
    print("ready -> play ok, first mission: Lastenrad befreien", flush=True)


def test_tap_to_drive(g):
    start = g.bike_tile()
    # a road tile ~5 tiles right and ~6 down, tapped on screen
    goal = next(t for t in [(start[0] + dx, start[1] + dy) for dy in range(4, 9) for dx in range(3, 8)] if t in g.city.car)
    sx, sy = g.to_screen(*KK.tile_center(*goal))
    assert KK.VIEW.collidepoint(sx, sy) and not KK.NO_TAP.collidepoint(sx, sy)
    g.tap(sx + 5, sy - 4)
    assert g.path, "tap on the map must start a route"
    frames(g, 4)
    shot(g, "02_driving.png")
    for _ in range(200):
        if not g.path:
            break
        frames(g, 1)
    assert g.bike_tile() == goal, (g.bike_tile(), goal)
    # tap on a house: snaps to the nearest road
    hx, hy = next(((x, y) for y in range(goal[1] - 4, goal[1] + 5) for x in range(goal[0] - 4, goal[0] + 5)
                   if g.city.at(x, y) == KK.HOUSE))
    sx, sy = g.to_screen(*KK.tile_center(hx, hy))
    if KK.VIEW.collidepoint(sx, sy) and not KK.MINI.inflate(8, 8).collidepoint(sx, sy):
        g.tap(sx, sy)
        assert g.path and g.city.bikeable(*KK.tile_of(*g.target))
        frames(g, 120)
    # corner + minimap taps do nothing while playing
    g.path = []
    before = (g.x, g.y, g.score, g.level)
    for xy in [(20, 20), (50, 120), (90, 140), (40, 170)]:
        assert g.tap(*xy) is None
        assert not g.path, f"tap at {xy} must not route"
    frames(g, 3)
    assert (g.x, g.y) == before[:2]
    print(f"tap-to-drive ok: {start} -> {goal}, corner/minimap taps ignored", flush=True)


def test_rad(g):
    m = g.mission
    assert m["kind"] == "rad"
    drive_to(g, m["target"])
    shot(g, "03_rad_befreien.png")
    press_act(g, "KAPERN!")
    press_act(g, "KAPERN!")
    assert m["phase"] == "find" and m["lock"] == 2
    press_act(g, "KAPERN!")
    assert m["phase"] == "bring" and g.level == 1, (m["phase"], g.level)
    frames(g, 3)
    shot(g, "04_rad_befreit.png")
    cash = g.score
    drive_to(g, m["target"], r=30)
    frames(g, 2)
    assert g.mission is None or g.mission is not m
    assert g.score >= cash + 800 and g.counts["rad"] == 1
    assert g.level == 0, "Hausprojekt lowers the Mietspiegel"
    print(f"mission Lastenrad ok: {KK.fmt_eur(g.score)}, Mietspiegel back to {g.level}", flush=True)


def test_suppe(g):
    m = fresh_mission(g, "suppe")
    drive_to(g, m["target"])
    press_act(g, "AUFLADEN")
    assert m["phase"] == "deliver" and m["temp"] > 70
    frames(g, 30)
    shot(g, "05_soli_suppe.png")
    cash = g.score
    drive_to(g, m["target"], r=30)
    frames(g, 2)
    assert g.counts["suppe"] == 1 and g.score > cash + 400, (g.counts, g.score - cash)
    # cold soup = failed mission
    m = fresh_mission(g, "suppe")
    drive_to(g, m["target"])
    press_act(g, "AUFLADEN")
    m["temp"] = KK.SOUP_MIN + 0.01
    frames(g, 2)
    assert g.mission is None and g.counts["suppe"] == 1
    print(f"mission Soli-Suppe ok (+{KK.fmt_eur(g.score - cash)}), cold soup fails", flush=True)


def test_kran(g):
    m = fresh_mission(g, "kran")
    level0 = g.level
    for i in range(3):
        drive_to(g, m["target"])
        press_act(g, "LOCKERN")
    assert all(m["loose"]) and m["phase"] == "tip"
    shot(g, "06_kran_schrauben.png")
    press_act(g, "KIPPEN!")
    assert m["site"] in g.toppled and g.counts["kran"] == 1
    assert g.level == min(5, level0 + 2), (level0, g.level)
    frames(g, 6)
    shot(g, "07_kran_kippt.png")
    print(f"mission Kran kippen ok, Mietspiegel {level0} -> {g.level}", flush=True)


def test_malen(g):
    m = fresh_mission(g, "malen")
    drive_to(g, m["target"])
    press_act(g, "MALEN")
    assert g.paint is not None
    _, _, _, canvas = g._paint_layout()
    g.tap(canvas.x + 40, canvas.y + 40)
    g.drag(canvas.x + 120, canvas.y + 60)
    g.drag(canvas.x + 200, canvas.y + 60)
    frames(g, 2)
    shot(g, "08_paint_exe.png")
    taps = 0
    for row in range(KK.PAINT_ROWS):
        for col in range(KK.PAINT_COLS):
            if (col, row) not in g.paint["cells"]:
                cw, ch = canvas.w / KK.PAINT_COLS, canvas.h / KK.PAINT_ROWS
                g.tap(int(canvas.x + (col + 0.5) * cw), int(canvas.y + (row + 0.5) * ch))
                taps += 1
                frames(g, 1)
            if g.paint is None or g.paint["done_at"] is not None:
                break
    frames(g, 4)
    shot(g, "09_paint_fertig.png")
    frames(g, 20)
    assert g.paint is None and g.counts["malen"] == 1 and m["board"] in g.painted
    print(f"mission Werbung übermalen ok ({taps} more taps)", flush=True)


def test_pfand(g):
    m = fresh_mission(g, "pfand")
    frames(g, 4)
    shot(g, "10_pfand.png")
    while g.mission is m:
        drive_to(g, m["target"], r=20)
        frames(g, 1)
    assert g.counts["pfand"] == 1
    print("mission Pfand sammeln ok", flush=True)


def test_spaeti(g):
    g.mission = None
    g.next_mission_t = 1e9
    g.set_level(3)
    door = min(g.city.spaeti_doors, key=lambda d: abs(d[0] - g.bike_tile()[0]) + abs(d[1] - g.bike_tile()[1]))
    g.invuln_until = 1e9
    drive_to(g, KK.tile_center(*door))
    press_act(g, "ABTAUCHEN")
    assert g.hidden == door
    frames(g, 30)
    shot(g, "11_spaeti.png")
    frames(g, int(2 * KK.HIDE_DROP_SECONDS / FRAME) + 4)
    assert g.level <= 1, g.level
    frames(g, int(KK.HIDE_DROP_SECONDS / FRAME) + 4)
    assert g.level == 0
    press_act(g, "RAUS")
    assert g.hidden is None
    print("Späti hiding ok: Mietspiegel 3 -> 0", flush=True)


def test_kiezblock(g):
    g.set_level(2)
    a, b = KK.POLLER[0]
    # ride across the bollard pair: from one side to the other
    if a[1] == b[1]:
        before, after = (a[0], a[1] - 2), (a[0], a[1] + 2)
    else:
        before, after = (a[0] - 2, a[1]), (a[0] + 2, a[1])
    drive_to(g, KK.tile_center(*before), max_s=60, r=6)  # (this route may cross the bollards already)
    g.poller_cd = {}
    g.set_level(2)
    level = g.level
    drive_to(g, KK.tile_center(*after), r=6)
    assert g.level == level - 1, (level, g.level)
    print(f"Kiezblock ok: Mietspiegel {level} -> {g.level}", flush=True)


def test_mietenhai(g):
    g.invuln_until = 0
    g.set_level(3)
    for _ in range(80):
        frames(g, 1)
        if any(mb.kind == "shark" for mb in g.mobs):
            break
    shark = next(mb for mb in g.mobs if mb.kind == "shark")
    assert g.banner and g.banner[1] == "MIETENHAI IM KIEZ"
    g.invuln_until = 1e9  # watch the chase without being caught
    d0 = ((shark.x - g.x) ** 2 + (shark.y - g.y) ** 2) ** 0.5
    frames(g, 40)
    d1 = ((shark.x - g.x) ** 2 + (shark.y - g.y) ** 2) ** 0.5
    assert d1 < d0 - 60, f"shark must chase: {d0:.0f} -> {d1:.0f} px"
    # screenshot: shark close behind on the road
    bt = g.bike_tile()
    near = min((t for t in g.city.car if 5 <= abs(t[0] - bt[0]) + abs(t[1] - bt[1]) <= 6), key=lambda t: abs(t[1] - bt[1]))
    shark.x, shark.y = KK.tile_center(*near)
    shark.way = None
    frames(g, 6)
    g.bubble = (["INDEX-MIETE! INDEX-MIETE!"], shark, g.t + 2)
    shot(g, "12_mietenhai_jagd.png")
    # escape into a park: the shark can't follow and gets stuck
    park_mid = (2 * KK.PER + 5, 2 * KK.PER + 5)
    assert g.city.at(*park_mid) == KK.PATH
    hai = g.counts["hai"]
    drive_to(g, KK.tile_center(*park_mid), max_s=60, r=6)
    shark = next(mb for mb in g.mobs if mb.kind == "shark")
    shark.x, shark.y = KK.tile_center(2 * KK.PER + 5, 2 * KK.PER + 1)  # on the road at the park's edge
    shark.way = None
    frames(g, 12)
    assert shark.stuck and g.counts["hai"] >= hai + 1, (shark.stuck, hai, g.counts["hai"])
    x, y = shark.x, shark.y
    frames(g, 20)
    assert (shark.x, shark.y) == (x, y), "a stuck shark stays put"
    shot(g, "13_hai_abgehaengt.png")
    print(f"Mietenhai ok: chases ({d0:.0f} -> {d1:.0f} px), stuck at the park ({g.counts['hai']}x abgehängt)", flush=True)


def test_caught_and_rausmodernisiert(g):
    g.invuln_until = 0
    g.hidden = None
    g.set_level(4)
    lvl = g.level
    bot = KK.Mob("bot", g.x + 10, g.y)
    g.mobs.append(bot)
    frames(g, 1)
    assert g.state == "over" and g.level == 5 and g.rausmod, (g.state, g.level)
    assert lvl == 4
    entries = party_games.top_list(g.NAME)
    assert any(e.get("id") == g.entry_id or e is not None for e in entries) and g.place is not None
    frames(g, 10)
    shot(g, "14_rausmodernisiert.png")
    # corner taps do nothing in "over" either
    frames(g, 30)
    assert g.bilanz
    g.tap(30, 30)
    assert g.bilanz
    shot(g, "15_bilanz.png")
    g.tap(240, 700)
    assert not g.bilanz
    g.update(g.last_tick + 0.1)
    shot(g, "16_bestenliste.png")
    print(f"caught at 4/5 -> 5/5 -> Rausmodernisiert, stored at place {g.place + 1}, score {KK.fmt_eur(g.score)}", flush=True)


def test_schicht_end():
    g = new_game()
    g.tap(240, 600)
    frames(g, 10)
    g.schicht = KK.SCHICHT_SECONDS - 0.2
    frames(g, 6)
    assert g.state == "over" and g.over_text in KK.OVER_TIME and not g.rausmod
    assert len(party_games.top_list(g.NAME)) == 2
    frames(g, 34)
    shot(g, "17_schicht_vorbei.png")
    # NOCHMAL via the leaderboard
    g.tap(240, 700)
    g.update(g.last_tick + 0.1)
    g.draw(GAME_SURF)
    again = g.buttons["again"]
    # regression: NOCHMAL sits where the Bilanz's "Weiter" was; a double tap must not restart right away
    g.tap(*again.center)
    assert g.state == "over", "double tap on Weiter skipped the Bestenliste"
    frames(g, int(party_games.GAME_OVER_TAP_DELAY_SECONDS / FRAME) + 1)
    g.draw(GAME_SURF)
    g.tap(*g.buttons["again"].center)
    assert g.state == "ready"
    print("end of Schicht -> over, stored (2 rounds in the Bestenliste), NOCHMAL -> ready", flush=True)


def test_perf():
    g = new_game()
    g.tap(240, 600)
    frames(g, 10)
    g.invuln_until = 1e9
    g.set_level(4)
    frames(g, 160)  # let bots, drones, shark spawn and close in
    g.route_to_tile((g.bike_tile()[0] + 9, g.bike_tile()[1]))
    times = []
    for i in range(200):
        if i % 20 == 0:
            g._burst(g.x, g.y, 30, [KK.WHITE, KK.RED], speed=300)
            g._popup("+1,00 €", g.x, g.y)
        if not g.path:
            g.route_to_tile(g.rng.choice([t for t in g.city.car if abs(t[0] - g.bike_tile()[0]) + abs(t[1] - g.bike_tile()[1]) < 12]))
        t = time.perf_counter()
        g.update(g.last_tick + FRAME)
        g.draw(GAME_SURF)
        times.append((time.perf_counter() - t) * 1000)
    kinds = sorted(mb.kind for mb in g.mobs)
    shot(g, "18_busy_frame.png")
    mean, p95, worst = statistics.mean(times), sorted(times)[int(len(times) * 0.95)], max(times)
    print(f"busy frame (Mietspiegel {g.level}, mobs {kinds}, {len(g.parts)} particles): "
          f"mean {mean:.2f} ms, p95 {p95:.2f} ms, max {worst:.2f} ms", flush=True)
    assert p95 < 25, p95
    return mean, p95, worst


def test_texts_fit():
    """Regression: long mission texts were squeezed to 12-13 px in the HUD and overflowed the banner."""
    hud_w = KK.W - 16 - 40
    texts = ["Lastenrad von ROLLKAPITAL befreien!", "Lastenrad ins Hausprojekt bringen!", "Soli-Suppe in der SOLI-KÜCHE abholen",
             "LUXUS-LOFTS-Kran: 3 Schrauben lockern", "LUXUS-LOFTS-Kran: 2/3 Schrauben locker", "3/3 Schrauben locker: Kran KIPPEN!",
             "Pfand sammeln: 6/6 Flaschen (45 s)", "Warte auf die nächste Mission..."]
    texts += [KK.soup_text(p) for p in KK.SOUP_PLACES] + ["Werbung übermalen: " + KK.ad_name(ad) for ad in KK.ADS]
    for t in texts:
        assert K.font(15).size(t)[0] <= hud_w, f"HUD text needs < 15 px: {t}"
    assert KK.ad_name(["MIETPREIS-", "BREMSE?", "LOL."]) == "MIETPREIS-BREMSE?"
    g = new_game()
    g.tap(240, 600)
    frames(g, 2)
    for text in texts + ["Pfand-Zeit vorbei. Die Flaschen finden andere.", "Suppe kalt. Nächstes Mal schneller!"]:
        g.banner = ("NEUE MISSION", text, g.t, 2.0)
        lines = g._banner_lines()
        assert 1 <= len(lines) <= 2 and " ".join(lines) == text, (text, lines)
        assert all(K.font(15).size(ln)[0] <= KK.BANNER_TEXT_W for ln in lines), lines
        g.draw(GAME_SURF)
    print(f"texts ok: {len(texts)} HUD lines fit at >= 15 px, banners wrap to <= 2 lines", flush=True)


def test_map_reachability():
    """Every bike tile is reachable from the start, every car tile is a bike tile, every map tap snaps to a road."""
    c = KK.city()
    bike = {(x, y) for y in range(KK.N) for x in range(KK.N) if c.bikeable(x, y)}
    seen, todo = {KK.START_TILE}, [KK.START_TILE]
    while todo:
        x, y = todo.pop()
        for t in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if t in bike and t not in seen:
                seen.add(t)
                todo.append(t)
    assert seen == bike and c.car <= bike, "the bike graph must be one connected piece"
    assert all(c.nearest_bikeable(x, y) for y in range(KK.N) for x in range(KK.N)), "a tap must always snap to a road"
    for (tile, road) in c.billboards:
        assert road in seen
    for site in KK.SITES:
        bx, by = site
        for b in [(bx * KK.PER + 4, by * KK.PER + 1), (bx * KK.PER + KK.PER, by * KK.PER + 6), (bx * KK.PER + 6, by * KK.PER + KK.PER)]:
            assert b in c.car, b
    print(f"map ok: {len(bike)} bike tiles in one piece, every tap snaps to a road", flush=True)


def test_rad_rack():
    """Regression: on a crossing the ROLLKAPITAL rack stood on the road and the bike parked on top of it."""
    g = new_game()
    g.tap(240, 600)
    frames(g, 2)
    for seed in range(60):
        g.rng.seed(seed)
        g.x, g.y = KK.tile_center(*g.rng.choice(sorted(g.city.car)))
        g.mission = None
        g.new_mission("rad")
        m = g.mission
        rack, road = KK.tile_of(*m["rack"]), KK.tile_of(*m["target"])
        assert g.city.at(*rack) == KK.WALK and abs(rack[0] - road[0]) + abs(rack[1] - road[1]) == 1, (rack, road)
    print("Lastenrad racks always on a sidewalk next to the road ok", flush=True)


def test_reward_before_rausmodernisiert():
    """Regression: KIPPEN!/MALEN at a high Mietspiegel ended the round before the reward was paid."""
    g = new_game()
    g.tap(240, 600)
    frames(g, 2)
    g.invuln_until = 1e9
    m = fresh_mission(g, "kran")
    m["loose"] = [True] * 3
    m["phase"] = "tip"
    g.set_level(3)
    cash = g.score
    g.x, g.y = KK.tile_center(*m["bolts"][0])
    press_act(g, "KIPPEN!")
    assert g.state == "over" and g.rausmod
    assert g.score == cash + 1500 and g.counts["kran"] == 1, (g.score - cash, g.counts)
    assert party_games.top_list(g.NAME)[g.place]["score"] == g.score, "stored result must include the crane"
    frames(g, 40)
    g.draw(GAME_SURF)
    lst, btn = g.bilanz_rects
    assert lst.bottom <= btn.top - 4, "Bilanz Bestenliste runs into the Weiter button"
    assert g._ctrl_key[0] == "AKTION", "no stale KAPERN! on the control bar after the end"

    g = new_game()
    g.tap(240, 600)
    frames(g, 2)
    m = fresh_mission(g, "malen")
    g.x, g.y = m["target"]
    g.set_level(4)
    press_act(g, "MALEN")
    assert g.action_label()[2] is False, "AKTION must be disabled while paint.exe is open"
    g.paint["cells"] = {(c, r) for c in range(KK.PAINT_COLS) for r in range(KK.PAINT_ROWS)}
    g.paint["done_at"] = g.t
    cash = g.score
    frames(g, 30)
    assert g.state == "over" and g.score == cash + 400 and g.counts["malen"] == 1, (g.state, g.score - cash)
    print("rewards paid before a 5/5 ends the round; Bilanz list fits; AKTION off in paint.exe ok", flush=True)


def test_overlay_layout():
    """Regression: the target arrow hid under the mission banner, its 'Ziel' label sat on the arrow,
    bubbles overlapped the banner, popups printed over each other."""
    g = new_game()
    g.tap(240, 600)
    frames(g, 2)
    g.invuln_until = 1e9
    g.next_mission_t = 1e9
    for target in [(36, 0), (36, 63), (0, 27), (63, 27), (0, 0), (63, 63)]:
        g.mission = {"kind": "rad", "phase": "bring", "target": KK.tile_center(*target), "text": "x", "icon": "ok", "born": 0}
        g.x, g.y = KK.tile_center(36, 27)
        g.cam = [g.x - KK.VIEW.w / 2, g.y - KK.VIEW.h / 2 + 30]
        g._clamp_cam()
        g.banner = ("MISSION VERPASST", "Pfand-Zeit vorbei. Die Flaschen finden andere.", g.t, 2.0)
        g.mobs = [KK.Mob("shark", g.x, g.y - 250)]
        g.mobs[0].stun_until = 1e9
        g.bubble = (["Ich muss nur kurz aufwerten!"], g.mobs[0], g.t + 2)
        g.draw(GAME_SURF)
        banner = g._banner_rect()
        arrow = pygame.Rect(0, 0, 44, 44)
        arrow.center = g.arrow_at
        assert not arrow.colliderect(banner), f"arrow to {target} under the banner"
        assert not g.arrow_label.colliderect(arrow.inflate(-8, -8)), f"Ziel label on the arrow to {target}"
        assert not g.arrow_label.colliderect(banner) and not g.arrow_label.colliderect(KK.MINI)
        assert g.bubble_rect is None or not g.bubble_rect.colliderect(banner), "bubble over the banner"
        assert KK.VIEW.contains(g.arrow_label) and not KK.NO_TAP.colliderect(g.arrow_rect.clip(KK.VIEW))
    g.popups = []
    for text in ("KNACK! 2/3", "Mietspiegel +1", "+8,00 €"):
        g._popup(text, g.x, g.y - 40)
    ys = sorted(p[2] for p in g.popups)
    assert all(b - a >= 22 for a, b in zip(ys, ys[1:])), ys
    # Späti at Mietspiegel 0: hiding is pointless, the button stays NAVI
    g.mobs, g.bubble, g.banner = [], None, None
    g.set_level(0)
    g.mission = {"kind": "rad", "phase": "bring", "target": KK.tile_center(*KK.HAUSPROJEKT_DOOR), "text": "x", "icon": "ok", "born": 0}
    g.x, g.y = KK.tile_center(*g.city.spaeti_doors[0])
    assert g.action_label()[0] == "NAVI"
    g.set_level(2)
    assert g.action_label()[0] == "ABTAUCHEN"
    print("overlays ok: arrow below banner, label beside arrow, bubble below banner, popups stacked", flush=True)


def test_slow_frames():
    """Below 20 FPS the game used to run in slow motion (party_games caps a frame at 0.05 s):
    now up to 0.25 s per frame is caught up in sub-steps. 0 s and 1 s frames must not break anything."""
    g = new_game()
    g.tap(240, 600)
    frames(g, 2)
    s0 = g.schicht
    for _ in range(20):
        g.update(g.last_tick + 0.1)  # 10 FPS
    assert abs(g.schicht - s0 - 2.0) < 1e-6, g.schicht - s0
    g.update(g.last_tick + 5.0)  # a stall: only 0.25 s is simulated
    assert abs(g.schicht - s0 - 2.25) < 1e-6
    for i in range(400):
        g.update(g.last_tick + (0.0 if i % 2 else 1.0))
        g.draw(GAME_SURF)
        if g.state != "play":
            break
    print(f"slow frames ok: 10 FPS keeps real time, 0 s / 1 s frames survive ({g.state})", flush=True)


def bot_round(seed, careful=True, max_frames=4000):
    """A bot plays a whole Schicht through the real tap() paths: NAVI / target arrow, every AKTION,
    paint.exe; careful = hides in a Späti before anything would push the Mietspiegel to 5/5.
    Returns (game, frame ms list, missions open > 70 s)."""
    import random
    random.seed(seed)
    g = new_game()
    g.rng.seed(seed)
    g.tap(240, 600)
    times, born, stuck = [], {}, []
    for f in range(max_frames):
        t = time.perf_counter()
        g.update(g.last_tick + FRAME)
        g.draw(GAME_SURF)
        times.append((time.perf_counter() - t) * 1000)
        if g.state != "play":
            break
        if g.mission is not None:
            k = g.missions_started
            born.setdefault(k, g.schicht)
            if g.schicht - born[k] > 70 and k not in stuck:
                stuck.append(k)
        if f % 3:
            continue
        if g.paint is not None:
            _, _, _, canvas = g._paint_layout()
            todo = [(c, r) for r in range(KK.PAINT_ROWS) for c in range(KK.PAINT_COLS) if (c, r) not in g.paint["cells"]]
            if todo:
                c, r = random.choice(todo)
                g.tap(int(canvas.x + (c + .5) * canvas.w / KK.PAINT_COLS), int(canvas.y + (r + .5) * canvas.h / KK.PAINT_ROWS))
            continue
        label, sub, enabled, kind = g.action_label()
        spaeti = isinstance(kind, tuple) and kind[0] == "spaeti"
        if g.hidden:
            if g.level == 0:
                g.tap(*KK.ACT_RECT.center)
            continue
        raise_by = {"kippen": 2, "malen": 1}.get(kind if isinstance(kind, str) else "", 0)
        if kind == "kapern" and g.mission["lock"] == 2:
            raise_by = 1
        if careful and (g.level >= 3 or g.level + raise_by >= 5):
            if spaeti:
                g.tap(*KK.ACT_RECT.center)
            elif not g.path or KK.tile_of(*g.target) not in g.city.spaeti_doors:
                door = min(g.city.spaeti_doors, key=lambda d: abs(d[0] - g.bike_tile()[0]) + abs(d[1] - g.bike_tile()[1]))
                g.route_to_tile(door)
            continue
        if kind and kind != "navi" and not spaeti:
            g.tap(*KK.ACT_RECT.center)
        elif random.random() < 0.02:
            g.tap(*KK.BELL_RECT.center)
        elif not g.path and kind == "navi":
            g.tap(*KK.ACT_RECT.center)
        elif not g.path and g.mission and g.mission.get("target"):
            g.tap(*(g.arrow_rect.center if g.arrow_rect else g.to_screen(*g.mission["target"])))
    return g, times, stuck


def test_bot_rounds():
    """Long sessions: whole Schichten with different seeds, careful and reckless, no stuck mission."""
    results = []
    for seed, careful in [(1, True), (2, True), (3, True), (4, False), (5, False)]:
        g, times, stuck = bot_round(seed, careful)
        c = g.counts
        print(f"  bot seed {seed} {'careful ' if careful else 'reckless'}: {g.over_text:40s} {KK.fmt_eur(g.score):>9s}, "
              f"{g.missions_started} missions, max Mietspiegel {g.max_level}, frame p95 {sorted(times)[int(len(times) * .95)]:.2f} ms",
              flush=True)
        assert g.state == "over" and not stuck, (seed, stuck)
        assert g.place is not None and party_games.top_list(g.NAME)[g.place]["score"] == g.score
        results.append((careful, g))
    held = [g for careful, g in results if careful and not g.rausmod]
    assert len(held) >= 2, "careful players should mostly hold the Kiez for the whole 3 min"
    for g in held:
        assert g.missions_started >= 10 and min(g.counts[k] for k in ("rad", "suppe", "kran", "malen", "pfand")) >= 1, g.counts
    print("bot rounds ok: careful bots finish the Schicht with every mission type done, no mission ever stuck", flush=True)


def main():
    t0 = time.perf_counter()
    g = new_game()
    print(f"city build + first reset: {(time.perf_counter() - t0) * 1000:.0f} ms", flush=True)
    test_ready_and_start(g)
    test_tap_to_drive(g)
    g.invuln_until = 1e9  # mission tests: no catching (tested separately)
    test_rad(g)
    test_suppe(g)
    test_kran(g)
    test_malen(g)
    test_pfand(g)
    test_spaeti(g)
    test_kiezblock(g)
    test_mietenhai(g)
    test_caught_and_rausmodernisiert(g)
    test_schicht_end()
    test_texts_fit()
    test_map_reachability()
    test_rad_rack()
    test_reward_before_rausmodernisiert()
    test_overlay_layout()
    test_slow_frames()
    test_bot_rounds()
    mean, p95, worst = test_perf()
    print(f"\nALL KIEZ KAPERN CHECKS PASSED in {time.perf_counter() - t0:.1f} s; busy frame mean {mean:.2f} ms / "
          f"p95 {p95:.2f} ms (budget 25 ms); screenshots in {OUT}", flush=True)


if __name__ == "__main__":
    main()
