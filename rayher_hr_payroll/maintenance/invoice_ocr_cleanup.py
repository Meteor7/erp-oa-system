"""Conservative, recoverable retention cleanup for unlinked invoice OCR uploads."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
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
    root = Path(
        os.path.abspath(
            os.fspath(frappe.get_site_path("private", "files"))
        )
    )
    current = Path(root.anchor)
    try:
        for component in root.parts[1:]:
            current /= component
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise OSError("symbolic link in private files root")
        if not stat.S_ISDIR(root.lstat().st_mode):
            raise OSError("private files root is not a directory")
    except OSError as error:
        raise CleanupFatalError(
            "unsafe private files root for invoice cleanup"
        ) from error
    return root


def _leaf_state(path: Path) -> str:
    """Return a lexical leaf state without following symbolic links."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "invalid"
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    if stat.S_ISREG(metadata.st_mode):
        return "regular"
    return "other"


def _private_path(file_doc, file_url: str) -> Path | None:
    if not file_url.startswith(_PRIVATE_PREFIX):
        return None
    tail = file_url[len(_PRIVATE_PREFIX):]
    if not tail or PurePosixPath(tail).name != tail or tail in {".", ".."}:
        return None
    root = _private_root()
    expected = root / tail
    try:
        actual = Path(os.path.abspath(os.fspath(file_doc.get_full_path())))
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if expected != actual or actual.parent != root:
        return None
    if _leaf_state(actual) == "symlink":
        return None
    return actual


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


_JOURNAL_PREFIX = "__invoice_ocr_cleanup_journal__"
_JOURNAL_PATTERN = re.compile(
    rf"{re.escape(_JOURNAL_PREFIX)}(?P<journal_id>[0-9a-f]{{48}})\.json"
)
_JOURNAL_KIND = "rayher.invoice_ocr.cleanup.v1"
_JOURNAL_VERSION = 1
_JOURNAL_MAX_BYTES = 16 * 1024
_JOURNAL_ENVELOPE_KEYS = {"payload", "signature"}
_JOURNAL_KEYS = {
    "version", "kind", "journal_id", "file_id", "record_id", "batch_id",
    "original_basename", "original_file_name", "original_file_url",
    "original_owner", "tombstone_basename", "tombstone_file_url",
}


class CleanupFatalError(RuntimeError):
    """Stop cleanup when the database transaction state is unknown."""


