"""薪酬计算的三样输入：工时、社保公积金、个税累计（决定 2026-10-14）。

- 工时：当月总工时 = 公司日历这个月的工作日 × 8；实际工时 = 在职期间的工作日 × 8 − 已批准的事假小时。
  只有事假扣工时（年假、调休、病假、婚丧产假都不扣），和研发工时上限同一个算法（attendance_requests.leave_hours_by_date）。
- 社保：已生效的社保账单 → 本月社保月度记录 → 按员工档案基数 × 公司当年政策算（hr_contributions.social_policy）；
  公积金：本月公积金月度记录（公积金账单生效时写入）→ 按档案基数 × 政策比例算。
  按档案算出来的，保存工资草稿时顺带写一条月度记录（备注“自动：按档案基数”），社保公积金页、看板、研发分摊都看得到。
- 个税：工资次月发，按发放月累计预扣（income_tax.py）。今年之前的月份 = 员工个税资料里的期初累计 + 本单位已确认的工资条。
"""
from __future__ import annotations

from datetime import date
from calendar import monthrange

import frappe

from rayher_hr_payroll import income_tax
from rayher_hr_payroll.hr_contributions import (
    calculate_social_snapshot,
    fund_rates,
    household_classification,
    housing_fund_amounts,
    social_policy,
)

HOURS_PER_DAY = 8
AUTO_REMARK = "自动：按档案基数"
SOCIAL_RATE_FIELDS = (
    "employee_pension_rate", "company_pension_rate", "employee_medical_rate", "company_medical_rate",
    "employee_unemployment_rate", "company_unemployment_rate", "company_injury_rate", "company_maternity_rate",
)
TAX_PROFILE = "Employee Tax Profile"
TAX_PROFILE_FIELDS = (
    "name", "low_income_rule", "special_total", "other_deduction", "opening_to_period", "opening_months",
    "opening_income", "opening_tax_free", "opening_special", "opening_special_additional", "opening_other",
    "opening_tax", "opening_bonus_used",
)
TAX_SLIP_FIELDS = (
    "name", "start_date", "hr_tax_period", "hr_tax_income", "hr_tax_special", "hr_tax_special_additional",
    "hr_tax_other", "hr_income_tax", "hr_bonus_tax", "hr_bonus_separate",
)


def _num(value):
    return float(value or 0)


def _month(period):
    year, month = int(str(period)[:4]), int(str(period)[5:7])
    return year, month, date(year, month, 1), date(year, month, monthrange(year, month)[1])


# ---------------------------------------------------------------- 工时
def work_hours(employee, company, period, calendars=None):
    """{total_hours, employed_hours, personal_leave_hours, actual_hours, work_days, calendar_source}。
    calendars：同一次请求里按公司缓存公司日历（全员算工资时不重复查）。"""
    from rayher_hr_payroll.attendance_requests import COMPLETED, REQUEST_LEAVE, leave_hours_by_date
    from rayher_hr_payroll.working_calendar import resolve_monthly_calendar

    year, month, first, last = _month(period)
    cache = calendars if calendars is not None else {}
    key = (company, period)
    if key not in cache:
        cache[key] = resolve_monthly_calendar(year, month, company=company)
    company_calendar = cache[key]
    person = resolve_monthly_calendar(year, month, employee=employee, company=company)
    rows = frappe.get_all(
        "OA Approval Request",
        filters={"employee": employee, "request_type": REQUEST_LEAVE, "leave_type": "事假",
                 "workflow_status": ["in", list(COMPLETED)], "from_date": ["<=", last], "to_date": [">=", first]},
        fields=["request_type", "workflow_status", "leave_type", "attendance_days", "from_date", "to_date"],
        limit_page_length=0,
    )
    leave = float(sum(leave_hours_by_date(rows, person["work_dates"]).values()))
    total = float(len(company_calendar["work_dates"]) * HOURS_PER_DAY)
    employed = float(len(person["work_dates"]) * HOURS_PER_DAY)
    return {
        "total_hours": total, "employed_hours": employed, "personal_leave_hours": leave,
        "actual_hours": max(employed - leave, 0.0), "work_days": len(company_calendar["work_dates"]),
        "calendar_source": company_calendar.get("calendar_source"),
    }


# ---------------------------------------------------------------- 社保公积金
def _social_batch_row(employee, company, period):
    batch = frappe.db.get_value("Social Insurance Import Batch", {"period": period, "is_current": 1}, "name")
    if not batch:
        return None
    return frappe.db.get_value(
        "Social Insurance Import Row",
        {"batch": batch, "employee": employee, "company": company, "status": ["in", ["Matched", "Confirmed Difference"]]},
        ["name", "employee_pension", "employee_medical", "employee_unemployment", "employee_total", "company_total"],
        as_dict=True,
    )


def _record(doctype, employee, period, fields):
    return frappe.db.get_value(doctype, {"employee": employee, "period": period}, fields, as_dict=True)


