<script setup>
// 横条图：标签 + 金额 + 按最大值缩放的条。
import { computed } from 'vue';
import { hbarRows } from '../../lib/expenseBoards.js';
import { money } from '../../lib/expenseClaims.js';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  color: { type: String, default: '#FF8F00' },
  empty: { type: String, default: '暂无数据' },
});
const bars = computed(() => hbarRows(props.rows));
</script>

<template>
  <div v-if="bars.length" class="hbars">
    <div v-for="bar in bars" :key="bar.label">
      <div class="top"><span>{{ bar.label }}</span><span class="num">{{ money(bar.value) }}</span></div>
      <div class="track"><div class="fill" :style="{ width: bar.width + '%', background: color }"></div></div>
    </div>
  </div>
  <div v-else class="empty">{{ empty }}</div>
</template>
