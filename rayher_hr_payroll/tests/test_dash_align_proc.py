"""看板数字和点进去看到的对齐（采购 / PMC / 生产主管 / 项目负责人，2026-10-13 审查 F1–F17）。

规则（用户 2026-10-13 定的）：看板上每个数 = 点进去看到的（同样的行、同样的条数 / 合计），对不上就点进同一份数据的明细；
采购金额 = PO 物料行金额合计；PMC、生产主管从看板点得到的地方演示员工177出现金额；“超过 3 天” = 严格大于 3 个日历日；
看板给谁看一行，谁就能打开那一行的详情。
今天固定为 2026-10-09（周五），本周 = 10-05 到 10-11。
"""
import json
from datetime import date
from types import SimpleNamespace as NS

import pytest

from rayher_hr_payroll.dashboard import core
from rayher_hr_payroll.dashboard import procurement as proc
from rayher_hr_payroll.dashboard import projects

TODAY = "2026-10-09"


def make_ctx(positions=(), roles=("Employee",), user="u@example.com", period="2026-10", **kw):
    return core.Ctx(user=user, roles=frozenset(roles), positions=frozenset(positions), period=period, today=TODAY, **kw)


def manager():
    return make_ctx(positions=("procurement_manager",), roles=("Employee", "Purchase Manager"))


def pmc():
    return make_ctx(positions=("pmc",), roles=("Employee", "Purchase User"))


def run(key, ctx):
    entry = core.REGISTRY[key]
    return entry.fn(ctx) if entry.visible is None or entry.visible(ctx) else None


def line(po, quantity, got, state="", due="", project="", item="", sr="", sl="", status="供应商制作中", name=None):
    return {"po": po, "po_status": status, "supplier": "甲", "line": name or f"{po}-{item}-{due}", "quantity": quantity, "received": got,
            "inspection": state, "due": due, "project": project, "item": item, "source_request": sr, "source_line": sl}


@pytest.fixture
def world(monkeypatch):
    data = {"calls": [], "lines": [], "arrivals": {}, "records": [], "month_pos": [], "month_lines": [], "pay": [], "pr": [],
            "price": {"pending": 0, "draft": 0, "unquoted": {}, "names": []}, "await": [], "uncoded": [], "stages": [],
            "chain": {"request": 0, "pr": 0, "po": 0, "payment": 0}, "urgent": [], "overdue": [], "heads": {},
            "breakdown": {"request": {}, "pr": {}, "po": {}, "payment": {}}}

    def reader(name, key, fn=None):
        def read(*args):
            data["calls"].append((name, args))
            return fn(*args) if fn else data[key]
        monkeypatch.setattr(proc, name, read)

    monkeypatch.setattr(proc, "_gate_open", lambda ctx, kind: data.get("gate", {}).get(kind, True))
    for name, key in (("_load_live_lines", "lines"), ("_load_month_records", "records"), ("_load_month_pos", "month_pos"),
                      ("_load_po_line_amounts", "month_lines"), ("_load_payment_items", "pay"), ("_load_pr_lines", "pr"),
                      ("_load_price_state", "price"), ("_load_await_pr", "await"), ("_load_uncoded", "uncoded"),
                      ("_load_stage_counts", "stages"), ("_load_chain_counts", "chain"), ("_load_urgent", "urgent"),
                      ("_load_overdue_materials", "overdue"), ("_load_chain_breakdown", "breakdown")):
        reader(name, key)
    reader("_load_latest_arrivals", "arrivals", lambda names: {po: day for po, day in data["arrivals"].items() if po in names})
    reader("_load_request_heads", "heads", lambda names: {key: value for key, value in data["heads"].items() if key in names})
    return data


class FakeFrappe:
    def __init__(self, tables=None, sql_rows=None):
        self.tables, self.sql_rows, self.queries = tables or {}, sql_rows or [], []
        self.db = NS(sql=self._sql)

    def get_all(self, doctype, filters=None, fields=None, pluck=None, **kwargs):
        self.queries.append((doctype, filters))
        rows = self.tables.get(doctype, [])
        rows = rows(filters) if callable(rows) else rows
        return [row.get(pluck) for row in rows] if pluck else [dict(row) for row in rows]

    def _sql(self, query, values=(), as_dict=False):
        self.queries.append(("sql", query, values))
        return self.sql_rows


# ---------------------------------------------------------------- F1 待提 PR：卡片和明细同一份数据
def test_f1_await_pr_card_opens_a_list_built_from_the_same_rows(world):
    world["await"] = [{"request": "R1", "line": "1"}, {"request": "R1", "line": "2"}, {"request": "R2", "line": "1"}]
    world["heads"] = {"R1": {"subject": " 伺服电机 ", "employee_name": "演示员工129", "project": "RD03"}, "R2": {"subject": "", "employee_name": "", "project": ""}}
    ctx = manager()
    card = run("proc.await_pr", ctx)
    assert card["value"] == "2" and card["target"] == {"key": "drill", "params": {"item": "proc.await_pr", "period": "2026-10"}}
    detail = core.get_detail_for(ctx, "proc.await_pr")
    assert len(detail["rows"]) == int(card["value"]) and detail["summary"] == "共 2 张，3 项物料"
    assert detail["rows"][0]["cells"] == ["R1", "伺服电机", "演示员工129", "RD03", "2 项"]
    # 采购经理能看物料进度看板：点一行到看板里这张申请的物料（PMC 在那里提 PR）
    assert detail["rows"][0]["target"] == {"key": "material.progress", "params": {"request": "R1"}}


