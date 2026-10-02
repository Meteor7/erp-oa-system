<script setup>
// 会计期间：上一月 / 本月（可直接选）/ 下一月。读写全局的 lib/period.js，四个页面共用同一个期间。
import { computed } from 'vue';
import { period, periodScope, periodYear } from '../../lib/period.js';
import RdIcon from './RdIcon.vue';

const emit = defineEmits(['change']);
const yearMode = computed(() => periodScope.value === 'year');

function shift(delta) {
  if (yearMode.value) {
    period.value = `${Number(periodYear()) + delta}-${period.value.slice(5, 7)}`;
  } else {
    const [y, m] = period.value.split('-').map(Number);
    const d = new Date(y, m - 1 + delta, 1);
    period.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  }
  emit('change', period.value);
}
function onPick(event) {
  if (!/^\d{4}-\d{2}$/.test(event.target.value)) return;
  period.value = event.target.value;
  emit('change', period.value);
}
</script>

<template>
  <div class="period">
    <button type="button" :aria-label="yearMode ? '上一年' : '上一月'" @click="shift(-1)"><RdIcon name="left" /></button>
    <b v-if="yearMode">{{ periodYear() }} 年</b>
    <input v-else type="month" :value="period" aria-label="会计期间" @change="onPick" />
    <button type="button" :aria-label="yearMode ? '下一年' : '下一月'" @click="shift(1)"><RdIcon name="right" /></button>
  </div>
</template>
