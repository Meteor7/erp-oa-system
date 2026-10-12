"""看板块：采购、PMC、生产主管。

数据来源和口径（每个块的 hint 里也写了）：
- PO 物料行（OA Purchase Order Line）：待到货 / 待验收 / 换货 / 退货 / 合同交期逾期 / 本周预计到货。只看合同已生效的 PO
  （已生效、供应商制作中、到货验收中、付款中）——草稿 PO 的"交期"还是报价上的，不算合同交期。
- 到货 / 验收登记（OA PO Fulfillment Record）：本月已到货、本月已验收、到货后多久没验收。
- 付款期次：直接调 `procurement_chain.list_payment_work_items`（可提交付款审批、已过计划付款日）。
- 物料进度（OA Material Progress）：阶段分布、未编码、缺料影响的项目；阶段 SQL 复用 `material_progress_query.stage_sql`。
- 价格审批 / PR / 采购申请：待比价、价格审批中、待提 PR。

权限：每个块的 `visible` 对应它背后现有接口的真实权限，规则抄自 `procurement_chain._require_view / _require_po_view`、
`material_progress.can_access_board`（测试里有一条对照测试，规则变了会提醒），再加功能开关。
PMC 因为有 Purchase User 角色，会被现有判断当成"能看采购金额"——这里明确挡掉：看板上 PMC 不出现任何金额。
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import frappe

from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, col_row, cols, drill, drill_row, drill_to, kpi, list_row, listing, money_wan, provider, target,
)

# 合同已生效、货还在路上或还没结清的 PO 状态（草稿 / 待确认 / 待合同复核 / 待电子用印的合同还没生效；已关闭 / 已取消不看）
EFFECTIVE_PO = ("已生效", "供应商制作中", "到货验收中", "付款中")
STALE_INSPECT_DAYS = 7          # 到货后超过 7 天（不含）还没验收
PRICE_VIEW_ROLES = {"Purchase User", "Purchase Manager", "Rayher Business Executive"}
PO_VIEW_ROLES = {"Accounts User", "Finance User"} | PRICE_VIEW_ROLES
# 持有这些岗位的人本来就合法看采购 / 付款金额；只持有 pmc / 生产主管岗位的人不给金额
MONEY_POSITIONS = ("procurement_manager", "vice_manager", "general_manager",
                   "finance_manager", "finance_accountant", "finance_auditor")
WEEKDAYS = "一二三四五六日"


# ---------------------------------------------------------------- 权限
def _gate_open(ctx, kind):
    """功能开关：采购链路接口跟随"采购申请"开关，付款接口跟随"采购付款"开关（procurement_chain._require_gate）。"""
    from rayher_hr_payroll.oa_document_types import REQUEST_PROCUREMENT, REQUEST_PROCUREMENT_PAYMENT
    from rayher_hr_payroll.oa_feature_gate import can_access_request_type

    request_type = REQUEST_PROCUREMENT_PAYMENT if kind == "payment" else REQUEST_PROCUREMENT
    return bool(can_access_request_type(request_type, ctx.user))


def _has_chain_view(ctx):
    """= procurement_chain._require_view：PMC、采购经理、副总、采购角色、系统管理员（价格审批 / PR 的查看权）。"""
    return ctx.holds("pmc", "procurement_manager", "vice_manager") or ctx.can("System Manager", *PRICE_VIEW_ROLES)


def _has_po_view(ctx):
    """= procurement_chain._require_po_view：在 _require_view 的基础上加生产主管和财务（PO / 付款期次的查看权）。"""
    return (ctx.holds("pmc", "procurement_manager", "vice_manager", "production_asset_owner")
            or ctx.can("System Manager", *PO_VIEW_ROLES))


def _has_board(ctx):
    """= material_progress.can_access_board：PMC、采购经理、副总、总经理、系统管理员。"""
    return (ctx.user.strip().lower() == "administrator" or ctx.can("System Manager")
            or ctx.holds("pmc", "procurement_manager", "vice_manager", "general_manager"))


def _money_blocked(ctx):
    """PMC / 生产主管不给金额：持有 pmc 或生产主管岗位、又没有任何一个本来就看金额的岗位（采购经理、副总、总经理、财务）。
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
    """合同已生效的 PO 的物料行。"""
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
    """PR 里还没进价格审批的物料行（剩余可选数量 > 0，PR 没取消）——价格审批页"PR 待比价物料"就是这些。"""
    lines = frappe.get_all("OA Procurement Request Line", filters={"remaining_quantity": [">", 0]},
                           fields=["name", "parent", "remaining_quantity"], limit_page_length=0)
    if not lines:
        return []
    live = set(frappe.get_all("OA Procurement Request",
                              filters={"name": ["in", sorted({row.get("parent") for row in lines})], "status": ["!=", "已取消"]},
                              pluck="name", limit_page_length=0))
    return [{"pr": row.get("parent"), "line": row.get("name")} for row in lines if row.get("parent") in live]


