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


class PaymentLine(SimpleNamespace):
    def as_dict(self):
        return vars(self).copy()


def payment_po(**overrides):
    values = {
        "name": "PO-TEST-1", "status": "供应商制作中", "contract_status": "已生效",
        "currency": "CNY", "supplier": "示例企业028", "source_price_approvals": "PA-1",
        "lines": [PaymentLine(name="LINE-1", material_serial="MAT-1", item_name="控制器",
                              quantity=10, received_quantity=0, inspection_status="未验收")],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def payment_plan_row(**overrides):
    values = {
        "name": "PLAN-1", "installment_no": 1, "installment_name": "第1期",
        "payment_stage": "到货款", "planned_date": "2026-09-10", "trigger_condition": "全部到货",
        "invoice_requirement": "付款前提供", "percentage": 30, "amount": 3000,
        "paid_amount": 0, "status": "待审批", "payment_request": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_payment_work_item_is_visible_before_conditions_are_met(monkeypatch):
    from rayher_hr_payroll.api import procurement_chain

    monkeypatch.setattr(procurement_chain, "_can_record_receipt", lambda: True)
    monkeypatch.setattr(procurement_chain, "_can_purchase", lambda: False)
    monkeypatch.setattr(procurement_chain, "_fulfillment_records", lambda _name: [])
    item = procurement_chain._payment_work_item(
        payment_po(), payment_plan_row(trigger_condition="验收通过")
    )

    assert item["work_status"] == "待到货资料"
    assert item["blockers"] == ["验收前需全部到货", "本期要求验收通过"]
    assert item["can_record_receipt"] == 1
    assert item["can_push_payment"] == 0
    assert item["lines"][0]["material_serial"] == "MAT-1"


def test_payment_work_item_becomes_actionable_after_receipt_and_inspection(monkeypatch):
    from rayher_hr_payroll.api import procurement_chain

    line = PaymentLine(name="LINE-1", material_serial="MAT-1", item_name="控制器",
                       quantity=10, received_quantity=10, inspection_status="已通过")
    monkeypatch.setattr(procurement_chain, "_can_record_receipt", lambda: False)
    monkeypatch.setattr(procurement_chain, "_can_purchase", lambda: True)
    monkeypatch.setattr(procurement_chain, "_fulfillment_records", lambda _name: [
        {"record_type": "到货"}, {"record_type": "验收"},
    ])
    item = procurement_chain._payment_work_item(
        payment_po(lines=[line]), payment_plan_row(trigger_condition="验收通过")
    )

    assert item["work_status"] == "可提交付款审批"
    assert item["blockers"] == []
    assert item["can_push_payment"] == 1


def test_supplier_payment_plan_requires_full_percentage_and_amount(monkeypatch):
    from rayher_hr_payroll.api import procurement_chain

    monkeypatch.setattr(procurement_chain.frappe, "throw", lambda message: (_ for _ in ()).throw(ValueError(message)))
    valid = procurement_chain._normalize_supplier_payment_plan([{
        "installment_name": "预付款", "payment_stage": "预付款", "percentage": 30,
        "amount": 300, "trigger_condition": "合同生效", "invoice_requirement": "付款后提供",
    }, {
        "installment_name": "尾款", "payment_stage": "尾款", "percentage": 70,
        "amount": 700, "trigger_condition": "验收通过", "invoice_requirement": "付款前提供",
    }], 1000)
    assert [row["amount"] for row in valid] == [300.0, 700.0]
    with pytest.raises(ValueError, match="100%"):
        procurement_chain._normalize_supplier_payment_plan([{
            "payment_stage": "预付款", "percentage": 30, "amount": 1000,
            "trigger_condition": "合同生效", "invoice_requirement": "付款后提供",
        }], 1000)


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


def test_procurement_payment_routes_pre_and_post_arrival_payments_differ():
    roles = {
        "finance_auditor": role("finance_auditor", "出纳", "finance@example.com", "演示员工32"),
        "finance_accountant": role("finance_accountant", "总账会计", "accountant@example.com", "演示员工19"),
        "finance_manager": role("finance_manager", "财务主管", "manager@example.com", "演示员工16"),
        "vice_manager": role("vice_manager", "副总经理", "li@example.com", "演示员工21"),
        "general_manager": role("general_manager", "总经理", "wang@example.com", "演示员工29"),
    }

    prepayment = build_route(
        REQUEST_PROCUREMENT_PAYMENT, payment_stage="预付款", roles=roles
    )
    expected_labels = [
        "演示员工21", "总账会计：演示员工19", "财务主管：演示员工16", "出纳：演示员工32", "总经理付款：演示员工29"
    ]
    assert [row["label"] for row in prepayment] == expected_labels
    assert [row["approvers"] for row in prepayment] == [
        ["li@example.com"], ["accountant@example.com"], ["manager@example.com"], ["finance@example.com"], ["wang@example.com"]
    ]
    assert [row["mode"] for row in prepayment] == [
        "approve", "approve", "approve", "approve", "handle"
    ]

    for stage in ("到货款", "尾款", "到货后全额付款"):
        post_arrival = build_route(
            REQUEST_PROCUREMENT_PAYMENT, payment_stage=stage, roles=roles
        )
        assert [row["label"] for row in post_arrival] == expected_labels, stage
        assert [row["approvers"] for row in post_arrival] == [
            ["li@example.com"], ["accountant@example.com"], ["manager@example.com"], ["finance@example.com"], ["wang@example.com"]
        ], stage
        assert [row["mode"] for row in post_arrival] == [
            "approve", "approve", "approve", "approve", "handle"
        ]


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


def test_replacement_can_arrive_again_and_be_reinspected():
    doc = payment(
        business_status="待验收",
        arrival_status="全部到货",
        received_quantity=10,
    )
    failed = transition_business_state(
        doc,
        "fail_inspection",
        {"reason": "尺寸不符", "direction": "换货"},
        evidence("验收资料"),
    )
    assert failed["business_status"] == "换货中"
    assert failed["arrival_status"] == "换货中"
    assert failed["received_quantity"] == 0

    for key, value in failed.items():
        setattr(doc, key, value)
    replacement = transition_business_state(
        doc,
        "record_arrival",
        {"quantity": 10, "arrival_date": "2026-08-16"},
        evidence("送货单"),
    )
    assert replacement["business_status"] == "待验收"
    assert replacement["arrival_status"] == "全部到货"
    assert replacement["inspection_status"] == "未验收"
    assert replacement["followup_status"] == ""


def test_supplier_refund_completion_requires_refund_receipt():
    doc = payment(
        business_status="供应商退款中",
        arrival_status="退货中",
        received_quantity=10,
    )
    with pytest.raises(ProcurementWorkflowError, match="退款回单"):
        transition_business_state(doc, "complete_supplier_refund", evidence=[])
    result = transition_business_state(
        doc,
        "complete_supplier_refund",
        evidence=evidence("退款回单"),
    )
    assert result == {
        "business_status": "已退款",
        "arrival_status": "关闭未交数量",
        "followup_status": "供应商退款完成",
        "prepayment_writeoff_status": "无需核销",
    }


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

    doc.business_status = "已关闭"
    with pytest.raises(ProcurementWorkflowError, match="已经关闭"):
        transition_business_state(doc, "close_procurement", evidence=evidence("发票", "验收资料", "采购完成报告"))

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
    monkeypatch.setattr(oa_entry, "_require_procurement_lifecycle_access", lambda current, action=None: None, raising=False)
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


def test_completed_procurement_source_can_record_arrival_before_first_payment(monkeypatch, oa_entry):
    source_doc = lifecycle_request(
        name="PROC-NO-PREPAY-1",
        request_type="采购申请",
        workflow_status="已完成",
        business_status="采购执行中",
        payment_stage="",
        prepayment_percentage=0,
    )
    source_doc.purchaser_user = "buyer@example.com"
    docs = [{"name": "OABD-DELIVERY", "document_type": "送货单", "supersedes": ""}]
    install_lifecycle(monkeypatch, oa_entry, source_doc, docs)
    access_calls = []
    monkeypatch.setattr(
        oa_entry,
        "_require_procurement_lifecycle_access",
        lambda current, action: access_calls.append((current.request_type, action)),
    )

    result = oa_entry.record_arrival(source_doc.name, 10, "2026-08-12")

    assert access_calls == [("采购申请", "record_arrival")]
    assert result["arrival_status"] == "全部到货"
    assert result["business_status"] == "待验收"


def test_procurement_source_lifecycle_access_is_limited_to_arrival_and_inspection(monkeypatch, oa_entry):
    source_doc = lifecycle_request(
        request_type="采购申请",
        workflow_status="已完成",
        business_status="采购执行中",
    )
    source_doc.purchaser_user = "buyer@example.com"
    oa_entry.frappe.local.session = SimpleNamespace(user="buyer@example.com")
    monkeypatch.setattr(oa_entry.frappe, "get_roles", lambda *_args, **_kwargs: ["Purchase User"])
    monkeypatch.setattr(oa_entry.frappe, "_", lambda message: message)
    monkeypatch.setattr(oa_entry.frappe, "throw", lambda message: (_ for _ in ()).throw(Exception(message)))

    oa_entry._require_procurement_lifecycle_access(source_doc, "record_arrival")
    oa_entry._require_procurement_lifecycle_access(source_doc, "pass_inspection")
    with pytest.raises(Exception, match="只能在采购付款单"):
        oa_entry._require_procurement_lifecycle_access(source_doc, "writeoff_prepayment")


def test_arrival_endpoint_synchronizes_fulfillment_to_source_request(monkeypatch, oa_entry):
    payment_doc = lifecycle_request(source_request="PROC-SOURCE-1")
    source_doc = Request(
        name="PROC-SOURCE-1", request_type="采购申请", workflow_status="已完成",
        arrival_status="未到货", received_quantity=0, arrival_date=None,
        inspection_status="未验收", inspection_failure_reason="",
        exception_direction="", followup_status="", prepayment_writeoff_status="无需核销",
    )
    docs = [{"name": "OABD-DELIVERY", "document_type": "送货单", "supersedes": ""}]
    install_lifecycle(monkeypatch, oa_entry, payment_doc, docs)
    monkeypatch.setattr(
        oa_entry.frappe,
        "get_doc",
        lambda doctype, name: source_doc if (doctype, name) == ("OA Approval Request", "PROC-SOURCE-1") else None,
        raising=False,
    )

    oa_entry.record_arrival(payment_doc.name, 4, "2026-08-12")

    assert source_doc.business_status == "部分到货"
    assert source_doc.received_quantity == 4
    assert source_doc.arrival_status == "部分到货"
    assert source_doc.arrival_date == "2026-08-12"
    assert source_doc.inspection_status == "未验收"


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


def test_supplier_refund_endpoint_posts_ledger_and_closes_refund_state(monkeypatch, oa_entry):
    doc = lifecycle_request(
        business_status="供应商退款中",
        arrival_status="退货中",
        source_request="PROC-SOURCE-1",
    )
    docs = [{"name": "OABD-REFUND", "document_type": "退款回单", "supersedes": ""}]
    install_lifecycle(monkeypatch, oa_entry, doc, docs)
    monkeypatch.setattr(
        oa_entry.approval_amount_ledger,
        "linked_payment_balance",
        lambda _name: {"paid_amount": 100},
    )
    refunds = []
    monkeypatch.setattr(
        oa_entry.approval_amount_ledger,
        "refund",
        lambda source, payment, amount, key, note="": refunds.append(
            (source, payment, amount, key, note)
        ),
    )

    # 决定（2026-09-24）：只有财务可以确认供应商退款
    monkeypatch.setattr(oa_entry, "_is_finance_user", lambda user=None: False)
    monkeypatch.setattr(oa_entry.frappe, "_", lambda text, *args, **kwargs: text, raising=False)

    def refuse(message, *args, **kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr(oa_entry.frappe, "throw", refuse, raising=False)
    with pytest.raises(Exception, match="只有财务可以确认供应商退款"):
        oa_entry.complete_supplier_refund(doc.name, "退款到账")
    assert refunds == []
    monkeypatch.setattr(oa_entry, "_is_finance_user", lambda user=None: True)

    result = oa_entry.complete_supplier_refund(doc.name, "退款到账")

    assert result["business_status"] == "已退款"
    assert result["arrival_status"] == "关闭未交数量"
    assert refunds == [
        ("PROC-SOURCE-1", doc.name, 100, f"refund:{doc.name}:complete", "退款到账")
    ]
    assert json.loads(doc.operation_log)[-1]["action"] == "确认供应商退款"


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


def test_po_payment_ledger_helpers_use_po_plan_without_oa_amount_ledger(monkeypatch, oa_entry):
    doc = lifecycle_request(
        workflow_status="待审批",
        source_request="PROC-ZERO-AMOUNT",
        source_purchase_order="PO-1",
        source_po_payment_plan_row="PLAN-1",
    )
    statuses = []
    monkeypatch.setattr(oa_entry, "_sync_payment_plan_row", lambda current, status: statuses.append(status))
    monkeypatch.setattr(oa_entry.approval_amount_ledger, "reserve", lambda *_args, **_kwargs: pytest.fail("PO payment must not reserve OA amount"))
    monkeypatch.setattr(oa_entry.approval_amount_ledger, "release_all_reserved", lambda *_args, **_kwargs: pytest.fail("PO payment must not release OA amount"))
    monkeypatch.setattr(oa_entry.approval_amount_ledger, "mark_paid", lambda *_args, **_kwargs: pytest.fail("PO payment must not pay OA amount"))

    oa_entry._reserve_procurement_payment(doc)
    oa_entry._release_procurement_payment_reservation(doc, "驳回重填")
    oa_entry._mark_procurement_payment_paid(doc)

    assert statuses == ["已下推", "待下推", "已付款"]

def test_payment_completion_initializes_arrival_and_writeoff_state(oa_entry):
    doc = lifecycle_request(payment_stage="预付款", prepayment_percentage=100, business_status="待审批")
    oa_entry._set_procurement_payment_paid_state(doc)
    assert doc.business_status == "待到货"
    assert doc.arrival_status == "未到货"
    assert doc.inspection_status == "未验收"
    assert doc.prepayment_writeoff_status == "待核销"


def test_completed_procurement_price_approval_moves_to_execution():
    from types import SimpleNamespace
    from decimal import Decimal
    from rayher_hr_payroll.api import oa_entry

    step = SimpleNamespace(step_index=1, label="价格审批：副总经理：演示员工21")
    doc = SimpleNamespace(
        steps=[step],
        request_type=oa_entry.REQUEST_PROCUREMENT,
        workflow_status=oa_entry.STATUS_PENDING,
        business_status="待价格审批",
        current_step_index=1,
        current_step_label=step.label,
        amount=Decimal("123.45"),
        approved_amount=None,
    )

    oa_entry._advance_after_step(doc, step)

    assert doc.workflow_status == oa_entry.STATUS_COMPLETED
    assert doc.business_status == "价格已批准/待补充合同信息"
    assert doc.approved_amount == Decimal("123.45")


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
    # Demand approval now ends the OA stage; contract/PR execution is handled
    # by the downstream procurement chain.
    assert doc.business_status == "需求已批准/待询价"
    assert doc.approved_amount == Decimal("123.45")
