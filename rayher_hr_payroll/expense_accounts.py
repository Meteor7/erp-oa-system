"""Canonical reimbursement expense-account hierarchy."""

from __future__ import annotations


EXPENSE_ACCOUNT_TREE = (
    (
        "差旅费",
        (
            "飞机票",
            "高铁\\火车票",
            "市内交通费",
            "乘车费",
            "住宿费",
            "出差补助",
            "过路/停车费",
            "Philippe",
            "Sabri",
        ),
    ),
    ("员工福利费", ("员工聚餐", "节日福利", "员工工服", "日常零食", "团建活动")),
    (
        "中介机构费",
        ("审计费", "资质认证咨询服务费", "体系认证咨询服务费", "代办服务费"),
    ),
    ("业务招待费", ("餐饮费", "乘车费")),
    ("租赁费", ("房屋", "车辆", "仪器")),
    ("市内交通费", ()),
    ("办公费", ()),
    ("保洁费", ()),
    ("快递费", ()),
    ("物业费", ()),
    ("水费", ()),
    ("电费", ()),
    ("会议费", ()),
    ("咨询费", ()),
    ("招聘费", ()),
    ("培训费", ()),
    ("维修费", ()),
    ("装修费", ()),
    ("押金/保证金", ()),
    ("燃油费", ()),
    ("商标\\专利费", ()),
    ("信息技术服务费", ()),
    ("固定资产-电子设备", ()),
    ("固定资产-办公家具、工具及器具", ()),
    ("劳保费", ()),
    ("安全生产费", ()),
    ("招投标费", ()),
    ("保险费", ()),
    ("包装费", ()),
    ("运输费", ()),
    ("装卸费", ()),
    ("广告宣传费", ()),
    ("展览费", ()),
    ("经济补偿金", ()),
    ("诉讼费", ()),
    ("其他", ()),
)

_ACCOUNT_LOOKUP = {level_1: frozenset(level_2) for level_1, level_2 in EXPENSE_ACCOUNT_TREE}


def _clean(value) -> str:
    return str(value or "").strip()


def account_options() -> list[dict[str, object]]:
    """Return a fresh JSON-safe account hierarchy."""

    return [
        {"level_1": level_1, "level_2": list(level_2)}
        for level_1, level_2 in EXPENSE_ACCOUNT_TREE
    ]


def normalize_account_pair(level_1, level_2) -> tuple[str, str, str]:
    """Validate and normalize an account pair and its compatibility label."""

    normalized_level_1 = _clean(level_1)
    normalized_level_2 = _clean(level_2)
    if not normalized_level_1 or normalized_level_1 not in _ACCOUNT_LOOKUP:
        raise ValueError("请选择有效的一级费用科目。")
    children = _ACCOUNT_LOOKUP[normalized_level_1]
    if children:
        if not normalized_level_2:
            raise ValueError("该一级费用科目必须选择二级费用科目。")
        if normalized_level_2 not in children:
            raise ValueError("一级费用科目与二级费用科目不匹配。")
        display = f"{normalized_level_1} / {normalized_level_2}"
        return normalized_level_1, normalized_level_2, display
    if normalized_level_2:
        raise ValueError("该一级费用科目没有二级费用科目。")
    return normalized_level_1, "", normalized_level_1
