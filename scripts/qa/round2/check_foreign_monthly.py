import sys,json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_transaction_locks import connect
import frappe
connect()
try:
    from rayher_hr_payroll.api.foreign_rd_entry import save_foreign_rd
    users=frappe.get_all("Has Role",filters={"role":"Accounts User","parenttype":"User"},pluck="parent")
    user=next(u for u in users if u!="Administrator" and frappe.db.get_value("User",u,"enabled"))
    project=frappe.get_all("Project",filters={"allow_rd_timesheet":1},pluck="name",limit=1)[0]
    activity=frappe.get_all("Activity Type",pluck="name",limit=1)[0]
    assert not frappe.db.exists("Foreign RD Expense",{"year":2098,"month":10})
    frappe.set_user(user)
    for days,kind in [(1,""),(2,activity)]:
        try:
            result=save_foreign_rd("2098-10",rows=[dict(project=project,occurrence_days=days,activity_type=kind)])
            stored=frappe.get_doc("Foreign RD Expense",result["name"])
            assert stored.total_hours==days*8
            print(json.dumps({"days":days,"activity_given":bool(kind),"saved":True}))
        except Exception as e:
            raise
        finally:frappe.db.rollback()
finally:
    frappe.set_user("Administrator")
    for name in frappe.get_all("Foreign RD Expense",filters={"year":2098,"month":10},pluck="name"):
        frappe.delete_doc("Foreign RD Expense",name,ignore_permissions=True,force=True)
    frappe.db.commit();frappe.destroy()
