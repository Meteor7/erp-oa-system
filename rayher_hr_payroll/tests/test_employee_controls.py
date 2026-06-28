"""Unit tests for employee archive completeness (pure helpers, no DB)."""
from rayher_hr_payroll.employee_controls import _archive_problems, _negative_mock_fields


def _complete(**over):
    d = {
        "archive_status": "已归档",
        "id_card_number_cn": "110101199001010031",
        "date_of_joining": "2026-01-01",
        "rd_mock_base": 20000,
        "department": "研发部 - R",
    }
    d.update(over)
    return d


def test_archive_complete_has_no_problems():
    assert _archive_problems(_complete()) == []


def test_archive_missing_department_flagged():
    assert "部门必填" in _archive_problems(_complete(department=""))
    assert "部门必填" in _archive_problems(_complete(department="   "))


def test_archive_missing_id_flagged():
    assert "身份证号需≥15位" in _archive_problems(_complete(id_card_number_cn="123"))


def test_archive_missing_joining_flagged():
    probs = _archive_problems(_complete(date_of_joining=None))
    assert "入职日期必填" in probs


def test_archive_does_not_require_salary():
    # Real payroll (Salary Slip) is the salary source now; archive must not be
    # blocked on the legacy rd_mock_base field.
    assert _archive_problems(_complete(rd_mock_base=0)) == []


def test_non_archived_has_no_problems():
    assert _archive_problems({"archive_status": "待完善"}) == []


def test_negative_mock_fields_detected():
    assert _negative_mock_fields({"rd_mock_base": -1}) == ["应发工资"]
    assert _negative_mock_fields({"rd_mock_base": 1, "rd_mock_tax": -5}) == ["个税"]
    assert _negative_mock_fields({"rd_mock_base": 1}) == []