def test_f1_rows_open_the_request_only_where_the_viewer_can(world):
    world["await"] = [{"request": "R1", "line": "1"}]
    buyer = make_ctx(roles=("Employee", "Purchase User"))            # 采购角色、没有看板岗位：去申请详情（按角色可读）
    assert core.get_detail_for(buyer, "proc.await_pr")["rows"][0]["target"] == {"key": "procurement.detail", "params": {"request": "R1"}}
    assert run("proc.await_pr", make_ctx()) is None and core.get_detail_for(make_ctx(), "proc.await_pr") is None     # 普通员工看不到
    assert proc._await_pr_open(make_ctx(positions=("vice_manager",)), "R1") == {"key": "material.progress", "params": {"request": "R1"}}
    assert proc._await_pr_open(make_ctx(), "R1") is None


def test_f1_no_link_when_nothing_waits(world):
    assert run("proc.await_pr", manager())["target"] is None


# ---------------------------------------------------------------- F2 / F11 物料逾期：和物料进度页同一句 SQL，按物料进度的行
def test_f2_overdue_loader_uses_the_material_board_sql(monkeypatch):
    from rayher_hr_payroll.material_progress_query import FROM_SQL, overdue_due_sql, overdue_sql

    frappe = FakeFrappe(sql_rows=[{"name": "M1", "source_request": "R1", "source_line": "1", "project": " RD03 ", "item_name": "镜片", "due": date(2026, 9, 30)}])
    monkeypatch.setattr(proc, "frappe", frappe)
    assert proc._load_overdue_materials(TODAY) == [{"name": "M1", "request": "R1", "line": "1", "project": "RD03", "item": "镜片", "due": "2026-09-30"}]
    _, query, values = frappe.queries[0]
    assert FROM_SQL in query and overdue_sql() in query and overdue_due_sql() in query and values == {"today": TODAY}


def test_f2_the_page_filter_and_the_card_are_one_sql():
    from rayher_hr_payroll.material_progress_query import overdue_sql, conditions

    where, params = conditions(overdue=True, today=TODAY)
    assert overdue_sql() in where and params["today"] == TODAY
    sql = overdue_sql()
    # 已取消的物料不算；PO 演示员工116已生效；交期早于今天（服务器的今天）；没收齐或退货中
    for part in ("b.status!='已取消'", "po.status IN ('已生效','供应商制作中','到货验收中','付款中')", "pl.contract_delivery_date < %(today)s",
                 "COALESCE(pl.received_quantity,0) < COALESCE(pl.quantity,0)", "COALESCE(pl.inspection_status,'')='退货中'"):
        assert part in sql, part
    project_where, project_params = conditions(project=" RD03 ")
    assert "b.project=%(project)s" in project_where and project_params["project"] == "RD03"


def test_f2_a_line_being_returned_counts_as_not_received_everywhere():
    from rayher_hr_payroll.api.material_progress import contract_line_overdue

    returning = NS(contract_delivery_date="2026-10-01", received_quantity=5, quantity=5, inspection_status="退货中")
    assert contract_line_overdue(returning, "到货验收中", TODAY)
    assert not contract_line_overdue(NS(contract_delivery_date="2026-10-01", received_quantity=5, quantity=5, inspection_status="已通过"), "到货验收中", TODAY)
    assert proc.classify([line("PO-A", 5, 5, state="退货中", due="2026-10-01")], date(2026, 10, 9))["overdue"]      # PO 口径一样


def test_f2_card_count_equals_the_rows_the_page_lists_and_projects_link_with_a_filter(world):
    world["overdue"] = [
        {"name": "M1", "request": "R1", "line": "1", "project": "RD03", "item": "镜片", "due": "2026-09-20"},
        {"name": "M2", "request": "R1", "line": "2", "project": "RD03", "item": "导轨", "due": "2026-10-05"},
        {"name": "M3", "request": "R2", "line": "1", "project": "", "item": "螺丝", "due": "2026-10-08"}]
    ctx = pmc()
    card = run("proc.material_overdue", ctx)
    assert (card["value"], card["sub"], card["target"]) == ("3", "最久逾期 19 天", {"key": "material.overdue", "params": {}})
    assert run("alert.material_overdue", ctx)["title"] == "3 项物料超过演示员工116交期还没到"
    aging = run("block.overdue_aging", ctx)
    assert sum(int(row["value"]) for row in aging["rows"]) == 3
    risk = core.get_detail_for(ctx, "proc.risk_projects")
    assert [row["cells"][:3] for row in risk["rows"]] == [["RD03", "2 项", "19 天"]]
    # F11：一行点进去只看这个项目的逾期物料，条数 = 这一行的“逾期物料”
    assert risk["rows"][0]["target"] == {"key": "material.overdue", "params": {"project": "RD03"}}
    block = run("block.risk_projects", ctx)
    assert block["rows"][0]["target"] == {"key": "material.overdue", "params": {"project": "RD03"}}
    assert run("proc.risk_projects", ctx)["value"] == "1"


