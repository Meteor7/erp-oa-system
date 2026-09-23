<script setup>
// 近 6 个月报销 + 付款堆叠柱状图（报销橙色在下，付款蓝色在上）。
import { computed } from 'vue';
import { shortMoney, stackedChart } from '../../lib/expenseBoards.js';
import { money } from '../../lib/expenseClaims.js';

const props = defineProps({ trend: { type: Array, default: () => [] } });
const chart = computed(() => stackedChart(props.trend));
</script>

<template>
  <div style="overflow-x:auto">
    <svg :viewBox="`0 0 ${chart.width} ${chart.height}`" width="100%" style="min-width:420px" role="img" aria-label="近 6 个月报销与付款金额">
      <g v-for="tick in chart.ticks" :key="tick.value">
        <line :x1="chart.pad" :x2="chart.width - 8" :y1="tick.y" :y2="tick.y" stroke="#EEF0F4" />
        <text :x="chart.pad - 6" :y="tick.y + 4" text-anchor="end" font-size="10" fill="#8A93A3">{{ tick.label }}</text>
      </g>
      <g v-for="bar in chart.bars" :key="bar.month">
        <rect :x="bar.x" :y="bar.reimbursementY" :width="bar.width" :height="bar.reimbursementHeight" fill="#FF8F00" rx="2">
          <title>{{ bar.month }} 报销 {{ money(bar.reimbursement) }}</title>
        </rect>
        <rect :x="bar.x" :y="bar.paymentY" :width="bar.width" :height="bar.paymentHeight" fill="#3E63DD" rx="2">
          <title>{{ bar.month }} 付款 {{ money(bar.payment) }}</title>
        </rect>
        <text v-if="bar.total" :x="bar.x + bar.width / 2" :y="bar.labelY" text-anchor="middle" font-size="10" fill="#4A5365">{{ shortMoney(bar.total) }}</text>
        <text :x="bar.x + bar.width / 2" :y="chart.height - 8" text-anchor="middle" font-size="11" fill="#8A93A3">{{ bar.label }}</text>
      </g>
    </svg>
  </div>
  <div class="legend">
    <span><i style="background:#FF8F00"></i>报销</span>
    <span><i style="background:#3E63DD"></i>付款</span>
    <span class="muted">按实际付款日期计入月份</span>
  </div>
</template>
