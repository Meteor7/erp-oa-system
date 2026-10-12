"""看板「财务、费用、付款、审批卡点」块（dashboard/money.py）。

大多数测试把底层数据直接放进 ctx 的备忘（`ctx._memo["money.*"]`），只检查块怎么用这些数据、谁能看；
`_stuck` 和 `_step_buckets` 两个读库的函数用假的 frappe.get_all 单独测。
"""
import pytest

from rayher_hr_payroll.dashboard import core, layout, money

MONEY_KEYS = {key for key, item in core.REGISTRY.items() if item.fn.__module__ == money.__name__ and item.kind != "drill"}
DRILL_KEYS = {key for key, item in core.REGISTRY.items() if item.fn.__module__ == money.__name__ and item.kind == "drill"}
# 明细清单 -> 它背后的卡片 / 块：看得到卡片的人才看得到清单，不多也不少
DRILL_OF = {"drill.cost.total": "cost.total", "drill.cost.po": "cost.po", "drill.cost.expense": "cost.expense", "drill.cost.projects": "block.cost_projects",
            "drill.pay.in_approval": "pay.in_approval", "drill.approval.stuck": "approval.stuck", "drill.invoice.review": "invoice.review"}


def make_ctx(roles=("Employee",), positions=(), **kw):
    base = dict(user="u@example.com", roles=frozenset(roles), positions=frozenset(positions), period="2026-10", today="2026-10-09")
    base.update(kw)
    return core.Ctx(**base)


def run(key, ctx, **memo):
    """像 core.build_tab 那样跑一个块：先看 visible，再调函数；出错的块会记在 errors 里，这里直接要求没有。"""
    ctx._memo.update(memo)
    errors = []
    out = core._run(core.REGISTRY[key], ctx, errors)
    assert errors == [], errors
    return out


# ---------------------------------------------------------------- 假数据
def overview(**kw):
    months = ("11月", "12月", "1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月")
    totals = (100, 200, 300, 400, 500, 600, 3520000, 3720000, 3800000, 3670000, 3940000, 4182000)
    trend = [{"label": label, "rd": 0, "po": 0, "expense": 0, "total": total, "preview": label == "10月"}
             for label, total in zip(months, totals)]
    base = {
        "visible": True, "scope": "month", "year": 2026, "month": 10,
        "totals": {"rd": 2864000.0, "po": 982000.0, "expense": 336000.0, "total": 4182000.0},
        "deltas": {"rd": 5.0, "po": 12.4, "expense": -4.1, "total": 6.2},
        "projects": [
            {"project": "P1", "label": "ACONCA 7961", "total": 1126000.0}, {"project": "P2", "label": "RD14 视觉模组", "total": 863000.0},
            {"project": "P3", "label": "光学平台", "total": 618000.0}, {"project": "__none__", "label": "非项目", "total": 524000.0},
            {"project": "P4", "label": "项目四", "total": 300000.0}, {"project": "P5", "label": "项目五", "total": 200000.0},
            {"project": "P6", "label": "项目六", "total": 100000.0},
        ],
        "trend": trend, "preview": True, "preview_months": ["2026-10"],
    }
    base.update(kw)
    return base


def allocation(**kw):
    base = {"has_data": True, "preview": True, "finalized": False, "status": "预览",
            "capitalized": 1642000.0, "expensed": 1089000.0, "unknown": 133000.0}
    base.update(kw)
    return base


def claim_row(name, kind="报销单", status="待审批", waited=0, amount=0, paid_on=None, step=1):
    return {"name": name, "request_type": kind, "workflow_status": status, "waited_days": waited, "amount": amount,
            "paid_on": paid_on, "current_step_index": step}


def queue_row(name, kind="报销单", amount=0.0, urgency="一般", waited=0, status="待付款"):
    return {"name": name, "request_type": kind, "amount": amount, "urgency": urgency, "waited_days": waited, "status": status}


def claims(rows=(), queue=(), by_account=(), claim_paid=0.0, payment_paid=0.0):
    return {"rows": list(rows), "board": {
        "summary": {"reimbursement_paid": claim_paid, "payment_paid": payment_paid},
        "cashier_queue": list(queue), "by_account": [list(item) for item in by_account]}}


def work_item(status, amount, po="PO-1", no=1, request="", supplier="", stage="", paid=0.0, step=0):
    return {"po": po, "installment_no": no, "work_status": status, "amount": amount, "paid_amount": paid,
            "payment_request": request, "supplier": supplier, "payment_stage": stage,
            "payment_request_summary": {"current_step_index": step} if request else {}}


def purchase(items=(), waits=None, paid_month=()):
    return {"items": list(items), "waits": waits or {}, "paid_month": list(paid_month)}


# 付款相关块共用的一组数据
PAY_CLAIMS = claims(
    rows=[claim_row("OA-1", waited=2, amount=3000, step=1),
          claim_row("OA-8", status="已付款", paid_on="2026-10-03", amount=1000),
          claim_row("OA-9", kind="付款单", status="已付款", paid_on="2026-10-04", amount=2000),
          claim_row("OA-7", status="已付款", paid_on="2026-09-28", amount=500)],
    queue=[queue_row("OA-2", amount=1000.0, urgency="加急", waited=0), queue_row("OA-3", kind="付款单", amount=2000.0, waited=5),
           queue_row("OA-4", kind="付款单", amount=800.0, status="待核验", waited=9)],
    by_account=[("差旅费 / 机票", 142000.0), ("招待费", 68000.0), ("办公费", 51000.0), ("其他", 20000.0)],
    claim_paid=1000.0, payment_paid=2000.0)
PAY_PURCHASE = purchase(
    items=[work_item("待实际付款", 5000.0, request="OA-P1", no=1, supplier=" 光学元件 ", stage="到货款", step=4),
           work_item("付款审批中", 7000.0, request="OA-P2", no=2, supplier="光学元件", stage="尾款", step=3),
           work_item("可提交付款审批", 3000.0, no=3, supplier="精密机加工", stage="预付款"),
           work_item("待合同生效", 9000.0, po="PO-2", supplier="电子元器件", stage="预付款"),
           work_item("已付款", 4000.0, po="PO-3", supplier="包装材料", stage="预付款", paid=4000.0)],
    waits={"OA-P1": 4, "OA-P2": 1}, paid_month=[3000.0, 2000.0])
PAY_BUCKETS = {"OA-1": "出纳", "OA-P2": "总经理"}


def pay_memo(**kw):
    base = {"money.claims": PAY_CLAIMS, "money.purchase": PAY_PURCHASE, "money.step_buckets": PAY_BUCKETS, "money.po_pay_view": True}
    base.update(kw)
    return base


FINANCE = dict(roles=("Accounts User",), positions=("finance_manager",))


