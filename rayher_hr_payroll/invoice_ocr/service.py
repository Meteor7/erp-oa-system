"""Server-owned workflow for invoice OCR batches and records."""

from __future__ import annotations

import hashlib
import json
import secrets
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

import frappe

from rayher_hr_payroll.invoice_ocr.domain import business_key, submission_blockers
from rayher_hr_payroll.invoice_ocr import permissions as invoice_permissions
from rayher_hr_payroll.invoice_ocr.permissions import can_read_invoice
from rayher_hr_payroll.oa_mutation_guard import authorized_oa_action

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
MAX_EXPENSE_DESCRIPTION_LENGTH = 1000
PROCESSING_STALE_SECONDS = 15 * 60
PREVIEW_TOKEN_TTL_SECONDS = 60
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
CANONICAL_MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
EDITABLE_FIELDS = {"invoice_category", "project_name", "issue_date", "invoice_number", "amount_before_tax", "tax_amount", "total_amount"}
MONEY_FIELDS = {"amount_before_tax", "tax_amount", "total_amount"}
_MANUAL_PRESENCE_PREFIX = "manual-field-presence:"
REQUEST_RECORD_FIELDS = ["name", "batch", "recognition_status", "invoice_category", "project_name", "invoice_number", "total_amount", "expense_description", "ocr_payload", "field_warnings", "request", "expense_line_key"]
REQUEST_SEARCH_LIMIT = 2000
REQUEST_REASON_LIMIT = 1000
FINANCE_ROLES = {"System Manager", "Accounts User"}
ACTIVE_REQUEST_STATUSES = {"草稿"}
POST_SUBMISSION_INVOICE_STATUSES = {"待审批", "待办理", "待流转", "已完成", "已付款"}
INVOICE_MODE_PENDING = "暂未取得发票"
INVOICE_FOLLOWUP_PENDING = "待收票"
INVOICE_FOLLOWUP_RECEIVED = "已收票"
WORKBENCH_STATUSES = {"排队中", "识别中", "待确认", "已确认", "疑似重复", "失败", "已排除"}
WORKBENCH_PRIVILEGED_ROLES = {"System Manager", "Accounts User", "HR User", "HR Manager"}
OPERATION_LOG_LIMIT = 100


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
    if _get(doc, "doctype") == REQUEST_DOCTYPE:
        with authorized_oa_action():
            return doc.save(ignore_permissions=True)
    return doc.save(ignore_permissions=True)


def _now():
    value = frappe.utils.now_datetime()
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _bounded_note(value, limit=500):
    if value is None:
        return ""
    if not isinstance(value, str):
        _throw("操作说明格式无效。")
    value = value.strip()
    if len(value) > limit:
        _throw("操作说明不能超过 500 个字符。")
    return value


def _operation_events(doc):
    raw = _get(doc, "operation_log") or "[]"
    try:
        events = json.loads(raw) if isinstance(raw, str) else list(raw)
    except (TypeError, ValueError):
        events = []
    return events if isinstance(events, list) else []


def _append_record_event(doc, action, from_status, to_status, note=""):
    events = _operation_events(doc)
    events.append(
        {
            "action": str(action),
            "actor": _user(),
            "acted_on": str(_now()),
            "from_status": str(from_status or ""),
            "to_status": str(to_status or ""),
            "note": _bounded_note(note),
        }
    )
    _set(doc, "operation_log", json.dumps(events[-OPERATION_LOG_LIMIT:], ensure_ascii=False))


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
    try:
        frappe.db.after_commit.add(release)
        frappe.db.after_rollback.add(release)
    except BaseException:
        release()
        raise
    yield lock


def _can_write_record(record, user=None, *, current=False) -> bool:
    user = user or _user()
    roles = _roles(user)
    if user == "Administrator" or "System Manager" in roles or _get(record, "owner") == user:
        return True
    batch = None
    batch_name = str(_get(record, "batch") or "")
    if batch_name:
        try:
            batch = (
                _current_doc(BATCH_DOCTYPE, batch_name)
                if current
                else frappe.get_doc(BATCH_DOCTYPE, batch_name)
            )
        except Exception:
            batch = None
        if batch and _get(batch, "owner") == user:
            return True
    request_name = str(_get(record, "request") or "")
    if not request_name and batch:
        request_name = str(_get(batch, "request") or "")
    return bool(
        request_name
        and invoice_permissions.can_edit_request(
            request_name, user, current=current
        )
    )

def _require_record(name: str, *, write=False, current=False):
    user = _user()
    record = _current_doc(RECORD_DOCTYPE, name) if current else frappe.get_doc(RECORD_DOCTYPE, name)
    allowed = (
        _can_write_record(record, user, current=current)
        if write
        else can_read_invoice(record, user, current=current)
    )
    if not allowed:
        _throw("您无权访问该发票记录。")
    return record


def _require_batch(name: str, *, owner_only=False, current=False):
    user = _user()
    batch = _current_doc(BATCH_DOCTYPE, name) if current else frappe.get_doc(BATCH_DOCTYPE, name)
    if owner_only:
        allowed = _get(batch, "owner") == user or user == "Administrator" or "System Manager" in _roles(user)
    else:
        allowed = can_read_invoice(batch, user, current=current)
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


