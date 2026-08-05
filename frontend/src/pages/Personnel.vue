<script setup>
import { ref, reactive, computed, watch } from "vue";
import { Card, Button, Badge, createResource } from "frappe-ui";
import { displayCompany, displayDepartment } from "../lib/displayBrand.js";
import { extractFrappeError } from "../lib/frappeError.js";

const RD_TYPES=["全时研发","非全时研发","研发辅助","非研发"];
const ARCH=["待完善","待确认","已归档"];
const GENDERS=[{v:"Male",l:"男"},{v:"Female",l:"女"}];
const EXPENSE_ACCOUNT_CATEGORIES=["","研发费用","管理费用","销售费用","生产成本"];
const api="rayher_hr_payroll.api.personnel_entry.";
const rows=createResource({url:api+"list_employees",method:"GET",auto:true});
const saver=createResource({url:api+"save_employee"});
const remover=createResource({url:api+"delete_employee"});
const companies=createResource({url:api+"get_company_options",method:"GET",auto:true});
const depts=createResource({url:api+"get_dept_options",method:"GET",auto:true});
const designations=createResource({url:api+"get_designation_options",method:"GET",auto:true});
const employmentTypes=createResource({url:api+"get_employment_type_options",method:"GET",auto:true});
const householdOptions=createResource({url:api+"get_household_options",method:"GET",auto:true});

const blank=()=>({
  name:"",company:"",employee_number:"",employee_name:"",english_name:"",date_of_birth:"",
  id_type_cn:"身份证",id_card_number_cn:"",gender:"Male",date_of_joining:"",relieving_date:"",
  department:"",designation:"",reports_to:"",employment_type:"",
  labour_contract_start_date:"",probation_months:"",probation_end_date:"",
  first_contract_period_years:"",first_contract_end_date:"",contract_renewal_status:"",
  second_contract_period_years:"",second_contract_end_date:"",
  default_monthly_salary:"",salary_months:"",
  first_education_level:"",first_education_school:"",first_education_major:"",
  education_level_cn:"",degree_cn:"",education_completion_type:"",
  graduation_school:"",major_cn:"",cell_number:"",household_registration:"",
  bank_name:"",bank_ac_no:"",social_insurance_number:"",housing_fund_number:"",
  default_social_insurance_base:"",default_housing_fund_base:"",
  rd_personnel_type:"",expense_account_category:"",archive_status:"待完善"
});
const form=reactive(blank());
const editing=ref(false);
const saving=ref(false);
const errMsg=ref("");
const companyFilter=ref("");
const departmentFilter=ref("");
const keyword=ref("");
const currentPage=ref(1);
const PAGE_SIZE=20;
const DEPARTMENT_GROUP_ORDER=["客户运营","研发","运营","职能"];
const departmentGroups=computed(()=>{
  const aggregated=new Map();
  for(const department of depts.data||[]){
    if(companyFilter.value&&department.company!==companyFilter.value)continue;
    const name=displayDepartment(department.department_name||department.name);
    if(!name||!department.group_name)continue;
    const key=`${department.group_name}:${name}`;
    const current=aggregated.get(key)||{name,group_name:department.group_name,employee_count:0};
    current.employee_count+=Number(department.employee_count||0);
    aggregated.set(key,current);
  }
  return DEPARTMENT_GROUP_ORDER.map(groupName=>{
    const departments=[...aggregated.values()].filter(item=>item.group_name===groupName&&item.employee_count>0);
    return {name:groupName,departments,total:departments.reduce((sum,item)=>sum+item.employee_count,0)};
  }).filter(group=>group.departments.length);
});
const departmentOptions=computed(()=>departmentGroups.value.flatMap(group=>group.departments.map(item=>item.name)));
const formDepartmentOptions=computed(()=>(depts.data||[]).filter(x=>x.company===form.company));
const filteredRows=computed(()=>{
  const needle=keyword.value.trim().toLowerCase();
  return (rows.data||[]).filter(e=>{
    if(companyFilter.value&&e.company!==companyFilter.value)return false;
    if(departmentFilter.value&&displayDepartment(e.department)!==departmentFilter.value)return false;
    if(!needle)return true;
    return [e.employee_number,e.employee_name,e.english_name,displayDepartment(e.department),e.designation].some(value=>String(value||"").toLowerCase().includes(needle));
  });
});
const pageCount=computed(()=>Math.max(1,Math.ceil(filteredRows.value.length/PAGE_SIZE)));
const pagedRows=computed(()=>filteredRows.value.slice((currentPage.value-1)*PAGE_SIZE,currentPage.value*PAGE_SIZE));
watch([companyFilter, departmentFilter, keyword],()=>{currentPage.value=1});
watch(companyFilter,()=>{
  if(departmentFilter.value&&!departmentOptions.value.includes(departmentFilter.value))departmentFilter.value="";
});
watch(()=>form.company,()=>{
  if(form.department&&!formDepartmentOptions.value.some(x=>x.name===form.department))form.department="";
});
watch(pageCount,count=>{if(currentPage.value>count)currentPage.value=count});
const canDelete=typeof window!=="undefined"&&Array.isArray(window.roles)&&window.roles.some(r=>["System Manager","HR Manager"].includes(r));
const archTheme=s=>s==="已归档"?"green":s==="待确认"?"orange":"gray";
const genderLabel=v=>v==="Female"?"女":v==="Male"?"男":v||"-";
const money=v=>Number(v||0).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2});
const supervisorName=id=>(rows.data||[]).find(x=>x.name===id)?.employee_name||id||"-";
function newEmp(){Object.assign(form,blank());editing.value=true;errMsg.value=""}
function edit(row){Object.assign(form,blank(),row);editing.value=true;errMsg.value=""}
function cancel(){editing.value=false}
async function save(){
  errMsg.value="";
  if(!form.employee_name||!form.company){errMsg.value="请填写姓名并选择所属单位";return}
  saving.value=true;
  try{await saver.submit({...form});editing.value=false;rows.reload()}
  catch(e){errMsg.value=extractFrappeError(e,"保存失败")}
  finally{saving.value=false}
}
async function del(name){try{await remover.submit({name});await rows.reload();if(currentPage.value>pageCount.value)currentPage.value=pageCount.value}catch(e){errMsg.value=extractFrappeError(e,"删除失败")}}
</script>

