"""公积金汇缴明细导入：解析 Excel、认人、按档案基数和比例复算、找出差异。

只放纯函数，不碰数据库；和 social_insurance_import.py 是一对：认人、期间写法、批次选择沿用社保那边的，
这里只补公积金自己的部分（表头识别、金额复算、"申报表里没有这个人"的反向检查）。
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO

from openpyxl import load_workbook

from rayher_hr_payroll.hr_contributions import housing_fund_amounts
from rayher_hr_payroll.social_insurance_import import (  # noqa: F401  (re-exported for the entry module)
    can_activate_rows,
    mask_identity,
    match_employee,
    normalize_identity,
    normalize_name,
    select_workbench_batches,
)

CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")
DEFAULT_EMPLOYEE_RATE = Decimal("7")
DEFAULT_COMPANY_RATE = Decimal("7")
HEADER_SCAN_ROWS = 20
TOTAL_LABELS = ("合计", "小计", "总计")

# 公积金中心导出的表头各地叫法不一样，按名字找列，不依赖列的位置。
HEADER_ALIASES = {
    "name": ("姓名", "职工姓名", "员工姓名", "缴存人", "缴存人姓名", "个人姓名"),
    "identity": ("证件号码", "身份证号", "身份证号码", "证件号", "公民身份号码", "身份证件号码"),
    "base": ("缴存基数", "缴费基数", "月缴存基数", "缴存工资", "缴存工资基数", "基数"),
    "employee_amount": ("个人缴存额", "个人缴存", "个人缴存金额", "职工缴存额", "个人月缴存额", "个人缴纳", "个人部分", "个人缴存额合计"),
    "company_amount": ("单位缴存额", "单位缴存", "单位缴存金额", "企业缴存额", "单位月缴存额", "单位缴纳", "单位部分", "单位缴存额合计"),
    "total": ("月缴存额", "缴存合计", "月缴存总额", "缴存总额", "应缴合计", "缴存额合计"),
    "period": ("缴存年月", "汇缴年月", "费款所属期", "所属期", "缴存月份", "汇缴月份", "缴存期间"),
}


def _money(value):
    if value in (None, ""):
        return Decimal("0.00")
    if isinstance(value, str):
        value = re.sub(r"[,，¥￥元\s]", "", value)
        if value in ("", "-"):
            return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"金额格式无效：{value}") from None


def canonical_period(value):
    """2026-10 / 2026/10 / 2026年10月 / 202610 / 日期 都认，统一成 YYYY-MM。"""
    if isinstance(value, (date, datetime)):
        return f"{value.year:04d}-{value.month:02d}"
    text = re.sub(r"\s", "", str(value or ""))
    match = re.fullmatch(r"(\d{4})[-/.年]?(\d{1,2})月?(?:[-/.]?\d{1,2}日?)?", text)
    if match and 1 <= int(match.group(2)) <= 12:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    raise ValueError("公积金期间格式错误")


def _header_key(value):
    text = re.sub(r"[\s（）()：:]", "", str(value or ""))
    return re.sub(r"元$", "", text)


def _map_headers(row):
    mapped = {}
    for index, cell in enumerate(row):
        key = _header_key(cell)
        if not key:
            continue
        for field, aliases in HEADER_ALIASES.items():
            if field not in mapped and key in {_header_key(alias) for alias in aliases}:
                mapped[field] = index
    return mapped


def _find_header(rows):
    for position, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        mapped = _map_headers(row)
        if {"name", "identity", "base"} <= set(mapped) and ("employee_amount" in mapped or "total" in mapped):
            return position, mapped
    return None, None


def parse_housing_workbook(content, period=None):
    """读出公积金汇缴明细。表头里要有：姓名、证件号码、缴存基数、个人缴存额，以及单位缴存额或月缴存额合计。"""
    expected_period = canonical_period(period) if period else None
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    parsed, detected, header_seen = [], None, False
    for sheet in workbook.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        position, mapped = _find_header(rows)
        if position is None:
            continue
        header_seen = True
        for offset, values in enumerate(rows[position + 1:], start=position + 2):
            def cell(field, _values=values, _mapped=mapped):
                index = _mapped.get(field)
                return _values[index] if index is not None and index < len(_values) else None
            name = str(cell("name") or "").strip()
            identity = normalize_identity(cell("identity"))
            if not name and not identity:
                continue
            if any(name.startswith(label) for label in TOTAL_LABELS):
                continue
            base = _money(cell("base"))
            employee_amount = _money(cell("employee_amount"))
            total = _money(cell("total")) if "total" in mapped else None
            if "company_amount" in mapped:
                company_amount = _money(cell("company_amount"))
            elif total is not None:
                company_amount = (total - employee_amount).quantize(CENT)
            else:
                raise ValueError("公积金Excel表头缺少单位缴存额或月缴存额合计")
            raw_period = cell("period")
            row_period = canonical_period(raw_period) if raw_period not in (None, "") else expected_period
            if not row_period:
                raise ValueError("Excel里没有缴存期间，请先选择期间再上传")
            if expected_period and row_period != expected_period:
                raise ValueError(f"Excel期间与所选期间不一致：{row_period}")
            if detected is None:
                detected = row_period
            elif row_period != detected:
                raise ValueError(f"Excel中存在多个公积金期间：{detected}、{row_period}")
            parsed.append({
                "row_number": len(parsed) + 1, "source_row": offset, "excel_name": name, "identity_number": identity,
                "period": row_period, "contribution_base": base, "employee_amount": employee_amount,
                "company_amount": company_amount, "total_amount": total,
            })
        if parsed:
            break
    if not header_seen:
        raise ValueError("没有找到公积金明细表头：需要包含姓名、证件号码、缴存基数、个人缴存额、单位缴存额")
    if not parsed:
        raise ValueError("Excel中没有可读取的公积金明细")
    return parsed


def resolve_fund_employees(employees, month_records, period):
    """每个人用于复算的基数和比例：本月已有的月度记录优先，否则用档案默认基数和默认 7% / 7%。"""
    by_employee = {row.get("employee"): row for row in (month_records or []) if row.get("employee")}
    resolved = []
    for source in employees or []:
        employee = dict(source)
        record = by_employee.get(employee.get("name"))
        if record:
            employee["housing_fund_base"] = _money(record.get("contribution_base"))
            employee["housing_base_source"] = f"{period}月度公积金记录"
            employee["employee_rate"] = Decimal(str(record.get("employee_rate") or DEFAULT_EMPLOYEE_RATE))
            employee["company_rate"] = Decimal(str(record.get("company_rate") or DEFAULT_COMPANY_RATE))
        else:
            employee["housing_fund_base"] = _money(employee.get("default_housing_fund_base"))
            employee["housing_base_source"] = "员工默认基数"
            employee["employee_rate"] = DEFAULT_EMPLOYEE_RATE
            employee["company_rate"] = DEFAULT_COMPANY_RATE
        resolved.append(employee)
    return resolved


def reconcile_fund_row(row, employee, association_reason=""):
    result = dict(row)
    reasons = [association_reason] if association_reason and "按姓名唯一关联" not in association_reason else []
    if not employee:
        result.update({
            "employee": None, "employee_name": None, "status": "Pending", "original_match_status": "Pending",
            "difference_reasons": association_reason or "证件号码无法关联员工",
        })
        return result

    base = _money(employee.get("housing_fund_base"))
    employee_rate = Decimal(str(employee.get("employee_rate") or DEFAULT_EMPLOYEE_RATE))
    company_rate = Decimal(str(employee.get("company_rate") or DEFAULT_COMPANY_RATE))
    excel_base, excel_employee, excel_company = (_money(row.get(key)) for key in ("contribution_base", "employee_amount", "company_amount"))
    if str(employee.get("employee_name") or "").strip() != row["excel_name"]:
        reasons.append("证件号码一致但姓名不同")
    if base <= 0:
        reasons.append("员工档案公积金基数未维护")
    elif base != excel_base:
        reasons.append("Excel缴存基数与员工档案公积金基数不一致")
    calculated, difference_total = {}, Decimal("0.00")
    if base > 0:
        amounts = housing_fund_amounts(base, employee_rate, company_rate)
        calculated = {"employee_amount": amounts["employee_amount"], "company_amount": amounts["company_amount"]}
        if abs(excel_employee - calculated["employee_amount"]) > TOLERANCE:
            reasons.append("个人缴存额与后台计算不一致")
        if abs(excel_company - calculated["company_amount"]) > TOLERANCE:
            reasons.append("单位缴存额与后台计算不一致")
        difference_total = (excel_employee + excel_company - calculated["employee_amount"] - calculated["company_amount"]).quantize(CENT)
    total = row.get("total_amount")
    if total is not None and abs(_money(total) - (excel_employee + excel_company)) > TOLERANCE:
        reasons.append("Excel内部合计不一致")

    result.update({
        "employee": employee.get("name"), "employee_name": employee.get("employee_name"), "company": employee.get("company"),
        "reference_base": base, "base_source": str(employee.get("housing_base_source") or "").strip(),
        "reference_employee_rate": employee_rate, "reference_company_rate": company_rate,
        "calculated": calculated, "difference_total": difference_total,
        "status": "Pending" if reasons else "Matched",
        "difference_reasons": "；".join(dict.fromkeys(reasons)),
    })
    result["original_match_status"] = result["status"]
    return result


def missing_from_excel(employees, linked_employee_ids):
    """反向检查：档案里有公积金基数、本月申报表里却没有的人（社保那边只看 Excel 里有的行，漏报发现不了）。"""
    linked = set(linked_employee_ids or [])
    return [
        employee for employee in employees or []
        if employee.get("name") not in linked and _money(employee.get("housing_fund_base")) > 0
    ]


def rates_from_amounts(base, employee_amount, company_amount):
    """人工确认"按 Excel 记账"的差异时，月度记录存的是基数和比例：由申报金额反推比例，使重新计算后金额和 Excel 一致。"""
    base = _money(base)
    if base <= 0:
        return DEFAULT_EMPLOYEE_RATE, DEFAULT_COMPANY_RATE
    quantum = Decimal("0.0001")
    return (
        (_money(employee_amount) * 100 / base).quantize(quantum, rounding=ROUND_HALF_UP),
        (_money(company_amount) * 100 / base).quantize(quantum, rounding=ROUND_HALF_UP),
    )


def summarize_fund_rows(rows):
    """批次汇总。反向检查生成的"申报表里没有"行不算 Excel 人数，单独计数。"""
    rows = list(rows or [])
    excel = [row for row in rows if row.get("row_type", "excel") != "missing"]
    missing = [row for row in rows if row.get("row_type") == "missing"]
    total = len(excel)
    linked = sum(1 for row in excel if row.get("employee"))
    matched = sum(1 for row in excel if row.get("original_match_status") == "Matched")

    def rate(numerator, denominator):
        return round(numerator * 100 / denominator, 2) if denominator else 0.0

    def money(field):
        return sum((_money(row.get(field)) for row in excel), Decimal("0.00"))

    employee_total, company_total = money("employee_amount"), money("company_amount")
    return {
        "total_rows": total,
        "linked_rows": linked,
        "comparable_rows": linked,
        "matched_rows": matched,
        "pending_rows": sum(1 for row in rows if row.get("status") == "Pending"),
        "confirmed_difference_rows": sum(1 for row in rows if row.get("status") == "Confirmed Difference"),
        "unlinked_rows": total - linked,
        "missing_rows": len(missing),
        "match_rate": rate(matched, total),
        "comparable_rate": rate(linked, total),
        "automatic_link_rate": rate(linked, total),
        "employee_total": employee_total,
        "company_total": company_total,
        "receivable_total": employee_total + company_total,
    }
