import hashlib
import re

import frappe
from frappe.model.document import Document

from rayher_hr_payroll.import_controls import validate_expense_import
from rayher_hr_payroll.period_controls import normalize_period_fields


class RDExpenseImport(Document):
    def before_insert(self):
        self._normalize_period()

    def validate(self):
        self._normalize_period()
        self.active_period_key = self.period if int(self.docstatus or 0) < 2 else None
        self._ensure_hash()
        self._check_not_allocated()
        self._check_period_lock()
        validate_expense_import(self)

    def before_submit(self):
        # An empty / all-zero import must not be submittable: once submitted it
        # blocks any replacement for the period (_check_unique_period), yet
        # Accounts User cannot cancel/delete it -- a permanent period squat.
        if not self.items or not any((it.amount or 0) != 0 for it in self.items):
            frappe.throw(frappe._("费用导入单至少需有一条金额非零的费用明细，不能提交。"))
        # Reject duplicate GL source row KEYS at submit using the SAME key the
        # allocator rejects, so a duplicate-laden import cannot be submitted and
        # then squat the period while allocation keeps failing. Rows that merely look
        # alike (same voucher / account / amount / project) are allowed: the same item
        # can be bought several times; the import page only reminds about them.
        from rayher_hr_payroll.rd_cost.frappe_adapter import source_row_key_for_row
        seen = set()
        for it in self.items:
            k = source_row_key_for_row(it)
            if k in seen:
                frappe.throw(frappe._("费用明细存在重复行（{0}），不能提交。").format(k))
            seen.add(k)

    def on_submit(self):
        self.db_set("status", "Imported")

    def before_cancel(self):
        self.active_period_key = None

    def on_cancel(self):
        self._check_period_lock()
        if frappe.db.exists("RD Cost Allocation", {"expense_import": self.name, "docstatus": 1}):
            frappe.throw(frappe._("本费用导入仍被已提交的分摊单引用，请先撤销分摊单后再取消。"))
        self.db_set("status", "Cancelled")

    def on_trash(self):
        self._check_period_lock()

    def _normalize_period(self):
        normalize_period_fields(self, throw=frappe.throw, translate=frappe._)

    def _ensure_hash(self):
        # Always derive the hash from the CURRENT source file so replacing the
        # attachment refreshes the audit hash. If a source file is attached but
        # cannot be read, fail loudly rather than fall back to a random hash that
        # would silently corrupt the audit trail.
        if self.source_file:
            try:
                f = frappe.get_doc("File", {"file_url": self.source_file})
                content = f.get_content()
            except Exception:
                # Fail loudly only when the attachment is set/changed on THIS
                # save; tolerate a pre-existing import whose File was later
                # removed so the record stays editable (on_trash/on_cancel do
                # not run validate).
                if self.is_new() or self.has_value_changed("source_file"):
                    frappe.throw(frappe._("无法读取源文件以计算校验哈希，请检查附件后重试。"))
                return
            if isinstance(content, str):
                content = content.encode("utf-8", "ignore")
            self.source_file_hash = hashlib.sha256(content).hexdigest()
            return
        # No attachment. On an EXISTING record, drop a hash left over from a
        # now-removed file. On a NEW record keep an explicitly-supplied hash
        # (e.g. demo imports set source_file_hash directly) -- has_value_changed
        # is always true for new docs, so guard on is_new() to avoid wiping it.
        if not self.is_new() and self.has_value_changed("source_file"):
            self.source_file_hash = None
        if not self.source_file_hash:
            self.source_file_hash = frappe.generate_hash(length=16)

    def _check_not_allocated(self):
        # Block edits only while a SUBMITTED allocation references this import.
        # Drafts are intentionally NOT blocked: submit recomputes the allocation
        # from current source data (RDCostAllocation.before_submit), so a draft
        # can never lock in stale data, and blocking drafts would strand the
        # import -- Accounts User can create allocations but not delete/cancel them.
        if self.is_new():
            return
        if frappe.db.exists(
            "RD Cost Allocation", {"expense_import": self.name, "docstatus": 1}
        ):
            frappe.throw(frappe._("本费用导入已被已提交的分摊单引用，请先撤销分摊单后再修改费用导入。"))

    def _check_period_lock(self):
        # Check BOTH new and pre-save period so a locked-period import cannot be
        # edited out of the locked period (which would remove locked GL data).
        periods = {"".join(c for c in str(self.period or "") if c.isdigit())[:6]}
        before = self.get_doc_before_save()
        if before is not None:
            periods.add("".join(c for c in str(before.get("period") or "") if c.isdigit())[:6])
        for digits in periods:
            if digits and frappe.db.exists(
                "RD Period Lock", {"period": digits, "docstatus": 1, "lock_gl_import": 1}
            ):
                frappe.throw(frappe._("会计期间 {0} 已锁定（费用导入），不能修改。").format(digits))
