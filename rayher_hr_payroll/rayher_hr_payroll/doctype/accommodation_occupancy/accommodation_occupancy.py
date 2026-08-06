import frappe
from frappe.model.document import Document


class AccommodationOccupancy(Document):
    def validate(self):
        self.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            frappe.throw(frappe._("退宿日期不能早于入住日期。"))
        self.is_active = 0 if self.end_date else 1
        if self.is_active and frappe.db.exists(
            "Accommodation Occupancy",
            {"employee": self.employee, "is_active": 1, "name": ["!=", self.name or ""]},
        ):
            frappe.throw(frappe._("该员工已有当前入住记录，请先办理退宿。"))
