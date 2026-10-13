"""考勤中心的图表和团队日历（只读）。

谁能看到什么由服务端按身份定（attendance_scope.resolve_scope），页面上隐藏只是展示：
- 员工：只返回自己的数据（额度以外的请假构成、近 6 个月、未来 14 天的安排），不返回任何同事；
- 部门主管（有在职直接下属的人）：只返回自己的团队——汇报关系向下的在职员工，含每个人 14 天的日历；取别的部门被拒绝；
- 人事经理 / 副总经理 / 总经理：get_attendance_board 只返回各部门的汇总数字，没有人名；
  点进某个部门（get_department_attendance）才返回这个部门的人名和日历。
员工调用 get_department_attendance 一律拒绝。
审批时的"同期谁不在"（get_request_overlap）同样按身份：部门主管只有申请人在自己团队时给团队里的人名，人事和管理层给人名，其他人只给空列表。
"""
from __future__ import annotations

from datetime import date, timedelta

import frappe

from rayher_hr_payroll import attendance_board as board
from rayher_hr_payroll import attendance_requests as att
from rayher_hr_payroll.attendance_scope import COMPANY, EMPLOYEE, MANAGER, resolve_scope
from rayher_hr_payroll.oa_document_types import REQUEST_TRAVEL
from rayher_hr_payroll.oa_feature_gate import can_access_request_type
from rayher_hr_payroll.team_scope import team_members
from rayher_hr_payroll.working_calendar import resolve_monthly_calendar

ROW_TYPES = (*att.ATTENDANCE_TYPES, REQUEST_TRAVEL)
PENDING = ("待审批", "待办理")


def _require_open():
    if not any(can_access_request_type(item) for item in att.ATTENDANCE_TYPES):
        frappe.throw(frappe._("当前审批功能暂未开放。"), frappe.PermissionError)


def _work_dates(first, last):
    """公司日历上 [first, last] 里的工作日。"""
    result = set()
    for year, month in sorted({(first.year, first.month), (last.year, last.month)}):
        result |= set(resolve_monthly_calendar(year, month)["work_dates"])
    return {day for day in result if first <= day <= last}


def _window(today, back=None):
    """今天起 14 天、今天所在的月份，和覆盖这些的日期范围（back 给了就再往前延伸到那天）、范围内的工作日。"""
    last = today + timedelta(days=board.WINDOW_DAYS - 1)
    month_first, month_last = board.month_start_end(today)
    start, end = min(today, month_first, back or today), max(last, month_last)
    return {"first": today, "month_first": month_first, "month_last": month_last, "start": start, "end": end,
            "work_dates": _work_dates(start, end)}


def _rows(employees, start, end, statuses=None):
    """这些员工在 [start, end] 里的请假、加班、调休、出差申请（含每日明细）。"""
    if not employees:
        return []
    return frappe.db.sql(
        "SELECT name, employee, request_type, leave_type, workflow_status, from_date, to_date, attendance_days, "
        "travel_start_date, travel_end_date, travel_destination FROM `tabOA Approval Request` "
        "WHERE employee IN %(employees)s AND request_type IN %(types)s AND workflow_status IN %(statuses)s "
        "AND ((request_type <> %(travel)s AND from_date <= %(end)s AND to_date >= %(start)s) "
        "OR (request_type = %(travel)s AND travel_start_date <= %(end)s AND travel_end_date >= %(start)s))",
        {"employees": tuple(sorted(employees)), "types": tuple(ROW_TYPES), "statuses": tuple(sorted(statuses or att.ACTIVE)),
         "travel": REQUEST_TRAVEL, "start": start, "end": end},
        as_dict=True,
    )


def _members(department):
    return frappe.get_all(
        "Employee", filters={"department": department, "status": "Active"},
        fields=["name", "employee_name"], order_by="name asc", limit_page_length=500,
    )


