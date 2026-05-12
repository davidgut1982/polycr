"""
FastAPI wrapper around ocrmypdf for producing searchable PDF documents.

Why: Separates the archival PDF generation concern from the text extraction concern
     handled by polycr's /ocr endpoint, so each service can be scaled or replaced
     independently.
What: Accepts an image or PDF upload, runs ocrmypdf with configurable options,
      and returns a searchable PDF with an embedded text layer.
Test: POST a JPEG to /pdf and assert the response Content-Type is application/pdf
      and the response body is a non-empty binary. GET /health and assert {"status":"ok"}.
"""

import io
import subprocess
import tempfile
import os

from fastapi import FastAPI, File, UploadFile, Query, HTTPException
from fastapi.responses import Response, JSONResponse

app = FastAPI(title="ocrmypdf-service")


@app.get("/health")
def health():
    """
    Why: Provides a readiness probe so docker-compose and uptime monitors can
         confirm the service started successfully.
    What: Returns a static JSON body indicating the service is alive.
    Test: GET /health and assert HTTP 200 with body {"status":"ok","service":"ocrmypdf"}.
    """
    return {"status": "ok", "service": "ocrmypdf"}


@app.post("/pdf")
async def create_pdf(
    file: UploadFile = File(...),
    deskew: bool = Query(default=True, description="Deskew the input image before OCR"),
    optimize: int = Query(default=1, ge=0, le=3, description="PDF optimization level (0-3)"),
    language: str = Query(default="eng", description="Tesseract language code for OCR (e.g. 'eng', 'lav'). Must be installed in the container."),
):
    """
    Why: Produces a PDF/A-compliant searchable document suitable for archival storage
         and copy/search workflows in Nextcloud.
    What: Writes the uploaded file to a temp path, invokes ocrmypdf with the requested
          options, reads the output PDF, and streams it back as application/pdf.
    Test: POST a grayscale JPEG to /pdf?deskew=true&optimize=1 and assert the response
          is 200, Content-Type is application/pdf, and the body length is > 0.
          POST an unsupported file type and assert a 422/500 JSON error response.
    """
    input_suffix = os.path.splitext(file.filename or "upload")[1] or ".jpg"

    with tempfile.NamedTemporaryFile(suffix=input_suffix, delete=False) as tmp_in:
        tmp_in.write(await file.read())
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path + "_out.pdf"

    try:
        cmd = ["ocrmypdf"]
        if deskew:
            cmd.append("--deskew")
        cmd += ["--optimize", str(optimize), "--language", language, tmp_in_path, tmp_out_path]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail={"error": "ocrmypdf failed", "detail": result.stderr.strip()},
            )

        with open(tmp_out_path, "rb") as f:
            pdf_bytes = f.read()

        return Response(content=pdf_bytes, media_type="application/pdf")

    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": "Unexpected error", "detail": str(exc)},
        )
    finally:
        for path in (tmp_in_path, tmp_out_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
