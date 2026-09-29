from rayher_hr_payroll.department_structure import (
    CANONICAL_DEPARTMENTS,
    DEPARTMENT_GROUPS,
    department_for_employee,
)
from rayher_hr_payroll.importers.personnel_master import normalize_record


def test_org_chart_maps_ai_members_to_rd_ai_department():
    for employee_name in ("演示员工218", "演示员工243", "演示员工247", "演示员工209"):
        assert department_for_employee(employee_name, "", "研发部") == "研发AI部"


def test_org_chart_maps_research_leaf_teams():
    expected = {
        "演示员工183": "知识产权部",
        "演示员工242": "研发机械部",
        "演示员工145": "研发电气部",
        "演示员工215": "研发部",
        "演示员工107": "研发光学部",
        "演示员工108": "研发算法部",
        "演示员工204": "研发算法部",
        "演示员工132": "研发软件部",
        "演示员工186": "研发软件部",
        "演示员工127": "研发系统部",
        "演示员工207": "研发系统部",
        "演示员工237": "研发系统部",
        "演示员工203": "研发系统部",
    }

    for employee_name, department in expected.items():
        assert department_for_employee(employee_name, "", "研发部") == department


def test_org_chart_keeps_customer_service_job_titles_in_customer_service_department():
    expected = {
        "演示员工158": "客服部",
        "演示员工109": "客服部",
        "演示员工202": "客服部",
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
    assert department_for_employee("新光学员工", "光学工程师", "研发部") == "研发光学部"
    assert department_for_employee("新测试员工", "软件测试工程师", "研发部") == "研发软件部"
    assert department_for_employee("新现场员工", "FSE工程师", "客服部") == "客服部"
    assert department_for_employee("无法判断员工", "专员", "财务部") == "财务部"
    assert department_for_employee("无法判断员工", "专员", "研发部") == "研发部"


def test_canonical_groups_contain_only_unique_leaf_departments():
    grouped = [department for departments in DEPARTMENT_GROUPS.values() for department in departments]

    assert len(grouped) == len(set(grouped))
    assert set(grouped) == set(CANONICAL_DEPARTMENTS)
    assert {"研发光学部", "研发算法部", "研发软件部", "研发系统部", "研发AI部"} <= set(grouped)
    assert not {"测试部", "工艺部", "现场服务部", "应用部"} & set(grouped)


def test_personnel_import_uses_shared_department_mapping():
    record = normalize_record({
        "employee_name": "演示员工107",
        "department": "研发部",
        "designation": "光学工程师",
    })

    assert record["department"] == "研发光学部"



def test_a_current_specific_department_is_kept_over_the_old_roster():
    # 模块 7（决定 D5）：人事把演示员工132调到研发系统部后，导入和部门同步不能按旧花名册改回研发软件部。
    assert department_for_employee("演示员工132", "软件组长", "研发系统部") == "研发系统部"
    assert department_for_employee("演示员工132", "软件组长", "软件部") == "研发软件部"
    assert department_for_employee("演示员工132", "软件组长", "研发部") == "研发软件部"


def test_the_hard_coded_organization_sync_is_gone():
    from rayher_hr_payroll import organization_master_data

    assert not hasattr(organization_master_data, "sync_organization_master_data")
    assert hasattr(organization_master_data, "sync_effective_leaver_statuses")
