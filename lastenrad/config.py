# -*- coding: utf-8 -*-
"""Every tuning number of LASTENRAD-SIMULATOR in one place (spec §11, §37).

World units: 1 unit = 1 screen px at zoom 1.0, y points UP, the ground is
y = 0 and the bike's kickstand foot (its tilt pivot) sits at (0, 0).
Masses are compressed "feel" units (spec §10), not kg.
"""

import math

DEBUG = False  # PiDashboard sets this from config GAMES.LASTENRAD.DEBUG: collision shapes, COM, angle, torque, FPS

# ------------------------------------------------------------ screen (game surface 480 x 764, below the KiezOS title bar)
W, H = 480, 764
BAR_H = 66  # the compact item bar on top (spec §18: one narrow strip)
GROUND_SCREEN_Y = 702  # screen y of the ground line at the start
CORNER = (100, 144)  # PiDashboard's emergency-exit box in game coords: nothing tappable there on menus

# ------------------------------------------------------------ physics (pymunk)
GRAVITY = 1800.0  # units/s^2; a bit lighter than "real" at this scale so drops read clearly
PHYSICS_HZ = 120  # fixed substeps; a frame at 30 FPS runs 4
MAX_SUBSTEPS = 8  # after a stall, drop time instead of spiralling
ITERATIONS = 18
SPACE_DAMPING = 0.82  # velocity kept after 1 s (spec §9 "gute Dämpfung")
SLEEP_TIME = 0.3  # s at rest before a body sleeps
IDLE_SPEED = 8.0  # units/s below which a body counts as resting (sleeping = the "Haftung" of resting contacts)
COLLISION_SLOP = 0.3
DEFAULT_FRICTION = 1.0  # pymunk multiplies both sides: 1.0 x 1.0 = grippy, arcade-stable stacks (spec §9)
HAFT_SPEED = 6.0  # an item slower than this (units/s, and spinning < HAFT_SPIN rad/s) counts as resting ...
HAFT_SPIN = 0.25
HAFT_BOOST = 1.5  # ... and grips harder: static > sliding friction (spec §9 "minimale zusätzliche Haftung")
ROLLING_ANGULAR_DAMPING = 0.6  # per item "angular_damping": fraction of spin kept per second
PROBE_TOLERANCE = 0.6  # units a held item may touch others (no visible clipping)

# ------------------------------------------------------------ the bike (spec §4)
DECK_LEN = 290  # ~60 % of the screen width at START_ZOOM
DECK_TOP = 72  # deck surface above the ground
DECK_THICK = 10
DECK_FRICTION = 1.1  # rubber mat
BIKE_MASS = 30.0
BIKE_MOMENT = 3.2e5
REAR_WHEEL = (-200.0, 30.0, 30.0)  # x, y, r (drawn; collides only once the bike is lost)
FRONT_WHEEL = (112.0, 25.0, 23.0)
WHEEL_LIFT = 4  # the kickstand lifts both wheels a little, grass hides the rest when tilting
LEF_X = -262  # Lef stands left of the saddle (spec §5)

# ------------------------------------------------------------ balance (spec §11)
# The kickstand is a nonlinear torsion spring with CAPACITY = BASE_HOLD_TORQUE
# + load_weight * STAND_LEVER (the base part makes the first items tolerant;
# with a heavy load, a centre of mass about STAND_LEVER off the stand is the
# limit). Restoring torque over the tilt angle, i.e. the spec's stages:
#   0 .. CATCH_ANGLE          stiff, up to CATCH_SHARE of capacity: small offsets are caught, minimal tilt
#   CATCH_ANGLE .. HOLD_ANGLE soft, up to the full capacity: visibly stronger tilt
#   HOLD_ANGLE .. NO_RETURN   the stand gives way (torque fades to 0): slow, then faster tipping
#   > NO_RETURN_ANGLE         crash
# Tilting shifts a tall stack's centre of mass sideways by itself, so in the
# soft range a tall tower runs away while a low one just leans (spec: "bei
# einem hohen Turm ... kritisch"); HEIGHT_ASSIST tempers that.
STAND_LEVER = 40.0
BASE_HOLD_TORQUE = 2.6e6
CATCH_SHARE = 0.6
CATCH_ANGLE = math.radians(3.0)
HOLD_ANGLE = math.radians(8.0)
NO_RETURN_ANGLE = math.radians(16.0)
# Virtual stabiliser (spec §11 "virtueller stabilisierender Drehmomentbereich"):
# cancels this share of the leaning tower's extra gravity torque (weight x
# COM height x sin tilt). 0 = pure physics (towers > ~25 items unplayable),
# 1 = height never matters. The rest keeps tall towers touchy.
HEIGHT_ASSIST = 0.5
BALANCE_ZETA = 0.5  # damping ratio of the bike's sway in the stiff range ...
WOBBLE_ZETA = 0.12  # ... and towards HOLD_ANGLE (spec: "stärkeres Wackeln")

