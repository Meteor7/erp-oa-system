"""看板：研发工时填报进度 + 部门（出勤、加班、请假、在职）。

数据来源和权限，都跟着现有接口走，不放宽：
- 工时填报：`monthly_timesheet_entry.get_fill_progress(period)`。它自己按身份限定范围——HR / 管理员 / 财务看全公司（kind=all），
  部门主管看自己 + 直接下属里的研发人员（kind=team），纯员工拿到空名单。所以这里用返回的 kind 决定标签
  （"本部门" 还是 "全公司"），不另外猜范围。
- 部门出勤：跟 `overview_entry.hr_scope` 同一条规则（HR 角色、部门主管角色、副总 / 总经理），范围取本人的所属部门。
  请假、调休只数「已完成」的申请；加班、请假小时数沿用 `overview_entry._attendance_rows`（跨月申请按天拆）。
- 「本部门」有两种口径，两处不一致时以 hint 说明：工时填报按汇报关系（自己 + 直接下属，仅研发人员），
  出勤 / 加班 / 请假 / 在职按员工档案的所属部门。
"""
from __future__ import annotations

from datetime import date, timedelta

from rayher_hr_payroll import attendance_requests as att
from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, kpi, provider, target,
)

# get_fill_progress 里看全公司的角色；部门主管角色看本部门。其他人（纯员工）拿到的是空名单。
FILL_ALL_ROLES = ("System Manager", "HR User", "HR Manager", "Accounts User")
FILL_ROLES = (*FILL_ALL_ROLES, "Department Manager")
# overview_entry.hr_scope 的规则：HR 角色 / 部门主管角色 / 副总、总经理
DEPT_ROLES = ("System Manager", "HR User", "HR Manager", "Department Manager")
DEPT_POSITIONS = ("vice_manager", "general_manager")
HR_ROLES = ("System Manager", "HR User", "HR Manager")
AWAY_WINDOW_DAYS = 14
HOURS_PER_DAY = 8     # 请假在申请里按小时存，看板按天展示
MAX_ROWS = 8
FILL_HINT = "按工时填报名单统计：研发类型为全时 / 非全时 / 辅助的人员（含本月离职的、不含免填账号）。已填满 = 已填天数达到当月可填上限；超过上限的不算已填满。"


# ---------------------------------------------------------------- 取数（单独成函数，测试里替换）
def _load_fill(period):
    from rayher_hr_payroll.api.monthly_timesheet_entry import get_fill_progress
    return get_fill_progress(period)


def _load_entries(period):
    from rayher_hr_payroll.api.monthly_timesheet_entry import list_monthly_entries
    return list_monthly_entries(period)


def _load_rd_headcount():
    """研发类型是全时 / 非全时 / 辅助的在职人数（不排除免填账号，hint 里说明）。"""
    import frappe
    from rayher_hr_payroll.api.timesheet_entry import RD_TYPES
    return frappe.db.count("Employee", {"status": "Active", "rd_personnel_type": ["in", list(RD_TYPES)]})


def _load_department_staff(department):
    import frappe
    return frappe.get_all("Employee", filters={"status": "Active", "department": department},
                          fields=["name", "date_of_joining"], limit_page_length=0)


def _load_absence_rows(department, start, end):
    """本部门已批准的请假 / 调休申请里，与 [start, end] 相交的。"""
    import frappe
    return frappe.get_all(
        "OA Approval Request",
        filters={"request_type": ["in", [att.REQUEST_LEAVE, att.REQUEST_COMP_TIME]],
                 "workflow_status": ["in", sorted(att.COMPLETED)], "department": department,
                 "from_date": ["<=", end], "to_date": [">=", start]},
        fields=["employee", "employee_name", "request_type", "from_date", "to_date", "attendance_days"],
        limit_page_length=0)


def _load_attendance_rows(year, month, department):
    from rayher_hr_payroll.api.overview_entry import _attendance_rows
    return _attendance_rows([(year, month)], department)


# ---------------------------------------------------------------- 小工具
def _n(value):
    return f"{round(float(value or 0), 2):g}"


def _md(day):
    return str(day)[5:10]


def _month_word(ctx):
    return "本月" if ctx.period == ctx.today[:7] else f"{int(ctx.period[5:])} 月"


def _prev_period(period):
    year, month = int(period[:4]), int(period[5:])
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _scope_label(kind):
    return "本部门" if kind == "team" else "全公司"


# ---------------------------------------------------------------- 工时填报
def _fill_visible(ctx):
    return ctx.can(*FILL_ROLES)


