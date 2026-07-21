"""Sanitized client for the private invoice OCR sidecar."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import frappe
import requests

DEFAULT_OCR_URL = "http://invoice-ocr:8080"
CONNECT_TIMEOUT_SECONDS = 3.05
READ_TIMEOUT_SECONDS = 120
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SEVEN_FIELDS = {
    "invoice_category",
    "project_name",
    "issue_date",
    "invoice_number",
    "amount_before_tax",
    "tax_amount",
    "total_amount",
}
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class OCRServiceError(Exception):
    """A user-safe OCR failure. Its message never contains transport details."""


def _configured_url() -> str:
    configured = getattr(getattr(frappe, "conf", None), "invoice_ocr_url", None)
    if configured is None and hasattr(frappe, "get_site_config"):
        configured = (frappe.get_site_config() or {}).get("invoice_ocr_url")
    base = str(configured or DEFAULT_OCR_URL).strip().rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise OCRServiceError("OCR 服务配置无效，请联系管理员。")
    return base


def _status_message(status_code: int) -> str:
    if status_code == 413:
        return "发票文件超过 10 MB 限制。"
    if status_code == 415:
        return "仅支持 PDF、JPG、JPEG 或 PNG 发票文件。"
    if status_code == 422:
        return "发票文件无效、已损坏或受密码保护。"
    if 400 <= status_code < 500:
        return "OCR 服务拒绝了该发票文件。"
    return "OCR 服务暂时不可用，请稍后重试。"


def _validate_payload(payload, record_id: str) -> dict:
    if not isinstance(payload, dict):
        raise OCRServiceError("OCR 服务返回无效结果，请稍后重试。")
    fields = payload.get("fields")
    if (
        payload.get("record_id") != record_id
        or payload.get("status") != "needs_confirmation"
        or not isinstance(fields, dict)
        or not SEVEN_FIELDS.issubset(fields)
        or not _SHA256.fullmatch(str(payload.get("file_sha256") or ""))
        or not isinstance(payload.get("warnings", []), list)
        or not isinstance(payload.get("field_confidence", {}), dict)
        or not isinstance(payload.get("ocr_lines", []), list)
    ):
        raise OCRServiceError("OCR 服务返回无效结果，请稍后重试。")
    return payload


def recognize_document(content: bytes, filename: str, record_id: str) -> dict:
    """Send one server-read private file to the internal sidecar.

    No endpoint, response body, local path, or invoice content is copied into a
    raised exception.
    """
    try:
        response = requests.post(
            f"{_configured_url()}/v1/recognize",
            files={"file": (filename, content, "application/octet-stream")},
            data={"record_id": record_id},
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        )
    except OCRServiceError:
        raise
    except requests.RequestException as error:
        raise OCRServiceError("OCR 服务暂时不可用，请稍后重试。") from error

    if response.status_code != 200:
        raise OCRServiceError(_status_message(response.status_code))
    raw = response.content
    if len(raw) > MAX_RESPONSE_BYTES:
        raise OCRServiceError("OCR 服务返回无效结果，请稍后重试。")
    try:
        payload = response.json()
    except (TypeError, ValueError) as error:
        raise OCRServiceError("OCR 服务返回无效结果，请稍后重试。") from error
    return _validate_payload(payload, record_id)
