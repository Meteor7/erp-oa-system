import frappe
from frappe.model.document import Document


class OABusinessDocument(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw("业务资料只允许追加版本，不允许更新。", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("业务资料不允许删除。", frappe.PermissionError)