def _pending(employees=None):
    """待审批的请假、加班、调休、出差张数：{部门: 张数}（只有数字）。employees 给了就只算这些人。"""
    if employees is not None and not employees:
        return {}
    sql = (
        "SELECT e.department AS department, COUNT(*) AS n FROM `tabOA Approval Request` r "
        "JOIN `tabEmployee` e ON e.name = r.employee WHERE e.status = 'Active' "
        "AND r.request_type IN %(types)s AND r.workflow_status IN %(statuses)s"
        + (" AND r.employee IN %(employees)s" if employees is not None else "") + " GROUP BY e.department"
    )
    args = {"types": tuple(ROW_TYPES), "statuses": PENDING}
    if employees is not None:
        args["employees"] = tuple(sorted(employees))
    return {(row.get("department") or ""): int(row.get("n") or 0) for row in frappe.db.sql(sql, args, as_dict=True)}


def _personal(scope, today):
    """员工自己的：只取本人的申请。"""
    if not scope["employee"]:
        return {"strip": [], "year": today.year, "year_by_kind": {}, "months": []}
    # 今年和最近 6 个月都要取：往前延伸到今年 1 月 1 日和 6 个月前的月初里更早的那天。
    back = min(date(today.year, 1, 1), (today.replace(day=1) - timedelta(days=170)).replace(day=1))
    window = _window(today, back)
    rows = _rows([scope["employee"]], window["start"], window["end"])
    return board.build_personal(scope["employee"], rows, first=today, work_dates=window["work_dates"], year=today.year)


def _department_detail(department, today):
    """一个部门的明细：汇总数字 + 每个人 14 天的日历（有人名，只给校验过范围的调用方）。"""
    window = _window(today)
    members = _members(department)
    ids = [member.get("name") for member in members]
    rows = _rows(ids, window["start"], window["end"])
    options = {"first": today, "work_dates": window["work_dates"]}
    stats = board.build_stats(ids, rows, month_first=window["month_first"], month_last=window["month_last"], **options)
    labels = board.department_labels([department])
    return {
        "department": department, "label": labels[department], "headcount": len(ids),
        "pending": sum(_pending(ids).values()), "stats": stats,
        "members": board.build_members(members, rows, **options),
    }


def _team_detail(scope, today):
    """部门主管的团队：汇报关系向下的在职员工（含他自己），汇总数字 + 每个人 14 天的日历。"""
    window = _window(today)
    members = team_members(scope["employee"], include_self=True)
    ids = [member.get("name") for member in members]
    rows = _rows(ids, window["start"], window["end"])
    options = {"first": today, "work_dates": window["work_dates"]}
    stats = board.build_stats(ids, rows, month_first=window["month_first"], month_last=window["month_last"], **options)
    return {
        "department": "", "label": "我的团队", "headcount": len(ids),
        "pending": sum(_pending(ids).values()), "stats": stats,
        "members": board.build_members(members, rows, **options),
    }


def _company_summary(today):
    """全公司和各部门的汇总数字：只有人数、小时、比例，没有人名。"""
    window = _window(today)
    employees = frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", "department"], limit_page_length=0)
    rows = _rows([employee.get("name") for employee in employees], window["start"], window["end"], att.COMPLETED)
    return board.summarize_departments(
        employees, rows, _pending(), first=today, work_dates=window["work_dates"],
        month_first=window["month_first"], month_last=window["month_last"],
    )


def today_trips(today=None):
    """今天出差的人（和公司汇总里的“出差中”同一口径），一人一条：单号、地点、日期。看板“出差中”点进去用。"""
    today = today or date.today()
    window = _window(today)
    employees = frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", "employee_name", "department"], limit_page_length=0)
    rows = _rows([employee.get("name") for employee in employees], window["start"], window["end"], att.COMPLETED)
    return board.today_trips(employees, rows, first=today, work_dates=window["work_dates"])


