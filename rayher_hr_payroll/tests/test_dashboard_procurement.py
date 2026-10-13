"""采购 / PMC / 生产主管的看板块（rayher_hr_payroll/dashboard/procurement.py）。

数据读取函数整体替换成假数据，验证口径、权限、空数据显示；SQL / 查询条件的 Python 侧逻辑用假 frappe 单独测。
今天固定为 2026-10-09（周五），本周 = 10-05 到 10-11。
"""
import json
import re
from types import SimpleNamespace as NS

import pytest

from rayher_hr_payroll.dashboard import core, layout
from rayher_hr_payroll.dashboard import procurement as proc

TODAY = "2026-10-09"

KPIS = ["proc.to_compare", "proc.price_pending", "proc.po_transit", "proc.po_overdue", "proc.ready_to_pay",
        "proc.pay_planned_passed", "proc.month_amount", "proc.suppliers_count", "proc.uncoded", "proc.await_pr",
        "proc.material_overdue", "proc.week_arrive", "proc.to_arrive", "proc.to_inspect", "proc.exchange",
        "proc.return", "proc.month_inspected", "proc.month_arrived", "proc.risk_projects", "proc.urgent"]
ALERTS = ["alert.po_overdue", "alert.pay_planned_passed", "alert.price_missing_quote", "alert.uncoded",
          "alert.inspect_stale", "alert.material_overdue", "alert.risk_projects", "alert.urgent"]
BLOCKS = ["block.proc_chain", "block.arrival_inspect", "block.proc_suppliers", "block.proc_projects",
          "block.material_stage", "block.risk_projects", "block.week_schedule", "block.urgent_requests"]
MINE = KPIS + ALERTS + BLOCKS
URGENT = {"proc.urgent", "alert.urgent", "block.urgent_requests"}      # 加急采购：采购链路的人、副总、总经理看，生产主管和财务不看
MONEY = {"proc.month_amount", "block.proc_suppliers", "block.proc_projects", "proc.ready_to_pay",
         "proc.pay_planned_passed", "alert.pay_planned_passed"}
CHAIN = {"proc.to_compare", "proc.price_pending", "proc.await_pr", "alert.price_missing_quote"}
BOARD = {"proc.uncoded", "proc.material_overdue", "proc.risk_projects", "alert.uncoded", "alert.material_overdue",
         "alert.risk_projects", "block.material_stage", "block.risk_projects"}


def make_ctx(positions=(), roles=("Employee",), user="u@example.com", period="2026-10", **kw):
    return core.Ctx(user=user, roles=frozenset(roles), positions=frozenset(positions), period=period, today=TODAY, **kw)


def line(po, quantity, got, state="", due="", project="", item="", sr="", sl="", status="供应商制作中", name=None):
    return {"po": po, "po_status": status, "supplier": "甲", "line": name or f"{po}-{item or quantity}-{got}-{due}",
            "quantity": quantity, "received": got, "inspection": state, "due": due, "project": project, "item": item,
            "source_request": sr, "source_line": sl}


def rich_lines():
    return [
        line("PO-A", 10, 0, due="2026-10-01", project="P1", item="镜片", sr="R1", sl="L1", name="A1"),
        line("PO-A", 5, 5, state="待验收", due="2026-10-02", name="A2"),
        line("PO-B", 4, 2, state="待验收", due="2026-10-10", status="到货验收中", name="B1"),
        line("PO-B", 3, 3, state="换货中", due="2026-09-20", status="到货验收中", name="B2"),
        line("PO-B", 2, 2, state="退货中", due="2026-09-30", status="到货验收中", name="B3"),
        line("PO-C", 1, 1, state="已通过", due="2026-09-01", status="付款中", name="C1"),
        line("PO-D", 9, 0, due="2026-09-01", status="草稿", name="D1"),          # 草稿 PO：合同没生效，不参与任何口径
        line("PO-E", 6, 0, project="P1", item="导轨", name="E1"),                 # 没填合同交期
        line("PO-E", 6, 0, due=TODAY, name="E2"),                                 # 交期就是今天：不算逾期，算本周
    ]


@pytest.fixture
def world(monkeypatch):
    """所有数据读取函数换成假数据；world["calls"] 记录被调用的读取函数，用来证明没权限的块没碰数据。"""
    data = {"calls": [], "lines": [], "arrivals": {}, "records": [], "month_pos": [], "month_lines": [], "pay": [],
            "pr": [], "price": {"pending": 0, "draft": 0, "unquoted": {}}, "await": [], "uncoded": [], "stages": [],
            "chain": {"request": 0, "pr": 0, "po": 0, "payment": 0}, "urgent": []}

    def reader(name, key, fn=None):
        def read(*args):
            data["calls"].append(name)
            return fn(*args) if fn else data[key]
        monkeypatch.setattr(proc, name, read)

    monkeypatch.setattr(proc, "_gate_open", lambda ctx, kind: data.get("gate", {}).get(kind, True))
    reader("_load_live_lines", "lines")
    reader("_load_latest_arrivals", "arrivals", lambda names: {po: day for po, day in data["arrivals"].items() if po in names})
    reader("_load_month_records", "records")
    reader("_load_month_pos", "month_pos")
    reader("_load_po_line_amounts", "month_lines")
    reader("_load_payment_items", "pay")
    reader("_load_pr_lines", "pr")
    reader("_load_price_state", "price")
    reader("_load_await_pr", "await")
    reader("_load_uncoded", "uncoded")
    reader("_load_stage_counts", "stages")
    reader("_load_chain_counts", "chain")
    reader("_load_urgent", "urgent")

    # 2026-10-13：物料口径改成物料进度的行（同物料进度页的 SQL）。假数据按同一规则从 PO 行推出来：
    # 有来源（申请, 行）的、合同已生效、交期已过、没收齐或退货中；一个（申请, 行）一项，交期取最早的。
    def overdue_materials(today):
        if data.get("overdue_materials") is not None:
            return data["overdue_materials"]
        out = {}
        for row in data["lines"] or []:
            due = str(row["due"] or "")
            if not (row["source_request"] and row["source_line"]) or row["po_status"] not in proc.EFFECTIVE_PO or not due or due >= today:
                continue
            if float(row["received"] or 0) >= float(row["quantity"] or 0) and row["inspection"] != "退货中":
                continue
            key = f"{row['source_request']}:{row['source_line']}"
            item = out.setdefault(key, {"name": key, "request": row["source_request"], "line": row["source_line"],
                                        "project": row["project"], "item": row["item"], "due": due})
            item["due"] = min(item["due"], due)
        return list(out.values())

    data.update(overdue_materials=None, heads={}, breakdown={"request": {}, "pr": {}, "po": {}, "payment": {}})
    reader("_load_overdue_materials", "overdue_materials", overdue_materials)
    reader("_load_request_heads", "heads", lambda names: {key: value for key, value in data["heads"].items() if key in names})
    reader("_load_chain_breakdown", "breakdown")
    return data


def run(key, ctx):
    """和 core._run 一样：没权限就不调用块函数。"""
    entry = core.REGISTRY[key]
    return entry.fn(ctx) if entry.visible is None or entry.visible(ctx) else None


def full_ctx():
    return make_ctx(positions=("procurement_manager",), roles=("Employee", "Purchase Manager"))


