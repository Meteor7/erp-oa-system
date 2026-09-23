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


def _payment_request_open():
    from rayher_hr_payroll.oa_feature_gate import is_admin_only
    return not is_admin_only(REQUEST_PAYMENT)


def _log_failure(name):
    frappe.log_error(title="付款单补票提醒发送失败", message=f"{name}\n{frappe.get_traceback()}")


def _remind(row, today, store):
    kind, suffix = folder.reminder(row.get("expected_invoice_date"), today)
    if not kind:
        return 0
    user = _applicant_user(row)
    if not user:
        return 0
    key = f"invoice-due:{row['name']}:{suffix}"
    if store.notification_exists(for_user=user, document_name=row["name"], key=key):
        return 0
    store.create_notification(
        for_user=user,
        document_name=row["name"],
        subject=f"付款单补票{kind}：{row['name']} [{key}]",
        content=folder.reminder_text(kind, row["name"], row.get("expected_invoice_date"), today),
        link=_request_link(frappe._dict(row)),
    )
    return 1


def send_payment_invoice_reminders(today=None, *, store=None):
    """Return the number of reminders sent.

    修复（2026-09-23）：付款单功能没开放时不发提醒；某一张单据出错只记录错误日志，
    不再让当天所有提醒都发不出去。
    """
    if not _payment_request_open():
        return 0
    today = getdate(today or nowdate())
    store = store or FrappeAssignmentStore()
    sent = 0
    for row in pending_payments():
        try:
            sent += _remind(row, today, store)
        except Exception:
            _log_failure(row.get("name"))
    return sent
