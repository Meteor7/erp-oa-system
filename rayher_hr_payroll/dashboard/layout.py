"""每个岗位首页的版式：页签 → 指标卡 / 需要关注 / 图表块（用块的 key）。

块的内容、数据来源和权限判断在各 provider 模块里（money / people / timesheet / procurement / personal）。
这里只管"这个岗位按什么顺序放哪些块"；放进来的块如果当前这个人没权限，provider 会自己返回 None。
总览页签的 `todos: True` 表示第一屏左边放「要我处理」（key `todo.queue`，不缓存）。
设计依据：docs/superpowers/specs/2026-10-09-role-dashboard-design.md
"""


def tab(key, label, kpis=(), alerts=(), blocks=(), todos=False):
    return {"key": key, "label": label, "kpis": list(kpis), "alerts": list(alerts), "blocks": list(blocks), "todos": todos}


_LEADER_OVERVIEW = tab(
    "overview", "总览",
    kpis=["cost.total", "pay.unpaid", "approval.stuck", "hr.active", "ts.rate", "alloc.status", "hr.expiring", "proc.po_transit"],
    alerts=["alert.pay_waiting", "alert.stuck", "alert.ts_open", "alert.inspect_stale", "alert.alloc_preview", "alert.rd_gap"],
    blocks=["block.cost_mix", "block.pay_wait_dist"],
    todos=True,
)
_LEADER_TABS = [
    _LEADER_OVERVIEW,
    tab("cost", "经营", kpis=["cost.total", "cost.rd", "cost.po", "cost.expense"],
        blocks=["block.cost_trend", "block.cost_projects", "block.pay_wait_dist", "block.proc_chain", "block.labor_cost"]),
    tab("people", "人事", kpis=["hr.active", "hr.joined_left", "hr.left_month", "hr.away_today"],
        blocks=["block.dept_headcount", "block.leave_types", "block.expiring_list", "block.dorm_summary"]),
    tab("rd", "研发", kpis=["ts.rate", "ts.rd_count", "cost.rd_pending", "hr.rd_gap"],
        blocks=["block.ts_by_dept", "block.alloc_mix"]),
]

