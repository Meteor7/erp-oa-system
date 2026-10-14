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
    """{employee: {"si": 单位社保合计, "hf": 单位公积金合计}}，只读已确认的数。

    修复（2026-09-29，审查 X2-2，决定 D1）：研发人工原来只有工资单应发，单位承担的社保和公积金
    进不了研发成本（总账里的同类行又和工资单冲突）。
    2026-10-14：已确认的工资条（新算法）存着当时用的单位社保 / 公积金（hr_social_company / hr_fund_company），
    和工资、研发分摊同一张单据，优先用它；社保账单生效后不写月度记录，原来按记录读会漏掉。
    没有快照的旧工资条、没有工资条的人，仍读人事模块里已确认的月度记录。
    """
    out = {}
    start, end = month_bounds(ym)
    slips = frappe.get_all(
        "Salary Slip",
        filters={"docstatus": 1, "start_date": ["between", [start, end]], "hr_amounts_v2": 1},
        fields=["employee", "hr_social_company", "hr_fund_company"],
        limit_page_length=0,
    )
    from_slips = set()
    for r in slips:
        if not r.get("employee"):
            continue
        from_slips.add(r.get("employee"))
        entry = out.setdefault(r.get("employee"), {"si": 0.0, "hf": 0.0})
        entry["si"] += float(r.get("hr_social_company") or 0)
        entry["hf"] += float(r.get("hr_fund_company") or 0)
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
            if not r.get("employee") or r.get("employee") in from_slips:
                continue
            entry = out.setdefault(r.get("employee"), {"si": 0.0, "hf": 0.0})
            entry[key] += float(r.get(field) or 0)
    return out


def period_pay_totals(ym):
    """本月工资合计：金额只算已确认（已提交）的工资条，和研发分摊读的是同一批（period_salaries）。

    另外给出人数：confirmed = 有已确认工资条的人；draft = 只有薪酬计算页生成的草稿（hr_spa_managed = 1）、还没确认的人，
    draft_gross 是这些草稿的应发合计——“确认本月工资”只确认这些（审查 2026-10-13）；
    external_draft / external_draft_gross = 别处生成的草稿（薪酬计算页不确认，要到生成它的地方处理），单独给出。
    看板上“工资 / 应发合计 / 人力成本”都用这一个函数（决定 2026-10-13：草稿只显示成进度，不算进金额）。
    """
    start, end = month_bounds(ym)
    rows = frappe.get_all(
        "Salary Slip",
        filters={"docstatus": ["<", 2], "start_date": ["between", [start, end]]},
        fields=["employee", "docstatus", "gross_pay", "total_deduction", "hr_spa_managed"],
        limit_page_length=0,
    )
    confirmed = [r for r in rows if int(r.get("docstatus") or 0) == 1]
    confirmed_people = {r.get("employee") for r in confirmed}
    open_drafts = [r for r in rows if int(r.get("docstatus") or 0) == 0 and r.get("employee") not in confirmed_people]
    drafts = [r for r in open_drafts if int(r.get("hr_spa_managed") or 0)]
    draft_people = {r.get("employee") for r in drafts}
    external = [r for r in open_drafts if not int(r.get("hr_spa_managed") or 0) and r.get("employee") not in draft_people]
    return {
        "gross": float(sum((r.get("gross_pay") or 0) for r in confirmed)),
        "deductions": float(sum((r.get("total_deduction") or 0) for r in confirmed)),
        "confirmed": len(confirmed_people),
        "draft": len(draft_people),
        "draft_gross": float(sum((r.get("gross_pay") or 0) for r in drafts)),
        "external_draft": len({r.get("employee") for r in external}),
        "external_draft_gross": float(sum((r.get("gross_pay") or 0) for r in external)),
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
