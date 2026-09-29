from rayher_hr_payroll.approval_identity import approval_actor_ids
from rayher_hr_payroll.procurement_mutation_guard import procurement_action
from rayher_hr_payroll.position_access import position_users, current_supervisors, executive_names
import json
from contextlib import ExitStack
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import frappe

from rayher_hr_payroll.attendance_requests import (
    ATTENDANCE_TYPES, REQUEST_OVERTIME, REQUEST_COMP_TIME, approved_attendance, attendance_request_transaction,
)
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
from rayher_hr_payroll.procurement_contract import (
    ProcurementContractError,
    contract_snapshot,
    price_approval_snapshot,
    render_contract_draft,
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
from rayher_hr_payroll.oa_assignments import (
    _request_link,
    notify_rejected_applicant,
    notify_request_applicant,
    sync_current_assignments,
)
from rayher_hr_payroll.oa_organization import (
    EXCLUDED_MANAGERS,
    OrganizationResolutionError,
    resolve_stage_two_supervisor,
    resolve_top_executive,
)

from rayher_hr_payroll.oa_document_types import REQUEST_PAYMENT, REQUEST_REIMBURSEMENT, REQUEST_TRAVEL  # noqa: E402

REQUEST_TYPES = [REQUEST_OVERTIME, REQUEST_COMP_TIME, REQUEST_LEAVE, REQUEST_EXPENSE_PAYMENT, REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE, REQUEST_PROCUREMENT_PAYMENT, REQUEST_TRAVEL, REQUEST_REIMBURSEMENT, REQUEST_PAYMENT]
ASSET_CATEGORIES = [ADMIN_ASSET, IT_ASSET, PRODUCTION_ASSET, OTHER_ASSET]
EXPENSE_FIXED_CATEGORY_BY_ASSET = {
    ADMIN_ASSET: "办公家具、工具及器具",
    IT_ASSET: "电子设备、研发专用设备、仪器仪表",
    PRODUCTION_ASSET: PRODUCTION_ASSET,
}

STATUS_DRAFT = "\u8349\u7a3f"
STATUS_PENDING = "\u5f85\u5ba1\u6279"
STATUS_WAIT_HANDLE = "\u5f85\u529e\u7406"
STATUS_WAIT_FLOW = "\u5f85\u6d41\u8f6c"
STATUS_APPROVED = "\u5df2\u901a\u8fc7"
STATUS_HANDLED = "\u5df2\u529e\u7406"
STATUS_COMPLETED = "\u5df2\u5b8c\u6210"
STATUS_REJECTED = "\u5df2\u62d2\u7edd"
STATUS_PAID = "\u5df2\u4ed8\u6b3e"
STATUS_WITHDRAWN = "\u5df2\u64a4\u56de"
ACTIVE_STATUSES = {STATUS_PENDING, STATUS_WAIT_HANDLE}
PRIVILEGED_ROLES = {"System Manager", "HR Manager", "HR User", "Accounts User"}
# 修复（2026-09-24，审查 R3-57-2，来自 #57）：报销统计和审批记录的"全部"只给财务和系统管理员。
# 行级权限早已不给 HR 看付款单据，这里原来仍用 PRIVILEGED_ROLES，HR 能看到全部报销。
EXPENSE_REPORT_ROLES = {"System Manager", "Accounts User"}
FINANCE_ROLES = {"System Manager", "Accounts User"}
# HR roles can manage HR data, but do not receive an unrestricted purchasing
# register. Purchasing visibility remains ownership/assignment scoped unless the
# account is an explicit purchasing, finance, or system administrator.
HR_SCOPED_ROLES = {"HR Manager", "HR User"}
PROCUREMENT_REQUEST_TYPES = {
    REQUEST_PROCUREMENT,
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT_PAYMENT,
}
PROCUREMENT_GLOBAL_ROLES = {"System Manager", "Purchase User", "Purchase Manager", "Rayher Business Executive"}
PROCUREMENT_PO_ROLES = PROCUREMENT_GLOBAL_ROLES | {"Accounts User", "Finance User"}

SOURCE_MANUAL = "\u624b\u5de5\u65b0\u5efa"
SOURCE_INVOICE_PUSH = "发票下推"
OPERATION_LOG_LIMIT = 100
REPORT_LIMIT = 1000

INVOICE_UPLOADED = "\u5df2\u4e0a\u4f20"
INVOICE_VERIFIED = "\u5df2\u9a8c\u8bc1"
INVOICE_CONFIRMED = "\u5df2\u786e\u8ba4"
INVOICE_DUPLICATE = "\u91cd\u590d\u53d1\u7968"


def _resolve_approval_roles(request_type, *, department="", asset_category="", purchase_method=""):
    if request_type in ATTENDANCE_TYPES:
        keys = ["hr_manager", "general_manager" if "财务" in _clean(department) else "vice_manager"]
    elif request_type == REQUEST_EXPENSE_PAYMENT:
        keys = ["finance_auditor", "finance_manager", "general_manager"]
        if "财务" not in _clean(department):
            keys.append("vice_manager")
        if asset_category == ADMIN_ASSET:
            keys.append("hr_manager")
        elif asset_category == IT_ASSET:
            keys.append("it_asset_owner")
        elif asset_category == PRODUCTION_ASSET:
            keys.append("production_asset_owner")
    elif request_type == REQUEST_PROCUREMENT:
        keys = ["pmc", "vice_manager", "procurement_manager"]
    elif request_type == REQUEST_DIRECT_PURCHASE:
        keys = (
            ["hr_manager", "vice_manager"]
            if _clean(purchase_method) == "京东购买"
            else ["vice_manager", "general_manager"]
        )
    elif request_type == REQUEST_PROCUREMENT_PAYMENT:
        keys = ["vice_manager", "finance_accountant", "finance_manager", "finance_auditor", "general_manager"]
    elif request_type == REQUEST_TRAVEL:
        keys = ["vice_manager", "general_manager"]
    elif request_type in {REQUEST_REIMBURSEMENT, REQUEST_PAYMENT}:
        keys = ["finance_auditor", "finance_manager", "general_manager"]
        if "财务" not in _clean(department):
            keys.append("vice_manager")
        if asset_category == ADMIN_ASSET:
            keys.append("hr_manager")
        elif asset_category == IT_ASSET:
            keys.append("it_asset_owner")
        elif asset_category == PRODUCTION_ASSET:
            keys.append("production_asset_owner")
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
        filters={"request": request_name, "status": ["!=", "已作废"]},
        fields=["name", "document_type", "supersedes", "version_no", "status"],
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
INVOICE_MODE_AVAILABLE = "已有发票"
INVOICE_MODE_PENDING = "暂未取得发票"
INVOICE_MODE_NOT_REQUIRED = "无需发票"
INVOICE_HANDLING_MODES = [INVOICE_MODE_AVAILABLE, INVOICE_MODE_PENDING, INVOICE_MODE_NOT_REQUIRED]
INVOICE_FOLLOWUP_PENDING = "待收票"
INVOICE_FOLLOWUP_RECEIVED = "已收票"
INVOICE_FOLLOWUP_VERIFIED = "已核验"
INVOICE_FOLLOWUP_NOT_REQUIRED = "无需发票"
COMPANIES = ["示例企业032有限公司"]
DEPARTMENT_EXECUTIVE_OFFICE = "\u603b\u7ecf\u529e"
DEPARTMENT_EXECUTIVE_OFFICE_LEGACY = "\u603b\u7ecf\u7406\u5ba4"


def _clean(value):
    return str(value or "").strip()


def _display_payment_type(value):
    value = _clean(value)
    return PAYMENT_PERSONAL if value == PAYMENT_PERSONAL_LEGACY else value


def _canonical_payment_type(value):
    # Payment type is descriptive metadata, not a workflow discriminator.
    return _bounded_optional_text(_display_payment_type(value), "付款类型", 140) or PAYMENT_TYPES[0]


def _invoice_mode(value):
    value = _clean(value)
    return value if value in INVOICE_HANDLING_MODES else ""


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
    # Approval step snapshots can contain datetime values; normalize them while
    # persisting the audit log so a valid withdrawal cannot fail on serialization.
    doc.operation_log = json.dumps(events[-OPERATION_LOG_LIMIT:], ensure_ascii=False, default=str)
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


def _can_submit_procurement_for_others(user=None):
    candidate = _clean(user or frappe.session.user).lower()
    if not candidate:
        return False
    try:
        return candidate == _clean(resolve_role("pmc").get("user")).lower()
    except (ApprovalRoleResolutionError, RuntimeError, ImportError):
        return False


def _employee_context(user=None, employee=None):
    user = _clean(user or frappe.session.user).lower()
    if user == "guest":
        frappe.throw(frappe._("请先登录。"))

    requested_employee = _clean(employee)
    fields = ["name", "employee_name", "department", "reports_to", "user_id"]
    if requested_employee:
        row = frappe.db.get_value(
            "Employee", {"name": requested_employee, "status": "Active"}, fields, as_dict=True
        )
        if not row:
            raise ApprovalRouteError("代提交的申请人不是在职员工")
        employee_user = _clean(row.get("user_id")).lower()
        if employee_user != user and not _can_submit_procurement_for_others(user):
            raise ApprovalRouteError("只有 PMC 演示员工178可以代其他员工提交采购申请")
    else:
        row = frappe.db.get_value(
            "Employee", {"user_id": user, "status": "Active"}, fields, as_dict=True
        )

    if not row:
        return {
            "employee": None,
            "employee_name": "",
            "applicant_user": user,
            "department": "",
            "supervisor": "",
            "supervisor_user": "",
            "supervisor_decision": "",
            "supervisor_path": [],
            "upper_supervisor": "",
            "upper_supervisor_user": "",
        }

    employee_name = _clean(row.employee_name or row.name)
    applicant_user = _clean(row.get("user_id")).lower() or user
    context = {
        "employee": row.name,
        "employee_name": employee_name,
        "applicant_user": applicant_user,
        "department": _display_department(row.department),
        "supervisor": "",
        "supervisor_user": "",
        "supervisor_decision": "",
        "supervisor_path": [],
        "upper_supervisor": "",
        "upper_supervisor_user": "",
    }
    if employee_name in current_supervisors():
        try:
            resolution = resolve_stage_two_supervisor(employee_name, _enabled_employee_user)
        except OrganizationResolutionError as exc:
            frappe.throw(str(exc))
        try:
            executive = resolve_top_executive(employee_name, _enabled_employee_user)
        except OrganizationResolutionError:
            executive = None
        context.update(
            {
                "supervisor": resolution.supervisor_name,
                "supervisor_user": resolution.user_id,
                "supervisor_decision": resolution.decision,
                "supervisor_path": list(resolution.traversed),
                "supervisor_reason": resolution.reason,
                "upper_supervisor": executive.executive_name if executive else "",
                "upper_supervisor_user": executive.user_id if executive else "",
            }
        )
        return context

    # Compatibility for active Employees not yet represented in the approved map.
    reports_to = _clean(row.get("reports_to"))
    if reports_to:
        supervisor_row = frappe.db.get_value(
            "Employee",
            reports_to,
            ["employee_name", "user_id", "status", "reports_to"],
            as_dict=True,
        )
        if supervisor_row and _clean(supervisor_row.get("status")) == "Active":
            context["supervisor"] = _clean(
                supervisor_row.get("employee_name") or reports_to
            )
            context["supervisor_user"] = _clean(supervisor_row.get("user_id")).lower()
            context["supervisor_decision"] = (
                "skip" if context["supervisor"] in executive_names() else "approve"
            )
            cursor = supervisor_row
            visited = {row.name}
            for _index in range(20):
                manager_name = _clean(cursor.get("employee_name"))
                if manager_name in executive_names():
                    context["upper_supervisor"] = manager_name
                    context["upper_supervisor_user"] = _clean(cursor.get("user_id")).lower()
                    break
                parent = _clean(cursor.get("reports_to"))
                if not parent or parent in visited:
                    break
                visited.add(parent)
                cursor = frappe.db.get_value(
                    "Employee",
                    parent,
                    ["employee_name", "user_id", "status", "reports_to"],
                    as_dict=True,
                ) or {}
                if _clean(cursor.get("status")) != "Active":
                    break
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
    if employee_name in executive_names():
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

    try:
        resolution = resolve_stage_two_supervisor(
            employee_name, _enabled_employee_user
        )
    except OrganizationResolutionError as exc:
        raise ApprovalRouteError(str(exc)) from exc

    supervisor_name = _clean(resolution.supervisor_name)
    supervisor_user = _clean(resolution.user_id).lower()
    if not supervisor_name:
        raise ApprovalRouteError("当前员工未配置直属上级，不能提交请假申请")
    if not supervisor_user:
        raise ApprovalRouteError(f"直属上级 {supervisor_name} 没有关联可用账号")
    if resolution.decision != "skip" and supervisor_user == user:
        raise ApprovalRouteError("申请人不能成为自己的直属上级审批人")

    context.update(
        {
            "supervisor": supervisor_name,
            "supervisor_user": supervisor_user,
            "supervisor_decision": resolution.decision,
            "supervisor_path": list(resolution.traversed),
            "supervisor_reason": resolution.reason,
        }
    )
    return context


NO_ACTIVE_EMPLOYEE_MESSAGE = "当前账号没有关联在职员工档案，不能提交这类申请；请联系人事处理。"


def _route_context(
    department=None,
    supervisor=None,
    asset_category=None,
    *,
    request_type=None,
    applicant_employee=None,
    require_employee=False,
):
    if request_type in ATTENDANCE_TYPES:
        ctx = _leave_employee_context()
    elif request_type == REQUEST_PROCUREMENT and applicant_employee:
        ctx = _employee_context(employee=applicant_employee)
    else:
        ctx = _employee_context()
    if request_type in ATTENDANCE_TYPES:
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

    organization_managed = bool(ctx.get("employee"))
    # 修复（2026-09-29，审查 X3-12，决定 D5）：没有在职员工档案的账号（管理员、离职但账号还开着的人）
    # 原来会直接用页面传来的部门和主管生成路线：部门填"财务部"能跳过副总，主管填副总的名字能免掉主管节点。
    # 提交和预览时要求在职员工档案；审批人驳回退回草稿等内部重算不受影响。
    if require_employee and not organization_managed:
        frappe.throw(frappe._(NO_ACTIVE_EMPLOYEE_MESSAGE))
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
    if request_type not in {*ATTENDANCE_TYPES, REQUEST_PROCUREMENT, REQUEST_PROCUREMENT_PAYMENT}:
        return
    subject_prefix = (
        request_type + "抄送"
        if request_type in ATTENDANCE_TYPES
        else "采购合同交期抄送"
        if request_type == REQUEST_PROCUREMENT
        else "采购付款结果汇总"
    )
    content = (
        f"{request_type} {doc.name} 已提交，现抄送给你查阅。"
        if request_type in ATTENDANCE_TYPES
        else "采购申请 {0} 的合同交期已确认，现抄送给你查阅。".format(doc.name)
        if request_type != REQUEST_PROCUREMENT_PAYMENT
        else "采购付款 {0} 已完成出纳办理，现汇总给你查阅。".format(doc.name)
    )
    for row in _parse_json(getattr(doc, "copied_to", None), default=[]) or []:
        user = _clean(row.get("user") if isinstance(row, dict) else "").lower()
        if not user:
            continue
        # 修复（2026-09-29，审查 #14）：键里带上操作日志条数。第二次确认合同交期、撤回付款后重新付款时
        # 原来键不变，抄送人收不到新的通知；同一次事件重复调用仍然只发一次。
        key = f"oa-copy:{doc.name}:{subject_prefix}:{len(_operation_events(doc))}"
        if frappe.db.exists(
            "Notification Log",
            {"for_user": user, "document_type": "OA Approval Request", "document_name": doc.name,
             "subject": ["like", f"%[{key}]%"]},
        ):
            continue
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "for_user": user,
                "type": "Alert",
                "document_type": "OA Approval Request",
                "document_name": doc.name,
                "subject": subject_prefix + "：" + str(doc.name) + f" [{key}]",
                "email_content": content,
                "link": _request_link(doc),
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


def _serialize_business_line(row):
    """Expose purchase-line fields so rejected procurement drafts can be edited again."""
    return {
        "material_code": _source_value(row, "material_code") or "",
        "material_serial": _source_value(row, "material_serial") or "",
        "category_code": _source_value(row, "category_code") or "",
        "category_path": _source_value(row, "category_path") or "",
        "item_name": _source_value(row, "item_name") or "",
        "specification": _source_value(row, "specification") or "",
        "product_desc": _source_value(row, "product_desc") or "",
        "brand": _source_value(row, "brand") or "",
        "product_name": _source_value(row, "product_name") or "",
        "product_desc_en": _source_value(row, "product_desc_en") or "",
        "brand_en": _source_value(row, "brand_en") or "",
        "material_attr": _source_value(row, "material_attr") or "外购",
        "quantity": _source_value(row, "quantity") or 0,
        "unit": _source_value(row, "unit") or "",
        "unit_price": _source_value(row, "unit_price") or 0,
        "amount": _source_value(row, "amount") or 0,
        "remarks": _source_value(row, "remarks") or "",
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



def _actor_names(user=None):
    return approval_actor_ids(user if user is not None else frappe.session.user)



def _is_oa_override_user(user=None):
    user = _clean(user or frappe.session.user)
    # Only explicit administrator accounts may bypass the assigned OA node.
    # Business executive and finance roles still receive their own routed
    # assignments, but must not approve someone else's step.
    return user in {"Administrator", "admin@staff.example.invalid"}
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
    if not step:
        return False
    matched = set(_matched_approvers(step, user))
    already_signed = bool(matched & set(_parse_json_list(getattr(step, "approved_by", None))))
    return bool((matched and not already_signed) or _is_oa_override_user(user))


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
        # 合同交期确认阶段不能加签；付款（经办）节点只能前加签（修复 2026-09-29，决定 D6/D9）。
        "can_add_sign": bool(can_act and not _is_contract_delivery_step(step)),
        "can_add_sign_after": bool(can_act and not _is_contract_delivery_step(step) and getattr(step, "mode", None) != "handle"),
        "can_edit_expense_items": finance_edit,
        "classification_ready": classification_ready,
        "is_override_actor": is_override,
        "action_scope": "override" if is_override else ("assigned" if can_act else ""),
    }


def _procurement_document_visibility(doc, user=None, *, chain=None):
    """Expose downstream procurement links only to their business owners."""
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT:
        return {"can_view_procurement_price": False, "can_view_procurement_po": False}
    candidate = _clean(user or frappe.session.user).lower()
    roles = set(frappe.get_roles(candidate) or [])
    price_user = candidate in position_users("pmc", "procurement_manager", "vice_manager") or bool(roles & PROCUREMENT_GLOBAL_ROLES)
    po_user = price_user or bool(roles & PROCUREMENT_PO_ROLES)
    price_numbers = _clean(getattr(doc, "price_approval_numbers", None))
    po_numbers = _clean(getattr(doc, "po_numbers", None))
    chain = _procurement_chain_summary(doc) if chain is None else chain
    has_price = bool(price_numbers or chain.get("price_approval_numbers"))
    has_po = bool(po_numbers or chain.get("po_numbers"))
    demand_approved = _clean(getattr(doc, "business_status", None)).startswith("需求已批准") or getattr(doc, "workflow_status", None) in {STATUS_COMPLETED, "已通过", "已审批", "已结束"}
    return {
        "can_view_procurement_price": bool(price_user and (has_price or demand_approved)),
        "can_view_procurement_po": bool(po_user and has_po),
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


def _request_attachments(doc):
    if getattr(doc, "request_type", None) not in ATTENDANCE_TYPES:
        return []
    return frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "OA Approval Request",
            "attached_to_name": doc.name,
        },
        fields=["name", "file_name", "file_url", "is_private", "creation"],
        order_by="creation asc",
        limit_page_length=100,
    )


