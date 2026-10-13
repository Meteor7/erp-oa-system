from datetime import date

import pytest

from rayher_hr_payroll import attendance_requests as att
from rayher_hr_payroll.api import dormitory_board, overview_entry
from rayher_hr_payroll.dashboard import core, layout, people

TODAY = "2026-10-09"
PERIOD = "2026-10"

KPIS = ["hr.active", "hr.joined_left", "hr.left_month", "hr.away_today", "hr.expiring", "hr.file_pending", "hr.rd_gap",
        "hr.payroll", "hr.pay_total", "hr.pay_si", "hr.pay_hf", "hr.social_pending",
        "hr.dorm_rate", "hr.dorm_vacant", "hr.dorm_lease", "hr.dorm_leaver"]
ALERTS = ["alert.probation", "alert.contract", "alert.rd_gap", "alert.payroll_draft",
          "alert.dorm_lease", "alert.dorm_leaver", "alert.dorm_register"]
BLOCKS = ["block.dept_headcount", "block.leave_types", "block.expiring_list", "block.dorm_summary", "block.dorm_cost",
          "block.dorm_split", "block.dorm_buildings", "block.dorm_lease_list", "block.pay_progress", "block.si_hf_list",
          "block.pay_by_dept"]
ALL_KEYS = KPIS + ALERTS + BLOCKS
# 只依赖员工表（和 overview_entry.hr_scope 一样，HR 角色或副总 / 总经理岗位可看）的块；其余的底层接口只认 HR 角色。
EMPLOYEE_TABLE_KEYS = {"hr.active", "hr.joined_left", "hr.left_month", "hr.away_today", "hr.expiring", "hr.file_pending",
                       "hr.rd_gap", "alert.probation", "alert.contract", "alert.rd_gap", "block.dept_headcount",
                       "block.leave_types", "block.expiring_list"}
SENSITIVE_KEYS = {"hr.pay_si", "hr.pay_hf", "hr.social_pending", "block.si_hf_list"}


def make_ctx(**kw):
    base = dict(user="hr@example.com", roles=frozenset({"Employee", "HR Manager"}), positions=frozenset({"hr_manager"}),
                period=PERIOD, today=TODAY)
    base.update(kw)
    return core.Ctx(**base)


# ---------------------------------------------------------------- 假数据
def _emp(name, label, dept, **kw):
    row = {"name": name, "employee_name": label, "status": "Active", "department": dept, "date_of_joining": "2023-01-01",
           "relieving_date": None, "probation_end_date": None, "first_contract_end_date": None,
           "second_contract_end_date": None, "archive_status": None, "rd_personnel_type": "非研发"}
    row.update(kw)
    return row


EMPLOYEES = [
    # 合同 10-20 到期（11 天）
    _emp("EMP-1", "演示员工128", "研发软件部 - RAY", rd_personnel_type="全时研发", archive_status="已归档", first_contract_end_date="2026-10-20"),
    # 试用期 10-12 到期（3 天）；第一次合同 10-15 到期但第二次合同更晚 = 已续签，不提醒
    _emp("EMP-2", "演示员工143", "研发算法部 - RAY", rd_personnel_type="研发辅助", archive_status="待确认", probation_end_date="2026-10-12",
         first_contract_end_date="2026-10-15", second_contract_end_date="2028-10-15"),
    # 本月入职；试用期还早
    _emp("EMP-3", "演示员工156", "客服部 - RAY", date_of_joining="2026-10-05", probation_end_date="2027-01-05"),
    # 研发部门但没设研发类型
    _emp("EMP-4", "赵四", "研发软件部 - RAY", rd_personnel_type="", archive_status="待完善"),
    # 本月 3 号已离职
    _emp("EMP-5", "钱五", "采购部 - RAY", status="Left", relieving_date="2026-10-03"),
    # 本月 20 号离职，今天还在职；合同 11-20 到期（42 天）
    _emp("EMP-6", "孙六", "采购部 - RAY", relieving_date="2026-10-20", first_contract_end_date="2026-11-20", archive_status="已归档"),
    # 早就离职
    _emp("EMP-7", "周七", "客服部 - RAY", status="Left", relieving_date="2026-03-01"),
    # 没有部门
    _emp("EMP-8", "吴八", None),
]


def _slip(employee, docstatus, gross, dept):
    return {"employee": employee, "docstatus": docstatus, "gross_pay": gross, "department": dept}


