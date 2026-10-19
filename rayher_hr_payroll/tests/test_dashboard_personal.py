import pytest

from rayher_hr_payroll.dashboard import core, layout, personal


def make_ctx(**kw):
    base = dict(user="u@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-09",
                employee="E0", department="研发软件部 - RAY")
    base.update(kw)
    return core.Ctx(**base)


def run(key, ctx):
    provider = core.REGISTRY[key]
    if provider.visible is not None and not provider.visible(ctx):
        return None
    return provider.fn(ctx)


ME_KEYS = ["me.annual", "me.comp", "me.overtime_month", "me.requests", "me.timesheet", "me.claim", "me.cc", "me.unread", "me.approvals",
           "alert.me_timesheet", "alert.me_leave_unused", "alert.me_trip", "block.me_requests", "block.me_timesheet", "block.me_strip", "block.me_balances", "todo.queue"]


@pytest.fixture
def data(monkeypatch):
    """所有取数函数换成可调的假数据，同时记录调用次数。"""
    state = {
        "leave": {"visible": True,
                  "annual": {"available": 30.0, "granted": 30.0, "used": 0.0, "reserved": 0.0, "eligible": True, "message": ""},
                  "comp": {"available": 1.0, "credit": 1.0, "used": 0.0, "reserved": 0.0}},
        "home": {"employee": {"name": "E0"}, "month": {"overtime_hours": 8, "leave_days": 1.5, "comp_hours": 0}},
        "requests": [], "rd": True,
        "entries": {"max_day_limit": 21.6, "total_days": 12.1, "entries": [
            {"project": "P1", "project_name": "ACONCA 7961", "occurrence_days": 8.0}, {"project": "P2", "project_name": "RD14 视觉模组", "occurrence_days": 4.1}]},
        "claims": [], "summary": {"total": 0, "categories": []}, "notes": {"mine": 0, "cc": 0, "biz": 0, "sys": 0}, "queue": [],
    }
    calls = {"leave": 0, "requests": 0}

    def leave():
        calls["leave"] += 1
        return state["leave"]

    def requests(limit):
        calls["requests"] += 1
        return state["requests"]

    monkeypatch.setattr(personal, "_load_leave_summary", leave)
    monkeypatch.setattr(personal, "_load_attendance_home", lambda period: state["home"])
    monkeypatch.setattr(personal, "_load_my_requests", requests)
    monkeypatch.setattr(personal, "_load_is_rd", lambda user, employee: state["rd"])
    monkeypatch.setattr(personal, "_load_my_entries", lambda period, employee: state["entries"])
    monkeypatch.setattr(personal, "_load_my_claims", lambda user, employee: state["claims"])
    monkeypatch.setattr(personal, "_load_approval_summary", lambda: state["summary"])
    monkeypatch.setattr(personal, "_load_notification_counts", lambda: state["notes"])
    monkeypatch.setattr(personal, "_load_approval_queue", lambda limit: state["queue"])
    state["trips"] = []
    monkeypatch.setattr(personal, "_load_my_trips", lambda ctx: state["trips"])
    state["calls"] = calls
    return state


def test_every_personal_key_in_the_layout_has_a_provider_of_the_right_kind():
    mine = {key for key in layout.all_block_keys() if key.startswith(("me.", "alert.me_", "block.me_", "todo."))} - {"me.processed"}   # me.processed 是财务任务（money.py）的
    assert mine == set(ME_KEYS)
    for key in mine:
        expected = "todos" if key.startswith("todo.") else "alert" if key.startswith("alert.") else "block" if key.startswith("block.") else "kpi"
        assert core.REGISTRY[key].kind == expected, key


def test_personal_blocks_need_an_employee_record_but_the_queue_and_approvals_do_not(data):
    ctx = make_ctx(employee="")
    for key in ME_KEYS:
        if key in ("todo.queue", "me.approvals", "me.unread"):
            assert core.REGISTRY[key].visible is None, key
        else:
            assert run(key, ctx) is None, key
    assert data["calls"] == {"leave": 0, "requests": 0}, "没有员工档案不能去取别人的数据"


