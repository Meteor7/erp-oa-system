"""CAS-style reconciliation for three explicitly approved supervisor corrections."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


APPROVED_CORRECTIONS = {
    "演示员工145": ("演示员工21", "演示员工172"),
    "演示员工159": ("演示员工21", "演示员工172"),
    "演示员工187": ("演示员工21", "演示员工183"),
}


def _text(value):
    return str(value or "").strip()


def build_reconciliation_plan(
    employees: Iterable[Mapping],
    corrections: Mapping[str, tuple[str, str]] | None = None,
):
    corrections = dict(corrections or APPROVED_CORRECTIONS)
    active_by_name = {}
    duplicates = set()
    for source in employees or []:
        row = dict(source)
        if _text(row.get("status")) != "Active":
            continue
        name = _text(row.get("employee_name"))
        if not name:
            continue
        if name in active_by_name:
            duplicates.add(name)
        active_by_name[name] = row

    updates = []
    unchanged = []
    conflicts = []
    for employee_name, (approved_old, expected) in sorted(corrections.items()):
        if employee_name in duplicates:
            conflicts.append(
                {"type": "employee_not_unique", "employee_name": employee_name}
            )
            continue
        employee = active_by_name.get(employee_name)
        supervisor = active_by_name.get(expected)
        old_supervisor = active_by_name.get(approved_old)
        if not employee or not supervisor or not old_supervisor:
            conflicts.append(
                {
                    "type": "employee_not_found",
                    "employee_name": employee_name,
                    "approved_old": approved_old,
                    "expected": expected,
                }
            )
            continue

        current = _text(employee.get("reports_to"))
        if current == _text(supervisor.get("name")):
            unchanged.append(
                {
                    "employee": employee.get("name"),
                    "employee_name": employee_name,
                    "reports_to": supervisor.get("name"),
                }
            )
        elif current == _text(old_supervisor.get("name")):
            updates.append(
                {
                    "employee": employee.get("name"),
                    "employee_name": employee_name,
                    "approved_old": old_supervisor.get("name"),
                    "reports_to": supervisor.get("name"),
                }
            )
        else:
            conflicts.append(
                {
                    "type": "unexpected_current_supervisor",
                    "employee": employee.get("name"),
                    "employee_name": employee_name,
                    "current": current,
                    "approved_old": old_supervisor.get("name"),
                    "expected": supervisor.get("name"),
                }
            )
    return {
        "updates": updates,
        "unchanged": unchanged,
        "conflicts": conflicts,
    }


def reconcile_approved_supervisors(*, dry_run=False):
    import json
    import frappe

    employees = frappe.get_all(
        "Employee",
        fields=["name", "employee_name", "status", "reports_to"],
        order_by="employee_name, name",
    )
    plan = build_reconciliation_plan(employees)
    plan["dry_run"] = bool(dry_run)
    plan["applied"] = 0
    if plan["conflicts"]:
        frappe.throw(
            "已核准主管关系纠正遇到未预期数据，未写入任何记录："
            + json.dumps(plan["conflicts"], ensure_ascii=False, sort_keys=True)
        )
    if dry_run:
        return plan
    for update in plan["updates"]:
        frappe.db.set_value(
            "Employee",
            update["employee"],
            "reports_to",
            update["reports_to"],
            update_modified=False,
        )
        plan["applied"] += 1
    return plan
