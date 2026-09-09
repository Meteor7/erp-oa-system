"""Read-only readiness diagnostics for OA reimbursement routing."""

from __future__ import annotations

import frappe

from rayher_hr_payroll.oa_role_resolver import ApprovalRoleResolutionError, resolve_role
from rayher_hr_payroll.oa_organization import (
    DIRECT_SUPERVISOR_BY_EMPLOYEE,
    OrganizationResolutionError,
    resolve_stage_two_supervisor,
)


REQUIRED_APPROVERS = {"演示员工18": "person068@staff.example.invalid"}
REQUIRED_ROLE_KEYS = (
    "pmc", "hr_manager", "finance_auditor", "finance_manager",
    "vice_manager", "general_manager", "production_asset_owner",
    "procurement_manager",
)


def _clean(value):
    return str(value or "").strip()


def build_diagnostics(
    employees,
    resolve_user,
    account_state,
    *,
    required_approvers=None,
):
    """Build a deterministic report without changing any supplied state."""
    required_approvers = REQUIRED_APPROVERS if required_approvers is None else required_approvers
    report = {"employees": [], "accounts": [], "errors": []}
    for source in employees or []:
        row = dict(source)
        employee_id = _clean(row.get("name"))
        employee_name = _clean(row.get("employee_name")) or employee_id
        item = {
            "employee": employee_id,
            "employee_name": employee_name,
            "department": _clean(row.get("department")),
            "decision": "error",
            "supervisor_name": "",
            "user_id": "",
            "traversed": [],
            "reason": "",
        }
        try:
            resolution = resolve_stage_two_supervisor(employee_name, resolve_user)
        except OrganizationResolutionError as exc:
            error_type = (
                "missing_mapping"
                if employee_name not in DIRECT_SUPERVISOR_BY_EMPLOYEE
                else "organization_resolution_error"
            )
            report["errors"].append(
                {
                    "type": error_type,
                    "employee": employee_id,
                    "employee_name": employee_name,
                    "message": str(exc),
                }
            )
            item["reason"] = str(exc)
        else:
            item.update(
                {
                    "decision": resolution.decision,
                    "supervisor_name": resolution.supervisor_name,
                    "user_id": resolution.user_id,
                    "traversed": list(resolution.traversed),
                    "reason": resolution.reason,
                }
            )
        report["employees"].append(item)

    for name, user_id in required_approvers.items():
        state = dict(account_state(user_id) or {})
        ready = bool(
            state.get("exists")
            and state.get("enabled")
            and _clean(state.get("employee_name")) == name
        )
        account = {
            "name": name,
            "user_id": user_id,
            "exists": bool(state.get("exists")),
            "enabled": bool(state.get("enabled")),
            "employee": _clean(state.get("employee")),
            "employee_name": _clean(state.get("employee_name")),
            "ready": ready,
        }
        report["accounts"].append(account)
        if not ready:
            report["errors"].append(
                {
                    "type": "required_account_not_ready",
                    "name": name,
                    "user_id": user_id,
                    "message": f"审批账号 {name} / {user_id} 未启用或未正确关联 Employee",
                }
            )
    report["employee_count"] = len(report["employees"])
    report["account_count"] = len(report["accounts"])
    report["error_count"] = len(report["errors"])
    return report


def _enabled_user_for_employee(employee_name):
    user_id = frappe.db.get_value(
        "Employee",
        {"employee_name": employee_name, "status": "Active"},
        "user_id",
    )
    if not user_id:
        return ""
    return _clean(
        frappe.db.get_value("User", {"name": user_id, "enabled": 1}, "name")
    )


def _account_state(user_id):
    enabled = frappe.db.get_value("User", user_id, "enabled")
    employee = frappe.db.get_value(
        "Employee",
        {"user_id": user_id, "status": "Active"},
        ["name", "employee_name"],
        as_dict=True,
    )
    return {
        "exists": enabled is not None,
        "enabled": bool(enabled),
        "employee": employee.get("name") if employee else "",
        "employee_name": employee.get("employee_name") if employee else "",
    }


def run(dry_run=True):
    """Return live readiness. This diagnostic is read-only in every mode."""
    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "employee_name", "department"],
        order_by="department asc, employee_name asc",
    )
    required_approvers = dict(REQUIRED_APPROVERS)
    role_errors = []
    for role_key in REQUIRED_ROLE_KEYS:
        try:
            role = resolve_role(role_key)
        except ApprovalRoleResolutionError as exc:
            role_errors.append({
                "type": "required_role_not_ready",
                "role_key": role_key,
                "message": str(exc),
            })
            continue
        required_approvers[role["employee_name"]] = role["user"]
    report = build_diagnostics(
        employees,
        _enabled_user_for_employee,
        _account_state,
        required_approvers=required_approvers,
    )
    report["errors"].extend(role_errors)
    report["error_count"] = len(report["errors"])
    report["dry_run"] = bool(dry_run)
    report["mutated"] = False
    return report