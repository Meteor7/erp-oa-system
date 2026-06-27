import frappe

from rayher_hr_payroll.api._guards import require_rd_access, parse_period, RD_FINANCE_ROLES

RD_TYPES = ("全时研发", "非全时研发", "研发辅助")


@frappe.whitelist()
def get_dashboard(period):
    require_rd_access()
    year, month = parse_period(period)
    emps = frappe.get_all("Employee", fields=["name", "archive_status", "rd_personnel_type"])
    total = len(emps)
    confirmed = sum(1 for e in emps if (e.archive_status or "") == "已归档")
    pending = total - confirmed
    ledger = sum(1 for e in emps if (e.rd_personnel_type or "") in RD_TYPES)
    projects = frappe.db.count("Project", {"allow_rd_timesheet": 1})

    hrows = frappe.db.sql(
        """
        select ts.employee, sum(tsd.hours) as h
        from `tabTimesheet Detail` tsd inner join `tabTimesheet` ts on ts.name = tsd.parent
        inner join `tabEmployee` e on e.name = ts.employee
        inner join `tabProject` p on p.name = tsd.project
        where ts.docstatus = 1 and month(tsd.from_time) = %(m)s and year(tsd.from_time) = %(y)s
          and e.rd_personnel_type in %(t)s
          and coalesce(p.allow_rd_timesheet, 0) = 1
        group by ts.employee
        """,
        {"m": month, "y": year, "t": RD_TYPES}, as_dict=True)
    hours_total = sum((r.h or 0) for r in hrows)
    filled = sum(1 for r in hrows if (r.h or 0) > 0)

    imp = frappe.db.get_value(
        "RD Expense Import", {"year": year, "month": month, "docstatus": ["<", 2]},
        "name", order_by="creation desc",
    )
    cost_items = 0
    cost_sum = 0.0
    if imp:
        items = frappe.get_all("RD Expense Item", filters={"parent": imp}, fields=["amount"])
        cost_items = len(items)
        cost_sum = sum((i.amount or 0) for i in items)

    period_canon = "%04d-%02d" % (year, month)
    dorms = frappe.get_all("Accommodation Deduction", filters={"period": period_canon}, fields=["total_amount"])
    dorm_count = len(dorms)
    dorm_sum = sum((d.total_amount or 0) for d in dorms)

    # payroll/salary aggregates are only exposed to HR/Accounts roles
    can_see_cost = bool(set(frappe.get_roles()) & set(RD_FINANCE_ROLES))
    alloc = (frappe.db.get_value("RD Cost Allocation", {"year": year, "month": month, "docstatus": 1},
                                 ["capitalized_total", "expensed_total", "unknown_total"],
                                 as_dict=True, order_by="creation desc") or {}) if can_see_cost else {}
    if can_see_cost:
        from rayher_hr_payroll.payroll_bridge import period_pay_totals
        pay = period_pay_totals(period_canon)
        gross = pay["gross"]
        deductions = pay["deductions"]
    else:
        cost_sum = 0
        cost_items = 0
        gross = 0
        deductions = 0

    return {
        "period": period,
        "kpi": {"total": total, "confirmed": confirmed, "ledger": ledger,
                "hours": hours_total, "projects": projects, "cost": cost_sum},
        "pipeline": {"emp": total, "ledger": ledger, "hours": hours_total, "cost": cost_sum},
        "todos": {"pending": pending, "filled": filled, "ledger": ledger,
                  "cost_items": cost_items, "dorm_count": dorm_count},
        "alloc": {"capitalized": alloc.get("capitalized_total") or 0,
                  "expensed": alloc.get("expensed_total") or 0,
                  "unknown": alloc.get("unknown_total") or 0},
        "salary": {"gross": gross, "deductions": deductions},
    }
