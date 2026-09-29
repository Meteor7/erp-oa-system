"""Hour-based OA attendance requests and transactionally serialized comp-time balances."""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

REQUEST_LEAVE = "请假申请"
REQUEST_OVERTIME = "加班申请"
REQUEST_COMP_TIME = "调休申请"
ATTENDANCE_TYPES = (REQUEST_LEAVE, REQUEST_OVERTIME, REQUEST_COMP_TIME)
LEAVE_TYPES = ("事假", "病假", "年假", "婚假", "产假", "陪产假", "丧假", "其他假")
ACTIVE = {"待审批", "待办理", "已完成", "已通过"}
COMPLETED = {"已完成", "已通过"}
ZERO = Decimal("0.00")


def value(row, field, default=None):
    return row.get(field, default) if isinstance(row, dict) else getattr(row, field, default)


def as_date(raw):
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        raise ValueError("开始和结束日期必须有效") from None


def date_range(start, end):
    start, end = as_date(start), as_date(end)
    if end < start or (end - start).days > 365:
        raise ValueError("结束日期不能早于开始日期，单次申请不能超过366天")
    return [start + timedelta(days=i) for i in range((end-start).days + 1)]


def normalize_days(raw, start, end, *, overtime=False, work_dates=None):
    dates = set(date_range(start, end))
    eligible = dates if overtime else dates & set(work_dates or [])
    if raw == "":
        raw = None
    if isinstance(raw, str):
        if len(raw) > 50000:
            raise ValueError("时长明细过大")
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ValueError("时长明细格式无效") from None
    if raw is None:
        raw = [{"work_date": d.isoformat(), "hours": 8} for d in sorted(eligible)]
    if not isinstance(raw, list) or len(raw) > 366:
        raise ValueError("时长明细必须为最多366行的列表")
    result, seen = [], set()
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("时长明细格式无效")
        day = as_date(row.get("work_date"))
        if day not in eligible or day in seen:
            raise ValueError("时长日期重复、超出申请日期或不是工作日")
        seen.add(day)
        try:
            hours = Decimal(str(row.get("hours")))
        except InvalidOperation:
            raise ValueError("小时数格式无效") from None
        if not hours.is_finite() or hours < 0 or hours > (24 if overtime else 8) or hours != hours.quantize(Decimal("0.01")):
            raise ValueError("小时数最多两位小数，请假和调休每天最多8小时，加班每天最多24小时")
        if hours:
            result.append({"work_date": day.isoformat(), "hours": float(hours)})
    if not result:
        raise ValueError("申请总时长必须大于0")
    return sorted(result, key=lambda row: row["work_date"])


def leave_hours_by_date(rows, work_dates):
    """Only completed personal leave reduces limits; half a day is four hours."""
    dates = set(work_dates)
    result = {}
    for row in rows:
        if value(row, "request_type") != REQUEST_LEAVE or value(row, "workflow_status") not in COMPLETED:
            continue
        # Paid, other and unclassified historical leave do not reduce the cap.
        if value(row, "leave_type") != "事假":
            continue
        raw = value(row, "attendance_days")
        if raw:
            details = json.loads(raw) if isinstance(raw, str) else raw
        else:
            start, end = as_date(value(row, "from_date")), as_date(value(row, "to_date"))
            details = [{"work_date": d.isoformat(), "hours": 8} for d in dates if start <= d <= end]
        for detail in details:
            day = as_date(detail["work_date"])
            if day in dates:
                result[day] = min(Decimal("8"), result.get(day, ZERO) + Decimal(str(detail["hours"])))
    return result


def approved_attendance(row):
    """已批准（已完成）的请假、加班、调休。"""
    return value(row, "request_type") in ATTENDANCE_TYPES and value(row, "workflow_status") in COMPLETED


def expand_days(row):
    """一张申请占用的每一天：[(日期, 小时数)]。

    新申请有逐日明细；只有起止日期的旧申请，按期间内每个周一到周五 8 小时算。
    """
    raw = value(row, "attendance_days")
    if raw:
        details = json.loads(raw) if isinstance(raw, str) else raw
        return [(as_date(detail["work_date"]), Decimal(str(detail["hours"]))) for detail in details]
    start, end = as_date(value(row, "from_date")), as_date(value(row, "to_date"))
    span = (start + timedelta(days=offset) for offset in range((end - start).days + 1))
    return [(day, Decimal("8")) for day in span if day.weekday() < 5]


