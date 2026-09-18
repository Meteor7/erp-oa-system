"""Dashboard overview APIs: company cost by project, HR leave stats, personal balance."""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date

import frappe

from rayher_hr_payroll import annual_leave, attendance_requests
from rayher_hr_payroll.api._guards import RD_FINANCE_ROLES
from rayher_hr_payroll.position_access import position_users

NON_PROJECT = "__none__"
NON_PROJECT_LABEL = "非项目"
EXPENSE_REQUEST = "费用付款申请"
EXPENSE_DONE = ("已完成", "已付款")
PO_DEAD_STATUS = ("已取消",)
HOURS_PER_DAY = 8
LEADER_POSITIONS = ("vice_manager", "general_manager")
HR_ROLES = {"HR User", "HR Manager", "System Manager"}
ATTENDANCE_TYPES = attendance_requests.ATTENDANCE_TYPES
LEAVE_TYPES = attendance_requests.LEAVE_TYPES


def _user():
    return str(frappe.session.user or "").strip().lower()


def _roles():
    return set(frappe.get_roles() or [])


def _is_leader():
    return _user() in position_users(*LEADER_POSITIONS)


def can_view_cost():
    return _is_leader() or bool(_roles() & set(RD_FINANCE_ROLES))


def hr_scope():
    """Return (visible, department). department None means the whole company."""
    if _is_leader() or bool(_roles() & HR_ROLES):
        return True, None
    if "Department Manager" in _roles():
        department = frappe.db.get_value("Employee", {"user_id": _user()}, "department")
        if department:
            return True, department
    return False, None


def parse_scope(scope, period):
    """Normalise (scope, period) into ("month"|"year", year, month or None)."""
    scope = "year" if str(scope or "").strip() == "year" else "month"
    text = str(period or "").strip()
    today = date.today()
    if scope == "year":
        return scope, int(text[:4]) if text[:4].isdigit() else today.year, None
    if len(text) >= 7 and text[:4].isdigit() and text[5:7].isdigit():
        return scope, int(text[:4]), int(text[5:7])
    return scope, today.year, today.month


def period_months(scope, year, month):
    if scope == "year":
        return [(year, index) for index in range(1, 13)]
    return [(year, month)]


def previous_months(scope, year, month):
    if scope == "year":
        return [(year - 1, index) for index in range(1, 13)]
    return [(year - 1, 12)] if month == 1 else [(year, month - 1)]


def trend_periods(scope, year, month):
    """Trend buckets: 12 months for a month view, 5 years for a year view."""
    if scope == "year":
        return [{"label": str(year - offset), "months": [(year - offset, index) for index in range(1, 13)]}
                for offset in range(4, -1, -1)]
    buckets = []
    for offset in range(11, -1, -1):
        shifted = (year * 12 + month - 1) - offset
        bucket_year, bucket_month = divmod(shifted, 12)
        buckets.append({"label": "%d月" % (bucket_month + 1), "months": [(bucket_year, bucket_month + 1)]})
    return buckets


def month_range(months):
    """First and last calendar date covered by the given (year, month) pairs."""
    first, last = min(months), max(months)
    return date(first[0], first[1], 1), date(last[0], last[1], calendar.monthrange(last[0], last[1])[1])


def _empty():
    return {"rd": 0.0, "po": 0.0, "expense": 0.0}


def project_costs(rows):
    """Aggregate {project, kind, amount} rows into per-project totals."""
    totals = defaultdict(_empty)
    for row in rows:
        project = row.get("project") or NON_PROJECT
        totals[project][row["kind"]] += float(row.get("amount") or 0)
    for values in totals.values():
        values["total"] = values["rd"] + values["po"] + values["expense"]
    return dict(totals)


def sum_costs(costs):
    result = _empty()
    for values in costs.values():
        for kind in ("rd", "po", "expense"):
            result[kind] += values[kind]
    result["total"] = result["rd"] + result["po"] + result["expense"]
    return result


