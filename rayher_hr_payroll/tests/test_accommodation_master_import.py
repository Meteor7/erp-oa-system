from datetime import date
import sys
import types

fake_frappe = types.ModuleType("frappe")
sys.modules["frappe"] = fake_frappe
try:
    from rayher_hr_payroll.importers.accommodation_master import (
        occupancy_is_effective,
        parse_master_row,
    )
finally:
    sys.modules.pop("frappe", None)


def test_parse_master_row_maps_all_twelve_source_columns_without_inventing_checkin():
    values = parse_master_row(
        (
            "B702",
            "一房一厅",
            date(2024, 3, 11),
            date(2026, 10, 14),
            1880,
            2000,
            "/private/files/rent.pdf",
            "/private/files/deposit.pdf",
            "演示员工108",
            None,
            None,
            "测试备注",
        )
    )

    assert values == {
        "room": {
            "room_no": "B702",
            "room_type": "一房一厅",
            "lease_start_date": date(2024, 3, 11),
            "lease_end_date": date(2026, 10, 14),
            "monthly_rent": 1880.0,
            "default_rent": 1880.0,
            "paid_deposit": 2000.0,
            "rent_contract_attachment": "/private/files/rent.pdf",
            "deposit_attachment": "/private/files/deposit.pdf",
            "occupant_label": "演示员工108",
            "room_purpose": "",
            "remark": "测试备注",
            "is_active": 1,
        },
        "occupancy": {
            "employee_name": "演示员工108",
            "start_date": None,
            "end_date": None,
            "remark": "测试备注",
        },
    }


def test_parse_master_row_keeps_special_room_purpose_out_of_employee_occupancy():
    values = parse_master_row(
        ("A703", "一房一厅", None, None, 2200, 1000, None, None, "客房", None, None, "演示员工155")
    )

    assert values["room"]["room_purpose"] == "客房"
    assert values["room"]["occupant_label"] == "客房"
    assert values["occupancy"] is None


def test_blank_start_date_is_effective_until_checkout():
    assert occupancy_is_effective(None, None, date(2026, 8, 1), date(2026, 8, 31))
    assert occupancy_is_effective(None, date(2026, 8, 1), date(2026, 8, 1), date(2026, 8, 31))
    assert not occupancy_is_effective(None, date(2026, 6, 18), date(2026, 8, 1), date(2026, 8, 31))


def test_future_checkin_is_not_effective_for_earlier_period():
    assert not occupancy_is_effective(date(2026, 9, 1), None, date(2026, 8, 1), date(2026, 8, 31))
