import frappe
from frappe.utils import getdate, get_last_day

from rayher_hr_payroll.api._guards import parse_period, require_rd_access

ROLES = ("System Manager", "HR User", "HR Manager")
STRUCTURE = "标准月薪"
COMPONENTS = (
    ("基本工资", "Earning"), ("公司补贴", "Earning"), ("奖金", "Earning"), ("其他收入", "Earning"),
    ("社保个人", "Deduction"), ("公积金个人", "Deduction"), ("宿舍扣款", "Deduction"),
    ("个税", "Deduction"), ("其他扣款", "Deduction"), ("已发放", "Deduction"),
)
EMPLOYEE_PAYROLL_FIELDS = [
    "name", "employee_name", "company", "id_card_number_cn", "gender", "expense_account_category",
    "department", "designation", "date_of_joining", "relieving_date", "cell_number", "bank_name",
    "bank_ac_no", "default_monthly_salary", "holiday_list",
]
SLIP_FIELDS = [
    "name", "employee", "employee_name", "company", "department", "designation", "bank_name", "bank_account_no",
    "start_date", "end_date", "total_working_days", "payment_days", "gross_pay", "total_deduction", "net_pay",
    "docstatus", "hr_spa_managed", "hr_base_salary", "hr_salary_adjustment", "hr_adjusted_base",
    "hr_company_subsidy", "hr_bonus", "hr_other_adjustment", "hr_income_tax", "hr_advanced_paid",
    "hr_id_card_number_cn", "hr_gender", "hr_expense_account_category", "hr_date_of_joining",
    "hr_relieving_date", "hr_phone",
]


def _bounds(period):
    year, month = parse_period(period)
    start = getdate("%04d-%02d-01" % (year, month))
    return start, get_last_day(start)


def _period(period):
    year, month = parse_period(period)
    return "%04d-%02d" % (year, month)


def _as_float(value):
    return float(value or 0)


def _nonnegative(label, value):
    number = _as_float(value)
    if number < 0:
        frappe.throw(frappe._("{0}不能为负数。").format(label))
    return number


def _money(value):
    return round(_as_float(value), 2)


def _calculate_amounts(total_working_days, payment_days, base_salary, salary_adjustment, company_subsidy,
                       bonus, other_adjustment, social_insurance, housing_fund, income_tax, accommodation,
                       advanced_paid):
    total = _nonnegative("当月应计薪总天数", total_working_days)
    days = _nonnegative("计薪天数", payment_days)
    if total <= 0:
        frappe.throw(frappe._("当月应计薪总天数必须大于 0。"))
    if days > total:
        frappe.throw(frappe._("计薪天数不能超过当月应计薪总天数。"))
    base = _nonnegative("基本工资", base_salary)
    adjustment = _as_float(salary_adjustment)
    adjusted = base + adjustment
    if adjusted < 0:
        frappe.throw(frappe._("基本工资调薪后不能为负数。"))
    subsidy = _nonnegative("公司补贴", company_subsidy)
    bonus_value = _nonnegative("奖金", bonus)
    other = _as_float(other_adjustment)
    social = _nonnegative("社保个人合计", social_insurance)
    fund = _nonnegative("公积金个人", housing_fund)
    tax = _nonnegative("个人所得税", income_tax)
    dormitory = _nonnegative("宿舍代扣", accommodation)
    advanced = _nonnegative("已发放金额", advanced_paid)
    prorated = adjusted * days / total
    payable = prorated + subsidy + bonus_value + other
    deductions = social + fund + tax + dormitory + advanced
    return {
        "adjusted_base": _money(adjusted),
        "prorated_base": _money(prorated),
        "payable_salary": _money(payable),
        "total_deduction": _money(deductions),
        "net_pay": _money(payable - deductions),
    }


def _period_employee_filters(start, end):
    return (
        {"date_of_joining": ["<=", end]},
        [["relieving_date", "is", "not set"], ["relieving_date", ">=", start]],
    )


def _require_contribution_records(social, housing):
    if not social:
        frappe.throw(frappe._("该员工尚未维护本月社保记录。"))
    if not housing:
        frappe.throw(frappe._("该员工尚未维护本月公积金记录。"))


