from decimal import Decimal
from types import SimpleNamespace

import pytest

from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix.rd_allocation_matrix import (
    build_allocation_matrix,
    build_foreign_allocation_matrix_lines,
    enrich_allocation_lines_with_snapshot_accounts,
)
from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import (
    build_timesheet_exception_rows,
)


def test_build_allocation_matrix_pivots_projects_to_columns():
    lines = [
        SimpleNamespace(voucher_no="V-001", account_level_3="社会保险费用（单位）", account_level_4="养老保险", project="RD-CAP", allocated_amount=Decimal("600.00")),
        SimpleNamespace(voucher_no="V-001", account_level_3="社会保险费用（单位）", account_level_4="养老保险", project="RD-EXP", allocated_amount=Decimal("400.00")),
        SimpleNamespace(voucher_no="V-001", account_level_3="社会保险费用（单位）", account_level_4="医疗保险", project="RD-CAP", allocated_amount=Decimal("120.00")),
    ]

    columns, rows = build_allocation_matrix(lines, include_total=False)

    assert [(column["label"], column["fieldname"]) for column in columns] == [
        ("Voucher No", "voucher_no"),
        ("3级费用科目", "account_level_3"),
        ("4级费用科目", "account_level_4"),
        ("RD-CAP", "project_1"),
        ("RD-EXP", "project_2"),
        ("汇总", "row_total"),
    ]
    assert rows == [
        {
            "voucher_no": "V-001",
            "account_level_3": "社会保险费用（单位）",
            "account_level_4": "养老保险",
            "project_1": Decimal("600.00"),
            "project_2": Decimal("400.00"),
            "row_total": Decimal("1000.00"),
        },
        {
            "voucher_no": "V-001",
            "account_level_3": "社会保险费用（单位）",
            "account_level_4": "医疗保险",
            "project_1": Decimal("120.00"),
            "row_total": Decimal("120.00"),
        },
    ]


def test_allocation_matrix_puts_period_first_and_keeps_months_separate():
    lines = [
        {"period": "2026-06", "voucher_no": "V-001", "account_level_3": "Travel", "account_level_4": "", "project": "RD01", "allocated_amount": Decimal("10.00")},
        {"period": "2026-07", "voucher_no": "V-001", "account_level_3": "Travel", "account_level_4": "", "project": "RD01", "allocated_amount": Decimal("20.00")},
    ]

    columns, rows = build_allocation_matrix(lines, include_total=False)

    assert (columns[0]["label"], columns[0]["fieldname"]) == ("\u65e5\u671f", "period")
    assert [row["period"] for row in rows] == ["2026-06", "2026-07"]
    assert [row["row_total"] for row in rows] == [Decimal("10.00"), Decimal("20.00")]


def test_build_timesheet_exception_rows_reports_missing_hours():
    employees = [
        SimpleNamespace(name="EMP-001", employee_name="Alice"),
        SimpleNamespace(name="EMP-002", employee_name="Bob"),
    ]
    hours_by_employee = {"EMP-001": Decimal("8.0"), "EMP-002": Decimal("0")}

    rows = build_timesheet_exception_rows(
        employees,
        hours_by_employee=hours_by_employee,
        year=2026,
        month=1,
    )

    assert rows == [
        {
            "employee": "EMP-002",
            "employee_name": "Bob",
            "exception_type": "Missing Timesheet",
            "message": "2026-01 has no submitted timesheet hours.",
        }
    ]

def test_build_unclassified_rd_rows_flags_hours_without_rd_type():
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import (
        build_unclassified_rd_rows,
    )

    logs = [
        {"employee": "EMP-1", "employee_name": "Alice", "rd_personnel_type": "全时研发", "hours": Decimal("8")},
        {"employee": "EMP-2", "employee_name": "Bob", "rd_personnel_type": None, "hours": Decimal("6")},
        {"employee": "EMP-3", "employee_name": "Cara", "rd_personnel_type": "非研发", "hours": Decimal("5")},
    ]
    rows = build_unclassified_rd_rows(logs)

    assert {r["employee"] for r in rows} == {"EMP-2", "EMP-3"}
    assert all(r["exception_type"] == "Unclassified R&D Hours" for r in rows)