def delta_percent(current, previous):
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def days(hours):
    return round(float(hours or 0) / HOURS_PER_DAY, 2)


def _rd_rows(months):
    wanted = set(months)
    periods = {row.name: (row.year, row.month) for row in frappe.get_all(
        "RD Cost Allocation",
        filters={"docstatus": 1, "year": ["in", sorted({year for year, _ in wanted})],
                 "month": ["in", sorted({month for _, month in wanted})]},
        fields=["name", "year", "month"], limit_page_length=0)
        if (row.year, row.month) in wanted}
    if not periods:
        return []
    return [{"project": line.project, "kind": "rd", "amount": line.allocated_amount,
             "label": line.account_level_3 or line.expense_item_name or "其他费用",
             "hours": line.basis_hours, "period": periods[line.parent]}
            for line in frappe.get_all("RD Cost Allocation Line", filters={"parent": ["in", list(periods)]},
                                       fields=["parent", "project", "allocated_amount", "account_level_3",
                                               "expense_item_name", "basis_hours"],
                                       limit_page_length=0)]


def _po_rows(months):
    start, end = month_range(months)
    names = frappe.get_all("OA Purchase Order",
                           filters={"status": ["not in", PO_DEAD_STATUS],
                                    "creation": ["between", [start, frappe.utils.add_days(end, 1)]]},
                           pluck="name")
    if not names:
        return []
    return [{"project": line.project, "kind": "po", "amount": line.amount,
             "label": line.item_name or line.material_code or "采购物料"}
            for line in frappe.get_all("OA Purchase Order Line", filters={"parent": ["in", names]},
                                       fields=["project", "amount", "item_name", "material_code"],
                                       limit_page_length=0)]


def _expense_rows(months):
    start, end = month_range(months)
    requests = frappe.get_all("OA Approval Request",
                              filters={"request_type": EXPENSE_REQUEST,
                                       "workflow_status": ["in", EXPENSE_DONE],
                                       "modified": ["between", [start, frappe.utils.add_days(end, 1)]]},
                              fields=["name", "project"], limit_page_length=0)
    if not requests:
        return []
    project_by_request = {row.name: row.project for row in requests}
    return [{"project": line.project_name or project_by_request.get(line.parent),
             "kind": "expense", "amount": line.total_amount or line.amount,
             "label": line.expense_account_level_2 or line.category or "其他报销"}
            for line in frappe.get_all("OA Approval Expense Line",
                                       filters={"parent": ["in", list(project_by_request)]},
                                       fields=["parent", "project_name", "total_amount", "amount",
                                               "expense_account_level_2", "category"],
                                       limit_page_length=0)]


def cost_rows(months):
    return _rd_rows(months) + _po_rows(months) + _expense_rows(months)


def _project_labels(keys):
    names = [key for key in keys if key and key != NON_PROJECT]
    if not names:
        return {}
    return {row.name: row.project_name or row.name
            for row in frappe.get_all("Project", filters={"name": ["in", names]},
                                      fields=["name", "project_name"], limit_page_length=0)}


@frappe.whitelist()
def get_cost_overview(scope="month", period=None):
    if not can_view_cost():
        return {"visible": False}
    scope, year, month = parse_scope(scope, period)
    costs = project_costs(cost_rows(period_months(scope, year, month)))
    previous = project_costs(cost_rows(previous_months(scope, year, month)))
    labels = _project_labels(costs)
    totals, previous_totals = sum_costs(costs), sum_costs(previous)
    projects = sorted(
        ({"project": key,
          "label": NON_PROJECT_LABEL if key == NON_PROJECT else labels.get(key, key),
          "delta": delta_percent(values["total"], previous.get(key, _empty()).get("total", 0)),
          **values} for key, values in costs.items()),
        key=lambda row: row["total"], reverse=True)
    trend = [{"label": bucket["label"], **sum_costs(project_costs(cost_rows(bucket["months"])))}
             for bucket in trend_periods(scope, year, month)]
    return {"visible": True, "scope": scope, "year": year, "month": month, "totals": totals,
            "deltas": {kind: delta_percent(totals[kind], previous_totals[kind])
                       for kind in ("rd", "po", "expense", "total")},
            "projects": projects, "trend": trend}


