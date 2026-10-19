"""看板：公司考勤（人事 / 演示员工113 / 总经理，放在“人事”页签的“考勤”一段里）。

看板上只有人数、天数和比例；要看是谁，点卡片直接进考勤中心首页对应的那一块（决定 2026-10-14，人事、演示员工113、总经理在首页就看到人名）：
“本月请假 / 本月加班”落在「N 月」概览、已经选好类型和月份，“出差中”落在「谁不在」、选好出差，出勤率和未来 14 天进考勤中心首页。
原来按部门列天数的明细（drill.att.leave / overtime / trip）留着给旧链接用，卡片不再指向它们。
数字复用考勤中心的公司汇总（`attendance_board_entry._company_summary`），和考勤中心首页对得上；
本月请假 / 加班 / 部门排行用 `overview_entry.month_leave`（按所选期间；和考勤中心首页的“本月请假”是同一个算法
`attendance_board.leave_figures`：只算在职员工、只算请假，调休单独算，部门按员工档案）。
考勤待审批不含前台待办理的出差（已经批准，算出差中）。
"""
from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from rayher_hr_payroll import attendance_requests as att
from rayher_hr_payroll.dashboard import people
from rayher_hr_payroll.oa_document_types import REQUEST_TRAVEL
from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, col_row, cols, drill, drill_row, drill_to, kpi, provider, target,
)

STUCK_DAYS = 3
# 考勤中心里的申请：请假、加班、调休，加上出差（和考勤中心的“待我审批”“全部”同一批）。
CENTER_TYPES = (*att.ATTENDANCE_TYPES, REQUEST_TRAVEL)
MAX_ROWS = 8
HOURS_PER_DAY = 8
HINT = "看板上只有人数和天数；点进考勤中心就能看到是谁（人事、演示员工113、总经理看全公司，可以按部门筛）。"


# ---------------------------------------------------------------- 取数（单独成函数，测试里替换）
def _load_summary(ctx):
    from rayher_hr_payroll.api import attendance_board_entry

    return attendance_board_entry._company_summary(date.fromisoformat(ctx.today))


def _load_today_trips(ctx):
    """今天出差的人，一人一条（口径同公司汇总里的“出差中”）。"""
    from rayher_hr_payroll.api import attendance_board_entry

    return attendance_board_entry.today_trips(date.fromisoformat(ctx.today))


def waiting_since(row):
    """轮到现在这一步的时间：最近一次有人处理的时间，没有就是最近一次提交，再没有就是创建时间。
    和考勤中心列表的“已等”（attendanceView.waitingSince）同一个规则。"""
    from rayher_hr_payroll.api import oa_entry

    raw = row.get("operation_log") or "[]"
    try:
        events = json.loads(raw) if isinstance(raw, str) else list(raw)
    except (TypeError, ValueError):
        events = []
    return row.get("last_acted") or oa_entry._last_submitted_on(events if isinstance(events, list) else []) or row.get("creation")


def _waited_days(row, today):
    since = str(waiting_since(row) or "")[:10]
    try:
        return max(0, (date.fromisoformat(today) - date.fromisoformat(since)).days)
    except ValueError:
        return 0


def _load_waiting_rows(ctx):
    """还在审批的请假 / 加班 / 调休 / 出差，一演示员工128行，带已等天数（日历天）。出差的起止日期取出发、返回日期。
    还在审批 = 待审批；出差到了前台待办理已经批准了，算“出差中”，不算在这里（attendance_board_entry.pending_sql）。"""
    import frappe
    from rayher_hr_payroll.api.attendance_board_entry import pending_sql

    rows = frappe.db.sql(
        "SELECT r.name, r.request_type, r.employee_name, r.department, COALESCE(r.from_date, r.travel_start_date) AS from_date, "
        "COALESCE(r.to_date, r.travel_end_date) AS to_date, r.duration_hours, r.current_step_label, r.creation, r.operation_log, "
        "(SELECT MAX(s.acted_on) FROM `tabOA Approval Step` s WHERE s.parent = r.name AND s.parenttype = 'OA Approval Request') AS last_acted "
        "FROM `tabOA Approval Request` r WHERE r.request_type IN %(types)s AND " + pending_sql("r"),
        {"types": tuple(CENTER_TYPES)}, as_dict=True)
    for row in rows:
        row["waited"] = _waited_days(row, ctx.today)
        row.pop("operation_log", None)
    return sorted(rows, key=lambda row: (-row["waited"], row.get("name") or ""))


