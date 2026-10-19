import frappe
from frappe.utils import getdate, get_last_day

from rayher_hr_payroll.api._guards import parse_period, require_rd_access

# 算法（决定 2026-10-14）：应付 = 定好的基本工资（含本月调薪）× 实际工时 ÷ 当月总工时 + 公司补贴 + 奖金 ± 其他补扣；
# 先扣社保、公积金个人部分，再按累计预扣法扣个税（工资次月发，按发放月累计），最后扣宿舍和已发放 = 实发。
# 当月总工时 = 公司日历的工作日 × 8；实际工时 = 在职期间的工作日 × 8 − 已批准的事假小时；系统不改人事定的基本工资和工时。
# 工时、社保公积金、个税累计这三样输入在 payroll_inputs.py；工资条的明细行和合计在 payroll_slip.py。

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
    "bank_ac_no", "default_monthly_salary", "holiday_list", "default_social_insurance_base",
    "default_housing_fund_base", "household_registration",
]
TAX_FIELDS = [
    "hr_tax_period", "hr_tax_income", "hr_tax_special", "hr_tax_special_additional", "hr_tax_other", "hr_tax_months",
    "hr_tax_cum_income", "hr_tax_cum_basic", "hr_tax_cum_special", "hr_tax_cum_special_additional", "hr_tax_cum_other",
    "hr_tax_cum_taxable", "hr_tax_rate", "hr_tax_quick", "hr_tax_cum_tax", "hr_tax_prior", "hr_tax_auto",
    "hr_tax_manual", "hr_tax_manual_reason", "hr_bonus_separate", "hr_bonus_tax",
]
SLIP_FIELDS = [
    "name", "employee", "employee_name", "company", "department", "designation", "bank_name", "bank_account_no",
    "start_date", "end_date", "total_working_days", "payment_days", "gross_pay", "total_deduction", "net_pay",
    "docstatus", "hr_spa_managed", "hr_base_salary", "hr_salary_adjustment", "hr_adjusted_base",
    "hr_company_subsidy", "hr_bonus", "hr_other_adjustment", "hr_income_tax", "hr_advanced_paid",
    "hr_id_card_number_cn", "hr_gender", "hr_expense_account_category", "hr_date_of_joining",
    "hr_relieving_date", "hr_phone",
]
REASON_LIMIT = 500


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


def _flag(value):
    return 1 if str(value or "").strip().lower() in ("1", "true", "yes", "on") else 0


def _calculate_amounts(total_hours, actual_hours, base_salary, salary_adjustment, company_subsidy,
                       bonus, other_adjustment, social_insurance, housing_fund, income_tax, accommodation,
                       advanced_paid):
    total = _nonnegative("当月总工时", total_hours)
    hours = _nonnegative("实际工时", actual_hours)
    if total <= 0:
        frappe.throw(frappe._("当月总工时必须大于 0（请检查公司工作日历）。"))
    if hours > total:
        frappe.throw(frappe._("实际工时不能超过当月总工时。"))
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
    prorated = _money(adjusted * hours / total)
    payable = prorated + subsidy + bonus_value + other
    deductions = social + fund + tax + dormitory + advanced
    return {
        "adjusted_base": _money(adjusted),
        "prorated_base": prorated,
        "payable_salary": _money(payable),
        "total_deduction": _money(deductions),
        "net_pay": _money(payable - deductions),
    }


def _period_employee_filters(start, end):
    return (
        {"date_of_joining": ["<=", end]},
        [["relieving_date", "is", "not set"], ["relieving_date", ">=", start]],
    )


def _require_contributions(found):
    """社保、公积金都要有（账单、月度记录或者按档案基数能算出来），算不出来就说清楚缺什么，不当 0。"""
    for key, label in (("social", "社保"), ("fund", "公积金")):
        item = found.get(key) or {}
        if item.get("missing"):
            frappe.throw(frappe._("{0}算不出来：{1}。").format(label, item["missing"]))


def _require_read():
    """看薪酬：人事角色；总经理、演示员工113经理岗位只读（决定 2026-10-13：领导点进来和人事看到的一样，不能改）。"""
    from rayher_hr_payroll.hr_read_access import require_hr_read

    require_hr_read(ROLES, require_rd_access)


