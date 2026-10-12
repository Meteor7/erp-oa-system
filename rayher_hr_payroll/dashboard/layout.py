"""每个岗位首页的版式：页签 → 指标卡 / 需要关注 / 图表块（用块的 key）。

块的内容、数据来源和权限判断在各 provider 模块里（money / people / timesheet / procurement / personal）。
这里只管"这个岗位按什么顺序放哪些块"；放进来的块如果当前这个人没权限，provider 会自己返回 None。
总览页签的 `todos: True` 表示第一屏左边放「要我处理」（key `todo.queue`，不缓存）。
设计依据：docs/superpowers/specs/2026-10-09-role-dashboard-design.md
"""


def tab(key, label, kpis=(), alerts=(), blocks=(), todos=False, sections=()):
    return {"key": key, "label": label, "kpis": list(kpis), "alerts": list(alerts), "blocks": list(blocks), "todos": todos,
            "sections": [dict(section) for section in sections]}


def section(title, sub="", kpis=(), blocks=()):
    """页签里的一段（小标题 + 自己的指标卡和图表块）。"""
    return {"title": title, "sub": sub, "kpis": list(kpis), "blocks": list(blocks)}


# 人事页签：人员 / 考勤 两段（考勤只有汇总，没有人名；点进考勤中心再点部门才看到人名）。
_PEOPLE_TAB = tab(
    "people", "人事",
    sections=[
        section("人员", "在职、合同、宿舍", kpis=["hr.active", "hr.joined_left", "hr.left_month"],
                blocks=["block.dept_headcount", "block.expiring_list", "block.dorm_summary"]),
        section("考勤", "只有人数和天数，不显示人名；要看是谁，点进考勤中心",
                kpis=["hr.away_today", "att.trip", "att.pending", "att.leave", "att.overtime", "att.rate"],
                blocks=["block.leave_types", "block.att_depts", "block.att_trend"]),
    ],
)


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
    _PEOPLE_TAB,
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
                blocks=["block.pay_steps", "block.pay_next30"], todos=True),
            tab("cash", "付款与现金", kpis=["pay.unpaid", "pay.waiting", "pay.in_approval", "pay.paid_month"],
                blocks=["block.pay_trend", "block.pay_suppliers", "block.pay_wait_dist", "block.pay_stage", "block.pay_steps", "block.pay_next30"]),
            tab("cost", "费用与分摊", kpis=["cost.total", "cost.rd", "cost.cap", "cost.unknown"],
                blocks=["block.cost_trend", "block.cost_mix", "block.alloc_mix", "block.cost_projects", "block.claim_category"]),
        ],
    },
    "finance_accountant": {
        "note": "记账、核对发票、跟进费用导入和分摊。",
        "tabs": [tab("overview", "总览", kpis=["claim.todo", "pay.todo", "invoice.review", "me.processed"],
                     alerts=["alert.invoice", "alert.alloc_unknown"], blocks=["block.aging", "block.invoice_status"], todos=True),
                 tab("invoice", "发票与报销", kpis=["invoice.review", "claim.todo"],
                     blocks=["block.invoice_status", "block.claim_category", "block.alloc_mix"])],
    },
    "finance_auditor": {
        "note": "要付谁、付多少、哪些等得太久。",
        "tabs": [tab("overview", "总览", kpis=["pay.cashier_queue", "pay.unpaid", "pay.waiting", "pay.paid_month"],
                     alerts=["alert.pay_waiting"], blocks=["block.pay_next30", "block.pay_wait_dist"], todos=True)],
    },
    "hr_manager": {
        "note": "人员、合同、考勤、薪酬社保和宿舍。",
        "tabs": [
            tab("overview", "总览",
                kpis=["hr.active", "hr.joined_left", "hr.away_today", "hr.expiring", "hr.payroll", "hr.social_pending", "hr.dorm_rate", "hr.file_pending"],
                alerts=["alert.att_pending", "alert.probation", "alert.payroll_draft", "alert.contract", "alert.dorm_lease", "alert.dorm_leaver", "alert.dorm_register", "alert.rd_gap"],
                blocks=["block.pay_progress", "block.dorm_summary", "block.dept_headcount"], todos=True),
            _PEOPLE_TAB,
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
                blocks=["block.week_cols", "block.proc_chain", "block.arrival_inspect"], todos=True),
            tab("analysis", "采购分析", kpis=["proc.month_amount", "proc.suppliers_count", "proc.to_inspect", "proc.month_inspected"],
                blocks=["block.proc_month_trend", "block.proc_suppliers", "block.proc_projects", "block.inspect_aging"]),
        ],
    },
    "pmc": {
        "note": "提 PR、盯物料到货、给物料编码。（这里不显示金额）",
        "tabs": [tab("overview", "总览",
                     kpis=["proc.await_pr", "proc.material_overdue", "proc.week_arrive", "proc.uncoded", "proc.po_transit", "proc.risk_projects", "me.approvals", "proc.price_pending"],
                     alerts=["alert.material_overdue", "alert.uncoded", "alert.risk_projects"],
                     blocks=["block.week_cols", "block.overdue_aging", "block.material_stage", "block.risk_projects"], todos=True)],
    },
    "production_asset_owner": {
        "note": "登记到货和验收，看本周要到什么货。",
        "tabs": [tab("overview", "总览",
                     kpis=["proc.to_arrive", "proc.to_inspect", "proc.week_arrive", "proc.po_overdue", "proc.exchange", "proc.return", "proc.month_inspected", "proc.month_arrived"],
                     alerts=["alert.inspect_stale", "alert.po_overdue"],
                     blocks=["block.week_cols", "block.inspect_aging", "block.week_schedule", "block.arrival_inspect"], todos=True)],
    },
    "dept_manager": {
        "note": "团队的审批、出勤、请假加班和工时。团队 = 汇报关系向下的在职员工。",
        "tabs": [
            tab("overview", "总览",
                kpis=["me.approvals", "team.away", "team.away2w", "ts.team", "team.leave", "team.overtime"],
                alerts=["alert.team_low_staff", "alert.ts_open_team"],
                blocks=["block.team_calendar", "block.team_leave_types"], todos=True),
            tab("team", "团队", kpis=["team.headcount", "team.leave", "team.overtime"],
                blocks=["block.team_people_hours", "block.ts_team"]),
            tab("ts", "工时", kpis=["ts.rate", "dept.projects", "ts.none"], blocks=["block.ts_projects", "block.ts_trend"]),
        ],
    },
    "employee": {
        "note": "我的待办、假期、申请、报销和工时。",
        "tabs": [tab("overview", "总览",
                     kpis=["me.annual", "me.comp", "me.overtime_month", "me.requests", "me.timesheet", "me.claim", "me.cc", "me.unread"],
                     alerts=["alert.me_timesheet", "alert.me_leave_unused"],
                     blocks=["block.me_strip", "block.me_balances", "block.me_requests", "block.me_timesheet"], todos=True)],
    },
}


