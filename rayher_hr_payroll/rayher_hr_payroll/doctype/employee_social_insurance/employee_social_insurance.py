from frappe.model.document import Document
from rayher_hr_payroll.hr_contributions import social_insurance_amounts

class EmployeeSocialInsurance(Document):
    def validate(self):
        self.employee_period_key = f"{self.employee}|{self.period}"
        # 按档案基数 × 政策自动生成的记录：金额按政策算好（含医疗最低基数、深户地方补充养老），这里不按比例重算
        if self.flags.get("keep_amounts"):
            return
        for key, value in social_insurance_amounts(self.contribution_base, **{k: self.get(k) for k in ("employee_pension_rate","company_pension_rate","employee_medical_rate","company_medical_rate","employee_unemployment_rate","company_unemployment_rate","company_injury_rate","company_maternity_rate")}).items():
            self.set(key, float(value))
