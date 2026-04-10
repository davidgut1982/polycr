"""
docTR OCR engine microservice.

Why: Exposes docTR's end-to-end document understanding behind the standard polycr
     REST contract so the router can use it interchangeably with other engines.
What: FastAPI service that loads an ocr_predictor at startup, accepts image uploads,
      and extracts text from all detected document blocks with averaged confidence.
Test: POST /ocr with a text image → engine=="doctr" and non-empty text;
      GET /health → {"status": "ok", "engine": "doctr"}.
"""

import io
import logging
from contextlib import asynccontextmanager

import numpy as np
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
from fastapi import FastAPI, UploadFile, File
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENGINE_NAME = "doctr"
predictor = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Download and load docTR detection + recognition models at startup."""
    global predictor
    logger.info("Loading docTR ocr_predictor...")
    try:
        predictor = ocr_predictor(pretrained=True)
        logger.info("docTR predictor loaded.")
    except Exception as exc:
        logger.error("docTR model load failed: %s", exc)
    yield


app = FastAPI(title="polycr-doctr", lifespan=lifespan)


@app.get("/health")
async def health():
    """
    Why: Health probe for Docker and the polycr router.
    What: Returns ok payload with engine name.
    Test: GET /health → HTTP 200 {"status": "ok", "engine": "doctr"}.
    """
    return {"status": "ok", "engine": ENGINE_NAME}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    """
    Why: Standard OCR endpoint consumed by the router.
    What: Writes upload bytes to a docTR DocumentFile, runs the predictor, iterates
          all page/block/line/word nodes to collect text and confidence, and returns
          the standardised result dict.
    Test: POST a JPEG with "Invoice 2026" → text contains "Invoice", confidence > 0.
    """
    if predictor is None:
        return {"engine": ENGINE_NAME, "error": "Model not loaded"}
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(image)

        doc = DocumentFile.from_images([img_array])
        result = predictor(doc)

        words: list[str] = []
        confidences: list[float] = []
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    for word in line.words:
                        words.append(word.value)
                        confidences.append(float(word.confidence))

        text = " ".join(words).strip()
        avg_confidence = (sum(confidences) / len(confidences) * 100) if confidences else 0.0

        return {"engine": ENGINE_NAME, "text": text, "confidence": avg_confidence}
    except Exception as exc:
        logger.error("OCR failed: %s", exc)
        return {"engine": ENGINE_NAME, "error": str(exc)}
