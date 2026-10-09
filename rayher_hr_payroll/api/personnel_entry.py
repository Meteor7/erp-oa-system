import json
import re
import frappe
from datetime import date

from rayher_hr_payroll.api._guards import is_hr_sensitive_hidden, require_rd_access
from rayher_hr_payroll.department_structure import (
    CANONICAL_DEPARTMENTS,
    DEPARTMENT_GROUP_BY_NAME,
)
from rayher_hr_payroll.hr_contributions import HOUSEHOLD_OPTIONS, household_classification

RD_HR_WRITE = ("System Manager", "HR User", "HR Manager")
EXPENSE_ACCOUNT_CATEGORIES = ("研发费用", "管理费用", "销售费用", "生产成本")
RD_PERSONNEL_TYPES = ("全时研发", "非全时研发", "研发辅助", "非研发")
ARCHIVE_STATUSES = ("待完善", "待确认", "已归档")
# 系统里的公司名 -> 页面上显示的名字（get_company_options 和 Excel 导入共用）
SUPPORTED_COMPANIES = {"Rayher": "示例总部", "示例研发中心": "示例研发中心"}
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
    # 员工信息页的在职/离职判断和抽屉底部「最近修改」用（不含敏感信息）。
    "status", "modified", "modified_by",
]


def _employment_status(relieving_date):
    if not relieving_date:
        return "Active"
    try:
        effective = date.fromisoformat(str(relieving_date))
    except ValueError:
        frappe.throw("离职日期格式无效。")
    current = date.fromisoformat(str(frappe.utils.today()))
    # 决定 D3（2026-09-29）：离职日当天仍在职，第二天起离职。
    return "Left" if effective < current else "Active"


@frappe.whitelist()
def list_employees():
    require_rd_access(RD_HR_WRITE)
    fields = list(EMPLOYEE_FIELDS)
    if is_hr_sensitive_hidden():
        fields = [field for field in fields if field not in {
            "default_social_insurance_base", "default_housing_fund_base",
            "social_insurance_number", "housing_fund_number",
        }]
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
    if household and household_classification(household) is None:
        frappe.throw(frappe._("户口信息无法判断为深户或非深户，请填写明确户籍地。"))
    return household


@frappe.whitelist()
def get_company_options():
    require_rd_access(RD_HR_WRITE)
    companies = frappe.get_all("Company", fields=["name", "company_name"], order_by="company_name")
    supported = SUPPORTED_COMPANIES
    return [{**row, "display_name": supported[row["name"]]} for row in companies if row.get("name") in supported]


@frappe.whitelist()
def get_dept_options():
    require_rd_access(RD_HR_WRITE)
    rows = frappe.db.sql(
        """
        SELECT d.name, d.department_name, d.company, COUNT(e.name) AS employee_count
        FROM `tabDepartment` d
        INNER JOIN `tabEmployee` e
            ON e.department = d.name AND e.status = 'Active'
        WHERE d.is_group = 0
        GROUP BY d.name, d.department_name, d.company
        """,
        as_dict=True,
    )
    order = {name: index for index, name in enumerate(CANONICAL_DEPARTMENTS)}
    result = []
    for row in rows:
        department_name = row.get("department_name")
        if department_name not in order:
            continue
        result.append({
            **row,
            "group_name": DEPARTMENT_GROUP_BY_NAME[department_name],
            "employee_count": int(row.get("employee_count") or 0),
        })
    return sorted(
        result,
        key=lambda row: (order[row["department_name"]], row.get("company") or ""),
    )


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


def _duplicate_active_name_message(employee_name, clash):
    return frappe._("已有在职员工叫「{0}」（{1}），请在姓名后加区分，例如「{0}(研发)」。").format(employee_name, clash)


def _require_unique_active_name(employee_name, exclude=None):
    """在职员工不能重名（修复 2026-09-29，审查 X3-1，决定 D1）：审批路线按姓名找主管。"""
    clash = frappe.db.get_value(
        "Employee", {"employee_name": employee_name, "status": "Active", "name": ["!=", exclude or ""]}, "name",
    )
    if clash:
        frappe.throw(_duplicate_active_name_message(employee_name, clash))


def _refuse_leaving_approver(name):
    if frappe.db.get_value("OA Approval Role Assignment", {"employee": name, "enabled": 1}, "role_label"):
        # 岗位任职人立即离职会让这个岗位的审批全部卡住，先交接（修复 2026-09-29，模块 7）。
        frappe.throw(frappe._("此人还担任审批岗位，请先在岗位任命中完成交接，再办理离职。"))


