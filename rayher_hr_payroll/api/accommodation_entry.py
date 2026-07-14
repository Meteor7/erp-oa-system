import frappe

from rayher_hr_payroll.api._guards import require_rd_access, ensure_not_locked, parse_period

EXPENSE_ACCOUNT_CATEGORIES = ("研发费用", "管理费用", "销售费用", "生产成本")
EMPLOYEE_OCCUPANT = "员工"
SPECIAL_OCCUPANTS = ("空", "客房", "午休室")


def _canon_period(period):
    y, m = parse_period(period)
    return "%04d-%02d" % (y, m)


def _amount(value):
    return float(value or 0)


def _category_for_employee(employee):
    category = (frappe.db.get_value("Employee", employee, "expense_account_category") or "").strip()
    if category not in EXPENSE_ACCOUNT_CATEGORIES:
        frappe.throw(frappe._("请先在人员信息中维护该员工的费用科目。"))
    return category


def _normalize_occupant(employee, occupant_type):
    occupant_type = (occupant_type or EMPLOYEE_OCCUPANT).strip()
    if occupant_type in SPECIAL_OCCUPANTS:
        return None, occupant_type
    if occupant_type != EMPLOYEE_OCCUPANT:
        frappe.throw(frappe._("入住人类型无效。"))
    if not employee:
        frappe.throw(frappe._("请选择入住人。"))
    return employee, EMPLOYEE_OCCUPANT


def _category_for_occupant(employee, occupant_type):
    return "管理费用" if occupant_type in SPECIAL_OCCUPANTS else _category_for_employee(employee)


def _validate_component(label, total, personal, company):
    if min(total, personal, company) < 0:
        frappe.throw(frappe._("金额不能为负数。"))
    if personal + company > total + 0.000001:
        frappe.throw(frappe._("{0}的个人承担和公司承担不能超过总费用。").format(label))


def _payload(period, employee, occupant_type, room_no, rent_amount, water_amount, electricity_amount,
             personal_rent_amount, personal_water_amount, personal_electricity_amount,
             company_rent_amount, company_water_amount, company_electricity_amount):
    rent = _amount(rent_amount)
    water = _amount(water_amount)
    electricity = _amount(electricity_amount)
    personal_rent = _amount(personal_rent_amount)
    personal_water = _amount(personal_water_amount)
    personal_electricity = _amount(personal_electricity_amount)
    company_rent = _amount(company_rent_amount)
    company_water = _amount(company_water_amount)
    company_electricity = _amount(company_electricity_amount)

    _validate_component("房租", rent, personal_rent, company_rent)
    _validate_component("水费", water, personal_water, company_water)
    _validate_component("电费", electricity, personal_electricity, company_electricity)

    employee, occupant_type = _normalize_occupant(employee, occupant_type)
    room_no = (room_no or "").strip()
    if not room_no:
        frappe.throw(frappe._("请选择或填写房间号。"))

    personal_total = personal_rent + personal_water + personal_electricity
    company_total = company_rent + company_water + company_electricity
    return {
        "period": period,
        "employee": employee,
        "occupant_type": occupant_type,
        "room_no": room_no,
        "expense_account_category": _category_for_occupant(employee, occupant_type),
        "rent_amount": rent,
        "water_amount": water,
        "electricity_amount": electricity,
        "personal_rent_amount": personal_rent,
        "personal_water_amount": personal_water,
        "personal_electricity_amount": personal_electricity,
        "personal_total_amount": personal_total,
        "company_rent_amount": company_rent,
        "company_water_amount": company_water,
        "company_electricity_amount": company_electricity,
        "company_total_amount": company_total,
        "total_amount": rent + water + electricity,
    }


@frappe.whitelist()
def get_emp_options():
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    # Role-based org-wide roster (no per-user Employee User Permissions in this
    # app); get_all works for management roles that lack an Employee read DocPerm.
    return frappe.get_all(
        "Employee",
        fields=["name", "employee_name", "expense_account_category"],
        order_by="employee_name",
    )