def window_hours(row, start, end):
    """这张申请落在 [start, end] 这段日期里的小时数（跨月的申请按天拆开）。"""
    return sum((hours for day, hours in expand_days(row) if start <= day <= end), ZERO)


ABSENCE_LABELS = {REQUEST_LEAVE: "请假", REQUEST_COMP_TIME: "调休", REQUEST_OVERTIME: "加班"}
MAX_ABSENCE_HOURS_PER_DAY = Decimal("8")
MAX_OVERTIME_HOURS_PER_DAY = Decimal("24")
_STATUS_TEXT = {"待审批": "审批中", "待办理": "审批中", "已完成": "已通过", "已通过": "已通过"}


def _taken_by_day(others, wanted):
    """这个员工其他有效申请在指定日期上已经占了多少：{日期: {absence, overtime, row}}。"""
    taken = {}
    for row in others:
        if value(row, "workflow_status") not in ACTIVE:
            continue
        kind = "overtime" if value(row, "request_type") == REQUEST_OVERTIME else "absence"
        for day, hours in expand_days(row):
            if day in wanted:
                slot = taken.setdefault(day, {"absence": ZERO, "overtime": ZERO, "row": row})
                slot[kind] += hours
                if hours:
                    slot["row"] = row
    return taken


def _where(day, row):
    label = ABSENCE_LABELS.get(value(row, "request_type"), "")
    return f"{day.month}月{day.day}日已有{label}申请 {value(row, 'name')}（{_STATUS_TEXT.get(value(row, 'workflow_status'), '')}）"


def find_day_conflict(request_type, days, others):
    """新申请的哪一天和这个员工已有的（审批中或已通过的）申请撞了；没有撞返回 None，撞了返回提示。

    修复（2026-09-29，审查 #56 P2）：三类申请之间原来没有任何日期冲突检查，
    同一天可以同时请假、调休、加班，加班一天还能报到 24 小时。规则：
    - 请假和调休：同一天合计不超过 8 小时（一天 8 小时）；
    - 加班：同一天已有的加班合计不超过 24 小时；
    - 同一天有请假或调休的，不能再申请加班，反过来也一样。
    """
    wanted = {}
    for detail in days:
        day = as_date(detail["work_date"])
        wanted[day] = wanted.get(day, ZERO) + Decimal(str(detail["hours"]))
    taken = _taken_by_day(others, set(wanted))
    for day in sorted(taken):
        slot, row = taken[day], taken[day]["row"]
        where = _where(day, row)
        if request_type == REQUEST_OVERTIME:
            if slot["absence"] > 0:
                return f"{where}，同一天不能再申请加班。"
            if slot["overtime"] + wanted[day] > MAX_OVERTIME_HOURS_PER_DAY:
                return f"{where}，同一天的加班合计不能超过 24 小时。"
        else:
            if slot["overtime"] > 0:
                return f"{where}，同一天不能再申请{ABSENCE_LABELS[request_type]}。"
            if slot["absence"] + wanted[day] > MAX_ABSENCE_HOURS_PER_DAY:
                return f"{where}，同一天的请假和调休合计不能超过 8 小时。"
    return None


def day_limits(request_type, dates, others):
    """申请表里每一天还能填多少小时；这天已经被占满时给出是哪张申请占的：
    {日期: {max_hours, conflict: None | {request, text}}}。"""
    taken = _taken_by_day(others, set(dates))
    limits = {}
    for day in dates:
        slot = taken.get(day)
        if request_type == REQUEST_OVERTIME:
            blocked = bool(slot and slot["absence"] > 0)
            remaining = MAX_OVERTIME_HOURS_PER_DAY - (slot["overtime"] if slot else ZERO)
        else:
            blocked = bool(slot and slot["overtime"] > 0)
            remaining = MAX_ABSENCE_HOURS_PER_DAY - (slot["absence"] if slot else ZERO)
        if slot and (blocked or remaining <= 0):
            row = slot["row"]
            limits[day] = {"max_hours": 0, "conflict": {"request": value(row, "name"), "text": _where(day, row)}}
        else:
            limits[day] = {"max_hours": float(remaining), "conflict": None}
    return limits


