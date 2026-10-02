from __future__ import annotations

import json
from datetime import date

import frappe
from rayher_hr_payroll.position_access import position_users
from frappe.utils import get_datetime, getdate, now_datetime

from rayher_hr_payroll.oa_approval import REQUEST_PROCUREMENT
from rayher_hr_payroll.oa_role_resolver import resolve_role

BOARD_ROUTE = "/planck-semicon/approval/material-progress"
EDITABLE_FIELDS = {
    "material_code": "物料编号",
    "item_name": "名称",
    "specification": "规格型号",
    "product_desc": "描述",
    "project": "项目",
    "unit": "单位",
    "quantity": "数量",
    "expected_delivery_date": "交期",
    "current_handler": "当前环节人",
    "actual_delivery_date": "实际交期",
    "po_closed": "PO 是否关闭",
    "remarks": "备注",
}


def _new_material_serial():
    suffix = frappe.model.naming.make_autoname("MAT-.#####").split("-")[-1]
    return f"MAT-{date.today().year}-{suffix}"

def _clean(value):
    return str(value or "").strip()


def can_access_board(user=None):
    user = _clean(user or frappe.session.user).lower()
    return user == "administrator" or "System Manager" in set(frappe.get_roles(user)) or user in position_users("pmc", "procurement_manager", "vice_manager")


def _board_user(user=None):
    user = _clean(user or frappe.session.user).lower()
    if can_access_board(user):
        return user
    frappe.throw("只有 PMC、采购和副总经理可以访问物料进度看板。")


def _is_procurement(doc):
    return _clean(getattr(doc, "request_type", None)) == REQUEST_PROCUREMENT


def _requester_user(doc):
    employee = _clean(getattr(doc, "employee", None))
    if employee:
        user = _clean(frappe.db.get_value("Employee", employee, "user_id"))
        if user:
            return user.lower()
    return _clean(getattr(doc, "owner", None)).lower()


def _source_line_rows(doc):
    return list(getattr(doc, "business_lines", []) or [])


def _source_key(doc, line):
    return _clean(getattr(doc, "name", None)), _clean(getattr(line, "name", None))


def _ensure_row(doc, line):
    source_request, source_line = _source_key(doc, line)
    if not source_request or not source_line:
        return None
    if not _clean(getattr(line, "material_serial", None)) or "{YYYY}" in _clean(getattr(line, "material_serial", None)):
        line.material_serial = _new_material_serial()
        line.db_set("material_serial", line.material_serial, update_modified=False)
    existing = frappe.db.get_value(
        "OA Material Progress",
        {"source_request": source_request, "source_line": source_line},
        "name",
    )
    if existing:
        board = frappe.get_doc("OA Material Progress", existing)
        if not _clean(getattr(board, "material_serial", None)):
            board.db_set("material_serial", line.material_serial, update_modified=False)
        return board
    board = frappe.get_doc({
        "doctype": "OA Material Progress",
        "source_request": source_request,
        "source_line": source_line,
        "material_serial": _clean(getattr(line, "material_serial", None)),
        "requester": _clean(getattr(doc, "employee_name", None)),
        "requester_user": _requester_user(doc),
        "project": _clean(getattr(doc, "project", None)),
        "material_code": _clean(getattr(line, "material_code", None)),
        "item_name": _clean(getattr(line, "item_name", None)),
        "specification": _clean(getattr(line, "specification", None)),
        "product_desc": _clean(getattr(line, "product_desc", None)),
        "brand": _clean(getattr(line, "brand", None)),
        "quantity": getattr(line, "quantity", 0) or 0,
        "unit": _clean(getattr(line, "unit", None)),
        "expected_delivery_date": getattr(doc, "expected_delivery_date", None),
        "status": "正常",
    })
    board.insert(ignore_permissions=True)
    return board


def sync_material_progress_for_request(doc, method=None):
    """Create/update board rows after a procurement request is approved."""
    del method
    if not _is_procurement(doc) or _clean(getattr(doc, "workflow_status", None)) == "草稿":
        return
    if not frappe.db.exists("DocType", "OA Material Progress"):
        return
    for line in _source_line_rows(doc):
        _ensure_row(doc, line)