def test_f2_the_board_endpoint_accepts_the_dashboard_filters(monkeypatch):
    from rayher_hr_payroll.api import material_progress as board

    asked = []
    monkeypatch.setattr(board, "_board_user", lambda: "pmc@example.com")
    monkeypatch.setattr(board.frappe.utils, "today", lambda: TODAY, raising=False)

    def sql(query, params=None, as_dict=False):
        asked.append((query, dict(params or {})))
        return [[0]] if query.startswith("SELECT COUNT(*)") else []
    monkeypatch.setattr(board.frappe, "db", NS(sql=sql), raising=False)
    raw = getattr(board.list_material_progress, "__wrapped__", board.list_material_progress)
    result = raw(overdue="1", uncoded="1", project="RD03")
    assert result["total"] == 0
    count_query, params = asked[0]
    from rayher_hr_payroll.material_progress_query import UNCODED_SQL, overdue_sql
    assert overdue_sql() in count_query and UNCODED_SQL in count_query and "b.project=%(project)s" in count_query
    assert params["today"] == TODAY and params["project"] == "RD03"


# ---------------------------------------------------------------- F3 采购金额 = 物料行金额合计
def month_world(world):
    world["month_pos"] = [
        {"po": "N1", "supplier": "甲", "amount": 100000, "month": "2026-10", "status": "已生效", "day": "2026-10-01"},
        {"po": "N2", "supplier": "乙", "amount": 5000, "month": "2026-10", "status": "草稿", "day": "2026-10-02"},
        {"po": "P1", "supplier": "甲", "amount": 1, "month": "2026-09", "status": "已关闭", "day": "2026-09-02"}]
    world["month_lines"] = [{"po": "N1", "project": "RD03", "amount": 60000}, {"po": "N1", "project": "", "amount": 40000.5},
                            {"po": "N2", "project": "RD03", "amount": 4000}, {"po": "P1", "project": "", "amount": 52000}]


def test_f3_month_amount_card_drill_suppliers_and_projects_all_add_up_to_line_amounts(world):
    month_world(world)
    ctx = manager()
    card = run("proc.month_amount", ctx)
    assert (card["value"], card["unit"], card["sub"]) == ("10.4", "万", "较上月 +100.0%")     # 104000.5 vs 52000
    detail = core.get_detail_for(ctx, "proc.month_amount")
    assert detail["summary"] == "共 2 个 PO，合计 10.4 万"
    assert [row["cells"][4] for row in detail["rows"]] == ["¥ 100,000.50", "¥ 4,000.00"]
    assert "2 个 PO 的表头总额和行金额合计对不上（N1、N2）" in detail["note"]          # 表头 10 万 / 5000 和行合计演示员工177一样
    suppliers = core.get_detail_for(ctx, "proc.suppliers")
    assert [row["cells"][2] for row in suppliers["rows"]] == ["¥ 100,000.50", "¥ 4,000.00"]
    by_project = core.get_detail_for(ctx, "proc.projects")
    assert sorted(row["cells"] for row in by_project["rows"]) == sorted([["RD03", "¥ 64,000.00"], ["非项目", "¥ 40,000.50"]])
    assert "合计 10.4 万" in by_project["summary"]


def test_f3_trend_uses_line_amounts_and_the_card_format_and_opens_month_by_month(world):
    month_world(world)
    ctx = manager()
    block = run("block.proc_month_trend", ctx)
    assert [row["value"] for row in block["rows"]][-2:] == ["5.2 万", "10.4 万"]
    assert block["rows"][-1]["value"] == "{} {}".format(*core.money_wan(104000.5))            # 和卡片同一个写法
    assert block["target"]["params"]["item"] == "proc.month_trend"
    detail = core.get_detail_for(ctx, "proc.month_trend")
    assert len(detail["rows"]) == 6 and detail["rows"][-1]["cells"] == ["2026 年 10 月", "2 个", "¥ 104,000.50"]
    assert detail["rows"][-1]["target"] == {"key": "drill", "params": {"item": "proc.month_amount", "period": "2026-10"}}
    assert detail["rows"][0]["target"] is None                                                   # 那个月没有 PO


def test_f3_small_amounts_read_the_same_on_card_and_trend(world):
    world["month_pos"] = [{"po": "N1", "supplier": "甲", "amount": 0, "month": "2026-10", "status": "已生效", "day": "2026-10-01"}]
    world["month_lines"] = [{"po": "N1", "project": "", "amount": 5000}]
    ctx = manager()
    card = run("proc.month_amount", ctx)
    assert (card["value"], card["unit"]) == ("5,000", "元")
    assert run("block.proc_month_trend", ctx)["rows"][-1]["value"] == "5,000 元"


