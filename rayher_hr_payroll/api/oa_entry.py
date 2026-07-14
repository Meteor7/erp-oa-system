import json

import frappe
from frappe.utils import now_datetime

from rayher_hr_payroll.oa_approval import (
    ADMIN_ASSET,
    IT_ASSET,
    OTHER_ASSET,
    REQUEST_EXPENSE_PAYMENT,
    REQUEST_LEAVE,
    ApprovalRouteError,
    build_route,
)

REQUEST_TYPES = [REQUEST_LEAVE, REQUEST_EXPENSE_PAYMENT]
ASSET_CATEGORIES = [ADMIN_ASSET, IT_ASSET, OTHER_ASSET]

STATUS_DRAFT = "\u8349\u7a3f"
STATUS_PENDING = "\u5f85\u5ba1\u6279"
STATUS_WAIT_HANDLE = "\u5f85\u529e\u7406"
STATUS_WAIT_FLOW = "\u5f85\u6d41\u8f6c"
STATUS_APPROVED = "\u5df2\u901a\u8fc7"
STATUS_HANDLED = "\u5df2\u529e\u7406"
STATUS_COMPLETED = "\u5df2\u5b8c\u6210"
STATUS_REJECTED = "\u5df2\u62d2\u7edd"
STATUS_PAID = "\u5df2\u4ed8\u6b3e"
ACTIVE_STATUSES = {STATUS_PENDING, STATUS_WAIT_HANDLE}
PRIVILEGED_ROLES = {"System Manager", "HR Manager", "HR User", "Accounts User"}
FINANCE_ROLES = {"System Manager", "Accounts User"}

SOURCE_MANUAL = "\u624b\u5de5\u65b0\u5efa"
SOURCE_PUSH = "\u6d88\u8d39\u660e\u7ec6\u4e0b\u63a8"

CD_WAIT_UPLOAD = "\u5f85\u4e0a\u4f20"
CD_UPLOADED = "\u5df2\u4e0a\u4f20\u53d1\u7968"
CD_WAIT_PUSH = "\u5f85\u4e0b\u63a8"
CD_PUSHED = "\u5df2\u4e0b\u63a8"
CD_REJECTED = "\u5df2\u9a73\u56de"

INVOICE_UPLOADED = "\u5df2\u4e0a\u4f20"
INVOICE_VERIFIED = "\u5df2\u9a8c\u8bc1"
INVOICE_DUPLICATE = "\u91cd\u590d\u53d1\u7968"

EXPENSE_CATEGORIES = [
    "\u673a\u7968",
    "\u4ea4\u901a/\u8f66\u7968",
    "\u5dee\u65c5\u8d39",
    "\u4f4f\u5bbf\u8d39",
    "\u4ea4\u901a\u8d39",
    "\u5dee\u65c5\u8865\u8d34",
    "\u9910\u996e\u8865\u8d34",
    "\u5458\u5de5\u798f\u5229\u8d39",
    "\u529e\u516c\u8d39",
    "\u54a8\u8be2\u8d39",
    "\u5f8b\u5e08\u8d39",
    "\u5370\u82b1\u7a0e",
    "\u8be2\u4ef7\u8d39",
    "\u529e\u516c\u7528\u54c1\u8d39",
    "\u5c55\u89c8\u8d39",
    "\u6837\u54c1\u8d39",
    "\u5de5\u7a0b\u8d39/\u4e13\u9879\u8d39",
    "\u4f19\u98df/\u71c3\u6c14\u8d39",
    "\u56fa\u5b9a\u8d44\u4ea7-\u751f\u4ea7\u8bbe\u5907",
    "\u56fa\u5b9a\u8d44\u4ea7-\u529e\u516c\u5bb6\u5177",
    "\u62a5\u544a\u8d39",
    "\u5b89\u5168\u6d4b\u8bd5\u8d39",
    "\u62db\u5f85\u8d39",
    "\u5feb\u9012\u8d39",
    "\u901a\u8baf\u8d39",
]
DEPARTMENTS = [
    "\u7814\u53d1\u90e8",
    "\u5e02\u573a\u90e8",
    "\u8d22\u52a1\u90e8",
    "IT\u90e8",
    "\u91c7\u8d2d\u90e8",
    "\u4ed3\u5e93",
    "\u9500\u552e\u90e8",
    "\u77e5\u8bc6\u4ea7\u6743\u90e8",
    "\u603b\u7ecf\u7406\u5ba4",
    "PMC",
    "\u8d28\u91cf\u90e8",
]
DOC_TYPES = [
    "\u975e\u56fa\u5b9a\u8d44\u4ea7",
    "\u56fa\u5b9a\u8d44\u4ea7-\u529e\u516c\u5bb6\u5177/\u4f4e\u503c\u6613\u8017\u54c1",
    "\u56fa\u5b9a\u8d44\u4ea7-\u751f\u4ea7\u8bbe\u5907",
]
URGENCY = ["\u4e00\u822c", "\u52a0\u6025"]
PAYMENT_TYPES = ["\u4ed8\u6b3e\u7533\u8bf7", "\u5bf9\u516c\u652f\u4ed8"]
PAYMENT_METHODS = ["\u94f6\u884c\u8f6c\u8d26", "\u73b0\u91d1\u652f\u4ed8"]
COMPANIES = ["\u67d0\u67d0\u5149\u534a\u5bfc\u4f53\u79d1\u6280\u6709\u9650\u516c\u53f8", "\u793a\u4f8b\u4f01\u4e1a025\u4e0a\u6d77\u6709\u9650\u516c\u53f8"]


