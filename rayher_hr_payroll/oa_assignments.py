from __future__ import annotations

import json

import frappe


ACTIVE_WORKFLOW_STATUSES = {"待审批", "待办理"}
OPEN_TODO_STATUS = "Open"
CLOSED_TODO_STATUS = "Closed"


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


def _row_value(row, key):
    return row.get(key) if isinstance(row, dict) else getattr(row, key, None)


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
    return sorted(desired)
