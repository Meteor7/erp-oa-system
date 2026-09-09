import frappe

OFFICIAL_ENTITY = "示例企业032有限公司"
LEGACY_ENTITY = "普朗克半导体"


def execute():
    if not frappe.db.table_exists("OA Approval Request"):
        return
    frappe.db.sql(
        """update `tabOA Approval Request`
        set contract_entity = %s
        where contract_entity = %s""",
        (OFFICIAL_ENTITY, LEGACY_ENTITY),
    )
    for field in ("contract_snapshot", "contract_draft_content"):
        if frappe.db.has_column("OA Approval Request", field):
            frappe.db.sql(
                f"""update `tabOA Approval Request`
                set `{field}` = replace(`{field}`, %s, %s)
                where `{field}` like %s""",
                (LEGACY_ENTITY, OFFICIAL_ENTITY, f"%{LEGACY_ENTITY}%"),
            )