# ---------------------------------------------------------------- 谁能看
ALWAYS = {"pay.todo", "claim.todo", "me.processed", "block.aging"}
COST = {"cost.total", "cost.rd", "cost.po", "cost.expense", "cost.rd_pending", "alloc.status", "block.cost_mix", "block.cost_trend", "block.cost_projects"}
ALLOC = {"cost.cap", "cost.unknown", "alert.alloc_unknown", "alert.alloc_preview", "block.alloc_mix"}
BOARD = {"pay.unpaid", "pay.waiting", "pay.in_approval", "pay.paid_month", "pay.cashier_queue", "approval.stuck", "alert.pay_waiting",
         "alert.stuck", "block.pay_wait_dist", "block.pay_steps", "block.claim_category", "block.pay_trend"}
SUPPLIER = {"block.pay_suppliers", "block.pay_stage"}
INVOICE = {"invoice.review", "alert.invoice", "block.invoice_status"}
LABOR = {"block.labor_cost"}


def visible_keys(ctx, po_view=False):
    ctx._memo.update({"money.invoice_open": True, "money.po_pay_view": po_view})
    return {key for key in MONEY_KEYS if core.REGISTRY[key].visible is None or core.REGISTRY[key].visible(ctx)}


def test_every_block_is_classified():
    assert ALWAYS | COST | ALLOC | BOARD | SUPPLIER | INVOICE | LABOR == MONEY_KEYS
    assert len(MONEY_KEYS) == 36


def test_every_detail_list_is_visible_to_exactly_the_people_who_see_its_card():
    assert set(DRILL_OF) == DRILL_KEYS
    for drill_key, card_key in DRILL_OF.items():
        assert core.REGISTRY[drill_key].visible is core.REGISTRY[card_key].visible, drill_key


@pytest.mark.parametrize("name, ctx_args, po_view, expected", [
    ("普通员工", dict(), False, ALWAYS),
    ("部门主管", dict(roles=("Employee", "Department Manager")), True, ALWAYS),
    # PMC 有 Purchase User：现有的 PO 判断会把他当财务，这里的付款/费用块一个都不能给
    ("PMC", dict(roles=("Employee", "Purchase User"), positions=("pmc",)), True, ALWAYS),
    ("采购经理", dict(roles=("Employee", "Purchase Manager"), positions=("procurement_manager",)), True, ALWAYS),
    ("人事经理", dict(roles=("HR Manager", "HR User")), False, ALWAYS | LABOR),
    ("副总：能看费用和付款，看不到分摊明细和发票", dict(positions=("vice_manager",)), True,
     ALWAYS | COST | BOARD | SUPPLIER | LABOR),
    ("总经理没有 PO 查看权时不给采购付款块", dict(positions=("general_manager",)), False, ALWAYS | COST | BOARD | LABOR),
    ("出纳（只有岗位）：付款看板范围，没有费用概览", dict(positions=("finance_auditor",)), True, ALWAYS | BOARD | SUPPLIER),
    ("财务主管 + Accounts User：除人力成本外全有", FINANCE, True, ALWAYS | COST | ALLOC | BOARD | SUPPLIER | INVOICE),
    ("总账会计 (Accounts User)", dict(roles=("Accounts User",), positions=("finance_accountant",)), False,
     ALWAYS | COST | ALLOC | BOARD | INVOICE),
    ("系统管理员", dict(roles=("System Manager",)), True, MONEY_KEYS),
])
def test_who_sees_what(name, ctx_args, po_view, expected):
    assert visible_keys(make_ctx(**ctx_args), po_view) == expected, name


def test_hidden_blocks_never_touch_the_data_layer():
    """没权限的人，底层函数一个都不会被调用（备忘是空的：一旦调用就会去 import 接口并报错）。"""
    ctx = make_ctx(roles=("Employee", "Purchase User"), positions=("pmc",))
    ctx._memo["money.po_pay_view"] = True
    ctx._memo["money.invoice_open"] = True
    errors = []
    for key in sorted(MONEY_KEYS - ALWAYS):
        assert core._run(core.REGISTRY[key], ctx, errors) is None, key
    assert errors == []
    assert set(ctx._memo) == {"money.po_pay_view", "money.invoice_open"}


def test_board_scope_follows_the_expense_board_rule():
    assert money._board_all(make_ctx(user="admin@staff.example.invalid"))
    assert money._board_all(make_ctx(roles=("Rayher Business Executive",)))
    assert not money._board_all(make_ctx(roles=("Department Manager", "Purchase Manager"), positions=("procurement_manager", "pmc")))


def test_layout_and_registry_agree():
    layout_keys = layout.all_block_keys()
    assert MONEY_KEYS <= layout_keys, MONEY_KEYS - layout_keys
    kinds = {"kpis": "kpi", "alerts": "alert", "blocks": "block"}
    for profile in layout.LAYOUTS.values():
        for tab in profile["tabs"]:
            for bucket, kind in kinds.items():
                for key in tab[bucket]:
                    if key in MONEY_KEYS:
                        assert core.REGISTRY[key].kind == kind, key


def test_new_targets_exist_and_match_the_pages_that_read_them():
    targets = core.load_targets()
    assert targets["claim.review"]["query"] == {"view": "list", "scope": "all", "bucket": "review"}
    assert targets["payment.review"]["path"] == "/approval/payment"
    assert targets["payment.stuck"]["query"] == {"view": "list", "scope": "all", "bucket": "review", "long": "1"}


# ---------------------------------------------------------------- 费用
def test_cost_cards_show_amounts_and_change_against_last_month():
    ctx = make_ctx(**FINANCE)
    memo = {"money.cost_overview": overview()}
    total = run("cost.total", ctx, **memo)
    assert (total["label"], total["value"], total["unit"], total["sub"], total["preview"]) == ("本月费用合计", "418.2", "万", "▲ 6.2% 较上月", True)
    # 合计 = 研发 + 采购 + 报销付款；研发费用汇总页只有研发那一部分，所以合计不直接跳过去，点进去是三部分的明细
    assert total["target"] == {"key": "drill", "params": {"item": "cost.total", "period": "2026-10"}}
    detail = core.get_detail_for(ctx, "cost.total")
    assert [row["cells"][0] for row in detail["rows"]] == ["研发分摊", "采购", "报销付款", "合计"]
    assert [row["cells"][2] for row in detail["rows"]] == ["¥ 286.4 万", "¥ 98.2 万", "¥ 33.6 万", "¥ 418.2 万"]
    assert detail["summary"] == "合计 ¥ 418.2 万" and "（预览，还没定版）" in detail["rows"][0]["cells"][1]
    assert [row["target"] and row["target"]["key"] for row in detail["rows"]] == ["cost.summary", "price.approvals", "board.payment", None]
    rd = run("cost.rd", ctx)
    assert (rd["value"], rd["sub"], rd["preview"]) == ("286.4", "占 68% · ▲ 5% 较上月", True)
    po, expense = run("cost.po", ctx), run("cost.expense", ctx)
    assert (po["value"], po["sub"], po["preview"]) == ("98.2", "▲ 12.4% 较上月", False)
    assert po["target"]["params"] == {"item": "cost.po", "period": "2026-10"} and expense_target(ctx) == {"item": "cost.expense", "period": "2026-10"}
    assert (expense["value"], expense["sub"]) == ("33.6", "▼ 4.1% 较上月")


