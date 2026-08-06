from __future__ import annotations

import frappe

from rayher_hr_payroll.oa_approval import REQUEST_EXPENSE_PAYMENT, REQUEST_LEAVE
from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
)

ADMIN_USERS = {"Administrator", "admin@staff.example.invalid"}
DRAFT_ONLY_REQUEST_TYPES = {
    REQUEST_PROCUREMENT,
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT_PAYMENT,
}
FEATURE_CONFIG_BY_REQUEST_TYPE = {
    REQUEST_LEAVE: "leave_approval_admin_only",
    REQUEST_EXPENSE_PAYMENT: "expense_reimbursement_admin_only",
}
BOOT_FLAG_BY_REQUEST_TYPE = {
    REQUEST_LEAVE: "leave_approval",
    REQUEST_EXPENSE_PAYMENT: "expense_reimbursement",
}


def _feature_key(request_type):
    try:
        return FEATURE_CONFIG_BY_REQUEST_TYPE[request_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported OA request type: {request_type}") from exc


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off", "none"}
    return bool(value)


def is_admin_only(request_type):
    if request_type in DRAFT_ONLY_REQUEST_TYPES:
        return True
    conf = getattr(frappe, "conf", {}) or {}
    key = _feature_key(request_type)
    value = conf.get(key, 0) if hasattr(conf, "get") else getattr(conf, key, 0)
    return _truthy(value)


def can_access_request_type(request_type, user=None):
    user = user or getattr(getattr(frappe, "session", None), "user", "")
    if request_type in DRAFT_ONLY_REQUEST_TYPES:
        return user in ADMIN_USERS
    return user in ADMIN_USERS or not is_admin_only(request_type)


def require_request_type_access(request_type, user=None):
    if not can_access_request_type(request_type, user):
        frappe.throw("当前审批功能暂未开放。", frappe.PermissionError)


def visible_request_types(request_types, user=None):
    return [item for item in request_types if can_access_request_type(item, user)]


def boot_access_flags(user=None):
    return {
        BOOT_FLAG_BY_REQUEST_TYPE[item]: can_access_request_type(item, user)
        for item in FEATURE_CONFIG_BY_REQUEST_TYPE
    }


def oa_request_query(user=None):
    allowed = visible_request_types(list(FEATURE_CONFIG_BY_REQUEST_TYPE), user)
    if not allowed:
        return "1=0"
    if len(allowed) == len(FEATURE_CONFIG_BY_REQUEST_TYPE):
        return ""
    values = ", ".join(frappe.db.escape(item) for item in allowed)
    return f"`tabOA Approval Request`.request_type in ({values})"


def oa_request_has_permission(doc, ptype=None, user=None):
    request_type = doc.get("request_type") if hasattr(doc, "get") else getattr(doc, "request_type", None)
    if request_type in FEATURE_CONFIG_BY_REQUEST_TYPE and not can_access_request_type(request_type, user):
        return False
    return None