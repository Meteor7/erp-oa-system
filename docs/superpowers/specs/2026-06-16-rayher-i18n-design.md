# QIHENG Demo Frappe 三语 i18n 设计

日期：2026-06-16
范围：QIHENG Demo 自定义 Frappe App 第一版语言切换，支持中文、英文、法文。

## 决策

采用 Frappe 原生翻译系统，不自建独立 i18n 框架。

官方依据：

- Frappe 自带翻译系统，代码和 DocType 字符串可进入翻译文件：https://docs.frappe.io/framework/user/en/translations
- 自定义 App 翻译文件放在 app 包目录的 `translations/<lang>.csv`，代码字符串用 `_()` 包裹：https://docs.frappe.io/framework/user/en/guides/basics/translations
- 登录用户语言由 `User.language` / session language 解析：https://docs.frappe.io/framework/user/en/python-api/language

## 第一版做什么

1. 支持 `zh`、`en`、`fr` 三个语言代码。
2. 新增后端白名单方法：当前用户选择语言后，写入 `User.language`，更新当前 request/session 的语言，并清理翻译缓存。
3. 新增 `rayher_hr_payroll/translations/zh.csv` 与 `fr.csv`。
4. 把 QIHENG Demo 自定义报表列名、异常类型、校验/报错消息接入 `_()`。
5. 保留现有中文业务枚举值，例如 `全时研发`、`资本化`、`待复核`，本版不做数据迁移。
6. 文档注明：项目名称、部门名称、岗位名称、费用科目等业务数据不会自动翻译，后续如要三语业务数据，需要主数据翻译表或多语言显示字段。

## 第一版不做什么

1. 不修改 Frappe、ERPNext、HRMS 核心代码。
2. 不重做 Desk 前端框架。
3. 不迁移 Select 选项存储值为英文代码，避免影响已有测试和研发费用逻辑。
4. 不翻译用户录入的业务数据。
5. 不承诺 Frappe core 法文完整度；本地核实 ERPNext/HRMS 有 `fr.csv`，Frappe core 当前安装包只有 `zh.csv`，缺失部分会回退英文。

## 设计细节

新增 `rayher_hr_payroll/i18n.py`：

- `SUPPORTED_LANGUAGES = {"zh", "en", "fr"}`。
- `normalize_language(language)` 接收 `zh-CN`、`fr-FR` 这类输入时归并到父语言 `zh` / `fr`。
- `set_language(language)`：仅允许登录用户调用；校验语言；保存当前 `User.language`；设置 `frappe.local.lang`；清理翻译缓存；返回 `{"language": language, "reload": True}`。
- `get_language_options()` 返回三语选项，便于前端按钮/菜单调用。

报表与控制逻辑：

- 纯函数增加可注入翻译函数，默认返回原字符串，保证无 Frappe 环境下测试简单。
- Frappe `execute()` 路径传入 `frappe._`，使报表列名和行消息按当前用户语言显示。
- `frappe.throw` 前的消息通过 `frappe._` 翻译，保留占位格式。

## 验收标准

1. `python -m pytest rayher_hr_payroll/tests -q` 通过。
2. 翻译文件存在且含 QIHENG Demo 关键字符串的 zh/fr 翻译。
3. 语言 API 拒绝不支持语言，允许 `zh`、`en`、`fr` 和常见地区码。
4. 报表列名和异常类型可通过注入翻译函数被翻译。
5. `bench migrate` 通过，demo 分摊仍为 RD-CAP 720 / RD-EXP 480。
