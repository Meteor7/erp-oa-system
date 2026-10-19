"""请假 / 加班 / 调休 / 出差页面接口（模块 4）。

页面的数据都在这里取：员工看到自己的额度、本月考勤和日历；审批人看到待审批的申请、批之前的影响，
以及本部门未来两周谁不在。提交、审批、驳回、撤回沿用 api/oa_entry.py 的接口，这里只读。
范围都由服务端定：员工只看自己；审批人的"谁不在"只给自己审批的申请所属部门和自己直属的下属所在部门，
只显示名字和日期，不显示请假类型和事由。
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import frappe

from rayher_hr_payroll import annual_leave, attendance_board as board, attendance_center as center, attendance_requests as att
from rayher_hr_payroll.api import oa_entry
from rayher_hr_payroll.attendance_scope import EMPLOYEE, MANAGER, resolve_scope
from rayher_hr_payroll.team_scope import team_members
from rayher_hr_payroll.oa_approval import ApprovalRouteError
from rayher_hr_payroll.oa_document_types import REQUEST_PAYMENT, REQUEST_REIMBURSEMENT, REQUEST_TRAVEL
from rayher_hr_payroll.oa_feature_gate import can_access_request_type
from rayher_hr_payroll.working_calendar import resolve_monthly_calendar, resolve_monthly_work_limit
from rayher_hr_payroll import site_time

REVIEW_LIMIT = 50
REVIEWED_LIMIT = 30
ALL_LIMIT = 100
MAX_TEAM_DEPARTMENTS = 3
# 人事和老板可以看到所有人的请假、加班、调休（只读）；其他人只看自己的和轮到自己审批的。
ALL_VIEW_ROLES = {"System Manager", "HR Manager", "HR User", "QIHENG Demo Business Executive"}
# 考勤中心里的申请类型：请假、加班、调休，加上出差（出差是"人在不在岗"的申请，和它们同一个入口、同一套可见范围；
# 单据类型和审批路线没变，报销、付款仍然按单号关联它）。额度、日历这些请假专用的计算仍然只认 att.ATTENDANCE_TYPES。
LIST_TYPES = (*att.ATTENDANCE_TYPES, REQUEST_TRAVEL)


def _user():
    user = str(frappe.session.user or "").strip().lower()
    if not user or user == "guest":
        frappe.throw(frappe._("请先登录。"), frappe.PermissionError)
    return user


def _types():
    """当前账号能用的申请类型（加班、调休和请假共用一个开关，出差是单独的开关，各自单独判断）。"""
    return [item for item in LIST_TYPES if can_access_request_type(item)]


def _require_types():
    types = _types()
    if not types:
        frappe.throw(frappe._("当前审批功能暂未开放。"), frappe.PermissionError)
    return types


def can_view_all():
    """能不能看所有人的请假 / 加班 / 调休 / 出差（页面上的"全部"栏目，只读）。
    人事和老板的角色，加上总经理、副总经理岗位（决定 2026-10-13：看板上他们看得到公司考勤的数字，点进去也要能看到）。"""
    from rayher_hr_payroll.hr_read_access import is_hr_leader

    user = str(frappe.session.user or "").strip()
    if not user or user.lower() == "guest":
        return False
    return user == "Administrator" or bool(set(frappe.get_roles(user) or []) & ALL_VIEW_ROLES) or is_hr_leader(user)


def _days_of(raw):
    """申请的逐日明细 [{work_date, hours}]；格式不对时给空列表。"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _employee():
    try:
        return oa_entry._leave_employee_context(), ""
    except ApprovalRouteError as exc:
        return None, str(exc)


def _names(users):
    users = sorted({str(item or "").strip().lower() for item in users if item})
    if not users:
        return {}
    rows = frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "full_name"], limit_page_length=len(users))
    found = {str(row.get("name") or "").lower(): row.get("full_name") or "" for row in rows}
    return {user: found.get(user) or user.split("@")[0] for user in users}


def department_label(value):
    """ERPNext 部门名带公司后缀（"客服部 - RAY"），页面上只显示前面的部门名。"""
    text = oa_entry._display_department(value)
    return re.sub(r"\s+-\s+[A-Za-z0-9]{1,8}$", "", text)


def _events(row):
    raw = row.get("operation_log") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    return raw if isinstance(raw, list) else []