def _clean(value):
    return str(value or "").strip()


def _to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() not in {"", "0", "false", "no"}


def _money(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _json_list(values):
    return json.dumps(list(values), ensure_ascii=False)


def _parse_json_list(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _parse_json(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _employee_context(user=None):
    user = user or frappe.session.user
    if user == "Guest":
        frappe.throw(frappe._("\u8bf7\u5148\u767b\u5f55\u3002"))
    row = frappe.db.get_value(
        "Employee", {"user_id": user}, ["name", "employee_name", "department", "reports_to"], as_dict=True
    )
    if not row:
        return {"employee": None, "employee_name": "", "department": "", "supervisor": ""}
    supervisor = ""
    if row.get("reports_to"):
        supervisor = frappe.db.get_value("Employee", row.reports_to, "employee_name") or row.reports_to
    return {
        "employee": row.name,
        "employee_name": row.employee_name or row.name,
        "department": row.department or "",
        "supervisor": supervisor,
    }


def _route_context(department=None, supervisor=None, asset_category=None):
    ctx = _employee_context()
    ctx["department"] = department or ctx.get("department") or ""
    ctx["supervisor"] = supervisor or ctx.get("supervisor") or ""
    ctx["asset_category"] = asset_category or OTHER_ASSET
    return ctx


def _step_pending_status(step):
    return STATUS_WAIT_HANDLE if step.get("mode") == "handle" else STATUS_PENDING


def _serialize_route_steps(steps, active=True):
    return [
        {
            "step_index": idx,
            "label": step["label"],
            "mode": step["mode"],
            "approvers": step["approvers"],
            "status": _step_pending_status(step) if active and idx == 1 else STATUS_WAIT_FLOW,
            "approved_by": [],
        }
        for idx, step in enumerate(steps, start=1)
    ]


def _serialize_doc_step(step):
    return {
        "step_index": int(step.step_index or 0),
        "label": step.label,
        "mode": step.mode,
        "approvers": _parse_json_list(step.approvers),
        "status": step.status,
        "approved_by": _parse_json_list(step.approved_by),
        "action_by": step.action_by,
        "acted_on": step.acted_on,
        "note": step.note,
    }


def _serialize_expense_line(row):
    return {
        "source_consumption": getattr(row, "source_consumption", None),
        "start_date": getattr(row, "start_date", None),
        "end_date": getattr(row, "end_date", None),
        "category": getattr(row, "category", None),
        "amount": getattr(row, "amount", 0),
        "description": getattr(row, "description", None),
        "attachment_count": getattr(row, "attachment_count", 0),
        "invoice_status": getattr(row, "invoice_status", None),
    }


def _serialize_invoice(row):
    return {
        "invoice_name": row.invoice_name,
        "invoice_file": row.invoice_file,
        "file_type": row.file_type,
        "file_size": row.file_size,
        "invoice_status": row.invoice_status,
        "uploaded_on": row.uploaded_on,
        "remark": row.remark,
    }


def _serialize_consumption(doc):
    return {
        "name": doc.name,
        "title": doc.title,
        "employee": doc.employee,
        "employee_name": doc.employee_name,
        "department": doc.department,
        "expense_date": doc.expense_date,
        "category": doc.category,
        "amount": doc.amount,
        "description": doc.description,
        "status": doc.status,
        "linked_request": doc.linked_request,
        "invoice_count": doc.invoice_count,
        "invoices": [_serialize_invoice(row) for row in doc.invoices],
        "creation": doc.creation,
        "modified": doc.modified,
    }


def _actor_names(user=None):
    user = user or frappe.session.user
    names = {user}
    full_name = frappe.db.get_value("User", user, "full_name")
    if full_name:
        names.add(full_name)
    ctx = _employee_context(user)
    for key in ("employee", "employee_name"):
        if ctx.get(key):
            names.add(ctx[key])
    return {str(name).strip() for name in names if str(name or "").strip()}


def _matched_approvers(step, user=None):
    actors = _actor_names(user)
    return [name for name in _parse_json_list(step.approvers) if name in actors]


def _current_step(doc):
    current = int(doc.current_step_index or 0)
    for step in doc.steps:
        if int(step.step_index or 0) == current:
            return step
    return None


def _can_act_on_current_step(doc, user=None):
    if doc.workflow_status not in ACTIVE_STATUSES:
        return False
    step = _current_step(doc)
    return bool(step and _matched_approvers(step, user))


def _kanban_status(workflow_status):
    if workflow_status == STATUS_DRAFT:
        return "draft"
    if workflow_status in ACTIVE_STATUSES:
        return "pending"
    if workflow_status == STATUS_COMPLETED:
        return "approved"
    if workflow_status == STATUS_REJECTED:
        return "rejected"
    if workflow_status == STATUS_PAID:
        return "paid"
    return "pending"


def _summarize_doc(doc):
    step = _current_step(doc)
    return {
        "name": doc.name,
        "request_type": doc.request_type,
        "employee": doc.employee,
        "employee_name": doc.employee_name,
        "department": doc.department,
        "supervisor": doc.supervisor,
        "company": getattr(doc, "company", None),
        "subject": doc.subject,
        "doc_type": getattr(doc, "doc_type", None),
        "urgency": getattr(doc, "urgency", None),
        "from_date": doc.from_date,
        "to_date": doc.to_date,
        "amount": doc.amount,
        "asset_category": doc.asset_category,
        "source_type": getattr(doc, "source_type", None) or SOURCE_MANUAL,
        "source_summary": getattr(doc, "source_summary", None),
        "from_consumption": (getattr(doc, "source_type", None) == SOURCE_PUSH),
        "payment_type": getattr(doc, "payment_type", None),
        "payment_method": getattr(doc, "payment_method", None),
        "bank_name": getattr(doc, "bank_name", None),
        "payee_name": getattr(doc, "payee_name", None),
        "branch": getattr(doc, "branch", None),
        "account_no": getattr(doc, "account_no", None),
        "paid_by": getattr(doc, "paid_by", None),
        "paid_on": getattr(doc, "paid_on", None),
        "reason": doc.reason,
        "workflow_status": doc.workflow_status,
        "kanban_status": _kanban_status(doc.workflow_status),
        "current_step_index": doc.current_step_index,
        "current_step_label": doc.current_step_label,
        "current_step_mode": step.mode if step else "",
        "can_act": _can_act_on_current_step(doc),
        "can_mark_paid": doc.request_type == REQUEST_EXPENSE_PAYMENT and doc.workflow_status == STATUS_COMPLETED and _is_finance_user(),
        "expense_lines": [_serialize_expense_line(row) for row in getattr(doc, "expense_lines", [])],
        "steps": [_serialize_doc_step(row) for row in doc.steps],
        "creation": doc.creation,
        "modified": doc.modified,
    }


def _load_request(name):
    if not name:
        frappe.throw(frappe._("\u7f3a\u5c11\u7533\u8bf7\u5355\u53f7\u3002"))
    return frappe.get_doc("OA Approval Request", name)


def _load_consumption(name):
    if not name:
        frappe.throw(frappe._("\u7f3a\u5c11\u6d88\u8d39\u660e\u7ec6\u7f16\u53f7\u3002"))
    return frappe.get_doc("OA Consumption Detail", name)


def _is_finance_user(user=None):
    return bool(set(frappe.get_roles(user or frappe.session.user)) & FINANCE_ROLES)


def _require_finance_user():
    if not _is_finance_user():
        frappe.throw(frappe._("\u53ea\u6709\u8d22\u52a1\u6216\u7cfb\u7edf\u7ba1\u7406\u5458\u53ef\u6267\u884c\u6b64\u64cd\u4f5c\u3002"))


def _advance_after_step(doc, step):
    rows = sorted(doc.steps, key=lambda row: int(row.step_index or 0))
    next_step = None
    for row in rows:
        if int(row.step_index or 0) > int(step.step_index or 0):
            next_step = row
            break
    if not next_step:
        doc.workflow_status = STATUS_COMPLETED
        doc.current_step_index = 0
        doc.current_step_label = ""
        return
    doc.workflow_status = STATUS_WAIT_HANDLE if next_step.mode == "handle" else STATUS_PENDING
    doc.current_step_index = next_step.step_index
    doc.current_step_label = next_step.label
    next_step.status = STATUS_WAIT_HANDLE if next_step.mode == "handle" else STATUS_PENDING


def _set_step_action(step, status, actor, note=None):
    step.status = status
    step.action_by = actor
    step.acted_on = now_datetime()
    if note:
        step.note = note


def _append_steps(doc, steps):
    doc.set("steps", [])
    for step in steps:
        doc.append(
            "steps",
            {
                "step_index": step["step_index"],
                "label": step["label"],
                "mode": step["mode"],
                "approvers": _json_list(step["approvers"]),
                "status": step["status"],
                "approved_by": _json_list([]),
            },
        )


def _normalize_expense_lines(expense_lines, fallback_amount=0, fallback_subject=None):
    rows = _parse_json(expense_lines, [])
    if not rows and _money(fallback_amount) > 0:
        rows = [{"category": fallback_subject or REQUEST_EXPENSE_PAYMENT, "amount": fallback_amount, "description": fallback_subject or ""}]
    normalized = []
    total = 0
    for row in rows or []:
        amount = _money(row.get("amount"))
        if amount <= 0:
            continue
        category = _clean(row.get("category")) or REQUEST_EXPENSE_PAYMENT
        normalized.append(
            {
                "source_consumption": row.get("source_consumption"),
                "start_date": row.get("start_date") or row.get("expense_date"),
                "end_date": row.get("end_date") or row.get("expense_date") or row.get("start_date"),
                "category": category,
                "amount": amount,
                "description": _clean(row.get("description") or row.get("desc")),
                "attachment_count": int(row.get("attachment_count") or row.get("invoice_count") or 0),
                "invoice_status": _clean(row.get("invoice_status")) or (INVOICE_UPLOADED if row.get("attachment_count") else ""),
            }
        )
        total += amount
    return normalized, total


def _set_expense_lines(doc, rows):
    doc.set("expense_lines", [])
    for row in rows:
        doc.append("expense_lines", row)


def _build_request_doc(
    *,
    request_type,
    subject=None,
    department=None,
    supervisor=None,
    asset_category=None,
    from_date=None,
    to_date=None,
    amount=None,
    reason=None,
    submit=True,
    expense_lines=None,
    company=None,
    doc_type=None,
    urgency=None,
    payment_type=None,
    payment_method=None,
    bank_name=None,
    payee_name=None,
    branch=None,
    account_no=None,
    source_type=None,
    source_summary=None,
):
    if request_type not in REQUEST_TYPES:
        frappe.throw(frappe._("\u4e0d\u652f\u6301\u7684 OA \u7533\u8bf7\u7c7b\u578b\u3002"))
    ctx = _route_context(department=department, supervisor=supervisor, asset_category=asset_category)
    route = preview_route(request_type, ctx["department"], ctx["supervisor"], ctx["asset_category"], active=submit)
    steps = route["steps"]
    if request_type == REQUEST_LEAVE and submit and (not from_date or not to_date):
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u8bf7\u5047\u5f00\u59cb\u548c\u7ed3\u675f\u65e5\u671f\u3002"))
    lines, total = _normalize_expense_lines(expense_lines, fallback_amount=amount, fallback_subject=subject)
    if request_type == REQUEST_EXPENSE_PAYMENT and submit and not lines:
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u8d39\u7528\u660e\u7ec6\u3002"))

    initial_status = steps[0]["status"] if submit else STATUS_DRAFT
    doc = frappe.get_doc(
        {
            "doctype": "OA Approval Request",
            "request_type": request_type,
            "workflow_status": initial_status,
            "employee": ctx.get("employee"),
            "employee_name": ctx.get("employee_name"),
            "department": ctx.get("department"),
            "supervisor": ctx.get("supervisor"),
            "company": company or COMPANIES[0],
            "subject": subject or request_type,
            "doc_type": doc_type or DOC_TYPES[0],
            "urgency": urgency or URGENCY[0],
            "from_date": from_date,
            "to_date": to_date,
            "amount": total if request_type == REQUEST_EXPENSE_PAYMENT else _money(amount),
            "asset_category": ctx.get("asset_category"),
            "source_type": source_type or SOURCE_MANUAL,
            "source_summary": source_summary or "",
            "payment_type": payment_type or PAYMENT_TYPES[0],
            "payment_method": payment_method or PAYMENT_METHODS[0],
            "bank_name": bank_name or "",
            "payee_name": payee_name or ctx.get("employee_name") or "",
            "branch": branch or "",
            "account_no": account_no or "",
            "reason": reason or "",
            "current_step_index": 1 if submit else 0,
            "current_step_label": steps[0]["label"] if submit else "",
        }
    )
    _append_steps(doc, steps)
    _set_expense_lines(doc, lines)
    doc.insert(ignore_permissions=True)
    return doc


def _submit_draft(doc):
    if doc.workflow_status != STATUS_DRAFT:
        return
    ctx = _route_context(department=doc.department, supervisor=doc.supervisor, asset_category=doc.asset_category)
    route = preview_route(doc.request_type, ctx["department"], ctx["supervisor"], ctx["asset_category"], active=True)
    _append_steps(doc, route["steps"])
    doc.workflow_status = route["steps"][0]["status"]
    doc.current_step_index = 1
    doc.current_step_label = route["steps"][0]["label"]


def _update_consumption_invoice_state(doc):
    invoices = list(getattr(doc, "invoices", []) or [])
    doc.invoice_count = len(invoices)
    if doc.status == CD_PUSHED:
        return
    if any(row.invoice_status == INVOICE_DUPLICATE for row in invoices):
        doc.status = CD_REJECTED
    elif invoices:
        doc.status = CD_WAIT_PUSH
    else:
        doc.status = CD_WAIT_UPLOAD


def _consumption_filters(view="mine", status=None):
    roles = set(frappe.get_roles(frappe.session.user))
    ctx = _employee_context()
    filters = {}
    if view == "all" and roles & PRIVILEGED_ROLES:
        filters = {}
    else:
        filters = {"employee": ctx.get("employee")} if ctx.get("employee") else {"owner": frappe.session.user}
    if status:
        filters["status"] = status
    return filters


@frappe.whitelist()
def get_options():
    roles = set(frappe.get_roles(frappe.session.user))
    return {
        "request_types": REQUEST_TYPES,
        "asset_categories": ASSET_CATEGORIES,
        "expense_categories": EXPENSE_CATEGORIES,
        "departments": DEPARTMENTS,
        "doc_types": DOC_TYPES,
        "urgencies": URGENCY,
        "payment_types": PAYMENT_TYPES,
        "payment_methods": PAYMENT_METHODS,
        "companies": COMPANIES,
        "context": _employee_context(),
        "can_manage_expense": bool(roles & FINANCE_ROLES),
        "can_see_all": bool(roles & PRIVILEGED_ROLES),
    }


@frappe.whitelist()
def preview_route(request_type, department=None, supervisor=None, asset_category=None, active=True):
    try:
        ctx = _route_context(department=department, supervisor=supervisor, asset_category=asset_category)
        steps = build_route(
            request_type,
            department=ctx["department"],
            supervisor=ctx["supervisor"],
            asset_category=ctx["asset_category"],
        )
        return {"context": ctx, "steps": _serialize_route_steps(steps, active=_to_bool(active))}
    except ApprovalRouteError as exc:
        frappe.throw(str(exc))


@frappe.whitelist(methods=["POST"])
def create_request(
    request_type,
    subject=None,
    department=None,
    supervisor=None,
    asset_category=None,
    from_date=None,
    to_date=None,
    amount=None,
    reason=None,
    submit=1,
    expense_lines=None,
    company=None,
    doc_type=None,
    urgency=None,
    payment_type=None,
    payment_method=None,
    bank_name=None,
    payee_name=None,
    branch=None,
    account_no=None,
):
    doc = _build_request_doc(
        request_type=request_type,
        subject=subject,
        department=department,
        supervisor=supervisor,
        asset_category=asset_category,
        from_date=from_date,
        to_date=to_date,
        amount=amount,
        reason=reason,
        submit=_to_bool(submit),
        expense_lines=expense_lines,
        company=company,
        doc_type=doc_type,
        urgency=urgency,
        payment_type=payment_type,
        payment_method=payment_method,
        bank_name=bank_name,
        payee_name=payee_name,
        branch=branch,
        account_no=account_no,
    )
    frappe.db.commit()
    return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def submit_request(name):
    doc = _load_request(name)
    if doc.workflow_status != STATUS_DRAFT:
        frappe.throw(frappe._("\u53ea\u6709\u8349\u7a3f\u72b6\u6001\u53ef\u63d0\u4ea4\u3002"))
    _submit_draft(doc)
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return _summarize_doc(doc)


@frappe.whitelist()
def list_requests(view="mine", limit=50, request_type=None):
    if request_type and request_type not in REQUEST_TYPES:
        frappe.throw(frappe._("\u4e0d\u652f\u6301\u7684 OA \u7533\u8bf7\u7c7b\u578b\u3002"))
    roles = set(frappe.get_roles(frappe.session.user))
    ctx = _employee_context()
    limit = min(int(limit or 50), 200)
    filters = {}
    if view == "pending":
        filters["workflow_status"] = ["in", list(ACTIVE_STATUSES)]
    elif view == "all" and roles & PRIVILEGED_ROLES:
        filters = {}
    else:
        filters = {"employee": ctx.get("employee")} if ctx.get("employee") else {"owner": frappe.session.user}
    if request_type:
        filters["request_type"] = request_type
    names = frappe.get_all(
        "OA Approval Request",
        filters=filters,
        fields=["name"],
        order_by="modified desc",
        limit_page_length=limit,
    )
    docs = [_load_request(row.name) for row in names]
    if view == "pending":
        docs = [doc for doc in docs if _can_act_on_current_step(doc)]
    return [_summarize_doc(doc) for doc in docs]


@frappe.whitelist()
def list_consumption_details(view="mine", status=None, limit=100):
    names = frappe.get_all(
        "OA Consumption Detail",
        filters=_consumption_filters(view=view, status=status),
        fields=["name"],
        order_by="modified desc",
        limit_page_length=min(int(limit or 100), 300),
    )
    return [_serialize_consumption(_load_consumption(row.name)) for row in names]


@frappe.whitelist(methods=["POST"])
def save_consumption_detail(name=None, title=None, category=None, expense_date=None, amount=None, department=None, description=None):
    if not _clean(title) or not _clean(category) or not expense_date or _money(amount) <= 0:
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u6d88\u8d39\u660e\u7ec6\u7684\u6807\u9898\u3001\u8d39\u7528\u9879\u76ee\u3001\u65e5\u671f\u548c\u91d1\u989d\u3002"))
    ctx = _employee_context()
    if name:
        doc = _load_consumption(name)
        if doc.status == CD_PUSHED:
            frappe.throw(frappe._("\u5df2\u4e0b\u63a8\u7684\u6d88\u8d39\u660e\u7ec6\u4e0d\u80fd\u4fee\u6539\u3002"))
    else:
        doc = frappe.get_doc({"doctype": "OA Consumption Detail"})
        doc.employee = ctx.get("employee")
        doc.employee_name = ctx.get("employee_name")
    doc.title = _clean(title)
    doc.category = _clean(category)
    doc.expense_date = expense_date
    doc.amount = _money(amount)
    doc.department = _clean(department) or ctx.get("department")
    doc.description = _clean(description)
    _update_consumption_invoice_state(doc)
    if name:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return _serialize_consumption(doc)


@frappe.whitelist(methods=["POST"])
def add_invoice(
    consumption,
    invoice_name,
    invoice_file=None,
    file_type=None,
    file_size=None,
    invoice_status=INVOICE_UPLOADED,
    remark=None,
):
    doc = _load_consumption(consumption)
    if doc.status == CD_PUSHED:
        frappe.throw(frappe._("\u5df2\u4e0b\u63a8\u7684\u6d88\u8d39\u660e\u7ec6\u4e0d\u80fd\u518d\u6dfb\u52a0\u53d1\u7968\u3002"))
    if not _clean(invoice_name):
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u53d1\u7968\u540d\u79f0\u3002"))
    doc.append(
        "invoices",
        {
            "invoice_name": _clean(invoice_name),
            "invoice_file": invoice_file,
            "file_type": file_type or "",
            "file_size": file_size or "",
            "invoice_status": invoice_status or INVOICE_UPLOADED,
            "uploaded_on": now_datetime(),
            "remark": remark or "",
        },
    )
    _update_consumption_invoice_state(doc)
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return _serialize_consumption(doc)


@frappe.whitelist(methods=["POST"])
def push_consumption_to_request(consumption_names, payment_info=None, submit=0):
    names = _parse_json(consumption_names, [])
    if not names:
        frappe.throw(frappe._("\u8bf7\u9009\u62e9\u8981\u4e0b\u63a8\u7684\u6d88\u8d39\u660e\u7ec6\u3002"))
    docs = [_load_consumption(name) for name in names]
    for doc in docs:
        if doc.status == CD_PUSHED:
            frappe.throw(frappe._("\u6d88\u8d39\u660e\u7ec6 {0} \u5df2\u4e0b\u63a8\u3002").format(doc.name))
        if not doc.invoices:
            frappe.throw(frappe._("\u6d88\u8d39\u660e\u7ec6 {0} \u8bf7\u5148\u4e0a\u4f20\u53d1\u7968\u3002").format(doc.name))
        if any(row.invoice_status == INVOICE_DUPLICATE for row in doc.invoices):
            frappe.throw(frappe._("\u6d88\u8d39\u660e\u7ec6 {0} \u5b58\u5728\u91cd\u590d\u53d1\u7968\uff0c\u4e0d\u80fd\u4e0b\u63a8\u3002").format(doc.name))
    info = _parse_json(payment_info, {}) or {}
    first = docs[0]
    expense_lines = [
        {
            "source_consumption": doc.name,
            "expense_date": doc.expense_date,
            "category": doc.category,
            "amount": doc.amount,
            "description": doc.description or doc.title,
            "attachment_count": len(doc.invoices),
            "invoice_status": INVOICE_VERIFIED if all(row.invoice_status == INVOICE_VERIFIED for row in doc.invoices) else INVOICE_UPLOADED,
        }
        for doc in docs
    ]
    doc = _build_request_doc(
        request_type=REQUEST_EXPENSE_PAYMENT,
        subject=info.get("subject") or ("\u6d88\u8d39\u660e\u7ec6\u4e0b\u63a8-" + first.title),
        department=info.get("department") or first.department,
        supervisor=info.get("supervisor"),
        asset_category=info.get("asset_category") or OTHER_ASSET,
        amount=sum(_money(item["amount"]) for item in expense_lines),
        reason=info.get("reason") or "\u7531 {0} \u6761\u6d88\u8d39\u660e\u7ec6\u4e0b\u63a8\u751f\u6210".format(len(docs)),
        submit=_to_bool(submit),
        expense_lines=expense_lines,
        company=info.get("company"),
        doc_type=info.get("doc_type"),
        urgency=info.get("urgency"),
        payment_type=info.get("payment_type"),
        payment_method=info.get("payment_method"),
        bank_name=info.get("bank_name"),
        payee_name=info.get("payee_name"),
        branch=info.get("branch"),
        account_no=info.get("account_no"),
        source_type=SOURCE_PUSH,
        source_summary="\u3001".join(doc.name for doc in docs),
    )
    for cd in docs:
        cd.status = CD_PUSHED
        cd.linked_request = doc.name
        cd.save(ignore_permissions=True)
    frappe.db.commit()
    return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def action_request(name, action="approve", note=None):
    doc = _load_request(name)
    step = _current_step(doc)
    if not step or doc.workflow_status not in ACTIVE_STATUSES:
        frappe.throw(frappe._("\u5f53\u524d\u7533\u8bf7\u4e0d\u5728\u53ef\u5904\u7406\u72b6\u6001\u3002"))
    matched = _matched_approvers(step)
    if not matched:
        frappe.throw(frappe._("\u5f53\u524d\u8282\u70b9\u4e0d\u5c5e\u4e8e\u4f60\u5904\u7406\u3002"))
    actor = sorted(_actor_names())[0]
    if action == "reject":
        _set_step_action(step, STATUS_REJECTED, actor, note)
        doc.workflow_status = STATUS_REJECTED
        doc.current_step_label = ""
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return _summarize_doc(doc)
    if action != "approve":
        frappe.throw(frappe._("\u4e0d\u652f\u6301\u7684\u5904\u7406\u52a8\u4f5c\u3002"))
    approved_by = set(_parse_json_list(step.approved_by))
    approved_by.update(matched)
    step.approved_by = _json_list(sorted(approved_by))
    if step.mode == "all" and not set(_parse_json_list(step.approvers)).issubset(approved_by):
        step.action_by = actor
        step.acted_on = now_datetime()
        if note:
            step.note = note
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return _summarize_doc(doc)
    done_status = STATUS_HANDLED if step.mode == "handle" else STATUS_APPROVED
    _set_step_action(step, done_status, actor, note)
    _advance_after_step(doc, step)
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def mark_paid(name, note=None):
    _require_finance_user()
    doc = _load_request(name)
    if doc.request_type != REQUEST_EXPENSE_PAYMENT:
        frappe.throw(frappe._("\u53ea\u6709\u8d39\u7528\u4ed8\u6b3e/\u62a5\u9500\u5355\u53ef\u6807\u8bb0\u4ed8\u6b3e\u3002"))
    if doc.workflow_status != STATUS_COMPLETED:
        frappe.throw(frappe._("\u53ea\u6709\u5ba1\u6279\u5df2\u901a\u8fc7\u7684\u5355\u636e\u53ef\u6807\u8bb0\u4ed8\u6b3e\u3002"))
    doc.workflow_status = STATUS_PAID
    doc.paid_by = sorted(_actor_names())[0]
    doc.paid_on = now_datetime()
    if note:
        doc.reason = ((doc.reason or "") + "\n" + "\u4ed8\u6b3e\u5907\u6ce8\uff1a" + note).strip()
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return _summarize_doc(doc)
