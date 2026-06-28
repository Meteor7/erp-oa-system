import json
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = APP_ROOT / "rayher_hr_payroll"
DOCTYPE_ROOT = MODULE_ROOT / "doctype"


def load_doctype(folder: str) -> dict:
    path = DOCTYPE_ROOT / folder / f"{folder}.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def fieldnames(doc: dict) -> set[str]:
    return {field["fieldname"] for field in doc["fields"] if "fieldname" in field}


def test_frappe_module_package_exists_for_modules_txt():
    assert (MODULE_ROOT / "__init__.py").exists()
    assert DOCTYPE_ROOT.exists()


def test_rd_expense_item_has_source_row_key_for_duplicate_guard():
    doc = load_doctype("rd_expense_item")

    assert doc["istable"] == 1
    assert {"source_row_key", "voucher_no", "amount", "direct_project"}.issubset(fieldnames(doc))


def test_rd_cost_allocation_has_source_snapshot_tables():
    doc = load_doctype("rd_cost_allocation")
    fields = {field["fieldname"]: field for field in doc["fields"]}

    assert doc["is_submittable"] == 1
    assert fields["hour_snapshots"]["options"] == "RD Allocation Source Hour"
    assert fields["expense_snapshots"]["options"] == "RD Allocation Source Expense"


def test_rd_period_lock_locks_timesheets_gl_and_allocations():
    doc = load_doctype("rd_period_lock")

    assert doc["is_submittable"] == 1
    assert {"lock_timesheets", "lock_project_stage", "lock_gl_import", "lock_allocations"}.issubset(fieldnames(doc))


def test_rayher_hr_settings_contains_standard_daily_hours():
    doc = load_doctype("rayher_hr_settings")

    assert doc["issingle"] == 1
    assert "standard_daily_hours" in fieldnames(doc)

def load_report(folder: str) -> dict:
    path = MODULE_ROOT / "report" / folder / f"{folder}.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def test_period_fields_are_derived_read_only_values():
    for folder in ["rd_cost_allocation", "rd_expense_import", "rd_period_lock"]:
        fields = {field["fieldname"]: field for field in load_doctype(folder)["fields"]}
        assert fields["period"].get("read_only") == 1
        assert fields["period"].get("reqd") != 1


def test_reports_declare_required_filters():
    exceptions = load_report("rd_timesheet_exceptions")
    matrix = load_report("rd_allocation_matrix")

    assert {field["fieldname"] for field in exceptions["filters"]} == {"year", "month"}
    assert {field["fieldname"] for field in matrix["filters"]} == {"allocation"}


def test_rd_cost_allocation_has_unknown_total():
    fields = {field["fieldname"]: field for field in load_doctype("rd_cost_allocation")["fields"]}

    assert fields["unknown_total"]["fieldtype"] == "Currency"


def test_period_doctype_controllers_normalize_before_insert():
    pytest.importorskip("frappe")  # controller modules import frappe at top
    from rayher_hr_payroll.rayher_hr_payroll.doctype.rd_cost_allocation.rd_cost_allocation import RDCostAllocation
    from rayher_hr_payroll.rayher_hr_payroll.doctype.rd_expense_import.rd_expense_import import RDExpenseImport
    from rayher_hr_payroll.rayher_hr_payroll.doctype.rd_period_lock.rd_period_lock import RDPeriodLock

    assert all(hasattr(cls, "before_insert") for cls in [RDCostAllocation, RDExpenseImport, RDPeriodLock])
def _roles_with(doc: dict, perm: str) -> set[str]:
    return {p["role"] for p in doc.get("permissions", []) if p.get(perm)}


RD_DOCTYPES = ["rd_cost_allocation", "rd_expense_import", "rd_period_lock",
               "accommodation_deduction", "rd_work_ratio_snapshot"]


def test_finance_role_can_read_and_report_every_rd_doctype():
    for folder in RD_DOCTYPES:
        doc = load_doctype(folder)
        assert "Accounts User" in _roles_with(doc, "read"), folder
        assert "Accounts User" in _roles_with(doc, "report"), folder


def test_finance_role_can_operate_the_allocation_chain():
    for folder in ["rd_cost_allocation", "rd_expense_import", "rd_period_lock"]:
        doc = load_doctype(folder)
        assert "Accounts User" in _roles_with(doc, "create"), folder
        assert "Accounts User" in _roles_with(doc, "submit"), folder


