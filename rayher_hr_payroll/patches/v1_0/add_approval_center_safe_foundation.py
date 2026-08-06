"""Reload approval-center schema without guessing values for historical requests."""


DOCTYPE_SLUGS = (
    "oa_approval_request",
    "oa_purchase_request_line",
    "oa_approval_amount_ledger",
    "oa_business_document",
)


def execute():
    import frappe

    for slug in DOCTYPE_SLUGS:
        frappe.reload_doc("rayher_hr_payroll", "doctype", slug)
