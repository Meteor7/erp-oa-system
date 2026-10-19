from datetime import date, datetime

import frappe

try:
    from frappe.utils import getdate
except (ImportError, AttributeError):
    # Unit tests may install a minimal frappe stub. Keep this pure classifier
    # usable without requiring the full frappe.utils package.
    def getdate(value):
        if isinstance(value, date):
            return value
        return datetime.fromisoformat(str(value)).date()


def _stage(doc, ym):
    """R&D stage of period `ym` (YYYYMM) for a project. Prefer the explicit
    backend rd_stage; fall back to the legacy capitalization date window."""
    explicit = (getattr(doc, "rd_stage", None) or "").strip() if doc else ""
    if explicit == "资本化":
        return "capitalized"
    if explicit == "费用化":
        return "expensed"
    s = doc.capitalization_start_date if doc else None
    e = doc.capitalization_end_date if doc else None
    if not (s and e):
        return "unknown"
    # Classify EXACTLY like rd_cost.frappe_adapter.stage_for_period: the actual
    # dates vs the first day of the period month, not a YYYYMM collapse. A
    # within-month shift of the start/end date (e.g. 2026-01-01 -> 2026-01-15)
    # changes the allocation stage, so the lock must detect it too.
    current = date(int(ym[:4]), int(ym[4:6]), 1)
    s, e = getdate(s), getdate(e)
    return "capitalized" if s <= current <= e else "expensed"


def _has_rd_hours(project, ym):
    """True if the project has SUBMITTED timesheet hours in period ym (YYYYMM)."""
    return bool(frappe.db.sql(
        """select 1 from `tabTimesheet Detail` tsd
           inner join `tabTimesheet` ts on ts.name = tsd.parent and ts.docstatus = 1
           inner join `tabEmployee` e on e.name = ts.employee
           where tsd.project = %(p)s and date_format(tsd.from_time, '%%Y%%m') = %(ym)s
             and e.rd_personnel_type in ('全时研发','非全时研发','研发辅助')
           limit 1""",
        {"p": project, "ym": ym},
    ))


def guarded_rd_periods(frappe_module):
    """(阶段锁定的期间, 已提交分摊的期间)，都是 YYYYMM。

    修复（2026-09-29，审查 X2-5）：原来只看 RD Period Lock；分摊提交后没有锁定期间时，
    员工的研发人员类型、项目的研发编号还能改，改完后这些工时不再被冻结，撤销重算时结果也变了。
    frappe 由调用方传入，测试替身不会被别的测试里导入的模块全局变量覆盖。
    """
    locked = set()
    for lk in frappe_module.get_all(
        "RD Period Lock",
        filters={"docstatus": 1, "lock_project_stage": 1},
        fields=["period"],
        limit_page_length=0,
    ):
        ym = "".join(c for c in str(getattr(lk, "period", "") or "") if c.isdigit())[:6]
        if len(ym) == 6:
            locked.add(ym)
    allocated = set()
    for row in frappe_module.get_all(
        "RD Cost Allocation",
        filters={"docstatus": 1},
        fields=["year", "month"],
        limit_page_length=0,
    ):
        year = row.get("year") if isinstance(row, dict) else getattr(row, "year", None)
        month = row.get("month") if isinstance(row, dict) else getattr(row, "month", None)
        if year and month:
            allocated.add("%04d%02d" % (int(year), int(month)))
    return locked, allocated


def _rd_code(doc):
    value = doc.get("rd_project_code") if isinstance(doc, dict) else getattr(doc, "rd_project_code", None)
    return str(value or "").strip()


PROCUREMENT_APPLICATION_TYPES = ("采购申请", "购买申请")


def sync_request_project_owner(doc, method=None):
    """项目负责人换人以后，这个项目名下的采购申请 / 购买申请跟着换成现在的负责人（决定 2026-10-12）。

    申请上的“项目负责人”是提交时记下的；不跟着换，新负责人看不到老申请、旧负责人却还看得到，
    后面的演示员工116交期确认等节点也会找错人。已经走过的审批节点不动（那是当时谁批的）。
    """
    before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
    if before is None:
        return 0
    old = str(getattr(before, "project_owner", "") or "").strip()
    new = str(getattr(doc, "project_owner", "") or "").strip()
    if old == new:
        return 0
    frappe.db.sql(
        "UPDATE `tabOA Approval Request` SET project_owner = %(owner)s, project_owner_name = %(name)s "
        "WHERE project = %(project)s AND request_type IN %(types)s",
        {"owner": new or None, "name": str(getattr(doc, "project_owner_name", "") or "") or None,
         "project": doc.name, "types": PROCUREMENT_APPLICATION_TYPES},
    )
    return 1


def validate_project_stage_lock(doc, method=None):
    """Block editing a Project in a way that would alter the allocation inputs of
    a stage-locked or allocated period.

    - Stage-locked periods (RD Period Lock.lock_project_stage): a stage or date
      change that flips a locked period's R&D stage.
    - Locked AND submitted-allocation periods: clearing or setting the R&D
      project code of a project that logged hours there. 修复（2026-09-29，审查 X2-5 / 17-c）：
      历史工时现在按"有研发项目编号"计入，不再看 allow_rd_timesheet（取消项目只关掉新填报），
      所以这里改看编号；已提交分摊的阶段是快照，改阶段不影响它们，不拦。"""
    if doc.is_new():
        return
    cap_changed = (doc.has_value_changed("rd_stage")
                   or doc.has_value_changed("capitalization_start_date")
                   or doc.has_value_changed("capitalization_end_date"))
    code_changed = doc.has_value_changed("rd_project_code")
    if not (cap_changed or code_changed):
        return
    before = doc.get_doc_before_save()
    rd_changed = code_changed and bool(_rd_code(before) if before else "") != bool(_rd_code(doc))
    locked, allocated = guarded_rd_periods(frappe)
    changed = []
    for ym in sorted(locked | allocated):
        hit = ym in locked and cap_changed and _stage(before, ym) != _stage(doc, ym)
        hit = hit or (rd_changed and _has_rd_hours(doc.name, ym))
        if hit:
            changed.append("%s-%s" % (ym[:4], ym[4:]))
    if changed:
        frappe.throw(
            frappe._("会改变已锁定期间或已分摊期间（{0}）的研发分摊输入，不允许修改该项目的研发阶段、起止日期或研发项目编号。").format(
                ", ".join(sorted(set(changed)))
            )
        )
