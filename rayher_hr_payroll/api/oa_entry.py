import json
from contextlib import ExitStack
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import frappe
from frappe.utils import now_datetime

from rayher_hr_payroll.invoice_ocr import service as invoice_service
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
SOURCE_INVOICE_PUSH = "发票下推"
OPERATION_LOG_LIMIT = 100
REPORT_LIMIT = 1000

CD_WAIT_UPLOAD = "\u5f85\u4e0a\u4f20"
CD_UPLOADED = "\u5df2\u4e0a\u4f20\u53d1\u7968"
CD_WAIT_PUSH = "\u5f85\u4e0b\u63a8"
CD_PUSHED = "\u5df2\u4e0b\u63a8"
CD_REJECTED = "\u5df2\u9a73\u56de"

INVOICE_UPLOADED = "\u5df2\u4e0a\u4f20"
INVOICE_VERIFIED = "\u5df2\u9a8c\u8bc1"
INVOICE_CONFIRMED = "\u5df2\u786e\u8ba4"
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
PAYMENT_PERSONAL = "支付个人"
PAYMENT_PERSONAL_LEGACY = "付款申请"
PAYMENT_TYPES = [PAYMENT_PERSONAL, "对公支付"]
PAYMENT_METHODS = ["\u94f6\u884c\u8f6c\u8d26", "\u73b0\u91d1\u652f\u4ed8"]
COMPANIES = ["\u67d0\u67d0\u5149\u534a\u5bfc\u4f53\u79d1\u6280\u6709\u9650\u516c\u53f8", "\u793a\u4f8b\u4f01\u4e1a025\u4e0a\u6d77\u6709\u9650\u516c\u53f8"]


def _clean(value):
    return str(value or "").strip()


def _display_payment_type(value):
    value = _clean(value)
    return PAYMENT_PERSONAL if value == PAYMENT_PERSONAL_LEGACY else value


def _canonical_payment_type(value):
    value = _display_payment_type(value)
    return value if value in PAYMENT_TYPES else PAYMENT_TYPES[0]


def _bounded_optional_text(value, label, limit):
    if value is None:
        return ""
    if not isinstance(value, str):
        frappe.throw(frappe._("{0}格式无效。").format(label))
    value = value.strip()
    if len(value) > limit:
        if label == "无票原因":
            frappe.throw(frappe._("无票原因不能超过 1000 个字符。"))
        frappe.throw(frappe._("{0}过长。").format(label))
    return value


def _to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() not in {"", "0", "false", "no"}


def _money(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _optional_money(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


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


def _operation_events(doc):
    raw = getattr(doc, "operation_log", None) or "[]"
    try:
        events = json.loads(raw) if isinstance(raw, str) else list(raw)
    except (TypeError, ValueError):
        events = []
    return events if isinstance(events, list) else []


def _append_request_event(doc, action, from_status, to_status, note="", details=None):
    note = _bounded_optional_text(note, "操作说明", 500)
    events = _operation_events(doc)
    event = {
        "action": str(action),
        "actor": frappe.session.user,
        "acted_on": str(now_datetime()),
        "from_status": str(from_status or ""),
        "to_status": str(to_status or ""),
        "note": note,
    }
    if details:
        event["details"] = details
    events.append(event)
    doc.operation_log = json.dumps(events[-OPERATION_LOG_LIMIT:], ensure_ascii=False)
    return event


def _invoice_names(value):
    rows = _parse_json(value, None)
    if not isinstance(rows, list) or not rows or len(rows) > 100:
        frappe.throw(frappe._("请选择 1 到 100 张发票。"))
    names = []
    seen = set()
    for item in rows:
        if not isinstance(item, str):
            frappe.throw(frappe._("发票标识格式无效。"))
        name = item.strip()
        if not name or len(name) > 140 or "\x00" in name:
            frappe.throw(frappe._("发票标识格式无效。"))
        if name not in seen:
            seen.add(name)
            names.append(name)
    if not names:
        frappe.throw(frappe._("请选择要操作的发票。"))
    return names


DRAFT_REASON_JSON_MAX_BYTES = 64 * 1024
DRAFT_REASON_MAX_ITEMS = 100


class _JSONObjectPairs(list):
    pass


class _DuplicateJSONKey(ValueError):
    pass


def _reason_json_error():
    frappe.throw(
        frappe._(
            "\u8d39\u7528\u660e\u7ec6\u5dee\u5f02\u8bf4\u660e\u5fc5\u987b\u662f\u6709\u6548\u7684 JSON \u5bf9\u8c61\u3002"
        )
    )


def _check_reason_json_size(raw):
    if len(raw) > DRAFT_REASON_JSON_MAX_BYTES:
        frappe.throw(
            frappe._(
                "\u8d39\u7528\u660e\u7ec6\u5dee\u5f02\u8bf4\u660e JSON \u4e0d\u80fd\u8d85\u8fc7 64KB\u3002"
            )
        )


def _reject_json_constant(_value):
    raise ValueError


def _json_object_pairs(pairs):
    seen = set()
    result = _JSONObjectPairs()
    for key, value in pairs:
        if key in seen:
            raise _DuplicateJSONKey
        seen.add(key)
        result.append((key, value))
    return result


def _strict_reason_pairs(value):
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        try:
            raw = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError):
            _reason_json_error()
        _check_reason_json_size(raw)
        pairs = list(value.items())
    elif isinstance(value, str):
        try:
            raw = value.encode("utf-8")
        except UnicodeEncodeError:
            _reason_json_error()
        _check_reason_json_size(raw)
        try:
            parsed = json.loads(
                value,
                object_pairs_hook=_json_object_pairs,
                parse_constant=_reject_json_constant,
            )
        except _DuplicateJSONKey:
            frappe.throw(
                frappe._(
                    "\u8d39\u7528\u660e\u7ec6\u5dee\u5f02\u8bf4\u660e\u4e0d\u80fd\u5305\u542b\u91cd\u590d\u952e\u3002"
                )
            )
        except (TypeError, ValueError):
            _reason_json_error()
        if not isinstance(parsed, _JSONObjectPairs):
            _reason_json_error()
        pairs = list(parsed)
    else:
        _reason_json_error()
    return pairs


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
        "action_by": getattr(step, "action_by", None),
        "acted_on": getattr(step, "acted_on", None),
        "note": getattr(step, "note", None),
    }


