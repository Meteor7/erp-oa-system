from rayher_hr_payroll.department_structure import department_for_employee


def _clean(value):
    return str(value or "").strip()


def plan_department_updates(employees):
    changes = []
    unchanged = []
    unresolved = []
    for employee in employees:
        current = _clean(employee.get("department_name"))
        target = department_for_employee(
            employee.get("employee_name"),
            employee.get("designation"),
            current,
        )
        if not target:
            unresolved.append({
                "name": employee.get("name"),
                "employee_name": employee.get("employee_name"),
                "company": employee.get("company"),
                "current_department": current,
                "designation": employee.get("designation") or "",
            })
        elif target == current:
            unchanged.append(employee.get("name"))
        else:
            changes.append({
                "name": employee.get("name"),
                "employee_name": employee.get("employee_name"),
                "company": employee.get("company"),
                "from_department": current,
                "to_department": target,
            })
    return {"changes": changes, "unchanged": unchanged, "unresolved": unresolved}


def _active_employees(frappe):
    return frappe.db.sql(
        """
        SELECT e.name, e.employee_name, e.company, e.designation,
               e.department, COALESCE(d.department_name, '') AS department_name
        FROM `tabEmployee` e
        LEFT JOIN `tabDepartment` d ON d.name = e.department
        WHERE e.status = 'Active'
        ORDER BY e.employee_name
        """,
        as_dict=True,
    )


def _ensure_department(frappe, department_name, company):
    name = frappe.db.get_value(
        "Department",
        {"department_name": department_name, "company": company, "is_group": 0},
        "name",
    )
    if name:
        return name
    doc = frappe.get_doc({
        "doctype": "Department",
        "department_name": department_name,
        "company": company,
        "is_group": 0,
    })
    doc.insert(ignore_permissions=True)
    return doc.name


def sync_active_employee_departments(dry_run=True):
    import frappe

    dry_run = str(dry_run).lower() not in {"0", "false", "no"} if isinstance(dry_run, str) else bool(dry_run)
    plan = plan_department_updates(_active_employees(frappe))
    if dry_run:
        return {**plan, "dry_run": True, "changed_count": len(plan["changes"])}
    if plan["unresolved"]:
        names = "、".join(row["employee_name"] for row in plan["unresolved"])
        frappe.throw(f"以下在职员工无法确定正式部门：{names}")

    try:
        for change in plan["changes"]:
            department = _ensure_department(
                frappe,
                change["to_department"],
                change["company"],
            )
            frappe.db.set_value(
                "Employee",
                change["name"],
                "department",
                department,
                update_modified=False,
            )
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    return {**plan, "dry_run": False, "changed_count": len(plan["changes"])}