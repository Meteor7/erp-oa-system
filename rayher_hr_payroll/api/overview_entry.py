"""Dashboard overview APIs: company cost by project, HR leave stats, personal balance."""
from __future__ import annotations

import calendar
import re
from collections import defaultdict
from datetime import date

import frappe

from rayher_hr_payroll import annual_leave, attendance_requests
from rayher_hr_payroll.api._guards import RD_FINANCE_ROLES
from rayher_hr_payroll.position_access import position_users

NON_PROJECT = "__none__"
NON_PROJECT_LABEL = "非项目"
EXPENSE_REQUEST = "费用付款申请"
# 首页成本同时取旧的费用付款申请和新的报销单、付款单。
COST_REQUEST_TYPES = (EXPENSE_REQUEST, "报销单", "付款单")
EXPENSE_DONE = ("已完成", "已付款")
PO_DEAD_STATUS = ("已取消",)
HOURS_PER_DAY = 8
LEADER_POSITIONS = ("vice_manager", "general_manager")
HR_ROLES = {"HR User", "HR Manager", "System Manager"}
ATTENDANCE_TYPES = attendance_requests.ATTENDANCE_TYPES
LEAVE_TYPES = attendance_requests.LEAVE_TYPES


def _user():
    return str(frappe.session.user or "").strip().lower()


def _roles():
    return set(frappe.get_roles() or [])


def _is_leader():
    return _user() in position_users(*LEADER_POSITIONS)


def can_view_cost():
    return _is_leader() or bool(_roles() & set(RD_FINANCE_ROLES))


def hr_scope():
    """Return (visible, department, team). department / team 都是 None 表示全公司。

    部门主管（有在职直接下属的人）看自己的团队 team：汇报关系向下的在职员工（含他自己），
    下属在哪个部门都算（决定 2026-10-12，和考勤中心、数据看板、工时填报进度同一个范围）。
    """
    if _is_leader() or bool(_roles() & HR_ROLES):
        return True, None, None
    if "Department Manager" in _roles():
        from rayher_hr_payroll.team_scope import team_of_user
        team = team_of_user(_user())["names"]
        if team:
            return True, None, team
    return False, None, None


def parse_scope(scope, period):
    """Normalise (scope, period) into ("month"|"year", year, month or None)."""
    scope = "year" if str(scope or "").strip() == "year" else "month"
    text = str(period or "").strip()
    today = date.today()
    if scope == "year":
        return scope, int(text[:4]) if text[:4].isdigit() else today.year, None
    if len(text) >= 7 and text[:4].isdigit() and text[5:7].isdigit():
        return scope, int(text[:4]), int(text[5:7])
    return scope, today.year, today.month


def period_months(scope, year, month):
    if scope == "year":
        return [(year, index) for index in range(1, 13)]
    return [(year, month)]


def previous_months(scope, year, month):
    if scope == "year":
        return [(year - 1, index) for index in range(1, 13)]
    return [(year - 1, 12)] if month == 1 else [(year, month - 1)]


def trend_periods(scope, year, month):
    """Trend buckets: 12 months for a month view, 5 years for a year view."""
    if scope == "year":
        return [{"label": str(year - offset), "months": [(year - offset, index) for index in range(1, 13)]}
                for offset in range(4, -1, -1)]
    buckets = []
    for offset in range(11, -1, -1):
        shifted = (year * 12 + month - 1) - offset
        bucket_year, bucket_month = divmod(shifted, 12)
        buckets.append({"label": "%d月" % (bucket_month + 1), "months": [(bucket_year, bucket_month + 1)]})
    return buckets


def month_range(months):
    """First and last calendar date covered by the given (year, month) pairs."""
    first, last = min(months), max(months)
    return date(first[0], first[1], 1), date(last[0], last[1], calendar.monthrange(last[0], last[1])[1])


def _empty():
    return {"rd": 0.0, "po": 0.0, "expense": 0.0}


def project_costs(rows):
    """Aggregate {project, kind, amount} rows into per-project totals."""
    totals = defaultdict(_empty)
    for row in rows:
        project = row.get("project") or NON_PROJECT
        totals[project][row["kind"]] += float(row.get("amount") or 0)
    for values in totals.values():
        values["total"] = values["rd"] + values["po"] + values["expense"]
    return dict(totals)


def sum_costs(costs):
    result = _empty()
    for values in costs.values():
        for kind in ("rd", "po", "expense"):
            result[kind] += values[kind]
    result["total"] = result["rd"] + result["po"] + result["expense"]
    return result


def delta_percent(current, previous):
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def days(hours):
    return round(float(hours or 0) / HOURS_PER_DAY, 2)


def _rd_rows(months):
    wanted = set(months)
    periods = {row.name: (row.year, row.month) for row in frappe.get_all(
        "RD Cost Allocation",
        filters={"docstatus": 1, "year": ["in", sorted({year for year, _ in wanted})],
                 "month": ["in", sorted({month for _, month in wanted})]},
        fields=["name", "year", "month"], limit_page_length=0)
        if (row.year, row.month) in wanted}
    if not periods:
        return []
    return [{"project": line.project, "kind": "rd", "amount": line.allocated_amount,
             "label": line.account_level_3 or line.expense_item_name or "其他费用",
             "hours": line.basis_hours, "period": periods[line.parent]}
            for line in frappe.get_all("RD Cost Allocation Line", filters={"parent": ["in", list(periods)]},
                                       fields=["parent", "project", "allocated_amount", "account_level_3",
                                               "expense_item_name", "basis_hours"],
                                       limit_page_length=0)]


