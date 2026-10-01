"""收货 / 验收 / 换货 / 退货规则（2026-10-01，用户决定：到货和验收都由生产主管登记）。"""
import inspect
from types import SimpleNamespace as NS

import pytest


@pytest.fixture(autouse=True)
def _open_procurement_gates(monkeypatch):
    from rayher_hr_payroll.api import procurement_chain as pc
    monkeypatch.setattr(pc, "_require_gate", lambda request_type: None)


def fail(message, *args):
    raise ValueError(message)


def line(name="L1", quantity=10, received=10, status="待验收", serial="M1"):
    return NS(name=name, quantity=quantity, received_quantity=received, inspection_status=status,
              material_serial=serial, item_name="控制器", unit="个", source_request="OA1")


def po_with(*lines, status="到货验收中"):
    saved = []
    po = NS(name="PO1", status=status, lines=list(lines), payment_plan=[], save=lambda **kw: saved.append(True))
    po.saved = saved
    return po


def patch_world(monkeypatch, po):
    from rayher_hr_payroll.api import procurement_chain as pc
    events = []
    monkeypatch.setattr(pc, "frappe", NS(get_doc=lambda *a, **kw: po, throw=fail, db=NS(commit=lambda: None)))
    monkeypatch.setattr(pc, "_require_production_receipt", lambda: None)
    monkeypatch.setattr(pc, "_create_fulfillment_record", lambda *a: events.append(a))
    monkeypatch.setattr(pc, "_sync_po_payment_fulfilment", lambda doc: None)
    monkeypatch.setattr(pc, "_notify", lambda *a: None)
    monkeypatch.setattr(pc, "_po_summary", lambda d: {})
    return pc, events


def test_inspection_is_registered_by_production_not_purchase(monkeypatch):
    from rayher_hr_payroll.api import procurement_chain as pc
    monkeypatch.setattr(pc, "frappe", NS(throw=fail))
    monkeypatch.setattr(pc, "_can_record_receipt", lambda: False)
    monkeypatch.setattr(pc, "_can_purchase", lambda: True)
    with pytest.raises(ValueError, match="只有生产主管或系统管理员可以登记到货资料"):
        inspect.unwrap(pc.record_po_inspection)("PO1", [{"line": "L1", "status": "已通过"}])
    monkeypatch.setattr(pc, "_can_record_receipt", lambda: True)
    assert pc._can_record_inspection() is True
    monkeypatch.setattr(pc, "_can_record_receipt", lambda: False)
    assert pc._can_record_inspection() is False


def test_inspection_passes_and_moves_po_to_payment_stage(monkeypatch):
    first, second = line("L1"), line("L2", serial="M2")
    po = po_with(first, second)
    pc, events = patch_world(monkeypatch, po)
    inspect.unwrap(pc.record_po_inspection)("PO1", [{"line": "L1", "status": "已通过"}, {"line": "L2", "status": "已通过"}], "2026-10-01", "F1")
    assert (first.inspection_status, second.inspection_status) == ("已通过", "已通过")
    assert po.status == "付款中"
    assert events[0][1] == "验收"


def test_inspection_is_allowed_while_po_is_in_payment_stage(monkeypatch):
    # 原来付款一笔就把 PO 置为"付款中"，而验收只允许在"到货验收中/供应商制作中"，货到齐但没验收的 PO 会卡死。
    item = line("L1")
    po = po_with(item, status="付款中")
    pc, events = patch_world(monkeypatch, po)
    inspect.unwrap(pc.record_po_inspection)("PO1", [{"line": "L1", "status": "已通过"}])
    assert item.inspection_status == "已通过"
    assert po.status == "付款中"


@pytest.mark.parametrize("status", ["换货中", "退货中"])
def test_exchange_and_return_need_a_reason(monkeypatch, status):
    po = po_with(line("L1"))
    pc, events = patch_world(monkeypatch, po)
    with pytest.raises(ValueError, match="请填写原因"):
        inspect.unwrap(pc.record_po_inspection)("PO1", [{"line": "L1", "status": status}])
    inspect.unwrap(pc.record_po_inspection)("PO1", [{"line": "L1", "status": status, "reason": "插损超标"}])
    assert po.lines[0].inspection_status == status
    assert events[0][3][0]["reason"] == "插损超标"
    assert po.status == "到货验收中"


