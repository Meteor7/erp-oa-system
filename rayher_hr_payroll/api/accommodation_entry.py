from calendar import monthrange
from datetime import date

import frappe

from rayher_hr_payroll.api._guards import require_rd_access, ensure_not_locked, parse_period
from rayher_hr_payroll.importers.accommodation_master import occupancy_is_effective

EXPENSE_ACCOUNT_CATEGORIES = ("研发费用", "管理费用", "销售费用", "生产成本")
EMPLOYEE_OCCUPANT = "员工"
SPECIAL_OCCUPANTS = ("空", "客房", "午休室")
PERIOD_ROOM_CATEGORY_OVERRIDES = {("2026-07", "A609"): "销售费用"}


def _canon_period(period):
    y, m = parse_period(period)
    return "%04d-%02d" % (y, m)


def _period_bounds(period):
    period = _canon_period(period)
    year, month = (int(part) for part in period.split("-"))
    return period, date(year, month, 1), date(year, month, monthrange(year, month)[1])


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


def _category_for_occupant(employee, occupant_type, room_no=None, period=None):
    override = PERIOD_ROOM_CATEGORY_OVERRIDES.get((period, room_no))
    if override:
        return override
    if occupant_type == "客房" and room_no == "A703":
        return "销售费用"
    return "管理费用" if occupant_type in SPECIAL_OCCUPANTS else _category_for_employee(employee)

def _validate_component(label, total, personal, company):
    if min(total, personal, company) < 0:
        frappe.throw(frappe._("金额不能为负数。"))
    if personal + company > total + 0.000001:
        frappe.throw(frappe._("{0}的个人承担和公司承担不能超过总费用。").format(label))


def _payload(period, employee, occupant_type, room_no, rent_amount, water_amount, electricity_amount,
             personal_rent_amount, personal_water_amount, personal_electricity_amount,
             company_rent_amount, company_water_amount, company_electricity_amount):
    personal_rent = _amount(personal_rent_amount)
    personal_water = _amount(personal_water_amount)
    personal_electricity = _amount(personal_electricity_amount)
    company_rent = _amount(company_rent_amount)
    company_water = _amount(company_water_amount)
    company_electricity = _amount(company_electricity_amount)

    if min(personal_rent, personal_water, personal_electricity, company_rent, company_water, company_electricity) < 0:
        frappe.throw(frappe._("金额不能为负数。"))
    rent, water, electricity = personal_rent + company_rent, personal_water + company_water, personal_electricity + company_electricity

    employee, occupant_type = _normalize_occupant(employee, occupant_type)
    room_no = (room_no or "").strip()
    if not room_no:
        frappe.throw(frappe._("请选择房间。"))

    personal_total = personal_rent + personal_water + personal_electricity
    company_total = company_rent + company_water + company_electricity
    return {
        "period": period,
        "employee": employee,
        "occupant_type": occupant_type,
        "room_no": room_no,
        "expense_account_category": _category_for_occupant(employee, occupant_type, room_no, period),
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
        # status 供宿舍页区分演示员工166员工：新入住只能选在职员工，历史记录照常显示姓名。
        fields=["name", "employee_name", "expense_account_category", "status"],
        order_by="employee_name",
    )


def _row_value(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


@frappe.whitelist()
def get_room_options():
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    return frappe.get_all("Accommodation Room", filters={"is_active": 1}, fields=["name", "room_no", "room_type", "monthly_rent", "default_rent"], order_by="room_no")


@frappe.whitelist()
def get_room_occupants(period, room_no):
    """Return the occupants effective for a room in the selected accounting month."""
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    _period, period_start, period_end = _period_bounds(period)
    room_no = (room_no or "").strip()
    room = frappe.db.get_value(
        "Accommodation Room", {"name": room_no, "is_active": 1},
        ["name", "room_purpose"], as_dict=True,
    )
    if not room:
        frappe.throw(frappe._("请选择有效且已启用的房间。"))

    purpose = (_row_value(room, "room_purpose") or "").strip()
    if purpose in SPECIAL_OCCUPANTS:
        label = "空（空置房间费用）" if purpose == "空" else purpose
        return [{
            "value": f"special:{purpose}", "employee": None,
            "occupant_type": purpose, "label": label,
            "start_date": None, "end_date": None,
        }]

    occupancies = frappe.get_all(
        "Accommodation Occupancy", filters={"room": room_no},
        fields=["employee", "employee_name", "start_date", "end_date", "is_active"],
        order_by="start_date, creation",
    )
    choices = []
    for occupancy in occupancies:
        employee = _row_value(occupancy, "employee")
        if not employee:
            continue
        if not (_row_value(occupancy, "is_active") or _row_value(occupancy, "end_date")):
            continue
        if not occupancy_is_effective(
            _row_value(occupancy, "start_date"), _row_value(occupancy, "end_date"),
            period_start, period_end,
        ):
            continue
        choices.append({
            "value": f"employee:{employee}", "employee": employee,
            "occupant_type": EMPLOYEE_OCCUPANT,
            "label": _row_value(occupancy, "employee_name") or employee,
            "start_date": _row_value(occupancy, "start_date"),
            "end_date": _row_value(occupancy, "end_date"),
        })
    if choices:
        return choices
    return [{
        "value": "special:空", "employee": None, "occupant_type": "空",
        "label": "空（空置房间费用）", "start_date": None, "end_date": None,
    }]


@frappe.whitelist()
def get_allowed_rooms(period, employee=None, occupant_type=EMPLOYEE_OCCUPANT):
    """Return only rooms whose basic-data relationship is effective in the period."""
    require_rd_access(("System Manager", "HR User", "HR Manager"))
    period = _canon_period(period)
    year, month = (int(part) for part in period.split("-"))
    period_start = date(year, month, 1)
    period_end = date(year, month, monthrange(year, month)[1])
    employee, occupant_type = _normalize_occupant(employee, occupant_type)

    if occupant_type in SPECIAL_OCCUPANTS:
        return frappe.get_all(
            "Accommodation Room",
            filters={"room_purpose": occupant_type, "is_active": 1},
            fields=["name", "room_no", "room_type", "monthly_rent"],
            order_by="room_no",
        )

    occupancies = frappe.get_all(
        "Accommodation Occupancy",
        filters={"employee": employee},
        fields=["room", "start_date", "end_date", "is_active"],
    )
    room_names = sorted({
        _row_value(row, "room")
        for row in occupancies
        if _row_value(row, "room")
        and (_row_value(row, "is_active") or _row_value(row, "end_date"))
        and occupancy_is_effective(
            _row_value(row, "start_date"), _row_value(row, "end_date"), period_start, period_end
        )
    })
    if not room_names:
        return []
    return frappe.get_all(
        "Accommodation Room",
        filters={"name": ["in", room_names], "is_active": 1},
        fields=["name", "room_no", "room_type", "monthly_rent"],
        order_by="room_no",
    )


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
        order_by="room_no, employee",
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
    if not frappe.db.exists("Accommodation Room", {"name": room_no, "is_active": 1}):
        frappe.throw(frappe._("请选择有效且已启用的房间。"))
    selected_occupant = f"employee:{employee}" if employee else f"special:{occupant_type}"
    allowed_occupants = {
        _row_value(choice, "value") for choice in get_room_occupants(period, room_no)
    }
    if selected_occupant not in allowed_occupants:
        frappe.throw(frappe._("该入住人在本期没有此房间的有效入住关系，请重新选择房间和入住人。"))
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