def _social(employee_row, period):
    employee, company = employee_row["name"], employee_row.get("company")
    row = _social_batch_row(employee, company, period)
    if row:
        return {**row, "source": f"社保账单（{period}）"}
    record = _record("Employee Social Insurance", employee, period,
                     ["name", "employee_pension", "employee_medical", "employee_unemployment", "employee_total",
                      "company_total", "remark", "contribution_base"])
    if record:
        auto = str(record.get("remark") or "").startswith(AUTO_REMARK)
        return {**record, "source": f"按档案基数 {_num(record.get('contribution_base')):g}" if auto else "社保月度记录"}
    base = _num(employee_row.get("default_social_insurance_base"))
    if base <= 0:
        return {"missing": "员工档案里没有社保基数"}
    policy = social_policy(company, period)
    if not policy:
        return {"missing": f"{company or '所属公司'} {period[:4]} 年的社保政策还没配置"}
    household = household_classification(employee_row.get("household_registration"))
    values = calculate_social_snapshot(base, bool(household), policy)
    return {
        "employee_pension": float(values["employee_pension"]), "employee_medical": float(values["employee_medical"]),
        "employee_unemployment": float(values["employee_unemployment"]), "employee_total": float(values["employee_total"]),
        "company_total": float(values["company_total"]), "contribution_base": base,
        "source": f"按档案基数 {base:g}（{policy['version']}）", "auto": True, "policy": policy,
        "household_known": household is not None,
    }


def _fund(employee_row, period):
    employee, company = employee_row["name"], employee_row.get("company")
    record = _record("Employee Housing Fund", employee, period,
                     ["name", "employee_amount", "company_amount", "remark", "contribution_base"])
    if record:
        auto = str(record.get("remark") or "").startswith(AUTO_REMARK)
        return {**record, "source": f"按档案基数 {_num(record.get('contribution_base')):g}" if auto else "公积金月度记录"}
    base = _num(employee_row.get("default_housing_fund_base"))
    if base <= 0:
        return {"missing": "员工档案里没有公积金基数"}
    employee_rate, company_rate = fund_rates(company, period)
    amounts = housing_fund_amounts(base, employee_rate, company_rate)
    return {
        "employee_amount": float(amounts["employee_amount"]), "company_amount": float(amounts["company_amount"]),
        "contribution_base": base, "source": f"按档案基数 {base:g} × {float(employee_rate):g}%", "auto": True,
        "employee_rate": float(employee_rate), "company_rate": float(company_rate),
    }


def contributions(employee_row, period):
    """{social, fund}：每样要么是金额 + 来源（source），要么是 {"missing": 原因}。只读，不写记录。"""
    return {"social": _social(employee_row, period), "fund": _fund(employee_row, period)}


def materialize(employee_row, period, found):
    """按档案算出来的社保 / 公积金写成本月月度记录（已有记录或账单的不动）。保存工资草稿时调用。"""
    employee = employee_row["name"]
    social, fund = found.get("social") or {}, found.get("fund") or {}
    if social.get("auto"):
        policy = social["policy"]
        doc = frappe.new_doc("Employee Social Insurance")
        doc.update({
            "period": period, "employee": employee, "employee_name": employee_row.get("employee_name"),
            "contribution_base": social["contribution_base"], **{key: float(policy[key]) for key in SOCIAL_RATE_FIELDS},
            "employee_pension": social["employee_pension"], "employee_medical": social["employee_medical"],
            "employee_unemployment": social["employee_unemployment"], "employee_total": social["employee_total"],
            "company_total": social["company_total"], "status": "Confirmed",
            "remark": f"{AUTO_REMARK}（{policy['version']}）", "employee_period_key": f"{employee}|{period}",
        })
        # 医疗有最低基数、深户有地方补充养老，记录自己的重算没有这两样：用政策算好的金额，不让它重算
        doc.flags.keep_amounts = True
        doc.insert(ignore_permissions=True)
    if fund.get("auto"):
        doc = frappe.new_doc("Employee Housing Fund")
        doc.update({
            "period": period, "employee": employee, "employee_name": employee_row.get("employee_name"),
            "contribution_base": fund["contribution_base"], "employee_rate": fund["employee_rate"],
            "company_rate": fund["company_rate"], "status": "Confirmed", "remark": AUTO_REMARK,
            "employee_period_key": f"{employee}|{period}",
        })
        doc.insert(ignore_permissions=True)


def drop_auto_records(employee, period, kinds=("si", "fund")):
    """基数改了：删掉本月自动生成的记录，下次算工资按新基数重算（手工维护和账单写入的记录不动）。"""
    for kind, doctype in (("si", "Employee Social Insurance"), ("fund", "Employee Housing Fund")):
        if kind not in kinds:
            continue
        for row in frappe.get_all(doctype, filters={"employee": employee, "period": period}, fields=["name", "remark"]):
            if str(row.get("remark") or "").startswith(AUTO_REMARK):
                frappe.delete_doc(doctype, row["name"], ignore_permissions=True)


