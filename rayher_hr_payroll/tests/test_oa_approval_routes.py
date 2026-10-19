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
        "出纳审核",
        "直属主管：演示员工132",
        "财务主管：演示员工16",
        "副总经理：演示员工21",
        "总经理：演示员工29",
        "出纳确认付款",
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
        "出纳审核",
        "固定资产审批：人事经理",
        "财务主管：演示员工16",
        "副总经理：演示员工21",
        "总经理：演示员工29",
        "出纳确认付款",
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
        "出纳审核",
        "IT负责人：演示员工18",
        "财务主管：演示员工16",
        "副总经理：演示员工21、总经理：演示员工29",
        "出纳确认付款",
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


def test_finance_merges_same_supervisor_and_finance_manager_then_uses_wang():
    steps = build_expense_payment_route(
        department="财务部 - RAY",
        supervisor="演示员工16",
        supervisor_user=FINANCE_MANAGER_USER,
        supervisor_decision="approve",
        asset_category=OTHER_ASSET,
    )

    assert labels(steps) == [
        "出纳审核",
        "直属主管：演示员工16",
        "总经理：演示员工29",
        "出纳确认付款",
    ]
    assert steps[1]["approvers"] == [FINANCE_MANAGER_USER]
    assert sum(FINANCE_MANAGER_USER in step["approvers"] for step in steps) == 1
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
        "finance_auditor": role("finance_auditor", "出纳", "finance@example.com", "演示员工32"),
        "finance_accountant": role("finance_accountant", "总账会计", "accountant@example.com", "演示员工19"),
        "finance_manager": role("finance_manager", "财务主管", "manager@example.com", "演示员工16"),
        "vice_manager": role("vice_manager", "副总经理", "vice@example.com", "演示员工21"),
        "general_manager": role("general_manager", "总经理", "general@example.com", "演示员工29"),
        "production_asset_owner": role(
            "production_asset_owner", "生产设备负责人", "production@example.com", "演示员工241"
        ),
        "procurement_manager": role(
            "procurement_manager", "采购经办人", "buyer@example.com", "演示员工216"
        ),
    }


def test_procurement_route_excludes_production_owner_for_production_asset():
    steps = build_procurement_route(
        supervisor="直属领导",
        supervisor_user="boss@example.com",
        project_owner="owner@example.com",
        project_owner_name="项目主管",
        asset_category=PRODUCTION_ASSET,
        roles=procurement_roles(),
    )
    assert labels(steps) == [
        "直属主管：直属领导、项目主管：项目主管（会签）",
        "PMC：演示员工178", "需求终审：副总经理：演示员工21",
    ]
    assert [step["approvers"] for step in steps] == [
        ["boss@example.com", "owner@example.com"],
        ["pmc@example.com"], ["vice@example.com"],
    ]
    assert modes(steps) == ["all", "approve", "approve"]


def test_one_person_who_is_both_direct_supervisor_and_project_owner_gets_one_node_that_names_both_roles():
    # 演示员工132这种既是直属主管又是项目主管的人：只批一次，节点标签里两个身份都写上（审批记录里看得出）。
    steps = build_procurement_route(
        supervisor="演示员工132",
        supervisor_user="junzhang@example.com",
        project_owner="junzhang@example.com",
        project_owner_name="演示员工132",
        asset_category=OTHER_ASSET,
        applicant_user="applicant@example.com",
        roles=procurement_roles(),
    )
    assert labels(steps) == ["直属主管、项目主管：演示员工132", "PMC：演示员工178", "需求终审：副总经理：演示员工21"]
    assert [step["approvers"] for step in steps] == [["junzhang@example.com"], ["pmc@example.com"], ["vice@example.com"]]
    assert modes(steps) == ["approve", "approve", "approve"]


def test_two_different_people_keep_the_cosign_labels_unchanged():
    steps = build_procurement_route(
        supervisor="直属领导", supervisor_user="boss@example.com", project_owner="owner@example.com", project_owner_name="项目主管",
        asset_category=OTHER_ASSET, roles=procurement_roles(),
    )
    assert labels(steps)[0] == "直属主管：直属领导、项目主管：项目主管（会签）"
    assert modes(steps)[0] == "all"


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
    assert labels(steps) == [
        "PMC：演示员工178", "需求终审：副总经理：演示员工21",
    ]


def test_procurement_route_keeps_pmc_when_pmc_is_the_applicant():
    roles = procurement_roles()
    steps = build_procurement_route(
        supervisor="演示员工21",
        supervisor_user="vice@example.com",
        supervisor_decision="skip",
        applicant_user="pmc@example.com",
        project_owner="",
        asset_category=OTHER_ASSET,
        roles=roles,
    )
    assert labels(steps) == [
        "PMC：演示员工178", "需求终审：副总经理：演示员工21",
    ]
    assert steps[0]["approvers"] == ["pmc@example.com"]