def _year_month(value):
    if not value:
        return None
    if hasattr(value, "year"):
        return (value.year, value.month)
    text = str(value)
    return (int(text[:4]), int(text[5:7])) if len(text) >= 7 else None


def _po_rows(months):
    start, end = month_range(months)
    orders = frappe.get_all("OA Purchase Order",
                            filters={"status": ["not in", PO_DEAD_STATUS],
                                     # 修复（2026-09-23）：日期上限对时间字段本来就取到当天 23:59:59，
                                     # 再加一天会把下月 1 日的数据也算进本月（下月再算一次）。
                                     "creation": ["between", [start, end]]},
                            fields=["name", "creation"], limit_page_length=0)
    if not orders:
        return []
    month_by_order = {row.name: _year_month(row.creation) for row in orders}
    lines = frappe.get_all("OA Purchase Order Line", filters={"parent": ["in", list(month_by_order)]},
                           fields=["parent", "project", "amount", "item_name", "material_code", "source_request"],
                           limit_page_length=0)
    sources = {row.source_request for row in lines if row.source_request}
    departments = {row.name: row.department for row in frappe.get_all(
        "OA Approval Request", filters={"name": ["in", list(sources)]},
        fields=["name", "department"], limit_page_length=0)} if sources else {}
    return [{"project": line.project, "kind": "po", "amount": line.amount,
             "label": line.item_name or line.material_code or "采购物料",
             "department": departments.get(line.source_request) or "",
             "cost_month": month_by_order.get(line.parent)}
            for line in lines]


def _expense_rows(months):
    start, end = month_range(months)
    # 按实际付款日期计入月份（原来按单据修改时间），未付款的单据不计入成本，和金额台账一致。
    requests = frappe.get_all("OA Approval Request",
                              filters={"request_type": ["in", list(COST_REQUEST_TYPES)],
                                       "workflow_status": "已付款",
                                       "paid_on": ["between", [start, end]]},
                              fields=["name", "project", "department", "paid_on"], limit_page_length=0)
    if not requests:
        return []
    project_by_request = {row.name: row.project for row in requests}
    department_by_request = {row.name: row.department for row in requests}
    month_by_request = {row.name: _year_month(row.get("paid_on")) for row in requests}
    return [{"project": line.claim_project or line.project_name or project_by_request.get(line.parent),
             "kind": "expense", "amount": line.total_amount or line.amount,
             "label": line.expense_account_level_2 or line.category or "其他报销",
             "department": department_by_request.get(line.parent) or "",
             "cost_month": month_by_request.get(line.parent)}
            for line in frappe.get_all("OA Approval Expense Line",
                                       filters={"parent": ["in", list(project_by_request)]},
                                       fields=["parent", "project_name", "claim_project", "total_amount",
                                               "amount", "expense_account_level_2", "category"],
                                       limit_page_length=0)]


FOREIGN_RD_LABEL = "境外委托研发"


def _foreign_rd_rows(months, extra_months=()):
    """境外委托研发按项目的分摊额，计入研发（修复 2026-09-29，审查 X2-10，决定 D7）。

    原来首页的研发只读国内分摊行，境外委托研发不在任何首页数字里。
    现在境外部分按月份直接计入（2026-10-13，和研发费用汇总页、分摊页同一口径），不看国内费用导入有没有提交。
    """
    # 统一口径（2026-10-13）：和研发费用汇总页（allocation_entry.get_allocation_dashboard）、分摊页一样，
    # 境外委托研发按月份直接计入，不看国内费用导入有没有提交；首页的研发分摊 = 点进去那一页的合计。
    # extra_months 保留参数，不再需要。
    imported = set(months)
    if not imported:
        return []
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix.rd_allocation_matrix import (
        _foreign_matrix_lines_for_month,
    )

    rows = []
    for year, month in sorted(imported):
        for line in _foreign_matrix_lines_for_month(year, month):
            rows.append({"project": line.get("project"), "kind": "rd", "amount": line.get("allocated_amount"),
                         "label": FOREIGN_RD_LABEL, "period": (year, month)})
    return rows


def _allocated_months(months):
    wanted = set(months)
    return {(int(row.year), int(row.month)) for row in frappe.get_all(
        "RD Cost Allocation",
        filters={"docstatus": 1, "year": ["in", sorted({year for year, _ in wanted})]},
        fields=["year", "month"], limit_page_length=0) if row.year and row.month} & wanted


def _rd_project_names():
    return set(frappe.get_all("Project", filters={"rd_project_code": ["!=", ""]}, pluck="name"))


def drop_allocated_rd_duplicates(rows, allocated_months, rd_projects):
    """去掉已进研发分摊的采购和报销行（修复 2026-09-29，审查 X2-10，决定 D7）。

    研发分摊的来源是财务总账导入，研发项目的采购付款、报销在总账里本来就有。某个月的分摊
    已提交时，这个月研发项目的采购和报销再加一遍就是重复计算；非研发项目、没有分摊的月份照旧。
    """
    return [row for row in rows
            if not (row["kind"] in ("po", "expense")
                    and row.get("cost_month") in allocated_months
                    and (row.get("project") or "") in rd_projects)]


PREVIEW_LIMIT = 12  # 一次请求最多现算几个月的预览（每个月约 0.4–0.7 秒）


