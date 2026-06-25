import frappe

from rayher_hr_payroll.api._guards import lock_period_import, require_rd_access, parse_period, ensure_not_locked, RD_FINANCE_ROLES


@frappe.whitelist()
def get_allocation(period):
    require_rd_access(RD_FINANCE_ROLES)
    year, month = parse_period(period)
    name = frappe.db.get_value(
        "RD Cost Allocation", {"year": year, "month": month, "docstatus": 1},
        "name", order_by="creation desc",
    )
    if not name:
        return {"name": None}
    d = frappe.get_doc("RD Cost Allocation", name)
    return {
        "name": d.name, "status": d.status,
        "capitalized": d.capitalized_total, "expensed": d.expensed_total,
        "unknown": d.unknown_total, "lines": len(d.lines),
    }


@frappe.whitelist(methods=["POST"])
def recalc_allocation(period):
    require_rd_access(RD_FINANCE_ROLES)
    year, month = parse_period(period)
    ensure_not_locked(period, "lock_allocations", "分摊")
    # Lock the period import row up front (same row every other path locks) so a
    # concurrent hour add/edit/delete serializes against this allocation: hours are then
    # read and snapshotted under the lock, closing the edit-vs-allocate race.
    imp = lock_period_import(year, month)
    if not imp:
        frappe.throw(frappe._("本期没有费用导入单，无法分摊。请先在「财务费用导入」录入费用。"))
    # A submitted allocation may only be superseded by System Manager: the
    # permission model (and test_finance_cannot_delete_any_rd_doctype_or_cancel_
    # submitted_ones) forbids finance from cancelling submitted R&D records.
    submitted = frappe.get_all(
        "RD Cost Allocation", filters={"year": year, "month": month, "docstatus": 1}, pluck="name",
    )
    if submitted and "System Manager" not in frappe.get_roles():
        frappe.throw(frappe._("本期已有已提交的分摊单，如需重算请联系系统管理员先撤销。"))
    frappe.db.savepoint("rd_recalc")
    try:
        # Submit the draft import first: the hardened allocation before_submit
        # requires a submitted (docstatus=1) import. Finance holds submit on
        # RD Expense Import; its before_submit re-checks total>0 + no duplicate rows.
        impdoc = frappe.get_doc("RD Expense Import", imp)
        if impdoc.docstatus == 0:
            impdoc.submit()
        # Supersede prior submitted allocations (only System Manager reaches here).
        for n in submitted:
            frappe.get_doc("RD Cost Allocation", n).cancel()
        a = frappe.get_doc(dict(
            doctype="RD Cost Allocation", period=period, year=year, month=month,
            expense_import=impdoc.name, allocation_basis="rd_project_hours", scope="all",
            calculation_version="v1",
        ))
        a.calculate()
        a.insert(ignore_permissions=True)
        a.submit()  # on_submit marks the source import as Allocated (path-independent)
    except Exception:
        frappe.db.rollback(save_point="rd_recalc")
        raise
    frappe.db.commit()
    return get_allocation(period)
