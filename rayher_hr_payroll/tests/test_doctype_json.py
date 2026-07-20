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

INVOICE_RECOGNITION_STATUSES = [
    "\u6392\u961f\u4e2d", "\u8bc6\u522b\u4e2d", "\u5f85\u786e\u8ba4", "\u5df2\u786e\u8ba4",
    "\u7591\u4f3c\u91cd\u590d", "\u5931\u8d25", "\u5df2\u6392\u9664",
]
INVOICE_BATCH_STATUSES = [
    "\u5f85\u4e0a\u4f20", "\u5904\u7406\u4e2d", "\u5f85\u786e\u8ba4", "\u5df2\u5b8c\u6210",
    "\u90e8\u5206\u5931\u8d25", "\u5931\u8d25", "\u5df2\u53d6\u6d88",
]
INVOICE_METADATA_DOCTYPES = (
    "oa_invoice_import_batch", "oa_invoice_record", "oa_invoice_view_log",
    "oa_approval_expense_line", "oa_approval_request",
)
INVOICE_ROLES = {
    "System Manager", "Employee", "Department Manager", "Accounts User", "HR User", "HR Manager",
}


def _fields_by_name(doc: dict) -> dict[str, dict]:
    return {field["fieldname"]: field for field in doc["fields"] if "fieldname" in field}


def _assert_exact_field_order(doc: dict) -> None:
    names = [field["fieldname"] for field in doc["fields"]]
    assert len(names) == len(set(names)), (doc["name"], names)
    assert doc["field_order"] == names, (doc["name"], doc["field_order"], names)


def _permission_rights(permission: dict) -> set[str]:
    rights = {
        "read", "write", "create", "delete", "submit", "cancel", "amend",
        "report", "export", "import", "print", "email", "share", "select",
    }
    return {right for right in rights if permission.get(right)}


def _permissions_by_role(doc: dict) -> dict[str, dict]:
    roles = [permission["role"] for permission in doc["permissions"]]
    assert len(roles) == len(set(roles)), (doc["name"], roles)
    assert set(roles) == INVOICE_ROLES, (doc["name"], roles)
    return {permission["role"]: permission for permission in doc["permissions"]}


def test_invoice_ocr_changed_doctypes_have_exact_one_to_one_field_order():
    for folder in INVOICE_METADATA_DOCTYPES:
        _assert_exact_field_order(load_doctype(folder))


def test_invoice_import_batch_uses_an_independent_ordered_lifecycle():
    batch = load_doctype("oa_invoice_import_batch")
    fields = _fields_by_name(batch)
    assert batch["track_changes"] == 1
    assert fields["batch_status"]["fieldtype"] == "Select"
    assert fields["batch_status"]["options"].split("\n") == INVOICE_BATCH_STATUSES
    assert fields["batch_status"]["default"] == "\u5f85\u4e0a\u4f20"
    assert len(INVOICE_BATCH_STATUSES) == len(set(INVOICE_BATCH_STATUSES))
    assert INVOICE_BATCH_STATUSES != INVOICE_RECOGNITION_STATUSES
    expected = {
        "temporary_token": ("Data", None), "request": ("Link", None),
        "uploaded_by": ("Link", None), "total_count": ("Int", "0"),
        "queued_count": ("Int", "0"), "processing_count": ("Int", "0"),
        "pending_confirmation_count": ("Int", "0"), "confirmed_count": ("Int", "0"),
        "duplicate_count": ("Int", "0"), "failed_count": ("Int", "0"),
        "excluded_count": ("Int", "0"), "expires_on": ("Datetime", None),
        "error_summary": ("Long Text", None),
    }
    for name, (fieldtype, default) in expected.items():
        assert fields[name]["fieldtype"] == fieldtype, name
        assert fields[name].get("read_only") == 1, name
        assert fields[name].get("default") == default, name
    assert fields["temporary_token"].get("unique") == 1
    assert fields["temporary_token"].get("reqd") != 1
    assert fields["request"]["options"] == "OA Approval Request"
    assert fields["uploaded_by"]["options"] == "User"


