from rayher_hr_payroll.payroll_bridge import month_bounds


def test_month_bounds_returns_first_and_last_day():
    assert month_bounds("2026-07") == ("2026-07-01", "2026-07-31")
    assert month_bounds("2026-02") == ("2026-02-01", "2026-02-28")


def test_month_bounds_rejects_bad_period():
    import pytest
    with pytest.raises(ValueError):
        month_bounds("2026/07")


def test_period_pay_totals_shape(monkeypatch):
    import rayher_hr_payroll.payroll_bridge as pb
    monkeypatch.setattr(pb.frappe, "get_all", lambda *a, **k: [
        {"employee": "E1", "docstatus": 1, "gross_pay": 100.0, "total_deduction": 30.0},
        {"employee": "E2", "docstatus": 1, "gross_pay": 200.0, "total_deduction": 40.0},
    ])
    out = pb.period_pay_totals("2026-07")
    assert out == {"gross": 300.0, "deductions": 70.0, "confirmed": 2, "draft": 0, "draft_gross": 0.0,
                   "external_draft": 0, "external_draft_gross": 0.0}


def test_period_pay_totals_counts_only_confirmed_slips_and_reports_drafts(monkeypatch):
    # 决定 2026-10-13：金额只算已确认的工资条；草稿只给人数和草稿合计（看板显示成“还有 N 人没确认”）。
    import rayher_hr_payroll.payroll_bridge as pb
    captured = {}

    def get_all(doctype, filters=None, fields=None, **kwargs):
        captured.update(filters)
        return [
            {"employee": "E1", "docstatus": 1, "gross_pay": 1000.0, "total_deduction": 100.0},
            # 审查修正（2026-10-13）：draft 只数薪酬计算页生成的草稿（hr_spa_managed = 1），别处的另算 external_draft
            {"employee": "E2", "docstatus": 0, "gross_pay": 2000.0, "total_deduction": 200.0, "hr_spa_managed": 1},
            {"employee": "E3", "docstatus": 0, "gross_pay": 3000.0, "total_deduction": 300.0, "hr_spa_managed": 1},
            # 撤回确认后重做的草稿：同一个人已经有确认的就不算草稿
            {"employee": "E1", "docstatus": 0, "gross_pay": 999.0, "total_deduction": 0.0},
        ]

    monkeypatch.setattr(pb.frappe, "get_all", get_all)
    out = pb.period_pay_totals("2026-10")
    assert out == {"gross": 1000.0, "deductions": 100.0, "confirmed": 1, "draft": 2, "draft_gross": 5000.0,
                   "external_draft": 0, "external_draft_gross": 0.0}
    assert captured == {"docstatus": ["<", 2], "start_date": ["between", ["2026-10-01", "2026-10-31"]]}


def test_period_salaries_sums_multiple_slips_per_employee(monkeypatch):
    # Weekly/off-cycle payroll -> several submitted slips per employee in one month.
    # Must SUM, not overwrite (consistent with period_pay_totals).
    import rayher_hr_payroll.payroll_bridge as pb

    rows = [
        {"employee": "E1", "gross_pay": 1000.0},
        {"employee": "E1", "gross_pay": 1500.0},
        {"employee": "E2", "gross_pay": 2000.0},
    ]
    monkeypatch.setattr(pb.frappe, "get_all", lambda *a, **k: [pb.frappe._dict(r) for r in rows])
    out = pb.period_salaries("2026-07")
    assert out == {"E1": 2500.0, "E2": 2000.0}


def test_get_period_salary_sums_all_slips(monkeypatch):
    import rayher_hr_payroll.payroll_bridge as pb

    monkeypatch.setattr(
        pb.frappe, "get_all",
        lambda *a, **k: [pb.frappe._dict({"gross_pay": 1000.0}), pb.frappe._dict({"gross_pay": 1500.0})],
    )
    assert pb.get_period_salary("E1", "2026-07") == 2500.0


def test_period_company_contributions_reads_confirmed_records_only(monkeypatch):
    # 审查 X2-2（决定 D1）：只读已确认的单位社保、公积金，不改这两个模块。
    from rayher_hr_payroll import payroll_bridge as bridge

    calls = []

    def get_all(doctype, filters=None, fields=None, **kwargs):
        calls.append((doctype, filters))
        if doctype == "Salary Slip":
            return []
        if doctype == "Employee Social Insurance":
            return [{"employee": "E1", "company_total": 3000}, {"employee": "E1", "company_total": 10}]
        return [{"employee": "E1", "company_amount": 1000}, {"employee": "E2", "company_amount": 500}]

    monkeypatch.setattr(bridge.frappe, "get_all", get_all, raising=False)

    assert bridge.period_company_contributions("2026-06") == {"E1": {"si": 3010.0, "hf": 1000.0}, "E2": {"si": 0.0, "hf": 500.0}}
    assert all(filters == {"status": "Confirmed", "period": "2026-06"} for doctype, filters in calls if doctype != "Salary Slip")


def test_company_contributions_come_from_the_confirmed_slip_snapshot_first(monkeypatch):
    # 2026-10-14：确认的工资条存着当时用的单位社保 / 公积金；有快照的人不再读月度记录（社保账单生效时不写记录，会漏）
    from rayher_hr_payroll import payroll_bridge as bridge

    def get_all(doctype, filters=None, fields=None, **kwargs):
        if doctype == "Salary Slip":
            assert filters == {"docstatus": 1, "start_date": ["between", ["2026-10-01", "2026-10-31"]], "hr_amounts_v2": 1}
            return [{"employee": "E1", "hr_social_company": 3000, "hr_fund_company": 700}]
        if doctype == "Employee Social Insurance":
            return [{"employee": "E1", "company_total": 99999}, {"employee": "E2", "company_total": 2000}]
        return [{"employee": "E2", "company_amount": 500}]

    monkeypatch.setattr(bridge.frappe, "get_all", get_all, raising=False)
    assert bridge.period_company_contributions("2026-10") == {"E1": {"si": 3000.0, "hf": 700.0}, "E2": {"si": 2000.0, "hf": 500.0}}
