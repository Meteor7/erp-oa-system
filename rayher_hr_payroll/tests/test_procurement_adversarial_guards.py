import inspect
from types import SimpleNamespace as NS
import pytest


def fail(message, *args):
    raise ValueError(message)


def test_native_mutations_cannot_forge_trusted_flags(monkeypatch):
    from rayher_hr_payroll import procurement_mutation_guard as guard
    monkeypatch.setattr(guard, "frappe", NS(throw=fail, PermissionError=PermissionError))
    doc = NS(flags=NS(ignore_permissions=True, authorized_procurement_action=True))
    with pytest.raises(ValueError): guard.require_procurement_action(doc)
    @guard.procurement_action
    def trusted(): guard.require_procurement_action(doc)
    trusted()
    with pytest.raises(ValueError): guard.require_procurement_action(doc)
    @guard.procurement_action
    def failed(): raise RuntimeError("test")
    with pytest.raises(RuntimeError): failed()
    with pytest.raises(ValueError): guard.require_procurement_action(doc)


def test_new_receipt_does_not_inherit_passed_inspection(monkeypatch):
    from rayher_hr_payroll.api import procurement_chain as pc
    line = NS(name="L1", quantity=10, received_quantity=4, inspection_status="已通过",
              material_serial="M1", item_name="Motor", unit="pcs", source_request="OA1")
    po = NS(name="PO1", status="到货验收中", lines=[line], save=lambda **kw: None)
    def get_doc(*args, **kwargs):
        assert kwargs.get("for_update") is True
        return po
    monkeypatch.setattr(pc, "frappe", NS(get_doc=get_doc, throw=fail, db=NS(commit=lambda: None)))
    monkeypatch.setattr(pc, "_require_production_receipt", lambda: None)
    events = []
    monkeypatch.setattr(pc, "_create_fulfillment_record", lambda *a: events.append(a))
    monkeypatch.setattr(pc, "_notify", lambda *a: None)
    monkeypatch.setattr(pc, "_po_summary", lambda d: {})
    inspect.unwrap(pc.record_po_receipt)("PO1", [{"line": "L1", "quantity": 6}])
    assert line.received_quantity == 10
    assert line.inspection_status == "待验收"
    assert events[0][3][0]["quantity"] == 6


def test_pr_uses_current_allocation_after_source_lock(monkeypatch):
    from rayher_hr_payroll.api import procurement_chain as pc
    events = []
    line = NS(name="L1", quantity=10, material_serial="M1")
    source = NS(name="OA1", business_lines=[line], business_status="需求已批准", workflow_status="已完成")
    def get_doc(*args, **kwargs):
        assert kwargs.get("for_update") is True
        events.append("source_locked")
        return source
    def sql(query, params, **kwargs):
        assert events == ["source_locked"]
        assert "FOR UPDATE" in query
        assert "已取消" in query
        return [{"quantity": 7}]
    monkeypatch.setattr(pc, "frappe", NS(get_doc=get_doc, new_doc=lambda *a: NS(),
        session=NS(user="pmc"), throw=fail, db=NS(sql=sql)))
    monkeypatch.setattr(pc, "_require_pmc", lambda: None)
    with pytest.raises(ValueError, match="可提 PR 数量为 3"):
        inspect.unwrap(pc.create_pr)([{"source_request": "OA1", "source_line": "L1", "quantity": 7}])


def test_shared_child_protects_only_procurement_parents(monkeypatch):
    from rayher_hr_payroll import procurement_mutation_guard as guard
    monkeypatch.setattr(guard, "frappe", NS(throw=fail, PermissionError=PermissionError))
    with pytest.raises(ValueError):
        guard.require_procurement_child_action(NS(parenttype="OA Purchase Order"))
    guard.require_procurement_child_action(NS(parenttype="OA Approval Request"))


@pytest.mark.parametrize("received,inspection,records,blocked", [
    (1, "已通过", [{"record_type": "验收"}], True),
    (10, "待验收", [{"record_type": "到货"}], True),
    (10, "已通过", [], True),
    (10, "已通过", [{"record_type": "验收"}], False),
])
def test_inspection_installment_cannot_release_before_full_receipt(monkeypatch, received, inspection, records, blocked):
    from rayher_hr_payroll.api import procurement_chain as pc
    po = NS(name="PO1", status="到货验收中", contract_status="已生效", lines=[NS(quantity=10, received_quantity=received, inspection_status=inspection)])
    row = NS(trigger_condition="验收通过")
    monkeypatch.setattr(pc, "_fulfillment_records", lambda name: records)
    monkeypatch.setattr(pc.frappe, "throw", fail)
    if blocked:
        with pytest.raises(ValueError): pc._require_po_payment_ready(po, row)
    else:
        pc._require_po_payment_ready(po, row)


def test_direct_push_stops_before_draft_creation_for_partial_receipt(monkeypatch):
    from rayher_hr_payroll.api import procurement_chain as pc
    row = NS(name="PLAN1", status="待审批", payment_request="", trigger_condition="验收通过")
    po = NS(name="PO1", status="到货验收中", contract_status="已生效", payment_plan=[row], lines=[NS(quantity=10, received_quantity=1, inspection_status="已通过")])
    monkeypatch.setattr(pc, "_require_purchase", lambda: None)
    monkeypatch.setattr(pc, "_fulfillment_records", lambda name: [{"record_type": "验收"}])
    monkeypatch.setattr(pc.frappe, "get_doc", lambda *a, **kw: po)
    monkeypatch.setattr(pc.frappe, "throw", fail)
    with pytest.raises(ValueError, match="全部到货"):
        inspect.unwrap(pc.push_po_payment_request)("PO1", "PLAN1")
