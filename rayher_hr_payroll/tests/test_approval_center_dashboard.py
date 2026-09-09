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
        self.project_rows = []
        self.payment_balances = {}
        self.payment_initiator_allowed = True
        self.default_purchaser = "buyer@example.com"

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

    def list_projects(self, limit):
        return self.project_rows[:limit]

    def list_procurement_payment_sources(self, limit):
        return self.rows[:limit]

    def source_balance(self, source):
        return source.get("balance") or {
            "approved_amount": Decimal(str(source.get("approved_amount") or 0)),
            "reserved_amount": Decimal("0"),
            "paid_amount": Decimal("0"),
            "available_amount": Decimal(str(source.get("approved_amount") or 0)),
        }

    def payment_balance(self, payment):
        return self.payment_balances.get(
            payment["name"],
            approval_center._zero_balance(payment.get("approved_amount")),
        )

    def can_initiate_procurement_payment(self, source):
        return self.payment_initiator_allowed

    def default_purchaser_user(self):
        return self.default_purchaser

    def payment_plan_row_in_use(self, row_name, current_name=None):
        return False


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
    value["business_lines"] = [
        {**line, "category_code": "1.ELC.3", "specification": line.get("specification") or "标准规格", "brand": line.get("brand") or "测试品牌"}
        for line in value["business_lines"]
    ]
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
        "source_payment_plan_row": "PLAN-1",
        "supplier": "SUP-1",
        "payment_stage": "预付款",
        "prepayment_percentage": 30,
        "has_balance_payment": 1,
    })
    value.update(overrides)
    return value


def test_procurement_project_options_expose_only_minimal_owner_snapshot():
    store = MemoryStore()
    store.project_rows = [
        {"name": "RD04", "project_name": "VEYMONT 2341", "status": "Open",
         "project_owner": "owner@example.com", "project_owner_name": "项目主管",
         "project_initiation_report": "/private/files/secret.pdf"},
    ]
    assert approval_center.project_options(store=store) == [{
        "name": "RD04", "project_name": "VEYMONT 2341", "status": "Open",
        "project_owner": "owner@example.com", "project_owner_name": "项目主管",
    }]


def test_payment_source_options_return_only_completed_available_procurements():
    store = MemoryStore(user="buyer@example.com")
    store.allowed = True
    store.rows = [
        {
            "name": "PROC-1", "request_type": "采购申请", "subject": "可付款",
            "workflow_status": "已完成", "approved_amount": 100,
            "purchaser_user": "buyer@example.com", "contract_status": "已生效",
            "supplier": "SUP-1", "inspection_status": "未验收", "arrival_status": "未到货",
            "payment_plan": [{"name": "PLAN-1", "status": "待下推", "payment_stage": "预付款", "percentage": 100, "amount": 100, "trigger_condition": "合同生效", "invoice_requirement": "付款后提供"}],
        },
        {
            "name": "PROC-2", "request_type": "采购申请", "subject": "无余额",
            "workflow_status": "已完成", "approved_amount": 100,
            "purchaser_user": "buyer@example.com",
            "balance": {"approved_amount": 100, "reserved_amount": 100, "paid_amount": 0, "available_amount": 0},
        },
        {
            "name": "DIRECT-1", "request_type": "购买申请", "subject": "错误类型",
            "workflow_status": "已完成", "approved_amount": 100,
        },
    ]

    result = approval_center.procurement_payment_source_options(store=store)

    assert [row["name"] for row in result] == ["PROC-1"]
    assert result[0]["purchaser_user"] == "buyer@example.com"
    assert result[0]["available_amount"] == Decimal("100")
    assert result[0]["payment_plan_row"] == "PLAN-1"


def test_approval_center_identity_climbs_past_accountless_excel_supervisor(monkeypatch):
    monkeypatch.setattr(
        approval_center,
        "_enabled_employee_user",
        lambda employee_name: (
            "demo_executive@example.com" if employee_name == "演示员工21" else ""
        ),
    )

    result = approval_center._resolved_supervisor("演示员工109", "HR-EMP-MANAGER")

    assert result == {
        "supervisor": "演示员工21",
        "supervisor_user": "demo_executive@example.com",
        "supervisor_decision": "skip",
        "supervisor_path": ["演示员工155", "演示员工21"],
    }


