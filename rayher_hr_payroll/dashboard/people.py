"""看板里的人事、薪酬与社保、宿舍。

数据口径尽量和现有页面一致，不另起一套：
- 员工数字（在职、入职离职、到期提醒、档案、研发类型）和前端 `lib/personnelView.js` 同一口径：60 天窗口、
  第二次合同到期晚于第一次视为已续签、离职日当天仍算在职、研发组取 `DEPARTMENT_GROUP_BY_NAME`。
- 工资条看 Salary Slip（草稿 + 已提交），应有工资条的人和薪酬计算页 `get_payroll_rows` 一样。
- 社保公积金公司承担部分只算已确认的记录（`payroll_bridge.period_company_contributions`）。
- 宿舍整块直接用 `dormitory_board.get_dormitory_board`，请假只借 `overview_entry` 里便宜的纯函数
  （不碰它逐人算年假余额的那一段）。

个人信息永远不进块：只给人数、进度、汇总金额；名单只给姓名 + 日期。
权限：`visible` 看真实权限。员工表类的块 HR 角色或副总/总经理岗位可看（和 `overview_entry.hr_scope` 一致）；
工资、社保、公积金、宿舍的底层接口只认 HR 角色，这里同样只认 HR 角色；社保公积金再叠加
`_guards.HR_SENSITIVE_HIDDEN_USERS`（被屏蔽的账号整块不返回）。
"""
from __future__ import annotations

import calendar
import re
from collections import Counter
from datetime import date, datetime

import frappe

from rayher_hr_payroll.api import _guards
from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, kpi, list_row, listing, money_wan, provider, stack, stack_row, target,
)
from rayher_hr_payroll.department_structure import DEPARTMENT_GROUP_BY_NAME

HR_ROLES = ("System Manager", "HR User", "HR Manager")
LEADER_POSITIONS = ("vice_manager", "general_manager")

EXPIRY_DAYS = 60            # 和 personnelView.EXPIRY_WINDOW_DAYS 一致
PROBATION_ALERT_DAYS = 60   # 和指标卡、员工信息页的「60 天内到期」同一个窗口；剩 7 天内标红
URGENT_DAYS = 7
LEASE_DAYS = 60             # 和宿舍看板 LEASE_WARNING_DAYS 一致
RD_FILL_TYPES = ("全时研发", "非全时研发", "研发辅助")   # 会出现在工时填报里的研发类型
RD_GROUP = "研发"
ARCHIVE_STATUSES = ("待完善", "待确认", "已归档")
NO_DEPARTMENT = "未分配部门"
TOP_N = 5
LIST_LIMIT = 5

BLUE, GREEN, AMBER, GREY = "#4F6BDC", "#2F855A", "#E89A3C", "#9AA0AA"


# ---------------------------------------------------------------- 权限
def _hr(ctx):
    return ctx.can(*HR_ROLES)


def _hr_view(ctx):
    return _hr(ctx) or ctx.holds(*LEADER_POSITIONS)


def _sensitive_hidden(ctx):
    return str(ctx.user or "").strip().lower() in _guards.HR_SENSITIVE_HIDDEN_USERS


def _hr_si(ctx):
    return _hr(ctx) and not _sensitive_hidden(ctx)