def _load_price_state():
    """{"pending": 待审批张数, "draft": 草稿张数, "unquoted": {待审批单号: 一个报价都没有的物料行数}}。"""
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
    return {"pending": len(pending), "draft": len(approvals) - len(pending), "unquoted": unquoted}


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
    """物料进度里还没编码的物料行：状态正常、源单没被拒绝 / 撤回、物料编号为空。"""
    rows = frappe.get_all("OA Material Progress", filters={"status": "正常"},
                          fields=["name", "source_request", "material_code"], limit_page_length=0)
    blank = [row for row in rows if not (row.get("material_code") or "").strip()]
    if not blank:
        return []
    dead = set(frappe.get_all(
        "OA Approval Request",
        filters={"name": ["in", sorted({row.get("source_request") for row in blank})], "workflow_status": ["in", ["已拒绝", "已撤回"]]},
        pluck="name", limit_page_length=0))
    return [{"name": row.get("name"), "request": row.get("source_request")} for row in blank
            if row.get("source_request") not in dead]


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


# ---------------------------------------------------------------- 加工（纯函数，测试直接喂数据）
def _received(row):
    """这一行算不算已到齐：数量够了，而且没有被判退货（同 procurement_chain._line_received）。"""
    return _n(row["received"]) >= _n(row["quantity"]) and row["inspection"] != "退货中"


def _material_key(row):
    """一个物料 = 采购申请的一行（物料进度看板的一行）；没有来源的 PO 行按 PO 行自己算。"""
    if row["source_request"] and row["source_line"]:
        return (row["source_request"], row["source_line"])
    return ("po-line", row["line"])


def classify(rows, today):
    """把合同已生效的 PO 物料行分到各个口径里（同一行可以同时算"待到货"和"待验收"：部分到货）。"""
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
    """逾期的 PO 物料行：逾期的 PO、物料（按 (申请, 行) 去重）、按项目汇总。"""
    def build():
        rows = _lines(ctx)["overdue"]
        pos, materials, projects = {}, {}, {}
        for row in rows:
            late = _days_since(ctx, _iso(row["due"]))
            pos[row["po"]] = max(pos.get(row["po"], 0), late)
            key = _material_key(row)
            materials[key] = max(materials.get(key, 0), late)
            if row["project"]:
                bucket = projects.setdefault(row["project"], {"keys": {}, "items": []})
                bucket["keys"][key] = max(bucket["keys"].get(key, 0), late)
                if row["item"] and row["item"] not in bucket["items"]:
                    bucket["items"].append(row["item"])
        return {"pos": pos, "materials": materials, "projects": projects, "rows": len(rows)}
    return ctx.memo("proc.overdue", build)


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
    def build():
        today = ctx.today
        rows = [item for item in _payment_items(ctx)
                if item["planned"] and item["planned"] < today and item["work_status"] != "已付款"]
        return {"count": len(rows), "amount": sum(max(item["amount"] - item["paid"], 0) for item in rows),
                "oldest": max((_days_since(ctx, item["planned"]) for item in rows), default=0)}
    return ctx.memo("proc.planned_passed", build)


def _month_pos(ctx):
    """本月 / 上月的 PO 表头。"""
    def build():
        prev_start, this_start, nxt = _month_bounds(ctx.period)
        rows = _load_month_pos(prev_start, nxt)
        return {"cur": [row for row in rows if row["month"] == ctx.period], "prev": [row for row in rows if row["month"] != ctx.period]}
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
    """按 PO 一行：PO | 供应商 | 状态 | 物料 | 最近合同交期。"""
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
    return drill(key, title, [("PO",), ("供应商",), ("状态",), ("物料", "r"), ("最近合同交期", "r"), ("已逾期", "r")], out,
                 summary=f"共 {len(grouped)} 个 PO，{len(rows)} 项物料", note=note)


def _line_drill(ctx, key, title, rows, columns, cells, note="", tone_of=None, summary=None):
    out = [drill_row(cells(row), _po_open(ctx, row["po"]), tone=(tone_of(row) if tone_of else "")) for row in rows]
    return drill(key, title, columns, out, summary=summary or f"共 {len(rows)} 项物料，来自 {_per_po(rows)} 个 PO", note=note)


@provider("drill.proc.po_transit", "drill", visible=_po_ok, title="PO 在途")
def drill_po_transit(ctx):
    return _po_list_drill(ctx, "drill.proc.po_transit", "在途的 PO", _lines(ctx)["transit"],
                          note="合同已生效、还有物料没收齐的 PO；“物料”是还没收齐的项数。")


@provider("drill.proc.po_overdue", "drill", visible=_po_ok, title="交期已逾期的 PO")
def drill_po_overdue(ctx):
    return _po_list_drill(ctx, "drill.proc.po_overdue", "交期已逾期的 PO", _lines(ctx)["overdue"],
                          note="合同交期早于今天、还没收齐的物料所在的 PO；红色 = 逾期超过 7 天。", tone_of=lambda late: "bad" if late > 7 else "warn")


