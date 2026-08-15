from decimal import Decimal
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import approval_center


class MemoryStore:
    def __init__(self, user="Administrator"):
        self.user = user
        self.saved = []
        self.rows = []
        self.allowed = user in {"Administrator", "admin@staff.example.invalid"}
        self.sources = {}
        self.projects = {}

    def require_draft_access(self, request_type):
        if not self.allowed:
            raise approval_center.ApprovalCenterError("暂未开放")

    def identity(self):
        return {
            "employee": None,
            "employee_name": "管理员",
            "department": "",
            "company": "QIHENG DEMO",
            "supervisor": "直属领导",
            "supervisor_user": "boss@example.com",
            "supervisor_decision": "approve",
        }

    def save_draft(self, request_type, values, name=None):
        row = {
            "name": name or f"OA-{len(self.saved) + 1}",
            "owner": self.user,
            "request_type": request_type,
            **values,
        }
        self.saved.append(row)
        return SimpleNamespace(**row)

    def list_requests(self, request_types, limit):
        return [row for row in self.rows if row["request_type"] in request_types][:limit]

    def resolve_source(self, name):
        if name not in self.sources:
            raise approval_center.ApprovalCenterError("来源申请不存在")
        return self.sources[name]

    def resolve_project(self, name):
        if name not in self.projects:
            raise approval_center.ApprovalCenterError("所属项目不存在")
        return self.projects[name]

    def source_balance(self, source):
        return source.get("balance") or {
            "approved_amount": Decimal(str(source.get("approved_amount") or 0)),
            "reserved_amount": Decimal("0"),
            "paid_amount": Decimal("0"),
            "available_amount": Decimal(str(source.get("approved_amount") or 0)),
        }


def valid_payload():
    return {
        "subject": "采购研发器件",
        "reason": "项目需要",
        "urgency": "一般",
        "asset_nature": "非固定资产",
        "business_lines": [
            {"item_name": "芯片", "specification": "A1", "quantity": "2", "unit": "片", "unit_price": "12.345", "remarks": "测试"},
            {"item_name": "连接器", "quantity": 3, "unit": "个", "unit_price": 5},
        ],
    }


def procurement_payload(**overrides):
    value = valid_payload()
    value.update({
        "procurement_scope": "项目采购",
        "expected_delivery_date": "2026-09-10",
        "project": "PRJ-1",
        "purchaser_user": "buyer@example.com",
    })
    value.update(overrides)
    return value


def payment_payload(**overrides):
    value = valid_payload()
    value.update({
        "source_request": "SRC-1",
        "supplier": "SUP-1",
        "payment_stage": "预付款",
        "prepayment_percentage": 30,
        "has_balance_payment": 1,
    })
    value.update(overrides)
    return value


def test_draft_recalculates_lines_and_keeps_all_workflow_fields_closed():
    store = MemoryStore()
    store.projects["PRJ-1"] = {"name": "PRJ-1", "project_owner": "owner@example.com", "project_owner_name": "项目主管"}
    result = approval_center.save_draft(
        approval_center.REQUEST_PROCUREMENT, procurement_payload(), store=store
    )
    assert result.workflow_status == "草稿"
    assert result.current_step_index == 0
    assert result.current_step_label == ""
    assert result.steps == []
    assert result.approved_amount is None
    assert result.currency == "CNY"
    assert result.amount == Decimal("39.70")
    assert result.business_lines[0]["amount"] == Decimal("24.70")
    assert result.company == "QIHENG DEMO"


def test_non_admin_and_server_owned_payload_fields_fail_closed():
    with pytest.raises(approval_center.ApprovalCenterError, match="暂未开放"):
        approval_center.save_draft(
            approval_center.REQUEST_PROCUREMENT, valid_payload(), store=MemoryStore("employee@example.com")
        )
    for field in ("workflow_status", "approved_amount", "amount", "steps", "owner", "employee", "department", "copied_to"):
        payload = valid_payload()
        payload[field] = "forged"
        with pytest.raises(approval_center.ApprovalCenterError, match="服务端字段"):
            approval_center.save_draft(approval_center.REQUEST_PROCUREMENT, payload, store=MemoryStore())


def test_line_validation_is_bounded_and_fail_closed():
    bad = valid_payload()
    bad["business_lines"][0]["quantity"] = 0
    with pytest.raises(approval_center.ApprovalCenterError, match="数量"):
        approval_center.save_draft(approval_center.REQUEST_DIRECT_PURCHASE, bad, store=MemoryStore())
    bad = valid_payload()
    bad["business_lines"] = bad["business_lines"] * 51
    with pytest.raises(approval_center.ApprovalCenterError, match="100"):
        approval_center.save_draft(approval_center.REQUEST_DIRECT_PURCHASE, bad, store=MemoryStore())



def test_procurement_payment_source_must_be_completed_procurement_and_is_snapshotted():
    store = MemoryStore()
    store.sources["SRC-1"] = {
        "name": "SRC-1", "request_type": approval_center.REQUEST_PROCUREMENT,
        "workflow_status": "待审批", "currency": "CNY", "approved_amount": 100,
        "modified": "2026-08-06 11:00:00",
        "business_lines": [{"quantity": 2}, {"quantity": 3}],
    }
    payload = payment_payload()
    with pytest.raises(approval_center.ApprovalCenterError, match="已完成"):
        approval_center.save_draft(approval_center.REQUEST_PROCUREMENT_PAYMENT, payload, store=store)
    store.sources["SRC-1"]["workflow_status"] = "已完成"
    result = approval_center.save_draft(
        approval_center.REQUEST_PROCUREMENT_PAYMENT, payload, store=store
    )
    assert result.source_request == "SRC-1"
    assert result.approved_amount_snapshot == Decimal("100.00")
    assert result.source_modified == "2026-08-06 11:00:00"
    assert result.payment_source_kind == "关联采购申请"
    assert result.ordered_quantity == Decimal("5.0000")


