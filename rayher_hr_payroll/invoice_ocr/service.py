"""Server-owned workflow for invoice OCR batches and records."""

from __future__ import annotations

import hashlib
import json
import secrets
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

import frappe

from rayher_hr_payroll.invoice_ocr.domain import business_key
from rayher_hr_payroll.invoice_ocr import permissions as invoice_permissions
from rayher_hr_payroll.invoice_ocr.permissions import can_read_invoice

BATCH_DOCTYPE = "OA Invoice Import Batch"
RECORD_DOCTYPE = "OA Invoice Record"
VIEW_LOG_DOCTYPE = "OA Invoice View Log"
REQUEST_DOCTYPE = "OA Approval Request"
LINE_DOCTYPE = "OA Approval Expense Line"
MAX_BATCH_FILES = 20
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_OCR_PAYLOAD_BYTES = 1024 * 1024
MAX_ERROR_CHARS = 300
MAX_EDIT_PAYLOAD_BYTES = 32 * 1024
PROCESSING_STALE_SECONDS = 15 * 60
PREVIEW_TOKEN_TTL_SECONDS = 60
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
CANONICAL_MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
EDITABLE_FIELDS = {"invoice_category", "project_name", "issue_date", "invoice_number", "amount_before_tax", "tax_amount", "total_amount"}
FINANCE_ROLES = {"System Manager", "Accounts User"}
ACTIVE_REQUEST_STATUSES = {"草稿"}


def _throw(message: str):
    frappe.throw(message, frappe.ValidationError)


def _user() -> str:
    user = str(getattr(getattr(frappe, "session", None), "user", "") or "")
    if not user or user == "Guest":
        _throw("请先登录后再操作发票。")
    return user


def _roles(user=None) -> set[str]:
    user = user or _user()
    return set(frappe.get_roles(user) or [])


def _get(doc, field, default=None):
    if hasattr(doc, "get"):
        return doc.get(field, default)
    return getattr(doc, field, default)


def _set(doc, field, value):
    setattr(doc, field, value)


def _save(doc):
    return doc.save(ignore_permissions=True)


def _now():
    value = frappe.utils.now_datetime()
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _get_all(doctype, *, filters=None, fields=None, order_by=None, limit=None):
    kwargs = {"filters": filters or {}, "fields": fields or ["name"]}
    if order_by:
        kwargs["order_by"] = order_by
    if limit is not None:
        kwargs["limit_page_length"] = limit
    return list(frappe.get_all(doctype, **kwargs) or [])


def _current_doc(doctype, name):
    """Load a locking current read under MariaDB REPEATABLE READ."""
    return frappe.get_doc(doctype, name, for_update=True)


def _current_rows(doctype, *, filters=None, fields=None, order_by=None, limit=None):
    kwargs = {
        "filters": filters or {},
        "fieldname": fields or ["name"],
        "as_dict": True,
        "for_update": True,
    }
    if order_by:
        kwargs["order_by"] = order_by
    if limit is not None:
        kwargs["limit"] = limit
    return list(frappe.db.get_values(doctype, **kwargs) or [])


def _current_value(doctype, filters, fields):
    return frappe.db.get_value(
        doctype,
        filters,
        fields,
        as_dict=True,
        for_update=True,
    )


def _site_scope():
    site = str(getattr(getattr(frappe, "local", None), "site", "") or "default")
    return hashlib.sha256(site.encode("utf-8")).hexdigest()[:16]


def _lock_key(category: str, *parts) -> str:
    serialized = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    safe_category = "".join(character for character in str(category) if character.isalnum() or character in {"-", "_"}) or "lock"
    return f"invoice:{_site_scope()}:{safe_category}:{digest}"


def _release_transaction_lock(key, state):
    if state.get("released"):
        return
    state["released"] = True
    held = getattr(getattr(frappe, "local", None), "invoice_transaction_locks", {})
    held.pop(key, None)
    try:
        state["lock"].release()
    except Exception:
        logger = getattr(frappe, "log_error", None)
        if callable(logger):
            try:
                logger("Invoice OCR lock lease expired", "Invoice OCR lock release")
            except Exception:
                pass


