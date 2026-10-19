<script setup>
// 第三步：全员本月基数。改的是员工档案里的基数（下个月自动沿用）；户口决定社保要不要缴地方补充养老。
import { computed, ref } from 'vue';
import { baseStatus, kindOf, missingBaseCount, money } from '../../lib/contributionView.js';
import { displayCompany, displayDepartment } from '../../lib/displayBrand.js';

const props = defineProps({
  kind: { type: String, required: true },
  rows: { type: Array, default: () => [] },
  householdOptions: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  readonly: { type: Boolean, default: false },   // 只读（总经理、演示员工113经理）：不能改基数、户口，也不能按上月带入
});
const emit = defineEmits(['base', 'household', 'carry', 'export']);

const filter = ref('all');
const query = ref('');
const name = computed(() => kindOf(props.kind).name);
const shown = computed(() => props.rows.filter((row) => {
  if (query.value && !String(row.employee_name || '').includes(query.value.trim())) return false;
  if (filter.value === 'missing') return row.base == null || (props.kind === 'si' && row.household_classification === '待完善');
  if (filter.value === 'changed') return row.prev_base != null && row.base != null && Math.abs(row.prev_base - row.base) > 0.005;
  return true;
}));
const missing = computed(() => missingBaseCount(props.rows, props.kind));
const carryable = computed(() => props.rows.filter((row) => row.base == null && row.prev_base != null).length);
const householdChoices = (row) => (row.household && !props.householdOptions.includes(row.household) ? [row.household, ...props.householdOptions] : props.householdOptions);

function onBase(row, event) {
  const text = event.target.value.trim();
  if (text === '' || Number(text) === row.base) return;
  emit('base', { employee: row.employee, base: text });
}
function onHousehold(row, event) {
  if (event.target.value && event.target.value !== row.household) emit('household', { employee: row.employee, household: event.target.value });
}
const cell = (value) => (value == null ? '—' : money(value));
</script>

<template>
  <section class="panel">
    <div class="pt">
      <span>第三步：{{ name }}基数与金额 <span class="muted">全员 {{ rows.length }} 人 · 缺基数{{ kind === 'si' ? '或户口' : '' }} {{ missing }} 人</span></span>
      <span v-if="!readonly" class="cw-chips">
        <button type="button" class="btn sm" :disabled="!carryable || busy" @click="emit('carry')">缺基数的按上月带入{{ carryable ? `（${carryable} 人）` : '' }}</button>
      </span>
    </div>
    <div v-if="readonly" class="muted">只读查看：基数和户口由人事维护。</div>
    <div v-else class="muted">直接改数字，改完当场重算金额，并写入员工档案（下个月自动沿用）。缺基数的格子标红，必须填完才能确认生效。{{ kind === 'si' ? '户口决定要不要缴地方补充养老，没填户口无法复算。' : '' }}</div>
    <div class="cw-foot">
      <span class="cw-seg" role="group" aria-label="筛选">
        <button type="button" :aria-pressed="filter === 'all'" @click="filter = 'all'">全部</button>
        <button type="button" :aria-pressed="filter === 'missing'" @click="filter = 'missing'">缺基数{{ kind === 'si' ? '/户口' : '' }} {{ missing }}</button>
        <button type="button" :aria-pressed="filter === 'changed'" @click="filter = 'changed'">较上月有变化</button>
      </span>
      <input v-model="query" class="cell" style="max-width:200px" placeholder="按姓名查找" aria-label="按姓名查找">
    </div>
    <div class="tbl">
      <table>
        <thead><tr><th>员工</th><th v-if="kind === 'si'">户口</th><th class="r">上月基数</th><th class="r">本月{{ name }}基数</th><th class="r">个人承担</th><th class="r">单位承担</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-if="loading && !rows.length"><td :colspan="kind === 'si' ? 7 : 6" class="empty">正在加载…</td></tr>
          <tr v-for="row in shown" :key="row.employee">
            <td><span class="cw-avatar">{{ String(row.employee_name || '').slice(-2) }}</span><b>{{ row.employee_name }}</b><div class="cw-sub">{{ displayCompany(row.company) }} · {{ displayDepartment(row.department) }}</div></td>
            <td v-if="kind === 'si'">
              <select class="cell-hk" :class="{ miss: row.household_classification === '待完善' }" :value="row.household || ''" :aria-label="`${row.employee_name} 户口`" :disabled="busy || readonly" @change="onHousehold(row, $event)">
                <option value="" disabled>未维护</option>
                <option v-for="option in householdChoices(row)" :key="option" :value="option">{{ option }}</option>
              </select>
            </td>
            <td class="r num">{{ cell(row.prev_base) }}</td>
            <td class="r"><input class="cell-base" :class="{ miss: row.base == null, chg: row.base != null && row.prev_base != null && Math.abs(row.prev_base - row.base) > 0.005 }" inputmode="decimal" :value="row.base ?? ''" placeholder="填写" :aria-label="`${row.employee_name} ${name}基数`" :disabled="busy || readonly" @change="onBase(row, $event)"></td>
            <td class="r num">{{ cell(row.employee_amount) }}</td>
            <td class="r num">{{ cell(row.company_amount) }}</td>
            <td><span :class="['pill', baseStatus(row, kind).tone]">{{ baseStatus(row, kind).text }}</span></td>
          </tr>
          <tr v-if="!loading && !shown.length"><td :colspan="kind === 'si' ? 7 : 6" class="empty">没有符合的员工</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
