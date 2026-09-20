"""Source-controlled organization corrections based on the 2026-08-22 employee workbook."""

from __future__ import annotations

from datetime import date

from rayher_hr_payroll.department_structure import DEPARTMENT_BY_EMPLOYEE
from rayher_hr_payroll.oa_organization import DIRECT_SUPERVISOR_BY_EMPLOYEE, TOP_EXECUTIVES


EFFECTIVE_LEAVING_DATES = {
    "演示员工215": "2026-07-10",
    "演示员工204": "2026-07-17",
    "演示员工13": "2026-08-07",
    "演示员工222": "2026-08-15",
    "演示员工223": "2026-08-14",
    "演示员工247": "2026-08-14",
    "演示员工10": "2026-08-31",
}
REMOVED_EMPLOYEES = ("演示员工182",)
LEGACY_DEPARTMENT_NAMES = {
    "AI部", "仓库", "光学部", "客户服务部", "工艺部", "应用部",
    "机械部", "测试部", "现场服务部", "生产部", "电气部", "算法部",
    "系统工程部", "系统部", "软件部",
}
NEW_EMPLOYEES = {
    "演示员工203": {
        "company": "Rayher",
        "department": "研发系统部",
        "designation": "系统工程师",
        "date_of_joining": "2026-08-14",
        # The source workbook has no birth date or gender. These placeholders keep
        # ERPNext's mandatory fields explicit until HR supplies the real values.
        "date_of_birth": "1990-01-01",
        "gender": "Male",
    },
}


def _clean(value):
    return str(value or "").strip()


def _ensure_department(frappe, department_name, company):
    name = frappe.db.get_value(
        "Department",
        {"department_name": department_name, "company": company, "is_group": 0},
        "name",
    )
    if name:
        if frappe.db.get_value("Department", name, "disabled"):
            frappe.db.set_value("Department", name, "disabled", 0, update_modified=False)
        return name
    doc = frappe.get_doc({
        "doctype": "Department",
        "department_name": department_name,
        "company": company,
        "is_group": 0,
    })
    doc.insert(ignore_permissions=True)
    return doc.name


def _ensure_designation(frappe, designation):
    if not frappe.db.exists("Designation", designation):
        frappe.get_doc({"doctype": "Designation", "designation_name": designation}).insert(
            ignore_permissions=True
        )
    return designation


def _employee_index(frappe):
    rows = frappe.get_all(
        "Employee",
        fields=["name", "employee_name", "company", "status", "reports_to"],
        order_by="employee_name, name",
        limit_page_length=0,
    )
    result = {}
    duplicates = set()
    for row in rows:
        employee_name = _clean(row.get("employee_name"))
        if employee_name in result:
            duplicates.add(employee_name)
        result[employee_name] = row
    if duplicates:
        frappe.throw("员工姓名不唯一，无法同步组织关系：" + "、".join(sorted(duplicates)))
    return result


def _create_missing_employees(frappe, employees):
    created = []
    for employee_name, values in NEW_EMPLOYEES.items():
        if employee_name in employees:
            continue
        department = _ensure_department(
            frappe, values["department"], values["company"]
        )
        designation = _ensure_designation(frappe, values["designation"])
        doc = frappe.get_doc({
            "doctype": "Employee",
            "first_name": employee_name,
            "employee_name": employee_name,
            "company": values["company"],
            "department": department,
            "designation": designation,
            "date_of_joining": values["date_of_joining"],
            "date_of_birth": values["date_of_birth"],
            "gender": values["gender"],
            "status": "Active",
        })
        doc.insert(ignore_permissions=True)
        created.append(doc.name)
    return created


def sync_effective_leaver_statuses(today=None):
    """Apply the dates maintained by HR, preserving rehires and current assignments."""
    import frappe

    current_date = str(today or frappe.utils.today())
    rows = frappe.get_all(
        "Employee", filters={"status": "Active", "relieving_date": ["<=", current_date]},
        fields=["name"], order_by="name", limit_page_length=0,
    )
    updates = []
    for row in rows:
        doc = frappe.get_doc("Employee", row.name, for_update=True)
        if (doc.status != "Active" or not doc.relieving_date
                or str(doc.relieving_date) > current_date):
            continue
        doc.status = "Left"
        # Use save so the linked login is disabled by the normal lifecycle hook.
        doc.save(ignore_permissions=True)
        updates.append({"employee_name": doc.employee_name, "status": doc.status})
    return updates


def sync_organization_master_data(today=None):
    import frappe

    employees = _employee_index(frappe)
    created = _create_missing_employees(frappe, employees)
    employees = _employee_index(frappe)
    removed = []
    for employee_name in REMOVED_EMPLOYEES:
        row = employees.get(employee_name)
        if not row:
            continue
        frappe.delete_doc("Employee", row.get("name"), ignore_permissions=True, force=True)
        removed.append(row.get("name"))
    employees = _employee_index(frappe)

    department_updates = []
    for employee_name, department_name in DEPARTMENT_BY_EMPLOYEE.items():
        row = employees.get(employee_name)
        if not row:
            continue
        department = _ensure_department(frappe, department_name, row.get("company"))
        frappe.db.set_value(
            "Employee", row.get("name"), "department", department, update_modified=False
        )
        department_updates.append(employee_name)

    supervisor_updates = []
    for employee_name, supervisor_name in DIRECT_SUPERVISOR_BY_EMPLOYEE.items():
        employee = employees.get(employee_name)
        supervisor = employees.get(supervisor_name)
        if not employee or not supervisor:
            continue
        frappe.db.set_value(
            "Employee",
            employee.get("name"),
            "reports_to",
            supervisor.get("name"),
            update_modified=False,
        )
        supervisor_updates.append(employee_name)
    for employee_name in TOP_EXECUTIVES:
        employee = employees.get(employee_name)
        if employee:
            frappe.db.set_value(
                "Employee", employee.get("name"), "reports_to", None, update_modified=False
            )

    disabled_departments = []
    legacy_departments = frappe.get_all(
        "Department",
        filters={"department_name": ["in", sorted(LEGACY_DEPARTMENT_NAMES)]},
        fields=["name", "department_name"],
        limit_page_length=0,
    )
    for department in legacy_departments:
        if frappe.db.exists("Employee", {"department": department.get("name")}):
            continue
        frappe.db.set_value(
            "Department", department.get("name"), "disabled", 1, update_modified=False
        )
        disabled_departments.append(department.get("name"))

    status_updates = sync_effective_leaver_statuses(today=today)
    return {
        "created": created,
        "removed": removed,
        "department_updates": len(department_updates),
        "supervisor_updates": len(supervisor_updates),
        "status_updates": status_updates,
        "disabled_departments": disabled_departments,
    }
