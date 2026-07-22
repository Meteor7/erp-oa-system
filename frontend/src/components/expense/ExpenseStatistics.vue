<script setup>
import { Button, FeatherIcon, createResource } from 'frappe-ui';
import { computed, reactive } from 'vue';
import { dateTime, money, toExpenseStatisticsParams } from '../../lib/expenseReporting.js';

const props = defineProps({
  options: { type: Object, default: () => ({}) },
});
const emit = defineEmits(['open-request']);

const filters = reactive({
  fromDate: '',
  toDate: '',
  department: '',
  employee: '',
  invoiceCategory: '',
  expenseItem: '',
  projectName: '',
  workflowStatus: '',
  paymentStatus: '',
  sourceType: '',
});

const workflowStatuses = ['草稿', '待审批', '待办理', '已完成', '已拒绝', '已付款'];
const paymentStatuses = ['已付款', '未付款'];
const sourceTypes = ['发票下推', '手工新建', '消费明细下推'];

const statistics = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.get_expense_statistics',
  method: 'GET',
  makeParams: () => toExpenseStatisticsParams(filters),
  auto: true,
});

const rows = computed(() => statistics.data?.rows || []);
const totals = computed(() => statistics.data?.totals || {
  request_count: 0,
  invoice_count: 0,
  amount_before_tax: 0,
  tax_amount: 0,
  total_amount: 0,
  paid_amount: 0,
  unpaid_amount: 0,
});
const metricItems = computed(() => [
  ['申请单数', totals.value.request_count, 'file-text', 'text-gray-900'],
  ['发票张数', totals.value.invoice_count, 'paperclip', 'text-gray-900'],
  ['税前金额', money(totals.value.amount_before_tax), 'pie-chart', 'text-gray-900'],
  ['税额', money(totals.value.tax_amount), 'percent', 'text-gray-900'],
  ['合计金额', money(totals.value.total_amount), 'credit-card', 'text-red-600'],
  ['已付款金额', money(totals.value.paid_amount), 'check-circle', 'text-emerald-600'],
  ['未付款金额', money(totals.value.unpaid_amount), 'clock', 'text-amber-600'],
]);

function search() {
  statistics.reload();
}

function reset() {
  Object.keys(filters).forEach((key) => { filters[key] = ''; });
  statistics.reload();
}

function refresh() {
  statistics.reload();
}

function errorText(error) {
  return String(error?.messages?.[0] || error?._error_message || error?.message || '费用统计加载失败')
    .replace(/<[^>]*>/g, '')
    .trim();
}

function openRequest(name) {
  if (name) emit('open-request', name);
}

defineExpose({ reload: refresh });
</script>

