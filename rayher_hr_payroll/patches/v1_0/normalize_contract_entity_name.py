import frappe

OFFICIAL_ENTITY = "示例企业032有限公司"
WRONG_ENTITIES = (
    "普朗克半导体",
    "示例企业022有限公司",
    "QIHENG Demo",
    "QIHENG Demo Technology Co., Ltd.",
)


def _replace_json_fields(doctype, fields):
    table = f"tab{doctype}"
    if not frappe.db.table_exists(table):
        return
    for field in fields:
        if not frappe.db.has_column(doctype, field):
            continue
        for wrong in WRONG_ENTITIES:
            frappe.db.sql(
                f"""update `{table}` set `{field}` = replace(`{field}`, %s, %s)
                where `{field}` like %s""",
                (wrong, OFFICIAL_ENTITY, f"%{wrong}%"),
            )


def execute():
    mappings = {
        "OA Price Approval Quote": ("contract_entity",),
        "OA Price Approval Line": ("selected_contract_entity",),
        "OA Purchase Order": ("contract_entity",),
        "OA Approval Request": ("contract_entity",),
    }
    for doctype, fields in mappings.items():
        table = f"tab{doctype}"
        if not frappe.db.table_exists(table):
            continue
        for field in fields:
            if not frappe.db.has_column(doctype, field):
                continue
            for wrong in WRONG_ENTITIES:
                frappe.db.sql(
                    f"""update `{table}` set `{field}` = %s where `{field}` = %s""",
                    (OFFICIAL_ENTITY, wrong),
                )
    _replace_json_fields("OA Approval Request", ("contract_snapshot", "contract_draft_content"))
    frappe.db.commit()