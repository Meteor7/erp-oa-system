from __future__ import annotations

import json

import frappe

from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_LEAVE,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
)
from rayher_hr_payroll.oa_approval import REQUEST_EXPENSE_PAYMENT
from rayher_hr_payroll.oa_feature_gate import visible_request_types


REQUEST_TYPES = (
    REQUEST_LEAVE,
    REQUEST_EXPENSE_PAYMENT,
    REQUEST_PROCUREMENT,
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT_PAYMENT,
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
DRAFT_STATUS = "草稿"
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
    identity = identity if identity is not None else _active_identity(user)
    names = {str(user or "").strip()}
    full_name = frappe.db.get_value("User", user, "full_name")
    if full_name:
        names.add(str(full_name).strip())
    if identity:
        names.update(
            str(identity.get(key) or "").strip()
            for key in ("employee", "employee_name")
        )
    return {name for name in names if name}


def _sql_type_scope(allowed_types):
    table = "`tabOA Approval Request`"
    if not allowed_types:
        return "1=0"
    values = ", ".join(frappe.db.escape(value) for value in allowed_types)
    return f"{table}.request_type in ({values})"


def _sql_row_scope(user, roles, identity, actors):
    table = "`tabOA Approval Request`"
    management_reader = user == "Administrator" or bool(roles & PROCUREMENT_GLOBAL_ROLES)
    finance_reader = "Accounts User" in roles and not management_reader
    if management_reader:
        return "1=1"
    clauses = [f"{table}.owner = {frappe.db.escape(user)}"]
    if identity and identity.get("employee"):
        clauses.append(
            f"{table}.employee = {frappe.db.escape(identity['employee'])}"
        )
    clauses.append(f"{table}.purchaser_user = {frappe.db.escape(user)}")
    actor_checks = [
        "JSON_CONTAINS(step.approvers, {0})".format(
            frappe.db.escape(json.dumps(actor, ensure_ascii=False))
        )
        for actor in sorted(actors)
    ]
    if actor_checks:
        clauses.append(
            "EXISTS (SELECT 1 FROM `tabOA Approval Step` step "
            f"WHERE step.parent = {table}.name "
            "AND step.parenttype = 'OA Approval Request' "
            "AND step.parentfield = 'steps' "
            f"AND step.step_index = {table}.current_step_index "
            "AND JSON_VALID(step.approvers) "
            "AND (" + " OR ".join(actor_checks) + "))"
        )
    scoped = "(" + " OR ".join(clauses) + ")"
    if finance_reader:
        values = ", ".join(frappe.db.escape(value) for value in sorted(PROCUREMENT_APPLICATION_TYPES))
        return f"({table}.request_type not in ({values}) OR ({table}.request_type in ({values}) AND {scoped}))"
    return scoped


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
    management_reader = user == "Administrator" or bool(roles & PROCUREMENT_GLOBAL_ROLES)
    finance_reader = "Accounts User" in roles and not management_reader
    request_type = _get(doc, "request_type")
    if management_reader:
        return True
    # Accounts User is global for payment requests, not procurement demands.
    if finance_reader and request_type not in PROCUREMENT_APPLICATION_TYPES:
        return True
    if _is_owner(doc, user, identity):
        return True
    if _get(doc, "purchaser_user") == user:
        return True
    return _is_current_approver(doc, _actor_names(user, identity))


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