def test_inspection_refuses_unreceived_line_duplicates_and_unknown_results(monkeypatch):
    po = po_with(line("L1", received=0, status="未验收"), line("L2"))
    pc, events = patch_world(monkeypatch, po)
    with pytest.raises(ValueError, match="尚未到货"):
        inspect.unwrap(pc.record_po_inspection)("PO1", [{"line": "L1", "status": "已通过"}])
    with pytest.raises(ValueError, match="重复"):
        inspect.unwrap(pc.record_po_inspection)("PO1", [{"line": "L2", "status": "已通过"}, {"line": "L2", "status": "已通过"}])
    with pytest.raises(ValueError, match="验收明细或验收结果无效"):
        inspect.unwrap(pc.record_po_inspection)("PO1", [{"line": "L2", "status": "随便"}])
    closed = po_with(line("L2"), status="已关闭")
    pc, events = patch_world(monkeypatch, closed)
    with pytest.raises(ValueError, match="当前 PO 不能登记验收"):
        inspect.unwrap(pc.record_po_inspection)("PO1", [{"line": "L2", "status": "已通过"}])


def test_exchange_receipt_returns_line_to_inspection_without_adding_stock(monkeypatch):
    item = line("L1", received=10, status="换货中")
    other = line("L2", serial="M2", received=10, status="已通过")
    po = po_with(item, other)
    pc, events = patch_world(monkeypatch, po)
    inspect.unwrap(pc.record_po_exchange_receipt)("PO1", [{"line": "L1", "quantity": 10}], "2026-10-02", "F2")
    assert item.received_quantity == 10
    assert item.inspection_status == "待验收"
    assert other.inspection_status == "已通过"
    assert events[0][1] == "换货到货"
    assert po.status == "到货验收中"


def test_exchange_receipt_only_for_exchange_lines_and_in_one_go(monkeypatch):
    po = po_with(line("L1", status="已通过"), line("L2", serial="M2", status="换货中"))
    pc, events = patch_world(monkeypatch, po)
    with pytest.raises(ValueError, match="当前不是「换货中」"):
        inspect.unwrap(pc.record_po_exchange_receipt)("PO1", [{"line": "L1", "quantity": 10}], "2026-10-02", "F2")
    with pytest.raises(ValueError, match="需要一次换货到货"):
        inspect.unwrap(pc.record_po_exchange_receipt)("PO1", [{"line": "L2", "quantity": 4}], "2026-10-02", "F2")
    assert events == []


def test_return_clears_received_quantity_until_supplier_redelivers(monkeypatch):
    item = line("L1", received=10, status="退货中")
    po = po_with(item)
    pc, events = patch_world(monkeypatch, po)
    inspect.unwrap(pc.record_po_return)("PO1", [{"line": "L1", "quantity": 10}], "2026-10-02", "F3")
    assert item.received_quantity == 0
    assert item.inspection_status == "未验收"
    assert events[0][1] == "退货"
    assert po.status == "供应商制作中"
    again = line("L2", serial="M2", received=10, status="退货中")
    kept = line("L3", serial="M3", received=10, status="已通过")
    po = po_with(again, kept)
    pc, events = patch_world(monkeypatch, po)
    inspect.unwrap(pc.record_po_return)("PO1", [{"line": "L2", "quantity": 10}], "2026-10-02", "F3")
    assert po.status == "到货验收中"
    with pytest.raises(ValueError, match="当前不是「退货中」"):
        inspect.unwrap(pc.record_po_return)("PO1", [{"line": "L3", "quantity": 10}], "2026-10-02", "F3")


def test_redelivery_after_return_goes_through_normal_receipt(monkeypatch):
    item = line("L1", received=0, status="未验收")
    po = po_with(item, status="供应商制作中")
    pc, events = patch_world(monkeypatch, po)
    inspect.unwrap(pc.record_po_receipt)("PO1", [{"line": "L1", "quantity": 10}], "2026-10-05", "F4")
    assert item.received_quantity == 10
    assert item.inspection_status == "待验收"


def work_row(**overrides):
    values = {"name": "PLAN-1", "installment_no": 2, "installment_name": "尾款", "payment_stage": "尾款",
              "planned_date": "2026-10-25", "trigger_condition": "全部到货并验收通过", "invoice_requirement": "付款前提供",
              "percentage": 70, "amount": 700, "paid_amount": 0, "status": "待审批", "payment_request": ""}
    values.update(overrides)
    return NS(**values)


class WorkLine(NS):
    def as_dict(self):
        return dict(vars(self))


def work_po(*lines, status="到货验收中"):
    return NS(name="PO1", status=status, contract_status="已生效", currency="CNY", supplier="供应商", source_price_approvals="PA1", lines=list(lines))


def patch_work(monkeypatch, *, production, purchase, draft=""):
    from rayher_hr_payroll.api import procurement_chain as pc
    monkeypatch.setattr(pc, "_can_record_receipt", lambda: production)
    monkeypatch.setattr(pc, "_can_purchase", lambda: purchase)
    monkeypatch.setattr(pc, "_fulfillment_records", lambda name: [])
    monkeypatch.setattr(pc, "_draft_payment_request", lambda po, row: draft)
    return pc


