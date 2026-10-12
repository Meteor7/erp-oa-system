"""财务、费用、付款和审批卡点的看板块（money）。

数据都来自现有接口，口径不另起炉灶：
- 费用：`overview_entry.get_cost_overview`（副总、总经理岗位，或 Accounts User / System Manager）；
  研发分摊：`allocation_entry.get_allocation`（只有 Accounts User / System Manager，含境外委托研发）。
- 付款：报销单 + 付款单用付款看板同一套查询和归集（`expense_board_entry._rows/_decorate` + `expense_boards.payment_board`），
  采购付款期次用 `procurement_chain.list_payment_work_items`（只在有 PO 查看权时）。付款看板的范围规则：
  财务、管理层看全公司，其他人不返回。
- 审批卡点：报销、付款、采购申请、购买申请、出差、采购付款（同付款/申请看板的范围）+ 价格审批（要有价格审批查看权）。

等待时长的口径只有一个：`expense_board_entry._decorate` 的 `waited_days`，从最近一次签批起算，
没有人签过就从最近一次提交起算。没有「逾期」，只有「等待超过 3 天」（> 3，不含）。

约定：`visible(ctx)` 只看 ctx（角色、岗位）和一次请求内备忘的权限探测，不看 profile；
没权限的人不会调用底层函数。底层数据通过 `ctx.memo("money.*", …)` 取，几个块共用一次。
"""
from __future__ import annotations

import calendar
import json
from datetime import date, timedelta

from rayher_hr_payroll import expense_boards as boards
from rayher_hr_payroll.dashboard.core import (
    alert, bar_row, bars, col_row, cols, drill, drill_row, drill_to, kpi, list_row, listing, money_wan, provider, stack,
    stack_row, target,
)

STUCK_DAYS = boards.STUCK_DAYS            # 3：等待超过 3 天（> 3）算卡住 / 算等得久
INVOICE_STALE_DAYS = 7                    # 发票待确认超过 7 天
BOARD_ADMIN_USERS = {"Administrator", "admin@staff.example.invalid"}   # 同 expense_board_entry._scope
FINANCE_ROLES = ("System Manager", "Accounts User")                   # 同 invoice_ocr.service.FINANCE_ROLES / RD_FINANCE_ROLES
LABOR_ROLES = ("System Manager", "HR Manager", "HR User")
LABOR_POSITIONS = ("vice_manager", "general_manager")

# 付款审批的岗位（按报销/付款路线的先后排；采购付款路线的岗位也都在里面）。
STEP_ROLES = (
    ("finance_auditor", "出纳"), ("finance_accountant", "总账会计"), ("finance_manager", "财务主管"),
    ("vice_manager", "副总经理"), ("general_manager", "总经理"),
)
STEP_ORDER = ("出纳", "直属主管", "总账会计", "财务主管", "副总经理", "总经理", "其他")

ORANGE, BLUE, GREEN, RED, GRAY = "#E89A3C", "#4F6BDC", "#2F855A", "#D1453B", "#9AA0AA"


# ---------------------------------------------------------------- 小工具
def _today(ctx):
    return date.fromisoformat(ctx.today)


def _month_label(ctx, tail):
    """当前月叫「本月xx」，选了别的月份就写「N 月xx」。"""
    if ctx.period == ctx.today[:7]:
        return "本月" + tail
    return f"{int(ctx.period[5:])} 月{tail}"


def _month_bounds(period):
    year, month = int(period[:4]), int(period[5:7])
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def _amt(amount):
    number, unit = money_wan(amount)
    return f"¥ {number}" if unit == "元" else f"¥ {number} {unit}"


def _wan(amount):
    return f"{float(amount or 0) / 10000:,.1f}"


def _pct(part, total):
    return float(part) / float(total) * 100 if total else 0


def _delta_text(delta):
    if delta is None:
        return "上月没有可比数据"
    if delta == 0:
        return "与上月持平"
    return f"{'▲' if delta > 0 else '▼'} {abs(delta):g}% 较上月"


def _json_list(value):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return []
    return [str(item).strip() for item in parsed] if isinstance(parsed, list) else []


def _top_bars(pairs, limit, other_unit, tone_of=None):
    """[(标签, 金额)] 已按金额从大到小：取前 limit 项，其余合并成「其他 N 个/家…」，条长相对最大值。"""
    pairs = [(label, float(amount)) for label, amount in pairs if float(amount) > 0]
    shown = pairs[:limit]
    rest = pairs[limit:]
    if rest:
        shown.append((f"其他 {len(rest)} {other_unit}", sum(amount for _label, amount in rest)))
    top = max((amount for _label, amount in shown), default=0)
    return [bar_row(label, _wan(amount), _pct(amount, top), tone_of(index, label) if tone_of else "")
            for index, (label, amount) in enumerate(shown)]


# ---------------------------------------------------------------- 权限
# visible 必须等于背后接口的真实权限；这几个函数就是那些接口的判断，换成 ctx 的写法。
def _can_cost(ctx):
    """get_cost_overview：副总、总经理岗位，或 Accounts User / System Manager。"""
    return ctx.holds("vice_manager", "general_manager") or ctx.can(*FINANCE_ROLES)


def _can_alloc(ctx):
    """get_allocation / get_allocation_dashboard：只有 Accounts User / System Manager（岗位不够）。"""
    return ctx.can(*FINANCE_ROLES)


def _board_all(ctx):
    """付款看板、申请看板、采购页签的范围：财务、管理层看全公司（`boards.board_scope`），其他人没有。"""
    return ctx.user in BOARD_ADMIN_USERS or boards.board_scope(ctx.roles, ctx.positions) == "all"


def _can_invoice(ctx):
    """list_invoice_folder(view="all")：财务角色 + 发票功能开放。"""
    if not ctx.can(*FINANCE_ROLES):
        return False

    def probe():
        from rayher_hr_payroll.invoice_ocr import permissions
        return bool(permissions.invoice_feature_open(ctx.user))

    return ctx.memo("money.invoice_open", probe)


def _can_labor(ctx):
    return ctx.can(*LABOR_ROLES) or ctx.holds(*LABOR_POSITIONS)


def _probe(ctx, name, checks):
    """用现有接口自己的检查函数探测当前登录人有没有权限（它们看的是当前会话用户，和 ctx.user 相同）。"""
    def run():
        import frappe
        from rayher_hr_payroll.api import procurement_chain
        try:
            for check, args in checks:
                getattr(procurement_chain, check)(*args)
        except (frappe.PermissionError, frappe.ValidationError):
            return False
        return True

    return ctx.memo(name, run)


def _po_pay_view(ctx):
    """list_payment_work_items：功能开关 + 能看 PO。"""
    from rayher_hr_payroll.oa_document_types import REQUEST_PROCUREMENT_PAYMENT
    return _probe(ctx, "money.po_pay_view", [("_require_gate", (REQUEST_PROCUREMENT_PAYMENT,)), ("_require_po_view", ())])


def _price_view(ctx):
    """list_price_approvals：功能开关 + 能看采购链路。"""
    from rayher_hr_payroll.oa_document_types import REQUEST_PROCUREMENT
    return _probe(ctx, "money.price_view", [("_require_gate", (REQUEST_PROCUREMENT,)), ("_require_view", ())])


def _always(_ctx):
    """本人的审批待办、本人处理过的记录：谁都只能看到自己的。"""
    return True


# ---------------------------------------------------------------- 底层数据（一次请求里共用）
def _overview(ctx):
    def load():
        from rayher_hr_payroll.api import overview_entry
        result = overview_entry.get_cost_overview("month", ctx.period)
        return result if result.get("visible") else None

    return ctx.memo("money.cost_overview", load)


def _allocation(ctx):
    def load():
        from rayher_hr_payroll.api import allocation_entry
        return allocation_entry.get_allocation(ctx.period)

    return ctx.memo("money.allocation", load)


