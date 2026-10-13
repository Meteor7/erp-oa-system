"""社保 / 公积金工作台共用的接口：全员基数表、改基数和户口、薪酬就绪情况。

差异核对和生效在各自的导入接口里（social_insurance_import_entry / housing_fund_import_entry）；
这里是第三步"基数与金额"和第四步"进入薪酬"要用的数据。
"""
import frappe
from rayher_hr_payroll.api._guards import require_hr_sensitive_access, require_rd_access
from rayher_hr_payroll.hr_read_access import require_hr_read
from rayher_hr_payroll.api.housing_fund_import_entry import _save_monthly_record
from rayher_hr_payroll.api.social_insurance_import_entry import SUPPORTED_COMPANIES, _company
from rayher_hr_payroll.hr_contributions import (
    HOUSEHOLD_OPTIONS,
    calculate_social_snapshot,
    household_classification,
    housing_fund_amounts,
    social_policy,
)
from rayher_hr_payroll.housing_fund_import import DEFAULT_COMPANY_RATE, DEFAULT_EMPLOYEE_RATE, canonical_period

ROLES = ("System Manager", "HR User", "HR Manager")
BASE_FIELD = {"si": "default_social_insurance_base", "fund": "default_housing_fund_base"}
KIND_LABEL = {"si": "社保", "fund": "公积金"}
MISSING_LIST_LIMIT = 200


def _kind(value):
    value = str(value or "").strip()
    if value not in BASE_FIELD:
        frappe.throw(frappe._("类型只能是社保或公积金。"))
    return value


def _previous_period(period):
    year, month = int(period[:4]), int(period[5:7])
    return f"{year - 1:04d}-12" if month == 1 else f"{year:04d}-{month - 1:02d}"


def _number(value):
    return float(value) if value not in (None, "") else None


def _employees(company):
    filters = {"status": "Active", "company": company if company else ["in", list(SUPPORTED_COMPANIES)]}
    return frappe.get_all(
        "Employee", filters=filters, order_by="company, employee_name",
        fields=["name", "employee_name", "company", "department", "household_registration", "date_of_joining",
                "default_social_insurance_base", "default_housing_fund_base"],
    )


def _social_prev_bases(prev):
    bases = {}
    batch = frappe.db.get_value("Social Insurance Import Batch", {"period": prev, "is_current": 1}, "name")
    if batch:
        for row in frappe.get_all("Social Insurance Import Row", filters={"batch": batch, "status": ["in", ["Matched", "Confirmed Difference"]]},
                                  fields=["employee", "contribution_base"]):
            if row.get("employee"):
                bases[row["employee"]] = row["contribution_base"]
    for row in frappe.get_all("Employee Social Insurance", filters={"period": prev}, fields=["employee", "contribution_base"]):
        bases.setdefault(row["employee"], row["contribution_base"])
    return bases


@frappe.whitelist()
def get_base_table(kind, period, company=None):
    """全员的本月基数：本月已有的月度记录优先，其次档案默认基数；金额按后台算法复算。"""
    require_hr_read(ROLES, require_rd_access)
    require_hr_sensitive_access()
    kind, period, company = _kind(kind), canonical_period(period), _company(company, allow_all=True)
    prev = _previous_period(period)
    rows = []
    if kind == "fund":
        month = {r["employee"]: r for r in frappe.get_all("Employee Housing Fund", filters={"period": period}, fields=["employee", "contribution_base", "employee_rate", "company_rate"])}
        previous = {r["employee"]: r["contribution_base"] for r in frappe.get_all("Employee Housing Fund", filters={"period": prev}, fields=["employee", "contribution_base"])}
    else:
        month = {r["employee"]: r for r in frappe.get_all("Employee Social Insurance", filters={"period": period}, fields=["employee", "contribution_base"])}
        previous = _social_prev_bases(prev)
    for employee in _employees(company):
        record = month.get(employee["name"])
        default = employee.get(BASE_FIELD[kind])
        base = record["contribution_base"] if record else default
        source = f"{period}月度记录" if record else "员工档案默认基数"
        household = household_classification(employee.get("household_registration"))
        item = {
            "employee": employee["name"], "employee_name": employee["employee_name"], "company": employee["company"],
            "department": employee.get("department"), "date_of_joining": employee.get("date_of_joining"),
            "household": employee.get("household_registration") or "", "household_classification": "深户" if household is True else "非深户" if household is False else "待完善",
            "base": _number(base) if base else None, "base_source": source if base else "未维护", "prev_base": _number(previous.get(employee["name"])),
            "employee_amount": None, "company_amount": None, "note": "",
        }
        if base and float(base) > 0:
            if kind == "fund":
                amounts = housing_fund_amounts(base, (record or {}).get("employee_rate") or DEFAULT_EMPLOYEE_RATE, (record or {}).get("company_rate") or DEFAULT_COMPANY_RATE)
                item.update({"employee_amount": float(amounts["employee_amount"]), "company_amount": float(amounts["company_amount"])})
            else:
                policy = social_policy(employee["company"], period)
                if household is None:
                    item["note"] = "户口未维护，无法复算"
                elif policy is None:
                    item["note"] = "所属公司社保政策未配置"
                else:
                    snapshot = calculate_social_snapshot(base, household, policy)
                    item.update({"employee_amount": float(snapshot["employee_total"]), "company_amount": float(snapshot["company_total"]), "policy_version": policy["version"]})
        rows.append(item)
    return {"kind": kind, "period": period, "rows": rows, "household_options": list(HOUSEHOLD_OPTIONS)}


