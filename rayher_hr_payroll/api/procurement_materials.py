"""Configurable procurement category and material catalog APIs."""

import re
import unicodedata
from difflib import SequenceMatcher

import frappe

from rayher_hr_payroll.oa_role_resolver import resolve_role


def _text(value):
    return str(value or "").strip()


def _is_pmc_or_manager():
    user = _text(frappe.session.user).lower()
    if user in {"administrator", "admin@staff.example.invalid"}:
        return True
    try:
        return user == _text(resolve_role("pmc")["user"]).lower()
    except Exception:
        return "Purchase User" in set(frappe.get_roles(user) or [])


def _category_level(code):
    return len([part for part in _text(code).split(".") if part])


def _normalize_material_text(value):
    value = unicodedata.normalize("NFKC", _text(value)).casefold()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value)


def _material_similarity(left, right):
    left = _normalize_material_text(left)
    right = _normalize_material_text(right)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))
    return SequenceMatcher(None, left, right).ratio()


def _classify_material_match(values, row):
    """Build duplicate evidence for one catalog row using reference-site rules."""
    specification = _text(values.get("specification"))
    item_name = _text(values.get("item_name"))
    brand = _text(values.get("brand"))
    row_specification = _text(row.get("specification"))
    row_name = _text(row.get("material_name"))
    row_brand = _text(row.get("brand"))
    normalized_specification = _normalize_material_text(specification)
    normalized_row_specification = _normalize_material_text(row_specification)
    spec_exact = bool(specification and normalized_specification == normalized_row_specification)
    name_exact = bool(item_name and _normalize_material_text(item_name) == _normalize_material_text(row_name))
    brand_exact = bool(brand and _normalize_material_text(brand) == _normalize_material_text(row_brand))
    spec_format_only = bool(spec_exact and specification != row_specification)
    identity_exact = bool(spec_exact and specification == row_specification and name_exact and brand_exact)
    name_only = bool(name_exact and not identity_exact and not spec_exact)
    return {
        "spec_exact": spec_exact,
        "spec_format_only": spec_format_only,
        "name_exact": name_exact,
        "brand_exact": brand_exact,
        "identity_exact": identity_exact,
        "name_only": name_only,
    }


def _validate_category_code(code):
    code = _text(code)
    if _category_level(code) < 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", code):
        frappe.throw("分类编码格式无效")
    return code


@frappe.whitelist()
def list_categories(query=None, parent_category=None, limit=100):
    query = _text(query)
    filters = {"is_active": 1}
    if parent_category:
        filters["parent_category"] = _text(parent_category)
    rows = frappe.get_all(
        "OA Procurement Category",
        filters=filters,
        or_filters=(
            [["category_code", "like", f"%{query}%"], ["category_name", "like", f"%{query}%"]]
            if query else None
        ),
        fields=["name", "category_code", "category_name", "full_path", "parent_category", "level", "allow_request", "sort_order"],
        order_by="level asc, sort_order asc, category_code asc",
        limit_page_length=min(max(int(limit or 100), 1), 2000),
    )
    return rows


@frappe.whitelist()
def list_materials(query=None, category_code=None, limit=50):
    query = _text(query)
    filters = {"is_active": 1}
    if category_code:
        filters["category_code"] = _text(category_code)
    rows = frappe.get_all(
        "OA Procurement Material",
        filters=filters,
        or_filters=(
            [["material_code", "like", f"%{query}%"], ["material_name", "like", f"%{query}%"], ["specification", "like", f"%{query}%"], ["brand", "like", f"%{query}%"]]
            if query else None
        ),
        fields=["name", "material_code", "category_code", "category_path", "material_name", "specification", "product_desc", "brand", "product_name", "product_desc_en", "brand_en", "material_attr", "unit", "source"],
        order_by="material_code asc",
        limit_page_length=min(max(int(limit or 50), 1), 500),
    )
    return rows


