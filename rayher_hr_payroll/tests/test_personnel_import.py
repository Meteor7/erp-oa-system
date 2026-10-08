"""员工信息 Excel 批量导入（preview_employee_import / import_employees）。

用一个内存里的假 frappe 跑，不碰数据库：员工、部门、职位都放在 env 里，
写入、回滚、提交都有计数，可以直接断言「预览不写库」「失败整批撤销」。
"""
import copy
import importlib
import sys
import types
from types import SimpleNamespace

import pytest


class RuleError(Exception):
    pass


HIDDEN_USER = "person046@staff.example.invalid"


def _employee(**fields):
    base = {"status": "Active", "company": "Rayher"}
    base.update(fields)
    return base


def _env(monkeypatch, user="Administrator", roles=("System Manager",), allow_create=True):
    env = SimpleNamespace(
        store=[
            _employee(name="HR-EMP-90001", employee_number="A001", employee_name="演示员工129", department="研发软件部 - RAY",
                      designation="工程师", date_of_joining="2024-01-01", default_monthly_salary=10000.0,
                      bank_ac_no="6222000011112222", cell_number="13800000002", english_name="Zhang San"),
            _employee(name="HR-EMP-90002", employee_number="B002", employee_name="演示员工146", company="示例研发中心"),
            _employee(name="HR-EMP-90003", employee_number="C003", employee_name="演示员工157", status="Left"),
        ],
        departments=[
            {"name": "研发软件部 - RAY", "department_name": "研发软件部", "company": "Rayher"},
            {"name": "财务部 - RAY", "department_name": "财务部", "company": "Rayher"},
            {"name": "财务部 - SHGL", "department_name": "财务部", "company": "示例研发中心"},
            {"name": "旧部门 - RAY", "department_name": "旧部门", "company": "Rayher"},
        ],
        designations=["工程师", "财务主管"],
        employment_types=["劳动合同", "实习协议"],
        approvers={},
        comments=[], commits=0, rollbacks=0, fail_on=set(), snapshot=None, inserted=[], saved=[],
    )
    env.snapshot = copy.deepcopy(env.store)

    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.ValidationError = RuleError
    frappe.only_for = lambda roles_: None
    frappe.get_roles = lambda user_=None: list(roles)
    frappe.session = SimpleNamespace(user=user)
    frappe.utils = SimpleNamespace(today=lambda: "2026-10-08")
    frappe.clear_messages = lambda: None
    frappe.has_permission = lambda doctype, ptype="read", doc=None: allow_create or ptype != "create"

    def throw(message, *args, **kwargs):
        raise RuleError(str(message))

    def whitelist(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    frappe.throw = throw
    frappe.whitelist = whitelist

    def get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, **kwargs):
        if doctype == "Employee":
            rows = env.store
            if filters and "employee_number" in filters:
                wanted = {str(x).lower() for x in filters["employee_number"][1]}
                rows = [r for r in rows if str(r.get("employee_number") or "").lower() in wanted]
            return [dict(r) for r in rows]
        if doctype == "Department":
            return [dict(r) for r in env.departments]
        if doctype == "Designation":
            return list(env.designations)
        if doctype == "Employment Type":
            return list(env.employment_types)
        return []

    def get_value(doctype, filters, field=None, *args, **kwargs):
        if doctype == "OA Approval Role Assignment":
            return env.approvers.get(filters["employee"])
        if doctype == "Employee":
            for row in env.store:
                if (row.get("employee_name") == filters.get("employee_name") and row.get("status") == filters.get("status")
                        and row.get("name") != filters["name"][1]):
                    return row["name"]
        return None

    def commit():
        env.commits += 1
        env.snapshot = copy.deepcopy(env.store)

    def rollback():
        env.rollbacks += 1
        env.store[:] = copy.deepcopy(env.snapshot)

    frappe.get_all = get_all
    frappe.db = SimpleNamespace(
        exists=lambda doctype, name: doctype == "Company" and name in ("Rayher", "示例研发中心"),
        get_value=get_value, commit=commit, rollback=rollback,
    )

    class Doc:
        def __init__(self, row):
            self.row = row

        def __getattr__(self, key):
            if key == "row":
                raise AttributeError(key)
            return self.row.get(key)

        def update(self, vals):
            self.row.update(vals)

        def save(self, ignore_permissions=False):
            if self.row.get("employee_name") in env.fail_on:
                raise RuleError("模拟校验失败")
            env.saved.append(self.row["name"])

        def insert(self, ignore_permissions=False):
            if self.row.get("employee_name") in env.fail_on:
                raise RuleError("模拟校验失败")
            self.row["name"] = "HR-EMP-%05d" % (len(env.store) + 1)
            env.store.append(self.row)
            env.inserted.append(self.row["name"])

        def add_comment(self, kind, text):
            env.comments.append((kind, self.row.get("name"), text))

    def get_doc(first, name=None):
        if isinstance(first, dict):
            return Doc(dict(first))
        return Doc(next(r for r in env.store if r["name"] == name))

    frappe.get_doc = get_doc
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.api.personnel_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.personnel_entry")
    return mod, env, frappe