def fill(world):
    world["lines"] = rich_lines()
    world["arrivals"] = {"PO-A": "2026-09-20", "PO-B": "2026-10-05"}
    world["records"] = [
        {"purchase_order": "PO-A", "record_type": "到货", "details_json": json.dumps([{"line": "A1x"}, {"line": "A2"}])},
        {"purchase_order": "PO-A", "record_type": "到货", "details_json": json.dumps([{"line": "A2"}])},      # 同一行分两次到货只算一次
        {"purchase_order": "PO-B", "record_type": "到货", "details_json": "不是 json"},                        # 明细坏了：这条登记算一项
        {"purchase_order": "PO-A", "record_type": "验收", "details_json": json.dumps(
            [{"line": "A2", "status": "已通过"}, {"line": "A3", "status": "换货中"}])},
        {"purchase_order": "PO-B", "record_type": "验收", "details_json": json.dumps([{"line": "B9", "status": "已通过"}])},
    ]
    world["month_pos"] = (
        [{"po": f"N{i}", "supplier": s, "amount": a, "month": "2026-10", "status": "已生效", "day": f"2026-10-0{i}"} for i, (s, a) in enumerate(
            [("甲", 100000), ("甲", 50000), ("乙", 30000), ("丙", 20000), ("丁", 10000), ("戊", 8000), ("己", 2000)], 1)]
        + [{"po": "P0", "supplier": "甲", "amount": 200000, "month": "2026-09", "status": "已关闭", "day": "2026-09-20"}])
    world["month_lines"] = [{"po": "N1", "project": "P1", "amount": 150000}, {"po": "N3", "project": "P2", "amount": 30000},
                            {"po": "N4", "project": "", "amount": 40000}]
    world["pay"] = [
        {"po": "PO-A", "work_status": "可提交付款审批", "amount": 50000, "paid": 0, "planned": "2026-10-20"},
        {"po": "PO-A", "work_status": "待到货资料", "amount": 30000, "paid": 0, "planned": "2026-10-01"},
        {"po": "PO-B", "work_status": "待实际付款", "amount": 20000, "paid": 5000, "planned": "2026-09-29"},
        {"po": "PO-C", "work_status": "已付款", "amount": 10000, "paid": 10000, "planned": "2026-09-01"},
        {"po": "PO-D", "work_status": "可提交付款审批", "amount": 20000, "paid": 0, "planned": ""},
    ]
    world["pr"] = [{"pr": "PR-1", "line": "a"}, {"pr": "PR-1", "line": "b"}, {"pr": "PR-2", "line": "c"}]
    world["price"] = {"pending": 2, "draft": 1, "unquoted": {"PA-1": 2}}
    world["await"] = [{"request": "R1", "line": "1"}, {"request": "R1", "line": "2"}, {"request": "R2", "line": "1"}]
    world["uncoded"] = [{"name": f"M{i}", "request": "R1"} for i in range(4)]
    world["stages"] = [
        {"stage": "采购确认中", "no_pr": 1, "total": 3}, {"stage": "采购确认中", "no_pr": 0, "total": 2},
        {"stage": "PO处理中", "no_pr": 0, "total": 4}, {"stage": "供应商制作中", "no_pr": 0, "total": 5},
        {"stage": "到货验收中", "no_pr": 0, "total": 2}, {"stage": "付款中", "no_pr": 0, "total": 1},
        {"stage": "已关闭", "no_pr": 0, "total": 6}, {"stage": "OA审批中", "no_pr": 0, "total": 9},
    ]
    world["chain"] = {"request": 40, "pr": 20, "po": 10, "payment": 25}
    world["urgent"] = [
        {"name": "OA-U1", "type": "采购申请", "subject": "伺服电机", "applicant": "演示员工129", "project": "RD03", "expected": "2026-10-08",
         "approving": False, "label": "PO 执行中", "since": "2026-10-01"},
        {"name": "OA-U2", "type": "购买申请", "subject": "打印机", "applicant": "演示员工146", "project": "", "expected": "",
         "approving": True, "label": "财务主管", "since": "2026-10-08"}]
    return world


def kpi_of(key, ctx=None):
    return run(key, ctx or full_ctx())


# ---------------------------------------------------------------- 注册和布局
def test_every_provider_in_the_layouts_is_registered_with_the_right_kind():
    registered = {key: entry.kind for key, entry in core.REGISTRY.items()}
    assert set(MINE) <= set(registered)
    assert {key for key in registered if key in MINE} == set(MINE)
    for key in KPIS:
        assert registered[key] == "kpi"
    for key in ALERTS:
        assert registered[key] == "alert"
    for key in BLOCKS:
        assert registered[key] == "block"
    wanted = layout.all_block_keys()
    assert {key for key in wanted if key.startswith("proc.")} <= set(KPIS)       # 布局里的采购指标一个不缺
    for key in ("alert.po_overdue", "alert.pay_planned_passed", "alert.price_missing_quote", "alert.uncoded",
                "alert.inspect_stale", "alert.material_overdue", "alert.risk_projects", "block.proc_chain",
                "block.arrival_inspect", "block.proc_suppliers", "block.proc_projects", "block.material_stage",
                "block.risk_projects", "block.week_schedule"):
        assert key in wanted


# ---------------------------------------------------------------- 权限
SCENARIO_ROLES = [(), ("Employee",), ("Purchase User",), ("Purchase Manager",), ("Accounts User",), ("Finance User",),
                  ("Rayher Business Executive",), ("System Manager",), ("Purchase User", "Accounts User")]
SCENARIO_POSITIONS = [(), ("pmc",), ("procurement_manager",), ("vice_manager",), ("general_manager",),
                      ("production_asset_owner",), ("finance_manager",), ("finance_accountant",), ("finance_auditor",),
                      ("hr_manager",), ("pmc", "production_asset_owner")]


def test_permission_helpers_match_the_existing_endpoint_checks(monkeypatch):
    """_has_chain_view / _has_po_view / _has_board 是抄 procurement_chain 和 material_progress 的规则；这里逐个组合对照，规则变了会在这里亮。"""
    from rayher_hr_payroll.api import material_progress as board
    from rayher_hr_payroll.api import procurement_chain as pc

    def fail(message, *args):
        raise ValueError(message)

    def passes(check):
        try:
            check()
            return True
        except ValueError:
            return False

    for roles in SCENARIO_ROLES:
        for positions in SCENARIO_POSITIONS:
            held = {key: ({"u@example.com"} if key in positions else set()) for key in
                    ("pmc", "procurement_manager", "vice_manager", "general_manager", "production_asset_owner")}

            def users(*keys, held=held):
                return {user for key in keys for user in held.get(key, set())}

            monkeypatch.setattr(pc, "frappe", NS(throw=fail))
            monkeypatch.setattr(pc, "position_users", users)
            monkeypatch.setattr(pc, "_user", lambda: "u@example.com")
            monkeypatch.setattr(pc, "_roles", lambda roles=roles: set(roles))
            monkeypatch.setattr(board, "position_users", users)
            monkeypatch.setattr(board, "frappe", NS(get_roles=lambda user=None, roles=roles: list(roles)))
            ctx = make_ctx(positions=positions, roles=roles)
            label = (roles, positions)
            assert proc._has_chain_view(ctx) == passes(pc._require_view), label
            assert proc._has_po_view(ctx) == passes(pc._require_po_view), label
            assert proc._has_board(ctx) == board.can_access_board("u@example.com"), label


def test_administrator_may_open_the_board_like_the_endpoint(monkeypatch):
    assert proc._has_board(make_ctx(user="Administrator"))
    assert not proc._has_board(make_ctx(user="clerk@example.com"))


def visible_keys(ctx):
    return {key for key in MINE if core.REGISTRY[key].visible(ctx)}


def test_visibility_by_identity(world):
    everything = set(MINE)
    manager = make_ctx(positions=("procurement_manager",), roles=("Employee", "Purchase Manager"))
    assert visible_keys(manager) == everything

    pmc = make_ctx(positions=("pmc",), roles=("Employee", "Purchase User", "Accounts User"))   # PMC 带着 Purchase User，也不给金额
    assert visible_keys(pmc) == everything - MONEY

    production = make_ctx(positions=("production_asset_owner",))
    assert visible_keys(production) == everything - MONEY - CHAIN - BOARD - URGENT

    accountant = make_ctx(positions=("finance_accountant",), roles=("Employee", "Accounts User"))
    assert visible_keys(accountant) == everything - CHAIN - BOARD - URGENT

    for positions in (("general_manager",), ("vice_manager",)):
        boss = make_ctx(positions=positions, roles=("Employee", "Accounts User", "Rayher Business Executive"))
        assert visible_keys(boss) == everything

    assert visible_keys(make_ctx()) == set()
    assert visible_keys(make_ctx(positions=("hr_manager",), roles=("Employee", "HR Manager"))) == set()


def test_pmc_who_also_holds_a_finance_or_purchase_position_keeps_the_union(world):
    for extra in ("procurement_manager", "vice_manager", "general_manager", "finance_accountant"):
        both = make_ctx(positions=("pmc", extra), roles=("Employee", "Purchase User", "Accounts User", "Rayher Business Executive"))
        assert MONEY <= visible_keys(both), extra
    admin = make_ctx(positions=("pmc",), roles=("Employee", "System Manager"))
    assert MONEY <= visible_keys(admin)


def test_feature_gates_hide_the_blocks_behind_them(world):
    manager = full_ctx()
    world["gate"] = {"payment": False}
    assert visible_keys(manager) == set(MINE) - {"proc.ready_to_pay", "proc.pay_planned_passed", "alert.pay_planned_passed"}
    world["gate"] = {"chain": False}
    assert visible_keys(manager) == BOARD | {"proc.ready_to_pay", "proc.pay_planned_passed", "alert.pay_planned_passed"}


