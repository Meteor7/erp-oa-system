# 第二轮真实数据库回归

仅在可丢弃的数据库副本运行；所有脚本复用 `../test_transaction_locks.py` 的隔离环境检查（`review_isolated=true`、`rayher-review-db`、`RAYHER_REVIEW_SITE=review.localhost`）。禁止指向业务库。

先同步当前工作区到隔离容器、迁移，再从隔离 bench 的 sites 目录逐个执行这些脚本。脚本依赖副本中的岗位、员工、项目和社保样例，会用2098年或REVIEW命名的临时记录并清理；权限及状态攻击失败时通过异常断言验收。

- check_po_fulfillment.py：不完整到货拦截、完整到货正常下推、验收反转阻止付款、附件权限及旧关联修复。
- check_social_import.py：跨公司工资取数、已生效导入不能经原生接口修改。
- check_identity_and_rd_lock.py：可修改姓名不解析成身份、显式旧映射可迁移、锁定期间类型保护。
- check_room.py：同一房间只能有一个当前入住人。
- check_concurrent_expense.py：两进程同期间创建只保留一张有效费用单。
- check_foreign_monthly.py：月度无活动类型和多天工时均可保存。
- round2_procurement_race.py：真实并发PR及核价不超分配，同时提供测试清理辅助函数。

这些是正确性验证，不替代正式数据规模压测或浏览器验收。全新空站点安装另行执行安装命令，不能直接运行依赖业务样例的脚本。
