"""看板数字和点进去看到的对齐（财务 / 费用，决定 2026-10-13）。

规则：每个数字点进去看到的就是这个数字（同一批行、同样的条数 / 合计）；页面列不出“正好这些”的，点进去是
同一份数据的明细（drill.*）。「超过 3 天」= 严格大于 3 个日历日；等待分三段：今天 / 1–3 天 / 超过 3 天。
演示员工113、总经理能只读打开数字背后的页面（研发分摊点进研发费用汇总）。
"""
import importlib
import sys
import types
from types import SimpleNamespace

import pytest

from rayher_hr_payroll.dashboard import core, money

FINANCE = dict(roles=("Accounts User",), positions=("finance_manager",))


def make_ctx(roles=("Employee",), positions=(), **kw):
    base = dict(user="u@example.com", roles=frozenset(roles), positions=frozenset(positions), period="2026-10", today="2026-10-09")
    base.update(kw)
    return core.Ctx(**base)


def run(key, ctx, **memo):
    ctx._memo.update(memo)
    errors = []
    out = core._run(core.REGISTRY[key], ctx, errors)
    assert errors == [], errors
    return out


def allocation(**kw):
    base = {"has_data": True, "has_domestic_data": True, "preview": True, "finalized": False,
            "capitalized": 1642000.0, "expensed": 1089000.0, "unknown": 133000.0}
    base.update(kw)
    return base


def overview(**kw):
    base = {"visible": True, "totals": {"rd": 2864000.0, "po": 982000.0, "expense": 336000.0, "total": 4182000.0},
            "deltas": {"rd": 0, "po": 0, "expense": 0, "total": 0}, "projects": [], "trend": [], "preview": True, "preview_months": ["2026-10"]}
    base.update(kw)
    return base


def amount_of(text):
    """"¥ 1,234" / "¥ 1.2 万" -> 元。"""
    number = text.replace("¥", "").replace(",", "").strip()
    return float(number.replace("万", "").strip()) * 10000 if "万" in number else float(number)


# ---------------------------------------------------------------- 1 研发分摊状态：三种状态，alloc.status 和 cost.rd_pending 不矛盾
STATES = [
    ("已定版", allocation(preview=False, finalized=True, unknown=0.0), "已定版", "已定版"),
    ("预览", allocation(), "预览", "预览，财务主管定版后才作数"),
    # 原来：没有分摊单也没有预览、只有境外委托研发时显示“已定版”
    ("只有境外", allocation(preview=False, finalized=False, has_domestic_data=False, capitalized=0.0, expensed=50000.0, unknown=0.0),
     "未定版", "未定版：还没有费用导入，只有境外委托研发"),
    ("没有数据", allocation(preview=False, finalized=False, has_data=False, has_domestic_data=False, capitalized=0.0, expensed=0.0, unknown=0.0),
     "—", "本期还没有研发分摊数据"),
]


@pytest.mark.parametrize("name, alloc, status_value, pending_sub", STATES, ids=[item[0] for item in STATES])
@pytest.mark.parametrize("who", [FINANCE, dict(positions=("general_manager",)), dict(positions=("vice_manager",))], ids=["财务", "总经理", "演示员工113"])
def test_alloc_status_and_rd_pending_share_one_state(name, alloc, status_value, pending_sub, who):
    ctx = make_ctx(**who)
    status = run("alloc.status", ctx, **{"money.allocation": alloc})
    pending = run("cost.rd_pending", ctx)
    assert status["value"] == status_value, name
    assert pending["sub"] == pending_sub, name
    assert status["preview"] == pending["preview"] == (name == "预览")
    # 金额 = 分摊页 / 研发费用汇总的合计（资本化 + 费用化 + 未判定）
    total = alloc["capitalized"] + alloc["expensed"] + alloc["unknown"]
    assert pending["value"] == core.money_wan(total)[0]
    if alloc["has_data"]:
        assert status["sub"].startswith(f"10 月 {money._amt(total)}")
    # 财务去分摊页；演示员工113、总经理只读，去研发费用汇总
    key = "allocation" if who is FINANCE else "cost.summary"
    assert status["target"]["key"] == pending["target"]["key"] == key
    assert "money.cost_overview" not in ctx._memo      # 不再一个看概览、一个看分摊


