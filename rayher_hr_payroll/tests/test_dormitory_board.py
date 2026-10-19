from rayher_hr_payroll.api import dormitory_board as board


def _room(no, purpose="", rent=1000, lease_end="2026-10-14", room_type="单房"):
    return {"name": no, "room_no": no, "room_type": room_type, "monthly_rent": rent,
            "lease_end_date": lease_end, "room_purpose": purpose}


def _fee(period, room, occupant_type="员工", employee=None, category="研发费用", company=(0, 0, 0), personal=(0, 0, 0)):
    row = {"period": period, "room_no": room, "occupant_type": occupant_type, "employee": employee,
           "expense_account_category": category}
    for key, c, p in zip(("rent", "water", "electricity"), company, personal):
        row[f"company_{key}_amount"] = c
        row[f"personal_{key}_amount"] = p
    row["company_total_amount"] = sum(company)
    row["personal_total_amount"] = sum(personal)
    return row


ROOMS = [
    _room("A101"), _room("A102", rent=1350), _room("A103", "空", rent=1350),
    _room("B201", "客房", rent=2200), _room("C301", "午休室"),
]
OCCUPANCIES = [
    {"employee": "EMP-1", "employee_name": "南通工厂9", "room": "A101"},
    {"employee": "EMP-L", "employee_name": "演示员工146", "room": "B201"},
]
DEDUCTIONS = [
    _fee("2026-06", "A101", employee="EMP-1", company=(1000, 0, 100), personal=(300, 50, 150)),
    _fee("2026-06", "A103", "空", category="管理费用", company=(1350, 0, 0)),
    _fee("2026-06", "C301", "午休室", category="管理费用", company=(1000, 20, 30)),
    _fee("2026-06", "B201", "客房", category="销售费用", company=(2200, 0, 0)),
]


def test_board_counts_rooms_the_same_way_as_the_room_page():
    data = board.build_board(ROOMS, OCCUPANCIES, ["EMP-L"], DEDUCTIONS, today="2026-09-29")

    occupancy = data["occupancy"]
    # 客房登记了人也仍算客房；A102 没人 = 空置；A103 用途"空" = 空置。
    assert (occupancy["入住"], occupancy["空置"], occupancy["客房"], occupancy["午休室"]) == (1, 2, 1, 1)
    assert occupancy["residential"] == 3 and occupancy["rate"] == round(1 / 3, 4)
    assert occupancy["vacant_rent"] == 2700
    assert [room["building"] for room in data["rooms"]] == ["A 栋", "A 栋", "A 栋", "B 栋", "C 栋"]
    assert data["leavers_in_rooms"] == [{"room_no": "B201", "employee_name": "演示员工146"}]


def test_board_defaults_to_the_latest_registered_month_and_marks_unregistered_months():
    data = board.build_board(ROOMS, OCCUPANCIES, [], DEDUCTIONS, today="2026-09-29")

    assert data["period"] == "2026-06"
    assert data["periods"] == ["2026-06", "2026-07", "2026-08", "2026-09"]
    assert [(m["period"], m["registered"]) for m in data["trend"]] == [
        ("2026-06", True), ("2026-07", False), ("2026-08", False), ("2026-09", False)]
    assert board.build_board(ROOMS, OCCUPANCIES, [], [], today="2026-09-29")["periods"] == ["2026-09"]
    # 提前登记的未来月份会出现在月份列表里，但默认仍看最近的已登记月份。
    ahead = board.build_board(ROOMS, OCCUPANCIES, [], DEDUCTIONS + [_fee("2026-11", "A101", employee="EMP-1")], today="2026-09-29")
    assert ahead["period"] == "2026-06" and ahead["periods"][-1] == "2026-11"


def test_board_splits_company_and_personal_cost_by_use_and_subject():
    cost = board.build_board(ROOMS, OCCUPANCIES, [], DEDUCTIONS, period="2026-06", today="2026-09-29")["cost"]

    assert (cost["total"], cost["company"], cost["personal"]) == (6200, 5700, 500)
    assert [(c["label"], c["company"], c["personal"]) for c in cost["components"]] == [
        ("房租", 5550, 300), ("水费", 20, 50), ("电费", 130, 150)]
    assert [(u["label"], u["count"], u["amount"]) for u in cost["uses"]] == [
        ("员工住宿补贴", 1, 1100), ("空置房间", 1, 1350), ("午休室", 1, 1050), ("客房", 1, 2200)]
    assert [(s["label"], s["amount"]) for s in cost["subjects"]] == [
        ("研发费用", 1100), ("管理费用", 2400), ("销售费用", 2200), ("生产成本", 0)]
    # 客房记在销售费用，所以管理费用的说明里只有空置房和午休室。
    assert cost["management_includes"] == [{"label": "空置房间", "amount": 1350}, {"label": "午休室", "amount": 1050}]
    assert cost["per_person"] == {"people": 1, "personal": 500, "company": 1100}


def test_room_tiles_carry_the_selected_month_cost_and_lease_alert():
    data = board.build_board(ROOMS, OCCUPANCIES, [], DEDUCTIONS, period="2026-06", today="2026-09-29")
    a101 = next(room for room in data["rooms"] if room["room_no"] == "A101")

    assert (a101["company"], a101["personal"], a101["employee_name"], a101["lease_days_left"]) == (1100, 500, "南通工厂9", 15)
    assert data["lease_alert"]["count"] == 5 and data["lease_alert"]["same_date"] is True
    assert data["lease_alert"]["earliest_date"] == "2026-10-14" and data["lease_alert"]["days_left"] == 15

    empty = board.build_board(ROOMS, OCCUPANCIES, [], DEDUCTIONS, period="2026-08", today="2026-09-29")
    assert empty["cost"]["registered"] is False and all(not room["registered"] for room in empty["rooms"])


def test_no_lease_alert_when_every_lease_is_far_away():
    rooms = [_room("A101", lease_end="2027-06-30")]
    assert board.build_board(rooms, [], [], [], today="2026-09-29")["lease_alert"] is None