def _comment(employee, text):
    frappe.get_doc("Employee", employee).add_comment("Info", text)


@frappe.whitelist(methods=["POST"])
def save_employee_base(kind, employee, base, period=None):
    """改一个人的基数：写进员工档案（下个月自动沿用）；本月已有公积金月度记录的同步改，免得薪酬读到旧数。"""
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    kind = _kind(kind)
    if not employee or not frappe.db.exists("Employee", employee):
        frappe.throw(frappe._("请选择有效员工。"))
    try:
        value = float(base)
    except (TypeError, ValueError):
        frappe.throw(frappe._("基数必须是数字。"))
    if value < 0:
        frappe.throw(frappe._("基数不能为负数。"))
    period = canonical_period(period) if period else None
    old = frappe.db.get_value("Employee", employee, BASE_FIELD[kind])
    if kind == "si" and period and frappe.db.exists("Employee Social Insurance", {"employee": employee, "period": period}):
        frappe.throw(frappe._("该员工本月已有手工维护的社保月度记录，请先在月度记录里处理。"))
    frappe.db.set_value("Employee", employee, BASE_FIELD[kind], value)
    if kind == "fund" and period:
        record = frappe.db.get_value("Employee Housing Fund", {"employee": employee, "period": period}, ["employee_rate", "company_rate", "remark"], as_dict=True)
        if record:
            _save_monthly_record(period, employee, value, record["employee_rate"] or DEFAULT_EMPLOYEE_RATE, record["company_rate"] or DEFAULT_COMPANY_RATE, record.get("remark") or "")
    _comment(employee, f"{KIND_LABEL[kind]}基数由 {old or 0} 调整为 {value}（{frappe.session.user}）")
    frappe.db.commit()
    return {"employee": employee, "base": value}


@frappe.whitelist(methods=["POST"])
def save_employee_household(employee, household):
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    household = str(household or "").strip()
    if household not in HOUSEHOLD_OPTIONS:
        frappe.throw(frappe._("户口只能选择：{0}。").format("、".join(HOUSEHOLD_OPTIONS)))
    if not employee or not frappe.db.exists("Employee", employee):
        frappe.throw(frappe._("请选择有效员工。"))
    old = frappe.db.get_value("Employee", employee, "household_registration")
    frappe.db.set_value("Employee", employee, "household_registration", household)
    _comment(employee, f"户口由 {old or '未维护'} 改为 {household}（{frappe.session.user}）")
    frappe.db.commit()
    return {"employee": employee, "household": household}


@frappe.whitelist()
def get_payroll_readiness(period):
    """薪酬计算要求每个在职员工本月都有社保和公积金记录；这里告诉 HR 还差谁。"""
    require_hr_read(ROLES, require_rd_access)
    require_hr_sensitive_access()
    period = canonical_period(period)
    employees = _employees(None)
    fund_ready = {r["employee"] for r in frappe.get_all("Employee Housing Fund", filters={"period": period}, fields=["employee"])}
    social_ready = {r["employee"] for r in frappe.get_all("Employee Social Insurance", filters={"period": period}, fields=["employee"])}
    batch = frappe.db.get_value("Social Insurance Import Batch", {"period": period, "is_current": 1}, "name")
    if batch:
        social_ready |= {r["employee"] for r in frappe.get_all(
            "Social Insurance Import Row", filters={"batch": batch, "status": ["in", ["Matched", "Confirmed Difference"]]}, fields=["employee"]) if r.get("employee")}
    result = {"period": period, "total": len(employees), "kinds": {}}
    for kind, ready in (("si", social_ready), ("fund", fund_ready)):
        missing = [{"employee": e["name"], "employee_name": e["employee_name"], "company": e["company"]} for e in employees if e["name"] not in ready]
        result["kinds"][kind] = {"label": KIND_LABEL[kind], "ready": len(employees) - len(missing), "missing_count": len(missing), "missing": missing[:MISSING_LIST_LIMIT]}
    result["payroll_ready"] = all(not item["missing_count"] for item in result["kinds"].values())
    return result