def test_alloc_status_hint_names_all_three_states_and_foreign_only_is_a_warning():
    card = run("alloc.status", make_ctx(**FINANCE), **{"money.allocation": STATES[2][1]})
    assert card["tone"] == "warn" and card["sub"] == "10 月 ¥ 5.0 万，还没有费用导入，只有境外委托研发"
    assert "已定版 = " in card["hint"] and "预览 = " in card["hint"] and "未定版 = " in card["hint"]
    broken = run("alloc.status", make_ctx(**FINANCE), **{"money.allocation": dict(STATES[2][1], preview_error="没有研发工时")})
    assert "有费用导入但预览算不出来" in broken["sub"]


def test_unknown_card_subtitle_on_a_finalized_month():
    ctx = make_ctx(**FINANCE)
    final = run("cost.unknown", ctx, **{"money.allocation": allocation(preview=False, finalized=True)})
    assert final["sub"] == "已定版，仍有未判定的金额"
    clean = run("cost.unknown", make_ctx(**FINANCE), **{"money.allocation": allocation(preview=False, finalized=True, unknown=0.0)})
    assert clean["sub"] == "已定版，没有未判定的"
    draft = run("cost.unknown", make_ctx(**FINANCE), **{"money.allocation": allocation()})
    assert draft["sub"] == "定版前要确认"


# ---------------------------------------------------------------- 10 / 14 演示员工113、总经理：分摊数字只读、能点开
@pytest.mark.parametrize("position", ["general_manager", "vice_manager"])
def test_leaders_get_allocation_blocks_read_only_with_working_links(position):
    ctx = make_ctx(positions=(position,))
    memo = {"money.allocation": allocation(), "money.cost_overview": overview()}
    summary = {"key": "cost.summary", "params": {"period": "2026-10"}}
    assert run("cost.rd", ctx, **memo)["target"] == summary
    assert run("alloc.status", ctx)["target"] == summary
    assert run("cost.rd_pending", ctx)["target"] == summary
    preview = run("alert.alloc_preview", ctx)
    assert preview is not None and preview["target"] == summary and preview["go"] == "研发费用汇总"
    mix = run("block.alloc_mix", ctx)
    assert mix["target"] == summary and mix["more"] == "研发费用汇总"
    assert run("cost.cap", ctx)["target"] == summary


def test_finance_still_goes_to_the_allocation_page():
    ctx = make_ctx(**FINANCE)
    ctx._memo["money.allocation"] = allocation()
    for key in ("alloc.status", "cost.rd_pending", "cost.cap", "cost.unknown", "block.alloc_mix", "alert.alloc_preview", "alert.alloc_unknown"):
        assert run(key, ctx)["target"] == {"key": "allocation", "params": {"period": "2026-10"}}, key


def test_plain_staff_and_hr_never_load_allocation_data():
    for ctx in (make_ctx(), make_ctx(roles=("HR Manager",)), make_ctx(roles=("Purchase User",), positions=("pmc",))):
        for key in ("alloc.status", "cost.rd_pending", "alert.alloc_preview", "block.alloc_mix", "cost.cap"):
            assert run(key, ctx) is None
        assert "money.allocation" not in ctx._memo


def _install_fake_frappe(monkeypatch, user, roles):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.only_for = lambda roles: None
    frappe.get_roles = lambda user=None: list(roles)
    frappe.session = SimpleNamespace(user=user)
    frappe.whitelist = lambda *args, **kwargs: (args[0] if args and callable(args[0]) else (lambda fn: fn))
    frappe.throw = lambda message, *args: (_ for _ in ()).throw(RuntimeError(str(message)))
    frappe.db = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    # 用假的 frappe 重新载入；测试结束后原来的模块放回去，不影响后面的测试
    import rayher_hr_payroll.api as api_pkg
    for name in ("_guards", "allocation_entry"):
        monkeypatch.setattr(api_pkg, name, getattr(api_pkg, name, None), raising=False)
        monkeypatch.delitem(sys.modules, f"rayher_hr_payroll.api.{name}", raising=False)
    return importlib.import_module("rayher_hr_payroll.api.allocation_entry")


