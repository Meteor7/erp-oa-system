import calendar

import frappe


def month_bounds(ym):
    parts = ym.split("-")
    if len(parts) != 2:
        raise ValueError("period must be YYYY-MM")
    year, month = int(parts[0]), int(parts[1])
    last = calendar.monthrange(year, month)[1]
    return (f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}")


def get_period_salary(employee, ym):
    """Submitted Salary Slip gross_pay for an employee in period 'YYYY-MM' (0.0 if none)."""
    start, end = month_bounds(ym)
    rows = frappe.get_all(
        "Salary Slip",
        filters={"employee": employee, "docstatus": 1, "start_date": ["between", [start, end]]},
        fields=["gross_pay"], limit=1,
    )
    return float(rows[0].gross_pay) if rows else 0.0


def period_salaries(ym):
    """{employee: gross_pay} for all submitted slips in the period."""
    start, end = month_bounds(ym)
    rows = frappe.get_all(
        "Salary Slip",
        filters={"docstatus": 1, "start_date": ["between", [start, end]]},
        fields=["employee", "gross_pay"],
    )
    return {r.employee: float(r.gross_pay) for r in rows}
