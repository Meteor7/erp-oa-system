"""工资薪金个人所得税：累计预扣法（不依赖 frappe，便于单元测试）。

口径（国家税务总局公告 2018 年第 61 号，2026 年仍执行；决定 2026-10-14）：
- 工资次月发，个税按实际发放的月份算：10 月的工资条算进 11 月（税款所属期 = 工资月份 + 1）；12 月工资算进下一年 1 月。
- 累计预扣预缴应纳税所得额 = 累计收入 − 累计免税收入 − 累计减除费用（5000 × 今年在本单位发工资的月数）
  − 累计专项扣除（社保、公积金个人部分）− 累计专项附加扣除 − 累计依法确定的其他扣除（个人养老金等）。
- 本期应预扣 = 累计应纳税所得额 × 预扣率 − 速算扣除数 − 累计已预扣；算出来是负数当月记 0，不退，年度汇算多退少补。
- 上一完整年度每月都在本单位预扣、全年工资不超过 6 万的（税务总局公告 2020 年第 19 号），减除费用从 1 月起直接按 6 万扣。
- 全年一次性奖金可以单独计税（财政部 税务总局公告 2023 年第 30 号，执行到 2027 年底）：奖金 ÷ 12 查月度税率表，
  奖金 × 税率 − 速算扣除数，不并入当月累计；一年只能用一次。
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
MONTHLY_BASIC_DEDUCTION = Decimal("5000")
LOW_INCOME_BASIC_DEDUCTION = Decimal("60000")
PAY_MONTH_OFFSET = 1   # 次月发

# 个人所得税预扣率表一（居民个人工资、薪金所得预扣预缴适用）：(累计应纳税所得额上限, 预扣率 %, 速算扣除数)
ANNUAL_TABLE = (
    (Decimal("36000"), Decimal("3"), Decimal("0")),
    (Decimal("144000"), Decimal("10"), Decimal("2520")),
    (Decimal("300000"), Decimal("20"), Decimal("16920")),
    (Decimal("420000"), Decimal("25"), Decimal("31920")),
    (Decimal("660000"), Decimal("30"), Decimal("52920")),
    (Decimal("960000"), Decimal("35"), Decimal("85920")),
    (None, Decimal("45"), Decimal("181920")),
)
# 按月换算后的综合所得税率表（全年一次性奖金单独计税用）
MONTHLY_TABLE = (
    (Decimal("3000"), Decimal("3"), Decimal("0")),
    (Decimal("12000"), Decimal("10"), Decimal("210")),
    (Decimal("25000"), Decimal("20"), Decimal("1410")),
    (Decimal("35000"), Decimal("25"), Decimal("2660")),
    (Decimal("55000"), Decimal("30"), Decimal("4410")),
    (Decimal("80000"), Decimal("35"), Decimal("7160")),
    (None, Decimal("45"), Decimal("15160")),
)


def money(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def tax_period(period):
    """工资月份 "YYYY-MM" → 个税所属期（实际发放的月份）。"""
    year, month = int(str(period)[:4]), int(str(period)[5:7]) + PAY_MONTH_OFFSET
    if month > 12:
        year, month = year + 1, month - 12
    return f"{year:04d}-{month:02d}"


def _bracket(amount, table):
    for upper, rate, quick in table:
        if upper is None or amount <= upper:
            return rate, quick
    return table[-1][1], table[-1][2]


def cumulative_tax(taxable):
    """累计应纳税所得额 → (预扣率 %, 速算扣除数, 累计应纳税额)。所得额 ≤ 0 不交税。"""
    taxable = money(taxable)
    if taxable <= 0:
        return Decimal("0"), Decimal("0"), money(0)
    rate, quick = _bracket(taxable, ANNUAL_TABLE)
    return rate, quick, money(taxable * rate / 100 - quick)


def bonus_tax(bonus):
    """全年一次性奖金单独计税：(预扣率 %, 速算扣除数, 税额)。"""
    bonus = money(bonus)
    if bonus <= 0:
        return Decimal("0"), Decimal("0"), money(0)
    rate, quick = _bracket(bonus / 12, MONTHLY_TABLE)
    return rate, quick, money(max(bonus * rate / 100 - quick, Decimal("0")))


def withholding(current, prior=None, *, low_income=False):
    """本月应预扣的个税和全部中间数。

    current：本月 {income 收入（不含单独计税的年终奖）, tax_free 免税收入, special 社保公积金个人部分,
             special_additional 专项附加扣除, other 其他扣除}；
    prior：今年之前月份的累计 {months 月数, income, tax_free, special, special_additional, other, tax 已预扣}；
    low_income：上年每月在本单位、全年不超过 6 万（减除费用直接按 6 万）。
    """
    prior = prior or {}
    months = int(prior.get("months") or 0) + 1
    keys = ("income", "tax_free", "special", "special_additional", "other")
    cum = {key: money(prior.get(key)) + money(current.get(key)) for key in keys}
    basic = LOW_INCOME_BASIC_DEDUCTION if low_income else MONTHLY_BASIC_DEDUCTION * months
    basic = max(basic, MONTHLY_BASIC_DEDUCTION * months)
    taxable = cum["income"] - cum["tax_free"] - basic - cum["special"] - cum["special_additional"] - cum["other"]
    rate, quick, cum_tax = cumulative_tax(taxable)
    withheld = money(prior.get("tax"))
    tax = max(cum_tax - withheld, Decimal("0"))
    return {
        "months": months, "cum_income": cum["income"], "cum_tax_free": cum["tax_free"], "cum_basic": money(basic),
        "cum_special": cum["special"], "cum_special_additional": cum["special_additional"], "cum_other": cum["other"],
        "cum_taxable": money(max(taxable, Decimal("0"))), "rate": rate, "quick": quick, "cum_tax": cum_tax,
        "prior_tax": withheld, "tax": money(tax),
    }
