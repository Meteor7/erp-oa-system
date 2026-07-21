"""Conservative, recoverable retention cleanup for unlinked invoice OCR uploads."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
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
    "name",
    "invoice_file",
    "file_sha256",
    "recognition_status",
    "confirmed_on",
    "request",
    "expense_line_key",
    "duplicate_of",
]
_FILE_FIELDS = [
    "name",
    "file_name",
    "file_url",
    "is_private",
    "owner",
    "attached_to_doctype",
    "attached_to_name",
    "attached_to_field",
]
_TOMBSTONE_PREFIX = "__invoice_ocr_cleanup__"
_TOMBSTONE_PATTERN = re.compile(
    rf"{re.escape(_TOMBSTONE_PREFIX)}[0-9a-f]{{48}}\.pending"
)
_PRIVATE_PREFIX = "/private/files/"


def _value(doc, field, default=None):
    if hasattr(doc, "get"):
        return doc.get(field, default)
    return getattr(doc, field, default)


def _set_value(doc, field, value):
    setter = getattr(doc, "set", None)
    if callable(setter):
        setter(field, value)
    elif isinstance(doc, dict):
        doc[field] = value
    else:
        setattr(doc, field, value)


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


def _lock_key(category: str, *parts) -> str:
    serialized = json.dumps(
        parts,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    safe_category = "".join(
        character
        for character in str(category)
        if character.isalnum() or character in {"-", "_"}
    ) or "lock"
    return f"invoice:{_site_scope()}:{safe_category}:{digest}"


@contextmanager
def _lease(category: str, *parts):
    key = _lock_key(category, *parts)
    lock = frappe.cache().lock(key, timeout=600, blocking_timeout=15)
    if not lock.acquire(blocking=True, blocking_timeout=15):
        raise RuntimeError("invoice cleanup lock unavailable")
    try:
        yield
    finally:
        try:
            lock.release()
        except Exception:
            _log("lock release failed", str(parts[-1] if parts else category))


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


def _log(message: str, subject: str):
    logger = getattr(frappe, "log_error", None)
    if not callable(logger):
        return
    try:
        logger(
            f"Invoice OCR cleanup skipped {subject}: {message}",
            "Invoice OCR cleanup",
        )
    except Exception:
        pass


def _rollback():
    rollback = getattr(frappe.db, "rollback", None)
    if callable(rollback):
        rollback()


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
        all(
            int(_value(batch, field) or 0) == count
            for field, count in counts.items()
        )
        and str(_value(batch, "batch_status") or "")
        == _expected_batch_status(records)
    )


def _record_set_is_safe(batch, records, cutoff: datetime, current: datetime) -> bool:
    if not _is_expired(batch, cutoff, current):
        return False
    if any(
        str(_value(row, "recognition_status") or "")
        not in _SAFE_RECORD_STATUSES
        or _value(row, "confirmed_on")
        or str(_value(row, "request") or "").strip()
        or str(_value(row, "expense_line_key") or "").strip()
        or not re.fullmatch(r"[0-9a-f]{64}", str(_value(row, "file_sha256") or ""))
        for row in records
    ):
        return False
    return _aggregate_is_consistent(batch, records)


def _has_view_audit(records) -> bool:
    names = [str(_value(row, "name")) for row in records]
    urls = [str(_value(row, "invoice_file") or "") for row in records]
    if names and _rows_for_update(
        VIEW_LOG_DOCTYPE,
        {"invoice_record": ["in", names]},
        ["name"],
    ):
        return True
    return bool(
        urls
        and _rows_for_update(
            VIEW_LOG_DOCTYPE,
            {"invoice_file": ["in", urls]},
            ["name"],
        )
    )


def _private_root() -> Path:
    return Path(frappe.get_site_path("private", "files")).resolve()


def _private_path(file_doc, file_url: str) -> Path | None:
    if not file_url.startswith(_PRIVATE_PREFIX):
        return None
    tail = file_url[len(_PRIVATE_PREFIX):]
    if not tail or PurePosixPath(tail).name != tail or tail in {".", ".."}:
        return None
    root = _private_root()
    expected = (root / tail).resolve()
    try:
        actual = Path(file_doc.get_full_path()).resolve()
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if expected != actual or actual.parent != root:
        return None
    return actual


def _preliminary_file_names(records):
    names = []
    for record in records:
        file_url = str(_value(record, "invoice_file") or "")
        rows = _rows_for_update(
            FILE_DOCTYPE,
            {"file_url": file_url},
            ["name"],
        )
        if len(rows) != 1:
            return None
        names.append(str(_value(rows[0], "name") or ""))
    return names if all(names) and len(names) == len(set(names)) else None


def _owned_files(records):
    owned = []
    for record in records:
        record_name = str(_value(record, "name"))
        file_url = str(_value(record, "invoice_file") or "")
        file_rows = _rows_for_update(
            FILE_DOCTYPE,
            {"file_url": file_url},
            _FILE_FIELDS,
        )
        references = _rows_for_update(
            RECORD_DOCTYPE,
            {"invoice_file": file_url},
            ["name"],
        )
        if (
            len(file_rows) != 1
            or len(references) != 1
            or str(_value(references[0], "name")) != record_name
        ):
            return None
        row = file_rows[0]
        if (
            int(_value(row, "is_private") or 0) != 1
            or str(_value(row, "attached_to_doctype") or "")
            != RECORD_DOCTYPE
            or str(_value(row, "attached_to_name") or "") != record_name
            or str(_value(row, "attached_to_field") or "") != "invoice_file"
        ):
            return None
        file_name = str(_value(row, "name") or "")
        file_doc = frappe.get_doc(
            FILE_DOCTYPE,
            file_name,
            for_update=True,
        )
        path = _private_path(file_doc, file_url)
        if path is None or not path.is_file():
            return None
        owned.append(
            {
                "name": file_name,
                "doc": file_doc,
                "path": path,
            }
        )
    return owned


def _has_external_duplicate_reference(records) -> bool:
    targets = {str(_value(row, "name")) for row in records}
    if not targets:
        return False
    inbound = _rows_for_update(
        RECORD_DOCTYPE,
        {"duplicate_of": ["in", sorted(targets)]},
        ["name", "duplicate_of", "batch"],
    )
    return any(str(_value(row, "name")) not in targets for row in inbound)


def _new_tombstone_path() -> tuple[str, str, Path]:
    filename = f"{_TOMBSTONE_PREFIX}{secrets.token_hex(24)}.pending"
    file_url = f"{_PRIVATE_PREFIX}{filename}"
    return filename, file_url, _private_root() / filename


def _stage_files(owned_files, staged):
    for owned in owned_files:
        original_path = owned["path"]
        filename, file_url, tombstone_path = _new_tombstone_path()
        os.replace(original_path, tombstone_path)
        staged_item = {
            "name": owned["name"],
            "original_path": original_path,
            "tombstone_path": tombstone_path,
        }
        staged.append(staged_item)
        file_doc = owned["doc"]
        _set_value(file_doc, "file_name", filename)
        _set_value(file_doc, "file_url", file_url)
        _set_value(file_doc, "is_private", 1)
        _set_value(file_doc, "owner", "Administrator")
        _set_value(file_doc, "attached_to_doctype", "")
        _set_value(file_doc, "attached_to_name", "")
        _set_value(file_doc, "attached_to_field", "")
        file_doc.save(ignore_permissions=True)
    return staged


def _restore_staged_files(staged, subject: str):
    failures = []
    for item in reversed(staged):
        tombstone = item["tombstone_path"]
        original = item["original_path"]
        if not tombstone.exists():
            continue
        restored = False
        for _attempt in range(3):
            try:
                os.replace(tombstone, original)
                restored = True
                break
            except OSError:
                continue
        if not restored:
            failures.append(item["name"])
    if failures:
        _log(
            "rollback could not restore staged files: " + ",".join(failures),
            subject,
        )
        raise RuntimeError("invoice cleanup rollback restore failed")


def _record_deletion_order(records):
    remaining = {
        str(_value(record, "name")): record
        for record in records
    }
    ordered = []
    while remaining:
        inbound_targets = {
            str(_value(record, "duplicate_of") or "")
            for record in remaining.values()
            if str(_value(record, "duplicate_of") or "") in remaining
        }
        ready = sorted(set(remaining) - inbound_targets)
        if not ready:
            raise RuntimeError("cyclic duplicate references in cleanup batch")
        for name in ready:
            ordered.append(remaining.pop(name))
    return ordered


def _delete_business_docs(batch_name: str, records):
    for record in _record_deletion_order(records):
        frappe.delete_doc(
            RECORD_DOCTYPE,
            str(_value(record, "name")),
            ignore_permissions=True,
            delete_permanently=True,
        )
    frappe.delete_doc(
        BATCH_DOCTYPE,
        batch_name,
        ignore_permissions=True,
        delete_permanently=True,
    )


def _is_strict_tombstone(file_doc) -> bool:
    filename = str(_value(file_doc, "file_name") or "")
    file_url = str(_value(file_doc, "file_url") or "")
    return bool(
        _TOMBSTONE_PATTERN.fullmatch(filename)
        and file_url == f"{_PRIVATE_PREFIX}{filename}"
        and int(_value(file_doc, "is_private") or 0) == 1
        and str(_value(file_doc, "owner") or "") == "Administrator"
        and not str(_value(file_doc, "attached_to_doctype") or "")
        and not str(_value(file_doc, "attached_to_name") or "")
        and not str(_value(file_doc, "attached_to_field") or "")
        and _private_path(file_doc, file_url) is not None
    )


def _purge_tombstone_file(file_name: str, subject: str | None = None) -> bool:
    label = subject or file_name
    try:
        with _lease("file", file_name):
            file_doc = frappe.get_doc(
                FILE_DOCTYPE,
                file_name,
                for_update=True,
            )
            if not _is_strict_tombstone(file_doc):
                _rollback()
                return False
            frappe.delete_doc(
                FILE_DOCTYPE,
                file_name,
                ignore_permissions=True,
                delete_permanently=True,
            )
            frappe.db.commit()
            return True
    except Exception as error:
        try:
            _rollback()
        except Exception:
            pass
        _log(
            f"tombstone deletion will be retried ({type(error).__name__})",
            label,
        )
        return False


def _purge_tombstones():
    rows = frappe.get_all(
        FILE_DOCTYPE,
        filters={
            "is_private": 1,
            "file_url": ["like", f"{_PRIVATE_PREFIX}{_TOMBSTONE_PREFIX}%"],
        },
        fields=["name"],
        order_by="name asc",
    )
    for row in rows:
        file_name = str(_value(row, "name") or "")
        if file_name:
            _purge_tombstone_file(file_name)


def cleanup_orphan_invoice_batches(retention_days: int = 7, now=None):
    """Delete only expired, unaudited, unconfirmed and unlinked OCR batches.

    Lock order is Record -> Batch -> File -> file-hash.  The file-hash lock is
    exactly the lock used by register_file, so no new exact-file duplicate can
    appear between the inbound duplicate_of check and the phase-one commit.
    A business-key lock is unnecessary: business duplicate targets are always
    confirmed records, while this cleanup refuses every confirmed record.

    Physical files are atomically staged under strict private tombstone names.
    Their File rows remain as persistent retry indexes until Frappe's real
    delete_doc lifecycle commits.  A phase-one rollback restores every staged
    path; a process exit after phase one is recovered by the next scheduler run.
    """
    if (
        isinstance(retention_days, bool)
        or not isinstance(retention_days, int)
        or retention_days < 0
    ):
        raise ValueError("retention_days must be a non-negative integer")
    current = _now(now)
    cutoff = current - timedelta(days=retention_days)

    _purge_tombstones()

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
        staged = []
        phase_one_committed = False
        try:
            preliminary = frappe.get_all(
                RECORD_DOCTYPE,
                filters={"batch": batch_name},
                fields=["name"],
                order_by="name asc",
            )
            preliminary_names = sorted(
                str(_value(row, "name"))
                for row in preliminary
            )
            with ExitStack() as locks:
                for record_name in preliminary_names:
                    locks.enter_context(_lease("record", record_name))
                locks.enter_context(_lease("batch", batch_name))

                batch = frappe.get_doc(
                    BATCH_DOCTYPE,
                    batch_name,
                    for_update=True,
                )
                records = _rows_for_update(
                    RECORD_DOCTYPE,
                    {"batch": batch_name},
                    _RECORD_FIELDS,
                )
                if (
                    sorted(str(_value(row, "name")) for row in records)
                    != preliminary_names
                ):
                    raise RuntimeError("record set changed during cleanup")
                if not _record_set_is_safe(batch, records, cutoff, current):
                    inconsistent = not _aggregate_is_consistent(batch, records)
                    _rollback()
                    if inconsistent:
                        _log(
                            "batch status or aggregate counts are inconsistent",
                            batch_name,
                        )
                    continue
                if _has_view_audit(records):
                    _rollback()
                    _log("view audit exists", batch_name)
                    continue

                file_names = _preliminary_file_names(records)
                if file_names is None:
                    _rollback()
                    _log("private file ownership is not exclusive", batch_name)
                    continue
                for file_name in sorted(file_names):
                    locks.enter_context(_lease("file", file_name))

                digests = sorted(
                    {str(_value(row, "file_sha256")) for row in records}
                )
                for digest in digests:
                    locks.enter_context(_lease("file-hash", digest))

                if _has_external_duplicate_reference(records):
                    _rollback()
                    _log("external duplicate reference exists", batch_name)
                    continue

                owned_files = _owned_files(records)
                if owned_files is None:
                    _rollback()
                    _log("private file ownership is not exclusive", batch_name)
                    continue

                _stage_files(owned_files, staged)
                _delete_business_docs(batch_name, records)
                frappe.db.commit()
                phase_one_committed = True
        except Exception as error:
            restore_error = None
            if not phase_one_committed:
                try:
                    _rollback()
                except Exception as rollback_error:
                    _log(
                        f"database rollback failed ({type(rollback_error).__name__})",
                        batch_name,
                    )
                try:
                    _restore_staged_files(staged, batch_name)
                except Exception as recovery_error:
                    restore_error = recovery_error
            _log(type(error).__name__, batch_name)
            if restore_error is not None:
                raise restore_error
            continue

        removed.append(batch_name)
        for item in staged:
            _purge_tombstone_file(item["name"], batch_name)

    _purge_tombstones()
    return removed