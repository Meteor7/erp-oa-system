import frappe

from rayher_hr_payroll.rd_expense_accounts import DEFAULT_PATHS, business_category, path_hash


def execute():
    if not frappe.db.table_exists("RD Expense Account Path"):
        return
    now = frappe.utils.now()
    for index, path in enumerate(DEFAULT_PATHS, start=1):
        digest = path_hash(path)
        if frappe.db.exists("RD Expense Account Path", {"path_hash": digest}):
            continue
        frappe.db.sql(
            """
            insert into `tabRD Expense Account Path`
              (name, creation, modified, modified_by, owner, docstatus, idx,
               path_hash, account_level_1, account_level_2, account_level_3,
               account_level_4, business_category, enabled, created_from, sort_order)
            values (%s, %s, %s, 'Administrator', 'Administrator', 0, 0,
                    %s, %s, %s, %s, %s, %s, 1, '系统初始化', %s)
            """,
            (digest, now, now, digest, *path, business_category(path), index),
        )
