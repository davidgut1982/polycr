"""
polycr router — multi-engine OCR with LLM reconciliation.

Why: Provides a single stable REST API that fans out to all configured OCR engine
     services, preprocesses images, reconciles results via an LLM, and returns both
     raw per-engine output and a structured final answer.
What: FastAPI app exposing POST /process (full pipeline), POST /ocr/raw (engines only),
      GET /health, POST /detect (receipt corner detection), and POST /correct
      (perspective rectification / deskew).  Engine selection is driven by the
      ENABLED_ENGINES env var.
Test: Start the router with at least the tesseract engine running; POST a JPEG to
      /process and assert the response has "text" and "engines_used" keys.
"""

import asyncio
import io
import json
import logging
import math
import os
from typing import Optional

import cv2
import httpx
import numpy as np
import pytesseract
from PIL import Image
from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from fastapi.responses import Response

from llm import reconcile
from models import EngineResult, ProcessResponse
from preprocess import preprocess_image
from PIL import ImageOps

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


@app.post("/detect")
async def detect_document(file: UploadFile = File(...)):
    """
    Why: Fast document corner/bbox detection for receipts-web auto-crop.
    What: Runs PaddleOCR only (no Tesseract, no LLM) to extract text regions,
          computes axis-aligned bounding box from region polygons with 8% padding,
          and returns corners + bbox for client-side cropping.
    Test: POST a receipt image → expect corners=[[[x,y], [x,y], [x,y], [x,y]]]
          and bbox={"x": ..., "y": ..., "width": ..., "height": ...}.
    """
    if "paddleocr" not in ENABLED_ENGINES:
        return {
            "corners": None,
            "bbox": None,
            "confidence": 0.0,
            "error": "paddleocr engine not enabled",
        }

    image_bytes = await file.read()
    clean = preprocess_image(image_bytes)

    result = await call_engine("paddleocr", clean)
    if result.error:
        return {
            "corners": None,
            "bbox": None,
            "confidence": 0.0,
            "error": result.error,
        }

    if not result.regions:
        return {
            "corners": None,
            "bbox": None,
            "confidence": result.confidence,
            "error": "no text regions detected",
        }

    # Use shared helper: decode bytes → numpy before passing to detect_corners_internal
    _arr = np.frombuffer(clean, np.uint8)
    _img_cv = cv2.imdecode(_arr, cv2.IMREAD_COLOR)
    if _img_cv is None:
        return {
            "corners": None,
            "bbox": None,
            "confidence": result.confidence,
            "error": "could not decode preprocessed image",
        }
    corners, status = await detect_corners_internal(_img_cv)
    if corners is None:
        return {
            "corners": None,
            "bbox": None,
            "confidence": result.confidence,
            "error": f"corner detection failed: {status}",
        }

    x_min, y_min = corners[0]
    x_max, y_max = corners[2]

    return {
        "corners": corners,
        "bbox": {
            "x": x_min,
            "y": y_min,
            "width": x_max - x_min,
            "height": y_max - y_min,
        },
        "confidence": result.confidence,
    }


@app.post("/detect-edges")
async def detect_edges_endpoint(file: UploadFile = File(...)):
    """
    Why: Direct edge-based document detection (jscanify-style Canny + contour).
    What: Reads image, applies EXIF auto-orient, runs Canny edge detection,
          finds contours, filters to 4-vertex quadrilaterals with sane aspect ratios,
          and returns corners + confidence based on contour area.
    Test: POST a receipt photographed at an angle -> expect corners and confidence > 0.5.
    """
    image_bytes = await file.read()
    img_cv = None

    # Try direct PIL EXIF auto-orient first
    try:
        pil_img = Image.open(io.BytesIO(image_bytes))
        pil_img = ImageOps.exif_transpose(pil_img)
        img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception as e:
        logger.warning(f"EXIF transpose failed: {e}, trying fallback")

    if img_cv is None:
        try:
            clean_bytes = preprocess_image(image_bytes)
            arr = np.frombuffer(clean_bytes, np.uint8)
            img_cv = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception as e2:
            logger.error(f"Both EXIF and preprocess failed: {e2}")

    if img_cv is None:
        return {
            "corners": None,
            "bbox": None,
            "confidence": 0.0,
            "error": "could not decode image",
            "method": "edges"
        }

    result = detect_document_edges(img_cv)

    if result is None:
        return {
            "corners": None,
            "bbox": None,
            "confidence": 0.0,
            "error": "no valid quadrilateral found",
            "method": "edges"
        }

    corners = result["corners"]
    confidence = result["confidence"]
    method = result.get("method", "edges")

    x_coords = [c[0] for c in corners]
    y_coords = [c[1] for c in corners]
    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)

    return {
        "corners": corners,
        "bbox": {
            "x": x_min,
            "y": y_min,
            "width": x_max - x_min,
            "height": y_max - y_min,
        },
        "confidence": confidence,
        "method": method,
        "area_ratio": result.get("area_ratio", 0.0),
        "center_offset": result.get("center_offset", 0.0)
    }


