import sys,json,base64,uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_transaction_locks import connect
from round2_procurement_race import erase
import frappe
connect();name=None;source=None;files=[]
try:
 from rayher_hr_payroll.api import procurement_chain as api
 from rayher_hr_payroll.procurement_mutation_guard import procurement_action
 from rayher_hr_payroll.position_access import position_user
 purchaser=position_user("procurement_manager");production=position_user("production_asset_owner")
 frappe.set_user(purchaser)
 from rayher_hr_payroll.api import oa_entry as oa
 ctx=oa._employee_context()
 source=frappe.get_doc(dict(doctype="OA Approval Request",request_type="采购申请",subject="REVIEW fulfillment source",employee=ctx["employee"],department=ctx["department"],company=frappe.db.get_value("Employee",ctx["employee"],"company"),workflow_status="已完成",approved_amount=1000,amount=1000,business_lines=[dict(item_name="REVIEW fulfillment",quantity=10,unit="件",unit_price=100)]))
 oa._insert_document(source)
 @procurement_action
 def fixture():
  return frappe.get_doc(dict(doctype="OA Purchase Order",supplier="REVIEW supplier",status="供应商制作中",contract_status="已生效",total_amount=1000,currency="CNY",lines=[dict(source_request=source.name,source_line=source.business_lines[0].name,item_name="REVIEW fulfillment",material_serial="REVIEW-FULFILL",quantity=10,unit="件",unit_price=100,total_price=1000,received_quantity=0,inspection_status="未验收")],payment_plan=[dict(installment_no=1,installment_name="尾款",payment_stage="尾款",trigger_condition="验收通过",invoice_requirement="付款后提供",percentage=100,amount=1000,status="待审批",approval_status="未发起")])).insert(ignore_permissions=True)
 po=fixture();name=po.name;line=po.lines[0].name;row=po.payment_plan[0].name;frappe.db.commit()
 def file_for(actor):
  frappe.set_user(actor)
  f=frappe.get_doc(dict(doctype="File",file_name="review-"+uuid.uuid4().hex+".png",is_private=1,content=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJp8AAAAASUVORK5CYII="))).insert(ignore_permissions=True)
  files.append(f.name);return f
 receipt=file_for(production)
 api.record_po_receipt(name,[dict(line=line,quantity=1)],arrival_date="2026-09-21",file_ref=receipt.name)
 inspection=file_for(purchaser)
 api.record_po_inspection(name,[dict(line=line,status="已通过")],inspection_date="2026-09-21",file_ref=inspection.name)
 po.reload();work=api._payment_work_item(po,po.payment_plan[0])
 facts=dict(ordered=10,received=po.lines[0].received_quantity,inspection=po.lines[0].inspection_status,ui_can_push=work["can_push_payment"],ui_blockers=work["blockers"])
 try:
  result=api.push_po_payment_request(name,row);facts["push_succeeded"]=True;facts["payment_request"]=result["payment_request"]
 except Exception as e:
  frappe.db.rollback();facts["push_succeeded"]=False;facts["push_error"]=str(e)
 print(json.dumps({"payment_trigger":facts},ensure_ascii=False))
 linkage=[]
 for fid in files:
  f=frappe.get_doc("File",fid)
  try: allowed=bool(frappe.has_permission("File",ptype="read",doc=f))
  except Exception as e: allowed=type(e).__name__
  linkage.append(dict(parent_type=f.attached_to_doctype,parent_exists=bool(frappe.db.exists(f.attached_to_doctype,f.attached_to_name)),fulfillment_exists=bool(frappe.db.exists("OA PO Fulfillment Record",f.attached_to_name)),purchaser_read=allowed))
 print(json.dumps({"fulfillment_file_links":linkage},ensure_ascii=False))
 assert facts["push_succeeded"] is False and "全部到货" in facts["push_error"]
 assert all(r["parent_exists"] and r["purchaser_read"] is True for r in linkage)
 from test_oa_security import ordinary_user
 normal=ordinary_user();frappe.set_user(normal)
 assert all(not frappe.has_permission("File",ptype="read",doc=frappe.get_doc("File",fid)) for fid in files)
 frappe.set_user(production)
 assert all(frappe.has_permission("File",ptype="read",doc=frappe.get_doc("File",fid)) for fid in files)
 receipt2=file_for(production)
 api.record_po_receipt(name,[dict(line=line,quantity=9)],arrival_date="2026-09-21",file_ref=receipt2.name)
 inspection2=file_for(purchaser)
 api.record_po_inspection(name,[dict(line=line,status="已通过")],inspection_date="2026-09-21",file_ref=inspection2.name)
 good=api.push_po_payment_request(name,row)
 print(json.dumps({"fully_received_payment_created":bool(good["payment_request"]),"ordinary_evidence_denied":True,"production_evidence_read":True}))
 assert good["payment_request"]
 # Seed a corrected historical inspection state to test release revalidation.
 frappe.db.set_value("OA Purchase Order Line",line,"inspection_status","不合格")
 payment=frappe.get_doc("OA Approval Request",good["payment_request"])
 try:
  oa._validate_procurement_payment_release(payment)
  raise AssertionError("Invalidated inspection still permits payment release")
 except frappe.ValidationError as exc:
  assert "验收通过" in str(exc)
 file_id=files[0]
 frappe.db.set_value("File",file_id,"attached_to_doctype","OA Business Document")
 from rayher_hr_payroll.patches.v1_0.repair_po_fulfillment_file_links import execute
 execute()
 assert frappe.db.get_value("File",file_id,"attached_to_doctype")=="OA PO Fulfillment Record"
 print(json.dumps({"invalidated_inspection_blocks_release":True,"legacy_attachment_repaired":True}))

finally:
 frappe.db.rollback();frappe.set_user("Administrator")
 if name:
  payments=frappe.get_all("OA Approval Request",filters={"source_purchase_order":name},pluck="name")
  for dt in ["ToDo","Notification Log"]:
   if payments:
    if dt=="ToDo":frappe.db.delete(dt,{"reference_type":"OA Approval Request","reference_name":["in",payments]})
    else:frappe.db.delete(dt,{"document_type":"OA Approval Request","document_name":["in",payments]})
  erase("OA Approval Request",payments)
  erase("OA PO Fulfillment Record",frappe.get_all("OA PO Fulfillment Record",filters={"purchase_order":name},pluck="name"))
  erase("OA Purchase Order",[name])
 if source:erase("OA Approval Request",[source.name])
 for fid in files:
  if frappe.db.exists("File",fid):frappe.delete_doc("File",fid,ignore_permissions=True,force=True)
 frappe.db.commit();frappe.destroy()
