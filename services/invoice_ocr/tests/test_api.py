from __future__ import annotations

from io import BytesIO
from pathlib import Path

import fitz
from fastapi.testclient import TestClient
from PIL import Image
import pytest

import invoice_ocr.api as api
from invoice_ocr.documents import DocumentError
from invoice_ocr.models import OCRLine

SEVEN_FIELDS = {
    "invoice_category",
    "project_name",
    "issue_date",
    "invoice_number",
    "amount_before_tax",
    "tax_amount",
    "total_amount",
}


class FakeEngine:
    def recognize(self, _image_path: Path) -> list[OCRLine]:
        values = [
            "电子发票（普通发票）",
            "开票日期 2026-07-14",
            "发票号码 00123456789012345678",
            "合计（不含税） ￥100.00",
            "合计税额 ￥6.00",
            "价税合计 ￥106.00",
            "项目名称：文具印章",
        ]
        return [
            OCRLine(text=value, score=0.98, box=(0, index * 20, 500, index * 20 + 18))
            for index, value in enumerate(values)
        ]


@pytest.fixture
def invoice_png() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (800, 400), "white").save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def override_engine(monkeypatch):
    api.reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", FakeEngine)
    yield
    api.reset_engine()


@pytest.fixture
def client(override_engine):
    with TestClient(api.app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_health_does_not_initialize_ocr_engine(monkeypatch):
    initialized = False

    class ExplodingEngine:
        def __init__(self):
            nonlocal initialized
            initialized = True
            raise AssertionError("health must not initialize the OCR model")

    api.reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", ExplodingEngine)

    with TestClient(api.app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "engine": "paddleocr"}
    assert initialized is False
    api.reset_engine()


def test_recognize_endpoint_returns_seven_fields_and_sanitized_filename(
    client,
    invoice_png,
):
    response = client.post(
        "/v1/recognize",
        files={
            "file": (
                "../../电子发票_错误号码999999_10000元.png",
                invoice_png,
                "image/png",
            )
        },
        data={"record_id": "INV-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["record_id"] == "INV-1"
    assert body["status"] == "needs_confirmation"
    assert SEVEN_FIELDS <= set(body["fields"])
    assert body["fields"]["invoice_category"] == "电子发票（普通发票）"
    assert body["fields"]["project_name"] == "文具印章"
    assert body["fields"]["issue_date"] == "2026-07-14"
    assert body["fields"]["invoice_number"] == "00123456789012345678"
    assert body["fields"]["amount_before_tax"] == "100.00"
    assert body["fields"]["tax_amount"] == "6.00"
    assert body["fields"]["total_amount"] == "106.00"
    assert body["fields"]["invoice_number"] != "999999"
    assert "/" not in body["source_filename"]
    assert "\\" not in body["source_filename"]


def test_rejects_more_than_ten_megabytes(client):
    response = client.post(
        "/v1/recognize",
        files={
            "file": (
                "big.png",
                b"x" * (10 * 1024 * 1024 + 1),
                "image/png",
            )
        },
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "file_too_large"}


@pytest.mark.parametrize("filename", ["invoice.gif", "invoice.txt", "invoice"])
def test_rejects_unsupported_filename_extension(client, filename, invoice_png):
    response = client.post(
        "/v1/recognize",
        files={"file": (filename, invoice_png, "application/octet-stream")},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "unsupported_file_type"}


def test_rejects_damaged_supported_document_without_leaking_contents(client):
    secret_contents = b"not-a-real-png SECRET-INVOICE-CONTENT"
    response = client.post(
        "/v1/recognize",
        files={"file": ("invoice.png", secret_contents, "image/png")},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_document"}
    assert "SECRET-INVOICE-CONTENT" not in response.text
    assert "Traceback" not in response.text


def test_rejects_password_protected_pdf_as_invalid_document(client):
    document = fitz.open()
    document.new_page()
    encrypted_pdf = document.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    document.close()

    response = client.post(
        "/v1/recognize",
        files={"file": ("protected.pdf", encrypted_pdf, "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_document"}


def test_controlled_document_error_does_not_leak_temporary_path(
    client,
    invoice_png,
    monkeypatch,
):
    def raise_document_error(source, *_args, **_kwargs):
        raise DocumentError(f"failed at {source.resolve()}")

    monkeypatch.setattr(api, "recognize_document", raise_document_error)

    response = client.post(
        "/v1/recognize",
        files={"file": ("invoice.png", invoice_png, "image/png")},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_document"}
    assert "invoice-" not in response.text
    assert "Traceback" not in response.text


def test_unexpected_error_returns_sanitized_500(client, invoice_png, monkeypatch):
    secret = "SECRET-INVOICE-CONTENT"

    def explode(*_args, **_kwargs):
        raise RuntimeError(f"{secret} at C:\\private\\invoice.png")

    monkeypatch.setattr(api, "recognize_document", explode)

    response = client.post(
        "/v1/recognize",
        files={"file": ("invoice.png", invoice_png, "image/png")},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    assert secret not in response.text
    assert "C:\\private" not in response.text
    assert "Traceback" not in response.text


def test_engine_initialization_failure_returns_sanitized_500(invoice_png, monkeypatch):
    secret = "SECRET-MODEL-PATH C:\\models\\private"

    class ExplodingEngine:
        def __init__(self):
            raise RuntimeError(secret)

    api.reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", ExplodingEngine)
    with TestClient(api.app) as test_client:
        response = test_client.post(
            "/v1/recognize",
            files={"file": ("invoice.png", invoice_png, "image/png")},
        )
    api.reset_engine()

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    assert secret not in response.text
    assert "Traceback" not in response.text
