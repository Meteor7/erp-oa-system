from datetime import date
import math

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
        def number(value, label):
            try:
                result = float(value or 0)
            except (ValueError, TypeError, OverflowError):
                frappe.throw(f"{label}格式无效。")
            if not math.isfinite(result) or result < 0:
                frappe.throw(f"{label}必须为非负有限数值。")
            return result

        number(self.total_amount, "境外委托研发费用总金额")
        for line in self.lines or []:
            if not line.work_date or not line.project_code or not line.project_name:
                frappe.throw("境外工时必须填写日期、项目代码和项目名称。")
            try:
                work_day = date.fromisoformat(str(line.work_date)[:10])
            except (ValueError, TypeError):
                frappe.throw("境外工时日期无效。")
            if (work_day.year, work_day.month) != (int(self.year), int(self.month)):
                frappe.throw("境外工时日期必须在当前会计期间内。")
            days = number(getattr(line, "occurrence_days", None), "境外发生天数")
            number(line.allocated_amount, "境外分摊金额")
            if days > 0:
                # Monthly rows represent aggregated days, not one workday.
                line.occurrence_days = round(days, 5)
                line.hours = round(line.occurrence_days * 8, 2)
                if line.hours <= 0:
                    frappe.throw("境外发生天数须对应至少0.01小时。")
            else:
                # Legacy daily rows have a NULL/zero occurrence_days column.
                if not line.activity_type:
                    frappe.throw("境外日工时必须填写活动类型。")
                hours = number(line.hours, "境外工时")
                if hours > 8:
                    frappe.throw("境外工时单日不能超过 8 小时。")

    def _check_period_lock(self):
        periods = {"".join(c for c in str(self.period or "") if c.isdigit())[:6]}
        before = self.get_doc_before_save()
        if before is not None:
            periods.add("".join(c for c in str(before.period or "") if c.isdigit())[:6])
        for period in periods:
            if period and frappe.db.exists("RD Period Lock", {"period": period, "docstatus": 1, "lock_allocations": 1}):
                frappe.throw(frappe._("会计期间 {0} 已分摊锁定，不能修改境外委托研发费用。").format(period))
