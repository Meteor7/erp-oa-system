from collections import OrderedDict


DEPARTMENT_GROUPS = OrderedDict({
    "客户运营": ("销售部", "客服部"),
    "研发": (
        "知识产权部", "研发软件部", "研发算法部", "研发光学部",
        "研发机械部", "研发电气部", "研发系统部", "研发AI部", "研发部",
    ),
    "运营": ("制造部", "仓库部", "采购部", "物控部"),
    "职能": ("总经办", "人事行政部", "财务部", "项目申报部", "IT部"),
})
CANONICAL_DEPARTMENTS = tuple(
    department
    for departments in DEPARTMENT_GROUPS.values()
    for department in departments
)
DEPARTMENT_GROUP_BY_NAME = {
    department: group_name
    for group_name, departments in DEPARTMENT_GROUPS.items()
    for department in departments
}

DEPARTMENT_MEMBERS = {
    "知识产权部": {"演示员工183", "演示员工187"},
    "研发机械部": {"演示员工242", "演示员工234", "演示员工212", "演示员工239", "演示员工211", "演示员工232"},
    "研发电气部": {"演示员工172", "演示员工159", "演示员工145"},
    "研发光学部": {"演示员工107", "演示员工238", "演示员工228", "演示员工231", "演示员工161", "演示员工236"},
    "研发算法部": {"演示员工108", "演示员工206", "演示员工217", "演示员工248", "演示员工244", "演示员工205", "演示员工221", "演示员工227", "演示员工210", "演示员工222", "演示员工204"},
    "研发软件部": {"演示员工132", "演示员工150", "演示员工117", "演示员工112", "演示员工142", "演示员工235", "演示员工208", "演示员工246", "演示员工134", "演示员工240", "演示员工233", "演示员工184", "演示员工220", "演示员工229", "演示员工186"},
    "研发系统部": {"南通工厂7", "演示员工207", "演示员工237", "演示员工203"},
    "研发AI部": {"演示员工218", "演示员工247", "演示员工209", "演示员工243"},
    "研发部": {"演示员工215"},
    "客服部": {"演示员工158", "演示员工109", "演示员工219", "演示员工226", "演示员工230", "演示员工202", "演示员工224", "演示员工213"},
    "销售部": {"演示员工155", "演示员工201"},
    "制造部": {"演示员工241", "演示员工214", "演示员工223"},
    "仓库部": {"演示员工245"},
    "采购部": {"演示员工216"},
    "物控部": {"演示员工178"},
    "人事行政部": {"演示员工10", "演示员工30", "演示员工38"},
    "财务部": {"演示员工16", "演示员工13", "演示员工19", "演示员工32"},
    "项目申报部": {"演示员工225"},
    "IT部": {"演示员工18"},
    "总经办": {"演示员工29", "演示员工21"},
}
DEPARTMENT_BY_EMPLOYEE = {
    employee_name: department
    for department, employees in DEPARTMENT_MEMBERS.items()
    for employee_name in employees
}

_DESIGNATION_RULES = (
    ("测试", "研发软件部"),
    ("FSE", "客服部"),
    ("现场服务", "客服部"),
    ("FAE", "客服部"),
    ("现场应用", "客服部"),
    ("系统", "研发系统部"),
    ("光学", "研发光学部"),
    ("算法", "研发算法部"),
    ("软件", "研发软件部"),
    ("机械", "研发机械部"),
    ("电气", "研发电气部"),
    ("工艺", "研发部"),
    ("知识产权", "知识产权部"),
    ("专利", "知识产权部"),
    ("AI", "研发AI部"),
    ("销售", "销售部"),
    ("生产", "制造部"),
    ("装配", "制造部"),
    ("仓库", "仓库部"),
    ("采购", "采购部"),
    ("物控", "物控部"),
    ("项目申报", "项目申报部"),
    ("人事", "人事行政部"),
    ("行政", "人事行政部"),
    ("财务", "财务部"),
    ("会计", "财务部"),
    ("出纳", "财务部"),
    ("网络", "IT部"),
)


def _clean(value):
    return str(value or "").strip()


# 笼统的旧部门名，需要按花名册/职务细分到具体部门。
GENERIC_DEPARTMENTS = {"研发部"}


def department_for_employee(employee_name, designation="", current_department=""):
    employee = _clean(employee_name)
    current = _clean(current_department)
    # 修复（2026-09-29，模块 7，决定 D5）：已经是正式的具体部门就以它为准（人事调岗后
    # 导入或部门同步不再按旧花名册改回去）；只有空、旧部门名或笼统的"研发部"才按下面规则推断。
    if current in CANONICAL_DEPARTMENTS and current not in GENERIC_DEPARTMENTS:
        return current
    if employee in DEPARTMENT_BY_EMPLOYEE:
        return DEPARTMENT_BY_EMPLOYEE[employee]

    job_title = _clean(designation)
    for keyword, department in _DESIGNATION_RULES:
        if keyword.lower() in job_title.lower():
            return department

    return current if current in CANONICAL_DEPARTMENTS else ""


# 部门的费用性质（采购申请的非项目采购按所选部门取这个类别）。和人员费用科目现在的做法一致：
# 研发部门记研发费用，销售、客服记销售费用，制造部记生产成本，其余（职能、仓库、采购、物控）记管理费用。
EXPENSE_CATEGORY_BY_GROUP = {"研发": "研发费用", "客户运营": "销售费用", "运营": "管理费用", "职能": "管理费用"}
EXPENSE_CATEGORY_BY_DEPARTMENT = {"制造部": "生产成本"}


def department_base_name(department):
    """"研发软件部 - RAY" → "研发软件部"（Department 的名字后面带公司缩写）。"""
    text = _clean(department)
    return text.rsplit(" - ", 1)[0].strip() if " - " in text else text


def department_expense_category(department):
    """部门对应的费用类别；不是正式部门（旧的英文部门等）返回空。"""
    base = department_base_name(department)
    if base in EXPENSE_CATEGORY_BY_DEPARTMENT:
        return EXPENSE_CATEGORY_BY_DEPARTMENT[base]
    return EXPENSE_CATEGORY_BY_GROUP.get(DEPARTMENT_GROUP_BY_NAME.get(base), "")
