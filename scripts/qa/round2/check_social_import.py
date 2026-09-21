import sys,json,uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_transaction_locks import connect
import frappe
connect();batch_name=row_name=None
try:
    from frappe.client import set_value
    from rayher_hr_payroll.api.social_insurance_import_entry import confirm_social_row,activate_social_batch
    from rayher_hr_payroll.api._guards import HR_SENSITIVE_HIDDEN_USERS
    users=frappe.get_all("Has Role",filters={"role":"HR User","parenttype":"User"},pluck="parent")
    user=next(u for u in users if u not in HR_SENSITIVE_HIDDEN_USERS and u!="Administrator" and "System Manager" not in frappe.get_roles(u) and frappe.db.get_value("User",u,"enabled"))
    period="2098-12"
    assert not frappe.db.exists("Social Insurance Import Batch",{"period":period})
    template_name=frappe.get_all("Social Insurance Import Row",filters={"employee":["is","set"]},pluck="name",limit=1)[0]
    row=frappe.copy_doc(frappe.get_doc("Social Insurance Import Row",template_name))
    batch=frappe.copy_doc(frappe.get_doc("Social Insurance Import Batch",row.batch))
    batch.update(dict(period=period,company=None,status="Pending Activation",is_current=0,file_hash=uuid.uuid4().hex,batch_key="REVIEW-"+uuid.uuid4().hex))
    other_employee=frappe.get_all("Employee",filters={"company":"示例研发中心","status":"Active"},fields=["name","employee_name","company"],limit=1)[0]
    frappe.set_user(user)
    from rayher_hr_payroll.social_import_mutation_guard import social_import_action
    social_import_action(lambda: batch.insert())();batch_name=batch.name
    row.update(dict(batch=batch.name,period=period,status="Matched",original_match_status="Matched",employee=other_employee.name,employee_name=other_employee.employee_name,company=other_employee.company))
    row.row_key=batch.name+"|"+str(row.source_row)
    social_import_action(lambda: row.insert())();row_name=row.name
    activate_social_batch(batch.name)
    assert frappe.db.get_value("Social Insurance Import Batch",batch.name,"status")=="Current"
    from rayher_hr_payroll.api.hr_payroll_entry import _social_record
    selected=_social_record(row.employee,period,["employee_total"])
    print(json.dumps({"mixed_company_batch_defaults_to_different_company":batch.company!=other_employee.company,"activated_row_exists":frappe.db.exists("Social Insurance Import Row",row.name) is not None,"payroll_reads_activated_row":selected is not None,"payroll_selected":bool(selected)}))
    blocked=False
    try:confirm_social_row(row.name,remark="REVIEW protected current batch")
    except frappe.ValidationError:blocked=True
    before=float(row.employee_total or 0)
    native_blocked=False
    try:set_value("Social Insurance Import Row",row.name,"employee_total",before+100)
    except frappe.PermissionError:native_blocked=True
    after=frappe.db.get_value("Social Insurance Import Row",row.name,"employee_total")
    print(json.dumps({"activated_via_real_api":True,"actor_has_system_manager":False,"current_batch_api_edit_blocked":blocked,"native_edit_allowed":float(after)==before+100,"native_blocked":native_blocked,"test_delta":100}))
    assert selected is not None and native_blocked and float(after)==before
finally:
    frappe.db.rollback();frappe.set_user("Administrator")
    if row_name:frappe.db.delete("Social Insurance Import Row",{"name":row_name})
    if batch_name:frappe.db.delete("Social Insurance Import Batch",{"name":batch_name})
    frappe.db.commit();frappe.destroy()
