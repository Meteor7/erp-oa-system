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
RD_MONTHLY_ENTRY_ROLES = ("System Manager", "HR User", "HR Manager", "Department Manager")
RD_MONTHLY_VIEW_ROLES = (*RD_MONTHLY_ENTRY_ROLES, "Accounts User", "Employee")
MONTHLY_SAVEPOINT = "rd_monthly_timesheet"


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
    if total_days > day_limit:
        frappe.throw(frappe._("该员工当月累计发生天数不能超过所选月份的自然日天数。"))
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
            """,
            {"employee": employee, "year": year, "month": month},
        )
    )


def _query_monthly_entries(period: str, employee=None) -> list:
    daily = _daily_module()
    employee_filter, selected_employee, visible_employees = daily._summary_employee_filter(employee)
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
    employee_filter, selected_employee, visible_employees = daily._summary_employee_filter(employee)
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
           and coalesce(p.allow_rd_timesheet, 0) = 1
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
def get_monthly_options():
    require_rd_access(RD_MONTHLY_VIEW_ROLES)
    return _daily_module().get_rd_options()


@frappe.whitelist()
def list_monthly_entries(period, employee=None):
    require_rd_access(RD_MONTHLY_VIEW_ROLES)
    year, month = parse_period(period)
    period_text = _canonical_period(year, month)
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
        "calendar_source": limit["calendar_source"],
        "holiday_list": limit["holiday_list"],
        "has_legacy_sources": has_legacy_sources,
        "legacy_daily_present": has_legacy_sources,
    }


def _load_existing_monthly_documents(employee: str, period: str) -> list:
    names = frappe.get_all(
        "Timesheet",
        filters={
            "employee": employee,
            "rd_system_generated": 1,
            "rd_entry_period": period,
            "docstatus": ["<", 2],
        },
        pluck="name",
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
    occupied_hours = {}
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
    daily._require_visible_employee(employee)
    ensure_not_locked(period_text, "lock_timesheets", "工时")
    limit = resolve_monthly_work_limit(year, month, employee=employee)
    if daily._period_has_submitted_allocation(year, month):
        frappe.throw(frappe._("本期已存在已提交的研发费用分摊，请先撤销分摊后再调整工时。"))

    if isinstance(rows, str):
        try:
            rows = json.loads(rows or "[]")
        except ValueError:
            frappe.throw(frappe._("月度工时数据格式不正确。"))
    if not isinstance(rows, list):
        frappe.throw(frappe._("月度工时数据格式不正确。"))
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
    daily._require_visible_employee(employee)
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
