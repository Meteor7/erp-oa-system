from frappe.model.document import Document

from rayher_hr_payroll.import_controls import validate_expense_import
from rayher_hr_payroll.period_controls import normalize_period_fields


class RDExpenseImport(Document):
    def validate(self):
        import frappe

        normalize_period_fields(self, throw=frappe.throw, translate=frappe._)
        validate_expense_import(self)
