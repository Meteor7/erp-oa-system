"""出差申请接口：保存草稿。提交、审批、撤回沿用 oa_entry 的通用接口。"""
from __future__ import annotations

import json

import frappe

from rayher_hr_payroll.api import oa_entry
from rayher_hr_payroll.oa_document_types import REQUEST_TRAVEL
from rayher_hr_payroll.oa_feature_gate import require_request_type_access
from rayher_hr_payroll.travel_requests import TravelRequestError, normalize_travel


def _payload(value):
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except ValueError:
            frappe.throw("出差申请数据格式无效。")
    if not isinstance(value, dict):
        frappe.throw("出差申请数据格式无效。")
    return value


def _values(payload):
    try:
        values = normalize_travel(_payload(payload))
    except TravelRequestError as exc:
        frappe.throw(str(exc))
    if values["project"] and not frappe.db.exists("Project", values["project"]):
        frappe.throw("所属项目不存在。")
    return values


@frappe.whitelist(methods=["POST"])
def save_travel_draft(payload, name=None):
    require_request_type_access(REQUEST_TRAVEL)
    values = _values(payload)
    draft_name = oa_entry._bounded_optional_text(name, "草稿编号", 140) if name else ""
    if draft_name:
        with oa_entry.invoice_service._transaction_lock("request", draft_name):
            doc = oa_entry._load_request(draft_name, current=True)
            if doc.request_type != REQUEST_TRAVEL:
                frappe.throw("这张单据不是出差申请。")
            oa_entry.invoice_service._request_permission(doc, "edit", current=True)
            if doc.workflow_status != oa_entry.STATUS_DRAFT:
                frappe.throw("只有草稿可以修改。")
            doc.update(values)
            oa_entry._save_document(doc)
            return oa_entry._summarize_doc(doc)
    ctx = oa_entry._route_context(request_type=REQUEST_TRAVEL)
    doc = frappe.get_doc({
        "doctype": "OA Approval Request",
        "request_type": REQUEST_TRAVEL,
        "workflow_status": oa_entry.STATUS_DRAFT,
        "employee": ctx.get("employee"),
        "employee_name": ctx.get("employee_name"),
        "department": ctx.get("department"),
        "supervisor": ctx.get("supervisor"),
        "company": oa_entry.COMPANIES[0],
        "urgency": oa_entry.URGENCY[0],
        "amount": 0,
        "currency": "CNY",
        "business_status": "",
        **values,
    })
    oa_entry._insert_document(doc)
    return oa_entry._summarize_doc(doc)