@pytest.mark.parametrize("user, roles, leaders, finance_check", [
    ("gm@x", ["Employee"], {"gm@x"}, False),            # 总经理岗位：只读放行，不走财务角色检查
    ("VP@X", ["Employee"], {"vp@x"}, False),            # 账号大小写不影响
    ("fin@x", ["Accounts User"], set(), True),          # 财务照旧
    ("emp@x", ["Employee"], {"gm@x"}, True),            # 其他人照旧被财务角色检查挡住
])
def test_allocation_read_is_open_to_leader_positions_only(monkeypatch, user, roles, leaders, finance_check):
    mod = _install_fake_frappe(monkeypatch, user, roles)
    from rayher_hr_payroll import position_access

    asked = {}
    monkeypatch.setattr(position_access, "position_users", lambda *keys: asked.setdefault("keys", keys) and set(leaders))
    checked = []
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: checked.append(roles))
    mod._require_read_access()
    assert bool(checked) == finance_check
    if checked:
        assert checked == [mod.RD_FINANCE_ROLES]
    if not set(roles) & set(mod.RD_FINANCE_ROLES):
        assert set(asked["keys"]) == {"vice_manager", "general_manager"}


def test_leaders_still_cannot_finalize_or_cancel(monkeypatch):
    """只读：定版、撤销定版、定版检查仍然只认财务角色（不走 _require_read_access）。"""
    mod = _install_fake_frappe(monkeypatch, "gm@x", ["Employee"])
    import inspect

    for name in ("finalize_allocation", "cancel_allocation", "get_finalize_check"):
        source = inspect.getsource(getattr(mod, name))
        assert "require_rd_access(RD_FINANCE_ROLES)" in source and "_require_read_access" not in source, name
    for name in ("get_allocation", "get_allocation_dashboard"):
        assert "_require_read_access()" in inspect.getsource(getattr(mod, name)), name


# ---------------------------------------------------------------- 2 / 4 待付款：点进去是同一批，分段和图表一样
def item(name, kind="报销单", amount=100.0, waited=0, urgent=False, request=None, po=""):
    return {"kind": kind, "name": name, "request": name if request is None else request, "po": po, "amount": amount, "waited": waited,
            "urgent": urgent, "bucket": "其他", "supplier": "", "stage": ""}


UNPAID = [item("R0", waited=0, urgent=True), item("R3", "付款单", 300.0, waited=3), item("R4", amount=400.0, waited=4),
          item("PO-1:2", "采购付款", 500.0, waited=9, request="", po="PO-1"), item("OA-P1", "采购付款", 700.0, waited=1)]


def pay_ctx(unpaid=UNPAID):
    ctx = make_ctx(**FINANCE)
    ctx._memo["money.pay"] = {"unpaid": list(unpaid), "approving": [], "payables": [], "has_purchase": True}
    return ctx


def test_unpaid_card_opens_a_list_with_the_same_rows_and_total():
    ctx = pay_ctx()
    card = run("pay.unpaid", ctx)
    assert card["target"] == {"key": "drill", "params": {"item": "pay.unpaid", "period": "2026-10"}}
    detail = core.get_detail_for(ctx, "pay.unpaid")
    assert len(detail["rows"]) == 5 and detail["summary"].startswith("共 5 笔，合计 ¥ 2,000")
    assert sum(amount_of(row["cells"][3]) for row in detail["rows"]) == amount_of(f"¥ {card['value']}")
    # 报销/付款单进单据；采购付款有付款单进付款审批单，还没有付款单的期次进 PO 的付款工作项
    targets = {row["cells"][1]: row["target"] for row in detail["rows"]}
    assert targets["R0"] == {"key": "claim.detail", "params": {"request": "R0"}}
    assert targets["R3"] == {"key": "payment.detail", "params": {"request": "R3"}}
    assert targets["OA-P1"] == {"key": "procpay.approvals", "params": {"request": "OA-P1"}}
    assert targets["PO-1:2"] == {"key": "procpay.work", "params": {"po": "PO-1"}}


def test_wait_buckets_are_today_one_to_three_and_strictly_more_than_three_everywhere():
    ctx = pay_ctx()
    block = run("block.pay_wait_dist", ctx)
    assert [row["label"] for row in block["rows"]] == ["今天", "1–3 天", "超过 3 天"]
    # 正好 3 天在 1–3 天里，4 天起才算超过 3 天
    assert [row["value"].split(" · ")[1] for row in block["rows"]] == ["1 笔", "2 笔", "2 笔"]
    assert block["target"]["params"]["item"] == "pay.unpaid" and block["more"] == "查看明细"
    detail = core.get_detail_for(ctx, "pay.unpaid")
    assert "今天 1 笔 · 1–3 天 2 笔 · 超过 3 天 2 笔" in detail["summary"]
    assert {row["cells"][1]: row["cells"][5].split("，")[0] for row in detail["rows"]} == {
        "R0": "今天", "OA-P1": "1–3 天", "R3": "1–3 天", "R4": "超过 3 天", "PO-1:2": "超过 3 天"}
    assert money._wait_bucket(3) == "1–3 天" and money._wait_bucket(4) == "超过 3 天" and money._wait_bucket(0) == "今天"


