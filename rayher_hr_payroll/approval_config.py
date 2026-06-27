import frappe

_TYPES = [
    ("Leave Application", "请假", "leave_approver", "status"),
    ("Travel Request", "出差", None, "status"),
    ("Expense Claim", "报销", "expense_approver", "workflow_state"),
    ("Compensatory Leave Request", "调休", "leave_approver", "status"),
]


def _submit(doctype, label, approver_field):
    recipients = [{"receiver_by_document_field": approver_field}] if approver_field else []
    return {
        "doctype": "Notification",
        "name": doctype + " 提交提醒",
        "subject": "新的" + label + "申请待审批: {{ doc.name }}",
        "document_type": doctype,
        "event": "Submit",
        "channel": "Notification",
        "enabled": 1,
        "is_standard": 1,
        "module": "Rayher HR Payroll",
        "recipients": recipients,
        "message": "{{ doc.owner }} 提交了" + label + "申请 {{ doc.name }},请及时处理。",
    }


def _decision(doctype, label, state_field):
    return {
        "doctype": "Notification",
        "name": doctype + " 结果提醒",
        "subject": "你的" + label + "申请已更新: {{ doc.name }}",
        "document_type": doctype,
        "event": "Value Change",
        "value_changed": state_field,
        "channel": "Notification",
        "enabled": 1,
        "is_standard": 1,
        "module": "Rayher HR Payroll",
        "recipients": [{"receiver_by_document_field": "owner"}],
        "message": "你的" + label + "申请 {{ doc.name }} 状态已更新。",
    }


NOTIFICATIONS = []
for _dt, _label, _appr, _state in _TYPES:
    NOTIFICATIONS.append(_submit(_dt, _label, _appr))
    NOTIFICATIONS.append(_decision(_dt, _label, _state))


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
