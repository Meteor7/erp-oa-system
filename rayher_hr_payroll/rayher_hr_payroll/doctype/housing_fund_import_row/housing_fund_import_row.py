from frappe.model.document import Document
from rayher_hr_payroll.housing_import_mutation_guard import require_housing_import_action


class HousingFundImportRow(Document):
    before_insert = require_housing_import_action
    validate = require_housing_import_action
    on_trash = require_housing_import_action
