from frappe.model.document import Document

from rayher_hr_payroll.rd_expense_accounts import (
    business_category,
    normalize_path,
    path_hash,
    validate_fixed_levels,
)


class RDExpenseAccountPath(Document):
    def validate(self):
        path = normalize_path(self.as_dict())
        errors = validate_fixed_levels(path)
        if errors:
            import frappe
            frappe.throw("；".join(errors))
        self.account_level_1, self.account_level_2, self.account_level_3, self.account_level_4 = path
        self.path_hash = path_hash(path)
        self.business_category = business_category(path)
