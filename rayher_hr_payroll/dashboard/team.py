"""看板：我的团队（部门主管 / 有下属的人）。

团队 = 汇报关系向下的在职员工（直接和间接下属，下属在哪个部门都算，决定 2026-10-12），和考勤中心、工时填报进度、
HR 概览共用 `team_scope` 这一个范围。团队页显示人名（日历、每个人的请假加班）；公司级看板（人事、副总、总经理）仍然只有汇总。

- 谁不在、未来 14 天的日历：复用考勤中心的团队明细（`attendance_board_entry._team_detail`），数字和日历对得上；
  “不在岗”只算请假和调休（口径见 attendance_board.today_away）；日历上也画出差，但出差不算不在岗，不进在岗人数和人少提醒。
- 本月请假 / 加班：复用 `overview_entry._attendance_rows`（已批准的，跨月申请按天拆），按 `attendance_board.leave_figures`
  算——和公司的“本月请假”、考勤中心首页同一个算法：请假按天，调休单独算。
- 卡片点进去是一南通工厂8行的明细（看板明细），每一行进那张申请（决定 2026-10-13）。
可见性只看“有没有在职直接下属”（`ctx.has_reports`），不看角色名。
"""
from __future__ import annotations

from datetime import date
from math import ceil

from rayher_hr_payroll import attendance_board as board
from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, calendar, drill, drill_row, drill_to, kpi, provider, stack, stack_row, target,
)

TEAM_HINT = "团队 = 汇报关系向下的在职员工（含你自己；直接和间接下属，下属在哪个部门都算），和考勤中心、工时填报进度是同一个范围。"
HOURS_PER_DAY = 8
MAX_ROWS = 8
LOW_STAFF_SHARE = 0.2     # 某个工作日不在岗的人数占团队 20% 以上、且至少 3 人，提醒一下
LOW_STAFF_MIN = 3
BAD_SHARE = 0.4
# 请假类型颜色：和考勤中心一致的低饱和色
KIND_COLORS = {"annual": "#78c3a2", "personal": "#8db4ee", "sick": "#f29d96", "comp": "#b8a6ee", "other": "#c3cad6"}
# 算“不在岗”的类型：请假、调休（决定 2026-10-13：出差不算不在岗，日历上照样画出来，但不进不在岗人数；加班也不算）
_AWAY = board.ABSENCE_KINDS


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


def _figures(ctx, year, month):
    """团队这个月的请假 / 调休 / 加班（口径见 attendance_board.leave_figures）。"""
    return ctx.memo(f"team.figures.{year}-{month}", lambda: board.leave_figures(_rows(ctx, year, month)))


def _period(ctx):
    return int(ctx.period[:4]), int(ctx.period[5:])


def _today_away(detail):
    return detail.get("today_away") or {"off": [], "trip": []}


# ---------------------------------------------------------------- 指标卡
@provider("team.headcount", "kpi", visible=team_visible, title="团队在职")
def team_headcount(ctx):
    staff = _staff(ctx)
    rd_types = _load_rd_types()
    rd = sum(1 for row in staff if row.get("rd_personnel_type") in rd_types)
    joined = sum(1 for row in staff if str(row.get("date_of_joining") or "")[:7] == ctx.period)
    sub = f"研发 {rd}" + (f" · 本月入职 {joined}" if joined else "")
    return kpi("team.headcount", "团队在职", len(staff), "人", sub, to=drill_to("team.headcount", ctx) if staff else None,
               hint=TEAM_HINT + "研发 = 研发类型是全时 / 非全时 / 辅助的人。点进去一人一行。")


@provider("drill.team.headcount", "drill", visible=team_visible, title="团队在职")
def drill_team_headcount(ctx):
    staff = sorted(_staff(ctx), key=lambda row: (str(row.get("date_of_joining") or ""), row.get("employee_name") or row.get("name") or ""))
    rd_types = _load_rd_types()
    rows = [drill_row([row.get("employee_name") or row.get("name"), row.get("rd_personnel_type") or "—", str(row.get("date_of_joining") or "")[:10] or "—"],
                      tone="info" if str(row.get("date_of_joining") or "")[:7] == ctx.period else "") for row in staff]
    rd = sum(1 for row in staff if row.get("rd_personnel_type") in rd_types)
    return drill("drill.team.headcount", "团队在职", [("姓名",), ("研发类型",), ("入职日",)], rows, summary=f"共 {len(staff)} 人，研发 {rd} 人",
                 note="浅色 = 所选月份入职。" + TEAM_HINT)


