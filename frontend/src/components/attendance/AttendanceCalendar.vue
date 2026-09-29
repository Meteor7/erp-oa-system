<script setup>
// 我的日历：这个月每一天请了什么假、加了什么班、审批到哪一步；正在填的申请用黑框标出。
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
</script>

<template>
  <div class="at-cal">
    <div class="nav">
      <h4 style="margin:0;font-size:18px">我的日历</h4>
      <div class="m">
        <button type="button" aria-label="上个月" @click="emit('period', shiftPeriod(period, -1))">‹</button>
        <span class="num" style="min-width:92px;text-align:center">{{ periodTitle(period) }}</span>
        <button type="button" aria-label="下个月" @click="emit('period', shiftPeriod(period, 1))">›</button>
      </div>
    </div>
    <div class="wk"><span v-for="name in ['一', '二', '三', '四', '五', '六', '日']" :key="name">{{ name }}</span></div>
    <div class="grid7">
      <div v-for="cell in cells" :key="cell.key" class="at-cell"
        :class="cell.blank ? 'blank' : [cell.kind, { off: cell.off && !cell.kind, pending: cell.pending, chosen: cell.chosen, today: cell.today }]"
        :aria-label="cell.blank ? undefined : `${cell.date}${cell.tag ? ' ' + cell.tag : ''}`">
        <template v-if="!cell.blank"><b>{{ cell.day }}</b><span>{{ cell.tag }}</span></template>
      </div>
    </div>
    <div class="at-key">
      <span><i style="background:#FFE2BF"></i>请假</span>
      <span><i style="background:#D9E6FB"></i>加班</span>
      <span><i style="background:#CDEFEA"></i>调休</span>
      <span><i style="border:1.5px dashed #B35C00;box-sizing:border-box"></i>审批中</span>
      <span><i style="border:2px solid #1D2129;box-sizing:border-box"></i>本次</span>
    </div>
  </div>
</template>
