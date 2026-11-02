# -*- coding: utf-8 -*-
"""The camera (spec §19): close at the start, follows the stack up, zooms
out only moderately, makes room for wide stacks, drifts along when the held
item nears an edge, never jumps."""

from . import config as C


class Camera:
    def __init__(self):
        self.zoom = C.START_ZOOM
        self.x = C.VIEW_LEFT + C.W / 2 / self.zoom  # world x at the screen centre
        self.y = 0.0  # world y drawn at GROUND_SCREEN_Y
        self.nudge_x = 0.0  # held-item edge follow, decays after release
        self.nudge_y = 0.0

    # ------------------------------------------------------------ transforms
    def to_screen(self, wx, wy):
        return C.W / 2 + (wx - self.x) * self.zoom, C.GROUND_SCREEN_Y - (wy - self.y) * self.zoom

    def to_world(self, sx, sy):
        return self.x + (sx - C.W / 2) / self.zoom, self.y + (C.GROUND_SCREEN_Y - sy) / self.zoom

    @property
    def rise(self):
        """Screen px the ground has moved down: drives the parallax."""
        return self.y * self.zoom

    # ------------------------------------------------------------ targets
    @staticmethod
    def target_zoom(top, extent):
        height = max(0.0, top - C.DECK_TOP - C.ZOOM_FREE_HEIGHT)
        z = C.START_ZOOM / (1.0 + height / C.ZOOM_HALF_HEIGHT)
        lo, hi = extent
        z = min(z, (C.W - 2 * C.SIDE_MARGIN) / max(1.0, hi - lo))
        return max(C.MIN_ZOOM, min(C.START_ZOOM, z))

    def targets(self, top, extent, zoom):
        lo, hi = extent
        view_w = C.W / zoom
        need_lo, need_hi = lo - C.SIDE_MARGIN / zoom, hi + C.SIDE_MARGIN / zoom
        left = min(max(C.VIEW_LEFT, need_hi - view_w), need_lo)
        tx = left + view_w / 2
        ty = max(0.0, top - (C.GROUND_SCREEN_Y - C.TOP_SCREEN_Y) / zoom)
        return tx, ty

    def update(self, dt, top, extent, held_screen=None):
        """top/extent of the landed stack; held_screen = screen bbox
        (left, top, right, bottom) of the held item or None."""
        tz = self.target_zoom(top, extent)
        self.zoom += (tz - self.zoom) * min(1.0, dt * C.ZOOM_RATE)
        tx, ty = self.targets(top, extent, self.zoom)
        if held_screen is not None:
            left, top_y, right, _ = held_screen
            if left < C.EDGE_FOLLOW:
                self.nudge_x -= C.EDGE_SPEED * dt * (1 - max(0.0, left) / C.EDGE_FOLLOW)
            elif right > C.W - C.EDGE_FOLLOW:
                self.nudge_x += C.EDGE_SPEED * dt * (1 - max(0.0, C.W - right) / C.EDGE_FOLLOW)
            if top_y < C.BAR_H + C.EDGE_FOLLOW * 0.6:
                self.nudge_y += C.EDGE_SPEED * dt * 0.6
            self.nudge_x = max(-260.0, min(260.0, self.nudge_x))
            self.nudge_y = max(0.0, min(500.0, self.nudge_y))
        else:
            decay = min(1.0, dt * 0.8)
            self.nudge_x -= self.nudge_x * decay
            self.nudge_y -= self.nudge_y * decay
        k = min(1.0, dt * C.CAM_RATE)
        self.x += (tx + self.nudge_x - self.x) * k
        self.y += (ty + self.nudge_y - self.y) * k

    def snap(self, top, extent):
        self.zoom = self.target_zoom(top, extent)
        self.x, self.y = self.targets(top, extent, self.zoom)
        self.nudge_x = self.nudge_y = 0.0
