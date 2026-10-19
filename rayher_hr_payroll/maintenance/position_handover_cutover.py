"""Explicit reviewed position cutover; never a whole-database restore."""
import json
import secrets
from pathlib import Path

def apply(backup, rehearsal=False):
 import frappe
 frappe.only_for("System Manager")
 frappe.flags.in_test=True  # Run new Role Profile updates synchronously, no queued jobs.
 from rayher_hr_payroll.maintenance.identity_alignment import business_snapshot,digest,manifest_path,verify_backup
 from rayher_hr_payroll.oa_role_resolver import ROLE_SPECS,resolve_role
 from rayher_hr_payroll.position_handover import sync_roles,independent_roles
 verify_backup(backup,expected_database=frappe.conf.db_name)
 def business():
  d=business_snapshot({})
  d.pop("tabOA Approval Role Assignment",None)
  return d
 before=business()
 before_users=frappe.db.sql("SELECT * FROM tabUser ORDER BY name",as_dict=True)
 before_employees=frappe.db.sql("SELECT * FROM tabEmployee ORDER BY name",as_dict=True)
 source=json.loads(manifest_path("designation_alignment_manifest.json").read_text(encoding="utf-8"))
 changes=[]
 before_auth=digest(frappe.db.sql("SELECT * FROM __Auth ORDER BY doctype,name,fieldname",as_dict=True))
 profiles={
 "hr_manager":["Employee","HR User","Department Manager"],
 "finance_auditor":["Employee","Accounts User"],
 "finance_accountant":["Employee","Accounts User"],
 "finance_manager":["Employee","Accounts User","Department Manager"],
 "general_manager":["Employee","Accounts User","All Project Access","Department Manager","HR Manager","QIHENG Demo Business Executive"],
 "vice_manager":["Employee","Accounts User","All Project Access","Department Manager","HR Manager","QIHENG Demo Business Executive"],
 "it_asset_owner":["Employee","Department Manager"],
 "pmc":["Employee","Purchase User"],
 "procurement_manager":["Employee","Purchase User"],
 "production_asset_owner":["Employee","Department Manager"]}
 try:
  if not frappe.conf.get("maintenance_mode"):
   raise ValueError("Maintenance required")
  by_id={r.name:r for r in before_employees}
  for item in source:
   current=by_id.get(item["name"])
   if not current or current.employee_name!=item["employee_name"]:
    raise ValueError("Employee identity mismatch")
   if (current.designation or None)!=(item["designation"] or None):
    value=item["designation"] or None
    if value and not frappe.db.exists("Designation",value):
     frappe.get_doc({"doctype":"Designation","designation_name":value}).insert(ignore_permissions=True)
    frappe.db.set_value("Employee",current.name,"designation",value,update_modified=False)
    changes.append({"employee":current.name,"before":current.designation,"after":value})
  if "HR-EMP-90006" in by_id:
   from rayher_hr_payroll.maintenance.designation_alignment import references
   excluded=by_id["HR-EMP-90006"]
   assert excluded.employee_name=="演示员工182" and not excluded.user_id
   assert not references(excluded.name,excluded.employee_name),"Excluded employee has historical references"
   frappe.delete_doc("Employee",excluded.name,ignore_permissions=True)
  holders={key:resolve_role(key) for key in ROLE_SPECS}
  employee=frappe.db.get_value("Employee",{"user_id":holders["hr_manager"]["user"]},"name")
  if not employee:
   doc=frappe.get_doc({"doctype":"Employee","first_name":"William","last_name":"Liu","company":"QIHENG Demo","department":"人事行政部 - RAY","designation":"人事行政经理","status":"Active","naming_series":"HR-EMP-.#####","create_user_permission":0})
   doc.flags.ignore_mandatory=True
   doc.insert(ignore_permissions=True)
   employee=doc.name
   frappe.db.set_value("Employee",employee,"user_id",holders["hr_manager"]["user"],update_modified=False)
  holders["hr_manager"]["employee"]=employee
  by_employee={v["employee"]:k for k,v in holders.items() if v["employee"]}
  # Create profile data first. Do not mutate any global existing role profile.
  for key,roles in profiles.items():
   name="岗位交接-"+key
   if not frappe.db.exists("Role Profile",name):
    profile=frappe.get_doc({"doctype":"Role Profile","name":name,"role_profile":name,"roles":[{"role":r} for r in roles]})
    profile.unlock()
    profile.insert(ignore_permissions=True)
  # Establish assignment rows before resolving parent links.
  for key,v in holders.items():
   if not frappe.db.exists("OA Approval Role Assignment",key):
    frappe.get_doc({"doctype":"OA Approval Role Assignment","role_key":key,"role_label":v["role_label"],"employee":v["employee"],"user":v["user"],"enabled":1}).insert(ignore_permissions=True)
  # Topological order: parents before children.
  order=["general_manager","vice_manager","finance_manager","hr_manager","production_asset_owner","it_asset_owner","pmc","procurement_manager","finance_auditor","finance_accountant"]
  for key in order:
   v=holders[key]
   doc=frappe.get_doc("OA Approval Role Assignment",key)
   parent=frappe.db.get_value("Employee",v["employee"],"reports_to")
   doc.employee=v["employee"];doc.user=v["user"]
   doc.role_profile="岗位交接-"+key
   doc.parent_position="general_manager" if key=="hr_manager" else by_employee.get(parent)
   doc.save(ignore_permissions=True)
  for person in ["演示员工38","演示员工30"]:
   target=frappe.db.get_value("Employee",{"employee_name":person,"status":"Active"},"name")
   assert target
   frappe.db.set_value("Employee",target,"reports_to",employee)
  from frappe.utils.nestedset import rebuild_tree
  rebuild_tree("Employee","reports_to")
  for person,key in [("演示员工10","hr_manager"),("演示员工13","finance_auditor")]:
   old=frappe.db.get_value("Employee",{"employee_name":person},["user_id","status"],as_dict=True)
   assert old.status=="Left"
   sync_roles(old.user_id,set(profiles[key]),set(),independent_roles(old.user_id,key))
  after=business()
  differences=[k for k in set(before)|set(after) if before.get(k)!=after.get(k)]
  assert not differences,differences
  assert before_auth==digest(frappe.db.sql("SELECT * FROM __Auth ORDER BY doctype,name,fieldname",as_dict=True))
  report={"william_employee":employee,"parent":frappe.db.get_value("Employee",frappe.db.get_value("Employee",employee,"reports_to"),"employee_name"),"reports":frappe.get_all("Employee",filters={"reports_to":employee},pluck="employee_name"),"roles":frappe.get_all("Has Role",filters={"parent":holders["hr_manager"]["user"],"parenttype":"User"},pluck="role"),"business_tables_unchanged":len(before),"passwords_unchanged":True}
  print(json.dumps(report,ensure_ascii=False))
 
  # Verify existing employee fields: only reviewed designation, two reports_to,
  # and derived nested-set/modified metadata may differ.
  expected={r.name:dict(r) for r in before_employees if r.name!="HR-EMP-90006"}
  for change in changes: expected[change["employee"]]["designation"]=change["after"]
  for r in expected.values():
   if r["employee_name"] in ["演示员工38","演示员工30"]:r["reports_to"]=employee
  ignored={"lft","rgt","modified","modified_by"}
  for r in frappe.db.sql("SELECT * FROM tabEmployee ORDER BY name",as_dict=True):
   if r.name in expected:
    assert {k:v for k,v in r.items() if k not in ignored}=={k:v for k,v in expected[r.name].items() if k not in ignored},r.name
   else:
    assert r.name==employee and r.employee_name=="William Liu"
    assert not r.date_of_birth and not r.date_of_joining and not r.gender
  assert before_users==frappe.db.sql("SELECT * FROM tabUser ORDER BY name",as_dict=True)
  # Align the explicitly authorized total-control roles without altering credentials.
  admin="admin@staff.example.invalid"
  sync_roles(admin,set(),{"Accounts User","All Project Access","Department Manager","HR Manager","QIHENG Demo Business Executive","System Manager"},set())
  report.update(designation_changes=changes,excluded_removed="HR-EMP-90006" in by_id,backup=backup)
  path=Path(frappe.get_site_path("private","position-handover"))
  path.mkdir(parents=True,exist_ok=True)
  report_path=path/(secrets.token_hex(8)+".json")
  if rehearsal:
   # Exercise the real controller with a replacement, then roll everything back.
   assignment=frappe.get_doc("OA Approval Role Assignment","hr_manager")
   replacement=frappe.db.get_value("Employee",{"employee_name":"演示员工30"},["name","user_id"],as_dict=True)
   assignment.employee=replacement.name;assignment.user=replacement.user_id
   assignment.save(ignore_permissions=True)
   assert frappe.db.get_value("Employee",{"employee_name":"演示员工38"},"reports_to")==replacement.name
   assert "HR User" not in frappe.get_all("Has Role",filters={"parent":holders["hr_manager"]["user"],"parenttype":"User"},pluck="role")
   assert business()==before
   frappe.db.rollback()
   report["state"]="rehearsed-and-rolled-back"
  else:
   report["state"]="commit-started"
   report_path.write_text(json.dumps(report,ensure_ascii=False,default=str),encoding="utf-8")
   report_path.chmod(0o600)
   frappe.db.commit()
   report["state"]="committed"
  report_path.write_text(json.dumps(report,ensure_ascii=False,default=str),encoding="utf-8")
  report_path.chmod(0o600)
  frappe.clear_cache()
  return {"report":str(report_path),**report}
 except Exception:
  frappe.db.rollback()
  raise
 