from frappe.model.document import Document

from rayher_hr_payroll.period_controls import normalize_period_fields


class RDPeriodLock(Document):
    def before_insert(self):
        self._normalize_period()

    def validate(self):
        self._normalize_period()

    def before_submit(self):
        import frappe

        # Stamp who locked the period and when (read-only audit fields) at the
        # moment the lock takes effect (docstatus=1).
        self.locked_by = frappe.session.user
        self.locked_on = frappe.utils.now()

    def _normalize_period(self):
        import frappe

        normalize_period_fields(self, throw=frappe.throw, translate=frappe._)
