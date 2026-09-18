"""Regenerates icons/merz_sprite.png (the MERZ minigame's pixel-art
sprite) from a source photo. Not part of the app's runtime - a one-off/
re-run-if-you-want-to-retune-it asset-prep script, same spirit as the
other dev/ utilities.

Needs opencv-python-headless + numpy for the GrabCut background removal
(deliberately not added to the main requirements.txt - the runtime app
never imports cv2/numpy, only this offline script does):
    pip install opencv-python-headless numpy

Source photo: Friedrich Merz, 26.06.2025, by Sophie Hugon, (c) European
Union - https://commons.wikimedia.org/wiki/File:Friedrich_Merz,_2025.06.26_(01).jpg
Attribution-only license, explicitly permits derivative works (unlike the
alternative candidate photo by the White House's Daniel Torok, which
explicitly forbids manipulation - deliberately not used for that reason).
The source JPG itself isn't committed (only the small derived pixel-art
PNG is) - download it from the URL above to `SRC` if you want to re-run
this with different crop/resolution/GrabCut settings.
"""

import cv2
import numpy as np
from PIL import Image

SRC = "merz_source_photo.jpg"  # download from the Commons URL above
OUT = "icons/merz_sprite.png"

# Generous rect (x, y, w, h) for GrabCut to learn background/foreground
# color stats from - needs real background margin around the person,
# unlike FINAL_CROP below which is deliberately tight.
GRABCUT_RECT = (55, 15, 430, 700)
FINAL_CROP = (85, 15, 395, 470)  # (left, upper, right, lower), within the ORIGINAL image
GRID_W, GRID_H = 28, 38  # pixel-art resolution
CELL = 6  # final on-screen px per grid cell
PALETTE_COLORS = 32


def main():
    img_bgr = cv2.imread(SRC)
    mask = np.zeros(img_bgr.shape[:2], np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(img_bgr, mask, GRABCUT_RECT, bgd_model, fgd_model, 8, cv2.GC_INIT_WITH_RECT)
    fg_mask = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype("uint8")

    # GrabCut misreads the glasses lenses as background (they're
    # reflective/light, similar to the blurred background tone) and
    # punches small holes through the middle of the face - morphological
    # closing (dilate then erode) fills those interior holes without
    # eating into the real silhouette edge.
    close_kernel = np.ones((15, 15), np.uint8)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, close_kernel)
    fg_mask = cv2.medianBlur(fg_mask, 5)  # smooth ragged single-pixel mask edges

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    full = Image.fromarray(np.dstack([img_rgb, fg_mask]), mode="RGBA")
    cropped = full.crop(FINAL_CROP)

    small = cropped.resize((GRID_W, GRID_H), Image.BOX)
    quantized = small.convert("RGB").quantize(colors=PALETTE_COLORS, method=Image.MEDIANCUT)
    quantized = quantized.convert("RGB")
    quantized.putalpha(small.split()[3])  # re-attach alpha lost during RGB quantization

    big = quantized.resize((GRID_W * CELL, GRID_H * CELL), Image.NEAREST)
    big.save(OUT)
    print(f"saved {OUT} ({big.size[0]}x{big.size[1]})")


if __name__ == "__main__":
    main()