def _assert_writable_slip(doc):
    if int(doc.docstatus or 0) == 1:
        frappe.throw(frappe._("工资单 {0} 已确认，不能修改；要改请先撤回确认。").format(doc.name))
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


def _accommodation(employee, period):
    rows = frappe.get_all(
        "Accommodation Deduction", filters={"employee": employee, "period": period},
        fields=["personal_total_amount"],
    )
    return _money(sum(_as_float(row.get("personal_total_amount")) for row in rows))


def _inputs():
    from rayher_hr_payroll import payroll_inputs

    return payroll_inputs


def _tax_view(values):
    """工资条上存的个税中间数 → 页面用的字典（键和 payroll_inputs.compute_tax 一样）。"""
    get = values.get if isinstance(values, dict) else (lambda key, default=None: getattr(values, key, default))
    return {
        "tax_period": get("hr_tax_period"), "income": _as_float(get("hr_tax_income")), "special": _as_float(get("hr_tax_special")),
        "special_additional": _as_float(get("hr_tax_special_additional")), "other": _as_float(get("hr_tax_other")),
        "months": int(get("hr_tax_months") or 0), "cum_income": _as_float(get("hr_tax_cum_income")),
        "cum_basic": _as_float(get("hr_tax_cum_basic")), "cum_special": _as_float(get("hr_tax_cum_special")),
        "cum_special_additional": _as_float(get("hr_tax_cum_special_additional")), "cum_other": _as_float(get("hr_tax_cum_other")),
        "cum_taxable": _as_float(get("hr_tax_cum_taxable")), "rate": _as_float(get("hr_tax_rate")), "quick": _as_float(get("hr_tax_quick")),
        "cum_tax": _as_float(get("hr_tax_cum_tax")), "prior_tax": _as_float(get("hr_tax_prior")), "tax": _as_float(get("hr_tax_auto")) - _as_float(get("hr_bonus_tax")),
        "bonus_tax": _as_float(get("hr_bonus_tax")), "total": _as_float(get("hr_tax_auto")),
    }


def _saved_payroll_row(employee, period, slip):
    """Display the saved salary document without re-reading mutable HR inputs."""
    def value(key, default=None):
        return getattr(slip, key, default)
    def components(table):
        totals = {}
        for line in value(table, []) or []:
            key = getattr(line, "salary_component", None)
            totals[key] = totals.get(key, 0) + _as_float(getattr(line, "amount", 0))
        return totals
    earnings, deductions = components("earnings"), components("deductions")
    managed = bool(value("hr_spa_managed", 0))
    v2 = bool(value("hr_amounts_v2", 0))
    inputs = {
        "base_salary": value("hr_base_salary") if managed else None,
        "salary_adjustment": value("hr_salary_adjustment") if managed else None,
        "company_subsidy": earnings.get("公司补贴", 0), "bonus": earnings.get("奖金", 0),
        "other_adjustment": earnings.get("其他收入", 0) - deductions.get("其他扣款", 0),
        "income_tax": deductions.get("个税", 0), "advanced_paid": deductions.get("已发放", 0),
    }
    return {
        "employee": employee["name"], "employee_name": value("employee_name"), "company": value("company"),
        "department": value("department"), "designation": value("designation"),
        "id_card_number_cn": value("hr_id_card_number_cn"), "gender": value("hr_gender"),
        "expense_account_category": value("hr_expense_account_category"),
        "date_of_joining": value("hr_date_of_joining"), "relieving_date": value("hr_relieving_date"),
        "cell_number": value("hr_phone"), "bank_name": value("bank_name"), "bank_ac_no": value("bank_account_no"),
        "period": period, "total_working_days": value("total_working_days"),
        "payment_days": value("payment_days"), "working_days_source": "salary_slip", **inputs,
        "total_hours": value("hr_total_hours") if v2 else None, "actual_hours": value("hr_actual_hours") if v2 else None,
        "personal_leave_hours": value("hr_personal_leave_hours") if v2 else None, "hours_manual": bool(value("hr_hours_manual", 0)),
        "adjusted_base": value("hr_adjusted_base") if managed else None,
        "prorated_base": earnings.get("基本工资"), "payable_salary": value("gross_pay"),
        # Older salary slips stored only the total social deduction, not its split.
        "employee_pension": None, "employee_medical": None, "employee_unemployment": None,
        "social_insurance": deductions.get("社保个人", 0), "housing_fund": deductions.get("公积金个人", 0),
        "social_source": value("hr_contribution_source") if v2 else None,
        "accommodation": deductions.get("宿舍扣款", 0), "total_deduction": value("total_deduction"),
        "net_pay": value("net_pay"), "social_record_exists": True, "housing_record_exists": True,
        "tax": _tax_view(slip) if v2 else None, "tax_manual": bool(value("hr_tax_manual", 0)),
        "tax_manual_reason": value("hr_tax_manual_reason"), "bonus_separate": bool(value("hr_bonus_separate", 0)),
        "salary_slip": value("name"), "docstatus": int(value("docstatus", 0)), "managed": managed,
        "amount_source": "salary_slip",
    }