def _source_value(source, fieldname, default=None):
    if isinstance(source, dict):
        return source.get(fieldname, default)
    return getattr(source, fieldname, default)


def _serialize_expense_line(row):
    legacy_category = getattr(row, "category", None)
    legacy_description = getattr(row, "description", None)
    legacy_date = getattr(row, "start_date", None)
    legacy_amount = getattr(row, "amount", 0)
    invoice_category = getattr(row, "invoice_category", None) or legacy_category
    project_name = getattr(row, "project_name", None) or legacy_description
    issue_date = getattr(row, "issue_date", None) or legacy_date
    total_amount = getattr(row, "total_amount", None)
    if total_amount in (None, ""):
        total_amount = legacy_amount
    return {
        "source_consumption": getattr(row, "source_consumption", None),
        "source_invoice": getattr(row, "source_invoice", None),
        "line_key": getattr(row, "line_key", None),
        "invoice_category": invoice_category or "",
        "project_name": project_name or "",
        "expense_item": _source_value(row, "expense_item") or "",
        "no_invoice_reason": _source_value(row, "no_invoice_reason") or "",
        "issue_date": issue_date,
        "invoice_number": getattr(row, "invoice_number", None) or "",
        "amount_before_tax": getattr(row, "amount_before_tax", None),
        "tax_amount": getattr(row, "tax_amount", None),
        "total_amount": total_amount,
        "invoice_difference_reason": getattr(row, "invoice_difference_reason", None),
        "start_date": getattr(row, "start_date", None),
        "end_date": getattr(row, "end_date", None),
        "category": legacy_category,
        "amount": legacy_amount,
        "description": legacy_description,
        "attachment_count": getattr(row, "attachment_count", 0),
        "invoice_status": getattr(row, "invoice_status", None),
    }

def _group_money(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _group_expense_sources(rows, invoices_by_key=None):
    grouped = {}
    invoices_by_key = invoices_by_key or {}
    amount_fields = ("amount_before_tax", "tax_amount", "total_amount")
    for index, source in enumerate(rows or []):
        line_key = _clean(_source_value(source, "line_key")) or f"row-{index + 1}"
        project_name = _clean(_source_value(source, "project_name"))
        expense_item = _clean(_source_value(source, "expense_item"))
        group_key = f"project:{project_name}" if project_name else f"line:{line_key}"
        group = grouped.get(group_key)
        if group is None:
            group = {
                "group_key": group_key,
                "project_name": project_name,
                "expense_item": "",
                "expense_items": [],
                "needs_expense_item": True,
                "source_line_keys": [],
                "source_lines": [],
                "source_count": 0,
                "invoice_source_count": 0,
                "manual_source_count": 0,
                "invoices": [],
                "_amounts": {fieldname: [] for fieldname in amount_fields},
            }
            grouped[group_key] = group
        normalized_source = dict(source) if isinstance(source, dict) else _serialize_expense_line(source)
        normalized_source["line_key"] = line_key
        normalized_source["project_name"] = project_name
        normalized_source["expense_item"] = expense_item
        group["source_line_keys"].append(line_key)
        group["source_lines"].append(normalized_source)
        group["source_count"] += 1
        source_invoice = _clean(_source_value(source, "source_invoice"))
        if source_invoice:
            group["invoice_source_count"] += 1
        else:
            group["manual_source_count"] += 1
        if expense_item and expense_item not in group["expense_items"]:
            group["expense_items"].append(expense_item)
        for fieldname in amount_fields:
            value = _source_value(source, fieldname)
            if fieldname == "total_amount" and value in (None, ""):
                value = _source_value(source, "amount")
            parsed = _group_money(value)
            if parsed is not None:
                group["_amounts"][fieldname].append(parsed)
        group["invoices"].extend(list(invoices_by_key.get(line_key) or []))
    result = []
    for group in grouped.values():
        for fieldname in amount_fields:
            values = group["_amounts"][fieldname]
            group[fieldname] = sum(values, Decimal("0.00")).quantize(Decimal("0.01")) if values else None
        group.pop("_amounts", None)
        if len(group["expense_items"]) == 1:
            group["expense_item"] = group["expense_items"][0]
            group["needs_expense_item"] = False
        result.append(group)
    return result



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
    invoice_summary = invoice_service.request_invoice_summary(doc)
    expense_lines = [_serialize_expense_line(row) for row in getattr(doc, "expense_lines", [])]
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
        "from_invoice_push": (getattr(doc, "source_type", None) == SOURCE_INVOICE_PUSH),
        "payment_type": _display_payment_type(getattr(doc, "payment_type", None)),
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
        "can_withdraw": doc.workflow_status not in {STATUS_DRAFT, STATUS_PAID} and invoice_service.invoice_permissions.can_edit_request(doc, frappe.session.user),
        "can_withdraw_payment": doc.workflow_status == STATUS_PAID and _is_finance_user(),
        "invoice_count": invoice_summary["invoice_count"],
        "invoice_status": invoice_summary["invoice_status"],
        "invoice_search_text": invoice_summary.get("invoice_search_text", ""),
        "invoice_categories": invoice_summary.get("invoice_categories", []),
        "invoice_project_names": invoice_summary.get("invoice_project_names", []),
        "invoice_numbers": invoice_summary.get("invoice_numbers", []),
        "no_invoice_reason": getattr(doc, "no_invoice_reason", None) or "",
        "operation_log": _operation_events(doc),
        "expense_lines": expense_lines,
        "project_groups": _group_expense_sources(expense_lines),
        "steps": [_serialize_doc_step(row) for row in doc.steps],
        "creation": doc.creation,
        "modified": doc.modified,
    }


def _load_request(name, *, current=False):
    if not name:
        frappe.throw(frappe._("\u7f3a\u5c11\u7533\u8bf7\u5355\u53f7\u3002"))
    if current:
        return invoice_service._current_doc("OA Approval Request", name)
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


def _uuid4_text(value):
    try:
        parsed = UUID(str(value or ""))
    except (ValueError, TypeError, AttributeError):
        return ""
    return str(parsed) if parsed.version == 4 else ""