# 多个身份拼在一起（决定 2026-10-12）：首页按优先级最高的岗位排版，再按他实际有的身份多加页签，互不覆盖——
# 有在职直接下属的多一个“团队”页，负责项目的多一个“我负责的项目”页。每个页签只用自己的范围：
# 团队页只给团队，项目页只给项目，不会因为他是主管就看到项目成员的考勤。
TEAM_TAB = tab(
    "team", "团队",
    kpis=["team.headcount", "team.away", "team.away2w", "team.leave", "team.overtime"],
    alerts=["alert.team_low_staff"],
    blocks=["block.team_calendar", "block.team_people_hours", "block.team_leave_types", "block.ts_team"],
)
PROJECT_TAB = tab(
    "projects", "我负责的项目",
    kpis=["prj.count", "prj.exec", "prj.sign"],
    blocks=["block.prj_stage", "block.prj_by_project", "block.prj_requests"],
)
# 这几个岗位首页本来就是公司级（或者在人事页看各部门汇总），不再另加团队页；部门主管版式里已经有团队页。
NO_EXTRA_TEAM_TAB = ("dept_manager", "general_manager", "vice_manager", "hr_manager")


def layout_for(ctx, layouts=None):
    """这个人的首页版式：岗位版式 + 他多出来的身份。"""
    layouts = layouts or LAYOUTS
    base = layouts[ctx.profile]
    tabs = list(base["tabs"])
    keys = {item["key"] for item in tabs}
    if ctx.has_reports and ctx.profile not in NO_EXTRA_TEAM_TAB and TEAM_TAB["key"] not in keys:
        tabs.append(TEAM_TAB)
    if ctx.owns_projects and PROJECT_TAB["key"] not in keys:
        tabs.append(PROJECT_TAB)
    return {**base, "tabs": tabs}


def _tab_keys(item):
    keys = set(item["kpis"]) | set(item["alerts"]) | set(item["blocks"])
    for part in item.get("sections", ()):
        keys.update(part["kpis"])
        keys.update(part["blocks"])
    return keys


def all_block_keys():
    keys = {"todo.queue"}
    for layout in LAYOUTS.values():
        for t in layout["tabs"]:
            keys.update(_tab_keys(t))
    for extra in (TEAM_TAB, PROJECT_TAB):
        keys.update(_tab_keys(extra))
    return keys
