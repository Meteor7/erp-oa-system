from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from invoice_ocr.models import OCRLine


class OCRBackendError(RuntimeError):
    """Stable boundary for local OCR initialization or inference failures."""


class OCREngine(Protocol):
    def recognize(self, image_path: Path) -> list[OCRLine]: ...


def _payload(result: Any) -> dict[str, Any]:
    value = getattr(result, "json", result)
    if callable(value):
        value = value()
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        return {}
    nested = value.get("res")
    return nested if isinstance(nested, dict) else value


def _box(value: Any) -> tuple[int, int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) == 4 and all(isinstance(item, (int, float)) for item in value):
        return tuple(int(item) for item in value)
    if isinstance(value, (list, tuple)) and value:
        points = [point for point in value if isinstance(point, (list, tuple)) and len(point) >= 2]
        if points:
            xs = [int(point[0]) for point in points]
            ys = [int(point[1]) for point in points]
            return min(xs), min(ys), max(xs), max(ys)
    return 0, 0, 0, 0


def prediction_to_lines(predictions: Any) -> list[OCRLine]:
    lines: list[OCRLine] = []
    for prediction in predictions or []:
        payload = _payload(prediction)
        texts = payload.get("rec_texts") or []
        scores = payload.get("rec_scores") or []
        boxes = payload.get("rec_boxes") or payload.get("rec_polys") or []
        for index, raw_text in enumerate(texts):
            text = str(raw_text).strip()
            if not text:
                continue
            score = float(scores[index]) if index < len(scores) else 0.0
            box = _box(boxes[index]) if index < len(boxes) else (0, index * 20, 0, index * 20 + 18)
            lines.append(OCRLine(text=text, score=max(0.0, min(score, 1.0)), box=box))
    return lines


def text_to_lines(text: str) -> list[OCRLine]:
    lines: list[OCRLine] = []
    for index, value in enumerate(text.splitlines()):
        value = value.strip()
        if value:
            lines.append(OCRLine(text=value, score=0.99, box=(0, index * 20, 0, index * 20 + 18)))
    return lines


class PaddleOCREngine:
    def __init__(self) -> None:
        from paddleocr import PaddleOCR

        self._engine = PaddleOCR(
            lang="ch",
            device="cpu",
            enable_mkldnn=False,
            use_doc_orientation_classify=True,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )

    def recognize(self, image_path: Path) -> list[OCRLine]:
        return prediction_to_lines(self._engine.predict(str(image_path)))