def _hours_for(employee, company, period, slip=None, actual_hours=None, hours_manual=None, calendars=None):
    """{total_hours, actual_hours, ...} 实际工时：人事手动改过（hours_manual）用改的数，否则按考勤算。"""
    hours = _inputs().work_hours(employee, company, period, calendars)
    manual = bool(_flag(hours_manual)) if hours_manual is not None else bool(slip and int(getattr(slip, "hr_hours_manual", 0) or 0))
    if manual:
        value = actual_hours if actual_hours not in (None, "") else getattr(slip, "hr_actual_hours", None)
        hours["actual_hours"] = _nonnegative("实际工时", value)
    hours["hours_manual"] = manual
    return hours


def _row(employee, period, start, end, slip=None, calendars=None):
    if slip and (int(slip.docstatus or 0) == 1 or not slip.hr_spa_managed):
        return _saved_payroll_row(employee, period, slip)
    inputs_module = _inputs()
    found = inputs_module.contributions(employee, period)
    social, fund = found["social"], found["fund"]
    managed = bool(slip and int(slip.hr_spa_managed or 0))
    hours = _hours_for(employee["name"], employee["company"], period, slip if managed else None, calendars=calendars)
    assignment = _assignment(employee["name"], start)
    base = _as_float(slip.hr_base_salary) if managed else _as_float(assignment.get("base") if assignment else employee.get("default_monthly_salary"))
    inputs = {
        "base_salary": base,
        "salary_adjustment": _as_float(slip.hr_salary_adjustment) if managed else 0,
        "company_subsidy": _as_float(slip.hr_company_subsidy) if managed else 0,
        "bonus": _as_float(slip.hr_bonus) if managed else 0,
        "other_adjustment": _as_float(slip.hr_other_adjustment) if managed else 0,
        "advanced_paid": _as_float(slip.hr_advanced_paid) if managed else 0,
    }
    v2 = managed and int(getattr(slip, "hr_amounts_v2", 0) or 0)
    # 旧草稿（新算法之前存的）个税是人事手填的：当作手动，原样保留
    tax_manual = bool(managed and (int(getattr(slip, "hr_tax_manual", 0) or 0) or (not v2 and _as_float(slip.hr_income_tax) > 0)))
    bonus_separate = bool(managed and int(getattr(slip, "hr_bonus_separate", 0) or 0))
    accommodation = _accommodation(employee["name"], period)
    social_total = _as_float(social.get("employee_total"))
    housing_total = _as_float(fund.get("employee_amount"))
    preview = _calculate_amounts(
        hours["total_hours"] or 1, min(hours["actual_hours"], hours["total_hours"] or 1), inputs["base_salary"], inputs["salary_adjustment"],
        inputs["company_subsidy"], inputs["bonus"], inputs["other_adjustment"], social_total, housing_total, 0, accommodation, inputs["advanced_paid"],
    )
    basis = inputs_module.tax_basis(employee["name"], employee["company"], period, exclude=slip.name if slip else None)
    tax = inputs_module.compute_tax(basis, preview["payable_salary"], social_total, housing_total, inputs["bonus"], bonus_separate)
    income_tax = _as_float(slip.hr_income_tax) if tax_manual else tax["total"]
    amounts = _calculate_amounts(
        hours["total_hours"] or 1, min(hours["actual_hours"], hours["total_hours"] or 1), inputs["base_salary"], inputs["salary_adjustment"],
        inputs["company_subsidy"], inputs["bonus"], inputs["other_adjustment"], social_total, housing_total, income_tax,
        accommodation, inputs["advanced_paid"],
    )
    return {
        "employee": employee["name"], "employee_name": employee.get("employee_name"), "company": employee.get("company"),
        "id_card_number_cn": employee.get("id_card_number_cn"), "gender": employee.get("gender"),
        "expense_account_category": employee.get("expense_account_category"), "department": employee.get("department"),
        "designation": employee.get("designation"), "date_of_joining": employee.get("date_of_joining"),
        "relieving_date": employee.get("relieving_date"), "cell_number": employee.get("cell_number"),
        "bank_name": employee.get("bank_name"), "bank_ac_no": employee.get("bank_ac_no"),
        "period": period, **inputs, "income_tax": income_tax,
        "total_hours": hours["total_hours"], "actual_hours": hours["actual_hours"], "employed_hours": hours["employed_hours"],
        "personal_leave_hours": hours["personal_leave_hours"], "hours_manual": hours["hours_manual"], "work_days": hours["work_days"],
        "calendar_source": hours.get("calendar_source"),
        # 兼容旧字段：按天显示的地方用小时 ÷ 8
        "total_working_days": round(hours["total_hours"] / 8, 2), "payment_days": round(hours["actual_hours"] / 8, 2),
        "working_days_source": "hours",
        "adjusted_base": amounts["adjusted_base"], "prorated_base": amounts["prorated_base"],
        "payable_salary": amounts["payable_salary"], "employee_pension": _as_float(social.get("employee_pension")),
        "employee_medical": _as_float(social.get("employee_medical")),
        "employee_unemployment": _as_float(social.get("employee_unemployment")),
        "social_insurance": social_total, "housing_fund": housing_total, "accommodation": accommodation,
        "social_source": social.get("source"), "fund_source": fund.get("source"),
        "social_missing": social.get("missing"), "fund_missing": fund.get("missing"),
        "total_deduction": amounts["total_deduction"], "net_pay": amounts["net_pay"],
        "social_record_exists": not social.get("missing"), "housing_record_exists": not fund.get("missing"),
        "tax": tax, "tax_basis": {key: basis[key] for key in ("tax_period", "prior", "low_income", "special_additional", "other", "bonus_used", "has_profile")},
        "tax_warnings": basis["warnings"], "tax_manual": tax_manual, "bonus_separate": bonus_separate,
        "tax_manual_reason": getattr(slip, "hr_tax_manual_reason", None) if managed else None,
        "salary_slip": slip.name if slip else None, "docstatus": int(slip.docstatus or 0) if slip else None,
        "managed": managed,
    }


