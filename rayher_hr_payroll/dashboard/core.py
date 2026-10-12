"""按岗位区分的数据看板：骨架。

- `layout.py` 说每个岗位（profile）有哪些页签，每个页签放哪些块（用块的 key）。
- 每个块是一个 provider：用 `@provider(key, kind, visible=…)` 注册；`visible(ctx)` 反映它背后现有接口的真实权限，
  没权限的人拿不到这个块（返回 None，不是灰掉）；provider 返回 None 也表示"现在没东西可显示"（比如提醒没有触发）。
- 一个块出错只影响它自己：卡片 / 提醒直接略过并记在页签的 `errors` 里，图表块返回带 `error` 的占位。
- 跳转只给目标名和参数（`target(key, **params)`），目标名必须在 `targets.json` 里；前端用同一份表对应到路由。
- 结果按「用户 + 期间」缓存 60 秒，待办（`todos`）不缓存。
"""
from __future__ import annotations

import importlib
import json
import os
import time
from dataclasses import dataclass, field

TARGETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "targets.json")
CACHE_SECONDS = 60
TONES = ("", "ok", "info", "warn", "bad", "hot")

# 提供者所在的模块；每个模块 import 时用 @provider 注册自己的块。模块不存在就跳过（集成测试会检查布局里的每个 key 都有提供者）。
PROVIDER_MODULES = (
    "rayher_hr_payroll.dashboard.money",
    "rayher_hr_payroll.dashboard.people",
    "rayher_hr_payroll.dashboard.timesheet",
    "rayher_hr_payroll.dashboard.procurement",
    "rayher_hr_payroll.dashboard.personal",
    "rayher_hr_payroll.dashboard.team",
    "rayher_hr_payroll.dashboard.attendance",
    "rayher_hr_payroll.dashboard.projects",
)


class DashboardError(Exception):
    pass


# ---------------------------------------------------------------- 目标表
_TARGETS = None


def load_targets():
    global _TARGETS
    if _TARGETS is None:
        with open(TARGETS_PATH, encoding="utf-8") as handle:
            _TARGETS = json.load(handle)["targets"]
    return _TARGETS


def target(key, **params):
    """校验目标名和参数名都在 targets.json 里，返回 {"key", "params"}。值为 None 的参数丢掉。"""
    spec = load_targets().get(key)
    if spec is None:
        raise DashboardError(f"未知的看板目标：{key}")
    clean = {name: str(value) for name, value in params.items() if value is not None and value != ""}
    extra = set(clean) - set(spec.get("params") or [])
    if extra:
        raise DashboardError(f"目标 {key} 不接受参数：{sorted(extra)}")
    return {"key": key, "params": clean}


# ---------------------------------------------------------------- 条目构造
def _checked_target(value):
    if value is None:
        return None
    if isinstance(value, dict) and "key" in value:
        target(value["key"], **(value.get("params") or {}))
        return {"key": value["key"], "params": dict(value.get("params") or {})}
    raise DashboardError("target 必须是 target(...) 的返回值")


def kpi(key, label, value, unit="", sub="", tone="", to=None, hint="", preview=False):
    assert tone in TONES, tone
    return {"key": key, "label": label, "value": str(value), "unit": unit, "sub": sub, "tone": tone,
            "target": _checked_target(to), "hint": hint, "preview": bool(preview)}


def alert(key, tone, title, sub="", go="", to=None):
    assert tone in ("bad", "warn", "info"), tone
    return {"key": key, "tone": tone, "title": title, "sub": sub, "go": go, "target": _checked_target(to)}


def todo_item(kind, title, sub="", btn="去处理", tone="info", to=None):
    return {"kind": kind, "title": title, "sub": sub, "btn": btn, "tone": tone, "target": _checked_target(to)}


def bar_row(label, value, pct, tone=""):
    return {"label": label, "value": str(value), "pct": max(0, min(100, round(float(pct or 0), 1))), "tone": tone}


def col_row(label, value, pct, last=False):
    return {"label": label, "value": str(value), "pct": max(0, min(100, round(float(pct or 0), 1))), "last": bool(last)}


def stack_row(label, value, pct, color):
    return {"label": label, "value": str(value), "pct": max(0, min(100, round(float(pct or 0), 1))), "color": color}


def list_row(label, sub="", value="", tone="", to=None):
    return {"label": label, "sub": sub, "value": str(value), "tone": tone, "target": _checked_target(to)}


# ---------------------------------------------------------------- 明细（点指标卡 / 提醒进去看到的清单）
# 合计类的数字（费用合计、审批卡点、付款审批中、考勤天数……）背后是好几张表，没有一个现成的页面能列出“正好是这些”。
# 明细就是同一个数字的清单：用同一份数据算，逐条列出来，每一行再点进真实的单据。清单的条数 / 合计一定等于指标卡上的数字。
DRILL_PREFIX = "drill."


def drill_to(item, ctx):
    return target("drill", item=item, period=ctx.period)