@provider("team.away", "kpi", visible=team_visible, title="今天不在岗")
def team_away(ctx):
    detail = _detail(ctx)
    away = _today_away(detail)
    gone, trip = away["off"], away["trip"]
    labels = [f"{item['employee_name']}（{board.KIND_LABELS[item['kind']]}）" for item in gone]
    if detail.get("stats", {}).get("today", {}).get("rest_day"):
        sub = "今天休息"
    elif gone or trip:
        sub = _names(labels, 2) + (f"{' · ' if labels else ''}另有出差 {len(trip)}" if trip else "")
    else:
        sub = "全员在岗"
    return kpi("team.away", "今天不在岗", len(gone), "人", sub, to=drill_to("team.away", ctx) if gone or trip else None,
               hint="团队里今天（工作日）有已批准的请假或调休的人，一人只算一次；出差不算不在岗，单独写在副标题里。"
                    "点进去一人一行，每一行进那张申请。" + TEAM_HINT)


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
    figures = _figures(ctx, *_period(ctx))
    headcount = len(_ids(ctx)) or 1
    sub = f"人均 {_n(figures['leave_days'] / headcount)} 天" + (f" · 另有调休 {_n(figures['comp_days'])} 天" if figures["comp_days"] else "")
    return kpi("team.leave", f"{_month_word(ctx)}请假", _n(figures["leave_days"]), "天", sub,
               to=drill_to("team.leave", ctx) if figures["leave_count"] or figures["comp_count"] else None,
               hint="团队已批准的请假天数（只算请假，调休单独算；出差、加班不算；跨月申请按天拆到各月；小时 ÷ 8），"
                    "和公司的“本月请假”、考勤中心首页同一个算法。点进去一南通工厂8行，每一行进那张申请。" + TEAM_HINT)


@provider("team.overtime", "kpi", visible=team_visible, title="本月加班")
def team_overtime(ctx):
    current = _figures(ctx, *_period(ctx))["overtime_hours"]
    previous = _figures(ctx, *_prev_period(ctx.period))["overtime_hours"]
    if previous:
        change = (current - previous) / previous * 100
        sub = f"{'▲' if change >= 0 else '▼'} {abs(change):.0f}% 较上月"
    else:
        sub = "上月没有加班" if current else "本月没有加班"
    return kpi("team.overtime", f"{_month_word(ctx)}加班", _n(current), "小时", sub, to=drill_to("team.overtime", ctx) if current else None,
               hint="团队已批准的加班小时数（跨月申请按天拆到各月）；提交后按 1:1 计入调休额度。点进去一南通工厂8行，每一行进那张申请。" + TEAM_HINT)


# ---------------------------------------------------------------- 明细：一张申请一行，每一行进申请详情
def _span(item):
    first, last = item.get("from_date") or "", item.get("to_date") or ""
    return first[5:10] if not last or last == first else f"{first[5:10]} ～ {last[5:10]}"


def _request_rows(items):
    return [drill_row([item["employee_name"], item.get("leave_type") or board.KIND_LABELS.get(board.kind_of(item), ""), _span(item),
                       f"{_n(item['hours'])} 小时", f"{_n(item['hours'] / HOURS_PER_DAY)} 天"],
                      target("attendance.detail", request=item["name"]) if item.get("name") else None)
            for item in sorted(items, key=lambda item: (item.get("from_date") or "", item["employee_name"], item.get("name") or ""))]


_REQUEST_COLUMNS = [("申请人",), ("类型",), ("日期",), ("这个月", "r"), ("折合", "r")]


@provider("drill.team.leave", "drill", visible=team_visible, title="团队本月请假")
def drill_team_leave(ctx):
    from rayher_hr_payroll.attendance_requests import REQUEST_COMP_TIME, REQUEST_LEAVE

    figures = _figures(ctx, *_period(ctx))
    leave = [item for item in figures["requests"] if item["request_type"] == REQUEST_LEAVE]
    comp = [item for item in figures["requests"] if item["request_type"] == REQUEST_COMP_TIME]
    rows = _request_rows(leave)
    if comp:
        rows += [{**row, "tone": "info"} for row in _request_rows(comp)]
    note = "已批准的请假，跨月申请只算落在这个月里的小时。"
    if comp:
        note += f"调休不是请假：浅色的 {len(comp)} 行是调休（合计 {_n(figures['comp_days'])} 天），不算在上面的合计里。"
    return drill("drill.team.leave", f"团队{_month_word(ctx)}请假", _REQUEST_COLUMNS, rows,
                 summary=f"请假 {len(leave)} 张，合计 {_n(figures['leave_days'])} 天", note=note + TEAM_HINT)


@provider("drill.team.overtime", "drill", visible=team_visible, title="团队本月加班")
def drill_team_overtime(ctx):
    from rayher_hr_payroll.attendance_requests import REQUEST_OVERTIME

    figures = _figures(ctx, *_period(ctx))
    items = [item for item in figures["requests"] if item["request_type"] == REQUEST_OVERTIME]
    return drill("drill.team.overtime", f"团队{_month_word(ctx)}加班", _REQUEST_COLUMNS, _request_rows(items),
                 summary=f"加班 {len(items)} 张，合计 {_n(figures['overtime_hours'])} 小时",
                 note="已批准的加班，跨月申请只算落在这个月里的小时。" + TEAM_HINT)


