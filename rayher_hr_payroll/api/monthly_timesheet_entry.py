"""Month-level R&D timesheet entry backed by generated ERPNext Timesheet rows."""

import hashlib
import json
import re
import uuid
from calendar import monthrange
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP

import frappe

from rayher_hr_payroll.api._guards import (
    ensure_not_locked,
    lock_period_import,
    parse_period,
    require_rd_access,
)

from rayher_hr_payroll.working_calendar import resolve_monthly_work_limit


DAY_QUANTUM = Decimal("0.01")
HOUR_QUANTUM = Decimal("0.01")
HOURS_PER_DAY = Decimal("8.00")
# 月度工时按小时填（2026-10-12 起）：小时是真实的数，天数只是 小时 ÷ 8 的显示值（保留两位小数）。
# 一天最多 8 小时这条没变：月度上限 = 工作日 × 8 − 已批事假小时，保存时系统自动把小时摊到各个工作日，每天不超过 8 小时。
# 暂时不用填研发工时的人（特例，决定 2026-10-09）：演示员工21的研发人员类型保持“研发辅助”不变，
# 只是不出现在工时填报名单里，也不能登记工时。要恢复填工时，把这个账号从这里删掉即可。
TIMESHEET_EXEMPT_USERS = frozenset({"person046@staff.example.invalid"})
RD_MONTHLY_ENTRY_ROLES = ("System Manager", "HR User", "HR Manager", "Department Manager", "Employee")
RD_MONTHLY_VIEW_ROLES = (*RD_MONTHLY_ENTRY_ROLES, "Accounts User", "Employee")
RD_MONTHLY_ADMIN_ROLES = {"System Manager", "HR User", "HR Manager"}
MONTHLY_SAVEPOINT = "rd_monthly_timesheet"


def _session_user() -> str:
    return str(getattr(getattr(frappe, "session", None), "user", "") or "")


def _roles() -> set[str]:
    return set(frappe.get_roles(_session_user()) or [])


def _as_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year"):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


def _period_start(year: int, month: int):
    return datetime(int(year), int(month), 1).date()


def _eligible_employee_filters(period_start=None, **extra) -> dict:
    filters = {
        "status": ["in", ["Active", "Left"]] if period_start else "Active",
        "rd_personnel_type": ["in", _daily_module().RD_TYPES],
    }
    filters.update(extra)
    return filters


def _eligible_employee_rows(period_start=None, **extra) -> list:
    rows = frappe.get_all(
        "Employee",
        filters=_eligible_employee_filters(period_start, **extra),
        fields=["name", "employee_name", "user_id", "reports_to", "status", "relieving_date"],
        order_by="name",
    )
    rows = [row for row in rows if str(_value(row, "user_id") or "").strip().lower() not in TIMESHEET_EXEMPT_USERS]
    if not period_start:
        return rows
    # 修复（2026-09-29，审查 X3-6）：演示员工166员工在演示员工166当天就被停用，演示员工166当月的工时再也登记不进去，
    # 工资却照发。按月份看时，演示员工166日期落在这个月或以后的演示员工166员工仍然可以查看和补登。
    kept = []
    for row in rows:
        relieved_on = _as_date(_value(row, "relieving_date"))
        if _value(row, "status") != "Left" or (relieved_on and relieved_on >= period_start):
            kept.append(row)
    return kept


def _row_name(row) -> str:
    return str(_value(row, "name") or "")


def _single_active_linked_rd_employee() -> str:
    rows = _eligible_employee_rows(user_id=_session_user())
    if not rows:
        frappe.throw(frappe._("当前账号未关联唯一的在职研发员工，请联系 HR 处理。"))
    if len(rows) > 1:
        frappe.throw(frappe._("当前账号关联了多个在职研发员工，请联系 HR 清理重复关联。"))
    return _row_name(rows[0])


def _team_research_names(manager: str, period_start=None) -> list[str]:
    """部门主管团队里的研发人员：汇报关系向下（直接和间接下属，下属在哪个部门都算），决定 2026-10-12。

    按月份看时带上本月演示员工166的人（和 _eligible_employee_rows 的规则一致）。
    """
    from rayher_hr_payroll.team_scope import team_names

    team = team_names(manager, statuses=("Active", "Left") if period_start else ("Active",))
    if not team:
        return []
    return [_row_name(row) for row in _eligible_employee_rows(period_start, name=["in", team])]


def _monthly_employee_scope(mode: str, period_start=None) -> list[str] | None:
    if mode not in {"view", "edit"}:
        raise ValueError("mode must be view or edit")
    roles = _roles()
    if roles & RD_MONTHLY_ADMIN_ROLES:
        return None
    if "Department Manager" in roles:
        own = _eligible_employee_rows(user_id=_session_user())
        if len(own) > 1:
            frappe.throw(frappe._("当前账号关联了多个在职研发员工，请联系 HR 清理重复关联。"))
        if own:
            current = _row_name(own[0])
            return sorted({current, *_team_research_names(current, period_start)})
        # 修复（2026-09-29，审查 X3-7，决定 D4）：部门经理本人不是研发人员（总经理、财务主管、IT、
        # 生产、人事）时原来直接报"未关联在职研发员工"，页面打不开。现在：有财务角色的按财务只读看全部；
        # 其余看自己名下的研发下属。
        if "Accounts User" in roles and mode == "view":
            return None
        manager = frappe.get_all(
            "Employee", filters={"user_id": _session_user(), "status": "Active"}, fields=["name"],
        )
        if len(manager) != 1:
            return []
        return sorted(_team_research_names(_row_name(manager[0]), period_start))
    if "Accounts User" in roles:
        return None if mode == "view" else []
    if "Employee" in roles:
        return [_single_active_linked_rd_employee()]
    return []