def test_waiting_card_and_alert_open_exactly_the_waiting_rows():
    ctx = pay_ctx()
    card = run("pay.waiting", ctx)
    alert_ = run("alert.pay_waiting", ctx)
    assert card["target"] == alert_["target"] == {"key": "drill", "params": {"item": "pay.waiting", "period": "2026-10"}}
    assert alert_["go"] == "超过 3 天的付款"        # 按钮写的就是点进去看到的（原来写“付款看板”）
    detail = core.get_detail_for(ctx, "pay.waiting")
    assert [row["cells"][1] for row in detail["rows"]] == ["PO-1:2", "R4"]
    assert sum(amount_of(row["cells"][3]) for row in detail["rows"]) == amount_of(f"¥ {card['value']}") == 900.0
    assert all(row["tone"] == "bad" for row in detail["rows"])


def test_nothing_waiting_has_no_link():
    ctx = pay_ctx([item("A", waited=1)])
    assert run("pay.waiting", ctx)["target"] is None and run("alert.pay_waiting", ctx) is None
    empty = pay_ctx([])
    assert run("pay.unpaid", empty)["target"] is None and run("block.pay_wait_dist", empty)["target"] is None


def test_cashier_queue_card_counts_only_to_pay_rows_like_the_board_title():
    ctx = make_ctx(positions=("finance_auditor",))
    ctx._memo.update({"money.claims": {"rows": [], "board": {"summary": {}, "cashier_queue": [
        {"name": "A", "request_type": "报销单", "amount": 100.0, "urgency": "一般", "waited_days": 1, "status": "待付款"},
        {"name": "V", "request_type": "付款单", "amount": 900.0, "urgency": "一般", "waited_days": 9, "status": "待核验"}]}},
        "money.purchase": None})
    card = run("pay.cashier_queue", ctx)
    assert (card["value"], card["sub"]) == ("100", "1 张")
    assert "不含已付款等核验发票" in card["hint"]


# ---------------------------------------------------------------- 5 / 6 费用里的采购、报销付款：明细合计 = 卡片，去重的单列
def _cost_frappe(monkeypatch):
    frappe = pytest.importorskip("frappe")

    def fake_get_all(doctype, filters=None, **kwargs):
        if doctype == "OA Purchase Order":
            return [{"name": "PO-1", "supplier": "甲", "status": "已生效", "creation": "2026-10-03 10:00:00"},
                    {"name": "PO-2", "supplier": "乙", "status": "已生效", "creation": "2026-10-04 10:00:00"},
                    {"name": "PO-3", "supplier": "丙", "status": "草稿", "creation": "2026-10-05 10:00:00"}]
        if doctype == "OA Purchase Order Line":
            return [{"parent": "PO-1", "amount": 100.0, "project": "NP"}, {"parent": "PO-1", "amount": 40.0, "project": "RD1"},
                    {"parent": "PO-2", "amount": 60.0, "project": "RD1"}, {"parent": "PO-3", "amount": 30.0, "project": None}]
        if doctype == "OA Approval Request":
            return [{"name": "R-1", "request_type": "报销单", "subject": "差旅", "employee_name": "演示员工129", "paid_on": "2026-10-02", "project": "RD1"},
                    {"name": "R-2", "request_type": "付款单", "subject": "", "employee_name": "演示员工146", "paid_on": "2026-10-04", "project": ""},
                    {"name": "R-3", "request_type": "费用付款申请", "subject": "旧单", "employee_name": "演示员工157", "paid_on": "2026-10-06", "project": ""}]
        assert doctype == "OA Approval Expense Line", doctype
        # R-1：表头是研发项目，明细没写项目 -> 跟表头，去重；第二行写了非研发项目 -> 保留
        return [{"parent": "R-1", "total_amount": 80.0, "amount": 70.0}, {"parent": "R-1", "total_amount": 20.0, "claim_project": "NP"},
                {"parent": "R-2", "total_amount": None, "amount": 40.0, "project_name": "RD1"}, {"parent": "R-3", "total_amount": 15.0}]

    monkeypatch.setattr(frappe, "get_all", fake_get_all, raising=False)


