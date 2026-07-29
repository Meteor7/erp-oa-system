import sys
import types
from pathlib import Path

import pytest

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


def _install_delivery_frappe(monkeypatch, private_root, events, *, fail_update=False, fail_commit=False):
    private_root.mkdir(parents=True, exist_ok=True)
    frappe = types.ModuleType("frappe")
    frappe.get_all = lambda *args, **kwargs: [
        {"name": "person036@legacy.example.invalid", "full_name": "New User"},
    ]
    frappe.get_site_path = lambda name: str(private_root)

    def commit():
        events.append("commit")
        if fail_commit:
            raise RuntimeError("commit failed")

    def rollback():
        events.append("rollback")

    frappe.db = types.SimpleNamespace(commit=commit, rollback=rollback)
    password = types.ModuleType("frappe.utils.password")

    def update_password(user_id, temporary_password, logout_all_sessions=True):
        events.append(("update", user_id, temporary_password, logout_all_sessions))
        if fail_update:
            raise RuntimeError("update failed")

    password.update_password = update_password
    utils = types.ModuleType("frappe.utils")
    utils.password = password
    frappe.utils = utils
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    monkeypatch.setitem(sys.modules, "frappe.utils.password", password)


def _delivery_paths(tmp_path):
    private_root = tmp_path / "private"
    known = tmp_path / "known.txt"
    known.write_text("", encoding="utf-8")
    output = private_root / "files" / "credentials.csv"
    return private_root, known, output, output.with_suffix(".csv.pending")


def test_delivery_rejects_directory_output_before_password_updates(tmp_path, monkeypatch):
    private_root, known, output, _pending = _delivery_paths(tmp_path)
    output.mkdir(parents=True)
    events = []
    _install_delivery_frappe(monkeypatch, private_root, events)

    with pytest.raises(IsADirectoryError):
        delivery.deliver_enabled_system_user_passwords(known, output, dry_run=False)

    assert events == []


def test_delivery_refuses_to_overwrite_stale_pending_journal(tmp_path, monkeypatch):
    private_root, known, output, pending = _delivery_paths(tmp_path)
    pending.parent.mkdir(parents=True)
    pending.write_text("recoverable credentials", encoding="utf-8")
    events = []
    _install_delivery_frappe(monkeypatch, private_root, events)

    with pytest.raises(FileExistsError):
        delivery.deliver_enabled_system_user_passwords(known, output, dry_run=False)

    assert pending.read_text(encoding="utf-8") == "recoverable credentials"
    assert events == []


def test_delivery_keeps_pending_and_rolls_back_when_password_update_fails(tmp_path, monkeypatch):
    private_root, known, output, pending = _delivery_paths(tmp_path)
    events = []
    _install_delivery_frappe(monkeypatch, private_root, events, fail_update=True)

    with pytest.raises(RuntimeError, match="update failed"):
        delivery.deliver_enabled_system_user_passwords(known, output, dry_run=False)

    assert pending.exists()
    assert not output.exists()
    assert events[-1] == "rollback"
    assert "commit" not in events


def test_delivery_keeps_pending_and_rolls_back_when_commit_fails(tmp_path, monkeypatch):
    private_root, known, output, pending = _delivery_paths(tmp_path)
    events = []
    _install_delivery_frappe(monkeypatch, private_root, events, fail_commit=True)

    with pytest.raises(RuntimeError, match="commit failed"):
        delivery.deliver_enabled_system_user_passwords(known, output, dry_run=False)

    assert pending.exists()
    assert not output.exists()
    assert events[-2:] == ["commit", "rollback"]


def test_delivery_keeps_recovery_journal_without_rollback_when_publish_fails(tmp_path, monkeypatch):
    private_root, known, output, pending = _delivery_paths(tmp_path)
    events = []
    _install_delivery_frappe(monkeypatch, private_root, events)
    monkeypatch.setattr(delivery.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("publish failed")))

    with pytest.raises(OSError, match="publish failed"):
        delivery.deliver_enabled_system_user_passwords(known, output, dry_run=False)

    assert pending.exists()
    assert not output.exists()
    assert "commit" in events
    assert "rollback" not in events


def test_delivery_atomically_publishes_private_credentials_after_commit(tmp_path, monkeypatch):
    private_root, known, output, pending = _delivery_paths(tmp_path)
    events = []
    _install_delivery_frappe(monkeypatch, private_root, events)
    chmod_calls = []
    real_chmod = delivery.os.chmod

    def record_chmod(path, mode):
        chmod_calls.append((Path(path), mode))
        real_chmod(path, mode)

    monkeypatch.setattr(delivery.os, "chmod", record_chmod)
    result = delivery.deliver_enabled_system_user_passwords(known, output, dry_run=False)

    assert result["reset_count"] == 1
    assert output.exists()
    assert not pending.exists()
    assert events[-1] == "commit"
    assert "rollback" not in events
    assert chmod_calls == [(pending, 0o600)]
