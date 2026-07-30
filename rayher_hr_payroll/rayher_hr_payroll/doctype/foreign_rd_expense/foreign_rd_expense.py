import frappe
from frappe.model.document import Document

from rayher_hr_payroll.period_controls import normalize_period_fields


class ForeignRDExpense(Document):
    def autoname(self):
        self._normalize_period()
        self.name = f"FRD-{int(self.year):04d}-{int(self.month):02d}"

    def before_insert(self):
        self._normalize_period()

    def validate(self):
        self._normalize_period()
        self._check_amounts()
        self.total_hours = sum((line.hours or 0) for line in (self.lines or []))
        self.status = "Calculated" if self.lines or (self.total_amount or 0) else "Draft"
        self._check_period_lock()

    def on_trash(self):
        self._check_period_lock()

    def _normalize_period(self):
        normalize_period_fields(self, throw=frappe.throw, translate=frappe._)

    def _check_amounts(self):
        if (self.total_amount or 0) < 0:
            frappe.throw(frappe._("\u5883\u5916\u59d4\u6258\u7814\u53d1\u8d39\u7528\u603b\u91d1\u989d\u4e0d\u80fd\u4e3a\u8d1f\u6570\u3002"))
        for line in self.lines or []:
            if not line.work_date or not line.activity_type or not line.project_code or not line.project_name:
                frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u5fc5\u987b\u586b\u5199\u65e5\u671f\u3001\u6d3b\u52a8\u7c7b\u578b\u3001\u9879\u76ee\u4ee3\u7801\u548c\u9879\u76ee\u540d\u79f0\u3002"))
            if (line.hours or 0) < 0 or (line.allocated_amount or 0) < 0:
                frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u548c\u5206\u644a\u91d1\u989d\u4e0d\u80fd\u4e3a\u8d1f\u6570\u3002"))
            if (line.hours or 0) > 8:
                frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u5355\u65e5\u4e0d\u80fd\u8d85\u8fc7 8 \u5c0f\u65f6\u3002"))

    def _check_period_lock(self):
        period = "".join(c for c in str(self.period or "") if c.isdigit())[:6]
        if period and frappe.db.exists("RD Period Lock", {"period": period, "docstatus": 1, "lock_allocations": 1}):
            frappe.throw(frappe._("\u4f1a\u8ba1\u671f\u95f4 {0} \u5df2\u5206\u644a\u9501\u5b9a\uff0c\u4e0d\u80fd\u4fee\u6539\u5883\u5916\u59d4\u6258\u7814\u53d1\u8d39\u7528\u3002").format(period))