<template>
<div class="space-y-4">
<Card title="员工信息管理" subtitle="维护员工基本资料、劳动合同、教育、银行及社保公积金信息">
<template #actions><Button variant="solid" @click="newEmp">+ 新增员工</Button></template>
<div v-if="editing" class="mb-4 space-y-5 rounded-lg bg-gray-50 p-4">
<section><h3 class="section-title">基本信息</h3><div class="form-grid">
<label class="label">所属单位 *<select v-model="form.company" class="field"><option value="">请选择</option><option v-for="x in companies.data||[]" :key="x.name" :value="x.name">{{x.display_name||displayCompany(x.company_name||x.name)}}</option></select></label>
<label class="label">员工号<input v-model="form.employee_number" class="field"/></label>
<label class="label">姓名 *<input v-model="form.employee_name" class="field"/></label>
<label class="label">英文名<input v-model="form.english_name" class="field"/></label>
<label class="label">出生日期<input v-model="form.date_of_birth" type="date" class="field"/></label>
<label class="label">性别<select v-model="form.gender" class="field"><option v-for="g in GENDERS" :key="g.v" :value="g.v">{{g.l}}</option></select></label>
<label class="label">证件类型<input v-model="form.id_type_cn" class="field"/></label>
<label class="label">身份证号<input v-model="form.id_card_number_cn" class="field"/></label>
</div></section>

<section><h3 class="section-title">任职与薪资</h3><div class="form-grid">
<label class="label">入职时间<input v-model="form.date_of_joining" type="date" class="field"/></label>
<label class="label">离职时间<input v-model="form.relieving_date" type="date" class="field"/></label>
<label class="label">部门<select v-model="form.department" class="field"><option value="">{{form.company?'未设置':'请先选择所属单位'}}</option><option v-for="x in formDepartmentOptions" :key="x.name" :value="x.name">{{displayDepartment(x.department_name||x.name)}}</option></select></label>
<label class="label">职位<select v-model="form.designation" class="field"><option value="">未设置</option><option v-for="x in designations.data||[]" :key="x" :value="x">{{x}}</option></select></label>
<label class="label">汇报对象<select v-model="form.reports_to" class="field"><option value="">未设置</option><option v-for="x in (rows.data||[]).filter(x=>x.name!==form.name)" :key="x.name" :value="x.name">{{x.employee_name}}</option></select></label>
<label class="label">合同类型<select v-model="form.employment_type" class="field"><option value="">未设置</option><option v-for="x in employmentTypes.data||[]" :key="x" :value="x">{{x}}</option></select></label>
<label class="label">工资<input v-model="form.default_monthly_salary" type="number" min="0" step="0.01" class="field text-right"/></label>
<label class="label">薪资月数<input v-model="form.salary_months" type="number" min="0" step="1" class="field text-right"/></label>
</div></section>

