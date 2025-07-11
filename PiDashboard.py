#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# MIT License
#
# Copyright (c) 2016 LoveBootCaptain (Stephan Ansorge)
# Additional changes (c) 2025 MassEast
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import datetime
import json
import locale
import logging
import math
import os
import random
import sys
import threading
import pandas as pd
import time

import pygame
import pygame.gfxdraw
import requests
from PIL import Image, ImageDraw

from utils import get_stop_data

# Allow the system to manage blanking
os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "1"

PATH = sys.path[0] + "/"
ICON_PATH = PATH + "/icons/"
FONT_PATH = PATH + "/fonts/"
LOG_PATH = PATH + "/logs/"

# Load config file
config_data = open(PATH + "config.json").read()
config = json.loads(config_data)

# Create logger
logger = logging.getLogger(__package__)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger.setLevel(logging.INFO)

# Create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# Create file handler and set level to info
# for file path, get starting time in nice str format
datetimenow = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
fh = logging.FileHandler(os.path.join(LOG_PATH, f"{datetimenow}.log"))
fh.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# add formatter to ch
ch.setFormatter(formatter)
fh.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(ch)
if config["LOG_TO_FILES"]:
    logger.addHandler(fh)

theme_config = config["THEME"]

theme_settings = open(PATH + theme_config).read()
theme = json.loads(theme_settings)

SERVER = config["WEATHERBIT_URL"]
HEADERS = {}
WEATHERBIT_COUNTRY = config["WEATHERBIT_COUNTRY"]
WEATHERBIT_LANG = config["WEATHERBIT_LANGUAGE"]
WEATHERBIT_POSTALCODE = config["WEATHERBIT_POSTALCODE"]
WEATHERBIT_HOURS = config["WEATHERBIT_HOURS"]
WEATHERBIT_DAYS = config["WEATHERBIT_DAYS"]
METRIC = config["LOCALE"]["METRIC"]

locale.setlocale(locale.LC_ALL, (config["LOCALE"]["ISO"], "UTF-8"))

BVG_DEPARTURE_ID = config["BVG"]["DEPARTURE_ID"]
BVG_DIRECTION_ID_LEFT = config["BVG"]["DIRECTION_ID_LEFT"]
BVG_DIRECTION_ID_RIGHT = config["BVG"]["DIRECTION_ID_RIGHT"]
BVG_LINE = config["BVG"]["LINE"]
BVG_LOOKAHEAD_MIN = config["BVG"]["LOOKAHEAD_MIN"]
BVG_LOOKBACK_MIN = config["BVG"]["LOOKBACK_MIN"]


class SimpleScheduler:
    """Simple, clean scheduler for weather and BVG updates"""

    def __init__(self):
        self.weather_timer = None
        self.bvg_timer = None
        self.running = True

    def start_weather_updates(self):
        """Start weather update cycle - combines API call and data processing"""
        if self.weather_timer:
            self.weather_timer.cancel()

        def weather_cycle():
            if not self.running or DISPLAY_BLANK:
                # Reschedule for later if display is blank
                if self.running:
                    self.weather_timer = threading.Timer(60, weather_cycle)  # Check again in 1 min
                    self.weather_timer.start()
                return

            try:
                # Do complete weather update in one cycle
                WeatherUpdate.update_and_process()
                logger.info("Weather cycle completed successfully")
            except Exception as e:
                logger.error(f"Weather cycle failed: {e}")

            # Schedule next cycle
            if self.running:
                self.weather_timer = threading.Timer(
                    config["TIMER"]["WEATHER_UPDATE"], weather_cycle
                )
                self.weather_timer.start()

        # Start the cycle
        weather_cycle()

    def start_bvg_updates(self):
        """Start BVG update cycle"""
        if self.bvg_timer:
            self.bvg_timer.cancel()

        def bvg_cycle():
            if not self.running or DISPLAY_BLANK:
                # Reschedule for later if display is blank
                if self.running:
                    self.bvg_timer = threading.Timer(60, bvg_cycle)  # Check again in 1 min
                    self.bvg_timer.start()
                return

            try:
                BVGUpdate.update_bvg_stop_information()
                logger.info("BVG cycle completed successfully")
            except Exception as e:
                logger.error(f"BVG cycle failed: {e}")

            # Schedule next cycle
            if self.running:
                self.bvg_timer = threading.Timer(config["TIMER"]["BVG_UPDATE"], bvg_cycle)
                self.bvg_timer.start()

        # Start the cycle
        bvg_cycle()

    def stop_all(self):
        """Clean shutdown of all timers"""
        logger.info("Stopping scheduler - cancelling all timers")
        self.running = False

        if self.weather_timer:
            self.weather_timer.cancel()
            logger.info("Weather timer cancelled")
        if self.bvg_timer:
            self.bvg_timer.cancel()
            logger.info("BVG timer cancelled")


# Global scheduler instance
scheduler = SimpleScheduler()

UPDATED_BVG_TIME = None
BVG_STOP_INFORMATION = pd.DataFrame(columns=["type", "line", "departure", "delay", "direction"])

LAST_TOUCH_TIME = time.time()
DISPLAY_BLANK_AFTER = config["TIMER"]["DISPLAY_BLANK"]
DISPLAY_BLANK = False

try:
    # if you do local development you can add a mock server (e.g. from postman.io our your homebrew solution)
    # simple add this variables to your config.json to save api-requests
    # or to create your own custom test data for your own dashboard views)
    if config["ENV"] == "DEV":
        SERVER = config["MOCKSERVER_URL"]
        WEATHERBIT_IO_KEY = config["WEATHERBIT_DEV_KEY"]
        HEADERS = {"X-Api-Key": f'{config["MOCKSERVER_API_KEY"]}'}

    elif config["ENV"] == "STAGE":
        WEATHERBIT_IO_KEY = config["WEATHERBIT_DEV_KEY"]
        # Note: In this mode, we are not using any weather updates from API,
        #  but instead simply showing the latest data from
        #  logs/latest_weather.json.

    elif config["ENV"] == "Pi":
        LOG_PATH = "/mnt/ramdisk/"
        WEATHERBIT_IO_KEY = config["WEATHERBIT_IO_KEY"]

    logger.info(f"STARTING IN {config['ENV']} MODE")


