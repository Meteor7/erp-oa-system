"""看板接口：申请看板、付款看板、采购看板。

三个看板都只读，数据范围在服务端定：财务和管理层看全公司，部门主管只看本部门，
普通员工不开放（用"我的申请 / 我的报销 / 我的付款"看自己的单据）。
"""
from __future__ import annotations

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
        frappe.throw("看板只对财务、管理层和部门主管开放；本人的单据请在我的申请、我的报销、我的付款里查看。", frappe.PermissionError)
    department = ""
    if scope == "department":
        context = oa_entry._employee_context()
        department = context.get("department") or ""
        if not department:
            frappe.throw("当前账号没有部门信息，无法查看本部门看板。", frappe.PermissionError)
    return scope, department


def _rows(request_types, scope, department, *, extra_filters=None):
    filters = {"request_type": ["in", list(request_types)]}
    if scope == "department" and department:
        filters["department"] = department
    filters.update(extra_filters or {})
    return frappe.get_all("OA Approval Request", filters=filters, fields=ROW_FIELDS,
                          order_by="modified desc", limit_page_length=LIMIT)


def _step_timestamps(names):
    """Per request: when the current step started waiting, and when the last step was signed."""
    if not names:
        return {}
    rows = frappe.get_all(
        "OA Approval Step",
        filters={"parent": ["in", names], "parenttype": "OA Approval Request"},
        fields=["parent", "step_index", "status", "acted_on"],
        limit_page_length=0,
    )
    stamps = {}
    for row in rows:
        acted = boards.as_date(row.get("acted_on"))
        if not acted:
            continue
        item = stamps.setdefault(row["parent"], {"last_acted": acted})
        if acted > item["last_acted"]:
            item["last_acted"] = acted
    return stamps


def _decorate(rows, today):
    stamps = _step_timestamps([row["name"] for row in rows])
    for row in rows:
        stamp = stamps.get(row["name"], {})
        started = stamp.get("last_acted") or boards.as_date(row.get("creation"))
        row["waited_days"] = max(0, (today - started).days) if started else 0
        row["approved_on"] = stamp.get("last_acted") or boards.as_date(row.get("modified"))
        row["asset_classification"] = (
            row.get("fixed_asset_category") or ("非固定资产" if row.get("asset_nature") == "非固定资产" else row.get("asset_category")) or "未分类"
        )
    return rows


def _ledger_amounts(rows):
    """Reserved / paid per 购买申请, straight from the amount ledger."""
    for row in rows:
        row["reserved_amount"] = 0
        row["paid_amount"] = 0
    purchases = [row for row in rows if row["request_type"] == REQUEST_DIRECT_PURCHASE and row["workflow_status"] == "已完成"]
    for row in purchases:
        try:
            balance = approval_amount_ledger.source_balance(row["name"], store=approval_amount_ledger.WorkflowLedgerStore())
        except approval_amount_ledger.ApprovalAmountError:
            continue
        row["reserved_amount"] = float(balance["reserved_amount"])
        row["paid_amount"] = float(balance["paid_amount"])
    return rows


def _travel_claimed(rows):
    """How much each 出差申请 has actually paid out through its 报销单 / 付款单."""
    travels = [row for row in rows if row["request_type"] == REQUEST_TRAVEL]
    names = [row["name"] for row in travels]
    if not names:
        return rows
    claims = frappe.get_all(
        "OA Approval Request",
        filters={"request_type": ["in", [REQUEST_REIMBURSEMENT, REQUEST_PAYMENT]],
                 "source_request": ["in", names], "workflow_status": "已付款"},
        fields=["source_request", "amount"], limit_page_length=0,
    )
    totals = {}
    for claim in claims:
        totals[claim["source_request"]] = totals.get(claim["source_request"], 0) + float(claim["amount"] or 0)
    for row in travels:
        row["paid_amount"] = totals.get(row["name"], 0)
    return rows


@frappe.whitelist()
def request_board():
    """申请看板：购买申请与出差申请。采购申请在采购看板里。"""
    scope, department = _scope()
    today = getdate(nowdate())
    types = [request_type for request_type in boards.APPLICATION_TYPES if can_access_request_type(request_type)]
    rows = _decorate(_rows(types, scope, department), today)
    _ledger_amounts(rows)
    _travel_claimed(rows)
    result = boards.request_board(rows, today=today)
    result["scope"] = scope
    result["department"] = department
    return result


@frappe.whitelist()
def payment_board():
    """付款看板：报销单与付款单，金额按实际付款日期计入月份。"""
    scope, department = _scope()
    today = getdate(nowdate())
    types = [request_type for request_type in boards.CLAIM_TYPES if can_access_request_type(request_type)]
    rows = _decorate(_rows(types, scope, department), today)
    names = [row["name"] for row in rows if row["workflow_status"] == "已付款"]
    lines = frappe.get_all(
        "OA Approval Expense Line",
        filters={"parent": ["in", names or [""]], "parenttype": "OA Approval Request"},
        fields=["parent", "expense_account_level_1", "expense_account_level_2", "total_amount", "claim_project"],
        limit_page_length=0,
    ) if names else []
    result = boards.payment_board(rows, lines, today=today)
    result["scope"] = scope
    result["department"] = department
    return result


@frappe.whitelist()
def procurement_board():
    """采购看板：采购申请与采购付款单独统计，不和购买、报销、付款混在一起。"""
    scope, department = _scope()
    today = getdate(nowdate())
    types = [request_type for request_type in boards.PROCUREMENT_TYPES if can_access_request_type(request_type)]
    rows = _decorate(_rows(types, scope, department), today)
    result = boards.procurement_board(rows, today=today)
    result["scope"] = scope
    result["department"] = department
    return result
