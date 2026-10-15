"""Fictional, append-only data for the local Docker demo; never reset passwords."""
import json
from datetime import date, timedelta
import frappe
from rayher_hr_payroll import oa_role_resolver
from rayher_hr_payroll.api import oa_entry as oa
from rayher_hr_payroll.approval_center import save_draft

COMPANY = "[演示]示例企业021有限公司"
PREFIX = "[演示]"
PEOPLE = [
    ("manager", "演示员工14", "管理部", ["HR Manager", "Projects Manager", "Rayher Business Executive"]),
    ("hr", "许晴", "人事行政部", ["HR Manager"]),
    ("finance", "顾安", "财务部", ["Accounts User", "Accounts Manager"]),
    ("pmc", "林序", "供应链部", ["Purchase User"]),
    ("buyer", "江禾", "供应链部", ["Purchase Manager"]),
    ("production", "陆川", "供应链部", ["Purchase User"]),
    ("front", "白露", "人事行政部", []),
    ("it", "程墨", "人事行政部", []),
    ("engineer1", "苏辰", "研发部", ["Projects User"]),
    ("engineer2", "唐禾", "研发部", ["Projects User"]),
    ("engineer3", "沈星", "研发部", ["Projects User"]),
    ("sales1", "林悦", "销售部", []),
    ("sales2", "陈舟", "销售部", []),
]
PEOPLE = [row for row in PEOPLE if row[0] in {"manager", "hr", "finance", "pmc", "buyer", "engineer1", "sales1"}]

def user(key):
    return "demo." + key + "@example.com"

def guard(confirm):
    if frappe.local.site != "logistics.localhost" or confirm != frappe.local.site:
        raise RuntimeError("Only the explicitly confirmed local Docker site is allowed.")
    frappe.set_user("Administrator")
    frappe.flags.mute_emails = True

def ensure(dt, filters, values):
    name = frappe.db.exists(dt, filters)
    return frappe.get_doc(dt, name) if name else frappe.get_doc({"doctype": dt, **values}).insert(ignore_permissions=True)

def seed_masters(confirm="", password=None):
    guard(confirm)
    if not password or len(password) < 20:
        raise ValueError("Provide a long random password for new demo accounts.")
    from frappe.utils.password import update_password
    today = date.today()
    frappe.db.set_single_value("System Settings", "time_zone", "Asia/Shanghai")
    if not frappe.db.exists("Warehouse Type", "Transit"):
        from erpnext.setup.setup_wizard.operations.install_fixtures import install
        install(country="China")
    company = ensure("Company", COMPANY, {"company_name": COMPANY, "abbr": "DEMO", "default_currency": "CNY", "country": "China"})
    if not frappe.defaults.get_global_default("company"):
        frappe.defaults.set_global_default("company", company.name)
    calendar = f"DEMO-{today.year}-双休演示日历"
    days = []
    cursor = date(today.year, 1, 1)
    while cursor.year == today.year:
        if cursor.weekday() >= 5:
            days.append({"holiday_date": str(cursor), "description": "演示周末", "weekly_off": 1})
        cursor += timedelta(days=1)
    holiday = ensure("Holiday List", calendar, {"holiday_list_name": calendar, "from_date": f"{today.year}-01-01", "to_date": f"{today.year}-12-31", "holidays": days})
    if not company.default_holiday_list:
        company.default_holiday_list = holiday.name
        company.save(ignore_permissions=True)
    depts = {}
    for label in sorted({row[2] for row in PEOPLE}):
        depts[label] = ensure("Department", {"department_name": PREFIX+label, "company": COMPANY}, {"department_name": PREFIX+label, "company": COMPANY}).name
    ensure("Gender", "Male", {"gender": "Male"})
    staff = {}
    for key, name, department, roles in PEOPLE:
        email = user(key)
        if not frappe.db.exists("User", email):
            allowed = [role for role in ["Employee", *roles] if frappe.db.exists("Role", role)]
            frappe.get_doc({"doctype": "User", "email": email, "first_name": PREFIX+name, "enabled": 1, "send_welcome_email": 0, "roles": [{"role": r} for r in allowed]}).insert(ignore_permissions=True)
            update_password(email, password, logout_all_sessions=False)
        values = {"first_name": PREFIX+name, "gender": "Male", "date_of_birth": "1994-06-15", "date_of_joining": f"{today.year-2}-01-08", "company": COMPANY, "department": depts[department], "status": "Active", "user_id": email, "holiday_list": holiday.name, "create_user_permission": 0, "rd_personnel_type": "全时研发" if department == "研发部" else "非研发"}
        if key != "manager":
            values["reports_to"] = staff["manager"]
        staff[key] = ensure("Employee", {"user_id": email}, values).name
    if not frappe.db.exists("Employee", {"user_id": "Administrator"}):
        frappe.get_doc({"doctype": "Employee", "first_name": "[演示]系统负责人", "gender": "Male", "date_of_birth": "1990-01-01", "date_of_joining": f"{today.year-2}-01-08", "company": COMPANY, "department": depts["管理部"], "status": "Active", "user_id": "Administrator", "reports_to": staff["manager"], "holiday_list": holiday.name, "create_user_permission": 0}).insert(ignore_permissions=True)
    mapping = {"general_manager":"manager", "vice_manager":"manager", "hr_manager":"hr", "finance_auditor":"finance", "finance_accountant":"finance", "finance_manager":"finance", "pmc":"pmc", "procurement_manager":"buyer", "production_asset_owner":"pmc", "it_asset_owner":"hr", "front_desk":"hr"}
    for key, person in mapping.items():
        ensure("OA Approval Role Assignment", {"role_key": key}, {"role_key": key, "role_label": oa_role_resolver.ROLE_SPECS[key]["label"], "employee": staff[person], "user": user(person), "enabled": 1})
    for i, title in enumerate(["晶圆缺陷检测平台", "先进封装光学检测"], 1):
        ensure("Project", {"project_name": PREFIX+title}, {"project_name": PREFIX+title, "company": COMPANY, "status": "Open", "expected_start_date": f"{today.year}-01-01", "expected_end_date": f"{today.year}-12-31", "project_owner": user("manager"), "allow_rd_timesheet": 1, "rd_project_code": "DEMO"+str(i), "rd_project_key": "DEMO"+str(i)+" | "+title})
    ensure("Activity Type", "Demo Development", {"activity_type": "Demo Development"})
    ensure("OA Procurement Category", "DEMO-ELC", {"category_code":"DEMO-ELC", "category_name":"[演示]电子与光学组件", "full_path":"[演示]电子与光学组件", "level":1, "allow_request":1, "is_active":1, "source":"本地演示"})
    for i, name in enumerate(["工业相机", "远心镜头", "光源控制器"], 1):
        code = "DEMO-MAT-"+str(i)
        ensure("OA Procurement Material", code, {"material_code":code, "category_code":"DEMO-ELC", "category_path":"[演示]电子与光学组件", "material_name":PREFIX+name, "specification":"演示标准型", "product_desc":"虚构演示物料", "brand":"DEMO", "material_attr":"外购", "unit":"个", "is_active":1, "source":"本地演示"})
    for label in ["星河精密组件", "云帆光电器件"]:
        ensure("Supplier", {"supplier_name": PREFIX+label}, {"supplier_name":PREFIX+label, "supplier_type":"Company", "supplier_group":"All Supplier Groups", "country":"China"})
    frappe.db.commit()
    return {"employees": len(staff)+1, "departments":len(depts), "projects":2, "materials":3, "suppliers":2}