def drill(key, title, columns, rows, summary="", note=""):
    """columns：[(标题, 对齐)]，对齐 "" 或 "r"；rows：drill_row(...) 的列表；summary：清单合计那一句，和指标卡上的数字对得上。"""
    return {"key": key, "title": title, "summary": summary, "note": note, "rows": list(rows),
            "columns": [{"label": column[0], "align": column[1] if len(column) > 1 else ""} for column in columns]}


def drill_row(cells, to=None, tone=""):
    assert tone in TONES, tone
    return {"cells": [str(cell) for cell in cells], "target": _checked_target(to), "tone": tone}


def _block(kind, key, title, sub, rows, more, to, hint):
    return {"key": key, "type": kind, "title": title, "sub": sub, "rows": rows, "more": more,
            "target": _checked_target(to), "hint": hint, "error": None}


def bars(key, title, rows, sub="", more="", to=None, hint=""):
    return _block("bars", key, title, sub, rows, more, to, hint)


def cols(key, title, rows, sub="", more="", to=None, hint=""):
    return _block("cols", key, title, sub, rows, more, to, hint)


def stack(key, title, rows, sub="", more="", to=None, hint=""):
    return _block("stack", key, title, sub, rows, more, to, hint)


def listing(key, title, rows, sub="", more="", to=None, hint=""):
    return _block("list", key, title, sub, rows, more, to, hint)


def calendar(key, title, days, people, totals, sub="", more="", to=None, hint=""):
    """日历块：行 = 人，列 = 天。days [{date, label, day, weekday, off_day}]；
    people [{name, cells: [None | {kind, pending}]}]（每天一格）；totals [{off, present}]（每天不在岗 / 在岗人数）。"""
    block = _block("calendar", key, title, sub, [], more, to, hint)
    block.update(days=list(days), people=list(people), totals=list(totals))
    return block


def money_wan(amount):
    """金额 → (数字, 单位)：不到 1 万按元，其余按万保留一位小数。"""
    value = float(amount or 0)
    if abs(value) >= 10000:
        return f"{value / 10000:,.1f}", "万"
    return f"{value:,.0f}", "元"


# ---------------------------------------------------------------- 上下文
@dataclass
class Ctx:
    user: str
    roles: frozenset
    positions: frozenset          # 持有的岗位 key，来自 position_access.position_flags
    period: str                   # "YYYY-MM"
    today: str                    # "YYYY-MM-DD"
    employee: str = ""            # 本人的员工号（没有就空）
    department: str = ""
    has_reports: bool = False     # 有在职直接下属（“部门主管”的唯一定义）
    owns_projects: bool = False   # 是至少一个项目的负责人
    full_name: str = ""
    profile: str = "employee"
    _memo: dict = field(default_factory=dict)

    def can(self, *roles):
        return bool(self.roles & set(roles))

    def holds(self, *positions):
        return bool(self.positions & set(positions))

    def memo(self, name, fn):
        """同一次请求里，几个块共用同一个底层调用的结果。"""
        if name not in self._memo:
            self._memo[name] = fn()
        return self._memo[name]


# 岗位优先级：一个人有多个身份时，首页按优先级最高的排版；其他身份给的权限不丢（块的 visible 看真实权限）
PROFILE_ORDER = (
    ("general_manager", "general_manager"), ("vice_manager", "vice_manager"), ("finance_manager", "finance_manager"),
    ("hr_manager", "hr_manager"), ("procurement_manager", "procurement_manager"), ("pmc", "pmc"),
    ("finance_accountant", "finance_accountant"), ("finance_auditor", "finance_auditor"),
    ("production_asset_owner", "production_asset_owner"),
)
PROFILE_LABELS = {
    "general_manager": "总经理", "vice_manager": "副总经理", "finance_manager": "财务主管", "hr_manager": "人事经理",
    "procurement_manager": "采购经理", "pmc": "PMC", "finance_accountant": "总账会计", "finance_auditor": "出纳",
    "production_asset_owner": "生产主管", "dept_manager": "部门主管", "employee": "员工",
}


def resolve_profile(ctx):
    for position, profile in PROFILE_ORDER:
        if position in ctx.positions:
            return profile
    if "System Manager" in ctx.roles:
        return "general_manager"
    if ctx.has_reports:
        return "dept_manager"
    return "employee"


# ---------------------------------------------------------------- 注册表
@dataclass
class Provider:
    key: str
    kind: str                     # kpi | alert | block | todos
    fn: object
    visible: object = None
    title: str = ""               # 图表块出错时占位用


REGISTRY: dict = {}


def provider(key, kind, visible=None, title=""):
    assert kind in ("kpi", "alert", "block", "todos", "drill"), kind

    def register(fn):
        REGISTRY[key] = Provider(key, kind, fn, visible, title)
        return fn

    return register


def load_providers():
    for name in PROVIDER_MODULES:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise


# ---------------------------------------------------------------- 组装
def _run(provider_, ctx, errors):
    if provider_.visible is not None and not provider_.visible(ctx):
        return None
    try:
        return provider_.fn(ctx)
    except Exception as exc:  # 一个块失败不拖垮整页
        errors.append({"key": provider_.key, "message": str(exc)[:200]})
        if provider_.kind == "block":
            return {"key": provider_.key, "type": "bars", "title": provider_.title or provider_.key, "sub": "",
                    "rows": [], "more": "", "target": None, "hint": "", "error": "这一块暂时加载失败"}
        return None


def _fill_buckets(ctx, spec, out, errors, buckets):
    for bucket, kind in buckets:
        for key in spec.get(bucket, ()):
            provider_ = REGISTRY.get(key)
            if provider_ is None or provider_.kind != kind:
                continue
            item = _run(provider_, ctx, errors)
            if item is not None:
                out[bucket].append(item)


def get_detail_for(ctx, item):
    """一个明细清单：没有这个清单、或者当前账号看不了背后的数据，都返回 None（页面显示“看不到”，不抛内部错误）。"""
    provider_ = REGISTRY.get(DRILL_PREFIX + str(item or ""))
    if provider_ is None or provider_.kind != "drill":
        return None
    if provider_.visible is not None and not provider_.visible(ctx):
        return None
    return provider_.fn(ctx)


def build_tab(ctx, tab, include_todos=True):
    errors = []
    out = {"key": tab["key"], "label": tab["label"], "kpis": [], "alerts": [], "blocks": [], "todos": [], "sections": [], "errors": errors}
    _fill_buckets(ctx, tab, out, errors, (("kpis", "kpi"), ("alerts", "alert"), ("blocks", "block")))
    # 分段：一个页签里按小标题分几段（人事页的“人员 / 考勤”），每段自己有指标卡和图表块；没有内容的段不给。
    for section in tab.get("sections", ()):
        built = {"title": section["title"], "sub": section.get("sub", ""), "kpis": [], "blocks": []}
        _fill_buckets(ctx, section, built, errors, (("kpis", "kpi"), ("blocks", "block")))
        if built["kpis"] or built["blocks"]:
            out["sections"].append(built)
    if include_todos and tab.get("todos"):
        provider_ = REGISTRY.get("todo.queue")
        if provider_ is not None:
            out["todos"] = _run(provider_, ctx, errors) or []
    out["has_todos"] = bool(tab.get("todos"))
    out["has_alerts"] = bool(tab.get("alerts"))
    return out


def assemble(ctx, layout, include_todos=True):
    """layout：LAYOUTS[ctx.profile]。总览页签一定保留，其他页签里什么都没有就不给。"""
    tabs = []
    for tab in layout["tabs"]:
        built = build_tab(ctx, tab, include_todos)
        if tab["key"] == "overview" or built["kpis"] or built["alerts"] or built["blocks"] or built["todos"] or built["sections"]:
            tabs.append(built)
    return {
        "role": {"key": ctx.profile, "label": PROFILE_LABELS.get(ctx.profile, ctx.profile), "person": ctx.full_name,
                 "note": layout.get("note", "")},
        "period": ctx.period,
        "tabs": [{"key": tab["key"], "label": tab["label"]} for tab in tabs],
        "pages": {tab["key"]: {k: v for k, v in tab.items() if k not in ("key", "label")} for tab in tabs},
    }


# ---------------------------------------------------------------- 缓存（可在测试里替换）
def _cache_get(key):
    import frappe
    value = frappe.cache.get_value(key)
    return value


def _cache_set(key, value, ttl):
    import frappe
    frappe.cache.set_value(key, value, expires_in_sec=ttl)


def get_home_for(ctx, layouts, cache_get=None, cache_set=None, now=time.time):
    """按用户 + 期间缓存除待办以外的部分，待办每次现取。"""
    from rayher_hr_payroll.dashboard.layout import layout_for

    ctx.profile = resolve_profile(ctx)
    # 多个身份拼在一起：主岗位版式 + 每多一个身份（有下属、负责项目）多一个页签，互不覆盖。
    layout = layout_for(ctx, layouts) if layouts is None else layouts[ctx.profile]
    cache_get = cache_get or _cache_get
    cache_set = cache_set or _cache_set
    key = f"dashboard_home:{ctx.user}:{ctx.period}:{ctx.profile}:{int(ctx.has_reports)}{int(ctx.owns_projects)}"
    cached = cache_get(key)
    if cached:
        payload = json.loads(cached) if isinstance(cached, (str, bytes)) else cached
    else:
        payload = assemble(ctx, layout, include_todos=False)
        cache_set(key, json.dumps(payload, ensure_ascii=False), CACHE_SECONDS)
    todo_tabs = [tab for tab in layout["tabs"] if tab.get("todos")]
    if todo_tabs:
        provider_ = REGISTRY.get("todo.queue")
        errors = []
        items = (_run(provider_, ctx, errors) or []) if provider_ is not None else []
        for tab in todo_tabs:
            if tab["key"] in payload["pages"]:
                payload["pages"][tab["key"]]["todos"] = items
                payload["pages"][tab["key"]]["errors"] = list(payload["pages"][tab["key"]].get("errors") or []) + errors
    payload["generated_at"] = int(now())
    return payload