@contextmanager
def _transaction_lock(category: str, *parts, timeout=600, blocking_timeout=15):
    key = _lock_key(category, *parts)
    local = getattr(frappe, "local", None)
    held = getattr(local, "invoice_transaction_locks", None)
    if held is None:
        held = {}
        setattr(local, "invoice_transaction_locks", held)
    if key in held:
        yield held[key]["lock"]
        return
    lock = frappe.cache().lock(key, timeout=timeout, blocking_timeout=blocking_timeout)
    if not lock.acquire(blocking=True, blocking_timeout=blocking_timeout):
        _throw("发票正在被其他操作处理，请稍后重试。")
    state = {"lock": lock, "released": False}
    held[key] = state
    release = lambda: _release_transaction_lock(key, state)
    frappe.db.after_commit.add(release)
    frappe.db.after_rollback.add(release)
    try:
        yield lock
    except BaseException:
        release()
        raise


def _can_write_record(record, user=None) -> bool:
    user = user or _user()
    roles = _roles(user)
    if user == "Administrator" or "System Manager" in roles or _get(record, "owner") == user:
        return True
    batch_name = str(_get(record, "batch") or "")
    if batch_name:
        try:
            batch = frappe.get_doc(BATCH_DOCTYPE, batch_name)
        except Exception:
            batch = None
        if batch and _get(batch, "owner") == user:
            return True
    request_name = str(_get(record, "request") or "")
    return bool(request_name and invoice_permissions.can_edit_request(request_name, user))

def _require_record(name: str, *, write=False, current=False):
    user = _user()
    record = _current_doc(RECORD_DOCTYPE, name) if current else frappe.get_doc(RECORD_DOCTYPE, name)
    allowed = _can_write_record(record, user) if write else can_read_invoice(record, user)
    if not allowed:
        _throw("您无权访问该发票记录。")
    return record


def _require_batch(name: str, *, owner_only=False, current=False):
    user = _user()
    batch = _current_doc(BATCH_DOCTYPE, name) if current else frappe.get_doc(BATCH_DOCTYPE, name)
    if owner_only:
        allowed = _get(batch, "owner") == user or user == "Administrator" or "System Manager" in _roles(user)
    else:
        allowed = can_read_invoice(batch, user)
    if not allowed:
        _throw("您无权访问该发票批次。")
    if _get(batch, "batch_status") == "已取消":
        _throw("该发票批次已取消。")
    expires_on = _get(batch, "expires_on")
    if expires_on:
        expiry = expires_on if isinstance(expires_on, datetime) else datetime.fromisoformat(str(expires_on))
        if expiry < _now() and not _get(batch, "request"):
            _throw("该临时发票批次已过期，请重新上传。")
    return batch


def create_batch():
    user = _user()
    doc = frappe.get_doc({
        "doctype": BATCH_DOCTYPE, "owner": user, "uploaded_by": user,
        "temporary_token": secrets.token_urlsafe(32), "batch_status": "待上传",
        "expires_on": _now() + timedelta(days=7), "total_count": 0,
        "queued_count": 0, "processing_count": 0, "pending_confirmation_count": 0,
        "confirmed_count": 0, "duplicate_count": 0, "failed_count": 0, "excluded_count": 0,
    })
    doc.insert(ignore_permissions=True)
    return _serialize_batch(doc)


def _safe_file_url(file_url) -> str:
    value = str(file_url or "")
    if len(value) > 500 or not value.startswith("/private/files/"):
        _throw("必须上传私有发票文件。")
    if "?" in value or "#" in value or "\\" in value:
        _throw("发票文件地址无效。")
    tail = value[len("/private/files/"):]
    if not tail or "/" in tail or tail in {".", ".."} or "%2f" in tail.lower() or "%5c" in tail.lower():
        _throw("发票文件地址无效。")
    return value


def _file_doc(file_url: str, *, current=False):
    name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not name:
        _throw("找不到已上传的发票文件。")
    file_doc = _current_doc("File", name) if current else frappe.get_doc("File", name)
    if _get(file_doc, "file_url") != file_url:
        _throw("发票文件关联已失效。")
    return file_doc


def _read_limited(file_doc) -> bytes:
    declared_size = _get(file_doc, "file_size")
    try:
        if declared_size is not None and int(declared_size) > MAX_FILE_BYTES:
            _throw("每个发票文件不能超过 10 MB。")
    except (TypeError, ValueError):
        pass
    try:
        with open(file_doc.get_full_path(), "rb") as stream:
            content = stream.read(MAX_FILE_BYTES + 1)
    except (OSError, TypeError, ValueError) as error:
        raise frappe.ValidationError("无法读取发票文件。") from error
    if len(content) > MAX_FILE_BYTES:
        _throw("每个发票文件不能超过 10 MB。")
    if not content:
        _throw("发票文件不能为空。")
    return content


