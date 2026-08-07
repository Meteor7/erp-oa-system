from rayher_hr_payroll.setup_two_companies import TARGET_EMPLOYEES, target_department_name


def test_target_employee_scope_is_exactly_the_six_approved_people():
    assert set(TARGET_EMPLOYEES) == {
        "演示员工201", "演示员工109", "演示员工219", "演示员工226", "演示员工155", "演示员工230",
    }
    assert len(TARGET_EMPLOYEES) == 6


def test_shanghai_department_names_use_company_suffix():
    assert target_department_name("销售部 - RAY") == "销售部 - SHGL"
    assert target_department_name("客户服务部") == "客户服务部 - SHGL"
