"""个税累计预扣法（决定 2026-10-14）：和人事表格里能对上的两行、税率表的分档、6 万规则、年终奖单独计税、次月发。"""
from decimal import Decimal

import pytest

from rayher_hr_payroll import income_tax as tax


def test_first_month_matches_the_hr_sheet_rows():
    # 表格第 6 行：(10000 − 1020 − 700 − 5000) × 3% = 98.4
    first = tax.withholding({"income": 10000, "special": 1720})
    assert first["tax"] == Decimal("98.40") and first["cum_basic"] == Decimal("5000.00") and first["rate"] == 3
    # 表格第 3 行：再扣 3300 的专项附加：(10000 − 544.54 − 350 − 5000 − 3300) × 3% = 24.16
    third = tax.withholding({"income": 10000, "special": Decimal("894.54"), "special_additional": 3300})
    assert third["tax"] == Decimal("24.16")


def test_cumulative_months_subtract_tax_already_withheld():
    # 第二个月：累计 20000 − 10000 − 3440 = 6560 × 3% = 196.8，已扣 98.4，本月 98.4
    second = tax.withholding({"income": 10000, "special": 1720},
                             {"months": 1, "income": 10000, "special": 1720, "tax": Decimal("98.40")})
    assert second["months"] == 2 and second["cum_taxable"] == Decimal("6560.00")
    assert second["cum_tax"] == Decimal("196.80") and second["tax"] == Decimal("98.40")


def test_crossing_into_the_ten_percent_bracket_uses_the_quick_deduction():
    # 累计 40000 → 10% − 2520 = 1480，之前已扣 900
    result = tax.withholding({"income": 9000}, {"months": 3, "income": 51000, "tax": 900})
    assert result["cum_taxable"] == Decimal("40000.00")
    assert (result["rate"], result["quick"], result["cum_tax"], result["tax"]) == (10, 2520, Decimal("1480.00"), Decimal("580.00"))


@pytest.mark.parametrize("taxable, rate, quick", [
    (36000, 3, 0), (36000.01, 10, 2520), (144000, 10, 2520), (300000, 20, 16920), (420000, 25, 31920),
    (660000, 30, 52920), (960000, 35, 85920), (960000.01, 45, 181920),
])
def test_annual_table_brackets(taxable, rate, quick):
    got_rate, got_quick, _ = tax.cumulative_tax(taxable)
    assert (got_rate, got_quick) == (rate, quick)


def test_negative_result_is_zero_not_a_refund():
    # 之前多扣了：本月不退，记 0
    result = tax.withholding({"income": 3000}, {"months": 1, "income": 20000, "tax": 500})
    assert result["tax"] == Decimal("0.00")
    assert tax.withholding({"income": 4000})["cum_taxable"] == Decimal("0.00")


def test_low_income_rule_deducts_sixty_thousand_from_january():
    normal = tax.withholding({"income": 9000})
    low = tax.withholding({"income": 9000}, low_income=True)
    assert normal["tax"] == Decimal("120.00") and low["tax"] == Decimal("0.00") and low["cum_basic"] == Decimal("60000.00")
    # 第 13 个月以后（不可能）也不会少于 5000 × 月数
    assert tax.withholding({"income": 1}, {"months": 12}, low_income=True)["cum_basic"] == Decimal("65000.00")


def test_annual_bonus_separate_taxation_uses_the_monthly_table():
    assert tax.bonus_tax(36000) == (3, 0, Decimal("1080.00"))
    assert tax.bonus_tax(36001) == (10, 210, Decimal("3390.10"))
    assert tax.bonus_tax(0)[2] == Decimal("0.00")


@pytest.mark.parametrize("period, expected", [("2026-10", "2026-11"), ("2026-12", "2027-01"), ("2027-01", "2027-02")])
def test_salary_is_paid_next_month_so_tax_belongs_to_the_next_month(period, expected):
    assert tax.tax_period(period) == expected