def test_gate_open_asks_for_the_matching_request_type(monkeypatch):
    from rayher_hr_payroll import oa_feature_gate
    from rayher_hr_payroll.oa_document_types import REQUEST_PROCUREMENT, REQUEST_PROCUREMENT_PAYMENT

    asked = []
    monkeypatch.setattr(oa_feature_gate, "can_access_request_type", lambda request_type, user=None: asked.append((request_type, user)) or False)
    ctx = make_ctx(user="who@example.com")
    assert proc._gate_open(ctx, "chain") is False and proc._gate_open(ctx, "payment") is False
    assert asked == [(REQUEST_PROCUREMENT, "who@example.com"), (REQUEST_PROCUREMENT_PAYMENT, "who@example.com")]


def test_hidden_blocks_never_touch_the_data(world):
    """没权限的人拿到整页：什么都没有，也没有读过任何数据（权限异常不会被当成块失败吞掉）。"""
    spec = {"note": "", "tabs": [layout.tab("overview", "总览", kpis=KPIS, alerts=ALERTS, blocks=BLOCKS)]}
    page = core.assemble(make_ctx(profile="employee"), spec)["pages"]["overview"]
    assert (page["kpis"], page["alerts"], page["blocks"], page["errors"]) == ([], [], [], [])
    assert world["calls"] == []


def test_pmc_page_has_no_money_and_does_not_read_money_data(world):
    fill(world)
    world["pay"] = None            # 付款数据 / 金额数据一旦被读，下面直接炸
    world["month_pos"] = None
    pmc = make_ctx(positions=("pmc",), roles=("Employee", "Purchase User", "Accounts User"), profile="pmc")
    out = core.assemble(pmc, layout.LAYOUTS["pmc"], include_todos=False)
    page = out["pages"]["overview"]
    assert page["errors"] == []
    assert page["kpis"] and page["alerts"] and page["blocks"]
    text = json.dumps(page, ensure_ascii=False)
    assert not re.search(r"¥|\d\s*(万|元)", text), text
    assert "_load_payment_items" not in world["calls"] and "_load_month_pos" not in world["calls"]
    assert {item["key"] for item in page["kpis"]} == {"proc.await_pr", "proc.material_overdue", "proc.week_arrive", "proc.uncoded",
                                                      "proc.po_transit", "proc.risk_projects", "proc.price_pending"}


def test_production_owner_page_only_has_arrival_and_inspection(world, monkeypatch):
    fill(world)
    fake(monkeypatch, {"OA Purchase Order Line": []})
    owner = make_ctx(positions=("production_asset_owner",), profile="production_asset_owner")
    page = core.assemble(owner, layout.LAYOUTS["production_asset_owner"], include_todos=False)["pages"]["overview"]
    assert page["errors"] == []
    assert [item["key"] for item in page["kpis"]] == ["proc.to_arrive", "proc.to_inspect", "proc.week_arrive", "proc.po_overdue",
                                                      "proc.exchange", "proc.return", "proc.month_inspected", "proc.month_arrived"]
    assert [item["key"] for item in page["alerts"]] == ["alert.inspect_stale", "alert.po_overdue"]
    assert [item["key"] for item in page["blocks"]] == ["block.week_cols", "block.inspect_aging", "block.week_schedule", "block.arrival_inspect"]
    for item in page["kpis"] + page["alerts"]:      # 生产主管看不了价格审批页：卡片点进去是明细清单，清单里每一行去采购付款页
        assert item["target"] is None or item["target"]["key"] == "drill", item["key"]
        if item["target"]:
            detail = core.get_detail_for(owner, item["target"]["params"]["item"])
            assert detail is not None and all(row["target"]["key"] == "procpay.work" for row in detail["rows"]), item["key"]
    assert not re.search(r"¥|\d\s*(万|元)", json.dumps(page, ensure_ascii=False))


def test_every_layout_that_uses_these_blocks_renders_without_errors(world):
    fill(world)
    boss_roles = ("Employee", "Accounts User", "Rayher Business Executive")
    ctxs = {
        "general_manager": make_ctx(positions=("general_manager",), roles=boss_roles),
        "vice_manager": make_ctx(positions=("vice_manager",), roles=boss_roles),
        "procurement_manager": full_ctx(),
        "pmc": make_ctx(positions=("pmc",), roles=("Employee", "Purchase User")),
        "production_asset_owner": make_ctx(positions=("production_asset_owner",)),
    }
    for profile, ctx in ctxs.items():
        ctx.profile = profile
        out = core.assemble(ctx, layout.LAYOUTS[profile], include_todos=False)
        for page in out["pages"].values():
            assert [e for e in page["errors"] if e["key"] in MINE] == [], profile
            for block in page["blocks"]:
                assert block["error"] is None, (profile, block["key"])


# ---------------------------------------------------------------- 物料行分类（纯函数）
def test_classify_puts_each_line_in_the_right_buckets():
    from datetime import date

    data = proc.classify(rich_lines(), date(2026, 10, 9))
    names = lambda key: sorted(row["line"] for row in data[key])
    assert names("transit") == ["A1", "B1", "B3", "E1", "E2"]
    assert names("to_arrive") == ["A1", "B1", "E1", "E2"]            # 退货中的 B3 不算待到货
    assert names("to_inspect") == ["A2", "B1"]                        # B1 部分到货：还差货也有已到的部分待验
    assert names("exchange") == ["B2"] and names("returning") == ["B3"]
    assert names("overdue") == ["A1", "B3"]                           # E1 没填交期、E2 交期是今天、草稿 PO 的 D1：都不算逾期
    assert names("week") == ["B1", "E2"]
    assert all(row["po"] != "PO-D" for rows in data.values() for row in rows)


def test_month_events_dedupes_lines_and_survives_bad_details(world):
    fill(world)
    assert proc.month_events(world["records"]) == (3, 2)
    assert proc.month_events([]) == (0, 0)
    assert proc.month_events([{"purchase_order": "X", "record_type": "验收", "details_json": None}]) == (0, 0)
    assert proc.month_events([{"purchase_order": "X", "record_type": "到货", "details_json": "[1, 2]"}]) == (1, 0)


# ---------------------------------------------------------------- 指标卡：有数据
def test_po_and_arrival_kpis_with_data(world):
    fill(world)
    ctx = full_ctx()
    transit = kpi_of("proc.po_transit", ctx)
    assert (transit["value"], transit["unit"], transit["sub"]) == ("3", "个", "待到货 4 项 · 待验收 2 项")
    assert transit["target"] == {"key": "drill", "params": {"item": "proc.po_transit", "period": "2026-10"}}
    overdue = kpi_of("proc.po_overdue", ctx)
    assert (overdue["value"], overdue["tone"], overdue["sub"]) == ("2", "bad", "最久逾期 9 天 · 共 2 项物料")
    arrive = kpi_of("proc.to_arrive", ctx)
    assert (arrive["value"], arrive["sub"], arrive["target"]["params"]["item"]) == ("4", "来自 3 个 PO", "proc.to_arrive")
    inspect = kpi_of("proc.to_inspect", ctx)
    assert (inspect["value"], inspect["sub"], inspect["tone"]) == ("2", "最久到货 19 天", "bad")      # PO-A 到货 19 天，超过 7 天
    assert inspect["target"]["params"]["item"] == "proc.to_inspect"
    week = kpi_of("proc.week_arrive", ctx)
    assert (week["value"], week["sub"]) == ("2", "来自 2 个 PO")
    assert kpi_of("proc.exchange", ctx)["value"] == "1" and kpi_of("proc.return", ctx)["value"] == "1"
    assert kpi_of("proc.month_arrived", ctx)["value"] == "3" and kpi_of("proc.month_inspected", ctx)["value"] == "2"


def test_to_inspect_is_only_bad_when_something_is_stale(world):
    fill(world)
    world["arrivals"] = {"PO-A": "2026-10-05", "PO-B": "2026-10-05"}      # 都只有 4 天
    inspect = kpi_of("proc.to_inspect")
    assert (inspect["tone"], inspect["sub"]) == ("hot", "最久到货 4 天")
    world["arrivals"] = {"PO-A": "2026-10-02"}                              # 恰好 7 天：不含，不算久拖
    assert kpi_of("proc.to_inspect")["tone"] == "hot"
    world["arrivals"] = {"PO-A": "2026-10-01"}                              # 8 天
    assert kpi_of("proc.to_inspect")["tone"] == "bad"


