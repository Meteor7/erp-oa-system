<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { Card, Button, Badge, createResource } from "frappe-ui";
import { period } from "../lib/period";
import { displayCompany } from "../lib/displayBrand.js";
import { extractFrappeError } from "../lib/frappeError";

const api = "rayher_hr_payroll.api.social_insurance_import_entry.";
const company = ref("all");
const selectedFile = ref(null);
const preview = ref(null);
const message = ref("");
const error = ref("");
const notes = ref({});
const batchNotes = ref({});
const selectedEmployees = ref({});
const companyOptions = [
  { value: "all", label: "全部公司" },
  { value: "Rayher", label: "示例总部" },
  { value: "示例研发中心", label: "示例研发中心" },
];
const workbench = createResource({
  url: api + "get_social_workbench", method: "GET",
  makeParams: () => ({ period: period.value, company: company.value }), auto: true,
});
const uploader = createResource({ url: api + "upload_social_workbook" });
const activator = createResource({ url: api + "activate_social_batch" });
const confirmer = createResource({ url: api + "confirm_social_row" });
const ignorer = createResource({ url: api + "ignore_social_row" });
const canceler = createResource({ url: api + "cancel_social_batch" });
const employees = createResource({
  url: api + "get_employee_options", method: "GET",
  makeParams: () => ({ company: "all" }), auto: true,
});
const data = computed(() => preview.value || workbench.data || {
  dashboard: {}, company_summaries: [], batches: [], pending: [], details: [],
});
const dashboard = computed(() => data.value.dashboard || {});
const money = value => Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const ratio = (value, numerator, denominator) => `${Number(value || 0).toFixed(2)}%（${numerator || 0}/${denominator || 0}）`;
const statusLabel = value => ({
  Matched: "匹配成功", Pending: "待确认", "Confirmed Difference": "已确认差异", Ignored: "已忽略",
  Current: "当前有效", Historical: "历史批次", "Pending Activation": "待确认导入", Canceled: "已取消", Failed: "失败",
}[value] || value);
const statusTheme = value => value === "Matched" || value === "Current" ? "green" : value === "Pending" || value === "Pending Activation" ? "orange" : "gray";
const employeeOptionsFor = row => (employees.data || []).filter(employee => !row.company || employee.company === row.company);

watch([period, company], () => { preview.value = null; workbench.reload(); employees.reload(); });

function chooseFile(event) { selectedFile.value = event.target.files?.[0] || null; error.value = ""; }
function readDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("读取Excel失败")); reader.readAsDataURL(file);
  });
}
async function upload() {
  error.value = ""; message.value = "";
  if (!selectedFile.value) { error.value = "请选择Excel文件"; return; }
  try {
    const result = await uploader.submit({ filename: selectedFile.value.name, content_base64: await readDataUrl(selectedFile.value) });
    if (company.value !== "all") { company.value = "all"; await nextTick(); }
    period.value = result.period || period.value; preview.value = result;
    message.value = `Excel已识别为${result.period}；后台已使用员工档案基数、户口信息和期间政策独立复算`;
  } catch (exception) { error.value = extractFrappeError(exception, "上传失败"); }
}
async function activate(batch) {
  error.value = ""; message.value = "";
  if (Number(batch.pending_rows || 0) > 0) { error.value = "请先处理该批次全部待确认明细"; return; }
  try {
    await activator.submit({ batch: batch.name }); period.value = batch.period || period.value;
    preview.value = null; await workbench.reload(); message.value = "该批次已设为当前有效批次";
  } catch (exception) { error.value = extractFrappeError(exception, "确认导入失败"); }
}
async function cancelBatch(batch) {
  error.value = ""; message.value = "";
  const remark = (batchNotes.value[batch.name] || "").trim();
  if (!remark) { error.value = "取消批次前必须填写原因"; return; }
  try {
    preview.value = await canceler.submit({ batch: batch.name, remark });
    message.value = "批次已取消，原文件和解析审计记录仍然保留";
  } catch (exception) { error.value = extractFrappeError(exception, "取消批次失败"); }
}
async function confirmRow(row) {
  error.value = ""; message.value = "";
  const remark = (notes.value[row.name] || "").trim();
  if (!remark) { error.value = "确认差异前必须填写备注"; return; }
  try {
    preview.value = await confirmer.submit({ row: row.name, employee: selectedEmployees.value[row.name] || row.employee || "", remark });
    message.value = `${row.excel_name}已确认并纳入本批次`;
  } catch (exception) { error.value = extractFrappeError(exception, "确认差异失败"); }
}
async function ignoreRow(row) {
  error.value = ""; message.value = "";
  const remark = (notes.value[row.name] || "").trim();
  if (!remark) { error.value = "忽略明细前必须填写原因"; return; }
  try {
    preview.value = await ignorer.submit({ row: row.name, remark });
    message.value = `${row.excel_name}已忽略，不会进入正式社保明细`;
  } catch (exception) { error.value = extractFrappeError(exception, "忽略明细失败"); }
}
</script>

