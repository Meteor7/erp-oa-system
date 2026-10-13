<script setup>
// 付款看板：钱付出去多少、花在哪、出纳还有多少没付、谁的发票没交。采购付款在"采购付款"页签单独看。
// 2026-10 改版：指标卡可点；出纳待付款的等待分段和待办表合成一块；页签放在地址里（?tab=main|procurement）。
import { computed, nextTick, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../styles/expenseUi.css';
import '../styles/boardsUi.css';
import '../styles/navUi.css';
import DonutChart from '../components/expense-ui/DonutChart.vue';
import HBars from '../components/expense-ui/HBars.vue';
import StackedBars from '../components/expense-ui/StackedBars.vue';
import ProcurementTab from '../components/expense-ui/ProcurementTab.vue';
import { agingTiles, boardAccess, boardRoute, boardTab, bottomColumns, dueText, paymentKpis, scopeText } from '../lib/expenseBoards.js';
import { callApi, money, pillClass } from '../lib/expenseClaims.js';
import { hereAsFrom, withFrom } from '../lib/navContext.js';
import { isWaitingTooLong } from '../lib/waiting.js';

// embedded：放在审批中心的分组首页下面时不再自己写标题，只留页签。
defineProps({ embedded: { type: Boolean, default: false } });
const route = useRoute();
const router = useRouter();
const tab = computed(() => boardTab(route.query));
const data = ref({});
const loading = ref(true);
const error = ref('');
const procurement = ref(null);
// 指标卡的链接按看的人的权限处理：打不开"全部报销 / 付款"的人，那张卡不可点（不会被悄悄换成"我的"）。
const access = boardAccess();
const kpis = computed(() => paymentKpis(data.value, access));
// 打开的单据 / 列表上"返回"回到这个看板（含当前页签）。
const here = computed(() => hereAsFrom(route.path, route.query));
const queue = computed(() => data.value.cashier_queue || []);
const tiles = computed(() => agingTiles(queue.value));
const summary = computed(() => data.value.summary || {});
const urgent = computed(() => queue.value.filter((row) => row.urgency === '加急').length);
const columnCount = computed(() => bottomColumns(data.value));

function setTab(value) {
  router.replace({ path: route.path, query: { ...route.query, tab: value } });
}

function open(row, requestType) {
  router.push({ path: boardRoute(requestType || row.request_type), query: { request: row.name, from: here.value } });
}

function openKpi(kpi) {
  if (kpi.to?.path) router.push(withFrom(kpi.to, here.value));
  else if (kpi.to?.anchor) nextTick(() => document.getElementById(kpi.to.anchor)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }));
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    data.value = await callApi('expense_board_entry.payment_board', {}, { method: 'GET' }) || {};
  } catch (exc) {
    error.value = String(exc?.message || exc);
  } finally {
    loading.value = false;
  }
}

function refresh() {
  if (tab.value === 'procurement') procurement.value?.reload();
  else load();
}

onMounted(load);
</script>