except Exception as e:
    logger.warning(e)
    quit()


pygame.display.init()
pygame.mixer.quit()
pygame.font.init()
pygame.mouse.set_visible(config["DISPLAY"]["MOUSE"])
pygame.display.set_caption("PiDashboard")


def quit_all():
    pygame.display.quit()
    pygame.quit()

    logger.info("Shutting down - stopping scheduler")

    # Stop the new scheduler
    scheduler.stop_all()

    sys.exit()


# display settings from theme config
DISPLAY_WIDTH = int(config["DISPLAY"]["WIDTH"])
DISPLAY_HEIGHT = int(config["DISPLAY"]["HEIGHT"])

# the drawing area to place all text and img on
SURFACE_WIDTH = 240
SURFACE_HEIGHT = 320

SCALE = float(DISPLAY_WIDTH / SURFACE_WIDTH)
ZOOM = 1

FPS = config["DISPLAY"]["FPS"]
SHOW_FPS = config["DISPLAY"]["SHOW_FPS"]
AA = config["DISPLAY"]["AA"]
ANIMATION = config["DISPLAY"]["ANIMATION"]


# correction for 1:1 displays like hyperpixel4 square
if DISPLAY_WIDTH / DISPLAY_HEIGHT == 1:
    logger.info(f"square display configuration detected")
    square_width = int(DISPLAY_WIDTH / float(4 / 3))
    SCALE = float(square_width / SURFACE_WIDTH)

    logger.info(f"scale and display correction caused by square display")
    logger.info(f"DISPLAY_WIDTH: {square_width} new SCALE: {SCALE}")

# check if a landscape display is configured
if DISPLAY_WIDTH > DISPLAY_HEIGHT:
    logger.info(f"landscape display configuration detected")
    SCALE = float(DISPLAY_HEIGHT / SURFACE_HEIGHT)

    logger.info(f"scale and display correction caused by landscape display")
    logger.info(f"DISPLAY_HEIGHT: {DISPLAY_HEIGHT} new SCALE: {SCALE}")

# zoom the application surface rendering to display size scale
if SCALE != 1:
    ZOOM = SCALE

    if DISPLAY_HEIGHT < SURFACE_HEIGHT:
        logger.info("screen smaller as surface area - zooming smaller")
        SURFACE_HEIGHT = DISPLAY_HEIGHT
        SURFACE_WIDTH = int(SURFACE_HEIGHT / (4 / 3))
        logger.info(f"surface correction caused by small display")
        if DISPLAY_WIDTH == DISPLAY_HEIGHT:
            logger.info("small and square")
            ZOOM = round(ZOOM, 2)
        else:
            ZOOM = round(ZOOM, 1)
        logger.info(f"zoom correction caused by small display")
    else:
        logger.info("screen bigger as surface area - zooming bigger")
        SURFACE_WIDTH = int(240 * ZOOM)
        SURFACE_HEIGHT = int(320 * ZOOM)
        logger.info(f"surface correction caused by bigger display")

    logger.info(f"SURFACE_WIDTH: {SURFACE_WIDTH} SURFACE_HEIGHT: {SURFACE_HEIGHT} ZOOM: {ZOOM}")

FIT_SCREEN = (
    int((DISPLAY_WIDTH - SURFACE_WIDTH) / 2),
    int((DISPLAY_HEIGHT - SURFACE_HEIGHT) / 2),
)

# the real display surface
tft_surf = pygame.display.set_mode(
    (DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.NOFRAME if config["ENV"] == "Pi" else 0
)

# the drawing area - everything will be drawn here before scaling and rendering on the display tft_surf
display_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
# dynamic surface for status bar updates and dynamic values like fps
dynamic_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
# exclusive surface for the time
time_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
# exclusive surface for the mouse/touch events
mouse_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
# surface for the weather data - will only be created once if the data is updated from the api
weather_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
# surface for the BVG departure data - will only be updated when the BVG API is called and delivers new data
bvg_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))

clock = pygame.time.Clock()

logger.info(
    f"display with {DISPLAY_WIDTH}px width and {DISPLAY_HEIGHT}px height is "
    f"set to {FPS} FPS with AA {AA}"
)

BACKGROUND = tuple(theme["COLOR"]["BACKGROUND"])
MAIN_FONT = tuple(theme["COLOR"]["MAIN_FONT"])
BLACK = tuple(theme["COLOR"]["BLACK"])
DARK_GRAY = tuple(theme["COLOR"]["DARK_GRAY"])
WHITE = tuple(theme["COLOR"]["WHITE"])
RED = tuple(theme["COLOR"]["RED"])
GREEN = tuple(theme["COLOR"]["GREEN"])
BLUE = tuple(theme["COLOR"]["BLUE"])
LIGHT_BLUE = tuple((BLUE[0], 210, BLUE[2]))
DARK_BLUE = tuple((BLUE[0], 100, 255))
YELLOW = tuple(theme["COLOR"]["YELLOW"])
ORANGE = tuple(theme["COLOR"]["ORANGE"])
VIOLET = tuple(theme["COLOR"]["VIOLET"])
COLOR_LIST = [BLUE, LIGHT_BLUE, DARK_BLUE]

FONT_MEDIUM = theme["FONT"]["MEDIUM"]
FONT_BOLD = theme["FONT"]["BOLD"]
DATE_SIZE = int(theme["FONT"]["DATE_SIZE"] * ZOOM)
CLOCK_SIZE = int(theme["FONT"]["CLOCK_SIZE"] * ZOOM)
SUPER_TINY_SIZE = int(theme["FONT"]["SUPER_TINY_SIZE"] * ZOOM)
TINY_SIZE = int(theme["FONT"]["TINY_SIZE"] * ZOOM)
SMALL_SIZE = int(theme["FONT"]["SMALL_SIZE"] * ZOOM)
BIG_SIZE = int(theme["FONT"]["BIG_SIZE"] * ZOOM)

