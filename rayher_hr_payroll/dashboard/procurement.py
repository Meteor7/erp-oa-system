"""看板块：采购、PMC、生产主管。

数据来源和口径（每个块的 hint 里也写了）：
- PO 物料行（OA Purchase Order Line）：待到货 / 待验收 / 换货 / 退货 / 演示员工116交期逾期 / 本周预计到货。只看演示员工116已生效的 PO
  （已生效、供应商制作中、到货验收中、付款中）——草稿 PO 的"交期"还是报价上的，不算演示员工116交期。
- 到货 / 验收登记（OA PO Fulfillment Record）：本月已到货、本月已验收、到货后多久没验收。
- 付款期次：直接调 `procurement_chain.list_payment_work_items`（可提交付款审批、已过计划付款日）。
- 物料进度（OA Material Progress）：阶段分布、未编码、逾期未到、缺料影响的项目；阶段 / 逾期 / 未编码的 SQL 复用
  `material_progress_query`（物料进度页筛选用的同一句），点进去条数一致。
- 价格审批 / PR / 采购申请：待比价、价格审批中、待提 PR。
- 采购金额 = PO 物料行金额合计（和「费用」页的采购同一口径，2026-10-13 决定），不用 PO 表头总额。

权限：每个块的 `visible` 对应它背后现有接口的真实权限，规则抄自 `procurement_chain._require_view / _require_po_view`、
`material_progress.can_access_board`（测试里有一条对照测试，规则变了会提醒），再加功能开关。
PMC 因为有 Purchase User 角色，会被现有判断当成"能看采购金额"——这里明确挡掉：看板上 PMC 不出现任何金额
（点进去的 PO / 价格审批 / 付款期次页面也由 procurement_chain._amounts_hidden 在服务端去掉金额）。
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import frappe

from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, col_row, cols, drill, drill_row, drill_to, kpi, list_row, listing, money_wan, provider, target,
)

# 演示员工116已生效、货还在路上或还没结清的 PO 状态（草稿 / 待确认 / 待演示员工116复核 / 待电子用印的演示员工116还没生效；已关闭 / 已取消不看）
EFFECTIVE_PO = ("已生效", "供应商制作中", "到货验收中", "付款中")
STALE_INSPECT_DAYS = 7          # 到货后超过 7 天（不含）还没验收
PRICE_VIEW_ROLES = {"Purchase User", "Purchase Manager", "QIHENG Demo Business Executive"}
PO_VIEW_ROLES = {"Accounts User", "Finance User"} | PRICE_VIEW_ROLES
# 持有这些岗位的人本来就合法看采购 / 付款金额；只持有 pmc / 生产主管岗位的人不给金额
MONEY_POSITIONS = ("procurement_manager", "vice_manager", "general_manager",
                   "finance_manager", "finance_accountant", "finance_auditor")
WEEKDAYS = "一二三四五六日"


# ---------------------------------------------------------------- 权限
def _gate_open(ctx, kind):
    """功能开关：采购链路接口跟随"采购申请"开关，付款接口跟随"采购付款"开关（procurement_chain._require_gate）；
    direct = 购买申请（加急清单里的购买申请详情页）。"""
    from rayher_hr_payroll.oa_document_types import REQUEST_DIRECT_PURCHASE, REQUEST_PROCUREMENT, REQUEST_PROCUREMENT_PAYMENT
    from rayher_hr_payroll.oa_feature_gate import can_access_request_type

    request_type = {"payment": REQUEST_PROCUREMENT_PAYMENT, "direct": REQUEST_DIRECT_PURCHASE}.get(kind, REQUEST_PROCUREMENT)
    return bool(can_access_request_type(request_type, ctx.user))


def _can_open_requests(ctx):
    """能打开别人的采购申请 / 购买申请详情（= oa_access._can_read 里按角色全局可读的那一条：
    PROCUREMENT_GLOBAL_ROLES）。岗位本身不给读权限，所以只持有岗位、没有这些角色的人点进去会“找不到单据”。"""
    from rayher_hr_payroll.oa_access import PROCUREMENT_GLOBAL_ROLES

    return ctx.user.strip().lower() == "administrator" or ctx.can(*PROCUREMENT_GLOBAL_ROLES)


def _has_chain_view(ctx):
    """= procurement_chain._require_view：PMC、采购经理、演示员工113、采购角色、系统演示员工170（价格审批 / PR 的查看权）。"""
    return ctx.holds("pmc", "procurement_manager", "vice_manager") or ctx.can("System Manager", *PRICE_VIEW_ROLES)


def _has_po_view(ctx):
    """= procurement_chain._require_po_view：在 _require_view 的基础上加生产主管和财务（PO / 付款期次的查看权）。"""
    return (ctx.holds("pmc", "procurement_manager", "vice_manager", "production_asset_owner")
            or ctx.can("System Manager", *PO_VIEW_ROLES))


def _has_board(ctx):
    """= material_progress.can_access_board：PMC、采购经理、演示员工113、总经理、系统演示员工170。"""
    return (ctx.user.strip().lower() == "administrator" or ctx.can("System Manager")
            or ctx.holds("pmc", "procurement_manager", "vice_manager", "general_manager"))


def _money_blocked(ctx):
    """PMC / 生产主管不给金额：持有 pmc 或生产主管岗位、又没有任何一个本来就看金额的岗位（采购经理、演示员工113、总经理、财务）。
    不能只看角色——PMC 带着 Purchase User 角色，现有的 `_can_view_procurement_financial` 之类会把他当财务。"""
    if ctx.can("System Manager") or ctx.holds(*MONEY_POSITIONS):
        return False
    return ctx.holds("pmc", "production_asset_owner")


def _chain_ok(ctx):
    """价格审批、PR、待提 PR（list_prs / list_materials_for_pr）。"""
    return _has_chain_view(ctx) and _gate_open(ctx, "chain")


def _po_ok(ctx):
    """PO 物料行、到货验收（list_purchase_orders）。不含金额的块用这个，PMC 也能看。"""
    return _has_po_view(ctx) and _gate_open(ctx, "chain")


def _money_ok(ctx):
    """PO 金额（本月采购金额、供应商 / 项目排行）。"""
    return _po_ok(ctx) and not _money_blocked(ctx)


def _pay_ok(ctx):
    """采购付款期次（list_payment_work_items）。PMC / 生产主管一律不给。"""
    return _has_po_view(ctx) and not _money_blocked(ctx) and _gate_open(ctx, "payment")


def _board_ok(ctx):
    """物料进度看板（list_material_progress）。"""
    return _has_board(ctx)


# ---------------------------------------------------------------- 小工具
def _n(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso(value):
    return str(value)[:10] if value else ""


def _today(ctx):
    return date.fromisoformat(ctx.today)


def _days_since(ctx, iso):
    return (_today(ctx) - date.fromisoformat(iso)).days


def _wan(amount):
    number, unit = money_wan(amount)
    return f"{number} {unit}"


def _now_sub(ctx, sub=""):
    """“当前状态”类的卡片不随所选月份变：选的不是本月时在副标题里说一声。"""
    if ctx.period == ctx.today[:7]:
        return sub
    return f"{sub} · 当前状态，不随月份" if sub else "当前状态，不随所选月份"


def _month_bounds(period):
    """(上月 1 号, 本月 1 号, 下月 1 号)，ISO 字符串。"""
    year, month = int(period[:4]), int(period[5:7])
    this = date(year, month, 1)
    prev = date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return prev.isoformat(), this.isoformat(), nxt.isoformat()


def _po_open(ctx, po):
    """一个 PO 的页面：有价格审批权的去价格审批页的 PO 页签；生产主管看不了价格审批，去采购付款页（到货验收在那里登记）。"""
    if _has_chain_view(ctx):
        return target("price.po", po=po)
    return target("procpay.work", po=po)


# ---------------------------------------------------------------- 数据读取（测试里整体替换；每个函数同一请求只跑一次）
def _load_live_lines():
    """演示员工116已生效的 PO 的物料行。"""
    pos = frappe.get_all("OA Purchase Order", filters={"status": ["in", list(EFFECTIVE_PO)]},
                         fields=["name", "status", "supplier"], limit_page_length=0)
    if not pos:
        return []
    by_name = {row.get("name"): row for row in pos}
    lines = frappe.get_all(
        "OA Purchase Order Line", filters={"parent": ["in", sorted(by_name)], "parenttype": "OA Purchase Order"},
        fields=["name", "parent", "quantity", "received_quantity", "inspection_status", "contract_delivery_date",
                "project", "item_name", "source_request", "source_line"],
        limit_page_length=0)
    return [{
        "po": line.get("parent"), "po_status": by_name[line.get("parent")].get("status"),
        "supplier": (by_name[line.get("parent")].get("supplier") or "").strip(), "line": line.get("name"),
        "quantity": line.get("quantity"), "received": line.get("received_quantity"),
        "inspection": (line.get("inspection_status") or "").strip(), "due": line.get("contract_delivery_date"),
        "project": (line.get("project") or "").strip(), "item": (line.get("item_name") or "").strip(),
        "source_request": line.get("source_request") or "", "source_line": line.get("source_line") or "",
    } for line in lines if line.get("parent") in by_name]


def _load_latest_arrivals(po_names):
    """{PO: 最近一条到货（含换货到货）登记的日期}。"""
    if not po_names:
        return {}
    rows = frappe.get_all(
        "OA PO Fulfillment Record",
        filters={"purchase_order": ["in", sorted(po_names)], "record_type": ["in", ["到货", "换货到货"]]},
        fields=["purchase_order", "record_date"], limit_page_length=0)
    latest = {}
    for row in rows:
        day = _iso(row.get("record_date"))
        if day and day > latest.get(row.get("purchase_order"), ""):
            latest[row.get("purchase_order")] = day
    return latest


def _load_month_records(start, nxt):
    return [dict(row) for row in frappe.get_all(
        "OA PO Fulfillment Record",
        filters=[["OA PO Fulfillment Record", "record_date", ">=", start], ["OA PO Fulfillment Record", "record_date", "<", nxt],
                 ["OA PO Fulfillment Record", "record_type", "in", ["到货", "验收"]]],
        fields=["name", "purchase_order", "record_type", "details_json", "record_date"], limit_page_length=0)]


def _load_month_pos(prev_start, nxt):
    """上月和本月创建的、没取消的 PO（表头）：名称、供应商、金额、创建月份。"""
    rows = frappe.get_all(
        "OA Purchase Order",
        filters=[["OA Purchase Order", "status", "!=", "已取消"], ["OA Purchase Order", "creation", ">=", prev_start],
                 ["OA Purchase Order", "creation", "<", nxt]],
        fields=["name", "supplier", "total_amount", "creation", "status"], limit_page_length=0)
    return [{"po": row.get("name"), "supplier": (row.get("supplier") or "").strip(), "status": row.get("status") or "",
             "amount": _n(row.get("total_amount")), "month": str(row.get("creation"))[:7], "day": str(row.get("creation"))[:10]} for row in rows]


def _load_po_line_amounts(po_names):
    if not po_names:
        return []
    return [{"po": row.get("parent"), "project": (row.get("project") or "").strip(), "amount": _n(row.get("amount"))}
            for row in frappe.get_all("OA Purchase Order Line",
                                      filters={"parent": ["in", sorted(po_names)], "parenttype": "OA Purchase Order"},
                                      fields=["parent", "project", "amount"], limit_page_length=0)]


def _load_payment_items():
    """付款期次工作项（权限由 list_payment_work_items 自己再查一遍；visible 已先判断过）。只留看板要用的字段。"""
    from rayher_hr_payroll.api.procurement_chain import list_payment_work_items

    return [{"po": item.get("po"), "work_status": item.get("work_status") or "", "amount": _n(item.get("amount")),
             "paid": _n(item.get("paid_amount")), "planned": _iso(item.get("planned_date"))}
            for item in (list_payment_work_items(limit=1000) or [])]


def _load_pr_lines():
    """PR 里还没进价格审批的物料行（剩余可选数量 > 0，PR 还能生成价格审批单：不是草稿 / 已取消 / 已关闭）
    ——价格审批页"PR 待比价物料"就是这些（procurement_chain.PR_CLOSED_STATUSES，页面同一口径）。"""
    from rayher_hr_payroll.api.procurement_chain import PR_CLOSED_STATUSES

    lines = frappe.get_all("OA Procurement Request Line", filters={"remaining_quantity": [">", 0]},
                           fields=["name", "parent", "remaining_quantity"], limit_page_length=0)
    if not lines:
        return []
    live = set(frappe.get_all("OA Procurement Request",
                              filters={"name": ["in", sorted({row.get("parent") for row in lines})], "status": ["not in", list(PR_CLOSED_STATUSES)]},
                              pluck="name", limit_page_length=0))
    return [{"pr": row.get("parent"), "line": row.get("name")} for row in lines if row.get("parent") in live]


def _load_price_state():
    """{"pending": 待审批张数, "draft": 草稿张数, "unquoted": {待审批单号: 一个报价都没有的物料行数}, "names": [待审批单号]}。"""
    approvals = frappe.get_all("OA Price Approval", filters={"status": ["in", ["草稿", "待审批"]]},
                               fields=["name", "status"], limit_page_length=0)
    pending = [row.get("name") for row in approvals if row.get("status") == "待审批"]
    unquoted = {}
    if pending:
        lines = frappe.get_all("OA Price Approval Line", filters={"parent": ["in", pending]},
                               fields=["name", "parent"], limit_page_length=0)
        quoted = {(row.get("price_approval"), row.get("price_line")) for row in frappe.get_all(
            "OA Price Approval Quote", filters={"price_approval": ["in", pending]},
            fields=["price_approval", "price_line"], limit_page_length=0)}
        for line in lines:
            if (line.get("parent"), line.get("name")) not in quoted:
                unquoted[line.get("parent")] = unquoted.get(line.get("parent"), 0) + 1
    return {"pending": len(pending), "draft": len(approvals) - len(pending), "unquoted": unquoted, "names": sorted(pending)}


def _load_await_pr():
    """需求审批通过、但物料行数量还没全部提成 PR 的采购申请：[{"request", "line"}]（和 list_materials_for_pr 同一口径）。"""
    requests = frappe.get_all(
        "OA Approval Request",
        filters={"request_type": "采购申请", "workflow_status": ["not in", ["草稿", "已拒绝", "已撤回"]]},
        fields=["name", "workflow_status", "business_status"], limit_page_length=0)
    approved = [row.get("name") for row in requests
                if (row.get("business_status") or "").startswith("需求已批准")
                or row.get("workflow_status") in ("已完成", "已通过", "已审批", "已结束")]
    if not approved:
        return []
    lines = frappe.get_all("OA Purchase Request Line", filters={"parent": ["in", approved]},
                           fields=["name", "parent", "quantity"], limit_page_length=0)
    cancelled_prs = set(frappe.get_all("OA Procurement Request", filters={"status": "已取消"}, pluck="name", limit_page_length=0))
    allocated = {}
    for row in frappe.get_all("OA Procurement Request Line", filters={"source_request": ["in", approved]},
                              fields=["source_request", "source_line", "quantity", "parent"], limit_page_length=0):
        if row.get("parent") not in cancelled_prs:
            key = (row.get("source_request"), row.get("source_line"))
            allocated[key] = allocated.get(key, 0.0) + _n(row.get("quantity"))
    dropped = {(row.get("source_request"), row.get("source_line")) for row in frappe.get_all(
        "OA Material Progress", filters={"status": "已取消", "source_request": ["in", approved]},
        fields=["source_request", "source_line"], limit_page_length=0)}
    return [{"request": line.get("parent"), "line": line.get("name")} for line in lines
            if (line.get("parent"), line.get("name")) not in dropped
            and _n(line.get("quantity")) - allocated.get((line.get("parent"), line.get("name")), 0.0) > 1e-6]


def _load_uncoded():
    """物料进度里还没编码的物料行：状态演示员工152、源单没被拒绝 / 撤回、物料编号为空。
    条件是物料进度页 ?uncoded=1 用的同一句 SQL（material_progress_query.UNCODED_SQL），点进去条数一样。"""
    from rayher_hr_payroll.material_progress_query import FROM_SQL, UNCODED_SQL

    return [{"name": row.get("name"), "request": row.get("source_request")} for row in frappe.db.sql(
        f"SELECT b.name, b.source_request {FROM_SQL} WHERE {UNCODED_SQL}", {}, as_dict=True)]


def _load_overdue_materials(today):
    """逾期未到的物料（物料进度的一行 = 采购申请的一行）：[{name, request, line, project, item, due}]，due = 逾期 PO 行里最早的演示员工116交期。
    条件是物料进度页 ?overdue=1 用的同一句 SQL（material_progress_query.overdue_sql），点进去条数一样。"""
    from rayher_hr_payroll.material_progress_query import FROM_SQL, overdue_due_sql, overdue_sql

    return [{"name": row.get("name"), "request": row.get("source_request") or "", "line": row.get("source_line") or "",
             "project": (row.get("project") or "").strip(), "item": (row.get("item_name") or "").strip(), "due": _iso(row.get("due"))}
            for row in frappe.db.sql(
                f"SELECT b.name, b.source_request, b.source_line, b.project, b.item_name, {overdue_due_sql()} AS due "
                f"{FROM_SQL} WHERE {overdue_sql()}", {"today": today}, as_dict=True)]


def _load_request_heads(names):
    """{申请单号: {subject, employee_name, project}}：明细清单里显示用。"""
    if not names:
        return {}
    return {row.get("name"): row for row in frappe.get_all(
        "OA Approval Request", filters={"name": ["in", sorted(names)]},
        fields=["name", "subject", "employee_name", "project"], limit_page_length=0)}


def _load_stage_counts():
    """[{"stage", "no_pr", "total"}]：物料进度按阶段分布（阶段 SQL 和物料进度页同一份），采购确认中再按有没有 PR 拆开。"""
    from rayher_hr_payroll.material_progress_query import FROM_SQL, stage_sql

    return [dict(row) for row in frappe.db.sql(
        f"SELECT {stage_sql()} AS stage, (COALESCE(b.pr_numbers,'')='') AS no_pr, COUNT(*) AS total "
        f"{FROM_SQL} GROUP BY stage, no_pr", {}, as_dict=True)]


def _load_chain_counts():
    """采购链路四个环节的累计存量。"""
    cancelled = set(frappe.get_all("OA Purchase Order", filters={"status": "已取消"}, pluck="name", limit_page_length=0))
    plan_rows = frappe.get_all("OA Procurement Payment Plan Row", filters={"parenttype": "OA Purchase Order"},
                               fields=["parent"], limit_page_length=0)
    return {
        "request": frappe.db.count("OA Approval Request", {
            "request_type": "采购申请", "workflow_status": ["not in", ["草稿", "已拒绝", "已撤回"]]}),
        "pr": frappe.db.count("OA Procurement Request", {"status": ["!=", "已取消"]}),
        "po": frappe.db.count("OA Purchase Order", {"status": ["!=", "已取消"]}),
        "payment": sum(1 for row in plan_rows if row.get("parent") not in cancelled),
    }


def _load_chain_breakdown():
    """采购链路四个环节按状态拆开（条件和 _load_chain_counts 一样，每个环节各状态加起来 = 图上的数）：
    {"request": {状态: 张数}, "pr": {...}, "po": {...}, "payment": {期次状态: 期数}}。"""
    def grouped(doctype, filters, field="status"):
        out = {}
        for row in frappe.get_all(doctype, filters=filters, fields=[field], limit_page_length=0):
            key = (row.get(field) or "").strip() or "（空）"
            out[key] = out.get(key, 0) + 1
        return out

    cancelled = set(frappe.get_all("OA Purchase Order", filters={"status": "已取消"}, pluck="name", limit_page_length=0))
    payment = {}
    for row in frappe.get_all("OA Procurement Payment Plan Row", filters={"parenttype": "OA Purchase Order"},
                              fields=["parent", "status"], limit_page_length=0):
        if row.get("parent") not in cancelled:
            key = (row.get("status") or "").strip() or "（空）"
            payment[key] = payment.get(key, 0) + 1
    return {
        "request": grouped("OA Approval Request", {"request_type": "采购申请", "workflow_status": ["not in", ["草稿", "已拒绝", "已撤回"]]},
                           "workflow_status"),
        "pr": grouped("OA Procurement Request", {"status": ["!=", "已取消"]}),
        "po": grouped("OA Purchase Order", {"status": ["!=", "已取消"]}),
        "payment": payment,
    }


# ---------------------------------------------------------------- 加工（纯函数，测试直接喂数据）
def _received(row):
    """这一行算不算已到齐：数量够了，而且没有被判退货（同 procurement_chain._line_received）。"""
    return _n(row["received"]) >= _n(row["quantity"]) and row["inspection"] != "退货中"


def classify(rows, today):
    """把演示员工116已生效的 PO 物料行分到各个口径里（同一行可以同时算"待到货"和"待验收"：部分到货）。"""
    out = {name: [] for name in ("transit", "to_arrive", "to_inspect", "exchange", "returning", "overdue", "week")}
    monday = today - timedelta(days=today.weekday())
    week = (monday.isoformat(), (monday + timedelta(days=6)).isoformat())
    for row in rows:
        if row["po_status"] not in EFFECTIVE_PO:
            continue
        state, got, want = row["inspection"], _n(row["received"]), _n(row["quantity"])
        done = _received(row)
        if not done:
            out["transit"].append(row)
        if state == "换货中":
            out["exchange"].append(row)
        elif state == "退货中":
            out["returning"].append(row)
        if got < want and state != "退货中":
            out["to_arrive"].append(row)
        if got > 0 and state in ("", "未验收", "待验收"):
            out["to_inspect"].append(row)
        due = _iso(row["due"])
        if due and not done:
            if due < today.isoformat():
                out["overdue"].append(row)
            if week[0] <= due <= week[1]:
                out["week"].append(row)
    return out


def month_event_items(records):
    """({(PO, 物料行): 登记日期} 本月到货, 同样的 本月验收通过)：按 (PO, 物料行) 去重；登记里没有明细时按一条登记算一项。"""
    arrived, passed = {}, {}
    for index, record in enumerate(records):
        try:
            details = json.loads(record.get("details_json") or "[]")
        except (TypeError, ValueError):
            details = []
        details = [item for item in details if isinstance(item, dict)] if isinstance(details, list) else []
        po, day = record.get("purchase_order"), _iso(record.get("record_date"))
        if record.get("record_type") == "到货":
            if details:
                arrived.update({(po, item.get("line") or f"#{index}-{i}"): day for i, item in enumerate(details)})
            else:
                arrived[(po, f"record-{index}")] = day
        elif record.get("record_type") == "验收":
            passed.update({(po, item.get("line") or f"#{index}-{i}"): day for i, item in enumerate(details) if item.get("status") == "已通过"})
    return arrived, passed


def month_events(records):
    """(本月到货的物料行数, 本月验收通过的物料行数)。"""
    arrived, passed = month_event_items(records)
    return len(arrived), len(passed)


def _lines(ctx):
    return ctx.memo("proc.lines", lambda: classify(_load_live_lines(), _today(ctx)))


def _overdue_info(ctx):
    """逾期的 PO 物料行（PO 口径：交期已逾期的 PO、提醒）：{PO: 最久逾期天数}、物料行数。"""
    def build():
        rows = _lines(ctx)["overdue"]
        pos = {}
        for row in rows:
            late = _days_since(ctx, _iso(row["due"]))
            pos[row["po"]] = max(pos.get(row["po"], 0), late)
        return {"pos": pos, "rows": len(rows)}
    return ctx.memo("proc.overdue", build)


def _overdue_materials(ctx):
    """逾期未到的物料（物料口径：物料逾期未到、缺料影响的项目、逾期了多久）。
    一项 = 物料进度看板的一行（采购申请的一行，已取消的不算），和物料进度页「交期已过未收齐」同一句 SQL；
    项目取物料进度上的项目（页面 ?project= 按它筛）。2026-10-13 对齐：原来按 PO 行算，没有来源的 PO 行、已取消的物料也算进来，
    点进去对不上。{"materials": {物料进度名: 逾期天数}, "rows": [...], "projects": {项目: {"keys": {名: 天数}, "items": [物料名]}}}"""
    def build():
        rows = sorted(_load_overdue_materials(ctx.today), key=lambda row: (row["due"] or "9999-12-31", row["name"]))
        materials, projects = {}, {}
        for row in rows:
            late = _days_since(ctx, row["due"]) if row["due"] else 0
            materials[row["name"]] = late
            if row["project"]:
                bucket = projects.setdefault(row["project"], {"keys": {}, "items": []})
                bucket["keys"][row["name"]] = late
                if row["item"] and row["item"] not in bucket["items"]:
                    bucket["items"].append(row["item"])
        return {"materials": materials, "rows": rows, "projects": projects}
    return ctx.memo("proc.material_overdue", build)


def _inspect_info(ctx):
    """待验收的 PO 各自"到货多少天了"（从最近一条到货登记起算）；超过 7 天的算久拖。"""
    def build():
        rows = _lines(ctx)["to_inspect"]
        po_names = {row["po"] for row in rows}
        latest = _load_latest_arrivals(po_names)
        waited = {po: _days_since(ctx, day) for po, day in latest.items() if po in po_names and day}
        return {"waited": waited, "stale": {po: days for po, days in waited.items() if days > STALE_INSPECT_DAYS}}
    return ctx.memo("proc.inspect", build)


def _payment_items(ctx):
    return ctx.memo("proc.pay_items", _load_payment_items)


def _planned_passed(ctx):
    """和明细清单同一份行（_pay_plan_rows）：已付完 / 未付为 0 的期次不算（原来卡片算了、清单没列，2026-10-13 对齐）。"""
    def build():
        rows = _pay_plan_rows(ctx, True)
        return {"count": len(rows), "amount": sum(item["owed"] for item in rows),
                "oldest": max((_days_since(ctx, item["planned"]) for item in rows), default=0)}
    return ctx.memo("proc.planned_passed", build)


def _with_line_amounts(rows, lines):
    """PO 表头 → 金额换成物料行金额合计（amount），表头总额留在 header。"""
    by_po = {}
    for line in lines:
        by_po[line["po"]] = by_po.get(line["po"], 0.0) + _n(line["amount"])
    return [dict(row, header=row["amount"], amount=by_po.get(row["po"], 0.0)) for row in rows]


def _month_pos(ctx):
    """本月 / 上月的 PO（不含已取消，按创建月份）：金额 = 物料行金额合计（2026-10-13 决定，和「费用」页的采购同一口径）。
    cur_lines = 本月 PO 的物料行（按项目分布用），和金额同一次读取。"""
    def build():
        prev_start, _this_start, nxt = _month_bounds(ctx.period)
        heads = _load_month_pos(prev_start, nxt)
        lines = _load_po_line_amounts({row["po"] for row in heads})
        rows = _with_line_amounts(heads, lines)
        cur = [row for row in rows if row["month"] == ctx.period]
        names = {row["po"] for row in cur}
        return {"cur": cur, "prev": [row for row in rows if row["month"] != ctx.period],
                "cur_lines": [line for line in lines if line["po"] in names]}
    return ctx.memo("proc.month_pos", build)


def _top_rows(amounts, label_if_blank, limit=5):
    """金额从大到小，前 5 个 + 其他。"""
    items = sorted(((name or label_if_blank, value) for name, value in amounts.items() if value > 0), key=lambda item: -item[1])
    top, rest = items[:limit], sum(value for _, value in items[limit:])
    peak = top[0][1] if top else 1
    rows = [bar_row(name, _wan(value), value / peak * 100) for name, value in top]
    if rest > 0:
        rows.append(bar_row(f"其他（{len(items) - limit} 项）", _wan(rest), rest / peak * 100))
    return rows


def _per_po(rows):
    return len({row["po"] for row in rows})


# ================================================================ 明细清单（点指标卡 / 提醒进去看到的）
# 每个清单用和指标卡同一份数据（同一个 _lines / _overdue_info / _payment_items …）逐条列出来：条数 = 卡片上的数字。
def _fmt(value):
    return f"{_n(value):g}"


def _qty(row):
    return f"{_fmt(row['received'])} / {_fmt(row['quantity'])}"


def _sorted_days(rows):
    return sorted(rows, key=lambda row: (_iso(row["due"]) or "9999-12-31", row["po"], row["item"]))


def _by_po(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["po"], []).append(row)
    return grouped


def _po_list_drill(ctx, key, title, rows, note="", tone_of=None):
    """按 PO 一行：PO | 供应商 | 状态 | 物料 | 最近演示员工116交期。"""
    grouped = _by_po(rows)

    def first_due(items):
        return min((_iso(r["due"]) for r in items if r["due"]), default="")

    out = []
    for po in sorted(grouped, key=lambda name: (first_due(grouped[name]) or "9999-12-31", name)):
        items = grouped[po]
        first = items[0]
        due = first_due(items)
        late = _days_since(ctx, due) if due and due < ctx.today else 0
        out.append(drill_row([po, first["supplier"] or "—", first["po_status"], f"{len(items)} 项", due or "未填", f"{late} 天" if late else "—"],
                             _po_open(ctx, po), tone=(tone_of(late) if tone_of else "")))
    return drill(key, title, [("PO",), ("供应商",), ("状态",), ("物料", "r"), ("最近演示员工116交期", "r"), ("已逾期", "r")], out,
                 summary=f"共 {len(grouped)} 个 PO，{len(rows)} 项物料", note=note)


def _line_drill(ctx, key, title, rows, columns, cells, note="", tone_of=None, summary=None):
    out = [drill_row(cells(row), _po_open(ctx, row["po"]), tone=(tone_of(row) if tone_of else "")) for row in rows]
    return drill(key, title, columns, out, summary=summary or f"共 {len(rows)} 项物料，来自 {_per_po(rows)} 个 PO", note=note)


@provider("drill.proc.po_transit", "drill", visible=_po_ok, title="PO 在途")
def drill_po_transit(ctx):
    return _po_list_drill(ctx, "drill.proc.po_transit", "在途的 PO", _lines(ctx)["transit"],
                          note="演示员工116已生效、还有物料没收齐的 PO；“物料”是还没收齐的项数。")


@provider("drill.proc.po_overdue", "drill", visible=_po_ok, title="交期已逾期的 PO")
def drill_po_overdue(ctx):
    return _po_list_drill(ctx, "drill.proc.po_overdue", "交期已逾期的 PO", _lines(ctx)["overdue"],
                          note="演示员工116交期早于今天、还没收齐的物料所在的 PO；红色 = 逾期超过 7 天。", tone_of=lambda late: "bad" if late > 7 else "warn")


@provider("drill.proc.week_arrive", "drill", visible=_po_ok, title="本周预计到货")
def drill_week_arrive(ctx):
    today = ctx.today

    def cells(row):
        due = _iso(row["due"])
        weekday = date.fromisoformat(due).weekday()
        return [f"{due[5:]} 周{WEEKDAYS[weekday]}", row["po"], row["item"] or "—", _qty(row), row["project"] or "—"]
    return _line_drill(ctx, "drill.proc.week_arrive", "本周预计到货的物料", _sorted_days(_lines(ctx)["week"]),
                       [("演示员工116交期",), ("PO",), ("物料",), ("已到 / 订购", "r"), ("项目",)], cells,
                       tone_of=lambda row: "bad" if _iso(row["due"]) < today else ("warn" if _iso(row["due"]) == today else ""),
                       note="演示员工116交期落在本周（周一到周日）、还没收齐的物料；红色 = 交期已过还没到，黄色 = 今天。")


@provider("drill.proc.to_arrive", "drill", visible=_po_ok, title="待登记到货")
def drill_to_arrive(ctx):
    return _line_drill(ctx, "drill.proc.to_arrive", "待登记到货的物料", _sorted_days(_lines(ctx)["to_arrive"]),
                       [("PO",), ("物料",), ("已到 / 订购", "r"), ("演示员工116交期", "r"), ("项目",)],
                       lambda row: [row["po"], row["item"] or "—", _qty(row), _iso(row["due"]) or "未填", row["project"] or "—"],
                       note="演示员工116已生效的 PO 里，到货数量还不够的物料行（退货中的不算）。")


@provider("drill.proc.to_inspect", "drill", visible=_po_ok, title="待验收")
def drill_to_inspect(ctx):
    waited = _inspect_info(ctx)["waited"]
    rows = sorted(_lines(ctx)["to_inspect"], key=lambda row: (-waited.get(row["po"], -1), row["po"], row["item"]))
    return _line_drill(ctx, "drill.proc.to_inspect", "待验收的物料", rows,
                       [("PO",), ("物料",), ("已到 / 订购", "r"), ("到货已", "r"), ("项目",)],
                       lambda row: [row["po"], row["item"] or "—", _qty(row), f"{waited[row['po']]} 天" if row["po"] in waited else "—", row["project"] or "—"],
                       tone_of=lambda row: "bad" if waited.get(row["po"], 0) > STALE_INSPECT_DAYS else "",
                       note=f"已有到货、还没登记验收结果的物料；天数从该 PO 最近一条到货登记起算，红色 = 超过 {STALE_INSPECT_DAYS} 天。")


@provider("drill.proc.inspect_wait", "drill", visible=_po_ok, title="待验收等了多久")
def drill_inspect_wait(ctx):
    return _inspect_po_drill(ctx, "drill.proc.inspect_wait", "待验收的 PO", _inspect_info(ctx)["waited"])


@provider("drill.proc.inspect_stale", "drill", visible=_po_ok, title="到货久未验收")
def drill_inspect_stale(ctx):
    return _inspect_po_drill(ctx, "drill.proc.inspect_stale", f"到货超过 {STALE_INSPECT_DAYS} 天还没验收的 PO", _inspect_info(ctx)["stale"])


def _inspect_po_drill(ctx, key, title, waited):
    lines = _by_po(_lines(ctx)["to_inspect"])
    out = []
    for po, days in sorted(waited.items(), key=lambda item: (-item[1], item[0])):
        items = lines.get(po, [])
        supplier = items[0]["supplier"] if items else ""
        out.append(drill_row([po, supplier or "—", f"{len(items)} 项", f"{days} 天"], _po_open(ctx, po), tone="bad" if days > STALE_INSPECT_DAYS else ""))
    return drill(key, title, [("PO",), ("供应商",), ("待验收物料", "r"), ("到货已", "r")], out, summary=f"共 {len(out)} 个 PO",
                 note=f"已有到货、还没验收的 PO；天数从最近一次到货登记起算，红色 = 超过 {STALE_INSPECT_DAYS} 天。")


def _state_drill(ctx, key, title, rows, state):
    return _line_drill(ctx, key, title, _sorted_days(rows), [("PO",), ("物料",), ("已到 / 订购", "r"), ("状态",), ("项目",)],
                       lambda row: [row["po"], row["item"] or "—", _qty(row), state, row["project"] or "—"], tone_of=lambda row: "warn")


@provider("drill.proc.exchange", "drill", visible=_po_ok, title="换货中")
def drill_exchange(ctx):
    return _state_drill(ctx, "drill.proc.exchange", "换货中的物料", _lines(ctx)["exchange"], "换货中")


@provider("drill.proc.return", "drill", visible=_po_ok, title="退货中")
def drill_return(ctx):
    return _state_drill(ctx, "drill.proc.return", "退货中的物料", _lines(ctx)["returning"], "退货中")


def _month_event_drill(ctx, key, title, which, note):
    _, this_start, nxt = _month_bounds(ctx.period)
    arrived, passed = month_event_items(_load_month_records(this_start, nxt))
    events = arrived if which == "arrived" else passed
    names = {}
    po_names = sorted({po for po, _line in events})
    if po_names:
        for line in frappe.get_all("OA Purchase Order Line", filters={"parent": ["in", po_names], "parenttype": "OA Purchase Order"},
                                   fields=["name", "item_name", "project"], limit_page_length=0):
            names[line.get("name")] = (line.get("item_name") or "").strip()
    rows = [drill_row([day or "—", po, names.get(line) or "（登记没写明细）"], _po_open(ctx, po))
            for (po, line), day in sorted(events.items(), key=lambda item: (item[1] or "", item[0][0]), reverse=True)]
    return drill(key, title, [("登记日",), ("PO",), ("物料",)], rows, summary=f"共 {len(events)} 项物料", note=note)


@provider("drill.proc.month_arrived", "drill", visible=_po_ok, title="本月已到货")
def drill_month_arrived(ctx):
    return _month_event_drill(ctx, "drill.proc.month_arrived", f"{int(ctx.period[5:])} 月已到货的物料", "arrived",
                              "本月登记的到货记录涉及的物料行（不含换货到货），同一 PO 的同一行只算一次。")


@provider("drill.proc.month_inspected", "drill", visible=_po_ok, title="本月已验收")
def drill_month_inspected(ctx):
    return _month_event_drill(ctx, "drill.proc.month_inspected", f"{int(ctx.period[5:])} 月已验收通过的物料", "passed",
                              "本月登记的验收记录里结果为「已通过」的物料行，同一 PO 的同一行只算一次。")


@provider("drill.proc.month_amount", "drill", visible=_money_ok, title="本月采购金额")
def drill_month_amount(ctx):
    rows = sorted(_month_pos(ctx)["cur"], key=lambda row: (-row["amount"], row["po"]))
    out = [drill_row([row["po"], row["supplier"] or "—", row.get("status") or "—", row.get("day") or "—", _wan_full(row["amount"])], _po_open(ctx, row["po"]))
           for row in rows]
    differ = [row["po"] for row in rows if abs(_n(row.get("header")) - row["amount"]) > 0.005]
    note = "本月创建的采购订单（PO），不含已取消，含还没生效的 PO；金额 = 物料行金额合计（和「费用」页的采购同一口径）。"
    if differ:
        note += f"其中 {len(differ)} 个 PO 的表头总额和行金额合计对不上（{'、'.join(differ[:3])}{' 等' if len(differ) > 3 else ''}），以行金额为准。"
    return drill("drill.proc.month_amount", f"{int(ctx.period[5:])} 月新下的 PO", [("PO",), ("供应商",), ("状态",), ("下单日",), ("行金额合计", "r")], out,
                 summary=f"共 {len(rows)} 个 PO，合计 {_wan(sum(row['amount'] for row in rows))}", note=note)


def _wan_full(amount):
    return f"¥ {_n(amount):,.2f}"


@provider("drill.proc.suppliers", "drill", visible=_money_ok, title="本月下单供应商")
def drill_suppliers(ctx):
    grouped = {}
    for row in _month_pos(ctx)["cur"]:
        entry = grouped.setdefault(row["supplier"] or "（未填供应商）", [0, 0.0])
        entry[0] += 1
        entry[1] += row["amount"]
    ranked = sorted(grouped.items(), key=lambda item: (-item[1][1], item[0]))
    out = [drill_row([name, f"{count} 张", _wan_full(amount)]) for name, (count, amount) in ranked]
    named = [name for name in grouped if name != "（未填供应商）"]
    return drill("drill.proc.suppliers", f"{int(ctx.period[5:])} 月下单的供应商", [("供应商",), ("PO", "r"), ("金额", "r")], out,
                 summary=f"共 {len(named)} 家，{sum(entry[0] for entry in grouped.values())} 张 PO",
                 note="本月创建的采购订单（不含已取消）涉及的供应商，金额 = 物料行金额合计；供应商是手填文本，去掉前后空格后同名算一家；没填供应商的单独一行，不算家数。")


def _project_totals(ctx):
    totals = {}
    for row in _month_pos(ctx)["cur_lines"]:
        totals[row["project"]] = totals.get(row["project"], 0.0) + _n(row["amount"])
    return totals


@provider("drill.proc.projects", "drill", visible=_money_ok, title="本月采购金额 · 项目")
def drill_projects(ctx):
    totals = {}
    for name, amount in _project_totals(ctx).items():
        totals[name or "非项目"] = totals.get(name or "非项目", 0.0) + amount
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    out = [drill_row([name, _wan_full(amount)]) for name, amount in ranked]
    return drill("drill.proc.projects", f"{int(ctx.period[5:])} 月采购金额 · 按项目", [("项目",), ("行金额", "r")], out,
                 summary=f"共 {len(ranked)} 个项目，合计 {_wan(sum(totals.values()))}",
                 note="本月创建的 PO（不含已取消）按物料行所属项目合计行金额；没填项目的归「非项目」。合计等于「本月采购金额」。")


def _pay_plan_rows(ctx, only_passed):
    today = ctx.today
    rows = []
    for item in _payment_items(ctx):
        owed = max(item["amount"] - item["paid"], 0)
        if item["work_status"] == "已付款" or owed <= 0:
            continue
        if only_passed and not (item["planned"] and item["planned"] < today):
            continue
        rows.append(dict(item, owed=owed))
    rows.sort(key=lambda item: (item["planned"] or "9999-12-31", item["po"]))
    return rows


def _pay_plan_drill(ctx, key, title, only_passed, note):
    rows = _pay_plan_rows(ctx, only_passed)
    out = []
    for item in rows:
        late = _days_since(ctx, item["planned"]) if item["planned"] and item["planned"] < ctx.today else 0
        out.append(drill_row([item["po"], item["planned"] or "没排期", item["work_status"], _wan_full(item["owed"]), f"{late} 天" if late else "—"],
                             target("procpay.work", po=item["po"]), tone="bad" if late else ""))
    return drill(key, title, [("PO",), ("计划付款日",), ("状态",), ("未付金额", "r"), ("已过", "r")], out,
                 summary=f"共 {len(rows)} 期，未付 {_wan(sum(item['owed'] for item in rows))}", note=note)


@provider("drill.proc.pay_planned_passed", "drill", visible=_pay_ok, title="已过计划付款日")
def drill_pay_planned_passed(ctx):
    return _pay_plan_drill(ctx, "drill.proc.pay_planned_passed", "已过计划付款日的付款期次", True,
                           "填了计划付款日、日期已过、还没付完的采购付款期次；没填计划付款日的不算。")


@provider("drill.proc.pay_plan", "drill", visible=_pay_ok, title="未来 30 天要付多少")
def drill_pay_plan(ctx):
    return _pay_plan_drill(ctx, "drill.proc.pay_plan", "还没付清的采购付款期次", False,
                           "按计划付款日排；红色 = 已过计划日；没填计划日的排在最后（“没排期”）。报销单、付款单没有计划日，不在这里。")


def _ranked_projects(ctx):
    projects = _overdue_materials(ctx)["projects"]
    return sorted(projects.items(), key=lambda item: (-len(item[1]["keys"]), item[0]))


@provider("drill.proc.risk_projects", "drill", visible=_board_ok, title="缺料影响的项目")
def drill_risk_projects(ctx):
    ranked = _ranked_projects(ctx)
    out = []
    for name, bucket in ranked:
        items = bucket["items"]
        worst = max(bucket["keys"].values())
        # 点一行 = 物料进度页只看这个项目的逾期物料（?overdue=1&project=），条数 = “逾期物料”这一列
        out.append(drill_row([name, f"{len(bucket['keys'])} 项", f"{worst} 天", "、".join(items[:3]) + (" 等" if len(items) > 3 else "")],
                             target("material.overdue", project=name), tone="bad" if worst > 7 else "warn"))
    return drill("drill.proc.risk_projects", "缺料影响的项目", [("项目",), ("逾期物料", "r"), ("最久逾期", "r"), ("物料",)], out,
                 summary=f"共 {len(ranked)} 个项目",
                 note="有物料超过演示员工116交期还没到的项目（项目取物料进度看板上的项目）；红色 = 最久逾期超过 7 天；项目为空的不列。点一行看这个项目的逾期物料。")


@provider("drill.proc.await_pr", "drill", visible=_chain_ok, title="待提 PR 的申请")
def drill_await_pr(ctx):
    """和卡片同一份数据（_load_await_pr）：一张申请一行，“物料”是还没提成 PR 的行数。"""
    rows = ctx.memo("proc.await_pr", _load_await_pr)
    counts = {}
    for row in rows:
        counts[row["request"]] = counts.get(row["request"], 0) + 1
    heads = _load_request_heads(set(counts))
    out = []
    for name in sorted(counts):
        head = heads.get(name) or {}
        out.append(drill_row([name, (head.get("subject") or "").strip() or "—", head.get("employee_name") or "—",
                              (head.get("project") or "").strip() or "—", f"{counts[name]} 项"], _await_pr_open(ctx, name)))
    return drill("drill.proc.await_pr", "待提 PR 的采购申请", [("单号",), ("事由",), ("申请人",), ("项目",), ("待提 PR 物料", "r")], out,
                 summary=f"共 {len(counts)} 张，{len(rows)} 项物料",
                 note="需求审批已通过、物料行数量还没全部提成 PR 的采购申请（已取消的 PR 数量退回来算；物料进度里已取消的物料不算）。"
                      "点一行到物料进度看板里这张申请的物料，PMC 在那里提 PR。")


def _await_pr_open(ctx, request):
    """PMC、采购经理在物料进度看板提 PR；看不了看板的人去申请详情（能打开的话）。"""
    if _board_ok(ctx):
        return target("material.progress", request=request)
    return target("procurement.detail", request=request) if _can_open_requests(ctx) else None


@provider("drill.proc.price_missing_quote", "drill", visible=_chain_ok, title="价格审批缺报价")
def drill_price_missing_quote(ctx):
    unquoted = ctx.memo("proc.price_state", _load_price_state)["unquoted"]
    out = [drill_row([name, f"{count} 项"], target("price.approvals", view="approvals", approval=name), tone="warn")
           for name, count in sorted(unquoted.items(), key=lambda item: (-item[1], item[0]))]
    return drill("drill.proc.price_missing_quote", "有物料没有报价的价格审批单", [("价格审批单",), ("没有报价的物料", "r")], out,
                 summary=f"共 {len(unquoted)} 张，{sum(unquoted.values())} 项物料",
                 note="已提交（待审批）的价格审批单里，一个供应商报价都没有的物料行；演示员工113没法给这些物料选供应商。")


@provider("drill.proc.arrival_inspect", "drill", visible=_po_ok, title="到货与验收")
def drill_arrival_inspect(ctx):
    """图上的四个数逐条列出来：本月已到货、本月验收通过（本月登记），待验收、待到货（当前存量）。"""
    _, this_start, nxt = _month_bounds(ctx.period)
    arrived, passed = month_event_items(_load_month_records(this_start, nxt))
    data = _lines(ctx)
    names = {}
    po_names = sorted({po for po, _line in list(arrived) + list(passed)})
    if po_names:
        for line in frappe.get_all("OA Purchase Order Line", filters={"parent": ["in", po_names], "parenttype": "OA Purchase Order"},
                                   fields=["name", "item_name"], limit_page_length=0):
            names[line.get("name")] = (line.get("item_name") or "").strip()
    out = []
    for label, events in (("本月已到货", arrived), ("本月已验收通过", passed)):
        for (po, line), day in sorted(events.items(), key=lambda item: (item[1] or "", item[0][0]), reverse=True):
            out.append(drill_row([label, po, names.get(line) or "（登记没写明细）", day or "—"], _po_open(ctx, po), tone="ok"))
    for label, rows in (("待验收", data["to_inspect"]), ("待到货", data["to_arrive"])):
        for row in _sorted_days(rows):
            out.append(drill_row([label, row["po"], row["item"] or "—", f"交期 {_iso(row['due'])}" if row["due"] else "交期未填"],
                                 _po_open(ctx, row["po"]), tone="warn" if label == "待验收" else ""))
    summary = (f"本月已到货 {len(arrived)} 项 · 本月已验收通过 {len(passed)} 项 · 待验收 {len(data['to_inspect'])} 项 · "
               f"待到货 {len(data['to_arrive'])} 项")
    return drill("drill.proc.arrival_inspect", "到货与验收", [("类别",), ("PO",), ("物料",), ("日期",)], out, summary=summary,
                 note="前两类是本月的到货、验收登记（同一 PO 的同一行只算一次）；后两类是现在还没办完的存量（演示员工116已生效的 PO）。部分到货的物料行会同时出现在待验收和待到货里。")


CHAIN_STEPS = (("request", "OA 申请"), ("pr", "PR"), ("po", "PO"), ("payment", "付款期次"))


@provider("drill.proc.chain", "drill", visible=_po_ok, title="采购链路")
def drill_chain(ctx):
    """图上四个累计数按状态拆开（每个环节各状态加起来 = 图上的数）。行不再往下链：
    现有的列表页按“最近 200 张 / 自己的筛选”显示，点过去条数对不上，不如不链。"""
    breakdown = ctx.memo("proc.chain_breakdown", _load_chain_breakdown)
    out = []
    for step, label in CHAIN_STEPS:
        for status, count in sorted(breakdown[step].items(), key=lambda item: (-item[1], item[0])):
            out.append(drill_row([label, status, count]))
    totals = " · ".join(f"{label} {sum(breakdown[step].values())}" for step, label in CHAIN_STEPS)
    return drill("drill.proc.chain", "采购链路（累计）按状态", [("环节",), ("状态",), ("数量", "r")], out, summary=totals,
                 note="历史累计，不按月份：OA 申请 = 已提交且没被拒绝 / 撤回的采购申请；PR、PO 不含已取消；付款期次 = 没取消的 PO 的付款计划期数（按期次状态）。")


@provider("drill.proc.month_trend", "drill", visible=_money_ok, title="近 6 个月采购金额")
def drill_month_trend(ctx):
    months, totals, counts = _trend(ctx)
    out = [drill_row([f"{key[:4]} 年 {int(key[5:])} 月", f"{counts.get(key, 0)} 个", _wan_full(totals.get(key, 0.0))],
                     target("drill", item="proc.month_amount", period=key) if counts.get(key) else None, tone="hot" if key == ctx.period else "")
           for key in months]
    return drill("drill.proc.month_trend", "近 6 个月采购金额", [("月份",), ("PO", "r"), ("行金额合计", "r")], out,
                 summary=f"合计 {_wan(sum(totals.get(key, 0.0) for key in months))}",
                 note="每月创建的 PO（不含已取消），金额 = 物料行金额合计；点一个月看那个月的 PO。")


# ================================================================ 加急采购（老板、采购、PMC 关心的：催得最紧的那几张）
URGENT_TYPES = ("采购申请", "购买申请")
URGENT_SKIP_STATUS = ("草稿", "已拒绝", "已撤回", "已取消")
URGENT_STUCK_DAYS = 3           # “没动静”= 超过 3 天（不含 3 天，按日历日）


def _urgent_ok(ctx):
    """加急采购清单：采购链路的人、演示员工113、总经理（管理层角色）。
    清单每一行点进申请详情，详情按角色给读权限（oa_access._can_read）：只持有岗位、没有采购 / 管理层角色的人打不开，
    所以也不给看这张清单（2026-10-13：可见范围对齐到“点得开”，没有另外给岗位开读权限）。"""
    return ((ctx.holds("general_manager", "vice_manager", "procurement_manager", "pmc")
             or ctx.can("System Manager", "QIHENG Demo Business Executive"))
            and _can_open_requests(ctx) and _gate_open(ctx, "chain"))


def _load_urgent():
    """加急（urgency = 加急）的采购申请、购买申请里还没办完的：
    [{name, type, subject, applicant, project, expected, approving, label, since}]。
    采购申请审批通过后的“现在在哪”取采购链路的阶段（等 PMC 提 PR / 询价 / 价格审批 / PO 执行）；购买申请取当前审批节点或付款状态。"""
    from rayher_hr_payroll.api import oa_entry
    from rayher_hr_payroll.dashboard.projects import STAGE_DEMAND, STAGE_EXEC, stage_of

    rows = frappe.get_all(
        "OA Approval Request",
        filters={"request_type": ["in", list(URGENT_TYPES)], "urgency": "加急", "workflow_status": ["not in", list(URGENT_SKIP_STATUS)]},
        fields=["name", "request_type", "subject", "employee_name", "project", "workflow_status", "business_status",
                "current_step_label", "expected_delivery_date", "operation_log", "modified", "creation"], limit_page_length=0)
    acted = {}
    if rows:
        for step in frappe.get_all("OA Approval Step", filters={"parent": ["in", [row["name"] for row in rows]], "parenttype": "OA Approval Request"},
                                   fields=["parent", "acted_on"], limit_page_length=0):
            day = _iso(step.get("acted_on"))
            if day and day > acted.get(step["parent"], ""):
                acted[step["parent"]] = day
    out, executing = [], []
    for row in rows:
        business = (row.get("business_status") or "").strip()
        approving = row.get("workflow_status") in ("待审批", "待办理")
        label = (row.get("current_step_label") or "").strip() or "审批中"
        chain = None
        if not approving and row["request_type"] == "采购申请":
            chain = oa_entry._calculate_procurement_chain(frappe.get_doc("OA Approval Request", row["name"]))
            label = chain.get("label") or label
        elif not approving:
            label = business or "待付款"
        # 在途 = 需求审批 / 采购执行（和“我负责的项目”、采购申请列表同一套阶段规则，projects.stage_of）
        if stage_of(dict(row, procurement_chain=chain)) not in (STAGE_DEMAND, STAGE_EXEC):
            continue
        if chain is not None:
            executing.append(row["name"])
        out.append({"name": row["name"], "type": row["request_type"], "subject": (row.get("subject") or "").strip(),
                    "applicant": row.get("employee_name") or "", "project": (row.get("project") or "").strip(),
                    "expected": _iso(row.get("expected_delivery_date")), "approving": approving, "label": label,
                    # 和申请页上的“已等几天”同一个起点：最近一次签批，没有就从最近一次“提交申请”（再没有就从最后修改、创建）算起
                    "since": acted.get(row["name"]) or _submitted_day(row) or _iso(row.get("modified")) or _iso(row.get("creation"))})
    # 已进入采购执行的：PR / 价格审批 / PO 有变动也算有动静（2026-10-13：原来只看签批，采购在推进也显示“没动静”）
    moved = _chain_activity(executing)
    for item in out:
        if moved.get(item["name"], "") > (item["since"] or ""):
            item["since"] = moved[item["name"]]
    return out


def _chain_activity(names):
    """{采购申请: 它的 PR / 价格审批 / PO 最近一次修改的日期}。"""
    latest = {}
    if not names:
        return latest
    for line_type, head_type in (("OA Procurement Request Line", "OA Procurement Request"),
                                 ("OA Price Approval Line", "OA Price Approval"), ("OA Purchase Order Line", "OA Purchase Order")):
        lines = frappe.get_all(line_type, filters={"source_request": ["in", sorted(names)]}, fields=["parent", "source_request"],
                               limit_page_length=0)
        parents = sorted({line.get("parent") for line in lines if line.get("parent")})
        if not parents:
            continue
        changed = {row.get("name"): _iso(row.get("modified")) for row in frappe.get_all(
            head_type, filters={"name": ["in", parents]}, fields=["name", "modified"], limit_page_length=0)}
        for line in lines:
            day = changed.get(line.get("parent"), "")
            if day > latest.get(line.get("source_request"), ""):
                latest[line.get("source_request")] = day
    return latest


def _submitted_day(row):
    """最近一次“提交申请”的日期（操作记录里取，同申请页的 submitted_on）；没有记录返回空。"""
    try:
        events = json.loads(row.get("operation_log") or "[]")
    except (TypeError, ValueError):
        return ""
    for event in reversed(events if isinstance(events, list) else []):
        if isinstance(event, dict) and event.get("action") == "提交申请":
            return _iso(event.get("acted_on"))
    return ""


def _urgent(ctx):
    """购买申请的功能开关关着时，购买申请的详情页打不开，清单里也不列。"""
    def build():
        direct = _gate_open(ctx, "direct")
        return sorted((item for item in _load_urgent() if direct or item["type"] != "购买申请"), key=lambda item: item["since"] or "9999")
    return ctx.memo("proc.urgent", build)


def _urgent_wait(ctx, item):
    return max(0, _days_since(ctx, item["since"])) if item["since"] else 0


def _urgent_target(item):
    return target("procurement.detail" if item["type"] == "采购申请" else "directpurchase.detail", request=item["name"])


@provider("proc.urgent", "kpi", visible=_urgent_ok, title="加急采购在途")
def _kpi_urgent(ctx):
    items = _urgent(ctx)
    stuck = [item for item in items if _urgent_wait(ctx, item) > URGENT_STUCK_DAYS]
    late = [item for item in items if item["expected"] and item["expected"] < ctx.today]
    parts = []
    if stuck:
        parts.append(f"{len(stuck)} 张超过 {URGENT_STUCK_DAYS} 天没动静")
    if late:
        parts.append(f"{len(late)} 张已过期望到货日")
    return kpi("proc.urgent", "加急采购在途", len(items), "张", _now_sub(ctx, " · ".join(parts) if parts else ("都在演示员工152推进" if items else "")),
               tone="bad" if stuck or late else ("hot" if items else ""), to=drill_to("proc.urgent", ctx) if items else None,
               hint="申请单上勾了「加急」的采购申请、购买申请，还没办完的（购买申请 = 还没付完款，采购申请 = 采购链路还没关闭）。"
                    f"“没动静”= 距离最近一次进展（审批签字；已进入采购执行的，还算 PR / 价格审批 / PO 的变动）超过 {URGENT_STUCK_DAYS} 天"
                    "（按日历日，不含 3 天）。点进去看每一张现在在谁手上。")


@provider("drill.proc.urgent", "drill", visible=_urgent_ok, title="加急采购在途")
def drill_urgent(ctx):
    items = _urgent(ctx)
    out = []
    for item in items:
        wait = _urgent_wait(ctx, item)
        late = bool(item["expected"] and item["expected"] < ctx.today)
        out.append(drill_row([item["name"], item["type"], item["subject"] or "—", item["applicant"] or "—", item["project"] or "—", item["label"],
                              f"{wait} 天", item["expected"] or "—"], _urgent_target(item),
                             tone="bad" if late or wait > URGENT_STUCK_DAYS else "hot"))
    return drill("drill.proc.urgent", "加急采购在途", [("单号",), ("类型",), ("事由",), ("申请人",), ("项目",), ("现在在",), ("距上次进展", "r"), ("期望到货", "r")], out,
                 summary=f"共 {len(items)} 张",
                 note=f"红色 = 超过 {URGENT_STUCK_DAYS} 天没动静（最近一次审批签字，或 PR / 价格审批 / PO 的变动），或者已经过了期望到货日。")


@provider("alert.urgent", "alert", visible=_urgent_ok, title="加急采购卡住")
def _alert_urgent(ctx):
    items = _urgent(ctx)
    stuck = [item for item in items if _urgent_wait(ctx, item) > URGENT_STUCK_DAYS]
    if not stuck:
        return None
    worst = max(stuck, key=lambda item: _urgent_wait(ctx, item))
    return alert("alert.urgent", "bad", f"{len(stuck)} 张加急采购超过 {URGENT_STUCK_DAYS} 天没动静",
                 sub=f"最久的 {worst['name']}（{worst['subject'] or worst['type']}）卡在「{worst['label']}」{_urgent_wait(ctx, worst)} 天",
                 go="加急采购", to=drill_to("proc.urgent", ctx))


@provider("block.urgent_requests", "block", visible=_urgent_ok, title="加急采购")
def _block_urgent(ctx):
    items = _urgent(ctx)
    ranked = sorted(items, key=lambda item: -_urgent_wait(ctx, item))[:6]
    rows = []
    for item in ranked:
        wait = _urgent_wait(ctx, item)
        late = bool(item["expected"] and item["expected"] < ctx.today)
        sub = f"{item['label']} · {item['applicant']}" + (f" · {item['project']}" if item["project"] else "")
        rows.append(list_row(item["subject"] or item["name"], sub=sub, value=f"{wait} 天", tone="bad" if late or wait > URGENT_STUCK_DAYS else "warn",
                             to=_urgent_target(item)))
    return listing("block.urgent_requests", "加急采购", rows, sub="谁手上、距上次进展多久" if rows else "没有在途的加急采购",
                   more=f"全部 {len(items)} 张" if len(items) > len(ranked) else "", to=drill_to("proc.urgent", ctx) if items else None,
                   hint="加急的采购申请、购买申请里还没办完的，等得最久的在前；红色 = 超过 3 天没动静或已过期望到货日。点一行进申请详情。")


# ================================================================ KPI：采购
@provider("proc.to_compare", "kpi", visible=_chain_ok, title="待比价物料")
def _to_compare(ctx):
    rows = ctx.memo("proc.pr_lines", _load_pr_lines)
    return kpi("proc.to_compare", "待比价物料", len(rows), "项", sub=_now_sub(ctx, f"来自 {len({row['pr'] for row in rows})} 张 PR" if rows else ""),
               tone="hot" if rows else "", to=target("price.approvals", view="source"),
               hint="PR 里还没进价格审批的物料行（剩余可选数量大于 0，PR 还能生成价格审批单：不是草稿 / 已取消 / 已关闭）。"
                    "撤回或取消价格审批后，数量会回到这里。和价格审批页「PR 待比价物料」同一口径。")


@provider("proc.price_pending", "kpi", visible=_chain_ok, title="价格审批中")
def _price_pending(ctx):
    state = ctx.memo("proc.price_state", _load_price_state)
    names = state.get("names") or []
    # 点进去 = 价格审批单列表筛「待审批」；只有一张时直接打开那一张
    to = target("price.approvals", view="approvals", status="pending", approval=names[0] if len(names) == 1 else None)
    return kpi("proc.price_pending", "价格审批中", state["pending"], "张",
               sub=_now_sub(ctx, f"另有 {state['draft']} 张还在比价（草稿）" if state["draft"] else ""), to=to,
               hint="已提交、等演示员工113经理终审的价格审批单。草稿是采购还在比价，没算进来。")


@provider("proc.po_transit", "kpi", visible=_po_ok, title="PO 在途")
def _po_transit(ctx):
    data = _lines(ctx)
    pos = {row["po"] for row in data["transit"]}
    sub = _now_sub(ctx, f"待到货 {len(data['to_arrive'])} 项 · 待验收 {len(data['to_inspect'])} 项" if pos else "")
    return kpi("proc.po_transit", "PO 在途", len(pos), "个", sub=sub, to=drill_to("proc.po_transit", ctx) if pos else None,
               hint="在途 = 演示员工116已生效（已生效 / 供应商制作中 / 到货验收中 / 付款中）、还有物料没收齐的 PO。已关闭、已取消和演示员工116还没生效的草稿 PO 不算。")


@provider("proc.po_overdue", "kpi", visible=_po_ok, title="交期已逾期的 PO")
def _po_overdue(ctx):
    info = _overdue_info(ctx)
    count = len(info["pos"])
    sub = _now_sub(ctx, f"最久逾期 {max(info['pos'].values())} 天 · 共 {info['rows']} 项物料" if count else "")
    return kpi("proc.po_overdue", "交期已逾期的 PO", count, "个", sub=sub, tone="bad" if count else "", to=drill_to("proc.po_overdue", ctx) if count else None,
               hint="演示员工116交期早于今天、还没收齐的物料所在的 PO（只看演示员工116已生效的 PO）。没填演示员工116交期的物料不算逾期。")


@provider("proc.ready_to_pay", "kpi", visible=_pay_ok, title="可提交付款审批")
def _ready_to_pay(ctx):
    rows = [item for item in _payment_items(ctx) if item["work_status"] == "可提交付款审批"]
    amount = sum(item["amount"] for item in rows)
    return kpi("proc.ready_to_pay", "可提交付款审批", len(rows), "期", sub=_now_sub(ctx, f"合计 {_wan(amount)}" if rows else ""),
               tone="hot" if rows else "", to=target("procpay.work", status="可提交付款审批"),
               hint="采购付款期次里到货 / 验收 / 演示员工116条件都满足、还没提交付款审批的期次。")


@provider("proc.pay_planned_passed", "kpi", visible=_pay_ok, title="已过计划付款日")
def _pay_planned_passed(ctx):
    info = _planned_passed(ctx)
    sub = _now_sub(ctx, f"未付 {_wan(info['amount'])} · 最久 {info['oldest']} 天" if info["count"] else "")
    return kpi("proc.pay_planned_passed", "已过计划付款日", info["count"], "期", sub=sub, tone="bad" if info["count"] else "",
               to=drill_to("proc.pay_planned_passed", ctx) if info["count"] else None,
               hint="填了计划付款日、日期已过、还没付完（未付金额大于 0）的采购付款期次。没填计划付款日的不算。")


@provider("proc.month_amount", "kpi", visible=_money_ok, title="本月采购金额")
def _month_amount(ctx):
    data = _month_pos(ctx)
    cur, prev = sum(row["amount"] for row in data["cur"]), sum(row["amount"] for row in data["prev"])
    number, unit = money_wan(cur)
    if not data["cur"]:
        sub = "本月还没有下单"
    elif prev <= 0:
        sub = "上月没有采购"
    else:
        sub = f"较上月 {(cur - prev) / prev * 100:+.1f}%"
    return kpi("proc.month_amount", "本月采购金额", number, unit, sub=sub, to=drill_to("proc.month_amount", ctx) if data["cur"] else None,
               hint="本月创建的采购订单（PO）物料行金额合计，不含已取消，含还没生效的 PO；较上月按同样口径比。"
                    "和「费用」页的采购（PO 金额）同一口径；不同的是已经做了研发分摊的月份，费用页不重复计入研发项目的采购，这里照算。")


@provider("proc.suppliers_count", "kpi", visible=_po_ok, title="本月下单供应商")
def _suppliers_count(ctx):
    rows = _month_pos(ctx)["cur"]
    suppliers = {row["supplier"] for row in rows if row["supplier"]}
    return kpi("proc.suppliers_count", "本月下单供应商", len(suppliers), "家", sub=f"共 {len(rows)} 张 PO" if rows else "",
               to=drill_to("proc.suppliers", ctx) if rows and _money_ok(ctx) else None,
               hint="本月创建的采购订单（不含已取消）涉及的供应商家数；供应商是手填文本，前后空格去掉后同名算一家。")


# ================================================================ KPI：PMC / 物料
@provider("proc.await_pr", "kpi", visible=_chain_ok, title="待提 PR 的申请")
def _await_pr(ctx):
    rows = ctx.memo("proc.await_pr", _load_await_pr)
    requests = {row["request"] for row in rows}
    # 采购申请列表是在最近 200 张里按阶段筛，阶段规则也和这里不完全一样（列表按“现在走到哪一段”，这里按“还有没有物料没提 PR”），
    # 点进去对不上；所以点进去是同一份数据的明细清单（2026-10-13）。
    return kpi("proc.await_pr", "待提 PR 的申请", len(requests), "张", sub=_now_sub(ctx, f"共 {len(rows)} 项物料" if rows else ""),
               tone="hot" if rows else "", to=drill_to("proc.await_pr", ctx) if rows else None,
               hint="需求审批已通过、物料行数量还没全部提成 PR 的采购申请（已取消的 PR 数量退回来算；物料进度里已取消的物料不算）。点进去一张申请一行。")


@provider("proc.uncoded", "kpi", visible=_board_ok, title="未编码物料")
def _uncoded(ctx):
    rows = ctx.memo("proc.uncoded", _load_uncoded)
    return kpi("proc.uncoded", "未编码物料", len(rows), "项", sub=_now_sub(ctx, "要 PMC 绑定物料编码" if rows else ""),
               tone="hot" if rows else "", to=target("material.progress", uncoded="1"),
               hint="物料进度看板里物料编号为空的物料（状态演示员工152，源申请没被拒绝或撤回）。点进去物料进度页只看这些。")


@provider("proc.material_overdue", "kpi", visible=_board_ok, title="物料逾期未到")
def _material_overdue(ctx):
    materials = _overdue_materials(ctx)["materials"]
    count = len(materials)
    return kpi("proc.material_overdue", "物料逾期未到", count, "项", sub=_now_sub(ctx, f"最久逾期 {max(materials.values())} 天" if count else ""),
               tone="bad" if count else "", to=target("material.overdue"),
               hint="物料进度看板里演示员工116交期已过、还没收齐的物料（一行 = 采购申请的一行；只看演示员工116已生效的 PO；退货中的算没收齐；"
                    "没填演示员工116交期、已取消的物料不算）。和物料进度页「交期已过未收齐」同一口径。")


@provider("proc.risk_projects", "kpi", visible=_board_ok, title="缺料影响的项目")
def _risk_projects(ctx):
    count = len(_overdue_materials(ctx)["projects"])
    return kpi("proc.risk_projects", "缺料影响的项目", count, "个", sub=_now_sub(ctx, "有物料逾期未到" if count else ""),
               tone="bad" if count else "", to=drill_to("proc.risk_projects", ctx) if count else None,
               hint="有物料逾期未到的项目数（项目取物料进度看板上的项目，为空的不算）。点进去按项目列出来。")


# ================================================================ KPI：到货、验收（生产主管、PMC）
@provider("proc.week_arrive", "kpi", visible=_po_ok, title="本周预计到货")
def _week_arrive(ctx):
    rows = _lines(ctx)["week"]
    return kpi("proc.week_arrive", "本周预计到货", len(rows), "项", sub=_now_sub(ctx, f"来自 {_per_po(rows)} 个 PO" if rows else ""),
               to=drill_to("proc.week_arrive", ctx) if rows else None,
               hint="演示员工116交期落在本周（周一到周日）、还没收齐的物料；本周已经过了交期的也在里面（同时算进逾期）。")


@provider("proc.to_arrive", "kpi", visible=_po_ok, title="待到货")
def _to_arrive(ctx):
    rows = _lines(ctx)["to_arrive"]
    return kpi("proc.to_arrive", "待登记到货", len(rows), "项", sub=_now_sub(ctx, f"来自 {_per_po(rows)} 个 PO" if rows else ""),
               tone="hot" if rows else "", to=drill_to("proc.to_arrive", ctx) if rows else None,
               hint="演示员工116已生效的 PO 里，到货数量还不够的物料行（退货中的不算，单独在「退货中」）。部分到货的行会同时算在待验收里。")


@provider("proc.to_inspect", "kpi", visible=_po_ok, title="待验收")
def _to_inspect(ctx):
    rows = _lines(ctx)["to_inspect"]
    info = _inspect_info(ctx)
    waited = max(info["waited"].values(), default=None)
    return kpi("proc.to_inspect", "待验收", len(rows), "项", sub=_now_sub(ctx, f"最久到货 {waited} 天" if rows and waited is not None else ""),
               tone="bad" if info["stale"] else ("hot" if rows else ""), to=drill_to("proc.to_inspect", ctx) if rows else None,
               hint="已有到货、还没登记验收结果的物料行。天数从该 PO 最近一条到货登记起算。")


@provider("proc.exchange", "kpi", visible=_po_ok, title="换货中")
def _exchange(ctx):
    rows = _lines(ctx)["exchange"]
    return kpi("proc.exchange", "换货中", len(rows), "项", sub=_now_sub(ctx, "等供应商补发" if rows else ""), tone="warn" if rows else "",
               to=drill_to("proc.exchange", ctx) if rows else None, hint="验收结果为「换货中」的物料行（演示员工116已生效的 PO）。")


@provider("proc.return", "kpi", visible=_po_ok, title="退货中")
def _return(ctx):
    rows = _lines(ctx)["returning"]
    return kpi("proc.return", "退货中", len(rows), "项", sub=_now_sub(ctx, "等货退回供应商" if rows else ""), tone="warn" if rows else "",
               to=drill_to("proc.return", ctx) if rows else None, hint="验收结果为「退货中」的物料行（演示员工116已生效的 PO）。")


def _month_counts(ctx):
    def build():
        _, this_start, nxt = _month_bounds(ctx.period)
        return month_events(_load_month_records(this_start, nxt))
    return ctx.memo("proc.month_events", build)


@provider("proc.month_inspected", "kpi", visible=_po_ok, title="本月已验收")
def _month_inspected(ctx):
    count = _month_counts(ctx)[1]
    return kpi("proc.month_inspected", "本月已验收", count, "项", to=drill_to("proc.month_inspected", ctx) if count else None,
               hint="本月登记的验收记录里结果为「已通过」的物料行，同一 PO 的同一行只算一次。")


@provider("proc.month_arrived", "kpi", visible=_po_ok, title="本月已到货")
def _month_arrived(ctx):
    count = _month_counts(ctx)[0]
    return kpi("proc.month_arrived", "本月已到货", count, "项", to=drill_to("proc.month_arrived", ctx) if count else None,
               hint="本月登记的到货记录涉及的物料行（不含换货到货），同一 PO 的同一行只算一次。")


# ================================================================ 提醒
@provider("alert.po_overdue", "alert", visible=_po_ok, title="PO 交期逾期")
def _alert_po_overdue(ctx):
    pos = _overdue_info(ctx)["pos"]
    if not pos:
        return None
    worst = max(pos, key=lambda name: pos[name])
    return alert("alert.po_overdue", "bad" if pos[worst] > 7 else "warn", f"{len(pos)} 个 PO 已过演示员工116交期还没收齐",
                 sub=f"最久逾期 {pos[worst]} 天（{worst}）", go="逾期的 PO", to=drill_to("proc.po_overdue", ctx))


@provider("alert.pay_planned_passed", "alert", visible=_pay_ok, title="已过计划付款日")
def _alert_pay_planned_passed(ctx):
    info = _planned_passed(ctx)
    if not info["count"]:
        return None
    return alert("alert.pay_planned_passed", "bad", f"{info['count']} 期采购付款已过计划付款日",
                 sub=f"未付 {_wan(info['amount'])}，最久 {info['oldest']} 天，供应商可能催款", go="付款期次", to=drill_to("proc.pay_planned_passed", ctx))


@provider("alert.price_missing_quote", "alert", visible=_chain_ok, title="价格审批缺报价")
def _alert_price_missing_quote(ctx):
    unquoted = ctx.memo("proc.price_state", _load_price_state)["unquoted"]
    if not unquoted:
        return None
    lines = sum(unquoted.values())
    # 只有一张时直接打开那一张；几张时点进去是这几张的清单（价格审批页没有“缺报价”这个筛选）
    only = next(iter(unquoted)) if len(unquoted) == 1 else None
    to = target("price.approvals", view="approvals", approval=only) if only else drill_to("proc.price_missing_quote", ctx)
    return alert("alert.price_missing_quote", "warn", f"{len(unquoted)} 张待审批的价格审批单有物料没有报价",
                 sub=f"共 {lines} 项物料一个报价都没有，演示员工113没法选供应商", go="价格审批", to=to)


@provider("alert.uncoded", "alert", visible=_board_ok, title="物料未编码")
def _alert_uncoded(ctx):
    rows = ctx.memo("proc.uncoded", _load_uncoded)
    if not rows:
        return None
    return alert("alert.uncoded", "warn", f"{len(rows)} 项物料还没有物料编码", sub="要 PMC 绑定", go="物料进度",
                 to=target("material.progress", uncoded="1"))


@provider("alert.inspect_stale", "alert", visible=_po_ok, title="到货久未验收")
def _alert_inspect_stale(ctx):
    stale = _inspect_info(ctx)["stale"]
    if not stale:
        return None
    worst = max(stale, key=lambda name: stale[name])
    return alert("alert.inspect_stale", "bad", f"{len(stale)} 个 PO 到货超过 {STALE_INSPECT_DAYS} 天还没验收",
                 sub=f"{worst} 已到货 {stale[worst]} 天，可能耽误付款", go="待验收的 PO", to=drill_to("proc.inspect_stale", ctx))


@provider("alert.material_overdue", "alert", visible=_board_ok, title="物料逾期未到")
def _alert_material_overdue(ctx):
    materials = _overdue_materials(ctx)["materials"]
    if not materials:
        return None
    worst = max(materials.values())
    return alert("alert.material_overdue", "bad" if worst > 7 else "warn", f"{len(materials)} 项物料超过演示员工116交期还没到",
                 sub=f"最久逾期 {worst} 天", go="物料进度", to=target("material.overdue"))


@provider("alert.risk_projects", "alert", visible=_board_ok, title="缺料影响项目")
def _alert_risk_projects(ctx):
    ranked = _ranked_projects(ctx)
    if not ranked:
        return None
    sub = "；".join(f"{name} 有 {len(bucket['keys'])} 项物料逾期" for name, bucket in ranked[:2])
    return alert("alert.risk_projects", "warn", f"{len(ranked)} 个项目有物料逾期未到", sub=sub, go="缺料项目", to=drill_to("proc.risk_projects", ctx))


# ================================================================ 图表块
@provider("block.proc_chain", "block", visible=_po_ok, title="采购链路")
def _block_proc_chain(ctx):
    counts = ctx.memo("proc.chain", _load_chain_counts)
    values = [("OA 申请", counts["request"]), ("PR", counts["pr"]), ("PO", counts["po"]), ("付款期次", counts["payment"])]
    peak = max((value for _, value in values), default=0) or 1
    return bars("block.proc_chain", "采购链路", [bar_row(label, value, value / peak * 100) for label, value in values],
                sub="累计，个", more="按状态看", to=drill_to("proc.chain", ctx),
                hint="历史累计的存量，不按月份：OA 申请 = 已提交且没被拒绝 / 撤回的采购申请；PR、PO 不含已取消；付款期次 = 所有 PO 付款计划的期数。四个环节单位不同，只看各自的体量，不是转化率。点进去按状态拆开。")


@provider("block.arrival_inspect", "block", visible=_po_ok, title="到货与验收")
def _block_arrival_inspect(ctx):
    arrived, passed = _month_counts(ctx)
    data = _lines(ctx)
    rows = [("本月已到货", arrived, "ok"), ("本月已验收通过", passed, "ok"),
            ("待验收", len(data["to_inspect"]), "warn" if data["to_inspect"] else ""), ("待到货", len(data["to_arrive"]), "")]
    peak = max((value for _, value, _ in rows), default=0) or 1
    return bars("block.arrival_inspect", "到货与验收", [bar_row(label, value, value / peak * 100, tone) for label, value, tone in rows],
                sub="物料行 · 前两项是本月登记，后两项是当前存量", more="逐条看" if any(value for _, value, _ in rows) else "",
                to=drill_to("proc.arrival_inspect", ctx) if any(value for _, value, _ in rows) else None,
                hint="已到货 / 已验收通过按本月的到货、验收登记数物料行；待验收、待到货是现在还没办完的存量（演示员工116已生效的 PO）。")


@provider("block.proc_suppliers", "block", visible=_money_ok, title="本月采购金额 · 供应商")
def _block_proc_suppliers(ctx):
    totals = {}
    for row in _month_pos(ctx)["cur"]:
        totals[row["supplier"]] = totals.get(row["supplier"], 0.0) + row["amount"]
    return bars("block.proc_suppliers", "本月采购金额 · 供应商", _top_rows(totals, "未填供应商"), sub="前 5 家",
                more="全部供应商" if totals else "", to=drill_to("proc.suppliers", ctx) if totals else None,
                hint="本月创建的 PO（不含已取消）按供应商合计物料行金额；供应商是手填文本，去掉前后空格后同名合并。")


@provider("block.proc_projects", "block", visible=_money_ok, title="本月采购金额 · 项目")
def _block_proc_projects(ctx):
    totals = _project_totals(ctx)
    return bars("block.proc_projects", "本月采购金额 · 项目", _top_rows(totals, "非项目"), sub="前 5 个项目",
                more="全部项目" if totals else "", to=drill_to("proc.projects", ctx) if totals else None,
                hint="本月创建的 PO（不含已取消）按物料行所属项目合计行金额；没填项目的归「非项目」。合计等于「本月采购金额」。")


# 阶段名和物料进度页上方的阶段条一模一样（同一句 stage_sql），点进去能对上（2026-10-13：原来合并成自己起的名字，页面上找不到）。
MATERIAL_STAGE_ROWS = (("OA审批中", ""), ("采购确认中", ""), ("PO处理中", ""), ("供应商制作中", ""), ("到货验收中", ""), ("付款中", ""),
                       ("已关闭", "ok"))


@provider("block.material_stage", "block", visible=_board_ok, title="物料进度")
def _block_material_stage(ctx):
    counts = dict.fromkeys((label for label, _ in MATERIAL_STAGE_ROWS), 0)
    no_pr = 0
    for row in ctx.memo("proc.stages", _load_stage_counts):
        stage, total = row["stage"], int(row["total"] or 0)
        if stage in counts:
            counts[stage] += total
        if stage == "采购确认中" and row.get("no_pr"):
            no_pr += total
    peak = max(counts.values(), default=0) or 1
    return bars("block.material_stage", "物料进度", [bar_row(label, counts[label], counts[label] / peak * 100, tone) for label, tone in MATERIAL_STAGE_ROWS],
                sub=f"按阶段 · 物料行（采购确认中有 {no_pr} 项还没提 PR）" if no_pr else "按阶段 · 物料行", to=target("material.progress"),
                hint="阶段和物料进度看板上方的阶段条同一口径、同样的名字：采购确认中 = 还没进价格审批（含还没提 PR 的）；PO处理中 = 价格审批或 PO 草稿；"
                     "供应商制作中 = PO 已生效；到货验收中、付款中；已关闭 = 关联 PO 都已关闭。被拒绝 / 撤回 / 取消的物料不在这里（页面上在「其他状态」）。")


@provider("block.risk_projects", "block", visible=_board_ok, title="缺料影响的项目")
def _block_risk_projects(ctx):
    ranked_all = _ranked_projects(ctx)
    ranked = ranked_all[:6]
    rows = []
    for name, bucket in ranked:
        items = bucket["items"]
        sub = "、".join(items[:2]) + (" 等" if len(items) > 2 else "")
        rows.append(list_row(name, sub=sub, value=f"{len(bucket['keys'])} 项", tone="bad" if max(bucket["keys"].values()) > 7 else "warn",
                             to=target("material.overdue", project=name)))
    return listing("block.risk_projects", "缺料影响的项目", rows, sub="逾期未到的物料", to=drill_to("proc.risk_projects", ctx) if ranked_all else None,
                   more=f"还有 {len(ranked_all) - len(ranked)} 个项目" if len(ranked_all) > len(ranked) else "",
                   hint="按项目汇总演示员工116交期已过、还没收齐的物料（物料进度看板的行，项目取看板上的项目）；红色 = 最久逾期超过 7 天；项目为空的不列。"
                        "点一行到物料进度页只看这个项目的逾期物料。")


@provider("block.week_schedule", "block", visible=_po_ok, title="本周预计到货")
def _block_week_schedule(ctx):
    by_day = {}
    for row in _lines(ctx)["week"]:
        by_day.setdefault(_iso(row["due"]), []).append(row)
    rows = []
    for day in sorted(by_day):
        items = by_day[day]
        pos = sorted({row["po"] for row in items})
        sub = f"{len(pos)} 个 PO：" + "、".join(pos[:3]) + (" 等" if len(pos) > 3 else "")
        weekday = date.fromisoformat(day).weekday()
        tone = "bad" if day < ctx.today else ("warn" if day == ctx.today else "")
        rows.append(list_row(f"{day[5:]} 周{WEEKDAYS[weekday]}", sub=sub, value=f"{len(items)} 项", tone=tone))
    return listing("block.week_schedule", "本周预计到货", rows, sub="按演示员工116交期 · 物料行" if rows else "本周没有预计到货的物料",
                   to=drill_to("proc.week_arrive", ctx) if rows else None,
                   hint="演示员工116交期落在本周（周一到周日）、还没收齐的物料，按日期排；红色 = 交期已过还没到，黄色 = 今天。")


# ================================================================ 图表块：日程、账龄、趋势（2026-10-12 按岗位看板方案补）
def _pct(part, peak):
    return part / peak * 100 if peak else 0


@provider("block.week_cols", "block", visible=_po_ok, title="本周到货日程")
def _block_week_cols(ctx):
    """本周每天预计到货的物料数（柱），比文字列表更容易看出哪天货多；今天标橙。"""
    today = _today(ctx)
    monday = today - timedelta(days=today.weekday())
    counts = {(monday + timedelta(days=offset)).isoformat(): 0 for offset in range(7)}
    for row in _lines(ctx)["week"]:
        day = _iso(row["due"])
        if day in counts:
            counts[day] += 1
    if not any(counts.values()):
        return None
    peak = max(counts.values()) or 1
    rows = [col_row(f"周{WEEKDAYS[offset]}", counts[day], _pct(counts[day], peak), day == today.isoformat())
            for offset, day in enumerate(sorted(counts))]
    return cols("block.week_cols", "本周到货日程", rows, sub="预计到货的物料行 · 按演示员工116交期", more="本周明细", to=drill_to("proc.week_arrive", ctx),
                hint="演示员工116交期落在本周（周一到周日）、还没收齐的物料，按天数；今天标橙；已过交期的也在里面（同时算进逾期）。")


def _age_groups(days_list, edges):
    """按天数分档：edges [(标签, 上限天数含)] 最后一档无上限。"""
    groups = []
    low = None
    for label, high in edges:
        groups.append((label, sum(1 for days in days_list if (low is None or days > low) and (high is None or days <= high))))
        low = high
    return groups


@provider("block.inspect_aging", "block", visible=_po_ok, title="待验收等了多久")
def _block_inspect_aging(ctx):
    waited = list(_inspect_info(ctx)["waited"].values())
    if not waited:
        return None
    groups = _age_groups(waited, [("1 天内", 1), ("2–3 天", 3), ("4–7 天", STALE_INSPECT_DAYS), (f"超过 {STALE_INSPECT_DAYS} 天", None)])
    peak = max(count for _label, count in groups) or 1
    rows = [bar_row(label, count, _pct(count, peak), "bad" if label.startswith("超过") and count else "") for label, count in groups]
    return bars("block.inspect_aging", "待验收等了多久", rows, sub="PO 个数 · 从最近一次到货登记起算", more="待验收的 PO", to=drill_to("proc.inspect_wait", ctx),
                hint=f"已有到货、还没验收的 PO，按最近一次到货登记到今天的天数分档；超过 {STALE_INSPECT_DAYS} 天算久拖。")


@provider("block.overdue_aging", "block", visible=_board_ok, title="逾期了多久")
def _block_overdue_aging(ctx):
    late = list(_overdue_materials(ctx)["materials"].values())
    if not late:
        return None
    groups = _age_groups(late, [("1–3 天", 3), ("4–7 天", 7), ("超过 7 天", None)])
    peak = max(count for _label, count in groups) or 1
    rows = [bar_row(label, count, _pct(count, peak), "bad" if label.startswith("超过") and count else "") for label, count in groups]
    return bars("block.overdue_aging", "逾期了多久", rows, sub="物料（物料进度看板的行）", to=target("material.overdue"),
                hint="演示员工116交期已过、还没收齐的物料，按逾期天数分档（从最早的逾期演示员工116交期次日起算）；加起来 = 物料进度页「交期已过未收齐」的条数。")


def _trend(ctx):
    """近 6 个月（到所选月份为止）：(月份列表, {月份: 行金额合计}, {月份: PO 数})。"""
    def build():
        year, month = int(ctx.period[:4]), int(ctx.period[5:7])
        start = date(year, month, 1)
        for _ in range(5):
            start = (start - timedelta(days=1)).replace(day=1)
        nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        heads = _load_month_pos(start.isoformat(), nxt.isoformat())
        return _with_line_amounts(heads, _load_po_line_amounts({row["po"] for row in heads}))
    totals, counts = {}, {}
    for row in ctx.memo("proc.trend_pos", build):
        totals[row["month"]] = totals.get(row["month"], 0.0) + row["amount"]
        counts[row["month"]] = counts.get(row["month"], 0) + 1
    year, month = int(ctx.period[:4]), int(ctx.period[5:7])
    months = []
    for _ in range(6):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    months.reverse()
    return months, totals, counts


@provider("block.proc_month_trend", "block", visible=_money_ok, title="近 6 个月采购金额")
def _block_proc_month_trend(ctx):
    months, totals, counts = _trend(ctx)
    if not counts:
        return None
    peak = max(totals.get(key, 0.0) for key in months) or 1
    # 金额写法和「本月采购金额」卡片一样（不到 1 万按元，其余按万），同一个月两处看到的是同一个数
    rows = [col_row(f"{int(key[5:])}月", _wan(totals.get(key, 0.0)), _pct(totals.get(key, 0.0), peak), key == ctx.period) for key in months]
    return cols("block.proc_month_trend", "近 6 个月采购金额", rows, sub="按 PO 创建月份 · 物料行金额", more="逐月看", to=drill_to("proc.month_trend", ctx),
                hint="每月创建的 PO（不含已取消）物料行金额合计，和「本月采购金额」同一口径；供应商、项目分布看右边两块。")


PAY_WEEK_LABELS = ["已过计划日", "本周", "下周", "第 3 周", "第 4 周", "更晚", "没排期"]


def _pay_week(today, planned):
    """计划付款日落在哪一档。周 = 周一到周日（和「本周预计到货」一样）：本周 = 今天到本周日。"""
    day = date.fromisoformat(planned)
    if day < today:
        return "已过计划日"
    weeks = (day - (today - timedelta(days=today.weekday()))).days // 7
    return PAY_WEEK_LABELS[1 + weeks] if weeks < 4 else "更晚"


@provider("block.pay_next30", "block", visible=_pay_ok, title="未来 30 天要付多少")
def _block_pay_next30(ctx):
    """按计划付款日，采购付款期次里还没付清的金额：已过计划日、本周、下周、第 3 周、第 4 周、更晚、没排期。
    和「未来 30 天要付多少」明细同一份行（_pay_plan_rows），加起来等于明细的合计。"""
    today = _today(ctx)
    totals = dict.fromkeys(PAY_WEEK_LABELS, 0.0)
    for item in _pay_plan_rows(ctx, False):
        totals["没排期" if not item["planned"] else _pay_week(today, item["planned"])] += item["owed"]
    if not any(totals.values()):
        return None
    peak = max(totals.values()) or 1
    rows = [col_row(label, _wan(totals[label]), _pct(totals[label], peak), label == "已过计划日" and totals[label] > 0) for label in PAY_WEEK_LABELS]
    return cols("block.pay_next30", "未来 30 天要付多少", rows, sub="采购付款，按计划付款日 · 周一到周日算一周", more="付款期次", to=drill_to("proc.pay_plan", ctx),
                hint="采购付款期次里还没付清的金额（演示员工116金额 − 已付），按计划付款日分档：本周 = 今天到本周日，下周、第 3 周、第 4 周都是周一到周日"
                     "（和「本周预计到货」同一个“周”）；已过计划日的标橙；没填计划日的单独一栏。报销单、付款单没有计划日，不在这里。")
