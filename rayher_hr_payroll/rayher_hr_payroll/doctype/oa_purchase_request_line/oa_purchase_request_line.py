from datetime import date
import frappe
from frappe.model.document import Document
from rayher_hr_payroll import site_time


class OAPurchaseRequestLine(Document):
    def before_insert(self):
        if not self.material_serial:
            self.material_serial = f"MAT-{site_time.today().year}-{frappe.model.naming.make_autoname('MAT-.#####').split('-')[-1]}"