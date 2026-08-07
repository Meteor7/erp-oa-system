from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")

HOUSEHOLD_OPTIONS = (
    "深圳", "广东省内城镇", "广东省内农村", "广东省外城镇", "广东省外农村",
)


def household_classification(value):
    """Classify canonical choices, legacy labels, and explicit locations."""

    text = str(value or "").strip()
    if not text:
        return None
    compact = "".join(text.split())
    if compact.startswith("非深") or "非深圳" in compact:
        return False
    if compact == "深户" or "深圳" in compact:
        return True
    if compact in HOUSEHOLD_OPTIONS[1:]:
        return False
    if any(marker in compact for marker in ("省", "市", "县", "自治州", "自治区")):
        return False
    return None


def social_policy(company, period):
    if str(company or "").strip() != "Rayher" or not str(period or "").startswith("2026-"):
        return None
    return {
        "version": "示例总部-2026",
        "medical_floor": Decimal("6727"),
        "employee_pension_rate": Decimal("8"),
        "company_pension_rate": Decimal("16"),
        "employee_medical_rate": Decimal("2"),
        "company_medical_rate": Decimal("6"),
        "company_maternity_rate": Decimal("0.5"),
        "company_injury_rate": Decimal("0.8"),
        "employee_unemployment_rate": Decimal("0.2"),
        "company_unemployment_rate": Decimal("0.8"),
        "local_pension_rate": Decimal("1"),
    }

SOCIAL_COMPONENTS = (
    "employee_pension", "company_pension", "employee_medical", "company_medical",
    "company_maternity", "company_injury", "employee_unemployment",
    "company_unemployment", "local_pension",
)


def _money(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _part(base, rate):
    return (_money(base) * Decimal(str(rate or 0)) / Decimal("100")).quantize(
        CENT, rounding=ROUND_HALF_UP
    )


def social_insurance_amounts(base, **rates):
    employee_pension = _part(base, rates.get("employee_pension_rate"))
    company_pension = _part(base, rates.get("company_pension_rate"))
    employee_medical = _part(base, rates.get("employee_medical_rate"))
    company_medical = _part(base, rates.get("company_medical_rate"))
    employee_unemployment = _part(base, rates.get("employee_unemployment_rate"))
    company_unemployment = _part(base, rates.get("company_unemployment_rate"))
    company_injury = _part(base, rates.get("company_injury_rate"))
    company_maternity = _part(base, rates.get("company_maternity_rate"))
    return {
        "employee_pension": employee_pension,
        "company_pension": company_pension,
        "employee_medical": employee_medical,
        "company_medical": company_medical,
        "employee_unemployment": employee_unemployment,
        "company_unemployment": company_unemployment,
        "company_injury": company_injury,
        "company_maternity": company_maternity,
        "employee_total": employee_pension + employee_medical + employee_unemployment,
        "company_total": company_pension + company_medical + company_unemployment + company_injury + company_maternity,
    }


def calculate_social_snapshot(wage, is_shenzhen_household=False, policy=None):
    wage = _money(wage)
    policy = {
        "medical_floor": Decimal("6727"),
        "employee_pension_rate": Decimal("8"),
        "company_pension_rate": Decimal("16"),
        "employee_medical_rate": Decimal("2"),
        "company_medical_rate": Decimal("6"),
        "company_maternity_rate": Decimal("0.5"),
        "company_injury_rate": Decimal("0.8"),
        "employee_unemployment_rate": Decimal("0.2"),
        "company_unemployment_rate": Decimal("0.8"),
        "local_pension_rate": Decimal("1"),
        **(policy or {}),
    }
    medical_base = max(wage, _money(policy["medical_floor"]))
    values = {
        "employee_pension": _part(wage, policy["employee_pension_rate"]),
        "company_pension": _part(wage, policy["company_pension_rate"]),
        "employee_medical": _part(medical_base, policy["employee_medical_rate"]),
        "company_medical": _part(medical_base, policy["company_medical_rate"]),
        "company_maternity": _part(medical_base, policy["company_maternity_rate"]),
        "company_injury": _part(wage, policy["company_injury_rate"]),
        "employee_unemployment": _part(wage, policy["employee_unemployment_rate"]),
        "company_unemployment": _part(wage, policy["company_unemployment_rate"]),
        "local_pension": _part(wage, policy["local_pension_rate"]) if is_shenzhen_household else _money(0),
        "medical_base": medical_base,
        "contribution_base": wage,
    }
    values["employee_total"] = sum(
        (values[key] for key in ("employee_pension", "employee_medical", "employee_unemployment")),
        _money(0),
    )
    values["company_total"] = sum(
        (values[key] for key in (
            "company_pension", "company_medical", "company_maternity",
            "company_injury", "company_unemployment", "local_pension",
        )),
        _money(0),
    )
    values["receivable_total"] = values["employee_total"] + values["company_total"]
    return values


def compare_social_snapshot(excel_amounts, calculated_amounts):
    money_keys = (*SOCIAL_COMPONENTS, "employee_total", "company_total", "receivable_total")
    excel = {key: _money(excel_amounts.get(key)) for key in money_keys}
    calculated = {key: _money(calculated_amounts.get(key)) for key in money_keys}
    reasons = []
    excel_employee = sum(
        (excel.get(key, _money(0)) for key in ("employee_pension", "employee_medical", "employee_unemployment")),
        _money(0),
    )
    excel_company = sum(
        (excel.get(key, _money(0)) for key in (
            "company_pension", "company_medical", "company_maternity",
            "company_injury", "company_unemployment", "local_pension",
        )),
        _money(0),
    )
    if (
        excel.get("employee_total") != excel_employee
        or excel.get("company_total") != excel_company
        or excel.get("receivable_total") != excel_employee + excel_company
    ):
        reasons.append("Excel内部合计不一致")
    differences = {}
    for key in (*SOCIAL_COMPONENTS, "employee_total", "company_total", "receivable_total"):
        difference = excel.get(key, _money(0)) - calculated.get(key, _money(0))
        differences[key] = difference
        if difference and key not in ("employee_total", "company_total", "receivable_total"):
            reasons.append(f"{key}与后台计算不一致")
    return {"matches": not reasons, "reasons": reasons, "differences": differences}


def housing_fund_amounts(base, employee_rate, company_rate):
    return {
        "employee_amount": _part(base, employee_rate),
        "company_amount": _part(base, company_rate),
    }