def _load_waiting(ctx):
    """还在审批的请假 / 加班 / 调休 / 出差：{total, old}；old = 已等超过 3 天的张数（和明细同一份数据）。"""
    rows = ctx.memo("att.waiting_rows", lambda: _load_waiting_rows(ctx))
    return {"total": len(rows), "old": sum(1 for row in rows if int(row.get("waited") or 0) > STUCK_DAYS)}


def _summary(ctx):
    return ctx.memo("att.summary", lambda: _load_summary(ctx))


def _waiting(ctx):
    return ctx.memo("att.waiting", lambda: _load_waiting(ctx))


def _n(value):
    return f"{round(float(value or 0), 2):g}"


def _d1(days):
    """天数保留一位小数（四舍五入，和考勤中心「N 月」概览的 attendanceHome.daysText 同一个写法，两边显示的数字一样）。"""
    return f"{Decimal(str(float(days or 0))).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):f}".rstrip("0").rstrip(".") or "0"


def _month_word(ctx):
    return "本月" if ctx.period == ctx.today[:7] else f"{int(ctx.period[5:])} 月"


def _visible(ctx):
    return people._hr_view(ctx)


# ---------------------------------------------------------------- 指标卡
@provider("att.trip", "kpi", visible=_visible, title="出差中")
def att_trip(ctx):
    today = _summary(ctx)["stats"]["today"]
    return kpi("att.trip", "出差中", today["trip"], "人", "不算请假，不进出勤率", to=(target("attendance.away", tile="trip") if people.company_attendance(ctx) else drill_to("att.trip", ctx)) if today["trip"] else None,
               hint="今天在已批准的出差申请期间的人数（已在请假的不重复算；周末和节假日不算）。"
                    "点进去是考勤中心的「谁不在 · 今天」，已经选好出差，一人一行，每一行进出差申请。")


@provider("att.pending", "kpi", visible=_visible, title="考勤待审批")
def att_pending(ctx):
    waiting = _waiting(ctx)
    return kpi("att.pending", "考勤待审批", waiting["total"], "张", f"其中 {waiting['old']} 张超过 {STUCK_DAYS} 天" if waiting["old"] else "没有等得久的",
               "hot" if waiting["old"] else "", to=drill_to("att.pending", ctx) if waiting["total"] else None,
               hint=f"请假、加班、调休、出差里还在审批的申请张数（所有审批人手上的，不只是你的）；前台待办理的出差已经批准，算“出差中”，不算这里。"
                    f"“超过 {STUCK_DAYS} 天”按日历天，从最近一次有人处理（没有就从提交）算起，和考勤中心列表的“已等”一样。"
                    "点进去一演示员工128行，每一行进申请详情。")


LEAVE_HINT = ("在职员工已批准的请假天数（只算请假，调休不是请假、单独算；跨月申请按天拆到各月；小时 ÷ 8，保留一位小数），"
              "和考勤中心首页「N 月」概览的“请假”是同一个算法。点进去就是那一块，已经选好请假和这个月份，按部门、按假别都能点开看是谁；"
              "调休在旁边一格，点一下就是。")


def month_target(ctx, metric):
    """本月请假 / 加班点进去：考勤中心首页的「N 月」概览，选好类型和看板所选的月份。
    只有 HR 角色、没有人事经理 / 演示员工113 / 总经理岗位的人在考勤中心首页只看到自己，仍然进原来按部门列的明细。"""
    if people.company_attendance(ctx):
        return target("attendance.month", metric=metric, month=ctx.period)
    if metric == "leave":
        return drill_to("att.leave", ctx)
    return drill_to("att.overtime", ctx)


@provider("att.leave", "kpi", visible=_visible, title="本月请假")
def att_leave(ctx):
    stats = people._leave_stats(ctx)["totals"]
    return kpi("att.leave", f"{_month_word(ctx)}请假", _d1(stats["leave_days"]), "天",
               f"另有调休 {_d1(stats['comp_days'])} 天", to=month_target(ctx, "leave") if stats["leave_days"] or stats.get("comp_days") else None,
               hint=LEAVE_HINT + HINT)


