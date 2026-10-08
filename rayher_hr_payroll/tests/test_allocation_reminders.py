"""月初提醒财务主管给上个月的研发费用分摊定版：日期规则、条件、去重、永不抛错。"""
import importlib
import sys
import types
from datetime import date, datetime
from types import SimpleNamespace

import pytest


@pytest.fixture
def reminders():
    return importlib.import_module("rayher_hr_payroll.allocation_reminders")


class Outbox:
    """内存里的通知箱：模拟 Notification Log 的去重查询和写入。"""

    def __init__(self):
        self.sent = []

    def already_sent(self, user, import_name, key):
        return any(item["user"] == user and item["import"] == import_name and item["key"] == key for item in self.sent)

    def send(self, user, import_name, key, subject, content):
        self.sent.append({"user": user, "import": import_name, "key": key, "subject": subject, "content": content})


def _setup(monkeypatch, reminders, *, import_name="IMP-2026-09", submitted=False, users=("zhangmeng@example.com",),
           unfilled=3, enabled=True):
    outbox = Outbox()
    seen = {"import_lookups": [], "allocation_lookups": [], "unfilled_lookups": []}
    monkeypatch.setattr(reminders, "_previous_import", lambda y, m: seen["import_lookups"].append((y, m)) or import_name)
    monkeypatch.setattr(reminders, "_has_submitted_allocation", lambda y, m: seen["allocation_lookups"].append((y, m)) or submitted)
    monkeypatch.setattr(reminders, "_finance_managers", lambda: list(users))
    monkeypatch.setattr(reminders, "_unfilled_people", lambda y, m: seen["unfilled_lookups"].append((y, m)) or unfilled)
    monkeypatch.setattr(reminders, "_enabled", lambda user: enabled)
    monkeypatch.setattr(reminders, "_already_sent", outbox.already_sent)
    monkeypatch.setattr(reminders, "_send", outbox.send)
    return outbox, seen


def test_previous_month_wraps_the_year(reminders):
    assert reminders.previous_month(date(2026, 10, 3)) == (2026, 9)
    assert reminders.previous_month(date(2027, 1, 1)) == (2026, 12)


@pytest.mark.parametrize("day, expected", [(1, True), (3, True), (5, True), (6, False), (15, False), (31, False)])
def test_only_days_one_to_five_are_in_the_window(reminders, day, expected):
    assert reminders.in_reminder_window(date(2026, 8, day)) is expected


@pytest.mark.parametrize("day", [6, 7, 20, 31])
def test_does_not_run_after_the_fifth_and_never_touches_the_database(monkeypatch, reminders, day):
    outbox, seen = _setup(monkeypatch, reminders)

    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, day)) == 0

    assert outbox.sent == []
    assert seen == {"import_lookups": [], "allocation_lookups": [], "unfilled_lookups": []}


def test_sends_one_notification_to_the_finance_manager_for_the_previous_month(monkeypatch, reminders):
    outbox, seen = _setup(monkeypatch, reminders, unfilled=4)

    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 2)) == 1

    assert seen["import_lookups"] == [(2026, 9)]
    assert seen["allocation_lookups"] == [(2026, 9)]
    assert seen["unfilled_lookups"] == [(2026, 9)]
    assert outbox.sent == [{
        "user": "zhangmeng@example.com",
        "import": "IMP-2026-09",
        "key": "alloc-finalize:2026-09:2026-10-02",
        "subject": "2026年9月研发费用分摊待定版",
        "content": "2026年9月的研发费用分摊还没有定版：还有 4 人工时没填满，请到「研发费用台账」检查后定版。",
    }]


def test_january_reminds_about_december_of_the_previous_year(monkeypatch, reminders):
    outbox, seen = _setup(monkeypatch, reminders, unfilled=1)

    assert reminders.remind_finance_manager_to_finalize(datetime(2027, 1, 4, 8, 0)) == 1

    assert seen["import_lookups"] == [(2026, 12)]
    assert outbox.sent[0]["content"].startswith("2026年12月的研发费用分摊还没有定版：还有 1 人工时没填满，")
    assert outbox.sent[0]["key"] == "alloc-finalize:2026-12:2027-01-04"


def test_text_when_everyone_has_filled_their_hours(reminders):
    assert reminders.reminder_text(2026, 9, 0) == "2026年9月的研发费用分摊还没有定版：工时都已填满，请到「研发费用台账」检查后定版。"


def test_same_day_rerun_does_not_send_again_but_the_next_day_does(monkeypatch, reminders):
    outbox, _seen = _setup(monkeypatch, reminders, users=("a@example.com", "b@example.com"))

    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 2)) == 2
    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 2)) == 0
    assert len(outbox.sent) == 2
    # 只有一个人没收到时只补发给他
    outbox.sent.pop()
    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 2)) == 1
    assert [item["user"] for item in outbox.sent] == ["a@example.com", "b@example.com"]
    # 第二天重新提醒（每天一条，直到定版或过了 5 号）
    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 3)) == 2
    assert len(outbox.sent) == 4


