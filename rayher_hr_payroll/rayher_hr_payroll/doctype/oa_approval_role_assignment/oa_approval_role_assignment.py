import frappe
from frappe.model.document import Document


class OAApprovalRoleAssignment(Document):
    def validate(self):
        if self.employee:
            employee = frappe.db.get_value(
                "Employee", self.employee, ["user_id", "status"], as_dict=True
            )
            if not employee or employee.user_id != self.user:
                frappe.throw("审批岗位的员工与账号必须关联同一个人")
            if self.enabled and employee.status != "Active":
                frappe.throw("启用的审批岗位必须关联在职员工")
        elif self.role_key != "hr_manager":
            frappe.throw("该审批岗位必须关联员工档案")
        if self.enabled and not frappe.db.get_value("User", self.user, "enabled"):
            frappe.throw("启用的审批岗位必须关联启用账号")
