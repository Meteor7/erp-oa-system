"""出差前台办理复查（2026-10-13）：前台这一步服务端也不能加签；岗位没任命时撤回照样成功；补丁只补前台岗位；
抄送轮次不受日志条数上限影响；费用审批记录不重复列同意 / 已办理；行程提醒只给真的经过前台办理的出差。"""
import inspect
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import oa_role_resolver
from rayher_hr_payroll.api import oa_entry
from rayher_hr_payroll.dashboard import core, personal
from rayher_hr_payroll.invoice_ocr import service
from rayher_hr_payroll.patches.v1_0 import seed_front_desk_assignment


class Refused(Exception):
    pass


def _throw(message, exc=None):
    raise Refused(message)


@pytest.fixture
def fake_frappe(monkeypatch):
    stub = SimpleNamespace(_=lambda text: text, throw=_throw, session=SimpleNamespace(user="desk@tests-x.example.invalid"), local=SimpleNamespace(),
                           db=None, get_doc=None)
    monkeypatch.setattr(oa_entry, "frappe", stub)
    monkeypatch.setattr(oa_entry, "now_datetime", lambda: "2026-10-13 10:00:00")
    return stub


class Doc(SimpleNamespace):
    def set(self, field, value):
        setattr(self, field, list(value))

    def append(self, field, row):
        getattr(self, field).append(SimpleNamespace(**row))


def _step(mode="handle", status="待办理", **extra):
    values = dict(step_index=3, step_key="desk", origin="base", mode=mode, label="前台办理：演示员工30" if mode == "handle" else "副总经理：演示员工21",
                  approvers='["desk@tests-x.example.invalid"]', approved_by="[]", status=status, action_by="", acted_on=None, note="")
    values.update(extra)
    return SimpleNamespace(**values)


def _trip(step):
    return Doc(name="OA-T1", request_type="出差申请", workflow_status=step.status, business_status="待前台办理", current_step_index=3,
               current_step_label=step.label, steps=[step], operation_log="[]", copied_to="[]", expense_lines=[],
               department="研发软件部 - RAY", supervisor="", asset_category="", employee="E1")


# ---------------------------------------------------------------- 1. 加签
@pytest.fixture
def add_sign(fake_frappe, monkeypatch):
    monkeypatch.setattr(oa_entry.invoice_service, "_transaction_lock", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "require_request_type_access", lambda request_type: None)
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda step, user=None: ["desk@tests-x.example.invalid"])
    monkeypatch.setattr(oa_entry, "_can_act_on_current_step", lambda doc, user=None: True)
    return inspect.unwrap(oa_entry.add_sign_request)


def test_the_front_desk_cannot_add_sign_through_the_api(add_sign, monkeypatch):
    document = _trip(_step())
    monkeypatch.setattr(oa_entry, "_load_request", lambda *args, **kwargs: document)
    inserted = []
    monkeypatch.setattr(oa_entry, "_insert_add_sign_step", lambda *args: inserted.append(args))
    for position in ("before", "after"):
        with pytest.raises(Refused, match="前台办理这一步不能加签"):
            add_sign("OA-T1", "boss@tests-x.example.invalid", position, "请看一下", expected_step_key="desk")
    assert inserted == [] and len(document.steps) == 1 and document.operation_log == "[]"


def test_approval_steps_of_a_trip_can_still_add_sign(add_sign, monkeypatch):
    document = _trip(_step(mode="approve", status="待审批"))
    monkeypatch.setattr(oa_entry, "_load_request", lambda *args, **kwargs: document)
    monkeypatch.setattr(oa_entry, "_resolve_add_sign_approver", lambda value: _throw("reached the add-sign path"))
    with pytest.raises(Refused, match="reached the add-sign path"):
        add_sign("OA-T1", "boss@tests-x.example.invalid", "before", "请看一下", expected_step_key="desk")


# ---------------------------------------------------------------- 2. 补丁只补前台；岗位没任命也能撤回
class Store:
    def __init__(self, holders):
        self.assignments = {}
        self.holders = holders
        self.enabled = {row["user_id"] for rows in holders.values() for row in rows}

    def assignment_exists(self, role_key):
        return role_key in self.assignments

    def employees_for_designation(self, designation):
        return list(self.holders.get(designation, []))

    def is_user_enabled(self, user):
        return user in self.enabled

    def upsert_assignment(self, role_key, role_label, employee, user):
        self.assignments[role_key] = (employee, user)


def _holder(name, user):
    return {"name": name, "employee_name": name, "user_id": user, "status": "Active"}


