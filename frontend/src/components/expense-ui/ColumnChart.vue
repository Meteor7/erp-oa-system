<script setup>
// 竖柱图：少量分组（例如等待天数分段），柱高按最大值缩放，柱上写数量，柱下写分组和金额。
import { computed } from 'vue';

const props = defineProps({
  columns: { type: Array, default: () => [] },
  height: { type: Number, default: 120 },
  unit: { type: String, default: '张' },
});
const peak = computed(() => Math.max(1, ...props.columns.map((column) => Number(column.value || 0))));
const bars = computed(() => props.columns.map((column) => ({
  ...column,
  px: Math.round((Number(column.value || 0) / peak.value) * props.height),
})));
</script>

<template>
  <div class="columns">
    <div class="plot" :style="{ height: height + 24 + 'px' }">
      <div v-for="bar in bars" :key="bar.label" class="col">
        <span class="n">{{ bar.value }} {{ unit }}</span>
        <i :style="{ height: Math.max(bar.value ? 3 : 0, bar.px) + 'px', background: bar.color }"></i>
      </div>
    </div>
    <div class="axis">
      <div v-for="bar in bars" :key="bar.label"><span>{{ bar.label }}</span><small v-if="bar.sub">{{ bar.sub }}</small></div>
    </div>
  </div>
</template>
