from rayher_hr_payroll.patches.v1_0 import migrate_oa_asset_categories as migration


def test_legacy_asset_categories_are_normalized_to_current_select_values():
    assert migration.normalize_legacy_asset_category("行政固定资产") == "非电子类固定资产（人事/行政）"
    assert migration.normalize_legacy_asset_category("IT类固定资产") == "电子类固定资产（IT）"
    assert migration.normalize_legacy_asset_category("其它") == "其他"
    assert migration.normalize_legacy_asset_category("其他") == "其他"