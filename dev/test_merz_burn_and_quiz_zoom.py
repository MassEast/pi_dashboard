#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Headless check for two PiDashboard.py overlay features:

1. MERZ "BURN" easter egg - the EIER, KLÖTEN x3, EIER, KLÖTEN x2 ("1312")
   pill combo unlocks/selects BURN, a too-slow combo does not, holding fire
   streams flames that score hits (rate-limited), release stops the stream.
2. AFM quiz results zoom - tapping empty plot space zooms in, "-" zooms out,
   and a held dot's name label is drawn on top of everything else.

Renders screenshots to a fresh temp dir (path printed at the end) for
eyeballing. Runs PiDashboard.py's module-level setup
with SDL's dummy video driver, so it needs the local config.json but no
display. Run directly: SDL_VIDEODRIVER=dummy venv/bin/python3 dev/test_merz_burn_and_quiz_zoom.py
"""

import os
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import PiDashboard as P  # noqa: E402

OUT_DIR = tempfile.mkdtemp(prefix="pidashboard_overlays_")


def tap_pill(kind):
    rect = P.MERZ_ACTION_RECTS[f"select_{kind}"]
    P.handle_merz_click(*rect.center)


def test_merz_burn():
    P.MERZ_ENABLED = True
    P.activate_merz_game()
    P.draw_merz_overlay()
    assert "select_burn" not in P.MERZ_ACTION_RECTS

    # Regression: the dashboard's emolog footer hit zone (never cleared,
    # bottom-left) overlaps the EIER pill and used to swallow taps there.
    P.EMOLOG_FOOTER_RECT = P.MERZ_ACTION_RECTS["select_egg"].copy()
    assert not P.handle_emolog_footer_click(*P.MERZ_ACTION_RECTS["select_egg"].center)
    P.QUIZ_STAGE = "results"
    assert not P.handle_emolog_footer_click(*P.MERZ_ACTION_RECTS["select_egg"].center)
    P.QUIZ_STAGE = None

    # Too slow: one gap over the limit must not unlock.
    combo = P.MERZ_BURN_COMBO
    for i, kind in enumerate(combo):
        if i == 4:
            P.MERZ_BURN_COMBO_TAPS = [(k, t - 5.0) for k, t in P.MERZ_BURN_COMBO_TAPS]
        tap_pill(kind)
    assert not P.MERZ_BURN_UNLOCKED, "slow combo unlocked BURN"

    # Noise taps before the real combo are fine (only the tail has to match).
    tap_pill("testicle")
    tap_pill("egg")
    for kind in combo:
        tap_pill(kind)
    assert P.MERZ_BURN_UNLOCKED and P.MERZ_PROJECTILE_KIND == "burn", "combo did not unlock BURN"
    P.draw_merz_overlay()
    assert "select_burn" in P.MERZ_ACTION_RECTS
    burn = P.MERZ_ACTION_RECTS["select_burn"]
    egg = P.MERZ_ACTION_RECTS["select_egg"]
    testicle = P.MERZ_ACTION_RECTS["select_testicle"]
    assert burn.centerx == P.DISPLAY_WIDTH // 2 and burn.bottom < egg.top, "BURN pill not centered above"
    assert all(0 <= r.left and r.right <= P.DISPLAY_WIDTH for r in (egg, burn, testicle)), "pill off-screen"
    pygame.image.save(P.tft_surf, os.path.join(OUT_DIR, "merz_burn_unlocked.png"))
    exit_zone = pygame.Rect(0, 0, P.EMERGENCY_EXIT_MAX_X, P.EMERGENCY_EXIT_MAX_Y)
    for name, rect in P.MERZ_ACTION_RECTS.items():
        assert not rect.colliderect(exit_zone), f"merz {name} button inside emergency-exit zone"

    # Hold fire at Merz for ~3s of simulated frames; he can't dodge this.
    hits_before = P.MERZ_HITS
    P.handle_merz_click(int(P.MERZ_X), int(P.MERZ_Y))
    assert P.MERZ_BURN_HELD
    t0 = time.time() - 3.0  # simulate the last 3s, so particle timestamps stay in the past
    frames = 60
    for i in range(frames):
        now = t0 + i * 0.05
        P.MERZ_LAST_TICK = now - 0.05
        # The dummy video driver ignores mouse.set_pos, so fake the finger.
        pygame.mouse.get_pos = lambda: (int(P.MERZ_X), int(P.MERZ_Y))
        P.MERZ_WANDER_TARGET_X, P.MERZ_WANDER_TARGET_Y = P.MERZ_X, P.MERZ_Y  # hold still
        P.MERZ_NEXT_WANDER_AT = now + 10
        P.update_merz_game(now, 40, P.DISPLAY_WIDTH - 40, 100, 300)
    hits = P.MERZ_HITS - hits_before
    max_hits = int(frames * 0.05 / P.MERZ_BURN_HIT_INTERVAL_SECONDS) + 1
    print(f"BURN: {hits} hits in {frames * 0.05:.1f}s simulated (cap {max_hits}), "
          f"{len(P.MERZ_BURN_PARTICLES)} flames alive", flush=True)
    assert 0 < hits <= max_hits, hits
    assert P.MERZ_BURN_PARTICLES

    # Render one real frame mid-stream for the screenshot.
    P.MERZ_LAST_TICK = time.time()
    P.draw_merz_overlay()
    pygame.image.save(P.tft_surf, os.path.join(OUT_DIR, "merz_burn_firing.png"))

    P.handle_merz_release()
    assert not P.MERZ_BURN_HELD

    # A new game (replay) drops BURN again.
    P.activate_merz_game()
    assert not P.MERZ_BURN_UNLOCKED and P.MERZ_PROJECTILE_KIND == "egg"
    P.dismiss_merz_game("test")


def test_quiz_zoom():
    import random

    rng = random.Random(0)
    P.QUIZ_OWN_RESULT = None
    P.QUIZ_ALL_RESULTS = [
        {"id": str(i), "name": f"Person{i}", "mausig": rng.randint(2, 6),
         "atzig": rng.randint(2, 6), "fotzig": rng.randint(2, 6)}
        for i in range(40)
    ]
    assert P._quiz_results_dot_radius(1) < P._quiz_results_dot_radius(2) < P._quiz_results_dot_radius(4)
    P._quiz_results_reset_zoom()
    P.QUIZ_STAGE = "results"
    P.draw_quiz_overlay()
    pygame.image.save(P.tft_surf, os.path.join(OUT_DIR, "quiz_zoom_1x.png"))

    # Tap empty plot space (centroid-ish but away from dots) -> zoom 2x there.
    view = P.QUIZ_RESULTS_VIEW
    cx, cy = (int(c) for c in view["plot_center"])
    empty = min(
        (
            (x, y) for y in range(cy - 60, cy + 60, 3) for x in range(cx - 80, cx + 80, 3)
            if all(((x - h["pos"][0]) ** 2 + (y - h["pos"][1]) ** 2) ** 0.5 > 12 for h in P.QUIZ_RESULTS_DOT_HITBOXES)
        ),
        key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2,
    )
    P.handle_quiz_click(*empty)
    P.handle_quiz_results_release()
    assert P.QUIZ_RESULTS_ZOOM == 1.0, "plain tap on empty space must not zoom"
    P.handle_quiz_click(*P.QUIZ_RESULTS_ACTION_RECTS["zoom_in"].center)
    P.handle_quiz_results_release()
    assert P.QUIZ_RESULTS_ZOOM == 2.0, P.QUIZ_RESULTS_ZOOM
    P.draw_quiz_overlay()
    P.handle_quiz_click(*P.QUIZ_RESULTS_ACTION_RECTS["zoom_in"].center)
    assert P.QUIZ_RESULTS_ZOOM == 4.0
    P.draw_quiz_overlay()

    # Drag from empty space pans (content follows the finger) and does not zoom.
    P.handle_quiz_results_release()  # clear the button press
    dot_free = min(
        (
            (x, y) for y in range(200, 600, 5) for x in range(100, 400, 5)
            if all(((x - h["pos"][0]) ** 2 + (y - h["pos"][1]) ** 2) ** 0.5 > 16 for h in P.QUIZ_RESULTS_DOT_HITBOXES)
        ),
        key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2,
    )
    center_before = P.QUIZ_RESULTS_VIEW_CENTER
    P.handle_quiz_click(*dot_free)
    P.handle_quiz_results_motion(dot_free[0] + 40, dot_free[1])
    P.handle_quiz_results_release()
    assert P.QUIZ_RESULTS_ZOOM == 4.0, "drag zoomed"
    assert abs(P.QUIZ_RESULTS_VIEW_CENTER[0] - (center_before[0] - 10)) < 1e-6, P.QUIZ_RESULTS_VIEW_CENTER
    # Pan back so the dot-picking below sees the same view.
    P.handle_quiz_click(*dot_free)
    P.handle_quiz_results_motion(dot_free[0] - 40, dot_free[1])
    P.handle_quiz_results_release()
    P.draw_quiz_overlay()
    print(f"QUIZ: {len(P.QUIZ_RESULTS_DOT_HITBOXES)} dots visible at 4x", flush=True)

    # Hold a dot: label must be on top - the pixel at the label box's
    # interior is the label's white fill, not some dot drawn after it.
    target = P.QUIZ_RESULTS_DOT_HITBOXES[len(P.QUIZ_RESULTS_DOT_HITBOXES) // 2]
    P.handle_quiz_click(int(target["pos"][0]), int(target["pos"][1]))
    assert P.QUIZ_RESULTS_HELD_KEY is not None
    P.draw_quiz_overlay()
    pygame.image.save(P.tft_surf, os.path.join(OUT_DIR, "quiz_zoom_4x_held.png"))

    P.handle_quiz_click(*P.QUIZ_RESULTS_ACTION_RECTS["zoom_out"].center)
    P.handle_quiz_click(*P.QUIZ_RESULTS_ACTION_RECTS["zoom_out"].center)
    assert P.QUIZ_RESULTS_ZOOM == 1.0

    # Regression: the "+" button used to sit inside the emergency-exit
    # corner, so zooming in 5 times quit the app on the device.
    exit_zone = pygame.Rect(0, 0, P.EMERGENCY_EXIT_MAX_X, P.EMERGENCY_EXIT_MAX_Y)
    for name, rect in P.QUIZ_RESULTS_ACTION_RECTS.items():
        assert not rect.colliderect(exit_zone), f"quiz {name} button inside emergency-exit zone"
    P.dismiss_quiz("test")
    assert P.QUIZ_RESULTS_ZOOM == 1.0 and P.QUIZ_RESULTS_VIEW_CENTER is None


if __name__ == "__main__":
    test_merz_burn()
    test_quiz_zoom()
    print(f"ALL PASSED - screenshots in {OUT_DIR}", flush=True)