def _rejection(row):
    """最近一次被驳回给申请人的记录：(操作人, 时间, 原因)；没有返回 None。"""
    for event in reversed(_events(row)):
        if event.get("action") in ("Targeted rejection", "定向驳回"):
            actor = (event.get("details") or {}).get("actor") or event.get("actor") or event.get("user") or ""
            return actor, event.get("timestamp") or event.get("acted_on"), event.get("note") or ""
    return None


def _work_dates(first, last):
    """公司日历上 [first, last] 里的工作日。"""
    result = set()
    for year, month in sorted({(first.year, first.month), (last.year, last.month)}):
        result |= set(resolve_monthly_calendar(year, month)["work_dates"])
    return {day for day in result if first <= day <= last}


@frappe.whitelist()
def get_attendance_home(request_type=None, period=None):
    """员工首页：额度、本月考勤、日历。period 是 "2026-10"，空就是当月。"""
    _user()
    types = _require_types()
    request_type = request_type if request_type in types else types[0]
    year, month, first, last = center.period_bounds(period)
    context, reason = _employee()
    result = {
        "request_type": request_type, "types": types, "period": f"{year}-{month:02d}", "employee": None,
        "reason": reason, "leave_types": list(att.LEAVE_TYPES), "can_view_all": can_view_all(),
    }
    if not context:
        return result
    employee = context["employee"]
    rows = att.active_rows(employee, first, last)
    calendar_info = resolve_monthly_calendar(year, month, employee=employee)
    limit = resolve_monthly_work_limit(year, month, employee=employee)
    totals = center.month_totals(rows, first, last)
    result.update({
        "employee": {
            "name": employee, "employee_name": context.get("employee_name"),
            "department": context.get("department"), "supervisor": context.get("supervisor"),
        },
        "annual": annual_leave.get_annual_balance(employee),
        "comp": att.get_balance(employee),
        "month": {
            **totals,
            "base_hour_limit": limit.get("base_hour_limit"),
            "cap_deducted_hours": limit.get("leave_hours"),
            "hour_limit": limit.get("hour_limit"),
        },
        "calendar": {
            "period": f"{year}-{month:02d}", "days_in_month": last.day, "first_weekday": first.weekday(),
            "work_dates": sorted(day.isoformat() for day in calendar_info["work_dates"]),
            "entries": center.calendar_entries(rows, first, last),
        },
    })
    return result


@frappe.whitelist()
def get_attendance_route(request_type, from_date=None, to_date=None):
    """新建申请时的审批路线：审批人给姓名，不再给邮箱。请假连续 3 个日历日以内到人事经理为止，所以要带起止日期。"""
    _user()
    if request_type not in LIST_TYPES:
        frappe.throw(frappe._("不支持的申请类型。"))
    preview = oa_entry.preview_route(request_type, from_date=from_date or None, to_date=to_date or None)
    steps = preview.get("steps") or []
    copied = preview.get("copied_to") or []
    names = _names([user for step in steps for user in step.get("approvers") or []] + [row.get("user") for row in copied])
    return {
        "short_leave": bool(preview.get("short_leave")),
        "steps": [{
            "step_index": step.get("step_index"), "label": step.get("label"), "mode": step.get("mode"),
            "approvers": [{"user": user, "name": names.get(str(user).lower(), user)} for user in step.get("approvers") or []],
        } for step in steps],
        "copied_to": [{"user": row.get("user"), "label": row.get("label"), "name": names.get(str(row.get("user") or "").lower(), "")} for row in copied],
    }


def _balances(employee, cache):
    if employee not in cache:
        cache[employee] = {"annual": annual_leave.get_annual_balance(employee), "comp": att.get_balance(employee)}
    return cache[employee]


