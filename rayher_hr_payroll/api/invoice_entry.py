"""Whitelisted, bounded entry points for the invoice OCR workflow."""

from __future__ import annotations

import frappe

from rayher_hr_payroll.invoice_ocr import service


def _authenticated():
    user = str(getattr(getattr(frappe, "session", None), "user", "") or "")
    if not user or user == "Guest":
        frappe.throw("请先登录后再操作发票。", frappe.ValidationError)


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
def confirm_invoice(invoice_name, values=None):
    _authenticated()
    return service.confirm_invoice(_bounded(invoice_name, "发票标识", 140), values)


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
def serve_invoice_preview(token):
    _authenticated()
    return service.serve_invoice_preview(_bounded(token, "预览凭证", 200))
