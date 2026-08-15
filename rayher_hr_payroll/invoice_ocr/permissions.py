"""Row-level visibility for private invoice OCR records and their view logs."""

import json

import frappe

from rayher_hr_payroll.oa_approval import REQUEST_EXPENSE_PAYMENT
from rayher_hr_payroll.oa_feature_gate import can_access_request_type

_BATCH = "OA Invoice Import Batch"
_RECORD = "OA Invoice Record"
_VIEW_LOG = "OA Invoice View Log"
_HIGH_PRIVILEGE_ROLES = {"System Manager", "Accounts User", "HR User", "HR Manager", "Rayher Business Executive"}


def _get(doc, field, default=None):
    if hasattr(doc, "get"):
        return doc.get(field, default)
    return getattr(doc, field, default)


def _roles(user):
    return set(frappe.get_roles(user) or [])


def _is_high_privilege(user, roles=None):
    return user == "Administrator" or bool((roles if roles is not None else _roles(user)) & _HIGH_PRIVILEGE_ROLES)


def _locking_kwargs(current):
    return {"for_update": True} if current else {}


def _identity(user, *, current=False):
    row = frappe.db.get_value(
        "Employee",
        {"user_id": user},
        ["name", "employee_name", "department"],
        as_dict=True,
        **_locking_kwargs(current),
    )
    employee = dict(row) if row else {}
    full_name = frappe.db.get_value(
        "User", user, "full_name", **_locking_kwargs(current)
    )
    actors = {user}
    for value in (employee.get("name"), employee.get("employee_name"), full_name):
        if str(value or "").strip():
            actors.add(str(value).strip())
    return {
        "employee": employee.get("name"),
        "employee_name": employee.get("employee_name"),
        "department": employee.get("department"),
        "actors": actors,
    }


def _request_row(request_name, *, current=False):
    if not request_name:
        return None
    return frappe.db.get_value(
        "OA Approval Request",
        request_name,
        ["name", "owner", "employee", "department", "current_step_index"],
        as_dict=True,
        **_locking_kwargs(current),
    )


def _current_approvers(request_name, step_index, *, current=False):
    if not request_name or not step_index:
        return set()
    value = frappe.db.get_value(
        "OA Approval Step",
        {
            "parent": request_name,
            "parenttype": "OA Approval Request",
            "parentfield": "steps",
            "step_index": int(step_index),
        },
        "approvers",
        **_locking_kwargs(current),
    )
    if not value:
        return set()
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(item).strip() for item in parsed if str(item or "").strip()}


def _request_access_context(request, user, *, current=False):
    request_doc = (
        _request_row(request, current=current)
        if isinstance(request, str)
        else request
    )
    if not request_doc:
        return None, None, set()
    identity = _identity(user, current=current)
    approvers = _current_approvers(
        _get(request_doc, "name"),
        _get(request_doc, "current_step_index"),
        current=current,
    )
    return request_doc, identity, approvers


def _can_read_request(request_name, user, roles=None, *, current=False):
    roles = roles if roles is not None else _roles(user)
    if _is_high_privilege(user, roles):
        return True
    request, identity, approvers = _request_access_context(
        request_name, user, current=current
    )
    if not request:
        return False
    if _get(request, "owner") == user:
        return True
    if identity.get("employee") and _get(request, "employee") == identity["employee"]:
        return True
    if (
        "Department Manager" in roles
        and identity.get("department")
        and _get(request, "department") == identity["department"]
    ):
        return True
    return bool(identity["actors"] & approvers)


def _effective_request(doc, doctype, *, current=False):
    request_name = str(_get(doc, "request") or "").strip()
    if request_name or doctype != _RECORD:
        return request_name
    batch = _get(doc, "batch")
    if not batch:
        return ""
    return str(
        frappe.db.get_value(
            _BATCH, batch, "request", **_locking_kwargs(current)
        ) or ""
    ).strip()


def _record_doc(name, *, current=False):
    row = frappe.db.get_value(
        _RECORD,
        name,
        ["name", "owner", "request", "batch"],
        as_dict=True,
        **_locking_kwargs(current),
    )
    if not row:
        return None
    result = dict(row)
    result["doctype"] = _RECORD
    return result


def can_read_invoice(doc, user=None, *, current=False):
    """Return whether ``user`` can read one batch, record, or immutable view log."""
    user = user or frappe.session.user
    if not can_access_request_type(REQUEST_EXPENSE_PAYMENT, user):
        return False
    if not user or user == "Guest":
        return False
    doctype = _get(doc, "doctype")
    if doctype == _VIEW_LOG:
        source_name = _get(doc, "invoice_record")
        source = _record_doc(source_name, current=current) if source_name else None
        return bool(source and can_read_invoice(source, user, current=current))
    if doctype not in {_BATCH, _RECORD}:
        return False

    roles = _roles(user)
    if _is_high_privilege(user, roles):
        return True
    if _get(doc, "owner") == user:
        return True
    request_name = _effective_request(doc, doctype, current=current)
    return bool(
        request_name
        and _can_read_request(
            request_name,
            user,
            roles=roles,
            current=current,
        )
    )


def _escaped(value):
    return frappe.db.escape(str(value))


