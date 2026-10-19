<script setup>
// 近 6 个月报销 + 付款堆叠柱状图（报销在下，付款在上）。
// 按容器实际宽度画、固定高度：原来用固定小画布整体缩放，宽屏上文字和图会放大三四倍。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { shortMoney, stackedChart } from '../../lib/expenseBoards.js';
import { money } from '../../lib/expenseClaims.js';

const REIMBURSEMENT = '#E0A45A';
const PAYMENT = '#5470C6';
const HEIGHT = 220;

const props = defineProps({ trend: { type: Array, default: () => [] } });
const box = ref(null);
const width = ref(560);
let observer = null;

onMounted(() => {
  const measure = () => { if (box.value) width.value = Math.max(320, Math.round(box.value.clientWidth)); };
  measure();
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(measure);
    observer.observe(box.value);
  }
});
onBeforeUnmount(() => observer?.disconnect());

const hasData = computed(() => props.trend.some((row) => Number(row.reimbursement || 0) + Number(row.payment || 0) > 0));
// 刻度最多显示 5 条左右，避免 0~1000 每 100 一条挤成一片。
const ticks = computed(() => {
  const all = chart.value.ticks;
  const every = Math.max(1, Math.ceil((all.length - 1) / 5));
  return all.filter((tick, index) => index % every === 0 || index === all.length - 1);
});
const chart = computed(() => stackedChart(props.trend, {
  width: width.value,
  height: HEIGHT,
  pad: 44,
  bar: Math.round(Math.min(56, Math.max(24, width.value / (Math.max(1, props.trend.length) * 3)))),
}));
</script>

<template>
  <div ref="box">
    <svg v-if="hasData" :viewBox="`0 0 ${chart.width} ${chart.height}`" :width="chart.width" :height="chart.height" role="img" aria-label="近 6 个月报销与付款金额" style="display:block;max-width:100%">
      <g v-for="tick in ticks" :key="tick.value">
        <line :x1="chart.pad" :x2="chart.width - 8" :y1="tick.y" :y2="tick.y" stroke="#EEF0F4" />
        <text :x="chart.pad - 8" :y="tick.y + 4" text-anchor="end" font-size="12" fill="#65788B">{{ tick.label }}</text>
      </g>
      <g v-for="bar in chart.bars" :key="bar.month">
        <rect :x="bar.x" :y="bar.reimbursementY" :width="bar.width" :height="bar.reimbursementHeight" :fill="REIMBURSEMENT" rx="2">
          <title>{{ bar.month }} 报销 {{ money(bar.reimbursement) }}</title>
        </rect>
        <rect :x="bar.x" :y="bar.paymentY" :width="bar.width" :height="bar.paymentHeight" :fill="PAYMENT" rx="2">
          <title>{{ bar.month }} 付款 {{ money(bar.payment) }}</title>
        </rect>
        <text v-if="bar.total" :x="bar.x + bar.width / 2" :y="bar.labelY" text-anchor="middle" font-size="12" fill="#4A5365">{{ shortMoney(bar.total) }}</text>
        <text :x="bar.x + bar.width / 2" :y="chart.height - 6" text-anchor="middle" font-size="13" fill="#5B6475">{{ bar.label }}</text>
      </g>
    </svg>
    <div v-else class="empty" style="padding:28px 0">近 6 个月还没有报销或付款记录</div>
  </div>
  <div v-if="hasData" class="legend">
    <span><i :style="{ background: REIMBURSEMENT }"></i>报销</span>
    <span><i :style="{ background: PAYMENT }"></i>付款</span>
    <span class="muted">按实际付款日期计入月份</span>
  </div>
</template>
