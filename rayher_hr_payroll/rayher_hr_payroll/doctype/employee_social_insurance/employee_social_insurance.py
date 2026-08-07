from frappe.model.document import Document
from rayher_hr_payroll.hr_contributions import social_insurance_amounts

class EmployeeSocialInsurance(Document):
    def validate(self):
        self.employee_period_key = f"{self.employee}|{self.period}"
        for key, value in social_insurance_amounts(self.contribution_base, **{k: self.get(k) for k in ("employee_pension_rate","company_pension_rate","employee_medical_rate","company_medical_rate","employee_unemployment_rate","company_unemployment_rate","company_injury_rate","company_maternity_rate")}).items():
            self.set(key, float(value))