FONT_SUPER_TINY = pygame.font.Font(FONT_PATH + FONT_MEDIUM, SUPER_TINY_SIZE)
FONT_TINY = pygame.font.Font(FONT_PATH + FONT_MEDIUM, TINY_SIZE)
FONT_SMALL = pygame.font.Font(FONT_PATH + FONT_MEDIUM, SMALL_SIZE)
FONT_SMALL_BOLD = pygame.font.Font(FONT_PATH + FONT_BOLD, SMALL_SIZE)
FONT_BIG = pygame.font.Font(FONT_PATH + FONT_MEDIUM, BIG_SIZE)
FONT_BIG_BOLD = pygame.font.Font(FONT_PATH + FONT_BOLD, BIG_SIZE)
DATE_FONT = pygame.font.Font(FONT_PATH + FONT_BOLD, DATE_SIZE)
CLOCK_FONT = pygame.font.Font(FONT_PATH + FONT_BOLD, CLOCK_SIZE)

WEATHERICON = "unknown"

FORECASTICON_DAY_1 = "unknown"
FORECASTICON_DAY_2 = "unknown"
FORECASTICON_DAY_3 = "unknown"

CONNECTION_ERROR = True
REFRESH_ERROR = True
PATH_ERROR = True
PRECIPTYPE = "NULL"
PRECIPCOLOR = WHITE

CONNECTION = False
READING = False
UPDATING = False

WEATHER_JSON_DATA = {}


def image_factory(image_path):
    result = {}
    for img in os.listdir(image_path):
        image_id = img.split(".")[0]
        if image_id == "":
            pass
        else:
            result[image_id] = Image.open(image_path + img)
    return result


class Particles(object):
    def __init__(self):
        self.size = int(20 * ZOOM)
        self.count = 20
        self.surf = pygame.Surface((self.size, self.size))

    def create_particle_list(self):

        particle_list = []

        for i in range(self.count):
            x = random.randrange(0, self.size)
            y = random.randrange(0, self.size)
            w = int(1 * ZOOM)
            h = random.randint(int(2 * ZOOM), int(3 * ZOOM))
            speed = random.choice([1, 2, 3])
            color = random.choice(COLOR_LIST)
            direct = random.choice([0, 0, 1])
            particle_list.append([x, y, w, h, speed, color, direct])
        return particle_list

    def move(self, surf, particle_list):
        # Process each snow flake in the list
        self.surf.fill(BACKGROUND)
        self.surf.set_colorkey(BACKGROUND)

        if not PRECIPTYPE == config["LOCALE"]["PRECIP_STR"]:

            for i in range(len(particle_list)):

                particle = particle_list[i]
                x, y, w, h, speed, color, direct = particle

                # Draw the snow flake
                if PRECIPTYPE == config["LOCALE"]["RAIN_STR"]:
                    pygame.draw.rect(self.surf, color, (x, y, w, h), 0)
                else:
                    pygame.draw.rect(self.surf, PRECIPCOLOR, (x, y, 2, 2), 0)

                # Move the snow flake down one pixel
                particle_list[i][1] += speed if PRECIPTYPE == config["LOCALE"]["RAIN_STR"] else 1
                if random.choice([True, False]):
                    if PRECIPTYPE == config["LOCALE"]["SNOW_STR"]:
                        particle_list[i][0] += 1 if direct else 0

                # If the snow flake has moved off the bottom of the screen
                if particle_list[i][1] > self.size:
                    # Reset it just above the top
                    y -= self.size
                    particle_list[i][1] = y
                    # Give it a new x position
                    x = random.randrange(0, self.size)
                    particle_list[i][0] = x

            surf.blit(self.surf, (int(155 * ZOOM), int(140 * ZOOM)))


class DrawString:
    def __init__(self, surf, string: str, font, color, y: int):
        """
        :param string: the input string
        :param font: the fonts object
        :param color: a rgb color tuple
        :param y: the y position where you want to render the text
        """
        self.string = string
        self.font = font
        self.color = color
        self.y = int(y * ZOOM)
        self.size = self.font.size(self.string)
        self.surf = surf

    def left(self, offset=0):
        """
        :param offset: define some offset pixel to move strings a little bit more left (default=0)
        """

        x = int(10 * ZOOM + (offset * ZOOM))

        self.draw_string(x)

    def right(self, offset=0):
        """
        :param offset: define some offset pixel to move strings a little bit more right (default=0)
        """

        x = int((SURFACE_WIDTH - self.size[0] - (10 * ZOOM)) - (offset * ZOOM))

        self.draw_string(x)

    def center(self, parts, part, offset=0):
        """
        :param parts: define in how many parts you want to split your display
        :param part: the part in which you want to render text (first part is 0, second is 1, etc.)
        :param offset: define some offset pixel to move strings a little bit (default=0)
        """

        x = int(
            (
                (((SURFACE_WIDTH / parts) / 2) + ((SURFACE_WIDTH / parts) * part))
                - (self.size[0] / 2)
            )
            + (offset * ZOOM)
        )

        self.draw_string(x)

    def draw_string(self, x):
        """
        takes x and y from the functions above and render the fonts
        """

        self.surf.blit(self.font.render(self.string, True, self.color), (x, self.y))


