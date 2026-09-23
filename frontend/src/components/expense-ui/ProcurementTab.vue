<script setup>
// 看板里的"采购"页签：采购申请 / 采购付款单独统计，不和购买、报销、付款的数字混在一起。
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import HBars from './HBars.vue';
import { boardRoute, procurementKpis } from '../../lib/expenseBoards.js';
import { callApi, money, pillClass } from '../../lib/expenseClaims.js';

const props = defineProps({ part: { type: String, default: 'request' } });
const router = useRouter();
const data = ref({});
const loading = ref(true);
const error = ref('');
const kpis = computed(() => procurementKpis(data.value, props.part));
const rows = computed(() => (props.part === 'request' ? data.value.applications : data.value.payments) || []);
const bars = computed(() => (props.part === 'request' ? data.value.applications_by_status : data.value.payments_by_status) || []);

function open(row) {
  router.push({ path: boardRoute(row.request_type), query: { request: row.name } });
}

onMounted(async () => {
  try {
    data.value = await callApi('expense_board_entry.procurement_board', {}, { method: 'GET' }) || {};
  } catch (exc) {
    error.value = String(exc?.message || exc);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div v-if="loading" class="panel empty">正在加载采购数据…</div>
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
      <div class="pt">{{ part === 'request' ? '采购申请按业务状态' : '采购付款按业务状态' }}</div>
      <HBars :rows="bars" color="#1FA58C" />
    </div>
    <div class="panel flush">
      <div class="tbl">
        <table>
          <thead>
            <tr>
              <th>单据</th><th>申请人</th><th class="r">金额</th><th>审批</th><th>业务状态</th>
              <template v-if="part === 'payment'"><th>到货</th><th>验收</th><th>预付款核销</th></template>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.name" class="row-sel" @click="open(row)">
              <td><div class="num" style="font-weight:600">{{ row.name }}</div><div class="muted">{{ row.subject }}</div></td>
              <td>{{ row.employee_name }} <span class="muted">{{ row.department }}</span></td>
              <td class="r num">{{ money(row.amount) }}</td>
              <td><span :class="pillClass(row.workflow_status)">{{ row.workflow_status }}</span></td>
              <td>{{ row.business_status || '—' }}</td>
              <template v-if="part === 'payment'">
                <td>{{ row.arrival_status || '—' }}</td>
                <td>{{ row.inspection_status || '—' }}</td>
                <td>{{ row.prepayment_writeoff_status || '—' }}</td>
              </template>
            </tr>
            <tr v-if="!rows.length"><td :colspan="part === 'payment' ? 8 : 5" class="empty">没有{{ part === 'request' ? '采购申请' : '采购付款' }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </template>
</template>
