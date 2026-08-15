from datetime import date

import pytest

from rayher_hr_payroll.procurement_workflow import (
    ProcurementWorkflowError,
    derive_prepayment_overdue,
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


def test_project_procurement_requires_delivery_project_and_owner():
    validate_procurement_submission(project_request())
    for field, message in (
        ("expected_delivery_date", "意向交期"),
        ("project", "所属项目"),
        ("project_owner", "项目负责人"),
    ):
        with pytest.raises(ProcurementWorkflowError, match=message):
            validate_procurement_submission(project_request(**{field: ""}))


def test_non_project_procurement_requires_explicit_allocation():
    with pytest.raises(ProcurementWorkflowError, match="非项目归属"):
        validate_procurement_submission(project_request(
            procurement_scope="非项目采购", project="", project_owner="",
        ))
    validate_procurement_submission(project_request(
        procurement_scope="非项目采购", project="", project_owner="",
        non_project_allocation_type="非项目采购",
    ))
    with pytest.raises(ProcurementWorkflowError, match="成本中心"):
        validate_procurement_submission(project_request(
            procurement_scope="非项目采购", project="", project_owner="",
            non_project_allocation_type="成本中心", non_project_cost_center="",
        ))
    with pytest.raises(ProcurementWorkflowError, match="所属部门"):
        validate_procurement_submission(project_request(
            procurement_scope="非项目采购", project="", project_owner="",
            non_project_allocation_type="部门", non_project_department="",
        ))


def test_100_percent_prepayment_requires_arrival_date_risk_note_and_documents():
    request = payment_request(
        prepayment_percentage=100,
        has_balance_payment=0,
        expected_arrival_date="",
        prepayment_risk_note="",
    )
    with pytest.raises(ProcurementWorkflowError, match="预计到货日期"):
        validate_payment_submission(request, evidence={"合同", "付款计划"})
    request["expected_arrival_date"] = "2026-09-20"
    with pytest.raises(ProcurementWorkflowError, match="预付款风险说明"):
        validate_payment_submission(request, evidence={"合同", "付款计划"})
    request["prepayment_risk_note"] = "供应商长期合作，合同约定逾期退款"
    with pytest.raises(ProcurementWorkflowError, match="付款计划"):
        validate_payment_submission(request, evidence={"合同"})
    validate_payment_submission(request, evidence={"合同", "付款计划"})


def test_tail_payment_requires_full_arrival_acceptance_and_evidence():
    request = payment_request(
        payment_stage="尾款",
        arrival_status="部分到货",
        inspection_status="待验收",
    )
    with pytest.raises(ProcurementWorkflowError, match="全部到货"):
        validate_payment_submission(request, evidence={"验收资料"})
    request.update(arrival_status="全部到货", inspection_status="验收通过")
    with pytest.raises(ProcurementWorkflowError, match="验收资料"):
        validate_payment_submission(request, evidence=set())
    validate_payment_submission(request, evidence={"验收资料"})


def test_arrival_transition_enforces_quantity_and_proof():
    request = {
        "business_status": "待到货",
        "ordered_quantity": 10,
        "received_quantity": 0,
    }
    with pytest.raises(ProcurementWorkflowError, match="到货证明"):
        transition_business_state(request, "record_arrival", {"quantity": 4}, evidence=set())
    partial = transition_business_state(
        request, "record_arrival", {"quantity": 4}, evidence={"送货单"}
    )
    assert partial == {
        "business_status": "部分到货",
        "arrival_status": "部分到货",
        "received_quantity": 4,
    }
    with pytest.raises(ProcurementWorkflowError, match="超过"):
        transition_business_state(
            {**request, "received_quantity": 8},
            "record_arrival", {"quantity": 3}, evidence={"入库单"},
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
    ) == {"business_status": "验收通过", "inspection_status": "验收通过"}


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
