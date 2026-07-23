import pytest

from rayher_hr_payroll import expense_accounts


def test_account_tree_preserves_workbook_hierarchy_and_normalizes_duplicates():
    rows = expense_accounts.account_options()

    assert rows[0] == {
        "level_1": "差旅费",
        "level_2": [
            "飞机票",
            "高铁\\火车票",
            "市内交通费",
            "乘车费",
            "住宿费",
            "出差补助",
            "过路/停车费",
            "Philippe",
            "Sabri",
        ],
    }
    assert [row["level_1"] for row in rows].count("信息技术服务费") == 1
    assert "广告宣传费" in {row["level_1"] for row in rows}
    assert "广告宣传费 " not in {row["level_1"] for row in rows}


def test_account_pair_requires_child_only_when_children_exist():
    assert expense_accounts.normalize_account_pair("办公费", "") == (
        "办公费",
        "",
        "办公费",
    )
    assert expense_accounts.normalize_account_pair("差旅费", "住宿费") == (
        "差旅费",
        "住宿费",
        "差旅费 / 住宿费",
    )

    with pytest.raises(ValueError, match="二级"):
        expense_accounts.normalize_account_pair("差旅费", "")
    with pytest.raises(ValueError, match="不匹配"):
        expense_accounts.normalize_account_pair("差旅费", "员工聚餐")
    with pytest.raises(ValueError, match="一级"):
        expense_accounts.normalize_account_pair("不存在", "")


def test_account_options_return_fresh_mutable_payloads():
    first = expense_accounts.account_options()
    second = expense_accounts.account_options()

    first[0]["level_2"].append("污染值")

    assert "污染值" not in second[0]["level_2"]