SLIPS = {
    "2026-10": [_slip("EMP-1", 1, 20000, "研发软件部 - RAY"), _slip("EMP-2", 1, 15000, "研发算法部 - RAY"),
                _slip("EMP-3", 0, 8000, "客服部 - RAY"), _slip("EMP-4", 0, 9000, "研发软件部 - RAY")],
    "2026-09": [_slip("EMP-1", 1, 25000, "研发软件部 - RAY"), _slip("EMP-2", 1, 15000, "研发算法部 - RAY")],
}
# 单位承担的社保 / 公积金，按人：合计 = 31200 / 12800
CONTRIBUTIONS = {"EMP-1": {"si": 20000.0, "hf": 8000.0}, "EMP-2": {"si": 11200.0, "hf": 4800.0}, "EMP-8": {"si": 0.0, "hf": 0.0}}
RECORDS = {
    "si": {"any": {"EMP-1", "EMP-2", "EMP-4"}, "confirmed": {"EMP-1", "EMP-2"}},
    "hf": {"any": {"EMP-1", "EMP-2", "EMP-3"}, "confirmed": {"EMP-1", "EMP-2", "EMP-3"}},
}
WORKBENCH = {"dashboard": {"pending_rows": 5}, "batches": [{"status": "Pending Activation", "uploaded_at": "2026-10-08 10:00:00"}]}


def _room(no, purpose="", rent=1000, lease_end="2027-05-01"):
    return {"name": no, "room_no": no, "room_type": "单房", "monthly_rent": rent, "lease_end_date": lease_end, "room_purpose": purpose}


def _fee(room, employee, company, personal, period=PERIOD):
    row = {"period": period, "room_no": room, "occupant_type": "员工", "employee": employee, "expense_account_category": "研发费用"}
    for key, c, p in zip(("rent", "water", "electricity"), company, personal):
        row[f"company_{key}_amount"] = c
        row[f"personal_{key}_amount"] = p
    row["company_total_amount"] = sum(company)
    row["personal_total_amount"] = sum(personal)
    return row


def dorm_board():
    rooms = [
        _room("A101", rent=1000, lease_end="2026-10-14"), _room("A102", rent=1350, lease_end="2026-10-14"),
        _room("A103", "空", rent=1350), _room("B201", rent=2200, lease_end="2026-12-01"),
        _room("B202", rent=1800, lease_end="2027-01-01"), _room("C301", "午休室"),
    ]
    occupancies = [{"employee": "EMP-1", "employee_name": "演示员工128", "room": "A101"},
                   {"employee": "EMP-L", "employee_name": "离职人", "room": "A102"},
                   {"employee": "EMP-2", "employee_name": "演示员工143", "room": "B202"}]
    fees = [_fee("A101", "EMP-1", (1000, 0, 100), (300, 50, 150))]
    return dormitory_board.build_board(rooms, occupancies, ["EMP-L"], fees, PERIOD, TODAY)


AWAY = {"count": 3, "by_type": [{"label": "事假", "count": 2}, {"label": "调休", "count": 1}]}


def leave_stats():
    return overview_entry.leave_stats([
        {"request_type": att.REQUEST_LEAVE, "leave_type": "事假", "duration_hours": 12, "department": "研发软件部"},
        {"request_type": att.REQUEST_LEAVE, "leave_type": "年假", "duration_hours": 8, "department": "客服部"},
    ])


FETCHERS = ("_fetch_employees", "_fetch_slips", "_fetch_contribution_detail", "_fetch_contribution_records",
            "_fetch_workbench", "_fetch_dorm", "_fetch_away", "_fetch_leave_stats", "_fetch_pay_totals", "_fetch_salaries")


# 已确认工资的金额来自 payroll_bridge（2026-10-13）：这里按 SLIPS 里已提交的工资条算同样的数
def confirmed_salaries(period):
    return {slip["employee"]: float(slip["gross_pay"]) for slip in SLIPS.get(period, []) if slip["docstatus"] == 1}


def pay_totals(period):
    return {"gross": sum(confirmed_salaries(period).values()),
            "draft_gross": float(sum(slip["gross_pay"] for slip in SLIPS.get(period, []) if slip["docstatus"] == 0))}


