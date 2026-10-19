import pytest

from rayher_hr_payroll.oa_organization import (
    DIRECT_SUPERVISOR_BY_EMPLOYEE,
    OrganizationResolutionError,
    direct_supervisor_name,
    resolve_stage_two_supervisor,
    resolve_top_executive,
)


USERS = {
    "演示员工132": "person024@business.example.invalid",
    "演示员工108": "person062@business.example.invalid",
    "演示员工218": "person075@staff.example.invalid",
    "演示员工16": "person072@staff.example.invalid",
    "演示员工21": "person046@staff.example.invalid",
    "演示员工29": "person060@staff.example.invalid",
}


def resolve_user(name):
    return USERS.get(name)


def test_software_employee_resolves_to_jun_zhang():
    result = resolve_stage_two_supervisor("演示员工150", resolve_user)
    assert result.decision == "approve"
    assert result.supervisor_name == "演示员工132"
    assert result.user_id == "person024@business.example.invalid"
    assert result.traversed == ("演示员工132",)


def test_manager_reporting_directly_to_top_executive_skips_duplicate_stage():
    for employee_name in ("演示员工132", "南通工厂7", "演示员工30", "演示员工243"):
        result = resolve_stage_two_supervisor(employee_name, resolve_user)
        assert result.decision == "skip"
        assert result.supervisor_name == "演示员工21"
        assert result.traversed == ("演示员工21",)


def test_peer_names_do_not_become_a_vertical_chain():
    assert direct_supervisor_name("演示员工117") == "演示员工132"
    assert direct_supervisor_name("演示员工112") == "演示员工132"


def test_finance_member_resolves_to_zhang_meng():
    result = resolve_stage_two_supervisor("演示员工13", resolve_user)
    assert result.decision == "approve"
    assert result.supervisor_name == "演示员工16"
    assert result.user_id == "person072@staff.example.invalid"


def test_algorithm_member_resolves_to_xi_he():
    result = resolve_stage_two_supervisor("演示员工206", resolve_user)
    assert result.decision == "approve"
    assert result.supervisor_name == "演示员工108"
    assert result.user_id == "person062@business.example.invalid"


def test_ai_team_members_follow_the_excel_reporting_lines():
    for employee_name in ("演示员工247", "演示员工209"):
        result = resolve_stage_two_supervisor(employee_name, resolve_user)
        assert result.decision == "approve"
        assert result.supervisor_name == "演示员工218"
        assert result.traversed == ("演示员工218",)
    assert direct_supervisor_name("演示员工243") == "演示员工21"


def test_accountless_nonexecutive_supervisor_moves_to_parent():
    result = resolve_stage_two_supervisor("演示员工109", resolve_user)
    assert result.decision == "skip"
    assert result.supervisor_name == "演示员工21"
    assert result.traversed == ("演示员工155", "演示员工21")


def test_top_executive_applicant_skips_stage_two():
    result = resolve_stage_two_supervisor("演示员工29", resolve_user)
    assert result.decision == "skip"
    assert result.supervisor_name == "演示员工29"
    assert result.traversed == ()


def test_every_current_excel_employee_has_a_server_mapping_except_top_executives():
    current_names = {
        "演示员工29", "演示员工21", "演示员工132", "演示员工242", "演示员工150", "演示员工117", "演示员工172", "演示员工107",
        "演示员工183", "演示员工235", "演示员工38", "演示员工231", "演示员工186", "演示员工212", "演示员工142", "演示员工234",
        "演示员工228", "演示员工112", "演示员工245", "演示员工108", "演示员工18", "演示员工208", "演示员工238", "演示员工246",
        "演示员工248", "演示员工187", "演示员工159", "演示员工134", "演示员工16", "演示员工205", "演示员工244", "演示员工240",
        "南通工厂7", "演示员工233", "演示员工145", "演示员工206", "演示员工158", "演示员工184", "演示员工207", "演示员工239",
        "演示员工30", "演示员工221", "演示员工161", "演示员工218", "演示员工227", "演示员工202", "演示员工220", "演示员工241",
        "演示员工225", "演示员工224", "演示员工236", "演示员工217", "演示员工210", "演示员工19", "演示员工214", "演示员工211",
        "演示员工243", "演示员工232", "演示员工178", "演示员工229", "演示员工216", "演示员工213", "演示员工209", "演示员工32",
        "演示员工237", "演示员工203", "演示员工155", "演示员工230", "演示员工109", "演示员工201", "演示员工219", "演示员工226",
    }
    assert current_names - {"演示员工29", "演示员工21"} <= set(DIRECT_SUPERVISOR_BY_EMPLOYEE)


def test_other_purchase_executive_resolves_through_excel_chain():
    software = resolve_top_executive("演示员工150", resolve_user)
    finance = resolve_top_executive("演示员工13", resolve_user)
    assert software.executive_name == "演示员工21"
    assert software.traversed == ("演示员工132", "演示员工21")
    assert finance.executive_name == "演示员工29"
    assert finance.traversed == ("演示员工16", "演示员工29")


def test_unknown_employee_fails_closed():
    with pytest.raises(OrganizationResolutionError, match="未配置"):
        resolve_stage_two_supervisor("不存在的人", resolve_user)


def test_recent_excel_employee_routes_are_server_mapped():
    expected = {
        "演示员工155": "演示员工21", "演示员工201": "演示员工155", "演示员工109": "演示员工155",
        "演示员工219": "演示员工155", "演示员工226": "演示员工155", "演示员工230": "演示员工155",
        "演示员工213": "演示员工155", "演示员工237": "演示员工21", "演示员工32": "演示员工16",
        "演示员工203": "演示员工21",
    }
    for employee_name, supervisor_name in expected.items():
        assert DIRECT_SUPERVISOR_BY_EMPLOYEE[employee_name] == supervisor_name

@pytest.fixture(autouse=True)
def organization_fixture(monkeypatch):
    from rayher_hr_payroll import oa_organization as module
    monkeypatch.setattr(module, "current_supervisors", lambda: dict(module.DIRECT_SUPERVISOR_BY_EMPLOYEE))
    monkeypatch.setattr(module, "executive_names", lambda: set(module.TOP_EXECUTIVES))