def _journal_hmac_key() -> bytes:
    """Return the current site's secret or fail closed without logging it."""
    local = getattr(frappe, "local", None)
    configuration = getattr(local, "conf", None)
    if configuration is None:
        getter = getattr(frappe, "get_conf", None)
        configuration = getter() if callable(getter) else None
    key = _value(configuration, "encryption_key") if configuration else None
    if isinstance(key, bytes):
        encoded = key
    else:
        value = str(key or "").strip()
        encoded = value.encode("utf-8") if value else b""
    if len(encoded) < 16:
        raise CleanupFatalError(
            "site encryption key unavailable for invoice cleanup"
        )
    return encoded


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _signed_journal_bytes(payload) -> bytes:
    canonical_payload = _canonical_json(payload)
    signature = hmac.new(
        _journal_hmac_key(),
        canonical_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return _canonical_json(
        {"payload": canonical_payload, "signature": signature}
    ).encode("utf-8")


def _rollback_or_fatal(subject: str):
    rollback = getattr(frappe.db, "rollback", None)
    if not callable(rollback):
        raise CleanupFatalError(
            f"invoice cleanup rollback unavailable for {subject}"
        )
    try:
        rollback()
    except Exception as error:
        _log(f"database rollback failed ({type(error).__name__})", subject)
        raise CleanupFatalError(
            f"invoice cleanup rollback failed for {subject}"
        ) from error


def _install_commit_sentinel():
    state = {"sql_committed": False}
    callbacks = getattr(frappe.db, "after_commit", None)
    add = getattr(callbacks, "add", None)
    if not callable(add):
        raise CleanupFatalError("Frappe after_commit callback queue unavailable")

    def mark_sql_committed():
        state["sql_committed"] = True

    add(mark_sql_committed)
    return state


def _record_signature(records):
    return sorted(
        (
            str(_value(row, "name") or ""),
            str(_value(row, "invoice_file") or ""),
            str(_value(row, "file_sha256") or ""),
        )
        for row in records
    )


def _preliminary_snapshot(batch_name: str):
    records = list(
        frappe.get_all(
            RECORD_DOCTYPE,
            filters={"batch": batch_name},
            fields=["name", "invoice_file", "file_sha256"],
            order_by="name asc",
        )
        or []
    )
    signature = _record_signature(records)
    record_names = [name for name, _url, _digest in signature]
    if len(record_names) != len(set(record_names)):
        return None
    file_names = []
    for _record_name, file_url, digest in signature:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return None
        file_rows = list(
            frappe.get_all(
                FILE_DOCTYPE,
                filters={"file_url": file_url},
                fields=["name"],
                order_by="name asc",
            )
            or []
        )
        if len(file_rows) != 1:
            return None
        file_names.append(str(_value(file_rows[0], "name") or ""))
    if not all(file_names) or len(file_names) != len(set(file_names)):
        return None
    return {
        "signature": signature,
        "record_names": sorted(record_names),
        "file_names": sorted(file_names),
        "digests": sorted({digest for _name, _url, digest in signature}),
    }


def _owned_files(records, expected_file_names):
    owned = []
    actual_file_names = []
    for record in records:
        record_name = str(_value(record, "name") or "")
        file_url = str(_value(record, "invoice_file") or "")
        file_rows = _rows_for_update(
            FILE_DOCTYPE, {"file_url": file_url}, _FILE_FIELDS,
        )
        references = _rows_for_update(
            RECORD_DOCTYPE, {"invoice_file": file_url}, ["name"],
        )
        if (
            len(file_rows) != 1
            or len(references) != 1
            or str(_value(references[0], "name")) != record_name
        ):
            return None
        row = file_rows[0]
        file_id = str(_value(row, "name") or "")
        actual_file_names.append(file_id)
        if (
            int(_value(row, "is_private") or 0) != 1
            or str(_value(row, "attached_to_doctype") or "")
            != RECORD_DOCTYPE
            or str(_value(row, "attached_to_name") or "") != record_name
            or str(_value(row, "attached_to_field") or "") != "invoice_file"
        ):
            return None
        file_doc = frappe.get_doc(FILE_DOCTYPE, file_id, for_update=True)
        path = _private_path(file_doc, file_url)
        if path is None or _leaf_state(path) != "regular":
            return None
        owned.append(
            {
                "file_id": file_id,
                "file_doc": file_doc,
                "record_id": record_name,
                "original_path": path,
                "original_basename": path.name,
                "original_file_name": str(_value(row, "file_name") or ""),
                "original_file_url": file_url,
                "original_owner": str(_value(row, "owner") or ""),
            }
        )
    if sorted(actual_file_names) != sorted(expected_file_names):
        return None
    return owned


def _record_deletion_order(records):
    remaining = {str(_value(record, "name")): record for record in records}
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


def _fsync_directory(directory: Path):
    if os.name == "nt":
        return
    descriptor = os.open(
        str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _valid_identifier(value, maximum=200) -> bool:
    text = str(value or "")
    return bool(
        text and len(text) <= maximum and text == text.strip()
        and "\x00" not in text and "/" not in text and "\\" not in text
    )


def _journal_payload(owned, batch_name: str):
    journal_id = secrets.token_hex(24)
    tombstone_basename = f"{_TOMBSTONE_PREFIX}{journal_id}.pending"
    payload = {
        "version": _JOURNAL_VERSION,
        "kind": _JOURNAL_KIND,
        "journal_id": journal_id,
        "file_id": owned["file_id"],
        "record_id": owned["record_id"],
        "batch_id": batch_name,
        "original_basename": owned["original_basename"],
        "original_file_name": owned["original_file_name"],
        "original_file_url": owned["original_file_url"],
        "original_owner": owned["original_owner"],
        "tombstone_basename": tombstone_basename,
        "tombstone_file_url": f"{_PRIVATE_PREFIX}{tombstone_basename}",
    }
    journal_path = _private_root() / (
        f"{_JOURNAL_PREFIX}{journal_id}.json"
    )
    return payload, journal_path


def _write_journal(payload, journal_path: Path):
    root = _private_root()
    if journal_path.parent != root or not _JOURNAL_PATTERN.fullmatch(
        journal_path.name
    ):
        raise RuntimeError("invalid invoice cleanup journal path")
    if _leaf_state(journal_path) != "missing":
        raise RuntimeError("invoice cleanup journal path already exists")
    serialized = _signed_journal_bytes(payload)
    if len(serialized) > _JOURNAL_MAX_BYTES:
        raise RuntimeError("invoice cleanup journal is too large")
    temporary = root / f".{journal_path.name}.{secrets.token_hex(12)}.tmp"
    descriptor = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(str(temporary), flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        if (
            _leaf_state(journal_path) != "missing"
            or _leaf_state(temporary) != "regular"
        ):
            raise RuntimeError("invoice cleanup journal path changed")
        os.replace(temporary, journal_path)
        _fsync_directory(root)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            if _leaf_state(temporary) == "regular":
                temporary.unlink()
        except OSError:
            pass


def _stage_files(owned_files, batch_name: str, journal_paths):
    root = _private_root()
    for owned in owned_files:
        payload, journal_path = _journal_payload(owned, batch_name)
        _write_journal(payload, journal_path)
        journal_paths.append(journal_path)
        tombstone_path = root / payload["tombstone_basename"]
        if (
            owned["original_path"].parent != root
            or _leaf_state(owned["original_path"]) != "regular"
            or _leaf_state(tombstone_path) != "missing"
        ):
            raise RuntimeError("invoice cleanup managed path is unsafe")
        os.replace(owned["original_path"], tombstone_path)
        _fsync_directory(root)
        file_doc = owned["file_doc"]
        _set_value(file_doc, "file_name", payload["tombstone_basename"])
        _set_value(file_doc, "file_url", payload["tombstone_file_url"])
        _set_value(file_doc, "is_private", 1)
        _set_value(file_doc, "owner", "Administrator")
        _set_value(file_doc, "attached_to_doctype", "")
        _set_value(file_doc, "attached_to_name", "")
        _set_value(file_doc, "attached_to_field", "")
        file_doc.save(ignore_permissions=True)


def _validated_journal(journal_path: Path):
    root = _private_root()
    match = _JOURNAL_PATTERN.fullmatch(journal_path.name)
    if (
        journal_path.parent != root
        or not match
        or _leaf_state(journal_path) != "regular"
    ):
        return None
    try:
        raw = journal_path.read_bytes()
        if not raw or len(raw) > _JOURNAL_MAX_BYTES:
            return None
        envelope = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    if (
        not isinstance(envelope, dict)
        or set(envelope) != _JOURNAL_ENVELOPE_KEYS
        or not isinstance(envelope.get("payload"), str)
        or not isinstance(envelope.get("signature"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", envelope["signature"])
        or raw != _canonical_json(envelope).encode("utf-8")
    ):
        return None

    # Authenticate the opaque canonical payload before parsing any of its
    # identifiers or constructing/accessing paths from it.
    canonical_payload = envelope["payload"]
    expected_signature = hmac.new(
        _journal_hmac_key(),
        canonical_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, envelope["signature"]):
        return None
    try:
        payload = json.loads(canonical_payload)
    except (UnicodeError, ValueError, TypeError):
        return None
    if (
        not isinstance(payload, dict)
        or set(payload) != _JOURNAL_KEYS
        or canonical_payload != _canonical_json(payload)
    ):
        return None

    journal_id = str(payload.get("journal_id") or "")
    if (
        payload.get("version") != _JOURNAL_VERSION
        or payload.get("kind") != _JOURNAL_KIND
        or journal_id != match.group("journal_id")
    ):
        return None
    if not all(
        _valid_identifier(payload.get(field))
        for field in (
            "file_id", "record_id", "batch_id",
            "original_basename", "original_file_name",
        )
    ):
        return None
    owner = str(payload.get("original_owner") or "")
    if (
        not owner or len(owner) > 200 or "\x00" in owner
        or owner != owner.strip()
    ):
        return None
    original_basename = str(payload["original_basename"])
    tombstone_basename = str(payload["tombstone_basename"])
    if (
        PurePosixPath(original_basename).name != original_basename
        or tombstone_basename
        != f"{_TOMBSTONE_PREFIX}{journal_id}.pending"
        or not _TOMBSTONE_PATTERN.fullmatch(tombstone_basename)
        or payload.get("original_file_url")
        != f"{_PRIVATE_PREFIX}{original_basename}"
        or payload.get("tombstone_file_url")
        != f"{_PRIVATE_PREFIX}{tombstone_basename}"
    ):
        return None
    original_path = root / original_basename
    tombstone_path = root / tombstone_basename
    if (
        original_path.parent != root
        or tombstone_path.parent != root
        or original_path == tombstone_path
        or _leaf_state(original_path) == "symlink"
        or _leaf_state(tombstone_path) == "symlink"
    ):
        return None
    return {
        **payload,
        "journal_path": journal_path,
        "original_path": original_path,
        "tombstone_path": tombstone_path,
    }


def _matches_original_file(file_doc, journal) -> bool:
    return bool(
        str(_value(file_doc, "name") or "") == journal["file_id"]
        and str(_value(file_doc, "file_name") or "")
        == journal["original_file_name"]
        and str(_value(file_doc, "file_url") or "")
        == journal["original_file_url"]
        and int(_value(file_doc, "is_private") or 0) == 1
        and str(_value(file_doc, "owner") or "")
        == journal["original_owner"]
        and str(_value(file_doc, "attached_to_doctype") or "")
        == RECORD_DOCTYPE
        and str(_value(file_doc, "attached_to_name") or "")
        == journal["record_id"]
        and str(_value(file_doc, "attached_to_field") or "")
        == "invoice_file"
        and _private_path(file_doc, journal["original_file_url"])
        == journal["original_path"]
    )


def _matches_tombstone_file(file_doc, journal) -> bool:
    return bool(
        str(_value(file_doc, "name") or "") == journal["file_id"]
        and str(_value(file_doc, "file_name") or "")
        == journal["tombstone_basename"]
        and str(_value(file_doc, "file_url") or "")
        == journal["tombstone_file_url"]
        and int(_value(file_doc, "is_private") or 0) == 1
        and str(_value(file_doc, "owner") or "") == "Administrator"
        and not str(_value(file_doc, "attached_to_doctype") or "")
        and not str(_value(file_doc, "attached_to_name") or "")
        and not str(_value(file_doc, "attached_to_field") or "")
        and _private_path(file_doc, journal["tombstone_file_url"])
        == journal["tombstone_path"]
    )


def _remove_journal(journal_path: Path):
    root = _private_root()
    state = _leaf_state(journal_path)
    if journal_path.parent != root or state != "regular":
        raise OSError("refusing unsafe invoice cleanup journal unlink")
    journal_path.unlink()
    _fsync_directory(journal_path.parent)


def _unlink_tombstone(journal) -> bool:
    path = journal["tombstone_path"]
    try:
        state = _leaf_state(path)
        if path.parent != _private_root() or state in {
            "symlink", "other", "invalid",
        }:
            raise OSError("refusing unsafe invoice cleanup tombstone unlink")
        if state == "regular":
            path.unlink()
            _fsync_directory(path.parent)
        return True
    except OSError as error:
        _log(
            f"tombstone unlink will be retried ({type(error).__name__})",
            journal["file_id"],
        )
        return False


def _finish_journal(journal) -> bool:
    if not _unlink_tombstone(journal):
        return False
    try:
        _remove_journal(journal["journal_path"])
    except OSError as error:
        _log(
            f"journal removal will be retried ({type(error).__name__})",
            journal["file_id"],
        )
        return False
    return True


def _current_file_doc(file_id: str):
    rows = _rows_for_update(FILE_DOCTYPE, {"name": file_id}, ["name"])
    if len(rows) > 1:
        raise CleanupFatalError("duplicate File primary key during cleanup")
    if not rows:
        return None
    return frappe.get_doc(FILE_DOCTYPE, file_id, for_update=True)


def _reconcile_journal(journal_path: Path) -> bool:
    journal = _validated_journal(journal_path)
    if journal is None:
        _log("invalid cleanup journal ignored", journal_path.name)
        return False
    file_id = journal["file_id"]
    with _lease("file", file_id):
        journal_file_rows = _rows_for_update(
            FILE_DOCTYPE,
            {"file_url": f"{_PRIVATE_PREFIX}{journal_path.name}"},
            ["name", "owner"],
        )
        if journal_file_rows:
            _rollback_or_fatal(file_id)
            _log("user-tracked cleanup journal ignored", file_id)
            return False
        try:
            file_doc = _current_file_doc(file_id)
        except CleanupFatalError:
            raise
        except Exception as error:
            _rollback_or_fatal(file_id)
            _log(type(error).__name__, file_id)
            return False

        if file_doc is None:
            tombstone_rows = _rows_for_update(
                FILE_DOCTYPE,
                {"file_url": journal["tombstone_file_url"]},
                ["name"],
            )
            if tombstone_rows:
                _rollback_or_fatal(file_id)
                _log("tombstone is referenced by another File row", file_id)
                return False
            record_rows = _rows_for_update(
                RECORD_DOCTYPE,
                {"name": journal["record_id"]},
                ["name", "batch", "invoice_file"],
            )
            batch_rows = _rows_for_update(
                BATCH_DOCTYPE,
                {"name": journal["batch_id"]},
                ["name"],
            )
            if record_rows or batch_rows:
                _rollback_or_fatal(file_id)
                _log(
                    "business documents still exist while File metadata "
                    "is missing",
                    file_id,
                )
                return False
            _rollback_or_fatal(file_id)
            return _finish_journal(journal)

        if _matches_original_file(file_doc, journal):
            original = journal["original_path"]
            tombstone = journal["tombstone_path"]
            original_state = _leaf_state(original)
            tombstone_state = _leaf_state(tombstone)
            unsafe_states = {"symlink", "other", "invalid"}
            if (
                original_state in unsafe_states
                or tombstone_state in unsafe_states
            ):
                _rollback_or_fatal(file_id)
                _log("unsafe original or tombstone path", file_id)
                return False
            if original_state == "regular" and tombstone_state == "regular":
                _rollback_or_fatal(file_id)
                _log("ambiguous original and tombstone paths", file_id)
                return False
            try:
                if tombstone_state == "regular":
                    if (
                        _leaf_state(tombstone) != "regular"
                        or _leaf_state(original) != "missing"
                    ):
                        raise OSError("managed path changed during restore")
                    os.replace(tombstone, original)
                    _fsync_directory(original.parent)
                elif original_state != "regular":
                    _rollback_or_fatal(file_id)
                    _log("both original and tombstone paths are missing", file_id)
                    return False
            except OSError as error:
                _rollback_or_fatal(file_id)
                _log(
                    f"original path restore will be retried "
                    f"({type(error).__name__})",
                    file_id,
                )
                return False
            _rollback_or_fatal(file_id)
            try:
                _remove_journal(journal_path)
            except OSError as error:
                _log(
                    f"journal removal will be retried "
                    f"({type(error).__name__})",
                    file_id,
                )
                return False
            return True

        if not _matches_tombstone_file(file_doc, journal):
            _rollback_or_fatal(file_id)
            _log("File state does not match cleanup journal", file_id)
            return False

        try:
            frappe.delete_doc(
                FILE_DOCTYPE,
                file_id,
                ignore_permissions=True,
                delete_permanently=True,
            )
            frappe.db.commit()
        except Exception as error:
            _rollback_or_fatal(file_id)
            _log(
                f"File metadata deletion will be retried "
                f"({type(error).__name__})",
                file_id,
            )
            return False
        return _finish_journal(journal)


def _reconcile_journals():
    root = _private_root()
    for journal_path in sorted(
        root.glob(f"{_JOURNAL_PREFIX}*.json"),
        key=lambda path: path.name,
    ):
        _reconcile_journal(journal_path)


def cleanup_orphan_invoice_batches(retention_days: int = 7, now=None):
    """Clean expired invoice batches with locks and durable file journals.

    Redis locks are acquired Record -> Batch -> File -> file-hash before any
    target row is selected FOR UPDATE. A business-key lock is unnecessary:
    business duplicate targets are confirmed, and confirmed records are never
    eligible for cleanup.
    """
    if (
        isinstance(retention_days, bool)
        or not isinstance(retention_days, int)
        or retention_days < 0
    ):
        raise ValueError("retention_days must be a non-negative integer")
    # A site secret is mandatory even when there are currently no candidates:
    # unsigned journals must never trigger filesystem or database mutations.
    _journal_hmac_key()
    current = _now(now)
    cutoff = current - timedelta(days=retention_days)
    _reconcile_journals()

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
        preliminary = _preliminary_snapshot(batch_name)
        if preliminary is None:
            _rollback_or_fatal(batch_name)
            _log("preliminary file ownership is not exclusive", batch_name)
            continue

        journal_paths = []
        phase_one_committed = False
        commit_state = None
        try:
            with ExitStack() as locks:
                for record_name in preliminary["record_names"]:
                    locks.enter_context(_lease("record", record_name))
                locks.enter_context(_lease("batch", batch_name))
                for file_id in preliminary["file_names"]:
                    locks.enter_context(_lease("file", file_id))
                for digest in preliminary["digests"]:
                    locks.enter_context(_lease("file-hash", digest))

                batch = frappe.get_doc(
                    BATCH_DOCTYPE, batch_name, for_update=True,
                )
                records = _rows_for_update(
                    RECORD_DOCTYPE,
                    {"batch": batch_name},
                    _RECORD_FIELDS,
                )
                if _record_signature(records) != preliminary["signature"]:
                    raise RuntimeError("record set changed during cleanup")
                if not _record_set_is_safe(batch, records, cutoff, current):
                    inconsistent = not _aggregate_is_consistent(batch, records)
                    _rollback_or_fatal(batch_name)
                    if inconsistent:
                        _log(
                            "batch status or aggregate counts are inconsistent",
                            batch_name,
                        )
                    continue
                if _has_view_audit(records):
                    _rollback_or_fatal(batch_name)
                    _log("view audit exists", batch_name)
                    continue
                if _has_external_duplicate_reference(records):
                    _rollback_or_fatal(batch_name)
                    _log("external duplicate reference exists", batch_name)
                    continue
                owned_files = _owned_files(
                    records, preliminary["file_names"],
                )
                if owned_files is None:
                    _rollback_or_fatal(batch_name)
                    _log("private file ownership is not exclusive", batch_name)
                    continue

                # This is intentionally the first callback registered by the
                # mutation phase. Frappe runs after_commit FIFO after SQL COMMIT.
                commit_state = _install_commit_sentinel()
                _stage_files(owned_files, batch_name, journal_paths)
                _delete_business_docs(batch_name, records)
                try:
                    frappe.db.commit()
                except Exception as commit_error:
                    if commit_state["sql_committed"]:
                        phase_one_committed = True
                        _log(
                            "SQL committed before after_commit callback failed "
                            f"({type(commit_error).__name__})",
                            batch_name,
                        )
                    else:
                        raise
                else:
                    phase_one_committed = True
        except CleanupFatalError:
            raise
        except Exception as error:
            if commit_state and commit_state["sql_committed"]:
                phase_one_committed = True
            if not phase_one_committed:
                _rollback_or_fatal(batch_name)
                for journal_path in journal_paths:
                    _reconcile_journal(journal_path)
                _log(type(error).__name__, batch_name)
                continue

        if not phase_one_committed:
            raise CleanupFatalError(
                f"invoice cleanup commit state unknown for {batch_name}"
            )
        removed.append(batch_name)
        for journal_path in journal_paths:
            _reconcile_journal(journal_path)

    _reconcile_journals()
    return removed