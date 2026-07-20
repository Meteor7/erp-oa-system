from __future__ import annotations

import asyncio
from io import BytesIO
import logging
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest

import invoice_ocr.api as api
from invoice_ocr.models import OCRLine


def png_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (32, 24), "white").save(stream, format="PNG")
    return stream.getvalue()


def recognized_lines() -> list[OCRLine]:
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


def reset_engine() -> None:
    reset = getattr(api, "reset_engine", None)
    if reset is not None:
        reset()
    else:
        api.get_engine.cache_clear()


def test_engine_inference_failure_is_a_sanitized_backend_500(monkeypatch, caplog):
    secret = "SECRET-INFERENCE C:\\private\\model"

    class ExplodingEngine:
        def recognize(self, _image_path: Path):
            raise RuntimeError(secret)

    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", ExplodingEngine)
    caplog.set_level(logging.ERROR, logger=api.__name__)
    with TestClient(api.app) as client:
        response = client.post(
            "/v1/recognize",
            files={"file": ("invoice.png", png_bytes(), "image/png")},
        )
    reset_engine()

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    assert secret not in response.text
    assert secret not in caplog.text
    assert "Traceback" not in response.text
    assert "Traceback" not in caplog.text


@pytest.mark.parametrize(
    ("filename", "content", "expected_status"),
    [
        ("invoice.gif", png_bytes(), 415),
        ("big.png", b"x" * (10 * 1024 * 1024 + 1), 413),
    ],
    ids=["unsupported-extension", "oversized-file"],
)
def test_extension_and_file_size_rejection_precede_engine_initialization(
    monkeypatch,
    filename,
    content,
    expected_status,
):
    initialized = 0

    class CountingEngine:
        def __init__(self):
            nonlocal initialized
            initialized += 1

    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", CountingEngine)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/recognize",
            files={"file": (filename, content, "application/octet-stream")},
        )
    reset_engine()

    assert response.status_code == expected_status
    assert initialized == 0


@pytest.mark.parametrize(
    "client_filename",
    [
        "D:invoice.png",
        "D:\\private\\invoice.png",
        "\\\\server\\share\\invoice.png",
        "folder/subfolder/invoice.png",
    ],
)
def test_client_filename_is_never_used_as_the_temporary_path(
    monkeypatch,
    client_filename,
):
    observed_paths: list[Path] = []

    class CapturingEngine:
        def recognize(self, image_path: Path):
            observed_paths.append(image_path)
            return recognized_lines()

    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", CapturingEngine)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/recognize",
            files={"file": (client_filename, png_bytes(), "image/png")},
        )
    reset_engine()

    assert response.status_code == 200
    assert response.json()["source_filename"] == "invoice.png"
    assert observed_paths
    rendered_path = observed_paths[0]
    assert rendered_path.name != client_filename
    assert ":" not in str(rendered_path)
    assert "private" not in str(rendered_path).lower()
    assert "server" not in str(rendered_path).lower()


def test_engine_initialization_exception_is_consumed_and_logs_are_sanitized(
    monkeypatch,
    caplog,
):
    secret = "SECRET-MODEL-PATH C:\\models\\private"

    class ExplodingEngine:
        def __init__(self):
            raise RuntimeError(secret)

    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", ExplodingEngine)
    caplog.set_level(logging.ERROR, logger=api.__name__)
    with TestClient(api.app) as client:
        response = client.post(
            "/v1/recognize",
            files={"file": ("invoice.png", png_bytes(), "image/png")},
        )
    reset_engine()

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    assert secret not in response.text
    assert secret not in caplog.text
    assert "Traceback" not in caplog.text


def test_get_engine_wraps_initialization_failure_in_backend_contract(monkeypatch):
    from invoice_ocr.engine import OCRBackendError

    class ExplodingEngine:
        def __init__(self):
            raise RuntimeError("constructor failed")

    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", ExplodingEngine)
    try:
        with pytest.raises(OCRBackendError, match="initialization failed") as captured:
            api.get_engine()
    finally:
        reset_engine()

    assert isinstance(captured.value.__cause__, RuntimeError)

@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_asgi_error_boundaries_do_not_swallow_base_exceptions(error_type):
    async def explode(_scope, _receive, _send):
        raise error_type("must propagate")

    application = api.SanitizedErrorMiddleware(
        api.RequestSizeLimitMiddleware(explode, api.MAX_REQUEST_BYTES)
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/health",
        "headers": [],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    with pytest.raises(error_type, match="must propagate"):
        asyncio.run(application(scope, receive, send))