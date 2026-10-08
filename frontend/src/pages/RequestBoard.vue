<script setup>
// 申请看板：本月申请了什么、走到哪一步、批下来的额度用了多少、哪些卡在审批上、谁在出差。
// 采购申请在"采购申请"页签单独看。页签放在地址里（?tab=main|procurement）；指标卡可点。
import { computed, nextTick, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../styles/expenseUi.css';
import '../styles/boardsUi.css';
import '../styles/navUi.css';
import DonutChart from '../components/expense-ui/DonutChart.vue';
import HBars from '../components/expense-ui/HBars.vue';
import ProcurementTab from '../components/expense-ui/ProcurementTab.vue';
import { boardAccess, boardRoute, boardTab, budgetBars, flowBars, requestKpis, scopeText, waitBars } from '../lib/expenseBoards.js';
import { callApi, money, pillClass } from '../lib/expenseClaims.js';
import { hereAsFrom, withFrom } from '../lib/navContext.js';

const route = useRoute();
const router = useRouter();
const tab = computed(() => boardTab(route.query));
const data = ref({});
const loading = ref(true);
const error = ref('');
const showAllBudgets = ref(false);
// 指标卡的链接按看的人的权限处理：打不开"全部出差申请"的人，那张卡不可点（不会被悄悄换成"我的"）。
const access = boardAccess();
const kpis = computed(() => requestKpis(data.value, access));
const summary = computed(() => data.value.summary || {});
const flow = computed(() => flowBars(data.value.month_flow || []));
const budgets = computed(() => budgetBars(data.value.applications || []));
const shownBudgets = computed(() => (showAllBudgets.value ? budgets.value : budgets.value.slice(0, 6)));
const stuck = computed(() => waitBars(data.value.pending || [], data.value.stuck_days));
const assetRows = computed(() => [
  ...(data.value.fixed_by_category || []).map(([label, value]) => [`固定资产 · ${label}`, value]),
  ...(Number(data.value.non_fixed_amount || 0) ? [['非固定资产', data.value.non_fixed_amount]] : []),
]);

function setTab(value) {
  router.replace({ path: route.path, query: { ...route.query, tab: value } });
}

// 带上来源：打开的单据 / 列表上"返回"回到这个看板（含当前页签）。
function open(row, requestType) {
  router.push({ path: boardRoute(requestType || row.request_type), query: { request: row.name, from: hereAsFrom(route.path, route.query) } });
}

function openKpi(kpi) {
  if (kpi.to?.path) router.push(withFrom(kpi.to, hereAsFrom(route.path, route.query)));
  else if (kpi.to?.anchor) nextTick(() => document.getElementById(kpi.to.anchor)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }));
}

