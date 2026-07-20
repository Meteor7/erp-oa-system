from invoice_ocr.engine import prediction_to_lines, text_to_lines


class FakeResult:
    @property
    def json(self):
        return {
            "res": {
                "rec_texts": ["Invoice Number", "00123456", ""],
                "rec_scores": [0.93, 0.98, 0.4],
                "rec_boxes": [[10, 10, 140, 30], [150, 10, 260, 30], [0, 0, 0, 0]],
            }
        }


def test_prediction_to_lines_maps_paddle_result_contract():
    lines = prediction_to_lines([FakeResult()])
    assert [line.text for line in lines] == ["Invoice Number", "00123456"]
    assert lines[1].score == 0.98
    assert lines[1].box == (150, 10, 260, 30)


def test_text_to_lines_preserves_non_empty_embedded_pdf_lines():
    lines = text_to_lines("Invoice Number 00123456\n\nTotal 106.00")
    assert [line.text for line in lines] == ["Invoice Number 00123456", "Total 106.00"]
    assert all(line.score == 0.99 for line in lines)


def test_paddle_engine_disables_incompatible_mkldnn(monkeypatch):
    import sys
    from types import SimpleNamespace
    from invoice_ocr.engine import PaddleOCREngine

    captured = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCR=FakePaddleOCR))
    PaddleOCREngine()
    assert captured["enable_mkldnn"] is False
