from datetime import date

import frappe

from rayher_hr_payroll.api._guards import require_rd_access

HR_ROLES = ("System Manager", "HR User", "HR Manager")
ROOM_FIELDS = [
    "name", "room_no", "room_type", "lease_start_date", "lease_end_date",
    "monthly_rent", "paid_deposit", "rent_contract_attachment",
    "deposit_attachment", "occupant_label", "room_purpose", "remark", "is_active",
]


def _get(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _dict(row):
    if isinstance(row, dict):
        return dict(row)
    return {field: _get(row, field) for field in ROOM_FIELDS}


def room_status(room_purpose, occupancy):
    purpose = (room_purpose or "").strip()
    if purpose == "空":
        return "空置"
    if purpose in ("客房", "午休室"):
        return purpose
    return "有人" if occupancy and _get(occupancy, "employee") else "空置"


@frappe.whitelist()
def list_rooms():
    require_rd_access(HR_ROLES)
    rooms = frappe.get_all(
        "Accommodation Room", fields=ROOM_FIELDS, order_by="room_no"
    )
    occupancies = frappe.get_all(
        "Accommodation Occupancy",
        fields=["name", "employee", "employee_name", "room", "start_date", "end_date", "is_active"],
        order_by="room, modified desc",
    )
    active_by_room = {}
    for occupancy in occupancies:
        room_name = _get(occupancy, "room")
        if not room_name:
            continue
        if _get(occupancy, "is_active"):
            active_by_room.setdefault(room_name, occupancy)
    # 已离职但还登记在住的员工单独标出，提醒人事办理退宿（模块 7，决定 D7）。
    occupant_ids = sorted({_get(row, "employee") for row in active_by_room.values() if _get(row, "employee")})
    left_ids = set(frappe.get_all(
        "Employee", filters={"name": ["in", occupant_ids], "status": "Left"}, pluck="name",
    )) if occupant_ids else set()
    result = []
    for source in rooms:
        row = _dict(source)
        active_occupancy = active_by_room.get(row.get("name"))
        row.update({
            "employee": _get(active_occupancy, "employee"),
            "employee_left": _get(active_occupancy, "employee") in left_ids,
            "employee_name": _get(active_occupancy, "employee_name"),
            "start_date": _get(active_occupancy, "start_date"),
            "end_date": _get(active_occupancy, "end_date"),
            "occupancy_status": room_status(row.get("room_purpose"), active_occupancy),
        })
        result.append(row)
    return result


@frappe.whitelist()
def list_checkout_history():
    require_rd_access(HR_ROLES)
    return frappe.get_all(
        "Accommodation Occupancy",
        filters={"end_date": ["is", "set"]},
        fields=["name", "room", "employee", "employee_name", "start_date", "end_date", "remark"],
        order_by="end_date desc, modified desc",
    )


def _date_value(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _amount(value):
    return float(value or 0)


@frappe.whitelist(methods=["POST"])
def save_room(
    room_no,
    room_type="",
    lease_start_date=None,
    lease_end_date=None,
    monthly_rent=0,
    paid_deposit=0,
    rent_contract_attachment="",
    deposit_attachment="",
    employee=None,
    start_date=None,
    end_date=None,
    room_purpose="",
    occupant_label="",
    remark="",
    is_active=1,
):
    require_rd_access(HR_ROLES)
    room_no = (room_no or "").strip()
    if not room_no:
        frappe.throw(frappe._("请输入房号。"))
    monthly_rent = _amount(monthly_rent)
    paid_deposit = _amount(paid_deposit)
    if monthly_rent < 0 or paid_deposit < 0:
        frappe.throw(frappe._("金额不能为负数。"))

    lease_start = _date_value(lease_start_date)
    lease_end = _date_value(lease_end_date)
    check_in = _date_value(start_date)
    check_out = _date_value(end_date)
    if lease_start and lease_end and lease_end < lease_start:
        frappe.throw(frappe._("到期日不能早于承租日。"))
    if check_in and check_out and check_out < check_in:
        frappe.throw(frappe._("退宿日期不能早于入住日期。"))

    purpose = (room_purpose or "").strip()
    if purpose not in ("", "空", "客房", "午休室"):
        frappe.throw(frappe._("房间用途无效。"))
    employee = (employee or "").strip() or None
    if employee and purpose:
        frappe.throw(frappe._("员工入住与特殊房间用途不能同时设置。"))
    if employee and not frappe.db.exists("Employee", employee):
        frappe.throw(frappe._("请选择有效的入住人。"))
    if employee and frappe.db.get_value("Employee", employee, "status") == "Left":
        # 修复（2026-09-29，模块 7，决定 D7）：离职员工不能新安排入住；已登记在住的离职员工
        # 仍可在原记录上填写退宿日期（离职不自动退宿，由人事维护）。
        current_employee = frappe.db.get_value(
            "Accommodation Occupancy", {"room": room_no, "is_active": 1}, "employee"
        )
        if current_employee != employee:
            frappe.throw(frappe._("该员工已离职，不能安排入住。"))

    existing_room = frappe.db.exists("Accommodation Room", room_no)
    room = frappe.get_doc("Accommodation Room", existing_room) if existing_room else frappe.new_doc("Accommodation Room")
    if employee:
        display_occupant = frappe.db.get_value("Employee", employee, "employee_name") or employee
    elif purpose:
        display_occupant = purpose
    else:
        display_occupant = (occupant_label or "").strip()
    room.update({
        "room_no": room_no,
        "room_type": (room_type or "").strip(),
        "lease_start_date": lease_start,
        "lease_end_date": lease_end,
        "monthly_rent": monthly_rent,
        "default_rent": monthly_rent,
        "paid_deposit": paid_deposit,
        "rent_contract_attachment": rent_contract_attachment or "",
        "deposit_attachment": deposit_attachment or "",
        "occupant_label": display_occupant,
        "room_purpose": purpose,
        "remark": remark or "",
        "is_active": 1 if str(is_active).lower() not in ("0", "false") else 0,
    })
    room.save(ignore_permissions=True)

    current_name = frappe.db.get_value(
        "Accommodation Occupancy", {"room": room.name, "is_active": 1}, "name"
    )
    if not employee and current_name:
        frappe.throw(frappe._("该房间仍有关联入住人；请先选择该入住人并填写退宿日期。"))
    if employee:
        occupancy = frappe.get_doc("Accommodation Occupancy", current_name) if current_name else frappe.new_doc("Accommodation Occupancy")
        if current_name and occupancy.employee != employee:
            frappe.throw(frappe._("该房间已有其他入住人；请先为原入住人填写退宿日期。"))
        occupancy.update({
            "employee": employee,
            "room": room.name,
            "start_date": check_in,
            "end_date": check_out,
            "remark": remark or "",
        })
        occupancy.save(ignore_permissions=True)

    frappe.db.commit()
    return {"name": room.name, "room_no": room.room_no}