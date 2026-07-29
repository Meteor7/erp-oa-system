import importlib
import json
import sys
import types

import pytest


@pytest.fixture
def migration_module(monkeypatch):
    frappe = types.ModuleType("frappe")
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.maintenance.account_domain_migration", None)
    return importlib.import_module("rayher_hr_payroll.maintenance.account_domain_migration")


def test_build_domain_mappings_targets_only_approved_legacy_domains(migration_module):
    rows = migration_module.build_domain_mappings(
        [
            "person067@legacy.example.invalid",
            "admin@legacy-business.example.invalid",
            "person046@business.example.invalid",
            "Administrator",
        ]
    )

    assert rows == [
        {
            "old_user": "admin@legacy-business.example.invalid",
            "new_user": "admin@staff.example.invalid",
            "management": True,
        },
        {
            "old_user": "person067@legacy.example.invalid",
            "new_user": "person067@staff.example.invalid",
            "management": False,
        },
    ]


def test_build_domain_mappings_normalizes_case_and_deduplicates(migration_module):
    rows = migration_module.build_domain_mappings(
        ["history.29d3deeea7@legacy.example.invalid", "person067@legacy.example.invalid"]
    )

    assert rows == [
        {
            "old_user": "person067@legacy.example.invalid",
            "new_user": "person067@staff.example.invalid",
            "management": False,
        }
    ]


def test_exact_reference_replacement_handles_json_without_partial_matches(migration_module):
    mapping = {"person067@legacy.example.invalid": "person067@staff.example.invalid"}

    assert json.loads(
        migration_module.replace_exact_user_ids('["person067@legacy.example.invalid"]', mapping)
    ) == ["person067@staff.example.invalid"]
    assert (
        migration_module.replace_exact_user_ids("person045@legacy.example.invalid", mapping)
        == "person045@legacy.example.invalid"
    )


def test_exact_reference_replacement_updates_scalar_user_id(migration_module):
    mapping = {"admin@legacy-business.example.invalid": "admin@staff.example.invalid"}

    assert (
        migration_module.replace_exact_user_ids("admin@legacy-business.example.invalid", mapping)
        == "admin@staff.example.invalid"
    )