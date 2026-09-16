from frappe.model.document import Document

from rayher_hr_payroll.oa_mutation_guard import validate_request_mutation


class OAApprovalRequest(Document):
    def validate(self):
        validate_request_mutation(self)
        from rayher_hr_payroll.attendance_requests import validate_attendance_request
        validate_attendance_request(self)

    def on_update(self):
        from rayher_hr_payroll.attendance_requests import warn_leave_over_limit
        warn_leave_over_limit(self)

    def on_trash(self):
        from rayher_hr_payroll.attendance_requests import ATTENDANCE_TYPES, value
        import frappe
        if value(self, "request_type") in ATTENDANCE_TYPES and value(self, "workflow_status") != "草稿":
            frappe.throw("请先撤回申请再删除，避免影响工时上限和调休余额")
