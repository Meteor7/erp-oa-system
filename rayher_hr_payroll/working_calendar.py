"""Resolve monthly employee work limits from ERPNext holiday calendars."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

import frappe
from frappe.utils import getdate

HOURS_PER_WORKDAY = 8


def _row_value(row, fieldname, default=None):
    if isinstance(row, dict):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def count_work_dates(year, month, holiday_dates):
    dates = [date(int(year), int(month), day) for day in range(1, monthrange(int(year), int(month))[1] + 1)]
    if holiday_dates is None:
        return [value for value in dates if value.weekday() < 5]
    excluded = {getdate(value) for value in holiday_dates}
    return [value for value in dates if value not in excluded]


def _complete_holiday_list(name, first_day, last_day):
    if not name:
        return False
    row = frappe.db.get_value(
        "Holiday List", name, ["from_date", "to_date"], as_dict=True
    )
    if not row:
        return False
    from_date = getdate(_row_value(row, "from_date"))
    to_date = getdate(_row_value(row, "to_date"))
    return from_date <= first_day and to_date >= last_day


def resolve_monthly_calendar(year, month, employee=None, company=None):
    year = int(year)
    month = int(month)
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    employee_holiday_list = ""
    joined_on = relieved_on = None

    if employee:
        row = frappe.db.get_value(
            "Employee", employee, ["holiday_list", "company", "date_of_joining", "relieving_date"], as_dict=True
        ) or {}
        employee_holiday_list = str(_row_value(row, "holiday_list") or "")
        company = company or _row_value(row, "company")
        joined_on = _row_value(row, "date_of_joining")
        relieved_on = _row_value(row, "relieving_date")

    if not company and hasattr(frappe.db, "get_single_value"):
        company = frappe.db.get_single_value("Global Defaults", "default_company")

    company_holiday_list = ""
    if company:
        company_row = frappe.db.get_value(
            "Company", company, ["default_holiday_list"], as_dict=True
        )
        if isinstance(company_row, str):
            company_holiday_list = company_row
        else:
            company_holiday_list = str(
                _row_value(company_row or {}, "default_holiday_list") or ""
            )

    selected_list = ""
    source = "weekday_fallback"
    if _complete_holiday_list(employee_holiday_list, first_day, last_day):
        selected_list = employee_holiday_list
        source = "employee_holiday_list"
    elif _complete_holiday_list(company_holiday_list, first_day, last_day):
        selected_list = company_holiday_list
        source = "company_holiday_list"

    holiday_dates = None
    if selected_list:
        holiday_dates = frappe.get_all(
            "Holiday", filters={"parent": selected_list}, pluck="holiday_date"
        )
    work_dates = count_work_dates(year, month, holiday_dates)
    # 修复（2026-09-29，审查 #51 / X3-6）：入职前、演示员工166后的日子不算这个员工的工作日。
    # 原来月中入职或演示员工166的人也按整月算上限，工时会摊到入职前或演示员工166后的日子上。
    # 复职的人可能还留着上次的演示员工166日期（早于这次入职日期），这种演示员工166日期不用。
    joined_on = getdate(joined_on) if joined_on else None
    relieved_on = getdate(relieved_on) if relieved_on else None
    if relieved_on and joined_on and relieved_on < joined_on:
        relieved_on = None
    if joined_on:
        work_dates = [value for value in work_dates if value >= joined_on]
    if relieved_on:
        work_dates = [value for value in work_dates if value <= relieved_on]
    return {
        "day_limit": len(work_dates),
        "hour_limit": len(work_dates) * HOURS_PER_WORKDAY,
        "calendar_source": source,
        "holiday_list": selected_list,
        "work_dates": work_dates,
        "joined_on": joined_on.isoformat() if joined_on and joined_on > first_day else None,
        "relieved_on": relieved_on.isoformat() if relieved_on and relieved_on < last_day else None,
    }


def resolve_monthly_work_limit(year, month, employee=None, company=None, *, lock=False):
    from rayher_hr_payroll.attendance_requests import leave_hours_by_date
    result = resolve_monthly_calendar(year, month, employee=employee, company=company)
    base_hours = result["hour_limit"]
    deductions = {}
    if employee:
        first_day = date(int(year), int(month), 1)
        last_day = date(int(year), int(month), monthrange(int(year), int(month))[1])
        rows = frappe.get_all(
            "OA Approval Request",
            filters={"employee": employee, "request_type": "请假申请",
                     "workflow_status": ["in", ["已完成", "已通过"]],
                     "from_date": ["<=", last_day], "to_date": [">=", first_day]},
            fields=["name", "request_type", "workflow_status", "from_date", "to_date", "leave_type", "attendance_days"],
            limit_page_length=0,
        )
        if lock:
            # Current read after the employee mutex; a snapshot taken before approval
            # must not permit a stale monthly cap under REPEATABLE READ.
            rows = frappe.db.sql(
                "SELECT name, request_type, workflow_status, from_date, to_date, leave_type, attendance_days "
                "FROM `tabOA Approval Request` WHERE employee = %s AND request_type = %s "
                "AND workflow_status IN (%s, %s) AND from_date <= %s AND to_date >= %s FOR UPDATE",
                (employee, "请假申请", "已完成", "已通过", last_day, first_day), as_dict=True,
            )
        deductions = leave_hours_by_date(rows, result["work_dates"])
    leave_hours = float(sum(deductions.values()))
    result.update({"base_hour_limit": base_hours, "leave_hours": leave_hours,
                   "hour_limit": max(0, base_hours - leave_hours),
                   "day_limit": max(0, base_hours - leave_hours) / HOURS_PER_WORKDAY,
                   "leave_hours_by_date": {d.isoformat(): float(h) for d, h in deductions.items()}})
    return result
