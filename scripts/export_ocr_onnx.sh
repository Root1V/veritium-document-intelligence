#!/usr/bin/env bash
# Converts the PaddleOCR models Veritium reads with (VRT-70) to ONNX, for the
# default "rapidocr" reader: PP-OCRv5 server detection and latin mobile
# recognition, plus the recognizer's character list. Our own conversion, not
# RapidOCR's published files: those read measurably differently from Paddle.
#
#   scripts/export_ocr_onnx.sh [out_dir]      (default: OCR_ONNX_DIR or ~/.veritium/ocr-onnx)
#
# Downloads the Paddle models if they are not there yet. paddle2onnx runs on
# Python 3.12 in a throwaway environment, because it has no build for the
# project's Python.
set -euo pipefail
OUT="${1:-${OCR_ONNX_DIR:-$HOME/.veritium/ocr-onnx}}"
SRC="${PADDLE_MODELS_DIR:-$HOME/.paddlex/official_models}"
mkdir -p "$OUT"
if [ ! -f "$SRC/PP-OCRv5_server_det/inference.json" ] || [ ! -f "$SRC/latin_PP-OCRv5_mobile_rec/inference.json" ]; then
  uv run --no-sync python -c "from paddleocr import TextDetection, TextRecognition; TextDetection(model_name='PP-OCRv5_server_det'); TextRecognition(model_name='latin_PP-OCRv5_mobile_rec')"
fi
for model in PP-OCRv5_server_det latin_PP-OCRv5_mobile_rec; do
  uvx --python 3.12 --with paddlepaddle==3.3.1 --with packaging paddle2onnx \
    --model_dir "$SRC/$model" --model_filename inference.json --params_filename inference.pdiparams \
    --save_file "$OUT/$model.onnx" --opset_version 14 2>&1 | grep -E "saved|Error" || true
done
uv run --no-sync python - "$SRC/latin_PP-OCRv5_mobile_rec/inference.yml" "$OUT/latin_PP-OCRv5_mobile_rec.keys.txt" <<'PY'
import sys, yaml
chars = yaml.safe_load(open(sys.argv[1]))["PostProcess"]["character_dict"]
open(sys.argv[2], "w").write("\n".join(chars) + "\n")
PY
ls -la "$OUT"
