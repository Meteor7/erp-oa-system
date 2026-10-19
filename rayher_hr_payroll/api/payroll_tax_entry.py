"""员工个税资料（2026-10-14）：每月专项附加扣除、其他扣除、上年不超过 6 万的规则、系统上线前的期初累计。

薪酬计算按累计预扣法算个税要用这些数（payroll_inputs.tax_basis）。看：人事角色，总经理、演示员工113经理只读；改：人事角色。
数据来源：员工在个税 App 里填的专项附加扣除，人事从扣缴客户端导出后录到这里；期初累计按扣缴客户端里本单位已申报的累计数填。
"""
import frappe

from rayher_hr_payroll.api._guards import require_hr_sensitive_access, require_rd_access

ROLES = ("System Manager", "HR User", "HR Manager")
DOCTYPE = "Employee Tax Profile"
EDITABLE = (
    "low_income_rule", "special_child_education", "special_infant_care", "special_continuing_education",
    "special_housing_loan", "special_housing_rent", "special_elderly_support", "other_deduction",
    "opening_to_period", "opening_months", "opening_income", "opening_tax_free", "opening_special",
    "opening_special_additional", "opening_other", "opening_tax", "opening_bonus_used", "remark",
)
CHECKS = ("low_income_rule", "opening_bonus_used")
TEXTS = ("opening_to_period", "remark")
INTS = ("opening_months",)


def _year(value):
    try:
        year = int(str(value or "").strip())
    except ValueError:
        year = 0
    if year < 2000 or year > 2100:
        frappe.throw(frappe._("请选择有效年度。"))
    return year


def _require_read():
    from rayher_hr_payroll.hr_read_access import require_hr_read

    require_hr_read(ROLES, require_rd_access)
    require_hr_sensitive_access()


@frappe.whitelist()
def get_tax_profiles(year):
    """这一年每个在职员工（以及这一年演示员工166的）一行：个税资料（没有就是空的默认值）。"""
    _require_read()
    year = _year(year)
    employees = frappe.get_all(
        "Employee", filters={"status": "Active"}, fields=["name", "employee_name", "company", "department", "date_of_joining"],
        order_by="company, employee_name", limit_page_length=0,
    )
    profiles = {row["employee"]: row for row in frappe.get_all(
        DOCTYPE, filters={"year": year}, fields=["name", "employee", "special_total", *EDITABLE], limit_page_length=0)}
    rows = []
    for employee in employees:
        profile = profiles.get(employee["name"]) or {}
        rows.append({
            "employee": employee["name"], "employee_name": employee["employee_name"], "company": employee["company"],
            "department": employee.get("department"), "date_of_joining": employee.get("date_of_joining"),
            "profile": profile.get("name"), "special_total": float(profile.get("special_total") or 0),
            **{key: profile.get(key) for key in EDITABLE},
        })
    return {"year": year, "rows": rows}


@frappe.whitelist(methods=["POST"])
def save_tax_profile(employee, year, values=None):
    """新建或更新一个员工这一年的个税资料。values：EDITABLE 里的字段（JSON 或字典）。"""
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    year = _year(year)
    if not employee or not frappe.db.exists("Employee", employee):
        frappe.throw(frappe._("请选择有效员工。"))
    data = frappe.parse_json(values) if values else {}
    clean = {}
    for key in EDITABLE:
        if key not in data:
            continue
        value = data.get(key)
        if key in CHECKS:
            clean[key] = 1 if value in (1, True, "1", "true") else 0
        elif key in TEXTS:
            clean[key] = str(value or "").strip()
        elif key in INTS:
            clean[key] = int(value or 0)
        else:
            clean[key] = float(value or 0)
    name = frappe.db.get_value(DOCTYPE, {"employee": employee, "year": year})
    doc = frappe.get_doc(DOCTYPE, name) if name else frappe.new_doc(DOCTYPE)
    doc.update({"employee": employee, "year": year, **clean})
    doc.save(ignore_permissions=True)
    return {"name": doc.name, "special_total": float(doc.special_total or 0)}
