import hashlib

FIXED_LEVEL_1 = "研发支出"
FIXED_LEVEL_2 = (
    "人员人工费用", "直接投入费用", "折旧费用", "无形资产摊销", "其他相关费用", "委托研发",
)
FIELDS = ("account_level_1", "account_level_2", "account_level_3", "account_level_4")

DEFAULT_PATHS = [
    ("研发支出", "人员人工费用", "工资、奖金、补助等", ""),
    ("研发支出", "人员人工费用", "社会保险费用（单位）", "养老保险"),
    ("研发支出", "人员人工费用", "社会保险费用（单位）", "医疗保险"),
    ("研发支出", "人员人工费用", "社会保险费用（单位）", "生育保险"),
    ("研发支出", "人员人工费用", "社会保险费用（单位）", "工伤保险"),
    ("研发支出", "人员人工费用", "社会保险费用（单位）", "失业保险"),
    ("研发支出", "人员人工费用", "住房公积金（单位）", ""),
    ("研发支出", "人员人工费用", "外聘人员劳务费", ""),
    ("研发支出", "直接投入费用", "研发材料", ""),
    ("研发支出", "直接投入费用", "电费", ""),
    ("研发支出", "直接投入费用", "水费", ""),
    ("研发支出", "直接投入费用", "试制模具、工艺装备开发及制造费", ""),
    ("研发支出", "直接投入费用", "不构成固定资产的样品、样机及一般测试手段购置费", ""),
    ("研发支出", "直接投入费用", "检验检测费", ""),
    ("研发支出", "直接投入费用", "仪器、设备的运行维护、调整、检验、维修等费用", ""),
    ("研发支出", "直接投入费用", "仪器、设备租赁费", ""),
    ("研发支出", "折旧费用", "仪器仪表折旧（研发）", ""),
    ("研发支出", "折旧费用", "专用设备折旧（研发）", ""),
    ("研发支出", "折旧费用", "电子设备折旧（研发）", ""),
    ("研发支出", "折旧费用", "办公家具、工具及器具折旧（研发）", ""),
    ("研发支出", "折旧费用", "使用权资产折旧（研发）", ""),
    ("研发支出", "无形资产摊销", "无形资产摊销", ""),
    ("研发支出", "其他相关费用", "差旅费", ""),
    ("研发支出", "其他相关费用", "会议费", ""),
    ("研发支出", "其他相关费用", "专家咨询费", ""),
    ("研发支出", "其他相关费用", "知识产权的申请费、注册费、代理费", ""),
    ("研发支出", "其他相关费用", "办公耗材", ""),
    ("研发支出", "其他相关费用", "职工福利费", "员工工服"),
    ("研发支出", "其他相关费用", "职工福利费", "日常零食"),
    ("研发支出", "其他相关费用", "职工福利费", "集体宿舍"),
    ("研发支出", "其他相关费用", "职工福利费", "团建活动"),
    ("研发支出", "其他相关费用", "职工福利费", "节日福利"),
    ("研发支出", "其他相关费用", "职工福利费", "员工聚餐"),
    ("研发支出", "其他相关费用", "地方补充养老（单位）", ""),
    ("研发支出", "其他相关费用", "快递费", ""),
    ("研发支出", "其他相关费用", "装修费", ""),
    ("研发支出", "其他相关费用", "资料费", ""),
    ("研发支出", "其他相关费用", "市内交通费", ""),
    ("研发支出", "其他相关费用", "搬运费", ""),
    ("研发支出", "委托研发", "境内", ""),
    ("研发支出", "委托研发", "境外", "QIHENG DEMO OVERSEAS"),
    ("研发支出", "委托研发", "境外", "Kontron AIS GmbH"),
    ("研发支出", "委托研发", "境外", "Sabri费用"),
]


def _clean(value):
    return str(value or "").strip()


def normalize_path(value):
    if isinstance(value, dict):
        values = [value.get(field) for field in FIELDS]
    else:
        values = list(value or [])
    values = (values + [""] * 4)[:4]
    return tuple(_clean(item) for item in values)


def path_dict(value):
    return dict(zip(FIELDS, normalize_path(value)))


def path_hash(value):
    return hashlib.sha256("\x1f".join(normalize_path(value)).encode("utf-8")).hexdigest()


def validate_fixed_levels(value):
    level_1, level_2, level_3, _level_4 = normalize_path(value)
    errors = []
    if level_1 != FIXED_LEVEL_1:
        errors.append("1级费用科目必须为“研发支出”")
    if level_2 not in FIXED_LEVEL_2:
        errors.append("2级费用科目不在固定分类中")
    if not level_3:
        errors.append("3级费用科目不能为空")
    return errors


def missing_paths(rows, existing_paths):
    known = {normalize_path(path) for path in existing_paths}
    result, seen = [], set()
    for row in rows:
        path = normalize_path(row)
        if path not in known and path not in seen:
            seen.add(path)
            result.append(path)
    return result




def confirmed_new_paths(rows, existing_paths, confirmed_paths):
    for row in rows:
        errors = validate_fixed_levels(row)
        if errors:
            raise ValueError("；".join(errors))
    missing = missing_paths(rows, existing_paths)
    confirmed = {normalize_path(path) for path in (confirmed_paths or [])}
    missing_set = set(missing)
    if confirmed != missing_set:
        details = []
        if missing_set - confirmed:
            details.append("存在未确认的新费用科目")
        if confirmed - missing_set:
            details.append("确认列表包含本次明细中不存在的费用科目")
        raise ValueError("；".join(details))
    return missing

def business_category(value):
    level_2 = normalize_path(value)[1]
    return {
        "人员人工费用": "personnel",
        "直接投入费用": "direct_input",
        "折旧费用": "depreciation",
        "无形资产摊销": "amortization",
    }.get(level_2, "other")


def catalog_paths(enabled_only=True):
    import frappe
    table_exists = getattr(frappe.db, "table_exists", None)
    if not callable(table_exists) or not table_exists("RD Expense Account Path"):
        return [normalize_path(path) for path in DEFAULT_PATHS]
    filters = {"enabled": 1} if enabled_only else {}
    rows = frappe.get_all(
        "RD Expense Account Path", filters=filters, fields=list(FIELDS),
        order_by="sort_order asc, creation asc",
    )
    return [normalize_path(row) for row in rows]


def ensure_paths(paths, created_from="系统初始化"):
    import frappe
    created = []
    for value in paths:
        path = normalize_path(value)
        errors = validate_fixed_levels(path)
        if errors:
            frappe.throw("；".join(errors))
        digest = path_hash(path)
        existing = frappe.db.get_value(
            "RD Expense Account Path", {"path_hash": digest}, ["name", "enabled"], as_dict=True
        )
        if existing:
            if not existing.get("enabled"):
                frappe.throw("费用科目已禁用，不能用于新导入：{0}".format(" → ".join(part for part in path if part)))
            continue
        doc = frappe.get_doc({
            "doctype": "RD Expense Account Path",
            "path_hash": digest,
            **path_dict(path),
            "business_category": business_category(path),
            "enabled": 1,
            "created_from": created_from,
        })
        doc.insert(ignore_permissions=True)
        created.append(path)
    return created
