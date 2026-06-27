import frappe

_TYPES = [
    ("请假", "Leave Application", {"leave_approver": None, "status": "Open", "docstatus": 0}, "status"),
    ("出差", "Travel Request", {"docstatus": 0}, "status"),
    ("报销", "Expense Claim", {"workflow_state": ["in", ["待经理审批", "待财务复核"]]}, "workflow_state"),
    ("调休", "Compensatory Leave Request", {"docstatus": 0}, "status"),
]


def get_columns():
    return [
        {"label": "类型", "fieldname": "type", "fieldtype": "Data", "width": 80},
        {"label": "单号", "fieldname": "name", "fieldtype": "Dynamic Link", "options": "doctype", "width": 160},
        {"label": "申请人", "fieldname": "applicant", "fieldtype": "Data", "width": 120},
        {"label": "状态", "fieldname": "state", "fieldtype": "Data", "width": 120},
    ]


def rows_from_sources(sources):
    rows = []
    for label, docs in sources.items():
        for d in docs:
            state = d.get("workflow_state") or d.get("status") or ""
            rows.append([label, d.get("name"), d.get("employee_name") or d.get("owner") or "", state])
    return rows


def _fetch():
    user = frappe.session.user
    sources = {}
    for label, doctype, filters, _state in _TYPES:
        f = dict(filters)
        if "leave_approver" in f:
            f["leave_approver"] = user
        sources[label] = frappe.get_all(
            doctype, filters=f,
            fields=["name", "employee_name", "owner", "status"] +
                   (["workflow_state"] if doctype == "Expense Claim" else []),
        )
    return sources


def execute(filters=None):
    return get_columns(), rows_from_sources(_fetch())