def test_frappe_payment_source_query_is_scoped_to_purchaser_or_finance(monkeypatch):
    calls = []
    monkeypatch.setattr(approval_center.frappe, "session", SimpleNamespace(user="buyer@example.com"))
    monkeypatch.setattr(approval_center.frappe, "get_roles", lambda _user=None: ["Employee"])
    monkeypatch.setattr(
        approval_center.frappe,
        "get_all",
        lambda *args, **kwargs: calls.append((args, kwargs)) or [],
    )
    store = approval_center.FrappeApprovalCenterStore()

    store.list_procurement_payment_sources(50)
    assert calls[-1][1]["filters"]["purchaser_user"] == "buyer@example.com"

    approval_center.frappe.session.user = "finance@example.com"
    monkeypatch.setattr(approval_center.frappe, "get_roles", lambda _user=None: ["Accounts User"])
    store.list_procurement_payment_sources(50)
    assert "purchaser_user" not in calls[-1][1]["filters"]


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
    assert result.amount == Decimal("0.00")
    assert result.business_lines[0]["unit_price"] == Decimal("0.00")
    assert result.business_lines[0]["amount"] == Decimal("0.00")
    assert result.ordered_quantity == Decimal("5.0000")
    assert result.company == "QIHENG DEMO"


def test_pmc_can_save_procurement_for_selected_employee_and_others_cannot_forge_it():
    store = MemoryStore(user="pmc@example.com")
    store.allowed = True
    selected = {
        "employee": "EMP-OTHER",
        "employee_name": "其他员工",
        "department": "软件部",
        "company": "QIHENG DEMO",
        "supervisor": "演示员工132",
        "supervisor_user": "junzhang@example.com",
        "supervisor_decision": "approve",
    }
    store.resolve_procurement_applicant = lambda employee: (
        selected if employee == "EMP-OTHER" else store.identity()
    )
    store.projects["PRJ-1"] = {
        "name": "PRJ-1",
        "project_owner": "owner@example.com",
        "project_owner_name": "项目主管",
    }

    result = approval_center.save_draft(
        approval_center.REQUEST_PROCUREMENT,
        procurement_payload(applicant_employee="EMP-OTHER"),
        store=store,
    )

    assert result.employee == "EMP-OTHER"
    assert result.employee_name == "其他员工"
    assert result.department == "软件部"


def test_procurement_purchaser_is_resolved_server_side_and_cannot_be_forged():
    store = MemoryStore()
    store.default_purchaser = "manager@example.com"
    store.projects["PRJ-1"] = {
        "name": "PRJ-1", "project_owner": "owner@example.com",
        "project_owner_name": "项目主管",
    }
    result = approval_center.save_draft(
        approval_center.REQUEST_PROCUREMENT,
        procurement_payload(purchaser_user="forged@example.com"),
        store=store,
    )
    assert result.purchaser_user == "manager@example.com"


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


def test_line_validation_ignores_known_frontend_state_but_rejects_unknown_fields():
    payload = valid_payload()
    payload["business_lines"][0].update({
        "material_serial": "client-value-must-not-be-persisted",
        "category_parts": ["1", "ELC", "3"],
        "category_query": "1.ELC.3",
        "category_open": True,
        "category_picker_parent": "1.ELC",
        "category_picker_path": ["1", "1.ELC"],
        "material_query": "芯片",
        "material_open": True,
        "category_name": "电子物料",
        "amount": 999,
    })
    lines, total = approval_center._lines(payload["business_lines"])
    assert "material_serial" not in lines[0]
    assert lines[0]["amount"] == Decimal("24.70")
    assert total == Decimal("39.70")

    payload["business_lines"][0]["unexpected_field"] = "forged"
    with pytest.raises(approval_center.ApprovalCenterError, match="未知字段.*unexpected_field"):
        approval_center._lines(payload["business_lines"])


