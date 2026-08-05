from collections import OrderedDict


DEPARTMENT_GROUPS = OrderedDict({
    "客户运营": ("销售部", "应用部", "现场服务部"),
    "研发": (
        "知识产权部", "机械部", "电气部", "工艺部", "光学部",
        "算法部", "软件部", "测试部", "系统工程部",
    ),
    "运营": ("制造部", "仓库部", "采购部", "物控部", "AI部"),
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
    "机械部": {"演示员工242", "演示员工234", "演示员工212", "演示员工239", "演示员工211", "演示员工232"},
    "电气部": {"演示员工172", "演示员工159", "演示员工145"},
    "工艺部": {"演示员工215"},
    "光学部": {"演示员工107", "演示员工238", "演示员工228", "演示员工231", "演示员工161", "演示员工236"},
    "算法部": {"演示员工108", "演示员工206", "演示员工217", "演示员工248", "演示员工244", "演示员工205", "演示员工221", "演示员工227", "演示员工210", "演示员工222", "演示员工204"},
    "软件部": {"演示员工132", "演示员工150", "演示员工117", "演示员工112", "演示员工142", "演示员工235", "演示员工208", "演示员工246", "演示员工134", "演示员工240", "演示员工233", "演示员工184", "演示员工220", "演示员工229"},
    "测试部": {"演示员工186"},
    "系统工程部": {"演示员工127", "演示员工207", "演示员工237"},
    "AI部": {"演示员工218", "演示员工247", "演示员工209", "演示员工243"},
    "应用部": {"演示员工158", "演示员工109", "演示员工219", "演示员工226", "演示员工230"},
    "现场服务部": {"演示员工202", "演示员工224", "演示员工213"},
    "销售部": {"演示员工155", "演示员工201"},
    "制造部": {"演示员工241", "演示员工214", "演示员工223"},
    "仓库部": {"演示员工245"},
    "采购部": {"演示员工216"},
    "物控部": {"演示员工178"},
    "人事行政部": {"演示员工10", "演示员工30", "演示员工38"},
    "财务部": {"演示员工16", "演示员工13", "演示员工19", "演示员工32"},
    "项目申报部": {"演示员工225"},
    "IT部": {"演示员工18"},
    "总经办": {"演示员工29", "演示员工21", "演示员工182"},
}
DEPARTMENT_BY_EMPLOYEE = {
    employee_name: department
    for department, employees in DEPARTMENT_MEMBERS.items()
    for employee_name in employees
}

_DESIGNATION_RULES = (
    ("测试", "测试部"),
    ("FSE", "现场服务部"),
    ("现场服务", "现场服务部"),
    ("FAE", "应用部"),
    ("现场应用", "应用部"),
    ("系统", "系统工程部"),
    ("光学", "光学部"),
    ("算法", "算法部"),
    ("软件", "软件部"),
    ("机械", "机械部"),
    ("电气", "电气部"),
    ("工艺", "工艺部"),
    ("知识产权", "知识产权部"),
    ("专利", "知识产权部"),
    ("AI", "AI部"),
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


def department_for_employee(employee_name, designation="", current_department=""):
    employee = _clean(employee_name)
    if employee in DEPARTMENT_BY_EMPLOYEE:
        return DEPARTMENT_BY_EMPLOYEE[employee]

    job_title = _clean(designation)
    for keyword, department in _DESIGNATION_RULES:
        if keyword.lower() in job_title.lower():
            return department

    current = _clean(current_department)
    return current if current in CANONICAL_DEPARTMENTS else ""