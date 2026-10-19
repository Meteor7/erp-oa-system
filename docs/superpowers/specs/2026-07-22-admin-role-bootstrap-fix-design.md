# Frappe 演示员工170角色注入模板修复设计

## 问题

`rayher_hr_payroll/www/rayher.html` 被写成单行文件，原有 20 个换行变成了字面量 `\\n`。这些字符进入内联 JavaScript 后触发语法错误，导致 `window.user`、`window.full_name` 和 `window.roles` 没有注入。前端因此把任何已登录用户都当作普通账号，并显示 403。

数据库中的 `admin@legacy-business.example.invalid` 仍是启用的 System User，且拥有 System Manager、Accounts User、HR Manager 等角色，因此不修改账号和数据库权限。

## 方案

采用最小修复：

1. 恢复 `rayher.html` 的真实 UTF-8 换行，保留现有 Jinja boot 注入逻辑和已构建资源引用。
2. 增加源码回归测试，要求模板包含真实换行、不包含字面量 `\\n`，并继续注入 `boot` 中的用户与角色。
3. 将模板同步到正在运行的 Frappe app，清理 Frappe 网站缓存并重启 Web 服务。
4. 通过模板测试、前端全量测试、实际 HTTP 页面源码和演示员工170会话验证结果。

## 边界

- 不修改数据库、业务单据、发票、附件或角色配置。
- 不修改 `main`，只提交到 `feat/invoice-ocr-reimbursement`。
- 不引入新的登录接口或前端权限模型。