<template>
  <div :class="['xp board bd', { 'bd-embedded': embedded }]">
    <div class="ph">
      <div v-if="!embedded">
        <div class="crumb">审批中心 · 看板<template v-if="scopeText(data)"> · {{ scopeText(data) }}</template></div>
        <h1 class="bd-title">付款看板</h1>
        <div class="muted">{{ tab === 'procurement' ? '采购付款单独统计，不和报销、对外付款的数字混在一起。按 PO 付款期次的真实状态统计。' : '钱付出去多少、花在哪、出纳还有多少没付、谁的发票没交。' }}</div>
      </div>
      <div class="head-actions bd-tools">
        <div class="seg" role="tablist">
          <button type="button" role="tab" :aria-selected="tab === 'main'" :aria-pressed="tab === 'main'" @click="setTab('main')">报销与付款</button>
          <button type="button" role="tab" :aria-selected="tab === 'procurement'" :aria-pressed="tab === 'procurement'" @click="setTab('procurement')">采购付款</button>
        </div>
        <button type="button" class="btn" :disabled="loading && tab === 'main'" @click="refresh">刷新</button>
      </div>
    </div>

    <ProcurementTab v-if="tab === 'procurement'" ref="procurement" part="payment" />
    <div v-else-if="loading" class="panel empty">正在加载看板数据…</div>
    <div v-else-if="error" class="banner err">{{ error }}</div>
    <template v-else>
      <div class="bd-kpis">
        <button v-for="kpi in kpis" :key="kpi.key" type="button" class="bd-kpi" :disabled="!kpi.to" :title="kpi.note || ''" @click="openKpi(kpi)">
          <span class="bd-kpi-top"><span>{{ kpi.label }}</span><em v-if="kpi.to" aria-hidden="true">›</em></span>
          <b class="bd-kpi-value" :style="kpi.tone ? { color: kpi.tone } : null">{{ kpi.value }}</b>
          <span class="bd-kpi-sub">{{ kpi.sub }}</span>
        </button>
      </div>

      <div class="grid g75">
        <div class="panel"><div class="pt"><span>近 6 个月付出去多少</span><span class="muted">按实际付款日期</span></div><StackedBars :trend="data.trend || []" /></div>
        <div class="panel"><div class="pt"><span>本月钱花在哪</span><span class="muted">按费用科目</span></div><DonutChart :rows="data.by_account || []" center-label="本月已付" empty="本月还没有付款" /></div>
      </div>

      <div id="bd-cashier" class="panel">
        <div class="pt">
          <span>出纳待付款 <span class="muted">{{ queue.length }} 张 · ¥ {{ money(summary.to_pay_amount) }}<template v-if="urgent"> · 其中加急 {{ urgent }} 张</template> · 加急优先，其次按等待时间</span></span>
          <span class="links"><router-link class="link" :to="{ path: '/approval/claim', query: { view: 'list', scope: 'todo', from: here } }">报销待办 →</router-link><router-link class="link" :to="{ path: '/approval/payment', query: { view: 'list', scope: 'todo', from: here } }">付款待办 →</router-link></span>
        </div>
        <div v-if="queue.length" class="bd-tiles">
          <div v-for="tile in tiles" :key="tile.label" class="bd-tile">
            <span class="muted">{{ tile.label }}</span>
            <span class="bd-tile-n"><b>{{ tile.count }}</b> <span class="muted">张 · {{ tile.amount }}</span></span>
            <div class="stack-bar bd-mini"><i :style="{ width: tile.width, background: tile.color }"></i></div>
          </div>
        </div>
        <div class="tbl">
          <table>
            <thead><tr><th>单据</th><th>类型</th><th>申请人</th><th>部门</th><th class="r">金额</th><th class="r">等待</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="row in queue" :key="row.name" class="row-sel" @click="open(row)">
                <td class="num">{{ row.name }}<span v-if="row.urgency === '加急'" class="pill p-red" style="margin-left:4px">加急</span></td>
                <td>{{ row.request_type === '报销单' ? '报销' : '付款' }}</td>
                <td>{{ row.employee_name }}</td>
                <td>{{ row.department }}</td>
                <td class="r num">{{ money(row.amount) }}</td>
                <td :class="['r', { warn: isWaitingTooLong(row.waited_days) }]">{{ row.waited_days }} 天</td>
                <td><span :class="pillClass(row.status)">{{ row.status }}</span></td>
              </tr>
              <tr v-if="!queue.length"><td colspan="7" class="empty">出纳没有待付的单据</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="bd-bottom" :class="'bd-cols-' + columnCount">
        <div class="panel"><div class="pt"><span>本月按部门</span><span class="muted">已付金额</span></div><HBars :rows="data.by_department || []" empty="本月还没有付款" /></div>
        <div id="bd-invoices" class="panel">
          <div class="pt"><span>待补票</span><span class="muted">到期前 3 天开始提醒，逾期每天提醒</span></div>
          <div v-for="row in data.invoice_tracking || []" :key="row.name" class="bd-owe row-sel" @click="open(row, '付款单')">
            <span class="num strong">{{ row.name }}</span>
            <span class="grow">{{ row.employee_name }} · {{ row.payee_name || '—' }}</span>
            <span class="num strong">¥ {{ money(row.amount) }}</span>
            <span :class="'pill ' + dueText(row).tone">{{ dueText(row).text }}</span>
            <span class="muted">提醒 {{ row.reminders }} 次</span>
          </div>
          <div v-if="!(data.invoice_tracking || []).length" class="empty">没有待补票的付款单</div>
        </div>
        <div v-if="data.scope !== 'department'" class="panel">
          <div class="pt"><span>今年付给谁最多</span><span class="muted">收款单位 Top 5</span></div>
          <HBars :rows="data.top_payees || []" color="#8C96A8" :limit="5" empty="今年还没有对外付款" />
        </div>
      </div>
    </template>
  </div>
</template>