@frappe.whitelist()
def get_project_cost_detail(project="", scope="month", period=None):
    if not can_view_cost():
        frappe.throw(frappe._("只有财务和公司领导可以查看项目费用明细。"))
    scope, year, month = parse_scope(scope, period)
    key = str(project or NON_PROJECT).strip() or NON_PROJECT
    groups = {"rd": defaultdict(float), "po": defaultdict(float), "expense": defaultdict(float)}
    # basis_hours repeats on every allocation line of a month, so keep one value per month.
    hours_by_period = {}
    for row in cost_rows(period_months(scope, year, month)):
        if (row.get("project") or NON_PROJECT) != key:
            continue
        groups[row["kind"]][row["label"]] += float(row.get("amount") or 0)
        if row.get("period"):
            hours_by_period[row["period"]] = max(hours_by_period.get(row["period"], 0.0),
                                                 float(row.get("hours") or 0))
    hours = sum(hours_by_period.values())
    totals = {kind: sum(values.values()) for kind, values in groups.items()}
    totals["total"] = sum(totals.values())
    label = NON_PROJECT_LABEL
    if key != NON_PROJECT:
        label = frappe.db.get_value("Project", key, "project_name") or key
    return {"project": key, "label": label, "totals": totals, "hours": round(hours, 1),
            "breakdown": {kind: sorted(({"label": label_text, "amount": amount}
                                        for label_text, amount in values.items()),
                                       key=lambda row: row["amount"], reverse=True)[:8]
                          for kind, values in groups.items()}}


def leave_stats(rows):
    """Aggregate attendance requests into per-type and per-department day totals."""
    by_type, by_department = defaultdict(float), defaultdict(lambda: {"leave": 0.0, "overtime": 0.0})
    totals = {"leave_days": 0.0, "leave_count": 0, "overtime_days": 0.0, "comp_days": 0.0}
    for row in rows:
        request_type = row.get("request_type")
        hours = float(row.get("duration_hours") or 0)
        department = row.get("department") or "未分配部门"
        if request_type == attendance_requests.REQUEST_LEAVE:
            totals["leave_days"] += days(hours)
            totals["leave_count"] += 1
            by_type[row.get("leave_type") or "未填类别"] += days(hours)
            by_department[department]["leave"] += days(hours)
        elif request_type == attendance_requests.REQUEST_OVERTIME:
            totals["overtime_days"] += days(hours)
            by_department[department]["overtime"] += days(hours)
        elif request_type == attendance_requests.REQUEST_COMP_TIME:
            totals["comp_days"] += days(hours)
            by_type["调休"] += days(hours)
            by_department[department]["leave"] += days(hours)
    totals = {key: round(value, 2) if isinstance(value, float) else value for key, value in totals.items()}
    return {
        "totals": totals,
        "by_type": sorted(({"label": key, "days": round(value, 2)} for key, value in by_type.items()),
                          key=lambda row: row["days"], reverse=True),
        "by_department": sorted(({"label": key, "leave": round(value["leave"], 2),
                                  "overtime": round(value["overtime"], 2)}
                                 for key, value in by_department.items()),
                                key=lambda row: row["leave"] + row["overtime"], reverse=True)[:10],
    }


def _attendance_rows(months, department=None):
    start, end = month_range(months)
    filters = {"request_type": ["in", list(ATTENDANCE_TYPES)],
               "workflow_status": ["in", list(attendance_requests.COMPLETED)],
               "from_date": ["between", [start, end]]}
    if department:
        filters["department"] = department
    return frappe.get_all("OA Approval Request", filters=filters,
                          fields=["request_type", "leave_type", "duration_hours", "department",
                                  "employee", "employee_name", "from_date"],
                          limit_page_length=0)


