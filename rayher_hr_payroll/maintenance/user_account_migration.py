"""Maintenance helpers for renaming generated R&D employee accounts."""

from __future__ import annotations

import re

import frappe

USER_DOMAIN = "legacy.example.invalid"
_GENERATED_USER_RE = re.compile(r"^hr-emp-\d+@legacy\.example\.invalid$", re.IGNORECASE)


def _romanize(value):
    from pypinyin import lazy_pinyin

    return lazy_pinyin(value or "", errors=lambda chunk: list(chunk))


def is_generated_rd_user(user_id):
    return bool(_GENERATED_USER_RE.fullmatch(str(user_id or "").strip()))


def _employee_suffix(employee_id):
    digits = "".join(re.findall(r"\d", str(employee_id or "")))
    return digits[-4:].zfill(4)


def build_username(employee_name, employee_id, used_names, romanize=None):
    romanize = romanize or _romanize
    parts = romanize(str(employee_name or "").strip())
    local_part = re.sub(r"[^a-z0-9]", "", "".join(parts).lower())
    if not local_part:
        raise ValueError(f"Employee {employee_id} has no usable pinyin username")

    used = {str(name).lower() for name in (used_names or set())}
    candidate = f"{local_part}@{USER_DOMAIN}"
    if candidate.lower() not in used:
        return candidate

    candidate = f"{local_part}{_employee_suffix(employee_id)}@{USER_DOMAIN}"
    if candidate.lower() in used:
        raise ValueError(f"Username collision remains for employee {employee_id}")
    return candidate


def build_rename_plan(employees, existing_users, romanize=None):
    targets = [
        dict(employee)
        for employee in (employees or [])
        if employee.get("status") == "Active" and is_generated_rd_user(employee.get("user_id"))
    ]
    targets.sort(key=lambda row: str(row.get("name") or ""))
    old_users = {str(row.get("user_id") or "").lower() for row in targets}
    used = {
        str(user).lower()
        for user in (existing_users or set())
        if str(user).lower() not in old_users
    }

    plan = []
    for employee in targets:
        new_user = build_username(
            employee.get("employee_name"),
            employee.get("name"),
            used,
            romanize=romanize,
        )
        used.add(new_user.lower())
        plan.append({
            "employee": employee.get("name"),
            "employee_name": employee.get("employee_name"),
            "old_user": employee.get("user_id"),
            "new_user": new_user,
        })
    return plan


def plan_generated_rd_user_renames():
    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active", "user_id": ["like", "history.ec94337428@legacy.example.invalid"]},
        fields=["name", "employee_name", "user_id", "status"],
        order_by="name asc",
    )
    existing_users = set(frappe.get_all("User", pluck="name"))
    return build_rename_plan(employees, existing_users)


def rename_generated_rd_users(dry_run=True):
    mappings = plan_generated_rd_user_renames()
    if dry_run:
        return {"dry_run": True, "count": len(mappings), "mappings": mappings}

    try:
        for row in mappings:
            frappe.rename_doc(
                "User",
                row["old_user"],
                row["new_user"],
                force=True,
                show_alert=False,
            )
            linked_user = frappe.db.get_value("Employee", row["employee"], "user_id")
            if linked_user != row["new_user"]:
                frappe.throw(f"Employee link was not updated for {row['employee']}")
            if frappe.db.exists("Project", {"project_owner": row["old_user"]}):
                frappe.throw(f"Project owner link still references {row['old_user']}")
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise

    return {"dry_run": False, "count": len(mappings), "mappings": mappings}
