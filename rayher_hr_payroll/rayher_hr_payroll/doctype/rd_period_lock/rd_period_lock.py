from frappe.model.document import Document

from rayher_hr_payroll.period_controls import normalize_period_fields


class RDPeriodLock(Document):
    def before_insert(self):
        self._normalize_period()

    def validate(self):
        self._normalize_period()

    def _normalize_period(self):
        import frappe

        normalize_period_fields(self, throw=frappe.throw, translate=frappe._)