# ---------------------------------------------------------------- 假期 / 加班
def test_annual_and_comp_balances_in_days_with_comp_credit_in_hours(data):
    ctx = make_ctx()
    annual = run("me.annual", ctx)
    comp = run("me.comp", ctx)
    assert data["calls"]["leave"] == 1, "同一次请求里几个块共用一次接口"
    assert (annual["label"], annual["value"], annual["unit"], annual["sub"]) == ("年假可用", "30", "天", "已用 0 天")
    assert annual["target"] == {"key": "attendance.home", "params": {}}
    data["leave"]["annual"].update(used=1.5, reserved=0.5, available=28.0)
    assert run("me.annual", make_ctx())["sub"] == "已用 1.5 天 · 审批中 0.5 天"
    assert (comp["value"], comp["sub"]) == ("1", "累计加班 8 小时")
    data["leave"]["comp"].update(reserved=0.5)
    assert run("me.comp", make_ctx())["sub"] == "累计加班 8 小时 · 审批中 4 小时"


def test_annual_when_not_yet_eligible_or_no_balance_record(data):
    data["leave"]["annual"].update(eligible=False, available=0.0, message="入职满一年后才有年假")
    kpi = run("me.annual", make_ctx())
    assert (kpi["value"], kpi["sub"]) == ("—", "入职满一年后才有年假")
    assert run("alert.me_leave_unused", make_ctx()) is None
    data["leave"] = {"visible": False}
    ctx = make_ctx()
    assert run("me.annual", ctx) is None and run("me.comp", ctx) is None and run("alert.me_leave_unused", ctx) is None


def test_overtime_month_is_in_hours(data):
    kpi = run("me.overtime_month", make_ctx())
    assert (kpi["label"], kpi["value"], kpi["unit"], kpi["sub"]) == ("本月加班", "8", "小时", "请假 1.5 天")
    data["home"]["month"].update(comp_hours=4)
    assert run("me.overtime_month", make_ctx())["sub"] == "请假 1.5 天 · 调休 4 小时"
    assert run("me.overtime_month", make_ctx(period="2026-09"))["label"] == "9 月加班"
    data["home"] = {}                                   # 请假 / 加班功能没对这个账号开放，或没有员工档案
    assert run("me.overtime_month", make_ctx()) is None


def test_unused_annual_leave_reminder(data):
    item = run("alert.me_leave_unused", make_ctx())
    assert (item["title"], item["sub"], item["tone"]) == ("年假还有 30 天一天没休", "年底前记得安排", "info")
    data["leave"]["annual"].update(used=2.0, available=28.0)
    assert run("alert.me_leave_unused", make_ctx()) is None
    data["leave"]["annual"].update(used=0.0, reserved=1.0)
    assert run("alert.me_leave_unused", make_ctx()) is None, "已经提了年假申请就不提醒"


# ---------------------------------------------------------------- 我的申请 / 报销
def req(name, route, status="待审批", returned=False, step="财务主管", note="", request_type="报销单", subject=None):
    return {"name": name, "request_type": request_type, "subject": subject or f"{request_type} {name}", "status": status, "step_label": step,
            "returned": returned, "returned_note": note, "route": route, "amount": 2860}


def test_requests_kpi_counts_running_returned_and_drafts_and_the_block_lists_returned_first(data):
    data["requests"] = [
        req("OA-1", "/approval/claim", subject="报销 差旅"), req("OA-2", "/approval/leave", "草稿", True, "", "补充事由", "请假申请", "请假 10-26 至 10-28"),
        req("OA-3", "/approval/overtime", "草稿", False, "", "", "加班申请", "加班 10-18 4 小时"),
    ]
    ctx = make_ctx()
    kpi = run("me.requests", ctx)
    assert (kpi["value"], kpi["sub"], kpi["tone"]) == ("3", "进行中 1 · 被退回 1 · 草稿 1", "hot")
    block = run("block.me_requests", ctx)
    assert [r["label"] for r in block["rows"]] == ["请假 10-26 至 10-28", "报销 差旅", "加班 10-18 4 小时"]
    assert [(r["sub"], r["value"], r["tone"]) for r in block["rows"]] == [
        ("请假申请 · 被退回：补充事由", "修改", "bad"), ("报销单 · 财务主管审批中", "审批中", "warn"), ("加班申请 · 草稿", "继续填写", "")]
    assert [r["target"] for r in block["rows"]] == [
        {"key": "attendance.detail", "params": {"request": "OA-2"}}, {"key": "claim.detail", "params": {"request": "OA-1"}},
        {"key": "attendance.detail", "params": {"request": "OA-3"}}]
    assert data["calls"]["requests"] == 1