def expense_target(ctx):
    return run("cost.expense", ctx)["target"]["params"]


def test_cost_blocks_open_the_list_that_adds_up_to_the_block():
    ctx = make_ctx(**FINANCE)
    ctx._memo["money.cost_overview"] = overview()
    mix, trend, projects = run("block.cost_mix", ctx), run("block.cost_trend", ctx), run("block.cost_projects", ctx)
    assert mix["target"]["params"]["item"] == "cost.total" and projects["target"]["params"]["item"] == "cost.projects"
    assert trend["target"] is None      # 六个月的趋势没有一个对得上的页面，不给假跳转
    detail = core.get_detail_for(ctx, "cost.projects")
    assert detail["summary"] == "共 7 个项目，合计 ¥ 373.1 万" and detail["rows"][0]["cells"] == ["ACONCA 7961", "¥ 112.6 万"]


def test_cost_po_and_expense_lists_sum_the_same_lines_the_overview_uses(monkeypatch):
    frappe = pytest.importorskip("frappe")
    ctx = make_ctx(**FINANCE)
    ctx._memo["money.cost_overview"] = overview(totals={"rd": 0, "po": 300.0, "expense": 120.0, "total": 420.0})
    asked = []

    def fake_get_all(doctype, filters=None, **kwargs):
        asked.append(doctype)
        if doctype == "OA Purchase Order":
            return [{"name": "PO-1", "supplier": " 甲 ", "status": "已生效", "creation": "2026-10-03 10:00:00"},
                    {"name": "PO-2", "supplier": "", "status": "草稿", "creation": "2026-10-05 10:00:00"}]
        if doctype == "OA Purchase Order Line":
            return [{"parent": "PO-1", "amount": 100.0}, {"parent": "PO-1", "amount": 50.0}, {"parent": "PO-2", "amount": 150.0}]
        if doctype == "OA Approval Request":
            return [{"name": "R-1", "request_type": "报销单", "subject": "差旅", "employee_name": "演示员工129", "paid_on": "2026-10-02"},
                    {"name": "R-2", "request_type": "付款单", "subject": "", "employee_name": "演示员工146", "paid_on": "2026-10-04"}]
        return [{"parent": "R-1", "total_amount": 80.0, "amount": 70.0}, {"parent": "R-2", "total_amount": None, "amount": 40.0}]

    monkeypatch.setattr(frappe, "get_all", fake_get_all, raising=False)
    po = core.get_detail_for(ctx, "cost.po")
    assert po["summary"] == "共 2 个 PO，合计 ¥ 300" and po["note"] == ""
    assert [row["cells"][:2] for row in po["rows"]] == [["PO-1", "甲"], ["PO-2", "—"]]
    assert po["rows"][0]["target"] == {"key": "price.po", "params": {"po": "PO-1"}}
    expense = core.get_detail_for(ctx, "cost.expense")
    assert expense["summary"] == "共 2 张，合计 ¥ 120"
    assert [row["target"] for row in expense["rows"]] == [{"key": "claim.detail", "params": {"request": "R-1"}}, {"key": "payment.detail", "params": {"request": "R-2"}}]
    # 本期已有研发分摊时，概览里的采购比逐个 PO 加起来少：清单要说明为什么
    ctx2 = make_ctx(**FINANCE)
    ctx2._memo["money.cost_overview"] = overview(totals={"rd": 1000.0, "po": 100.0, "expense": 120.0, "total": 1220.0})
    assert "研发项目的采购包含在研发分摊里" in core.get_detail_for(ctx2, "cost.po")["note"]


def test_cost_card_without_last_month_data_and_other_period_label():
    ctx = make_ctx(**FINANCE, period="2026-09")
    card = run("cost.total", ctx, **{"money.cost_overview": overview(deltas={"total": None, "rd": 0, "po": 0, "expense": 0}, preview=False)})
    assert card["label"] == "9 月费用合计" and card["sub"] == "上月没有可比数据" and card["preview"] is False
    assert run("cost.rd", ctx)["sub"] == "占 68% · 与上月持平"


def test_cost_card_is_left_out_when_the_overview_says_not_visible():
    assert run("cost.total", make_ctx(**FINANCE), **{"money.cost_overview": None}) is None


def test_cost_mix_stack():
    block = run("block.cost_mix", make_ctx(**FINANCE), **{"money.cost_overview": overview()})
    assert [row["label"] for row in block["rows"]] == ["研发分摊", "采购", "报销付款"]
    assert [row["value"] for row in block["rows"]] == ["286.4 万", "98.2 万", "33.6 万"]
    assert [row["pct"] for row in block["rows"]] == [68.5, 23.5, 8.0]
    assert block["sub"] == "本月费用合计 ¥ 418.2 万"
    empty = overview(totals={"rd": 0, "po": 0, "expense": 0, "total": 0})
    block = run("block.cost_mix", make_ctx(**FINANCE), **{"money.cost_overview": empty})
    assert block["rows"] == [] and block["sub"] == "本月还没有费用数据"


def test_cost_trend_is_the_last_six_months_with_the_current_one_marked():
    block = run("block.cost_trend", make_ctx(**FINANCE), **{"money.cost_overview": overview()})
    assert [row["label"] for row in block["rows"]] == ["5月", "6月", "7月", "8月", "9月", "10月"]
    assert [row["last"] for row in block["rows"]] == [False] * 5 + [True]
    assert block["rows"][0]["value"] == "352" and block["rows"][-1]["pct"] == 100.0 and block["rows"][-1]["value"] == "418.2"
    assert "含预览月份" in block["sub"]


def test_cost_projects_top_five_and_the_rest_merged():
    block = run("block.cost_projects", make_ctx(**FINANCE), **{"money.cost_overview": overview()})
    assert [row["label"] for row in block["rows"]] == ["ACONCA 7961", "RD14 视觉模组", "光学平台", "非项目", "项目四", "其他 2 个项目"]
    assert block["rows"][0]["pct"] == 100.0 and block["rows"][-1]["value"] == "30.0"


