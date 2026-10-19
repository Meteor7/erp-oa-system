<script setup>
// 三张小图：工资去向（环形）、各部门应付工资（横向条形）、实发工资分布（柱状）。纯 SVG / CSS，数据都来自当前筛选的工资行。
import { computed } from 'vue';
import { accountShare, chartParts, deptBars, money, netBuckets, totalsOf } from '../../lib/payrollView.js';

const props = defineProps({ rows: { type: Array, default: () => [] } });
const R = 38, C = 2 * Math.PI * R;
const total = computed(() => totalsOf(props.rows));
const parts = computed(() => chartParts(total.value));
const arcs = computed(() => {
  let offset = 0;
  return parts.value.map((part) => { const length = part.share * C; const arc = { ...part, dash: `${length.toFixed(2)} ${(C - length).toFixed(2)}`, offset: (-offset).toFixed(2) }; offset += length; return arc; });
});
const netShare = computed(() => (parts.value[0].share * 100).toFixed(1));
const gross = computed(() => parts.value.reduce((t, part) => t + Math.max(part.value, 0), 0));
const depts = computed(() => deptBars(props.rows));
const buckets = computed(() => netBuckets(props.rows));
const accounts = computed(() => accountShare(props.rows));
const pct = (share) => (share * 100).toFixed(1) + '%';
</script>

<template>
  <div class="pr-charts" aria-label="图表">
    <div class="pr-cc">
      <h4>工资去向 <span>占 {{ money(gross) }} 的比例</span></h4>
      <div class="pr-donut">
        <svg viewBox="0 0 104 104" role="img" aria-label="工资去向">
          <circle cx="52" cy="52" :r="R" fill="none" stroke="#EEF1F6" stroke-width="14" />
          <circle v-for="arc in arcs" :key="arc.key" cx="52" cy="52" :r="R" fill="none" :stroke="arc.color" stroke-width="14" :stroke-dasharray="arc.dash" :stroke-dashoffset="arc.offset" transform="rotate(-90 52 52)"><title>{{ arc.label }} {{ money(arc.value) }}</title></circle>
          <text x="52" y="50" text-anchor="middle" font-size="17" font-weight="700" fill="#1A2130">{{ netShare }}%</text>
          <text x="52" y="65" text-anchor="middle" font-size="9" fill="#65788B">实发占比</text>
        </svg>
        <div class="pr-lg"><div v-for="part in parts" :key="part.key"><span class="l"><i :style="{ background: part.color }"></i>{{ part.label }}</span><b>{{ pct(part.share) }}</b></div></div>
      </div>
    </div>
    <div class="pr-cc">
      <h4>各部门应付工资 <span>深色是实发，浅色是被扣掉的</span></h4>
      <div class="pr-hb">
        <div v-for="item in depts" :key="item.name" class="r">
          <span>{{ item.name }}<span class="pr-note"> {{ item.people }}人</span></span>
          <div class="t" :title="`应付 ${money(item.payable)}，实发 ${money(item.net)}`"><i :style="{ width: item.netWidth + '%' }"></i><i class="rest" :style="{ width: (item.payableWidth - item.netWidth) + '%' }"></i></div>
          <span class="num r" style="text-align:right">{{ money(item.payable) }}</span>
        </div>
        <div v-if="!depts.length" class="pr-note">没有数据</div>
      </div>
      <div class="pr-note">费用科目：<template v-for="(item, index) in accounts" :key="item.name"><template v-if="index"> · </template>{{ item.name }} {{ pct(item.share) }}</template>（成本分摊的依据）</div>
    </div>
    <div class="pr-cc">
      <h4>实发工资分布 <span>按人数</span></h4>
      <div class="pr-cols"><div v-for="item in buckets" :key="item.label" class="c" :title="`${item.label}：${item.count} 人`"><b>{{ item.count }}</b><i :style="{ height: Math.max(item.height * 78, item.count ? 4 : 2) + 'px' }"></i></div></div>
      <div class="pr-axis"><span v-for="item in buckets" :key="item.label">{{ item.label }}</span></div>
    </div>
  </div>
</template>