def _validated_file(batch, file_doc, file_url: str):
    file_url = _safe_file_url(file_url)
    user = _user()
    if _get(file_doc, "file_url") != file_url:
        _throw("发票文件关联已失效。")
    if int(_get(file_doc, "is_private") or 0) != 1:
        _throw("发票文件必须为私有文件。")
    if _get(file_doc, "owner") != user and "System Manager" not in _roles(user):
        _throw("只能登记本人上传的发票文件。")
    attached_type = str(_get(file_doc, "attached_to_doctype") or "")
    attached_name = str(_get(file_doc, "attached_to_name") or "")
    if attached_type and (attached_type != BATCH_DOCTYPE or attached_name != _get(batch, "name")):
        _throw("该文件已附加到其他业务记录。")
    base_name = PurePosixPath(file_url).name
    url_extension = "." + base_name.rsplit(".", 1)[-1].lower() if "." in base_name else ""
    original = str(_get(file_doc, "file_name") or base_name)
    name_extension = "." + original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if url_extension not in ALLOWED_EXTENSIONS or name_extension != url_extension:
        _throw("仅支持 PDF、JPG、JPEG 或 PNG 发票文件。")
    content = _read_limited(file_doc)
    valid_signature = (
        (url_extension == ".pdf" and content.startswith(b"%PDF-"))
        or (url_extension in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff"))
        or (url_extension == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
    )
    if not valid_signature:
        _throw("发票文件内容与扩展名不匹配。")
    return file_doc, content, original, CANONICAL_MIME[url_extension]


def _first_duplicate(filters, *, exclude=None, current=False):
    filters = dict(filters)
    filters.setdefault("recognition_status", ["!=", "已排除"])
    reader = _current_rows if current else _get_all
    rows = reader(
        RECORD_DOCTYPE,
        filters=filters,
        fields=["name", "recognition_status", "request"],
        order_by="creation asc",
        limit=20,
    )
    for row in rows:
        if _get(row, "name") != exclude:
            return row
    return None


@contextmanager
def _trusted_file_controller_values():
    form_dict = getattr(frappe, "form_dict", None)
    marker = object()
    if isinstance(form_dict, dict):
        previous = form_dict.pop("file_size", marker)
        restore = lambda: form_dict.__setitem__("file_size", previous) if previous is not marker else None
    else:
        previous = getattr(form_dict, "file_size", marker) if form_dict is not None else marker
        if form_dict is not None and previous is not marker:
            delattr(form_dict, "file_size")
        restore = lambda: setattr(form_dict, "file_size", previous) if form_dict is not None and previous is not marker else None
    try:
        yield
    finally:
        restore()


def _attach_file(file_doc, record, trusted_size):
    _set(file_doc, "is_private", 1)
    _set(file_doc, "file_size", trusted_size)
    _set(file_doc, "attached_to_doctype", RECORD_DOCTYPE)
    _set(file_doc, "attached_to_name", _get(record, "name"))
    _set(file_doc, "attached_to_field", "invoice_file")
    with _trusted_file_controller_values():
        _save(file_doc)

ENQUEUE_FAILURE_MESSAGE = "发票识别任务入队失败，请重试。"


def _log_internal(title):
    logger = getattr(frappe, "log_error", None)
    if callable(logger):
        try:
            logger(title, title)
        except Exception:
            pass


@contextmanager
def _lease_lock(category: str, *parts, timeout=600, blocking_timeout=15):
    lock = frappe.cache().lock(
        _lock_key(category, *parts),
        timeout=timeout,
        blocking_timeout=blocking_timeout,
    )
    if not lock.acquire(blocking=True, blocking_timeout=blocking_timeout):
        _throw("发票正在被其他操作处理，请稍后重试。")
    try:
        yield lock
    finally:
        try:
            lock.release()
        except Exception:
            _log_internal("Invoice OCR lock lease expired")


def _mark_enqueue_failure(invoice_name):
    try:
        with _transaction_lock("record", invoice_name):
            record = frappe.get_doc(RECORD_DOCTYPE, invoice_name)
            if _get(record, "recognition_status") == "排队中":
                _set(record, "recognition_status", "失败")
                _set(record, "processing_error", ENQUEUE_FAILURE_MESSAGE)
                _set(record, "processing_started_on", None)
                _save(record)
                _recompute_record_batch(record)
        frappe.db.commit()
    except Exception:
        rollback = getattr(frappe.db, "rollback", None)
        if callable(rollback):
            rollback()
        _log_internal("Invoice OCR enqueue recovery failed")


def _dispatch_recognition(invoice_name):
    try:
        frappe.enqueue(
            "rayher_hr_payroll.invoice_ocr.jobs.recognize_invoice",
            invoice_name=invoice_name,
            queue="long",
        )
    except Exception:
        _mark_enqueue_failure(invoice_name)


def _enqueue_recognition_after_commit(invoice_name):
    frappe.db.after_commit.add(lambda: _dispatch_recognition(invoice_name))


def _recompute_batch_after_commit(batch_name):
    local = getattr(frappe, "local", None)
    pending = getattr(local, "invoice_batch_recomputes", None)
    if pending is None:
        pending = set()
        setattr(local, "invoice_batch_recomputes", pending)
    if batch_name in pending:
        return
    pending.add(batch_name)

    def run():
        pending.discard(batch_name)
        try:
            recompute_batch(batch_name)
            frappe.db.commit()
        except Exception:
            rollback = getattr(frappe.db, "rollback", None)
            if callable(rollback):
                rollback()
            _log_internal("Invoice OCR batch aggregation failed")
            try:
                frappe.enqueue(
                    "rayher_hr_payroll.invoice_ocr.jobs.recompute_invoice_batch",
                    batch_name=batch_name,
                    queue="short",
                )
            except Exception:
                _log_internal("Invoice OCR batch aggregation retry enqueue failed")

    frappe.db.after_commit.add(run)


def _recompute_record_batch(record):
    batch_name = str(_get(record, "batch") or "")
    if batch_name:
        _recompute_batch_after_commit(batch_name)


def register_file(batch, file_url):
    batch_name = str(batch)
    file_url = _safe_file_url(file_url)
    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        _throw("找不到已上传的发票文件。")
    with _transaction_lock("batch", batch_name):
        batch_doc = _require_batch(batch_name, owner_only=True, current=True)
        with _transaction_lock("file", file_name):
            file_doc = _current_doc("File", file_name)
            file_doc, content, server_name, server_mime = _validated_file(batch_doc, file_doc, file_url)
            digest = hashlib.sha256(content).hexdigest()
            with _transaction_lock("file-hash", digest):
                count = len(_current_rows(RECORD_DOCTYPE, filters={"batch": batch_name}, fields=["name"]))
                if count >= MAX_BATCH_FILES:
                    _throw("每批最多上传 20 张发票。")
                user = _user()
                duplicate = _first_duplicate({"file_sha256": digest}, current=True)
                record = frappe.get_doc({
                    "doctype": RECORD_DOCTYPE, "owner": user, "batch": batch_name,
                    "invoice_file": _get(file_doc, "file_url"), "original_filename": server_name,
                    "mime_type": server_mime, "file_size": len(content), "file_sha256": digest,
                    "uploaded_by": user, "recognition_status": "疑似重复" if duplicate else "排队中",
                    "duplicate_of": _get(duplicate, "name") if duplicate else "",
                    "duplicate_reason": "文件内容与已有发票完全相同" if duplicate else "", "retry_count": 0,
                })
                record.insert(ignore_permissions=True)
                _attach_file(file_doc, record, len(content))
                _recompute_batch_after_commit(batch_name)
                if not duplicate:
                    _enqueue_recognition_after_commit(_get(record, "name"))
    return _serialize_record(record)

def _batch_status(current, counts):
    if current == "已取消": return "已取消"
    total = counts["total_count"]
    if total == 0: return "待上传"
    if counts["queued_count"] or counts["processing_count"]: return "处理中"
    if counts["failed_count"]:
        return "失败" if counts["failed_count"] == total else "部分失败"
    if counts["pending_confirmation_count"] or counts["duplicate_count"]: return "待确认"
    if counts["confirmed_count"] + counts["excluded_count"] == total: return "已完成"
    return "处理中"


def recompute_batch(batch_name: str):
    with _transaction_lock("batch", batch_name):
        batch = _current_doc(BATCH_DOCTYPE, batch_name)
        rows = _current_rows(
            RECORD_DOCTYPE,
            filters={"batch": batch_name},
            fields=["recognition_status", "processing_error"],
        )
        statuses = [str(_get(row, "recognition_status") or "") for row in rows]
        counts = {
            "total_count": len(statuses),
            "queued_count": statuses.count("排队中"),
            "processing_count": statuses.count("识别中"),
            "pending_confirmation_count": statuses.count("待确认"),
            "confirmed_count": statuses.count("已确认"),
            "duplicate_count": statuses.count("疑似重复"),
            "failed_count": statuses.count("失败"),
            "excluded_count": statuses.count("已排除"),
        }
        for field, value in counts.items():
            _set(batch, field, value)
        _set(batch, "batch_status", _batch_status(_get(batch, "batch_status"), counts))
        errors = [
            str(_get(row, "processing_error") or "")[:MAX_ERROR_CHARS]
            for row in rows
            if _get(row, "processing_error")
        ]
        _set(batch, "error_summary", "\n".join(errors[:20]))
        _save(batch)
        return batch



def _normalize_text(field, value):
    if value is None: return ""
    text = str(value).strip()
    if len(text) > {"invoice_category": 140, "project_name": 1000, "invoice_number": 100}[field]:
        _throw("发票字段内容过长，请检查后重试。")
    return text


def _normalize_date(value):
    if value is None or str(value).strip() == "": return None
    if isinstance(value, datetime): return value.date().isoformat()
    if isinstance(value, date): return value.isoformat()
    try: return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError: _throw("开票日期格式无效。")


def _normalize_money(value):
    if value is None or str(value).strip() == "": return None
    try: result = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError): _throw("发票金额格式无效。")
    if not result.is_finite() or result < 0 or result > Decimal("999999999999.99"):
        _throw("发票金额超出有效范围。")
    return result


def _normalized_fields(values):
    return {
        "invoice_category": _normalize_text("invoice_category", values.get("invoice_category")),
        "project_name": _normalize_text("project_name", values.get("project_name")),
        "issue_date": _normalize_date(values.get("issue_date")),
        "invoice_number": _normalize_text("invoice_number", values.get("invoice_number")),
        "amount_before_tax": _normalize_money(values.get("amount_before_tax")),
        "tax_amount": _normalize_money(values.get("tax_amount")),
        "total_amount": _normalize_money(values.get("total_amount")),
    }


def _parse_values(values, *, controlled_message="只能修改七项发票字段。"):
    if values is None:
        return {}
    if isinstance(values, str):
        if len(values.encode("utf-8")) > MAX_EDIT_PAYLOAD_BYTES:
            _throw("发票字段数据过长。")
        try:
            values = json.loads(values)
        except (TypeError, ValueError):
            _throw("发票字段数据格式无效。")
    if not isinstance(values, dict) or len(values) > len(EDITABLE_FIELDS):
        _throw("发票字段数据格式无效。")
    if any(not isinstance(key, str) for key in values):
        _throw("发票字段数据格式无效。")
    scalar_types = (str, int, float, bool, Decimal, date, datetime)
    if any(value is not None and not isinstance(value, scalar_types) for value in values.values()):
        _throw("发票字段数据格式无效。")
    try:
        encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    except (TypeError, ValueError):
        _throw("发票字段数据格式无效。")
    if len(encoded) > MAX_EDIT_PAYLOAD_BYTES:
        _throw("发票字段数据过长。")
    extras = set(values) - EDITABLE_FIELDS
    if extras:
        if extras & {"recognition_status", "duplicate_of", "duplicate_reason"}:
            _throw("重复状态只能由服务端更新。")
        _throw(controlled_message)
    return dict(values)


def _apply_supplied_fields(record, supplied):
    current = {field: _get(record, field) for field in EDITABLE_FIELDS}
    current.update(supplied)
    for field, value in _normalized_fields(current).items():
        _set(record, field, value)


def update_invoice(invoice_name, values):
    supplied = _parse_values(values)
    name = str(invoice_name)
    with _transaction_lock("record", name):
        record = _require_record(name, write=True, current=True)
        if _get(record, "recognition_status") not in {"待确认", "疑似重复"}:
            _throw("当前发票状态不允许修改识别字段。")
        _apply_supplied_fields(record, supplied)
        _save(record)
        return _serialize_record(record)


def _resolution_prefix(key):
    fingerprint = hashlib.sha256(str(key or "").encode("utf-8")).hexdigest()
    return f"duplicate-override:v1:{fingerprint}:"


def _resolution_applies(record, key):
    return str(_get(record, "duplicate_reason") or "").startswith(_resolution_prefix(key))


def _business_duplicate(record, *, current=False):
    key = business_key(_get(record, "invoice_number"), _get(record, "issue_date"), _get(record, "total_amount"))
    if not key:
        return None, None
    filters = {
        "invoice_number": str(_get(record, "invoice_number") or "").strip(),
        "issue_date": _get(record, "issue_date"),
        "total_amount": _get(record, "total_amount"),
        "recognition_status": "已确认",
    }
    return key, _first_duplicate(filters, exclude=_get(record, "name"), current=current)


def _confirm(record):
    _set(record, "recognition_status", "已确认")
    _set(record, "confirmed_by", _user())
    _set(record, "confirmed_on", _now())
    _set(record, "processing_error", "")
    _set(record, "processing_started_on", None)
    _save(record)


def confirm_invoice(invoice_name, values=None):
    supplied = _parse_values(values)
    name = str(invoice_name)
    with _transaction_lock("record", name):
        record = _require_record(name, write=True, current=True)
        status = _get(record, "recognition_status")
        if status == "疑似重复":
            _throw("疑似重复发票必须先由财务解除后才能确认。")
        if status != "待确认":
            _throw("当前发票状态不允许确认。")
        if supplied:
            _apply_supplied_fields(record, supplied)
        key, _duplicate = _business_duplicate(record)
        if key and not _resolution_applies(record, key):
            with _transaction_lock("business", key):
                _, duplicate = _business_duplicate(record, current=True)
                if duplicate:
                    duplicate_name = _get(duplicate, "name")
                    _set(record, "recognition_status", "疑似重复")
                    _set(record, "duplicate_of", duplicate_name)
                    _set(record, "duplicate_reason", "发票号码、开票日期和合计金额与已确认发票相同")
                    _save(record)
                    _recompute_record_batch(record)
                    result = _serialize_record(record)
                    result["conflict"] = {"code": "duplicate", "duplicate_of": duplicate_name}
                    return result
                _confirm(record)
                _recompute_record_batch(record)
                return _serialize_record(record)
        _confirm(record)
        _recompute_record_batch(record)
        return _serialize_record(record)


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _processing_claim_is_stale(record):
    started = _as_datetime(_get(record, "processing_started_on"))
    return bool(started and (_now() - started).total_seconds() >= PROCESSING_STALE_SECONDS)


def retry_invoice(invoice_name):
    name = str(invoice_name)
    with _transaction_lock("record", name):
        record = _require_record(name, write=True, current=True)
        status = _get(record, "recognition_status")
        if status != "失败" and not (status == "识别中" and _processing_claim_is_stale(record)):
            _throw("只有识别失败或识别超时的发票可以重试。")
        _read_private_record(record)
        _set(record, "recognition_status", "排队中")
        _set(record, "processing_error", "")
        _set(record, "processing_started_on", None)
        _save(record)
        _recompute_record_batch(record)
        _enqueue_recognition_after_commit(_get(record, "name"))
        return _serialize_record(record)


def exclude_invoice(invoice_name, reason):
    reason = str(reason or "").strip()
    if not reason:
        _throw("排除发票必须填写原因。")
    if len(reason) > 500:
        _throw("排除原因过长。")
    name = str(invoice_name)
    with _transaction_lock("record", name):
        record = _require_record(name, write=True, current=True)
        if _get(record, "recognition_status") not in {"待确认", "疑似重复", "失败"}:
            _throw("当前发票状态不允许排除。")
        _set(record, "recognition_status", "已排除")
        _set(record, "duplicate_reason", f"排除：{reason}")
        _set(record, "processing_started_on", None)
        _save(record)
        _recompute_record_batch(record)
        return _serialize_record(record)


def resolve_duplicate(invoice_name, reason):
    user = _user()
    if not (_roles(user) & FINANCE_ROLES):
        _throw("仅财务人员可以解除疑似重复。")
    reason = str(reason or "").strip()
    if not reason:
        _throw("解除疑似重复必须填写复核原因。")
    if len(reason) > 500:
        _throw("复核原因过长。")
    name = str(invoice_name)
    with _transaction_lock("record", name):
        record = _current_doc(RECORD_DOCTYPE, name)
        if _get(record, "recognition_status") != "疑似重复":
            _throw("该发票当前不是疑似重复状态。")
        key = business_key(_get(record, "invoice_number"), _get(record, "issue_date"), _get(record, "total_amount"))
        _set(record, "recognition_status", "待确认")
        _set(record, "duplicate_reason", f"{_resolution_prefix(key)}{reason}")
        _save(record)
        _recompute_record_batch(record)
        return _serialize_record(record)



def _request_permission(request_doc, ptype):
    user = _user()
    if ptype == "edit":
        allowed = invoice_permissions.can_edit_request(request_doc, user)
    else:
        allowed = invoice_permissions.can_read_request(request_doc, user)
    if not allowed:
        _throw("您无权访问该费用付款/报销单。")

def link_invoice(invoice_name, request, expense_line_key):
    invoice_name = str(invoice_name)
    request_name = str(request)
    line_key = str(expense_line_key or "").strip()
    if not line_key:
        _throw("必须选择费用明细。")

    # This first read is address/authentication only. Every decision is repeated
    # as a current read after all Redis locks are acquired, so no DB row lock is
    # held while waiting on the batch/request Redis locks.
    preliminary = _require_record(invoice_name, write=True)
    preliminary_batch = str(_get(preliminary, "batch") or "")
    with _transaction_lock("record", invoice_name):
        with _transaction_lock("batch", preliminary_batch):
            with _transaction_lock("request", request_name):
                record = _require_record(invoice_name, write=True, current=True)
                batch_name = str(_get(record, "batch") or "")
                if batch_name != preliminary_batch:
                    _throw("发票批次已发生变化，请刷新后重试。")
                batch = _current_doc(BATCH_DOCTYPE, batch_name)
                request_doc = _current_doc(REQUEST_DOCTYPE, request_name)
                _request_permission(request_doc, "edit")
                if _get(record, "recognition_status") != "已确认":
                    _throw("只有已确认发票可以关联费用明细。")
                if _get(request_doc, "workflow_status") not in ACTIVE_REQUEST_STATUSES:
                    _throw("报销单提交后不能调整发票关联。")
                line = _current_value(
                    LINE_DOCTYPE,
                    {
                        "parent": request_name,
                        "parenttype": REQUEST_DOCTYPE,
                        "parentfield": "expense_lines",
                        "line_key": line_key,
                    },
                    ["name", "line_key"],
                )
                if not line:
                    _throw("所选费用明细不属于该报销单。")
                existing_request = str(_get(record, "request") or "")
                existing_line = str(_get(record, "expense_line_key") or "")
                if existing_request and (
                    existing_request != request_name or existing_line != line_key
                ):
                    _throw("该发票已关联到其他费用明细或报销单。")
                batch_request = str(_get(batch, "request") or "")
                if batch_request and batch_request != request_name:
                    _throw("同一发票批次不能关联多张报销单。")
                _set(record, "request", request_name)
                _set(record, "expense_line_key", line_key)
                _save(record)
                if not batch_request:
                    _set(batch, "request", request_name)
                    _save(batch)
                return _serialize_record(record)



def _read_private_record(record, *, current=False):
    file_url = _safe_file_url(_get(record, "invoice_file")); file_doc = _file_doc(file_url, current=current)
    if int(_get(file_doc, "is_private") or 0) != 1: _throw("发票文件不再是私有文件。")
    if _get(file_doc, "attached_to_doctype") != RECORD_DOCTYPE or _get(file_doc, "attached_to_name") != _get(record, "name"): _throw("发票文件关联已失效。")
    content = _read_limited(file_doc); digest = hashlib.sha256(content).hexdigest()
    if digest != _get(record, "file_sha256"): _throw("发票文件内容已发生变化。")
    return file_doc, content


def get_batch(batch):
    batch_doc = _require_batch(str(batch)); records = []
    for row in _get_all(RECORD_DOCTYPE, filters={"batch": _get(batch_doc, "name")}, fields=["name"]):
        record = frappe.get_doc(RECORD_DOCTYPE, _get(row, "name"))
        if can_read_invoice(record, _user()): records.append(_serialize_record(record))
    result = _serialize_batch(batch_doc)
    if _get(batch_doc, "owner") != _user():
        result.pop("temporary_token", None)
    result["records"] = records
    return result


def get_request_invoices(request):
    _user()
    request_doc = frappe.get_doc(REQUEST_DOCTYPE, str(request)); _request_permission(request_doc, "read"); result = []
    for row in _get_all(RECORD_DOCTYPE, filters={"request": _get(request_doc, "name")}, fields=["name"]):
        record = frappe.get_doc(RECORD_DOCTYPE, _get(row, "name"))
        if can_read_invoice(record, _user()): result.append(_serialize_record(record))
    return result


def _preview_cache_key(token):
    return _lock_key("preview-token", token)


def preview_invoice(invoice_name):
    record = _require_record(str(invoice_name))
    _file_doc_value, _content = _read_private_record(record)
    token = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"user": _user(), "invoice": _get(record, "name")},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    frappe.cache().set_value(
        _preview_cache_key(token),
        payload,
        expires_in_sec=PREVIEW_TOKEN_TTL_SECONDS,
    )
    return {
        "token": token,
        "preview_method": "POST",
        "preview_url": (
            "/api/method/rayher_hr_payroll.api.invoice_entry."
            "serve_invoice_preview"
        ),
        "mime_type": _get(record, "mime_type"),
        "display_name": _get(record, "original_filename"),
    }


