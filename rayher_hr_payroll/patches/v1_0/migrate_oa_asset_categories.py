"""Normalize persisted OA asset categories to the six-stage workflow values."""


LEGACY_ASSET_CATEGORY_MAP = {
    "行政固定资产": "非电子类固定资产（人事/行政）",
    "IT类固定资产": "电子类固定资产（IT）",
    "其它": "其他",
}


def normalize_legacy_asset_category(value):
    return LEGACY_ASSET_CATEGORY_MAP.get(str(value or "").strip(), value)


def execute():
    import frappe

    for legacy, current in LEGACY_ASSET_CATEGORY_MAP.items():
        frappe.db.sql(
            """UPDATE `tabOA Approval Request`
               SET asset_category = %s
               WHERE asset_category = %s""",
            (current, legacy),
        )