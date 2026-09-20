from frappe.model.document import Document
from rayher_hr_payroll.procurement_mutation_guard import require_procurement_child_action


class OAApprovalStep(Document):
    before_insert = require_procurement_child_action
    validate = require_procurement_child_action
    on_trash = require_procurement_child_action
