<script setup>
import { computed, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { useRoute, useRouter } from 'vue-router';
import { boardRoute } from '../lib/expenseBoards.js';
import { hereAsFrom } from '../lib/navContext.js';

const route = useRoute();
const router = useRouter();
const kind = computed(() => route.path === '/approval/payment-dashboard' ? 'payment' : 'request');
const title = computed(() => kind.value === 'payment' ? '付款看板' : '申请看板');
const selectedNames = ref([]);
const selectedLabel = ref('全部单据');

const resource = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.get_approval_center_dashboard',
  method: 'GET',
  makeParams: () => ({ kind: kind.value }),
  auto: true,
});

watch(kind, () => {
  selectedNames.value = [];
  selectedLabel.value = '全部单据';
  resource.reload();
});

const data = computed(() => resource.data || {
  summary: {},
  asset_summary: {},
  prepayment_risk_summary: {},
  rows: [],
});

const moneyCards = [
  ['applied_amount', '申请金额'],
  ['approved_amount', '批准金额'],
  ['reserved_amount', '占用金额'],
  ['paid_amount', '已付金额'],
  ['available_amount', '可用余额'],
];

const emptyBucket = (label) => ({ label, count: 0, applied_amount: 0, names: [] });
const bucket = (value, label) => ({ ...emptyBucket(label), ...(value || {}), label });

const assetCards = computed(() => {
  const summary = data.value.asset_summary || {};
  return [
    bucket(summary.fixed_asset, '固定资产'),
    bucket(summary.non_fixed_asset, '非固定资产'),
    bucket(summary.historical_unclassified, '历史未分类'),
    ...(summary.categories || []).map((item) => bucket(item, item.label || '固定资产未分类')),
  ];
});

const riskCards = computed(() => {
  const summary = data.value.prepayment_risk_summary || {};
  return [
    bucket(summary.overdue_full_prepayment, '100%预付款逾期'),
    bucket(summary.pending_arrival, '待到货'),
    bucket(summary.pending_inspection, '待验收'),
    bucket(summary.inspection_rejected, '验收不合格'),
    bucket(summary.pending_writeoff, '待预付款核销'),
  ];
});

// 从"关联付款 N 笔 / 来源申请 N 张"点进来时地址里带着 source_request= / request=：表格只显示相关的单据，并在表头上说明、可以一键清除。
const linkedRequest = computed(() => String(route.query.source_request || route.query.request || ''));

const filteredRows = computed(() => {
  const linkedName = linkedRequest.value;
  if (linkedName) return (data.value.rows || []).filter((row) => row.name === linkedName || (row.linked_requests || []).includes(linkedName));
  if (!selectedNames.value.length) return data.value.rows || [];
  const names = new Set(selectedNames.value);
  return (data.value.rows || []).filter((row) => names.has(row.name));
});

function selectDrilldown(card) {
  selectedNames.value = Array.from(card.names || []);
  selectedLabel.value = card.label;
}

function showAll() {
  selectedNames.value = [];
  selectedLabel.value = '全部单据';
  router.replace({ path: route.path });
}

function openRelatedPayments(row) {
  router.push({ path: '/approval/payment-dashboard', query: { source_request: row.name } });
}

function openSourceRequest(row) {
  const name = (row.linked_requests || [])[0];
  if (name) router.push({ path: '/approval/request-dashboard', query: { request: name } });
}

// 按单据自己的类型打开（购买申请、出差申请、报销单…各有各的页面），类型不明才按看板种类猜；带上来源，返回时回到这里。
function openDocument(row) {
  const mapped = boardRoute(row.request_type);
  const fallback = kind.value === 'payment' ? '/approval/procurement-payment' : '/approval/procurement';
  router.push({ path: mapped === '/dashboard' ? fallback : mapped, query: { request: row.name, from: hereAsFrom(route.path, route.query) } });
}

