<script setup>
// 环形图 + 右边的图例：items 是 [{kind, label, hours}]，颜色跟请假类型走。
import { computed } from 'vue';
import { KINDS, donutArcs, totalHours } from '../../lib/attendanceCharts.js';

const props = defineProps({
  items: { type: Array, default: () => [] },
  label: { type: String, default: '' },
});

const arcs = computed(() => donutArcs(props.items));
const total = computed(() => Math.round(totalHours(props.items) * 10) / 10);
</script>

<template>
  <div class="ac-donut">
    <svg viewBox="0 0 92 92" role="img" :aria-label="label">
      <circle cx="46" cy="46" r="33" fill="none" stroke="var(--ac-soft)" stroke-width="12" />
      <circle v-for="arc in arcs" :key="arc.kind" cx="46" cy="46" r="33" fill="none" :class="'s-' + arc.kind" stroke-width="12" :stroke-dasharray="arc.dash + ' ' + arc.gap" :stroke-dashoffset="arc.offset" transform="rotate(-90 46 46)"><title>{{ KINDS[arc.kind] }} {{ arc.hours }} 小时</title></circle>
      <text x="46" y="45" text-anchor="middle" font-size="15" font-weight="700" fill="var(--ac-ink)">{{ total }}h</text>
      <text x="46" y="58" text-anchor="middle" font-size="8" fill="var(--ac-muted)">合计</text>
    </svg>
    <div class="ac-lg"><div v-for="item in items" :key="item.kind"><span class="l"><i :class="'k-' + item.kind"></i>{{ item.label }}</span><b>{{ item.hours }}h</b></div></div>
  </div>
</template>
