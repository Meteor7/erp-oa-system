from __future__ import annotations

import json

import frappe


ACTIVE_WORKFLOW_STATUSES = {"待审批", "待办理"}
OPEN_TODO_STATUS = "Open"
CLOSED_TODO_STATUS = "Closed"

REQUEST_ROUTES = {
    "请假申请": "/planck-semicon/approval/leave",
    "加班申请": "/planck-semicon/approval/overtime",
    "调休申请": "/planck-semicon/approval/comp-time",
    "采购申请": "/planck-semicon/approval/procurement",
    "购买申请": "/planck-semicon/approval/direct-purchase",
    "采购付款": "/planck-semicon/approval/procurement-payment",
    "费用付款申请": "/planck-semicon/approval/reimbursement",
}


def _clean(value):
    return str(value or "").strip()


def _json_users(value):
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        try:
            values = json.loads(value or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
    return {_clean(item) for item in values if _clean(item)}


def _current_step(doc):
    if _clean(getattr(doc, "workflow_status", None)) not in ACTIVE_WORKFLOW_STATUSES:
        return None
    current_index = int(getattr(doc, "current_step_index", 0) or 0)
    return next(
        (
            row
            for row in list(getattr(doc, "steps", []) or [])
            if int(getattr(row, "step_index", 0) or 0) == current_index
        ),
        None,
    )


def assignment_reference_key(doc, step):
    request_name = _clean(getattr(doc, "name", None))
    step_key = _clean(getattr(step, "step_key", None))
    if not request_name or not step_key:
        raise ValueError("OA request name and step key are required for assignment synchronization.")
    return f"oa-assignment:{request_name}:{step_key}"


def _description(doc, step):
    return "OA审批待办 [{0}] {1}".format(
        assignment_reference_key(doc, step),
        _clean(getattr(step, "label", None)) or "待审批",
    )


class FrappeAssignmentStore:
    def list_open(self, reference_type, reference_name):
        return frappe.get_all(
            "ToDo",
            filters={
                "reference_type": reference_type,
                "reference_name": reference_name,
                "status": OPEN_TODO_STATUS,
            },
            fields=["name", "allocated_to", "description", "status"],
            order_by="creation asc",
            limit_page_length=500,
        )

    def create(self, *, reference_type, reference_name, allocated_to, description):
        return frappe.get_doc(
            {
                "doctype": "ToDo",
                "allocated_to": allocated_to,
                "reference_type": reference_type,
                "reference_name": reference_name,
                "description": description,
                "status": OPEN_TODO_STATUS,
                "assigned_by": frappe.session.user,
            }
        ).insert(ignore_permissions=True)

    def close(self, name):
        todo = frappe.get_doc("ToDo", name)
        if todo.status == OPEN_TODO_STATUS:
            todo.status = CLOSED_TODO_STATUS
            todo.save(ignore_permissions=True)
        return todo

    def notification_exists(self, *, for_user, document_name, key):
        return bool(frappe.db.exists(
            "Notification Log",
            {
                "for_user": for_user,
                "document_type": "OA Approval Request",
                "document_name": document_name,
                "subject": ["like", f"%[{key}]%"],
            },
        ))

    def create_notification(self, *, for_user, document_name, subject, content, link):
        return frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": for_user,
            "type": "Alert",
            "document_type": "OA Approval Request",
            "document_name": document_name,
            "subject": subject,
            "email_content": content,
            "link": link,
        }).insert(ignore_permissions=True)


def _row_value(row, key):
    return row.get(key) if isinstance(row, dict) else getattr(row, key, None)


def _request_link(doc):
    route = REQUEST_ROUTES.get(_clean(getattr(doc, "request_type", None)), "/planck-semicon/approval/request-dashboard")
    return f"{route}?request={_clean(getattr(doc, 'name', None))}"


def _assignment_message(doc, step, key):
    request_type = _clean(getattr(doc, "request_type", None)) or "OA申请"
    request_name = _clean(getattr(doc, "name", None))
    applicant = _clean(getattr(doc, "employee_name", None)) or _clean(getattr(doc, "employee", None))
    subject = _clean(getattr(doc, "subject", None))
    node = _clean(getattr(step, "label", None)) or "待审批"
    title = f"{request_type}待处理：{request_name} [{key}]"
    content = f"申请人：{applicant}<br>主题：{subject}<br>当前节点：{node}"
    return title, content


