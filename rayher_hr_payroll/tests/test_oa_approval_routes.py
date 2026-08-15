import pytest

from rayher_hr_payroll.oa_approval import (
    ADMIN_ASSET,
    FINANCE_AUDITOR_USER,
    FINANCE_MANAGER_USER,
    GENERAL_MANAGER_USER,
    IT_APPROVER_USER,
    IT_ASSET,
    LEAVE_ADMIN_APPROVER_USER,
    LEAVE_FINANCE_APPROVER_USER,
    LEAVE_OTHER_APPROVER_USER,
    OTHER_ASSET,
    PRODUCTION_ASSET,
    VICE_MANAGER_USER,
    ApprovalRouteError,
    build_direct_purchase_route,
    build_expense_payment_route,
    build_procurement_payment_route,
    build_procurement_route,
    build_leave_route,
    leave_copy_recipients,
    normalize_asset_category,
)


def labels(steps):
    return [step["label"] for step in steps]


def modes(steps):
    return [step["mode"] for step in steps]


def test_leave_route_for_other_department_uses_supervisor_ren_and_qingbo():
    steps = build_leave_route(
        department="研发部 - RAY",
        supervisor="演示员工132",
        supervisor_user="person024@staff.example.invalid",
        applicant_user="employee@staff.example.invalid",
    )

    assert labels(steps) == ["直属主管：演示员工132", "人事经理", "演示员工21"]
    assert modes(steps) == ["approve", "approve", "approve"]
    assert [step["approvers"] for step in steps] == [
        ["person024@staff.example.invalid"],
        [LEAVE_ADMIN_APPROVER_USER],
        [LEAVE_OTHER_APPROVER_USER],
    ]


def test_leave_route_for_finance_uses_wangbo_at_level_three():
    steps = build_leave_route(
        department="财务部 - RAY",
        supervisor="演示员工16",
        supervisor_user="person072@staff.example.invalid",
        applicant_user="finance@staff.example.invalid",
    )

    assert labels(steps) == ["直属主管：演示员工16", "人事经理", "演示员工29"]
    assert steps[2]["approvers"] == [LEAVE_FINANCE_APPROVER_USER]


def test_leave_route_skips_self_and_duplicate_fixed_approvers():
    ren_steps = build_leave_route(
        department="研发部 - RAY",
        supervisor="演示员工132",
        supervisor_user="person024@staff.example.invalid",
        applicant_user=LEAVE_ADMIN_APPROVER_USER,
    )
    qing_steps = build_leave_route(
        department="研发部 - RAY",
        supervisor="演示员工10",
        supervisor_user=LEAVE_ADMIN_APPROVER_USER,
        applicant_user="employee@staff.example.invalid",
    )

    assert labels(ren_steps) == ["直属主管：演示员工132", "演示员工21"]
    assert labels(qing_steps) == ["直属主管：演示员工10", "演示员工21"]


def test_leave_route_skips_level_one_for_top_executives_without_self_approval():
    qingbo_steps = build_leave_route(
        department="总经办 - RAY",
        supervisor="演示员工21",
        supervisor_user=LEAVE_OTHER_APPROVER_USER,
        supervisor_decision="skip",
        applicant_user=LEAVE_OTHER_APPROVER_USER,
    )
    wangbo_steps = build_leave_route(
        department="总经办 - RAY",
        supervisor="演示员工29",
        supervisor_user=LEAVE_FINANCE_APPROVER_USER,
        supervisor_decision="skip",
        applicant_user=LEAVE_FINANCE_APPROVER_USER,
    )

    assert labels(qingbo_steps) == ["人事经理"]
    assert labels(wangbo_steps) == ["人事经理", "演示员工21"]
    assert all(
        LEAVE_OTHER_APPROVER_USER not in step["approvers"]
        for step in qingbo_steps
    )
    assert all(
        LEAVE_FINANCE_APPROVER_USER not in step["approvers"]
        for step in wangbo_steps
    )



def test_leave_route_rejects_missing_or_self_supervisor_accounts():
    with pytest.raises(ApprovalRouteError, match="没有关联可用账号"):
        build_leave_route(
            department="研发部 - RAY", supervisor="演示员工132", supervisor_user=""
        )
    with pytest.raises(ApprovalRouteError, match="不能成为自己的直属上级"):
        build_leave_route(
            department="研发部 - RAY",
            supervisor="申请人",
            supervisor_user="employee@staff.example.invalid",
            applicant_user="employee@staff.example.invalid",
        )