class PreviewBook:
    """没有定版（已提交）分摊单的月份，用「预览」（按当前数据现算，只读）顶上研发成本。

    一次请求共用一个：同一个月只算一次，总共最多算 PREVIEW_LIMIT 个月（先到先算，调用方先传当前
    期间，所以当前期间优先）。有费用导入但算不出来的月份（比如还没有研发工时）和以前一样不计入。"""

    def __init__(self, limit=PREVIEW_LIMIT):
        self.limit = limit
        self.computed = 0
        self._lines = {}      # (year, month) -> 研发成本行；算不出来是 None
        self._imports = {}    # year -> 有费用导入的月份集合

    @property
    def months(self):
        """已经用预览顶上的月份 {(year, month)}。"""
        return {key for key, rows in self._lines.items() if rows is not None}

    def _imported(self, year):
        if year not in self._imports:
            self._imports[year] = {int(row.month) for row in frappe.get_all(
                "RD Expense Import", filters={"docstatus": ["<", 2], "year": year},
                fields=["month"], limit_page_length=0) if row.month}
        return self._imports[year]

    def _compute(self, year, month):
        from rayher_hr_payroll.rd_cost.allocation_preview import build_preview

        try:
            preview = build_preview("%04d-%02d" % (year, month), year, month)
        except Exception:
            return None
        if preview is None or preview.error or preview.doc is None:
            return None
        return [{"project": line.project, "kind": "rd", "amount": line.allocated_amount,
                 "label": line.account_level_3 or line.expense_item_name or "其他费用",
                 "hours": line.basis_hours, "period": (year, month)}
                for line in (preview.doc.lines or [])]

    def lines_for(self, months, finalized):
        """months 里没定版、有费用导入、预览算得出来的月份 -> {(year, month): 成本行}。"""
        result = {}
        for year, month in sorted(set(months) - set(finalized), reverse=True):
            if (year, month) not in self._lines:
                if month not in self._imported(year) or self.computed >= self.limit:
                    continue
                self.computed += 1
                self._lines[(year, month)] = self._compute(year, month)
            rows = self._lines[(year, month)]
            if rows is not None:
                result[(year, month)] = rows
        return result

    def preview_months(self, months):
        """months 里用了预览的月份，形如 ["2026-09"]。"""
        return sorted("%04d-%02d" % key for key in self.months & set(months))


def cost_rows(months, previews=None):
    allocated = _allocated_months(months)
    preview_lines = previews.lines_for(months, allocated) if previews is not None else {}
    rows = _rd_rows(months)
    if preview_lines:
        rows += [row for lines in preview_lines.values() for row in lines]
        rows += _foreign_rd_rows(months, extra_months=set(preview_lines))
    else:
        rows += _foreign_rd_rows(months)
    rows += _po_rows(months) + _expense_rows(months)
    # 预览顶上的月份和已定版的月份一样：研发项目的采购、报销已在总账分摊里，不再重复计入。
    allocated = set(allocated) | set(preview_lines)
    if not allocated:
        return rows
    return drop_allocated_rd_duplicates(rows, allocated, _rd_project_names())


def _project_labels(keys):
    names = [key for key in keys if key and key != NON_PROJECT]
    if not names:
        return {}
    return {row.name: row.project_name or row.name
            for row in frappe.get_all("Project", filters={"name": ["in", names]},
                                      fields=["name", "project_name"], limit_page_length=0)}


@frappe.whitelist()
def get_cost_overview(scope="month", period=None):
    if not can_view_cost():
        return {"visible": False}
    scope, year, month = parse_scope(scope, period)
    # 没定版的月份用预览顶上研发成本；一次请求共用一个 PreviewBook，同一个月只算一次。
    book = PreviewBook()
    current_months = period_months(scope, year, month)
    costs = project_costs(cost_rows(current_months, book))
    previous = project_costs(cost_rows(previous_months(scope, year, month), book))
    labels = _project_labels(costs)
    totals, previous_totals = sum_costs(costs), sum_costs(previous)
    projects = sorted(
        ({"project": key,
          "label": NON_PROJECT_LABEL if key == NON_PROJECT else labels.get(key, key),
          "delta": delta_percent(values["total"], previous.get(key, _empty()).get("total", 0)),
          **values} for key, values in costs.items()),
        key=lambda row: row["total"], reverse=True)
    trend = []
    for bucket in trend_periods(scope, year, month):
        bucket_costs = sum_costs(project_costs(cost_rows(bucket["months"], book)))
        trend.append({"label": bucket["label"], **bucket_costs,
                      "preview": bool(book.preview_months(bucket["months"]))})
    preview_months = book.preview_months(current_months)
    return {"visible": True, "scope": scope, "year": year, "month": month, "totals": totals,
            "deltas": {kind: delta_percent(totals[kind], previous_totals[kind])
                       for kind in ("rd", "po", "expense", "total")},
            "projects": projects, "trend": trend,
            "preview": bool(preview_months), "preview_months": preview_months}


