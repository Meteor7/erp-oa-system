"""Month-level R&D timesheet entry backed by generated ERPNext Timesheet rows."""

import hashlib
import json
import uuid
from calendar import monthrange
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

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
    if not period_start:
        return rows
    # 修复（2026-09-29，审查 X3-6）：离职员工在离职当天就被停用，离职当月的工时再也登记不进去，
    # 工资却照发。按月份看时，离职日期落在这个月或以后的离职员工仍然可以查看和补登。
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


def _monthly_employee_scope(mode: str, period_start=None) -> list[str] | None:
    if mode not in {"view", "edit"}:
        raise ValueError("mode must be view or edit")
    roles = _roles()
    if roles & RD_MONTHLY_ADMIN_ROLES:
        return None
    if "Department Manager" in roles:
        current = _single_active_linked_rd_employee()
        reports = [_row_name(row) for row in _eligible_employee_rows(period_start, reports_to=current)]
        return sorted({current, *reports})
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
        frappe.throw(frappe._("只能为在职研发员工登记工时；已离职的只能补登离职当月及以前的工时。"))


def _employees_for_scope(scope: list[str] | None, period_start=None) -> list:
    if scope is None:
        return _eligible_employee_rows(period_start)
    if not scope:
        return []
    return _eligible_employee_rows(period_start, name=["in", scope])


def _monthly_summary_employee_filter(employee=None):
    selected = str(employee or "").strip() or None
    if selected:
        _require_monthly_employee(selected, "view")
        return "and ts.employee = %(employee)s", selected, None
    scope = _monthly_employee_scope("view")
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


def calculated_hours(days: Decimal) -> Decimal:
    return (days * HOURS_PER_DAY).quantize(HOUR_QUANTUM, rounding=ROUND_HALF_UP)


def split_day_hours(days: Decimal) -> list[Decimal]:
    full_days = int(days)
    result = [HOURS_PER_DAY] * full_days
    remainder = days - Decimal(full_days)
    if remainder:
        result.append(calculated_hours(remainder))
    return result


def prepare_monthly_rows(raw_rows, year: int, month: int, resolve_project, day_limit=None) -> list[dict]:
    prepared = []
    projects = set()
    total_days = Decimal("0.00")
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

        days = parse_occurrence_days(raw.get("occurrence_days"), year, month)
        total_days += days
        prepared.append(
            {
                "monthly_entry_id": str(raw.get("monthly_entry_id") or "").strip(),
                "project": project,
                "project_code": project_code,
                "project_name": project_name,
                "occurrence_days": days,
                "calculated_hours": calculated_hours(days),
                "remark": str(raw.get("remark") or raw.get("description") or "").strip(),
            }
        )

    day_limit = Decimal(
        str(day_limit if day_limit is not None else monthrange(int(year), int(month))[1])
    )
    if calculated_hours(total_days) > calculated_hours(day_limit):
        frappe.throw(frappe._("该员工当月累计工时不能超过扣除请假后的可填报上限。"))
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
        "rd_occurrence_days": float(Decimal(row["occurrence_days"])),
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


def _query_monthly_entries(period: str, employee=None) -> list:
    employee_filter, selected_employee, visible_employees = _monthly_summary_employee_filter(employee)
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



def _query_legacy_monthly_entries(period: str, employee=None) -> list:
    daily = _daily_module()
    employee_filter, selected_employee, visible_employees = _monthly_summary_employee_filter(employee)
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
        "occurrence_days": round(float(_value(source, "occurrence_days", 0) or 0), 2),
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
            current["occurrence_days"] = round(current["occurrence_days"] + row["occurrence_days"], 2)
            current["hours"] = round(current["hours"] + row["hours"], 2)
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
    total_days = round(sum(float(row["occurrence_days"]) for row in rows), 2)
    total_hours = round(sum(float(row["hours"]) for row in rows), 2)
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
            split_day_hours(row["occurrence_days"]),
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
