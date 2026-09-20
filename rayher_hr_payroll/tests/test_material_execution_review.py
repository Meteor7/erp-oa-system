"""Regressions for original-OA slices and split quantity stages."""
import importlib
import json
import sqlite3
import sys
import types
import pytest


@pytest.fixture
def modules(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda *args, **kwargs: lambda function: function
    frappe.PermissionError = PermissionError
    frappe.throw = lambda message, exc=ValueError: (_ for _ in ()).throw(exc(message))
    frappe.session = types.SimpleNamespace(user="applicant@example.com")
    frappe.get_roles = lambda user: ["Employee"]
    utils = types.ModuleType("frappe.utils")
    utils.getdate = utils.get_datetime = utils.now_datetime = lambda *args: None
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    for name in ("rayher_hr_payroll.api.material_progress", "rayher_hr_payroll.api.material_execution"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    progress = importlib.import_module("rayher_hr_payroll.api.material_progress")
    execution = importlib.import_module("rayher_hr_payroll.api.material_execution")
    monkeypatch.setattr(execution, "require_request_type_access", lambda *args: None)
    monkeypatch.setattr(execution, "can_access_board", lambda user: False)
    monkeypatch.setattr(execution, "_active_identity", lambda user: {})
    return frappe, progress, execution


def test_original_oa_slice_keeps_split_quantities_and_excludes_commercial_fields(modules, monkeypatch):
    frappe, _, api = modules
    ns = types.SimpleNamespace
    source = ns(name="OA-OWN", request_type="采购申请", workflow_status="已完成", business_lines=[ns(name="MOTOR", material_serial="MAT-1", item_name="电机", specification="TEST", unit="台", quantity=10), ns(name="SENSOR")])
    frappe.get_doc = lambda *args: source
    monkeypatch.setattr(api, "_can_read", lambda *args: True)
    calls = []
    def sql(query, values, **kwargs):
        calls.append((query, values))
        assert values == {"request": "OA-OWN", "lines": ["MOTOR"]}
        assert "l.source_request=%(request)s" in query and "l.source_line IN %(lines)s" in query
        assert "supplier" not in query and "total_amount" not in query
        if "`tabOA Procurement Request Line`" in query:
            return [ns(name="PR-L1", parent="PR-1", source_line="MOTOR", quantity=6, remaining_quantity=0, status="已完成"), ns(name="PR-L2", parent="PR-2", source_line="MOTOR", quantity=4, remaining_quantity=4, status="草稿")]
        if "`tabOA Price Approval Line`" in query:
            return []
        return [ns(parent="PO-MERGED", source_line="MOTOR", source_pr_line="PR-L1", quantity=6, received_quantity=4, inspection_status="待验收", contract_delivery_date="2026-10-01", status="到货验收中", payment_status="部分付款")]
    frappe.db = ns(sql=sql)
    result = api.get_progress(source.name, limit=1)
    item = result["items"][0]
    assert result["total"] == 2 and result["has_more"] and not result["can_access_board"]
    assert item["pr_quantity"] == 10 and item["unallocated_quantity"] == 0
    assert len(item["branches"]) == 2 and item["branches"][0]["orders"][0]["received_quantity"] == 4
    assert item["branches"][1]["orders"] == [] and len(calls) == 3


def test_unrelated_oa_rejected_before_chain_queries(modules, monkeypatch):
    frappe, _, api = modules
    frappe.get_doc = lambda *args: types.SimpleNamespace(request_type="采购申请")
    monkeypatch.setattr(api, "_can_read", lambda *args: False)
    with pytest.raises(PermissionError):
        api.get_progress("OA-OTHER")


@pytest.mark.parametrize("po_qty,price_qty,po_status,expected", [
    (6,6,"已关闭","采购确认中"), (6,10,"已关闭","PO处理中"),
    (10,10,"已关闭","已关闭"), (10,10,"到货验收中","到货验收中"),
])
def test_partial_closed_po_cannot_close_whole_original_material(modules, po_qty, price_qty, po_status, expected):
    _, progress, _ = modules
    from rayher_hr_payroll.material_progress_query import stage_sql, FROM_SQL
    board = types.SimpleNamespace(status="", quantity=10, po_numbers="PO-1", price_approval_numbers="PRICE-1")
    source = types.SimpleNamespace(workflow_status="已完成", business_status="")
    assert progress._derived_status(board, source, {"PO-1": po_status}, {"po_quantity": po_qty, "price_approval_quantity": price_qty}) == expected
    # The database filter and Python serializer must agree on mixed batches.
    db = sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE `tabOA Material Progress` (source_request,source_line,status,quantity,price_approval_numbers); CREATE TABLE `tabOA Approval Request` (name,workflow_status,business_status); CREATE TABLE `tabOA Purchase Order Line` (parent,source_request,source_line,quantity); CREATE TABLE `tabOA Purchase Order` (name,status); CREATE TABLE `tabOA Price Approval Line` (parent,source_request,source_line,quantity); CREATE TABLE `tabOA Price Approval` (name,status);")
    db.execute("INSERT INTO `tabOA Material Progress` VALUES ('OA','LINE','',10,'PRICE-1')")
    db.execute("INSERT INTO `tabOA Approval Request` VALUES ('OA','已完成','')")
    db.execute("INSERT INTO `tabOA Purchase Order Line` VALUES ('PO-1','OA','LINE',?)", (po_qty,))
    db.execute("INSERT INTO `tabOA Purchase Order` VALUES ('PO-1',?)", (po_status,))
    db.execute("INSERT INTO `tabOA Price Approval Line` VALUES ('PRICE-1','OA','LINE',?)", (price_qty,))
    db.execute("INSERT INTO `tabOA Price Approval` VALUES ('PRICE-1','已通过')")
    assert db.execute("SELECT " + stage_sql().replace("%%", "%") + " " + FROM_SQL).fetchone()[0] == expected