def _procurement_has_payment_activity(doc):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT:
        return False
    return bool(frappe.db.exists(
        "OA Approval Request",
        {
            "request_type": REQUEST_PROCUREMENT_PAYMENT,
            "source_request": doc.name,
            "workflow_status": ["not in", [STATUS_DRAFT, STATUS_REJECTED]],
        },
    ))


def _can_submit_procurement_quote(doc, step=None, user=None):
    # Procurement quoting is handled by PR/Price Approval documents. The OA
    # request is only the demand-approval source and must never reopen the
    # legacy in-OA quotation form.
    return False


def _procurement_actor(doc):
    user = _clean(getattr(frappe.session, "user", None)).lower()
    return (
        user == _clean(getattr(doc, "purchaser_user", None)).lower()
        or "System Manager" in set(frappe.get_roles(user))
    )


def _can_edit_procurement_contract(doc):
    return (
        getattr(doc, "request_type", None) == REQUEST_PROCUREMENT
        and getattr(doc, "workflow_status", None) == STATUS_COMPLETED
        and _clean(getattr(doc, "business_status", None)) == "价格已批准/待补充合同信息"
        and _procurement_actor(doc)
    )


def _can_review_procurement_contract(doc):
    return (
        getattr(doc, "request_type", None) == REQUEST_PROCUREMENT
        and _clean(getattr(doc, "business_status", None)) == "合同草稿待复核"
        and _procurement_actor(doc)
    )


def _can_seal_procurement_contract(doc):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT:
        return False
    if _clean(getattr(doc, "business_status", None)) != "待电子用印":
        return False
    user = _clean(getattr(frappe.session, "user", None)).lower()
    return user == _clean(getattr(doc, "contract_seal_user", None)).lower() or "System Manager" in set(
        frappe.get_roles(user)
    )


def _find_payment_plan_row(doc, row_name):
    target = _clean(row_name)
    for row in (getattr(doc, "payment_plan", []) or []):
        if _clean(getattr(row, "name", None)) == target:
            return row
    return None


@procurement_action
def _sync_payment_plan_row(payment_doc, status):
    if getattr(payment_doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
        return None
    po_name = _clean(getattr(payment_doc, "source_purchase_order", None))
    po_row_name = _clean(getattr(payment_doc, "source_po_payment_plan_row", None))
    if po_name and po_row_name:
        po = frappe.get_doc("OA Purchase Order", po_name)
        row = next((item for item in (getattr(po, "payment_plan", []) or []) if _clean(getattr(item, "name", None)) == po_row_name), None)
        if not row:
            frappe.throw(frappe._("来源 PO 付款计划期次不存在。"))
        if status == "已下推" and (
            _clean(getattr(row, "status", None)) not in {"待审批", "审批中"}
            or _clean(getattr(row, "payment_request", None)) not in {"", payment_doc.name}
        ):
            # 修复（2026-09-24，审查 R3-52-1，来自 #52）：同一期次已被另一张采购付款占用时不能再提交，
            # 否则两张都能审批付款，期次上的付款单号和已付金额会被后一张覆盖。
            frappe.throw(frappe._("该 PO 付款计划期次已经生成其他采购付款，不能重复提交。"))
        if status in {"已下推", "已付款"}:
            row.payment_request = payment_doc.name
            row.pushed_by = _clean(frappe.session.user)
            row.pushed_on = now_datetime()
            row.approval_status = "已通过" if status == "已付款" else "审批中"
            if status == "已付款":
                row.paid_amount = getattr(payment_doc, "amount", None) or 0
        elif status == "待下推":
            # 修复（2026-09-24，审查 #5，来自 #52）：PO 期次没有"待下推"状态，写入后整张 PO 保存失败，
            # 采购付款无法驳回或撤回。退回时期次回到"待审批"，工作台重新显示为可提交付款审批；
            # 只清掉本单占用的付款单号，已付金额不动。
            if _clean(getattr(row, "payment_request", None)) in {"", payment_doc.name}:
                row.payment_request = ""
                row.pushed_by = ""
                row.pushed_on = None
            row.approval_status = "未发起"
            status = "待审批"
        row.status = status
        if status == "已付款":
            po.paid_amount = sum(float(item.paid_amount or 0) for item in po.payment_plan)
            po.payment_status = "已付款" if po.paid_amount >= float(po.total_amount or 0) else "部分付款"
            po.status = "付款中"
            for line in po.lines:
                line.payment_status = po.payment_status
        _save_document(po)
        return po
    source_name = _clean(getattr(payment_doc, "source_request", None))
    row_name = _clean(getattr(payment_doc, "source_payment_plan_row", None))
    if not source_name or not row_name:
        return None
    source = frappe.get_doc("OA Approval Request", source_name)
    row = _find_payment_plan_row(source, row_name)
    if not row:
        frappe.throw(frappe._("来源付款计划期次不存在。"))
    row.status = status
    if status == "已下推":
        row.payment_request = payment_doc.name
        row.pushed_by = _clean(frappe.session.user)
        row.pushed_on = now_datetime()
        row.approval_status = "审批中"
    elif status == "已付款":
        row.payment_request = payment_doc.name
        row.paid_amount = getattr(payment_doc, "amount", None) or 0
        row.approval_status = "已通过"
    elif status == "待下推":
        row.payment_request = ""
        row.pushed_by = ""
        row.pushed_on = None
        row.paid_amount = 0
    _save_document(source)
    return source


def _procurement_chain_summary(doc):
    from rayher_hr_payroll.procurement_summary_cache import prepared_summary
    cached = prepared_summary(doc.name)
    if cached is not None:
        return cached
    return _calculate_procurement_chain(doc)


def _calculate_procurement_chain(doc, data=None):
    empty = {
        "stage": "demand" if not (_clean(getattr(doc, "business_status", None)).startswith("需求已批准") or getattr(doc, "workflow_status", None) == STATUS_COMPLETED) else "await_pr",
        "label": "需求审批中" if not (_clean(getattr(doc, "business_status", None)).startswith("需求已批准") or getattr(doc, "workflow_status", None) == STATUS_COMPLETED) else "等待 PMC 提 PR",
        "summary": "需求审批完成后由 PMC 从物料进度看板生成 PR。",
        "pr_numbers": [], "price_approval_numbers": [], "po_numbers": [],
        "pending_pr_lines": 0, "pending_price_lines": 0,
        "draft_price_lines": 0, "approval_lines": 0, "po_lines": 0,
    }
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT:
        return empty
    approved_business = _clean(getattr(doc, "business_status", None)).startswith("需求已批准")
    if getattr(doc, "workflow_status", None) not in {STATUS_COMPLETED, "已通过", "已审批", "已结束"} and not approved_business:
        return empty
    try:
        source_lines = list(getattr(doc, "business_lines", []) or [])
        requested = {row.name: Decimal(str(getattr(row, "quantity", 0) or 0)) for row in source_lines}
        if data is None:
            pr_lines = frappe.get_all(
                "OA Procurement Request Line", filters={"source_request": doc.name},
                fields=["parent", "source_line", "quantity", "remaining_quantity"], limit_page_length=0,
            )
            active_price_approvals = frappe.get_all(
                "OA Price Approval", filters={"status": ["not in", ["已取消"]]},
                pluck="name", limit_page_length=0,
            )
            price_lines = frappe.get_all(
                "OA Price Approval Line",
                filters={"source_request": doc.name, "parent": ["in", active_price_approvals or ["__none__"]]},
                fields=["parent", "source_line", "quantity"], limit_page_length=0,
            )
            po_lines = frappe.get_all(
                "OA Purchase Order Line", filters={"source_request": doc.name},
                fields=["parent", "source_line", "quantity"], limit_page_length=0,
            )
            pr_names = sorted({row.parent for row in pr_lines if row.parent})
            price_names = sorted({row.parent for row in price_lines if row.parent})
            po_names = sorted({row.parent for row in po_lines if row.parent})
            price_status = {
                row.name: _clean(row.status) for row in frappe.get_all(
                    "OA Price Approval", filters={"name": ["in", price_names]},
                    fields=["name", "status"], limit_page_length=0,
                )
            } if price_names else {}
            po_status = {
                row.name: _clean(row.status) for row in frappe.get_all(
                    "OA Purchase Order", filters={"name": ["in", po_names]},
                    fields=["name", "status"], limit_page_length=0,
                )
            } if po_names else {}
        else:
            pr_lines, price_lines, po_lines, price_status, po_status = data
        pr_names = sorted({row.parent for row in pr_lines if row.parent})
        price_names = sorted({row.parent for row in price_lines if row.parent})
        po_names = sorted({row.parent for row in po_lines if row.parent})

        pr_quantity = {}
        pending_price_sources = set()
        for row in pr_lines:
            source_line = _clean(row.source_line)
            pr_quantity[source_line] = pr_quantity.get(source_line, Decimal("0")) + Decimal(str(row.quantity or 0))
            if Decimal(str(row.remaining_quantity or 0)) > 0:
                pending_price_sources.add(source_line)
        pending_pr_sources = {
            name for name, quantity in requested.items()
            if quantity - pr_quantity.get(name, Decimal("0")) > 0
        }
        draft_sources = {
            _clean(row.source_line) for row in price_lines if price_status.get(row.parent) == "草稿"
        }
        approval_sources = {
            _clean(row.source_line) for row in price_lines if price_status.get(row.parent) == "待审批"
        }
        po_sources = {_clean(row.source_line) for row in po_lines}
        active_po = {name for name, value in po_status.items() if value != "已关闭"}

        if pending_price_sources or draft_sources:
            stage, label = "quote", "采购询价/录价"
        elif pending_pr_sources:
            stage, label = "await_pr", "等待 PMC 提 PR"
        elif approval_sources:
            stage, label = "price", "价格审批中"
        elif active_po:
            stage, label = "po", "PO 执行中"
        elif po_names and all(value == "已关闭" for value in po_status.values()):
            stage, label = "closed", "采购已关闭"
        elif price_names:
            stage, label = "po", "价格审批已通过 / 待 PO"
        else:
            stage, label = empty["stage"], empty["label"]

        parts = []
        if pending_pr_sources:
            parts.append(f"待 PMC 提 PR {len(pending_pr_sources)} 项")
        actionable_price = pending_price_sources | draft_sources
        if actionable_price:
            parts.append(f"待采购询价/录价 {len(actionable_price)} 项")
        if approval_sources:
            parts.append(f"待演示员工37选择并审批 {len(approval_sources)} 项")
        if po_sources:
            parts.append(f"已进入 PO {len(po_sources)} 项")
        return {
            "stage": stage, "label": label,
            "summary": "；".join(parts) or "当前没有可处理的采购链路明细。",
            "pr_numbers": pr_names, "price_approval_numbers": price_names, "po_numbers": po_names,
            "pending_pr_lines": len(pending_pr_sources),
            "pending_price_lines": len(pending_price_sources),
            "draft_price_lines": len(draft_sources),
            "approval_lines": len(approval_sources), "po_lines": len(po_sources),
        }
    except Exception:
        return empty


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
    chain_summary = _procurement_chain_summary(doc)
    document_visibility = _procurement_document_visibility(doc, chain=chain_summary)
    workflow_metadata = _workflow_metadata(doc)
    po_fulfillment_records = []
    source_po = _clean(getattr(doc, "source_purchase_order", None))
    if getattr(doc, "request_type", None) == REQUEST_PROCUREMENT_PAYMENT and source_po:
        try:
            po_fulfillment_records = frappe.get_all(
                "OA PO Fulfillment Record", filters={"purchase_order": source_po},
                fields=["name", "record_type", "record_date", "recorded_by", "details_json",
                        "evidence_file", "original_filename", "note", "creation"],
                order_by="creation desc", limit_page_length=500,
            )
        except Exception:
            po_fulfillment_records = []
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
        "attendance_days": _parse_json(getattr(doc, "attendance_days", None), default=[]),
        "duration_hours": getattr(doc, "duration_hours", None),
        "leave_type": getattr(doc, "leave_type", None),
        "from_date": doc.from_date,
        "to_date": doc.to_date,
        "amount": doc.amount,
        "asset_category": doc.asset_category,
        "source_type": getattr(doc, "source_type", None) or SOURCE_MANUAL,
        "source_summary": getattr(doc, "source_summary", None),
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
        "procurement_chain": chain_summary,
        # Keep the user-facing asset decision separate from the legacy
        # accounting routing field below. Procurement only needs the broad
        # fixed/non-fixed decision; direct purchase may also have a category.
        "asset_nature": getattr(doc, "asset_nature", None) or "",
        "fixed_asset_category": getattr(doc, "fixed_asset_category", None) or "",
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
        "payment_source_kind": getattr(doc, "payment_source_kind", None) or "",
        "source_request": getattr(doc, "source_request", None),
        "source_payment_plan_row": getattr(doc, "source_payment_plan_row", None) or "",
        "source_payment_plan_installment": getattr(doc, "source_payment_plan_installment", None) or 0,
        "source_purchase_order": getattr(doc, "source_purchase_order", None) or "",
        "source_po_payment_plan_row": getattr(doc, "source_po_payment_plan_row", None) or "",
        "po_fulfillment_records": po_fulfillment_records,
        "price_revision": getattr(doc, "price_revision", None) or 0,
        "price_tax_included": getattr(doc, "price_tax_included", None) or 0,
        "price_tax_rate": getattr(doc, "price_tax_rate", None) or 0,
        "price_delivery_terms": getattr(doc, "price_delivery_terms", None) or "",
        "price_warranty_terms": getattr(doc, "price_warranty_terms", None) or "",
        "price_invoice_condition": getattr(doc, "price_invoice_condition", None) or "",
        "price_snapshot": _parse_json(getattr(doc, "price_snapshot", None), default={}),
        "price_submitted_by": getattr(doc, "price_submitted_by", None) or "",
        "price_submitted_on": getattr(doc, "price_submitted_on", None) or "",
        "price_approved_by": getattr(doc, "price_approved_by", None) or "",
        "price_approved_on": getattr(doc, "price_approved_on", None) or "",
        "contract_status": getattr(doc, "contract_status", None) or "",
        "contract_version": getattr(doc, "contract_version", None) or 0,
        "contract_supplier_legal_name": getattr(doc, "contract_supplier_legal_name", None) or "",
        "contract_credit_code": getattr(doc, "contract_credit_code", None) or "",
        "contract_supplier_address": getattr(doc, "contract_supplier_address", None) or "",
        "contract_contact": getattr(doc, "contract_contact", None) or "",
        "contract_bank_name": getattr(doc, "contract_bank_name", None) or "",
        "contract_bank_account": getattr(doc, "contract_bank_account", None) or "",
        "contract_entity": getattr(doc, "contract_entity", None) or "",
        "contract_template": getattr(doc, "contract_template", None) or "",
        "contract_seal_user": getattr(doc, "contract_seal_user", None) or "",
        "contract_draft_content": getattr(doc, "contract_draft_content", None) or "",
        "contract_reviewed_by": getattr(doc, "contract_reviewed_by", None) or "",
        "contract_reviewed_on": getattr(doc, "contract_reviewed_on", None) or "",
        "contract_sealed_by": getattr(doc, "contract_sealed_by", None) or "",
        "contract_sealed_on": getattr(doc, "contract_sealed_on", None) or "",
        "payment_plan": [
            {
                "name": getattr(row, "name", None) or "",
                "installment_no": int(getattr(row, "installment_no", 0) or 0),
                "installment_name": getattr(row, "installment_name", None) or "",
                "payment_stage": getattr(row, "payment_stage", None) or "",
                "percentage": float(getattr(row, "percentage", 0) or 0),
                "amount": float(getattr(row, "amount", 0) or 0),
                "planned_date": getattr(row, "planned_date", None) or "",
                "trigger_condition": getattr(row, "trigger_condition", None) or "",
                "invoice_requirement": getattr(row, "invoice_requirement", None) or "",
                "status": getattr(row, "status", None) or "",
                "payment_request": getattr(row, "payment_request", None) or "",
                "paid_amount": float(getattr(row, "paid_amount", 0) or 0),
            }
            for row in (getattr(doc, "payment_plan", []) or [])
        ],
        "can_edit_procurement_contract": _can_edit_procurement_contract(doc),
        "can_review_procurement_contract": _can_review_procurement_contract(doc),
        "can_seal_procurement_contract": _can_seal_procurement_contract(doc),
        "payment_stage": getattr(doc, "payment_stage", None),
        "prepayment_percentage": getattr(doc, "prepayment_percentage", None) or 0,
        "has_balance_payment": getattr(doc, "has_balance_payment", None) or 0,
        "expected_arrival_date": getattr(doc, "expected_arrival_date", None),
        "prepayment_risk_note": getattr(doc, "prepayment_risk_note", None),
        "workflow_status": doc.workflow_status,
        "workflow_status_label": (
            STATUS_WITHDRAWN
            if doc.request_type == REQUEST_PROCUREMENT
            and doc.workflow_status == STATUS_DRAFT
            and _clean(getattr(doc, "business_status", None)) == STATUS_WITHDRAWN
            else doc.workflow_status
        ),
        "kanban_status": _kanban_status(doc.workflow_status),
        "current_step_index": doc.current_step_index,
        "current_step_label": doc.current_step_label,
        "current_step_mode": step.mode if step else "",
        # 页面审批时带回这个值，服务端据此确认批的是页面上看到的那一步（修复 2026-09-29，决定 D10）。
        "current_step_key": _clean(getattr(step, "step_key", None)) if step else "",
        "can_act": capabilities["can_approve"] or capabilities["can_reject"],
        **capabilities,
        **document_visibility,
        **workflow_metadata,
        "can_mark_paid": doc.request_type == REQUEST_EXPENSE_PAYMENT and doc.workflow_status == STATUS_COMPLETED and _is_finance_user(),
        "can_supplement_invoices": (
            doc.request_type == REQUEST_EXPENSE_PAYMENT
            and _invoice_mode(getattr(doc, "invoice_handling_mode", None)) == INVOICE_MODE_PENDING
            and getattr(doc, "invoice_followup_status", None) in {INVOICE_FOLLOWUP_PENDING, INVOICE_FOLLOWUP_RECEIVED}
            and doc.workflow_status not in {STATUS_DRAFT, STATUS_REJECTED}
            and (invoice_service.invoice_permissions.can_edit_request(doc, frappe.session.user) or _is_finance_user())
        ),
        "can_verify_invoices": (
            doc.request_type == REQUEST_EXPENSE_PAYMENT
            and getattr(doc, "invoice_followup_status", None) == INVOICE_FOLLOWUP_RECEIVED
            and _is_finance_user()
        ),
        "can_withdraw": (
            (
                doc.request_type == REQUEST_PROCUREMENT
                and doc.workflow_status in ACTIVE_STATUSES
                and not _procurement_withdraw_blocker(doc)
            )
            or (
                doc.request_type != REQUEST_PROCUREMENT
                and doc.workflow_status not in {STATUS_DRAFT, STATUS_PAID}
                and not (
                    doc.request_type in {REQUEST_DIRECT_PURCHASE, REQUEST_TRAVEL}
                    and doc.workflow_status == STATUS_COMPLETED
                )
                # 修复（2026-09-29，审查 R3-56-1）：已批准的请假、加班、调休暂不能撤回。
                and not approved_attendance(doc)
            )
        ) and invoice_service.invoice_permissions.can_edit_request(doc, frappe.session.user),
        "can_withdraw_payment": doc.workflow_status == STATUS_PAID and _is_finance_user(),
        "invoice_count": invoice_summary["invoice_count"],
        "invoice_status": invoice_summary["invoice_status"],
        "invoice_handling_mode": _invoice_mode(getattr(doc, "invoice_handling_mode", None)),
        "invoice_followup_status": getattr(doc, "invoice_followup_status", None) or "",
        "expected_invoice_date": getattr(doc, "expected_invoice_date", None) or "",
        "invoice_search_text": invoice_summary.get("invoice_search_text", ""),
        "invoice_categories": invoice_summary.get("invoice_categories", []),
        "invoice_project_names": invoice_summary.get("invoice_project_names", []),
        "invoice_numbers": invoice_summary.get("invoice_numbers", []),
        "no_invoice_reason": getattr(doc, "no_invoice_reason", None) or "",
        "operation_log": _operation_events(doc),
        "attachments": _request_attachments(doc),
        "can_submit_procurement_quote": _can_submit_procurement_quote(doc, step),
        "can_modify_procurement_request": bool(
            doc.request_type == REQUEST_PROCUREMENT
            and doc.workflow_status in ACTIVE_STATUSES
            and step
            and _clean(getattr(step, "label", "")).startswith("PMC")
            and _is_pmc_user()
        ),
        "expense_lines": expense_lines,
        "business_lines": [
            _serialize_business_line(row)
            for row in (
                # New direct-purchase requests use their dedicated child table.
                # Fall back to the legacy shared table so historical requests
                # remain readable after the schema split.
                ((getattr(doc, "direct_purchase_lines", []) or [])
                 or (getattr(doc, "business_lines", []) or []))
                if doc.request_type == REQUEST_DIRECT_PURCHASE
                else (getattr(doc, "business_lines", []) or [])
            )
        ],
        "direct_purchase_lines": [
            _serialize_business_line(row)
            for row in (getattr(doc, "direct_purchase_lines", []) or [])
        ],
        "project_groups": _group_expense_sources(expense_lines),
        "steps": [_serialize_doc_step(row) for row in doc.steps],
        "pmc_change_version": getattr(doc, "pmc_change_version", None) or 0,
        "travel_destination": getattr(doc, "travel_destination", None) or "",
        "travel_start_date": getattr(doc, "travel_start_date", None),
        "travel_end_date": getattr(doc, "travel_end_date", None),
        "travel_days": getattr(doc, "travel_days", None) or 0,
        **_claim_summary(doc),
        "creation": doc.creation,
        "modified": doc.modified,
    }