def test_build_allocation_matrix_translates_static_columns():
    lines = [
        SimpleNamespace(voucher_no='V-001', account_level_3='社保', account_level_4='养老保险', project='RD-CAP', allocated_amount=Decimal('600.00')),
    ]

    columns, _rows = build_allocation_matrix(lines, translate=lambda text: f'T:{text}')

    assert columns[0]['label'] == 'T:Voucher No'
    assert columns[1]['label'] == 'T:3级费用科目'
    assert columns[2]['label'] == 'T:4级费用科目'


def test_build_timesheet_exception_rows_translates_labels_and_message_template():
    employees = [SimpleNamespace(name='EMP-002', employee_name='Bob')]

    rows = build_timesheet_exception_rows(
        employees,
        hours_by_employee={'EMP-002': Decimal('0')},
        year=2026,
        month=1,
        translate=lambda text: f'T:{text}',
    )

    assert rows[0]['exception_type'] == 'T:Missing Timesheet'
    assert rows[0]['message'] == 'T:2026-01 has no submitted timesheet hours.'


def test_build_unclassified_rd_rows_translates_labels_and_message_template():
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import (
        build_unclassified_rd_rows,
    )

    rows = build_unclassified_rd_rows(
        [{'employee': 'EMP-2', 'employee_name': 'Bob', 'rd_personnel_type': None, 'hours': Decimal('6')}],
        translate=lambda text: f'T:{text}',
    )

    assert rows[0]['exception_type'] == 'T:Unclassified R&D Hours'
    assert rows[0]['message'].startswith('T:Logged 6 h on R&D projects')
    assert rows[0]['message'].endswith('excluded from R&D allocation.')


def test_allocation_matrix_skips_blank_project_lines():
    lines = [
        SimpleNamespace(voucher_no="V-001", account_level_3="差旅费", account_level_4="", project=None, allocated_amount=Decimal("99.00")),
        SimpleNamespace(voucher_no="V-001", account_level_3="差旅费", account_level_4="", project="", allocated_amount=Decimal("88.00")),
        SimpleNamespace(voucher_no="V-001", account_level_3="差旅费", account_level_4="", project="RD-CAP", allocated_amount=Decimal("10.00")),
    ]

    columns, rows = build_allocation_matrix(lines, include_total=False)

    assert [(column["label"], column["fieldname"]) for column in columns] == [
        ("Voucher No", "voucher_no"),
        ("3级费用科目", "account_level_3"),
        ("4级费用科目", "account_level_4"),
        ("RD-CAP", "project_1"),
        ("汇总", "row_total"),
    ]
    assert rows == [{"voucher_no": "V-001", "account_level_3": "差旅费", "account_level_4": "", "project_1": Decimal("10.00"), "row_total": Decimal("10.00")}]


def test_allocation_matrix_uses_safe_project_fieldnames_and_accumulates_duplicate_cells():
    lines = [
        SimpleNamespace(voucher_no="V-001", account_level_3="差旅费", account_level_4="", project="voucher_no", allocated_amount=Decimal("10.00")),
        SimpleNamespace(voucher_no="V-001", account_level_3="差旅费", account_level_4="", project="RD CAP", allocated_amount=Decimal("2.50")),
        SimpleNamespace(voucher_no="V-001", account_level_3="差旅费", account_level_4="", project="RD CAP", allocated_amount=Decimal("7.50")),
    ]

    columns, rows = build_allocation_matrix(lines, include_total=False)

    project_columns = {column["label"]: column["fieldname"] for column in columns if column.get("project")}
    assert set(project_columns) == {"RD CAP", "voucher_no"}
    assert project_columns["voucher_no"] != "voucher_no"
    assert project_columns["RD CAP"] != "RD CAP"
    assert rows == [
        {
            "voucher_no": "V-001",
            "account_level_3": "差旅费",
            "account_level_4": "",
            project_columns["RD CAP"]: Decimal("10.00"),
            project_columns["voucher_no"]: Decimal("10.00"),
            "row_total": Decimal("20.00"),
        }
    ]


class ReportRuleError(Exception):
    pass


def report_throw(message):
    raise ReportRuleError(str(message))


def test_parse_year_month_filters_requires_both_values():
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import parse_year_month_filters

    with pytest.raises(ReportRuleError, match="Year and month filters are required"):
        parse_year_month_filters({}, throw=report_throw)