def test_chain_and_material_kpis_with_data(world):
    fill(world)
    ctx = full_ctx()
    compare = kpi_of("proc.to_compare", ctx)
    assert (compare["value"], compare["unit"], compare["sub"], compare["target"]["params"]) == ("3", "项", "来自 2 张 PR", {"view": "source"})
    pending = kpi_of("proc.price_pending", ctx)
    # 2026-10-13：点进去是价格审批单列表筛「待审批」
    assert (pending["value"], pending["sub"], pending["target"]["params"]) == ("2", "另有 1 张还在比价（草稿）", {"view": "approvals", "status": "pending"})
    await_pr = kpi_of("proc.await_pr", ctx)
    assert (await_pr["value"], await_pr["sub"], await_pr["tone"]) == ("2", "共 3 项物料", "hot")
    # 2026-10-13：点进去是同一份数据的明细（原来去采购申请列表，那里的阶段规则不一样）
    assert await_pr["target"] == {"key": "drill", "params": {"item": "proc.await_pr", "period": "2026-10"}}
    uncoded = kpi_of("proc.uncoded", ctx)
    assert (uncoded["value"], uncoded["tone"], uncoded["target"]["key"]) == ("4", "hot", "material.progress")
    material = kpi_of("proc.material_overdue", ctx)
    # 物料口径 = 物料进度的行：没有来源的 PO 行（B3）不在物料进度看板上，不算（2026-10-13）
    assert (material["value"], material["sub"], material["tone"], material["target"]["key"]) == ("1", "最久逾期 8 天", "bad", "material.overdue")
    risk = kpi_of("proc.risk_projects", ctx)
    assert (risk["value"], risk["unit"]) == ("1", "个")          # 只有 P1 一个项目（B3 没填项目）


def test_payment_kpis_with_data(world):
    fill(world)
    ctx = full_ctx()
    ready = kpi_of("proc.ready_to_pay", ctx)
    assert (ready["value"], ready["sub"], ready["tone"]) == ("2", "合计 7.0 万", "hot")
    assert ready["target"] == {"key": "procpay.work", "params": {"status": "可提交付款审批"}}
    passed = kpi_of("proc.pay_planned_passed", ctx)
    # 过期未付的两期：3 万（没付）+ 1.5 万（付了 5000 还差 1.5 万）；没填计划日的、已付款的不算
    assert (passed["value"], passed["sub"], passed["tone"]) == ("2", "未付 4.5 万 · 最久 10 天", "bad")


def test_month_amount_and_suppliers(world):
    fill(world)
    world["month_lines"].append({"po": "P0", "project": "", "amount": 200000})      # 2026-10-13：金额按物料行合计
    ctx = full_ctx()
    amount = kpi_of("proc.month_amount", ctx)
    assert (amount["value"], amount["unit"], amount["sub"]) == ("22.0", "万", "较上月 +10.0%")
    suppliers = kpi_of("proc.suppliers_count", ctx)
    assert (suppliers["value"], suppliers["unit"], suppliers["sub"]) == ("6", "家", "共 7 张 PO")
    world["month_pos"] = [{"po": "N1", "supplier": "甲", "amount": 5000, "month": "2026-10"}]
    world["month_lines"] = [{"po": "N1", "project": "", "amount": 5000}]
    small = kpi_of("proc.month_amount", full_ctx())            # 同一个 ctx 里读过的数据会被记住，换数据要换 ctx
    assert (small["value"], small["unit"], small["sub"]) == ("5,000", "元", "上月没有采购")


# ---------------------------------------------------------------- 指标卡：没有数据
def test_kpis_show_zero_when_there_is_nothing(world):
    ctx = make_ctx(positions=("vice_manager",), roles=("Employee", "Accounts User", "Rayher Business Executive"))
    for key in KPIS:
        item = run(key, ctx)
        assert item is not None, key
        if key == "proc.month_amount":
            assert (item["value"], item["unit"], item["sub"]) == ("0", "元", "本月还没有下单")
        else:
            assert item["value"] == "0", key
            assert item["sub"] == "" and item["tone"] == "", key


def test_alerts_stay_quiet_when_nothing_triggers(world):
    ctx = make_ctx(positions=("vice_manager",), roles=("Employee", "Accounts User", "Rayher Business Executive"))
    for key in ALERTS:
        assert run(key, ctx) is None, key


def test_blocks_are_empty_but_present_without_data(world):
    ctx = make_ctx(positions=("vice_manager",), roles=("Employee", "Accounts User", "Rayher Business Executive"))
    for key in ("block.proc_suppliers", "block.proc_projects", "block.risk_projects", "block.week_schedule"):
        block = run(key, ctx)
        assert block["rows"] == [] and block["error"] is None, key
    assert run("block.week_schedule", ctx)["sub"] == "本周没有预计到货的物料"
    for key in ("block.proc_chain", "block.arrival_inspect", "block.material_stage"):
        block = run(key, ctx)
        assert all(row["value"] == "0" and row["pct"] == 0 for row in block["rows"]), key


# ---------------------------------------------------------------- 提醒：有数据
def test_alerts_with_data(world):
    fill(world)
    ctx = full_ctx()
    overdue = run("alert.po_overdue", ctx)
    assert (overdue["tone"], overdue["title"], overdue["sub"]) == ("bad", "2 个 PO 已过合同交期还没收齐", "最久逾期 9 天（PO-B）")
    passed = run("alert.pay_planned_passed", ctx)
    assert (passed["tone"], passed["title"], passed["sub"]) == ("bad", "2 期采购付款已过计划付款日", "未付 4.5 万，最久 10 天，供应商可能催款")
    missing = run("alert.price_missing_quote", ctx)
    assert (missing["tone"], missing["title"], missing["sub"]) == ("warn", "1 张待审批的价格审批单有物料没有报价", "共 2 项物料一个报价都没有，副总没法选供应商")
    assert run("alert.uncoded", ctx)["title"] == "4 项物料还没有物料编码"
    stale = run("alert.inspect_stale", ctx)
    assert (stale["tone"], stale["title"], stale["sub"]) == ("bad", "1 个 PO 到货超过 7 天还没验收", "PO-A 已到货 19 天，可能耽误付款")
    assert stale["target"]["params"]["item"] == "proc.inspect_stale"
    material = run("alert.material_overdue", ctx)
    assert (material["tone"], material["title"]) == ("bad", "1 项物料超过合同交期还没到")      # 没有来源的 B3 不算（2026-10-13）
    risk = run("alert.risk_projects", ctx)
    assert (risk["title"], risk["sub"]) == ("1 个项目有物料逾期未到", "P1 有 1 项物料逾期")


def test_overdue_alert_is_only_a_warning_within_a_week(world):
    world["lines"] = [line("PO-A", 10, 0, due="2026-10-05", sr="R1", sl="1", name="A1")]       # 逾期 4 天
    assert run("alert.po_overdue", full_ctx())["tone"] == "warn"
    assert run("alert.material_overdue", full_ctx())["tone"] == "warn"
    world["lines"] = [line("PO-A", 10, 0, due="2026-10-02", name="A1")]       # 逾期 7 天：超过 7 天才标红
    assert run("alert.po_overdue", full_ctx())["tone"] == "warn"
    world["lines"] = [line("PO-A", 10, 0, due="2026-10-01", name="A1")]
    assert run("alert.po_overdue", full_ctx())["tone"] == "bad"


def test_overdue_ignores_received_lines_and_dead_pos(world):
    world["lines"] = [
        line("PO-A", 10, 10, state="已通过", due="2026-09-01", name="A1"),                 # 收齐了
        line("PO-B", 10, 0, due="2026-09-01", status="已关闭", name="B1"),                 # 已关闭
        line("PO-C", 10, 0, due="2026-09-01", status="待电子用印", name="C1"),             # 合同没生效
        line("PO-D", 10, 0, due="", name="D1"),                                            # 没填合同交期
    ]
    assert kpi_of("proc.po_overdue")["value"] == "0"
    assert run("alert.po_overdue", full_ctx()) is None


# ---------------------------------------------------------------- 图表块
def test_proc_chain_scales_to_the_biggest_stage(world):
    fill(world)
    block = run("block.proc_chain", full_ctx())
    assert block["type"] == "bars" and "累计" in block["hint"] and "累计" in block["sub"]
    assert [(r["label"], r["value"], r["pct"]) for r in block["rows"]] == [
        ("OA 申请", "40", 100.0), ("PR", "20", 50.0), ("PO", "10", 25.0), ("付款期次", "25", 62.5)]


def test_arrival_inspect_rows(world):
    fill(world)
    block = run("block.arrival_inspect", full_ctx())
    assert [(r["label"], r["value"], r["tone"]) for r in block["rows"]] == [
        ("本月已到货", "3", "ok"), ("本月已验收通过", "2", "ok"), ("待验收", "2", "warn"), ("待到货", "4", "")]
    assert [r["pct"] for r in block["rows"]] == [75.0, 50.0, 50.0, 100.0]


