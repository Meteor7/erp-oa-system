"""宿舍看板数据（2026-09-30，模块 7，按用户确认的 demo 实现）。

一次返回看板需要的全部数据：入住情况、租约到期提醒、演示员工166仍在住提醒、所选月份的
公司/个人费用拆分、公司承担的用途与费用科目、每月费用走势和房间一览。
只读；权限与宿舍基本信息、当月费用页相同（人事）。
"""

from datetime import date

import frappe

from rayher_hr_payroll.api._guards import parse_period, require_rd_access
from rayher_hr_payroll.hr_read_access import require_hr_read
from rayher_hr_payroll import site_time

HR_ROLES = ("System Manager", "HR User", "HR Manager")
EXPENSE_ACCOUNT_CATEGORIES = ("研发费用", "管理费用", "销售费用", "生产成本")
FUNCTION_ROOMS = ("客房", "午休室")
LEASE_WARNING_DAYS = 60
TREND_MONTHS = 12
COMPONENTS = (("rent", "房租"), ("water", "水费"), ("electricity", "电费"))
USES = (("员工", "员工住宿补贴"), ("空", "空置房间"), ("午休室", "午休室"), ("客房", "客房"))
DEDUCTION_FIELDS = [
    "period", "employee", "occupant_type", "room_no", "expense_account_category",
    "personal_rent_amount", "personal_water_amount", "personal_electricity_amount", "personal_total_amount",
    "company_rent_amount", "company_water_amount", "company_electricity_amount", "company_total_amount",
]


