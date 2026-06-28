import json, os
import rayher_hr_payroll

WS = os.path.join(os.path.dirname(rayher_hr_payroll.__file__), "fixtures", "workspace.json")


def _load():
    with open(WS, encoding="utf-8") as f:
        return {w["name"]: w for w in json.load(f)}


def test_two_portal_workspaces_present():
    ws = _load()
    assert "员工工作台" in ws and "审批中心" in ws


def test_employee_workspace_quick_actions_only_fully_routed_types():
    # Only the request types with a complete approval route are offered as
    # create shortcuts: 请假 (Leave) and 报销 (Expense). Travel Request and
    # Compensatory Leave Request have no approval routing yet, so exposing a
    # create shortcut for them would be a dead-end -> intentionally omitted.
    sc = _load()["员工工作台"]["shortcuts"]
    targets = {(s["link_to"], s.get("doc_view")) for s in sc}
    assert ("Leave Application", "New") in targets
    assert ("Expense Claim", "New") in targets
    links = {s["link_to"] for s in sc}
    assert "Travel Request" not in links
    assert "Compensatory Leave Request" not in links


def test_approval_center_links_pending_report():
    sc = _load()["审批中心"]["shortcuts"]
    assert any(s["link_to"] == "Pending My Approval" and s["type"] == "Report" for s in sc)


def test_workspace_content_embeds_shortcut_blocks():
    # Frappe Desk renders a workspace from its `content` blocks; shortcuts only
    # appear if the content has matching {"type":"shortcut"} blocks.
    import json
    ws = _load()
    for name in ("员工工作台", "审批中心"):
        content = json.loads(ws[name]["content"])
        assert any(b.get("type") == "shortcut" for b in content), name


def test_content_shortcut_blocks_match_shortcut_rows():
    # Every {"type":"shortcut"} block in content must have a backing shortcut row,
    # else the workspace renders empty/broken tiles (and could re-expose a removed
    # flow). Guards against a half-applied shortcut change.
    import json as _json
    for ws in _load().values():
        block_names = {
            b["data"]["shortcut_name"]
            for b in _json.loads(ws["content"])
            if b.get("type") == "shortcut"
        }
        row_labels = {s["label"] for s in ws.get("shortcuts", [])}
        assert block_names <= row_labels, (ws["name"], block_names - row_labels)
