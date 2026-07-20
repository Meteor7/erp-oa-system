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


def test_prepare_pdf_allows_six_pages_by_default(tmp_path: Path):
    source = tmp_path / "six-pages.pdf"
    pdf = fitz.open()
    for _ in range(6):
        pdf.new_page(width=20, height=20)
    pdf.save(source)
    pdf.close()

    prepared = prepare_document(source, tmp_path / "rendered")

    assert len(prepared.page_images) == 6


def test_prepare_pdf_honors_configured_page_limit(tmp_path: Path):
    source = tmp_path / "six-pages.pdf"
    pdf = fitz.open()
    for _ in range(6):
        pdf.new_page(width=20, height=20)
    pdf.save(source)
    pdf.close()

    with pytest.raises(DocumentError, match="configured page limit"):
        prepare_document(source, tmp_path / "rendered", max_pages=5)


def test_prepare_pdf_rejects_page_before_rendering_when_pixel_limit_exceeded(tmp_path: Path):
    source = tmp_path / "large-page.pdf"
    pdf = fitz.open()
    pdf.new_page(width=20, height=20)
    pdf.save(source)
    pdf.close()

    with pytest.raises(DocumentError, match=r"PDF page 1 exceeds pixel limit"):
        prepare_document(source, tmp_path / "rendered", max_page_pixels=100)


def test_prepare_pdf_rejects_cumulative_render_pixels(tmp_path: Path):
    source = tmp_path / "two-pages.pdf"
    pdf = fitz.open()
    for _ in range(2):
        pdf.new_page(width=20, height=20)
    pdf.save(source)
    pdf.close()

    with pytest.raises(DocumentError, match="PDF exceeds document pixel limit"):
        prepare_document(source, tmp_path / "rendered", max_document_pixels=2000)


def test_prepare_pdf_wraps_page_processing_error_as_document_error(tmp_path: Path, monkeypatch):
    source = tmp_path / "broken-page.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    class BrokenPage:
        rect = fitz.Rect(0, 0, 20, 20)

        def get_text(self, _kind):
            raise RuntimeError("text extraction exploded")

    class BrokenDocument:
        page_count = 1
        closed = False

        def __iter__(self):
            return iter([BrokenPage()])

        def close(self):
            self.closed = True

    document = BrokenDocument()
    monkeypatch.setattr("invoice_ocr.documents.fitz.open", lambda _path: document)

    with pytest.raises(DocumentError, match="PDF page 1 could not be processed") as error:
        prepare_document(source, tmp_path / "rendered")

    assert isinstance(error.value.__cause__, RuntimeError)
    assert document.closed is True


def test_prepare_transparent_png_composites_onto_white(tmp_path: Path):
    source = tmp_path / "transparent.png"
    image = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
    image.putpixel((1, 0), (255, 0, 0, 255))
    image.save(source)

    prepared = prepare_document(source, tmp_path / "rendered")

    with Image.open(prepared.page_images[0]) as normalized:
        assert normalized.mode == "RGB"
        assert normalized.getpixel((0, 0)) == (255, 255, 255)
        assert normalized.getpixel((1, 0)) == (255, 0, 0)


def test_validate_source_wraps_decompression_bomb_error(tmp_path: Path, monkeypatch):
    source = tmp_path / "bomb.png"
    Image.new("RGB", (2, 2), "white").save(source)

    def raise_bomb(_path):
        raise Image.DecompressionBombError("pixel count is unsafe")

    monkeypatch.setattr("invoice_ocr.documents.Image.open", raise_bomb)

    with pytest.raises(DocumentError, match="image exceeds pixel safety limit") as error:
        validate_source(source)

    assert isinstance(error.value.__cause__, Image.DecompressionBombError)


def test_prepare_image_wraps_decompression_bomb_during_conversion(tmp_path: Path, monkeypatch):
    source = tmp_path / "bomb.png"
    Image.new("RGB", (2, 2), "white").save(source)

    def raise_bomb(_image):
        raise Image.DecompressionBombError("conversion pixel count is unsafe")

    monkeypatch.setattr("invoice_ocr.documents.ImageOps.exif_transpose", raise_bomb)

    with pytest.raises(DocumentError, match="image exceeds pixel safety limit") as error:
        prepare_document(source, tmp_path / "rendered")

    assert isinstance(error.value.__cause__, Image.DecompressionBombError)