def _file_doc(
    file_url: str,
    *,
    current=False,
    attached_to_doctype=None,
    attached_to_name=None,
):
    lookup_kwargs = {"for_update": True} if current else {}
    filters = {"file_url": file_url}
    if attached_to_doctype:
        filters["attached_to_doctype"] = attached_to_doctype
    if attached_to_name:
        filters["attached_to_name"] = attached_to_name
    name = frappe.db.get_value(
        "File", filters, "name", **lookup_kwargs
    )
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


def _attach_file(file_guard, record, trusted_size):
    """Idempotently attach the latest locked File document."""
    file_name = str(file_guard.get("name") or "").strip()
    expected_url = str(file_guard.get("file_url") or "")
    expected_owner = str(file_guard.get("owner") or "")
    if not file_name:
        _throw("\u53d1\u7968\u6587\u4ef6\u5173\u8054\u5df2\u5931\u6548\u3002")
    file_doc = _current_doc("File", file_name)
    if (
        str(_get(file_doc, "name") or "") != file_name
        or str(_get(file_doc, "file_url") or "") != expected_url
    ):
        _throw("\u53d1\u7968\u6587\u4ef6\u5173\u8054\u5df2\u5931\u6548\u3002")
    if (
        int(file_guard.get("is_private") or 0) != 1
        or int(_get(file_doc, "is_private") or 0) != 1
    ):
        _throw("\u53d1\u7968\u6587\u4ef6\u5fc5\u987b\u4e3a\u79c1\u6709\u6587\u4ef6\u3002")
    if str(_get(file_doc, "owner") or "") != expected_owner:
        _throw("\u53d1\u7968\u6587\u4ef6\u6240\u6709\u8005\u5df2\u53d1\u751f\u53d8\u5316\u3002")

    record_name = str(_get(record, "name") or "")
    record_batch = str(_get(record, "batch") or "")
    current_attachment = (
        str(_get(file_doc, "attached_to_doctype") or ""),
        str(_get(file_doc, "attached_to_name") or ""),
    )
    allowed_attachments = {
        ("", ""),
        (BATCH_DOCTYPE, record_batch),
        (RECORD_DOCTYPE, record_name),
    }
    if current_attachment not in allowed_attachments:
        _throw(
            "\u8be5\u6587\u4ef6\u5df2\u9644\u52a0\u5230\u5176\u4ed6\u4e1a\u52a1\u8bb0\u5f55\u3002"
        )

    desired = {
        "file_size": trusted_size,
        "attached_to_doctype": RECORD_DOCTYPE,
        "attached_to_name": record_name,
        "attached_to_field": "invoice_file",
    }
    if all(_get(file_doc, field) == value for field, value in desired.items()):
        return file_doc
    for field, value in desired.items():
        _set(file_doc, field, value)
    with _trusted_file_controller_values():
        _save(file_doc)
    return file_doc

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
            record = _current_doc(RECORD_DOCTYPE, invoice_name)
            if _get(record, "recognition_status") == "排队中":
                _set(record, "recognition_status", "失败")
                _set(record, "processing_error", ENQUEUE_FAILURE_MESSAGE)
                _set(record, "processing_started_on", None)
                _set(record, "processing_claim_id", "")
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

    def enqueue_recompute():
        pending.discard(batch_name)
        try:
            frappe.enqueue(
                "rayher_hr_payroll.invoice_ocr.jobs.recompute_invoice_batch",
                batch_name=batch_name,
                queue="short",
                enqueue_after_commit=False,
            )
        except Exception:
            _log_internal("Invoice OCR batch aggregation enqueue failed")

    frappe.db.after_commit.add(enqueue_recompute)
    frappe.db.after_rollback.add(lambda: pending.discard(batch_name))


def _recompute_record_batch(record):
    batch_name = str(_get(record, "batch") or "")
    if batch_name:
        _recompute_batch_after_commit(batch_name)


