import sys,json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_transaction_locks import connect
import frappe

def room_probe():
    connect()
    room_name="REVIEW-ROOM-ONLY-2098"
    names=[]
    try:
        frappe.set_user("Administrator")
        assert not frappe.db.exists("Accommodation Room",room_name)
        employees=[]
        for e in frappe.get_all("Employee",filters={"status":"Active"},pluck="name"):
            if not frappe.db.exists("Accommodation Occupancy",{"employee":e,"is_active":1}):employees.append(e)
            if len(employees)==2:break
        assert len(employees)==2
        frappe.get_doc(dict(doctype="Accommodation Room",room_no=room_name,is_active=1,monthly_rent=100,default_rent=100)).insert()
        from rayher_hr_payroll.api.accommodation_entry import save_occupancy
        from rayher_hr_payroll.api.accommodation_master_entry import list_rooms
        names.append(save_occupancy(employees[0],room_name,"2026-09-01")["name"])
        try:
            save_occupancy(employees[1],room_name,"2026-09-01")
            raise AssertionError("Second active occupant was accepted")
        except frappe.ValidationError:
            frappe.db.rollback()

        count=frappe.db.count("Accommodation Occupancy",{"room":room_name,"is_active":1})
        assert count == 1
        visible=[r for r in list_rooms() if r["name"]==room_name]
        print(json.dumps({"room_active_occupants":count,"room_display_rows":len(visible),"room_display_employee_count":sum(bool(r.get("employee")) for r in visible)}))
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")
        for n in names:
            if frappe.db.exists("Accommodation Occupancy",n):frappe.delete_doc("Accommodation Occupancy",n,ignore_permissions=True,force=True)
        if frappe.db.exists("Accommodation Room",room_name):frappe.delete_doc("Accommodation Room",room_name,ignore_permissions=True,force=True)
        frappe.db.commit();frappe.destroy()

if __name__=="__main__":room_probe()
