"""Read-only execution slices linked to the original OA material line."""
from decimal import Decimal
import frappe
from rayher_hr_payroll.oa_approval import REQUEST_PROCUREMENT
from rayher_hr_payroll.oa_feature_gate import require_request_type_access
from rayher_hr_payroll.oa_access import _can_read, _active_identity
from rayher_hr_payroll.api.material_progress import can_access_board


def _quantity(value):
    return float(Decimal(str(value or 0)))


@frappe.whitelist()
def get_progress(request, source_line=None, limit=50, offset=0):
    require_request_type_access(REQUEST_PROCUREMENT)
    user = frappe.session.user
    source = frappe.get_doc("OA Approval Request", request)
    board_access = can_access_board(user)
    if user == "Guest" or source.request_type != REQUEST_PROCUREMENT or not (
        board_access or _can_read(source, user, set(frappe.get_roles(user)), _active_identity(user))
    ):
        frappe.throw("无权查看此申请的物料进度。", frappe.PermissionError)
    try:
        limit, offset = min(100, max(1, int(limit))), max(0, int(offset))
    except (ValueError, TypeError):
        frappe.throw("分页参数格式无效。")
    all_lines = list(source.business_lines or [])
    if source_line:
        all_lines = [line for line in all_lines if line.name == source_line]
    selected = all_lines[offset:offset + limit]
    keys = [line.name for line in selected]
    if not keys:
        return {"items": [], "total": len(all_lines), "has_more": False, "can_access_board": board_access}
    # All detail reads are constrained to this OA and the page's original lines.
    params = {"request": source.name, "lines": keys}
    prs = frappe.db.sql("""SELECT l.name,l.parent,l.source_line,l.quantity,l.remaining_quantity,p.status
        FROM `tabOA Procurement Request Line` l JOIN `tabOA Procurement Request` p ON p.name=l.parent
        WHERE l.source_request=%(request)s AND l.source_line IN %(lines)s
        ORDER BY p.creation,l.idx""", params, as_dict=True)
    prices = frappe.db.sql("""SELECT l.name,l.parent,l.source_line,l.source_pr_line,l.quantity,p.status
        FROM `tabOA Price Approval Line` l JOIN `tabOA Price Approval` p ON p.name=l.parent
        WHERE l.source_request=%(request)s AND l.source_line IN %(lines)s
        ORDER BY p.creation,l.idx""", params, as_dict=True)
    pos = frappe.db.sql("""SELECT l.parent,l.source_line,l.source_pr_line,l.source_price_line,l.quantity,
        l.received_quantity,l.inspection_status,l.contract_delivery_date,p.status,p.payment_status
        FROM `tabOA Purchase Order Line` l JOIN `tabOA Purchase Order` p ON p.name=l.parent
        WHERE l.source_request=%(request)s AND l.source_line IN %(lines)s
        ORDER BY p.creation,l.idx""", params, as_dict=True)
    items = []
    for line in selected:
        branches = []
        line_prs = [r for r in prs if r.source_line == line.name]
        for pr in line_prs:
            linked_prices = [r for r in prices if r.source_line == line.name and r.source_pr_line == pr.name]
            linked_pos = [r for r in pos if r.source_line == line.name and r.source_pr_line == pr.name]
            branches.append({"pr": pr.parent, "pr_line": pr.name, "quantity": _quantity(pr.quantity), "status": pr.status,
                "remaining_quantity": _quantity(pr.remaining_quantity),
                "prices": [{"name": r.parent, "quantity": _quantity(r.quantity), "status": r.status} for r in linked_prices],
                "orders": [{"name": r.parent, "quantity": _quantity(r.quantity), "received_quantity": _quantity(r.received_quantity), "inspection_status": r.inspection_status or "未验收", "delivery_date": str(r.contract_delivery_date or ""), "status": r.status, "payment_status": r.payment_status or "待付款"} for r in linked_pos]})
        active_prs = [r for r in line_prs if r.status != "已取消"]
        allocated = sum(_quantity(r.quantity) for r in active_prs)
        items.append({"source_line": line.name, "material_serial": line.material_serial or "", "item_name": line.item_name or "", "specification": line.specification or "", "quantity": _quantity(line.quantity), "unit": line.unit or "", "pr_quantity": allocated, "unallocated_quantity": max(0, _quantity(line.quantity) - allocated), "branches": branches})
    return {"request": source.name, "workflow_status": source.workflow_status, "items": items, "total": len(all_lines), "has_more": offset + len(items) < len(all_lines), "can_access_board": board_access}
