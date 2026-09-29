from __future__ import annotations

import json

from rayher_hr_payroll.approval_identity import approval_actor_ids

import frappe

from rayher_hr_payroll.attendance_requests import ATTENDANCE_TYPES, REQUEST_OVERTIME, REQUEST_COMP_TIME

from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_LEAVE,
    REQUEST_PAYMENT,
    REQUEST_PROCUREMENT,
    REQUEST_REIMBURSEMENT,
    REQUEST_TRAVEL,
    REQUEST_PROCUREMENT_PAYMENT,
)
from rayher_hr_payroll.oa_approval import REQUEST_EXPENSE_PAYMENT
from rayher_hr_payroll.oa_feature_gate import visible_request_types


REQUEST_TYPES = (
    REQUEST_OVERTIME, REQUEST_COMP_TIME,
    REQUEST_LEAVE,
    REQUEST_EXPENSE_PAYMENT,
    REQUEST_PROCUREMENT,
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT_PAYMENT,
    REQUEST_TRAVEL,
    REQUEST_REIMBURSEMENT,
    REQUEST_PAYMENT,
)
PRIVILEGED_READ_ROLES = {
    "System Manager",
    "HR Manager",
    "HR User",
    "Accounts User",
    "Rayher Business Executive",
}
HR_SCOPED_ROLES = {"HR Manager", "HR User"}
PROCUREMENT_REQUEST_TYPES = {REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE, REQUEST_PROCUREMENT_PAYMENT}
PROCUREMENT_APPLICATION_TYPES = {REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE}
PROCUREMENT_GLOBAL_ROLES = {"System Manager", "Purchase User", "Purchase Manager", "Rayher Business Executive"}
GLOBAL_READ_ROLES = {"System Manager", "Rayher Business Executive"}
PAYMENT_REQUEST_TYPES = {REQUEST_EXPENSE_PAYMENT, REQUEST_PROCUREMENT_PAYMENT}
# 报销单、付款单：财务只看提交后的单据，草稿只有申请人自己能看。
CLAIM_REQUEST_TYPES = {REQUEST_REIMBURSEMENT, REQUEST_PAYMENT}
ACTIVE_STATUSES = {"待审批", "待办理"}
DRAFT_STATUS = "草稿"
# 财务只能看已提交的这些类型（草稿里有收款账户，只给申请人自己看）。
FINANCE_SUBMITTED_ONLY_TYPES = {REQUEST_EXPENSE_PAYMENT}
READ_PTYPES = {None, "read", "select", "report", "export", "print", "email"}


def _get(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    getter = getattr(value, "get", None)
    if callable(getter):
        result = getter(key)
        return default if result is None else result
    return getattr(value, key, default)


def _roles(user):
    return set(frappe.get_roles(user) or [])


def _active_identity(user):
    rows = frappe.get_all(
        "Employee",
        filters={"user_id": user, "status": "Active"},
        fields=["name", "employee_name"],
        limit_page_length=2,
    )
    if len(rows) != 1:
        return None
    row = rows[0]
    return {
        "employee": _get(row, "name"),
        "employee_name": _get(row, "employee_name"),
    }


def _actor_names(user, identity=None):
    return approval_actor_ids(user)



def _sql_type_scope(allowed_types):
    table = "`tabOA Approval Request`"
    if not allowed_types:
        return "1=0"
    values = ", ".join(frappe.db.escape(value) for value in allowed_types)
    return f"{table}.request_type in ({values})"


def _sql_current_step(actors, *, pending=False):
    table = "`tabOA Approval Request`"
    checks = [
        "JSON_CONTAINS(CASE WHEN JSON_VALID(step.approvers) THEN step.approvers ELSE '[]' END, "
        + frappe.db.escape(json.dumps(actor, ensure_ascii=False)) + ")"
        for actor in sorted(actors)
    ]
    if not checks:
        return "1=0"
    unsigned = ""
    if pending:
        signed_checks = [check.replace("step.approvers", "step.approved_by") for check in checks]
        unsigned = " AND NOT (" + " OR ".join(signed_checks) + ")"
    return (
        f"{table}.workflow_status IN ('待审批', '待办理') AND EXISTS ("
        "SELECT 1 FROM `tabOA Approval Step` step "
        f"WHERE step.parent = {table}.name "
        "AND step.parenttype = 'OA Approval Request' AND step.parentfield = 'steps' "
        f"AND step.step_index = {table}.current_step_index "
        "AND (" + " OR ".join(checks) + ")" + unsigned + ")"
    )


def _sql_involvement(actors, escape=None):
    """抄送给了这个人，或他在任一节点审批、办理过（修复 2026-09-29，审查 R3-57，决定 D3）。

    原来只有申请人、采购经办人、财务和当前审批人能看：抄送人点通知链接提示无权限，
    主管批完以后也看不到这张单据后来的结果。这两类人现在只读可见。
    """
    table = "`tabOA Approval Request`"
    escape = escape or frappe.db.escape
    if not actors:
        return "1=0"
    copied = [
        f"JSON_CONTAINS(CASE WHEN JSON_VALID({table}.copied_to) THEN {table}.copied_to ELSE '[]' END, "
        + escape(json.dumps({"user": actor}, ensure_ascii=False)) + ")"
        for actor in sorted(actors)
    ]
    acted = [
        "JSON_CONTAINS(CASE WHEN JSON_VALID(step.approved_by) THEN step.approved_by ELSE '[]' END, "
        + escape(json.dumps(actor, ensure_ascii=False)) + ")"
        for actor in sorted(actors)
    ] + [f"step.action_by = {escape(actor)}" for actor in sorted(actors)]
    return (
        "(" + " OR ".join(copied) + " OR EXISTS ("
        "SELECT 1 FROM `tabOA Approval Step` step "
        f"WHERE step.parent = {table}.name "
        "AND step.parenttype = 'OA Approval Request' AND step.parentfield = 'steps' "
        "AND (" + " OR ".join(acted) + ")))"
    )


def _sql_row_scope(user, roles, identity, actors):
    table = "`tabOA Approval Request`"
    if user == "Administrator" or roles & GLOBAL_READ_ROLES:
        return "1=1"
    clauses = [f"{table}.owner = {frappe.db.escape(user)}"]
    if identity and identity.get("employee"):
        clauses.append(f"{table}.employee = {frappe.db.escape(identity['employee'])}")
    procurement = _sql_type_scope(PROCUREMENT_REQUEST_TYPES)
    clauses.append(f"({procurement} AND {table}.purchaser_user = {frappe.db.escape(user)})")
    if roles & PROCUREMENT_GLOBAL_ROLES:
        clauses.append(procurement)
    if "Accounts User" in roles:
        # 修复（2026-09-24，审查第三轮 Codex-A）：财务原来能看到别人未提交的费用付款申请草稿
        # （含收款账户），现在和报销单、付款单一样只看已提交的。采购付款不变。
        clauses.append(_sql_type_scope(PAYMENT_REQUEST_TYPES - FINANCE_SUBMITTED_ONLY_TYPES))
        clauses.append(
            "(" + _sql_type_scope(CLAIM_REQUEST_TYPES | FINANCE_SUBMITTED_ONLY_TYPES)
            + f" AND {table}.workflow_status != " + frappe.db.escape(DRAFT_STATUS) + ")"
        )
    clauses.append("(" + _sql_current_step(actors) + ")")
    clauses.append(_sql_involvement(actors))
    return "(" + " OR ".join(clauses) + ")"


def oa_request_query(user=None):
    user = user or frappe.session.user
    if not user or user == "Guest":
        return "1=0"
    allowed_types = visible_request_types(REQUEST_TYPES, user)
    type_scope = _sql_type_scope(allowed_types)
    if type_scope == "1=0":
        return type_scope
    roles = _roles(user)
    identity = _active_identity(user)
    row_scope = _sql_row_scope(user, roles, identity, _actor_names(user, identity))
    return f"({type_scope}) AND ({row_scope})"


def _parse_approvers(value):
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item or "").strip()}
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(item).strip() for item in parsed if str(item or "").strip()}


