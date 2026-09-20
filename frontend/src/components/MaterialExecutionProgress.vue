<script setup>
import { ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
const props = defineProps({ request: { type: String, required: true }, sourceLine: { type: String, default: '' }, expanded: { type: Boolean, default: false } });
const opened = ref(props.expanded);
const data = ref(null);
const loading = ref(false);
const error = ref('');
const page = ref(0);
let version = 0;
const loader = createResource({ url: 'rayher_hr_payroll.api.material_execution.get_progress', method: 'GET' });
async function load() {
  const current = ++version;
  if (!opened.value || !props.request) return;
  loading.value = true; error.value = ''; data.value = null;
  try {
    const result = await loader.fetch({ request: props.request, ...(props.sourceLine ? { source_line: props.sourceLine } : {}), limit: 20, offset: page.value * 20 });
    if (current === version) data.value = result;
  } catch (err) { if (current === version) error.value = err?.messages?.[0] || err?.message || '物料执行进度加载失败'; }
  finally { if (current === version) loading.value = false; }
}
function toggle() { opened.value = !opened.value; if (opened.value) load(); }
function changePage(delta) { page.value += delta; load(); }
watch(() => [props.request, props.sourceLine], () => { ++version; data.value = null; error.value = ''; page.value = 0; loading.value = false; if (opened.value) load(); }, { immediate: true });
const boardLink = (line) => ({ path: '/approval/material-progress', query: { request: props.request, source_line: line || undefined } });
const number = (value) => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 });
</script>

<template>
  <section class="border-b border-gray-200 bg-white px-5 py-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div><h3 class="text-sm font-semibold text-gray-900">物料执行进度</h3><p class="mt-1 text-xs text-gray-500">按原始物料跟踪 PR、核价、PO、到货和验收；付款显示关联 PO 的整体状态。</p></div>
      <button type="button" class="rounded border border-gray-300 px-3 py-1.5 text-sm" :aria-expanded="opened" @click="toggle">{{ opened ? '收起进度' : '查看执行进度' }}</button>
    </div>
    <div v-if="opened" class="mt-4" aria-live="polite">
      <p v-if="loading" class="py-5 text-sm text-gray-500">正在读取关联进度…</p>
      <div v-else-if="error" role="alert" class="text-sm text-red-700">{{ error }} <button type="button" class="underline" @click="load">重试</button></div>
      <template v-else-if="data">
        <div class="mb-3 flex flex-wrap justify-between gap-2 text-xs text-gray-500"><span>需求审批：{{ data.workflow_status || '查看来源 OA' }} · 共 {{ data.total }} 项</span><router-link v-if="data.can_access_board && !sourceLine" :to="boardLink()" class="text-blue-700">在物料看板查看整张 OA →</router-link></div>
        <details v-for="line in data.items" :key="line.source_line" class="mb-3 rounded border border-gray-200" :open="!!sourceLine">
          <summary class="cursor-pointer bg-gray-50 px-4 py-3 text-sm"><span class="font-semibold">{{ line.item_name }}</span><span class="ml-3 text-gray-500">{{ line.specification }} · 申请 {{ number(line.quantity) }} {{ line.unit }} · 已提 PR {{ number(line.pr_quantity) }} {{ line.unit }}</span><span v-if="line.unallocated_quantity > 0" class="ml-3 text-amber-700">待提 {{ number(line.unallocated_quantity) }} {{ line.unit }}</span></summary>
          <div class="space-y-3 p-4">
            <div class="flex flex-wrap justify-between gap-2 text-xs text-gray-500"><span>{{ line.material_serial || line.source_line }}</span><router-link v-if="data.can_access_board && !sourceLine" :to="boardLink(line.source_line)" class="text-blue-700">在物料看板定位此物料 →</router-link></div>
            <p v-if="!line.branches.length" class="text-sm text-gray-500">尚未建立 PR，原始需求仍保留在本 OA 下。</p>
            <article v-for="branch in line.branches" :key="branch.pr_line" class="rounded border border-gray-200 p-3">
              <div class="flex flex-wrap justify-between gap-2 text-sm"><strong>{{ branch.pr }} · {{ number(branch.quantity) }} {{ line.unit }}</strong><span>{{ branch.status }}</span></div>
              <div class="mt-2 space-y-2 text-xs text-gray-600"><div v-for="price in branch.prices" :key="price.name">核价：{{ price.name }} · {{ number(price.quantity) }} {{ line.unit }} · {{ price.status }}</div><p v-if="!branch.prices.length">尚未建立核价单</p></div>
              <div v-for="(order, index) in branch.orders" :key="order.name + ':' + index" class="mt-3 grid gap-3 border-t border-gray-200 pt-3 text-xs sm:grid-cols-2 xl:grid-cols-3">
                <div><span class="block text-gray-500">关联 PO / 状态</span>{{ order.name }} · {{ order.status }}</div>
                <div><span class="block text-gray-500">本物料到货</span>{{ number(order.received_quantity) }} / {{ number(order.quantity) }} {{ line.unit }}</div>
                <div><span class="block text-gray-500">本物料验收</span>{{ order.inspection_status }}</div>
                <div><span class="block text-gray-500">本物料合同交期</span>{{ order.delivery_date || '待确认' }}</div>
                <div><span class="block text-gray-500">关联 PO 付款状态（整单）</span>{{ order.payment_status }}</div>
              </div>
              <p v-if="!branch.orders.length" class="mt-3 text-xs text-gray-500">尚未建立 PO</p>
            </article>
          </div>
        </details>
        <p v-if="!data.items.length" class="py-4 text-sm text-gray-500">暂无关联物料。</p>
        <div v-if="page > 0 || data.has_more" class="flex items-center justify-end gap-3 text-sm"><button type="button" :disabled="page === 0" class="rounded border px-3 py-1 disabled:opacity-40" @click="changePage(-1)">上一页</button><span>第 {{ page + 1 }} 页</span><button type="button" :disabled="!data.has_more" class="rounded border px-3 py-1 disabled:opacity-40" @click="changePage(1)">下一页</button></div>
      </template>
    </div>
  </section>
</template>
