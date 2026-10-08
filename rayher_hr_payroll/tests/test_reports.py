from decimal import Decimal
from types import SimpleNamespace

import pytest

try:
    from rayher_hr_payroll.report.rd_allocation_matrix.rd_allocation_matrix import (
        build_allocation_matrix,
        build_foreign_allocation_matrix_lines,
        enrich_allocation_lines_with_snapshot_accounts,
    )
    from rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import (
        build_timesheet_exception_rows,
    )
    _REPORT_PACKAGE = "rayher_hr_payroll.report"
except ModuleNotFoundError:
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix.rd_allocation_matrix import (
        build_allocation_matrix,
        build_foreign_allocation_matrix_lines,
        enrich_allocation_lines_with_snapshot_accounts,
    )
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import (
        build_timesheet_exception_rows,
    )
    _REPORT_PACKAGE = "rayher_hr_payroll.rayher_hr_payroll.report"


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
    monkeypatch.setattr(mod, "_require_finance_access", lambda: None)
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
    monkeypatch.setattr(mod, "_require_finance_access", lambda: None)
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
    monkeypatch.setattr(mod, "_require_finance_access", lambda: None)
    monkeypatch.setattr(mod, "_foreign_matrix_lines_for_month", lambda year, month: [])

    columns, rows = mod.execute({"allocation": "ALLOC-1"})

    assert columns[0]["fieldname"] == "period"
    assert rows[0]["period"] == "2026-06"


def test_matrix_report_year_month_loads_only_requested_foreign_month(monkeypatch):
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    called = []

    class FakeFrappe:
        _ = staticmethod(lambda text: text)

        def get_list(self, doctype, **kwargs):
            assert doctype == "RD Cost Allocation"
            return []

    monkeypatch.setattr(mod, "_get_frappe", lambda: FakeFrappe())
    monkeypatch.setattr(mod, "_require_finance_access", lambda: None, raising=False)
    monkeypatch.setattr(
        mod,
        "_foreign_matrix_lines_for_month",
        lambda year, month: called.append((year, month)) or [],
    )

    mod.execute({"year": 2026, "month": 6, "stage": "all"})

    assert called == [(2026, 6)]


def test_matrix_report_year_month_queries_only_same_month_domestic_allocation(monkeypatch):
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    captured = {}

    class FakeFrappe:
        _ = staticmethod(lambda text: text)

        def get_list(self, doctype, filters=None, limit_page_length=None, **kwargs):
            assert doctype == "RD Cost Allocation"
            captured["filters"] = filters
            captured["limit_page_length"] = limit_page_length
            return []

    monkeypatch.setattr(mod, "_get_frappe", lambda: FakeFrappe())
    monkeypatch.setattr(mod, "_require_finance_access", lambda: None, raising=False)
    monkeypatch.setattr(mod, "_foreign_matrix_lines_for_month", lambda year, month: [])
    monkeypatch.setattr(
        mod,
        "_allocation_names_for_year",
        lambda frappe, year: (_ for _ in ()).throw(AssertionError("annual query must not run")),
    )

    mod.execute({"year": 2026, "month": 6, "stage": "all"})

    assert captured["filters"] == {
        "year": 2026,
        "month": 6,
        "docstatus": 1,
    }
    assert captured["limit_page_length"] == 1


def test_matrix_report_stops_before_business_reads_when_finance_access_is_denied(monkeypatch):
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    class AccessDenied(Exception):
        pass

    business_reads = []

    class FakeFrappe:
        def get_list(self, *args, **kwargs):
            business_reads.append((args, kwargs))
            raise AssertionError("business read must not run")

    monkeypatch.setattr(mod, "_get_frappe", lambda: FakeFrappe())
    monkeypatch.setattr(
        mod,
        "_require_finance_access",
        lambda: (_ for _ in ()).throw(AccessDenied()),
        raising=False,
    )

    with pytest.raises(AccessDenied):
        mod.execute({"year": 2026, "month": 6})

    assert business_reads == []


def test_matrix_report_finance_wrapper_uses_finance_roles(monkeypatch):
    import sys

    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    checked = []
    fake_guards = SimpleNamespace(
        RD_FINANCE_ROLES=("System Manager", "Accounts User"),
        require_rd_access=lambda roles: checked.append(roles),
    )
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.api._guards", fake_guards)

    mod._require_finance_access()

    assert checked == [fake_guards.RD_FINANCE_ROLES]



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


def test_foreign_matrix_direct_cost_uses_the_period_stage_when_given():
    sources = [{"voucher_no": "V1", "account_level_3": "\u5883\u5916", "amount": 80, "allocation_type": "project", "direct_project": "RD20"}]
    info = {"RD20": {"rd_stage": "", "period_stage": "capitalized"}}

    rows = build_foreign_allocation_matrix_lines(sources, [], info)

    assert rows[0]["project_stage"] == "capitalized"
    assert build_foreign_allocation_matrix_lines(sources, [], {"RD20": {"rd_stage": "\u8d39\u7528\u5316"}})[0]["project_stage"] == "expensed"


