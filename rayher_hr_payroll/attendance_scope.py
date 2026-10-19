"""考勤中心里"能看到谁"的身份判断（服务端定，前端只是照着显示）。

三档：
- company：人事经理、演示员工113经理、总经理（按岗位任命判断，不看角色名）和 Administrator。首页直接看到全公司的人名（决定 2026-10-14，原来是先看部门数字、点进部门才有人名），
  也可以选一个部门只看它；
- manager：有在职直接下属的员工，只看自己的团队——汇报关系向下的在职员工，下属在哪个部门都算，同部门但不是下属的人不算
  （决定 2026-10-12，见 team_scope）；演示员工113同人事经理一样看全公司，还没有"只看分管部门"的数据；
- employee：其他人，只看自己的数据，看不到同事的请假。
"""
from __future__ import annotations

import frappe

from rayher_hr_payroll.position_access import position_users
from rayher_hr_payroll.team_scope import has_direct_reports

COMPANY_POSITIONS = ("hr_manager", "vice_manager", "general_manager")
COMPANY = "company"
MANAGER = "manager"
EMPLOYEE = "employee"


def resolve_scope(user=None):
    """当前登录人的档次：{level, user, employee, employee_name, department}。没登录直接拒绝。"""
    user = str(user or frappe.session.user or "").strip().lower()
    if not user or user == "guest":
        frappe.throw(frappe._("请先登录。"), frappe.PermissionError)
    scope = {"level": EMPLOYEE, "user": user, "employee": "", "employee_name": "", "department": ""}
    rows = frappe.get_all(
        "Employee", filters={"user_id": user, "status": "Active"},
        fields=["name", "employee_name", "department"], order_by="name asc", limit_page_length=2,
    )
    if len(rows) == 1:
        scope.update(employee=rows[0].get("name") or "", employee_name=rows[0].get("employee_name") or "",
                     department=rows[0].get("department") or "")
    if user == "administrator" or user in position_users(*COMPANY_POSITIONS):
        scope["level"] = COMPANY
    elif scope["employee"] and has_direct_reports(scope["employee"]):
        scope["level"] = MANAGER
    return scope
