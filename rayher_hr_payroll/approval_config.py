import frappe

# Notify the APPLICANT (owner) when their request is decided. The trigger differs
# per doctype because their approval mechanics differ (verified against HRMS):
#   - Leave Application: tracks a real `status` field -> Value Change on status.
#   - Expense Claim: driven by our Workflow -> Value Change on workflow_state.
#   - Travel Request / Compensatory Leave Request: approved by submission and have
#     NO status field -> fire on Submit (a Value Change on a missing field would be
#     auto-disabled by Frappe).
# Approver-side reminders are intentionally NOT modeled as custom notifications:
# the Expense Claim workflow's `send_email_alert` notifies the next actor, HRMS
# already notifies leave/travel approvers natively, and the P5 "待我审批" report is
# the in-app pending queue. This avoids dead/duplicate notifications.
_RESULT = [
    ("Leave Application", "请假", "Value Change", "status"),
    ("Expense Claim", "报销", "Value Change", "workflow_state"),
    ("Travel Request", "出差", "Submit", None),
    ("Compensatory Leave Request", "调休", "Submit", None),
]


def _result_notification(doctype, label, event, value_changed):
    n = {
        "doctype": "Notification",
        "name": doctype + " 结果提醒",
        "subject": "你的" + label + "申请已更新: {{ doc.name }}",
        "document_type": doctype,
        "event": event,
        "channel": "System Notification",
        "enabled": 1,
        "is_standard": 0,
        "module": "Rayher HR Payroll",
        "recipients": [{"receiver_by_document_field": "owner"}],
        "message": "你的" + label + "申请 {{ doc.name }} 已处理,请查看最新状态。",
    }
    if value_changed:
        n["value_changed"] = value_changed
    return n


NOTIFICATIONS = [_result_notification(dt, label, ev, vc) for dt, label, ev, vc in _RESULT]


def ensure_notifications():
    for n in NOTIFICATIONS:
        name = n["name"]
        skip = ("doctype", "name", "recipients")
        if frappe.db.exists("Notification", name):
            doc = frappe.get_doc("Notification", name)
            doc.update({k: v for k, v in n.items() if k not in skip})
            doc.set("recipients", [])
        else:
            doc = frappe.new_doc("Notification")
            doc.update({k: v for k, v in n.items() if k not in ("doctype", "recipients")})
        for r in n.get("recipients", []):
            doc.append("recipients", r)
        doc.save(ignore_permissions=True)
