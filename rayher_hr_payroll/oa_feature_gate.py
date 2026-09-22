from __future__ import annotations

import frappe

from rayher_hr_payroll.attendance_requests import ATTENDANCE_TYPES, REQUEST_OVERTIME, REQUEST_COMP_TIME

from rayher_hr_payroll.oa_approval import REQUEST_EXPENSE_PAYMENT, REQUEST_LEAVE
from rayher_hr_payroll.oa_document_types import (
    OPT_IN_REQUEST_TYPES,
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PAYMENT,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
    REQUEST_REIMBURSEMENT,
    REQUEST_TRAVEL,
)

ADMIN_USERS = {"Administrator", "admin@staff.example.invalid"}
DRAFT_ONLY_REQUEST_TYPES = set()
FEATURE_CONFIG_BY_REQUEST_TYPE = {
    REQUEST_OVERTIME: "leave_approval_admin_only",
    REQUEST_COMP_TIME: "leave_approval_admin_only",
    REQUEST_LEAVE: "leave_approval_admin_only",
    REQUEST_EXPENSE_PAYMENT: "expense_reimbursement_admin_only",
    REQUEST_PROCUREMENT: "procurement_application_admin_only",
    REQUEST_DIRECT_PURCHASE: "direct_purchase_application_admin_only",
    REQUEST_PROCUREMENT_PAYMENT: "procurement_payment_admin_only",
    # Opt-in types: closed to everyone but the admin accounts until the site
    # config key is set to a truthy value.
    REQUEST_TRAVEL: "travel_application_enabled",
    REQUEST_REIMBURSEMENT: "reimbursement_request_enabled",
    REQUEST_PAYMENT: "payment_request_enabled",
}
BOOT_FLAG_BY_REQUEST_TYPE = {
    REQUEST_OVERTIME: "overtime_approval",
    REQUEST_COMP_TIME: "comp_time_approval",
    REQUEST_LEAVE: "leave_approval",
    REQUEST_EXPENSE_PAYMENT: "expense_reimbursement",
    REQUEST_PROCUREMENT: "procurement_application",
    REQUEST_DIRECT_PURCHASE: "direct_purchase_application",
    REQUEST_PROCUREMENT_PAYMENT: "procurement_payment",
    REQUEST_TRAVEL: "travel_application",
    REQUEST_REIMBURSEMENT: "reimbursement_request",
    REQUEST_PAYMENT: "payment_request",
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
    conf = getattr(frappe, "conf", {}) or {}
    key = _feature_key(request_type)
    value = conf.get(key, 0) if hasattr(conf, "get") else getattr(conf, key, 0)
    if request_type in OPT_IN_REQUEST_TYPES:
        return not _truthy(value)
    return _truthy(value)


def can_access_request_type(request_type, user=None):
    if request_type not in FEATURE_CONFIG_BY_REQUEST_TYPE:
        raise ValueError(f"Unsupported OA request type: {request_type}")
    user = user or getattr(getattr(frappe, "session", None), "user", "")
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
