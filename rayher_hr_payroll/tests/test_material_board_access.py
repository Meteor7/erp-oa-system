def test_general_manager_can_open_the_material_board(monkeypatch):
    from rayher_hr_payroll.api import material_progress as board

    monkeypatch.setattr(board.frappe, "get_roles", lambda user=None: ["Employee"])
    held = {"pmc": {"pmc@x"}, "procurement_manager": {"buyer@x"}, "vice_manager": {"vp@x"}, "general_manager": {"gm@x"}}
    monkeypatch.setattr(board, "position_users", lambda *keys: {user for key in keys for user in held.get(key, set())})
    for user in ("pmc@x", "buyer@x", "vp@x", "gm@x"):
        assert board.can_access_board(user), user
    assert not board.can_access_board("clerk@x")


def test_nobody_is_masked_from_the_sensitive_hr_pages_now():
    from rayher_hr_payroll.api import _guards

    assert _guards.HR_SENSITIVE_HIDDEN_USERS == set()
