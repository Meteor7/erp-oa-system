<script setup>
import { computed, reactive, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Card, Button, createResource } from "frappe-ui";
import { period, usePeriodFromRoute } from "../lib/period";
const props = defineProps({ kind: { type: String, required: true } });
// 看板链接带 ?period=YYYY-MM：先读好期间，再建下面的数据请求。
usePeriodFromRoute(useRoute(), useRouter());
const social = computed(() => props.kind === "social");
const title = computed(() => social.value ? "社保信息管理" : "公积金信息管理");
const subtitle = computed(() => social.value ? "按月维护员工社保基数与比例，金额由系统自动计算" : "按月维护员工公积金基数与比例，金额由系统自动计算");
const baseUrl = "rayher_hr_payroll.api.hr_contribution_entry.";
const employees = createResource({ url: baseUrl + "get_employee_options", method: "GET", auto: true });
const rows = createResource({ url: baseUrl + (props.kind === "social" ? "list_social_insurance" : "list_housing_fund"), method: "GET", makeParams: () => ({ period: period.value }), auto: true });
const saver = createResource({ url: baseUrl + (props.kind === "social" ? "save_social_insurance" : "save_housing_fund") });
const blank = () => social.value ? { employee:"",contribution_base:"",employee_pension_rate:8,company_pension_rate:16,employee_medical_rate:2,company_medical_rate:7,employee_unemployment_rate:0.5,company_unemployment_rate:0.5,company_injury_rate:0.4,company_maternity_rate:0.8,status:"Draft",remark:"" } : { employee:"",contribution_base:"",employee_rate:7,company_rate:7,status:"Draft",remark:"" };
const form = reactive(blank());
const error = computed(() => saver.error?.message || "");
const n = (v) => Number(v || 0);
const money = (v) => n(v).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2});
const pct = (rate) => Math.round(n(form.contribution_base) * n(rate)) / 100;
const employeeTotal = computed(() => social.value ? pct(form.employee_pension_rate)+pct(form.employee_medical_rate)+pct(form.employee_unemployment_rate) : pct(form.employee_rate));
const companyTotal = computed(() => social.value ? pct(form.company_pension_rate)+pct(form.company_medical_rate)+pct(form.company_unemployment_rate)+pct(form.company_injury_rate)+pct(form.company_maternity_rate) : pct(form.company_rate));
async function save(){
  if(!form.employee || n(form.contribution_base)<0) return;
  await saver.submit({period:period.value,...form});
  Object.assign(form,blank());
  rows.reload();
}
function applyEmployeeDefaultBase(){
  const employee=(employees.data||[]).find((row)=>row.name===form.employee);
  form.contribution_base=employee ? (social.value ? employee.default_social_insurance_base : employee.default_housing_fund_base) : "";
}
function edit(row){Object.assign(form,blank(),row)}
watch(period,()=>rows.reload());
</script>
<template>
  <div class="space-y-4">
    <Card :title="title" :subtitle="subtitle">
      <div class="mb-4 flex flex-wrap items-end gap-3">
        <label class="text-xs text-gray-500">期间<input v-model="period" type="month" class="mt-1 block rounded border border-gray-300 px-3 py-2 text-sm" /></label>
        <label class="min-w-48 text-xs text-gray-500">员工<select v-model="form.employee" class="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm" @change="applyEmployeeDefaultBase"><option value="">请选择</option><option v-for="e in employees.data||[]" :key="e.name" :value="e.name">{{e.employee_name}}</option></select></label>
        <label class="text-xs text-gray-500">缴费基数<input v-model="form.contribution_base" type="number" min="0" step="0.01" class="mt-1 block w-36 rounded border border-gray-300 px-3 py-2 text-sm text-right" /></label>
        <label class="text-xs text-gray-500">状态<select v-model="form.status" class="mt-1 block rounded border border-gray-300 px-3 py-2 text-sm"><option value="Draft">草稿</option><option value="Confirmed">已确认</option></select></label>
      </div>
      <div v-if="social" class="grid gap-3 rounded-lg bg-gray-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
        <label v-for="field in [
          ['employee_pension_rate','个人养老'],['company_pension_rate','公司养老'],['employee_medical_rate','个人医疗'],['company_medical_rate','公司医疗'],
          ['employee_unemployment_rate','个人失业'],['company_unemployment_rate','公司失业'],['company_injury_rate','公司工伤'],['company_maternity_rate','公司生育']
        ]" :key="field[0]" class="text-xs text-gray-500">{{field[1]}}（%）<input v-model="form[field[0]]" type="number" min="0" step="0.01" class="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm text-right"/></label>
      </div>
      <div v-else class="grid gap-3 rounded-lg bg-gray-50 p-4 sm:grid-cols-2">
        <label class="text-xs text-gray-500">个人比例（%）<input v-model="form.employee_rate" type="number" min="0" step="0.01" class="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm text-right"/></label>
        <label class="text-xs text-gray-500">公司比例（%）<input v-model="form.company_rate" type="number" min="0" step="0.01" class="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm text-right"/></label>
      </div>
      <div class="mt-3 flex flex-wrap items-center gap-4">
        <span class="text-sm text-gray-600">个人预计：<b>{{money(employeeTotal)}}</b></span><span class="text-sm text-gray-600">公司预计：<b>{{money(companyTotal)}}</b></span>
        <input v-model="form.remark" placeholder="备注（可选）" class="min-w-64 flex-1 rounded border border-gray-300 px-3 py-2 text-sm"/>
        <Button variant="solid" :loading="saver.loading" @click="save">保存</Button>
      </div>
      <p v-if="error" class="mt-2 text-xs text-red-600">{{error}}</p>
    </Card>
    <Card :title="period+' 已保存记录'">
      <div class="overflow-x-auto"><table class="w-full min-w-[760px] text-sm">
        <thead class="border-b text-gray-500"><tr><th class="px-3 py-2 text-left">员工</th><th class="px-3 py-2 text-right">基数</th><th class="px-3 py-2 text-right">个人合计</th><th class="px-3 py-2 text-right">公司合计</th><th class="px-3 py-2 text-left">状态</th><th class="px-3 py-2 text-right">操作</th></tr></thead>
        <tbody><tr v-for="r in rows.data||[]" :key="r.name" class="border-b last:border-0"><td class="px-3 py-2">{{r.employee_name}}</td><td class="px-3 py-2 text-right">{{money(r.contribution_base)}}</td><td class="px-3 py-2 text-right">{{money(social?r.employee_total:r.employee_amount)}}</td><td class="px-3 py-2 text-right">{{money(social?r.company_total:r.company_amount)}}</td><td class="px-3 py-2">{{r.status==='Confirmed'?'已确认':'草稿'}}</td><td class="px-3 py-2 text-right"><button class="text-blue-600" @click="edit(r)">编辑</button></td></tr><tr v-if="!(rows.data||[]).length"><td colspan="6" class="py-8 text-center text-gray-400">本期暂无记录，请在上方填写</td></tr></tbody>
      </table></div>
    </Card>
  </div>
</template>
