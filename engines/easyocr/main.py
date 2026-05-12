"""
EasyOCR engine microservice.

Why: Provides EasyOCR deep-learning OCR behind the same REST contract as all
     other polycr engines, enabling the router to fan-out without special cases.
What: FastAPI service that loads an EasyOCR Reader at startup (GPU off by default)
      and exposes POST /ocr returning text with averaged per-detection confidence.
Test: POST /ocr with a text image — expect engine=="easyocr" and non-empty text;
      GET /health returns {"status": "ok", "engine": "easyocr"}.
"""

import io
import logging
from contextlib import asynccontextmanager

import easyocr
import numpy as np
from fastapi import FastAPI, UploadFile, File
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENGINE_NAME = "easyocr"
reader: easyocr.Reader | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load EasyOCR model weights at startup so the first request is fast."""
    global reader
    logger.info("Loading EasyOCR model (this may take a while on first run)...")
    try:
        reader = easyocr.Reader(["en", "lv"], gpu=False)
        logger.info("EasyOCR model loaded.")
    except Exception as exc:
        logger.error("EasyOCR model load failed: %s", exc)
    yield


app = FastAPI(title="polycr-easyocr", lifespan=lifespan)


@app.get("/health")
async def health():
    """
    Why: Lets the router and Docker health checks verify readiness.
    What: Returns ok payload with engine name.
    Test: GET /health → HTTP 200 {"status": "ok", "engine": "easyocr"}.
    """
    return {"status": "ok", "engine": ENGINE_NAME}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    """
    Why: Central OCR endpoint consumed by the polycr router.
    What: Reads an uploaded image, runs EasyOCR readtext, averages confidence across
          all bounding-box detections, and returns the standardised result dict.
    Test: POST an image with "Hello World" → text contains "Hello", confidence > 0;
          POST a blank image → text is empty string, no error key in response.
    """
    if reader is None:
        return {"engine": ENGINE_NAME, "error": "Model not loaded"}
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(image)

        results = reader.readtext(img_array)

        lines: list[str] = [detection[1] for detection in results]
        confidences: list[float] = [float(detection[2]) for detection in results]

        text = " ".join(lines).strip()
        avg_confidence = (sum(confidences) / len(confidences) * 100) if confidences else 0.0

        return {"engine": ENGINE_NAME, "text": text, "confidence": avg_confidence}
    except Exception as exc:
        logger.error("OCR failed: %s", exc)
        return {"engine": ENGINE_NAME, "error": str(exc)}
