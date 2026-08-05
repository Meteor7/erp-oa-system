from rayher_hr_payroll.department_structure import (
    CANONICAL_DEPARTMENTS,
    DEPARTMENT_GROUPS,
    department_for_employee,
)
from rayher_hr_payroll.importers.personnel_master import normalize_record


def test_org_chart_maps_ai_members_to_ai_department():
    for employee_name in ("演示员工218", "演示员工243", "演示员工247", "演示员工209"):
        assert department_for_employee(employee_name, "", "研发部") == "AI部"


def test_org_chart_maps_research_leaf_teams():
    expected = {
        "演示员工183": "知识产权部",
        "演示员工242": "机械部",
        "演示员工145": "电气部",
        "演示员工215": "工艺部",
        "演示员工107": "光学部",
        "演示员工108": "算法部",
        "演示员工204": "算法部",
        "演示员工132": "软件部",
        "演示员工186": "测试部",
        "演示员工127": "系统工程部",
        "演示员工207": "系统工程部",
        "演示员工237": "系统工程部",
    }

    for employee_name, department in expected.items():
        assert department_for_employee(employee_name, "", "研发部") == department


def test_org_chart_maps_customer_operation_and_function_teams():
    expected = {
        "演示员工158": "应用部",
        "演示员工109": "应用部",
        "演示员工202": "现场服务部",
        "演示员工155": "销售部",
        "演示员工241": "制造部",
        "演示员工245": "仓库部",
        "演示员工216": "采购部",
        "演示员工178": "物控部",
        "演示员工225": "项目申报部",
        "演示员工18": "IT部",
        "演示员工21": "总经办",
    }

    for employee_name, department in expected.items():
        assert department_for_employee(employee_name, "", "") == department


def test_recent_employee_falls_back_to_designation_then_current_canonical_department():
    assert department_for_employee("新光学员工", "光学工程师", "研发部") == "光学部"
    assert department_for_employee("新测试员工", "软件测试工程师", "研发部") == "测试部"
    assert department_for_employee("无法判断员工", "专员", "财务部") == "财务部"
    assert department_for_employee("无法判断员工", "专员", "研发部") == ""


def test_canonical_groups_contain_only_unique_leaf_departments():
    grouped = [department for departments in DEPARTMENT_GROUPS.values() for department in departments]

    assert len(grouped) == len(set(grouped))
    assert set(grouped) == set(CANONICAL_DEPARTMENTS)
    assert {"光学部", "算法部", "软件部", "测试部"} <= set(grouped)


def test_personnel_import_uses_shared_department_mapping():
    record = normalize_record({
        "employee_name": "演示员工107",
        "department": "研发部",
        "designation": "光学工程师",
    })

    assert record["department"] == "光学部"