def test_no_open_requests(data):
    ctx = make_ctx()
    kpi = run("me.requests", ctx)
    assert (kpi["value"], kpi["sub"], kpi["tone"]) == ("0", "没有进行中的申请", "")
    assert run("block.me_requests", ctx) is None


def test_my_claims_show_count_total_and_how_far_the_approval_got(data):
    data["claims"] = [
        {"name": "C2", "amount": 100, "approved_amount": 0, "workflow_status": "待办理", "current_step_label": "演示员工110"},
        {"name": "C1", "amount": 2860, "approved_amount": 2800, "workflow_status": "待审批", "current_step_label": "财务主管"},
        {"name": "C0", "amount": 50, "approved_amount": 0, "workflow_status": "草稿", "current_step_label": ""},
    ]
    kpi = run("me.claim", make_ctx())
    assert (kpi["value"], kpi["unit"], kpi["sub"]) == ("2", "张", "合计 ¥ 2,900 · 演示员工110办理中 · 草稿 1")
    # 2026-10-13：报销页“我的”列出全部报销单，和在途张数对不上；点进去是同一份在途清单
    assert kpi["target"] == {"key": "drill", "params": {"item": "me.claim", "period": "2026-10"}}
    assert "不预测到账日" in kpi["hint"]
    data["claims"] = [{"name": "C1", "amount": 123456, "approved_amount": 0, "workflow_status": "待审批", "current_step_label": ""}]
    assert run("me.claim", make_ctx())["sub"] == "合计 ¥ 12.3 万 · 审批中"
    data["claims"] = []
    assert run("me.claim", make_ctx())["sub"] == "没有在途的报销"
    data["claims"] = None                                    # 报销功能没对这个账号开放
    assert run("me.claim", make_ctx()) is None


# ---------------------------------------------------------------- 我的工时
def test_timesheet_kpi_alert_and_block_when_hours_are_missing(data):
    ctx = make_ctx()
    kpi = run("me.timesheet", ctx)
    assert (kpi["label"], kpi["value"], kpi["unit"], kpi["sub"], kpi["tone"]) == ("本月工时", "还差 9.5", "天", "已填 12.1 / 21.6", "hot")
    assert kpi["target"] == {"key": "timesheet.mine", "params": {"period": "2026-10"}}
    item = run("alert.me_timesheet", ctx)
    assert (item["title"], item["sub"], item["tone"], item["go"]) == ("10 月工时还差 9.5 天", "10-31 截止", "warn", "去填报")
    block = run("block.me_timesheet", ctx)
    assert block["title"] == "我这个月的工时" and block["sub"] == "已填 12.1 / 21.6 天"
    assert [(r["label"], r["value"], r["tone"]) for r in block["rows"]] == [("ACONCA 7961", "8", ""), ("RD14 视觉模组", "4.1", ""), ("还差", "9.5", "warn")]
    assert [r["pct"] for r in block["rows"]] == [37.0, 19.0, 44.0]


def test_timesheet_states_full_over_past_and_future(data):
    data["entries"].update(total_days=21.6)
    ctx = make_ctx()
    kpi = run("me.timesheet", ctx)
    assert (kpi["value"], kpi["tone"]) == ("已填满", "ok")
    assert run("alert.me_timesheet", ctx) is None
    assert [r["label"] for r in run("block.me_timesheet", ctx)["rows"]] == ["ACONCA 7961", "RD14 视觉模组"]
    data["entries"].update(total_days=22)
    kpi = run("me.timesheet", make_ctx())
    assert (kpi["value"], kpi["tone"]) == ("超 0.4", "warn") and run("alert.me_timesheet", make_ctx()) is None
    data["entries"].update(total_days=10)
    past = run("alert.me_timesheet", make_ctx(period="2026-09"))
    assert past["tone"] == "bad" and past["sub"] == "09-30 截止，已过截止"
    assert run("alert.me_timesheet", make_ctx(period="2026-11")) is None
    assert run("block.me_timesheet", make_ctx(period="2026-09"))["title"] == "我 9 月的工时"