def test_parse_year_month_filters_accepts_numeric_strings():
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import parse_year_month_filters

    assert parse_year_month_filters({"year": "2026", "month": "1"}, throw=report_throw) == (2026, 1)
def test_matrix_report_checks_parent_read_permission(monkeypatch):
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    checked = []

    class FakeDoc:
        def check_permission(self, ptype):
            checked.append(ptype)

    class FakeFrappe:
        def get_doc(self, doctype, name):
            return FakeDoc()

        def get_all(self, *args, **kwargs):
            return []

        def _(self, text):
            return text

    monkeypatch.setattr(mod, "_get_frappe", lambda: FakeFrappe())
    mod.execute({"allocation": "ALLOC-1"})
    assert "read" in checked


def test_matrix_report_propagates_denied_parent_read(monkeypatch):
    import pytest
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    class Denied(Exception):
        pass

    class FakeDoc:
        def check_permission(self, ptype):
            raise Denied()

    class FakeFrappe:
        def get_doc(self, doctype, name):
            return FakeDoc()

        def get_all(self, *args, **kwargs):
            return []

        def _(self, text):
            return text

    monkeypatch.setattr(mod, "_get_frappe", lambda: FakeFrappe())
    with pytest.raises(Denied):
        mod.execute({"allocation": "ALLOC-1"})


def test_matrix_report_adds_allocation_period_to_domestic_rows(monkeypatch):
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    class FakeDoc:
        name = "ALLOC-1"
        year = 2026
        month = 6

        def check_permission(self, ptype):
            assert ptype == "read"

    class FakeMeta:
        def has_field(self, fieldname):
            return fieldname in {"account_level_3", "account_level_4"}

    class FakeFrappe:
        _ = staticmethod(lambda text: text)

        def get_doc(self, doctype, name):
            assert (doctype, name) == ("RD Cost Allocation", "ALLOC-1")
            return FakeDoc()

        def get_meta(self, doctype):
            return FakeMeta()

        def get_all(self, doctype, **kwargs):
            if doctype == "RD Cost Allocation Line":
                return [{
                    "parent": "ALLOC-1",
                    "voucher_no": "V-001",
                    "expense_item_name": "Travel",
                    "account_level_3": "Travel",
                    "account_level_4": "",
                    "project": "RD01",
                    "project_stage": "expensed",
                    "allocated_amount": Decimal("10.00"),
                }]
            if doctype == "RD Allocation Source Expense":
                return []
            raise AssertionError(doctype)

    monkeypatch.setattr(mod, "_get_frappe", lambda: FakeFrappe())
    monkeypatch.setattr(mod, "_foreign_matrix_lines_for_month", lambda year, month: [])

    columns, rows = mod.execute({"allocation": "ALLOC-1"})

    assert columns[0]["fieldname"] == "period"
    assert rows[0]["period"] == "2026-06"



def test_build_allocation_matrix_adds_stage_metadata_and_project_total_row():
    lines = [
        SimpleNamespace(voucher_no="V-001", account_level_3="社保", account_level_4="养老保险", project="RD-CAP", project_stage="capitalized", allocated_amount=Decimal("600.00")),
        SimpleNamespace(voucher_no="V-001", account_level_3="社保", account_level_4="养老保险", project="RD-EXP", project_stage="expensed", allocated_amount=Decimal("400.00")),
        SimpleNamespace(voucher_no="V-002", account_level_3="差旅费", account_level_4="", project="RD-CAP", project_stage="capitalized", allocated_amount=Decimal("120.00")),
    ]

    columns, rows = build_allocation_matrix(lines, translate=lambda text: {"Project Total": "????"}.get(text, text))

    project_columns = [column for column in columns if column.get("project")]
    assert project_columns[0]["project_stage"] == "capitalized"
    assert project_columns[1]["project_stage"] == "expensed"
    assert rows[-1]["_is_total"] == 1
    assert rows[-1]["account_level_3"] == "????"
    assert rows[-1]["account_level_4"] == ""
    assert rows[-1][project_columns[0]["fieldname"]] == Decimal("720.00")
    assert rows[-1][project_columns[1]["fieldname"]] == Decimal("400.00")