# ---------- 保存员工：整理字段 -> 写入。save_employee 和 Excel 批量导入共用这三步 ----------
_SI_HF_FIELDS = {
    "default_social_insurance_base", "default_housing_fund_base",
    "social_insurance_number", "housing_fund_number",
}


def _employee_values(name, raw):
    """把收到的原始值整理成要写入的字段；None 表示「没提供」，不写。"""
    company = raw.get("company")
    default_monthly_salary = raw.get("default_monthly_salary")
    salary_months = raw.get("salary_months")
    default_social_insurance_base = raw.get("default_social_insurance_base")
    default_housing_fund_base = raw.get("default_housing_fund_base")
    expense_account_category = raw.get("expense_account_category")
    household_registration = raw.get("household_registration")
    provided = {
        "employee_number": raw.get("employee_number"),
        "employee_name": raw.get("employee_name"),
        "company": _company(company, required=not bool(name)) if company is not None or not name else None,
        "english_name": raw.get("english_name"),
        "id_card_number_cn": raw.get("id_card_number_cn"),
        "date_of_birth": raw.get("date_of_birth"),
        "gender": raw.get("gender"),
        "date_of_joining": raw.get("date_of_joining"),
        "relieving_date": raw.get("relieving_date"),
        "rd_personnel_type": raw.get("rd_personnel_type"),
        "archive_status": raw.get("archive_status"),
        "department": raw.get("department"),
        "designation": raw.get("designation"),
        "expense_account_category": _clean_expense_category(expense_account_category) if expense_account_category is not None else None,
        "default_monthly_salary": _nonnegative("默认月基本工资", default_monthly_salary) if default_monthly_salary is not None else None,
        "salary_months": _clean_salary_months(salary_months) if salary_months is not None else None,
        "first_education_level": raw.get("first_education_level"),
        "first_education_school": raw.get("first_education_school"),
        "first_education_major": raw.get("first_education_major"),
        "education_level_cn": raw.get("education_level_cn"),
        "graduation_school": raw.get("graduation_school"),
        "major_cn": raw.get("major_cn"),
        "cell_number": raw.get("cell_number"),
        "bank_name": raw.get("bank_name"),
        "bank_ac_no": raw.get("bank_ac_no"),
        "default_social_insurance_base": _nonnegative("社保基数", default_social_insurance_base) if default_social_insurance_base is not None else None,
        "default_housing_fund_base": _nonnegative("公积金基数", default_housing_fund_base) if default_housing_fund_base is not None else None,
        "reports_to": raw.get("reports_to"), "employment_type": raw.get("employment_type"),
        "labour_contract_start_date": raw.get("labour_contract_start_date"), "probation_months": raw.get("probation_months"),
        "probation_end_date": raw.get("probation_end_date"), "first_contract_period_years": raw.get("first_contract_period_years"),
        "first_contract_end_date": raw.get("first_contract_end_date"), "contract_renewal_status": raw.get("contract_renewal_status"),
        "second_contract_period_years": raw.get("second_contract_period_years"), "second_contract_end_date": raw.get("second_contract_end_date"),
        "degree_cn": raw.get("degree_cn"), "education_completion_type": raw.get("education_completion_type"),
        "household_registration": _clean_household(household_registration) if household_registration is not None else None,
        "id_type_cn": raw.get("id_type_cn"),
        "social_insurance_number": raw.get("social_insurance_number"), "housing_fund_number": raw.get("housing_fund_number"),
    }
    return {key: value for key, value in provided.items() if value is not None}


def _default_rd_type(department):
    """新增员工没选研发人员类型时，按部门给一个默认值：研发类部门记“全时研发”，其他部门记“非研发”。
    部门没填，或不是标准部门时不补，留空。已有员工不会被改。"""
    if not department:
        return None
    group = DEPARTMENT_GROUP_BY_NAME.get(frappe.db.get_value("Department", department, "department_name"))
    if not group:
        return None
    return "全时研发" if group == "研发" else "非研发"


def _refuse_hidden_sensitive(vals):
    """受限的测试账号不能维护社保和公积金信息：有值就拒绝，空值直接丢掉。"""
    if is_hr_sensitive_hidden():
        if any(vals.get(field) not in (None, "") for field in _SI_HF_FIELDS):
            frappe.throw(frappe._("当前测试账号暂不能维护社保和公积金信息。"))
        for field in _SI_HF_FIELDS:
            vals.pop(field, None)
    return vals


