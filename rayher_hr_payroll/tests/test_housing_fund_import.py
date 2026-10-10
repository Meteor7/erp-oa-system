from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook

from rayher_hr_payroll.housing_fund_import import (
    canonical_period,
    missing_from_excel,
    parse_housing_workbook,
    rates_from_amounts,
    reconcile_fund_row,
    resolve_fund_employees,
    summarize_fund_rows,
)
from rayher_hr_payroll.hr_contributions import housing_fund_amounts


def _workbook(rows, header=("姓名", "证件号码", "缴存基数", "个人缴存额", "单位缴存额"), lead=()):
    book = Workbook()
    sheet = book.active
    for row in lead:
        sheet.append(row)
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def _employee(**overrides):
    base = {
        "name": "EMP-1", "employee_name": "员工甲", "company": "Rayher", "id_card_number_cn": "110101199001010070",
        "housing_fund_base": Decimal("10000.00"), "housing_base_source": "员工默认基数",
        "employee_rate": Decimal("7"), "company_rate": Decimal("7"),
    }
    base.update(overrides)
    return base


def _row(**overrides):
    row = {
        "row_number": 1, "source_row": 2, "excel_name": "员工甲", "identity_number": "110101199001010070", "period": "2026-10",
        "contribution_base": Decimal("10000.00"), "employee_amount": Decimal("700.00"), "company_amount": Decimal("700.00"), "total_amount": None,
    }
    row.update(overrides)
    return row


def test_period_accepts_the_common_spellings():
    for text in ("2026-10", "2026/10", "2026年10月", "202610", "2026.10", date(2026, 10, 9)):
        assert canonical_period(text) == "2026-10"
    for text in ("2026-13", "十月", ""):
        with pytest.raises(ValueError):
            canonical_period(text)


def test_parse_finds_columns_by_header_name_not_position():
    content = _workbook(
        [("员工甲", "110101199001010070", 10000, 700, 700, "2026-10")],
        header=("姓名", "证件号码", "缴存基数（元）", "个人缴存额", "单位缴存额", "缴存年月"),
        lead=[("某公司公积金汇缴明细",), ()],
    )
    rows = parse_housing_workbook(content)
    assert len(rows) == 1
    assert rows[0]["period"] == "2026-10"
    assert rows[0]["contribution_base"] == Decimal("10000.00")
    assert rows[0]["employee_amount"] == Decimal("700.00") and rows[0]["company_amount"] == Decimal("700.00")
    assert rows[0]["source_row"] == 4


def test_parse_derives_company_amount_from_the_monthly_total():
    content = _workbook([("员工甲", "110101199001010070", "10,000.00", "700.00", "1,400.00")],
                        header=("职工姓名", "身份证号", "缴存基数", "个人缴存额", "月缴存额"))
    rows = parse_housing_workbook(content, "2026-10")
    assert rows[0]["company_amount"] == Decimal("700.00")
    assert rows[0]["total_amount"] == Decimal("1400.00")


def test_parse_skips_total_rows_and_blank_lines():
    content = _workbook([("员工甲", "110101199001010070", 10000, 700, 700), (None, None, None, None, None), ("合计", None, 10000, 700, 700)])
    assert len(parse_housing_workbook(content, "2026-10")) == 1


def test_parse_needs_a_period_from_somewhere():
    content = _workbook([("员工甲", "110101199001010070", 10000, 700, 700)])
    with pytest.raises(ValueError, match="期间"):
        parse_housing_workbook(content)
    with pytest.raises(ValueError, match="不一致"):
        parse_housing_workbook(_workbook([("员工甲", "110101199001010070", 10000, 700, 700, "2026-09")],
                                         header=("姓名", "证件号码", "缴存基数", "个人缴存额", "单位缴存额", "缴存年月")), "2026-10")


def test_parse_explains_a_workbook_without_the_expected_header():
    with pytest.raises(ValueError, match="表头"):
        parse_housing_workbook(_workbook([("a", "b")], header=("甲", "乙")), "2026-10")


def test_a_row_that_agrees_with_the_archive_is_matched():
    result = reconcile_fund_row(_row(), _employee())
    assert result["status"] == "Matched" and result["difference_reasons"] == ""
    assert result["calculated"] == {"employee_amount": Decimal("700.00"), "company_amount": Decimal("700.00")}
    assert result["difference_total"] == Decimal("0.00")


