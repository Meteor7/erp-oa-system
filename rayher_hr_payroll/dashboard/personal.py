"""看板：我自己的数据（假期、申请、报销、工时、通知）+ 首页「要我处理」。

这些都是本人的数据，权限就是"有员工档案"（`ctx.employee`）；待办 `todo.queue` 对所有登录人开放，
范围由 `overview_entry.get_my_approval_queue` 自己按"轮到谁"决定。
单位：接口里的假期余额是「天」，加班 / 调休在考勤首页的月度汇总里是「小时」，这里不换算，原样按各自的单位展示。
PMC 的首页不出现任何金额：待办里不带金额，也不放采购付款这类带金额的事项。
"""
from __future__ import annotations

import calendar

from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, calendar as calendar_block, drill, drill_row, drill_to, kpi, list_row, listing, provider, target, todo_item,
)

MAX_ROWS = 8
RETURNED_HINT = "被退回的申请会变回草稿，要修改后重新提交。"
# 待办 / 申请的 route → 打开单据详情的目标名（参数名都叫 request）
_DETAIL_TARGETS = {
    "/approval/leave": "attendance.detail", "/approval/overtime": "attendance.detail", "/approval/comp-time": "attendance.detail",
    "/approval/claim": "claim.detail", "/approval/payment": "payment.detail", "/approval/procurement": "procurement.detail",
    "/approval/direct-purchase": "directpurchase.detail", "/approval/travel": "travel.detail",
    "/approval/reimbursement": "reimbursement.detail",
}
PRICE_ROUTE = "/approval/procurement/price-approvals"
PAYMENT_ROUTE = "/approval/procurement-payment"
# 「待我审批」按类别拆开时，只有一类就直接跳到那一类的待办列表（没有对应目标的类别不跳）
_APPROVAL_TARGETS = {
    "leave": ("attendance.todo", {"type": "请假"}), "overtime": ("attendance.todo", {"type": "加班"}),
    "comp_time": ("attendance.todo", {"type": "调休"}), "travel": ("attendance.todo", {"type": "出差"}),
    "reimbursement": ("claim.todo", {}), "payment": ("payment.todo", {}), "procurement_payment": ("procpay.approvals", {}),
}
# 出差申请 2026-10-13 并进了考勤中心，待我审批的出差也在考勤中心的“待我审批”里。
_ATTENDANCE_KEYS = ("leave", "overtime", "comp_time", "travel")
_ATTENDANCE_LABELS = {"请假申请": "请假", "加班申请": "加班", "调休申请": "调休"}


# ---------------------------------------------------------------- 取数（单独成函数，测试里替换）
def _load_leave_summary():
    from rayher_hr_payroll.api.overview_entry import get_my_leave_summary
    return get_my_leave_summary()


def _load_attendance_home(period):
    import frappe
    from rayher_hr_payroll.api.attendance_entry import get_attendance_home
    try:
        return get_attendance_home(period=period)
    except frappe.PermissionError:      # 请假 / 加班 / 调休功能还没对这个账号开放
        return {}


def _load_my_strip(ctx):
    """我未来 14 天的安排（考勤中心首页同一份数据：已批准和审批中的请假、调休、出差、加班，休息日标出来）。"""
    from datetime import date

    from rayher_hr_payroll.api import attendance_board_entry
    from rayher_hr_payroll.attendance_scope import resolve_scope

    scope = resolve_scope()
    if not scope.get("employee"):
        return []
    return attendance_board_entry._personal(scope, date.fromisoformat(ctx.today)).get("strip") or []


def _load_my_requests(limit):
    from rayher_hr_payroll.api.overview_entry import get_my_requests
    return get_my_requests(limit=limit)["items"]


def _load_is_rd(user, employee):
    """是不是工时填报名单里的人：研发类型是全时 / 非全时 / 辅助，且不是免填账号。"""
    import frappe
    from rayher_hr_payroll.api.monthly_timesheet_entry import TIMESHEET_EXEMPT_USERS
    from rayher_hr_payroll.api.timesheet_entry import RD_TYPES
    if str(user or "").strip().lower() in TIMESHEET_EXEMPT_USERS:
        return False
    return frappe.db.get_value("Employee", employee, "rd_personnel_type") in RD_TYPES


def _load_my_entries(period, employee):
    from rayher_hr_payroll.api.monthly_timesheet_entry import list_monthly_entries
    return list_monthly_entries(period, employee)


