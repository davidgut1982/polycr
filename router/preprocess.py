"""
Image preprocessing pipeline for the polycr router.

Why: Raw scanned images often have EXIF rotation, poor contrast, or low resolution
     that degrades OCR accuracy across all engines; centralising preprocessing ensures
     consistent improvements without duplicating logic in each engine service.
What: Applies auto-orientation and deskew via ImageMagick (wand), followed by
      CLAHE contrast enhancement and optional upscaling via OpenCV.
Test: Pass a 200x200 JPEG of rotated text through preprocess_image, assert the returned
      bytes are valid JPEG (starts with b'\\xff\\xd8') and the decoded image is >= 200px
      on the long edge; pass a 2000px image and assert it is NOT upscaled.
"""

import io
import logging

import cv2
import numpy as np
from PIL import Image as PILImage
from wand.image import Image as WandImage

logger = logging.getLogger(__name__)

_MIN_DIMENSION_PX = 1000
_JPEG_QUALITY = 95
_CLAHE_CLIP_LIMIT = 3.0
_CLAHE_TILE_GRID = (8, 8)
_DESKEW_THRESHOLD = 0.4


def preprocess_image(image_bytes: bytes) -> bytes:
    """
    Why: Improves OCR accuracy by correcting common image quality issues before
         fan-out to all engine services.
    What: (1) Auto-orients EXIF rotation and deskews with ImageMagick, (2) optionally
          upscales small images with bicubic interpolation, (3) normalises contrast
          using CLAHE in LAB colour space, (4) returns JPEG bytes.
    Test: Call with a base64-decoded JPEG — the return value must start with b'\\xff\\xd8'
          and be parseable by PIL.Image.open without errors.
    """
    try:
        processed = _orient_and_deskew(image_bytes)
        processed = _enhance_contrast_and_scale(processed)
        return processed
    except Exception as exc:
        logger.warning("Preprocessing failed (%s); returning original bytes.", exc)
        return image_bytes


def _orient_and_deskew(image_bytes: bytes) -> bytes:
    """
    Why: EXIF rotation and scanner skew are the two most common sources of
         orientation-induced OCR errors.
    What: Uses wand (ImageMagick) to auto-orient the image based on EXIF data,
          then applies a deskew operation with a threshold of 40% of quantum range.
    Test: Pass bytes of a 90-degree rotated JPEG; assert the output PIL image has
          its width > height (portrait input becomes landscape output).
    """
    with WandImage(blob=image_bytes) as img:
        img.auto_orient()
        img.deskew(_DESKEW_THRESHOLD * img.quantum_range)
        return img.make_blob("jpeg")


def _enhance_contrast_and_scale(image_bytes: bytes) -> bytes:
    """
    Why: Low-resolution or low-contrast images produce poor OCR results; upscaling
         and CLAHE address both without introducing artefacts.
    What: Decodes JPEG bytes into a BGR numpy array, upscales if max dimension is
          below 1000 px, applies CLAHE on the L channel in LAB space, and returns
          JPEG bytes at quality 95.
    Test: Pass a 400px image; assert the returned image long edge >= 1000px.
          Pass a 2000px image; assert its dimensions are unchanged.
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img_cv = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    h, w = img_cv.shape[:2]
    if max(h, w) < _MIN_DIMENSION_PX:
        scale = _MIN_DIMENSION_PX / max(h, w)
        img_cv = cv2.resize(img_cv, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    lab = cv2.cvtColor(img_cv, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=_CLAHE_CLIP_LIMIT, tileGridSize=_CLAHE_TILE_GRID)
    l_channel = clahe.apply(l_channel)
    lab = cv2.merge([l_channel, a_channel, b_channel])
    img_cv = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    _, buf = cv2.imencode(".jpg", img_cv, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
    return buf.tobytes()