def advance(name, max_steps=30):
    for _ in range(max_steps):
        doc = frappe.get_doc("OA Approval Request", name)
        if doc.workflow_status in {"已完成", "已付款", "已驳回"}:
            return
        step = oa._current_step(doc)
        if not step:
            return
        approved = set(json.loads(step.approved_by or "[]"))
        for actor in json.loads(step.approvers or "[]"):
            if actor not in approved:
                frappe.set_user(actor)
                oa.action_request(name, "approve", "[演示]资料齐全，同意申请", expected_step_key=step.step_key)
    return

def seed_activity(confirm=""):
    guard(confirm)
    today = date.today()
    month = today.replace(day=1)
    working = [month + timedelta(days=i) for i in range((today-month).days) if (month+timedelta(days=i)).weekday()<5]
    staff = {key:frappe.db.get_value("Employee", {"user_id":user(key)}, "name") for key,*_ in PEOPLE}
    projects = frappe.get_all("Project", filters={"project_name":["like", PREFIX+"%"]}, pluck="name", order_by="name")
    for key in staff:
        for day in working[-2:]:
            ensure("Attendance", {"employee":staff[key], "attendance_date":str(day)}, {"employee":staff[key], "attendance_date":str(day), "status":"Present", "company":COMPANY}).submit() if not frappe.db.exists("Attendance", {"employee":staff[key], "attendance_date":str(day)}) else None
    for n, key in enumerate(["engineer1"]):
        for day in working[-2:]:
            if frappe.db.exists("Timesheet", {"employee":staff[key], "start_date":str(day)}):
                continue
            doc = frappe.get_doc({"doctype":"Timesheet", "employee":staff[key], "company":COMPANY, "time_logs":[{"activity_type":"Demo Development", "from_time":str(day)+" 09:00:00", "to_time":str(day)+" 12:00:00", "hours":3, "project":projects[n%len(projects)]}, {"activity_type":"Demo Development", "from_time":str(day)+" 13:00:00", "to_time":str(day)+" 18:00:00", "hours":5, "project":projects[(n+1)%len(projects)]}]}).insert(ignore_permissions=True)
            doc.submit()
    frappe.db.commit()
    scenarios = [("engineer1","加班申请",-4,4,True,""), ("engineer1","请假申请",1,8,False,"年假"), ("sales1","请假申请",5,3,True,"事假")]
    for index,(key,kind,offset,hours,complete,leave) in enumerate(scenarios,1):
        subject = f"{PREFIX}考勤场景{index:02d}·{kind}"
        if frappe.db.exists("OA Approval Request", {"subject":subject}):
            continue
        day = today+timedelta(days=offset)
        if kind != "加班申请":
            while day.weekday()>=5: day+=timedelta(days=1)
        frappe.set_user(user(key))
        result = oa.create_request(kind, subject=subject, from_date=str(day), to_date=str(day), attendance_days=json.dumps([{"work_date":str(day),"hours":hours}]), leave_type=leave or None, reason="仅用于本地功能演示的虚构申请", submit=1)
        if complete: advance(result["name"])
        frappe.db.commit()
    for i in range(2):
        subject = f"{PREFIX}办公采购{i+1:02d}·样品整理用品"
        if frappe.db.exists("OA Approval Request", {"subject":subject}): continue
        frappe.set_user(user("engineer1" if i%2 else "sales1"))
        doc = save_draft("购买申请", {"subject":subject, "reason":"演示购买审批与费用归属", "asset_nature":"非固定资产", "purchase_method":"其他购买", "expected_delivery_date":str(today+timedelta(days=7)), "business_lines":[{"item_name":"[演示]防静电收纳盒", "quantity":5+i, "unit":"个", "unit_price":85, "specification":"标准型", "remarks":"虚构演示"}]})
        if i != 0: oa.submit_request(doc.name)
        if i == 1: advance(doc.name)
        frappe.db.commit()
    frappe.set_user("Administrator")
    return {dt:frappe.db.count(dt) for dt in ["Attendance","Timesheet","OA Approval Request"]}