def _claim_summary(doc):
    if getattr(doc, "request_type", None) not in {REQUEST_REIMBURSEMENT, REQUEST_PAYMENT}:
        return {}
    from rayher_hr_payroll.api import expense_claim_entry
    return expense_claim_entry.capabilities(doc)


def _load_request(name, *, current=False):
    if not name:
        frappe.throw(frappe._("\u7f3a\u5c11\u7533\u8bf7\u5355\u53f7\u3002"))
    if current:
        return invoice_service._current_doc("OA Approval Request", name)
    return frappe.get_doc("OA Approval Request", name)


def legacy_expense_closed():
    """报销单和付款单都在站点配置里启用后，才不再新建旧的费用付款申请。

    修复（2026-09-23）：原来只开其中一个就关闭旧入口，另一类付款就没有地方提交了。
    在途的旧单据照常审批、付款、补票，被驳回的旧草稿也能继续修改；把配置关掉即可回到旧入口。
    """
    from rayher_hr_payroll.oa_feature_gate import is_admin_only
    return not is_admin_only(REQUEST_REIMBURSEMENT) and not is_admin_only(REQUEST_PAYMENT)


def _require_legacy_expense_entry():
    if legacy_expense_closed():
        frappe.throw(frappe._("旧的费用付款申请已停用，请使用报销或付款。"))


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
        if doc.request_type in {REQUEST_EXPENSE_PAYMENT, REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE}:
            doc.approved_amount = getattr(doc, "amount", None) or 0
        if doc.request_type == REQUEST_PROCUREMENT:
            if _clean(getattr(step, "label", None)).startswith("价格审批："):
                # Legacy requests that still contain the old downstream OA steps.
                doc.business_status = "价格已批准/待补充合同信息"
                doc.contract_status = "待补充信息"
                doc.price_approved_by = _clean(getattr(step, "action_by", None))
                doc.price_approved_on = getattr(step, "acted_on", None)
            else:
                doc.business_status = "需求已批准/待询价"
        elif doc.request_type == REQUEST_DIRECT_PURCHASE and _clean(getattr(doc, "business_status", None)) == "待审批":
            doc.business_status = "待付款"
        elif doc.request_type in ATTENDANCE_TYPES:
            doc.business_status = "已完成"
        elif doc.request_type == REQUEST_TRAVEL:
            doc.business_status = "已通过"
        return
    doc.workflow_status = STATUS_WAIT_HANDLE if next_step.mode == "handle" else STATUS_PENDING
    if doc.request_type in {REQUEST_EXPENSE_PAYMENT, REQUEST_REIMBURSEMENT, REQUEST_PAYMENT} and next_step.mode == "handle":
        doc.business_status = "待付款"
    elif doc.request_type == REQUEST_PROCUREMENT:
        if _clean(getattr(next_step, "label", None)) == "采购询价/录入价格":
            doc.business_status = "需求已批准/待询价"
        elif _clean(getattr(next_step, "label", None)).startswith("价格审批："):
            doc.business_status = "待价格审批"
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


def _normalize_expense_lines(expense_lines, fallback_amount=0, fallback_subject=None, *, keep_incomplete=False):
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
        if amount < 0:
            frappe.throw("费用金额不能为负数。")
        if amount <= 0 and not source_invoice and not keep_incomplete:
            continue
        invoice_category = _clean(row.get("invoice_category"))
        project_name = _clean(row.get("project_name"))
        account_level_1 = _clean(row.get("expense_account_level_1"))
        account_level_2 = _clean(row.get("expense_account_level_2"))
        account_level_1, account_level_2, expense_item = _expense_account_pair(
            account_level_1, account_level_2, allow_incomplete=keep_incomplete
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


def _prepare_request_doc(
    *,
    request_type,
    subject=None,
    department=None,
    supervisor=None,
    asset_category=None,
    from_date=None,
    to_date=None,
    attendance_days=None,
    leave_type=None,
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
    invoice_handling_mode=None,
    expected_invoice_date=None,
    payment_source_kind=None,
    source_request=None,
):
    if request_type not in REQUEST_TYPES:
        frappe.throw(frappe._("\u4e0d\u652f\u6301\u7684 OA \u7533\u8bf7\u7c7b\u578b\u3002"))
    ctx = _route_context(department=department, supervisor=supervisor, asset_category=asset_category, request_type=request_type,
                         require_employee=_to_bool(submit))
    if request_type == REQUEST_EXPENSE_PAYMENT:
        classification = _expense_classification(doc_type, asset_category, submitting=submit)
        ctx["asset_category"] = classification["asset_category"]
        doc_type = classification["doc_type"]
    route = ({"steps": [], "copied_to": []} if request_type == REQUEST_EXPENSE_PAYMENT and not submit else preview_route(request_type, ctx["department"], ctx["supervisor"], ctx["asset_category"], active=submit))
    steps = route["steps"]
    if request_type in ATTENDANCE_TYPES and submit and (not from_date or not to_date):
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u8bf7\u5047\u5f00\u59cb\u548c\u7ed3\u675f\u65e5\u671f\u3002"))
    lines, total = _normalize_expense_lines(expense_lines, fallback_amount=amount, fallback_subject=subject, keep_incomplete=request_type == REQUEST_EXPENSE_PAYMENT and not submit)
    if request_type == REQUEST_EXPENSE_PAYMENT and submit and not lines:
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u8d39\u7528\u660e\u7ec6\u3002"))

    initial_status = steps[0]["status"] if submit else STATUS_DRAFT
    expense_asset = (
        {key: classification[key] for key in ("asset_nature", "fixed_asset_category")}
        if request_type == REQUEST_EXPENSE_PAYMENT
        else {"asset_nature": "", "fixed_asset_category": ""}
    )
    source_doc = frappe.get_doc("OA Approval Request", source_request) if source_request else None
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
            "attendance_days": json.dumps(attendance_days) if isinstance(attendance_days, list) else attendance_days,
            "leave_type": leave_type or "",
            "from_date": from_date,
            "to_date": to_date,
            "amount": total if request_type == REQUEST_EXPENSE_PAYMENT else _money(amount),
            "asset_category": ctx.get("asset_category"),
            "asset_nature": expense_asset["asset_nature"],
            "fixed_asset_category": expense_asset["fixed_asset_category"],
            "business_status": "待审批" if submit else "",
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
            "invoice_handling_mode": _invoice_mode(invoice_handling_mode),
            "invoice_followup_status": "",
            "expected_invoice_date": expected_invoice_date or None,
            "payment_source_kind": payment_source_kind or ("无事前申请" if not source_request else ""),
            "source_request": source_request or None,
            "approved_amount_snapshot": getattr(source_doc, "approved_amount", None) if source_doc else None,
            "source_modified": getattr(source_doc, "modified", None) if source_doc else None,
            "reason": reason or "",
            "operation_log": "[]",
            "current_step_index": 1 if submit else 0,
            "current_step_label": steps[0]["label"] if submit else "",
        }
    )
    _append_steps(doc, steps)
    _set_expense_lines(doc, lines)
    return doc


def _build_request_doc(**values):
    doc = _prepare_request_doc(**values)
    _insert_document(doc)
    if values.get("submit", True) and doc.request_type != REQUEST_PROCUREMENT_PAYMENT:
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


def _expense_classification(doc_type, asset_category, *, submitting=False):
    kind = _clean(doc_type)
    category = _clean(asset_category)
    if not kind:
        kind = "固定资产" if category and normalize_asset_category(category) != OTHER_ASSET else "非固定资产"
    if kind == "非固定资产":
        return {"doc_type": kind, "asset_category": OTHER_ASSET, "asset_nature": "非固定资产", "fixed_asset_category": ""}
    if kind != "固定资产" and kind not in DOC_TYPES[1:]:
        frappe.throw("不支持的单据类型。")
    if category and category not in ASSET_CATEGORIES:
        frappe.throw("不支持的资产类型。")
    if submitting and (not category or category == OTHER_ASSET):
        frappe.throw("固定资产必须选择具体资产类型。")
    if category == OTHER_ASSET:
        category = ""
    return {"doc_type": kind, "asset_category": category, "asset_nature": "固定资产", "fixed_asset_category": EXPENSE_FIXED_CATEGORY_BY_ASSET.get(category, "")}


def _required_asset_category(value):
    if not _clean(value):
        frappe.throw(frappe._("提交报销前必须选择资产类型。"))
    try:
        return normalize_asset_category(value)
    except ApprovalRouteError as exc:
        frappe.throw(str(exc))


def _expense_dashboard_classification(asset_category):
    normalized = normalize_asset_category(asset_category)
    fixed_category = EXPENSE_FIXED_CATEGORY_BY_ASSET.get(normalized, "")
    return {
        "asset_category": normalized,
        "asset_nature": "固定资产" if fixed_category else "非固定资产",
        "fixed_asset_category": fixed_category,
    }


def _validate_invoice_handling_submission(doc):
    summary = invoice_service.request_invoice_summary(doc)
    mode = _invoice_mode(getattr(doc, "invoice_handling_mode", None))
    if not mode:
        frappe.throw(frappe._("请选择发票处理方式。"))
    source_name = _clean(getattr(doc, "source_request", None))
    source_kind = _clean(getattr(doc, "payment_source_kind", None))
    requires_purchase_source = (
        mode in {INVOICE_MODE_PENDING, INVOICE_MODE_NOT_REQUIRED}
        and _clean(getattr(doc, "source_type", None)) == SOURCE_MANUAL
    )
    if requires_purchase_source and not source_name:
        frappe.throw(frappe._("暂未取得发票或无需发票的付款必须关联已批准的购买申请。"))
    if source_name:
        source = frappe.get_doc("OA Approval Request", source_name)
        if source.request_type != REQUEST_DIRECT_PURCHASE:
            frappe.throw(frappe._("付款/报销入口只能关联购买申请；正式采购请使用采购付款流程。"))
        if source.workflow_status != STATUS_COMPLETED:
            frappe.throw(frappe._("付款来源申请尚未审批完成。"))
        balance = _run_approval_amount_operation(approval_amount_ledger.source_balance, source)
        if _money(getattr(doc, "amount", None)) > balance["available_amount"]:
            frappe.throw(frappe._("本次付款金额超过来源购买申请的可付款余额。"))
        doc.payment_source_kind = source_kind or "关联购买申请"
        doc.approved_amount_snapshot = getattr(source, "approved_amount", None)
        doc.source_modified = getattr(source, "modified", None)
    elif mode == INVOICE_MODE_AVAILABLE:
        doc.payment_source_kind = "无事前申请"
    invoice_count = int(summary.get("invoice_count") or 0)
    reason = _clean(getattr(doc, "no_invoice_reason", None))
    if mode == INVOICE_MODE_AVAILABLE:
        if not invoice_count:
            frappe.throw(frappe._("选择已有发票时必须上传并确认发票。"))
        summary = invoice_service.validate_request_invoices(doc, submitting=True)
        doc.invoice_followup_status = INVOICE_FOLLOWUP_RECEIVED
        doc.expected_invoice_date = None
    elif mode == INVOICE_MODE_PENDING:
        if invoice_count:
            frappe.throw(frappe._("已上传发票时请选择已有发票。"))
        if not reason:
            frappe.throw(frappe._("暂未取得发票时必须填写原因。"))
        expected_value = getattr(doc, "expected_invoice_date", None)
        # 修复（2026-09-22）：草稿从数据库读出的是日期对象，原来只接受字符串，
        # 先保存再提交的"暂未取得发票"草稿会报"预计取得发票日期格式无效"。
        if isinstance(expected_value, date):
            expected_value = expected_value.isoformat()
        expected = _report_date(expected_value, "预计取得发票日期")
        if not expected:
            frappe.throw(frappe._("暂未取得发票时必须填写预计取得发票日期。"))
        doc.expected_invoice_date = expected
        doc.invoice_followup_status = INVOICE_FOLLOWUP_PENDING
    else:
        if invoice_count:
            frappe.throw(frappe._("已上传发票时不能选择无需发票。"))
        if not reason:
            frappe.throw(frappe._("无需发票时必须填写原因。"))
        doc.expected_invoice_date = None
        doc.invoice_followup_status = INVOICE_FOLLOWUP_NOT_REQUIRED
    doc.invoice_count = summary.get("invoice_count", 0)
    doc.invoice_status = summary.get("invoice_status", "")
    return summary


