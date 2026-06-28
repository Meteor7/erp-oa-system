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
        fields=["gross_pay"],
    )
    return float(sum((r.gross_pay or 0) for r in rows))


def period_salaries(ym):
    """{employee: gross_pay} for all submitted slips in the period."""
    start, end = month_bounds(ym)
    rows = frappe.get_all(
        "Salary Slip",
        filters={"docstatus": 1, "start_date": ["between", [start, end]]},
        fields=["employee", "gross_pay"],
    )
    out = {}
    for r in rows:
        out[r.employee] = out.get(r.employee, 0.0) + float(r.gross_pay or 0)
    return out


def period_pay_totals(ym):
    """Aggregate {gross, deductions} from submitted Salary Slips in the period."""
    start, end = month_bounds(ym)
    rows = frappe.get_all(
        "Salary Slip",
        filters={"docstatus": 1, "start_date": ["between", [start, end]]},
        fields=["gross_pay", "total_deduction"],
    )
    return {
        "gross": float(sum((r["gross_pay"] or 0) for r in rows)),
        "deductions": float(sum((r["total_deduction"] or 0) for r in rows)),
    }


def _period_from_date(start_date):
    """(year, month) from a Salary Slip start_date, or None."""
    if not start_date:
        return None
    s = str(start_date)
    return int(s[:4]), int(s[5:7])


def block_locked_salary_slip_change(doc, method=None):
    """Freeze a period's payroll once an RD Cost Allocation has been submitted for it.

    The allocation reads live submitted Salary Slips at submit time, so letting payroll
    change afterwards (amend/cancel/add a slip) would silently desync the booked R&D
    labour from the slips. Block any Salary Slip new-save/amend/cancel/delete in a period
    that already has a submitted allocation; the operator must cancel the allocation first.
    """
    period = _period_from_date(getattr(doc, "start_date", None))
    if not period:
        return
    year, month = period
    if frappe.db.exists("RD Cost Allocation", {"year": year, "month": month, "docstatus": 1}):
        frappe.throw(
            "本期(%04d-%02d)已有已提交的研发费用分摊,工资单不可新增/修改/取消;"
            "请先作废该分摊后再调整工资。" % (year, month)
        )
