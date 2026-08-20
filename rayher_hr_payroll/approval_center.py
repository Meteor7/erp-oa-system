from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe

from rayher_hr_payroll.oa_approval import OTHER_ASSET, PRODUCTION_ASSET, REQUEST_EXPENSE_PAYMENT
from rayher_hr_payroll.procurement_workflow import (
    NON_PROJECT_ALLOCATION_TYPES,
    ProcurementWorkflowError,
    derive_payment_stage,
    derive_prepayment_overdue,
    validate_procurement_submission,
)
from rayher_hr_payroll.oa_role_resolver import ApprovalRoleResolutionError, resolve_role
from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
)


CENT = Decimal("0.01")
QUANTITY_UNIT = Decimal("0.0001")
DRAFT_STATUS = "草稿"
DRAFT_TYPES = (REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE, REQUEST_PROCUREMENT_PAYMENT)
REQUEST_DASHBOARD_TYPES = (REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE)
PAYMENT_DASHBOARD_TYPES = (REQUEST_PROCUREMENT_PAYMENT, REQUEST_EXPENSE_PAYMENT)
ASSET_NATURES = {"固定资产", "非固定资产"}
FIXED_ASSET_CATEGORIES = {
    "办公家具、工具及器具",
    "电子设备、研发专用设备、仪器仪表",
    "生产设备、生产工具及器具",
}
SERVER_FIELDS = {
    "workflow_status", "approved_amount", "amount", "steps", "owner", "employee",
    "employee_name", "department", "company", "copied_to", "current_step_index",
    "current_step_label", "currency", "paid_by", "paid_on", "operation_log",
    "approved_amount_snapshot", "source_modified", "payment_source_kind",
    "business_status", "project_owner", "project_owner_name", "contract_delivery_date",
    "pending_contract_delivery_date", "delivery_change_reason", "arrival_status",
    "inspection_status", "prepayment_writeoff_status", "ordered_quantity",
    "received_quantity", "arrival_date", "inspection_failure_reason",
    "exception_direction", "followup_status",
}
ALLOWED_PAYLOAD_FIELDS = {
    "subject", "reason", "urgency", "asset_nature", "fixed_asset_category",
    "business_lines", "source_request", "procurement_scope", "expected_delivery_date",
    "project", "non_project_allocation_type", "non_project_cost_center",
    "non_project_department", "purchaser_user", "contract_delivery_date",
    "delivery_change_reason", "purchase_method", "supplier", "payment_stage",
    "prepayment_percentage", "has_balance_payment", "expected_arrival_date",
    "prepayment_risk_note", "applicant_employee",
}


class ApprovalCenterError(ValueError):
    pass


