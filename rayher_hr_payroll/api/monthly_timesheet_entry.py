"""Month-level R&D timesheet entry backed by generated ERPNext Timesheet rows."""

from calendar import monthrange
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe


DAY_QUANTUM = Decimal("0.01")
HOUR_QUANTUM = Decimal("0.01")
HOURS_PER_DAY = Decimal("8.00")


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