def _require_monthly_employee(employee: str, mode: str, period_start=None) -> None:
    employee = str(employee or "").strip()
    scope = _monthly_employee_scope(mode, period_start)
    if scope is not None and employee not in scope:
        frappe.throw(frappe._("您无权查看或登记该员工的工时。"))
    if mode == "edit" and not _eligible_employee_rows(period_start, name=employee):
        frappe.throw(frappe._("只能为在职研发员工登记工时；已演示员工166的只能补登演示员工166当月及以前的工时。"))


def _employees_for_scope(scope: list[str] | None, period_start=None) -> list:
    if scope is None:
        return _eligible_employee_rows(period_start)
    if not scope:
        return []
    return _eligible_employee_rows(period_start, name=["in", scope])


def _monthly_summary_employee_filter(employee=None, period_start=None, employees=None):
    """查询工时记录时的员工范围。

    修复（2026-10-13）：原来不带月份算范围（只有在职的人），部门主管看这个月时，本月演示员工166的下属明明在填报名单里，
    他填的工时却查不出来，填报进度里显示成“一点没填”。现在按月份算范围（和名单同一个规则）；
    employees 给了（填报进度的名单）就直接按名单查，调用方已经按身份定好了范围。
    """
    if employees is not None:
        return "and ts.employee in %(employees)s", None, tuple(employees or ["__none__"])
    selected = str(employee or "").strip() or None
    if selected:
        _require_monthly_employee(selected, "view", period_start)
        return "and ts.employee = %(employee)s", selected, None
    scope = _monthly_employee_scope("view", period_start)
    if scope is None:
        return "", None, None
    return "and ts.employee in %(employees)s", None, tuple(scope or ["__none__"])


def parse_occurrence_days(value, year: int, month: int) -> Decimal:
    text = str(value if value is not None else "").strip()
    try:
        days = Decimal(text)
    except (InvalidOperation, ValueError):
        frappe.throw(frappe._("发生天数必须是有效数字。"))

    if not days.is_finite() or days <= 0:
        frappe.throw(frappe._("发生天数必须大于 0。"))
    if days.as_tuple().exponent < -2:
        frappe.throw(frappe._("发生天数最多保留两位小数。"))

    day_limit = Decimal(monthrange(int(year), int(month))[1])
    days = days.quantize(DAY_QUANTUM, rounding=ROUND_HALF_UP)
    if days > day_limit:
        frappe.throw(frappe._("发生天数不能超过所选月份的自然日天数。"))
    return days


def parse_occurrence_hours(value, year: int, month: int) -> Decimal:
    """一条月度工时的小时数：大于 0，最多两位小数，不超过当月自然日 × 8 小时。"""
    text = str(value if value is not None else "").strip()
    try:
        hours = Decimal(text)
    except (InvalidOperation, ValueError):
        frappe.throw(frappe._("工时必须是有效数字。"))

    if not hours.is_finite() or hours <= 0:
        frappe.throw(frappe._("工时必须大于 0。"))
    if hours.as_tuple().exponent < -2:
        frappe.throw(frappe._("工时最多保留两位小数。"))

    ceiling = Decimal(monthrange(int(year), int(month))[1]) * HOURS_PER_DAY
    hours = hours.quantize(HOUR_QUANTUM, rounding=ROUND_HALF_UP)
    if hours > ceiling:
        frappe.throw(frappe._("工时不能超过所选月份自然日天数 × 8 小时。"))
    return hours


def days_from_hours(hours) -> Decimal:
    """小时反推的天数（显示用，保留两位小数）：1 天 = 8 小时。"""
    return (_as_decimal(hours) / HOURS_PER_DAY).quantize(DAY_QUANTUM, rounding=ROUND_HALF_UP)


def calculated_hours(days: Decimal) -> Decimal:
    return (days * HOURS_PER_DAY).quantize(HOUR_QUANTUM, rounding=ROUND_HALF_UP)


def _as_decimal(value) -> Decimal:
    try:
        number = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return number if number.is_finite() else Decimal("0")


def display_days(hours) -> float:
    """页面上显示的天数（小时 ÷ 8，两位小数）。"""
    return float(days_from_hours(hours))


def split_day_hours(days: Decimal) -> list[Decimal]:
    full_days = int(days)
    result = [HOURS_PER_DAY] * full_days
    remainder = days - Decimal(full_days)
    if remainder:
        result.append(calculated_hours(remainder))
    return result


