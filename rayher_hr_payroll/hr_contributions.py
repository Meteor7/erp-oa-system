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


# 示例总部 2026 年的社保政策：数据库里没有配置“社保公积金政策”时用它（原来写死在这里，决定 2026-10-14 改成可配置）。
BUILTIN_POLICIES = {
    ("QIHENG Demo", 2026): {
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
        "fund_employee_rate": Decimal("7"),
        "fund_company_rate": Decimal("7"),
    },
}
POLICY_RATE_FIELDS = (
    "medical_floor", "employee_pension_rate", "company_pension_rate", "employee_medical_rate", "company_medical_rate",
    "company_maternity_rate", "company_injury_rate", "employee_unemployment_rate", "company_unemployment_rate",
    "local_pension_rate", "fund_employee_rate", "fund_company_rate",
)
DEFAULT_FUND_RATE = Decimal("7")


def _year(period):
    try:
        return int(str(period or "")[:4])
    except ValueError:
        return None


def _configured_policy(company, year):
    """“社保公积金政策”里启用的这家公司这一年的政策；没有 frappe / 没连数据库（纯函数测试）或还没迁移出这张表时给 None。"""
    try:
        import frappe
        if not frappe.db.table_exists("Contribution Policy"):
            return None
        rows = frappe.get_all(
            "Contribution Policy", filters={"company": company, "year": year, "enabled": 1},
            fields=["name", "version", *POLICY_RATE_FIELDS], limit_page_length=1,
        )
    except (ImportError, AttributeError, RuntimeError):   # RuntimeError：frappe.db 还没连上（本地代理没绑定）
        return None
    if not rows:
        return None
    row = rows[0]
    policy = {key: Decimal(str(row.get(key) or 0)) for key in POLICY_RATE_FIELDS}
    policy["version"] = row.get("version") or row.get("name")
    return policy


def social_policy(company, period):
    company, year = str(company or "").strip(), _year(period)
    if not company or not year:
        return None
    return _configured_policy(company, year) or (dict(BUILTIN_POLICIES[(company, year)]) if (company, year) in BUILTIN_POLICIES else None)


def fund_rates(company, period):
    """公积金个人、单位比例（%）：公司当年政策里配的，没有就各 7%。"""
    policy = social_policy(company, period) or {}
    return (Decimal(str(policy.get("fund_employee_rate") or DEFAULT_FUND_RATE)),
            Decimal(str(policy.get("fund_company_rate") or DEFAULT_FUND_RATE)))

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
