from __future__ import annotations

import asyncio
from io import BytesIO
import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest
from starlette.datastructures import UploadFile as StarletteUploadFile

import invoice_ocr.api as api
from invoice_ocr.models import OCRLine

REQUEST_OVERHEAD_BYTES = 64 * 1024


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


def reset_engine() -> None:
    reset = getattr(api, "reset_engine", None)
    if reset is not None:
        reset()
    else:
        api.get_engine.cache_clear()


def multipart_body(total_bytes: int, boundary: bytes = b"hard-limit") -> bytes:
    prefix = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="invoice.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
    )
    suffix = b"\r\n--" + boundary + b"--\r\n"
    payload_size = total_bytes - len(prefix) - len(suffix)
    assert payload_size >= 8
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * (payload_size - 8)
    return prefix + payload + suffix


def call_asgi(application, *, headers, chunks):
    async def scenario():
        receive_calls = 0
        messages = []
        pending = list(chunks) if chunks is not None else None

        async def receive():
            nonlocal receive_calls
            receive_calls += 1
            if pending is None:
                raise AssertionError("oversized Content-Length must be rejected before receive")
            if not pending:
                return {"type": "http.disconnect"}
            body = pending.pop(0)
            return {"type": "http.request", "body": body, "more_body": bool(pending)}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/recognize",
            "raw_path": b"/v1/recognize",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "state": {},
        }
        await application(scope, receive, send)
        start = next(message for message in messages if message["type"] == "http.response.start")
        raw_body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        start_count = sum(message["type"] == "http.response.start" for message in messages)
        return start["status"], json.loads(raw_body), receive_calls, start_count

    return asyncio.run(scenario())


def test_content_length_hard_limit_rejects_before_reading_or_initializing(monkeypatch):
    initialized = 0

    class CountingEngine:
        def __init__(self):
            nonlocal initialized
            initialized += 1

    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", CountingEngine)
    request_limit = api.MAX_BYTES + REQUEST_OVERHEAD_BYTES
    status, body, receive_calls, start_count = call_asgi(
        api.app,
        headers=[
            (b"content-type", b"multipart/form-data; boundary=hard-limit"),
            (b"content-length", str(request_limit + 1).encode("ascii")),
        ],
        chunks=None,
    )
    reset_engine()

    assert getattr(api, "MAX_REQUEST_BYTES", None) == request_limit
    assert status == 413
    assert body == {"detail": "request_too_large"}
    assert receive_calls == 0
    assert start_count == 1
    assert initialized == 0


@pytest.mark.parametrize("content_length", [None, b"1"])
def test_chunk_count_hard_limit_rejects_missing_or_forged_length(monkeypatch, content_length):
    initialized = 0

    class CountingEngine:
        def __init__(self):
            nonlocal initialized
            initialized += 1

    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", CountingEngine)
    request_limit = api.MAX_BYTES + REQUEST_OVERHEAD_BYTES
    body = multipart_body(request_limit + 1)
    headers = [(b"content-type", b"multipart/form-data; boundary=hard-limit")]
    if content_length is not None:
        headers.append((b"content-length", content_length))
    split = request_limit - 64
    status, response_body, _receive_calls, start_count = call_asgi(
        api.app,
        headers=headers,
        chunks=[body[:split], body[split:]],
    )
    reset_engine()

    assert status == 413
    assert response_body == {"detail": "request_too_large"}
    assert start_count == 1
    assert initialized == 0


def test_exact_ten_mib_file_is_allowed_with_bounded_multipart_overhead(monkeypatch):
    class FakeEngine:
        def recognize(self, _image_path: Path):
            return recognized_lines()

    content = png_bytes()
    content += b"\0" * (api.MAX_BYTES - len(content))
    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", FakeEngine)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/recognize",
            files={"file": ("invoice.png", content, "image/png")},
        )
    reset_engine()

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("filename", "content", "engine_mode", "expected_status", "expects_temp"),
    [
        ("invoice.png", png_bytes(), "success", 200, True),
        ("invoice.png", b"not-a-png", "success", 422, True),
        ("invoice.png", png_bytes(), "explode", 500, True),
        ("invoice.gif", png_bytes(), "success", 415, False),
        ("big.png", b"x" * (10 * 1024 * 1024 + 1), "success", 413, False),
    ],
    ids=["success", "invalid-document", "backend-error", "unsupported", "file-too-large"],
)
def test_upload_spool_and_temporary_directory_cleanup_is_observable(
    monkeypatch,
    filename,
    content,
    engine_mode,
    expected_status,
    expects_temp,
):
    from tempfile import TemporaryDirectory as RealTemporaryDirectory

    closed_uploads = []
    temporary_paths: list[Path] = []
    original_close = StarletteUploadFile.close

    async def tracking_close(self):
        closed_uploads.append(self.filename)
        await original_close(self)

    class TrackingTemporaryDirectory(RealTemporaryDirectory):
        def __enter__(self):
            value = super().__enter__()
            temporary_paths.append(Path(value))
            return value

    class TestEngine:
        def recognize(self, _image_path: Path):
            if engine_mode == "explode":
                raise RuntimeError("secret failure")
            return recognized_lines()

    reset_engine()
    monkeypatch.setattr(StarletteUploadFile, "close", tracking_close)
    monkeypatch.setattr(api, "TemporaryDirectory", TrackingTemporaryDirectory)
    monkeypatch.setattr(api, "PaddleOCREngine", TestEngine)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/recognize",
            files={"file": (filename, content, "application/octet-stream")},
        )
    reset_engine()

    assert response.status_code == expected_status
    assert closed_uploads == [filename]
    assert bool(temporary_paths) is expects_temp
    assert all(not path.exists() for path in temporary_paths)


def test_chunk_limit_closes_partially_parsed_multipart_spool(monkeypatch, caplog):
    import starlette.formparsers as formparsers

    caplog.set_level(logging.ERROR, logger=api.__name__)
    endpoint_entered = False
    real_validate = api._validated_suffix

    def track_endpoint(filename):
        nonlocal endpoint_entered
        endpoint_entered = True
        return real_validate(filename)

    monkeypatch.setattr(api, "_validated_suffix", track_endpoint)
    real_spooled_file = formparsers.SpooledTemporaryFile
    spools = []

    def tracking_spooled_file(*args, **kwargs):
        spool = real_spooled_file(*args, **kwargs)
        spools.append(spool)
        return spool

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", tracking_spooled_file)
    request_limit = api.MAX_REQUEST_BYTES
    body = multipart_body(request_limit + 1)
    split = request_limit - 64
    status, response_body, _receive_calls, start_count = call_asgi(
        api.app,
        headers=[(b"content-type", b"multipart/form-data; boundary=hard-limit")],
        chunks=[body[:split], body[split:]],
    )

    assert status == 413
    assert response_body == {"detail": "request_too_large"}
    assert start_count == 1
    assert endpoint_entered is False
    assert not caplog.records
    assert spools
    assert all(spool.closed for spool in spools)