def test_no_reminder_when_the_previous_month_has_no_import(monkeypatch, reminders):
    outbox, seen = _setup(monkeypatch, reminders, import_name=None)

    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 1)) == 0

    assert outbox.sent == []
    assert seen["allocation_lookups"] == []


def test_no_reminder_when_the_previous_month_is_already_finalized(monkeypatch, reminders):
    outbox, seen = _setup(monkeypatch, reminders, submitted=True)

    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 1)) == 0

    assert outbox.sent == []
    assert seen["unfilled_lookups"] == []


def test_skips_quietly_when_nobody_holds_the_finance_manager_position(monkeypatch, reminders):
    outbox, seen = _setup(monkeypatch, reminders, users=())

    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 1)) == 0

    assert outbox.sent == []
    assert seen["unfilled_lookups"] == []


def test_skips_disabled_users(monkeypatch, reminders):
    outbox, _seen = _setup(monkeypatch, reminders, enabled=False)

    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 1)) == 0
    assert outbox.sent == []


def test_never_raises_and_logs_when_the_lookup_fails(monkeypatch, reminders):
    outbox, _seen = _setup(monkeypatch, reminders)
    logged = []
    monkeypatch.setattr(reminders, "_log_failure", lambda: logged.append("logged"))

    def boom(year, month):
        raise RuntimeError("database down")

    monkeypatch.setattr(reminders, "_previous_import", boom)

    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 1)) == 0
    assert logged == ["logged"]
    assert outbox.sent == []


def test_a_failure_for_one_user_does_not_stop_the_next(monkeypatch, reminders):
    outbox, _seen = _setup(monkeypatch, reminders, users=("a@example.com", "b@example.com"))
    logged = []
    monkeypatch.setattr(reminders, "_log_failure", lambda: logged.append("logged"))

    def send(user, import_name, key, subject, content):
        if user == "a@example.com":
            raise RuntimeError("mail queue broken")
        outbox.send(user, import_name, key, subject, content)

    monkeypatch.setattr(reminders, "_send", send)

    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 1)) == 1
    assert logged == ["logged"]
    assert [item["user"] for item in outbox.sent] == ["b@example.com"]


def test_a_failing_error_log_still_does_not_raise(monkeypatch, reminders):
    fake = types.ModuleType("frappe")

    def log_error(**kwargs):
        raise RuntimeError("log table gone")

    fake.log_error = log_error
    fake.get_traceback = lambda: "trace"
    monkeypatch.setitem(sys.modules, "frappe", fake)
    monkeypatch.setattr(reminders, "_previous_import", lambda y, m: (_ for _ in ()).throw(RuntimeError("x")))

    assert reminders.remind_finance_manager_to_finalize(date(2026, 10, 1)) == 0


def test_notification_log_shape_and_dedupe_query(monkeypatch, reminders):
    fake = types.ModuleType("frappe")
    exists_calls = []
    inserted = []

    class NotificationLog:
        def __init__(self, values):
            self.values = values

        def insert(self, ignore_permissions=False):
            inserted.append((self.values, ignore_permissions))

    fake.get_doc = lambda values: NotificationLog(values)
    fake.db = SimpleNamespace(exists=lambda doctype, filters: exists_calls.append((doctype, filters)) or False)
    monkeypatch.setitem(sys.modules, "frappe", fake)

    key = reminders.reminder_key(2026, 9, date(2026, 10, 2))
    assert key == "alloc-finalize:2026-09:2026-10-02"
    assert reminders._already_sent("a@example.com", "IMP-1", key) is False
    reminders._send("a@example.com", "IMP-1", key, "2026年9月研发费用分摊待定版", "正文")

    assert exists_calls == [("Notification Log", {
        "for_user": "a@example.com", "document_type": "RD Expense Import", "document_name": "IMP-1",
        "subject": ["like", "%[alloc-finalize:2026-09:2026-10-02]%"],
    })]
    assert inserted == [({
        "doctype": "Notification Log", "for_user": "a@example.com", "type": "Alert",
        "document_type": "RD Expense Import", "document_name": "IMP-1",
        "subject": "2026年9月研发费用分摊待定版 [alloc-finalize:2026-09:2026-10-02]",
        "email_content": "正文", "link": "/planck-semicon/allocation",
    }, True)]


def test_unfilled_people_counts_none_and_part_only(monkeypatch, reminders):
    api_package = importlib.import_module("rayher_hr_payroll.api")
    calls = []
    fake_module = SimpleNamespace(_fill_rows=lambda year, month, scope: calls.append((year, month, scope)) or [
        {"status": status} for status in ("none", "none", "part", "full", "over")
    ])
    monkeypatch.setattr(api_package, "monthly_timesheet_entry", fake_module, raising=False)
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.api.monthly_timesheet_entry", fake_module)

    assert reminders._unfilled_people(2026, 9) == 3
    assert calls == [(2026, 9, None)]


def test_the_job_is_registered_as_a_daily_scheduler_event():
    from rayher_hr_payroll import hooks

    assert "rayher_hr_payroll.allocation_reminders.remind_finance_manager_to_finalize" in hooks.scheduler_events["daily"]
