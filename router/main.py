"""
polycr router — multi-engine OCR with LLM reconciliation.
"""

import asyncio
import io
import logging
import os
from typing import Optional

import cv2
import httpx
import numpy as np
from PIL import Image
from fastapi import FastAPI, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from docaligner import DocAligner

from llm import reconcile
from models import EngineResult, ProcessResponse
from preprocess import preprocess_image
from PIL import ImageOps

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENABLED_ENGINES = os.getenv("ENABLED_ENGINES", "tesseract,easyocr,doctr").split(",")

_docaligner = None

def _get_docaligner():
    global _docaligner
    if _docaligner is None:
        _docaligner = DocAligner()
    return _docaligner

app = FastAPI(
    title="polycr",
    description="Multi-engine OCR with LLM reconciliation",
    version="0.1.0",
)


async def call_engine(name: str, image_bytes: bytes, language: str = "eng") -> EngineResult:
    url = f"http://{name}:8000/ocr"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                files={"file": ("image.jpg", image_bytes, "image/jpeg")},
                params={"language": language},
            )
            data = response.json()
            return EngineResult(**data)
    except Exception as exc:
        logger.warning("Engine %s failed: %s", name, exc)
        return EngineResult(engine=name, error=str(exc))


@app.post("/process", response_model=ProcessResponse)
async def process(file: UploadFile = File(...)):
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
async def ocr_raw(
    file: UploadFile = File(...),
    language: str = Query(default="eng"),
):
    image_bytes = await file.read()
    clean = preprocess_image(image_bytes)
    results = await asyncio.gather(*[call_engine(e.strip(), clean, language) for e in ENABLED_ENGINES])
    return {"results": [r.dict() for r in results]}


@app.post("/detect")
async def detect_document(file: UploadFile = File(...)):
    if "paddleocr" not in ENABLED_ENGINES:
        return {"corners": None, "bbox": None, "confidence": 0.0, "error": "paddleocr engine not enabled"}

    image_bytes = await file.read()
    clean = preprocess_image(image_bytes)

    result = await call_engine("paddleocr", clean)
    if result.error:
        return {"corners": None, "bbox": None, "confidence": 0.0, "error": result.error}

    if not result.regions:
        return {"corners": None, "bbox": None, "confidence": result.confidence, "error": "no text regions detected"}

    _arr = np.frombuffer(clean, np.uint8)
    _img_cv = cv2.imdecode(_arr, cv2.IMREAD_COLOR)
    if _img_cv is None:
        return {"corners": None, "bbox": None, "confidence": result.confidence, "error": "could not decode preprocessed image"}

    corners, status = await detect_corners_internal(_img_cv)
    if corners is None:
        return {"corners": None, "bbox": None, "confidence": result.confidence, "error": f"corner detection failed: {status}"}

    x_min, y_min = corners[0]
    x_max, y_max = corners[2]

    return {
        "corners": corners,
        "bbox": {"x": x_min, "y": y_min, "width": x_max - x_min, "height": y_max - y_min},
        "confidence": result.confidence,
    }


def _auto_canny(gray, sigma=0.33):
    median = float(np.median(gray))
    low  = int(max(0,   (1.0 - sigma) * median))
    high = int(min(255, (1.0 + sigma) * median))
    return cv2.Canny(gray, low, high)