def _assert_writable_slip(doc):
    if int(doc.docstatus or 0) == 1:
        frappe.throw(frappe._("工资单 {0} 已提交，不能覆盖。").format(doc.name))
    if not int(doc.hr_spa_managed or 0):
        frappe.throw(frappe._("本月已有其他来源工资单 {0}，不能覆盖。").format(doc.name))


def _structure_name(company):
    return "%s - %s" % (STRUCTURE, company)


def _existing_structure_for_company(company):
    expected = _structure_name(company)
    return frappe.db.get_value(
        "Salary Structure",
        {"name": expected, "company": company, "is_active": "Yes", "docstatus": 1},
        "name",
    )


def _default_company():
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if company:
        return company
    companies = frappe.get_all("Company", pluck="name", limit=1)
    if not companies:
        frappe.throw(frappe._("请先设置所属单位。"))
    return companies[0]


def _component(name, kind):
    if not frappe.db.exists("Salary Component", name):
        frappe.get_doc({
            "doctype": "Salary Component", "salary_component": name,
            "salary_component_abbr": name[:8], "type": kind, "is_tax_applicable": 0,
        }).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def ensure_payroll_masters(company=None):
    require_rd_access(ROLES)
    company = company or _default_company()
    if not frappe.db.exists("Company", company):
        frappe.throw(frappe._("请选择有效所属单位。"))
    for name, kind in COMPONENTS:
        _component(name, kind)
    existing = _existing_structure_for_company(company)
    structure = existing or _structure_name(company)
    if not existing:
        doc = frappe.get_doc({
            "doctype": "Salary Structure", "name": structure, "company": company,
            "payroll_frequency": "Monthly", "is_active": "Yes",
        })
        doc.append("earnings", {"salary_component": "基本工资", "amount_based_on_formula": 1, "formula": "base"})
        doc.insert(ignore_permissions=True)
        doc.submit()
    return {"salary_structure": structure, "company": company}


def _employee(employee):
    if not employee:
        frappe.throw(frappe._("请选择有效员工。"))
    row = frappe.db.get_value("Employee", employee, EMPLOYEE_PAYROLL_FIELDS, as_dict=True)
    if not row:
        frappe.throw(frappe._("请选择有效员工。"))
    if not row.get("company"):
        frappe.throw(frappe._("员工尚未设置所属单位。"))
    return row


def _monthly_record(doctype, employee, period, fields):
    return frappe.db.get_value(doctype, {"employee": employee, "period": period}, fields, as_dict=True)

def _social_record(employee, period, fields):
    company = frappe.db.get_value("Employee", employee, "company")
    batch = None
    if company:
        batch = frappe.db.get_value(
            "Social Insurance Import Batch",
            {"company": company, "period": period, "is_current": 1},
            "name",
        )
    if batch:
        row = frappe.db.get_value(
            "Social Insurance Import Row",
            {"batch": batch, "employee": employee, "status": ["in", ["Matched", "Confirmed Difference"]]},
            fields,
            as_dict=True,
        )
        if row:
            return row
    return _monthly_record("Employee Social Insurance", employee, period, fields)


def _assignment(employee, start):
    rows = frappe.get_all(
        "Salary Structure Assignment",
        filters={"employee": employee, "from_date": ["<=", start], "docstatus": 1},
        fields=["name", "salary_structure", "base", "from_date", "company"],
        order_by="from_date desc", limit=1,
    )
    return rows[0] if rows else None


def _slip(employee, start, end):
    name = frappe.db.get_value(
        "Salary Slip", {"employee": employee, "start_date": start, "end_date": end, "docstatus": ["<", 2]}, "name"
    )
    return frappe.get_doc("Salary Slip", name) if name else None


def _calendar_working_days(start, end, date_of_joining=None, relieving_date=None):
    period_start, period_end = getdate(start), getdate(end)
    employed_start = max(period_start, getdate(date_of_joining)) if date_of_joining else period_start
    employed_end = min(period_end, getdate(relieving_date)) if relieving_date else period_end
    total = float((period_end - period_start).days + 1)
    payment = float(max((employed_end - employed_start).days + 1, 0))
    return total, payment, "calendar_fallback"


