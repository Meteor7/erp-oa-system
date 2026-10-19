"""PR #79 审查（采购 + PMC / 生产主管不看金额）：
PMC、生产主管（procurement_chain._amounts_hidden）从看板能点到的地方都拿不到金额——演示员工116草稿正文 / 演示员工116快照、
物料看板的已付 / PO 总额 / 付款单金额、首页采购概览的金额也一样；采购经理等照常。隐藏的金额是 None，不是 0，
报没报价、付清没有这些非金额判断由服务端另给标志。采购申请列表「我负责的项目」按项目负责人在服务端取全部。
"""
import json
from types import SimpleNamespace as NS

import pytest

from rayher_hr_payroll.api import procurement_chain as pc

PMC = (("pmc",), ("Employee", "Purchase User"))
PRODUCTION = (("production_asset_owner",), ("Employee",))
MANAGER = (("procurement_manager",), ("Employee", "Purchase Manager"))


def chain_env(monkeypatch, positions, roles):
    holders = {key: ({"u@example.com"} if key in positions else set()) for key in
               ("pmc", "production_asset_owner", *pc.MONEY_POSITIONS, "vice_manager")}
    monkeypatch.setattr(pc, "_user", lambda: "u@example.com")
    monkeypatch.setattr(pc, "_roles", lambda: set(roles))
    monkeypatch.setattr(pc, "position_users", lambda *keys: {user for key in keys for user in holders.get(key, set())})
    monkeypatch.setattr(pc, "_request_memo", lambda key, fn: fn())
    monkeypatch.setattr(pc, "_can_seal_contract", lambda doc: False)
    return pc


def make_po(paid=1000.0, row_paid=(300.0, 700.0), status="付款中"):
    draft = "示例企业032有限公司采购演示员工116\nPO：PO-1\n供应商：甲\n演示员工116金额：CNY 1,000.00\n演示员工116交期：2026-10-20\n付款方式：预付"
    snapshot = json.dumps({"po": "PO-1", "supplier": "甲", "total_amount": 1000.0, "currency": "CNY"}, ensure_ascii=False)
    lines = [pc._Row(name="L1", item_name="镜片", quantity=2, received_quantity=2, inspection_status="已通过",
                     unit_price=500.0, amount=1000.0, source_request="OA-1")]
    plan = [pc._Row(name="P1", installment_no=1, percentage=30, amount=300.0, paid_amount=row_paid[0], status="已付款"),
            pc._Row(name="P2", installment_no=2, percentage=70, amount=700.0, paid_amount=row_paid[1],
                    status="已付款" if row_paid[1] >= 700 else "审批通过")]
    return pc._Row(name="PO-1", status=status, supplier="甲", contract_status="已生效", currency="CNY", total_amount=1000.0,
                   paid_amount=paid, payment_status="已付款" if paid >= 1000 else "部分付款",
                   contract_draft_content=draft, contract_snapshot=snapshot, lines=lines, payment_plan=plan)


# ---------------------------------------------------------------- #79-1 演示员工116草稿 / 演示员工116快照
@pytest.mark.parametrize("who", [PMC, PRODUCTION])
def test_79_1_po_summary_withholds_contract_text_and_snapshot_when_amounts_hidden(monkeypatch, who):
    chain_env(monkeypatch, *who)
    result = pc._po_summary(make_po(), steps=[])
    assert result["amounts_hidden"] == 1
    assert result["contract_draft_content"] is None and result["contract_snapshot"] is None
    text = json.dumps(result, ensure_ascii=False, default=str)
    assert "演示员工116金额" not in text and "1,000.00" not in text and "1000.0" not in text
    assert result["total_amount"] is None and result["paid_amount"] is None and result["outstanding_amount"] is None
    assert result["lines"][0]["amount"] is None and result["lines"][0]["unit_price"] is None
    assert result["payment_plan"][0]["amount"] is None and result["payment_plan"][0]["paid_amount"] is None
    # 非金额的东西不动
    assert result["lines"][0]["quantity"] == 2 and result["payment_plan"][1]["percentage"] == 70
    assert result["contract_status"] == "已生效" and result["payment_status"] == "已付款"


