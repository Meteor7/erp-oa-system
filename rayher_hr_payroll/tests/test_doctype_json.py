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
               "accommodation_deduction", "rd_work_ratio_snapshot", "foreign_rd_expense"]


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
        "foreign_rd_expense": {"System Manager": "rwcdREPMS", "Accounts User": "rwcREP"},
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


def test_oa_approval_doctypes_define_request_and_steps():
    request = load_doctype('oa_approval_request')
    step = load_doctype('oa_approval_step')
    expense_line = load_doctype('oa_approval_expense_line')
    request_fields = {field["fieldname"]: field for field in request["fields"] if "fieldname" in field}
    step_fields = fieldnames(step)
    line_fields = fieldnames(expense_line)

    assert request['is_submittable'] == 0
    assert {
        'request_type', 'workflow_status', 'company', 'employee', 'department', 'supervisor', 'doc_type',
        'urgency', 'source_type', 'source_summary', 'payment_type', 'payment_method', 'bank_name',
        'payee_name', 'branch', 'account_no', 'paid_by', 'paid_on', 'expense_lines', 'steps'
    }.issubset(request_fields)
    assert request_fields['expense_lines']['options'] == 'OA Approval Expense Line'
    assert {
        '\u8349\u7a3f', '\u5f85\u5ba1\u6279', '\u5f85\u529e\u7406', '\u5df2\u5b8c\u6210',
        '\u5df2\u62d2\u7edd', '\u5df2\u4ed8\u6b3e'
    }.issubset(set(request_fields['workflow_status']['options'].split('\n')))
    assert {'Employee', 'Department Manager', 'Accounts User', 'HR User', 'HR Manager'}.issubset(
        {p['role'] for p in request['permissions']}
    )
    assert step['istable'] == 1
    assert {'step_index', 'label', 'mode', 'approvers', 'status', 'approved_by', 'action_by', 'acted_on'}.issubset(step_fields)
    assert expense_line['istable'] == 1
    assert {
        'source_consumption', 'start_date', 'end_date', 'category', 'amount',
        'description', 'attachment_count', 'invoice_status'
    }.issubset(line_fields)


def test_oa_consumption_detail_doctypes_define_invoice_pushdown_model():
    consumption = load_doctype('oa_consumption_detail')
    invoice = load_doctype('oa_invoice_attachment')
    consumption_fields = {field["fieldname"]: field for field in consumption["fields"] if "fieldname" in field}
    invoice_fields = fieldnames(invoice)

    assert consumption['is_submittable'] == 0
    assert {
        'title', 'employee', 'employee_name', 'department', 'expense_date', 'category',
        'amount', 'description', 'status', 'linked_request', 'invoice_count', 'invoices'
    }.issubset(consumption_fields)
    assert consumption_fields['invoices']['options'] == 'OA Invoice Attachment'
    assert consumption_fields['linked_request']['options'] == 'OA Approval Request'
    assert {
        '\u5f85\u4e0a\u4f20', '\u5df2\u4e0a\u4f20\u53d1\u7968', '\u5f85\u4e0b\u63a8',
        '\u5df2\u4e0b\u63a8', '\u5df2\u9a73\u56de'
    }.issubset(set(consumption_fields['status']['options'].split('\n')))
    assert {'Employee', 'Department Manager', 'Accounts User', 'HR User', 'HR Manager'}.issubset(
        {p['role'] for p in consumption['permissions']}
    )
    assert invoice['istable'] == 1
    assert {'invoice_name', 'invoice_file', 'file_type', 'file_size', 'invoice_status', 'uploaded_on', 'remark'}.issubset(invoice_fields)



def test_foreign_rd_expense_doctypes_store_total_and_hour_lines():
    parent = load_doctype("foreign_rd_expense")
    child = load_doctype("foreign_rd_expense_line")
    parent_fields = {field["fieldname"]: field for field in parent["fields"]}
    child_fields = {field["fieldname"]: field for field in child["fields"]}

    assert parent["istable"] == 0
    assert parent_fields["total_amount"]["fieldtype"] == "Currency"
    assert parent_fields["lines"]["options"] == "Foreign RD Expense Line"
    assert {"period", "year", "month", "total_amount", "lines"}.issubset(parent_fields)
    assert child["istable"] == 1
    assert {"work_date", "project", "project_code", "project_name", "activity_type", "project_stage", "hours", "ratio", "allocated_amount", "description"}.issubset(child_fields)



def test_rd_cost_allocation_line_keeps_expense_account_levels_for_matrix_report():
    fields = {field["fieldname"]: field for field in load_doctype("rd_cost_allocation_line")["fields"]}

    assert fields["account_level_3"]["fieldtype"] == "Data"
    assert fields["account_level_4"]["fieldtype"] == "Data"

INVOICE_RECOGNITION_STATUSES = {
    "排队中", "识别中", "待确认", "已确认", "疑似重复", "失败", "已排除"
}


def _fields_by_name(doc: dict) -> dict[str, dict]:
    return {field["fieldname"]: field for field in doc["fields"] if "fieldname" in field}


def _permission_rights(permission: dict) -> set[str]:
    rights = {"read", "write", "create", "delete", "report", "export", "print", "email", "share"}
    return {right for right in rights if permission.get(right)}


