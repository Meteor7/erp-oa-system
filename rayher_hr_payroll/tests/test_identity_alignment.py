import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

PATH = Path(__file__).resolve().parents[1] / "maintenance/identity_alignment.py"

@pytest.fixture
def module(monkeypatch):
    monkeypatch.setitem(sys.modules, "frappe", SimpleNamespace())
    spec = importlib.util.spec_from_file_location("identity_alignment_test", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def person(name="Alice", ident="HR-EMP-90001", user="person003@staff.example.invalid"):
    return {"employee_name": name, "name": ident, "target_user": user,
            "status": "Active", "roles": ["Employee"]}

def test_prefers_bound_account_when_legacy_duplicate_exists(module):
    m = {"people": [person()]}
    e = [{"name": "HR-EMP-90001", "employee_name": "Alice", "user_id": "generated@local"}]
    u = [{"name": "legacy@local", "full_name": "Alice"},
         {"name": "generated@local", "full_name": "Alice"}]
    row = module.build_plan(m, e, u)[0]
    assert row["primary_user"] == "generated@local"
    assert row["aliases"] == ["generated@local", "legacy@local"]

def test_target_owned_by_another_person_is_rejected(module):
    with pytest.raises(ValueError, match="occupied"):
        module.build_plan({"people": [person()]}, [],
                          [{"name": "person003@staff.example.invalid", "full_name": "Bob"}])

def test_cross_person_account_binding_is_rejected(module):
    emps = [{"name": "A", "employee_name": "Alice", "user_id": "old"},
            {"name": "B", "employee_name": "Bob", "user_id": "old"}]
    with pytest.raises(ValueError, match="another employee"):
        module.build_plan({"people": [person()]}, emps, [{"name": "old", "full_name": "Alice"}])

def test_unreviewed_employee_id_occupant_is_rejected(module):
    with pytest.raises(ValueError, match="outside reviewed roster"):
        module.build_plan({"people": [person()]},
                          [{"name": "HR-EMP-90001", "employee_name": "Excluded"}], [])

def test_number_cycle_is_a_mapping_not_a_merge(module):
    people = [person("Alice", "A", "alice@x"), person("Bob", "B", "bob@x")]
    employees = [{"name": "B", "employee_name": "Alice"}, {"name": "A", "employee_name": "Bob"}]
    rows = module.build_plan({"people": people}, employees, [])
    assert module.mappings(rows)[0] == {"B": "A", "A": "B"}

def test_ambiguous_names_fail_closed(module):
    with pytest.raises(ValueError, match="Ambiguous person"):
        module.build_plan({"people": [person()]},
                          [{"name": "A", "employee_name": "Alice"},
                           {"name": "B", "employee_name": "Alice"}], [])

def test_only_exact_tokens_are_repaired(module):
    mapping = {"old@x": "new@x", "HR-EMP-1": "HR-EMP-8"}
    assert module.replace_value("mail old@x yesterday", mapping) == "mail old@x yesterday"
    assert module.replace_value('["old@x", {"employee":"HR-EMP-1"}]', mapping) == (
        '["new@x",{"employee":"HR-EMP-8"}]')
    assert module.replace_value("HR-EMP-10", mapping) == "HR-EMP-10"

def test_canonical_snapshot_accepts_identity_only_changes(module):
    old = {"employee":"A","owner":"old@x","hours":8,"snapshot":'{"user": "old@x"}'}
    new = {"employee":"B","owner":"new@x","hours":8,"snapshot":'{"user":"new@x"}'}
    assert module.normalize(old, {"A":"B","old@x":"new@x"}) == module.normalize(new, {})
    new["hours"] = 7
    assert module.normalize(old, {"A":"B","old@x":"new@x"}) != module.normalize(new, {})

def test_target_already_aligned_is_idempotent(module):
    p = person()
    rows = module.build_plan({"people":[p]},
        [{"name":p["name"],"employee_name":"Alice","user_id":p["target_user"]}],
        [{"name":p["target_user"],"full_name":"Alice"}])
    assert module.mappings(rows) == ({}, {})
    assert rows[0]["primary_user"] == p["target_user"]

def test_cycle_text_repair_does_not_map_framework_updated_cell_twice(module):
    calls = []
    def sql(query, args):
        calls.append((query, args))
        return [("B",)] if query.startswith("SELECT") else None
    module.frappe.db = SimpleNamespace(sql=sql)
    assert module.apply_text_references([("tabTimesheet", "TS1", "employee", "A", "B")],
                                       {"A": "B", "B": "A"}) == {}
    assert len(calls) == 1

def test_text_repair_rejects_concurrent_cell_changes(module):
    module.frappe.db = SimpleNamespace(sql=lambda query, args: [("third-party",)])
    with pytest.raises(ValueError, match="changed during migration"):
        module.apply_text_references([("tabX", "X1", "user", "old", "new")], {"old":"new"})


def test_backup_rejects_other_database_and_stale_file(module, tmp_path):
    import gzip, os, time
    backup = tmp_path / "backup.sql.gz"
    with gzip.open(backup, "wb") as stream:
        stream.write(b"-- MariaDB dump\n-- Host: db    Database: expected_db\n")
    assert module.verify_backup(backup, "expected_db") == str(backup.resolve())
    with pytest.raises(ValueError, match="different database"):
        module.verify_backup(backup, "production_db")
    os.utime(backup, (time.time() - 7200, time.time() - 7200))
    with pytest.raises(ValueError, match="stale"):
        module.verify_backup(backup, "expected_db")
