from rayher_hr_payroll.maintenance import user_password_delivery as delivery


def test_build_reset_plan_preserves_known_credentials_and_resets_every_other_enabled_user():
    users = [
        {"name": "Administrator", "full_name": "Administrator"},
        {"name": "person026@legacy.example.invalid", "full_name": "Known User"},
        {"name": "person036@legacy.example.invalid", "full_name": "New User"},
    ]

    plan = delivery.build_reset_plan(
        users,
        known_credentials={"person026@legacy.example.invalid": "ExistingSecret"},
        password_factory=iter(["AdminSecret", "NewSecret"]).__next__,
    )

    assert plan == [
        {
            "user_id": "Administrator",
            "full_name": "Administrator",
            "temporary_password": "AdminSecret",
            "reset_required": True,
        },
        {
            "user_id": "person026@legacy.example.invalid",
            "full_name": "Known User",
            "temporary_password": "ExistingSecret",
            "reset_required": False,
        },
        {
            "user_id": "person036@legacy.example.invalid",
            "full_name": "New User",
            "temporary_password": "NewSecret",
            "reset_required": True,
        },
    ]


def test_parse_known_credentials_rejects_duplicate_user(tmp_path):
    credentials = tmp_path / "credentials.txt"
    credentials.write_text(
        "person026@legacy.example.invalid SecretOne\person037@legacy.example.invalid SecretTwo\n",
        encoding="utf-8",
    )

    try:
        delivery.read_known_credentials(credentials)
    except ValueError as error:
        assert "duplicate" in str(error).lower()
    else:
        raise AssertionError("duplicate credential user must be rejected")