@frappe.whitelist()
def get_project_cost_detail(project="", scope="month", period=None):
    if not can_view_cost():
        frappe.throw(frappe._("只有财务和公司领导可以查看项目费用明细。"))
    scope, year, month = parse_scope(scope, period)
    key = str(project or NON_PROJECT).strip() or NON_PROJECT
    groups = {"rd": defaultdict(float), "po": defaultdict(float), "expense": defaultdict(float)}
    # basis_hours repeats on every allocation line of a month, so keep one value per month.
    hours_by_period = {}
    book = PreviewBook()
    current_months = period_months(scope, year, month)
    all_rows = cost_rows(current_months, book)
    for row in all_rows:
        if (row.get("project") or NON_PROJECT) != key:
            continue
        groups[row["kind"]][row["label"]] += float(row.get("amount") or 0)
        if row.get("period"):
            hours_by_period[row["period"]] = max(hours_by_period.get(row["period"], 0.0),
                                                 float(row.get("hours") or 0))
    hours = sum(hours_by_period.values())
    totals = {kind: sum(values.values()) for kind, values in groups.items()}
    totals["total"] = sum(totals.values())
    label, owner, team = NON_PROJECT_LABEL, "", 0
    if key != NON_PROJECT:
        row = frappe.db.get_value("Project", key, ["project_name", "project_owner_name"], as_dict=True) or {}
        label = row.get("project_name") or key
        owner = row.get("project_owner_name") or ""
        team = _project_team(key, period_months(scope, year, month))
    breakdown = {kind: sorted(({"label": label_text, "amount": amount}
                               for label_text, amount in values.items()),
                              key=lambda row: row["amount"], reverse=True)[:8]
                 for kind, values in groups.items()}
    if key == NON_PROJECT:
        # unassigned spend is easier to act on grouped by the department that spent it
        by_department = defaultdict(float)
        for row in all_rows:
            if (row.get("project") or NON_PROJECT) != NON_PROJECT:
                continue
            by_department[row.get("department") or "未指定部门"] += float(row.get("amount") or 0)
        breakdown["department"] = sorted(({"label": name, "amount": amount}
                                          for name, amount in by_department.items()),
                                         key=lambda row: row["amount"], reverse=True)[:8]
    preview_months = book.preview_months(current_months)
    return {"project": key, "label": label, "owner": owner, "team": team,
            "totals": totals, "hours": round(hours, 1), "breakdown": breakdown,
            "preview": bool(preview_months), "preview_months": preview_months}


def _project_team(project, months):
    """How many people booked hours to the project in the period."""
    start, end = month_range(months)
    rows = frappe.db.sql("""select count(distinct ts.employee) as people
                            from `tabTimesheet Detail` td join `tabTimesheet` ts on ts.name = td.parent
                            where ts.docstatus = 1 and td.project = %s and date(td.from_time) between %s and %s""",
                         (project, start, end))
    return int(rows[0][0] or 0) if rows else 0


def leave_stats(rows):
    """Aggregate attendance requests into per-type and per-department day totals."""
    by_type, by_department = defaultdict(float), defaultdict(lambda: {"leave": 0.0, "overtime": 0.0})
    totals = {"leave_days": 0.0, "leave_count": 0, "overtime_days": 0.0, "comp_days": 0.0}
    for row in rows:
        request_type = row.get("request_type")
        hours = float(row.get("duration_hours") or 0)
        department = row.get("department") or "未分配部门"
        if request_type == attendance_requests.REQUEST_LEAVE:
            totals["leave_days"] += days(hours)
            totals["leave_count"] += 1
            by_type[row.get("leave_type") or "未填类别"] += days(hours)
            by_department[department]["leave"] += days(hours)
        elif request_type == attendance_requests.REQUEST_OVERTIME:
            totals["overtime_days"] += days(hours)
            by_department[department]["overtime"] += days(hours)
        elif request_type == attendance_requests.REQUEST_COMP_TIME:
            totals["comp_days"] += days(hours)
            by_type["调休"] += days(hours)
            by_department[department]["leave"] += days(hours)
    totals = {key: round(value, 2) if isinstance(value, float) else value for key, value in totals.items()}
    return {
        "totals": totals,
        "by_type": sorted(({"label": key, "days": round(value, 2)} for key, value in by_type.items()),
                          key=lambda row: row["days"], reverse=True),
        "by_department": sorted(({"label": key, "leave": round(value["leave"], 2),
                                  "overtime": round(value["overtime"], 2)}
                                 for key, value in by_department.items()),
                                key=lambda row: row["leave"] + row["overtime"], reverse=True)[:10],
    }


def _away_today(department=None, employees=None):
    """People on approved leave or comp-time today, by leave type."""
    today = date.today()
    filters = {"request_type": ["in", [attendance_requests.REQUEST_LEAVE, attendance_requests.REQUEST_COMP_TIME]],
               "workflow_status": ["in", list(attendance_requests.COMPLETED)],
               "from_date": ["<=", today], "to_date": [">=", today]}
    if department:
        filters["department"] = department
    if employees is not None:
        filters["employee"] = ["in", list(employees) or ["__none__"]]
    rows = frappe.get_all("OA Approval Request", filters=filters,
                          fields=["employee", "employee_name", "leave_type", "request_type"],
                          limit_page_length=0)
    by_type = defaultdict(int)
    for row in rows:
        by_type[row.leave_type or ("调休" if row.request_type == attendance_requests.REQUEST_COMP_TIME else "请假")] += 1
    return {"count": len({row.employee for row in rows}),
            "by_type": sorted(({"label": key, "count": value} for key, value in by_type.items()),
                              key=lambda item: item["count"], reverse=True)}


def _attendance_rows(months, department=None, employees=None):
    """已批准的请假、加班、调休；跨月的申请按天拆开，只算落在所选月份里的小时。

    修复（2026-09-29，审查 #56 P3）：原来按开始日期归月，一张 9 月 30 日到 10 月 2 日的假
    全部记在 9 月。现在按每天的明细分月。
    修复（2026-10-13）：拆月和考勤中心用同一个函数（attendance_board.month_window）：只有起止日期的旧申请
    也按期间里每个周一到周五 8 小时拆，不再整张记在开始那个月。
    """
    from rayher_hr_payroll import attendance_board

    start, end = month_range(months)
    filters = {"request_type": ["in", list(ATTENDANCE_TYPES)],
               "workflow_status": ["in", list(attendance_requests.COMPLETED)],
               "from_date": ["<=", end], "to_date": [">=", start]}
    if department:
        filters["department"] = department
    if employees is not None:
        filters["employee"] = ["in", list(employees) or ["__none__"]]
    rows = frappe.get_all("OA Approval Request", filters=filters,
                          fields=["name", "request_type", "leave_type", "duration_hours", "department",
                                  "employee", "employee_name", "from_date", "to_date", "attendance_days"],
                          limit_page_length=0)
    return attendance_board.month_window(rows, start, end)


