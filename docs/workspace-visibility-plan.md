# 工作区按角色可见性方案 (Workspace Visibility by Role)

状态: 设计文档 (待实现进 app)。背景: Desk 侧边栏混入大量 ERPNext 自带模块(Buying/Selling/
Stock/Manufacturing 等),与本系统(HR/OA 审批 + 研发成本)无关; 且不同角色需要看到的工作区不同。

## 1. 现状
- 自定义工作区已按角色绑定(roles):
  - 员工工作台: [Employee]
  - 审批中心: [Department Manager, Accounts User, System Manager, Leave Approver, Expense Approver]
  - 研发成本: [System Manager, Accounts User, Projects Manager] (module=Rayher HR Payroll)
- 自带工作区(Accounting/HR/Payroll/Projects/Users 及商贸制造类)是 public 且按 module 显示;
  默认用户 allow_modules 不限 -> 全部显示 -> 侧边栏混乱。

## 2. 目标矩阵 (每个角色应看到的顶层工作区)
| 角色 | 看到 | 看不到 |
|------|------|--------|
| 员工 Employee | 员工工作台 | 其余全部 |
| 经理 Department Manager | 员工工作台, 审批中心 | 财务/HR/研发/商贸/制造/系统 |
| 财务 Accounts User | 审批中心, 研发成本, Accounting, Payroll | HR-admin, 商贸/制造, 系统 |
| HR (HR User/Manager) | HR, Payroll, 审批中心 | Accounting深, 研发成本, 商贸/制造 |
| 总控 Serena (SysMgr+HRMgr+AcctUser) | 审批中心, 研发成本, HR, Payroll, Accounting, Projects, Users, Home, ERPNext Settings | 商贸/制造/集成类 |

## 3. 三层机制
### (A) 全局隐藏 - 所有角色演示员工177需要 (is_hidden=1)
Buying, Selling, Stock, Assets, Manufacturing, Quality, Support, Website, CRM,
Integrations, ERPNext Integrations, Welcome Workspace, Build。
理由: 本部署不做商贸/制造/CRM; 这些对任何角色都是噪音。

### (B) 自定义工作区按 roles (已实现)
员工工作台/审批中心/研发成本 已绑定角色; 无 module 的靠 roles 显示, 有 module 的(研发成本)靠 roles+module。

### (C) 自带工作区按 Module Profile (待实现) - 控制各角色 allow_modules
为每个角色档建一个 Module Profile(block_modules 列表), 按主角色分配给用户:
| Module Profile | 放行的模块(其余 block) | 适用角色 |
|----------------|----------------------|---------|
| MP-员工 | (全 block; 只靠角色绑定看 员工工作台) | Employee-only 用户 |
| MP-经理 | (全 block; 靠角色看 员工工作台+审批中心) | Department Manager |
| MP-财务 | Accounts, Payroll, Rayher HR Payroll | Accounts User |
| MP-HR | HR, Payroll | HR User/HR Manager |
| 总控 | 不分配 Profile(或只 block 商贸/制造) | Serena (System Manager) |

注: Module Profile 绑定在 User 上(user.module_profile), 非 Role。需在开户/分配角色时按主角色设置。

## 4. 实现计划 (进 app)
1. install.py 的 after_install/after_migrate:
   - 对 (A) 列表的工作区设 is_hidden=1(幂等; 注意是修改自带工作区, 需评估 migrate 覆盖)。
   - 幂等创建 (C) 的 Module Profile(block_modules)。
2. lifecycle_controls.sync_user_for_employee: 自动开户时按主角色设 user.module_profile
   (员工->MP-员工; 后续 HR 加管理角色时改 Profile)。HR 手动加管理角色的账号由 HR 设 Profile。
3. 研发成本 工作区的 Projects Manager 角色按需保留/调整。

## 5. 风险/取舍
- (A) 修改自带工作区 is_hidden, ERPNext 升级/migrate 可能重置 -> 用 after_migrate 幂等重设。
- Module Profile 是按用户分配, 非按角色自动; 需在 provisioning 钩子里按主角色设。
- 更保守的替代: 只做 (A) 全局隐藏商贸/制造(对所有角色), 暂不做 (C) 细分; 细分留待确认。