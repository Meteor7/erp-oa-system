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
from rayher_hr_payroll.position_access import current_supervisors, executive_names
from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
)
from rayher_hr_payroll.oa_organization import (
    DIRECT_SUPERVISOR_BY_EMPLOYEE,
    TOP_EXECUTIVES,
    OrganizationResolutionError,
    resolve_stage_two_supervisor,
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
    "exception_direction", "followup_status", "source_payment_plan_installment",
}
ALLOWED_PAYLOAD_FIELDS = {
    "subject", "reason", "urgency", "asset_nature", "fixed_asset_category",
    "business_lines", "source_request", "procurement_scope", "expected_delivery_date",
    "project", "non_project_allocation_type", "non_project_cost_center",
    "non_project_department", "purchaser_user", "contract_delivery_date",
    "delivery_change_reason", "purchase_method", "supplier", "payment_stage",
    "prepayment_percentage", "has_balance_payment", "expected_arrival_date",
    "prepayment_risk_note", "applicant_employee", "source_payment_plan_row",
    "source_purchase_order", "source_po_payment_plan_row",
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


def _enabled_employee_user(employee_name):
    candidate = _name(employee_name)
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
            return str(enabled_user).strip().lower()
    return ""


def _resolved_supervisor(employee_name, reports_to=""):
    employee_name = _name(employee_name)
    if employee_name in current_supervisors() or employee_name in executive_names():
        try:
            resolution = resolve_stage_two_supervisor(
                employee_name, _enabled_employee_user
            )
        except OrganizationResolutionError as exc:
            raise ApprovalCenterError(str(exc)) from exc
        return {
            "supervisor": resolution.supervisor_name,
            "supervisor_user": resolution.user_id,
            "supervisor_decision": resolution.decision,
            "supervisor_path": list(resolution.traversed),
        }

    supervisor = {}
    if reports_to:
        supervisor = frappe.db.get_value(
            "Employee",
            reports_to,
            ["employee_name", "user_id", "status"],
            as_dict=True,
        ) or {}
    if _get(supervisor, "status") != "Active":
        return {
            "supervisor": "", "supervisor_user": "",
            "supervisor_decision": "", "supervisor_path": [],
        }
    supervisor_name = _get(supervisor, "employee_name") or reports_to
    return {
        "supervisor": supervisor_name,
        "supervisor_user": _enabled_employee_user(supervisor_name),
        "supervisor_decision": (
            "skip" if supervisor_name in executive_names() else "approve"
        ),
        "supervisor_path": [supervisor_name],
    }


def _text(value, label="文本", limit=140, *, required=False):
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
    allowed = {
        "material_code", "category_code", "category_path", "item_name", "specification",
        "product_desc", "brand", "product_name", "product_desc_en", "brand_en", "material_attr",
        "quantity", "unit", "unit_price", "remarks",
    }
    # UI-only state may be present in drafts created by older frontend bundles.
    # Ignore it at the API boundary; never persist client-provided serials or picker state.
    ignored_client_fields = {
        "material_serial", "category_parts", "category_query", "category_open",
        "category_picker_parent", "category_picker_path", "material_query", "material_open",
        "category_name", "amount",
    }
    for index, row in enumerate(values, 1):
        if not isinstance(row, dict):
            raise ApprovalCenterError(f"第{index}行采购明细格式无效")
        unknown = set(row) - allowed - ignored_client_fields
        if unknown:
            raise ApprovalCenterError(
                f"第{index}行采购明细包含未知字段：" + "、".join(sorted(unknown))
            )
        quantity = _decimal(row.get("quantity"), f"第{index}行数量", positive=True, places=QUANTITY_UNIT)
        unit_price = _decimal(row.get("unit_price"), f"第{index}行单价")
        amount = (quantity * unit_price).quantize(CENT, rounding=ROUND_HALF_UP)
        item = {
            "material_code": _text(row.get("material_code"), f"第{index}行物料编号", 140),
            "category_code": _text(row.get("category_code"), f"第{index}行物料编号层级", 140),
            "category_path": _text(row.get("category_path"), f"第{index}行分类路径", 500),
            "item_name": _text(row.get("item_name"), f"第{index}行物品名称", 140, required=True),
            "specification": _text(row.get("specification"), f"第{index}行规格", 140),
            "product_desc": _text(row.get("product_desc"), f"第{index}行产品描述", 2000),
            "brand": _text(row.get("brand"), f"第{index}行品牌", 140),
            "product_name": _text(row.get("product_name"), f"第{index}行英文名称", 140),
            "product_desc_en": _text(row.get("product_desc_en"), f"第{index}行英文描述", 2000),
            "brand_en": _text(row.get("brand_en"), f"第{index}行英文品牌", 140),
            "material_attr": _text(row.get("material_attr"), f"第{index}行物料属性", 40),
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
        supervisor = _resolved_supervisor(
            _get(row, "employee_name"), _get(row, "reports_to")
        )
        return {
            "employee": _get(row, "name"),
            "employee_name": _get(row, "employee_name") or "",
            "department": _get(row, "department") or "",
            "company": company,
            **supervisor,
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
        supervisor = _resolved_supervisor(
            _get(row, "employee_name"), _get(row, "reports_to")
        )
        return {
            "employee": _get(row, "name"),
            "employee_name": _get(row, "employee_name") or _get(row, "name"),
            "department": _get(row, "department") or "",
            "company": _get(row, "company") or "",
            **supervisor,
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
            withdrawn_procurement = (
                request_type == REQUEST_PROCUREMENT
                and _get(doc, "workflow_status") == DRAFT_STATUS
                and _get(doc, "business_status") == "已撤回"
            )
            if doc.request_type != request_type or (
                doc.workflow_status != DRAFT_STATUS and not withdrawn_procurement
            ):
                raise ApprovalCenterError("只能修改同类型草稿")
            if withdrawn_procurement:
                doc.business_status = ""
        else:
            doc = frappe.new_doc("OA Approval Request")
        doc.update({key: value for key, value in values.items() if key not in {"business_lines", "direct_purchase_lines"}})
        doc.request_type = request_type
        if request_type == REQUEST_DIRECT_PURCHASE:
            doc.set("business_lines", [])
            doc.set("direct_purchase_lines", values.get("direct_purchase_lines", []))
        else:
            doc.set("business_lines", values.get("business_lines", []))
            doc.set("direct_purchase_lines", [])
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
                "purchaser_user", "source_request", "source_purchase_order", "source_po_payment_plan_row", "modified", "business_status", "payment_stage",
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
            "contract_status": "已生效",
        }
        if user not in {"Administrator", "admin@staff.example.invalid"} and not roles & {"System Manager", "Accounts User"}:
            filters["purchaser_user"] = user
        names = frappe.get_all(
            "OA Approval Request",
            filters=filters,
            pluck="name",
            order_by="modified desc",
            limit_page_length=limit,
        )
        return [frappe.get_doc("OA Approval Request", name) for name in names]

    def payment_plan_row_in_use(self, row_name, current_name=None):
        filters = {
            "request_type": REQUEST_PROCUREMENT_PAYMENT,
            "source_payment_plan_row": row_name,
            "workflow_status": ["not in", ["已拒绝"]],
        }
        if current_name:
            filters["name"] = ["!=", current_name]
        return bool(frappe.db.exists("OA Approval Request", filters))

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
        if _get(source, "contract_status") != "已生效":
            continue
        balance = store.source_balance(source)
        available = _money(balance.get("available_amount"))
        if available <= 0:
            continue
        for row in list(_get(source, "payment_plan", []) or []):
            row_name = _name(row)
            if _get(row, "status") != "待下推" or not row_name:
                continue
            in_use = getattr(store, "payment_plan_row_in_use", lambda *args: False)
            if in_use(row_name):
                continue
            trigger = str(_get(row, "trigger_condition") or "").strip()
            if "验收" in trigger and _get(source, "inspection_status") != "验收通过":
                continue
            if "到货" in trigger and _get(source, "arrival_status") not in {"全部到货", "关闭未交数量"}:
                continue
            amount = _money(_get(row, "amount"))
            if amount <= 0 or amount > available:
                continue
            result.append({
                "name": _name(source),
                "payment_plan_row": row_name,
                "installment_no": int(_get(row, "installment_no") or 0),
                "installment_name": _get(row, "installment_name") or "",
                "payment_stage": _get(row, "payment_stage") or "",
                "percentage": _decimal(_get(row, "percentage") or 0, "付款比例"),
                "planned_date": _get(row, "planned_date") or "",
                "trigger_condition": _get(row, "trigger_condition") or "",
                "invoice_requirement": _get(row, "invoice_requirement") or "",
                "amount": amount,
                "supplier": _get(source, "supplier") or "",
                "business_lines": [
                    {
                        key: _get(line, key)
                        for key in ("item_name", "specification", "quantity", "unit", "unit_price", "amount", "remarks")
                    }
                    for line in list(_get(source, "business_lines", []) or [])
                ],
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
    # PO-owned payment plans are the current procurement payment source.  The
    # memory-store unit tests do not bind a Frappe request context, so avoid
    # touching the database in that isolated mode.
    try:
        po_names = frappe.get_all(
            "OA Purchase Order", filters={"contract_status": "已生效", "status": ["not in", ["草稿", "待采购确认", "待合同复核", "待电子用印", "已取消"]]},
            pluck="name", order_by="modified desc", limit_page_length=limit,
        )
    except RuntimeError:
        po_names = []
    for po_name in po_names:
        po = frappe.get_doc("OA Purchase Order", po_name)
        for row in list(getattr(po, "payment_plan", []) or []):
            row_name = _name(row)
            if not row_name or _get(row, "status") not in {"待审批", "审批中"}:
                continue
            trigger = str(_get(row, "trigger_condition") or "").strip()
            if "验收" in trigger and not all(_get(line, "inspection_status") == "已通过" for line in (getattr(po, "lines", []) or [])):
                continue
            if "到货" in trigger and not all(Decimal(str(_get(line, "received_quantity") or 0)) >= Decimal(str(_get(line, "quantity") or 0)) for line in (getattr(po, "lines", []) or [])):
                continue
            result.append({
                "name": po.name, "payment_plan_row": row_name, "source_purchase_order": po.name,
                "source_po_payment_plan_row": row_name, "installment_no": int(_get(row, "installment_no") or 0),
                "installment_name": _get(row, "installment_name") or "", "payment_stage": _get(row, "payment_stage") or "",
                "percentage": _decimal(_get(row, "percentage") or 0, "付款比例"), "planned_date": _get(row, "planned_date") or "",
                "trigger_condition": _get(row, "trigger_condition") or "", "invoice_requirement": _get(row, "invoice_requirement") or "",
                "amount": _money(_get(row, "amount")), "supplier": _get(po, "supplier") or "",
                "business_lines": [{key: _get(line, key) for key in ("item_name", "specification", "quantity", "unit", "unit_price", "amount", "remarks")} for line in (getattr(po, "lines", []) or [])],
                "request_type": REQUEST_PROCUREMENT, "subject": f"{po.name} · {_get(row, 'installment_name') or ''}",
                "workflow_status": "已完成", "purchaser_user": _get(po, "owner") or "", "business_status": _get(po, "status") or "",
                "arrival_status": "", "inspection_status": "", "expected_arrival_date": _get(row, "planned_date") or "",
                "approved_amount": _money(_get(po, "total_amount")), "reserved_amount": _money(0), "paid_amount": _money(0),
                "available_amount": _money(_get(row, "amount")),
            })
    return result


def save_draft(request_type, payload, name=None, *, store=None):
    if request_type not in DRAFT_TYPES:
        raise ApprovalCenterError("草稿类型无效")
    store = _store(store)
    store.require_draft_access(request_type)
    values = _payload(payload)
    lines, total = _lines(values.get("business_lines"))
    direct_lines = []
    if request_type == REQUEST_DIRECT_PURCHASE:
        direct_lines = [
            {key: line.get(key) for key in ("item_name", "specification", "product_desc", "quantity", "unit", "unit_price", "remarks")}
            for line in values.get("business_lines", [])
        ]
    if request_type == REQUEST_PROCUREMENT:
        for line in lines:
            line["unit_price"] = Decimal("0.00")
            line["amount"] = Decimal("0.00")
        total = Decimal("0.00")
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
    if request_type == REQUEST_PROCUREMENT:
        # Procurement requests keep only the broad asset nature for later
        # accounting; detailed fixed-asset categories belong to direct purchase.
        fixed_category = ""
    elif asset_nature == "固定资产" and fixed_category not in FIXED_ASSET_CATEGORIES:
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
                "business_lines": lines,
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
    elif purchase_method:
        raise ApprovalCenterError("购买方式只属于购买申请")

    if request_type == REQUEST_PROCUREMENT_PAYMENT:
        if not supplier:
            raise ApprovalCenterError("采购付款必须选择供应商")
    elif any((supplier, payment_stage, prepayment_percentage, has_balance_payment, expected_arrival_date, prepayment_risk_note)):
        raise ApprovalCenterError("采购付款字段只属于采购付款")

    source_request = _text(values.get("source_request"), "来源申请", 140)
    source_payment_plan_row = _text(values.get("source_payment_plan_row"), "付款计划期次", 140)
    source_purchase_order = _text(values.get("source_purchase_order"), "来源 PO", 140)
    source_po_payment_plan_row = _text(values.get("source_po_payment_plan_row"), "PO 付款计划期次", 140)
    if request_type != REQUEST_PROCUREMENT_PAYMENT and (source_request or source_payment_plan_row or source_purchase_order or source_po_payment_plan_row):
        raise ApprovalCenterError("只有采购付款草稿可以关联付款计划")
    source_snapshot = None
    source_plan = None
    if request_type == REQUEST_PROCUREMENT_PAYMENT and not ((source_request and source_payment_plan_row) or (source_purchase_order and source_po_payment_plan_row)):
        raise ApprovalCenterError("采购付款必须选择已生效合同的付款计划期次")
    if source_purchase_order:
        po = frappe.get_doc("OA Purchase Order", source_purchase_order)
        if _get(po, "contract_status") != "已生效":
            raise ApprovalCenterError("来源 PO 合同必须已电子用印生效")
        source_plan = next((row for row in list(_get(po, "payment_plan", []) or []) if _name(row) == source_po_payment_plan_row), None)
        if not source_plan or _get(source_plan, "status") not in {"待审批", "审批中"}:
            raise ApprovalCenterError("PO 付款计划期次不存在或当前不可下推")
        supplier = _text(_get(po, "supplier"), "供应商", 140, required=True)
        source_request = source_request or next((_text(_get(line, "source_request")) for line in list(_get(po, "lines", []) or []) if _text(_get(line, "source_request"))), "")
        source_snapshot = {
            "name": po.name, "request_type": REQUEST_PROCUREMENT, "workflow_status": "已完成",
            "contract_status": "已生效", "currency": _get(po, "currency") or "CNY",
            "approved_amount": _get(po, "total_amount") or 0, "supplier": supplier,
            "purchaser_user": _get(po, "owner") or "", "project": "",
            "payment_plan": list(_get(po, "payment_plan", []) or []),
            "business_lines": list(_get(po, "lines", []) or []),
            "modified": _get(po, "modified"),
        }
        source_lines = [{key: _get(row, key) for key in ("item_name", "specification", "quantity", "unit", "unit_price", "remarks")} for row in list(_get(po, "lines", []) or [])]
        lines, ignored_total = _lines(source_lines)
        total = _money(_get(source_plan, "amount"))
        payment_stage = _text(_get(source_plan, "payment_stage"), "付款阶段", 20, required=True)
        prepayment_percentage = _decimal(_get(source_plan, "percentage") or 0, "预付款比例") if payment_stage == "预付款" else Decimal("0")
        has_balance_payment = 1 if any(_name(row) != source_po_payment_plan_row and _get(row, "status") in {"待审批", "审批中"} for row in list(_get(source_snapshot, "payment_plan", []) or [])) else 0
    elif source_request:
        source_snapshot = store.resolve_source(source_request)
        if _get(source_snapshot, "request_type") != REQUEST_PROCUREMENT:
            raise ApprovalCenterError("采购付款只能关联采购申请")
        if _get(source_snapshot, "workflow_status") != "已完成" or _get(source_snapshot, "contract_status") != "已生效":
            raise ApprovalCenterError("来源采购合同必须已生效")
        if str(_get(source_snapshot, "currency") or "") != "CNY":
            raise ApprovalCenterError("来源采购申请必须为人民币")
        if _money(_get(source_snapshot, "approved_amount")) <= 0:
            raise ApprovalCenterError("来源采购申请批准金额无效")
        if not store.can_initiate_procurement_payment(source_snapshot):
            raise ApprovalCenterError("只有来源采购申请的采购经办人或财务可以发起采购付款")
        source_plan = next(
            (row for row in list(_get(source_snapshot, "payment_plan", []) or []) if _name(row) == source_payment_plan_row),
            None,
        )
        if not source_plan or _get(source_plan, "status") != "待下推":
            raise ApprovalCenterError("付款计划期次不存在或当前不可下推")
        in_use = getattr(store, "payment_plan_row_in_use", lambda *args: False)
        if in_use(source_payment_plan_row, _text(name, "草稿编号", 140) or None):
            raise ApprovalCenterError("该付款计划期次已经生成采购付款单")
        supplier = _text(_get(source_snapshot, "supplier"), "供应商", 140, required=True)
        source_lines = [
            {key: _get(row, key) for key in ("item_name", "specification", "quantity", "unit", "unit_price", "remarks")}
            for row in list(_get(source_snapshot, "business_lines", []) or [])
        ]
        lines, ignored_total = _lines(source_lines)
        total = _money(_get(source_plan, "amount"))
        payment_stage = _text(_get(source_plan, "payment_stage"), "付款阶段", 20, required=True)
        prepayment_percentage = _decimal(_get(source_plan, "percentage") or 0, "预付款比例") if payment_stage == "预付款" else Decimal("0")
        has_balance_payment = 1 if any(
            _name(row) != source_payment_plan_row and _get(row, "status") == "待下推"
            for row in list(_get(source_snapshot, "payment_plan", []) or [])
        ) else 0
        if payment_stage == "预付款" and prepayment_percentage == 100:
            expected_arrival_date = expected_arrival_date or _text(_get(source_plan, "planned_date"), "预计到货日期", 10)
        # The payment request is created by procurement, but its business
        # applicant remains the employee who submitted the source request.
        # The current user remains the technical owner of the generated doc.
        identity = {
            **identity,
            "employee": _get(source_snapshot, "employee") or identity.get("employee"),
            "employee_name": _get(source_snapshot, "employee_name") or identity.get("employee_name"),
            "department": _get(source_snapshot, "department") or identity.get("department"),
            "company": _get(source_snapshot, "company") or identity.get("company"),
            "supervisor": _get(source_snapshot, "supervisor") or identity.get("supervisor"),
        }
    fulfillment = _source_fulfillment_snapshot(source_snapshot)
    source_payment_balance = (
        {"approved_amount": _money(_get(source_snapshot, "approved_amount")), "paid_amount": _money(0), "reserved_amount": _money(0), "available_amount": _money(_get(source_snapshot, "approved_amount"))}
        if source_purchase_order and source_snapshot
        else store.source_balance(source_snapshot) if source_snapshot else None
    )
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
        "source_payment_plan_row": source_payment_plan_row or None,
        "source_purchase_order": source_purchase_order or None,
        "source_po_payment_plan_row": source_po_payment_plan_row or None,
        "source_payment_plan_installment": int(_get(source_plan, "installment_no") or 0) if source_plan else 0,
        "approved_amount_snapshot": _money(_get(source_snapshot, "approved_amount")) if source_snapshot else None,
        "source_modified": _get(source_snapshot, "modified") if source_snapshot else None,
        "payment_source_kind": "关联 PO" if source_purchase_order else ("关联采购申请" if source_request else None),
        "business_lines": [] if request_type == REQUEST_DIRECT_PURCHASE else lines,
        "direct_purchase_lines": direct_lines,
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
            "source_request": _get(source, "source_request") or "",
            "source_purchase_order": _get(source, "source_purchase_order") or "",
            "source_po_payment_plan_row": _get(source, "source_po_payment_plan_row") or "",
            "supplier": _get(source, "supplier") or "",
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