def test_cost_po_list_total_equals_the_card_and_lists_rd_duplicates_separately(monkeypatch):
    _cost_frappe(monkeypatch)
    ctx = make_ctx(**FINANCE)
    # 概览：PO 去掉研发项目 RD1 的行后 = 100 + 30
    ctx._memo.update({"money.cost_overview": overview(totals={"rd": 1000.0, "po": 130.0, "expense": 35.0, "total": 1165.0}),
                      "money.rd_dup_projects": frozenset({"RD1"})})
    card = run("cost.po", ctx)
    detail = core.get_detail_for(ctx, "cost.po")
    assert detail["summary"] == "共 2 个 PO，合计 ¥ 130" and card["value"] == "130"
    assert [(row["cells"][0], row["cells"][2], row["cells"][4], row["tone"]) for row in detail["rows"]] == [
        ("PO-1", "已生效", "¥ 100", ""), ("PO-3", "草稿", "¥ 30", ""),
        ("PO-2", "已含在研发分摊", "¥ 60", "info"), ("PO-1", "已含在研发分摊", "¥ 40", "info")]
    assert "另有研发项目的采购 ¥ 100" in detail["note"] and "不计入合计" in detail["note"]
    # 费用合计的明细里，采购这一行点进去就是这张清单，金额一样
    total = core.get_detail_for(ctx, "cost.total")
    assert total["rows"][1]["cells"][2] == "¥ 130" and total["rows"][1]["target"]["params"] == {"item": "cost.po", "period": "2026-10"}


def test_cost_expense_list_total_equals_the_card_and_lists_rd_duplicates_separately(monkeypatch):
    _cost_frappe(monkeypatch)
    ctx = make_ctx(**FINANCE)
    ctx._memo.update({"money.cost_overview": overview(totals={"rd": 1000.0, "po": 130.0, "expense": 35.0, "total": 1165.0}),
                      "money.rd_dup_projects": frozenset({"RD1"})})
    detail = core.get_detail_for(ctx, "cost.expense")
    # 保留：R-1 的非研发行 20 + R-3 的 15 = 35（= 概览的报销付款）；R-2 整张是研发项目
    assert detail["summary"] == "共 2 张，合计 ¥ 35" and run("cost.expense", ctx)["value"] == "35"
    assert [(row["cells"][0], row["cells"][1], row["cells"][5]) for row in detail["rows"]] == [
        ("R-1", "报销单", "¥ 20"), ("R-3", "费用付款申请", "¥ 15"), ("R-1", "已含在研发分摊", "¥ 80"), ("R-2", "已含在研发分摊", "¥ 40")]
    assert detail["rows"][1]["target"] == {"key": "reimbursement.detail", "params": {"request": "R-3"}}
    assert "另有研发项目的报销付款 ¥ 120" in detail["note"]
    assert core.get_detail_for(ctx, "cost.total")["rows"][2]["target"]["params"]["item"] == "cost.expense"


def test_without_an_allocation_nothing_is_dropped(monkeypatch):
    _cost_frappe(monkeypatch)
    ctx = make_ctx(**FINANCE)
    ctx._memo.update({"money.cost_overview": overview(preview=False, preview_months=[]), "money.rd_dup_projects": frozenset()})
    po = core.get_detail_for(ctx, "cost.po")
    assert po["summary"] == "共 3 个 PO，合计 ¥ 230" and po["note"] == ""
    assert core.get_detail_for(ctx, "cost.expense")["summary"] == "共 3 张，合计 ¥ 155"


def test_rd_duplicate_rule_follows_the_overview(monkeypatch):
    pytest.importorskip("frappe")
    from rayher_hr_payroll.api import overview_entry

    monkeypatch.setattr(overview_entry, "_rd_project_names", lambda: {"RD1", "RD2"})
    finalized = set()
    monkeypatch.setattr(overview_entry, "_allocated_months", lambda months: set(months) & finalized)
    preview = make_ctx(**FINANCE)
    preview._memo["money.cost_overview"] = overview()                     # 预览月份：去重
    assert money._rd_dup_projects(preview) == {"RD1", "RD2"}
    plain = make_ctx(**FINANCE)
    plain._memo["money.cost_overview"] = overview(preview=False, preview_months=[])
    assert money._rd_dup_projects(plain) == frozenset()                   # 没定版也没预览：不去重
    finalized.add((2026, 10))
    done = make_ctx(**FINANCE)
    done._memo["money.cost_overview"] = overview(preview=False, preview_months=[])
    assert money._rd_dup_projects(done) == {"RD1", "RD2"}                 # 已定版：去重