def install(monkeypatch, forbid=(), calls=None, **override):
    """把所有取数函数换成假数据；forbid 里的函数一被调用就失败（证明没权限的人根本没碰底层）。"""
    data = {
        "_fetch_employees": lambda ctx: EMPLOYEES,
        "_fetch_slips": lambda period: SLIPS.get(period, []),
        "_fetch_contribution_detail": lambda ctx: CONTRIBUTIONS,
        "_fetch_contribution_records": lambda ctx: RECORDS,
        "_fetch_workbench": lambda ctx: WORKBENCH,
        "_fetch_dorm": lambda ctx: dorm_board(),
        "_fetch_away": lambda ctx: AWAY,
        "_fetch_leave_stats": lambda ctx: leave_stats(),
        "_fetch_pay_totals": pay_totals,
        "_fetch_salaries": confirmed_salaries,
    }
    data.update(override)
    for name in FETCHERS:
        fn = data[name]

        def make(name, fn):
            def wrapped(*args):
                if name in forbid:
                    raise AssertionError(f"{name} must not be called")
                if calls is not None:
                    calls[name] = calls.get(name, 0) + 1
                return fn(*args)
            return wrapped

        monkeypatch.setattr(people, name, make(name, fn))


def run(ctx, key):
    errors = []
    item = core._run(core.REGISTRY[key], ctx, errors)
    assert not errors, errors
    return item


def run_all(ctx):
    return {key: run(ctx, key) for key in ALL_KEYS}


# ---------------------------------------------------------------- 注册与版式
def test_every_people_key_is_registered_with_the_right_kind_and_placed_in_a_layout():
    for keys, kind in ((KPIS, "kpi"), (ALERTS, "alert"), (BLOCKS, "block")):
        for key in keys:
            assert core.REGISTRY[key].kind == kind, key
    placed = layout.all_block_keys()
    assert set(ALL_KEYS) <= placed
    assert {key for key in placed if key.startswith("hr.")} <= set(core.REGISTRY)


# ---------------------------------------------------------------- 员工表聚合（口径与 personnelView.js 一致）
def test_left_on_the_relieving_day_is_still_active():
    assert not people.is_left({"relieving_date": "2026-10-09"}, date(2026, 10, 9))
    assert people.is_left({"relieving_date": "2026-10-08"}, date(2026, 10, 9))
    assert people.is_left({"status": "Left"}, date(2026, 10, 9))


def test_expiry_window_and_renewed_first_contract():
    today = date(2026, 10, 9)
    assert people.expiry_items({"probation_end_date": "2026-10-12"}, today) == [("试用期", date(2026, 10, 12), 3)]
    assert people.expiry_items({"probation_end_date": "2026-12-09"}, today) == []                                   # 61 天不在窗口里
    assert people.expiry_items({"probation_end_date": "2026-12-08"}, today)[0][2] == 60
    assert people.expiry_items({"probation_end_date": "2026-10-08"}, today) == []                                   # 已过期不提醒
    # 第二次合同晚于第一次 = 第一次已续签；第二次早于或等于第一次才都算
    assert people.expiry_items({"first_contract_end_date": "2026-10-15", "second_contract_end_date": "2028-10-15"}, today) == []
    both = people.expiry_items({"first_contract_end_date": "2026-11-15", "second_contract_end_date": "2026-10-20"}, today)
    assert both == [("合同", date(2026, 10, 20), 11)]
    assert people.expiry_items({"first_contract_end_date": "2026-10-20"}, today)[0][2] == 11


def test_summarize_employees_counts_like_the_personnel_page():
    facts = people.summarize_employees(EMPLOYEES, date(2026, 10, 9), PERIOD)
    assert (facts["active"], facts["rd"], facts["other"]) == (6, 2, 4)
    assert facts["rd_gap"] == 1                                    # 赵四
    assert facts["joined"] == 1 and facts["new_joiners"] == ["EMP-3"]
    assert (facts["left_month"], facts["left_effective"], facts["left_pending"]) == (2, 1, 1)
    assert facts["on_probation"] == 2                              # 演示员工143、演示员工156
    assert (facts["file_pending"], facts["file_confirm"]) == (3, 1)  # 没填档案状态的算待完善
    assert [person["name"] for person in facts["expiring"]] == ["演示员工143", "演示员工128", "孙六"]
    assert facts["dept_counts"] == {"研发软件部": 2, "研发算法部": 1, "客服部": 1, "采购部": 1, "未分配部门": 1}


def test_top_with_other_groups_the_tail():
    items = [(f"部门{i}", value) for i, value in enumerate([9, 8, 7, 6, 5, 4, 3])]
    assert people._top_with_other(items) == [("部门0", 9), ("部门1", 8), ("部门2", 7), ("部门3", 6), ("部门4", 5), ("其他", 7)]
    assert people._top_with_other(items[:5]) == items[:5]


