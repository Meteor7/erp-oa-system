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
    # NOTE: frappe.add_permission() defaults ptype to "read" on creation, so we
    # MUST explicitly set read:0 to keep these report-only (otherwise the role could
    # browse every Expense Claim in Desk). _ensure_spa_perms applies each flag.
    ("Expense Claim", "Department Manager", {"read": 0, "report": 1}),
    ("Expense Claim", "Accounts User", {"read": 1, "report": 1}),  # finance legitimately reviews all reimbursements (opens finance-stage claims; not shared per-doc)
]

# Permissions a prior version granted that are now revoked: Travel Request portal
# self-service is deferred until its approval routing exists, so drop the Employee
# grant entirely (any lingering Custom DocPerm row is removed on migrate).
REVOKE_PERMS = [("Travel Request", "Employee")]


def _ensure_spa_perms():
    import frappe
    from frappe.permissions import add_permission, update_permission_property

    for dt, role, props in SPA_PERMS:
        # Idempotent + declarative. add_permission only matches an if_owner=0 row, so
        # re-running on a site whose row is if_owner=1 would create a SECOND row and
        # leave the stale one; Frappe ORs flags across rows, resurrecting a revoked
        # permission (e.g. Travel submit). Remove every prior row for this
        # (doctype, role, permlevel) first, then create exactly one with the declared
        # flags. props must list if_owner LAST so it is flipped after the other flags.
        _drop_role_perms(dt, role)
        add_permission(dt, role, 0)
        for prop, value in props.items():
            update_permission_property(dt, role, 0, prop, value)

    # Revoke obsolete grants (delete any lingering row for these app-owned pairs).
    for dt, role in REVOKE_PERMS:
        _drop_role_perms(dt, role)


def _drop_role_perms(dt, role):
    # These (doctype, role) permission rows are EXCLUSIVELY managed by this app
    # (verified: no stock perm ships for them), so removing all rows for the pair
    # before re-granting is config-as-code ownership, not clobbering of others'
    # customizations. It also collapses the if_owner duplicate add_permission would
    # otherwise leave (which ORed flags to resurrect a revoked permission).
    import frappe

    for name in frappe.get_all(
        "Custom DocPerm", filters={"parent": dt, "role": role, "permlevel": 0}, pluck="name"
    ):
        frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True, force=True)


def after_install():
    create_custom_fields(CUSTOM_FIELDS, update=True)
    ensure_access_control()  # create roles/profile FIRST so grants below can target them
    ensure_workflow_masters()
    _ensure_spa_perms()
    ensure_notifications()