# ---------------------------------------------------------------- 7 / 8 / 9 已付：一个算法，期间跟着走
def test_paid_loader_uses_line_totals_like_the_cost_overview(monkeypatch):
    _cost_frappe(monkeypatch)
    paid = money._paid(make_ctx(**FINANCE), "2026-10-01", "2026-10-31")
    assert {doc["name"]: doc["amount"] for doc in paid["docs"]} == {"R-1": 100.0, "R-2": 40.0, "R-3": 15.0}
    # 项目归属：明细的所属项目 > 明细的项目名称 > 表头项目
    assert [line["project"] for line in paid["lines"]] == ["RD1", "NP", "RD1", ""]
    assert {line["account"] for line in paid["lines"]} == {"未填写"}


PAID = {"money.paid:2026-10-01:2026-10-31": {
    "docs": [{"name": "R-1", "kind": "报销单", "subject": "差旅", "employee_name": "演示员工129", "paid_on": "2026-10-02", "amount": 100.0},
             {"name": "R-2", "kind": "付款单", "subject": "", "employee_name": "演示员工146", "paid_on": "2026-10-04", "amount": 40.0},
             {"name": "R-3", "kind": "费用付款申请", "subject": "", "employee_name": "", "paid_on": "2026-10-06", "amount": 15.0}],
    "lines": [{"parent": "R-1", "project": "", "amount": 80.0, "account": "管理费用 / 差旅费"},
              {"parent": "R-1", "project": "", "amount": 20.0, "account": "管理费用 / 办公费"},
              {"parent": "R-2", "project": "", "amount": 40.0, "account": "管理费用 / 差旅费"},
              {"parent": "R-3", "project": "", "amount": 15.0, "account": "未填写"}]},
    "money.paid_po:2026-10-01:2026-10-31": [{"name": "P-1", "kind": "采购付款", "subject": "", "employee_name": "", "paid_on": "2026-10-07", "amount": 500.0}],
    "money.po_pay_view": True}


def test_paid_month_card_opens_a_list_for_the_same_period_with_the_same_total():
    ctx = make_ctx(**FINANCE, period="2026-10")
    card = run("pay.paid_month", ctx, **PAID)
    assert card["value"] == "655" and card["sub"] == "4 笔 · 报销 ¥ 100 · 付款 ¥ 40 · 费用付款申请（旧） ¥ 15 · 采购付款 ¥ 500"
    assert card["target"] == {"key": "drill", "params": {"item": "pay.paid", "period": "2026-10"}}
    detail = core.get_detail_for(ctx, "pay.paid")
    assert detail["summary"] == "共 4 笔，合计 ¥ 655" and len(detail["rows"]) == 4
    assert [row["target"]["key"] for row in detail["rows"]] == ["procpay.approvals", "reimbursement.detail", "payment.detail", "claim.detail"]


def test_claim_category_uses_the_same_algorithm_and_its_list_keeps_the_period():
    ctx = make_ctx(**FINANCE, period="2026-10")
    block = run("block.claim_category", ctx, **PAID)
    assert [row["label"] for row in block["rows"]] == ["管理费用 / 差旅费", "管理费用 / 办公费", "未填写"]
    assert block["target"] == {"key": "drill", "params": {"item": "pay.category", "period": "2026-10"}}
    detail = core.get_detail_for(ctx, "pay.category")
    assert [row["cells"] for row in detail["rows"]] == [["管理费用 / 差旅费", "2 张", "¥ 120"], ["管理费用 / 办公费", "1 张", "¥ 20"], ["未填写", "1 张", "¥ 15"]]
    # 按类别合计 = 已付里报销、付款、费用付款申请的合计（不含采购付款，采购付款没有费用科目）
    paid = core.get_detail_for(ctx, "pay.paid")
    claims_total = sum(amount_of(row["cells"][5]) for row in paid["rows"] if row["cells"][0] != "采购付款")
    assert detail["summary"] == f"共 3 类，合计 {money._amt(claims_total)}"


