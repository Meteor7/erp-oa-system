"""考勤中心首页的申请明细（get_attendance_requests，决定 2026-10-14）：一张申请一行，带人名。

最要紧的一条：把已批准的明细按类型把 month_hours 加起来，必须等于看板的“本月请假 / 本月加班”和“另有调休”
（people._leave_stats → overview_entry.month_leave → attendance_board.leave_figures）。
这里不碰数据库：同一张内存里的员工表和申请表，同时喂给考勤中心的接口和看板的取数，看两边算出来是不是同一个数。
"""
import json
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import attendance_board as board
from rayher_hr_payroll import attendance_requests as att
from rayher_hr_payroll.api import attendance_board_entry as entry
from rayher_hr_payroll.api import overview_entry
from rayher_hr_payroll.dashboard import attendance as dash_attendance
from rayher_hr_payroll.dashboard import core, people

TODAY = date(2026, 10, 15)   # 周四
STAFF = [
    {"name": "A", "employee_name": "甲", "department": "研发软件部 - RAY", "status": "Active"},
    {"name": "B", "employee_name": "乙", "department": "客服部 - RAY", "status": "Active"},
    {"name": "C", "employee_name": "丙", "department": "客服部 - RAY", "status": "Left"},          # 已离职：哪边都不算
]


def leave(name, employee, request_type, days, leave_type="", status="已完成"):
    return {"name": name, "employee": employee, "employee_name": "", "request_type": request_type, "leave_type": leave_type,
            "workflow_status": status, "current_step_label": "人事经理" if status == "待审批" else "",
            "from_date": days[0][0], "to_date": days[-1][0], "duration_hours": sum(hours for _day, hours in days),
            "attendance_days": json.dumps([{"work_date": day, "hours": hours} for day, hours in days]),
            "travel_start_date": None, "travel_end_date": None, "travel_destination": ""}


def legacy(name, employee, start, end, hours, leave_type="事假"):
    """没有逐日明细的旧申请：duration_hours 整张记在开始日期所在的月。"""
    return {**leave(name, employee, att.REQUEST_LEAVE, [(start, 0)], leave_type), "to_date": end, "attendance_days": None, "duration_hours": hours}


def trip(name, employee, start, end, status="已完成", place="上海"):
    return {"name": name, "employee": employee, "employee_name": "", "request_type": "出差申请", "leave_type": "", "workflow_status": status,
            "current_step_label": "前台办理" if status == "待办理" else "", "from_date": None, "to_date": None, "duration_hours": 0,
            "attendance_days": None, "travel_start_date": start, "travel_end_date": end, "travel_destination": place}


REQUESTS = [
    leave("L1", "A", att.REQUEST_LEAVE, [("2026-09-30", 8), ("2026-10-01", 8)], "年假"),               # 跨月：10 月只算 8
    leave("L2", "B", att.REQUEST_LEAVE, [("2026-10-15", 3)], "事假", status="已通过"),
    leave("L3", "A", att.REQUEST_LEAVE, [("2026-10-20", 8)], "病假", status="待审批"),                  # 审批中：列出来，不算数
    legacy("L4", "B", "2026-10-28", "2026-11-02", 32),                                                   # 旧申请：32 小时都在 10 月
    legacy("L5", "A", "2026-09-29", "2026-10-02", 16),                                                   # 旧申请：开始在 9 月，10 月是 0
    leave("L6", "C", att.REQUEST_LEAVE, [("2026-10-15", 8)], "年假"),                                    # 已离职
    leave("L7", "B", att.REQUEST_LEAVE, [("2026-10-16", 8)], "事假", status="草稿"),                    # 草稿：不要
    leave("L8", "A", att.REQUEST_LEAVE, [("2026-10-16", 8)], "事假", status="已撤回"),                  # 撤回：不要
    leave("C1", "B", att.REQUEST_COMP_TIME, [("2026-10-16", 8)]),
    leave("O1", "A", att.REQUEST_OVERTIME, [("2026-10-17", 6)]),                                        # 周六加班
    leave("O2", "B", att.REQUEST_OVERTIME, [("2026-10-31", 2), ("2026-11-01", 3)]),                     # 跨月：10 月只算 2
    trip("T1", "A", "2026-10-14", "2026-10-16"),
    trip("T2", "B", "2026-10-20", "2026-10-21", status="待办理"),                                       # 前台待办理 = 已批准
    trip("T3", "A", "2026-10-17", "2026-10-19", place="北京"),                                          # 周六周日不算
]


def _iso(raw):
    return raw.isoformat() if isinstance(raw, date) else str(raw or "")[:10]


