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
SPA_PERMS = []


def _ensure_spa_perms():
    from frappe.permissions import add_permission, update_permission_property

    for dt, role, props in SPA_PERMS:
        add_permission(dt, role, 0)
        for prop, value in props.items():
            update_permission_property(dt, role, 0, prop, value)


def after_install():
    create_custom_fields(CUSTOM_FIELDS, update=True)
    _ensure_spa_perms()
    ensure_access_control()
    ensure_workflow_masters()
    ensure_notifications()
