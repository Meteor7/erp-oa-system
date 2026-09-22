"""每日任务：提醒付款单申请人按时补录发票。

只处理"已付款·待补票"的付款单：到期前 3 天内提醒一次，到期当天提醒一次，逾期后
每天提醒一次（同一天重复运行不会重复发送）。提醒只发给申请人，不拦截新的付款。
"""
from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate

from rayher_hr_payroll import expense_claims as rules
from rayher_hr_payroll import invoice_folder as folder
from rayher_hr_payroll.oa_assignments import FrappeAssignmentStore, _request_link
from rayher_hr_payroll.oa_document_types import REQUEST_PAYMENT


def _applicant_user(row):
    if row.get("owner") and row["owner"] not in {"Administrator", "Guest"}:
        return row["owner"]
    employee = row.get("employee")
    return frappe.db.get_value("Employee", employee, "user_id") if employee else None


def pending_payments():
    return frappe.get_all(
        "OA Approval Request",
        filters={
            "request_type": REQUEST_PAYMENT,
            "workflow_status": "已付款",
            "invoice_followup_status": rules.FOLLOWUP_PENDING,
            "expected_invoice_date": ["is", "set"],
        },
        fields=["name", "owner", "employee", "subject", "request_type", "expected_invoice_date"],
        limit_page_length=0,
    )


def send_payment_invoice_reminders(today=None, *, store=None):
    """Return the number of reminders sent."""
    today = getdate(today or nowdate())
    store = store or FrappeAssignmentStore()
    sent = 0
    for row in pending_payments():
        kind, suffix = folder.reminder(row.get("expected_invoice_date"), today)
        if not kind:
            continue
        user = _applicant_user(row)
        if not user:
            continue
        key = f"invoice-due:{row['name']}:{suffix}"
        if store.notification_exists(for_user=user, document_name=row["name"], key=key):
            continue
        store.create_notification(
            for_user=user,
            document_name=row["name"],
            subject=f"付款单补票{kind}：{row['name']} [{key}]",
            content=folder.reminder_text(kind, row["name"], row.get("expected_invoice_date"), today),
            link=_request_link(frappe._dict(row)),
        )
        sent += 1
    return sent
