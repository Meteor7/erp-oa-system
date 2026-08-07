<script setup>
import { reactive, watch } from "vue";
import { Card, Button, createResource } from "frappe-ui";
import { displayCompany, displayDepartment } from "../lib/displayBrand.js";
import { period } from "../lib/period";
const api="rayher_hr_payroll.api.hr_payroll_entry.";
const rows=createResource({url:api+"get_payroll_rows",method:"GET",makeParams:()=>({period:period.value}),auto:true});
const saver=createResource({url:api+"save_payroll_draft"});
const adjuster=createResource({url:api+"apply_salary_adjustment"});
const saving=reactive({}); const applying=reactive({}); const messages=reactive({}); const errors=reactive({});
const n=v=>Number(v||0); const money=v=>n(v).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2});
const gender=v=>v==="Female"?"女":v==="Male"?"男":v||"-";
const adjusted=row=>n(row.base_salary)+n(row.salary_adjustment);
const prorated=row=>n(row.total_working_days)>0?adjusted(row)*n(row.payment_days)/n(row.total_working_days):0;
const payable=row=>prorated(row)+n(row.company_subsidy)+n(row.bonus)+n(row.other_adjustment);
const net=row=>payable(row)-n(row.social_insurance)-n(row.housing_fund)-n(row.income_tax)-n(row.accommodation)-n(row.advanced_paid);
const locked=row=>row.docstatus===1||Boolean(row.salary_slip&&!row.managed);
async function saveRow(row){
  saving[row.employee]=true; errors[row.employee]=""; messages[row.employee]="";
  try{
    await saver.submit({employee:row.employee,period:period.value,payment_days:n(row.payment_days),base_salary:n(row.base_salary),salary_adjustment:n(row.salary_adjustment),company_subsidy:n(row.company_subsidy),bonus:n(row.bonus),other_adjustment:n(row.other_adjustment),income_tax:n(row.income_tax),advanced_paid:n(row.advanced_paid)});
    messages[row.employee]="草稿已保存"; await rows.reload();
  }catch(e){errors[row.employee]=e?.message||"保存失败"}finally{saving[row.employee]=false}
}
async function applyAdjustment(row){
  applying[row.employee]=true; errors[row.employee]=""; messages[row.employee]="";
  try{await adjuster.submit({employee:row.employee,period:period.value,adjusted_base:adjusted(row)});messages[row.employee]="调薪已应用至后续月份";await rows.reload()}
  catch(e){errors[row.employee]=e?.message||"应用调薪失败"}finally{applying[row.employee]=false}
}
watch(period,()=>rows.reload());
</script>
<template>
<div class="space-y-4">
<Card title="薪酬计算" subtitle="按员工逐行维护本月薪酬，关联社保、公积金和宿舍代扣后生成真实草稿工资单">
  <div class="flex flex-wrap items-end gap-3"><label class="text-xs text-gray-500">期间<input v-model="period" type="month" class="mt-1 block rounded border border-gray-300 px-3 py-2 text-sm"/></label><span class="text-xs text-gray-400">没有社保或公积金月度记录的员工不能保存工资草稿</span></div>
