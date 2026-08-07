"""Move the Qingbo executive account to the canonical local domain safely."""

from __future__ import annotations

import json

import frappe

OLD_USER = "person046@business.example.invalid"
NEW_USER = "person046@staff.example.invalid"
EMPLOYEE = "HR-EMP-90004"


def replace_user_id_list(value):
    if isinstance(value, list):
        values = list(value)
    elif not value:
        return value
    else:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return NEW_USER if str(value).lower() == OLD_USER else value
        if not isinstance(parsed, list):
            return value
        values = parsed
    replaced = [NEW_USER if str(item).lower() == OLD_USER else item for item in values]
    if replaced == values:
        return value
    return json.dumps(replaced, ensure_ascii=False)


def execute():
    old_exists = bool(frappe.db.exists("User", OLD_USER))
    new_exists = bool(frappe.db.exists("User", NEW_USER))
    if old_exists and new_exists:
        frappe.throw(
            f"审批账号迁移冲突：{OLD_USER} 与 {NEW_USER} 同时存在，请先合并账号"
        )
    if old_exists:
        frappe.rename_doc("User", OLD_USER, NEW_USER, force=True)
        new_exists = True
    if not new_exists:
        frappe.throw(f"审批账号不存在：{NEW_USER}")

    user = frappe.get_doc("User", NEW_USER)
    if getattr(user, "email", None) != NEW_USER:
        user.email = NEW_USER
        user.save(ignore_permissions=True)

    employee_user = str(
        frappe.db.get_value("Employee", EMPLOYEE, "user_id") or ""
    ).lower()
    if employee_user not in {"", OLD_USER, NEW_USER}:
        frappe.throw(
            f"员工 {EMPLOYEE} 已关联其他账号 {employee_user}，停止审批账号迁移"
        )
    if employee_user != NEW_USER:
        frappe.db.set_value("Employee", EMPLOYEE, "user_id", NEW_USER)

    for row in frappe.get_all(
        "OA Approval Step",
        fields=["name", "approvers", "approved_by"],
        limit_page_length=0,
    ):
        for fieldname in ("approvers", "approved_by"):
            current = row.get(fieldname)
            replaced = replace_user_id_list(current)
            if replaced != current:
                frappe.db.set_value(
                    "OA Approval Step", row["name"], fieldname, replaced,
                    update_modified=False,
                )
