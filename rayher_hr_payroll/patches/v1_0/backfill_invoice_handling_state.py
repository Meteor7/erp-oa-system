"""Backfill explicit invoice handling and follow-up state without guessing deferred invoices."""

import frappe

REQUEST_DOCTYPE = "OA Approval Request"


def execute():
    frappe.reload_doc("rayher_hr_payroll", "doctype", "oa_approval_request")
    if not frappe.db.table_exists(REQUEST_DOCTYPE, cached=False):
        return
    rows = frappe.get_all(
        REQUEST_DOCTYPE,
        filters={"request_type": "费用付款申请"},
        fields=["name", "invoice_count", "no_invoice_reason", "invoice_handling_mode", "invoice_followup_status"],
        limit_page_length=0,
    )
    updated = 0
    for row in rows:
        if str(row.get("invoice_handling_mode") or "").strip():
            continue
        has_invoices = int(row.get("invoice_count") or 0) > 0
        mode = "已有发票" if has_invoices else "无需发票"
        followup = "已收票" if has_invoices else "无需发票"
        frappe.db.set_value(
            REQUEST_DOCTYPE,
            row["name"],
            {"invoice_handling_mode": mode, "invoice_followup_status": followup},
            update_modified=False,
        )
        updated += 1
    frappe.logger("invoice_ocr").info(
        "backfill_invoice_handling_state scanned=%s updated=%s", len(rows), updated
    )
