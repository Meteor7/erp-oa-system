"""Simple R&D timesheet entry API for the SPA (04 工时填报).

Translates {period, employee, project, hours} into a submitted Timesheet so the
existing allocation engine (which reads tabTimesheet Detail) keeps working
unchanged. One submitted Timesheet per employee+project+period combo (upsert /
replace semantics); editing replaces. Zero hours are retained only for leave/comp-time drafts.
"""
import json
from datetime import timedelta

import frappe
from frappe.utils import getdate

from rayher_hr_payroll.api._guards import lock_period_import, require_rd_access, ensure_not_locked, parse_period

RD_TYPES = ("全时研发", "非全时研发", "研发辅助")
RD_ACTIVITY_TYPES = (
    "需求分析",
    "方案设计",
    "编码开发",
    "代码评审",
    "单元测试",
    "集成测试",
    "缺陷修复",
    "技术调研",
    "文档编写",
    "项目会议",
    "技术分享",
    "运维支持",
    "调休",
    "请假",
    "其他",
)
_DEFAULT_ACTIVITY = "编码开发"
ZERO_HOUR_ACTIVITY_TYPES = ("请假", "调休")
MAX_DAILY_HOURS = 8
MAX_DAILY_SECONDS = MAX_DAILY_HOURS * 60 * 60


RD_TIMESHEET_ENTRY_ROLES = ("System Manager", "HR User", "HR Manager", "Department Manager")
RD_TIMESHEET_VIEW_ROLES = (*RD_TIMESHEET_ENTRY_ROLES, "Accounts User", "Employee")
RD_TIMESHEET_ADMIN_ROLES = ("System Manager", "Accounts User", "HR User", "HR Manager")
RD_TIMESHEET_ALL_EMPLOYEE_ROLES = (*RD_TIMESHEET_ADMIN_ROLES, "All Project Access")
RD_TIMESHEET_FINANCE_VIEW_ROLES = ("Accounts User",)


def _period_has_submitted_allocation(year, month):
    """True if the period already has a SUBMITTED RD Cost Allocation. Once allocated,
    the period's hours are frozen: any add/update/delete would silently invalidate the
    submitted allocation (which only a System Manager can supersede), so hour mutations
    are blocked until that allocation is cancelled."""
    return bool(frappe.db.exists("RD Cost Allocation", {"year": year, "month": month, "docstatus": 1}))


def _month_has_monthly_entries(employee, year, month):
    return bool(
        frappe.db.exists(
            "Timesheet",
            {
                "employee": employee,
                "rd_system_generated": 1,
                "rd_entry_period": f"{int(year):04d}-{int(month):02d}",
                "docstatus": ["<", 2],
            },
        )
    )


def _has_any_role(roles):
    return bool(set(frappe.get_roles()) & set(roles))


def _session_user():
    return getattr(getattr(frappe, "session", None), "user", None)


def _current_employee():
    user = _session_user()
    if not user or user == "Guest":
        return None
    return frappe.db.get_value("Employee", {"user_id": user}, "name")


def _visible_employee_names(include_finance=False):
    all_employee_roles = RD_TIMESHEET_ALL_EMPLOYEE_ROLES + (RD_TIMESHEET_FINANCE_VIEW_ROLES if include_finance else ())
    if _has_any_role(all_employee_roles):
        return None
    current = _current_employee()
    names = []
    if current:
        names.append(current)
    if current and _has_any_role(("Department Manager",)):
        names.extend(frappe.get_all("Employee", filters={"reports_to": current}, pluck="name"))
    return sorted({name for name in names if name})


def _employee_filter(include_finance=False):
    filters = {"rd_personnel_type": ["in", RD_TYPES]}
    names = _visible_employee_names(include_finance=include_finance)
    if names is not None:
        filters["name"] = ["in", names or ["__none__"]]
    return filters


def _require_visible_employee(employee):
    names = _visible_employee_names()
    if names is not None and employee not in names:
        frappe.throw(frappe._("您无权为该员工登记工时。"))


def _company():
    return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all(
        "Company", pluck="name", limit=1
    )[0]


def _ensure_activity(activity_type=None):
    activity = (activity_type or _DEFAULT_ACTIVITY).strip()
    if activity not in RD_ACTIVITY_TYPES:
        frappe.throw(frappe._("活动类型不在研发工时分类中。"))
    if not frappe.db.exists("Activity Type", activity):
        frappe.get_doc({"doctype": "Activity Type", "activity_type": activity}).insert(
            ignore_permissions=True
        )
    return activity


