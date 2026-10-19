from datetime import date

import pytest

from rayher_hr_payroll.procurement_workflow import (
    ProcurementWorkflowError,
    derive_prepayment_overdue,
    procurement_expense_category,
    transition_business_state,
    validate_payment_submission,
    validate_procurement_submission,
)


def project_request(**overrides):
    value = {
        "procurement_scope": "项目采购",
        "expected_delivery_date": "2026-09-10",
        "project": "RD-001",
        "project_owner": "owner@example.com",
        "business_lines": [{
            "category_code": "1.ELC.3",
            "item_name": "测试物料",
            "specification": "标准规格",
            "product_desc": "测试采购物料",
            "brand": "测试品牌",
            "quantity": 1,
            "unit": "个",
        }],
    }
    value.update(overrides)
    return value


def payment_request(**overrides):
    value = {
        "source_request": "OA-2026-00001",
        "supplier": "SUP-001",
        "payment_stage": "预付款",
        "prepayment_percentage": 30,
        "has_balance_payment": 1,
    }
    value.update(overrides)
    return value


def test_payment_submission_derives_prepayment_without_client_stage():
    request = payment_request(payment_stage="", prepayment_percentage=100)
    request.update(
        expected_arrival_date="2026-09-20",
        prepayment_risk_note="供应商长期合作，演示员工116约定逾期退款",
    )
    assert validate_payment_submission(
        request, evidence={"演示员工116", "付款计划"}
    ) == "预付款"


def test_post_arrival_payment_requires_invoice_and_derives_tail_from_paid_amount():
    request = payment_request(
        payment_stage="",
        prepayment_percentage=0,
        arrival_status="全部到货",
        inspection_status="验收通过",
        source_paid_amount=30,
        source_available_amount=70,
        amount=70,
    )
    with pytest.raises(ProcurementWorkflowError, match="发票"):
        validate_payment_submission(request, evidence={"验收资料"})
    assert validate_payment_submission(
        request, evidence={"验收资料", "发票"}
    ) == "尾款"


def test_post_arrival_first_full_payment_has_unambiguous_stage():
    request = payment_request(
        payment_stage="全额付款",
        prepayment_percentage=0,
        arrival_status="全部到货",
        inspection_status="验收通过",
        source_paid_amount=0,
        source_available_amount=100,
        amount=100,
    )
    assert validate_payment_submission(
        request, evidence={"验收资料", "发票"}
    ) == "到货后全额付款"


def test_project_procurement_requires_delivery_project_and_owner():
    validate_procurement_submission(project_request())
    for field, message in (
        ("expected_delivery_date", "意向交期"),
        ("project", "所属项目"),
        ("project_owner", "项目负责人"),
    ):
        with pytest.raises(ProcurementWorkflowError, match=message):
            validate_procurement_submission(project_request(**{field: ""}))


def test_procurement_submission_requires_material_category_and_details():
    with pytest.raises(ProcurementWorkflowError, match="至少添加一项采购明细"):
        validate_procurement_submission(project_request(business_lines=[]))
    with pytest.raises(ProcurementWorkflowError, match="至少需要填写到三级"):
        validate_procurement_submission(project_request(business_lines=[{
            "category_code": "1.ELC", "item_name": "物料", "specification": "规格",
            "product_desc": "描述", "brand": "品牌", "quantity": 1, "unit": "个",
        }]))
    validate_procurement_submission(project_request(business_lines=[{
        "category_code": "1.ELC.3", "item_name": "物料", "specification": "规格",
        "product_desc": "", "brand": "品牌", "quantity": 1, "unit": "个",
    }]))


def test_procurement_submission_accepts_category_depth_at_or_above_three():
    for category_code in ("1.ELC.3", "1.ELC.3.3", "1.ELC.3.3.03", "1.ELC.3.3.03.001"):
        validate_procurement_submission(project_request(business_lines=[{
            "category_code": category_code, "item_name": "物料", "specification": "规格",
            "product_desc": "", "brand": "品牌", "quantity": 1, "unit": "个",
        }]))


def test_non_project_procurement_must_pick_a_department_that_has_an_expense_category():
    non_project = dict(procurement_scope="非项目采购", project="", project_owner="")
    with pytest.raises(ProcurementWorkflowError, match="所属部门"):
        validate_procurement_submission(project_request(**non_project))
    with pytest.raises(ProcurementWorkflowError, match="所属部门"):      # 原来的"成本中心""非项目采购"选项不再有效
        validate_procurement_submission(project_request(**non_project, non_project_allocation_type="成本中心", non_project_cost_center="CC-1"))
    with pytest.raises(ProcurementWorkflowError, match="所属部门"):
        validate_procurement_submission(project_request(**non_project, non_project_allocation_type="部门", non_project_department=""))
    with pytest.raises(ProcurementWorkflowError, match="费用类别"):      # 不是正式部门（旧的英文部门）取不到费用类别
        validate_procurement_submission(project_request(**non_project, non_project_allocation_type="部门", non_project_department="Accounts - RAY"))
    validate_procurement_submission(project_request(**non_project, non_project_allocation_type="部门", non_project_department="财务部 - RAY"))


