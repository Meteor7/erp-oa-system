import pytest

from rayher_hr_payroll.oa_approval import (
    ADMIN_ASSET,
    FINANCE_AUDITOR_USER,
    FINANCE_MANAGER_USER,
    GENERAL_MANAGER_USER,
    IT_APPROVER_USER,
    IT_ASSET,
    OTHER_ASSET,
    VICE_MANAGER_USER,
    ApprovalRouteError,
    build_expense_payment_route,
    build_leave_route,
    normalize_asset_category,
)


def labels(steps):
    return [step["label"] for step in steps]


def modes(steps):
    return [step["mode"] for step in steps]


def test_leave_route_uses_current_vice_and_general_manager_accounts():
    steps = build_leave_route(supervisor="直属上级")

    assert labels(steps) == ["直属上级", "演示员工21", "演示员工29"]
    assert modes(steps) == ["approve", "approve", "approve"]
    assert steps[1]["approvers"] == [VICE_MANAGER_USER]
    assert steps[2]["approvers"] == [GENERAL_MANAGER_USER]


def test_other_department_ordinary_employee_has_full_sequential_route():
    steps = build_expense_payment_route(
        department="研发部 - RAY",
        supervisor="演示员工132",
        supervisor_user="person024@business.example.invalid",
        supervisor_decision="approve",
        asset_category=OTHER_ASSET,
    )

    assert labels(steps) == [
        "财务审核：演示员工13",
        "直属主管：演示员工132",
        "财务主管：演示员工16",
        "副总经理：演示员工21",
        "总经理：演示员工29",
        "确认付款：演示员工13",
    ]
    assert modes(steps) == ["approve", "approve", "approve", "approve", "approve", "handle"]
    assert [step["approvers"] for step in steps] == [
        [FINANCE_AUDITOR_USER],
        ["person024@business.example.invalid"],
        [FINANCE_MANAGER_USER],
        [VICE_MANAGER_USER],
        [GENERAL_MANAGER_USER],
        [FINANCE_AUDITOR_USER],
    ]


def test_manager_under_philippe_skips_stage_two_and_uses_ren_for_non_electronic_asset():
    steps = build_expense_payment_route(
        department="研发部 - RAY",
        supervisor="演示员工21",
        supervisor_user=VICE_MANAGER_USER,
        supervisor_decision="skip",
        asset_category=ADMIN_ASSET,
    )

    assert labels(steps) == [
        "财务审核：演示员工13",
        "固定资产审批：演示员工10",
        "财务主管：演示员工16",
        "副总经理：演示员工21",
        "总经理：演示员工29",
        "确认付款：演示员工13",
    ]
    assert "直属主管：演示员工21" not in labels(steps)
    assert steps[1]["approvers"] == ["person047@legacy.example.invalid"]


def test_customer_service_is_sales_and_uses_electronic_asset_then_executive_cosign():
    steps = build_expense_payment_route(
        department="客户服务部 - RAY",
        supervisor="演示员工21",
        supervisor_user=VICE_MANAGER_USER,
        supervisor_decision="skip",
        asset_category=IT_ASSET,
    )

    assert labels(steps) == [
        "财务审核：演示员工13",
        "固定资产审批：演示员工18",
        "财务主管：演示员工16",
        "副总经理：演示员工21、总经理：演示员工29",
        "确认付款：演示员工13",
    ]
    assert modes(steps) == ["approve", "approve", "approve", "all", "handle"]
    assert steps[1]["approvers"] == [IT_APPROVER_USER]
    assert steps[3]["approvers"] == [VICE_MANAGER_USER, GENERAL_MANAGER_USER]


@pytest.mark.parametrize("department", ["销售部", "客服部 - RAY", "客户服务部 - RAY"])
def test_sales_department_aliases_use_cosign(department):
    steps = build_expense_payment_route(
        department=department,
        supervisor="演示员工21",
        supervisor_user=VICE_MANAGER_USER,
        supervisor_decision="skip",
        asset_category=OTHER_ASSET,
    )

    assert any(step["mode"] == "all" for step in steps)


def test_finance_keeps_supervisor_and_finance_manager_then_only_wang_at_stage_five():
    steps = build_expense_payment_route(
        department="财务部 - RAY",
        supervisor="演示员工16",
        supervisor_user=FINANCE_MANAGER_USER,
        supervisor_decision="approve",
        asset_category=OTHER_ASSET,
    )

    assert labels(steps) == [
        "财务审核：演示员工13",
        "直属主管：演示员工16",
        "财务主管：演示员工16",
        "总经理：演示员工29",
        "确认付款：演示员工13",
    ]
    assert steps[1]["approvers"] == [FINANCE_MANAGER_USER]
    assert steps[2]["approvers"] == [FINANCE_MANAGER_USER]
    assert VICE_MANAGER_USER not in {user for step in steps for user in step["approvers"]}


def test_self_owned_finance_manager_node_is_not_removed():
    steps = build_expense_payment_route(
        department="财务部 - RAY",
        supervisor="演示员工29",
        supervisor_user=GENERAL_MANAGER_USER,
        supervisor_decision="skip",
        asset_category=OTHER_ASSET,
    )

    assert "财务主管：演示员工16" in labels(steps)
    assert next(step for step in steps if step["label"] == "财务主管：演示员工16")["approvers"] == [FINANCE_MANAGER_USER]


def test_legacy_asset_names_normalize_to_the_three_canonical_values():
    assert normalize_asset_category("行政固定资产") == ADMIN_ASSET
    assert normalize_asset_category("IT类固定资产") == IT_ASSET
    assert normalize_asset_category("其它") == OTHER_ASSET


def test_unknown_asset_category_is_rejected():
    with pytest.raises(ApprovalRouteError, match="资产类型"):
        build_expense_payment_route(
            department="研发部",
            supervisor="演示员工132",
            supervisor_user="person024@business.example.invalid",
            supervisor_decision="approve",
            asset_category="随便填写",
        )