def _request_scope_sql(request_alias, user, roles, identity):
    clauses = [f"{request_alias}.owner = {_escaped(user)}"]
    if identity.get("employee"):
        clauses.append(f"{request_alias}.employee = {_escaped(identity['employee'])}")
    if "Department Manager" in roles and identity.get("department"):
        clauses.append(f"{request_alias}.department = {_escaped(identity['department'])}")

    actor_checks = []
    for actor in sorted(identity["actors"]):
        actor_checks.append(
            "JSON_CONTAINS("
            "CASE WHEN JSON_VALID(step.approvers) THEN step.approvers ELSE '[]' END, "
            f"JSON_QUOTE({_escaped(actor)}))"
        )
    clauses.append(
        "EXISTS (SELECT 1 FROM `tabOA Approval Step` step "
        f"WHERE step.parent = {request_alias}.name "
        "AND step.parenttype = 'OA Approval Request' "
        "AND step.parentfield = 'steps' "
        f"AND step.step_index = {request_alias}.current_step_index "
        f"AND ({' OR '.join(actor_checks)}))"
    )
    return "(" + " OR ".join(clauses) + ")"


def _request_exists_sql(request_expression, user, roles, identity):
    scope = _request_scope_sql("req", user, roles, identity)
    return (
        "EXISTS (SELECT 1 FROM `tabOA Approval Request` req "
        f"WHERE req.name = {request_expression} AND {scope})"
    )


def _query_context(user):
    user = user or frappe.session.user
    if not user or user == "Guest":
        return user, set(), None
    roles = _roles(user)
    if _is_high_privilege(user, roles):
        return user, roles, None
    return user, roles, _identity(user)


def invoice_batch_query(user=None):
    requested_user = user or frappe.session.user
    if not can_access_request_type(REQUEST_EXPENSE_PAYMENT, requested_user):
        return "1=0"
    user, roles, identity = _query_context(user)
    if not user or user == "Guest":
        return "1=0"
    if identity is None:
        return ""
    table = "`tabOA Invoice Import Batch`"
    request_access = _request_exists_sql(f"NULLIF({table}.request, '')", user, roles, identity)
    return f"({table}.owner = {_escaped(user)} OR {request_access})"


def _record_access_sql(record_alias, user, roles, identity, batch_alias="batch_scope"):
    effective_request = (
        f"COALESCE(NULLIF({record_alias}.request, ''), "
        f"(SELECT {batch_alias}.request FROM `tabOA Invoice Import Batch` {batch_alias} "
        f"WHERE {batch_alias}.name = {record_alias}.batch LIMIT 1))"
    )
    request_access = _request_exists_sql(effective_request, user, roles, identity)
    return f"({record_alias}.owner = {_escaped(user)} OR {request_access})"


def invoice_record_query(user=None):
    requested_user = user or frappe.session.user
    if not can_access_request_type(REQUEST_EXPENSE_PAYMENT, requested_user):
        return "1=0"
    user, roles, identity = _query_context(user)
    if not user or user == "Guest":
        return "1=0"
    if identity is None:
        return ""
    return _record_access_sql("`tabOA Invoice Record`", user, roles, identity)


def invoice_view_log_query(user=None):
    requested_user = user or frappe.session.user
    if not can_access_request_type(REQUEST_EXPENSE_PAYMENT, requested_user):
        return "1=0"
    user, roles, identity = _query_context(user)
    if not user or user == "Guest":
        return "1=0"
    if identity is None:
        return (
            "EXISTS (SELECT 1 FROM `tabOA Invoice Record` source "
            "WHERE source.name = `tabOA Invoice View Log`.invoice_record)"
        )
    source_access = _record_access_sql("source", user, roles, identity, batch_alias="source_batch")
    return (
        "EXISTS (SELECT 1 FROM `tabOA Invoice Record` source "
        "WHERE source.name = `tabOA Invoice View Log`.invoice_record "
        f"AND {source_access})"
    )


def _has_permission(doctype, doc, ptype=None, user=None):
    if ptype not in (None, "read"):
        return None
    if _get(doc, "doctype") == doctype:
        target = doc
    elif isinstance(doc, dict):
        target = dict(doc, doctype=doctype)
    else:
        target = doc
    return can_read_invoice(target, user)


def invoice_batch_has_permission(doc, ptype=None, user=None):
    return _has_permission(_BATCH, doc, ptype, user)


def invoice_record_has_permission(doc, ptype=None, user=None):
    return _has_permission(_RECORD, doc, ptype, user)


def invoice_view_log_has_permission(doc, ptype=None, user=None):
    return _has_permission(_VIEW_LOG, doc, ptype, user)


def can_read_request(request, user=None, *, current=False):
    """Apply the same row scope used by invoice permission hooks to one OA request."""
    user = user or frappe.session.user
    if not user or user == "Guest":
        return False
    request_name = _get(request, "name") if not isinstance(request, str) else request
    return _can_read_request(str(request_name or ""), user, current=current)


def can_edit_request(request, user=None, *, current=False):
    """Only the request applicant/owner or a System Manager may edit request data."""
    user = user or frappe.session.user
    request_type = REQUEST_EXPENSE_PAYMENT if isinstance(request, str) else (
        _get(request, "request_type") or REQUEST_EXPENSE_PAYMENT
    )
    if not can_access_request_type(request_type, user):
        return False
    if not user or user == "Guest":
        return False
    roles = _roles(user)
    if user == "Administrator" or "System Manager" in roles:
        return True
    request_doc, identity, _approvers = _request_access_context(
        request, user, current=current
    )
    if not request_doc:
        return False
    if _get(request_doc, "owner") == user:
        return True
    return bool(identity.get("employee") and _get(request_doc, "employee") == identity["employee"])
