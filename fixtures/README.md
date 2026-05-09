# Edge Detection Fixture Suite

## Purpose

This fixture suite tests the `POST /detect-edges` endpoint of the polycr router. It validates the edge-based document detection pipeline (Canny + contour analysis) against a collection of real receipt photographs with known characteristics.

## Structure

```
/home/david/polycr-fixtures/
├── README.md                       (this file)
├── run-fixtures.sh                 (test runner)
├── 01-clean-counter/               (scenario directories)
│   ├── input.jpg                   (seed photograph)
│   ├── baseline_run.json           (current /detect-edges output)
│   └── expected.json               (desired output, Phase C/D target)
├── 02-busy-table/
├── 03-low-contrast/
├── ... (10 scenarios total)
└── 10-sideways-clean/
```

## Scenarios

| Fixture | Source | Description | Current Status |
|---------|--------|-------------|-----------------|
| 01-clean-counter | receipts-web 3fa6cd25 | Clean receipt on counter, good lighting | BASELINE |
| 02-busy-table | receipts-web 97fd5469 | Receipt among table clutter | BASELINE |
| 03-low-contrast | receipts-web 97fd5469-raw_001 | Faded/low-contrast paper | BASELINE |
| 04-lying-flat | receipts-web 97fd5469-raw_002 | Receipt lying flat, overhead shot | BASELINE |
| 05-steep-angle | receipts-web 60635b44 | Receipt at steep camera angle | BASELINE |
| 06-handheld | receipts-web c2e68322 | Handheld, slightly blurred | BASELINE |
| 07-thin-strip | receipts-web 5367220c | Partial receipt, thin vertical strip | BASELINE |
| 08-near-square | receipts-web 881d82c6 | Nearly square aspect ratio | BASELINE |
| 09-portrait-clean | receipts-web 67abd6ad | Portrait orientation, clean | BASELINE |
| 10-sideways-clean | receipts-web 8c14af04 | Horizontal/landscape receipt | BASELINE |

## Running Tests

### Against local service (localhost:8000)
```bash
cd /home/david/polycr-fixtures
./run-fixtures.sh
```

### Against remote host
```bash
BASE_URL=http://192.168.1.11:8000 /home/david/polycr-fixtures/run-fixtures.sh
```

### From another machine
```bash
ssh david@192.168.1.11 "cd /home/david/polycr-fixtures && BASE_URL=http://localhost:8000 ./run-fixtures.sh"
```

## Files Explained

### baseline_run.json
Captures the CURRENT output from `/detect-edges` for each fixture. Establishes the baseline behavior before improvements.

**Example (no rectangle found):**
```json
{
  "corners": null,
  "bbox": null,
  "confidence": 0.0,
  "error": "no valid quadrilateral found",
  "method": "edges"
}
```

**Example (rectangle found):**
```json
{
  "corners": [[100, 200], [800, 200], [800, 1200], [100, 1200]],
  "bbox": {"x": 100, "y": 200, "width": 700, "height": 1000},
  "confidence": 0.85,
  "method": "edges"
}
```

### expected.json
Defines DESIRED behavior for this scenario. Used in Phase C/D to validate improvements.

**Schema:**
```json
{
  "scenario": "lying-flat",
  "description": "Receipt photographed from above, lying horizontal on table",
  "expect": {
    "edges": {
      "should_succeed": true,
      "method_in": ["canny", "adaptive"],
      "area_ratio_min": 0.30,
      "area_ratio_max": 0.92,
      "confidence_min": 0.20
    },
    "correct_output": {
      "must_be_portrait": true,
      "aspect_min": 1.2,
      "aspect_max": 4.0
    }
  }
}
```

## Adding a New Fixture

1. Get a receipt photo from receipts-web:
   ```bash
   ssh david@192.168.1.9 "find /home/david/receipts-web/data/batches -name raw_000.jpg" | head -1
   ```

2. Create fixture directory:
   ```bash
   mkdir -p /home/david/polycr-fixtures/11-new-scenario
   scp david@192.168.1.9:/path/to/receipt.jpg /home/david/polycr-fixtures/11-new-scenario/input.jpg
   ```

3. Run test to capture baseline:
   ```bash
   cd /home/david/polycr-fixtures
   BASE_URL=http://localhost:8000 ./run-fixtures.sh
   ```

4. Inspect baseline_run.json, then create expected.json with target behavior

5. Add row to Scenarios table above

## Phase A Status

**Completed:**
- Auto-Canny edge detection with Gaussian blur (5x5) and dilate (2 iterations)
- Contour filtering (4-vertex quads, area > 10% of image, aspect 1.2-3.5)
- `POST /detect-edges` endpoint returning corners, bbox, confidence, method
- 10-fixture suite with seed photos from receipts-web
- Baseline capture for all 10 scenarios

**Current Results (Phase A):**
- 10/10 fixtures captured baselines
- 0/10 found valid quadrilaterals (expected for Phase A)
- Edge detection working; contour filtering too strict OR images lack strong edges

**Next Steps (Phase C/D):**
- Evaluate why no quadrilaterals found (likely need lower area thresholds or better edge detection tuning)
- Implement adaptive-threshold fallback (currently only Canny)
- Tune Canny thresholds (currently hardcoded 75/200)
- Add expected.json targets for each scenario
- Verify existing `/detect` and `/correct` endpoints unchanged (13/13 e2e)

## Pre-Push Hook Integration

Once Phase A complete, receipts-web will run:

```bash
ssh david@192.168.1.11 "/home/david/polycr-fixtures/run-fixtures.sh" && echo "Fixtures PASS"
```

This ensures that changes to polycr don't break the fixture suite baseline.

## References

- Main router: `/home/david/polycr-src-router/main.py`
- Edge detection helper: `detect_document_edges()` function (line 246)
- Auto-Canny function: `_auto_canny()` (Phase B candidate)
- Contour ordering: `_order_corners()` function (line 321)

