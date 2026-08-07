import json

from rayher_hr_payroll.household_registration_backfill import (
    build_backfill_plan,
    load_expected,
)


def test_expected_values_come_from_the_private_data_file(tmp_path):
    path = tmp_path / "household_registration_backfill.json"
    path.write_text(json.dumps({" 员工甲 ": "深户", "员工乙": "非深农村", "员工丙": ""}, ensure_ascii=False), encoding="utf-8")

    assert load_expected(path) == {"员工甲": "深户", "员工乙": "非深农村"}


def test_missing_data_file_means_nothing_to_backfill(tmp_path):
    assert load_expected(tmp_path / "absent.json") == {}
    assert build_backfill_plan([{"name": "E1", "employee_name": "员工甲"}], {}) == {
        "updates": [],
        "unchanged": [],
        "conflicts": [],
    }


def test_plan_only_fills_empty_values_and_is_idempotent():
    rows = [
        {"name": "E1", "employee_name": "员工甲", "household_registration": ""},
        {"name": "E2", "employee_name": "员工乙", "household_registration": "非深农村"},
    ]
    expected = {"员工甲": "深户", "员工乙": "非深农村"}

    plan = build_backfill_plan(rows, expected)

    assert plan["updates"] == [
        {"employee": "E1", "employee_name": "员工甲", "household_registration": "深户"}
    ]
    assert plan["unchanged"] == [
        {"employee": "E2", "employee_name": "员工乙", "household_registration": "非深农村"}
    ]
    assert plan["conflicts"] == []


def test_plan_fails_closed_instead_of_overwriting_a_different_value():
    rows = [
        {"name": "E1", "employee_name": "员工甲", "household_registration": "非深农村"}
    ]

    plan = build_backfill_plan(rows, {"员工甲": "深户"})

    assert plan["updates"] == []
    assert plan["conflicts"][0]["type"] == "unexpected_existing_value"
    assert plan["conflicts"][0]["current"] == "非深农村"