def test_summarize_payroll_uses_the_payroll_page_population():
    payroll = people.summarize_payroll(EMPLOYEES, SLIPS[PERIOD], PERIOD)
    # 应有工资条的人：除早已离职的周七
    assert payroll["expected"] == 7 and payroll["generated"] == 4
    assert (payroll["confirmed"], payroll["draft"], payroll["missing"]) == (2, 2, 3)
    assert payroll["draft_gross"] == 17000 and payroll["draft_people"] == {"EMP-3", "EMP-4"}
    # 同一个人有草稿和已提交两张时，按已提交算（已确认 = docstatus 1）
    twice = people.summarize_payroll(EMPLOYEES, [_slip("EMP-1", 0, 1, "x"), _slip("EMP-1", 1, 20000, "x")], PERIOD)
    assert (twice["generated"], twice["confirmed"], twice["draft"], twice["draft_gross"]) == (1, 1, 0, 0)


# ---------------------------------------------------------------- 权限
def test_plain_employee_and_finance_get_nothing_and_never_touch_the_data(monkeypatch):
    install(monkeypatch, forbid=FETCHERS)
    for ctx in (make_ctx(roles=frozenset({"Employee"}), positions=frozenset()),
                make_ctx(roles=frozenset({"Employee", "Accounts User"}), positions=frozenset({"finance_manager"})),
                make_ctx(roles=frozenset({"Employee", "Purchase User"}), positions=frozenset({"pmc"}))):
        assert run_all(ctx) == {key: None for key in ALL_KEYS}


def test_leaders_see_only_what_their_real_interfaces_allow(monkeypatch):
    # 副总 / 总经理岗位但没有 HR 角色：员工表类可以看（hr_scope 允许），工资、社保、宿舍的底层只认 HR 角色
    install(monkeypatch, forbid=("_fetch_slips", "_fetch_contribution_detail", "_fetch_contribution_records", "_fetch_workbench", "_fetch_dorm",
                                 "_fetch_pay_totals", "_fetch_salaries"))
    for position in ("vice_manager", "general_manager"):
        got = run_all(make_ctx(roles=frozenset({"Employee"}), positions=frozenset({position})))
        assert {key for key, item in got.items() if item is not None} == EMPLOYEE_TABLE_KEYS, position


def test_hr_roles_see_everything(monkeypatch):
    install(monkeypatch)
    for roles in ({"HR User"}, {"HR Manager"}, {"System Manager"}):
        got = run_all(make_ctx(roles=frozenset(roles | {"Employee"}), positions=frozenset()))
        assert all(item is not None for item in got.values()), [key for key, item in got.items() if item is None]


def test_hidden_account_gets_no_social_or_housing_fund_data(monkeypatch):
    install(monkeypatch, forbid=("_fetch_workbench", "_fetch_contribution_detail", "_fetch_contribution_records"))
    monkeypatch.setattr(people._guards, "HR_SENSITIVE_HIDDEN_USERS", {"hr@example.com"})
    got = run_all(make_ctx(user="HR@example.com"))
    assert {key for key, item in got.items() if item is None} == SENSITIVE_KEYS
    labels = [row["label"] for row in got["block.pay_progress"]["rows"]]
    assert labels == ["工资条已确认", "工资条草稿", "工资条未生成"]       # 社保、公积金两行也不给
    assert got["hr.payroll"]["value"] == "2 / 7"                         # 工资本身不在屏蔽范围内


# ---------------------------------------------------------------- 指标卡
def test_headcount_cards(monkeypatch):
    install(monkeypatch)
    ctx = make_ctx()
    active = run(ctx, "hr.active")
    assert (active["value"], active["sub"], active["target"]) == ("6", "研发 2 · 其他 4", {"key": "personnel.list", "params": {"status": "active"}})
    assert "离职日当天仍算在职" in active["hint"] and "工时填报" in active["hint"]
    joined = run(ctx, "hr.joined_left")
    assert (joined["label"], joined["value"], joined["sub"]) == ("本月入职", "1", "试用期中 2 人 · 本月离职 1 人")
    assert joined["target"]["key"] == "personnel.joined"
    left = run(ctx, "hr.left_month")
    # 数字 = 点进去员工页「已离职 + 本月离职」能看到的人数（已经离职的）；离职日还没到的在副标题里单独说
    assert (left["value"], left["sub"]) == ("1", "另有 1 人离职日在本月、还没到")
    assert left["target"] == {"key": "personnel.left_month", "params": {}}
    away = run(ctx, "hr.away_today")
    assert (away["value"], away["sub"], away["target"]["key"]) == ("3", "事假 2 · 调休 1", "attendance.today")


