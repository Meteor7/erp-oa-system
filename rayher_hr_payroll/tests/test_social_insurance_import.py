from io import BytesIO
from decimal import Decimal

from openpyxl import Workbook

from rayher_hr_payroll.social_insurance_import import (
    parse_social_workbook,
    mask_identity,
)


def _workbook_bytes():
    wb = Workbook()
    ws = wb.active
    ws.title = "申报明细"
    ws.append([
        None, None, None, None, None, "应收金额", "个人社保合计", "单位社保合计", None,
        "基本养老保险（单位）", None, "基本养老保险（个人）", None,
        "基本医疗保险（单位）", None, "地方补充医疗（单位）", None,
        "基本医疗保险（个人）", None, "生育保险", None, "职业年金（单位）",
        None, "职业年金（个人）", None, "工伤保险（单位）", None,
        "公务员医疗补助", None, "家属统筹医疗（单位）", None,
        "家属统筹医疗（个人）", None, "失业保险（单位）", None,
        "失业保险（个人）", None, "地方补充养老（单位）", None,
    ])
    ws.append([
        "序号", "姓名", "证件号码", "费款所属期起", "费款所属期止",
        None, None, None, "缴费工资", "费率", "应缴费额", "费率", "应缴费额",
        "费率", "应缴费额", "费率", "应缴费额", "费率", "应缴费额",
        "费率", "应缴费额", "费率", "应缴费额", "费率", "应缴费额",
        "费率", "应缴费额", "费率", "应缴费额", "费率", "应缴费额",
        "费率", "应缴费额", "费率", "应缴费额", "费率", "应缴费额",
        "费率", "应缴费额",
    ])
    ws.append(["在职人员"])
    row = [None] * 39
    row[0:9] = [1, "测试员工", "110101199001010090", "2026-07", "2026-07", 3430, 1020, 2410, 10000]
    row[10], row[12], row[14], row[18], row[20] = 1600, 800, 600, 200, 50
    row[26], row[34], row[36], row[38] = 80, 80, 20, 0
    ws.append(row)
    ws.append([None, "小计"])
    ws.append(["退休人员"])
    ws.append([1, "不应读取"])
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def test_parser_reads_only_active_section_and_amounts():
    rows = parse_social_workbook(_workbook_bytes(), "2026-07")
    assert len(rows) == 1
    row = rows[0]
    assert row["excel_name"] == "测试员工"
    assert row["identity_number"] == "110101199001010090"
    assert row["contribution_base"] == Decimal("10000.00")
    assert row["employee_total"] == Decimal("1020.00")
    assert row["company_total"] == Decimal("2410.00")
    assert row["receivable_total"] == Decimal("3430.00")
    assert row["company_pension"] == Decimal("1600.00")
    assert row["employee_unemployment"] == Decimal("20.00")


def test_parser_rejects_page_period_mismatch():
    try:
        parse_social_workbook(_workbook_bytes(), "2026-08")
    except ValueError as exc:
        assert "期间" in str(exc)
    else:
        raise AssertionError("period mismatch was accepted")


def test_identity_mask_keeps_only_safe_edges():
    assert mask_identity("110101199001010090") == "4403**********1234"
    assert mask_identity("H10435642") == "H104*5642"


def test_reconcile_row_marks_company_scoped_employee_and_exact_match():
    from rayher_hr_payroll.social_insurance_import import reconcile_row
    row = parse_social_workbook(_workbook_bytes(), "2026-07")[0]
    result = reconcile_row(row, {
        "name": "EMP-1",
        "employee_name": "测试员工",
        "company": "QIHENG Demo",
        "household_registration": "广东省外城镇",
        "social_insurance_base": Decimal("10000.00"),
        "social_base_source": "员工默认基数",
    }, "QIHENG Demo")
    assert result["employee"] == "EMP-1"
    assert result["status"] == "Matched"
    assert result["original_match_status"] == "Matched"


def test_reconcile_row_rejects_cross_company_employee():
    from rayher_hr_payroll.social_insurance_import import reconcile_row
    row = parse_social_workbook(_workbook_bytes(), "2026-07")[0]
    result = reconcile_row(row, {
        "name": "EMP-1",
        "employee_name": "测试员工",
        "company": "示例研发中心",
        "household_registration": "广东省外城镇",
        "social_insurance_base": Decimal("10000.00"),
        "social_base_source": "员工默认基数",
    }, "QIHENG Demo")
    assert result["status"] == "Pending"
    assert "所属公司" in result["difference_reasons"]


