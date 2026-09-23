"""看板接口：申请看板、付款看板，以及各自的"采购"页签。

看板只读，数据范围在服务端定：财务和管理层看全公司，部门主管只看本部门，普通员工
不开放（员工用"我的出差申请 / 我的报销 / 我的付款"看自己的单据）。
"""
from __future__ import annotations

import re

import frappe
from frappe.utils import getdate, nowdate

from rayher_hr_payroll import approval_amount_ledger, expense_boards as boards
from rayher_hr_payroll.api import oa_entry
from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PAYMENT,
    REQUEST_REIMBURSEMENT,
    REQUEST_TRAVEL,
)
from rayher_hr_payroll.oa_feature_gate import can_access_request_type
from rayher_hr_payroll.position_access import position_users

ROW_FIELDS = [
    "name", "request_type", "subject", "employee", "employee_name", "department", "workflow_status",
    "business_status", "amount", "approved_amount", "asset_category", "asset_nature",
    "fixed_asset_category", "urgency", "paid_on", "payee_name", "invoice_followup_status",
    "expected_invoice_date", "travel_destination", "travel_start_date", "travel_end_date",
    "travel_days", "current_step_label", "current_step_index", "arrival_status", "inspection_status",
    "prepayment_writeoff_status", "creation", "modified", "project",
]
LIMIT = 2000
REMINDER_KEY = re.compile(r"\[invoice-due:([^:\]]+):")


def _positions(user):
    held = {}
    for key in boards.SCOPE_ALL_POSITIONS:
        try:
            held[key] = user in set(position_users(key) or [])
        except Exception:
            held[key] = False
    return held


def _scope():
    user = frappe.session.user
    roles = set(frappe.get_roles(user) or [])
    if user in {"Administrator", "admin@staff.example.invalid"}:
        return "all", ""
    scope = boards.board_scope(roles, _positions(user))
    if scope == "none":
        frappe.throw("看板只对财务、管理层和部门主管开放；本人的单据请在我的出差申请、我的报销、我的付款里查看。", frappe.PermissionError)
    department = ""
    if scope == "department":
        department = oa_entry._employee_context().get("department") or ""
        if not department:
            frappe.throw("当前账号没有部门信息，无法查看本部门看板。", frappe.PermissionError)
    return scope, department


def _rows(request_types, scope, department):
    request_types = [request_type for request_type in request_types if can_access_request_type(request_type)]
    if not request_types:
        return []
    filters = {"request_type": ["in", request_types]}
    if scope == "department" and department:
        filters["department"] = department
    return frappe.get_all("OA Approval Request", filters=filters, fields=ROW_FIELDS,
                          order_by="modified desc", limit_page_length=LIMIT)


def _decorate(rows, today):
    """waited_days = days since the current step started; approved_on = when the last step was signed."""
    names = [row["name"] for row in rows]
    stamps = {}
    if names:
        for step in frappe.get_all(
            "OA Approval Step",
            filters={"parent": ["in", names], "parenttype": "OA Approval Request"},
            fields=["parent", "acted_on"], limit_page_length=0,
        ):
            acted = boards.as_date(step.get("acted_on"))
            if acted and (step["parent"] not in stamps or acted > stamps[step["parent"]]):
                stamps[step["parent"]] = acted
    for row in rows:
        started = stamps.get(row["name"]) or boards.as_date(row.get("creation"))
        row["waited_days"] = max(0, (today - started).days) if started else 0
        row["approved_on"] = stamps.get(row["name"]) or boards.as_date(row.get("modified"))
    return rows


def _ledger_amounts(rows):
    for row in rows:
        row.setdefault("reserved_amount", 0)
        row.setdefault("paid_amount", 0)
        if row["request_type"] != REQUEST_DIRECT_PURCHASE or row["workflow_status"] != "已完成":
            continue
        try:
            balance = approval_amount_ledger.source_balance(row["name"], store=approval_amount_ledger.WorkflowLedgerStore())
        except approval_amount_ledger.ApprovalAmountError:
            continue
        row["reserved_amount"] = float(balance["reserved_amount"])
        row["paid_amount"] = float(balance["paid_amount"])


def _travel_claimed(rows):
    travels = {row["name"]: row for row in rows if row["request_type"] == REQUEST_TRAVEL}
    if not travels:
        return
    for claim in frappe.get_all(
        "OA Approval Request",
        filters={"request_type": ["in", [REQUEST_REIMBURSEMENT, REQUEST_PAYMENT]],
                 "source_request": ["in", list(travels)], "workflow_status": "已付款"},
        fields=["source_request", "amount"], limit_page_length=0,
    ):
        row = travels[claim["source_request"]]
        row["paid_amount"] = float(row.get("paid_amount") or 0) + float(claim["amount"] or 0)


def _reminder_counts(names):
    counts = {}
    if not names:
        return counts
    for subject in frappe.get_all(
        "Notification Log",
        filters={"document_type": "OA Approval Request", "document_name": ["in", names], "subject": ["like", "%[invoice-due:%"]},
        pluck="subject", limit_page_length=0,
    ):
        match = REMINDER_KEY.search(subject or "")
        if match:
            counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    return counts


def _result(result, scope, department):
    result["scope"] = scope
    result["department"] = department
    return result


@frappe.whitelist()
def request_board():
    """申请看板：购买申请与出差申请。"""
    scope, department = _scope()
    today = getdate(nowdate())
    rows = _decorate(_rows(boards.APPLICATION_TYPES, scope, department), today)
    _ledger_amounts(rows)
    _travel_claimed(rows)
    return _result(boards.request_board(rows, today=today), scope, department)


@frappe.whitelist()
def payment_board():
    """付款看板：报销单与付款单，金额按实际付款日期计入月份。"""
    scope, department = _scope()
    today = getdate(nowdate())
    rows = _decorate(_rows(boards.CLAIM_TYPES, scope, department), today)
    paid = [row["name"] for row in rows if row["workflow_status"] == "已付款"]
    lines = frappe.get_all(
        "OA Approval Expense Line",
        filters={"parent": ["in", paid], "parenttype": "OA Approval Request"},
        fields=["parent", "expense_account_level_1", "expense_account_level_2", "total_amount"],
        limit_page_length=0,
    ) if paid else []
    pending_invoices = [row["name"] for row in rows if row.get("invoice_followup_status") == "待收票"]
    return _result(boards.payment_board(rows, lines, today=today, reminders=_reminder_counts(pending_invoices)), scope, department)


@frappe.whitelist()
def procurement_board():
    """采购页签：采购申请与采购付款单独统计。"""
    scope, department = _scope()
    today = getdate(nowdate())
    rows = _decorate(_rows(boards.PROCUREMENT_TYPES, scope, department), today)
    return _result(boards.procurement_board(rows, today=today), scope, department)