def test_line_validation_is_bounded_and_fail_closed():
    bad = valid_payload()
    bad["business_lines"][0]["quantity"] = 0
    with pytest.raises(approval_center.ApprovalCenterError, match="数量"):
        approval_center.save_draft(approval_center.REQUEST_DIRECT_PURCHASE, bad, store=MemoryStore())
    bad = valid_payload()
    bad["business_lines"] = bad["business_lines"] * 51
    with pytest.raises(approval_center.ApprovalCenterError, match="100"):
        approval_center.save_draft(approval_center.REQUEST_DIRECT_PURCHASE, bad, store=MemoryStore())



def test_frappe_source_resolution_allows_only_custom_purchaser_read(monkeypatch):
    source = SimpleNamespace(name="SRC-1", request_type=approval_center.REQUEST_PROCUREMENT)
    monkeypatch.setattr(approval_center.frappe, "get_doc", lambda *_args: source)
    monkeypatch.setattr(approval_center.frappe, "has_permission", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(approval_center.frappe, "session", SimpleNamespace(user="buyer@example.com"))
    from rayher_hr_payroll import oa_access
    monkeypatch.setattr(
        oa_access,
        "oa_request_has_permission",
        lambda doc, ptype=None, user=None: True if user == "buyer@example.com" else False,
    )

    assert approval_center.FrappeApprovalCenterStore().resolve_source("SRC-1") is source
    approval_center.frappe.session.user = "other@example.com"
    with pytest.raises(approval_center.ApprovalCenterError, match="无权"):
        approval_center.FrappeApprovalCenterStore().resolve_source("SRC-1")


def test_procurement_payment_source_must_be_completed_procurement_and_is_snapshotted():
    store = MemoryStore()
    store.sources["SRC-1"] = {
        "name": "SRC-1", "request_type": approval_center.REQUEST_PROCUREMENT,
        "workflow_status": "待审批", "currency": "CNY", "approved_amount": 100,
        "modified": "2026-08-06 11:00:00", "contract_status": "已生效", "supplier": "SUP-1",
        "business_lines": [
            {"item_name": "A", "quantity": 2, "unit": "个", "unit_price": 20},
            {"item_name": "B", "quantity": 3, "unit": "个", "unit_price": 20},
        ],
        "payment_plan": [{"name": "PLAN-1", "status": "待下推", "payment_stage": "预付款", "percentage": 100, "amount": 100, "trigger_condition": "合同生效", "invoice_requirement": "付款后提供"}],
    }
    payload = payment_payload()
    with pytest.raises(approval_center.ApprovalCenterError, match="已生效"):
        approval_center.save_draft(approval_center.REQUEST_PROCUREMENT_PAYMENT, payload, store=store)
    store.sources["SRC-1"]["workflow_status"] = "已完成"
    store.payment_initiator_allowed = False
    with pytest.raises(approval_center.ApprovalCenterError, match="采购经办人或财务"):
        approval_center.save_draft(
            approval_center.REQUEST_PROCUREMENT_PAYMENT, payload, store=store
        )
    store.payment_initiator_allowed = True
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


def test_request_dashboard_exposes_purchaser_for_payment_source_filtering():
    store = MemoryStore()
    store.rows = [{
        "name": "PROC-1", "request_type": "采购申请", "subject": "采购",
        "workflow_status": "已完成", "amount": 100, "approved_amount": 100,
        "asset_nature": "非固定资产", "purchaser_user": "buyer@example.com",
    }]

    result = approval_center.dashboard("request", store=store)

    assert result["rows"][0]["purchaser_user"] == "buyer@example.com"


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


def test_tail_payment_draft_inherits_source_fulfillment_snapshot():
    store = MemoryStore()
    store.sources["SRC-1"] = {
        "name": "SRC-1", "request_type": approval_center.REQUEST_PROCUREMENT,
        "workflow_status": "已完成", "currency": "CNY", "approved_amount": 100,
        "modified": "2026-08-16 10:00:00", "contract_status": "已生效", "supplier": "SUP-1",
        "business_lines": [{"item_name": "A", "quantity": 5, "unit": "个", "unit_price": 20}],
        "payment_plan": [{"name": "PLAN-1", "status": "待下推", "payment_stage": "尾款", "percentage": 100, "amount": 100, "trigger_condition": "验收通过", "invoice_requirement": "付款后提供"}],
        "received_quantity": 5, "arrival_status": "全部到货",
        "arrival_date": "2026-08-16", "inspection_status": "验收通过",
        "inspection_failure_reason": "", "exception_direction": "",
        "followup_status": "", "prepayment_writeoff_status": "无需核销",
    }

    result = approval_center.save_draft(
        approval_center.REQUEST_PROCUREMENT_PAYMENT,
        payment_payload(payment_stage="尾款", prepayment_percentage=0),
        store=store,
    )

    assert result.received_quantity == Decimal("5.0000")
    assert result.arrival_status == "全部到货"
    assert result.arrival_date == "2026-08-16"
    assert result.inspection_status == "验收通过"


def test_direct_purchase_method_and_procurement_payment_fields_are_separate():
    direct_store = MemoryStore()
    direct_store.projects["PRJ-1"] = {"name": "PRJ-1", "project_owner": "owner@example.com", "project_owner_name": "项目主管"}
    direct = approval_center.save_draft(
        approval_center.REQUEST_DIRECT_PURCHASE,
        {
            **valid_payload(), "purchase_method": "京东购买",
            "expected_delivery_date": "2026-09-10", "project": "PRJ-1",
        },
        store=direct_store,
    )
    assert direct.purchase_method == "京东购买"
    assert direct.project == "PRJ-1"
    assert direct.project_owner == "owner@example.com"
    assert direct.business_lines == []
    assert direct.direct_purchase_lines[0]["item_name"] == "芯片"

    store = MemoryStore()
    store.sources["SRC-1"] = {
        "name": "SRC-1", "request_type": approval_center.REQUEST_PROCUREMENT,
        "workflow_status": "已完成", "currency": "CNY", "approved_amount": 100,
        "modified": "2026-08-15 10:00:00", "contract_status": "已生效", "supplier": "SUP-1",
        "business_lines": [{"item_name": "A", "quantity": 1, "unit": "个", "unit_price": 100}],
        "payment_plan": [{"name": "PLAN-1", "status": "待下推", "payment_stage": "预付款", "percentage": 30, "amount": 100, "trigger_condition": "合同生效", "invoice_requirement": "付款后提供"}],
    }
    payment = approval_center.save_draft(
        approval_center.REQUEST_PROCUREMENT_PAYMENT, payment_payload(), store=store
    )
    assert payment.supplier == "SUP-1"
    assert payment.payment_stage == "预付款"
    assert payment.prepayment_percentage == 30


def test_direct_purchase_does_not_require_procurement_material_fields():
    store = MemoryStore()
    result = approval_center.save_draft(
        approval_center.REQUEST_DIRECT_PURCHASE,
        {
            **valid_payload(),
            "business_lines": [{
                "item_name": "办公用品",
                "quantity": 2,
                "unit": "盒",
                "unit_price": 0,
                "category_code": "",
                "brand": "",
            }],
            "purchase_method": "京东购买",
            "expected_delivery_date": "2026-09-10",
        },
        store=store,
    )
    assert result.business_lines == []
    assert result.direct_purchase_lines[0]["item_name"] == "办公用品"
    assert "brand" not in result.direct_purchase_lines[0]


def test_payment_dashboard_has_fixed_asset_categories_and_real_prepayment_risk_drilldowns():
    store = MemoryStore()
    store.rows = [
        {
            "name": "PAY-FIXED-OVERDUE", "request_type": approval_center.REQUEST_PROCUREMENT_PAYMENT,
            "subject": "生产设备预付款", "workflow_status": "已付款", "business_status": "待到货",
            "amount": 100, "approved_amount": 0, "asset_nature": "固定资产",
            "fixed_asset_category": "生产设备、生产工具及器具", "payment_stage": "预付款",
            "prepayment_percentage": 100, "expected_arrival_date": "2000-01-01", "arrival_status": "未到货",
            "inspection_status": "未验收", "prepayment_writeoff_status": "待核销", "owner": "a", "modified": "now",
        },
        {
            "name": "PAY-NONFIXED-INSPECT", "request_type": approval_center.REQUEST_PROCUREMENT_PAYMENT,
            "subject": "材料到货", "workflow_status": "已付款", "business_status": "待验收",
            "amount": 60, "approved_amount": 0, "asset_nature": "非固定资产", "fixed_asset_category": "",
            "payment_stage": "预付款", "prepayment_percentage": 50, "expected_arrival_date": "2099-01-01",
            "arrival_status": "全部到货", "inspection_status": "待验收", "prepayment_writeoff_status": "无需核销",
            "owner": "a", "modified": "now",
        },
        {
            "name": "PAY-FIXED-REJECT", "request_type": approval_center.REQUEST_PROCUREMENT_PAYMENT,
            "subject": "电子设备", "workflow_status": "已付款", "business_status": "换货中",
            "amount": 40, "approved_amount": 0, "asset_nature": "固定资产",
            "fixed_asset_category": "电子设备、研发专用设备、仪器仪表", "payment_stage": "全额付款",
            "prepayment_percentage": 0, "arrival_status": "全部到货", "inspection_status": "验收不合格",
            "prepayment_writeoff_status": "无需核销", "owner": "a", "modified": "now",
        },
    ]

    result = approval_center.dashboard("payment", store=store)

    assert result["asset_summary"]["fixed_asset"] == {
        "label": "固定资产", "count": 2, "applied_amount": Decimal("140.00"),
        "names": ["PAY-FIXED-OVERDUE", "PAY-FIXED-REJECT"],
    }
    assert result["asset_summary"]["non_fixed_asset"]["names"] == ["PAY-NONFIXED-INSPECT"]
    categories = {row["label"]: row for row in result["asset_summary"]["categories"]}
    assert categories["生产设备、生产工具及器具"]["names"] == ["PAY-FIXED-OVERDUE"]
    assert result["prepayment_risk_summary"]["pending_arrival"]["names"] == ["PAY-FIXED-OVERDUE"]
    assert result["prepayment_risk_summary"]["pending_inspection"]["names"] == ["PAY-NONFIXED-INSPECT"]
    assert result["prepayment_risk_summary"]["inspection_rejected"]["names"] == ["PAY-FIXED-REJECT"]
    assert result["prepayment_risk_summary"]["pending_writeoff"]["names"] == ["PAY-FIXED-OVERDUE"]
    assert result["prepayment_risk_summary"]["overdue_full_prepayment"]["names"] == ["PAY-FIXED-OVERDUE"]



def test_payment_dashboard_uses_payment_scoped_ledger_amounts():
    store = MemoryStore()
    store.rows = [
        {
            "name": "PAY-PAID", "request_type": approval_center.REQUEST_PROCUREMENT_PAYMENT,
            "subject": "已付款", "workflow_status": "已付款", "business_status": "待到货",
            "amount": 50, "approved_amount": 0, "asset_nature": "非固定资产",
            "fixed_asset_category": "", "source_request": "SRC-1", "owner": "a", "modified": "now",
        },
        {
            "name": "PAY-RESERVED", "request_type": approval_center.REQUEST_PROCUREMENT_PAYMENT,
            "subject": "待审批", "workflow_status": "待审批", "business_status": "待审批",
            "amount": 50, "approved_amount": 0, "asset_nature": "非固定资产",
            "fixed_asset_category": "", "source_request": "SRC-2", "owner": "a", "modified": "now",
        },
    ]
    store.payment_balances = {
        "PAY-PAID": {
            "approved_amount": Decimal("50"), "reserved_amount": Decimal("0"),
            "paid_amount": Decimal("50"), "available_amount": Decimal("0"),
        },
        "PAY-RESERVED": {
            "approved_amount": Decimal("0"), "reserved_amount": Decimal("50"),
            "paid_amount": Decimal("0"), "available_amount": Decimal("0"),
        },
    }

    result = approval_center.dashboard("payment", store=store)

    assert result["summary"] == {
        "applied_amount": Decimal("100.00"),
        "approved_amount": Decimal("50.00"),
        "reserved_amount": Decimal("50.00"),
        "paid_amount": Decimal("50.00"),
        "available_amount": Decimal("0.00"),
    }
    by_name = {row["name"]: row for row in result["rows"]}
    assert by_name["PAY-PAID"]["paid_amount"] == Decimal("50.00")
    assert by_name["PAY-RESERVED"]["reserved_amount"] == Decimal("50.00")
