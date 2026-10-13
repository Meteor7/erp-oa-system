"""请假 / 加班 / 调休页面的展示规则（不依赖 frappe，便于单元测试）。

页面要给员工看的是：还剩多少额度、这个月已经请了多少、每一天的状态；给审批人看的是：
批之前要知道的影响（余额、月度上限、同期缺勤）。这里只做计算，数据由 api/attendance_entry.py 取。
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from rayher_hr_payroll.attendance_requests import (
    ACTIVE,
    COMPLETED,
    REQUEST_COMP_TIME,
    REQUEST_LEAVE,
    REQUEST_OVERTIME,
    ZERO,
    expand_days,
    value,
    window_hours,
)
from rayher_hr_payroll.oa_document_types import REQUEST_TRAVEL
from rayher_hr_payroll import site_time

KIND_BY_TYPE = {REQUEST_LEAVE: "leave", REQUEST_OVERTIME: "overtime", REQUEST_COMP_TIME: "comp"}
HOURS_PER_DAY = Decimal("8")
TEAM_WINDOW_DAYS = 14
WEEKDAYS = "一二三四五六日"


def period_bounds(period, today=None):
    """"2026-10" -> (2026, 10, 该月第一天, 该月最后一天)；空或写错时用今天所在的月。"""
    today = today or site_time.today()
    text = str(period or "").strip()
    year, month = today.year, today.month
    if len(text) >= 7 and text[:4].isdigit() and text[5:7].isdigit() and 1 <= int(text[5:7]) <= 12:
        year, month = int(text[:4]), int(text[5:7])
    return year, month, date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _num(hours):
    number = float(hours)
    return int(number) if number == int(number) else round(number, 2)


def is_pending(status):
    return status in ACTIVE and status not in COMPLETED


def entry_label(row):
    kind = KIND_BY_TYPE.get(value(row, "request_type"), "leave")
    if kind == "overtime":
        return "加班"
    if kind == "comp":
        return "调休"
    return value(row, "leave_type") or "请假"


def calendar_entries(rows, first, last):
    """日历上每一天的记录：[{date, kind, label, hours, pending, request}]，一张申请一天一条。"""
    entries = []
    for row in rows:
        if value(row, "workflow_status") not in ACTIVE:
            continue
        for day, hours in expand_days(row):
            if first <= day <= last and hours > 0:
                entries.append({
                    "date": day.isoformat(), "kind": KIND_BY_TYPE.get(value(row, "request_type"), "leave"),
                    "label": entry_label(row), "hours": _num(hours),
                    "pending": is_pending(value(row, "workflow_status")), "request": value(row, "name"),
                })
    return sorted(entries, key=lambda item: (item["date"], item["request"]))


def month_totals(rows, first, last):
    """本月我的考勤：请假按类型合计（含审批中），加班和调休按小时；事假审批中的部分单独列出，
    因为事假通过后才扣当月工时上限。"""
    leave_hours_by_type, overtime, comp, pending_cap = {}, ZERO, ZERO, ZERO
    for row in rows:
        status = value(row, "workflow_status")
        if status not in ACTIVE:
            continue
        hours = window_hours(row, first, last)
        kind = KIND_BY_TYPE.get(value(row, "request_type"))
        if kind == "overtime":
            overtime += hours
        elif kind == "comp":
            comp += hours
        else:
            label = value(row, "leave_type") or "请假"
            leave_hours_by_type[label] = leave_hours_by_type.get(label, ZERO) + hours
            if value(row, "leave_type") == "事假" and is_pending(status):
                pending_cap += hours
    return {
        "leave_hours": _num(sum(leave_hours_by_type.values(), ZERO)),
        "leave_days": _num(sum(leave_hours_by_type.values(), ZERO) / HOURS_PER_DAY),
        "leave_days_by_type": {label: _num(hours / HOURS_PER_DAY) for label, hours in leave_hours_by_type.items()},
        "overtime_hours": _num(overtime),
        "comp_hours": _num(comp),
        "pending_cap_hours": _num(pending_cap),
    }


def cap_by_month(row):
    """一张事假按月拆开的小时数：{(年, 月): 小时}。"""
    months = {}
    for day, hours in expand_days(row):
        months[(day.year, day.month)] = months.get((day.year, day.month), ZERO) + hours
    return months


def review_hints(row, *, annual=None, comp=None, year_leave_count=0, teammates_off=0):
    """审批人在通过之前要看到的影响：[{tone, text}]，tone 是 ok / warn / info。

    余额取的是现在的可用额度：申请在审批中就已经占用（年假、调休）或计入（加班）了，
    所以"审批前"的数 = 现在可用 + 这张申请的小时数，"审批后" = 现在可用。
    """
    if value(row, "request_type") == REQUEST_TRAVEL:
        # 出差没有额度和小时数：只提醒不扣年假和工时上限，以及同期部门有几个人请假或调休。
        return [{"tone": "info", "text": "出差不扣年假和工时上限"},
                {"tone": "warn", "text": f"同期 {teammates_off} 人请假或调休"} if teammates_off
                else {"tone": "ok", "text": "同期部门无人请假"}]
    kind = KIND_BY_TYPE.get(value(row, "request_type"), "leave")
    leave_type = value(row, "leave_type")
    hours = sum((hour for _day, hour in expand_days(row)), ZERO)
    hints = []
    if kind == "leave" and leave_type == "年假" and annual is not None:
        after = Decimal(str(annual.get("available_hours") or 0))
        hints.append({"tone": "ok" if after >= 0 else "warn",
                      "text": f"年假够：{_num(after + hours)}h → {_num(after)}h" if after >= 0 else f"年假不够：还差 {_num(-after)}h"})
    elif kind == "leave" and leave_type == "事假":
        if year_leave_count:
            hints.append({"tone": "warn" if year_leave_count >= 3 else "info", "text": f"今年第 {year_leave_count} 次事假"})
        for (year, month), month_hours in sorted(cap_by_month(row).items()):
            hints.append({"tone": "info", "text": f"通过后 {month} 月工时上限 −{_num(month_hours)}h"})
    elif kind == "leave":
        hints.append({"tone": "info", "text": "不扣年假和工时上限"})
    elif kind == "comp" and comp is not None:
        after = Decimal(str(comp.get("available_hours") or 0))
        hints.append({"tone": "ok" if after >= 0 else "warn",
                      "text": f"调休余额 {_num(after + hours)}h → {_num(after)}h" if after >= 0 else f"调休不够：还差 {_num(-after)}h"})
    elif kind == "overtime":
        hints.append({"tone": "info", "text": f"提交时已计入调休额度 +{_num(hours)}h，驳回或撤回后冲回"})
    if kind != "overtime":
        hints.append({"tone": "warn", "text": f"同期 {teammates_off} 人请假或调休"} if teammates_off
                     else {"tone": "ok", "text": "同期部门无人请假"})
    return hints


def impact_text(row, *, annual=None, comp=None):
    """详情页"通过后的影响"那一格：一句话。"""
    if value(row, "request_type") == REQUEST_TRAVEL:
        return "出差期间不算请假，不扣年假和工时上限；通过后可以关联报销、付款"
    kind = KIND_BY_TYPE.get(value(row, "request_type"), "leave")
    leave_type = value(row, "leave_type")
    hours = sum((hour for _day, hour in expand_days(row)), ZERO)
    if kind == "leave" and leave_type == "事假":
        parts = [f"{month} 月工时上限 −{_num(month_hours)}h" for (_year, month), month_hours in sorted(cap_by_month(row).items())]
        return "，".join(parts) or "不扣年假和工时上限"
    if kind == "leave" and leave_type == "年假" and annual is not None:
        after = Decimal(str(annual.get("available_hours") or 0))
        return f"年假余额 {_num(after + hours)}h → {_num(after)}h"
    if kind == "comp" and comp is not None:
        after = Decimal(str(comp.get("available_hours") or 0))
        return f"调休余额 {_num(after + hours)}h → {_num(after)}h"
    if kind == "overtime":
        return f"调休额度 +{_num(hours)}h"
    return "不扣年假和工时上限"


def team_absence(first, work_dates, employees, rows, days=TEAM_WINDOW_DAYS):
    """一个部门未来两周谁不在（只给名字和日期，不给类型和事由）。

    work_dates：这两周里的工作日集合（其余是休息日）；employees：部门在职员工 [{name, employee_name}]；
    rows：这些员工审批中或已通过的请假、调休申请。
    """
    names = {value(employee, "name"): value(employee, "employee_name") or value(employee, "name") for employee in employees}
    window = [first + timedelta(days=offset) for offset in range(days)]
    by_day = {day: {"approved": {}, "pending": {}} for day in window}
    for row in rows:
        status = value(row, "workflow_status")
        if status not in ACTIVE or value(row, "request_type") == REQUEST_OVERTIME:
            continue
        who = names.get(value(row, "employee")) or value(row, "employee_name") or value(row, "employee")
        for day, hours in expand_days(row):
            if day in by_day and hours > 0:
                bucket = "pending" if is_pending(status) else "approved"
                by_day[day][bucket][value(row, "employee")] = who
    result = []
    for day in window:
        approved, pending = by_day[day]["approved"], by_day[day]["pending"]
        # 同一个人同一天既有已通过又有审批中的，只算已通过。
        pending = {key: name for key, name in pending.items() if key not in approved}
        result.append({
            "date": day.isoformat(), "label": f"{day.month}/{day.day}", "weekday": WEEKDAYS[day.weekday()],
            "off_day": day not in work_dates,
            "approved": sorted(approved.values()), "pending": sorted(pending.values()),
        })
    crowded = [item for item in result if not item["off_day"] and len(item["approved"]) + len(item["pending"]) >= 2]
    note = ""
    if crowded:
        first_day, last_day = crowded[0], crowded[-1]
        who = sorted({name for item in crowded for name in item["approved"] + item["pending"]})
        span = first_day["label"] if first_day is last_day else f"{first_day['label']}–{last_day['label']}"
        note = f"{span} 会有 2 人以上同时不在（{'、'.join(who)}）。"
    return {"headcount": len(names), "days": result, "note": note}
