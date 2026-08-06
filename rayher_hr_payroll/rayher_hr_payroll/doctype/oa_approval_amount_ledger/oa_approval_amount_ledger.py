import frappe
from frappe.model.document import Document


class OAApprovalAmountLedger(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw("金额流水只允许追加，不允许更新。", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("金额流水不允许删除。", frappe.PermissionError)
