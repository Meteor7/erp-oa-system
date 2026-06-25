"""Simple R&D timesheet entry API for the SPA (04 工时填报).

Translates {period, employee, project, hours} into a submitted Timesheet so the
existing allocation engine (which reads tabTimesheet Detail) keeps working
unchanged. One submitted Timesheet per employee+project+period combo (upsert /
replace semantics); editing replaces, hours=0 deletes.
"""
import frappe
from frappe.utils import getdate

from rayher_hr_payroll.api._guards import lock_period_import, require_rd_access, ensure_not_locked, parse_period

RD_TYPES = ("全时研发", "非全时研发", "研发辅助")
_DEFAULT_ACTIVITY = "研发工时"




def _period_has_submitted_allocation(year, month):
    """True if the period already has a SUBMITTED RD Cost Allocation. Once allocated,
    the period's hours are frozen: any add/update/delete would silently invalidate the
    submitted allocation (which only a System Manager can supersede), so hour mutations
    are blocked until that allocation is cancelled."""
    return bool(frappe.db.exists("RD Cost Allocation", {"year": year, "month": month, "docstatus": 1}))


def _company():
    return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all(
        "Company", pluck="name", limit=1
    )[0]


def _ensure_activity():
    if not frappe.db.exists("Activity Type", _DEFAULT_ACTIVITY):
        frappe.get_doc({"doctype": "Activity Type", "activity_type": _DEFAULT_ACTIVITY}).insert(
            ignore_permissions=True
        )
    return _DEFAULT_ACTIVITY


def _in_period(value, year, month):
    if not value:
        return False
    d = getdate(value)
    return d is not None and d.year == year and d.month == month


def _combo_timesheets(employee, project, year, month):
    return frappe.db.sql(
        """
        select distinct ts.name
        from `tabTimesheet Detail` tsd
        inner join `tabTimesheet` ts on ts.name = tsd.parent
        where ts.employee = %(employee)s and tsd.project = %(project)s
          and ts.docstatus < 2
          and month(tsd.from_time) = %(month)s and year(tsd.from_time) = %(year)s
        """,
        {"employee": employee, "project": project, "year": year, "month": month},
        pluck=True,
    )


def _drop_combo(employee, project, year, month):
    """Delete only timesheets fully owned by this (employee, project, month) combo,
    so we never destroy unrelated time logs that share a timesheet."""
    for name in _combo_timesheets(employee, project, year, month):
        doc = frappe.get_doc("Timesheet", name)
        if not doc.get("rd_spa_managed"):
            frappe.throw(
                frappe._("该员工本期该项目存在手工工时单 {0}，请在后台处理后再填报。").format(name)
            )
        logs = doc.time_logs or []
        owned = logs and all(
            (l.project == project) and _in_period(l.from_time, year, month) for l in logs
        )
        if not owned:
            frappe.throw(
                frappe._("工时单 {0} 含本组合以外的工时行，请在后台处理以避免误删。").format(name)
            )
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("Timesheet", name, force=True, ignore_permissions=True)


@frappe.whitelist()
def get_rd_options():
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    return {
        "employees": frappe.get_all(
            "Employee", filters={"rd_personnel_type": ["in", RD_TYPES]},
            fields=["name", "employee_name"], order_by="employee_name",
        ),
        "projects": frappe.get_all(
            "Project", filters={"allow_rd_timesheet": 1},
            fields=["name", "project_name"], order_by="project_name",
        ),
    }


@frappe.whitelist()
def list_rd_hours(period):
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    year, month = parse_period(period)
    return frappe.db.sql(
        """
        select ts.name as timesheet, tsd.name as timesheet_detail,
               ts.rd_spa_managed, ts.employee, e.employee_name,
               tsd.project, p.project_name, tsd.hours
        from `tabTimesheet Detail` tsd
        inner join `tabTimesheet` ts on ts.name = tsd.parent
        inner join `tabEmployee` e on e.name = ts.employee
        inner join `tabProject` p on p.name = tsd.project
        where ts.docstatus = 1
          and month(tsd.from_time) = %(month)s and year(tsd.from_time) = %(year)s
          and e.rd_personnel_type in %(types)s
          and coalesce(p.allow_rd_timesheet, 0) = 1
        order by e.employee_name, p.project_name
        """,
        {"year": year, "month": month, "types": RD_TYPES},
        as_dict=True,
    )


