import paddleocr
from pathlib import Path

print("[build] Pre-downloading PaddleOCR models (lang=en)...")
# PaddleOCR 3.5.0: use_angle_cls and show_log are removed;
# use_textline_orientation replaces use_angle_cls.
ocr = paddleocr.PaddleOCR(lang="en", use_textline_orientation=True)
print("[build] PaddleOCR models downloaded successfully")

model_dir = Path("/root/.paddlex/official_models")
if model_dir.exists():
    models = [m for m in model_dir.iterdir() if m.is_dir()]
    print(f"[build] Cached {len(models)} model dir(s): {[m.name for m in models]}")
