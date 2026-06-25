import json
import frappe

from rayher_hr_payroll.api._guards import require_rd_access, parse_period, ensure_not_locked, RD_FINANCE_ROLES


@frappe.whitelist()
def get_expense(period):
    require_rd_access(RD_FINANCE_ROLES)
    year, month = parse_period(period)
    name = frappe.db.get_value(
        "RD Expense Import", {"year": year, "month": month, "docstatus": ["<", 2]},
        "name", order_by="creation desc",
    )
    if not name:
        return {"name": None, "status": None, "items": []}
    d = frappe.get_doc("RD Expense Import", name)
    return {
        "name": d.name, "status": d.status,
        "items": [
            {"voucher_no": i.voucher_no, "account_level_3": i.account_level_3,
             "category": i.category, "amount": i.amount}
            for i in d.items
        ],
    }


@frappe.whitelist(methods=["POST"])
def save_expense(period, items):
    require_rd_access(RD_FINANCE_ROLES)
    ensure_not_locked(period, "lock_gl_import", "费用导入")
    if isinstance(items, str):
        items = json.loads(items)
    year, month = parse_period(period)
    # Reject duplicate GL rows up front (same voucher + account + amount): the SPA
    # assigns each row a synthetic source_row_key, which would otherwise slip
    # identical rows past the import's source_row_key dedup and double-allocate.
    seen = set()
    for it in items:
        k = ((it.get("voucher_no") or "").strip(), (it.get("account_level_3") or "").strip(),
             round(float(it.get("amount") or 0), 2))
        if k[2] == 0:
            continue
        if k in seen:
            frappe.throw(frappe._("存在重复的费用行（凭证号、科目与金额都相同），请合并或更正。"))
        seen.add(k)
    rows = []
    for idx, it in enumerate(items):
        amt = float(it.get("amount") or 0)
        if amt < 0:
            frappe.throw(frappe._("费用金额不能为负数。"))
        desc = (it.get("account_level_3") or "").strip()
        if amt == 0:
            continue
        rows.append({
            "source_row_key": "R%d" % (idx + 1),
            "voucher_no": it.get("voucher_no") or ("V%03d" % (idx + 1)),
            "account_level_1": "研发支出", "account_level_2": desc or "费用",
            "account_level_3": desc or "费用",
            "category": it.get("category") or "other", "amount": amt,
        })
    if not rows:
        frappe.throw(frappe._("请至少录入一条有效费用（金额需大于 0）。"))
    name = frappe.db.get_value(
        "RD Expense Import", {"year": year, "month": month, "docstatus": ["<", 2]},
        "name", order_by="creation desc",
    )
    if name:
        doc = frappe.get_doc("RD Expense Import", name)
        if doc.docstatus == 1 or (doc.status or "") == "Allocated":
            frappe.throw(frappe._("本期费用已提交或已分摊，如需修改请先撤销分摊单。"))
        if any(getattr(it, "direct_project", None) for it in doc.items):
            frappe.throw(frappe._("本期导入含直接归属项目的费用，请在后台编辑以免丢失归属。"))
        # Update the existing draft in place (no ignore_permissions delete, which
        # would bypass the finance-no-delete policy).
        doc.set("items", rows)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({
            "doctype": "RD Expense Import", "period": period, "year": year, "month": month,
            "items": rows,
        })
        doc.insert(ignore_permissions=True)
    # Left as a DRAFT so finance can keep editing; recalc_allocation submits it
    # (reaching docstatus=1, which the hardened allocation before_submit requires)
    # as the first step of allocation.
    frappe.db.commit()
    return get_expense(period)