def _claims(ctx):
    """报销单 + 付款单：{"rows": 待审批/待办理/已付款的单据（带 waited_days）, "board": payment_board 的结果}。

    和 `expense_board_entry.payment_board` 同一套查询；多取一份 rows 是为了拿到「审批中」和等待天数。
    付款/费用科目按所选期间的实际付款日期算（board 的 today 取期间内的一天），待付款队列是当前状态。"""
    def load():
        import frappe
        from rayher_hr_payroll.api import expense_board_entry as board_entry

        today = _today(ctx)
        rows = board_entry._decorate(
            board_entry._rows(boards.CLAIM_TYPES, "all", "", (*boards.ACTIVE_STATUSES, boards.PAID)), today)
        anchor = today if ctx.period == ctx.today[:7] else date(int(ctx.period[:4]), int(ctx.period[5:7]), 1)
        paid = [row["name"] for row in rows
                if row["workflow_status"] == boards.PAID and boards.month_key(row.get("paid_on")) == ctx.period]
        lines = frappe.get_all(
            "OA Approval Expense Line", filters={"parent": ["in", paid], "parenttype": "OA Approval Request"},
            fields=["parent", "expense_account_level_1", "expense_account_level_2", "total_amount"],
            limit_page_length=0) if paid else []
        return {"rows": rows, "board": boards.payment_board(rows, lines, today=anchor)}

    return ctx.memo("money.claims", load)


def _purchase(ctx):
    """采购付款期次：没有 PO 查看权返回 None。{"items": 付款工作项, "waits": {付款单号: 等待天数}, "paid_month": [本月已付金额]}。"""
    def load():
        if not _po_pay_view(ctx):
            return None
        import frappe
        from rayher_hr_payroll.api import expense_board_entry as board_entry, procurement_chain
        from rayher_hr_payroll.oa_document_types import REQUEST_PROCUREMENT_PAYMENT

        items = procurement_chain.list_payment_work_items(limit=1000) or []
        names = sorted({item["payment_request"] for item in items
                        if item.get("payment_request") and item.get("work_status") in ("待实际付款", "付款审批中")})
        waits = {}
        if names:
            rows = frappe.get_all("OA Approval Request", filters={"name": ["in", names]},
                                  fields=["name", "creation", "modified"], limit_page_length=0)
            waits = {row["name"]: row["waited_days"] for row in board_entry._decorate(rows, _today(ctx))}
        first, last = _month_bounds(ctx.period)
        paid = frappe.get_all(
            "OA Approval Request",
            filters={"request_type": REQUEST_PROCUREMENT_PAYMENT, "workflow_status": boards.PAID,
                     "paid_on": ["between", [first, last]]},
            fields=["amount"], limit_page_length=0)
        return {"items": items, "waits": waits, "paid_month": [float(row.get("amount") or 0) for row in paid]}

    return ctx.memo("money.purchase", load)


def _step_bucket(approvers, label, owners):
    users = {name.lower() for name in _json_list(approvers)}
    for _key, name in STEP_ROLES:
        if users & owners.get(name, set()):
            return name
    if str(label or "").startswith("直属主管"):
        return "直属主管"
    return "其他"


def _step_buckets(ctx):
    """审批中的单据 -> 当前审批节点归到哪个岗位：{单据号: "出纳" | "总账会计" | … | "其他"}。

    用 OA Approval Step.approvers（审批人账号）反查 `position_users`，岗位对不上的合并成「其他」。"""
    def load():
        import frappe
        from rayher_hr_payroll.position_access import position_users

        wanted = {row["name"]: int(row.get("current_step_index") or 0)
                  for row in _claims(ctx)["rows"] if row["workflow_status"] == "待审批"}
        for item in ((_purchase(ctx) or {}).get("items") or []):
            if item.get("work_status") == "付款审批中" and item.get("payment_request"):
                wanted[item["payment_request"]] = int((item.get("payment_request_summary") or {}).get("current_step_index") or 0)
        if not wanted:
            return {}
        owners = {name: {user.lower() for user in position_users(key)} for key, name in STEP_ROLES}
        steps = frappe.get_all(
            "OA Approval Step", filters={"parent": ["in", sorted(wanted)], "parenttype": "OA Approval Request"},
            fields=["parent", "step_index", "label", "approvers"], limit_page_length=0)
        return {step["parent"]: _step_bucket(step.get("approvers"), step.get("label"), owners)
                for step in steps if int(step.get("step_index") or 0) == wanted.get(step["parent"])}

    return ctx.memo("money.step_buckets", load)


def _pay(ctx):
    """把报销、付款、采购付款整理成同一种条目：

    unpaid：待付款（报销/付款单「待办理」+ 采购付款期次「待实际付款」）；approving：付款审批中；
    paid：本期已付。条目 {kind, name, amount, waited, urgent, bucket, supplier, stage}。"""
    def build():
        claims, purchase = _claims(ctx), _purchase(ctx)
        buckets = _step_buckets(ctx) if _step_buckets_needed(claims, purchase) else {}
        unpaid, approving = [], []
        for row in claims["board"]["cashier_queue"]:
            if row["status"] == "待付款":
                unpaid.append({"kind": row["request_type"], "name": row["name"], "amount": float(row["amount"]),
                               "waited": int(row["waited_days"]), "urgent": row["urgency"] == "加急",
                               "supplier": "", "stage": ""})
        for row in claims["rows"]:
            if row["workflow_status"] == "待审批":
                approving.append({"kind": row["request_type"], "name": row["name"], "amount": float(row.get("amount") or 0),
                                  "waited": int(row["waited_days"]), "urgent": False,
                                  "bucket": buckets.get(row["name"], "其他"), "supplier": "", "stage": ""})
        payables = []   # 采购付款里「合同已生效、还没付清」的期次，给供应商排行用
        for item in ((purchase or {}).get("items") or []):
            status, request = item.get("work_status"), item.get("payment_request") or ""
            amount = float(item.get("amount") or 0)
            owed = max(0.0, amount - float(item.get("paid_amount") or 0))
            entry = {"kind": "采购付款", "name": request or f"{item.get('po')}:{item.get('installment_no')}",
                     "amount": owed, "waited": int((purchase["waits"] or {}).get(request, 0)), "urgent": False,
                     "bucket": buckets.get(request, "其他"), "supplier": str(item.get("supplier") or "").strip(),
                     "stage": str(item.get("payment_stage") or "").strip()}
            if status == "待实际付款":
                unpaid.append(entry)
            elif status == "付款审批中":
                approving.append(dict(entry, amount=amount))
            if status not in ("已付款", "待合同生效") and owed > 0:
                payables.append(entry)
        summary = claims["board"]["summary"]
        paid_rows = [row for row in claims["rows"]
                     if row["workflow_status"] == boards.PAID and boards.month_key(row.get("paid_on")) == ctx.period]
        paid = {"claim_amount": float(summary["reimbursement_paid"]), "payment_amount": float(summary["payment_paid"]),
                "claim_count": len(paid_rows),
                "purchase_amount": sum((purchase or {}).get("paid_month") or []),
                "purchase_count": len((purchase or {}).get("paid_month") or []), "has_purchase": purchase is not None}
        return {"unpaid": unpaid, "approving": approving, "payables": payables, "paid": paid,
                "has_purchase": purchase is not None, "by_account": claims["board"].get("by_account") or []}

    return ctx.memo("money.pay", build)


def _step_buckets_needed(claims, purchase):
    return any(row["workflow_status"] == "待审批" for row in claims["rows"]) or any(
        item.get("work_status") == "付款审批中" for item in ((purchase or {}).get("items") or []))


def _verify_queue(oa_entry, frappe):
    """财务的“待核验发票”付款单（和付款申请页的待我处理同一个查询：已付款、等核验，财务才有）。不是财务就是空的。"""
    from rayher_hr_payroll import expense_claims
    from rayher_hr_payroll.oa_document_types import REQUEST_PAYMENT

    try:
        oa_entry._require_finance_user()
    except Exception:
        return []
    return list(frappe.get_all(
        "OA Approval Request",
        filters={"request_type": REQUEST_PAYMENT, "workflow_status": oa_entry.STATUS_PAID, "business_status": expense_claims.CLAIM_WAIT_VERIFY},
        pluck="name", order_by="modified asc", limit_page_length=200))


def _my_queue(ctx):
    """我待审批的报销、付款单、采购付款（`get_my_approval_summary`）+ 各自等待天数。"""
    def load():
        import frappe
        from rayher_hr_payroll.api import expense_board_entry as board_entry, oa_entry

        groups = {category["key"]: list(category.get("requests") or [])
                  for category in oa_entry.get_my_approval_summary().get("categories", [])}
        verify = _verify_queue(oa_entry, frappe)
        # 付款申请页的“待我处理”= 轮到我审批的付款单 + 财务的待核验发票的付款单（同一张不重复算）
        verify = [name for name in verify if name not in set(groups.get("payment", []))]
        names = sorted({name for key in ("reimbursement", "payment", "procurement_payment") for name in groups.get(key, [])} | set(verify))
        waited = {}
        if names:
            rows = frappe.get_all("OA Approval Request", filters={"name": ["in", names]},
                                  fields=["name", "creation", "modified"], limit_page_length=0)
            waited = {row["name"]: row["waited_days"] for row in board_entry._decorate(rows, _today(ctx))}
        return {"claim": groups.get("reimbursement", []), "payment": groups.get("payment", []),
                "procpay": groups.get("procurement_payment", []), "verify": verify, "waited": waited}

    return ctx.memo("money.my_queue", load)


