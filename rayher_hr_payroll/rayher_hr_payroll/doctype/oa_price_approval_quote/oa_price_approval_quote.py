from frappe.model.document import Document
from rayher_hr_payroll.procurement_mutation_guard import require_procurement_action


class OAPriceApprovalQuote(Document):
    before_insert = require_procurement_action
    validate = require_procurement_action
    on_trash = require_procurement_action