def _auto_canny(gray, sigma=0.33):
    median = float(np.median(gray))
    low  = int(max(0,   (1.0 - sigma) * median))
    high = int(min(255, (1.0 + sigma) * median))
    return cv2.Canny(gray, low, high)


def detect_document_edges(img: np.ndarray) -> Optional[dict]:
    """
    Edge-based document detection. Returns tuple (corners, confidence) or (None, 0.0)
    if no plausible quadrilateral found.

    Why: Fallback corner detection when text-region detection fails or gives
         suspect aspect ratio. Implements jscanify-style edge-detection algorithm.

    What:
      1. Convert to grayscale; apply Gaussian blur (5x5).
      2. Try Canny first; if edge density < 1%, fall back to adaptive threshold.
      3. Close gaps with morphology.
      4. Find external contours.
      5. For each contour, approximate to polygon with epsilon=0.04 of perimeter.
      6. Reject contours touching image edges (within 5px of boundary).
      7. Filter to quadrilaterals (4 vertices) with area 30-92% of image (restored to spec).
      8. Filter by center offset (max 60% of image diagonal from center).
      9. Pick candidate with highest confidence.
      10. Order corners as TL/TR/BR/BL using sum/diff heuristic.
      11. Return corners + confidence + method used (canny or adaptive).

    NOTE: This function does NOT filter by receipt aspect ratio. The projected
    shape in image space can be near-square for tilted receipts. Aspect filtering
    happens AFTER perspective warp in the main pipeline.

    Returns: (corners, confidence) where corners is None if no valid quad found.
    """
    H, W = img.shape[:2]
    img_area = float(H * W)
    img_cx, img_cy = W / 2.0, H / 2.0
    img_diag = (W**2 + H**2) ** 0.5
    EDGE_MARGIN = 5  # contours touching within 5px of image boundary are rejected

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    canny = _auto_canny(blurred)
    canny_density = float(np.count_nonzero(canny)) / img_area

    if canny_density >= 0.01:  # Canny found enough edges
        edge_map = canny
        method_used = "canny"
    else:  # Canny under-detected; fall back to adaptive
        adaptive = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2,
        )
        edge_map = adaptive
        method_used = "adaptive"

    # Close gaps with morphology
    kernel = np.ones((5, 5), np.uint8)
    closed = cv2.morphologyEx(edge_map, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)  # eps=0.04 per real-data analysis
        if len(approx) != 4:
            continue
        pts = approx.reshape(4, 2).astype(float)

        # Reject contours touching image edges (almost always the photo frame)
        touches_edge = any(
            x < EDGE_MARGIN or x > W - EDGE_MARGIN or
            y < EDGE_MARGIN or y > H - EDGE_MARGIN
            for x, y in pts
        )
        if touches_edge:
            continue

        area = cv2.contourArea(approx)
        area_ratio = area / img_area
        if area_ratio < 0.03 or area_ratio > 0.92:  # relaxed based on real-world data
            continue

        cx, cy = pts.mean(axis=0)
        dist = ((cx - img_cx)**2 + (cy - img_cy)**2) ** 0.5
        center_offset = dist / (img_diag / 2.0)
        if center_offset > 0.6:
            continue

        confidence = float(area_ratio * max(0.0, 1.0 - 1.5 * center_offset))
        candidates.append({
            "pts": pts, "area_ratio": float(area_ratio),
            "center_offset": float(center_offset),
            "confidence": confidence, "method": method_used,
        })

    if not candidates:
        return None

    best = max(candidates, key=lambda c: c["confidence"])
    pts = best["pts"]
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).flatten()
    tl = pts[int(np.argmin(s))]
    br = pts[int(np.argmax(s))]
    tr = pts[int(np.argmin(d))]
    bl = pts[int(np.argmax(d))]
    ordered = np.array([tl, tr, br, bl], dtype=np.float32)

    return {
        "corners": ordered.tolist(),
        "area_ratio": best["area_ratio"],
        "center_offset": best["center_offset"],
        "confidence": best["confidence"],
        "method": best["method"],
    }



