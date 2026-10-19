"""Database-side material filtering; only the selected page is hydrated."""

# The CASE mirrors material_progress._derived_status. Subqueries use the original
# OA line key, never a latest PO identifier (one material may have several POs).
FROM_SQL = "FROM `tabOA Material Progress` b JOIN `tabOA Approval Request` r ON r.name=b.source_request"
PO_FROM = "FROM `tabOA Purchase Order Line` pl JOIN `tabOA Purchase Order` po ON po.name=pl.parent WHERE pl.source_request=b.source_request AND pl.source_line=b.source_line"

def stage_sql():
    def po_exists(condition="1=1"):
        return f"EXISTS (SELECT 1 {PO_FROM} AND ({condition}))"
    return f"""CASE
        WHEN b.status='已取消' THEN '已取消'
        WHEN r.workflow_status IN ('已拒绝','已撤回') THEN r.workflow_status
        WHEN r.workflow_status NOT IN ('已完成','已通过','已审批','已结束')
          AND COALESCE(r.business_status,'') NOT LIKE '需求已批准%%' THEN 'OA审批中'
        WHEN COALESCE((SELECT SUM(pl.quantity) {PO_FROM}),0)+0.000001 < b.quantity THEN
          CASE WHEN COALESCE((SELECT SUM(pal.quantity) FROM `tabOA Price Approval Line` pal
            JOIN `tabOA Price Approval` pa ON pa.name=pal.parent
            WHERE pal.source_request=b.source_request AND pal.source_line=b.source_line
            AND pa.status!='已取消'),0)+0.000001 >= b.quantity THEN 'PO处理中'
          ELSE '采购确认中' END
        WHEN {po_exists()} THEN CASE
          WHEN NOT {po_exists("po.status!='已关闭'")} THEN '已关闭'
          WHEN {po_exists("po.status IN ('草稿','待确认')")} THEN 'PO处理中'
          WHEN {po_exists("po.status IN ('已生效','供应商制作中')")} THEN '供应商制作中'
          WHEN {po_exists("po.status='到货验收中'")} THEN '到货验收中'
          WHEN {po_exists("po.status='付款中'")} THEN '付款中'
          ELSE 'PO处理中' END
        WHEN COALESCE(b.price_approval_numbers,'')!='' THEN 'PO处理中'
        ELSE '采购确认中' END"""


# 演示员工116已生效、货还在路上或还没结清的 PO 状态（= material_progress.LIVE_PO_STATUSES，有测试盯着）。
LIVE_PO_SQL = "('已生效','供应商制作中','到货验收中','付款中')"


def overdue_line_sql(today_param="today"):
    """某个 PO 行演示员工116交期已过、还没收齐（同 material_progress.contract_line_overdue：退货中的货不算收到）。
    接在 PO_FROM 后面用（pl = PO 行，po = PO）。"""
    return (f"po.status IN {LIVE_PO_SQL} AND pl.contract_delivery_date IS NOT NULL "
            f"AND pl.contract_delivery_date < %({today_param})s "
            "AND (COALESCE(pl.received_quantity,0) < COALESCE(pl.quantity,0) OR COALESCE(pl.inspection_status,'')='退货中')")


def overdue_sql(today_param="today"):
    """物料逾期未到：物料没取消，至少一个演示员工116已生效的 PO 行交期已过还没收齐。
    看板的「物料逾期未到 / 缺料影响的项目 / 逾期了多久」和物料进度页的「交期已过未收齐」都用这一句（2026-10-13 对齐）。"""
    return f"b.status!='已取消' AND EXISTS (SELECT 1 {PO_FROM} AND {overdue_line_sql(today_param)})"


def overdue_due_sql(today_param="today"):
    """逾期 PO 行里最早的演示员工116交期（算“逾期了多少天”）。"""
    return f"(SELECT MIN(pl.contract_delivery_date) {PO_FROM} AND {overdue_line_sql(today_param)})"


# 未编码物料：状态演示员工152、物料编号为空、源申请没被拒绝 / 撤回（看板「未编码物料」同一句）。
UNCODED_SQL = "b.status='演示员工152' AND TRIM(COALESCE(b.material_code,''))='' AND r.workflow_status NOT IN ('已拒绝','已撤回')"


def conditions(search="", requester="", status="", source_request="", overdue=False, uncoded=False, project="", today=""):
    clauses, params = ["1=1"], {}
    for field, value in (("requester", requester), ("source_request", source_request), ("project", project)):
        if value:
            clauses.append(f"b.{field}=%({field})s")
            params[field] = str(value).strip()
    # 看板点进来的筛选：逾期未到（按服务器的今天算）、未编码
    if overdue:
        clauses.append(overdue_sql())
        params["today"] = str(today)
    if uncoded:
        clauses.append(UNCODED_SQL)
    if search:
        fields = ("source_request", "material_serial", "requester", "project", "material_code", "item_name", "specification", "brand", "pr_numbers", "po_numbers", "supplier", "current_handler", "remarks")
        clauses.append("(" + " OR ".join(f"COALESCE(b.{field},'') LIKE %(search)s" for field in fields) + ")")
        params["search"] = "%" + str(search).strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if status:
        clauses.append(f"({stage_sql()})=%(status)s")
        params["status"] = str(status).strip()
    return " AND ".join(clauses), params
