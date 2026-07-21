from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
import types
from copy import deepcopy
from datetime import datetime
from pathlib import Path


BATCH = "OA Invoice Import Batch"
RECORD = "OA Invoice Record"
VIEW_LOG = "OA Invoice View Log"
FILE = "File"
NOW = datetime(2026, 7, 20, 12, 0, 0)
WAITING = chr(0x5f85) + chr(0x786e) + chr(0x8ba4)
COMPLETE = chr(0x5df2) + chr(0x5b8c) + chr(0x6210)
CONFIRMED = chr(0x5df2) + chr(0x786e) + chr(0x8ba4)
PROCESSING = chr(0x5904) + chr(0x7406) + chr(0x4e2d)
QUEUED = chr(0x6392) + chr(0x961f) + chr(0x4e2d)
FAILED = chr(0x5931) + chr(0x8d25)
WARMUP = chr(0x9996) + chr(0x6b21) + chr(0x6a21) + chr(0x578b) + chr(0x8054) + chr(0x7f51) + chr(0x9884) + chr(0x70ed)
BACKUP = chr(0x5907) + chr(0x4efd)
SMOKE = chr(0x5192) + chr(0x70df)
ROLLBACK = chr(0x56de) + chr(0x6eda)


class FakeLock:
    def __init__(self):
        self.released = False

    def acquire(self, **_kwargs):
        return True

    def release(self):
        self.released = True


class FakeCache:
    def __init__(self):
        self.locks = []
        self.keys = []
        self.on_lock = None

    def lock(self, _key, **_kwargs):
        self.keys.append(_key)
        if self.on_lock:
            self.on_lock(_key)
        lock = FakeLock()
        self.locks.append(lock)
        return lock


class FakeDoc(dict):
    active_env = None

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as error:
            raise AttributeError(key) from error

    def get_full_path(self):
        return self.get("full_path")

    def save(self, **kwargs):
        env = type(self).active_env
        assert env is not None
        env.events.append(("save", self.get("doctype"), self.get("name"), kwargs))
        if env.fail_save_once_for == self.get("name"):
            env.fail_save_once_for = None
            raise RuntimeError("injected save failure")
        if self.get("doctype") == FILE:
            tail = str(self.get("file_url") or "").removeprefix("/private/files/")
            self["full_path"] = str(env.private_root / tail)
        return self


class FakeDB:
    def __init__(self, env):
        self.env = env
        self.commits = 0
        self.rollbacks = 0
        self.fail_once_for = None
        self.fail_commit_once = False
        self._committed = deepcopy(env.docs)
        self._committed_artifacts = deepcopy(env.lifecycle_artifacts)

    def _matches(self, row, filters):
        for key, expected in (filters or {}).items():
            actual = row.get(key)
            if isinstance(expected, (list, tuple)) and len(expected) == 2:
                operator, operand = expected
                if operator == "in" and actual not in operand:
                    return False
                if operator == "!=" and actual == operand:
                    return False
                if operator == "<" and not (actual < operand):
                    return False
                if operator == "like":
                    pattern = "^" + re.escape(str(operand)).replace("%", ".*") + "$"
                    if not re.match(pattern, str(actual or "")):
                        return False
            elif actual != expected:
                return False
        return True

    def get_values(self, doctype, filters=None, fieldname=None, as_dict=False, **_kwargs):
        rows = [row for row in self.env.docs.get(doctype, {}).values() if self._matches(row, filters)]
        fields = fieldname or ["name"]
        if as_dict:
            return [{field: row.get(field) for field in fields} for row in rows]
        return [tuple(row.get(field) for field in fields) for row in rows]

    def delete(self, *_args, **_kwargs):
        raise AssertionError("cleanup must use frappe.delete_doc lifecycle")

    def commit(self):
        self.commits += 1
        if self.fail_commit_once:
            self.fail_commit_once = False
            raise RuntimeError("injected commit failure")
        self._committed = deepcopy(self.env.docs)
        self._committed_artifacts = deepcopy(self.env.lifecycle_artifacts)

    def rollback(self, **_kwargs):
        self.rollbacks += 1
        self.env.docs = deepcopy(self._committed)
        self.env.lifecycle_artifacts = deepcopy(self._committed_artifacts)


