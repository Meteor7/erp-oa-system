<script setup>
// 首页顶上的一条指标栏。人事 / 领导的下面多一条今日出勤（在岗 / 请假 / 出差）。
// items：[{key, label, value, unit, sub, hot, go: [范围, 类型]}]；有 go 的可以点，点了去对应的列表。
import { computed } from 'vue';
import { todayParts } from '../../lib/attendanceCharts.js';

const props = defineProps({
  items: { type: Array, default: () => [] },
  // 今日出勤条：{title, today: {in, off, trip, rest_day}, headcount, rate}；不给就不显示这一条。
  today: { type: Object, default: null },
});
const emit = defineEmits(['list']);

const parts = computed(() => (props.today ? todayParts(props.today.today, props.today.headcount) : []));
</script>

<template>
  <section class="ac-panel" aria-label="指标">
    <div class="ac-metrics">
      <template v-for="item in items" :key="item.key">
        <button v-if="item.go" type="button" :class="{ hot: item.hot }" @click="emit('list', item.go[0], item.go[1])">
          <span class="l">{{ item.label }}</span>
          <span class="v">{{ item.value }}<small v-if="item.unit">{{ item.unit }}</small></span>
          <span class="s">{{ item.sub }}</span>
        </button>
        <div v-else :class="{ hot: item.hot }">
          <span class="l">{{ item.label }}</span>
          <span class="v">{{ item.value }}<small v-if="item.unit">{{ item.unit }}</small></span>
          <span class="s">{{ item.sub }}</span>
        </div>
      </template>
    </div>
    <div v-if="today" class="ac-today">
      <div class="row">
        <b>{{ today.title }}</b>
        <span>共 {{ today.headcount }} 人<template v-if="today.rate"> · 未来 14 天出勤率 <b>{{ today.rate }}%</b></template></span>
      </div>
      <p v-if="today.today.rest_day" class="ac-note" style="margin: 0">今天是休息日。</p>
      <div v-else class="ac-stackbar" role="img" aria-label="今日出勤">
        <i v-for="part in parts" :key="part.key" :class="'k-' + part.color" :style="{ width: part.pct + '%' }"></i>
      </div>
      <div v-if="!today.today.rest_day" class="ac-legend">
        <span v-for="part in parts" :key="part.key"><i :class="'k-' + part.color"></i>{{ part.label }}<b>{{ part.count }}</b></span>
      </div>
    </div>
  </section>
</template>