def split_hour_chunks(hours) -> list[Decimal]:
    """小时拆成每天最多 8 小时的块：整 8 小时若干块，余下的一块（保存时按块摊到工作日）。"""
    total = _as_decimal(hours).quantize(HOUR_QUANTUM, rounding=ROUND_HALF_UP)
    full_days = int(total // HOURS_PER_DAY)
    result = [HOURS_PER_DAY] * full_days
    remainder = (total - HOURS_PER_DAY * full_days).quantize(HOUR_QUANTUM)
    if remainder > 0:
        result.append(remainder)
    return result


def _row_hours(raw: dict, year: int, month: int) -> Decimal:
    """这一行填的小时：优先用 hours；老的调用方只给 occurrence_days 时按 天 × 8 换算。"""
    value = raw.get("hours")
    if value is not None and str(value).strip() != "":
        return parse_occurrence_hours(value, year, month)
    return calculated_hours(parse_occurrence_days(raw.get("occurrence_days"), year, month))


def prepare_monthly_rows(raw_rows, year: int, month: int, resolve_project, day_limit=None, hour_limit=None) -> list[dict]:
    prepared = []
    projects = set()
    total_hours = Decimal("0.00")
    for raw in raw_rows or []:
        if not isinstance(raw, dict):
            frappe.throw(frappe._("月度工时明细格式不正确。"))
        project_code = str(raw.get("project_code") or "").strip()
        project_name = str(raw.get("project_name") or "").strip()
        selected_project = str(raw.get("project") or "").strip() or None
        project = resolve_project(project_code, project_name, selected_project)
        if project in projects:
            frappe.throw(frappe._("同一员工、月份和项目只能填写一条月度工时。"))
        projects.add(project)

        hours = _row_hours(raw, year, month)
        total_hours += hours
        prepared.append(
            {
                "monthly_entry_id": str(raw.get("monthly_entry_id") or "").strip(),
                "project": project,
                "project_code": project_code,
                "project_name": project_name,
                "occurrence_days": days_from_hours(hours),
                "calculated_hours": hours,
                "remark": str(raw.get("remark") or raw.get("description") or "").strip(),
            }
        )

    if hour_limit is not None:
        limit_hours = Decimal(str(hour_limit))
    else:
        days = day_limit if day_limit is not None else monthrange(int(year), int(month))[1]
        limit_hours = Decimal(str(days)) * HOURS_PER_DAY
    if total_hours > limit_hours:
        frappe.throw(
            frappe._("该员工当月累计工时不能超过扣除请假后的可填报上限：当前 {0} 小时，本月最多 {1} 小时（约 {2} 天）。").format(
                f"{total_hours:f}".rstrip("0").rstrip("."), f"{limit_hours:f}".rstrip("0").rstrip("."), days_from_hours(limit_hours)
            )
        )
    return prepared


def build_technical_time_logs(
    year: int,
    month: int,
    hour_chunks: list[Decimal],
    *,
    project: str,
    project_code: str,
    project_name: str,
    remark: str,
    occupied_hours: dict,
    work_dates=None,
) -> list[dict]:
    logs = []
    eligible_dates = list(work_dates) if work_dates is not None else [
        datetime(int(year), int(month), day).date()
        for day in range(1, monthrange(int(year), int(month))[1] + 1)
    ]
    project_key = f"{project_code} | {project_name}" if project_code and project_name else project_code or project_name

    for requested in hour_chunks:
        remaining = Decimal(requested).quantize(HOUR_QUANTUM)
        while remaining > 0:
            chosen_day = None
            used = Decimal("0.00")
            for candidate in eligible_dates:
                candidate_used = Decimal(str(occupied_hours.get(candidate, 0))).quantize(HOUR_QUANTUM)
                if candidate_used < HOURS_PER_DAY:
                    chosen_day = candidate
                    used = candidate_used
                    break
            if chosen_day is None:
                frappe.throw(frappe._("所选月份已没有可分配的内部工时日期。"))

            allocated = min(remaining, HOURS_PER_DAY - used).quantize(HOUR_QUANTUM)
            from_time = datetime.combine(chosen_day, datetime.min.time()) + timedelta(
                seconds=int(used * Decimal(3600))
            )
            to_time = from_time + timedelta(seconds=int(allocated * Decimal(3600)))
            logs.append(
                {
                    "activity_type": "编码开发",
                    "project": project,
                    "rd_project_code": project_code,
                    "rd_project_name": project_name,
                    "rd_project_key": project_key,
                    "hours": float(allocated),
                    "from_time": from_time,
                    "to_time": to_time,
                    "description": remark,
                }
            )
            occupied_hours[chosen_day] = used + allocated
            remaining -= allocated
    return logs


def build_timesheet_payload(
    *,
    employee: str,
    company: str,
    period: str,
    entry_id: str,
    row: dict,
    time_logs: list[dict],
) -> dict:
    expected = Decimal(row["calculated_hours"]).quantize(HOUR_QUANTUM)
    actual = sum((Decimal(str(log.get("hours") or 0)) for log in time_logs), Decimal("0.00")).quantize(
        HOUR_QUANTUM
    )
    if actual != expected:
        frappe.throw(frappe._("系统生成的工时明细与月度折算工时不一致。"))
    return {
        "doctype": "Timesheet",
        "company": company,
        "employee": employee,
        "rd_spa_managed": 1,
        "rd_system_generated": 1,
        "rd_monthly_entry_id": entry_id,
        "rd_entry_period": period,
        "rd_occurrence_days": float(days_from_hours(expected)),
        "rd_calculated_hours": float(expected),
        "time_logs": time_logs,
    }


def _daily_module():
    from rayher_hr_payroll.api import timesheet_entry

    return timesheet_entry


def _value(row, fieldname, default=None):
    if isinstance(row, dict):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def _canonical_period(year: int, month: int) -> str:
    return f"{int(year):04d}-{int(month):02d}"


def _monthly_revision(sources) -> str:
    snapshot = [
        {
            "name": str(_value(source, "timesheet") or _value(source, "name") or ""),
            "monthly_entry_id": str(_value(source, "monthly_entry_id") or _value(source, "rd_monthly_entry_id") or ""),
            "modified": str(_value(source, "modified") or ""),
        }
        for source in (sources or [])
    ]
    snapshot.sort(key=lambda item: (item["name"], item["monthly_entry_id"], item["modified"]))
    payload = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _legacy_daily_exists(employee: str, year: int, month: int) -> bool:
    return bool(
        frappe.db.sql(
            """
            select 1
              from `tabTimesheet Detail` tsd
              inner join `tabTimesheet` ts on ts.name = tsd.parent
             where ts.employee = %(employee)s
               and ts.docstatus < 2
               and coalesce(ts.rd_system_generated, 0) = 0
               and year(tsd.from_time) = %(year)s
               and month(tsd.from_time) = %(month)s
             limit 1
             for update
            """,
            {"employee": employee, "year": year, "month": month},
        )
    )


def _period_start_of(period: str):
    year, month = parse_period(period)
    return _period_start(year, month)


def _query_monthly_entries(period: str, employee=None, employees=None) -> list:
    employee_filter, selected_employee, visible_employees = _monthly_summary_employee_filter(employee, _period_start_of(period), employees)
    return frappe.db.sql(
        f"""
        select ts.rd_monthly_entry_id as monthly_entry_id,
               ts.name as timesheet,
               ts.modified,
               ts.employee,
               e.employee_name,
               ts.rd_entry_period as period,
               ts.rd_occurrence_days as occurrence_days,
               ts.rd_calculated_hours as hours,
               min(tsd.project) as project,
               coalesce(nullif(min(tsd.rd_project_code), ''), min(p.rd_project_code)) as project_code,
               coalesce(nullif(min(tsd.rd_project_name), ''), min(p.project_name)) as project_name,
               max(tsd.description) as remark,
               ts.rd_review_status as review_status
          from `tabTimesheet` ts
          inner join `tabTimesheet Detail` tsd on tsd.parent = ts.name
          inner join `tabEmployee` e on e.name = ts.employee
          inner join `tabProject` p on p.name = tsd.project
         where ts.docstatus = 1
           and coalesce(ts.rd_system_generated, 0) = 1
           and ts.rd_entry_period = %(period)s
           {employee_filter}
         group by ts.name, ts.rd_monthly_entry_id, ts.modified, ts.employee, e.employee_name,
                  ts.rd_entry_period, ts.rd_occurrence_days, ts.rd_calculated_hours,
                  ts.rd_review_status
         order by e.employee_name, project_code, project_name
        """,
        {
            "period": period,
            "employee": selected_employee,
            "employees": visible_employees or ("__none__",),
        },
        as_dict=True,
    )



def _query_legacy_monthly_entries(period: str, employee=None, employees=None) -> list:
    daily = _daily_module()
    employee_filter, selected_employee, visible_employees = _monthly_summary_employee_filter(employee, _period_start_of(period), employees)
    return frappe.db.sql(
        f"""
        select ts.employee,
               e.employee_name,
               tsd.project,
               coalesce(nullif(tsd.rd_project_code, ''), p.rd_project_code) as project_code,
               coalesce(nullif(tsd.rd_project_name, ''), p.project_name) as project_name,
               round(sum(tsd.hours) / 8, 2) as occurrence_days,
               round(sum(tsd.hours), 2) as hours,
               group_concat(
                   distinct nullif(trim(tsd.description), '')
                   order by trim(tsd.description)
                   separator '；'
               ) as remark,
               'legacy_daily' as source_kind
          from `tabTimesheet Detail` tsd
          inner join `tabTimesheet` ts on ts.name = tsd.parent
          inner join `tabEmployee` e on e.name = ts.employee
          inner join `tabProject` p on p.name = tsd.project
         where ts.docstatus = 1
           and coalesce(ts.rd_system_generated, 0) = 0
           and date_format(tsd.from_time, '%%Y-%%m') = %(period)s
           and e.rd_personnel_type in %(types)s
           and coalesce(p.rd_project_code, '') != ''
           {employee_filter}
         group by ts.employee, e.employee_name, tsd.project,
                  coalesce(nullif(tsd.rd_project_code, ''), p.rd_project_code),
                  coalesce(nullif(tsd.rd_project_name, ''), p.project_name)
         order by e.employee_name, project_code, project_name
        """,
        {
            "period": period,
            "types": daily.RD_TYPES,
            "employee": selected_employee,
            "employees": visible_employees or ("__none__",),
        },
        as_dict=True,
    )


def _monthly_view_row(source, period: str, source_kind: str) -> dict:
    employee = str(_value(source, "employee") or "")
    project = str(_value(source, "project") or "")
    monthly_entry_id = _value(source, "monthly_entry_id")
    if source_kind == "legacy_daily":
        monthly_entry_id = f"legacy:{period}:{employee}:{project}"
    return {
        "monthly_entry_id": monthly_entry_id,
        "timesheet": _value(source, "timesheet"),
        "employee": employee,
        "employee_name": _value(source, "employee_name") or "",
        "period": period,
        "project": project,
        "project_code": _value(source, "project_code") or "",
        "project_name": _value(source, "project_name") or "",
        "occurrence_days": display_days(_value(source, "hours", 0) or 0),
        "hours": round(float(_value(source, "hours", 0) or 0), 2),
        "remark": _value(source, "remark") or "",
        "review_status": _value(source, "review_status") or "",
        "source_kind": source_kind,
        "editable": source_kind == "monthly",
    }


def _merge_monthly_entry_rows(monthly_rows: list, legacy_rows: list, period: str) -> list[dict]:
    grouped = {}
    for source_kind, sources in (("monthly", monthly_rows or []), ("legacy_daily", legacy_rows or [])):
        for source in sources:
            row = _monthly_view_row(source, period, source_kind)
            key = (row["employee"], row["project"])
            current = grouped.get(key)
            if current is None:
                grouped[key] = row
                continue
            current["hours"] = round(current["hours"] + row["hours"], 2)
            current["occurrence_days"] = display_days(current["hours"])
            remarks = []
            for value in (current.get("remark"), row.get("remark")):
                for item in str(value or "").split("；"):
                    item = item.strip()
                    if item and item not in remarks:
                        remarks.append(item)
            current["remark"] = "；".join(remarks)
            current["source_kind"] = "mixed" if current["source_kind"] != row["source_kind"] else current["source_kind"]
            current["editable"] = current["source_kind"] == "monthly"
            if current["source_kind"] == "mixed":
                current["monthly_entry_id"] = f"mixed:{period}:{row['employee']}:{row['project']}"
                current["timesheet"] = None
    return sorted(
        grouped.values(),
        key=lambda row: (row["employee_name"], row["project_code"], row["project_name"], row["project"]),
    )


@frappe.whitelist()
def get_monthly_options(period=None):
    require_rd_access(RD_MONTHLY_VIEW_ROLES)
    period_start = _period_start(*parse_period(period)) if period else None
    options = dict(_daily_module().get_rd_options())
    visible = _employees_for_scope(_monthly_employee_scope("view", period_start), period_start)
    editable = _employees_for_scope(_monthly_employee_scope("edit", period_start), period_start)
    options["employees"] = [
        {"name": _row_name(row), "employee_name": str(_value(row, "employee_name") or "")}
        for row in visible
    ]
    options["editable_employees"] = [_row_name(row) for row in editable]
    return options


@frappe.whitelist()
def list_monthly_entries(period, employee=None):
    require_rd_access(RD_MONTHLY_VIEW_ROLES)
    year, month = parse_period(period)
    period_text = _canonical_period(year, month)
    if employee:
        _require_monthly_employee(employee, "view", _period_start(year, month))
    monthly_rows = _query_monthly_entries(period_text, employee)
    rows = _merge_monthly_entry_rows(
        monthly_rows,
        _query_legacy_monthly_entries(period_text, employee),
        period_text,
    )
    total_hours = round(sum(float(row["hours"]) for row in rows), 2)
    total_days = display_days(total_hours)
    has_legacy_sources = any(row["source_kind"] in {"legacy_daily", "mixed"} for row in rows)
    employee_count = len({row["employee"] for row in rows if row["employee"]})
    limit = resolve_monthly_work_limit(
        year,
        month,
        employee=employee or None,
    )
    return {
        "period": period_text,
        "employee": employee or None,
        "revision": _monthly_revision(monthly_rows) if employee else None,
        "entries": rows,
        "total_days": total_days,
        "total_hours": total_hours,
        "employee_count": employee_count,
        "day_limit": limit["day_limit"],
        "max_day_limit": display_days(limit["hour_limit"]),
        "hour_limit": limit["hour_limit"],
        "base_hour_limit": limit.get("base_hour_limit", limit["hour_limit"]),
        "leave_hours": limit.get("leave_hours", 0),
        "over_limit_hours": max(0, round(total_hours - limit["hour_limit"], 2)) if employee else 0,
        "calendar_source": limit["calendar_source"],
        "holiday_list": limit["holiday_list"],
        "joined_on": limit.get("joined_on") if employee else None,
        "relieved_on": limit.get("relieved_on") if employee else None,
        "has_legacy_sources": has_legacy_sources,
        "legacy_daily_present": has_legacy_sources,
    }


def _load_existing_monthly_documents(employee: str, period: str) -> list:
    # 修复（2026-09-29，审查第一轮 #9）：员工行加锁后当前读（get_all 不支持 for_update）。
    # 原来是快照读，两个请求同时首次保存同一员工同一月时，都看到"还没有月度工时"，
    # 各插入一整套，超出月度上限。
    names = frappe.db.get_values(
        "Timesheet",
        {
            "employee": employee,
            "rd_system_generated": 1,
            "rd_entry_period": period,
            "docstatus": ["<", 2],
        },
        "name",
        for_update=True,
        pluck=True,
    )
    return [frappe.get_doc("Timesheet", name) for name in names]


def _delete_monthly_document(doc, employee: str, period: str) -> None:
    if not doc.get("rd_system_generated") or doc.get("rd_entry_period") != period or doc.employee != employee:
        frappe.throw(frappe._("月度工时记录归属校验失败，已停止替换。"))
    if doc.docstatus == 1:
        doc.flags.ignore_permissions = True
        doc.cancel()
    frappe.delete_doc("Timesheet", doc.name, force=True, ignore_permissions=True)


def _replace_monthly_documents(
    *,
    employee: str,
    period: str,
    year: int,
    month: int,
    rows: list[dict],
    company: str,
    expected_revision: str,
    work_dates=None,
    leave_hours_by_date=None,
) -> None:
    existing = _load_existing_monthly_documents(employee, period)
    if _monthly_revision(existing) != expected_revision:
        frappe.throw(frappe._("\u6708\u5ea6\u5de5\u65f6\u6570\u636e\u5df2\u88ab\u5176\u4ed6\u7528\u6237\u66f4\u65b0\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002"))
    existing_ids = {str(doc.get("rd_monthly_entry_id") or "") for doc in existing}
    requested_ids = [row["monthly_entry_id"] for row in rows if row.get("monthly_entry_id")]
    if len(requested_ids) != len(set(requested_ids)):
        frappe.throw(frappe._("月度工时记录编号重复。"))
    if not set(requested_ids).issubset(existing_ids):
        frappe.throw(frappe._("提交的月度工时记录编号不属于当前员工和月份。"))

    for doc in existing:
        _delete_monthly_document(doc, employee, period)

    _daily_module()._ensure_activity()
    # 修复（2026-09-29，审查 X2-7）：已批准的事假先占住那天的小时数。原来从空表开始摊，
    # 上限虽然扣了请假，工时却照样排在请假那天，同一天既请假又有 8 小时研发工时。
    occupied_hours = {
        _as_date(day): Decimal(str(hours)).quantize(HOUR_QUANTUM)
        for day, hours in (leave_hours_by_date or {}).items()
    }
    for row in rows:
        entry_id = row.get("monthly_entry_id") or uuid.uuid4().hex
        logs = build_technical_time_logs(
            year,
            month,
            split_hour_chunks(row["calculated_hours"]),
            project=row["project"],
            project_code=row["project_code"],
            project_name=row["project_name"],
            remark=row["remark"],
            occupied_hours=occupied_hours,
            work_dates=work_dates,
        )
        payload = build_timesheet_payload(
            employee=employee,
            company=company,
            period=period,
            entry_id=entry_id,
            row=row,
            time_logs=logs,
        )
        doc = frappe.get_doc(payload)
        doc.insert(ignore_permissions=True)
        doc.flags.ignore_permissions = True
        doc.submit()


@frappe.whitelist(methods=["POST"])
def save_monthly_entries(period, employee, rows, expected_revision=None):
    require_rd_access(RD_MONTHLY_ENTRY_ROLES)
    year, month = parse_period(period)
    period_text = _canonical_period(year, month)
    employee = str(employee or "").strip()
    if not employee:
        frappe.throw(frappe._("请选择研发人员。"))
    expected_revision = str(expected_revision or "").strip()
    if not expected_revision:
        frappe.throw(frappe._("\u6708\u5ea6\u5de5\u65f6\u6570\u636e\u7248\u672c\u5df2\u5931\u6548\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002"))
    daily = _daily_module()
    _require_monthly_employee(employee, "edit", _period_start(year, month))
    ensure_not_locked(period_text, "lock_timesheets", "工时")
    if daily._period_has_submitted_allocation(year, month):
        frappe.throw(frappe._("本期已存在已提交的研发费用分摊，请先撤销分摊后再调整工时。"))

    if isinstance(rows, str):
        try:
            rows = json.loads(rows or "[]")
        except ValueError:
            frappe.throw(frappe._("月度工时数据格式不正确。"))
    if not isinstance(rows, list):
        frappe.throw(frappe._("月度工时数据格式不正确。"))
    lock_period_import(year, month)
    frappe.db.get_value("Employee", employee, "name", for_update=True)
    limit = resolve_monthly_work_limit(year, month, employee=employee, lock=True)
    prepared = prepare_monthly_rows(
        rows,
        year,
        month,
        daily._resolve_rd_project,
        day_limit=Decimal(str(limit["day_limit"])),
        hour_limit=Decimal(str(limit["hour_limit"])) if limit.get("hour_limit") is not None else None,
    )

    lock_period_import(year, month)
    if daily._period_has_submitted_allocation(year, month):
        frappe.throw(frappe._("本期已存在已提交的研发费用分摊，请先撤销分摊后再调整工时。"))
    frappe.db.get_value("Employee", employee, "name", for_update=True)
    if _legacy_daily_exists(employee, year, month):
        frappe.throw(frappe._("该员工本月已有按日工时，不能与按月工时混用。"))
    company = frappe.db.get_value("Employee", employee, "company") or daily._company()

    frappe.db.savepoint(MONTHLY_SAVEPOINT)
    try:
        _replace_monthly_documents(
            employee=employee,
            period=period_text,
            year=year,
            month=month,
            rows=prepared,
            company=company,
            expected_revision=expected_revision,
            work_dates=limit["work_dates"],
            leave_hours_by_date=limit.get("leave_hours_by_date"),
        )
    except Exception:
        frappe.db.rollback(save_point=MONTHLY_SAVEPOINT)
        raise
    frappe.db.commit()
    return list_monthly_entries(period_text, employee=employee)


@frappe.whitelist(methods=["POST"])
def delete_monthly_entry(monthly_entry_id):
    require_rd_access(RD_MONTHLY_ENTRY_ROLES)
    entry_id = str(monthly_entry_id or "").strip()
    name = frappe.db.get_value("Timesheet", {"rd_monthly_entry_id": entry_id}, "name")
    if not name:
        frappe.throw(frappe._("月度工时记录不存在或已删除。"))
    doc = frappe.get_doc("Timesheet", name)
    period = str(doc.get("rd_entry_period") or "").strip()
    if not doc.get("rd_system_generated") or doc.get("rd_monthly_entry_id") != entry_id:
        frappe.throw(frappe._("该记录不是系统生成的月度工时。"))

    year, month = parse_period(period)
    employee = doc.employee
    daily = _daily_module()
    _require_monthly_employee(employee, "edit", _period_start(year, month))
    ensure_not_locked(period, "lock_timesheets", "工时")
    lock_period_import(year, month)
    if daily._period_has_submitted_allocation(year, month):
        frappe.throw(frappe._("本期已存在已提交的研发费用分摊，请先撤销分摊后再删除工时。"))
    frappe.db.get_value("Employee", employee, "name", for_update=True)

    frappe.db.savepoint(MONTHLY_SAVEPOINT)
    try:
        _delete_monthly_document(doc, employee, period)
    except Exception:
        frappe.db.rollback(save_point=MONTHLY_SAVEPOINT)
        raise
    frappe.db.commit()
    return list_monthly_entries(period, employee=employee)


# ---------------------------------------------------------------------------
# 填报进度：部门主管看本部门成员有没有填，老板 / 财务 / 人事看全部人。
# ---------------------------------------------------------------------------
FILL_REMIND_ROLES = RD_MONTHLY_ADMIN_ROLES | {"Department Manager"}
FILL_REMINDER_PREFIX = "rd-fill:"


def _department_label(value) -> str:
    """ERPNext 部门名带公司后缀（"研发一部 - RAY"），页面上只显示前面的部门名。"""
    return re.sub(r"\s+-\s+[A-Za-z0-9]{1,8}$", "", str(value or "").strip())


def _fill_status(used_hours, limit_hours) -> str:
    """none 一天没填；over 超过上限；full 已填满；part 还没填满。

    都按小时比较（两位小数）：填的小时等于可填小时才算已填满，不再有"零头容差"。
    例：可填 173 小时时，填 173 = 已填满，172.5 = 未填满，173.5 = 超上限。
    """
    used = _as_decimal(used_hours).quantize(HOUR_QUANTUM, rounding=ROUND_HALF_UP)
    limit = _as_decimal(limit_hours).quantize(HOUR_QUANTUM, rounding=ROUND_HALF_UP)
    if used <= 0:
        return "none" if limit > 0 else "full"
    if used > limit:
        return "over"
    return "full" if used == limit else "part"


def _limit_hours(limit) -> float:
    """一个月可填的小时数：用 hour_limit；只有 day_limit 的（老数据、测试替身）按 天 × 8。"""
    if limit.get("hour_limit") is not None:
        return float(limit["hour_limit"])
    return float(limit.get("day_limit") or 0) * float(HOURS_PER_DAY)


def _fill_scope_kind(scope) -> str:
    if scope is None:
        return "all"
    return "team" if "Department Manager" in _roles() else "self"


def _fill_rows(year: int, month: int, scope) -> list[dict]:
    period_text = _canonical_period(year, month)
    start = _period_start(year, month)
    employees = _employees_for_scope(scope, start)
    names = [_row_name(row) for row in employees]
    if not names:
        return []
    info = {
        _row_name(row): row
        for row in frappe.get_all(
            "Employee", filters={"name": ["in", names]},
            fields=["name", "employee_name", "department", "user_id"], limit_page_length=0,
        )
    }
    used = {}
    # 已填的工时按名单里的人查（名单含本月演示员工166的人），不再另算一次范围。
    for row in _merge_monthly_entry_rows(
        _query_monthly_entries(period_text, employees=names), _query_legacy_monthly_entries(period_text, employees=names), period_text
    ):
        used[row["employee"]] = round(used.get(row["employee"], 0) + float(row["hours"]), 2)
    result = []
    for name in names:
        detail = info.get(name) or {}
        limit_hours = _limit_hours(resolve_monthly_work_limit(year, month, employee=name))
        used_hours = round(used.get(name, 0), 2)
        result.append({
            "employee": name,
            "employee_name": str(_value(detail, "employee_name") or _value(next((r for r in employees if _row_name(r) == name), {}), "employee_name") or name),
            "department": _department_label(_value(detail, "department")),
            "user_id": str(_value(detail, "user_id") or ""),
            # 小时是真实的数；天数 = 小时 ÷ 8，只用来显示。状态按小时判定，和保存时的校验一致。
            "used_hours": used_hours,
            "limit_hours": round(limit_hours, 2),
            "used_days": display_days(used_hours),
            "limit_days": display_days(limit_hours),
            "status": _fill_status(used_hours, limit_hours),
        })
    return result


def _last_reminders(period_text: str, names: list[str]) -> dict:
    if not names:
        return {}
    rows = frappe.get_all(
        "Notification Log",
        filters={"document_type": "Employee", "document_name": ["in", names], "subject": ["like", f"%[{FILL_REMINDER_PREFIX}{period_text}]"]},
        fields=["document_name", "creation"], order_by="creation desc", limit_page_length=0,
    )
    latest = {}
    for row in rows:
        latest.setdefault(str(_value(row, "document_name")), str(_value(row, "creation") or "")[:16])
    return latest


@frappe.whitelist()
def get_fill_progress(period):
    require_rd_access(RD_MONTHLY_VIEW_ROLES)
    year, month = parse_period(period)
    period_text = _canonical_period(year, month)
    scope = _monthly_employee_scope("view", _period_start(year, month))
    kind = _fill_scope_kind(scope)
    last_day = monthrange(year, month)[1]
    result = {
        "period": period_text, "kind": kind,
        "can_remind": bool(kind != "self" and _roles() & FILL_REMIND_ROLES),
        "deadline": f"{year:04d}-{month:02d}-{last_day:02d}",
        "summary": {"total": 0, "full": 0, "part": 0, "none": 0, "over": 0, "rate": 0},
        "employees": [],
    }
    if kind == "self":
        return result
    rows = _fill_rows(year, month, scope)
    reminded = _last_reminders(period_text, [row["employee"] for row in rows])
    for row in rows:
        row.pop("user_id", None)
        row["last_reminded"] = reminded.get(row["employee"], "")
    counts = {key: sum(1 for row in rows if row["status"] == key) for key in ("full", "part", "none", "over")}
    result["summary"] = {
        "total": len(rows), **counts,
        "rate": round(counts["full"] / len(rows) * 100, 1) if rows else 0,
    }
    result["employees"] = rows
    return result


@frappe.whitelist(methods=["POST"])
def remind_timesheet_fill(period, employees):
    require_rd_access(RD_MONTHLY_VIEW_ROLES)
    if not _roles() & FILL_REMIND_ROLES:
        frappe.throw(frappe._("只有部门主管、人事或演示员工170可以催办填报。"))
    year, month = parse_period(period)
    period_text = _canonical_period(year, month)
    start = _period_start(year, month)
    try:
        wanted = json.loads(employees) if isinstance(employees, str) else list(employees or [])
    except (TypeError, ValueError):
        frappe.throw(frappe._("催办名单格式无效。"))
    wanted = [str(item).strip() for item in wanted if str(item).strip()]
    if not wanted or len(wanted) > 500:
        frappe.throw(frappe._("请选择 1 到 500 位需要催办的员工。"))
    for name in wanted:
        _require_monthly_employee(name, "view", start)
    scope = _monthly_employee_scope("view", start)
    rows = {row["employee"]: row for row in _fill_rows(year, month, scope)}
    today = frappe.utils.nowdate() if hasattr(frappe.utils, "nowdate") else datetime.now().strftime("%Y-%m-%d")
    already = {name: stamp for name, stamp in _last_reminders(period_text, wanted).items() if stamp.startswith(today)}
    sender = frappe.utils.get_fullname(_session_user()) if hasattr(frappe.utils, "get_fullname") else _session_user()
    last_day = monthrange(year, month)[1]
    sent = skipped_today = skipped_done = 0
    for name in wanted:
        row = rows.get(name)
        if not row or row["status"] not in {"none", "part"}:
            skipped_done += 1
            continue
        if name in already:
            skipped_today += 1
            continue
        user = row["user_id"]
        if not user or not frappe.db.exists("User", {"name": user, "enabled": 1}):
            skipped_done += 1
            continue
        frappe.get_doc({
            "doctype": "Notification Log", "for_user": user, "type": "Alert",
            "document_type": "Employee", "document_name": name,
            "subject": f"请填报 {period_text} 研发工时 [{FILL_REMINDER_PREFIX}{period_text}]",
            "email_content": (
                f"{sender or '部门主管'} 提醒你：{period_text} 的研发工时还没填满"
                f"（已填 {row['used_days']:g} / 上限 {row['limit_days']:g} 天），请在 {year:04d}-{month:02d}-{last_day:02d} 前完成。"
            ),
            "link": "/planck-semicon/entry",
        }).insert(ignore_permissions=True)
        sent += 1
    return {"sent": sent, "skipped_today": skipped_today, "skipped_done": skipped_done}