# ---------------------------------------------------------------- 个税
def tax_basis(employee, company, period, exclude=None):
    """算这个人本月个税要用的累计数（不含本月）。exclude：本月自己的工资条，不算进“之前的月份”。"""
    period_start = _month(period)[2]
    month = income_tax.tax_period(period)
    year = int(month[:4])
    profile = frappe.db.get_value(TAX_PROFILE, {"employee": employee, "year": year}, list(TAX_PROFILE_FIELDS), as_dict=True) or {}
    opening_to = str(profile.get("opening_to_period") or "")
    slips = frappe.get_all(
        "Salary Slip",
        filters={"employee": employee, "company": company, "docstatus": 1, "hr_spa_managed": 1,
                 "hr_tax_period": ["like", f"{year:04d}-%"]},
        fields=list(TAX_SLIP_FIELDS), limit_page_length=0,
    )
    earlier = [slip for slip in slips if slip.get("name") != exclude and str(slip.get("hr_tax_period") or "") < month
               and str(slip.get("hr_tax_period") or "") > opening_to]
    prior = {
        "months": int(profile.get("opening_months") or 0) + len(earlier),
        "income": _num(profile.get("opening_income")) + sum(_num(s.get("hr_tax_income")) for s in earlier),
        "tax_free": _num(profile.get("opening_tax_free")),
        "special": _num(profile.get("opening_special")) + sum(_num(s.get("hr_tax_special")) for s in earlier),
        "special_additional": _num(profile.get("opening_special_additional")) + sum(_num(s.get("hr_tax_special_additional")) for s in earlier),
        "other": _num(profile.get("opening_other")) + sum(_num(s.get("hr_tax_other")) for s in earlier),
        # 已预扣只算累计预扣的部分；单独计税的年终奖税额另算
        "tax": _num(profile.get("opening_tax")) + sum(_num(s.get("hr_income_tax")) - _num(s.get("hr_bonus_tax")) for s in earlier),
    }
    bonus_used = bool(profile.get("opening_bonus_used")) or any(
        int(s.get("hr_bonus_separate") or 0) and s.get("name") != exclude for s in slips)
    warnings = []
    drafts = frappe.get_all(
        "Salary Slip",
        filters={"employee": employee, "company": company, "docstatus": 0, "hr_spa_managed": 1, "start_date": ["<", period_start]},
        fields=["name", "start_date", "hr_tax_period"], limit_page_length=0,
    )
    # 同一个个税年度里、比本月早、还没确认的草稿（旧草稿没有 hr_tax_period，按工资月份 + 1 算）
    pending = sorted({str(d.get("start_date"))[:7] for d in drafts
                      if str(d.get("hr_tax_period") or income_tax.tax_period(str(d.get("start_date"))[:7]))[:4] == str(year)})
    if pending:
        warnings.append("还没确认的工资：" + "、".join(pending) + "；个税累计没算它们，先确认前面的月份")
    if int(month[5:]) > 1 and not prior["months"] and not profile:
        warnings.append(f"今年 1–{int(month[5:]) - 1} 月的累计数没有录入（个税资料里的期初累计），本月个税按今年第一个月算，可能偏少")
    return {
        "tax_period": month, "year": year, "prior": prior, "low_income": bool(profile.get("low_income_rule")),
        "special_additional": _num(profile.get("special_total")), "other": _num(profile.get("other_deduction")),
        "bonus_used": bonus_used, "has_profile": bool(profile), "warnings": warnings,
    }


def compute_tax(basis, payable, social, fund, bonus, bonus_separate):
    """本月个税：累计预扣（不含单独计税的年终奖）+ 年终奖单独计税。返回金额都是 float。"""
    bonus_part = _num(bonus) if bonus_separate else 0.0
    current = {
        "income": _num(payable) - bonus_part, "tax_free": 0, "special": _num(social) + _num(fund),
        "special_additional": basis["special_additional"], "other": basis["other"],
    }
    result = income_tax.withholding(current, basis["prior"], low_income=basis["low_income"])
    bonus_rate, bonus_quick, bonus_tax = income_tax.bonus_tax(bonus_part)
    out = {key: (float(value) if not isinstance(value, int) else value) for key, value in result.items()}
    out.update({
        "income": round(current["income"], 2), "special": round(current["special"], 2),
        "special_additional": round(current["special_additional"], 2), "other": round(current["other"], 2),
        "bonus_rate": float(bonus_rate), "bonus_quick": float(bonus_quick), "bonus_tax": float(bonus_tax),
        "total": round(float(result["tax"]) + float(bonus_tax), 2), "tax_period": basis.get("tax_period"),
    })
    return out