# ---------------------------------------------------------------- F4 已过计划付款日：卡片和明细同一份行
def test_f4_a_fully_paid_installment_is_neither_on_the_card_nor_in_the_list(world):
    world["pay"] = [
        {"po": "PO-A", "work_status": "待实际付款", "amount": 10000, "paid": 10000, "planned": "2026-10-01"},   # 付清了，状态还没跟上
        {"po": "PO-B", "work_status": "待验收", "amount": 0, "paid": 0, "planned": "2026-10-02"},              # 没金额
        {"po": "PO-C", "work_status": "付款审批中", "amount": 8000, "paid": 3000, "planned": "2026-10-03"}]
    ctx = manager()
    card = run("proc.pay_planned_passed", ctx)
    detail = core.get_detail_for(ctx, "proc.pay_planned_passed")
    assert card["value"] == "1" and len(detail["rows"]) == 1 and card["sub"].startswith("未付 5,000 元")
    assert run("alert.pay_planned_passed", ctx)["title"] == "1 期采购付款已过计划付款日"


# ---------------------------------------------------------------- F5–F8 项目负责人
def prj_ctx(**kw):
    base = dict(user="owner@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-12",
                employee="E1", owns_projects=True)
    base.update(kw)
    return core.Ctx(**base)


def req(name, workflow, request_type="采购申请", business="", chain=None, project="RD02", **extra):
    row = {"name": name, "request_type": request_type, "workflow_status": workflow, "business_status": business, "subject": name,
           "project": project, "project_owner": "owner@example.com", "employee": "E9", "employee_name": "演示员工147", "current_step_label": "",
           "modified": f"2026-10-{len(name):02d}", "procurement_chain": chain, "can_approve": False}
    row.update(extra)
    return row


@pytest.fixture
def owner(monkeypatch):
    data = {"requests": [], "projects": [{"name": "RD02", "project_name": "ACONCA", "rd_project_code": "RD02", "status": "Open"}]}
    monkeypatch.setattr(projects, "_load_requests", lambda ctx: data["requests"])
    monkeypatch.setattr(projects, "_load_projects", lambda ctx: data["projects"])
    return data


def test_f5_own_requests_are_not_counted_like_the_owned_tab_of_the_list(owner):
    owner["requests"] = [req("A", "待审批"), req("BB", "待审批", employee="E1"), req("CCC", "已完成", chain={"stage": "po"})]
    ctx = prj_ctx()
    assert [row["name"] for row, _stage in projects._mine(ctx)] == ["CCC", "A"]
    assert run("prj.count", ctx)["sub"] == "共 2 张采购 / 购买申请"


def test_f5_a_project_row_opens_the_procurement_list_filtered_to_that_project(owner):
    owner["requests"] = [req("A", "待审批"), req("BB", "已完成", chain={"stage": "closed"}), req("HH", "已完成", request_type="购买申请", business="待付款")]
    detail = core.get_detail_for(prj_ctx(), "prj.projects")
    row = detail["rows"][0]
    assert row["cells"] == ["RD02 · ACONCA", "Open", "1", "0", "1", "1"]
    assert row["target"] == {"key": "procurement.list", "params": {"scope": "owned", "project": "RD02", "stage": "live"}}


def test_f6_recent_requests_open_the_page_of_their_own_type(owner):
    owner["requests"] = [req("A", "待审批"), req("HH", "已完成", request_type="购买申请", business="待付款")]
    block = run("block.prj_requests", prj_ctx())
    targets = {row["label"]: row["target"]["key"] for row in block["rows"]}
    assert targets == {"A": "procurement.detail", "HH": "directpurchase.detail"}


@pytest.mark.parametrize("row, stage", [
    (req("a", "待审批"), "demand"), (req("a", "待办理"), "demand"),
    (req("a", "草稿"), None), (req("a", "已拒绝"), None), (req("a", "已撤回"), None), (req("a", "已取消"), None),
    (req("a", "已完成", business="已撤回"), None), (req("a", "已完成", business="已取消"), None),
    (req("a", "已完成", chain={"stage": "demand"}), "exec"),                      # 列表：需求已批准、链路没开始 = 等待提 PR
    (req("a", "已完成", chain={"stage": "await_pr"}), "exec"), (req("a", "已完成", chain={"stage": "po"}), "exec"),
    (req("a", "已完成", chain={"stage": "closed"}), "done"), (req("a", "已完成", business="已关闭", chain={"stage": "po"}), "done"),
    (req("a", "审批中", business="需求已批准/待提PR", chain={"stage": "await_pr"}), "exec"),
    (req("a", "已通过"), "demand"),                                               # 列表：没完成也没批准需求 = 需求审批
    (req("a", "已完成", request_type="购买申请", business="待付款"), "exec"), (req("a", "已完成", request_type="购买申请", business="部分付款"), "exec"),
    (req("a", "已完成", request_type="购买申请", business="已付款"), "done"), (req("a", "已完成", request_type="购买申请", business="已关闭"), "done"),
])
def test_f7_one_stage_rule_for_the_project_page_the_list_and_urgent(row, stage):
    assert projects.stage_of(row) == stage