@frappe.whitelist()
def get_attendance_board():
    """考勤中心首页的图表数据，按调用者的身份只返回他能看的范围：level 是 employee / manager / company。"""
    scope = resolve_scope()
    _require_open()
    today = date.today()
    if scope["level"] == EMPLOYEE:
        return {"level": EMPLOYEE, "personal": _personal(scope, today)}
    if scope["level"] == MANAGER:
        return {"level": MANAGER, "detail": _team_detail(scope, today)}
    return {"level": COMPANY, "summary": _company_summary(today)}


@frappe.whitelist()
def get_department_attendance(department=""):
    """一个部门的明细（有人名）：人事和管理层可以取任何部门；部门主管只有自己的团队（不能按部门取），员工一律拒绝。"""
    scope = resolve_scope()
    _require_open()
    if scope["level"] == EMPLOYEE:
        frappe.throw(frappe._("只有部门主管、人事和管理层可以查看团队出勤。"), frappe.PermissionError)
    department = str(department or "").strip()
    if scope["level"] == MANAGER:
        if department and department != scope["department"]:
            frappe.throw(frappe._("部门主管只能查看自己团队的出勤。"), frappe.PermissionError)
        detail = _team_detail(scope, date.today())
        return {"level": scope["level"], "detail": detail}
    if not department:
        frappe.throw(frappe._("请选择要查看的部门。"))
    detail = _department_detail(department, date.today())
    if not detail["headcount"]:
        frappe.throw(frappe._("找不到这个部门，或部门里没有在职员工。"), frappe.DoesNotExistError)
    return {"level": scope["level"], "detail": detail}


@frappe.whitelist()
def get_request_overlap(name):
    """批之前看"同期谁不在"：申请人所在部门里，和这张申请日期重叠的请假、调休、出差的人（审批中的也列，标出来）。

    先走详情页同一套权限（看不到这张申请就报错）；再按身份定能不能给人名：人事和管理层给申请人所在部门的人，
    部门主管只有申请人在自己团队时给团队里的人，其他人（没有管理职责的审批人）一律只给空列表，不泄露同事的请假。加班申请不查。
    """
    scope = resolve_scope()
    _require_open()
    from rayher_hr_payroll.api import attendance_entry

    detail = getattr(attendance_entry.get_attendance_request, "__wrapped__", attendance_entry.get_attendance_request)
    request = (detail(name) or {}).get("request") or {}
    empty = {"visible": False, "count": 0, "people": []}
    employee = request.get("employee")
    if not employee or request.get("request_type") == att.REQUEST_OVERTIME:
        return empty
    if scope["level"] == EMPLOYEE:
        return empty
    if scope["level"] == MANAGER:
        # 部门主管只给自己团队里的人名：申请人不在他的团队里，就什么都不给。
        team = team_members(scope["employee"], include_self=True)
        if employee not in {member.get("name") for member in team}:
            return empty
        members = [member for member in team if member.get("name") != employee]
    else:
        department = frappe.db.get_value("Employee", employee, "department") or ""
        if not department:
            return empty
        members = [member for member in _members(department) if member.get("name") != employee]
    wanted = {day for day, _hours in board.days_of(request)}
    if not wanted:
        return {**empty, "visible": True}
    names = {member.get("name"): member.get("employee_name") or member.get("name") for member in members}
    found = {}
    for row in _rows(list(names), min(wanted), max(wanted)):
        kind = board.kind_of(row)
        if kind not in (*board.ABSENCE_KINDS, "trip"):
            continue
        dates = sorted({day for day, _hours in board.days_of(row) if day in wanted})
        if not dates:
            continue
        person = found.setdefault(row.get("employee"), {"name": names.get(row.get("employee")), "kind": kind, "dates": set(), "pending": True})
        person["dates"].update(dates)
        person["pending"] = person["pending"] and row.get("workflow_status") not in att.COMPLETED
        if kind in board.ABSENCE_KINDS:
            person["kind"] = kind
    people = sorted(({**person, "dates": [day.isoformat() for day in sorted(person["dates"])]} for person in found.values()),
                    key=lambda item: (item["dates"][0], item["name"] or ""))
    return {"visible": True, "count": len(people), "people": people[:12]}
