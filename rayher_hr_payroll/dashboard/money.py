"""财务、费用、付款和审批卡点的看板块（money）。

数据都来自现有接口，口径不另起炉灶：
- 费用：`overview_entry.get_cost_overview`（副总、总经理岗位，或 Accounts User / System Manager）；
  研发分摊：`allocation_entry.get_allocation`（Accounts User / System Manager；副总、总经理岗位只读，含境外委托研发）。
- 付款：报销单 + 付款单用付款看板同一套查询和归集（`expense_board_entry._rows/_decorate` + `expense_boards.payment_board`），
  采购付款期次用 `procurement_chain.list_payment_work_items`（只在有 PO 查看权时）。付款看板的范围规则：
  财务、管理层看全公司，其他人不返回。
- 已付：只有一个算法 `_paid`（报销单、付款单、旧的费用付款申请按费用明细价税合计，同首页费用概览）+ `_paid_purchase`
  （采购付款按单据金额，要有 PO 查看权）。本月已付、按类别、近 6 个月、费用里的报销付款都用它。
- 每个数字点进去看到的就是这个数字：页面列不出“正好这些”的，点进去是同一份数据的明细（drill.*）。
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
LEADER_POSITIONS = ("vice_manager", "general_manager")   # 总经理、副总经理：数字背后的页面都能只读打开（决定 2026-10-13）
PAID_CLAIM_TYPES = ("费用付款申请", *boards.CLAIM_TYPES)    # 同 overview_entry.COST_REQUEST_TYPES

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
    """分摊页（/allocation，能定版的那一页）：只有 Accounts User / System Manager。"""
    return ctx.can(*FINANCE_ROLES)


def _can_alloc_read(ctx):
    """读分摊数据（get_allocation / get_allocation_dashboard）：财务角色，或副总、总经理岗位只读（allocation_entry._require_read_access）。"""
    return ctx.can(*FINANCE_ROLES) or ctx.holds(*LEADER_POSITIONS)


def _alloc_target(ctx):
    """分摊数字点进去：财务去分摊页；副总、总经理去研发费用汇总（只读，同一份分摊数据）。"""
    if _can_alloc(ctx):
        return target("allocation", period=ctx.period)
    return target("cost.summary", period=ctx.period)


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
    这里只用待付款队列（当前状态）；已付金额、费用科目统一用 `_paid`，不再用看板按单据金额的合计。"""
    def load():
        from rayher_hr_payroll.api import expense_board_entry as board_entry

        today = _today(ctx)
        rows = board_entry._decorate(
            board_entry._rows(boards.CLAIM_TYPES, "all", "", (*boards.ACTIVE_STATUSES, boards.PAID)), today)
        return {"rows": rows, "board": boards.payment_board(rows, [], today=today)}

    return ctx.memo("money.claims", load)


def _purchase(ctx):
    """采购付款期次：没有 PO 查看权返回 None。{"items": 付款工作项, "waits": {付款单号: 等待天数}}。本期已付见 `_paid_purchase`。"""
    def load():
        if not _po_pay_view(ctx):
            return None
        import frappe
        from rayher_hr_payroll.api import expense_board_entry as board_entry, procurement_chain

        items = procurement_chain.list_payment_work_items(limit=1000) or []
        names = sorted({item["payment_request"] for item in items
                        if item.get("payment_request") and item.get("work_status") in ("待实际付款", "付款审批中")})
        waits = {}
        if names:
            rows = frappe.get_all("OA Approval Request", filters={"name": ["in", names]},
                                  fields=["name", "creation", "modified"], limit_page_length=0)
            waits = {row["name"]: row["waited_days"] for row in board_entry._decorate(rows, _today(ctx))}
        return {"items": items, "waits": waits}

    return ctx.memo("money.purchase", load)


def _paid(ctx, first, last):
    """[first, last] 里已付款的报销单、付款单、旧的费用付款申请（按实际付款日期）。「已付报销付款」只有这一个算法：
    每张单的金额 = 费用明细行的价税合计（没有就取金额）相加，和首页费用概览（overview_entry._expense_rows）同一口径；
    本月已付、按类别、近 6 个月已付、费用里的报销付款都从这里来，只是费用那边再去掉已含在研发分摊里的部分。
    {"docs": [{name, kind, subject, employee_name, paid_on, amount}], "lines": [{parent, project, amount, account}]}"""
    def load():
        import frappe

        rows = frappe.get_all(
            "OA Approval Request",
            filters={"request_type": ["in", list(PAID_CLAIM_TYPES)], "workflow_status": boards.PAID, "paid_on": ["between", [first, last]]},
            fields=["name", "request_type", "subject", "employee_name", "paid_on", "project"], limit_page_length=0)
        header = {row["name"]: row.get("project") or "" for row in rows}
        lines = []
        if rows:
            for line in frappe.get_all(
                    "OA Approval Expense Line", filters={"parent": ["in", list(header)]},
                    fields=["parent", "project_name", "claim_project", "total_amount", "amount", "expense_account_level_1", "expense_account_level_2"],
                    limit_page_length=0):
                account = " / ".join(part for part in (str(line.get("expense_account_level_1") or "").strip(),
                                                       str(line.get("expense_account_level_2") or "").strip()) if part) or "未填写"
                # 项目归属同费用概览：明细的所属项目 > 明细的项目名称 > 单据上的项目
                lines.append({"parent": line["parent"], "amount": float(line.get("total_amount") or line.get("amount") or 0), "account": account,
                              "project": line.get("claim_project") or line.get("project_name") or header.get(line["parent"]) or ""})
        totals = {}
        for line in lines:
            totals[line["parent"]] = totals.get(line["parent"], 0.0) + line["amount"]
        docs = [{"name": row["name"], "kind": row["request_type"], "subject": str(row.get("subject") or "").strip(),
                 "employee_name": str(row.get("employee_name") or ""), "paid_on": str(row.get("paid_on") or "")[:10],
                 "amount": totals.get(row["name"], 0.0)} for row in rows]
        return {"docs": docs, "lines": lines}

    return ctx.memo(f"money.paid:{first}:{last}", load)


