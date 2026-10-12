"""看板：公司考勤（人事 / 副总 / 总经理，放在“人事”页签的“考勤”一段里）。

只有人数、小时和比例，没有人名；要看是谁，点进考勤中心：先看各部门汇总，点进某个部门才看到那个部门的日历和人名。
数字复用考勤中心的公司汇总（`attendance_board_entry._company_summary`），和考勤中心首页对得上；
本月请假 / 加班 / 部门排行复用 `overview_entry` 的统计（按所选期间）。
"""
from __future__ import annotations

from datetime import date, timedelta

from rayher_hr_payroll import attendance_requests as att
from rayher_hr_payroll.dashboard import people
from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, col_row, cols, kpi, provider, target,
)

STUCK_DAYS = 3
MAX_ROWS = 8
HOURS_PER_DAY = 8
HINT = "只有人数、小时和比例，没有人名；点进考勤中心，先看各部门汇总，点进某个部门才看到那个部门的日历和人名。"


# ---------------------------------------------------------------- 取数（单独成函数，测试里替换）
def _load_summary(ctx):
    from rayher_hr_payroll.api import attendance_board_entry

    return attendance_board_entry._company_summary(date.fromisoformat(ctx.today))


def _load_waiting(ctx):
    """还在审批的请假 / 加班 / 调休：{total, old}；old = 最近一次处理（没有就提交）起已经超过 3 天的张数。"""
    import frappe

    rows = frappe.db.sql(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN DATEDIFF(%(today)s, DATE(modified)) > %(days)s THEN 1 ELSE 0 END) AS old "
        "FROM `tabOA Approval Request` WHERE request_type IN %(types)s AND workflow_status IN %(statuses)s",
        {"today": ctx.today, "days": STUCK_DAYS, "types": tuple(att.ATTENDANCE_TYPES), "statuses": ("待审批", "待办理")}, as_dict=True,
    )
    row = rows[0] if rows else {}
    return {"total": int(row.get("total") or 0), "old": int(row.get("old") or 0)}


def _summary(ctx):
    return ctx.memo("att.summary", lambda: _load_summary(ctx))


def _waiting(ctx):
    return ctx.memo("att.waiting", lambda: _load_waiting(ctx))


def _n(value):
    return f"{round(float(value or 0), 2):g}"


def _month_word(ctx):
    return "本月" if ctx.period == ctx.today[:7] else f"{int(ctx.period[5:])} 月"


def _visible(ctx):
    return people._hr_view(ctx)


# ---------------------------------------------------------------- 指标卡
@provider("att.trip", "kpi", visible=_visible, title="出差中")
def att_trip(ctx):
    today = _summary(ctx)["stats"]["today"]
    return kpi("att.trip", "出差中", today["trip"], "人", "不算请假，不进出勤率", to=target("attendance.today"),
               hint="今天在已批准的出差申请期间的人数（已在请假的不重复算）。" + HINT)


@provider("att.pending", "kpi", visible=_visible, title="考勤待审批")
def att_pending(ctx):
    waiting = _waiting(ctx)
    return kpi("att.pending", "考勤待审批", waiting["total"], "张", f"其中 {waiting['old']} 张超过 {STUCK_DAYS} 天" if waiting["old"] else "没有等得久的",
               "hot" if waiting["old"] else "", to=target("attendance.all"),
               hint=f"请假、加班、调休里还在审批的申请张数（所有审批人手上的，不只是你的）；“超过 {STUCK_DAYS} 天”从最近一次处理（没有就从提交）算起。")


@provider("att.leave", "kpi", visible=_visible, title="本月请假")
def att_leave(ctx):
    stats = people._leave_stats(ctx)["totals"]
    return kpi("att.leave", f"{_month_word(ctx)}请假", _n(stats["leave_days"]), "天",
               f"其中调休 {_n(stats['comp_days'])} 天", to=target("attendance.all"),
               hint="已批准的请假天数（含调休；跨月申请按天拆到各月；小时 ÷ 8）。" + HINT)


@provider("att.overtime", "kpi", visible=_visible, title="本月加班")
def att_overtime(ctx):
    stats = people._leave_stats(ctx)["totals"]
    return kpi("att.overtime", f"{_month_word(ctx)}加班", _n(stats["overtime_days"]), "天", "提交后按 1:1 计入调休额度",
               to=target("attendance.all"), hint="已批准的加班天数（小时 ÷ 8；跨月申请按天拆到各月）。")


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
                 "考勤中心", target("attendance.all"))


# ---------------------------------------------------------------- 图表块
@provider("block.att_depts", "block", visible=_visible, title="各部门请假")
def block_att_depts(ctx):
    rows = [row for row in people._leave_stats(ctx)["by_department"] if row["leave"] > 0]
    if not rows:
        return None
    ranked = sorted(rows, key=lambda row: (-row["leave"], row["label"]))[:MAX_ROWS]
    biggest = ranked[0]["leave"] or 1
    return bars("block.att_depts", f"各部门{_month_word(ctx)}请假", [bar_row(row["label"], f"{_n(row['leave'])} 天", row["leave"] / biggest * 100) for row in ranked],
                sub="天 · 只有部门汇总，没有人名", more="考勤中心", to=target("attendance.home"),
                hint="已批准的请假和调休天数，按员工档案的所属部门。点进考勤中心的部门概况再点某个部门，才看到那个部门的人名和日历。")


@provider("block.att_trend", "block", visible=_visible, title="全公司未来 14 天")
def block_att_trend(ctx):
    days = _summary(ctx)["stats"]["days"]
    if not days:
        return None
    biggest = max(int(day.get("off") or 0) for day in days) or 1
    rows = [col_row(str(day["day"]), int(day.get("off") or 0), int(day.get("off") or 0) / biggest * 100, index == 0) for index, day in enumerate(days)]
    return cols("block.att_trend", "全公司未来 14 天", rows, sub="每天请假或调休的人数", more="考勤中心", to=target("attendance.home"),
                hint="已批准的请假和调休，周末和节假日为 0。" + HINT)
