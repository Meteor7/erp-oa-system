"""看板：我负责的项目（项目负责人，不管他还是不是部门主管 / 员工）。

项目里别人提的采购申请 / 购买申请都能看到进度（只读，不含别人没提交的草稿；价格、供应商不显示）。
数据走 `oa_entry.list_requests(view="all")`，和采购申请页面是同一个权限（`oa_access` 里项目负责人只读可见的规则），
再按“项目负责人 = 我”筛。只有项目里的采购进度，项目成员的考勤、工时不在这里（那是团队页的事，范围不同）。
"""
from __future__ import annotations

from rayher_hr_payroll.dashboard.core import (
    bar_row, bars, drill, drill_row, drill_to, kpi, list_row, listing, provider, stack, stack_row, target,
)

REQUEST_TYPES = ("采购申请", "购买申请")
STAGE_DEMAND, STAGE_EXEC, STAGE_DONE = "demand", "exec", "done"
STAGE_LABELS = {STAGE_DEMAND: "需求审批", STAGE_EXEC: "采购执行", STAGE_DONE: "已完成"}
STAGE_COLORS = {STAGE_DEMAND: "#8db4ee", STAGE_EXEC: "#f4c47a", STAGE_DONE: "#78c3a2"}
MAX_ROWS = 6
HINT = "只显示项目里的采购 / 购买申请进度，只读；没提交的草稿看不到，价格和供应商不显示。"


# ---------------------------------------------------------------- 取数（单独成函数，测试里替换）
def _load_requests(ctx):
    from rayher_hr_payroll.api import oa_entry

    rows = []
    for request_type in REQUEST_TYPES:
        rows += oa_entry.list_requests(view="all", request_type=request_type, limit=200)
    return rows


def _load_projects(ctx):
    import frappe

    return frappe.get_all(
        "Project", filters={"project_owner": ctx.user, "status": ["!=", "Cancelled"]},
        fields=["name", "project_name", "rd_project_code", "status"], limit_page_length=0,
    )


# ---------------------------------------------------------------- 整理
def stage_of(row):
    """一张申请走到哪一段：需求审批 / 采购执行 / 已完成。"""
    status = row.get("workflow_status")
    if status in ("待审批", "待办理"):
        return STAGE_DEMAND
    if status != "已完成":
        return None                      # 草稿、已驳回、已撤回不算进度
    if row.get("request_type") == "购买申请":
        return STAGE_DONE if row.get("business_status") == "已付款" else STAGE_EXEC
    stage = (row.get("procurement_chain") or {}).get("stage")
    if stage == "closed":
        return STAGE_DONE
    return STAGE_DEMAND if stage == "demand" else STAGE_EXEC


def _mine(ctx):
    """项目负责人是我、已提交的申请（草稿不看）：[(row, stage)]，最近的在前。"""
    def load():
        found = []
        for row in _load_requests(ctx):
            if row.get("project_owner") != ctx.user or row.get("workflow_status") == "草稿":
                continue
            stage = stage_of(row)
            if stage:
                found.append((row, stage))
        return sorted(found, key=lambda item: str(item[0].get("modified") or ""), reverse=True)
    return ctx.memo("prj.mine", load)


def _projects(ctx):
    return ctx.memo("prj.projects", lambda: _load_projects(ctx))


def _project_label(projects, key):
    for project in projects:
        if project.get("name") == key:
            return " · ".join(part for part in (project.get("rd_project_code"), project.get("project_name")) if part) or key
    return key or "非项目"


def visible(ctx):
    return bool(ctx.owns_projects)


def _counts(items):
    counts = {STAGE_DEMAND: 0, STAGE_EXEC: 0, STAGE_DONE: 0}
    for _row, stage in items:
        counts[stage] += 1
    return counts


# ---------------------------------------------------------------- 明细（采购申请和购买申请在两个页面里，数字是合起来的，所以点进去是合在一起的清单）
DETAIL_TARGET = {"采购申请": "procurement.detail", "购买申请": "directpurchase.detail"}


