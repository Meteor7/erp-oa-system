from datetime import date
import importlib
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from rayher_hr_payroll.oa_approval import build_route, REQUEST_PROCUREMENT_PAYMENT
from rayher_hr_payroll.procurement_workflow import (
    ProcurementWorkflowError,
    derive_prepayment_overdue,
    transition_business_state,
)


def payment(**overrides):
    values = {
        "payment_stage": "预付款",
        "prepayment_percentage": 100,
        "has_balance_payment": 0,
        "business_status": "待到货",
        "arrival_status": "未到货",
        "inspection_status": "未验收",
        "prepayment_writeoff_status": "待核销",
        "ordered_quantity": 10,
        "received_quantity": 0,
        "expected_arrival_date": "2026-08-10",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def evidence(*document_types):
    return [{"name": f"DOC-{index}", "document_type": value} for index, value in enumerate(document_types, 1)]


def role(key, label, user, name):
    return {"role_key": key, "role_label": label, "user": user, "employee_name": name}


def test_every_procurement_payment_stage_uses_finance_li_wang_then_finance_handle():
    roles = {
        "finance_auditor": role("finance_auditor", "财务审核", "finance@example.com", "演示员工13"),
        "vice_manager": role("vice_manager", "副总经理", "li@example.com", "演示员工21"),
        "general_manager": role("general_manager", "总经理", "wang@example.com", "演示员工29"),
    }
    for stage in ("预付款", "到货款", "尾款", "全额付款"):
        steps = build_route(REQUEST_PROCUREMENT_PAYMENT, roles=roles)
        assert [row["label"] for row in steps] == [
            "财务审核：演示员工13", "演示员工21", "演示员工29", "财务确认付款：演示员工13"
        ], stage


def test_arrival_requires_date_and_proof_and_tracks_partial_then_full_quantity():
    doc = payment()
    with pytest.raises(ProcurementWorkflowError, match="到货日期"):
        transition_business_state(doc, "record_arrival", {"quantity": 4}, evidence("送货单"))
    with pytest.raises(ProcurementWorkflowError, match="到货证明"):
        transition_business_state(doc, "record_arrival", {"quantity": 4, "arrival_date": "2026-08-12"}, [])

    partial = transition_business_state(doc, "record_arrival", {"quantity": 4, "arrival_date": "2026-08-12"}, evidence("送货单"))
    assert partial == {
        "business_status": "部分到货", "arrival_status": "部分到货",
        "received_quantity": 4, "arrival_date": "2026-08-12",
        "inspection_status": "未验收",
    }
    doc.business_status = partial["business_status"]
    doc.arrival_status = partial["arrival_status"]
    doc.received_quantity = partial["received_quantity"]
    full = transition_business_state(doc, "record_arrival", {"quantity": 6, "arrival_date": "2026-08-13"}, evidence("入库单"))
    assert full["arrival_status"] == "全部到货"
    assert full["business_status"] == "待验收"
    assert full["received_quantity"] == 10
    with pytest.raises(ProcurementWorkflowError, match="超过"):
        transition_business_state(doc, "record_arrival", {"quantity": 7, "arrival_date": "2026-08-13"}, evidence("入库单"))


def test_inspection_pass_needs_acceptance_evidence_and_failure_needs_reason_direction():
    doc = payment(business_status="待验收", arrival_status="全部到货", received_quantity=10)
    with pytest.raises(ProcurementWorkflowError, match="验收资料"):
        transition_business_state(doc, "pass_inspection", evidence=[])
    assert transition_business_state(doc, "pass_inspection", evidence=evidence("验收资料")) == {
        "business_status": "验收通过", "inspection_status": "验收通过",
        "inspection_failure_reason": "", "exception_direction": "",
    }
    with pytest.raises(ProcurementWorkflowError, match="原因"):
        transition_business_state(doc, "fail_inspection", {"direction": "退货"}, evidence("验收资料"))
    with pytest.raises(ProcurementWorkflowError, match="退货或换货"):
        transition_business_state(doc, "fail_inspection", {"reason": "尺寸不符", "direction": "返修"}, evidence("验收资料"))
    failed = transition_business_state(doc, "fail_inspection", {"reason": "尺寸不符", "direction": "换货"}, evidence("验收资料"))
    assert failed["business_status"] == "换货中"
    assert failed["inspection_status"] == "验收不合格"


def test_prepayment_overdue_followup_writeoff_and_no_tail_close_rules():
    doc = payment()
    assert derive_prepayment_overdue(doc, today=date(2026, 8, 15)) is True
    followup = transition_business_state(doc, "record_followup", {"status": "催办中", "reason": "已联系供应商"})
    assert followup == {"business_status": "催办中", "followup_status": "催办中"}

    doc.business_status = "验收通过"
    doc.arrival_status = "全部到货"
    doc.inspection_status = "验收通过"
    with pytest.raises(ProcurementWorkflowError, match="发票"):
        transition_business_state(doc, "writeoff_prepayment", evidence=evidence("验收资料"))
    writeoff = transition_business_state(doc, "writeoff_prepayment", evidence=evidence("发票", "验收资料"))
    assert writeoff == {"business_status": "已核销", "prepayment_writeoff_status": "已核销"}

    doc.business_status = "已核销"
    doc.prepayment_writeoff_status = "已核销"
    with pytest.raises(ProcurementWorkflowError, match="采购完成报告"):
        transition_business_state(doc, "close_procurement", evidence=evidence("发票", "验收资料"))
    closed = transition_business_state(doc, "close_procurement", evidence=evidence("发票", "验收资料", "采购完成报告"))
    assert closed == {"business_status": "已关闭"}

    with pytest.raises(ProcurementWorkflowError, match="尾款"):
        transition_business_state(payment(has_balance_payment=1, business_status="已核销", arrival_status="全部到货", inspection_status="验收通过", prepayment_writeoff_status="已核销"), "close_procurement", evidence=evidence("发票", "验收资料", "采购完成报告"))

class Request(SimpleNamespace):
    doctype = "OA Approval Request"


def lifecycle_request(**overrides):
    values = vars(payment()).copy()
    values.update({
        "name": "PAY-LIFECYCLE-1", "owner": "buyer@example.com",
        "request_type": "采购付款", "workflow_status": "已付款",
        "operation_log": "[]", "paid_by": "finance@example.com",
    })
    values.update(overrides)
    return Request(**values)


@pytest.fixture
def oa_entry():
    return importlib.import_module("rayher_hr_payroll.api.oa_entry")


def install_lifecycle(monkeypatch, oa_entry, doc, evidence_rows):
    oa_entry.frappe.local.flags = SimpleNamespace(in_test=True)
    oa_entry.frappe.local.session = SimpleNamespace(user="buyer@example.com")
    monkeypatch.setattr(oa_entry, "require_request_type_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(oa_entry, "now_datetime", lambda: "2026-08-15 12:00:00")
    monkeypatch.setattr(oa_entry.invoice_service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_load_request", lambda *_args, **_kwargs: doc)
    monkeypatch.setattr(oa_entry, "_require_procurement_lifecycle_access", lambda current: None, raising=False)
    monkeypatch.setattr(oa_entry, "_active_request_business_documents", lambda name: list(evidence_rows), raising=False)
    monkeypatch.setattr(oa_entry, "_save_document", lambda current: current)
    monkeypatch.setattr(oa_entry, "_sync_assignments_after_save", lambda current: current)
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda current, authorized_expense_lines=None: {
        "business_status": current.business_status,
        "arrival_status": current.arrival_status,
        "inspection_status": current.inspection_status,
        "prepayment_writeoff_status": current.prepayment_writeoff_status,
        "received_quantity": current.received_quantity,
    })


def test_lifecycle_endpoints_apply_evidence_backed_changes_and_audit_names(monkeypatch, oa_entry):
    doc = lifecycle_request()
    docs = [{"name": "OABD-DELIVERY", "document_type": "送货单", "supersedes": ""}]
    install_lifecycle(monkeypatch, oa_entry, doc, docs)
    result = oa_entry.record_arrival(doc.name, 4, "2026-08-12")
    assert result["arrival_status"] == "部分到货"
    event = json.loads(doc.operation_log)[-1]
    assert event["action"] == "登记到货"
    assert event["details"]["evidence_names"] == ["OABD-DELIVERY"]

    doc.business_status = "待验收"
    doc.arrival_status = "全部到货"
    doc.received_quantity = 10
    docs[:] = [{"name": "OABD-ACCEPT", "document_type": "验收资料", "supersedes": ""}]
    result = oa_entry.record_inspection(doc.name, "不合格", reason="尺寸不符", direction="换货")
    assert result["business_status"] == "换货中"
    assert doc.inspection_failure_reason == "尺寸不符"
    assert doc.exception_direction == "换货"


def test_writeoff_and_close_endpoints_require_active_evidence(monkeypatch, oa_entry):
    doc = lifecycle_request(
        business_status="验收通过", arrival_status="全部到货", inspection_status="验收通过",
        received_quantity=10, prepayment_writeoff_status="待核销",
    )
    docs = [
        {"name": "OABD-INVOICE", "document_type": "发票", "supersedes": ""},
        {"name": "OABD-ACCEPT", "document_type": "验收资料", "supersedes": ""},
    ]
    install_lifecycle(monkeypatch, oa_entry, doc, docs)
    result = oa_entry.writeoff_prepayment(doc.name, "发票已核对")
    assert result["prepayment_writeoff_status"] == "已核销"
    docs.append({"name": "OABD-REPORT", "document_type": "采购完成报告", "supersedes": ""})
    result = oa_entry.close_procurement(doc.name, "无尾款关闭")
    assert result["business_status"] == "已关闭"


def test_active_business_documents_exclude_superseded_versions(monkeypatch, oa_entry):
    rows = [
        {"name": "OLD", "document_type": "送货单", "supersedes": ""},
        {"name": "NEW", "document_type": "送货单", "supersedes": "OLD"},
        {"name": "INVOICE", "document_type": "发票", "supersedes": ""},
    ]
    monkeypatch.setattr(oa_entry.frappe, "get_all", lambda *_args, **_kwargs: rows, raising=False)
    active = oa_entry._active_request_business_documents("PAY-1")
    assert [row["name"] for row in active] == ["NEW", "INVOICE"]

def test_procurement_payment_ledger_helpers_use_revisioned_keys(monkeypatch, oa_entry):
    doc = lifecycle_request(
        workflow_status="待审批", source_request="PROC-SOURCE-1", operation_log=json.dumps([{"action": "提交申请"}]),
    )
    calls = []
    monkeypatch.setattr(oa_entry.approval_amount_ledger, "reserve", lambda source, payment, key, note="": calls.append(("reserve", source, payment, key)))
    monkeypatch.setattr(oa_entry.approval_amount_ledger, "release_all_reserved", lambda source, payment, key, note="": calls.append(("release", source, payment, key)))
    monkeypatch.setattr(oa_entry.approval_amount_ledger, "mark_paid", lambda source, payment, key, note="": calls.append(("pay", source, payment, key)))

    oa_entry._reserve_procurement_payment(doc)
    oa_entry._release_procurement_payment_reservation(doc, "驳回重填")
    oa_entry._mark_procurement_payment_paid(doc)

    assert calls == [
        ("reserve", "PROC-SOURCE-1", doc.name, "submit:PAY-LIFECYCLE-1:1"),
        ("release", "PROC-SOURCE-1", doc.name, "release:PAY-LIFECYCLE-1:1"),
        ("pay", "PROC-SOURCE-1", doc.name, "pay:PAY-LIFECYCLE-1"),
    ]


def test_payment_completion_initializes_arrival_and_writeoff_state(oa_entry):
    doc = lifecycle_request(payment_stage="预付款", prepayment_percentage=100, business_status="待审批")
    oa_entry._set_procurement_payment_paid_state(doc)
    assert doc.business_status == "待到货"
    assert doc.arrival_status == "未到货"
    assert doc.inspection_status == "未验收"
    assert doc.prepayment_writeoff_status == "待核销"


def test_completed_procurement_approval_sets_payable_approved_amount():
    from types import SimpleNamespace
    from decimal import Decimal
    from rayher_hr_payroll.api import oa_entry

    step = SimpleNamespace(step_index=1)
    doc = SimpleNamespace(
        steps=[step],
        request_type=oa_entry.REQUEST_PROCUREMENT,
        workflow_status=oa_entry.STATUS_PENDING,
        business_status="待审批",
        current_step_index=1,
        current_step_label="PMC",
        amount=Decimal("123.45"),
        approved_amount=None,
    )

    oa_entry._advance_after_step(doc, step)

    assert doc.workflow_status == oa_entry.STATUS_COMPLETED
    assert doc.business_status == "合同待登记"
    assert doc.approved_amount == Decimal("123.45")
