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



def test_purchaser_handover_moves_open_procurement_requests(monkeypatch):
    # 审查 X3-9（决定 D6）：采购经理交接后，没办完的采购单改由新任经办，并留备注。
    import sys
    import types as _types
    from rayher_hr_payroll import position_handover as ph

    calls = {"filters": None, "set": [], "comments": []}
    fake = _types.ModuleType("frappe")

    def get_all(doctype, filters=None, **kwargs):
        calls["filters"] = filters
        return ["OA-1", "OA-2"]

    fake.get_all = get_all
    fake.db = _types.SimpleNamespace(set_value=lambda *a, **k: calls["set"].append(a))
    fake.get_doc = lambda values: _types.SimpleNamespace(insert=lambda **k: calls["comments"].append(values["reference_name"]))
    monkeypatch.setitem(sys.modules, "frappe", fake)

    assert ph.transfer_purchaser_requests("old@x", "new@x") == ["OA-1", "OA-2"]
    assert calls["filters"]["purchaser_user"] == "old@x"
    assert "已关闭" in calls["filters"]["business_status"][1] and "已付款" in calls["filters"]["workflow_status"][1]
    assert calls["set"] == [("OA Approval Request", "OA-1", "purchaser_user", "new@x"), ("OA Approval Request", "OA-2", "purchaser_user", "new@x")]
    assert calls["comments"] == ["OA-1", "OA-2"]
    assert ph.transfer_purchaser_requests("same@x", "same@x") == []