def _invoices(ctx):
    """发票夹各状态张数（全部发票）+ 待确认超过 7 天的张数（按最后修改时间）。"""
    def load():
        import frappe
        from rayher_hr_payroll.api import invoice_folder_entry
        from rayher_hr_payroll.invoice_ocr import service

        counts = invoice_folder_entry.list_invoice_folder(view="all", limit=1).get("counts") or {}
        cutoff = (_today(ctx) - timedelta(days=INVOICE_STALE_DAYS)).isoformat()
        stale = frappe.db.count(service.RECORD_DOCTYPE, {"recognition_status": "待确认", "modified": ["<", cutoff]})
        return {"counts": {name: int(value or 0) for name, value in counts.items()}, "stale": int(stale or 0)}

    return ctx.memo("money.invoices", load)


def _stuck(ctx):
    """审批卡点：[{type, name, waited, step}]，等待 > 3 天。

    范围：报销单、付款单、采购申请、购买申请、出差申请、采购付款（待审批/待办理）+ 价格审批（有查看权时）；不含请假、加班、调休。"""
    def load():
        import frappe
        from rayher_hr_payroll.api import expense_board_entry as board_entry

        today = _today(ctx)
        types = (*boards.APPLICATION_TYPES, *boards.CLAIM_TYPES, *boards.PROCUREMENT_TYPES)
        rows = board_entry._decorate(board_entry._rows(types, "all", "", boards.ACTIVE_STATUSES), today)
        items = [{"type": row["request_type"], "name": row["name"], "waited": int(row["waited_days"]),
                  "step": row.get("current_step_label") or ""}
                 for row in rows if int(row["waited_days"]) > STUCK_DAYS]
        if _price_view(ctx):
            approvals = frappe.get_all("OA Price Approval", filters={"status": "待审批"},
                                       fields=["name", "modified"], limit_page_length=0)
            acted = {}
            if approvals:
                for step in frappe.get_all("OA Approval Step", filters={"parent": ["in", [row["name"] for row in approvals]]},
                                           fields=["parent", "acted_on"], limit_page_length=0):
                    day = boards.as_date(step.get("acted_on"))
                    if day and (step["parent"] not in acted or day > acted[step["parent"]]):
                        acted[step["parent"]] = day
            for row in approvals:
                started = acted.get(row["name"]) or boards.as_date(row.get("modified"))
                waited = max(0, (today - started).days) if started else 0
                if waited > STUCK_DAYS:
                    items.append({"type": "价格审批", "name": row["name"], "waited": waited, "step": "价格审批（副总终审）"})
        return items

    return ctx.memo("money.stuck", load)


def _labor(ctx):
    def load():
        import frappe
        from rayher_hr_payroll import payroll_bridge
        from rayher_hr_payroll.api import dormitory_board

        pay = payroll_bridge.period_pay_totals(ctx.period)
        contributions = payroll_bridge.period_company_contributions(ctx.period)
        rows = frappe.get_all("Accommodation Deduction", filters={"period": ctx.period},
                              fields=dormitory_board.DEDUCTION_FIELDS, limit_page_length=0)
        dorm = dormitory_board._cost(rows)
        return {"gross": float(pay.get("gross") or 0),
                "social": sum(float(value.get("si") or 0) for value in contributions.values()),
                "fund": sum(float(value.get("hf") or 0) for value in contributions.values()),
                "has_contributions": bool(contributions),
                "dorm_company": float(dorm["company"]), "dorm_registered": bool(dorm["registered"])}

    return ctx.memo("money.labor", load)


# ================================================================ 费用
def _cost_card(ctx, key, label, field, to, hint, with_share=False):
    data = _overview(ctx)
    if not data:
        return None
    totals, deltas = data["totals"], data["deltas"]
    number, unit = money_wan(totals[field])
    sub = _delta_text(deltas.get(field))
    if with_share:
        sub = f"占 {_pct(totals['rd'], totals['total']):.0f}% · {sub}"
    return kpi(key, label, number, unit, sub, to=to, hint=hint, preview=bool(data.get("preview")) and field in ("rd", "total"))


@provider("cost.total", "kpi", visible=_can_cost, title="费用合计")
def cost_total(ctx):
    # 合计由三部分相加，研发费用汇总页只有研发那一部分，直接跳过去数字对不上；点进去是三部分的明细（相加正好等于这个数）。
    return _cost_card(
        ctx, "cost.total", _month_label(ctx, "费用合计"), "total", drill_to("cost.total", ctx),
        "费用合计 = 研发分摊 + 采购（PO 金额，按下单日期）+ 报销付款（按实际付款日期）；已有研发分摊的月份，研发项目的采购和报销不重复计入；"
        "没定版的月份研发部分用预览。来源：首页费用概览。点进去看三部分各是多少。")


@provider("drill.cost.total", "drill", visible=_can_cost, title="费用合计")
def drill_cost_total(ctx):
    """三部分相加 = 指标卡上的费用合计；每一部分再点进它自己的页面。"""
    data = _overview(ctx)
    if not data:
        return None
    totals = data["totals"]
    rows = [
        drill_row(["研发分摊", "工资、社保公积金、境外委托研发" + ("（预览，还没定版）" if data.get("preview") else ""), _amt(totals["rd"])],
                  target("cost.summary", period=ctx.period)),
        drill_row(["采购", "本期新下的 PO 金额，按下单日期，不含已取消", _amt(totals["po"])], target("price.approvals", tab="po")),
        drill_row(["报销付款", "本期已付款的报销单、付款单，按实际付款日期", _amt(totals["expense"])], target("board.payment")),
    ]
    rows.append(drill_row(["合计", "三部分相加", _amt(totals["total"])], tone="hot"))
    return drill("drill.cost.total", f"{_month_label(ctx, '费用合计')}由哪几部分组成",
                 [("部分",), ("口径",), ("金额", "r")], rows, summary=f"合计 {_amt(totals['total'])}",
                 note="已有研发分摊的月份，研发项目的采购和报销已经包含在研发分摊里，不重复计入。")


@provider("cost.rd", "kpi", visible=_can_cost, title="研发分摊")
def cost_rd(ctx):
    return _cost_card(
        ctx, "cost.rd", "研发分摊", "rd", target("cost.summary", period=ctx.period),
        "研发分摊含工资、社保公积金和境外委托研发；没定版的月份是预览数。来源：首页费用概览。", with_share=True)


@provider("cost.po", "kpi", visible=_can_cost, title="采购")
def cost_po(ctx):
    return _cost_card(ctx, "cost.po", "采购（PO 金额）", "po", drill_to("cost.po", ctx),
                      "本期新下的 PO 金额合计（不含已取消），按下单日期；不是付款额。来源：首页费用概览。点进去按 PO 列出来。")


@provider("drill.cost.po", "drill", visible=_can_cost, title="采购（PO 金额）")
def drill_cost_po(ctx):
    """和 overview_entry._po_rows 同一个口径：本期创建、没取消的 PO，金额取物料行合计（已有研发分摊的月份，研发项目的行不重复计入）。"""
    import frappe
    from rayher_hr_payroll.api import overview_entry as overview

    data = _overview(ctx)
    start, end = overview.month_range([(int(ctx.period[:4]), int(ctx.period[5:7]))])
    pos = frappe.get_all("OA Purchase Order", filters={"status": ["not in", list(overview.PO_DEAD_STATUS)], "creation": ["between", [start, end]]},
                         fields=["name", "supplier", "status", "creation"], limit_page_length=0)
    amounts = {}
    if pos:
        for line in frappe.get_all("OA Purchase Order Line", filters={"parent": ["in", [po["name"] for po in pos]]},
                                   fields=["parent", "amount"], limit_page_length=0):
            amounts[line["parent"]] = amounts.get(line["parent"], 0.0) + float(line.get("amount") or 0)
    pos.sort(key=lambda po: -amounts.get(po["name"], 0.0))
    rows = [drill_row([po["name"], str(po.get("supplier") or "").strip() or "—", po.get("status") or "", str(po.get("creation"))[:10],
                       _amt(amounts.get(po["name"], 0.0))], target("price.po", po=po["name"])) for po in pos]
    total = sum(amounts.values())
    shown = ((data or {}).get("totals") or {}).get("po", total)
    note = ("本期已有研发分摊，研发项目的采购包含在研发分摊里，所以费用合计里的采购比这张清单少。"
            if abs(float(shown) - total) > 0.5 else "")
    return drill("drill.cost.po", _month_label(ctx, "新下的 PO"), [("PO",), ("供应商",), ("状态",), ("下单日",), ("PO 金额", "r")], rows,
                 summary=f"共 {len(pos)} 个 PO，合计 {_amt(total)}", note=note)