def _load_my_claims(user, employee):
    """我名下在途的报销单（草稿 / 审批中 / 待办理），和 oa_entry.list_requests(view="mine") 同一个范围（本人是申请人或所有人），
    只取看板要的几个字段——list_requests 会把每张单据整个加载。功能没对这个账号开放时返回 None。"""
    import frappe
    from rayher_hr_payroll.oa_document_types import REQUEST_REIMBURSEMENT
    from rayher_hr_payroll.oa_feature_gate import can_access_request_type
    if not can_access_request_type(REQUEST_REIMBURSEMENT, user):
        return None
    return frappe.get_all(
        "OA Approval Request",
        filters={"request_type": REQUEST_REIMBURSEMENT, "workflow_status": ["in", ["草稿", "待审批", "待办理"]]},
        or_filters=[["owner", "=", user], ["employee", "=", employee]],
        fields=["name", "amount", "approved_amount", "workflow_status", "current_step_label"],
        order_by="modified desc", limit_page_length=50)


def _load_approval_summary():
    from rayher_hr_payroll.api.oa_entry import get_my_approval_summary
    return get_my_approval_summary()


def _load_notification_counts():
    """{类别: 未读数}。类别里没有「待你处理」——那些在待办列表里。"""
    from rayher_hr_payroll.api.overview_entry import get_my_notification_feed
    feed = get_my_notification_feed(category="mine", unread_only=1, limit=1)
    return {row["key"]: int(row.get("unread") or 0) for row in feed["categories"]}


def _load_approval_queue(limit):
    from rayher_hr_payroll.api.overview_entry import get_my_approval_queue
    return get_my_approval_queue(limit=limit)["items"]


# ---------------------------------------------------------------- 小工具
def _n(value):
    return f"{round(float(value or 0), 2):g}"


def _md(day):
    return str(day)[5:10]


def _month_word(ctx):
    return "本月" if ctx.period == ctx.today[:7] else f"{int(ctx.period[5:])} 月"


def _yuan(amount):
    amount = float(amount or 0)
    return f"¥ {amount / 10000:,.1f} 万" if abs(amount) >= 10000 else f"¥ {amount:,.0f}"


def _progress_text(status, step):
    if status == "草稿":
        return "草稿"
    if status == "待办理":
        return f"{step}办理中" if step else "待办理"
    return f"{step}审批中" if step else "审批中"


def _detail_target(route, query):
    """待办 / 申请指向的单据 → 看板目标；对应不上就返回 None（按钮不可点，不报错）。"""
    query = query or {}
    if route in _DETAIL_TARGETS:
        return target(_DETAIL_TARGETS[route], request=query.get("request"))
    if route == PRICE_ROUTE:
        if query.get("approval"):
            return target("price.approvals", approval=query["approval"])
        if query.get("po"):
            return target("price.po", po=query["po"])
    if route == PAYMENT_ROUTE:
        if query.get("po"):
            return target("procpay.work", po=query["po"])
        return target("procpay.approvals", request=query.get("request"))
    return None


def _has_employee(ctx):
    return bool(ctx.employee)


def _load_my_trips(ctx):
    """我已办理、还没回来的出差（最近的在前）：前台办理完给我的行程提醒用。

    只算真的经过前台办理的出差（有办理节点而且已办理）；旧路线的出差、前台自己的出差没有这一步，不提醒（修复 2026-10-13）。
    """
    import frappe

    rows = frappe.db.sql(
        "SELECT name, travel_destination, travel_start_date, travel_end_date FROM `tabOA Approval Request` "
        "WHERE request_type = '出差申请' AND employee = %(employee)s AND workflow_status = '已完成' AND travel_end_date >= %(today)s "
        "ORDER BY travel_start_date, name LIMIT 20", {"employee": ctx.employee, "today": ctx.today}, as_dict=True)
    trips = []
    for row in rows:
        desk = frappe.db.sql(
            "SELECT status, note FROM `tabOA Approval Step` WHERE parent = %s AND mode = 'handle' ORDER BY acted_on DESC",
            (row["name"],), as_dict=True)
        done = [step for step in desk or [] if step.get("status") == "已办理"]
        if not done:
            continue
        row["note"] = next((str(step.get("note") or "").strip() for step in done if str(step.get("note") or "").strip()), "")
        trips.append(row)
        if len(trips) >= 5:
            break
    return trips