def _by_row(preview):
    return {row["row"]: row for row in preview["rows"]}


def _new_row(**fields):
    base = {"_row": 2, "company": "示例总部", "employee_number": "N100", "employee_name": "新员工", "date_of_joining": "2026-10-01"}
    base.update(fields)
    return base


def test_import_columns_have_unique_keys_and_labels(monkeypatch):
    mod, _env_, _frappe = _env(monkeypatch)
    keys = [column[0] for column in mod.IMPORT_COLUMNS]
    labels = [column[1] for column in mod.IMPORT_COLUMNS]
    assert len(set(keys)) == len(keys) and len(set(labels)) == len(labels)
    assert {"default_monthly_salary", "id_card_number_cn", "bank_ac_no", "social_insurance_number", "housing_fund_number"} <= mod.IMPORT_SENSITIVE_KEYS
    assert "employee_name" not in mod.IMPORT_SENSITIVE_KEYS


def test_preview_classifies_new_update_unchanged_and_never_writes(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    rows = [
        _new_row(_row=2),
        {"_row": 3, "employee_number": "A001", "designation": "财务主管", "default_monthly_salary": "12000"},
        {"_row": 4, "employee_number": "B002"},
        {"_row": 5, "employee_number": "A001-X"},
    ]
    result = mod.preview_employee_import(rows)
    by = _by_row(result)
    assert by[2]["status"] == "create"
    assert by[3]["status"] == "update"
    assert by[4]["status"] == "unchanged"
    assert by[5]["status"] == "error" and "所属单位" in by[5]["errors"][0]   # 新员工号没写所属单位
    assert result["summary"]["create"] == 1 and result["summary"]["update"] == 1 and result["summary"]["unchanged"] == 1
    assert result["summary"]["error"] == 1 and result["summary"]["total"] == 4
    # 预览只读
    assert env.inserted == [] and env.saved == [] and env.commits == 0 and env.rollbacks == 0 and env.comments == []
    # 更新行显示新旧值，敏感值被遮挡
    changes = {c["field"]: c for c in by[3]["changes"]}
    assert changes["designation"]["old"] == "工程师" and changes["designation"]["new"] == "财务主管"
    assert changes["default_monthly_salary"]["sensitive"] is True
    assert changes["default_monthly_salary"]["old"] == "••••••" and changes["default_monthly_salary"]["new"] == "••••••"
    assert "12000" not in str(by[3]) and "10000" not in str(by[3])


def test_rows_may_arrive_as_a_json_string(monkeypatch):
    import json
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import(json.dumps([_new_row()]))
    assert result["summary"]["create"] == 1
    with pytest.raises(RuleError, match="格式"):
        mod.preview_employee_import("not json")


def test_unknown_department_is_reported_per_row(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([
        _new_row(_row=2, department="不存在部"),
        _new_row(_row=3, employee_number="N101", employee_name="另一人", department="旧部门"),
        _new_row(_row=4, employee_number="N102", employee_name="第三人", department="财务部"),
    ])
    by = _by_row(result)
    assert by[2]["status"] == "error" and "部门“不存在部”" in by[2]["errors"][0]
    assert by[3]["status"] == "error"  # 不在标准部门名单里
    assert by[4]["status"] == "create"


def test_department_is_resolved_inside_the_rows_company(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([
        _new_row(_row=2, company="示例研发中心", department="研发软件部"),   # 示例研发中心没有研发软件部
        _new_row(_row=3, employee_number="N101", employee_name="二号", company="示例研发中心", department="财务部"),
    ])
    by = _by_row(result)
    assert by[2]["status"] == "error"
    assert by[3]["status"] == "create"
    assert by[3]["employee_name"] == "二号"


def test_option_fields_are_checked_against_the_existing_lists(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([
        _new_row(_row=2, designation="首席摸鱼官", employment_type="终身制", rd_personnel_type="半研发",
                 archive_status="随便", expense_account_category="杂费", household_registration="待确认", gender="未知"),
    ])
    errors = " ".join(result["rows"][0]["errors"])
    for needle in ("职位“首席摸鱼官”", "合同类型“终身制”", "研发人员类型", "归档状态", "费用科目", "户口信息", "性别"):
        assert needle in errors, needle
    ok = mod.preview_employee_import([_new_row(designation="工程师", employment_type="劳动合同", rd_personnel_type="全时研发",
                                              archive_status="待完善", expense_account_category="研发费用", household_registration="深圳", gender="女")])
    assert ok["rows"][0]["status"] == "create"


def test_duplicate_employee_number_in_the_file_marks_both_rows(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([
        _new_row(_row=2, employee_number="N100"),
        _new_row(_row=5, employee_number="n100", employee_name="另一个"),
        _new_row(_row=6, employee_number="N200", employee_name="正常"),
    ])
    by = _by_row(result)
    assert by[2]["status"] == "error" and "第 5 行" in by[2]["errors"][0]
    assert by[5]["status"] == "error" and "第 2 行" in by[5]["errors"][0]
    assert by[6]["status"] == "create"


def test_existing_employee_number_with_another_company_is_an_error(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([
        {"_row": 2, "employee_number": "A001", "company": "示例研发中心", "designation": "工程师"},
        {"_row": 3, "employee_number": "B002", "company": "示例研发中心", "english_name": "Li Si"},
        {"_row": 4, "employee_number": "C003", "company": "Rayher", "english_name": "Wang Wu"},
        {"_row": 5, "employee_number": "B002 ", "company": "示例总部"},
    ])
    by = _by_row(result)
    # B002 在文件里出现了两次：先按「文件内重复」拦
    assert by[3]["status"] == "error" and by[5]["status"] == "error"
    assert by[2]["status"] == "error" and "不一致" in by[2]["errors"][0] and "示例总部" in by[2]["errors"][0]
    assert by[4]["status"] == "update"
    only = mod.preview_employee_import([{"_row": 2, "employee_number": "B002", "company": "示例总部"}])
    assert only["rows"][0]["status"] == "error" and "不一致" in only["rows"][0]["errors"][0]


def test_company_is_required_for_new_rows_and_must_be_known(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([
        _new_row(_row=2, company=""),
        _new_row(_row=3, employee_number="N101", company="火星分公司"),
        _new_row(_row=4, employee_number="N102", employee_name="三号", company="Rayher"),
    ])
    by = _by_row(result)
    assert "所属单位" in by[2]["errors"][0]
    assert "所属单位“火星分公司”无效" in by[3]["errors"][0]
    assert by[4]["status"] == "create"


def test_new_employee_requires_number_name_and_joining_date(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([
        {"_row": 2, "company": "示例总部", "employee_name": "没员工号", "date_of_joining": "2026-10-01"},
        {"_row": 3, "company": "示例总部", "employee_number": "N1", "date_of_joining": "2026-10-01"},
        {"_row": 4, "company": "示例总部", "employee_number": "N2", "employee_name": "没入职日期"},
        {"_row": 5, "company": "示例总部", "employee_number": "N3", "employee_name": "日期坏", "date_of_joining": "2026-13-45"},
    ])
    by = _by_row(result)
    assert "员工号必填" in by[2]["errors"][0]
    assert "姓名" in by[3]["errors"][0]
    assert "入职日期" in by[4]["errors"][0]
    assert "入职日期" in by[5]["errors"][0] and by[5]["status"] == "error"


def test_dates_accept_iso_and_common_spreadsheet_spellings(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    for text in ("2026-10-01", "2026/10/1", "2026.10.01", "2026-10-01 00:00:00"):
        result = mod.preview_employee_import([_new_row(date_of_joining=text)])
        assert result["rows"][0]["status"] == "create", text
    bad = mod.preview_employee_import([_new_row(date_of_joining="十月一号")])
    assert bad["rows"][0]["status"] == "error"


def test_example_rows_from_the_template_are_blocked(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([_new_row(employee_number="示例001")])
    assert result["rows"][0]["status"] == "error" and "示例" in result["rows"][0]["errors"][0]


def test_more_than_300_rows_is_refused_by_preview_and_import(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    rows = [_new_row(_row=i + 2, employee_number="X%d" % i, employee_name="员工%d" % i) for i in range(301)]
    with pytest.raises(RuleError, match="300"):
        mod.preview_employee_import(rows)
    with pytest.raises(RuleError, match="300"):
        mod.import_employees(rows)
    assert env.inserted == [] and env.commits == 0
    # 恰好 300 行没问题
    assert mod.preview_employee_import(rows[:300])["summary"]["create"] == 300
    with pytest.raises(RuleError):
        mod.preview_employee_import([])


def test_sensitive_columns_from_a_masked_account_are_ignored_with_a_warning(monkeypatch):
    mod, env, _ = _env(monkeypatch, user=HIDDEN_USER)
    rows = [
        {"_row": 2, "employee_number": "A001", "designation": "财务主管", "default_monthly_salary": "99999", "bank_ac_no": "1", "id_card_number_cn": "110101199001010090"},
        {"_row": 3, "employee_number": "B002", "default_monthly_salary": "5000"},
        _new_row(_row=4, default_social_insurance_base="8000", social_insurance_number="123"),
    ]
    result = mod.preview_employee_import(rows)
    by = _by_row(result)
    assert by[2]["status"] == "update" and [c["field"] for c in by[2]["changes"]] == ["designation"]
    assert "工资" in by[2]["warnings"][0] and "银行卡号" in by[2]["warnings"][0] and "身份证号" in by[2]["warnings"][0]
    assert by[3]["status"] == "unchanged" and by[3]["warnings"]
    assert by[4]["status"] == "create" and any("社保基数" in w for w in by[4]["warnings"])
    assert result["summary"]["sensitive_ignored"] is True
    assert result["summary"]["warnings"] == 3

    summary = mod.import_employees(rows)
    assert summary["created"] == 1 and summary["updated"] == 1
    a001 = next(r for r in env.store if r["employee_number"] == "A001")
    assert a001["designation"] == "财务主管"
    assert a001["default_monthly_salary"] == 10000.0 and a001["bank_ac_no"] == "6222000011112222"
    n100 = next(r for r in env.store if r["employee_number"] == "N100")
    assert "default_social_insurance_base" not in n100 and "social_insurance_number" not in n100


def test_sensitive_columns_are_applied_for_accounts_with_access(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    mod.import_employees([
        {"_row": 2, "employee_number": "A001", "default_monthly_salary": "12,000.50", "bank_ac_no": "0001234567890123", "salary_months": "13"},
    ])
    a001 = next(r for r in env.store if r["employee_number"] == "A001")
    assert a001["default_monthly_salary"] == 12000.5
    assert a001["bank_ac_no"] == "0001234567890123"  # 前导 0 保留，仍是文本
    assert a001["salary_months"] == 13


def test_blank_cells_never_clear_existing_values(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    rows = [{"_row": 2, "employee_number": "A001", "employee_name": "", "designation": "", "cell_number": "  ",
             "default_monthly_salary": "", "english_name": "Zhang San", "department": "研发软件部"}]
    result = mod.preview_employee_import(rows)
    assert result["rows"][0]["status"] == "unchanged" and result["rows"][0]["changes"] == []
    with pytest.raises(RuleError, match="没有需要导入"):
        mod.import_employees(rows)
    a001 = next(r for r in env.store if r["employee_number"] == "A001")
    assert a001["designation"] == "工程师" and a001["cell_number"] == "13800000002" and a001["default_monthly_salary"] == 10000.0

    mod.import_employees([{"_row": 2, "employee_number": "A001", "designation": "财务主管", "cell_number": ""}])
    a001 = next(r for r in env.store if r["employee_number"] == "A001")
    assert a001["designation"] == "财务主管" and a001["cell_number"] == "13800000002"
    assert env.saved == ["HR-EMP-90001"]


def test_zero_for_an_unset_money_field_counts_as_no_change(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    env.store[1]["default_monthly_salary"] = None
    result = mod.preview_employee_import([{"_row": 2, "employee_number": "B002", "default_monthly_salary": "0"}])
    assert result["rows"][0]["status"] == "unchanged"


def test_import_creates_new_employees_and_adds_info_comments(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    rows = [
        _new_row(_row=2, department="财务部", designation="工程师", gender="女", date_of_birth="1995-05-05",
                 default_monthly_salary="8000", reports_to="A001", cell_number="13800000004"),
        {"_row": 3, "employee_number": "A001", "designation": "财务主管"},
        {"_row": 4, "employee_number": "B002"},
    ]
    result = mod.import_employees(rows)
    assert result["created"] == 1 and result["updated"] == 1 and result["unchanged"] == 1
    assert env.commits == 1 and env.rollbacks == 0
    new = next(r for r in env.store if r["employee_number"] == "N100")
    assert new["company"] == "Rayher" and new["department"] == "财务部 - RAY" and new["gender"] == "Female"
    assert new["date_of_birth"] == "1995-05-05" and new["date_of_joining"] == "2026-10-01"
    assert new["reports_to"] == "HR-EMP-90001" and new["first_name"] == "新员工" and new["status"] == "Active"
    assert new["default_monthly_salary"] == 8000.0
    kinds = {(kind, name): text for kind, name, text in env.comments}
    assert kinds[("Info", new["name"])] == "批量导入（Excel）：新增"
    assert kinds[("Info", "HR-EMP-90001")].startswith("批量导入（Excel）：更新 ") and "职位" in kinds[("Info", "HR-EMP-90001")]
    assert len(env.comments) == 2  # 无变化的员工不加记录
    assert "8000" not in kinds[("Info", new["name"])]


def test_import_defaults_match_save_employee_for_gender_and_birth_date(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    preview = mod.preview_employee_import([_new_row()])
    assert any("性别" in w for w in preview["rows"][0]["warnings"])
    assert any("出生日期" in w for w in preview["rows"][0]["warnings"])
    mod.import_employees([_new_row()])
    new = next(r for r in env.store if r["employee_number"] == "N100")
    assert new["gender"] == "Male" and new["date_of_birth"] == "1990-01-01"


def test_leaving_date_marks_the_employee_left_but_not_while_an_approver(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    mod.import_employees([{"_row": 2, "employee_number": "A001", "relieving_date": "2026-09-30"}])
    a001 = next(r for r in env.store if r["employee_number"] == "A001")
    assert a001["status"] == "Left" and a001["relieving_date"] == "2026-09-30"

    mod2, env2, _ = _env(monkeypatch)
    env2.approvers["HR-EMP-90001"] = "财务经理"
    result = mod2.preview_employee_import([{"_row": 2, "employee_number": "A001", "relieving_date": "2026-09-30"}])
    assert result["rows"][0]["status"] == "error" and "交接" in result["rows"][0]["errors"][0]


def test_cross_field_date_rules_are_checked(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([
        {"_row": 2, "employee_number": "A001", "relieving_date": "2023-12-31"},  # 早于入职 2024-01-01
        _new_row(_row=3, employee_number="N1", date_of_birth="2026-10-01", date_of_joining="2026-10-01"),
    ])
    assert "离职日期不能早于入职日期" in result["rows"][0]["errors"][0]
    assert "入职日期必须晚于出生日期" in result["rows"][1]["errors"][0]


def test_archived_status_needs_the_same_information_as_the_employee_validation(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([_new_row(archive_status="已归档")])
    assert result["rows"][0]["status"] == "error" and "无法归档" in result["rows"][0]["errors"][0]


def test_active_employee_names_must_stay_unique_inside_the_file_and_against_the_system(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([
        _new_row(_row=2, employee_number="N1", employee_name="演示员工129"),         # 系统里已有在职演示员工129
        _new_row(_row=3, employee_number="N2", employee_name="演示员工175"),
        _new_row(_row=4, employee_number="N3", employee_name="演示员工175"),         # 文件里重名
        _new_row(_row=5, employee_number="N4", employee_name="演示员工157"),         # 演示员工157已离职，可以用
    ])
    by = _by_row(result)
    assert by[2]["status"] == "error" and "已有在职员工叫「演示员工129」" in by[2]["errors"][0]
    assert by[3]["status"] == "error" and by[4]["status"] == "error" and "第 3、4 行" in by[3]["errors"][0]
    assert by[5]["status"] == "create"
    # 把演示员工146改名成演示员工129
    renamed = mod.preview_employee_import([{"_row": 2, "employee_number": "B002", "employee_name": "演示员工129"}])
    assert renamed["rows"][0]["status"] == "error" and "已有在职员工叫「演示员工129」" in renamed["rows"][0]["errors"][0]
    # 改名成没人用的名字没问题；名字没变的更新不查重名
    assert mod.preview_employee_import([{"_row": 2, "employee_number": "B002", "employee_name": "演示员工146(财务)"}])["rows"][0]["status"] == "update"
    assert mod.preview_employee_import([{"_row": 2, "employee_number": "A001", "employee_name": "演示员工129", "designation": "财务主管"}])["rows"][0]["status"] == "update"


def test_supervisor_is_resolved_by_number_or_unique_active_name(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.preview_employee_import([
        _new_row(_row=2, employee_number="N1", employee_name="甲", reports_to="A001"),
        _new_row(_row=3, employee_number="N2", employee_name="乙", reports_to="演示员工129"),
        _new_row(_row=4, employee_number="N3", employee_name="丙", reports_to="演示员工157"),   # 已离职，不能按姓名找
        _new_row(_row=5, employee_number="N4", employee_name="丁", reports_to="查无此人"),
        {"_row": 6, "employee_number": "A001", "reports_to": "A001"},
    ])
    by = _by_row(result)
    assert by[2]["status"] == "create" and by[3]["status"] == "create"
    assert by[4]["status"] == "error" and by[5]["status"] == "error"
    assert "不能是本人" in by[6]["errors"][0]


def test_import_refuses_the_whole_file_when_any_row_has_a_problem(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    rows = [_new_row(_row=2), _new_row(_row=3, employee_number="N101", employee_name="坏行", department="不存在部")]
    with pytest.raises(RuleError, match="第 3 行"):
        mod.import_employees(rows)
    assert env.inserted == [] and env.saved == [] and env.commits == 0 and env.comments == []


def test_import_does_not_trust_a_client_side_preview(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    # 前端算好的字段（status / vals）一概不看，服务端按原始单元格重新算
    rows = [dict(_new_row(), status="create", errors=[], vals={"company": "Rayher", "employee_name": "伪造"}, department="不存在部")]
    with pytest.raises(RuleError, match="整份都没有导入"):
        mod.import_employees(rows)
    assert env.inserted == []


def test_permission_refusal_blocks_preview_and_import(monkeypatch):
    mod, env, frappe = _env(monkeypatch)

    def refuse(roles):
        raise RuleError("没有权限")

    monkeypatch.setattr(mod, "require_rd_access", refuse)
    with pytest.raises(RuleError, match="没有权限"):
        mod.preview_employee_import([_new_row()])
    with pytest.raises(RuleError, match="没有权限"):
        mod.import_employees([_new_row()])
    assert env.inserted == [] and env.commits == 0
    # 两个接口都用和 save_employee 相同的角色集合
    captured = []
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.append(roles))
    mod.preview_employee_import([_new_row()])
    mod.import_employees([_new_row()])
    assert captured == [mod.RD_HR_WRITE, mod.RD_HR_WRITE]


def test_a_user_who_cannot_create_employees_gets_row_errors(monkeypatch):
    mod, env, _ = _env(monkeypatch, allow_create=False)
    result = mod.preview_employee_import([_new_row()])
    assert result["rows"][0]["status"] == "error" and "无权新增" in result["rows"][0]["errors"][0]


def test_failure_on_the_second_write_rolls_everything_back(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    before = copy.deepcopy(env.store)
    env.fail_on = {"会失败的人"}
    rows = [
        _new_row(_row=2, employee_number="N1", employee_name="先写入的人"),
        _new_row(_row=3, employee_number="N2", employee_name="会失败的人"),
    ]
    assert mod.preview_employee_import(rows)["summary"]["create"] == 2   # 预览看不出写入时才出的错
    with pytest.raises(RuleError, match="第 3 行写入失败，本次导入已全部撤销：模拟校验失败"):
        mod.import_employees(rows)
    assert env.rollbacks == 1
    assert env.commits == 0
    assert env.store == before          # 第一行已经 insert 过，回滚后不见了
    assert env.inserted == ["HR-EMP-90004"]  # 确实写过一行，说明回滚是真的在撤销


def test_failure_on_an_update_also_rolls_back_earlier_updates(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    before = copy.deepcopy(env.store)
    env.fail_on = {"演示员工146"}
    rows = [
        {"_row": 2, "employee_number": "A001", "designation": "财务主管"},
        {"_row": 3, "employee_number": "B002", "english_name": "Li Si"},
    ]
    with pytest.raises(RuleError, match="第 3 行写入失败"):
        mod.import_employees(rows)
    assert env.store == before and env.commits == 0 and env.rollbacks == 1


def test_save_employee_still_uses_the_shared_write_path(monkeypatch):
    mod, env, _ = _env(monkeypatch)
    result = mod.save_employee(employee_number="Z9", employee_name="手工新增", company="Rayher", date_of_joining="2026-10-02")
    assert result == {"name": "HR-EMP-90004"} and env.commits == 1
    row = env.store[-1]
    assert row["gender"] == "Male" and row["date_of_birth"] == "1990-01-01" and row["first_name"] == "手工新增"
    mod.save_employee(name="HR-EMP-90001", designation="财务主管")
    assert env.store[0]["designation"] == "财务主管"
