"""Background jobs for one-record-at-a-time invoice recognition."""

from __future__ import annotations

import json
import uuid

import frappe

from rayher_hr_payroll.invoice_ocr import client, service

_QUEUED = "\u6392\u961f\u4e2d"
_PROCESSING = "\u8bc6\u522b\u4e2d"
_FAILED = "\u5931\u8d25"


def _safe_error(error: Exception) -> str:
    if isinstance(error, client.OCRServiceError):
        return str(error)[: service.MAX_ERROR_CHARS]
    if isinstance(error, getattr(frappe, "ValidationError", ())):
        message = str(error).strip()
        allowed = ("发票文件", "每个发票", "无法读取发票", "必须上传私有", "找不到已上传")
        if any(message.startswith(prefix) for prefix in allowed):
            return message[: service.MAX_ERROR_CHARS]
    return "发票识别失败，请稍后重试。"


def _serialized_payload(payload: dict) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(serialized.encode("utf-8")) > service.MAX_OCR_PAYLOAD_BYTES:
        raise client.OCRServiceError("OCR 服务返回无效结果，请稍后重试。")
    return serialized


def _save_success(record, payload: dict):
    if payload.get("file_sha256") != service._get(record, "file_sha256"):
        raise client.OCRServiceError("OCR 服务返回无效结果，请稍后重试。")
    fields = payload.get("fields") or {}
    normalized = service._normalized_fields(
        {field: fields.get(field) for field in service.EDITABLE_FIELDS}
    )
    for field, value in normalized.items():
        service._set(record, field, value)
    service._set(record, "ocr_payload", _serialized_payload(payload))
    service._set(
        record,
        "field_warnings",
        json.dumps(payload.get("warnings") or [], ensure_ascii=False, separators=(",", ":")),
    )
    service._set(record, "processing_error", "")
    service._set(record, "processing_started_on", None)
    service._set(record, "processing_claim_id", "")
    service._set(record, "duplicate_of", "")
    service._set(record, "duplicate_reason", "")
    # 修复（2026-09-28）：识别结果入库时按发票号码查重（老版发票含代码），日期、金额不参与。
    key, _duplicate = service._business_duplicate(record)
    if key:
        with service._transaction_lock("business", service._business_lock_key(record)):
            _, duplicate = service._business_duplicate(record, current=True)
            if duplicate:
                service._set(record, "recognition_status", "疑似重复")
                service._set(record, "duplicate_of", service._get(duplicate, "name"))
                service._set(record, "duplicate_reason", service.duplicate_reason(record, duplicate))
            else:
                service._set(record, "recognition_status", "待确认")
            service._save(record)
    else:
        service._set(record, "recognition_status", "待确认")
        service._save(record)


def recompute_invoice_batch(batch_name: str):
    """Commit batch counts, then refresh its request in a separate transaction."""
    try:
        batch = service.recompute_batch(str(batch_name))
        request_name = str(service._get(batch, "request") or "").strip()
        frappe.db.commit()
    except Exception:
        rollback = getattr(frappe.db, "rollback", None)
        if callable(rollback):
            rollback()
        raise
    if not request_name:
        return
    try:
        service.recompute_request_summary(request_name)
        frappe.db.commit()
    except Exception:
        rollback = getattr(frappe.db, "rollback", None)
        if callable(rollback):
            rollback()
        service._log_internal("Invoice OCR request summary aggregation failed")
        raise


def _recompute_safely(record):
    batch_name = str(service._get(record, "batch") or "")
    if not batch_name:
        return
    try:
        recompute_invoice_batch(batch_name)
    except Exception:
        service._log_internal("Invoice OCR batch aggregation failed")


def _claim_is_current(record, claim_id: str) -> bool:
    return (
        service._get(record, "recognition_status") == _PROCESSING
        and service._get(record, "processing_claim_id") == claim_id
    )


def _read_claimed_private_file(record, claim_id: str):
    file_url = service._safe_file_url(service._get(record, "invoice_file"))
    preliminary_file = service._file_doc(file_url)
    file_name = str(service._get(preliminary_file, "name") or "")
    with service._transaction_lock("file", file_name):
        current = service._current_doc(service.RECORD_DOCTYPE, service._get(record, "name"))
        if not _claim_is_current(current, claim_id):
            return current, None
        _file_doc, content = service._read_private_record(current, current=True)
        return current, content


def _save_failure(record, error: Exception):
    service._set(record, "recognition_status", _FAILED)
    service._set(record, "processing_error", _safe_error(error))
    service._set(record, "processing_started_on", None)
    service._set(record, "processing_claim_id", "")
    service._set(
        record,
        "retry_count",
        int(service._get(record, "retry_count") or 0) + 1,
    )
    service._save(record)


def recognize_invoice(invoice_name: str):
    """Recognize one queued record and fence late workers by a durable claim ID."""
    name = str(invoice_name)
    with service._lease_lock("record", name, timeout=600, blocking_timeout=15):
        record = service._current_doc(service.RECORD_DOCTYPE, name)
        if service._get(record, "recognition_status") != _QUEUED:
            return service._serialize_record(record)

        claim_id = uuid.uuid4().hex
        service._set(record, "recognition_status", _PROCESSING)
        service._set(record, "processing_error", "")
        service._set(record, "processing_started_on", service._now())
        service._set(record, "processing_claim_id", claim_id)
        service._save(record)
        # Persist the claim before the slow sidecar call. The Redis lease is only
        # an optimization; processing_claim_id is the durable fencing token.
        frappe.db.commit()
        _recompute_safely(record)

        payload = None
        outcome_error = None
        try:
            current, content = _read_claimed_private_file(record, claim_id)
            # Release the File/current-read transaction lock before OCR. A late
            # result is still fenced by the durable claim below.
            frappe.db.commit()
            if content is None:
                return service._serialize_record(current)
            payload = client.recognize_document(
                content,
                service._get(current, "original_filename"),
                service._get(current, "name"),
            )
        except Exception as error:
            outcome_error = error

        # SELECT ... FOR UPDATE is the final record lock. A retry/new worker may
        # have replaced the claim after this worker's Redis lease expired.
        current = service._current_doc(service.RECORD_DOCTYPE, name)
        if not _claim_is_current(current, claim_id):
            frappe.db.commit()
            return service._serialize_record(current)

        if outcome_error is not None:
            _save_failure(current, outcome_error)
        else:
            try:
                _save_success(current, payload)
            except Exception as error:
                _save_failure(current, error)

        # Commit the fenced terminal state before recomputing from committed rows.
        frappe.db.commit()
        _recompute_safely(current)
        return service._serialize_record(current)
