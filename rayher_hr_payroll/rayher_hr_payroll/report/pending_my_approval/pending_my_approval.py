import frappe

# Expense Claim workflow stages where a claim is still awaiting action.
MANAGER_STATE = "待经理审批"
FINANCE_STATE = "待财务复核"


def get_columns():
    return [
        {"label": "类型", "fieldname": "type", "fieldtype": "Data", "width": 90},
        {"label": "单号", "fieldname": "name", "fieldtype": "Dynamic Link", "options": "doctype", "width": 200},
        {"label": "申请人", "fieldname": "applicant", "fieldtype": "Data", "width": 140},
        {"label": "状态", "fieldname": "state", "fieldtype": "Data", "width": 120},
        # hidden column backing the Dynamic Link 单号 column above
        {"label": "doctype", "fieldname": "doctype", "fieldtype": "Data", "width": 1, "hidden": 1},
    ]


def rows_from_sources(sources):
    """sources: list of (label, doctype, docs). Rows are fieldname-keyed dicts so
    the Dynamic Link 单号 column resolves its target via the `doctype` field."""
    rows = []
    for label, doctype, docs in sources:
        for d in docs:
            rows.append({
                "type": label,
                "doctype": doctype,
                "name": d.get("name"),
                "applicant": d.get("employee_name") or d.get("owner") or "",
                "state": d.get("workflow_state") or d.get("status") or "待提交",
            })
    return rows


def _fetch():
    """Only items genuinely pending the VIEWING user. frappe.get_all bypasses
    record permissions, so each source is explicitly scoped to the viewer.

    Travel Request and Compensatory Leave Request have no approver field and no
    approval workflow yet, so a per-viewer 'pending me' set cannot be expressed for
    them; they are intentionally omitted rather than shown company-wide (which would
    over-expose). Their approval routing is a follow-up."""
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    sources = []

    sources.append(("请假", "Leave Application", frappe.get_all(
        "Leave Application",
        filters={"leave_approver": user, "status": "Open", "docstatus": 0},
        fields=["name", "owner", "employee_name", "status"],
    )))

    # Expense Claim: manager stage -> that doc's expense_approver; finance stage ->
    # any Accounts User (role-based; the finance step has no per-doc approver).
    expense = frappe.get_all(
        "Expense Claim",
        filters={"workflow_state": MANAGER_STATE, "expense_approver": user},
        fields=["name", "owner", "employee_name", "workflow_state"],
    )
    if "Accounts User" in roles:
        expense += frappe.get_all(
            "Expense Claim",
            filters={"workflow_state": FINANCE_STATE},
            fields=["name", "owner", "employee_name", "workflow_state"],
        )
    sources.append(("报销", "Expense Claim", expense))
    return sources


def execute(filters=None):
    return get_columns(), rows_from_sources(_fetch())
