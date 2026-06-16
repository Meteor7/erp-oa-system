from frappe.model.document import Document

from rayher_hr_payroll.import_controls import validate_expense_import
from rayher_hr_payroll.period_controls import normalize_period_fields


class RDExpenseImport(Document):
    def before_insert(self):
        self._normalize_period()

    def validate(self):
        self._normalize_period()
        validate_expense_import(self)

    def _normalize_period(self):
        import frappe

        normalize_period_fields(self, throw=frappe.throw, translate=frappe._)
