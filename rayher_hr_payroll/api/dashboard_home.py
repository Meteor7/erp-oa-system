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
    # “部门主管”以有没有在职直接下属为准（不看角色名）；项目负责人以项目上的“项目负责人”为准。
    has_reports = bool(employee and frappe.db.exists("Employee", {"reports_to": employee.name, "status": "Active"}))
    owns_projects = bool(frappe.db.exists("Project", {"project_owner": user, "status": ["!=", "Cancelled"]}))
    return core.Ctx(
        user=user,
        roles=frozenset(frappe.get_roles(user)),
        positions=frozenset(key for key, held in position_flags(user).items() if held),
        period=month,
        today=today,
        employee=(employee.name if employee else ""),
        department=(employee.department if employee else "") or "",
        has_reports=has_reports,
        owns_projects=owns_projects,
        full_name=(employee.employee_name if employee else "") or frappe.utils.get_fullname(user) or user,
    )


@frappe.whitelist(methods=["GET"])
def get_home(period=None):
    """当前登录人的看板首页：按他的岗位排版，只返回他有权限看的块。"""
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.throw(frappe._("请先登录"), frappe.PermissionError)
    core.load_providers()
    return core.get_home_for(_make_ctx(period), None)


@frappe.whitelist(methods=["GET"])
def get_detail(item=None, period=None):
    """点指标卡 / 提醒进去的明细清单：用和指标卡同一份数据逐条列出来，条数 / 合计和卡片上的数字一致。
    没有这个清单或没有权限时 available 为 False（页面显示“看不到”）。"""
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.throw(frappe._("请先登录"), frappe.PermissionError)
    core.load_providers()
    ctx = _make_ctx(period)
    detail = core.get_detail_for(ctx, str(item or "")[:80])
    if detail is None:
        return {"available": False}
    return {"available": True, "period": ctx.period, **detail}