@frappe.whitelist()
def get_payroll_rows(period):
    _require_read()
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
    calendars = {}
    return [_row(employee, period, start, end, slip_map.get(employee["name"]), calendars) for employee in employees]


def _tax_values(tax):
    return {
        "hr_tax_period": tax.get("tax_period"), "hr_tax_income": tax["income"], "hr_tax_special": tax["special"],
        "hr_tax_special_additional": tax["special_additional"], "hr_tax_other": tax["other"], "hr_tax_months": tax["months"],
        "hr_tax_cum_income": tax["cum_income"], "hr_tax_cum_basic": tax["cum_basic"], "hr_tax_cum_special": tax["cum_special"],
        "hr_tax_cum_special_additional": tax["cum_special_additional"], "hr_tax_cum_other": tax["cum_other"],
        "hr_tax_cum_taxable": tax["cum_taxable"], "hr_tax_rate": tax["rate"], "hr_tax_quick": tax["quick"],
        "hr_tax_cum_tax": tax["cum_tax"], "hr_tax_prior": tax["prior_tax"], "hr_tax_auto": tax["total"], "hr_bonus_tax": tax["bonus_tax"],
    }


@frappe.whitelist(methods=["POST"])
def save_payroll_draft(employee, period, payment_days=None, base_salary=0, salary_adjustment=0,
                       company_subsidy=0, bonus=0, other_adjustment=0, income_tax=0, advanced_paid=0,
                       actual_hours=None, hours_manual=0, tax_manual=0, tax_manual_reason="", bonus_separate=0):
    """保存草稿。实际工时默认按考勤算（hours_manual=1 才用传进来的 actual_hours）；个税默认按累计预扣法算
    （tax_manual=1 才用传进来的 income_tax，而且要写原因）；payment_days 是旧参数，只在手动改工时又没传小时数时按 × 8 用。"""
    require_rd_access(ROLES)
    inputs_module = _inputs()
    employee_row = _employee(employee)
    period = _period(period)
    start, end = _bounds(period)
    existing = _slip(employee, start, end)
    if existing:
        _assert_writable_slip(existing)
    found = inputs_module.contributions(employee_row, period)
    _require_contributions(found)
    social, fund = found["social"], found["fund"]
    if _flag(hours_manual) and actual_hours in (None, "") and payment_days not in (None, ""):
        actual_hours = _as_float(payment_days) * 8
    hours = _hours_for(employee, employee_row["company"], period, actual_hours=actual_hours, hours_manual=_flag(hours_manual))
    accommodation = _accommodation(employee, period)
    social_total, housing_total = _as_float(social.get("employee_total")), _as_float(fund.get("employee_amount"))
    bonus_flag = _flag(bonus_separate)
    preview = _calculate_amounts(hours["total_hours"], hours["actual_hours"], base_salary, salary_adjustment, company_subsidy,
                                 bonus, other_adjustment, social_total, housing_total, 0, accommodation, advanced_paid)
    basis = inputs_module.tax_basis(employee, employee_row["company"], period, exclude=existing.name if existing else None)
    if bonus_flag and basis["bonus_used"]:
        frappe.throw(frappe._("今年已经有一演示员工17资条用过年终奖单独计税，一年只能用一次。"))
    if bonus_flag and _as_float(bonus) <= 0:
        frappe.throw(frappe._("选了年终奖单独计税，奖金要大于 0。"))
    tax = inputs_module.compute_tax(basis, preview["payable_salary"], social_total, housing_total, bonus, bonus_flag)
    manual = _flag(tax_manual)
    reason = str(tax_manual_reason or "").strip()
    if manual and not reason:
        frappe.throw(frappe._("手动改个税要写原因。"))
    if len(reason) > REASON_LIMIT:
        frappe.throw(frappe._("原因不能超过 {0} 个字。").format(REASON_LIMIT))
    final_tax = _nonnegative("个人所得税", income_tax) if manual else tax["total"]
    amounts = _calculate_amounts(
        hours["total_hours"], hours["actual_hours"], base_salary, salary_adjustment, company_subsidy, bonus, other_adjustment,
        social_total, housing_total, final_tax, accommodation, advanced_paid,
    )
    if amounts["net_pay"] < 0:
        frappe.throw(frappe._("实发工资不能为负数。"))
    masters = ensure_payroll_masters(employee_row["company"])
    inputs_module.materialize(employee_row, period, found)
    doc = existing or frappe.new_doc("Salary Slip")
    doc.update({
        "employee": employee, "employee_name": employee_row.get("employee_name"), "company": employee_row["company"],
        "department": employee_row.get("department"), "designation": employee_row.get("designation"),
        "posting_date": end, "start_date": start, "end_date": end, "payroll_frequency": "Monthly",
        "salary_structure": masters["salary_structure"],
        "bank_name": employee_row.get("bank_name"), "bank_account_no": employee_row.get("bank_ac_no"),
        "hr_spa_managed": 1, "hr_amounts_v2": 1, "hr_base_salary": _as_float(base_salary), "hr_salary_adjustment": _as_float(salary_adjustment),
        "hr_adjusted_base": amounts["adjusted_base"], "hr_prorated_base": amounts["prorated_base"],
        "hr_company_subsidy": _as_float(company_subsidy), "hr_bonus": _as_float(bonus), "hr_other_adjustment": _as_float(other_adjustment),
        "hr_income_tax": final_tax, "hr_advanced_paid": _as_float(advanced_paid),
        "hr_total_hours": hours["total_hours"], "hr_actual_hours": hours["actual_hours"],
        "hr_personal_leave_hours": hours["personal_leave_hours"], "hr_hours_manual": 1 if hours["hours_manual"] else 0,
        "hr_social_personal": social_total, "hr_social_company": _as_float(social.get("company_total")),
        "hr_fund_personal": housing_total, "hr_fund_company": _as_float(fund.get("company_amount")),
        "hr_accommodation": accommodation, "hr_contribution_source": f"社保：{social.get('source')}；公积金：{fund.get('source')}",
        **_tax_values(tax), "hr_tax_manual": manual, "hr_tax_manual_reason": reason if manual else "",
        "hr_bonus_separate": bonus_flag,
        "hr_id_card_number_cn": employee_row.get("id_card_number_cn"), "hr_gender": employee_row.get("gender"),
        "hr_expense_account_category": employee_row.get("expense_account_category"),
        "hr_date_of_joining": employee_row.get("date_of_joining"), "hr_relieving_date": employee_row.get("relieving_date"),
        "hr_phone": employee_row.get("cell_number"),
    })
    from rayher_hr_payroll.payroll_slip import apply_lines

    apply_lines(doc)
    if existing:
        doc.save(ignore_permissions=True)
    else:
        # HRMS 新建对象时就按当时的员工号定了编号格式（那时还没有员工号，会成 Sal Slip/None/…），填完员工后重设。
        doc.default_series = "Sal Slip/%s/.#####" % employee
        doc.insert(ignore_permissions=True)
    return {"name": doc.name, "employee": employee, "income_tax": final_tax, "tax": tax, **amounts}


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
    return row