class DrawImage:
    def __init__(self, surf, image=Image, y=None, size=None, fillcolor=None, angle=None):
        """
        :param image: image from the image_factory()
        :param y: the y-position of the image you want to render
        """
        self.image = image
        if y:
            self.y = int(y * ZOOM)

        self.img_size = self.image.size
        self.size = int(size * ZOOM)
        self.angle = angle
        self.surf = surf

        if angle:
            self.image = self.image.rotate(self.angle, resample=Image.BICUBIC)

        if size:
            width, height = self.image.size
            if width >= height:
                width, height = (self.size, int(self.size / width * height))
            else:
                width, height = (int(self.size / width * height), self.size)

            new_image = self.image.resize((width, height), Image.LANCZOS if AA else Image.BILINEAR)
            self.image = new_image
            self.img_size = new_image.size

        self.fillcolor = fillcolor

        self.image = pygame.image.fromstring(self.image.tobytes(), self.image.size, self.image.mode)

    @staticmethod
    def fill(surface, fillcolor: tuple):
        """converts the color on an mono colored icon"""
        surface.set_colorkey(BACKGROUND)
        w, h = surface.get_size()
        r, g, b = fillcolor
        for x in range(w):
            for y in range(h):
                a: int = surface.get_at((x, y))[3]
                # removes some distortion from scaling/zooming
                if a > 5:
                    color = pygame.Color(r, g, b, a)
                    surface.set_at((x, y), color)

    def left(self, offset=0):
        """
        :param offset: define some offset pixel to move image a little bit more left(default=0)
        """

        x = int(10 * ZOOM + (offset * ZOOM))

        self.draw_image(x)

    def right(self, offset=0):
        """
        :param offset: define some offset pixel to move image a little bit more right (default=0)
        """

        x = int((SURFACE_WIDTH - self.img_size[0] - 10 * ZOOM) - (offset * ZOOM))

        self.draw_image(x)

    def center(self, parts, part, offset=0):
        """
        :param parts: define in how many parts you want to split your display
        :param part: the part in which you want to render text (first part is 0, second is 1, etc.)
        :param offset: define some offset pixel to move strings a little bit (default=0)
        """

        x = int(
            (
                (((SURFACE_WIDTH / parts) / 2) + ((SURFACE_WIDTH / parts) * part))
                - (self.img_size[0] / 2)
            )
            + (offset * ZOOM)
        )

        self.draw_image(x)

    def draw_middle_position_icon(self):

        position_x = int(
            (SURFACE_WIDTH - ((SURFACE_WIDTH / 3) / 2) - (self.image.get_rect()[2] / 2))
        )

        position_y = int((self.y - (self.image.get_rect()[3] / 2)))

        self.draw_image(draw_x=position_x, draw_y=position_y)

    def draw_position(self, pos: tuple):
        x, y = pos
        if y == 0:
            y += 1
        self.draw_image(draw_x=int(x * ZOOM), draw_y=int(y * ZOOM))

    def draw_absolut_position(self, pos: tuple):
        x, y = pos
        if y == 0:
            y += 1
        self.draw_image(draw_x=int(x), draw_y=int(y))

    def draw_image(self, draw_x, draw_y=None):
        """
        takes x from the functions above and the y from the class to render the image
        """

        if self.fillcolor:

            surface = self.image
            self.fill(surface, self.fillcolor)

            if draw_y:
                self.surf.blit(surface, (int(draw_x), int(draw_y)))
            else:
                self.surf.blit(surface, (int(draw_x), self.y))
        else:
            if draw_y:
                self.surf.blit(self.image, (int(draw_x), int(draw_y)))
            else:
                self.surf.blit(self.image, (int(draw_x), self.y))