@frappe.whitelist()
def get_attendance_request(name):
    """一张申请的详情：申请本身（沿用列表接口的权限和字段）、审批人姓名、通过后的影响；出差申请另带 mine（是不是我自己的）。"""
    _user()
    _require_types()
    rows = oa_entry.list_requests(view="all", name=name, limit=1)
    row = rows[0] if rows else None
    if not row and (can_view_all() or _in_my_team(name)):
        # 人事和老板可以只读查看任何一张已提交的申请（草稿只有本人看得到）；部门主管可以只读查看自己团队
        # （汇报关系向下）的人的申请——看板“团队本月请假 / 今天不在岗”点进去的每一行就是这些单据。
        found = _load_summaries(_attendance_names(None, 1, name=name))
        row = found[0] if found else None
    if not row or row.get("request_type") not in LIST_TYPES:
        frappe.throw(frappe._("找不到这张申请，或你没有权限查看。"), frappe.DoesNotExistError)
    balances = _balances(row.get("employee"), {}) if row.get("employee") else {"annual": None, "comp": None}
    users = [user for step in row.get("steps") or [] for user in step.get("approvers") or []]
    users += [step.get("action_by") for step in row.get("steps") or []]
    users += [entry.get("user") for entry in row.get("copied_to") or [] if isinstance(entry, dict)]
    # 是不是我自己的出差申请（决定要不要显示"发起报销 / 发起付款"）：和"我的"列表同一个判断。
    is_trip = row.get("request_type") == REQUEST_TRAVEL
    mine = bool(oa_entry.list_requests(view="mine", name=name, limit=1)) if is_trip else False
    return {
        "request": row,
        "names": _names(users),
        "impact": center.impact_text(row, annual=balances["annual"], comp=balances["comp"]),
        "mine": mine,
        "linked": _linked_documents(row.get("name")) if is_trip else [],
    }


def _in_my_team(name):
    """这张申请的申请人在不在我的团队里（我是部门主管时）。查不出来就当不在（只会少给看，不会多给看）。"""
    try:
        scope = resolve_scope()
        if scope["level"] != MANAGER:
            return False
        employee = frappe.db.get_value("OA Approval Request", name, "employee")
        return bool(employee) and employee in {member.get("name") for member in team_members(scope["employee"], include_self=True)}
    except Exception:
        return False


@frappe.whitelist()
def list_attendance_away_today():
    """今天不在岗（请假 / 调休）的人，一人一张单（口径同看板“今天不在岗”：attendance_board_entry.today_away）。
    只读；人事、老板、总经理、副总经理才能看（和“全部”同一个权限）。出差中的人另算，只给人数。"""
    _user()
    _require_types()
    if not can_view_all():
        frappe.throw(frappe._("只有人事或管理员可以查看全部申请。"), frappe.PermissionError)
    from rayher_hr_payroll.api import attendance_board_entry

    away = attendance_board_entry.today_away(site_time.today())
    rows = _load_summaries([item["request"] for item in away["off"] if item.get("request")])
    return {"items": rows, "names": _names(_people(rows)), "trip": len(away["trip"])}


def _linked_documents(trip):
    """报销、付款里关联了这张出差申请的单据（出差途中的打车、住宿等费用在那边报）：只列当前登录人自己有权打开的。"""
    names = frappe.get_all(
        "OA Approval Request", filters={"source_request": trip, "request_type": ["in", [REQUEST_REIMBURSEMENT, REQUEST_PAYMENT]]},
        pluck="name", order_by="creation desc", limit_page_length=50,
    )
    linked = []
    for name in names:
        found = oa_entry.list_requests(view="all", name=name, limit=1)
        if found:
            item = found[0]
            linked.append({key: item.get(key) for key in ("name", "request_type", "subject", "employee_name", "amount", "workflow_status", "business_status")})
    return linked


def _attendance_names(request_types, limit, name=None):
    """已提交的（不含草稿）请假 / 加班 / 调休 / 出差单号，最近改过的在前。只给有"看全部"权限的人用。"""
    types = tuple(request_types or LIST_TYPES)
    sql = ("SELECT name FROM `tabOA Approval Request` WHERE request_type IN %(types)s AND workflow_status <> '草稿'"
           + (" AND name = %(name)s" if name else "") + " ORDER BY modified DESC, name DESC LIMIT %(limit)s")
    rows = frappe.db.sql(sql, {"types": types, "limit": limit, "name": name}, as_dict=True)
    return [row.get("name") for row in rows]


def _load_summaries(names):
    """和 oa_entry.list_requests 一样的单据摘要（审批人姓名、步骤、可执行的操作按当前登录人算）。"""
    from rayher_hr_payroll.procurement_summary_cache import prepare_summaries
    docs = [oa_entry._load_request(name) for name in names]
    with prepare_summaries(docs, oa_entry._calculate_procurement_chain):
        return [oa_entry._summarize_doc(doc) for doc in docs]


def _people(rows):
    """这些申请当前审批人和被退回时的操作人（用来显示姓名）。"""
    users = []
    for row in rows:
        for step in row.get("steps") or []:
            if step.get("step_index") == row.get("current_step_index"):
                users += step.get("approvers") or []
        rejection = _rejection(row)
        if rejection:
            users.append(rejection[0])
    return users