@frappe.whitelist(methods=["POST"])
def create_draft_salary_slip(employee, period, other_income=0, income_tax=0, other_deduction=0):
    rows = get_payroll_rows(period)
    row = next((item for item in rows if item["employee"] == employee), None)
    if not row:
        frappe.throw(frappe._("请选择有效员工。"))
    return save_payroll_draft(
        employee, period, base_salary=row["base_salary"], other_adjustment=_as_float(other_income) - _as_float(other_deduction),
    )


@frappe.whitelist()
def get_payroll_access():
    """页面用：能不能改（人事角色）。总经理、演示员工113经理能打开但只读。"""
    _require_read()
    return {"can_edit": bool(set(frappe.get_roles(frappe.session.user)) & set(ROLES))}


@frappe.whitelist()
def list_salary_slips(period):
    _require_read()
    start, end = _bounds(period)
    return frappe.get_all(
        "Salary Slip", filters={"start_date": start, "end_date": end, "docstatus": ["<", 2]},
        fields=["name", "employee", "employee_name", "gross_pay", "total_deduction", "net_pay", "docstatus", "hr_spa_managed"],
        order_by="employee_name",
    )


# ---------------------------------------------------------------- 确认本月工资（决定 2026-10-13）
# 草稿 = 人事算好、还能改的工资条；确认 = 核对完锁定（提交工资条），发工资、入账、研发人工和看板金额只认已确认的。
# 要改已确认的：先撤回确认（作废这张，复制一张草稿接着改，作废的那张留作记录）。
# 研发分摊已经定版、用到了这个人工时的月份，工资单锁定规则（payroll_bridge.block_locked_salary_slip_change）不让撤回。


