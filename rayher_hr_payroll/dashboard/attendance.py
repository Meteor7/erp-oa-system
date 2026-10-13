"""看板：公司考勤（人事 / 副总 / 总经理，放在“人事”页签的“考勤”一段里）。

请假的数字只有人数、小时和比例，没有人名；要看是谁，点进考勤中心：先看各部门汇总，点进某个部门才看到那个部门的日历和人名。
出差不一样：“出差中”点进去一人一行，直接进出差申请（出差申请现在在考勤中心里，人事、副总、总经理都能看到）。
数字复用考勤中心的公司汇总（`attendance_board_entry._company_summary`），和考勤中心首页对得上；
本月请假 / 加班 / 部门排行复用 `overview_entry` 的统计（按所选期间）。
"""
from __future__ import annotations

from datetime import date, timedelta

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
HINT = "只有人数、小时和比例，没有人名；点进考勤中心，先看各部门汇总，点进某个部门才看到那个部门的日历和人名。"


# ---------------------------------------------------------------- 取数（单独成函数，测试里替换）
def _load_summary(ctx):
    from rayher_hr_payroll.api import attendance_board_entry

    return attendance_board_entry._company_summary(date.fromisoformat(ctx.today))


def _load_today_trips(ctx):
    """今天出差的人，一人一条（口径同公司汇总里的“出差中”）。"""
    from rayher_hr_payroll.api import attendance_board_entry

    return attendance_board_entry.today_trips(date.fromisoformat(ctx.today))


def _load_waiting(ctx):
    """还在审批的请假 / 加班 / 调休 / 出差：{total, old}；old = 最近一次处理（没有就提交）起已经超过 3 天的张数。"""
    import frappe

    rows = frappe.db.sql(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN DATEDIFF(%(today)s, DATE(modified)) > %(days)s THEN 1 ELSE 0 END) AS old "
        "FROM `tabOA Approval Request` WHERE request_type IN %(types)s AND workflow_status IN %(statuses)s",
        {"today": ctx.today, "days": STUCK_DAYS, "types": tuple(CENTER_TYPES), "statuses": ("待审批", "待办理")}, as_dict=True,
    )
    row = rows[0] if rows else {}
    return {"total": int(row.get("total") or 0), "old": int(row.get("old") or 0)}


def _load_waiting_rows(ctx):
    """还在审批的请假 / 加班 / 调休 / 出差，一演示员工128行（明细用；条数口径同 _load_waiting）。出差的起止日期取出发、返回日期。"""
    import frappe

    return frappe.db.sql(
        "SELECT name, request_type, employee_name, department, COALESCE(from_date, travel_start_date) AS from_date, "
        "COALESCE(to_date, travel_end_date) AS to_date, duration_hours, current_step_label, "
        "DATEDIFF(%(today)s, DATE(modified)) AS waited FROM `tabOA Approval Request` "
        "WHERE request_type IN %(types)s AND workflow_status IN %(statuses)s ORDER BY waited DESC, name",
        {"today": ctx.today, "types": tuple(CENTER_TYPES), "statuses": ("待审批", "待办理")}, as_dict=True)


def _load_month_rows(ctx):
    """所选月份已批准的请假 / 加班 / 调休（跨月的申请只留落在这个月里的小时）：和本月请假 / 加班同一份数据。"""
    from rayher_hr_payroll.api import overview_entry

    return overview_entry._attendance_rows([(int(ctx.period[:4]), int(ctx.period[5:7]))], None)


def _month_rows(ctx):
    return ctx.memo("att.month_rows", lambda: _load_month_rows(ctx))


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
    return kpi("att.trip", "出差中", today["trip"], "人", "不算请假，不进出勤率", to=drill_to("att.trip", ctx) if today["trip"] else None,
               hint="今天在已批准的出差申请期间的人数（已在请假的不重复算；周末和节假日不算）。点进去一人一行，每一行进出差申请。")


@provider("att.pending", "kpi", visible=_visible, title="考勤待审批")
def att_pending(ctx):
    waiting = _waiting(ctx)
    return kpi("att.pending", "考勤待审批", waiting["total"], "张", f"其中 {waiting['old']} 张超过 {STUCK_DAYS} 天" if waiting["old"] else "没有等得久的",
               "hot" if waiting["old"] else "", to=drill_to("att.pending", ctx) if waiting["total"] else None,
               hint=f"请假、加班、调休、出差里还在审批的申请张数（所有审批人手上的，不只是你的）；“超过 {STUCK_DAYS} 天”从最近一次处理（没有就从提交）算起。"
                    "点进去一演示员工128行，每一行进申请详情。")


