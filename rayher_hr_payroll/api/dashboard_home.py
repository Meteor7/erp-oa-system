"""按岗位区分的数据看板的入口。内容和权限在 rayher_hr_payroll/dashboard/ 里。"""
import frappe

from rayher_hr_payroll.dashboard import core


def _make_ctx(period=None):
    from rayher_hr_payroll.position_access import position_flags

    user = frappe.session.user
    today = str(frappe.utils.nowdate())
    month = str(period or today[:7])
    if len(month) != 7 or month[4] != "-" or not (month[:4] + month[5:]).isdigit() or not 1 <= int(month[5:]) <= 12:
        frappe.throw(frappe._("期间格式应为 YYYY-MM"))
    employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, ["name", "department", "employee_name"], as_dict=True)
    has_reports = bool(employee and frappe.db.exists("Employee", {"reports_to": employee.name, "status": "Active"}))
    return core.Ctx(
        user=user,
        roles=frozenset(frappe.get_roles(user)),
        positions=frozenset(key for key, held in position_flags(user).items() if held),
        period=month,
        today=today,
        employee=(employee.name if employee else ""),
        department=(employee.department if employee else "") or "",
        has_reports=has_reports,
        full_name=(employee.employee_name if employee else "") or frappe.utils.get_fullname(user) or user,
    )


@frappe.whitelist(methods=["GET"])
def get_home(period=None):
    """当前登录人的看板首页：按他的岗位排版，只返回他有权限看的块。"""
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.throw(frappe._("请先登录"), frappe.PermissionError)
    core.load_providers()
    return core.get_home_for(_make_ctx(period), None)
