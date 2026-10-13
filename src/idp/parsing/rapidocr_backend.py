"""The same OCR models as ``PaddleOCRBackend`` — PP-OCRv5 server detection
and latin mobile recognition — run on ONNX Runtime through RapidOCR (VRT-70).

Measured on the same 9 pages: 1.1 s per page instead of 13.9 on this
machine's CPU, with 470 of 507 lines identical to Paddle's reading (the rest
mostly noise Paddle reads and this does not) and boxes a median 1 px apart.
That holds only with our own conversion of Paddle's models
(scripts/export_ocr_onnx.sh) and Paddle's detection settings: RapidOCR's
published files and defaults read measurably worse, and cost 14 points of
extraction accuracy. No text-line orientation step, as in Paddle without it
(505 of 507 lines unchanged). Layout regions stay with PaddleOCRBackend's
detector, which this extends.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from rapidocr import RapidOCR
from rapidocr.utils.typings import LangDet, LangRec, ModelType, OCRVersion

from idp.config import Settings
from idp.parsing.paddleocr_backend import PaddleOCRBackend

DET_MODEL = "PP-OCRv5_server_det.onnx"
REC_MODEL = "latin_PP-OCRv5_mobile_rec.onnx"
REC_KEYS = "latin_PP-OCRv5_mobile_rec.keys.txt"

# PaddleOCR's detection settings for this model (paddlex OCR pipeline), not RapidOCR's defaults.
_PADDLE_DETECTION = {
    "Det.limit_side_len": 64, "Det.limit_type": "min", "Det.thresh": 0.3, "Det.box_thresh": 0.6, "Det.unclip_ratio": 1.5,
    "Det.use_dilation": False, "Det.mean": [0.485, 0.456, 0.406], "Det.std": [0.229, 0.224, 0.225], "Global.max_side_len": 4000,
}


class RapidOCRBackend(PaddleOCRBackend):
    name = "rapidocr"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._models = Path(settings.ocr_onnx_dir).expanduser()
        self._rapid: RapidOCR | None = None

    def _engine(self) -> RapidOCR:
        if self._rapid is None:
            missing = [f for f in (DET_MODEL, REC_MODEL, REC_KEYS) if not (self._models / f).is_file()]
            if missing:
                raise RuntimeError(f"faltan los modelos ONNX del OCR en {self._models} ({', '.join(missing)}): corre scripts/export_ocr_onnx.sh")
            self._rapid = RapidOCR(
                params={
                    "Global.log_level": "warning", "Global.use_cls": False,
                    "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.SERVER, "Det.lang_type": LangDet.CH,
                    "Det.model_path": str(self._models / DET_MODEL),
                    "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE, "Rec.lang_type": LangRec.LATIN,
                    "Rec.model_path": str(self._models / REC_MODEL), "Rec.rec_keys_path": str(self._models / REC_KEYS),
                    **_PADDLE_DETECTION,
                }
            )
        return self._rapid

    def _read_lines(self, image_array: np.ndarray) -> list[tuple[str, float, Any]]:
        result: Any = self._engine()(image_array)  # the full pipeline's output: boxes, txts, scores
        if result.boxes is None:  # a page without text
            return []
        return list(zip(result.txts, result.scores, result.boxes))
