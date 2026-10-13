<script setup>
// 物料执行进度：按原始物料跟踪 PR → 价格审批 → PO → 到货 / 验收；付款显示关联 PO 的整体状态。
// 申请人只看数量和状态；供应商、单价、金额只给能看价格 / PO 的角色（采购、PMC、副总、财务等），其中 PMC、生产主管不看金额。
// 属性和事件保持不变（request / sourceLine / expanded），2026-09-30 只改了样式。
import { computed, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import '../styles/expenseUi.css';
import '../styles/procurementUi.css';
import { quantityText } from '../lib/procurementView.js';
import { amountText } from '../lib/priceView.js';
import { canSeeProcurementPO, canSeeProcurementPrice } from '../lib/access.js';
import { loadPurchaseOrders } from './procurement/procData.js';

const props = defineProps({ request: { type: String, required: true }, sourceLine: { type: String, default: '' }, expanded: { type: Boolean, default: false } });
const opened = ref(props.expanded);
const data = ref(null);
const loading = ref(false);
const error = ref('');
const page = ref(0);
const orders = ref({});
let version = 0;
const loader = createResource({ url: 'rayher_hr_payroll.api.material_execution.get_progress', method: 'GET' });
const insider = computed(() => canSeeProcurementPrice() || canSeeProcurementPO());

async function loadOrders() {
  if (!insider.value) return;
  const rows = await loadPurchaseOrders();
  orders.value = Object.fromEntries(rows.map((po) => [po.name, po]));
}

async function load() {
  const current = ++version;
  if (!opened.value || !props.request) return;
  loading.value = true; error.value = ''; data.value = null;
  try {
    const result = await loader.fetch({ request: props.request, ...(props.sourceLine ? { source_line: props.sourceLine } : {}), limit: 20, offset: page.value * 20 });
    if (current === version) {
      data.value = result;
      loadOrders();
    }
  } catch (err) { if (current === version) error.value = err?.messages?.[0] || err?.message || '物料执行进度加载失败'; }
  finally { if (current === version) loading.value = false; }
}
function toggle() { opened.value = !opened.value; if (opened.value) load(); }
function changePage(delta) { page.value += delta; load(); }
watch(() => [props.request, props.sourceLine], () => { ++version; data.value = null; error.value = ''; page.value = 0; loading.value = false; if (opened.value) load(); }, { immediate: true });
const boardLink = (line) => ({ path: '/approval/material-progress', query: { request: props.request, source_line: line || undefined } });
const number = quantityText;

// 这一项物料在某张 PO 里的供应商、单价、本申请金额（一张 PO 也可能同时包含别的申请的物料）。
// PMC、生产主管看不到金额（PO 上带 amounts_hidden）：单价、金额是 null，显示“—”，不显示成 ¥ 0.00。
function priceOf(order, line) {
  const po = orders.value[order.name];
  if (!po) return null;
  if (po.amounts_hidden) return { supplier: po.supplier || '—', unit: null, amount: null, hidden: true };
  const rows = (po.lines || []).filter((item) => item.source_line === line.source_line);
  const amount = rows.reduce((sum, item) => sum + Number(item.amount || 0), 0);
  return { supplier: po.supplier || '—', unit: rows[0] ? Number(rows[0].unit_price || 0) : 0, amount, hidden: false };
}
const cash = (price, value) => amountText(value, price.hidden);
const amountsHidden = computed(() => Object.values(orders.value).some((po) => po.amounts_hidden));
</script>

<template>
  <section class="xp pr-exec">
    <div class="pt">
      <span>执行明细 <span class="muted">每项物料：申请 → PR → 价格审批 → PO，数量和状态</span></span>
      <span class="row-actions">
        <span v-if="insider" class="tag">{{ amountsHidden ? '含供应商（金额不对你显示）' : '含供应商和金额（仅采购 / 副总 / 财务可见）' }}</span>
        <button type="button" class="btn sm" :aria-expanded="opened" @click="toggle">{{ opened ? '收起进度' : '查看执行进度' }}</button>
      </span>
    </div>
    <div v-if="opened" aria-live="polite">
      <p v-if="loading" class="muted">正在读取关联进度…</p>
      <div v-else-if="error" role="alert" class="err">{{ error }} <button type="button" class="link" @click="load">重试</button></div>
      <template v-else-if="data">
        <div class="split muted pr-exec-top">
          <span>需求审批：{{ data.workflow_status || '查看来源申请' }} · 共 {{ data.total }} 项</span>
          <router-link v-if="data.can_access_board && !sourceLine" :to="boardLink()" class="link">在物料看板查看整张申请 →</router-link>
        </div>
        <div v-for="line in data.items" :key="line.source_line" class="pr-exec-line">
          <div class="pr-exec-head">
            <b>{{ line.item_name }}</b>
            <span class="muted">{{ line.specification }}</span>
            <span class="pr-exec-sum">申请 {{ number(line.quantity) }} {{ line.unit }} · 已提 PR {{ number(line.pr_quantity) }} {{ line.unit }}<template v-if="line.unallocated_quantity > 0"> · <span class="warn">待提 {{ number(line.unallocated_quantity) }} {{ line.unit }}</span></template></span>
          </div>
          <div class="split muted pr-exec-sub">
            <span class="num">{{ line.material_serial || line.source_line }}</span>
            <router-link v-if="data.can_access_board && !sourceLine" :to="boardLink(line.source_line)" class="link">在物料看板定位此物料 →</router-link>
          </div>
          <p v-if="!line.branches.length" class="muted pr-exec-empty">尚未建立 PR，原始需求仍保留在本申请下。</p>
          <div v-for="branch in line.branches" :key="branch.pr_line" class="pr-branch">
            <div class="pr-branch-top">
              <div><span class="k">PR</span><b>{{ branch.pr }}</b><span class="muted">{{ number(branch.quantity) }} {{ line.unit }} · {{ branch.status }}</span></div>
              <div>
                <span class="k">价格审批</span>
                <template v-if="branch.prices.length"><div v-for="price in branch.prices" :key="price.name"><b>{{ price.name }}</b><span class="muted">{{ number(price.quantity) }} {{ line.unit }} · {{ price.status }}</span></div></template>
                <span v-else class="muted">尚未建立核价单</span>
              </div>
            </div>
            <div v-for="(order, index) in branch.orders" :key="order.name + ':' + index" class="pr-order">
              <div><span class="k">PO</span><b>{{ order.name }}</b><span class="muted">{{ order.status }}</span></div>
              <div><span class="k">到货</span>{{ number(order.received_quantity) }} / {{ number(order.quantity) }} {{ line.unit }}</div>
              <div><span class="k">验收</span>{{ order.inspection_status }}</div>
              <div><span class="k">合同交期</span>{{ order.delivery_date || '待确认' }}</div>
              <div><span class="k">所在 PO 付款（整单）</span>{{ order.payment_status }}</div>
              <template v-if="insider && priceOf(order, line)">
                <div><span class="k">供应商</span>{{ priceOf(order, line).supplier }}</div>
                <div><span class="k">单价 / 本申请金额</span><b>{{ cash(priceOf(order, line), priceOf(order, line).unit) }} / {{ cash(priceOf(order, line), priceOf(order, line).amount) }}</b></div>
              </template>
            </div>
            <p v-if="!branch.orders.length" class="muted pr-exec-empty">尚未建立 PO</p>
          </div>
        </div>
        <p v-if="!data.items.length" class="muted">暂无关联物料。</p>
        <div v-if="page > 0 || data.has_more" class="row-actions pr-exec-pages">
          <button type="button" class="btn sm" :disabled="page === 0" @click="changePage(-1)">上一页</button>
          <span class="muted">第 {{ page + 1 }} 页</span>
          <button type="button" class="btn sm" :disabled="!data.has_more" @click="changePage(1)">下一页</button>
        </div>
        <div class="muted pr-exec-note">一项物料如果分了几次提 PR，会并列显示几条分支；一张 PO 也可能同时包含别的申请的物料，所以"所在 PO 付款"是整张 PO 的进度。</div>
      </template>
    </div>
  </section>
</template>
