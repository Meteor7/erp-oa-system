"""Anniversary annual leave: 40 hours per completed year, without expiry.

OA requests are the reservation/use ledger. Read current rows under the employee
mutex so concurrent applications cannot spend the same entitlement twice.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from rayher_hr_payroll.attendance_requests import (
    ACTIVE, COMPLETED, REQUEST_LEAVE, ZERO, as_date, date_range, value,
)

ANNUAL_HOURS = 40


def anniversary(joined, year):
    # February 29 anniversaries fall on February 28 in non-leap years.
    return date(year, joined.month, min(joined.day, monthrange(year, joined.month)[1]))


def entitlement(joining_date, as_of):
    today = as_date(as_of)
    if not joining_date:
        return dict(credit_hours=0, completed_years=0, eligible=False,
                    eligible_from=None, next_grant_date=None, date_of_joining=None,
                    eligibility_message="缺少入职日期，请联系人事补齐后申请年假")
    joined = as_date(joining_date)
    years = max(0, today.year - joined.year - (today < anniversary(joined, today.year)))
    first = anniversary(joined, joined.year + 1)
    next_grant = anniversary(joined, joined.year + years + 1)
    return dict(credit_hours=years * ANNUAL_HOURS, completed_years=years,
                eligible=today >= first, eligible_from=first.isoformat(),
                next_grant_date=next_grant.isoformat(), date_of_joining=joined.isoformat(),
                eligibility_message="" if today >= first else f"入职未满12个月，{first.isoformat()}起可享年假")


def is_active_annual(row):
    return (value(row, "request_type") == REQUEST_LEAVE and value(row, "leave_type") == "年假"
            and value(row, "workflow_status") in ACTIVE)


def annual_details(row):
    import json
    raw = value(row, "attendance_days")
    if raw:
        return json.loads(raw) if isinstance(raw, str) else raw
    # Compatibility for historical date-only OA annual leave.
    from rayher_hr_payroll.attendance_requests import work_dates_for_range
    return [{"work_date": d.isoformat(), "hours": 8} for d in sorted(work_dates_for_range(
        value(row, "employee"), value(row, "from_date"), value(row, "to_date")))]


def summarize_annual(joining_date, rows, as_of):
    result = entitlement(joining_date, as_of)
    reserved, used = ZERO, ZERO
    for row in rows:
        if not is_active_annual(row):
            continue
        hours = sum((Decimal(str(day["hours"])) for day in annual_details(row)), ZERO)
        if value(row, "workflow_status") in COMPLETED:
            used += hours
        else:
            reserved += hours
    result.update(reserved_hours=float(reserved), used_hours=float(used),
                  available_hours=float(Decimal(result["credit_hours"]) - reserved - used),
                  as_of=as_date(as_of).isoformat(), carry_forward=True)
    return result


def validate_annual_capacity(joining_date, rows, as_of):
    """Do not spend unearned future grants or backdate leave before entitlement."""
    result = summarize_annual(joining_date, rows, as_of)
    if not result["eligible"]:
        raise ValueError(result["eligibility_message"])
    if result["available_hours"] < 0:
        raise ValueError("可用年假余额不足，请检查申请中占用和已用时长")
    daily = {}
    for row in rows:
        if is_active_annual(row):
            for day in annual_details(row):
                key = as_date(day["work_date"])
                daily[key] = daily.get(key, ZERO) + Decimal(str(day["hours"]))
    spent = ZERO
    for day in sorted(daily):
        spent += daily[day]
        earned = entitlement(joining_date, min(day, as_date(as_of)))["credit_hours"]
        if spent > earned:
            raise ValueError(f"{day.isoformat()}可用年假额度不足，不能提前使用入职周年尚未发放的额度")


def annual_rows(employee, *, lock=False):
    import frappe
    return frappe.db.sql(
        "SELECT name, employee, request_type, leave_type, workflow_status, from_date, to_date, "
        "attendance_days, duration_hours FROM `tabOA Approval Request` "
        "WHERE employee=%s AND request_type=%s AND leave_type=%s "
        "AND workflow_status IN (%s,%s,%s,%s)" + (" FOR UPDATE" if lock else ""),
        (employee, REQUEST_LEAVE, "年假", *sorted(ACTIVE)), as_dict=True,
    )


def get_annual_balance(employee):
    import frappe
    from frappe.utils import today
    joining_date = frappe.db.get_value("Employee", employee, "date_of_joining") if employee else None
    return summarize_annual(joining_date, annual_rows(employee) if employee else [], today())


def validate_annual_request(doc, before=None):
    if not is_active_annual(doc):
        return
    # Unchanged pending -> approved moves reserved hours to used without charging
    # again. Withdrawals and returns to draft release the source request itself.
    if before and is_active_annual(before):
        old = [(d["work_date"], d["hours"]) for d in annual_details(before)]
        new = [(d["work_date"], d["hours"]) for d in annual_details(doc)]
        if old == new and value(before, "employee") == value(doc, "employee"):
            return
    import frappe
    from frappe.utils import today
    employee = value(doc, "employee")
    if not employee:
        frappe.throw("年假申请必须关联员工")
    joined = frappe.db.get_value("Employee", employee, "date_of_joining", for_update=True)
    rows = [row for row in annual_rows(employee, lock=True) if value(row, "name") != doc.name]
    try:
        validate_annual_capacity(joined, rows + [doc], today())
    except ValueError as exc:
        frappe.throw(str(exc))