class FakeFrappe:
    def __init__(self, tmp_path):
        self.docs = {BATCH: {}, RECORD: {}, VIEW_LOG: {}, FILE: {}}
        self.lifecycle_artifacts = set()
        self.db = FakeDB(self)
        self._cache = FakeCache()
        self.local = types.SimpleNamespace(site="test.local")
        self.private_root = tmp_path / "sites" / "test.local" / "private" / "files"
        self.private_root.mkdir(parents=True)
        self.logs = []
        self.events = []
        self.mutate_before_batch_lock = None
        self.fail_save_once_for = None
        self.fail_delete_doc_counts = {}

    def mark_committed(self):
        self.db._committed = deepcopy(self.docs)
        self.db._committed_artifacts = deepcopy(self.lifecycle_artifacts)

    def get_all(self, doctype, filters=None, fields=None, **_kwargs):
        rows = [row for row in self.docs.get(doctype, {}).values() if self.db._matches(row, filters)]
        return [{field: row.get(field) for field in (fields or ["name"])} for row in rows]

    def get_doc(self, doctype, name, **kwargs):
        if doctype == BATCH and kwargs.get("for_update") and self.mutate_before_batch_lock:
            mutation = self.mutate_before_batch_lock
            self.mutate_before_batch_lock = None
            mutation(self.docs[doctype][name])
        FakeDoc.active_env = self
        return self.docs[doctype][name]

    def delete_doc(self, doctype, name, **kwargs):
        self.events.append(("delete_doc", doctype, name, kwargs))
        remaining = self.fail_delete_doc_counts.get(name, 0)
        if remaining:
            self.fail_delete_doc_counts[name] = remaining - 1
            raise RuntimeError("injected delete_doc failure")
        row = self.docs[doctype][name]
        if doctype == RECORD and any(
            other_name != name and other.get("duplicate_of") == name
            for other_name, other in self.docs[RECORD].items()
        ):
            raise RuntimeError("simulated Frappe LinkExistsError")
        if doctype == FILE:
            path = Path(row.get_full_path())
            if path.exists():
                path.unlink()
        del self.docs[doctype][name]
        self.lifecycle_artifacts.discard((doctype, name))

    def cache(self):
        return self._cache

    def get_site_path(self, *parts):
        assert parts == ("private", "files")
        return str(self.private_root)

    def log_error(self, message, title=None):
        self.logs.append((message, title))


def _load_module(monkeypatch, env):
    fake = types.ModuleType("frappe")
    for name in ("db", "local", "get_all", "get_doc", "delete_doc", "cache", "get_site_path", "log_error"):
        setattr(fake, name, getattr(env, name))
    monkeypatch.setitem(sys.modules, "frappe", fake)
    sys.modules.pop("rayher_hr_payroll.maintenance.invoice_ocr_cleanup", None)
    return importlib.import_module("rayher_hr_payroll.maintenance.invoice_ocr_cleanup")


def _batch(env, name, *, status=WAITING, request='', creation=datetime(2026, 7, 1), expires=datetime(2026, 7, 8)):
    env.docs[BATCH][name] = FakeDoc(
        doctype=BATCH, name=name, request=request, creation=creation, expires_on=expires,
        batch_status=status, total_count=0, queued_count=0, processing_count=0,
        pending_confirmation_count=0, confirmed_count=0, duplicate_count=0,
        failed_count=0, excluded_count=0,
    )
    env.lifecycle_artifacts.add((BATCH, name))


def _record(env, batch, suffix='1', *, status=WAITING, confirmed_on=None, request='', line='', file_owner=True):
    name = f"REC-{batch}-{suffix}"
    filename = f"{name}.pdf"
    file_url = f"/private/files/{filename}"
    path = env.private_root / filename
    path.write_bytes(b"invoice")
    digest = hashlib.sha256(b"invoice").hexdigest()
    env.docs[RECORD][name] = FakeDoc(
        doctype=RECORD, name=name, batch=batch, invoice_file=file_url,
        file_sha256=digest, recognition_status=status, confirmed_on=confirmed_on,
        request=request, expense_line_key=line, duplicate_of="",
    )
    env.docs[FILE][f"FILE-{name}"] = FakeDoc(
        doctype=FILE, name=f"FILE-{name}", file_name=filename, file_url=file_url,
        is_private=1, owner="alice@example.com",
        attached_to_doctype=RECORD if file_owner else "Other",
        attached_to_name=name if file_owner else "OTHER",
        attached_to_field="invoice_file", full_path=str(path),
    )
    env.lifecycle_artifacts.update({(RECORD, name), (FILE, f"FILE-{name}")})
    batch_doc = env.docs[BATCH][batch]
    batch_doc["total_count"] += 1
    count_field = {
        WAITING: "pending_confirmation_count",
        CONFIRMED: "confirmed_count",
        QUEUED: "queued_count",
        FAILED: "failed_count",
    }.get(status)
    if count_field:
        batch_doc[count_field] += 1
    return name, path