@provider("cost.expense", "kpi", visible=_can_cost, title="报销")
def cost_expense(ctx):
    return _cost_card(ctx, "cost.expense", "报销付款", "expense", drill_to("cost.expense", ctx),
                      "本期已付款的报销单、付款单费用明细合计，按实际付款日期。来源：首页费用概览。点进去按单据列出来。")


_COST_DETAIL_TARGET = {"报销单": "claim.detail", "付款单": "payment.detail", "费用付款申请": "reimbursement.detail"}


@provider("drill.cost.expense", "drill", visible=_can_cost, title="报销付款")
def drill_cost_expense(ctx):
    """和 overview_entry._expense_rows 同一个口径：本期已付款的报销单、付款单，金额取费用明细行合计。"""
    import frappe
    from rayher_hr_payroll.api import overview_entry as overview

    start, end = overview.month_range([(int(ctx.period[:4]), int(ctx.period[5:7]))])
    requests = frappe.get_all("OA Approval Request",
                              filters={"request_type": ["in", list(overview.COST_REQUEST_TYPES)], "workflow_status": "已付款", "paid_on": ["between", [start, end]]},
                              fields=["name", "request_type", "subject", "employee_name", "paid_on"], limit_page_length=0)
    amounts = {}
    if requests:
        for line in frappe.get_all("OA Approval Expense Line", filters={"parent": ["in", [row["name"] for row in requests]]},
                                   fields=["parent", "total_amount", "amount"], limit_page_length=0):
            amounts[line["parent"]] = amounts.get(line["parent"], 0.0) + float(line.get("total_amount") or line.get("amount") or 0)
    requests.sort(key=lambda row: -amounts.get(row["name"], 0.0))
    rows = []
    for row in requests:
        key = _COST_DETAIL_TARGET.get(row["request_type"])
        rows.append(drill_row([row["name"], row["request_type"], str(row.get("subject") or "").strip() or "—", str(row.get("employee_name") or "—"),
                               str(row.get("paid_on"))[:10], _amt(amounts.get(row["name"], 0.0))],
                              target(key, request=row["name"]) if key else None))
    total = sum(amounts.values())
    return drill("drill.cost.expense", _month_label(ctx, "已付款的报销和付款"),
                 [("单号",), ("类型",), ("事由",), ("申请人",), ("付款日",), ("金额", "r")], rows,
                 summary=f"共 {len(requests)} 张，合计 {_amt(total)}")


@provider("cost.rd_pending", "kpi", visible=_can_cost, title="本期研发分摊")
def cost_rd_pending(ctx):
    """状态为主：预览 = 按当前数据现算、财务主管定版后才作数。副总、总经理没有分摊页权限，所以用费用概览里的数字和预览标记。"""
    data = _overview(ctx)
    if not data:
        return None
    rd = data["totals"]["rd"]
    number, unit = money_wan(rd)
    if data.get("preview"):
        sub, tone = "预览，财务主管定版后才作数", "warn"
    elif rd > 0:
        sub, tone = "已定版", "ok"
    else:
        sub, tone = "本期还没有研发分摊数据", ""
    return kpi("cost.rd_pending", "本期研发分摊", number, unit, sub, tone,
               to=target("allocation", period=ctx.period) if _can_alloc(ctx) else None,
               hint="本期研发分摊金额（含境外委托研发）；预览表示本月还没有定版。来源：首页费用概览。", preview=bool(data.get("preview")))


def _alloc_card(ctx, key, label, field, stage_label):
    alloc = _allocation(ctx)
    amount = float(alloc.get(field) or 0)
    number, unit = money_wan(amount)
    total = sum(float(alloc.get(name) or 0) for name in ("capitalized", "expensed", "unknown"))
    if not alloc.get("has_data"):
        return kpi(key, label, "—", "", "本期还没有费用导入", to=target("allocation", period=ctx.period),
                   hint=f"{stage_label}。来源：研发费用分摊（含境外委托研发）。")
    sub = f"占研发分摊 {_pct(amount, total):.0f}%" if field == "capitalized" else "定版前要确认"
    tone = ("hot" if amount > 0 else "ok") if field == "unknown" else ""
    return kpi(key, label, number, unit, sub, tone, to=target("allocation", period=ctx.period),
               hint=f"{stage_label}。来源：研发费用分摊（含境外委托研发，口径同分摊页）。", preview=bool(alloc.get("preview")))


@provider("cost.cap", "kpi", visible=_can_alloc, title="资本化")
def cost_cap(ctx):
    return _alloc_card(ctx, "cost.cap", "其中资本化", "capitalized", "研发分摊里判定为资本化的金额")


@provider("cost.unknown", "kpi", visible=_can_alloc, title="未判定")
def cost_unknown(ctx):
    return _alloc_card(ctx, "cost.unknown", "未判定", "unknown", "研发分摊里还没判定资本化 / 费用化的金额")


@provider("alloc.status", "kpi", visible=_can_cost, title="研发分摊状态")
def alloc_status(ctx):
    """财务（Accounts User / System Manager）看到完整状态和未判定金额；副总、总经理只有预览 / 已定版（来自费用概览）。"""
    to = target("allocation", period=ctx.period) if _can_alloc(ctx) else None
    hint = ("研发分摊本期的状态：预览 = 按当前数据现算、还没定版；已定版 = 财务主管已提交。"
            "未判定 = 还没判定资本化 / 费用化的金额（只有财务看得到）。")
    if _can_alloc(ctx):
        alloc = _allocation(ctx)
        if not alloc.get("has_data"):
            return kpi("alloc.status", "研发分摊", "—", "", "本期还没有费用导入", to=to, hint=hint)
        total = sum(float(alloc.get(name) or 0) for name in ("capitalized", "expensed", "unknown"))
        unknown = float(alloc.get("unknown") or 0)
        preview = bool(alloc.get("preview")) and not alloc.get("finalized")
        parts = [f"{int(ctx.period[5:])} 月 {_amt(total)}"]
        if preview:
            parts.append("未定版")
        if unknown > 0:
            parts.append(f"未判定 {_amt(unknown)}")
        tone = "warn" if preview or unknown > 0 else "ok"
        return kpi("alloc.status", "研发分摊", "预览" if preview else "已定版", "", "，".join(parts), tone, to=to, hint=hint, preview=preview)
    data = _overview(ctx)
    if not data:
        return None
    rd = data["totals"]["rd"]
    preview = bool(data.get("preview"))
    if not preview and rd <= 0:
        return kpi("alloc.status", "研发分摊", "—", "", "本期还没有研发分摊数据", hint=hint)
    return kpi("alloc.status", "研发分摊", "预览" if preview else "已定版", "",
               f"{int(ctx.period[5:])} 月 {_amt(rd)}" + ("，未定版" if preview else ""), "warn" if preview else "ok",
               hint=hint, preview=preview)


@provider("alert.alloc_unknown", "alert", visible=_can_alloc, title="分摊未判定")
def alert_alloc_unknown(ctx):
    alloc = _allocation(ctx)
    unknown = float(alloc.get("unknown") or 0)
    if unknown <= 0:
        return None
    return alert("alert.alloc_unknown", "warn", f"分摊有 {_amt(unknown)} 费用未判定阶段",
                 "定版前需要确认" if not alloc.get("finalized") else "这个月已经定版，仍有未判定的金额",
                 "研发分摊", target("allocation", period=ctx.period))


@provider("alert.alloc_preview", "alert", visible=_can_alloc, title="分摊仍是预览")
def alert_alloc_preview(ctx):
    alloc = _allocation(ctx)
    unknown = float(alloc.get("unknown") or 0)
    if not alloc.get("preview") or alloc.get("finalized") or unknown <= 0:
        return None
    return alert("alert.alloc_preview", "info", f"{int(ctx.period[5:])} 月研发分摊仍是预览",
                 f"还有 {_amt(unknown)} 未判定，定版前需要处理", "研发分摊", target("allocation", period=ctx.period))


