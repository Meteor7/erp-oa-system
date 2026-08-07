"""Synchronize approved OA supervisor mappings into timesheet authorization data."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

from rayher_hr_payroll.oa_organization import DIRECT_SUPERVISOR_BY_EMPLOYEE


RD_TYPES = frozenset({"全时研发", "非全时研发", "研发辅助"})
EXTERNAL_NODES = frozenset({"BOARD", "Philippe", "Sabri"})
MANAGER_ROLE = "Department Manager"


def _value(row, key, default=None):
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _text(value) -> str:
    return str(value or "").strip()


def _employee_record(row) -> dict:
    return {
        "name": _text(_value(row, "name")),
        "employee_name": _text(_value(row, "employee_name")),
        "user_id": _text(_value(row, "user_id")),
        "status": _text(_value(row, "status")),
        "rd_personnel_type": _text(_value(row, "rd_personnel_type")),
        "reports_to": _text(_value(row, "reports_to")),
    }


def build_sync_plan(
    employee_rows: Iterable,
    enabled_users: set[str],
    *,
    roles_by_user: Mapping[str, Iterable[str]] | None = None,
    mapping: Mapping[str, str] | None = None,
) -> dict:
    """Build a deterministic, read-only plan before any database write."""

    supervisor_mapping = dict(mapping or DIRECT_SUPERVISOR_BY_EMPLOYEE)
    enabled = {_text(user) for user in enabled_users if _text(user)}
    user_roles = {
        _text(user): {_text(role) for role in roles}
        for user, roles in (roles_by_user or {}).items()
    }
    employees = sorted(
        (_employee_record(row) for row in employee_rows),
        key=lambda row: (row["employee_name"], row["name"]),
    )
    active_by_name = defaultdict(list)
    for row in employees:
        if row["status"] == "Active" and row["employee_name"]:
            active_by_name[row["employee_name"]].append(row)

    plan = {
        "report_updates": [],
        "role_additions": [],
        "unchanged": [],
        "skipped_external": [],
        "skipped_user": [],
        "conflicts": [],
    }
    managers_with_reports: dict[str, dict] = {}

    for employee in employees:
        if employee["status"] != "Active" or employee["rd_personnel_type"] not in RD_TYPES:
            continue
        employee_name = employee["employee_name"]
        supervisor_name = _text(supervisor_mapping.get(employee_name))
        if not supervisor_name:
            plan["conflicts"].append(
                {
                    "type": "employee_mapping_missing",
                    "employee": employee["name"],
                    "employee_name": employee_name,
                }
            )
            continue
        if supervisor_name in EXTERNAL_NODES:
            plan["skipped_external"].append(
                {
                    "employee": employee["name"],
                    "employee_name": employee_name,
                    "supervisor_name": supervisor_name,
                }
            )
            continue

        matches = active_by_name.get(supervisor_name, [])
        if len(matches) != 1:
            plan["conflicts"].append(
                {
                    "type": "supervisor_name_not_unique",
                    "employee": employee["name"],
                    "employee_name": employee_name,
                    "supervisor_name": supervisor_name,
                    "matches": sorted(row["name"] for row in matches),
                }
            )
            continue

        manager = matches[0]
        managers_with_reports[manager["name"]] = manager
        expected = manager["name"]
        current = employee["reports_to"]
        if not current:
            plan["report_updates"].append(
                {
                    "employee": employee["name"],
                    "employee_name": employee_name,
                    "reports_to": expected,
                }
            )
        elif current == expected:
            plan["unchanged"].append(
                {
                    "employee": employee["name"],
                    "employee_name": employee_name,
                    "reports_to": expected,
                }
            )
        else:
            plan["conflicts"].append(
                {
                    "type": "reports_to_mismatch",
                    "employee": employee["name"],
                    "employee_name": employee_name,
                    "current": current,
                    "expected": expected,
                }
            )

    for manager in sorted(managers_with_reports.values(), key=lambda row: (row["employee_name"], row["name"])):
        user = manager["user_id"]
        if manager["rd_personnel_type"] not in RD_TYPES:
            plan["skipped_user"].append(
                {
                    "employee": manager["name"],
                    "employee_name": manager["employee_name"],
                    "user": user,
                    "reason": "supervisor_not_rd",
                }
            )
            continue
        if not user:
            plan["skipped_user"].append(
                {
                    "employee": manager["name"],
                    "employee_name": manager["employee_name"],
                    "user": "",
                    "reason": "missing_user",
                }
            )
            continue
        if user not in enabled:
            plan["skipped_user"].append(
                {
                    "employee": manager["name"],
                    "employee_name": manager["employee_name"],
                    "user": user,
                    "reason": "user_not_enabled",
                }
            )
            continue
        if MANAGER_ROLE not in user_roles.get(user, set()):
            plan["role_additions"].append(
                {
                    "employee": manager["name"],
                    "employee_name": manager["employee_name"],
                    "user": user,
                    "role": MANAGER_ROLE,
                }
            )

    for key in plan:
        plan[key] = sorted(
            plan[key],
            key=lambda row: (
                _text(row.get("employee_name")),
                _text(row.get("employee")),
                _text(row.get("type")),
            ),
        )
    return plan

def _get_frappe():
    import frappe

    return frappe


def synchronize_timesheet_supervisors(*, dry_run: bool = False) -> dict:
    """Validate and optionally apply the one-time timesheet supervisor sync."""

    import json

    frappe = _get_frappe()
    employees = frappe.get_all(
        "Employee",
        fields=[
            "name",
            "employee_name",
            "user_id",
            "status",
            "rd_personnel_type",
            "reports_to",
        ],
        order_by="employee_name, name",
    )
    enabled_users = set(
        frappe.get_all("User", filters={"enabled": 1}, pluck="name")
    )
    roles_by_user = {user: set(frappe.get_roles(user) or []) for user in enabled_users}
    plan = build_sync_plan(
        employees,
        enabled_users,
        roles_by_user=roles_by_user,
        mapping=DIRECT_SUPERVISOR_BY_EMPLOYEE,
    )
    plan["dry_run"] = bool(dry_run)
    plan["applied_report_updates"] = 0
    plan["applied_role_additions"] = 0

    if plan["conflicts"]:
        details = json.dumps(plan["conflicts"], ensure_ascii=False, sort_keys=True)
        frappe.throw(frappe._("工时主管关系冲突，未写入任何数据：{0}").format(details))
    if dry_run:
        return plan

    for update in plan["report_updates"]:
        frappe.db.set_value(
            "Employee",
            update["employee"],
            "reports_to",
            update["reports_to"],
            update_modified=False,
        )
        plan["applied_report_updates"] += 1
    for addition in plan["role_additions"]:
        frappe.get_doc("User", addition["user"]).add_roles(addition["role"])
        plan["applied_role_additions"] += 1
    return plan