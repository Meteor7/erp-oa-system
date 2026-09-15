import pytest
from rayher_hr_payroll.position_handover import reporting_plan, role_delta

def test_shared_role_and_temporary_exception_survive():
    assert role_delta(["HR User","Department Manager","All Project Access"],
                      ["HR User","Department Manager"], ["Department Manager"],
                      ["All Project Access"]) == ([], ["HR User"])

def test_new_holder_receives_complete_profile():
    assert role_delta(["Employee"], [], ["HR User","Department Manager"], []) == (
        ["Department Manager","HR User"], [])

def test_active_subordinates_follow_position_not_history():
    rows=[dict(name="boss",status="Active",reports_to=None),
          dict(name="old",status="Left",reports_to="boss"),
          dict(name="new",status="Active",reports_to="old"),
          dict(name="staff",status="Active",reports_to="old"),
          dict(name="former",status="Left",reports_to="old")]
    assert reporting_plan(rows,"old","new","boss")=={"new":"boss","staff":"new"}
    assert rows[3]["reports_to"]=="old"

def test_cycle_rejected():
    rows=[dict(name="a",status="Active",reports_to=None),dict(name="b",status="Active",reports_to="a")]
    with pytest.raises(ValueError,match="cycle"):
        reporting_plan(rows,None,"a","b")

def test_inactive_holder_rejected():
    with pytest.raises(ValueError,match="active"):
        reporting_plan([dict(name="a",status="Left",reports_to=None)],None,"a",None)

def test_idempotent():
    rows=[dict(name="a",status="Active",reports_to=None),dict(name="b",status="Active",reports_to="a")]
    assert reporting_plan(rows,"b","b","a")=={}