def test_foreign_common_cost_without_hours_gets_its_own_column():
    sources = [{"voucher_no": "F-COMMON", "account_level_3": "\u5883\u5916", "amount": 100, "allocation_type": "common"}]

    rows = build_foreign_allocation_matrix_lines(sources, [], {})

    assert [(row["project"], row["project_stage"], row["allocated_amount"]) for row in rows] == [
        ("\u672a\u5206\u644a\u5883\u5916\u516c\u5171\u8d39\u7528", "unknown", 100.0),
    ]


# ---------------------------------------------------------------------------
# \u9884\u89c8\u7b5b\u9009\u6761\u4ef6\uff082026-10\uff09\uff1a\u6ca1\u6709\u5b9a\u7248\u7684\u6708\u4efd\uff0c\u56fd\u5185\u90e8\u5206\u6309\u5f53\u524d\u6570\u636e\u73b0\u7b97
# ---------------------------------------------------------------------------
def _preview_lines():
    return [
        {"parent": "PREVIEW", "voucher_no": "V1", "expense_item_name": "Travel", "account_level_3": "Travel",
         "account_level_4": "Hotel", "project": "RD01", "project_stage": "capitalized",
         "allocated_amount": 60.0, "period": "2026-07"},
        {"parent": "PREVIEW", "voucher_no": "V1", "expense_item_name": "Travel", "account_level_3": "Travel",
         "account_level_4": "Hotel", "project": "RD02", "project_stage": "expensed",
         "allocated_amount": 40.0, "period": "2026-07"},
    ]


def _matrix_with_preview(monkeypatch, filters, *, submitted=(), preview_calls=None):
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    preview_calls = preview_calls if preview_calls is not None else []
    foreign_calls = []

    class FakeDoc:
        name = "ALLOC-1"
        year = 2026
        month = 7

        def check_permission(self, ptype):
            assert ptype == "read"

    class FakeMeta:
        def has_field(self, fieldname):
            return fieldname in {"account_level_3", "account_level_4"}

    class FakeFrappe:
        _ = staticmethod(lambda text: text)

        def get_list(self, doctype, **kwargs):
            assert doctype == "RD Cost Allocation"
            return [{"name": name} for name in submitted]

        def get_doc(self, doctype, name):
            return FakeDoc()

        def get_meta(self, doctype):
            return FakeMeta()

        def get_all(self, doctype, **kwargs):
            if doctype == "RD Cost Allocation Line":
                return [{"parent": "ALLOC-1", "voucher_no": "REAL", "expense_item_name": "Real", "account_level_3": "Real",
                         "account_level_4": "", "project": "RD09", "project_stage": "expensed", "allocated_amount": 5.0}]
            return []

    def preview_domestic_lines(frappe, year, month):
        preview_calls.append((year, month))
        return _preview_lines()

    monkeypatch.setattr(mod, "_get_frappe", lambda: FakeFrappe())
    monkeypatch.setattr(mod, "_require_finance_access", lambda: None)
    monkeypatch.setattr(mod, "_preview_domestic_lines", preview_domestic_lines)
    monkeypatch.setattr(
        mod, "_foreign_matrix_lines_for_month",
        lambda year, month: foreign_calls.append((year, month)) or [
            {"voucher_no": "F1", "account_level_3": "Foreign", "account_level_4": "", "project": "RD03",
             "project_stage": "capitalized", "allocated_amount": 7.0},
        ],
    )
    columns, rows = mod.execute(filters)
    return columns, rows, preview_calls, foreign_calls


def test_matrix_report_preview_filter_builds_domestic_rows_from_the_preview(monkeypatch):
    columns, rows, preview_calls, foreign_calls = _matrix_with_preview(
        monkeypatch, {"year": 2026, "month": 7, "preview": 1},
    )

    assert preview_calls == [(2026, 7)]
    assert foreign_calls == [(2026, 7)]
    assert [column["label"] for column in columns if column.get("project")] == ["RD01", "RD02", "RD03"]
    detail = [row for row in rows if not row.get("_is_total")]
    assert [(row["period"], row["voucher_no"], row["account_level_3"], row["account_level_4"], row["row_total"]) for row in detail] == [
        ("2026-07", "F1", "Foreign", "", 7.0),
        ("2026-07", "V1", "Travel", "Hotel", 100.0),
    ]
    assert rows[-1]["_is_total"] == 1
    assert rows[-1]["row_total"] == 107.0