def test_supplier_and_project_blocks_top5_plus_other(world):
    fill(world)
    ctx = full_ctx()
    suppliers = run("block.proc_suppliers", ctx)
    # 2026-10-13：金额 = 物料行金额合计（N1 15 万、N3 3 万、N4 4 万；其余 PO 没有物料行金额，不上榜）
    assert [(r["label"], r["value"]) for r in suppliers["rows"]] == [("甲", "15.0 万"), ("丙", "4.0 万"), ("乙", "3.0 万")]
    assert suppliers["rows"][0]["pct"] == 100.0 and suppliers["rows"][2]["pct"] == 20.0
    projects = run("block.proc_projects", ctx)
    assert [(r["label"], r["value"]) for r in projects["rows"]] == [("P1", "15.0 万"), ("非项目", "4.0 万"), ("P2", "3.0 万")]
    world["month_pos"] = [{"po": "N1", "supplier": "", "amount": 100, "month": "2026-10"}]
    assert run("block.proc_suppliers", full_ctx())["rows"][0]["label"] == "未填供应商"


def test_material_stage_mapping(world):
    fill(world)
    block = run("block.material_stage", make_ctx(positions=("pmc",)))
    # 2026-10-13：阶段名和物料进度页的阶段条一样（点进去能对上）；还没提 PR 的单独在副标题里说
    assert [(r["label"], r["value"]) for r in block["rows"]] == [
        ("OA审批中", "9"), ("采购确认中", "5"), ("PO处理中", "4"), ("供应商制作中", "5"), ("到货验收中", "2"), ("付款中", "1"), ("已关闭", "6")]
    assert [r["pct"] for r in block["rows"]] == [100.0, 55.6, 44.4, 55.6, 22.2, 11.1, 66.7]
    assert block["rows"][6]["tone"] == "ok" and "采购确认中有 3 项还没提 PR" in block["sub"]


def test_risk_projects_list(world):
    fill(world)
    world["lines"] = [
        line("PO-A", 10, 0, due="2026-09-20", project="ACONCA 7961", item="镜片", sr="R1", sl="1", name="1"),
        line("PO-A", 10, 0, due="2026-09-25", project="ACONCA 7961", item="导轨", sr="R1", sl="2", name="2"),
        line("PO-A", 10, 5, due="2026-09-26", project="ACONCA 7961", item="底板", sr="R1", sl="3", name="3"),
        line("PO-B", 10, 0, due="2026-10-07", project="RD14", item="连接器", sr="R2", sl="1", name="4"),
        line("PO-B", 10, 0, due="2026-10-07", project="", item="无项目", sr="R2", sl="2", name="5"),
    ]
    block = run("block.risk_projects", make_ctx(positions=("pmc",)))
    assert [(r["label"], r["sub"], r["value"], r["tone"]) for r in block["rows"]] == [
        ("ACONCA 7961", "镜片、导轨 等", "3 项", "bad"), ("RD14", "连接器", "1 项", "warn")]
    assert block["more"] == "" and block["target"]["params"]["item"] == "proc.risk_projects"
    assert kpi_of("proc.risk_projects")["value"] == "2" and kpi_of("proc.material_overdue")["value"] == "5"
    detail = core.get_detail_for(make_ctx(positions=("pmc",)), "proc.risk_projects")
    assert len(detail["rows"]) == 2 and detail["summary"] == "共 2 个项目"
    assert detail["rows"][0]["cells"] == ["ACONCA 7961", "3 项", "19 天", "镜片、导轨、底板"] and detail["rows"][0]["target"]["key"] == "material.overdue"


def test_risk_projects_list_is_cut_at_six(world):
    world["lines"] = [line("PO-A", 1, 0, due="2026-09-01", project=f"P{i}", sr=f"R{i}", sl="1", name=str(i)) for i in range(8)]
    block = run("block.risk_projects", make_ctx(positions=("pmc",)))
    assert len(block["rows"]) == 6 and block["more"] == "还有 2 个项目"


def test_week_schedule_groups_by_day(world):
    fill(world)
    world["lines"] += [line("PO-F", 3, 0, due="2026-10-07", name="F1"), line("PO-G", 3, 1, due="2026-10-07", name="G1"),
                       line("PO-H", 3, 0, due="2026-10-12", name="H1")]            # 下周一不在本周里
    block = run("block.week_schedule", make_ctx(positions=("production_asset_owner",)))
    assert [(r["label"], r["sub"], r["value"], r["tone"]) for r in block["rows"]] == [
        ("10-07 周三", "2 个 PO：PO-F、PO-G", "2 项", "bad"),
        ("10-09 周五", "1 个 PO：PO-E", "1 项", "warn"),
        ("10-10 周六", "1 个 PO：PO-B", "1 项", "")]


# ---------------------------------------------------------------- 目标
def test_all_targets_are_registered_and_params_checked(world):
    fill(world)
    ctx = make_ctx(positions=("general_manager",), roles=("Employee", "Accounts User", "Rayher Business Executive"))
    production = make_ctx(positions=("production_asset_owner",))
    seen = set()
    for who in (ctx, production):
        for key in MINE:
            item = run(key, who)
            if item is None:
                continue
            for target in [item.get("target")] + [row.get("target") for row in item.get("rows", []) if isinstance(row, dict)]:
                if target:
                    seen.add(target["key"])
                    assert target["key"] in core.load_targets()
    # 待提 PR 不再去采购申请列表（2026-10-13，改成同一份数据的明细清单）
    assert seen == {"drill", "price.approvals", "procpay.work", "material.progress", "material.overdue",
                    "procurement.detail", "directpurchase.detail"}
    assert proc._po_open(production, "PO-A") == {"key": "procpay.work", "params": {"po": "PO-A"}}
    assert proc._po_open(full_ctx(), "PO-A") == {"key": "price.po", "params": {"po": "PO-A"}}


# ---------------------------------------------------------------- 明细清单：点卡片进去，条数 / 合计和卡片上的数字一致
def detail_of(ctx, key):
    return core.get_detail_for(ctx, key)


def test_po_lists_have_the_same_pos_as_the_cards(world):
    fill(world)
    ctx = full_ctx()
    transit = kpi_of("proc.po_transit", ctx)
    detail = detail_of(ctx, "proc.po_transit")
    assert len(detail["rows"]) == int(transit["value"]) == 3 and detail["summary"] == "共 3 个 PO，5 项物料"
    assert [row["cells"][0] for row in detail["rows"]] == ["PO-B", "PO-A", "PO-E"]               # 交期最早的在前
    assert detail["rows"][0]["cells"] == ["PO-B", "甲", "到货验收中", "2 项", "2026-09-30", "9 天"]
    assert detail["rows"][2]["cells"][4:] == [TODAY, "—"]                                          # 今天到期不算逾期
    assert all(row["target"] == {"key": "price.po", "params": {"po": row["cells"][0]}} for row in detail["rows"])
    overdue = kpi_of("proc.po_overdue", ctx)
    detail = detail_of(ctx, "proc.po_overdue")
    assert len(detail["rows"]) == int(overdue["value"]) == 2 and [row["cells"][0] for row in detail["rows"]] == ["PO-B", "PO-A"]
    assert [row["tone"] for row in detail["rows"]] == ["bad", "bad"] and detail["summary"] == "共 2 个 PO，2 项物料"


def test_material_line_lists_have_the_same_lines_as_the_cards(world):
    fill(world)
    ctx = full_ctx()
    for card, item in (("proc.week_arrive", "proc.week_arrive"), ("proc.to_arrive", "proc.to_arrive"), ("proc.to_inspect", "proc.to_inspect"),
                       ("proc.exchange", "proc.exchange"), ("proc.return", "proc.return")):
        value = int(kpi_of(card, ctx)["value"])
        detail = detail_of(ctx, item)
        assert len(detail["rows"]) == value, card
        assert detail["summary"].startswith(f"共 {value} 项物料"), card
    week = detail_of(ctx, "proc.week_arrive")
    assert [row["cells"] for row in week["rows"]] == [["10-09 周五", "PO-E", "—", "0 / 6", "—"], ["10-10 周六", "PO-B", "—", "2 / 4", "—"]]
    assert [row["tone"] for row in week["rows"]] == ["warn", ""]                                    # 今天标黄
    inspect = detail_of(ctx, "proc.to_inspect")
    assert [row["cells"][0] for row in inspect["rows"]] == ["PO-A", "PO-B"] and inspect["rows"][0]["cells"][3] == "19 天"
    assert inspect["rows"][0]["tone"] == "bad" and inspect["rows"][1]["tone"] == ""
    stale = detail_of(ctx, "proc.inspect_stale")
    assert [row["cells"] for row in stale["rows"]] == [["PO-A", "甲", "1 项", "19 天"]]
    assert [row["cells"][0] for row in detail_of(ctx, "proc.inspect_wait")["rows"]] == ["PO-A", "PO-B"]       # 等得久的在前