def _working_days(employee, company, start, end, date_of_joining=None, relieving_date=None, holiday_list=None):
    if not holiday_list and not frappe.get_cached_value("Company", company, "default_holiday_list"):
        return _calendar_working_days(start, end, date_of_joining, relieving_date)
    doc = frappe.new_doc("Salary Slip")
    doc.update({
        "employee": employee, "company": company, "start_date": start, "end_date": end,
        "posting_date": end, "payroll_frequency": "Monthly",
    })
    try:
        doc.get_working_days_details()
    except Exception as exc:
        if "holiday list" not in str(exc).lower():
            raise
        return _calendar_working_days(start, end, date_of_joining, relieving_date)
    return _as_float(doc.total_working_days), _as_float(doc.payment_days), "hrms"


def _accommodation(employee, period):
    rows = frappe.get_all(
        "Accommodation Deduction", filters={"employee": employee, "period": period},
        fields=["personal_total_amount"],
    )
    return _money(sum(_as_float(row.get("personal_total_amount")) for row in rows))


def _row(employee, period, start, end, slip=None):
    social = _social_record( employee["name"], period,
        ["name", "employee_pension", "employee_medical", "employee_unemployment", "employee_total"],
    )
    housing = _monthly_record("Employee Housing Fund", employee["name"], period, ["name", "employee_amount"])
    total_days, default_payment_days, working_days_source = _working_days(
        employee["name"], employee["company"], start, end,
        employee.get("date_of_joining"), employee.get("relieving_date"), employee.get("holiday_list"),
    )
    assignment = _assignment(employee["name"], start)
    managed = bool(slip and int(slip.hr_spa_managed or 0))
    base = _as_float(slip.hr_base_salary) if managed else _as_float(assignment.get("base") if assignment else employee.get("default_monthly_salary"))
    inputs = {
        "payment_days": _as_float(slip.payment_days) if managed else default_payment_days,
        "base_salary": base,
        "salary_adjustment": _as_float(slip.hr_salary_adjustment) if managed else 0,
        "company_subsidy": _as_float(slip.hr_company_subsidy) if managed else 0,
        "bonus": _as_float(slip.hr_bonus) if managed else 0,
        "other_adjustment": _as_float(slip.hr_other_adjustment) if managed else 0,
        "income_tax": _as_float(slip.hr_income_tax) if managed else 0,
        "advanced_paid": _as_float(slip.hr_advanced_paid) if managed else 0,
    }
    accommodation = _accommodation(employee["name"], period)
    social_total = _as_float(social.get("employee_total") if social else 0)
    housing_total = _as_float(housing.get("employee_amount") if housing else 0)
    amounts = _calculate_amounts(
        total_days, inputs["payment_days"], inputs["base_salary"], inputs["salary_adjustment"],
        inputs["company_subsidy"], inputs["bonus"], inputs["other_adjustment"], social_total,
        housing_total, inputs["income_tax"], accommodation, inputs["advanced_paid"],
    )
    return {
        "employee": employee["name"], "employee_name": employee.get("employee_name"), "company": employee.get("company"),
        "id_card_number_cn": employee.get("id_card_number_cn"), "gender": employee.get("gender"),
        "expense_account_category": employee.get("expense_account_category"), "department": employee.get("department"),
        "designation": employee.get("designation"), "date_of_joining": employee.get("date_of_joining"),
        "relieving_date": employee.get("relieving_date"), "cell_number": employee.get("cell_number"),
        "bank_name": employee.get("bank_name"), "bank_ac_no": employee.get("bank_ac_no"),
        "period": period, "total_working_days": total_days, "working_days_source": working_days_source, **inputs,
        "adjusted_base": amounts["adjusted_base"], "prorated_base": amounts["prorated_base"],
        "payable_salary": amounts["payable_salary"], "employee_pension": _as_float(social.get("employee_pension") if social else 0),
        "employee_medical": _as_float(social.get("employee_medical") if social else 0),
        "employee_unemployment": _as_float(social.get("employee_unemployment") if social else 0),
        "social_insurance": social_total, "housing_fund": housing_total, "accommodation": accommodation,
        "total_deduction": amounts["total_deduction"], "net_pay": amounts["net_pay"],
        "social_record_exists": bool(social), "housing_record_exists": bool(housing),
        "salary_slip": slip.name if slip else None, "docstatus": int(slip.docstatus or 0) if slip else None,
        "managed": managed,
    }