def ensure_rd_activity_types():
    for activity in RD_ACTIVITY_TYPES:
        _ensure_activity(activity)


def _project_key(project_code, project_name):
    code = (project_code or "").strip()
    name = (project_name or "").strip()
    return f"{code} | {name}" if code and name else code or name


def _resolve_rd_project(project_code, project_name, selected_project=None):
    code = (project_code or "").strip()
    name = (project_name or "").strip()
    if not code or not name:
        frappe.throw(frappe._("请填写项目代码和项目名称。"))
    matches = frappe.get_all(
        "Project",
        filters={"rd_project_code": code, "project_name": name, "allow_rd_timesheet": 1, "status": ["not in", ["Completed", "Cancelled"]]},
        pluck="name",
        limit=2,
    )
    if len(matches) > 1:
        frappe.throw(frappe._("项目代码与项目名称匹配到多个项目，请先清理项目主数据。"))
    if matches:
        project = matches[0]
        if selected_project and selected_project != project:
            frappe.throw(frappe._("项目代码与项目名称匹配的项目与提交项目不一致。"))
        return project
    if selected_project:
        frappe.throw(frappe._("提交项目与项目代码、项目名称不匹配。"))
    frappe.throw(frappe._("项目代码和项目名称必须匹配项目管理中的可填报项目，请先在项目管理中新增或修正项目。"))


def _in_period(value, year, month):
    if not value:
        return False
    d = getdate(value)
    return d is not None and d.year == year and d.month == month


def _combo_timesheets(employee, project, year, month, work_date=None, activity_type=None):
    date_filter = "and date(tsd.from_time) = %(work_date)s" if work_date else ""
    activity_filter = "and tsd.activity_type = %(activity_type)s" if activity_type else ""
    return frappe.db.sql(
        f"""
        select distinct ts.name
        from `tabTimesheet Detail` tsd
        inner join `tabTimesheet` ts on ts.name = tsd.parent
        where ts.employee = %(employee)s and tsd.project = %(project)s
          and ts.docstatus < 2
          and month(tsd.from_time) = %(month)s and year(tsd.from_time) = %(year)s
          {date_filter}
          {activity_filter}
        """,
        {
            "employee": employee,
            "project": project,
            "year": year,
            "month": month,
            "work_date": work_date,
            "activity_type": activity_type,
        },
        pluck=True,
    )


def _log_matches(log, project, year, month, work_date=None, activity_type=None):
    if log.project != project or not _in_period(log.from_time, year, month):
        return False
    if work_date and getdate(log.from_time) != work_date:
        return False
    if activity_type and getattr(log, "activity_type", None) != activity_type:
        return False
    return True


def _drop_combo(employee, project, year, month, work_date=None, activity_type=None):
    """Delete only timesheets fully owned by this target row, so we never destroy
    unrelated time logs that share a timesheet."""
    for name in _combo_timesheets(employee, project, year, month, work_date, activity_type):
        doc = frappe.get_doc("Timesheet", name)
        if not doc.get("rd_spa_managed"):
            frappe.throw(
                frappe._("该员工本期该项目存在手工工时单 {0}，请在后台处理后再填报。").format(name)
            )
        logs = doc.time_logs or []
        owned = logs and all(_log_matches(l, project, year, month, work_date, activity_type) for l in logs)
        if not owned:
            frappe.throw(
                frappe._("工时单 {0} 含本行以外的工时行，请在后台处理以避免误删。").format(name)
            )
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("Timesheet", name, force=True, ignore_permissions=True)


@frappe.whitelist()
def get_rd_options():
    require_rd_access(RD_TIMESHEET_VIEW_ROLES)
    ensure_rd_activity_types()
    return {
        "employees": frappe.get_all(
            "Employee", filters=_employee_filter(include_finance=True),
            fields=["name", "employee_name"], order_by="employee_name",
        ),
        "projects": frappe.get_all(
            "Project", filters={"allow_rd_timesheet": 1, "status": ["not in", ["Completed", "Cancelled"]]},
            fields=["name", "project_name", "rd_project_code", "rd_project_key"], order_by="project_name",
        ),
        "activity_types": [{"name": activity} for activity in RD_ACTIVITY_TYPES],
    }


