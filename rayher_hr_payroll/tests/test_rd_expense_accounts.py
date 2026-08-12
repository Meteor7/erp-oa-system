import pytest

from rayher_hr_payroll.rd_expense_accounts import (
    DEFAULT_PATHS,
    FIXED_LEVEL_1,
    FIXED_LEVEL_2,
    missing_paths,
    normalize_path,
    validate_fixed_levels,
)


def test_levels_one_and_two_are_fixed_but_lower_levels_are_dynamic():
    assert FIXED_LEVEL_1 == "研发支出"
    assert "人员人工费用" in FIXED_LEVEL_2
    assert validate_fixed_levels(["研发支出", "人员人工费用", "年终一次性奖金", ""]) == []
    assert validate_fixed_levels(["管理费用", "人员人工费用", "年终一次性奖金", ""])
    assert validate_fixed_levels(["研发支出", "新增二级", "年终一次性奖金", ""])


def test_missing_paths_compares_normalized_complete_paths():
    existing = [["研发支出", "人员人工费用", "工资、奖金、补助等", ""]]
    rows = [
        {"account_level_1": " 研发支出 ", "account_level_2": "人员人工费用", "account_level_3": "工资、奖金、补助等", "account_level_4": ""},
        {"account_level_1": "研发支出", "account_level_2": "人员人工费用", "account_level_3": "年终一次性奖金", "account_level_4": ""},
        {"account_level_1": "研发支出", "account_level_2": "人员人工费用", "account_level_3": "年终一次性奖金", "account_level_4": ""},
    ]
    assert missing_paths(rows, existing) == [normalize_path(["研发支出", "人员人工费用", "年终一次性奖金", ""])]



def test_confirmed_paths_must_exactly_match_unknown_paths():
    from rayher_hr_payroll.rd_expense_accounts import DEFAULT_PATHS, confirmed_new_paths

    row = {"account_level_1": "研发支出", "account_level_2": "人员人工费用", "account_level_3": "年终一次性奖金", "account_level_4": ""}
    assert confirmed_new_paths([row], DEFAULT_PATHS, [row]) == [normalize_path(row)]
    try:
        confirmed_new_paths([row], DEFAULT_PATHS, [])
    except ValueError as error:
        assert "确认" in str(error)
    else:
        raise AssertionError("unconfirmed path must be rejected")

def test_confirmed_paths_rejects_rows_that_omit_fixed_levels():
    from rayher_hr_payroll.rd_expense_accounts import confirmed_new_paths
    with pytest.raises(ValueError, match="1级费用科目"):
        confirmed_new_paths(
            [{"account_level_3": "任意新科目", "amount": 1}],
            DEFAULT_PATHS,
            [],
        )