def test_rd_pending_reads_the_overview_so_leaders_get_it_too():
    leader = make_ctx(positions=("vice_manager",))
    preview = run("cost.rd_pending", leader, **{"money.cost_overview": overview()})
    assert (preview["value"], preview["tone"], preview["preview"], preview["target"]) == ("286.4", "warn", True, None)
    final = run("cost.rd_pending", make_ctx(**FINANCE), **{"money.cost_overview": overview(preview=False)})
    assert (final["sub"], final["tone"], final["preview"]) == ("已定版", "ok", False)
    assert final["target"]["key"] == "allocation"
    none = run("cost.rd_pending", make_ctx(**FINANCE), **{"money.cost_overview": overview(preview=False, totals={"rd": 0, "po": 0, "expense": 0, "total": 0})})
    assert none["sub"] == "本期还没有研发分摊数据"


def test_allocation_cards():
    ctx = make_ctx(**FINANCE)
    memo = {"money.allocation": allocation()}
    cap, unknown = run("cost.cap", ctx, **memo), run("cost.unknown", ctx)
    assert (cap["value"], cap["unit"], cap["sub"], cap["preview"]) == ("164.2", "万", "占研发分摊 57%", True)
    assert (unknown["value"], unknown["tone"], unknown["target"]["key"]) == ("13.3", "hot", "allocation")
    clean = run("cost.unknown", ctx, **{"money.allocation": allocation(unknown=0.0)})
    assert clean["value"] == "0" and clean["tone"] == "ok"
    nothing = run("cost.cap", ctx, **{"money.allocation": allocation(has_data=False, capitalized=0, expensed=0, unknown=0)})
    assert nothing["value"] == "—" and nothing["sub"] == "本期还没有费用导入"


def test_alloc_status_for_finance_and_for_leaders():
    ctx = make_ctx(**FINANCE)
    status = run("alloc.status", ctx, **{"money.allocation": allocation(), "money.cost_overview": overview()})
    assert (status["value"], status["tone"], status["preview"]) == ("预览", "warn", True)
    assert status["sub"] == "10 月 ¥ 286.4 万，未定版，未判定 ¥ 13.3 万"
    final = run("alloc.status", make_ctx(**FINANCE), **{"money.allocation": allocation(preview=False, finalized=True, unknown=0.0, status="已定版")})
    assert (final["value"], final["tone"], final["preview"]) == ("已定版", "ok", False)
    empty = run("alloc.status", make_ctx(**FINANCE), **{"money.allocation": allocation(has_data=False)})
    assert empty["value"] == "—"
    # 副总、总经理不能调 get_allocation：只用费用概览里的预览标记，没有未判定金额，也不可点进分摊页
    leader = make_ctx(positions=("general_manager",))
    seen = run("alloc.status", leader, **{"money.cost_overview": overview()})
    assert (seen["value"], seen["sub"], seen["target"]) == ("预览", "10 月 ¥ 286.4 万，未定版", None)
    assert "money.allocation" not in leader._memo
    done = run("alloc.status", make_ctx(positions=("vice_manager",)), **{"money.cost_overview": overview(preview=False)})
    assert done["value"] == "已定版"
    none = run("alloc.status", make_ctx(positions=("vice_manager",)), **{"money.cost_overview": overview(preview=False, totals={"rd": 0, "po": 0, "expense": 0, "total": 0})})
    assert none["value"] == "—"


def test_allocation_alerts():
    ctx = make_ctx(**FINANCE)
    unknown = run("alert.alloc_unknown", ctx, **{"money.allocation": allocation()})
    assert (unknown["tone"], unknown["title"], unknown["sub"]) == ("warn", "分摊有 ¥ 13.3 万 费用未判定阶段", "定版前需要确认")
    preview = run("alert.alloc_preview", ctx)
    assert preview["title"] == "10 月研发分摊仍是预览" and preview["sub"] == "还有 ¥ 13.3 万 未判定，定版前需要处理"
    # 预览但没有未判定金额：不提醒；已定版：不提醒预览，但仍有未判定会提醒
    quiet = {"money.allocation": allocation(unknown=0.0)}
    assert run("alert.alloc_unknown", ctx, **quiet) is None and run("alert.alloc_preview", ctx) is None
    final = {"money.allocation": allocation(preview=False, finalized=True)}
    assert run("alert.alloc_preview", ctx, **final) is None
    assert run("alert.alloc_unknown", ctx)["sub"] == "这个月已经定版，仍有未判定的金额"


def test_alloc_mix_stack_and_empty_state():
    block = run("block.alloc_mix", make_ctx(**FINANCE), **{"money.allocation": allocation()})
    assert block["title"] == "分摊构成（预览）" and block["sub"] == "10 月 ¥ 286.4 万"
    assert [row["label"] for row in block["rows"]] == ["资本化", "费用化", "未判定"]
    assert round(sum(row["pct"] for row in block["rows"])) == 100
    empty = run("block.alloc_mix", make_ctx(**FINANCE), **{"money.allocation": allocation(capitalized=0, expensed=0, unknown=0, has_data=False)})
    assert empty["rows"] == [] and empty["sub"] == "本期还没有分摊数据"


# ---------------------------------------------------------------- 付款
def test_unpaid_counts_claims_and_purchase_payments_together():
    card = run("pay.unpaid", make_ctx(**FINANCE), **pay_memo())
    assert (card["value"], card["unit"], card["tone"]) == ("8,000", "元", "bad")
    assert card["sub"] == "共 3 笔 · 加急 1 笔 · 等待超过 3 天 2 笔"
    assert card["target"] == {"key": "board.payment", "params": {}}
    assert "采购付款期次「待实际付款」" in card["hint"] and "不含采购付款" not in card["hint"]


def test_unpaid_without_po_view_leaves_purchase_out_and_says_so():
    card = run("pay.unpaid", make_ctx(positions=("finance_auditor",)), **pay_memo(**{"money.purchase": None}))
    assert (card["value"], card["sub"]) == ("3,000", "共 2 笔 · 加急 1 笔 · 等待超过 3 天 1 笔")
    assert "你没有 PO 查看权，不含采购付款" in card["hint"]


def test_unpaid_with_only_purchase_goes_to_the_purchase_payment_page():
    only = claims()
    card = run("pay.unpaid", make_ctx(**FINANCE), **pay_memo(**{"money.claims": only}))
    assert card["value"] == "5,000" and card["tone"] == "bad"
    assert card["target"] == {"key": "procpay.work", "params": {"status": "待实际付款"}}


