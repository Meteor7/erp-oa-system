"""Month-level R&D timesheet entry backed by generated ERPNext Timesheet rows."""

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


def prepare_monthly_rows(raw_rows, year: int, month: int, resolve_project) -> list[dict]:
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

    day_limit = Decimal(monthrange(int(year), int(month))[1])
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
) -> list[dict]:
    logs = []
    last_day = monthrange(int(year), int(month))[1]
    project_key = f"{project_code} | {project_name}" if project_code and project_name else project_code or project_name

    for requested in hour_chunks:
        remaining = Decimal(requested).quantize(HOUR_QUANTUM)
        while remaining > 0:
            chosen_day = None
            used = Decimal("0.00")
            for day in range(1, last_day + 1):
                candidate = datetime(int(year), int(month), day).date()
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
         group by ts.name, ts.rd_monthly_entry_id, ts.employee, e.employee_name,
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


@frappe.whitelist()
def get_monthly_options():
    require_rd_access(RD_MONTHLY_VIEW_ROLES)
    return _daily_module().get_rd_options()


@frappe.whitelist()
def list_monthly_entries(period, employee=None):
    require_rd_access(RD_MONTHLY_VIEW_ROLES)
    year, month = parse_period(period)
    period_text = _canonical_period(year, month)
    rows = []
    for source in _query_monthly_entries(period_text, employee):
        rows.append(
            {
                "monthly_entry_id": _value(source, "monthly_entry_id"),
                "timesheet": _value(source, "timesheet"),
                "employee": _value(source, "employee"),
                "employee_name": _value(source, "employee_name"),
                "period": period_text,
                "project": _value(source, "project"),
                "project_code": _value(source, "project_code"),
                "project_name": _value(source, "project_name"),
                "occurrence_days": round(float(_value(source, "occurrence_days", 0) or 0), 2),
                "hours": round(float(_value(source, "hours", 0) or 0), 2),
                "remark": _value(source, "remark") or "",
                "review_status": _value(source, "review_status") or "",
            }
        )
    total_days = round(sum(float(row["occurrence_days"]) for row in rows), 2)
    total_hours = round(sum(float(row["hours"]) for row in rows), 2)
    return {
        "period": period_text,
        "employee": employee or None,
        "entries": rows,
        "total_days": total_days,
        "total_hours": total_hours,
        "day_limit": monthrange(year, month)[1],
        "legacy_daily_present": bool(employee and _legacy_daily_exists(employee, year, month)),
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
    *, employee: str, period: str, year: int, month: int, rows: list[dict], company: str
) -> None:
    existing = _load_existing_monthly_documents(employee, period)
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
def save_monthly_entries(period, employee, rows):
    require_rd_access(RD_MONTHLY_ENTRY_ROLES)
    year, month = parse_period(period)
    period_text = _canonical_period(year, month)
    employee = str(employee or "").strip()
    if not employee:
        frappe.throw(frappe._("请选择研发人员。"))
    daily = _daily_module()
    daily._require_visible_employee(employee)
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
    prepared = prepare_monthly_rows(rows, year, month, daily._resolve_rd_project)

    lock_period_import(year, month)
    if daily._period_has_submitted_allocation(year, month):
        frappe.throw(frappe._("本期已存在已提交的研发费用分摊，请先撤销分摊后再调整工时。"))
    frappe.db.get_value("Employee", employee, "name", for_update=True)
    if _legacy_daily_exists(employee, year, month):
        frappe.throw(frappe._("该员工本月已有按日工时，不能与按月工时混用。"))

    frappe.db.savepoint(MONTHLY_SAVEPOINT)
    try:
        _replace_monthly_documents(
            employee=employee,
            period=period_text,
            year=year,
            month=month,
            rows=prepared,
            company=daily._company(),
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
