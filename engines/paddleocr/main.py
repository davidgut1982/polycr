"""
PaddleOCR engine microservice.

Why: Exposes PaddleOCR behind the standard polycr REST contract, adding a
     high-accuracy CRNN-based alternative to the other engines.
What: FastAPI service that initialises PaddleOCR at startup and returns text with
      averaged confidence from the per-line result list, plus polygon regions.
      Supports PaddleOCR 2.x list format and 3.x dict format transparently.
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
        ocr_engine = PaddleOCR(lang="en")
        logger.info("PaddleOCR engine ready.")
    except Exception as exc:
        logger.error("PaddleOCR init failed: %s", exc)
    yield


app = FastAPI(title="polycr-paddleocr", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "engine": ENGINE_NAME}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    if ocr_engine is None:
        return {"engine": ENGINE_NAME, "error": "Model not loaded"}
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(image)

        results = ocr_engine.ocr(img_array)

        lines: list[str] = []
        confidences: list[float] = []
        regions: list[dict] = []
        if results:
            for page_result in results:
                if isinstance(page_result, dict):
                    texts = page_result.get('rec_texts', [])
                    scores = page_result.get('rec_scores', [])
                    polys = page_result.get('dt_polys', page_result.get('rec_polys', []))
                    for i, (text, score) in enumerate(zip(texts, scores)):
                        poly = polys[i].tolist() if i < len(polys) else []
                        lines.append(str(text))
                        conf = float(score)
                        confidences.append(conf)
                        regions.append({
                            "polygon": poly,
                            "text": str(text),
                            "confidence": conf,
                        })
                elif isinstance(page_result, list):
                    for line in page_result:
                        if not line or len(line) < 2:
                            continue
                        box = line[0]
                        text_conf = line[1]
                        if isinstance(text_conf, (list, tuple)) and len(text_conf) >= 2:
                            text = str(text_conf[0])
                            conf = float(text_conf[1])
                        else:
                            continue
                        lines.append(text)
                        confidences.append(conf)
                        regions.append({
                            "polygon": box if isinstance(box, list) else box.tolist(),
                            "text": text,
                            "confidence": conf,
                        })

        text = "\n".join(lines).strip()
        avg_confidence = (sum(confidences) / len(confidences) * 100) if confidences else 0.0

        return {
            "engine": ENGINE_NAME,
            "text": text,
            "confidence": avg_confidence,
            "regions": regions
        }
    except Exception as exc:
        logger.error("OCR failed: %s", exc)
        return {"engine": ENGINE_NAME, "error": str(exc)}
