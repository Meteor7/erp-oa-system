"""Material-level OA -> PR -> price approval -> PO workflow."""
from __future__ import annotations

import json
import hashlib
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import frappe
from rayher_hr_payroll.position_access import position_user, position_users
from frappe.utils import now_datetime

from rayher_hr_payroll.api.material_progress import _ensure_all_rows
from rayher_hr_payroll.oa_mutation_guard import authorized_oa_action
from rayher_hr_payroll.procurement_mutation_guard import procurement_action

PO_PAYMENT_PUSH_SOURCE = "PO付款下推"
PRICE_VIEW_ROLES = {"Purchase User", "Purchase Manager", "Rayher Business Executive"}
PRICE_ENTRY_ROLES = {"Purchase User", "Purchase Manager"}


def _text(value):
    return str(value or "").strip()


def _json(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _decimal(value, label="数值"):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        frappe.throw(f"{label}格式无效。")


def _flag(value):
    return 1 if value in (1, True, "1", "true", "True", "yes", "on") else 0


def _normalize_supplier_payment_plan(value, total_amount):
    rows = _json(value, [])
    if not isinstance(rows, list) or not rows:
        frappe.throw("每个供应商方案必须填写付款计划。")
    normalized, percentage_total, amount_total = [], Decimal("0"), Decimal("0")
    allowed_stages = {"预付款", "到货款", "尾款", "到货后全额付款"}
    allowed_invoices = {"付款前提供", "付款后提供", "无需发票"}
    for index, raw in enumerate(rows, 1):
        percentage = _decimal(raw.get("percentage"), f"第{index}期付款比例")
        amount = _decimal(raw.get("amount"), f"第{index}期付款金额")
        stage = _text(raw.get("payment_stage"))
        trigger = _text(raw.get("trigger_condition"))
        invoice = _text(raw.get("invoice_requirement"))
        if percentage <= 0 or amount <= 0:
            frappe.throw(f"第{index}期付款比例和金额必须大于零。")
        if stage not in allowed_stages or not trigger or invoice not in allowed_invoices:
            frappe.throw(f"第{index}期付款阶段、触发条件或发票要求无效。")
        normalized.append({
            "installment_no": index,
            "installment_name": _text(raw.get("installment_name")) or f"第{index}期",
            "payment_stage": stage,
            "percentage": float(percentage),
            "amount": float(amount),
            "planned_date": _text(raw.get("planned_date")),
            "trigger_condition": trigger,
            "invoice_requirement": invoice,
        })
        percentage_total += percentage
        amount_total += amount
    if abs(percentage_total - Decimal("100")) > Decimal("0.0001"):
        frappe.throw("付款计划比例合计必须为 100%。")
    if abs(amount_total - _decimal(total_amount)) > Decimal("0.01"):
        frappe.throw("付款计划金额合计必须等于该供应商报价总额。")
    return normalized


def _fulfillment_records(po_name):
    try:
        rows = frappe.get_all(
            "OA PO Fulfillment Record", filters={"purchase_order": po_name},
            fields=["name", "record_type", "record_date", "recorded_by", "details_json",
                    "evidence_file", "original_filename", "note", "creation"],
            order_by="creation desc", limit_page_length=500,
        )
    except Exception:
        return []
    for row in rows:
        row["details"] = _json(row.get("details_json"), [])
    return rows


def _create_fulfillment_record(po, record_type, record_date, details, file_ref, note=""):
    if not record_date:
        frappe.throw(f"请填写{record_type}日期。")
    if not _text(file_ref):
        frappe.throw(f"请先上传{record_type}资料。")
    from rayher_hr_payroll.business_documents import FrappeBusinessDocumentStore, _validate_file, _validate_file_metadata
    store = FrappeBusinessDocumentStore()
    file_doc = store.get_file(file_ref)
    _validate_file_metadata(file_doc)
    filename, content = _validate_file(file_doc, store.file_content(file_doc))
    record = frappe.get_doc({
        "doctype": "OA PO Fulfillment Record", "purchase_order": po.name,
        "record_type": record_type, "record_date": record_date, "recorded_by": _user(),
        "details_json": json.dumps(details, ensure_ascii=False),
        "evidence_file": file_doc.file_url, "original_filename": filename,
        "file_sha256": hashlib.sha256(content).hexdigest(), "note": _text(note),
    }).insert(ignore_permissions=True)
    store.link_file(file_doc, record, "Administrator")
    return record


def _user():
    return _text(frappe.session.user).lower()


def _roles():
    return set(frappe.get_roles() or [])


def _require_view():
    if _user() not in position_users("pmc", "procurement_manager", "vice_manager") and not (_roles() & PRICE_VIEW_ROLES) and "System Manager" not in _roles():
        frappe.throw("只有 PMC、采购、副总经理或系统管理员可以查看采购链路。")


def _require_po_view():
    if _user() in position_users("pmc", "procurement_manager", "vice_manager") | position_users("production_asset_owner") or "System Manager" in _roles() or _roles() & ({"Accounts User", "Finance User"} | PRICE_VIEW_ROLES):
        return
    frappe.throw("只有 PMC、采购、副总经理、生产主管或财务人员可以查看 PO。")


def _can_purchase():
    # PMC remains read-only here even when a legacy Purchase User role is assigned.
    if _user() == position_user("pmc"):
        return False
    return _user() in position_users("procurement_manager") or bool(_roles() & PRICE_ENTRY_ROLES) or "System Manager" in _roles()


def _require_purchase():
    if not _can_purchase():
        frappe.throw("只有采购或系统管理员可以操作采购单据。")


def _can_record_receipt():
    return _user() in position_users("production_asset_owner") or "System Manager" in _roles()


def _require_production_receipt():
    if not _can_record_receipt():
        frappe.throw("只有生产主管或系统管理员可以登记到货资料。")


def _require_po_payment_actor():
    roles = _roles()
    if _user() not in position_users("procurement_manager") and not (roles & {"Accounts User", "Finance User", "Purchase Manager"}) and "System Manager" not in roles:
        frappe.throw("只有采购或财务人员可以处理 PO 付款。")


def _require_pmc():
    if _user() not in position_users("pmc") and "System Manager" not in _roles():
        frappe.throw("只有 PMC 或系统管理员可以提报 PR。")


def _require_purchase_or_qingbo():
    if _user() not in position_users("procurement_manager") | {position_user("vice_manager")} and "System Manager" not in _roles():
        frappe.throw("只有采购、副总经理或系统管理员可以生成 PO。")


def _new_material_serial():
    suffix = frappe.model.naming.make_autoname("MAT-.#####").split("-")[-1]
    return f"MAT-{date.today().year}-{suffix}"


def _source_line(request_name, line_name, source=None):
    source = source or frappe.get_doc("OA Approval Request", request_name)
    line = next((row for row in (source.business_lines or []) if row.name == line_name), None)
    if not line:
        frappe.throw(f"找不到 OA {request_name} 的物料明细。")
    if not getattr(line, "material_serial", None):
        line.material_serial = _new_material_serial()
        line.db_set("material_serial", line.material_serial, update_modified=False)
    return source, line


def _available(source_request, source_line, requested, *, current=False):
    # Source OA rows serialize writers; a locking read also avoids an older
    # REPEATABLE READ snapshot after waiting for another PR to commit.
    rows = frappe.db.sql(
        "SELECT l.quantity FROM `tabOA Procurement Request Line` l "
        "JOIN `tabOA Procurement Request` p ON p.name=l.parent "
        "WHERE l.source_request=%s AND l.source_line=%s "
        "AND p.status != '已取消'" + (" FOR UPDATE" if current else ""),
        (source_request, source_line), as_dict=True,
    )
    allocated = sum((_decimal(row.get("quantity")) for row in rows), Decimal("0"))
    return max(Decimal("0"), _decimal(requested) - allocated)


def _demand_approved(source):
    business = _text(getattr(source, "business_status", None))
    workflow = _text(getattr(source, "workflow_status", None))
    return business.startswith("需求已批准") or workflow in {"已完成", "已通过", "已审批", "已结束"}


def _append_identifier(name_pair, field, value):
    board_name = frappe.db.get_value(
        "OA Material Progress",
        {"source_request": name_pair[0], "source_line": name_pair[1]}, "name",
    )
    if not board_name:
        return
    current = _text(frappe.db.get_value("OA Material Progress", board_name, field))
    values = [item.strip() for item in current.split(",") if item.strip()]
    if value not in values:
        values.append(value)
        frappe.db.set_value("OA Material Progress", board_name, field, ",".join(values), update_modified=False)


def _approval_steps(parent):
    return frappe.get_all(
        "OA Approval Step", filters={"parent": parent},
        fields=["name", "step_index", "label", "status", "approvers", "approved_by", "action_by", "acted_on", "note"],
        order_by="step_index asc, idx asc", limit_page_length=100,
    )


def _html(value):
    return (_text(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _linked_material_context(source_requests):
    rows = []
    for request_name in sorted({_text(item) for item in (source_requests or []) if _text(item)}):
        try:
            source = frappe.get_doc("OA Approval Request", request_name)
        except Exception:
            continue
        for line in getattr(source, "business_lines", []) or []:
            serial = _html(getattr(line, "material_serial", None)) or "未生成"
            code = _html(getattr(line, "material_code", None)) or "未绑定"
            item_name = _html(getattr(line, "item_name", None) or serial)
            project = _html(getattr(source, "project", None)) or "非项目"
            quantity = _html(getattr(line, "quantity", None) or 0)
            unit = _html(getattr(line, "unit", None))
            delivery = _html(getattr(source, "expected_delivery_date", None)) or "未填写"
            rows.append(f"OA {_html(source.name)} · 物料流水号 {serial} · {item_name}（{code}）· 项目 {project} · 数量 {quantity}{unit} · OA预计交期 {delivery}")
    return "<br>".join(rows[:80]) or "无可展示的物料明细"


def _notification_link(document_type, document_name):
    if document_type == "OA Material Progress":
        return f"/planck-semicon/approval/material-progress?request={_text(document_name)}"
    if document_type == "OA Procurement Request":
        return f"/planck-semicon/approval/procurement/price-approvals?view=source&pr={_text(document_name)}"
    if document_type == "OA Purchase Order":
        return f"/planck-semicon/approval/procurement/price-approvals?tab=po&po={_text(document_name)}"
    return f"/planck-semicon/approval/procurement/price-approvals?approval={_text(document_name)}"


def _notify(subject, content, document_type, document_name, source_requests=None):
    source_requests = list(source_requests or [])
    recipients = {position_user("pmc"), position_user("procurement_manager"), position_user("vice_manager")}
    for request_name in source_requests:
        try:
            source = frappe.get_doc("OA Approval Request", request_name)
        except Exception:
            continue
        for field in ("owner", "requester_user", "employee_user", "project_owner", "purchaser_user"):
            value = _text(getattr(source, field, None)).lower()
            if value and "@" in value:
                recipients.add(value)
    recipients.discard(_user())
    token = f"procurement-chain:{document_type}:{document_name}:{uuid4()}"
    detail = _linked_material_context(source_requests)
    subject_detail = detail.replace("<br>", "；").replace("<strong>", "").replace("</strong>", "")
    subject_text = f"{subject} · {subject_detail[:150]}"
    full_content = f"{content}<br><br><strong>关联物料明细</strong><br>{detail}"
    for recipient in recipients:
        if not frappe.db.exists("User", recipient):
            continue
        frappe.get_doc({
            "doctype": "Notification Log", "for_user": recipient, "type": "Alert",
            "document_type": document_type, "document_name": document_name,
            "subject": f"{subject_text} [{token}]", "email_content": full_content,
            "link": _notification_link(document_type, document_name),
        }).insert(ignore_permissions=True)
def _pr_summary(doc):
    available_line_count = sum(1 for row in (doc.lines or []) if _decimal(row.remaining_quantity) > 0)
    available_quantity = sum(_decimal(row.remaining_quantity) for row in (doc.lines or []))
    return {
        "name": doc.name, "status": doc.status or "", "requested_by": doc.requested_by or "",
        "source_projects": doc.source_projects or "", "source_count": int(doc.source_count or 0),
        "total_quantity": float(doc.total_quantity or 0),
        "available_line_count": available_line_count,
        "available_quantity": float(available_quantity),
        "can_create_price_approval": 1 if available_line_count else 0,
        "lines": [row.as_dict() for row in (doc.lines or [])], "modified": str(doc.modified or ""),
    }


def _supplier_comparisons(doc, quotes):
    line_map = {row.name: row for row in (doc.lines or [])}
    groups = {}
    for quote in quotes:
        supplier = _text(quote.supplier)
        if not supplier or quote.price_line not in line_map:
            continue
        group = groups.setdefault(supplier, {
            "supplier": supplier,
            "payment_method": _text(quote.payment_method),
            "currency": _text(quote.currency) or "CNY",
            "tax_rate": float(quote.tax_rate or 0),
            "contract_entity": _text(quote.contract_entity),
            "note": _text(quote.note),
            "payment_plan": _json(getattr(quote, "payment_plan_json", None), []),
            "is_recommended": 0,
            "is_selected": 0,
            "package_total": 0.0,
            "prices": [],
        })
        group["is_recommended"] = max(group["is_recommended"], int(quote.is_recommended or 0))
        group["package_total"] += float(quote.total_price or 0)
        group["prices"].append({
            "quote_name": quote.name,
            "price_line": quote.price_line,
            "material_serial": _text(line_map[quote.price_line].material_serial),
            "unit_price": float(quote.unit_price or 0),
            "total_price": float(quote.total_price or 0),
            "delivery_date": str(quote.delivery_date or ""),
        })
    for supplier, group in groups.items():
        group["is_selected"] = int(any(
            _text(line.selected_supplier) == supplier and line.selected_quote for line in doc.lines
        ))
        group["prices"].sort(key=lambda item: next(
            (idx for idx, line in enumerate(doc.lines) if line.name == item["price_line"]), 9999,
        ))
    return list(groups.values())


def _validate_supplier_comparisons(doc):
    quotes = frappe.get_all(
        "OA Price Approval Quote", filters={"price_approval": doc.name},
        fields=["name", "price_line", "supplier", "unit_price", "total_price", "payment_method", "currency",
                "tax_rate", "contract_entity", "is_recommended", "note", "payment_plan_json"],
        limit_page_length=2000,
    )
    valid_lines = {line.name for line in (doc.lines or [])}
    quotes = [quote for quote in quotes if quote.price_line in valid_lines and _text(quote.supplier)]
    if not quotes:
        frappe.throw("请至少录入一个供应商的有效报价。")
    for quote in quotes:
        if _decimal(quote.unit_price) <= 0:
            frappe.throw(f"物料报价单价必须大于零。")
        if not _text(quote.payment_method):
            frappe.throw(f"供应商 {quote.supplier} 的报价缺少付款方式。")
    # A supplier may quote only the lines it has actually priced. Commercial
    # conditions must remain consistent within that supplier's quoted lines.
    by_supplier = defaultdict(list)
    for quote in quotes:
        by_supplier[_text(quote.supplier)].append(quote)
    for supplier, supplier_quotes in by_supplier.items():
        conditions = {
            (_text(quote.payment_method), _text(quote.currency) or "CNY",
             float(quote.tax_rate or 0), _text(quote.contract_entity), _text(quote.note))
            for quote in supplier_quotes
        }
        if len(conditions) != 1:
            frappe.throw(f"供应商 {supplier} 的付款方式等商业条件必须保持一致。")
        plans = {_text(getattr(quote, "payment_plan_json", None)) for quote in supplier_quotes}
        if len(plans) != 1:
            frappe.throw(f"供应商 {supplier} 的付款计划必须保持一致。")
        _normalize_supplier_payment_plan(next(iter(plans)), sum(_decimal(quote.total_price) for quote in supplier_quotes))
    return quotes


def _price_summary(doc):
    quotes = frappe.get_all(
        "OA Price Approval Quote", filters={"price_approval": doc.name},
        fields=["name", "price_line", "supplier", "unit_price", "total_price", "delivery_date",
                "payment_method", "currency", "tax_rate", "contract_entity", "is_recommended", "note", "payment_plan_json"],
        order_by="creation asc", limit_page_length=2000,
    )
    source_names = sorted({_text(row.source_request) for row in (doc.lines or []) if _text(row.source_request)})
    source_docs = [frappe.get_doc("OA Approval Request", name) for name in source_names]
    projects = sorted({_text(row.project) for row in (doc.lines or []) if _text(row.project)})
    departments = sorted({_text(getattr(source, "department", None)) for source in source_docs if _text(getattr(source, "department", None))})
    requesters = sorted({_text(getattr(source, "employee_name", None)) for source in source_docs if _text(getattr(source, "employee_name", None))})
    return {
        "name": doc.name, "status": doc.status or "", "created_by": doc.created_by or "",
        "source_prs": doc.source_prs or "", "source_requests": ",".join(source_names),
        "source_projects": ",".join(projects), "source_departments": "、".join(departments),
        "source_requesters": "、".join(requesters), "summary": _text(getattr(doc, "summary", None)),
        "demand_summary": "；".join(
            f"{row.item_name or row.material_serial} {row.specification or ''} × {float(row.quantity or 0):g}{row.unit or ''}"
            for row in (doc.lines or [])
        ),
        "total_amount": float(doc.total_amount or 0),
        "lines": [row.as_dict() for row in (doc.lines or [])], "quotes": quotes,
        "supplier_comparisons": _supplier_comparisons(doc, quotes),
        "steps": _approval_steps(doc.name), "modified": str(doc.modified or ""),
        "can_select_quote": (_user() == position_user("vice_manager") or "System Manager" in _roles()) and doc.status == "待审批",
    }


def _po_summary(doc):
    result = doc.as_dict()
    result["steps"] = _approval_steps(doc.name)
    result["contract_status"] = _text(getattr(doc, "contract_status", None)) or "待补充信息"
    result["payment_plan"] = [row.as_dict() for row in (getattr(doc, "payment_plan", []) or [])]
    result["paid_amount"] = float(getattr(doc, "paid_amount", 0) or 0)
    result["outstanding_amount"] = max(0, float(doc.total_amount or 0) - result["paid_amount"])
    result["can_manage_purchase"] = 1 if _can_purchase() else 0
    result["can_record_receipt"] = 1 if _can_record_receipt() and doc.status in {"供应商制作中", "到货验收中", "付款中"} else 0
    result["can_record_inspection"] = 1 if _can_purchase() and doc.status in {"供应商制作中", "到货验收中"} else 0
    return result


def _po_payment_plan_row(po, row_name):
    row = next((item for item in (getattr(po, "payment_plan", []) or []) if item.name == _text(row_name)), None)
    if not row:
        frappe.throw("找不到 PO 付款计划期次。")
    return row


def _po_contract_ready(po):
    return _text(getattr(po, "contract_status", None)) == "已生效" and po.status not in {"草稿", "待采购确认", "待合同复核", "待电子用印", "已取消"}


@frappe.whitelist()
def list_materials_for_pr(search="", limit=500):
    _require_view()
    _ensure_all_rows()
    search = _text(search).lower()
    rows = []
    boards = frappe.get_all(
        "OA Material Progress",
        fields=["name", "source_request", "source_line", "material_serial", "project", "material_code",
                "item_name", "specification", "product_desc", "brand", "quantity", "unit", "expected_delivery_date"],
        order_by="modified desc", limit_page_length=2000,
    )
    for board in boards:
        source, line = _source_line(board.source_request, board.source_line)
        if not _demand_approved(source):
            continue
        available = _available(board.source_request, board.source_line, line.quantity)
        if available <= 0:
            continue
        payload = {
            **board, "material_serial": board.get("material_serial") or line.material_serial,
            "source_request": board.source_request, "source_line": board.source_line,
            "project": board.project or source.project or "", "quantity": float(line.quantity or 0),
            "available_quantity": float(available), "expected_delivery_date": str(source.expected_delivery_date or ""),
            "requester": source.employee_name or "",
        }
        haystack = " ".join(str(payload.get(key) or "") for key in (
            "source_request", "material_serial", "project", "material_code", "item_name", "specification", "requester"
        )).lower()
        if not search or search in haystack:
            rows.append(payload)
        if len(rows) >= min(max(int(limit or 500), 1), 2000):
            break
    return rows


@frappe.whitelist()
def list_prs(status=None, limit=200):
    _require_view()
    filters = {"status": _text(status)} if _text(status) else {}
    names = frappe.get_all("OA Procurement Request", filters=filters, fields=["name"],
                           order_by="modified desc", limit_page_length=min(max(int(limit or 200), 1), 500))
    summaries = [_pr_summary(frappe.get_doc("OA Procurement Request", row.name)) for row in names]
    return sorted(summaries, key=lambda item: 0 if item["can_create_price_approval"] else 1)


@frappe.whitelist()
def list_price_approvals(status=None, limit=200):
    _require_view()
    filters = {"status": _text(status)} if _text(status) else {}
    names = frappe.get_all("OA Price Approval", filters=filters, fields=["name"],
                           order_by="modified desc", limit_page_length=min(max(int(limit or 200), 1), 500))
    return [_price_summary(frappe.get_doc("OA Price Approval", row.name)) for row in names]


@frappe.whitelist()
def get_price_approval(name):
    _require_view()
    return _price_summary(frappe.get_doc("OA Price Approval", _text(name)))


@frappe.whitelist()
def list_purchase_orders(status=None, limit=200):
    _require_po_view()
    filters = {"status": _text(status)} if _text(status) else {}
    names = frappe.get_all("OA Purchase Order", filters=filters, fields=["name"],
                           order_by="modified desc", limit_page_length=min(max(int(limit or 200), 1), 500))
    return [_po_summary(frappe.get_doc("OA Purchase Order", row.name)) for row in names]


def _payment_work_item(po, row):
    contract_ready = _po_contract_ready(po)
    lines = list(getattr(po, "lines", []) or [])
    all_received = bool(lines) and all(
        _decimal(line.received_quantity) >= _decimal(line.quantity) for line in lines
    )
    all_inspected = bool(lines) and all(
        _text(line.inspection_status) == "已通过" for line in lines
    )
    trigger = _text(getattr(row, "trigger_condition", None))
    fulfillment_records = _fulfillment_records(po.name)
    has_receipt_evidence = any(record.get("record_type") == "到货" for record in fulfillment_records)
    has_inspection_evidence = any(record.get("record_type") == "验收" for record in fulfillment_records)
    blockers = []
    if not contract_ready:
        blockers.append("PO 合同尚未生效")
    if "到货" in trigger and not all_received:
        blockers.append("本期要求全部到货")
    if "到货" in trigger and all_received and not has_receipt_evidence:
        blockers.append("缺少到货资料")
    if "验收" in trigger:
        if not all_received:
            blockers.append("验收前需全部到货")
        if not all_inspected:
            blockers.append("本期要求验收通过")
        if all_inspected and not has_inspection_evidence:
            blockers.append("缺少验收资料")

    payment_request = _text(getattr(row, "payment_request", None))
    payment_summary = {}
    if payment_request and frappe.db.exists("OA Approval Request", payment_request):
        payment_doc = frappe.get_doc("OA Approval Request", payment_request)
        payment_summary = {
            "name": payment_doc.name,
            "workflow_status": _text(getattr(payment_doc, "workflow_status", None)),
            "business_status": _text(getattr(payment_doc, "business_status", None)),
            "current_step_index": int(getattr(payment_doc, "current_step_index", 0) or 0),
            "current_step_label": _text(getattr(payment_doc, "current_step_label", None)),
        }

    row_status = _text(getattr(row, "status", None))
    paid_amount = float(getattr(row, "paid_amount", 0) or 0)
    amount = float(getattr(row, "amount", 0) or 0)
    if row_status == "已付款" or (amount > 0 and paid_amount >= amount):
        work_status = "已付款"
    elif payment_summary:
        current_label = payment_summary.get("current_step_label", "")
        if "付款" in current_label or payment_summary.get("workflow_status") in {"已通过", "已完成"}:
            work_status = "待实际付款"
        else:
            work_status = "付款审批中"
    elif blockers:
        if not contract_ready:
            work_status = "待合同生效"
        elif any("到货" in item for item in blockers):
            work_status = "待到货资料"
        else:
            work_status = "待验收"
    else:
        work_status = "可提交付款审批"

    return {
        "key": f"{po.name}:{row.name}",
        "po": po.name,
        "payment_plan_row": row.name,
        "installment_no": int(getattr(row, "installment_no", 0) or 0),
        "installment_name": _text(getattr(row, "installment_name", None)),
        "payment_stage": _text(getattr(row, "payment_stage", None)),
        "planned_date": str(getattr(row, "planned_date", None) or ""),
        "trigger_condition": trigger,
        "invoice_requirement": _text(getattr(row, "invoice_requirement", None)),
        "percentage": float(getattr(row, "percentage", 0) or 0),
        "amount": amount,
        "paid_amount": paid_amount,
        "currency": _text(getattr(po, "currency", None)) or "CNY",
        "supplier": _text(getattr(po, "supplier", None)),
        "po_status": _text(getattr(po, "status", None)),
        "contract_status": _text(getattr(po, "contract_status", None)),
        "source_price_approvals": _text(getattr(po, "source_price_approvals", None)),
        "payment_request": payment_request,
        "payment_request_summary": payment_summary,
        "work_status": work_status,
        "blockers": blockers,
        "all_received": 1 if all_received else 0,
        "all_inspected": 1 if all_inspected else 0,
        "can_record_receipt": 1 if contract_ready and _can_record_receipt() and not all_received else 0,
        "can_record_inspection": 1 if contract_ready and _can_purchase() and any(_decimal(line.received_quantity) > 0 for line in lines) else 0,
        "can_push_payment": 1 if contract_ready and _can_purchase() and not blockers and not payment_request and row_status in {"待审批", "审批中"} else 0,
        "lines": [line.as_dict() for line in lines],
        "fulfillment_records": fulfillment_records,
    }


@frappe.whitelist()
def list_payment_work_items(limit=500):
    """Return every PO payment-plan installment, including blocked installments."""
    _require_po_view()
    limit = min(max(int(limit or 500), 1), 1000)
    names = frappe.get_all(
        "OA Purchase Order",
        filters={"status": ["not in", ["已取消"]]},
        pluck="name",
        order_by="modified desc",
        limit_page_length=limit,
    )
    result = []
    for name in names:
        po = frappe.get_doc("OA Purchase Order", name)
        for row in list(getattr(po, "payment_plan", []) or []):
            if getattr(row, "name", None):
                result.append(_payment_work_item(po, row))
    priority = {
        "可提交付款审批": 0, "待到货资料": 1, "待验收": 2,
        "付款审批中": 3, "待实际付款": 4, "待合同生效": 5, "已付款": 6,
    }
    return sorted(result, key=lambda item: (priority.get(item["work_status"], 9), item["po"], item["installment_no"]))

@frappe.whitelist(methods=["POST"])
@procurement_action
def create_pr(lines):
    _require_pmc()
    values = _json(lines, [])
    if not isinstance(values, list) or not values:
        frappe.throw("请选择至少一个物料生成 PR。")
    if any(not isinstance(row, dict) or not _text(row.get("source_request"))
           or not _text(row.get("source_line")) for row in values):
        frappe.throw("物料来源格式无效。")
    sources_locked = {
        name: frappe.get_doc("OA Approval Request", name, for_update=True)
        for name in sorted({_text(row.get("source_request")) for row in values})
    }
    doc = frappe.new_doc("OA Procurement Request")
    doc.status = "待采购"
    doc.requested_by = frappe.session.user
    projects, sources, seen = set(), set(), set()
    total = Decimal("0")
    for raw in values:
        request_name, line_name = _text(raw.get("source_request")), _text(raw.get("source_line"))
        key = (request_name, line_name)
        if key in seen:
            frappe.throw("同一 OA 物料不能在一张 PR 中重复选择。")
        seen.add(key)
        source, line = _source_line(request_name, line_name, sources_locked[request_name])
        if not _demand_approved(source):
            frappe.throw(f"OA {request_name} 需求审批尚未完成，不能生成 PR。")
        requested = _decimal(line.quantity)
        quantity = _decimal(raw.get("quantity") or requested, "本次 PR 数量")
        available = _available(request_name, line_name, requested, current=True)
        if quantity <= 0 or quantity > available:
            frappe.throw(f"物料 {line.material_serial} 可提 PR 数量为 {available}。")
        doc.append("lines", {
            "source_request": request_name, "source_line": line_name, "material_serial": line.material_serial,
            "project": _text(source.project), "material_code": _text(line.material_code or line.category_code),
            "category_code": _text(line.category_code), "item_name": _text(line.item_name),
            "specification": _text(line.specification), "product_desc": _text(line.product_desc),
            "brand": _text(line.brand), "quantity": float(quantity), "unit": _text(line.unit),
            "source_requested_quantity": float(requested), "po_quantity": 0,
            "remaining_quantity": float(quantity), "expected_delivery_date": source.expected_delivery_date,
        })
        projects.add(_text(source.project))
        sources.add(request_name)
        total += quantity
    doc.source_projects = ",".join(sorted(filter(None, projects)))
    doc.source_count = len(sources)
    doc.total_quantity = float(total)
    doc.insert(ignore_permissions=True)
    for row in doc.lines:
        _append_identifier((row.source_request, row.source_line), "pr_numbers", doc.name)
    _notify(f"PR 已生成：{doc.name}",
            f"PMC 已从 {len(sources)} 张 OA 选择 {len(doc.lines)} 项物料生成 PR，合计数量 {doc.total_quantity}。",
            "OA Procurement Request", doc.name, sources)
    frappe.db.commit()
    return _pr_summary(doc)


@frappe.whitelist(methods=["POST"])
@procurement_action
def create_price_approval(lines):
    _require_purchase()
    values = _json(lines, [])
    if not isinstance(values, list) or not values:
        frappe.throw("请选择至少一个 PR 物料生成价格审批单。")
    doc = frappe.new_doc("OA Price Approval")
    doc.status, doc.created_by = "草稿", frappe.session.user
    prs, seen = set(), set()
    locked_prs = {
        name: frappe.get_doc("OA Procurement Request", name, for_update=True)
        for name in sorted({_text(raw.get("source_pr")) for raw in values})
    }
    for raw in values:
        pr_name, pr_line_name = _text(raw.get("source_pr")), _text(raw.get("source_pr_line"))
        key = (pr_name, pr_line_name)
        if key in seen:
            frappe.throw("同一 PR 物料不能在一张价格审批单中重复选择。")
        seen.add(key)
        pr = locked_prs[pr_name]
        line = next((row for row in (pr.lines or []) if row.name == pr_line_name), None)
        if not line or _text(pr.status) in {"草稿", "Draft", "已取消", "已关闭"}:
            frappe.throw("PR 明细无效或当前不可生成价格审批单。")
        remaining = _decimal(line.remaining_quantity or 0)
        if remaining < 0 or remaining > _decimal(line.quantity) - _decimal(line.po_quantity):
            frappe.throw(f"PR {pr_name} 的剩余数量异常，请先核对。")
        quantity = _decimal(raw.get("quantity") or remaining, "本次价格审批数量")
        if quantity <= 0 or quantity > remaining:
            frappe.throw(f"PR {pr_name} 的物料 {line.material_serial} 可选数量为 {remaining}。")
        doc.append("lines", {
            "source_pr": pr_name, "source_pr_line": pr_line_name, "source_request": line.source_request,
            "source_line": line.source_line, "material_serial": line.material_serial, "project": line.project,
            "material_code": line.material_code or line.category_code, "item_name": line.item_name, "specification": line.specification,
            "product_desc": line.product_desc, "quantity": float(quantity), "unit": line.unit,
            "expected_delivery_date": line.expected_delivery_date,
        })
        line.remaining_quantity = float(remaining - quantity)
        line.save(ignore_permissions=True)
        prs.add(pr_name)
    doc.source_prs = ",".join(sorted(prs))
    doc.total_amount = 0
    doc.insert(ignore_permissions=True)
    for row in doc.lines:
        _append_identifier((row.source_request, row.source_line), "price_approval_numbers", doc.name)
    _notify(f"价格审批单已创建：{doc.name}",
            f"采购已从 {len(prs)} 张 PR 选择 {len(doc.lines)} 项物料，请按候选供应商补充实际问到的物料报价和付款方式，未问到的物料可留空。",
            "OA Price Approval", doc.name, {row.source_request for row in doc.lines})
    frappe.db.commit()
    return _price_summary(doc)


@frappe.whitelist(methods=["POST"])
@procurement_action
def save_supplier_comparison(price_approval, supplier, prices, payment_method=None,
                             currency="CNY", tax_rate=0, contract_entity=None,
                             is_recommended=0, note=None, original_supplier=None,
                             payment_plan=None):
    _require_purchase()
    approval = frappe.get_doc("OA Price Approval", _text(price_approval))
    if approval.status != "草稿":
        frappe.throw("只有草稿价格审批单可以编辑供应商报价方案。")
    supplier = _text(supplier)
    original = _text(original_supplier) or supplier
    payment_method = _text(payment_method)
    rate = _decimal(tax_rate, "税率")
    recommended = _flag(is_recommended)
    if not supplier:
        frappe.throw("供应商不能为空。")
    if not payment_method:
        frappe.throw("请填写该供应商的付款方式。")
    if rate < 0 or rate > 100:
        frappe.throw("税率必须在 0 到 100 之间。")
    values = _json(prices, [])
    if not isinstance(values, list):
        frappe.throw("物料报价格式无效。")
    value_map = {_text(item.get("price_line")): item for item in values if _text(item.get("price_line"))}
    line_map = {line.name: line for line in approval.lines}
    unknown = set(value_map) - set(line_map)
    if unknown:
        frappe.throw("报价包含不属于当前价格审批单的物料。")
    if original != supplier and frappe.db.exists("OA Price Approval Quote", {
        "price_approval": approval.name, "supplier": supplier,
    }):
        frappe.throw(f"供应商 {supplier} 已存在，请直接编辑该方案。")
    quoted_total = sum(
        _decimal(raw.get("unit_price")) * _decimal(line_map[line_name].quantity)
        for line_name, raw in value_map.items() if raw.get("unit_price") not in (None, "")
    )
    normalized_plan = _normalize_supplier_payment_plan(payment_plan, quoted_total)
    payment_plan_json = json.dumps(normalized_plan, ensure_ascii=False)
    if recommended:
        frappe.db.set_value("OA Price Approval Quote", {"price_approval": approval.name},
                            "is_recommended", 0, update_modified=False)
    for line_name, raw in value_map.items():
        line = line_map[line_name]
        raw_price = raw.get("unit_price")
        if raw_price in (None, ""):
            # Blank means this supplier did not quote this material. Remove an
            # older quote when editing so the line returns to an unquoted state.
            frappe.db.delete("OA Price Approval Quote", {"price_approval": approval.name, "price_line": line.name, "supplier": original})
            continue
        unit_price = _decimal(raw_price, f"{line.material_serial} 报价单价")
        if unit_price <= 0:
            frappe.throw(f"物料 {line.material_serial} 的报价单价必须大于零。")
        quote_name = frappe.db.get_value("OA Price Approval Quote", {
            "price_approval": approval.name, "price_line": line.name, "supplier": original,
        }, "name")
        quote = frappe.get_doc("OA Price Approval Quote", quote_name) if quote_name else frappe.new_doc("OA Price Approval Quote")
        if quote.is_new():
            quote.update({
                "price_approval": approval.name, "price_line": line.name,
                "source_pr": line.source_pr, "source_request": line.source_request,
                "material_serial": line.material_serial,
            })
        quote.update({
            "supplier": supplier, "unit_price": float(unit_price),
            "total_price": float(unit_price * _decimal(line.quantity)),
            "delivery_date": raw.get("delivery_date") or None,
            "payment_method": payment_method, "currency": _text(currency) or "CNY",
            "tax_rate": float(rate), "contract_entity": _text(contract_entity),
            "is_recommended": recommended, "note": _text(note),
            "payment_plan_json": payment_plan_json,
        })
        quote.insert(ignore_permissions=True) if quote.is_new() else quote.save(ignore_permissions=True)
    recommended_supplier = supplier if recommended else frappe.db.get_value(
        "OA Price Approval Quote", {"price_approval": approval.name, "is_recommended": 1}, "supplier"
    ) or ""
    quoted_line_names = {
        line_name for line_name, raw in value_map.items()
        if raw.get("unit_price") not in (None, "")
    }
    for line in approval.lines:
        line.recommended_supplier = recommended_supplier if line.name in quoted_line_names else ""
    approval.total_amount = float(sum(_decimal(item.selected_total) for item in approval.lines))
    approval.save(ignore_permissions=True)
    frappe.db.commit()
    _notify(
        f"供应商报价方案已更新：{approval.name}",
        f"采购已更新供应商 {_html(supplier)} 的部分报价方案；未报价物料保持空白；付款方式：{_html(payment_method)}；{'推荐供应商' if recommended else '候选供应商'}。",
        "OA Price Approval", approval.name, {line.source_request for line in approval.lines},
    )
    return _price_summary(approval)


@frappe.whitelist(methods=["POST"])
@procurement_action
def delete_supplier_comparison(price_approval, supplier):
    _require_purchase()
    approval = frappe.get_doc("OA Price Approval", _text(price_approval))
    if approval.status != "草稿":
        frappe.throw("只有草稿价格审批单可以删除供应商报价方案。")
    supplier = _text(supplier)
    if not supplier:
        frappe.throw("供应商不能为空。")
    frappe.db.delete("OA Price Approval Quote", {
        "price_approval": approval.name, "supplier": supplier,
    })
    for line in approval.lines:
        line.recommended_supplier = frappe.db.get_value(
            "OA Price Approval Quote",
            {"price_approval": approval.name, "price_line": line.name, "is_recommended": 1},
            "supplier",
        ) or ""
    approval.save(ignore_permissions=True)
    frappe.db.commit()
    return _price_summary(approval)


def _apply_supplier_selection(approval, supplier):
    supplier = _text(supplier)
    quotes = frappe.get_all(
        "OA Price Approval Quote",
        filters={"price_approval": approval.name, "supplier": supplier},
        fields=["name", "price_line", "supplier", "unit_price", "total_price", "delivery_date",
                "payment_method", "currency", "tax_rate", "contract_entity", "payment_plan_json"],
        limit_page_length=2000,
    )
    quote_map = {quote.price_line: quote for quote in quotes}
    if not quote_map:
        frappe.throw(f"供应商 {supplier} 尚未录入任何有效报价。")
    conditions = {
        (_text(quote.payment_method), _text(quote.currency) or "CNY",
         float(quote.tax_rate or 0), _text(quote.contract_entity))
        for quote in quotes
    }
    if len(conditions) != 1:
        frappe.throw(f"供应商 {supplier} 的商业条件不一致，不能选择。")
    plans = {_text(getattr(quote, "payment_plan_json", None)) for quote in quotes}
    if len(plans) != 1:
        frappe.throw(f"供应商 {supplier} 的付款计划不一致，不能选择。")
    _normalize_supplier_payment_plan(next(iter(plans)), sum(_decimal(quote.total_price) for quote in quotes))
    for line in approval.lines:
        quote = quote_map.get(line.name)
        if quote:
            line.update({
                "selected_quote": quote.name, "selected_supplier": quote.supplier,
                "selected_unit_price": quote.unit_price, "selected_total": quote.total_price,
                "selected_delivery_date": quote.delivery_date, "payment_method": quote.payment_method,
                "selected_currency": quote.currency, "selected_tax_rate": quote.tax_rate,
                "selected_contract_entity": quote.contract_entity,
            })
        else:
            line.update({
                "selected_quote": "", "selected_supplier": "", "selected_unit_price": 0,
                "selected_total": 0, "selected_delivery_date": None, "payment_method": "",
                "selected_currency": "", "selected_tax_rate": 0, "selected_contract_entity": "",
            })
    approval.total_amount = float(sum(_decimal(item.selected_total) for item in approval.lines))
    approval.save(ignore_permissions=True)
    return approval


@frappe.whitelist(methods=["POST"])
@procurement_action
def select_supplier_comparison(price_approval, supplier):
    approval = frappe.get_doc("OA Price Approval", _text(price_approval))
    if approval.status != "待审批":
        frappe.throw("只有待审批的价格审批单可以选择最终成交供应商。")
    if _user() != position_user("vice_manager") and "System Manager" not in _roles():
        frappe.throw("只有副总经理可以在价格审批阶段选择成交供应商。")
    _apply_supplier_selection(approval, supplier)
    frappe.db.commit()
    _notify(
        f"成交供应商已确认：{approval.name}",
        f"{_user()} 已为价格审批单选择成交供应商 {_html(supplier)}，当前成交金额 {_html(approval.total_amount)}。",
        "OA Price Approval", approval.name, {line.source_request for line in approval.lines},
    )
    return _price_summary(approval)


@frappe.whitelist(methods=["POST"])
@procurement_action
def save_price_quote(price_approval, price_line, supplier, unit_price, delivery_date=None,
                     payment_method=None, currency="CNY", tax_rate=0, contract_entity=None,
                     is_recommended=0, note=None, quote_name=None):
    _require_purchase()
    approval = frappe.get_doc("OA Price Approval", _text(price_approval))
    if approval.status != "草稿":
        frappe.throw("只有草稿价格审批单可以编辑报价。")
    line = next((row for row in approval.lines if row.name == _text(price_line)), None)
    if not line:
        frappe.throw("找不到价格审批物料。")
    supplier, price = _text(supplier), _decimal(unit_price, "报价单价")
    rate, recommended = _decimal(tax_rate, "税率"), _flag(is_recommended)
    if not supplier:
        frappe.throw("供应商不能为空。")
    if price <= 0:
        frappe.throw("报价单价必须大于零。")
    if rate < 0 or rate > 100:
        frappe.throw("税率必须在 0 到 100 之间。")
    if recommended:
        frappe.db.set_value("OA Price Approval Quote",
            {"price_approval": approval.name, "price_line": line.name},
            "is_recommended", 0, update_modified=False)
    if _text(quote_name):
        quote = frappe.get_doc("OA Price Approval Quote", _text(quote_name))
        if quote.price_approval != approval.name or quote.price_line != line.name:
            frappe.throw("报价不属于当前价格审批物料。")
    else:
        quote = frappe.new_doc("OA Price Approval Quote")
        quote.update({"price_approval": approval.name, "price_line": line.name,
                      "source_pr": line.source_pr, "source_request": line.source_request,
                      "material_serial": line.material_serial})
    quote.update({
        "supplier": supplier, "unit_price": float(price),
        "total_price": float(price * _decimal(line.quantity)), "delivery_date": delivery_date or None,
        "payment_method": _text(payment_method), "currency": _text(currency) or "CNY",
        "tax_rate": float(rate), "contract_entity": _text(contract_entity),
        "is_recommended": recommended, "note": _text(note),
    })
    quote.insert(ignore_permissions=True) if quote.is_new() else quote.save(ignore_permissions=True)
    if recommended:
        line.recommended_supplier = supplier
    elif line.recommended_supplier == supplier:
        line.recommended_supplier = frappe.db.get_value("OA Price Approval Quote",
            {"price_approval": approval.name, "price_line": line.name, "is_recommended": 1},
            "supplier") or ""
    if line.selected_quote == quote.name:
        line.update({
            "selected_supplier": quote.supplier, "selected_unit_price": quote.unit_price,
            "selected_total": quote.total_price, "selected_delivery_date": quote.delivery_date,
            "payment_method": quote.payment_method, "selected_currency": quote.currency,
            "selected_tax_rate": quote.tax_rate, "selected_contract_entity": quote.contract_entity,
        })
    approval.total_amount = float(sum(_decimal(item.selected_total) for item in approval.lines))
    approval.save(ignore_permissions=True)
    frappe.db.commit()
    _notify(f"采购报价已更新：{approval.name}", f"采购已录入物料 {line.material_serial} 的报价：供应商 {_html(supplier)}，报价 {_html(price)} {_html(quote.currency)}，交期 {_html(quote.delivery_date) or '未填写'}，{'推荐供应商' if recommended else '候选供应商'}。", "OA Price Approval", approval.name, {line.source_request})
    return _price_summary(approval)


@frappe.whitelist(methods=["POST"])
@procurement_action
def delete_price_quote(price_approval, price_line, quote_name):
    _require_purchase()
    approval = frappe.get_doc("OA Price Approval", _text(price_approval))
    if approval.status != "草稿":
        frappe.throw("只有草稿价格审批单可以删除报价。")
    line = next((row for row in approval.lines if row.name == _text(price_line)), None)
    quote = frappe.get_doc("OA Price Approval Quote", _text(quote_name))
    if not line or quote.price_approval != approval.name or quote.price_line != line.name:
        frappe.throw("报价不属于当前价格审批物料。")
    was_recommended, was_selected = int(quote.is_recommended or 0), line.selected_quote == quote.name
    frappe.delete_doc("OA Price Approval Quote", quote.name, ignore_permissions=True)
    if was_recommended:
        line.recommended_supplier = ""
    if was_selected:
        line.update({"selected_quote": "", "selected_supplier": "", "selected_unit_price": 0,
                     "selected_total": 0, "selected_delivery_date": None, "payment_method": "",
                     "selected_currency": "", "selected_tax_rate": 0, "selected_contract_entity": ""})
    approval.total_amount = float(sum(_decimal(item.selected_total) for item in approval.lines))
    approval.save(ignore_permissions=True)
    frappe.db.commit()
    return _price_summary(approval)


@frappe.whitelist(methods=["POST"])
@procurement_action
def select_price_quote(price_approval, price_line, quote_name):
    approval = frappe.get_doc("OA Price Approval", _text(price_approval))
    quote = frappe.get_doc("OA Price Approval Quote", _text(quote_name))
    line = next((row for row in approval.lines if row.name == _text(price_line)), None)
    if not line or quote.price_approval != approval.name or quote.price_line != line.name:
        frappe.throw("报价不属于当前价格审批物料。")
    return select_supplier_comparison(approval.name, quote.supplier)

@frappe.whitelist(methods=["POST"])
@procurement_action
def update_price_approval_summary(name, summary):
    _require_purchase()
    doc = frappe.get_doc("OA Price Approval", _text(name))
    if doc.status != "草稿":
        frappe.throw("只有草稿价格审批单可以修改总结。")
    value = _text(summary)
    if not value:
        frappe.throw("请填写采购比价总结。")
    if len(value) > 2000:
        frappe.throw("采购比价总结不能超过 2000 个字符。")
    doc.summary = value
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    _notify(f"采购比价总结已更新：{doc.name}", f"采购已更新价格审批单的比价总结：{_html(value)}", "OA Price Approval", doc.name, {row.source_request for row in doc.lines})
    return _price_summary(doc)


def _locked_pr_documents(lines):
    """Use a stable lock order for all quantity writers in this workflow."""
    return {
        name: frappe.get_doc("OA Procurement Request", name, for_update=True)
        for name in sorted({_text(line.source_pr) for line in lines if line.source_pr})
    }


def _change_reserved_pr_lines(approval, *, release, lines=None):
    """Move quantities atomically; the caller saves the approval in this transaction."""
    rows = list(approval.lines if lines is None else lines)
    prs = _locked_pr_documents(rows)
    quantities = defaultdict(Decimal)
    for row in rows:
        if not row.source_pr or not row.source_pr_line or _decimal(row.quantity) <= 0:
            frappe.throw("价格审批物料的 PR 关联或数量无效。")
        quantities[(row.source_pr, row.source_pr_line)] += _decimal(row.quantity)
    changes = []
    for (pr_name, line_name), quantity in quantities.items():
        pr = prs[pr_name]
        line = next((item for item in pr.lines if item.name == line_name), None)
        if not line:
            frappe.throw("价格审批关联的 PR 物料不存在。")
        remaining = _decimal(line.remaining_quantity)
        maximum = _decimal(line.quantity) - _decimal(line.po_quantity)
        if remaining < 0 or remaining > maximum:
            frappe.throw(f"PR {pr_name} 的剩余数量异常，请先核对。")
        if not release and (_text(pr.status) in {"草稿", "Draft", "已取消", "已关闭"} or quantity > remaining):
            frappe.throw(f"PR {pr_name} 的可用数量不足或状态不可用，请重新核对价格审批数量。")
        updated = remaining + quantity if release else remaining - quantity
        if updated < 0 or updated > maximum:
            frappe.throw(f"PR {pr_name} 的数量占用与释放不一致，请先核对。")
        changes.append((line, updated))
    for line, updated in changes:
        line.remaining_quantity = float(updated)
        line.save(ignore_permissions=True)
    return set(prs)


def _release_reserved_pr_lines(approval):
    if approval.get("pr_quantities_released"):
        return set()
    released = _change_reserved_pr_lines(approval, release=True)
    approval.pr_quantities_released = 1
    return released


def _reserve_released_pr_lines(approval):
    if not approval.get("pr_quantities_released"):
        return
    _change_reserved_pr_lines(approval, release=False)
    approval.pr_quantities_released = 0


@frappe.whitelist(methods=["POST"])
@procurement_action
def withdraw_price_approval(name, note=None):
    _require_purchase()
    doc = frappe.get_doc("OA Price Approval", _text(name), for_update=True)
    if doc.status != "待审批":
        frappe.throw("只有待副总经理审批的价格审批单可以撤回。")
    _release_reserved_pr_lines(doc)
    frappe.db.delete("OA Approval Step", {"parent": doc.name})
    doc.status = "草稿"
    for line in doc.lines:
        line.update({"selected_quote": "", "selected_supplier": "", "selected_unit_price": 0, "selected_total": 0, "payment_method": "", "selected_currency": "", "selected_tax_rate": 0, "selected_contract_entity": ""})
    doc.total_amount = 0
    doc.save(ignore_permissions=True)
    _notify(f"价格审批单已撤回：{doc.name}", f"采购已撤回价格审批单，可修改后重新提交。备注：{_html(note) or '未填写'}", "OA Price Approval", doc.name, {line.source_request for line in doc.lines})
    frappe.db.commit()
    return _price_summary(doc)


@frappe.whitelist(methods=["POST"])
@procurement_action
def cancel_price_approval(name, note=None):
    _require_purchase()
    doc = frappe.get_doc("OA Price Approval", _text(name), for_update=True)
    if doc.status not in {"草稿", "待审批"}:
        frappe.throw("只有草稿或待审批的价格审批单可以取消。")
    _release_reserved_pr_lines(doc)
    frappe.db.delete("OA Approval Step", {"parent": doc.name})
    doc.status = "已取消"
    doc.save(ignore_permissions=True)
    _notify(f"价格审批单已取消：{doc.name}", f"采购已取消价格审批单，物料数量已释放回 PR。备注：{_html(note) or '未填写'}", "OA Price Approval", doc.name, {line.source_request for line in doc.lines})
    frappe.db.commit()
    return _price_summary(doc)


@frappe.whitelist(methods=["POST"])
@procurement_action
def submit_price_approval(name):
    _require_purchase()
    doc = frappe.get_doc("OA Price Approval", _text(name), for_update=True)
    if doc.status != "草稿":
        frappe.throw("当前价格审批单不能提交。")
    if not _text(getattr(doc, "summary", None)):
        frappe.throw("提交价格审批前必须填写采购比价总结。")
    _validate_supplier_comparisons(doc)
    _reserve_released_pr_lines(doc)
    doc.status = "待审批"
    doc.save(ignore_permissions=True)
    step = frappe.new_doc("OA Approval Step")
    step.update({
        "parent": doc.name, "parentfield": "steps", "parenttype": "OA Price Approval",
        "idx": 1, "step_index": 1, "label": "价格审批：演示员工21", "mode": "approve",
        "approvers": json.dumps([position_user("vice_manager")], ensure_ascii=False), "status": "待审批",
        "approved_by": "[]", "step_key": str(uuid4()), "origin": "base",
    })
    step.insert(ignore_permissions=True)
    _notify(f"价格审批单待审批：{doc.name}",
            f"采购已提交价格审批单，金额 {doc.total_amount:.2f}，等待演示员工21审批。",
            "OA Price Approval", doc.name, {row.source_request for row in doc.lines})
    frappe.db.commit()
    return _price_summary(doc)


@frappe.whitelist(methods=["POST"])
@procurement_action
def approve_price_approval(name, note=None):
    if _user() != position_user("vice_manager") and "System Manager" not in _roles():
        frappe.throw("只有副总经理或系统管理员可以审批价格审批单。")
    doc = frappe.get_doc("OA Price Approval", _text(name), for_update=True)
    if doc.status != "待审批":
        frappe.throw("当前价格审批单不在待审批状态。")
    selected_suppliers = {_text(line.selected_supplier) for line in doc.lines if _text(line.selected_supplier) and line.selected_quote}
    if len(selected_suppliers) != 1:
        frappe.throw("请先选择一个至少有一项有效报价的最终成交供应商。")
    if any(line.selected_quote and (not line.selected_unit_price or not _text(line.payment_method)) for line in doc.lines):
        frappe.throw("已选择的报价缺少单价或付款方式。")
    _locked_pr_documents(doc.lines)
    # Only unselected quantities return to PR; selected quantities become POs.
    _change_reserved_pr_lines(doc, release=True,
                              lines=[line for line in doc.lines if not line.selected_quote])
    doc.status = "已通过"
    doc.save(ignore_permissions=True)
    frappe.db.set_value("OA Approval Step", {"parent": doc.name, "step_index": 1}, {
        "status": "已通过", "approved_by": json.dumps([frappe.session.user]),
        "action_by": frappe.session.user, "acted_on": now_datetime(), "note": _text(note),
    }, update_modified=False)
    po_names = generate_po_drafts(doc.name)
    _notify(f"价格审批已通过：{doc.name}",
            f"演示员工21已通过价格审批，系统已生成 {len(po_names)} 张 PO 草稿：{', '.join(po_names)}。",
            "OA Price Approval", doc.name, {row.source_request for row in doc.lines})
    frappe.db.commit()
    return {"price_approval": _price_summary(doc), "po_names": po_names}


@frappe.whitelist(methods=["POST"])
@procurement_action
def generate_po_drafts(price_approval):
    _require_purchase_or_qingbo()
    approval = frappe.get_doc("OA Price Approval", _text(price_approval), for_update=True)
    if approval.status not in {"已通过", "已转PO"}:
        frappe.throw("价格审批通过后才能生成 PO。")
    _locked_pr_documents(approval.lines)
    groups = defaultdict(list)
    for line in approval.lines:
        if not line.selected_supplier or not line.selected_quote or _decimal(line.selected_total) <= 0:
            continue
        key = (
            _text(line.selected_supplier), _text(line.payment_method) or "未指定",
            _text(line.selected_currency) or "CNY", str(_decimal(line.selected_tax_rate)),
            _text(line.selected_contract_entity) or "未指定",
        )
        groups[key].append(line)
    if not groups:
        frappe.throw("没有可生成 PO 的已报价物料。")
    result = []
    for (supplier, payment_method, currency, tax_rate, contract_entity), lines in groups.items():
        existing = frappe.db.get_value("OA Purchase Order", {
            "source_price_approvals": ["like", f"%{approval.name}%"], "supplier": supplier,
            "payment_method": payment_method, "currency": currency,
            "tax_rate": float(_decimal(tax_rate)), "contract_entity": contract_entity,
        }, "name")
        if existing:
            result.append(existing)
            continue
        po = frappe.new_doc("OA Purchase Order")
        po.update({
            "status": "草稿", "supplier": supplier, "payment_method": payment_method,
            "currency": currency, "tax_rate": float(_decimal(tax_rate)),
            "contract_entity": contract_entity, "source_price_approvals": approval.name,
            "paid_amount": 0, "payment_status": "待付款", "contract_status": "待补充信息",
        })
        total, dates = Decimal("0"), []
        for line in lines:
            amount = _decimal(line.selected_total)
            total += amount
            if line.selected_delivery_date:
                dates.append(line.selected_delivery_date)
            po.append("lines", {
                "source_price_approval": approval.name, "source_price_line": line.name,
                "source_pr": line.source_pr, "source_pr_line": line.source_pr_line,
                "source_request": line.source_request, "source_line": line.source_line,
                "material_serial": line.material_serial, "project": line.project,
                "material_code": line.material_code or getattr(line, "category_code", None),
                "item_name": line.item_name, "specification": line.specification,
                "quantity": line.quantity, "unit": line.unit, "unit_price": line.selected_unit_price,
                "amount": float(amount),
                "expected_delivery_date": frappe.db.get_value("OA Approval Request", line.source_request, "expected_delivery_date"),
                "contract_delivery_date": line.selected_delivery_date, "received_quantity": 0,
                "inspection_status": "未验收", "payment_status": "待付款",
            })
        po.contract_delivery_date = max(dates) if dates else None
        po.total_amount = float(total)
        selected_quote = frappe.get_doc("OA Price Approval Quote", lines[0].selected_quote)
        selected_plan = _normalize_supplier_payment_plan(
            getattr(selected_quote, "payment_plan_json", None), total
        )
        for plan in selected_plan:
            po.append("payment_plan", {
                "installment_no": plan["installment_no"],
                "installment_name": plan["installment_name"],
                "payment_stage": plan["payment_stage"],
                "percentage": plan["percentage"],
                "amount": plan["amount"],
                "planned_date": plan["planned_date"] or None,
                "trigger_condition": plan["trigger_condition"],
                "invoice_requirement": plan["invoice_requirement"],
                "status": "待生成",
                "approval_status": "未发起",
                "paid_amount": 0,
            })
        po.insert(ignore_permissions=True)
        result.append(po.name)
        for line in lines:
            pr_doc = frappe.get_doc("OA Procurement Request", line.source_pr)
            pr_line = next((item for item in pr_doc.lines if item.name == line.source_pr_line), None)
            if pr_line:
                pr_line.po_quantity = float(_decimal(pr_line.po_quantity) + _decimal(line.quantity))
                pr_line.save(ignore_permissions=True)
            _append_identifier((line.source_request, line.source_line), "po_numbers", po.name)
            frappe.db.set_value("OA Material Progress",
                {"source_request": line.source_request, "source_line": line.source_line},
                {"supplier": supplier}, update_modified=False)
        for pr_name in sorted({line.source_pr for line in lines}):
            pr_doc = frappe.get_doc("OA Procurement Request", pr_name)
            pr_doc.status = "已转PO" if all(
                _decimal(item.po_quantity) >= _decimal(item.quantity) for item in pr_doc.lines
            ) else "部分转PO"
            pr_doc.save(ignore_permissions=True)
    approval.status = "已转PO"
    approval.save(ignore_permissions=True)
    frappe.db.commit()
    return result


@frappe.whitelist(methods=["POST"])
@procurement_action
def update_po_delivery(name, lines=None):
    _require_purchase()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    if po.status not in {"草稿", "待采购确认"}:
        frappe.throw("只有 PO 草稿可以修改合同交期。")
    values = _json(lines, [])
    if not isinstance(values, list) or not values:
        frappe.throw("请提供需要更新的 PO 明细。")
    dates = []
    for raw in values:
        line = next((row for row in po.lines if row.name == _text(raw.get("line"))), None)
        if not line:
            frappe.throw("找不到 PO 明细。")
        line.contract_delivery_date = raw.get("contract_delivery_date") or None
        if line.contract_delivery_date:
            dates.append(line.contract_delivery_date)
    po.contract_delivery_date = max(dates) if dates else None
    po.save(ignore_permissions=True)
    frappe.db.commit()
    return _po_summary(po)


@frappe.whitelist(methods=["POST"])
@procurement_action
def confirm_po(name):
    _require_purchase()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    if po.status not in {"草稿", "待采购确认"}:
        frappe.throw("只有 PO 草稿可以确认。")
    if not po.supplier or not po.payment_method:
        frappe.throw("PO 缺少供应商或付款方式，不能确认。")
    if any(not line.contract_delivery_date for line in po.lines):
        frappe.throw("每条 PO 物料都必须确认合同交期。")
    po.status = "待合同复核"
    po.contract_status = "待补充信息"
    po.save(ignore_permissions=True)
    _notify(f"PO 已确认待合同复核：{po.name}",
            f"采购已确认 PO，供应商：{po.supplier}，金额：{po.total_amount:.2f}，请补充合同信息并复核用印。",
            "OA Purchase Order", po.name, {row.source_request for row in po.lines})
    frappe.db.commit()
    return _po_summary(po)


@frappe.whitelist(methods=["POST"])
@procurement_action
def save_po_contract_information(name, seal_user, contract_delivery_date=None,
                                 supplier_legal_name=None, credit_code=None,
                                 supplier_address=None, contract_contact=None,
                                 contract_bank_name=None, contract_bank_account=None,
                                 contract_template=None):
    """Create the PO contract draft after procurement confirms the PO."""
    _require_purchase()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    if po.status not in {"待合同复核", "草稿", "待采购确认"}:
        frappe.throw("当前 PO 不在合同信息补充阶段。")
    seal_user = _text(seal_user)
    if not seal_user or not frappe.db.exists("User", {"name": seal_user, "enabled": 1}):
        frappe.throw("用印账号不存在或未启用。")
    po.contract_version = int(getattr(po, "contract_version", 0) or 0) + 1
    po.contract_supplier_legal_name = _text(supplier_legal_name) or _text(po.supplier)
    po.contract_credit_code = _text(credit_code)
    po.contract_supplier_address = _text(supplier_address)
    po.contract_contact = _text(contract_contact)
    po.contract_bank_name = _text(contract_bank_name)
    po.contract_bank_account = _text(contract_bank_account)
    po.contract_entity = _text(getattr(po, "contract_entity", None)) or "示例企业032有限公司"
    po.contract_template = _text(contract_template) or "标准采购合同"
    po.contract_seal_user = seal_user
    if contract_delivery_date:
        po.contract_delivery_date = contract_delivery_date
        for line in po.lines:
            if not line.contract_delivery_date:
                line.contract_delivery_date = contract_delivery_date
    po.contract_snapshot = json.dumps({
        "po": po.name, "supplier": po.supplier, "supplier_legal_name": po.contract_supplier_legal_name,
        "contract_entity": po.contract_entity, "contract_delivery_date": str(po.contract_delivery_date or ""),
        "total_amount": float(po.total_amount or 0), "currency": po.currency or "CNY",
        "payment_method": po.payment_method or "",
    }, ensure_ascii=False)
    po.contract_draft_content = (
        f"示例企业032有限公司采购合同\nPO：{po.name}\n供应商：{po.contract_supplier_legal_name}\n"
        f"合同金额：{po.currency or 'CNY'} {float(po.total_amount or 0):,.2f}\n"
        f"合同交期：{po.contract_delivery_date or '未填写'}\n付款方式：{po.payment_method or '未填写'}"
    )
    po.contract_status = "草稿待复核"
    po.status = "待合同复核"
    po.save(ignore_permissions=True)
    _notify(f"PO 合同草稿待复核：{po.name}", "采购已生成 PO 合同草稿，请复核后进行电子用印。", "OA Purchase Order", po.name, {row.source_request for row in po.lines})
    frappe.db.commit()
    return _po_summary(po)


@frappe.whitelist(methods=["POST"])
@procurement_action
def review_po_contract(name, note=None):
    _require_purchase()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    if po.contract_status != "草稿待复核" or not po.contract_draft_content:
        frappe.throw("当前 PO 没有待复核的合同草稿。")
    po.contract_status = "待电子用印"
    po.status = "待电子用印"
    po.contract_reviewed_by = _user()
    po.contract_reviewed_on = now_datetime()
    po.save(ignore_permissions=True)
    _notify(f"PO 合同已复核：{po.name}", "PO 合同草稿已复核，等待电子用印。", "OA Purchase Order", po.name, {row.source_request for row in po.lines})
    frappe.db.commit()
    return _po_summary(po)


@frappe.whitelist(methods=["POST"])
@procurement_action
def seal_po_contract(name, note=None):
    _require_purchase()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    if po.contract_status != "待电子用印":
        frappe.throw("当前 PO 不在待电子用印状态。")
    seal_user = _text(getattr(po, "contract_seal_user", None))
    if _user() != seal_user and "System Manager" not in _roles():
        frappe.throw("当前账号不是该 PO 配置的用印账号。")
    po.contract_status = "已生效"
    po.status = "供应商制作中"
    po.contract_sealed_by = _user()
    po.contract_sealed_on = now_datetime()
    for row in (getattr(po, "payment_plan", []) or []):
        if _text(row.status) in {"", "待生成", "待下推"}:
            row.status = "待审批"
            row.approval_status = "未发起"
    po.save(ignore_permissions=True)
    _notify(f"PO 已电子用印生效：{po.name}", "PO 合同已完成电子用印，符合条件的付款期次可以发起付款审批。", "OA Purchase Order", po.name, {row.source_request for row in po.lines})
    frappe.db.commit()
    return _po_summary(po)

@frappe.whitelist(methods=["POST"])
@procurement_action
def record_po_receipt(name, lines, arrival_date=None, file_ref=None, note=None):
    _require_production_receipt()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    if po.status not in {"供应商制作中", "到货验收中", "付款中"}:
        frappe.throw("PO 合同生效并进入供应商制作后，才能登记到货资料。")
    values = _json(lines, [])
    if not isinstance(values, list) or not values:
        frappe.throw("请选择到货物料并填写本次到货数量。")
    changed = 0
    details = []
    for raw in values:
        line = next((row for row in po.lines if row.name == _text(raw.get("line"))), None)
        if not line:
            frappe.throw("找不到 PO 明细。")
        quantity = _decimal(raw.get("quantity"), "本次到货数量")
        if quantity <= 0:
            frappe.throw("本次到货数量必须大于零。")
        next_quantity = _decimal(line.received_quantity) + quantity
        if next_quantity > _decimal(line.quantity):
            frappe.throw(f"物料 {line.material_serial} 累计到货不能超过 PO 数量 {line.quantity}。")
        line.received_quantity = float(next_quantity)
        # Prior inspection records remain as evidence; new stock is uninspected.
        line.inspection_status = "待验收"
        changed += 1
        details.append({
            "line": line.name, "material_serial": _text(line.material_serial),
            "item_name": _text(line.item_name), "quantity": float(quantity), "unit": _text(line.unit),
        })
    _create_fulfillment_record(po, "到货", arrival_date, details, file_ref, note)
    po.status = "到货验收中"
    po.save(ignore_permissions=True)
    _notify(f"PO 已登记到货：{po.name}",
            f"生产主管已登记 {changed} 项物料到货，请相关人员完成验收。",
            "OA Purchase Order", po.name, {row.source_request for row in po.lines})
    frappe.db.commit()
    return _po_summary(po)


@frappe.whitelist(methods=["POST"])
@procurement_action
def record_po_inspection(name, lines, inspection_date=None, file_ref=None, note=None):
    _require_purchase()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    if po.status not in {"到货验收中", "供应商制作中"}:
        frappe.throw("当前 PO 不能登记验收。")
    values = _json(lines, [])
    allowed = {"已通过", "不合格", "退货中", "换货中"}
    if not isinstance(values, list) or not values:
        frappe.throw("请选择需要验收的物料。")
    details = []
    for raw in values:
        line = next((row for row in po.lines if row.name == _text(raw.get("line"))), None)
        status = _text(raw.get("status"))
        if not line or status not in allowed:
            frappe.throw("验收明细或验收结果无效。")
        if _decimal(line.received_quantity) <= 0:
            frappe.throw(f"物料 {line.material_serial} 尚未到货，不能验收。")
        line.inspection_status = status
        details.append({
            "line": line.name, "material_serial": _text(line.material_serial),
            "item_name": _text(line.item_name), "status": status,
            "received_quantity": float(line.received_quantity or 0), "unit": _text(line.unit),
        })
    _create_fulfillment_record(po, "验收", inspection_date, details, file_ref, note)
    all_received = all(_decimal(line.received_quantity) >= _decimal(line.quantity) for line in po.lines)
    all_passed = all(_text(line.inspection_status) == "已通过" for line in po.lines)
    po.status = "付款中" if all_received and all_passed else "到货验收中"
    po.save(ignore_permissions=True)
    _notify(f"PO 验收结果已更新：{po.name}", f"验收结果已更新，当前状态：{po.status}。",
            "OA Purchase Order", po.name, {row.source_request for row in po.lines})
    frappe.db.commit()
    return _po_summary(po)


@frappe.whitelist(methods=["POST"])
@procurement_action
def start_po_payment_approval(name, payment_plan_row):
    """Start the existing five-step payment route on a PO payment-plan row."""
    # Keep the historical endpoint aligned with the single PO -> payment OA
    # workflow.  It must not create an approval route embedded on the PO.
    return push_po_payment_request(name, payment_plan_row)

@frappe.whitelist(methods=["POST"])
@procurement_action
def push_po_payment_request(name, payment_plan_row):
    """Create the visible 采购付款 OA from a PO payment-plan row."""
    _require_purchase()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    if not _po_contract_ready(po):
        frappe.throw("PO 电子用印生效后才能下推采购付款。")
    row = _po_payment_plan_row(po, payment_plan_row)
    if _text(row.status) not in {"待审批", "审批中"} or _text(row.payment_request):
        frappe.throw("该付款期次当前不可下推，或已经生成采购付款。")
    trigger = _text(getattr(row, "trigger_condition", None))
    records = _fulfillment_records(po.name)
    if "到货" in trigger and not all(_decimal(line.received_quantity) >= _decimal(line.quantity) for line in (po.lines or [])):
        frappe.throw("该付款期次要求全部到货后才能下推。")
    if "到货" in trigger and not any(record.get("record_type") == "到货" for record in records):
        frappe.throw("该付款期次要求先上传并登记到货资料。")
    if "验收" in trigger and not all(_text(line.inspection_status) == "已通过" for line in (po.lines or [])):
        frappe.throw("该付款期次要求验收通过后才能下推。")
    if "验收" in trigger and not any(record.get("record_type") == "验收" for record in records):
        frappe.throw("该付款期次要求先上传并登记验收资料。")
    source_request = next((_text(line.source_request) for line in po.lines if _text(line.source_request)), "")
    from rayher_hr_payroll.approval_center import save_draft
    from rayher_hr_payroll.api.oa_entry import _save_document, _submit_draft, _sync_assignments_after_save
    payload = {
        "subject": f"{po.name} · {_text(row.installment_name)}",
        "reason": "由 PO 付款计划下推",
        "asset_nature": "非固定资产", "fixed_asset_category": "",
        "source_request": source_request or None,
        "source_payment_plan_row": _text(row.name),
        # source_purchase_order: po.name; source_po_payment_plan_row: _text(row.name)
        "source_purchase_order": po.name,
        "source_po_payment_plan_row": _text(row.name),
        "business_lines": [{key: getattr(line, key, None) or "" for key in ("item_name", "specification", "quantity", "unit", "unit_price", "remarks")} for line in po.lines],
        "supplier": _text(po.supplier), "payment_stage": _text(row.payment_stage),
        "prepayment_percentage": float(row.percentage or 0) if _text(row.payment_stage) == "预付款" else 0,
        "expected_arrival_date": _text(row.planned_date),
        "prepayment_risk_note": "",
    }
    payment_doc = save_draft("采购付款", payload)
    # The material lines preserve PO unit prices and totals for audit, while
    # the approval amount must be the selected installment rather than 100%
    # of the PO line total.
    payment_doc.amount = float(row.amount or 0)
    payment_doc.source_type = PO_PAYMENT_PUSH_SOURCE
    payment_doc.source_summary = f"{po.name} · {_text(row.installment_name)}"
    _submit_draft(payment_doc)
    _save_document(payment_doc)
    frappe.db.set_value("OA Approval Request", payment_doc.name, {
        "source_type": PO_PAYMENT_PUSH_SOURCE,
        "source_summary": f"{po.name} · {_text(row.installment_name)}",
    }, update_modified=False)
    _sync_assignments_after_save(payment_doc)
    row.status = "已下推"
    row.approval_status = "审批中"
    row.payment_request = payment_doc.name
    row.pushed_by = _user()
    row.pushed_on = now_datetime()
    po.save(ignore_permissions=True)
    _notify(f"PO 已下推采购付款：{po.name}", f"付款期次：{row.installment_name}，已生成采购付款 {payment_doc.name} 并进入审批流程。", "OA Purchase Order", po.name, {line.source_request for line in po.lines})
    frappe.db.commit()
    return {"payment_request": payment_doc.name, "po": _po_summary(po)}


@frappe.whitelist(methods=["POST"])
@procurement_action
def approve_po_payment_step(name, payment_plan_row, note=None):
    _require_po_payment_actor()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    row = _po_payment_plan_row(po, payment_plan_row)
    if _text(row.approval_status) != "审批中":
        frappe.throw("该付款期次当前没有进行中的审批。")
    prefix = f"{po.name} · {_text(row.installment_name)} · "
    steps = [step for step in (po.steps or []) if _text(step.label).startswith(prefix)]
    current = next((step for step in steps if _text(step.status) in {"待审批", "待处理"}), None)
    if not current:
        frappe.throw("该付款期次没有待处理的审批节点。")
    approvers = _json(current.approvers, []) or []
    if _user() not in {_text(item).lower() for item in approvers} and "System Manager" not in _roles():
        frappe.throw("当前账号不是该付款审批节点的处理人。")
    current.status = "已通过"
    current.approved_by = json.dumps([_user()], ensure_ascii=False)
    current.action_by = _user()
    current.acted_on = now_datetime()
    current.note = _text(note)
    if all(_text(step.status) == "已通过" for step in steps):
        row.approval_status = "已通过"
        row.status = "审批通过"
        row.approval_completed_by = _user()
        row.approval_completed_on = now_datetime()
        row.approval_note = _text(note)
        po.status = "付款中"
    po.save(ignore_permissions=True)
    _notify(f"PO 付款审批更新：{po.name}", f"付款期次：{row.installment_name}，当前状态：{row.status}。", "OA Purchase Order", po.name, {line.source_request for line in po.lines})
    frappe.db.commit()
    return _po_summary(po)


@frappe.whitelist(methods=["POST"])
@procurement_action
def record_po_payment(name, amount, payment_plan_row=None, payment_reference=None):
    _require_po_payment_actor()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    if po.status not in {"付款中", "到货验收中", "供应商制作中"}:
        frappe.throw("当前 PO 不能登记付款。")
    if not payment_plan_row:
        frappe.throw("请先选择 PO 付款计划期次并完成付款审批。")
    row = _po_payment_plan_row(po, payment_plan_row)
    if _text(row.approval_status) != "已通过" or _text(row.status) not in {"审批通过", "部分付款"}:
        frappe.throw("该付款期次尚未完成付款审批。")
    paid = _decimal(amount, "本次付款金额")
    if paid <= 0:
        frappe.throw("本次付款金额必须大于零。")
    row_paid = _decimal(getattr(row, "paid_amount", 0)) + paid
    if row_paid > _decimal(row.amount):
        frappe.throw("本次付款超过该期付款计划金额。")
    next_paid = _decimal(getattr(po, "paid_amount", 0)) + paid
    if next_paid > _decimal(po.total_amount):
        frappe.throw(f"累计付款不能超过 PO 总额 {po.total_amount}。")
    po.paid_amount = float(next_paid)
    po.payment_reference = _text(payment_reference)
    po.payment_status = "已付款" if next_paid >= _decimal(po.total_amount) else "部分付款"
    po.status = "付款中"
    row.paid_amount = float(row_paid)
    row.status = "已付款" if row_paid >= _decimal(row.amount) else "部分付款"
    for line in po.lines:
        line.payment_status = po.payment_status
    po.save(ignore_permissions=True)
    _notify(f"PO 付款已更新：{po.name}",
            f"本次付款 {float(paid):.2f}，累计付款 {po.paid_amount:.2f}，状态：{po.payment_status}。",
            "OA Purchase Order", po.name, {row.source_request for row in po.lines})
    frappe.db.commit()
    return _po_summary(po)


@frappe.whitelist(methods=["POST"])
@procurement_action
def close_po(name):
    _require_purchase()
    po = frappe.get_doc("OA Purchase Order", _text(name), for_update=True)
    if po.status == "已关闭":
        return _po_summary(po)
    if any(_decimal(line.received_quantity) < _decimal(line.quantity) for line in po.lines):
        frappe.throw("PO 尚未全部到货，不能关闭。")
    if any(_text(line.inspection_status) != "已通过" for line in po.lines):
        frappe.throw("PO 尚未全部验收通过，不能关闭。")
    if _decimal(getattr(po, "paid_amount", 0)) < _decimal(po.total_amount):
        frappe.throw("PO 尚未完成付款，不能关闭。")
    if any(_decimal(getattr(row, "paid_amount", 0)) < _decimal(getattr(row, "amount", 0)) for row in (getattr(po, "payment_plan", []) or [])):
        frappe.throw("PO 付款计划尚未全部完成，不能关闭。")
    po.status = "已关闭"
    po.payment_status = "已付款"
    po.save(ignore_permissions=True)
    for line in po.lines:
        frappe.db.set_value("OA Material Progress",
            {"source_request": line.source_request, "source_line": line.source_line},
            {"po_closed": 1, "actual_delivery_date": str(po.modified)[:10]}, update_modified=False)
    _notify(f"PO 已关闭：{po.name}", "到货、验收和付款均已完成，PO 已正式关闭。",
            "OA Purchase Order", po.name, {row.source_request for row in po.lines})
    frappe.db.commit()
    return _po_summary(po)

@procurement_action
def backfill_legacy_chain():
    """Fill selected quote and commercial fields for records created before this workflow revision."""
    for name in frappe.get_all("OA Price Approval", pluck="name", limit_page_length=0):
        approval = frappe.get_doc("OA Price Approval", name)
        changed = False
        for line in approval.lines:
            pr_doc = frappe.get_doc("OA Procurement Request", line.source_pr) if line.source_pr else None
            pr_line = next((row for row in (pr_doc.lines or []) if row.name == line.source_pr_line), None) if pr_doc else None
            if pr_line:
                source_updates = {
                    "material_code": pr_line.material_code,
                    "product_desc": pr_line.product_desc,
                    "expected_delivery_date": pr_line.expected_delivery_date,
                }
                for field, value in source_updates.items():
                    if not getattr(line, field, None) and value:
                        setattr(line, field, value)
                        changed = True
            quotes = frappe.get_all(
                "OA Price Approval Quote",
                filters={"price_approval": approval.name, "price_line": line.name},
                fields=["name", "supplier", "unit_price", "delivery_date", "payment_method",
                        "currency", "tax_rate", "contract_entity", "is_recommended"],
                order_by="creation asc", limit_page_length=0,
            )
            for quote in quotes:
                updates = {}
                if not quote.currency:
                    updates["currency"] = "CNY"
                if quote.tax_rate in (None, 0):
                    updates["tax_rate"] = 13
                if not quote.contract_entity:
                    updates["contract_entity"] = "示例企业032有限公司"
                if updates:
                    frappe.db.set_value("OA Price Approval Quote", quote.name, updates, update_modified=False)
                    for key, value in updates.items():
                        quote[key] = value
            recommended = next((quote for quote in quotes if int(quote.is_recommended or 0)), None)
            if recommended and line.recommended_supplier != recommended.supplier:
                line.recommended_supplier = recommended.supplier
                changed = True
            selected = next((quote for quote in quotes
                if quote.supplier == line.selected_supplier
                and abs(float(quote.unit_price or 0) - float(line.selected_unit_price or 0)) < 0.0001), None)
            if selected and not line.selected_quote:
                line.update({
                    "selected_quote": selected.name,
                    "selected_currency": selected.currency or "CNY",
                    "selected_tax_rate": selected.tax_rate or 13,
                    "selected_contract_entity": selected.contract_entity or "示例企业032有限公司",
                    "payment_method": line.payment_method or selected.payment_method,
                    "selected_delivery_date": line.selected_delivery_date or selected.delivery_date,
                })
                changed = True
        if not _text(getattr(approval, "summary", None)):
            selected_suppliers = sorted({_text(line.selected_supplier) for line in approval.lines if _text(line.selected_supplier)})
            approval.summary = (
                + ("推荐并选择：" + "、".join(selected_suppliers) + "；" if selected_suppliers else "")
                + f"成交总额为 CNY {float(approval.total_amount or 0):,.2f}。"
            )
            changed = True
        if changed:
            approval.save(ignore_permissions=True)
    for name in frappe.get_all("OA Purchase Order", pluck="name", limit_page_length=0):
        po = frappe.get_doc("OA Purchase Order", name)
        changed = False
        defaults = {
            "currency": po.currency or "CNY",
            "tax_rate": po.tax_rate or 13,
            "contract_entity": po.contract_entity or "示例企业032有限公司",
            "payment_status": po.payment_status or "待付款",
        }
        for field, value in defaults.items():
            if getattr(po, field, None) != value:
                setattr(po, field, value)
                changed = True
        if changed:
            po.save(ignore_permissions=True)
    frappe.db.commit()
    return {"price_approvals": frappe.db.count("OA Price Approval"), "purchase_orders": frappe.db.count("OA Purchase Order")}

def create_pr_ready_acceptance_data():
    """Compatibility wrapper for the formal procurement-chain seed.

    The previous implementation copied completed OA records and intentionally
    left them without PRs. Keep the callable name for old deployment commands,
    but delegate to the single formal seed so it cannot create partial data.
    """
    from rayher_hr_payroll.maintenance.procurement_test_data import seed

    return seed()