def test_month_event_lists_name_the_material_lines_that_were_counted(world, monkeypatch):
    fill(world)
    fake(monkeypatch, {"OA Purchase Order Line": [{"name": "A2", "item_name": "导轨"}, {"name": "B9", "item_name": "镜片"}]})
    world["records"] = [dict(row, record_date="2026-10-0" + str(index + 1)) for index, row in enumerate(world["records"])]
    ctx = full_ctx()
    arrived = detail_of(ctx, "proc.month_arrived")
    assert len(arrived["rows"]) == int(kpi_of("proc.month_arrived", ctx)["value"]) == 3
    assert {row["cells"][2] for row in arrived["rows"]} == {"导轨", "（登记没写明细）"}
    inspected = detail_of(ctx, "proc.month_inspected")
    assert len(inspected["rows"]) == int(kpi_of("proc.month_inspected", ctx)["value"]) == 2
    assert {tuple(row["cells"][1:]) for row in inspected["rows"]} == {("PO-A", "导轨"), ("PO-B", "镜片")}
    assert proc.month_event_items([{"purchase_order": "X", "record_type": "到货", "details_json": "[1, 2]", "record_date": "2026-10-02"}])[0] == {("X", "record-0"): "2026-10-02"}


def test_money_lists_add_up_to_the_cards(world):
    fill(world)
    ctx = full_ctx()
    amount = detail_of(ctx, "proc.month_amount")
    assert len(amount["rows"]) == 7 and amount["summary"] == "共 7 个 PO，合计 22.0 万"
    assert amount["rows"][0]["cells"] == ["N1", "甲", "已生效", "2026-10-01", "¥ 150,000.00"]       # 物料行金额合计（2026-10-13）
    suppliers = detail_of(ctx, "proc.suppliers")
    assert suppliers["summary"] == "共 6 家，7 张 PO" and int(kpi_of("proc.suppliers_count", ctx)["value"]) == 6
    assert suppliers["rows"][0]["cells"] == ["甲", "2 张", "¥ 150,000.00"]
    projects = detail_of(ctx, "proc.projects")
    assert [row["cells"] for row in projects["rows"]] == [["P1", "¥ 150,000.00"], ["非项目", "¥ 40,000.00"], ["P2", "¥ 30,000.00"]]
    passed = detail_of(ctx, "proc.pay_planned_passed")
    assert len(passed["rows"]) == int(kpi_of("proc.pay_planned_passed", ctx)["value"]) == 2
    assert [row["cells"][:2] for row in passed["rows"]] == [["PO-B", "2026-09-29"], ["PO-A", "2026-10-01"]]
    assert passed["summary"] == "共 2 期，未付 4.5 万" and passed["rows"][0]["cells"][4] == "10 天"
    plan = detail_of(ctx, "proc.pay_plan")
    assert [row["cells"][1] for row in plan["rows"]] == ["2026-09-29", "2026-10-01", "2026-10-20", "没排期"]
    assert all(row["target"]["key"] == "procpay.work" for row in plan["rows"])


def test_a_card_with_nothing_behind_it_does_not_link_to_an_empty_list(world):
    ctx = make_ctx(positions=("vice_manager",), roles=("Employee", "Accounts User", "Rayher Business Executive"))
    for key in ("proc.po_transit", "proc.po_overdue", "proc.pay_planned_passed", "proc.month_amount", "proc.suppliers_count", "proc.risk_projects",
                "proc.week_arrive", "proc.to_arrive", "proc.to_inspect", "proc.exchange", "proc.return", "proc.month_inspected", "proc.month_arrived",
                "proc.urgent"):
        assert run(key, ctx)["target"] is None, key


# ---------------------------------------------------------------- 加急采购（老板、采购、PMC）
def test_urgent_card_alert_block_and_list(world):
    fill(world)
    ctx = full_ctx()
    card = kpi_of("proc.urgent", ctx)
    assert (card["value"], card["unit"], card["tone"]) == ("2", "张", "bad")
    assert card["sub"] == "1 张超过 3 天没动静 · 1 张已过期望到货日"
    assert card["target"] == {"key": "drill", "params": {"item": "proc.urgent", "period": "2026-10"}}
    alert = run("alert.urgent", ctx)
    assert (alert["tone"], alert["title"]) == ("bad", "1 张加急采购超过 3 天没动静")
    assert alert["sub"] == "最久的 OA-U1（伺服电机）卡在「PO 执行中」8 天" and alert["target"] == card["target"]
    block = run("block.urgent_requests", ctx)
    assert [(row["label"], row["sub"], row["value"], row["tone"]) for row in block["rows"]] == [
        ("伺服电机", "PO 执行中 · 演示员工129 · RD03", "8 天", "bad"), ("打印机", "财务主管 · 演示员工146", "1 天", "warn")]
    assert [row["target"] for row in block["rows"]] == [{"key": "procurement.detail", "params": {"request": "OA-U1"}},
                                                         {"key": "directpurchase.detail", "params": {"request": "OA-U2"}}]
    detail = detail_of(ctx, "proc.urgent")
    assert len(detail["rows"]) == int(card["value"]) and detail["summary"] == "共 2 张"
    assert detail["rows"][0]["cells"] == ["OA-U1", "采购申请", "伺服电机", "演示员工129", "RD03", "PO 执行中", "8 天", "2026-10-08"]
    assert [row["tone"] for row in detail["rows"]] == ["bad", "hot"]


def test_urgent_quiet_when_everything_is_moving(world):
    world["urgent"] = [{"name": "OA-U3", "type": "购买申请", "subject": "", "applicant": "演示员工157", "project": "", "expected": "2026-10-30",
                        "approving": True, "label": "直属主管", "since": "2026-10-08"}]
    ctx = full_ctx()
    card = kpi_of("proc.urgent", ctx)
    assert (card["value"], card["sub"], card["tone"]) == ("1", "都在正常推进", "hot")
    assert run("alert.urgent", ctx) is None
    assert run("block.urgent_requests", ctx)["rows"][0]["label"] == "OA-U3"          # 没填事由就显示单号


def test_urgent_is_seen_by_the_bosses_procurement_and_pmc_but_not_by_production_or_finance(world):
    fill(world)
    seen = lambda ctx: core.REGISTRY["proc.urgent"].visible(ctx)
    # 2026-10-13：还要能打开申请详情（详情按角色给读权限），所以带上这些岗位本来就有的角色
    for positions, roles in ((("general_manager",), "Rayher Business Executive"), (("vice_manager",), "Rayher Business Executive"),
                             (("procurement_manager",), "Purchase Manager"), (("pmc",), "Purchase User")):
        assert seen(make_ctx(positions=positions, roles=("Employee", roles))), positions
    assert seen(make_ctx(roles=("Employee", "Rayher Business Executive")))
    assert not seen(make_ctx(positions=("production_asset_owner",)))
    assert not seen(make_ctx(positions=("finance_accountant",), roles=("Employee", "Accounts User")))
    assert not seen(make_ctx())


def test_the_boss_procurement_tab_leads_with_urgent_purchases_and_has_no_pmc_only_blocks():
    for profile in ("general_manager", "vice_manager"):
        tab = next(item for item in layout.LAYOUTS[profile]["tabs"] if item["key"] == "proc")
        assert tab["label"] == "采购" and tab["kpis"][0] == "proc.urgent" and tab["blocks"][0] == "block.urgent_requests"
        assert "alert.urgent" in tab["alerts"]
        overview = layout.LAYOUTS[profile]["tabs"][0]
        assert "proc.urgent" in overview["kpis"] and "alert.urgent" in overview["alerts"]


