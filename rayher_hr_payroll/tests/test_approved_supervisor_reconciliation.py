from rayher_hr_payroll.approved_supervisor_reconciliation import (
    build_reconciliation_plan,
)


def _rows(current_for_lijiaqi="QING"):
    return [
        {"name": "QING", "employee_name": "演示员工21", "status": "Active", "reports_to": ""},
        {"name": "CAI", "employee_name": "演示员工172", "status": "Active", "reports_to": "QING"},
        {"name": "GAO", "employee_name": "演示员工183", "status": "Active", "reports_to": "QING"},
        {"name": "LI", "employee_name": "演示员工145", "status": "Active", "reports_to": current_for_lijiaqi},
        {"name": "WANG", "employee_name": "演示员工159", "status": "Active", "reports_to": "QING"},
        {"name": "HUANG", "employee_name": "演示员工187", "status": "Active", "reports_to": "QING"},
    ]


def test_plan_updates_only_the_three_approved_old_values():
    plan = build_reconciliation_plan(_rows())

    assert plan["conflicts"] == []
    assert {(row["employee"], row["reports_to"]) for row in plan["updates"]} == {
        ("LI", "CAI"),
        ("WANG", "CAI"),
        ("HUANG", "GAO"),
    }


def test_plan_is_idempotent_after_corrections():
    rows = _rows("CAI")
    for row in rows:
        if row["name"] == "WANG":
            row["reports_to"] = "CAI"
        if row["name"] == "HUANG":
            row["reports_to"] = "GAO"

    plan = build_reconciliation_plan(rows)

    assert plan["updates"] == []
    assert len(plan["unchanged"]) == 3
    assert plan["conflicts"] == []


def test_plan_fails_closed_on_an_unexpected_existing_supervisor():
    plan = build_reconciliation_plan(_rows("SOMEONE-ELSE"))

    assert plan["updates"] == [
        {
            "employee": "WANG",
            "employee_name": "演示员工159",
            "approved_old": "QING",
            "reports_to": "CAI",
        },
        {
            "employee": "HUANG",
            "employee_name": "演示员工187",
            "approved_old": "QING",
            "reports_to": "GAO",
        },
    ]
    assert plan["conflicts"][0]["type"] == "unexpected_current_supervisor"
    assert plan["conflicts"][0]["employee_name"] == "演示员工145"