def test_joined_and_left_cards_do_not_point_at_this_month_filter_for_another_month(monkeypatch):
    """员工页只会按“当前月”筛，看别的月份时跳过去数字对不上，所以不给跳转。"""
    install(monkeypatch)
    ctx = make_ctx(period="2026-09")
    joined, left = run(ctx, "hr.joined_left"), run(ctx, "hr.left_month")
    assert joined["value"] == "0" and joined["target"] is None
    assert left["value"] == "0" and left["target"] is None


def test_expiry_file_and_rd_gap_cards(monkeypatch):
    install(monkeypatch)
    ctx = make_ctx()
    expiring = run(ctx, "hr.expiring")
    assert (expiring["value"], expiring["sub"], expiring["tone"]) == ("3", "合同 2 · 试用期 1", "bad")   # 演示员工143只剩 3 天
    assert expiring["target"]["key"] == "personnel.expiring"
    file_ = run(ctx, "hr.file_pending")
    assert (file_["value"], file_["sub"], file_["target"]["key"]) == ("3", "2 人还没填档案状态 · 1 人标了待完善", "personnel.file")
    gap = run(ctx, "hr.rd_gap")
    assert (gap["value"], gap["target"]["key"]) == ("1", "personnel.rd_gap")


def test_payroll_cards(monkeypatch):
    install(monkeypatch)
    ctx = make_ctx()
    payroll = run(ctx, "hr.payroll")
    assert (payroll["label"], payroll["value"], payroll["sub"], payroll["tone"]) == ("工资条已确认", "2 / 7", "草稿 2 · 未生成 3", "hot")
    assert payroll["target"] == {"key": "payroll", "params": {"period": PERIOD, "status": "draft"}}
    total = run(ctx, "hr.pay_total")
    # 只算已确认的：35000（上月 40000）；草稿 2 人另外说
    assert (total["value"], total["unit"], total["sub"]) == ("3.5", "万", "还有 2 人没确认（草稿 约 1.7 万） · ▼ 12.5% 较上月")
    si = run(ctx, "hr.pay_si")
    assert (si["value"], si["unit"], si["sub"], si["target"]["params"]["item"]) == ("3.1", "万", "待确认 5 行", "hr.pay_si")
    hf = run(ctx, "hr.pay_hf")
    assert (hf["value"], hf["sub"], hf["target"]["params"]["item"]) == ("1.3", "已核对 3 / 7 人", "hr.pay_hf")
    # 社保 / 公积金信息页按导入的 Excel 申报数据看，口径和卡片不同：卡片点进去先按部门看这个数是怎么来的
    for item, field, amount in (("hr.pay_si", "si", "¥ 31,200.00"), ("hr.pay_hf", "hf", "¥ 12,800.00")):
        detail = core.get_detail_for(ctx, item)
        assert detail["summary"].endswith(amount), item
        assert [row["cells"][0] for row in detail["rows"]] == ["研发软件部", "研发算法部"]          # 金额为 0 的人不列
    assert core.get_detail_for(ctx, "hr.pay_si")["rows"][0]["target"] == {"key": "social", "params": {"period": PERIOD}}
    assert core.get_detail_for(ctx, "hr.pay_hf")["rows"][0]["target"] == {"key": "housing", "params": {"period": PERIOD}}
    pay_total = core.get_detail_for(ctx, "hr.pay_total")
    assert total["target"] == {"key": "drill", "params": {"item": "hr.pay_total", "period": PERIOD}}
    assert pay_total["summary"] == "已确认 2 人，应发合计 ¥ 35,000.00"
    assert [row["cells"] for row in pay_total["rows"]] == [["研发软件部", "1 人", "1 人", "¥ 20,000.00"], ["研发算法部", "1 人", "0 人", "¥ 15,000.00"],
                                                           ["客服部", "0 人", "1 人", "¥ 0.00"]]
    assert "草稿确认后才计入合计" in pay_total["note"]
    pending = run(ctx, "hr.social_pending")
    assert (pending["value"], pending["sub"]) == ("6", "社保待确认 5 行 · 新入职待开通 1 人")   # 演示员工156没有社保记录