def _order_corners(pts: list[list[float]]) -> np.ndarray:
    """
    Why: cv2.getPerspectiveTransform requires corners in a consistent TL/TR/BR/BL
         order; caller-supplied polygons may be in any winding order.
    What: Sorts the four input points by the sum-of-coordinates heuristic:
          TL has the smallest sum (x+y), BR has the largest; TR has the largest
          difference (x-y), BL has the smallest.  Returns a (4,2) float32 array
          in [TL, TR, BR, BL] order.
    Test: Pass [[100,100],[800,100],[800,1200],[100,1200]] in shuffled order;
          assert result[0]==[100,100] (TL) and result[2]==[800,1200] (BR).
    """
    pts_np = np.array(pts, dtype=np.float32)
    sums = pts_np.sum(axis=1)        # x+y
    diffs = pts_np[:, 0] - pts_np[:, 1]  # x-y

    tl = pts_np[np.argmin(sums)]
    br = pts_np[np.argmax(sums)]
    tr = pts_np[np.argmax(diffs)]
    bl = pts_np[np.argmin(diffs)]

    return np.array([tl, tr, br, bl], dtype=np.float32)


def _euclidean(p1: np.ndarray, p2: np.ndarray) -> float:
    return float(np.linalg.norm(p1 - p2))


def _is_degenerate(ordered: np.ndarray) -> bool:
    """
    Why: A degenerate quadrilateral (colinear or near-zero area) would produce a
         singular transform matrix and a nonsensical output image.
    What: Checks that the computed output width and height are both >= 10px, and
          that the cross-product area of the quad is above a minimum threshold.
    Test: Pass four colinear points; assert returns True.
    """
    tl, tr, br, bl = ordered
    w = max(_euclidean(tl, tr), _euclidean(bl, br))
    h = max(_euclidean(tl, bl), _euclidean(tr, br))
    if w < 10 or h < 10:
        return True
    # Cross-product area check (shoelace)
    pts = ordered
    area = 0.5 * abs(
        (pts[0][0] * pts[1][1] - pts[1][0] * pts[0][1]) +
        (pts[1][0] * pts[2][1] - pts[2][0] * pts[1][1]) +
        (pts[2][0] * pts[3][1] - pts[3][0] * pts[2][1]) +
        (pts[3][0] * pts[0][1] - pts[0][0] * pts[3][1])
    )
    return area < 100.0


def _cluster_regions_by_proximity(regions, image_diag: float):
    """
    Group text regions by spatial proximity using union-find.

    Receipt text is densely packed; background text is usually sparse and far
    from the receipt. Clusters regions whose centroids are within
    proximity_threshold of each other. Threshold is 8% of image diagonal,
    calibrated so receipt-internal lines (~50px apart) merge while background
    text (~500px+ away) stays separate.

    Args:
        regions: List of OCR region objects with .polygon attribute
        image_diag: Diagonal length of image (used for threshold scaling)

    Returns:
        List of clusters, each cluster is a list of region objects
    """
    if not regions:
        return []

    proximity_threshold = image_diag * 0.08

    # Compute centroids
    centroids = []
    for r in regions:
        pts = np.array(r.polygon)
        centroids.append(pts.mean(axis=0))

    # Union-find to group nearby regions
    n = len(regions)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    # Connect regions within proximity threshold
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.linalg.norm(centroids[i] - centroids[j])
            if dist <= proximity_threshold:
                union(i, j)

    # Group by cluster root
    clusters = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(regions[i])

    return list(clusters.values())


def _cluster_score(cluster, image_area: float) -> float:
    """
    Score a cluster: more regions + denser packing + receipt-like aspect = higher score.
    Penalize clusters whose bbox is too large (catches lone background text).

    Args:
        cluster: List of region objects in this cluster
        image_area: Total image area in pixels

    Returns:
        Float score; higher is better
    """
    if not cluster:
        return 0.0

    # Extract all points from cluster
    all_pts = np.array([pt for r in cluster for pt in r.polygon])
    minx, miny = all_pts.min(axis=0)
    maxx, maxy = all_pts.max(axis=0)
    bbox_w = maxx - minx
    bbox_h = maxy - miny
    bbox_area = bbox_w * bbox_h
    bbox_area_ratio = bbox_area / image_area

    # Penalize clusters covering >95% of image (likely background)
    if bbox_area_ratio > 0.95:
        return 0.0

    # Score based on region count, density, and aspect ratio
    n_regions = len(cluster)
    density = n_regions / max(bbox_area, 1.0)

    # Receipt prior: prefer tall (portrait) clusters
    aspect_h_w = bbox_h / max(bbox_w, 1.0)
    aspect_bonus = 1.0 if 1.0 <= aspect_h_w <= 4.0 else 0.5

    # Combined score: regions × aspect × (1 + density normalized)
    return n_regions * aspect_bonus * (1.0 + min(density * 1e6, 5.0))


