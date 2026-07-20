from pathlib import Path

import fitz
from PIL import Image
import pytest

from invoice_ocr.documents import DocumentError, file_sha256, prepare_document, validate_source


def test_validate_source_rejects_extension_magic_mismatch(tmp_path: Path):
    source = tmp_path / "fake.png"
    source.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(DocumentError, match="header"):
        validate_source(source)


def test_prepare_pdf_extracts_text_and_renders_page(tmp_path: Path):
    source = tmp_path / "invoice.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 100), "Invoice Number 00123456 Date 2026-07-14 Total 106.00")
    pdf.save(source)
    pdf.close()

    prepared = prepare_document(source, tmp_path / "rendered")

    assert prepared.source_sha256 == file_sha256(source)
    assert prepared.use_embedded_text is True
    assert "00123456" in prepared.embedded_text
    assert len(prepared.page_images) == 1
    assert prepared.page_images[0].suffix == ".png"
    assert prepared.page_images[0].exists()


def test_prepare_image_normalizes_to_png(tmp_path: Path):
    source = tmp_path / "ticket.jpg"
    Image.new("RGB", (80, 40), "white").save(source, format="JPEG")

    prepared = prepare_document(source, tmp_path / "rendered")

    assert prepared.use_embedded_text is False
    assert len(prepared.page_images) == 1
    with Image.open(prepared.page_images[0]) as image:
        assert image.mode == "RGB"
        assert image.size == (80, 40)
