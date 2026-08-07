import re

import frappe
from frappe.model.document import Document


class AccommodationDeduction(Document):
    def before_insert(self):
        # Normalize before autoname (DORM-.{period}.-.####) so the document name
        # uses the canonical YYYY-MM, matching the stored period.
        self._canonical_period()

    def validate(self):
        self._canonical_period()
        self._check_amounts()
        self.personal_total_amount = (self.personal_rent_amount or 0) + (self.personal_water_amount or 0) + (self.personal_electricity_amount or 0)
        self.company_total_amount = (self.company_rent_amount or 0) + (self.company_water_amount or 0) + (self.company_electricity_amount or 0)
        self.rent_amount = (self.personal_rent_amount or 0) + (self.company_rent_amount or 0)
        self.water_amount = (self.personal_water_amount or 0) + (self.company_water_amount or 0)
        self.electricity_amount = (self.personal_electricity_amount or 0) + (self.company_electricity_amount or 0)
        self.total_amount = self.personal_total_amount + self.company_total_amount
        self._check_not_exported()
        self._check_period_lock()
        self._check_duplicate()

    def _check_not_exported(self):
        # Once exported to finance the record is frozen for routine HR/Accounts
        # edits, but System Manager can still correct/clear it (the flag is also
        # read_only in the doctype, so it can no longer be checked by accident).
        if (not self.is_new() and self.get_db_value("exported_to_finance")
                and "System Manager" not in frappe.get_roles()):
            frappe.throw(frappe._("该宿舍代扣已导出财务，不可修改（如需更正请联系系统管理员）。"))

    def on_trash(self):
        self._check_period_lock()
        if (self.get_db_value("exported_to_finance")
                and "System Manager" not in frappe.get_roles()):
            frappe.throw(frappe._("该宿舍代扣已导出财务，不可删除（如需更正请联系系统管理员）。"))

    def _canonical_period(self):
        raw = str(self.period or "").strip()
        if not raw:
            return
        # Accept YYYY-MM, YYYYMM, and single-digit months (2026-1); normalize to
        # YYYY-MM. Reject anything else so a malformed period (e.g. "2026-1"
        # left un-normalized) can never slip past the period-lock / duplicate /
        # report filters, which all key off this value.
        m = re.fullmatch(r"(\d{4})-?(\d{1,2})", raw)
        if not m or not (1 <= int(m.group(2)) <= 12):
            frappe.throw(frappe._("期间格式无效，应为 YYYY-MM（例如 2026-01）。"))
        self.period = "%04d-%02d" % (int(m.group(1)), int(m.group(2)))

    def _check_amounts(self):
        if min((self.personal_rent_amount or 0), (self.personal_water_amount or 0), (self.personal_electricity_amount or 0), (self.company_rent_amount or 0), (self.company_water_amount or 0), (self.company_electricity_amount or 0)) < 0:
            frappe.throw(frappe._("金额不能为负数。"))

    def _check_period_lock(self):
        # Check BOTH the new and the pre-save period: a record currently in a
        # locked period must not be edited even to MOVE it to an unlocked period
        # (that would silently remove locked-period data). Robust digit parse
        # tolerates legacy separators / single-digit months; fail closed.
        def _key(val):
            d = "".join(c for c in str(val or "") if c.isdigit())
            return (d[:4] + d[4:6].zfill(2)) if len(d) >= 5 else None
        periods = {_key(self.period)}
        before = self.get_doc_before_save()
        if before is not None:
            periods.add(_key(before.get("period")))
        for digits in periods:
            if digits and frappe.db.exists(
                "RD Period Lock", {"period": digits, "docstatus": 1, "lock_timesheets": 1}
            ):
                frappe.throw(frappe._("会计期间 {0} 已锁定，不能修改宿舍代扣。").format(digits))

    def _check_duplicate(self):
        if self.employee and self.period:
            dup = frappe.db.exists(
                "Accommodation Deduction",
                {"employee": self.employee, "period": self.period, "name": ["!=", self.name or ""]},
            )
            if dup:
                frappe.throw(frappe._("该员工在期间 {0} 已有宿舍代扣记录（{1}），不能重复。").format(self.period, dup))