def register_file(batch, file_url):
    batch_name = str(batch)
    file_url = _safe_file_url(file_url)
    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        _throw("\u627e\u4e0d\u5230\u5df2\u4e0a\u4f20\u7684\u53d1\u7968\u6587\u4ef6\u3002")

    preliminary_batch = _require_batch(batch_name, owner_only=True)
    preliminary_request = str(_get(preliminary_batch, "request") or "").strip()
    with ExitStack() as registration_locks:
        if preliminary_request:
            registration_locks.enter_context(
                _transaction_lock("request", preliminary_request)
            )
        registration_locks.enter_context(_transaction_lock("batch", batch_name))
        batch_doc = _require_batch(batch_name, owner_only=True, current=True)
        request_name = str(_get(batch_doc, "request") or "").strip()
        if request_name != preliminary_request:
            _throw("\u53d1\u7968\u6279\u6b21\u5173\u8054\u5df2\u53d1\u751f\u53d8\u5316\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002")
        if request_name:
            request_doc = _current_doc(REQUEST_DOCTYPE, request_name)
            _request_permission(request_doc, "edit", current=True)
            if _get(request_doc, "workflow_status") not in ACTIVE_REQUEST_STATUSES:
                _throw("\u62a5\u9500\u5355\u63d0\u4ea4\u540e\u4e0d\u80fd\u8ffd\u52a0\u53d1\u7968\u3002")

        registration_locks.enter_context(_transaction_lock("file", file_name))
        file_doc = _current_doc("File", file_name)
        file_doc, content, server_name, server_mime = _validated_file(
            batch_doc, file_doc, file_url
        )
        file_guard = {
            "name": str(_get(file_doc, "name") or ""),
            "file_url": str(_get(file_doc, "file_url") or ""),
            "is_private": int(_get(file_doc, "is_private") or 0),
            "owner": str(_get(file_doc, "owner") or ""),
        }
        digest = hashlib.sha256(content).hexdigest()
        with _transaction_lock("file-hash", digest):
            count = len(
                _current_rows(
                    RECORD_DOCTYPE,
                    filters={"batch": batch_name},
                    fields=["name"],
                )
            )
            if count >= MAX_BATCH_FILES:
                _throw("\u6bcf\u6279\u6700\u591a\u4e0a\u4f20 20 \u5f20\u53d1\u7968\u3002")
            user = _user()
            duplicate = _first_duplicate({"file_sha256": digest}, current=True)
            record = frappe.get_doc(
                {
                    "doctype": RECORD_DOCTYPE,
                    "owner": user,
                    "batch": batch_name,
                    "request": request_name,
                    "invoice_file": _get(file_doc, "file_url"),
                    "original_filename": server_name,
                    "mime_type": server_mime,
                    "file_size": len(content),
                    "file_sha256": digest,
                    "uploaded_by": user,
                    "recognition_status": "\u7591\u4f3c\u91cd\u590d" if duplicate else "\u6392\u961f\u4e2d",
                    "duplicate_of": _get(duplicate, "name") if duplicate else "",
                    "duplicate_reason": (
                        "\u6587\u4ef6\u5185\u5bb9\u4e0e\u5df2\u6709\u53d1\u7968\u5b8c\u5168\u76f8\u540c"
                        if duplicate
                        else ""
                    ),
                    "retry_count": 0,
                }
            )
            record.insert(ignore_permissions=True)
            _attach_file(file_guard, record, len(content))
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
            "queued_count": statuses.count("\u6392\u961f\u4e2d"),
            "processing_count": statuses.count("\u8bc6\u522b\u4e2d"),
            "pending_confirmation_count": statuses.count("\u5f85\u786e\u8ba4"),
            "confirmed_count": statuses.count("\u5df2\u786e\u8ba4"),
            "duplicate_count": statuses.count("\u7591\u4f3c\u91cd\u590d"),
            "failed_count": statuses.count("\u5931\u8d25"),
            "excluded_count": statuses.count("\u5df2\u6392\u9664"),
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


def derive_total_amount(amount_before_tax, tax_amount, total_amount):
    before_tax = _normalize_money(amount_before_tax)
    tax = _normalize_money(tax_amount)
    total = _normalize_money(total_amount)
    if total is None and before_tax is not None and tax is not None:
        total = (before_tax + tax).quantize(Decimal("0.01"))
    return total


