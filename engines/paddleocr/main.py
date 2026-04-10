"""
PaddleOCR engine microservice.

Why: Exposes PaddleOCR behind the standard polycr REST contract, adding a
     high-accuracy CRNN-based alternative to the other engines.
What: FastAPI service that initialises PaddleOCR at startup and returns text with
      averaged confidence from the per-line result list.
Test: POST /ocr with a receipt image → engine=="paddleocr" and non-empty text;
      GET /health → {"status": "ok", "engine": "paddleocr"}.
"""

import io
import logging
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, UploadFile, File
from paddleocr import PaddleOCR
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENGINE_NAME = "paddleocr"
ocr_engine: PaddleOCR | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Download PaddleOCR models and warm-up the engine at startup."""
    global ocr_engine
    logger.info("Initialising PaddleOCR engine...")
    try:
        ocr_engine = PaddleOCR(use_angle_cls=True, lang="en", use_gpu=False, show_log=False)
        logger.info("PaddleOCR engine ready.")
    except Exception as exc:
        logger.error("PaddleOCR init failed: %s", exc)
    yield


app = FastAPI(title="polycr-paddleocr", lifespan=lifespan)


@app.get("/health")
async def health():
    """
    Why: Docker and router health probe.
    What: Returns ok payload with engine name.
    Test: GET /health → HTTP 200 {"status": "ok", "engine": "paddleocr"}.
    """
    return {"status": "ok", "engine": ENGINE_NAME}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    """
    Why: Standard OCR endpoint consumed by the router.
    What: Converts uploaded image to numpy array, runs PaddleOCR, flattens the
          nested result list (pages → lines → [box, (text, conf)]) and averages
          confidence across all detected text regions.
    Test: POST a document image → expect text and confidence > 0 for real content.
    """
    if ocr_engine is None:
        return {"engine": ENGINE_NAME, "error": "Model not loaded"}
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(image)

        results = ocr_engine.ocr(img_array, cls=True)

        lines: list[str] = []
        confidences: list[float] = []
        if results:
            for page in results:
                if page:
                    for line in page:
                        text_conf = line[1]
                        lines.append(text_conf[0])
                        confidences.append(float(text_conf[1]))

        text = "\n".join(lines).strip()
        avg_confidence = (sum(confidences) / len(confidences) * 100) if confidences else 0.0

        return {"engine": ENGINE_NAME, "text": text, "confidence": avg_confidence}
    except Exception as exc:
        logger.error("OCR failed: %s", exc)
        return {"engine": ENGINE_NAME, "error": str(exc)}
