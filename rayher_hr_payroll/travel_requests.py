"""出差申请：字段校验与规范化。

出差申请只审批"该不该去"，不填金额、不设预算；报销单和付款单可以关联它。
本模块不依赖 frappe，便于单元测试。
"""
from __future__ import annotations

from datetime import date

MAX_TRAVEL_DAYS = 366


class TravelRequestError(ValueError):
    pass


def _text(value, label, limit, *, required=False):
    text = str(value or "").strip()
    if required and not text:
        raise TravelRequestError(f"请填写{label}。")
    if len(text) > limit:
        raise TravelRequestError(f"{label}不能超过 {limit} 个字。")
    return text


def _date(value, label):
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise TravelRequestError(f"请填写{label}。")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise TravelRequestError(f"{label}格式无效。") from exc


def normalize_travel(payload):
    """Return the stored travel fields, or raise TravelRequestError with a readable message."""
    payload = payload or {}
    start = _date(payload.get("travel_start_date"), "出发日期")
    end = _date(payload.get("travel_end_date"), "返回日期")
    if end < start:
        raise TravelRequestError("返回日期不能早于出发日期。")
    days = (end - start).days + 1
    if days > MAX_TRAVEL_DAYS:
        raise TravelRequestError(f"出差天数不能超过 {MAX_TRAVEL_DAYS} 天。")
    return {
        "subject": _text(payload.get("subject"), "主题", 140, required=True),
        "travel_destination": _text(payload.get("travel_destination"), "出差地点", 140, required=True),
        "travel_start_date": start.isoformat(),
        "travel_end_date": end.isoformat(),
        "travel_days": days,
        "reason": _text(payload.get("reason"), "出差事由", 1000, required=True),
        "project": _text(payload.get("project"), "所属项目", 140) or None,
    }
