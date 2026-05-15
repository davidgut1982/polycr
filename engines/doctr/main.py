"""docTR OCR engine microservice — PyTorch backend, CUDA."""
import io
import logging
from contextlib import asynccontextmanager

import torch
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENGINE_NAME = "doctr"
_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Loading docTR model on {device}...")
    _model = ocr_predictor(det_arch="db_resnet50", reco_arch="crnn_vgg16_bn", pretrained=True)
    if device == "cuda":
        _model = _model.cuda()
    logger.info(f"docTR ready on {device}")
    yield
    _model = None


app = FastAPI(title="docTR OCR Engine", lifespan=lifespan)


@app.get("/health")
async def health():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    gpu_mb = torch.cuda.memory_allocated(0) / 1024**2 if device == "cuda" and torch.cuda.is_available() else None
    return {"status": "ok", "engine": ENGINE_NAME, "device": device, "model_loaded": _model is not None, "gpu_memory_mb": gpu_mb}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...), language: str = "eng"):
    if _model is None:
        return JSONResponse({"engine": ENGINE_NAME, "text": "", "confidence": 0.0, "error": "model not loaded"}, status_code=503)
    img_bytes = await file.read()
    try:
        doc = DocumentFile.from_images([img_bytes])
        result = _model(doc)
        blocks = []
        confidences = []
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    line_text = " ".join(w.value for w in line.words)
                    line_conf = sum(w.confidence for w in line.words) / max(len(line.words), 1)
                    blocks.append(line_text)
                    confidences.append(line_conf)
        text = "\n".join(blocks)
        confidence = sum(confidences) / max(len(confidences), 1) if confidences else 0.0
        return {"engine": ENGINE_NAME, "text": text, "confidence": round(confidence, 4), "error": None}
    except Exception as e:
        logger.error(f"docTR inference error: {e}")
        return JSONResponse({"engine": ENGINE_NAME, "text": "", "confidence": 0.0, "error": str(e)}, status_code=500)