def test_timesheet_is_only_for_people_on_the_fill_list(data):
    data["rd"] = False
    ctx = make_ctx()
    for key in ("me.timesheet", "alert.me_timesheet", "block.me_timesheet"):
        assert run(key, ctx) is None, key
    data["rd"] = True
    data["entries"] = {"max_day_limit": 0, "total_days": 0, "entries": []}          # 当月可填上限是 0（比如月底才入职）
    ctx = make_ctx()
    for key in ("me.timesheet", "alert.me_timesheet", "block.me_timesheet"):
        assert run(key, ctx) is None, key


# ---------------------------------------------------------------- 审批 / 通知
def category(key, label, count):
    return {"key": key, "label": label, "count": count, "requests": []}


def test_approvals_kpi_breaks_down_by_category_and_jumps_only_when_unambiguous(data):
    data["summary"] = {"total": 3, "categories": [category("leave", "请假", 2), category("overtime", "加班", 1), category("claim", "报销", 0)]}
    kpi = run("me.approvals", make_ctx())
    assert (kpi["value"], kpi["sub"], kpi["tone"]) == ("3", "请假 2 · 加班 1", "hot")
    assert kpi["target"] == {"key": "attendance.todo", "params": {}}
    data["summary"] = {"total": 2, "categories": [category("leave", "请假", 2)]}
    assert run("me.approvals", make_ctx())["target"] == {"key": "attendance.todo", "params": {"type": "请假"}}
    data["summary"] = {"total": 2, "categories": [category("reimbursement", "报销", 2)]}
    assert run("me.approvals", make_ctx())["target"] == {"key": "claim.todo", "params": {}}
    data["summary"] = {"total": 3, "categories": [category("leave", "请假", 2), category("reimbursement", "报销", 1)]}
    assert run("me.approvals", make_ctx())["target"] is None
    data["summary"] = {"total": 0, "categories": []}
    kpi = run("me.approvals", make_ctx())
    assert (kpi["value"], kpi["sub"], kpi["tone"], kpi["target"]) == ("0", "没有要我审批的", "", None)


def test_cc_and_unread_notifications(data):
    data["notes"] = {"mine": 1, "cc": 2, "biz": 0, "sys": 3}
    ctx = make_ctx()
    cc = run("me.cc", ctx)
    assert (cc["value"], cc["unit"], cc["sub"]) == ("2", "条", "只是知会，不用审批")
    unread = run("me.unread", ctx)
    assert (unread["value"], unread["tone"]) == ("6", "hot")
    data["notes"] = {"mine": 0, "cc": 0}
    ctx = make_ctx()
    assert run("me.cc", ctx)["sub"] == "没有未读的抄送" and run("me.unread", ctx)["value"] == "0" and run("me.unread", ctx)["tone"] == ""


# ---------------------------------------------------------------- 要我处理
def queue_item(**kw):
    base = {"name": "OA-1", "request_type": "报销单", "kind": "报销单", "subject": "报销 · 差旅", "applicant": "演示员工186", "amount": 2860.0,
            "hours": 0, "from_date": "", "to_date": "", "waited_days": 2, "route": "/approval/claim", "query": {"request": "OA-1"}}
    base.update(kw)
    return base