def _expense_line_key(row, seen):
    supplied = row.get("line_key")
    supplied = supplied.strip() if isinstance(supplied, str) else ""
    source_invoice = _clean(row.get("source_invoice"))
    source_consumption = _clean(row.get("source_consumption"))
    if source_invoice:
        candidate = str(uuid5(NAMESPACE_URL, f"rayher:invoice:{source_invoice}"))
        if candidate not in seen:
            seen.add(candidate)
            return candidate
    if source_consumption:
        candidate = supplied if supplied and len(supplied) <= 140 else str(
            uuid5(NAMESPACE_URL, f"rayher:consumption:{source_consumption}")
        )
        if candidate not in seen:
            seen.add(candidate)
            return candidate
    candidate = _uuid4_text(supplied)
    if candidate and candidate not in seen:
        seen.add(candidate)
        return candidate
    while True:
        candidate = str(uuid4())
        if candidate not in seen:
            seen.add(candidate)
            return candidate


def _difference_reason(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        frappe.throw(frappe._("费用明细的发票金额差异说明格式无效。"))
    value = value.strip()
    if len(value) > 500:
        frappe.throw(frappe._("费用明细的发票金额差异说明不能超过 500 个字符。"))
    return value


def _normalize_expense_lines(expense_lines, fallback_amount=0, fallback_subject=None):
    rows = _parse_json(expense_lines, [])
    if not rows and _money(fallback_amount) > 0:
        rows = [{"category": fallback_subject or REQUEST_EXPENSE_PAYMENT, "amount": fallback_amount, "description": fallback_subject or ""}]
    normalized = []
    total = 0
    seen_line_keys = set()
    for row in rows or []:
        source_invoice = _clean(row.get("source_invoice"))
        total_value = row.get("total_amount")
        if total_value in (None, ""):
            total_value = row.get("amount")
        amount = _money(total_value)
        if amount <= 0 and not source_invoice:
            continue
        invoice_category = _clean(row.get("invoice_category"))
        project_name = _clean(row.get("project_name"))
        expense_item = _clean(row.get("expense_item"))
        description = _clean(row.get("description") or row.get("desc"))
        issue_date = row.get("issue_date") or row.get("start_date") or row.get("expense_date")
        category = invoice_category or expense_item or _clean(row.get("category")) or project_name or REQUEST_EXPENSE_PAYMENT
        normalized.append(
            {
                "source_consumption": row.get("source_consumption"),
                "source_invoice": source_invoice or None,
                "line_key": _expense_line_key(row, seen_line_keys),
                "invoice_category": invoice_category,
                "project_name": project_name,
                "expense_item": expense_item,
                "no_invoice_reason": _bounded_optional_text(row.get("no_invoice_reason"), "无票原因", 1000),
                "issue_date": issue_date,
                "invoice_number": _clean(row.get("invoice_number")),
                "amount_before_tax": _optional_money(row.get("amount_before_tax")),
                "tax_amount": _optional_money(row.get("tax_amount")),
                "total_amount": amount,
                "start_date": issue_date,
                "end_date": row.get("end_date") or issue_date,
                "category": category,
                "amount": amount,
                "description": (project_name if source_invoice else description) or project_name,
                "attachment_count": int(row.get("attachment_count") or row.get("invoice_count") or (1 if source_invoice else 0)),
                "invoice_status": _clean(row.get("invoice_status")) or (INVOICE_CONFIRMED if source_invoice else (INVOICE_UPLOADED if row.get("attachment_count") else "")),
                "invoice_difference_reason": _difference_reason(row.get("invoice_difference_reason")),
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
    no_invoice_reason=None,
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
            "payment_type": _canonical_payment_type(payment_type),
            "payment_method": payment_method or PAYMENT_METHODS[0],
            "bank_name": bank_name or "",
            "payee_name": payee_name or ctx.get("employee_name") or "",
            "branch": branch or "",
            "account_no": account_no or "",
            "invoice_count": 0,
            "invoice_status": "无发票",
            "no_invoice_reason": no_invoice_reason or "",
            "reason": reason or "",
            "operation_log": "[]",
            "current_step_index": 1 if submit else 0,
            "current_step_label": steps[0]["label"] if submit else "",
        }
    )
    _append_steps(doc, steps)
    _set_expense_lines(doc, lines)
    doc.insert(ignore_permissions=True)
    return doc


def _validate_expense_project_groups(doc):
    if getattr(doc, "request_type", None) != REQUEST_EXPENSE_PAYMENT:
        return []
    sources = [_serialize_expense_line(row) for row in list(getattr(doc, "expense_lines", []) or [])]
    groups = _group_expense_sources(sources)
    for group in groups:
        if not _clean(group.get("project_name")):
            frappe.throw(frappe._("提交前必须填写每项费用的项目名称。"))
        if group.get("needs_expense_item"):
            frappe.throw(frappe._("提交前必须为每个项目填写一致的费用项目。"))
    for source in sources:
        if not _clean(source.get("source_invoice")) and not _clean(source.get("no_invoice_reason")):
            frappe.throw(frappe._("手工费用提交前必须填写无票原因。"))
    return groups


def _submit_draft(doc):
    if doc.workflow_status != STATUS_DRAFT:
        return
    old_status = doc.workflow_status
    if doc.request_type == REQUEST_LEAVE and (not doc.from_date or not doc.to_date):
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u8bf7\u5047\u5f00\u59cb\u548c\u7ed3\u675f\u65e5\u671f\u3002"))
    if doc.request_type == REQUEST_EXPENSE_PAYMENT and not list(getattr(doc, "expense_lines", []) or []):
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u8d39\u7528\u660e\u7ec6\u3002"))
    _validate_expense_project_groups(doc)
    summary = invoice_service.validate_request_invoices(doc, submitting=True)
    if isinstance(summary, dict):
        doc.invoice_count = summary.get("invoice_count", 0)
        doc.invoice_status = summary.get("invoice_status", "")
    ctx = _route_context(department=doc.department, supervisor=doc.supervisor, asset_category=doc.asset_category)
    route = preview_route(doc.request_type, ctx["department"], ctx["supervisor"], ctx["asset_category"], active=True)
    _append_steps(doc, route["steps"])
    doc.workflow_status = route["steps"][0]["status"]
    doc.current_step_index = 1
    doc.current_step_label = route["steps"][0]["label"]
    _append_request_event(doc, "提交申请", old_status, doc.workflow_status)


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
    context = _employee_context()
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
        "context": context,
        "current_applicant": {
            "employee": context.get("employee"),
            "employee_name": context.get("employee_name") or "",
            "user": frappe.session.user,
        },
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
    invoice_batch=None,
    no_invoice_reason=None,
):
    requested_submit = _to_bool(submit)
    batch_name = _bounded_optional_text(invoice_batch, "发票批次", 140)
    no_invoice_reason = _bounded_optional_text(no_invoice_reason, "无票原因", 1000)
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
        submit=False,
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
        no_invoice_reason=no_invoice_reason,
    )
    if batch_name:
        doc = invoice_service.attach_batch_to_request(batch_name, doc)
    draft_summary = invoice_service.validate_request_invoices(doc, submitting=False)
    if isinstance(draft_summary, dict):
        doc.invoice_count = draft_summary.get("invoice_count", 0)
        doc.invoice_status = draft_summary.get("invoice_status", "")
    if requested_submit:
        _submit_draft(doc)
    doc.save(ignore_permissions=True)
    return _summarize_doc(doc)


