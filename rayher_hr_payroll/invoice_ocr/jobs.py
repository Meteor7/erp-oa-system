"""Background jobs for one-record-at-a-time invoice recognition."""

from __future__ import annotations

import json

import frappe

from rayher_hr_payroll.invoice_ocr import client, service


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
    service._set(record, "duplicate_of", "")
    service._set(record, "duplicate_reason", "")
    key, _duplicate = service._business_duplicate(record)
    if key:
        with service._transaction_lock("business", key):
            _, duplicate = service._business_duplicate(record, current=True)
            if duplicate:
                service._set(record, "recognition_status", "疑似重复")
                service._set(record, "duplicate_of", service._get(duplicate, "name"))
                service._set(
                    record,
                    "duplicate_reason",
                    "发票号码、开票日期和合计金额与已确认发票相同",
                )
            else:
                service._set(record, "recognition_status", "待确认")
            service._save(record)
    else:
        service._set(record, "recognition_status", "待确认")
        service._save(record)


def recompute_invoice_batch(batch_name: str):
    """Run one independently retryable aggregate transaction."""
    try:
        service.recompute_batch(str(batch_name))
        frappe.db.commit()
    except Exception:
        rollback = getattr(frappe.db, "rollback", None)
        if callable(rollback):
            rollback()
        raise


def _recompute_safely(record):
    batch_name = str(service._get(record, "batch") or "")
    if not batch_name:
        return
    try:
        recompute_invoice_batch(batch_name)
    except Exception:
        service._log_internal("Invoice OCR batch aggregation failed")


def recognize_invoice(invoice_name: str):
    """Recognize one queued record under a long site-scoped record lease."""
    name = str(invoice_name)
    with service._lease_lock("record", name, timeout=600, blocking_timeout=15):
        record = service._current_doc(service.RECORD_DOCTYPE, name)
        if service._get(record, "recognition_status") != "排队中":
            return service._serialize_record(record)

        service._set(record, "recognition_status", "识别中")
        service._set(record, "processing_error", "")
        service._set(record, "processing_started_on", service._now())
        service._save(record)
        # This is a top-level worker transaction boundary. It makes the claim
        # recoverable before a slow/OOM-prone OCR call while the Redis lease
        # remains held independently across the network operation.
        frappe.db.commit()
        _recompute_safely(record)

        try:
            _file_doc, content = service._read_private_record(record)
            payload = client.recognize_document(
                content,
                service._get(record, "original_filename"),
                service._get(record, "name"),
            )
            _save_success(record, payload)
        except Exception as error:
            service._set(record, "recognition_status", "失败")
            service._set(record, "processing_error", _safe_error(error))
            service._set(record, "processing_started_on", None)
            service._set(
                record,
                "retry_count",
                int(service._get(record, "retry_count") or 0) + 1,
            )
            service._save(record)

        # A background worker owns this top-level transaction boundary. Commit
        # the terminal record/business-key reservation before recomputing the
        # aggregate from committed rows in a separate transaction.
        frappe.db.commit()
        _recompute_safely(record)
        return service._serialize_record(record)