const money = (value) => Number(value || 0).toLocaleString('zh-CN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
</script>

<template>
  <div class="space-y-5">
    <section v-if="resource.loading" class="rounded-lg border bg-white p-10 text-center text-sm text-gray-500 shadow-sm">
      正在加载看板数据…
    </section>
    <template v-else>
    <section class="rounded-lg border bg-white p-6 shadow-sm">
      <h1 class="text-xl font-semibold">{{ title }}</h1>
      <p class="mt-1 text-sm text-gray-500">只展示当前登录账号在服务端权限范围内可见的单据。</p>
      <div v-if="data.can_view_financial" class="mt-5 grid gap-3 md:grid-cols-5">
        <div v-for="card in moneyCards" :key="card[0]" class="rounded border bg-gray-50 p-4">
          <div class="text-sm text-gray-500">{{ card[1] }}</div>
          <div class="mt-1 text-xl font-semibold">{{ money(data.summary[card[0]]) }}</div>
        </div>
      </div>
    </section>

    <section class="rounded-lg border bg-white p-6 shadow-sm">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="font-semibold">资产分类</h2>
          <p class="mt-1 text-xs text-gray-500">固定资产类别按申请单保存的分类聚合；旧数据单独列为历史未分类。</p>
        </div>
        <button type="button" class="rounded border px-3 py-1.5 text-sm" @click="showAll">显示全部</button>
      </div>
      <div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <button
          v-for="card in assetCards"
          :key="card.label"
          type="button"
          class="rounded border p-4 text-left hover:border-gray-500"
          :class="{ 'border-gray-900 ring-1 ring-gray-900': selectedLabel === card.label }"
          @click="selectDrilldown(card)"
        >
          <div class="text-sm text-gray-500">{{ card.label }}</div>
          <div class="mt-2 text-2xl font-semibold">{{ card.count }}</div>
          <div class="mt-1 text-xs text-gray-500">申请金额 {{ money(card.applied_amount) }}</div>
        </button>
      </div>
    </section>

    <section v-if="kind === 'payment'" class="rounded-lg border bg-white p-6 shadow-sm">
      <h2 class="font-semibold">预付款与到货风险</h2>
      <p class="mt-1 text-xs text-gray-500">仅统计采购付款；卡片可下钻到对应付款单。</p>
      <div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <button
          v-for="card in riskCards"
          :key="card.label"
          type="button"
          class="rounded border p-4 text-left hover:border-amber-500"
          :class="{ 'border-amber-600 bg-amber-50': selectedLabel === card.label }"
          @click="selectDrilldown(card)"
        >
          <div class="text-sm text-gray-600">{{ card.label }}</div>
          <div class="mt-2 text-2xl font-semibold">{{ card.count }}</div>
          <div class="mt-1 text-xs text-gray-500">申请金额 {{ money(card.applied_amount) }}</div>
        </button>
      </div>
    </section>

    <section class="rounded-lg border bg-white p-6 shadow-sm">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="font-semibold">{{ linkedRequest ? '关联单据' : selectedLabel }}（{{ filteredRows.length }}）</h2>
        <button v-if="selectedNames.length || linkedRequest" type="button" class="text-sm text-gray-600 underline" @click="showAll">显示全部</button>
      </div>
      <div v-if="linkedRequest" class="mb-3 flex items-center justify-between gap-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" data-testid="linked-filter">
        <span>只显示与 <b>{{ linkedRequest }}</b> 关联的单据（{{ kind === 'payment' ? '来源申请' : '关联付款 / 采购链路' }}）。</span>
        <button type="button" class="shrink-0 underline" @click="showAll">清除筛选，显示全部</button>
      </div>
      <div class="overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="border-b text-left text-gray-500">
              <th class="p-2">单号</th>
              <th class="p-2">类型</th>
              <th class="p-2">主题</th>
              <th class="p-2">审批状态</th>
              <th v-if="kind === 'payment'" class="p-2">业务状态</th>
              <th class="p-2">采购链路</th>
              <th class="p-2">PO执行</th>
              <th class="p-2">资产分类</th>
              <template v-if="data.can_view_financial"><th v-for="card in moneyCards" :key="card[0]" class="p-2 text-right">{{ card[1] }}</th></template>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filteredRows" :key="row.name" class="border-b">
              <td class="p-2"><button type="button" class="font-medium text-blue-700 hover:underline" @click="openDocument(row)">{{ row.name }}</button></td>
              <td class="p-2">{{ row.request_type }}</td>
              <td class="p-2">{{ row.subject }}</td>
              <td class="p-2">{{ row.workflow_status }}</td>
              <td v-if="kind === 'payment'" class="p-2">{{ row.business_status || '-' }}</td>
              <td class="p-2 text-xs leading-5 text-gray-600">
                <template v-if="kind === 'request'">
                  <div>PR {{ row.linked_prs?.length || 0 }}<template v-if="data.can_view_financial"> · 价格审批 {{ row.linked_price_approvals?.length || 0 }}</template></div>
                  <template v-if="data.can_view_financial"><button v-if="row.linked_payments?.length" type="button" class="text-blue-700 hover:underline" @click="openRelatedPayments(row)">关联付款 {{ row.linked_payments.length }} 笔</button><span v-else>暂未生成付款</span></template>
                </template>
                <template v-else>
                  <div>{{ row.source_purchase_order || '未关联PO' }} · {{ row.supplier || '-' }}</div>
                  <button v-if="row.linked_requests?.length" type="button" class="text-blue-700 hover:underline" @click="openSourceRequest(row)">来源申请 {{ row.linked_requests.length }} 张</button>
                </template>
              </td>
              <td class="p-2 text-xs leading-5 text-gray-600">
                <div v-if="kind === 'request'">PO {{ row.linked_pos?.length || 0 }} · {{ row.po_statuses?.join('、') || '未下单' }}</div>
                <div v-else>{{ row.po_status || '-' }} · PO总额 {{ money(row.po_total_amount) }}</div>
                <div v-if="data.can_view_financial">已付 {{ money(row.po_paid_amount) }} · 未付 {{ money(row.po_unpaid_amount) }}</div>
              </td>
              <td class="p-2">{{ row.asset_classification || '历史未分类' }}</td>
              <template v-if="data.can_view_financial"><td v-for="card in moneyCards" :key="card[0]" class="p-2 text-right">{{ money(row[card[0]]) }}</td></template>
            </tr>
          </tbody>
        </table>
        <p v-if="!filteredRows.length" class="py-10 text-center text-gray-400">当前分类暂无可见单据。</p>
      </div>
    </section>
    </template>
  </div>
</template>