def test_unpaid_empty_state():
    ctx = make_ctx(**FINANCE)
    card = run("pay.unpaid", ctx, **pay_memo(**{"money.claims": claims(), "money.purchase": purchase()}))
    assert (card["value"], card["unit"], card["sub"], card["tone"]) == ("0", "元", "没有待付款的单据", "")
    waiting = run("pay.waiting", ctx)
    assert (waiting["value"], waiting["sub"], waiting["tone"]) == ("0", "没有等待超过 3 天的", "ok")
    assert run("alert.pay_waiting", ctx) is None
    block = run("block.pay_wait_dist", ctx)
    assert block["rows"] == [] and block["sub"] == "没有待付款的单据"


def test_waiting_is_strictly_more_than_three_days():
    on_the_line = claims(queue=[queue_row("A", amount=100.0, waited=3), queue_row("B", amount=200.0, waited=4)])
    card = run("pay.waiting", make_ctx(**FINANCE), **pay_memo(**{"money.claims": on_the_line, "money.purchase": purchase()}))
    assert (card["value"], card["sub"]) == ("200", "1 笔 · 最久已等 4 天")


def test_waiting_card_and_alert():
    ctx = make_ctx(**FINANCE)
    card = run("pay.waiting", ctx, **pay_memo())
    assert (card["label"], card["value"], card["unit"], card["sub"], card["tone"]) == ("等待超过 3 天", "7,000", "元", "2 笔 · 最久已等 5 天", "bad")
    alert_ = run("alert.pay_waiting", ctx)
    assert alert_["tone"] == "bad" and alert_["title"] == "2 笔付款等了超过 3 天，合计 ¥ 7,000"
    assert alert_["sub"] == "最久已等 5 天，其中 1 笔在等出纳付款"
    purchase_only = run("alert.pay_waiting", make_ctx(**FINANCE), **pay_memo(**{"money.claims": claims()}))
    assert purchase_only["sub"] == "最久已等 4 天，都在等总经理确认付款"
    assert purchase_only["target"] == {"key": "procpay.work", "params": {"status": "待实际付款"}}


def test_in_approval_split_by_current_step_position():
    ctx = make_ctx(**FINANCE)
    card = run("pay.in_approval", ctx, **pay_memo())
    assert (card["value"], card["unit"], card["sub"], card["tone"]) == ("2", "张", "出纳 1 · 总经理 1", "")
    assert card["target"] == {"key": "drill", "params": {"item": "pay.in_approval", "period": "2026-10"}}
    # 报销单、付款单、采购付款在三个页面里：点进去是合在一起的清单，条数 = 卡片上的数字，每行进自己的单据
    detail = core.get_detail_for(ctx, "pay.in_approval")
    assert detail["summary"] == "共 2 张，合计 ¥ 1.0 万" and len(detail["rows"]) == int(card["value"])
    assert [row["target"] for row in detail["rows"]] == [{"key": "claim.detail", "params": {"request": "OA-1"}}, {"key": "procpay.approvals", "params": {"request": "OA-P2"}}]
    stuck_rows = claims(rows=[claim_row("S1", waited=4), claim_row("S2", kind="付款单", waited=1)])
    card = run("pay.in_approval", make_ctx(**FINANCE), **pay_memo(**{"money.claims": stuck_rows, "money.purchase": None, "money.step_buckets": {"S1": "财务主管"}}))
    assert card["sub"] == "财务主管 1 · 其他 1" and card["tone"] == "hot"
    steps = run("block.pay_steps", make_ctx(**FINANCE), **pay_memo(**{"money.claims": stuck_rows, "money.purchase": None, "money.step_buckets": {"S1": "财务主管"}}))
    assert [(row["label"], row["value"], row["tone"]) for row in steps["rows"]] == [("财务主管", "1", "bad"), ("其他", "1", "")]
    assert steps["sub"] == "付款审批中 2 张"


def test_in_approval_nothing_in_flight():
    memo = pay_memo(**{"money.claims": claims(), "money.purchase": purchase(), "money.step_buckets": {}})
    ctx = make_ctx(**FINANCE)
    card = run("pay.in_approval", ctx, **memo)
    assert (card["value"], card["sub"]) == ("0", "没有在审批的付款") and card["target"] is None
    block = run("block.pay_steps", ctx)
    assert block["rows"] == [] and block["sub"] == "没有在审批的付款"


def test_paid_this_month():
    card = run("pay.paid_month", make_ctx(**FINANCE), **pay_memo())
    assert (card["label"], card["value"], card["unit"]) == ("本月已付", "8,000", "元")
    assert card["sub"] == "4 笔 · 报销 ¥ 1,000 · 付款 ¥ 2,000 · 采购付款 ¥ 5,000"
    no_po = run("pay.paid_month", make_ctx(positions=("finance_auditor",)), **pay_memo(**{"money.purchase": None}))
    assert no_po["value"] == "3,000" and "采购付款" not in no_po["sub"]
    other = run("pay.paid_month", make_ctx(period="2026-09", **FINANCE), **pay_memo())
    assert other["label"] == "9 月已付"


def test_cashier_queue_is_claims_and_payments_only():
    card = run("pay.cashier_queue", make_ctx(positions=("finance_auditor",)), **pay_memo())
    assert (card["value"], card["sub"], card["tone"]) == ("3,000", "2 张 · 加急 1 张 · 等待超过 3 天 1 张", "bad")
    empty = run("pay.cashier_queue", make_ctx(positions=("finance_auditor",)), **pay_memo(**{"money.claims": claims()}))
    assert empty["sub"] == "出纳这一步没有待付款的" and empty["value"] == "0"


def test_wait_distribution_stack():
    block = run("block.pay_wait_dist", make_ctx(**FINANCE), **pay_memo())
    assert [(row["label"], row["value"]) for row in block["rows"]] == [("今天", "0.1 万 · 1 笔"), ("1–3 天", "0.0 万 · 0 笔"), ("超过 3 天", "0.7 万 · 2 笔")]
    assert [row["pct"] for row in block["rows"]] == [12.5, 0.0, 87.5]
    assert block["sub"] == "待付款 ¥ 8,000"


def test_suppliers_merge_names_and_skip_contracts_not_in_force_and_paid():
    block = run("block.pay_suppliers", make_ctx(**FINANCE), **pay_memo())
    assert [(row["label"], row["value"], row["tone"]) for row in block["rows"]] == [("光学元件", "1.2", "bad"), ("精密机加工", "0.3", "")]
    assert block["rows"][1]["pct"] == 25.0


def test_suppliers_top_five_then_others():
    items = [work_item("待实际付款", 1000.0 * (index + 1), po=f"PO-{index}", supplier=f"供应商{index}", request=f"R{index}") for index in range(8)]
    block = run("block.pay_suppliers", make_ctx(**FINANCE), **pay_memo(**{"money.purchase": purchase(items)}))
    assert len(block["rows"]) == 6 and block["rows"][-1]["label"] == "其他 3 家"
    assert block["rows"][0]["label"] == "供应商7"


