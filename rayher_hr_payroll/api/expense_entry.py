import json
import frappe

from rayher_hr_payroll.api._guards import require_rd_access, parse_period, ensure_not_locked, RD_FINANCE_ROLES
from rayher_hr_payroll.rd_expense_accounts import (
    catalog_paths, confirmed_new_paths, ensure_paths, path_dict
)


_EDITABLE_REPLACEMENT_STATUSES = {"Imported", "Allocated"}
_VALID_CATEGORIES = {"personnel", "direct_input", "depreciation", "amortization", "other", "design"}


def _clean(value):
    return (value or "").strip() if isinstance(value, str) else value


def _text(value):
    return str(_clean(value) or "")


def _category_for_accounts(level_2, level_3, level_4, category=None):
    category = _text(category)
    if category in _VALID_CATEGORIES:
        return category
    text = " ".join([_text(level_2), _text(level_3), _text(level_4)])
    if any(token in text for token in ["人员人工", "人工", "工资", "社保", "社会保险", "养老保险", "医疗保险", "生育保险", "工伤保险", "失业保险", "住房公积金"]):
        return "personnel"
    if "直接投入" in text:
        return "direct_input"
    if "折旧" in text:
        return "depreciation"
    if "摊销" in text or "无形资产" in text:
        return "amortization"
    if "设计" in text:
        return "design"
    return "other"


def _account_levels(row):
    level_3 = _text(row.get("account_level_3")) or "费用"
    level_1 = _text(row.get("account_level_1")) or "研发支出"
    level_2 = _text(row.get("account_level_2")) or level_3
    level_4 = _text(row.get("account_level_4"))
    return level_1, level_2, level_3, level_4


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
    rows = []
    for idx, it in enumerate(items):
        amt = float(it.get("amount") or 0)
        direct_project = _direct_project_for_row(it)
        account_level_1, account_level_2, account_level_3, account_level_4 = _account_levels(it)
        voucher_no = _clean(it.get("voucher_no")) or ("V%03d" % (idx + 1))
        # 同一个项目一张凭证里把同一样东西买几次是正常的，完全相同的行也允许保存；
        # 费用导入页只提醒（见 lib/rdExpense.js duplicateVoucherRows），不拦截。
        rows.append({
            "source_row_key": _row_key(idx, direct_project),
            "voucher_no": voucher_no,
            "account_level_1": account_level_1,
            "account_level_2": account_level_2,
            "account_level_3": account_level_3,
            "account_level_4": account_level_4,
            "category": _category_for_accounts(account_level_2, account_level_3, account_level_4, it.get("category")),
            "amount": amt,
            "direct_project": direct_project,
        })
    if not rows:
        frappe.throw(frappe._("请至少录入一条有效费用。"))
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
    try:
        doc.insert(ignore_permissions=True)
    except frappe.UniqueValidationError as exc:
        if "active_period_key" not in str(exc):
            raise
        frappe.throw("本期间已被另一个操作保存，请刷新后在现有费用导入单上继续编辑。")
    return doc


def _value(row, fieldname, default=None):
    if isinstance(row, dict):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def _serialize_expense_item(item, source_period=None):
    return {
        "period": source_period,
        "voucher_no": item.voucher_no,
        "account_level_1": getattr(item, "account_level_1", None) or "\u7814\u53d1\u652f\u51fa",
        "account_level_2": getattr(item, "account_level_2", None) or item.account_level_3,
        "account_level_3": item.account_level_3,
        "account_level_4": getattr(item, "account_level_4", None) or "",
        "category": item.category,
        "amount": item.amount,
        "direct_project": getattr(item, "direct_project", None) or None,
        "allocation_type": "project" if getattr(item, "direct_project", None) else "common",
    }


def _get_expense_year(year):
    imports = frappe.get_all(
        "RD Expense Import",
        filters={"year": year, "docstatus": ["<", 2]},
        fields=["name", "period"],
        order_by="month asc, creation desc",
    )
    items = []
    names = []
    for row in imports:
        name = _text(_value(row, "name"))
        source_period = _text(_value(row, "period"))
        if not name:
            continue
        names.append(name)
        doc = frappe.get_doc("RD Expense Import", name)
        items.extend(_serialize_expense_item(item, source_period=source_period) for item in doc.items)
    return {"name": None, "status": "Yearly" if names else None, "scope": "year", "imports": names, "items": items}


@frappe.whitelist()
def get_expense(period, scope="month"):
    require_rd_access(RD_FINANCE_ROLES)
    year, month = parse_period(period)
    if str(scope or "month") == "year":
        return _get_expense_year(year)
    name = _active_import_name(year, month)
    if not name:
        return {"name": None, "status": None, "scope": "month", "items": []}
    d = frappe.get_doc("RD Expense Import", name)
    return {
        "name": d.name,
        "status": d.status,
        "scope": "month",
        "items": [_serialize_expense_item(i) for i in d.items],
    }


@frappe.whitelist()
def get_expense_account_catalog():
    require_rd_access(RD_FINANCE_ROLES)
    return {"paths": [path_dict(path) for path in catalog_paths()]}


@frappe.whitelist(methods=["POST"])
def save_expense(period, items, new_account_paths=None):
    require_rd_access(RD_FINANCE_ROLES)
    ensure_not_locked(period, "lock_gl_import", "费用导入")
    if isinstance(items, str):
        items = json.loads(items)
    if isinstance(new_account_paths, str):
        new_account_paths = json.loads(new_account_paths)
    try:
        paths_to_create = confirmed_new_paths(items, catalog_paths(), new_account_paths or [])
    except ValueError as error:
        frappe.throw(str(error))
    ensure_paths(paths_to_create, created_from="Excel确认")
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