@frappe.whitelist()
def list_attendance_all(request_type=None, limit=ALL_LIMIT):
    """全部请假 / 加班 / 调休 / 出差（只读；人事和老板才能看）：已提交的，最近有动静的在前。"""
    _user()
    types = _require_types()
    if not can_view_all():
        frappe.throw(frappe._("只有人事或管理员可以查看全部申请。"), frappe.PermissionError)
    if request_type and request_type not in types:
        frappe.throw(frappe._("不支持的申请类型。"))
    try:
        limit = max(1, min(int(limit or ALL_LIMIT), 200))
    except (TypeError, ValueError):
        frappe.throw(frappe._("查询数量格式无效。"))
    rows = _load_summaries(_attendance_names([request_type] if request_type else types, limit))
    return {"items": rows, "names": _names(_people(rows))}


def _department_mates(employees):
    """给定员工所在的部门（Employee 表里的部门）：{部门: [该部门在职员工]}。"""
    rows = frappe.get_all(
        "Employee", filters={"name": ["in", sorted(employees)], "status": "Active"},
        fields=["name", "department"], limit_page_length=len(employees) or 1,
    ) if employees else []
    departments = sorted({row.get("department") for row in rows if row.get("department")})
    result = {}
    for department in departments:
        result[department] = frappe.get_all(
            "Employee", filters={"department": department, "status": "Active"},
            fields=["name", "employee_name"], order_by="name asc", limit_page_length=500,
        )
    return result


def _absence_rows(employees, start, end):
    if not employees:
        return []
    statuses, types = sorted(att.ACTIVE), [att.REQUEST_LEAVE, att.REQUEST_COMP_TIME]
    return frappe.db.sql(
        "SELECT name, employee, employee_name, request_type, leave_type, workflow_status, from_date, to_date, "
        "attendance_days, duration_hours FROM `tabOA Approval Request` "
        "WHERE employee IN %(employees)s AND request_type IN %(types)s AND workflow_status IN %(statuses)s "
        "AND from_date <= %(end)s AND to_date >= %(start)s",
        {"employees": tuple(sorted(employees)), "types": tuple(types), "statuses": tuple(statuses), "start": start, "end": end},
        as_dict=True,
    )


def _team(departments, today):
    """每个部门未来两周谁不在。"""
    last = today + timedelta(days=center.TEAM_WINDOW_DAYS - 1)
    work_dates = _work_dates(today, last)
    result = []
    for department, members in list(departments.items())[:MAX_TEAM_DEPARTMENTS]:
        employees = [row.get("name") for row in members]
        rows = _absence_rows(employees, today, last)
        info = center.team_absence(today, work_dates, members, rows)
        result.append({"department": department_label(department), **info})
    return result