@frappe.whitelist(methods=["POST"])
def confirm_payroll(period, employees=None):
    """确认本月工资：把本页生成的草稿工资条逐张确认。employees 为空 = 本月全部草稿；
    别处生成的草稿不在这里确认；某一张确认不了（比如分摊已定版）就跳过，返回原因，其余照常确认。"""
    require_rd_access(ROLES)
    period = _period(period)
    start, end = _bounds(period)
    wanted = set(frappe.parse_json(employees) or []) if employees else None
    drafts = frappe.get_all(
        "Salary Slip", filters={"start_date": start, "end_date": end, "docstatus": 0},
        fields=["name", "employee", "employee_name", "hr_spa_managed"], order_by="employee_name",
    )
    confirmed, skipped = [], []
    # 确认是人事内部锁定，不顺带给员工发工资条邮件（薪酬设置里开着“提交时发邮件”，HRMS 只在批量发薪时跳过它）。
    previous = frappe.flags.via_payroll_entry
    frappe.flags.via_payroll_entry = True
    try:
        _confirm_each(drafts, wanted, confirmed, skipped, period)
    finally:
        frappe.flags.via_payroll_entry = previous
    return {"period": period, "confirmed": len(confirmed), "skipped": skipped}


RESAVE_FAILED = "按现在的工时、社保、公积金、宿舍和个税重算失败："