def test_pay_trend_list_has_one_row_per_month_and_each_opens_that_months_paid_list():
    ctx = make_ctx(**FINANCE)
    docs = [{"name": "R-1", "kind": "报销单", "subject": "", "employee_name": "", "paid_on": "2026-10-02", "amount": 100.0},
            {"name": "R-0", "kind": "付款单", "subject": "", "employee_name": "", "paid_on": "2026-06-30", "amount": 60.0}]
    ctx._memo.update({"money.paid:2026-05-01:2026-10-31": {"docs": docs, "lines": []},
                      "money.paid_po:2026-05-01:2026-10-31": [{"name": "P", "kind": "采购付款", "subject": "", "employee_name": "", "paid_on": "2026-10-09", "amount": 40.0}],
                      "money.po_pay_view": True})
    block = run("block.pay_trend", ctx)
    assert block["target"]["params"]["item"] == "pay.trend" and block["sub"] == "万元 · 报销 + 付款 + 采购付款"
    detail = core.get_detail_for(ctx, "pay.trend")
    assert [row["cells"][0] for row in detail["rows"]] == ["5月", "6月", "7月", "8月", "9月", "10月"]
    assert detail["rows"][-1]["cells"] == ["10月", "¥ 100", "¥ 40", "¥ 140"] and detail["rows"][1]["cells"][3] == "¥ 60"
    assert detail["rows"][1]["target"] == {"key": "drill", "params": {"item": "pay.paid", "period": "2026-06"}}
    assert detail["summary"] == "6 个月合计 ¥ 200"


def test_pay_trend_leaves_purchase_payments_out_without_po_view():
    """原来趋势不看 PO 查看权、总把采购付款算进去，和「本月已付」对不上。"""
    ctx = make_ctx(positions=("finance_auditor",))
    ctx._memo.update({"money.paid:2026-05-01:2026-10-31": {"docs": [], "lines": []}, "money.po_pay_view": False})
    assert money._paid_purchase(ctx, "2026-05-01", "2026-10-31") is None      # 没有 PO 查看权：不查采购付款
    detail = core.get_detail_for(ctx, "pay.trend")
    assert [column["label"] for column in detail["columns"]] == ["月份", "报销付款", "合计"]


# ---------------------------------------------------------------- 12 发票：待确认、识别失败各进自己的筛选
def test_invoice_rows_open_a_single_status_filter():
    ctx = make_ctx(roles=("Accounts User",))
    ctx._memo.update({"money.invoices": {"counts": {"待确认": 3, "识别失败": 2, "疑似重复": 1}, "stale": 0}, "money.invoice_open": True})
    detail = core.get_detail_for(ctx, "invoice.review")
    assert {row["cells"][0]: row["target"]["params"]["tab"] for row in detail["rows"]} == {"待确认": "confirm", "疑似重复": "dup", "识别失败": "failed"}


# ---------------------------------------------------------------- 13 趋势、本月已处理：点得进去
def test_cost_trend_list_rows_open_each_months_cost_total():
    months = ("11月", "12月", "1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月")
    trend = [{"label": label, "rd": 10.0, "po": 20.0, "expense": 30.0, "total": 60.0, "preview": label == "10月"} for label in months]
    ctx = make_ctx(**FINANCE)
    ctx._memo["money.cost_overview"] = overview(trend=trend)
    block = run("block.cost_trend", ctx)
    assert block["target"]["params"] == {"item": "cost.trend", "period": "2026-10"}
    detail = core.get_detail_for(ctx, "cost.trend")
    assert [row["cells"][0] for row in detail["rows"]] == ["5月", "6月", "7月", "8月", "9月", "10月（含预览）"]
    assert [row["target"]["params"]["period"] for row in detail["rows"]] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert all(row["target"]["params"]["item"] == "cost.total" for row in detail["rows"])
    assert detail["rows"][0]["cells"][1:] == ["¥ 10", "¥ 20", "¥ 30", "¥ 60"]
    # 跨年：1 月往前是去年 12 月
    assert money._last_months("2026-02", 3) == ["2025-12", "2026-01", "2026-02"]


def test_processed_card_opens_the_list_of_what_i_processed():
    ctx = make_ctx()
    rows = [{"name": "R1", "kind": "报销单", "subject": "差旅", "employee_name": "演示员工129", "acted_on": "2026-10-03"},
            {"name": "L1", "kind": "请假申请", "subject": "", "employee_name": "演示员工146", "acted_on": "2026-10-05"},
            {"name": "X1", "kind": "没见过的类型", "subject": "", "employee_name": "", "acted_on": "2026-10-01"}]
    card = run("me.processed", ctx, **{"money.processed": {"count": 3, "kinds": {"报销单": 1, "请假申请": 1, "没见过的类型": 1}, "rows": rows}})
    assert card["target"] == {"key": "drill", "params": {"item": "me.processed", "period": "2026-10"}}
    detail = core.get_detail_for(ctx, "me.processed")
    assert len(detail["rows"]) == int(card["value"]) == 3 and detail["summary"] == "共 3 张"
    assert [row["cells"][1] for row in detail["rows"]] == ["L1", "R1", "X1"]
    assert [row["target"] for row in detail["rows"]] == [{"key": "attendance.detail", "params": {"request": "L1"}},
                                                         {"key": "claim.detail", "params": {"request": "R1"}}, None]
    nothing = run("me.processed", make_ctx(), **{"money.processed": {"count": 0, "kinds": {}}})
    assert nothing["target"] is None