class WeatherUpdate(object):

    @staticmethod
    def update_and_process():
        """Complete weather update cycle - API call + data processing + surface creation"""
        global CONNECTION_ERROR, REFRESH_ERROR, CONNECTION, READING, UPDATING

        # Skip if display is blank or in STAGE mode
        if DISPLAY_BLANK or config["ENV"] == "STAGE":
            # In STAGE mode, just read the existing JSON file
            if config["ENV"] == "STAGE":
                WeatherUpdate.read_json_and_process()
            return

        CONNECTION = pygame.time.get_ticks() + 1500  # 1.5 seconds

        try:
            # Step 1: Fetch new data from API
            current_endpoint = f"{SERVER}/current"
            daily_endpoint = f"{SERVER}/forecast/daily"
            stats_endpoint = f"{SERVER}/subscription/usage"
            units = "M" if METRIC else "I"

            logger.info(f"connecting to server: {SERVER}")

            options = str(
                f"&postal_code={WEATHERBIT_POSTALCODE}"
                f"&country={WEATHERBIT_COUNTRY}"
                f"&lang={WEATHERBIT_LANG}"
                f"&units={units}"
            )

            current_request_url = str(f"{current_endpoint}?key={WEATHERBIT_IO_KEY}{options}")
            daily_request_url = str(
                f"{daily_endpoint}?key={WEATHERBIT_IO_KEY}{options}&days={WEATHERBIT_DAYS}"
            )
            stats_request_url = str(f"{stats_endpoint}?key={WEATHERBIT_IO_KEY}")

            current_data = requests.get(current_request_url, headers=HEADERS, timeout=10).json()
            daily_data = requests.get(daily_request_url, headers=HEADERS, timeout=10).json()
            stats_data = requests.get(stats_request_url, headers=HEADERS, timeout=10).json()

            data = {"current": current_data, "daily": daily_data, "stats": stats_data}

            # Step 2: Save to file
            with open(LOG_PATH + "latest_weather.json", "w+") as outputfile:
                json.dump(data, outputfile, indent=2, sort_keys=True)

            logger.info("json file saved")
            CONNECTION_ERROR = False

            # Step 3: Process the data immediately
            WeatherUpdate.process_data(data)

        except (
            requests.HTTPError,
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.JSONDecodeError,
        ) as update_ex:
            CONNECTION_ERROR = True
            logger.warning(
                f"Failed updating latest_weather.json. weatherbit connection ERROR: {update_ex}"
            )

            # Fallback: try to read existing file
            try:
                WeatherUpdate.read_json_and_process()
            except Exception as fallback_ex:
                logger.error(f"Fallback read also failed: {fallback_ex}")

    @staticmethod
    def read_json_and_process():
        """Read JSON file and process data"""
        global WEATHER_JSON_DATA, REFRESH_ERROR, READING

        READING = pygame.time.get_ticks() + 1500  # 1.5 seconds

        try:
            data = open(LOG_PATH + "latest_weather.json").read()
            new_json_data = json.loads(data)
            logger.info("json file read by module")

            REFRESH_ERROR = False
            WeatherUpdate.process_data(new_json_data)

        except IOError as read_ex:
            REFRESH_ERROR = True
            logger.warning(f"ERROR - json file read by module: {read_ex}")

    @staticmethod
    def process_data(data):
        """Process weather data and create surface"""
        global WEATHER_JSON_DATA

        WEATHER_JSON_DATA = data
        WeatherUpdate.icon_path()

    @staticmethod
    def icon_path():

        global WEATHERICON, FORECASTICON_DAY_1, FORECASTICON_DAY_2, FORECASTICON_DAY_3, PRECIPTYPE, PRECIPCOLOR, UPDATING

        icon_extension = ".png"

        updated_list = []

        icon = WEATHER_JSON_DATA["current"]["data"][0]["weather"]["icon"]

        forecast_icon_1 = WEATHER_JSON_DATA["daily"]["data"][1]["weather"]["icon"]
        forecast_icon_2 = WEATHER_JSON_DATA["daily"]["data"][2]["weather"]["icon"]
        forecast_icon_3 = WEATHER_JSON_DATA["daily"]["data"][3]["weather"]["icon"]

        forecast = (
            str(icon),
            str(forecast_icon_1),
            str(forecast_icon_2),
            str(forecast_icon_3),
        )

        logger.debug(forecast)

        logger.debug(f"validating path: {forecast}")

        for icon in forecast:

            if os.path.isfile(ICON_PATH + icon + icon_extension):

                logger.debug(f"TRUE : {icon}")

                updated_list.append(icon)

            else:

                logger.warning(f"FALSE : {icon}")

                updated_list.append("unknown")

        WEATHERICON = updated_list[0]
        FORECASTICON_DAY_1 = updated_list[1]
        FORECASTICON_DAY_2 = updated_list[2]
        FORECASTICON_DAY_3 = updated_list[3]

        global PATH_ERROR

        if any("unknown" in s for s in updated_list):

            PATH_ERROR = True

        else:

            PATH_ERROR = False

        logger.info(f"update path for icons: {updated_list}")

        WeatherUpdate.get_precip_type()

    @staticmethod
    def get_precip_type():

        global WEATHER_JSON_DATA, PRECIPCOLOR, PRECIPTYPE

        pop = int(WEATHER_JSON_DATA["daily"]["data"][0]["pop"])
        rain = float(WEATHER_JSON_DATA["daily"]["data"][0]["precip"])
        snow = float(WEATHER_JSON_DATA["daily"]["data"][0]["snow"])

        if pop == 0:

            PRECIPTYPE = config["LOCALE"]["PRECIP_STR"]
            PRECIPCOLOR = GREEN

        else:

            if pop > 0 and rain > snow:

                PRECIPTYPE = config["LOCALE"]["RAIN_STR"]
                PRECIPCOLOR = BLUE

            elif pop > 0 and snow > rain:

                PRECIPTYPE = config["LOCALE"]["SNOW_STR"]
                PRECIPCOLOR = WHITE

        logger.info(f"update PRECIPPOP to: {pop} %")
        logger.info(f"update PRECIPTYPE to: {PRECIPTYPE}")
        logger.info(f"update PRECIPCOLOR to: {PRECIPCOLOR}")

        WeatherUpdate.create_surface()

    @staticmethod
    def create_surface():

        current_forecast = WEATHER_JSON_DATA["current"]["data"][0]
        daily_forecast = WEATHER_JSON_DATA["daily"]["data"]
        stats_data = WEATHER_JSON_DATA["stats"]

        summary_string = current_forecast["weather"]["description"]
        temp_out = str(int(current_forecast["temp"]))
        temp_out_unit = "°C" if METRIC else "°F"
        temp_out_string = str(temp_out + temp_out_unit)
        precip = WEATHER_JSON_DATA["daily"]["data"][0]["pop"]
        precip_string = str(f"{precip} %")

        today = daily_forecast[0]
        day_1 = daily_forecast[1]
        day_2 = daily_forecast[2]
        day_3 = daily_forecast[3]

        df_forecast = theme["DATE_FORMAT"]["FORECAST_DAY"]
        df_sun = theme["DATE_FORMAT"]["SUNRISE_SUNSET"]

        day_1_ts = time.mktime(time.strptime(day_1["datetime"], "%Y-%m-%d"))
        day_1_ts = convert_timestamp(day_1_ts, df_forecast)
        day_2_ts = time.mktime(time.strptime(day_2["datetime"], "%Y-%m-%d"))
        day_2_ts = convert_timestamp(day_2_ts, df_forecast)
        day_3_ts = time.mktime(time.strptime(day_3["datetime"], "%Y-%m-%d"))
        day_3_ts = convert_timestamp(day_3_ts, df_forecast)

        day_1_min_max_temp = f"{int(day_1['low_temp'])} | {int(day_1['high_temp'])}"
        day_2_min_max_temp = f"{int(day_2['low_temp'])} | {int(day_2['high_temp'])}"
        day_3_min_max_temp = f"{int(day_3['low_temp'])} | {int(day_3['high_temp'])}"

        sunrise = convert_timestamp(today["sunrise_ts"], df_sun)
        sunset = convert_timestamp(today["sunset_ts"], df_sun)

        wind_direction = str(current_forecast["wind_cdir"])
        wind_speed = float(current_forecast["wind_spd"])
        wind_speed = wind_speed * 3.6 if METRIC else wind_speed
        wind_speed_unit = "km/h" if METRIC else "mph"
        wind_speed_string = str(f"{round(wind_speed, 1)} {wind_speed_unit}")

        global weather_surf, UPDATING

        new_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
        new_surf.fill(BACKGROUND)

        DrawImage(
            new_surf,
            images["wifi"],
            5,
            size=15,
            fillcolor=RED if CONNECTION_ERROR else GREEN,
        ).left()
        DrawImage(
            new_surf,
            images["refresh"],
            5,
            size=15,
            fillcolor=RED if REFRESH_ERROR else GREEN,
        ).right(8)
        DrawImage(
            new_surf,
            images["path"],
            5,
            size=15,
            fillcolor=RED if PATH_ERROR else GREEN,
        ).right(-5)

        DrawImage(new_surf, images[WEATHERICON], 43, size=100).center(2, 0, offset=10)

        if not ANIMATION:
            if PRECIPTYPE == config["LOCALE"]["RAIN_STR"]:

                DrawImage(new_surf, images["preciprain"], size=20).draw_position(pos=(155, 140))

            elif PRECIPTYPE == config["LOCALE"]["SNOW_STR"]:

                DrawImage(new_surf, images["precipsnow"], size=20).draw_position(pos=(155, 140))

        DrawImage(new_surf, images[FORECASTICON_DAY_1], 157, size=50).center(3, 0)
        DrawImage(new_surf, images[FORECASTICON_DAY_2], 157, size=50).center(3, 1)
        DrawImage(new_surf, images[FORECASTICON_DAY_3], 157, size=50).center(3, 2)

        DrawImage(new_surf, images["sunrise"], 215, size=20).left()
        DrawImage(new_surf, images["sunset"], 235, size=20).left()

        draw_wind_layer(new_surf, current_forecast["wind_dir"], 225)

        draw_moon_layer(new_surf, int(215 * ZOOM), int(42 * ZOOM))

        # draw all the strings
        if config["DISPLAY"]["SHOW_API_STATS"]:
            DrawString(
                new_surf, str(stats_data["calls_remaining"]), FONT_SMALL_BOLD, BLUE, 20
            ).right(offset=-5)

        # DrawString(new_surf, summary_string, FONT_SMALL_BOLD, VIOLET, 50).center(1, 0)
        # Ignoring the summary string for now (like "Scattered clouds")

        DrawString(new_surf, temp_out_string, FONT_BIG, ORANGE, 50).right()

        DrawString(new_surf, precip_string, FONT_BIG, PRECIPCOLOR, 80).right()
        # Ignoring the "Precipitation" label for now
        # DrawString(new_surf, PRECIPTYPE, FONT_SMALL_BOLD, PRECIPCOLOR, 140).right()

        DrawString(new_surf, day_1_ts, FONT_SMALL_BOLD, ORANGE, 123).center(3, 0)
        DrawString(new_surf, day_2_ts, FONT_SMALL_BOLD, ORANGE, 123).center(3, 1)
        DrawString(new_surf, day_3_ts, FONT_SMALL_BOLD, ORANGE, 123).center(3, 2)

        DrawString(new_surf, day_1_min_max_temp, FONT_SMALL_BOLD, MAIN_FONT, 138).center(3, 0)
        DrawString(new_surf, day_2_min_max_temp, FONT_SMALL_BOLD, MAIN_FONT, 138).center(3, 1)
        DrawString(new_surf, day_3_min_max_temp, FONT_SMALL_BOLD, MAIN_FONT, 138).center(3, 2)

        DrawString(new_surf, sunrise, FONT_SMALL_BOLD, MAIN_FONT, 218).left(30)
        DrawString(new_surf, sunset, FONT_SMALL_BOLD, MAIN_FONT, 237).left(30)

        # DrawString(new_surf, wind_direction, FONT_SMALL_BOLD, MAIN_FONT, 250).center(
        #     3, 2
        # )
        DrawString(new_surf, wind_speed_string, FONT_SMALL_BOLD, MAIN_FONT, 237).center(3, 2)

        weather_surf = new_surf

        logger.info(f"summary: {summary_string}")
        logger.info(f"temp out: {temp_out_string}")
        logger.info(f"{PRECIPTYPE}: {precip_string}")
        logger.info(f"icon: {WEATHERICON}")
        logger.info(
            f"forecast: "
            f"{day_1_ts} {day_1_min_max_temp} {FORECASTICON_DAY_1}; "
            f"{day_2_ts} {day_2_min_max_temp} {FORECASTICON_DAY_2}; "
            f"{day_3_ts} {day_3_min_max_temp} {FORECASTICON_DAY_3}"
        )
        logger.info(f"sunrise: {sunrise} ; sunset {sunset}")
        logger.info(f"WindSpeed: {wind_speed_string}")

        pygame.time.delay(1500)
        UPDATING = pygame.time.get_ticks() + 1500  # 1.5 seconds

        return weather_surf


