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
    has_reports: bool = False     # 有在职直接下属
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
    assert kind in ("kpi", "alert", "block", "todos"), kind

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


def build_tab(ctx, tab, include_todos=True):
    errors = []
    out = {"key": tab["key"], "label": tab["label"], "kpis": [], "alerts": [], "blocks": [], "todos": [], "errors": errors}
    for bucket, kind in (("kpis", "kpi"), ("alerts", "alert"), ("blocks", "block")):
        for key in tab.get(bucket, ()):
            provider_ = REGISTRY.get(key)
            if provider_ is None or provider_.kind != kind:
                continue
            item = _run(provider_, ctx, errors)
            if item is not None:
                out[bucket].append(item)
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
        if tab["key"] == "overview" or built["kpis"] or built["alerts"] or built["blocks"] or built["todos"]:
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
    from rayher_hr_payroll.dashboard.layout import LAYOUTS as default_layouts

    layouts = layouts or default_layouts
    ctx.profile = resolve_profile(ctx)
    layout = layouts[ctx.profile]
    cache_get = cache_get or _cache_get
    cache_set = cache_set or _cache_set
    key = f"dashboard_home:{ctx.user}:{ctx.period}:{ctx.profile}"
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
