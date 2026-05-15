from pathlib import Path

EXPECTED_MODELS = [
    "PP-LCNet_x1_0_doc_ori",
    "UVDoc",
    "PP-OCRv5_server_det",
    "PP-LCNet_x1_0_textline_ori",
    "en_PP-OCRv5_mobile_rec",
]

model_dir = Path("/root/.paddlex/official_models")
missing = [m for m in EXPECTED_MODELS if not (model_dir / m).is_dir()]
assert not missing, f"Missing model dirs: {missing}"
present = [m for m in EXPECTED_MODELS if (model_dir / m).is_dir()]
print(f"[verify] OK — {len(present)}/{len(EXPECTED_MODELS)} model dirs present: {present}")
