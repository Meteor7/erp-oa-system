"""Private supplemental attachments permanently owned by invoice records."""

from __future__ import annotations

import json
import secrets
from pathlib import PurePosixPath

import frappe

from rayher_hr_payroll import expense_attachments
from rayher_hr_payroll.invoice_ocr import service as invoice_service

ATTACHMENT_DOCTYPE = "OA Invoice Supplemental Attachment"
RECORD_DOCTYPE = "OA Invoice Record"
EDITABLE_STATUSES = {"待确认", "疑似重复", "已确认"}


def _throw(message):
    frappe.throw(frappe._(message))


def _value(source, field, default=None):
    if isinstance(source, dict):
        return source.get(field, default)
    return getattr(source, field, default)


def validate_record_mutability(record):
    if str(_value(record, "request") or "").strip():
        _throw("发票已经下推，请先撤回下推后再修改费用说明或附件。")
    if _value(record, "recognition_status") not in EDITABLE_STATUSES:
        _throw("当前发票状态不允许修改补充附件。")
    return record


def serialize_attachment(doc):
    return {
        "name": _value(doc, "name"),
        "invoice_record": _value(doc, "invoice_record"),
        "original_filename": _value(doc, "original_filename") or "",
        "mime_type": _value(doc, "mime_type") or "",
        "file_size": int(_value(doc, "file_size", 0) or 0),
        "uploaded_by": _value(doc, "uploaded_by") or "",
        "uploaded_on": _value(doc, "uploaded_on"),
    }


def _attachment_count(invoice_name):
    return int(
        frappe.db.count(
            ATTACHMENT_DOCTYPE, {"invoice_record": invoice_name}
        )
        or 0
    )


def _load_record(invoice_name, *, write=False, current=False):
    name = str(invoice_name or "").strip()
    if not name or len(name) > 140:
        _throw("发票标识无效。")
    return invoice_service._require_record(
        name, write=write, current=current
    )


def _read_attachment_file(attachment, current=False):
    file_url = invoice_service._safe_file_url(
        _value(attachment, "file_url")
    )
    file_doc = invoice_service._file_doc(file_url, current=current)
    if _value(file_doc, "name") != _value(attachment, "file"):
        _throw("补充附件文件关联无效。")
    if int(_value(file_doc, "is_private", 0) or 0) != 1:
        _throw("补充附件不再是私有文件。")
    if (
        _value(file_doc, "attached_to_doctype") != RECORD_DOCTYPE
        or _value(file_doc, "attached_to_name")
        != _value(attachment, "invoice_record")
    ):
        _throw("补充附件与发票关联无效。")
    content = invoice_service._read_limited(file_doc)
    metadata = expense_attachments.validate_attachment_content(
        _value(attachment, "original_filename"), content
    )
    if metadata["sha256"] != _value(attachment, "file_sha256"):
        _throw("补充附件内容已发生变化。")
    return file_doc, content


def list_attachments(invoice_name, current=False):
    record = _load_record(invoice_name, write=False, current=current)
    return list_attachments_for_record(record)


def list_attachments_for_record(record):
    rows = frappe.get_all(
        ATTACHMENT_DOCTYPE,
        filters={"invoice_record": _value(record, "name")},
        fields=["name"],
        order_by="creation asc",
        limit_page_length=100,
    )
    return [
        serialize_attachment(
            frappe.get_doc(ATTACHMENT_DOCTYPE, _value(row, "name"))
        )
        for row in rows
    ]


def register_attachment(invoice_name, file_url):
    invoice_name = str(invoice_name or "").strip()
    with invoice_service._transaction_lock(
        "invoice-supplemental-attachment", invoice_name, str(file_url or "")
    ):
        record = _load_record(invoice_name, write=True, current=True)
        validate_record_mutability(record)
        expense_attachments.validate_capacity(
            _attachment_count(invoice_name)
        )
        safe_url = invoice_service._safe_file_url(file_url)
        file_doc = invoice_service._file_doc(safe_url, current=True)
        expense_attachments.validate_file_registration(file_doc)
        content = invoice_service._read_limited(file_doc)
        metadata = expense_attachments.validate_attachment_content(
            _value(file_doc, "file_name")
            or PurePosixPath(safe_url).name,
            content,
        )
        if frappe.db.exists(
            ATTACHMENT_DOCTYPE, {"file": _value(file_doc, "name")}
        ):
            _throw("该文件已经登记为补充附件。")
        original_link = {
            "attached_to_doctype": _value(
                file_doc, "attached_to_doctype"
            )
            or "",
            "attached_to_name": _value(file_doc, "attached_to_name")
            or "",
            "attached_to_field": _value(file_doc, "attached_to_field")
            or "",
        }
        try:
            file_doc.attached_to_doctype = RECORD_DOCTYPE
            file_doc.attached_to_name = invoice_name
            file_doc.attached_to_field = "expense_description"
            file_doc.save(ignore_permissions=True)
            attachment = frappe.get_doc(
                {
                    "doctype": ATTACHMENT_DOCTYPE,
                    "invoice_record": invoice_name,
                    "file": _value(file_doc, "name"),
                    "file_url": safe_url,
                    "original_filename": metadata[
                        "original_filename"
                    ],
                    "mime_type": metadata["mime_type"],
                    "file_size": metadata["file_size"],
                    "file_sha256": metadata["sha256"],
                    "uploaded_by": invoice_service._user(),
                    "uploaded_on": invoice_service._now(),
                }
            )
            attachment.insert(ignore_permissions=True)
            return serialize_attachment(attachment)
        except BaseException:
            try:
                file_doc.attached_to_doctype = original_link[
                    "attached_to_doctype"
                ]
                file_doc.attached_to_name = original_link[
                    "attached_to_name"
                ]
                file_doc.attached_to_field = original_link[
                    "attached_to_field"
                ]
                file_doc.save(ignore_permissions=True)
                frappe.delete_doc(
                    "File",
                    _value(file_doc, "name"),
                    ignore_permissions=True,
                    force=True,
                )
            except BaseException:
                logger = getattr(frappe, "log_error", None)
                if callable(logger):
                    logger(
                        "Invoice supplemental attachment cleanup failed",
                        "Invoice supplemental attachment",
                    )
            raise


