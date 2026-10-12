"""看板：研发工时填报进度。

数据来源和权限，都跟着现有接口走，不放宽：
- 工时填报：`monthly_timesheet_entry.get_fill_progress(period)`。它自己按身份限定范围——HR / 管理员 / 财务看全公司（kind=all），
  部门主管看自己的团队（kind=team，汇报关系向下的研发人员，和 `team_scope` 一致），纯员工拿到空名单。
  所以这里用返回的 kind 决定标签（"本部门" 还是 "全公司"），不另外猜范围。
团队的出勤 / 请假 / 加班在 `dashboard/team.py`。
"""
from __future__ import annotations

from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, col_row, cols, kpi, provider, target,
)

# get_fill_progress 里看全公司的角色；部门主管角色看本部门。其他人（纯员工）拿到的是空名单。
FILL_ALL_ROLES = ("System Manager", "HR User", "HR Manager", "Accounts User")
FILL_ROLES = (*FILL_ALL_ROLES, "Department Manager")
MAX_ROWS = 8
TREND_MONTHS = 6
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
               hint=(f"{scope}的工时填报名单。" + ("范围按汇报关系：自己 + 汇报关系向下（直接和间接下属）里的研发人员，和考勤中心的团队一致。" if data["kind"] == "team" else "")) + FILL_HINT)


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


@provider("dept.projects", "kpi", visible=_fill_visible, title="工时投到的项目")
def dept_projects(ctx):
    data = _fill(ctx, "team", "all")
    if not data:
        return None
    projects = _project_hours(ctx.memo("ts.entries", lambda: _load_entries(ctx.period))["entries"])
    return kpi("dept.projects", "工时投到的项目", len(projects), "个",
               f"最多的是 {projects[0][0]}" if projects else "本月还没有工时记录", to=_board(ctx),
               hint=f"{_scope_label(data['kind'])}填报名单里的人，本月工时投到的不同项目数。")


def _trend_periods(period, count=TREND_MONTHS):
    """以 period 结尾的最近 count 个月（旧的在前）：["2026-05", ..., "2026-10"]。"""
    year, month = int(period[:4]), int(period[5:])
    result = []
    for _ in range(count):
        result.append(f"{year:04d}-{month:02d}")
        year, month = _prev_period(f"{year:04d}-{month:02d}")
    return list(reversed(result))


@provider("block.ts_trend", "block", visible=_fill_visible, title="近 6 个月填报率")
def block_ts_trend(ctx):
    """团队每个月“已填满”的比例（只给部门主管：团队人数少，逐月取一次进度不贵；全公司不做）。"""
    data = _fill(ctx, "team")
    if not data:
        return None
    rows = []
    periods = _trend_periods(ctx.period)
    for period in periods:
        month_data = data if period == ctx.period else ctx.memo(f"ts.fill.{period}", lambda p=period: _load_fill(p))
        total = (month_data.get("summary") or {}).get("total") or 0
        rate = float(month_data["summary"]["rate"]) if total and month_data.get("kind") == "team" else 0.0
        rows.append(col_row(f"{int(period[5:])}月", f"{rate:g}%", rate, period == ctx.period))
    if not any(float(row["value"].rstrip("%")) for row in rows):
        return None
    return cols("block.ts_trend", "近 6 个月填报率", rows, sub="团队 · 已填满的人数占比", more="填报进度", to=_board(ctx),
                hint="每个月团队工时填报名单里“已填满”的比例；范围按汇报关系向下的研发人员。" + FILL_HINT)
