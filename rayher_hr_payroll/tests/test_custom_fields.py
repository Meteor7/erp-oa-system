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
    assert fields["capitalization_start_date"]["fieldtype"] == "Date"
    assert fields["capitalization_end_date"]["fieldtype"] == "Date"


def test_timesheet_review_fields_exist():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Timesheet"]}

    assert fields["rd_review_status"]["fieldtype"] == "Select"
    assert fields["rd_reviewer"]["options"] == "User"


def test_custom_fieldnames_are_unique_per_doctype():
    for doctype, fields in CUSTOM_FIELDS.items():
        names = [field["fieldname"] for field in fields]
        assert len(names) == len(set(names)), doctype