def _ensure_all_rows():
    if not frappe.db.exists("DocType", "OA Material Progress"):
        return
    # 只处理还缺看板行（或物料编号还没补上）的申请；原来每次打开页面都把所有已批准的申请逐个加载一遍，
    # 申请越多越慢。
    names = [row.get("name") for row in frappe.db.sql(
        "SELECT DISTINCT r.name FROM `tabOA Approval Request` r "
        "JOIN `tabOA Purchase Request Line` l ON l.parent = r.name AND l.parenttype = 'OA Approval Request' "
        "LEFT JOIN `tabOA Material Progress` m ON m.source_request = r.name AND m.source_line = l.name "
        "WHERE r.request_type = %s AND r.workflow_status != '草稿' "
        "AND (m.name IS NULL OR IFNULL(m.material_serial, '') = '' "
        "OR IFNULL(l.material_serial, '') = '' OR l.material_serial LIKE '%%{YYYY}%%')",
        (REQUEST_PROCUREMENT,), as_dict=True,
    )]
    for name in names:
        try:
            sync_material_progress_for_request(frappe.get_doc("OA Approval Request", name))
        except Exception:
            frappe.log_error(frappe.get_traceback(), "物料进度看板同步失败：" + str(name))


def _related_status(board, po_statuses=None, metrics=None):
    """Derive the material stage from linked PR, price approval, and PO documents."""
    if metrics is not None and metrics["po_quantity"] + 0.000001 < float(board.quantity or 0):
        return "PO处理中" if metrics["price_approval_quantity"] + 0.000001 >= float(board.quantity or 0) else "采购确认中"
    price_names = [item for item in _clean(getattr(board, "price_approval_numbers", "")).split(",") if item]
    po_names = [item for item in _clean(getattr(board, "po_numbers", "")).split(",") if item]
    if not po_names and _clean(getattr(board, "po_number", "")):
        po_names = [_clean(board.po_number)]
    if po_names:
        if po_statuses is None:
            rows = frappe.get_all("OA Purchase Order", filters={"name": ["in", po_names]}, fields=["name", "status"], limit_page_length=0)
            po_statuses = {row.name: row.status for row in rows}
        statuses = {_clean(po_statuses.get(name)) for name in po_names}
        if statuses == {"已关闭"}:
            return "已关闭"
        for candidates, stage in (({"草稿", "待确认"}, "PO处理中"), ({"已生效", "供应商制作中"}, "供应商制作中"), ({"到货验收中"}, "到货验收中"), ({"付款中"}, "付款中")):
            if statuses & candidates:
                return stage
        return "PO处理中"
    if price_names:
        return "PO处理中"
    pr_names = [item for item in _clean(getattr(board, "pr_numbers", "")).split(",") if item]
    if not pr_names and _clean(getattr(board, "pr_number", "")):
        pr_names = [_clean(board.pr_number)]
    if pr_names:
        return "采购确认中"
    return "采购确认中"


def _derived_status(board, source, po_statuses=None, metrics=None):
    if _clean(getattr(board, "status", None)) == "已取消":
        return "已取消"
    workflow = _clean(getattr(source, "workflow_status", None))
    if workflow in {"已拒绝", "已撤回"}:
        return workflow
    if workflow not in {"已完成", "已通过", "已审批", "已结束"}:
        if _clean(getattr(source, "business_status", None)).startswith("需求已批准"):
            return _related_status(board, po_statuses, metrics)
        return "OA审批中"
    return _related_status(board, po_statuses, metrics)

def _payment_rows(source):
    return list(getattr(source, "payment_plan", []) or [])


def _payment_done(source):
    rows = _payment_rows(source)
    return bool(rows) and all(_clean(getattr(row, "status", None)) == "已付款" for row in rows)


