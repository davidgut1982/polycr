# polycr

Multi-engine OCR pipeline with LLM reconciliation, packaged as a Docker Compose stack with a single REST API.

polycr fans out every image to multiple OCR engines in parallel, then uses a vision-capable LLM to reconcile the outputs into one high-confidence transcription and extract structured fields (dates, names, prices, contact info, etc.).

---

## Used With

[ocr-mcp](https://github.com/davidgut1982/ocr-mcp) — MCP server that wraps this stack and exposes OCR tools to OpenClaw. Calls the `/ocr/raw` endpoint and handles engine selection, fallback, and image preprocessing.

---

## Quick start

```bash
# 1. Clone and configure
git clone https://github.com/davidgut1982/polycr.git && cd polycr
cp .env.example .env
# Edit .env — set LLM_API_KEY at minimum

# 2. Start the default stack (router + tesseract + easyocr + doctr)
make up

# 3. Wait for services to be healthy (~60 s on first run, models download)
docker compose logs -f

# 4. Send an image
curl -X POST http://localhost:8000/process \
  -F "file=@/path/to/document.jpg" | jq .
```

---

## curl examples

### Full pipeline (OCR + LLM reconciliation)
```bash
curl -X POST http://localhost:8000/process \
  -F "file=@invoice.jpg" | jq '{text, structured, engines_used}'
```

### Raw OCR only (no LLM)
```bash
curl -X POST http://localhost:8000/ocr/raw \
  -F "file=@invoice.jpg" | jq '.results[] | {engine, confidence, text}'
```

### Health check
```bash
curl http://localhost:8000/health
# {"status":"ok","engines":["tesseract","easyocr","doctr"]}
```

---

## Engines

| Engine | Technology | Notes |
|--------|-----------|-------|
| `tesseract` | Tesseract 4 (LSTM) | Fastest; best for clean printed text |
| `easyocr` | CRNN deep learning | Good on varied fonts and orientations |
| `doctr` | Transformer (docTR) | Strong on document layouts |
| `paddleocr` | PaddlePaddle CRNN | High accuracy; large download |
| `surya` | Transformer (Surya) | Multilingual; best layout understanding |

Default stack (`ENABLED_ENGINES=tesseract,easyocr,doctr`) balances speed and accuracy without requiring the `full` profile.

Enable all engines:
```bash
docker compose --profile full up -d
```

---

## LLM providers

| Provider | `LLM_PROVIDER` | Example model |
|----------|---------------|--------------|
| Anthropic | `anthropic` | `claude-haiku-4-5-20251001` |
| OpenAI | `openai` | `gpt-4o` |
| OpenRouter | `openrouter` | `qwen/qwen2.5-vl-72b-instruct` |
| Groq | `groq` | `llama-3.2-11b-vision-preview` |

If `LLM_API_KEY` is not set, the `/process` endpoint falls back to the highest-confidence engine result with no structured extraction.

---

## CPU vs GPU

| Mode | Command | Notes |
|------|---------|-------|
| CPU (default) | `make up` | Works everywhere; slower inference |
| GPU (NVIDIA) | `make up-gpu` | Requires nvidia-container-toolkit |
| Minimal (tesseract only) | `make up-minimal` | Fastest start; no model downloads |

---

## Architecture

polycr exposes two complementary services:

| Service | Port | Purpose |
|---------|------|---------|
| `router` (polycr) | 8000 | Multi-engine text extraction — fans out to OCR engines, reconciles with an LLM, returns structured text. Used for document classification and filename generation. |
| `ocrmypdf` | 8001 | Archival PDF generation — wraps ocrmypdf to produce a searchable PDF with an embedded text layer. Used to create the final stored document. |

These are intentionally separate: the router is optimised for high-confidence text extraction (queried first), and ocrmypdf is optimised for producing a compact, searchable PDF suitable for long-term storage. A typical scan pipeline calls both in sequence:

```
scan_document → JPEG temp file
    ↓
:8000/ocr/raw   — multi-engine text extraction (classification + filename)
    ↓
:8001/pdf       — searchable PDF with embedded text layer (archival copy)
    ↓
Upload to Nextcloud
```

---

## API reference

### `POST /process`

Full pipeline: preprocess → OCR fan-out → LLM reconciliation.

**Request:** `multipart/form-data` with `file` field (JPEG/PNG/TIFF/BMP).

**Response:**
```json
{
  "text": "reconciled full text",
  "structured": {
    "date": "2026-04-10",
    "total": "$142.50"
  },
  "ocr_raw": [
    {"engine": "tesseract", "text": "...", "confidence": 87.3, "error": ""}
  ],
  "engines_used": ["tesseract", "easyocr", "doctr"],
  "engines_failed": []
}
```

### `POST /ocr/raw`

OCR fan-out only — no LLM call.

**Response:**
```json
{
  "results": [
    {"engine": "tesseract", "text": "...", "confidence": 87.3, "error": ""}
  ]
}
```

### `GET /health`

Readiness probe.

**Response:** `{"status": "ok", "engines": ["tesseract", "easyocr", "doctr"]}`

---

### ocrmypdf service (port 8001)

#### `POST /pdf`

Run ocrmypdf on an uploaded image or PDF and return a searchable PDF.

**Request:** `multipart/form-data` with `file` field (JPEG/PNG/PDF/TIFF).

**Query params:**

| Param | Default | Description |
|-------|---------|-------------|
| `deskew` | `true` | Deskew the input image before OCR |
| `optimize` | `1` | PDF optimization level (0 = none, 3 = maximum) |

**Response (success):** PDF binary with `Content-Type: application/pdf`.

**Response (error):** `{"error": "...", "detail": "..."}` with a 5xx status code.

#### `GET /health`

Readiness probe for the ocrmypdf service.

**Response:** `{"status": "ok", "service": "ocrmypdf"}`

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | LLM provider: anthropic, openai, openrouter, groq |
| `LLM_API_KEY` | _(none)_ | API key for the chosen provider |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | Model identifier |
| `ENABLED_ENGINES` | `tesseract,easyocr,doctr` | Comma-separated engine list |
| `PORT` | `8000` | Host port for the router |

---

## Contributing

1. Fork the repository and create a feature branch.
2. Run `make up-minimal` to start a dev stack.
3. Run `make test` to validate your changes.
4. Open a pull request — the CI workflow will run integration tests automatically.

Engine additions follow the same contract: `POST /ocr` + `GET /health`, multipart file upload, JSON response `{engine, text, confidence}`.