<section><h3 class="section-title">劳动合同</h3><div class="form-grid">
<label class="label">劳动合同开始日期<input v-model="form.labour_contract_start_date" type="date" class="field"/></label>
<label class="label">试用期（月）<input v-model="form.probation_months" type="number" min="0" step="1" class="field"/></label>
<label class="label">试用期到期日<input v-model="form.probation_end_date" type="date" class="field"/></label>
<label class="label">第一次合同期限（年）<input v-model="form.first_contract_period_years" type="number" min="0" step="0.5" class="field"/></label>
<label class="label">第一次劳动合同到期日<input v-model="form.first_contract_end_date" type="date" class="field"/></label>
<label class="label">劳动合同续签情况<input v-model="form.contract_renewal_status" class="field"/></label>
<label class="label">第二次合同期限（年）<input v-model="form.second_contract_period_years" type="number" min="0" step="0.5" class="field"/></label>
<label class="label">第二次劳动合同到期日<input v-model="form.second_contract_end_date" type="date" class="field"/></label>
</div></section>

<section><h3 class="section-title">教育经历</h3><div class="form-grid">
<label class="label">第一学历<input v-model="form.first_education_level" class="field"/></label>
<label class="label">第一学历学校<input v-model="form.first_education_school" class="field"/></label>
<label class="label">第一学历专业<input v-model="form.first_education_major" class="field"/></label>
<label class="label">最高学历<input v-model="form.education_level_cn" class="field"/></label>
<label class="label">学位<input v-model="form.degree_cn" class="field"/></label>
<label class="label">学历完成形式<input v-model="form.education_completion_type" class="field"/></label>
<label class="label">最高学历学校<input v-model="form.graduation_school" class="field"/></label>
<label class="label">最高学历专业<input v-model="form.major_cn" class="field"/></label>
</div></section>

<section><h3 class="section-title">联系与银行</h3><div class="form-grid">
<label class="label">联系电话<input v-model="form.cell_number" class="field"/></label>
<label class="label">户口信息<select v-model="form.household_registration" class="field"><option value="">未维护</option><option v-for="x in householdOptions.data||[]" :key="x" :value="x">{{x}}</option></select></label>
<label class="label">工资卡银行开户行及支行<input v-model="form.bank_name" class="field"/></label>
<label class="label">工资卡银行账号<input v-model="form.bank_ac_no" class="field"/></label>
</div></section>

<section><h3 class="section-title">社保公积金</h3><div class="form-grid">
<label class="label">社保电脑号<input v-model="form.social_insurance_number" class="field"/></label>
<label class="label">公积金账号<input v-model="form.housing_fund_number" class="field"/></label>
<label class="label">社保基数<input v-model="form.default_social_insurance_base" type="number" min="0" step="0.01" class="field text-right"/></label>
<label class="label">公积金基数<input v-model="form.default_housing_fund_base" type="number" min="0" step="0.01" class="field text-right"/></label>
</div></section>

<section><h3 class="section-title">扩展信息</h3><div class="grid gap-3 md:grid-cols-3">
<label class="label">研发人员类型<select v-model="form.rd_personnel_type" class="field"><option value="">未设置</option><option v-for="x in RD_TYPES" :key="x" :value="x">{{x}}</option></select></label>
<label class="label">费用科目<select v-model="form.expense_account_category" class="field"><option v-for="x in EXPENSE_ACCOUNT_CATEGORIES" :key="x" :value="x">{{x||'未设置'}}</option></select></label>
<label class="label">归档状态<select v-model="form.archive_status" class="field"><option v-for="x in ARCH" :key="x" :value="x">{{x}}</option></select></label>
</div></section>
<p v-if="errMsg" class="text-xs text-red-600">{{errMsg}}</p>
<div class="flex gap-2"><Button variant="solid" :loading="saving" @click="save">保存</Button><Button variant="subtle" @click="cancel">取消</Button></div>
</div>

