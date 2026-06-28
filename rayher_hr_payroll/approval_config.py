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


# ---- Applicant decision notification (covers HR-created-on-behalf requests) ----
# The declarative Notifications above notify doc.owner, which for a self-submitted request
# IS the applicant. When HR/admin creates a request on behalf of an employee, owner is the
# staff creator, so the employee would never hear the decision. This hook posts a bell
# Notification Log to the employee's own login on the terminal decision, only when that
# user differs from owner (else the declarative owner notification already covers it).

def _expense_terminal(doc):
    return getattr(doc, "workflow_state", "") in ("财务已审", "已拒绝")


def _leave_terminal(doc):
    return getattr(doc, "status", "") in ("Approved", "Rejected")


def _submit_terminal(doc):
    return True  # wired to on_submit, so reaching the hook means it was just submitted


_APPLICANT_TERMINAL = {
    "Expense Claim": _expense_terminal,
    "Leave Application": _leave_terminal,
    "Travel Request": _submit_terminal,
    "Compensatory Leave Request": _submit_terminal,
}


def notify_applicant_on_decision(doc, method=None):
    check = _APPLICANT_TERMINAL.get(getattr(doc, "doctype", None))
    if not check or not check(doc):
        return
    # Value-Change doctypes (Expense/Leave) fire on_update on every save; only act on the
    # transition INTO the terminal state. Submit-driven doctypes (Travel/Comp) fire on_submit
    # exactly once, where get_doc_before_save() is the pre-submit draft -- skip the dedup there.
    if method != "on_submit":
        before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
        if before is not None and check(before):
            return
    emp = getattr(doc, "employee", None)
    if not emp:
        return
    user = frappe.db.get_value("Employee", emp, "user_id")
    if not user or user == getattr(doc, "owner", None):
        return  # owner notification already reaches the applicant
    frappe.get_doc({
        "doctype": "Notification Log",
        "for_user": user,
        "type": "Alert",
        "document_type": doc.doctype,
        "document_name": doc.name,
        "subject": "你的申请已更新: " + str(doc.name),
        "email_content": "你的" + doc.doctype + "申请 " + str(doc.name) + " 已处理,请查看最新状态。",
    }).insert(ignore_permissions=True)