def _fill(ctx, *kinds):
    """填报进度；范围不对（纯员工的空名单）或名单是空的，就当没有东西可显示。"""
    data = ctx.memo("ts.fill", lambda: _load_fill(ctx.period))
    if data.get("kind") not in kinds or not data["summary"]["total"]:
        return None
    return data


def _board(ctx, status=None):
    return target("timesheet.board", status=status, period=ctx.period)


@provider("ts.rate", "kpi", visible=_fill_visible, title="工时填报率")
def ts_rate(ctx):
    data = _fill(ctx, "all", "team")
    if not data:
        return None
    s = data["summary"]
    label = "工时填报率" if data["kind"] == "all" else "本部门工时填报率"
    return kpi("ts.rate", label, f"{s['rate']:g}", "%", f"{s['full']} / {s['total']} 人已填满",
               tone="ok" if s["full"] == s["total"] else "hot", to=_board(ctx), hint=FILL_HINT)


@provider("ts.rd_count", "kpi", visible=_fill_visible, title="研发人员在册")
def ts_rd_count(ctx):
    data = _fill(ctx, "all")
    if not data:
        return None
    return kpi("ts.rd_count", "研发人员在册", _load_rd_headcount(), "人", f"填工时 {data['summary']['total']} 人",
               to=_board(ctx),
               hint="研发 = 研发类型是全时 / 非全时 / 辅助的在职人数；填工时 = 本月工时填报名单人数（含本月离职的、不含免填账号），两个数可能不同。")


@provider("ts.team", "kpi", visible=_fill_visible, title="工时已填满")
def ts_team(ctx):
    data = _fill(ctx, "team", "all")
    if not data:
        return None
    s = data["summary"]
    unfilled = s["part"] + s["none"]
    sub = "全部已填满" if not unfilled and not s["over"] else f"{unfilled} 人没填满"
    if s["over"]:
        sub += f"，{s['over']} 人超上限"
    scope = _scope_label(data["kind"])
    return kpi("ts.team", f"{scope}工时已填满", f"{s['full']} / {s['total']}", "人", sub,
               tone="hot" if unfilled else "ok", to=_board(ctx, "open" if unfilled else None),
               hint=(f"{scope}的工时填报名单。" + ("范围按汇报关系：自己 + 直接下属里的研发人员（不是员工档案的所属部门）。" if data["kind"] == "team" else "")) + FILL_HINT)


@provider("ts.none", "kpi", visible=_fill_visible, title="没填工时的人")
def ts_none(ctx):
    data = _fill(ctx, "team", "all")
    if not data:
        return None
    count = data["summary"]["none"]
    return kpi("ts.none", "没填工时的人", count, "人", "一点没填" if count else "都已开始填报",
               tone="bad" if count else "ok", to=_board(ctx, "none" if count else None),
               hint=f"{_scope_label(data['kind'])}填报名单里，这个月一天都没填的人。")


def _open_alert(ctx, key, data, prefix):
    s = data["summary"]
    unfilled = s["part"] + s["none"]
    if not unfilled or ctx.period > ctx.today[:7]:
        return None
    past = ctx.today > data["deadline"]
    title = f"{prefix}{unfilled} 人{_month_word(ctx)}工时没填满"
    if s["none"]:
        title += f"，{s['none']} 人一点没填"
    sub = f"截止 {_md(data['deadline'])}" + ("，已过截止" if past else "") + ("，可以催办" if data["can_remind"] else "")
    return alert(key, "bad" if past else "warn", title, sub, "填报进度", _board(ctx, "open"))


@provider("alert.ts_open", "alert", visible=_fill_visible)
def alert_ts_open(ctx):
    data = _fill(ctx, "all")
    return _open_alert(ctx, "alert.ts_open", data, "") if data else None


@provider("alert.ts_open_team", "alert", visible=_fill_visible)
def alert_ts_open_team(ctx):
    data = _fill(ctx, "team", "all")
    return _open_alert(ctx, "alert.ts_open_team", data, "" if data["kind"] == "team" else "全公司 ") if data else None


@provider("block.ts_by_dept", "block", visible=_fill_visible, title="各部门工时填报进度")
def block_ts_by_dept(ctx):
    data = _fill(ctx, "all")
    if not data:
        return None
    groups = {}
    for row in data["employees"]:
        name = row["department"] or "未分配部门"
        full_count, total = groups.get(name, (0, 0))
        groups[name] = (full_count + (row["status"] == "full"), total + 1)
    ranked = sorted(((name, full, total, full / total * 100) for name, (full, total) in groups.items()),
                    key=lambda item: (item[3], -item[2], item[0]))
    rows = [bar_row(name, f"{full} / {total}", pct, "ok" if pct >= 60 else "warn" if pct >= 40 else "bad")
            for name, full, total, pct in ranked[:MAX_ROWS]]
    sub = "已填满 / 部门人数" + (f" · 只列最需要跟进的 {MAX_ROWS} 个部门" if len(ranked) > MAX_ROWS else "")
    return bars("block.ts_by_dept", "各部门工时填报进度", rows, sub=sub, more="填报进度", to=_board(ctx, "open"), hint=FILL_HINT)


