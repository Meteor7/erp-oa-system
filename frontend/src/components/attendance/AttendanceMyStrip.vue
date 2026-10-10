<script setup>
// 员工首页右边：我未来 14 天。只显示自己的安排，不显示任何同事。
import { KINDS, stripTitle } from '../../lib/attendanceCharts.js';

defineProps({
  strip: { type: Array, default: () => [] },
});
</script>

<template>
  <section class="ac-panel" aria-label="我未来 14 天">
    <div class="ac-hd"><h2>我未来 14 天</h2><span class="ac-note ac-right">只显示你自己的安排</span></div>
    <div class="ac-strip">
      <div v-for="(day, index) in strip" :key="day.date" :class="{ we: day.off_day, t0: index === 0 }">
        {{ day.day }}<br />{{ day.weekday }}<i :class="[day.kind ? 'k-' + day.kind : '', { pend: day.pending }]" :title="stripTitle(day)"></i>
      </div>
    </div>
    <div class="ac-gl">
      <span v-for="(label, kind) in KINDS" :key="kind"><i :class="'k-' + kind"></i>{{ label }}</span>
      <span>淡色 = 审批中</span><span class="t0">橙色日期是今天</span>
    </div>
  </section>
</template>
