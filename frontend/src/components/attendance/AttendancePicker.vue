<script setup>
// 新建页的月历：先点开始日，再点结束日（只请一天点一次）。休息日、假期和已被占满的日子点不了（加班可以选休息日），
// 已有部分申请的日子下面有一个小点；今天的日期标成橙色。日子的状态来自服务端当月的可填日子，还没取到时都能点。
import { computed } from 'vue';
import { dayStatus, inRange, monthGrid } from '../../lib/attendanceFlow.js';

const props = defineProps({
  month: { type: String, required: true },
  from: { type: String, default: '' },
  to: { type: String, default: '' },
  info: { type: Object, default: null },
  overtime: { type: Boolean, default: false },
  today: { type: String, default: '' },
});
const emit = defineEmits(['pick', 'shift']);

const grid = computed(() => monthGrid(props.month));
const cells = computed(() => grid.value.cells.map((cell) => {
  if (!cell) return null;
  const status = dayStatus(cell.date, props.info, props.overtime);
  const selected = inRange(cell.date, props.from, props.to);
  return {
    ...cell, status, selected, edge: selected && (cell.date === props.from || cell.date === (props.to || props.from)),
    disabled: status === 'busy' || (status === 'rest' && !props.overtime),
    title: { busy: '这天已经请满了', rest: '休息日', part: '这天已有申请，还能请一部分', work: '' }[status],
  };
}));
</script>

<template>
  <div class="af-cal">
    <div class="mh">
      <button type="button" class="ac-btn sm" aria-label="上个月" @click="emit('shift', -1)">‹</button>
      <b>{{ grid.title }}</b>
      <button type="button" class="ac-btn sm" aria-label="下个月" @click="emit('shift', 1)">›</button>
    </div>
    <div class="g">
      <span v-for="week in ['一', '二', '三', '四', '五', '六', '日']" :key="week" class="w">{{ week }}</span>
      <template v-for="(cell, index) in cells" :key="index">
        <span v-if="!cell" class="d blank"></span>
        <button v-else type="button" :class="['d', { in: cell.selected, edge: cell.edge, today: cell.date === today, part: cell.status === 'part' }]" :disabled="cell.disabled" :aria-pressed="cell.selected" :title="cell.title" @click="emit('pick', cell.date)">{{ cell.day }}</button>
      </template>
    </div>
    <div class="legend"><span><i class="sel"></i>所选</span><span><i class="rest"></i>休息日 / 假期 / 已请满</span><span><i class="part"></i>已有部分申请</span><span class="t0">橙色数字是今天</span></div>
  </div>
</template>
