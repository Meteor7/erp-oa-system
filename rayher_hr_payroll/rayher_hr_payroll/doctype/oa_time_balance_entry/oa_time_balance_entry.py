from frappe.model.document import Document
import frappe
from rayher_hr_payroll.oa_mutation_guard import _authorized

class OATimeBalanceEntry(Document):
    def validate(self):
        if not _authorized():
            frappe.throw("调休余额只能通过申请流程更新", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("调休余额记录不能直接删除", frappe.PermissionError)