onMounted(async () => {
  try {
    data.value = await callApi('expense_board_entry.request_board', {}, { method: 'GET' }) || {};
  } catch (exc) {
    error.value = String(exc?.message || exc);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="xp board bd">
    <div class="ph">
      <div>
        <div class="crumb">审批中心 · 看板<template v-if="scopeText(data)"> · {{ scopeText(data) }}</template></div>
        <h1 class="bd-title">申请看板</h1>
        <div class="muted">本月申请了什么、走到哪一步、批下来的额度用了多少、哪些卡在审批上。</div>
      </div>
      <div class="head-actions bd-tools">
        <div class="seg" role="tablist">
          <button type="button" role="tab" :aria-selected="tab === 'main'" :aria-pressed="tab === 'main'" @click="setTab('main')">购买与出差</button>
          <button type="button" role="tab" :aria-selected="tab === 'procurement'" :aria-pressed="tab === 'procurement'" @click="setTab('procurement')">采购申请</button>
        </div>
      </div>
    </div>

    <ProcurementTab v-if="tab === 'procurement'" part="request" />
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

      <div class="grid g57">
        <div class="panel"><div class="pt"><span>本月都申请了什么</span><span class="muted">按张数</span></div><DonutChart :rows="data.month_mix || []" center-label="本月申请" format="count" empty="本月还没有申请" /></div>
        <div class="panel">
          <div class="pt"><span>申请走到哪一步了</span><span class="muted">本月提交的，不含驳回和撤回</span></div>
          <div v-if="flow.length && flow[0].count" class="flow">
            <div v-for="step in flow" :key="step.key" class="flow-row">
              <span class="label">{{ step.label }}</span>
              <div class="track"><div class="fill" :style="{ width: step.width, background: step.color }"></div></div>
              <span class="value"><b>{{ step.count }} 张</b><span v-if="step.amount" class="muted"> ¥ {{ money(step.amount) }}</span></span>
            </div>
          </div>
          <div v-else class="empty">本月还没有申请</div>
        </div>
      </div>

      <div id="bd-budget" class="panel">
        <div class="pt">
          <span>批下来的额度用了多少</span>
          <span class="muted">
            <span v-if="summary.stale_count" class="pill p-red">{{ summary.stale_count }} 张通过超过 {{ data.stale_days }} 天仍未付款</span>
            <template v-else>蓝 = 已付，浅蓝 = 在途，灰 = 还没用</template>
          </span>
        </div>
        <div v-for="row in shownBudgets" :key="row.name" class="budget-row row-sel" @click="open(row)">
          <div class="who"><span class="num strong">{{ row.name }}</span><span class="muted">{{ row.employee_name }} · {{ row.subject }}</span></div>
          <div class="track"><div class="paid" :style="{ width: row.paidWidth }"></div><div class="reserved" :style="{ width: row.reservedWidth }"></div></div>
          <span class="num">¥ {{ money(row.paid_amount + row.reserved_amount) }} / {{ money(row.approved_amount) }}</span>
          <span><span :class="pillClass(row.status)">{{ row.status }}</span><span v-if="row.stale" class="pill p-red" style="margin-left:4px">{{ row.idle_days }} 天未执行</span></span>
        </div>
        <div v-if="!budgets.length" class="empty">没有已通过的购买申请</div>
        <button v-if="budgets.length > 6" type="button" class="btn sm" style="margin-top:8px" @click="showAllBudgets = !showAllBudgets">{{ showAllBudgets ? '收起' : `显示全部 ${budgets.length} 张` }}</button>
      </div>

      <div class="grid g2">
        <div class="panel"><div class="pt"><span>按部门的批准金额</span></div><HBars :rows="data.by_department || []" empty="没有已批准的购买申请" /></div>
        <div class="panel"><div class="pt"><span>批准的钱买了什么</span><span class="muted">固定资产按类别</span></div><DonutChart :rows="assetRows" center-label="已批准" empty="没有已批准的购买申请" /></div>
      </div>

      <div id="bd-stuck" class="panel">
        <div class="pt"><span>卡住的申请</span><span class="muted">等待超过 {{ data.stuck_days }} 天的标出来，按等待时间排</span></div>
        <div v-for="row in stuck" :key="row.name" class="wait-row row-sel" @click="open(row)">
          <span class="num strong">{{ row.name }}</span>
          <span class="grow">{{ row.subject }} <span class="muted">{{ row.request_type }} · {{ row.employee_name }}</span></span>
          <span class="muted">卡在：{{ row.current_step_label || '—' }}</span>
          <div class="track"><div class="fill" :style="{ width: row.width, background: row.overdue ? '#D98C4A' : '#C3CAD6' }"></div></div>
          <span :class="['days', { warn: row.overdue }]">{{ row.waited_days }} 天</span>
        </div>
        <div v-if="!stuck.length" class="empty">没有审批中的申请</div>
      </div>

      <div class="panel">
        <div class="pt"><span>出差</span><span class="muted">已报销、付款金额来自关联的单据</span></div>
        <div class="tbl">
          <table>
            <thead><tr><th>出差申请</th><th>出差人</th><th>地点</th><th>日期</th><th>状态</th><th class="r">已报销/付款</th></tr></thead>
            <tbody>
              <tr v-for="row in data.trips || []" :key="row.name" class="row-sel" @click="open(row, '出差申请')">
                <td class="num">{{ row.name }}<div class="muted">{{ row.subject }}</div></td>
                <td>{{ row.employee_name }} <span class="muted">{{ row.department }}</span></td>
                <td>{{ row.travel_destination }}</td>
                <td class="num">{{ row.travel_start_date }} ~ {{ row.travel_end_date }}</td>
                <td><span :class="pillClass(row.status)">{{ row.status }}</span></td>
                <td class="r num">{{ money(row.claimed_amount) }}</td>
              </tr>
              <tr v-if="!(data.trips || []).length"><td colspan="6" class="empty">最近没有出差</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