@frappe.whitelist()
def get_room_options():
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    rooms = frappe.get_all(
        "Accommodation Deduction",
        filters={"room_no": ["is", "set"]},
        pluck="room_no",
        order_by="room_no",
    )
    return sorted({str(room).strip() for room in rooms if str(room or "").strip()})


@frappe.whitelist()
def list_accommodation(period):
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    period = _canon_period(period)
    return frappe.get_all(
        "Accommodation Deduction", filters={"period": period},
        fields=[
            "name", "employee", "occupant_type", "room_no", "expense_account_category",
            "rent_amount", "water_amount", "electricity_amount",
            "personal_rent_amount", "personal_water_amount", "personal_electricity_amount", "personal_total_amount",
            "company_rent_amount", "company_water_amount", "company_electricity_amount", "company_total_amount",
            "total_amount",
        ],
        order_by="employee",
    )


@frappe.whitelist()
def get_accommodation_summary(period):
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    period = _canon_period(period)
    buckets = {
        category: {
            "expense_account_category": category,
            "company_rent_amount": 0.0,
            "company_water_amount": 0.0,
            "company_electricity_amount": 0.0,
            "company_total_amount": 0.0,
        }
        for category in EXPENSE_ACCOUNT_CATEGORIES
    }
    rows = frappe.get_all(
        "Accommodation Deduction", filters={"period": period},
        fields=["expense_account_category", "company_rent_amount", "company_water_amount", "company_electricity_amount", "company_total_amount"],
    )
    for row in rows:
        category = (row.get("expense_account_category") or "").strip()
        if category not in buckets:
            continue
        bucket = buckets[category]
        bucket["company_rent_amount"] += _amount(row.get("company_rent_amount"))
        bucket["company_water_amount"] += _amount(row.get("company_water_amount"))
        bucket["company_electricity_amount"] += _amount(row.get("company_electricity_amount"))
        bucket["company_total_amount"] += _amount(row.get("company_total_amount"))
    return [buckets[category] for category in EXPENSE_ACCOUNT_CATEGORIES]


@frappe.whitelist(methods=["POST"])
def save_accommodation(period, employee=None, occupant_type=EMPLOYEE_OCCUPANT, room_no="", rent_amount=0, water_amount=0, electricity_amount=0,
                       personal_rent_amount=0, personal_water_amount=0, personal_electricity_amount=0,
                       company_rent_amount=0, company_water_amount=0, company_electricity_amount=0):
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    employee, occupant_type = _normalize_occupant(employee, occupant_type)
    if employee and not frappe.has_permission("Employee", "read", doc=employee):
        frappe.throw(frappe._("您无权为该员工登记宿舍代扣。"))
    period = _canon_period(period)
    ensure_not_locked(period, "lock_timesheets", "工时")
    values = _payload(
        period, employee, occupant_type, room_no, rent_amount, water_amount, electricity_amount,
        personal_rent_amount, personal_water_amount, personal_electricity_amount,
        company_rent_amount, company_water_amount, company_electricity_amount,
    )
    # Serialize concurrent saves for this employee (single PK row lock, released on commit)
    # so two simultaneous saves for the same (employee, period) cannot both pass the
    # check-then-insert below and create duplicate deductions. Same pattern as save_rd_hours.
    if employee:
        frappe.db.get_value("Employee", employee, "name", for_update=True)
        existing_filters = {"employee": employee, "period": period}
    else:
        existing_filters = {
            "period": period,
            "occupant_type": occupant_type,
            "room_no": values["room_no"],
            "employee": ["is", "not set"],
        }
    existing = frappe.db.get_value("Accommodation Deduction", existing_filters, "name")
    if existing:
        d = frappe.get_doc("Accommodation Deduction", existing)
        d.update(values)
        d.save(ignore_permissions=True)
    else:
        frappe.get_doc({"doctype": "Accommodation Deduction", **values}).insert(ignore_permissions=True)
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