def test_processed_loader_counts_each_request_once(monkeypatch):
    frappe = pytest.importorskip("frappe")

    def fake_get_all(doctype, filters=None, **kwargs):
        if doctype == "OA Approval Step":
            assert filters["action_by"] == "u@example.com" and filters["acted_on"] == ["between", ["2026-10-01", "2026-10-31"]]
            return [{"parent": "R1", "acted_on": "2026-10-02 09:00:00"}, {"parent": "R1", "acted_on": "2026-10-04 09:00:00"},
                    {"parent": "P1", "acted_on": "2026-10-03 10:00:00"}]
        return [{"name": "R1", "request_type": "报销单", "subject": "差旅", "employee_name": "演示员工129"},
                {"name": "P1", "request_type": "付款单", "subject": None, "employee_name": "演示员工146"}]

    monkeypatch.setattr(frappe, "get_all", fake_get_all, raising=False)
    done = money._processed(make_ctx())
    assert done["count"] == 2 and done["kinds"] == {"报销单": 1, "付款单": 1}
    assert {row["name"]: row["acted_on"] for row in done["rows"]} == {"R1": "2026-10-04", "P1": "2026-10-03"}


# ---------------------------------------------------------------- 14 价格审批卡点：从提交算起
def test_price_approval_waits_from_submit_not_from_last_edit(monkeypatch):
    frappe = pytest.importorskip("frappe")
    from rayher_hr_payroll.api import expense_board_entry as board_entry

    monkeypatch.setattr(board_entry, "_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(board_entry, "_decorate", lambda rows, today: rows)

    def fake_get_all(doctype, **kwargs):
        if doctype == "OA Price Approval":
            # 单据 10-08 改过（比如改了备注），但 10-01 就提交了，没人签过
            return [{"name": "PA-1", "modified": "2026-10-08 10:00:00"}, {"name": "PA-2", "modified": "2026-10-08 10:00:00"}]
        return [{"parent": "PA-1", "acted_on": None, "creation": "2026-10-01 09:00:00"},
                {"parent": "PA-2", "acted_on": "2026-10-07 09:00:00", "creation": "2026-09-20 09:00:00"}]

    monkeypatch.setattr(frappe, "get_all", fake_get_all, raising=False)
    ctx = make_ctx(positions=("vice_manager",))
    ctx._memo["money.price_view"] = True
    assert [(item["name"], item["waited"]) for item in money._stuck(ctx)] == [("PA-1", 8)]


# ---------------------------------------------------------------- 人力成本：只算已确认的工资条
def labor(**kw):
    base = {"gross": 0.0, "draft": 0, "social": 0.0, "fund": 0.0, "has_contributions": False, "dorm_company": 0.0, "dorm_registered": False}
    base.update(kw)
    return base


def test_labor_cost_counts_confirmed_slips_and_shows_drafts_as_progress():
    ctx = make_ctx(positions=("general_manager",))
    only_draft = run("block.labor_cost", ctx, **{"money.labor": labor(draft=5)})["rows"][0]
    assert (only_draft["value"], only_draft["sub"], only_draft["tone"]) == ("—（还有 5 人工资条没确认）", "还有 5 人工资条没确认", "warn")
    both = run("block.labor_cost", make_ctx(positions=("general_manager",)), **{"money.labor": labor(gross=100000.0, draft=2)})["rows"][0]
    assert (both["value"], both["sub"]) == ("¥ 10.0 万", "已确认的工资条；另有 2 人没确认")
    ctx = make_ctx(roles=("HR Manager",))
    ctx._memo["money.labor"] = labor(gross=100000.0, draft=2)
    detail = core.get_detail_for(ctx, "cost.labor")
    assert detail["rows"][0]["cells"] == ["工资（应发合计）", "已确认的工资条；另有 2 人没确认", "¥ 10.0 万"]
    assert "已提交" not in str(run("block.labor_cost", make_ctx(roles=("HR Manager",)), **{"money.labor": labor()}))
