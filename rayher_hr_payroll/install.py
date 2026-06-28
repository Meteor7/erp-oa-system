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
    # Expense Claim approvers need real document access to apply the workflow: the
    # manager step (待经理审批->待财务复核) saves a draft (needs write) and the finance
    # step (待财务复核->财务已审) SUBMITS the claim (needs submit). A report-only row is
    # both invalid (Frappe needs a basic perm) and non-functional; stock HRMS already
    # grants every Employee read+write on Expense Claim, so this is not a new exposure.
    ("Expense Claim", "Department Manager", {"read": 1, "write": 1, "report": 1}),
    ("Expense Claim", "Accounts User", {"read": 1, "write": 1, "report": 1}),  # no submit: finance review never submits (doc_status 0)
    # permlevel-1: the 财务已审 state sets approval_status (the ONLY permlevel-1 field on
    # Expense Claim) to Approved; without lvl1 write Frappe silently drops that update and
    # the claim stays Draft. Accounts User is the finance reviewer, so this is correct.
    ("Expense Claim", "Accounts User", {"read": 1, "write": 1}, 1),
    # Leave Approver runs the shared 待我审批 report whose ref_doctype is Expense Claim;
    # Frappe gates report execution on report perm of the ref_doctype. read is scoped to
    # their own claims by request_visibility.
    ("Expense Claim", "Leave Approver", {"read": 1, "report": 1}),
]

# Permissions a prior version granted that are now revoked: Travel Request portal
# self-service is deferred until its approval routing exists, so drop the Employee
# grant entirely (any lingering Custom DocPerm row is removed on migrate).
REVOKE_PERMS = [("Travel Request", "Employee")]


def _ensure_spa_perms():
    import frappe
    from frappe.permissions import add_permission, update_permission_property

    for entry in SPA_PERMS:
        dt, role, props = entry[0], entry[1], entry[2]
        permlevel = entry[3] if len(entry) > 3 else 0
        # Idempotent + declarative. add_permission only matches an if_owner=0 row, so
        # re-running on a site whose row is if_owner=1 would create a SECOND row and
        # leave the stale one; Frappe ORs flags across rows, resurrecting a revoked
        # permission (e.g. Travel submit). Remove every prior row for this
        # (doctype, role, permlevel) first, then create exactly one with the declared
        # flags. props must list if_owner LAST so it is flipped after the other flags.
        _drop_role_perms(dt, role, permlevel)
        add_permission(dt, role, permlevel)
        for prop, value in props.items():
            update_permission_property(dt, role, permlevel, prop, value)

    # Revoke obsolete grants (delete any lingering row for these app-owned pairs).
    for dt, role in REVOKE_PERMS:
        _drop_role_perms(dt, role)


def _drop_role_perms(dt, role, permlevel=0):
    # These (doctype, role) permission rows are EXCLUSIVELY managed by this app
    # (verified: no stock perm ships for them), so removing all rows for the pair
    # before re-granting is config-as-code ownership, not clobbering of others'
    # customizations. It also collapses the if_owner duplicate add_permission would
    # otherwise leave (which ORed flags to resurrect a revoked permission).
    import frappe

    for name in frappe.get_all(
        "Custom DocPerm", filters={"parent": dt, "role": role, "permlevel": permlevel}, pluck="name"
    ):
        frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True, force=True)


def ensure_link_targets():
    # The app's standard reports, workflow fixture, and workspaces reference the
    # custom Department Manager role + workflow state/action masters. Frappe syncs
    # those (sync_for / sync_fixtures) BEFORE after_install/after_migrate runs, so on
    # a fresh install AND on an existing-site upgrade the sync can validate the links
    # before they exist. Create them in before_install/before_migrate so the targets
    # are always present first. All targets are framework/HRMS doctypes available at
    # before_install/before_migrate time.
    ensure_access_control()
    ensure_workflow_masters()


def after_install():
    create_custom_fields(CUSTOM_FIELDS, update=True)
    ensure_access_control()  # create roles/profile FIRST so grants below can target them
    ensure_workflow_masters()
    _ensure_spa_perms()
    ensure_notifications()
