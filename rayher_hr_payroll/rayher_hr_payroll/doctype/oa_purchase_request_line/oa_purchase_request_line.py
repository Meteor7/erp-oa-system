from datetime import date
import frappe
from frappe.model.document import Document


class OAPurchaseRequestLine(Document):
    def before_insert(self):
        if not self.material_serial:
            self.material_serial = f"MAT-{date.today().year}-{frappe.model.naming.make_autoname('MAT-.#####').split('-')[-1]}"