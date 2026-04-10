"""
Integration test suite for the polycr API.

Why: Validates the full API contract (health probe, raw OCR fan-out, full LLM
     pipeline) against a live running stack without any external image dependencies.
What: Generates a synthetic test image via Pillow, runs it through all three
     endpoints, prints a timing table, and asserts correctness invariants.
Test: Run directly with `python tests/test_pipeline.py` against a running stack,
      or via `make test` which starts the minimal stack first.
"""

import io
import os
import sys
import time
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont

BASE_URL = os.getenv("POLYCR_BASE_URL", "http://localhost:8000")

# ── Synthetic test image ──────────────────────────────────────────────────────

def make_test_image() -> bytes:
    """
    Why: Eliminates external file dependencies in tests; any CI runner can generate
         a valid image with predictable text content using only Pillow.
    What: Creates a 600x200 white JPEG with black text "Hello World 2026-04-10"
          centred on the canvas.
    Test: Assert the returned bytes start with JPEG magic bytes 0xFF 0xD8.
    """
    img = Image.new("RGB", (600, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    text = "Hello World 2026-04-10"
    try:
        # Try to use a system font for better OCR results
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
    except (IOError, OSError):
        # Fall back to default bitmap font
        font = ImageFont.load_default()

    # Centre the text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (600 - text_w) // 2
    y = (200 - text_h) // 2
    draw.text((x, y), text, fill=(0, 0, 0), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# ── Test helpers ──────────────────────────────────────────────────────────────

def _post_image(endpoint: str, image_bytes: bytes) -> tuple[dict[str, Any], float]:
    """Post image bytes to an endpoint and return (json_body, elapsed_seconds)."""
    start = time.perf_counter()
    response = requests.post(
        f"{BASE_URL}{endpoint}",
        files={"file": ("test.jpg", image_bytes, "image/jpeg")},
        timeout=120,
    )
    elapsed = time.perf_counter() - start
    response.raise_for_status()
    return response.json(), elapsed


def _print_timing_table(rows: list[tuple[str, float, str]]) -> None:
    """Print a formatted timing table to stdout."""
    print("\n" + "=" * 60)
    print(f"{'Endpoint':<25}  {'Time (s)':>8}  {'Status'}")
    print("-" * 60)
    for endpoint, elapsed, status in rows:
        print(f"{endpoint:<25}  {elapsed:>8.2f}  {status}")
    print("=" * 60 + "\n")


# ── Individual tests ──────────────────────────────────────────────────────────

def test_health(timings: list) -> None:
    """
    Why: Confirms the router is reachable and reports its engine list.
    What: GET /health and assert status==ok and engines list is non-empty.
    Test: Assert no exception and body contains "status": "ok".
    """
    start = time.perf_counter()
    response = requests.get(f"{BASE_URL}/health", timeout=10)
    elapsed = time.perf_counter() - start
    response.raise_for_status()
    body = response.json()

    assert body.get("status") == "ok", f"Expected status ok, got: {body}"
    assert isinstance(body.get("engines"), list), "Expected engines list"
    assert len(body["engines"]) > 0, "Expected at least one engine"

    timings.append(("/health", elapsed, f"ok — engines: {body['engines']}"))
    print(f"[PASS] /health — engines: {body['engines']}")


def test_ocr_raw(image_bytes: bytes, timings: list) -> None:
    """
    Why: Validates raw fan-out returns one result per enabled engine.
    What: POST /ocr/raw and assert results list contains engine-keyed entries.
    Test: Assert len(results) >= 1 and each entry has an "engine" key.
    """
    body, elapsed = _post_image("/ocr/raw", image_bytes)

    assert "results" in body, f"Expected 'results' key, got: {list(body.keys())}"
    results = body["results"]
    assert len(results) >= 1, f"Expected at least 1 engine result, got {len(results)}"

    for r in results:
        assert "engine" in r, f"Missing 'engine' key in result: {r}"

    engines = [r["engine"] for r in results]
    successful = [r for r in results if not r.get("error")]
    timings.append((
        "/ocr/raw",
        elapsed,
        f"ok — {len(successful)}/{len(results)} engines succeeded",
    ))
    print(f"[PASS] /ocr/raw — engines: {engines}")
    for r in results:
        if r.get("error"):
            print(f"       WARNING: {r['engine']} error: {r['error']}")
        else:
            snippet = r.get("text", "")[:60].replace("\n", " ")
            print(f"       {r['engine']}: conf={r.get('confidence', 0):.1f}  text={snippet!r}")


def test_process(image_bytes: bytes, timings: list) -> None:
    """
    Why: Validates the full pipeline endpoint returns the expected schema.
    What: POST /process and assert text, structured, ocr_raw, engines_used keys exist.
    Test: If LLM_API_KEY is not set the router falls back to best-engine text;
          assert text field is a string regardless.
    """
    body, elapsed = _post_image("/process", image_bytes)

    assert "text" in body, f"Missing 'text' key: {list(body.keys())}"
    assert "structured" in body, f"Missing 'structured' key"
    assert "ocr_raw" in body, f"Missing 'ocr_raw' key"
    assert "engines_used" in body, f"Missing 'engines_used' key"
    assert "engines_failed" in body, f"Missing 'engines_failed' key"
    assert isinstance(body["text"], str), "Expected text to be a string"
    assert isinstance(body["structured"], dict), "Expected structured to be a dict"

    text_snippet = body["text"][:80].replace("\n", " ")
    timings.append((
        "/process",
        elapsed,
        f"ok — {len(body['engines_used'])} engines used",
    ))
    print(f"[PASS] /process — text={text_snippet!r}")
    print(f"       engines_used: {body['engines_used']}")
    print(f"       engines_failed: {body['engines_failed']}")
    print(f"       structured fields: {list(body['structured'].keys())}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    """
    Why: Orchestrates all tests, prints a timing summary, and returns a non-zero
         exit code on failure so CI fails cleanly.
    What: Generates a synthetic test image, runs health/raw/process tests in order,
          prints a timing table, and reports pass/fail counts.
    Test: All three tests should pass against a running minimal stack.
    """
    print(f"\npolycr integration tests — target: {BASE_URL}\n")

    image_bytes = make_test_image()
    assert image_bytes[:2] == b"\xff\xd8", "make_test_image did not produce JPEG bytes"
    print(f"[INFO] Synthetic test image: {len(image_bytes)} bytes\n")

    timings: list[tuple[str, float, str]] = []
    failures: list[str] = []

    for name, fn, args in [
        ("test_health", test_health, (timings,)),
        ("test_ocr_raw", test_ocr_raw, (image_bytes, timings)),
        ("test_process", test_process, (image_bytes, timings)),
    ]:
        try:
            fn(*args)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            timings.append((name, 0.0, f"FAIL — {exc}"))
            print(f"[FAIL] {name}: {exc}")

    _print_timing_table(timings)

    if failures:
        print(f"FAILED: {len(failures)} test(s) failed.")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"PASSED: all {len(timings)} tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