@frappe.whitelist()
def get_payroll_rows(period):
    require_rd_access(ROLES)
    period = _period(period)
    start, end = _bounds(period)
    filters, or_filters = _period_employee_filters(start, end)
    employees = frappe.get_all(
        "Employee", filters=filters, or_filters=or_filters, fields=EMPLOYEE_PAYROLL_FIELDS, order_by="employee_name",
    )
    known = {row["name"] for row in employees}
    slips = frappe.get_all(
        "Salary Slip", filters={"start_date": start, "end_date": end, "docstatus": ["<", 2]}, fields=SLIP_FIELDS,
    )
    for slip in slips:
        if slip.get("employee") not in known:
            employee = frappe.db.get_value("Employee", slip.get("employee"), EMPLOYEE_PAYROLL_FIELDS, as_dict=True)
            if employee:
                employees.append(employee)
                known.add(employee["name"])
    slip_map = {row["employee"]: frappe.get_doc("Salary Slip", row["name"]) for row in slips}
    return [_row(employee, period, start, end, slip_map.get(employee["name"])) for employee in employees]


def _line(doc, table, component, amount):
    amount = _money(amount)
    if amount > 0:
        doc.append(table, {"salary_component": component, "amount": amount})


@frappe.whitelist(methods=["POST"])
def save_payroll_draft(employee, period, payment_days=None, base_salary=0, salary_adjustment=0,
                       company_subsidy=0, bonus=0, other_adjustment=0, income_tax=0, advanced_paid=0):
    require_rd_access(ROLES)
    employee_row = _employee(employee)
    period = _period(period)
    start, end = _bounds(period)
    social = _social_record( employee, period,
        ["name", "employee_pension", "employee_medical", "employee_unemployment", "employee_total"],
    )
    housing = _monthly_record("Employee Housing Fund", employee, period, ["name", "employee_amount"])
    _require_contribution_records(social, housing)
    total_days, default_days, working_days_source = _working_days(
        employee, employee_row["company"], start, end,
        employee_row.get("date_of_joining"), employee_row.get("relieving_date"), employee_row.get("holiday_list"),
    )
    days = default_days if payment_days in (None, "") else payment_days
    accommodation = _accommodation(employee, period)
    amounts = _calculate_amounts(
        total_days, days, base_salary, salary_adjustment, company_subsidy, bonus, other_adjustment,
        social.get("employee_total"), housing.get("employee_amount"), income_tax, accommodation, advanced_paid,
    )
    if amounts["net_pay"] < 0:
        frappe.throw(frappe._("实发工资不能为负数。"))
    existing = _slip(employee, start, end)
    if existing:
        _assert_writable_slip(existing)
    masters = ensure_payroll_masters(employee_row["company"])
    doc = existing or frappe.new_doc("Salary Slip")
    doc.update({
        "employee": employee, "employee_name": employee_row.get("employee_name"), "company": employee_row["company"],
        "department": employee_row.get("department"), "designation": employee_row.get("designation"),
        "posting_date": end, "start_date": start, "end_date": end, "payroll_frequency": "Monthly",
        "salary_structure": masters["salary_structure"], "total_working_days": total_days, "payment_days": _as_float(days),
        "bank_name": employee_row.get("bank_name"), "bank_account_no": employee_row.get("bank_ac_no"),
        "hr_spa_managed": 1, "hr_base_salary": _as_float(base_salary), "hr_salary_adjustment": _as_float(salary_adjustment),
        "hr_adjusted_base": amounts["adjusted_base"], "hr_company_subsidy": _as_float(company_subsidy),
        "hr_bonus": _as_float(bonus), "hr_other_adjustment": _as_float(other_adjustment),
        "hr_income_tax": _as_float(income_tax), "hr_advanced_paid": _as_float(advanced_paid),
        "hr_id_card_number_cn": employee_row.get("id_card_number_cn"), "hr_gender": employee_row.get("gender"),
        "hr_expense_account_category": employee_row.get("expense_account_category"),
        "hr_date_of_joining": employee_row.get("date_of_joining"), "hr_relieving_date": employee_row.get("relieving_date"),
        "hr_phone": employee_row.get("cell_number"),
    })
    doc.set("earnings", [])
    doc.set("deductions", [])
    _line(doc, "earnings", "基本工资", amounts["prorated_base"])
    _line(doc, "earnings", "公司补贴", company_subsidy)
    _line(doc, "earnings", "奖金", bonus)
    _line(doc, "earnings", "其他收入", max(_as_float(other_adjustment), 0))
    _line(doc, "deductions", "社保个人", social.get("employee_total"))
    _line(doc, "deductions", "公积金个人", housing.get("employee_amount"))
    _line(doc, "deductions", "宿舍扣款", accommodation)
    _line(doc, "deductions", "个税", income_tax)
    _line(doc, "deductions", "其他扣款", max(-_as_float(other_adjustment), 0))
    _line(doc, "deductions", "已发放", advanced_paid)
    if existing:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)
    return {"name": doc.name, "employee": employee, "working_days_source": working_days_source, **amounts}


