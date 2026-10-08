<script setup>
// 看板里的"采购"页签：采购申请 / 采购付款单独统计，不和购买、报销、付款的数字混在一起。
// 采购付款按 PO 付款期次的真实状态统计（po_work：期次状态、各 PO 的到货 / 验收 / 已付进度）；
// 服务端没有 po_work 时退回旧口径，新的两块面板隐藏。
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../../styles/boardsUi.css';
import '../../styles/navUi.css';
import HBars from './HBars.vue';
import {
  boardRoute, hasPoWork, paymentFulfilment, poProgressRows, poStatusCount, poStatusRows, procurementKpis,
} from '../../lib/expenseBoards.js';
import { callApi, money, pillClass } from '../../lib/expenseClaims.js';
import { hereAsFrom, withFrom } from '../../lib/navContext.js';

const props = defineProps({ part: { type: String, default: 'request' } });
const router = useRouter();
const route = useRoute();
// 打开的单据 / 列表上"返回"回到这个看板（含采购页签）。
const here = () => hereAsFrom(route.path, route.query);
const data = ref({});
const loading = ref(true);
const error = ref('');
const kpis = computed(() => procurementKpis(data.value, props.part));
const isRequest = computed(() => props.part === 'request');
const rows = computed(() => (isRequest.value ? data.value.applications : data.value.payments) || []);
const bars = computed(() => (isRequest.value ? data.value.applications_by_status : data.value.payments_by_status) || []);
const poWork = computed(() => (hasPoWork(data.value) ? data.value.po_work : null));
const statusRows = computed(() => poStatusRows(poWork.value || {}));
const statusTotal = computed(() => poStatusCount(poWork.value || {}));
const poRows = computed(() => poProgressRows(poWork.value || {}));
const paymentRows = computed(() => rows.value.map((row) => ({ ...row, fulfil: paymentFulfilment(row, poWork.value || {}) })));

function open(row) {
  router.push({ path: boardRoute(row.request_type), query: { request: row.name, from: here() } });
}
function openPo(row) {
  router.push({ path: '/approval/procurement-payment', query: { po: row.po, from: here() } });
}
function openKpi(kpi) {
  if (kpi.to?.path) router.push(withFrom(kpi.to, here()));
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    data.value = await callApi('expense_board_entry.procurement_board', {}, { method: 'GET' }) || {};
  } catch (exc) {
    error.value = String(exc?.message || exc);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
defineExpose({ reload: load });
</script>

<template>
  <div v-if="loading" class="panel empty">正在加载采购数据…</div>
  <div v-else-if="error" class="banner err">{{ error }}</div>
  <template v-else>
    <div class="bd-kpis" :class="{ 'bd-kpis-3': kpis.length === 3, 'bd-kpis-2': kpis.length === 2 }">
      <button v-for="kpi in kpis" :key="kpi.key" type="button" class="bd-kpi" @click="openKpi(kpi)">
        <span class="bd-kpi-top"><span>{{ kpi.label }}</span><em aria-hidden="true">›</em></span>
        <b class="bd-kpi-value" :style="kpi.tone ? { color: kpi.tone } : null">{{ kpi.value }}</b>
        <span class="bd-kpi-sub">{{ kpi.sub }}</span>
      </button>
    </div>

    <!-- 采购付款：按 PO 付款期次的真实状态 -->
    <div v-if="!isRequest && poWork" class="grid g57 bd-po-grid">
      <div class="panel">
        <div class="pt"><span>付款期次按状态</span><span class="muted">金额 · 共 {{ statusTotal }} 期</span></div>
        <HBars :rows="statusRows" color="#5470C6" empty="还没有 PO 付款期次" />
        <div class="muted bd-note">"待到货资料"是尾款在等整张 PO 到货；它不是出了问题，只是前面的条件没到。</div>
      </div>
      <div class="panel">
        <div class="pt"><span>各 PO 进度</span><span class="muted">点一行进入采购付款</span></div>
        <div class="tbl narrow bd-po">
          <table>
            <thead><tr><th>PO</th><th class="bd-sup">供应商</th><th>到货</th><th>验收通过</th><th>已付 / 总额</th><th>PO 状态</th></tr></thead>
            <tbody>
              <tr v-for="row in poRows" :key="row.po" class="row-sel" @click="openPo(row)">
                <td class="num strong">{{ row.po }}</td>
                <td class="bd-sup">{{ row.supplier }}</td>
                <td><span :class="['pill', row.receivedDone ? 'p-jade' : 'p-gray']">{{ row.received }}</span></td>
                <td><span :class="['pill', row.passedDone ? 'p-jade' : 'p-gray']">{{ row.passed }}</span></td>
                <td class="bd-paid"><span class="num">{{ row.paidText }}</span><div class="stack-bar bd-mini"><i :style="{ width: row.paidWidth, background: '#7FA38E' }"></i></div></td>
                <td><span :class="['pill', row.tone]">{{ row.status || '—' }}</span></td>
              </tr>
              <tr v-if="!poRows.length"><td colspan="6" class="empty">还没有 PO</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
    <div v-else-if="isRequest || !poWork" class="panel">
      <div class="pt">{{ isRequest ? '采购申请按业务状态' : '采购付款按业务状态' }}</div>
      <HBars :rows="bars" color="#5470C6" />
    </div>

    <div class="panel flush">
      <div class="pt bd-pad"><span>{{ isRequest ? '采购申请' : '采购付款单' }}</span><span class="muted">点一行打开审批单 · 最多 200 张</span></div>
      <div class="tbl">
        <table>
          <thead>
            <tr>
              <th>单据</th><th>申请人</th><th class="r">金额</th><th>审批</th><th>业务状态</th>
              <template v-if="!isRequest"><th>到货</th><th>验收</th></template>
            </tr>
          </thead>
          <tbody>
            <template v-if="isRequest">
              <tr v-for="row in rows" :key="row.name" class="row-sel" @click="open(row)">
                <td><div class="num" style="font-weight:600">{{ row.name }}</div><div class="muted">{{ row.subject }}</div></td>
                <td>{{ row.employee_name }} <span class="muted">{{ row.department }}</span></td>
                <td class="r num">{{ money(row.amount) }}</td>
                <td><span :class="pillClass(row.workflow_status)">{{ row.workflow_status }}</span></td>
                <td>{{ row.business_status || '—' }}</td>
              </tr>
            </template>
            <template v-else>
              <tr v-for="row in paymentRows" :key="row.name" class="row-sel" @click="open(row)">
                <td><div class="num" style="font-weight:600">{{ row.name }}</div><div class="muted">{{ row.source_purchase_order ? row.source_purchase_order + ' · ' : '' }}{{ row.subject }}</div></td>
                <td>{{ row.employee_name }} <span class="muted">{{ row.department }}</span></td>
                <td class="r num">{{ money(row.amount) }}</td>
                <td><span :class="pillClass(row.workflow_status)">{{ row.workflow_status }}</span><div v-if="row.current_step_label" class="muted">{{ row.current_step_label }}</div></td>
                <td>{{ row.business_status || '—' }}</td>
                <td><span :class="['pill', row.fulfil.arrival.tone]">{{ row.fulfil.arrival.text }}</span></td>
                <td><span :class="['pill', row.fulfil.inspection.tone]">{{ row.fulfil.inspection.text }}</span></td>
              </tr>
            </template>
            <tr v-if="!rows.length"><td :colspan="isRequest ? 5 : 7" class="empty">没有{{ isRequest ? '采购申请' : '采购付款' }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </template>
</template>
