import frappe

# Notify the APPLICANT (owner) when their request is DECIDED. Trigger differs per
# doctype because their approval mechanics differ (verified against HRMS):
#   - Leave Application: real `status` field -> Value Change on status.
#   - Expense Claim: our Workflow -> Value Change on workflow_state, gated by a
#     condition to the terminal states so the applicant isn't pinged on their own
#     submission or on intermediate manager/finance steps.
#   - Travel Request / Compensatory Leave Request: no status field, approved by
#     submission -> fire on Submit (a Value Change on a missing field is auto-disabled).
# Approver-side routing is handled by the workflow's email alert, by HRMS native
# notifications, and by the P5 "待我审批" report — not by custom notifications here.
# (HRMS also pushes its own PWA approval notification for Expense Claim; the custom
# System Notification is the in-bell complement.)
_RESULT = [
    ("Leave Application", "请假", "Value Change", "status", "doc.status in ['Approved', 'Rejected']"),
    ("Expense Claim", "报销", "Value Change", "workflow_state", "doc.workflow_state in ['财务已审', '已拒绝']"),
    ("Travel Request", "出差", "Submit", "", ""),
    ("Compensatory Leave Request", "调休", "Submit", "", ""),
]


def _result_notification(doctype, label, event, value_changed, condition):
    # value_changed and condition are ALWAYS present (possibly "") so the idempotent
    # update path reconciles any stale value left by an earlier version.
    return {
        "doctype": "Notification",
        "name": doctype + " 结果提醒",
        "subject": "你的" + label + "申请已更新: {{ doc.name }}",
        "document_type": doctype,
        "event": event,
        "value_changed": value_changed,
        "condition": condition,
        "channel": "System Notification",
        "enabled": 1,
        "is_standard": 0,
        "module": "Rayher HR Payroll",
        "recipients": [{"receiver_by_document_field": "owner"}],
        "message": "你的" + label + "申请 {{ doc.name }} 已处理,请查看最新状态。",
    }


# Approver-side reminders for the Expense Claim workflow: notify the assigned
# manager when a claim reaches 待经理审批, and any Accounts User when it reaches
# 待财务复核. (The other request types route via HRMS-native approver notifications.)
_APPROVER = [
    ("Expense Claim 经理待办", "待经理审批", "有报销待你审批: {{ doc.name }}",
     [{"receiver_by_document_field": "expense_approver"}]),
    ("Expense Claim 财务待办", "待财务复核", "有报销待财务复核: {{ doc.name }}",
     [{"receiver_by_role": "Accounts User"}]),
]


def _approver_notification(name, state, subject, recipients):
    return {
        "doctype": "Notification",
        "name": name,
        "subject": subject,
        "document_type": "Expense Claim",
        "event": "Value Change",
        "value_changed": "workflow_state",
        "condition": "doc.workflow_state == '" + state + "'",
        "channel": "System Notification",
        "enabled": 1,
        "is_standard": 0,
        "module": "Rayher HR Payroll",
        "recipients": recipients,
        "message": subject,
    }


NOTIFICATIONS = (
    [_result_notification(*spec) for spec in _RESULT]
    + [_approver_notification(*spec) for spec in _APPROVER]
)


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

    # Declarative cleanup of OUR own stale reminders only (e.g. the earlier
    # submit/approver reminders removed as broken). Scope strictly to names matching
    # our "<our doctype> <reminder-suffix>" convention so a co-located admin- or
    # other-app Notification under the same module is never deleted.
    managed = {n["name"] for n in NOTIFICATIONS}
    our_doctypes = ("Leave Application", "Expense Claim", "Travel Request", "Compensatory Leave Request")
    our_suffixes = ("结果提醒", "经理待办", "财务待办", "提交提醒", "审批提醒", "提醒", "待办")
    for stale in frappe.get_all("Notification", filters={"module": "Rayher HR Payroll"}, fields=["name", "document_type"]):
        if stale.name in managed:
            continue
        if stale.document_type in our_doctypes and any(stale.name.endswith(sfx) for sfx in our_suffixes):
            frappe.delete_doc("Notification", stale.name, ignore_permissions=True, force=True)


# The Expense Claim workflow references these state/action names. They are Link
# targets (workflow_state -> Workflow State), and fixture import does NOT create
# the masters, so a real transition (or even creating a claim whose default state
# is 草稿) fails link validation until these exist. Create them idempotently.
WORKFLOW_STATES = ["草稿", "待经理审批", "待财务复核", "财务已审", "已拒绝"]
WORKFLOW_ACTIONS = ["提交审批", "经理批准", "财务复核", "驳回", "重新提交"]


def ensure_workflow_masters():
    for name in WORKFLOW_STATES:
        if not frappe.db.exists("Workflow State", name):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": name}).insert(ignore_permissions=True)
    for name in WORKFLOW_ACTIONS:
        if not frappe.db.exists("Workflow Action Master", name):
            frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": name}).insert(ignore_permissions=True)