def month_leave(months, employees=None):
    """看板“本月请假 / 调休 / 加班”的取数（口径见 attendance_board.leave_figures）：已批准的、在职员工的申请，
    跨月申请按天拆。employees 给了就只算这些人里在职的。部门按员工档案里的部门（不是申请单上的快照）。

    返回 {totals {leave_days, leave_count, comp_days, overtime_days}, by_type [{label, days}]（只有请假的假别）,
          by_department [{department, leave, comp, overtime, leave_count, overtime_count}]（天，从多到少，不截断）, figures, headcount}。
    """
    from rayher_hr_payroll import attendance_board

    filters = {"status": "Active"}
    if employees is not None:
        filters["name"] = ["in", list(employees) or ["__none__"]]
    staff = frappe.get_all("Employee", filters=filters, fields=["name", "department"], limit_page_length=0)
    ids = [row.get("name") for row in staff]
    figures = attendance_board.leave_figures(_attendance_rows(months, None, ids), ids)
    department_of = {row.get("name"): row.get("department") or "" for row in staff}
    grouped = {}
    for item in figures["requests"]:
        entry = grouped.setdefault(department_of.get(item["employee"], ""), {"leave": 0.0, "comp": 0.0, "overtime": 0.0, "leave_count": 0, "overtime_count": 0})
        key = {attendance_requests.REQUEST_LEAVE: "leave", attendance_requests.REQUEST_COMP_TIME: "comp"}.get(item["request_type"], "overtime")
        entry[key] += float(item["hours"])          # 先按小时加，最后再折成天，和合计同一种舍入
        if key in ("leave", "overtime"):
            entry[f"{key}_count"] += 1
    by_department = [{"department": name, **{key: days(value) if isinstance(value, float) else value for key, value in entry.items()}}
                     for name, entry in grouped.items()]
    by_department.sort(key=lambda row: (-row["leave"], -row["overtime"], row["department"]))
    return {
        "totals": {"leave_days": figures["leave_days"], "leave_count": figures["leave_count"], "comp_days": figures["comp_days"],
                   "overtime_days": figures["overtime_days"]},
        "by_type": sorted(({"label": key, "days": days(value)} for key, value in figures["by_type"].items()), key=lambda row: (-row["days"], row["label"])),
        "by_department": by_department, "figures": figures, "headcount": len(ids),
    }


@frappe.whitelist()
def get_hr_overview(scope="month", period=None):
    visible, department, team = hr_scope()
    if not visible:
        return {"visible": False}
    scope, year, month = parse_scope(scope, period)
    stats = leave_stats(_attendance_rows(period_months(scope, year, month), department, team))
    trend = []
    for bucket in trend_periods(scope, year, month):
        bucket_stats = leave_stats(_attendance_rows(bucket["months"], department, team))["totals"]
        trend.append({"label": bucket["label"], "leave": bucket_stats["leave_days"],
                      "overtime": bucket_stats["overtime_days"]})
    employee_filters = {"status": "Active"}
    if department:
        employee_filters["department"] = department
    if team is not None:
        employee_filters["name"] = ["in", team]
    employees = frappe.get_all("Employee", filters=employee_filters,
                               fields=["name", "employee_name", "department", "date_of_joining"],
                               limit_page_length=0)
    balances, missing_joining = [], 0
    for employee in employees:
        if not employee.date_of_joining:
            missing_joining += 1
        annual = annual_leave.get_annual_balance(employee.name)
        comp = attendance_requests.get_balance(employee.name)
        balances.append({"employee": employee.employee_name or employee.name,
                         "department": employee.department or "",
                         "annual_days": days(annual.get("available_hours")),
                         "comp_days": days(comp.get("available_hours"))})
    balances.sort(key=lambda row: row["annual_days"] + row["comp_days"], reverse=True)
    return {"visible": True, "scope": scope, "year": year, "month": month,
            "department": department, "headcount": len(employees), "away_today": _away_today(department, team),
            "alerts": {"missing_joining": missing_joining,
                       "negative_comp": sum(1 for row in balances if row["comp_days"] < 0)},
            "trend": trend, "balances": balances[:8], **stats}


@frappe.whitelist()
def get_my_leave_summary():
    if _user() in {"", "guest"}:
        frappe.throw(frappe._("请先登录。"))
    employee = frappe.db.get_value("Employee", {"user_id": _user(), "status": "Active"},
                                   ["name", "date_of_joining"], as_dict=True)
    if not employee:
        return {"visible": False}
    annual = annual_leave.get_annual_balance(employee.name)
    comp = attendance_requests.get_balance(employee.name)
    return {"visible": True,
            "annual": {"available": days(annual.get("available_hours")),
                       "granted": days(annual.get("credit_hours")),
                       "used": days(annual.get("used_hours")),
                       "reserved": days(annual.get("reserved_hours")),
                       "eligible": annual.get("eligible"),
                       "message": annual.get("eligibility_message") or "",
                       "next_grant_date": annual.get("next_grant_date"),
                       "next_grant_days": days(annual_leave.ANNUAL_HOURS)},
            "comp": {"available": days(comp.get("available_hours")),
                     "credit": days(comp.get("credit_hours")),
                     "used": days(comp.get("used_hours")),
                     "reserved": days(comp.get("reserved_hours"))}}


# --- personal queue ----------------------------------------------------------

