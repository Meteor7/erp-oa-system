<script setup>
// 「未来 14 天」（2026-10-14 按确认的 demo）：一天一根柱子，柱子上只写一个数 = 已批准的人数（审批中的不画，也不写“+N”）。
// 纵轴是整数刻度加浅网格线；周末 / 节假日底色、写“休”；今天的日期是橙色。
// 切换“不在岗”（按年假 / 事假 / 病假 / 调休 / 其他假堆叠）和“出差”；点一根柱子，「谁不在」就看那一天。纯 SVG，不引图表库。
import { computed } from 'vue';
import { KIND_LABELS, chartModel } from '../../lib/attendanceHome.js';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  today: { type: String, default: '' },
  workDates: { type: Array, default: () => [] },
  mode: { type: String, default: 'off' },
  // 「谁不在」正在看的那一天（看本周时为空）。
  selected: { type: String, default: '' },
});
const emit = defineEmits(['mode', 'day']);

const model = computed(() => chartModel(props.rows, { today: props.today, workDates: props.workDates, mode: props.mode, selected: props.selected }));
</script>

<template>
  <section class="ac-panel" aria-label="未来 14 天">
    <div class="ac-hd">
      <h2>未来 14 天</h2><span class="ac-note">每天几个人 · 点柱子看名单</span>
      <span class="ac-seg ac-right" role="group" aria-label="看哪一类">
        <button type="button" :class="{ on: mode !== 'trip' }" :aria-pressed="mode !== 'trip'" @click="emit('mode', 'off')">不在岗</button>
        <button type="button" :class="{ on: mode === 'trip' }" :aria-pressed="mode === 'trip'" @click="emit('mode', 'trip')">出差</button>
      </span>
    </div>
    <div class="ac-body">
      <svg class="ac-svg" :viewBox="`0 0 ${model.width} ${model.height}`" role="group" aria-label="未来 14 天每天人数，点一天看名单">
        <g class="gl">
          <g v-for="tick in model.ticks" :key="tick.value">
            <line :x1="model.left" :x2="model.width - model.right" :y1="tick.y" :y2="tick.y" />
            <text :x="model.left - 8" :y="tick.y + 4" text-anchor="end">{{ tick.value }}</text>
          </g>
        </g>
        <g
          v-for="col in model.columns" :key="col.date" :class="['col', { sel: col.selected, we: col.offDay }]" tabindex="0" role="button" :aria-label="col.label"
          @click="emit('day', col.date)" @keydown.enter="emit('day', col.date)">
          <rect class="hit" :x="col.x + 1" :y="model.top - 14" :width="col.width - 2" :height="model.height - model.top - 2" rx="6" />
          <rect v-for="seg in col.segments" :key="seg.kind" :class="'f-' + seg.kind" :x="col.barX" :y="seg.y" :width="col.barWidth" :height="seg.height" rx="4" />
          <text v-if="col.total" class="val" :x="col.center" :y="col.valueY" text-anchor="middle">{{ col.total }}</text>
          <text :class="['dl', { t0: col.today }]" :x="col.center" :y="model.dayY" text-anchor="middle">{{ col.day }}</text>
          <text class="wl" :x="col.center" :y="model.weekY" text-anchor="middle">{{ col.offDay ? '休' : col.weekday }}</text>
        </g>
      </svg>
      <div class="ac-legend">
        <span v-for="kind in model.legend" :key="kind"><i :class="'k-' + kind"></i>{{ KIND_LABELS[kind] }}</span>
        <span v-if="!model.legend.length" class="ac-note">这 14 天没有</span>
        <span class="ac-note">{{ mode === 'trip' ? '已批准的出差，前台办理中的也算；当天请假的人算在请假里' : '不在岗 = 请假 + 调休，出差不算' }}</span>
      </div>
    </div>
  </section>
</template>
