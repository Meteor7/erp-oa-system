"""看板：我的团队（部门主管 / 有下属的人）。

团队 = 汇报关系向下的在职员工（直接和间接下属，下属在哪个部门都算，决定 2026-10-12），和考勤中心、工时填报进度、
HR 概览共用 `team_scope` 这一个范围。团队页显示人名（日历、每个人的请假加班）；公司级看板（人事、副总、总经理）仍然只有汇总。

- 谁不在、未来 14 天的日历：复用考勤中心的团队明细（`attendance_board_entry._team_detail`），数字和日历对得上；
- 本月请假 / 加班：复用 `overview_entry._attendance_rows`（已批准的，跨月申请按天拆）。
可见性只看“有没有在职直接下属”（`ctx.has_reports`），不看角色名。
"""
from __future__ import annotations

from datetime import date, timedelta
from math import ceil

from rayher_hr_payroll import attendance_board as board
from rayher_hr_payroll import attendance_requests as att
from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, calendar, kpi, provider, stack, stack_row, target,
)

TEAM_HINT = "团队 = 汇报关系向下的在职员工（含你自己；直接和间接下属，下属在哪个部门都算），和考勤中心、工时填报进度是同一个范围。"
HOURS_PER_DAY = 8
MAX_ROWS = 8
LOW_STAFF_SHARE = 0.2     # 某个工作日不在岗的人数占团队 20% 以上、且至少 3 人，提醒一下
LOW_STAFF_MIN = 3
BAD_SHARE = 0.4
# 请假类型颜色：和考勤中心一致的低饱和色
KIND_COLORS = {"annual": "#78c3a2", "personal": "#8db4ee", "sick": "#f29d96", "comp": "#b8a6ee", "other": "#c3cad6"}
_AWAY = (*board.ABSENCE_KINDS, "trip")      # 日历上算“不在岗”的类型：请假、调休、出差（加班不算）


# ---------------------------------------------------------------- 取数（单独成函数，测试里替换）
def _load_team_ids(ctx):
    from rayher_hr_payroll.team_scope import team_of_user

    return team_of_user(ctx.user)["names"]


def _load_team_detail(ctx):
    from rayher_hr_payroll.api import attendance_board_entry
    from rayher_hr_payroll.attendance_scope import resolve_scope

    return attendance_board_entry._team_detail(resolve_scope(), date.fromisoformat(ctx.today))


def _load_team_staff(ids):
    import frappe

    return frappe.get_all(
        "Employee", filters={"name": ["in", list(ids) or ["__none__"]], "status": "Active"},
        fields=["name", "employee_name", "rd_personnel_type", "date_of_joining"], limit_page_length=0,
    )


def _load_team_rows(year, month, ids):
    from rayher_hr_payroll.api import overview_entry

    return overview_entry._attendance_rows([(year, month)], None, list(ids))


def _load_rd_types():
    from rayher_hr_payroll.api.timesheet_entry import RD_TYPES

    return tuple(RD_TYPES)


# ---------------------------------------------------------------- 小工具
def team_visible(ctx):
    return bool(ctx.has_reports)


def _ids(ctx):
    return ctx.memo("team.ids", lambda: _load_team_ids(ctx))


def _detail(ctx):
    return ctx.memo("team.detail", lambda: _load_team_detail(ctx))


def _staff(ctx):
    return ctx.memo("team.staff", lambda: _load_team_staff(_ids(ctx)))


def _rows(ctx, year, month):
    return ctx.memo(f"team.rows.{year}-{month}", lambda: _load_team_rows(year, month, _ids(ctx)))


def _n(value):
    return f"{round(float(value or 0), 2):g}"


def _md(label):
    return str(label)


def _month_word(ctx):
    return "本月" if ctx.period == ctx.today[:7] else f"{int(ctx.period[5:])} 月"


def _prev_period(period):
    year, month = int(period[:4]), int(period[5:])
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _names(people, limit=3):
    shown = "、".join(people[:limit])
    return shown + ("等" if len(people) > limit else "")


def _cell(member, index):
    cells = member.get("cells") or []
    return cells[index] if index < len(cells) else None


def _away_on(detail, index, kinds=_AWAY):
    """第 index 天（0 = 今天）已批准、不在岗的人：[(姓名, 类型)]（审批中的不算）。"""
    people = []
    for member in detail.get("members") or []:
        cell = _cell(member, index)
        if cell and cell.get("kind") in kinds and not cell.get("pending"):
            people.append((member.get("name") or "", cell["kind"]))
    return people


def _hours(rows, request_type):
    return sum(float(row.get("duration_hours") or 0) for row in rows if row.get("request_type") == request_type)