<section class="department-overview" aria-label="部门分类">
<div class="department-overview-head"><div><h3>部门分布</h3><p>按组织架构展示实际在职团队，点击部门可筛选员工</p></div><button v-if="departmentFilter" class="clear-department" type="button" @click="departmentFilter=''">查看全部</button></div>
<div class="department-board">
<article v-for="group in departmentGroups" :key="group.name" class="department-group">
<div class="department-group-title"><span>{{group.name}}</span><strong>{{group.total}} 人</strong></div>
<div class="department-list"><button v-for="department in group.departments" :key="department.name" type="button" class="department-card" :class="{'department-card-active':departmentFilter===department.name}" @click="departmentFilter=department.name"><span>{{department.name}}</span><b>{{department.employee_count}}</b></button></div>
</article>
</div>
</section>

<div class="mb-3 grid gap-3 md:grid-cols-3">
<label class="label">所属公司<select v-model="companyFilter" class="field"><option value="">全部公司</option><option v-for="x in companies.data||[]" :key="x.name" :value="x.name">{{x.display_name||displayCompany(x.name)}}</option></select></label>
<label class="label">部门筛选<select v-model="departmentFilter" class="field"><option value="">全部部门</option><option v-for="name in departmentOptions" :key="name" :value="name">{{name}}</option></select></label>
<label class="label">搜索员工<input v-model="keyword" class="field" placeholder="姓名、员工号、职位"/></label>
</div>
<div v-if="rows.loading" class="py-4 text-sm text-gray-500">加载中...</div>
<div v-else class="table-scroll"><table class="employee-table w-full min-w-[3400px] text-sm">
<thead><tr>
<th class="cell">序号</th><th class="cell">员工号</th><th class="cell">所属单位</th><th class="cell">姓名</th><th class="cell">部门</th><th class="cell">职位</th><th class="cell">户口信息</th><th class="cell">系统判断</th><th class="cell text-right">社保基数</th><th class="cell text-right">公积金基数</th><th class="cell">英文名</th><th class="cell">出生日期</th><th class="cell">性别</th><th class="cell">入职时间</th><th class="cell">离职时间</th><th class="cell">汇报对象</th><th class="cell">合同类型</th><th class="cell text-right">工资</th><th class="cell">薪资月数</th><th class="cell">最高学历</th><th class="cell">学位</th><th class="cell">毕业学校</th><th class="cell">联系电话</th><th class="cell">开户行及支行</th><th class="cell">银行卡号</th><th class="cell">社保电脑号</th><th class="cell">公积金账号</th><th class="cell">费用科目</th><th class="cell">归档</th><th class="cell text-right">操作</th>
</tr></thead>
<tbody><tr v-for="(e,index) in pagedRows" :key="e.name" class="border-b hover:bg-gray-50">
<td class="cell">{{(currentPage-1)*PAGE_SIZE+index+1}}</td><td class="cell">{{e.employee_number||'-'}}</td><td class="cell">{{displayCompany(e.company)}}</td><td class="cell font-medium">{{e.employee_name}}</td><td class="cell">{{displayDepartment(e.department)||'-'}}</td><td class="cell">{{e.designation||'-'}}</td>
<td class="cell"><Badge :theme="e.household_registration?'gray':'orange'">{{e.household_registration||'未维护'}}</Badge></td><td class="cell"><Badge :theme="e.household_classification==='待完善'?'orange':'green'">{{e.household_classification||'待完善'}}</Badge></td>
<td class="cell text-right"><span v-if="Number(e.default_social_insurance_base||0)>0">{{money(e.default_social_insurance_base)}}</span><Badge v-else theme="orange">未维护</Badge></td><td class="cell text-right"><span v-if="Number(e.default_housing_fund_base||0)>0">{{money(e.default_housing_fund_base)}}</span><Badge v-else theme="orange">未维护</Badge></td>
<td class="cell">{{e.english_name||'-'}}</td><td class="cell">{{e.date_of_birth||'-'}}</td><td class="cell">{{genderLabel(e.gender)}}</td><td class="cell">{{e.date_of_joining||'-'}}</td><td class="cell">{{e.relieving_date||'-'}}</td><td class="cell">{{supervisorName(e.reports_to)}}</td><td class="cell">{{e.employment_type||'-'}}</td><td class="cell text-right">{{money(e.default_monthly_salary)}}</td><td class="cell">{{e.salary_months?e.salary_months+'薪':'-'}}</td><td class="cell">{{e.education_level_cn||'-'}}</td><td class="cell">{{e.degree_cn||'-'}}</td><td class="cell">{{e.graduation_school||'-'}}</td><td class="cell">{{e.cell_number||'-'}}</td><td class="cell">{{e.bank_name||'-'}}</td><td class="cell">{{e.bank_ac_no||'-'}}</td><td class="cell">{{e.social_insurance_number||'-'}}</td><td class="cell">{{e.housing_fund_number||'-'}}</td><td class="cell">{{e.expense_account_category||'-'}}</td><td class="cell"><Badge :theme="archTheme(e.archive_status)">{{e.archive_status||'-'}}</Badge></td><td class="cell text-right"><button class="mr-2 text-xs text-blue-600" @click="edit(e)">编辑</button><button v-if="canDelete" class="text-xs text-red-600" @click="del(e.name)">删除</button></td>
</tr><tr v-if="!pagedRows.length"><td colspan="30" class="py-10 text-center text-gray-400">没有符合条件的员工</td></tr></tbody></table></div>
<div class="mt-3 flex items-center justify-between text-sm text-gray-500"><span>共 {{filteredRows.length}} 人，第 {{currentPage}} / {{pageCount}} 页</span><div class="flex gap-2"><Button size="sm" :disabled="currentPage<=1" @click="currentPage--">上一页</Button><Button size="sm" :disabled="currentPage>=pageCount" @click="currentPage++">下一页</Button></div></div>

