from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe

from rayher_hr_payroll.oa_approval import REQUEST_EXPENSE_PAYMENT
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
    "employee_name", "department", "company", "current_step_index",
    "current_step_label", "currency", "paid_by", "paid_on", "operation_log",
    "approved_amount_snapshot", "source_modified", "payment_source_kind",
}
ALLOWED_PAYLOAD_FIELDS = {
    "subject", "reason", "urgency", "asset_nature", "fixed_asset_category",
    "business_lines", "source_request",
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
            fields=["name", "employee_name", "department", "company"],
            limit_page_length=2,
        )
        if len(rows) > 1:
            raise ApprovalCenterError("当前账号关联多个在职员工，请先清理基础资料")
        row = rows[0] if rows else {}
        company = _get(row, "company")
        if not company:
            company = frappe.defaults.get_user_default("Company") or ""
        return {
            "employee": _get(row, "name"),
            "employee_name": _get(row, "employee_name") or "",
            "department": _get(row, "department") or "",
            "company": company,
        }

    def save_draft(self, request_type, values, name=None):
        from rayher_hr_payroll.oa_mutation_guard import authorized_oa_action

        if name:
            doc = frappe.get_doc("OA Approval Request", name)
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
        "subject": _text(values.get("subject"), "主题", 140, required=True),
        "urgency": _text(values.get("urgency") or "一般", "紧急程度", 20),
        "reason": _text(values.get("reason"), "申请说明", 1000),
        "asset_nature": asset_nature,
        "fixed_asset_category": fixed_category,
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