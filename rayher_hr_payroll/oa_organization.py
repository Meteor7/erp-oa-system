from dataclasses import dataclass
from typing import Callable, Mapping


EXCLUDED_MANAGERS = frozenset({"Philippe", "Sabri"})
TOP_EXECUTIVES = frozenset({"演示人员Hf4b020", "演示人员H57af9a"})


# This is a department/team-supervisor map. People listed under one team are peers.
DIRECT_SUPERVISOR_BY_EMPLOYEE = {
    # C-level and excluded organization nodes.
    "演示人员Hf4b020": "BOARD",
    "演示人员H57af9a": "BOARD",
    "Philippe": "演示人员Hf4b020",
    "Sabri": "演示人员Hf4b020",

    # R&D: IP and business-unit branches.
    "演示人员Ha2d9f4": "演示人员Hf4b020",
    "演示人员Hf146b2": "演示人员Ha2d9f4",
    "演示人员He95afb": "Sabri",
    "演示人员H4a66a5": "Sabri",

    # R&D: Mechanics.
    "演示人员H435ea7": "Philippe",
    "演示人员Hf31bac": "演示人员H435ea7",
    "演示人员H2c5e55": "演示人员H435ea7",
    "演示人员Ha666d2": "演示人员H435ea7",
    "演示人员Hc91876": "演示人员H435ea7",
    "演示人员Hd89aca": "演示人员H435ea7",

    # R&D: Electric.
    "演示人员H85b69f": "Philippe",
    "演示人员Hd7a708": "演示人员H85b69f",
    "演示人员H797f24": "演示人员H85b69f",

    # R&D: Optics/process.
    "演示人员H64d259": "Philippe",
    "演示人员Hb7788d": "演示人员H64d259",
    "演示人员H138f2f": "演示人员H64d259",
    "演示人员H08e141": "演示人员H64d259",
    "演示人员Hdda596": "演示人员H64d259",
    "演示人员H58dbfc": "演示人员H64d259",

    # R&D: Algorithm.
    "演示人员H638030": "Philippe",
    "演示人员Hc1fd05": "演示人员H638030",
    "演示人员Hba0059": "演示人员H638030",
    "演示人员H9e5efa": "演示人员H638030",
    "演示人员H17c1f4": "演示人员H638030",
    "演示人员H5ecd5c": "演示人员H638030",
    "演示人员H533990": "演示人员H638030",
    "演示人员Hfc65a4": "演示人员H638030",
    "演示人员Heb7874": "演示人员H638030",
    "演示人员Hfbc2f0": "演示人员H638030",

    # R&D: Software and test.
    "演示人员He1b926": "Philippe",
    "演示人员Ha1d1f6": "演示人员He1b926",
    "演示人员H131256": "演示人员He1b926",
    "演示人员H5fe8c6": "演示人员He1b926",
    "演示人员H661fb2": "演示人员He1b926",
    "演示人员H4707eb": "演示人员He1b926",
    "演示人员Hf82881": "演示人员He1b926",
    "演示人员H865633": "演示人员He1b926",
    "演示人员H61d48c": "演示人员He1b926",
    "演示人员Hdcbae0": "演示人员He1b926",
    "演示人员Heb905e": "演示人员He1b926",
    "演示人员Hdf3882": "演示人员He1b926",
    "演示人员Hc76601": "演示人员He1b926",
    "演示人员H1f34f2": "演示人员He1b926",
    "演示人员H0edfa3": "演示人员He1b926",

    # Active R&D staff not shown under a named leaf team on the supplied chart.
    "演示人员H7e2c07": "Philippe",
    "演示人员Haf2449": "Philippe",

    # AI branch under Operation.
    "演示人员H7188e9": "演示人员Hf4b020",
    "演示人员H85c4c3": "演示人员H7188e9",
    "演示人员H5d15fc": "演示人员H7188e9",
    "演示人员H5b7816": "演示人员H7188e9",
    # Operation/manufacturing/supply-chain branches.
    "演示人员Hb2957c": "演示人员Hf4b020",
    "演示人员H40c44a": "演示人员Hb2957c",
    "演示人员H0686c8": "演示人员Hb2957c",
    "演示人员H109018": "演示人员Hf4b020",
    "演示人员H122511": "演示人员Hf4b020",
    "演示人员Hfc0966": "演示人员Hb2957c",
    "演示人员Hbdc69a": "演示人员Hf4b020",
    "演示人员H337caa": "演示人员Hbdc69a",
    "演示人员H118c59": "演示人员Hbdc69a",
    "演示人员H01feec": "演示人员Hbdc69a",
    "演示人员He58aff": "演示人员Hbdc69a",
    "演示人员He60276": "演示人员Hbdc69a",
    "演示人员Hb76b07": "演示人员Hbdc69a",
    "演示人员H48d9f9": "演示人员Hf4b020",
    "演示人员H79b96c": "演示人员Hdd56ba",

    # Customer operation. These branches connect directly to Qingbo for approval.
    "演示人员H72d494": "演示人员Hf4b020",
    "演示人员H9a5ecf": "演示人员Hf4b020",
    "演示人员H8554d5": "演示人员Hf4b020",

    # HR/Admin and IT under Wangbo.
    "演示人员Heaf0f1": "演示人员H57af9a",
    "演示人员Habf887": "演示人员Heaf0f1",
    "演示人员H26bfa0": "演示人员Heaf0f1",
    "演示人员H75c4e2": "演示人员H57af9a",

    # Finance under Zhang Meng, then Wangbo.
    "演示人员Hdd56ba": "演示人员H57af9a",
    "演示人员Hc518b1": "演示人员Hdd56ba",
    "演示人员H0c8197": "演示人员Hdd56ba",

    # General-office and project-application staff.
    "演示人员H70623a": "演示人员H57af9a",
    "演示人员H307f00": "演示人员H57af9a",
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
    supervisors = mapping or DIRECT_SUPERVISOR_BY_EMPLOYEE
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
    supervisors = mapping or DIRECT_SUPERVISOR_BY_EMPLOYEE
    if not employee:
        raise OrganizationResolutionError("员工姓名不能为空")
    if employee in TOP_EXECUTIVES:
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
                f"员工 {employee} 的主管链未连接到演示员工37或演示员工28"
            )
        current = _clean(supervisors[current])
        if not current or current == "BOARD":
            raise OrganizationResolutionError(
                f"员工 {employee} 的主管链未连接到演示员工37或演示员工28"
            )
        if current in visited:
            chain = " -> ".join([*traversed, current])
            raise OrganizationResolutionError(f"组织主管配置存在循环：{chain}")
        visited.add(current)
        traversed.append(current)
        if current in TOP_EXECUTIVES:
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
    supervisors = mapping or DIRECT_SUPERVISOR_BY_EMPLOYEE
    if not employee:
        raise OrganizationResolutionError("员工姓名不能为空")
    if employee in TOP_EXECUTIVES:
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

        if current in TOP_EXECUTIVES:
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