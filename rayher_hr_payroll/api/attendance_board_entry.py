"""考勤中心的图表和团队日历（只读）。

谁能看到什么由服务端按身份定（attendance_scope.resolve_scope），页面上隐藏只是展示：
- 员工：只返回自己的数据（额度以外的请假构成、近 6 个月、未来 14 天的安排），不返回任何同事；
- 部门主管（有在职直接下属的人）：只返回自己的团队——汇报关系向下的在职员工，含每个人 14 天的日历和一张申请一行的明细
  （get_attendance_requests）；取别的部门被拒绝；
- 人事经理 / 演示员工113经理 / 总经理：决定 2026-10-14 起首页直接看到全公司的人名——get_attendance_requests 返回全公司（或选中的部门）
  一张申请一行的明细；get_attendance_board 仍然给各部门的汇总数字（部门概况表）；点进某个部门（get_department_attendance）给那个部门的日历。
员工调用 get_department_attendance、get_attendance_requests 一律拒绝（员工首页只看自己的）。
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
from rayher_hr_payroll import site_time

ROW_TYPES = (*att.ATTENDANCE_TYPES, REQUEST_TRAVEL)
# 统计里算已批准的状态：已完成 / 已通过，加上出差在前台办理（待办理）。其他类型没有办理节点，不会有“待办理”。
APPROVED = frozenset({*att.COMPLETED, "待办理"})
PENDING = ("待审批", "待办理")


def pending_sql(alias=""):
    """“还在审批”的 SQL 条件：待审批；待办理只算请假 / 加班 / 调休——出差到了前台待办理已经批准了，
    算“出差中”，不算待审批（决定 2026-10-13）。考勤中心的待审批、看板的考勤待审批共用这一条。"""
    prefix = f"{alias}." if alias else ""
    return (f"({prefix}workflow_status = '待审批' OR ({prefix}workflow_status = '待办理' "
            f"AND {prefix}request_type <> '{REQUEST_TRAVEL}'))")


def _require_open():
    if not any(can_access_request_type(item) for item in att.ATTENDANCE_TYPES):
        frappe.throw(frappe._("当前审批功能暂未开放。"), frappe.PermissionError)


def _months(first, last):
    """[first, last] 经过的每个月 [(年, 月)]（first 晚于 last 时是空的）。"""
    result = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        result.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def _work_dates(first, last):
    """公司日历上 [first, last] 里的工作日。
    修复（2026-10-14）：原来只取首尾两个月的日历，跨三个月以上的范围中间的月份一个工作日都没有；现在每个月都取。"""
    result = set()
    for year, month in _months(first, last):
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
    """这些员工在 [start, end] 里的请假、加班、调休、出差申请（含每日明细；没有明细的旧申请本月数字用 duration_hours）。"""
    if not employees:
        return []
    return frappe.db.sql(
        "SELECT name, employee, employee_name, request_type, leave_type, workflow_status, current_step_label, from_date, to_date, "
        "attendance_days, duration_hours, travel_start_date, travel_end_date, travel_destination FROM `tabOA Approval Request` "
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
        "AND r.request_type IN %(types)s AND r.workflow_status IN %(statuses)s AND " + pending_sql("r")
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
        # 今天不在岗 / 出差中的人和单号（团队页有人名；口径同 stats.today，看板的“今天不在岗”点进去用）。
        "today_away": _named_away(board.today_away(ids, rows, **options), members),
    }


def _named_away(away, members):
    names = {member.get("name"): member.get("employee_name") or member.get("name") for member in members}
    return {
        "off": [{"employee": item["employee"], "employee_name": names.get(item["employee"]) or item["employee"], "kind": item["kind"],
                 "request": item["request"]} for item in away["off"]],
        "trip": [{"employee": item["employee"], "employee_name": names.get(item["employee"]) or item["employee"], "request": item["request"]}
                 for item in away["trip"]],
    }


def today_away(today=None, employees=None):
    """今天不在岗（请假 / 调休）和出差中的人（口径见 attendance_board.today_away），一人一条，带姓名、部门和单号：
    看板“今天不在岗”、考勤中心“今天不在岗”列表用。employees 给了就只算这些人里在职的。"""
    today = today or site_time.today()
    filters = {"status": "Active"}
    if employees is not None:
        filters["name"] = ["in", list(employees) or ["__none__"]]
    staff = frappe.get_all("Employee", filters=filters, fields=["name", "employee_name", "department"], limit_page_length=0)
    ids = [row.get("name") for row in staff]
    rows = _rows(ids, today, today, APPROVED)
    away = board.today_away(ids, rows, first=today, work_dates=_work_dates(today, today))
    named = _named_away(away, staff)
    departments = {row.get("name"): row.get("department") or "" for row in staff}
    for item in named["off"] + named["trip"]:
        item["department"] = departments.get(item["employee"], "")
    return named


def _company_summary(today):
    """全公司和各部门的汇总数字（部门概况表、看板的考勤卡片）：只有人数、小时、比例；人名由 get_attendance_requests 另外给。"""
    window = _window(today)
    employees = frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", "department"], limit_page_length=0)
    rows = _rows([employee.get("name") for employee in employees], window["start"], window["end"], APPROVED)
    return board.summarize_departments(
        employees, rows, _pending(), first=today, work_dates=window["work_dates"],
        month_first=window["month_first"], month_last=window["month_last"],
    )


def today_trips(today=None):
    """今天出差的人（和公司汇总里的“出差中”同一口径），一人一条：单号、地点、日期。看板“出差中”点进去用。"""
    today = today or site_time.today()
    window = _window(today)
    employees = frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", "employee_name", "department"], limit_page_length=0)
    rows = _rows([employee.get("name") for employee in employees], window["start"], window["end"], APPROVED)
    return board.today_trips(employees, rows, first=today, work_dates=window["work_dates"])


@frappe.whitelist()
def get_attendance_board():
    """考勤中心首页的图表数据，按调用者的身份只返回他能看的范围：level 是 employee / manager / company。"""
    scope = resolve_scope()
    _require_open()
    today = site_time.today()
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
        detail = _team_detail(scope, site_time.today())
        return {"level": scope["level"], "detail": detail}
    if not department:
        frappe.throw(frappe._("请选择要查看的部门。"))
    detail = _department_detail(department, site_time.today())
    if not detail["headcount"]:
        frappe.throw(frappe._("找不到这个部门，或部门里没有在职员工。"), frappe.DoesNotExistError)
    return {"level": scope["level"], "detail": detail}


def _month_bounds(month, today):
    """"YYYY-MM" → 这个月的第一天和最后一天；空就是 today 所在的月。格式不对报错。"""
    text = str(month or "").strip()
    if not text:
        return board.month_start_end(today)
    try:
        if len(text) != 7 or text[4] != "-":
            raise ValueError(text)
        first = date(int(text[:4]), int(text[5:]), 1)
    except ValueError:
        frappe.throw(frappe._("月份格式不对，应为 YYYY-MM。"))
    return board.month_start_end(first)


def home_window(today):
    """首页“谁不在（今天 / 本周）”“未来 14 天”“近 5 个工作日”要用到的日期：本周一（或今天）到今天起第 14 天（或本周日）。"""
    monday = today - timedelta(days=today.weekday())
    return min(today, monday), max(today + timedelta(days=board.WINDOW_DAYS - 1), monday + timedelta(days=6))


def _scope_staff(scope, department):
    """按身份定好的人：部门主管 = 自己的团队（department 只能空着或是自己的部门）；人事和管理层 = 全公司，或选中的那个部门。
    返回 (在职员工 [{name, employee_name, department}], 标签)。员工不该走到这里。"""
    if scope["level"] == MANAGER:
        if department and department != scope["department"]:
            frappe.throw(frappe._("部门主管只能查看自己团队的出勤。"), frappe.PermissionError)
        return team_members(scope["employee"], include_self=True), "我的团队"
    filters = {"status": "Active"}
    if department:
        filters["department"] = department
    staff = frappe.get_all("Employee", filters=filters, fields=["name", "employee_name", "department"], order_by="name asc", limit_page_length=0)
    if department and not staff:
        frappe.throw(frappe._("找不到这个部门，或部门里没有在职员工。"), frappe.DoesNotExistError)
    return staff, (board.department_labels([department])[department] if department else "全公司")


@frappe.whitelist()
def get_attendance_requests(month="", department=""):
    """考勤中心首页（人事 / 领导、部门主管）的申请明细：一张申请一行，带人名。
    “谁不在”“未来 14 天”“N 月概览”“近 5 个工作日”都在页面上从这一份算，人数和合计的口径见 attendance_board.request_rows。

    范围由服务端按身份定：员工一律拒绝；部门主管只有自己的团队（汇报关系向下的在职员工，department 只能空着或是自己的部门）；
    人事经理 / 演示员工113经理 / 总经理看全公司（决定 2026-10-14：首页直接显示人名），department 给了就只看这个部门。
    month 是 "YYYY-MM"，空就是站点今天所在的月（看板点进来带它所选的期间）。取的申请：和这个月重叠的，加上和
    home_window（本周一到今天起 14 天）重叠的，按单号去重。
    返回 {level, today, month, start, end, department, label, headcount, work_dates（start 到 end 的工作日）, rows}。
    """
    scope = resolve_scope()
    _require_open()
    if scope["level"] == EMPLOYEE:
        frappe.throw(frappe._("只有部门主管、人事和管理层可以查看团队的申请。"), frappe.PermissionError)
    today = site_time.today()
    month_first, month_last = _month_bounds(month, today)
    department = str(department or "").strip()
    staff, label = _scope_staff(scope, department)
    ids = [member.get("name") for member in staff]
    start, end = home_window(today)
    found = {}
    for first, last in ((month_first, month_last), (start, end)):
        for row in _rows(ids, first, last):
            found.setdefault(row.get("name"), row)
    rows = list(found.values())
    # 出差按工作日算天：工作日要覆盖每张出差的日期（太长的坏数据 days_of 本来就不算）。
    ranges = [(month_first, month_last), (start, end)]
    for row in rows:
        if row.get("request_type") == REQUEST_TRAVEL:
            try:
                first, last = att.as_date(row.get("travel_start_date")), att.as_date(row.get("travel_end_date") or row.get("travel_start_date"))
            except ValueError:
                continue
            if first <= last and (last - first).days <= 366:
                ranges.append((first, last))
    months = sorted({key for first, last in ranges for key in _months(first, last)})
    work_dates = set()
    for year, number in months:
        work_dates |= set(resolve_monthly_calendar(year, number)["work_dates"])
    return {
        "level": scope["level"], "today": today.isoformat(), "month": month_first.strftime("%Y-%m"),
        "start": start.isoformat(), "end": end.isoformat(), "department": department if scope["level"] == COMPANY else "",
        "label": label, "headcount": len(ids),
        "work_dates": sorted(day.isoformat() for day in work_dates if start <= day <= end),
        "rows": board.request_rows(staff, rows, month_first=month_first, month_last=month_last, work_dates=work_dates),
    }


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
        # 部门主管只给自己团队里的人名：申请人不在他的团队里，就什么演示员工177给。
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
        person["pending"] = person["pending"] and not board.is_approved(row)
        if kind in board.ABSENCE_KINDS:
            person["kind"] = kind
    people = sorted(({**person, "dates": [day.isoformat() for day in sorted(person["dates"])]} for person in found.values()),
                    key=lambda item: (item["dates"][0], item["name"] or ""))
    return {"visible": True, "count": len(people), "people": people[:12]}
