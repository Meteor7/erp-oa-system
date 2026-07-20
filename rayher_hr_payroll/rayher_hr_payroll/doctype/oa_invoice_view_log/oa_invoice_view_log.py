import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


ALLOWED_ACTIONS = {"\u67e5\u770b", "\u4e0b\u8f7d"}


def _get_request_audit_values():
    request_context = getattr(frappe.local, "request", None)
    if request_context is None:
        return None, None

    headers = getattr(request_context, "headers", None)
    user_agent = headers.get("User-Agent") if headers is not None else None
    return getattr(frappe.local, "request_ip", None), user_agent


class OAInvoiceViewLog(Document):
    def before_insert(self):
        if self.action not in ALLOWED_ACTIONS:
            frappe.throw(
                _("\u53d1\u7968\u8bbf\u95ee\u52a8\u4f5c\u4ec5\u5141\u8bb8\u67e5\u770b\u6216\u4e0b\u8f7d\u3002"),
                frappe.ValidationError,
            )

        invoice_record = getattr(self, "invoice_record", None)
        if not invoice_record:
            frappe.throw(_("\u5fc5\u987b\u6307\u5b9a\u53d1\u7968\u8bb0\u5f55\u3002"), frappe.ValidationError)

        source = frappe.get_doc("OA Invoice Record", invoice_record)
        source.check_permission("read")
        ip_address, user_agent = _get_request_audit_values()
        self.invoice_file = source.invoice_file
        self.request = source.request
        self.viewed_by = frappe.session.user
        self.viewed_on = now_datetime()
        self.ip_address = ip_address
        self.user_agent = user_agent