def test_invoice_record_fields_and_status_are_exact_and_nullable():
    record = load_doctype("oa_invoice_record")
    fields = _fields_by_name(record)
    assert record["track_changes"] == 1
    seven_fields = {
        "invoice_category": "Data", "project_name": "Small Text", "issue_date": "Date",
        "invoice_number": "Data", "amount_before_tax": "Currency",
        "tax_amount": "Currency", "total_amount": "Currency",
    }
    for name, fieldtype in seven_fields.items():
        assert fields[name]["fieldtype"] == fieldtype, name
        assert fields[name].get("reqd") != 1, name
        assert fields[name].get("read_only") != 1, name
        if fieldtype == "Currency":
            assert fields[name].get("precision") in {"2", 2}, name
    assert fields["recognition_status"]["fieldtype"] == "Select"
    assert fields["recognition_status"]["options"].split("\n") == INVOICE_RECOGNITION_STATUSES
    assert fields["recognition_status"]["default"] == "\u6392\u961f\u4e2d"
    assert len(INVOICE_RECOGNITION_STATUSES) == len(set(INVOICE_RECOGNITION_STATUSES))
    contracts = {
        "batch": ("Link", "OA Invoice Import Batch", True),
        "invoice_file": ("Attach", None, True), "original_filename": ("Data", None, True),
        "mime_type": ("Data", None, True), "file_size": ("Int", None, True),
        "file_sha256": ("Data", None, True), "uploaded_by": ("Link", "User", True),
        "ocr_payload": ("Code", "JSON", False), "field_warnings": ("Code", "JSON", False),
        "duplicate_of": ("Link", "OA Invoice Record", False),
        "duplicate_reason": ("Small Text", None, False),
        "request": ("Link", "OA Approval Request", False),
        "expense_line_key": ("Data", None, False), "confirmed_by": ("Link", "User", False),
        "confirmed_on": ("Datetime", None, False), "processing_error": ("Long Text", None, False),
        "retry_count": ("Int", None, False),
    }
    for name, (fieldtype, options, required) in contracts.items():
        assert fields[name]["fieldtype"] == fieldtype, name
        assert fields[name].get("options") == options, name
        assert fields[name].get("read_only") == 1, name
        assert bool(fields[name].get("reqd")) is required, name
    assert fields["file_sha256"].get("search_index") == 1
    assert fields["invoice_number"].get("search_index") == 1
    assert fields["expense_line_key"].get("search_index") == 1
    assert fields["retry_count"].get("default") == "0"


def test_invoice_view_log_metadata_is_immutable_and_auditable():
    view_log = load_doctype("oa_invoice_view_log")
    fields = _fields_by_name(view_log)
    assert view_log["track_changes"] == 1
    contracts = {
        "invoice_record": ("Link", "OA Invoice Record", True),
        "invoice_file": ("Data", None, True), "request": ("Link", "OA Approval Request", False),
        "action": ("Select", "\u67e5\u770b\n\u4e0b\u8f7d", True),
        "viewed_by": ("Link", "User", True), "viewed_on": ("Datetime", None, True),
        "ip_address": ("Data", None, False), "user_agent": ("Small Text", None, False),
    }
    for name, (fieldtype, options, required) in contracts.items():
        assert fields[name]["fieldtype"] == fieldtype, name
        assert fields[name].get("options") == options, name
        assert fields[name].get("read_only") == 1, name
        assert bool(fields[name].get("reqd")) is required, name
    assert fields["action"]["options"].split("\n") == ["\u67e5\u770b", "\u4e0b\u8f7d"]