def serve_invoice_preview(token):
    user = _user()
    token = str(token or "").strip()
    if len(token) < 32 or len(token) > 200 or "\x00" in token:
        _throw("发票预览凭证已失效或过期。")

    cache = frappe.cache()
    key = _preview_cache_key(token)
    lock = cache.lock(
        _lock_key("preview-consume", token),
        timeout=PREVIEW_TOKEN_TTL_SECONDS,
        blocking_timeout=5,
    )
    if not lock.acquire(blocking=True, blocking_timeout=5):
        _throw("发票正在被其他操作处理，请稍后重试。")
    state = {"released": False, "deferred": False}

    def release():
        if state["released"]:
            return
        state["released"] = True
        try:
            lock.release()
        except Exception:
            _log_internal("Invoice OCR preview lock release failed")

    try:
        raw = cache.get_value(key)
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            payload = None
        if not isinstance(payload, dict) or not payload.get("invoice"):
            _throw("发票预览凭证已失效或过期。")
        if payload.get("user") != user:
            _throw("您无权使用该发票预览凭证。")

        record = _require_record(str(payload["invoice"]), current=True)
        _file_doc_value, content = _read_private_record(record, current=True)
        consumed_marker = json.dumps(
            {"consumed": True}, ensure_ascii=False, separators=(",", ":")
        )
        cache.set_value(
            key,
            consumed_marker,
            expires_in_sec=PREVIEW_TOKEN_TTL_SECONDS,
        )

        def committed():
            try:
                cache.delete_value(key)
            finally:
                release()

        def rolled_back():
            try:
                cache.set_value(
                    key,
                    raw,
                    expires_in_sec=PREVIEW_TOKEN_TTL_SECONDS,
                )
            finally:
                release()

        frappe.db.after_commit.add(committed)
        frappe.db.after_rollback.add(rolled_back)
        state["deferred"] = True

        log = frappe.get_doc(
            {
                "doctype": VIEW_LOG_DOCTYPE,
                "invoice_record": _get(record, "name"),
                "action": "查看",
            }
        )
        log.insert(ignore_permissions=True)
        display_name = (
            str(_get(record, "original_filename") or "invoice")
            .replace("\r", "")
            .replace("\n", "")[:255]
        )
        response = frappe.local.response
        response.type = "download"
        response.filename = display_name
        response.filecontent = content
        response.content_type = _get(record, "mime_type") or "application/octet-stream"
        response.display_content_as = "inline"
        return None
    except BaseException:
        if not state["deferred"]:
            release()
        raise



