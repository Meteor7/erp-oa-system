<script setup>
// 未来 14 天每天的堆叠柱：每根柱子是当天各类型的人数（请假、调休、出差、加班），休息日淡一点，轴上今天标成橙色。
import { computed } from 'vue';
import { KINDS, stackColumns } from '../../lib/attendanceCharts.js';

const props = defineProps({
  days: { type: Array, default: () => [] },
});

const columns = computed(() => stackColumns(props.days));
const legend = computed(() => {
  const found = new Set();
  props.days.forEach((day) => Object.entries(day.by_kind || {}).forEach(([kind, count]) => { if (count) found.add(kind); }));
  return Object.keys(KINDS).filter((kind) => found.has(kind));
});
</script>

<template>
  <div class="ac-stackchart">
    <div class="ac-cols"><div v-for="column in columns" :key="column.date" :class="['d', { we: column.offDay }]" :title="column.title"><i v-for="segment in column.segments" :key="segment.kind" :class="'k-' + segment.kind" :style="{ height: segment.height + 'px' }"></i></div></div>
    <div class="ac-axis"><span v-for="(column, index) in columns" :key="column.date" :class="{ t0: index === 0 }">{{ column.label }}</span></div>
    <div class="ac-gl" style="padding: 6px 0 0"><span v-for="kind in legend" :key="kind"><i :class="'k-' + kind"></i>{{ KINDS[kind] }}</span><span v-if="!legend.length">这 14 天全员在岗</span></div>
  </div>
</template>