def _payment_summary(source):
    rows = _payment_rows(source)
    requests = []
    for row in rows:
        name = _clean(getattr(row, "payment_request", None))
        if name:
            requests.append({
                "name": name,
                "stage": _clean(getattr(row, "payment_stage", None)),
                "status": _clean(getattr(row, "status", None)) or "待生成",
                "amount": float(getattr(row, "amount", 0) or 0),
            })
    if not rows:
        status = "未配置付款计划"
    elif _payment_done(source):
        status = "已付款"
    elif any(_clean(getattr(row, "status", None)) in {"已付款", "已下推"} for row in rows):
        status = "部分付款"
    else:
        status = "待付款"
    return status, requests


def _active_lines(doctype, parenttype, filters, fields):
    candidates = frappe.get_all(doctype, filters=filters, pluck="parent", limit_page_length=0)
    parents = frappe.get_all(parenttype, filters={"name": ["in", sorted(set(candidates)) or ["__none__"]], "status": ["!=", "已取消"]}, pluck="name", limit_page_length=0)
    return frappe.get_all(doctype, filters={**filters, "parent": ["in", parents or ["__none__"]]}, fields=fields, limit_page_length=0)


def _chain_metrics(board):
    filters = {"source_request": board.source_request, "source_line": board.source_line}
    pr_lines = _active_lines("OA Procurement Request Line", "OA Procurement Request", filters,
        ["parent", "quantity", "remaining_quantity", "po_quantity"])
    price_lines = _active_lines("OA Price Approval Line", "OA Price Approval", filters, ["parent", "quantity"])
    po_lines = frappe.get_all(
        "OA Purchase Order Line", filters=filters,
        fields=["parent", "quantity", "received_quantity", "inspection_status", "contract_delivery_date"],
        limit_page_length=0,
    )
    po_docs = []
    for name in sorted({row.parent for row in po_lines if row.parent}):
        if frappe.db.exists("OA Purchase Order", name):
            po_docs.append(frappe.get_doc("OA Purchase Order", name))
    contract_dates = sorted({str(row.contract_delivery_date) for row in po_lines if row.contract_delivery_date})
    inspection_values = {_clean(row.inspection_status) for row in po_lines if _clean(row.inspection_status)}
    if "不合格" in inspection_values:
        inspection_status = "不合格"
    elif "退货中" in inspection_values:
        inspection_status = "退货中"
    elif "换货中" in inspection_values:
        inspection_status = "换货中"
    elif inspection_values and inspection_values == {"已通过"}:
        inspection_status = "已通过"
    elif inspection_values:
        inspection_status = "待验收"
    else:
        inspection_status = "未验收"
    paid = sum(float(getattr(po, "paid_amount", 0) or 0) for po in po_docs)
    total = sum(float(getattr(po, "total_amount", 0) or 0) for po in po_docs)
    if po_docs and total > 0 and paid >= total:
        payment_status = "已付款"
    elif paid > 0:
        payment_status = "部分付款"
    elif po_docs:
        payment_status = "待付款"
    else:
        payment_status = "未生成PO"
    return {
        "pr_quantity": sum(float(row.quantity or 0) for row in pr_lines),
        "pr_remaining_quantity": sum(float(row.remaining_quantity or 0) for row in pr_lines),
        "price_approval_quantity": sum(float(row.quantity or 0) for row in price_lines),
        "po_quantity": sum(float(row.quantity or 0) for row in po_lines),
        "received_quantity": sum(float(row.received_quantity or 0) for row in po_lines),
        "contract_delivery_date": "、".join(contract_dates),
        "inspection_status": inspection_status,
        "payment_status": payment_status,
        "paid_amount": paid,
        "po_total_amount": total,
    }