def _serialize_batch(batch):
    return {
        "name": _get(batch, "name"), "temporary_token": _get(batch, "temporary_token"), "request": _get(batch, "request"),
        "batch_status": _get(batch, "batch_status"), "total_count": int(_get(batch, "total_count") or 0),
        "queued_count": int(_get(batch, "queued_count") or 0), "processing_count": int(_get(batch, "processing_count") or 0),
        "pending_confirmation_count": int(_get(batch, "pending_confirmation_count") or 0), "confirmed_count": int(_get(batch, "confirmed_count") or 0),
        "duplicate_count": int(_get(batch, "duplicate_count") or 0), "failed_count": int(_get(batch, "failed_count") or 0),
        "excluded_count": int(_get(batch, "excluded_count") or 0), "expires_on": _get(batch, "expires_on"), "error_summary": _get(batch, "error_summary") or "",
    }


def _serialize_record(record):
    return {
        "name": _get(record, "name"), "batch": _get(record, "batch"), "original_filename": _get(record, "original_filename"),
        "mime_type": _get(record, "mime_type"), "file_size": int(_get(record, "file_size") or 0), "recognition_status": _get(record, "recognition_status"),
        "invoice_category": _get(record, "invoice_category") or "", "project_name": _get(record, "project_name") or "", "issue_date": _get(record, "issue_date"),
        "invoice_number": _get(record, "invoice_number") or "", "amount_before_tax": _get(record, "amount_before_tax"), "tax_amount": _get(record, "tax_amount"),
        "total_amount": _get(record, "total_amount"), "field_warnings": _get(record, "field_warnings") or "[]", "is_duplicate": bool(_get(record, "duplicate_of")),
        "duplicate_reason": _get(record, "duplicate_reason") or "", "request": _get(record, "request") or "", "expense_line_key": _get(record, "expense_line_key") or "",
        "processing_started_on": _get(record, "processing_started_on"), "processing_error": _get(record, "processing_error") or "",
        "retry_count": int(_get(record, "retry_count") or 0),
        "confirmed_by": _get(record, "confirmed_by") or "", "confirmed_on": _get(record, "confirmed_on"),
    }