def test_a_different_base_is_pending_with_the_amount_difference():
    row = _row(contribution_base=Decimal("12000.00"), employee_amount=Decimal("840.00"), company_amount=Decimal("840.00"))
    result = reconcile_fund_row(row, _employee())
    assert result["status"] == "Pending"
    assert "Excel缴存基数与员工档案公积金基数不一致" in result["difference_reasons"]
    assert result["difference_total"] == Decimal("280.00")


def test_an_employee_paid_at_a_different_rate_is_flagged_even_when_the_base_matches():
    row = _row(employee_amount=Decimal("500.00"))
    result = reconcile_fund_row(row, _employee())
    assert result["difference_reasons"] == "个人缴存额与后台计算不一致"
    assert result["difference_total"] == Decimal("-200.00")


def test_a_monthly_record_with_its_own_rate_is_what_the_excel_is_compared_with():
    employee = resolve_fund_employees(
        [{"name": "EMP-1", "employee_name": "员工甲", "company": "Rayher", "default_housing_fund_base": 9000}],
        [{"employee": "EMP-1", "contribution_base": 10000, "employee_rate": 5, "company_rate": 7}], "2026-10",
    )[0]
    assert employee["housing_base_source"] == "2026-10月度公积金记录"
    assert reconcile_fund_row(_row(employee_amount=Decimal("500.00")), employee)["status"] == "Matched"


def test_an_employee_without_an_archive_base_cannot_be_compared():
    employee = resolve_fund_employees([{"name": "EMP-1", "employee_name": "员工甲", "company": "Rayher"}], [], "2026-10")[0]
    result = reconcile_fund_row(_row(), employee)
    assert result["status"] == "Pending"
    assert result["difference_reasons"] == "员工档案公积金基数未维护"
    assert result["calculated"] == {}


def test_an_unlinked_row_stays_pending_with_the_reason():
    result = reconcile_fund_row(_row(), None, "证件号码和姓名均无法关联员工")
    assert result["status"] == "Pending" and result["employee"] is None
    assert result["difference_reasons"] == "证件号码和姓名均无法关联员工"


def test_the_same_identity_with_another_name_is_pending():
    result = reconcile_fund_row(_row(excel_name="员工乙"), _employee())
    assert result["difference_reasons"] == "证件号码一致但姓名不同"


def test_an_inconsistent_total_in_the_excel_is_reported():
    result = reconcile_fund_row(_row(total_amount=Decimal("1500.00")), _employee())
    assert result["difference_reasons"] == "Excel内部合计不一致"


def test_people_with_a_base_but_not_in_the_excel_are_reported():
    employees = [_employee(name="EMP-1"), _employee(name="EMP-2"), _employee(name="EMP-3", housing_fund_base=Decimal("0"))]
    assert [e["name"] for e in missing_from_excel(employees, {"EMP-1"})] == ["EMP-2"]


def test_rates_derived_from_confirmed_amounts_reproduce_the_excel():
    employee_rate, company_rate = rates_from_amounts(Decimal("12400"), Decimal("620.00"), Decimal("868.00"))
    amounts = housing_fund_amounts(Decimal("12400"), employee_rate, company_rate)
    assert (amounts["employee_amount"], amounts["company_amount"]) == (Decimal("620.00"), Decimal("868.00"))
    assert rates_from_amounts(Decimal("0"), 1, 1) == (Decimal("7"), Decimal("7"))


def test_summary_counts_excel_rows_separately_from_missing_people():
    rows = [
        {"row_type": "excel", "employee": "A", "status": "Matched", "original_match_status": "Matched", "employee_amount": 700, "company_amount": 700},
        {"row_type": "excel", "employee": None, "status": "Pending", "original_match_status": "Pending", "employee_amount": 500, "company_amount": 500},
        {"row_type": "missing", "employee": "B", "status": "Pending", "original_match_status": "Pending", "employee_amount": 0, "company_amount": 0},
    ]
    summary = summarize_fund_rows(rows)
    assert (summary["total_rows"], summary["matched_rows"], summary["pending_rows"], summary["unlinked_rows"], summary["missing_rows"]) == (2, 1, 2, 1, 1)
    assert summary["employee_total"] == Decimal("1200.00") and summary["receivable_total"] == Decimal("2400.00")
    assert summary["match_rate"] == 50.0