def _finalize_employee_values(vals, employee_name):
    if "relieving_date" in vals:
        vals["relieving_date"] = vals["relieving_date"] or None
        vals["status"] = _employment_status(vals["relieving_date"])
    if employee_name:
        vals["first_name"] = employee_name
    if not (set(frappe.get_roles()) & {"System Manager", "HR User", "HR Manager"}):
        vals.pop("id_card_number_cn", None)
    return vals


def _write_employee(name, vals, raw):
    """新增（name 为空）或更新一个员工，走 Employee 自己的校验；不提交，由调用方决定什么时候 commit。"""
    employee_name = raw.get("employee_name")
    relieving_date = raw.get("relieving_date")
    if name:
        if not frappe.has_permission("Employee", "write", doc=name):
            frappe.throw(frappe._("您无权修改该员工。"))
        doc = frappe.get_doc("Employee", name)
        if vals.get("status") == "Left":
            _refuse_leaving_approver(name)
        doc.update(vals)
        final_name = getattr(doc, "employee_name", None) or employee_name
        if (getattr(doc, "status", None) or "Active") == "Active" and final_name:
            _require_unique_active_name(final_name, exclude=name)
        doc.save(ignore_permissions=True)
    else:
        if not frappe.has_permission("Employee", "create"):
            frappe.throw(frappe._("您无权新增员工。"))
        if _employment_status(relieving_date) == "Active" and employee_name:
            _require_unique_active_name(employee_name)
        company_value = vals.pop("company")
        if not vals.get("rd_personnel_type"):
            default_type = _default_rd_type(vals.get("department"))
            if default_type:
                vals["rd_personnel_type"] = default_type
        doc = frappe.get_doc({
            "doctype": "Employee", "company": company_value,
            "status": _employment_status(relieving_date), "relieving_date": relieving_date or None,
            "employee_number": raw.get("employee_number"),
            "employee_name": employee_name, "first_name": employee_name,
            "gender": raw.get("gender") or "Male", "date_of_birth": _birth(raw.get("id_card_number_cn")) or "1990-01-01",
            "date_of_joining": raw.get("date_of_joining") or frappe.utils.today(), **vals,
        })
        doc.insert(ignore_permissions=True)
    return doc


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
    raw = dict(locals())
    raw.pop("name", None)
    vals = _employee_values(name, raw)
    _refuse_hidden_sensitive(vals)
    _finalize_employee_values(vals, raw.get("employee_name"))
    doc = _write_employee(name, vals, raw)
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


# ---------- Excel 批量导入 ----------
# 一行一个字段：(字段名, 表头, 类型, 是否敏感)。前端 lib/personnelTransfer.js 的列要和这里一一对应（有测试对照）。
IMPORT_MAX_ROWS = 300
IMPORT_COLUMNS = (
    ("company", "所属单位", "company", False),
    ("employee_number", "员工号", "text", False),
    ("employee_name", "姓名", "text", False),
    ("english_name", "英文名", "text", False),
    ("gender", "性别", "gender", False),
    ("date_of_birth", "出生日期", "date", False),
    ("cell_number", "联系电话", "text", False),
    ("household_registration", "户口信息", "household", False),
    ("date_of_joining", "入职日期", "date", False),
    ("relieving_date", "离职日期", "date", False),
    ("department", "部门", "department", False),
    ("designation", "职位", "designation", False),
    ("reports_to", "直属主管", "supervisor", False),
    ("employment_type", "合同类型", "employment_type", False),
    ("rd_personnel_type", "研发人员类型", "rd_type", False),
    ("expense_account_category", "费用科目", "expense", False),
    ("archive_status", "归档状态", "archive", False),
    ("labour_contract_start_date", "劳动合同开始日期", "date", False),
    ("probation_months", "试用期（月）", "int", False),
    ("probation_end_date", "试用期到期日", "date", False),
    ("first_contract_period_years", "第一次合同期限（年）", "float", False),
    ("first_contract_end_date", "第一次劳动合同到期日", "date", False),
    ("contract_renewal_status", "劳动合同续签情况", "text", False),
    ("second_contract_period_years", "第二次合同期限（年）", "float", False),
    ("second_contract_end_date", "第二次劳动合同到期日", "date", False),
    ("first_education_level", "第一学历", "text", False),
    ("first_education_school", "第一学历学校", "text", False),
    ("first_education_major", "第一学历专业", "text", False),
    ("education_level_cn", "最高学历", "text", False),
    ("degree_cn", "学位", "text", False),
    ("education_completion_type", "学历完成形式", "text", False),
    ("graduation_school", "最高学历学校", "text", False),
    ("major_cn", "最高学历专业", "text", False),
    ("default_monthly_salary", "工资", "money", True),
    ("salary_months", "薪资月数", "months", True),
    ("default_social_insurance_base", "社保基数", "money", True),
    ("default_housing_fund_base", "公积金基数", "money", True),
    ("social_insurance_number", "社保电脑号", "text", True),
    ("housing_fund_number", "公积金账号", "text", True),
    ("id_type_cn", "证件类型", "text", True),
    ("id_card_number_cn", "身份证号", "text", True),
    ("bank_name", "开户行", "text", True),
    ("bank_ac_no", "银行卡号", "text", True),
)
IMPORT_KEYS = tuple(column[0] for column in IMPORT_COLUMNS)
IMPORT_LABEL = {column[0]: column[1] for column in IMPORT_COLUMNS}
IMPORT_KIND = {column[0]: column[2] for column in IMPORT_COLUMNS}
IMPORT_SENSITIVE_KEYS = frozenset(column[0] for column in IMPORT_COLUMNS if column[3])
_NUMERIC_KINDS = {"money", "months", "int", "float"}
_MASK = "••••••"
_BLANK_TEXT = "（空）"


