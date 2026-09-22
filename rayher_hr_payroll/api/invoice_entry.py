"""Whitelisted, bounded entry points for the invoice OCR workflow."""

from __future__ import annotations

import frappe

from rayher_hr_payroll import invoice_supplemental_attachments
from rayher_hr_payroll.oa_approval import REQUEST_EXPENSE_PAYMENT
from rayher_hr_payroll.oa_feature_gate import require_request_type_access
from rayher_hr_payroll.invoice_ocr import permissions as invoice_permissions
from rayher_hr_payroll.invoice_ocr import service


def _authenticated():
    user = str(getattr(getattr(frappe, "session", None), "user", "") or "")
    if not user or user == "Guest":
        frappe.throw("请先登录后再操作发票。", frappe.ValidationError)
    if not invoice_permissions.invoice_feature_open(user):
        require_request_type_access(REQUEST_EXPENSE_PAYMENT)


def _bounded(value, label, maximum, *, required=True):
    text = str(value or "").strip()
    if (required and not text) or len(text) > maximum or "\x00" in text:
        frappe.throw(f"{label}无效。", frappe.ValidationError)
    return text


@frappe.whitelist(methods=["POST"])
def create_batch():
    _authenticated()
    return service.create_batch()


@frappe.whitelist(methods=["POST"])
def attach_batch(batch, request, difference_note=None):
    _authenticated()
    return service.attach_batch_to_existing_request(
        _bounded(batch, "批次标识", 140),
        _bounded(request, "报销单标识", 140),
        _bounded(difference_note, "差异说明", 1000, required=False),
    )


@frappe.whitelist(methods=["POST"])
def register_file(batch, file_url):
    _authenticated()
    return service.register_file(
        _bounded(batch, "批次标识", 140),
        _bounded(file_url, "文件地址", 500),
    )


@frappe.whitelist()
def get_batch(batch):
    _authenticated()
    return service.get_batch(_bounded(batch, "批次标识", 140))


@frappe.whitelist(methods=["POST"])
def update_invoice(invoice_name, values):
    _authenticated()
    return service.update_invoice(_bounded(invoice_name, "发票标识", 140), values)


@frappe.whitelist(methods=["POST"])
def update_expense_context(invoice_name, expense_description):
    _authenticated()
    return service.update_expense_context(
        _bounded(invoice_name, "发票标识", 140),
        _bounded(
            expense_description,
            "费用说明",
            1000,
            required=False,
        ),
    )


@frappe.whitelist(methods=["POST"])
def confirm_invoice(invoice_name, values=None):
    _authenticated()
    return service.confirm_invoice(_bounded(invoice_name, "发票标识", 140), values)


@frappe.whitelist(methods=["POST"])
def list_workbench(view="mine", status=None, limit=200, include_pushed=0):
    _authenticated()
    return service.list_workbench_invoices(
        view=view,
        status=status,
        limit=limit,
        include_pushed=include_pushed,
    )


@frappe.whitelist(methods=["POST"])
def unconfirm_invoice(invoice_name, note=None):
    _authenticated()
    return service.unconfirm_invoice(
        _bounded(invoice_name, "发票标识", 140),
        _bounded(note, "操作说明", 500, required=False),
    )


@frappe.whitelist(methods=["POST"])
def retry_invoice(invoice_name):
    _authenticated()
    return service.retry_invoice(_bounded(invoice_name, "发票标识", 140))


@frappe.whitelist(methods=["POST"])
def exclude_invoice(invoice_name, reason):
    _authenticated()
    return service.exclude_invoice(
        _bounded(invoice_name, "发票标识", 140),
        _bounded(reason, "排除原因", 500),
    )


@frappe.whitelist(methods=["POST"])
def link_invoice(invoice_name, request, expense_line_key):
    _authenticated()
    return service.link_invoice(
        _bounded(invoice_name, "发票标识", 140),
        _bounded(request, "报销单标识", 140),
        _bounded(expense_line_key, "\u8d39\u7528\u660e\u7ec6\u6807\u8bc6", 140, required=False),
    )


@frappe.whitelist(methods=["POST"])
def resolve_duplicate(invoice_name, reason):
    _authenticated()
    return service.resolve_duplicate(
        _bounded(invoice_name, "发票标识", 140),
        _bounded(reason, "复核原因", 500),
    )


@frappe.whitelist()
def get_request_invoices(request):
    _authenticated()
    return service.get_request_invoices(_bounded(request, "报销单标识", 140))


@frappe.whitelist(methods=["POST"])
def preview_invoice(invoice_name):
    _authenticated()
    return service.preview_invoice(_bounded(invoice_name, "发票标识", 140))


@frappe.whitelist(methods=["POST"])
def upload_supplemental_attachment(invoice_name, file_url):
    _authenticated()
    return invoice_supplemental_attachments.register_attachment(
        _bounded(invoice_name, "发票标识", 140),
        _bounded(file_url, "文件地址", 500),
    )


@frappe.whitelist(methods=["POST"])
def delete_supplemental_attachment(invoice_name, attachment):
    _authenticated()
    return invoice_supplemental_attachments.delete_attachment(
        _bounded(invoice_name, "发票标识", 140),
        _bounded(attachment, "附件标识", 140),
    )


@frappe.whitelist(methods=["POST"])
def preview_supplemental_attachment(attachment):
    _authenticated()
    return invoice_supplemental_attachments.preview_attachment(
        _bounded(attachment, "附件标识", 140)
    )


@frappe.whitelist(methods=["POST"])
def serve_supplemental_attachment_preview(token):
    _authenticated()
    return invoice_supplemental_attachments.serve_attachment_preview(
        _bounded(token, "预览凭证", 200)
    )


@frappe.whitelist(methods=["POST"])
def serve_invoice_preview(token):
    _authenticated()
    return service.serve_invoice_preview(_bounded(token, "预览凭证", 200))