def wl(name, quantity, received, status):
    return WorkLine(name=name, material_serial=name, item_name="物料", quantity=quantity, received_quantity=received, inspection_status=status)


def test_work_item_flags_follow_production_role_and_line_states(monkeypatch):
    pc = patch_work(monkeypatch, production=True, purchase=False)
    po = work_po(wl("A", 10, 10, "换货中"), wl("B", 5, 0, "未验收"), wl("C", 3, 3, "退货中"), wl("D", 2, 2, "待验收"))
    item = pc._payment_work_item(po, work_row())
    assert (item["can_record_receipt"], item["can_record_inspection"], item["can_record_exchange"], item["can_record_return"]) == (1, 1, 1, 1)
    assert item["can_push_payment"] == 0
    assert item["requires_receipt"] == 1 and item["requires_inspection"] == 1
    assert item["work_status"] == "待到货资料"


def test_work_item_hides_registration_from_purchase_and_finance(monkeypatch):
    pc = patch_work(monkeypatch, production=False, purchase=True)
    po = work_po(wl("A", 10, 10, "待验收"))
    item = pc._payment_work_item(po, work_row(trigger_condition="合同生效"))
    assert (item["can_record_receipt"], item["can_record_inspection"], item["can_record_exchange"], item["can_record_return"]) == (0, 0, 0, 0)
    assert item["work_status"] == "可提交付款审批" and item["can_push_payment"] == 1


def test_returned_draft_blocks_a_second_push_and_is_reported(monkeypatch):
    pc = patch_work(monkeypatch, production=False, purchase=True, draft="OA-2026-1")
    item = pc._payment_work_item(work_po(wl("A", 10, 10, "已通过")), work_row(trigger_condition="合同生效"))
    assert item["draft_request"] == "OA-2026-1"
    assert item["can_push_payment"] == 0
    po = NS(name="PO1", status="供应商制作中", contract_status="已生效", payment_plan=[work_row(name="PLAN-1")], lines=[wl("A", 10, 10, "已通过")])
    monkeypatch.setattr(pc, "_require_purchase", lambda: None)
    monkeypatch.setattr(pc, "_fulfillment_records", lambda name: [])
    monkeypatch.setattr(pc.frappe, "get_doc", lambda *a, **kw: po)
    monkeypatch.setattr(pc.frappe, "throw", fail)
    po.payment_plan[0].trigger_condition = "合同生效"
    with pytest.raises(ValueError, match="已有被退回的采购付款 OA-2026-1"):
        inspect.unwrap(pc.push_po_payment_request)("PO1", "PLAN-1")


def test_regressed_conditions_are_flagged_on_an_in_flight_payment(monkeypatch):
    pc = patch_work(monkeypatch, production=False, purchase=False)
    monkeypatch.setattr(pc.frappe, "db", NS(exists=lambda *a, **kw: False), raising=False)
    po = work_po(wl("A", 10, 10, "换货中"))
    item = pc._payment_work_item(po, work_row())
    assert item["conditions_regressed"] == 0
    # An OA that was submitted while the gates were open and has since regressed.
    summary_row = work_row(payment_request="OA-2026-9", status="已下推")
    monkeypatch.setattr(pc.frappe, "db", NS(exists=lambda *a, **kw: True), raising=False)
    monkeypatch.setattr(pc.frappe, "get_doc", lambda *a, **kw: NS(
        name="OA-2026-9", workflow_status="待审批", business_status="待审批", current_step_index=2, current_step_label="财务主管：某人"))
    item = pc._payment_work_item(po, summary_row)
    assert item["work_status"] == "付款审批中"
    assert item["conditions_regressed"] == 1
    assert "本期要求验收通过" in item["blockers"]


def test_work_item_reports_invoice_documents_without_reading_the_documents(monkeypatch):
    pc = patch_work(monkeypatch, production=False, purchase=True)
    monkeypatch.setattr(pc, "_invoice_document_count", lambda request: 2 if request == "OA-9" else 0)
    po = work_po(wl("A", 10, 10, "已通过"))
    monkeypatch.setattr(pc.frappe, "db", NS(exists=lambda *a, **kw: True), raising=False)
    monkeypatch.setattr(pc.frappe, "get_doc", lambda *a, **kw: NS(
        name="OA-9", workflow_status="待审批", business_status="待审批", current_step_index=5, current_step_label="总经理付款：某人"))
    item = pc._payment_work_item(po, work_row(payment_request="OA-9", status="已下推", trigger_condition="合同生效"))
    assert item["invoice_documents"] == 2
    assert pc._payment_work_item(po, work_row(trigger_condition="合同生效"))["invoice_documents"] == 0
