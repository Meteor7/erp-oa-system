<script setup>
import { Button, FeatherIcon, createResource } from 'frappe-ui';
import { computed, reactive } from 'vue';
import { dateTime, toApprovalRecordParams } from '../../lib/expenseReporting.js';

const props = defineProps({
  options: { type: Object, default: () => ({}) },
});
const emit = defineEmits(['open-request']);

const filters = reactive({
  requestKeyword: '',
  employee: '',
  department: '',
  approver: '',
  action: '',
  workflowStatus: '',
  fromDate: '',
  toDate: '',
});
const workflowStatuses = ['草稿', '待审批', '待办理', '已完成', '已拒绝', '已付款'];
const commonActions = ['发票下推', '提交申请', '待审批', '待流转', '已通过', '已办理', '已拒绝', '撤回申请', '撤回发票下推', '标记已付款', '撤回付款'];

const records = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_expense_approval_records',
  method: 'GET',
  makeParams: () => toApprovalRecordParams(filters),
  auto: true,
});

const rows = computed(() => records.data?.records || []);

function search() {
  records.reload();
}

function reset() {
  Object.keys(filters).forEach((key) => { filters[key] = ''; });
  records.reload();
}

function refresh() {
  records.reload();
}

function errorText(error) {
  return String(error?.messages?.[0] || error?._error_message || error?.message || '审批记录加载失败')
    .replace(/<[^>]*>/g, '')
    .trim();
}

function openRequest(name) {
  if (name) emit('open-request', name);
}

function statusClass(status) {
  return {
    '草稿': 'bg-gray-100 text-gray-700',
    '待审批': 'bg-amber-50 text-amber-700',
    '待办理': 'bg-amber-50 text-amber-700',
    '已完成': 'bg-emerald-50 text-emerald-700',
    '已付款': 'bg-blue-50 text-blue-700',
    '已拒绝': 'bg-red-50 text-red-700',
  }[status] || 'bg-gray-100 text-gray-700';
}

defineExpose({ reload: refresh });
</script>

<template>
  <section class="space-y-4">
    <header class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
      <div>
        <h2 class="text-xl font-bold text-gray-900">审批记录</h2>
        <p class="mt-1 text-sm text-gray-500">集中查看审批节点和下推、撤回、付款等操作日志。</p>
      </div>
      <Button variant="subtle" :loading="records.loading" @click="refresh">
        <FeatherIcon name="refresh-cw" class="h-4 w-4" />刷新
      </Button>
    </header>

    <div class="rounded border bg-white p-4 shadow-sm">
      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
        <label class="text-xs text-gray-500">申请单关键字<input v-model="filters.requestKeyword" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="单据号 / 主题" /></label>
        <label class="text-xs text-gray-500">申请人<input v-model="filters.employee" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="员工编号" /></label>
        <label class="text-xs text-gray-500">部门<select v-model="filters.department" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">全部部门</option><option v-for="item in props.options?.departments || []" :key="item" :value="item">{{ item }}</option></select></label>
        <label class="text-xs text-gray-500">审批人<input v-model="filters.approver" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="账号或姓名" /></label>
        <label class="text-xs text-gray-500">操作<select v-model="filters.action" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">全部操作</option><option v-for="item in commonActions" :key="item">{{ item }}</option></select></label>
        <label class="text-xs text-gray-500">当前状态<select v-model="filters.workflowStatus" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">全部状态</option><option v-for="item in workflowStatuses" :key="item">{{ item }}</option></select></label>
        <label class="text-xs text-gray-500">操作开始日期<input v-model="filters.fromDate" type="date" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
        <label class="text-xs text-gray-500">操作结束日期<input v-model="filters.toDate" type="date" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
        <div class="flex items-end justify-end gap-2 xl:col-span-4 2xl:col-span-2">
          <Button variant="subtle" @click="reset">重置</Button>
          <Button variant="solid" :loading="records.loading" @click="search">查询</Button>
        </div>
      </div>
    </div>

    <div v-if="records.error" role="alert" class="rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{{ errorText(records.error) }}</div>
    <div v-if="records.data?.truncated" class="rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">结果达到服务端安全上限，请缩小筛选范围。</div>

    <div class="overflow-hidden rounded border bg-white shadow-sm">
      <div class="border-b px-4 py-3 text-sm font-semibold">审批与操作明细 <span class="ml-2 text-xs font-normal text-gray-400">{{ rows.length }} 条</span></div>
      <div class="overflow-x-auto">
        <table class="w-full min-w-[1580px] text-sm">
          <thead class="border-b bg-gray-50 text-xs text-gray-500">
            <tr>
              <th class="px-3 py-3 text-left">申请单</th><th class="px-3 py-3 text-left">申请人 / 部门</th>
              <th class="px-3 py-3 text-left">事件类型</th><th class="px-3 py-3 text-left">审批节点</th>
              <th class="px-3 py-3 text-left">审批人</th><th class="px-3 py-3 text-left">操作</th>
              <th class="px-3 py-3 text-left">操作人</th><th class="px-3 py-3 text-left">操作时间</th>
              <th class="px-3 py-3 text-left">备注</th><th class="px-3 py-3 text-left">当前状态</th><th class="px-3 py-3 text-left">来源</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row,index) in rows" :key="`${row.request_name}-${row.event_type}-${row.acted_on}-${index}`" class="border-b hover:bg-blue-50">
              <td class="px-3 py-3"><button class="font-medium text-blue-700 hover:underline" @click="openRequest(row.request_name)">{{ row.request_name }}</button><div class="mt-1 max-w-[220px] truncate text-xs text-gray-400">{{ row.subject || '-' }}</div></td>
              <td class="px-3 py-3">{{ row.employee_name || row.employee || '-' }}<div class="mt-1 text-xs text-gray-400">{{ row.department || '-' }}</div></td>
              <td class="px-3 py-3">{{ row.event_type || '-' }}</td><td class="px-3 py-3">{{ row.step_label || '-' }}</td>
              <td class="max-w-[220px] px-3 py-3">{{ row.approvers?.length ? row.approvers.join(' / ') : '-' }}</td>
              <td class="px-3 py-3 font-medium">{{ row.action || '-' }}</td><td class="px-3 py-3">{{ row.actor || '-' }}</td>
              <td class="px-3 py-3 text-gray-500">{{ dateTime(row.acted_on) }}</td>
              <td class="max-w-[260px] px-3 py-3 whitespace-pre-wrap">{{ row.note || '-' }}</td>
              <td class="px-3 py-3"><span class="rounded px-2 py-1 text-xs" :class="statusClass(row.workflow_status)">{{ row.workflow_status || '-' }}</span></td>
              <td class="px-3 py-3">{{ row.source_type || '-' }}</td>
            </tr>
            <tr v-if="records.loading"><td colspan="11" class="py-20 text-center text-gray-400">正在加载审批记录...</td></tr>
            <tr v-else-if="!rows.length"><td colspan="11" class="py-20 text-center text-gray-400">暂无审批或操作记录</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>