ROUTE_BY_TYPE = {
    "请假申请": "/approval/leave",
    "加班申请": "/approval/overtime",
    "调休申请": "/approval/comp-time",
    "采购申请": "/approval/procurement",
    "购买申请": "/approval/direct-purchase",
    "采购付款": "/approval/procurement-payment",
    "费用付款申请": "/approval/reimbursement",
    "出差申请": "/approval/travel",
    "报销单": "/approval/claim",
    "付款单": "/approval/payment",
}
OVERDUE_DAYS = 3


def waiting_days(since):
    if not since:
        return 0
    return max(0, (frappe.utils.now_datetime() - frappe.utils.get_datetime(since)).days)


def queue_item(doc, steps):
    """Shape one pending approval for the dashboard list."""
    waited = waiting_days(doc.get("modified"))
    amount = float(doc.get("approved_amount") or doc.get("amount") or 0)
    current = next((row for row in steps if row.get("status") in ("待审批", "待办理", "")), None)
    return {
        "name": doc.get("name"),
        "request_type": doc.get("request_type"),
        "subject": doc.get("subject") or doc.get("name"),
        "applicant": doc.get("employee_name") or doc.get("owner") or "",
        "department": doc.get("department") or "",
        "amount": amount,
        "leave_type": doc.get("leave_type") or "",
        "hours": float(doc.get("duration_hours") or 0),
        "from_date": str(doc.get("from_date") or ""),
        "to_date": str(doc.get("to_date") or ""),
        "step_label": (current or {}).get("label") or doc.get("current_step_label") or "",
        "waited_days": waited,
        "overdue": waited >= OVERDUE_DAYS,
        "route": ROUTE_BY_TYPE.get(doc.get("request_type"), "/approval/request-dashboard"),
    }


def _steps_by_parent(names):
    rows = frappe.get_all("OA Approval Step", filters={"parent": ["in", names]},
                          fields=["parent", "step_index", "label", "status", "note", "acted_on"],
                          order_by="parent asc, step_index asc", limit_page_length=0) if names else []
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.parent].append(row)
    return grouped


PROCUREMENT_ROUTE = "/approval/procurement/price-approvals"
PAYMENT_ROUTE = "/approval/procurement-payment"


def task_item(kind, title, detail, waited, route, reason, name, amount=0, query=None):
    """One thing the signed-in user has to do, whatever document it lives on."""
    return {"name": name, "kind": kind, "request_type": kind, "subject": title, "applicant": detail,
            "department": "", "amount": float(amount or 0), "leave_type": "", "hours": 0,
            "from_date": "", "to_date": "", "step_label": "", "reason": reason,
            "waited_days": waited, "overdue": waited >= OVERDUE_DAYS,
            "route": route, "query": query or {}}


def _price_approval_tasks():
    """Price approvals waiting for the person who signs them off."""
    if _user() not in position_users("vice_manager") and "System Manager" not in _roles():
        return []
    rows = frappe.get_all("OA Price Approval", filters={"status": "待审批"},
                          fields=["name", "total_amount", "modified", "owner"], limit_page_length=0)
    return [task_item("价格审批", f"{row.name} 待选择成交供应商并审批",
                      f"采购提交 · {frappe.db.get_value('User', row.owner, 'full_name') or row.owner}",
                      waiting_days(row.modified), PROCUREMENT_ROUTE, "我是价格审批人", row.name,
                      row.total_amount, {"approval": row.name})
            for row in rows]


def _purchase_order_tasks():
    """PO stages, each shown only to the role that has to act on it."""
    user, roles = _user(), _roles()
    is_purchase = user in position_users("procurement_manager") or bool(roles & {"Purchase User", "Purchase Manager"})
    is_asset_owner = user in position_users("production_asset_owner")
    is_admin = "System Manager" in roles
    stages = {
        "草稿": ("待采购确认订单", "我是采购", is_purchase or is_admin),
        "待采购确认": ("待采购确认订单", "我是采购", is_purchase or is_admin),
        "待合同复核": ("合同待复核", "我是采购", is_purchase or is_admin),
        "待电子用印": ("合同待电子用印", "我负责用印", is_purchase or is_admin),
        "供应商制作中": ("待登记到货", "我是生产主管", is_asset_owner or is_admin),
        "到货验收中": ("待验收", "我是采购", is_purchase or is_admin),
    }
    rows = frappe.get_all("OA Purchase Order",
                          filters={"status": ["in", list(stages)]},
                          fields=["name", "status", "supplier", "total_amount", "modified"],
                          limit_page_length=0)
    items = []
    for row in rows:
        label, reason, allowed = stages[row.status]
        if not allowed:
            continue
        items.append(task_item("采购订单", f"{row.name} {label}",
                               f"{row.supplier or '供应商待定'} · {row.status}",
                               waiting_days(row.modified), PAYMENT_ROUTE if row.status == "到货验收中" else PROCUREMENT_ROUTE,
                               reason, row.name, row.total_amount, {"po": row.name}))
    return items


def _payment_tasks():
    """Payment periods whose conditions are met, or blocked and waiting on me."""
    from rayher_hr_payroll.api.procurement_chain import list_payment_work_items

    try:
        work_items = list_payment_work_items(limit=200) or []
    except Exception as exc:
        if not isinstance(exc, (frappe.PermissionError, frappe.ValidationError)):
            raise
        return []
    items = []
    for row in work_items:
        if not row.get("can_push_payment"):
            continue
        items.append(task_item("采购付款", f"{row.get('po')} {row.get('installment_name') or '付款期次'} 可提交付款",
                               f"金额 {float(row.get('amount') or 0):,.2f} · 条件已满足",
                               waiting_days(row.get("planned_date")), PAYMENT_ROUTE,
                               "我负责提交付款", str(row.get("po")), row.get("amount"),
                               {"po": row.get("po")}))
    return items


