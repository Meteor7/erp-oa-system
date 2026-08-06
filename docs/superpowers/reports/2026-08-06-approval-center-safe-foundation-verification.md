# 审批中心安全底座 V2 验证报告

验证日期：2026-08-06
验证范围：本地隔离 worktree + 本地 Docker 站点 `rayher.localhost`
分支：`codex/approval-center-safe-foundation-v2`
源码验收提交：`1b37904e`

## 交付范围

- 保留既有请假审批、报销和对公付款逻辑。
- 新增采购申请、购买申请、采购付款的本地草稿能力；正式审批路线保持关闭，不能提交或推进状态。
- 新增申请看板、付款看板，区分申请金额、批准金额、占用金额、已付金额和可用余额。
- 新增不可变金额流水，使用来源行锁、付款行锁和唯一幂等键防止并发超额。
- 新增业务资料归档，支持规定资料类型、私有文件、SHA-256、版本递增和父审批单权限。
- 新增 Frappe 原生列表/文档权限与服务端字段、状态转换保护。

## 自动化验证

### Python

仓库旧测试会在整包单进程收集时互相覆盖 `frappe` / `frappe.utils` 测试桩，因此按测试文件独立进程执行全部 75 个测试文件：

- 通过：951
- 失败：0
- 跳过：0
- 错误：0

首次全量检查发现 `OA Approval Request` 的 `field_order` 与字段数组顺序不一致，已在 `ba3a5a3b` 修复；修复后重新执行全量并全部通过。

### 前端

命令：`node --test tests/*.test.js`

- 通过：195
- 失败：0
- 跳过：0

### 构建

命令：`yarn build`

- Vite：5.4.21
- 构建结果：成功
- `public/frontend/index.html` 开头：`<!DOCTYPE html>`
- `www/rayher.html` 开头：`<!DOCTYPE html>`
- TipRay TSD 文件头标记：本次修改和构建产物均未发现

## 本地备份与迁移

备份完成：

- 配置：`sites/rayher.localhost/private/backups/20260806_182338-rayher_localhost-site_config_backup.json`
- 数据库：`sites/rayher.localhost/private/backups/20260806_182338-rayher_localhost-database.sql.gz`
- 公共文件：`sites/rayher.localhost/private/backups/20260806_182338-rayher_localhost-files.tar`
- 私有文件：`sites/rayher.localhost/private/backups/20260806_182338-rayher_localhost-private-files.tar`

通过 `PYTHONPATH` 明确加载隔离 worktree，连续执行两次 `bench --site rayher.localhost migrate`：

- 第一次：退出码 0；执行 `add_approval_center_safe_foundation` 成功。
- 第二次：退出码 0；没有再次执行补丁。
- 两次迁移后已清缓存。

关键业务计数前后保持一致：

| DocType | 第一次迁移后 | 第二次迁移后 |
|---|---:|---:|
| Employee | 84 | 84 |
| Timesheet | 970 | 970 |
| OA Approval Request | 0 | 0 |
| OA Approval Amount Ledger | 0 | 0 |
| OA Business Document | 0 | 0 |

## 直接攻击验收

所有临时单据在同一事务内回滚，没有写入业务数据：

- 关闭路线直接创建非草稿：拒绝（`PermissionError`）。
- 原生保存篡改批准金额：拒绝（`PermissionError`）。
- 原生保存伪造状态转换：拒绝（`PermissionError`）。
- 其他员工原生列表查询该草稿：无结果。
- 其他员工直接读取该草稿：拒绝（`PermissionError`）。
- 重复幂等键、余额非负、并发锁顺序和未授权文件归档：由金额流水及业务资料测试覆盖并通过。

## 环境边界

- 未连接或修改 staging `203.0.113.58`。
- 未连接或修改 product `203.0.113.32`。
- 本地 Bench 主 app 目录存在大量用户未提交改动，因此未覆盖主 app 目录。
- 数据库 Schema 已通过隔离 worktree 迁移；运行中的主站仍加载原主 app 代码。要在本地主站看到新界面，需先由用户决定如何合并/部署隔离分支，避免覆盖主目录未提交工作。

## 暂不启用

以下内容等待正式审批人和路线确认后另行实施：采购申请审批路线、购买申请审批路线、采购付款预付款/到货/尾款状态机、价格审批、合同生成与电子章、金蝶/邮件真实接口、采购发票 OCR 自动放行。