def _status_detail(board, source, metrics, approval_steps=None, po_statuses=None):
    stage = _derived_status(board, source, po_statuses, metrics)
    if stage == "OA审批中":
        pending_rows = [row for row in (approval_steps or []) if _clean(row.status) not in {"已通过", "已完成"}]
        if approval_steps is None:
            pending_rows = frappe.get_all(
                "OA Approval Step",
                filters={"parent": source.name, "status": ["not in", ["已通过", "已完成"]]},
                fields=["label"], order_by="step_index asc, idx asc", limit_page_length=1,
            )
        return (pending_rows[0].label if pending_rows else "") or "等待需求审批"
    if stage == "采购确认中":
        return "等待 PMC 提 PR" if not _clean(getattr(board, "pr_numbers", None)) else "等待采购生成价格审批单"
    if stage == "PO处理中":
        return "价格比价/审批或 PO 草稿确认"
    if stage == "供应商制作中":
        return "PO 已生效，供应商制作"
    if stage == "到货验收中":
        return f"已到货 {metrics['received_quantity']}/{float(board.quantity or 0)}，{metrics['inspection_status']}"
    if stage == "付款中":
        return metrics["payment_status"]
    if stage == "已关闭":
        return "关联 PO 均已关闭；到货、验收及付款请查看分批明细"
    return stage


def _source_approval_trail(source, steps=None):
    if steps is None:
        steps = frappe.get_all(
            "OA Approval Step", filters={"parent": source.name},
            fields=["label", "status"], order_by="step_index asc, idx asc", limit_page_length=100,
        )
    return " → ".join(
        f"{_clean(step.label)}（{_clean(step.status) or '待处理'}）" for step in steps if _clean(step.label)
    )


def _serialize(board, source=None, metrics=None, approval_steps=None, po_statuses=None):
    source = source or frappe.get_doc("OA Approval Request", board.source_request)
    metrics = metrics or _chain_metrics(board)
    payment_status, payments = _payment_summary(source)
    payment_status = metrics["payment_status"] if metrics["payment_status"] != "未生成PO" else payment_status
    return {
        "name": board.name,
        "source_request": board.source_request,
        "source_line": board.source_line,
        "material_serial": getattr(board, "material_serial", None) or "",
        "requester": board.requester or "",
        "requester_user": board.requester_user or "",
        "project": board.project or "",
        "material_code": board.material_code or "",
        "item_name": board.item_name or "",
        "specification": board.specification or "",
        "product_desc": board.product_desc or "",
        "brand": board.brand or "",
        "quantity": float(board.quantity or 0),
        "unit": board.unit or "",
        "expected_delivery_date": str(board.expected_delivery_date or ""),
        "pr_numbers": getattr(board, "pr_numbers", None) or "",
        "price_approval_numbers": getattr(board, "price_approval_numbers", None) or "",
        "po_numbers": getattr(board, "po_numbers", None) or "",
        "pr_number": getattr(board, "pr_numbers", None) or getattr(board, "pr_number", None) or "",
        "po_number": getattr(board, "po_numbers", None) or getattr(board, "po_number", None) or "",
        "supplier": board.supplier or "",
        "current_handler": board.current_handler or "",
        "actual_delivery_date": str(board.actual_delivery_date or ""),
        "po_closed": int(board.po_closed or 0),
        "remarks": board.remarks or "",
        "record_status": board.status or "正常",
        "progress_override": "",
        "progress_status": _derived_status(board, source, po_statuses, metrics),
        "business_status": _clean(getattr(source, "business_status", None)),
        "arrival_status": _clean(getattr(source, "arrival_status", None)),
        "workflow_status": _clean(getattr(source, "workflow_status", None)),
        "payment_status": payment_status,
        "payment_requests": payments,
        "pr_quantity": metrics["pr_quantity"],
        "pr_remaining_quantity": metrics["pr_remaining_quantity"],
        "price_approval_quantity": metrics["price_approval_quantity"],
        "po_quantity": metrics["po_quantity"],
        "received_quantity": metrics["received_quantity"],
        "contract_delivery_date": metrics["contract_delivery_date"],
        "inspection_status": metrics["inspection_status"],
        "paid_amount": metrics["paid_amount"],
        "po_total_amount": metrics["po_total_amount"],
        "pr_available_quantity": max(0, float(board.quantity or 0) - metrics["pr_quantity"]),
        "pr_eligible": 1 if (_clean(getattr(source, "workflow_status", None)) in {"已完成", "已通过", "已审批", "已结束"} or _clean(getattr(source, "business_status", None)).startswith("需求已批准")) and max(0, float(board.quantity or 0) - metrics["pr_quantity"]) > 0 else 0,
        "status_detail": _status_detail(board, source, metrics, approval_steps, po_statuses),
        "oa_approval_trail": _source_approval_trail(source, approval_steps),
        "request_modified": str(getattr(source, "modified", None) or ""),
        "modified": str(board.modified or ""),
    }