@provider("drill.proc.week_arrive", "drill", visible=_po_ok, title="本周预计到货")
def drill_week_arrive(ctx):
    today = ctx.today

    def cells(row):
        due = _iso(row["due"])
        weekday = date.fromisoformat(due).weekday()
        return [f"{due[5:]} 周{WEEKDAYS[weekday]}", row["po"], row["item"] or "—", _qty(row), row["project"] or "—"]
    return _line_drill(ctx, "drill.proc.week_arrive", "本周预计到货的物料", _sorted_days(_lines(ctx)["week"]),
                       [("合同交期",), ("PO",), ("物料",), ("已到 / 订购", "r"), ("项目",)], cells,
                       tone_of=lambda row: "bad" if _iso(row["due"]) < today else ("warn" if _iso(row["due"]) == today else ""),
                       note="合同交期落在本周（周一到周日）、还没收齐的物料；红色 = 交期已过还没到，黄色 = 今天。")


@provider("drill.proc.to_arrive", "drill", visible=_po_ok, title="待登记到货")
def drill_to_arrive(ctx):
    return _line_drill(ctx, "drill.proc.to_arrive", "待登记到货的物料", _sorted_days(_lines(ctx)["to_arrive"]),
                       [("PO",), ("物料",), ("已到 / 订购", "r"), ("合同交期", "r"), ("项目",)],
                       lambda row: [row["po"], row["item"] or "—", _qty(row), _iso(row["due"]) or "未填", row["project"] or "—"],
                       note="合同已生效的 PO 里，到货数量还不够的物料行（退货中的不算）。")


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
    rows = sorted(_month_pos(ctx)["cur"], key=lambda row: -row["amount"])
    out = [drill_row([row["po"], row["supplier"] or "—", row.get("status") or "—", row.get("day") or "—", _wan_full(row["amount"])], _po_open(ctx, row["po"]))
           for row in rows]
    return drill("drill.proc.month_amount", f"{int(ctx.period[5:])} 月新下的 PO", [("PO",), ("供应商",), ("状态",), ("下单日",), ("金额", "r")], out,
                 summary=f"共 {len(rows)} 个 PO，合计 {_wan(sum(row['amount'] for row in rows))}",
                 note="本月创建的采购订单（PO）金额合计，不含已取消，含还没生效的 PO。")


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
                 note="本月创建的采购订单（不含已取消）涉及的供应商；供应商是手填文本，去掉前后空格后同名算一家；没填供应商的单独一行，不算家数。")


@provider("drill.proc.projects", "drill", visible=_money_ok, title="本月采购金额 · 项目")
def drill_projects(ctx):
    names = {row["po"] for row in _month_pos(ctx)["cur"]}
    totals = {}
    for row in ctx.memo("proc.month_lines", lambda: _load_po_line_amounts(names)):
        totals[row["project"] or "非项目"] = totals.get(row["project"] or "非项目", 0.0) + row["amount"]
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    out = [drill_row([name, _wan_full(amount)]) for name, amount in ranked]
    return drill("drill.proc.projects", f"{int(ctx.period[5:])} 月采购金额 · 按项目", [("项目",), ("行金额", "r")], out,
                 summary=f"共 {len(ranked)} 个项目，合计 {_wan(sum(totals.values()))}",
                 note="本月创建的 PO（不含已取消）按物料行所属项目合计行金额；没填项目的归「非项目」。行金额合计可能和 PO 总额有尾差。")


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


@provider("drill.proc.risk_projects", "drill", visible=_board_ok, title="缺料影响的项目")
def drill_risk_projects(ctx):
    projects = _overdue_info(ctx)["projects"]
    ranked = sorted(projects.items(), key=lambda item: (-len(item[1]["keys"]), item[0]))
    out = []
    for name, bucket in ranked:
        items = bucket["items"]
        worst = max(bucket["keys"].values())
        out.append(drill_row([name, f"{len(bucket['keys'])} 项", f"{worst} 天", "、".join(items[:3]) + (" 等" if len(items) > 3 else "")],
                             target("material.overdue"), tone="bad" if worst > 7 else "warn"))
    return drill("drill.proc.risk_projects", "缺料影响的项目", [("项目",), ("逾期物料", "r"), ("最久逾期", "r"), ("物料",)], out,
                 summary=f"共 {len(ranked)} 个项目", note="有物料超过合同交期还没到的项目；红色 = 最久逾期超过 7 天；物料所属项目为空的不列。")


# ================================================================ 加急采购（老板、采购、PMC 关心的：催得最紧的那几张）
URGENT_TYPES = ("采购申请", "购买申请")
URGENT_SKIP_STATUS = ("草稿", "已拒绝", "已撤回", "已取消")
URGENT_DONE_BUSINESS = ("已付款", "已关闭")
URGENT_STUCK_DAYS = 3