class BVGUpdate(object):

    @staticmethod
    def update_bvg_stop_information():
        """Simple BVG update without self-scheduling"""
        global UPDATED_BVG_TIME, BVG_STOP_INFORMATION

        if DISPLAY_BLANK:
            return

        try:
            UPDATED_BVG_TIME, BVG_STOP_INFORMATION = get_stop_data(
                BVG_DEPARTURE_ID,
                BVG_DIRECTION_ID_LEFT,
                BVG_DIRECTION_ID_RIGHT,
                BVG_LINE,
                BVG_LOOKAHEAD_MIN,
                BVG_LOOKBACK_MIN,
            )
            logger.info("BVG data updated successfully")
            BVGUpdate.create_surface()
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as update_ex:
            logger.warning(f"BVG Connection ERROR: {update_ex}")
        except Exception as e:
            logger.error(f"Unexpected error in BVG update: {e}")

    @staticmethod
    def create_surface():
        global bvg_surf, UPDATED_BVG_TIME, BVG_STOP_INFORMATION
        new_surf = pygame.Surface((SURFACE_WIDTH, SURFACE_HEIGHT))
        new_surf.fill(BACKGROUND)
        new_surf.set_colorkey(BACKGROUND)
        logger.info("Creating BVG surface")

        # Clear of cancelled stops
        if "cancelled" in BVG_STOP_INFORMATION.columns:
            BVG_STOP_INFORMATION = BVG_STOP_INFORMATION[~BVG_STOP_INFORMATION["cancelled"]]

        # Draw a line of bus information for direction to the left
        DrawImage(new_surf, images["arrow"], 262, size=13, fillcolor=RED, angle=90).left(-3)
        DrawImage(new_surf, images["bus"], 263, size=10).left(
            10
        )  # (TODO): make this image variable here according to lane (resp. ask for it in the config file)
        DrawString(new_surf, BVG_LINE + ":", FONT_SMALL, ORANGE, 260).left(22)
        bvg_print = ""
        # Print closest two connections for each direction
        if len(BVG_STOP_INFORMATION) and len(
            results_left := BVG_STOP_INFORMATION[BVG_STOP_INFORMATION["direction_str"] == "left"]
        ):
            departures_reported = 0
            for _, departure in results_left.iterrows():
                if departures_reported >= 2:
                    break
                delay = departure["delay"]
                if delay > 0:
                    delay = f"+{delay}'"
                elif delay < 0:
                    delay = f"{delay}'"
                else:
                    delay = ""
                and_print = ", " if departures_reported > 0 else ""
                bvg_print += f"{and_print}{departure['departure']}{delay}"
                departures_reported += 1
        else:
            bvg_print = "none :("

        DrawString(new_surf, bvg_print, FONT_SMALL, ORANGE, 260).left(60)
        DrawImage(new_surf, images["haltestelle"], 263, size=10).right()

        # Perform same stuff for the right direction
        DrawImage(new_surf, images["arrow"], 282, size=13, fillcolor=RED, angle=-90).left(-3)
        DrawImage(new_surf, images["bus"], 283, size=10).left(
            10
        )  # (TODO): make this image variable here according to lane (resp. ask for it in the config file)
        DrawString(new_surf, BVG_LINE + ":", FONT_SMALL, ORANGE, 280).left(22)
        bvg_print = ""
        # Print closest two connections for each direction
        if len(BVG_STOP_INFORMATION) and len(
            results_right := BVG_STOP_INFORMATION[BVG_STOP_INFORMATION["direction_str"] == "right"]
        ):
            departures_reported = 0
            for _, departure in results_right.iterrows():
                if departures_reported >= 2:
                    break
                delay = departure["delay"]
                if delay > 0:
                    delay = f"+{delay}'"
                elif delay < 0:
                    delay = f"{delay}'"
                else:
                    delay = ""
                and_print = ", " if departures_reported > 0 else ""
                bvg_print += f"{and_print}{departure['departure']}{delay}"
                departures_reported += 1
        else:
            bvg_print = "none :("

        DrawString(new_surf, bvg_print, FONT_SMALL, ORANGE, 280).left(60)
        DrawImage(new_surf, images["haltestelle"], 283, size=10).right()

        # Extra information
        jw_msg = "JW likes you. Have a nice day!"
        if UPDATED_BVG_TIME is not None:
            actuality_msg = "BVG API: {}".format(convert_timestamp(UPDATED_BVG_TIME, "%H:%M:%S"))
        else:
            actuality_msg = "BVG API: no data"
        DrawString(new_surf, jw_msg, FONT_TINY, WHITE, 307).left()
        DrawImage(new_surf, images["refresh"], 308, size=10, fillcolor=YELLOW).right(55)
        DrawString(new_surf, actuality_msg, FONT_SUPER_TINY, WHITE, 310).right(-3)

        bvg_surf = new_surf

        pygame.time.delay(1500)

        return bvg_surf