def _match(row, text):
    if not text:
        return True
    haystack = " ".join(str(row.get(key) or "") for key in (
        "source_request", "material_serial", "requester", "project", "material_code", "item_name", "specification",
        "brand", "pr_number", "po_number", "supplier", "current_handler", "remarks",
    )).lower()
    return text.lower() in haystack


def _batch_chain_context(boards):
    source_names = sorted({board.source_request for board in boards if board.source_request})
    keys = {(board.source_request, board.source_line) for board in boards}

    def empty_metrics():
        return {
            "pr_quantity": 0.0, "pr_remaining_quantity": 0.0,
            "price_approval_quantity": 0.0, "po_quantity": 0.0,
            "received_quantity": 0.0, "contract_dates": set(),
            "inspection_values": set(), "po_names": set(),
        }

    metrics = {key: empty_metrics() for key in keys}
    common_filters = {"source_request": ["in", source_names or ["__none__"]], "source_line": ["in", sorted({key[1] for key in keys}) or ["__none__"]]}
    pr_lines = _active_lines("OA Procurement Request Line", "OA Procurement Request", common_filters,
        ["source_request", "source_line", "quantity", "remaining_quantity"])
    price_lines = _active_lines("OA Price Approval Line", "OA Price Approval", common_filters,
        ["source_request", "source_line", "quantity"])
    po_lines = frappe.get_all(
        "OA Purchase Order Line", filters=common_filters,
        fields=["source_request", "source_line", "parent", "quantity", "received_quantity", "inspection_status", "contract_delivery_date"],
        limit_page_length=0,
    )
    for row in pr_lines:
        item = metrics.get((row.source_request, row.source_line))
        if item is not None:
            item["pr_quantity"] += float(row.quantity or 0)
            item["pr_remaining_quantity"] += float(row.remaining_quantity or 0)
    for row in price_lines:
        item = metrics.get((row.source_request, row.source_line))
        if item is not None:
            item["price_approval_quantity"] += float(row.quantity or 0)
    for row in po_lines:
        item = metrics.get((row.source_request, row.source_line))
        if item is None:
            continue
        item["po_quantity"] += float(row.quantity or 0)
        item["received_quantity"] += float(row.received_quantity or 0)
        if row.contract_delivery_date:
            item["contract_dates"].add(str(row.contract_delivery_date))
        if _clean(row.inspection_status):
            item["inspection_values"].add(_clean(row.inspection_status))
        if row.parent:
            item["po_names"].add(row.parent)

    po_names = sorted({name for item in metrics.values() for name in item["po_names"]})
    po_rows = frappe.get_all(
        "OA Purchase Order", filters={"name": ["in", po_names or ["__none__"]]},
        fields=["name", "status", "paid_amount", "total_amount"], limit_page_length=0,
    )
    po_by_name = {row.name: row for row in po_rows}
    po_statuses = {row.name: row.status for row in po_rows}
    for item in metrics.values():
        values = item.pop("inspection_values")
        if "不合格" in values:
            inspection_status = "不合格"
        elif "退货中" in values:
            inspection_status = "退货中"
        elif "换货中" in values:
            inspection_status = "换货中"
        elif values and values == {"已通过"}:
            inspection_status = "已通过"
        elif values:
            inspection_status = "待验收"
        else:
            inspection_status = "未验收"
        docs = [po_by_name[name] for name in item.pop("po_names") if name in po_by_name]
        paid = sum(float(row.paid_amount or 0) for row in docs)
        total = sum(float(row.total_amount or 0) for row in docs)
        item["contract_delivery_date"] = "、".join(sorted(item.pop("contract_dates")))
        item["inspection_status"] = inspection_status
        item["payment_status"] = "已付款" if docs and total > 0 and paid >= total else "部分付款" if paid > 0 else "待付款" if docs else "未生成PO"
        item["paid_amount"] = paid
        item["po_total_amount"] = total

    steps = frappe.get_all(
        "OA Approval Step", filters={"parent": ["in", source_names or ["__none__"]]},
        fields=["parent", "label", "status", "step_index", "idx"],
        order_by="parent asc, step_index asc, idx asc", limit_page_length=0,
    )
    steps_by_source = {name: [] for name in source_names}
    for row in steps:
        steps_by_source.setdefault(row.parent, []).append(row)
    sources = {name: frappe.get_doc("OA Approval Request", name) for name in source_names}
    return metrics, sources, steps_by_source, po_statuses