def test_79_1_procurement_manager_keeps_contract_text_and_amounts(monkeypatch):
    chain_env(monkeypatch, *MANAGER)
    result = pc._po_summary(make_po(), steps=[])
    assert "amounts_hidden" not in result
    assert "演示员工116金额：CNY 1,000.00" in result["contract_draft_content"]
    assert json.loads(result["contract_snapshot"])["total_amount"] == 1000.0
    assert result["total_amount"] == 1000.0 and result["lines"][0]["amount"] == 1000.0


def test_79_1_list_purchase_orders_sends_no_contract_money_to_pmc(monkeypatch):
    chain_env(monkeypatch, *PMC)
    monkeypatch.setattr(pc, "_require_gate", lambda *a: None)
    monkeypatch.setattr(pc, "_require_po_view", lambda: None)
    monkeypatch.setattr(pc, "_load_pos", lambda limit, exclude_statuses=(), status=None: [make_po()])
    monkeypatch.setattr(pc, "_approval_steps_bulk", lambda names: {})
    rows = getattr(pc.list_purchase_orders, "__wrapped__", pc.list_purchase_orders)()
    assert rows[0]["contract_draft_content"] is None and rows[0]["contract_snapshot"] is None
    assert "演示员工116金额" not in json.dumps(rows, ensure_ascii=False, default=str)


def test_79_1_every_money_carrying_po_field_is_in_money_keys():
    # PO / 物料行 / 付款期次 / 报价上所有带钱的字段
    for key in ("total_amount", "paid_amount", "outstanding_amount", "amount", "unit_price", "total_price",
                "selected_unit_price", "selected_total", "package_total", "payment_plan_json",
                "contract_draft_content", "contract_snapshot", "price_snapshot"):
        assert key in pc.MONEY_KEYS, key


# ---------------------------------------------------------------- #79-3 付清标志
def test_79_3_paid_full_survives_hiding_and_matches_close_po(monkeypatch):
    chain_env(monkeypatch, *PMC)
    paid = pc._po_summary(make_po(), steps=[])
    assert paid["paid_full"] == 1 and [row["paid_full"] for row in paid["payment_plan"]] == [1, 1]
    partial = pc._po_summary(make_po(paid=300.0, row_paid=(300.0, 0.0)), steps=[])
    assert partial["paid_full"] == 0 and [row["paid_full"] for row in partial["payment_plan"]] == [1, 0]
    # 表头付清了、期次没付清：和 close_po 一样算没付清
    mixed = pc._po_summary(make_po(paid=1000.0, row_paid=(300.0, 0.0)), steps=[])
    assert mixed["paid_full"] == 0


# ---------------------------------------------------------------- #79-2 报价标志
def test_79_2_supplier_prices_carry_a_quoted_flag_that_survives_hiding(monkeypatch):
    chain_env(monkeypatch, *PMC)
    doc = NS(name="PA-1", lines=[NS(name="A1", material_serial="M1", selected_supplier="", selected_quote=""),
                                 NS(name="A2", material_serial="M2", selected_supplier="", selected_quote="")])
    quotes = [NS(name="Q1", supplier="甲", price_line="A1", unit_price=12.5, total_price=25.0, delivery_date="2026-10-20",
                 payment_method="预付", currency="CNY", tax_rate=13, contract_entity="", note="", is_recommended=1,
                 payment_plan_json='[{"amount": 25.0, "percentage": 100}]')]
    groups = pc._supplier_comparisons(doc, quotes)
    assert groups[0]["prices"][0]["quoted"] == 1
    cleaned = pc._for_viewer({"supplier_comparisons": groups, "quotes": quotes and [dict(vars(quotes[0]))]})
    price = cleaned["supplier_comparisons"][0]["prices"][0]
    assert price["quoted"] == 1 and price["delivery_date"] == "2026-10-20"
    assert price["unit_price"] is None and price["total_price"] is None
    assert cleaned["supplier_comparisons"][0]["package_total"] is None
    assert cleaned["supplier_comparisons"][0]["payment_plan"][0] == {"amount": None, "percentage": 100}