def _get(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    getter = getattr(value, "get", None)
    if callable(getter):
        result = getter(key)
        return default if result is None else result
    return getattr(value, key, default)


def _name(value):
    return str(value if isinstance(value, str) else _get(value, "name") or "").strip()


def _text(value, label, limit, *, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApprovalCenterError(f"{label}格式无效")
    result = value.strip()
    if "\x00" in result or len(result) > limit or (required and not result):
        raise ApprovalCenterError(f"{label}格式无效")
    return result


def _decimal(value, label, *, positive=False, places=CENT):
    if isinstance(value, bool):
        raise ApprovalCenterError(f"{label}格式无效")
    try:
        result = Decimal(str(value)).quantize(places, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ApprovalCenterError(f"{label}格式无效")
    if not result.is_finite() or (positive and result <= 0) or result < 0:
        raise ApprovalCenterError(f"{label}格式无效")
    return result


def _payload(value):
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 128 * 1024:
            raise ApprovalCenterError("草稿内容不能超过128KB")
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            raise ApprovalCenterError("草稿内容格式无效")
    if not isinstance(value, dict):
        raise ApprovalCenterError("草稿内容格式无效")
    forbidden = sorted(SERVER_FIELDS & set(value))
    if forbidden:
        raise ApprovalCenterError("禁止客户端写入服务端字段：" + "、".join(forbidden))
    unknown = sorted(set(value) - ALLOWED_PAYLOAD_FIELDS)
    if unknown:
        raise ApprovalCenterError("草稿包含未知字段：" + "、".join(unknown))
    return value


def _lines(values):
    if not isinstance(values, list) or not values or len(values) > 100:
        raise ApprovalCenterError("采购明细必须为1到100行")
    result = []
    total = Decimal("0.00")
    allowed = {"item_name", "specification", "quantity", "unit", "unit_price", "remarks"}
    for index, row in enumerate(values, 1):
        if not isinstance(row, dict) or set(row) - allowed:
            raise ApprovalCenterError(f"第{index}行采购明细格式无效")
        quantity = _decimal(row.get("quantity"), f"第{index}行数量", positive=True, places=QUANTITY_UNIT)
        unit_price = _decimal(row.get("unit_price"), f"第{index}行单价")
        amount = (quantity * unit_price).quantize(CENT, rounding=ROUND_HALF_UP)
        item = {
            "item_name": _text(row.get("item_name"), f"第{index}行物品名称", 140, required=True),
            "specification": _text(row.get("specification"), f"第{index}行规格", 140),
            "quantity": quantity,
            "unit": _text(row.get("unit"), f"第{index}行单位", 40, required=True),
            "unit_price": unit_price,
            "amount": amount,
            "remarks": _text(row.get("remarks"), f"第{index}行备注", 500),
        }
        result.append(item)
        total += amount
    return result, total.quantize(CENT)


class FrappeApprovalCenterStore:
    def require_draft_access(self, request_type):
        from rayher_hr_payroll.oa_feature_gate import require_request_type_access

        require_request_type_access(request_type)

    def identity(self):
        user = frappe.session.user
        rows = frappe.get_all(
            "Employee",
            filters={"user_id": user, "status": "Active"},
            fields=["name", "employee_name", "department", "company", "reports_to"],
            limit_page_length=2,
        )
        if len(rows) > 1:
            raise ApprovalCenterError("当前账号关联多个在职员工，请先清理基础资料")
        row = rows[0] if rows else {}
        company = _get(row, "company")
        if not company:
            company = frappe.defaults.get_user_default("Company") or ""
        supervisor_employee = _get(row, "reports_to") or ""
        supervisor = ""
        supervisor_user = ""
        if supervisor_employee:
            supervisor_row = frappe.db.get_value(
                "Employee", supervisor_employee, ["employee_name", "user_id", "status"], as_dict=True
            ) or {}
            if _get(supervisor_row, "status") == "Active":
                supervisor = _get(supervisor_row, "employee_name") or supervisor_employee
                supervisor_user = _get(supervisor_row, "user_id") or ""
        return {
            "employee": _get(row, "name"),
            "employee_name": _get(row, "employee_name") or "",
            "department": _get(row, "department") or "",
            "company": company,
            "supervisor": supervisor,
            "supervisor_user": supervisor_user,
            "supervisor_decision": "approve" if supervisor else "",
        }

    def resolve_procurement_applicant(self, employee):
        requested = _text(employee, "申请人", 140)
        current = self.identity()
        if not requested or requested == _text(current.get("employee"), "申请人", 140):
            return current
        user = str(frappe.session.user or "").strip().lower()
        try:
            pmc_user = str(resolve_role("pmc").get("user") or "").strip().lower()
        except ApprovalRoleResolutionError as exc:
            raise ApprovalCenterError(str(exc))
        if user != pmc_user:
            raise ApprovalCenterError("只有 PMC 演示员工178可以代其他员工提交采购申请")
        row = frappe.db.get_value(
            "Employee",
            {"name": requested, "status": "Active"},
            ["name", "employee_name", "department", "company", "reports_to"],
            as_dict=True,
        )
        if not row:
            raise ApprovalCenterError("代提交的申请人不是在职员工")
        supervisor = {}
        if _get(row, "reports_to"):
            supervisor = frappe.db.get_value(
                "Employee",
                _get(row, "reports_to"),
                ["employee_name", "user_id", "status"],
                as_dict=True,
            ) or {}
        return {
            "employee": _get(row, "name"),
            "employee_name": _get(row, "employee_name") or _get(row, "name"),
            "department": _get(row, "department") or "",
            "company": _get(row, "company") or "",
            "supervisor": (
                _get(supervisor, "employee_name") or _get(row, "reports_to") or ""
                if _get(supervisor, "status") == "Active"
                else ""
            ),
            "supervisor_user": (
                _get(supervisor, "user_id") or ""
                if _get(supervisor, "status") == "Active"
                else ""
            ),
            "supervisor_decision": "approve" if _get(supervisor, "status") == "Active" else "",
        }

    def can_initiate_procurement_payment(self, source):
        user = str(frappe.session.user or "").strip()
        roles = set(frappe.get_roles(user) or [])
        if user in {"Administrator", "admin@staff.example.invalid"} or roles & {"System Manager", "Accounts User"}:
            return True
        return _text(_get(source, "purchaser_user"), "采购经办人", 140) == user

    def default_purchaser_user(self):
        try:
            return resolve_role("procurement_manager")["user"]
        except ApprovalRoleResolutionError as exc:
            raise ApprovalCenterError(str(exc))

    def save_draft(self, request_type, values, name=None):
        from rayher_hr_payroll.oa_mutation_guard import authorized_oa_action

        if name:
            doc = frappe.get_doc("OA Approval Request", name)
            user = frappe.session.user
            if user not in {"Administrator", "admin@staff.example.invalid"} and _get(doc, "owner") != user:
                raise ApprovalCenterError("只能修改本人创建的草稿")
            if not frappe.has_permission("OA Approval Request", "write", doc=doc):
                raise ApprovalCenterError("无权修改该草稿")
            if doc.request_type != request_type or doc.workflow_status != DRAFT_STATUS:
                raise ApprovalCenterError("只能修改同类型草稿")
        else:
            doc = frappe.new_doc("OA Approval Request")
        doc.update({key: value for key, value in values.items() if key != "business_lines"})
        doc.request_type = request_type
        doc.set("business_lines", values["business_lines"])
        with authorized_oa_action():
            if doc.is_new():
                doc.insert(ignore_permissions=True)
            else:
                doc.save(ignore_permissions=True)
        return doc

    def list_requests(self, request_types, limit):
        return frappe.get_list(
            "OA Approval Request",
            filters={"request_type": ["in", list(request_types)]},
            fields=[
                "name", "request_type", "subject", "workflow_status", "amount",
                "approved_amount", "asset_nature", "fixed_asset_category", "owner",
                "purchaser_user", "source_request", "modified", "business_status", "payment_stage",
                "prepayment_percentage", "expected_arrival_date", "arrival_status",
                "inspection_status", "prepayment_writeoff_status", "has_balance_payment",
            ],
            order_by="modified desc",
            limit_page_length=limit,
        )

    def resolve_source(self, name):
        from rayher_hr_payroll.oa_access import oa_request_has_permission

        source = frappe.get_doc("OA Approval Request", name)
        framework_allowed = frappe.has_permission("OA Approval Request", "read", doc=source)
        purchaser_allowed = (
            oa_request_has_permission(source, "read", frappe.session.user) is True
        )
        if not framework_allowed and not purchaser_allowed:
            raise ApprovalCenterError("无权使用来源申请")
        return source

    def resolve_project(self, name):
        project = frappe.db.get_value(
            "Project", name,
            ["name", "project_name", "status", "project_owner", "project_owner_name"],
            as_dict=True,
        )
        if not project or project.get("status") == "Cancelled":
            raise ApprovalCenterError("所属项目不存在或已取消")
        owner = str(project.get("project_owner") or "").strip()
        if not owner or not frappe.db.get_value("User", owner, "enabled"):
            raise ApprovalCenterError("所属项目未配置有效项目主管")
        return project

    def list_projects(self, limit):
        return frappe.get_all(
            "Project",
            filters={"status": ["!=", "Cancelled"], "project_owner": ["!=", ""]},
            fields=["name", "project_name", "status", "project_owner", "project_owner_name"],
            order_by="modified desc",
            limit_page_length=limit,
        )

    def list_procurement_payment_sources(self, limit):
        user = str(frappe.session.user or "").strip()
        roles = set(frappe.get_roles(user) or [])
        filters = {
            "request_type": REQUEST_PROCUREMENT,
            "workflow_status": "已完成",
        }
        if user not in {"Administrator", "admin@staff.example.invalid"} and not roles & {"System Manager", "Accounts User"}:
            filters["purchaser_user"] = user
        return frappe.get_all(
            "OA Approval Request",
            filters=filters,
            fields=[
                "name", "request_type", "subject", "workflow_status", "approved_amount",
                "purchaser_user", "business_status", "arrival_status", "inspection_status",
                "expected_arrival_date", "modified",
            ],
            order_by="modified desc",
            limit_page_length=limit,
        )

    def source_balance(self, source):
        from rayher_hr_payroll.approval_amount_ledger import source_balance

        request_type = _get(source, "request_type")
        if request_type in REQUEST_DASHBOARD_TYPES:
            return source_balance(_name(source))
        target = _get(source, "source_request")
        if target:
            return source_balance(target)
        return _zero_balance(_get(source, "approved_amount"))

    def payment_balance(self, payment):
        from rayher_hr_payroll.approval_amount_ledger import linked_payment_balance

        if not _get(payment, "source_request"):
            return _zero_balance(_get(payment, "approved_amount"))
        return linked_payment_balance(_name(payment))


def _store(store):
    return store or FrappeApprovalCenterStore()


FULFILLMENT_SNAPSHOT_FIELDS = (
    "arrival_status", "arrival_date", "inspection_status",
    "inspection_failure_reason", "exception_direction", "followup_status",
    "prepayment_writeoff_status",
)


def _source_ordered_quantity(source):
    total = Decimal("0")
    for row in list(_get(source, "business_lines", []) or []):
        total += _decimal(_get(row, "quantity"), "来源采购数量", positive=True, places=QUANTITY_UNIT)
    return total.quantize(QUANTITY_UNIT)


def _source_fulfillment_snapshot(source):
    if not source:
        return {}
    result = {field: _get(source, field) for field in FULFILLMENT_SNAPSHOT_FIELDS}
    result["received_quantity"] = _decimal(
        _get(source, "received_quantity") or 0,
        "来源采购累计到货数量",
        places=QUANTITY_UNIT,
    )
    return result


def project_options(limit=500, *, store=None):
    try:
        limit = max(1, min(int(limit or 500), 500))
    except (TypeError, ValueError):
        raise ApprovalCenterError("项目数量格式无效")
    store = _store(store)
    store.require_draft_access(REQUEST_PROCUREMENT)
    allowed = {"name", "project_name", "status", "project_owner", "project_owner_name"}
    return [
        {key: _get(row, key) or "" for key in allowed}
        for row in store.list_projects(limit)
    ]


def procurement_payment_source_options(limit=500, *, store=None):
    try:
        limit = max(1, min(int(limit or 500), 500))
    except (TypeError, ValueError):
        raise ApprovalCenterError("采购付款来源数量格式无效")
    store = _store(store)
    store.require_draft_access(REQUEST_PROCUREMENT_PAYMENT)
    result = []
    for source in store.list_procurement_payment_sources(limit):
        if _get(source, "request_type") != REQUEST_PROCUREMENT or _get(source, "workflow_status") != "已完成":
            continue
        balance = store.source_balance(source)
        available = _money(balance.get("available_amount"))
        if available <= 0:
            continue
        result.append({
            "name": _name(source),
            "request_type": REQUEST_PROCUREMENT,
            "subject": _get(source, "subject") or "",
            "workflow_status": "已完成",
            "purchaser_user": _get(source, "purchaser_user") or "",
            "business_status": _get(source, "business_status") or "",
            "arrival_status": _get(source, "arrival_status") or "",
            "inspection_status": _get(source, "inspection_status") or "",
            "expected_arrival_date": _get(source, "expected_arrival_date") or "",
            "approved_amount": _money(balance.get("approved_amount")),
            "reserved_amount": _money(balance.get("reserved_amount")),
            "paid_amount": _money(balance.get("paid_amount")),
            "available_amount": available,
        })
    return result


def save_draft(request_type, payload, name=None, *, store=None):
    if request_type not in DRAFT_TYPES:
        raise ApprovalCenterError("草稿类型无效")
    store = _store(store)
    store.require_draft_access(request_type)
    values = _payload(payload)
    lines, total = _lines(values.get("business_lines"))
    applicant_employee = _text(values.get("applicant_employee"), "申请人", 140)
    identity = store.identity()
    if request_type == REQUEST_PROCUREMENT:
        resolver = getattr(store, "resolve_procurement_applicant", None)
        if callable(resolver):
            identity = resolver(applicant_employee)
        elif applicant_employee and applicant_employee != _get(identity, "employee"):
            raise ApprovalCenterError("当前存储实现不支持代其他员工提交采购申请")
    elif applicant_employee:
        raise ApprovalCenterError("代申请人只属于采购申请")
    asset_nature = _text(values.get("asset_nature"), "资产属性", 20, required=True)
    if asset_nature not in ASSET_NATURES:
        raise ApprovalCenterError("资产属性无效")
    fixed_category = _text(values.get("fixed_asset_category"), "固定资产类别", 80)
    if asset_nature == "固定资产" and fixed_category not in FIXED_ASSET_CATEGORIES:
        raise ApprovalCenterError("固定资产类别无效")
    if asset_nature != "固定资产":
        fixed_category = ""

    procurement_scope = _text(values.get("procurement_scope"), "采购范围", 20)
    expected_delivery_date = _text(values.get("expected_delivery_date"), "意向交期", 10)
    project_name = _text(values.get("project"), "所属项目", 140)
    project_owner = ""
    project_owner_name = ""
    allocation_type = _text(values.get("non_project_allocation_type"), "非项目归属", 20)
    non_project_cost_center = _text(values.get("non_project_cost_center"), "成本中心", 140)
    non_project_department = _text(values.get("non_project_department"), "所属部门", 140)
    purchaser_user = _text(values.get("purchaser_user"), "采购经办人", 140)
    if request_type == REQUEST_PROCUREMENT:
        resolver = getattr(store, "default_purchaser_user", None)
        if callable(resolver):
            purchaser_user = _text(resolver(), "采购经办人", 140, required=True)
        elif not purchaser_user:
            raise ApprovalCenterError("采购申请未配置采购经办人")
    elif purchaser_user:
        raise ApprovalCenterError("采购经办人只属于采购申请")
    purchase_method = _text(values.get("purchase_method"), "购买方式", 20)
    supplier = _text(values.get("supplier"), "供应商", 140)
    payment_stage = _text(values.get("payment_stage"), "付款阶段", 20)
    prepayment_percentage = _decimal(values.get("prepayment_percentage") or 0, "预付款比例")
    has_balance_payment = 1 if values.get("has_balance_payment") in (1, "1", True) else 0
    expected_arrival_date = _text(values.get("expected_arrival_date"), "预计到货日期", 10)
    prepayment_risk_note = _text(values.get("prepayment_risk_note"), "预付款风险说明", 1000)

    if request_type in {REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE} and project_name:
        project = store.resolve_project(project_name)
        project_owner = _text(_get(project, "project_owner"), "项目负责人", 140)
        project_owner_name = _text(_get(project, "project_owner_name"), "项目负责人姓名", 140) or project_owner

    if request_type == REQUEST_PROCUREMENT:
        try:
            validate_procurement_submission({
                "procurement_scope": procurement_scope,
                "expected_delivery_date": expected_delivery_date,
                "project": project_name,
                "project_owner": project_owner,
                "non_project_allocation_type": allocation_type,
                "non_project_cost_center": non_project_cost_center,
                "non_project_department": non_project_department,
            })
        except ProcurementWorkflowError as exc:
            raise ApprovalCenterError(str(exc))
    elif request_type != REQUEST_DIRECT_PURCHASE and any((procurement_scope, project_name, allocation_type, non_project_cost_center, non_project_department)):
        raise ApprovalCenterError("采购范围和项目归属只属于采购申请或购买申请")

    if request_type == REQUEST_DIRECT_PURCHASE:
        if purchase_method not in {"京东购买", "其他购买"}:
            raise ApprovalCenterError("购买申请必须选择京东购买或其他购买")
        try:
            date.fromisoformat(expected_delivery_date)
        except (TypeError, ValueError):
            raise ApprovalCenterError("购买申请必须填写有效意向交期")
        if not project_name:
            if allocation_type not in NON_PROJECT_ALLOCATION_TYPES:
                raise ApprovalCenterError("购买申请必须选择项目或非项目成本归属")
            if allocation_type == "成本中心" and not non_project_cost_center:
                raise ApprovalCenterError("购买申请选择成本中心时必须填写成本中心")
            if allocation_type == "部门" and not non_project_department:
                raise ApprovalCenterError("购买申请选择部门时必须填写所属部门")
    elif purchase_method:
        raise ApprovalCenterError("购买方式只属于购买申请")

    if request_type == REQUEST_PROCUREMENT_PAYMENT:
        if not supplier:
            raise ApprovalCenterError("采购付款必须选择供应商")
    elif any((supplier, payment_stage, prepayment_percentage, has_balance_payment, expected_arrival_date, prepayment_risk_note)):
        raise ApprovalCenterError("采购付款字段只属于采购付款")

    source_request = _text(values.get("source_request"), "来源申请", 140)
    if request_type != REQUEST_PROCUREMENT_PAYMENT and source_request:
        raise ApprovalCenterError("只有采购付款草稿可以关联来源申请")
    source_snapshot = None
    if source_request:
        source_snapshot = store.resolve_source(source_request)
        if _get(source_snapshot, "request_type") != REQUEST_PROCUREMENT:
            raise ApprovalCenterError("采购付款只能关联采购申请")
        if _get(source_snapshot, "workflow_status") != "已完成":
            raise ApprovalCenterError("来源采购申请必须已完成")
        if str(_get(source_snapshot, "currency") or "") != "CNY":
            raise ApprovalCenterError("来源采购申请必须为人民币")
        if _money(_get(source_snapshot, "approved_amount")) <= 0:
            raise ApprovalCenterError("来源采购申请批准金额无效")
        if not store.can_initiate_procurement_payment(source_snapshot):
            raise ApprovalCenterError("只有来源采购申请的采购经办人或财务可以发起采购付款")
    fulfillment = _source_fulfillment_snapshot(source_snapshot)
    source_payment_balance = store.source_balance(source_snapshot) if source_snapshot else None
    if request_type == REQUEST_PROCUREMENT_PAYMENT:
        stage_values = {
            "prepayment_percentage": prepayment_percentage,
            "arrival_status": fulfillment.get("arrival_status") or "未到货",
            "inspection_status": fulfillment.get("inspection_status") or "未验收",
            "source_paid_amount": _get(source_payment_balance, "paid_amount") or 0,
            "source_available_amount": _get(source_payment_balance, "available_amount") or 0,
            "amount": total,
        }
        try:
            payment_stage = derive_payment_stage(stage_values)
        except ProcurementWorkflowError as exc:
            raise ApprovalCenterError(str(exc))
        if payment_stage == "预付款":
            has_balance_payment = 1 if prepayment_percentage < 100 else 0
        else:
            has_balance_payment = 1 if total < _get(source_payment_balance, "available_amount") else 0
            prepayment_percentage = Decimal("0")
    prepared = {
        "workflow_status": DRAFT_STATUS,
        "company": identity.get("company") or "",
        "employee": identity.get("employee"),
        "employee_name": identity.get("employee_name") or "",
        "department": identity.get("department") or "",
        "supervisor": identity.get("supervisor") or "",
        "subject": _text(values.get("subject"), "主题", 140, required=True),
        "urgency": _text(values.get("urgency") or "一般", "紧急程度", 20),
        "reason": _text(values.get("reason"), "申请说明", 1000),
        "asset_nature": asset_nature,
        "fixed_asset_category": fixed_category,
        "asset_category": PRODUCTION_ASSET if fixed_category == PRODUCTION_ASSET else OTHER_ASSET,
        "business_status": "",
        "procurement_scope": procurement_scope or None,
        "expected_delivery_date": expected_delivery_date or None,
        "project": project_name or None,
        "project_owner": project_owner or None,
        "project_owner_name": project_owner_name,
        "non_project_allocation_type": allocation_type or None,
        "non_project_cost_center": non_project_cost_center or None,
        "non_project_department": non_project_department or None,
        "purchaser_user": purchaser_user or None,
        "purchase_method": purchase_method or None,
        "supplier": supplier or None,
        "payment_stage": payment_stage or None,
        "prepayment_percentage": prepayment_percentage,
        "has_balance_payment": has_balance_payment,
        "expected_arrival_date": expected_arrival_date or None,
        "prepayment_risk_note": prepayment_risk_note,
        "ordered_quantity": (
            _source_ordered_quantity(source_snapshot)
            if source_snapshot
            else _source_ordered_quantity({"business_lines": lines})
            if request_type == REQUEST_PROCUREMENT
            else None
        ),
        "received_quantity": fulfillment.get("received_quantity", 0),
        "arrival_status": fulfillment.get("arrival_status") or ("未到货" if source_snapshot else None),
        "arrival_date": fulfillment.get("arrival_date"),
        "inspection_status": fulfillment.get("inspection_status") or ("未验收" if source_snapshot else None),
        "inspection_failure_reason": fulfillment.get("inspection_failure_reason") or "",
        "exception_direction": fulfillment.get("exception_direction") or "",
        "followup_status": fulfillment.get("followup_status") or "",
        "prepayment_writeoff_status": fulfillment.get("prepayment_writeoff_status") or "无需核销",
        "amount": total,
        "currency": "CNY",
        "approved_amount": None,
        "source_request": source_request or None,
        "approved_amount_snapshot": _money(_get(source_snapshot, "approved_amount")) if source_snapshot else None,
        "source_modified": _get(source_snapshot, "modified") if source_snapshot else None,
        "payment_source_kind": "关联采购申请" if source_request else None,
        "business_lines": lines,
        "current_step_index": 0,
        "current_step_label": "",
        "steps": [],
        "operation_log": "[]",
    }
    return store.save_draft(request_type, prepared, _text(name, "草稿编号", 140) or None)


def _zero_balance(approved=0):
    approved = _decimal(approved or 0, "批准金额")
    return {
        "approved_amount": approved,
        "reserved_amount": Decimal("0.00"),
        "paid_amount": Decimal("0.00"),
        "available_amount": approved,
    }


def _money(value):
    return _decimal(value or 0, "金额")


def _summary_bucket(label):
    return {"label": label, "count": 0, "applied_amount": Decimal("0.00"), "names": []}


def _add_summary_record(bucket, row):
    bucket["count"] += 1
    bucket["applied_amount"] += _money(row.get("applied_amount"))
    bucket["names"].append(row["name"])


def _dashboard_drilldowns(kind, rows):
    asset_summary = {
        "fixed_asset": _summary_bucket("固定资产"),
        "non_fixed_asset": _summary_bucket("非固定资产"),
        "historical_unclassified": _summary_bucket("历史未分类"),
        "categories": [],
    }
    category_buckets = {}
    prepayment_risk_summary = {
        "pending_arrival": _summary_bucket("待到货"),
        "pending_inspection": _summary_bucket("待验收"),
        "inspection_rejected": _summary_bucket("验收不合格"),
        "pending_writeoff": _summary_bucket("待预付款核销"),
        "overdue_full_prepayment": _summary_bucket("100%预付款逾期"),
    }

    for row in rows:
        asset_nature = row.get("asset_nature") or ""
        if asset_nature == "固定资产":
            _add_summary_record(asset_summary["fixed_asset"], row)
            category = row.get("fixed_asset_category") or "固定资产未分类"
            bucket = category_buckets.setdefault(category, _summary_bucket(category))
            _add_summary_record(bucket, row)
        elif asset_nature == "非固定资产":
            _add_summary_record(asset_summary["non_fixed_asset"], row)
        else:
            _add_summary_record(asset_summary["historical_unclassified"], row)

        if kind != "payment" or row.get("request_type") != REQUEST_PROCUREMENT_PAYMENT:
            continue
        if row.get("workflow_status") in {"已完成", "已付款"} and row.get("business_status") != "已关闭":
            arrival_status = row.get("arrival_status") or "未到货"
            inspection_status = row.get("inspection_status") or "未验收"
            if arrival_status not in {"全部到货", "已关闭"}:
                _add_summary_record(prepayment_risk_summary["pending_arrival"], row)
            if arrival_status in {"全部到货", "已关闭"} and inspection_status in {"", "未验收", "待验收"}:
                _add_summary_record(prepayment_risk_summary["pending_inspection"], row)
            if inspection_status == "验收不合格":
                _add_summary_record(prepayment_risk_summary["inspection_rejected"], row)
            if row.get("prepayment_writeoff_status") == "待核销":
                _add_summary_record(prepayment_risk_summary["pending_writeoff"], row)
            try:
                if derive_prepayment_overdue(row):
                    _add_summary_record(prepayment_risk_summary["overdue_full_prepayment"], row)
            except ProcurementWorkflowError:
                pass

    asset_summary["categories"] = [
        category_buckets[label] for label in sorted(category_buckets)
    ]
    return asset_summary, prepayment_risk_summary


def dashboard(kind, limit=200, *, store=None):
    if kind == "request":
        request_types = REQUEST_DASHBOARD_TYPES
    elif kind == "payment":
        request_types = PAYMENT_DASHBOARD_TYPES
    else:
        raise ApprovalCenterError("看板类型无效")
    try:
        limit = max(1, min(int(limit or 200), 500))
    except (TypeError, ValueError):
        raise ApprovalCenterError("看板数量格式无效")
    store = _store(store)
    rows = []
    summary = {key: Decimal("0.00") for key in (
        "applied_amount", "approved_amount", "reserved_amount", "paid_amount", "available_amount"
    )}
    for source in store.list_requests(request_types, limit):
        applied = _money(_get(source, "amount"))
        approved = _money(_get(source, "approved_amount"))
        if kind == "payment" and _get(source, "request_type") == REQUEST_PROCUREMENT_PAYMENT:
            balance = store.payment_balance(source)
        elif _get(source, "workflow_status") == "已完成" and approved > 0:
            balance = store.source_balance(source)
        else:
            balance = _zero_balance(approved)
        asset_nature = _text(_get(source, "asset_nature"), "资产属性", 20)
        asset_classification = asset_nature or "历史未分类"
        if asset_nature == "固定资产" and _get(source, "fixed_asset_category"):
            asset_classification = str(_get(source, "fixed_asset_category"))
        row = {
            "name": _name(source),
            "request_type": _get(source, "request_type"),
            "subject": _get(source, "subject") or "",
            "workflow_status": _get(source, "workflow_status") or "",
            "asset_classification": asset_classification,
            "asset_nature": asset_nature,
            "fixed_asset_category": _get(source, "fixed_asset_category") or "",
            "owner": _get(source, "owner") or "",
            "purchaser_user": _get(source, "purchaser_user") or "",
            "modified": _get(source, "modified"),
            "business_status": _get(source, "business_status") or "",
            "payment_stage": _get(source, "payment_stage") or "",
            "prepayment_percentage": _get(source, "prepayment_percentage"),
            "expected_arrival_date": _get(source, "expected_arrival_date"),
            "arrival_status": _get(source, "arrival_status") or "",
            "inspection_status": _get(source, "inspection_status") or "",
            "prepayment_writeoff_status": _get(source, "prepayment_writeoff_status") or "",
            "has_balance_payment": _get(source, "has_balance_payment"),
            "applied_amount": applied,
            "approved_amount": _money(balance.get("approved_amount")),
            "reserved_amount": _money(balance.get("reserved_amount")),
            "paid_amount": _money(balance.get("paid_amount")),
            "available_amount": _money(balance.get("available_amount")),
        }
        rows.append(row)
        for key in summary:
            summary[key] += row[key]
    asset_summary, prepayment_risk_summary = _dashboard_drilldowns(kind, rows)
    return {
        "kind": kind,
        "summary": summary,
        "asset_summary": asset_summary,
        "prepayment_risk_summary": prepayment_risk_summary,
        "rows": rows,
    }