def test_payment_stage_uses_the_systems_own_stage_names():
    block = run("block.pay_stage", make_ctx(**FINANCE), **pay_memo())
    assert [(row["label"], row["value"]) for row in block["rows"]] == [("到货款", "0.5")]
    items = [work_item("待实际付款", 3000.0, request="A", stage="预付款"), work_item("待实际付款", 2000.0, request="B", no=2, stage="尾款"),
             work_item("待实际付款", 1000.0, request="C", no=3)]
    block = run("block.pay_stage", make_ctx(**FINANCE), **pay_memo(**{"money.purchase": purchase(items)}))
    assert [row["label"] for row in block["rows"]] == ["预付款", "尾款", "（未填类型）"]


def test_claim_category_top_five():
    block = run("block.claim_category", make_ctx(**FINANCE), **pay_memo())
    assert [row["label"] for row in block["rows"]] == ["差旅费 / 机票", "招待费", "办公费", "其他"]
    assert block["rows"][0]["value"] == "14.2" and block["sub"] == "本月已付 · 万元"


# ---------------------------------------------------------------- 我的待办
QUEUE = {"claim": ["R1", "R2"], "payment": ["P1"], "procpay": [], "waited": {"R1": 2, "R2": 5, "P1": 0}}


def test_my_queue_cards():
    ctx = make_ctx()
    claim = run("claim.todo", ctx, **{"money.my_queue": QUEUE})
    assert (claim["value"], claim["sub"], claim["target"]["key"]) == ("2", "最久已等 5 天", "claim.todo")
    pay = run("pay.todo", ctx)
    assert (pay["value"], pay["sub"], pay["target"]["key"]) == ("1", "付款单 1 · 采购付款 0 · 最久已等 0 天", "payment.todo")
    only_procurement = {"claim": [], "payment": [], "procpay": ["X"], "waited": {"X": 3}}
    pay = run("pay.todo", ctx, **{"money.my_queue": only_procurement})
    assert (pay["value"], pay["target"]["key"]) == ("1", "procpay.approvals")
    empty = {"claim": [], "payment": [], "procpay": [], "waited": {}}
    assert run("claim.todo", ctx, **{"money.my_queue": empty})["sub"] == "没有等你审批的报销"
    assert run("pay.todo", ctx)["sub"] == "没有等你处理的付款"


def test_aging_groups_by_waiting_days():
    queue = {"claim": ["a", "b", "c"], "payment": ["d"], "procpay": ["e"], "waited": {"a": 0, "b": 1, "c": 2, "d": 3, "e": 9}}
    block = run("block.aging", make_ctx(), **{"money.my_queue": queue})
    assert [(row["label"], row["value"], row["tone"]) for row in block["rows"]] == [("1 天内", "2", ""), ("2–3 天", "2", ""), ("超过 3 天", "1", "bad")]
    assert block["sub"] == "报销 + 付款 · 张（共 5）"
    empty = run("block.aging", make_ctx(), **{"money.my_queue": {"claim": [], "payment": [], "procpay": [], "waited": {}}})
    assert [row["value"] for row in empty["rows"]] == ["0", "0", "0"] and empty["sub"] == "没有等你处理的报销和付款"


def test_processed_this_month():
    ctx = make_ctx()
    card = run("me.processed", ctx, **{"money.processed": {"count": 21, "kinds": {"报销单": 13, "付款单": 6, "采购付款": 2}}})
    assert (card["label"], card["value"], card["sub"]) == ("本月已处理", "21", "报销 13 · 付款 6 · 采购付款 2")
    zero = run("me.processed", make_ctx(period="2026-08"), **{"money.processed": {"count": 0, "kinds": {}}})
    assert (zero["label"], zero["value"], zero["sub"]) == ("8 月已处理", "0", "这个月还没有处理过审批")


# ---------------------------------------------------------------- 审批卡点
STUCK = [
    {"type": "报销单", "name": "A", "waited": 5, "step": "财务主管：演示员工16"}, {"type": "报销单", "name": "B", "waited": 4, "step": "出纳审核"},
    {"type": "价格审批", "name": "PA-1", "waited": 9, "step": "价格审批（副总终审）"},
]


def test_stuck_card_and_alert():
    ctx = make_ctx(positions=("vice_manager",))
    card = run("approval.stuck", ctx, **{"money.stuck": STUCK})
    assert (card["value"], card["unit"], card["tone"], card["sub"]) == ("3", "张", "hot", "超过 3 天没处理 · 最久 9 天")
    assert card["target"] == {"key": "drill", "params": {"item": "approval.stuck", "period": "2026-10"}}
    assert "不含请假、加班、调休" in card["hint"]
    alert_ = run("alert.stuck", ctx)
    assert alert_["title"] == "3 张审批超过 3 天没处理"
    assert alert_["sub"] == "最久卡在「价格审批（副总终审）」，已 9 天（报销单 2、价格审批 1）"
    assert alert_["go"] == "审批卡点" and alert_["target"] == card["target"]


def test_stuck_list_has_one_row_per_stuck_item_and_each_row_opens_that_record():
    """合计跨好几类单据，没有一个现成页面能列出“正好这些”，所以点进去是明细：条数 = 卡片上的数字，每行进自己的单据。"""
    ctx = make_ctx(positions=("vice_manager",), roles=("Rayher Business Executive",))
    ctx._memo["money.stuck"] = STUCK
    card = run("approval.stuck", ctx)
    detail = core.get_detail_for(ctx, "approval.stuck")
    assert len(detail["rows"]) == int(card["value"]) == 3 and detail["summary"] == "共 3 张超过 3 天没处理"
    assert [row["cells"] for row in detail["rows"]] == [["价格审批", "PA-1", "价格审批（副总终审）", "9 天"], ["报销单", "A", "财务主管：演示员工16", "5 天"], ["报销单", "B", "出纳审核", "4 天"]]
    assert [row["target"] for row in detail["rows"]] == [
        {"key": "price.approvals", "params": {"approval": "PA-1"}}, {"key": "claim.detail", "params": {"request": "A"}}, {"key": "claim.detail", "params": {"request": "B"}}]


def test_every_kind_of_stuck_item_opens_its_own_detail_page():
    cases = [("报销单", "claim.detail", {"request": "x"}), ("付款单", "payment.detail", {"request": "x"}), ("采购付款", "procpay.approvals", {"request": "x"}),
             ("采购申请", "procurement.detail", {"request": "x"}), ("购买申请", "directpurchase.detail", {"request": "x"}),
             ("出差申请", "travel.detail", {"request": "x"}), ("价格审批", "price.approvals", {"approval": "x"})]
    for kind, key, params in cases:
        assert money._stuck_record_target({"type": kind, "name": "x", "waited": 4, "step": ""}) == {"key": key, "params": params}, kind
    assert money._stuck_record_target({"type": "没见过的类型", "name": "x", "waited": 4, "step": ""}) is None


