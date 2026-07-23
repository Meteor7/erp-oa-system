"""Backfill invoice-owned expense descriptions from existing request lines."""

import frappe

RECORD_DOCTYPE = "OA Invoice Record"
LINE_DOCTYPE = "OA Approval Expense Line"


def execute():
    frappe.reload_doc("rayher_hr_payroll", "doctype", "oa_invoice_record")
    frappe.reload_doc("rayher_hr_payroll", "doctype", "oa_approval_expense_line")
    if not frappe.db.table_exists(RECORD_DOCTYPE, cached=False):
        return
    if not frappe.db.table_exists(LINE_DOCTYPE, cached=False):
        return

    rows = frappe.db.sql(
        """
        SELECT invoice.name, line.expense_description
        FROM `tabOA Invoice Record` invoice
        INNER JOIN `tabOA Approval Expense Line` line
          ON line.parent = invoice.request
         AND line.line_key = invoice.expense_line_key
        WHERE (invoice.expense_description IS NULL OR invoice.expense_description = '')
          AND line.expense_description IS NOT NULL
          AND line.expense_description != ''
        ORDER BY invoice.name
        """,
        as_dict=True,
    )
    updated = 0
    for row in rows:
        description = str(row.get("expense_description") or "").strip()
        if not description:
            continue
        frappe.db.set_value(
            RECORD_DOCTYPE,
            row["name"],
            "expense_description",
            description,
            update_modified=False,
        )
        updated += 1
    frappe.logger("invoice_ocr").info(
        "backfill_invoice_expense_context scanned=%s updated=%s",
        len(rows),
        updated,
    )
