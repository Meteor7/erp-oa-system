from __future__ import annotations

import json
import logging
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from invoice_ocr.documents import DocumentError, SUPPORTED_EXTENSIONS
from invoice_ocr.engine import OCRBackendError, OCREngine, PaddleOCREngine
from invoice_ocr.pipeline import recognize_document

MAX_BYTES = 10 * 1024 * 1024
# Bound each untrusted multipart metadata value by its UTF-8 byte length.
MAX_FILENAME_BYTES = 255
MAX_RECORD_ID_BYTES = 512
# 64 KiB covers both legal metadata maxima plus multipart headers/boundaries,
# while keeping the complete request close to the 10 MiB file contract.
MAX_MULTIPART_OVERHEAD = 64 * 1024
MAX_REQUEST_BYTES = MAX_BYTES + MAX_MULTIPART_OVERHEAD
ENGINE_INIT_FAILURE_BACKOFF_SECONDS = 5.0

logger = logging.getLogger(__name__)
_engine_instance: OCREngine | None = None
_engine_retry_after = 0.0
_engine_init_lock = Lock()
_recognition_lock = Lock()


def get_engine() -> OCREngine:
    """Return the shared engine, with a short sanitized failure backoff."""
    global _engine_instance, _engine_retry_after
    instance = _engine_instance
    if instance is not None:
        return instance
    with _engine_init_lock:
        instance = _engine_instance
        if instance is not None:
            return instance
        if monotonic() < _engine_retry_after:
            raise OCRBackendError("OCR backend temporarily unavailable")
        try:
            instance = PaddleOCREngine()
        except Exception as error:
            _engine_retry_after = monotonic() + ENGINE_INIT_FAILURE_BACKOFF_SECONDS
            raise OCRBackendError("OCR backend initialization failed") from error
        _engine_instance = instance
        _engine_retry_after = 0.0
        return instance


def reset_engine() -> None:
    """Discard cached success and failure state during an idle/test lifecycle."""
    global _engine_instance, _engine_retry_after
    with _engine_init_lock:
        _engine_instance = None
        _engine_retry_after = 0.0


def _validated_suffix(filename: str | None) -> str:
    raw_name = filename or ""
    if len(raw_name.encode("utf-8")) > MAX_FILENAME_BYTES:
        raise HTTPException(status_code=422, detail="filename_too_long")
    name = PurePosixPath(raw_name.replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    if not name or suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="unsupported_file_type")
    return suffix


def _validate_record_id(record_id: str | None) -> None:
    if record_id is not None and len(record_id.encode("utf-8")) > MAX_RECORD_ID_BYTES:
        raise HTTPException(status_code=422, detail="record_id_too_long")


def _log_internal_error(error: Exception) -> None:
    logger.error(
        "invoice OCR request failed (error_type=%s)",
        type(error).__name__,
    )


def _process_document(content: bytes, suffix: str, record_id: str | None):
    with TemporaryDirectory(prefix="invoice-ocr-") as temporary:
        temporary_root = Path(temporary)
        # Never let the untrusted multipart filename become a filesystem component.
        source = temporary_root / f"invoice{suffix}"
        source.write_bytes(content)
        engine = get_engine()
        # PaddleOCR is shared process-wide and its inference calls are serialized.
        # This lock is acquired in a worker thread, never on the event loop.
        with _recognition_lock:
            return recognize_document(
                source,
                temporary_root / "work",
                engine,
                record_id,
            )


async def _send_json_error(send: Send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestSizeLimitMiddleware:
    """Enforce a total ASGI request limit before endpoint execution.

    Content-Length is rejected without reading. Missing or forged lengths are
    enforced while consuming receive chunks; inner response messages are held
    until the final byte count is known, preventing a second response.
    """

    def __init__(self, application: ASGIApp, max_bytes: int) -> None:
        self.application = application
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return

        declared_lengths = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == b"content-length"
        ]
        if declared_lengths:
            try:
                parsed_lengths = [int(value) for value in declared_lengths]
            except (TypeError, ValueError):
                await _send_json_error(send, 413, "request_too_large")
                return
            if (
                any(value < 0 or value > self.max_bytes for value in parsed_lengths)
                or len(set(parsed_lengths)) != 1
            ):
                await _send_json_error(send, 413, "request_too_large")
                return

        received = 0
        exceeded = False
        buffered_messages: list[Message] = []

        async def limited_receive() -> Message:
            nonlocal exceeded, received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    raise MultiPartException("request body exceeds configured limit")
            return message

        async def buffered_send(message: Message) -> None:
            buffered_messages.append(message)

        try:
            await self.application(scope, limited_receive, buffered_send)
        except Exception:
            if not exceeded:
                raise

        if exceeded:
            await _send_json_error(send, 413, "request_too_large")
            return
        for message in buffered_messages:
            await send(message)


class SanitizedErrorMiddleware:
    """Consume ordinary application exceptions at the outer ASGI boundary."""

    def __init__(self, application: ASGIApp) -> None:
        self.application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return
        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            await send(message)
            if message["type"] == "http.response.start":
                response_started = True

        try:
            await self.application(scope, receive, tracking_send)
        except Exception as error:
            if response_started:
                raise
            _log_internal_error(error)
            await _send_json_error(send, 500, "internal_error")


api = FastAPI(
    title="QIHENG Demo Invoice OCR",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@api.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "engine": "paddleocr"}


@api.get("/ready")
async def ready() -> Any:
    try:
        await run_in_threadpool(get_engine)
    except Exception as error:
        _log_internal_error(error)
        return JSONResponse(status_code=503, content={"detail": "not_ready"})
    return {"status": "ready", "engine": "paddleocr"}


@api.post("/v1/recognize")
async def recognize(
    file: Annotated[UploadFile, File()],
    record_id: Annotated[str | None, Form()] = None,
) -> Any:
    suffix = _validated_suffix(file.filename)
    _validate_record_id(record_id)
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")

    try:
        result = await run_in_threadpool(
            _process_document,
            content,
            suffix,
            record_id,
        )
    except DocumentError:
        raise HTTPException(status_code=422, detail="invalid_document") from None
    except Exception as error:
        _log_internal_error(error)
        return JSONResponse(status_code=500, content={"detail": "internal_error"})
    return result.model_dump(mode="json")


app: ASGIApp = SanitizedErrorMiddleware(
    RequestSizeLimitMiddleware(api, MAX_REQUEST_BYTES)
)