# ---------------------------------------------------------------- 指标卡
@provider("team.headcount", "kpi", visible=team_visible, title="团队在职")
def team_headcount(ctx):
    staff = _staff(ctx)
    rd_types = _load_rd_types()
    rd = sum(1 for row in staff if row.get("rd_personnel_type") in rd_types)
    joined = sum(1 for row in staff if str(row.get("date_of_joining") or "")[:7] == ctx.period)
    sub = f"研发 {rd}" + (f" · 本月入职 {joined}" if joined else "")
    return kpi("team.headcount", "团队在职", len(staff), "人", sub, hint=TEAM_HINT + "研发 = 研发类型是全时 / 非全时 / 辅助的人。")


@provider("team.away", "kpi", visible=team_visible, title="今天不在岗")
def team_away(ctx):
    detail = _detail(ctx)
    gone = _away_on(detail, 0, (*board.ABSENCE_KINDS,))
    trip = _away_on(detail, 0, ("trip",))
    labels = [f"{name}（{board.KIND_LABELS[kind]}）" for name, kind in gone]
    if detail.get("stats", {}).get("today", {}).get("rest_day"):
        sub = "今天休息"
    elif gone or trip:
        sub = _names(labels, 2) + (f"{' · ' if labels else ''}出差 {len(trip)}" if trip else "")
    else:
        sub = "全员在岗"
    return kpi("team.away", "今天不在岗", len(gone), "人", sub, to=target("attendance.home"),
               hint="团队里今天有已批准的请假或调休的人；出差单独在右边显示，不算请假。" + TEAM_HINT)


@provider("team.away2w", "kpi", visible=team_visible, title="两周内不在岗")
def team_away2w(ctx):
    detail = _detail(ctx)
    days = (detail.get("stats") or {}).get("days") or []
    firsts = {}
    for member in detail.get("members") or []:
        for index, cell in enumerate(member.get("cells") or []):
            if cell and cell.get("kind") in board.ABSENCE_KINDS and not cell.get("pending") and index < len(days):
                firsts.setdefault(member.get("name"), days[index]["label"])
                break
    ordered = sorted(firsts.values(), key=lambda label: tuple(int(part) for part in label.split("/")))
    shown = " · ".join(ordered[:3]) + (" …" if len(ordered) > 3 else "")
    return kpi("team.away2w", "两周内不在岗", len(firsts), "人", shown or "两周内没有人请假或调休",
               to=target("attendance.home"),
               hint=f"团队从今天起 {board.WINDOW_DAYS} 天内有已批准的请假 / 调休的人数，日期是每个人最早的一天。" + TEAM_HINT)


@provider("team.leave", "kpi", visible=team_visible, title="本月请假")
def team_leave(ctx):
    year, month = int(ctx.period[:4]), int(ctx.period[5:])
    rows = _rows(ctx, year, month)
    hours = _hours(rows, att.REQUEST_LEAVE) + _hours(rows, att.REQUEST_COMP_TIME)
    headcount = len(_ids(ctx)) or 1
    return kpi("team.leave", f"{_month_word(ctx)}请假", _n(hours), "小时", f"人均 {_n(hours / headcount)} 小时",
               to=target("attendance.home"),
               hint="团队已批准的请假和调休小时（出差、加班不算；跨月申请按天拆到各月）。" + TEAM_HINT)


@provider("team.overtime", "kpi", visible=team_visible, title="本月加班")
def team_overtime(ctx):
    year, month = int(ctx.period[:4]), int(ctx.period[5:])
    current = _hours(_rows(ctx, year, month), att.REQUEST_OVERTIME)
    previous = _hours(_rows(ctx, *_prev_period(ctx.period)), att.REQUEST_OVERTIME)
    if previous:
        change = (current - previous) / previous * 100
        sub = f"{'▲' if change >= 0 else '▼'} {abs(change):.0f}% 较上月"
    else:
        sub = "上月没有加班" if current else "本月没有加班"
    return kpi("team.overtime", f"{_month_word(ctx)}加班", _n(current), "小时", sub, to=target("attendance.home"),
               hint="团队已批准的加班小时数（跨月申请按天拆到各月）；提交后按 1:1 计入调休额度。" + TEAM_HINT)


