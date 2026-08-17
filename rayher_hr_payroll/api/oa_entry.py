import json
from contextlib import ExitStack
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import frappe
from frappe.utils import now_datetime

from rayher_hr_payroll.invoice_ocr import service as invoice_service
from rayher_hr_payroll import approval_amount_ledger, expense_attachments, invoice_supplemental_attachments
from rayher_hr_payroll.access_control import BUSINESS_EXECUTIVE_ROLE
from rayher_hr_payroll.expense_accounts import account_options, normalize_account_pair
from rayher_hr_payroll.oa_approval import (
    ADMIN_ASSET,
    IT_ASSET,
    OTHER_ASSET,
    PRODUCTION_ASSET,
    REQUEST_DIRECT_PURCHASE,
    REQUEST_EXPENSE_PAYMENT,
    REQUEST_LEAVE,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
    ApprovalRouteError,
    build_route,
    leave_copy_recipients,
    normalize_asset_category,
)
from rayher_hr_payroll.oa_feature_gate import require_request_type_access, visible_request_types
from rayher_hr_payroll.oa_role_resolver import (
    ApprovalRoleResolutionError,
    resolve_role,
)
from rayher_hr_payroll.procurement_workflow import (
    ProcurementWorkflowError,
    contract_copy_recipients,
    plan_contract_delivery,
    transition_business_state,
    validate_payment_submission,
    validate_procurement_submission,
)
from rayher_hr_payroll.oa_mutation_guard import authorized_oa_action
from rayher_hr_payroll.oa_assignments import sync_current_assignments
from rayher_hr_payroll.oa_organization import (
    DIRECT_SUPERVISOR_BY_EMPLOYEE,
    EXCLUDED_MANAGERS,
    TOP_EXECUTIVES,
    OrganizationResolutionError,
    resolve_stage_two_supervisor,
)

REQUEST_TYPES = [REQUEST_LEAVE, REQUEST_EXPENSE_PAYMENT, REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE, REQUEST_PROCUREMENT_PAYMENT]
ASSET_CATEGORIES = [ADMIN_ASSET, IT_ASSET, PRODUCTION_ASSET, OTHER_ASSET]

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


def _resolve_approval_roles(request_type, *, department="", asset_category="", purchase_method=""):
    if request_type == REQUEST_LEAVE:
        keys = ["hr_manager", "general_manager" if "财务" in _clean(department) else "vice_manager"]
    elif request_type == REQUEST_EXPENSE_PAYMENT:
        keys = ["finance_auditor", "finance_manager", "general_manager"]
        if "财务" not in _clean(department):
            keys.append("vice_manager")
        if asset_category == ADMIN_ASSET:
            keys.append("hr_manager")
        elif asset_category == PRODUCTION_ASSET:
            keys.append("production_asset_owner")
    elif request_type == REQUEST_PROCUREMENT:
        keys = ["pmc"]
        if asset_category == PRODUCTION_ASSET:
            keys.append("production_asset_owner")
    elif request_type == REQUEST_DIRECT_PURCHASE:
        keys = ["hr_manager", "vice_manager"] if _clean(purchase_method) == "京东购买" else []
    elif request_type == REQUEST_PROCUREMENT_PAYMENT:
        keys = ["finance_auditor", "vice_manager", "general_manager"]
    else:
        keys = []
    try:
        return {key: resolve_role(key) for key in dict.fromkeys(keys)}
    except ApprovalRoleResolutionError as exc:
        raise ApprovalRouteError(str(exc)) from exc


def _active_request_business_documents(request_name):
    if not request_name:
        return []
    rows = frappe.get_all(
        "OA Business Document",
        filters={"request": request_name},
        fields=["name", "document_type", "supersedes", "version_no"],
        order_by="version_no asc, creation asc",
        limit_page_length=0,
    )
    superseded = {_clean(row.get("supersedes")) for row in rows if _clean(row.get("supersedes"))}
    return [row for row in rows if _clean(row.get("name")) not in superseded]


def _request_business_document_types(request_name):
    return {
        _clean(row.get("document_type"))
        for row in _active_request_business_documents(request_name)
        if _clean(row.get("document_type"))
    }


def _save_document(doc):
    if getattr(doc, "doctype", None) == "OA Approval Request":
        with authorized_oa_action():
            return doc.save(ignore_permissions=True)
    return doc.save(ignore_permissions=True)


def _sync_assignments_after_save(doc):
    if getattr(doc, "doctype", None) == "OA Approval Request":
        sync_current_assignments(doc)
    return doc


def _insert_document(doc):
    if getattr(doc, "doctype", None) == "OA Approval Request":
        with authorized_oa_action():
            return doc.insert(ignore_permissions=True)
    return doc.insert(ignore_permissions=True)


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
    "\u603b\u7ecf\u529e",
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
DEPARTMENT_EXECUTIVE_OFFICE = "\u603b\u7ecf\u529e"
DEPARTMENT_EXECUTIVE_OFFICE_LEGACY = "\u603b\u7ecf\u7406\u5ba4"


def _clean(value):
    return str(value or "").strip()


def _display_payment_type(value):
    value = _clean(value)
    return PAYMENT_PERSONAL if value == PAYMENT_PERSONAL_LEGACY else value


def _canonical_payment_type(value):
    value = _display_payment_type(value)
    return value if value in PAYMENT_TYPES else PAYMENT_TYPES[0]


def _display_department(value):
    value = _clean(value)
    return (
        DEPARTMENT_EXECUTIVE_OFFICE
        if value == DEPARTMENT_EXECUTIVE_OFFICE_LEGACY
        else value
    )


def _canonical_department(value):
    return _display_department(value)


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


def _enabled_employee_user(employee_name):
    candidate = _clean(employee_name)
    if not candidate:
        return ""
    for filters in (
        {"employee_name": candidate, "status": "Active"},
        {"name": candidate, "status": "Active"},
    ):
        employee_user = frappe.db.get_value("Employee", filters, "user_id")
        if not employee_user:
            continue
        enabled_user = frappe.db.get_value(
            "User", {"name": employee_user, "enabled": 1}, "name"
        )
        if enabled_user:
            return str(enabled_user)
    return ""


def _employee_context(user=None):
    user = user or frappe.session.user
    if user == "Guest":
        frappe.throw(frappe._("请先登录。"))
    row = frappe.db.get_value(
        "Employee", {"user_id": user}, ["name", "employee_name", "department", "reports_to"], as_dict=True
    )
    if not row:
        return {
            "employee": None,
            "employee_name": "",
            "applicant_user": str(user).lower(),
            "department": "",
            "supervisor": "",
            "supervisor_user": "",
            "supervisor_decision": "",
            "supervisor_path": [],
        }

    employee_name = _clean(row.employee_name or row.name)
    context = {
        "employee": row.name,
        "employee_name": employee_name,
        "applicant_user": str(user).lower(),
        "department": _display_department(row.department),
        "supervisor": "",
        "supervisor_user": "",
        "supervisor_decision": "",
        "supervisor_path": [],
    }
    if employee_name in DIRECT_SUPERVISOR_BY_EMPLOYEE:
        try:
            resolution = resolve_stage_two_supervisor(employee_name, _enabled_employee_user)
        except OrganizationResolutionError as exc:
            frappe.throw(str(exc))
        context.update(
            {
                "supervisor": resolution.supervisor_name,
                "supervisor_user": resolution.user_id,
                "supervisor_decision": resolution.decision,
                "supervisor_path": list(resolution.traversed),
                "supervisor_reason": resolution.reason,
            }
        )
        return context

    # Compatibility for active Employees not yet represented in the organization map.
    if row.get("reports_to"):
        supervisor_row = frappe.db.get_value(
            "Employee",
            row.reports_to,
            ["employee_name", "user_id", "status"],
            as_dict=True,
        )
        if supervisor_row and _clean(supervisor_row.get("status")) == "Active":
            context["supervisor"] = _clean(
                supervisor_row.get("employee_name") or row.reports_to
            )
            context["supervisor_user"] = _enabled_employee_user(
                context["supervisor"]
            )
    return context


def _leave_employee_context(user=None):
    """Resolve leave identity and the immediate approver from server-owned data."""

    user = str(user or frappe.session.user or "").strip().lower()
    if not user or user == "guest":
        frappe.throw(frappe._("请先登录。"))

    rows = frappe.get_all(
        "Employee",
        filters={"user_id": user, "status": "Active"},
        fields=["name", "employee_name", "department", "reports_to"],
        order_by="name asc",
        limit_page_length=2,
    )
    if not rows:
        raise ApprovalRouteError("当前账号未关联在职员工，不能提交请假申请")
    if len(rows) != 1:
        raise ApprovalRouteError("当前账号关联了多个在职员工，请联系 HR 清理后再提交请假申请")

    row = rows[0]
    employee_id = _clean(row.get("name"))
    employee_name = _clean(row.get("employee_name") or employee_id)
    department = _canonical_department(_display_department(row.get("department")))
    if not department:
        raise ApprovalRouteError("当前员工未配置所属部门，不能提交请假申请")

    context = {
        "employee": employee_id,
        "employee_name": employee_name,
        "applicant_user": user,
        "department": department,
        "supervisor": "",
        "supervisor_user": "",
        "supervisor_decision": "",
        "supervisor_path": [],
    }
    if employee_name in TOP_EXECUTIVES:
        context.update(
            {
                "supervisor": employee_name,
                "supervisor_user": user,
                "supervisor_decision": "skip",
                "supervisor_path": [],
                "supervisor_reason": "applicant_is_top_executive",
            }
        )
        return context

    supervisor_name = ""
    reports_to = _clean(row.get("reports_to"))
    if reports_to:
        supervisor = frappe.db.get_value(
            "Employee",
            reports_to,
            ["employee_name", "status", "user_id"],
            as_dict=True,
        )
        if not supervisor or _clean(supervisor.get("status")) != "Active":
            raise ApprovalRouteError("当前员工配置的直属上级不存在或已离职")
        supervisor_name = _clean(supervisor.get("employee_name") or reports_to)
        supervisor_user = _clean(supervisor.get("user_id")).lower()
    else:
        supervisor_name = _clean(DIRECT_SUPERVISOR_BY_EMPLOYEE.get(employee_name))
        if not supervisor_name:
            raise ApprovalRouteError("当前员工未配置直属上级，不能提交请假申请")
        if supervisor_name in EXCLUDED_MANAGERS or supervisor_name == "BOARD":
            try:
                resolution = resolve_stage_two_supervisor(
                    employee_name, _enabled_employee_user
                )
            except OrganizationResolutionError as exc:
                raise ApprovalRouteError(str(exc)) from exc
            supervisor_name = _clean(resolution.supervisor_name)
        supervisor_user = _clean(_enabled_employee_user(supervisor_name)).lower()

    if not supervisor_name:
        raise ApprovalRouteError("当前员工未配置直属上级，不能提交请假申请")
    enabled_user = (
        frappe.db.get_value(
            "User", {"name": supervisor_user, "enabled": 1}, "name"
        )
        if supervisor_user
        else None
    )
    if not enabled_user:
        raise ApprovalRouteError(f"直属上级 {supervisor_name} 没有关联可用账号")
    supervisor_user = str(enabled_user).strip().lower()
    if supervisor_user == user:
        raise ApprovalRouteError("申请人不能成为自己的直属上级审批人")

    context.update(
        {
            "supervisor": supervisor_name,
            "supervisor_user": supervisor_user,
            "supervisor_decision": "approve",
            "supervisor_path": [supervisor_name],
            "supervisor_reason": "direct_employee_reports_to",
        }
    )
    return context