def test_queue_maps_every_document_type_to_a_dashboard_target(data):
    data["queue"] = [
        queue_item(),
        queue_item(name="OA-2", request_type="请假申请", kind="请假申请", subject="请假申请", applicant="演示员工186", amount=0, from_date="2026-10-26",
                   to_date="2026-10-28", route="/approval/leave", query={"request": "OA-2"}, waited_days=0),
        queue_item(name="OA-3", request_type="加班申请", kind="加班申请", applicant="演示员工112", amount=0, hours=6, from_date="2026-10-24", to_date="2026-10-24",
                   route="/approval/overtime", query={"request": "OA-3"}, waited_days=5),
        queue_item(name="OA-4", request_type="付款单", kind="付款单", route="/approval/payment", query={"request": "OA-4"}),
        queue_item(name="OA-5", request_type="采购申请", kind="采购申请", route="/approval/procurement", query={"request": "OA-5"}),
        queue_item(name="OA-6", request_type="购买申请", kind="购买申请", route="/approval/direct-purchase", query={"request": "OA-6"}),
        queue_item(name="OA-7", request_type="出差申请", kind="出差申请", route="/approval/travel", query={"request": "OA-7"}),
        queue_item(name="OA-8", request_type="采购付款", kind="采购付款", route="/approval/procurement-payment", query={"request": "OA-8"}),
    ]
    todos = run("todo.queue", make_ctx())
    assert [t["target"] for t in todos] == [
        {"key": "claim.detail", "params": {"request": "OA-1"}}, {"key": "attendance.detail", "params": {"request": "OA-2"}},
        {"key": "attendance.detail", "params": {"request": "OA-3"}}, {"key": "payment.detail", "params": {"request": "OA-4"}},
        {"key": "procurement.detail", "params": {"request": "OA-5"}}, {"key": "directpurchase.detail", "params": {"request": "OA-6"}},
        {"key": "travel.detail", "params": {"request": "OA-7"}}, {"key": "procpay.approvals", "params": {"request": "OA-8"}}]
    first, leave, overtime = todos[:3]
    assert (first["kind"], first["title"], first["sub"], first["btn"], first["tone"]) == ("报销单", "报销 · 差旅", "演示员工186 · ¥ 2,860 · 等你 2 天", "去审批", "info")
    assert (leave["title"], leave["sub"]) == ("请假 · 演示员工186 · 10-26 至 10-28", "今天刚到")
    assert (overtime["title"], overtime["tone"]) == ("加班 · 演示员工112 · 10-24 6 小时", "warn")      # 等了超过 3 天


def test_queue_non_request_tasks_get_their_own_buttons_and_targets(data):
    data["queue"] = [
        queue_item(name="PA-1", request_type="价格审批", kind="价格审批", subject="PA-1 待选择成交供应商并审批", route="/approval/procurement/price-approvals",
                   query={"approval": "PA-1"}, amount=98000),
        queue_item(name="PO-1", request_type="采购订单", kind="采购订单", subject="PO-1 待采购确认订单", route="/approval/procurement/price-approvals",
                   query={"po": "PO-1"}, amount=0),
        queue_item(name="PO-2", request_type="采购订单", kind="采购订单", subject="PO-2 待验收", route="/approval/procurement-payment", query={"po": "PO-2"}),
        queue_item(name="PO-3", request_type="采购付款", kind="采购付款", subject="PO-3 第 2 期 可提交付款", route="/approval/procurement-payment",
                   query={"po": "PO-3"}),
        queue_item(name="X", request_type="未知类型", kind="未知类型", route="/approval/request-dashboard", query={"request": "X"}),
    ]
    todos = run("todo.queue", make_ctx())
    assert [(t["btn"], t["target"]) for t in todos] == [
        ("去审批", {"key": "price.approvals", "params": {"approval": "PA-1"}}), ("去处理", {"key": "price.po", "params": {"po": "PO-1"}}),
        ("去处理", {"key": "procpay.work", "params": {"po": "PO-2"}}), ("去提交", {"key": "procpay.work", "params": {"po": "PO-3"}}),
        ("去审批", None)]


def test_queue_for_pmc_has_no_money(data):
    data["queue"] = [queue_item(), queue_item(name="PO-3", request_type="采购付款", kind="采购付款", applicant="金额 86,400 · 条件已满足",
                                              route="/approval/procurement-payment", query={"po": "PO-3"})]
    todos = run("todo.queue", make_ctx(profile="pmc"))
    assert len(todos) == 1 and "¥" not in todos[0]["sub"]
    assert "¥" in run("todo.queue", make_ctx(profile="procurement_manager"))[0]["sub"]