def test_summary_uses_weighted_counts_not_average_percentages():
    from rayher_hr_payroll.social_insurance_import import summarize_rows
    rows = [
        {"status": "Matched", "original_match_status": "Matched", "employee": "A", "employee_total": 10, "company_total": 20, "receivable_total": 30},
        {"status": "Pending", "original_match_status": "Pending", "employee": "B", "employee_total": 5, "company_total": 10, "receivable_total": 15},
        {"status": "Pending", "original_match_status": "Pending", "employee": None, "employee_total": 1, "company_total": 2, "receivable_total": 3},
    ]
    summary = summarize_rows(rows)
    assert summary["matched_rows"] == 1
    assert summary["comparable_rows"] == 2
    assert summary["match_rate"] == 33.33
    assert summary["linked_rows"] == 2
    assert summary["automatic_link_rate"] == 66.67


def test_reconcile_uses_employee_base_instead_of_excel_base():
    from rayher_hr_payroll.social_insurance_import import reconcile_row
    row = parse_social_workbook(_workbook_bytes(), "2026-07")[0]
    result = reconcile_row(row, {
        "name": "EMP-BASE", "employee_name": "测试员工", "company": "QIHENG Demo",
        "household_registration": "广东省外城镇",
        "social_insurance_base": Decimal("5000.00"),
        "social_base_source": "员工默认基数",
    })
    assert result["status"] == "Pending"
    assert "缴费工资与员工档案社保基数不一致" in result["difference_reasons"]
    assert result["calculated"]["employee_pension"] == Decimal("400.00")


def test_reconcile_missing_household_and_company_policy_are_pending():
    from rayher_hr_payroll.social_insurance_import import reconcile_row
    row = parse_social_workbook(_workbook_bytes(), "2026-07")[0]
    missing_household = reconcile_row(row, {
        "name": "EMP-H", "employee_name": "测试员工", "company": "QIHENG Demo",
        "household_registration": "", "social_insurance_base": Decimal("10000.00"),
        "social_base_source": "员工默认基数",
    })
    assert "户口信息未维护" in missing_household["difference_reasons"]
    missing_policy = reconcile_row(row, {
        "name": "EMP-SH", "employee_name": "测试员工", "company": "示例研发中心",
        "household_registration": "广东省外城镇", "social_insurance_base": Decimal("10000.00"),
        "social_base_source": "员工默认基数",
    })
    assert "社保政策未配置" in missing_policy["difference_reasons"]


def test_period_social_base_overrides_employee_default():
    from rayher_hr_payroll.social_insurance_import import resolve_employee_bases
    employees = [{"name": "EMP-1", "default_social_insurance_base": 5000}]
    period_rows = [{"employee": "EMP-1", "contribution_base": 6000}]
    resolved = resolve_employee_bases(employees, period_rows, "2026-07")
    assert resolved[0]["social_insurance_base"] == Decimal("6000.00")
    assert resolved[0]["social_base_source"] == "2026-07月度社保记录"


def test_default_social_base_is_used_without_period_record():
    from rayher_hr_payroll.social_insurance_import import resolve_employee_bases
    resolved = resolve_employee_bases(
        [{"name": "EMP-1", "default_social_insurance_base": 5000}], [], "2026-07"
    )
    assert resolved[0]["social_insurance_base"] == Decimal("5000.00")
    assert resolved[0]["social_base_source"] == "员工默认基数"


def test_ignored_rows_stay_in_strict_match_rate_denominator():
    from rayher_hr_payroll.social_insurance_import import summarize_rows
    rows = [
        {"status": "Matched", "original_match_status": "Matched", "employee": "A"},
        {"status": "Ignored", "original_match_status": "Pending", "employee": "B"},
        {"status": "Pending", "original_match_status": "Pending", "employee": None},
    ]
    summary = summarize_rows(rows)
    assert summary["matched_rows"] == 1
    assert summary["match_rate"] == 33.33


def test_batch_activation_allows_ignored_but_requires_accepted_row():
    from rayher_hr_payroll.social_insurance_import import can_activate_rows
    matched = {"status": "Matched", "employee": "A"}
    ignored = {"status": "Ignored", "employee": None}
    pending = {"status": "Pending", "employee": "B"}
    assert can_activate_rows([matched, ignored]) is True
    assert can_activate_rows([ignored]) is False
    assert can_activate_rows([matched, pending]) is False