def detect_document_edges(img: np.ndarray) -> Optional[dict]:
    """Edge-based document detection (fallback only)."""
    H, W = img.shape[:2]
    img_area = float(H * W)
    img_cx, img_cy = W / 2.0, H / 2.0
    img_diag = (W**2 + H**2) ** 0.5
    EDGE_MARGIN = 5

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    canny = _auto_canny(blurred)
    canny_density = float(np.count_nonzero(canny)) / img_area

    if canny_density >= 0.01:
        edge_map = canny
        method_used = "canny"
    else:
        adaptive = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2,
        )
        edge_map = adaptive
        method_used = "adaptive"

    kernel = np.ones((5, 5), np.uint8)
    closed = cv2.morphologyEx(edge_map, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)
        if len(approx) != 4:
            continue
        pts = approx.reshape(4, 2).astype(float)

        touches_edge = any(
            x < EDGE_MARGIN or x > W - EDGE_MARGIN or
            y < EDGE_MARGIN or y > H - EDGE_MARGIN
            for x, y in pts
        )
        if touches_edge:
            continue

        area = cv2.contourArea(approx)
        area_ratio = area / img_area
        if area_ratio < 0.03 or area_ratio > 0.92:
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
    pts_np = np.array(pts, dtype=np.float32)
    sums = pts_np.sum(axis=1)
    diffs = pts_np[:, 0] - pts_np[:, 1]
    tl = pts_np[np.argmin(sums)]
    br = pts_np[np.argmax(sums)]
    tr = pts_np[np.argmax(diffs)]
    bl = pts_np[np.argmin(diffs)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def _euclidean(p1: np.ndarray, p2: np.ndarray) -> float:
    return float(np.linalg.norm(p1 - p2))


def _is_degenerate(ordered: np.ndarray) -> bool:
    tl, tr, br, bl = ordered
    w = max(_euclidean(tl, tr), _euclidean(bl, br))
    h = max(_euclidean(tl, bl), _euclidean(tr, br))
    if w < 10 or h < 10:
        return True
    pts = ordered
    area = 0.5 * abs(
        (pts[0][0] * pts[1][1] - pts[1][0] * pts[0][1]) +
        (pts[1][0] * pts[2][1] - pts[2][0] * pts[1][1]) +
        (pts[2][0] * pts[3][1] - pts[3][0] * pts[2][1]) +
        (pts[3][0] * pts[0][1] - pts[0][0] * pts[3][1])
    )
    return area < 100.0


def _cluster_regions_by_proximity(regions, image_diag: float):
    if not regions:
        return []
    proximity_threshold = image_diag * 0.08
    centroids = []
    for r in regions:
        pts = np.array(r.polygon)
        centroids.append(pts.mean(axis=0))
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

    for i in range(n):
        for j in range(i + 1, n):
            dist = np.linalg.norm(centroids[i] - centroids[j])
            if dist <= proximity_threshold:
                union(i, j)

    clusters = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(regions[i])

    return list(clusters.values())


def _cluster_score(cluster, image_area: float) -> float:
    if not cluster:
        return 0.0
    all_pts = np.array([pt for r in cluster for pt in r.polygon])
    minx, miny = all_pts.min(axis=0)
    maxx, maxy = all_pts.max(axis=0)
    bbox_w = maxx - minx
    bbox_h = maxy - miny
    bbox_area = bbox_w * bbox_h
    bbox_area_ratio = bbox_area / image_area
    if bbox_area_ratio > 0.95:
        return 0.0
    n_regions = len(cluster)
    density = n_regions / max(bbox_area, 1.0)
    aspect_h_w = bbox_h / max(bbox_w, 1.0)
    aspect_bonus = 1.0 if 1.0 <= aspect_h_w <= 4.0 else 0.5
    return n_regions * aspect_bonus * (1.0 + min(density * 1e6, 5.0))


def _infer_4_corners_from_2_diagonal(corners: list[list[float]]) -> Optional[list[list[float]]]:
    if len(corners) != 2:
        return None
    p1, p2 = corners[0], corners[1]
    if p1[0] + p1[1] < p2[0] + p2[1]:
        tl, br = p1, p2
    else:
        tl, br = p2, p1
    return [tl, [br[0], tl[1]], br, [tl[0], br[1]]]


def _infer_4_corners_from_3_parallelogram(corners: list[list[float]]) -> Optional[list[list[float]]]:
    if len(corners) != 3:
        return None
    a, b, c = corners[0], corners[1], corners[2]
    d = [a[0] + c[0] - b[0], a[1] + c[1] - b[1]]
    return [a, b, c, d]


def _validate_quadrilateral_aspect(corners: list[list[float]], min_aspect: float = 0.3, max_aspect: float = 4.0) -> bool:
    if len(corners) != 4:
        return False
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    if w < 10 or h < 10:
        return False
    aspect = h / w if w > 0 else float('inf')
    return min_aspect <= aspect <= max_aspect


def detect_corners_docaligner(img: np.ndarray) -> Optional[list[list[float]]]:
    try:
        aligner = _get_docaligner()
        result = aligner(img)
        h, w = img.shape[:2]
        if result is None or len(result) == 0:
            return None
        corners = result.tolist()
        if len(corners) == 4:
            valid = all(0 <= c[0] <= w and 0 <= c[1] <= h for c in corners)
            return corners if valid else None
        if len(corners) == 2:
            inferred = _infer_4_corners_from_2_diagonal(corners)
            if inferred and _validate_quadrilateral_aspect(inferred):
                valid = all(0 <= c[0] <= w and 0 <= c[1] <= h for c in inferred)
                if valid:
                    return inferred
            return None
        if len(corners) == 3:
            inferred = _infer_4_corners_from_3_parallelogram(corners)
            if inferred and _validate_quadrilateral_aspect(inferred):
                valid = all(0 <= c[0] <= w and 0 <= c[1] <= h for c in inferred)
                if valid:
                    return inferred
            return None
        return None
    except Exception as e:
        logger.warning(f"DocAligner detection failed: {e}")
        return None


async def detect_corners_internal(img: np.ndarray) -> tuple[Optional[list[list[float]]], str]:
    h, w = img.shape[:2]
    image_area = h * w
    image_diag = (h**2 + w**2) ** 0.5

    docaligner_corners = detect_corners_docaligner(img)
    if docaligner_corners is not None:
        return docaligner_corners, "docaligner"

    if "paddleocr" not in ENABLED_ENGINES:
        edge_result = detect_document_edges(img)
        if edge_result is not None:
            return edge_result["corners"], "edges"
        return None, "no-detection-methods"

    success_encode, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not success_encode:
        return None, "encode-failed"

    image_bytes = buf.tobytes()
    result = await call_engine("paddleocr", image_bytes)

    if result.error:
        edge_result = detect_document_edges(img)
        if edge_result is not None:
            return edge_result["corners"], "edges"
        return None, f"engine-error:{result.error[:20]}"

    if not result.regions:
        edge_result = detect_document_edges(img)
        if edge_result is not None:
            return edge_result["corners"], "edges"
        return None, "no-regions"

    clusters = _cluster_regions_by_proximity(result.regions, image_diag)
    if not clusters:
        edge_result = detect_document_edges(img)
        if edge_result is not None:
            return edge_result["corners"], "edges"
        return None, "no-clusters"

    cluster_scores = [(c, _cluster_score(c, image_area)) for c in clusters]
    best_cluster = max(cluster_scores, key=lambda x: x[1])[0]

    if not best_cluster:
        edge_result = detect_document_edges(img)
        if edge_result is not None:
            return edge_result["corners"], "edges"
        return None, "all-clusters-rejected"

    points = []
    for region in best_cluster:
        points.extend(region.polygon)

    if len(points) < 4:
        edge_result = detect_document_edges(img)
        if edge_result is not None:
            return edge_result["corners"], "edges"
        return None, "insufficient-points"

    points_np = np.array(points, dtype=np.float32)
    x_min, y_min = points_np.min(axis=0)
    x_max, y_max = points_np.max(axis=0)

    pad_x = (x_max - x_min) * 0.15
    pad_y = (y_max - y_min) * 0.15
    x_min = max(0, x_min - pad_x)
    y_min = max(0, y_min - pad_y)
    x_max = x_max + pad_x
    y_max = y_max + pad_y

    text_w = x_max - x_min
    text_h = y_max - y_min
    text_aspect = text_h / max(text_w, 1)
    text_area_ratio = (text_w * text_h) / image_area

    text_corners = [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]]
    cluster_status = f"cluster:{len(best_cluster)}:{len(clusters)}"

    if 1.2 <= text_aspect <= 4.5 and text_area_ratio > 0.30:
        return text_corners, cluster_status

    edge_result = detect_document_edges(img)
    if edge_result is not None:
        return edge_result["corners"], "edges"

    return [[0, 0], [w, 0], [w, h], [0, h]], "fallback"