def _draft_source_rows(source_lines):
    rows = _parse_json(source_lines, None)
    if not isinstance(rows, list) or len(rows) > 200:
        frappe.throw(frappe._("报销费用明细格式无效，单次最多 200 行。"))
    for row in rows:
        if not isinstance(row, dict):
            frappe.throw(frappe._("报销费用明细格式无效。"))
    return rows


def _manual_expense_source(payload, existing=None):
    source = dict(existing or {})
    for fieldname in (
        "project_name", "expense_item", "issue_date", "total_amount",
        "description", "no_invoice_reason", "line_key",
    ):
        if fieldname in payload:
            source[fieldname] = payload.get(fieldname)
    project_name = _bounded_optional_text(source.get("project_name"), "项目名称", 1000)
    expense_item = _bounded_optional_text(source.get("expense_item"), "费用项目", 140)
    issue_date = _clean(source.get("issue_date"))
    total_amount = _optional_money(source.get("total_amount"))
    description = _bounded_optional_text(source.get("description"), "费用说明", 1000)
    no_invoice_reason = _bounded_optional_text(source.get("no_invoice_reason"), "无票原因", 1000)
    if not project_name:
        frappe.throw(frappe._("手工费用必须填写项目名称。"))
    if not expense_item:
        frappe.throw(frappe._("手工费用必须填写费用项目。"))
    if not issue_date:
        frappe.throw(frappe._("手工费用必须填写日期。"))
    if total_amount is None or total_amount <= 0:
        frappe.throw(frappe._("手工费用金额必须大于 0。"))
    if not description:
        frappe.throw(frappe._("手工费用必须填写费用说明。"))
    if not no_invoice_reason:
        frappe.throw(frappe._("手工费用必须填写无票原因。"))
    source.update(
        {
            "source_invoice": None,
            "source_consumption": None,
            "project_name": project_name,
            "expense_item": expense_item,
            "no_invoice_reason": no_invoice_reason,
            "invoice_category": "",
            "issue_date": issue_date,
            "invoice_number": "",
            "amount_before_tax": None,
            "tax_amount": None,
            "total_amount": total_amount,
            "category": expense_item,
            "amount": total_amount,
            "description": description,
            "start_date": issue_date,
            "end_date": issue_date,
            "attachment_count": 0,
            "invoice_status": "",
            "invoice_difference_reason": "",
        }
    )
    normalized, _total = _normalize_expense_lines([source])
    if len(normalized) != 1:
        frappe.throw(frappe._("手工费用明细无效。"))
    return normalized[0]


def _updated_invoice_source(existing, payload):
    source = dict(existing)
    project_value = payload.get("project_name") if "project_name" in payload else source.get("project_name")
    item_value = payload.get("expense_item") if "expense_item" in payload else source.get("expense_item")
    source["project_name"] = _bounded_optional_text(project_value, "项目名称", 1000)
    source["expense_item"] = _bounded_optional_text(item_value, "费用项目", 140)
    source["no_invoice_reason"] = ""
    source["description"] = source["project_name"]
    return source


