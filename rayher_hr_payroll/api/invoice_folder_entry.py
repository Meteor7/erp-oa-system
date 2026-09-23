"""发票夹接口：列出本人发票及其发票夹状态、财务查看疑似重复。

上传、识别、修改、确认、重试、排除和解除重复沿用 api/invoice_entry.py 的接口。
"""
from __future__ import annotations

import frappe

from rayher_hr_payroll import invoice_folder as folder
from rayher_hr_payroll.invoice_ocr import permissions as invoice_permissions
from rayher_hr_payroll.invoice_ocr import service

LIST_LIMIT = 500
FIELDS = [
    "name", "batch", "recognition_status", "invoice_category", "project_name", "issue_date",
    "invoice_number", "amount_before_tax", "tax_amount", "total_amount", "expense_description",
    "request", "duplicate_of", "duplicate_reason", "processing_error", "original_filename",
    "owner", "modified",
]


def _require_access():
    user = str(frappe.session.user or "")
    if not user or user == "Guest":
        frappe.throw("请先登录后再操作发票。", frappe.PermissionError)
    if not invoice_permissions.invoice_feature_open(user):
        frappe.throw("当前审批功能暂未开放。", frappe.PermissionError)
    return user


def _requests(names):
    names = sorted({str(name or "").strip() for name in names if str(name or "").strip()})
    if not names:
        return {}
    rows = frappe.get_all(
        "OA Approval Request",
        filters={"name": ["in", names]},
        fields=["name", "request_type", "workflow_status", "business_status", "subject"],
        limit_page_length=len(names),
    )
    return {row["name"]: row for row in rows}


def _serialize(row, requests, owners=None):
    item = {key: row.get(key) for key in FIELDS if key != "owner"}
    if owners is not None:
        item["owner"] = row.get("owner")
        item["owner_name"] = owners.get(row.get("owner")) or row.get("owner")
    item["folder_status"] = folder.folder_status(row.get("recognition_status"), row.get("request"))
    linked = requests.get(row.get("request") or "")
    item["used_by"] = dict(linked) if linked else None
    return item


@frappe.whitelist()
def list_invoice_folder(status=None, include_excluded=0, view="mine"):
    """本人发票夹：每张发票的发票夹状态，以及被哪张单据使用。财务可以看全部发票（view="all"）。"""
    user = _require_access()
    finance_view = str(view or "mine").strip() == "all"
    if finance_view:
        roles = set(frappe.get_roles(user) or [])
        if user != "Administrator" and not roles & service.FINANCE_ROLES:
            frappe.throw("只有财务可以查看全部发票。", frappe.PermissionError)
    status = str(status or "").strip()
    if status and status not in folder.FOLDER_STATUSES:
        frappe.throw("发票夹状态无效。")
    rows = frappe.get_all(
        service.RECORD_DOCTYPE,
        filters={} if finance_view else {"owner": user},
        fields=FIELDS,
        order_by="modified desc",
        limit_page_length=LIST_LIMIT,
    )
    requests = _requests(row.get("request") for row in rows)
    owners = None
    if finance_view:
        owners = {
            row["name"]: row["full_name"]
            for row in frappe.get_all("User", filters={"name": ["in", sorted({row.get("owner") for row in rows if row.get("owner")}) or [""]]},
                                      fields=["name", "full_name"], limit_page_length=0)
        }
    items = [_serialize(row, requests, owners) for row in rows]
    counts = {name: 0 for name in folder.FOLDER_STATUSES}
    for item in items:
        counts[item["folder_status"]] += 1
    show_excluded = str(include_excluded or "").strip().lower() in {"1", "true", "yes"} or status == folder.FOLDER_EXCLUDED
    visible = [
        item for item in items
        if (not status or item["folder_status"] == status)
        and (show_excluded or item["folder_status"] != folder.FOLDER_EXCLUDED)
    ]
    return {"invoices": visible, "counts": counts}


@frappe.whitelist()
def list_duplicate_invoices():
    """财务：所有疑似重复的发票，以及与之重复的已确认发票。"""
    _require_access()
    roles = set(frappe.get_roles(frappe.session.user) or [])
    if frappe.session.user != "Administrator" and not roles & service.FINANCE_ROLES:
        frappe.throw("只有财务可以处理疑似重复发票。", frappe.PermissionError)
    rows = frappe.get_all(
        service.RECORD_DOCTYPE,
        filters={"recognition_status": "疑似重复"},
        fields=FIELDS,
        order_by="modified desc",
        limit_page_length=LIST_LIMIT,
    )
    originals = {
        row["name"]: row
        for row in frappe.get_all(
            service.RECORD_DOCTYPE,
            filters={"name": ["in", sorted({row.get("duplicate_of") for row in rows if row.get("duplicate_of")}) or [""]]},
            fields=FIELDS,
            limit_page_length=LIST_LIMIT,
        )
    }
    requests = _requests([row.get("request") for row in rows] + [row.get("request") for row in originals.values()])
    result = []
    for row in rows:
        item = _serialize(row, requests)
        item["uploaded_by"] = row.get("owner")
        original = originals.get(row.get("duplicate_of") or "")
        item["duplicate_original"] = _serialize(original, requests) if original else None
        result.append(item)
    return result
