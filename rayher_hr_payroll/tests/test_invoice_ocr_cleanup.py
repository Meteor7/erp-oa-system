from __future__ import annotations

import importlib
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

    def lock(self, _key, **_kwargs):
        self.keys.append(_key)
        lock = FakeLock()
        self.locks.append(lock)
        return lock


class FakeDoc(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as error:
            raise AttributeError(key) from error

    def get_full_path(self):
        return self.get("full_path")


class FakeDB:
    def __init__(self, env):
        self.env = env
        self.commits = 0
        self.rollbacks = 0
        self.fail_once_for = None
        self._committed = deepcopy(env.docs)

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
            elif actual != expected:
                return False
        return True

    def get_values(self, doctype, filters=None, fieldname=None, as_dict=False, **_kwargs):
        rows = [row for row in self.env.docs.get(doctype, {}).values() if self._matches(row, filters)]
        fields = fieldname or ["name"]
        if as_dict:
            return [{field: row.get(field) for field in fields} for row in rows]
        return [tuple(row.get(field) for field in fields) for row in rows]

    def delete(self, doctype, filters):
        if self.fail_once_for == filters.get("name"):
            self.fail_once_for = None
            raise RuntimeError("injected delete failure")
        names = [name for name, row in self.env.docs.get(doctype, {}).items() if self._matches(row, filters)]
        for name in names:
            del self.env.docs[doctype][name]

    def commit(self):
        self.commits += 1
        self._committed = deepcopy(self.env.docs)

    def rollback(self, **_kwargs):
        self.rollbacks += 1
        self.env.docs = deepcopy(self._committed)


class FakeFrappe:
    def __init__(self, tmp_path):
        self.docs = {BATCH: {}, RECORD: {}, VIEW_LOG: {}, FILE: {}}
        self.db = FakeDB(self)
        self._cache = FakeCache()
        self.local = types.SimpleNamespace(site="test.local")
        self.private_root = tmp_path / "sites" / "test.local" / "private" / "files"
        self.private_root.mkdir(parents=True)
        self.logs = []
        self.mutate_before_batch_lock = None

    def get_all(self, doctype, filters=None, fields=None, **_kwargs):
        rows = [row for row in self.docs.get(doctype, {}).values() if self.db._matches(row, filters)]
        return [{field: row.get(field) for field in (fields or ["name"])} for row in rows]

    def get_doc(self, doctype, name, **kwargs):
        if doctype == BATCH and kwargs.get("for_update") and self.mutate_before_batch_lock:
            mutation = self.mutate_before_batch_lock
            self.mutate_before_batch_lock = None
            mutation(self.docs[doctype][name])
        return self.docs[doctype][name]

    def cache(self):
        return self._cache

    def get_site_path(self, *parts):
        assert parts == ("private", "files")
        return str(self.private_root)

    def log_error(self, message, title=None):
        self.logs.append((message, title))


def _load_module(monkeypatch, env):
    fake = types.ModuleType("frappe")
    for name in ("db", "local", "get_all", "get_doc", "cache", "get_site_path", "log_error"):
        setattr(fake, name, getattr(env, name))
    monkeypatch.setitem(sys.modules, "frappe", fake)
    sys.modules.pop("rayher_hr_payroll.maintenance.invoice_ocr_cleanup", None)
    return importlib.import_module("rayher_hr_payroll.maintenance.invoice_ocr_cleanup")


def _batch(env, name, *, status=WAITING, request='', creation=datetime(2026, 7, 1), expires=datetime(2026, 7, 8)):
    env.docs[BATCH][name] = FakeDoc(
        name=name, request=request, creation=creation, expires_on=expires,
        batch_status=status, total_count=0, queued_count=0, processing_count=0,
        pending_confirmation_count=0, confirmed_count=0, duplicate_count=0,
        failed_count=0, excluded_count=0,
    )


def _record(env, batch, suffix='1', *, status=WAITING, confirmed_on=None, request='', line='', file_owner=True):
    name = f"REC-{batch}-{suffix}"
    filename = f"{name}.pdf"
    file_url = f"/private/files/{filename}"
    path = env.private_root / filename
    path.write_bytes(b"invoice")
    env.docs[RECORD][name] = FakeDoc(
        name=name, batch=batch, invoice_file=file_url, recognition_status=status,
        confirmed_on=confirmed_on, request=request, expense_line_key=line,
    )
    env.docs[FILE][f"FILE-{name}"] = FakeDoc(
        name=f"FILE-{name}", file_url=file_url, is_private=1,
        attached_to_doctype=RECORD if file_owner else "Other",
        attached_to_name=name if file_owner else "OTHER",
        attached_to_field="invoice_file", full_path=str(path),
    )
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
    env.db._committed = deepcopy(env.docs)

    cleanup = _load_module(monkeypatch, env)
    removed = cleanup.cleanup_orphan_invoice_batches(retention_days=7, now='2026-07-20 12:00:00')
    assert ':record:' in env._cache.keys[0]
    assert ':batch:' in env._cache.keys[1]

    assert removed == ["BATCH-EXPIRED"]
    assert "BATCH-EXPIRED" not in env.docs[BATCH]
    assert all(row.get("batch") != "BATCH-EXPIRED" for row in env.docs[RECORD].values())
    assert not removed_path.exists()
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
    env.db._committed = deepcopy(env.docs)

    cleanup = _load_module(monkeypatch, env)
    assert cleanup.cleanup_orphan_invoice_batches(now=NOW) == []
    assert set(env.docs[BATCH]) == {"BATCH-AUDITED", "BATCH-EXTERNAL", "BATCH-SHARED"}


def test_cleanup_rechecks_current_state_under_lock(monkeypatch, tmp_path):
    env = FakeFrappe(tmp_path)
    _batch(env, "BATCH-RACE")
    _record(env, "BATCH-RACE")
    env.db._committed = deepcopy(env.docs)
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
    env.db._committed = deepcopy(env.docs)
    env.db.fail_once_for = "FILE-REC-BATCH-FAIL-1"

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
    assert '127.0.0.1:8080/health' in compose
    assert "ports:" not in compose
    for phrase in (WARMUP, 'invoice_ocr_url', BACKUP, 'migrate', 'build --app', SMOKE, ROLLBACK):
        assert phrase in runbook
    assert "git reset --hard" not in runbook
    assert "docker volume rm" not in runbook
