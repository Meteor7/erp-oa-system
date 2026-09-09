import sys
import types


if "frappe" not in sys.modules:
    frappe_stub = types.ModuleType("frappe")

    def whitelist(*_args, **_kwargs):
        return lambda function: function

    frappe_stub.whitelist = whitelist
    frappe_stub.session = types.SimpleNamespace(user="Administrator")
    sys.modules["frappe"] = frappe_stub


from rayher_hr_payroll.api.procurement_materials import _classify_material_match


def evidence(**overrides):
    values = {"item_name": "电柜全套", "specification": "XTC-80A", "brand": "金盾"}
    values.update(overrides)
    return values


def catalog_row(**overrides):
    row = {"material_name": "电柜全套", "specification": "XTC-80A", "brand": "金盾"}
    row.update(overrides)
    return row


def test_exact_identity_is_high_confidence_duplicate_evidence():
    result = _classify_material_match(evidence(), catalog_row())

    assert result["identity_exact"] is True
    assert result["spec_exact"] is True
    assert result["spec_format_only"] is False
    assert result["name_only"] is False


def test_separator_and_case_variants_are_format_only_matches():
    result = _classify_material_match(
        evidence(specification="xtc 80a"),
        catalog_row(specification="XTC-80A"),
    )

    assert result["spec_exact"] is True
    assert result["spec_format_only"] is True
    assert result["identity_exact"] is False


def test_same_name_with_different_spec_is_not_treated_as_identity_duplicate():
    result = _classify_material_match(
        evidence(specification="XTC-90A"),
        catalog_row(specification="XTC-80A"),
    )

    assert result["name_exact"] is True
    assert result["name_only"] is True
    assert result["spec_exact"] is False
    assert result["identity_exact"] is False


def test_different_name_and_spec_has_no_duplicate_evidence():
    result = _classify_material_match(
        evidence(item_name="服务器柜", specification="ND61042"),
        catalog_row(material_name="电柜全套", specification="XTC-80A"),
    )

    assert result == {
        "spec_exact": False,
        "spec_format_only": False,
        "name_exact": False,
        "brand_exact": True,
        "identity_exact": False,
        "name_only": False,
    }