def _is_current_approver(doc, actors):
    if _get(doc, "workflow_status") not in ACTIVE_STATUSES:
        return False
    try:
        current = int(_get(doc, "current_step_index") or 0)
    except (TypeError, ValueError):
        return False
    for step in list(_get(doc, "steps", []) or []):
        try:
            index = int(_get(step, "step_index") or 0)
        except (TypeError, ValueError):
            continue
        if index == current and (_parse_approvers(_get(step, "approvers")) & actors):
            return True
    return False


def _is_involved(doc, actors):
    """Python 版的 _sql_involvement：抄送人，或在任一节点审批、办理过的人。"""
    if not actors:
        return False
    try:
        copied = json.loads(_get(doc, "copied_to") or "[]") if isinstance(_get(doc, "copied_to"), str) else (_get(doc, "copied_to") or [])
    except (TypeError, ValueError, json.JSONDecodeError):
        copied = []
    for row in copied if isinstance(copied, list) else []:
        user = row.get("user") if isinstance(row, dict) else row
        if str(user or "").strip() in actors:
            return True
    for step in list(_get(doc, "steps", []) or []):
        if _parse_approvers(_get(step, "approved_by")) & actors:
            return True
        if str(_get(step, "action_by") or "").strip() in actors:
            return True
    return False


def _is_owner(doc, user, identity):
    if _get(doc, "owner") == user:
        return True
    return bool(
        identity
        and identity.get("employee")
        and _get(doc, "employee") == identity["employee"]
    )


def _is_applicant(doc, user, identity):
    employee = _get(doc, "employee")
    if employee:
        return bool(identity and identity.get("employee") == employee)
    return _get(doc, "owner") == user


def _can_read(doc, user, roles, identity):
    request_type = _get(doc, "request_type")
    if user == "Administrator" or roles & GLOBAL_READ_ROLES:
        return True
    if request_type in PROCUREMENT_REQUEST_TYPES and roles & PROCUREMENT_GLOBAL_ROLES:
        return True
    if request_type in PAYMENT_REQUEST_TYPES - FINANCE_SUBMITTED_ONLY_TYPES and "Accounts User" in roles:
        return True
    if (
        request_type in CLAIM_REQUEST_TYPES | FINANCE_SUBMITTED_ONLY_TYPES
        and "Accounts User" in roles
        and _get(doc, "workflow_status") != DRAFT_STATUS
    ):
        return True
    if _is_owner(doc, user, identity):
        return True
    if request_type in PROCUREMENT_REQUEST_TYPES and _get(doc, "purchaser_user") == user:
        return True
    actors = _actor_names(user, identity)
    return _is_current_approver(doc, actors) or _is_involved(doc, actors)


def oa_request_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if not user or user == "Guest":
        return False
    request_type = _get(doc, "request_type")
    if request_type not in visible_request_types(REQUEST_TYPES, user):
        return False
    if user == "Administrator":
        return None
    roles = _roles(user)
    identity = _active_identity(user)
    if ptype in READ_PTYPES:
        if request_type == REQUEST_PROCUREMENT and _get(doc, "purchaser_user") == user:
            return True
        return None if _can_read(doc, user, roles, identity) else False
    if ptype == "create":
        return None if _is_applicant(doc, user, identity) else False
    if ptype == "write":
        return None if _is_applicant(doc, user, identity) and _get(doc, "workflow_status") == DRAFT_STATUS else False
    return False
