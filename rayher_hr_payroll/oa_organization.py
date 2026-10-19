from rayher_hr_payroll.position_access import current_supervisors, executive_names
from dataclasses import dataclass
from typing import Callable, Mapping


EXCLUDED_MANAGERS = frozenset({"Philippe", "Sabri"})
TOP_EXECUTIVES = frozenset({"演示员工21", "演示员工29"})


# This is a department/team-supervisor map. People listed under one team are peers.
DIRECT_SUPERVISOR_BY_EMPLOYEE = {
    "演示员工132": "演示员工21", "演示员工242": "演示员工21", "演示员工150": "演示员工132", "演示员工117": "演示员工132",
    "演示员工172": "演示员工21", "演示员工107": "演示员工21", "演示员工183": "演示员工21", "演示员工235": "演示员工132",
    "演示员工38": "演示员工21", "演示员工231": "演示员工21", "演示员工186": "演示员工132", "演示员工212": "演示员工242",
    "演示员工142": "演示员工132", "演示员工234": "演示员工242", "演示员工228": "演示员工21", "演示员工112": "演示员工132",
    "演示员工245": "演示员工241", "演示员工108": "演示员工21", "演示员工18": "演示员工21", "演示员工208": "演示员工132",
    "演示员工238": "演示员工21", "演示员工246": "演示员工132", "演示员工248": "演示员工108", "演示员工187": "演示员工183",
    "演示员工159": "演示员工172", "演示员工134": "演示员工132", "演示员工16": "演示员工29", "演示员工205": "演示员工108",
    "演示员工244": "演示员工108", "演示员工240": "演示员工132", "南通工厂7": "演示员工21", "演示员工233": "演示员工132",
    "演示员工145": "演示员工172", "演示员工206": "演示员工108", "演示员工158": "演示员工155", "演示员工184": "演示员工132",
    "演示员工207": "演示员工21", "演示员工239": "演示员工242", "演示员工30": "演示员工21", "演示员工221": "演示员工108",
    "演示员工161": "演示员工21", "演示员工218": "演示员工21", "演示员工227": "演示员工108", "演示员工202": "演示员工155",
    "演示员工220": "演示员工132", "演示员工241": "演示员工21", "演示员工225": "演示员工21", "演示员工224": "演示员工155",
    "演示员工236": "演示员工21", "演示员工217": "演示员工108", "演示员工210": "演示员工108", "演示员工19": "演示员工16",
    "演示员工214": "演示员工241", "演示员工211": "演示员工242", "演示员工243": "演示员工21", "演示员工232": "演示员工242",
    "演示员工178": "演示员工21", "演示员工229": "演示员工132", "演示员工216": "演示员工21", "演示员工213": "演示员工155",
    "演示员工209": "演示员工218", "演示员工32": "演示员工16", "演示员工237": "演示员工21", "演示员工203": "演示员工21",
    "演示员工155": "演示员工21", "演示员工230": "演示员工155", "演示员工109": "演示员工155", "演示员工201": "演示员工155",
    "演示员工219": "演示员工155", "演示员工226": "演示员工155", "演示员工215": "演示员工21", "演示员工204": "演示员工108",
    "演示员工13": "演示员工16", "演示员工222": "演示员工108", "演示员工223": "演示员工241", "演示员工247": "演示员工218",
    "演示员工10": "演示员工21",
}


class OrganizationResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class SupervisorResolution:
    decision: str
    supervisor_name: str = ""
    user_id: str = ""
    traversed: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ExecutiveResolution:
    executive_name: str
    user_id: str
    traversed: tuple[str, ...] = ()


def _clean(value):
    return str(value or "").strip()


def direct_supervisor_name(employee_name, mapping=None):
    employee = _clean(employee_name)
    supervisors = current_supervisors() if mapping is None else mapping
    if employee not in supervisors:
        raise OrganizationResolutionError(f"员工 {employee or '<空>'} 未配置部门主管")
    return _clean(supervisors[employee])


def resolve_top_executive(
    employee_name: str,
    resolve_user: Callable[[str], str | None],
    *,
    mapping: Mapping[str, str] | None = None,
) -> ExecutiveResolution:
    employee = _clean(employee_name)
    supervisors = current_supervisors() if mapping is None else mapping
    if not employee:
        raise OrganizationResolutionError("员工姓名不能为空")
    if employee in executive_names():
        user_id = _clean(resolve_user(employee))
        if not user_id:
            raise OrganizationResolutionError(f"高管 {employee} 没有关联可用账号")
        return ExecutiveResolution(employee, user_id)

    current = employee
    traversed = []
    visited = {employee}
    while current:
        if current not in supervisors:
            raise OrganizationResolutionError(
                f"员工 {employee} 的主管链未连接到副总经理或总经理"
            )
        current = _clean(supervisors[current])
        if not current or current == "BOARD":
            raise OrganizationResolutionError(
                f"员工 {employee} 的主管链未连接到副总经理或总经理"
            )
        if current in visited:
            chain = " -> ".join([*traversed, current])
            raise OrganizationResolutionError(f"组织主管配置存在循环：{chain}")
        visited.add(current)
        traversed.append(current)
        if current in executive_names():
            user_id = _clean(resolve_user(current))
            if not user_id:
                raise OrganizationResolutionError(f"高管 {current} 没有关联可用账号")
            return ExecutiveResolution(current, user_id, tuple(traversed))

    raise OrganizationResolutionError(f"员工 {employee} 的主管链无法解析")


def resolve_stage_two_supervisor(
    employee_name: str,
    resolve_user: Callable[[str], str | None],
    *,
    mapping: Mapping[str, str] | None = None,
) -> SupervisorResolution:
    employee = _clean(employee_name)
    supervisors = current_supervisors() if mapping is None else mapping
    if not employee:
        raise OrganizationResolutionError("员工姓名不能为空")
    if employee in executive_names():
        return SupervisorResolution(
            decision="skip",
            supervisor_name=employee,
            user_id=_clean(resolve_user(employee)),
            reason="applicant_is_top_executive",
        )

    current = direct_supervisor_name(employee, supervisors)
    traversed = []
    visited = {employee}
    while current:
        if current in visited:
            chain = " -> ".join([*traversed, current])
            raise OrganizationResolutionError(f"组织主管配置存在循环：{chain}")
        visited.add(current)
        traversed.append(current)

        if current in executive_names():
            return SupervisorResolution(
                decision="skip",
                supervisor_name=current,
                user_id=_clean(resolve_user(current)),
                traversed=tuple(traversed),
                reason="reached_top_executive",
            )

        user_id = "" if current in EXCLUDED_MANAGERS else _clean(resolve_user(current))
        if user_id:
            return SupervisorResolution(
                decision="approve",
                supervisor_name=current,
                user_id=user_id,
                traversed=tuple(traversed),
                reason="enabled_supervisor",
            )

        if current not in supervisors:
            raise OrganizationResolutionError(
                f"主管 {current} 没有可用账号，且未配置上一级部门主管"
            )
        current = _clean(supervisors[current])

    raise OrganizationResolutionError(f"员工 {employee} 的组织主管链无法解析")