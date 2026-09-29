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


def period_company_contributions(ym):
    """{employee: {"si": 单位社保合计, "hf": 单位公积金合计}}，只读已确认的记录。

    修复（2026-09-29，审查 X2-2，决定 D1）：研发人工原来只有工资单应发，单位承担的社保和公积金
    进不了研发成本（总账里的同类行又和工资单冲突）。这里只读取人事模块里已确认的记录，
    不改社保、公积金模块本身。
    """
    out = {}
    for doctype, field, key in (
        ("Employee Social Insurance", "company_total", "si"),
        ("Employee Housing Fund", "company_amount", "hf"),
    ):
        rows = frappe.get_all(
            doctype,
            filters={"status": "Confirmed", "period": ym},
            fields=["employee", field],
            limit_page_length=0,
        )
        for r in rows:
            if not r.get("employee"):
                continue
            entry = out.setdefault(r.get("employee"), {"si": 0.0, "hf": 0.0})
            entry[key] += float(r.get(field) or 0)
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
    emp = getattr(doc, "employee", None)
    if not emp:
        return
    # Lock only if a SUBMITTED allocation for this period actually captured THIS employee's
    # R&D labour (recorded in its hour snapshots). Keying on the booked snapshot -- not the
    # employee's CURRENT rd_personnel_type -- is reclassification-proof (HR can't reclassify
    # an employee to non-R&D and then amend the old slip) and still narrow (a non-R&D
    # employee whose hours were never captured stays editable).
    allocs = frappe.get_all(
        "RD Cost Allocation", filters={"year": year, "month": month, "docstatus": 1}, pluck="name"
    )
    if allocs and frappe.db.exists("RD Allocation Source Hour", {"parent": ["in", allocs], "employee": emp}):
        frappe.throw(
            "本期(%04d-%02d)已提交的研发费用分摊已采用该员工工时,工资单不可新增/修改/取消;"
            "请先作废该分摊后再调整工资。" % (year, month)
        )
