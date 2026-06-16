from frappe.model.document import Document

from rayher_hr_payroll.period_controls import normalize_period_fields


class RDPeriodLock(Document):
    def validate(self):
        import frappe

        normalize_period_fields(self, throw=frappe.throw, translate=frappe._)