# ------------------------------------------------------------ touch & rotation (spec §6-8)
GRAB_LIFT = 26  # the held item floats this far above the finger, so the finger never hides it
ROTATE_SPEED = math.radians(100)  # fallback buttons: rad/s while held
PROBE_STEPS = 9  # binary-search steps when a drag would push the held item into others
ITEM_CACHE = 700  # rotated/zoomed sprites kept
ANGLE_STEP = math.radians(2.0)  # sprite rotation quantisation
ZOOM_STEP = 0.02

# ------------------------------------------------------------ camera (spec §19)
START_ZOOM = 1.0
MIN_ZOOM = 0.56
ZOOM_FREE_HEIGHT = 380  # stack height (above the deck) before the camera starts zooming out at all
ZOOM_HALF_HEIGHT = 1500  # further height at which zoom is START_ZOOM / 2 (clamped at MIN_ZOOM)
TOP_SCREEN_Y = 300  # the stack's top is kept at or below this screen y, room above to hold the next item
VIEW_LEFT = LEF_X - 44  # preferred left edge of the view: Lef visible as long as the stack allows
SIDE_MARGIN = 26
CAM_RATE = 2.4  # 1/s, exponential follow
ZOOM_RATE = 1.2
EDGE_FOLLOW = 70  # px from the screen edge where the held item pulls the camera along
EDGE_SPEED = 260  # units/s

# ------------------------------------------------------------ parallax (spec §20), screen px of camera rise R
TREE_FACTOR = 0.82
HOUSE_FACTOR = 0.40
SKYLINE_FACTOR = 0.12
TOWER_FACTOR = 0.07
CLOUD_FACTOR = 0.04
TREE_TOP_Y = 300  # canopy top at the start
HOUSE_TOP_Y = 362  # roofs at the start, hidden behind the canopy until R ~ 160 (about 15 items)
SKYLINE_TOP_Y = 470
TOWER_TIP_Y = 560  # Fernsehturm tip, rises out from behind the roofs later
BIRDS = [  # (kind, from R, to R, seconds between flocks)
    ("taube", 650, 2600, 7.0),
    ("rabe", 1500, 4200, 9.0),
    ("gans", 3000, 99999, 11.0),
]

# ------------------------------------------------------------ difficulty director (spec §12, §14, §24)
SAFE_ITEMS = 6  # the first items are big and easy
WTF_EARLIEST = 12  # ~30-45 s into a run
WTF_CHANCE = 0.09  # per item once allowed
PERSON_EARLIEST = 35
PERSON_CHANCE = 0.03
DIFFICULTY_RAMP = 11.0  # items per +1 target difficulty
MAX_ROUND_IN_A_ROW = 1

# ------------------------------------------------------------ rules (spec §22, §25, §29)
BLAME_SECONDS = 3.0  # a fall this soon after a release doesn't count that item (Endlos) / knocks its placer out (Party)
CRASH_SECONDS = 2.4  # crash spectacle before the result (spec: physics first)
CRASH_EXTRA_PER_ITEM = 0.03
CRASH_MAX_SECONDS = 4.0
CRASH_BOOM_DELAY = 0.35
CRASH_BOOM_FROM = 6  # stacks at least this big get the absurd Broforce burst
CRASH_BOOM_IMPULSE = 340.0  # per unit mass, grows with the stack
STORY_SETTLE_SECONDS = 3.0  # after the last item: 3 s nothing may fall (dramatised countdown)
STORY_RIDE_SECONDS = 3.2  # Lef rides off into the sunset
PARTY_OUT_SECONDS = 2.2
PARTY_MIN, PARTY_MAX = 2, 6
RESUME_SECONDS = 1800  # a closed run waits this long (kiosk compromise for spec §32)
IDLE_TIMEOUT_SECONDS = 600

THUMB_W = 160
