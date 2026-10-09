<script setup>
// 部门这两周谁不在：每个不在的人一行，每天一格（蓝 = 已通过，虚线 = 审批中，灰底 = 休息日），最下面一行是当天不在的人数，
// 同一个工作日有 2 人以上不在时标红。只列出这两周有人请假或调休的人；只给名字和日期，不给类型和事由，加班不算不在。
import { computed } from 'vue';
import { teamGrid } from '../../lib/attendanceView.js';

const props = defineProps({
  teams: { type: Array, default: () => [] },
});

const grids = computed(() => (props.teams || []).map((team) => ({ department: team.department, headcount: team.headcount, ...teamGrid(team) })));
const range = computed(() => grids.value.find((grid) => grid.range)?.range || '');
</script>

<template>
  <section v-if="grids.length" class="panel flush" aria-label="部门这两周谁不在">
    <div class="at-hd"><b>部门这两周谁不在</b><span v-if="range" class="muted at-right">{{ range }}</span></div>
    <template v-for="grid in grids" :key="grid.department">
      <div v-if="grids.length > 1" class="at-dept">{{ grid.department }} · {{ grid.headcount }} 人</div>
      <div v-if="!grid.rows.length" class="at-out"><span class="muted">这两周没有人请假或调休</span></div>
      <div v-else class="at-tg" role="table" :style="{ '--tg-cols': grid.days.length }" :aria-label="grid.department + ' 这两周谁不在'">
        <div class="at-tg-r" role="row">
          <span role="columnheader" class="at-tg-n"></span>
          <span v-for="day in grid.days" :key="day.date" role="columnheader" :class="['at-tgd', { off: day.off }]" :title="day.title">{{ day.label }}</span>
        </div>
        <div v-for="person in grid.rows" :key="person.name" class="at-tg-r" role="row">
          <span role="rowheader" class="at-tg-n" :title="person.name">{{ person.name }}</span>
          <span v-for="(cell, index) in person.cells" :key="index" role="cell" :class="['at-tgc', cell.state, { off: grid.days[index].off }]" :title="cell.title"></span>
        </div>
        <div class="at-tg-r" role="row">
          <span role="rowheader" class="at-tg-n muted">不在人数</span>
          <span v-for="(total, index) in grid.totals" :key="index" role="cell" :class="['at-tgt', { crowded: total.crowded }]">{{ total.n || '' }}</span>
        </div>
      </div>
      <div v-if="grid.note" class="at-tg-note">{{ grid.note }}</div>
    </template>
    <div class="at-tg-legend"><span><i class="at-tgc approved"></i>已通过</span><span><i class="at-tgc pending"></i>审批中</span><span><i class="at-tgc off"></i>休息日</span></div>
    <div class="muted at-foot">请假和调休，不含加班；只显示日期。</div>
  </section>
</template>