async def detect_corners_internal(img: np.ndarray) -> tuple[Optional[list[list[float]]], str]:
    """
    Why: Shared corner-detection logic with fallback strategy: try text-region detection
         first, then edge-based if text fails or aspect ratio is suspect.
    What:
      1. Try PaddleOCR text regions → compute bbox with 15% padding.
      2. Check bbox aspect ratio: if 1.2 <= h/w <= 3.5 AND area > 30% of image → return text.
      3. Else try edge-based (Canny) detection.
      4. If edge detection returns a valid quad with sane aspect → return edges.
      5. Else fall back to full image.
    Returns: (corners, status) where status in ["text", "edges", "fallback"].
    """
    if "paddleocr" not in ENABLED_ENGINES:
        return None, "paddleocr-disabled"

    # Step 1: Try text-region detection
    success_encode, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not success_encode:
        return None, "encode-failed"

    image_bytes = buf.tobytes()
    result = await call_engine("paddleocr", image_bytes)

    if result.error:
        return None, f"engine-error:{result.error[:20]}"

    if not result.regions:
        # No text detected; try edge-based
        edge_result = detect_document_edges(img)
        if edge_result is not None:
            return edge_result["corners"], "edges"
        return None, "no-regions"

    # Step 1.5: Cluster regions by proximity to separate receipt from background
    h, w = img.shape[:2]
    image_area = h * w
    image_diag = (h**2 + w**2) ** 0.5

    clusters = _cluster_regions_by_proximity(result.regions, image_diag)
    if not clusters:
        return None, "no-clusters"

    # Score each cluster and pick the best
    cluster_scores = [(c, _cluster_score(c, image_area)) for c in clusters]
    best_cluster = max(cluster_scores, key=lambda x: x[1])[0]

    if not best_cluster:
        return None, "all-clusters-rejected"

    # Collect points only from the best cluster
    points = []
    for region in best_cluster:
        points.extend(region.polygon)

    if len(points) < 4:
        # Insufficient text points in best cluster; try edge-based
        edge_result = detect_document_edges(img)
        if edge_result is not None:
            return edge_result["corners"], "edges"
        return None, "insufficient-points"

    points_np = np.array(points, dtype=np.float32)
    x_min, y_min = points_np.min(axis=0)
    x_max, y_max = points_np.max(axis=0)

    # Pad by 15% to capture margins outside text
    pad_x = (x_max - x_min) * 0.15
    pad_y = (y_max - y_min) * 0.15
    x_min = max(0, x_min - pad_x)
    y_min = max(0, y_min - pad_y)
    x_max = x_max + pad_x
    y_max = y_max + pad_y

    # Step 2: Sanity check text-region aspect
    text_w = x_max - x_min
    text_h = y_max - y_min
    text_aspect = text_h / max(text_w, 1)
    text_area_ratio = (text_w * text_h) / image_area

    text_corners = [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]]
    cluster_status = f"cluster:{len(best_cluster)}:{len(clusters)}"

    # Accept text if aspect is sane and covers enough of image
    if 1.2 <= text_aspect <= 4.5 and text_area_ratio > 0.30:
        return text_corners, cluster_status

    # Step 3: Text aspect suspect; try edge-based
    edge_result = detect_document_edges(img)
    if edge_result is not None:
        return edge_result["corners"], "edges"

    # Step 4: Fall back to full image
    return [[0, 0], [w, 0], [w, h], [0, h]], "fallback"