def _urgent_ok(ctx):
    """加急采购清单：采购链路的人、副总、总经理（管理层角色）。申请单本身的可见范围同其他看板（管理层看全公司）。"""
    return (ctx.holds("general_manager", "vice_manager", "procurement_manager", "pmc")
            or ctx.can("System Manager", "Rayher Business Executive")) and _gate_open(ctx, "chain")


def _load_urgent():
    """加急（urgency = 加急）的采购申请、购买申请里还没办完的：
    [{name, type, subject, applicant, project, expected, approving, label, since}]。
    采购申请审批通过后的“现在在哪”取采购链路的阶段（等 PMC 提 PR / 询价 / 价格审批 / PO 执行）；购买申请取当前审批节点或付款状态。"""
    from rayher_hr_payroll.api import oa_entry

    rows = frappe.get_all(
        "OA Approval Request",
        filters={"request_type": ["in", list(URGENT_TYPES)], "urgency": "加急", "workflow_status": ["not in", list(URGENT_SKIP_STATUS)]},
        fields=["name", "request_type", "subject", "employee_name", "project", "workflow_status", "business_status",
                "current_step_label", "expected_delivery_date", "creation"], limit_page_length=0)
    acted = {}
    if rows:
        for step in frappe.get_all("OA Approval Step", filters={"parent": ["in", [row["name"] for row in rows]], "parenttype": "OA Approval Request"},
                                   fields=["parent", "acted_on"], limit_page_length=0):
            day = _iso(step.get("acted_on"))
            if day and day > acted.get(step["parent"], ""):
                acted[step["parent"]] = day
    out = []
    for row in rows:
        business = (row.get("business_status") or "").strip()
        if business in URGENT_DONE_BUSINESS:
            continue
        approving = row.get("workflow_status") in ("待审批", "待办理")
        label = (row.get("current_step_label") or "").strip() or "审批中"
        if not approving and row["request_type"] == "采购申请":
            chain = oa_entry._calculate_procurement_chain(frappe.get_doc("OA Approval Request", row["name"]))
            if chain.get("stage") == "closed":
                continue
            label = chain.get("label") or label
        elif not approving:
            label = business or "待付款"
        out.append({"name": row["name"], "type": row["request_type"], "subject": (row.get("subject") or "").strip(),
                    "applicant": row.get("employee_name") or "", "project": (row.get("project") or "").strip(),
                    "expected": _iso(row.get("expected_delivery_date")), "approving": approving, "label": label,
                    "since": acted.get(row["name"]) or _iso(row.get("creation"))})
    return out


def _urgent(ctx):
    return ctx.memo("proc.urgent", lambda: sorted(_load_urgent(), key=lambda item: item["since"] or "9999"))


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
    return kpi("proc.urgent", "加急采购在途", len(items), "张", " · ".join(parts) if parts else ("都在正常推进" if items else ""),
               tone="bad" if stuck or late else ("hot" if items else ""), to=drill_to("proc.urgent", ctx) if items else None,
               hint="申请单上勾了「加急」的采购申请、购买申请，还没办完的（购买申请 = 还没付完款，采购申请 = 采购链路还没关闭）。"
                    f"“没动静”= 距离最近一次审批已经超过 {URGENT_STUCK_DAYS} 天。点进去看每一张现在在谁手上。")


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
    return drill("drill.proc.urgent", "加急采购在途", [("单号",), ("类型",), ("事由",), ("申请人",), ("项目",), ("现在在",), ("距上次审批", "r"), ("期望到货", "r")], out,
                 summary=f"共 {len(items)} 张", note=f"红色 = 超过 {URGENT_STUCK_DAYS} 天没动静，或者已经过了期望到货日。")


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
    return listing("block.urgent_requests", "加急采购", rows, sub="谁手上、距上次审批多久" if rows else "没有在途的加急采购",
                   more=f"全部 {len(items)} 张" if len(items) > len(ranked) else "", to=drill_to("proc.urgent", ctx) if items else None,
                   hint="加急的采购申请、购买申请里还没办完的，等得最久的在前；红色 = 超过 3 天没动静或已过期望到货日。点一行进申请详情。")


# ================================================================ KPI：采购
@provider("proc.to_compare", "kpi", visible=_chain_ok, title="待比价物料")
def _to_compare(ctx):
    rows = ctx.memo("proc.pr_lines", _load_pr_lines)
    return kpi("proc.to_compare", "待比价物料", len(rows), "项", sub=f"来自 {len({row['pr'] for row in rows})} 张 PR" if rows else "",
               tone="hot" if rows else "", to=target("price.approvals", view="source"),
               hint="PR 里还没进价格审批的物料行（剩余可选数量大于 0，PR 没取消）。撤回或取消价格审批后，数量会回到这里。")