def _validate_procurement_plan_payment(doc):
    po_name = _clean(getattr(doc, "source_purchase_order", None))
    po_row_name = _clean(getattr(doc, "source_po_payment_plan_row", None))
    if po_name and po_row_name:
        po = frappe.get_doc("OA Purchase Order", po_name, for_update=True)
        if getattr(po, "contract_status", None) != "已生效":
            frappe.throw(frappe._("来源采购合同尚未生效。"))
        row = next((item for item in (getattr(po, "payment_plan", []) or []) if _clean(getattr(item, "name", None)) == po_row_name), None)
        if not row:
            frappe.throw(frappe._("来源 PO 付款计划期次不存在。"))
        if _clean(getattr(row, "status", None)) not in {"待审批", "审批中"}:
            frappe.throw(frappe._("来源 PO 付款计划期次已下推或已付款。"))
        if _clean(getattr(row, "payment_request", None)) not in {"", _clean(getattr(doc, "name", None))}:
            frappe.throw(frappe._("该 PO 付款计划期次已经生成其他采购付款，不能重复提交。"))
        if (_clean(getattr(po, "currency", None)) or "CNY") != "CNY":
            frappe.throw(frappe._("采购订单目前只支持人民币（CNY）。"))
        if _money(getattr(row, "amount", None)) != _money(getattr(doc, "amount", None)):
            frappe.throw(frappe._("采购付款金额必须与 PO 付款计划期次一致。"))
        if _clean(getattr(row, "payment_stage", None)) != _clean(getattr(doc, "payment_stage", None)):
            frappe.throw(frappe._("采购付款阶段必须与 PO 付款计划期次一致。"))
        from rayher_hr_payroll.api.procurement_chain import _require_po_payment_ready
        _require_po_payment_ready(po, row)
        return _clean(getattr(row, "payment_stage", None))
    source = frappe.get_doc("OA Approval Request", _clean(getattr(doc, "source_request", None)))
    if getattr(source, "contract_status", None) != "已生效":
        frappe.throw(frappe._("来源采购合同尚未生效。"))
    row = _find_payment_plan_row(source, getattr(doc, "source_payment_plan_row", None))
    if not row:
        frappe.throw(frappe._("来源付款计划期次不存在。"))
    if _clean(getattr(row, "status", None)) != "待下推":
        frappe.throw(frappe._("来源付款计划期次已下推或已付款。"))
    if _money(getattr(row, "amount", None)) != _money(getattr(doc, "amount", None)):
        frappe.throw(frappe._("采购付款金额必须与付款计划期次一致。"))
    if _clean(getattr(row, "payment_stage", None)) != _clean(getattr(doc, "payment_stage", None)):
        frappe.throw(frappe._("采购付款阶段必须与付款计划期次一致。"))
    trigger = _clean(getattr(row, "trigger_condition", None))
    if "验收" in trigger and _clean(getattr(source, "inspection_status", None)) != "验收通过":
        frappe.throw(frappe._("该付款计划要求验收通过后才能提交付款。"))
    if _clean(getattr(doc, "payment_stage", None)) == "预付款" and _money(
        getattr(doc, "prepayment_percentage", None)
    ) == Decimal("100") and not _clean(getattr(doc, "prepayment_risk_note", None)):
        frappe.throw(frappe._("100%预付款必须填写风险说明。"))
    return _clean(getattr(row, "payment_stage", None))


def _validate_procurement_payment_release(doc):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
        return
    po_name = _clean(getattr(doc, "source_purchase_order", None))
    po_row_name = _clean(getattr(doc, "source_po_payment_plan_row", None))
    if po_name and po_row_name:
        po = frappe.get_doc("OA Purchase Order", po_name, for_update=True)
        row = next((item for item in (getattr(po, "payment_plan", []) or []) if _clean(getattr(item, "name", None)) == po_row_name), None)
        if not row:
            frappe.throw("来源 PO 付款计划期次不存在。")
        from rayher_hr_payroll.api.procurement_chain import _require_po_payment_ready
        _require_po_payment_ready(po, row)
        if _clean(getattr(row, "invoice_requirement", None)) == "付款前提供" and "发票" not in _request_business_document_types(doc.name):
            frappe.throw(frappe._("该 PO 付款计划要求付款前提供发票，请上传发票后再确认付款。"))
        return
    source_name = _clean(getattr(doc, "source_request", None))
    row_name = _clean(getattr(doc, "source_payment_plan_row", None))
    if not source_name or not row_name:
        return
    source = frappe.get_doc("OA Approval Request", source_name)
    row = _find_payment_plan_row(source, row_name)
    if row and _clean(getattr(row, "invoice_requirement", None)) == "付款前提供":
        if "发票" not in _request_business_document_types(doc.name):
            frappe.throw(frappe._("该付款计划要求付款前提供发票，请上传发票后再确认付款。"))


def _submit_draft(doc):
    if doc.workflow_status != STATUS_DRAFT:
        return
    old_status = doc.workflow_status
    if doc.request_type in ATTENDANCE_TYPES and (not doc.from_date or not doc.to_date):
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u8bf7\u5047\u5f00\u59cb\u548c\u7ed3\u675f\u65e5\u671f\u3002"))
    if doc.request_type == REQUEST_EXPENSE_PAYMENT and not list(getattr(doc, "expense_lines", []) or []):
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u8d39\u7528\u660e\u7ec6\u3002"))
    if doc.request_type == REQUEST_EXPENSE_PAYMENT:
        classification = _expense_classification(getattr(doc, "doc_type", None), getattr(doc, "asset_category", None), submitting=True)
        for fieldname, value in classification.items():
            setattr(doc, fieldname, value)
        for line in doc.expense_lines:
            if not getattr(line, "issue_date", None) or _money(getattr(line, "amount", None)) <= 0:
                frappe.throw("提交前必须填写每项费用的日期和正数金额。")
            level_1, level_2, display = _expense_account_pair(
                getattr(line, "expense_account_level_1", None),
                getattr(line, "expense_account_level_2", None),
            )
            line.expense_account_level_1 = level_1
            line.expense_account_level_2 = level_2
            line.expense_item = display
            line.category = _clean(getattr(line, "invoice_category", None)) or display or REQUEST_EXPENSE_PAYMENT
        _validate_expense_project_groups(doc)
        _validate_invoice_handling_submission(doc)
    elif doc.request_type == REQUEST_PROCUREMENT:
        for line in list(getattr(doc, "business_lines", []) or []):
            if not _clean(getattr(line, "material_serial", None)):
                suffix = frappe.model.naming.make_autoname("MAT-.#####").split("-")[-1]
                line.material_serial = f"MAT-{date.today().year}-{suffix}"
        try:
            validate_procurement_submission(doc)
        except ProcurementWorkflowError as exc:
            frappe.throw(str(exc))
    elif doc.request_type in {REQUEST_REIMBURSEMENT, REQUEST_PAYMENT}:
        from rayher_hr_payroll.api import expense_claim_entry
        expense_claim_entry.validate_submit(doc)
    elif doc.request_type == REQUEST_PROCUREMENT_PAYMENT:
        balance = approval_amount_ledger.source_balance(doc.source_request)
        doc.source_paid_amount = balance["paid_amount"]
        doc.source_available_amount = balance["available_amount"]
        # 修复（2026-09-24，审查 R3-57 / R3-52-1）：从审批中心按 PO 期次建的采购付款只带
        # source_po_payment_plan_row，原来走旧的校验，跳过了 PO 期次的状态、金额、阶段和到货验收条件。
        if _clean(getattr(doc, "source_payment_plan_row", None)) or _clean(getattr(doc, "source_po_payment_plan_row", None)):
            doc.payment_stage = _validate_procurement_plan_payment(doc)
        else:
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
    if doc.request_type == REQUEST_TRAVEL:
        from rayher_hr_payroll.travel_requests import TravelRequestError, normalize_travel
        try:
            travel = normalize_travel({
                field: getattr(doc, field, None)
                for field in ("subject", "travel_destination", "travel_start_date", "travel_end_date", "reason", "project")
            })
        except TravelRequestError as exc:
            frappe.throw(str(exc))
        doc.travel_days = travel["travel_days"]
    ctx = _route_context(
        department=getattr(doc, "department", None),
        supervisor=getattr(doc, "supervisor", None),
        asset_category=getattr(doc, "asset_category", None),
        request_type=doc.request_type,
        applicant_employee=getattr(doc, "employee", None),
        require_employee=True,
    )
    doc.department = ctx["department"]
    doc.supervisor = ctx["supervisor"]
    route = preview_route(
        doc.request_type, ctx["department"], ctx["supervisor"], ctx["asset_category"], active=True,
        project_owner=getattr(doc, "project_owner", None),
        project_owner_name=getattr(doc, "project_owner_name", None),
        purchase_method=getattr(doc, "purchase_method", None),
        payment_stage=getattr(doc, "payment_stage", None),
        applicant_employee=getattr(doc, "employee", None),
    )
    doc.copied_to = _json_list(route.get("copied_to") or [])
    steps = route["steps"]
    _append_steps(doc, steps)
    if not steps:
        frappe.throw(frappe._("审批路线不能为空，请先维护申请人的组织审批关系。"))
    doc.workflow_status = steps[0]["status"]
    doc.business_status = "待审批"
    doc.current_step_index = 1
    doc.current_step_label = steps[0]["label"]
    _append_request_event(doc, "提交申请", old_status, doc.workflow_status)


def _is_procurement_global_reader(user=None, request_type=None):
    candidate = _clean(user or frappe.session.user)
    roles = set(frappe.get_roles(candidate) or [])
    if candidate in {"Administrator", "admin@staff.example.invalid"} or roles & PROCUREMENT_GLOBAL_ROLES:
        return True
    # Finance has global visibility for payment requests only. It does not
    # receive the procurement-demand register merely by having Accounts User.
    return request_type == REQUEST_PROCUREMENT_PAYMENT and "Accounts User" in roles


def _procurement_row_is_related(doc, user, context):
    employee = context.get("employee") if context else None
    return bool(
        getattr(doc, "employee", None) == employee
        or getattr(doc, "owner", None) == user
        or (
            getattr(doc, "request_type", None) in PROCUREMENT_REQUEST_TYPES
            and getattr(doc, "purchaser_user", None) == user
        )
        or _can_act_on_current_step(doc, user)
    )


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
        "expense_doc_types": ["非固定资产", "固定资产"],
        "urgencies": URGENCY,
        "payment_types": PAYMENT_TYPES,
        "payment_methods": PAYMENT_METHODS,
        "invoice_handling_modes": INVOICE_HANDLING_MODES,
        "companies": COMPANIES,
        "context": context,
        "current_applicant": {
            "employee": context.get("employee"),
            "employee_name": context.get("employee_name") or "",
            "user": frappe.session.user,
            "department": context.get("department") or "",
            "supervisor": context.get("supervisor") or "",
        },
        "can_manage_expense": bool(roles & FINANCE_ROLES),
        "can_see_all": bool(roles & PRIVILEGED_ROLES),
        "procurement_global_access": {
            request_type: _is_procurement_global_reader(frappe.session.user, request_type)
            for request_type in PROCUREMENT_REQUEST_TYPES
        },
        "can_submit_procurement_for_others": _can_submit_procurement_for_others(),
        "can_manage_procurement_catalog": _can_maintain_procurement_catalog(),
    }


@frappe.whitelist()
def preview_route(
    request_type, department=None, supervisor=None, asset_category=None, active=True,
    project_owner=None, project_owner_name=None, purchase_method=None, payment_stage=None,
    applicant_employee=None,
):
    require_request_type_access(request_type)
    try:
        ctx = _route_context(
            department=department,
            supervisor=supervisor,
            asset_category=asset_category,
            request_type=request_type,
            applicant_employee=applicant_employee,
            require_employee=_to_bool(active),
        )
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
            upper_supervisor=ctx.get("upper_supervisor"),
            upper_supervisor_user=ctx.get("upper_supervisor_user"),
            roles=roles,
        )
        copied_to = (
            leave_copy_recipients(ctx.get("applicant_user"), roles=roles)
            if request_type in ATTENDANCE_TYPES else []
        )
        if request_type in ATTENDANCE_TYPES:
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
    attendance_days=None,
    leave_type=None,
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
    invoice_handling_mode=None,
    expected_invoice_date=None,
    payment_source_kind=None,
    source_request=None,
):
    if request_type == REQUEST_PROCUREMENT_PAYMENT:
        frappe.throw(frappe._("采购付款必须由 PO 付款计划下推生成，不能单独新建。"))
    if request_type in (REQUEST_TRAVEL, REQUEST_REIMBURSEMENT, REQUEST_PAYMENT):
        # 修复（2026-09-23）：这三类单据有各自的草稿接口（travel_entry / expense_claim_entry），
        # 关联申请的校验和购买申请额度的占用都在那里；从这个通用接口新建并提交会绕过额度占用，
        # 超额的单据能审批通过，到出纳付款时才报错。
        frappe.throw(frappe._("出差申请、报销单、付款单请在各自的页面新建。"))
    if request_type == REQUEST_EXPENSE_PAYMENT:
        # 旧的费用付款申请停用后不能再新建；在途单据和被驳回的旧草稿不受影响。
        _require_legacy_expense_entry()
    require_request_type_access(request_type)
    requested_submit = _to_bool(submit)
    batch_name = _bounded_optional_text(invoice_batch, "发票批次", 140)
    no_invoice_reason = _bounded_optional_text(no_invoice_reason, "无票原因", 1000)
    invoice_handling_mode = _invoice_mode(invoice_handling_mode) or (INVOICE_MODE_AVAILABLE if batch_name else "")
    doc = _build_request_doc(
        request_type=request_type,
        subject=subject,
        department=department,
        supervisor=supervisor,
        asset_category=asset_category,
        from_date=from_date,
        to_date=to_date,
        attendance_days=attendance_days,
        leave_type=leave_type,
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
        invoice_handling_mode=invoice_handling_mode,
        expected_invoice_date=expected_invoice_date,
        payment_source_kind=_bounded_optional_text(payment_source_kind, "付款来源类型", 40),
        source_request=_bounded_optional_text(source_request, "来源申请", 140),
    )
    if batch_name:
        doc = invoice_service.attach_batch_to_request(batch_name, doc)
    draft_summary = invoice_service.validate_request_invoices(doc, submitting=False)
    if isinstance(draft_summary, dict):
        doc.invoice_count = draft_summary.get("invoice_count", 0)
        doc.invoice_status = draft_summary.get("invoice_status", "")
    if requested_submit:
        _submit_draft(doc)
        _reserve_expense_payment(doc)
    _save_document(doc)
    if requested_submit:
        _sync_assignments_after_save(doc)
        if doc.request_type in ATTENDANCE_TYPES:
            _notify_copied_users(doc)
    return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
