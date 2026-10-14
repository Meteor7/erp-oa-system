"""薪酬计算页生成的工资条：金额只认人事算好的数（决定 2026-10-14：系统不许改计薪天数和基本工资）。

HRMS 的 Salary Slip.validate 每次保存 / 确认都会按工资结构公式（base）重建“基本工资”、按请假重算计薪天数，
调薪、折算全丢（实测：页面算实发 4402，存下去变成 8777）。这里在 validate 的最后（doc_events 在控制器之后跑）
按工资条上记下的 hr_* 数把明细行、计薪天数和合计放回去。只处理新算法保存的工资条（hr_amounts_v2）。
"""
from __future__ import annotations

HOURS_PER_DAY = 8
EARNINGS = (("基本工资", "hr_prorated_base"), ("公司补贴", "hr_company_subsidy"), ("奖金", "hr_bonus"))
DEDUCTIONS = (("社保个人", "hr_social_personal"), ("公积金个人", "hr_fund_personal"), ("宿舍扣款", "hr_accommodation"),
              ("个税", "hr_income_tax"))


def _num(value):
    return float(value or 0)


def _get(doc, key):
    getter = getattr(doc, "get", None)
    return getter(key) if callable(getter) else getattr(doc, key, None)


def _amount(row):
    return _num(row.get("amount") if isinstance(row, dict) else getattr(row, "amount", 0))


def _money(value):
    return round(_num(value), 2)


def _line(doc, table, component, amount):
    amount = _money(amount)
    if amount > 0:
        doc.append(table, {"salary_component": component, "amount": amount})


def apply_lines(doc):
    """按 hr_* 数重建明细行和合计：应付 = 基本工资（按工时折算后）+ 补贴 + 奖金 ± 其他；实发 = 应付 − 社保 − 公积金 − 宿舍 − 个税 − 已发放。"""
    other = _num(_get(doc, "hr_other_adjustment"))
    doc.set("earnings", [])
    doc.set("deductions", [])
    for component, field in EARNINGS:
        _line(doc, "earnings", component, _get(doc, field))
    _line(doc, "earnings", "其他收入", max(other, 0))
    for component, field in DEDUCTIONS:
        _line(doc, "deductions", component, _get(doc, field))
    _line(doc, "deductions", "其他扣款", max(-other, 0))
    _line(doc, "deductions", "已发放", _get(doc, "hr_advanced_paid"))
    gross = _money(sum(_amount(row) for row in _get(doc, "earnings") or []))
    deduction = _money(sum(_amount(row) for row in _get(doc, "deductions") or []))
    net = _money(gross - deduction)
    total_hours, actual_hours = _num(_get(doc, "hr_total_hours")), _num(_get(doc, "hr_actual_hours"))
    doc.update({
        "total_working_days": round(total_hours / HOURS_PER_DAY, 4), "payment_days": round(actual_hours / HOURS_PER_DAY, 4),
        "leave_without_pay": 0, "absent_days": 0,
        "gross_pay": gross, "base_gross_pay": gross, "total_deduction": deduction, "base_total_deduction": deduction,
        # 实发保留两位小数，不取整到元（HRMS 的 rounded_total 默认四舍五入到元）
        "net_pay": net, "base_net_pay": net, "rounded_total": net, "base_rounded_total": net,
    })


def keep_hr_amounts(doc, method=None):
    """Salary Slip validate 钩子：薪酬计算页的工资条，HRMS 算完以后把人事的数放回去。"""
    if not int(_get(doc, "hr_spa_managed") or 0) or not int(_get(doc, "hr_amounts_v2") or 0):
        return
    apply_lines(doc)
    if hasattr(doc, "set_net_total_in_words"):
        doc.set_net_total_in_words()