def test_cleanup_deletes_only_expired_unconfirmed_unlinked_consistent_batches(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-EXPIRED")
    _name, removed_path = _record(env, "BATCH-EXPIRED")
    _batch(env, 'BATCH-CONFIRMED', status=COMPLETE)
    _record(env, 'BATCH-CONFIRMED', status=CONFIRMED, confirmed_on=datetime(2026, 7, 2))
    _batch(env, "BATCH-LINKED", request="REQ-1")
    _record(env, "BATCH-LINKED", request="REQ-1", line="line-1")
    _batch(env, 'BATCH-ACTIVE', status=PROCESSING)
    _record(env, 'BATCH-ACTIVE', status=QUEUED)
    _batch(env, 'BATCH-MISMATCH', status=FAILED)
    _record(env, 'BATCH-MISMATCH', status=WAITING)
    _batch(env, 'BATCH-COUNT-MISMATCH')
    _record(env, 'BATCH-COUNT-MISMATCH')
    env.docs[BATCH]['BATCH-COUNT-MISMATCH']['total_count'] = 99
    _batch(env, "BATCH-RECENT", creation=datetime(2026, 7, 19), expires=datetime(2026, 7, 27))
    _record(env, "BATCH-RECENT")
    env.mark_committed()

    cleanup = _load_module(monkeypatch, env)
    removed = cleanup.cleanup_orphan_invoice_batches(retention_days=7, now='2026-07-20 12:00:00')
    assert ':record:' in env._cache.keys[0]
    assert ':batch:' in env._cache.keys[1]

    assert removed == ["BATCH-EXPIRED"]
    assert "BATCH-EXPIRED" not in env.docs[BATCH]
    assert all(row.get("batch") != "BATCH-EXPIRED" for row in env.docs[RECORD].values())
    assert not removed_path.exists()
    assert any('inconsistent' in message for message, _title in env.logs)
    for preserved in ('BATCH-CONFIRMED', 'BATCH-LINKED', 'BATCH-ACTIVE', 'BATCH-MISMATCH', 'BATCH-COUNT-MISMATCH', 'BATCH-RECENT'):
        assert preserved in env.docs[BATCH]


def test_cleanup_skips_audited_and_not_strictly_owned_or_shared_files(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-AUDITED")
    record, _path = _record(env, "BATCH-AUDITED")
    env.docs[VIEW_LOG]["LOG-1"] = FakeDoc(name="LOG-1", invoice_record=record, invoice_file=env.docs[RECORD][record]["invoice_file"])
    _batch(env, "BATCH-EXTERNAL")
    _record(env, "BATCH-EXTERNAL", file_owner=False)
    _batch(env, "BATCH-SHARED")
    shared_record, _path = _record(env, "BATCH-SHARED")
    env.docs[RECORD]["REC-OTHER"] = FakeDoc(
        name="REC-OTHER", batch="OTHER", invoice_file=env.docs[RECORD][shared_record]["invoice_file"],
        recognition_status=WAITING, confirmed_on=None, request='', expense_line_key='',
    )
    env.mark_committed()

    cleanup = _load_module(monkeypatch, env)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == []
    assert set(env.docs[BATCH]) == {"BATCH-AUDITED", "BATCH-EXTERNAL", "BATCH-SHARED"}


def test_cleanup_rechecks_current_state_under_lock(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-RACE")
    _record(env, "BATCH-RACE")
    env.mark_committed()
    env.mutate_before_batch_lock = lambda batch: batch.update(request="REQ-LATE")

    cleanup = _load_module(monkeypatch, env)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == []
    assert "BATCH-RACE" in env.docs[BATCH]


def test_cleanup_rolls_back_failed_item_and_continues(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-FAIL")
    _record(env, "BATCH-FAIL")
    _batch(env, "BATCH-OK")
    _record(env, "BATCH-OK")
    env.mark_committed()
    env.fail_delete_doc_counts["REC-BATCH-FAIL-1"] = 1

    cleanup = _load_module(monkeypatch, env)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == ["BATCH-OK"]
    assert "BATCH-FAIL" in env.docs[BATCH]
    assert "BATCH-OK" not in env.docs[BATCH]
    assert env.db.rollbacks >= 1
    assert env.logs


def test_hooks_compose_and_runbook_contracts():
    root = Path(__file__).resolve().parents[2]
    hooks = (root / "rayher_hr_payroll" / "hooks.py").read_text(encoding="utf-8")
    compose = (root / "deploy" / "docker-compose.invoice-ocr.yml").read_text(encoding="utf-8")
    runbook = (root / "docs" / "invoice-ocr-runbook.md").read_text(encoding="utf-8")

    assert "scheduler_events" in hooks
    assert "rayher_hr_payroll.maintenance.invoice_ocr_cleanup.cleanup_orphan_invoice_batches" in hooks
    assert "rayher/invoice-ocr:0.1.0" in compose
    assert "target: runtime" in compose
    assert "rayher-ocr-internal" in compose and "internal: true" in compose
    assert "rayher-invoice-ocr-models" in compose
    assert '127.0.0.1:8080/ready' in compose
    assert 'start_period: 180s' in compose
    assert "ports:" not in compose
    for phrase in (WARMUP, 'invoice_ocr_url', BACKUP, 'migrate', 'build --app', SMOKE, ROLLBACK, '/health', '/ready', 'Get-FileHash'):
        assert phrase in runbook
    assert runbook.count("docker cp $PatchFile rayher-bench:/tmp/invoice-ocr.patch") >= 2
    assert runbook.count("Get-FileHash -Algorithm SHA256 $PatchFile") >= 2
    assert "bench rebuild" in runbook.lower()
    assert "git reset --hard" not in runbook
    assert "docker volume rm" not in runbook


def _external_reference(env, target, name="REC-EXTERNAL"):
    env.docs[RECORD][name] = FakeDoc(
        doctype=RECORD, name=name, batch="OTHER",
        invoice_file="/private/files/external.pdf", file_sha256="f" * 64,
        recognition_status=WAITING, confirmed_on=None, request="",
        expense_line_key="", duplicate_of=target,
    )


def test_cleanup_skips_external_duplicate_reference_and_allows_same_batch_reference(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-EXTERNAL-REF")
    target, external_path = _record(env, "BATCH-EXTERNAL-REF")
    _external_reference(env, target)
    _batch(env, "BATCH-SAME")
    first, _path = _record(env, "BATCH-SAME", suffix="1")
    second, _path = _record(env, "BATCH-SAME", suffix="2")
    env.docs[RECORD][second]["duplicate_of"] = first
    env.mark_committed()

    cleanup = _load_module(monkeypatch, env)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == ["BATCH-SAME"]
    assert "BATCH-EXTERNAL-REF" in env.docs[BATCH]
    assert external_path.exists()
    assert "BATCH-SAME" not in env.docs[BATCH]
    record_deletes = [
        event[2] for event in env.events
        if event[0] == "delete_doc" and event[1] == RECORD
        and event[2].startswith("REC-BATCH-SAME")
    ]
    assert record_deletes == [second, first]
    assert all(
        event[3].get("delete_permanently") is True
        and event[3].get("ignore_permissions") is True
        for event in env.events if event[0] == "delete_doc"
    )


def test_cleanup_uses_exact_file_hash_lock_and_rechecks_racing_inbound_reference(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-RACE-DUP")
    target, original_path = _record(env, "BATCH-RACE-DUP")
    digest = env.docs[RECORD][target]["file_sha256"]
    env.mark_committed()
    inserted = False

    def concurrent_registration(lock_key):
        nonlocal inserted
        if ":file-hash:" in lock_key and not inserted:
            inserted = True
            _external_reference(env, target, name="REC-CONCURRENT")
            env.mark_committed()

    env._cache.on_lock = concurrent_registration
    cleanup = _load_module(monkeypatch, env)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == []

    scope = hashlib.sha256(b"test.local").hexdigest()[:16]
    encoded = json.dumps((digest,), ensure_ascii=False, separators=(",", ":"), default=str)
    expected = f"invoice:{scope}:file-hash:{hashlib.sha256(encoded.encode()).hexdigest()}"
    assert expected in env._cache.keys
    assert original_path.exists()
    assert "BATCH-RACE-DUP" in env.docs[BATCH]
    assert "REC-CONCURRENT" in env.docs[RECORD]


def test_stage_failure_rolls_back_metadata_and_atomically_restores_all_files(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-RESTORE")
    _first, first_path = _record(env, "BATCH-RESTORE", suffix="1")
    _second, second_path = _record(env, "BATCH-RESTORE", suffix="2")
    env.mark_committed()

    cleanup = _load_module(monkeypatch, env)
    real_replace = cleanup.os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected physical stage failure")
        return real_replace(source, destination)

    monkeypatch.setattr(cleanup.os, "replace", fail_second_replace)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == []

    assert "BATCH-RESTORE" in env.docs[BATCH]
    assert first_path.read_bytes() == b"invoice"
    assert second_path.read_bytes() == b"invoice"
    assert not list(env.private_root.glob("__invoice_ocr_cleanup__*"))
    assert env.db.rollbacks >= 1


def test_database_failure_after_stage_rolls_back_and_restores_original_path(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-DB-FAIL")
    record, original_path = _record(env, "BATCH-DB-FAIL")
    env.fail_delete_doc_counts[record] = 1
    env.mark_committed()

    cleanup = _load_module(monkeypatch, env)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == []

    assert original_path.exists()
    assert "BATCH-DB-FAIL" in env.docs[BATCH]
    assert record in env.docs[RECORD]
    assert env.docs[FILE][f"FILE-{record}"]["file_url"].endswith(f"{record}.pdf")
    assert not list(env.private_root.glob("__invoice_ocr_cleanup__*"))


def test_committed_tombstone_survives_file_delete_failures_and_next_run_retries(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-TOMBSTONE")
    record, original_path = _record(env, "BATCH-TOMBSTONE")
    file_name = f"FILE-{record}"
    env.fail_delete_doc_counts[file_name] = 2
    env.mark_committed()

    cleanup = _load_module(monkeypatch, env)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == ["BATCH-TOMBSTONE"]

    assert "BATCH-TOMBSTONE" not in env.docs[BATCH]
    assert record not in env.docs[RECORD]
    assert file_name in env.docs[FILE]
    tombstone = env.docs[FILE][file_name]
    tombstone_path = Path(tombstone.get_full_path())
    assert not original_path.exists()
    assert tombstone_path.exists()
    assert tombstone["owner"] == "Administrator"
    assert not tombstone["attached_to_doctype"]
    assert cleanup._TOMBSTONE_PATTERN.fullmatch(tombstone["file_name"])

    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == []
    assert file_name not in env.docs[FILE]
    assert not tombstone_path.exists()


def test_process_exit_after_phase_one_is_recovered_by_next_scheduler_run(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-EXIT")
    record, _path = _record(env, "BATCH-EXIT")
    file_name = f"FILE-{record}"
    env.mark_committed()

    cleanup = _load_module(monkeypatch, env)
    real_purge = cleanup._purge_tombstone_file

    def exit_now(*_args, **_kwargs):
        raise SystemExit(9)

    monkeypatch.setattr(cleanup, "_purge_tombstone_file", exit_now)
    try:
        cleanup.cleanup_orphan_invoice_batches(now=NOW)
    except SystemExit as error:
        assert error.code == 9
    else:
        raise AssertionError("simulated process exit must escape")

    assert "BATCH-EXIT" not in env.docs[BATCH]
    assert file_name in env.docs[FILE]
    monkeypatch.setattr(cleanup, "_purge_tombstone_file", real_purge)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == []
    assert file_name not in env.docs[FILE]


def test_tombstone_scan_never_deletes_user_prefix_upload_or_out_of_root_path(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    user_filename = "__invoice_ocr_cleanup__" + "a" * 48 + ".pending"
    user_path = env.private_root / user_filename
    user_path.write_bytes(b"user upload")
    env.docs[FILE]["FILE-USER"] = FakeDoc(
        doctype=FILE, name="FILE-USER", file_name=user_filename,
        file_url=f"/private/files/{user_filename}", is_private=1,
        owner="alice@example.com", attached_to_doctype="", attached_to_name="",
        attached_to_field="", full_path=str(user_path),
    )
    outside = tmp_path / "outside.pending"
    outside.write_bytes(b"outside")
    system_filename = "__invoice_ocr_cleanup__" + "b" * 48 + ".pending"
    env.docs[FILE]["FILE-OUTSIDE"] = FakeDoc(
        doctype=FILE, name="FILE-OUTSIDE", file_name=system_filename,
        file_url=f"/private/files/{system_filename}", is_private=1,
        owner="Administrator", attached_to_doctype="", attached_to_name="",
        attached_to_field="", full_path=str(outside),
    )
    env.mark_committed()

    cleanup = _load_module(monkeypatch, env)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == []
    assert set(env.docs[FILE]) == {"FILE-USER", "FILE-OUTSIDE"}
    assert user_path.exists()
    assert outside.exists()


def test_commit_failure_restores_original_file_and_all_metadata(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-COMMIT-FAIL")
    record, original_path = _record(env, "BATCH-COMMIT-FAIL")
    env.mark_committed()
    env.db.fail_commit_once = True

    cleanup = _load_module(monkeypatch, env)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == []
    assert original_path.exists()
    assert "BATCH-COMMIT-FAIL" in env.docs[BATCH]
    assert record in env.docs[RECORD]
    assert f"FILE-{record}" in env.docs[FILE]
    assert not list(env.private_root.glob("__invoice_ocr_cleanup__*"))