# ---------------------------------------------------------------- 假期 / 加班
def _leave(ctx):
    summary = ctx.memo("me.leave", _load_leave_summary)
    return summary if summary.get("visible") else None


@provider("me.annual", "kpi", visible=_has_employee, title="年假可用")
def me_annual(ctx):
    summary = _leave(ctx)
    if not summary:
        return None
    annual = summary["annual"]
    hint = "年假可用 = 已发放 − 已用 − 审批中占用，单位是天（8 小时 = 1 天）。"
    if not annual.get("eligible"):
        return kpi("me.annual", "年假可用", "—", "", annual.get("message") or "暂时没有年假", to=target("attendance.home"), hint=hint)
    sub = f"已用 {_n(annual['used'])} 天" + (f" · 审批中 {_n(annual['reserved'])} 天" if annual.get("reserved") else "")
    return kpi("me.annual", "年假可用", _n(annual["available"]), "天", sub, to=target("attendance.home"), hint=hint)


@provider("me.comp", "kpi", visible=_has_employee, title="调休可用")
def me_comp(ctx):
    summary = _leave(ctx)
    if not summary:
        return None
    comp = summary["comp"]
    sub = f"累计加班 {_n(comp['credit'] * 8)} 小时" + (f" · 审批中 {_n(comp['reserved'] * 8)} 小时" if comp.get("reserved") else "")
    return kpi("me.comp", "调休可用", _n(comp["available"]), "天", sub, to=target("attendance.home"),
               hint="调休可用 = 加班累计 − 已调休 − 审批中占用，单位是天（8 小时 = 1 天）；加班按小时累计。")


@provider("me.overtime_month", "kpi", visible=_has_employee, title="本月加班")
def me_overtime_month(ctx):
    home = ctx.memo("me.att_home", lambda: _load_attendance_home(ctx.period))
    month = home.get("month")
    if not home.get("employee") or month is None:
        return None
    leave_days = float(month.get("leave_days") or 0)
    sub = f"请假 {_n(leave_days)} 天" + (f" · 调休 {_n(month['comp_hours'])} 小时" if month.get("comp_hours") else "")
    # 考勤中心首页只看当月：看别的月份时不给跳转（数字对不上就不如不跳）。
    current = ctx.period == ctx.today[:7]
    return kpi("me.overtime_month", f"{_month_word(ctx)}加班", _n(month.get("overtime_hours")), "小时", sub,
               to=target("attendance.home") if current else None,
               hint="本人已批准和审批中的加班小时数；请假按天、调休按小时，都含审批中的。" + ("点进去是考勤中心首页（当月）。" if current else ""))


@provider("alert.me_trip", "alert", visible=_has_employee)
def alert_me_trip(ctx):
    """出差办理完以后的行程提醒：显示到回来那天为止，带前台的备注；和“抄送”“已完成”通知不一样，是要他安排工作的。"""
    trips = ctx.memo("me.trips", lambda: _load_my_trips(ctx))
    if not trips:
        return None
    trip = trips[0]
    start, end = str(trip.get("travel_start_date") or "")[5:10], str(trip.get("travel_end_date") or "")[5:10]
    when = start if not end or end == start else f"{start} 至 {end}"
    place = str(trip.get("travel_destination") or "").strip()
    more = f"，另有 {len(trips) - 1} 次出差" if len(trips) > 1 else ""
    return alert("alert.me_trip", "info", f"{when} 去{place or '外地'}出差，前台已办理，请安排好行程{more}",
                 str(trip.get("note") or "").strip() or "请安排好手头的工作和交接", "出差详情", target("travel.detail", request=trip["name"]))


@provider("alert.me_leave_unused", "alert", visible=_has_employee)
def alert_me_leave_unused(ctx):
    summary = _leave(ctx)
    if not summary:
        return None
    annual = summary["annual"]
    if not annual.get("eligible") or annual.get("available", 0) <= 0 or annual.get("used", 0) or annual.get("reserved", 0):
        return None
    return alert("alert.me_leave_unused", "info", f"年假还有 {_n(annual['available'])} 天一天没休", "年底前记得安排", "考勤中心", target("attendance.home"))