def test_dashboard_does_not_hide_corrupt_ledger_balance():
    store = MemoryStore()
    store.rows = [{
        "name": "REQ-1", "request_type": approval_center.REQUEST_PROCUREMENT,
        "subject": "申请", "workflow_status": "已完成", "amount": 100,
        "approved_amount": 100, "asset_nature": "非固定资产", "owner": "a", "modified": "now",
    }]
    store.source_balance = lambda _source: (_ for _ in ()).throw(
        approval_center.ApprovalCenterError("金额流水余额不合法")
    )
    with pytest.raises(approval_center.ApprovalCenterError, match="余额不合法"):
        approval_center.dashboard("request", store=store)

def test_request_dashboard_uses_visible_rows_and_preserves_historical_unclassified():
    store = MemoryStore()
    store.rows = [
        {
            "name": "REQ-1", "request_type": approval_center.REQUEST_PROCUREMENT,
            "subject": "旧申请", "workflow_status": "已完成", "amount": 100,
            "approved_amount": 90, "asset_nature": "", "fixed_asset_category": "",
            "owner": "alice@example.com", "modified": "2026-08-06",
            "balance": {"approved_amount": Decimal("90"), "reserved_amount": Decimal("20"), "paid_amount": Decimal("30"), "available_amount": Decimal("40")},
        },
        {
            "name": "PAY-1", "request_type": approval_center.REQUEST_PROCUREMENT_PAYMENT,
            "subject": "付款", "workflow_status": "草稿", "amount": 20,
            "approved_amount": 0, "asset_nature": "固定资产", "fixed_asset_category": "生产设备、生产工具及器具",
            "owner": "alice@example.com", "modified": "2026-08-06",
        },
    ]
    result = approval_center.dashboard("request", store=store)
    assert [row["name"] for row in result["rows"]] == ["REQ-1"]
    assert result["rows"][0]["asset_classification"] == "历史未分类"
    assert result["summary"] == {
        "applied_amount": Decimal("100.00"),
        "approved_amount": Decimal("90.00"),
        "reserved_amount": Decimal("20.00"),
        "paid_amount": Decimal("30.00"),
        "available_amount": Decimal("40.00"),
    }


def test_payment_dashboard_does_not_accept_client_department_scope():
    store = MemoryStore()
    with pytest.raises(TypeError):
        approval_center.dashboard("payment", department="研发部", store=store)


def test_unknown_dashboard_kind_rejected():
    with pytest.raises(approval_center.ApprovalCenterError, match="看板"):
        approval_center.dashboard("all", store=MemoryStore())

def test_procurement_draft_snapshots_project_owner_and_server_identity():
    store = MemoryStore()
    store.projects["PRJ-1"] = {
        "name": "PRJ-1", "project_owner": "owner@example.com", "project_owner_name": "项目主管"
    }
    result = approval_center.save_draft(
        approval_center.REQUEST_PROCUREMENT, procurement_payload(), store=store
    )
    assert result.project == "PRJ-1"
    assert result.project_owner == "owner@example.com"
    assert result.project_owner_name == "项目主管"
    assert result.expected_delivery_date == "2026-09-10"
    assert result.supervisor == "直属领导"


def test_procurement_rejects_missing_delivery_and_project_owner():
    store = MemoryStore()
    store.projects["PRJ-1"] = {"name": "PRJ-1", "project_owner": ""}
    with pytest.raises(approval_center.ApprovalCenterError, match="项目负责人"):
        approval_center.save_draft(
            approval_center.REQUEST_PROCUREMENT, procurement_payload(), store=store
        )
    store.projects["PRJ-1"]["project_owner"] = "owner@example.com"
    with pytest.raises(approval_center.ApprovalCenterError, match="意向交期"):
        approval_center.save_draft(
            approval_center.REQUEST_PROCUREMENT, procurement_payload(expected_delivery_date=""), store=store
        )


def test_direct_purchase_method_and_procurement_payment_fields_are_separate():
    direct = approval_center.save_draft(
        approval_center.REQUEST_DIRECT_PURCHASE,
        {**valid_payload(), "purchase_method": "京东购买"},
        store=MemoryStore(),
    )
    assert direct.purchase_method == "京东购买"

    store = MemoryStore()
    store.sources["SRC-1"] = {
        "name": "SRC-1", "request_type": approval_center.REQUEST_PROCUREMENT,
        "workflow_status": "已完成", "currency": "CNY", "approved_amount": 100,
        "modified": "2026-08-15 10:00:00",
    }
    payment = approval_center.save_draft(
        approval_center.REQUEST_PROCUREMENT_PAYMENT, payment_payload(), store=store
    )
    assert payment.supplier == "SUP-1"
    assert payment.payment_stage == "预付款"
    assert payment.prepayment_percentage == 30