def _match(row, key, condition):
    if isinstance(condition, list):
        op, target = condition
        current = _iso(row.get(key)) if key.endswith("_date") else row.get(key)
        if op == "in":
            return current in target
        if op == "<=":
            return current <= _iso(target)
        if op == ">=":
            return current >= _iso(target)
        raise AssertionError(op)
    return row.get(key) == condition


@pytest.fixture
def db(monkeypatch):
    def get_all(doctype, filters=None, fields=None, **_kwargs):
        table = STAFF if doctype == "Employee" else REQUESTS if doctype == "OA Approval Request" else pytest.fail(doctype)
        rows = [row for row in table if all(_match(row, key, value) for key, value in (filters or {}).items())]
        return [{field: row.get(field) for field in (fields or row)} for row in rows]

    def sql(query, args=None, as_dict=False):
        assert "FROM `tabOA Approval Request`" in query
        start, end = _iso(args["start"]), _iso(args["end"])
        found = []
        for row in REQUESTS:
            if row["employee"] not in args["employees"] or row["request_type"] not in args["types"] or row["workflow_status"] not in args["statuses"]:
                continue
            first, last = (row["travel_start_date"], row["travel_end_date"]) if row["request_type"] == args["travel"] else (row["from_date"], row["to_date"])
            if first <= end and last >= start:
                found.append(dict(row))
        return found

    monkeypatch.setattr(entry.frappe, "get_all", get_all, raising=False)
    monkeypatch.setattr(entry.frappe, "db", SimpleNamespace(sql=sql), raising=False)
    monkeypatch.setattr(entry.frappe, "_", lambda text, *args, **kwargs: text, raising=False)

    def throw(message, exc=None):
        raise (exc or ValueError)(str(message))

    monkeypatch.setattr(entry.frappe, "throw", throw, raising=False)
    monkeypatch.setattr(entry, "resolve_scope", lambda: {"level": "company", "user": "hr@tests-x.example.invalid", "employee": "", "department": ""})
    monkeypatch.setattr(entry, "_require_open", lambda: None)
    monkeypatch.setattr(entry.site_time, "today", lambda: TODAY)
    monkeypatch.setattr(entry, "resolve_monthly_calendar", lambda year, month: {
        "work_dates": [date(year, month, 1) + timedelta(days=offset) for offset in range(31)
                       if (date(year, month, 1) + timedelta(days=offset)).month == month and (date(year, month, 1) + timedelta(days=offset)).weekday() < 5]})


def home(month="2026-10", department=""):
    raw = getattr(entry.get_attendance_requests, "__wrapped__", entry.get_attendance_requests)
    return raw(month=month, department=department)


def approved_hours(rows, request_type):
    return sum(row["month_hours"] for row in rows if row["approved"] and row["request_type"] == request_type)


def one_decimal(days):
    """前端 attendanceHome.daysText 的写法（四舍五入一位小数）。"""
    return f"{Decimal(str(days)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):f}".rstrip("0").rstrip(".")


def test_the_month_totals_of_the_rows_equal_the_dashboard_cards(db):
    rows = home()["rows"]
    stats = overview_entry.month_leave([(2026, 10)])
    figures = stats["figures"]
    assert approved_hours(rows, att.REQUEST_LEAVE) == figures["leave_hours"] == 43          # 8（L1 的 10-01）+ 3 + 32（旧申请 L4）
    assert approved_hours(rows, att.REQUEST_COMP_TIME) == figures["comp_hours"] == 8
    assert approved_hours(rows, att.REQUEST_OVERTIME) == figures["overtime_hours"] == 8      # 6（周六）+ 2（O2 的 10-31）
    totals = stats["totals"]
    assert (totals["leave_days"], totals["comp_days"], totals["overtime_days"]) == (5.38, 1.0, 1.0)
    # 看板卡片上的数字（一位小数）和考勤中心「N 月」四格上的数字（明细加起来 ÷ 8，一位小数）一样
    ctx = core.Ctx(user="hr@tests-x.example.invalid", roles=frozenset({"HR Manager"}), positions=frozenset({"hr_manager"}), period="2026-10", today="2026-10-15")
    card = dash_attendance.att_leave(ctx)
    assert card["value"] == one_decimal(approved_hours(rows, att.REQUEST_LEAVE) / 8) == "5.4"
    assert card["sub"] == f"另有调休 {one_decimal(approved_hours(rows, att.REQUEST_COMP_TIME) / 8)} 天" == "另有调休 1 天"
    assert dash_attendance.att_overtime(ctx)["value"] == one_decimal(approved_hours(rows, att.REQUEST_OVERTIME) / 8) == "1"
    assert people._leave_stats(ctx)["totals"]["leave_days"] == totals["leave_days"]


