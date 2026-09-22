from datetime import date

import pytest

from rayher_hr_payroll import invoice_folder as folder
from rayher_hr_payroll import payment_invoice_reminders as reminders


@pytest.mark.parametrize("recognition, linked_request, expected", [
    ("排队中", "", "识别中"),
    ("识别中", "", "识别中"),
    ("待确认", "", "待确认"),
    ("已确认", "", "可用"),
    ("已确认", None, "可用"),
    ("已确认", "OA-2026-1", "已使用"),
    ("疑似重复", "", "疑似重复"),
    ("失败", "", "识别失败"),
    ("已排除", "", "已排除"),
])
def test_folder_status(recognition, linked_request, expected):
    assert folder.folder_status(recognition, linked_request) == expected


TODAY = date(2026, 9, 22)


@pytest.mark.parametrize("expected, kind, suffix", [
    ("2026-09-26", None, None),
    ("2026-09-25", "即将到期", "soon:2026-09-25"),
    ("2026-09-23", "即将到期", "soon:2026-09-23"),
    ("2026-09-22", "今天到期", "today:2026-09-22"),
    ("2026-09-20", "已逾期", "overdue:2026-09-20:2026-09-22"),
    (None, None, None),
])
def test_reminder_schedule(expected, kind, suffix):
    assert folder.reminder(expected, TODAY) == (kind, suffix)


def test_due_soon_is_sent_once_per_expected_date_but_overdue_every_day():
    assert folder.reminder("2026-09-25", TODAY)[1] == folder.reminder("2026-09-25", date(2026, 9, 23))[1]
    assert folder.reminder("2026-09-20", TODAY)[1] != folder.reminder("2026-09-20", date(2026, 9, 23))[1]


def test_due_state_labels():
    assert folder.due_state("2026-09-30", TODAY) == ""
    assert folder.due_state("2026-09-24", TODAY) == "2 天后到期"
    assert folder.due_state("2026-09-22", TODAY) == "今天到期"
    assert folder.due_state("2026-09-19", TODAY) == "已逾期 3 天"
    assert "已逾期 3 天" in folder.reminder_text("已逾期", "OA-1", "2026-09-19", TODAY)


class Store:
    def __init__(self):
        self.sent = []

    def notification_exists(self, *, for_user, document_name, key):
        return any(row["for_user"] == for_user and f"[{key}]" in row["subject"] for row in self.sent)

    def create_notification(self, **values):
        self.sent.append(values)


def test_job_sends_each_reminder_once(monkeypatch):
    rows = [
        {"name": "PAY-1", "owner": "wang@example.com", "employee": "EMP-1", "subject": "x", "request_type": "付款单", "expected_invoice_date": date(2026, 9, 24)},
        {"name": "PAY-2", "owner": "li@example.com", "employee": "EMP-2", "subject": "y", "request_type": "付款单", "expected_invoice_date": date(2026, 9, 20)},
        {"name": "PAY-3", "owner": "li@example.com", "employee": "EMP-2", "subject": "z", "request_type": "付款单", "expected_invoice_date": date(2026, 10, 30)},
    ]
    monkeypatch.setattr(reminders, "pending_payments", lambda: rows)
    store = Store()
    assert reminders.send_payment_invoice_reminders(TODAY, store=store) == 2
    assert reminders.send_payment_invoice_reminders(TODAY, store=store) == 0
    assert reminders.send_payment_invoice_reminders(date(2026, 9, 23), store=store) == 1  # PAY-2 overdue again
    assert [row["for_user"] for row in store.sent] == ["wang@example.com", "li@example.com", "li@example.com"]
    assert store.sent[0]["link"].endswith("?request=PAY-1")