def active_rows(employee, start, end, *, exclude="", lock=False):
    """员工在 [start, end] 里审批中或已通过的请假、加班、调休申请（含每日明细）。"""
    import frappe
    statuses, types = sorted(ACTIVE), sorted(ATTENDANCE_TYPES)
    status_marks, type_marks = ", ".join(["%s"] * len(statuses)), ", ".join(["%s"] * len(types))
    return frappe.db.sql(
        "SELECT name, request_type, leave_type, workflow_status, from_date, to_date, attendance_days, duration_hours "
        "FROM `tabOA Approval Request` WHERE employee = %s AND name <> %s "
        f"AND request_type IN ({type_marks}) AND workflow_status IN ({status_marks}) "
        "AND from_date <= %s AND to_date >= %s" + (" FOR UPDATE" if lock else ""),
        (employee, exclude or "", *types, *statuses, end, start), as_dict=True,
    )


def balance_effect(request_type, status, hours):
    hours = Decimal(str(hours or 0))
    if status not in ACTIVE:
        return (ZERO, ZERO, ZERO)
    if request_type == REQUEST_OVERTIME:
        return (hours, ZERO, ZERO)
    if request_type == REQUEST_COMP_TIME:
        return (ZERO, ZERO, hours) if status in COMPLETED else (ZERO, hours, ZERO)
    return (ZERO, ZERO, ZERO)


def summarize_balance(rows):
    totals = {key: sum((Decimal(str(value(row, key, 0) or 0)) for row in rows), ZERO)
              for key in ("credit_hours", "reserved_hours", "used_hours")}
    totals["available_hours"] = totals["credit_hours"] - totals["reserved_hours"] - totals["used_hours"]
    return {key: float(number) for key, number in totals.items()}


def work_dates_for_range(employee, start, end):
    from rayher_hr_payroll.working_calendar import resolve_monthly_calendar
    dates = date_range(start, end)
    months = sorted({(d.year, d.month) for d in dates})
    return {d for y, m in months for d in resolve_monthly_calendar(y, m, employee=employee)["work_dates"]} & set(dates)


def prepare_request(doc):
    import frappe
    if value(doc, "request_type") not in ATTENDANCE_TYPES:
        return
    start, end = value(doc, "from_date"), value(doc, "to_date")
    if value(doc, "workflow_status") == "草稿" and (not start or not end):
        return
    try:
        overtime = doc.request_type == REQUEST_OVERTIME
        days = normalize_days(value(doc, "attendance_days"), start, end, overtime=overtime,
                              work_dates=None if overtime else work_dates_for_range(doc.employee, start, end))
        if doc.request_type == REQUEST_LEAVE and value(doc, "leave_type") not in LEAVE_TYPES:
            raise ValueError("请选择有效请假类型；调休请使用调休申请")
    except ValueError as exc:
        frappe.throw(str(exc))
    doc.attendance_days = json.dumps(days, ensure_ascii=False)
    doc.duration_hours = sum(row["hours"] for row in days)


def get_balance(employee, *, lock=False):
    import frappe
    if not employee:
        return summarize_balance([])
    if lock:
        frappe.db.get_value("Employee", employee, "name", for_update=True)
    rows = frappe.db.sql(
        "SELECT name, source_request, credit_hours, reserved_hours, used_hours "
        "FROM `tabOA Time Balance Entry` WHERE employee = %s" + (" FOR UPDATE" if lock else ""),
        (employee,), as_dict=True,
    )
    return summarize_balance(rows)


