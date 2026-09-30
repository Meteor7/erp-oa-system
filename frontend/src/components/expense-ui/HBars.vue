<script setup>
// 横条图：一行一类，标签、条、金额在同一行；条按同组最大值缩放。
import { computed } from 'vue';
import { hbarRows } from '../../lib/expenseBoards.js';
import { money } from '../../lib/expenseClaims.js';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  color: { type: String, default: '#5470C6' },
  empty: { type: String, default: '暂无数据' },
  limit: { type: Number, default: 8 },
});
const bars = computed(() => hbarRows(props.rows).slice(0, props.limit));
</script>

<template>
  <div v-if="bars.length" class="hbars">
    <div v-for="bar in bars" :key="bar.label" class="hrow">
      <span class="label" :title="bar.label">{{ bar.label }}</span>
      <div class="track"><div class="fill" :style="{ width: bar.width + '%', background: color }"></div></div>
      <span class="value">¥ {{ money(bar.value) }}</span>
    </div>
  </div>
  <div v-else class="empty">{{ empty }}</div>
</template>