@provider("block.cost_mix", "block", visible=_can_cost, title="费用构成")
def block_cost_mix(ctx):
    data = _overview(ctx)
    if not data:
        return None
    totals = data["totals"]
    to = drill_to("cost.total", ctx)
    if totals["total"] <= 0:
        return stack("block.cost_mix", "费用构成", [], sub=_month_label(ctx, "还没有费用数据"), more="明细", to=to)
    rows = [stack_row("研发分摊", f"{_wan(totals['rd'])} 万", _pct(totals["rd"], totals["total"]), ORANGE),
            stack_row("采购", f"{_wan(totals['po'])} 万", _pct(totals["po"], totals["total"]), BLUE),
            stack_row("报销付款", f"{_wan(totals['expense'])} 万", _pct(totals["expense"], totals["total"]), GREEN)]
    return stack("block.cost_mix", "费用构成", rows, sub=_month_label(ctx, f"费用合计 {_amt(totals['total'])}"), more="明细", to=to,
                 hint="研发分摊 + 采购（PO 金额）+ 报销付款（已付款）；口径同「费用合计」。")


@provider("block.cost_trend", "block", visible=_can_cost, title="月度费用趋势")
def block_cost_trend(ctx):
    data = _overview(ctx)
    if not data:
        return None
    trend = list(data.get("trend") or [])[-6:]
    top = max((float(item["total"]) for item in trend), default=0)
    rows = [col_row(item["label"], _wan(item["total"]).replace(".0", ""), _pct(item["total"], top), last=index == len(trend) - 1)
            for index, item in enumerate(trend)]
    preview = any(item.get("preview") for item in trend)
    return cols("block.cost_trend", "月度费用趋势", rows, sub="近 6 个月 · 万元" + ("（含预览月份）" if preview else ""),
                hint="每月费用合计（研发分摊 + 采购 + 报销付款），没定版的月份研发部分是预览。")


@provider("block.cost_projects", "block", visible=_can_cost, title="项目费用排行")
def block_cost_projects(ctx):
    data = _overview(ctx)
    if not data:
        return None
    pairs = [(project["label"], project["total"]) for project in data.get("projects") or []]
    return bars("block.cost_projects", "项目费用排行", _top_bars(pairs, 5, "个项目"), sub=_month_label(ctx, " · 万元"),
                more="全部项目", to=drill_to("cost.projects", ctx),
                hint="按项目汇总的费用合计（研发分摊 + 采购 + 报销付款），前 5 名，其余合并。")


@provider("drill.cost.projects", "drill", visible=_can_cost, title="项目费用排行")
def drill_cost_projects(ctx):
    data = _overview(ctx)
    if not data:
        return None
    projects = sorted(data.get("projects") or [], key=lambda project: -float(project["total"] or 0))
    rows = [drill_row([project["label"], _amt(project["total"])]) for project in projects]
    total = sum(float(project["total"] or 0) for project in projects)
    return drill("drill.cost.projects", _month_label(ctx, "各项目的费用"), [("项目",), ("费用合计", "r")], rows,
                 summary=f"共 {len(projects)} 个项目，合计 {_amt(total)}",
                 note="研发分摊 + 采购 + 报销付款，口径同「费用合计」。")


@provider("block.alloc_mix", "block", visible=_can_alloc, title="分摊构成")
def block_alloc_mix(ctx):
    alloc = _allocation(ctx)
    parts = [("资本化", float(alloc.get("capitalized") or 0), GREEN), ("费用化", float(alloc.get("expensed") or 0), BLUE),
             ("未判定", float(alloc.get("unknown") or 0), ORANGE)]
    total = sum(amount for _label, amount, _color in parts)
    preview = bool(alloc.get("preview")) and not alloc.get("finalized")
    title = "分摊构成（预览）" if preview else "分摊构成"
    to = target("allocation", period=ctx.period)
    if total <= 0:
        return stack("block.alloc_mix", title, [], sub="本期还没有分摊数据", more="研发费用分摊", to=to)
    rows = [stack_row(label, f"{_wan(amount)} 万", _pct(amount, total), color) for label, amount, color in parts]
    return stack("block.alloc_mix", title, rows, sub=f"{int(ctx.period[5:])} 月 {_amt(total)}", more="研发费用分摊", to=to,
                 hint="研发分摊按阶段拆开：资本化 / 费用化 / 未判定（含境外委托研发）。")


# ================================================================ 付款
def _unpaid_target(items):
    """待付款的去处：报销、付款单在付款看板；只有采购付款时去采购付款页（待实际付款）。"""
    if items and all(item["kind"] == "采购付款" for item in items):
        return target("procpay.work", status="待实际付款")
    return target("board.payment")


def _waiting(items):
    return [item for item in items if item["waited"] > STUCK_DAYS]


@provider("pay.unpaid", "kpi", visible=_board_all, title="待付款")
def pay_unpaid(ctx):
    data = _pay(ctx)
    items = data["unpaid"]
    amount = sum(item["amount"] for item in items)
    urgent = sum(1 for item in items if item["urgent"])
    waiting = _waiting(items)
    number, unit = money_wan(amount)
    parts = [f"共 {len(items)} 笔" if items else "没有待付款的单据"]
    if urgent:
        parts.append(f"加急 {urgent} 笔")
    if waiting:
        parts.append(f"等待超过 {STUCK_DAYS} 天 {len(waiting)} 笔")
    return kpi("pay.unpaid", "待付款", number, unit, " · ".join(parts), "bad" if waiting else ("hot" if urgent else ""),
               to=_unpaid_target(items),
               hint="待付款 = 报销单、付款单状态「待办理」（只差出纳付款）+ 采购付款期次「待实际付款」"
                    + ("" if data["has_purchase"] else "（你没有 PO 查看权，不含采购付款）") + "。当前状态，不随期间变化。")


@provider("pay.waiting", "kpi", visible=_board_all, title="等待超过 3 天")
def pay_waiting(ctx):
    data = _pay(ctx)
    waiting = _waiting(data["unpaid"])
    number, unit = money_wan(sum(item["amount"] for item in waiting))
    sub = (f"{len(waiting)} 笔 · 最久已等 {max(item['waited'] for item in waiting)} 天"
           if waiting else f"没有等待超过 {STUCK_DAYS} 天的")
    return kpi("pay.waiting", f"等待超过 {STUCK_DAYS} 天", number, unit, sub, "bad" if waiting else "ok",
               to=_unpaid_target(waiting or data["unpaid"]),
               hint=f"待付款里，从最近一次审批通过（没有就从提交）算起已经等了超过 {STUCK_DAYS} 天（不含）的。系统里没有「逾期」口径，用等待时长代替。")


@provider("pay.in_approval", "kpi", visible=_board_all, title="付款审批中")
def pay_in_approval(ctx):
    data = _pay(ctx)
    items = data["approving"]
    counts = {name: sum(1 for item in items if item["bucket"] == name) for name in STEP_ORDER}
    breakdown = " · ".join(f"{name} {counts[name]}" for name in STEP_ORDER if counts[name])
    stuck = _waiting(items)
    return kpi("pay.in_approval", "付款审批中", len(items), "张", breakdown or "没有在审批的付款",
               "hot" if stuck else "", to=drill_to("pay.in_approval", ctx) if items else None,
               hint="报销单、付款单状态「待审批」+ 采购付款期次「付款审批中」；括号按当前审批节点的岗位拆（对不上的归「其他」）。"
                    "三种单据在三个页面里，点进去是合在一起的清单。")


_PAY_DETAIL_TARGET = {"报销单": "claim.detail", "付款单": "payment.detail", "采购付款": "procpay.approvals"}


@provider("drill.pay.in_approval", "drill", visible=_board_all, title="付款审批中")
def drill_pay_in_approval(ctx):
    items = sorted(_pay(ctx)["approving"], key=lambda item: -item["waited"])
    rows = [drill_row([item["kind"], item["name"], item["bucket"], _amt(item["amount"]), f"{item['waited']} 天"],
                      target(_PAY_DETAIL_TARGET[item["kind"]], request=item["name"]) if item["kind"] in _PAY_DETAIL_TARGET else None,
                      tone="bad" if item["waited"] > STUCK_DAYS else "")
            for item in items]
    return drill("drill.pay.in_approval", "付款审批中", [("类型",), ("单号",), ("现在在",), ("金额", "r"), ("已等", "r")], rows,
                 summary=f"共 {len(items)} 张，合计 {_amt(sum(item['amount'] for item in items))}",
                 note="报销单、付款单（待审批）+ 采购付款期次（付款审批中）；红色 = 等待超过 3 天。")