def test_load_urgent_keeps_unfinished_ones_and_names_where_each_one_is(monkeypatch):
    from rayher_hr_payroll.api import oa_entry

    rows = [
        {"name": "U1", "request_type": "采购申请", "subject": " 伺服电机 ", "employee_name": "演示员工129", "project": "RD03", "workflow_status": "已完成",
         "business_status": "需求已批准/待询价", "current_step_label": "", "expected_delivery_date": "2026-10-20", "creation": "2026-09-28 09:00:00"},
        {"name": "U2", "request_type": "购买申请", "subject": "打印机", "employee_name": "演示员工146", "project": None, "workflow_status": "待审批",
         "business_status": "待审批", "current_step_label": "财务主管", "expected_delivery_date": None, "creation": "2026-10-06 09:00:00",
         "operation_log": json.dumps([{"action": "提交申请", "acted_on": "2026-10-05 08:00:00"}])},
        {"name": "U3", "request_type": "购买申请", "subject": "显示器", "employee_name": "演示员工157", "project": "", "workflow_status": "已完成",
         "business_status": "已付款", "current_step_label": "", "expected_delivery_date": None, "creation": "2026-09-01 09:00:00"},
        {"name": "U4", "request_type": "采购申请", "subject": "导轨", "employee_name": "演示员工175", "project": "", "workflow_status": "已完成",
         "business_status": "需求已批准/待询价", "current_step_label": "", "expected_delivery_date": None, "creation": "2026-09-01 09:00:00"},
        {"name": "U5", "request_type": "购买申请", "subject": "鼠标", "employee_name": "演示员工179", "project": "", "workflow_status": "已完成",
         "business_status": "待付款", "current_step_label": "", "expected_delivery_date": None, "creation": "2026-09-30 09:00:00",
         "modified": "2026-10-02 08:00:00"}]
    steps = [{"parent": "U1", "acted_on": "2026-10-02 10:00:00"}, {"parent": "U1", "acted_on": "2026-10-04 10:00:00"}]
    stages = {"U1": {"stage": "po", "label": "PO 执行中"}, "U4": {"stage": "closed", "label": "采购已关闭"}}

    def get_all(doctype, filters=None, **kwargs):
        if doctype == "OA Approval Request":
            assert filters["urgency"] == "加急" and filters["request_type"] == ["in", ["采购申请", "购买申请"]]
            assert filters["workflow_status"] == ["not in", ["草稿", "已拒绝", "已撤回", "已取消"]]
            return rows
        if doctype != "OA Approval Step":
            return []                       # 采购链路单据（2026-10-13 起也算“动静”）：这里没有
        return steps

    monkeypatch.setattr(proc, "frappe", NS(get_all=get_all, get_doc=lambda doctype, name: NS(name=name)))
    monkeypatch.setattr(oa_entry, "_calculate_procurement_chain", lambda doc: stages[doc.name])
    got = {item["name"]: item for item in proc._load_urgent()}
    assert sorted(got) == ["U1", "U2", "U5"]                       # 已付款、采购已关闭的不算在途
    assert (got["U1"]["label"], got["U1"]["since"], got["U1"]["subject"], got["U1"]["expected"]) == ("PO 执行中", "2026-10-04", "伺服电机", "2026-10-20")
    assert (got["U2"]["label"], got["U2"]["approving"], got["U2"]["since"], got["U2"]["project"]) == ("财务主管", True, "2026-10-05", "")
    # 最近一次签批 > 最近一次“提交申请”（操作记录）> 最后修改 > 创建：和申请页上的“已等几天”同一个起点
    assert (got["U5"]["label"], got["U5"]["approving"], got["U5"]["since"]) == ("待付款", False, "2026-10-02")


# ---------------------------------------------------------------- 读取函数（假 frappe，验证过滤条件和 Python 侧的整理）
class FakeFrappe:
    def __init__(self, tables, counts=None, sql_rows=None):
        self.tables, self.queries, self.counts, self.sql_rows = tables, [], counts or {}, sql_rows or []
        self.db = NS(count=self._count, sql=self._sql)

    def get_all(self, doctype, filters=None, fields=None, pluck=None, limit_page_length=None, **kwargs):
        self.queries.append((doctype, filters, fields))
        rows = [NS_ROW(row) for row in self.tables.get(doctype, [])]
        return [row.get(pluck) for row in rows] if pluck else rows

    def _count(self, doctype, filters=None):
        return self.counts[doctype]

    def _sql(self, query, values=(), as_dict=False):
        self.queries.append(("sql", query, values))
        return self.sql_rows


class NS_ROW(dict):
    def __getattr__(self, name):
        return self.get(name)


def fake(monkeypatch, tables, **kwargs):
    frappe = FakeFrappe(tables, **kwargs)
    monkeypatch.setattr(proc, "frappe", frappe)
    return frappe


def test_load_live_lines_only_asks_for_effective_pos(monkeypatch):
    frappe = fake(monkeypatch, {
        "OA Purchase Order": [{"name": "PO-A", "status": "供应商制作中", "supplier": " 甲 "}],
        "OA Purchase Order Line": [
            {"name": "l1", "parent": "PO-A", "quantity": 2, "received_quantity": 1, "inspection_status": None,
             "contract_delivery_date": "2026-10-01", "project": " P1 ", "item_name": "镜片", "source_request": "R1", "source_line": "x"},
            {"name": "l2", "parent": "PO-OTHER", "quantity": 1, "received_quantity": 0}]})
    rows = proc._load_live_lines()
    assert frappe.queries[0][1] == {"status": ["in", ["已生效", "供应商制作中", "到货验收中", "付款中"]]}
    assert frappe.queries[1][1]["parent"] == ["in", ["PO-A"]]
    assert rows == [{"po": "PO-A", "po_status": "供应商制作中", "supplier": "甲", "line": "l1", "quantity": 2, "received": 1,
                     "inspection": "", "due": "2026-10-01", "project": "P1", "item": "镜片", "source_request": "R1", "source_line": "x"}]
    fake(monkeypatch, {"OA Purchase Order": []})
    assert proc._load_live_lines() == []


def test_load_month_pos_splits_by_creation_month_and_strips_suppliers(monkeypatch):
    frappe = fake(monkeypatch, {"OA Purchase Order": [
        {"name": "N1", "supplier": " 甲 ", "total_amount": 100, "creation": "2026-10-03 09:00:00", "status": "已生效"},
        {"name": "N0", "supplier": None, "total_amount": None, "creation": "2026-09-30 23:59:59", "status": None}]})
    rows = proc._load_month_pos("2026-09-01", "2026-11-01")
    assert frappe.queries[0][1] == [["OA Purchase Order", "status", "!=", "已取消"], ["OA Purchase Order", "creation", ">=", "2026-09-01"],
                                    ["OA Purchase Order", "creation", "<", "2026-11-01"]]
    assert rows == [{"po": "N1", "supplier": "甲", "status": "已生效", "amount": 100.0, "month": "2026-10", "day": "2026-10-03"},
                    {"po": "N0", "supplier": "", "status": "", "amount": 0.0, "month": "2026-09", "day": "2026-09-30"}]


def test_month_bounds_handles_year_ends():
    assert proc._month_bounds("2026-10") == ("2026-09-01", "2026-10-01", "2026-11-01")
    assert proc._month_bounds("2026-01") == ("2025-12-01", "2026-01-01", "2026-02-01")
    assert proc._month_bounds("2026-12") == ("2026-11-01", "2026-12-01", "2027-01-01")


def test_month_pos_asks_for_last_and_this_month_once(world, monkeypatch):
    asked = []
    monkeypatch.setattr(proc, "_load_month_pos", lambda prev, nxt: asked.append((prev, nxt)) or [])
    ctx = full_ctx()
    run("proc.month_amount", ctx)
    run("proc.suppliers_count", ctx)
    run("block.proc_suppliers", ctx)
    assert asked == [("2026-09-01", "2026-11-01")]          # 三个块共用一次读取


def test_load_latest_arrivals_keeps_the_newest_date(monkeypatch):
    frappe = fake(monkeypatch, {"OA PO Fulfillment Record": [
        {"purchase_order": "PO-A", "record_date": "2026-09-01"}, {"purchase_order": "PO-A", "record_date": "2026-09-20"},
        {"purchase_order": "PO-B", "record_date": None}]})
    assert proc._load_latest_arrivals({"PO-A", "PO-B"}) == {"PO-A": "2026-09-20"}
    assert frappe.queries[0][1]["record_type"] == ["in", ["到货", "换货到货"]]
    assert proc._load_latest_arrivals(set()) == {}


def test_load_pr_lines_skips_cancelled_prs(monkeypatch):
    fake(monkeypatch, {
        "OA Procurement Request Line": [{"name": "a", "parent": "PR-1", "remaining_quantity": 2}, {"name": "b", "parent": "PR-X", "remaining_quantity": 1}],
        "OA Procurement Request": [{"name": "PR-1"}]})
    assert proc._load_pr_lines() == [{"pr": "PR-1", "line": "a"}]


def test_load_price_state_counts_lines_without_any_quote(monkeypatch):
    fake(monkeypatch, {
        "OA Price Approval": [{"name": "PA-1", "status": "待审批"}, {"name": "PA-2", "status": "待审批"}, {"name": "PA-3", "status": "草稿"}],
        "OA Price Approval Line": [{"name": "l1", "parent": "PA-1"}, {"name": "l2", "parent": "PA-1"}, {"name": "l3", "parent": "PA-2"}],
        "OA Price Approval Quote": [{"price_approval": "PA-1", "price_line": "l1"}, {"price_approval": "PA-2", "price_line": "l3"}]})
    assert proc._load_price_state() == {"pending": 2, "draft": 1, "unquoted": {"PA-1": 1}, "names": ["PA-1", "PA-2"]}


