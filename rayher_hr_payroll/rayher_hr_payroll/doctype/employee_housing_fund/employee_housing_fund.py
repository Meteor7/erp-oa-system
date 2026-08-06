from frappe.model.document import Document
from rayher_hr_payroll.hr_contributions import housing_fund_amounts

class EmployeeHousingFund(Document):
    def validate(self):
        self.employee_period_key = f"{self.employee}|{self.period}"
        for key, value in housing_fund_amounts(self.contribution_base, self.employee_rate, self.company_rate).items():
            self.set(key, float(value))
