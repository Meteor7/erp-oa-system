<script setup>
// 环形图：按金额或张数的占比，最多显示 5 类，其余合并为"其他"。
import { computed } from 'vue';
import { donutSegments, shortMoney } from '../../lib/expenseBoards.js';
import { money } from '../../lib/expenseClaims.js';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  centerLabel: { type: String, default: '合计' },
  format: { type: String, default: 'money' },
  empty: { type: String, default: '暂无数据' },
  max: { type: Number, default: 5 },
});
const chart = computed(() => donutSegments(props.rows, props.max));
const value = (amount) => (props.format === 'count' ? `${amount} 张` : `¥ ${money(amount)}`);
const center = computed(() => (props.format === 'count' ? String(chart.value.total) : `¥ ${shortMoney(chart.value.total)}`));
</script>

<template>
  <div v-if="chart.total > 0" class="donut">
    <div class="ring" :style="{ background: chart.gradient }" role="img" :aria-label="centerLabel + ' ' + center">
      <div class="hole"><span>{{ centerLabel }}</span><b>{{ center }}</b></div>
    </div>
    <div class="legend-list">
      <div v-for="item in chart.segments" :key="item.label" class="row">
        <i :style="{ background: item.color }"></i>
        <span class="label">{{ item.label }}</span>
        <span class="share">{{ item.share }}</span>
        <b>{{ value(item.value) }}</b>
      </div>
    </div>
  </div>
  <div v-else class="empty">{{ empty }}</div>
</template>