@frappe.whitelist()
def get_hr_overview(scope="month", period=None):
    visible, department = hr_scope()
    if not visible:
        return {"visible": False}
    scope, year, month = parse_scope(scope, period)
    stats = leave_stats(_attendance_rows(period_months(scope, year, month), department))
    trend = []
    for bucket in trend_periods(scope, year, month):
        bucket_stats = leave_stats(_attendance_rows(bucket["months"], department))["totals"]
        trend.append({"label": bucket["label"], "leave": bucket_stats["leave_days"],
                      "overtime": bucket_stats["overtime_days"]})
    employee_filters = {"status": "Active"}
    if department:
        employee_filters["department"] = department
    employees = frappe.get_all("Employee", filters=employee_filters,
                               fields=["name", "employee_name", "department", "date_of_joining"],
                               limit_page_length=0)
    balances, missing_joining = [], 0
    for employee in employees:
        if not employee.date_of_joining:
            missing_joining += 1
        annual = annual_leave.get_annual_balance(employee.name)
        comp = attendance_requests.get_balance(employee.name)
        balances.append({"employee": employee.employee_name or employee.name,
                         "department": employee.department or "",
                         "annual_days": days(annual.get("available_hours")),
                         "comp_days": days(comp.get("available_hours"))})
    balances.sort(key=lambda row: row["annual_days"] + row["comp_days"], reverse=True)
    return {"visible": True, "scope": scope, "year": year, "month": month,
            "department": department, "headcount": len(employees),
            "alerts": {"missing_joining": missing_joining,
                       "negative_comp": sum(1 for row in balances if row["comp_days"] < 0)},
            "trend": trend, "balances": balances[:8], **stats}


@frappe.whitelist()
def get_my_leave_summary():
    if _user() in {"", "guest"}:
        frappe.throw(frappe._("请先登录。"))
    employee = frappe.db.get_value("Employee", {"user_id": _user(), "status": "Active"},
                                   ["name", "date_of_joining"], as_dict=True)
    if not employee:
        return {"visible": False}
    annual = annual_leave.get_annual_balance(employee.name)
    comp = attendance_requests.get_balance(employee.name)
    return {"visible": True,
            "annual": {"available": days(annual.get("available_hours")),
                       "granted": days(annual.get("credit_hours")),
                       "used": days(annual.get("used_hours")),
                       "reserved": days(annual.get("reserved_hours")),
                       "eligible": annual.get("eligible"),
                       "message": annual.get("eligibility_message") or "",
                       "next_grant_date": annual.get("next_grant_date"),
                       "next_grant_days": days(annual_leave.ANNUAL_HOURS)},
            "comp": {"available": days(comp.get("available_hours")),
                     "credit": days(comp.get("credit_hours")),
                     "used": days(comp.get("used_hours")),
                     "reserved": days(comp.get("reserved_hours"))}}


# --- personal queue ----------------------------------------------------------

ROUTE_BY_TYPE = {
    "请假申请": "/approval/leave",
    "加班申请": "/approval/overtime",
    "调休申请": "/approval/comp-time",
    "采购申请": "/approval/procurement",
    "购买申请": "/approval/direct-purchase",
    "采购付款": "/approval/procurement-payment",
    "费用付款申请": "/approval/reimbursement",
}
OVERDUE_DAYS = 3


def waiting_days(since):
    if not since:
        return 0
    return max(0, (frappe.utils.now_datetime() - frappe.utils.get_datetime(since)).days)


