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


def resolve_monthly_work_limit(year, month, employee=None, company=None):
    year = int(year)
    month = int(month)
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    employee_holiday_list = ""

    if employee:
        row = frappe.db.get_value(
            "Employee", employee, ["holiday_list", "company"], as_dict=True
        ) or {}
        employee_holiday_list = str(_row_value(row, "holiday_list") or "")
        company = company or _row_value(row, "company")

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
    return {
        "day_limit": len(work_dates),
        "hour_limit": len(work_dates) * HOURS_PER_WORKDAY,
        "calendar_source": source,
        "holiday_list": selected_list,
        "work_dates": work_dates,
    }