def test_leave_copy_recipients_exclude_the_applicant_without_changing_approval():
    assert leave_copy_recipients() == [
        {"label": "人事经理", "user": LEAVE_ADMIN_APPROVER_USER},
        {"label": "演示员工21", "user": LEAVE_OTHER_APPROVER_USER},
    ]
    assert leave_copy_recipients(LEAVE_ADMIN_APPROVER_USER) == [
        {"label": "演示员工21", "user": LEAVE_OTHER_APPROVER_USER}
    ]


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
        "固定资产审批：人事经理",
        "财务主管：演示员工16",
        "副总经理：演示员工21",
        "总经理：演示员工29",
        "确认付款：演示员工13",
    ]
    assert "直属主管：演示员工21" not in labels(steps)
    assert steps[1]["approvers"] == ["person047@staff.example.invalid"]


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


def role(role_key, label, user, name):
    return {
        "role_key": role_key,
        "role_label": label,
        "user": user,
        "employee": "EMP-" + role_key,
        "employee_name": name,
    }


def procurement_roles():
    return {
        "pmc": role("pmc", "PMC", "pmc@example.com", "演示员工178"),
        "hr_manager": role("hr_manager", "人事经理", "hr@example.com", "演示员工10"),
        "finance_auditor": role("finance_auditor", "财务审核", "finance@example.com", "演示员工13"),
        "finance_manager": role("finance_manager", "财务主管", "manager@example.com", "演示员工16"),
        "vice_manager": role("vice_manager", "副总经理", "vice@example.com", "演示员工21"),
        "general_manager": role("general_manager", "总经理", "general@example.com", "演示员工29"),
        "production_asset_owner": role(
            "production_asset_owner", "生产设备负责人", "production@example.com", "演示员工241"
        ),
    }


def test_procurement_route_is_pmc_supervisor_project_owner_and_production_owner():
    steps = build_procurement_route(
        supervisor="直属领导",
        supervisor_user="boss@example.com",
        project_owner="owner@example.com",
        project_owner_name="项目主管",
        asset_category=PRODUCTION_ASSET,
        roles=procurement_roles(),
    )
    assert labels(steps) == ["PMC：演示员工178", "直属主管：直属领导", "项目主管：项目主管", "生产设备负责人：演示员工241"]
    assert [step["approvers"] for step in steps] == [
        ["pmc@example.com"], ["boss@example.com"], ["owner@example.com"], ["production@example.com"]
    ]


def test_procurement_route_skips_top_supervisor_and_omits_project_for_non_project():
    steps = build_procurement_route(
        supervisor="演示员工21",
        supervisor_user="vice@example.com",
        supervisor_decision="skip",
        project_owner="",
        project_owner_name="",
        asset_category=OTHER_ASSET,
        roles=procurement_roles(),
    )
    assert labels(steps) == ["PMC：演示员工178"]


def test_procurement_route_deduplicates_same_supervisor_and_project_owner():
    roles = procurement_roles()
    roles["pmc"]["user"] = "same@example.com"
    steps = build_procurement_route(
        supervisor="主管",
        supervisor_user="same@example.com",
        project_owner="same@example.com",
        project_owner_name="项目主管",
        asset_category=OTHER_ASSET,
        roles=roles,
    )
    assert labels(steps) == ["PMC：演示员工178"]


def test_direct_purchase_jd_and_other_routes_are_distinct():
    roles = procurement_roles()
    jd = build_direct_purchase_route(
        purchase_method="京东购买",
        supervisor="主管",
        supervisor_user="boss@example.com",
        roles=roles,
    )
    other = build_direct_purchase_route(
        purchase_method="其他购买",
        supervisor="主管",
        supervisor_user="boss@example.com",
        roles=roles,
    )
    assert labels(jd) == ["人事经理", "演示员工21"]
    assert [step["approvers"] for step in jd] == [["hr@example.com"], ["vice@example.com"]]
    assert labels(other) == ["直属主管：主管"]


def test_procurement_payment_is_fixed_but_expense_payment_keeps_department_branching():
    roles = procurement_roles()
    procurement = build_procurement_payment_route(roles=roles)
    assert labels(procurement) == ["财务审核：演示员工13", "演示员工21", "演示员工29", "财务确认付款：演示员工13"]
    assert [step["approvers"] for step in procurement] == [
        ["finance@example.com"], ["vice@example.com"], ["general@example.com"], ["finance@example.com"]
    ]
    assert modes(procurement) == ["approve", "approve", "approve", "handle"]

    buying_payment = build_expense_payment_route(
        department="销售部 - RAY",
        supervisor="演示员工21",
        supervisor_user=VICE_MANAGER_USER,
        supervisor_decision="skip",
        asset_category=OTHER_ASSET,
    )
    assert any(step["mode"] == "all" for step in buying_payment)
