from types import SimpleNamespace

import pytest

from rayher_hr_payroll.period_controls import normalize_period_fields


class RuleError(Exception):
    pass


def throw(message):
    raise RuleError(str(message))


def test_normalize_period_fields_derives_yyyymm_from_year_and_month():
    doc = SimpleNamespace(year=2026, month=1, period="2026-01")

    normalize_period_fields(doc, throw=throw)

    assert doc.period == "202601"


def test_normalize_period_fields_rejects_invalid_month():
    doc = SimpleNamespace(year=2026, month=13, period="202613")

    with pytest.raises(RuleError, match="Month must be between 1 and 12"):
        normalize_period_fields(doc, throw=throw)
