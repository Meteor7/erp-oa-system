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