@provider("proc.price_pending", "kpi", visible=_chain_ok, title="价格审批中")
def _price_pending(ctx):
    state = ctx.memo("proc.price_state", _load_price_state)
    return kpi("proc.price_pending", "价格审批中", state["pending"], "张", sub=f"另有 {state['draft']} 张还在比价（草稿）" if state["draft"] else "",
               to=target("price.approvals", view="approvals"),
               hint="已提交、等副总经理终审的价格审批单。草稿是采购还在比价，没算进来。")


@provider("proc.po_transit", "kpi", visible=_po_ok, title="PO 在途")
def _po_transit(ctx):
    data = _lines(ctx)
    pos = {row["po"] for row in data["transit"]}
    sub = f"待到货 {len(data['to_arrive'])} 项 · 待验收 {len(data['to_inspect'])} 项" if pos else ""
    return kpi("proc.po_transit", "PO 在途", len(pos), "个", sub=sub, to=drill_to("proc.po_transit", ctx) if pos else None,
               hint="在途 = 合同已生效（已生效 / 供应商制作中 / 到货验收中 / 付款中）、还有物料没收齐的 PO。已关闭、已取消和合同还没生效的草稿 PO 不算。")


@provider("proc.po_overdue", "kpi", visible=_po_ok, title="交期已逾期的 PO")
def _po_overdue(ctx):
    info = _overdue_info(ctx)
    count = len(info["pos"])
    sub = f"最久逾期 {max(info['pos'].values())} 天 · 共 {info['rows']} 项物料" if count else ""
    return kpi("proc.po_overdue", "交期已逾期的 PO", count, "个", sub=sub, tone="bad" if count else "", to=drill_to("proc.po_overdue", ctx) if count else None,
               hint="合同交期早于今天、还没收齐的物料所在的 PO（只看合同已生效的 PO）。没填合同交期的物料不算逾期。")


@provider("proc.ready_to_pay", "kpi", visible=_pay_ok, title="可提交付款审批")
def _ready_to_pay(ctx):
    rows = [item for item in _payment_items(ctx) if item["work_status"] == "可提交付款审批"]
    amount = sum(item["amount"] for item in rows)
    return kpi("proc.ready_to_pay", "可提交付款审批", len(rows), "期", sub=f"合计 {_wan(amount)}" if rows else "",
               tone="hot" if rows else "", to=target("procpay.work", status="可提交付款审批"),
               hint="采购付款期次里到货 / 验收 / 合同条件都满足、还没提交付款审批的期次。")


@provider("proc.pay_planned_passed", "kpi", visible=_pay_ok, title="已过计划付款日")
def _pay_planned_passed(ctx):
    info = _planned_passed(ctx)
    sub = f"未付 {_wan(info['amount'])} · 最久 {info['oldest']} 天" if info["count"] else ""
    return kpi("proc.pay_planned_passed", "已过计划付款日", info["count"], "期", sub=sub, tone="bad" if info["count"] else "",
               to=drill_to("proc.pay_planned_passed", ctx) if info["count"] else None,
               hint="填了计划付款日、日期已过、还没付完的采购付款期次。没填计划付款日的不算。")


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
               hint="本月创建的采购订单（PO）金额合计，不含已取消，含还没生效的 PO；较上月按同样口径比。")


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
    return kpi("proc.await_pr", "待提 PR 的申请", len(requests), "张", sub=f"共 {len(rows)} 项物料" if rows else "",
               tone="hot" if rows else "", to=target("procurement.list", scope="all", stage="await_pr"),
               hint="需求审批已通过、物料行数量还没全部提成 PR 的采购申请（已取消的物料不算）。")


@provider("proc.uncoded", "kpi", visible=_board_ok, title="未编码物料")
def _uncoded(ctx):
    rows = ctx.memo("proc.uncoded", _load_uncoded)
    return kpi("proc.uncoded", "未编码物料", len(rows), "项", sub="要 PMC 绑定物料编码" if rows else "",
               tone="hot" if rows else "", to=target("material.progress"),
               hint="物料进度看板里物料编号为空的物料（状态正常，源申请没被拒绝或撤回）。")


@provider("proc.material_overdue", "kpi", visible=_board_ok, title="物料逾期未到")
def _material_overdue(ctx):
    info = _overdue_info(ctx)
    count = len(info["materials"])
    return kpi("proc.material_overdue", "物料逾期未到", count, "项", sub=f"最久逾期 {max(info['materials'].values())} 天" if count else "",
               tone="bad" if count else "", to=target("material.overdue"),
               hint="合同交期早于今天、还没收齐的物料（按采购申请的物料行去重；只看合同已生效的 PO；没填合同交期的不算）。")


@provider("proc.risk_projects", "kpi", visible=_board_ok, title="缺料影响的项目")
def _risk_projects(ctx):
    count = len(_overdue_info(ctx)["projects"])
    return kpi("proc.risk_projects", "缺料影响的项目", count, "个", sub="有物料逾期未到" if count else "",
               tone="bad" if count else "", to=drill_to("proc.risk_projects", ctx) if count else None,
               hint="有物料逾期未到的项目数（物料所属项目为空的不算项目）。点进去按项目列出来。")


