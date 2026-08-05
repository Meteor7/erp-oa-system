import frappe

from rayher_hr_payroll.api._guards import require_rd_access
from rayher_hr_payroll.hr_contributions import HOUSEHOLD_OPTIONS, household_classification

RD_HR_WRITE = ("System Manager", "HR User", "HR Manager")
EXPENSE_ACCOUNT_CATEGORIES = ("研发费用", "管理费用", "销售费用", "生产成本")
EMPLOYEE_FIELDS = [
    "name", "company", "employee_number", "employee_name", "english_name", "date_of_birth", "gender", "date_of_joining", "relieving_date",
    "rd_personnel_type", "archive_status", "expense_account_category", "department", "designation",
    "default_monthly_salary", "salary_months", "first_education_level", "first_education_school",
    "first_education_major", "education_level_cn", "graduation_school", "major_cn", "cell_number",
    "bank_name", "bank_ac_no", "default_social_insurance_base", "default_housing_fund_base",
    "reports_to", "employment_type", "labour_contract_start_date", "probation_months",
    "probation_end_date", "first_contract_period_years", "first_contract_end_date",
    "contract_renewal_status", "second_contract_period_years", "second_contract_end_date",
    "degree_cn", "education_completion_type", "household_registration", "id_type_cn",
    "social_insurance_number", "housing_fund_number",
]


@frappe.whitelist()
def list_employees():
    require_rd_access(RD_HR_WRITE)
    fields = list(EMPLOYEE_FIELDS)
    if set(frappe.get_roles()) & {"System Manager", "HR User", "HR Manager"}:
        fields.insert(3, "id_card_number_cn")
    rows = frappe.get_all("Employee", fields=fields, order_by="employee_name")
    for row in rows:
        classification = household_classification(row.get("household_registration"))
        row["household_classification"] = (
            "深户" if classification is True else "非深户" if classification is False else "待完善"
        )
    return rows




@frappe.whitelist()
def get_household_options():
    require_rd_access(RD_HR_WRITE)
    return list(HOUSEHOLD_OPTIONS)


def _clean_household(value):
    household = str(value or "").strip()
    if household and household not in HOUSEHOLD_OPTIONS:
        frappe.throw(frappe._("户口信息必须从规定选项中选择。"))
    return household


@frappe.whitelist()
def get_company_options():
    require_rd_access(RD_HR_WRITE)
    companies = frappe.get_all("Company", fields=["name", "company_name"], order_by="company_name")
    supported = {"Rayher": "示例总部", "示例研发中心": "示例研发中心"}
    return [{**row, "display_name": supported[row["name"]]} for row in companies if row.get("name") in supported]


@frappe.whitelist()
def get_dept_options():
    require_rd_access(RD_HR_WRITE)
    return frappe.get_all("Department", filters={"is_group": 0}, fields=["name", "department_name"], order_by="department_name")


@frappe.whitelist()
def get_employment_type_options():
    require_rd_access(RD_HR_WRITE)
    return frappe.get_all("Employment Type", pluck="name", order_by="name")


@frappe.whitelist()
def get_designation_options():
    require_rd_access(RD_HR_WRITE)
    return frappe.get_all("Designation", pluck="name", order_by="name")


def _birth(idc):
    from datetime import date as _date
    idc = (idc or "").strip()
    if len(idc) == 18 and idc[6:14].isdigit():
        y, m, d = idc[6:10], idc[10:12], idc[12:14]
    elif len(idc) == 15 and idc[6:12].isdigit():
        y, m, d = "19" + idc[6:8], idc[8:10], idc[10:12]
    else:
        return None
    try:
        _date(int(y), int(m), int(d))
    except ValueError:
        return None
    return "%s-%s-%s" % (y, m, d)


def _clean_expense_category(value):
    category = (value or "").strip()
    if category and category not in EXPENSE_ACCOUNT_CATEGORIES:
        frappe.throw(frappe._("费用科目必须是研发费用、管理费用、销售费用或生产成本。"))
    return category


def _nonnegative(label, value):
    number = float(value or 0)
    if number < 0:
        frappe.throw(frappe._("{0}不能为负数。").format(label))
    return number


def _clean_salary_months(value):
    number = float(value or 0)
    if number < 0 or not number.is_integer():
        frappe.throw(frappe._("薪资月数必须是非负整数。"))
    return int(number)


def _company(value, required=False):
    company = (value or "").strip()
    if required and not company:
        frappe.throw(frappe._("请选择所属单位。"))
    if company and not frappe.db.exists("Company", company):
        frappe.throw(frappe._("请选择有效所属单位。"))
    return company or None