def test_load_price_state_without_pending_approvals_skips_the_line_queries(monkeypatch):
    frappe = fake(monkeypatch, {"OA Price Approval": [{"name": "PA-3", "status": "草稿"}]})
    assert proc._load_price_state() == {"pending": 0, "draft": 1, "unquoted": {}, "names": []}
    assert [query[0] for query in frappe.queries] == ["OA Price Approval"]


def test_load_await_pr_follows_list_materials_for_pr(monkeypatch):
    fake(monkeypatch, {
        "OA Approval Request": [
            {"name": "R1", "workflow_status": "已完成", "business_status": ""},
            {"name": "R2", "workflow_status": "审批中", "business_status": "需求已批准/待提PR"},
            {"name": "R3", "workflow_status": "审批中", "business_status": ""}],       # 需求还没批准：不算
        "OA Purchase Request Line": [
            {"name": "1", "parent": "R1", "quantity": 10}, {"name": "2", "parent": "R1", "quantity": 5},
            {"name": "3", "parent": "R2", "quantity": 4}, {"name": "4", "parent": "R2", "quantity": 4}],
        "OA Procurement Request": [{"name": "PR-CANCELLED"}],
        "OA Procurement Request Line": [
            {"source_request": "R1", "source_line": "1", "quantity": 10, "parent": "PR-1"},             # 全部提了 PR
            {"source_request": "R1", "source_line": "2", "quantity": 2, "parent": "PR-1"},              # 只提了一部分
            {"source_request": "R2", "source_line": "3", "quantity": 4, "parent": "PR-CANCELLED"}],     # PR 取消了，数量回来
        "OA Material Progress": [{"source_request": "R2", "source_line": "4"}]})                        # 物料已取消
    assert proc._load_await_pr() == [{"request": "R1", "line": "2"}, {"request": "R2", "line": "3"}]
    fake(monkeypatch, {"OA Approval Request": [{"name": "R3", "workflow_status": "审批中", "business_status": ""}]})
    assert proc._load_await_pr() == []


def test_load_uncoded_ignores_blank_spaces_and_dead_requests(monkeypatch):
    # 2026-10-13：条件是物料进度页 ?uncoded=1 用的同一句 SQL（状态正常、编号去空格后为空、源申请没被拒绝 / 撤回）
    from rayher_hr_payroll.material_progress_query import FROM_SQL, UNCODED_SQL

    frappe = fake(monkeypatch, {}, sql_rows=[{"name": "M1", "source_request": "R1"}, {"name": "M2", "source_request": "R1"}])
    assert proc._load_uncoded() == [{"name": "M1", "request": "R1"}, {"name": "M2", "request": "R1"}]
    query = frappe.queries[0][1]
    assert FROM_SQL in query and UNCODED_SQL in query
    for part in ("b.status='正常'", "TRIM(COALESCE(b.material_code,''))=''", "NOT IN ('已拒绝','已撤回')"):
        assert part in UNCODED_SQL


def test_load_stage_counts_reuses_the_material_board_stage_sql(monkeypatch):
    from rayher_hr_payroll.material_progress_query import FROM_SQL, stage_sql

    frappe = fake(monkeypatch, {}, sql_rows=[{"stage": "已关闭", "no_pr": 0, "total": 3}])
    assert proc._load_stage_counts() == [{"stage": "已关闭", "no_pr": 0, "total": 3}]
    query = frappe.queries[0][1]
    assert stage_sql() in query and FROM_SQL in query and "GROUP BY stage, no_pr" in query


def test_load_chain_counts_leaves_out_cancelled_pos(monkeypatch):
    fake(monkeypatch, {"OA Purchase Order": [{"name": "PO-X"}],
                       "OA Procurement Payment Plan Row": [{"parent": "PO-1"}, {"parent": "PO-1"}, {"parent": "PO-X"}]},
         counts={"OA Approval Request": 7, "OA Procurement Request": 5, "OA Purchase Order": 3})
    assert proc._load_chain_counts() == {"request": 7, "pr": 5, "po": 3, "payment": 2}


def test_payment_items_are_trimmed_to_what_the_board_needs(monkeypatch):
    from rayher_hr_payroll.api import procurement_chain as pc

    calls = []
    monkeypatch.setattr(pc, "list_payment_work_items", lambda limit=500: calls.append(limit) or [
        {"po": "PO-A", "work_status": "待验收", "amount": "100", "paid_amount": None, "planned_date": "2026-10-01",
         "payment_stage": "预付款", "supplier": "甲", "lines": ["很大的明细"]}])
    assert proc._load_payment_items() == [{"po": "PO-A", "work_status": "待验收", "amount": 100.0, "paid": 0.0,
                                           "planned": "2026-10-01"}]
    assert calls == [1000]


# ---------------------------------------------------------------- 日程、账龄、趋势（按岗位看板方案补的块）
NEW_BLOCKS = ["block.week_cols", "block.inspect_aging", "block.overdue_aging", "block.proc_month_trend", "block.pay_next30"]


def test_the_new_blocks_are_registered_and_used_by_a_layout():
    for key in NEW_BLOCKS:
        assert core.REGISTRY[key].kind == "block", key
        assert key in layout.all_block_keys(), key


def test_the_week_columns_count_the_weeks_materials_per_day_and_mark_today(world):
    fill(world)
    block = run("block.week_cols", full_ctx())
    assert block["type"] == "cols"
    assert [(r["label"], r["value"], r["last"]) for r in block["rows"]] == [
        ("周一", "0", False), ("周二", "0", False), ("周三", "0", False), ("周四", "0", False),
        ("周五", "1", True), ("周六", "1", False), ("周日", "0", False)]
    world["lines"] = []
    assert run("block.week_cols", full_ctx()) is None


def test_inspect_aging_groups_waiting_pos_by_days_since_the_last_arrival(world):
    fill(world)
    block = run("block.inspect_aging", full_ctx())
    assert [(r["label"], r["value"], r["tone"]) for r in block["rows"]] == [
        ("1 天内", "0", ""), ("2–3 天", "0", ""), ("4–7 天", "1", ""), ("超过 7 天", "1", "bad")]
    world["lines"] = []
    assert run("block.inspect_aging", full_ctx()) is None


def test_overdue_aging_groups_late_materials_and_needs_the_material_board_right(world):
    fill(world)
    block = run("block.overdue_aging", make_ctx(positions=("pmc",), roles=("Employee", "Purchase User")))
    # 物料进度的行：没有来源的 B3 不算（2026-10-13）
    assert [(r["label"], r["value"], r["tone"]) for r in block["rows"]] == [("1–3 天", "0", ""), ("4–7 天", "0", ""), ("超过 7 天", "1", "bad")]
    world["calls"].clear()
    assert run("block.overdue_aging", make_ctx(positions=("production_asset_owner",))) is None
    assert world["calls"] == []


def test_the_monthly_purchase_trend_covers_six_months_and_is_never_shown_to_pmc(world):
    fill(world)
    world["month_lines"].append({"po": "P0", "project": "", "amount": 200000})
    block = run("block.proc_month_trend", full_ctx())
    assert [r["label"] for r in block["rows"]] == ["5月", "6月", "7月", "8月", "9月", "10月"]
    # 物料行金额合计，写法和「本月采购金额」卡片一样（2026-10-13）
    assert [r["value"] for r in block["rows"]] == ["0 元", "0 元", "0 元", "0 元", "20.0 万", "22.0 万"]
    assert block["rows"][-1]["last"] is True and block["rows"][-1]["pct"] == 100.0
    world["calls"].clear()
    assert run("block.proc_month_trend", make_ctx(positions=("pmc",), roles=("Employee", "Purchase User"))) is None
    assert world["calls"] == []


def test_next_thirty_days_groups_unpaid_purchase_payments_by_planned_week(world):
    fill(world)
    block = run("block.pay_next30", full_ctx())
    # 2026-10-13：周 = 周一到周日（今天 10-09 周五，10-20 在第 3 周）；金额写法同卡片
    assert [(r["label"], r["value"]) for r in block["rows"]] == [
        ("已过计划日", "4.5 万"), ("本周", "0 元"), ("下周", "0 元"), ("第 3 周", "5.0 万"), ("第 4 周", "0 元"), ("更晚", "0 元"), ("没排期", "2.0 万")]
    assert block["rows"][0]["last"] is True                      # 已过计划日的标橙
    world["calls"].clear()
    for blocked in (make_ctx(positions=("pmc",), roles=("Employee", "Purchase User")), make_ctx(positions=("production_asset_owner",))):
        assert run("block.pay_next30", blocked) is None
    assert world["calls"] == []                                  # PMC、生产主管不碰付款数据
    world["pay"] = [{"po": "PO-C", "work_status": "已付款", "amount": 10000, "paid": 10000, "planned": "2026-09-01"}]
    assert run("block.pay_next30", full_ctx()) is None
