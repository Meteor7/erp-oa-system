import importlib
import sys
import types
from types import SimpleNamespace


class RuleError(Exception):
    pass


def _load_foreign_rd_expense(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text

    def throw(message):
        raise RuleError(str(message))

    frappe.throw = throw
    frappe.db = SimpleNamespace(exists=lambda *args, **kwargs: False)

    model = types.ModuleType("frappe.model")
    document = types.ModuleType("frappe.model.document")

    class Document:
        def __init__(self, **values):
            self.__dict__.update(values)

    document.Document = Document
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.model", model)
    monkeypatch.setitem(sys.modules, "frappe.model.document", document)
    module_name = (
        "rayher_hr_payroll.rayher_hr_payroll.doctype."
        "foreign_rd_expense.foreign_rd_expense"
    )
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_new_foreign_rd_expense_uses_one_deterministic_name_per_period(monkeypatch):
    mod = _load_foreign_rd_expense(monkeypatch)
    doc = mod.ForeignRDExpense(year=2026, month=7, period="2026/07")

    doc.autoname()

    assert doc.period == "202607"
    assert doc.name == "FRD-2026-07"


def test_locked_foreign_period_cannot_be_moved_to_open_period(monkeypatch):
    import pytest
    mod = _load_foreign_rd_expense(monkeypatch)
    doc = mod.ForeignRDExpense(period="202609")
    doc.get_doc_before_save = lambda: SimpleNamespace(period="202608")
    mod.frappe.db.exists = lambda dt, filters: filters["period"] == "202608"
    with pytest.raises(RuleError, match="202608"):
        doc._check_period_lock()


def test_open_foreign_period_cannot_be_moved_to_locked_period(monkeypatch):
    import pytest
    mod = _load_foreign_rd_expense(monkeypatch)
    doc = mod.ForeignRDExpense(period="202608")
    doc.get_doc_before_save = lambda: SimpleNamespace(period="202607")
    mod.frappe.db.exists = lambda dt, filters: filters["period"] == "202608"
    with pytest.raises(RuleError, match="202608"):
        doc._check_period_lock()


def test_monthly_row_keeps_the_hours_and_derives_the_days(monkeypatch):
    # 2026-10-12：工时（小时）是源头，天数 = 工时 / 8，和研发工时填报一致。
    mod = _load_foreign_rd_expense(monkeypatch)
    line = SimpleNamespace(work_date="2026-07-01", project_code="P1", project_name="Project", activity_type="", occurrence_days=1, hours=18.8, allocated_amount=0)
    doc = mod.ForeignRDExpense(year=2026, month=7, total_amount=0, lines=[line])
    doc._check_amounts()
    assert line.hours == 18.8
    assert line.occurrence_days == 2.35


def test_monthly_row_with_only_days_is_converted_at_eight_hours_a_day(monkeypatch):
    # 旧模板、老数据只有天数：按 1 天 = 8 小时换算成工时。
    mod = _load_foreign_rd_expense(monkeypatch)
    line = SimpleNamespace(work_date="2026-07-01", project_code="P1", project_name="Project", activity_type="", occurrence_days=2.5, hours=0, allocated_amount=0)
    doc = mod.ForeignRDExpense(year=2026, month=7, total_amount=0, lines=[line])
    doc._check_amounts()
    assert line.hours == 20
    assert line.occurrence_days == 2.5


def test_legacy_daily_row_still_requires_activity_and_daily_limit(monkeypatch):
    import pytest
    mod = _load_foreign_rd_expense(monkeypatch)
    line = SimpleNamespace(work_date="2026-07-01", project_code="P1", project_name="Project", activity_type="", occurrence_days=0, hours=9, allocated_amount=0)
    doc = mod.ForeignRDExpense(year=2026, month=7, total_amount=0, lines=[line])
    with pytest.raises(RuleError, match="活动类型"): doc._check_amounts()
    line.activity_type = "R&D"
    with pytest.raises(RuleError, match="8 小时"): doc._check_amounts()
    line.hours = 8
    doc._check_amounts()
    line.work_date = "2026-08-01"
    with pytest.raises(RuleError, match="期间"): doc._check_amounts()


def test_monthly_row_rejects_nonfinite_or_negative_days(monkeypatch):
    import pytest
    mod = _load_foreign_rd_expense(monkeypatch)
    line = SimpleNamespace(work_date="2026-07-01", project_code="P1", project_name="Project", activity_type="", occurrence_days=0, hours=8, allocated_amount=0)
    doc = mod.ForeignRDExpense(year=2026, month=7, total_amount=0, lines=[line])
    for days in (-1, float("nan"), float("inf")):
        line.occurrence_days = days
        with pytest.raises(RuleError): doc._check_amounts()