def _route_context(
    department=None,
    supervisor=None,
    asset_category=None,
    *,
    request_type=None,
):
    ctx = _leave_employee_context() if request_type == REQUEST_LEAVE else _employee_context()
    if request_type == REQUEST_LEAVE:
        if not ctx.get("employee"):
            raise ApprovalRouteError("当前账号未关联在职员工，不能提交请假申请")
        ctx["department"] = _canonical_department(ctx.get("department"))
        if not ctx.get("department"):
            raise ApprovalRouteError("当前员工未配置所属部门，不能提交请假申请")
        if not ctx.get("supervisor"):
            raise ApprovalRouteError("当前员工未配置直属上级，不能提交请假申请")
        if not ctx.get("supervisor_user"):
            raise ApprovalRouteError(
                f"直属上级 {ctx.get('supervisor')} 没有关联可用账号"
            )
        ctx["asset_category"] = OTHER_ASSET
        return ctx

    organization_managed = bool(ctx.get("supervisor_decision"))
    selected_department = ctx.get("department") if organization_managed else (department or ctx.get("department"))
    ctx["department"] = _canonical_department(selected_department)
    if not organization_managed:
        ctx["supervisor"] = supervisor or ctx.get("supervisor") or ""
    ctx["asset_category"] = asset_category or OTHER_ASSET
    return ctx

def _step_pending_status(step):
    return STATUS_WAIT_HANDLE if step.get("mode") == "handle" else STATUS_PENDING


def _resolve_route_approver(value):
    candidate = _clean(value)
    if not candidate:
        return ""
    if "@" in candidate:
        return candidate.lower()
    user = frappe.db.get_value(
        "User", {"full_name": candidate, "enabled": 1}, "name"
    )
    if user:
        return str(user)
    for filters in (
        {"employee_name": candidate, "status": "Active"},
        {"name": candidate, "status": "Active"},
    ):
        employee_user = frappe.db.get_value("Employee", filters, "user_id")
        if not employee_user:
            continue
        enabled_user = frappe.db.get_value(
            "User", {"name": employee_user, "enabled": 1}, "name"
        )
        if enabled_user:
            return str(enabled_user)
    return candidate
def _require_leave_accounts(steps, copied_to):
    users = []
    for step in steps:
        users.extend(step.get("approvers") or [])
    users.extend(row.get("user") for row in copied_to or [])
    for user in dict.fromkeys(_clean(value).lower() for value in users if value):
        enabled = frappe.db.get_value(
            "User", {"name": user, "enabled": 1}, "name"
        )
        if not enabled:
            raise ApprovalRouteError(f"请假审批账号未启用或不存在：{user}")


def _notify_copied_users(doc):
    request_type = getattr(doc, "request_type", None)
    if request_type not in {REQUEST_LEAVE, REQUEST_PROCUREMENT}:
        return
    subject_prefix = "请假申请抄送" if request_type == REQUEST_LEAVE else "采购合同交期抄送"
    content = (
        "请假申请 {0} 已提交，现抄送给你查阅。".format(doc.name)
        if request_type == REQUEST_LEAVE
        else "采购申请 {0} 的合同交期已确认，现抄送给你查阅。".format(doc.name)
    )
    for row in _parse_json(getattr(doc, "copied_to", None), default=[]) or []:
        user = _clean(row.get("user") if isinstance(row, dict) else "").lower()
        if not user:
            continue
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "for_user": user,
                "type": "Alert",
                "document_type": "OA Approval Request",
                "document_name": doc.name,
                "subject": subject_prefix + "：" + str(doc.name),
                "email_content": content,
            }
        ).insert(ignore_permissions=True)


def _serialize_route_steps(steps, active=True):
    return [
        {
            "step_index": idx,
            "label": step["label"],
            "mode": step["mode"],
            "approvers": [_resolve_route_approver(value) for value in step["approvers"]],
            "status": _step_pending_status(step) if active and idx == 1 else STATUS_WAIT_FLOW,
            "approved_by": [],
        }
        for idx, step in enumerate(steps, start=1)
    ]