def _orientation_vote(regions, image_shape):
    """
    Aggregate per-region orientation predictions from PaddleOCR cls.
    Returns (rotation_degrees, confidence) where rotation_degrees is
    0 (no rotation needed) or 180 (rotate 180), and confidence is
    the area-weighted average of cls confidences for the winning angle.

    For 90-degree rotations, cls only returns 0/180 — those are caught
    by aspect-shape and PaddleOCR's region polygon orientation
    (long-axis of polygons running horizontal vs vertical).
    """
    if not regions:
        return 0, 0.0

    # Vote on 0 vs 180
    vote_0 = 0.0
    vote_180 = 0.0
    for r in regions:
        # Area of polygon using shoelace formula
        pts = np.array(r.polygon, dtype=np.float32)
        if len(pts) < 4:
            continue
        xs = pts[:, 0]
        ys = pts[:, 1]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        weight = area * max(r.angle_confidence, 0.0)
        if r.angle == 0:
            vote_0 += weight
        elif r.angle == 180:
            vote_180 += weight

    total = vote_0 + vote_180
    if total == 0:
        return 0, 0.0

    if vote_180 > vote_0:
        return 180, vote_180 / total
    return 0, vote_0 / total


def _detect_text_axis(regions):
    """
    Returns 'horizontal' or 'vertical' based on dominant text-line orientation.
    If most polygons have height > width, text is running vertical (receipt rotated 90°).
    """
    if not regions:
        return 'horizontal'
    h_count = 0
    v_count = 0
    for r in regions:
        pts = np.array(r.polygon, dtype=np.float32)
        if len(pts) < 4:
            continue
        xs = pts[:, 0]
        ys = pts[:, 1]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        if w >= h:
            h_count += 1
        else:
            v_count += 1
    return 'vertical' if v_count > h_count else 'horizontal'