@frappe.whitelist(methods=["POST"])
def save_draft_expense_sources(name, source_lines):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    payload_rows = _draft_source_rows(source_lines)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        invoice_service._request_permission(doc, "edit", current=True)
        if doc.request_type != REQUEST_EXPENSE_PAYMENT:
            frappe.throw(frappe._("只有费用付款/报销单可以编辑费用明细。"))
        if doc.workflow_status != STATUS_DRAFT:
            frappe.throw(frappe._("只有草稿状态可以编辑费用明细。"))
        current_rows = [_serialize_expense_line(row) for row in list(getattr(doc, "expense_lines", []) or [])]
        current_by_key = {_clean(row.get("line_key")): row for row in current_rows if _clean(row.get("line_key"))}
        invoice_keys = {key for key, row in current_by_key.items() if _clean(row.get("source_invoice"))}
        seen_keys = set()
        prepared = []
        invoice_sources = []
        for payload in payload_rows:
            line_key = _clean(payload.get("line_key"))
            existing = current_by_key.get(line_key) if line_key else None
            if line_key and existing is None:
                frappe.throw(frappe._("费用明细不属于该报销单。"))
            if line_key in seen_keys:
                frappe.throw(frappe._("费用明细不能重复。"))
            supplied_invoice = _clean(payload.get("source_invoice"))
            existing_invoice = _clean(existing.get("source_invoice")) if existing else ""
            if existing_invoice:
                if supplied_invoice and supplied_invoice != existing_invoice:
                    frappe.throw(frappe._("费用明细不属于该报销单。"))
                source = _updated_invoice_source(existing, payload)
                invoice_sources.append(source)
            else:
                if supplied_invoice:
                    frappe.throw(frappe._("费用明细不属于该报销单。"))
                source = _manual_expense_source(payload, existing)
            prepared.append(source)
            seen_keys.add(_clean(source.get("line_key")))
        if invoice_keys - seen_keys:
            frappe.throw(frappe._("发票费用不能在草稿编辑中删除，请使用撤回发票操作。"))
        with ExitStack() as record_locks:
            invoice_names = sorted({_clean(row.get("source_invoice")) for row in invoice_sources if _clean(row.get("source_invoice"))})
            for invoice_name in invoice_names:
                record_locks.enter_context(invoice_service._transaction_lock("record", invoice_name))
            records = {}
            for invoice_name in invoice_names:
                record = invoice_service._require_record(invoice_name, write=True, current=True)
                records[invoice_name] = record
            for source in invoice_sources:
                invoice_name = _clean(source.get("source_invoice"))
                record = records[invoice_name]
                if _clean(getattr(record, "request", None)) != doc.name or _clean(getattr(record, "expense_line_key", None)) != _clean(source.get("line_key")):
                    frappe.throw(frappe._("发票关联已变化，请刷新后重试。"))
                project_name = _clean(source.get("project_name"))
                if _clean(getattr(record, "project_name", None)) != project_name:
                    old_status = getattr(record, "recognition_status", None)
                    record.project_name = project_name
                    invoice_service._append_record_event(record, "报销草稿调整", old_status, old_status, doc.name)
                    invoice_service._save(record)
            _set_expense_lines(doc, prepared)
            doc.amount = round(sum(_money(row.get("total_amount")) for row in prepared), 2)
            _append_request_event(
                doc,
                "编辑报销草稿",
                STATUS_DRAFT,
                STATUS_DRAFT,
                details={
                    "source_count": len(prepared),
                    "invoice_source_count": len(invoice_sources),
                    "manual_source_count": len(prepared) - len(invoice_sources),
                },
            )
            invoice_service._apply_request_invoice_summary(doc, save=False, current=True)
            doc.save(ignore_permissions=True)
            return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def update_draft_invoice_details(name, no_invoice_reason=None, expense_line_reasons=None):
    request_name = _bounded_optional_text(name, "\u7533\u8bf7\u5355\u53f7", 140)
    supplied_reason = (
        None
        if no_invoice_reason is None
        else _bounded_optional_text(
            no_invoice_reason,
            "\u65e0\u7968\u539f\u56e0",
            1000,
        )
    )
    reason_pairs = _strict_reason_pairs(expense_line_reasons)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        invoice_service._request_permission(doc, "edit", current=True)
        if doc.workflow_status != STATUS_DRAFT:
            frappe.throw(
                frappe._(
                    "\u53ea\u6709\u8349\u7a3f\u72b6\u6001\u53ef\u4ee5\u4fee\u6539\u53d1\u7968\u8bf4\u660e\u3002"
                )
            )
        lines = {
            str(getattr(row, "line_key", "") or ""): row
            for row in list(getattr(doc, "expense_lines", []) or [])
        }
        if len(reason_pairs) > DRAFT_REASON_MAX_ITEMS:
            frappe.throw(
                frappe._(
                    "\u8d39\u7528\u660e\u7ec6\u5dee\u5f02\u8bf4\u660e\u6700\u591a\u5141\u8bb8 100 \u9879\u3002"
                )
            )
        normalized_reasons = {}
        for raw_key, raw_value in reason_pairs:
            key = _bounded_optional_text(
                raw_key,
                "\u8d39\u7528\u660e\u7ec6\u6807\u8bc6",
                140,
            )
            if key in normalized_reasons:
                frappe.throw(
                    frappe._(
                        "\u8d39\u7528\u660e\u7ec6\u5dee\u5f02\u8bf4\u660e\u4e0d\u80fd\u5305\u542b\u91cd\u590d\u952e\u3002"
                    )
                )
            normalized_reasons[key] = _difference_reason(raw_value)
        if len(normalized_reasons) > len(lines):
            frappe.throw(
                frappe._(
                    "\u8d39\u7528\u660e\u7ec6\u5dee\u5f02\u8bf4\u660e\u6570\u91cf\u4e0d\u80fd\u8d85\u8fc7\u8be5\u7533\u8bf7\u7684\u8d39\u7528\u660e\u7ec6\u6570\u91cf\u3002"
                )
            )
        unknown = [key for key in normalized_reasons if not key or key not in lines]
        if unknown:
            frappe.throw(
                frappe._(
                    "\u8d39\u7528\u660e\u7ec6\u6807\u8bc6\u4e0d\u5c5e\u4e8e\u8be5\u62a5\u9500\u5355\u3002"
                )
            )
        if supplied_reason is not None:
            doc.no_invoice_reason = supplied_reason
        for key, value in normalized_reasons.items():
            lines[key].invoice_difference_reason = value
        doc.save(ignore_permissions=True)
        return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def submit_request(name, no_invoice_reason=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    supplied_reason = None
    if no_invoice_reason is not None:
        supplied_reason = _bounded_optional_text(no_invoice_reason, "无票原因", 1000)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        invoice_service._request_permission(doc, "edit", current=True)
        if doc.workflow_status != STATUS_DRAFT:
            frappe.throw(frappe._("\u53ea\u6709\u8349\u7a3f\u72b6\u6001\u53ef\u63d0\u4ea4\u3002"))
        if supplied_reason is not None:
            doc.no_invoice_reason = supplied_reason
        _submit_draft(doc)
        doc.save(ignore_permissions=True)
        return _summarize_doc(doc)


@frappe.whitelist()
def list_requests(view="mine", limit=50, request_type=None, name=None):
    if request_type and request_type not in REQUEST_TYPES:
        frappe.throw(frappe._("不支持的 OA 申请类型。"))
    roles = set(frappe.get_roles(frappe.session.user))
    ctx = _employee_context()
    try:
        limit = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        frappe.throw(frappe._("查询数量格式无效。"))
    exact_name = _report_text(name, "申请单号") if name is not None else ""
    filters = {}
    if view == "pending":
        filters["workflow_status"] = ["in", list(ACTIVE_STATUSES)]
    elif view == "all" and roles & PRIVILEGED_ROLES:
        filters = {}
    else:
        filters = {"employee": ctx.get("employee")} if ctx.get("employee") else {"owner": frappe.session.user}
    if request_type:
        filters["request_type"] = request_type
    if exact_name:
        filters["name"] = exact_name
    names = frappe.get_all(
        "OA Approval Request",
        filters=filters,
        fields=["name"],
        order_by="modified desc",
        limit_page_length=limit,
    )
    docs = [_load_request(_result_name(row)) for row in names]
    if view == "pending":
        docs = [doc for doc in docs if _can_act_on_current_step(doc)]
    return [_summarize_doc(doc) for doc in docs]


def _result_name(row):
    if isinstance(row, dict):
        return row.get("name")
    return row.name


def _report_text(value, label, limit=140):
    text = _bounded_optional_text(value, label, limit)
    if "\x00" in text:
        frappe.throw(frappe._("{0}格式无效。").format(label))
    return text


def _report_date(value, label):
    text = _report_text(value, label, 10)
    if not text:
        return ""
    try:
        date.fromisoformat(text)
    except (TypeError, ValueError):
        frappe.throw(frappe._("{0}格式无效。").format(label))
    return text


def _bounded_report_limit(value):
    try:
        return max(1, min(int(value or REPORT_LIMIT), REPORT_LIMIT))
    except (TypeError, ValueError):
        frappe.throw(frappe._("查询数量格式无效。"))


def _decimal_money(value):
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _expense_report_documents(
    *,
    view="mine",
    limit=REPORT_LIMIT,
    from_date=None,
    to_date=None,
    department=None,
    employee=None,
    workflow_status=None,
    source_type=None,
):
    report_limit = _bounded_report_limit(limit)
    roles = set(frappe.get_roles(frappe.session.user))
    ctx = _employee_context()
    if view == "all" and roles & PRIVILEGED_ROLES:
        filters = {}
    else:
        filters = {"employee": ctx.get("employee")} if ctx.get("employee") else {"owner": frappe.session.user}
    filters["request_type"] = REQUEST_EXPENSE_PAYMENT

    for field, value, label in (
        ("department", department, "部门"),
        ("employee", employee, "申请人"),
        ("workflow_status", workflow_status, "审批状态"),
        ("source_type", source_type, "来源"),
    ):
        cleaned = _report_text(value, label) if value is not None else ""
        if cleaned:
            filters[field] = cleaned

    start_date = _report_date(from_date, "开始日期") if from_date is not None else ""
    end_date = _report_date(to_date, "结束日期") if to_date is not None else ""
    if start_date and end_date and start_date > end_date:
        frappe.throw(frappe._("开始日期不能晚于结束日期。"))
    if start_date and end_date:
        filters["creation"] = ["between", [start_date + " 00:00:00", end_date + " 23:59:59"]]
    elif start_date:
        filters["creation"] = [">=", start_date + " 00:00:00"]
    elif end_date:
        filters["creation"] = ["<=", end_date + " 23:59:59"]

    names = frappe.get_all(
        "OA Approval Request",
        filters=filters,
        fields=["name"],
        order_by="modified desc",
        limit_page_length=report_limit + 1,
    )
    truncated = len(names) > report_limit
    docs = [_load_request(_result_name(row)) for row in names[:report_limit]]
    return docs, truncated


def _line_value(line, field, default=None):
    if isinstance(line, dict):
        return line.get(field, default)
    return getattr(line, field, default)


@frappe.whitelist()
def get_expense_statistics(
    view="mine",
    from_date=None,
    to_date=None,
    department=None,
    employee=None,
    invoice_category=None,
    project_name=None,
    workflow_status=None,
    payment_status=None,
    source_type=None,
    limit=REPORT_LIMIT,
):
    report_limit = _bounded_report_limit(limit)
    category_filter = _report_text(invoice_category, "发票类别") if invoice_category is not None else ""
    project_filter = _report_text(project_name, "项目名称") if project_name is not None else ""
    payment_filter = _report_text(payment_status, "付款状态") if payment_status is not None else ""
    if payment_filter not in {"", "已付款", "未付款"}:
        frappe.throw(frappe._("付款状态格式无效。"))

    docs, truncated = _expense_report_documents(
        view=view,
        limit=report_limit,
        from_date=from_date,
        to_date=to_date,
        department=department,
        employee=employee,
        workflow_status=workflow_status,
        source_type=source_type,
    )
    rows = []
    request_names = set()
    invoice_names = set()
    fallback_invoice_count = 0
    totals = {
        "request_count": 0,
        "invoice_count": 0,
        "amount_before_tax": Decimal("0"),
        "tax_amount": Decimal("0"),
        "total_amount": Decimal("0"),
        "paid_amount": Decimal("0"),
        "unpaid_amount": Decimal("0"),
    }

    for doc in docs:
        is_paid = doc.workflow_status == STATUS_PAID
        if payment_filter == "已付款" and not is_paid:
            continue
        if payment_filter == "未付款" and is_paid:
            continue

        detail_lines = list(getattr(doc, "expense_lines", []) or [])
        matched_lines = []
        for line in detail_lines:
            line_category = _clean(_line_value(line, "invoice_category") or _line_value(line, "category"))
            line_project = _clean(_line_value(line, "project_name") or _line_value(line, "description"))
            if category_filter and line_category != category_filter:
                continue
            if project_filter and line_project != project_filter:
                continue
            matched_lines.append(line)
        if (category_filter or project_filter) and not matched_lines:
            continue
        if not matched_lines:
            matched_lines = [None]

        request_names.add(doc.name)
        matched_sources = set()
        for line in matched_lines:
            if line is None:
                amount_before_tax = Decimal("0")
                tax_amount = Decimal("0")
                total_amount = _decimal_money(getattr(doc, "amount", 0))
                line_category = ""
                line_project = ""
                issue_date = None
                invoice_number = ""
                source_invoice = ""
            else:
                amount_before_tax = _decimal_money(_line_value(line, "amount_before_tax"))
                tax_amount = _decimal_money(_line_value(line, "tax_amount"))
                total_value = _line_value(line, "total_amount")
                if total_value in (None, ""):
                    total_value = _line_value(line, "amount", 0)
                total_amount = _decimal_money(total_value)
                line_category = _clean(_line_value(line, "invoice_category") or _line_value(line, "category"))
                line_project = _clean(_line_value(line, "project_name") or _line_value(line, "description"))
                issue_date = _line_value(line, "issue_date") or _line_value(line, "start_date")
                invoice_number = _clean(_line_value(line, "invoice_number"))
                source_invoice = _clean(_line_value(line, "source_invoice"))
            if source_invoice:
                invoice_names.add(source_invoice)
                matched_sources.add(source_invoice)
            paid_amount = total_amount if is_paid else Decimal("0")
            unpaid_amount = Decimal("0") if is_paid else total_amount
            totals["amount_before_tax"] += amount_before_tax
            totals["tax_amount"] += tax_amount
            totals["total_amount"] += total_amount
            totals["paid_amount"] += paid_amount
            totals["unpaid_amount"] += unpaid_amount
            rows.append(
                {
                    "request_name": doc.name,
                    "subject": getattr(doc, "subject", "") or "",
                    "creation": getattr(doc, "creation", None),
                    "employee": getattr(doc, "employee", None),
                    "employee_name": getattr(doc, "employee_name", None) or "",
                    "department": getattr(doc, "department", None) or "",
                    "source_type": getattr(doc, "source_type", None) or SOURCE_MANUAL,
                    "workflow_status": doc.workflow_status,
                    "invoice_count": 1 if source_invoice else int(getattr(doc, "invoice_count", 0) or 0),
                    "invoice_category": line_category,
                    "project_name": line_project,
                    "issue_date": issue_date,
                    "invoice_number": invoice_number,
                    "amount_before_tax": amount_before_tax,
                    "tax_amount": tax_amount,
                    "total_amount": total_amount,
                    "paid_amount": paid_amount,
                    "unpaid_amount": unpaid_amount,
                }
            )
        if not matched_sources:
            fallback_invoice_count += int(getattr(doc, "invoice_count", 0) or 0)

    totals["request_count"] = len(request_names)
    totals["invoice_count"] = len(invoice_names) + fallback_invoice_count
    if len(rows) > report_limit:
        truncated = True
        rows = rows[:report_limit]
    return {"totals": totals, "rows": rows, "truncated": truncated}


def _approval_record_matches(record, approver, action, start_date, end_date):
    if approver and approver not in set(record["approvers"]) | {record["actor"]}:
        return False
    if action and record["action"] != action:
        return False
    acted_on = str(record["acted_on"] or "")
    if start_date and (not acted_on or acted_on < start_date + " 00:00:00"):
        return False
    if end_date and (not acted_on or acted_on > end_date + " 23:59:59"):
        return False
    return True


@frappe.whitelist()
def list_expense_approval_records(
    view="mine",
    request_keyword=None,
    employee=None,
    department=None,
    approver=None,
    action=None,
    workflow_status=None,
    from_date=None,
    to_date=None,
    limit=REPORT_LIMIT,
):
    report_limit = _bounded_report_limit(limit)
    keyword = _report_text(request_keyword, "申请单关键字", 200).lower() if request_keyword is not None else ""
    approver_filter = _report_text(approver, "审批人") if approver is not None else ""
    action_filter = _report_text(action, "操作") if action is not None else ""
    start_date = _report_date(from_date, "开始日期") if from_date is not None else ""
    end_date = _report_date(to_date, "结束日期") if to_date is not None else ""
    if start_date and end_date and start_date > end_date:
        frappe.throw(frappe._("开始日期不能晚于结束日期。"))

    docs, truncated = _expense_report_documents(
        view=view,
        limit=report_limit,
        department=department,
        employee=employee,
        workflow_status=workflow_status,
    )
    records = []
    for doc in docs:
        if keyword and keyword not in (str(doc.name) + " " + str(getattr(doc, "subject", "") or "")).lower():
            continue
        common = {
            "request_name": doc.name,
            "subject": getattr(doc, "subject", "") or "",
            "employee": getattr(doc, "employee", None),
            "employee_name": getattr(doc, "employee_name", None) or "",
            "department": getattr(doc, "department", None) or "",
            "source_type": getattr(doc, "source_type", None) or SOURCE_MANUAL,
            "workflow_status": doc.workflow_status,
        }
        for step in list(getattr(doc, "steps", []) or []):
            serialized = _serialize_doc_step(step)
            record = {
                **common,
                "event_type": "审批节点",
                "step_label": serialized["label"] or "",
                "approvers": serialized["approvers"],
                "action": serialized["status"] or "",
                "actor": serialized["action_by"] or "",
                "acted_on": serialized["acted_on"] or "",
                "note": serialized["note"] or "",
            }
            if _approval_record_matches(record, approver_filter, action_filter, start_date, end_date):
                records.append(record)
        for event in _operation_events(doc):
            if not isinstance(event, dict):
                continue
            record = {
                **common,
                "event_type": "操作日志",
                "step_label": "",
                "approvers": [],
                "action": _clean(event.get("action")),
                "actor": _clean(event.get("actor") or event.get("user")),
                "acted_on": _clean(event.get("acted_on") or event.get("timestamp")),
                "note": _clean(event.get("note")),
            }
            if _approval_record_matches(record, approver_filter, action_filter, start_date, end_date):
                records.append(record)

    records.sort(key=lambda row: (bool(row["acted_on"]), str(row["acted_on"])), reverse=True)
    if len(records) > report_limit:
        truncated = True
        records = records[:report_limit]
    return {"records": records, "truncated": truncated}


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
            "invoice_status": INVOICE_CONFIRMED if all(row.invoice_status in {INVOICE_VERIFIED, INVOICE_CONFIRMED} for row in doc.invoices) else INVOICE_UPLOADED,
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
        submit=False,
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
        no_invoice_reason="由旧消费明细附件下推",
    )
    if _to_bool(submit):
        _submit_draft(doc)
        doc.save(ignore_permissions=True)
    for cd in docs:
        cd.status = CD_PUSHED
        cd.linked_request = doc.name
        cd.save(ignore_permissions=True)
    return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def action_request(name, action="approve", note=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
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
            return _summarize_doc(doc)
        done_status = STATUS_HANDLED if step.mode == "handle" else STATUS_APPROVED
        _set_step_action(step, done_status, actor, note)
        _advance_after_step(doc, step)
        doc.save(ignore_permissions=True)
        return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def mark_paid(name, note=None):
    _require_finance_user()
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        if doc.request_type != REQUEST_EXPENSE_PAYMENT:
            frappe.throw(frappe._("\u53ea\u6709\u8d39\u7528\u4ed8\u6b3e/\u62a5\u9500\u5355\u53ef\u6807\u8bb0\u4ed8\u6b3e\u3002"))
        if doc.workflow_status != STATUS_COMPLETED:
            frappe.throw(frappe._("\u53ea\u6709\u5ba1\u6279\u5df2\u901a\u8fc7\u7684\u5355\u636e\u53ef\u6807\u8bb0\u4ed8\u6b3e\u3002"))
        old_status = doc.workflow_status
        doc.workflow_status = STATUS_PAID
        doc.paid_by = sorted(_actor_names())[0]
        doc.paid_on = now_datetime()
        if note:
            doc.reason = ((doc.reason or "") + "\n" + "\u4ed8\u6b3e\u5907\u6ce8\uff1a" + note).strip()
        _append_request_event(doc, "标记已付款", old_status, STATUS_PAID, note)
        doc.save(ignore_permissions=True)
        return _summarize_doc(doc)

def _reset_request_to_draft(doc, note=""):
    old_status = doc.workflow_status
    details = {"steps": [_serialize_doc_step(row) for row in list(getattr(doc, "steps", []) or [])]}
    ctx = _route_context(
        department=doc.department,
        supervisor=doc.supervisor,
        asset_category=doc.asset_category,
    )
    route = preview_route(
        doc.request_type,
        ctx["department"],
        ctx["supervisor"],
        ctx["asset_category"],
        active=False,
    )
    _append_steps(doc, route["steps"])
    doc.workflow_status = STATUS_DRAFT
    doc.current_step_index = 0
    doc.current_step_label = ""
    _append_request_event(doc, "撤回申请", old_status, STATUS_DRAFT, note, details)
    return doc


@frappe.whitelist(methods=["POST"])
def push_invoices_to_request(invoice_names, payment_info=None):
    names = _invoice_names(invoice_names)
    info = _parse_json(payment_info, {}) or {}
    if not isinstance(info, dict):
        frappe.throw(frappe._("付款信息格式无效。"))
    with ExitStack() as locks:
        for name in sorted(names):
            locks.enter_context(invoice_service._transaction_lock("record", name))
        records = []
        for name in sorted(names):
            record = invoice_service._require_record(name, write=True, current=True)
            if str(getattr(record, "recognition_status", "") or "") != INVOICE_CONFIRMED:
                frappe.throw(frappe._("只有已确认发票可以下推。"))
            if str(getattr(record, "request", "") or "").strip():
                frappe.throw(frappe._("发票 {0} 已下推到其他报销单。").format(name))
            records.append(record)
        expense_lines = [
            {
                "source_invoice": record.name,
                "invoice_category": getattr(record, "invoice_category", None),
                "project_name": getattr(record, "project_name", None),
                "issue_date": getattr(record, "issue_date", None),
                "invoice_number": getattr(record, "invoice_number", None),
                "amount_before_tax": getattr(record, "amount_before_tax", None),
                "tax_amount": getattr(record, "tax_amount", None),
                "total_amount": getattr(record, "total_amount", None),
                "attachment_count": 1,
                "invoice_status": INVOICE_CONFIRMED,
            }
            for record in records
        ]
        doc = _build_request_doc(
            request_type=REQUEST_EXPENSE_PAYMENT,
            subject=_clean(info.get("subject")) or "发票报销-" + (records[0].project_name or records[0].invoice_number or records[0].name),
            department=info.get("department"),
            supervisor=None,
            asset_category=info.get("asset_category") or OTHER_ASSET,
            reason=info.get("reason"),
            submit=False,
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
            source_type=SOURCE_INVOICE_PUSH,
            source_summary="、".join(record.name for record in records),
            no_invoice_reason="",
        )
        lines = {str(row.source_invoice): row for row in doc.expense_lines}
        for record in records:
            line = lines[record.name]
            record.request = doc.name
            record.expense_line_key = line.line_key
            invoice_service._append_record_event(record, "发票下推", INVOICE_CONFIRMED, INVOICE_CONFIRMED, doc.name)
            invoice_service._save(record)
        _append_request_event(doc, "发票下推", STATUS_DRAFT, STATUS_DRAFT, "、".join(names))
        invoice_service._apply_request_invoice_summary(doc, save=False)
        doc.save(ignore_permissions=True)
        return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def withdraw_request(name, note=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        invoice_service._request_permission(doc, "edit", current=True)
        if doc.workflow_status == STATUS_PAID:
            frappe.throw(frappe._("已付款单据必须先由财务撤回付款。"))
        if doc.workflow_status == STATUS_DRAFT:
            return _summarize_doc(doc)
        _reset_request_to_draft(doc, note)
        doc.save(ignore_permissions=True)
        return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def withdraw_payment(name, note=None):
    _require_finance_user()
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        if doc.request_type != REQUEST_EXPENSE_PAYMENT or doc.workflow_status != STATUS_PAID:
            frappe.throw(frappe._("只有已付款报销单可以撤回付款。"))
        old_status = doc.workflow_status
        doc.workflow_status = STATUS_COMPLETED
        doc.paid_by = ""
        doc.paid_on = None
        _append_request_event(doc, "撤回付款", old_status, STATUS_COMPLETED, note)
        doc.save(ignore_permissions=True)
        return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def withdraw_invoice_push(invoice_names, note=None):
    names = _invoice_names(invoice_names)
    note = _bounded_optional_text(note, "操作说明", 500)
    with ExitStack() as locks:
        for name in sorted(names):
            locks.enter_context(invoice_service._transaction_lock("record", name))
        records = [invoice_service._require_record(name, write=True, current=True) for name in sorted(names)]
        request_names = sorted({str(record.request or "").strip() for record in records if str(record.request or "").strip()})
        if not request_names or any(not str(record.request or "").strip() for record in records):
            frappe.throw(frappe._("所选发票中存在尚未下推的记录。"))
        for request_name in request_names:
            locks.enter_context(invoice_service._transaction_lock("request", request_name))
        results = []
        for request_name in request_names:
            doc = _load_request(request_name, current=True)
            invoice_service._request_permission(doc, "edit", current=True)
            if doc.workflow_status == STATUS_PAID:
                frappe.throw(frappe._("已付款单据必须先由财务撤回付款。"))
            if doc.workflow_status != STATUS_DRAFT:
                _reset_request_to_draft(doc, note)
            selected = [record for record in records if str(record.request) == request_name]
            selected_keys = {str(record.expense_line_key or "") for record in selected}
            remaining = [
                _serialize_expense_line(row)
                for row in list(doc.expense_lines or [])
                if str(getattr(row, "line_key", "") or "") not in selected_keys
            ]
            _set_expense_lines(doc, remaining)
            doc.amount = sum(_money(row.amount) for row in doc.expense_lines)
            for record in selected:
                record.request = ""
                record.expense_line_key = ""
                invoice_service._append_record_event(record, "撤回发票下推", INVOICE_CONFIRMED, INVOICE_CONFIRMED, note)
                invoice_service._save(record)
            _append_request_event(doc, "撤回发票下推", STATUS_DRAFT, STATUS_DRAFT, note, {"invoices": [record.name for record in selected]})
            invoice_service._apply_request_invoice_summary(doc, save=False)
            doc.save(ignore_permissions=True)
            results.append(_summarize_doc(doc))
        return results[0] if len(results) == 1 else {"requests": results, "invoice_names": names}
