import frappe
from rayher_hr_payroll.api._guards import require_hr_sensitive_access, require_rd_access, parse_period
from rayher_hr_payroll.hr_read_access import require_hr_read
from rayher_hr_payroll.hr_contributions import housing_fund_amounts, social_insurance_amounts

ROLES = ("System Manager", "HR User", "HR Manager")
SOCIAL_RATES = ("employee_pension_rate", "company_pension_rate", "employee_medical_rate", "company_medical_rate", "employee_unemployment_rate", "company_unemployment_rate", "company_injury_rate", "company_maternity_rate")

def _period(value):
    y, m = parse_period(value)
    return "%04d-%02d" % (y, m)

def _nonnegative(label, value):
    value = float(value or 0)
    if value < 0:
        frappe.throw(frappe._("{0}不能为负数。").format(label))
    return value

def _employee(employee):
    if not employee or not frappe.db.exists("Employee", employee):
        frappe.throw(frappe._("请选择有效员工。"))
    return employee

def employee_options():
    return frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", "employee_name", "default_social_insurance_base", "default_housing_fund_base"], order_by="employee_name")

@frappe.whitelist()
def get_employee_options():
    require_hr_read(ROLES, require_rd_access)
    require_hr_sensitive_access()
    return employee_options()

@frappe.whitelist()
def list_social_insurance(period):
    require_hr_read(ROLES, require_rd_access)
    require_hr_sensitive_access()
    return frappe.get_all("Employee Social Insurance", filters={"period": _period(period)}, fields=["name","period","employee","employee_name","contribution_base",*SOCIAL_RATES,"employee_pension","company_pension","employee_medical","company_medical","employee_unemployment","company_unemployment","company_injury","company_maternity","employee_total","company_total","status","remark"], order_by="employee_name")

@frappe.whitelist(methods=["POST"])
def save_social_insurance(period, employee, contribution_base=0, status="Draft", remark="", **rates):
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    period, employee = _period(period), _employee(employee)
    base = _nonnegative("缴费基数", contribution_base)
    clean_rates = {key: _nonnegative("缴费比例", rates.get(key)) for key in SOCIAL_RATES}
    amounts = {key: float(value) for key, value in social_insurance_amounts(base, **clean_rates).items()}
    values = {"period": period, "employee": employee, "employee_name": frappe.db.get_value("Employee", employee, "employee_name"), "contribution_base": base, **clean_rates, **amounts, "status": status if status in ("Draft","Confirmed") else "Draft", "remark": remark or "", "employee_period_key": f"{employee}|{period}"}
    name = frappe.db.get_value("Employee Social Insurance", {"employee_period_key": values["employee_period_key"]})
    doc = frappe.get_doc("Employee Social Insurance", name) if name else frappe.new_doc("Employee Social Insurance")
    doc.update(values)
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name, **amounts}

@frappe.whitelist()
def list_housing_fund(period):
    require_hr_read(ROLES, require_rd_access)
    require_hr_sensitive_access()
    return frappe.get_all("Employee Housing Fund", filters={"period": _period(period)}, fields=["name","period","employee","employee_name","contribution_base","employee_rate","company_rate","employee_amount","company_amount","status","remark"], order_by="employee_name")

@frappe.whitelist(methods=["POST"])
def save_housing_fund(period, employee, contribution_base=0, employee_rate=0, company_rate=0, status="Draft", remark=""):
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    period, employee = _period(period), _employee(employee)
    base = _nonnegative("缴存基数", contribution_base)
    employee_rate, company_rate = _nonnegative("个人比例", employee_rate), _nonnegative("公司比例", company_rate)
    amounts = {key: float(value) for key, value in housing_fund_amounts(base, employee_rate, company_rate).items()}
    values = {"period": period, "employee": employee, "employee_name": frappe.db.get_value("Employee", employee, "employee_name"), "contribution_base": base, "employee_rate": employee_rate, "company_rate": company_rate, **amounts, "status": status if status in ("Draft","Confirmed") else "Draft", "remark": remark or "", "employee_period_key": f"{employee}|{period}"}
    name = frappe.db.get_value("Employee Housing Fund", {"employee_period_key": values["employee_period_key"]})
    doc = frappe.get_doc("Employee Housing Fund", name) if name else frappe.new_doc("Employee Housing Fund")
    doc.update(values)
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name, **amounts}
