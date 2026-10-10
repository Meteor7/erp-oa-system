<script setup>
// 团队日历：每人一行、未来 14 天每天一格，固定列宽。今天只把表头日期标成橙色加粗（不描边），周末格子用很浅的底色；
// 格子按请假类型上柔和的颜色，审批中的淡一点。这个组件只给部门主管（自己的部门）和人事 / 领导（点进某个部门后）用。
import { KINDS, cellClass, cellTitle } from '../../lib/attendanceCharts.js';

defineProps({
  title: { type: String, default: '团队 · 未来 14 天' },
  note: { type: String, default: '' },
  days: { type: Array, default: () => [] },
  members: { type: Array, default: () => [] },
});
</script>

<template>
  <section class="ac-panel" aria-label="团队日历">
    <div class="ac-hd"><h2>{{ title }}</h2><span class="ac-note ac-right">{{ note }}</span></div>
    <div v-if="!members.length" class="ac-empty">没有成员</div>
    <div v-else class="ac-cal">
      <table>
        <colgroup><col class="n" /><col v-for="day in days" :key="day.date" /></colgroup>
        <thead><tr><th class="n">成员</th><th v-for="(day, index) in days" :key="day.date" :class="{ t: index === 0 }">{{ day.day }}<br />{{ day.weekday }}</th></tr></thead>
        <tbody>
          <tr v-for="member in members" :key="member.id">
            <th class="n" :title="member.name">{{ member.name }}</th>
            <td v-for="(day, index) in days" :key="day.date" :class="cellClass(member.cells[index], day)" :title="cellTitle(member.name, day, member.cells[index])"></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="ac-gl">
      <span v-for="(label, kind) in KINDS" :key="kind"><i :class="'k-' + kind"></i>{{ label }}</span>
      <span>淡色 = 审批中（不计入统计）</span><span class="t0">橙色日期是今天</span>
    </div>
  </section>
</template>
