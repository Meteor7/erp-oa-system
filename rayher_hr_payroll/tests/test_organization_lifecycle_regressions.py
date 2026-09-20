from types import SimpleNamespace
import sys
import types


def test_daily_departure_uses_current_records_and_normal_save(monkeypatch):
    from rayher_hr_payroll import organization_master_data as mod
    saved = []
    class Employee:
        status = "Active"
        relieving_date = "2026-09-19"
        employee_name = "Current employee"
        def save(self, **kwargs): saved.append(self.status)
    employee = Employee()
    fake = types.ModuleType("frappe")
    def get_all(dt, **kwargs):
        assert kwargs["filters"] == {"status": "Active", "relieving_date": ["<=", "2026-09-20"]}
        return [SimpleNamespace(name="EMP-1")]
    fake.get_all = get_all
    def get_doc(dt, name, **kwargs):
        assert kwargs["for_update"] is True
        return employee
    fake.get_doc = get_doc
    monkeypatch.setitem(sys.modules, "frappe", fake)
    assert mod.sync_effective_leaver_statuses(today="2026-09-20") == [{"employee_name": "Current employee", "status": "Left"}]
    assert saved == ["Left"]


def test_daily_departure_rechecks_date_after_lock(monkeypatch):
    from rayher_hr_payroll import organization_master_data as mod
    fake = types.ModuleType("frappe")
    fake.get_all = lambda *a, **kw: [SimpleNamespace(name="EMP-1")]
    fake.get_doc = lambda *a, **kw: SimpleNamespace(status="Active", relieving_date="2026-10-01")
    monkeypatch.setitem(sys.modules, "frappe", fake)
    assert mod.sync_effective_leaver_statuses(today="2026-09-20") == []