@frappe.whitelist()
def suggest_material(
    item_name=None, specification=None, product_desc=None, brand=None,
    category_code=None, limit=5,
):
    """Return duplicate evidence and a non-binding category suggestion for PMC review."""
    if not _is_pmc_or_manager():
        frappe.throw("只有 PMC 可以生成物料重复/分类建议")
    values = {
        "item_name": _text(item_name),
        "specification": _text(specification),
        "product_desc": _text(product_desc),
        "brand": _text(brand),
        "category_code": _text(category_code),
    }
    query_values = [values[key] for key in ("item_name", "specification", "product_desc", "brand") if values[key]]
    if not query_values:
        return {"matches": [], "duplicates": {}, "suggested_category": None, "risk_assessment": {"level": "无", "action": "暂无足够资料"}}
    or_filters = []
    for field in ("material_name", "specification", "product_desc", "brand"):
        for value in query_values:
            or_filters.append([field, "like", f"%{value}%"])
    rows = frappe.get_all(
        "OA Procurement Material",
        filters={"is_active": 1},
        or_filters=or_filters,
        fields=["name", "material_code", "category_code", "category_path", "material_name", "specification", "product_desc", "brand", "unit"],
        limit_page_length=min(max(int(limit or 5) * 20, 20), 200),
    )
    ranked = []
    for row in rows:
        evidence = _classify_material_match(values, row)
        spec_exact = evidence["spec_exact"]
        name_exact = evidence["name_exact"]
        brand_exact = evidence["brand_exact"]
        score = max(
            _material_similarity(values["specification"], row.get("specification")) * 0.55,
            _material_similarity(values["item_name"], row.get("material_name")) * 0.25,
            _material_similarity(values["product_desc"], row.get("product_desc")) * 0.15,
            _material_similarity(values["brand"], row.get("brand")) * 0.05,
        )
        if spec_exact:
            score = max(score, 0.85)
        if name_exact and brand_exact and spec_exact:
            score = 1.0
        ranked.append({
            **row,
            "score": round(score, 4),
            "spec_exact": spec_exact,
            "name_exact": name_exact,
            "brand_exact": brand_exact,
            "spec_format_only": evidence["spec_format_only"],
            "identity_exact": evidence["identity_exact"],
            "name_only": evidence["name_only"],
        })
    ranked.sort(key=lambda row: (-row["score"], row.get("material_code") or ""))
    matches = ranked[: min(max(int(limit or 5), 1), 20)]
    spec_rows = [row for row in matches if row["spec_exact"]]
    identity_rows = [row for row in spec_rows if row["name_exact"] and row["brand_exact"]]
    spec_format_rows = [row for row in matches if row["spec_format_only"]]
    name_rows = [row for row in matches if row["name_exact"] and not row["spec_exact"]]
    duplicates = {
        "spec": spec_rows,
        "spec_format": spec_format_rows,
        "identity": identity_rows,
        "name": name_rows,
    }
    duplicates = {key: rows for key, rows in duplicates.items() if rows}
    top = matches[0] if matches and matches[0]["score"] >= 0.45 else None
    suggested_category = None
    if top:
        suggested_category = {
            "category_code": top.get("category_code"),
            "category_path": top.get("category_path") or "",
            "confidence": round(top["score"] * 100),
            "basis_material_code": top.get("material_code"),
        }
    if identity_rows or spec_rows:
        risk = {"level": "高风险", "action": "禁止直接新增，优先绑定已有物料"}
    elif spec_format_rows:
        risk = {"level": "中风险", "action": "需人工确认是否为同一型号"}
    elif name_rows:
        risk = {"level": "中低风险", "action": "名称可复用，请核对规格、品牌和用途"}
    else:
        risk = {"level": "低风险", "action": "可继续补录，建议由 PMC 最终确认"}
    return {
        "matches": matches,
        "duplicates": duplicates,
        "suggested_category": suggested_category,
        "risk_assessment": risk,
    }


@frappe.whitelist(methods=["POST"])
def save_category(category_code, category_name, parent_category=None, full_path=None, allow_request=1):
    if not _is_pmc_or_manager():
        frappe.throw("只有 PMC 可以维护采购物料编号层级")
    category_code = _validate_category_code(category_code)
    category_name = _text(category_name)
    if not category_name:
        frappe.throw("分类名称不能为空")
    existing = frappe.db.exists("OA Procurement Category", category_code)
    doc = frappe.get_doc("OA Procurement Category", existing) if existing else frappe.new_doc("OA Procurement Category")
    doc.category_code = category_code
    doc.category_name = category_name
    doc.parent_category = _text(parent_category) or None
    doc.full_path = _text(full_path) or category_name
    doc.level = _category_level(category_code)
    doc.allow_request = 1 if int(allow_request or 0) else 0
    doc.is_active = 1
    doc.source = "PMC维护"
    doc.save(ignore_permissions=True)
    return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def save_material(material_code, category_code, material_name, specification, product_desc, brand, unit, **kwargs):
    if not _is_pmc_or_manager():
        frappe.throw("只有 PMC 可以维护采购物料")
    material_code = _text(material_code)
    category_code = _validate_category_code(category_code)
    if _category_level(category_code) < 3:
        frappe.throw("物料编号层级至少需要三级")
    required = {"物料名称": material_name, "规格型号": specification, "产品描述": product_desc, "商品品牌": brand, "计量单位": unit}
    missing = [label for label, value in required.items() if not _text(value)]
    if missing:
        frappe.throw("物料资料不完整：" + "、".join(missing))
    if not material_code:
        frappe.throw("PMC新增物料必须填写物料编号")
    existing = frappe.db.exists("OA Procurement Material", material_code)
    doc = frappe.get_doc("OA Procurement Material", existing) if existing else frappe.new_doc("OA Procurement Material")
    values = {
        "material_code": material_code, "category_code": category_code,
        "category_path": _text(kwargs.get("category_path")), "material_name": _text(material_name),
        "specification": _text(specification), "product_desc": _text(product_desc),
        "brand": _text(brand), "product_name": _text(kwargs.get("product_name")),
        "product_desc_en": _text(kwargs.get("product_desc_en")), "brand_en": _text(kwargs.get("brand_en")),
        "material_attr": _text(kwargs.get("material_attr")) or "外购", "unit": _text(unit),
        "is_active": 1, "source": "PMC维护",
    }
    doc.update(values)
    doc.save(ignore_permissions=True)
    return doc.as_dict()