@frappe.whitelist()
def list_rd_hours(period, employee=None, scope="month"):
    require_rd_access(RD_TIMESHEET_VIEW_ROLES)
    year, month = parse_period(period)
    employee_filter, selected_employee, visible_employees = _summary_employee_filter(employee)
    return frappe.db.sql(
        f"""
        select ts.name as timesheet, tsd.name as timesheet_detail,
               ts.rd_spa_managed, ts.employee, e.employee_name,
               date(tsd.from_time) as work_date, tsd.activity_type,
               tsd.project,
               coalesce(nullif(tsd.rd_project_code, ''), p.rd_project_code) as rd_project_code,
               coalesce(nullif(tsd.rd_project_name, ''), p.project_name) as project_name,
               coalesce(
                   nullif(tsd.rd_project_key, ''),
                   p.rd_project_key,
                   concat(
                       coalesce(nullif(tsd.rd_project_code, ''), nullif(p.rd_project_code, ''), tsd.project),
                       ' | ',
                       coalesce(nullif(tsd.rd_project_name, ''), nullif(p.project_name, ''), tsd.project)
                   )
               ) as rd_project_key,
               tsd.hours, tsd.description
        from `tabTimesheet Detail` tsd
        inner join `tabTimesheet` ts on ts.name = tsd.parent
        inner join `tabEmployee` e on e.name = ts.employee
        inner join `tabProject` p on p.name = tsd.project
        where (
            ts.docstatus = 1
            or (
                ts.docstatus = 0
                and ts.rd_spa_managed = 1
                and tsd.hours = 0
                and tsd.activity_type in %(zero_hour_activity_types)s
            )
          )
          {_period_filter_sql(scope)}
          and e.rd_personnel_type in %(types)s
          {employee_filter}
          and coalesce(p.allow_rd_timesheet, 0) = 1
        order by date(tsd.from_time), e.employee_name, project_name, tsd.activity_type
        """,
        {
            "year": year,
            "month": month,
            "types": RD_TYPES,
            "zero_hour_activity_types": ZERO_HOUR_ACTIVITY_TYPES,
            "employee": selected_employee,
            "employees": visible_employees or ("__none__",),
        },
        as_dict=True,
    )


def _row_value(row, fieldname, default=None):
    if isinstance(row, dict):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def _period_filter_sql(scope=None):
    if str(scope or "month") == "year":
        return "and year(tsd.from_time) = %(year)s"
    return "and month(tsd.from_time) = %(month)s and year(tsd.from_time) = %(year)s"


def _summary_employee_filter(employee=None):
    selected = (employee or "").strip()
    visible = _visible_employee_names(include_finance=True)
    if selected and visible is not None and selected not in visible:
        frappe.throw(frappe._("您无权查看该员工的工时概览。"))
    if selected:
        return "and ts.employee = %(employee)s", selected, None
    if visible is not None:
        return "and ts.employee in %(employees)s", None, tuple(visible or ["__none__"])
    return "", None, None


@frappe.whitelist()
def get_rd_hour_summary(period, employee=None, scope="month"):
    require_rd_access(RD_TIMESHEET_VIEW_ROLES)
    year, month = parse_period(period)
    employee_filter, selected_employee, visible_employees = _summary_employee_filter(employee)
    rows = frappe.db.sql(
        f"""
        select ts.employee, e.employee_name, date(tsd.from_time) as work_date, tsd.hours
        from `tabTimesheet Detail` tsd
        inner join `tabTimesheet` ts on ts.name = tsd.parent
        inner join `tabEmployee` e on e.name = ts.employee
        inner join `tabProject` p on p.name = tsd.project
        where ts.docstatus = 1
          {_period_filter_sql(scope)}
          and e.rd_personnel_type in %(types)s
          and coalesce(p.allow_rd_timesheet, 0) = 1
          {employee_filter}
        """,
        {
            "year": year,
            "month": month,
            "types": RD_TYPES,
            "employee": selected_employee,
            "employees": visible_employees or ("__none__",),
        },
        as_dict=True,
    )
    total_hours = sum(float(_row_value(row, "hours", 0) or 0) for row in rows)
    employee_days = {}
    for row in rows:
        work_date = _row_value(row, "work_date")
        employee_name_key = _row_value(row, "employee")
        if work_date and employee_name_key:
            employee_days.setdefault(employee_name_key, set()).add(str(work_date))
    employee_day_count = sum(len(days) for days in employee_days.values())
    day_count = len(employee_days.get(selected_employee, set())) if selected_employee else max((len(days) for days in employee_days.values()), default=0)
    standard_hours = float(employee_day_count * MAX_DAILY_HOURS)
    first = rows[0] if rows else None
    employee_name = _row_value(first, "employee_name") if selected_employee and first else ""
    return {
        "employee": selected_employee or None,
        "employee_name": employee_name or "",
        "total_hours": round(total_hours, 2),
        "filled_days": day_count,
        "average_hours": round(total_hours / employee_day_count, 2) if employee_day_count else 0,
        "standard_hours": standard_hours,
        "standard_delta": round(total_hours - standard_hours, 2),
    }

