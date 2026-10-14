import frappe
from frappe.model.document import Document

SPECIAL_FIELDS = (
    "special_child_education", "special_infant_care", "special_continuing_education",
    "special_housing_loan", "special_housing_rent", "special_elderly_support",
)
MONEY_FIELDS = (
    *SPECIAL_FIELDS, "other_deduction", "opening_income", "opening_tax_free", "opening_special",
    "opening_special_additional", "opening_other", "opening_tax",
)


class EmployeeTaxProfile(Document):
    """一个员工一年的个税资料：每月专项附加扣除、其他扣除、上年不超过 6 万的规则，以及系统上线前的期初累计。"""

    def validate(self):
        if not self.year or int(self.year) < 2000:
            frappe.throw(frappe._("请填写年度。"))
        for field in MONEY_FIELDS:
            if float(self.get(field) or 0) < 0:
                frappe.throw(frappe._("金额不能为负数。"))
        if int(self.opening_months or 0) < 0 or int(self.opening_months or 0) > 12:
            frappe.throw(frappe._("期初月数要在 0 到 12 之间。"))
        period = str(self.opening_to_period or "").strip()
        if period and (len(period) != 7 or period[4] != "-" or period[:4] != str(self.year)):
            frappe.throw(frappe._("期初累计截至月份要写成 {0}-MM。").format(self.year))
        self.opening_to_period = period
        self.special_total = round(sum(float(self.get(field) or 0) for field in SPECIAL_FIELDS), 2)
        if not self.employee_name and self.employee:
            self.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name")