@frappe.whitelist()
def get_my_approval_queue(limit=12):
    """Everything waiting on the signed-in user, from every document type."""
    from rayher_hr_payroll.api import oa_entry

    summary = oa_entry.get_my_approval_summary()
    names = [name for category in summary["categories"] for name in category["requests"]]
    items = []
    if names:
        docs = frappe.get_all("OA Approval Request", filters={"name": ["in", names]},
                              fields=["name", "request_type", "subject", "employee_name", "owner", "department",
                                      "amount", "approved_amount", "leave_type", "duration_hours", "from_date",
                                      "to_date", "current_step_label", "modified"],
                              limit_page_length=0)
        steps = _steps_by_parent([row.name for row in docs])
        for row in docs:
            item = queue_item(row, steps.get(row.name, []))
            item["reason"] = "我是审批人"
            item["kind"] = row.request_type
            item["query"] = {"request": row.name}
            items.append(item)
    for extra in (_price_approval_tasks(), _purchase_order_tasks(), _payment_tasks()):
        items.extend(extra)
    items.sort(key=lambda row: (not row["overdue"], -row["waited_days"]))
    return {"total": len(items), "approval_total": summary["total"], "items": items[:int(limit or 12)]}


def request_progress(doc, steps):
    """Where a request of mine stands, and whether it came back for changes."""
    total = len(steps) or 1
    done = sum(1 for row in steps if row.get("status") in ("已通过", "已审批", "已完成", "已办理"))
    returned = next((row for row in steps if row.get("status") in ("已拒绝", "已退回", "退回")), None)
    return {
        "name": doc.get("name"),
        "request_type": doc.get("request_type"),
        "subject": doc.get("subject") or doc.get("name"),
        "amount": float(doc.get("approved_amount") or doc.get("amount") or 0),
        "status": doc.get("workflow_status"),
        "step_label": doc.get("current_step_label") or "",
        "done_steps": done,
        "total_steps": total,
        "returned": bool(returned),
        "returned_note": (returned or {}).get("note") or "",
        "route": ROUTE_BY_TYPE.get(doc.get("request_type"), "/approval/request-dashboard"),
    }


@frappe.whitelist()
def get_my_requests(limit=6):
    """Requests I submitted that are still running or came back to me."""
    user = _user()
    if user in {"", "guest"}:
        frappe.throw(frappe._("请先登录。"))
    employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name") or frappe.db.get_value("Employee", {"user_id": user}, "name")
    filters = {"workflow_status": ["in", ["待审批", "待办理", "草稿"]]}
    if employee:
        filters["employee"] = employee
    else:
        filters["owner"] = frappe.session.user
    docs = frappe.get_all("OA Approval Request", filters=filters,
                          fields=["name", "request_type", "subject", "amount", "approved_amount",
                                  "workflow_status", "current_step_label", "modified"],
                          order_by="modified desc", limit_page_length=int(limit or 6))
    steps = _steps_by_parent([row.name for row in docs])
    return {"items": [request_progress(row, steps.get(row.name, [])) for row in docs]}


# --- notifications -----------------------------------------------------------

# Events that mean "go and do something": the queue already shows them, so they
# never repeat here.
ACTION_EVENTS = ("待处理", "待审批", "待办理", "待你处理")
MINE_EVENTS = ("已通过", "已拒绝", "已退回", "被退回", "已付款", "已完成", "已撤回", "已关闭")
CC_MARK = "抄送"
# 修复（2026-10，导航审计 P1）：价格审批页只认 approval= / pr= / po=（request= 是 OA 采购申请单号），
# 原来价格审批单和 PR 的通知都用 request=，打开后是空页面加"仅查看这张采购申请"。
# 第三项是固定要带的查询：PR 要 view=source 才落在"PR 待比价物料"页签。
DOC_ROUTES = {
    "OA Purchase Order": ("/approval/procurement/price-approvals", "po", {"tab": "po"}),
    "OA Price Approval": ("/approval/procurement/price-approvals", "approval", {"view": "approvals"}),
    "OA Procurement Request": ("/approval/procurement/price-approvals", "pr", {"view": "source"}),
    "OA Material Progress": ("/approval/material-progress", "request", {}),
}
CATEGORY_LABELS = [("mine", "我的申请"), ("cc", "抄送我的"), ("biz", "业务进展"), ("sys", "系统与指派")]


def _clean_subject(subject):
    """Strip the machine tail like [oa-assignment:OA-2026-1:uuid] and the id list."""
    text = re.sub(r"\s*\[[^\]]*\]\s*$", "", str(subject or "")).strip()
    event, _, rest = text.partition("：")
    return event.strip(), rest.strip()