def _work_date_in_period(work_date, year, month):
    if not work_date:
        frappe.throw(frappe._("请填写填报日期。"))
    value = getdate(work_date)
    if value.year != year or value.month != month:
        frappe.throw(frappe._("填报日期必须在会计期间内。"))
    return value


def _window_for_entry(year, month, work_date=None):
    if work_date:
        start = frappe.utils.get_datetime(f"{work_date.isoformat()} 00:00:00")
        return start, start + timedelta(days=1)
    month_start = frappe.utils.get_datetime("%04d-%02d-01 00:00:00" % (year, month))
    next_month = frappe.utils.get_datetime(
        frappe.utils.add_to_date("%04d-%02d-01 00:00:00" % (year, month), months=1)
    )
    return month_start, next_month


def _save_rd_hours_row(period, employee, project=None, hours=None, work_date=None, activity_type=None, description=None, project_code=None, project_name=None, allow_replace=True):
    _require_visible_employee(employee)
    year, month = parse_period(period)
    entry_date = _work_date_in_period(work_date, year, month)
    if _month_has_monthly_entries(employee, year, month):
        frappe.throw(frappe._("该员工本月已有按月工时，不能与按日工时混用。"))
    explicit_activity = (activity_type or "").strip()
    activity = _ensure_activity(explicit_activity or _DEFAULT_ACTIVITY)
    ensure_not_locked(period, "lock_timesheets", "工时")
    if _period_has_submitted_allocation(year, month):
        frappe.throw(frappe._("本期已存在已提交的研发费用分摊，工时已冻结；如需调整请先撤销分摊。"))
    hours = float(hours or 0)
    if hours < 0:
        frappe.throw(frappe._("工时不能为负数。"))
    if hours == 0 and activity not in ZERO_HOUR_ACTIVITY_TYPES:
        frappe.throw(frappe._("只有请假或调休的工时可以为 0。"))
    if hours > MAX_DAILY_HOURS:
        frappe.throw(frappe._("单日工时不能超过 8 小时。"))
    # server-side trust boundary: the UI filters options, but validate here too
    if (frappe.db.get_value("Employee", employee, "rd_personnel_type") or "") not in RD_TYPES:
        frappe.throw(frappe._("仅可为研发人员登记工时。"))
    submitted_project_code = (project_code or "").strip()
    submitted_project_name = (project_name or "").strip()
    project = _resolve_rd_project(submitted_project_code, submitted_project_name, project)
    project_code = submitted_project_code
    project_name = submitted_project_name
    project_key = _project_key(project_code, project_name)
    # Shared lock with recalc_allocation: serialize this insert against a concurrent
    # allocate so the freeze re-check below cannot be raced past (the allocation reads
    # hours under the same lock). When no import exists, no allocation can either.
    if lock_period_import(year, month) and _period_has_submitted_allocation(year, month):
        frappe.throw(frappe._("本期已存在已提交的研发费用分摊，工时已冻结；如需调整请先撤销分摊。"))
    frappe.db.get_value("Employee", employee, "name", for_update=True)  # serialize concurrent saves for this employee so the drop+insert cannot double-count
    drop_activity = activity if explicit_activity else None
    if not allow_replace and _combo_timesheets(employee, project, year, month, entry_date, drop_activity):
        frappe.throw(frappe._("系统中已存在相同员工/日期/项目/活动类型工时，请先删除后再导入。"))
    if allow_replace:
        _drop_combo(employee, project, year, month, entry_date, drop_activity)
    if hours > 0:
        # Place the log in the earliest free slot inside the chosen day (or month),
        # considering ALL the employee's logs (manual + SPA) so it overlaps none.
        date_filter = "and date(tsd.from_time) = %(work_date)s" if entry_date else ""
        existing = frappe.db.sql(
            f"""
            select tsd.from_time, tsd.to_time
            from `tabTimesheet` ts
            inner join `tabTimesheet Detail` tsd on tsd.parent = ts.name
            where ts.employee = %(emp)s and ts.docstatus < 2
              and month(tsd.from_time) = %(month)s and year(tsd.from_time) = %(year)s
              {date_filter}
            order by tsd.from_time
            """,
            {"emp": employee, "month": month, "year": year, "work_date": entry_date},
            as_dict=True,
        )
        need = int(round(hours * 3600))
        existing_seconds = 0
        for r in existing:
            f = frappe.utils.get_datetime(r.from_time)
            t = frappe.utils.get_datetime(r.to_time or r.from_time)
            existing_seconds += max(0, int(round((t - f).total_seconds())))
        if existing_seconds + need > MAX_DAILY_SECONDS:
            frappe.throw(frappe._("单日工时不能超过 8 小时。"))
        cursor, window_end = _window_for_entry(year, month, entry_date)
        for r in existing:
            f = frappe.utils.get_datetime(r.from_time)
            t = frappe.utils.get_datetime(r.to_time or r.from_time)
            if (f - cursor).total_seconds() >= need:
                break
            if t > cursor:
                cursor = t
        from_time = cursor
        if frappe.utils.get_datetime(frappe.utils.add_to_date(from_time, seconds=need)) > window_end:
            frappe.throw(frappe._("本日或本月工时累计过大，无法分布在目标期间内，请核对工时。"))
        ts = frappe.get_doc({
            "doctype": "Timesheet", "company": (frappe.db.get_value("Employee", employee, "company") or _company()), "employee": employee,
            "rd_spa_managed": 1,
            "time_logs": [{
                "activity_type": activity, "project": project,
                "rd_project_code": project_code, "rd_project_name": project_name, "rd_project_key": project_key,
                "hours": hours, "from_time": from_time,
                "description": (description or "").strip(),
            }],
        })
        ts.insert(ignore_permissions=True)
        ts.flags.ignore_permissions = True  # endpoint is role-gated by require_rd_access; carry the bypass into submit so HR users without native Timesheet submit can still file R&D hours
        ts.submit()
    else:
        from_time, _window_end = _window_for_entry(year, month, entry_date)
        ts = frappe.get_doc({
            "doctype": "Timesheet",
            "company": (frappe.db.get_value("Employee", employee, "company") or _company()),
            "employee": employee,
            "rd_spa_managed": 1,
            "time_logs": [{
                "activity_type": activity,
                "project": project,
                "rd_project_code": project_code,
                "rd_project_name": project_name,
                "rd_project_key": project_key,
                "hours": 0,
                "from_time": from_time,
                "to_time": from_time,
                "description": (description or "").strip(),
            }],
        })
        ts.insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def save_rd_hours(period, employee, project=None, hours=None, work_date=None, activity_type=None, description=None, project_code=None, project_name=None):
    require_rd_access(RD_TIMESHEET_ENTRY_ROLES)
    _save_rd_hours_row(
        period=period,
        employee=employee,
        project=project,
        hours=hours,
        work_date=work_date,
        activity_type=activity_type,
        description=description,
        project_code=project_code,
        project_name=project_name,
        allow_replace=True,
    )
    frappe.db.commit()
    return list_rd_hours(period)


