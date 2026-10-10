<script setup>
// 部门概况（人事 / 领导的首页）：每个部门一行，只有人数、趋势线、请假小时、出勤率、待审批数，没有人名；
// 点一行进入部门，才会看到那个部门的 14 天日历和近 5 天不在岗的人。
import { ratePercent, rateTone, sparklinePoints } from '../../lib/attendanceCharts.js';

defineProps({
  departments: { type: Array, default: () => [] },
});
const emit = defineEmits(['pick']);
</script>

<template>
  <section class="ac-panel" aria-label="部门概况">
    <div class="ac-hd"><h2>部门概况</h2><span class="ac-note ac-right">点一行进入部门，才会看到具体的人</span></div>
    <div v-if="!departments.length" class="ac-empty">没有部门数据</div>
    <div v-else class="ac-tblwrap">
      <table class="ac-dept">
        <thead><tr><th>部门</th><th class="r">今日请假</th><th>未来 14 天</th><th class="r">本月请假</th><th class="r">出勤率</th><th class="r">待审批</th><th></th></tr></thead>
        <tbody>
          <tr v-for="item in departments" :key="item.department" tabindex="0" role="button" :aria-label="'进入 ' + item.label" @click="emit('pick', item.department)" @keydown.enter="emit('pick', item.department)">
            <td class="name"><b>{{ item.label }}</b><span class="ac-note">{{ item.headcount }} 人</span></td>
            <td class="r"><span class="ac-off"><b>{{ item.today_off }}</b><span class="ac-mini"><i :style="{ width: (item.headcount ? item.today_off / item.headcount * 100 : 0) + '%' }"></i></span></span></td>
            <td><svg class="ac-spark" viewBox="0 0 84 24" aria-hidden="true"><polyline :points="sparklinePoints(item.trend)" fill="none" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round" /></svg></td>
            <td class="r">{{ item.month_hours }}<span class="ac-note"> h</span><div class="ac-note">人均 {{ item.per_capita }}</div></td>
            <td class="r"><span :class="['ac-tag', rateTone(item.rate)]">{{ ratePercent(item.rate) }}%</span></td>
            <td class="r"><span v-if="item.pending" class="ac-cnt">{{ item.pending }}</span><span v-else class="ac-note">—</span></td>
            <td class="ac-go">›</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
