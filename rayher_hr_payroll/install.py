from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from rayher_hr_payroll.custom_fields import CUSTOM_FIELDS
from rayher_hr_payroll.access_control import ensure_access_control
from rayher_hr_payroll.approval_config import ensure_notifications, ensure_workflow_masters

# Permissions the R&D cost SPA needs so its reports/endpoints work for the
# management roles (finance = Accounts User, HR = HR User). Shipped here so a
# fresh install reproduces them instead of relying on manual DB grants.
# No DocPerm grants in this split. Finance does NOT need Employee/Project DocPerms
# here: the in-scope desk reports are Query Reports gated by their own report roles
# and run raw SQL (no record DocPerm needed), and granting Accounts User read on
# Employee would also expose permlevel-0 fields (incl. the reserved rd_mock_* salary
# fields). The SPA's role-scoped read/write perms ship with the SPA endpoints in
# split 2/2, where they belong.
SPA_PERMS = [
    # The 待我审批 (Pending My Approval) report is a Script Report whose ref_doctype
    # is Expense Claim; Frappe gates report execution on has_permission(ref_doctype,
    # "report"). Grant report ONLY (not read) so a manager cannot browse every claim
    # in Desk; read for opening/approving comes from the user's stock Employee role.
    ("Expense Claim", "Department Manager", {"report": 1}),
    ("Expense Claim", "Accounts User", {"report": 1}),
    # Employees self-serve Travel Requests from the portal but the stock Employee
    # role lacks create on it (unlike Leave/Expense/Comp-Leave).
    ("Travel Request", "Employee", {"read": 1, "create": 1, "write": 1, "submit": 1, "if_owner": 1}),
]


def _ensure_spa_perms():
    from frappe.permissions import add_permission, update_permission_property

    for dt, role, props in SPA_PERMS:
        add_permission(dt, role, 0)
        for prop, value in props.items():
            update_permission_property(dt, role, 0, prop, value)


def after_install():
    create_custom_fields(CUSTOM_FIELDS, update=True)
    ensure_access_control()  # create roles/profile FIRST so grants below can target them
    ensure_workflow_masters()
    _ensure_spa_perms()
    ensure_notifications()