_STATUS_ORDER = {"none": 0, "part": 1, "over": 2, "full": 3}
_STATUS_TONE = {"none": "bad", "part": "warn", "over": "warn", "full": "ok"}


@provider("block.ts_team", "block", visible=_fill_visible, title="本部门工时填报进度")
def block_ts_team(ctx):
    data = _fill(ctx, "team", "all")
    if not data:
        return None
    people = sorted(data["employees"], key=lambda r: (_STATUS_ORDER.get(r["status"], 9), r["employee_name"]))
    rows = [bar_row(p["employee_name"], f"{_n(p['used_days'])} / {_n(p['limit_days'])}",
                    p["used_days"] / p["limit_days"] * 100 if p["limit_days"] else 0, _STATUS_TONE.get(p["status"], ""))
            for p in people[:MAX_ROWS]]
    scope = _scope_label(data["kind"])
    sub = "已填 / 上限（天）" + (f" · 只列最需要跟进的 {MAX_ROWS} 人" if len(people) > MAX_ROWS else "")
    return bars("block.ts_team", f"{scope}工时填报进度", rows, sub=sub, more="填报进度", to=_board(ctx), hint=FILL_HINT)


def _project_hours(entries):
    """工时按项目汇总：[(项目名, 小时)]，从多到少。"""
    totals = {}
    for row in entries:
        key = row.get("project") or row.get("project_code") or ""
        name, hours = totals.get(key, (row.get("project_name") or row.get("project_code") or key or "未命名项目", 0))
        totals[key] = (name, hours + float(row.get("hours") or 0))
    return sorted(totals.values(), key=lambda item: (-item[1], item[0]))


@provider("block.ts_projects", "block", visible=_fill_visible, title="本部门工时按项目")
def block_ts_projects(ctx):
    data = _fill(ctx, "team", "all")
    if not data:
        return None
    projects = _project_hours(ctx.memo("ts.entries", lambda: _load_entries(ctx.period))["entries"])
    if not projects:
        return None
    top = projects[:5]
    rest = projects[5:]
    if rest:
        top.append((f"其他 {len(rest)} 个", sum(hours for _, hours in rest)))
    biggest = max(hours for _, hours in top) or 1
    rows = [bar_row(name, _n(hours), hours / biggest * 100) for name, hours in top]
    scope = _scope_label(data["kind"])
    return bars("block.ts_projects", f"{scope}工时按项目", rows, sub=f"{_month_word(ctx)} · 小时", more="填报进度", to=_board(ctx),
                hint="按月度工时记录里的项目汇总（含旧版按日填报的记录）；范围和填报进度一致。")


# ---------------------------------------------------------------- 部门（出勤 / 加班 / 请假 / 在职）
def _dept_visible(ctx):
    """和 overview_entry.hr_scope 同一条规则；而且得有所属部门，没有部门就不知道看谁。"""
    return bool(ctx.department) and (ctx.can(*DEPT_ROLES) or ctx.holds(*DEPT_POSITIONS))


DEPT_HINT = "按员工档案的所属部门统计；工时填报里的“本部门”按汇报关系（自己 + 直接下属），两处范围可能不同。"


def _absence_window(ctx):
    """今天起 14 天内本部门已批准的请假 / 调休，按人整理：{员工: (姓名, [有请假的日期])}。"""
    def build():
        today = date.fromisoformat(ctx.today)
        end = today + timedelta(days=AWAY_WINDOW_DAYS - 1)
        people = {}
        for row in _load_absence_rows(ctx.department, today, end):
            days = sorted(day for day, hours in att.expand_days(row) if today <= day <= end and hours > 0)
            if not days:
                continue
            name, found = people.setdefault(row["employee"], (row.get("employee_name") or row["employee"], []))
            found.extend(days)
        return {key: (name, sorted(set(days))) for key, (name, days) in people.items()}
    return ctx.memo("dept.absence", build)


