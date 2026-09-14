"""Regression checks for occupancy naming migration (no Frappe site needed)."""

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/v1_0/isolate_accommodation_occupancy_series.py"


@pytest.mark.parametrize(
    "maximum, existing, expected",
    [(131, None, 131), (131, 108, 131), (131, 250, 250), (0, None, 0)],
)
def test_migration_seeds_only_occupancy_series_and_never_rewinds(
    monkeypatch, maximum, existing, expected
):
    counters = {"": 108, "HR-EMP-": 79}
    if existing is not None:
        counters["OCC-"] = existing
    events = []

    def sql(query, values=None):
        if query.lstrip().startswith("SELECT"):
            assert "REGEXP '^OCC-[0-9]+$'" in query
            assert "CAST(SUBSTRING(name, 5) AS UNSIGNED)" in query
            return [(maximum,)]
        assert "ON DUPLICATE KEY UPDATE" in query
        assert "GREATEST" in query
        key, value = values
        counters[key] = max(counters.get(key, 0), value)
        events.append("seed")

    def reload_doc(*args):
        assert args == ("rayher_hr_payroll", "doctype", "accommodation_occupancy")
        assert counters["OCC-"] == expected
        events.append("reload")

    fake = SimpleNamespace(
        db=SimpleNamespace(table_exists=lambda name: True, sql=sql),
        reload_doc=reload_doc,
    )
    monkeypatch.setitem(sys.modules, "frappe", fake)
    spec = importlib.util.spec_from_file_location("occupancy_series_patch", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.execute()
    module.execute()
    assert counters == {"": 108, "HR-EMP-": 79, "OCC-": expected}
    assert events == ["seed", "reload", "seed", "reload"]


def test_new_install_reloads_schema_without_querying_missing_table(monkeypatch):
    calls = []
    fake = SimpleNamespace(
        db=SimpleNamespace(table_exists=lambda name: False),
        reload_doc=lambda *args: calls.append(args),
    )
    monkeypatch.setitem(sys.modules, "frappe", fake)
    spec = importlib.util.spec_from_file_location("occupancy_series_patch", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.execute()
    assert calls == [("rayher_hr_payroll", "doctype", "accommodation_occupancy")]


def test_doctype_uses_native_prefix_series_and_patch_is_registered():
    schema = json.loads(
        (ROOT / "rayher_hr_payroll/doctype/accommodation_occupancy/accommodation_occupancy.json")
        .read_text(encoding="utf-8")
    )
    assert schema["autoname"] == "OCC-.#####"
    assert "rayher_hr_payroll.patches.v1_0.isolate_accommodation_occupancy_series" in (
        ROOT / "patches.txt"
    ).read_text(encoding="utf-8").splitlines()
