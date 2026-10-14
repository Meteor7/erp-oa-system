"""工资条金额只认人事算好的数（决定 2026-10-14）：HRMS validate 按结构重建了基本工资、改了计薪天数以后，钩子把它们放回去。"""
from rayher_hr_payroll import payroll_slip


class Slip(dict):
    def get(self, key, default=None):
        return super().get(key, default)
    def set(self, table, rows): self[table] = list(rows)
    def append(self, table, row): self.setdefault(table, []).append(row)
    def update(self, values): super().update(values)


def _hrms_overwritten():
    # 页面算的：10750（10000 + 调薪 750）× 88 / 176 = 5375；奖金 500；社保 900、公积金 450、个税 123
    # HRMS validate 之后：计薪天数 22、基本工资按结构 base 重建成 9750
    return Slip(
        hr_spa_managed=1, hr_amounts_v2=1, hr_total_hours=176, hr_actual_hours=88, hr_prorated_base=5375,
        hr_company_subsidy=0, hr_bonus=500, hr_other_adjustment=-75, hr_social_personal=900, hr_fund_personal=450,
        hr_accommodation=200, hr_income_tax=123, hr_advanced_paid=0,
        payment_days=22, total_working_days=22, earnings=[{"salary_component": "基本工资", "amount": 9750}],
        deductions=[], gross_pay=10250, net_pay=8777, rounded_total=8777,
    )


def test_hook_restores_hours_lines_and_totals_after_hrms_validate():
    doc = _hrms_overwritten()
    payroll_slip.keep_hr_amounts(doc)
    assert {row["salary_component"]: row["amount"] for row in doc["earnings"]} == {"基本工资": 5375.0, "奖金": 500.0}
    assert {row["salary_component"]: row["amount"] for row in doc["deductions"]} == {
        "社保个人": 900.0, "公积金个人": 450.0, "宿舍扣款": 200.0, "个税": 123.0, "其他扣款": 75.0}
    assert (doc["payment_days"], doc["total_working_days"]) == (11.0, 22.0)
    assert (doc["gross_pay"], doc["total_deduction"], doc["net_pay"]) == (5875.0, 1748.0, 4127.0)
    # 实发保留两位小数，不按元取整
    assert doc["rounded_total"] == doc["net_pay"] and doc["base_net_pay"] == doc["net_pay"]


def test_hook_leaves_other_slips_alone():
    for flags in ({"hr_spa_managed": 0, "hr_amounts_v2": 1}, {"hr_spa_managed": 1, "hr_amounts_v2": 0}):
        doc = _hrms_overwritten()
        doc.update(flags)
        payroll_slip.keep_hr_amounts(doc)
        assert doc["net_pay"] == 8777 and doc["earnings"] == [{"salary_component": "基本工资", "amount": 9750}]


def test_the_hook_runs_after_the_hrms_controller_on_every_salary_slip_save():
    from rayher_hr_payroll import hooks

    validate = hooks.doc_events["Salary Slip"]["validate"]
    assert validate[-1] == "rayher_hr_payroll.payroll_slip.keep_hr_amounts"
    assert "rayher_hr_payroll.payroll_bridge.block_locked_salary_slip_change" in validate