def _resave_draft(doc, period):
    """确认前重算：草稿存的是当时的工时 / 社保 / 公积金 / 宿舍 / 个税累计，页面（_row）却按现在的数显示。
    用工资条上人事填的数（hr_*），走 save_payroll_draft 同一套计算重新保存，确认锁定的就是页面上看到的金额。
    人事手动改过的工时、个税原样保留；旧草稿（新算法之前存的）手填的个税也当手动保留。"""
    v2 = int(getattr(doc, "hr_amounts_v2", 0) or 0)
    tax_manual = int(getattr(doc, "hr_tax_manual", 0) or 0) or (not v2 and _as_float(doc.hr_income_tax) > 0)
    reason = getattr(doc, "hr_tax_manual_reason", None) or ("新算法之前手填的个税" if tax_manual else "")
    save_payroll_draft(
        doc.employee, period,
        base_salary=_as_float(doc.hr_base_salary), salary_adjustment=_as_float(doc.hr_salary_adjustment),
        company_subsidy=_as_float(doc.hr_company_subsidy), bonus=_as_float(doc.hr_bonus),
        other_adjustment=_as_float(doc.hr_other_adjustment), income_tax=_as_float(doc.hr_income_tax),
        advanced_paid=_as_float(doc.hr_advanced_paid),
        actual_hours=getattr(doc, "hr_actual_hours", None), hours_manual=int(getattr(doc, "hr_hours_manual", 0) or 0),
        tax_manual=1 if tax_manual else 0, tax_manual_reason=reason,
        bonus_separate=int(getattr(doc, "hr_bonus_separate", 0) or 0),
    )
    return frappe.get_doc("Salary Slip", doc.name)


def _confirm_each(drafts, wanted, confirmed, skipped, period):
    for row in drafts:
        if wanted is not None and row.get("employee") not in wanted:
            continue
        who = {"employee": row.get("employee"), "employee_name": row.get("employee_name")}
        if not int(row.get("hr_spa_managed") or 0):
            skipped.append({**who, "reason": "别处生成的工资条，不在这里确认"})
            continue
        frappe.db.savepoint("confirm_payroll")
        stage = RESAVE_FAILED
        try:
            doc = frappe.get_doc("Salary Slip", row.get("name"))
            doc = _resave_draft(doc, period)   # 重算失败（比如社保算不出来）：这张跳过，写明原因
            stage = ""
            doc.flags.ignore_permissions = True
            doc.submit()
        except Exception as exc:
            frappe.db.rollback(save_point="confirm_payroll")
            frappe.clear_messages()
            skipped.append({**who, "reason": stage + (str(exc) or "确认失败")})
            continue
        confirmed.append(row.get("employee"))


@frappe.whitelist(methods=["POST"])
def withdraw_payroll_confirmation(employee, period, reason=None):
    """撤回确认：作废这个人本月已确认的工资条，复制一张草稿接着改；撤回原因记在作废的那张上。"""
    require_rd_access(ROLES)
    reason = str(reason or "").strip()
    if not reason:
        frappe.throw(frappe._("请写撤回原因。"))
    if len(reason) > REASON_LIMIT:
        frappe.throw(frappe._("撤回原因不能超过 {0} 个字。").format(REASON_LIMIT))
    period = _period(period)
    start, end = _bounds(period)
    name = frappe.db.get_value(
        "Salary Slip", {"employee": employee, "start_date": start, "end_date": end, "docstatus": 1}, "name"
    )
    if not name:
        frappe.throw(frappe._("这个人本月没有已确认的工资条。"))
    doc = frappe.get_doc("Salary Slip", name)
    if not int(doc.hr_spa_managed or 0):
        frappe.throw(frappe._("工资单 {0} 是别处生成的，不能在这里撤回。").format(name))
    doc.flags.ignore_permissions = True
    doc.cancel()
    doc.add_comment("Comment", "撤回确认：" + reason)
    draft = frappe.copy_doc(doc)
    draft.amended_from = doc.name
    draft.docstatus = 0
    draft.insert(ignore_permissions=True)
    if not int(getattr(doc, "hr_amounts_v2", 0) or 0):
        # 新算法之前确认的工资条：复制出来的草稿 HRMS 会按结构重算，按人事填的数重存一遍
        _resave_draft(draft, period)
    return {"name": draft.name, "cancelled": doc.name}