def delete_attachment(invoice_name, attachment_name):
    invoice_name = str(invoice_name or "").strip()
    attachment_name = str(attachment_name or "").strip()
    with invoice_service._transaction_lock(
        "invoice-supplemental-attachment",
        invoice_name,
        attachment_name,
    ):
        record = _load_record(invoice_name, write=True, current=True)
        validate_record_mutability(record)
        attachment = invoice_service._current_doc(
            ATTACHMENT_DOCTYPE, attachment_name
        )
        if _value(attachment, "invoice_record") != invoice_name:
            _throw("补充附件不属于该发票。")
        file_doc, _content = _read_attachment_file(
            attachment, current=True
        )
        frappe.delete_doc(
            ATTACHMENT_DOCTYPE,
            attachment_name,
            ignore_permissions=True,
            force=True,
        )
        frappe.delete_doc(
            "File",
            _value(file_doc, "name"),
            ignore_permissions=True,
            force=True,
        )
        return {
            "deleted": attachment_name,
            "invoice_record": invoice_name,
        }


def _preview_cache_key(token):
    return invoice_service._lock_key(
        "invoice-supplement-preview-token", token
    )


def preview_attachment(attachment_name):
    attachment = frappe.get_doc(
        ATTACHMENT_DOCTYPE, str(attachment_name or "").strip()
    )
    _load_record(
        _value(attachment, "invoice_record"),
        write=False,
        current=True,
    )
    _file_doc, _content = _read_attachment_file(
        attachment, current=True
    )
    token = secrets.token_urlsafe(32)
    frappe.cache().set_value(
        _preview_cache_key(token),
        json.dumps(
            {
                "user": invoice_service._user(),
                "attachment": _value(attachment, "name"),
            },
            separators=(",", ":"),
        ),
        expires_in_sec=invoice_service.PREVIEW_TOKEN_TTL_SECONDS,
    )
    return {
        "token": token,
        "preview_method": "POST",
        "preview_url": (
            "/api/method/rayher_hr_payroll.api.invoice_entry."
            "serve_supplemental_attachment_preview"
        ),
        "mime_type": _value(attachment, "mime_type"),
        "display_name": _value(attachment, "original_filename"),
    }


def serve_attachment_preview(token):
    user = invoice_service._user()
    token = str(token or "").strip()
    if len(token) < 32 or len(token) > 200 or "\x00" in token:
        _throw("补充附件预览凭证无效或已过期。")
    cache = frappe.cache()
    key = _preview_cache_key(token)
    lock = cache.lock(
        invoice_service._lock_key(
            "invoice-supplement-preview-consume", token
        ),
        timeout=invoice_service.PREVIEW_TOKEN_TTL_SECONDS,
        blocking_timeout=5,
    )
    if not lock.acquire(blocking=True, blocking_timeout=5):
        _throw("补充附件预览繁忙，请重试。")
    try:
        raw = cache.get_value(key)
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            payload = None
        if (
            not isinstance(payload, dict)
            or not payload.get("attachment")
            or payload.get("user") != user
        ):
            _throw("补充附件预览凭证无效或已过期。")
        attachment = invoice_service._current_doc(
            ATTACHMENT_DOCTYPE, str(payload["attachment"])
        )
        _load_record(
            _value(attachment, "invoice_record"),
            write=False,
            current=True,
        )
        _file_doc, content = _read_attachment_file(
            attachment, current=True
        )
        cache.delete_value(key)
        response = frappe.local.response
        response.type = "download"
        response.filename = (
            str(
                _value(attachment, "original_filename")
                or "attachment"
            )
            .replace("\r", "")
            .replace("\n", "")[:255]
        )
        response.filecontent = content
        response.content_type = (
            _value(attachment, "mime_type")
            or "application/octet-stream"
        )
        response.display_content_as = "inline"
        return None
    finally:
        lock.release()
