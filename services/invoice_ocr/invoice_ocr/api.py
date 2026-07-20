from __future__ import annotations

import json
import logging
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from threading import Lock
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
# A legal 10 MiB file needs multipart boundaries and the small record_id field.
# Cap that protocol overhead at 64 KiB so the whole request remains bounded.
MAX_MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_REQUEST_BYTES = MAX_BYTES + MAX_MULTIPART_OVERHEAD_BYTES

logger = logging.getLogger(__name__)
_engine_instance: OCREngine | None = None
_engine_init_lock = Lock()
_recognition_lock = Lock()


def get_engine() -> OCREngine:
    """Return the process-wide Paddle engine, constructing it exactly once."""
    global _engine_instance
    instance = _engine_instance
    if instance is not None:
        return instance
    with _engine_init_lock:
        instance = _engine_instance
        if instance is None:
            try:
                instance = PaddleOCREngine()
            except Exception as error:
                raise OCRBackendError("OCR backend initialization failed") from error
            _engine_instance = instance
    return instance


def reset_engine() -> None:
    """Discard the cached engine during a controlled idle/test lifecycle."""
    global _engine_instance
    with _engine_init_lock:
        _engine_instance = None


def _validated_suffix(filename: str | None) -> str:
    name = PurePosixPath((filename or "").replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    if not name or suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="unsupported_file_type")
    return suffix


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
        try:
            await self.application(scope, receive, send)
        except Exception as error:
            _log_internal_error(error)
            await _send_json_error(send, 500, "internal_error")


api = FastAPI(
    title="Rayher Invoice OCR",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@api.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "engine": "paddleocr"}


@api.post("/v1/recognize")
async def recognize(
    file: Annotated[UploadFile, File()],
    record_id: Annotated[str | None, Form()] = None,
) -> Any:
    suffix = _validated_suffix(file.filename)
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