<template>
  <div class="space-y-4">
    <Card title="社保汇总看板" subtitle="按期间和所属公司查看Excel申报金额、员工档案独立复算结果及数据质量">
      <div class="mb-4 flex flex-wrap items-end gap-3">
        <label class="text-xs text-gray-500">社保期间<input v-model="period" type="month" class="field mt-1" /></label>
        <label class="min-w-48 text-xs text-gray-500">所属公司<select v-model="company" class="field mt-1"><option v-for="option in companyOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      </div>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="kpi"><span>Excel参保人数</span><b>{{ dashboard.total_rows || 0 }}</b></div>
        <div class="kpi"><span>个人承担合计</span><b>{{ money(dashboard.employee_total) }}</b></div>
        <div class="kpi"><span>单位承担合计</span><b>{{ money(dashboard.company_total) }}</b></div>
        <div class="kpi"><span>应收合计</span><b>{{ money(dashboard.receivable_total) }}</b></div>
        <div class="kpi"><span>严格匹配率</span><b>{{ ratio(dashboard.match_rate, dashboard.matched_rows, dashboard.total_rows) }}</b></div>
        <div class="kpi"><span>数据可比较率</span><b>{{ ratio(dashboard.comparable_rate, dashboard.comparable_rows, dashboard.total_rows) }}</b></div>
        <div class="kpi"><span>自动关联率</span><b>{{ ratio(dashboard.automatic_link_rate, dashboard.linked_rows, dashboard.total_rows) }}</b></div>
        <div class="kpi"><span>待确认人数</span><b>{{ dashboard.pending_rows || 0 }}</b></div>
      </div>
      <div v-if="company==='all'" class="mt-4 overflow-x-auto"><table class="w-full min-w-[760px] text-sm">
        <thead><tr><th>所属公司</th><th>参保人数</th><th>个人合计</th><th>单位合计</th><th>应收合计</th><th>严格匹配</th><th>待确认</th></tr></thead>
        <tbody><tr v-for="item in data.company_summaries||[]" :key="item.company"><td>{{ item.company_display }}</td><td>{{ item.total_rows }}</td><td>{{ money(item.employee_total) }}</td><td>{{ money(item.company_total) }}</td><td>{{ money(item.receivable_total) }}</td><td>{{ item.matched_rows }}/{{ item.total_rows }}</td><td>{{ item.pending_rows }}</td></tr></tbody>
      </table></div>
    </Card>

    <Card title="上传Excel与批次管理" subtitle="Excel仅作为申报结果；后台使用员工档案基数、户口信息和对应期间政策独立复算">
      <div class="flex flex-wrap items-end gap-3">
        <label class="min-w-72 text-xs text-gray-500">社保缴费明细（.xlsx）<input type="file" accept=".xlsx" class="field mt-1" @change="chooseFile" /></label>
        <Button variant="solid" :loading="uploader.loading" @click="upload">上传并解析</Button>
      </div>
      <p v-if="message" class="mt-2 text-xs text-green-600">{{ message }}</p><p v-if="error" class="mt-2 text-xs text-red-600">{{ error }}</p>
      <div v-if="data.batches?.length" class="mt-4 overflow-x-auto"><table class="w-full min-w-[1350px] text-sm">
        <thead><tr><th>所属公司</th><th>文件名</th><th>上传时间</th><th>解析人数</th><th>自动匹配</th><th>待确认</th><th>状态</th><th>取消/处理原因</th><th>批次操作</th></tr></thead>
        <tbody><tr v-for="batch in data.batches" :key="batch.name">
          <td>{{ batch.company_display }}</td><td>{{ batch.source_filename }}</td><td>{{ batch.uploaded_at }}</td><td>{{ batch.parsed_rows }}</td><td>{{ batch.matched_rows }}</td><td>{{ batch.pending_rows }}</td><td><Badge :theme="statusTheme(batch.status)">{{ statusLabel(batch.status) }}</Badge></td>
          <td><input v-if="batch.status==='Pending Activation'" v-model="batchNotes[batch.name]" class="field min-w-56" placeholder="取消批次时填写原因"/><span v-else>{{batch.cancel_remark||'-'}}</span></td>
          <td><div v-if="batch.status==='Pending Activation'" class="flex gap-2"><Button size="sm" variant="solid" :disabled="Number(batch.pending_rows||0)>0" @click="activate(batch)">确认导入</Button><Button size="sm" @click="cancelBatch(batch)">取消批次</Button></div><span v-else>-</span></td>
        </tr></tbody>
      </table></div>
    </Card>

    <Card title="待确认社保信息明细" subtitle="不匹配或基础资料不完整的Excel记录，填写备注后确认纳入或忽略">
      <div class="overflow-x-auto"><table class="w-full min-w-[3000px] text-sm">
        <thead><tr><th>所属公司</th><th>姓名</th><th>证件号码</th><th>关联员工</th><th>档案社保基数</th><th>Excel缴费工资</th><th>基数来源</th><th>户口信息</th><th>系统判断</th><th>政策版本</th><th>Excel个人</th><th>后台个人</th><th>Excel单位</th><th>后台单位</th><th>Excel应收</th><th>后台应收</th><th>总差额</th><th>自动差异原因</th><th>备注与操作</th></tr></thead>
        <tbody><tr v-for="row in data.pending||[]" :key="row.name">
          <td>{{ displayCompany(row.company) }}</td><td>{{ row.excel_name }}</td><td>{{ row.masked_identity }}</td>
          <td><select v-model="selectedEmployees[row.name]" class="field min-w-40"><option :value="row.employee||''">{{ row.employee_name || '请选择员工' }}</option><option v-for="employee in employeeOptionsFor(row)" :key="employee.name" :value="employee.name">{{ employee.employee_name }}</option></select></td>
          <td class="num">{{ money(row.reference_base) }}</td><td class="num">{{ money(row.contribution_base) }}</td><td>{{row.base_source||'-'}}</td><td>{{row.household_source||'未维护'}}</td><td><Badge :theme="row.household_classification==='待完善'?'orange':'gray'">{{row.household_classification||'待完善'}}</Badge></td><td>{{row.policy_version||'未配置'}}</td>
          <td class="num">{{money(row.employee_total)}}</td><td class="num">{{money(row.calculated_employee_total)}}</td><td class="num">{{money(row.company_total)}}</td><td class="num">{{money(row.calculated_company_total)}}</td><td class="num">{{money(row.receivable_total)}}</td><td class="num">{{money(row.calculated_receivable_total)}}</td><td class="num">{{money(row.difference_total)}}</td>
          <td class="max-w-80 whitespace-normal text-red-600">{{ row.difference_reasons }}</td>
          <td><div class="flex min-w-[480px] gap-2"><input v-model="notes[row.name]" class="field flex-1" placeholder="填写确认或忽略原因"/><Button size="sm" variant="solid" @click="confirmRow(row)">确认并纳入本批次</Button><Button size="sm" @click="ignoreRow(row)">忽略此行</Button></div></td>
        </tr><tr v-if="!(data.pending||[]).length"><td colspan="19" class="empty">没有待确认社保信息</td></tr></tbody>
      </table></div>
    </Card>

    <Card title="社保信息明细" subtitle="展示当前批次自动匹配成功或人工确认纳入的Excel申报记录">
      <div class="overflow-x-auto"><table class="w-full min-w-[2400px] text-sm">
        <thead><tr><th>所属公司</th><th>员工</th><th>档案社保基数</th><th>Excel缴费工资</th><th>基数来源</th><th>户籍判断</th><th>个人养老</th><th>单位养老</th><th>个人医疗</th><th>单位医疗</th><th>单位生育</th><th>单位工伤</th><th>个人失业</th><th>单位失业</th><th>地方补充养老</th><th>个人合计</th><th>单位合计</th><th>应收合计</th><th>匹配状态</th><th>备注</th></tr></thead>
        <tbody><tr v-for="row in data.details||[]" :key="row.name">
          <td>{{displayCompany(row.company)}}</td><td>{{row.employee_name||row.excel_name}}</td><td class="num">{{money(row.reference_base)}}</td><td class="num">{{money(row.contribution_base)}}</td><td>{{row.base_source||'-'}}</td><td>{{row.household_classification||'-'}}</td><td class="num">{{money(row.employee_pension)}}</td><td class="num">{{money(row.company_pension)}}</td><td class="num">{{money(row.employee_medical)}}</td><td class="num">{{money(row.company_medical)}}</td><td class="num">{{money(row.company_maternity)}}</td><td class="num">{{money(row.company_injury)}}</td><td class="num">{{money(row.employee_unemployment)}}</td><td class="num">{{money(row.company_unemployment)}}</td><td class="num">{{money(row.local_pension)}}</td><td class="num">{{money(row.employee_total)}}</td><td class="num">{{money(row.company_total)}}</td><td class="num font-medium">{{money(row.receivable_total)}}</td><td><Badge :theme="statusTheme(row.status)">{{statusLabel(row.status)}}</Badge></td><td>{{row.remark||'-'}}</td>
        </tr><tr v-if="!(data.details||[]).length"><td colspan="20" class="empty">本期暂无社保信息明细</td></tr></tbody>
      </table></div>
    </Card>
  </div>
</template>

<style scoped>
.kpi{display:flex;min-height:88px;flex-direction:column;justify-content:space-between;border-radius:.75rem;background:#f8fafc;padding:1rem;color:#64748b}.kpi b{font-size:1.25rem;color:#111827;font-variant-numeric:tabular-nums}th{white-space:nowrap;border-bottom:1px solid #e5e7eb;padding:.625rem .75rem;text-align:left;color:#6b7280;background:white}td{white-space:nowrap;border-bottom:1px solid #f1f5f9;padding:.625rem .75rem}.num{text-align:right;font-variant-numeric:tabular-nums}.field{display:block;border:1px solid #d1d5db;border-radius:.375rem;padding:.45rem .6rem;font-size:.875rem;background:white}.empty{padding:2rem;text-align:center;color:#9ca3af}
</style>