from rayher_hr_payroll.patches.v1_0 import migrate_active_oa_approvers as migration


def test_migration_maps_legacy_finance_vice_general_and_joint_steps():
    cases = [
        ("\u8d22\u52a1\u5ba1\u8ba1\uff1a\u6f14\u793a\u5458\u5de513", ["\u6f14\u793a\u5458\u5de513"], "\u5f85\u5ba1\u6279", "\u8d22\u52a1\u5ba1\u8ba1\uff1a\u6f14\u793a\u5458\u5de513", ["person067@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de510", ["\u6f14\u793a\u5458\u5de510"], "\u5f85\u6d41\u8f6c", "\u6f14\u793a\u5458\u5de510", ["person047@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de537", ["\u6f14\u793a\u5458\u5de537"], "\u5f85\u5ba1\u6279", "\u6f14\u793a\u5458\u5de521", ["person046@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de528", ["\u6f14\u793a\u5458\u5de528"], "\u5f85\u5ba1\u6279", "\u6f14\u793a\u5458\u5de529", ["person060@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de528", ["person058@staff.example.invalid"], "\u5f85\u6d41\u8f6c", "\u6f14\u793a\u5458\u5de529", ["person060@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de537\u3001\u6f14\u793a\u5458\u5de528", ["\u6f14\u793a\u5458\u5de537", "\u6f14\u793a\u5458\u5de528"], "\u5f85\u5ba1\u6279", "\u6f14\u793a\u5458\u5de521\u3001\u6f14\u793a\u5458\u5de529", ["person046@staff.example.invalid", "person060@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de537\u3001\u6f14\u793a\u5458\u5de528", ["person046@staff.example.invalid", "person058@staff.example.invalid"], "\u5f85\u5ba1\u6279", "\u6f14\u793a\u5458\u5de521\u3001\u6f14\u793a\u5458\u5de529", ["person046@staff.example.invalid", "person060@staff.example.invalid"]),
    ]
    for label, approvers, status, expected_label, expected_approvers in cases:
        result = migration.build_step_migration(label, approvers, status)
        assert result == {"label": expected_label, "approvers": expected_approvers}


def test_migration_never_changes_completed_history_and_is_idempotent():
    assert migration.build_step_migration("\u6f14\u793a\u5458\u5de510", ["\u6f14\u793a\u5458\u5de510"], "\u5df2\u901a\u8fc7") is None
    assert migration.build_step_migration("\u6f14\u793a\u5458\u5de521", ["person046@staff.example.invalid"], "\u5f85\u5ba1\u6279") is None
    assert migration.build_step_migration("\u6f14\u793a\u5458\u5de529", ["person060@staff.example.invalid"], "\u5f85\u5ba1\u6279") is None


def test_migration_never_looks_up_mutable_display_names(monkeypatch):
    from types import SimpleNamespace
    def forbidden(*args, **kwargs):
        raise AssertionError("Display names must not resolve approval identities")
    monkeypatch.setattr(migration.frappe, "db", SimpleNamespace(get_value=forbidden))
    assert migration._resolve_user("review-user-alias") == "review-user-alias"
    assert migration._resolve_user("actual@example.com") == "actual@example.com"
    assert migration._resolve_user(migration.YE) == migration.YE_USER



def test_migration_keeps_a_step_whose_target_account_is_missing_or_disabled(monkeypatch):
    # 审查 #12：映射到已演示员工166（账号停用）的人，这一步就没人能审批。
    import json
    from types import SimpleNamespace

    step = SimpleNamespace(label="\u6f14\u793a\u5458\u5de510", approvers=json.dumps(["\u6f14\u793a\u5458\u5de510"]), status="\u5f85\u5ba1\u6279", step_index=1)
    doc = SimpleNamespace(steps=[step], current_step_index=1, save=lambda **kw: (_ for _ in ()).throw(AssertionError("must not save")))
    monkeypatch.setattr(migration.frappe, "get_all", lambda *a, **k: ["OA-1"])
    monkeypatch.setattr(migration.frappe, "get_doc", lambda *a, **k: doc)
    monkeypatch.setattr(migration.frappe, "db", SimpleNamespace(get_value=lambda doctype, name, field: 0))

    report = migration.execute()

    assert report["changed_steps"] == 0
    assert report["unresolved"][0]["unusable_accounts"] == ["person047@staff.example.invalid"]
    assert json.loads(step.approvers) == ["\u6f14\u793a\u5458\u5de510"]