def test_invoice_expense_and_request_extensions_are_exact_and_backward_compatible():
    line_fields = _fields_by_name(load_doctype("oa_approval_expense_line"))
    request_fields = _fields_by_name(load_doctype("oa_approval_request"))
    assert line_fields["line_key"]["fieldtype"] == "Data"
    assert line_fields["line_key"].get("read_only") == 1
    assert line_fields["line_key"].get("search_index") == 1
    assert line_fields["line_key"].get("unique") == 1
    assert line_fields["line_key"].get("reqd") != 1
    assert line_fields["invoice_difference_reason"]["fieldtype"] == "Small Text"
    assert line_fields["invoice_difference_reason"].get("reqd") != 1
    assert request_fields["invoice_count"]["fieldtype"] == "Int"
    assert request_fields["invoice_count"].get("default") == "0"
    assert request_fields["invoice_count"].get("read_only") == 1
    assert request_fields["invoice_count"].get("reqd") != 1
    assert request_fields["invoice_status"]["fieldtype"] == "Data"
    assert request_fields["invoice_status"].get("read_only") == 1
    assert request_fields["invoice_status"].get("reqd") != 1
    assert request_fields["no_invoice_reason"]["fieldtype"] == "Small Text"
    assert request_fields["no_invoice_reason"].get("reqd") != 1


def _assert_exact_permission(permission: dict, rights: set[str], *, if_owner: bool = False) -> None:
    expected_keys = {"role", "permlevel", *rights}
    if if_owner:
        expected_keys.add("if_owner")
    assert set(permission) == expected_keys, permission
    assert permission["permlevel"] == 0
    assert _permission_rights(permission) == rights
    assert bool(permission.get("if_owner")) is if_owner


def test_invoice_ocr_metadata_uses_the_exact_minimum_permission_matrix():
    read_roles = ("Department Manager", "Accounts User", "HR User", "HR Manager")
    system_rights = {"read", "write", "create", "delete", "report", "export", "print"}
    for folder in ("oa_invoice_import_batch", "oa_invoice_record", "oa_invoice_view_log"):
        by_role = _permissions_by_role(load_doctype(folder))
        _assert_exact_permission(by_role["Employee"], {"read"}, if_owner=True)
        for role in read_roles:
            _assert_exact_permission(by_role[role], {"read"})
        _assert_exact_permission(by_role["System Manager"], system_rights)


