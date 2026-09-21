import sys,json
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_transaction_locks import connect
from test_oa_security import ordinary_user
import frappe

def migration_probe():
    connect()
    try:
        from frappe.client import set_value
        from rayher_hr_payroll.patches.v1_0 import migrate_active_oa_approvers as migration
        attacker=ordinary_user()
        frappe.set_user("Administrator")
        name=frappe.get_all("OA Approval Request",filters={"workflow_status":["in",list(migration.ACTIVE_REQUEST_STATUSES)]},pluck="name",limit=1)[0]
        doc=frappe.get_doc("OA Approval Request",name)
        step=next(s for s in doc.steps if s.status in migration.UNRESOLVED_STEP_STATUSES)
        alias="REVIEW Unique Legacy Approver"
        # Seed a legacy-name step; only this fixture bypasses normal authoring.
        frappe.db.set_value(step.doctype,step.name,"approvers",json.dumps([alias]))
        frappe.set_user(attacker)
        set_value("User",attacker,{"first_name":alias,"last_name":""})
        frappe.set_user("Administrator")
        assert migration._resolve_user(alias) != attacker
        print(json.dumps({"legacy_alias_resolves_attacker":migration._resolve_user(alias)==attacker}))
        try:
            report=migration.execute()
            stored=frappe.db.get_value(step.doctype,step.name,"approvers")
            assert json.loads(stored) != [attacker]
            assert any(r["request"]==name for r in report["unresolved"])
            print(json.dumps({"legacy_migration_changed_steps":report["changed_steps"],"legacy_step_routed_to_attacker":False,"unresolved_is_reported":True}))
            frappe.db.set_value(step.doctype,step.name,"approvers",json.dumps([migration.GENERAL]))
            report=migration.execute()
            stored=frappe.db.get_value(step.doctype,step.name,"approvers")
            assert json.loads(stored)==[migration.GENERAL_USER]
            print(json.dumps({"reviewed_legacy_mapping_applied":True}))
        except frappe.PermissionError:
            raise
    finally:
        frappe.db.rollback();frappe.destroy()

def rd_probe():
    connect()
    try:
        frappe.set_user("Administrator")
        candidates=frappe.db.sql("""select ts.employee,year(d.from_time) as yr,month(d.from_time) as mo
        from `tabTimesheet Detail` d join `tabTimesheet` ts on ts.name=d.parent
        join `tabEmployee` e on e.name=ts.employee join `tabProject` p on p.name=d.project
        where ts.docstatus=1 and e.rd_personnel_type='全时研发' and p.allow_rd_timesheet=1
        order by d.from_time desc limit 1""",as_dict=True)
        assert candidates,"Need full time RD employee with submitted hours"
        row=candidates[0]
        lock=frappe.get_doc(dict(doctype="RD Period Lock",year=row.yr,month=row.mo,lock_project_stage=1))
        lock.insert();lock.submit()
        employee=frappe.get_doc("Employee",row.employee)
        employee.rd_personnel_type="非全时研发"
        try:
            employee.save()
            raise AssertionError("Locked allocation policy changed")
        except frappe.ValidationError as exc:
            assert "已锁定期间" in str(exc)
            print(json.dumps({"locked_period_type_change_blocked":True}))
    finally:
        frappe.db.rollback();frappe.destroy()

if __name__=="__main__":
    migration_probe()
    rd_probe()
