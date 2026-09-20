from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from rayher_hr_payroll.custom_fields import CUSTOM_FIELDS
from rayher_hr_payroll.rd_expense_accounts import DEFAULT_PATHS, ensure_paths
from rayher_hr_payroll.access_control import ensure_access_control
from rayher_hr_payroll.approval_config import ensure_notifications, ensure_workflow_masters
from rayher_hr_payroll.oa_role_resolver import bootstrap_pmc, bootstrap_procurement_manager
from rayher_hr_payroll.organization_master_data import sync_organization_master_data
from rayher_hr_payroll.api.timesheet_entry import ensure_rd_activity_types
from rayher_hr_payroll.api.project_entry import (
    backfill_project_owner_accounts,
    ensure_default_projects,
)

RAYHER_DEFAULT_APP = "rayher_hr_payroll"

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
    # 财务看全员工资 (spec L64): stock Salary Slip grants no read to Accounts User; add it so
    # finance can view payroll (request_visibility lets finance see all salary slips).
    ("Salary Slip", "Accounts User", {"read": 1, "report": 1}),
    # HR 见 PII (spec): id_card_number_cn 等是 Employee 的 permlevel-1 字段; 授予 HR 角色
    # permlevel-1 读写, 让 HR 看到/维护 PII。Accounts User 无 permlevel-1 -> 财务不看 PII。
    ("Employee", "HR Manager", {"read": 1, "write": 1}, 1),
    ("Employee", "HR User", {"read": 1, "write": 1}, 1),
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


def ensure_default_rayher_app():
    import frappe

    frappe.db.set_single_value("System Settings", "default_app", RAYHER_DEFAULT_APP)


def after_install():
    _sync_app(bootstrap_organization=True)


def after_migrate():
    # Existing personnel records are the current source of truth.
    _sync_app(bootstrap_organization=False)


def _sync_app(*, bootstrap_organization):
    ensure_default_rayher_app()
    create_custom_fields(CUSTOM_FIELDS, update=True)
    if bootstrap_organization:
        sync_organization_master_data()
    backfill_timesheet_detail_project_codes()
    backfill_rd_project_keys()
    ensure_access_control()  # create roles/profile FIRST so grants below can target them
    ensure_workflow_masters()
    _ensure_spa_perms()
    ensure_rd_activity_types()
    ensure_default_projects()
    ensure_paths(DEFAULT_PATHS, created_from="系统初始化")
    backfill_project_owner_accounts()
    bootstrap_pmc()
    bootstrap_procurement_manager()
    relink_project_documents()
    ensure_notifications()
    ensure_hidden_workspaces()


def relink_project_documents():
    import frappe

    attachment_fields = [
        "project_initiation_report",
        "project_completion_report",
        "capitalization_confirmation_file",
    ]
    available_fields = [
        fieldname for fieldname in attachment_fields
        if frappe.db.has_column("Project", fieldname)
    ]
    if not available_fields:
        return

    files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Project",
            "attached_to_field": ["in", available_fields],
            "is_private": 1,
        },
        fields=["attached_to_name", "attached_to_field", "file_url"],
        order_by="creation desc",
    )
    linked = set()
    for file_row in files:
        project_name = file_row.get("attached_to_name")
        fieldname = file_row.get("attached_to_field")
        key = (project_name, fieldname)
        if not project_name or not file_row.get("file_url") or key in linked:
            continue
        linked.add(key)
        if not frappe.db.exists("Project", project_name):
            continue
        if frappe.db.get_value("Project", project_name, fieldname):
            continue
        frappe.db.set_value(
            "Project",
            project_name,
            fieldname,
            file_row.get("file_url"),
            update_modified=False,
        )




def backfill_timesheet_detail_project_codes():
    import frappe

    if not frappe.db.has_column("Timesheet Detail", "rd_project_code"):
        return
    frappe.db.sql(
        """
        update `tabTimesheet Detail` tsd
        inner join `tabProject` p on p.name = tsd.project
        set tsd.rd_project_code = p.rd_project_code
        where coalesce(tsd.project, '') != ''
          and coalesce(tsd.rd_project_code, '') = ''
          and coalesce(p.rd_project_code, '') != ''
        """
    )


def backfill_rd_project_keys():
    import frappe

    if frappe.db.has_column("Project", "rd_project_key"):
        frappe.db.sql(
            """
            update `tabProject`
            set rd_project_key = concat(rd_project_code, ' | ', project_name)
            where coalesce(rd_project_key, '') = ''
              and coalesce(rd_project_code, '') != ''
              and coalesce(project_name, '') != ''
            """
        )

    if frappe.db.has_column("Timesheet Detail", "rd_project_name"):
        frappe.db.sql(
            """
            update `tabTimesheet Detail` tsd
            inner join `tabProject` p on p.name = tsd.project
            set tsd.rd_project_name = p.project_name
            where coalesce(tsd.project, '') != ''
              and coalesce(tsd.rd_project_name, '') = ''
              and coalesce(p.project_name, '') != ''
            """
        )

    if frappe.db.has_column("Timesheet Detail", "rd_project_key"):
        frappe.db.sql(
            """
            update `tabTimesheet Detail` tsd
            inner join `tabProject` p on p.name = tsd.project
            set tsd.rd_project_key = concat(
                coalesce(nullif(tsd.rd_project_code, ''), nullif(p.rd_project_code, ''), tsd.project),
                ' | ',
                coalesce(nullif(tsd.rd_project_name, ''), nullif(p.project_name, ''), tsd.project)
            )
            where coalesce(tsd.project, '') != ''
              and coalesce(tsd.rd_project_key, '') = ''
            """
        )

# Stock ERPNext workspaces irrelevant to this HR/OA + R&D-cost deployment (no role uses
# commerce/manufacturing/CRM/integrations). Hidden via is_hidden=1, NOT deleted --
# reversible and non-destructive. Re-applied each migrate so an ERPNext re-sync cannot
# bring the clutter back.
HIDE_WORKSPACES = [
    "Buying", "Selling", "Stock", "Assets", "Manufacturing", "Quality", "Support",
    "Website", "CRM", "Integrations", "ERPNext Integrations", "Welcome Workspace", "Build",
]


def ensure_hidden_workspaces():
    import frappe

    for name in HIDE_WORKSPACES:
        if frappe.db.exists("Workspace", name) and not frappe.db.get_value("Workspace", name, "is_hidden"):
            frappe.db.set_value("Workspace", name, "is_hidden", 1)