def _normalized_fields(values):
    return {
        "invoice_category": _normalize_text("invoice_category", values.get("invoice_category")),
        "project_name": _normalize_text("project_name", values.get("project_name")),
        "issue_date": _normalize_date(values.get("issue_date")),
        "invoice_number": _normalize_text("invoice_number", values.get("invoice_number")),
        "amount_before_tax": _normalize_money(values.get("amount_before_tax")),
        "tax_amount": _normalize_money(values.get("tax_amount")),
        "total_amount": derive_total_amount(values.get("amount_before_tax"), values.get("tax_amount"), values.get("total_amount")),
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


def _warning_entries(record):
    try:
        warnings = json.loads(_get(record, "field_warnings") or "[]")
    except (TypeError, ValueError):
        return []
    return warnings if isinstance(warnings, list) else []


def _has_supplied_value(value):
    return value is not None and str(value).strip() != ""


def _set_money_presence_markers(record, supplied):
    touched = MONEY_FIELDS.intersection(supplied)
    if not touched:
        return
    warnings = []
    for warning in _warning_entries(record):
        if not isinstance(warning, str) or not warning.startswith(_MANUAL_PRESENCE_PREFIX):
            warnings.append(warning)
            continue
        marker = warning[len(_MANUAL_PRESENCE_PREFIX):].split(":", 1)
        if not marker or marker[0] not in touched:
            warnings.append(warning)
    for field in sorted(touched):
        state = "present" if _has_supplied_value(supplied[field]) else "blank"
        warnings.append(f"{_MANUAL_PRESENCE_PREFIX}{field}:{state}")
    _set(record, "field_warnings", json.dumps(warnings, ensure_ascii=False, separators=(",", ":")))


def _money_presence(record, field):
    prefix = f"{_MANUAL_PRESENCE_PREFIX}{field}:"
    for warning in reversed(_warning_entries(record)):
        if isinstance(warning, str) and warning.startswith(prefix):
            return warning == f"{prefix}present"
    try:
        payload = json.loads(_get(record, "ocr_payload") or "{}")
    except (TypeError, ValueError):
        return None
    fields = payload.get("fields") if isinstance(payload, dict) else None
    if not isinstance(fields, dict) or field not in fields:
        return None
    return _has_supplied_value(fields.get(field))


def _record_money(record, field):
    presence = _money_presence(record, field)
    if field == "total_amount" and presence is False:
        components_present = (
            _money_presence(record, "amount_before_tax") is True
            and _money_presence(record, "tax_amount") is True
        )
        if components_present and _get(record, field) is not None:
            return _get(record, field)
    return None if presence is False else _get(record, field)


def _public_field_warnings(record):
    warnings = [
        warning for warning in _warning_entries(record)
        if not (isinstance(warning, str) and warning.startswith(_MANUAL_PRESENCE_PREFIX))
    ]
    return json.dumps(warnings, ensure_ascii=False, separators=(",", ":"))


def _apply_supplied_fields(record, supplied):
    current = {field: _get(record, field) for field in EDITABLE_FIELDS}
    current.update(supplied)
    for field, value in _normalized_fields(current).items():
        _set(record, field, value)
    _set_money_presence_markers(record, supplied)


def update_invoice(invoice_name, values):
    supplied = _parse_values(values)
    name = str(invoice_name)
    with _transaction_lock("record", name):
        record = _require_record(name, write=True, current=True)
        if _get(record, "recognition_status") not in {"待确认", "疑似重复"}:
            _throw("当前发票状态不允许修改识别字段。")
        _apply_supplied_fields(record, supplied)
        _save(record)
        return _serialize_record(record, include_attachments=True)


def _normalize_expense_description(value):
    description = str(value or "").strip()
    if "\x00" in description or len(description) > MAX_EXPENSE_DESCRIPTION_LENGTH:
        _throw("费用说明格式无效或内容过长。")
    return description


def update_expense_context(invoice_name, expense_description):
    name = str(invoice_name)
    with _transaction_lock("record", name):
        record = _require_record(name, write=True, current=True)
        if str(_get(record, "request") or "").strip():
            _throw("发票已经下推，请先撤回下推后再修改费用说明或附件。")
        if _get(record, "recognition_status") not in {"待确认", "疑似重复", "已确认"}:
            _throw("当前发票状态不允许修改费用说明。")
        old_description = str(_get(record, "expense_description") or "").strip()
        description = _normalize_expense_description(expense_description)
        _set(record, "expense_description", description)
        if description != old_description:
            _append_record_event(
                record,
                "费用说明修改",
                _get(record, "recognition_status"),
                _get(record, "recognition_status"),
                description,
            )
        _save(record)
        return _serialize_record(record, include_attachments=True)


def _resolution_prefix(key):
    fingerprint = hashlib.sha256(str(key or "").encode("utf-8")).hexdigest()
    return f"duplicate-override:v1:{fingerprint}:"


def _resolution_applies(record, key):
    return str(_get(record, "duplicate_reason") or "").startswith(_resolution_prefix(key))


def _business_duplicate(record, *, current=False):
    total_amount = _record_money(record, "total_amount")
    key = business_key(_get(record, "invoice_number"), _get(record, "issue_date"), total_amount)
    if not key:
        return None, None
    filters = {
        "invoice_number": str(_get(record, "invoice_number") or "").strip(),
        "issue_date": _get(record, "issue_date"),
        "total_amount": total_amount,
        "recognition_status": "已确认",
    }
    return key, _first_duplicate(filters, exclude=_get(record, "name"), current=current)


def _confirm(record):
    _set(record, "recognition_status", "已确认")
    _set(record, "confirmed_by", _user())
    _set(record, "confirmed_on", _now())
    _set(record, "processing_error", "")
    _set(record, "processing_started_on", None)
    _set(record, "processing_claim_id", "")
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
        description = _normalize_expense_description(
            _get(record, "expense_description")
        )
        if not description:
            _throw("确认发票前必须填写费用说明。")
        _set(record, "expense_description", description)
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
                    result = _serialize_record(
                        record, include_attachments=True
                    )
                    result["conflict"] = {"code": "duplicate", "duplicate_of": duplicate_name}
                    return result
                _confirm(record)
                _recompute_record_batch(record)
                return _serialize_record(
                    record, include_attachments=True
                )
        _confirm(record)
        _recompute_record_batch(record)
        return _serialize_record(record, include_attachments=True)


def list_workbench_invoices(view="mine", status=None, limit=200, include_pushed=False):
    user = _user()
    roles = _roles(user)
    view = str(view or "mine").strip()
    status = str(status or "").strip()
    if status and status not in WORKBENCH_STATUSES:
        _throw("发票状态无效。")
    try:
        bounded_limit = int(limit or 200)
    except (TypeError, ValueError):
        _throw("查询数量无效。")
    if bounded_limit < 1 or bounded_limit > 300:
        _throw("查询数量必须在 1 到 300 之间。")
    filters = {}
    if not (view == "all" and roles & WORKBENCH_PRIVILEGED_ROLES):
        filters["owner"] = user
    if status:
        filters["recognition_status"] = status
    include_pushed = (
        include_pushed
        if isinstance(include_pushed, bool)
        else str(include_pushed or "").strip().lower() in {"1", "true", "yes"}
    )
    if not include_pushed:
        filters["request"] = ""
    names = _get_all(
        RECORD_DOCTYPE,
        filters=filters,
        fields=["name"],
        order_by="modified desc",
        limit=bounded_limit,
    )
    rows = []
    for item in names:
        name = str(_get(item, "name") or "").strip()
        if not name:
            continue
        record = frappe.get_doc(RECORD_DOCTYPE, name)
        if can_read_invoice(record, user):
            rows.append(
                _serialize_record(record, include_attachments=True)
            )
    return rows


def unconfirm_invoice(invoice_name, note=None):
    name = str(invoice_name or "").strip()
    note = _bounded_note(note)
    with _transaction_lock("record", name):
        record = _require_record(name, write=True, current=True)
        status = str(_get(record, "recognition_status") or "")
        if status != "已确认":
            _throw("只有已确认发票可以撤回确认。")
        if str(_get(record, "request") or "").strip() or str(_get(record, "expense_line_key") or "").strip():
            _throw("该发票已下推，请先撤回下推后再撤回确认。")
        _set(record, "recognition_status", "待确认")
        _set(record, "confirmed_by", "")
        _set(record, "confirmed_on", None)
        _append_record_event(record, "撤回确认", status, "待确认", note)
        _save(record)
        _recompute_record_batch(record)
        return _serialize_record(record, include_attachments=True)


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
        _read_private_record(record, current=True)
        _set(record, "recognition_status", "排队中")
        _set(record, "processing_error", "")
        _set(record, "processing_started_on", None)
        _set(record, "processing_claim_id", "")
        _save(record)
        _recompute_record_batch(record)
        _enqueue_recognition_after_commit(_get(record, "name"))
        return _serialize_record(record, include_attachments=True)


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
        _set(record, "processing_claim_id", "")
        _save(record)
        _recompute_record_batch(record)
        return _serialize_record(record, include_attachments=True)


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
        key = business_key(_get(record, "invoice_number"), _get(record, "issue_date"), _record_money(record, "total_amount"))
        _set(record, "recognition_status", "待确认")
        _set(record, "duplicate_reason", f"{_resolution_prefix(key)}{reason}")
        _set(record, "processing_claim_id", "")
        _save(record)
        _recompute_record_batch(record)
        return _serialize_record(record, include_attachments=True)


def _request_invoice_records(request_name, *, current=False):
    """Read the complete, deduplicated request invoice collection."""
    request_name = str(request_name or "").strip()
    if not request_name:
        return []
    read_rows = _current_rows if current else _get_all
    records = {}
    for row in read_rows(
        RECORD_DOCTYPE,
        filters={"request": request_name},
        fields=REQUEST_RECORD_FIELDS,
    ):
        record_name = str(_get(row, "name") or "").strip()
        if record_name:
            records[record_name] = row
    batches = read_rows(
        BATCH_DOCTYPE,
        filters={"request": request_name},
        fields=["name"],
    )
    for batch in sorted(
        batches, key=lambda row: str(_get(row, "name") or "")
    ):
        batch_name = str(_get(batch, "name") or "").strip()
        if not batch_name:
            continue
        for row in read_rows(
            RECORD_DOCTYPE,
            filters={"batch": batch_name},
            fields=REQUEST_RECORD_FIELDS,
        ):
            record_name = str(_get(row, "name") or "").strip()
            if record_name:
                records.setdefault(record_name, row)
    return [records[name] for name in sorted(records)]



def _request_name(request_doc):
    return str(_get(request_doc, "name") or "").strip()


def _decimal_money(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite():
        return None
    return number.quantize(Decimal("0.01"))


def _deduplicated_values(values):
    parts = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        if value and value not in seen:
            seen.add(value)
            parts.append(value)
    return parts


def _deduplicated_text(values, limit=REQUEST_SEARCH_LIMIT):
    parts = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        if not value or value in seen:
            continue
        candidate = "；".join([*parts, value])
        if len(candidate) > limit:
            break
        seen.add(value)
        parts.append(value)
    return "；".join(parts)


def request_invoice_summary(request_doc, *, current=False):
    records = _request_invoice_records(
        _request_name(request_doc), current=current
    )
    included = [row for row in records if _get(row, "recognition_status") != "已排除"]
    statuses = []
    for row in included:
        status = str(_get(row, "recognition_status") or "状态异常")
        if status not in statuses:
            statuses.append(status)
    confirmed = [row for row in records if _get(row, "recognition_status") == "已确认"]
    invoice_categories = _deduplicated_values(_get(row, "invoice_category") for row in confirmed)
    invoice_project_names = _deduplicated_values(_get(row, "project_name") for row in confirmed)
    invoice_numbers = _deduplicated_values(_get(row, "invoice_number") for row in confirmed)
    search_values = [*invoice_categories, *invoice_project_names, *invoice_numbers]
    return {
        "invoice_count": len(included),
        "invoice_status": "、".join(statuses) if statuses else "无发票",
        "invoice_search_text": _deduplicated_text(search_values),
        "invoice_categories": invoice_categories,
        "invoice_project_names": invoice_project_names,
        "invoice_numbers": invoice_numbers,
    }


def _apply_request_invoice_summary(request_doc, *, save=False, current=False):
    summary = request_invoice_summary(request_doc, current=current)
    _set(request_doc, "invoice_count", summary["invoice_count"])
    _set(request_doc, "invoice_status", summary["invoice_status"])
    if save:
        _save(request_doc)
    return summary


def recompute_request_summary(request_name: str):
    """Refresh one request after the batch transaction has committed."""
    request_name = str(request_name or "").strip()
    if not request_name:
        return None
    with _transaction_lock("request", request_name):
        request_doc = _current_doc(REQUEST_DOCTYPE, request_name)
        _apply_request_invoice_summary(request_doc, save=True, current=False)
        return request_doc


def _latest_committed_request_batch_names(request_name):
    """Read committed batch links without locking batch rows.

    The dedicated connection's first consistent read cannot inherit the
    caller transaction's older REPEATABLE READ snapshot. Callers hold the
    request Redis lock, and every batch.request writer uses that same lock,
    so the committed result stays stable until the caller commits.
    """
    connection = frappe.db.get_connection()
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT `name`
            FROM `tabOA Invoice Import Batch`
            WHERE `request` = %s
            ORDER BY `name`
            """,
            (str(request_name),),
        )
        return [
            str(row[0])
            for row in cursor.fetchall()
            if row and str(row[0] or "").strip()
        ]
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def _assert_request_single_batch_current(request_name, batch_name):
    """Reject a second batch without extending DB row-lock order."""
    request_name = str(request_name or "").strip()
    batch_name = str(batch_name or "").strip()
    batch_names = set(
        _latest_committed_request_batch_names(request_name)
    )
    # Include this transaction's own earlier blank -> request assignments.
    # The association is write-once, so a snapshot row cannot be a stale
    # reassignment; this read is non-locking and cannot wait on register_file.
    for row in _get_all(
        BATCH_DOCTYPE,
        filters={"request": request_name},
        fields=["name"],
    ):
        name = str(_get(row, "name") or "").strip()
        if name:
            batch_names.add(name)
    other_batches = sorted(
        name for name in batch_names if name != batch_name
    )
    if other_batches:
        _throw(
            "\u8be5\u62a5\u9500\u5355\u5df2\u5173\u8054\u5176\u4ed6\u53d1\u7968\u6279\u6b21\u3002"
        )


def _can_supplement_request(request_doc, *, current=False):
    if _get(request_doc, "request_type") != "费用付款申请":
        return False
    if _get(request_doc, "invoice_handling_mode") != INVOICE_MODE_PENDING:
        return False
    if _get(request_doc, "invoice_followup_status") not in {INVOICE_FOLLOWUP_PENDING, INVOICE_FOLLOWUP_RECEIVED}:
        return False
    if _get(request_doc, "workflow_status") not in POST_SUBMISSION_INVOICE_STATUSES:
        return False
    return invoice_permissions.can_edit_request(request_doc, _user(), current=current) or bool(_roles() & FINANCE_ROLES)


def _append_request_invoice_event(request_doc, action, note=""):
    try:
        events = json.loads(_get(request_doc, "operation_log") or "[]")
    except (TypeError, ValueError):
        events = []
    if not isinstance(events, list):
        events = []
    events.append({"action": action, "actor": _user(), "acted_on": str(_now()), "from_status": _get(request_doc, "workflow_status") or "", "to_status": _get(request_doc, "workflow_status") or "", "note": _bounded_note(note)})
    _set(request_doc, "operation_log", json.dumps(events[-OPERATION_LOG_LIMIT:], ensure_ascii=False, default=str))


def attach_batch_to_request(batch_name, request_doc):
    batch_name = str(batch_name or "").strip()
    request_name = _request_name(request_doc)
    if not batch_name:
        _throw("\u7f3a\u5c11\u53d1\u7968\u6279\u6b21\u3002")
    if not request_name:
        _throw("\u8bf7\u5148\u4fdd\u5b58\u8d39\u7528\u4ed8\u6b3e/\u62a5\u9500\u5355\u3002")
    preliminary = _get_all(
        RECORD_DOCTYPE,
        filters={"batch": batch_name},
        fields=["name", "batch"],
    )
    record_names = sorted(
        {str(_get(row, "name") or "") for row in preliminary if _get(row, "name")}
    )
    with ExitStack() as locks:
        locks.enter_context(_transaction_lock("request", request_name))
        locks.enter_context(_transaction_lock("batch", batch_name))
        for record_name in record_names:
            locks.enter_context(_transaction_lock("record", record_name))
        batch = _require_batch(batch_name, owner_only=True, current=True)
        current_request = _current_doc(REQUEST_DOCTYPE, request_name)
        workflow_status = str(_get(current_request, "workflow_status") or "")
        supplementing = workflow_status != "草稿"
        if supplementing:
            if not _can_supplement_request(current_request, current=True):
                _throw("当前单据状态或权限不允许补录发票。")
        else:
            _request_permission(current_request, "edit", current=True)
        batch_request = str(_get(batch, "request") or "")
        if batch_request and batch_request != request_name:
            _throw("\u8be5\u53d1\u7968\u6279\u6b21\u5df2\u5173\u8054\u5230\u5176\u4ed6\u62a5\u9500\u5355\u3002")
        if not supplementing:
            _assert_request_single_batch_current(request_name, batch_name)
        current_rows = _current_rows(
            RECORD_DOCTYPE,
            filters={"batch": batch_name},
            fields=["name", "batch"],
        )
        current_names = sorted(
            {str(_get(row, "name") or "") for row in current_rows if _get(row, "name")}
        )
        if current_names != record_names:
            _throw("\u53d1\u7968\u6279\u6b21\u5185\u5bb9\u5df2\u53d1\u751f\u53d8\u5316\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002")
        records = [_current_doc(RECORD_DOCTYPE, name) for name in record_names]
        for record in records:
            if str(_get(record, "batch") or "") != batch_name:
                _throw("\u53d1\u7968\u6279\u6b21\u5185\u5bb9\u5df2\u53d1\u751f\u53d8\u5316\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002")
            existing = str(_get(record, "request") or "")
            if existing and existing != request_name:
                _throw("\u8be5\u53d1\u7968\u5df2\u5173\u8054\u5230\u5176\u4ed6\u62a5\u9500\u5355\u3002")
        if supplementing:
            included = [record for record in records if _get(record, "recognition_status") != "已排除"]
            if not included:
                _throw("补录批次中没有有效发票。")
            blockers = submission_blockers(included, "")
            if blockers:
                _throw("；".join(blockers))
        for record in records:
            _set(record, "request", request_name)
            _save(record)
        _set(batch, "request", request_name)
        _save(batch)
        _apply_request_invoice_summary(current_request, save=False, current=True)
        if supplementing:
            _set(current_request, "invoice_followup_status", INVOICE_FOLLOWUP_RECEIVED)
            _append_request_invoice_event(current_request, "补录发票", batch_name)
        _save(current_request)
        return current_request



def attach_batch_to_existing_request(batch_name, request_name):
    request_name = str(request_name or "").strip()
    attach_batch_to_request(batch_name, {"name": request_name})
    return {"name": str(batch_name or "").strip(), "request": request_name}


def _request_reason(request_doc):
    value = _get(request_doc, "no_invoice_reason")
    if value is None:
        return ""
    if not isinstance(value, str):
        _throw("无票原因格式无效。")
    value = value.strip()
    if len(value) > REQUEST_REASON_LIMIT:
        _throw("无票原因不能超过 1000 个字符。")
    return value


def validate_request_invoices(request_doc, submitting: bool):
    summary = request_invoice_summary(request_doc)
    if not submitting or _get(request_doc, "request_type") != "费用付款申请":
        return summary
    request_lines = list(_get(request_doc, "expense_lines") or [])
    explicit_manual_lines = {
        str(_get(row, "line_key") or "").strip()
        for row in request_lines
        if not str(_get(row, "source_invoice") or "").strip()
        and str(_get(row, "expense_account_level_1") or "").strip()
        and str(_get(row, "expense_description") or "").strip()
    }
    records = _request_invoice_records(_request_name(request_doc))
    included = [row for row in records if _get(row, "recognition_status") != "已排除"]
    reason = _request_reason(request_doc)
    blockers = submission_blockers(
        included,
        reason or ("已填写手工费用明细" if explicit_manual_lines else ""),
    )
    if blockers:
        _throw("；".join(blockers))
    if not included:
        return summary
    lines = {
        str(_get(row, "line_key") or "").strip(): row
        for row in request_lines
        if str(_get(row, "line_key") or "").strip()
    }
    totals = {key: Decimal("0.00") for key in lines}
    linked_counts = {key: 0 for key in lines}
    missing_totals = set()
    messages = []
    for record in included:
        line_key = str(_get(record, "expense_line_key") or "").strip()
        if not line_key:
            messages.append("存在未关联费用明细的发票")
            continue
        if line_key not in lines:
            messages.append("发票关联的费用明细不属于该报销单")
            continue
        linked_counts[line_key] += 1
        total = _decimal_money(_record_money(record, "total_amount"))
        if total is None:
            missing_totals.add(line_key)
        else:
            totals[line_key] += total
    for line_key, line in lines.items():
        reason = str(_get(line, "invoice_difference_reason") or "").strip()
        if line_key in missing_totals and not reason:
            messages.append("发票金额缺失，请填写费用明细差异说明")
            continue
        line_amount = _decimal_money(_get(line, "amount"))
        if line_amount is None:
            messages.append("费用明细金额无效")
            continue
        if linked_counts[line_key] == 0 and line_key not in missing_totals:
            if line_key in explicit_manual_lines:
                continue
            if not reason:
                messages.append("费用明细未关联发票，请填写差异说明")
            continue
        if abs(line_amount - totals[line_key]) > Decimal("0.02") and not reason:
            messages.append("费用明细金额与发票合计不一致，请填写差异说明")
    if messages:
        _throw("；".join(dict.fromkeys(messages)))
    return summary



def _request_permission(request_doc, ptype, *, current=False):
    user = _user()
    if ptype == "edit":
        allowed = invoice_permissions.can_edit_request(
            request_doc, user, current=current
        )
    else:
        allowed = invoice_permissions.can_read_request(
            request_doc, user, current=current
        )
    if not allowed:
        _throw("您无权访问该费用付款/报销单。")


def link_invoice(invoice_name, request, expense_line_key):
    invoice_name = str(invoice_name)
    request_name = str(request)
    line_key = str(expense_line_key or "").strip()

    # This first read is address/authentication only. Every decision is repeated
    # as a current read after all Redis locks are acquired, so no DB row lock is
    # held while waiting on the batch/request Redis locks.
    preliminary = _require_record(invoice_name, write=True)
    preliminary_batch = str(_get(preliminary, "batch") or "")
    with _transaction_lock("request", request_name):
        with _transaction_lock("batch", preliminary_batch):
            with _transaction_lock("record", invoice_name):
                record = _require_record(invoice_name, write=True, current=True)
                batch_name = str(_get(record, "batch") or "")
                if batch_name != preliminary_batch:
                    _throw("\u53d1\u7968\u6279\u6b21\u5df2\u53d1\u751f\u53d8\u5316\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002")
                batch = _current_doc(BATCH_DOCTYPE, batch_name)
                request_doc = _current_doc(REQUEST_DOCTYPE, request_name)
                _request_permission(request_doc, "edit", current=True)
                if _get(record, "recognition_status") != "\u5df2\u786e\u8ba4":
                    _throw("\u53ea\u6709\u5df2\u786e\u8ba4\u53d1\u7968\u53ef\u4ee5\u5173\u8054\u8d39\u7528\u660e\u7ec6\u3002")
                if _get(request_doc, "workflow_status") not in ACTIVE_REQUEST_STATUSES:
                    _throw("\u62a5\u9500\u5355\u63d0\u4ea4\u540e\u4e0d\u80fd\u8c03\u6574\u53d1\u7968\u5173\u8054\u3002")
                if line_key:
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
                        _throw("\u6240\u9009\u8d39\u7528\u660e\u7ec6\u4e0d\u5c5e\u4e8e\u8be5\u62a5\u9500\u5355\u3002")
                existing_request = str(_get(record, "request") or "")
                if existing_request and existing_request != request_name:
                    _throw("\u8be5\u53d1\u7968\u5df2\u5173\u8054\u5230\u5176\u4ed6\u62a5\u9500\u5355\u3002")
                batch_request = str(_get(batch, "request") or "")
                if batch_request and batch_request != request_name:
                    _throw("\u540c\u4e00\u53d1\u7968\u6279\u6b21\u4e0d\u80fd\u5173\u8054\u591a\u5f20\u62a5\u9500\u5355\u3002")
                _assert_request_single_batch_current(request_name, batch_name)
                _set(record, "request", request_name)
                _set(record, "expense_line_key", line_key)
                _save(record)
                if not batch_request:
                    _set(batch, "request", request_name)
                    _save(batch)
                _apply_request_invoice_summary(request_doc, save=True)
                return _serialize_record(
                    record, include_attachments=True
                )



def _read_private_record(record, *, current=False):
    file_url = _safe_file_url(_get(record, "invoice_file"))
    file_doc = _file_doc(
        file_url,
        current=current,
        attached_to_doctype=RECORD_DOCTYPE,
        attached_to_name=_get(record, "name"),
    )
    if int(_get(file_doc, "is_private") or 0) != 1: _throw("发票文件不再是私有文件。")
    if _get(file_doc, "attached_to_doctype") != RECORD_DOCTYPE or _get(file_doc, "attached_to_name") != _get(record, "name"): _throw("发票文件关联已失效。")
    content = _read_limited(file_doc); digest = hashlib.sha256(content).hexdigest()
    if digest != _get(record, "file_sha256"): _throw("发票文件内容已发生变化。")
    return file_doc, content


def get_batch(batch):
    batch_doc = _require_batch(str(batch)); records = []
    for row in _get_all(RECORD_DOCTYPE, filters={"batch": _get(batch_doc, "name")}, fields=["name"]):
        record = frappe.get_doc(RECORD_DOCTYPE, _get(row, "name"))
        if can_read_invoice(record, _user()):
            records.append(
                _serialize_record(record, include_attachments=True)
            )
    result = _serialize_batch(batch_doc)
    if _get(batch_doc, "owner") != _user():
        result.pop("temporary_token", None)
    result["records"] = records
    return result


def get_request_invoices(request):
    user = _user()
    request_doc = frappe.get_doc(REQUEST_DOCTYPE, str(request))
    _request_permission(request_doc, "read")
    result = []
    for row in _request_invoice_records(_get(request_doc, "name")):
        record = frappe.get_doc(RECORD_DOCTYPE, _get(row, "name"))
        if can_read_invoice(record, user):
            result.append(
                _serialize_record(record, include_attachments=True)
            )
    return result


def _preview_cache_key(token):
    return _lock_key("preview-token", token)


def preview_invoice(invoice_name):
    record = _require_record(str(invoice_name), current=True)
    _file_doc_value, _content = _read_private_record(record, current=True)
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


from rayher_hr_payroll import invoice_supplemental_attachments


def _serialize_record(record, include_attachments=False):
    result = {
        "name": _get(record, "name"), "batch": _get(record, "batch"), "original_filename": _get(record, "original_filename"),
        "mime_type": _get(record, "mime_type"), "file_size": int(_get(record, "file_size") or 0), "recognition_status": _get(record, "recognition_status"),
        "invoice_category": _get(record, "invoice_category") or "", "project_name": _get(record, "project_name") or "", "issue_date": _get(record, "issue_date"),
        "invoice_number": _get(record, "invoice_number") or "", "amount_before_tax": _record_money(record, "amount_before_tax"), "tax_amount": _record_money(record, "tax_amount"),
        "total_amount": _record_money(record, "total_amount"), "field_warnings": _public_field_warnings(record), "is_duplicate": bool(_get(record, "duplicate_of")),
        "expense_description": _get(record, "expense_description") or "",
        "duplicate_reason": _get(record, "duplicate_reason") or "", "request": _get(record, "request") or "", "expense_line_key": _get(record, "expense_line_key") or "",
        "processing_started_on": _get(record, "processing_started_on"), "processing_error": _get(record, "processing_error") or "",
        "retry_count": int(_get(record, "retry_count") or 0),
        "confirmed_by": _get(record, "confirmed_by") or "", "confirmed_on": _get(record, "confirmed_on"),
    }
    if include_attachments:
        result["supplemental_attachments"] = (
            invoice_supplemental_attachments.list_attachments_for_record(
                record
            )
        )
    return result