def test_matrix_report_preview_filter_still_applies_the_stage_filter(monkeypatch):
    columns, rows, _preview_calls, _foreign_calls = _matrix_with_preview(
        monkeypatch, {"year": 2026, "month": 7, "preview": "1", "stage": "capitalized"},
    )

    assert [column["label"] for column in columns if column.get("project")] == ["RD01", "RD03"]


@pytest.mark.parametrize("preview_value", [None, 0, "0", "", "false"])
def test_matrix_report_without_a_truthy_preview_filter_never_previews(monkeypatch, preview_value):
    filters = {"year": 2026, "month": 7}
    if preview_value is not None:
        filters["preview"] = preview_value

    _columns, rows, preview_calls, foreign_calls = _matrix_with_preview(monkeypatch, filters)

    assert preview_calls == []
    assert foreign_calls == [(2026, 7)]
    assert [row["voucher_no"] for row in rows if not row.get("_is_total")] == ["F1"]


def test_matrix_report_preview_filter_is_ignored_when_the_month_is_finalized(monkeypatch):
    _columns, rows, preview_calls, _foreign_calls = _matrix_with_preview(
        monkeypatch, {"year": 2026, "month": 7, "preview": 1}, submitted=["ALLOC-1"],
    )

    assert preview_calls == []
    assert {row["voucher_no"] for row in rows if not row.get("_is_total")} == {"REAL", "F1"}


def test_matrix_report_preview_filter_needs_year_and_month(monkeypatch):
    _columns, _rows, preview_calls, foreign_calls = _matrix_with_preview(
        monkeypatch, {"year": 2026, "preview": 1},
    )

    assert preview_calls == []
    assert len(foreign_calls) == 12


def test_preview_domestic_lines_builds_rows_from_the_calculated_document_and_refuses_failed_previews(monkeypatch):
    from rayher_hr_payroll.rd_cost import allocation_preview
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    class Boom(Exception):
        pass

    class FakeFrappe:
        _ = staticmethod(lambda text: text)

        @staticmethod
        def throw(message):
            raise Boom(message)

    doc = SimpleNamespace(
        lines=[SimpleNamespace(voucher_no="V1", expense_item_name="Hotel", project="RD01", project_stage="capitalized",
                               allocated_amount=Decimal("10.00"), account_level_3="", account_level_4="")],
        expense_snapshots=[SimpleNamespace(voucher_no="V1", expense_item="Hotel", account_level_1="R", account_level_2="O",
                                           account_level_3="Travel", account_level_4="Hotel")],
    )
    seen = []

    def ok(period, year, month):
        seen.append((period, year, month))
        return SimpleNamespace(doc=doc, error=None)

    monkeypatch.setattr(allocation_preview, "build_preview", ok)
    rows = mod._preview_domestic_lines(FakeFrappe(), 2026, 7)
    assert seen == [("2026-07", 2026, 7)]
    assert rows[0]["parent"] == "PREVIEW"
    assert rows[0]["period"] == "2026-07"
    assert (rows[0]["account_level_3"], rows[0]["account_level_4"]) == ("Travel", "Hotel")

    monkeypatch.setattr(allocation_preview, "build_preview", lambda period, year, month: None)
    assert mod._preview_domestic_lines(FakeFrappe(), 2026, 7) == []

    monkeypatch.setattr(
        allocation_preview, "build_preview",
        lambda period, year, month: SimpleNamespace(doc=None, error="duplicated labour"),
    )
    with pytest.raises(Boom, match="duplicated labour"):
        mod._preview_domestic_lines(FakeFrappe(), 2026, 7)


def test_preview_domestic_lines_surfaces_the_chinese_no_hours_message(monkeypatch):
    # 矩阵报表的预览路径用 build_preview 翻好的中文，不再带英文，也不重复加前缀。
    from rayher_hr_payroll.rd_cost import allocation_preview
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    class Boom(Exception):
        pass

    class FakeFrappe:
        _ = staticmethod(lambda text: text)

        @staticmethod
        def throw(message):
            raise Boom(message)

    no_hours = "本月还没有研发工时，费用没法分摊。请先在「研发工时填报」填工时。"
    monkeypatch.setattr(
        allocation_preview, "build_preview",
        lambda period, year, month: SimpleNamespace(doc=None, error=allocation_preview.friendly_error("project_hours total must be greater than zero")),
    )
    with pytest.raises(Boom) as excinfo:
        mod._preview_domestic_lines(FakeFrappe(), 2026, 7)
    assert str(excinfo.value) == "预览计算失败：" + no_hours

    monkeypatch.setattr(
        allocation_preview, "build_preview",
        lambda period, year, month: SimpleNamespace(doc=None, error=allocation_preview.friendly_error("odd failure")),
    )
    with pytest.raises(Boom) as excinfo:
        mod._preview_domestic_lines(FakeFrappe(), 2026, 7)
    assert str(excinfo.value) == "预览计算失败：odd failure"