def _get(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _money(value):
    return round(float(value or 0), 2)


def _date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _period(value):
    year, month = parse_period(value)
    return "%04d-%02d" % (year, month)


def _shift_month(value, months):
    year, month = (int(part) for part in value.split("-"))
    index = year * 12 + month - 1 + months
    return "%04d-%02d" % (index // 12, index % 12 + 1)


def room_state(purpose, occupant):
    """房间当前状态：入住 / 空置 / 客房 / 午休室（与房间管理页的判断一致）。"""
    purpose = (purpose or "").strip()
    if purpose in FUNCTION_ROOMS:
        return purpose
    if purpose == "空":
        return "空置"
    return "入住" if occupant else "空置"


def building_of(room_no):
    head = (room_no or "").strip()[:1].upper()
    return f"{head} 栋" if head.isascii() and head.isalpha() else "其他"


def _period_rows(deductions, period):
    return [row for row in deductions if _get(row, "period") == period]


def _cost(rows):
    company = sum(_money(_get(row, "company_total_amount")) for row in rows)
    personal = sum(_money(_get(row, "personal_total_amount")) for row in rows)
    components = [
        {
            "key": key, "label": label,
            "company": _money(sum(_money(_get(row, f"company_{key}_amount")) for row in rows)),
            "personal": _money(sum(_money(_get(row, f"personal_{key}_amount")) for row in rows)),
        }
        for key, label in COMPONENTS
    ]
    for item in components:
        item["total"] = _money(item["company"] + item["personal"])

    uses = []
    for occupant_type, label in USES:
        matched = [row for row in rows if (_get(row, "occupant_type") or "员工") == occupant_type]
        units = {_get(row, "employee") if occupant_type == "员工" else _get(row, "room_no") for row in matched}
        uses.append({
            "key": occupant_type, "label": label,
            "count": len({unit for unit in units if unit}),
            "unit": "人" if occupant_type == "员工" else "间",
            "amount": _money(sum(_money(_get(row, "company_total_amount")) for row in matched)),
        })

    subjects = []
    for category in EXPENSE_ACCOUNT_CATEGORIES:
        matched = [row for row in rows if (_get(row, "expense_account_category") or "").strip() == category]
        subjects.append({
            "label": category,
            "amount": _money(sum(_money(_get(row, "company_total_amount")) for row in matched)),
        })
    # 管理费用里含多少空置房、午休室、客房（看板上的说明文字按实际科目算，不写死）。
    management_includes = [
        {"label": label, "amount": _money(sum(
            _money(_get(row, "company_total_amount")) for row in rows
            if _get(row, "occupant_type") == occupant_type
            and (_get(row, "expense_account_category") or "").strip() == "管理费用"
        ))}
        for occupant_type, label in USES[1:]
    ]

    staff = [row for row in rows if (_get(row, "occupant_type") or "员工") == "员工"]
    people = len({_get(row, "employee") for row in staff if _get(row, "employee")})
    return {
        "registered": bool(rows),
        "total": _money(company + personal),
        "company": _money(company),
        "personal": _money(personal),
        "components": components,
        "uses": uses,
        "subjects": subjects,
        "management_includes": [item for item in management_includes if item["amount"]],
        "per_person": {
            "people": people,
            "personal": _money(sum(_money(_get(row, "personal_total_amount")) for row in staff) / people) if people else 0,
            "company": _money(sum(_money(_get(row, "company_total_amount")) for row in staff) / people) if people else 0,
        },
    }


def build_board(rooms, occupancies, left_employees, deductions, period=None, today=None):
    """纯函数：由房间、当前入住、演示员工166员工、费用记录算出看板数据（便于测试）。"""
    today = _date(today) or site_time.today()
    current = today.strftime("%Y-%m")
    registered = sorted({_get(row, "period") for row in deductions if _get(row, "period")})
    # 默认看最近一个已登记、且不晚于本月的月份（提前登记的未来月份不作为默认）。
    past = [month for month in registered if month <= current]
    if period:
        period = _period(period)
    else:
        period = past[-1] if past else (registered[-1] if registered else current)

    last = max(current, registered[-1]) if registered else current
    first = registered[0] if registered else current
    first = max(first, _shift_month(last, -(TREND_MONTHS - 1)))
    months, cursor = [], first
    while cursor <= last:
        months.append(cursor)
        cursor = _shift_month(cursor, 1)
    if period not in months:
        months.append(period)
        months.sort()

    occupant_by_room = {}
    for row in occupancies:
        if _get(row, "room") and _get(row, "employee"):
            occupant_by_room.setdefault(_get(row, "room"), row)
    left_employees = set(left_employees or ())

    selected_rows = _period_rows(deductions, period)
    room_rows = []
    for room in rooms:
        name = _get(room, "name")
        occupant = occupant_by_room.get(name)
        status = room_state(_get(room, "room_purpose"), occupant)
        lease_end = _date(_get(room, "lease_end_date"))
        own = [row for row in selected_rows if (_get(row, "room_no") or "").strip() == name]
        company = _money(sum(_money(_get(row, "company_total_amount")) for row in own))
        personal = _money(sum(_money(_get(row, "personal_total_amount")) for row in own))
        employee = _get(occupant, "employee") if occupant else None
        room_rows.append({
            "room_no": _get(room, "room_no") or name,
            "name": name,
            "building": building_of(_get(room, "room_no") or name),
            "room_type": _get(room, "room_type") or "",
            "monthly_rent": _money(_get(room, "monthly_rent")),
            "lease_end_date": lease_end.isoformat() if lease_end else None,
            "lease_days_left": (lease_end - today).days if lease_end else None,
            "status": status,
            "employee": employee,
            "employee_name": (_get(occupant, "employee_name") or employee) if occupant else None,
            "employee_left": bool(employee and employee in left_employees),
            "company": company,
            "personal": personal,
            "total": _money(company + personal),
            "registered": bool(own),
        })

    counts = {state: sum(1 for row in room_rows if row["status"] == state) for state in ("入住", "空置", "客房", "午休室")}
    residential = counts["入住"] + counts["空置"]
    vacant_rent = sum(row["monthly_rent"] for row in room_rows if row["status"] == "空置")

    expiring = [row for row in room_rows if row["lease_days_left"] is not None and 0 <= row["lease_days_left"] <= LEASE_WARNING_DAYS]
    expired = [row for row in room_rows if row["lease_days_left"] is not None and row["lease_days_left"] < 0]
    lease_alert = None
    if expiring or expired:
        earliest = min(expiring, key=lambda row: row["lease_days_left"]) if expiring else None
        lease_alert = {
            "count": len(expiring),
            "expired_count": len(expired),
            "same_date": len({row["lease_end_date"] for row in expiring}) == 1,
            "earliest_date": earliest["lease_end_date"] if earliest else None,
            "days_left": earliest["lease_days_left"] if earliest else None,
            "rooms": [row["room_no"] for row in sorted(expiring + expired, key=lambda row: row["lease_days_left"])],
        }

    trend = []
    for month in months:
        cost = _cost(_period_rows(deductions, month))
        trend.append({
            "period": month, "registered": cost["registered"],
            "company": cost["company"], "personal": cost["personal"], "total": cost["total"],
        })

    return {
        "today": today.isoformat(),
        "period": period,
        "periods": months,
        "occupancy": {
            **counts,
            "total": len(room_rows),
            "residential": residential,
            "rate": round(counts["入住"] / residential, 4) if residential else 0,
            "vacant_rent": _money(vacant_rent),
        },
        "lease_alert": lease_alert,
        "leavers_in_rooms": [
            {"room_no": row["room_no"], "employee_name": row["employee_name"]}
            for row in room_rows if row["employee_left"]
        ],
        "cost": _cost(selected_rows),
        "trend": trend,
        "rooms": room_rows,
    }


@frappe.whitelist()
def get_dormitory_board(period=None):
    require_hr_read(HR_ROLES, require_rd_access)
    rooms = frappe.get_all(
        "Accommodation Room", filters={"is_active": 1},
        fields=["name", "room_no", "room_type", "monthly_rent", "lease_end_date", "room_purpose"],
        order_by="room_no", limit_page_length=0,
    )
    occupancies = frappe.get_all(
        "Accommodation Occupancy", filters={"is_active": 1},
        fields=["employee", "employee_name", "room"], order_by="room, modified desc", limit_page_length=0,
    )
    occupant_ids = sorted({_get(row, "employee") for row in occupancies if _get(row, "employee")})
    left_employees = frappe.get_all(
        "Employee", filters={"name": ["in", occupant_ids], "status": "Left"}, pluck="name",
    ) if occupant_ids else []
    deductions = frappe.get_all(
        "Accommodation Deduction", fields=DEDUCTION_FIELDS, order_by="period", limit_page_length=0,
    )
    return build_board(rooms, occupancies, left_employees, deductions, period, frappe.utils.today())