@attendance_request_transaction
def update_leave_draft(name, subject, from_date, to_date, reason=None, attendance_days=None, leave_type=None):
    request_name = _bounded_optional_text(name, "Request", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        invoice_service._request_permission(doc, "edit", current=True)
        if doc.request_type not in ATTENDANCE_TYPES or doc.workflow_status != STATUS_DRAFT:
            frappe.throw(frappe._("\u53ea\u6709\u8bf7\u5047\u8349\u7a3f\u53ef\u4ee5\u4fee\u6539\u3002"))
        clean_subject = _bounded_optional_text(subject, "\u4e3b\u9898", 140)
        clean_reason = _bounded_optional_text(reason, "\u4e8b\u7531", 1000)
        start_date = _report_date(from_date, "\u5f00\u59cb\u65e5\u671f")
        end_date = _report_date(to_date, "\u7ed3\u675f\u65e5\u671f")
        if not clean_subject or not start_date or not end_date:
            frappe.throw(frappe._("\u8bf7\u5047\u4e3b\u9898\u3001\u5f00\u59cb\u65e5\u671f\u548c\u7ed3\u675f\u65e5\u671f\u4e0d\u80fd\u4e3a\u7a7a\u3002"))
        if start_date > end_date:
            frappe.throw(frappe._("\u5f00\u59cb\u65e5\u671f\u4e0d\u80fd\u665a\u4e8e\u7ed3\u675f\u65e5\u671f\u3002"))
        doc.attendance_days = json.dumps(attendance_days) if isinstance(attendance_days, list) else attendance_days
        doc.leave_type = leave_type or ""
        doc.subject = clean_subject
        doc.from_date = start_date
        doc.to_date = end_date
        doc.reason = clean_reason
        _save_document(doc)
        return _summarize_doc(doc)


def _draft_source_rows(source_lines):
    rows = _parse_json(source_lines, None)
    if not isinstance(rows, list) or len(rows) > 200:
        frappe.throw(frappe._("报销费用明细格式无效，单次最多 200 行。"))
    for row in rows:
        if not isinstance(row, dict):
            frappe.throw(frappe._("报销费用明细格式无效。"))
    return rows


def _expense_account_pair(level_1, level_2, *, required=False, allow_incomplete=False):
    level_1 = _clean(level_1)
    level_2 = _clean(level_2)
    if not required and not level_1 and not level_2:
        return "", "", ""
    if allow_incomplete and level_1 and not level_2:
        options = {row["level_1"]: row["level_2"] for row in account_options()}
        if options.get(level_1):
            return level_1, "", ""
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
def update_manual_expense_draft(name, payload):
    """Resume the original manual draft without replacing invoice-linked sources."""
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    values = _parse_json(payload, None)
    if not isinstance(values, dict):
        frappe.throw("草稿格式无效。")
    editable = ("subject", "company", "doc_type", "urgency", "asset_category", "reason",
                "payment_type", "payment_method", "bank_name", "payee_name", "branch", "account_no",
                "no_invoice_reason", "invoice_handling_mode", "expected_invoice_date", "payment_source_kind", "source_request")
    with invoice_service._transaction_lock("request", name):
        doc = _load_request(name, current=True)
        invoice_service._request_permission(doc, "edit", current=True)
        if doc.request_type != REQUEST_EXPENSE_PAYMENT or doc.workflow_status != STATUS_DRAFT:
            frappe.throw("只有费用申请草稿可以继续编辑。")
        if any(_clean(getattr(row, "source_invoice", None)) for row in doc.expense_lines):
            frappe.throw("发票生成的申请请在详情中编辑，不能替换发票明细。")
        rows = _draft_source_rows(values.get("expense_lines", []))
        if any(row.get("source_invoice") or row.get("source_consumption") for row in rows):
            frappe.throw("手工草稿不能指定发票关联。")
        replacement = _prepare_request_doc(request_type=REQUEST_EXPENSE_PAYMENT, submit=False,
            expense_lines=rows, **{key: values.get(key, getattr(doc, key, None)) for key in editable})
        for key in editable + ("asset_nature", "fixed_asset_category", "amount", "approved_amount_snapshot", "source_modified"):
            if hasattr(replacement, key):
                setattr(doc, key, getattr(replacement, key))
        _set_expense_lines(doc, [row.as_dict() if hasattr(row, "as_dict") else dict(row) for row in replacement.expense_lines])
        _save_document(doc)
        return _summarize_doc(doc)


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



FINANCE_AUDIT_LABEL_PREFIX = "\u8d22\u52a1\u5ba1\u6838"


def _is_finance_audit_step(step):
    return bool(step and getattr(step, "mode", None) == "approve" and _clean(getattr(step, "label", None)).startswith(("出纳审核", FINANCE_AUDIT_LABEL_PREFIX)))


def _classification_ready(doc):
    if getattr(doc, "request_type", None) not in {REQUEST_EXPENSE_PAYMENT, REQUEST_REIMBURSEMENT, REQUEST_PAYMENT}:
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


def _workflow_ledger_kwargs(workflow):
    """工作流发起的台账操作（驳回释放、确认付款、盖章后自动下推）不按当前操作人的来源权限校验。

    修复（2026-09-29，审查 X1-4 / #12）：默认的台账存储只放行管理员、财务和来源申请的经办人；
    副总驳回、总经理确认付款、副总盖章后自动下推占用时，操作人不是这些人，整个操作失败。
    旧费用付款、报销单、付款单已经这样处理（WorkflowLedgerStore），这里把采购付款旧路径补上。
    申请人自己提交时仍按默认存储校验。
    """
    return {"store": approval_amount_ledger.WorkflowLedgerStore()} if workflow else {}


def _reserve_procurement_payment(doc, workflow=False):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
        return None
    if _clean(getattr(doc, "source_purchase_order", None)):
        return _sync_payment_plan_row(doc, "已下推")
    revision = _procurement_payment_revision(doc)
    result = _run_approval_amount_operation(
        approval_amount_ledger.reserve,
        _clean(getattr(doc, "source_request", None)),
        doc.name,
        "submit:{0}:{1}".format(doc.name, revision),
        note="采购付款提交占用",
        **_workflow_ledger_kwargs(workflow),
    )
    _sync_payment_plan_row(doc, "已下推")
    return result


def _release_procurement_payment_reservation(doc, note=""):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
        return None
    if _clean(getattr(doc, "source_purchase_order", None)):
        return _sync_payment_plan_row(doc, "待下推")
    revision = _procurement_payment_revision(doc)
    result = _run_approval_amount_operation(
        approval_amount_ledger.release_all_reserved,
        _clean(getattr(doc, "source_request", None)),
        doc.name,
        "release:{0}:{1}".format(doc.name, revision),
        note=note or "采购付款退回释放占用",
        **_workflow_ledger_kwargs(True),
    )
    _sync_payment_plan_row(doc, "待下推")
    return result


def _mark_procurement_payment_paid(doc):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
        return None
    if _clean(getattr(doc, "source_purchase_order", None)):
        return _sync_payment_plan_row(doc, "已付款")
    result = _run_approval_amount_operation(
        approval_amount_ledger.mark_paid,
        _clean(getattr(doc, "source_request", None)),
        doc.name,
        "pay:{0}".format(doc.name),
        note="采购付款确认付款",
        **_workflow_ledger_kwargs(True),
    )
    _sync_payment_plan_row(doc, "已付款")
    return result


def _reserve_expense_payment(doc):
    if getattr(doc, "request_type", None) != REQUEST_EXPENSE_PAYMENT or not _clean(getattr(doc, "source_request", None)):
        return None
    revision = _procurement_payment_revision(doc)
    return _run_approval_amount_operation(
        approval_amount_ledger.reserve,
        _clean(doc.source_request), doc.name,
        "expense-submit:{0}:{1}".format(doc.name, revision),
        note="购买申请付款提交占用",
    )


def _release_expense_payment_reservation(doc, note=""):
    if getattr(doc, "request_type", None) != REQUEST_EXPENSE_PAYMENT or not _clean(getattr(doc, "source_request", None)):
        return None
    revision = _procurement_payment_revision(doc)
    # 修复（2026-09-22）：驳回人可能是直属主管等非申请人，改用工作流台账存储，见 WorkflowLedgerStore。
    return _run_approval_amount_operation(
        approval_amount_ledger.release_all_reserved,
        _clean(doc.source_request), doc.name,
        "expense-release:{0}:{1}".format(doc.name, revision),
        note=note or "购买申请付款退回释放占用",
        store=approval_amount_ledger.WorkflowLedgerStore(),
    )


def _expense_payment_round(doc):
    """第几次付款：每撤回一次付款加一。"""
    return 1 + sum(1 for event in _operation_events(doc) if event.get("action") == "撤回付款")


def _round_key(base, round_no):
    # 第一次付款沿用原来的幂等键，已有台账记录不受影响。
    return base if round_no == 1 else "{0}:{1}".format(base, round_no)


def _mark_expense_payment_paid(doc):
    if getattr(doc, "request_type", None) != REQUEST_EXPENSE_PAYMENT or not _clean(getattr(doc, "source_request", None)):
        return None
    # 修复（2026-09-22）：原来的键固定为 expense-pay:<单号>，财务撤回付款后再付款会被当成
    # 重复请求直接跳过，单据显示已付款但台账没有记账。现在键里带上付款轮次。
    return _run_approval_amount_operation(
        approval_amount_ledger.mark_paid,
        _clean(doc.source_request), doc.name,
        _round_key("expense-pay:{0}".format(doc.name), _expense_payment_round(doc)),
        note="购买申请付款确认付款",
        store=approval_amount_ledger.WorkflowLedgerStore(),
    )


def _reverse_expense_payment_paid(doc, note=""):
    if getattr(doc, "request_type", None) != REQUEST_EXPENSE_PAYMENT or not _clean(getattr(doc, "source_request", None)):
        return None
    round_no = _expense_payment_round(doc)
    result = _run_approval_amount_operation(
        approval_amount_ledger.reverse,
        _clean(doc.source_request), doc.name, _money(doc.amount),
        _round_key("expense-reverse:{0}".format(doc.name), round_no),
        note=note or "撤回购买申请付款",
        store=approval_amount_ledger.WorkflowLedgerStore(),
    )
    # 修复（2026-09-22）：冲回已付后重新占用这笔金额，否则再次付款时台账没有可支付的占用。
    return _run_approval_amount_operation(
        approval_amount_ledger.reserve,
        _clean(doc.source_request), doc.name,
        "expense-rereserve:{0}:{1}".format(doc.name, round_no),
        note="撤回付款后重新占用",
        store=approval_amount_ledger.WorkflowLedgerStore(),
    ) or result


def _set_procurement_payment_paid_state(doc):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
        return doc
    po_name = _clean(getattr(doc, "source_purchase_order", None))
    if po_name:
        # 修复（2026-09-24，审查 X1-7）：PO 付款的到货和验收取自 PO 明细，不再停在下推时的"未到货/未验收"。
        from rayher_hr_payroll.api.procurement_chain import po_fulfilment_state
        for fieldname, value in po_fulfilment_state(frappe.get_doc("OA Purchase Order", po_name)).items():
            setattr(doc, fieldname, value)
        doc.prepayment_writeoff_status = "无需核销"
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
@attendance_request_transaction
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
        _reserve_expense_payment(doc)
        if doc.request_type in {REQUEST_REIMBURSEMENT, REQUEST_PAYMENT}:
            from rayher_hr_payroll.api import expense_claim_entry
            expense_claim_entry.reserve(doc)
        _save_document(doc)
        _sync_assignments_after_save(doc)
        if doc.request_type != REQUEST_PROCUREMENT_PAYMENT:
            _notify_copied_users(doc)
        return _summarize_doc(doc)


def _step_snapshot(doc, prefix, role_label):
    for step in list(getattr(doc, "steps", []) or []):
        if _clean(getattr(step, "label", None)).startswith(prefix):
            users = _parse_json_list(getattr(step, "approvers", None))
            if users:
                return {"label": role_label, "user": _clean(users[0])}
    return {"label": role_label, "user": ""}


def _request_applicant_user(doc):
    employee = _clean(getattr(doc, "employee", None))
    user = (
        _clean(frappe.db.get_value("Employee", employee, "user_id"))
        if employee
        else ""
    )
    return user or _clean(getattr(doc, "owner", None))


def _contract_copy_snapshot(doc):
    return {
        "applicant": {"label": "申请人", "user": _request_applicant_user(doc)},
        "purchaser": {"label": "采购经办人", "user": _clean(getattr(doc, "purchaser_user", None))},
        "pmc": _step_snapshot(doc, "PMC", "PMC"),
        "supervisor": _step_snapshot(doc, "直属主管", "直属上级"),
        "project_owner": {"label": "项目主管", "user": _clean(getattr(doc, "project_owner", None))},
    }


def _can_maintain_procurement_catalog():
    from rayher_hr_payroll.api.procurement_materials import can_maintain_catalog
    return can_maintain_catalog()


def _is_pmc_user(user=None):
    """Return true only for the dynamically assigned PMC account.

    System administrators can inspect the queue, but they must not inherit
    PMC-only material editing or catalog-maintenance capabilities.
    """
    candidate = _clean(user or frappe.session.user).lower()
    try:
        return bool(candidate) and candidate == _clean(resolve_role("pmc").get("user")).lower()
    except (ApprovalRoleResolutionError, RuntimeError, ImportError):
        return False


def _notify_procurement_modification(doc, recipients):
    for row in recipients or []:
        user = _clean(row.get("user") if isinstance(row, dict) else "").lower()
        if not user or user == _clean(frappe.session.user).lower():
            continue
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": user,
            "type": "Alert",
            "document_type": "OA Approval Request",
            "document_name": doc.name,
            "subject": "采购申请已由 PMC 修改：" + str(doc.name),
            "email_content": "采购申请 {0} 已由 PMC 修改，请按修改后的版本查阅。".format(doc.name),
        }).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def modify_procurement_request(name, business_lines=None, expected_delivery_date=None, reason=None, subject=None):
    """Allow PMC to enrich an active procurement request without resetting upstream approvals."""
    request_name = _bounded_optional_text(name, "申请单号", 140)
    if not _is_pmc_user():
        frappe.throw(frappe._("只有 PMC 可以修改审批中的采购申请。"))
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        if doc.request_type != REQUEST_PROCUREMENT:
            frappe.throw(frappe._("只有采购申请可以由 PMC 修改。"))
        # 修复（2026-09-29，审查 #8）：采购申请功能关闭时 PMC 也不能改。
        require_request_type_access(doc.request_type)
        step = _current_step(doc)
        if doc.workflow_status not in ACTIVE_STATUSES or not step or not _clean(getattr(step, "label", "")).startswith("PMC"):
            frappe.throw(frappe._("采购申请只有流转到 PMC 节点后才能修改。"))
        before = {
            "business_lines": [_serialize_business_line(row) for row in list(getattr(doc, "business_lines", []) or [])],
            "expected_delivery_date": _clean(getattr(doc, "expected_delivery_date", None)),
            "subject": _clean(getattr(doc, "subject", None)),
            "reason": _clean(getattr(doc, "reason", None)),
        }
        supplied_lines = _parse_json(business_lines, None) if isinstance(business_lines, str) else business_lines
        if supplied_lines is not None:
            if not isinstance(supplied_lines, list) or not supplied_lines or len(supplied_lines) > 100:
                frappe.throw(frappe._("采购明细格式无效。"))
            doc.set("business_lines", [
                {key: row.get(key) for key in (
                    "material_code", "material_serial", "category_code", "category_path", "item_name", "specification",
                    "product_desc", "brand", "product_name", "product_desc_en", "brand_en", "material_attr",
                    "quantity", "unit", "unit_price", "remarks",
                ) if key in row}
                for row in supplied_lines if isinstance(row, dict)
            ])
        if expected_delivery_date is not None:
            doc.expected_delivery_date = expected_delivery_date
        if reason is not None:
            doc.reason = _bounded_optional_text(reason, "申请说明", 1000)
        if subject is not None:
            doc.subject = _bounded_optional_text(subject, "主题", 140)
        after = {
            "business_lines": [_serialize_business_line(row) for row in list(getattr(doc, "business_lines", []) or [])],
            "expected_delivery_date": _clean(getattr(doc, "expected_delivery_date", None)),
            "subject": _clean(getattr(doc, "subject", None)),
            "reason": _clean(getattr(doc, "reason", None)),
        }
        changed = {key: {"before": before[key], "after": after[key]} for key in before if before[key] != after[key]}
        if not changed:
            frappe.throw(frappe._("没有检测到采购申请修改。"))
        recipients = contract_copy_recipients(_contract_copy_snapshot(doc))
        recipients = [row for row in recipients if row.get("label") in {"申请人", "直属上级", "项目主管"}]
        doc.copied_to = _json_list(recipients)
        doc.pmc_change_version = int(getattr(doc, "pmc_change_version", 0) or 0) + 1
        _append_request_event(doc, "PMC修改采购申请", doc.workflow_status, doc.workflow_status, details={"changes": changed, "recipients": recipients})
        _save_document(doc)
        _sync_assignments_after_save(doc)
        _notify_procurement_modification(doc, recipients)
        return _summarize_doc(doc)


CONTRACT_REGISTRATION_CLOSED = {"验收通过", "已关闭", "已取消"}
CONTRACT_DELIVERY_REJECT_TARGET = "contract_delivery"


def _current_contract_delivery_step(doc):
    if getattr(doc, "workflow_status", None) not in ACTIVE_STATUSES:
        return None
    step = _current_step(doc)
    return step if step is not None and _clean(getattr(step, "origin", None)) == "contract_delivery" else None


def _reject_contract_delivery(doc, current_step, actor, reason):
    """修复（2026-09-24，审查 R3-53-1，来自 #53）：合同交期确认节点驳回时只驳回本次登记的交期。

    原来会退回申请人或更早的节点，已完成的采购申请回到草稿，而它的 PR、PO 和付款仍在执行。
    现在本轮交期确认节点作废，采购申请保持已完成，恢复原交期和登记前的状态。
    """
    old_status = doc.workflow_status
    for step in list(getattr(doc, "steps", []) or []):
        if _clean(getattr(step, "origin", None)) != "contract_delivery":
            continue
        if step is current_step:
            step.status = STATUS_REJECTED
            step.action_by = actor
            step.acted_on = now_datetime()
            step.note = reason
        elif getattr(step, "status", None) in {STATUS_PENDING, STATUS_WAIT_FLOW, STATUS_WAIT_HANDLE}:
            step.status = STATUS_WITHDRAWN
    registered = next((event for event in reversed(_operation_events(doc)) if event.get("action") == "登记延期合同交期"), {})
    rejected_date = _clean(getattr(doc, "pending_contract_delivery_date", None))
    doc.pending_contract_delivery_date = ""
    doc.business_status = _clean(registered.get("from_status")) or ("采购执行中" if _clean(getattr(doc, "contract_delivery_date", None)) else "合同待登记")
    doc.workflow_status = STATUS_COMPLETED
    doc.current_step_label = ""
    _append_request_event(doc, "驳回合同交期", old_status, doc.workflow_status, reason, {"rejected_contract_delivery_date": rejected_date})


