"""测试数据脚本的站点开关（修复 2026-09-29，模块 7，决定 D9）。

生成/清理验收测试数据的脚本会批量建单、按前缀删除单据，procurement_test_data.seed
默认还会重置审批节点账号的密码。原来任何站点都能跑，误在正式站点执行就会改掉真实数据。
现在只有 site_config.json 里设置了 "allow_test_data_seed": 1 的站点才能真正写入或删除；
只读预览（dry_run）不受限制。
"""

import frappe

SWITCH = "allow_test_data_seed"


def require_test_data_site():
    if not frappe.conf.get(SWITCH):
        raise frappe.ValidationError(
            f"本站点没有开启测试数据开关（site_config.json 的 {SWITCH}），不能生成或清理测试数据。"
        )


def like_prefix(text):
    """LIKE 前缀匹配时把 %、_ 和反斜杠当普通字符（批次号允许下划线）。"""
    escaped = str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"
