"""“我的团队”：汇报关系向下的在职员工（决定 2026-10-12）。

部门主管 = 有在职直接下属的人；他的团队 = 直接或间接汇报给他的在职员工，下属在哪个部门都算，
不是下属的人（哪怕在同一个部门）不算。考勤中心、数据看板、工时填报进度、HR 概览共用这一个范围。

Employee 档案里的“汇报给”（reports_to）是唯一的依据。中间有人已经离职时，他名下的人仍然沿着他往上挂，
所以向下遍历时不看状态，只在结果里去掉非在职的人。
"""
from __future__ import annotations

MAX_DEPTH = 12
MAX_TEAM = 5000
MANAGER_ROLE = "Department Manager"


def collect_team(root, fetch_children, *, max_depth=MAX_DEPTH, limit=MAX_TEAM):
    """从 root 起沿汇报关系向下遍历（防环、有层数和人数上限）。

    fetch_children(names) 返回 [{name, status}]：汇报给 names 里任意一个人的员工。
    返回 [{name, status}]，不含 root 自己，按先近后远排。
    """
    root = str(root or "").strip()
    if not root:
        return []
    seen, frontier, found = {root}, [root], []
    for _ in range(max_depth):
        if not frontier:
            break
        children = []
        for row in fetch_children(list(frontier)) or []:
            name = str(row.get("name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                children.append({"name": name, "status": row.get("status")})
        found.extend(children)
        frontier = [row["name"] for row in children]
        if len(found) >= limit:
            break
    return found[:limit]


def _fetch_children(names):
    import frappe

    return frappe.get_all(
        "Employee", filters={"reports_to": ["in", list(names)]}, fields=["name", "status"], limit_page_length=0,
    )


def active_employee_of(user):
    """登录账号对应的在职员工号；没有、或对应了不止一个都当作没有。"""
    import frappe

    user = str(user or "").strip().lower()
    if not user:
        return ""
    rows = frappe.get_all(
        "Employee", filters={"user_id": user, "status": "Active"}, fields=["name"], limit_page_length=2,
    )
    return rows[0]["name"] if len(rows) == 1 else ""


def has_direct_reports(employee):
    import frappe

    return bool(employee and frappe.db.exists("Employee", {"reports_to": employee, "status": "Active"}))


def team_names(employee, *, include_self=False, statuses=("Active",)):
    """这个人团队里的员工号（默认只要在职的；按月份看工时时要带上本月离职的，传 statuses=("Active", "Left")）。"""
    names = [row["name"] for row in collect_team(employee, _fetch_children) if row.get("status") in statuses]
    return ([str(employee)] if include_self and employee else []) + names


def team_members(employee, *, include_self=True):
    """团队成员 [{name, employee_name, department}]，按员工号排序（有人名，只给调用方已经校验过范围的人用）。"""
    import frappe

    names = team_names(employee, include_self=include_self)
    if not names:
        return []
    return frappe.get_all(
        "Employee", filters={"name": ["in", names], "status": "Active"},
        fields=["name", "employee_name", "department"], order_by="name asc", limit_page_length=0,
    )


def team_of_user(user, *, include_self=True):
    """登录账号的团队：{employee, names}。账号没有对应的在职员工、或没有下属，names 为空。"""
    employee = active_employee_of(user)
    if not employee or not has_direct_reports(employee):
        return {"employee": employee, "names": []}
    return {"employee": employee, "names": team_names(employee, include_self=include_self)}


def ensure_manager_role(doc, method=None):
    """员工档案保存时：他的“汇报给”那个人的账号补上“部门主管”角色（只补不删，手工授予的角色保留）。

    “部门主管”从此以有没有下属为准；角色只是让既有的按角色放行的页面（工时填报进度等）认得他。
    """
    import frappe

    supervisor = str(getattr(doc, "reports_to", "") or "").strip()
    if not supervisor or getattr(doc, "status", "Active") != "Active":
        return False
    user = frappe.db.get_value("Employee", supervisor, "user_id")
    return grant_manager_role(user)


def grant_manager_role(user):
    import frappe

    user = str(user or "").strip()
    if not user or not frappe.db.exists("User", user):
        return False
    if frappe.db.exists("Has Role", {"parent": user, "parenttype": "User", "role": MANAGER_ROLE}):
        return False
    frappe.get_doc("User", user).add_roles(MANAGER_ROLE)
    return True


def grant_manager_role_to_all_supervisors():
    """补发：现在所有有在职直接下属的人。返回补上角色的账号。"""
    import frappe

    granted = []
    rows = frappe.get_all(
        "Employee", filters={"status": "Active", "reports_to": ["is", "set"]}, fields=["reports_to"], limit_page_length=0,
    )
    for supervisor in sorted({row["reports_to"] for row in rows if row.get("reports_to")}):
        user = frappe.db.get_value("Employee", supervisor, "user_id")
        if grant_manager_role(user):
            granted.append(user)
    return granted
