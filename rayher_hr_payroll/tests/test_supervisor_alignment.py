import pytest
from rayher_hr_payroll.maintenance.supervisor_alignment import build_plan


def rows():
    return [{"name": f"E{i:03}", "employee_name": f"Person {i}", "reports_to": None if i==0 else "E000", "status": "Active"} for i in range(85)]


def test_only_reports_to_changes_and_unlisted_employee_is_preserved():
    source=rows()
    current=[dict(r) for r in source]+[{"name":"EXTRA","employee_name":"Other","reports_to":None}]
    current[1]["reports_to"]=None
    plan=build_plan(source,current)
    assert plan["changes"]==[{"employee":"E001","person":"Person 1","before":None,"after":"E000"}]


def test_wrong_person_cannot_receive_a_supervisor_by_reused_id():
    source=rows();current=[dict(r) for r in source];current[1]["employee_name"]="Different"
    with pytest.raises(ValueError,match="identity"):build_plan(source,current)


def test_cycles_are_rejected():
    source=rows();source[0]["reports_to"]="E001"
    with pytest.raises(ValueError,match="cycle"):build_plan(source,source)


def test_inactive_supervisor_rejected():
    source=rows();source[0]["status"]="Left"
    with pytest.raises(ValueError,match="inactive"):build_plan(source,source)
