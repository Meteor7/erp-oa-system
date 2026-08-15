from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe

from rayher_hr_payroll.oa_approval import OTHER_ASSET, PRODUCTION_ASSET, REQUEST_EXPENSE_PAYMENT
from rayher_hr_payroll.procurement_workflow import (
    PAYMENT_STAGES,
    ProcurementWorkflowError,
    validate_procurement_submission,
)
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
    "inspection_status", "prepayment_writeoff_status", "received_quantity",
}
ALLOWED_PAYLOAD_FIELDS = {
    "subject", "reason", "urgency", "asset_nature", "fixed_asset_category",
    "business_lines", "source_request", "procurement_scope", "expected_delivery_date",
    "project", "non_project_allocation_type", "non_project_cost_center",
    "non_project_department", "purchaser_user", "contract_delivery_date",
    "delivery_change_reason", "purchase_method", "supplier", "payment_stage",
    "prepayment_percentage", "has_balance_payment", "expected_arrival_date",
    "prepayment_risk_note",
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
                "source_request", "modified",
            ],
            order_by="modified desc",
            limit_page_length=limit,
        )

    def resolve_source(self, name):
        source = frappe.get_doc("OA Approval Request", name)
        if not frappe.has_permission("OA Approval Request", "read", doc=source):
            raise ApprovalCenterError("无权使用来源申请")
        return source

    def resolve_project(self, name):
        project = frappe.get_doc("Project", name)
        if not frappe.has_permission("Project", "read", doc=project):
            raise ApprovalCenterError("无权使用所属项目")
        return project

    def source_balance(self, source):
        from rayher_hr_payroll.approval_amount_ledger import source_balance

        request_type = _get(source, "request_type")
        if request_type in REQUEST_DASHBOARD_TYPES:
            return source_balance(_name(source))
        target = _get(source, "source_request")
        if target:
            return source_balance(target)
        return _zero_balance(_get(source, "approved_amount"))


def _store(store):
    return store or FrappeApprovalCenterStore()


def save_draft(request_type, payload, name=None, *, store=None):
    if request_type not in DRAFT_TYPES:
        raise ApprovalCenterError("草稿类型无效")
    store = _store(store)
    store.require_draft_access(request_type)
    values = _payload(payload)
    lines, total = _lines(values.get("business_lines"))
    identity = store.identity()
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
    purchase_method = _text(values.get("purchase_method"), "购买方式", 20)
    supplier = _text(values.get("supplier"), "供应商", 140)
    payment_stage = _text(values.get("payment_stage"), "付款阶段", 20)
    prepayment_percentage = _decimal(values.get("prepayment_percentage") or 0, "预付款比例")
    has_balance_payment = 1 if values.get("has_balance_payment") in (1, "1", True) else 0
    expected_arrival_date = _text(values.get("expected_arrival_date"), "预计到货日期", 10)
    prepayment_risk_note = _text(values.get("prepayment_risk_note"), "预付款风险说明", 1000)

    if request_type == REQUEST_PROCUREMENT:
        if project_name:
            project = store.resolve_project(project_name)
            project_owner = _text(_get(project, "project_owner"), "项目负责人", 140)
            project_owner_name = _text(_get(project, "project_owner_name"), "项目负责人姓名", 140) or project_owner
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
    elif any((procurement_scope, project_name, allocation_type, non_project_cost_center, non_project_department)):
        raise ApprovalCenterError("采购范围和项目归属只属于采购申请")

    if request_type == REQUEST_DIRECT_PURCHASE:
        if purchase_method not in {"京东购买", "其他购买"}:
            raise ApprovalCenterError("购买申请必须选择京东购买或其他购买")
    elif purchase_method:
        raise ApprovalCenterError("购买方式只属于购买申请")

    if request_type == REQUEST_PROCUREMENT_PAYMENT:
        if not supplier:
            raise ApprovalCenterError("采购付款必须选择供应商")
        if payment_stage not in PAYMENT_STAGES:
            raise ApprovalCenterError("付款阶段无效")
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
        if _get(source, "workflow_status") == "已完成" and approved > 0:
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
            "owner": _get(source, "owner") or "",
            "modified": _get(source, "modified"),
            "applied_amount": applied,
            "approved_amount": _money(balance.get("approved_amount")),
            "reserved_amount": _money(balance.get("reserved_amount")),
            "paid_amount": _money(balance.get("paid_amount")),
            "available_amount": _money(balance.get("available_amount")),
        }
        rows.append(row)
        for key in summary:
            summary[key] += row[key]
    return {"kind": kind, "summary": summary, "rows": rows}