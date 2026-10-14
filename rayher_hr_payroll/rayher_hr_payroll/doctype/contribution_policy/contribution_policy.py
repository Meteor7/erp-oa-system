import frappe
from frappe.model.document import Document

RATE_FIELDS = (
    "medical_floor", "employee_pension_rate", "company_pension_rate", "employee_medical_rate", "company_medical_rate",
    "company_maternity_rate", "company_injury_rate", "employee_unemployment_rate", "company_unemployment_rate",
    "local_pension_rate", "fund_employee_rate", "fund_company_rate",
)


class ContributionPolicy(Document):
    """一家公司一年的社保、公积金比例（%）。薪酬按员工档案基数 × 这里的比例算社保公积金。"""

    def validate(self):
        if not self.year or int(self.year) < 2000:
            frappe.throw(frappe._("请填写年度。"))
        for field in RATE_FIELDS:
            if float(self.get(field) or 0) < 0:
                frappe.throw(frappe._("比例和基数不能为负数。"))
        for field in RATE_FIELDS[1:]:
            if float(self.get(field) or 0) > 100:
                frappe.throw(frappe._("比例按百分数填写，不能超过 100。"))