@frappe.whitelist()
def list_material_progress(search="", requester="", status="", limit=50, offset=0, source_request=""):
    _board_user()
    from rayher_hr_payroll.material_progress_query import FROM_SQL, conditions, stage_sql
    try:
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        frappe.throw("分页参数格式无效。")
    where, params = conditions(search, requester, status, source_request)
    count = frappe.db.sql(f"SELECT COUNT(*) {FROM_SQL} WHERE {where}", params)[0][0]
    params.update(limit=limit, offset=offset)
    names = frappe.db.sql(f"SELECT b.name {FROM_SQL} WHERE {where} ORDER BY b.modified DESC,b.name DESC LIMIT %(limit)s OFFSET %(offset)s", params, as_dict=True)
    boards = [frappe.get_doc("OA Material Progress", item.name) for item in names]
    result = []
    if boards:
        metrics, sources, steps_by_source, po_statuses = _batch_chain_context(boards)
        for board in boards:
            result.append(_serialize(board, source=sources[board.source_request], metrics=metrics[(board.source_request, board.source_line)], approval_steps=steps_by_source.get(board.source_request, []), po_statuses=po_statuses))
    base_where, base_params = conditions(search, requester, "", source_request)
    counts = frappe.db.sql(f"SELECT {stage_sql()} AS stage,COUNT(*) AS total {FROM_SQL} WHERE {base_where} GROUP BY stage", base_params, as_dict=True)
    people_where, people_params = conditions(source_request=source_request)
    people = frappe.db.sql(f"SELECT DISTINCT b.requester {FROM_SQL} WHERE {people_where} AND COALESCE(b.requester,'')!='' ORDER BY b.requester", people_params, as_dict=True)
    return {"total": count, "items": result, "offset": offset, "limit": limit, "has_more": offset + len(result) < count, "stage_counts": {row.stage: row.total for row in counts}, "requesters": [row.requester for row in people]}


def _recipient_users(source):
    users = []
    requester = _requester_user(source)
    # 岗位空缺时跳过该岗位，不再让整条通知失败（修复 2026-09-29，审查 #10）。
    insiders = [user for key in ("pmc", "procurement_manager", "vice_manager") for user in sorted(position_users(key))]
    for user in (requester, getattr(source, "purchaser_user", None), getattr(source, "project_owner", None), *insiders):
        value = _clean(user).lower()
        if value and value not in users:
            users.append(value)
    return users