class _RowProblem(Exception):
    """某一行、某一列的问题；消息直接给用户看。"""


def _error_text(exc):
    return re.sub(r"<[^>]+>", "", str(exc)).strip() or "校验未通过"


def _clear_message_log():
    clear = getattr(frappe, "clear_messages", None)
    if callable(clear):
        clear()


def _rule(fn, *args, **kwargs):
    """调用 save_employee 用的校验函数（不合格时会 frappe.throw），把错误变成这一行的提示，不让它冒出去。"""
    try:
        return fn(*args, **kwargs)
    except (getattr(frappe, "ValidationError", None) or Exception, ValueError, TypeError) as exc:
        _clear_message_log()
        raise _RowProblem(_error_text(exc))


def _cell_text(value):
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace(" ", " ").replace("​", "").replace("﻿", "").strip()


def _parse_number(label, text):
    cleaned = re.sub(r"[￥¥,，\s]", "", text)
    try:
        number = float(cleaned)
    except ValueError:
        raise _RowProblem("%s必须是数字（现在是“%s”）。" % (label, text))
    if number != number or number in (float("inf"), float("-inf")):
        raise _RowProblem("%s必须是数字（现在是“%s”）。" % (label, text))
    return number


def _parse_date(label, text):
    match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?", text)
    if not match:
        raise _RowProblem("%s格式不对，请写成 YYYY-MM-DD（现在是“%s”）。" % (label, text))
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        raise _RowProblem("%s不是有效日期（现在是“%s”）。" % (label, text))


def _choice(label, text, options):
    if text not in options:
        raise _RowProblem("%s“%s”不在可选范围内，可填：%s。" % (label, text, "、".join(options)))
    return text


def _display_department(value):
    return re.sub(r"\s*-\s*(RAY|SHGL)$", "", str(value or "").strip(), flags=re.I)


def _number_text(value):
    number = float(value)
    return str(int(number)) if number == int(number) else ("%.2f" % number).rstrip("0").rstrip(".")