def sync_balance(doc):
    import frappe
    if value(doc, "request_type") not in (REQUEST_OVERTIME, REQUEST_COMP_TIME):
        return
    # Hold the employee row until request + balance entry commit together. FOR UPDATE
    # reads current committed rows even under MariaDB REPEATABLE READ.
    employee = value(doc, "employee")
    if not employee:
        frappe.throw("申请必须关联员工")
    frappe.db.get_value("Employee", employee, "name", for_update=True)
    rows = frappe.db.sql(
        "SELECT name, source_request, credit_hours, reserved_hours, used_hours "
        "FROM `tabOA Time Balance Entry` WHERE employee = %s FOR UPDATE", (employee,), as_dict=True,
    )
    previous = next((row for row in rows if row.source_request == doc.name), None)
    credit, reserved, used = balance_effect(doc.request_type, doc.workflow_status, value(doc, "duration_hours"))
    previous_debit = sum((Decimal(str(value(previous, key, 0) or 0)) for key in ("reserved_hours", "used_hours")), ZERO)
    extra_debit = reserved + used - previous_debit
    if extra_debit > 0 and Decimal(str(summarize_balance(rows)["available_hours"])) < extra_debit:
        frappe.throw("可用调休余额不足，请先检查加班额度及申请中占用的时长")
    values = {"employee": employee, "source_request": doc.name,
              "credit_hours": float(credit), "reserved_hours": float(reserved), "used_hours": float(used)}
    if previous:
        frappe.db.set_value("OA Time Balance Entry", previous.name, values)
    elif credit or reserved or used:
        frappe.get_doc({"doctype": "OA Time Balance Entry", **values}).insert(ignore_permissions=True)
    projected = [row for row in rows if value(row, "source_request") != doc.name] + [values]
    if summarize_balance(projected)["available_hours"] < 0:
        frappe.msgprint("加班额度冲回后调休余额不足，已保留调休记录；请联系人事处理，余额补足前不能新增调休。", indicator="orange")


def check_day_conflicts(doc):
    """申请提交（从草稿变成审批中）时，和这个员工其他有效申请比对日期。员工行已经加锁，读当前数据。"""
    import frappe
    employee, start, end = value(doc, "employee"), value(doc, "from_date"), value(doc, "to_date")
    if not (employee and start and end):
        return
    rows = active_rows(employee, start, end, exclude=value(doc, "name"), lock=True)
    message = find_day_conflict(doc.request_type, expand_detail_rows(doc), rows)
    if message:
        frappe.throw(message)


def expand_detail_rows(doc):
    return [{"work_date": day.isoformat(), "hours": float(hours)} for day, hours in expand_days(doc)]


def validate_attendance_request(doc):
    if value(doc, "request_type") not in ATTENDANCE_TYPES:
        return
    import frappe
    if value(doc, "employee"):
        frappe.db.get_value("Employee", doc.employee, "name", for_update=True)
    before = doc.get_doc_before_save()
    # Keep historical approved date-only leave readable; normalize when submitted/edited.
    if before is None or value(before, "workflow_status") == "草稿":
        prepare_request(doc)
    if value(doc, "workflow_status") in ACTIVE and (before is None or value(before, "workflow_status") not in ACTIVE):
        check_day_conflicts(doc)
    from rayher_hr_payroll.annual_leave import validate_annual_request
    validate_annual_request(doc, before)
    sync_balance(doc)


def warn_leave_over_limit(doc):
    import frappe
    if value(doc, "request_type") != REQUEST_LEAVE or value(doc, "workflow_status") not in COMPLETED or value(doc, "leave_type") != "事假":
        return
    before = doc.get_doc_before_save()
    if before and value(before, "workflow_status") in COMPLETED:
        return
    from rayher_hr_payroll.working_calendar import resolve_monthly_work_limit
    months = sorted({(d.year, d.month) for d in date_range(doc.from_date, doc.to_date)})
    for year, month in months:
        limit = resolve_monthly_work_limit(year, month, employee=doc.employee)
        rows = frappe.db.sql(
            "SELECT COALESCE(SUM(d.hours), 0) AS hours FROM `tabTimesheet Detail` d "
            "JOIN `tabTimesheet` t ON t.name = d.parent "
            "WHERE t.employee = %s AND t.docstatus = 1 AND YEAR(d.from_time) = %s AND MONTH(d.from_time) = %s",
            (doc.employee, year, month), as_dict=True,
        )
        actual = float(rows[0].hours or 0)
        if actual > limit["hour_limit"]:
            frappe.msgprint(f"{year}-{month:02d} 已填报 {actual:g} 小时，超过请假后的上限 {limit['hour_limit']:g} 小时，请调整工时。", indicator="orange")



def attendance_request_transaction(function):
    """Acquire HR's employee mutex before existing request/approval locks."""
    from functools import wraps
    @wraps(function)
    def wrapped(name, *args, **kwargs):
        import frappe
        row = frappe.db.get_value("OA Approval Request", name, ["request_type", "employee"], as_dict=True)
        if row and value(row, "request_type") in ATTENDANCE_TYPES and value(row, "employee"):
            frappe.db.get_value("Employee", value(row, "employee"), "name", for_update=True)
        return function(name, *args, **kwargs)
    return wrapped
