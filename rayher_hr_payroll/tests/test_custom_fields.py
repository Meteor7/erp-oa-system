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
    assert fields["project_owner"]["fieldtype"] == "Link"
    assert fields["project_owner"]["options"] == "User"
    assert fields["capitalization_start_date"]["fieldtype"] == "Date"
    assert fields["capitalization_end_date"]["fieldtype"] == "Date"
    assert fields["rd_project_key"]["fieldtype"] == "Data"
    assert fields["rd_project_key"]["label"] == "\u9879\u76ee\u6807\u8bc6"
    assert fields["rd_project_key"]["read_only"] == 1


def test_timesheet_review_fields_exist():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Timesheet"]}

    assert fields["rd_review_status"]["fieldtype"] == "Select"
    assert fields["rd_reviewer"]["options"] == "User"


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


def test_timesheet_detail_project_codes_are_backfilled_on_migrate():
    source = Path("rayher_hr_payroll/install.py").read_text(encoding="utf-8")

    assert "backfill_timesheet_detail_project_codes()" in source
    assert "backfill_rd_project_keys()" in source
    assert "tsd.rd_project_code = p.rd_project_code" in source
    assert "tsd.rd_project_key" in source