def test_queue_adds_returned_requests_after_the_approvals_and_is_capped(data):
    data["requests"] = [req("OA-2", "/approval/leave", "草稿", True, "", "补充事由", "请假申请", "请假 10-26"), req("OA-9", "/approval/claim")]
    data["queue"] = [queue_item(name=f"OA-{i}", query={"request": f"OA-{i}"}) for i in range(10, 13)]
    todos = run("todo.queue", make_ctx())
    assert len(todos) == 4
    last = todos[-1]
    assert (last["kind"], last["title"], last["sub"], last["btn"], last["tone"]) == ("请假申请", "被退回 · 请假 10-26", "补充事由", "去修改", "bad")
    assert last["target"] == {"key": "attendance.detail", "params": {"request": "OA-2"}}
    data["queue"] = [queue_item(name=f"OA-{i}", query={"request": f"OA-{i}"}) for i in range(10, 18)]
    assert len(run("todo.queue", make_ctx())) == personal.MAX_ROWS
    assert run("todo.queue", make_ctx(employee="")) is not None            # 没有员工档案也能看审批待办，只是不带"被退回"
    data["queue"] = []
    assert run("todo.queue", make_ctx(employee="")) == []


# ---------------------------------------------------------------- 取数函数确实接到了现有接口
def test_loaders_call_the_real_apis(monkeypatch):
    import frappe
    from rayher_hr_payroll import oa_feature_gate
    from rayher_hr_payroll.api import attendance_entry, monthly_timesheet_entry, oa_entry, overview_entry, timesheet_entry

    seen = {}
    monkeypatch.setattr(overview_entry, "get_my_requests", lambda limit: {"items": [{"name": "OA-1", "limit": limit}]})
    assert personal._load_my_requests(50) == [{"name": "OA-1", "limit": 50}]
    monkeypatch.setattr(overview_entry, "get_my_approval_queue", lambda limit: {"items": [{"name": "Q"}], "limit": limit})
    assert personal._load_approval_queue(8) == [{"name": "Q"}]
    monkeypatch.setattr(overview_entry, "get_my_notification_feed", lambda **kw: {"categories": [{"key": "cc", "unread": 2}, {"key": "mine", "unread": None}]})
    assert personal._load_notification_counts() == {"cc": 2, "mine": 0}
    monkeypatch.setattr(oa_entry, "get_my_approval_summary", lambda: {"total": 0, "categories": []})
    assert personal._load_approval_summary() == {"total": 0, "categories": []}
    monkeypatch.setattr(overview_entry, "get_my_leave_summary", lambda: {"visible": False})
    assert personal._load_leave_summary() == {"visible": False}
    monkeypatch.setattr(monthly_timesheet_entry, "list_monthly_entries", lambda period, employee=None: seen.update(entries=(period, employee)) or {})
    personal._load_my_entries("2026-10", "E0")
    assert seen["entries"] == ("2026-10", "E0")

    def home(period=None):
        raise frappe.PermissionError("当前审批功能暂未开放。")

    monkeypatch.setattr(attendance_entry, "get_attendance_home", home)
    assert personal._load_attendance_home("2026-10") == {}          # 功能没开放不当成块失败

    # 工时填报名单：研发类型 + 不是免填账号
    monkeypatch.setattr(frappe, "db", type("DB", (), {"get_value": staticmethod(lambda doctype, name, field: "全时研发" if name == "E0" else "")}), raising=False)
    assert personal._load_is_rd("u@example.com", "E0") is True and personal._load_is_rd("u@example.com", "E1") is False
    exempt = sorted(monthly_timesheet_entry.TIMESHEET_EXEMPT_USERS)[0]
    assert personal._load_is_rd(exempt.upper(), "E0") is False
    assert "全时研发" in timesheet_entry.RD_TYPES

    # 我的报销：本人是申请人或所有人；功能关闭返回 None
    def get_all(doctype, **kw):
        seen["claims"] = (doctype, kw)
        return [{"name": "C1"}]

    monkeypatch.setattr(frappe, "get_all", get_all, raising=False)
    monkeypatch.setattr(oa_feature_gate, "can_access_request_type", lambda request_type, user=None: True)
    assert personal._load_my_claims("u@example.com", "E0") == [{"name": "C1"}]
    doctype, kw = seen["claims"]
    assert doctype == "OA Approval Request" and kw["filters"]["request_type"] == "报销单"
    assert kw["or_filters"] == [["owner", "=", "u@example.com"], ["employee", "=", "E0"]]
    assert kw["filters"]["workflow_status"] == ["in", ["草稿", "待审批", "待办理"]]
    monkeypatch.setattr(oa_feature_gate, "can_access_request_type", lambda request_type, user=None: False)
    assert personal._load_my_claims("u@example.com", "E0") is None


