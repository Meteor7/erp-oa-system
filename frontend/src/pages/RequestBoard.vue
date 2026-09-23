<script setup>
// 申请看板：批了多少、还没花出去多少、哪些卡在审批上、谁在出差。采购申请在"采购申请"页签单独看。
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import '../styles/expenseUi.css';
import HBars from '../components/expense-ui/HBars.vue';
import ProcurementTab from '../components/expense-ui/ProcurementTab.vue';
import { boardRoute, requestKpis, scopeText } from '../lib/expenseBoards.js';
import { callApi, money, pillClass } from '../lib/expenseClaims.js';

const router = useRouter();
const tab = ref('main');
const data = ref({});
const loading = ref(true);
const error = ref('');
const kpis = computed(() => requestKpis(data.value));
const summary = computed(() => data.value.summary || {});

function open(row, requestType) {
  router.push({ path: boardRoute(requestType || row.request_type), query: { request: row.name } });
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
  <div class="xp">
    <div class="ph">
      <div>
        <h3>申请看板</h3>
        <div class="muted">给管理层、财务和部门主管：批了多少、还没花出去多少、哪些卡在审批上、谁在出差。</div>
      </div>
      <span class="muted">{{ scopeText(data) }}</span>
    </div>
    <div class="tabs" role="tablist">
      <button role="tab" :aria-selected="tab === 'main'" @click="tab = 'main'">购买与出差</button>
      <button role="tab" :aria-selected="tab === 'procurement'" @click="tab = 'procurement'">采购申请</button>
    </div>

    <ProcurementTab v-if="tab === 'procurement'" part="request" />
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

      <div class="panel">
        <div class="pt">
          <span>购买申请额度执行</span>
          <span class="muted">
            <span v-if="summary.stale_count" class="pill p-red">{{ summary.stale_count }} 张通过超过 {{ data.stale_days }} 天仍未付款</span>
            <template v-else>没有长期未执行的申请</template>
          </span>
        </div>
        <div class="tbl">
          <table>
            <thead><tr><th>申请</th><th>申请人</th><th>部门</th><th class="r">批准金额</th><th class="r">已付</th><th class="r">剩余</th><th style="width:150px">执行进度</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="row in data.applications || []" :key="row.name" class="row-sel" @click="open(row)">
                <td><div class="num" style="font-weight:600">{{ row.name }}</div><div class="muted">{{ row.subject }}</div></td>
                <td>{{ row.employee_name }}</td>
                <td>{{ row.department }}</td>
                <td class="r num">{{ money(row.approved_amount) }}</td>
                <td class="r num">{{ money(row.paid_amount) }}</td>
                <td class="r num">{{ money(row.remaining_amount) }}</td>
                <td>
                  <div class="bar wide"><i :style="{ width: row.progress + '%' }"></i></div>
                  <div class="muted">{{ row.progress }}%<template v-if="row.reserved_amount"> · 在途 {{ money(row.reserved_amount) }}</template></div>
                </td>
                <td>
                  <span :class="pillClass(row.status)">{{ row.status }}</span>
                  <span v-if="row.stale" class="pill p-red" style="margin-left:4px">{{ row.idle_days }} 天未执行</span>
                </td>
              </tr>
              <tr v-if="!(data.applications || []).length"><td colspan="8" class="empty">没有已通过的购买申请</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="grid g2">
        <div class="panel"><div class="pt">按部门的批准金额</div><HBars :rows="data.by_department || []" color="#3E63DD" /></div>
        <div class="panel">
          <div class="pt">固定资产申请（按类别）</div>
          <HBars :rows="data.fixed_by_category || []" color="#FF8F00" empty="没有固定资产申请" />
          <div class="muted" style="margin-top:8px">非固定资产 ¥ {{ money(data.non_fixed_amount) }}</div>
        </div>
      </div>

      <div class="panel">
        <div class="pt"><span>审批卡点</span><span class="muted">等待超过 {{ data.stuck_days }} 天标红</span></div>
        <div class="tbl">
          <table>
            <thead><tr><th>单据</th><th>类型</th><th>申请人</th><th class="r">金额</th><th>卡在</th><th>已等</th></tr></thead>
            <tbody>
              <tr v-for="row in data.pending || []" :key="row.name" class="row-sel" @click="open(row)">
                <td class="num">{{ row.name }}<div class="muted">{{ row.subject }}</div></td>
                <td>{{ row.request_type }}</td>
                <td>{{ row.employee_name }} <span class="muted">{{ row.department }}</span></td>
                <td class="r num">{{ row.amount == null ? '—' : money(row.amount) }}</td>
                <td>{{ row.current_step_label || '—' }}</td>
                <td><span v-if="row.overdue" class="pill p-red">{{ row.waited_days }} 天</span><template v-else>{{ row.waited_days }} 天</template></td>
              </tr>
              <tr v-if="!(data.pending || []).length"><td colspan="6" class="empty">没有审批中的申请</td></tr>
            </tbody>
          </table>
        </div>
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
