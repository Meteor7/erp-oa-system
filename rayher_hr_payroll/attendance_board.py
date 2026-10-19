"""考勤中心图表和团队日历的统计（不依赖 frappe，便于单元测试）。

三种身份看到的东西不一样，范围由 api/attendance_board_entry.py 按身份定好以后才调用这里：
- 员工只看自己：额度以外的"我今年请假构成""近 6 个月""未来 14 天我的安排"（build_personal）；
- 部门主管看自己的团队：每个人 14 天的日历（build_members）、团队的汇总数字（build_stats）和一张申请一行的明细（request_rows）；
- 人事和管理层看全公司：各部门的汇总数字（summarize_departments，部门概况表），和全公司一张申请一行的明细（request_rows，带人名，
  决定 2026-10-14：首页直接显示是谁，不再先看部门数字、点进部门才有人名）；点进某个部门再看那个部门的日历。
统计只算已通过的请假、调休、出差、加班；日历上审批中的也显示（虚线），但不进统计。
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from rayher_hr_payroll.attendance_center import WEEKDAYS
from rayher_hr_payroll.attendance_requests import (
    ACTIVE,
    COMPLETED,
    REQUEST_COMP_TIME,
    REQUEST_LEAVE,
    REQUEST_OVERTIME,
    ZERO,
    as_date,
    expand_days,
    value,
)
from rayher_hr_payroll.oa_document_types import REQUEST_TRAVEL

WINDOW_DAYS = 14
DAY_HOURS = Decimal("8")
# 请假类型 -> 颜色类别；其他假（婚假、产假、陪产假、丧假、其他假）归在一起。加班和出差不算"不在岗"。
LEAVE_KINDS = {"年假": "annual", "事假": "personal", "病假": "sick"}
ABSENCE_KINDS = ("annual", "personal", "sick", "comp", "other")
KIND_LABELS = {"annual": "年假", "personal": "事假", "sick": "病假", "comp": "调休", "other": "其他假", "trip": "出差", "ot": "加班"}
ALL_KINDS = ABSENCE_KINDS + ("trip", "ot")
# 日历格子里同一天有几条记录时，显示哪一条：先已通过后审批中，再请假调休、出差、加班。
_KIND_RANK = {kind: (0 if kind in ABSENCE_KINDS else 1 if kind == "trip" else 2) for kind in ALL_KINDS}


def is_approved(row):
    """已批准：请假、加班、调休通过后是已完成 / 已通过；出差两级审批通过后到前台办理（待办理），
    按出差日期算人，不等前台点完“已办理”（副总、总经理自己出差直接到前台备案，也算）。"""
    status = value(row, "workflow_status")
    return status in COMPLETED or (value(row, "request_type") == REQUEST_TRAVEL and status == "待办理")


def _num(hours):
    number = float(hours)
    return int(number) if number == int(number) else round(number, 2)


def kind_of(row):
    """一张申请落在哪个颜色类别；不是考勤类的单据给 None。"""
    request_type = value(row, "request_type")
    if request_type == REQUEST_COMP_TIME:
        return "comp"
    if request_type == REQUEST_OVERTIME:
        return "ot"
    if request_type == REQUEST_TRAVEL:
        return "trip"
    if request_type == REQUEST_LEAVE:
        return LEAVE_KINDS.get(value(row, "leave_type"), "other")
    return None


def days_of(row, work_dates=None):
    """一张申请占用的每一天 [(日期, 小时)]。出差没有小时数：出发到返回的每个工作日算 8 小时。明细坏了给空列表。"""
    try:
        if value(row, "request_type") == REQUEST_TRAVEL:
            start = as_date(value(row, "travel_start_date"))
            end = as_date(value(row, "travel_end_date") or value(row, "travel_start_date"))
            if end < start or (end - start).days > 366:
                return []
            span = (start + timedelta(days=offset) for offset in range((end - start).days + 1))
            return [(day, DAY_HOURS) for day in span if work_dates is None or day in work_dates]
        return [(day, hours) for day, hours in expand_days(row) if hours > 0]
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return []


def window_days(first, work_dates, count=WINDOW_DAYS):
    """从 first 起 count 天：[{date, label, day, weekday, off_day}]，off_day 是休息日。"""
    result = []
    for offset in range(count):
        day = first + timedelta(days=offset)
        result.append({
            "date": day.isoformat(), "label": f"{day.month}/{day.day}", "day": day.day,
            "weekday": WEEKDAYS[day.weekday()], "off_day": day not in work_dates,
        })
    return result


def _days(hours):
    return round(float(hours or 0) / float(DAY_HOURS), 2)


def _legacy_month_hours(row, month_first, month_last):
    """没有逐日明细的旧申请：按原来的规矩，duration_hours 整张记在开始日期所在的月（不按工作日 8 小时拆）。"""
    try:
        start = as_date(value(row, "from_date"))
        hours = Decimal(str(value(row, "duration_hours") or 0))
    except (ValueError, TypeError, ArithmeticError):
        return ZERO
    return hours if month_first <= start <= month_last else ZERO


def month_hours(row, month_first, month_last, work_dates=None):
    """一张申请落在 [month_first, month_last] 里的小时：请假 / 调休 / 加班按逐日明细，没有明细的旧申请按 _legacy_month_hours；
    出差没有小时数，按出发到返回之间落在这个月里的工作日、每天 8 小时（work_dates 要覆盖出差的日期）。别的类型是 0。
    month_window（看板和考勤中心的“本月请假 / 加班”）和首页明细（request_rows）都用它，所以两边的数一定对得上。"""
    request_type = value(row, "request_type")
    if request_type == REQUEST_TRAVEL:
        return sum((hours for day, hours in days_of(row, work_dates) if month_first <= day <= month_last), ZERO)
    if request_type not in (REQUEST_LEAVE, REQUEST_COMP_TIME, REQUEST_OVERTIME):
        return ZERO
    if value(row, "attendance_days"):
        return sum((hours for day, hours in days_of(row) if month_first <= day <= month_last), ZERO)
    return _legacy_month_hours(row, month_first, month_last)


def month_window(rows, month_first, month_last):
    """请假 / 调休 / 加班按天拆到 [month_first, month_last]：每张申请只留落在这段日期里的小时（duration_hours 换成这个数），
    一点都不落在里面的丢掉。调用方只传已批准的。
    修复（2026-10-13 审查）：没有逐日明细（attendance_days）的旧申请不再按每个工作日 8 小时拆（周六加班会丢、
    2 小时加班变 8 小时、4 小时半天假变 8 小时），按原来的规矩：duration_hours 记在开始日期所在的月。"""
    result = []
    for row in rows:
        if value(row, "request_type") not in (REQUEST_LEAVE, REQUEST_COMP_TIME, REQUEST_OVERTIME):
            continue
        hours = month_hours(row, month_first, month_last)
        if hours > 0:
            result.append({**dict(row), "duration_hours": float(hours)})
    return result


def leave_figures(rows, employee_ids=None):
    """“本月请假 / 调休 / 加班”的唯一口径（决定 2026-10-13）：看板的本月请假、请假类型、各部门请假、团队本月请假，
    和考勤中心首页的“本月请假”都用它，数字一定对得上。

    rows：已批准的申请，duration_hours 已经是落在这个月里的小时（month_window 拆好的）。employee_ids 给了就只算这些人（在职的人）。
    请假只算请假申请，按天（小时 ÷ 8）；调休单独算、不进请假合计；加班另算。
    返回 {leave_hours, leave_days, leave_count, comp_hours, comp_days, comp_count, overtime_hours, overtime_days, overtime_count,
          by_type {假别: 小时}（只有请假）, by_kind {颜色类别: 小时}（请假各类 + 调休）, by_employee {员工: {name, leave, comp, overtime}}（小时）,
          requests [{name, employee, employee_name, request_type, leave_type, from_date, to_date, hours}]}。
    """
    ids = None if employee_ids is None else set(employee_ids)
    keys = {REQUEST_LEAVE: "leave", REQUEST_COMP_TIME: "comp", REQUEST_OVERTIME: "overtime"}
    hours = {"leave": 0.0, "comp": 0.0, "overtime": 0.0}
    counts = {"leave": 0, "comp": 0, "overtime": 0}
    by_type, by_kind, by_employee, requests = {}, {}, {}, []
    for row in rows:
        key = keys.get(value(row, "request_type"))
        employee = value(row, "employee") or value(row, "employee_name") or ""
        if not key or (ids is not None and value(row, "employee") not in ids):
            continue
        amount = float(value(row, "duration_hours") or 0)
        if amount <= 0:
            continue
        hours[key] += amount
        counts[key] += 1
        if key == "leave":
            leave_type = value(row, "leave_type") or "未填类别"
            by_type[leave_type] = by_type.get(leave_type, 0.0) + amount
        if key != "overtime":
            kind = kind_of(row)
            by_kind[kind] = by_kind.get(kind, 0.0) + amount
        person = by_employee.setdefault(employee, {"name": value(row, "employee_name") or employee, "leave": 0.0, "comp": 0.0, "overtime": 0.0})
        person[key] += amount
        requests.append({"name": value(row, "name") or "", "employee": value(row, "employee") or "", "employee_name": value(row, "employee_name") or employee,
                         "request_type": value(row, "request_type"), "leave_type": value(row, "leave_type") or "",
                         "from_date": str(value(row, "from_date") or "")[:10], "to_date": str(value(row, "to_date") or value(row, "from_date") or "")[:10],
                         "hours": round(amount, 2)})
    out = {}
    for key in ("leave", "comp", "overtime"):
        out[f"{key}_hours"] = round(hours[key], 2)
        out[f"{key}_days"] = _days(hours[key])
        out[f"{key}_count"] = counts[key]
    out.update(by_type={key: round(item, 2) for key, item in by_type.items()}, by_kind={key: round(item, 2) for key, item in by_kind.items()},
               by_employee=by_employee, requests=requests)
    return out


def today_away(employee_ids, rows, *, first, work_dates):
    """“今天不在岗”的唯一口径（决定 2026-10-13）：看板的今天不在岗（公司、团队）、考勤中心今天请假和“今天不在岗”列表、
    团队日历的不在岗人数都用它。

    - 不在岗 off：今天（工作日）有已批准的请假或调休、当天明细小时大于 0 的人，一人一条（同一个人几张单只取最早的一张）；
    - 出差中 trip：今天（工作日）在已批准的出差期间、今天没有请假 / 调休的人，一人一条；出差不算不在岗。前台待办理的出差已经批准，也算。
    今天是休息日两样都是空的。返回 {"off": [{employee, kind, request}], "trip": [{employee, request}]}。
    """
    if first not in work_dates:
        return {"off": [], "trip": []}
    ids = set(employee_ids)
    off, trips = {}, {}
    ordered = sorted(rows, key=lambda row: (str(value(row, "from_date") or value(row, "travel_start_date") or ""), str(value(row, "name") or "")))
    for row in ordered:
        employee = value(row, "employee")
        if not is_approved(row) or employee not in ids:
            continue
        kind = kind_of(row)
        if kind in ABSENCE_KINDS:
            if any(day == first and hours > 0 for day, hours in days_of(row, work_dates)):
                off.setdefault(employee, {"employee": employee, "kind": kind, "request": value(row, "name") or ""})
        elif kind == "trip" and first in {day for day, _hours in days_of(row, work_dates)}:
            trips.setdefault(employee, {"employee": employee, "request": value(row, "name") or "", "row": row})
    return {"off": list(off.values()), "trip": [item for employee, item in trips.items() if employee not in off]}


def build_stats(employee_ids, rows, *, first, work_dates, month_first, month_last, count=WINDOW_DAYS):
    """这批人的汇总数字（只有人数和小时，没有人名）。

    rows：这些人的申请（统计时只取已通过的）。返回：
    today {off, trip, in, rest_day, off_by_kind}：今天请假或调休 / 出差 / 在岗的人数（口径见 today_away）；
    month：本月请假（口径见 leave_figures）：hours / leave_days 只有请假，comp_hours / comp_days 是调休，per_capita 人均请假小时，
           per_capita_days 人均请假天数，by_kind 请假各类和调休各自的小时；
    rate：未来 count 天工作日的出勤率（请假和调休的小时占应出勤小时的比例）；
    days：每天 {off, by_kind}：当天各类型的人数（off = 请假和调休的人数）。
    """
    ids = set(employee_ids)
    headcount = len(ids)
    dates = [first + timedelta(days=offset) for offset in range(count)]
    index = {day: position for position, day in enumerate(dates)}
    per_day = [{} for _ in dates]
    absent = {}
    approved = []
    for row in rows:
        employee = value(row, "employee")
        if not is_approved(row) or employee not in ids:
            continue
        approved.append(row)
        kind = kind_of(row)
        if not kind:
            continue
        for day, hours in days_of(row, work_dates):
            if day in index:
                per_day[index[day]].setdefault(kind, set()).add(employee)
                if kind in ABSENCE_KINDS and day in work_dates:
                    absent[(employee, day)] = min(DAY_HOURS, absent.get((employee, day), ZERO) + hours)
    days = window_days(first, work_dates, count)
    for position, entry in enumerate(days):
        found = per_day[position]
        entry["off"] = len(set().union(*(found.get(kind, set()) for kind in ABSENCE_KINDS)))
        entry["by_kind"] = {kind: len(found.get(kind, ())) for kind in ALL_KINDS}
    away = today_away(ids, approved, first=first, work_dates=work_dates)
    off_by_kind = {}
    for item in away["off"]:
        off_by_kind[item["kind"]] = off_by_kind.get(item["kind"], 0) + 1
    work_days = sum(1 for day in dates if day in work_dates)
    capacity = DAY_HOURS * headcount * work_days
    rate = 1.0 if not capacity else round(float(1 - sum(absent.values(), ZERO) / capacity), 4)
    month = leave_figures(month_window(approved, month_first, month_last), ids)
    by_kind = {kind: _num(month["by_kind"].get(kind, 0)) for kind in ABSENCE_KINDS}
    gone, trip = len(away["off"]), len(away["trip"])
    return {
        "headcount": headcount,
        "today": {"off": gone, "trip": trip, "in": max(0, headcount - gone - trip), "rest_day": first not in work_dates,
                  "off_by_kind": off_by_kind},
        "month": {
            "hours": _num(month["leave_hours"]), "per_capita": round(month["leave_hours"] / headcount, 1) if headcount else 0,
            "leave_days": month["leave_days"], "per_capita_days": round(month["leave_days"] / headcount, 2) if headcount else 0,
            "comp_hours": _num(month["comp_hours"]), "comp_days": month["comp_days"],
            "by_kind": by_kind,
        },
        "rate": rate,
        "days": days,
    }


def today_trips(employees, rows, *, first, work_dates):
    """build_stats 里“今天出差”的那些人，一人一条（口径见 today_away，人数一定相等），
    多给每个人的单号、地点和日期，让看板的数字能点进具体的出差申请。
    """
    known = {value(employee, "name"): employee for employee in employees}
    result = []
    for item in today_away(list(known), rows, first=first, work_dates=work_dates)["trip"]:
        employee, row = item["employee"], item["row"]
        person = known[employee]
        result.append({
            "employee": employee, "employee_name": value(person, "employee_name") or employee, "department": value(person, "department") or "",
            "name": value(row, "name"), "destination": value(row, "travel_destination") or "",
            "start": str(value(row, "travel_start_date") or ""), "end": str(value(row, "travel_end_date") or value(row, "travel_start_date") or ""),
        })
    return sorted(result, key=lambda item: (item["department"], item["employee_name"], item["name"]))


def _better(candidate, current):
    if current is None:
        return True
    return (candidate["pending"], _KIND_RANK[candidate["kind"]]) < (current["pending"], _KIND_RANK[current["kind"]])


def _cells(rows, employee_ids, first, work_dates, count):
    """{员工: [每天一格 None | {kind, pending, hours}]}（审批中和已通过的都画；同一天有几条取最该显示的一条）。"""
    index = {first + timedelta(days=offset): offset for offset in range(count)}
    cells = {employee: [None] * count for employee in employee_ids}
    for row in rows:
        employee = value(row, "employee")
        if value(row, "workflow_status") not in ACTIVE or employee not in cells:
            continue
        kind = kind_of(row)
        if not kind:
            continue
        pending = not is_approved(row)
        for day, hours in days_of(row, work_dates):
            if day in index:
                cell = {"kind": kind, "pending": pending, "hours": _num(hours)}
                if _better(cell, cells[employee][index[day]]):
                    cells[employee][index[day]] = cell
    return cells


def build_members(members, rows, *, first, work_dates, count=WINDOW_DAYS):
    """部门日历：[{id, name, cells}]，members 是 [{name: 员工号, employee_name}]。只给调用方已经校验过范围的部门用。"""
    ids = [value(member, "name") for member in members]
    cells = _cells(rows, ids, first, work_dates, count)
    return [{"id": value(member, "name"), "name": value(member, "employee_name") or value(member, "name"),
             "cells": cells[value(member, "name")]} for member in members]


def build_personal(employee, rows, *, first, work_dates, year, count=WINDOW_DAYS, months=6):
    """员工自己的：未来 count 天的安排、今年请假构成（小时）、最近 months 个月的请假小时。rows 必须只是本人的申请。"""
    cells = _cells(rows, [employee], first, work_dates, count)[employee]
    strip = [{**entry, "kind": (cell or {}).get("kind"), "pending": bool(cell and cell["pending"]), "hours": (cell or {}).get("hours", 0)}
             for entry, cell in zip(window_days(first, work_dates, count), cells)]
    by_kind = {kind: ZERO for kind in ABSENCE_KINDS}
    month_keys = []
    year_number, month_number = first.year, first.month
    for _ in range(months):
        month_keys.append((year_number, month_number))
        month_number -= 1
        if month_number == 0:
            year_number, month_number = year_number - 1, 12
    month_keys.reverse()
    by_month = {key: ZERO for key in month_keys}
    for row in rows:
        if value(row, "workflow_status") not in ACTIVE or value(row, "employee") != employee:
            continue
        kind = kind_of(row)
        if kind not in ABSENCE_KINDS:
            continue
        for day, hours in days_of(row, work_dates):
            if day.year == year:
                by_kind[kind] += hours
            if (day.year, day.month) in by_month:
                by_month[(day.year, day.month)] += hours
    return {
        "strip": strip,
        "year": year,
        "year_by_kind": {kind: _num(hours) for kind, hours in by_kind.items()},
        "months": [{"period": f"{y}-{m:02d}", "label": f"{m}月", "hours": _num(by_month[(y, m)])} for y, m in month_keys],
    }


def department_labels(departments):
    """部门页面上显示的名字：去掉 ERPNext 的公司后缀；去掉后重名的（不同公司的同名部门）保留全名。"""
    import re
    short = {name: re.sub(r"\s+-\s+[A-Za-z0-9]{1,8}$", "", name) for name in departments}
    counts = {}
    for text in short.values():
        counts[text] = counts.get(text, 0) + 1
    return {name: (short[name] if counts[short[name]] == 1 else name) for name in departments}


def _iso(raw):
    return str(raw or "")[:10]


def request_rows(employees, rows, *, month_first, month_last, work_dates, labels=None):
    """考勤中心首页的明细：一张申请一行，带人名（“谁不在”“未来 14 天”“N 月概览”“近 5 个工作日”都从这一份算）。
    只给调用方已经校验过范围的人用：人事和管理层是全公司（或选中的部门），部门主管是自己的团队。

    employees：[{name, employee_name, department}]（在职的；不在里面的人的申请丢掉）；rows：这些人的申请。
    只留审批中和已批准的（ACTIVE；草稿、撤回、驳回不要）。approved 的口径见 is_approved（出差到前台待办理算已批准），
    没批准的前端只列出来、标“审批中”，不进人数和合计。
    days：每天的小时 [[日期, 小时]]（出差只算工作日、每天 8 小时，work_dates 要覆盖出差的日期）；
    month_hours：落在 [month_first, month_last] 里的小时，算法是 month_hours（和 month_window / leave_figures 同一个），
    所以把已批准的按类型加起来，一定等于看板的“本月请假 / 本月加班”和“另有调休”。
    返回按开始日期、部门、姓名、单号排好的 [{name, employee, employee_name, department, department_label, request_type, kind,
    leave_type, workflow_status, approved, current_step_label, from_date, to_date, travel_destination, days, month_hours}]。
    """
    known = {value(employee, "name"): employee for employee in employees}
    if labels is None:
        labels = department_labels(sorted({value(employee, "department") or "" for employee in employees} - {""}))
    result = []
    for row in rows:
        employee = value(row, "employee")
        kind = kind_of(row)
        if employee not in known or not kind or value(row, "workflow_status") not in ACTIVE:
            continue
        person = known[employee]
        trip = kind == "trip"
        start = value(row, "travel_start_date") if trip else value(row, "from_date")
        end = (value(row, "travel_end_date") if trip else value(row, "to_date")) or start
        department = value(person, "department") or ""
        result.append({
            "name": value(row, "name") or "", "employee": employee,
            "employee_name": value(person, "employee_name") or value(row, "employee_name") or employee,
            "department": department, "department_label": labels.get(department, "未分配部门") if department else "未分配部门",
            "request_type": value(row, "request_type"), "kind": kind,
            "leave_type": (value(row, "leave_type") or "") if value(row, "request_type") == REQUEST_LEAVE else "",
            "workflow_status": value(row, "workflow_status"), "approved": is_approved(row),
            "current_step_label": value(row, "current_step_label") or "",
            "from_date": _iso(start), "to_date": _iso(end),
            "travel_destination": (value(row, "travel_destination") or "") if trip else "",
            "days": [[day.isoformat(), _num(hours)] for day, hours in days_of(row, work_dates)],
            "month_hours": _num(month_hours(row, month_first, month_last, work_dates)),
        })
    result.sort(key=lambda item: (item["from_date"], item["department_label"], item["employee_name"], item["name"]))
    return result


def summarize_departments(employees, rows, pending, *, first, work_dates, month_first, month_last):
    """公司汇总：全公司的统计 + 每个部门一行（只有数字，部门概况表用；人名在 request_rows 里，接口另外给）。

    employees：[{name, department}]（在职）；rows：这些人的申请；pending：{部门: 待审批的申请张数}。
    """
    by_department = {}
    for employee in employees:
        by_department.setdefault(value(employee, "department") or "", []).append(value(employee, "name"))
    labels = department_labels([name for name in by_department if name])
    rows = list(rows)
    options = dict(first=first, work_dates=work_dates, month_first=month_first, month_last=month_last)
    company = build_stats([value(employee, "name") for employee in employees], rows, **options)
    departments = []
    for department, ids in by_department.items():
        stats = build_stats(ids, rows, **options)
        departments.append({
            "department": department, "label": labels.get(department, "未分配部门"), "headcount": stats["headcount"],
            "today_off": stats["today"]["off"], "today_trip": stats["today"]["trip"],
            "trend": [day["off"] for day in stats["days"]],
            "month_hours": stats["month"]["hours"], "per_capita": stats["month"]["per_capita"],
            "month_leave_days": stats["month"]["leave_days"], "month_comp_hours": stats["month"]["comp_hours"],
            "rate": stats["rate"], "pending": int(pending.get(department, 0)),
        })
    departments.sort(key=lambda item: (-item["headcount"], item["label"]))
    return {"stats": company, "departments": departments, "pending": sum(int(count) for count in pending.values())}


def month_start_end(today: date):
    """今天所在月份的第一天和最后一天。"""
    first = today.replace(day=1)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return first, last