def test_allocation_matrix_stage_filter_uses_shared_accounting_views():
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as report

    lines = [
        {"project": "RD-CAP", "project_stage": "capitalized", "allocated_amount": 60},
        {"project": "RD-EXP", "project_stage": "expensed", "allocated_amount": 40},
        {"project": "RD-UNK", "project_stage": "unknown", "allocated_amount": 10},
    ]

    assert report.filter_allocation_lines_by_stage(lines, "all") == lines
    assert report.filter_allocation_lines_by_stage(lines, "capitalized") == [lines[0]]
    assert report.filter_allocation_lines_by_stage(lines, "expensed") == [lines[1]]
    assert report.filter_allocation_lines_by_stage(lines, "not-a-view") == lines


def test_allocation_matrix_adds_a_total_to_every_row():
    lines = [
        {"voucher_no": "V-001", "account_level_3": "Travel", "account_level_4": "", "project": "RD01", "allocated_amount": Decimal("12.50")},
        {"voucher_no": "V-001", "account_level_3": "Travel", "account_level_4": "", "project": "RD02", "allocated_amount": Decimal("7.50")},
        {"voucher_no": "V-002", "account_level_3": "Wages", "account_level_4": "", "project": "RD01", "allocated_amount": Decimal("30.00")},
    ]

    columns, rows = build_allocation_matrix(lines)

    assert columns[-1]["fieldname"] == "row_total"
    assert columns[-1]["label"] == "\u6c47\u603b"
    assert rows[0]["row_total"] == Decimal("20.00")
    assert rows[1]["row_total"] == Decimal("30.00")
    assert rows[-1]["row_total"] == Decimal("50.00")



def test_build_foreign_allocation_matrix_lines_keeps_three_and_four_level_accounts():
    expense_sources = [
        {
            "voucher_no": "F-COMMON",
            "account_level_3": "??",
            "account_level_4": "QIHENG DEMO OVERSEAS",
            "amount": 100,
            "allocation_type": "common",
        },
        {
            "voucher_no": "F-DIRECT",
            "account_level_3": "??",
            "account_level_4": "Sabri??",
            "amount": 50,
            "allocation_type": "project",
            "direct_project": "RD10",
        },
    ]
    time_lines = [
        {"project": "RD02", "project_stage": "expensed", "hours": 1},
        {"project": "RD06", "project_stage": "capitalized", "hours": 3},
    ]
    project_info = {
        "RD10": {"rd_stage": "expensed"},
    }

    rows = build_foreign_allocation_matrix_lines(expense_sources, time_lines, project_info)

    assert [(row["voucher_no"], row["account_level_3"], row["account_level_4"], row["project"], row["allocated_amount"]) for row in rows] == [
        ("F-COMMON", "??", "QIHENG DEMO OVERSEAS", "RD02", 25.0),
        ("F-COMMON", "??", "QIHENG DEMO OVERSEAS", "RD06", 75.0),
        ("F-DIRECT", "??", "Sabri??", "RD10", 50.0),
    ]
    assert rows[2]["project_stage"] == "expensed"



def test_enrich_allocation_lines_with_snapshot_accounts_restores_old_submitted_rows():
    lines = [
        {
            "parent": "ALLOC-1",
            "voucher_no": "119",
            "expense_item_name": "\u517b\u8001\u4fdd\u9669",
            "account_level_3": "",
            "account_level_4": "",
            "project": "RD02",
            "allocated_amount": Decimal("10.00"),
        }
    ]
    snapshots = [
        {
            "parent": "ALLOC-1",
            "voucher_no": "119",
            "account_level_1": "\u7814\u53d1\u652f\u51fa",
            "account_level_2": "\u4eba\u5458\u4eba\u5de5\u8d39\u7528",
            "account_level_3": "\u793e\u4f1a\u4fdd\u9669\u8d39\u7528\uff08\u5355\u4f4d\uff09",
            "account_level_4": "\u517b\u8001\u4fdd\u9669",
            "expense_item": "ROW-119-PENSION",
        }
    ]

    enriched = enrich_allocation_lines_with_snapshot_accounts(lines, snapshots)

    assert enriched[0]["account_level_3"] == "\u793e\u4f1a\u4fdd\u9669\u8d39\u7528\uff08\u5355\u4f4d\uff09"
    assert enriched[0]["account_level_4"] == "\u517b\u8001\u4fdd\u9669"