def _paid_purchase(ctx, first, last):
    """同一期间已付款的采购付款单（没有费用明细，取单据金额）；没有 PO 查看权返回 None（和采购付款页同一个权限）。"""
    def load():
        if not _po_pay_view(ctx):
            return None
        import frappe
        from rayher_hr_payroll.oa_document_types import REQUEST_PROCUREMENT_PAYMENT

        rows = frappe.get_all(
            "OA Approval Request",
            filters={"request_type": REQUEST_PROCUREMENT_PAYMENT, "workflow_status": boards.PAID, "paid_on": ["between", [first, last]]},
            fields=["name", "subject", "employee_name", "paid_on", "amount"], limit_page_length=0)
        return [{"name": row["name"], "kind": REQUEST_PROCUREMENT_PAYMENT, "subject": str(row.get("subject") or "").strip(),
                 "employee_name": str(row.get("employee_name") or ""), "paid_on": str(row.get("paid_on") or "")[:10],
                 "amount": float(row.get("amount") or 0)} for row in rows]

    return ctx.memo(f"money.paid_po:{first}:{last}", load)


def _paid_month(ctx):
    """所选月份已付：{"docs": 报销/付款/费用付款申请 + 采购付款（有 PO 查看权时）, "has_purchase"}。"""
    first, last = _month_bounds(ctx.period)
    purchase = _paid_purchase(ctx, first, last)
    return {"docs": list(_paid(ctx, first, last)["docs"]) + list(purchase or []), "has_purchase": purchase is not None}


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

    unpaid：待付款（报销/付款单「待办理」+ 采购付款期次「待实际付款」）；approving：付款审批中。
    条目 {kind, name, request, po, amount, waited, urgent, bucket, supplier, stage}。本期已付见 `_paid_month`。"""
    def build():
        claims, purchase = _claims(ctx), _purchase(ctx)
        buckets = _step_buckets(ctx) if _step_buckets_needed(claims, purchase) else {}
        unpaid, approving = [], []
        for row in claims["board"]["cashier_queue"]:
            if row["status"] == "待付款":
                unpaid.append({"kind": row["request_type"], "name": row["name"], "request": row["name"], "po": "",
                               "amount": float(row["amount"]), "waited": int(row["waited_days"]), "urgent": row["urgency"] == "加急",
                               "supplier": "", "stage": ""})
        for row in claims["rows"]:
            if row["workflow_status"] == "待审批":
                approving.append({"kind": row["request_type"], "name": row["name"], "request": row["name"], "po": "",
                                  "amount": float(row.get("amount") or 0), "waited": int(row["waited_days"]), "urgent": False,
                                  "bucket": buckets.get(row["name"], "其他"), "supplier": "", "stage": ""})
        payables = []   # 采购付款里「合同已生效、还没付清」的期次，给供应商排行用
        for item in ((purchase or {}).get("items") or []):
            status, request = item.get("work_status"), item.get("payment_request") or ""
            amount = float(item.get("amount") or 0)
            owed = max(0.0, amount - float(item.get("paid_amount") or 0))
            entry = {"kind": "采购付款", "name": request or f"{item.get('po')}:{item.get('installment_no')}",
                     "request": request, "po": str(item.get("po") or ""), "amount": owed, "waited": int((purchase["waits"] or {}).get(request, 0)), "urgent": False,
                     "bucket": buckets.get(request, "其他"), "supplier": str(item.get("supplier") or "").strip(),
                     "stage": str(item.get("payment_stage") or "").strip()}
            if status == "待实际付款":
                unpaid.append(entry)
            elif status == "付款审批中":
                approving.append(dict(entry, amount=amount))
            if status not in ("已付款", "待合同生效") and owed > 0:
                payables.append(entry)
        return {"unpaid": unpaid, "approving": approving, "payables": payables, "has_purchase": purchase is not None}

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
            acted, submitted = {}, {}
            if approvals:
                for step in frappe.get_all("OA Approval Step", filters={"parent": ["in", [row["name"] for row in approvals]]},
                                           fields=["parent", "acted_on", "creation"], limit_page_length=0):
                    for stamps, value in ((acted, step.get("acted_on")), (submitted, step.get("creation"))):
                        day = boards.as_date(value)
                        if day and (step["parent"] not in stamps or day > stamps[step["parent"]]):
                            stamps[step["parent"]] = day
            for row in approvals:
                # 从最近一次签批算起；没人签过就从提交算起（提交时才生成审批步骤，步骤的创建时间就是提交时间），
                # 原来用单据的修改时间，改一下备注就会重新计时。
                started = acted.get(row["name"]) or submitted.get(row["name"]) or boards.as_date(row.get("modified"))
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
        # 工资只算已确认的工资条（决定 2026-10-13）；draft = 只有草稿工资条、还没确认的人数，作为进度提示
        return {"gross": float(pay.get("gross") or 0), "draft": int(pay.get("draft", 0) or 0),
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
        "费用合计 = 研发分摊 + 采购（PO 行金额合计，按下单日期）+ 报销付款（按实际付款日期）；已有研发分摊的月份，研发项目的采购和报销不重复计入；"
        "没定版的月份研发部分用预览。来源：首页费用概览。点进去看三部分各是多少。")


@provider("drill.cost.total", "drill", visible=_can_cost, title="费用合计")
def drill_cost_total(ctx):
    """三部分相加 = 指标卡上的费用合计；每一部分再点进去，看到的金额和这一行一样（采购、报销付款是同期间、同口径的明细）。"""
    data = _overview(ctx)
    if not data:
        return None
    totals = data["totals"]
    rows = [
        drill_row(["研发分摊", "工资、社保公积金、境外委托研发" + ("（预览，还没定版）" if data.get("preview") else ""), _amt(totals["rd"])],
                  target("cost.summary", period=ctx.period)),
        drill_row(["采购", "本期新下的 PO 行金额合计，按下单日期，不含已取消", _amt(totals["po"])], drill_to("cost.po", ctx)),
        drill_row(["报销付款", "本期已付款的报销单、付款单（价税合计），按实际付款日期", _amt(totals["expense"])], drill_to("cost.expense", ctx)),
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
                      "本期新下的 PO 行金额合计（不含已取消），按下单日期；不是付款额。已有研发分摊（含预览）的月份，研发项目的行不重复计入。"
                      "来源：首页费用概览。点进去按 PO 列出来，合计和这里一样。")


def _rd_dup_projects(ctx):
    """本期哪些项目的采购、报销已含在研发分摊里，费用合计不重复计入（口径同 overview_entry.cost_rows）：
    这个月已定版或用了预览，才去掉研发项目的行；否则空集合。"""
    def load():
        from rayher_hr_payroll.api import overview_entry as overview

        month = (int(ctx.period[:4]), int(ctx.period[5:7]))
        data = _overview(ctx) or {}
        allocated = ctx.period in (data.get("preview_months") or []) or month in overview._allocated_months([month])
        return frozenset(overview._rd_project_names()) if allocated else frozenset()

    return ctx.memo("money.rd_dup_projects", load)


_DUP_NOTE = "已经包含在研发分摊里（研发项目，这个月已有研发分摊），不计入合计，和卡片一样；单独列在最后，标“已含在研发分摊”。"


@provider("drill.cost.po", "drill", visible=_can_cost, title="采购（PO 金额）")
def drill_cost_po(ctx):
    """和 overview_entry._po_rows 同一个口径：本期创建、没取消的 PO，金额取物料行合计；
    已有研发分摊的月份，研发项目的行去掉（合计 = 卡片），去掉的部分单独列出来。"""
    import frappe
    from rayher_hr_payroll.api import overview_entry as overview

    start, end = overview.month_range([(int(ctx.period[:4]), int(ctx.period[5:7]))])
    pos = frappe.get_all("OA Purchase Order", filters={"status": ["not in", list(overview.PO_DEAD_STATUS)], "creation": ["between", [start, end]]},
                         fields=["name", "supplier", "status", "creation"], limit_page_length=0)
    dup = _rd_dup_projects(ctx) if pos else frozenset()
    kept, dropped = {}, {}
    if pos:
        for line in frappe.get_all("OA Purchase Order Line", filters={"parent": ["in", [po["name"] for po in pos]]},
                                   fields=["parent", "amount", "project"], limit_page_length=0):
            bucket = dropped if (line.get("project") or "") in dup else kept
            bucket[line["parent"]] = bucket.get(line["parent"], 0.0) + float(line.get("amount") or 0)
    counted = [po for po in pos if po["name"] in kept or po["name"] not in dropped]
    counted.sort(key=lambda po: -kept.get(po["name"], 0.0))

    def cells(po, amount, status):
        return [po["name"], str(po.get("supplier") or "").strip() or "—", status, str(po.get("creation"))[:10], _amt(amount)]

    rows = [drill_row(cells(po, kept.get(po["name"], 0.0), po.get("status") or ""), target("price.po", po=po["name"])) for po in counted]
    rows += [drill_row(cells(po, dropped[po["name"]], "已含在研发分摊"), target("price.po", po=po["name"]), tone="info")
             for po in sorted((po for po in pos if po["name"] in dropped), key=lambda po: -dropped[po["name"]])]
    total = sum(kept.values())
    note = f"另有研发项目的采购 {_amt(sum(dropped.values()))}" + _DUP_NOTE if dropped else ""
    return drill("drill.cost.po", _month_label(ctx, "新下的 PO"), [("PO",), ("供应商",), ("状态",), ("下单日",), ("PO 行金额", "r")], rows,
                 summary=f"共 {len(counted)} 个 PO，合计 {_amt(total)}", note=note)


@provider("cost.expense", "kpi", visible=_can_cost, title="报销")
def cost_expense(ctx):
    return _cost_card(ctx, "cost.expense", "报销付款（计入费用）", "expense", drill_to("cost.expense", ctx),
                      "本期已付款的报销单、付款单（含旧的费用付款申请），按费用明细的价税合计、实际付款日期；已有研发分摊（含预览）的月份，"
                      "研发项目的部分已在研发分摊里，不重复计入（所以可能比「已付」少）。来源：首页费用概览。点进去按单据列出来。")


_COST_DETAIL_TARGET = {"报销单": "claim.detail", "付款单": "payment.detail", "费用付款申请": "reimbursement.detail",
                       "采购付款": "procpay.approvals"}


def _paid_target(doc):
    key = _COST_DETAIL_TARGET.get(doc["kind"])
    return target(key, request=doc["name"]) if key else None


@provider("drill.cost.expense", "drill", visible=_can_cost, title="报销付款")
def drill_cost_expense(ctx):
    """和 overview_entry._expense_rows 同一个口径（同 `_paid`）：本期已付款的报销单、付款单、费用付款申请，金额取费用明细行合计；
    已有研发分摊的月份，研发项目的明细行去掉（合计 = 卡片），去掉的部分单独列出来。"""
    first, last = _month_bounds(ctx.period)
    paid = _paid(ctx, first, last)
    dup = _rd_dup_projects(ctx) if paid["lines"] else frozenset()
    dropped = {}
    for line in paid["lines"]:
        if line["project"] in dup:
            dropped[line["parent"]] = dropped.get(line["parent"], 0.0) + line["amount"]
    kept = {doc["name"]: doc["amount"] - dropped.get(doc["name"], 0.0) for doc in paid["docs"]}
    counted = [doc for doc in paid["docs"] if doc["name"] not in dropped or abs(kept[doc["name"]]) > 0.005]
    counted.sort(key=lambda doc: -kept[doc["name"]])

    def cells(doc, amount, kind):
        return [doc["name"], kind, doc["subject"] or "—", doc["employee_name"] or "—", doc["paid_on"], _amt(amount)]

    rows = [drill_row(cells(doc, kept[doc["name"]], doc["kind"]), _paid_target(doc)) for doc in counted]
    rows += [drill_row(cells(doc, dropped[doc["name"]], "已含在研发分摊"), _paid_target(doc), tone="info")
             for doc in sorted((doc for doc in paid["docs"] if doc["name"] in dropped), key=lambda doc: -dropped[doc["name"]])]
    total = sum(kept[doc["name"]] for doc in counted)
    note = f"另有研发项目的报销付款 {_amt(sum(dropped.values()))}" + _DUP_NOTE if dropped else ""
    return drill("drill.cost.expense", _month_label(ctx, "计入费用的报销和付款"),
                 [("单号",), ("类型",), ("事由",), ("申请人",), ("付款日",), ("金额", "r")], rows,
                 summary=f"共 {len(counted)} 张，合计 {_amt(total)}", note=note)


def _alloc_state(ctx):
    """研发分摊本期的状态，alloc.status 和 cost.rd_pending 都用这一个，不会一个说已定版、一个说预览。

    state：final = 有已提交的分摊单（财务主管定版）；preview = 没定版、按当前数据算出了预览；
    none = 既没定版也没有预览（还没有费用导入，或预览算不出来），这时最多只有境外委托研发。
    amount = 资本化 + 费用化 + 未判定（含境外委托研发），和分摊页 / 研发费用汇总的合计一样。"""
    alloc = _allocation(ctx)
    if alloc.get("finalized"):
        state = "final"
    elif alloc.get("preview"):
        state = "preview"
    else:
        state = "none"
    return {"state": state, "amount": sum(float(alloc.get(name) or 0) for name in ("capitalized", "expensed", "unknown")),
            "unknown": float(alloc.get("unknown") or 0), "has_data": bool(alloc.get("has_data")),
            "why": "有费用导入但预览算不出来" if alloc.get("preview_error") else "还没有费用导入"}


_ALLOC_STATES = "已定版 = 财务主管已提交分摊单；预览 = 还没定版，按当前数据现算；未定版 = 既没定版也算不出预览（还没有费用导入，或预览出错），这时只有境外委托研发。"


@provider("cost.rd_pending", "kpi", visible=_can_cost, title="本期研发分摊")
def cost_rd_pending(ctx):
    """状态为主，和 alloc.status 用同一个 `_alloc_state`；金额 = 点进去那一页的合计。"""
    state = _alloc_state(ctx)
    number, unit = money_wan(state["amount"])
    if not state["has_data"]:
        sub, tone = "本期还没有研发分摊数据", ""
    elif state["state"] == "preview":
        sub, tone = "预览，财务主管定版后才作数", "warn"
    elif state["state"] == "final":
        sub, tone = "已定版", "ok"
    else:
        sub, tone = f"未定版：{state['why']}，只有境外委托研发", "warn"
    return kpi("cost.rd_pending", "本期研发分摊", number, unit, sub, tone, to=_alloc_target(ctx),
               hint="本期研发分摊金额（资本化 + 费用化 + 未判定，含境外委托研发），和研发费用分摊页同一个数。" + _ALLOC_STATES,
               preview=state["state"] == "preview")


def _alloc_card(ctx, key, label, field, stage_label):
    alloc = _allocation(ctx)
    amount = float(alloc.get(field) or 0)
    number, unit = money_wan(amount)
    total = sum(float(alloc.get(name) or 0) for name in ("capitalized", "expensed", "unknown"))
    to = _alloc_target(ctx)
    if not alloc.get("has_data"):
        return kpi(key, label, "—", "", "本期还没有费用导入", to=to,
                   hint=f"{stage_label}。来源：研发费用分摊（含境外委托研发）。")
    if field == "capitalized":
        sub = f"占研发分摊 {_pct(amount, total):.0f}%"
    elif alloc.get("finalized"):
        sub = "已定版，仍有未判定的金额" if amount > 0 else "已定版，没有未判定的"
    else:
        sub = "定版前要确认" if amount > 0 else "没有未判定的"
    tone = ("hot" if amount > 0 else "ok") if field == "unknown" else ""
    return kpi(key, label, number, unit, sub, tone, to=to,
               hint=f"{stage_label}。来源：研发费用分摊（含境外委托研发，口径同分摊页）。", preview=bool(alloc.get("preview")))


@provider("cost.cap", "kpi", visible=_can_alloc_read, title="资本化")
def cost_cap(ctx):
    return _alloc_card(ctx, "cost.cap", "其中资本化", "capitalized", "研发分摊里判定为资本化的金额")


@provider("cost.unknown", "kpi", visible=_can_alloc_read, title="未判定")
def cost_unknown(ctx):
    return _alloc_card(ctx, "cost.unknown", "未判定", "unknown", "研发分摊里还没判定资本化 / 费用化的金额")


@provider("alloc.status", "kpi", visible=_can_alloc_read, title="研发分摊状态")
def alloc_status(ctx):
    """三种状态（已定版 / 预览 / 未定版），和 cost.rd_pending 同一个 `_alloc_state`。
    财务点进分摊页；副总、总经理只读，点进研发费用汇总。"""
    state = _alloc_state(ctx)
    to = _alloc_target(ctx)
    hint = "研发分摊本期的状态。" + _ALLOC_STATES + "未判定 = 还没判定资本化 / 费用化的金额。金额含境外委托研发，和点进去的页面一致。"
    if not state["has_data"]:
        return kpi("alloc.status", "研发分摊", "—", "", "本期还没有研发分摊数据", to=to, hint=hint)
    parts = [f"{int(ctx.period[5:])} 月 {_amt(state['amount'])}"]
    if state["state"] == "preview":
        value = "预览"
        parts.append("未定版")
    elif state["state"] == "final":
        value = "已定版"
    else:
        value = "未定版"
        parts.append(f"{state['why']}，只有境外委托研发")
    if state["unknown"] > 0:
        parts.append(f"未判定 {_amt(state['unknown'])}")
    tone = "ok" if state["state"] == "final" and state["unknown"] <= 0 else "warn"
    return kpi("alloc.status", "研发分摊", value, "", "，".join(parts), tone, to=to, hint=hint, preview=state["state"] == "preview")


@provider("alert.alloc_unknown", "alert", visible=_can_alloc_read, title="分摊未判定")
def alert_alloc_unknown(ctx):
    alloc = _allocation(ctx)
    unknown = float(alloc.get("unknown") or 0)
    if unknown <= 0:
        return None
    return alert("alert.alloc_unknown", "warn", f"分摊有 {_amt(unknown)} 费用未判定阶段",
                 "定版前需要确认" if not alloc.get("finalized") else "这个月已经定版，仍有未判定的金额",
                 "研发费用分摊" if _can_alloc(ctx) else "研发费用汇总", _alloc_target(ctx))


@provider("alert.alloc_preview", "alert", visible=_can_alloc_read, title="分摊仍是预览")
def alert_alloc_preview(ctx):
    alloc = _allocation(ctx)
    unknown = float(alloc.get("unknown") or 0)
    if not alloc.get("preview") or alloc.get("finalized") or unknown <= 0:
        return None
    return alert("alert.alloc_preview", "info", f"{int(ctx.period[5:])} 月研发分摊仍是预览",
                 f"还有 {_amt(unknown)} 未判定，定版前需要处理", "研发费用分摊" if _can_alloc(ctx) else "研发费用汇总", _alloc_target(ctx))


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
                more="按月明细" if trend else "", to=drill_to("cost.trend", ctx) if trend else None,
                hint="每月费用合计（研发分摊 + 采购 + 报销付款），没定版的月份研发部分是预览。点进去每个月一行，再点进那个月的费用合计。")


def _last_months(period, count):
    """所选月份往前 count 个月（含所选月份），从早到晚：["2026-05", …, "2026-10"]。"""
    year, month = int(period[:4]), int(period[5:7])
    months = []
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(months))


@provider("drill.cost.trend", "drill", visible=_can_cost, title="月度费用趋势")
def drill_cost_trend(ctx):
    """柱子上的每个月 = 一行，数字同费用概览的趋势；每行点进那个月的「费用合计」三部分。"""
    data = _overview(ctx)
    if not data:
        return None
    trend = list(data.get("trend") or [])[-6:]
    months = _last_months(ctx.period, len(trend))
    rows = [drill_row([item["label"] + ("（含预览）" if item.get("preview") else ""), _amt(item.get("rd") or 0), _amt(item.get("po") or 0),
                       _amt(item.get("expense") or 0), _amt(item["total"])], target("drill", item="cost.total", period=month),
                      tone="hot" if month == ctx.period else "")
            for month, item in zip(months, trend)]
    return drill("drill.cost.trend", "近 6 个月费用合计", [("月份",), ("研发分摊", "r"), ("采购", "r"), ("报销付款", "r"), ("合计", "r")], rows,
                 summary=f"共 {len(rows)} 个月", note="每月 = 研发分摊 + 采购 + 报销付款，口径同「费用合计」；点一行看那个月三部分的明细。")


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


@provider("block.alloc_mix", "block", visible=_can_alloc_read, title="分摊构成")
def block_alloc_mix(ctx):
    alloc = _allocation(ctx)
    parts = [("资本化", float(alloc.get("capitalized") or 0), GREEN), ("费用化", float(alloc.get("expensed") or 0), BLUE),
             ("未判定", float(alloc.get("unknown") or 0), ORANGE)]
    total = sum(amount for _label, amount, _color in parts)
    preview = bool(alloc.get("preview")) and not alloc.get("finalized")
    title = "分摊构成（预览）" if preview else "分摊构成"
    to = _alloc_target(ctx)
    more = "研发费用分摊" if _can_alloc(ctx) else "研发费用汇总"
    if total <= 0:
        return stack("block.alloc_mix", title, [], sub="本期还没有分摊数据", more=more, to=to)
    rows = [stack_row(label, f"{_wan(amount)} 万", _pct(amount, total), color) for label, amount, color in parts]
    return stack("block.alloc_mix", title, rows, sub=f"{int(ctx.period[5:])} 月 {_amt(total)}", more=more, to=to,
                 hint="研发分摊按阶段拆开：资本化 / 费用化 / 未判定（含境外委托研发）。")


# ================================================================ 付款
def _waiting(items):
    return [item for item in items if item["waited"] > STUCK_DAYS]


# 等待时长分三段，全公司同一个口径：今天（0 天）/ 1–3 天 / 超过 3 天（> 3，不含）。付款看板的出纳待付款也是这三段。
WAIT_BUCKETS = (("今天", GRAY, lambda days: days <= 0), (f"1–{STUCK_DAYS} 天", ORANGE, lambda days: 0 < days <= STUCK_DAYS),
                (f"超过 {STUCK_DAYS} 天", RED, lambda days: days > STUCK_DAYS))


def _wait_bucket(days):
    return next(label for label, _color, match in WAIT_BUCKETS if match(days))


_PAY_DETAIL_TARGET = {"报销单": "claim.detail", "付款单": "payment.detail", "采购付款": "procpay.approvals"}


def _pay_target(item):
    """一笔付款点进去：报销单、付款单进单据；采购付款进付款审批单，还没有付款单的期次进这个 PO 的付款工作项。"""
    if item["kind"] == "采购付款" and not item.get("request"):
        return target("procpay.work", po=item.get("po")) if item.get("po") else None
    key = _PAY_DETAIL_TARGET.get(item["kind"])
    return target(key, request=item.get("request") or item["name"]) if key else None


def _unpaid_drill(ctx, key, title, items, note):
    """待付款的清单（报销、付款单在付款看板，采购付款在采购付款页，没有一页列得全）：条数、合计、分段都和卡片 / 图表一样。"""
    items = sorted(items, key=lambda item: (-item["waited"], item["name"]))
    rows = [drill_row([item["kind"], item["name"], item["supplier"] or "—", _amt(item["amount"]), f"{item['waited']} 天",
                       _wait_bucket(item["waited"]) + ("，加急" if item["urgent"] else "")], _pay_target(item),
                      tone="bad" if item["waited"] > STUCK_DAYS else "")
            for item in items]
    split = " · ".join(f"{label} {sum(1 for item in items if match(item['waited']))} 笔" for label, _color, match in WAIT_BUCKETS)
    return drill(key, title, [("类型",), ("单号",), ("供应商",), ("金额", "r"), ("已等", "r"), ("等待",)], rows,
                 summary=f"共 {len(items)} 笔，合计 {_amt(sum(item['amount'] for item in items))}（{split}）", note=note)


_UNPAID_NOTE = ("报销单、付款单状态「待办理」（只差出纳付款）+ 采购付款期次「待实际付款」（金额 = 期次金额 − 已付）；"
                "已等 = 从最近一次审批通过（没有就从提交）算起的日历天数，红色 = 超过 3 天。")


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
    # 报销/付款单和采购付款在两个页面里，付款看板没有采购付款：点进去是合在一起的清单（条数 = 卡片上的数字）
    return kpi("pay.unpaid", "待付款", number, unit, " · ".join(parts), "bad" if waiting else ("hot" if urgent else ""),
               to=drill_to("pay.unpaid", ctx) if items else None,
               hint="待付款 = 报销单、付款单状态「待办理」（只差出纳付款）+ 采购付款期次「待实际付款」"
                    + ("" if data["has_purchase"] else "（你没有 PO 查看权，不含采购付款）") + "。当前状态，不随期间变化。点进去逐笔列出来。")


@provider("drill.pay.unpaid", "drill", visible=_board_all, title="待付款")
def drill_pay_unpaid(ctx):
    return _unpaid_drill(ctx, "drill.pay.unpaid", "待付款", _pay(ctx)["unpaid"], _UNPAID_NOTE)


@provider("pay.waiting", "kpi", visible=_board_all, title="等待超过 3 天")
def pay_waiting(ctx):
    data = _pay(ctx)
    waiting = _waiting(data["unpaid"])
    number, unit = money_wan(sum(item["amount"] for item in waiting))
    sub = (f"{len(waiting)} 笔 · 最久已等 {max(item['waited'] for item in waiting)} 天"
           if waiting else f"没有等待超过 {STUCK_DAYS} 天的")
    return kpi("pay.waiting", f"等待超过 {STUCK_DAYS} 天", number, unit, sub, "bad" if waiting else "ok",
               to=drill_to("pay.waiting", ctx) if waiting else None,
               hint=f"待付款里，从最近一次审批通过（没有就从提交）算起已经等了超过 {STUCK_DAYS} 天（不含）的。系统里没有「逾期」口径，用等待时长代替。"
                    "点进去正好是这几笔。")


@provider("drill.pay.waiting", "drill", visible=_board_all, title="等待超过 3 天的付款")
def drill_pay_waiting(ctx):
    return _unpaid_drill(ctx, "drill.pay.waiting", f"待付款里等待超过 {STUCK_DAYS} 天的", _waiting(_pay(ctx)["unpaid"]), _UNPAID_NOTE)


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


@provider("drill.pay.in_approval", "drill", visible=_board_all, title="付款审批中")
def drill_pay_in_approval(ctx):
    items = sorted(_pay(ctx)["approving"], key=lambda item: -item["waited"])
    rows = [drill_row([item["kind"], item["name"], item["bucket"], _amt(item["amount"]), f"{item['waited']} 天"], _pay_target(item),
                      tone="bad" if item["waited"] > STUCK_DAYS else "")
            for item in items]
    return drill("drill.pay.in_approval", "付款审批中", [("类型",), ("单号",), ("现在在",), ("金额", "r"), ("已等", "r")], rows,
                 summary=f"共 {len(items)} 张，合计 {_amt(sum(item['amount'] for item in items))}",
                 note="报销单、付款单（待审批）+ 采购付款期次（付款审批中）；红色 = 等待超过 3 天。")


_PAID_PARTS = (("报销单", "报销"), ("付款单", "付款"), ("费用付款申请", "费用付款申请（旧）"), ("采购付款", "采购付款"))
_PAID_HINT = ("按实际付款日期计入所选月份。报销单、付款单（含旧的费用付款申请）按费用明细的价税合计，和首页费用概览同一口径；"
              "采购付款按单据金额，要有 PO 查看权才计入。「报销付款按类别」「近 6 个月已付」也是这个算法；"
              "「费用合计」里的报销付款（计入费用）再去掉已含在研发分摊里的研发项目部分，所以可能比这里少。")


@provider("pay.paid_month", "kpi", visible=_board_all, title="本月已付")
def pay_paid_month(ctx):
    paid = _paid_month(ctx)
    docs = paid["docs"]
    number, unit = money_wan(sum(doc["amount"] for doc in docs))
    parts = [f"{len(docs)} 笔"]
    for kind, label in _PAID_PARTS:
        amount = sum(doc["amount"] for doc in docs if doc["kind"] == kind)
        # 报销、付款总是写出来；旧的费用付款申请有才写；采购付款有 PO 查看权才写
        if kind in boards.CLAIM_TYPES or (kind == "采购付款" and paid["has_purchase"]) or amount:
            parts.append(f"{label} {_amt(amount)}")
    # 付款看板只看当月、没有采购付款：点进去是所选月份逐笔的清单（合计 = 卡片上的数字）
    return kpi("pay.paid_month", _month_label(ctx, "已付"), number, unit, " · ".join(parts), to=drill_to("pay.paid", ctx),
               hint=_PAID_HINT + ("" if paid["has_purchase"] else "你没有 PO 查看权，不含采购付款。") + "点进去逐笔列出来。")


@provider("drill.pay.paid", "drill", visible=_board_all, title="本月已付")
def drill_pay_paid(ctx):
    paid = _paid_month(ctx)
    docs = sorted(paid["docs"], key=lambda doc: (doc["paid_on"], doc["name"]), reverse=True)
    rows = [drill_row([doc["kind"], doc["name"], doc["subject"] or "—", doc["employee_name"] or "—", doc["paid_on"], _amt(doc["amount"])],
                      _paid_target(doc)) for doc in docs]
    return drill("drill.pay.paid", _month_label(ctx, "已付"), [("类型",), ("单号",), ("事由",), ("申请人",), ("付款日",), ("金额", "r")], rows,
                 summary=f"共 {len(docs)} 笔，合计 {_amt(sum(doc['amount'] for doc in docs))}", note=_PAID_HINT)


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
               to=target("board.payment"),
               hint="报销单、付款单走到最后一步「出纳确认付款」、还没付的（不含已付款等核验发票的付款单）。采购付款的最后一步是总经理，不在这里。"
                    "和付款看板「出纳待付款」的张数、金额一样。")


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


def _processed(ctx):
    """我在所选月份签过批（审批、驳回、办理）的单据：{"count", "kinds": {类型: 张数}, "rows": [{name, kind, subject, employee_name, acted_on}]}。"""
    def load():
        import frappe
        first, last = _month_bounds(ctx.period)
        steps = frappe.get_all(
            "OA Approval Step",
            filters={"parenttype": "OA Approval Request", "action_by": ctx.user, "acted_on": ["between", [first, last]]},
            fields=["parent", "acted_on"], limit_page_length=0)
        acted = {}
        for step in steps:
            day = str(step.get("acted_on") or "")[:10]
            acted[step["parent"]] = max(acted.get(step["parent"], ""), day)
        names = sorted(acted)
        kinds, rows = {}, []
        if names:
            for row in frappe.get_all("OA Approval Request", filters={"name": ["in", names]},
                                      fields=["name", "request_type", "subject", "employee_name"], limit_page_length=0):
                kinds[row["request_type"]] = kinds.get(row["request_type"], 0) + 1
                rows.append({"name": row["name"], "kind": row["request_type"], "subject": str(row.get("subject") or "").strip(),
                             "employee_name": str(row.get("employee_name") or ""), "acted_on": acted.get(row["name"], "")})
        return {"count": len(names), "kinds": kinds, "rows": rows}

    return ctx.memo("money.processed", load)


@provider("me.processed", "kpi", visible=_always, title="本月已处理")
def me_processed(ctx):
    done = _processed(ctx)
    short = {"报销单": "报销", "付款单": "付款"}
    parts = [f"{short.get(kind, kind)} {count}" for kind, count in sorted(done["kinds"].items(), key=lambda item: -item[1])]
    return kpi("me.processed", _month_label(ctx, "已处理"), done["count"], "张",
               " · ".join(parts) if parts else "这个月还没有处理过审批", to=drill_to("me.processed", ctx) if done["count"] else None,
               hint="我在审批节点上签过批（审批、驳回、办理）的单据数，按签批日期算。点进去逐张列出来。")


# 我处理过的单据点进去看什么（审批中心各自的单据页）
_PROCESSED_RECORD = {
    "报销单": "claim.detail", "付款单": "payment.detail", "采购付款": "procpay.approvals", "采购申请": "procurement.detail",
    "购买申请": "directpurchase.detail", "出差申请": "travel.detail", "费用付款申请": "reimbursement.detail",
    "请假申请": "attendance.detail", "加班申请": "attendance.detail", "调休申请": "attendance.detail",
}


@provider("drill.me.processed", "drill", visible=_always, title="本月已处理")
def drill_me_processed(ctx):
    rows_in = sorted(_processed(ctx).get("rows") or [], key=lambda row: (row["acted_on"], row["name"]), reverse=True)
    rows = [drill_row([row["kind"], row["name"], row["subject"] or "—", row["employee_name"] or "—", row["acted_on"] or "—"],
                      target(_PROCESSED_RECORD[row["kind"]], request=row["name"]) if row["kind"] in _PROCESSED_RECORD else None)
            for row in rows_in]
    return drill("drill.me.processed", _month_label(ctx, "我处理过的单据"), [("类型",), ("单号",), ("事由",), ("申请人",), ("我最后签批",)], rows,
                 summary=f"共 {len(rows)} 张", note="我在审批节点上签过批（审批、驳回、办理）的单据，一张单签过几次也只算一张；按签批日期算。")


@provider("alert.pay_waiting", "alert", visible=_board_all, title="付款等待太久")
def alert_pay_waiting(ctx):
    data = _pay(ctx)
    waiting = _waiting(data["unpaid"])
    if not waiting:
        return None
    longest = max(item["waited"] for item in waiting)
    cashier = sum(1 for item in waiting if item["kind"] != "采购付款")
    sub = f"最久已等 {longest} 天" + (f"，其中 {cashier} 笔在等出纳付款" if cashier else "，都在等总经理确认付款")
    # 按钮写的就是点进去看到的：这几笔超过 3 天的付款（报销、付款单和采购付款合在一起的清单）
    return alert("alert.pay_waiting", "bad", f"{len(waiting)} 笔付款等了超过 {STUCK_DAYS} 天，合计 {_amt(sum(i['amount'] for i in waiting))}",
                 sub, f"超过 {STUCK_DAYS} 天的付款", drill_to("pay.waiting", ctx))


@provider("block.pay_wait_dist", "block", visible=_board_all, title="待付款按等待时长")
def block_pay_wait_dist(ctx):
    items = _pay(ctx)["unpaid"]
    total = sum(item["amount"] for item in items)
    if not items or total <= 0:
        return stack("block.pay_wait_dist", "待付款按等待时长", [], sub="没有待付款的单据")
    rows = []
    for label, color, match in WAIT_BUCKETS:
        part = [item for item in items if match(item["waited"])]
        amount = sum(item["amount"] for item in part)
        rows.append(stack_row(label, f"{_wan(amount)} 万 · {len(part)} 笔", _pct(amount, total), color))
    return stack("block.pay_wait_dist", "待付款按等待时长", rows, sub=f"待付款 {_amt(total)}", more="查看明细", to=drill_to("pay.unpaid", ctx),
                 hint="从最近一次审批通过（没有就从提交）算起的等待天数：今天 / 1–3 天 / 超过 3 天（> 3，不含）。"
                      "点进去是同一批待付款，每笔标了在哪一段；付款看板的出纳待付款也是这三段。")


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


def _category_pairs(ctx):
    """所选月份已付的报销付款按科目（一级 / 二级）汇总：[(科目, 金额, 张数)]，从大到小。和「本月已付」同一个 `_paid`。"""
    first, last = _month_bounds(ctx.period)
    amounts, docs = {}, {}
    for line in _paid(ctx, first, last)["lines"]:
        amounts[line["account"]] = amounts.get(line["account"], 0.0) + line["amount"]
        docs.setdefault(line["account"], set()).add(line["parent"])
    return [(label, amount, len(docs[label])) for label, amount in sorted(amounts.items(), key=lambda pair: (-pair[1], pair[0]))]


@provider("block.claim_category", "block", visible=_board_all, title="报销付款按类别")
def block_claim_category(ctx):
    pairs = [(label, amount) for label, amount, _count in _category_pairs(ctx)]
    # 付款看板只看当月：点进去是所选月份按科目的完整清单（合计 = 这几条加起来）
    return bars("block.claim_category", "报销付款按类别", _top_bars(pairs, 5, "类"), sub=_month_label(ctx, "已付 · 万元"),
                more="全部类别" if pairs else "", to=drill_to("pay.category", ctx) if pairs else None,
                hint="所选月份已付款的报销单、付款单（含旧的费用付款申请），按费用明细的科目（一级 / 二级）汇总价税合计，前 5 名，其余合并。"
                     "和「本月已付」的报销、付款部分同一个算法。")


@provider("drill.pay.category", "drill", visible=_board_all, title="报销付款按类别")
def drill_pay_category(ctx):
    pairs = _category_pairs(ctx)
    rows = [drill_row([label, f"{count} 张", _amt(amount)]) for label, amount, count in pairs]
    return drill("drill.pay.category", _month_label(ctx, "已付的报销付款按类别"), [("科目",), ("单据", "r"), ("金额", "r")], rows,
                 summary=f"共 {len(pairs)} 类，合计 {_amt(sum(amount for _label, amount, _count in pairs))}",
                 note="按费用明细行的科目汇总（一张单有几个科目会分别计入）；逐张的单据见「已付」明细。" + _PAID_HINT)


def _paid_months(ctx):
    """近 6 个月（含所选月份）每月已付：{"2026-05": {"claim": 元, "purchase": 元}}，和「本月已付」同一个算法（`_paid` + `_paid_purchase`）。"""
    months = _last_months(ctx.period, 6)
    first, last = f"{months[0]}-01", _month_bounds(ctx.period)[1]
    result = {month: {"claim": 0.0, "purchase": 0.0} for month in months}
    for part, docs in (("claim", _paid(ctx, first, last)["docs"]), ("purchase", _paid_purchase(ctx, first, last) or [])):
        for doc in docs:
            month = doc["paid_on"][:7]
            if month in result:
                result[month][part] += doc["amount"]
    return result


def _paid_by_month(ctx):
    """近 6 个月每月已付合计：{"2026-05": 元}。采购付款只在有 PO 查看权时计入（和「本月已付」一样）。"""
    def load():
        return {month: parts["claim"] + parts["purchase"] for month, parts in _paid_months(ctx).items()
                if parts["claim"] or parts["purchase"]}

    return ctx.memo("money.paid_by_month", load)


@provider("block.pay_trend", "block", visible=_board_all, title="近 6 个月已付金额")
def block_pay_trend(ctx):
    totals = _paid_by_month(ctx)
    if not any(totals.values()):
        return None
    months = _last_months(ctx.period, 6)
    peak = max(totals.get(key, 0.0) for key in months) or 1
    rows = [col_row(f"{int(key[5:])}月", _wan(totals.get(key, 0.0)).replace(".0", ""), _pct(totals.get(key, 0.0), peak), key == ctx.period)
            for key in months]
    return cols("block.pay_trend", "近 6 个月已付金额", rows, sub="万元 · 报销 + 付款" + (" + 采购付款" if _po_pay_view(ctx) else ""),
                more="按月明细", to=drill_to("pay.trend", ctx),
                hint="每月实际付出去的金额（按付款日期）：报销单、付款单按费用明细价税合计，采购付款按单据金额（要有 PO 查看权）。"
                     "和「本月已付」同一个算法；点进去每个月一行，再点进那个月逐笔的清单。")


@provider("drill.pay.trend", "drill", visible=_board_all, title="近 6 个月已付金额")
def drill_pay_trend(ctx):
    data = _paid_months(ctx)
    purchase = _po_pay_view(ctx)
    rows = []
    for month, parts in data.items():
        cells = [f"{int(month[5:])}月", _amt(parts["claim"])] + ([_amt(parts["purchase"])] if purchase else []) + [_amt(parts["claim"] + parts["purchase"])]
        rows.append(drill_row(cells, target("drill", item="pay.paid", period=month), tone="hot" if month == ctx.period else ""))
    columns = [("月份",), ("报销付款", "r")] + ([("采购付款", "r")] if purchase else []) + [("合计", "r")]
    return drill("drill.pay.trend", "近 6 个月已付金额", columns, rows,
                 summary=f"6 个月合计 {_amt(sum(parts['claim'] + parts['purchase'] for parts in data.values()))}",
                 note="点一行看那个月逐笔的清单。" + _PAID_HINT)


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
    # 发票夹给财务的单状态页签：confirm = 全部发票里的待确认，failed = 识别失败（原来都进“全部发票”，张数对不上）
    spec = (("待确认", "confirm", f"其中超过 {INVOICE_STALE_DAYS} 天没确认的 {data['stale']} 张" if data["stale"] else "OCR 识别完，等人确认"),
            ("疑似重复", "dup", "和已有发票可能重复，要人工看"), ("识别失败", "failed", "OCR 没识别出来，要手工补"))
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
def _wage_cells(data):
    """工资那一行：(说明, 金额)。只算已确认的工资条；还有没确认的写出人数（决定 2026-10-13，确认本月工资后才作数）。"""
    draft = int(data.get("draft", 0) or 0)
    if data["gross"]:
        return "已确认的工资条" + (f"；另有 {draft} 人没确认" if draft else ""), _amt(data["gross"])
    if draft:
        return f"还有 {draft} 人工资条没确认", f"—（还有 {draft} 人工资条没确认）"
    return "本期还没有已确认的工资条", "—"


@provider("block.labor_cost", "block", visible=_can_labor, title="人力成本汇总")
def block_labor_cost(ctx):
    data = _labor(ctx)
    social = data["social"] + data["fund"]
    wage_note, wage_value = _wage_cells(data)
    rows = [
        list_row("工资（应发合计）", wage_note, wage_value, tone="" if data["gross"] else "warn"),
        list_row("社保 + 公积金（公司承担）", "只含已确认的记录" if data["has_contributions"] else "本期还没有已确认的记录",
                 _amt(social) if data["has_contributions"] else "—", tone="" if data["has_contributions"] else "warn"),
        list_row("宿舍（公司承担）", "" if data["dorm_registered"] else "本期宿舍费用还没登记",
                 _amt(data["dorm_company"]) if data["dorm_registered"] else "—", tone="" if data["dorm_registered"] else "warn"),
    ]
    return listing("block.labor_cost", "人力成本汇总", rows, sub=f"{int(ctx.period[5:])} 月 · 不含个人明细", more="查看明细",
                   to=drill_to("cost.labor", ctx),
                   hint="只给汇总：工资 = 已确认工资条的应发合计（草稿不算，只显示还有几人没确认）；社保 + 公积金 = 公司承担、状态已确认的记录；宿舍 = 公司承担的宿舍费用。"
                        "三项来自三个不同的页面，点进去逐项列出来，再点各自的页面。")


@provider("drill.cost.labor", "drill", visible=_can_labor, title="人力成本汇总")
def drill_cost_labor(ctx):
    data = _labor(ctx)
    social = data["social"] + data["fund"]
    wage_note, wage_value = _wage_cells(data)
    rows = [
        drill_row(["工资（应发合计）", wage_note, wage_value], target("payroll", period=ctx.period)),
        drill_row(["社保 + 公积金（公司承担）", "员工记录里已确认的单位承担部分" if data["has_contributions"] else "本期还没有已确认的记录",
                   _amt(social) if data["has_contributions"] else "—"], target("social", period=ctx.period)),
        drill_row(["宿舍（公司承担）", "公司承担的宿舍费用" if data["dorm_registered"] else "本期宿舍费用还没登记",
                   _amt(data["dorm_company"]) if data["dorm_registered"] else "—"], target("dorm.board")),
    ]
    total = data["gross"] + (social if data["has_contributions"] else 0) + (data["dorm_company"] if data["dorm_registered"] else 0)
    rows.append(drill_row(["合计", "三项相加", _amt(total)], tone="hot"))
    return drill("drill.cost.labor", f"{int(ctx.period[5:])} 月人力成本由哪几项组成", [("项",), ("口径",), ("金额", "r")], rows,
                 summary=f"合计 {_amt(total)}", note="只给汇总，不含个人金额。社保 / 公积金信息页是按导入的 Excel 申报数据看的，口径和这里不同。")