def _serialize_doc_step(step):
    return {
        "step_index": int(step.step_index or 0),
        "step_key": getattr(step, "step_key", None) or "",
        "origin": getattr(step, "origin", None) or "base",
        "parent_step_key": getattr(step, "parent_step_key", None) or "",
        "add_sign_position": getattr(step, "add_sign_position", None) or "",
        "add_sign_opinion": getattr(step, "add_sign_opinion", None) or "",
        "added_by": getattr(step, "added_by", None) or "",
        "added_on": getattr(step, "added_on", None),
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
    expense_description = getattr(row, "expense_description", None) or legacy_description or ""
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
        "expense_account_level_1": _source_value(row, "expense_account_level_1") or "",
        "expense_account_level_2": _source_value(row, "expense_account_level_2") or "",
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
        "description": legacy_description or expense_description,
        "expense_description": expense_description,
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
        "department": _display_department(doc.department),
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


def _is_oa_override_user(user=None):
    user = _clean(user or frappe.session.user)
    roles = set(frappe.get_roles(user))
    return bool(
        user == "Administrator"
        or "System Manager" in roles
        or BUSINESS_EXECUTIVE_ROLE in roles
    )
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
    return bool(step and (_matched_approvers(step, user) or _is_oa_override_user(user)))


def _request_capabilities(doc, user=None):
    step = _current_step(doc)
    can_act = _can_act_on_current_step(doc, user)
    is_override = bool(can_act and _is_oa_override_user(user))
    classification_ready = _classification_ready(doc)
    finance_edit = bool(
        can_act
        and _is_finance_audit_step(step)
        and (_is_finance_user(user) or is_override)
    )
    can_approve = bool(can_act and (not finance_edit or classification_ready))
    return {
        "can_approve": can_approve,
        "can_reject": bool(can_act),
        "can_add_sign": bool(can_act),
        "can_edit_expense_items": finance_edit,
        "classification_ready": classification_ready,
        "is_override_actor": is_override,
        "action_scope": "override" if is_override else ("assigned" if can_act else ""),
    }


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


def _with_expense_attachments(doc, lines):
    if not lines:
        return []
    attachments = expense_attachments.list_attachments(getattr(doc, "name", None))
    by_line = {}
    for attachment in attachments:
        serialized = dict(attachment)
        serialized["attachment_source"] = "request_line"
        by_line.setdefault(_clean(serialized.get("expense_line_key")), []).append(serialized)
    result = []
    for source in lines:
        line = dict(source)
        line_attachments = list(by_line.get(_clean(line.get("line_key")), []))
        invoice_attachments = []
        source_invoice = _clean(line.get("source_invoice"))
        if source_invoice:
            invoice_attachments = [
                {**dict(attachment), "attachment_source": "invoice"}
                for attachment in invoice_supplemental_attachments.list_attachments(source_invoice)
            ]
        line["supplemental_attachments"] = invoice_attachments
        line["attachments"] = line_attachments + invoice_attachments
        line["attachment_count"] = len(line["attachments"])
        result.append(line)
    return result


def _summarize_doc(doc, authorized_expense_lines=None):
    step = _current_step(doc)
    invoice_summary = invoice_service.request_invoice_summary(doc)
    expense_lines = (
        authorized_expense_lines
        if authorized_expense_lines is not None
        else _with_expense_attachments(
            doc, [_serialize_expense_line(row) for row in getattr(doc, "expense_lines", [])]
        )
    )
    capabilities = _request_capabilities(doc)
    workflow_metadata = _workflow_metadata(doc)
    return {
        "name": doc.name,
        "request_type": doc.request_type,
        "employee": doc.employee,
        "employee_name": doc.employee_name,
        "department": _display_department(doc.department),
        "supervisor": doc.supervisor,
        "copied_to": _parse_json(getattr(doc, "copied_to", None), default=[]),
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
        "business_status": getattr(doc, "business_status", None) or "",
        "contract_delivery_date": getattr(doc, "contract_delivery_date", None) or "",
        "pending_contract_delivery_date": getattr(doc, "pending_contract_delivery_date", None) or "",
        "delivery_change_reason": getattr(doc, "delivery_change_reason", None) or "",
        "ordered_quantity": getattr(doc, "ordered_quantity", None) or 0,
        "received_quantity": getattr(doc, "received_quantity", None) or 0,
        "arrival_date": getattr(doc, "arrival_date", None) or "",
        "arrival_status": getattr(doc, "arrival_status", None) or "",
        "inspection_status": getattr(doc, "inspection_status", None) or "",
        "inspection_failure_reason": getattr(doc, "inspection_failure_reason", None) or "",
        "exception_direction": getattr(doc, "exception_direction", None) or "",
        "followup_status": getattr(doc, "followup_status", None) or "",
        "prepayment_writeoff_status": getattr(doc, "prepayment_writeoff_status", None) or "",
        "procurement_scope": getattr(doc, "procurement_scope", None),
        "expected_delivery_date": getattr(doc, "expected_delivery_date", None),
        "project": getattr(doc, "project", None),
        "project_owner": getattr(doc, "project_owner", None),
        "project_owner_name": getattr(doc, "project_owner_name", None),
        "purchaser_user": getattr(doc, "purchaser_user", None),
        "non_project_allocation_type": getattr(doc, "non_project_allocation_type", None),
        "non_project_cost_center": getattr(doc, "non_project_cost_center", None),
        "non_project_department": getattr(doc, "non_project_department", None),
        "purchase_method": getattr(doc, "purchase_method", None),
        "supplier": getattr(doc, "supplier", None),
        "payment_stage": getattr(doc, "payment_stage", None),
        "prepayment_percentage": getattr(doc, "prepayment_percentage", None) or 0,
        "has_balance_payment": getattr(doc, "has_balance_payment", None) or 0,
        "expected_arrival_date": getattr(doc, "expected_arrival_date", None),
        "prepayment_risk_note": getattr(doc, "prepayment_risk_note", None),
        "workflow_status": doc.workflow_status,
        "kanban_status": _kanban_status(doc.workflow_status),
        "current_step_index": doc.current_step_index,
        "current_step_label": doc.current_step_label,
        "current_step_mode": step.mode if step else "",
        "can_act": capabilities["can_approve"] or capabilities["can_reject"],
        **capabilities,
        **workflow_metadata,
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

def _require_consumption_write_access(doc):
    user = frappe.session.user
    if _is_finance_user(user):
        return
    if _clean(getattr(doc, "owner", None)) == _clean(user):
        return
    ctx = _employee_context(user)
    if ctx.get("employee") and _clean(getattr(doc, "employee", None)) == _clean(ctx.get("employee")):
        return
    frappe.throw(frappe._("\u60a8\u65e0\u6743\u4fee\u6539\u8be5\u6d88\u8d39\u660e\u7ec6\u3002"))


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
        if doc.request_type in {REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE}:
            doc.approved_amount = getattr(doc, "amount", None) or 0
        if doc.request_type == REQUEST_PROCUREMENT and _clean(getattr(doc, "business_status", None)) == "待审批":
            doc.business_status = "合同待登记"
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
                "step_key": step.get("step_key") or str(uuid4()),
                "origin": step.get("origin") or "base",
                "parent_step_key": step.get("parent_step_key") or "",
                "add_sign_position": step.get("add_sign_position") or "",
                "add_sign_opinion": step.get("add_sign_opinion") or "",
                "added_by": step.get("added_by") or "",
                "added_on": step.get("added_on"),
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
            derived_total = invoice_service.derive_total_amount(
                row.get("amount_before_tax"), row.get("tax_amount"), None
            )
            total_value = derived_total if derived_total is not None else row.get("amount")
        amount = _money(total_value)
        if amount <= 0 and not source_invoice:
            continue
        invoice_category = _clean(row.get("invoice_category"))
        project_name = _clean(row.get("project_name"))
        account_level_1 = _clean(row.get("expense_account_level_1"))
        account_level_2 = _clean(row.get("expense_account_level_2"))
        expense_item = _clean(row.get("expense_item"))
        if account_level_1 or account_level_2:
            account_level_1, account_level_2, expense_item = _expense_account_pair(
                account_level_1, account_level_2, required=True
            )
        description = _clean(row.get("expense_description") or row.get("description") or row.get("desc"))
        issue_date = row.get("issue_date") or row.get("start_date") or row.get("expense_date")
        category = invoice_category or expense_item or _clean(row.get("category")) or project_name or REQUEST_EXPENSE_PAYMENT
        normalized.append(
            {
                "source_consumption": row.get("source_consumption"),
                "source_invoice": source_invoice or None,
                "line_key": _expense_line_key(row, seen_line_keys),
                "invoice_category": invoice_category,
                "project_name": project_name,
                "expense_account_level_1": account_level_1,
                "expense_account_level_2": account_level_2,
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
                "description": description or (project_name if not source_invoice else ""),
                "expense_description": description or (project_name if not source_invoice else ""),
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
    ctx = _route_context(department=department, supervisor=supervisor, asset_category=asset_category, request_type=request_type)
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
            "copied_to": _json_list(route.get("copied_to") or []),
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
    _insert_document(doc)
    if submit:
        _notify_copied_users(doc)
    return doc


def _validate_expense_project_groups(doc):
    if getattr(doc, "request_type", None) != REQUEST_EXPENSE_PAYMENT:
        return []
    sources = [_serialize_expense_line(row) for row in list(getattr(doc, "expense_lines", []) or [])]
    groups = _group_expense_sources(sources)
    for group in groups:
        if not _clean(group.get("project_name")):
            frappe.throw(frappe._("\u63d0\u4ea4\u524d\u5fc5\u987b\u586b\u5199\u6bcf\u9879\u8d39\u7528\u7684\u9879\u76ee\u540d\u79f0\u3002"))
    for source in sources:
        if not _clean(source.get("expense_description")):
            frappe.throw(frappe._("\u63d0\u4ea4\u524d\u5fc5\u987b\u586b\u5199\u6bcf\u9879\u8d39\u7528\u7684\u8d39\u7528\u8bf4\u660e\u3002"))
    return groups


def _required_asset_category(value):
    if not _clean(value):
        frappe.throw(frappe._("提交报销前必须选择资产类型。"))
    try:
        return normalize_asset_category(value)
    except ApprovalRouteError as exc:
        frappe.throw(str(exc))


def _submit_draft(doc):
    if doc.workflow_status != STATUS_DRAFT:
        return
    old_status = doc.workflow_status
    if doc.request_type == REQUEST_LEAVE and (not doc.from_date or not doc.to_date):
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u8bf7\u5047\u5f00\u59cb\u548c\u7ed3\u675f\u65e5\u671f\u3002"))
    if doc.request_type == REQUEST_EXPENSE_PAYMENT and not list(getattr(doc, "expense_lines", []) or []):
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u8d39\u7528\u660e\u7ec6\u3002"))
    if doc.request_type == REQUEST_EXPENSE_PAYMENT:
        doc.asset_category = _required_asset_category(getattr(doc, "asset_category", None))
        _validate_expense_project_groups(doc)
        summary = invoice_service.validate_request_invoices(doc, submitting=True)
        if isinstance(summary, dict):
            doc.invoice_count = summary.get("invoice_count", 0)
            doc.invoice_status = summary.get("invoice_status", "")
    elif doc.request_type == REQUEST_PROCUREMENT:
        try:
            validate_procurement_submission(doc)
        except ProcurementWorkflowError as exc:
            frappe.throw(str(exc))
    elif doc.request_type == REQUEST_PROCUREMENT_PAYMENT:
        balance = approval_amount_ledger.source_balance(doc.source_request)
        doc.source_paid_amount = balance["paid_amount"]
        doc.source_available_amount = balance["available_amount"]
        try:
            doc.payment_stage = validate_payment_submission(
                doc, evidence=_request_business_document_types(doc.name)
            )
        except ProcurementWorkflowError as exc:
            frappe.throw(str(exc))
        if doc.payment_stage == "预付款":
            doc.has_balance_payment = 1 if Decimal(str(doc.prepayment_percentage or 0)) < 100 else 0
        else:
            doc.prepayment_percentage = 0
            doc.has_balance_payment = 1 if Decimal(str(doc.amount or 0)) < balance["available_amount"] else 0
    ctx = _route_context(
        department=getattr(doc, "department", None),
        supervisor=getattr(doc, "supervisor", None),
        asset_category=getattr(doc, "asset_category", None),
        request_type=doc.request_type,
    )
    doc.department = ctx["department"]
    doc.supervisor = ctx["supervisor"]
    route = preview_route(
        doc.request_type, ctx["department"], ctx["supervisor"], ctx["asset_category"], active=True,
        project_owner=getattr(doc, "project_owner", None),
        project_owner_name=getattr(doc, "project_owner_name", None),
        purchase_method=getattr(doc, "purchase_method", None),
        payment_stage=getattr(doc, "payment_stage", None),
    )
    doc.copied_to = _json_list(route.get("copied_to") or [])
    _append_steps(doc, route["steps"])
    doc.workflow_status = route["steps"][0]["status"]
    if doc.request_type in {REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE, REQUEST_PROCUREMENT_PAYMENT}:
        doc.business_status = "待审批"
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
        "request_types": visible_request_types(REQUEST_TYPES),
        "asset_categories": ASSET_CATEGORIES,
        "expense_categories": EXPENSE_CATEGORIES,
        "expense_account_tree": account_options(),
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
def preview_route(
    request_type, department=None, supervisor=None, asset_category=None, active=True,
    project_owner=None, project_owner_name=None, purchase_method=None, payment_stage=None,
):
    require_request_type_access(request_type)
    try:
        ctx = _route_context(department=department, supervisor=supervisor, asset_category=asset_category, request_type=request_type)
        roles = _resolve_approval_roles(
            request_type, department=ctx["department"], asset_category=ctx["asset_category"],
            purchase_method=purchase_method,
        )
        steps = build_route(
            request_type,
            department=ctx["department"],
            supervisor=ctx["supervisor"],
            supervisor_user=ctx.get("supervisor_user"),
            supervisor_decision=ctx.get("supervisor_decision"),
            applicant_user=ctx.get("applicant_user"),
            asset_category=ctx["asset_category"],
            project_owner=project_owner,
            project_owner_name=project_owner_name,
            purchase_method=purchase_method,
            payment_stage=payment_stage,
            roles=roles,
        )
        copied_to = (
            leave_copy_recipients(ctx.get("applicant_user"), roles=roles)
            if request_type == REQUEST_LEAVE
            else []
        )
        if request_type == REQUEST_LEAVE:
            _require_leave_accounts(steps, copied_to)
        return {
            "context": ctx,
            "steps": _serialize_route_steps(steps, active=_to_bool(active)),
            "copied_to": copied_to,
            "role_snapshots": list(roles.values()),
        }
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
    require_request_type_access(request_type)
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
    _save_document(doc)
    if requested_submit:
        _sync_assignments_after_save(doc)
    return _summarize_doc(doc)


def _draft_source_rows(source_lines):
    rows = _parse_json(source_lines, None)
    if not isinstance(rows, list) or len(rows) > 200:
        frappe.throw(frappe._("报销费用明细格式无效，单次最多 200 行。"))
    for row in rows:
        if not isinstance(row, dict):
            frappe.throw(frappe._("报销费用明细格式无效。"))
    return rows


def _expense_account_pair(level_1, level_2, *, required=False):
    level_1 = _clean(level_1)
    level_2 = _clean(level_2)
    if not required and not level_1 and not level_2:
        return "", "", ""
    try:
        return normalize_account_pair(level_1, level_2)
    except ValueError as error:
        frappe.throw(frappe._(str(error)))


def _manual_expense_source(payload, existing=None):
    source = dict(existing or {})
    for fieldname in (
        "project_name", "expense_account_level_1", "expense_account_level_2",
        "issue_date", "total_amount", "expense_description", "description",
        "line_key",
    ):
        if fieldname in payload:
            source[fieldname] = payload.get(fieldname)
    project_name = _bounded_optional_text(source.get("project_name"), "项目名称", 1000)
    account_level_1, account_level_2, expense_item = _expense_account_pair(
        source.get("expense_account_level_1"),
        source.get("expense_account_level_2"),
        required=True,
    )
    issue_date = _clean(source.get("issue_date"))
    total_amount = _optional_money(source.get("total_amount"))
    description = _bounded_optional_text(source.get("expense_description") or source.get("description"), "Expense description", 1000)
    if not project_name:
        frappe.throw(frappe._("手工费用必须填写项目名称。"))
    if not issue_date:
        frappe.throw(frappe._("手工费用必须填写日期。"))
    if total_amount is None or total_amount <= 0:
        frappe.throw(frappe._("手工费用金额必须大于 0。"))
    if not description:
        frappe.throw(frappe._("手工费用必须填写费用说明。"))
    source.update(
        {
            "source_invoice": None,
            "source_consumption": None,
            "project_name": project_name,
            "expense_account_level_1": account_level_1,
            "expense_account_level_2": account_level_2,
            "expense_item": expense_item,
            "no_invoice_reason": "",
            "invoice_category": "",
            "issue_date": issue_date,
            "invoice_number": "",
            "amount_before_tax": None,
            "tax_amount": None,
            "total_amount": total_amount,
            "category": expense_item or REQUEST_EXPENSE_PAYMENT,
            "amount": total_amount,
            "description": description,
            "expense_description": description,
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
    source["project_name"] = _bounded_optional_text(source.get("project_name"), "Project name", 1000)
    source["expense_item"] = _bounded_optional_text(source.get("expense_item"), "Expense item", 140)
    source["expense_description"] = _bounded_optional_text(
        source.get("expense_description") or source.get("description"),
        "Expense description",
        1000,
    )
    source["description"] = source["expense_description"]
    source["no_invoice_reason"] = ""
    return source


@frappe.whitelist(methods=["POST"])
def save_draft_expense_sources(name, source_lines):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
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
            _save_document(doc)
            return _summarize_doc(doc)



FINANCE_AUDIT_LABEL_PREFIX = "\u8d22\u52a1\u5ba1\u8ba1"


def _is_finance_audit_step(step):
    return bool(step and getattr(step, "mode", None) == "approve" and _clean(getattr(step, "label", None)).startswith(FINANCE_AUDIT_LABEL_PREFIX))


def _classification_ready(doc):
    if getattr(doc, "request_type", None) != REQUEST_EXPENSE_PAYMENT:
        return True
    for line in list(getattr(doc, "expense_lines", []) or []):
        try:
            normalize_account_pair(
                getattr(line, "expense_account_level_1", None),
                getattr(line, "expense_account_level_2", None),
            )
        except ValueError:
            return False
    return True


def _validate_finance_classification(doc, step):
    if _is_finance_audit_step(step) and not _classification_ready(doc):
        frappe.throw(frappe._("财务审批前必须为所有费用明细选择完整的费用科目。"))


@frappe.whitelist(methods=["POST"])
def save_finance_expense_items(name, lines):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    request_name = _bounded_optional_text(name, "Request", 140)
    payload_rows = _draft_source_rows(lines)
    if not payload_rows:
        frappe.throw(frappe._("No expense classification was supplied."))
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        step = _current_step(doc)
        if doc.request_type != REQUEST_EXPENSE_PAYMENT or doc.workflow_status not in ACTIVE_STATUSES:
            frappe.throw(frappe._("The request is not at an editable Finance approval step."))
        if (
            not _is_finance_audit_step(step)
            or not _can_act_on_current_step(doc)
            or not (_is_finance_user() or _is_oa_override_user())
        ):
            frappe.throw(frappe._("Only the active Finance approver may classify expense items."))
        current_lines = list(getattr(doc, "expense_lines", []) or [])
        by_key = {_clean(getattr(line, "line_key", None)): line for line in current_lines if _clean(getattr(line, "line_key", None))}
        assignments = {}
        seen = set()
        for payload in payload_rows:
            if set(payload) - {
                "line_key",
                "expense_account_level_1",
                "expense_account_level_2",
            }:
                frappe.throw(frappe._("财务归类只能修改费用科目。"))
            line_key = _clean(payload.get("line_key"))
            if not line_key or line_key in seen or line_key not in by_key:
                frappe.throw(frappe._("The expense line is invalid or no longer belongs to this request."))
            seen.add(line_key)
            account = _expense_account_pair(
                payload.get("expense_account_level_1"),
                payload.get("expense_account_level_2"),
                required=True,
            )
            project = _clean(getattr(by_key[line_key], "project_name", None))
            if project in assignments and assignments[project] != account:
                frappe.throw(frappe._("同一项目必须使用一致的费用科目。"))
            assignments[project] = account
        for line in current_lines:
            project = _clean(getattr(line, "project_name", None))
            if project in assignments:
                level_1, level_2, display = assignments[project]
                line.expense_account_level_1 = level_1
                line.expense_account_level_2 = level_2
                line.expense_item = display
        _append_request_event(doc, "Finance expense classification", doc.workflow_status, doc.workflow_status, details={"project_count": len(assignments), "line_count": len(seen)})
        _save_document(doc)
        return _summarize_doc(doc)
@frappe.whitelist(methods=["POST"])
def update_draft_invoice_details(name, no_invoice_reason=None, expense_line_reasons=None):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
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
        _save_document(doc)
        return _summarize_doc(doc)


def _procurement_payment_revision(doc):
    return max(1, sum(1 for event in _operation_events(doc) if event.get("action") == "提交申请"))


def _run_approval_amount_operation(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except approval_amount_ledger.ApprovalAmountError as error:
        frappe.throw(frappe._(str(error)))


def _reserve_procurement_payment(doc):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
        return None
    revision = _procurement_payment_revision(doc)
    return _run_approval_amount_operation(
        approval_amount_ledger.reserve,
        _clean(getattr(doc, "source_request", None)),
        doc.name,
        "submit:{0}:{1}".format(doc.name, revision),
        note="采购付款提交占用",
    )


def _release_procurement_payment_reservation(doc, note=""):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
        return None
    revision = _procurement_payment_revision(doc)
    return _run_approval_amount_operation(
        approval_amount_ledger.release_all_reserved,
        _clean(getattr(doc, "source_request", None)),
        doc.name,
        "release:{0}:{1}".format(doc.name, revision),
        note=note or "采购付款退回释放占用",
    )


def _mark_procurement_payment_paid(doc):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
        return None
    return _run_approval_amount_operation(
        approval_amount_ledger.mark_paid,
        _clean(getattr(doc, "source_request", None)),
        doc.name,
        "pay:{0}".format(doc.name),
        note="采购付款确认付款",
    )


def _set_procurement_payment_paid_state(doc):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
        return doc
    stage = _clean(getattr(doc, "payment_stage", None))
    percentage = Decimal(str(getattr(doc, "prepayment_percentage", 0) or 0))
    if stage in {"预付款", "全额付款"}:
        doc.business_status = "待到货"
        doc.arrival_status = _clean(getattr(doc, "arrival_status", None)) or "未到货"
        doc.inspection_status = _clean(getattr(doc, "inspection_status", None)) or "未验收"
    else:
        doc.business_status = "验收通过" if _clean(getattr(doc, "inspection_status", None)) == "验收通过" else "待验收"
    doc.prepayment_writeoff_status = "待核销" if stage == "预付款" and percentage == 100 else (_clean(getattr(doc, "prepayment_writeoff_status", None)) or "无需核销")
    return doc


@frappe.whitelist(methods=["POST"])
def submit_request(name, no_invoice_reason=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    supplied_reason = None
    if no_invoice_reason is not None:
        supplied_reason = _bounded_optional_text(no_invoice_reason, "无票原因", 1000)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        invoice_service._request_permission(doc, "edit", current=True)
        if doc.workflow_status != STATUS_DRAFT:
            frappe.throw(frappe._("\u53ea\u6709\u8349\u7a3f\u72b6\u6001\u53ef\u63d0\u4ea4\u3002"))
        if supplied_reason is not None:
            doc.no_invoice_reason = supplied_reason
        _submit_draft(doc)
        _reserve_procurement_payment(doc)
        _save_document(doc)
        _sync_assignments_after_save(doc)
        _notify_copied_users(doc)
        return _summarize_doc(doc)


def _step_snapshot(doc, prefix, role_label):
    for step in list(getattr(doc, "steps", []) or []):
        if _clean(getattr(step, "label", None)).startswith(prefix):
            users = _parse_json_list(getattr(step, "approvers", None))
            if users:
                return {"label": role_label, "user": _clean(users[0])}
    return {"label": role_label, "user": ""}


def _contract_copy_snapshot(doc):
    return {
        "applicant": {"label": "申请人", "user": _clean(getattr(doc, "owner", None))},
        "purchaser": {"label": "采购经办人", "user": _clean(getattr(doc, "purchaser_user", None))},
        "pmc": _step_snapshot(doc, "PMC", "PMC"),
        "supervisor": _step_snapshot(doc, "直属主管", "直属上级"),
        "project_owner": {"label": "项目主管", "user": _clean(getattr(doc, "project_owner", None))},
    }


def _require_contract_registration_access(doc):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT:
        frappe.throw(frappe._("只有采购申请可以登记合同交期。"))
    if getattr(doc, "workflow_status", None) != STATUS_COMPLETED:
        frappe.throw(frappe._("采购审批完成后才能登记合同交期。"))
    if _clean(getattr(doc, "business_status", None)) == "合同交期待确认":
        frappe.throw(frappe._("当前合同交期仍在确认中，不能重复登记。"))
    user = _clean(getattr(frappe.session, "user", None))
    allowed = {_clean(getattr(doc, "owner", None)), _clean(getattr(doc, "purchaser_user", None))}
    roles = set(frappe.get_roles(user))
    if user not in allowed and not (roles & {"System Manager", "Purchase User", "Purchase Manager"}):
        frappe.throw(frappe._("只有申请人、采购经办人或采购管理人员可以登记合同交期。"))


def _append_contract_delivery_steps(doc, role_keys, contract_date):
    pmc = _step_snapshot(doc, "PMC", "PMC")
    role_rows = {
        "pmc": (pmc, "合同交期确认-PMC"),
        "project_owner": ({"label": "项目主管", "user": _clean(getattr(doc, "project_owner", None))}, "合同交期确认-项目主管"),
    }
    next_index = max([int(getattr(row, "step_index", 0) or 0) for row in list(getattr(doc, "steps", []) or [])] or [0]) + 1
    appended = []
    seen_users = set()
    for role_key in role_keys:
        role, label_prefix = role_rows[role_key]
        user = _clean(role.get("user"))
        if not user:
            frappe.throw(frappe._("合同交期确认缺少{0}有效账号。".format(role.get("label") or role_key)))
        if user in seen_users:
            continue
        seen_users.add(user)
        offset = len(appended)
        if role_key == "project_owner":
            display_name = _clean(getattr(doc, "project_owner_name", None)) or "项目主管"
        else:
            source = next((row for row in doc.steps if _clean(getattr(row, "label", None)).startswith("PMC")), None)
            display_name = _clean(source.label).split("：", 1)[1] if source and "：" in _clean(source.label) else "PMC"
        index = next_index + offset
        row = doc.append("steps", {
            "step_index": index,
            "step_key": str(uuid5(NAMESPACE_URL, "{0}:contract:{1}:{2}:{3}".format(doc.name, contract_date, index, role_key))),
            "origin": "contract_delivery",
            "parent_step_key": "",
            "add_sign_position": "",
            "add_sign_opinion": "",
            "added_by": _clean(getattr(frappe.session, "user", None)),
            "added_on": now_datetime(),
            "label": label_prefix + "：" + display_name,
            "mode": "approve",
            "approvers": _json_list([user]),
            "status": STATUS_PENDING if offset == 0 else STATUS_WAIT_FLOW,
            "approved_by": _json_list([]),
            "action_by": "",
            "acted_on": None,
            "note": "",
        })
        appended.append(row)
    doc.workflow_status = STATUS_PENDING
    doc.current_step_index = appended[0].step_index
    doc.current_step_label = appended[0].label
    return appended


def _finalize_contract_delivery_if_complete(doc, completed_step):
    if _clean(getattr(completed_step, "origin", None)) != "contract_delivery":
        return False
    if getattr(doc, "workflow_status", None) != STATUS_COMPLETED:
        return False
    pending_date = _clean(getattr(doc, "pending_contract_delivery_date", None))
    if not pending_date:
        return False
    previous = _clean(getattr(doc, "contract_delivery_date", None))
    doc.contract_delivery_date = pending_date
    doc.pending_contract_delivery_date = ""
    doc.business_status = "采购执行中"
    doc.copied_to = _json_list(contract_copy_recipients(_contract_copy_snapshot(doc)))
    _append_request_event(doc, "确认合同交期", "合同交期待确认", "采购执行中", getattr(doc, "delivery_change_reason", None), {"previous_contract_delivery_date": previous, "contract_delivery_date": pending_date})
    return True


@frappe.whitelist(methods=["POST"])
def register_contract_delivery(name, contract_delivery_date, reason=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        _require_contract_registration_access(doc)
        try:
            plan = plan_contract_delivery(getattr(doc, "expected_delivery_date", None), contract_delivery_date, getattr(doc, "procurement_scope", None), reason)
        except ProcurementWorkflowError as error:
            frappe.throw(frappe._(str(error)))
        previous = _clean(getattr(doc, "contract_delivery_date", None))
        old_business_status = _clean(getattr(doc, "business_status", None))
        doc.delivery_change_reason = _bounded_optional_text(reason, "交期变更原因", 500)
        details = {"previous_contract_delivery_date": previous, "requested_contract_delivery_date": plan["contract_delivery_date"], "requires_reapproval": plan["requires_reapproval"]}
        if plan["requires_reapproval"]:
            doc.pending_contract_delivery_date = plan["contract_delivery_date"]
            doc.business_status = "合同交期待确认"
            _append_contract_delivery_steps(doc, plan["approval_roles"], plan["contract_delivery_date"])
            _append_request_event(doc, "登记延期合同交期", old_business_status, doc.business_status, doc.delivery_change_reason, details)
            notify = False
        else:
            doc.contract_delivery_date = plan["contract_delivery_date"]
            doc.pending_contract_delivery_date = ""
            doc.business_status = "采购执行中"
            doc.copied_to = _json_list(contract_copy_recipients(_contract_copy_snapshot(doc)))
            _append_request_event(doc, "确认合同交期", old_business_status, doc.business_status, doc.delivery_change_reason, details)
            notify = True
        _save_document(doc)
        _sync_assignments_after_save(doc)
        if notify:
            _notify_copied_users(doc)
        return _summarize_doc(doc)


def _require_procurement_lifecycle_access(doc, action):
    request_type = getattr(doc, "request_type", None)
    workflow_status = getattr(doc, "workflow_status", None)
    source_actions = {"record_arrival", "record_inspection", "pass_inspection", "fail_inspection"}
    if request_type == REQUEST_PROCUREMENT:
        if action not in source_actions:
            frappe.throw(frappe._("预付款跟进、核销和关闭只能在采购付款单办理。"))
        if workflow_status != STATUS_COMPLETED:
            frappe.throw(frappe._("采购申请审批完成后才能登记到货和验收。"))
    elif request_type == REQUEST_PROCUREMENT_PAYMENT:
        if workflow_status != STATUS_PAID:
            frappe.throw(frappe._("采购付款完成后才能登记到货、验收和核销。"))
    else:
        frappe.throw(frappe._("只有采购申请或采购付款单可以登记采购履约状态。"))
    user = _clean(getattr(frappe.session, "user", None))
    roles = set(frappe.get_roles(user))
    allowed = {_clean(getattr(doc, "owner", None)), _clean(getattr(doc, "purchaser_user", None))}
    if user not in allowed and not (roles & {"System Manager", "Purchase User", "Purchase Manager", "Accounts User"}):
        frappe.throw(frappe._("只有申请人、采购经办人、采购或财务人员可以登记采购履约状态。"))


def _evidence_audit(rows):
    return {
        "evidence_names": [_clean(row.get("name")) for row in rows if _clean(row.get("name"))],
        "evidence_types": [_clean(row.get("document_type")) for row in rows if _clean(row.get("document_type"))],
    }


def _audit_detail_value(value):
    if isinstance(value, (Decimal, date)):
        return str(value)
    return value


PROCUREMENT_FULFILLMENT_FIELDS = (
    "business_status", "received_quantity", "arrival_status", "arrival_date", "inspection_status",
    "inspection_failure_reason", "exception_direction", "followup_status",
    "prepayment_writeoff_status",
)


def _sync_procurement_fulfillment_to_source(payment_doc):
    source_name = _clean(getattr(payment_doc, "source_request", None))
    if not source_name:
        return None
    source = frappe.get_doc("OA Approval Request", source_name)
    if getattr(source, "request_type", None) != REQUEST_PROCUREMENT:
        frappe.throw(frappe._("采购付款关联的来源申请类型无效。"))
    for fieldname in PROCUREMENT_FULFILLMENT_FIELDS:
        setattr(source, fieldname, getattr(payment_doc, fieldname, None))
    _append_request_event(
        source,
        "同步采购履约",
        getattr(source, "business_status", None),
        getattr(source, "business_status", None),
        details={"payment_request": payment_doc.name},
    )
    _save_document(source)
    return source


def _apply_procurement_lifecycle_transition(doc, action, payload, event_action, note=""):
    evidence = _active_request_business_documents(doc.name)
    old_status = _clean(getattr(doc, "business_status", None))
    try:
        updates = transition_business_state(doc, action, payload=payload, evidence=evidence)
    except ProcurementWorkflowError as error:
        frappe.throw(frappe._(str(error)))
    for fieldname, value in updates.items():
        setattr(doc, fieldname, value)
    details = _evidence_audit(evidence)
    details.update({key: _audit_detail_value(value) for key, value in (payload or {}).items() if value not in (None, "")})
    _append_request_event(doc, event_action, old_status, getattr(doc, "business_status", None), note, details)
    _save_document(doc)
    _sync_procurement_fulfillment_to_source(doc)
    _sync_assignments_after_save(doc)
    return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def record_arrival(name, quantity, arrival_date, reason=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        _require_procurement_lifecycle_access(doc, "record_arrival")
        note = _bounded_optional_text(reason, "到货说明", 500)
        return _apply_procurement_lifecycle_transition(
            doc,
            "record_arrival",
            {"quantity": quantity, "arrival_date": arrival_date},
            "登记到货",
            note,
        )


@frappe.whitelist(methods=["POST"])
def record_inspection(name, outcome, reason=None, direction=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        _require_procurement_lifecycle_access(doc, "record_inspection")
        normalized_outcome = _bounded_optional_text(outcome, "验收结果", 20)
        note = _bounded_optional_text(reason, "验收说明", 500)
        action = "pass_inspection" if normalized_outcome == "通过" else "fail_inspection" if normalized_outcome == "不合格" else ""
        if not action:
            frappe.throw(frappe._("验收结果必须选择通过或不合格。"))
        return _apply_procurement_lifecycle_transition(
            doc,
            action,
            {"reason": note, "direction": _bounded_optional_text(direction, "异常方向", 20)},
            "验收通过" if action == "pass_inspection" else "验收不合格",
            note,
        )


@frappe.whitelist(methods=["POST"])
def record_prepayment_followup(name, status, reason):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        _require_procurement_lifecycle_access(doc, "record_followup")
        note = _bounded_optional_text(reason, "跟进说明", 500)
        return _apply_procurement_lifecycle_transition(
            doc,
            "record_followup",
            {"status": _bounded_optional_text(status, "跟进状态", 30), "reason": note},
            "预付款异常跟进",
            note,
        )


@frappe.whitelist(methods=["POST"])
def writeoff_prepayment(name, reason=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        _require_procurement_lifecycle_access(doc, "writeoff_prepayment")
        note = _bounded_optional_text(reason, "核销说明", 500)
        return _apply_procurement_lifecycle_transition(doc, "writeoff_prepayment", {}, "预付款核销", note)


@frappe.whitelist(methods=["POST"])
def close_procurement(name, reason=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        _require_procurement_lifecycle_access(doc, "close_procurement")
        note = _bounded_optional_text(reason, "关闭说明", 500)
        return _apply_procurement_lifecycle_transition(doc, "close_procurement", {}, "关闭采购", note)


@frappe.whitelist()
def list_requests(view="mine", limit=50, request_type=None, name=None):
    allowed_types = visible_request_types(REQUEST_TYPES)
    if request_type:
        require_request_type_access(request_type)
        allowed_types = [request_type]
    if not allowed_types:
        return []
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
    filters["request_type"] = request_type if request_type else ["in", allowed_types]
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
    expense_item=None,
    project_name=None,
    workflow_status=None,
    payment_status=None,
    source_type=None,
    limit=REPORT_LIMIT,
):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    report_limit = _bounded_report_limit(limit)
    category_filter = _report_text(invoice_category, "发票类别") if invoice_category is not None else ""
    expense_filter = _report_text(expense_item, "费用项目") if expense_item is not None else ""
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

        detail_lines = [_serialize_expense_line(line) for line in list(getattr(doc, "expense_lines", []) or [])]
        matched_lines = []
        for line in detail_lines:
            line_category = _clean(line.get("invoice_category") or line.get("category"))
            line_expense_item = _clean(line.get("expense_item"))
            line_project = _clean(line.get("project_name") or line.get("description"))
            if category_filter and line_category != category_filter:
                continue
            if expense_filter and line_expense_item != expense_filter:
                continue
            if project_filter and line_project != project_filter:
                continue
            matched_lines.append(line)
        if (category_filter or expense_filter or project_filter) and not matched_lines:
            continue

        if not matched_lines:
            request_names.add(doc.name)
            total_amount = _decimal_money(getattr(doc, "amount", 0))
            paid_amount = total_amount if is_paid else Decimal("0")
            unpaid_amount = Decimal("0") if is_paid else total_amount
            totals["total_amount"] += total_amount
            totals["paid_amount"] += paid_amount
            totals["unpaid_amount"] += unpaid_amount
            fallback_invoice_count += int(getattr(doc, "invoice_count", 0) or 0)
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
                    "invoice_count": int(getattr(doc, "invoice_count", 0) or 0),
                    "invoice_category": "",
                    "expense_item": "",
                    "project_name": "",
                    "issue_date": None,
                    "invoice_number": "",
                    "amount_before_tax": Decimal("0"),
                    "tax_amount": Decimal("0"),
                    "total_amount": total_amount,
                    "paid_amount": paid_amount,
                    "unpaid_amount": unpaid_amount,
                }
            )
            continue

        request_names.add(doc.name)
        for group in _group_expense_sources(matched_lines):
            group_sources = list(group.get("source_lines") or [])
            categories = []
            issue_dates = []
            invoice_numbers = []
            source_invoices = []
            for source in group_sources:
                category_value = _clean(source.get("invoice_category") or source.get("category"))
                issue_value = source.get("issue_date") or source.get("start_date")
                number_value = _clean(source.get("invoice_number"))
                invoice_value = _clean(source.get("source_invoice"))
                if category_value and category_value not in categories:
                    categories.append(category_value)
                if issue_value and str(issue_value) not in issue_dates:
                    issue_dates.append(str(issue_value))
                if number_value and number_value not in invoice_numbers:
                    invoice_numbers.append(number_value)
                if invoice_value and invoice_value not in source_invoices:
                    source_invoices.append(invoice_value)
                    invoice_names.add(invoice_value)

            amount_before_tax = _decimal_money(group.get("amount_before_tax"))
            tax_amount = _decimal_money(group.get("tax_amount"))
            total_amount = _decimal_money(group.get("total_amount"))
            paid_amount = total_amount if is_paid else Decimal("0")
            unpaid_amount = Decimal("0") if is_paid else total_amount
            totals["amount_before_tax"] += amount_before_tax
            totals["tax_amount"] += tax_amount
            totals["total_amount"] += total_amount
            totals["paid_amount"] += paid_amount
            totals["unpaid_amount"] += unpaid_amount
            expense_items = list(group.get("expense_items") or [])
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
                    "invoice_count": len(source_invoices),
                    "invoice_category": "、".join(categories),
                    "expense_item": group.get("expense_item") or "、".join(expense_items),
                    "project_name": group.get("project_name") or "",
                    "issue_date": "、".join(issue_dates) if issue_dates else None,
                    "invoice_number": "、".join(invoice_numbers),
                    "amount_before_tax": amount_before_tax,
                    "tax_amount": tax_amount,
                    "total_amount": total_amount,
                    "paid_amount": paid_amount,
                    "unpaid_amount": unpaid_amount,
                }
            )

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
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
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
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
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
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    if not _clean(title) or not _clean(category) or not expense_date or _money(amount) <= 0:
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u6d88\u8d39\u660e\u7ec6\u7684\u6807\u9898\u3001\u8d39\u7528\u9879\u76ee\u3001\u65e5\u671f\u548c\u91d1\u989d\u3002"))
    ctx = _employee_context()
    if name:
        doc = _load_consumption(name)
        _require_consumption_write_access(doc)
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
        _save_document(doc)
    else:
        _insert_document(doc)
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
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    doc = _load_consumption(consumption)
    _require_consumption_write_access(doc)
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
    _save_document(doc)
    frappe.db.commit()
    return _serialize_consumption(doc)


@frappe.whitelist(methods=["POST"])
def push_consumption_to_request(consumption_names, payment_info=None, submit=0):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    names = _parse_json(consumption_names, [])
    if not names:
        frappe.throw(frappe._("\u8bf7\u9009\u62e9\u8981\u4e0b\u63a8\u7684\u6d88\u8d39\u660e\u7ec6\u3002"))
    docs = [_load_consumption(name) for name in names]
    for doc in docs:
        _require_consumption_write_access(doc)
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
        asset_category=_required_asset_category(info.get("asset_category")),
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
        _save_document(doc)
        _sync_assignments_after_save(doc)
    for cd in docs:
        cd.status = CD_PUSHED
        cd.linked_request = doc.name
        cd.save(ignore_permissions=True)
    return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def action_request(name, action="approve", note=None, reject_target=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        step = _current_step(doc)
        if not step or doc.workflow_status not in ACTIVE_STATUSES:
            frappe.throw(frappe._("\u5f53\u524d\u7533\u8bf7\u4e0d\u5728\u53ef\u5904\u7406\u72b6\u6001\u3002"))
        matched = _matched_approvers(step)
        is_override = _is_oa_override_user()
        if not matched and not is_override:
            frappe.throw(frappe._("\u5f53\u524d\u8282\u70b9\u4e0d\u5c5e\u4e8e\u4f60\u5904\u7406\u3002"))
        acting_as_override = bool(is_override and not matched)
        actor = _clean(frappe.session.user)
        if action == "reject":
            authorized_expense_lines = _with_expense_attachments(
                doc, [_serialize_expense_line(row) for row in getattr(doc, "expense_lines", [])]
            )
            _reject_to_target(doc, step, reject_target, actor, note)
            if doc.request_type == REQUEST_PROCUREMENT_PAYMENT and doc.workflow_status == STATUS_DRAFT:
                _release_procurement_payment_reservation(doc, note)
            _save_document(doc)
            _sync_assignments_after_save(doc)
            return _summarize_doc(doc, authorized_expense_lines)
        if action != "approve":
            frappe.throw(frappe._("\u4e0d\u652f\u6301\u7684\u5904\u7406\u52a8\u4f5c\u3002"))
        _validate_finance_classification(doc, step)
        authorized_expense_lines = _with_expense_attachments(
            doc, [_serialize_expense_line(row) for row in getattr(doc, "expense_lines", [])]
        )
        approved_by = set(_parse_json_list(step.approved_by))
        approved_by.update([actor] if acting_as_override else matched)
        step.approved_by = _json_list(sorted(approved_by))
        if (
            step.mode == "all"
            and not acting_as_override
            and not set(_parse_json_list(step.approvers)).issubset(approved_by)
        ):
            step.action_by = actor
            step.acted_on = now_datetime()
            if note:
                step.note = note
            _save_document(doc)
            _sync_assignments_after_save(doc)
            return _summarize_doc(doc, authorized_expense_lines)
        done_status = STATUS_HANDLED if step.mode == "handle" else STATUS_APPROVED
        from_status = doc.workflow_status
        _set_step_action(step, done_status, actor, note)
        _advance_after_step(doc, step)
        contract_delivery_confirmed = _finalize_contract_delivery_if_complete(doc, step)
        if step.mode == "handle" and doc.request_type in {REQUEST_EXPENSE_PAYMENT, REQUEST_PROCUREMENT_PAYMENT}:
            if doc.request_type == REQUEST_PROCUREMENT_PAYMENT:
                _mark_procurement_payment_paid(doc)
                _set_procurement_payment_paid_state(doc)
            doc.workflow_status = STATUS_PAID
            doc.paid_by = actor
            doc.paid_on = step.acted_on or now_datetime()
            _append_request_event(doc, "确认付款", from_status, STATUS_PAID, note)
        _save_document(doc)
        _sync_assignments_after_save(doc)
        if contract_delivery_confirmed:
            _notify_copied_users(doc)
        return _summarize_doc(doc, authorized_expense_lines)


@frappe.whitelist(methods=["POST"])
def mark_paid(name, note=None):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
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
        _save_document(doc)
        _sync_assignments_after_save(doc)
        return _summarize_doc(doc)

def _reset_request_to_draft(doc, note=""):
    old_status = doc.workflow_status
    details = {"steps": [_serialize_doc_step(row) for row in list(getattr(doc, "steps", []) or [])]}
    ctx = _route_context(
        department=doc.department,
        supervisor=doc.supervisor,
        asset_category=doc.asset_category,
        request_type=doc.request_type,
    )
    route = preview_route(
        doc.request_type,
        ctx["department"],
        ctx["supervisor"],
        ctx["asset_category"],
        active=False,
        project_owner=getattr(doc, "project_owner", None),
        project_owner_name=getattr(doc, "project_owner_name", None),
        purchase_method=getattr(doc, "purchase_method", None),
        payment_stage=getattr(doc, "payment_stage", None),
    )
    doc.copied_to = _json_list(route.get("copied_to") or [])
    _append_steps(doc, route["steps"])
    doc.workflow_status = STATUS_DRAFT
    doc.current_step_index = 0
    doc.current_step_label = ""
    _append_request_event(doc, "撤回申请", old_status, STATUS_DRAFT, note, details)
    return doc


@frappe.whitelist(methods=["POST"])
def push_invoices_to_request(invoice_names, payment_info=None):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
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
            if not _clean(getattr(record, "expense_description", None)):
                frappe.throw(frappe._("确认并下推发票前必须填写费用说明。"))
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
                "description": getattr(record, "expense_description", None),
                "expense_description": getattr(record, "expense_description", None),
                "attachment_count": 0,
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
        _save_document(doc)
        return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def withdraw_request(name, note=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        invoice_service._request_permission(doc, "edit", current=True)
        if doc.workflow_status == STATUS_PAID:
            frappe.throw(frappe._("已付款单据必须先由财务撤回付款。"))
        if doc.workflow_status == STATUS_DRAFT:
            return _summarize_doc(doc)
        _reset_request_to_draft(doc, note)
        _release_procurement_payment_reservation(doc, note)
        _save_document(doc)
        _sync_assignments_after_save(doc)
        return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def withdraw_payment(name, note=None):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
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
        _save_document(doc)
        _sync_assignments_after_save(doc)
        return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def withdraw_invoice_push(invoice_names, note=None):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    names = sorted(_invoice_names(invoice_names))
    note = _bounded_optional_text(note, "\u64cd\u4f5c\u8bf4\u660e", 500)

    snapshot_records = [
        invoice_service._require_record(name, write=True, current=False)
        for name in names
    ]
    snapshot_links = {
        record.name: _clean(getattr(record, "request", None))
        for record in snapshot_records
    }
    request_names = sorted({request_name for request_name in snapshot_links.values() if request_name})
    if not request_names or any(not request_name for request_name in snapshot_links.values()):
        frappe.throw(frappe._("\u6240\u9009\u53d1\u7968\u4e2d\u5b58\u5728\u5c1a\u672a\u4e0b\u63a8\u7684\u8bb0\u5f55\u3002"))

    with ExitStack() as locks:
        for request_name in request_names:
            locks.enter_context(invoice_service._transaction_lock("request", request_name))
        for name in names:
            locks.enter_context(invoice_service._transaction_lock("record", name))

        records = [
            invoice_service._require_record(name, write=True, current=True)
            for name in names
        ]
        current_links = {
            record.name: _clean(getattr(record, "request", None))
            for record in records
        }
        if current_links != snapshot_links:
            frappe.throw(frappe._("\u53d1\u7968\u5173\u8054\u5df2\u53d1\u751f\u53d8\u5316\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002"))

        results = []
        for request_name in request_names:
            doc = _load_request(request_name, current=True)
            invoice_service._request_permission(doc, "edit", current=True)
            if doc.workflow_status == STATUS_PAID:
                frappe.throw(frappe._("\u5df2\u4ed8\u6b3e\u5355\u636e\u5fc5\u987b\u5148\u7531\u8d22\u52a1\u64a4\u56de\u4ed8\u6b3e\u3002"))
            if doc.workflow_status != STATUS_DRAFT:
                _reset_request_to_draft(doc, note)
            selected = [record for record in records if _clean(record.request) == request_name]
            selected_keys = {_clean(record.expense_line_key) for record in selected}
            remaining = [
                _serialize_expense_line(row)
                for row in list(doc.expense_lines or [])
                if _clean(getattr(row, "line_key", None)) not in selected_keys
            ]
            _set_expense_lines(doc, remaining)
            doc.amount = sum(_money(row.amount) for row in doc.expense_lines)
            for record in selected:
                record.request = ""
                record.expense_line_key = ""
                invoice_service._append_record_event(
                    record,
                    "\u64a4\u56de\u53d1\u7968\u4e0b\u63a8",
                    INVOICE_CONFIRMED,
                    INVOICE_CONFIRMED,
                    note,
                )
                invoice_service._save(record)
            _append_request_event(
                doc,
                "\u64a4\u56de\u53d1\u7968\u4e0b\u63a8",
                STATUS_DRAFT,
                STATUS_DRAFT,
                note,
                {"invoices": [record.name for record in selected]},
            )
            invoice_service._apply_request_invoice_summary(doc, save=False)
            _save_document(doc)
            _sync_assignments_after_save(doc)
            results.append(_summarize_doc(doc))
        return results[0] if len(results) == 1 else {"requests": results, "invoice_names": names}


@frappe.whitelist(methods=["POST"])
def upload_expense_attachment(name, line_key, file_url):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    return expense_attachments.register_attachment(name, line_key, file_url)


@frappe.whitelist(methods=["POST"])
def delete_expense_attachment(name, attachment):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    return expense_attachments.delete_attachment(name, attachment)


@frappe.whitelist(methods=["POST"])
def preview_expense_attachment(attachment):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    return expense_attachments.preview_attachment(attachment)


@frappe.whitelist(methods=["POST"])
def serve_expense_attachment_preview(token):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    return expense_attachments.serve_attachment_preview(token)


MAX_ADD_SIGN_OPERATIONS = 20


def _reset_approval_step(step, status=STATUS_WAIT_FLOW):
    step.status = status
    step.approved_by = _json_list([])
    step.action_by = ""
    step.acted_on = None
    step.note = ""


def _eligible_rejection_targets(doc):
    current_index = int(getattr(doc, "current_step_index", 0) or 0)
    targets = [{"target": "applicant", "label": "\u7533\u8bf7\u4eba"}]
    completed = {STATUS_APPROVED, STATUS_HANDLED}
    for step in sorted(list(getattr(doc, "steps", []) or []), key=lambda row: int(getattr(row, "step_index", 0) or 0)):
        index = int(getattr(step, "step_index", 0) or 0)
        step_key = _clean(getattr(step, "step_key", None))
        if step_key and index < current_index and getattr(step, "status", None) in completed:
            targets.append({"target": step_key, "label": getattr(step, "label", None) or step_key, "step_index": index})
    return targets


def _reject_to_target(doc, current_step, target, actor, note):
    reason = _bounded_optional_text(note, "Reject reason", 1000)
    if not reason:
        frappe.throw(frappe._("A rejection reason is required."))
    target = _clean(target)
    eligible = {item["target"]: item for item in _eligible_rejection_targets(doc)}
    if target not in eligible:
        frappe.throw(frappe._("The rejection target is invalid or no longer eligible."))
    old_status = doc.workflow_status
    rows = sorted(list(getattr(doc, "steps", []) or []), key=lambda row: int(getattr(row, "step_index", 0) or 0))
    if target == "applicant":
        for step in rows:
            _reset_approval_step(step)
        doc.workflow_status = STATUS_DRAFT
        doc.current_step_index = 0
        doc.current_step_label = ""
    else:
        target_step = next((step for step in rows if _clean(getattr(step, "step_key", None)) == target), None)
        if not target_step:
            frappe.throw(frappe._("The rejection target no longer exists."))
        target_index = int(target_step.step_index or 0)
        for step in rows:
            if int(step.step_index or 0) >= target_index:
                _reset_approval_step(step)
        target_step.status = STATUS_WAIT_HANDLE if target_step.mode == "handle" else STATUS_PENDING
        doc.workflow_status = target_step.status
        doc.current_step_index = target_index
        doc.current_step_label = target_step.label
    _append_request_event(
        doc,
        "Targeted rejection",
        old_status,
        doc.workflow_status,
        reason,
        {"actor": actor, "source_step_key": _clean(getattr(current_step, "step_key", None)), "target": target},
    )
    return doc


def _approval_step_values(step):
    return {
        "step_index": int(getattr(step, "step_index", 0) or 0),
        "step_key": _clean(getattr(step, "step_key", None)) or str(uuid4()),
        "origin": _clean(getattr(step, "origin", None)) or "base",
        "parent_step_key": _clean(getattr(step, "parent_step_key", None)),
        "add_sign_position": _clean(getattr(step, "add_sign_position", None)),
        "add_sign_opinion": _clean(getattr(step, "add_sign_opinion", None)),
        "added_by": _clean(getattr(step, "added_by", None)),
        "added_on": getattr(step, "added_on", None),
        "label": getattr(step, "label", None) or "",
        "mode": getattr(step, "mode", None) or "approve",
        "approvers": getattr(step, "approvers", None) or _json_list([]),
        "status": getattr(step, "status", None) or STATUS_WAIT_FLOW,
        "approved_by": getattr(step, "approved_by", None) or _json_list([]),
        "action_by": getattr(step, "action_by", None) or "",
        "acted_on": getattr(step, "acted_on", None),
        "note": getattr(step, "note", None) or "",
    }


def _insert_add_sign_step(doc, current_step, approver, position, opinion, actor):
    approver = _bounded_optional_text(approver, "Add-sign approver", 140)
    opinion = _bounded_optional_text(opinion, "Add-sign opinion", 1000)
    position = _clean(position)
    if position not in {"before", "after"}:
        frappe.throw(frappe._("Add-sign position must be before or after the current approver."))
    if not approver or not opinion:
        frappe.throw(frappe._("Add-sign approver and opinion are required."))
    if approver == _clean(actor):
        frappe.throw(frappe._("You cannot add yourself as an approver."))
    rows = sorted(list(getattr(doc, "steps", []) or []), key=lambda row: int(getattr(row, "step_index", 0) or 0))
    if sum(1 for step in rows if _clean(getattr(step, "origin", None)) == "add_sign") >= MAX_ADD_SIGN_OPERATIONS:
        frappe.throw(frappe._("Each request supports at most 20 add-sign operations."))
    unresolved = {STATUS_PENDING, STATUS_WAIT_HANDLE, STATUS_WAIT_FLOW}
    for step in rows:
        if getattr(step, "status", None) in unresolved and approver in _parse_json_list(getattr(step, "approvers", None)):
            frappe.throw(frappe._("This approver already exists in the unresolved approval chain."))
    current_key = _clean(getattr(current_step, "step_key", None))
    current_position = next((index for index, step in enumerate(rows) if _clean(getattr(step, "step_key", None)) == current_key), None)
    if current_position is None:
        frappe.throw(frappe._("The current approval step has changed. Please refresh and retry."))
    if position == "before":
        current_step.status = STATUS_WAIT_FLOW
        insert_at = current_position
        new_status = STATUS_WAIT_HANDLE if current_step.mode == "handle" else STATUS_PENDING
    else:
        insert_at = current_position + 1
        new_status = STATUS_WAIT_FLOW
    new_values = {
        "step_index": 0,
        "step_key": str(uuid4()),
        "origin": "add_sign",
        "parent_step_key": current_key,
        "add_sign_position": position,
        "add_sign_opinion": opinion,
        "added_by": actor,
        "added_on": now_datetime(),
        "label": "\u52a0\u7b7e\uff1a" + approver,
        "mode": "approve",
        "approvers": _json_list([approver]),
        "status": new_status,
        "approved_by": _json_list([]),
        "action_by": "",
        "acted_on": None,
        "note": "",
    }
    values = [_approval_step_values(step) for step in rows]
    values.insert(insert_at, new_values)
    doc.set("steps", [])
    inserted = None
    for index, value in enumerate(values, start=1):
        value["step_index"] = index
        child = doc.append("steps", value)
        if value["step_key"] == new_values["step_key"]:
            inserted = child
    if position == "before":
        doc.current_step_index = inserted.step_index
        doc.current_step_label = inserted.label
        doc.workflow_status = inserted.status
    else:
        current = next(step for step in doc.steps if step.step_key == current_key)
        doc.current_step_index = current.step_index
        doc.current_step_label = current.label
    return inserted


def _resolve_add_sign_approver(value):
    candidate = _bounded_optional_text(value, "Add-sign approver", 140)
    if not candidate:
        frappe.throw(frappe._("An add-sign approver is required."))
    user = frappe.db.get_value("User", {"name": candidate, "enabled": 1}, "name")
    if not user:
        employee_user = frappe.db.get_value("Employee", {"name": candidate, "status": "Active"}, "user_id")
        if employee_user:
            user = frappe.db.get_value("User", {"name": employee_user, "enabled": 1}, "name")
    if not user:
        frappe.throw(frappe._("The selected add-sign approver is not an enabled user."))
    return str(user)


@frappe.whitelist()
def list_approval_people(query="", limit=20):
    query = _bounded_optional_text(query, "Search", 100)
    try:
        limit = max(1, min(int(limit or 20), 50))
    except (TypeError, ValueError):
        frappe.throw(frappe._("Search limit is invalid."))
    filters = {"enabled": 1, "user_type": "System User"}
    or_filters = None
    if query:
        like = "%" + query + "%"
        or_filters = {"name": ["like", like], "full_name": ["like", like]}
    rows = frappe.get_all("User", filters=filters, or_filters=or_filters, fields=["name", "full_name"], order_by="full_name asc", limit_page_length=limit)
    current_names = _actor_names()
    return [
        {"user": _source_value(row, "name"), "label": _source_value(row, "full_name") or _source_value(row, "name")}
        for row in rows
        if _source_value(row, "name") not in current_names and _source_value(row, "name") not in {"Guest", "Administrator"}
    ]


@frappe.whitelist(methods=["POST"])
def add_sign_request(name, approver, position, opinion):
    request_name = _bounded_optional_text(name, "Request", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        step = _current_step(doc)
        if not step or doc.workflow_status not in ACTIVE_STATUSES:
            frappe.throw(frappe._("The request is not at an active approval step."))
        if not _matched_approvers(step):
            frappe.throw(frappe._("Only the current approver may add an approver."))
        resolved = _resolve_add_sign_approver(approver)
        actor_names = _actor_names()
        if resolved in actor_names:
            frappe.throw(frappe._("You cannot add yourself as an approver."))
        actor = _clean(getattr(frappe.session, "user", None)) or sorted(actor_names)[0]
        inserted = _insert_add_sign_step(doc, step, resolved, position, opinion, actor)
        _append_request_event(
            doc,
            "Add-sign",
            doc.workflow_status,
            doc.workflow_status,
            _clean(opinion),
            {"actor": actor, "approver": resolved, "position": _clean(position), "step_key": inserted.step_key, "parent_step_key": inserted.parent_step_key},
        )
        _save_document(doc)
        _sync_assignments_after_save(doc)
        return _summarize_doc(doc)


def _workflow_metadata(doc):
    count = sum(1 for step in list(getattr(doc, "steps", []) or []) if _clean(getattr(step, "origin", None)) == "add_sign")
    return {
        "rejection_targets": _eligible_rejection_targets(doc) if getattr(doc, "workflow_status", None) in ACTIVE_STATUSES else [],
        "add_sign_count": count,
        "add_sign_remaining": max(0, MAX_ADD_SIGN_OPERATIONS - count),
    }


def _approval_center_result(value):
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return value


@frappe.whitelist(methods=["POST"])
def save_approval_center_draft(request_type, payload, name=None):
    from rayher_hr_payroll.approval_center import ApprovalCenterError, save_draft

    try:
        return _approval_center_result(save_draft(request_type, payload, name=name))
    except ApprovalCenterError as exc:
        frappe.throw(str(exc))


@frappe.whitelist(methods=["POST"])
def submit_approval_center_draft(name):
    return submit_request(name)


@frappe.whitelist()
def list_approval_center_projects(limit=500):
    from rayher_hr_payroll.approval_center import ApprovalCenterError, project_options

    try:
        return project_options(limit=limit)
    except ApprovalCenterError as exc:
        frappe.throw(str(exc))


@frappe.whitelist()
def get_approval_center_dashboard(kind, limit=200):
    from rayher_hr_payroll.approval_center import ApprovalCenterError, dashboard

    try:
        return dashboard(kind, limit=limit)
    except ApprovalCenterError as exc:
        frappe.throw(str(exc))


@frappe.whitelist(methods=["POST"])
def attach_approval_business_document(request, document_type, file_ref):
    from rayher_hr_payroll.business_documents import BusinessDocumentError, attach

    try:
        return _approval_center_result(attach(request, document_type, file_ref))
    except BusinessDocumentError as exc:
        frappe.throw(str(exc))


@frappe.whitelist()
def list_approval_business_documents(request):
    from rayher_hr_payroll.business_documents import BusinessDocumentError, list_documents

    try:
        return list_documents(request)
    except BusinessDocumentError as exc:
        frappe.throw(str(exc))