# ---------------------------------------------------------------- 我的下两周 / 我的假期
def strip_days():
    out = []
    for index in range(14):
        day = 9 + index
        out.append({"date": f"2026-10-{day:02d}", "label": f"10/{day}", "day": day, "weekday": "五", "off_day": index in (1, 2, 8, 9),
                    "kind": {0: "annual", 3: "comp", 4: "trip"}.get(index), "pending": index == 3, "hours": 8})
    return out


def test_my_strip_is_one_calendar_row_without_staff_totals(data, monkeypatch):
    monkeypatch.setattr(personal, "_load_my_strip", lambda ctx: strip_days())
    block = run("block.me_strip", make_ctx())
    assert block["type"] == "calendar" and block["title"] == "我的下两周" and block["totals"] == []
    assert [person["name"] for person in block["people"]] == ["我"] and len(block["days"]) == 14
    cells = block["people"][0]["cells"]
    assert cells[0] == {"kind": "annual", "pending": False} and cells[3] == {"kind": "comp", "pending": True} and cells[1] is None
    assert block["days"][1]["off_day"] is True
    assert block["target"]["key"] == "attendance.home"


def test_my_strip_is_left_out_without_an_employee_record_or_without_data(data, monkeypatch):
    monkeypatch.setattr(personal, "_load_my_strip", lambda ctx: pytest.fail("没有员工档案不能取"))
    assert run("block.me_strip", make_ctx(employee="")) is None
    monkeypatch.setattr(personal, "_load_my_strip", lambda ctx: [])
    assert run("block.me_strip", make_ctx()) is None


def test_my_balances_show_annual_and_comp_as_bars(data):
    data["leave"]["annual"] = {"available": 6.5, "granted": 10.0, "used": 3.5, "reserved": 1.0, "eligible": True, "message": ""}
    data["leave"]["comp"] = {"available": 1.5, "credit": 3.0, "used": 0.0, "reserved": 0.0}
    block = run("block.me_balances", make_ctx())
    assert [(r["label"], r["value"], r["pct"], r["tone"]) for r in block["rows"]] == [
        ("年假", "可用 6.5 / 10 天", 65.0, "ok"), ("调休", "可用 12 小时", 50.0, "info")]
    assert block["sub"] == "已用 3.5 天 · 审批中 1 天"
    data["leave"]["annual"] = {"eligible": False, "message": "演示员工173期内暂无年假"}
    only_comp = run("block.me_balances", make_ctx())
    assert [r["label"] for r in only_comp["rows"]] == ["调休"] and only_comp["sub"] == "年假暂未发放"
    data["leave"] = {"visible": False}
    assert run("block.me_balances", make_ctx()) is None
    assert run("block.me_balances", make_ctx(employee="")) is None


def test_a_handled_trip_shows_a_reminder_to_arrange_the_itinerary_until_the_return_day(data):
    """前台办理完：申请人看板上有一条行程提醒（带前台备注），和抄送、已完成通知不一样；没有出差就不出现。"""
    ctx = make_ctx()
    assert run("alert.me_trip", ctx) is None
    data["trips"] = [{"name": "OA-T1", "travel_destination": "上海", "travel_start_date": "2026-10-12", "travel_end_date": "2026-10-14", "note": "机票已订"},
                     {"name": "OA-T2", "travel_destination": "北京", "travel_start_date": "2026-10-20", "travel_end_date": "2026-10-20", "note": ""}]
    item = run("alert.me_trip", make_ctx())
    assert item["title"] == "10-12 至 10-14 去上海出差，前台已办理，请安排好行程，另有 1 次出差"
    assert item["sub"] == "机票已订" and item["tone"] == "info"
    assert item["target"] == {"key": "travel.detail", "params": {"request": "OA-T1"}}
    data["trips"] = data["trips"][1:]
    item = run("alert.me_trip", make_ctx())
    assert item["title"] == "10-20 去北京出差，前台已办理，请安排好行程" and item["sub"] == "请安排好手头的工作和交接"


def test_every_role_overview_carries_the_trip_reminder():
    for profile, spec in layout.LAYOUTS.items():
        overview = spec["tabs"][0]
        assert "alert.me_trip" in overview["alerts"], profile
