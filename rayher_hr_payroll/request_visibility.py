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
}

# See every request regardless of owner.
_SEE_ALL_ROLES = {"System Manager", "HR Manager", "HR User"}
# Finance reviews all reimbursements (spec L64: 财务见全员费用) -- Expense Claim only.
_FINANCE_ROLES = {"Accounts User"}


def _scope_sql(doctype, user, roles, employee):
    """Pure: SQL WHERE fragment (or '' for unrestricted). roles is a set, employee may
    be None."""
    if user == "Administrator" or (roles & _SEE_ALL_ROLES):
        return ""
    if doctype == "Expense Claim" and (roles & _FINANCE_ROLES):
        return ""
    emp_field, approver_field = _SCOPING[doctype]
    tbl = "`tab" + doctype + "`"
    clauses = []
    if approver_field and "Department Manager" in roles:
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
    if doctype == "Expense Claim" and (roles & _FINANCE_ROLES):
        return True
    emp_field, approver_field = _SCOPING[doctype]
    if approver_field and "Department Manager" in roles and doc.get(approver_field) == user:
        return True
    if employee and doc.get(emp_field) == employee:
        return True
    return doc.get("owner") == user


def _employee_of(user):
    return frappe.db.get_value("Employee", {"user_id": user}, "name")


def _query(doctype, user):
    user = user or frappe.session.user
    return _scope_sql(doctype, user, set(frappe.get_roles(user)), _employee_of(user))


def _perm(doctype, doc, user):
    user = user or frappe.session.user
    # return False to deny out-of-scope docs; None to defer in-scope ones to role perms.
    if _in_scope(doctype, doc, user, set(frappe.get_roles(user)), _employee_of(user)):
        return None
    return False


# permission_query_conditions hooks (one per doctype; the hook passes only `user`)
def expense_claim_query(user=None):
    return _query("Expense Claim", user)


def leave_application_query(user=None):
    return _query("Leave Application", user)


def travel_request_query(user=None):
    return _query("Travel Request", user)


def compensatory_leave_query(user=None):
    return _query("Compensatory Leave Request", user)


# has_permission hooks (signature: doc, ptype, user)
def expense_claim_has_permission(doc, ptype=None, user=None):
    return _perm("Expense Claim", doc, user)


def leave_application_has_permission(doc, ptype=None, user=None):
    return _perm("Leave Application", doc, user)


def travel_request_has_permission(doc, ptype=None, user=None):
    return _perm("Travel Request", doc, user)


def compensatory_leave_has_permission(doc, ptype=None, user=None):
    return _perm("Compensatory Leave Request", doc, user)