def get_brightness():
    current_time = time.time()
    current_time = int(convert_timestamp(current_time, "%H"))

    return 25 if current_time >= 20 or current_time <= 5 else 100


def convert_timestamp(timestamp, param_string):
    """
    :param timestamp: takes a normal integer unix timestamp
    :param param_string: use the default convert timestamp to timestring options
    :return: a converted string from timestamp
    """
    timestring = str(
        datetime.datetime.fromtimestamp(int(timestamp)).astimezone().strftime(param_string)
    )

    return timestring


def draw_time_layer():
    timestamp = time.time()

    date_day_string = convert_timestamp(timestamp, theme["DATE_FORMAT"]["DATE"])
    date_time_string = convert_timestamp(timestamp, theme["DATE_FORMAT"]["TIME"])

    logger.debug(f"Day: {date_day_string}")
    logger.debug(f"Time: {date_time_string}")

    DrawString(time_surf, date_day_string, DATE_FONT, MAIN_FONT, 0).center(1, 0)
    DrawString(time_surf, date_time_string, CLOCK_FONT, MAIN_FONT, 15).center(1, 0)


def draw_moon_layer(surf, y, size):
    # based on @miyaichi's fork -> great idea :)
    _size = 1000
    dt = datetime.datetime.fromtimestamp(WEATHER_JSON_DATA["daily"]["data"][0]["ts"])
    moon_age = (
        ((dt.year - 11) % 19) * 11 + [0, 2, 0, 2, 2, 4, 5, 6, 7, 8, 9, 10][dt.month - 1] + dt.day
    ) % 30

    image = Image.new("RGBA", (_size + 2, _size + 2))
    draw = ImageDraw.Draw(image)

    radius = int(_size / 2)

    # draw full moon
    draw.ellipse([(1, 1), (_size, _size)], fill=WHITE)

    # draw dark side of the moon
    theta = moon_age / 14.765 * math.pi
    sum_x = sum_length = 0

    for _y in range(-radius, radius, 1):
        alpha = math.acos(_y / radius)
        x = radius * math.sin(alpha)
        length = radius * math.cos(theta) * math.sin(alpha)

        if moon_age < 15:
            start = (radius - x, radius + _y)
            end = (radius + length, radius + _y)
        else:
            start = (radius - length, radius + _y)
            end = (radius + x, radius + _y)

        draw.line((start, end), fill=DARK_GRAY)

        sum_x += 2 * x
        sum_length += end[0] - start[0]

    logger.debug(
        f"moon phase age: {moon_age} percentage: {round(100 - (sum_length / sum_x) * 100, 1)}"
    )

    image = image.resize((size, size))
    image = pygame.image.fromstring(image.tobytes(), image.size, image.mode)

    x = (SURFACE_WIDTH / 2) - (size / 2)

    surf.blit(image, (x, y))