@frappe.whitelist(methods=["POST"])
def apply_salary_adjustment(employee, period, adjusted_base):
    require_rd_access(ROLES)
    employee_row = _employee(employee)
    base = _nonnegative("调薪后基本工资", adjusted_base)
    if base <= 0:
        frappe.throw(frappe._("调薪后基本工资必须大于 0。"))
    start, _ = _bounds(period)
    masters = ensure_payroll_masters(employee_row["company"])
    filters = {
        "employee": employee, "salary_structure": masters["salary_structure"],
        "from_date": start, "docstatus": ["<", 2],
    }
    existing = frappe.db.get_value("Salary Structure Assignment", filters, "name")
    if existing:
        frappe.throw(frappe._("该员工本月起始日已有工资分配 {0}，不能覆盖。").format(existing))
    doc = frappe.new_doc("Salary Structure Assignment")
    doc.update({
        "employee": employee, "salary_structure": masters["salary_structure"], "from_date": start,
        "base": base, "company": employee_row["company"],
    })
    doc.insert(ignore_permissions=True)
    doc.submit()
    return {"name": doc.name, "base": base, "from_date": start}


@frappe.whitelist()
def get_payroll_options():
    require_rd_access(ROLES)
    return {"employees": frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", "employee_name"], order_by="employee_name")}


@frappe.whitelist(methods=["POST"])
def save_salary_base(employee, period, base):
    return apply_salary_adjustment(employee, period, base)


@frappe.whitelist()
def preview_payroll(employee, period, other_income=0, income_tax=0, other_deduction=0):
    require_rd_access(ROLES)
    rows = get_payroll_rows(period)
    row = next((item for item in rows if item["employee"] == employee), None)
    if not row:
        frappe.throw(frappe._("请选择有效员工。"))
    amounts = _calculate_amounts(
        row["total_working_days"], row["payment_days"], row["base_salary"], 0,
        _as_float(other_income), 0, -_as_float(other_deduction), row["social_insurance"],
        row["housing_fund"], income_tax, row["accommodation"], 0,
    )
    return {**row, **amounts}


@frappe.whitelist(methods=["POST"])
def create_draft_salary_slip(employee, period, other_income=0, income_tax=0, other_deduction=0):
    rows = get_payroll_rows(period)
    row = next((item for item in rows if item["employee"] == employee), None)
    if not row:
        frappe.throw(frappe._("请选择有效员工。"))
    return save_payroll_draft(
        employee, period, row["payment_days"], row["base_salary"], 0, other_income, 0,
        -_as_float(other_deduction), income_tax, 0,
    )


@frappe.whitelist()
def list_salary_slips(period):
    require_rd_access(ROLES)
    start, end = _bounds(period)
    return frappe.get_all(
        "Salary Slip", filters={"start_date": start, "end_date": end, "docstatus": ["<", 2]},
        fields=["name", "employee", "employee_name", "gross_pay", "total_deduction", "net_pay", "docstatus", "hr_spa_managed"],
        order_by="employee_name",
    )