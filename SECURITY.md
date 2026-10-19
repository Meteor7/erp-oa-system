# 数据与凭据

本仓库用于作品集演示。客户、供应商、员工、邮箱、电话及证件示例使用虚构数据；演示截图标有“演示”。示例邮箱使用保留的 example.invalid 或 example.com 域名。

部署密码从环境变量或私有站点配置注入。不要把真实客户清单、员工台账、数据库备份、站点配置、会话 Cookie、访问令牌或私钥提交到仓库；也不要把这些值放进截图和验收报告。验收脚本生成的临时密码只保存在本地。

每次推送会运行 Gitleaks 凭据检查。发现泄露时，应先撤销或轮换凭据，再清理文件与 Git 历史；仅删除最新文件不能清除旧提交中的内容。参见 [GitHub 清理指南](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)。
