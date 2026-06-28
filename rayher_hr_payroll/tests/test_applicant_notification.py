import types

import rayher_hr_payroll.approval_config as ac


class Doc:
    def __init__(self, **kw):
        self.doctype = kw.pop("doctype", "Expense Claim")
        self.name = kw.pop("name", "EXP-1")
        self.owner = kw.pop("owner", "hr@co")
        self.employee = kw.pop("employee", "EMP-1")
        self._before = kw.pop("before", None)
        self.__dict__.update(kw)

    def get_doc_before_save(self):
        return self._before


def _patch(monkeypatch, inserted, user_id="emp@co"):
    monkeypatch.setattr(ac, "frappe", types.SimpleNamespace(
        db=types.SimpleNamespace(get_value=lambda dt, name, field: user_id),
        get_doc=lambda d: types.SimpleNamespace(insert=lambda **k: inserted.append(d)),
    ))


def test_hr_created_claim_notifies_applicant(monkeypatch):
    inserted = []
    _patch(monkeypatch, inserted)
    ac.notify_applicant_on_decision(Doc(workflow_state="财务已审", owner="hr@co"))
    assert inserted and inserted[0]["for_user"] == "emp@co" and inserted[0]["document_name"] == "EXP-1"


def test_self_submitted_not_double_notified(monkeypatch):
    inserted = []
    _patch(monkeypatch, inserted, user_id="me@co")
    ac.notify_applicant_on_decision(Doc(workflow_state="财务已审", owner="me@co"))
    assert inserted == []  # owner == applicant -> declarative owner notification covers it


def test_non_terminal_state_no_notification(monkeypatch):
    inserted = []
    _patch(monkeypatch, inserted)
    ac.notify_applicant_on_decision(Doc(workflow_state="待财务复核", owner="hr@co"))
    assert inserted == []


def test_repeated_save_in_terminal_state_no_duplicate(monkeypatch):
    inserted = []
    _patch(monkeypatch, inserted)
    before = Doc(workflow_state="财务已审", owner="hr@co")  # already terminal before this save
    ac.notify_applicant_on_decision(Doc(workflow_state="财务已审", owner="hr@co", before=before))
    assert inserted == []


def test_leave_terminal_status(monkeypatch):
    inserted = []
    _patch(monkeypatch, inserted)
    ac.notify_applicant_on_decision(Doc(doctype="Leave Application", name="LV-1", status="Approved", owner="hr@co"))
    assert inserted and inserted[0]["document_type"] == "Leave Application"
