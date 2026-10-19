from rayher_hr_payroll.position_access import position_users
import frappe
from frappe.utils import getdate, nowdate

from rayher_hr_payroll.api._guards import require_rd_access, parse_period, RD_FINANCE_ROLES

RD_TYPES = ("全时研发", "非全时研发", "研发辅助")


def _can_view_procurement_financial():
    # PMC、生产主管一律不给金额（PMC 带 Purchase User 角色，原来会拿到一组 0 金额；审查 #79-3），判断同采购链路
    from rayher_hr_payroll.api.procurement_chain import _amounts_hidden

    if _amounts_hidden():
        return False
    user = str(frappe.session.user or "").strip().lower()
    roles = set(frappe.get_roles(user) or [])
    return user in position_users("procurement_manager", "vice_manager", "general_manager") or bool(roles & {"System Manager", "Accounts User", "Purchase User", "Purchase Manager"})


def _procurement_overview():
    from rayher_hr_payroll.approval_center import dashboard
    from rayher_hr_payroll.api.procurement_chain import list_payment_work_items

    request_rows = dashboard("request", limit=500).get("rows") or []
    request_names = [row["name"] for row in request_rows if row.get("request_type") == "采购申请"]
    pr_sources = set(frappe.get_all("OA Procurement Request Line", filters={"source_request": ["in", request_names]}, pluck="source_request", limit_page_length=0)) if request_names else set()
    po_lines = frappe.get_all("OA Purchase Order Line", filters={"source_request": ["in", request_names]}, fields=["parent", "source_request", "quantity", "received_quantity", "inspection_status"], limit_page_length=0) if request_names else []
    po_names = sorted({row.parent for row in po_lines})
    pos = {row.name: row for row in frappe.get_all("OA Purchase Order", filters={"name": ["in", po_names]}, fields=["name", "status"], limit_page_length=0)} if po_names else {}
    financial_access = _can_view_procurement_financial()
    try:
        work_items = list_payment_work_items(limit=1000) or []
    except Exception as exc:
        if not isinstance(exc, (frappe.PermissionError, frappe.ValidationError)):
            raise
        work_items = []
    status_counts = {}
    for item in work_items:
        status = item.get("work_status") or "其他"
        status_counts[status] = status_counts.get(status, 0) + 1
    if financial_access:
        cards = [
            {"label": "进行中申请", "value": sum(1 for row in request_rows if row.get("workflow_status") not in {"已完成", "已拒绝"}), "route": "/approval/request-dashboard"},
            {"label": "待到货/资料", "value": status_counts.get("待到货资料", 0), "route": "/approval/procurement-payment", "filter": "待到货资料"},
            {"label": "待验收", "value": status_counts.get("待验收", 0), "route": "/approval/procurement-payment", "filter": "待验收"},
            {"label": "可提交付款", "value": status_counts.get("可提交付款审批", 0), "route": "/approval/procurement-payment", "filter": "可提交付款审批"},
            {"label": "付款审批中", "value": status_counts.get("付款审批中", 0) + status_counts.get("待实际付款", 0), "route": "/approval/payment-dashboard"},
        ]
    else:
        po_sources = {row.source_request for row in po_lines}
        cards = [
            {"label": "进行中申请", "value": sum(1 for row in request_rows if row.get("workflow_status") not in {"已完成", "已拒绝"}), "route": "/approval/request-dashboard"},
            {"label": "待提PR申请", "value": sum(1 for row in request_rows if row.get("workflow_status") == "已完成" and row["name"] not in pr_sources), "route": "/approval/request-dashboard"},
            {"label": "采购执行中", "value": sum(1 for name in pr_sources if name not in po_sources), "route": "/approval/request-dashboard"},
            {"label": "待到货物料", "value": sum(1 for row in po_lines if float(row.received_quantity or 0) < float(row.quantity or 0)), "route": "/approval/request-dashboard"},
            {"label": "待验收物料", "value": sum(1 for row in po_lines if float(row.received_quantity or 0) >= float(row.quantity or 0) and row.inspection_status != "已通过"), "route": "/approval/request-dashboard"},
            {"label": "已完成PO", "value": sum(1 for po in pos.values() if po.status == "已关闭"), "route": "/approval/request-dashboard"},
        ]
    amounts = {
        "po_total": sum(float(item.get("amount") or 0) for item in work_items),
        "paid": sum(float(item.get("paid_amount") or 0) for item in work_items),
    }
    amounts["unpaid"] = max(amounts["po_total"] - amounts["paid"], 0)
    amounts["payable"] = sum(float(item.get("amount") or 0) for item in work_items if item.get("can_push_payment"))
    # One payment period is one action item. Keep the first actionable blocker as
    # the headline and retain the rest as context, otherwise one PO becomes a
    # noisy list of near-duplicate alerts.
    action_items, grouped = [], {}
    for item in work_items:
        blockers = list(item.get("blockers") or [])
        if not blockers and not item.get("can_push_payment"):
            continue
        key = (item.get("po"), item.get("payment_plan_row"))
        grouped.setdefault(key, []).append(item)
    for key, items in grouped.items():
        item = items[0]
        blockers = []
        for row in items:
            for blocker in row.get("blockers") or []:
                if blocker not in blockers:
                    blockers.append(blocker)
        if blockers:
            headline = blockers[0]
            severity = "urgent" if any(word in headline for word in ("逾期", "不合格", "拒绝")) else "attention"
            action = "补齐资料" if "缺少" in headline else ("完成验收" if "验收" in headline else "查看付款条件")
            status = "阻塞"
        else:
            headline, severity, action, status = "本期条件已满足", "ready", "提交付款审批", "可办理"
        action_items.append({
            "key": ":".join(str(value or "") for value in key),
            "title": headline,
            "detail": f"{item.get('po')} · {item.get('installment_name') or '付款期次'}",
            "context": "、".join(blockers[1:]),
            "action": action,
            "status": status,
            "planned_date": item.get("planned_date") or "",
            "route": "/approval/procurement-payment", "po": item.get("po"),
            "severity": severity,
        })
        planned = item.get("planned_date")
        if planned:
            try:
                days = (getdate(nowdate()) - getdate(planned)).days
                action_items[-1]["overdue"] = days > 0 and status != "可办理"
                action_items[-1]["due_label"] = f"已逾期 {days} 天" if days > 0 and status != "可办理" else f"截止 {getdate(planned)}"
                if days > 0 and status != "可办理":
                    action_items[-1]["severity"] = "urgent"
            except (TypeError, ValueError):
                pass
    action_items.sort(key=lambda row: {"urgent": 0, "attention": 1, "ready": 2}.get(row["severity"], 9))
    stages = [
        {"key": "request", "label": "OA申请", "value": len(request_rows), "route": "/approval/request-dashboard"},
        {"key": "pr", "label": "PR/询价", "value": len(pr_sources), "route": "/approval/request-dashboard"},
        {"key": "po", "label": "PO/演示员工116", "value": len(po_names), "route": "/approval/request-dashboard"},
        {"key": "payment", "label": "付款", "value": len(work_items), "route": "/approval/procurement-payment"},
    ]
    return {"visible": bool(request_rows or work_items), "can_view_financial": financial_access,
            "cards": cards, "stages": stages, "action_items": action_items[:10],
            "amounts": amounts if financial_access else {}, "alerts": action_items[:10] if financial_access else []}