@provider("pay.paid_month", "kpi", visible=_board_all, title="本月已付")
def pay_paid_month(ctx):
    paid = _pay(ctx)["paid"]
    total = paid["claim_amount"] + paid["payment_amount"] + paid["purchase_amount"]
    count = paid["claim_count"] + paid["purchase_count"]
    number, unit = money_wan(total)
    parts = [f"{count} 笔", f"报销 {_amt(paid['claim_amount'])}", f"付款 {_amt(paid['payment_amount'])}"]
    if paid["has_purchase"]:
        parts.append(f"采购付款 {_amt(paid['purchase_amount'])}")
    return kpi("pay.paid_month", _month_label(ctx, "已付"), number, unit, " · ".join(parts), to=target("board.payment"),
               hint="按实际付款日期计入月份：报销单 + 付款单"
                    + ("" if not paid["has_purchase"] else " + 采购付款") + "。来源：付款看板。")


@provider("pay.cashier_queue", "kpi", visible=_board_all, title="出纳待付款")
def pay_cashier_queue(ctx):
    queue = [item for item in _pay(ctx)["unpaid"] if item["kind"] != "采购付款"]
    amount = sum(item["amount"] for item in queue)
    urgent = sum(1 for item in queue if item["urgent"])
    waiting = _waiting(queue)
    number, unit = money_wan(amount)
    parts = [f"{len(queue)} 张" if queue else "出纳这一步没有待付款的"]
    if urgent:
        parts.append(f"加急 {urgent} 张")
    if waiting:
        parts.append(f"等待超过 {STUCK_DAYS} 天 {len(waiting)} 张")
    return kpi("pay.cashier_queue", "出纳待付款", number, unit, " · ".join(parts), "bad" if waiting else ("hot" if urgent else ""),
               to=target("board.payment"), hint="报销单、付款单走到最后一步「出纳确认付款」、还没付的。采购付款的最后一步是总经理，不在这里。来源：付款看板的出纳待付款。")


def _todo_waits(queue, keys):
    waits = [queue["waited"].get(name, 0) for key in keys for name in queue[key]]
    return max(waits, default=0)


@provider("pay.todo", "kpi", visible=_always, title="付款待我处理")
def pay_todo(ctx):
    queue = _my_queue(ctx)
    count = len(queue["payment"]) + len(queue["procpay"]) + len(queue["verify"])
    longest = _todo_waits(queue, ("payment", "procpay", "verify"))
    parts = [f"付款单 {len(queue['payment'])}", f"采购付款 {len(queue['procpay'])}"]
    if queue["verify"]:
        parts.append(f"待核验发票 {len(queue['verify'])}")
    sub = " · ".join([*parts, f"最久已等 {longest} 天"]) if count else "没有等你处理的付款"
    # 付款单、采购付款、待核验发票在两个页面里，点进去是合在一起的清单（条数 = 卡片上的数字）
    return kpi("pay.todo", "付款待我处理", count, "张", sub, "hot" if count else "", to=drill_to("pay.todo", ctx) if count else None,
               hint="轮到我审批或办理的付款单、采购付款，加上财务的待核验发票（本人的待办）。点进去是合在一起的清单。")


_QUEUE_RECORD = {"报销单": "claim.detail", "付款单": "payment.detail", "采购付款": "procpay.approvals"}


def _queue_drill(ctx, key, title, groups, note):
    import frappe

    queue = _my_queue(ctx)
    kind_of = {"claim": "报销单", "payment": "付款单", "procpay": "采购付款", "verify": "付款单"}
    names = [(group, name) for group in groups for name in queue[group]]
    details = {}
    if names:
        for row in frappe.get_all("OA Approval Request", filters={"name": ["in", sorted({name for _group, name in names})]},
                                  fields=["name", "subject", "employee_name", "amount", "current_step_label"], limit_page_length=0):
            details[row["name"]] = row
    rows = []
    for group, name in sorted(names, key=lambda pair: (-queue["waited"].get(pair[1], 0), pair[1])):
        row = details.get(name, {})
        waited = queue["waited"].get(name, 0)
        where = "待核验发票" if group == "verify" else (row.get("current_step_label") or "—")
        rows.append(drill_row([kind_of[group], name, str(row.get("subject") or "").strip() or "—", row.get("employee_name") or "—",
                               _amt(row.get("amount") or 0), where, f"{waited} 天"], target(_QUEUE_RECORD[kind_of[group]], request=name),
                              tone="bad" if waited > STUCK_DAYS else ""))
    return drill(key, title, [("类型",), ("单号",), ("事由",), ("申请人",), ("金额", "r"), ("现在在",), ("已等", "r")], rows,
                 summary=f"共 {len(rows)} 张", note=note)


@provider("drill.pay.todo", "drill", visible=_always, title="付款待我处理")
def drill_pay_todo(ctx):
    return _queue_drill(ctx, "drill.pay.todo", "付款待我处理", ("payment", "procpay", "verify"),
                        "轮到我审批或办理的付款单、采购付款，加上财务的待核验发票；红色 = 等待超过 3 天。")


@provider("drill.my.queue", "drill", visible=_always, title="待处理账龄")
def drill_my_queue(ctx):
    return _queue_drill(ctx, "drill.my.queue", "待我处理的报销和付款", ("claim", "payment", "procpay", "verify"),
                        "轮到我审批或办理的报销单、付款单、采购付款，加上财务的待核验发票；等得久的在前，红色 = 超过 3 天。")


@provider("claim.todo", "kpi", visible=_always, title="报销待我审批")
def claim_todo(ctx):
    queue = _my_queue(ctx)
    count = len(queue["claim"])
    longest = _todo_waits(queue, ("claim",))
    return kpi("claim.todo", "报销待我审批", count, "张", f"最久已等 {longest} 天" if count else "没有等你审批的报销",
               "hot" if count else "", to=target("claim.todo"),
               hint="轮到我审批的报销单（本人的审批待办）；最久 = 从最近一次审批通过（没有就从提交）算起。")


@provider("me.processed", "kpi", visible=_always, title="本月已处理")
def me_processed(ctx):
    def load():
        import frappe
        first, last = _month_bounds(ctx.period)
        steps = frappe.get_all(
            "OA Approval Step",
            filters={"parenttype": "OA Approval Request", "action_by": ctx.user, "acted_on": ["between", [first, last]]},
            fields=["parent"], limit_page_length=0)
        names = sorted({step["parent"] for step in steps})
        kinds = {}
        if names:
            for row in frappe.get_all("OA Approval Request", filters={"name": ["in", names]},
                                      fields=["name", "request_type"], limit_page_length=0):
                kinds[row["request_type"]] = kinds.get(row["request_type"], 0) + 1
        return {"count": len(names), "kinds": kinds}

    done = ctx.memo("money.processed", load)
    short = {"报销单": "报销", "付款单": "付款"}
    parts = [f"{short.get(kind, kind)} {count}" for kind, count in sorted(done["kinds"].items(), key=lambda item: -item[1])]
    return kpi("me.processed", _month_label(ctx, "已处理"), done["count"], "张",
               " · ".join(parts) if parts else "这个月还没有处理过审批",
               hint="我在审批节点上签过批（审批、驳回、办理）的单据数，按签批日期算。")


@provider("alert.pay_waiting", "alert", visible=_board_all, title="付款等待太久")
def alert_pay_waiting(ctx):
    data = _pay(ctx)
    waiting = _waiting(data["unpaid"])
    if not waiting:
        return None
    longest = max(item["waited"] for item in waiting)
    cashier = sum(1 for item in waiting if item["kind"] != "采购付款")
    sub = f"最久已等 {longest} 天" + (f"，其中 {cashier} 笔在等出纳付款" if cashier else "，都在等总经理确认付款")
    return alert("alert.pay_waiting", "bad", f"{len(waiting)} 笔付款等了超过 {STUCK_DAYS} 天，合计 {_amt(sum(i['amount'] for i in waiting))}",
                 sub, "付款看板", _unpaid_target(waiting))