def _notify_change(board, source, changed, actor):
    fields = []
    for key, pair in changed.items():
        label = EDITABLE_FIELDS.get(key, key)
        before = pair["before"] if pair["before"] not in (None, "") else "未填写"
        after = pair["after"] if pair["after"] not in (None, "") else "未填写"
        fields.append(f"{label}：{before} → {after}")
    content = (
        f"采购申请：{source.name}<br>物料流水号：{_clean(getattr(board, 'material_serial', None)) or '未生成'}<br>"
        f"物料：{board.item_name or board.material_code}（{_clean(getattr(board, 'material_code', None)) or '未绑定'}）<br>"
        f"项目：{_clean(getattr(board, 'project', None)) or '非项目'}<br>数量：{getattr(board, 'quantity', 0) or 0}{_clean(getattr(board, 'unit', None))}<br>"
        f"当前流程状态：{_clean(getattr(source, 'workflow_status', None)) or '未提交'}<br>修改人：{actor}<br>" + "<br>".join(fields)
    )
    key = f"material-progress:{board.name}:{board.modified}"
    subject_detail = f"{source.name} · {_clean(getattr(board, 'material_serial', None)) or '未生成'} · {board.item_name or board.material_code} · 项目 {_clean(getattr(board, 'project', None)) or '非项目'}"
    for user in _recipient_users(source):
        if user == _clean(frappe.session.user).lower():
            continue
        if frappe.db.exists("Notification Log", {"for_user": user, "document_type": "OA Material Progress", "document_name": board.name, "subject": ["like", f"%[{key}]%"]}):
            continue
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": user,
            "type": "Alert",
            "document_type": "OA Material Progress",
            "document_name": board.name,
            "subject": f"物料进度已更新：{subject_detail} [{key}]",
            "email_content": content,
            "link": f"{BOARD_ROUTE}?request={source.name}",
        }).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def update_material_progress(name, values=None, expected_modified=None):
    actor = _board_user()
    board = frappe.get_doc("OA Material Progress", _clean(name))
    if board.status == "已取消":
        frappe.throw("已取消的物料记录不能修改。")
    source = frappe.get_doc("OA Approval Request", board.source_request)
    payload = json.loads(values) if isinstance(values, str) else (values or {})
    if not isinstance(payload, dict):
        frappe.throw("修改内容格式无效。")
    if expected_modified and str(board.modified) != str(expected_modified):
        frappe.throw("这条记录已被其他人修改，请刷新后再保存。")
    changed = {}
    short_text_fields = {
        "material_code", "item_name", "specification", "project", "unit",
        "expected_delivery_date", "current_handler",
    }
    for key, label in EDITABLE_FIELDS.items():
        if key not in payload:
            continue
        value = payload.get(key)
        if key in short_text_fields:
            value = _clean(value)
            if len(value) > 140:
                frappe.throw(f"{label}不能超过140个字符。")
        elif key in {"product_desc", "remarks"}:
            value = _clean(value)
            if len(value) > 2000:
                frappe.throw(f"{label}不能超过2000个字符。")
        elif key == "actual_delivery_date":
            value = _clean(value)
            if value:
                try:
                    value = getdate(value)
                except Exception:
                    frappe.throw(f"{label}格式无效，请使用 YYYY-MM-DD。")
            else:
                value = None
        elif key == "quantity":
            try:
                value = float(value)
            except (TypeError, ValueError):
                frappe.throw("数量格式无效。")
            if value <= 0:
                frappe.throw("数量必须大于0。")
        elif key == "po_closed":
            value = 1 if value in (1, True, "1", "true", "True") else 0
        before = getattr(board, key, None)
        if str(before or "") != str(value or ""):
            changed[key] = {"before": before, "after": value}
            setattr(board, key, value)
    if not changed:
        frappe.throw("没有检测到修改。")
    board.save(ignore_permissions=True)
    _notify_change(board, source, changed, actor)
    return _serialize(board)


@frappe.whitelist(methods=["POST"])
def cancel_material_progress(name, reason=None):
    actor = _board_user()
    board = frappe.get_doc("OA Material Progress", _clean(name))
    if board.status == "已取消":
        return _serialize(board)
    reason = _clean(reason)
    if not reason:
        frappe.throw("取消物料记录必须填写原因。")
    if len(reason) > 500:
        frappe.throw("取消原因不能超过500个字符。")
    board.status = "已取消"
    board.cancel_reason = reason
    board.save(ignore_permissions=True)
    source = frappe.get_doc("OA Approval Request", board.source_request)
    _notify_change(board, source, {"status": {"before": "正常", "after": f"已取消（{reason}）"}}, actor)
    return _serialize(board)