def test_payroll_total_without_slips_or_without_last_month(monkeypatch):
    install(monkeypatch, _fetch_slips=lambda period: [], _fetch_pay_totals=lambda period: {})
    assert run(make_ctx(), "hr.pay_total")["sub"] == "这个月还没有确认的工资条"
    install(monkeypatch, _fetch_pay_totals=lambda period: pay_totals(period) if period == PERIOD else {})
    assert run(make_ctx(), "hr.pay_total")["sub"].endswith("上月没有确认的工资条")


def test_dorm_cards(monkeypatch):
    install(monkeypatch)
    ctx = make_ctx()
    rate = run(ctx, "hr.dorm_rate")
    assert (rate["value"], rate["unit"], rate["sub"], rate["target"]["key"]) == ("60", "%", "3 / 5 间", "dorm.board")
    vacant = run(ctx, "hr.dorm_vacant")
    assert (vacant["value"], vacant["unit"], vacant["sub"]) == ("3,550", "元", "2 间空置")
    lease = run(ctx, "hr.dorm_lease")
    assert (lease["value"], lease["sub"], lease["target"]["key"]) == ("3", "最早 10-14 到期", "dorm.lease")
    leaver = run(ctx, "hr.dorm_leaver")
    assert (leaver["value"], leaver["tone"], leaver["target"]["key"]) == ("1", "bad", "dorm.leaver")


# ---------------------------------------------------------------- 提醒
def test_expiry_alerts(monkeypatch):
    install(monkeypatch)
    ctx = make_ctx()
    probation = run(ctx, "alert.probation")
    assert probation["tone"] == "bad" and probation["title"] == "演示员工143 试用期 10-12 到期，只剩 3 天"
    contract = run(ctx, "alert.contract")
    assert contract["tone"] == "warn" and contract["title"] == "演示员工128等 2 人合同 60 天内到期" and contract["sub"] == "最早 10-20"
    # 试用期 / 合同分开：各去员工页只看那一种
    assert contract["target"] == {"key": "personnel.contract", "params": {}}
    rd = run(ctx, "alert.rd_gap")
    assert rd["title"] == "研发部门有 1 人没设研发类型" and rd["target"]["key"] == "personnel.rd_gap"


def test_probation_alert_uses_the_same_60_day_window_as_the_card(monkeypatch):
    near = [_emp("EMP-9", "郑九", "客服部 - RAY", probation_end_date="2026-11-20")]       # 42 天：卡片和提醒都算
    install(monkeypatch, _fetch_employees=lambda ctx: near)
    assert run(make_ctx(), "alert.probation")["tone"] == "warn"
    assert run(make_ctx(), "hr.expiring")["value"] == "1"
    far = [_emp("EMP-8", "钱八", "客服部 - RAY", probation_end_date="2026-12-20")]        # 72 天：都不算
    install(monkeypatch, _fetch_employees=lambda ctx: far)
    assert run(make_ctx(), "alert.probation") is None
    assert run(make_ctx(), "hr.expiring")["value"] == "0"


def test_payroll_and_dorm_alerts(monkeypatch):
    install(monkeypatch)
    ctx = make_ctx()
    draft = run(ctx, "alert.payroll_draft")
    assert draft["title"] == "2 人工资条还没确认" and draft["go"] == "去确认"
    assert draft["target"] == {"key": "payroll", "params": {"period": PERIOD, "status": "draft"}}
    lease = run(ctx, "alert.dorm_lease")
    assert (lease["tone"], lease["title"], lease["sub"]) == ("bad", "3 间租约 60 天内到期", "最早 10-14")   # 5 天内
    leaver = run(ctx, "alert.dorm_leaver")
    assert (leaver["title"], leaver["sub"], leaver["target"]["key"]) == ("1 位已离职员工仍占房", "房间 A102", "dorm.leaver")
    register = run(ctx, "alert.dorm_register")
    assert register["title"] == "10 月宿舍费用还有 2 间没登记"       # A102、B202 在住但没登记
    assert register["target"] == {"key": "dorm.monthly", "params": {"period": PERIOD, "status": "open"}}


