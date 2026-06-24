from datetime import date

import frappe
from frappe.utils import getdate


def _stage(doc, ym):
    """R&D stage of period `ym` (YYYYMM) for a project: capitalized inside the
    capitalization window, expensed when complete dates exist but the period is
    outside the window, else unknown (incomplete dates)."""
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


def validate_project_stage_lock(doc, method=None):
    """Block editing a Project in a way that would alter the allocation inputs of
    a stage-locked period (RD Period Lock.lock_project_stage): a capitalization
    window change that flips a locked period's R&D stage, OR toggling
    allow_rd_timesheet for a project that logged hours in a locked period (which
    would include/exclude those hours from the locked period's allocation)."""
    if doc.is_new():
        return
    cap_changed = (doc.has_value_changed("capitalization_start_date")
                   or doc.has_value_changed("capitalization_end_date"))
    rd_changed = doc.has_value_changed("allow_rd_timesheet")
    if not (cap_changed or rd_changed):
        return
    before = doc.get_doc_before_save()
    changed = []
    for lk in frappe.get_all(
        "RD Period Lock",
        filters={"docstatus": 1, "lock_project_stage": 1},
        fields=["period"],
        limit_page_length=0,
    ):
        ym = "".join(c for c in str(lk.period or "") if c.isdigit())[:6]
        if len(ym) != 6:
            continue
        hit = cap_changed and _stage(before, ym) != _stage(doc, ym)
        hit = hit or (rd_changed and _has_rd_hours(doc.name, ym))
        if hit:
            changed.append("%s-%s" % (ym[:4], ym[4:]))
    if changed:
        frappe.throw(
            frappe._("会改变已锁定期间（{0}）的研发分摊输入，不允许修改该项目的资本化日期或研发工时资格。").format(
                ", ".join(sorted(set(changed)))
            )
        )