@provider("block.pay_wait_dist", "block", visible=_board_all, title="待付款按等待时长")
def block_pay_wait_dist(ctx):
    items = _pay(ctx)["unpaid"]
    groups = [("今天", GRAY, lambda days: days <= 0), (f"1–{STUCK_DAYS} 天", ORANGE, lambda days: 0 < days <= STUCK_DAYS),
              (f"超过 {STUCK_DAYS} 天", RED, lambda days: days > STUCK_DAYS)]
    total = sum(item["amount"] for item in items)
    to = _unpaid_target(items)
    if not items or total <= 0:
        return stack("block.pay_wait_dist", "待付款按等待时长", [], sub="没有待付款的单据", more="付款看板", to=to)
    rows = []
    for label, color, match in groups:
        part = [item for item in items if match(item["waited"])]
        amount = sum(item["amount"] for item in part)
        rows.append(stack_row(label, f"{_wan(amount)} 万 · {len(part)} 笔", _pct(amount, total), color))
    return stack("block.pay_wait_dist", "待付款按等待时长", rows, sub=f"待付款 {_amt(total)}", more="付款看板", to=to,
                 hint="从最近一次审批通过（没有就从提交）算起的等待天数：今天 / 1–3 天 / 超过 3 天。")


@provider("block.pay_steps", "block", visible=_board_all, title="付款审批卡在哪一步")
def block_pay_steps(ctx):
    items = _pay(ctx)["approving"]
    counts = {name: [item for item in items if item["bucket"] == name] for name in STEP_ORDER}
    top = max((len(part) for part in counts.values()), default=0)
    rows = []
    for name in STEP_ORDER:
        part = counts[name]
        if not part:
            continue
        tone = "bad" if _waiting(part) else ("warn" if len(part) == top and top > 1 else "")
        rows.append(bar_row(name, len(part), _pct(len(part), top), tone))
    return bars("block.pay_steps", "付款审批卡在哪一步", rows, sub=f"付款审批中 {len(items)} 张" if items else "没有在审批的付款",
                more="查看明细" if items else "", to=drill_to("pay.in_approval", ctx) if items else None,
                hint="按当前审批节点的岗位拆（审批人账号反查岗位，对不上的归「其他」）；标红 = 这一步有等待超过 3 天的。"
                     "报销/付款路线：出纳审核 → 直属主管 → 财务主管 → 副总/总经理；采购付款路线：副总 → 总账 → 财务主管 → 出纳 → 总经理。")


def _supplier_view(ctx):
    return _board_all(ctx) and _po_pay_view(ctx)


@provider("block.pay_suppliers", "block", visible=_supplier_view, title="应付最多的供应商")
def block_pay_suppliers(ctx):
    totals = {}
    for item in _pay(ctx)["payables"]:
        name = item["supplier"] or "（未填供应商）"
        totals[name] = totals.get(name, 0) + item["amount"]
    pairs = sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
    return bars("block.pay_suppliers", "应付最多的供应商", _top_bars(pairs, 5, "家", lambda index, _label: "bad" if index == 0 else ""),
                sub="采购付款还没付清 · 万元", more="采购付款", to=target("procpay.work"),
                hint="按供应商汇总采购付款期次的「金额 − 已付」；只含合同已生效的期次，不含已付清的。供应商是自由文本，同名（去掉首尾空格）合并。")


@provider("block.pay_stage", "block", visible=_supplier_view, title="付款类型")
def block_pay_stage(ctx):
    totals = {}
    for item in _pay(ctx)["unpaid"]:
        if item["kind"] == "采购付款":
            stage = item["stage"] or "（未填类型）"
            totals[stage] = totals.get(stage, 0) + item["amount"]
    pairs = sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
    return bars("block.pay_stage", "付款类型", _top_bars(pairs, 6, "类"), sub="采购付款待付款 · 万元", more="采购付款",
                to=target("procpay.work", status="待实际付款"),
                hint="采购付款期次「待实际付款」按付款类型（预付款、到货款、尾款、到货后全额付款）汇总。")


@provider("block.claim_category", "block", visible=_board_all, title="报销付款按类别")
def block_claim_category(ctx):
    pairs = [(label, amount) for label, amount in _pay(ctx)["by_account"]]
    return bars("block.claim_category", "报销付款按类别", _top_bars(pairs, 5, "类"), sub=_month_label(ctx, "已付 · 万元"),
                more="付款看板", to=target("board.payment"),
                hint="本期已付款的报销单、付款单，按费用明细的科目（一级 / 二级）汇总，前 5 名，其余合并。来源：付款看板。")


def _paid_by_month(ctx):
    """近 6 个月（含所选月份）每月已付金额：{"2026-05": 元}。报销单 + 付款单 + 采购付款，按实际付款日期。"""
    def load():
        import frappe
        from rayher_hr_payroll.oa_document_types import REQUEST_PROCUREMENT_PAYMENT

        year, month = int(ctx.period[:4]), int(ctx.period[5:7])
        start = date(year, month, 1)
        for _ in range(5):
            start = (start - timedelta(days=1)).replace(day=1)
        _first, last = _month_bounds(ctx.period)
        rows = frappe.get_all(
            "OA Approval Request",
            filters={"request_type": ["in", [*boards.CLAIM_TYPES, REQUEST_PROCUREMENT_PAYMENT]], "workflow_status": boards.PAID,
                     "paid_on": ["between", [start.isoformat(), last]]},
            fields=["amount", "paid_on"], limit_page_length=0)
        totals = {}
        for row in rows:
            key = boards.month_key(row.get("paid_on"))
            if key:
                totals[key] = totals.get(key, 0.0) + float(row.get("amount") or 0)
        return totals

    return ctx.memo("money.paid_by_month", load)


@provider("block.pay_trend", "block", visible=_board_all, title="近 6 个月已付金额")
def block_pay_trend(ctx):
    totals = _paid_by_month(ctx)
    if not any(totals.values()):
        return None
    year, month = int(ctx.period[:4]), int(ctx.period[5:7])
    months = []
    for _ in range(6):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    months.reverse()
    peak = max(totals.get(key, 0.0) for key in months) or 1
    rows = [col_row(f"{int(key[5:])}月", _wan(totals.get(key, 0.0)).replace(".0", ""), _pct(totals.get(key, 0.0), peak), key == ctx.period)
            for key in months]
    return cols("block.pay_trend", "近 6 个月已付金额", rows, sub="万元 · 报销 + 付款 + 采购付款", more="付款看板", to=target("board.payment"),
                hint="每月实际付出去的金额（按付款日期；报销单、付款单、采购付款合计）。")


@provider("block.aging", "block", visible=_always, title="待处理账龄")
def block_aging(ctx):
    queue = _my_queue(ctx)
    waits = [queue["waited"].get(name, 0) for key in ("claim", "payment", "procpay", "verify") for name in queue[key]]
    groups = [("1 天内", "", sum(1 for days in waits if days <= 1)),
              (f"2–{STUCK_DAYS} 天", "", sum(1 for days in waits if 2 <= days <= STUCK_DAYS)),
              (f"超过 {STUCK_DAYS} 天", "bad", sum(1 for days in waits if days > STUCK_DAYS))]
    top = max((count for _label, _tone, count in groups), default=0)
    rows = [bar_row(label, count, _pct(count, top), tone if count else "") for label, tone, count in groups]
    return bars("block.aging", "待处理账龄", rows, sub=f"报销 + 付款 · 张（共 {len(waits)}）" if waits else "没有等你处理的报销和付款",
                more="查看明细" if waits else "", to=drill_to("my.queue", ctx) if waits else None,
                hint="轮到我审批的报销单、付款单、采购付款，加上财务的待核验发票，按等待天数分组（从最近一次审批通过，没有就从提交算起）。")


# ================================================================ 审批卡点
# 一张卡住的单据点进去看什么：目标名 + 放单号的参数名。
_STUCK_RECORD = {
    "报销单": ("claim.detail", "request"), "付款单": ("payment.detail", "request"), "采购付款": ("procpay.approvals", "request"),
    "采购申请": ("procurement.detail", "request"), "购买申请": ("directpurchase.detail", "request"),
    "出差申请": ("travel.detail", "request"), "价格审批": ("price.approvals", "approval"),
}


def _stuck_record_target(item):
    spec = _STUCK_RECORD.get(item["type"])
    return target(spec[0], **{spec[1]: item["name"]}) if spec else None


@provider("drill.approval.stuck", "drill", visible=_board_all, title="审批卡点")
def drill_approval_stuck(ctx):
    items = sorted(_stuck(ctx), key=lambda item: -item["waited"])
    rows = [drill_row([item["type"], item["name"], item["step"] or "—", f"{item['waited']} 天"], _stuck_record_target(item),
                      tone="bad" if item["waited"] > 7 else "warn") for item in items]
    return drill("drill.approval.stuck", "审批卡点", [("类型",), ("单号",), ("卡在",), ("已等", "r")], rows,
                 summary=f"共 {len(items)} 张超过 {STUCK_DAYS} 天没处理",
                 note="待审批 / 待办理的单据里，从最近一次签批（没有就从提交）算起超过 3 天的；含报销、付款、采购申请、购买申请、出差申请、采购付款、价格审批；不含请假、加班、调休。")