LAYOUTS = {
    "general_manager": {"note": "公司整体 + 要你终审的事，一屏看全。", "tabs": _LEADER_TABS},
    "vice_manager": {"note": "公司整体 + 要你审批的事，一屏看全。", "tabs": _LEADER_TABS},
    "finance_manager": {
        "note": "钱的进出和费用分摊。",
        "tabs": [
            tab("overview", "总览",
                kpis=["pay.unpaid", "pay.waiting", "pay.in_approval", "cost.total", "alloc.status", "claim.todo", "invoice.review", "pay.paid_month"],
                alerts=["alert.pay_waiting", "alert.alloc_unknown", "alert.invoice", "alert.stuck"],
                blocks=["block.pay_steps", "block.pay_wait_dist"], todos=True),
            tab("cash", "付款与现金", kpis=["pay.unpaid", "pay.waiting", "pay.in_approval", "pay.paid_month"],
                blocks=["block.pay_wait_dist", "block.pay_suppliers", "block.pay_stage", "block.pay_steps"]),
            tab("cost", "费用与分摊", kpis=["cost.total", "cost.rd", "cost.cap", "cost.unknown"],
                blocks=["block.cost_mix", "block.alloc_mix", "block.cost_projects", "block.claim_category"]),
        ],
    },
    "finance_accountant": {
        "note": "记账、核对发票、跟进费用导入和分摊。",
        "tabs": [tab("overview", "总览", kpis=["claim.todo", "pay.todo", "invoice.review", "me.processed"],
                     alerts=["alert.invoice", "alert.alloc_unknown"], blocks=["block.invoice_status", "block.aging"], todos=True)],
    },
    "finance_auditor": {
        "note": "要付谁、付多少、哪些等得太久。",
        "tabs": [tab("overview", "总览", kpis=["pay.cashier_queue", "pay.unpaid", "pay.waiting", "pay.paid_month"],
                     alerts=["alert.pay_waiting"], blocks=["block.pay_wait_dist"], todos=True)],
    },
    "hr_manager": {
        "note": "人员、合同、考勤、薪酬社保和宿舍。",
        "tabs": [
            tab("overview", "总览",
                kpis=["hr.active", "hr.joined_left", "hr.away_today", "hr.expiring", "hr.payroll", "hr.social_pending", "hr.dorm_rate", "hr.file_pending"],
                alerts=["alert.probation", "alert.payroll_draft", "alert.contract", "alert.dorm_lease", "alert.dorm_leaver", "alert.dorm_register", "alert.rd_gap"],
                blocks=["block.pay_progress", "block.dorm_summary", "block.dept_headcount"], todos=True),
            tab("people", "人事", kpis=["hr.active", "hr.joined_left", "hr.left_month", "hr.away_today"],
                blocks=["block.dept_headcount", "block.leave_types", "block.expiring_list", "block.dorm_summary"]),
            tab("pay", "薪酬与社保", kpis=["hr.payroll", "hr.pay_total", "hr.pay_si", "hr.pay_hf"],
                blocks=["block.pay_progress", "block.si_hf_list", "block.pay_by_dept"]),
            tab("dorm", "宿舍", kpis=["hr.dorm_rate", "hr.dorm_vacant", "hr.dorm_lease", "hr.dorm_leaver"],
                blocks=["block.dorm_cost", "block.dorm_split", "block.dorm_buildings", "block.dorm_lease_list"]),
        ],
    },
    "procurement_manager": {
        "note": "比价、PO、到货、供应商和付款提交。",
        "tabs": [
            tab("overview", "总览",
                kpis=["proc.to_compare", "proc.price_pending", "proc.po_transit", "proc.po_overdue", "proc.ready_to_pay", "proc.pay_planned_passed", "proc.month_amount", "proc.uncoded"],
                alerts=["alert.po_overdue", "alert.pay_planned_passed", "alert.price_missing_quote", "alert.uncoded"],
                blocks=["block.proc_chain", "block.arrival_inspect"], todos=True),
            tab("analysis", "采购分析", kpis=["proc.month_amount", "proc.suppliers_count", "proc.to_inspect", "proc.month_inspected"],
                blocks=["block.proc_suppliers", "block.proc_projects", "block.arrival_inspect"]),
        ],
    },
    "pmc": {
        "note": "提 PR、盯物料到货、给物料编码。（这里不显示金额）",
        "tabs": [tab("overview", "总览",
                     kpis=["proc.await_pr", "proc.material_overdue", "proc.week_arrive", "proc.uncoded", "proc.po_transit", "proc.risk_projects", "me.approvals", "proc.price_pending"],
                     alerts=["alert.material_overdue", "alert.uncoded", "alert.risk_projects"],
                     blocks=["block.material_stage", "block.risk_projects"], todos=True)],
    },
    "production_asset_owner": {
        "note": "登记到货和验收，看本周要到什么货。",
        "tabs": [tab("overview", "总览",
                     kpis=["proc.to_arrive", "proc.to_inspect", "proc.week_arrive", "proc.po_overdue", "proc.exchange", "proc.return", "proc.month_inspected", "proc.month_arrived"],
                     alerts=["alert.inspect_stale", "alert.po_overdue"],
                     blocks=["block.week_schedule", "block.arrival_inspect"], todos=True)],
    },
    "dept_manager": {
        "note": "本部门的审批、工时、出勤和加班。",
        "tabs": [tab("overview", "总览",
                     kpis=["me.approvals", "ts.team", "dept.away2w", "dept.active", "dept.overtime", "dept.leave", "dept.projects", "ts.none"],
                     alerts=["alert.ts_open_team", "alert.dept_attendance"],
                     blocks=["block.ts_team", "block.ts_projects"], todos=True)],
    },
    "employee": {
        "note": "我的待办、假期、申请、报销和工时。",
        "tabs": [tab("overview", "总览",
                     kpis=["me.annual", "me.comp", "me.overtime_month", "me.requests", "me.timesheet", "me.claim", "me.cc", "me.unread"],
                     alerts=["alert.me_timesheet", "alert.me_leave_unused"],
                     blocks=["block.me_requests", "block.me_timesheet"], todos=True)],
    },
}


def all_block_keys():
    keys = {"todo.queue"}
    for layout in LAYOUTS.values():
        for t in layout["tabs"]:
            keys.update(t["kpis"])
            keys.update(t["alerts"])
            keys.update(t["blocks"])
    return keys