@frappe.whitelist(methods=["POST"])
def bulk_save_rd_hours(period, rows):
    require_rd_access(RD_TIMESHEET_ENTRY_ROLES)
    if isinstance(rows, str):
        try:
            rows = json.loads(rows or "[]")
        except ValueError:
            frappe.throw(frappe._("导入工时数据格式不正确。"))
    if not isinstance(rows, list) or not rows:
        frappe.throw(frappe._("请导入至少一行工时。"))

    frappe.db.savepoint("rd_bulk_timesheet")
    try:
        for row in rows:
            if not isinstance(row, dict):
                frappe.throw(frappe._("导入工时数据格式不正确。"))
            _save_rd_hours_row(
                period=period,
                employee=row.get("employee"),
                project=row.get("project"),
                hours=row.get("hours"),
                work_date=row.get("work_date"),
                activity_type=row.get("activity_type"),
                description=row.get("description"),
                project_code=row.get("project_code"),
                project_name=row.get("project_name"),
                allow_replace=False,
            )
    except Exception:
        frappe.db.rollback(save_point="rd_bulk_timesheet")
        raise

    frappe.db.commit()
    return list_rd_hours(period)

@frappe.whitelist(methods=["POST"])
def delete_rd_hours(timesheet):
    require_rd_access(RD_TIMESHEET_ENTRY_ROLES)
    doc = frappe.get_doc("Timesheet", timesheet)
    _require_visible_employee(doc.employee)
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
