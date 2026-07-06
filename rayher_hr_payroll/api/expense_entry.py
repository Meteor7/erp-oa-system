import json
import frappe

from rayher_hr_payroll.api._guards import require_rd_access, parse_period, ensure_not_locked, RD_FINANCE_ROLES


_EDITABLE_REPLACEMENT_STATUSES = {"Imported", "Allocated"}


def _clean(value):
    return (value or "").strip() if isinstance(value, str) else value


def _direct_project_for_row(row):
    direct_project = _clean(row.get("direct_project"))
    allocation_type = _clean(row.get("allocation_type"))
    if allocation_type == "project" and not direct_project:
        frappe.throw(frappe._("项目费用请选择所属项目。"))
    if not direct_project:
        return None
    if not frappe.db.exists("Project", direct_project):
        frappe.throw(frappe._("所属项目不存在：{0}").format(direct_project))
    return direct_project


def _row_key(index, direct_project):
    scope = direct_project or "COMMON"
    return "R%d|%s" % (index + 1, scope)


def _expense_rows(items):
    seen = set()
    rows = []
    for idx, it in enumerate(items):
        amt = float(it.get("amount") or 0)
        if amt < 0:
            frappe.throw(frappe._("费用金额不能为负数。"))
        direct_project = _direct_project_for_row(it)
        desc = _clean(it.get("account_level_3")) or "费用"
        voucher_no = _clean(it.get("voucher_no")) or ("V%03d" % (idx + 1))
        if amt == 0:
            continue
        duplicate_key = (voucher_no, desc, round(amt, 2), direct_project or "")
        if duplicate_key in seen:
            frappe.throw(frappe._("存在重复的费用行（凭证号、科目、金额与所属项目都相同），请合并或更正。"))
        seen.add(duplicate_key)
        rows.append({
            "source_row_key": _row_key(idx, direct_project),
            "voucher_no": voucher_no,
            "account_level_1": "研发支出",
            "account_level_2": desc,
            "account_level_3": desc,
            "category": it.get("category") or "other",
            "amount": amt,
            "direct_project": direct_project,
        })
    if not rows:
        frappe.throw(frappe._("请至少录入一条有效费用（金额需大于 0）。"))
    return rows


def _active_import_name(year, month):
    return frappe.db.get_value(
        "RD Expense Import",
        {"year": year, "month": month, "docstatus": ["<", 2]},
        "name",
        order_by="creation desc",
    )


def _allow_ignore_permissions(doc):
    flags = getattr(doc, "flags", None)
    if flags is not None:
        flags.ignore_permissions = True


def _cancel_submitted_allocations(expense_import):
    for allocation_name in frappe.get_all(
        "RD Cost Allocation",
        filters={"expense_import": expense_import, "docstatus": 1},
        pluck="name",
    ):
        allocation = frappe.get_doc("RD Cost Allocation", allocation_name)
        _allow_ignore_permissions(allocation)
        allocation.cancel()


def _needs_replacement(doc):
    status = getattr(doc, "status", None) or ""
    docstatus = int(getattr(doc, "docstatus", 0) or 0)
    return docstatus == 1 or status in _EDITABLE_REPLACEMENT_STATUSES


def _create_import(period, year, month, rows):
    doc = frappe.get_doc({
        "doctype": "RD Expense Import",
        "period": period,
        "year": year,
        "month": month,
        "items": rows,
    })
    doc.insert(ignore_permissions=True)
    return doc


@frappe.whitelist()
def get_expense(period):
    require_rd_access(RD_FINANCE_ROLES)
    year, month = parse_period(period)
    name = _active_import_name(year, month)
    if not name:
        return {"name": None, "status": None, "items": []}
    d = frappe.get_doc("RD Expense Import", name)
    return {
        "name": d.name,
        "status": d.status,
        "items": [
            {
                "voucher_no": i.voucher_no,
                "account_level_3": i.account_level_3,
                "category": i.category,
                "amount": i.amount,
                "direct_project": getattr(i, "direct_project", None) or None,
                "allocation_type": "project" if getattr(i, "direct_project", None) else "common",
            }
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
    rows = _expense_rows(items)

    name = _active_import_name(year, month)
    if name:
        doc = frappe.get_doc("RD Expense Import", name)
        if _needs_replacement(doc):
            _cancel_submitted_allocations(name)
            doc = frappe.get_doc("RD Expense Import", name)
            if int(getattr(doc, "docstatus", 0) or 0) == 1:
                _allow_ignore_permissions(doc)
                doc.cancel()
            _create_import(period, year, month, rows)
        else:
            doc.set("items", rows)
            doc.save(ignore_permissions=True)
    else:
        _create_import(period, year, month, rows)

    frappe.db.commit()
    return get_expense(period)