# ================================================================ KPI：到货、验收（生产主管、PMC）
@provider("proc.week_arrive", "kpi", visible=_po_ok, title="本周预计到货")
def _week_arrive(ctx):
    rows = _lines(ctx)["week"]
    return kpi("proc.week_arrive", "本周预计到货", len(rows), "项", sub=f"来自 {_per_po(rows)} 个 PO" if rows else "",
               to=drill_to("proc.week_arrive", ctx) if rows else None,
               hint="合同交期落在本周（周一到周日）、还没收齐的物料；本周已经过了交期的也在里面（同时算进逾期）。")


@provider("proc.to_arrive", "kpi", visible=_po_ok, title="待到货")
def _to_arrive(ctx):
    rows = _lines(ctx)["to_arrive"]
    return kpi("proc.to_arrive", "待登记到货", len(rows), "项", sub=f"来自 {_per_po(rows)} 个 PO" if rows else "",
               tone="hot" if rows else "", to=drill_to("proc.to_arrive", ctx) if rows else None,
               hint="合同已生效的 PO 里，到货数量还不够的物料行（退货中的不算，单独在「退货中」）。部分到货的行会同时算在待验收里。")


@provider("proc.to_inspect", "kpi", visible=_po_ok, title="待验收")
def _to_inspect(ctx):
    rows = _lines(ctx)["to_inspect"]
    info = _inspect_info(ctx)
    waited = max(info["waited"].values(), default=None)
    return kpi("proc.to_inspect", "待验收", len(rows), "项", sub=f"最久到货 {waited} 天" if rows and waited is not None else "",
               tone="bad" if info["stale"] else ("hot" if rows else ""), to=drill_to("proc.to_inspect", ctx) if rows else None,
               hint="已有到货、还没登记验收结果的物料行。天数从该 PO 最近一条到货登记起算。")


@provider("proc.exchange", "kpi", visible=_po_ok, title="换货中")
def _exchange(ctx):
    rows = _lines(ctx)["exchange"]
    return kpi("proc.exchange", "换货中", len(rows), "项", sub="等供应商补发" if rows else "", tone="warn" if rows else "",
               to=drill_to("proc.exchange", ctx) if rows else None, hint="验收结果为「换货中」的物料行（合同已生效的 PO）。")