def queue_item(doc, steps):
    """Shape one pending approval for the dashboard list."""
    waited = waiting_days(doc.get("modified"))
    amount = float(doc.get("approved_amount") or doc.get("amount") or 0)
    current = next((row for row in steps if row.get("status") in ("待审批", "待办理", "")), None)
    return {
        "name": doc.get("name"),
        "request_type": doc.get("request_type"),
        "subject": doc.get("subject") or doc.get("name"),
        "applicant": doc.get("employee_name") or doc.get("owner") or "",
        "department": doc.get("department") or "",
        "amount": amount,
        "leave_type": doc.get("leave_type") or "",
        "hours": float(doc.get("duration_hours") or 0),
        "from_date": str(doc.get("from_date") or ""),
        "to_date": str(doc.get("to_date") or ""),
        "step_label": (current or {}).get("label") or doc.get("current_step_label") or "",
        "waited_days": waited,
        "overdue": waited >= OVERDUE_DAYS,
        "route": ROUTE_BY_TYPE.get(doc.get("request_type"), "/approval/request-dashboard"),
    }


def _steps_by_parent(names):
    rows = frappe.get_all("OA Approval Step", filters={"parent": ["in", names]},
                          fields=["parent", "step_index", "label", "status", "note", "acted_on"],
                          order_by="parent asc, step_index asc", limit_page_length=0) if names else []
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.parent].append(row)
    return grouped


PROCUREMENT_ROUTE = "/approval/procurement/price-approvals"
PAYMENT_ROUTE = "/approval/procurement-payment"


def task_item(kind, title, detail, waited, route, reason, name, amount=0, query=None):
    """One thing the signed-in user has to do, whatever document it lives on."""
    return {"name": name, "kind": kind, "request_type": kind, "subject": title, "applicant": detail,
            "department": "", "amount": float(amount or 0), "leave_type": "", "hours": 0,
            "from_date": "", "to_date": "", "step_label": "", "reason": reason,
            "waited_days": waited, "overdue": waited >= OVERDUE_DAYS,
            "route": route, "query": query or {}}


def _price_approval_tasks():
    """Price approvals waiting for the person who signs them off."""
    if _user() not in position_users("vice_manager") and "System Manager" not in _roles():
        return []
    rows = frappe.get_all("OA Price Approval", filters={"status": "待审批"},
                          fields=["name", "total_amount", "modified", "owner"], limit_page_length=0)
    return [task_item("价格审批", f"{row.name} 待选择成交供应商并审批",
                      f"采购提交 · {frappe.db.get_value('User', row.owner, 'full_name') or row.owner}",
                      waiting_days(row.modified), PROCUREMENT_ROUTE, "我是价格审批人", row.name,
                      row.total_amount, {"request": row.name})
            for row in rows]


def _purchase_order_tasks():
    """PO stages, each shown only to the role that has to act on it."""
    user, roles = _user(), _roles()
    is_purchase = user in position_users("procurement_manager") or bool(roles & {"Purchase User", "Purchase Manager"})
    is_asset_owner = user in position_users("production_asset_owner")
    is_admin = "System Manager" in roles
    stages = {
        "草稿": ("待采购确认订单", "我是采购", is_purchase or is_admin),
        "待采购确认": ("待采购确认订单", "我是采购", is_purchase or is_admin),
        "待合同复核": ("合同待复核", "我是采购", is_purchase or is_admin),
        "待电子用印": ("合同待电子用印", "我负责用印", is_purchase or is_admin),
        "供应商制作中": ("待登记到货", "我是生产主管", is_asset_owner or is_admin),
        "到货验收中": ("待验收", "我是采购", is_purchase or is_admin),
    }
    rows = frappe.get_all("OA Purchase Order",
                          filters={"status": ["in", list(stages)]},
                          fields=["name", "status", "supplier", "total_amount", "modified"],
                          limit_page_length=0)
    items = []
    for row in rows:
        label, reason, allowed = stages[row.status]
        if not allowed:
            continue
        items.append(task_item("采购订单", f"{row.name} {label}",
                               f"{row.supplier or '供应商待定'} · {row.status}",
                               waiting_days(row.modified), PAYMENT_ROUTE if row.status == "到货验收中" else PROCUREMENT_ROUTE,
                               reason, row.name, row.total_amount, {"po": row.name}))
    return items