</Card></div>
</template>

<style scoped>
.section-title{margin-bottom:.5rem;font-size:.875rem;font-weight:600}.department-overview{margin-bottom:1rem;border:1px solid #e5e7eb;border-radius:.65rem;background:#fafafa;padding:.9rem}.department-overview-head{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;margin-bottom:.75rem}.department-overview-head h3{font-size:.875rem;font-weight:650;color:#111827}.department-overview-head p{margin-top:.15rem;font-size:.75rem;color:#6b7280}.clear-department{border:0;background:transparent;padding:.2rem .35rem;font-size:.75rem;color:#2563eb}.department-board{display:grid;gap:.65rem}@media(min-width:1024px){.department-board{grid-template-columns:repeat(2,minmax(0,1fr))}}.department-group{min-width:0;border-left:3px solid #d1d5db;padding:.15rem 0 .15rem .7rem}.department-group-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:.45rem;font-size:.75rem;color:#4b5563}.department-group-title strong{font-weight:600;color:#111827}.department-list{display:flex;flex-wrap:wrap;gap:.4rem}.department-card{display:inline-flex;align-items:center;gap:.45rem;border:1px solid #d1d5db;border-radius:.45rem;background:white;padding:.35rem .55rem;font-size:.75rem;color:#374151;transition:border-color .15s,background .15s,color .15s}.department-card:hover{border-color:#9ca3af}.department-card b{min-width:1.35rem;border-radius:.35rem;background:#f3f4f6;padding:.05rem .3rem;text-align:center;font-weight:650;color:#111827}.department-card-active{border-color:#111827;background:#111827;color:white}.department-card-active b{background:#374151;color:white}.form-grid{display:grid;gap:.75rem}@media(min-width:768px){.form-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(min-width:1280px){.form-grid{grid-template-columns:repeat(6,minmax(0,1fr))}}.label{font-size:.75rem;color:rgb(107 114 128)}.field{margin-top:.25rem;display:block;width:100%;border-radius:.375rem;border:1px solid rgb(209 213 219);padding:.5rem .75rem;font-size:.875rem;color:rgb(17 24 39);background:white}.cell{padding:.55rem .75rem;text-align:left;white-space:nowrap}.table-scroll{max-height:68vh;overflow:auto;border:1px solid #e5e7eb;border-radius:.5rem}.employee-table thead th{position:sticky;top:0;z-index:20;background:#f8fafc;border-bottom:1px solid #d1d5db}.employee-table th:first-child{position:sticky;left:0;z-index:30;background:#f8fafc}.employee-table td:first-child{position:sticky;left:0;z-index:10;background:white;border-right:1px solid #e5e7eb}.employee-table tr:hover td:first-child{background:#f9fafb}
</style>
