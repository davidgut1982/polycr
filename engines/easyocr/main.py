"""EasyOCR engine microservice."""

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
    global reader
    logger.info("Loading EasyOCR model...")
    try:
        reader = easyocr.Reader(["en", "lv"], gpu=True)
        logger.info("EasyOCR model loaded.")
    except Exception as exc:
        logger.error("EasyOCR model load failed: %s", exc)
    yield


app = FastAPI(title="polycr-easyocr", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "engine": ENGINE_NAME}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    if reader is None:
        return {"engine": ENGINE_NAME, "error": "Model not loaded"}
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(image)
        results = reader.readtext(img_array)
        lines = [detection[1] for detection in results]
        confidences = [float(detection[2]) for detection in results]
        text = " ".join(lines).strip()
        avg_confidence = (sum(confidences) / len(confidences) * 100) if confidences else 0.0
        return {"engine": ENGINE_NAME, "text": text, "confidence": avg_confidence}
    except Exception as exc:
        logger.error("OCR failed: %s", exc)
        return {"engine": ENGINE_NAME, "error": str(exc)}