def _short(value, limit=40):
    value = str(value or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _document_summary(doctype, name):
    """A human line for the document a notification points at."""
    if not doctype or not name:
        return {"title": "", "detail": "", "route": "", "query": {}}
    if doctype == "OA Approval Request":
        row = frappe.db.get_value("OA Approval Request", name,
                                  ["subject", "request_type", "employee_name", "amount", "approved_amount",
                                   "current_step_label"], as_dict=True) or {}
        amount = float(row.get("approved_amount") or row.get("amount") or 0)
        detail = " · ".join(filter(None, [
            row.get("employee_name") and f"申请人 {row['employee_name']}",
            amount and f"¥ {amount:,.2f}",
            row.get("current_step_label") and f"当前 {row['current_step_label']}",
        ]))
        route = ROUTE_BY_TYPE.get(row.get("request_type"), "/approval/request-dashboard")
        return {"title": row.get("subject") or name, "detail": detail, "route": route, "query": {"request": name}}
    if doctype == "OA Purchase Order":
        row = frappe.db.get_value("OA Purchase Order", name,
                                  ["supplier", "status", "total_amount"], as_dict=True) or {}
        item = frappe.db.get_value("OA Purchase Order Line", {"parent": name}, "item_name")
        detail = " · ".join(filter(None, [row.get("supplier"), row.get("status"),
                                          row.get("total_amount") and f"¥ {float(row['total_amount']):,.2f}"]))
        return {"title": _short(item or "采购订单"), "detail": detail,
                "route": DOC_ROUTES[doctype][0], "query": _doc_query(doctype, name)}
    if doctype in ("OA Price Approval", "OA Procurement Request"):
        child = "OA Price Approval Line" if doctype == "OA Price Approval" else "OA Procurement Request Line"
        source = frappe.db.get_value(child, {"parent": name}, ["source_request", "item_name"], as_dict=True) or {}
        subject = frappe.db.get_value("OA Approval Request", source.get("source_request"), "subject") if source.get("source_request") else None
        total = frappe.db.get_value(doctype, name, "total_amount") if doctype == "OA Price Approval" else None
        detail = " · ".join(filter(None, [source.get("item_name"), total and f"¥ {float(total):,.2f}"]))
        return {"title": _short(subject or source.get("item_name") or name), "detail": detail,
                "route": DOC_ROUTES[doctype][0], "query": _doc_query(doctype, name)}
    if doctype == "OA Material Progress":
        # 物料进度看板按"来源 OA 申请单号"过滤（request=），不认物料进度行自己的编号。
        board = frappe.db.get_value("OA Material Progress", name,
                                    ["source_request", "source_line", "item_name"], as_dict=True) or {}
        source_request = board.get("source_request")
        query = {"request": source_request} if source_request else {}
        if source_request and board.get("source_line"):
            query["source_line"] = board["source_line"]
        return {"title": _short(board.get("item_name") or name), "detail": "", "route": DOC_ROUTES[doctype][0],
                "query": query}
    if doctype in DOC_ROUTES:
        return {"title": name, "detail": "", "route": DOC_ROUTES[doctype][0], "query": _doc_query(doctype, name)}
    return {"title": name, "detail": "", "route": "", "query": {}}


def _doc_query(doctype, name):
    """通知指向的单据在目标页面上的查询参数：固定的页签参数 + 单据自己的键。"""
    _route, key, extra = DOC_ROUTES[doctype]
    return {**extra, key: name}


def classify(subject, doctype, name, user, applicants):
    event, _ = _clean_subject(subject)
    if CC_MARK in event:
        return "cc", event
    if any(word in event for word in ACTION_EVENTS):
        return "action", event
    if applicants.get(name) == user or any(word in event for word in MINE_EVENTS) and applicants.get(name) == user:
        return "mine", event
    if doctype == "OA Approval Request" and applicants.get(name) == user:
        return "mine", event
    if doctype in DOC_ROUTES or doctype == "OA Approval Request":
        return "biz", event
    return "sys", event


@frappe.whitelist()
def get_my_notification_feed(category="mine", unread_only=1, limit=20):
    """Notifications written for people: what happened, to what, by whom."""
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw(frappe._("请先登录。"))
    rows = frappe.get_all("Notification Log", filters={"for_user": user},
                          fields=["name", "subject", "email_content", "document_type", "document_name",
                                  "read", "creation", "type"],
                          order_by="creation desc", limit_page_length=400)
    request_names = [row.document_name for row in rows if row.document_type == "OA Approval Request"]
    applicants = {}
    if request_names:
        for row in frappe.get_all("OA Approval Request", filters={"name": ["in", request_names]},
                                  fields=["name", "owner"], limit_page_length=0):
            applicants[row.name] = row.owner
    counts = {key: 0 for key, _ in CATEGORY_LABELS}
    grouped, order = {}, []
    for row in rows:
        bucket, event = classify(row.subject, row.document_type, row.document_name, user, applicants)
        if bucket == "action":
            continue
        if not row.read:
            counts[bucket] = counts.get(bucket, 0) + 1
        if bucket != category:
            continue
        key = f"{row.document_type}:{row.document_name}" if row.document_name else row.name
        if key in grouped:
            grouped[key]["more"] += 1
            grouped[key]["unread"] = grouped[key]["unread"] or not row.read
            grouped[key]["names"].append(row.name)
            continue
        summary = _document_summary(row.document_type, row.document_name)
        grouped[key] = {"event": event or "通知", "title": summary["title"] or event,
                        "detail": summary["detail"], "route": summary["route"], "query": summary["query"],
                        "created": str(row.creation), "unread": not row.read, "more": 0,
                        "names": [row.name], "document": row.document_name or ""}
        order.append(key)
    items = [grouped[key] for key in order]
    if int(unread_only or 0):
        items = [item for item in items if item["unread"]]
    return {"category": category, "categories": [{"key": key, "label": label, "unread": counts.get(key, 0)}
                                                 for key, label in CATEGORY_LABELS],
            "alert_unread": counts.get("mine", 0) + counts.get("cc", 0),
            "items": items[: int(limit or 20)]}


@frappe.whitelist(methods=["POST"])
def mark_notifications_read(names=None, category=None):
    """Mark one group, or a whole category, as read for the signed-in user."""
    from rayher_hr_payroll.api import oa_entry

    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw(frappe._("请先登录。"))
    targets = frappe.parse_json(names) if isinstance(names, str) else (names or [])
    if category:
        feed = get_my_notification_feed(category=category, unread_only=1, limit=400)
        targets = [name for item in feed["items"] for name in item["names"]]
    if not targets:
        return {"marked": 0}
    return oa_entry.mark_my_notifications_read(names=targets)