def draw_wind_layer(surf, angle, y):
    # center the wind direction icon and circle on surface
    DrawImage(surf, images["circle"], y, size=20, fillcolor=WHITE).draw_middle_position_icon()
    DrawImage(
        surf, images["arrow"], y, size=20, fillcolor=RED, angle=-angle
    ).draw_middle_position_icon()

    logger.debug(f"wind direction: {angle}")


def draw_statusbar():
    global CONNECTION, READING, UPDATING

    if CONNECTION:
        DrawImage(dynamic_surf, images["wifi"], 5, size=15, fillcolor=BLUE).left()
        if pygame.time.get_ticks() >= CONNECTION:
            CONNECTION = None

    if UPDATING:
        DrawImage(dynamic_surf, images["refresh"], 5, size=15, fillcolor=BLUE).right(8)
        if pygame.time.get_ticks() >= UPDATING:
            UPDATING = None

    if READING:
        DrawImage(dynamic_surf, images["path"], 5, size=15, fillcolor=BLUE).right(-5)
        if pygame.time.get_ticks() >= READING:
            READING = None


def draw_fps():
    DrawString(dynamic_surf, str(int(clock.get_fps())), FONT_SMALL_BOLD, RED, 20).left()


# TODO: make this useful for touch events
def draw_event(color=RED):

    pos = pygame.mouse.get_pos()

    size = 20
    radius = int(size / 2)
    new_pos = (
        int(pos[0] - FIT_SCREEN[0] - (radius * ZOOM)),
        int(pos[1] - FIT_SCREEN[1] - (radius * ZOOM)),
    )
    DrawImage(mouse_surf, images["circle"], size=size, fillcolor=color).draw_absolut_position(
        new_pos
    )


def create_scaled_surf(surf, aa=False):
    if aa:
        scaled_surf = pygame.transform.smoothscale(surf, (SURFACE_WIDTH, SURFACE_HEIGHT))
    else:
        scaled_surf = pygame.transform.scale(surf, (SURFACE_WIDTH, SURFACE_HEIGHT))

    return scaled_surf


def loop():
    # Start the new scheduler
    scheduler.start_weather_updates()
    scheduler.start_bvg_updates()

    running = True

    while running:
        global DISPLAY_BLANK
        if not DISPLAY_BLANK:

            tft_surf.fill(BACKGROUND)

            # fill the actual main surface
            display_surf.fill(BACKGROUND)

            # blit the image/weather
            display_surf.blit(weather_surf, (0, 0))
            # blit BVG layer on top
            display_surf.blit(bvg_surf, (0, 0))

            # pygame.draw.line(tft_surf, ORANGE, (0, 299), (240, 299), 1) # Doesn't scale well

            # fill the dynamic layer, make it transparent and use draw functions
            #  that write to that surface; then also blit it on top
            dynamic_surf.fill(BACKGROUND)
            dynamic_surf.set_colorkey(BACKGROUND)

            draw_statusbar()

            if SHOW_FPS:
                draw_fps()

            if ANIMATION:
                my_particles.move(dynamic_surf, my_particles_list)

            # finally take the dynamic surface and blit it to the main surface
            display_surf.blit(dynamic_surf, (0, 0))

            # now do the same for the time layer so it did not interfere with the other layers
            # fill the layer and make it transparent as well
            time_surf.fill(BACKGROUND)
            time_surf.set_colorkey(BACKGROUND)

            # draw the time to the main layer
            draw_time_layer()
            display_surf.blit(time_surf, (0, 0))

            # # draw the mouse events
            # mouse_surf.fill(BACKGROUND)
            # mouse_surf.set_colorkey(BACKGROUND)
            # draw_event(WHITE)

            # display_surf.blit(mouse_surf, (0, 0))

            # finally take the main surface and blit it to the tft surface
            tft_surf.blit(create_scaled_surf(display_surf, aa=AA), FIT_SCREEN)

            # update the display with all surfaces merged into the main one
            pygame.display.update()

        for event in pygame.event.get():

            if event.type == pygame.QUIT:
                running = False
                quit_all()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                logger.info("Screen pressed.")
                global LAST_TOUCH_TIME
                LAST_TOUCH_TIME = time.time()
                if DISPLAY_BLANK:
                    logger.info("Going from idle to active.")
                    DISPLAY_BLANK = False
                    # Scheduler will automatically resume updates when DISPLAY_BLANK = False

                # Maybe need to use "stats": "calls_count": "28", "calls_remaining": 27,
                #  answer from API here to decide whether to do new weather
                #  call right away (because there is only 50 calls in a day...)
                # (BVG is no problem, free 100 calls per minute :))

                if pygame.MOUSEBUTTONDOWN:
                    draw_event()

            elif event.type == pygame.KEYDOWN:

                if event.key == pygame.K_ESCAPE:
                    running = False
                    quit_all()

                elif event.key == pygame.K_SPACE:
                    shot_time = convert_timestamp(time.time(), "%Y-%m-%d %H-%M-%S")
                    pygame.image.save(display_surf, f"screenshot-{shot_time}.png")
                    logger.info(f"Screenshot created at {shot_time}")

        if not DISPLAY_BLANK and time.time() - LAST_TOUCH_TIME > DISPLAY_BLANK_AFTER:
            logger.info("Screen (likely/hopefully) blanked. Switching to idle.")
            DISPLAY_BLANK = True

        # do it as often as FPS configured (30 FPS recommend for particle
        #  simulation, 15 runs fine too, 60 is overkill)
        clock.tick(FPS)

    quit_all()


if __name__ == "__main__":

    try:

        if ANIMATION:
            my_particles = Particles()
            my_particles_list = my_particles.create_particle_list()

        images = image_factory(ICON_PATH)

        loop()

    except KeyboardInterrupt:

        quit_all()
