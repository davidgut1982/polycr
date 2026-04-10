"""
Surya OCR engine microservice.

Why: Adds Surya's transformer-based multilingual OCR as a polycr engine option,
     useful for complex layouts and non-Latin scripts.
What: FastAPI service that pre-loads detection and recognition models at startup,
      runs run_ocr on uploaded images, and returns text with averaged line confidence.
Test: POST /ocr with an English text image → engine=="surya" and non-empty text;
      GET /health → {"status": "ok", "engine": "surya"}.
"""

import io
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File
from PIL import Image
from surya.model.detection.model import load_model as load_det_model, load_processor as load_det_processor
from surya.model.recognition.model import load_model as load_rec_model
from surya.model.recognition.processor import load_processor as load_rec_processor
from surya.ocr import run_ocr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENGINE_NAME = "surya"

det_model = None
det_processor = None
rec_model = None
rec_processor = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Download and cache Surya detection + recognition models at startup."""
    global det_model, det_processor, rec_model, rec_processor
    logger.info("Loading Surya OCR models...")
    try:
        det_model = load_det_model()
        det_processor = load_det_processor()
        rec_model = load_rec_model()
        rec_processor = load_rec_processor()
        logger.info("Surya models loaded.")
    except Exception as exc:
        logger.error("Surya model load failed: %s", exc)
    yield


app = FastAPI(title="polycr-surya", lifespan=lifespan)


@app.get("/health")
async def health():
    """
    Why: Docker and router health probe.
    What: Returns ok payload with engine name.
    Test: GET /health → HTTP 200 {"status": "ok", "engine": "surya"}.
    """
    return {"status": "ok", "engine": ENGINE_NAME}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    """
    Why: Standard OCR endpoint consumed by the router.
    What: Opens uploaded image, calls run_ocr with ['en'] langs, iterates over
          OCRResult text lines to collect text and confidence, returns standardised dict.
    Test: POST a PNG with "Meeting at 3pm" → text contains "Meeting", confidence > 0.
    """
    if det_model is None or rec_model is None:
        return {"engine": ENGINE_NAME, "error": "Models not loaded"}
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        results = run_ocr(
            [image],
            [["en"]],
            det_model,
            det_processor,
            rec_model,
            rec_processor,
        )

        lines: list[str] = []
        confidences: list[float] = []
        for page_result in results:
            for line in page_result.text_lines:
                lines.append(line.text)
                confidences.append(float(line.confidence))

        text = " ".join(lines).strip()
        avg_confidence = (sum(confidences) / len(confidences) * 100) if confidences else 0.0

        return {"engine": ENGINE_NAME, "text": text, "confidence": avg_confidence}
    except Exception as exc:
        logger.error("OCR failed: %s", exc)
        return {"engine": ENGINE_NAME, "error": str(exc)}