def test_only_the_front_desk_position_is_seeded_and_a_skip_says_why(monkeypatch, capsys):
    store = Store({"行政专员": [_holder("E-FD", "fd@tests-x.example.invalid")], "出纳": [_holder("E-CA", "ca@tests-x.example.invalid")]})
    assert oa_role_resolver.seed_missing_assignment("front_desk", store=store) == (True, "")
    assert store.assignments == {"front_desk": ("E-FD", "fd@tests-x.example.invalid")}, "出纳等别的空岗位不跟着补"
    seeded, reason = oa_role_resolver.seed_missing_assignment("front_desk", store=store)
    assert seeded is False and "已有岗位任命" in reason
    two = Store({"行政专员": [_holder("E-1", "a@tests-x.example.invalid"), _holder("E-2", "b@tests-x.example.invalid")]})
    seeded, reason = oa_role_resolver.seed_missing_assignment("front_desk", store=two)
    assert seeded is False and "多个" in reason and two.assignments == {}
    assert oa_role_resolver.seed_missing_assignment("nobody", store=two)[0] is False

    calls = []
    monkeypatch.setattr(seed_front_desk_assignment, "seed_missing_assignment",
                        lambda role_key: calls.append(role_key) or (False, "审批角色前台办理没有找到在职人员"))
    monkeypatch.setattr(seed_front_desk_assignment.frappe, "db", SimpleNamespace(commit=lambda: None), raising=False)
    seed_front_desk_assignment.execute()
    assert calls == ["front_desk"]
    assert "前台办理没有找到在职人员" in capsys.readouterr().out


def test_withdrawing_works_when_a_route_position_has_no_assignment(fake_frappe, monkeypatch):
    # 副总已经批过、现在在总经理这一步；前台办理岗位没有任命，preview_route 会报“没有找到有效配置”。
    step = _step(mode="approve", status="待审批", approved_by='["vm@tests-x.example.invalid"]', action_by="vm@tests-x.example.invalid", note="同意")
    document = _trip(step)
    monkeypatch.setattr(oa_entry, "_route_context", lambda **kwargs: {"department": "研发软件部 - RAY", "supervisor": "", "asset_category": ""})

    def no_front_desk(*args, **kwargs):
        raise oa_entry.ApprovalRouteError("审批角色前台办理没有找到有效配置，请在岗位任命中设置")

    monkeypatch.setattr(oa_entry, "_resolve_approval_roles", no_front_desk)
    monkeypatch.setattr(oa_entry, "preview_route", lambda *args, **kwargs: pytest.fail("岗位没任命时不能再算路线"))
    oa_entry._reset_request_to_draft(document, "改日期")
    assert document.workflow_status == "草稿" and document.current_step_index == 0 and document.current_step_label == ""
    assert document.steps == [step] and step.status == "待流转" and step.approved_by == "[]" and step.action_by == "" and step.note == ""
    event = json.loads(document.operation_log)[-1]
    assert event["action"] == "撤回申请" and event["details"]["steps"][0]["approved_by"] == ["vm@tests-x.example.invalid"]


def test_withdrawing_still_rebuilds_the_route_when_every_position_resolves(fake_frappe, monkeypatch):
    document = _trip(_step(mode="approve", status="待审批"))
    monkeypatch.setattr(oa_entry, "_route_context", lambda **kwargs: {"department": "研发软件部 - RAY", "supervisor": "", "asset_category": ""})
    monkeypatch.setattr(oa_entry, "_resolve_approval_roles", lambda *args, **kwargs: {})
    route = {"steps": [{"step_index": 1, "label": "前台办理：演示员工30", "mode": "handle", "approvers": ["desk@tests-x.example.invalid"], "status": "待流转"}],
             "copied_to": [{"user": "hr@tests-x.example.invalid"}]}
    monkeypatch.setattr(oa_entry, "preview_route", lambda *args, **kwargs: route)
    oa_entry._reset_request_to_draft(document)
    assert [row.label for row in document.steps] == ["前台办理：演示员工30"] and json.loads(document.copied_to) == [{"user": "hr@tests-x.example.invalid"}]