@provider("block.me_strip", "block", visible=_has_employee, title="我的下两周")
def block_me_strip(ctx):
    strip = ctx.memo("me.strip", lambda: _load_my_strip(ctx))
    if not strip:
        return None
    days = [{key: day.get(key) for key in ("date", "label", "day", "weekday", "off_day")} for day in strip]
    cells = [{"kind": day["kind"], "pending": bool(day.get("pending"))} if day.get("kind") else None for day in strip]
    return calendar_block("block.me_strip", "我的下两周", days, [{"name": "我", "cells": cells}], [],
                          sub="假期、出差、加班 · 虚线是还在审批", more="考勤中心", to=target("attendance.home"),
                          hint="未来 14 天我的请假、调休、出差、加班（和考勤中心首页同一份数据）；周末和节假日是浅灰。")


@provider("block.me_balances", "block", visible=_has_employee, title="我的假期")
def block_me_balances(ctx):
    summary = _leave(ctx)
    if not summary:
        return None
    annual, comp = summary["annual"], summary["comp"]
    rows = []
    if annual.get("eligible"):
        granted = float(annual.get("granted") or 0)
        rows.append(bar_row("年假", f"可用 {_n(annual['available'])} / {_n(granted)} 天", annual["available"] / granted * 100 if granted else 0, "ok"))
    credit = float(comp.get("credit") or 0)
    rows.append(bar_row("调休", f"可用 {_n(comp['available'] * 8)} 小时", comp["available"] / credit * 100 if credit else 0, "info"))
    sub = "已用 " + _n(annual.get("used")) + " 天" + (f" · 审批中 {_n(annual['reserved'])} 天" if annual.get("reserved") else "") if annual.get("eligible") else "年假暂未发放"
    return bars("block.me_balances", "我的假期", rows, sub=sub, more="考勤中心", to=target("attendance.home"),
                hint="年假和调休余额（年假按天，调休按小时；条的长短是剩下的占已发放 / 累计加班的比例）。")


# ---------------------------------------------------------------- 我的申请 / 报销
def _requests(ctx):
    return ctx.memo("me.requests", lambda: _load_my_requests(50))


@provider("me.requests", "kpi", visible=_has_employee, title="我的申请")
def me_requests(ctx):
    items = _requests(ctx)
    returned = sum(1 for row in items if row.get("returned"))
    drafts = sum(1 for row in items if row.get("status") == "草稿" and not row.get("returned"))
    running = len(items) - returned - drafts
    parts = [f"进行中 {running}"] if running else []
    if returned:
        parts.append(f"被退回 {returned}")
    if drafts:
        parts.append(f"草稿 {drafts}")
    return kpi("me.requests", "我的申请", len(items), "张", " · ".join(parts) or "没有进行中的申请", tone="hot" if returned else "",
               to=drill_to("me.requests", ctx) if items else None,
               hint="我提交的、还没办结的申请（审批中、被退回、草稿）；点进去一演示员工128行，每一行进那张单据。" + RETURNED_HINT)


@provider("drill.me.requests", "drill", visible=_has_employee, title="我的申请")
def drill_me_requests(ctx):
    items = sorted(_requests(ctx), key=lambda row: not row.get("returned"))
    rows = [drill_row([row.get("subject") or row.get("name"), row.get("request_type") or "", _request_row(row)["sub"].split(" · ", 1)[-1], row.get("name") or ""],
                      _detail_target(row.get("route"), {"request": row.get("name")}), tone="bad" if row.get("returned") else "")
            for row in items]
    return drill("drill.me.requests", "我的申请", [("申请",), ("类型",), ("进度",), ("单号",)], rows, summary=f"共 {len(items)} 张",
                 note="我提交的、还没办结的申请，被退回的排在前面（红色）。" + RETURNED_HINT)


def _request_row(row):
    returned, status = bool(row.get("returned")), row.get("status")
    if returned:
        note = str(row.get("returned_note") or "").strip()
        sub, value, tone = "被退回" + (f"：{note[:20]}" if note else ""), "修改", "bad"
    elif status == "草稿":
        sub, value, tone = "草稿", "继续填写", ""
    else:
        sub, value, tone = _progress_text(status, row.get("step_label")), "审批中", "warn"
    return list_row(row.get("subject") or row.get("name"), f"{row.get('request_type')} · {sub}", value, tone,
                    _detail_target(row.get("route"), {"request": row.get("name")}))


@provider("block.me_requests", "block", visible=_has_employee, title="我的申请")
def block_me_requests(ctx):
    items = sorted(_requests(ctx), key=lambda row: not row.get("returned"))   # 被退回的排在前面（同类保持最近修改在前）
    if not items:
        return None
    return listing("block.me_requests", "我的申请", [_request_row(row) for row in items[:MAX_ROWS]], sub="进行中和被退回",
                   hint="我提交的、还没办结的申请，被退回的排在前面。")