</Card>
<Card :title="period+' 薪酬明细'">
<div v-if="rows.loading" class="py-8 text-center text-sm text-gray-500">正在加载薪酬明细...</div>
<div v-else class="overflow-x-auto"><table class="w-full min-w-[3600px] text-xs"><thead class="sticky top-0 border-b bg-white text-gray-500"><tr>
<th class="cell">序号</th><th class="cell">所属单位</th><th class="cell">身份证号</th><th class="cell">性别</th><th class="cell">费用科目</th><th class="cell">部门</th><th class="cell">职位</th><th class="cell">入职时间</th><th class="cell">离职时间</th><th class="cell">计薪天数</th><th class="cell">姓名</th><th class="cell">基本工资</th><th class="cell">调薪</th><th class="cell">基本工资调薪后</th><th class="cell">公司补贴</th><th class="cell">奖金</th><th class="cell">其他补/扣</th><th class="cell">应付工资</th><th class="cell">养老保险（个人）</th><th class="cell">医疗保险（个人）</th><th class="cell">失业保险（个人）</th><th class="cell">社保合计（个人）</th><th class="cell">公积金（个人）</th><th class="cell">个人所得税（代扣）</th><th class="cell">宿舍房租及水电费（代扣）</th><th class="cell">已发放</th><th class="cell">实发工资</th><th class="cell">开户银行</th><th class="cell">银行账号</th><th class="cell">手机号</th><th class="cell">状态与操作</th>
</tr></thead><tbody>
<tr v-for="(row,index) in rows.data||[]" :key="row.employee" class="border-b align-top hover:bg-gray-50">
<td class="cell">{{index+1}}</td><td class="cell">{{displayCompany(row.company)}}</td><td class="cell">{{row.id_card_number_cn||'-'}}</td><td class="cell">{{gender(row.gender)}}</td><td class="cell">{{row.expense_account_category||'-'}}</td><td class="cell">{{displayDepartment(row.department)||'-'}}</td><td class="cell">{{row.designation||'-'}}</td><td class="cell">{{row.date_of_joining||'-'}}</td><td class="cell">{{row.relieving_date||'-'}}</td>
<td class="cell"><input v-model="row.payment_days" :disabled="locked(row)" type="number" min="0" :max="row.total_working_days" step="0.5" class="amount"/><div class="hint">共 {{row.total_working_days}} 天</div><div v-if="row.working_days_source===`calendar_fallback`" class="warning">未设假日表，按日历天数</div></td><td class="cell font-medium">{{row.employee_name}}</td>
<td class="cell"><input v-model="row.base_salary" :disabled="locked(row)" type="number" min="0" step="0.01" class="amount"/></td><td class="cell"><input v-model="row.salary_adjustment" :disabled="locked(row)" type="number" step="0.01" class="amount"/></td><td class="cell number">{{money(adjusted(row))}}</td>
<td class="cell"><input v-model="row.company_subsidy" :disabled="locked(row)" type="number" min="0" step="0.01" class="amount"/></td><td class="cell"><input v-model="row.bonus" :disabled="locked(row)" type="number" min="0" step="0.01" class="amount"/></td><td class="cell"><input v-model="row.other_adjustment" :disabled="locked(row)" type="number" step="0.01" class="amount"/></td><td class="cell number font-medium">{{money(payable(row))}}</td>
<td class="cell number">{{money(row.employee_pension)}}</td><td class="cell number">{{money(row.employee_medical)}}</td><td class="cell number">{{money(row.employee_unemployment)}}</td><td class="cell number"><span v-if="row.social_record_exists">{{money(row.social_insurance)}}</span><span v-else class="warning">社保未维护</span></td><td class="cell number"><span v-if="row.housing_record_exists">{{money(row.housing_fund)}}</span><span v-else class="warning">公积金未维护</span></td>
<td class="cell"><input v-model="row.income_tax" :disabled="locked(row)" type="number" min="0" step="0.01" class="amount"/></td><td class="cell number">{{money(row.accommodation)}}</td><td class="cell"><input v-model="row.advanced_paid" :disabled="locked(row)" type="number" min="0" step="0.01" class="amount"/></td><td class="cell number font-semibold" :class="net(row)<0?'text-red-600':'text-gray-900'">{{money(net(row))}}</td>
<td class="cell">{{row.bank_name||'-'}}</td><td class="cell">{{row.bank_ac_no||'-'}}</td><td class="cell">{{row.cell_number||'-'}}</td>
<td class="cell min-w-52"><div class="mb-2">{{row.docstatus===1?'已提交':row.salary_slip?(row.managed?'人事中心草稿':'外部草稿'):'未生成'}}</div><div class="flex flex-wrap gap-1"><Button size="sm" variant="solid" :disabled="locked(row)||!row.social_record_exists||!row.housing_record_exists" :loading="saving[row.employee]" @click="saveRow(row)">保存草稿</Button><Button size="sm" variant="subtle" :disabled="locked(row)||n(row.salary_adjustment)===0||adjusted(row)<=0" :loading="applying[row.employee]" @click="applyAdjustment(row)">应用调薪</Button></div><p v-if="messages[row.employee]" class="mt-1 text-green-700">{{messages[row.employee]}}</p><p v-if="errors[row.employee]" class="mt-1 text-red-600">{{errors[row.employee]}}</p></td>
</tr><tr v-if="!(rows.data||[]).length"><td colspan="31" class="py-10 text-center text-gray-400">本期没有符合任职期间的员工</td></tr>
</tbody></table></div>
</Card>
</div>
</template>
<style scoped>
.cell{padding:.5rem .65rem;text-align:left;white-space:nowrap}.number{text-align:right;font-variant-numeric:tabular-nums}.amount{width:7rem;border-radius:.375rem;border:1px solid rgb(209 213 219);padding:.4rem .5rem;text-align:right;font-size:.75rem}.amount:disabled{background:rgb(243 244 246);color:rgb(107 114 128)}.hint{margin-top:.2rem;color:rgb(156 163 175)}.warning{color:rgb(220 38 38);font-weight:600}
</style>