# ---------------------------------------------------------------- #79-4 物料看板
def board_row():
    return {"name": "B1", "quantity": 4.0, "payment_status": "部分付款", "paid_amount": 300.0, "po_total_amount": 1000.0,
            "payment_requests": [{"name": "PAY-1", "stage": "预付款", "status": "已付款", "amount": 300.0}]}


def run_board_list(monkeypatch):
    from rayher_hr_payroll.api import material_progress as board

    monkeypatch.setattr(board, "_board_user", lambda: "u@example.com")
    monkeypatch.setattr(board.frappe.utils, "today", lambda: "2026-10-13", raising=False)

    def sql(query, params=None, as_dict=False):
        if query.startswith("SELECT COUNT(*)"):
            return [[1]]
        if query.startswith("SELECT b.name"):
            return [NS(name="B1")]
        return []
    monkeypatch.setattr(board.frappe, "db", NS(sql=sql), raising=False)
    monkeypatch.setattr(board.frappe, "get_doc", lambda doctype, name: NS(name=name, source_request="OA-1", source_line="L1"), raising=False)
    monkeypatch.setattr(board, "_batch_chain_context", lambda boards: ({("OA-1", "L1"): {}}, {"OA-1": NS()}, {}, {}))
    monkeypatch.setattr(board, "_serialize", lambda b, **kw: board_row())
    raw = getattr(board.list_material_progress, "__wrapped__", board.list_material_progress)
    return raw()["items"]


@pytest.mark.parametrize("who", [PMC, PRODUCTION])
def test_79_4_material_board_hides_paid_total_and_payment_amounts(monkeypatch, who):
    chain_env(monkeypatch, *who)
    row = run_board_list(monkeypatch)[0]
    assert row["amounts_hidden"] == 1
    assert row["paid_amount"] is None and row["po_total_amount"] is None and row["payment_requests"][0]["amount"] is None
    assert row["payment_status"] == "部分付款" and row["quantity"] == 4.0 and row["payment_requests"][0]["status"] == "已付款"


def test_79_4_material_board_keeps_amounts_for_procurement_manager(monkeypatch):
    chain_env(monkeypatch, *MANAGER)
    row = run_board_list(monkeypatch)[0]
    assert "amounts_hidden" not in row
    assert row["paid_amount"] == 300.0 and row["po_total_amount"] == 1000.0 and row["payment_requests"][0]["amount"] == 300.0


def test_79_4_board_edit_and_cancel_responses_are_cleaned_too():
    import inspect

    from rayher_hr_payroll.api import material_progress as board

    for fn in (board.update_material_progress, board.cancel_material_progress):
        source = inspect.getsource(getattr(fn, "__wrapped__", fn))
        assert "return _serialize(board)" not in source and "return _for_viewer(_serialize(board))" in source


# ---------------------------------------------------------------- #79-3 首页采购概览
def overview_env(monkeypatch, hidden, roles):
    from rayher_hr_payroll import approval_center
    from rayher_hr_payroll.api import dashboard_entry as de

    monkeypatch.setattr(pc, "_amounts_hidden", lambda: hidden)
    monkeypatch.setattr(de.frappe, "session", NS(user="u@example.com"), raising=False)
    monkeypatch.setattr(de.frappe, "get_roles", lambda user=None: list(roles), raising=False)
    monkeypatch.setattr(de, "position_users", lambda *keys: set())
    monkeypatch.setattr(approval_center, "dashboard", lambda kind, limit=500: {"rows": []})
    monkeypatch.setattr(pc, "list_payment_work_items", lambda limit=1000: [
        {"po": "PO-1", "payment_plan_row": "P1", "work_status": "待验收", "amount": None, "paid_amount": None,
         "blockers": ["本期要求验收通过"], "installment_name": "尾款", "planned_date": ""}])
    return de


def test_79_3_pmc_with_purchase_user_role_gets_no_financial_overview(monkeypatch):
    de = overview_env(monkeypatch, True, ("Employee", "Purchase User"))
    assert de._can_view_procurement_financial() is False
    result = de._procurement_overview()
    assert result["can_view_financial"] is False and result["amounts"] == {} and result["alerts"] == []
    assert all(card["label"] != "可提交付款" for card in result["cards"])