@frappe.whitelist()
def get_procurement_overview():
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.throw(frappe._("请先登录。"))
    return _procurement_overview()


@frappe.whitelist()
def get_dashboard(period):
    require_rd_access()
    year, month = parse_period(period)
    emps = frappe.get_all("Employee", fields=["name", "archive_status", "rd_personnel_type"])
    total = len(emps)
    confirmed = sum(1 for e in emps if (e.archive_status or "") == "已归档")
    pending = total - confirmed
    ledger = sum(1 for e in emps if (e.rd_personnel_type or "") in RD_TYPES)
    projects = frappe.db.count("Project", {"allow_rd_timesheet": 1})

    hrows = frappe.db.sql(
        """
        select ts.employee, sum(tsd.hours) as h
        from `tabTimesheet Detail` tsd inner join `tabTimesheet` ts on ts.name = tsd.parent
        inner join `tabEmployee` e on e.name = ts.employee
        inner join `tabProject` p on p.name = tsd.project
        where ts.docstatus = 1 and month(tsd.from_time) = %(m)s and year(tsd.from_time) = %(y)s
          and e.rd_personnel_type in %(t)s
          and coalesce(p.rd_project_code, '') != ''
        group by ts.employee
        """,
        {"m": month, "y": year, "t": RD_TYPES}, as_dict=True)
    hours_total = sum((r.h or 0) for r in hrows)
    filled = sum(1 for r in hrows if (r.h or 0) > 0)

    imp = frappe.db.get_value(
        "RD Expense Import", {"year": year, "month": month, "docstatus": ["<", 2]},
        "name", order_by="creation desc",
    )
    cost_items = 0
    cost_sum = 0.0
    if imp:
        items = frappe.get_all("RD Expense Item", filters={"parent": imp}, fields=["amount"])
        cost_items = len(items)
        cost_sum = sum((i.amount or 0) for i in items)

    period_canon = "%04d-%02d" % (year, month)
    dorms = frappe.get_all("Accommodation Deduction", filters={"period": period_canon}, fields=["total_amount"])
    dorm_count = len(dorms)
    dorm_sum = sum((d.total_amount or 0) for d in dorms)

    # salary aggregates are exposed only to finance roles (RD_FINANCE_ROLES)
    can_see_cost = bool(set(frappe.get_roles()) & set(RD_FINANCE_ROLES))
    alloc = (frappe.db.get_value("RD Cost Allocation", {"year": year, "month": month, "docstatus": 1},
                                 ["capitalized_total", "expensed_total", "unknown_total"],
                                 as_dict=True, order_by="creation desc") or {}) if can_see_cost else {}
    # 本月还没有定版（已提交）的分摊单、但有费用导入：用预览（按当前数据现算，只读）顶上，并标出 preview。
    preview = False
    if can_see_cost and imp and not alloc:
        preview_alloc = _preview_alloc_totals(period_canon, year, month)
        if preview_alloc is not None:
            alloc, preview = preview_alloc, True
    if can_see_cost:
        from rayher_hr_payroll.payroll_bridge import period_pay_totals
        pay = period_pay_totals(period_canon)
        gross = pay["gross"]
        deductions = pay["deductions"]
    else:
        cost_sum = 0
        cost_items = 0
        gross = 0
        deductions = 0

    return {
        "period": period,
        "kpi": {"total": total, "confirmed": confirmed, "ledger": ledger,
                "hours": hours_total, "projects": projects, "cost": cost_sum},
        "pipeline": {"emp": total, "ledger": ledger, "hours": hours_total, "cost": cost_sum},
        "todos": {"pending": pending, "filled": filled, "ledger": ledger,
                  "cost_items": cost_items, "dorm_count": dorm_count},
        "alloc": {"capitalized": alloc.get("capitalized_total") or 0,
                  "expensed": alloc.get("expensed_total") or 0,
                  "unknown": alloc.get("unknown_total") or 0},
        "preview": preview,
        "salary": {"gross": gross, "deductions": deductions},
    }


def _preview_alloc_totals(period, year, month):
    """没有定版时的三个阶段合计（预览）；算不出来返回 None。看板不能因为预览失败而打不开。"""
    from rayher_hr_payroll.rd_cost.allocation_preview import build_preview

    try:
        preview = build_preview(period, year, month)
    except Exception:
        return None
    if preview is None or preview.error or preview.doc is None:
        return None
    doc = preview.doc
    return {"capitalized_total": doc.capitalized_total, "expensed_total": doc.expensed_total,
            "unknown_total": doc.unknown_total}
