"""待办和通知里的跳转链接（2026-10 导航审计 P1）：每条链接带的查询参数，目标页面必须认得。

价格审批页（PriceWorkbench）只认 approval= / pr= / po=，request= 是 OA 采购申请单号；
物料进度看板（MaterialProgress）的 request= 是来源 OA 申请单号，不是物料进度行自己的编号。
"""
from types import SimpleNamespace

from rayher_hr_payroll.api import overview_entry as ov


def _fake_db(monkeypatch, handler):
    monkeypatch.setattr(ov.frappe, "db", SimpleNamespace(get_value=handler), raising=False)


def test_price_approval_todo_opens_the_approval_not_a_procurement_request(monkeypatch):
    monkeypatch.setattr(ov, "_user", lambda: "vice@example.com")
    monkeypatch.setattr(ov, "_roles", lambda: set())
    monkeypatch.setattr(ov, "position_users", lambda key: {"vice@example.com"})
    monkeypatch.setattr(ov, "waiting_days", lambda since: 1)
    monkeypatch.setattr(ov.frappe, "get_all", lambda *args, **kwargs: [
        SimpleNamespace(name="PA-2026-0001", total_amount=1200, modified="2026-10-01 10:00:00", owner="buyer@example.com"),
    ], raising=False)
    _fake_db(monkeypatch, lambda *args, **kwargs: "采购员")

    items = ov._price_approval_tasks()

    assert [item["name"] for item in items] == ["PA-2026-0001"]
    assert items[0]["route"] == "/approval/procurement/price-approvals"
    assert items[0]["query"] == {"approval": "PA-2026-0001"}
    assert "request" not in items[0]["query"]


def test_price_approval_todo_is_empty_for_other_people(monkeypatch):
    monkeypatch.setattr(ov, "_user", lambda: "someone@example.com")
    monkeypatch.setattr(ov, "_roles", lambda: set())
    monkeypatch.setattr(ov, "position_users", lambda key: {"vice@example.com"})

    assert ov._price_approval_tasks() == []


def _summary_db(monkeypatch):
    def get_value(doctype, filters=None, fieldname=None, as_dict=False, **kwargs):
        if doctype in ("OA Price Approval Line", "OA Procurement Request Line"):
            return {"source_request": "OA-1", "item_name": "硅光芯片"}
        if doctype == "OA Approval Request":
            return "采购硅光芯片"
        if doctype == "OA Price Approval" and fieldname == "total_amount":
            return 5000
        if doctype == "OA Purchase Order":
            return {"supplier": "苏州精测", "status": "待演示员工116复核", "total_amount": 800}
        if doctype == "OA Purchase Order Line":
            return "探针卡"
        if doctype == "OA Material Progress":
            return {"source_request": "OA-9", "source_line": "row-3", "item_name": "擦镜纸"}
        return None
    _fake_db(monkeypatch, get_value)


def test_price_approval_notification_opens_the_approval_tab(monkeypatch):
    _summary_db(monkeypatch)

    summary = ov._document_summary("OA Price Approval", "PA-7")

    assert summary["route"] == "/approval/procurement/price-approvals"
    assert summary["query"] == {"view": "approvals", "approval": "PA-7"}
    assert summary["title"] == "采购硅光芯片"


def test_procurement_request_notification_opens_the_pr_source_tab(monkeypatch):
    _summary_db(monkeypatch)

    summary = ov._document_summary("OA Procurement Request", "PR-3")

    assert summary["route"] == "/approval/procurement/price-approvals"
    assert summary["query"] == {"view": "source", "pr": "PR-3"}


def test_purchase_order_notification_opens_the_po_tab(monkeypatch):
    _summary_db(monkeypatch)

    summary = ov._document_summary("OA Purchase Order", "PO-5")

    assert summary["route"] == "/approval/procurement/price-approvals"
    assert summary["query"] == {"tab": "po", "po": "PO-5"}


def test_material_progress_notification_filters_by_the_source_request(monkeypatch):
    _summary_db(monkeypatch)

    summary = ov._document_summary("OA Material Progress", "MP-0001")

    assert summary["route"] == "/approval/material-progress"
    assert summary["query"] == {"request": "OA-9", "source_line": "row-3"}
    assert "MP-0001" not in summary["query"].values()


def test_material_progress_notification_without_a_source_has_no_filter(monkeypatch):
    _fake_db(monkeypatch, lambda *args, **kwargs: None)

    summary = ov._document_summary("OA Material Progress", "MP-0002")

    assert summary["route"] == "/approval/material-progress"
    assert summary["query"] == {}


def test_every_notification_document_route_has_a_fixed_shape():
    for doctype, value in ov.DOC_ROUTES.items():
        route, key, extra = value
        assert route.startswith("/approval/"), doctype
        assert key and isinstance(extra, dict), doctype
