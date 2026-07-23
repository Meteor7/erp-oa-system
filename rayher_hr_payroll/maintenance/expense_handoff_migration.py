"""One-time normalization for invoice reimbursement handoff values."""

from __future__ import annotations


PAID = "已付款"
SOURCE_INVOICE_PUSH = "发票下推"
PAYMENT_CORPORATE = "对公支付"
PAYMENT_PERSONAL = "支付个人"
DEPARTMENT_LEGACY = "总经理室"
DEPARTMENT_CURRENT = "总经办"


def build_migration_plan(rows):
    plan = []
    for row in rows or []:
        if str(row.get("workflow_status") or "") == PAID:
            continue
        changes = {}
        if (
            str(row.get("source_type") or "") == SOURCE_INVOICE_PUSH
            and str(row.get("payment_type") or "") == PAYMENT_CORPORATE
        ):
            changes["payment_type"] = PAYMENT_PERSONAL
        if str(row.get("department") or "") == DEPARTMENT_LEGACY:
            changes["department"] = DEPARTMENT_CURRENT
        if changes:
            plan.append({"name": str(row.get("name") or ""), "changes": changes})
    return plan


def normalize_unpaid_expense_handoff(dry_run=True):
    import frappe

    rows = frappe.get_all(
        "OA Approval Request",
        filters={"workflow_status": ["!=", PAID]},
        fields=[
            "name",
            "workflow_status",
            "source_type",
            "payment_type",
            "department",
        ],
        order_by="name asc",
        limit_page_length=0,
    )
    plan = build_migration_plan(rows)
    result = {
        "dry_run": bool(dry_run),
        "count": len(plan),
        "requests": [item["name"] for item in plan],
    }
    if dry_run:
        return result
    try:
        for item in plan:
            frappe.db.set_value(
                "OA Approval Request",
                item["name"],
                item["changes"],
                update_modified=False,
            )
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    return result