# ---------------------------------------------------------------- 块
def test_headcount_and_leave_blocks(monkeypatch):
    install(monkeypatch)
    ctx = make_ctx()
    dept = run(ctx, "block.dept_headcount")
    assert dept["type"] == "bars" and [(r["label"], r["value"]) for r in dept["rows"]][:2] == [("研发软件部", "2"), ("客服部", "1")]
    assert dept["rows"][0]["pct"] == 100 and dept["rows"][1]["pct"] == 50
    leave = run(ctx, "block.leave_types")
    assert [(r["label"], r["value"]) for r in leave["rows"]] == [("事假", "1.5"), ("年假", "1")]
    assert leave["rows"][0]["pct"] == 100 and leave["target"] == {"key": "drill", "params": {"item": "att.leave", "period": PERIOD}}
    assert "÷ 8" in leave["hint"]


def test_expiring_list_gives_only_names_and_dates(monkeypatch):
    install(monkeypatch)
    block = run(make_ctx(), "block.expiring_list")
    assert block["type"] == "list"
    assert [(r["label"], r["sub"], r["value"], r["tone"]) for r in block["rows"]] == [
        ("演示员工143", "试用期 10-12 到期", "3 天", "bad"),
        ("演示员工128", "合同 10-20 到期", "11 天", "warn"),
        ("孙六", "合同 11-20 到期", "42 天", "warn"),
    ]
    assert block["more"] == ""
    many = [_emp(f"EMP-{i}", f"人{i}", "客服部 - RAY", probation_end_date="2026-10-20") for i in range(8)]
    install(monkeypatch, _fetch_employees=lambda ctx: many)
    capped = run(make_ctx(), "block.expiring_list")
    assert len(capped["rows"]) == 5 and capped["more"] == "还有 3 人"


def test_pay_progress_and_social_list(monkeypatch):
    install(monkeypatch)
    ctx = make_ctx()
    progress = run(ctx, "block.pay_progress")
    assert [(r["label"], r["value"], r["tone"]) for r in progress["rows"]] == [
        ("工资条已确认", "2 / 7", "ok"), ("工资条草稿", "2", "warn"), ("工资条未生成", "3", "bad"),
        ("社保已确认", "2 / 7", "warn"), ("公积金已核对", "3 / 7", "warn")]
    assert progress["rows"][0]["pct"] == pytest.approx(28.6, abs=0.1)
    si_hf = run(ctx, "block.si_hf_list")
    assert [(r["label"], r["sub"], r["value"]) for r in si_hf["rows"]] == [
        ("社保导入批次 2026-10", "10-08 上传", "5 行待确认"), ("本月新入职", "需要开通社保公积金", "1 人")]
    assert all(r["target"]["key"] == "social" for r in si_hf["rows"])


def test_pay_by_dept_is_summary_only(monkeypatch):
    install(monkeypatch)
    block = run(make_ctx(), "block.pay_by_dept")
    assert [(r["label"], r["value"]) for r in block["rows"]] == [("研发软件部", "2.0"), ("研发算法部", "1.5")]   # 草稿不算
    assert block["rows"][0]["pct"] == 100
    assert "EMP" not in str(block) and "演示员工128" not in str(block)


def test_dorm_blocks(monkeypatch):
    install(monkeypatch)
    ctx = make_ctx()
    summary = run(ctx, "block.dorm_summary")
    assert [(r["label"], r["value"]) for r in summary["rows"]] == [
        ("入住率", "60%"), ("空置房租", "¥ 3,550 元"), ("租约到期 / 已过期", "3 间"), ("已离职员工仍占房", "1 人")]
    # 空置房租在宿舍看板上没有这个数：这一行点进去是空置房间的清单（加起来正好是这个数）
    vacant = core.get_detail_for(ctx, "hr.dorm_vacant")
    assert summary["rows"][1]["target"] == {"key": "drill", "params": {"item": "hr.dorm_vacant", "period": PERIOD}}
    assert vacant["summary"] == "共 2 间空置，每月房租 ¥ 3,550.00" and [row["cells"][0] for row in vacant["rows"]] == ["B201", "A103"]
    cost = run(ctx, "block.dorm_cost")
    assert cost["type"] == "stack" and cost["sub"] == "10 月 · ¥ 1,600 元"
    assert [(r["label"], r["value"]) for r in cost["rows"]] == [("房租", "1,300 元"), ("水费", "50 元"), ("电费", "250 元")]
    assert sum(r["pct"] for r in cost["rows"]) == pytest.approx(100, abs=0.3)
    split = run(ctx, "block.dorm_split")
    assert [(r["label"], r["value"]) for r in split["rows"]] == [("公司", "1,100 元"), ("个人扣款", "500 元")]
    buildings = run(ctx, "block.dorm_buildings")
    assert [(r["label"], r["value"]) for r in buildings["rows"]] == [("A 栋", "2 / 3"), ("B 栋", "1 / 2")]   # 午休室不算
    lease = run(ctx, "block.dorm_lease_list")
    assert [(r["label"], r["sub"], r["value"]) for r in lease["rows"]] == [
        ("A101、A102", "同一天到期", "10-14"), ("B201", "到期", "12-01"), ("登记状态", "10 月", "还有 2 间没登记")]
    assert lease["rows"][-1]["target"]["params"] == {"period": PERIOD, "status": "open"}


