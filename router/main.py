"""
polycr router — multi-engine OCR with LLM reconciliation.

Why: Provides a single stable REST API that fans out to all configured OCR engine
     services, preprocesses images, reconciles results via an LLM, and returns both
     raw per-engine output and a structured final answer.
What: FastAPI app exposing POST /process (full pipeline), POST /ocr/raw (engines only),
      and GET /health.  Engine selection is driven by the ENABLED_ENGINES env var.
Test: Start the router with at least the tesseract engine running; POST a JPEG to
      /process and assert the response has "text" and "engines_used" keys.
"""

import asyncio
import logging
import os

import httpx
from fastapi import FastAPI, UploadFile, File

from llm import reconcile
from models import EngineResult, ProcessResponse
from preprocess import preprocess_image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENABLED_ENGINES = os.getenv("ENABLED_ENGINES", "tesseract,easyocr,doctr").split(",")

app = FastAPI(
    title="polycr",
    description="Multi-engine OCR with LLM reconciliation",
    version="0.1.0",
)


async def call_engine(name: str, image_bytes: bytes) -> EngineResult:
    """
    Why: Isolates per-engine HTTP communication so failures in one engine never
         propagate to others or crash the router.
    What: POSTs image bytes to the named engine's /ocr endpoint within a 60-second
          timeout; wraps any exception into an EngineResult with an error field.
    Test: Point the router at a non-existent hostname; assert the returned EngineResult
          has a non-empty error field and engine == the hostname used.
    """
    url = f"http://{name}:8000/ocr"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                files={"file": ("image.jpg", image_bytes, "image/jpeg")},
            )
            data = response.json()
            return EngineResult(**data)
    except Exception as exc:
        logger.warning("Engine %s failed: %s", name, exc)
        return EngineResult(engine=name, error=str(exc))


@app.post("/process", response_model=ProcessResponse)
async def process(file: UploadFile = File(...)):
    """
    Why: Main public endpoint — runs the full polycr pipeline end-to-end.
    What: Reads upload bytes, preprocesses the image, fans out to all enabled engines
          in parallel, calls the LLM reconciler, and returns a ProcessResponse.
    Test: POST a JPEG to /process with tesseract running; assert response.status_code==200
          and response.json()["engines_used"] contains "tesseract".
    """
    image_bytes = await file.read()
    clean = preprocess_image(image_bytes)

    results = await asyncio.gather(*[call_engine(e.strip(), clean) for e in ENABLED_ENGINES])

    used = [r.engine for r in results if not r.error]
    failed = [r.engine for r in results if r.error]

    reconciled = await reconcile(list(results), clean)

    return ProcessResponse(
        text=reconciled.get("text", ""),
        structured=reconciled.get("structured", {}),
        ocr_raw=list(results),
        engines_used=used,
        engines_failed=failed,
    )


@app.post("/ocr/raw")
async def ocr_raw(file: UploadFile = File(...)):
    """
    Why: Allows callers to inspect raw engine outputs without LLM reconciliation,
         useful for debugging discrepancies or building custom reconciliation logic.
    What: Preprocesses the image and fans out to all engines; returns the raw list
          of EngineResult dicts without calling the LLM.
    Test: POST a JPEG to /ocr/raw; assert response contains "results" list with one
          entry per enabled engine.
    """
    image_bytes = await file.read()
    clean = preprocess_image(image_bytes)
    results = await asyncio.gather(*[call_engine(e.strip(), clean) for e in ENABLED_ENGINES])
    return {"results": [r.dict() for r in results]}


@app.get("/health")
async def health():
    """
    Why: Lets load balancers, Docker health checks, and monitoring tools verify
         the router is up and report which engines are configured.
    What: Returns a simple ok payload with the current ENABLED_ENGINES list.
    Test: GET /health → HTTP 200 {"status": "ok", "engines": ["tesseract", ...]}.
    """
    return {"status": "ok", "engines": ENABLED_ENGINES}
