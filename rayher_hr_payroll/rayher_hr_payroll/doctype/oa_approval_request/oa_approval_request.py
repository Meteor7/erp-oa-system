from frappe.model.document import Document

from rayher_hr_payroll.oa_mutation_guard import validate_request_mutation


class OAApprovalRequest(Document):
    def validate(self):
        validate_request_mutation(self)
