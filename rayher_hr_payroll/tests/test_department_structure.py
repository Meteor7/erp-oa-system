from rayher_hr_payroll.department_sync import plan_department_updates


def test_department_update_plan_uses_org_chart_and_reports_unresolved_without_deleting():
    plan = plan_department_updates([
        {"name": "EMP-1", "employee_name": "演示员工107", "designation": "光学工程师", "department_name": "研发部", "company": "Rayher"},
        {"name": "EMP-2", "employee_name": "演示员工132", "designation": "软件组长", "department_name": "软件部", "company": "Rayher"},
        {"name": "EMP-3", "employee_name": "新员工", "designation": "专员", "department_name": "研发部", "company": "Rayher"},
    ])

    assert plan["changes"] == [{
        "name": "EMP-1",
        "employee_name": "演示员工107",
        "company": "Rayher",
        "from_department": "研发部",
        "to_department": "研发光学部",
    }, {"name":"EMP-2","employee_name":"演示员工132","company":"Rayher","from_department":"软件部","to_department":"研发软件部"}]
    assert plan["unchanged"] == ["EMP-3"]
    assert plan["unresolved"] == []
    assert "deletions" not in plan