# ---------------------------------------------------------------- 小工具
def _d(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _md(day):
    return f"{day.month:02d}-{day.day:02d}"


def _month_bounds(period):
    year, month = int(period[:4]), int(period[5:7])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _shift_month(period, months):
    year, month = int(period[:4]), int(period[5:7])
    index = year * 12 + month - 1 + months
    return "%04d-%02d" % (index // 12, index % 12 + 1)


def _dept_label(value):
    """Department 的名字带公司后缀（"研发软件部 - RAY"），展示和分组都用去掉后缀的名字，和前端 displayDepartment 一致。"""
    return re.sub(r"\s*-\s*(RAY|SHGL)$", "", str(value or "").strip(), flags=re.I)


def _wan(amount):
    return f"{float(amount or 0) / 10000:,.1f}"


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _pct(part, whole):
    return (part / whole * 100) if whole else 0


def _top_with_other(items, limit=TOP_N):
    """[(label, value)] → 按数值从大到小取前 limit 个，其余合并成「其他」。"""
    ordered = sorted(items, key=lambda item: (-item[1], item[0]))
    top, rest = ordered[:limit], ordered[limit:]
    if rest:
        top.append(("其他", sum(value for _, value in rest)))
    return top


def _is_current_month(ctx):
    return ctx.period == ctx.today[:7]


# ---------------------------------------------------------------- 员工表：纯函数
def is_left(row, today):
    """与 personnelView.isLeft 一致：状态是 Left，或离职日已过（离职日当天仍在职）。"""
    if str(row.get("status") or "") == "Left":
        return True
    relieving = _d(row.get("relieving_date"))
    return relieving is not None and relieving < today


def archive_status_of(row):
    value = row.get("archive_status")
    return value if value in ARCHIVE_STATUSES else "待完善"


def expiry_items(row, today):
    """60 天内到期的试用期 / 合同：[(种类, 日期, 还剩几天)]。第二次合同到期晚于第一次的，第一次视为已续签。"""
    items = []
    probation = _d(row.get("probation_end_date"))
    if probation is not None and 0 <= (probation - today).days <= EXPIRY_DAYS:
        items.append(("试用期", probation, (probation - today).days))
    first, second = _d(row.get("first_contract_end_date")), _d(row.get("second_contract_end_date"))
    if first is not None and second is not None and (second - first).days > 0:
        first = None
    ends = sorted(day for day in (first, second) if day is not None and 0 <= (day - today).days <= EXPIRY_DAYS)
    if ends:
        items.append(("合同", ends[0], (ends[0] - today).days))
    return items


def summarize_employees(rows, today, period):
    """Employee 表一次聚合。today 是 date，period 是 "YYYY-MM"。"""
    out = {
        "active": 0, "rd": 0, "other": 0, "rd_gap": 0, "joined": 0, "new_joiners": [],
        "left_month": 0, "left_effective": 0, "left_pending": 0, "on_probation": 0,
        "file_pending": 0, "file_confirm": 0, "expiring": [], "dept_counts": Counter(),
    }
    for row in rows:
        joined = _d(row.get("date_of_joining"))
        relieving = _d(row.get("relieving_date"))
        left = is_left(row, today)
        if joined is not None and joined.strftime("%Y-%m") == period:
            out["joined"] += 1
            if not left:
                out["new_joiners"].append(row.get("name"))
        if relieving is not None and relieving.strftime("%Y-%m") == period:
            out["left_month"] += 1
            out["left_effective" if left else "left_pending"] += 1
        if left:
            continue
        out["active"] += 1
        rd_type = row.get("rd_personnel_type")
        out["rd" if rd_type in RD_FILL_TYPES else "other"] += 1
        label = _dept_label(row.get("department"))
        out["dept_counts"][label or NO_DEPARTMENT] += 1
        if label and DEPARTMENT_GROUP_BY_NAME.get(label) == RD_GROUP and not str(rd_type or "").strip():
            out["rd_gap"] += 1
        probation = _d(row.get("probation_end_date"))
        if probation is not None and probation >= today:
            out["on_probation"] += 1
        archive = archive_status_of(row)
        if archive == "待完善":
            out["file_pending"] += 1
        elif archive == "待确认":
            out["file_confirm"] += 1
        items = expiry_items(row, today)
        if items:
            out["expiring"].append({"name": row.get("employee_name") or row.get("name"), "items": items})
    out["expiring"].sort(key=lambda person: min(item[2] for item in person["items"]))
    return out


# ---------------------------------------------------------------- 工资条：纯函数
def _dedupe_slips(slips):
    """每人一张：已提交优先（和薪酬计算页按员工取工资条的做法一致）。"""
    chosen = {}
    for slip in slips:
        employee = slip.get("employee")
        if not employee:
            continue
        old = chosen.get(employee)
        if old is None or int(slip.get("docstatus") or 0) > int(old.get("docstatus") or 0):
            chosen[employee] = slip
    return chosen


def summarize_payroll(employees, slips, period):
    """本月应有工资条的人 = 入职日不晚于月末、且没在月初之前离职（与 hr_payroll_entry._period_employee_filters 一致）。"""
    start, end = _month_bounds(period)
    expected = set()
    dept_of = {}
    for row in employees:
        dept_of[row.get("name")] = _dept_label(row.get("department"))
        joined, relieving = _d(row.get("date_of_joining")), _d(row.get("relieving_date"))
        if joined is not None and joined <= end and (relieving is None or relieving >= start):
            expected.add(row.get("name"))
    chosen = _dedupe_slips(slips)
    population = expected | set(chosen)      # 页面也会把有工资条但不在名单里的人补进来
    submitted = sum(1 for slip in chosen.values() if int(slip.get("docstatus") or 0) == 1)
    by_dept = Counter()
    for employee, slip in chosen.items():
        by_dept[_dept_label(slip.get("department")) or dept_of.get(employee) or NO_DEPARTMENT] += _num(slip.get("gross_pay"))
    return {
        "population": population, "expected": len(population), "generated": len(chosen),
        "submitted": submitted, "draft": len(chosen) - submitted, "missing": len(population) - len(chosen),
        "gross": sum(_num(slip.get("gross_pay")) for slip in chosen.values()), "by_dept": by_dept,
    }


# ---------------------------------------------------------------- 取数（测试里替换）
EMPLOYEE_FIELDS = [
    "name", "employee_name", "status", "department", "date_of_joining", "relieving_date",
    "probation_end_date", "first_contract_end_date", "second_contract_end_date",
    "archive_status", "rd_personnel_type",
]


def _fetch_employees(ctx):
    return frappe.get_all("Employee", fields=EMPLOYEE_FIELDS, limit_page_length=0)


def _fetch_slips(period):
    start, end = _month_bounds(period)
    return frappe.get_all(
        "Salary Slip", filters={"start_date": start, "end_date": end, "docstatus": ["<", 2]},
        fields=["employee", "docstatus", "gross_pay", "department"], limit_page_length=0,
    )


def _fetch_company_contributions(ctx):
    from rayher_hr_payroll import payroll_bridge

    data = payroll_bridge.period_company_contributions(ctx.period)
    return {"si": sum(_num(item.get("si")) for item in data.values()), "hf": sum(_num(item.get("hf")) for item in data.values())}


def _fetch_contribution_records(ctx):
    """本月已有社保 / 公积金记录的人，和其中已确认的人（只要员工号，不取金额）。"""
    out = {}
    for key, doctype in (("si", "Employee Social Insurance"), ("hf", "Employee Housing Fund")):
        rows = frappe.get_all(doctype, filters={"period": ctx.period}, fields=["employee", "status"], limit_page_length=0)
        out[key] = {
            "any": {row.get("employee") for row in rows if row.get("employee")},
            "confirmed": {row.get("employee") for row in rows if row.get("employee") and row.get("status") == "Confirmed"},
        }
    return out


def _fetch_workbench(ctx):
    from rayher_hr_payroll.api import social_insurance_import_entry

    return social_insurance_import_entry.get_social_workbench(ctx.period)


def _fetch_dorm(ctx):
    from rayher_hr_payroll.api import dormitory_board

    return dormitory_board.get_dormitory_board(ctx.period)


def _fetch_away(ctx):
    from rayher_hr_payroll.api import overview_entry

    return overview_entry._away_today(None)


def _fetch_leave_stats(ctx):
    from rayher_hr_payroll.api import overview_entry

    rows = overview_entry._attendance_rows([(int(ctx.period[:4]), int(ctx.period[5:7]))], None)
    return overview_entry.leave_stats(rows)


# ---------------------------------------------------------------- 同一请求内共用
def _employees(ctx):
    return ctx.memo("people.employees", lambda: _fetch_employees(ctx))


def _facts(ctx):
    today = _d(ctx.today)
    return ctx.memo("people.facts", lambda: summarize_employees(_employees(ctx), today, ctx.period))


def _slips(ctx, period):
    return ctx.memo(f"people.slips:{period}", lambda: _fetch_slips(period))


def _payroll(ctx):
    return ctx.memo("people.payroll", lambda: summarize_payroll(_employees(ctx), _slips(ctx, ctx.period), ctx.period))


def _contributions(ctx):
    return ctx.memo("people.contributions", lambda: _fetch_company_contributions(ctx))


def _records(ctx):
    return ctx.memo("people.records", lambda: _fetch_contribution_records(ctx))


def _workbench(ctx):
    return ctx.memo("people.workbench", lambda: _fetch_workbench(ctx))


def _dorm(ctx):
    return ctx.memo("people.dorm", lambda: _fetch_dorm(ctx))


def _away(ctx):
    return ctx.memo("people.away", lambda: _fetch_away(ctx))


def _leave_stats(ctx):
    return ctx.memo("people.leave_stats", lambda: _fetch_leave_stats(ctx))


def _social_pending_rows(ctx):
    return int(((_workbench(ctx) or {}).get("dashboard") or {}).get("pending_rows") or 0)


def _new_joiners_without_records(ctx):
    """本月新入职、社保或公积金还没有任何记录的人数（没记录就进不了工资条）。"""
    records = _records(ctx)
    return sum(1 for employee in _facts(ctx)["new_joiners"]
               if employee not in records["si"]["any"] or employee not in records["hf"]["any"])


def _month_label(ctx):
    return f"{int(ctx.period[5:7])} 月"


# ================================================================ 人事：指标卡
@provider("hr.active", "kpi", visible=_hr_view, title="在职员工")
def hr_active(ctx):
    facts = _facts(ctx)
    return kpi("hr.active", "在职员工", facts["active"], "人", f"研发 {facts['rd']} · 其他 {facts['other']}",
               to=target("personnel.list", status="active"),
               hint="在职 = 状态不是离职、且离职日还没过（离职日当天仍算在职）。研发 = 研发人员类型是全时 / 非全时 / 辅助的人；"
                    "工时填报率里的「填工时」人数是工时填报名单（排除免填账号），两个数不一定相等。")


@provider("hr.joined_left", "kpi", visible=_hr_view, title="本月入职 / 离职")
def hr_joined_left(ctx):
    facts = _facts(ctx)
    # 点进去的员工页只会按“当前月”筛，所以看别的月份时不给跳转（数字对不上就不如不跳）。
    to = target("personnel.joined") if _is_current_month(ctx) else None
    return kpi("hr.joined_left", "本月入职", len(facts["new_joiners"]), "人",
               f"试用期中 {facts['on_probation']} 人 · 本月离职 {facts['left_effective']} 人", to=to,
               hint="入职 = 入职日在所选月份、现在还在职的人。试用期中 = 在职且试用期结束日不早于今天。"
                    "点进去是员工页的「本月入职」，人数和这里一致。")


@provider("hr.left_month", "kpi", visible=_hr_view, title="本月离职")
def hr_left_month(ctx):
    facts = _facts(ctx)
    to = target("personnel.left_month") if _is_current_month(ctx) else None
    return kpi("hr.left_month", "本月离职", facts["left_effective"], "人",
               f"另有 {facts['left_pending']} 人离职日在本月、还没到" if facts["left_pending"] else "离职日在本月、已经离职的人",
               to=to,
               hint="离职日在所选月份、且已经离职的人（离职日当天仍算在职）；离职日还没到的叫「待离职」，不算在这里，仍在在职名单里。"
                    "点进去是员工页的「已离职 + 本月离职」，人数和这里一致。")


@provider("hr.away_today", "kpi", visible=_hr_view, title="今天不在岗")
def hr_away_today(ctx):
    away = _away(ctx)
    parts = [f"{item['label']} {item['count']}" for item in (away.get("by_type") or [])[:3]]
    return kpi("hr.away_today", "今天不在岗", int(away.get("count") or 0), "人", " · ".join(parts),
               to=target("attendance.today"),
               hint="今天在已批准的请假或调休里的人数（按人去重）。")


@provider("hr.expiring", "kpi", visible=_hr_view, title="60 天内到期")
def hr_expiring(ctx):
    people = _facts(ctx)["expiring"]
    probation = sum(1 for person in people if any(item[0] == "试用期" for item in person["items"]))
    contract = sum(1 for person in people if any(item[0] == "合同" for item in person["items"]))
    soonest = min((item[2] for person in people for item in person["items"]), default=None)
    tone = "bad" if soonest is not None and soonest <= URGENT_DAYS else ("hot" if people else "")
    return kpi("hr.expiring", f"{EXPIRY_DAYS} 天内到期", len(people), "人", f"合同 {contract} · 试用期 {probation}", tone,
               to=target("personnel.expiring"),
               hint="在职员工里试用期或合同 60 天内到期的人数（一个人两样都到期只算一人）。合同：第二次合同到期晚于第一次的，第一次视为已续签。")


@provider("hr.file_pending", "kpi", visible=_hr_view, title="档案待完善")
def hr_file_pending(ctx):
    facts = _facts(ctx)
    return kpi("hr.file_pending", "档案待完善", facts["file_pending"], "人",
               f"待确认 {facts['file_confirm']} · 研发类型未设置 {facts['rd_gap']}",
               "warn" if facts["file_pending"] else "", to=target("personnel.file"),
               hint="在职员工里档案状态是「待完善」的人数；没填档案状态的也算待完善。")


@provider("hr.rd_gap", "kpi", visible=_hr_view, title="研发类型未设置")
def hr_rd_gap(ctx):
    count = _facts(ctx)["rd_gap"]
    return kpi("hr.rd_gap", "研发类型未设置", count, "人", "不会出现在工时填报里" if count else "", "warn" if count else "",
               to=target("personnel.rd_gap"),
               hint="在职、部门属于研发组，但研发人员类型还没设置的人。")


# ================================================================ 人事：提醒
def _names_title(people, suffix):
    first = people[0]["name"]
    return f"{first}等 {len(people)} 人{suffix}" if len(people) > 1 else first


def _expiry_people(ctx, kind, within):
    out = []
    for person in _facts(ctx)["expiring"]:
        hit = [item for item in person["items"] if item[0] == kind and item[2] <= within]
        if hit:
            out.append({"name": person["name"], "date": hit[0][1], "gap": hit[0][2]})
    out.sort(key=lambda item: item["gap"])
    return out


@provider("alert.probation", "alert", visible=_hr_view)
def alert_probation(ctx):
    people = _expiry_people(ctx, "试用期", PROBATION_ALERT_DAYS)
    if not people:
        return None
    first = people[0]
    tone = "bad" if first["gap"] <= URGENT_DAYS else "warn"
    if len(people) == 1:
        left = f"，只剩 {first['gap']} 天" if first["gap"] else "（今天）"
        return alert("alert.probation", tone, f"{first['name']} 试用期 {_md(first['date'])} 到期{left}", "需要转正评估",
                     "员工信息", target("personnel.expiring"))
    return alert("alert.probation", tone, _names_title(people, f"试用期 {PROBATION_ALERT_DAYS} 天内到期"),
                 f"最早 {_md(first['date'])} · 需要转正评估", "员工信息", target("personnel.expiring"))


@provider("alert.contract", "alert", visible=_hr_view)
def alert_contract(ctx):
    people = _expiry_people(ctx, "合同", EXPIRY_DAYS)
    if not people:
        return None
    first = people[0]
    return alert("alert.contract", "bad" if first["gap"] <= URGENT_DAYS else "warn",
                 _names_title(people, f"合同 {EXPIRY_DAYS} 天内到期"), f"最早 {_md(first['date'])}",
                 "员工信息", target("personnel.expiring"))


@provider("alert.rd_gap", "alert", visible=_hr_view)
def alert_rd_gap(ctx):
    count = _facts(ctx)["rd_gap"]
    if not count:
        return None
    return alert("alert.rd_gap", "info", f"研发部门有 {count} 人没设研发类型", "不会出现在工时填报里", "员工信息",
                 target("personnel.rd_gap"))


@provider("alert.payroll_draft", "alert", visible=_hr)
def alert_payroll_draft(ctx):
    draft = _payroll(ctx)["draft"]
    if not draft:
        return None
    return alert("alert.payroll_draft", "warn", f"{draft} 人工资条仍是草稿", "复核后提交", "薪酬计算",
                 target("payroll", period=ctx.period, status="draft"))


# ================================================================ 薪酬与社保：指标卡
@provider("hr.payroll", "kpi", visible=_hr, title="工资条")
def hr_payroll(ctx):
    payroll = _payroll(ctx)
    draft = payroll["draft"]
    return kpi("hr.payroll", "工资条", f"{payroll['generated']} / {payroll['expected']}", "人",
               f"待复核 {draft}" if draft else "", "hot" if draft else "",
               to=target("payroll", period=ctx.period),
               hint="已生成 / 本月应有工资条的人（入职日不晚于月末、且没在月初之前离职，与薪酬计算页一致）。待复核 = 草稿工资条。")


@provider("hr.pay_total", "kpi", visible=_hr, title="本月应发合计")
def hr_pay_total(ctx):
    payroll = _payroll(ctx)
    previous = sum(_num(slip.get("gross_pay")) for slip in _dedupe_slips(_slips(ctx, _shift_month(ctx.period, -1))).values())
    value, unit = money_wan(payroll["gross"])
    if not payroll["generated"]:
        sub = "这个月还没有工资条"
    elif not previous:
        sub = "上月没有工资条"
    else:
        change = (payroll["gross"] - previous) / previous * 100
        sub = "与上月持平" if round(change, 1) == 0 else f"{'▲' if change > 0 else '▼'} {abs(change):.1f}% 较上月"
    return kpi("hr.pay_total", "本月应发合计", value, unit, sub, to=target("payroll", period=ctx.period),
               hint="所选月份工资条的应发合计，含草稿；只给汇总，不含个人金额。")


@provider("hr.pay_si", "kpi", visible=_hr_si, title="社保（公司承担）")
def hr_pay_si(ctx):
    value, unit = money_wan(_contributions(ctx)["si"])
    pending = _social_pending_rows(ctx)
    return kpi("hr.pay_si", "社保（公司承担）", value, unit, f"待确认 {pending} 行" if pending else "", "hot" if pending else "",
               to=target("social", period=ctx.period),
               hint="所选月份单位承担的社保，只算已确认的记录。待确认 = 社保导入批次里还没处理的明细行数。")


@provider("hr.pay_hf", "kpi", visible=_hr_si, title="公积金（公司承担）")
def hr_pay_hf(ctx):
    value, unit = money_wan(_contributions(ctx)["hf"])
    confirmed = len(_records(ctx)["hf"]["confirmed"] & _payroll(ctx)["population"])
    return kpi("hr.pay_hf", "公积金（公司承担）", value, unit, f"已核对 {confirmed} / {_payroll(ctx)['expected']} 人",
               to=target("housing", period=ctx.period),
               hint="所选月份单位承担的公积金，只算已确认的记录。已核对 = 本月应有工资条的人里公积金记录已确认的人数。")


@provider("hr.social_pending", "kpi", visible=_hr_si, title="社保公积金待处理")
def hr_social_pending(ctx):
    pending, joiners = _social_pending_rows(ctx), _new_joiners_without_records(ctx)
    total = pending + joiners
    return kpi("hr.social_pending", "社保公积金待处理", total, "项", f"社保待确认 {pending} 行 · 新入职待开通 {joiners} 人",
               "hot" if total else "", to=target("social", period=ctx.period),
               hint="社保待确认 = 社保导入批次里待确认的明细行数；新入职待开通 = 所选月份入职、社保或公积金还没有记录的人数。")


# ================================================================ 宿舍：指标卡与提醒
def _lease_rooms(board):
    return [room for room in board.get("rooms") or [] if room.get("lease_days_left") is not None and room["lease_days_left"] <= LEASE_DAYS]


def _unregistered_rooms(board):
    return [room for room in board.get("rooms") or [] if room.get("status") == "入住" and not room.get("registered")]


@provider("hr.dorm_rate", "kpi", visible=_hr, title="宿舍入住率")
def hr_dorm_rate(ctx):
    occupancy = _dorm(ctx)["occupancy"]
    return kpi("hr.dorm_rate", "宿舍入住率", round((occupancy.get("rate") or 0) * 100), "%",
               f"{occupancy.get('入住', 0)} / {occupancy.get('residential', 0)} 间", to=target("dorm.board"),
               hint="入住 ÷（入住 + 空置）；客房、午休室不计入。")


@provider("hr.dorm_vacant", "kpi", visible=_hr, title="空置房租")
def hr_dorm_vacant(ctx):
    occupancy = _dorm(ctx)["occupancy"]
    value, unit = money_wan(occupancy.get("vacant_rent"))
    vacant = occupancy.get("空置", 0)
    return kpi("hr.dorm_vacant", "空置房租（每月）", value, unit, f"{vacant} 间空置", "hot" if vacant else "",
               to=target("dorm.board"), hint="空置房间的月租合计，公司白付的房租。")


@provider("hr.dorm_lease", "kpi", visible=_hr, title="租约 60 天内到期")
def hr_dorm_lease(ctx):
    alert_ = _dorm(ctx).get("lease_alert") or {}
    count, expired = int(alert_.get("count") or 0), int(alert_.get("expired_count") or 0)
    parts = [f"最早 {alert_['earliest_date'][5:]}"] if alert_.get("earliest_date") else []
    if expired:
        parts.append(f"已过期 {expired} 间")
    return kpi("hr.dorm_lease", f"租约 {LEASE_DAYS} 天内到期", count, "间", " · ".join(parts),
               "hot" if count or expired else "", to=target("dorm.lease"),
               hint="房间租约结束日在今天起 60 天内的间数；已经过期的另外标出。")


@provider("hr.dorm_leaver", "kpi", visible=_hr, title="已离职仍占房")
def hr_dorm_leaver(ctx):
    count = len(_dorm(ctx).get("leavers_in_rooms") or [])
    return kpi("hr.dorm_leaver", "已离职仍占房", count, "人", "需要清退" if count else "", "bad" if count else "",
               to=target("dorm.leaver"), hint="已离职员工的住宿登记还没取消，房间仍算被他占着。")


@provider("alert.dorm_lease", "alert", visible=_hr)
def alert_dorm_lease(ctx):
    lease = _dorm(ctx).get("lease_alert")
    if not lease:
        return None
    count, expired = int(lease.get("count") or 0), int(lease.get("expired_count") or 0)
    title = f"{count} 间租约 {LEASE_DAYS} 天内到期" if count else f"{expired} 间租约已过期"
    if count and expired:
        title += f"，另有 {expired} 间已过期"
    days_left = lease.get("days_left")
    urgent = bool(expired) or (days_left is not None and days_left <= URGENT_DAYS)
    sub = f"最早 {lease['earliest_date'][5:]}" if lease.get("earliest_date") else ""
    return alert("alert.dorm_lease", "bad" if urgent else "warn", title, sub, "宿舍", target("dorm.lease"))


@provider("alert.dorm_leaver", "alert", visible=_hr)
def alert_dorm_leaver(ctx):
    leavers = _dorm(ctx).get("leavers_in_rooms") or []
    if not leavers:
        return None
    rooms = "、".join(str(item.get("room_no")) for item in leavers[:3]) + ("等" if len(leavers) > 3 else "")
    return alert("alert.dorm_leaver", "warn", f"{len(leavers)} 位已离职员工仍占房", f"房间 {rooms}", "宿舍", target("dorm.leaver"))


@provider("alert.dorm_register", "alert", visible=_hr)
def alert_dorm_register(ctx):
    rooms = _unregistered_rooms(_dorm(ctx))
    if not rooms:
        return None
    return alert("alert.dorm_register", "info", f"{_month_label(ctx)}宿舍费用还有 {len(rooms)} 间没登记", "分摊前需要登记完",
                 "月度登记", target("dorm.monthly", period=ctx.period, status="open"))


# ================================================================ 人事：块
@provider("block.dept_headcount", "block", visible=_hr_view, title="部门人数")
def block_dept_headcount(ctx):
    items = _top_with_other(list(_facts(ctx)["dept_counts"].items()))
    top = items[0][1] if items else 0
    rows = [bar_row(label, value, _pct(value, top)) for label, value in items]
    return bars("block.dept_headcount", "部门人数", rows, "在职 · 人", to=target("personnel.list", status="active"),
                hint="按员工档案里的部门统计在职人数；「其他」= 第 6 名及以后的部门合计。")


@provider("block.leave_types", "block", visible=_hr_view, title="请假类型")
def block_leave_types(ctx):
    types = (_leave_stats(ctx).get("by_type") or [])[:6]
    top = types[0]["days"] if types else 0
    rows = [bar_row(item["label"], f"{item['days']:g}", _pct(item["days"], top)) for item in types]
    return bars("block.leave_types", "请假类型", rows, f"{_month_label(ctx)} · 天" if rows else f"{_month_label(ctx)}没有已批准的请假",
                to=target("attendance.all"),
                hint="所选月份已批准的请假和调休，按类型合计的天数（小时 ÷ 8）；跨月的申请只算落在这个月里的天。")


@provider("block.expiring_list", "block", visible=_hr_view, title="即将到期")
def block_expiring_list(ctx):
    people = _facts(ctx)["expiring"]
    rows = []
    for person in people[:LIST_LIMIT]:
        kind, day, gap = min(person["items"], key=lambda item: item[2])
        rows.append(list_row(person["name"], f"{kind} {_md(day)} 到期", f"{gap} 天" if gap else "今天",
                             "bad" if gap <= URGENT_DAYS else "warn", target("personnel.expiring")))
    more = f"还有 {len(people) - LIST_LIMIT} 人" if len(people) > LIST_LIMIT else ""
    return listing("block.expiring_list", "即将到期", rows, f"试用期 / 合同 · {EXPIRY_DAYS} 天内" if rows else "60 天内没有到期的试用期或合同",
                   more, target("personnel.expiring"), hint="只列姓名和日期，按剩余天数从近到远，最多 5 人。")


# ================================================================ 薪酬与社保：块
@provider("block.pay_progress", "block", visible=_hr, title="办理进度")
def block_pay_progress(ctx):
    payroll = _payroll(ctx)
    expected = payroll["expected"]
    rows = [
        bar_row("工资条已提交", f"{payroll['submitted']} / {expected}", _pct(payroll["submitted"], expected), "ok"),
        bar_row("工资条草稿", payroll["draft"], _pct(payroll["draft"], expected), "warn" if payroll["draft"] else ""),
        bar_row("工资条未生成", payroll["missing"], _pct(payroll["missing"], expected), "bad" if payroll["missing"] else ""),
    ]
    if not _sensitive_hidden(ctx):
        records = _records(ctx)
        for label, key in (("社保已确认", "si"), ("公积金已核对", "hf")):
            done = len(records[key]["confirmed"] & payroll["population"])
            rows.append(bar_row(label, f"{done} / {expected}", _pct(done, expected), "ok" if done >= expected else "warn"))
    return bars("block.pay_progress", "薪酬、社保、公积金办理进度", rows, f"{_month_label(ctx)} · 人" if expected else f"{_month_label(ctx)}没有需要出工资条的人",
                to=target("payroll", period=ctx.period),
                hint="分母 = 本月应有工资条的人。已提交 / 草稿 / 未生成是工资条的三种状态；社保已确认、公积金已核对按各自记录的状态算。")


@provider("block.si_hf_list", "block", visible=_hr_si, title="社保与公积金")
def block_si_hf_list(ctx):
    rows = []
    workbench = _workbench(ctx) or {}
    batch = next((item for item in workbench.get("batches") or [] if item.get("status") == "Pending Activation"), None)
    if batch:
        pending = _social_pending_rows(ctx)
        uploaded = _d(batch.get("uploaded_at"))
        rows.append(list_row(f"社保导入批次 {ctx.period}", f"{_md(uploaded)} 上传" if uploaded else "",
                             f"{pending} 行待确认" if pending else "待生效", "warn" if pending else "info",
                             target("social", period=ctx.period)))
    joiners = _new_joiners_without_records(ctx)
    if joiners:
        rows.append(list_row("本月新入职", "需要开通社保公积金", f"{joiners} 人", "info", target("social", period=ctx.period)))
    return listing("block.si_hf_list", "社保与公积金", rows, "需要你处理" if rows else "目前没有需要处理的社保、公积金事项",
                   to=target("social", period=ctx.period),
                   hint="社保导入批次：上传后还没生效的批次，及其中待确认的行数。新入职：所选月份入职、社保或公积金还没有记录的人数。")


@provider("block.pay_by_dept", "block", visible=_hr, title="部门人工成本")
def block_pay_by_dept(ctx):
    items = _top_with_other([(label, amount) for label, amount in _payroll(ctx)["by_dept"].items() if amount])
    top = items[0][1] if items else 0
    rows = [bar_row(label, _wan(amount), _pct(amount, top)) for label, amount in items]
    return bars("block.pay_by_dept", "部门人工成本", rows, "应发合计 · 万元（只看汇总）" if rows else f"{_month_label(ctx)}还没有工资条",
                to=target("payroll", period=ctx.period),
                hint="所选月份工资条的应发合计按部门汇总，含草稿；不显示个人。「其他」= 第 6 名及以后的部门合计。")


# ================================================================ 宿舍：块
@provider("block.dorm_summary", "block", visible=_hr, title="宿舍")
def block_dorm_summary(ctx):
    board = _dorm(ctx)
    occupancy = board["occupancy"]
    rate = round((occupancy.get("rate") or 0) * 100)
    value, unit = money_wan(occupancy.get("vacant_rent"))
    lease = board.get("lease_alert") or {}
    leavers = board.get("leavers_in_rooms") or []
    rows = [
        list_row("入住率", f"{occupancy.get('入住', 0)} / {occupancy.get('residential', 0)} 间", f"{rate}%",
                 "ok" if rate >= 90 else ("warn" if rate < 70 else ""), target("dorm.board")),
        list_row("空置房租", "每月", f"¥ {value} {unit}", "warn" if occupancy.get("vacant_rent") else "", target("dorm.board")),
        list_row(f"租约 {LEASE_DAYS} 天内到期", f"最早 {lease['earliest_date'][5:]}" if lease.get("earliest_date") else "",
                 f"{int(lease.get('count') or 0)} 间", "warn" if lease.get("count") or lease.get("expired_count") else "", target("dorm.lease")),
        list_row("已离职员工仍占房", "", f"{len(leavers)} 人", "bad" if leavers else "", target("dorm.leaver")),
    ]
    return listing("block.dorm_summary", "宿舍", rows, _month_label(ctx), to=target("dorm.board"),
                   hint="直接取宿舍看板的数：入住率 = 入住 ÷（入住 + 空置）；空置房租 = 空置房间的月租合计。")


def _component_rows(components):
    return [(item["label"], item["company"] + item["personal"]) for item in components]


@provider("block.dorm_cost", "block", visible=_hr, title="本月宿舍费用")
def block_dorm_cost(ctx):
    cost = _dorm(ctx)["cost"]
    if not cost.get("registered"):
        return stack("block.dorm_cost", "本月宿舍费用", [], f"{_month_label(ctx)}还没有登记费用", to=target("dorm.monthly", period=ctx.period),
                     hint="房租、水费、电费，公司和个人承担的合计。")
    total = cost["total"]
    value, unit = money_wan(total)
    colors = (BLUE, GREEN, AMBER)
    rows = [stack_row(label, "%s %s" % money_wan(amount), _pct(amount, total), colors[index % 3])
            for index, (label, amount) in enumerate(_component_rows(cost["components"]))]
    return stack("block.dorm_cost", "本月宿舍费用", rows, f"{_month_label(ctx)} · ¥ {value} {unit}", to=target("dorm.board"),
                 hint="所选月份已登记的宿舍费用，房租 / 水费 / 电费各自公司和个人承担之和。")


@provider("block.dorm_split", "block", visible=_hr, title="谁来承担")
def block_dorm_split(ctx):
    cost = _dorm(ctx)["cost"]
    if not cost.get("registered"):
        return stack("block.dorm_split", "谁来承担", [], f"{_month_label(ctx)}还没有登记费用", to=target("dorm.monthly", period=ctx.period),
                     hint="宿舍费用里公司承担和个人扣款各占多少。")
    total = cost["total"]
    value, unit = money_wan(total)
    rows = [stack_row("公司", "%s %s" % money_wan(cost["company"]), _pct(cost["company"], total), BLUE),
            stack_row("个人扣款", "%s %s" % money_wan(cost["personal"]), _pct(cost["personal"], total), GREY)]
    return stack("block.dorm_split", "谁来承担", rows, f"{_month_label(ctx)} · ¥ {value} {unit}", to=target("dorm.monthly", period=ctx.period),
                 hint="所选月份已登记的宿舍费用里，公司承担和个人扣款各占多少。")


@provider("block.dorm_buildings", "block", visible=_hr, title="各楼栋入住")
def block_dorm_buildings(ctx):
    live, total = Counter(), Counter()
    for room in _dorm(ctx).get("rooms") or []:
        if room.get("status") in ("入住", "空置"):
            total[room.get("building")] += 1
            if room["status"] == "入住":
                live[room.get("building")] += 1
    rows = []
    for building in sorted(total):
        pct = _pct(live[building], total[building])
        rows.append(bar_row(building, f"{live[building]} / {total[building]}", pct, "ok" if pct >= 90 else ("warn" if pct < 60 else "")))
    return bars("block.dorm_buildings", "各楼栋入住", rows, "间" if rows else "还没有宿舍房间", to=target("dorm.board"),
                hint="按房号首字母分楼栋；入住 / （入住 + 空置），客房和午休室不计入。")


@provider("block.dorm_lease_list", "block", visible=_hr, title="租约到期")
def block_dorm_lease_list(ctx):
    board = _dorm(ctx)
    groups = {}
    for room in _lease_rooms(board):
        groups.setdefault(room["lease_end_date"], []).append(room)
    rows = []
    for day in sorted(groups):
        rooms = groups[day]
        names = "、".join(room["room_no"] for room in rooms[:3]) + (f" 等 {len(rooms)} 间" if len(rooms) > 3 else "")
        expired = rooms[0]["lease_days_left"] < 0
        rows.append(list_row(names, "已过期" if expired else ("同一天到期" if len(rooms) > 1 else "到期"), day[5:],
                             "bad" if expired else "warn", target("dorm.lease")))
    more = f"还有 {len(rows) - LIST_LIMIT} 个到期日" if len(rows) > LIST_LIMIT else ""
    rows = rows[:LIST_LIMIT]
    open_rooms = _unregistered_rooms(board)
    if open_rooms or any(room.get("status") == "入住" for room in (board.get("rooms") or [])):
        rows.append(list_row("登记状态", _month_label(ctx), f"还有 {len(open_rooms)} 间没登记" if open_rooms else "已全部登记",
                             "info" if open_rooms else "ok", target("dorm.monthly", period=ctx.period, status="open" if open_rooms else None)))
    return listing("block.dorm_lease_list", "租约到期", rows, f"{LEASE_DAYS} 天内", more, target("dorm.lease"),
                   hint="租约结束日在今天起 60 天内（含已过期）的房间，同一天到期的合并一行。登记状态 = 所选月份在住但还没登记宿舍费用的房间数。")