@provider("att.overtime", "kpi", visible=_visible, title="本月加班")
def att_overtime(ctx):
    stats = people._leave_stats(ctx)["totals"]
    return kpi("att.overtime", f"{_month_word(ctx)}加班", _d1(stats["overtime_days"]), "天", "提交后按 1:1 计入调休额度",
               to=month_target(ctx, "ot") if stats["overtime_days"] else None,
               hint="在职员工已批准的加班天数（小时 ÷ 8，保留一位小数；跨月申请按天拆到各月）。"
                    "点进去是考勤中心「N 月」概览的“加班”，按部门、按周都能点开看是谁，合计等于这里。")


@provider("att.rate", "kpi", visible=_visible, title="出勤率")
def att_rate(ctx):
    stats = _summary(ctx)["stats"]
    rate = round(float(stats.get("rate") or 0) * 100, 1)
    work_days = sum(1 for day in stats["days"] if not day.get("off_day"))
    return kpi("att.rate", "出勤率", f"{rate:g}", "%", f"未来 14 天 · {work_days} 个工作日", "ok" if rate >= 95 else "warn",
               to=target("attendance.home"),
               hint="请假和调休的小时占应出勤小时（人数 × 8 × 工作日数）的比例；出差和加班不算。" + HINT)


# ---------------------------------------------------------------- 提醒
@provider("alert.att_pending", "alert", visible=_visible)
def alert_att_pending(ctx):
    waiting = _waiting(ctx)
    if not waiting["old"]:
        return None
    return alert("alert.att_pending", "warn", f"{waiting['old']} 张考勤申请等了超过 {STUCK_DAYS} 天", f"共 {waiting['total']} 张在审批中",
                 "查看明细", drill_to("att.pending_old", ctx))


# ---------------------------------------------------------------- 明细：和指标卡同一份数据，点进去逐条 / 逐部门列出来
def _waiting_drill(ctx, key, title, only_old):
    rows = ctx.memo("att.waiting_rows", lambda: _load_waiting_rows(ctx))
    if only_old:
        rows = [row for row in rows if int(row.get("waited") or 0) > STUCK_DAYS]
    out = [drill_row([row["request_type"], row.get("employee_name") or "—", people._dept_label(row.get("department")) or "—",
                      f"{str(row.get('from_date') or '')[5:10]} ～ {str(row.get('to_date') or row.get('from_date') or '')[5:10]}",
                      row.get("current_step_label") or "—", f"{int(row.get('waited') or 0)} 天"],
                     target("attendance.detail", request=row["name"]), tone="bad" if int(row.get("waited") or 0) > STUCK_DAYS else "")
           for row in rows]
    summary = f"共 {len(rows)} 张" + (f"，都等了超过 {STUCK_DAYS} 天" if only_old else "")
    return drill(key, title, [("类型",), ("申请人",), ("部门",), ("日期",), ("现在在",), ("已等", "r")], out, summary=summary,
                 note=f"“已等”按日历天，从最近一次有人处理（没有就从提交）算起，和考勤中心列表一样；红色 = 超过 {STUCK_DAYS} 天。"
                      "前台待办理的出差已经批准，不在这里。")


@provider("drill.att.pending", "drill", visible=_visible, title="考勤待审批")
def drill_att_pending(ctx):
    return _waiting_drill(ctx, "drill.att.pending", "考勤待审批", only_old=False)


@provider("drill.att.pending_old", "drill", visible=_visible, title="考勤申请等得久")
def drill_att_pending_old(ctx):
    return _waiting_drill(ctx, "drill.att.pending_old", f"等了超过 {STUCK_DAYS} 天的考勤申请", only_old=True)


def _department_drill(ctx, key, title, field, noun, note):
    """按部门列出本月请假 / 加班：和卡片同一份数（people._leave_stats），合计等于卡片上的数字。
    2026-10-14 起卡片不再指向这里（直接进考勤中心「N 月」概览），留着给旧链接；每一行进同一块概览（选好类型和月份）。"""
    stats = people._leave_stats(ctx)
    ranked = sorted((row for row in stats.get("by_department") or [] if float(row.get(field) or 0) > 0),
                    key=lambda row: (-float(row.get(field) or 0), row.get("label") or ""))
    names = people.company_attendance(ctx)
    current = ctx.period == ctx.today[:7]
    go = (target("attendance.month", metric="leave" if field == "leave" else "ot", month=ctx.period) if names
          else target("attendance.home") if current else None)
    rows = [drill_row([row.get("label") or "未分配部门", f"{int(row.get(f'{field}_count') or 0)} 张", f"{_n(row.get(field))} 天"], go)
            for row in ranked]
    total_count = sum(int(row.get(f"{field}_count") or 0) for row in ranked)
    total_days = float((stats.get("totals") or {}).get(f"{field}_days") or 0)
    return drill(key, title, [("部门",), (noun, "r"), ("天数", "r")], rows, summary=f"共 {total_count} 张，合计 {_n(total_days)} 天",
                 note=note + ("点一行进考勤中心的「N 月」概览，按部门点开就能看到是谁。" if names else ""))


