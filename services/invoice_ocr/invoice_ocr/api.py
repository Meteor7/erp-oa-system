from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from invoice_ocr.documents import DocumentError, SUPPORTED_EXTENSIONS
from invoice_ocr.engine import OCREngine, PaddleOCREngine
from invoice_ocr.pipeline import recognize_document

MAX_BYTES = 10 * 1024 * 1024

logger = logging.getLogger(__name__)
app = FastAPI(
    title="Rayher Invoice OCR",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@lru_cache(maxsize=1)
def get_engine() -> OCREngine:
    """Initialize the local PaddleOCR model only on the first recognition request."""
    return PaddleOCREngine()


def _safe_filename(filename: str | None) -> str:
    name = PurePosixPath((filename or "").replace("\\", "/")).name
    if not name or Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="unsupported_file_type")
    return name


def _internal_error(error: Exception) -> HTTPException:
    logger.error("invoice OCR request failed with %s", type(error).__name__)
    return HTTPException(status_code=500, detail="internal_error")


@app.exception_handler(Exception)
async def unhandled_error(_request: Request, error: Exception) -> JSONResponse:
    logger.error("invoice OCR request failed with %s", type(error).__name__)
    return JSONResponse(status_code=500, content={"detail": "internal_error"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "paddleocr"}


@app.post("/v1/recognize")
async def recognize(
    file: Annotated[UploadFile, File()],
    engine: Annotated[OCREngine, Depends(get_engine)],
    record_id: Annotated[str | None, Form()] = None,
) -> dict:
    safe_name = _safe_filename(file.filename)
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")

    try:
        with TemporaryDirectory(prefix="invoice-ocr-") as temporary:
            temporary_root = Path(temporary)
            source = temporary_root / safe_name
            source.write_bytes(content)
            result = recognize_document(
                source,
                temporary_root / "work",
                engine,
                record_id,
            )
    except DocumentError:
        raise HTTPException(status_code=422, detail="invalid_document") from None
    except Exception as exc:
        raise _internal_error(exc) from None

    return result.model_dump(mode="json")