def test_nothing_stuck():
    ctx = make_ctx(positions=("general_manager",))
    card = run("approval.stuck", ctx, **{"money.stuck": []})
    assert (card["value"], card["tone"], card["sub"]) == ("0", "ok", "没有超过 3 天的审批")
    assert run("alert.stuck", ctx) is None


def test_stuck_loader_boundary_scope_and_price_approvals(monkeypatch):
    frappe = pytest.importorskip("frappe")
    from rayher_hr_payroll.api import expense_board_entry as board_entry

    seen = {}

    def fake_rows(types, scope, department, statuses=None):
        seen.update(types=tuple(types), scope=scope, department=department, statuses=tuple(statuses))
        return [claim_row("OK3", waited=3), claim_row("S4", waited=4), claim_row("P10", kind="采购付款", status="待办理", waited=10)]

    def fake_get_all(doctype, **kwargs):
        if doctype == "OA Price Approval":
            return [{"name": "PA-1", "modified": "2026-10-01 10:00:00"}, {"name": "PA-2", "modified": "2026-10-01 10:00:00"}]
        assert doctype == "OA Approval Step"
        return [{"parent": "PA-1", "acted_on": "2026-10-06 09:00:00"}]

    monkeypatch.setattr(board_entry, "_rows", fake_rows)
    monkeypatch.setattr(board_entry, "_decorate", lambda rows, today: rows)
    monkeypatch.setattr(frappe, "get_all", fake_get_all, raising=False)
    ctx = make_ctx(positions=("vice_manager",))
    ctx._memo["money.price_view"] = True
    stuck = money._stuck(ctx)
    # 等了 3 天不算，4 天算；价格审批从最近一次签批（10-06）算起只有 3 天不算，没人签过的从 10-01 算起 8 天算
    assert [(item["name"], item["waited"]) for item in stuck] == [("S4", 4), ("P10", 10), ("PA-2", 8)]
    assert seen["scope"] == "all" and seen["statuses"] == ("待审批", "待办理")
    assert set(seen["types"]) == {"购买申请", "出差申请", "报销单", "付款单", "采购申请", "采购付款"}
    assert "请假申请" not in seen["types"] and "加班申请" not in seen["types"] and "调休申请" not in seen["types"]
    no_price = make_ctx(positions=("general_manager",))
    no_price._memo["money.price_view"] = False
    assert [item["name"] for item in money._stuck(no_price)] == ["S4", "P10"]


# ---------------------------------------------------------------- 审批卡在哪一步
def test_step_bucket_maps_approver_accounts_to_positions():
    owners = {"出纳": {"cashier@x"}, "总账会计": {"ledger@x"}, "财务主管": {"fm@x"}, "副总经理": {"vp@x"}, "总经理": {"gm@x"}}
    assert money._step_bucket('["Cashier@X"]', "出纳审核", owners) == "出纳"      # 账号大小写不影响
    assert money._step_bucket('["fm@x", "vp@x"]', "", owners) == "财务主管"      # 会签取先走到的岗位
    assert money._step_bucket('["boss@x"]', "直属主管：某某", owners) == "直属主管"
    assert money._step_bucket('["ghost@x"]', "固定资产审批：人事经理", owners) == "其他"
    assert money._step_bucket("not json", None, owners) == "其他"


def test_step_buckets_loader_uses_the_current_step_of_each_request(monkeypatch):
    frappe = pytest.importorskip("frappe")
    from rayher_hr_payroll import position_access

    holders = {"finance_auditor": {"cashier@x"}, "finance_accountant": {"ledger@x"}, "finance_manager": {"fm@x"},
               "vice_manager": {"vp@x"}, "general_manager": {"gm@x"}}
    steps = [
        {"parent": "R1", "step_index": 0, "label": "出纳审核", "approvers": '["cashier@x"]'},
        {"parent": "R1", "step_index": 1, "label": "财务主管：演示员工16", "approvers": '["fm@x"]'},
        {"parent": "R2", "step_index": 2, "label": "直属主管：某", "approvers": '["boss@x"]'},
        {"parent": "P1", "step_index": 3, "label": "总经理付款", "approvers": '["gm@x"]'},
    ]
    asked = {}

    def fake_get_all(doctype, filters=None, **kwargs):
        asked.update(doctype=doctype, parents=filters["parent"][1])
        return steps

    monkeypatch.setattr(position_access, "position_users", lambda key: holders[key])
    monkeypatch.setattr(frappe, "get_all", fake_get_all, raising=False)
    ctx = make_ctx(**FINANCE)
    ctx._memo["money.claims"] = claims(rows=[claim_row("R1", step=1), claim_row("R2", step=2), claim_row("PAID", status="已付款")])
    ctx._memo["money.purchase"] = purchase([work_item("付款审批中", 1.0, request="P1", step=3)])
    assert money._step_buckets(ctx) == {"R1": "财务主管", "R2": "直属主管", "P1": "总经理"}
    assert asked == {"doctype": "OA Approval Step", "parents": ["P1", "R1", "R2"]}


def test_step_buckets_not_loaded_when_nothing_is_in_approval():
    ctx = make_ctx(**FINANCE)
    ctx._memo.update(pay_memo(**{"money.claims": claims(queue=[queue_row("A", amount=5.0)]), "money.purchase": purchase()}))
    ctx._memo.pop("money.step_buckets")
    assert money._pay(ctx)["approving"] == []          # 没有 money.step_buckets 备忘也没去读库
    assert "money.step_buckets" not in ctx._memo


# ---------------------------------------------------------------- 发票
INVOICES = {"counts": {"待确认": 14, "疑似重复": 2, "识别失败": 1, "识别中": 0, "可用": 63, "已使用": 10, "已排除": 3}, "stale": 4}


def test_invoice_cards_alert_and_block():
    ctx = make_ctx(roles=("Accounts User",))
    card = run("invoice.review", ctx, **{"money.invoices": INVOICES, "money.invoice_open": True})
    assert (card["value"], card["unit"], card["tone"]) == ("17", "张", "hot")
    assert card["sub"] == "待确认 14（超过 7 天 4） · 疑似重复 2 · 识别失败 1"
    assert card["target"] == {"key": "drill", "params": {"item": "invoice.review", "period": "2026-10"}}
    warn = run("alert.invoice", ctx)
    assert warn["title"] == "4 张发票待确认超过 7 天，2 张发票疑似重复" and warn["target"] == card["target"]
    block = run("block.invoice_status", ctx)
    assert [(row["label"], row["value"], row["tone"]) for row in block["rows"]] == [
        ("待确认", "14", "warn"), ("疑似重复", "2", "bad"), ("识别失败", "1", "bad"), ("可用", "63", ""), ("已使用", "10", "")]
    assert block["rows"][3]["pct"] == 100.0


