"""Sanitized client for the private invoice OCR sidecar."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from urllib.parse import urlsplit

import frappe
import requests

DEFAULT_OCR_URL = "http://invoice-ocr:8080"
DEFAULT_DOCKER_HOST = "invoice-ocr"
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
_RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


class OCRServiceError(Exception):
    """A user-safe OCR failure. Its message never contains transport details."""


def _config_value(name, default=None):
    value = getattr(getattr(frappe, "conf", None), name, None)
    if value is None and hasattr(frappe, "get_site_config"):
        value = (frappe.get_site_config() or {}).get(name)
    return default if value is None else value


def _explicit_allowed_hosts() -> set[str]:
    configured = _config_value("invoice_ocr_allowed_hosts", ())
    if isinstance(configured, str):
        configured = configured.split(",")
    if not isinstance(configured, (list, tuple, set)):
        return set()
    return {str(item).strip().lower().rstrip(".") for item in configured if str(item or "").strip()}


def _safe_internal_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    return isinstance(address, ipaddress.IPv4Address) and any(
        address in network for network in _RFC1918_NETWORKS
    )


def _host_is_internal(hostname: str, port: int | None) -> bool:
    normalized = hostname.lower().rstrip(".")
    if normalized == DEFAULT_DOCKER_HOST:
        return True
    explicitly_allowed = normalized in _explicit_allowed_hosts()
    try:
        literal = ipaddress.ip_address(normalized)
    except ValueError:
        literal = None
    if literal is not None:
        return _safe_internal_address(str(literal))
    try:
        answers = socket.getaddrinfo(normalized, port or 80, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror):
        return explicitly_allowed
    addresses = {str(answer[4][0]) for answer in answers if answer and answer[4]}
    return bool(addresses) and all(_safe_internal_address(address) for address in addresses)

def _configured_url() -> str:
    base = str(_config_value("invoice_ocr_url", DEFAULT_OCR_URL) or DEFAULT_OCR_URL).strip().rstrip("/")
    parsed = urlsplit(base)
    try:
        port = parsed.port
    except ValueError as error:
        raise OCRServiceError("OCR 服务配置无效，请联系管理员。") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not _host_is_internal(parsed.hostname, port)
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


def _read_response(response) -> bytes:
    raw_length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
    if raw_length not in (None, ""):
        try:
            declared = int(raw_length)
        except (TypeError, ValueError) as error:
            raise OCRServiceError("OCR 服务返回无效结果，请稍后重试。") from error
        if declared < 0 or declared > MAX_RESPONSE_BYTES:
            raise OCRServiceError("OCR 服务返回无效结果，请稍后重试。")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise OCRServiceError("OCR 服务返回无效结果，请稍后重试。")
        chunks.append(chunk)
    return b"".join(chunks)


def recognize_document(content: bytes, filename: str, record_id: str) -> dict:
    """Send one server-read private file to the internal sidecar."""
    try:
        with requests.post(
            f"{_configured_url()}/v1/recognize",
            files={"file": (filename, content, "application/octet-stream")},
            data={"record_id": record_id},
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            stream=True,
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise OCRServiceError(_status_message(response.status_code))
            raw = _read_response(response)
    except OCRServiceError:
        raise
    except requests.RequestException as error:
        raise OCRServiceError("OCR 服务暂时不可用，请稍后重试。") from error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError) as error:
        raise OCRServiceError("OCR 服务返回无效结果，请稍后重试。") from error
    return _validate_payload(payload, record_id)