def test_79_3_purchase_user_who_is_not_pmc_still_gets_amounts(monkeypatch):
    de = overview_env(monkeypatch, False, ("Employee", "Purchase User"))
    assert de._can_view_procurement_financial() is True
    assert set(de._procurement_overview()["amounts"]) == {"po_total", "paid", "unpaid", "payable"}


# ---------------------------------------------------------------- #79-5 我负责的项目
def owned_env(monkeypatch, rows):
    from rayher_hr_payroll.api import procurement_owned as owned
    from rayher_hr_payroll.dashboard import projects

    asked = []
    monkeypatch.setattr(owned.frappe, "session", NS(user="boss@example.com"), raising=False)
    monkeypatch.setattr(owned.frappe, "db", NS(get_value=lambda *a, **k: "EMP-BOSS"), raising=False)
    monkeypatch.setattr(owned, "require_request_type_access", lambda request_type: asked.append(("gate", request_type)))

    def load(ctx, request_types=projects.REQUEST_TYPES):
        asked.append(("load", ctx.user, ctx.employee, tuple(request_types)))
        return rows
    monkeypatch.setattr(projects, "_load_requests", load)
    return getattr(owned.list_owned_requests, "__wrapped__", owned.list_owned_requests), asked


def test_79_5_owned_tab_lists_every_owned_request_not_just_the_latest_200(monkeypatch):
    others = [{"name": f"OA-{i}", "request_type": "采购申请", "project_owner": "boss@example.com", "owner": "a@example.com",
               "employee": "EMP-A", "workflow_status": "已完成"} for i in range(250)]
    noise = [
        {"name": "OWN", "request_type": "采购申请", "project_owner": "boss@example.com", "owner": "boss@example.com", "employee": "EMP-BOSS", "workflow_status": "已完成"},
        {"name": "OWN2", "request_type": "采购申请", "project_owner": "boss@example.com", "owner": "x@example.com", "employee": "EMP-BOSS", "workflow_status": "待审批"},
        {"name": "DRAFT", "request_type": "采购申请", "project_owner": "boss@example.com", "owner": "a@example.com", "employee": "EMP-A", "workflow_status": "草稿"},
        {"name": "OTHER", "request_type": "采购申请", "project_owner": "z@example.com", "owner": "a@example.com", "employee": "EMP-A", "workflow_status": "已完成"},
    ]
    fn, asked = owned_env(monkeypatch, others + noise)
    rows = fn("采购申请")
    assert len(rows) == 250 and {row["name"] for row in rows} == {f"OA-{i}" for i in range(250)}
    assert ("gate", "采购申请") in asked and ("load", "boss@example.com", "EMP-BOSS", ("采购申请",)) in asked


def test_79_5_owned_tab_rejects_other_request_types(monkeypatch):
    import frappe

    def throw(message, exc=None):
        raise ValueError(message)
    monkeypatch.setattr(frappe, "throw", throw)
    fn, asked = owned_env(monkeypatch, [])
    with pytest.raises(ValueError, match="不支持"):
        fn("出差申请")
    assert asked == []


def test_79_5_load_requests_only_queries_the_wanted_type(monkeypatch):
    import frappe

    from rayher_hr_payroll import oa_feature_gate, procurement_summary_cache
    from rayher_hr_payroll.dashboard import projects

    seen = {}
    monkeypatch.setattr(oa_feature_gate, "visible_request_types", lambda types, user=None: list(types))
    monkeypatch.setattr(procurement_summary_cache, "prepare_summaries", lambda docs, fn: __import__("contextlib").nullcontext())

    def get_all(doctype, filters=None, **kw):
        seen["filters"] = filters
        return []
    monkeypatch.setattr(frappe, "get_all", get_all, raising=False)
    assert projects._load_requests(NS(user="boss@example.com"), ("采购申请",)) == []
    assert seen["filters"]["request_type"] == ["in", ["采购申请"]] and seen["filters"]["project_owner"] == "boss@example.com"
    projects._load_requests(NS(user="boss@example.com"))
    assert seen["filters"]["request_type"] == ["in", ["采购申请", "购买申请"]]