def seed_procurement(confirm=""):
    guard(confirm)
    from rayher_hr_payroll.maintenance import procurement_test_data as existing
    from rayher_hr_payroll.api import procurement_chain as chain
    old = {key:getattr(existing,key) for key in ["PREFIX","APPLICANT","PROJECTS","MATERIAL_CODES","SUPPLIERS","PRICE_APPROVER_USER","SEAL_USER"]}
    existing.PREFIX = "[演示]采购链·"
    existing.APPLICANT = frappe.db.get_value("Employee", {"user_id":user("engineer1")}, "name")
    existing.PROJECTS = tuple(frappe.get_all("Project", filters={"project_name":["like",PREFIX+"%"]},pluck="name",order_by="name")[:2])
    existing.MATERIAL_CODES = tuple("DEMO-MAT-"+str(i) for i in range(1,4))
    existing.SUPPLIERS = tuple(frappe.get_all("Supplier",filters={"supplier_name":["like",PREFIX+"%"]},pluck="name",order_by="name"))
    existing.PRICE_APPROVER_USER = user("manager")
    existing.SEAL_USER = user("buyer")
    results=[]
    try:
        for i,stage in [(0,"待需求审批"),(4,"已生成PO")]:
            marker=existing.PREFIX+stage
            if frappe.db.exists("OA Approval Request", {"subject":["like",marker+"%"]}): continue
            frappe.set_user(user("engineer1"))
            source = save_draft("采购申请", {"subject": marker, "reason":"[演示]研发设备组件采购", "urgency":"一般", "asset_nature":"非固定资产", "procurement_scope":"项目采购", "project":existing.PROJECTS[i%2], "expected_delivery_date":str(date.today()+timedelta(days=20)), "business_lines":existing._materials(i, count=2)})
            oa.submit_request(source.name)
            if i: advance(source.name)
            sources=[frappe.get_doc("OA Approval Request",source.name)]
            row={"stage":stage,"oa":sources[0].name}
            if i>=2:
                prs=existing._create_prs(sources); row["pr"]=prs[0]["name"]
            if i>=3:
                price=existing._create_price(prs); row["price"]=price["name"]
                frappe.set_user(user("buyer"))
                for j,supplier in enumerate(existing.SUPPLIERS):
                    prices=[{"price_line":line["name"],"unit_price":360+50*k+30*j,"delivery_date":str(date.today()+timedelta(days=14+j))} for k,line in enumerate(price["lines"])]
                    total=sum(p["unit_price"]*float(line["quantity"]) for p,line in zip(prices,price["lines"]))
                    plan=[{"installment_name":"验收后全额付款","payment_stage":"全额付款","percentage":100,"amount":total,"planned_date":str(date.today()+timedelta(days=30)),"trigger_condition":"全部到货并验收通过","invoice_requirement":"付款前提供"}]
                    chain.save_supplier_comparison(price["name"],supplier,json.dumps(prices),payment_method="验收合格后付款",currency="CNY",tax_rate=13,contract_entity=COMPANY,is_recommended=int(j==0),note="[演示]供应商比价",payment_plan=json.dumps(plan))
                chain.update_price_approval_summary(price["name"],"[演示]比较价格、交期与付款条件")
                price=chain.submit_price_approval(price["name"])
                if i==4:
                    row["po"]=existing._approve_price_to_po(price)
            frappe.db.commit(); results.append(row)
    except Exception:
        frappe.db.rollback(); raise
    finally:
        for key,value in old.items(): setattr(existing,key,value)
        frappe.set_user("Administrator")
    return results
