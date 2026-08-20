"""Backfill approved amounts for completed expense requests."""


def approved_amount_change(row):
    if str(row.get("request_type") or "").strip() != "费用付款申请":
        return {}
    if str(row.get("workflow_status") or "").strip() not in {"已完成", "已付款"}:
        return {}
    amount = float(row.get("amount") or 0)
    approved = float(row.get("approved_amount") or 0)
    return {"approved_amount": amount} if amount > 0 and approved <= 0 else {}


def execute():
    import frappe

    rows = frappe.get_all(
        "OA Approval Request",
        filters={
            "request_type": "费用付款申请",
            "workflow_status": ["in", ["已完成", "已付款"]],
        },
        fields=["name", "request_type", "workflow_status", "amount", "approved_amount"],
        limit_page_length=0,
    )
    for row in rows:
        changes = approved_amount_change(row)
        if changes:
            frappe.db.set_value(
                "OA Approval Request", row.name, changes, update_modified=False
            )
