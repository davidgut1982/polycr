"""
Tesseract OCR engine microservice.

Why: Provides a standardized REST interface for Tesseract OCR so the router
     can fan out requests to multiple engines without engine-specific logic.
What: FastAPI service that accepts image uploads, runs pytesseract, and returns
      extracted text with average confidence score.
Test: POST /ocr with a JPEG image containing text, assert response has engine=="tesseract"
      and non-empty text field; GET /health returns {"status": "ok"}.
"""

import io
import logging
from contextlib import asynccontextmanager

import pytesseract
from fastapi import FastAPI, UploadFile, File
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENGINE_NAME = "tesseract"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm tesseract by running a tiny test so the first real request is fast."""
    logger.info("Pre-warming tesseract engine...")
    try:
        dummy = Image.new("RGB", (10, 10), color="white")
        pytesseract.image_to_string(dummy)
        logger.info("Tesseract engine ready.")
    except Exception as exc:
        logger.error("Tesseract warm-up failed: %s", exc)
    yield


app = FastAPI(title="polycr-tesseract", lifespan=lifespan)


@app.get("/health")
async def health():
    """
    Why: Allows the router and Docker health checks to verify this engine is up.
    What: Returns a simple ok payload with the engine name.
    Test: GET /health returns HTTP 200 with body {"status": "ok", "engine": "tesseract"}.
    """
    return {"status": "ok", "engine": ENGINE_NAME}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    """
    Why: Central OCR endpoint consumed by the polycr router.
    What: Reads an uploaded image, runs pytesseract for text and per-word confidence,
          averages confidence across all detected words, and returns a standardised result.
    Test: POST an image with the word "Hello" — expect text containing "Hello" and
          confidence between 0 and 100; POST a blank image — expect empty text, no error key.
    """
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))

        text = pytesseract.image_to_string(image).strip()

        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        confidences = [
            float(c)
            for c in data["conf"]
            if str(c).lstrip("-").isdigit() and int(c) >= 0
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return {"engine": ENGINE_NAME, "text": text, "confidence": avg_confidence}
    except Exception as exc:
        logger.error("OCR failed: %s", exc)
        return {"engine": ENGINE_NAME, "error": str(exc)}