def _sync_assignment_notification(doc, step, user, key, store):
    if store.notification_exists(for_user=user, document_name=doc.name, key=key):
        return
    subject, content = _assignment_message(doc, step, key)
    store.create_notification(
        for_user=user,
        document_name=doc.name,
        subject=subject,
        content=content,
        link=_request_link(doc),
    )


def notify_rejected_applicant(doc, actor, reason, *, store=None, event_key=None):
    store = store or FrappeAssignmentStore()
    user = _clean(getattr(doc, "owner", None))
    if not user:
        employee = _clean(getattr(doc, "employee", None))
        user = _clean(frappe.db.get_value("Employee", employee, "user_id")) if employee else ""
    if not user:
        return False
    key = event_key or f"oa-rejection:{_clean(getattr(doc, 'name', None))}:{_clean(actor)}"
    if store.notification_exists(for_user=user, document_name=doc.name, key=key):
        return False
    request_type = _clean(getattr(doc, "request_type", None)) or "OA申请"
    subject = f"{request_type}已驳回：{doc.name} [{key}]"
    content = (
        f"驳回人：{_clean(actor)}<br>驳回原因：{_clean(reason)}"
        f"<br>当前状态：{_clean(getattr(doc, 'workflow_status', None))}"
    )
    store.create_notification(
        for_user=user,
        document_name=doc.name,
        subject=subject,
        content=content,
        link=_request_link(doc),
    )
    return True


def notify_request_applicant(doc, status, *, actor=None, note=None, event_key=None, store=None):
    """Notify the applicant when an OA request reaches a terminal business state."""
    store = store or FrappeAssignmentStore()
    user = _clean(getattr(doc, "owner", None))
    if not user:
        employee = _clean(getattr(doc, "employee", None))
        user = _clean(frappe.db.get_value("Employee", employee, "user_id")) if employee else ""
    if not user:
        return False
    key = event_key or f"oa-result:{_clean(getattr(doc, 'name', None))}:{_clean(status)}"
    if store.notification_exists(for_user=user, document_name=doc.name, key=key):
        return False
    request_type = _clean(getattr(doc, "request_type", None)) or "OA申请"
    subject = f"{request_type}{status}：{doc.name} [{key}]"
    content = f"申请单：{doc.name}<br>当前状态：{_clean(status)}"
    if actor:
        content += f"<br>处理人：{_clean(actor)}"
    if note:
        content += f"<br>备注：{_clean(note)}"
    store.create_notification(
        for_user=user,
        document_name=doc.name,
        subject=subject,
        content=content,
        link=_request_link(doc),
    )
    return True


def close_request_assignments(doc, *, store=None):
    store = store or FrappeAssignmentStore()
    reference_type = _clean(getattr(doc, "doctype", None)) or "OA Approval Request"
    reference_name = _clean(getattr(doc, "name", None))
    if not reference_name:
        return []
    rows = list(store.list_open(reference_type, reference_name) or [])
    for row in rows:
        store.close(_row_value(row, "name"))
    return rows


def sync_current_assignments(doc, previous_step=None, *, store=None):
    del previous_step  # compatibility hook for callers that retain the prior step
    store = store or FrappeAssignmentStore()
    reference_type = _clean(getattr(doc, "doctype", None)) or "OA Approval Request"
    reference_name = _clean(getattr(doc, "name", None))
    if not reference_name:
        raise ValueError("OA request must be saved before assignments can be synchronized.")

    step = _current_step(doc)
    desired = {}
    if step is not None:
        approved = _json_users(getattr(step, "approved_by", None))
        for user in sorted(_json_users(getattr(step, "approvers", None)) - approved):
            desired[user] = assignment_reference_key(doc, step)

    open_rows = list(store.list_open(reference_type, reference_name) or [])
    kept = set()
    for row in open_rows:
        user = _clean(_row_value(row, "allocated_to"))
        description = _clean(_row_value(row, "description"))
        expected_key = desired.get(user)
        if expected_key and f"[{expected_key}]" in description and user not in kept:
            kept.add(user)
            continue
        store.close(_row_value(row, "name"))

    if step is not None:
        description = _description(doc, step)
        for user in sorted(set(desired) - kept):
            store.create(
                reference_type=reference_type,
                reference_name=reference_name,
                allocated_to=user,
                description=description,
            )
        for user, key in sorted(desired.items()):
            _sync_assignment_notification(doc, step, user, key, store)
    return sorted(desired)