def _where(row, stage):
    if stage == STAGE_DEMAND:
        return row.get("current_step_label") or "需求审批"
    if row.get("request_type") == "采购申请":
        return (row.get("procurement_chain") or {}).get("label") or "采购执行"
    return row.get("business_status") or "待付款"


def _request_rows(ctx, items):
    projects = _projects(ctx)
    return [drill_row([row.get("name"), row.get("request_type"), row.get("subject") or "—", row.get("employee_name") or "—",
                       _project_label(projects, row.get("project")), STAGE_LABELS[stage], _where(row, stage)],
                      target(DETAIL_TARGET[row.get("request_type")], request=row.get("name")) if row.get("request_type") in DETAIL_TARGET else None,
                      tone="warn" if stage == STAGE_DEMAND else "") for row, stage in items]


REQUEST_COLUMNS = [("单号",), ("类型",), ("事由",), ("申请人",), ("项目",), ("阶段",), ("现在在",)]


@provider("drill.prj.requests", "drill", visible=visible, title="项目里的采购 / 购买申请")
def drill_prj_requests(ctx):
    items = _mine(ctx)
    return drill("drill.prj.requests", "我负责的项目里的采购 / 购买申请", REQUEST_COLUMNS, _request_rows(ctx, items), summary=f"共 {len(items)} 张",
                 note=HINT + " 采购申请和购买申请在两个页面里，这里合在一起。")


@provider("drill.prj.exec", "drill", visible=visible, title="采购执行中")
def drill_prj_exec(ctx):
    items = [(row, stage) for row, stage in _mine(ctx) if stage == STAGE_EXEC]
    return drill("drill.prj.exec", "采购执行中的申请", REQUEST_COLUMNS, _request_rows(ctx, items), summary=f"共 {len(items)} 张",
                 note="已批准、正在提 PR、比价、下 PO 或等付款的申请（购买申请：待付款 / 部分付款）。采购申请和购买申请在两个页面里，这里合在一起。")


@provider("drill.prj.sign", "drill", visible=visible, title="待我会签")
def drill_prj_sign(ctx):
    items = [(row, stage) for row, stage in _mine(ctx) if stage == STAGE_DEMAND and row.get("can_approve")]
    return drill("drill.prj.sign", "等我会签的申请", REQUEST_COLUMNS, _request_rows(ctx, items), summary=f"共 {len(items)} 张",
                 note="项目里别人提的申请，轮到你这个项目负责人会签；同一张申请你既是直属主管又是项目负责人时，同意一次即可。")


@provider("drill.prj.projects", "drill", visible=visible, title="我负责的项目")
def drill_prj_projects(ctx):
    projects = _projects(ctx)
    per_project = {}
    for row, stage in _mine(ctx):
        per_project.setdefault(row.get("project") or "", _counts([]))[stage] += 1
    rows = []
    for project in sorted(projects, key=lambda item: str(item.get("name"))):
        counts = per_project.get(project.get("name")) or _counts([])
        rows.append(drill_row([_project_label(projects, project.get("name")), project.get("status") or "—", counts[STAGE_DEMAND], counts[STAGE_EXEC], counts[STAGE_DONE]],
                              target("procurement.list", scope="owned")))
    return drill("drill.prj.projects", "我负责的项目", [("项目",), ("状态",), ("需求审批", "r"), ("采购执行", "r"), ("已完成", "r")], rows,
                 summary=f"共 {len(projects)} 个项目", note=HINT)


# ---------------------------------------------------------------- 指标卡
@provider("prj.count", "kpi", visible=visible, title="我负责的项目")
def prj_count(ctx):
    projects = _projects(ctx)
    items = _mine(ctx)
    return kpi("prj.count", "我负责的项目", len(projects), "个", f"共 {len(items)} 张采购 / 购买申请",
               to=drill_to("prj.projects", ctx) if projects else None, hint=HINT + " 点进去一个项目一行。")


