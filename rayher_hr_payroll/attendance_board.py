"""考勤中心图表和团队日历的统计（不依赖 frappe，便于单元测试）。

三种身份看到的东西不一样，范围由 api/attendance_board_entry.py 按身份定好以后才调用这里：
- 员工只看自己：额度以外的"我今年请假构成""近 6 个月""未来 14 天我的安排"（build_personal）；
- 部门主管看自己的部门：每个人 14 天的日历（build_members）和部门的汇总数字（build_stats）；
- 人事和管理层先看各部门的汇总数字，不带人名（summarize_departments），点进某个部门才取到人名。
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


def build_stats(employee_ids, rows, *, first, work_dates, month_first, month_last, count=WINDOW_DAYS):
    """这批人的汇总数字（只有人数和小时，没有人名）。

    rows：这些人的申请（统计时只取已通过的）。返回：
    today {off, trip, in, rest_day}：今天请假或调休 / 出差 / 在岗的人数；
    month {hours, per_capita, by_kind}：本月请假和调休的小时（出差、加班不算）及按类型的小时；
    rate：未来 count 天工作日的出勤率（请假和调休的小时占应出勤小时的比例）；
    days：每天 {off, by_kind}：当天各类型的人数（off = 请假和调休的人数）。
    """
    ids = set(employee_ids)
    headcount = len(ids)
    dates = [first + timedelta(days=offset) for offset in range(count)]
    index = {day: position for position, day in enumerate(dates)}
    per_day = [{} for _ in dates]
    month_hours = {kind: ZERO for kind in ABSENCE_KINDS}
    absent = {}
    for row in rows:
        employee = value(row, "employee")
        if value(row, "workflow_status") not in COMPLETED or employee not in ids:
            continue
        kind = kind_of(row)
        if not kind:
            continue
        for day, hours in days_of(row, work_dates):
            if day in index:
                per_day[index[day]].setdefault(kind, set()).add(employee)
                if kind in ABSENCE_KINDS and day in work_dates:
                    absent[(employee, day)] = min(DAY_HOURS, absent.get((employee, day), ZERO) + hours)
            if kind in ABSENCE_KINDS and month_first <= day <= month_last:
                month_hours[kind] += hours
    days = window_days(first, work_dates, count)
    for position, entry in enumerate(days):
        found = per_day[position]
        entry["off"] = len(set().union(*(found.get(kind, set()) for kind in ABSENCE_KINDS)))
        entry["by_kind"] = {kind: len(found.get(kind, ())) for kind in ALL_KINDS}
    gone = set().union(*(per_day[0].get(kind, set()) for kind in ABSENCE_KINDS))
    trip = per_day[0].get("trip", set()) - gone
    work_days = sum(1 for day in dates if day in work_dates)
    capacity = DAY_HOURS * headcount * work_days
    rate = 1.0 if not capacity else round(float(1 - sum(absent.values(), ZERO) / capacity), 4)
    total = sum(month_hours.values(), ZERO)
    return {
        "headcount": headcount,
        "today": {"off": len(gone), "trip": len(trip), "in": max(0, headcount - len(gone) - len(trip)), "rest_day": first not in work_dates},
        "month": {
            "hours": _num(total), "per_capita": round(float(total) / headcount, 1) if headcount else 0,
            "by_kind": {kind: _num(hours) for kind, hours in month_hours.items()},
        },
        "rate": rate,
        "days": days,
    }


def today_trips(employees, rows, *, first, work_dates):
    """build_stats 里“今天出差”的那些人，一人一条：已批准的出差、今天在出差期间且是工作日；今天已在请假 / 调休的人不算。

    和 build_stats 的 today.trip 同一个口径（人数一定相等），多给每个人的单号、地点和日期，让看板的数字能点进具体的出差申请。
    """
    known = {value(employee, "name"): employee for employee in employees}
    gone, trips = set(), {}
    for row in rows:
        employee = value(row, "employee")
        if value(row, "workflow_status") not in COMPLETED or employee not in known:
            continue
        kind = kind_of(row)
        if not kind or first not in {day for day, _hours in days_of(row, work_dates)}:
            continue
        if kind in ABSENCE_KINDS:
            gone.add(employee)
        elif kind == "trip":
            trips.setdefault(employee, []).append(row)
    result = []
    for employee, items in trips.items():
        if employee in gone:
            continue
        row = sorted(items, key=lambda item: (str(value(item, "travel_start_date") or ""), str(value(item, "name") or "")))[0]
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
        pending = value(row, "workflow_status") not in COMPLETED
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


def summarize_departments(employees, rows, pending, *, first, work_dates, month_first, month_last):
    """公司汇总：全公司的统计 + 每个部门一行（只有数字，没有人名）。

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
            "rate": stats["rate"], "pending": int(pending.get(department, 0)),
        })
    departments.sort(key=lambda item: (-item["headcount"], item["label"]))
    return {"stats": company, "departments": departments, "pending": sum(int(count) for count in pending.values())}


def month_start_end(today: date):
    """今天所在月份的第一天和最后一天。"""
    first = today.replace(day=1)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return first, last
