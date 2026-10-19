from datetime import datetime

from rayher_hr_payroll.importers.personnel_master import (
    normalize_record,
    normalize_text,
    plan_personnel_import,
    summarize_plan,
)


def test_repairs_workbook_mojibake_without_changing_valid_chinese():
    assert normalize_text("ÑÐ·¢²¿") == "研发部"
    assert normalize_text("研发部") == "研发部"
    assert normalize_text("  PLANCK  ") == "PLANCK"


def test_normalize_record_maps_source_types_and_chart_department_aliases():
    record = normalize_record({
        "employee_number": 39.0,
        "employee_name": "演示员工155",
        "gender": "男",
        "date_of_birth": datetime(1980, 1, 2),
        "date_of_joining": "2024-02-03 00:00:00",
        "department": "客服部",
        "bank_ac_no": 621234,
        "default_monthly_salary": 999999,
        "default_social_insurance_base": 888888,
    })

    assert record["employee_number"] == "39"
    assert record["employee_name"] == "演示员工155"
    assert record["gender"] == "Male"
    assert record["date_of_birth"] == "1980-01-02"
    assert record["date_of_joining"] == "2024-02-03"
    # 决定 D5：文件里已经是正式的具体部门时以文件为准，不再按旧花名册改成销售部。
    assert record["department"] == "客服部"
    assert record["bank_ac_no"] == "621234"
    assert "default_monthly_salary" not in record
    assert "default_social_insurance_base" not in record


def test_plan_matches_number_then_unique_name_and_skips_ambiguous_names():
    records = [
        {"employee_number": "3", "employee_name": "演示员工132", "department": "研发部"},
        {"employee_number": "39", "employee_name": "演示员工155", "department": "销售部"},
        {"employee_number": "77", "employee_name": "重名员工"},
        {"employee_number": "78", "employee_name": "新员工", "gender": "Female"},
    ]
    existing = [
        {"name": "EMP-A", "employee_number": "3", "employee_name": "旧姓名"},
        {"name": "EMP-B", "employee_number": "", "employee_name": "演示员工155"},
        {"name": "EMP-C", "employee_number": "", "employee_name": "重名员工"},
        {"name": "EMP-D", "employee_number": "", "employee_name": "重名员工"},
    ]

    result = plan_personnel_import(records, existing)

    assert [(item["action"], item.get("target")) for item in result["items"]] == [
        ("update", "EMP-A"),
        ("update", "EMP-B"),
        ("skip", None),
        ("create", None),
    ]
    assert result["counts"] == {"create": 1, "update": 2, "skip": 1}
    assert result["items"][2]["reason"] == "ambiguous_name"


def test_public_summary_never_exposes_source_personal_data():
    plan = {
        "counts": {"create": 1, "update": 0, "skip": 1},
        "items": [
            {"action": "create", "record": {"employee_name": "演示员工129", "id_card_number_cn": "secret", "bank_ac_no": "secret"}},
            {"action": "skip", "reason": "ambiguous_name", "record": {"employee_name": "演示员工146"}},
        ],
    }
    summary = summarize_plan(plan)

    assert summary == {
        "counts": {"create": 1, "update": 0, "skip": 1},
        "skip_reasons": {"ambiguous_name": 1},
    }
    assert "secret" not in repr(summary)


def test_plan_never_overwrites_a_leaver_or_a_numbered_namesake():
    # 审查 X3-2（决定 D2）：同名演示员工166员工、工号不同的同名在职员工演示员工177能被覆盖。
    records = [
        {"employee_number": "101", "employee_name": "演示员工149"},
        {"employee_number": "102", "employee_name": "演示员工164"},
        {"employee_number": "", "employee_name": "演示员工176"},
    ]
    existing = [
        {"name": "EMP-L", "employee_number": "", "employee_name": "演示员工149", "status": "Left"},
        {"name": "EMP-W", "employee_number": "55", "employee_name": "演示员工164", "status": "Active"},
        {"name": "EMP-Z", "employee_number": "60", "employee_name": "演示员工176", "status": "Active"},
    ]

    result = plan_personnel_import(records, existing)

    assert [(item["action"], item.get("reason"), item.get("target")) for item in result["items"]] == [
        ("skip", "name_matches_left_employee", None),
        ("skip", "employee_number_conflict", None),
        ("update", None, "EMP-Z"),
    ]