@provider("prj.exec", "kpi", visible=visible, title="采购执行中")
def prj_exec(ctx):
    counts = _counts(_mine(ctx))
    return kpi("prj.exec", "采购执行中", counts[STAGE_EXEC], "张", f"需求审批中 {counts[STAGE_DEMAND]} · 已完成 {counts[STAGE_DONE]}",
               to=drill_to("prj.exec", ctx) if counts[STAGE_EXEC] else None,
               hint="已批准、正在提 PR、比价、下 PO 或等付款的申请（购买申请：待付款 / 部分付款）。" + HINT)


@provider("prj.sign", "kpi", visible=visible, title="待我会签")
def prj_sign(ctx):
    waiting = [row for row, stage in _mine(ctx) if stage == STAGE_DEMAND and row.get("can_approve")]
    return kpi("prj.sign", "待我会签", len(waiting), "张", waiting[0].get("subject") or "" if waiting else "没有要你会签的",
               "hot" if waiting else "", to=drill_to("prj.sign", ctx) if waiting else None,
               hint="项目里别人提的申请，轮到你这个项目负责人会签。同一张申请你既是直属主管又是项目负责人时，同意一次即可。")


# ---------------------------------------------------------------- 图表块
@provider("block.prj_stage", "block", visible=visible, title="项目里的申请走到哪一步")
def block_prj_stage(ctx):
    counts = _counts(_mine(ctx))
    total = sum(counts.values())
    if not total:
        return None
    rows = [stack_row(STAGE_LABELS[stage], f"{counts[stage]} 张", counts[stage] / total * 100, STAGE_COLORS[stage])
            for stage in (STAGE_DEMAND, STAGE_EXEC, STAGE_DONE) if counts[stage]]
    return stack("block.prj_stage", "项目里的申请走到哪一步", rows, sub=f"共 {total} 张", more="查看明细", to=drill_to("prj.requests", ctx), hint=HINT)


@provider("block.prj_requests", "block", visible=visible, title="最近的申请")
def block_prj_requests(ctx):
    projects = _projects(ctx)
    rows = []
    for row, stage in _mine(ctx)[:MAX_ROWS]:
        who = row.get("employee_name") or ""
        step = row.get("current_step_label") if stage == STAGE_DEMAND else ""
        sub = " · ".join(part for part in (who, _project_label(projects, row.get("project")), f"在 {step}" if step else "") if part)
        tone = "warn" if stage == STAGE_DEMAND else "ok" if stage == STAGE_DONE else "info"
        rows.append(list_row(row.get("subject") or row.get("name") or "（无主题）", sub, STAGE_LABELS[stage], tone,
                             target("procurement.detail", request=row.get("name"))))
    if not rows:
        return None
    return listing("block.prj_requests", "项目里最近的申请", rows, sub="只读", more="全部申请", to=drill_to("prj.requests", ctx), hint=HINT)


@provider("block.prj_by_project", "block", visible=visible, title="各项目的申请")
def block_prj_by_project(ctx):
    projects = _projects(ctx)
    by_project = {}
    for row, stage in _mine(ctx):
        by_project.setdefault(row.get("project") or "", []).append(stage)
    if not by_project:
        return None
    ranked = sorted(by_project.items(), key=lambda item: (-len(item[1]), item[0]))[:MAX_ROWS]
    biggest = len(ranked[0][1]) or 1
    rows = [bar_row(_project_label(projects, key), f"{len(stages)} 张 · 执行中 {sum(1 for s in stages if s == STAGE_EXEC)}", len(stages) / biggest * 100)
            for key, stages in ranked]
    return bars("block.prj_by_project", "各项目的申请", rows, sub="张", more="查看明细", to=drill_to("prj.projects", ctx), hint=HINT)