def test_f7_the_live_group_of_the_list_is_exactly_the_stages_the_dashboard_counts():
    import pathlib
    import re

    view = (pathlib.Path(projects.__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "procurementView.js").read_text(encoding="utf-8")
    live = re.search(r"live: Object\.freeze\(\[([^\]]*)\]\)", view).group(1)
    assert [item.strip().strip("'") for item in live.split(",")] == ["demand", "await_pr", "quote", "price", "po", "closed"]


def test_f7_exec_hint_says_what_the_code_counts(owner):
    card = run("prj.exec", prj_ctx())
    assert card["hint"].startswith(projects.EXEC_RULE) and "没关闭" in projects.EXEC_RULE and "采购链路还没关闭" in projects.EXEC_RULE
    assert core.get_detail_for(prj_ctx(), "prj.exec")["note"].startswith(projects.EXEC_RULE)


def test_f8_requests_are_queried_by_project_owner_without_a_200_cap(monkeypatch):
    from rayher_hr_payroll import oa_feature_gate, procurement_summary_cache
    from rayher_hr_payroll.api import oa_entry

    frappe = FakeFrappe({"OA Approval Request": [{"name": f"OA-{i}"} for i in range(250)]})
    import frappe as real_frappe
    monkeypatch.setattr(real_frappe, "get_all", frappe.get_all, raising=False)
    monkeypatch.setattr(oa_feature_gate, "visible_request_types", lambda types, user=None: list(types))
    monkeypatch.setattr(oa_entry, "_load_request", lambda name: NS(name=name))
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda doc: {"name": doc.name})

    class Prepared:
        def __init__(self, docs, fn):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False
    monkeypatch.setattr(procurement_summary_cache, "prepare_summaries", Prepared)
    rows = projects._load_requests(prj_ctx())
    assert len(rows) == 250
    doctype, filters = frappe.queries[0]
    assert doctype == "OA Approval Request" and filters["project_owner"] == "owner@example.com"
    assert filters["workflow_status"] == ["!=", "草稿"] and filters["request_type"] == ["in", ["采购申请", "购买申请"]]


# ---------------------------------------------------------------- F9 价格审批
def test_f9_price_cards_keep_the_filter(world):
    world["price"] = {"pending": 2, "draft": 0, "unquoted": {"PA-1": 2, "PA-2": 1}, "names": ["PA-1", "PA-2"]}
    ctx = manager()
    assert run("proc.price_pending", ctx)["target"] == {"key": "price.approvals", "params": {"view": "approvals", "status": "pending"}}
    alert = run("alert.price_missing_quote", ctx)
    assert alert["target"] == {"key": "drill", "params": {"item": "proc.price_missing_quote", "period": "2026-10"}}
    detail = core.get_detail_for(ctx, "proc.price_missing_quote")
    assert [row["cells"] for row in detail["rows"]] == [["PA-1", "2 项"], ["PA-2", "1 项"]] and detail["summary"] == "共 2 张，3 项物料"
    assert detail["rows"][0]["target"] == {"key": "price.approvals", "params": {"view": "approvals", "approval": "PA-1"}}


def test_f9_exactly_one_opens_it_directly(world):
    world["price"] = {"pending": 1, "draft": 0, "unquoted": {"PA-7": 1}, "names": ["PA-7"]}
    ctx = manager()
    assert run("proc.price_pending", ctx)["target"]["params"] == {"view": "approvals", "status": "pending", "approval": "PA-7"}
    assert run("alert.price_missing_quote", ctx)["target"] == {"key": "price.approvals", "params": {"view": "approvals", "approval": "PA-7"}}


# ---------------------------------------------------------------- F10 未编码、阶段名
def test_f10_uncoded_links_keep_the_filter_and_use_the_page_sql(world):
    world["uncoded"] = [{"name": "M1", "request": "R1"}]
    ctx = pmc()
    assert run("proc.uncoded", ctx)["target"] == {"key": "material.progress", "params": {"uncoded": "1"}}
    assert run("alert.uncoded", ctx)["target"] == {"key": "material.progress", "params": {"uncoded": "1"}}
    from rayher_hr_payroll.material_progress_query import UNCODED_SQL, conditions

    assert UNCODED_SQL in conditions(uncoded=True)[0]


