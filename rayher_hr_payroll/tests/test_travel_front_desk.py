"""出差的前台办理（决定 2026-10-13）：前台只能点“已办理”，不能退回、不能加签；办完给申请人一条单独的行程提醒。"""
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import oa_assignments
from rayher_hr_payroll.api import oa_entry


def doc(mode="handle", request_type="出差申请", status="待办理"):
    step = SimpleNamespace(step_index=3, mode=mode, label="前台办理：演示员工30" if mode == "handle" else "演示员工113经理：演示员工21", approvers='["desk@tests-x.example.invalid"]')
    return SimpleNamespace(request_type=request_type, workflow_status=status, current_step_index=3, steps=[step]), step


@pytest.fixture
def can_act(monkeypatch):
    monkeypatch.setattr(oa_entry, "_can_act_on_current_step", lambda document, user=None: True)
    monkeypatch.setattr(oa_entry, "_is_oa_override_user", lambda user=None: False)
    monkeypatch.setattr(oa_entry, "_classification_ready", lambda document: True)
    monkeypatch.setattr(oa_entry, "_is_finance_audit_step", lambda step: False)
    monkeypatch.setattr(oa_entry, "_is_contract_delivery_step", lambda step: False)


def test_the_front_desk_can_only_mark_the_trip_handled(can_act):
    document, step = doc()
    assert oa_entry._is_travel_desk_step(document, step) is True
    caps = oa_entry._request_capabilities(document)
    assert caps["can_approve"] is True
    assert caps["can_reject"] is False and caps["can_add_sign"] is False and caps["can_add_sign_after"] is False


@pytest.mark.parametrize("mode, request_type", [("approve", "出差申请"), ("handle", "报销单")])
def test_other_steps_and_other_types_keep_reject(can_act, mode, request_type):
    document, step = doc(mode=mode, request_type=request_type)
    assert oa_entry._is_travel_desk_step(document, step) is False
    assert oa_entry._request_capabilities(document)["can_reject"] is True


class Store:
    def __init__(self):
        self.sent = []

    def notification_exists(self, *, for_user, document_name, key):
        return any(item["key"] == key for item in self.sent)

    def create_notification(self, *, for_user, document_name, subject, content, link):
        self.sent.append({"user": for_user, "name": document_name, "subject": subject, "content": content, "link": link,
                          "key": subject.split("[")[-1].rstrip("]")})


def test_the_applicant_gets_a_separate_itinerary_reminder_once():
    trip = SimpleNamespace(name="OA-T1", owner="wu@tests-x.example.invalid", employee="E1", request_type="出差申请", travel_destination="上海",
                           travel_start_date="2026-10-12", travel_end_date="2026-10-14", travel_days=3)
    store = Store()
    assert oa_assignments.notify_travel_arranged(trip, actor="desk@tests-x.example.invalid", note="机票 CA1234 已订", event_key="oa-travel-arranged:OA-T1:1", store=store) is True
    sent = store.sent[0]
    assert sent["user"] == "wu@tests-x.example.invalid" and sent["subject"].startswith("出差已办理，请安排行程：OA-T1")
    assert "出差地点：上海" in sent["content"] and "2026-10-12 至 2026-10-14（3 天）" in sent["content"]
    assert "前台备注：机票 CA1234 已订" in sent["content"] and "请按行程安排好手头的工作和交接" in sent["content"]
    assert sent["link"] == "/planck-semicon/approval/travel?request=OA-T1"
    assert oa_assignments.notify_travel_arranged(trip, event_key="oa-travel-arranged:OA-T1:1", store=store) is False, "sent only once"
    # 不是“抄送”、也不是“已完成”：通知中心按申请人自己的单据归到“我的申请”
    from rayher_hr_payroll.api.overview_entry import classify
    assert classify(sent["subject"], "OA Approval Request", "OA-T1", "wu@tests-x.example.invalid", {"OA-T1": "wu@tests-x.example.invalid"})[0] == "mine"


def test_the_trip_route_resolves_the_front_desk_position(monkeypatch):
    monkeypatch.setattr(oa_entry, "resolve_role", lambda key: {"role_key": key})
    assert list(oa_entry._resolve_approval_roles("出差申请")) == ["vice_manager", "general_manager", "front_desk"]
