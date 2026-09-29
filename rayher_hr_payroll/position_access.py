"""Current position holders for routing and access, never personal account allowlists."""
from rayher_hr_payroll.oa_role_resolver import (
    ROLE_SPECS, ApprovalRoleResolutionError, resolve_role,
)


def position_user(key):
    return resolve_role(key)["user"].strip().lower()


def position_users(*keys):
    users = set()
    for key in keys:
        try:
            users.add(position_user(key))
        except ApprovalRoleResolutionError:
            # An unresolved position grants no access.
            continue
    return users


def position_flags(user):
    candidate = str(user or "").strip().lower()
    return {key: candidate in position_users(key) for key in ROLE_SPECS}


def current_supervisors():
    import frappe
    rows = frappe.get_all("Employee", fields=["name", "employee_name", "reports_to"],
                          limit_page_length=0)
    names = {row.name: row.employee_name for row in rows}
    result = {}
    for row in rows:
        if row.employee_name in result:
            raise ApprovalRoleResolutionError("同名员工无法唯一解析主管，需核对员工档案")
        result[row.employee_name] = names.get(row.reports_to, "")
    return result


def executive_names():
    """副总经理、总经理的姓名，用来判断某人是不是高管。

    修复（2026-09-29，审查 #10）：原来任一岗位空缺或绑定的人已离职就直接抛错，所有请假、加班、
    调休和其他申请的提交都失败（页面上是 500）。空缺的岗位没有人，自然谁也不是它；需要这个岗位
    审批时，路线生成那一步会给出明确的提示。
    """
    names = set()
    for key in ("vice_manager", "general_manager"):
        try:
            names.add(resolve_role(key)["employee_name"])
        except ApprovalRoleResolutionError:
            continue
    return names
