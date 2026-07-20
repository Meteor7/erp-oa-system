from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from invoice_ocr.documents import DocumentError
from invoice_ocr.pipeline import recognize_document


class ExplodingEngine:
    def recognize(self, _image_path: Path):
        raise RuntimeError("backend inference failed")


def test_pipeline_preserves_backend_failure_as_stable_non_document_error(tmp_path: Path):
    stream = BytesIO()
    Image.new("RGB", (16, 12), "white").save(stream, format="PNG")
    source = tmp_path / "invoice.png"
    source.write_bytes(stream.getvalue())

    with pytest.raises(Exception) as captured:
        recognize_document(source, tmp_path / "work", ExplodingEngine())

    assert type(captured.value).__name__ == "OCRBackendError"
    assert not isinstance(captured.value, DocumentError)
    assert captured.value.__cause__ is not None