@provider("me.claim", "kpi", visible=_has_employee, title="我的报销")
def me_claim(ctx):
    rows = ctx.memo("me.claims", lambda: _load_my_claims(ctx.user, ctx.employee))
    if rows is None:
        return None
    active = [row for row in rows if row.get("workflow_status") != "草稿"]
    drafts = len(rows) - len(active)
    total = sum(float(row.get("approved_amount") or row.get("amount") or 0) for row in active)
    if active:
        latest = active[0]
        sub = f"合计 {_yuan(total)} · {_progress_text(latest.get('workflow_status'), latest.get('current_step_label'))}"
    else:
        sub = "没有在途的报销"
    if drafts:
        sub += f" · 草稿 {drafts}"
    # 报销页“我的”列出我所有的报销单（含已付款的），和这里的“在途”张数对不上；点进去是同一份在途清单（决定 2026-10-13）。
    return kpi("me.claim", "我的报销", len(active), "张", sub, to=drill_to("me.claim", ctx) if rows else target("claim.mine"),
               hint="我名下的报销单：审批中或等演示员工110付款的张数；金额取审批金额（没有就取申请金额）。不预测到账日，只显示审批到了哪一步。"
                    "点进去一演示员工128行（草稿浅色列在后面，不算在张数里），每一行进报销单。")


@provider("drill.me.claim", "drill", visible=_has_employee, title="我的报销")
def drill_me_claim(ctx):
    rows = ctx.memo("me.claims", lambda: _load_my_claims(ctx.user, ctx.employee)) or []
    active = [row for row in rows if row.get("workflow_status") != "草稿"]
    drafts = [row for row in rows if row.get("workflow_status") == "草稿"]
    out = [drill_row([row["name"], _progress_text(row.get("workflow_status"), row.get("current_step_label")),
                      _yuan(row.get("approved_amount") or row.get("amount"))], target("claim.detail", request=row["name"]))
           for row in active]
    out += [drill_row([row["name"], "草稿", _yuan(row.get("amount"))], target("claim.detail", request=row["name"]), tone="info") for row in drafts]
    total = sum(float(row.get("approved_amount") or row.get("amount") or 0) for row in active)
    return drill("drill.me.claim", "我在途的报销单", [("单号",), ("进度",), ("金额", "r")], out, summary=f"在途 {len(active)} 张，合计 {_yuan(total)}",
                 note="审批中或等演示员工110付款的报销单；草稿浅色列在后面，不算在张数里。已付款的在报销页“我的”里看。")


# ---------------------------------------------------------------- 我的工时
def _my_timesheet(ctx):
    """{limit, used, entries}；不在工时填报名单里（非研发、免填账号）就是 None。"""
    def build():
        if not _load_is_rd(ctx.user, ctx.employee):
            return None
        data = _load_my_entries(ctx.period, ctx.employee)
        limit, used = float(data.get("max_day_limit") or 0), float(data.get("total_days") or 0)
        return {"limit": limit, "used": used, "entries": data.get("entries") or [],
                "limit_hours": float(data["hour_limit"]) if data.get("hour_limit") is not None else limit * 8,
                "used_hours": float(data["total_hours"]) if data.get("total_hours") is not None else used * 8}
    return ctx.memo("me.ts", build)


def _fill_status(used_hours, limit_hours):
    from rayher_hr_payroll.api.monthly_timesheet_entry import _fill_status as fill_status
    return fill_status(used_hours, limit_hours)


def _ts_state(data):
    """(状态, 差几天)：和填报进度（monthly_timesheet_entry._fill_status）同一条规则——按小时比，填的小时等于可填小时才算填满；
    一点没填也算“还差”。差几天 = 差的小时 ÷ 8。"""
    status = _fill_status(data["used_hours"], data["limit_hours"])
    diff = round((data["limit_hours"] - data["used_hours"]) / 8, 2)
    return ("part" if status in ("part", "none") else status), diff


