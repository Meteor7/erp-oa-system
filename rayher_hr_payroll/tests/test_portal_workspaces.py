import json, os
import rayher_hr_payroll

WS = os.path.join(os.path.dirname(rayher_hr_payroll.__file__), "fixtures", "workspace.json")


def _load():
    with open(WS, encoding="utf-8") as f:
        return {w["name"]: w for w in json.load(f)}


def test_two_portal_workspaces_present():
    ws = _load()
    assert "员工工作台" in ws and "审批中心" in ws


def test_employee_workspace_has_four_quick_actions():
    sc = _load()["员工工作台"]["shortcuts"]
    targets = {(s["link_to"], s.get("doc_view")) for s in sc}
    for dt in ("Leave Application", "Travel Request", "Expense Claim", "Compensatory Leave Request"):
        assert (dt, "New") in targets


def test_approval_center_links_pending_report():
    sc = _load()["审批中心"]["shortcuts"]
    assert any(s["link_to"] == "待我审批" and s["type"] == "Report" for s in sc)