def test_f10_material_stage_rows_are_the_page_stage_names(world):
    import pathlib
    import re

    page = (pathlib.Path(proc.__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "MaterialProgress.vue").read_text(encoding="utf-8")
    page_stages = re.findall(r"'([^']+)'", re.search(r"const stageStatuses = \[([^\]]*)\]", page).group(1))
    assert [label for label, _tone in proc.MATERIAL_STAGE_ROWS] == page_stages
    world["stages"] = [{"stage": "采购确认中", "no_pr": 1, "total": 2}, {"stage": "已取消", "no_pr": 1, "total": 5}]
    block = run("block.material_stage", pmc())
    assert dict((row["label"], row["value"]) for row in block["rows"])["采购确认中"] == "2"
    assert block["target"] == {"key": "material.progress", "params": {}}


# ---------------------------------------------------------------- F12 PMC / 生产主管看不到金额（服务端）
def chain_env(monkeypatch, positions, roles=("Employee",)):
    from rayher_hr_payroll.api import procurement_chain as pc

    holders = {key: ({"u@example.com"} if key in positions else set()) for key in
               ("pmc", "production_asset_owner", *pc.MONEY_POSITIONS, "vice_manager")}
    monkeypatch.setattr(pc, "_user", lambda: "u@example.com")
    monkeypatch.setattr(pc, "_roles", lambda: set(roles))
    monkeypatch.setattr(pc, "position_users", lambda *keys: {user for key in keys for user in holders.get(key, set())})
    monkeypatch.setattr(pc, "_request_memo", lambda key, fn: fn())
    return pc


@pytest.mark.parametrize("positions, roles, hidden", [
    (("pmc",), ("Employee", "Purchase User"), True),
    (("production_asset_owner",), ("Employee",), True),
    (("pmc", "procurement_manager"), ("Employee", "Purchase User"), False),
    (("pmc",), ("Employee", "System Manager"), False),
    (("finance_accountant",), ("Employee", "Accounts User"), False),
    ((), ("Employee", "Purchase User"), False),
])
def test_f12_who_gets_amounts_matches_the_dashboard(monkeypatch, positions, roles, hidden):
    pc = chain_env(monkeypatch, positions, roles)
    assert pc._amounts_hidden() is hidden
    assert proc._money_blocked(make_ctx(positions=positions, roles=roles)) is hidden


def test_f12_summaries_lose_every_amount_for_pmc(monkeypatch):
    pc = chain_env(monkeypatch, ("pmc",), ("Employee", "Purchase User"))
    raw = {"name": "PO-1", "total_amount": 100.0, "paid_amount": 10.0, "outstanding_amount": 90.0, "status": "付款中",
           "lines": [{"item_name": "镜片", "quantity": 2, "unit_price": 50.0, "amount": 100.0}],
           "payment_plan": [{"installment_no": 1, "percentage": 30, "amount": 30.0, "paid_amount": 0}],
           "quotes": [{"supplier": "甲", "unit_price": 1, "total_price": 2, "payment_plan_json": "[{\"amount\": 2}]"}],
           "supplier_comparisons": [{"supplier": "甲", "package_total": 2.0, "prices": [{"unit_price": 1, "total_price": 2}]}]}
    cleaned = pc._for_viewer(raw)
    text = json.dumps(cleaned)
    assert cleaned["amounts_hidden"] == 1 and cleaned["lines"][0]["quantity"] == 2 and cleaned["payment_plan"][0]["percentage"] == 30
    for key in pc.MONEY_KEYS:
        assert f'"{key}": null' in text or f'"{key}"' not in text, key
    assert raw["total_amount"] == 100.0 and raw["lines"][0]["amount"] == 100.0          # 原对象不动
    pc_open = chain_env(monkeypatch, ("procurement_manager",), ("Employee", "Purchase Manager"))
    assert pc_open._for_viewer(raw) is raw


def test_f12_payment_work_items_are_cleaned_for_production(monkeypatch):
    pc = chain_env(monkeypatch, ("production_asset_owner",))
    monkeypatch.setattr(pc, "_require_gate", lambda *a: None)
    monkeypatch.setattr(pc, "_require_po_view", lambda: None)
    po = NS(name="PO-1", payment_plan=[NS(name="r1")])
    monkeypatch.setattr(pc, "_load_pos", lambda limit: [po])
    monkeypatch.setattr(pc, "_work_context", lambda pos: {})
    monkeypatch.setattr(pc, "_payment_work_item", lambda po, row, ctx: {"po": po.name, "installment_no": 1, "work_status": "待验收",
                                                                          "amount": 500.0, "paid_amount": 0.0, "lines": [{"amount": 500.0, "quantity": 1}]})
    items = getattr(pc.list_payment_work_items, "__wrapped__", pc.list_payment_work_items)()
    assert items[0]["amount"] is None and items[0]["lines"][0]["amount"] is None and items[0]["amounts_hidden"] == 1
    assert items[0]["work_status"] == "待验收" and items[0]["lines"][0]["quantity"] == 1


# ---------------------------------------------------------------- F13 加急采购：给谁看就得能打开
def test_f13_urgent_list_only_for_people_who_can_open_the_requests(world):
    seen = lambda ctx: core.REGISTRY["proc.urgent"].visible(ctx)
    for positions in (("general_manager",), ("vice_manager",), ("procurement_manager",), ("pmc",)):
        assert not seen(make_ctx(positions=positions)), positions                       # 只有岗位、没有读权限的角色：详情打不开
    assert seen(make_ctx(positions=("pmc",), roles=("Employee", "Purchase User")))
    assert seen(make_ctx(positions=("general_manager",), roles=("Employee", "QIHENG Demo Business Executive")))
    assert seen(make_ctx(user="Administrator", roles=("Administrator", "System Manager")))
    from rayher_hr_payroll.oa_access import PROCUREMENT_GLOBAL_ROLES

    assert {"Purchase User", "Purchase Manager", "QIHENG Demo Business Executive", "System Manager"} <= set(PROCUREMENT_GLOBAL_ROLES)


def test_f13_direct_purchases_are_left_out_when_their_page_is_switched_off(world):
    world["urgent"] = [{"name": "U1", "type": "购买申请", "subject": "", "applicant": "", "project": "", "expected": "", "approving": True, "label": "", "since": TODAY},
                       {"name": "U2", "type": "采购申请", "subject": "", "applicant": "", "project": "", "expected": "", "approving": True, "label": "", "since": TODAY}]
    world["gate"] = {"direct": False}
    assert run("proc.urgent", manager())["value"] == "1"


# ---------------------------------------------------------------- F14 “没动静”算上采购链路的变动
def test_f14_chain_activity_moves_the_since_date(monkeypatch):
    from rayher_hr_payroll.api import oa_entry

    rows = [{"name": "U1", "request_type": "采购申请", "subject": "电机", "employee_name": "演示员工129", "project": "", "workflow_status": "已完成",
             "business_status": "需求已批准/待询价", "current_step_label": "", "expected_delivery_date": None, "creation": "2026-09-01 09:00:00"},
            {"name": "U2", "request_type": "采购申请", "subject": "导轨", "employee_name": "演示员工146", "project": "", "workflow_status": "已完成",
             "business_status": "需求已批准/待询价", "current_step_label": "", "expected_delivery_date": None, "creation": "2026-09-01 09:00:00"}]
    tables = {
        "OA Approval Request": rows,
        "OA Approval Step": [{"parent": "U1", "acted_on": "2026-09-20 10:00:00"}, {"parent": "U2", "acted_on": "2026-09-20 10:00:00"}],
        "OA Procurement Request Line": [{"parent": "PR-1", "source_request": "U1"}],
        "OA Procurement Request": [{"name": "PR-1", "modified": "2026-09-25 08:00:00"}],
        "OA Price Approval Line": [],
        "OA Purchase Order Line": [{"parent": "PO-1", "source_request": "U1"}],
        "OA Purchase Order": [{"name": "PO-1", "modified": "2026-10-07 15:00:00"}],
    }
    monkeypatch.setattr(proc, "frappe", NS(get_all=FakeFrappe(tables).get_all, get_doc=lambda doctype, name: NS(name=name)))
    monkeypatch.setattr(oa_entry, "_calculate_procurement_chain", lambda doc: {"stage": "po", "label": "PO 执行中"})
    got = {item["name"]: item["since"] for item in proc._load_urgent()}
    assert got == {"U1": "2026-10-07", "U2": "2026-09-20"}


def test_f14_more_than_three_calendar_days_is_strict(world):
    world["urgent"] = [
        {"name": f"U{days}", "type": "采购申请", "subject": "", "applicant": "", "project": "", "expected": "", "approving": True, "label": "",
         "since": f"2026-10-{9 - days:02d}"} for days in (3, 4)]
    card = run("proc.urgent", manager())
    assert card["sub"] == "1 张超过 3 天没动静"


# ---------------------------------------------------------------- F15 图表块都能点进去，点进去的数和图一样
def test_f15_arrival_and_inspection_block_opens_the_same_four_numbers(world, monkeypatch):
    monkeypatch.setattr(proc, "frappe", FakeFrappe({"OA Purchase Order Line": [{"name": "A2", "item_name": "导轨"}]}))
    world["lines"] = [line("PO-A", 10, 0, due="2026-10-01", name="A1"), line("PO-B", 4, 2, state="待验收", due="2026-10-10", name="B1")]
    world["records"] = [{"purchase_order": "PO-A", "record_type": "到货", "details_json": json.dumps([{"line": "A2"}]), "record_date": "2026-10-02"},
                        {"purchase_order": "PO-A", "record_type": "验收", "details_json": json.dumps([{"line": "A2", "status": "已通过"}]), "record_date": "2026-10-03"}]
    ctx = manager()
    block = run("block.arrival_inspect", ctx)
    values = {row["label"]: int(row["value"]) for row in block["rows"]}
    detail = core.get_detail_for(ctx, block["target"]["params"]["item"])
    counted = {}
    for row in detail["rows"]:
        counted[row["cells"][0]] = counted.get(row["cells"][0], 0) + 1
    assert counted == {label: value for label, value in values.items() if value}
    assert all(row["target"] for row in detail["rows"])


def test_f15_chain_block_opens_a_breakdown_that_adds_up(world):
    world["chain"] = {"request": 3, "pr": 2, "po": 1, "payment": 2}
    world["breakdown"] = {"request": {"已完成": 2, "待审批": 1}, "pr": {"待采购": 2}, "po": {"付款中": 1}, "payment": {"待审批": 1, "已付款": 1}}
    ctx = manager()
    block = run("block.proc_chain", ctx)
    detail = core.get_detail_for(ctx, block["target"]["params"]["item"])
    sums = {}
    for row in detail["rows"]:
        sums[row["cells"][0]] = sums.get(row["cells"][0], 0) + int(row["cells"][2])
    assert sums == {row["label"]: int(row["value"]) for row in block["rows"]}
    assert detail["summary"] == "OA 申请 3 · PR 2 · PO 1 · 付款期次 2"


def test_f15_chain_breakdown_uses_the_same_filters_as_the_counts(monkeypatch):
    frappe = FakeFrappe({
        "OA Purchase Order": lambda filters: [{"name": "PO-X"}] if filters == {"status": "已取消"} else [{"status": "付款中"}, {"status": "已生效"}],
        "OA Procurement Payment Plan Row": [{"parent": "PO-1", "status": "待审批"}, {"parent": "PO-X", "status": "待审批"}],
        "OA Approval Request": [{"workflow_status": "已完成"}], "OA Procurement Request": [{"status": "待采购"}]})
    monkeypatch.setattr(proc, "frappe", frappe)
    got = proc._load_chain_breakdown()
    assert got == {"request": {"已完成": 1}, "pr": {"待采购": 1}, "po": {"付款中": 1, "已生效": 1}, "payment": {"待审批": 1}}
    filters = {doctype: f for doctype, f in frappe.queries}
    assert filters["OA Approval Request"] == {"request_type": "采购申请", "workflow_status": ["not in", ["草稿", "已拒绝", "已撤回"]]}
    assert filters["OA Procurement Request"] == {"status": ["!=", "已取消"]}


# ---------------------------------------------------------------- F16 周、单位、过去的月份
def test_f16_pay_weeks_are_monday_to_sunday_like_the_arrival_week():
    friday = date(2026, 10, 9)
    assert proc._pay_week(friday, "2026-10-08") == "已过计划日"
    assert proc._pay_week(friday, "2026-10-11") == "本周"              # 周日
    assert proc._pay_week(friday, "2026-10-12") == "下周"              # 下周一（原来按滚动 7 天算成“本周”）
    assert proc._pay_week(friday, "2026-10-19") == "第 3 周"
    assert proc._pay_week(friday, "2026-11-01") == "第 4 周"
    assert proc._pay_week(friday, "2026-11-02") == "更晚"


def test_f16_pay_columns_add_up_to_the_list(world):
    world["pay"] = [{"po": "PO-A", "work_status": "待验收", "amount": 30000, "paid": 0, "planned": "2026-10-12"},
                    {"po": "PO-B", "work_status": "待实际付款", "amount": 10000, "paid": 10000, "planned": "2026-10-10"}]
    ctx = manager()
    block = run("block.pay_next30", ctx)
    assert {row["label"]: row["value"] for row in block["rows"]}["下周"] == "3.0 万"
    assert core.get_detail_for(ctx, "proc.pay_plan")["summary"] == "共 1 期，未付 3.0 万"


def test_f16_current_state_cards_say_so_when_a_past_month_is_picked(world):
    world["lines"] = [line("PO-A", 10, 0, due="2026-10-01", name="A1")]
    past = make_ctx(positions=("procurement_manager",), roles=("Employee", "Purchase Manager"), period="2026-08")
    assert run("proc.po_transit", past)["sub"].endswith("当前状态，不随月份")
    assert run("proc.to_compare", past)["sub"] == "当前状态，不随所选月份"
    assert "当前状态" not in run("proc.month_amount", past)["sub"]          # 按月份的卡片不加
    assert "当前状态" not in run("proc.po_transit", manager())["sub"]


# ---------------------------------------------------------------- F17 待比价：不能再生成价格审批单的 PR 不算
def test_f17_closed_draft_and_cancelled_prs_are_left_out(monkeypatch):
    from rayher_hr_payroll.api import procurement_chain as pc

    frappe = FakeFrappe({"OA Procurement Request Line": [{"name": "a", "parent": "PR-1", "remaining_quantity": 2}],
                         "OA Procurement Request": [{"name": "PR-1"}]})
    monkeypatch.setattr(proc, "frappe", frappe)
    assert proc._load_pr_lines() == [{"pr": "PR-1", "line": "a"}]
    assert frappe.queries[1][1]["status"] == ["not in", ["草稿", "Draft", "已取消", "已关闭"]]
    assert tuple(pc.PR_CLOSED_STATUSES) == ("草稿", "Draft", "已取消", "已关闭")
    line_row = NS(remaining_quantity=3, as_dict=lambda: {"remaining_quantity": 3})
    closed = NS(name="PR-2", status="已关闭", requested_by="", source_projects="", source_count=1, total_quantity=3, lines=[line_row], modified="")
    assert pc._pr_summary(closed)["available_line_count"] == 0 and pc._pr_summary(closed)["can_create_price_approval"] == 0
    open_pr = NS(name="PR-3", status="待采购", requested_by="", source_projects="", source_count=1, total_quantity=3, lines=[line_row], modified="")
    assert pc._pr_summary(open_pr)["available_line_count"] == 1
