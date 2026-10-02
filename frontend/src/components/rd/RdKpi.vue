<script setup>
// 指标卡：名称、数值（可带单位）、一行说明。tone: '' | 'warn' | 'bad'
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '' },
  unit: { type: String, default: '' },
  sub: { type: String, default: '' },
  tone: { type: String, default: '' },
});
</script>

<template>
  <div class="kpi" :class="tone">
    <div class="k">{{ label }}</div>
    <div class="v">{{ value }}<small v-if="unit">{{ unit }}</small></div>
    <div class="s">{{ sub || ' ' }}</div>
  </div>
</template>
