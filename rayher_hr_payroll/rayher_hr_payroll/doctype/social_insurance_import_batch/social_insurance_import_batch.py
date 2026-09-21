from frappe.model.document import Document
from rayher_hr_payroll.social_import_mutation_guard import require_social_import_action


class SocialInsuranceImportBatch(Document):
    before_insert = require_social_import_action
    validate = require_social_import_action
    on_trash = require_social_import_action
