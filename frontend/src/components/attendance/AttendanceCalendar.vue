<script setup>
// 我的月历：这个月每一天请了什么假、加了什么班、审批到哪一步。请假实心、调休描边、加班一个点、审批中虚线框。
import { computed } from 'vue';
import { calendarCells, periodTitle, shiftPeriod } from '../../lib/attendanceView.js';

const props = defineProps({
  home: { type: Object, default: null },
  period: { type: String, required: true },
  chosen: { type: Array, default: () => [] },
});
const emit = defineEmits(['period']);

const cells = computed(() => calendarCells({
  period: props.period,
  firstWeekday: props.home?.calendar?.first_weekday,
  daysInMonth: props.home?.calendar?.days_in_month,
  workDates: props.home?.calendar?.work_dates || [],
  entries: props.home?.calendar?.entries || [],
  selected: props.chosen,
}));

function cellClass(cell) {
  if (cell.blank) return 'blank';
  const kind = cell.kind === 'overtime' ? 'ot' : cell.kind;
  return [cell.pending ? 'pend' : kind === 'ot' ? '' : kind, kind === 'ot' ? 'ot' : '', { today: cell.today, off: cell.off && !cell.kind, chosen: cell.chosen }];
}
</script>

<template>
  <section class="panel flush" aria-label="我的月历">
    <div class="at-hd">
      <b>{{ periodTitle(period) }}</b>
      <span class="at-right at-nav">
        <button type="button" aria-label="上个月" @click="emit('period', shiftPeriod(period, -1))">‹</button>
        <button type="button" aria-label="下个月" @click="emit('period', shiftPeriod(period, 1))">›</button>
      </span>
    </div>
    <div class="at-cal" role="grid" aria-label="我的月历">
      <div v-for="name in ['一', '二', '三', '四', '五', '六', '日']" :key="name" class="h">{{ name }}</div>
      <div v-for="cell in cells" :key="cell.key" class="d" :class="cellClass(cell)" :aria-label="cell.blank ? undefined : `${cell.date}${cell.tag ? ' ' + cell.tag : ''}`">{{ cell.blank ? '' : cell.day }}</div>
    </div>
    <div class="at-legend">
      <span class="at-dchip am">请假</span><span class="at-dchip comp">调休</span><span class="at-dchip pm">加班 ●</span><span class="at-dchip pend">审批中</span>
    </div>
  </section>
</template>
