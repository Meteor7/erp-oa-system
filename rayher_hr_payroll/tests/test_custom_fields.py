from pathlib import Path

from rayher_hr_payroll.custom_fields import CUSTOM_FIELDS


def test_employee_rd_personnel_type_exists():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Employee"]}

    assert fields["rd_personnel_type"]["fieldtype"] == "Select"
    assert "全时研发" in fields["rd_personnel_type"]["options"]
    assert "非全时研发" in fields["rd_personnel_type"]["options"]
    assert "非研发" in fields["rd_personnel_type"]["options"]


def test_project_capitalization_fields_exist():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Project"]}

    assert fields["allow_rd_timesheet"]["fieldtype"] == "Check"
    assert fields["project_owner_name"]["fieldtype"] == "Data"
    assert fields["project_owner_name"]["label"] == "项目负责人"
    assert fields["project_owner"]["fieldtype"] == "Link"
    assert fields["project_owner"]["options"] == "User"
    assert fields["project_owner"]["hidden"] == 1
    assert fields["capitalization_start_date"]["fieldtype"] == "Date"
    assert fields["capitalization_end_date"]["fieldtype"] == "Date"
    assert fields["rd_project_key"]["fieldtype"] == "Data"
    assert fields["rd_project_key"]["label"] == "\u9879\u76ee\u6807\u8bc6"
    assert fields["rd_project_key"]["read_only"] == 1
    assert fields["project_initiation_report"]["fieldtype"] == "Attach"
    assert fields["project_completion_report"]["fieldtype"] == "Attach"
    assert fields["capitalization_confirmation_file"]["fieldtype"] == "Attach"


def test_timesheet_review_fields_exist():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Timesheet"]}

    assert fields["rd_review_status"]["fieldtype"] == "Select"
    assert fields["rd_reviewer"]["options"] == "User"


def test_timesheet_monthly_entry_fields_exist():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Timesheet"]}

    assert fields["rd_monthly_entry_id"]["fieldtype"] == "Data"
    assert fields["rd_monthly_entry_id"]["unique"] == 1
    assert fields["rd_entry_period"]["fieldtype"] == "Data"
    assert fields["rd_occurrence_days"]["fieldtype"] == "Float"
    assert fields["rd_occurrence_days"]["precision"] == 2
    assert fields["rd_calculated_hours"]["fieldtype"] == "Float"
    assert fields["rd_calculated_hours"]["precision"] == 2
    assert fields["rd_system_generated"]["fieldtype"] == "Check"


def test_timesheet_detail_project_code_field_exists():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Timesheet Detail"]}

    project_code = fields["rd_project_code"]
    assert project_code["fieldtype"] == "Data"
    assert project_code["label"] == "\u9879\u76ee\u4ee3\u7801"
    assert project_code["fetch_from"] == "project.rd_project_code"
    assert project_code["read_only"] == 1
    assert project_code["insert_after"] == "project"

    project_name = fields["rd_project_name"]
    assert project_name["fieldtype"] == "Data"
    assert project_name["label"] == "\u9879\u76ee\u540d\u79f0"
    assert project_name["read_only"] == 1
    assert project_name["insert_after"] == "rd_project_code"

    project_key = fields["rd_project_key"]
    assert project_key["fieldtype"] == "Data"
    assert project_key["label"] == "\u9879\u76ee\u6807\u8bc6"
    assert project_key["read_only"] == 1
    assert project_key["insert_after"] == "rd_project_name"


def test_custom_fieldnames_are_unique_per_doctype():
    for doctype, fields in CUSTOM_FIELDS.items():
        names = [field["fieldname"] for field in fields]
        assert len(names) == len(set(names)), doctype


def test_custom_fields_sync_on_install_and_migrate():
    from rayher_hr_payroll import hooks

    assert hooks.after_install == "rayher_hr_payroll.install.after_install"
    assert hooks.after_migrate == "rayher_hr_payroll.install.after_install"


def test_project_document_links_are_repaired_after_custom_field_sync():
    source = Path("rayher_hr_payroll/install.py").read_text(encoding="utf-8")
    after_install = source[source.index("def after_install():"):source.index("def backfill_timesheet_detail_project_codes")]

    assert "create_custom_fields(CUSTOM_FIELDS, update=True)" in after_install
    assert "relink_project_documents()" in after_install
    assert after_install.index("create_custom_fields") < after_install.index("relink_project_documents")
    assert after_install.index("ensure_default_projects") < after_install.index("relink_project_documents")
    assert "def relink_project_documents():" in source
    assert "project_initiation_report" in source
    assert "project_completion_report" in source
    assert "capitalization_confirmation_file" in source


def test_timesheet_detail_project_codes_are_backfilled_on_migrate():
    source = Path("rayher_hr_payroll/install.py").read_text(encoding="utf-8")

    assert "backfill_timesheet_detail_project_codes()" in source
    assert "backfill_rd_project_keys()" in source
    assert "tsd.rd_project_code = p.rd_project_code" in source
    assert "tsd.rd_project_key" in source


def test_employee_expense_account_category_exists():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Employee"]}

    field = fields["expense_account_category"]
    assert field["label"] == "费用科目"
    assert field["fieldtype"] == "Select"
    assert field["options"].splitlines() == ["", "研发费用", "管理费用", "销售费用", "生产成本"]
