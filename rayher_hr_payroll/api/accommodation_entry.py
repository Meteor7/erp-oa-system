import frappe

from rayher_hr_payroll.api._guards import require_rd_access, ensure_not_locked, parse_period


@frappe.whitelist()
def get_emp_options():
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    # Role-based org-wide roster (no per-user Employee User Permissions in this
    # app); get_all works for management roles that lack an Employee read DocPerm.
    return frappe.get_all("Employee", fields=["name", "employee_name"], order_by="employee_name")


@frappe.whitelist()
def list_accommodation(period):
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    y, m = parse_period(period)
    period = "%04d-%02d" % (y, m)  # canonicalize so a YYYYMM caller still matches stored YYYY-MM
    return frappe.get_all(
        "Accommodation Deduction", filters={"period": period},
        fields=["name", "employee", "rent_amount", "water_amount", "electricity_amount", "total_amount"],
        order_by="employee",
    )


@frappe.whitelist(methods=["POST"])
def save_accommodation(period, employee, rent_amount=0, water_amount=0, electricity_amount=0):
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    if not frappe.has_permission("Employee", "read", doc=employee):
        frappe.throw(frappe._("您无权为该员工登记宿舍代扣。"))
    y, m = parse_period(period)
    period = "%04d-%02d" % (y, m)  # canonicalize so lock/report/query keys match
    ensure_not_locked(period, "lock_timesheets", "工时")
    rent, water, elec = float(rent_amount or 0), float(water_amount or 0), float(electricity_amount or 0)
    if min(rent, water, elec) < 0:
        frappe.throw(frappe._("金额不能为负数。"))
    # Serialize concurrent saves for this employee (single PK row lock, released on commit)
    # so two simultaneous saves for the same (employee, period) cannot both pass the
    # check-then-insert below and create duplicate deductions. Same pattern as save_rd_hours.
    frappe.db.get_value("Employee", employee, "name", for_update=True)
    existing = frappe.db.get_value("Accommodation Deduction", {"employee": employee, "period": period}, "name")
    if existing:
        d = frappe.get_doc("Accommodation Deduction", existing)
        d.rent_amount, d.water_amount, d.electricity_amount = rent, water, elec
        d.total_amount = rent + water + elec
        d.save(ignore_permissions=True)
    else:
        frappe.get_doc({
            "doctype": "Accommodation Deduction", "period": period, "employee": employee,
            "rent_amount": rent, "water_amount": water, "electricity_amount": elec,
            "total_amount": rent + water + elec,
        }).insert(ignore_permissions=True)
    frappe.db.commit()
    return list_accommodation(period)


@frappe.whitelist(methods=["POST"])
def delete_accommodation(name):
    require_rd_access(("System Manager",))  # Accommodation Deduction grants delete to System Manager only
    period = frappe.db.get_value("Accommodation Deduction", name, "period")
    ensure_not_locked(period, "lock_timesheets", "工时")
    frappe.delete_doc("Accommodation Deduction", name, ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}
