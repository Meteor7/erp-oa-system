"""Conservative retention cleanup for unlinked invoice OCR uploads."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

import frappe

BATCH_DOCTYPE = "OA Invoice Import Batch"
RECORD_DOCTYPE = "OA Invoice Record"
VIEW_LOG_DOCTYPE = "OA Invoice View Log"
FILE_DOCTYPE = "File"

_WAITING_UPLOAD = "\u5f85\u4e0a\u4f20"
_PROCESSING = "\u5904\u7406\u4e2d"
_WAITING_CONFIRMATION = "\u5f85\u786e\u8ba4"
_COMPLETE = "\u5df2\u5b8c\u6210"
_PARTIAL_FAILURE = "\u90e8\u5206\u5931\u8d25"
_FAILURE = "\u5931\u8d25"

_QUEUED = "\u6392\u961f\u4e2d"
_RECOGNIZING = "\u8bc6\u522b\u4e2d"
_PENDING = "\u5f85\u786e\u8ba4"
_CONFIRMED = "\u5df2\u786e\u8ba4"
_DUPLICATE = "\u7591\u4f3c\u91cd\u590d"
_FAILED = "\u5931\u8d25"
_EXCLUDED = "\u5df2\u6392\u9664"

_SAFE_RECORD_STATUSES = {_PENDING, _DUPLICATE, _FAILED, _EXCLUDED}
_RECORD_FIELDS = [
    "name", "invoice_file", "recognition_status", "confirmed_on",
    "request", "expense_line_key",
]
_FILE_FIELDS = [
    "name", "file_url", "is_private", "attached_to_doctype",
    "attached_to_name", "attached_to_field",
]


def _value(doc, field, default=None):
    if hasattr(doc, "get"):
        return doc.get(field, default)
    return getattr(doc, field, default)


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _now(value=None) -> datetime:
    if value is not None:
        return _as_datetime(value)
    current = frappe.utils.now_datetime()
    return current if isinstance(current, datetime) else _as_datetime(current)


def _site_scope() -> str:
    site = str(getattr(getattr(frappe, "local", None), "site", "") or "default")
    return hashlib.sha256(site.encode("utf-8")).hexdigest()[:16]


@contextmanager
def _lease(category: str, name: str):
    serialized = json.dumps((name,), ensure_ascii=False, separators=(',', ':'), default=str)
    digest = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    key = f"invoice:{_site_scope()}:{category}:{digest}"
    lock = frappe.cache().lock(key, timeout=600, blocking_timeout=15)
    if not lock.acquire(blocking=True, blocking_timeout=15):
        raise RuntimeError("invoice cleanup lock unavailable")
    try:
        yield
    finally:
        try:
            lock.release()
        except Exception:
            _log("lock release failed", name)


def _rows_for_update(doctype, filters, fields):
    return list(
        frappe.db.get_values(
            doctype,
            filters=filters,
            fieldname=fields,
            as_dict=True,
            for_update=True,
        )
        or []
    )


def _log(message: str, batch_name: str):
    logger = getattr(frappe, "log_error", None)
    if not callable(logger):
        return
    try:
        logger(
            f"Invoice OCR cleanup skipped {batch_name}: {message}",
            "Invoice OCR cleanup",
        )
    except Exception:
        pass


def _is_expired(batch, cutoff: datetime, current: datetime) -> bool:
    try:
        return (
            not str(_value(batch, "request") or "").strip()
            and _as_datetime(_value(batch, "creation")) < cutoff
            and _as_datetime(_value(batch, "expires_on")) < current
        )
    except (TypeError, ValueError):
        return False


def _record_counts(records):
    statuses = [str(_value(row, "recognition_status") or "") for row in records]
    return {
        "total_count": len(records),
        "queued_count": statuses.count(_QUEUED),
        "processing_count": statuses.count(_RECOGNIZING),
        "pending_confirmation_count": statuses.count(_PENDING),
        "confirmed_count": statuses.count(_CONFIRMED),
        "duplicate_count": statuses.count(_DUPLICATE),
        "failed_count": statuses.count(_FAILED),
        "excluded_count": statuses.count(_EXCLUDED),
    }


def _expected_batch_status(records) -> str:
    counts = _record_counts(records)
    total = counts["total_count"]
    if not total:
        return _WAITING_UPLOAD
    if counts["queued_count"] or counts["processing_count"]:
        return _PROCESSING
    if counts["failed_count"]:
        return _FAILURE if counts["failed_count"] == total else _PARTIAL_FAILURE
    if counts["pending_confirmation_count"] or counts["duplicate_count"]:
        return _WAITING_CONFIRMATION
    if counts["confirmed_count"] + counts["excluded_count"] == total:
        return _COMPLETE
    return _PROCESSING

def _aggregate_is_consistent(batch, records) -> bool:
    counts = _record_counts(records)
    return (
        all(int(_value(batch, field) or 0) == count for field, count in counts.items())
        and str(_value(batch, "batch_status") or "") == _expected_batch_status(records)
    )


def _record_set_is_safe(batch, records, cutoff: datetime, current: datetime) -> bool:
    if not _is_expired(batch, cutoff, current):
        return False
    if any(
        str(_value(row, "recognition_status") or "") not in _SAFE_RECORD_STATUSES
        or _value(row, "confirmed_on")
        or str(_value(row, "request") or "").strip()
        or str(_value(row, "expense_line_key") or "").strip()
        for row in records
    ):
        return False
    return _aggregate_is_consistent(batch, records)


def _has_view_audit(records) -> bool:
    names = [str(_value(row, "name")) for row in records]
    urls = [str(_value(row, "invoice_file") or "") for row in records]
    if names and _rows_for_update(VIEW_LOG_DOCTYPE, {"invoice_record": ["in", names]}, ["name"]):
        return True
    return bool(urls and _rows_for_update(VIEW_LOG_DOCTYPE, {"invoice_file": ["in", urls]}, ["name"]))


def _private_path(file_doc, file_url: str) -> Path | None:
    prefix = "/private/files/"
    if not file_url.startswith(prefix):
        return None
    tail = file_url[len(prefix):]
    if not tail or PurePosixPath(tail).name != tail or tail in {".", ".."}:
        return None
    root = Path(frappe.get_site_path("private", "files")).resolve()
    expected = (root / tail).resolve()
    try:
        actual = Path(file_doc.get_full_path()).resolve()
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if expected != actual or actual.parent != root:
        return None
    return actual


def _owned_files(records):
    owned = []
    for record in records:
        record_name = str(_value(record, "name"))
        file_url = str(_value(record, "invoice_file") or "")
        file_rows = _rows_for_update(FILE_DOCTYPE, {"file_url": file_url}, _FILE_FIELDS)
        references = _rows_for_update(RECORD_DOCTYPE, {"invoice_file": file_url}, ["name"])
        if len(file_rows) != 1 or len(references) != 1 or str(_value(references[0], "name")) != record_name:
            return None
        row = file_rows[0]
        if (
            int(_value(row, "is_private") or 0) != 1
            or str(_value(row, "attached_to_doctype") or "") != RECORD_DOCTYPE
            or str(_value(row, "attached_to_name") or "") != record_name
            or str(_value(row, "attached_to_field") or "") != "invoice_file"
        ):
            return None
        file_doc = frappe.get_doc(FILE_DOCTYPE, str(_value(row, "name")), for_update=True)
        path = _private_path(file_doc, file_url)
        if path is None:
            return None
        owned.append((str(_value(row, "name")), path))
    return owned


def _delete_metadata(batch_name: str, records, owned_files):
    for file_name, _path in owned_files:
        frappe.db.delete(FILE_DOCTYPE, {"name": file_name})
    for record in records:
        frappe.db.delete(RECORD_DOCTYPE, {"name": str(_value(record, "name"))})
    frappe.db.delete(BATCH_DOCTYPE, {"name": batch_name})


def _unlink_after_commit(batch_name: str, owned_files):
    for _file_name, path in owned_files:
        try:
            if path.exists():
                os.remove(path)
        except OSError as error:
            _log(f"orphaned private file could not be removed ({type(error).__name__})", batch_name)


def cleanup_orphan_invoice_batches(retention_days: int = 7, now=None):
    """Delete only expired, unaudited, unconfirmed and unlinked OCR batches.

    Each candidate is re-read with database row locks while matching Redis
    record/batch locks are held in the same order as the business workflow.
    Unsafe or inconsistent candidates are skipped. Database metadata is
    committed before exact private paths are unlinked, so a database rollback
    can never restore a record whose physical file was removed.
    """
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 0:
        raise ValueError("retention_days must be a non-negative integer")
    days = retention_days
    current = _now(now)
    cutoff = current - timedelta(days=days)
    candidates = frappe.get_all(
        BATCH_DOCTYPE,
        filters={"creation": ["<", cutoff], "expires_on": ["<", current]},
        fields=["name"],
        order_by="creation asc, name asc",
    )
    removed = []
    for candidate in candidates:
        batch_name = str(_value(candidate, "name") or "")
        if not batch_name:
            continue
        try:
            preliminary = frappe.get_all(
                RECORD_DOCTYPE,
                filters={"batch": batch_name},
                fields=["name"],
                order_by="name asc",
            )
            preliminary_names = sorted(
                str(_value(row, "name")) for row in preliminary
            )
            with ExitStack() as locks:
                for record_name in preliminary_names:
                    locks.enter_context(_lease("record", record_name))
                locks.enter_context(_lease("batch", batch_name))
                batch = frappe.get_doc(BATCH_DOCTYPE, batch_name, for_update=True)
                records = _rows_for_update(
                    RECORD_DOCTYPE,
                    {"batch": batch_name},
                    _RECORD_FIELDS,
                )
                if sorted(str(_value(row, "name")) for row in records) != preliminary_names:
                    raise RuntimeError("record set changed during cleanup")
                if not _record_set_is_safe(batch, records, cutoff, current):
                    inconsistent = not _aggregate_is_consistent(batch, records)
                    frappe.db.rollback()
                    if inconsistent:
                        _log("batch status or aggregate counts are inconsistent", batch_name)
                    continue
                if _has_view_audit(records):
                    frappe.db.rollback()
                    _log("view audit exists", batch_name)
                    continue
                owned_files = _owned_files(records)
                if owned_files is None:
                    frappe.db.rollback()
                    _log("private file ownership is not exclusive", batch_name)
                    continue
                _delete_metadata(batch_name, records, owned_files)
                frappe.db.commit()
                removed.append(batch_name)
                _unlink_after_commit(batch_name, owned_files)
        except Exception as error:
            try:
                frappe.db.rollback()
            except Exception:
                pass
            _log(type(error).__name__, batch_name)
    return removed
