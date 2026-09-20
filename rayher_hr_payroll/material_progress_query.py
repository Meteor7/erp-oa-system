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
        WHEN {po_exists()} THEN CASE
          WHEN NOT {po_exists("po.status!='已关闭'")} THEN '已关闭'
          WHEN {po_exists("po.status IN ('草稿','待确认')")} THEN 'PO处理中'
          WHEN {po_exists("po.status IN ('已生效','供应商制作中')")} THEN '供应商制作中'
          WHEN {po_exists("po.status='到货验收中'")} THEN '到货验收中'
          WHEN {po_exists("po.status='付款中'")} THEN '付款中'
          ELSE 'PO处理中' END
        WHEN COALESCE(b.price_approval_numbers,'')!='' THEN 'PO处理中'
        ELSE '采购确认中' END"""


def conditions(search="", requester="", status="", source_request=""):
    clauses, params = ["1=1"], {}
    for field, value in (("requester", requester), ("source_request", source_request)):
        if value:
            clauses.append(f"b.{field}=%({field})s")
            params[field] = str(value).strip()
    if search:
        fields = ("source_request", "material_serial", "requester", "project", "material_code", "item_name", "specification", "brand", "pr_numbers", "po_numbers", "supplier", "current_handler", "remarks")
        clauses.append("(" + " OR ".join(f"COALESCE(b.{field},'') LIKE %(search)s" for field in fields) + ")")
        params["search"] = "%" + str(search).strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if status:
        clauses.append(f"({stage_sql()})=%(status)s")
        params["status"] = str(status).strip()
    return " AND ".join(clauses), params