def _procurement_withdraw_blocker(doc):
    """修复（2026-09-24，审查 X1-3）：进入合同交期确认或已有采购付款的采购申请不能撤回。

    原来登记延期交期后单据回到审批中，申请人可以撤回、改明细，再生成重复的 PR / PO。
    """
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT:
        return ""
    if _clean(getattr(doc, "pending_contract_delivery_date", None)) or any(
        _clean(getattr(step, "origin", None)) == "contract_delivery" for step in list(getattr(doc, "steps", []) or [])
    ):
        return "采购申请已进入合同交期确认，不能撤回；如需调整请由确认人驳回本次交期。"
    if _procurement_has_payment_activity(doc):
        return "采购申请已有采购付款，不能撤回。"
    return ""


def _require_contract_registration_access(doc):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT:
        frappe.throw(frappe._("只有采购申请可以登记合同交期。"))
    if getattr(doc, "workflow_status", None) != STATUS_COMPLETED:
        frappe.throw(frappe._("采购审批完成后才能登记合同交期。"))
    if _clean(getattr(doc, "business_status", None)) == "合同交期待确认":
        frappe.throw(frappe._("当前合同交期仍在确认中，不能重复登记。"))
    if _clean(getattr(doc, "business_status", None)) in CONTRACT_REGISTRATION_CLOSED:
        # 修复（2026-09-24，审查 R3-53 / #53）：已验收或已关闭的采购再登记交期会把状态改回采购执行中。
        frappe.throw(frappe._("采购已验收或已关闭，不能再登记合同交期。"))
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
        if _clean(getattr(doc, "source_purchase_order", None)):
            # 修复（2026-09-24，审查 X1-7 / R3-53 J）：PO 付款的到货、验收在采购付款工作台按 PO 登记；
            # 在付款单上登记会把 PO 的数量覆盖到采购申请上，退款也会因为 PO 付款不走金额台账而失败。
            frappe.throw(frappe._("采购订单付款的到货、验收请在采购付款工作台按 PO 登记；退款、核销暂不支持在付款单上办理。"))
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
    source = _sync_procurement_fulfillment_to_source(doc)
    if source:
        created_payment_requests = _auto_push_procurement_payment_plans(source)
        if created_payment_requests:
            source = _load_request(source.name, current=True)
            _append_request_event(
                source,
                "验收后付款计划自动下推",
                _clean(getattr(source, "business_status", None)),
                _clean(getattr(source, "business_status", None)),
                details={"payment_requests": created_payment_requests},
            )
            _save_document(source)
    elif getattr(doc, "request_type", None) == REQUEST_PROCUREMENT:
        created_payment_requests = _auto_push_procurement_payment_plans(doc)
        if created_payment_requests:
            doc = _load_request(doc.name, current=True)
            _append_request_event(
                doc,
                "验收后付款计划自动下推",
                _clean(getattr(doc, "business_status", None)),
                _clean(getattr(doc, "business_status", None)),
                details={"payment_requests": created_payment_requests},
            )
            _save_document(doc)
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
def complete_supplier_refund(name, reason=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        _require_procurement_lifecycle_access(doc, "complete_supplier_refund")
        if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT_PAYMENT:
            frappe.throw(frappe._("只有采购付款单可以确认供应商退款。"))
        # 决定（2026-09-24）：确认退款会把已付金额冲回台账、让采购申请的额度重新可用，
        # 并且要核对银行退款回单，只由财务确认；申请人和采购仍可登记退款中、上传回单。
        if not _is_finance_user():
            frappe.throw(frappe._("只有财务可以确认供应商退款。"))
        note = _bounded_optional_text(reason, "退款说明", 500)
        evidence = _active_request_business_documents(doc.name)
        old_status = _clean(getattr(doc, "business_status", None))
        try:
            updates = transition_business_state(
                doc,
                "complete_supplier_refund",
                payload={"reason": note},
                evidence=evidence,
            )
            balance = approval_amount_ledger.linked_payment_balance(doc.name)
            refund_amount = Decimal(str(balance.get("paid_amount") or 0))
            if refund_amount <= 0:
                raise approval_amount_ledger.ApprovalAmountError("当前付款单没有可退款的已付金额")
            approval_amount_ledger.refund(
                doc.source_request,
                doc.name,
                refund_amount,
                f"refund:{doc.name}:complete",
                note=note,
            )
        except (ProcurementWorkflowError, approval_amount_ledger.ApprovalAmountError) as error:
            frappe.throw(frappe._(str(error)))
        for fieldname, value in updates.items():
            setattr(doc, fieldname, value)
        details = _evidence_audit(evidence)
        details["refund_amount"] = float(refund_amount)
        _append_request_event(
            doc,
            "确认供应商退款",
            old_status,
            doc.business_status,
            note,
            details,
        )
        _save_document(doc)
        _sync_assignments_after_save(doc)
        return _summarize_doc(doc)


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
def get_my_approval_summary():
    if _clean(frappe.session.user) in {"", "Guest"}:
        frappe.throw(frappe._("请先登录。"))
    routes = {
        REQUEST_OVERTIME: {"key": "overtime", "label": "加班", "route": "/approval/overtime"},
        REQUEST_COMP_TIME: {"key": "comp_time", "label": "调休", "route": "/approval/comp-time"},
        REQUEST_LEAVE: {"key": "leave", "label": "请假", "route": "/approval/leave"},
        REQUEST_PROCUREMENT: {"key": "procurement", "label": "采购", "route": "/approval/procurement"},
        REQUEST_DIRECT_PURCHASE: {"key": "direct_purchase", "label": "购买", "route": "/approval/direct-purchase"},
        REQUEST_PROCUREMENT_PAYMENT: {"key": "procurement_payment", "label": "采购付款", "route": "/approval/procurement-payment"},
        REQUEST_EXPENSE_PAYMENT: {"key": "expense_payment", "label": "付款/报销", "route": "/approval/reimbursement"},
        # 修复（2026-09-29，审查 E3）：新的报销单、付款单和出差申请原来不计入待办角标。
        REQUEST_REIMBURSEMENT: {"key": "reimbursement", "label": "报销", "route": "/approval/claim"},
        REQUEST_PAYMENT: {"key": "payment", "label": "付款", "route": "/approval/payment"},
        REQUEST_TRAVEL: {"key": "travel", "label": "出差", "route": "/approval/travel"},
    }
    # 修复（2026-09-29，审查 #8）：只统计当前账号能用的审批类型（功能开关）。
    allowed_types = visible_request_types(list(routes))
    routes = {request_type: value for request_type, value in routes.items() if request_type in allowed_types}
    categories = {
        value["key"]: {**value, "count": 0, "requests": []}
        for value in routes.values()
    }
    if not routes:
        return {"total": 0, "categories": []}
    names = frappe.get_all(
        "OA Approval Request",
        filters={"workflow_status": ["in", list(ACTIVE_STATUSES)], "request_type": ["in", list(routes)]},
        fields=["name"],
        order_by="modified desc",
        limit_page_length=500,
    )
    summary_user = _clean(frappe.session.user)
    global_queue = summary_user == "Administrator" or "System Manager" in set(frappe.get_roles(summary_user))
    for row in names:
        doc = _load_request(_result_name(row))
        if global_queue:
            visible = _can_act_on_current_step(doc, summary_user)
        else:
            step = _current_step(doc)
            visible = bool(step and _matched_approvers(step, summary_user))
        if not visible:
            continue
        item = routes.get(getattr(doc, "request_type", None))
        if not item:
            continue
        bucket = categories[item["key"]]
        bucket["requests"].append(doc.name)
        bucket["count"] += 1
    return {
        "total": sum(item["count"] for item in categories.values()),
        "categories": list(categories.values()),
    }


@frappe.whitelist()
def get_my_notifications(limit=30, unread_only=0):
    """Return the signed-in user's actionable station messages for the app inbox."""
    user = _clean(frappe.session.user)
    if not user or user == "Guest":
        frappe.throw(frappe._("请先登录。"))
    try:
        limit = max(1, min(int(limit or 30), 100))
    except (TypeError, ValueError):
        frappe.throw(frappe._("通知数量格式无效。"))
    filters = {"for_user": user}
    if _to_bool(unread_only):
        filters["read"] = 0
    rows = frappe.get_all(
        "Notification Log",
        filters=filters,
        fields=["name", "subject", "email_content", "creation", "read", "link", "document_type", "document_name", "type"],
        order_by="creation desc",
        limit_page_length=limit,
    )
    unread = frappe.db.count("Notification Log", filters={"for_user": user, "read": 0})
    return {"unread": int(unread or 0), "items": rows}


@frappe.whitelist(methods=["POST"])
def mark_my_notifications_read(names=None, all_notifications=0):
    """Mark only the current user's notification rows as read."""
    user = _clean(frappe.session.user)
    if not user or user == "Guest":
        frappe.throw(frappe._("请先登录。"))
    if _to_bool(all_notifications):
        rows = frappe.get_all("Notification Log", filters={"for_user": user, "read": 0}, fields=["name"], limit_page_length=500)
    else:
        parsed = _parse_json(names, default=names) if isinstance(names, str) else names
        if not isinstance(parsed, (list, tuple, set)):
            parsed = [parsed] if parsed else []
        wanted = {_clean(value) for value in parsed if _clean(value)}
        rows = frappe.get_all("Notification Log", filters={"for_user": user, "name": ["in", list(wanted)]}, fields=["name"], limit_page_length=500) if wanted else []
    for row in rows:
        frappe.db.set_value("Notification Log", row.name, "read", 1, update_modified=False)
    return {"marked": len(rows)}


from rayher_hr_payroll.list_read_scope import read_scope


@frappe.whitelist()
@read_scope
def list_requests(view="mine", limit=50, request_type=None, name=None, offset=0):
    from rayher_hr_payroll.oa_access import (
        _active_identity, _actor_names as access_actors, _sql_current_step,
        _sql_row_scope, _sql_type_scope,
    )
    allowed_types = visible_request_types(REQUEST_TYPES)
    if request_type:
        require_request_type_access(request_type)
        if request_type not in REQUEST_TYPES:
            frappe.throw("不支持的 OA 申请类型。")
        allowed_types = [request_type]
    if not allowed_types:
        return []
    try:
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        frappe.throw("分页参数格式无效。")
    if view not in {"mine", "pending", "all"}:
        frappe.throw("不支持的申请列表视图。")
    user = frappe.session.user
    if not user or user == "Guest":
        return []
    roles = set(frappe.get_roles(user) or [])
    identity = _active_identity(user)
    actors = access_actors(user, identity)
    clauses = [_sql_type_scope(allowed_types)]
    table = "`tabOA Approval Request`"
    if view == "pending":
        clauses.append(
            f"{table}.workflow_status IN ('待审批', '待办理')"
            if _is_oa_override_user(user) else _sql_current_step(actors, pending=True)
        )
    elif view == "all":
        clauses.append(_sql_row_scope(user, roles, identity, actors))
    else:
        own = [f"{table}.owner = {frappe.db.escape(user)}"]
        if identity and identity.get("employee"):
            own.append(f"{table}.employee = {frappe.db.escape(identity['employee'])}")
        clauses.append("(" + " OR ".join(own) + ")")
    if name is not None:
        clauses.append(f"{table}.name = {frappe.db.escape(_report_text(name, '申请单号'))}")
    names = frappe.db.sql(
        f"SELECT {table}.name FROM {table} WHERE "
        + " AND ".join(f"({clause})" for clause in clauses)
        + f" ORDER BY {table}.modified DESC, {table}.name DESC LIMIT %s OFFSET %s",
        (limit, offset), as_dict=True,
    )
    docs = [_load_request(_result_name(row)) for row in names]
    from rayher_hr_payroll.procurement_summary_cache import prepare_summaries
    with prepare_summaries(docs, _calculate_procurement_chain):
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
    all_view = view == "all" and bool(roles & EXPENSE_REPORT_ROLES)
    if all_view:
        filters = {}
    else:
        filters = {"employee": ctx.get("employee")} if ctx.get("employee") else {"owner": frappe.session.user}
    filters["request_type"] = REQUEST_EXPENSE_PAYMENT

    # 修复（2026-09-24，审查 P0-1，来自 #50）：原来"申请人"筛选会覆盖上面的本人范围，
    # 任何员工传 employee=别人 就能看到别人的报销和审批意见。现在只有"全部"视图才按申请人筛选。
    for field, value, label in (
        ("department", department, "部门"),
        ("employee", employee if all_view else None, "申请人"),
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


def _event_stamp(event):
    event = event if isinstance(event, dict) else {}
    return _clean(event.get("timestamp") or event.get("acted_on"))


def _validate_procurement_material_codes(doc, step):
    """PMC may approve only after every purchase line has a formal material code."""
    if doc.request_type != REQUEST_PROCUREMENT:
        return
    if not _clean(getattr(step, "label", None)).startswith("PMC"):
        return
    missing = [
        str(index)
        for index, row in enumerate(getattr(doc, "business_lines", []) or [], start=1)
        if not _clean(getattr(row, "material_code", None))
    ]
    if missing:
        frappe.throw(
            frappe._(
                "第{0}项物料编号尚未补全，PMC不能通过；请先绑定正式物料编号后再提交。"
            ).format("、".join(missing))
        )
    # 修复（2026-09-24，审查 R3-54，来自 #54）：原来只检查填没填，任意字符串都能通过；
    # 现在编号必须是物料库里启用的物料。
    rows = list(getattr(doc, "business_lines", []) or [])
    codes = sorted({_clean(getattr(row, "material_code", None)) for row in rows})
    active = set(frappe.get_all("OA Procurement Material", filters={"name": ["in", codes], "is_active": 1}, pluck="name")) if codes else set()
    unknown = [str(index) for index, row in enumerate(rows, start=1) if _clean(getattr(row, "material_code", None)) not in active]
    if unknown:
        frappe.throw(
            frappe._("第{0}项物料编号不在物料库中或已停用，PMC不能通过；请改为物料库里启用的物料编号。").format("、".join(unknown))
        )


@frappe.whitelist(methods=["POST"])
@attendance_request_transaction
def action_request(name, action="approve", note=None, reject_target=None, expected_step_key=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    # 审批意见和驳回原因一样最多 1000 字（修复 2026-09-29，审查 E5）。
    note = _bounded_optional_text(note, "审批意见", 1000) or None
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        step = _current_step(doc)
        if not step or doc.workflow_status not in ACTIVE_STATUSES:
            frappe.throw(frappe._("\u5f53\u524d\u7533\u8bf7\u4e0d\u5728\u53ef\u5904\u7406\u72b6\u6001\u3002"))
        _require_expected_step(doc, step, expected_step_key)
        matched = _matched_approvers(step)
        is_override = _is_oa_override_user()
        if not _can_act_on_current_step(doc):
            frappe.throw(frappe._("\u5f53\u524d\u8282\u70b9\u4e0d\u5c5e\u4e8e\u4f60\u5904\u7406\u3002"))
        acting_as_override = bool(is_override and not matched)
        actor = _clean(frappe.session.user)
        if (
            doc.request_type == REQUEST_PROCUREMENT
            and _clean(getattr(step, "label", None)) == "采购询价/录入价格"
            and action == "approve"
        ):
            frappe.throw(frappe._("请填写供应商、报价明细并通过询价表单提交价格。"))
        if action == "reject":
            authorized_expense_lines = _with_expense_attachments(
                doc, [_serialize_expense_line(row) for row in getattr(doc, "expense_lines", [])]
            )
            _reject_to_target(doc, step, reject_target, actor, note)
            if doc.request_type == REQUEST_PROCUREMENT_PAYMENT and doc.workflow_status == STATUS_DRAFT:
                _release_procurement_payment_reservation(doc, note)
            if doc.request_type == REQUEST_EXPENSE_PAYMENT and doc.workflow_status == STATUS_DRAFT:
                _release_expense_payment_reservation(doc, note)
            if doc.request_type in {REQUEST_REIMBURSEMENT, REQUEST_PAYMENT} and doc.workflow_status == STATUS_DRAFT:
                from rayher_hr_payroll.api import expense_claim_entry
                expense_claim_entry.release(doc, note)
            _save_document(doc)
            _sync_assignments_after_save(doc)
            if _clean(reject_target) == "applicant":
                events = _operation_events(doc)
                stamp = _event_stamp(events[-1] if events else None)
                notify_rejected_applicant(
                    doc,
                    actor,
                    note,
                    event_key=f"oa-rejection:{doc.name}:{stamp}",
                )
            return _summarize_doc(doc, authorized_expense_lines)
        if action != "approve":
            frappe.throw(frappe._("\u4e0d\u652f\u6301\u7684\u5904\u7406\u52a8\u4f5c\u3002"))
        _validate_procurement_material_codes(doc, step)
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
        if step.mode == "handle" and _unresolved_add_sign_after(doc, step):
            # 旧数据里付款节点后面的加签节点还没处理，不能直接置为已付款（修复 2026-09-29，审查 X1-5）。
            frappe.throw(frappe._("付款节点后面还有未处理的加签节点，请联系管理员处理后再确认付款。"))
        if step.mode == "handle" and doc.request_type == REQUEST_PROCUREMENT_PAYMENT:
            _validate_procurement_payment_release(doc)
        _set_step_action(step, done_status, actor, note)
        _advance_after_step(doc, step)
        contract_delivery_confirmed = _finalize_contract_delivery_if_complete(doc, step)
        if step.mode == "handle" and doc.request_type in {REQUEST_REIMBURSEMENT, REQUEST_PAYMENT}:
            from rayher_hr_payroll.api import expense_claim_entry
            expense_claim_entry.mark_paid(doc, actor, from_status, note, step)
        elif step.mode == "handle" and doc.request_type in {REQUEST_EXPENSE_PAYMENT, REQUEST_PROCUREMENT_PAYMENT}:
            if doc.request_type == REQUEST_PROCUREMENT_PAYMENT:
                _mark_procurement_payment_paid(doc)
                _set_procurement_payment_paid_state(doc)
            else:
                _mark_expense_payment_paid(doc)
                doc.business_status = "已付款"
            doc.workflow_status = STATUS_PAID
            doc.paid_by = actor
            doc.paid_on = step.acted_on or now_datetime()
            _append_request_event(doc, "确认付款", from_status, STATUS_PAID, note)
        _save_document(doc)
        _sync_assignments_after_save(doc)
        if doc.workflow_status in {STATUS_COMPLETED, STATUS_PAID}:
            notify_request_applicant(
                doc,
                "已完成" if doc.workflow_status == STATUS_COMPLETED else "已付款",
                actor=actor,
                note=note,
                event_key=f"oa-result:{doc.name}:{doc.workflow_status}:{_event_stamp(_operation_events(doc)[-1] if _operation_events(doc) else None)}",
            )
        if contract_delivery_confirmed or (
            step.mode == "handle" and doc.request_type == REQUEST_PROCUREMENT_PAYMENT
        ):
            _notify_copied_users(doc)
        return _summarize_doc(doc, authorized_expense_lines)


def _quote_snapshot(doc):
    lines = []
    for row in (getattr(doc, "business_lines", []) or []):
        item = _serialize_business_line(row)
        for field in ("quantity", "unit_price", "amount"):
            item[field] = float(item[field] or 0)
        lines.append(item)
    return {
        "supplier": _clean(getattr(doc, "supplier", None)),
        "amount": float(_money(getattr(doc, "amount", None) or 0)),
        "business_lines": lines,
        "price_revision": int(getattr(doc, "price_revision", 0) or 0),
    }


@frappe.whitelist(methods=["POST"])
def submit_procurement_quote(
    name,
    supplier,
    business_lines,
    payment_plan,
    tax_included=1,
    tax_rate=0,
    delivery_terms=None,
    warranty_terms=None,
    invoice_condition=None,
    change_reason=None,
):
    frappe.throw(frappe._("采购报价已改为从 PR 表格进入价格审批工作台，请勿在 OA 内录价。"))
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        if doc.request_type != REQUEST_PROCUREMENT:
            frappe.throw(frappe._("只有采购申请可以提交价格审批表。"))
        if not _can_submit_procurement_quote(doc):
            frappe.throw(frappe._("当前账号或状态不能提交采购价格审批表。"))
        supplier_name = _bounded_optional_text(supplier, "供应商", 140)
        from rayher_hr_payroll.approval_center import ApprovalCenterError, _lines
        try:
            parsed = _parse_json(business_lines, None)
            lines, total = _lines(parsed)
            revision_no = int(getattr(doc, "price_revision", 0) or 0) + 1
            snapshot, plan_rows = price_approval_snapshot(
                supplier=supplier_name,
                total_amount=total,
                business_lines=[
                    {key: (float(value) if isinstance(value, Decimal) else value) for key, value in row.items()}
                    for row in lines
                ],
                tax_included=tax_included,
                tax_rate=tax_rate,
                delivery_terms=delivery_terms,
                warranty_terms=warranty_terms,
                invoice_condition=invoice_condition,
                payment_plan=payment_plan,
                revision=revision_no,
            )
        except (ApprovalCenterError, ProcurementContractError) as exc:
            frappe.throw(str(exc))
        old_snapshot = _quote_snapshot(doc)
        revision = doc.workflow_status == STATUS_COMPLETED
        reason = _bounded_optional_text(change_reason, "价格修改原因", 1000)
        if revision and not reason:
            frappe.throw(frappe._("修改已批准的商业条件时必须填写修改原因。"))
        doc.supplier = supplier_name
        doc.set("business_lines", lines)
        doc.set("payment_plan", plan_rows)
        doc.amount = total
        doc.approved_amount = None
        doc.price_revision = revision_no
        doc.price_tax_included = snapshot["tax_included"]
        doc.price_tax_rate = snapshot["tax_rate"]
        doc.price_delivery_terms = snapshot["delivery_terms"]
        doc.price_warranty_terms = snapshot["warranty_terms"]
        doc.price_invoice_condition = snapshot["invoice_condition"]
        doc.price_snapshot = json.dumps(snapshot, ensure_ascii=False)
        doc.price_submitted_by = _clean(frappe.session.user)
        doc.price_submitted_on = now_datetime()
        doc.price_approved_by = ""
        doc.price_approved_on = None
        doc.contract_status = ""
        doc.contract_snapshot = ""
        doc.contract_draft_content = ""
        doc.contract_reviewed_by = ""
        doc.contract_reviewed_on = None
        doc.contract_sealed_by = ""
        doc.contract_sealed_on = None
        actor = _clean(frappe.session.user)
        if revision:
            vice = resolve_role("vice_manager")
            next_index = max([int(row.step_index or 0) for row in doc.steps] or [0]) + 1
            doc.append("steps", {
                "step_index": next_index,
                "step_key": str(uuid4()),
                "origin": "base",
                "label": "价格审批：副总经理：" + _clean(vice.get("employee_name")),
                "mode": "approve",
                "approvers": _json_list([vice["user"]]),
                "status": STATUS_PENDING,
                "approved_by": _json_list([]),
            })
            doc.workflow_status = STATUS_PENDING
            doc.current_step_index = next_index
            doc.current_step_label = doc.steps[-1].label
        else:
            step = _current_step(doc)
            _set_step_action(step, STATUS_HANDLED, actor, reason)
            _advance_after_step(doc, step)
        doc.business_status = "待价格审批"
        _append_request_event(
            doc,
            "变更价格审批表" if revision else "提交价格审批表",
            _clean(getattr(doc, "business_status", None)) if revision else "需求已批准/待询价",
            "待价格审批",
            reason,
            {"before": old_snapshot, "after": snapshot},
        )
        _save_document(doc)
        _sync_assignments_after_save(doc)
        return _summarize_doc(doc)


def _require_procurement_contract_actor(doc, capability, message):
    if getattr(doc, "request_type", None) != REQUEST_PROCUREMENT or not capability(doc):
        frappe.throw(frappe._(message))


@frappe.whitelist(methods=["POST"])
def save_procurement_contract_information(
    name,
    supplier_legal_name,
    credit_code,
    supplier_address,
    contract_contact,
    contract_bank_name,
    contract_bank_account,
    contract_entity,
    contract_template,
    seal_user,
    contract_delivery_date,
):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        _require_procurement_contract_actor(doc, _can_edit_procurement_contract, "只有采购经办人可在价格批准后补充合同信息。")
        values = {
            "supplier_legal_name": supplier_legal_name,
            "credit_code": credit_code,
            "supplier_address": supplier_address,
            "contract_contact": contract_contact,
            "contract_bank_name": contract_bank_name,
            "contract_bank_account": contract_bank_account,
            "contract_entity": contract_entity,
            "contract_template": contract_template,
            "seal_user": seal_user,
            "contract_delivery_date": contract_delivery_date,
        }
        user_name = _bounded_optional_text(seal_user, "用印账号", 140)
        if not frappe.db.exists("User", {"name": user_name, "enabled": 1}):
            frappe.throw(frappe._("用印账号不存在或未启用。"))
        try:
            version = int(getattr(doc, "contract_version", 0) or 0) + 1
            snapshot = contract_snapshot(values, getattr(doc, "price_snapshot", None), version)
            draft = render_contract_draft(snapshot)
        except ProcurementContractError as exc:
            frappe.throw(str(exc))
        old_status = _clean(getattr(doc, "business_status", None))
        doc.contract_version = version
        doc.contract_supplier_legal_name = snapshot["supplier_legal_name"]
        doc.contract_credit_code = snapshot["credit_code"]
        doc.contract_supplier_address = snapshot["supplier_address"]
        doc.contract_contact = snapshot["contract_contact"]
        doc.contract_bank_name = snapshot["contract_bank_name"]
        doc.contract_bank_account = snapshot["contract_bank_account"]
        doc.contract_entity = snapshot["contract_entity"]
        doc.contract_template = snapshot["contract_template"]
        doc.contract_seal_user = snapshot["seal_user"]
        doc.contract_delivery_date = snapshot["contract_delivery_date"]
        doc.contract_snapshot = json.dumps(snapshot, ensure_ascii=False)
        doc.contract_draft_content = draft
        doc.contract_status = "草稿待复核"
        doc.business_status = "合同草稿待复核"
        _append_request_event(doc, "生成电子合同草稿", old_status, doc.business_status, details={"contract_version": version, "price_fingerprint": snapshot["price_fingerprint"]})
        _save_document(doc)
        return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def review_procurement_contract(name, note=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        _require_procurement_contract_actor(doc, _can_review_procurement_contract, "只有采购经办人可复核电子合同草稿。")
        old_status = doc.business_status
        doc.contract_status = "待电子用印"
        doc.business_status = "待电子用印"
        doc.contract_reviewed_by = _clean(frappe.session.user)
        doc.contract_reviewed_on = now_datetime()
        _append_request_event(doc, "复核电子合同", old_status, doc.business_status, _bounded_optional_text(note, "复核备注", 500))
        _save_document(doc)
        return _summarize_doc(doc)


def _payment_plan_trigger_ready(source, row):
    """Return whether a plan row can be turned into an approval request now."""
    trigger = _clean(getattr(row, "trigger_condition", None))
    if "验收" in trigger and _clean(getattr(source, "inspection_status", None)) != "验收通过":
        return False
    if "到货" in trigger and _clean(getattr(source, "arrival_status", None)) not in {"全部到货", "关闭未交数量"}:
        return False
    return True


def _auto_push_procurement_payment_plans(source):
    """Create and submit eligible payment requests from a sealed contract's plan rows."""
    if getattr(source, "request_type", None) != REQUEST_PROCUREMENT or getattr(source, "contract_status", None) != "已生效":
        return []
    # New contracts are paid from the PO directly. Keep this legacy path only
    # for procurement requests that predate PO-owned payment plans.
    if frappe.db.exists("OA Purchase Order Line", {"source_request": source.name}):
        return []
    from rayher_hr_payroll.approval_center import ApprovalCenterError, save_draft

    created = []
    source_lines = [
        {
            key: getattr(line, key, None) or ""
            for key in ("item_name", "specification", "quantity", "unit", "unit_price", "remarks")
        }
        for line in (getattr(source, "business_lines", []) or [])
    ]
    for row in (getattr(source, "payment_plan", []) or []):
        if _clean(getattr(row, "status", None)) != "待下推" or not _payment_plan_trigger_ready(source, row):
            continue
        row_name = _clean(getattr(row, "name", None))
        if not row_name or frappe.db.exists(
            "OA Approval Request",
            {"request_type": REQUEST_PROCUREMENT_PAYMENT, "source_payment_plan_row": row_name, "workflow_status": ["not in", [STATUS_REJECTED]]},
        ):
            continue
        payload = {
            "subject": f"{_clean(getattr(source, 'name', None))} · {_clean(getattr(row, 'installment_name', None))}",
            "reason": "由已生效采购合同付款计划自动下推",
            "asset_nature": "非固定资产",
            "fixed_asset_category": "",
            "source_request": source.name,
            "source_payment_plan_row": row_name,
            "business_lines": source_lines,
            "supplier": _clean(getattr(source, "supplier", None)),
            "payment_stage": _clean(getattr(row, "payment_stage", None)),
            "prepayment_percentage": float(getattr(row, "percentage", 0) or 0) if _clean(getattr(row, "payment_stage", None)) == "预付款" else 0,
            "expected_arrival_date": _clean(getattr(row, "planned_date", None)),
            "prepayment_risk_note": "合同付款计划已审批" if float(getattr(row, "percentage", 0) or 0) == 100 else "",
        }
        try:
            payment_doc = save_draft(REQUEST_PROCUREMENT_PAYMENT, payload)
            _submit_draft(payment_doc)
            _reserve_procurement_payment(payment_doc, workflow=True)
            _save_document(payment_doc)
            _sync_assignments_after_save(payment_doc)
            created.append(payment_doc.name)
        except ApprovalCenterError:
            raise
    return created


@frappe.whitelist(methods=["POST"])
def seal_procurement_contract(name, note=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        _require_procurement_contract_actor(doc, _can_seal_procurement_contract, "当前账号不是该合同配置的用印账号。")
        if not _clean(getattr(doc, "contract_draft_content", None)):
            frappe.throw(frappe._("电子合同草稿不存在。"))
        old_status = doc.business_status
        for row in (getattr(doc, "payment_plan", []) or []):
            row.status = "待下推"
            row.payment_request = ""
            row.pushed_by = ""
            row.pushed_on = None
            row.paid_amount = 0
        doc.contract_status = "已生效"
        doc.business_status = "付款计划已生成"
        doc.contract_sealed_by = _clean(frappe.session.user)
        doc.contract_sealed_on = now_datetime()
        _append_request_event(doc, "电子用印并生成付款计划", old_status, doc.business_status, _bounded_optional_text(note, "用印备注", 500), {"payment_plan_count": len(getattr(doc, "payment_plan", []) or [])})
        _save_document(doc)
        created_payment_requests = _auto_push_procurement_payment_plans(doc)
        if created_payment_requests:
            # The payment request reserves its source row in a fresh document
            # instance; reload before appending the audit event so that save
            # does not restore stale "待下推" row values.
            doc = _load_request(request_name, current=True)
            _append_request_event(
                doc,
                "付款计划自动下推",
                "付款计划已生成",
                "付款计划已生成",
                details={"payment_requests": created_payment_requests},
            )
            _save_document(doc)
        else:
            created_payment_requests = []
        return _summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def verify_request_invoices(name, note=None):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    _require_finance_user()
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        if doc.request_type != REQUEST_EXPENSE_PAYMENT:
            frappe.throw(frappe._("只有费用付款/报销单可以核验发票。"))
        if getattr(doc, "invoice_followup_status", None) != INVOICE_FOLLOWUP_RECEIVED:
            frappe.throw(frappe._("只有已收票状态可以确认核验。"))
        summary = invoice_service.request_invoice_summary(doc, current=True)
        if not int(summary.get("invoice_count") or 0):
            frappe.throw(frappe._("当前单据没有可核验发票。"))
        records = invoice_service._request_invoice_records(doc.name, current=True)
        blockers = invoice_service.submission_blockers(records, "")
        if blockers:
            frappe.throw(frappe._("；".join(blockers)))
        old_status = doc.invoice_followup_status
        doc.invoice_followup_status = INVOICE_FOLLOWUP_VERIFIED
        _append_request_event(doc, "核验发票", old_status, INVOICE_FOLLOWUP_VERIFIED, note)
        _save_document(doc)
        return _summarize_doc(doc)


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
        _mark_expense_payment_paid(doc)
        doc.workflow_status = STATUS_PAID
        doc.business_status = "已付款"
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
        applicant_employee=getattr(doc, "employee", None),
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
        applicant_employee=getattr(doc, "employee", None),
    )
    doc.copied_to = _json_list(route.get("copied_to") or [])
    _append_steps(doc, route["steps"])
    doc.workflow_status = STATUS_DRAFT
    doc.business_status = ""
    doc.current_step_index = 0
    doc.current_step_label = ""
    _append_request_event(doc, "撤回申请", old_status, STATUS_DRAFT, note, details)
    return doc


@frappe.whitelist(methods=["POST"])
def push_invoices_to_request(invoice_names, payment_info=None):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    # 新流程下发票从发票夹进报销单，不再下推生成旧的费用付款申请。
    _require_legacy_expense_entry()
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
            invoice_handling_mode=INVOICE_MODE_AVAILABLE,
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
@attendance_request_transaction
def withdraw_request(name, note=None):
    request_name = _bounded_optional_text(name, "申请单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        invoice_service._request_permission(doc, "edit", current=True)
        if doc.workflow_status == STATUS_PAID:
            frappe.throw(frappe._("已付款单据必须先由财务撤回付款。"))
        if doc.request_type in {REQUEST_DIRECT_PURCHASE, REQUEST_TRAVEL} and doc.workflow_status == STATUS_COMPLETED:
            frappe.throw(frappe._("已通过的申请不能撤回。"))
        # 修复（2026-09-29，审查 R3-56-1，来自 #56）：已批准的请假、加班、调休原来可以随时撤回：
        # 假期过后撤回，年假、调休余额退回，那天也不会被扣，事假还会把月度工时上限抬回去。
        # 决定（2026-09-29）：批准后暂时不能撤回，需要取消的请联系人事（销假流程以后再做）。
        if approved_attendance(doc):
            frappe.throw(frappe._("已批准的请假、加班、调休暂不能撤回，需要取消请联系人事。"))
        if doc.request_type == REQUEST_PROCUREMENT:
            if doc.workflow_status not in ACTIVE_STATUSES:
                frappe.throw(frappe._("采购申请仅可在需求审批期间撤回；进入询价、价格审批或采购执行后不可撤回。"))
            blocker = _procurement_withdraw_blocker(doc)
            if blocker:
                frappe.throw(frappe._(blocker))
            _reset_request_to_draft(doc, note)
            doc.business_status = STATUS_WITHDRAWN
            _release_procurement_payment_reservation(doc, note)
            _save_document(doc)
            _sync_assignments_after_save(doc)
            return _summarize_doc(doc)
        if doc.workflow_status == STATUS_DRAFT:
            return _summarize_doc(doc)
        _reset_request_to_draft(doc, note)
        _release_procurement_payment_reservation(doc, note)
        _release_expense_payment_reservation(doc, note)
        if doc.request_type in {REQUEST_REIMBURSEMENT, REQUEST_PAYMENT}:
            from rayher_hr_payroll.api import expense_claim_entry
            expense_claim_entry.release(doc, note)
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
        _reverse_expense_payment_paid(doc, note)
        doc.workflow_status = STATUS_COMPLETED
        doc.business_status = "待付款"
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
            if doc.request_type in {REQUEST_REIMBURSEMENT, REQUEST_PAYMENT}:
                frappe.throw(frappe._("报销单、付款单的发票请在单据中移除。"))
            if doc.workflow_status == STATUS_PAID:
                frappe.throw(frappe._("\u5df2\u4ed8\u6b3e\u5355\u636e\u5fc5\u987b\u5148\u7531\u8d22\u52a1\u64a4\u56de\u4ed8\u6b3e\u3002"))
            if doc.workflow_status != STATUS_DRAFT:
                _reset_request_to_draft(doc, note)
                # 修复（2026-09-22）：退回草稿时同时释放对购买申请额度的占用，原来会一直占着。
                _release_expense_payment_reservation(doc, note)
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
    if _current_contract_delivery_step(doc) is not None:
        return [{"target": CONTRACT_DELIVERY_REJECT_TARGET, "label": "驳回本次合同交期（恢复原交期）"}]
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
    if _current_contract_delivery_step(doc) is not None:
        # 页面可能仍按"退回申请人"提交；交期确认节点一律只驳回本次交期。
        return _reject_contract_delivery(doc, current_step, actor, reason)
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


def _is_contract_delivery_step(step):
    return step is not None and _clean(getattr(step, "origin", None)) == "contract_delivery"


def _applicant_users(doc):
    """申请人本人的账号：单据创建人和申请人员工档案关联的账号。"""
    users = {_clean(getattr(doc, "owner", None))}
    employee = _clean(getattr(doc, "employee", None))
    if employee:
        users.add(_clean(frappe.db.get_value("Employee", employee, "user_id")))
    return {user for user in users if user}


def _unresolved_add_sign_after(doc, step):
    """付款节点之后还没处理的加签节点（旧数据里的"后加签"）。"""
    index = int(getattr(step, "step_index", 0) or 0)
    unresolved = {STATUS_PENDING, STATUS_WAIT_HANDLE, STATUS_WAIT_FLOW}
    return [
        row for row in (getattr(doc, "steps", []) or [])
        if int(getattr(row, "step_index", 0) or 0) > index
        and _clean(getattr(row, "origin", None)) == "add_sign"
        and getattr(row, "status", None) in unresolved
    ]


STALE_STEP_MESSAGE = "这张单据已经变化，现在在「{0}」这一步，已为你刷新，请看过后再操作。"


def _require_expected_step(doc, step, expected_step_key):
    """审批只作用在页面上看到的那一步（修复 2026-09-29，审查 #10，决定 D10）。

    原来接口只收单号，按服务端当前节点处理：双击、或同一人占相邻两个节点（包括管理员放行账号）时
    第二次点击会把下一步也批掉，最坏连付款一起确认；开着旧页面还会在没看到驳回原因的情况下再批一次。
    从网页和 API 来的请求必须带 expected_step_key；服务器内部代码（维护脚本、测试）直接调用时不要求。
    """
    expected = _clean(expected_step_key)
    current = _clean(getattr(step, "step_key", None))
    if not expected:
        if getattr(getattr(frappe, "local", None), "request", None) is None:
            return
        frappe.throw(frappe._("页面版本过旧，请刷新后再操作。"))
    if expected != current:
        label = _clean(getattr(step, "label", None)) or _clean(getattr(doc, "current_step_label", None)) or "—"
        frappe.throw(frappe._(STALE_STEP_MESSAGE).format(label))


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
    # 修复（2026-09-29，审查 E1，决定 D9）：合同交期确认阶段的加签节点不走交期确认的规则，
    # 在加签节点驳回会把执行中的采购申请退回草稿，最后一步通过时新交期也不生效。
    if _is_contract_delivery_step(current_step):
        frappe.throw(frappe._("合同交期确认阶段不能加签。"))
    # 修复（2026-09-29，审查 X1-5，决定 D6）：付款（经办）节点确认付款时单据直接变成已付款，
    # 排在它后面的加签节点再也没人处理。付款节点只能前加签：被加签人先批，批完才能付款。
    if position == "after" and getattr(current_step, "mode", None) == "handle":
        frappe.throw(frappe._("付款节点只能在前面加签：被加签人审批后才能确认付款。"))
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
        # 加签节点都是审批节点（mode=approve），状态也应是待审批；原来前加签到付款节点时写成了待办理。
        new_status = STATUS_PENDING
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
def list_approval_people(query="", limit=20, name=None):
    query = _bounded_optional_text(query, "Search", 100)
    try:
        limit = max(1, min(int(limit or 20), 50))
    except (TypeError, ValueError):
        frappe.throw(frappe._("Search limit is invalid."))
    # 修复（2026-09-29，审查 #7，决定 D8）：原来任何登录用户都能用它列出全公司账号。
    # 现在只有这张单据当前节点的审批人能查，并且只列在职员工的账号。
    request_name = _bounded_optional_text(name, "Request", 140)
    if not request_name:
        frappe.throw(frappe._("请从待审批的单据上加签。"))
    doc = _load_request(request_name)
    require_request_type_access(doc.request_type)
    if not _can_act_on_current_step(doc):
        frappe.throw(frappe._("Only the current approver may add an approver."))
    active_users = sorted({
        _clean(user) for user in frappe.get_all(
            "Employee", filters={"status": "Active", "user_id": ["is", "set"]}, pluck="user_id",
        ) if _clean(user)
    } - _applicant_users(doc))
    filters = {"enabled": 1, "user_type": "System User", "name": ["in", active_users or ["__none__"]]}
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
@attendance_request_transaction
def add_sign_request(name, approver, position, opinion, expected_step_key=None):
    request_name = _bounded_optional_text(name, "Request", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _load_request(request_name, current=True)
        require_request_type_access(doc.request_type)
        step = _current_step(doc)
        if not step or doc.workflow_status not in ACTIVE_STATUSES:
            frappe.throw(frappe._("The request is not at an active approval step."))
        _require_expected_step(doc, step, expected_step_key)
        if not _matched_approvers(step) or not _can_act_on_current_step(doc):
            frappe.throw(frappe._("Only the current approver may add an approver."))
        resolved = _resolve_add_sign_approver(approver)
        actor_names = _actor_names()
        if resolved in actor_names:
            frappe.throw(frappe._("You cannot add yourself as an approver."))
        # 修复（2026-09-29，审查 #6）：不能把申请人本人加成审批人。
        if resolved in _applicant_users(doc):
            frappe.throw(frappe._("不能把申请人本人加为审批人。"))
        actor = _clean(getattr(frappe.session, "user", None)) or sorted(actor_names)[0]
        # 修复（2026-09-29，审查 #4）：前加签后当前节点换成被加签人，操作人不再有读附件的权限，
        # 保存后再取费用明细会报"无权访问"并整体回滚。和 action_request 一样，先取好再改。
        authorized_expense_lines = _with_expense_attachments(
            doc, [_serialize_expense_line(row) for row in getattr(doc, "expense_lines", [])]
        )
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
        return _summarize_doc(doc, authorized_expense_lines)


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
        if request_type == REQUEST_PROCUREMENT_PAYMENT:
            values = _parse_json(payload, {}) or {}
            if not values.get("source_purchase_order") or not values.get("source_po_payment_plan_row"):
                frappe.throw(frappe._("采购付款必须由 PO 付款计划下推生成，不能单独新建。"))
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
def list_procurement_applicants():
    require_request_type_access(REQUEST_PROCUREMENT)
    context = _employee_context()
    if not context.get("employee"):
        return []
    if _can_submit_procurement_for_others():
        rows = frappe.get_all(
            "Employee",
            filters={"status": "Active"},
            fields=["name", "employee_name", "department", "user_id"],
            order_by="employee_name asc, name asc",
            limit_page_length=0,
        )
    else:
        rows = [{
            "name": context["employee"],
            "employee_name": context["employee_name"],
            "department": context["department"],
            "user_id": context["applicant_user"],
        }]
    return [{
        "name": row.get("name"),
        "employee_name": row.get("employee_name") or row.get("name"),
        "department": _display_department(row.get("department")),
        "user": row.get("user_id") or "",
        "has_account": 1 if row.get("user_id") else 0,
    } for row in rows]


@frappe.whitelist()
def list_procurement_users():
    require_request_type_access(REQUEST_PROCUREMENT)
    try:
        purchaser = resolve_role("procurement_manager")
    except ApprovalRoleResolutionError as exc:
        frappe.throw(str(exc))
    return [{
        "name": purchaser["user"],
        "full_name": purchaser["employee_name"] or purchaser["role_label"],
        "employee": purchaser["employee"],
        "designation": purchaser["role_label"],
        "is_default": 1,
    }]


@frappe.whitelist()
def list_procurement_payment_sources(limit=500):
    from rayher_hr_payroll.approval_center import ApprovalCenterError, procurement_payment_source_options

    try:
        return procurement_payment_source_options(limit=limit)
    except ApprovalCenterError as exc:
        frappe.throw(str(exc))


@frappe.whitelist()
def list_expense_payment_sources(limit=500):
    require_request_type_access(REQUEST_EXPENSE_PAYMENT)
    try:
        limit = max(1, min(int(limit or 500), 500))
    except (TypeError, ValueError):
        frappe.throw(frappe._("购买申请来源数量格式无效。"))
    user = _clean(frappe.session.user)
    roles = set(frappe.get_roles(user) or [])
    filters = {"request_type": REQUEST_DIRECT_PURCHASE, "workflow_status": STATUS_COMPLETED}
    names = frappe.get_all(
        "OA Approval Request", filters=filters, pluck="name",
        order_by="modified desc", limit_page_length=limit,
    )
    result = []
    for name in names:
        source = _load_request(name)
        if user not in {"Administrator", "admin@staff.example.invalid"} and not roles & {"System Manager", "Accounts User"}:
            if user not in {_clean(source.owner), _clean(getattr(source, "purchaser_user", None))}:
                employee_user = _clean(frappe.db.get_value("Employee", source.employee, "user_id")) if source.employee else ""
                if user != employee_user:
                    continue
        try:
            balance = approval_amount_ledger.source_balance(source)
        except approval_amount_ledger.ApprovalAmountError:
            continue
        if balance["available_amount"] <= 0:
            continue
        result.append({
            "name": source.name,
            "subject": source.subject,
            "employee_name": source.employee_name,
            "department": _display_department(source.department),
            "approved_amount": float(balance["approved_amount"]),
            "paid_amount": float(balance["paid_amount"]),
            "available_amount": float(balance["available_amount"]),
        })
    return result


@frappe.whitelist()
def get_approval_center_dashboard(kind, limit=200):
    from rayher_hr_payroll.approval_center import ApprovalCenterError, dashboard

    try:
        result = dashboard(kind, limit=limit)
        rows = result.get("rows") or []
        user = _clean(frappe.session.user).lower()
        roles = set(frappe.get_roles(user) or [])
        can_view_financial = user in position_users("procurement_manager", "vice_manager", "general_manager") or bool(roles & {"System Manager", "Accounts User", "Purchase User", "Purchase Manager"})
        result["can_view_financial"] = can_view_financial
        if kind == "request":
            request_names = [row["name"] for row in rows if row.get("request_type") == REQUEST_PROCUREMENT]
            pr_lines = frappe.get_all("OA Procurement Request Line", filters={"source_request": ["in", request_names]}, fields=["parent", "source_request"], limit_page_length=0) if request_names else []
            price_lines = frappe.get_all("OA Price Approval Line", filters={"source_request": ["in", request_names]}, fields=["parent", "source_request"], limit_page_length=0) if request_names else []
            po_lines = frappe.get_all("OA Purchase Order Line", filters={"source_request": ["in", request_names]}, fields=["parent", "source_request", "amount"], limit_page_length=0) if request_names else []
            po_names = sorted({item.parent for item in po_lines})
            pos = {item.name: item for item in frappe.get_all("OA Purchase Order", filters={"name": ["in", po_names]}, fields=["name", "status", "supplier", "total_amount", "paid_amount", "payment_status"], limit_page_length=0)} if po_names else {}
            payments = frappe.get_list("OA Approval Request", filters={"request_type": REQUEST_PROCUREMENT_PAYMENT, "source_purchase_order": ["in", po_names]}, fields=["name", "source_purchase_order"], limit_page_length=500) if po_names and can_view_financial else []
            for row in rows:
                name = row["name"]
                related_lines = [item for item in po_lines if item.source_request == name]
                related_pos = sorted({item.parent for item in related_lines})
                allocated = sum(float(item.amount or 0) for item in related_lines)
                paid = sum((float(pos[po].paid_amount or 0) * sum(float(item.amount or 0) for item in related_lines if item.parent == po) / float(pos[po].total_amount or 1)) for po in related_pos if po in pos)
                row.update({
                    "linked_prs": sorted({item.parent for item in pr_lines if item.source_request == name}),
                    "linked_price_approvals": sorted({item.parent for item in price_lines if item.source_request == name}) if can_view_financial else [],
                    "linked_pos": related_pos,
                    "linked_payments": sorted({item.name for item in payments if item.source_purchase_order in related_pos}),
                    "po_amount": allocated if can_view_financial else 0,
                    "po_paid_amount": paid if can_view_financial else 0,
                    "po_unpaid_amount": max(allocated - paid, 0) if can_view_financial else 0,
                    "po_statuses": sorted({pos[po].status for po in related_pos if po in pos}),
                })
        elif kind == "payment":
            po_names = sorted({row.get("source_purchase_order") for row in rows if row.get("source_purchase_order")})
            po_lines = frappe.get_all("OA Purchase Order Line", filters={"parent": ["in", po_names]}, fields=["parent", "source_request", "source_pr"], limit_page_length=0) if po_names else []
            pos = {item.name: item for item in frappe.get_all("OA Purchase Order", filters={"name": ["in", po_names]}, fields=["name", "status", "supplier", "total_amount", "paid_amount", "payment_status"], limit_page_length=0)} if po_names else {}
            for row in rows:
                po_name = row.get("source_purchase_order")
                po = pos.get(po_name)
                related = [item for item in po_lines if item.parent == po_name]
                row.update({
                    "linked_requests": sorted({item.source_request for item in related if item.source_request}),
                    "linked_prs": sorted({item.source_pr for item in related if item.source_pr}),
                    "po_status": po.status if po else "", "supplier": po.supplier if po else row.get("supplier", ""),
                    "po_total_amount": float(po.total_amount or 0) if po else 0,
                    "po_paid_amount": float(po.paid_amount or 0) if po else 0,
                    "po_unpaid_amount": max(float(po.total_amount or 0) - float(po.paid_amount or 0), 0) if po else 0,
                })
        return result
    except ApprovalCenterError as exc:
        frappe.throw(str(exc))


@frappe.whitelist(methods=["POST"])
def attach_approval_business_document(request, document_type, file_ref):
    from rayher_hr_payroll.business_documents import BusinessDocumentError, attach

    try:
        return _approval_center_result(attach(request, document_type, file_ref))
    except BusinessDocumentError as exc:
        frappe.throw(str(exc))


@frappe.whitelist(methods=["POST"])
def remove_approval_business_document(name, reason=None):
    from rayher_hr_payroll.business_documents import BusinessDocumentError, remove

    try:
        return remove(name, reason)
    except BusinessDocumentError as exc:
        frappe.throw(str(exc))


@frappe.whitelist()
def list_approval_business_documents(request):
    from rayher_hr_payroll.business_documents import BusinessDocumentError, list_documents

    try:
        return list_documents(request)
    except BusinessDocumentError as exc:
        frappe.throw(str(exc))


@frappe.whitelist()
def get_attendance_options(request_type, from_date=None, to_date=None):
    from rayher_hr_payroll.attendance_requests import (
        LEAVE_TYPES, active_rows, date_range, day_limits, work_dates_for_range, get_balance,
    )
    if request_type not in ATTENDANCE_TYPES:
        frappe.throw("不支持的申请类型")
    require_request_type_access(request_type)
    try:
        ctx = _leave_employee_context()
    except ApprovalRouteError as exc:
        frappe.throw(str(exc).replace("请假申请", request_type))
    from_date = None if from_date in (None, "", "null", "undefined") else from_date
    to_date = None if to_date in (None, "", "null", "undefined") else to_date
    days = []
    if from_date and to_date:
        try:
            dates = date_range(from_date, to_date) if request_type == REQUEST_OVERTIME else sorted(work_dates_for_range(ctx["employee"], from_date, to_date))
            # 每天还能填多少小时，以及这天已被哪张申请占用（2026-09-29，申请表按这个灰掉冲突的日子）。
            limits = day_limits(request_type, dates, active_rows(ctx["employee"], from_date, to_date))
            days = [{"work_date": d.isoformat(), "hours": min(8, limits[d]["max_hours"]),
                     "max_hours": limits[d]["max_hours"], "conflict": limits[d]["conflict"]} for d in dates]
        except ValueError as exc:
            frappe.throw(str(exc))
    from rayher_hr_payroll.annual_leave import get_annual_balance
    return {"days": days, "balance": get_balance(ctx["employee"]),
            "annual_balance": get_annual_balance(ctx["employee"]), "leave_types": LEAVE_TYPES}
