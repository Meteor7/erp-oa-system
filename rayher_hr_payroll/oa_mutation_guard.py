from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import frappe

from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_LEAVE,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
)


DRAFT_STATUS = "草稿"
CLOSED_REQUEST_TYPES = set()
SERVER_OWNED_FIELDS = {
    "attendance_days", "duration_hours",
    "request_type",
    "company",
    "employee",
    "employee_name",
    "department",
    "supervisor",
    "copied_to",
    "workflow_status",
    "current_step_index",
    "current_step_label",
    "steps",
    "amount",
    "currency",
    "approved_amount",
    "approved_amount_snapshot",
    "payment_source_kind",
    "source_request",
    "source_modified",
    "paid_by",
    "paid_on",
    "source_type",
    "source_summary",
    "invoice_count",
    "invoice_status",
    "expense_lines",
    "business_lines",
    "direct_purchase_lines",
    "operation_log",
    "business_status",
    "project_owner",
    "project_owner_name",
    "contract_delivery_date",
    "pending_contract_delivery_date",
    "delivery_change_reason",
    "arrival_status",
    "inspection_status",
    "prepayment_writeoff_status",
    "ordered_quantity",
    "received_quantity",
    "arrival_date",
    "inspection_failure_reason",
    "exception_direction",
    "followup_status",
    "travel_days",
    "invoice_difference_note",
}
DRAFT_ONLY_BUSINESS_FIELDS = {
    "from_date", "to_date", "leave_type",
    "subject", "reason", "urgency", "asset_nature", "fixed_asset_category",
    "asset_category", "procurement_scope", "expected_delivery_date", "project",
    "non_project_allocation_type", "non_project_cost_center",
    "non_project_department", "purchaser_user", "purchase_method", "supplier",
    "payment_stage", "prepayment_percentage", "has_balance_payment",
    "expected_arrival_date", "prepayment_risk_note", "source_request",
    "business_lines",
    "direct_purchase_lines",
    "travel_destination", "travel_start_date", "travel_end_date",
}

NEW_DOCUMENT_ALLOWED_VALUES = {
    "workflow_status": {None, "", DRAFT_STATUS},
    "current_step_index": {None, "", 0, "0"},
    "current_step_label": {None, ""},
    "steps": {None, ""},
    "operation_log": {None, "", "[]"},
}


def _get(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    getter = getattr(value, "get", None)
    if callable(getter):
        result = getter(key)
        return default if result is None else result
    return getattr(value, key, default)


def _normal(value):
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if isinstance(value, dict):
        return {key: _normal(item) for key, item in value.items() if key not in {"modified", "modified_by"}}
    if isinstance(value, (list, tuple)):
        return [_normal(item) for item in value]
    return value


def _empty(value):
    return value in (None, "", 0, "0", False) or value == [] or value == {}


def _flag_store():
    flags = getattr(frappe, "flags", None)
    if flags is None:
        flags = SimpleNamespace()
        frappe.flags = flags
    return flags


def _authorized():
    return bool(getattr(_flag_store(), "oa_authorized_action", False))


@contextmanager
def authorized_oa_action():
    flags = _flag_store()
    previous = getattr(flags, "oa_authorized_action", False)
    flags.oa_authorized_action = True
    try:
        yield
    finally:
        if previous:
            flags.oa_authorized_action = previous
        else:
            try:
                delattr(flags, "oa_authorized_action")
            except AttributeError:
                flags.oa_authorized_action = False


def _closed_route_is_not_draft(doc):
    if _get(doc, "request_type") not in CLOSED_REQUEST_TYPES:
        return False
    if _get(doc, "workflow_status") != DRAFT_STATUS:
        return True
    if not _empty(_get(doc, "current_step_index")):
        return True
    if not _empty(_get(doc, "current_step_label")):
        return True
    if not _empty(_get(doc, "steps")):
        return True
    if not _empty(_get(doc, "approved_amount")):
        return True
    if not _empty(_get(doc, "paid_by")) or not _empty(_get(doc, "paid_on")):
        return True
    return False


def _new_document_has_server_values(doc):
    for field in SERVER_OWNED_FIELDS:
        value = _get(doc, field)
        if field == "request_type":
            continue
        if field in NEW_DOCUMENT_ALLOWED_VALUES:
            allowed = NEW_DOCUMENT_ALLOWED_VALUES[field]
            if field == "steps" and value == []:
                continue
            if value in allowed:
                continue
            return True
        if not _empty(value):
            return True
    return False


def _changed_business_fields(doc, before):
    return [
        field
        for field in sorted(DRAFT_ONLY_BUSINESS_FIELDS)
        if _normal(_get(doc, field)) != _normal(_get(before, field))
    ]


def _changed_server_fields(doc, before):
    return [
        field
        for field in sorted(SERVER_OWNED_FIELDS)
        if _normal(_get(doc, field)) != _normal(_get(before, field))
    ]


def validate_request_mutation(doc):
    if _authorized():
        return

    if _closed_route_is_not_draft(doc):
        frappe.throw("审批流程尚未启用，当前仅可保存草稿。", frappe.PermissionError)

    before_getter = getattr(doc, "get_doc_before_save", None)
    before = before_getter() if callable(before_getter) else None
    if before is None:
        if _new_document_has_server_values(doc):
            frappe.throw("禁止客户端写入审批服务端字段。", frappe.PermissionError)
        return

    if _get(before, "workflow_status") != DRAFT_STATUS:
        business_changes = _changed_business_fields(doc, before)
        if business_changes:
            frappe.throw(
                "禁止修改审批中业务字段：" + "、".join(business_changes)
                + "；请先定向驳回申请人后重新提交。",
                frappe.PermissionError,
            )

    changed = _changed_server_fields(doc, before)
    if changed:
        frappe.throw(
            "禁止客户端写入审批服务端字段：" + "、".join(changed),
            frappe.PermissionError,
        )
