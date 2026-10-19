import re

TARGET_COMPANY = "示例研发中心"
TARGET_ABBR = "SHGL"
TARGET_EMPLOYEES = (
    "演示员工201",
    "演示员工109",
    "演示员工219",
    "演示员工226",
    "演示员工155",
    "演示员工230",
)


def target_department_name(value):
    base = re.sub(r"\s*-\s*(RAY|SHGL)$", "", str(value or "").strip(), flags=re.I)
    return f"{base} - {TARGET_ABBR}"


def _ensure_company(frappe):
    if frappe.db.exists("Company", TARGET_COMPANY):
        return frappe.get_doc("Company", TARGET_COMPANY)
    return frappe.get_doc({
        "doctype": "Company",
        "company_name": TARGET_COMPANY,
        "abbr": TARGET_ABBR,
        "default_currency": "CNY",
        "country": "China",
        "create_chart_of_accounts_based_on": "Standard Template",
        "chart_of_accounts": "Standard",
    }).insert(ignore_permissions=True)


def _ensure_department(frappe, source_department):
    source = frappe.get_doc("Department", source_department)
    target_name = target_department_name(source.name)
    if frappe.db.exists("Department", target_name):
        return target_name
    department_name = re.sub(r"\s*-\s*(RAY|SHGL)$", "", source.department_name or source.name, flags=re.I)
    doc = frappe.get_doc({
        "doctype": "Department",
        "department_name": department_name,
        "company": TARGET_COMPANY,
        "is_group": 0,
        "parent_department": "All Departments",
    })
    doc.insert(ignore_permissions=True)
    return doc.name


def execute():
    import frappe

    employees = frappe.get_all(
        "Employee",
        filters={"employee_name": ["in", TARGET_EMPLOYEES]},
        fields=["name", "employee_name", "company", "department"],
        order_by="employee_name",
    )
    found = {row["employee_name"]: row for row in employees}
    missing = [name for name in TARGET_EMPLOYEES if name not in found]
    duplicates = [name for name in TARGET_EMPLOYEES if sum(row["employee_name"] == name for row in employees) != 1]
    if missing or duplicates:
        frappe.throw(f"示例研发中心员工校验失败，缺失：{','.join(missing) or '无'}；重复：{','.join(duplicates) or '无'}")
    if any(not row.get("department") for row in employees):
        frappe.throw("示例研发中心员工校验失败：存在未设置部门的员工")

    _ensure_company(frappe)
    department_map = {
        row["department"]: _ensure_department(frappe, row["department"])
        for row in employees
    }
    for row in employees:
        doc = frappe.get_doc("Employee", row["name"])
        doc.company = TARGET_COMPANY
        doc.department = department_map[row["department"]]
        doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {
        "company": TARGET_COMPANY,
        "employees": sorted(TARGET_EMPLOYEES),
        "departments": sorted(set(department_map.values())),
    }
