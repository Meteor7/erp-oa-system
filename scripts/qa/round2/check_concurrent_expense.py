import sys, json, multiprocessing
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_transaction_locks import connect

def worker(barrier, queue, user, period):
    import frappe
    connect()
    frappe.set_user(user)
    from rayher_hr_payroll.api import expense_entry as api
    original = api._active_import_name
    calls = 0
    def synchronized(year, month):
        nonlocal calls
        result = original(year, month)
        calls += 1
        if calls == 1:
            barrier.wait(timeout=30)
        return result
    api._active_import_name = synchronized
    try:
        from rayher_hr_payroll.rd_expense_accounts import catalog_paths, path_dict
        row = path_dict(catalog_paths()[0])
        row.update(amount=12, voucher_no="REVIEW-CONCURRENT", allocation_type="common")
        result = api.save_expense(period, [row])
        queue.put(dict(ok=True, name=result["name"]))
    except Exception as e:
        frappe.db.rollback()
        queue.put(dict(ok=False, error=type(e).__name__, detail=str(e)))
    finally:
        frappe.destroy()

def main():
    import frappe
    connect()
    from test_oa_security import ordinary_user
    from frappe.client import set_value
    from rayher_hr_payroll.patches.v1_0.migrate_active_oa_approvers import _resolve_user
    attacker = ordinary_user()
    frappe.set_user(attacker)
    alias = "REVIEW Unique Legacy Approver"
    set_value("User", attacker, {"first_name": alias, "last_name": ""})
    print(json.dumps({"migration_self_edit_resolves_attacker": _resolve_user(alias) == attacker}))
    frappe.db.rollback()
    frappe.set_user("Administrator")
    user = next(r.parent for r in frappe.get_all("Has Role", filters={"role":"Accounts User", "parenttype":"User"}, fields=["parent"]) if r.parent != "Administrator" and frappe.db.get_value("User", r.parent, "enabled"))
    period = "2098-11"
    assert not frappe.db.exists("RD Expense Import", {"year":2098,"month":11})
    print(json.dumps({"isolation":frappe.db.sql("select @@tx_isolation")[0][0]}))
    frappe.destroy()
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    procs = [ctx.Process(target=worker, args=(barrier, queue, user, period)) for _ in range(2)]
    for p in procs: p.start()
    for p in procs: p.join(timeout=55)
    for p in procs:
        if p.is_alive(): p.kill(); p.join()
    results=[]
    while not queue.empty(): results.append(queue.get())
    connect()
    frappe.set_user("Administrator")
    names=frappe.get_all("RD Expense Import", filters={"year":2098,"month":11}, pluck="name")
    print(json.dumps({"concurrent_results":results,"active_count":len(names),"persisted_names":names}, ensure_ascii=False))
    assert len(names)==1 and sum(bool(r.get("ok")) for r in results)==1
    for name in names: frappe.delete_doc("RD Expense Import",name,ignore_permissions=True,force=True)
    frappe.db.commit()
    frappe.destroy()

if __name__ == "__main__": main()