@provider("me.timesheet", "kpi", visible=_has_employee, title="本月工时")
def me_timesheet(ctx):
    data = _my_timesheet(ctx)
    if not data or data["limit"] < 0.01:
        return None
    state, diff = _ts_state(data)
    label = f"{_month_word(ctx)}工时"
    detail = f"已填 {_n(data['used'])} / {_n(data['limit'])}"
    to = target("timesheet.mine", period=ctx.period)
    hint = "已填天数 / 当月可填上限（按工作日折算，扣掉已批准的事假）。只有研发工时填报名单里的人才有。"
    if state == "part":
        return kpi("me.timesheet", label, f"还差 {_n(diff)}", "天", detail, tone="hot", to=to, hint=hint)
    if state == "over":
        return kpi("me.timesheet", label, f"超 {_n(-diff)}", "天", detail + "，请调整", tone="warn", to=to, hint=hint)
    return kpi("me.timesheet", label, "已填满", "", detail + " 天", tone="ok", to=to, hint=hint)


@provider("alert.me_timesheet", "alert", visible=_has_employee)
def alert_me_timesheet(ctx):
    data = _my_timesheet(ctx)
    if not data or data["limit"] < 0.01 or ctx.period > ctx.today[:7]:
        return None
    state, diff = _ts_state(data)
    if state != "part":
        return None
    year, month = int(ctx.period[:4]), int(ctx.period[5:])
    last_day = f"{ctx.period}-{calendar.monthrange(year, month)[1]:02d}"
    past = ctx.today > last_day
    return alert("alert.me_timesheet", "bad" if past else "warn", f"{month} 月工时还差 {_n(diff)} 天",
                 f"{_md(last_day)} 截止" + ("，已过截止" if past else ""), "去填报", target("timesheet.mine", period=ctx.period))


@provider("block.me_timesheet", "block", visible=_has_employee, title="我这个月的工时")
def block_me_timesheet(ctx):
    data = _my_timesheet(ctx)
    if not data or data["limit"] < 0.01:
        return None
    totals = {}
    for row in data["entries"]:
        name = row.get("project_name") or row.get("project_code") or row.get("project") or "未命名项目"
        totals[name] = totals.get(name, 0) + float(row.get("occurrence_days") or 0)
    limit = data["limit"]
    rows = [bar_row(name, _n(days), days / limit * 100) for name, days in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:MAX_ROWS - 1]]
    state, diff = _ts_state(data)
    if state == "part":
        rows.append(bar_row("还差", _n(diff), diff / limit * 100, "warn"))
    title = "我这个月的工时" if ctx.period == ctx.today[:7] else f"我 {int(ctx.period[5:])} 月的工时"
    return bars("block.me_timesheet", title, rows, sub=f"已填 {_n(data['used'])} / {_n(limit)} 天", more="去填报",
                to=target("timesheet.mine", period=ctx.period), hint="按项目汇总我这个月填的天数；条的长短是占当月可填上限的比例。")


# ---------------------------------------------------------------- 审批 / 抄送 / 通知
@provider("me.approvals", "kpi", title="待我审批")
def me_approvals(ctx):
    summary = ctx.memo("me.approval_summary", _load_approval_summary)
    categories = [row for row in summary.get("categories", []) if row.get("count")]
    total = int(summary.get("total") or 0)
    top = sorted(categories, key=lambda row: -row["count"])[:3]
    sub = " · ".join(f"{row['label']} {row['count']}" for row in top) or "没有要我审批的"
    to = None
    keys = [row["key"] for row in categories]
    if len(keys) == 1 and keys[0] in _APPROVAL_TARGETS:
        key, params = _APPROVAL_TARGETS[keys[0]]
        to = target(key, **params)
    elif keys and all(key in _ATTENDANCE_KEYS for key in keys):
        to = target("attendance.todo")
    return kpi("me.approvals", "待我审批", total, "张", sub, tone="hot" if total else "", to=to,
               hint="现在轮到我审批的单据数（各类申请合计）；具体哪几张在左边“要我处理”里。")


def _notification_counts(ctx):
    return ctx.memo("me.notes", _load_notification_counts)


@provider("me.cc", "kpi", visible=_has_employee, title="抄送给我")
def me_cc(ctx):
    count = _notification_counts(ctx).get("cc", 0)
    return kpi("me.cc", "抄送给我", count, "条", "只是知会，不用审批" if count else "没有未读的抄送", to=drill_to("me.cc", ctx) if count else None,
               hint="别人抄送给我、我还没读的通知条数；点进去按单据列出来（同一张单据的几条合成一行），也可以在页面最下面的“通知”里查看。")