# ---------------------------------------------------------------- 4. 日志上限和按轮次的键
def test_copy_notification_rounds_do_not_stall_when_the_log_is_full(fake_frappe, monkeypatch):
    assert oa_entry.OPERATION_LOG_LIMIT == 500 and service.OPERATION_LOG_LIMIT == 500
    sent = []

    class Note(dict):
        def insert(self, ignore_permissions=False):
            sent.append(self["subject"])

    fake_frappe.get_doc = lambda values: Note(values)
    fake_frappe.db = SimpleNamespace(exists=lambda *args, **kwargs: False)
    monkeypatch.setattr(oa_entry, "_request_link", lambda doc: "/x")
    events = [{"action": "同意"}] * (oa_entry.OPERATION_LOG_LIMIT - 1) + [{"action": "提交申请"}]
    doc = SimpleNamespace(name="OA-L1", request_type=oa_entry.REQUEST_LEAVE, copied_to=json.dumps([{"user": "hr@tests-x.example.invalid"}]),
                          operation_log=json.dumps(events))
    oa_entry._notify_copied_users(doc)
    # 日志满了：再驳回、再提交，条数还是上限，轮次照样往上走
    events = (events + [{"action": "Targeted rejection"}, {"action": "提交申请"}])[-oa_entry.OPERATION_LOG_LIMIT:]
    doc.operation_log = json.dumps(events)
    assert len(events) == oa_entry.OPERATION_LOG_LIMIT
    oa_entry._notify_copied_users(doc)
    assert sent[0].endswith(":n1]") and sent[1].endswith(":n2]")


# ---------------------------------------------------------------- 5. 费用审批记录不重复
def test_expense_approval_records_list_each_approval_once(fake_frappe, monkeypatch):
    step = SimpleNamespace(step_index=1, step_key="s1", label="出纳审核", mode="approve", approvers='["fin@tests-x.example.invalid"]', status="已通过",
                           approved_by='["fin@tests-x.example.invalid"]', action_by="fin@tests-x.example.invalid", acted_on="2026-10-13 09:00:00", note="ok")
    log = [{"action": "提交申请", "actor": "a@tests-x.example.invalid", "acted_on": "2026-10-12 09:00:00"},
           {"action": "同意", "actor": "fin@tests-x.example.invalid", "acted_on": "2026-10-13 09:00:00"},
           {"action": "已办理", "actor": "desk@tests-x.example.invalid", "acted_on": "2026-10-13 10:00:00"}]
    doc = SimpleNamespace(name="OA-E1", subject="办公用品", employee="E1", employee_name="演示员工117", department="研发软件部", source_type="",
                          workflow_status="待审批", steps=[step], operation_log=json.dumps(log))
    monkeypatch.setattr(oa_entry, "require_request_type_access", lambda request_type: None)
    monkeypatch.setattr(oa_entry, "_expense_report_documents", lambda **kwargs: ([doc], False))
    records = inspect.unwrap(oa_entry.list_expense_approval_records)()["records"]
    assert sorted((row["event_type"], row["action"]) for row in records) == [("审批节点", "已通过"), ("操作日志", "提交申请")]


# ---------------------------------------------------------------- 6. 行程提醒
def test_the_itinerary_alert_only_counts_trips_the_front_desk_handled(monkeypatch):
    import frappe

    trips = [
        {"name": "OA-OLD", "travel_destination": "北京", "travel_start_date": "2026-10-10", "travel_end_date": "2026-10-11"},
        {"name": "OA-OWN", "travel_destination": "上海", "travel_start_date": "2026-10-12", "travel_end_date": "2026-10-14"},
        {"name": "OA-DESK", "travel_destination": "深圳", "travel_start_date": "2026-10-20", "travel_end_date": "2026-10-21"},
    ]
    # 旧路线没有办理节点；前台自己的出差也没有；只有 OA-DESK 经过前台办理。
    steps = {"OA-OLD": [], "OA-OWN": [], "OA-DESK": [{"status": "已办理", "note": " 机票已订 "}]}

    def sql(query, values=None, as_dict=False):
        if "tabOA Approval Step" in query:
            return steps[values[0]]
        return [dict(row) for row in trips]

    monkeypatch.setattr(frappe, "db", SimpleNamespace(sql=sql), raising=False)
    ctx = core.Ctx(user="u@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-09",
                   employee="E0", department="研发软件部 - RAY")
    rows = personal._load_my_trips(ctx)
    assert [row["name"] for row in rows] == ["OA-DESK"] and rows[0]["note"] == "机票已订"
    item = core.REGISTRY["alert.me_trip"].fn(ctx)
    assert item["title"] == "10-20 至 10-21 去深圳出差，前台已办理，请安排好行程" and item["sub"] == "机票已订"

    steps["OA-DESK"] = [{"status": "待办理", "note": ""}]
    other = core.Ctx(user="u@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-09",
                     employee="E0", department="研发软件部 - RAY")
    assert core.REGISTRY["alert.me_trip"].fn(other) is None, "没办理完或没有前台这一步就不说“前台已办理”"