def test_invoice_list_adds_up_to_the_card_and_each_row_opens_the_right_tab():
    ctx = make_ctx(roles=("Accounts User",))
    card = run("invoice.review", ctx, **{"money.invoices": INVOICES, "money.invoice_open": True})
    detail = core.get_detail_for(ctx, "invoice.review")
    assert detail["summary"] == f"共 {card['value']} 张"
    assert [(row["cells"][0], row["cells"][1]) for row in detail["rows"]] == [("待确认", "14"), ("疑似重复", "2"), ("识别失败", "1")]
    assert [row["target"]["params"] for row in detail["rows"]] == [{"tab": "allinv"}, {"tab": "dup"}, {"tab": "allinv"}]
    assert "其中超过 7 天没确认的 4 张" in detail["rows"][0]["cells"][2]


def test_invoice_duplicates_only_alert_points_at_the_list():
    data = {"counts": {"待确认": 3, "疑似重复": 1}, "stale": 0}
    warn = run("alert.invoice", make_ctx(roles=("Accounts User",)), **{"money.invoices": data, "money.invoice_open": True})
    assert warn["title"] == "1 张发票疑似重复" and warn["target"]["key"] == "drill"


def test_invoice_empty_state():
    ctx = make_ctx(roles=("Accounts User",))
    empty = {"counts": {}, "stale": 0}
    card = run("invoice.review", ctx, **{"money.invoices": empty, "money.invoice_open": True})
    assert (card["value"], card["sub"], card["tone"]) == ("0", "没有待处理的发票", "")
    assert run("alert.invoice", ctx) is None
    block = run("block.invoice_status", ctx)
    assert block["rows"] == [] and block["sub"] == "发票夹里还没有发票"


def test_invoice_needs_the_finance_role_and_the_feature_switch():
    ctx = make_ctx(roles=("Employee", "HR Manager"))
    ctx._memo["money.invoice_open"] = True
    assert not money._can_invoice(ctx)
    ctx = make_ctx(roles=("Accounts User",))
    ctx._memo["money.invoice_open"] = False
    assert not money._can_invoice(ctx)


# ---------------------------------------------------------------- 人力成本
def test_labor_cost_summary_only():
    data = {"gross": 1864000.0, "social": 312000.0, "fund": 128000.0, "has_contributions": True, "dorm_company": 52000.0, "dorm_registered": True}
    block = run("block.labor_cost", make_ctx(positions=("general_manager",)), **{"money.labor": data})
    assert [(row["label"], row["value"]) for row in block["rows"]] == [
        ("工资（应发合计）", "¥ 186.4 万"), ("社保 + 公积金（公司承担）", "¥ 44.0 万"), ("宿舍（公司承担）", "¥ 5.2 万")]
    assert block["sub"] == "10 月 · 不含个人明细"
    assert [row["target"]["key"] for row in block["rows"]] == ["payroll", "social", "dorm.board"]
    assert "身份证" not in str(block) and "银行" not in str(block)


def test_labor_cost_when_nothing_is_ready_yet():
    data = {"gross": 0.0, "social": 0.0, "fund": 0.0, "has_contributions": False, "dorm_company": 0.0, "dorm_registered": False}
    block = run("block.labor_cost", make_ctx(roles=("HR Manager",)), **{"money.labor": data})
    assert [(row["value"], row["tone"]) for row in block["rows"]] == [("—", "warn")] * 3
    assert [row["sub"] for row in block["rows"]] == ["本期还没有已提交的工资条", "本期还没有已确认的记录", "本期宿舍费用还没登记"]


# ---------------------------------------------------------------- 小函数
def test_small_helpers():
    assert money._delta_text(6.2) == "▲ 6.2% 较上月" and money._delta_text(-4.1) == "▼ 4.1% 较上月"
    assert money._amt(9800) == "¥ 9,800" and money._amt(1286400) == "¥ 128.6 万"
    assert money._month_label(make_ctx(), "已付") == "本月已付"
    assert money._month_label(make_ctx(period="2026-03"), "已付") == "3 月已付"
    assert money._month_bounds("2026-02") == ("2026-02-01", "2026-02-28")
    assert money._json_list('["a", 1]') == ["a", "1"] and money._json_list("oops") == [] and money._json_list('{"a": 1}') == []
    rows = money._top_bars([("甲", 30000.0), ("乙", 20000.0), ("丙", 10000.0), ("丁", 0.0)], 2, "家")
    assert [(row["label"], row["value"], row["pct"]) for row in rows] == [("甲", "3.0", 100.0), ("乙", "2.0", 66.7), ("其他 1 家", "1.0", 33.3)]


def test_pay_trend_covers_six_months_in_wan_and_marks_the_selected_month():
    totals = {"2026-07": 1500000.0, "2026-08": 0.0, "2026-09": 2124000.0, "2026-10": 1000000.0}
    block = run("block.pay_trend", make_ctx(**FINANCE), **{"money.paid_by_month": totals})
    assert block["type"] == "cols" and [r["label"] for r in block["rows"]] == ["5月", "6月", "7月", "8月", "9月", "10月"]
    assert [r["value"] for r in block["rows"]] == ["0", "0", "150", "0", "212.4", "100"]
    assert block["rows"][-1]["last"] is True and block["rows"][4]["pct"] == 100.0
    assert run("block.pay_trend", make_ctx(**FINANCE), **{"money.paid_by_month": {}}) is None


def test_pay_trend_is_only_for_those_who_see_the_payment_board():
    assert run("block.pay_trend", make_ctx(), **{"money.paid_by_month": {"2026-10": 1.0}}) is None


def test_paid_by_month_sums_all_three_payment_kinds_by_the_actual_paid_date(monkeypatch):
    import frappe

    seen = {}

    def get_all(doctype, **kwargs):
        seen.update(kwargs)
        return [{"amount": 100, "paid_on": "2026-10-03"}, {"amount": 50, "paid_on": "2026-10-20"}, {"amount": 70, "paid_on": "2026-08-31"},
                {"amount": 9, "paid_on": None}]

    monkeypatch.setattr(frappe, "get_all", get_all, raising=False)
    totals = money._paid_by_month(make_ctx(**FINANCE))
    assert totals == {"2026-10": 150.0, "2026-08": 70.0}
    assert seen["filters"]["workflow_status"] == "已付款"
    assert seen["filters"]["paid_on"] == ["between", ["2026-05-01", "2026-10-31"]]
    assert set(seen["filters"]["request_type"][1]) >= {"报销单", "付款单", "采购付款"}
