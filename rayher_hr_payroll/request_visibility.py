"""Row-level visibility for the OA request doctypes (spec §visibility matrix):

    员工只见自己 · 经理只见本部门(=指派给自己的) · 财务见全员费用 · HR/总控全见

This is enforced with permission_query_conditions (list/report scoping) + has_permission
(direct Desk/API doc access), NOT broad User Permissions: a self Employee User Permission
would also restrict a manager/finance reviewer (who is themselves an employee) from opening
subordinate requests. The per-doctype rules below are role-aware instead.
"""

import frappe

# doctype -> (employee_field, approver_field|None). Travel/Comp have no approver field.
_SCOPING = {
    "Expense Claim": ("employee", "expense_approver"),
    "Leave Application": ("employee", "leave_approver"),
    "Travel Request": ("employee", None),
    "Compensatory Leave Request": ("employee", None),
    "Salary Slip": ("employee", None),  # 工资单: 员工只见自己; HR/财务/总控见全员
}

# See every request regardless of owner.
_SEE_ALL_ROLES = {"System Manager", "HR Manager", "HR User"}
# Finance reviews all reimbursements + sees all payroll (spec L64: 财务见全员工资/费用).
_FINANCE_ROLES = {"Accounts User"}
_FINANCE_DOCTYPES = {"Expense Claim", "Salary Slip"}


def _scope_sql(doctype, user, roles, employee):
    """Pure: SQL WHERE fragment (or '' for unrestricted). roles is a set, employee may
    be None."""
    if user == "Administrator" or (roles & _SEE_ALL_ROLES):
        return ""
    if doctype in _FINANCE_DOCTYPES and (roles & _FINANCE_ROLES):
        return ""
    emp_field, approver_field = _SCOPING[doctype]
    tbl = "`tab" + doctype + "`"
    clauses = []
    # Anyone named as the assigned approver sees the request -- covers our Department
    # Manager flow AND stock HRMS Leave Approver / Expense Approver assigned per-document.
    if approver_field:
        clauses.append("{0}.{1} = {2}".format(tbl, approver_field, frappe.db.escape(user)))
    if employee:
        clauses.append("{0}.{1} = {2}".format(tbl, emp_field, frappe.db.escape(employee)))
    else:
        clauses.append("{0}.owner = {1}".format(tbl, frappe.db.escape(user)))
    return "(" + " or ".join(clauses) + ")"


def _in_scope(doctype, doc, user, roles, employee):
    """Pure: may this user access this single doc? doc is a mapping/obj with .get."""
    if user == "Administrator" or (roles & _SEE_ALL_ROLES):
        return True
    if doctype in _FINANCE_DOCTYPES and (roles & _FINANCE_ROLES):
        return True
    emp_field, approver_field = _SCOPING[doctype]
    if approver_field and doc.get(approver_field) == user:
        return True
    if employee:
        return doc.get(emp_field) == employee  # linked employee: own requests only (matches _scope_sql)
    return doc.get("owner") == user            # unlinked user: fall back to what they created


def _employee_of(user):
    # 同一账号有在职档和旧的离职档（复职）时取在职档（修复 2026-09-29，审查 X3-5）。
    return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name") or frappe.db.get_value("Employee", {"user_id": user}, "name")


def _query(doctype, user):
    user = user or frappe.session.user
    return _scope_sql(doctype, user, set(frappe.get_roles(user)), _employee_of(user))


# Expense Claim states where the claimant may still edit their OWN claim. Once submitted into
# the approval flow, only the assigned approver (or System Manager) edits it -- even if the
# claimant also holds the approver role -- so a finance-claimant can't edit their own claim
# while it waits for finance review.
_CLAIMANT_EDITABLE_STATES = {"草稿", "已拒绝"}


def _perm(doctype, doc, user, ptype=None):
    user = user or frappe.session.user
    roles = set(frappe.get_roles(user))
    employee = _employee_of(user)
    if not _in_scope(doctype, doc, user, roles, employee):
        return False  # out of scope -> deny
    if ptype == "write" and doctype == "Expense Claim" and employee and doc.get("employee") == employee:
        # The claimant may write their own claim only while it is (or was) in 草稿/已拒绝 -- this
        # covers creating a draft AND applying 提交审批/重新提交 (which transition OUT of those
        # states). Once the claim is ALREADY under review, the claimant can't edit it. Key on the
        # PRE-save state so a legitimate claimant transition isn't blocked by its own new state.
        before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
        before_state = (before.get("workflow_state") if before else None) or "草稿"
        if before_state not in _CLAIMANT_EDITABLE_STATES:
            return False  # claim already under review -> claimant may not edit it
    return None  # in scope -> defer to role perms


# permission_query_conditions hooks (one per doctype; the hook passes only `user`)
def expense_claim_query(user=None):
    return _query("Expense Claim", user)


def leave_application_query(user=None):
    return _query("Leave Application", user)


def travel_request_query(user=None):
    return _query("Travel Request", user)


def compensatory_leave_query(user=None):
    return _query("Compensatory Leave Request", user)


def salary_slip_query(user=None):
    return _query("Salary Slip", user)


# has_permission hooks (signature: doc, ptype, user)
def expense_claim_has_permission(doc, ptype=None, user=None):
    return _perm("Expense Claim", doc, user, ptype)


def leave_application_has_permission(doc, ptype=None, user=None):
    return _perm("Leave Application", doc, user, ptype)


def travel_request_has_permission(doc, ptype=None, user=None):
    return _perm("Travel Request", doc, user, ptype)


def compensatory_leave_has_permission(doc, ptype=None, user=None):
    return _perm("Compensatory Leave Request", doc, user, ptype)


def salary_slip_has_permission(doc, ptype=None, user=None):
    return _perm("Salary Slip", doc, user, ptype)
