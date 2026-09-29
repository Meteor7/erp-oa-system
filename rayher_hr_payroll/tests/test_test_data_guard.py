import importlib
import sys
import types

import pytest


def _guard(monkeypatch, conf):
    fake = types.ModuleType("frappe")
    fake.conf = conf
    fake.ValidationError = type("ValidationError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "frappe", fake)
    sys.modules.pop("rayher_hr_payroll.maintenance.test_data_guard", None)
    return importlib.import_module("rayher_hr_payroll.maintenance.test_data_guard"), fake


def test_test_data_scripts_only_write_on_sites_that_allow_it(monkeypatch):
    # 模块 7（决定 D9）：误在正式站点执行会批量建单、删单、改密码。
    guard, fake = _guard(monkeypatch, {})
    with pytest.raises(fake.ValidationError, match="allow_test_data_seed"):
        guard.require_test_data_site()
    guard, _fake = _guard(monkeypatch, {"allow_test_data_seed": 1})
    guard.require_test_data_site()


def test_like_prefix_treats_wildcards_literally(monkeypatch):
    guard, _fake = _guard(monkeypatch, {})
    assert guard.like_prefix("[OA测试:a_1]") == "[OA测试:a\\_1]%"
    assert guard.like_prefix("50%") == "50\\%%"
    assert guard.like_prefix("a\\b") == "a\\\\b%"
