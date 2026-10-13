<script setup>
// 一张采购 / 购买申请走到哪一步：分段进度条（已走过的绿、当前的橙、没到的灰）。
// where = 再显示“现在在谁手上 · 已等几天 · 到货多少”；labels = 条下面写出每一格的名字；footOnly = 只要那一行（详情页上面已经有采购进度条了）。
import { computed } from 'vue';
import { arrivalOf, isActive, pipeline, waitedDays, whereText } from '../../lib/procurementView.js';
import { STUCK_AFTER_DAYS, isWaitingTooLong } from '../../lib/waiting.js';

const props = defineProps({
  row: { type: Object, default: null },
  now: { type: Number, default: () => Date.now() },
  where: { type: Boolean, default: false },
  labels: { type: Boolean, default: false },
  footOnly: { type: Boolean, default: false },
});

const pipe = computed(() => pipeline(props.row));
const arrival = computed(() => arrivalOf(props.row));
const wait = computed(() => (props.row && isActive(props.row) ? waitedDays(props.row, props.now) : null));
const holder = computed(() => (props.row ? whereText(props.row) : ''));
</script>

<template>
  <div v-if="pipe" class="pr-pipe-wrap">
    <div v-if="!footOnly" class="pr-pipe" :style="{ '--n': pipe.cells.length }" role="img" :aria-label="`进度：${pipe.current}`">
      <i v-for="(state, index) in pipe.cells" :key="index" :class="state" :title="pipe.labels[index]"></i>
    </div>
    <div v-if="labels && !footOnly" class="pr-pipe-lbl" :style="{ '--n': pipe.cells.length }">
      <span v-for="(label, index) in pipe.labels" :key="label" :class="{ cur: pipe.cells[index] === 'cur' }">{{ label }}</span>
    </div>
    <div v-if="where" class="pr-pipe-foot">
      <span v-if="holder && holder !== '—'" class="who">现在在：{{ holder }}</span>
      <span v-if="wait !== null" :class="['wait', { warn: isWaitingTooLong(wait) }]">{{ wait ? `已等 ${wait} 天${isWaitingTooLong(wait) ? ` · 超过 ${STUCK_AFTER_DAYS} 天` : ''}` : '今天提交' }}</span>
      <span v-if="arrival" class="pr-arrive">已到 {{ arrival.got }} / {{ arrival.total }}<span class="t"><i :style="{ width: arrival.pct + '%' }"></i></span></span>
    </div>
    <div v-else-if="arrival" class="pr-pipe-foot"><span class="pr-arrive">已到 {{ arrival.got }} / {{ arrival.total }}<span class="t"><i :style="{ width: arrival.pct + '%' }"></i></span></span></div>
  </div>
</template>