def test_other_purchase_routes_once_when_direct_supervisor_is_top_executive():
    steps = build_direct_purchase_route(
        purchase_method="其他购买",
        supervisor="演示员工21",
        supervisor_user="vice@example.com",
        supervisor_decision="skip",
        applicant_user="employee@example.com",
        roles=procurement_roles(),
    )
    assert labels(steps) == ["副总经理：演示员工21"]
    assert steps[0]["approvers"] == ["vice@example.com"]


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
    assert labels(steps) == [
        "直属主管、项目主管：主管", "需求终审：副总经理：演示员工21",
    ]


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
        upper_supervisor="演示员工29",
        upper_supervisor_user="general@example.com",
        roles=roles,
    )
    assert labels(jd) == ["京东购买会签：人事经理、演示员工21"]
    assert [step["approvers"] for step in jd] == [["hr@example.com", "vice@example.com"]]
    assert modes(jd) == ["all"]
    assert labels(other) == ["直属部门主管：主管", "副总经理：演示员工21"]
    assert [step["approvers"] for step in other] == [
        ["boss@example.com"], ["vice@example.com"]
    ]


def test_other_purchase_rejects_executive_self_submission():
    with pytest.raises(ApprovalRouteError, match="公司高管本人"):
        build_direct_purchase_route(
            purchase_method="其他购买",
            supervisor="演示员工29",
            supervisor_user="general@example.com",
            supervisor_decision="skip",
            applicant_user="vice@example.com",
            roles=procurement_roles(),
        )


def test_procurement_payment_is_stage_specific_but_expense_payment_keeps_department_branching():
    roles = procurement_roles()
    prepayment = build_procurement_payment_route(payment_stage="预付款", roles=roles)
    assert labels(prepayment) == ["演示员工21", "总账会计：演示员工19", "财务主管：演示员工16", "出纳：演示员工32", "总经理付款：演示员工29"]
    assert [step["approvers"] for step in prepayment] == [
        ["vice@example.com"], ["accountant@example.com"], ["manager@example.com"], ["finance@example.com"], ["general@example.com"]
    ]
    assert modes(prepayment) == ["approve", "approve", "approve", "approve", "handle"]

    tail = build_procurement_payment_route(payment_stage="尾款", roles=roles)
    assert labels(tail) == ["演示员工21", "总账会计：演示员工19", "财务主管：演示员工16", "出纳：演示员工32", "总经理付款：演示员工29"]
    assert [step["approvers"] for step in tail] == [
        ["vice@example.com"], ["accountant@example.com"], ["manager@example.com"], ["finance@example.com"], ["general@example.com"]
    ]
    assert modes(tail) == ["approve", "approve", "approve", "approve", "handle"]

    buying_payment = build_expense_payment_route(
        department="销售部 - RAY",
        supervisor="演示员工21",
        supervisor_user=VICE_MANAGER_USER,
        supervisor_decision="skip",
        asset_category=OTHER_ASSET,
    )
    assert any(step["mode"] == "all" for step in buying_payment)

@pytest.fixture(autouse=True)
def current_position_fixture(monkeypatch):
    from rayher_hr_payroll import oa_approval as module
    values = {
        "hr_manager": ("人事经理", "演示员工10", module.ADMIN_APPROVER_USER),
        "finance_auditor": ("出纳", "演示员工32", module.FINANCE_AUDITOR_USER),
        "finance_accountant": ("总账会计", "演示员工19", module.FINANCE_ACCOUNTANT_USER),
        "finance_manager": ("财务主管", "演示员工16", module.FINANCE_MANAGER_USER),
        "vice_manager": ("副总经理", "演示员工21", module.VICE_MANAGER_USER),
        "general_manager": ("总经理", "演示员工29", module.GENERAL_MANAGER_USER),
        "pmc": ("PMC", "演示员工178", module.PMC_APPROVER_USER),
        "procurement_manager": ("采购经办人", "演示员工216", module.PROCUREMENT_MANAGER_USER),
        "production_asset_owner": ("生产设备负责人", "演示员工241", module.PRODUCTION_APPROVER_USER),
        "it_asset_owner": ("IT负责人", "演示员工18", module.IT_APPROVER_USER),
    }
    def resolve(key):
        label, name, user = values[key]
        return {"role_key": key, "role_label": label, "employee_name": name, "user": user}
    monkeypatch.setattr(module, "resolve_role", resolve)