def test_procurement_expense_category_follows_project_or_department():
    assert procurement_expense_category("项目采购", "") == "研发费用"
    assert procurement_expense_category("项目采购", "财务部 - RAY") == "研发费用"      # 项目采购不看部门
    assert procurement_expense_category("非项目采购", "研发软件部 - RAY") == "研发费用"
    assert procurement_expense_category("非项目采购", "财务部 - RAY") == "管理费用"
    assert procurement_expense_category("非项目采购", "制造部 - RAY") == "生产成本"
    assert procurement_expense_category("非项目采购", "客服部 - SHGL") == "销售费用"
    assert procurement_expense_category("非项目采购", "") == ""
    assert procurement_expense_category("", "财务部 - RAY") == ""


def test_100_percent_prepayment_requires_arrival_date_risk_note_and_documents():
    request = payment_request(
        prepayment_percentage=100,
        has_balance_payment=0,
        expected_arrival_date="",
        prepayment_risk_note="",
    )
    with pytest.raises(ProcurementWorkflowError, match="预计到货日期"):
        validate_payment_submission(request, evidence={"演示员工116", "付款计划"})
    request["expected_arrival_date"] = "2026-09-20"
    with pytest.raises(ProcurementWorkflowError, match="预付款风险说明"):
        validate_payment_submission(request, evidence={"演示员工116", "付款计划"})
    request["prepayment_risk_note"] = "供应商长期合作，演示员工116约定逾期退款"
    with pytest.raises(ProcurementWorkflowError, match="付款计划"):
        validate_payment_submission(request, evidence={"演示员工116"})
    validate_payment_submission(request, evidence={"演示员工116", "付款计划"})


def test_tail_payment_requires_full_arrival_acceptance_invoice_and_evidence():
    request = payment_request(
        payment_stage="尾款",
        prepayment_percentage=0,
        arrival_status="部分到货",
        inspection_status="待验收",
        source_paid_amount=30,
        source_available_amount=70,
        amount=70,
    )
    with pytest.raises(ProcurementWorkflowError, match="到货验收"):
        validate_payment_submission(request, evidence={"验收资料", "发票"})
    request.update(arrival_status="全部到货", inspection_status="验收通过")
    with pytest.raises(ProcurementWorkflowError, match="验收资料"):
        validate_payment_submission(request, evidence=set())
    with pytest.raises(ProcurementWorkflowError, match="发票"):
        validate_payment_submission(request, evidence={"验收资料"})
    assert validate_payment_submission(request, evidence={"验收资料", "发票"}) == "尾款"


def test_arrival_transition_enforces_quantity_and_proof():
    request = {
        "business_status": "待到货",
        "ordered_quantity": 10,
        "received_quantity": 0,
    }
    with pytest.raises(ProcurementWorkflowError, match="到货证明"):
        transition_business_state(request, "record_arrival", {"quantity": 4}, evidence=set())
    partial = transition_business_state(
        request, "record_arrival", {"quantity": 4, "arrival_date": "2026-08-12"}, evidence={"送货单"}
    )
    assert partial == {
        "business_status": "部分到货",
        "arrival_status": "部分到货",
        "received_quantity": 4,
        "arrival_date": "2026-08-12",
        "inspection_status": "未验收",
    }
    with pytest.raises(ProcurementWorkflowError, match="超过"):
        transition_business_state(
            {**request, "received_quantity": 8},
            "record_arrival", {"quantity": 3, "arrival_date": "2026-08-12"}, evidence={"入库单"},
        )


def test_inspection_cannot_pass_before_arrival_or_without_acceptance_document():
    with pytest.raises(ProcurementWorkflowError, match="到货"):
        transition_business_state(
            {"business_status": "待到货", "arrival_status": "未到货"},
            "pass_inspection", {}, evidence={"验收资料"},
        )
    with pytest.raises(ProcurementWorkflowError, match="验收资料"):
        transition_business_state(
            {"business_status": "待验收", "arrival_status": "全部到货"},
            "pass_inspection", {}, evidence=set(),
        )
    assert transition_business_state(
        {"business_status": "待验收", "arrival_status": "全部到货"},
        "pass_inspection", {}, evidence={"验收资料"},
    ) == {
        "business_status": "验收通过", "inspection_status": "验收通过",
        "inspection_failure_reason": "", "exception_direction": "",
    }


def test_prepayment_overdue_is_derived_without_mutating_workflow_status():
    request = {
        "payment_stage": "预付款",
        "prepayment_percentage": 100,
        "expected_arrival_date": "2026-08-14",
        "arrival_status": "部分到货",
        "workflow_status": "已付款",
    }
    assert derive_prepayment_overdue(request, today=date(2026, 8, 15)) is True
    assert request["workflow_status"] == "已付款"
    assert derive_prepayment_overdue(
        {**request, "arrival_status": "全部到货"}, today=date(2026, 8, 15)
    ) is False
