<script setup>
// 看板明细：点看板上的合计类数字（费用合计、审批卡点、付款审批中、考勤天数……）进来看到的清单。
// 清单由后端 dashboard_home.get_detail 按和指标卡同一份数据算出来，条数 / 合计一定和卡片上的数字一致；每一行可以再点进真实的单据。
import { computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { createResource } from 'frappe-ui';
import { canSee } from '../lib/access';
import { boardAccess } from '../lib/expenseBoards';
import { hereAsFrom } from '../lib/navContext';
import { buildTargetTable, targetState } from '../lib/dashboardTargets';
import targetsJson from '../lib/dashboardTargetsData';
import { cellClass, detailBack, detailItem, detailParams, rowClickable } from '../lib/dashboardDetail';
import { errorText } from '../lib/dashboardView';
import '../styles/dashboardUi.css';

const route = useRoute();
const router = useRouter();
const table = buildTargetTable(targetsJson);
const access = { ...boardAccess(), canSee };

const detail = createResource({
  url: 'rayher_hr_payroll.api.dashboard_home.get_detail', method: 'GET',
  makeParams: () => detailParams(route.query), auto: Boolean(detailItem(route.query)),
});
watch(() => [route.query.item, route.query.period], () => { if (detailItem(route.query)) detail.reload(); });

const data = computed(() => detail.data || null);
const unavailable = computed(() => !detailItem(route.query) || (data.value && data.value.available === false));
const here = computed(() => hereAsFrom(route.path, { item: route.query.item, period: route.query.period }));
const resolve = (target) => targetState(target, { table, from: here.value, access });
const states = computed(() => (data.value?.rows || []).map((row) => resolve(row.target)));

function back() {
  router.push(detailBack(route.query));
}
function open(index) {
  const state = states.value[index];
  if (rowClickable(state)) router.push(state.to);
}
</script>

<template>
  <div class="db dd" :aria-busy="detail.loading ? 'true' : 'false'">
    <header class="db-head">
      <div class="db-head-main">
        <div class="db-crumb"><button type="button" class="db-link" @click="back">← 返回</button></div>
        <h1>{{ data?.title || '看板明细' }}</h1>
        <p v-if="data?.summary" class="dd-sum">{{ data.summary }}</p>
        <p v-if="data?.note" class="db-mut">{{ data.note }}</p>
      </div>
    </header>

    <div v-if="unavailable" class="db-empty db-card" role="status">这个清单暂时看不到：可能不属于你的岗位，或者地址不对。<button type="button" class="db-link" @click="back">回到看板</button></div>
    <div v-else-if="detail.error && !data" class="db-fail" role="alert">
      <p>明细加载失败：{{ errorText(detail.error) || '请稍后再试' }}</p>
      <button type="button" class="db-btn is-pri" @click="detail.reload()">重新加载</button>
    </div>
    <div v-else-if="!data" class="db-skel" role="status" aria-label="正在加载明细"><i class="db-skel-card"></i></div>
    <section v-else class="db-card dd-card">
      <div v-if="!data.rows.length" class="db-empty">现在没有符合条件的记录。</div>
      <div v-else class="dd-wrap">
        <table class="dd-table">
          <thead>
            <tr><th v-for="column in data.columns" :key="column.label" :class="cellClass(column)">{{ column.label }}</th><th class="dd-go"></th></tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in data.rows" :key="index" :class="[`is-${row.tone || 'none'}`, { 'is-link': rowClickable(states[index]) }]"
              :tabindex="rowClickable(states[index]) ? 0 : -1" @click="open(index)" @keydown.enter="open(index)">
              <td v-for="(cell, at) in row.cells" :key="at" :class="cellClass(data.columns[at])">{{ cell }}</td>
              <td class="dd-go">{{ rowClickable(states[index]) ? '查看 →' : '' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