<template>
  <section class="space-y-4">
    <header class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
      <div>
        <h2 class="text-xl font-bold text-gray-900">费用统计</h2>
        <p class="mt-1 text-sm text-gray-500">按申请、发票和付款状态查看费用汇总，点击单据可查看完整明细。</p>
      </div>
      <Button variant="subtle" :loading="statistics.loading" @click="refresh">
        <FeatherIcon name="refresh-cw" class="h-4 w-4" />刷新
      </Button>
    </header>

    <div class="rounded border bg-white p-4 shadow-sm">
      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <label class="text-xs text-gray-500">开始日期<input v-model="filters.fromDate" type="date" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
        <label class="text-xs text-gray-500">结束日期<input v-model="filters.toDate" type="date" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
        <label class="text-xs text-gray-500">部门<select v-model="filters.department" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">全部部门</option><option v-for="item in props.options?.departments || []" :key="item" :value="item">{{ item }}</option></select></label>
        <label class="text-xs text-gray-500">申请人<input v-model="filters.employee" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="员工编号" /></label>
        <label class="text-xs text-gray-500">发票类别<input v-model="filters.invoiceCategory" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="如：电子发票（普通发票）" /></label>
        <label class="text-xs text-gray-500">费用项目<input v-model="filters.expenseItem" list="statistics-expense-items" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="下拉选择或填写" /></label>
        <label class="text-xs text-gray-500">项目名称<input v-model="filters.projectName" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
        <label class="text-xs text-gray-500">审批状态<select v-model="filters.workflowStatus" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">全部状态</option><option v-for="item in workflowStatuses" :key="item">{{ item }}</option></select></label>
        <label class="text-xs text-gray-500">付款状态<select v-model="filters.paymentStatus" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">全部</option><option v-for="item in paymentStatuses" :key="item">{{ item }}</option></select></label>
        <label class="text-xs text-gray-500">来源<select v-model="filters.sourceType" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">全部来源</option><option v-for="item in sourceTypes" :key="item">{{ item }}</option></select></label>
        <div class="flex items-end justify-end gap-2">
          <Button variant="subtle" @click="reset">重置</Button>
          <Button variant="solid" :loading="statistics.loading" @click="search">查询</Button>
        </div>
      </div>
    </div>

    <datalist id="statistics-expense-items"><option v-for="item in props.options?.expense_categories || []" :key="item" :value="item"></option></datalist>

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-7">
      <div v-for="[label,value,icon,color] in metricItems" :key="label" class="rounded border bg-white p-4 shadow-sm">
        <div class="flex items-center justify-between text-xs text-gray-500"><span>{{ label }}</span><FeatherIcon :name="icon" class="h-4 w-4" /></div>
        <div class="mt-2 text-xl font-semibold" :class="color">{{ value }}</div>
      </div>
    </div>

    <div v-if="statistics.error" role="alert" class="rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{{ errorText(statistics.error) }}</div>
    <div v-if="statistics.data?.truncated" class="rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">结果达到服务端安全上限，请缩小筛选范围。</div>

    <div class="overflow-hidden rounded border bg-white shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full min-w-[1640px] text-sm">
          <thead class="border-b bg-gray-50 text-xs text-gray-500">
            <tr>
              <th class="px-3 py-3 text-left">申请单号</th><th class="px-3 py-3 text-left">申请时间</th>
              <th class="px-3 py-3 text-left">申请人</th><th class="px-3 py-3 text-left">部门</th>
              <th class="px-3 py-3 text-left">发票类别</th><th class="px-3 py-3 text-left">项目名称</th>
              <th class="px-3 py-3 text-left">费用项目</th><th class="px-3 py-3 text-left">来源</th><th class="px-3 py-3 text-left">状态</th>
              <th class="px-3 py-3 text-right">税前金额</th><th class="px-3 py-3 text-right">税额</th>
              <th class="px-3 py-3 text-right">合计金额</th><th class="px-3 py-3 text-right">已付</th><th class="px-3 py-3 text-right">未付</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row,index) in rows" :key="`${row.request_name}-${row.invoice_number}-${index}`" class="border-b hover:bg-blue-50">
              <td class="px-3 py-3"><button class="font-medium text-blue-700 hover:underline" @click="openRequest(row.request_name)">{{ row.request_name }}</button></td>
              <td class="px-3 py-3 text-gray-500">{{ dateTime(row.creation) }}</td>
              <td class="px-3 py-3">{{ row.employee_name || row.employee || '-' }}</td><td class="px-3 py-3">{{ row.department || '-' }}</td>
              <td class="max-w-[220px] truncate px-3 py-3" :title="row.invoice_category">{{ row.invoice_category || '-' }}</td>
              <td class="max-w-[220px] truncate px-3 py-3" :title="row.project_name">{{ row.project_name || '-' }}</td>
              <td class="max-w-[180px] truncate px-3 py-3" :title="row.expense_item">{{ row.expense_item || '-' }}</td>
              <td class="px-3 py-3">{{ row.source_type || '-' }}</td><td class="px-3 py-3">{{ row.workflow_status || '-' }}</td>
              <td class="px-3 py-3 text-right">{{ money(row.amount_before_tax) }}</td><td class="px-3 py-3 text-right">{{ money(row.tax_amount) }}</td>
              <td class="px-3 py-3 text-right font-semibold text-red-600">{{ money(row.total_amount) }}</td>
              <td class="px-3 py-3 text-right text-emerald-600">{{ money(row.paid_amount) }}</td><td class="px-3 py-3 text-right text-amber-600">{{ money(row.unpaid_amount) }}</td>
            </tr>
            <tr v-if="statistics.loading"><td colspan="14" class="py-20 text-center text-gray-400">正在加载费用统计...</td></tr>
            <tr v-else-if="!rows.length"><td colspan="13" class="py-20 text-center text-gray-400">暂无统计数据</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>