@provider("proc.return", "kpi", visible=_po_ok, title="退货中")
def _return(ctx):
    rows = _lines(ctx)["returning"]
    return kpi("proc.return", "退货中", len(rows), "项", sub="等货退回供应商" if rows else "", tone="warn" if rows else "",
               to=drill_to("proc.return", ctx) if rows else None, hint="验收结果为「退货中」的物料行（合同已生效的 PO）。")


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
    return alert("alert.po_overdue", "bad" if pos[worst] > 7 else "warn", f"{len(pos)} 个 PO 已过合同交期还没收齐",
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
    return alert("alert.price_missing_quote", "warn", f"{len(unquoted)} 张待审批的价格审批单有物料没有报价",
                 sub=f"共 {lines} 项物料一个报价都没有，副总没法选供应商", go="价格审批", to=target("price.approvals", view="approvals"))


@provider("alert.uncoded", "alert", visible=_board_ok, title="物料未编码")
def _alert_uncoded(ctx):
    rows = ctx.memo("proc.uncoded", _load_uncoded)
    if not rows:
        return None
    return alert("alert.uncoded", "warn", f"{len(rows)} 项物料还没有物料编码", sub="要 PMC 绑定", go="物料进度", to=target("material.progress"))


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
    materials = _overdue_info(ctx)["materials"]
    if not materials:
        return None
    worst = max(materials.values())
    return alert("alert.material_overdue", "bad" if worst > 7 else "warn", f"{len(materials)} 项物料超过合同交期还没到",
                 sub=f"最久逾期 {worst} 天", go="物料进度", to=target("material.overdue"))


@provider("alert.risk_projects", "alert", visible=_board_ok, title="缺料影响项目")
def _alert_risk_projects(ctx):
    projects = _overdue_info(ctx)["projects"]
    if not projects:
        return None
    ranked = sorted(projects.items(), key=lambda item: (-len(item[1]["keys"]), item[0]))
    sub = "；".join(f"{name} 有 {len(bucket['keys'])} 项物料逾期" for name, bucket in ranked[:2])
    return alert("alert.risk_projects", "warn", f"{len(projects)} 个项目有物料逾期未到", sub=sub, go="缺料项目", to=drill_to("proc.risk_projects", ctx))


# ================================================================ 图表块
@provider("block.proc_chain", "block", visible=_po_ok, title="采购链路")
def _block_proc_chain(ctx):
    counts = ctx.memo("proc.chain", _load_chain_counts)
    values = [("OA 申请", counts["request"]), ("PR", counts["pr"]), ("PO", counts["po"]), ("付款期次", counts["payment"])]
    peak = max((value for _, value in values), default=0) or 1
    return bars("block.proc_chain", "采购链路", [bar_row(label, value, value / peak * 100) for label, value in values],
                sub="累计，个",
                hint="历史累计的存量，不按月份：OA 申请 = 已提交且没被拒绝 / 撤回的采购申请；PR、PO 不含已取消；付款期次 = 所有 PO 付款计划的期数。四个环节单位不同，只看各自的体量，不是转化率。")


@provider("block.arrival_inspect", "block", visible=_po_ok, title="到货与验收")
def _block_arrival_inspect(ctx):
    arrived, passed = _month_counts(ctx)
    data = _lines(ctx)
    rows = [("本月已到货", arrived, "ok"), ("本月已验收通过", passed, "ok"),
            ("待验收", len(data["to_inspect"]), "warn" if data["to_inspect"] else ""), ("待到货", len(data["to_arrive"]), "")]
    peak = max((value for _, value, _ in rows), default=0) or 1
    return bars("block.arrival_inspect", "到货与验收", [bar_row(label, value, value / peak * 100, tone) for label, value, tone in rows],
                sub="物料行 · 前两项是本月登记，后两项是当前存量",
                hint="已到货 / 已验收通过按本月的到货、验收登记数物料行；待验收、待到货是现在还没办完的存量（合同已生效的 PO）。")


@provider("block.proc_suppliers", "block", visible=_money_ok, title="本月采购金额 · 供应商")
def _block_proc_suppliers(ctx):
    totals = {}
    for row in _month_pos(ctx)["cur"]:
        totals[row["supplier"]] = totals.get(row["supplier"], 0.0) + row["amount"]
    return bars("block.proc_suppliers", "本月采购金额 · 供应商", _top_rows(totals, "未填供应商"), sub="前 5 家",
                more="全部供应商" if totals else "", to=drill_to("proc.suppliers", ctx) if totals else None,
                hint="本月创建的 PO（不含已取消）按供应商合计金额；供应商是手填文本，去掉前后空格后同名合并。")


@provider("block.proc_projects", "block", visible=_money_ok, title="本月采购金额 · 项目")
def _block_proc_projects(ctx):
    names = {row["po"] for row in _month_pos(ctx)["cur"]}
    totals = {}
    for row in ctx.memo("proc.month_lines", lambda: _load_po_line_amounts(names)):
        totals[row["project"]] = totals.get(row["project"], 0.0) + row["amount"]
    return bars("block.proc_projects", "本月采购金额 · 项目", _top_rows(totals, "非项目"), sub="前 5 个项目",
                more="全部项目" if totals else "", to=drill_to("proc.projects", ctx) if totals else None,
                hint="本月创建的 PO（不含已取消）按物料行所属项目合计行金额；没填项目的归「非项目」。行金额合计可能和 PO 总额有尾差。")


MATERIAL_STAGE_ROWS = (("待提 PR", ""), ("询价比价", ""), ("PO 已下", ""), ("到货验收", ""), ("已关闭", "ok"))


@provider("block.material_stage", "block", visible=_board_ok, title="物料进度")
def _block_material_stage(ctx):
    counts = dict.fromkeys((label for label, _ in MATERIAL_STAGE_ROWS), 0)
    for row in ctx.memo("proc.stages", _load_stage_counts):
        stage, total = row["stage"], int(row["total"] or 0)
        if stage == "采购确认中":
            counts["待提 PR" if row.get("no_pr") else "询价比价"] += total
        elif stage == "PO处理中":
            counts["询价比价"] += total
        elif stage == "供应商制作中":
            counts["PO 已下"] += total
        elif stage in ("到货验收中", "付款中"):
            counts["到货验收"] += total
        elif stage == "已关闭":
            counts["已关闭"] += total
    peak = max(counts.values(), default=0) or 1
    return bars("block.material_stage", "物料进度", [bar_row(label, counts[label], counts[label] / peak * 100, tone) for label, tone in MATERIAL_STAGE_ROWS],
                sub="按阶段 · 物料行", to=target("material.progress"),
                hint="阶段口径同物料进度看板：待提 PR = 采购确认中且还没有 PR；询价比价 = 采购确认中且已有 PR + PO 处理中（价格审批或 PO 草稿）；PO 已下 = 供应商制作中；到货验收 = 到货验收中 + 付款中；已关闭 = 关联 PO 都已关闭。需求还在 OA 审批的、被拒绝 / 撤回 / 取消的不算。")


@provider("block.risk_projects", "block", visible=_board_ok, title="缺料影响的项目")
def _block_risk_projects(ctx):
    projects = _overdue_info(ctx)["projects"]
    ranked = sorted(projects.items(), key=lambda item: (-len(item[1]["keys"]), item[0]))[:6]
    rows = []
    for name, bucket in ranked:
        items = bucket["items"]
        sub = "、".join(items[:2]) + (" 等" if len(items) > 2 else "")
        rows.append(list_row(name, sub=sub, value=f"{len(bucket['keys'])} 项", tone="bad" if max(bucket["keys"].values()) > 7 else "warn"))
    return listing("block.risk_projects", "缺料影响的项目", rows, sub="逾期未到的物料", to=drill_to("proc.risk_projects", ctx) if projects else None,
                   more=f"还有 {len(projects) - len(ranked)} 个项目" if len(projects) > len(ranked) else "",
                   hint="按项目汇总合同交期已过、还没收齐的物料（按采购申请的物料行去重）；红色 = 最久逾期超过 7 天；物料所属项目为空的不列。")


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
    return listing("block.week_schedule", "本周预计到货", rows, sub="按合同交期 · 物料行" if rows else "本周没有预计到货的物料",
                   to=drill_to("proc.week_arrive", ctx) if rows else None,
                   hint="合同交期落在本周（周一到周日）、还没收齐的物料，按日期排；红色 = 交期已过还没到，黄色 = 今天。")


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
    return cols("block.week_cols", "本周到货日程", rows, sub="预计到货的物料行 · 按合同交期", more="本周明细", to=drill_to("proc.week_arrive", ctx),
                hint="合同交期落在本周（周一到周日）、还没收齐的物料，按天数；今天标橙；已过交期的也在里面（同时算进逾期）。")


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
    late = list(_overdue_info(ctx)["materials"].values())
    if not late:
        return None
    groups = _age_groups(late, [("1–3 天", 3), ("4–7 天", 7), ("超过 7 天", None)])
    peak = max(count for _label, count in groups) or 1
    rows = [bar_row(label, count, _pct(count, peak), "bad" if label.startswith("超过") and count else "") for label, count in groups]
    return bars("block.overdue_aging", "逾期了多久", rows, sub="物料（按采购申请的行去重）", to=target("material.overdue"),
                hint="合同交期已过、还没收齐的物料，按逾期天数分档（从合同交期的次日起算）。")


@provider("block.proc_month_trend", "block", visible=_money_ok, title="近 6 个月采购金额")
def _block_proc_month_trend(ctx):
    def build():
        year, month = int(ctx.period[:4]), int(ctx.period[5:7])
        start = date(year, month, 1)
        for _ in range(5):
            start = (start - timedelta(days=1)).replace(day=1)
        nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        return _load_month_pos(start.isoformat(), nxt.isoformat())
    totals = {}
    for row in ctx.memo("proc.trend_pos", build):
        totals[row["month"]] = totals.get(row["month"], 0.0) + row["amount"]
    if not totals:
        return None
    year, month = int(ctx.period[:4]), int(ctx.period[5:7])
    months = []
    for _ in range(6):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    months.reverse()
    peak = max(totals.get(key, 0.0) for key in months) or 1
    rows = [col_row(f"{int(key[5:])}月", f"{totals.get(key, 0.0) / 10000:.1f}", _pct(totals.get(key, 0.0), peak), key == ctx.period) for key in months]
    return cols("block.proc_month_trend", "近 6 个月采购金额", rows, sub="万元 · 按 PO 创建月份",
                hint="每月创建的 PO（不含已取消）金额合计；供应商、项目分布看右边两块。")


@provider("block.pay_next30", "block", visible=_pay_ok, title="未来 30 天要付多少")
def _block_pay_next30(ctx):
    """按计划付款日，采购付款期次里还没付清的金额：已过计划日、本周、下周、第 3 周、第 4 周、更晚、没排期。"""
    today = _today(ctx)
    labels = ["已过计划日", "本周", "下周", "第 3 周", "第 4 周", "更晚", "没排期"]
    totals = dict.fromkeys(labels, 0.0)
    for item in _payment_items(ctx):
        owed = max(item["amount"] - item["paid"], 0)
        if item["work_status"] == "已付款" or owed <= 0:
            continue
        if not item["planned"]:
            totals["没排期"] += owed
            continue
        delta = (date.fromisoformat(item["planned"]) - today).days
        key = "已过计划日" if delta < 0 else "本周" if delta < 7 else "下周" if delta < 14 else "第 3 周" if delta < 21 else "第 4 周" if delta < 28 else "更晚"
        totals[key] += owed
    if not any(totals.values()):
        return None
    peak = max(totals.values()) or 1
    rows = [col_row(label, f"{totals[label] / 10000:.1f}", _pct(totals[label], peak), label == "已过计划日" and totals[label] > 0) for label in labels]
    return cols("block.pay_next30", "未来 30 天要付多少", rows, sub="万元 · 采购付款，按计划付款日", more="付款期次", to=drill_to("proc.pay_plan", ctx),
                hint="采购付款期次里还没付清的金额（合同金额 − 已付），按计划付款日分到各周；已过计划日的标橙；没填计划日的单独一栏。报销单、付款单没有计划日，不在这里。")
