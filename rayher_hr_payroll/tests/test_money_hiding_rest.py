"""PMC / 生产主管不见金额的剩余三处（审查 #79 追加）：申请详情、申请看板、采购通知正文。"""
from types import SimpleNamespace

from rayher_hr_payroll.api import oa_entry, procurement_chain


def test_procurement_notification_body_has_no_money_for_pmc(monkeypatch):
    sent = []
    users = {"pmc": {"pmc@tests-x.example.invalid"}, "procurement_manager": {"buyer@tests-x.example.invalid"}, "vice_manager": {"vp@tests-x.example.invalid"},
             "production_asset_owner": {"prod@tests-x.example.invalid"}, "general_manager": {"person014@tests-x.example.invalid"}}
    monkeypatch.setattr(procurement_chain, "position_users", lambda *keys: set().union(*(users.get(k, set()) for k in keys)))
    monkeypatch.setattr(procurement_chain, "_user", lambda: "someone@tests-x.example.invalid")
    monkeypatch.setattr(procurement_chain, "_linked_material_context", lambda names: "物料 A × 2")
    monkeypatch.setattr(procurement_chain, "_notification_link", lambda *args: "/po")
    monkeypatch.setattr(procurement_chain.frappe, "db", SimpleNamespace(exists=lambda *args, **kwargs: True), raising=False)

    class Log:
        def __init__(self, values): self.values = values
        def insert(self, ignore_permissions=False): sent.append(self.values)

    monkeypatch.setattr(procurement_chain.frappe, "get_doc", lambda values: Log(values))
    procurement_chain._notify("PO 付款已更新：PO-1", "本次付款 ¥ 3,000.00，累计付款 ¥ 9,000.00", "OA Purchase Order", "PO-1", [])
    body = {row["for_user"]: row["email_content"] for row in sent}
    assert "3,000" in body["buyer@tests-x.example.invalid"] and "3,000" in body["vp@tests-x.example.invalid"]
    assert "3,000" not in body["pmc@tests-x.example.invalid"] and "金额不对你显示" in body["pmc@tests-x.example.invalid"]


def test_request_detail_hides_contract_money_only_on_procurement_requests(monkeypatch):
    monkeypatch.setattr(procurement_chain, "_amounts_hidden", lambda: True)
    assert oa_entry._hide_procurement_money(SimpleNamespace(request_type=oa_entry.REQUEST_PROCUREMENT)) is True
    assert oa_entry._hide_procurement_money(SimpleNamespace(request_type=oa_entry.REQUEST_REIMBURSEMENT)) is False
    monkeypatch.setattr(procurement_chain, "_amounts_hidden", lambda: False)
    assert oa_entry._hide_procurement_money(SimpleNamespace(request_type=oa_entry.REQUEST_PROCUREMENT)) is False
