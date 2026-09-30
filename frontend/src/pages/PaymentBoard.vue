<script setup>
// 付款看板：钱付出去多少、花在哪、出纳还有多少没付、谁的发票没交。采购付款在"采购付款"页签单独看。
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import '../styles/expenseUi.css';
import ColumnChart from '../components/expense-ui/ColumnChart.vue';
import DonutChart from '../components/expense-ui/DonutChart.vue';
import HBars from '../components/expense-ui/HBars.vue';
import StackedBars from '../components/expense-ui/StackedBars.vue';
import ProcurementTab from '../components/expense-ui/ProcurementTab.vue';
import { agingColumns, boardRoute, dueText, paymentKpis, scopeText } from '../lib/expenseBoards.js';
import { callApi, money, pillClass } from '../lib/expenseClaims.js';

const router = useRouter();
const tab = ref('main');
const data = ref({});
const loading = ref(true);
const error = ref('');
const kpis = computed(() => paymentKpis(data.value));
const aging = computed(() => agingColumns(data.value.cashier_queue || []));
const urgent = computed(() => (data.value.cashier_queue || []).filter((row) => row.urgency === '加急').length);

function open(row, requestType) {
  router.push({ path: boardRoute(requestType || row.request_type), query: { request: row.name } });
}

onMounted(async () => {
  try {
    data.value = await callApi('expense_board_entry.payment_board', {}, { method: 'GET' }) || {};
  } catch (exc) {
    error.value = String(exc?.message || exc);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="xp board">
    <div class="ph">
      <div>
        <h3>付款看板</h3>
        <div class="muted">钱付出去多少、花在哪、出纳还有多少没付、谁的发票没交。</div>
      </div>
      <span class="muted">{{ scopeText(data) }}</span>
    </div>
    <div class="tabs" role="tablist">
      <button role="tab" :aria-selected="tab === 'main'" @click="tab = 'main'">报销与付款</button>
      <button role="tab" :aria-selected="tab === 'procurement'" @click="tab = 'procurement'">采购付款</button>
    </div>

    <ProcurementTab v-if="tab === 'procurement'" part="payment" />
    <div v-else-if="loading" class="panel empty">正在加载看板数据…</div>
    <div v-else-if="error" class="banner err">{{ error }}</div>
    <template v-else>
      <div class="grid g4">
        <div v-for="kpi in kpis" :key="kpi.key" class="stat">
          <div class="l">{{ kpi.label }}</div>
          <div class="v num" :style="kpi.tone ? { color: kpi.tone } : null">{{ kpi.value }}</div>
          <div class="l">{{ kpi.sub }}</div>
        </div>
      </div>

      <div class="grid g75">
        <div class="panel"><div class="pt"><span>近 6 个月付出去多少</span><span class="muted">按实际付款日期</span></div><StackedBars :trend="data.trend || []" /></div>
        <div class="panel"><div class="pt"><span>本月钱花在哪</span><span class="muted">按费用科目</span></div><DonutChart :rows="data.by_account || []" center-label="本月已付" empty="本月还没有付款" /></div>
      </div>

      <div class="grid g2">
        <div class="panel"><div class="pt"><span>本月按部门</span><span class="muted">已付金额</span></div><HBars :rows="data.by_department || []" empty="本月还没有付款" /></div>
        <div class="panel">
          <div class="pt"><span>出纳待付：等了多久</span><span class="muted">{{ (data.cashier_queue || []).length }} 张<template v-if="urgent"> · 加急 {{ urgent }} 张</template></span></div>
          <ColumnChart v-if="(data.cashier_queue || []).length" :columns="aging" />
          <div v-else class="empty">出纳没有待付的单据</div>
        </div>
      </div>

      <div class="panel">
        <div class="pt"><span>出纳待办</span><span class="muted">加急优先，其次按等待时间；点一行打开单据</span></div>
        <div class="tbl">
          <table>
            <thead><tr><th>单据</th><th>类型</th><th>申请人</th><th>部门</th><th class="r">金额</th><th>等待</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="row in data.cashier_queue || []" :key="row.name" class="row-sel" @click="open(row)">
                <td class="num">{{ row.name }}<span v-if="row.urgency === '加急'" class="pill p-red" style="margin-left:4px">加急</span></td>
                <td>{{ row.request_type === '报销单' ? '报销' : '付款' }}</td>
                <td>{{ row.employee_name }}</td>
                <td>{{ row.department }}</td>
                <td class="r num">{{ money(row.amount) }}</td>
                <td :class="{ warn: row.waited_days >= 3 }">{{ row.waited_days }} 天</td>
                <td><span :class="pillClass(row.status)">{{ row.status }}</span></td>
              </tr>
              <tr v-if="!(data.cashier_queue || []).length"><td colspan="7" class="empty">没有待办</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="grid g75">
        <div class="panel">
          <div class="pt"><span>待补票</span><span class="muted">到期前 3 天开始提醒申请人，逾期每天提醒</span></div>
          <div v-for="row in data.invoice_tracking || []" :key="row.name" class="line-row row-sel" @click="open(row, '付款单')">
            <span class="num strong">{{ row.name }}</span>
            <span class="grow">{{ row.employee_name }} · {{ row.payee_name || '—' }}</span>
            <span class="num">¥ {{ money(row.amount) }}</span>
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
