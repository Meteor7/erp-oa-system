from frappe.model.document import Document

from rayher_hr_payroll.import_controls import validate_expense_import


class RDExpenseImport(Document):
    def validate(self):
        validate_expense_import(self)
