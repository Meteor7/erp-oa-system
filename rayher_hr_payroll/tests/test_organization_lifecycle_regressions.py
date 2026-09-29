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
        assert kwargs["filters"] == {"status": "Active", "relieving_date": ["<", "2026-09-20"]}
        return [SimpleNamespace(name="EMP-1")]
    fake.get_all = get_all
    def get_doc(dt, name, **kwargs):
        assert kwargs["for_update"] is True
        return employee
    fake.get_doc = get_doc
    fake.db = SimpleNamespace(savepoint=lambda name: None, rollback=lambda save_point=None: None)
    monkeypatch.setitem(sys.modules, "frappe", fake)
    assert mod.sync_effective_leaver_statuses(today="2026-09-20") == [{"employee_name": "Current employee", "status": "Left"}]
    assert saved == ["Left"]


def test_daily_departure_rechecks_date_after_lock(monkeypatch):
    from rayher_hr_payroll import organization_master_data as mod
    fake = types.ModuleType("frappe")
    fake.get_all = lambda *a, **kw: [SimpleNamespace(name="EMP-1")]
    fake.get_doc = lambda *a, **kw: SimpleNamespace(status="Active", relieving_date="2026-10-01")
    fake.db = SimpleNamespace(savepoint=lambda name: None, rollback=lambda save_point=None: None)
    monkeypatch.setitem(sys.modules, "frappe", fake)
    assert mod.sync_effective_leaver_statuses(today="2026-09-20") == []



def test_one_failing_leaver_does_not_stop_the_others_and_rehires_stay_active(monkeypatch):
    # 模块 7：主管名下还有在职下属时 ERPNext 不让标离职；原来整批回滚，每天重复失败。
    from rayher_hr_payroll import organization_master_data as mod
    saved, logged, rolled = [], [], []

    class Employee:
        def __init__(self, name, relieving, joining="2020-01-01", fail=False):
            self.name, self.employee_name, self.status = name, name, "Active"
            self.relieving_date, self.date_of_joining, self.fail = relieving, joining, fail

        def save(self, **kwargs):
            if self.fail:
                raise ValueError("Cannot Relieve Employee")
            saved.append(self.name)

    people = {
        "BOSS": Employee("BOSS", "2026-09-10", fail=True),
        "E2": Employee("E2", "2026-09-10"),
        "REHIRED": Employee("REHIRED", "2025-12-31", joining="2026-03-01"),
    }
    fake = types.ModuleType("frappe")
    fake.get_all = lambda *a, **kw: [SimpleNamespace(name=n) for n in people]
    fake.get_doc = lambda dt, name, **kw: people[name]
    fake.db = SimpleNamespace(savepoint=lambda name: None, rollback=lambda save_point=None: rolled.append(save_point))
    fake.log_error = lambda title=None, message=None: logged.append(message)
    monkeypatch.setitem(sys.modules, "frappe", fake)

    result = mod.sync_effective_leaver_statuses(today="2026-09-20")

    assert [row["employee_name"] for row in result] == ["E2"]
    assert saved == ["E2"] and people["REHIRED"].status == "Active"
    assert rolled == ["leaver_sync"] and "BOSS" in logged[0]