@frappe.whitelist(methods=["POST"])
def save_employee(
    name=None, employee_number=None, employee_name=None, company=None, english_name=None, id_card_number_cn=None, date_of_birth=None, gender=None,
    date_of_joining=None, relieving_date=None, rd_personnel_type=None, archive_status=None, department=None,
    designation=None, expense_account_category=None, default_monthly_salary=None, salary_months=None,
    first_education_level=None, first_education_school=None, first_education_major=None,
    education_level_cn=None, graduation_school=None, major_cn=None, cell_number=None, bank_name=None,
    bank_ac_no=None, default_social_insurance_base=None, default_housing_fund_base=None, reports_to=None,
    employment_type=None, labour_contract_start_date=None, probation_months=None, probation_end_date=None,
    first_contract_period_years=None, first_contract_end_date=None, contract_renewal_status=None,
    second_contract_period_years=None, second_contract_end_date=None, degree_cn=None,
    education_completion_type=None, household_registration=None, id_type_cn=None,
    social_insurance_number=None, housing_fund_number=None,
):
    require_rd_access(RD_HR_WRITE)
    provided = {
        "employee_number": employee_number,
        "employee_name": employee_name,
        "company": _company(company, required=not bool(name)) if company is not None or not name else None,
        "english_name": english_name,
        "id_card_number_cn": id_card_number_cn,
        "date_of_birth": date_of_birth,
        "gender": gender,
        "date_of_joining": date_of_joining,
        "relieving_date": relieving_date,
        "rd_personnel_type": rd_personnel_type,
        "archive_status": archive_status,
        "department": department,
        "designation": designation,
        "expense_account_category": _clean_expense_category(expense_account_category) if expense_account_category is not None else None,
        "default_monthly_salary": _nonnegative("默认月基本工资", default_monthly_salary) if default_monthly_salary is not None else None,
        "salary_months": _clean_salary_months(salary_months) if salary_months is not None else None,
        "first_education_level": first_education_level,
        "first_education_school": first_education_school,
        "first_education_major": first_education_major,
        "education_level_cn": education_level_cn,
        "graduation_school": graduation_school,
        "major_cn": major_cn,
        "cell_number": cell_number,
        "bank_name": bank_name,
        "bank_ac_no": bank_ac_no,
        "default_social_insurance_base": _nonnegative("社保基数", default_social_insurance_base) if default_social_insurance_base is not None else None,
        "default_housing_fund_base": _nonnegative("公积金基数", default_housing_fund_base) if default_housing_fund_base is not None else None,
        "reports_to": reports_to, "employment_type": employment_type,
        "labour_contract_start_date": labour_contract_start_date, "probation_months": probation_months,
        "probation_end_date": probation_end_date, "first_contract_period_years": first_contract_period_years,
        "first_contract_end_date": first_contract_end_date, "contract_renewal_status": contract_renewal_status,
        "second_contract_period_years": second_contract_period_years, "second_contract_end_date": second_contract_end_date,
        "degree_cn": degree_cn, "education_completion_type": education_completion_type,
        "household_registration": _clean_household(household_registration) if household_registration is not None else None, "id_type_cn": id_type_cn,
        "social_insurance_number": social_insurance_number, "housing_fund_number": housing_fund_number,
    }
    vals = {key: value for key, value in provided.items() if value is not None}
    if "relieving_date" in vals:
        vals["relieving_date"] = vals["relieving_date"] or None
        vals["status"] = "Left" if vals["relieving_date"] else "Active"
    if employee_name:
        vals["first_name"] = employee_name
    if not (set(frappe.get_roles()) & {"System Manager", "HR User", "HR Manager"}):
        vals.pop("id_card_number_cn", None)

    if name:
        if not frappe.has_permission("Employee", "write", doc=name):
            frappe.throw(frappe._("您无权修改该员工。"))
        doc = frappe.get_doc("Employee", name)
        doc.update(vals)
        doc.save(ignore_permissions=True)
    else:
        if not frappe.has_permission("Employee", "create"):
            frappe.throw(frappe._("您无权新增员工。"))
        company_value = vals.pop("company")
        doc = frappe.get_doc({
            "doctype": "Employee", "company": company_value,
            "status": "Left" if relieving_date else "Active", "relieving_date": relieving_date or None,
            "employee_number": employee_number,
        "employee_name": employee_name, "first_name": employee_name,
            "gender": gender or "Male", "date_of_birth": _birth(id_card_number_cn) or "1990-01-01",
            "date_of_joining": date_of_joining or frappe.utils.today(), **vals,
        })
        doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def delete_employee(name):
    require_rd_access(("System Manager", "HR Manager"))
    if not frappe.has_permission("Employee", "delete", doc=name):
        frappe.throw(frappe._("您无权删除该员工。"))
    frappe.delete_doc("Employee", name, ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}