# ---------------------------------------------------------------- 没有数据
def test_empty_company_shows_zeros_and_empty_states_without_errors(monkeypatch):
    install(monkeypatch, _fetch_employees=lambda ctx: [], _fetch_slips=lambda period: [],
            _fetch_contribution_detail=lambda ctx: {},
            _fetch_contribution_records=lambda ctx: {"si": {"any": set(), "confirmed": set()}, "hf": {"any": set(), "confirmed": set()}},
            _fetch_workbench=lambda ctx: {"dashboard": {"pending_rows": 0}, "batches": []},
            _fetch_dorm=lambda ctx: dormitory_board.build_board([], [], [], [], PERIOD, TODAY),
            _fetch_away=lambda ctx: {"count": 0, "by_type": []}, _fetch_leave_stats=lambda ctx: overview_entry.leave_stats([]),
            _fetch_pay_totals=lambda period: {}, _fetch_salaries=lambda period: {})
    got = run_all(make_ctx())
    assert [got[key]["value"] for key in ("hr.active", "hr.joined_left", "hr.left_month", "hr.away_today", "hr.expiring",
                                          "hr.file_pending", "hr.rd_gap", "hr.payroll", "hr.social_pending")] == \
        ["0", "0", "0", "0", "0", "0", "0", "0 / 0", "0"]
    assert (got["hr.pay_total"]["value"], got["hr.pay_total"]["unit"]) == ("0", "元")
    assert got["hr.pay_si"]["value"] == "0" and got["hr.dorm_rate"]["value"] == "0" and got["hr.dorm_lease"]["value"] == "0"
    assert all(got[key] is None for key in ALERTS)              # 没触发的提醒不出现
    for key in ("block.dept_headcount", "block.leave_types", "block.expiring_list", "block.dorm_cost", "block.dorm_split",
                "block.dorm_buildings", "block.pay_by_dept", "block.si_hf_list"):
        assert got[key]["rows"] == [] and got[key]["error"] is None and got[key]["sub"], key
    assert "还没有登记" in got["block.dorm_cost"]["sub"]
    assert len(got["block.dorm_summary"]["rows"]) == 4
    assert got["block.dorm_lease_list"]["rows"] == []           # 一间房都没有，就不说「已全部登记」
    assert got["block.pay_progress"]["rows"][0]["pct"] == 0     # 分母为 0 不除零


# ---------------------------------------------------------------- 一次请求里的共用与隔离
def test_one_request_reads_each_source_once(monkeypatch):
    calls = {}
    install(monkeypatch, calls=calls)
    tabs = layout.LAYOUTS["hr_manager"]["tabs"]
    ctx = make_ctx(profile="hr_manager")
    for tab in tabs:
        page = core.build_tab(ctx, tab, include_todos=False)
        assert not page["errors"], page["errors"]
    assert calls["_fetch_employees"] == 1 and calls["_fetch_dorm"] == 1 and calls["_fetch_workbench"] == 1
    assert calls["_fetch_away"] == 1 and calls["_fetch_leave_stats"] == 1 and calls["_fetch_contribution_records"] == 1
    assert calls["_fetch_slips"] == 1 and calls["_fetch_pay_totals"] == 2   # 金额：本月 + 上月（应发合计的比较）


def test_a_failing_source_only_breaks_its_own_blocks(monkeypatch):
    def boom(ctx):
        raise RuntimeError("社保工作台出错")

    install(monkeypatch, _fetch_workbench=boom)
    ctx = make_ctx(profile="hr_manager")
    errors = []
    for tab in layout.LAYOUTS["hr_manager"]["tabs"]:
        errors += core.build_tab(ctx, tab, include_todos=False)["errors"]
    assert {error["key"] for error in errors} == {"hr.pay_si", "hr.social_pending", "block.si_hf_list"}