@provider("me.unread", "kpi", title="未读通知")
def me_unread(ctx):
    count = sum(_notification_counts(ctx).values())
    return kpi("me.unread", "未读通知", count, "条", "", tone="hot" if count else "", to=drill_to("me.unread", ctx) if count else None,
               hint="我还没读的通知条数（含抄送、我的申请进展、业务进展、系统通知；不含“待你处理”，那些在待办里）。"
                    "点进去按单据列出来（同一张单据的几条合成一行），也可以在页面最下面的“通知”里查看。")


def _load_notification_items(category):
    """某一类未读通知（按单据合并），和通知区同一个接口。"""
    from rayher_hr_payroll.api.overview_entry import get_my_notification_feed
    return get_my_notification_feed(category=category, unread_only=1, limit=400)["items"]


_NOTE_CATEGORIES = (("cc", "抄送"), ("mine", "我的申请"), ("biz", "业务进展"), ("sys", "系统与指派"))


def _notification_drill(ctx, key, title, categories):
    counts = _notification_counts(ctx)
    rows = []
    for category, label in categories:
        for item in _load_notification_items(category):
            rows.append(drill_row([label, item.get("event") or "通知", item.get("title") or item.get("document") or "", str(item.get("created") or "")[5:16]],
                                  _detail_target(item.get("route"), item.get("query"))))
    total = sum(counts.get(category, 0) for category, _label in categories)
    return drill(key, title, [("类别",), ("事件",), ("单据",), ("时间",)], rows, summary=f"共 {total} 条未读，涉及 {len(rows)} 份单据",
                 note="同一张单据的几条通知合成一行，所以行数可能比条数少。打开后在页面最下面的“通知”里标记已读。")


@provider("drill.me.cc", "drill", visible=_has_employee, title="抄送给我")
def drill_me_cc(ctx):
    return _notification_drill(ctx, "drill.me.cc", "抄送给我、还没读的", _NOTE_CATEGORIES[:1])


@provider("drill.me.unread", "drill", title="未读通知")
def drill_me_unread(ctx):
    return _notification_drill(ctx, "drill.me.unread", "未读通知", _NOTE_CATEGORIES)


# ---------------------------------------------------------------- 要我处理
def _todo_title(item):
    label = _ATTENDANCE_LABELS.get(item.get("request_type"))
    if not label:
        return item.get("subject") or item.get("name") or ""
    first, last = str(item.get("from_date") or ""), str(item.get("to_date") or "")
    span = _md(first) if first == last else f"{_md(first)} 至 {_md(last)}"
    hours = f" {_n(item['hours'])} 小时" if label == "加班" and item.get("hours") else ""
    return f"{label} · {item.get('applicant') or ''} · {span}{hours}"


def _todo_sub(item, hide_money):
    parts = []
    if item.get("request_type") not in _ATTENDANCE_LABELS and item.get("applicant"):
        parts.append(str(item["applicant"]))
    if not hide_money and float(item.get("amount") or 0) > 0:
        parts.append(_yuan(item["amount"]))
    waited = int(item.get("waited_days") or 0)
    parts.append(f"等你 {waited} 天" if waited else "今天刚到")
    return " · ".join(parts)


def _queue_todo(item, hide_money):
    kind, query = item.get("kind") or item.get("request_type") or "", item.get("query") or {}
    btn = "去提交" if kind == "采购付款" and query.get("po") else "去处理" if kind == "采购订单" else "去审批"
    waited = int(item.get("waited_days") or 0)
    return todo_item(kind, _todo_title(item), _todo_sub(item, hide_money), btn, "warn" if waited > 3 else "info",
                     _detail_target(item.get("route"), query))


def _returned_todo(row):
    note = str(row.get("returned_note") or "").strip()
    return todo_item(row.get("request_type") or "", f"被退回 · {row.get('subject') or row.get('name')}",
                     note[:30] or "请修改后重新提交", "去修改", "bad", _detail_target(row.get("route"), {"request": row.get("name")}))


@provider("todo.queue", "todos", title="要我处理")
def todo_queue(ctx):
    """轮到我审批 / 办理的事（最多 8 件），再加上被退回要我修改的申请。"""
    hide_money = ctx.profile == "pmc"
    items = _load_approval_queue(MAX_ROWS)
    if hide_money:
        items = [item for item in items if item.get("kind") != "采购付款"]
    todos = [_queue_todo(item, hide_money) for item in items]
    if ctx.employee:
        todos += [_returned_todo(row) for row in _requests(ctx) if row.get("returned")]
    return todos[:MAX_ROWS]
