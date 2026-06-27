import json
import os

import rayher_hr_payroll

REPORT_JSON = os.path.join(
    os.path.dirname(rayher_hr_payroll.__file__),
    "rayher_hr_payroll", "report", "employee_info_summary", "employee_info_summary.json",
)


def _load():
    with open(REPORT_JSON, encoding="utf-8") as f:
        return json.load(f)


def test_report_is_standard_query_report_on_employee():
    d = _load()
    assert d["report_type"] == "Query Report"
    assert d["is_standard"] == "Yes"
    assert d["ref_doctype"] == "Employee"
    assert d["module"] == "Rayher HR Payroll"


def test_report_is_hr_only_not_finance():
    d = _load()
    roles = {r["role"] for r in d["roles"]}
    assert {"HR User", "HR Manager", "System Manager"} <= roles
    # Finance must NOT see the PII (id card) report:
    assert "Accounts User" not in roles


def test_report_includes_left_employees_pii_and_education():
    q = _load()["query"].lower()
    # No status filter => 离职 (Left) employees are included (需求#5):
    assert "status =" not in q and "status=" not in q
    # PII column + education join present:
    assert "id_card_number_cn" in q
    assert "tabemployee education" in q


def test_report_uses_real_employee_education_columns():
    # Guard against regressions to non-existent columns: HRMS major field is
    # `maj_opt_subj` (not `maj_optional`); school is `school_univ`.
    q = _load()["query"].lower()
    assert "maj_opt_subj" in q
    assert "maj_optional" not in q
    assert "school_univ" in q
