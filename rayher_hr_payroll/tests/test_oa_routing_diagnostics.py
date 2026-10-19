from rayher_hr_payroll.maintenance.oa_routing_diagnostics import (
    REQUIRED_APPROVERS,
    build_diagnostics,
)


USERS = {
    "演示员工132": "person024@business.example.invalid",
    "演示员工21": "person046@staff.example.invalid",
    "演示员工29": "person060@staff.example.invalid",
}


def resolve_user(name):
    return USERS.get(name)


def account_state(user_id):
    names = {value: key for key, value in USERS.items()}
    return {
        "exists": user_id in names,
        "enabled": user_id in names,
        "employee_name": names.get(user_id, ""),
    }


def test_diagnostics_reports_routes_and_missing_mapping_without_mutation():
    employees = [
        {"name": "EMP-1", "employee_name": "演示员工150", "department": "研发部 - RAY"},
        {"name": "EMP-X", "employee_name": "未配置员工", "department": "研发部 - RAY"},
    ]
    original = [dict(row) for row in employees]

    report = build_diagnostics(employees, resolve_user, account_state, required_approvers={})

    assert employees == original
    assert report["employees"][0]["decision"] == "approve"
    assert report["employees"][0]["supervisor_name"] == "演示员工132"
    assert report["employees"][0]["user_id"] == "person024@business.example.invalid"
    assert report["errors"] == [
        {"type": "missing_mapping", "employee": "EMP-X", "employee_name": "未配置员工", "message": "员工 未配置员工 未配置部门主管"}
    ]


def test_accountless_excluded_manager_resolves_upward_without_error():
    report = build_diagnostics(
        [{"name": "EMP-BU", "employee_name": "南通工厂7", "department": "研发部 - RAY"}],
        resolve_user,
        account_state,
        required_approvers={},
    )

    assert report["errors"] == []
    assert report["employees"][0]["decision"] == "skip"
    assert report["employees"][0]["traversed"] == ["演示员工21"]


def test_required_account_diagnostics_find_missing_or_disabled_links():
    required = {
        "演示员工13": "person067@staff.example.invalid",
        "演示员工29": "person060@staff.example.invalid",
    }

    report = build_diagnostics([], resolve_user, account_state, required_approvers=required)

    assert report["accounts"][0]["name"] == "演示员工13"
    assert report["accounts"][0]["ready"] is False
    assert report["accounts"][1]["ready"] is True
    assert report["errors"][0]["type"] == "required_account_not_ready"


def test_static_required_approvers_only_contains_non_role_it_owner():
    assert REQUIRED_APPROVERS == {"演示员工18": "person068@staff.example.invalid"}


import pytest

@pytest.fixture(autouse=True)
def organization_fixture(monkeypatch):
    import rayher_hr_payroll.oa_organization as org
    monkeypatch.setattr(org, "current_supervisors", lambda: org.DIRECT_SUPERVISOR_BY_EMPLOYEE)
    monkeypatch.setattr(org, "executive_names", lambda: {"演示员工21", "演示员工29"})