# ---------------------------------------------------------------- 提醒
@provider("alert.team_low_staff", "alert", visible=team_visible)
def alert_team_low_staff(ctx):
    detail = _detail(ctx)
    days = (detail.get("stats") or {}).get("days") or []
    headcount = int(detail.get("headcount") or 0)
    if not headcount:
        return None
    threshold = max(LOW_STAFF_MIN, ceil(headcount * LOW_STAFF_SHARE))
    worst = None
    for index, day in enumerate(days):
        if day.get("off_day"):
            continue
        away = _away_on(detail, index)
        if len(away) >= threshold and (worst is None or len(away) > len(worst[2])):
            worst = (index, day, away)
    if worst is None:
        return None
    _, day, away = worst
    share = len(away) / headcount
    return alert("alert.team_low_staff", "bad" if share >= BAD_SHARE else "warn",
                 f"{_md(day['label'])} 有 {len(away)} 人不在岗，占团队 {round(share * 100)}%",
                 _names([name for name, _kind in away], 4), "考勤中心", target("attendance.home"))


# ---------------------------------------------------------------- 图表块
@provider("block.team_calendar", "block", visible=team_visible, title="团队日历 · 谁哪天不在")
def block_team_calendar(ctx):
    detail = _detail(ctx)
    members = detail.get("members") or []
    days = (detail.get("stats") or {}).get("days") or []
    if not members or not days:
        return None
    headcount = len(members)
    people = [{"name": member.get("name") or "", "cells": [
        ({"kind": cell["kind"], "pending": bool(cell.get("pending"))} if cell else None) for cell in (member.get("cells") or [])]}
        for member in members]
    totals = []
    for index, day in enumerate(days):
        away = 0 if day.get("off_day") else len(_away_on(detail, index))
        totals.append({"off": away, "present": None if day.get("off_day") else headcount - away})
    return calendar(
        "block.team_calendar", "团队日历 · 谁哪天不在",
        [{key: day.get(key) for key in ("date", "label", "day", "weekday", "off_day")} for day in days], people, totals,
        sub="未来 14 天 · 含人名，只有你和人事能看到", more="考勤中心", to=target("attendance.home"),
        hint="每行一个人，颜色是请假类型，虚线是还在审批的；最下面一行是当天在岗人数（请假、调休、出差算不在岗，加班不算）。人少的日子标橙 / 红。" + TEAM_HINT)


@provider("block.team_leave_types", "block", visible=team_visible, title="本月请假类型")
def block_team_leave_types(ctx):
    year, month = int(ctx.period[:4]), int(ctx.period[5:])
    by_kind = {}
    for row in _rows(ctx, year, month):
        kind = board.kind_of(row)
        if kind in board.ABSENCE_KINDS:
            by_kind[kind] = by_kind.get(kind, 0) + float(row.get("duration_hours") or 0)
    total = sum(by_kind.values())
    if not total:
        return None
    rows = [stack_row(board.KIND_LABELS[kind], f"{_n(hours)} 小时", hours / total * 100, KIND_COLORS[kind])
            for kind, hours in sorted(by_kind.items(), key=lambda item: -item[1])]
    return stack("block.team_leave_types", f"{_month_word(ctx)}请假类型", rows, sub="小时", more="考勤中心", to=target("attendance.home"),
                 hint="团队已批准的请假和调休小时，按类型。" + TEAM_HINT)


@provider("block.team_people_hours", "block", visible=team_visible, title="每个人本月的请假和加班")
def block_team_people_hours(ctx):
    year, month = int(ctx.period[:4]), int(ctx.period[5:])
    people = {}
    for row in _rows(ctx, year, month):
        name = row.get("employee_name") or row.get("employee") or ""
        found = people.setdefault(name, {"leave": 0.0, "overtime": 0.0})
        hours = float(row.get("duration_hours") or 0)
        if row.get("request_type") == att.REQUEST_OVERTIME:
            found["overtime"] += hours
        else:
            found["leave"] += hours
    if not people:
        return None
    ranked = sorted(people.items(), key=lambda item: (-(item[1]["leave"] + item[1]["overtime"]), item[0]))
    biggest = max(item[1]["leave"] + item[1]["overtime"] for item in ranked) or 1
    rows = [bar_row(name, f"请假 {_n(found['leave'])} · 加班 {_n(found['overtime'])}",
                    (found["leave"] + found["overtime"]) / biggest * 100) for name, found in ranked[:MAX_ROWS]]
    more = f"只列最多的 {MAX_ROWS} 人" if len(ranked) > MAX_ROWS else ""
    return bars("block.team_people_hours", f"{_month_word(ctx)}每个人的请假和加班", rows, sub="小时 · 含人名" + (f" · {more}" if more else ""),
                more="考勤中心", to=target("attendance.home"),
                hint="团队已批准的请假、调休和加班小时；只有你和人事能看到人名。" + TEAM_HINT)
