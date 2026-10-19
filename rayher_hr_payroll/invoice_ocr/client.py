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


def _configuration_error(error=None):
    failure = OCRServiceError("OCR 服务配置无效，请联系演示员工170。")
    if error is None:
        raise failure
    raise failure from error


def _resolved_private_addresses(hostname: str, port: int) -> list[ipaddress._BaseAddress]:
    try:
        answers = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as error:
        _configuration_error(error)
    addresses = {
        str(answer[4][0])
        for answer in answers
        if answer and len(answer) > 4 and answer[4]
    }
    if not addresses or not all(_safe_internal_address(address) for address in addresses):
        _configuration_error()
    return sorted(
        (ipaddress.ip_address(address) for address in addresses),
        key=lambda address: (address.version, int(address)),
    )


def _pinned_netloc(address: ipaddress._BaseAddress, explicit_port: int | None) -> str:
    host = f"[{address}]" if isinstance(address, ipaddress.IPv6Address) else str(address)
    return f"{host}:{explicit_port}" if explicit_port is not None else host


def _configured_endpoint() -> tuple[str, dict[str, str]]:
    configured = str(_config_value("invoice_ocr_url", DEFAULT_OCR_URL) or DEFAULT_OCR_URL).strip()
    parsed = urlsplit(configured)
    try:
        explicit_port = parsed.port
    except ValueError as error:
        _configuration_error(error)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        _configuration_error()

    hostname = parsed.hostname
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if parsed.scheme == "https":
        # Hostname HTTPS pinning requires custom SNI/hostname verification. Until
        # that is implemented, accept only a private/loopback literal IP and keep
        # Requests' normal certificate verification enabled.
        if literal is None or not _safe_internal_address(str(literal)):
            _configuration_error()
        return configured.rstrip("/"), {}

    if literal is not None:
        if not _safe_internal_address(str(literal)):
            _configuration_error()
        return configured.rstrip("/"), {}

    effective_port = explicit_port or 80
    address = _resolved_private_addresses(hostname, effective_port)[0]
    pinned = _pinned_netloc(address, explicit_port)
    host_header = hostname
    if explicit_port is not None:
        host_header = f"{hostname}:{explicit_port}"
    return f"http://{pinned}", {"Host": host_header}


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
    """Send one server-read private file to one verified private endpoint."""
    base_url, headers = _configured_endpoint()
    request_kwargs = {
        "files": {"file": (filename, content, "application/octet-stream")},
        "data": {"record_id": record_id},
        "timeout": (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        "stream": True,
        "allow_redirects": False,
    }
    if headers:
        request_kwargs["headers"] = headers
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.post(f"{base_url}/v1/recognize", **request_kwargs) as response:
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