@frappe.whitelist()
def list_attendance_review():
    """待我审批：请假、加班、调休、出差合在一起，每条带上批之前要看到的影响，另附相关部门未来两周谁不在。"""
    user = _user()
    types = _require_types()
    items = []
    for request_type in types:
        try:
            items += oa_entry.list_requests(view="pending", request_type=request_type, limit=REVIEW_LIMIT)
        except frappe.PermissionError:
            continue
    items = [row for row in items if row.get("request_type") in LIST_TYPES]
    items.sort(key=lambda row: str(row.get("name") or ""))
    cache, mates_cache = {}, {}
    applicants = {row.get("employee") for row in items if row.get("employee")}
    departments = _department_mates(applicants)
    department_of = {}
    for department, members in departments.items():
        for member in members:
            department_of[member.get("name")] = department
    for department, members in departments.items():
        mates_cache[department] = _absence_rows([m.get("name") for m in members], site_time.today() - timedelta(days=1), site_time.today() + timedelta(days=400))
    enriched = []
    for row in items:
        employee = row.get("employee")
        balances = _balances(employee, cache) if employee else {"annual": None, "comp": None}
        year_count = 0
        if row.get("leave_type") == "事假" and row.get("from_date"):
            year_count = _leave_count_in_year(employee, row)
        teammates = 0
        if row.get("request_type") != att.REQUEST_OVERTIME:
            days = {day for day, _hours in board.days_of(row)} if row.get("request_type") == REQUEST_TRAVEL \
                else {day for day, hours in att.expand_days(row) if hours > 0}
            department = department_of.get(employee)
            people = set()
            for other in mates_cache.get(department, []):
                if other.get("employee") == employee or other.get("name") == row.get("name"):
                    continue
                if any(day in days and hours > 0 for day, hours in att.expand_days(other)):
                    people.add(other.get("employee"))
            teammates = len(people)
        enriched.append({
            **row,
            "hints": center.review_hints(row, annual=balances["annual"], comp=balances["comp"],
                                         year_leave_count=year_count, teammates_off=teammates),
            "impact": center.impact_text(row, annual=balances["annual"], comp=balances["comp"]),
        })
    # 相关部门：待审批申请的申请人所在部门，加上直属下属所在部门（没有待审批时也能看部门情况）。
    mine = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
    if mine:
        reports = frappe.get_all("Employee", filters={"reports_to": mine, "status": "Active"}, pluck="name", limit_page_length=500)
        for department, members in _department_mates(set(reports)).items():
            departments.setdefault(department, members)
    # 没有管理职责的员工不返回"谁不在"：同事的请假不给他们看。部门主管只看自己的团队（汇报关系向下，
    # 下属在哪个部门都算）；人事、管理层看相关部门。
    scope = resolve_scope()
    if scope["level"] == EMPLOYEE:
        team = []
    elif scope["level"] == MANAGER:
        team = _team({"我的团队": team_members(scope["employee"], include_self=True)}, site_time.today())
    else:
        team = _team(departments, site_time.today())
    return {"items": enriched, "team": team}


def _leave_count_in_year(employee, row):
    if not employee:
        return 0
    year = att.as_date(row.get("from_date")).year
    rows = frappe.db.sql(
        "SELECT COUNT(*) AS n FROM `tabOA Approval Request` WHERE employee = %s AND request_type = %s "
        "AND leave_type = %s AND workflow_status IN %s AND YEAR(from_date) = %s "
        "AND creation <= (SELECT creation FROM `tabOA Approval Request` WHERE name = %s)",
        (employee, att.REQUEST_LEAVE, "事假", tuple(sorted(att.ACTIVE)), year, row.get("name")), as_dict=True,
    )
    return int(rows[0]["n"] or 0) if rows else 0


@frappe.whitelist()
def list_attendance_reviewed(limit=REVIEWED_LIMIT):
    """我审批过的请假、加班、调休、出差（我处理过的步骤，最近的在前）。"""
    user = _user()
    _require_types()
    try:
        limit = max(1, min(int(limit or REVIEWED_LIMIT), 100))
    except (TypeError, ValueError):
        frappe.throw(frappe._("查询数量格式无效。"))
    rows = frappe.db.sql(
        "SELECT p.name, p.request_type, p.leave_type, p.employee_name, p.department, p.from_date, p.to_date, "
        "p.duration_hours, p.workflow_status, p.subject, p.attendance_days, p.creation, p.reason, p.project, "
        "p.travel_destination, p.travel_start_date, p.travel_end_date, p.travel_days, s.label AS step_label, "
        "s.status AS my_status, s.acted_on, s.note FROM `tabOA Approval Step` s JOIN `tabOA Approval Request` p ON p.name = s.parent "
        "WHERE LOWER(s.action_by) = %(user)s AND p.request_type IN %(types)s "
        "ORDER BY s.acted_on DESC LIMIT %(limit)s",
        {"user": user, "types": tuple(LIST_TYPES), "limit": limit}, as_dict=True,
    )
    return {"items": [
        dict(row, department=department_label(row.get("department")), attendance_days=_days_of(row.get("attendance_days")))
        for row in rows]}


@frappe.whitelist()
def list_attendance_mine(request_type=None, limit=50):
    """我的申请：沿用列表接口，另外给出当前审批人姓名和被退回时的操作人姓名（页面上显示"等 陈立 审批"）。"""
    _user()
    types = _require_types()
    if request_type and request_type not in types:
        frappe.throw(frappe._("不支持的申请类型。"))
    try:
        limit = max(1, min(int(limit or 50), 100))
    except (TypeError, ValueError):
        frappe.throw(frappe._("查询数量格式无效。"))
    rows = oa_entry.list_requests(view="mine", request_type=request_type, limit=limit)
    rows = [row for row in rows if row.get("request_type") in types]
    return {"items": rows, "names": _names(_people(rows))}
