from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient
from PIL import Image
import pytest

import invoice_ocr.api as api
from invoice_ocr.engine import OCRBackendError
from invoice_ocr.models import OCRLine


def png_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (32, 24), "white").save(stream, format="PNG")
    return stream.getvalue()


def recognized_lines() -> list[OCRLine]:
    return [
        OCRLine(text="电子发票（普通发票）", score=0.98, box=(0, 0, 500, 18)),
        OCRLine(text="开票日期 2026-07-14", score=0.98, box=(0, 20, 500, 38)),
        OCRLine(text="发票号码 00123456789012345678", score=0.98, box=(0, 40, 500, 58)),
        OCRLine(text="合计（不含税） ￥100.00", score=0.98, box=(0, 60, 500, 78)),
        OCRLine(text="合计税额 ￥6.00", score=0.98, box=(0, 80, 500, 98)),
        OCRLine(text="价税合计 ￥106.00", score=0.98, box=(0, 100, 500, 118)),
    ]


def test_sanitized_error_middleware_does_not_send_second_start_after_send_failure():
    starts: list[int] = []

    async def application(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def failing_send(message):
        if message["type"] == "http.response.start":
            starts.append(message["status"])
            return
        raise RuntimeError("client socket closed")

    scope = {"type": "http", "method": "GET", "path": "/health", "headers": []}
    wrapped = api.SanitizedErrorMiddleware(application)

    with pytest.raises(RuntimeError, match="client socket closed"):
        asyncio.run(wrapped(scope, receive, failing_send))

    assert starts == [200]


def test_multipart_metadata_limits_are_explicit_and_bounded():
    assert api.MAX_MULTIPART_OVERHEAD == 64 * 1024
    assert api.MAX_FILENAME_BYTES == 255
    assert api.MAX_RECORD_ID_BYTES == 512
    assert api.MAX_REQUEST_BYTES == api.MAX_BYTES + api.MAX_MULTIPART_OVERHEAD
    assert api.MAX_FILENAME_BYTES + api.MAX_RECORD_ID_BYTES < api.MAX_MULTIPART_OVERHEAD


def test_exact_utf8_metadata_limits_allow_a_ten_mib_file(monkeypatch):
    filename = "票" * 83 + "ab.png"
    record_id = "单" * 170 + "ab"
    assert len(filename.encode("utf-8")) == 255
    assert len(record_id.encode("utf-8")) == 512

    class FakeEngine:
        def recognize(self, _image_path: Path):
            return recognized_lines()

    content = png_bytes()
    content += b"\0" * (api.MAX_BYTES - len(content))
    api.reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", FakeEngine)
    try:
        with TestClient(api.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/v1/recognize",
                files={"file": (filename, content, "image/png")},
                data={"record_id": record_id},
            )
    finally:
        api.reset_engine()

    assert response.status_code == 200
    assert response.json()["record_id"] == record_id


@pytest.mark.parametrize(
    ("filename", "record_id", "detail"),
    [
        ("票" * 84 + ".png", "INV-1", "filename_too_long"),
        ("invoice.png", "单" * 171, "record_id_too_long"),
    ],
    ids=["filename-256-utf8-bytes", "record-id-513-utf8-bytes"],
)
def test_oversized_utf8_metadata_is_rejected_without_engine_initialization(
    monkeypatch,
    filename,
    record_id,
    detail,
):
    initialized = 0

    class CountingEngine:
        def __init__(self):
            nonlocal initialized
            initialized += 1

    api.reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", CountingEngine)
    try:
        with TestClient(api.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/v1/recognize",
                files={"file": (filename, png_bytes(), "image/png")},
                data={"record_id": record_id},
            )
    finally:
        api.reset_engine()

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert initialized == 0


def test_abnormally_large_filename_header_is_stopped_by_total_request_limit(monkeypatch):
    initialized = 0

    class CountingEngine:
        def __init__(self):
            nonlocal initialized
            initialized += 1

    content = png_bytes()
    content += b"\0" * (api.MAX_BYTES - len(content))
    api.reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", CountingEngine)
    try:
        with TestClient(api.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/v1/recognize",
                files={
                    "file": (
                        "x" * (api.MAX_MULTIPART_OVERHEAD + 1) + ".png",
                        content,
                        "image/png",
                    )
                },
            )
    finally:
        api.reset_engine()

    assert response.status_code == 413
    assert response.json() == {"detail": "request_too_large"}
    assert initialized == 0


def test_concurrent_initialization_failure_is_constructed_once_per_backoff(monkeypatch):
    constructors = 0
    constructors_lock = threading.Lock()
    callers_ready = threading.Barrier(8)
    clock = [100.0]
    secret = "SECRET-CONSTRUCTOR-PATH"

    class FailingEngine:
        def __init__(self):
            nonlocal constructors
            with constructors_lock:
                constructors += 1
            time.sleep(0.05)
            raise RuntimeError(secret)

    def resolve_error():
        callers_ready.wait(timeout=2)
        try:
            api.get_engine()
        except OCRBackendError as error:
            return error
        raise AssertionError("engine initialization unexpectedly succeeded")

    api.reset_engine()
    monkeypatch.setattr(api, "monotonic", lambda: clock[0], raising=False)
    monkeypatch.setattr(api, "PaddleOCREngine", FailingEngine)
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            errors = list(executor.map(lambda _index: resolve_error(), range(8)))

        assert constructors == 1
        assert all(secret not in str(error) for error in errors)
        assert len({id(error) for error in errors}) == 8
        assert sum(error.__cause__ is not None for error in errors) == 1

        with pytest.raises(OCRBackendError, match="temporarily unavailable") as cached:
            api.get_engine()
        assert cached.value.__cause__ is None
        assert constructors == 1
    finally:
        api.reset_engine()


def test_initialization_retries_once_after_backoff_and_can_recover(monkeypatch):
    attempts = 0
    clock = [200.0]
    recovered = object()

    def factory():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("secret first failure")
        return recovered

    api.reset_engine()
    monkeypatch.setattr(api, "monotonic", lambda: clock[0], raising=False)
    monkeypatch.setattr(api, "PaddleOCREngine", factory)
    try:
        with pytest.raises(OCRBackendError, match="initialization failed"):
            api.get_engine()

        with pytest.raises(OCRBackendError, match="temporarily unavailable"):
            api.get_engine()
        assert attempts == 1

        assert 0 < api.ENGINE_INIT_FAILURE_BACKOFF_SECONDS <= 5.0
        clock[0] += api.ENGINE_INIT_FAILURE_BACKOFF_SECONDS + 0.01
        assert api.get_engine() is recovered
        assert api.get_engine() is recovered
        assert attempts == 2
    finally:
        api.reset_engine()


def test_reset_engine_clears_initialization_backoff(monkeypatch):
    attempts = 0
    recovered = object()

    def factory():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("first failure")
        return recovered

    api.reset_engine()
    monkeypatch.setattr(api, "monotonic", lambda: 300.0, raising=False)
    monkeypatch.setattr(api, "PaddleOCREngine", factory)
    try:
        with pytest.raises(OCRBackendError):
            api.get_engine()
        api.reset_engine()
        assert api.get_engine() is recovered
        assert attempts == 2
    finally:
        api.reset_engine()