def _load_view_log_controller(
    monkeypatch, *, invoice, now_value, session_user="employee@example.com",
    request_context=None, request_ip=None,
):
    import importlib.util
    import sys
    from types import ModuleType, SimpleNamespace

    frappe_module = ModuleType("frappe")
    model_module = ModuleType("frappe.model")
    document_module = ModuleType("frappe.model.document")
    utils_module = ModuleType("frappe.utils")

    class Document:
        pass

    class ValidationError(Exception):
        pass

    calls = []

    def get_doc(doctype, name):
        calls.append((doctype, name))
        return invoice

    def throw(message, exc=ValidationError):
        raise exc(message)

    document_module.Document = Document
    utils_module.now_datetime = lambda: now_value
    frappe_module.session = SimpleNamespace(user=session_user)
    frappe_module.ValidationError = ValidationError
    frappe_module.get_doc = get_doc
    frappe_module.throw = throw
    frappe_module._ = lambda message: message
    frappe_module.local = SimpleNamespace()
    if request_context is not None:
        frappe_module.local.request = request_context
        frappe_module.local.request_ip = request_ip
    monkeypatch.setitem(sys.modules, "frappe", frappe_module)
    monkeypatch.setitem(sys.modules, "frappe.model", model_module)
    monkeypatch.setitem(sys.modules, "frappe.model.document", document_module)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils_module)
    path = DOCTYPE_ROOT / "oa_invoice_view_log" / "oa_invoice_view_log.py"
    spec = importlib.util.spec_from_file_location("task3_oa_invoice_view_log_controller", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.OAInvoiceViewLog, ValidationError, calls


@pytest.mark.parametrize("action", ["\u67e5\u770b", "\u4e0b\u8f7d"])
def test_invoice_view_log_before_insert_overwrites_untrusted_request_audit(monkeypatch, action):
    from types import SimpleNamespace

    permission_calls = []
    invoice = SimpleNamespace(
        invoice_file="/private/files/trusted-invoice.pdf", request="OA-REQ-0001",
        check_permission=lambda permission: permission_calls.append(permission),
    )
    now_value = object()
    request_context = SimpleNamespace(headers={"User-Agent": "Trusted Browser/1.0"})
    controller, _, get_doc_calls = _load_view_log_controller(
        monkeypatch, invoice=invoice, now_value=now_value,
        request_context=request_context, request_ip="203.0.113.8",
    )
    log = controller()
    log.invoice_record = "OIR-2026-0000001"
    log.action = action
    log.invoice_file = "/private/files/forged.pdf"
    log.request = "OA-REQ-FORGED"
    log.viewed_by = "attacker@example.com"
    log.viewed_on = "2000-01-01 00:00:00"
    log.ip_address = "198.51.100.99"
    log.user_agent = "Forged Browser"
    log.before_insert()
    assert get_doc_calls == [("OA Invoice Record", "OIR-2026-0000001")]
    assert permission_calls == ["read"]
    assert log.invoice_file == "/private/files/trusted-invoice.pdf"
    assert log.request == "OA-REQ-0001"
    assert log.viewed_by == "employee@example.com"
    assert log.viewed_on is now_value
    assert log.ip_address == "203.0.113.8"
    assert log.user_agent == "Trusted Browser/1.0"


def test_invoice_view_log_before_insert_clears_network_audit_without_request_context(monkeypatch):
    from types import SimpleNamespace

    invoice = SimpleNamespace(
        invoice_file="/private/files/trusted-invoice.pdf", request=None,
        check_permission=lambda permission: None,
    )
    controller, _, _ = _load_view_log_controller(
        monkeypatch, invoice=invoice, now_value=object(), session_user="Administrator",
    )
    log = controller()
    log.invoice_record = "OIR-2026-0000001"
    log.action = "\u67e5\u770b"
    log.ip_address = "198.51.100.99"
    log.user_agent = "Forged Browser"
    log.before_insert()
    assert log.ip_address is None
    assert log.user_agent is None


def test_invoice_view_log_before_insert_rejects_unknown_actions_before_loading_source(monkeypatch):
    from types import SimpleNamespace

    invoice = SimpleNamespace(invoice_file="ignored", request=None, check_permission=lambda permission: None)
    controller, validation_error, get_doc_calls = _load_view_log_controller(
        monkeypatch, invoice=invoice, now_value=object(), session_user="Administrator",
    )
    log = controller()
    log.invoice_record = "OIR-2026-0000001"
    log.action = "\u4ee3\u586b\u5ba1\u8ba1"
    with pytest.raises(validation_error, match="\u67e5\u770b.*\u4e0b\u8f7d"):
        log.before_insert()
    assert get_doc_calls == []


def test_invoice_view_log_before_insert_stops_when_source_read_is_denied(monkeypatch):
    from types import SimpleNamespace

    def deny_read(permission):
        assert permission == "read"
        raise PermissionError("source invoice read denied")

    invoice = SimpleNamespace(
        invoice_file="/private/files/trusted-invoice.pdf", request="OA-REQ-0001",
        check_permission=deny_read,
    )
    controller, _, get_doc_calls = _load_view_log_controller(
        monkeypatch, invoice=invoice, now_value=object(),
    )
    log = controller()
    log.invoice_record = "OIR-2026-0000001"
    log.action = "\u4e0b\u8f7d"
    log.invoice_file = "/private/files/forged.pdf"
    log.request = "OA-REQ-FORGED"
    log.viewed_by = "attacker@example.com"
    log.viewed_on = "2000-01-01 00:00:00"
    log.ip_address = "198.51.100.99"
    log.user_agent = "Forged Browser"
    with pytest.raises(PermissionError, match="source invoice read denied"):
        log.before_insert()
    assert get_doc_calls == [("OA Invoice Record", "OIR-2026-0000001")]
    assert log.invoice_file == "/private/files/forged.pdf"
    assert log.request == "OA-REQ-FORGED"
    assert log.viewed_by == "attacker@example.com"
    assert log.viewed_on == "2000-01-01 00:00:00"
    assert log.ip_address == "198.51.100.99"
    assert log.user_agent == "Forged Browser"