def test_accounts_user_cannot_cancel_a_period_lock():
    # Finance may lock a period but must not unilaterally unlock it (only System Manager).
    assert "Accounts User" not in _roles_with(load_doctype("rd_period_lock"), "cancel")


def test_only_system_manager_can_share_or_email_rd_doctypes():
    for folder in RD_DOCTYPES:
        for p in load_doctype(folder)["permissions"]:
            if p["role"] != "System Manager":
                assert not p.get("share"), (folder, p["role"])
                assert not p.get("email"), (folder, p["role"])


def test_submit_perm_only_on_submittable_doctypes():
    for folder in ["accommodation_deduction", "rd_work_ratio_snapshot"]:
        doc = load_doctype(folder)
        assert doc.get("is_submittable", 0) == 0, folder
        for p in doc["permissions"]:
            assert not p.get("submit") and not p.get("cancel") and not p.get("amend"), (folder, p["role"])


def test_projects_manager_has_no_access_to_allocation():
    # The allocation now embeds per-employee salary-derived labor rows, so it must
    # not be visible to Projects Manager (salary data is finance/HR only).
    roles = {p["role"] for p in load_doctype("rd_cost_allocation")["permissions"]}
    assert "Projects Manager" not in roles
    assert "Projects Manager" not in {r["role"] for r in load_report("rd_allocation_matrix").get("roles", [])}


def test_hr_user_has_no_access_to_rd_cost_allocation():
    assert "HR User" not in {p["role"] for p in load_doctype("rd_cost_allocation")["permissions"]}


def test_matrix_report_grants_finance_and_matches_doctype_report_perms():
    report_roles = {r["role"] for r in load_report("rd_allocation_matrix").get("roles", [])}
    assert "Accounts User" in report_roles
    reporters = {p["role"] for p in load_doctype("rd_cost_allocation")["permissions"] if p.get("report")}
    assert reporters == report_roles, (reporters, report_roles)


def test_exceptions_report_scoped_to_timesheet_capable_roles():
    # ref_doctype is Timesheet; restrict to roles that natively hold Timesheet report
    # permission (HR User, System Manager) so the report doesn't depend on granting a
    # non-timesheet role (Finance) extra Timesheet access.
    roles = {r["role"] for r in load_report("rd_timesheet_exceptions").get("roles", [])}
    assert roles == {"System Manager", "HR User"}


def test_finance_cannot_delete_any_rd_doctype_or_cancel_submitted_ones():
    # Finance must not hard-delete ANY R&D cost record, nor cancel/unlock submitted ones;
    # all such corrections go through System Manager.
    for folder in RD_DOCTYPES:
        assert "Accounts User" not in _roles_with(load_doctype(folder), "delete"), folder
    for folder in ["rd_cost_allocation", "rd_expense_import", "rd_period_lock"]:
        assert "Accounts User" not in _roles_with(load_doctype(folder), "cancel"), folder


def test_exact_permission_matrix_on_all_changed_doctypes():
    # Pin every role/right on every changed doctype so no grant can drift untested.
    rights = {"r": "read", "w": "write", "c": "create", "d": "delete", "s": "submit",
              "x": "cancel", "a": "amend", "R": "report", "E": "export", "P": "print",
              "M": "email", "S": "share"}
    flags = {
        "rd_cost_allocation": {"System Manager": "rwcdsxaREPMS", "Accounts User": "rwcsREP"},
        "rd_expense_import": {"System Manager": "rwcdsxaREPMS", "Accounts User": "rwcsREP"},
        "rd_period_lock": {"System Manager": "rwcdsxaREP", "Accounts User": "rwcsR"},
        "accommodation_deduction": {"System Manager": "rwcdREPMS", "Accounts User": "rwcR", "HR User": "rwcR"},
        "rd_work_ratio_snapshot": {"System Manager": "rwcdREP", "Accounts User": "rR", "HR User": "rR"},
    }
    for folder, roles in flags.items():
        doc = load_doctype(folder)
        actual = {p["role"]: {name for f, name in rights.items() if p.get(name)} for p in doc["permissions"]}
        expected = {role: {rights[f] for f in fl} for role, fl in roles.items()}
        assert actual == expected, (folder, actual, expected)


def test_rd_cost_allocation_persists_skipped_labor():
    fields = {field["fieldname"]: field for field in load_doctype("rd_cost_allocation")["fields"]}
    assert "labor_skipped" in fields  # under-counted (incomplete-hours) employees recorded on the doc
    assert fields["labor_skipped"]["read_only"] == 1
