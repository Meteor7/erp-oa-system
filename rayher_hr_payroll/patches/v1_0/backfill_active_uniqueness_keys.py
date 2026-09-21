"""Enforce active-record uniqueness without deleting or selecting a winner."""
import frappe


def execute():
    specifications = [
        ("RD Expense Import", "period", "active_period_key", "docstatus < 2"),
        ("Accommodation Occupancy", "employee", "active_employee_key", "is_active = 1"),
        ("Accommodation Occupancy", "room", "active_room_key", "is_active = 1"),
    ]
    # Check every table before updating any keys. Never silently discard records.
    for doctype, source, target, condition in specifications:
        duplicates = frappe.db.sql(
            f"SELECT `{source}` AS value, COUNT(*) AS count FROM `tab{doctype}` "
            f"WHERE {condition} AND COALESCE(`{source}`, '') != '' "
            f"GROUP BY `{source}` HAVING COUNT(*) > 1", as_dict=True,
        )
        if duplicates:
            frappe.throw(f"{doctype} 存在重复有效记录，需核对后重试迁移：" + "; ".join(str(row.value) for row in duplicates))
    # patches.txt runs before normal schema sync on Frappe v15. Load these
    # DocTypes explicitly before addressing the new columns.
    for name in ("rd_expense_import", "accommodation_occupancy"):
        frappe.reload_doc("rayher_hr_payroll", "doctype", name, force=True)
    for doctype, source, target, condition in specifications:
        frappe.db.sql(
            f"UPDATE `tab{doctype}` SET `{target}` = "
            f"CASE WHEN {condition} THEN NULLIF(`{source}`, '') ELSE NULL END"
        )