def _load_import_rows(rows):
    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except ValueError:
            frappe.throw(frappe._("导入数据格式不对，请重新选择文件。"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        frappe.throw(frappe._("导入数据格式不对，请重新选择文件。"))
    if not rows:
        frappe.throw(frappe._("文件里没有可导入的行。"))
    if len(rows) > IMPORT_MAX_ROWS:
        frappe.throw(frappe._("一次最多导入 {0} 行，这个文件有 {1} 行，请拆开分批导入。").format(IMPORT_MAX_ROWS, len(rows)))
    return rows


class _ImportLookup:
    """导入要用到的基础资料；用到才查，整次预览每种只查一次。"""

    def __init__(self, numbers):
        self.numbers = sorted(set(numbers))
        self._existing = None
        self._directory = None
        self._departments = None
        self._designations = None
        self._employment_types = None

    def existing(self):
        if self._existing is None:
            by_number = {}
            if self.numbers:
                found = frappe.get_all(
                    "Employee", filters={"employee_number": ["in", self.numbers]},
                    fields=["name", "status"] + list(IMPORT_KEYS),
                )
                for row in found:
                    by_number.setdefault(_cell_text(row.get("employee_number")).lower(), []).append(row)
            self._existing = by_number
        return self._existing

    def directory(self):
        if self._directory is None:
            self._directory = frappe.get_all("Employee", fields=["name", "employee_number", "employee_name", "status"])
        return self._directory

    def employee_label(self, name):
        for row in self.directory():
            if row.get("name") == name:
                return row.get("employee_name") or name
        return name

    def supervisor(self, text):
        directory = self.directory()
        key = text.lower()
        hits = [row for row in directory if _cell_text(row.get("employee_number")).lower() == key]
        if not hits:
            hits = [row for row in directory if row.get("name") == text]
        if not hits:
            hits = [row for row in directory if row.get("employee_name") == text and row.get("status") == "Active"]
        if not hits:
            raise _RowProblem("直属主管“%s”找不到，请填主管的员工号或在职姓名（主管要先在系统里存在）。" % text)
        if len(hits) > 1:
            raise _RowProblem("直属主管“%s”对应多名员工，请改填员工号。" % text)
        return hits[0]["name"]

    def department(self, company, text):
        if self._departments is None:
            index = {}
            for row in frappe.get_all("Department", filters={"is_group": 0}, fields=["name", "department_name", "company"]):
                short = str(row.get("department_name") or "").strip()
                if short not in CANONICAL_DEPARTMENTS or not row.get("company"):
                    continue
                for label in {short, _display_department(row["name"]), row["name"]}:
                    index[(row["company"], label)] = row["name"]
            self._departments = index
        hit = self._departments.get((company, text)) or self._departments.get((company, _display_department(text)))
        if not hit:
            raise _RowProblem("部门“%s”不在「%s」的部门列表里。" % (text, SUPPORTED_COMPANIES.get(company, company)))
        return hit

    def designation(self, text):
        if self._designations is None:
            self._designations = {str(x).lower(): x for x in frappe.get_all("Designation", pluck="name")}
        hit = self._designations.get(text.lower())
        if not hit:
            raise _RowProblem("职位“%s”不在职位列表里，请先在系统里添加该职位。" % text)
        return hit

    def employment_type(self, text):
        if self._employment_types is None:
            self._employment_types = {str(x).lower(): x for x in frappe.get_all("Employment Type", pluck="name")}
        hit = self._employment_types.get(text.lower())
        if not hit:
            raise _RowProblem("合同类型“%s”不在合同类型列表里。" % text)
        return hit


def _company_aliases():
    aliases = {}
    for system, shown in SUPPORTED_COMPANIES.items():
        aliases[system.lower()] = system
        aliases[shown.lower()] = system
    return aliases


def _convert_import_value(key, text, lookup, company):
    """一个单元格 -> 要写入的值；不合格抛 _RowProblem。"""
    label = IMPORT_LABEL[key]
    kind = IMPORT_KIND[key]
    if kind == "text":
        return text
    if kind == "date":
        return _parse_date(label, text)
    if kind == "gender":
        value = {"男": "Male", "女": "Female", "male": "Male", "female": "Female"}.get(text.lower())
        if not value:
            raise _RowProblem("性别“%s”无法识别，请填“男”或“女”。" % text)
        return value
    if kind == "household":
        return _rule(_clean_household, text)
    if kind == "rd_type":
        return _choice(label, text, RD_PERSONNEL_TYPES)
    if kind == "archive":
        return _choice(label, text, ARCHIVE_STATUSES)
    if kind == "expense":
        return _rule(_clean_expense_category, text)
    if kind == "money":
        return _rule(_nonnegative, label, _parse_number(label, text))
    if kind == "months":
        number = _parse_number(label, text)
        return _rule(_clean_salary_months, number)
    if kind == "int":
        number = _parse_number(label, text)
        if number < 0 or not number.is_integer():
            raise _RowProblem("%s必须是非负整数（现在是“%s”）。" % (label, text))
        return int(number)
    if kind == "float":
        number = _parse_number(label, text)
        if number < 0:
            raise _RowProblem("%s不能为负数。" % label)
        return number
    if kind == "designation":
        return lookup.designation(text)
    if kind == "employment_type":
        return lookup.employment_type(text)
    if kind == "department":
        return lookup.department(company, text)
    if kind == "supervisor":
        return lookup.supervisor(text)
    raise _RowProblem("%s暂不支持导入。" % label)


def _same_value(kind, old, new):
    if kind in _NUMERIC_KINDS:
        try:
            return abs(float(old or 0) - float(new or 0)) < 1e-9
        except (TypeError, ValueError):
            return False
    return str(old if old is not None else "").strip() == str(new if new is not None else "").strip()


def _change_text(key, value, lookup):
    kind = IMPORT_KIND[key]
    if value is None or str(value).strip() == "" or (kind in _NUMERIC_KINDS and float(value or 0) == 0):
        return _BLANK_TEXT
    if key in IMPORT_SENSITIVE_KEYS:
        return _MASK
    if kind == "gender":
        return {"Male": "男", "Female": "女"}.get(value, str(value))
    if kind == "department":
        return _display_department(value)
    if kind == "supervisor":
        return lookup.employee_label(value)
    if kind in _NUMERIC_KINDS:
        return _number_text(value)
    return str(value)


def _date_problems(final, today):
    problems = []
    birth, joining, relieving = final.get("date_of_birth"), final.get("date_of_joining"), final.get("relieving_date")
    if birth and str(birth) > today:
        problems.append("出生日期不能晚于今天。")
    if birth and joining and str(birth) >= str(joining):
        problems.append("入职日期必须晚于出生日期。")
    if joining and relieving and str(relieving) < str(joining):
        problems.append("离职日期不能早于入职日期。")
    return problems


def _plan_employee_import(rows):
    """逐行检查导入文件，算出每行是新增、更新、无变化还是有问题；只读，不写库。预览和正式导入都走这里。"""
    rows = _load_import_rows(rows)
    hidden = is_hr_sensitive_hidden()
    hr_role = bool(set(frappe.get_roles()) & {"System Manager", "HR User", "HR Manager"})
    aliases = _company_aliases()
    today = str(frappe.utils.today())

    prepared = []
    for index, raw_row in enumerate(rows):
        try:
            number = int(raw_row.get("_row") or 0) or index + 2
        except (TypeError, ValueError):
            number = index + 2
        cells = {}
        for key in IMPORT_KEYS:
            text = _cell_text(raw_row.get(key))
            if text:
                cells[key] = text
        prepared.append((number, cells))

    lookup = _ImportLookup([cells["employee_number"] for _, cells in prepared if cells.get("employee_number")])
    seen = {}
    for number, cells in prepared:
        if cells.get("employee_number"):
            seen.setdefault(cells["employee_number"].lower(), []).append(number)

    can_create = None
    plans = []
    for number, cells in prepared:
        plan = {
            "row": number, "status": "error", "employee_number": cells.get("employee_number", ""),
            "employee_name": cells.get("employee_name", ""), "name": "", "errors": [], "warnings": [],
            "changes": [], "vals": {}, "labels": [],
        }
        plans.append(plan)
        errors, warnings = plan["errors"], plan["warnings"]
        if not cells:
            errors.append("整行是空的。")
            continue
        employee_number = cells.get("employee_number")
        if not employee_number:
            errors.append("员工号必填：导入靠员工号判断是新增还是更新。")
            continue
        if employee_number.startswith("示例"):
            errors.append("这是模板里的示例行，请删除，或改成真实数据。")
            continue
        key = employee_number.lower()
        if len(seen.get(key, [])) > 1:
            others = "、".join(str(n) for n in seen[key] if n != number)
            errors.append("员工号“%s”在文件里重复（还出现在第 %s 行）。" % (employee_number, others))
            continue
        matches = lookup.existing().get(key, [])
        if len(matches) > 1:
            errors.append("系统里有 %d 名员工使用员工号“%s”，请先在员工信息里处理重复。" % (len(matches), employee_number))
            continue
        existing = matches[0] if matches else None
        plan["name"] = existing["name"] if existing else ""

        # 所属单位
        company = existing.get("company") if existing else None
        if "company" in cells:
            system = aliases.get(cells["company"].lower())
            if not system:
                errors.append("所属单位“%s”无效，可填：%s。" % (cells["company"], "、".join(SUPPORTED_COMPANIES.values())))
                continue
            try:
                _rule(_company, system, True)
            except _RowProblem as problem:
                errors.append(str(problem))
                continue
            if existing and system != existing.get("company"):
                errors.append("员工号“%s”已经属于「%s」，和文件里的所属单位不一致。" % (
                    employee_number, SUPPORTED_COMPANIES.get(existing.get("company"), existing.get("company"))))
                continue
            company = system
        elif not existing:
            errors.append("新增员工必须填写所属单位。")
            continue

        # 敏感列：没有权限的账号只警告、不写入
        ignored = [k for k in cells if k in IMPORT_SENSITIVE_KEYS and (hidden or (k == "id_card_number_cn" and not hr_role))]
        if ignored:
            warnings.append("当前账号没有敏感信息权限，已忽略这些列：%s。" % "、".join(IMPORT_LABEL[k] for k in ignored))

        vals = {}
        for key_name, text in cells.items():
            if key_name in ("company", "employee_number") or key_name in ignored:
                continue
            try:
                vals[key_name] = _convert_import_value(key_name, text, lookup, company)
            except _RowProblem as problem:
                errors.append(str(problem))
        if existing and vals.get("reports_to") and vals["reports_to"] == existing["name"]:
            errors.append("直属主管不能是本人。")
        if errors:
            continue

        if existing:
            for key_name in list(vals):
                if _same_value(IMPORT_KIND[key_name], existing.get(key_name), vals[key_name]):
                    del vals[key_name]
            for key_name, value in vals.items():
                plan["changes"].append({
                    "field": key_name, "label": IMPORT_LABEL[key_name],
                    "old": _change_text(key_name, existing.get(key_name), lookup),
                    "new": _change_text(key_name, value, lookup),
                    "sensitive": key_name in IMPORT_SENSITIVE_KEYS,
                })
            final = {**existing, **vals}
            touched = set(vals)
        else:
            vals["employee_number"] = employee_number
            vals["company"] = company
            for key_name, label in (("employee_name", "姓名"), ("date_of_joining", "入职日期")):
                if not vals.get(key_name):
                    errors.append("新增员工必须填写%s。" % label)
            if "gender" not in vals:
                warnings.append("性别没填，系统会按默认记为“男”。")
            if "date_of_birth" not in vals and not _birth(vals.get("id_card_number_cn")):
                warnings.append("出生日期没填，系统会按默认记为 1990-01-01。")
            if not vals.get("rd_personnel_type"):
                default_type = _default_rd_type(vals.get("department"))
                if default_type:
                    vals["rd_personnel_type"] = default_type
                    warnings.append("研发人员类型没填，会按部门记为“%s”。" % default_type)
            final = {**vals}
            final.setdefault("date_of_birth", _birth(vals.get("id_card_number_cn")) or "1990-01-01")
            touched = set(final)
            plan["labels"] = [IMPORT_LABEL[k] for k in IMPORT_KEYS if k in vals]
        if errors:
            continue

        if touched & {"date_of_birth", "date_of_joining", "relieving_date"}:
            errors.extend(_date_problems(final, today))
        if final.get("archive_status") == "已归档" and (not existing or touched & {"archive_status", "id_card_number_cn", "date_of_joining", "department"}):
            from rayher_hr_payroll.employee_controls import _archive_problems
            problems = _archive_problems(final)
            if problems:
                errors.append("无法归档，信息不完整：" + "；".join(problems))
        if "relieving_date" in vals and _employment_status(vals["relieving_date"]) == "Left" and existing:
            try:
                _rule(_refuse_leaving_approver, existing["name"])
            except _RowProblem as problem:
                errors.append(str(problem))
        if existing and vals and not frappe.has_permission("Employee", "write", doc=existing["name"]):
            errors.append("您无权修改该员工。")
        if not existing:
            if can_create is None:
                can_create = bool(frappe.has_permission("Employee", "create"))
            if not can_create:
                errors.append("您无权新增员工。")
        if errors:
            continue
        plan["vals"] = vals
        plan["employee_name"] = vals.get("employee_name") or (existing or {}).get("employee_name") or ""
        plan["status"] = ("update" if vals else "unchanged") if existing else "create"
        plan["existing_status"] = (existing or {}).get("status")

    _check_active_name_clashes(plans, lookup)
    return plans


def _final_active_name(plan):
    """这一行写完之后，这个人是不是在职、叫什么；不在职或名字没变的人不需要查重名。"""
    vals = plan["vals"]
    if plan["status"] == "create":
        status = _employment_status(vals.get("relieving_date"))
        return vals.get("employee_name") if status == "Active" else None
    if plan["status"] != "update":
        return None
    changes_status = "relieving_date" in vals
    status = _employment_status(vals["relieving_date"]) if changes_status else (plan.get("existing_status") or "Active")
    if status != "Active":
        return None
    if "employee_name" in vals or (changes_status and plan.get("existing_status") != "Active"):
        return plan["employee_name"]
    return None


def _check_active_name_clashes(plans, lookup):
    """在职员工不能重名：和系统里的在职员工比，也和同一个文件里别的行比（和 save_employee 的规则一致）。"""
    seen = {}
    for plan in plans:
        name = _final_active_name(plan)
        if name:
            seen.setdefault(name, []).append(plan)
    for name, group in seen.items():
        if len(group) > 1:
            lines = "、".join(str(p["row"]) for p in group)
            for plan in group:
                plan["errors"].append("文件里第 %s 行的在职员工都叫“%s”，在职员工不能重名，请在姓名后加区分。" % (lines, name))
                plan["status"] = "error"
            continue
        plan = group[0]
        for row in lookup.directory():
            if row.get("employee_name") == name and row.get("status") == "Active" and row.get("name") != plan["name"]:
                plan["errors"].append(_error_text(_duplicate_active_name_message(name, row["name"])))
                plan["status"] = "error"
                break


def _public_row(plan):
    return {key: plan[key] for key in ("row", "status", "employee_number", "employee_name", "name", "errors", "warnings", "changes", "labels")}


def _import_summary(plans):
    counts = {"create": 0, "update": 0, "unchanged": 0, "error": 0}
    for plan in plans:
        counts[plan["status"]] += 1
    return {
        "total": len(plans), **counts,
        "warnings": sum(1 for plan in plans if plan["warnings"]),
        "sensitive_ignored": bool(is_hr_sensitive_hidden()),
    }


@frappe.whitelist(methods=["POST"])
def preview_employee_import(rows=None):
    """只读：检查导入文件，告诉前端每行会新增、更新、无变化还是有问题；不写任何数据。
    行数据可能有几百行，所以用 POST。"""
    require_rd_access(RD_HR_WRITE)
    plans = _plan_employee_import(rows)
    return {"summary": _import_summary(plans), "rows": [_public_row(plan) for plan in plans], "max_rows": IMPORT_MAX_ROWS}


@frappe.whitelist(methods=["POST"])
def import_employees(rows=None):
    """正式导入：服务端重新检查一遍（不信任前端的预览结果），有任何问题行就整份拒绝；
    没问题就在同一个事务里逐个写入，中途任何一行失败都会全部撤销。"""
    require_rd_access(RD_HR_WRITE)
    plans = _plan_employee_import(rows)
    bad = [plan for plan in plans if plan["status"] == "error"]
    if bad:
        shown = "；".join("第 %d 行：%s" % (plan["row"], "".join(plan["errors"][:2])) for plan in bad[:3])
        frappe.throw(frappe._("导入文件还有 {0} 行有问题，整份都没有导入。{1}{2}").format(
            len(bad), shown, "……" if len(bad) > 3 else ""))
    todo = [plan for plan in plans if plan["status"] in ("create", "update")]
    unchanged = sum(1 for plan in plans if plan["status"] == "unchanged")
    if not todo:
        frappe.throw(frappe._("文件里的内容和系统里现有的完全一致，没有需要导入的变化。"))
    created = updated = 0
    names = []
    current = None
    try:
        for plan in todo:
            current = plan
            vals = dict(plan["vals"])
            raw = dict(vals)
            if plan["status"] == "update":
                raw.setdefault("employee_name", plan["employee_name"])
            _finalize_employee_values(vals, vals.get("employee_name"))
            doc = _write_employee(plan["name"] or None, vals, raw)
            if plan["status"] == "create":
                created += 1
                note = "批量导入（Excel）：新增"
            else:
                updated += 1
                note = "批量导入（Excel）：更新 " + "、".join(change["label"] for change in plan["changes"])
            doc.add_comment("Info", note)
            names.append(doc.name)
    except Exception as exc:
        frappe.db.rollback()
        _clear_message_log()
        where = "第 %d 行" % current["row"] if current else "导入"
        frappe.throw(frappe._("{0}写入失败，本次导入已全部撤销：{1}").format(where, _error_text(exc)))
    frappe.db.commit()
    return {"created": created, "updated": updated, "unchanged": unchanged, "names": names}