@provider("drill.team.away", "drill", visible=team_visible, title="团队今天不在岗")
def drill_team_away(ctx):
    away = _today_away(_detail(ctx))
    rows = [drill_row([item["employee_name"], board.KIND_LABELS[item["kind"]], item["request"]], target("attendance.detail", request=item["request"]))
            for item in away["off"]]
    rows += [drill_row([item["employee_name"], "出差（不算不在岗）", item["request"]], target("attendance.detail", request=item["request"]), tone="info")
             for item in away["trip"]]
    summary = f"不在岗 {len(away['off'])} 人" + (f"，另有出差 {len(away['trip'])} 人" if away["trip"] else "")
    return drill("drill.team.away", "团队今天不在岗", [("姓名",), ("类型",), ("单号",)], rows, summary=summary,
                 note="今天（工作日）有已批准的请假或调休的人，一人一行；出差的人浅色列在后面，不算不在岗。" + TEAM_HINT)


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
        hint="每行一个人，颜色是请假类型，虚线是还在审批的；最下面一行是当天在岗人数（请假、调休算不在岗；出差画在日历上，但不算不在岗；加班不算）。"
             "人少的日子标橙 / 红。" + TEAM_HINT)


# 请假类型的颜色类别（调休不是请假，不进这个比例）
_LEAVE_KINDS = tuple(kind for kind in board.ABSENCE_KINDS if kind != "comp")


@provider("block.team_leave_types", "block", visible=team_visible, title="本月请假类型")
def block_team_leave_types(ctx):
    figures = _figures(ctx, *_period(ctx))
    by_kind = {kind: hours for kind, hours in figures["by_kind"].items() if kind in _LEAVE_KINDS and hours}
    total = sum(by_kind.values())
    if not total:
        return None
    rows = [stack_row(board.KIND_LABELS[kind], f"{_n(hours / HOURS_PER_DAY)} 天", hours / total * 100, KIND_COLORS[kind])
            for kind, hours in sorted(by_kind.items(), key=lambda item: -item[1])]
    sub = "天" + (f" · 另有调休 {_n(figures['comp_days'])} 天" if figures["comp_days"] else "")
    return stack("block.team_leave_types", f"{_month_word(ctx)}请假类型", rows, sub=sub, more="明细", to=drill_to("team.leave", ctx),
                 hint="团队已批准的请假天数，按类型；加起来等于“本月请假”。调休不是请假，单独写在副标题里。" + TEAM_HINT)


def _people_hours(ctx):
    people = _figures(ctx, *_period(ctx))["by_employee"].values()
    return sorted(((person["name"], person) for person in people), key=lambda item: (-(item[1]["leave"] + item[1]["comp"] + item[1]["overtime"]), item[0]))


def _people_text(found):
    return f"请假 {_n(found['leave'])}" + (f" · 调休 {_n(found['comp'])}" if found["comp"] else "") + f" · 加班 {_n(found['overtime'])}"


@provider("block.team_people_hours", "block", visible=team_visible, title="每个人本月的请假和加班")
def block_team_people_hours(ctx):
    ranked = _people_hours(ctx)
    if not ranked:
        return None
    biggest = max(found["leave"] + found["comp"] + found["overtime"] for _name, found in ranked) or 1
    rows = [bar_row(name, _people_text(found), (found["leave"] + found["comp"] + found["overtime"]) / biggest * 100) for name, found in ranked[:MAX_ROWS]]
    more = f"只列最多的 {MAX_ROWS} 人" if len(ranked) > MAX_ROWS else ""
    return bars("block.team_people_hours", f"{_month_word(ctx)}每个人的请假和加班", rows, sub="小时 · 含人名" + (f" · {more}" if more else ""),
                more="每个人", to=drill_to("team.people", ctx),
                hint="团队已批准的请假、调休、加班小时（调休单独写，不算在请假里）；只有你和人事能看到人名。点进去列出每个人。" + TEAM_HINT)


@provider("drill.team.people", "drill", visible=team_visible, title="每个人本月的请假和加班")
def drill_team_people(ctx):
    ranked = _people_hours(ctx)
    rows = [drill_row([name, _n(found["leave"]), _n(found["comp"]), _n(found["overtime"])]) for name, found in ranked]
    figures = _figures(ctx, *_period(ctx))
    return drill("drill.team.people", f"{_month_word(ctx)}每个人的请假和加班", [("姓名",), ("请假（小时）", "r"), ("调休（小时）", "r"), ("加班（小时）", "r")], rows,
                 summary=f"{len(ranked)} 人；请假 {_n(figures['leave_hours'])} 小时，调休 {_n(figures['comp_hours'])} 小时，加班 {_n(figures['overtime_hours'])} 小时",
                 note="已批准的申请，跨月申请只算落在这个月里的小时。" + TEAM_HINT)