def test_each_row_carries_names_dates_days_and_its_month_hours(db):
    result = home()
    assert (result["level"], result["month"], result["today"], result["label"], result["headcount"]) == ("company", "2026-10", "2026-10-15", "全公司", 2)
    assert (result["start"], result["end"]) == ("2026-10-12", "2026-10-28")                  # 本周一到今天起第 14 天
    rows = {row["name"]: row for row in result["rows"]}
    assert set(rows) == {"L1", "L2", "L3", "L4", "L5", "C1", "O1", "O2", "T1", "T2", "T3"}    # 草稿、撤回、离职的人不要
    assert rows["L1"]["employee_name"] == "甲" and rows["L1"]["department_label"] == "研发软件部" and rows["L1"]["kind"] == "annual"
    assert rows["L1"]["days"] == [["2026-09-30", 8], ["2026-10-01", 8]] and rows["L1"]["month_hours"] == 8
    assert (rows["L3"]["approved"], rows["L3"]["current_step_label"], rows["L3"]["kind"]) == (False, "人事经理", "sick")
    assert rows["L4"]["month_hours"] == 32 and rows["L5"]["month_hours"] == 0
    assert rows["O2"]["kind"] == "ot" and rows["O2"]["month_hours"] == 2 and rows["O2"]["leave_type"] == ""
    # 出差：日期用出发、返回日期；只算工作日、每天 8 小时；前台待办理的算已批准
    assert (rows["T1"]["from_date"], rows["T1"]["to_date"], rows["T1"]["travel_destination"], rows["T1"]["month_hours"]) == ("2026-10-14", "2026-10-16", "上海", 24)
    assert rows["T3"]["days"] == [["2026-10-19", 8]]
    assert rows["T2"]["approved"] is True and rows["T2"]["workflow_status"] == "待办理"
    assert "2026-10-17" not in result["work_dates"] and "2026-10-19" in result["work_dates"]
    # 按开始日期排
    assert [row["from_date"] for row in result["rows"]] == sorted(row["from_date"] for row in result["rows"])


def test_another_month_takes_that_month_and_still_the_next_fourteen_days(db):
    result = home(month="2026-09")
    rows = {row["name"]: row for row in result["rows"]}
    assert result["month"] == "2026-09"
    assert rows["L1"]["month_hours"] == 8 and rows["L5"]["month_hours"] == 16                 # 9 月：L1 的 09-30，旧申请 L5 整张
    assert "T1" in rows and rows["T1"]["month_hours"] == 0                                    # 今天起 14 天里的照样在（谁不在 / 未来 14 天要用）
    stats = overview_entry.month_leave([(2026, 9)])
    assert approved_hours(result["rows"], att.REQUEST_LEAVE) == stats["figures"]["leave_hours"] == 24


def test_a_department_filter_and_bad_input(db):
    result = home(department="客服部 - RAY")
    assert result["label"] == "客服部" and result["headcount"] == 1 and result["department"] == "客服部 - RAY"
    assert {row["employee"] for row in result["rows"]} == {"B"}
    with pytest.raises(Exception, match="找不到这个部门"):
        home(department="没有这个部门 - RAY")
    for bad in ("2026-1", "2026/10", "十月", "2026-13"):
        with pytest.raises(Exception, match="月份格式不对"):
            home(month=bad)


def test_work_dates_cover_every_month_of_a_long_range(monkeypatch):
    # 修复：原来只取首尾两个月的日历
    seen = []
    monkeypatch.setattr(entry, "resolve_monthly_calendar", lambda year, month: seen.append((year, month)) or {"work_dates": [date(year, month, 2)]})
    dates = entry._work_dates(date(2026, 7, 1), date(2026, 10, 31))
    assert seen == [(2026, 7), (2026, 8), (2026, 9), (2026, 10)] and len(dates) == 4
    assert entry._months(date(2026, 12, 5), date(2027, 1, 3)) == [(2026, 12), (2027, 1)]


def test_month_hours_is_the_same_rule_as_month_window():
    first, last = date(2026, 10, 1), date(2026, 10, 31)
    for row in REQUESTS:
        if row["request_type"] == "出差申请":
            continue
        windowed = board.month_window([row], first, last)
        assert float(board.month_hours(row, first, last)) == (windowed[0]["duration_hours"] if windowed else 0), row["name"]