def test_invoice_ocr_doctypes_define_auditable_records():
    batch = load_doctype("oa_invoice_import_batch")
    record = load_doctype("oa_invoice_record")
    view_log = load_doctype("oa_invoice_view_log")
    batch_fields = _fields_by_name(batch)
    record_fields = _fields_by_name(record)
    log_fields = _fields_by_name(view_log)

    assert batch["track_changes"] == 1
    assert {
        "temporary_token", "request", "uploaded_by", "batch_status", "total_count",
        "queued_count", "processing_count", "pending_confirmation_count",
        "confirmed_count", "duplicate_count", "failed_count", "excluded_count",
        "expires_on", "error_summary",
    }.issubset(batch_fields)
    assert batch_fields["request"]["options"] == "OA Approval Request"
    assert batch_fields["uploaded_by"]["options"] == "User"
    assert set(batch_fields["batch_status"]["options"].split("\n")) == INVOICE_RECOGNITION_STATUSES

    assert record["track_changes"] == 1
    assert {
        "batch", "invoice_file", "original_filename", "mime_type", "file_size", "file_sha256",
        "invoice_category", "project_name", "issue_date", "invoice_number",
        "amount_before_tax", "tax_amount", "total_amount", "ocr_payload", "field_warnings",
        "recognition_status", "duplicate_of", "duplicate_reason", "request", "expense_line_key",
        "uploaded_by", "confirmed_by", "confirmed_on", "processing_error", "retry_count",
    }.issubset(record_fields)
    assert record_fields["batch"]["options"] == "OA Invoice Import Batch"
    assert record_fields["invoice_file"]["fieldtype"] == "Attach"
    assert record_fields["file_sha256"]["fieldtype"] == "Data"
    assert record_fields["invoice_number"]["fieldtype"] == "Data"
    assert record_fields["expense_line_key"]["fieldtype"] == "Data"
    assert record_fields["duplicate_of"]["fieldtype"] == "Link"
    assert record_fields["duplicate_of"]["options"] == "OA Invoice Record"
    assert record_fields["request"]["options"] == "OA Approval Request"
    assert record_fields["confirmed_by"]["options"] == "User"
    assert record_fields["confirmed_on"]["fieldtype"] == "Datetime"
    assert all(record_fields[name]["fieldtype"] == "Currency" for name in (
        "amount_before_tax", "tax_amount", "total_amount"
    ))
    assert record_fields["ocr_payload"]["fieldtype"] in {"Code", "Long Text"}
    assert record_fields["field_warnings"]["fieldtype"] in {"Code", "Long Text"}
    assert set(record_fields["recognition_status"]["options"].split("\n")) == INVOICE_RECOGNITION_STATUSES
    assert not any(record_fields[name].get("reqd") for name in (
        "invoice_category", "project_name", "issue_date", "invoice_number",
        "amount_before_tax", "tax_amount", "total_amount",
    ))

    assert view_log["track_changes"] == 1
    assert {
        "invoice_record", "invoice_file", "request", "action", "viewed_by", "viewed_on",
        "ip_address", "user_agent",
    }.issubset(log_fields)
    assert log_fields["invoice_record"]["options"] == "OA Invoice Record"
    assert log_fields["request"]["options"] == "OA Approval Request"
    assert log_fields["viewed_by"]["options"] == "User"


def test_invoice_ocr_extensions_preserve_existing_expense_and_request_models():
    expense_line = load_doctype("oa_approval_expense_line")
    request = load_doctype("oa_approval_request")
    line_fields = _fields_by_name(expense_line)
    request_fields = _fields_by_name(request)

    assert expense_line["istable"] == 1
    assert line_fields["line_key"]["fieldtype"] == "Data"
    assert line_fields["invoice_difference_reason"]["fieldtype"] in {"Small Text", "Long Text"}
    assert line_fields["line_key"].get("reqd") != 1
    assert request_fields["invoice_count"]["fieldtype"] == "Int"
    assert request_fields["invoice_count"].get("read_only") == 1
    assert request_fields["invoice_status"].get("read_only") == 1
    assert request_fields["no_invoice_reason"]["fieldtype"] in {"Small Text", "Long Text"}
    assert request_fields["no_invoice_reason"].get("reqd") != 1


def test_invoice_ocr_metadata_uses_minimum_role_permissions():
    for folder in ("oa_invoice_import_batch", "oa_invoice_record"):
        doc = load_doctype(folder)
        by_role = {permission["role"]: permission for permission in doc["permissions"]}
        assert _permission_rights(by_role["Employee"]) == {"read", "create"}
        assert by_role["Employee"].get("if_owner") == 1
        for role in ("Department Manager", "Accounts User", "HR User", "HR Manager"):
            assert _permission_rights(by_role[role]) == {"read"}
        assert by_role["System Manager"].get("delete") == 1
        assert all(
            permission["role"] == "System Manager" or not permission.get("delete")
            for permission in doc["permissions"]
        )

    view_log = load_doctype("oa_invoice_view_log")
    log_by_role = {permission["role"]: permission for permission in view_log["permissions"]}
    assert _permission_rights(log_by_role["Employee"]) == {"read", "create"}
    assert log_by_role["Employee"].get("if_owner") == 1
    for role in ("Department Manager", "Accounts User", "HR User", "HR Manager"):
        assert _permission_rights(log_by_role[role]) == {"read"}
    assert log_by_role["System Manager"].get("delete") == 1
    for permission in view_log["permissions"]:
        if permission["role"] != "System Manager":
            assert not permission.get("write")
            assert not permission.get("delete")