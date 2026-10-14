from decimal import Decimal
from rayher_hr_payroll.hr_contributions import housing_fund_amounts, social_insurance_amounts

def test_social_insurance_amounts_are_calculated_from_base_and_rates():
    values = social_insurance_amounts(10000, employee_pension_rate=8, company_pension_rate=16, employee_medical_rate=2, company_medical_rate=7, employee_unemployment_rate=0.5, company_unemployment_rate=0.5, company_injury_rate=0.4, company_maternity_rate=0.8)
    assert values["employee_total"] == Decimal("1050.00")
    assert values["company_total"] == Decimal("2470.00")

def test_housing_fund_amounts_are_rounded_to_cents():
    values = housing_fund_amounts(8888.88, 7, 7)
    assert values == {"employee_amount": Decimal("622.22"), "company_amount": Decimal("622.22")}


def test_july_2026_policy_uses_medical_floor_and_deep_household_local_pension():
    from rayher_hr_payroll.hr_contributions import calculate_social_snapshot
    values = calculate_social_snapshot("5000", is_shenzhen_household=True)
    assert values["employee_pension"] == Decimal("400.00")
    assert values["company_pension"] == Decimal("800.00")
    assert values["employee_medical"] == Decimal("134.54")
    assert values["company_medical"] == Decimal("403.62")
    assert values["company_maternity"] == Decimal("33.64")
    assert values["company_injury"] == Decimal("40.00")
    assert values["employee_unemployment"] == Decimal("10.00")
    assert values["company_unemployment"] == Decimal("40.00")
    assert values["local_pension"] == Decimal("50.00")
    assert values["employee_total"] == Decimal("544.54")
    assert values["company_total"] == Decimal("1367.26")
    assert values["receivable_total"] == Decimal("1911.80")


def test_july_2026_policy_non_deep_household_has_no_local_pension():
    from rayher_hr_payroll.hr_contributions import calculate_social_snapshot
    values = calculate_social_snapshot("10000", is_shenzhen_household=False)
    assert values["local_pension"] == Decimal("0.00")
    assert values["employee_total"] == Decimal("1020.00")
    assert values["company_total"] == Decimal("2410.00")
    assert values["receivable_total"] == Decimal("3430.00")


def test_compare_social_snapshot_requires_internal_excel_balance():
    from rayher_hr_payroll.hr_contributions import compare_social_snapshot
    calculated = {
        "employee_pension": Decimal("800.00"),
        "company_pension": Decimal("1600.00"),
        "employee_medical": Decimal("200.00"),
        "company_medical": Decimal("600.00"),
        "company_maternity": Decimal("50.00"),
        "company_injury": Decimal("80.00"),
        "employee_unemployment": Decimal("20.00"),
        "company_unemployment": Decimal("80.00"),
        "local_pension": Decimal("0.00"),
        "employee_total": Decimal("1020.00"),
        "company_total": Decimal("2410.00"),
        "receivable_total": Decimal("3430.00"),
    }
    excel = {**calculated, "receivable_total": Decimal("3430.01")}
    result = compare_social_snapshot(excel, calculated)
    assert result["matches"] is False
    assert "Excel内部合计不一致" in result["reasons"]


def test_household_categories_map_without_excel_inference():
    from rayher_hr_payroll.hr_contributions import household_classification
    assert household_classification("深圳") is True
    for value in ("广东省内城镇", "广东省内农村", "广东省外城镇", "广东省外农村"):
        assert household_classification(value) is False
    assert household_classification("深户") is True
    assert household_classification("广东省深圳市南山区") is True
    for value in ("非深城镇", "非深农村", "湖北省襄阳市", "安徽省界首市"):
        assert household_classification(value) is False
    assert household_classification("") is None
    assert household_classification("待确认") is None


def test_social_policy_is_scoped_by_company_and_period():
    from rayher_hr_payroll.hr_contributions import social_policy
    assert social_policy("Rayher", "2026-07")["version"] == "示例总部-2026"
    assert social_policy("示例研发中心", "2026-07") is None
    assert social_policy("Rayher", "2027-01") is None   # 每年的政策要单独配置（社保公积金政策）


def test_fund_rates_come_from_the_company_policy_with_a_seven_percent_default():
    from decimal import Decimal
    from rayher_hr_payroll.hr_contributions import fund_rates
    assert fund_rates("Rayher", "2026-10") == (Decimal("7"), Decimal("7"))
    assert fund_rates("示例研发中心", "2026-10") == (Decimal("7"), Decimal("7"))
