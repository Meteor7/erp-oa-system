<script setup>
// 申请的日期条：申请的日期前后各留两天，每天一格；申请的那几天按类型上色并标出时段（全天 / 上午 / 下午 / N 小时），休息日浅色。
import { computed } from 'vue';
import { stripCells } from '../../lib/attendanceFlow.js';
import { rowKind } from '../../lib/attendanceCharts.js';

const props = defineProps({
  row: { type: Object, required: true },
});

const cells = computed(() => stripCells(props.row));
const kind = computed(() => rowKind(props.row));
</script>

<template>
  <div v-if="cells.length" class="af-strip" role="img" aria-label="申请的日期">
    <div v-for="cell in cells" :key="cell.date" :class="['c', { hit: cell.hit, we: cell.off && !cell.hit }, cell.hit ? kind : '']" :title="cell.title">{{ cell.label }}<br />{{ cell.week }}<i>{{ cell.text }}</i></div>
  </div>
</template>
