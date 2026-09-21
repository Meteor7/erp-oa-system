import sys,json,multiprocessing
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_transaction_locks import connect
import frappe

def worker(kind,args,user,barrier,queue):
    connect();frappe.set_user(user)
    from rayher_hr_payroll.api import procurement_chain as api
    guard_name="_require_pmc" if kind=="pr" else "_require_purchase"
    original=getattr(api,guard_name)
    def wait_guard():original();barrier.wait(timeout=20)
    setattr(api,guard_name,wait_guard)
    try:
        result=(api.create_pr if kind=="pr" else api.create_price_approval)(args)
        queue.put({"ok":True,"name":result.get("name")})
    except Exception as e:
        frappe.db.rollback();queue.put({"ok":False,"error":type(e).__name__,"detail":str(e)})
    finally:frappe.destroy()

def race(kind,args,user):
    ctx=multiprocessing.get_context("spawn");barrier=ctx.Barrier(2);queue=ctx.Queue()
    ps=[ctx.Process(target=worker,args=(kind,args,user,barrier,queue)) for _ in range(2)]
    for p in ps:p.start()
    for p in ps:p.join(timeout=35)
    for p in ps:
        if p.is_alive():p.kill();p.join()
    results=[]
    while not queue.empty():results.append(queue.get())
    return results

def erase(doctype,names):
    if not names:return
    for field in frappe.get_meta(doctype).get_table_fields():
        frappe.db.delete(field.options,{"parent":["in",names],"parenttype":doctype})
    frappe.db.delete("Notification Log",{"document_type":doctype,"document_name":["in",names]})
    frappe.db.delete(doctype,{"name":["in",names]})

def main():
    connect();frappe.set_user("Administrator")
    from rayher_hr_payroll.api import oa_entry as oa
    from rayher_hr_payroll.position_access import position_user
    pmc,purchaser=position_user("pmc"),position_user("procurement_manager")
    source=frappe.get_doc(dict(doctype="OA Approval Request",request_type=oa.REQUEST_PROCUREMENT,subject="REVIEW quantity race",workflow_status="已完成",business_lines=[dict(item_name="REVIEW-RACE",quantity=10,unit="件",material_serial="REVIEW-RACE")]))
    oa._insert_document(source);frappe.db.commit()
    source_name,line_name=source.name,source.business_lines[0].name
    frappe.destroy()
    try:
        pr_results=race("pr",[dict(source_request=source_name,source_line=line_name,quantity=8)],pmc)
        connect();frappe.set_user("Administrator")
        prs=frappe.get_all("OA Procurement Request Line",filters={"source_request":source_name},fields=["name","parent","quantity","remaining_quantity"])
        print(json.dumps({"pr_race":pr_results,"total_pr_quantity":sum(r.quantity for r in prs)},ensure_ascii=False))
        assert len(prs)==1 and sum(r.quantity for r in prs)==8
        pr=prs[0];frappe.destroy()
        price_results=race("price",[dict(source_pr=pr.parent,source_pr_line=pr.name,quantity=6)],purchaser)
        connect();frappe.set_user("Administrator")
        prices=frappe.get_all("OA Price Approval Line",filters={"source_request":source_name},fields=["name","quantity"])
        remaining=frappe.db.get_value("OA Procurement Request Line",pr.name,"remaining_quantity")
        print(json.dumps({"price_race":price_results,"total_price_quantity":sum(r.quantity for r in prices),"pr_remaining":remaining},ensure_ascii=False))
        assert len(prices)==1 and sum(r.quantity for r in prices)==6 and remaining==2
        frappe.destroy()
    finally:
        connect();frappe.set_user("Administrator")
        for child,parent in [("OA Price Approval Line","OA Price Approval"),("OA Procurement Request Line","OA Procurement Request")]:
            parents=frappe.get_all(child,filters={"source_request":source_name},pluck="parent")
            erase(parent,parents)
        boards=frappe.get_all("OA Material Progress",filters={"source_request":source_name},pluck="name")
        erase("OA Material Progress",boards);erase("OA Approval Request",[source_name]);frappe.db.commit();frappe.destroy()

if __name__=="__main__":main()
