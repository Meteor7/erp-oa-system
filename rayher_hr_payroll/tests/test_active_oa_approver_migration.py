from rayher_hr_payroll.patches.v1_0 import migrate_active_oa_approvers as migration


def test_migration_maps_legacy_finance_vice_general_and_joint_steps():
    cases = [
        ("\u8d22\u52a1\u5ba1\u8ba1\uff1a\u6f14\u793a\u5458\u5de513", ["\u6f14\u793a\u5458\u5de513"], "\u5f85\u5ba1\u6279", "\u8d22\u52a1\u5ba1\u8ba1\uff1a\u6f14\u793a\u5458\u5de513", ["person067@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de510", ["\u6f14\u793a\u5458\u5de510"], "\u5f85\u6d41\u8f6c", "\u6f14\u793a\u5458\u5de510", ["person047@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de537", ["\u6f14\u793a\u5458\u5de537"], "\u5f85\u5ba1\u6279", "\u6f14\u793a\u5458\u5de521", ["person046@business.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de528", ["\u6f14\u793a\u5458\u5de528"], "\u5f85\u5ba1\u6279", "\u6f14\u793a\u5458\u5de529", ["person060@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de528", ["person058@staff.example.invalid"], "\u5f85\u6d41\u8f6c", "\u6f14\u793a\u5458\u5de529", ["person060@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de537\u3001\u6f14\u793a\u5458\u5de528", ["\u6f14\u793a\u5458\u5de537", "\u6f14\u793a\u5458\u5de528"], "\u5f85\u5ba1\u6279", "\u6f14\u793a\u5458\u5de521\u3001\u6f14\u793a\u5458\u5de529", ["person046@business.example.invalid", "person060@staff.example.invalid"]),
        ("\u6f14\u793a\u5458\u5de537\u3001\u6f14\u793a\u5458\u5de528", ["person046@business.example.invalid", "person058@staff.example.invalid"], "\u5f85\u5ba1\u6279", "\u6f14\u793a\u5458\u5de521\u3001\u6f14\u793a\u5458\u5de529", ["person046@business.example.invalid", "person060@staff.example.invalid"]),
    ]
    for label, approvers, status, expected_label, expected_approvers in cases:
        result = migration.build_step_migration(label, approvers, status)
        assert result == {"label": expected_label, "approvers": expected_approvers}


def test_migration_never_changes_completed_history_and_is_idempotent():
    assert migration.build_step_migration("\u6f14\u793a\u5458\u5de510", ["\u6f14\u793a\u5458\u5de510"], "\u5df2\u901a\u8fc7") is None
    assert migration.build_step_migration("\u6f14\u793a\u5458\u5de521", ["person046@business.example.invalid"], "\u5f85\u5ba1\u6279") is None
    assert migration.build_step_migration("\u6f14\u793a\u5458\u5de529", ["person060@staff.example.invalid"], "\u5f85\u5ba1\u6279") is None