@provider("att.leave", "kpi", visible=_visible, title="本月请假")
def att_leave(ctx):
    stats = people._leave_stats(ctx)["totals"]
    return kpi("att.leave", f"{_month_word(ctx)}请假", _n(stats["leave_days"]), "天",
               f"另有调休 {_n(stats['comp_days'])} 天", to=drill_to("att.leave", ctx) if stats["leave_days"] else None,
               hint="已批准的请假天数（不含调休，调休单独算；跨月申请按天拆到各月；小时 ÷ 8）。点进去按部门看。" + HINT)


@provider("att.overtime", "kpi", visible=_visible, title="本月加班")
def att_overtime(ctx):
    stats = people._leave_stats(ctx)["totals"]
    return kpi("att.overtime", f"{_month_word(ctx)}加班", _n(stats["overtime_days"]), "天", "提交后按 1:1 计入调休额度",
               to=drill_to("att.overtime", ctx) if stats["overtime_days"] else None,
               hint="已批准的加班天数（小时 ÷ 8；跨月申请按天拆到各月）。点进去按部门看。")


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
    rows = _load_waiting_rows(ctx)
    if only_old:
        rows = [row for row in rows if int(row.get("waited") or 0) > STUCK_DAYS]
    out = [drill_row([row["request_type"], row.get("employee_name") or "—", people._dept_label(row.get("department")) or "—",
                      f"{str(row.get('from_date') or '')[5:10]} ～ {str(row.get('to_date') or row.get('from_date') or '')[5:10]}",
                      row.get("current_step_label") or "—", f"{int(row.get('waited') or 0)} 天"],
                     target("attendance.detail", request=row["name"]), tone="bad" if int(row.get("waited") or 0) > STUCK_DAYS else "")
           for row in rows]
    summary = f"共 {len(rows)} 张" + (f"，都等了超过 {STUCK_DAYS} 天" if only_old else "")
    return drill(key, title, [("类型",), ("申请人",), ("部门",), ("日期",), ("现在在",), ("已等", "r")], out, summary=summary,
                 note=f"“已等”从最近一次处理（没有就从提交）算起；红色 = 超过 {STUCK_DAYS} 天。")


@provider("drill.att.pending", "drill", visible=_visible, title="考勤待审批")
def drill_att_pending(ctx):
    return _waiting_drill(ctx, "drill.att.pending", "考勤待审批", only_old=False)


@provider("drill.att.pending_old", "drill", visible=_visible, title="考勤申请等得久")
def drill_att_pending_old(ctx):
    return _waiting_drill(ctx, "drill.att.pending_old", f"等了超过 {STUCK_DAYS} 天的考勤申请", only_old=True)


def _by_department(ctx, request_types):
    """所选月份已批准的申请按部门合计：{部门: [张数, 天数]}（天数 = 落在这个月里的小时 ÷ 8，同本月请假 / 加班）。"""
    from rayher_hr_payroll.api import overview_entry

    grouped = {}
    for row in _month_rows(ctx):
        if row.get("request_type") not in request_types:
            continue
        label = people._dept_label(row.get("department")) or "未分配部门"
        entry = grouped.setdefault(label, [0, 0.0])
        entry[0] += 1
        entry[1] += overview_entry.days(float(row.get("duration_hours") or 0))
    return grouped


def _department_drill(ctx, key, title, request_types, noun, note):
    grouped = _by_department(ctx, request_types)
    ranked = sorted(grouped.items(), key=lambda item: (-item[1][1], item[0]))
    rows = [drill_row([label, f"{count} 张", f"{_n(days)} 天"], target("attendance.home")) for label, (count, days) in ranked]
    total_count = sum(entry[0] for entry in grouped.values())
    total_days = sum(entry[1] for entry in grouped.values())
    return drill(key, title, [("部门",), (noun, "r"), ("天数", "r")], rows, summary=f"共 {total_count} 张，合计 {_n(total_days)} 天", note=note)


@provider("drill.att.leave", "drill", visible=_visible, title="本月请假")
def drill_att_leave(ctx):
    return _department_drill(ctx, "drill.att.leave", f"{_month_word(ctx)}请假 · 按部门", {att.REQUEST_LEAVE}, "请假单",
                             "已批准的请假（不含调休），跨月申请只算落在这个月里的天数；" + HINT)


@provider("drill.att.overtime", "drill", visible=_visible, title="本月加班")
def drill_att_overtime(ctx):
    return _department_drill(ctx, "drill.att.overtime", f"{_month_word(ctx)}加班 · 按部门", {att.REQUEST_OVERTIME}, "加班单",
                             "已批准的加班，跨月申请只算落在这个月里的天数；" + HINT)


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
