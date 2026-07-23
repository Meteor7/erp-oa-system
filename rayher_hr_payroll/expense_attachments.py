"""Private supplemental attachment workflow for expense reimbursement lines."""

import hashlib
import json
import secrets
from pathlib import PurePosixPath

import frappe

from rayher_hr_payroll.invoice_ocr import service as invoice_service

ATTACHMENT_DOCTYPE = "OA Expense Line Attachment"
REQUEST_DOCTYPE = "OA Approval Request"
DRAFT_STATUS = "\u8349\u7a3f"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_LINE = 10
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def _throw(message):
    frappe.throw(frappe._(message))


def validate_attachment_content(filename, content):
    name = str(filename or "").replace("\\", "/")
    base_name = PurePosixPath(name).name
    extension = PurePosixPath(base_name).suffix.lower()
    if not base_name or extension not in ALLOWED_EXTENSIONS:
        _throw("Only PDF, JPG, JPEG, and PNG attachments are supported.")
    if not isinstance(content, (bytes, bytearray)) or not content:
        _throw("The attachment is empty or unreadable.")
    if len(content) > MAX_ATTACHMENT_BYTES:
        _throw("Each attachment must not exceed 10 MB.")
    valid = (
        (extension == ".pdf" and content.startswith(b"%PDF-"))
        or (extension in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff"))
        or (extension == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
    )
    if not valid:
        _throw("The attachment content does not match its filename extension.")
    return {
        "original_filename": base_name[:255],
        "mime_type": MIME_BY_EXTENSION[extension],
        "file_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def validate_capacity(existing_count):
    try:
        count = int(existing_count)
    except (TypeError, ValueError):
        _throw("Attachment count is invalid.")
    if count < 0 or count >= MAX_ATTACHMENTS_PER_LINE:
        _throw("Each expense line can contain at most 10 supplemental attachments.")
    return count


def _value(source, field, default=None):
    if isinstance(source, dict):
        return source.get(field, default)
    return getattr(source, field, default)


def validate_line_membership(request, line_key):
    key = str(line_key or "").strip()
    if not key or len(key) > 140:
        _throw("The expense line key is invalid.")
    for line in list(_value(request, "expense_lines", []) or []):
        if str(_value(line, "line_key", "") or "").strip() == key:
            return line
    _throw("The expense line does not belong to this reimbursement request.")


def validate_file_registration(file_doc, user=None):
    user = user or invoice_service._user()
    file_url = invoice_service._safe_file_url(_value(file_doc, "file_url"))
    if int(_value(file_doc, "is_private", 0) or 0) != 1:
        _throw("Supplemental attachments must be private files.")
    roles = set(frappe.get_roles(user) or [])
    if _value(file_doc, "owner") != user and user != "Administrator" and "System Manager" not in roles:
        _throw("Only the uploader may register a supplemental attachment.")
    if _value(file_doc, "attached_to_doctype") or _value(file_doc, "attached_to_name"):
        _throw("The uploaded file is already attached to another record.")
    if _value(file_doc, "file_url") != file_url:
        _throw("The uploaded file address is invalid.")
    return file_doc


def _serialize_attachment(doc):
    return {
        "name": _value(doc, "name"),
        "request": _value(doc, "request"),
        "expense_line_key": _value(doc, "expense_line_key"),
        "original_filename": _value(doc, "original_filename") or "",
        "mime_type": _value(doc, "mime_type") or "",
        "file_size": int(_value(doc, "file_size", 0) or 0),
        "uploaded_by": _value(doc, "uploaded_by") or "",
        "uploaded_on": _value(doc, "uploaded_on"),
    }


def _load_request(name, current=False):
    request_name = str(name or "").strip()
    if not request_name or len(request_name) > 140:
        _throw("The reimbursement request number is invalid.")
    return invoice_service._current_doc(REQUEST_DOCTYPE, request_name) if current else frappe.get_doc(REQUEST_DOCTYPE, request_name)


def _require_request_access(request, write=False, current=False):
    invoice_service._request_permission(request, "edit" if write else "read", current=current)
    if write and _value(request, "workflow_status") != DRAFT_STATUS:
        _throw("Supplemental attachments can be changed only while the reimbursement is a draft.")


def _attachment_count(request_name, line_key):
    return int(frappe.db.count(ATTACHMENT_DOCTYPE, {"request": request_name, "expense_line_key": line_key}) or 0)


def _read_attachment_file(attachment, current=False):
    file_url = invoice_service._safe_file_url(_value(attachment, "file_url"))
    file_doc = invoice_service._file_doc(file_url, current=current)
    if _value(file_doc, "name") != _value(attachment, "file"):
        _throw("The supplemental attachment file link is invalid.")
    if int(_value(file_doc, "is_private", 0) or 0) != 1:
        _throw("The supplemental attachment is no longer private.")
    if _value(file_doc, "attached_to_doctype") != REQUEST_DOCTYPE or _value(file_doc, "attached_to_name") != _value(attachment, "request"):
        _throw("The supplemental attachment relation is invalid.")
    content = invoice_service._read_limited(file_doc)
    metadata = validate_attachment_content(_value(attachment, "original_filename"), content)
    if metadata["sha256"] != _value(attachment, "file_sha256"):
        _throw("The supplemental attachment content has changed.")
    return file_doc, content


def list_attachments(request_name, line_key=None, current=False):
    request = _load_request(request_name, current=current)
    _require_request_access(request, write=False, current=current)
    filters = {"request": _value(request, "name")}
    if line_key is not None:
        validate_line_membership(request, line_key)
        filters["expense_line_key"] = str(line_key).strip()
    rows = frappe.get_all(
        ATTACHMENT_DOCTYPE,
        filters=filters,
        fields=["name"],
        order_by="creation asc",
        limit_page_length=1000,
    )
    return [_serialize_attachment(frappe.get_doc(ATTACHMENT_DOCTYPE, _value(row, "name"))) for row in rows]


def register_attachment(request_name, line_key, file_url):
    request_name = str(request_name or "").strip()
    line_key = str(line_key or "").strip()
    with invoice_service._transaction_lock("expense-attachment", request_name, line_key):
        request = _load_request(request_name, current=True)
        _require_request_access(request, write=True, current=True)
        line = validate_line_membership(request, line_key)
        validate_capacity(_attachment_count(request_name, line_key))
        safe_url = invoice_service._safe_file_url(file_url)
        file_doc = invoice_service._file_doc(safe_url, current=True)
        validate_file_registration(file_doc)
        content = invoice_service._read_limited(file_doc)
        metadata = validate_attachment_content(_value(file_doc, "file_name") or PurePosixPath(safe_url).name, content)
        if frappe.db.exists(ATTACHMENT_DOCTYPE, {"file": _value(file_doc, "name")}):
            _throw("The uploaded file is already registered as an attachment.")
        original_link = {
            "attached_to_doctype": _value(file_doc, "attached_to_doctype") or "",
            "attached_to_name": _value(file_doc, "attached_to_name") or "",
            "attached_to_field": _value(file_doc, "attached_to_field") or "",
        }
        try:
            file_doc.attached_to_doctype = REQUEST_DOCTYPE
            file_doc.attached_to_name = request_name
            file_doc.attached_to_field = "expense_lines"
            file_doc.save(ignore_permissions=True)
            attachment = frappe.get_doc(
                {
                    "doctype": ATTACHMENT_DOCTYPE,
                    "request": request_name,
                    "expense_line_key": line_key,
                    "file": _value(file_doc, "name"),
                    "file_url": safe_url,
                    "original_filename": metadata["original_filename"],
                    "mime_type": metadata["mime_type"],
                    "file_size": metadata["file_size"],
                    "file_sha256": metadata["sha256"],
                    "uploaded_by": invoice_service._user(),
                    "uploaded_on": invoice_service._now(),
                }
            )
            attachment.insert(ignore_permissions=True)
            line.attachment_count = _attachment_count(request_name, line_key)
            request.save(ignore_permissions=True)
            return _serialize_attachment(attachment)
        except BaseException:
            try:
                file_doc.attached_to_doctype = original_link["attached_to_doctype"]
                file_doc.attached_to_name = original_link["attached_to_name"]
                file_doc.attached_to_field = original_link["attached_to_field"]
                file_doc.save(ignore_permissions=True)
                frappe.delete_doc("File", _value(file_doc, "name"), ignore_permissions=True, force=True)
            except BaseException:
                logger = getattr(frappe, "log_error", None)
                if callable(logger):
                    logger("Expense attachment cleanup failed", "Expense attachment")
            raise


def delete_attachment(request_name, attachment_name):
    request_name = str(request_name or "").strip()
    attachment_name = str(attachment_name or "").strip()
    with invoice_service._transaction_lock("expense-attachment", request_name, attachment_name):
        request = _load_request(request_name, current=True)
        _require_request_access(request, write=True, current=True)
        attachment = invoice_service._current_doc(ATTACHMENT_DOCTYPE, attachment_name)
        if _value(attachment, "request") != request_name:
            _throw("The supplemental attachment does not belong to this reimbursement request.")
        line_key = str(_value(attachment, "expense_line_key") or "")
        line = validate_line_membership(request, line_key)
        file_doc, _content = _read_attachment_file(attachment, current=True)
        frappe.delete_doc(ATTACHMENT_DOCTYPE, attachment_name, ignore_permissions=True, force=True)
        frappe.delete_doc("File", _value(file_doc, "name"), ignore_permissions=True, force=True)
        line.attachment_count = _attachment_count(request_name, line_key)
        request.save(ignore_permissions=True)
        return {"deleted": attachment_name, "expense_line_key": line_key}


def _preview_cache_key(token):
    return invoice_service._lock_key("expense-preview-token", token)


def preview_attachment(attachment_name):
    attachment = frappe.get_doc(ATTACHMENT_DOCTYPE, str(attachment_name or "").strip())
    request = _load_request(_value(attachment, "request"), current=True)
    _require_request_access(request, write=False, current=True)
    validate_line_membership(request, _value(attachment, "expense_line_key"))
    _file_doc, _content = _read_attachment_file(attachment, current=True)
    token = secrets.token_urlsafe(32)
    frappe.cache().set_value(
        _preview_cache_key(token),
        json.dumps({"user": invoice_service._user(), "attachment": _value(attachment, "name")}, separators=(",", ":")),
        expires_in_sec=invoice_service.PREVIEW_TOKEN_TTL_SECONDS,
    )
    return {
        "token": token,
        "preview_method": "POST",
        "preview_url": "/api/method/rayher_hr_payroll.api.oa_entry.serve_expense_attachment_preview",
        "mime_type": _value(attachment, "mime_type"),
        "display_name": _value(attachment, "original_filename"),
    }


def serve_attachment_preview(token):
    user = invoice_service._user()
    token = str(token or "").strip()
    if len(token) < 32 or len(token) > 200 or "\x00" in token:
        _throw("The attachment preview token is invalid or expired.")
    cache = frappe.cache()
    key = _preview_cache_key(token)
    lock = cache.lock(invoice_service._lock_key("expense-preview-consume", token), timeout=invoice_service.PREVIEW_TOKEN_TTL_SECONDS, blocking_timeout=5)
    if not lock.acquire(blocking=True, blocking_timeout=5):
        _throw("The attachment preview is busy. Please retry.")
    try:
        raw = cache.get_value(key)
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            payload = None
        if not isinstance(payload, dict) or not payload.get("attachment") or payload.get("user") != user:
            _throw("The attachment preview token is invalid or expired.")
        attachment = invoice_service._current_doc(ATTACHMENT_DOCTYPE, str(payload["attachment"]))
        request = _load_request(_value(attachment, "request"), current=True)
        _require_request_access(request, write=False, current=True)
        validate_line_membership(request, _value(attachment, "expense_line_key"))
        _file_doc, content = _read_attachment_file(attachment, current=True)
        cache.delete_value(key)
        response = frappe.local.response
        response.type = "download"
        response.filename = str(_value(attachment, "original_filename") or "attachment").replace("\r", "").replace("\n", "")[:255]
        response.filecontent = content
        response.content_type = _value(attachment, "mime_type") or "application/octet-stream"
        response.display_content_as = "inline"
        return None
    finally:
        lock.release()