@frappe.whitelist(methods=["POST"])
def save_rd_hours(period, employee, project, hours):
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    if not frappe.has_permission("Employee", "read", doc=employee):
        frappe.throw(frappe._("您无权为该员工登记工时。"))
    year, month = parse_period(period)
    ensure_not_locked(period, "lock_timesheets", "工时")
    if _period_has_submitted_allocation(year, month):
        frappe.throw(frappe._("本期已存在已提交的研发费用分摊，工时已冻结；如需调整请先撤销分摊。"))
    if float(hours or 0) < 0:
        frappe.throw(frappe._("工时不能为负数。"))
    # server-side trust boundary: the UI filters options, but validate here too
    if (frappe.db.get_value("Employee", employee, "rd_personnel_type") or "") not in RD_TYPES:
        frappe.throw(frappe._("仅可为研发人员登记工时。"))
    if not frappe.db.get_value("Project", project, "allow_rd_timesheet"):
        frappe.throw(frappe._("该项目未开启研发工时填报。"))
    hours = float(hours or 0)
    # Shared lock with recalc_allocation: serialize this insert against a concurrent
    # allocate so the freeze re-check below cannot be raced past (the allocation reads
    # hours under the same lock). When no import exists, no allocation can either.
    if lock_period_import(year, month) and _period_has_submitted_allocation(year, month):
        frappe.throw(frappe._("本期已存在已提交的研发费用分摊，工时已冻结；如需调整请先撤销分摊。"))
    frappe.db.get_value("Employee", employee, "name", for_update=True)  # serialize concurrent saves for this employee so the drop+insert cannot double-count
    _drop_combo(employee, project, year, month)
    if hours > 0:
        # Start this log right after the latest remaining timesheet log for the
        # employee in this period, so it never overlaps an existing one (ERPNext
        # derives to_time from from_time+hours and rejects overlapping employee
        # time when ignore_employee_time_overlap is off). Using max(to_time)
        # rather than a cumulative offset keeps edits/re-adds collision-free even
        # when the edited row originally preceded another. Monthly RD hours
        # (<=~200) fit well inside the month.
        # Place the log in the EARLIEST free slot of the month that fits `hours`,
        # considering ALL the employee's logs (manual + SPA) so it overlaps none,
        # yet packs from the 1st so a late-month entry is never pushed out of the
        # period (ends the SPA-only vs all-logs oscillation).
        existing = frappe.db.sql(
            """
            select tsd.from_time, tsd.to_time
            from `tabTimesheet` ts
            inner join `tabTimesheet Detail` tsd on tsd.parent = ts.name
            where ts.employee = %(emp)s and ts.docstatus < 2
              and month(tsd.from_time) = %(month)s and year(tsd.from_time) = %(year)s
            order by tsd.from_time
            """,
            {"emp": employee, "month": month, "year": year},
            as_dict=True,
        )
        need = int(round(hours * 3600))
        month_start = frappe.utils.get_datetime("%04d-%02d-01 00:00:00" % (year, month))
        next_month = frappe.utils.get_datetime(
            frappe.utils.add_to_date("%04d-%02d-01 00:00:00" % (year, month), months=1)
        )
        cursor = month_start
        for r in existing:
            f = frappe.utils.get_datetime(r.from_time)
            t = frappe.utils.get_datetime(r.to_time or r.from_time)
            if (f - cursor).total_seconds() >= need:
                break
            if t > cursor:
                cursor = t
        from_time = cursor
        if frappe.utils.get_datetime(frappe.utils.add_to_date(from_time, seconds=need)) > next_month:
            frappe.throw(frappe._("本月工时累计过大，无法分布在本月内，请核对工时。"))
        ts = frappe.get_doc({
            "doctype": "Timesheet", "company": (frappe.db.get_value("Employee", employee, "company") or _company()), "employee": employee,
            "rd_spa_managed": 1,
            "time_logs": [{
                "activity_type": _ensure_activity(), "project": project, "hours": hours,
                "from_time": from_time,
            }],
        })
        ts.insert(ignore_permissions=True)
        ts.flags.ignore_permissions = True  # endpoint is role-gated by require_rd_access; carry the bypass into submit so HR users without native Timesheet submit can still file R&D hours
        ts.submit()
    frappe.db.commit()
    return list_rd_hours(period)


@frappe.whitelist(methods=["POST"])
def delete_rd_hours(timesheet):
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    doc = frappe.get_doc("Timesheet", timesheet)
    if not frappe.has_permission("Employee", "read", doc=doc.employee):
        frappe.throw(frappe._("您无权删除该员工的工时。"))
    if not doc.get("rd_spa_managed") or len(doc.time_logs or []) != 1:
        frappe.throw(frappe._("仅可删除本工具创建的单行研发工时单；多行/手工工时单请在后台处理，以免误删其他工时。"))
    for l in (doc.time_logs or []):
        if not l.from_time:
            continue
        y, m = getdate(l.from_time).year, getdate(l.from_time).month
        ensure_not_locked("%04d%02d" % (y, m), "lock_timesheets", "工时")
        lock_period_import(y, m)  # same shared row as recalc/save: serialize delete vs allocate
        if _period_has_submitted_allocation(y, m):
            frappe.throw(frappe._("本期已存在已提交的研发费用分摊，请先撤销分摊后再删除工时。"))
    if doc.docstatus == 1:
        doc.flags.ignore_permissions = True
        doc.cancel()
    frappe.delete_doc("Timesheet", timesheet, force=True, ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}
