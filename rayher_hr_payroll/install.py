from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from rayher_hr_payroll.custom_fields import CUSTOM_FIELDS


def after_install():
    create_custom_fields(CUSTOM_FIELDS, update=True)