def test_procurement_route_refuses_a_supervisor_without_an_account(monkeypatch):
    # 审查 X3-12：主管没有账号时原来直接去掉主管节点。
    import pytest
    from rayher_hr_payroll import oa_approval

    monkeypatch.setattr(oa_approval, "resolve_role", lambda key: {"role_key": key, "role_label": key, "employee_name": key, "user": key + "@example.com"})
    with pytest.raises(oa_approval.ApprovalRouteError, match="没有关联可用账号"):
        oa_approval.build_procurement_route(supervisor="张主管", supervisor_user="", supervisor_decision="approve", applicant_user="a@example.com")


def test_short_leave_span_counts_calendar_days_including_both_ends():
    from rayher_hr_payroll.oa_approval import is_short_leave, leave_span_days

    assert leave_span_days("2026-10-09", "2026-10-11") == 3
    assert leave_span_days("2026-10-09", "2026-10-09") == 1
    assert leave_span_days("2026-10-09", "2026-10-12") == 4          # 周五到周一：只有 2 个工作日，但是 4 个日历日
    assert leave_span_days("2026-10-12", "2026-10-09") is None
    assert leave_span_days("", "2026-10-09") is None
    assert is_short_leave("2026-10-09", "2026-10-11") is True
    assert is_short_leave("2026-10-09", "2026-10-12") is False
    assert is_short_leave(None, None) is False


def test_leave_of_three_calendar_days_or_less_stops_at_the_hr_manager():
    common = dict(department="研发部 - RAY", supervisor="演示员工132", supervisor_user="person024@staff.example.invalid",
                  applicant_user="employee@staff.example.invalid")
    assert labels(build_leave_route(**common, span_days=3)) == ["直属主管：演示员工132", "人事经理"]
    assert labels(build_leave_route(**common, span_days=1)) == ["直属主管：演示员工132", "人事经理"]
    assert labels(build_leave_route(**common, span_days=4)) == ["直属主管：演示员工132", "人事经理", "演示员工21"]
    assert labels(build_leave_route(**common)) == ["直属主管：演示员工132", "人事经理", "演示员工21"], "no dates = the full route"
    finance = dict(common, department="财务部 - RAY", supervisor="演示员工16", supervisor_user="person072@staff.example.invalid")
    assert labels(build_leave_route(**finance, span_days=2)) == ["直属主管：演示员工16", "人事经理"]
    assert labels(build_leave_route(**finance, span_days=5)) == ["直属主管：演示员工16", "人事经理", "演示员工29"]


def test_only_leave_uses_the_short_route_overtime_and_comp_time_keep_theirs():
    from rayher_hr_payroll.oa_approval import build_route
    from rayher_hr_payroll.oa_document_types import REQUEST_LEAVE

    kw = dict(department="研发部 - RAY", supervisor="演示员工132", supervisor_user="person024@staff.example.invalid",
              applicant_user="employee@staff.example.invalid", from_date="2026-10-09", to_date="2026-10-10")
    assert labels(build_route(REQUEST_LEAVE, **kw)) == ["直属主管：演示员工132", "人事经理"]
    assert labels(build_route("加班申请", **kw)) == ["直属主管：演示员工132", "人事经理", "演示员工21"]
    assert labels(build_route("调休申请", **kw)) == ["直属主管：演示员工132", "人事经理", "演示员工21"]
    assert labels(build_route(REQUEST_LEAVE, **{**kw, "to_date": "2026-10-13"})) == ["直属主管：演示员工132", "人事经理", "演示员工21"]


def test_a_short_leave_is_not_copied_to_the_vice_manager_any_more():
    assert leave_copy_recipients(short=True) == [{"label": "人事经理", "user": LEAVE_ADMIN_APPROVER_USER}]
    assert leave_copy_recipients(LEAVE_ADMIN_APPROVER_USER, short=True) == []


def test_the_hr_manager_own_short_leave_still_has_an_approver():
    """人事经理自己请 3 天以内的假：直属上级是高管被跳过、人事经理是他自己，路线会变空——由总经理（演示员工28）审批，不能提交不了。"""
    steps = build_leave_route(department="人事行政部 - RAY", supervisor="演示员工29", supervisor_user=LEAVE_FINANCE_APPROVER_USER,
                              supervisor_decision="skip", applicant_user=LEAVE_ADMIN_APPROVER_USER, span_days=2)
    assert labels(steps) == ["演示员工29"]
    long_steps = build_leave_route(department="人事行政部 - RAY", supervisor="演示员工29", supervisor_user=LEAVE_FINANCE_APPROVER_USER,
                                   supervisor_decision="skip", applicant_user=LEAVE_ADMIN_APPROVER_USER, span_days=4)
    assert labels(long_steps) == ["演示员工21"]