@provider("drill.att.leave", "drill", visible=_visible, title="本月请假")
def drill_att_leave(ctx):
    comp = float((people._leave_stats(ctx).get("totals") or {}).get("comp_days") or 0)
    return _department_drill(ctx, "drill.att.leave", f"{_month_word(ctx)}请假 · 按部门", "leave", "请假单",
                             "在职员工已批准的请假（不含调休" + (f"，调休另有 {_n(comp)} 天" if comp else "") + "），部门按员工档案；"
                             "跨月申请只算落在这个月里的天数。" + HINT)


@provider("drill.att.overtime", "drill", visible=_visible, title="本月加班")
def drill_att_overtime(ctx):
    return _department_drill(ctx, "drill.att.overtime", f"{_month_word(ctx)}加班 · 按部门", "overtime", "加班单",
                             "在职员工已批准的加班，部门按员工档案；跨月申请只算落在这个月里的天数。" + HINT)


def _trip_date(row):
    start, end = str(row.get("start") or "")[5:10], str(row.get("end") or "")[5:10]
    return f"{start} ～ {end}" if end and end != start else start


@provider("drill.att.trip", "drill", visible=_visible, title="出差中")
def drill_att_trip(ctx):
    """今天出差的人，一人一行，点进去就是那张出差申请；条数和指标卡“出差中”一样。"""
    trips = _load_today_trips(ctx)
    rows = [drill_row([item["employee_name"], people._dept_label(item["department"]) or "—", item["destination"] or "—", _trip_date(item), item["name"]],
                      target("attendance.detail", request=item["name"])) for item in trips]
    return drill("drill.att.trip", "今天出差的人", [("出差人",), ("部门",), ("出差地点",), ("日期",), ("单号",)], rows, summary=f"共 {len(trips)} 人",
                 note="今天在已批准的出差申请期间的人（已在请假的不重复算；周末和节假日不算）。每一行进出差申请详情。")


# ---------------------------------------------------------------- 图表块
@provider("block.att_depts", "block", visible=_visible, title="各部门请假")
def block_att_depts(ctx):
    rows = [row for row in people._leave_stats(ctx)["by_department"] if row["leave"] > 0]
    if not rows:
        return None
    ordered = sorted(rows, key=lambda row: (-row["leave"], row["label"]))
    ranked = ordered[:MAX_ROWS]
    biggest = ranked[0]["leave"] or 1
    sub = "天 · 按部门" + (f" · 只列最多的 {MAX_ROWS} 个部门" if len(ordered) > MAX_ROWS else "")
    return bars("block.att_depts", f"各部门{_month_word(ctx)}请假", [bar_row(row["label"], f"{_n(row['leave'])} 天", row["leave"] / biggest * 100) for row in ranked],
                sub=sub, more="看是谁", to=month_target(ctx, "leave"),
                hint="在职员工已批准的请假天数（不含调休），按员工档案里的部门；各部门加起来等于“本月请假”。"
                     "点进去是考勤中心「N 月」概览的“请假”，点一个部门就列出这个部门是谁请的假。")


@provider("block.att_trend", "block", visible=_visible, title="全公司未来 14 天")
def block_att_trend(ctx):
    days = _summary(ctx)["stats"]["days"]
    if not days:
        return None
    biggest = max(int(day.get("off") or 0) for day in days) or 1
    rows = [col_row(str(day["day"]), int(day.get("off") or 0), int(day.get("off") or 0) / biggest * 100, index == 0) for index, day in enumerate(days)]
    return cols("block.att_trend", "全公司未来 14 天", rows, sub="每天请假或调休的人数", more="考勤中心", to=target("attendance.home"),
                hint="已批准的请假和调休，周末和节假日为 0。考勤中心首页有同一张图，点某一天的柱子就列出那天是谁。" + HINT)