@app.post("/correct")
async def correct_document(
    file: UploadFile = File(...),
    corners_json: Optional[str] = Form(default=None),
):
    image_bytes = await file.read()

    try:
        pil_img = Image.open(io.BytesIO(image_bytes))
        pil_img = ImageOps.exif_transpose(pil_img)
        img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception as e:
        logger.warning(f"EXIF transpose failed: {e}")
        clean_bytes = preprocess_image(image_bytes)
        arr = np.frombuffer(clean_bytes, np.uint8)
        img_cv = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img_cv is None:
            raise HTTPException(status_code=422, detail={"error": "could not decode image"})

    post_warp_rotation = 0
    is_docaligner = False

    detected_corners, redetect_status = await detect_corners_internal(img_cv)

    if detected_corners is not None:
        det_x_coords = [c[0] for c in detected_corners]
        det_y_coords = [c[1] for c in detected_corners]
        det_w = max(det_x_coords) - min(det_x_coords)
        det_h = max(det_y_coords) - min(det_y_coords)
        det_ratio = det_h / max(det_w, 1)

        is_docaligner = redetect_status and redetect_status.startswith("docaligner")
        if not is_docaligner and (det_ratio > 4.5 or det_ratio < 1.2):
            h, w = img_cv.shape[:2]
            detected_corners = [[0, 0], [w, 0], [w, h], [0, h]]
            redetect_status = "fallback-extreme-aspect"

            if w > h:
                img_cv = cv2.rotate(img_cv, cv2.ROTATE_90_CLOCKWISE)
                h, w = img_cv.shape[:2]
                detected_corners = [[0, 0], [w, 0], [w, h], [0, h]]
                redetect_status = "fallback-extreme-aspect-rotated"
                post_warp_rotation = 90

    if detected_corners is None:
        h, w = img_cv.shape[:2]
        detected_corners = [[0, 0], [w, 0], [w, h], [0, h]]
        redetect_status = "none"

    ordered = _order_corners(detected_corners)

    if _is_degenerate(ordered):
        raise HTTPException(status_code=422, detail={"error": "degenerate quadrilateral"})

    tl, tr, br, bl = ordered

    width_top = _euclidean(tl, tr)
    width_bot = _euclidean(bl, br)
    out_w = int(max(width_top, width_bot))

    height_left = _euclidean(tl, bl)
    height_right = _euclidean(tr, br)
    out_h = int(max(height_left, height_right))

    dst = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )

    M = cv2.getPerspectiveTransform(ordered, dst)
    warped = cv2.warpPerspective(img_cv, M, (out_w, out_h))

    is_docaligner = redetect_status and redetect_status.startswith("docaligner")
    if is_docaligner and out_w > out_h:
        warp_aspect = out_h / max(out_w, 1)
        if warp_aspect < 1.0:
            warped = cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE)
            out_h_new, out_w_new = warped.shape[:2]
            out_w, out_h = out_w_new, out_h_new
            post_warp_rotation = 90
            redetect_status = "docaligner-wide-rotated"

    success, buf = cv2.imencode(".jpg", warped, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not success:
        raise HTTPException(status_code=500, detail={"error": "JPEG encoding failed"})

    jpeg_bytes = buf.tobytes()

    detection_source = "unknown"
    if redetect_status and redetect_status.startswith("docaligner"):
        detection_source = "docaligner"
    elif redetect_status and redetect_status.startswith("cluster"):
        detection_source = "cluster"
    elif redetect_status == "edges":
        detection_source = "edges"
    elif redetect_status and "fallback" in redetect_status:
        detection_source = "fallback"

    headers_dict = {
        "X-Pipeline": "docaligner-primary",
        "X-Detection-Source": detection_source,
        "X-Detection-Method": redetect_status,
        "X-Output-Width": str(out_w),
        "X-Output-Height": str(out_h),
    }
    if post_warp_rotation > 0:
        headers_dict["X-Post-Warp-Rotation"] = str(post_warp_rotation)

    return Response(content=jpeg_bytes, media_type="image/jpeg", headers=headers_dict)


@app.get("/health")
async def health():
    return {"status": "ok", "engines": ENABLED_ENGINES}