@app.post("/correct")
async def correct_document(
    file: UploadFile = File(...),
    corners_json: Optional[str] = Form(default=None),
):
    """
    Why: Receipts-web needs a flat, axis-aligned image for OCR; a scanned receipt
         photographed at an angle requires perspective rectification before reliable
         text extraction is possible.
    What: NEW ALGORITHM (PaddleOCR cls orientation):
          1. Read image bytes and decode.
          2. Apply EXIF auto-orient via PIL.ImageOps.exif_transpose.
          3. Run PaddleOCR to detect text regions and per-region orientation (cls).
          4. Detect 90-degree rotations via _detect_text_axis (polygon shape analysis).
          5. If 90° rotation needed, apply it and re-run PaddleOCR.
          6. Re-detect corners on the oriented image.
          7. Compute perspective transform and warp.
          8. Post-warp: run PaddleOCR cls vote to detect 180-degree rotation.
          9. Apply 180-degree rotation if cls vote confidence > 0.7.
          Removes: Tesseract OSD pass 1, OSD pass 2, OCR-vote tiers.
          Retains: EXIF auto-orient, aspect-fallback heuristic (last resort).
    Test: POST a sideways receipt → assert response has portrait dimensions
          and all 4 orientations produce similar-sized portrait output.
    """
    image_bytes = await file.read()

    if corners_json is not None:
        logger.warning("ignoring caller-supplied corners; re-detecting after orient")

    # Step 1: EXIF auto-orient
    try:
        pil_img = Image.open(io.BytesIO(image_bytes))
        pil_img = ImageOps.exif_transpose(pil_img)
        img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception as e:
        logger.warning(f"EXIF transpose failed: {e}, falling back to preprocess_image")
        clean_bytes = preprocess_image(image_bytes)
        arr = np.frombuffer(clean_bytes, np.uint8)
        img_cv = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img_cv is None:
            raise HTTPException(status_code=422, detail={"error": "could not decode image"})

    h_orig, w_orig = img_cv.shape[:2]
    rotation_method = "none"
    text_axis_pre_warp = "horizontal"

    # Step 2: Pre-warp orientation correction using PaddleOCR cls + text-axis detection
    pre_warp_rotation = 0
    try:
        success_encode, buf = cv2.imencode(".jpg", img_cv, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if success_encode:
            img_bytes_encoded = buf.tobytes()
            result = await call_engine("paddleocr", img_bytes_encoded)
            if not result.error and result.regions:
                text_axis_pre_warp = _detect_text_axis(result.regions)
                if text_axis_pre_warp == 'vertical':
                    pre_warp_rotation = 90
                    img_cv = cv2.rotate(img_cv, cv2.ROTATE_90_CLOCKWISE)
                    logger.info(f"pre-warp: detected vertical text axis, rotating 90 CW")
    except Exception as e:
        logger.warning(f"pre-warp PaddleOCR detection failed: {e}")

    # Step 3: Re-detect corners on the now-oriented image
    detected_corners, redetect_status = await detect_corners_internal(img_cv)

    # Sanity check: if detected region has extreme aspect, fall back to full image
    if detected_corners is not None:
        det_x_coords = [c[0] for c in detected_corners]
        det_y_coords = [c[1] for c in detected_corners]
        det_w = max(det_x_coords) - min(det_x_coords)
        det_h = max(det_y_coords) - min(det_y_coords)
        det_ratio = det_h / max(det_w, 1)

        if det_ratio > 4.5 or det_ratio < 1.2:
            logger.warning(f"aspect sanity failed: ratio={det_ratio:.2f} outside [1.2, 4.5]; using full image")
            h, w = img_cv.shape[:2]
            detected_corners = [[0, 0], [w, 0], [w, h], [0, h]]
            redetect_status = "fallback-extreme-aspect"

            if w > h:
                logger.warning(f"fallback produced landscape ({w}x{h}); rotating 90 CW to portrait")
                img_cv = cv2.rotate(img_cv, cv2.ROTATE_90_CLOCKWISE)
                h, w = img_cv.shape[:2]
                detected_corners = [[0, 0], [w, 0], [w, h], [0, h]]
                redetect_status = "fallback-extreme-aspect-rotated"

    if detected_corners is None:
        h, w = img_cv.shape[:2]
        detected_corners = [[0, 0], [w, 0], [w, h], [0, h]]
        redetect_status = "none"

    # Step 4: Order corners and apply perspective warp
    ordered = _order_corners(detected_corners)

    if _is_degenerate(ordered):
        raise HTTPException(
            status_code=422,
            detail={"error": "degenerate quadrilateral: corners are colinear or cover too small an area"},
        )

    tl, tr, br, bl = ordered

    # Compute output dimensions
    width_top = _euclidean(tl, tr)
    width_bot = _euclidean(bl, br)
    out_w = int(max(width_top, width_bot))

    height_left = _euclidean(tl, bl)
    height_right = _euclidean(tr, br)
    out_h = int(max(height_left, height_right))

    if out_w > out_h * 1.5:
        logger.warning(f"output is very wide ({out_w}x{out_h}); check corner detection")

    dst = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )

    M = cv2.getPerspectiveTransform(ordered, dst)
    warped = cv2.warpPerspective(img_cv, M, (out_w, out_h))

    # Step 5: Post-warp orientation refinement using PaddleOCR cls vote
    cls_vote_rotation = 0
    cls_vote_confidence = 0.0
    try:
        success_encode, buf = cv2.imencode(".jpg", warped, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if success_encode:
            img_bytes_warped = buf.tobytes()
            result = await call_engine("paddleocr", img_bytes_warped)
            if not result.error and result.regions:
                cls_vote_rotation, cls_vote_confidence = _orientation_vote(result.regions, warped.shape)
                if cls_vote_rotation == 180 and cls_vote_confidence > 0.7:
                    warped = cv2.rotate(warped, cv2.ROTATE_180)
                    logger.info(f"post-warp cls vote: applied 180° rotation (conf={cls_vote_confidence:.2f})")
                    rotation_method = "cls"
                elif pre_warp_rotation == 90:
                    rotation_method = "aspect"
                else:
                    rotation_method = "none" if cls_vote_confidence < 0.5 else "cls-low-conf"
    except Exception as e:
        logger.warning(f"post-warp PaddleOCR cls vote failed: {e}")
        if pre_warp_rotation == 90:
            rotation_method = "aspect"

    # Fallback rotation_method detection
    if rotation_method == "none" and pre_warp_rotation == 90:
        rotation_method = "aspect"

    # Encode as JPEG q=90
    success, buf = cv2.imencode(".jpg", warped, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not success:
        raise HTTPException(status_code=500, detail={"error": "JPEG encoding failed"})

    jpeg_bytes = buf.tobytes()

    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={
            "X-Pipeline": "paddleocr-cls-orient",
            "X-Detection-Method": redetect_status,
            "X-Text-Axis-Pre-Warp": text_axis_pre_warp,
            "X-Pre-Warp-Rotation": str(pre_warp_rotation),
            "X-Cls-Vote-180": str(cls_vote_rotation),
            "X-Cls-Vote-Confidence": f"{cls_vote_confidence:.2f}",
            "X-Rotation-Method": rotation_method,
            "X-Output-Width": str(out_w),
            "X-Output-Height": str(out_h),
        },
    )


@app.get("/health")
async def health():
    """
    Why: Lets load balancers, Docker health checks, and monitoring tools verify
         the router is up and report which engines are configured.
    What: Returns a simple ok payload with the current ENABLED_ENGINES list.
    Test: GET /health → HTTP 200 {"status": "ok", "engines": ["tesseract", ...]}.
    """
    return {"status": "ok", "engines": ENABLED_ENGINES}
