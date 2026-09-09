"""Import the reference PMC material catalog into local configurable DocTypes."""


def _text(value):
    return str(value or "").strip()


def _parts(code):
    return [part for part in _text(code).split(".") if part]


def import_rows(material_rows, *, category_rows=None, source="PMC material-share"):
    import frappe

    categories = {}
    for row in category_rows or []:
        code = _text(row.get("prefix") or row.get("category_code"))
        if not code:
            continue
        categories[code] = {
            "category_code": code,
            "category_name": _text(row.get("name") or row.get("category_name") or code),
            "full_path": _text(row.get("full_name") or row.get("full_path") or row.get("name") or code),
            "parent_category": _text(row.get("parent_prefix") or row.get("parent_category")) or None,
            "level": int(row.get("level") or len(_parts(code))),
            "allow_request": 1,
            "is_active": 1,
            "source": source,
        }
    materials = []
    for row in material_rows or []:
        row = row or {}
        prefix = _text(row.get("category_prefix"))
        if prefix:
            code_parts = _parts(prefix)
            names = _text(row.get("category_full_name")).split("_")
            for index in range(1, len(code_parts) + 1):
                code = ".".join(code_parts[:index])
                categories.setdefault(code, {
                    "category_code": code,
                    "category_name": _text(names[index - 1] if index - 1 < len(names) else code_parts[index - 1]),
                    "full_path": "_".join(names[:index]) if names else code,
                    "parent_category": ".".join(code_parts[:index - 1]) or None,
                    "level": index,
                    "allow_request": 1,
                    "is_active": 1,
                    "source": source,
                })
        materials.append({
            "material_code": _text(row.get("code")),
            "category_code": prefix,
            "category_path": _text(row.get("category_full_name")),
            "material_name": _text(row.get("name")),
            "specification": _text(row.get("spec")),
            "product_desc": _text(row.get("product_desc")),
            "brand": _text(row.get("brand")),
            "product_name": _text(row.get("product_name")),
            "product_desc_en": _text(row.get("product_desc_en")),
            "brand_en": _text(row.get("brand_en")),
            "material_attr": _text(row.get("material_attr")) or "外购",
            "unit": _text(row.get("unit") or row.get("unit_group")) or "个",
            "is_active": 0 if _text(row.get("material_status")) in {"停用", "已停用"} else 1,
            "source": source,
            "external_id": str(row.get("id") or ""),
        })

    category_count = 0
    for values in categories.values():
        name = frappe.db.exists("OA Procurement Category", values["category_code"])
        doc = frappe.get_doc("OA Procurement Category", name) if name else frappe.new_doc("OA Procurement Category")
        doc.update(values)
        doc.save(ignore_permissions=True)
        category_count += 1
    material_count = 0
    for values in materials:
        if not values["material_code"] or not values["category_code"]:
            continue
        name = frappe.db.exists("OA Procurement Material", values["material_code"])
        doc = frappe.get_doc("OA Procurement Material", name) if name else frappe.new_doc("OA Procurement Material")
        doc.update(values)
        doc.save(ignore_permissions=True)
        material_count += 1
    frappe.db.commit()
    return {"categories": category_count, "materials": material_count}