def _payment_tasks():
    """Payment periods whose conditions are met, or blocked and waiting on me."""
    from rayher_hr_payroll.api.procurement_chain import list_payment_work_items

    try:
        work_items = list_payment_work_items(limit=200) or []
    except Exception as exc:
        if not isinstance(exc, (frappe.PermissionError, frappe.ValidationError)):
            raise
        return []
    items = []
    for row in work_items:
        if not row.get("can_push_payment"):
            continue
        items.append(task_item("采购付款", f"{row.get('po')} {row.get('installment_name') or '付款期次'} 可提交付款",
                               f"金额 {float(row.get('amount') or 0):,.2f} · 条件已满足",
                               waiting_days(row.get("planned_date")), PAYMENT_ROUTE,
                               "我负责提交付款", str(row.get("po")), row.get("amount"),
                               {"po": row.get("po")}))
    return items


@frappe.whitelist()
def get_my_approval_queue(limit=12):
    """Everything waiting on the signed-in user, from every document type."""
    from rayher_hr_payroll.api import oa_entry

    summary = oa_entry.get_my_approval_summary()
    names = [name for category in summary["categories"] for name in category["requests"]]
    items = []
    if names:
        docs = frappe.get_all("OA Approval Request", filters={"name": ["in", names]},
                              fields=["name", "request_type", "subject", "employee_name", "owner", "department",
                                      "amount", "approved_amount", "leave_type", "duration_hours", "from_date",
                                      "to_date", "current_step_label", "modified"],
                              limit_page_length=0)
        steps = _steps_by_parent([row.name for row in docs])
        for row in docs:
            item = queue_item(row, steps.get(row.name, []))
            item["reason"] = "我是审批人"
            item["kind"] = row.request_type
            item["query"] = {"request": row.name}
            items.append(item)
    for extra in (_price_approval_tasks(), _purchase_order_tasks(), _payment_tasks()):
        items.extend(extra)
    items.sort(key=lambda row: (not row["overdue"], -row["waited_days"]))
    return {"total": len(items), "approval_total": summary["total"], "items": items[:int(limit or 12)]}


def request_progress(doc, steps):
    """Where a request of mine stands, and whether it came back for changes."""
    total = len(steps) or 1
    done = sum(1 for row in steps if row.get("status") in ("已通过", "已审批", "已完成", "已办理"))
    returned = next((row for row in steps if row.get("status") in ("已拒绝", "已退回", "退回")), None)
    return {
        "name": doc.get("name"),
        "request_type": doc.get("request_type"),
        "subject": doc.get("subject") or doc.get("name"),
        "amount": float(doc.get("approved_amount") or doc.get("amount") or 0),
        "status": doc.get("workflow_status"),
        "step_label": doc.get("current_step_label") or "",
        "done_steps": done,
        "total_steps": total,
        "returned": bool(returned),
        "returned_note": (returned or {}).get("note") or "",
        "route": ROUTE_BY_TYPE.get(doc.get("request_type"), "/approval/request-dashboard"),
    }


@frappe.whitelist()
def get_my_requests(limit=6):
    """Requests I submitted that are still running or came back to me."""
    user = _user()
    if user in {"", "guest"}:
        frappe.throw(frappe._("请先登录。"))
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    filters = {"workflow_status": ["in", ["待审批", "待办理", "草稿"]]}
    if employee:
        filters["employee"] = employee
    else:
        filters["owner"] = frappe.session.user
    docs = frappe.get_all("OA Approval Request", filters=filters,
                          fields=["name", "request_type", "subject", "amount", "approved_amount",
                                  "workflow_status", "current_step_label", "modified"],
                          order_by="modified desc", limit_page_length=int(limit or 6))
    steps = _steps_by_parent([row.name for row in docs])
    return {"items": [request_progress(row, steps.get(row.name, [])) for row in docs]}