@provider("approval.stuck", "kpi", visible=_board_all, title="审批卡点")
def approval_stuck(ctx):
    items = _stuck(ctx)
    sub = (f"超过 {STUCK_DAYS} 天没处理 · 最久 {max(item['waited'] for item in items)} 天"
           if items else f"没有超过 {STUCK_DAYS} 天的审批")
    return kpi("approval.stuck", "审批卡点", len(items), "张", sub, "hot" if items else "ok",
               to=drill_to("approval.stuck", ctx) if items else None,
               hint=f"待审批 / 待办理的单据里，从最近一次签批（没有就从提交）算起超过 {STUCK_DAYS} 天（不含）的。"
                    "含报销、付款、采购申请、购买申请、出差申请、采购付款、价格审批；不含请假、加班、调休。")


@provider("alert.stuck", "alert", visible=_board_all, title="审批卡住")
def alert_stuck(ctx):
    items = _stuck(ctx)
    if not items:
        return None
    oldest = max(items, key=lambda item: item["waited"])
    kinds = {}
    for item in items:
        kinds[item["type"]] = kinds.get(item["type"], 0) + 1
    where = f"最久卡在「{oldest['step']}」，已 {oldest['waited']} 天" if oldest["step"] else f"最久已 {oldest['waited']} 天"
    breakdown = "、".join(f"{kind} {count}" for kind, count in sorted(kinds.items(), key=lambda pair: -pair[1]))
    return alert("alert.stuck", "warn", f"{len(items)} 张审批超过 {STUCK_DAYS} 天没处理", f"{where}（{breakdown}）", "审批卡点", drill_to("approval.stuck", ctx))


# ================================================================ 发票
@provider("invoice.review", "kpi", visible=_can_invoice, title="发票待处理")
def invoice_review(ctx):
    data = _invoices(ctx)
    counts = data["counts"]
    confirm, dup, failed = counts.get("待确认", 0), counts.get("疑似重复", 0), counts.get("识别失败", 0)
    parts = [f"待确认 {confirm}" + (f"（超过 {INVOICE_STALE_DAYS} 天 {data['stale']}）" if data["stale"] else "")]
    if dup:
        parts.append(f"疑似重复 {dup}")
    if failed:
        parts.append(f"识别失败 {failed}")
    total = confirm + dup + failed
    return kpi("invoice.review", "发票待处理", total, "张", " · ".join(parts) if total else "没有待处理的发票",
               "hot" if data["stale"] or dup else "", to=drill_to("invoice.review", ctx) if total else None,
               hint=f"发票夹（全部发票）里状态为待确认、疑似重复、识别失败的张数；「超过 {INVOICE_STALE_DAYS} 天」按发票最后修改时间算。"
                    "点进去按状态分开列，每一行再进发票夹。")


@provider("drill.invoice.review", "drill", visible=_can_invoice, title="发票待处理")
def drill_invoice_review(ctx):
    data = _invoices(ctx)
    counts = data["counts"]
    spec = (("待确认", "allinv", f"其中超过 {INVOICE_STALE_DAYS} 天没确认的 {data['stale']} 张" if data["stale"] else "OCR 识别完，等人确认"),
            ("疑似重复", "dup", "和已有发票可能重复，要人工看"), ("识别失败", "allinv", "OCR 没识别出来，要手工补"))
    rows = [drill_row([name, counts.get(name, 0), note], target("invoice.folder", tab=tab), tone="hot" if name == "疑似重复" and counts.get(name, 0) else "")
            for name, tab, note in spec if counts.get(name, 0)]
    total = sum(counts.get(name, 0) for name, _tab, _note in spec)
    return drill("drill.invoice.review", "发票待处理", [("状态",), ("张数", "r"), ("说明",)], rows, summary=f"共 {total} 张")


@provider("alert.invoice", "alert", visible=_can_invoice, title="发票待处理")
def alert_invoice(ctx):
    data = _invoices(ctx)
    stale, dup = data["stale"], data["counts"].get("疑似重复", 0)
    if not (stale or dup):
        return None
    parts = []
    if stale:
        parts.append(f"{stale} 张发票待确认超过 {INVOICE_STALE_DAYS} 天")
    if dup:
        parts.append(f"{dup} 张发票疑似重复")
    return alert("alert.invoice", "warn", "，".join(parts), "", "发票明细", drill_to("invoice.review", ctx))


@provider("block.invoice_status", "block", visible=_can_invoice, title="发票状态")
def block_invoice_status(ctx):
    counts = _invoices(ctx)["counts"]
    spec = (("待确认", "warn"), ("疑似重复", "bad"), ("识别失败", "bad"), ("识别中", ""), ("可用", ""), ("已使用", ""))
    shown = [(name, counts.get(name, 0), tone) for name, tone in spec if counts.get(name, 0) or name in ("待确认", "可用")]
    top = max((count for _name, count, _tone in shown), default=0)
    rows = [bar_row(name, count, _pct(count, top), tone if count else "") for name, count, tone in shown]
    total = sum(count for _name, count, _tone in shown)
    return bars("block.invoice_status", "发票状态", rows if total else [], sub="发票夹 · 张" if total else "发票夹里还没有发票",
                more="发票夹", to=target("invoice.folder", tab="allinv"),
                hint="发票夹全部发票按状态统计（不含已排除）：待确认、疑似重复、识别失败、识别中、可用（已确认未使用）、已使用。")


# ================================================================ 人力成本
@provider("block.labor_cost", "block", visible=_can_labor, title="人力成本汇总")
def block_labor_cost(ctx):
    data = _labor(ctx)
    social = data["social"] + data["fund"]
    rows = [
        list_row("工资（应发合计）", "已提交的工资条" if data["gross"] else "本期还没有已提交的工资条",
                 _amt(data["gross"]) if data["gross"] else "—", tone="" if data["gross"] else "warn"),
        list_row("社保 + 公积金（公司承担）", "只含已确认的记录" if data["has_contributions"] else "本期还没有已确认的记录",
                 _amt(social) if data["has_contributions"] else "—", tone="" if data["has_contributions"] else "warn"),
        list_row("宿舍（公司承担）", "" if data["dorm_registered"] else "本期宿舍费用还没登记",
                 _amt(data["dorm_company"]) if data["dorm_registered"] else "—", tone="" if data["dorm_registered"] else "warn"),
    ]
    return listing("block.labor_cost", "人力成本汇总", rows, sub=f"{int(ctx.period[5:])} 月 · 不含个人明细", more="查看明细",
                   to=drill_to("cost.labor", ctx),
                   hint="只给汇总：工资 = 已提交工资条的应发合计；社保 + 公积金 = 公司承担、状态已确认的记录；宿舍 = 公司承担的宿舍费用。"
                        "三项来自三个不同的页面，点进去逐项列出来，再点各自的页面。")


@provider("drill.cost.labor", "drill", visible=_can_labor, title="人力成本汇总")
def drill_cost_labor(ctx):
    data = _labor(ctx)
    social = data["social"] + data["fund"]
    rows = [
        drill_row(["工资（应发合计）", "已提交的工资条" if data["gross"] else "本期还没有已提交的工资条", _amt(data["gross"]) if data["gross"] else "—"],
                  target("payroll", period=ctx.period)),
        drill_row(["社保 + 公积金（公司承担）", "员工记录里已确认的单位承担部分" if data["has_contributions"] else "本期还没有已确认的记录",
                   _amt(social) if data["has_contributions"] else "—"], target("social", period=ctx.period)),
        drill_row(["宿舍（公司承担）", "公司承担的宿舍费用" if data["dorm_registered"] else "本期宿舍费用还没登记",
                   _amt(data["dorm_company"]) if data["dorm_registered"] else "—"], target("dorm.board")),
    ]
    total = data["gross"] + (social if data["has_contributions"] else 0) + (data["dorm_company"] if data["dorm_registered"] else 0)
    rows.append(drill_row(["合计", "三项相加", _amt(total)], tone="hot"))
    return drill("drill.cost.labor", f"{int(ctx.period[5:])} 月人力成本由哪几项组成", [("项",), ("口径",), ("金额", "r")], rows,
                 summary=f"合计 {_amt(total)}", note="只给汇总，不含个人金额。社保 / 公积金信息页是按导入的 Excel 申报数据看的，口径和这里不同。")