@provider("dept.away2w", "kpi", visible=_dept_visible, title="两周内不在岗")
def dept_away2w(ctx):
    people = _absence_window(ctx)
    firsts = sorted(days[0] for _, days in people.values())
    shown = " · ".join(_md(day) for day in firsts[:3]) + (" …" if len(firsts) > 3 else "")
    return kpi("dept.away2w", "两周内不在岗", len(people), "人", shown or "两周内没有人请假或调休",
               to=target("attendance.home"),
               hint=f"本部门从今天起 {AWAY_WINDOW_DAYS} 天内有已批准的请假 / 调休的人数，日期是每个人最早的一天。" + DEPT_HINT)


@provider("alert.dept_attendance", "alert", visible=_dept_visible)
def alert_dept_attendance(ctx):
    tomorrow = date.fromisoformat(ctx.today) + timedelta(days=1)
    names = [name for name, days in _absence_window(ctx).values() if tomorrow in days]
    if len(names) < 2:
        return None
    sub = "、".join(sorted(names)[:3]) + ("等" if len(names) > 3 else "")
    return alert("alert.dept_attendance", "info", f"{_md(tomorrow)} 有 {len(names)} 人请假或调休", sub, "考勤中心", target("attendance.home"))


@provider("dept.active", "kpi", visible=_dept_visible, title="本部门在职")
def dept_active(ctx):
    staff = ctx.memo("dept.staff", lambda: _load_department_staff(ctx.department))
    joined = sum(1 for row in staff if str(row.get("date_of_joining") or "")[:7] == ctx.period)
    to = target("personnel.list", status="active") if ctx.can(*HR_ROLES) or ctx.holds(*DEPT_POSITIONS) else None
    return kpi("dept.active", "本部门在职", len(staff), "人", f"本月入职 {joined}" if joined else "本月无人入职", to=to,
               hint="员工档案里所属部门是你的部门、状态为在职的人数；本月入职按所选期间。" + DEPT_HINT)


def _attendance_rows(ctx, year, month):
    return ctx.memo(f"dept.att.{year}-{month}", lambda: _load_attendance_rows(year, month, ctx.department))


def _hours(rows, request_type):
    return sum(float(row.get("duration_hours") or 0) for row in rows if row.get("request_type") == request_type)


@provider("dept.overtime", "kpi", visible=_dept_visible, title="本月加班")
def dept_overtime(ctx):
    year, month = int(ctx.period[:4]), int(ctx.period[5:])
    current = _hours(_attendance_rows(ctx, year, month), att.REQUEST_OVERTIME)
    previous = _hours(_attendance_rows(ctx, *_prev_period(ctx.period)), att.REQUEST_OVERTIME)
    if previous:
        change = (current - previous) / previous * 100
        sub = f"{'▲' if change >= 0 else '▼'} {abs(change):.0f}% 较上月"
    else:
        sub = "上月没有加班" if current else "本月没有加班"
    return kpi("dept.overtime", f"{_month_word(ctx)}加班", _n(current), "小时", sub, to=target("attendance.home"),
               hint="本部门已批准的加班小时数（跨月申请按天拆到各月）。" + DEPT_HINT)


@provider("dept.leave", "kpi", visible=_dept_visible, title="本月请假")
def dept_leave(ctx):
    year, month = int(ctx.period[:4]), int(ctx.period[5:])
    by_type = {}
    for row in _attendance_rows(ctx, year, month):
        if row.get("request_type") == att.REQUEST_LEAVE:
            label = row.get("leave_type") or "未填类别"
            by_type[label] = by_type.get(label, 0) + float(row.get("duration_hours") or 0)
    total = sum(by_type.values())
    top = sorted(by_type.items(), key=lambda item: -item[1])[:2]
    sub = " · ".join(f"{label} {_n(hours / HOURS_PER_DAY)}" for label, hours in top) or "本月没有请假"
    return kpi("dept.leave", f"{_month_word(ctx)}请假", _n(total / HOURS_PER_DAY), "天", sub, to=target("attendance.home"),
               hint="本部门已批准的请假天数（小时 ÷ 8，不含调休；跨月申请按天拆到各月）。" + DEPT_HINT)


@provider("dept.projects", "kpi", visible=_fill_visible, title="工时投到的项目")
def dept_projects(ctx):
    data = _fill(ctx, "team", "all")
    if not data:
        return None
    projects = _project_hours(ctx.memo("ts.entries", lambda: _load_entries(ctx.period))["entries"])
    return kpi("dept.projects", "工时投到的项目", len(projects), "个",
               f"最多的是 {projects[0][0]}" if projects else "本月还没有工时记录", to=_board(ctx),
               hint=f"{_scope_label(data['kind'])}填报名单里的人，本月工时投到的不同项目数。")
