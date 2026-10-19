"""Stable approval-center document and ledger event contracts."""

REQUEST_LEAVE = "请假申请"
REQUEST_PROCUREMENT = "采购申请"
REQUEST_DIRECT_PURCHASE = "购买申请"
REQUEST_PROCUREMENT_PAYMENT = "采购付款"
# 付款报销改造新增的单据类型；在站点配置启用前只有演示员工170可见。
REQUEST_TRAVEL = "出差申请"
REQUEST_REIMBURSEMENT = "报销单"
REQUEST_PAYMENT = "付款单"
OPT_IN_REQUEST_TYPES = (REQUEST_TRAVEL, REQUEST_REIMBURSEMENT, REQUEST_PAYMENT)

PAYMENT_SOURCE_PROCUREMENT = "关联采购申请"
PAYMENT_SOURCE_DIRECT_PURCHASE = "关联购买申请"
PAYMENT_SOURCE_NONE = "无事前申请"

ASSET_FIXED = "固定资产"
ASSET_NON_FIXED = "非固定资产"

AMOUNT_EVENTS = ("reserve", "release", "pay", "refund", "reverse")
