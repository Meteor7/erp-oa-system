<script setup>
// 「谁不在」（2026-10-14 按确认的 demo）：今天 / 本周，或者在「未来 14 天」的图上点的某一天（右上角一个 ✕ 回到今天）。
// 四格：请假 / 调休 / 出差 / 加班，每格一个数字 = 这段时间有已批准申请的人数（出差的人当天有请假就算在请假里，出差不算不在岗）；
// 点一格只看这一类，再点一下取消。下面一张申请一行，还在审批的排在最后、不算人数；超过 8 行折叠；点一行进那张申请。
import { computed, ref, watch } from 'vue';
import { awayView, fold, kindText, lengthText, md, spanText, statusOf } from '../../lib/attendanceHome.js';

const props = defineProps({
  // 已经按页面顶上的部门 / 姓名筛过的明细（attendance_board_entry.get_attendance_requests 的 rows）。
  rows: { type: Array, default: () => [] },
  today: { type: String, default: '' },
  workDates: { type: Array, default: () => [] },
  period: { type: String, default: 'day' },
  day: { type: String, default: '' },
  tile: { type: String, default: '' },
  // 进了某个部门就不再显示“部门”这一列。
  showDept: { type: Boolean, default: true },
});
const emit = defineEmits(['period', 'day', 'tile', 'open']);

const open = ref(false);
const view = computed(() => awayView(props.rows, { today: props.today, period: props.period, day: props.day, tile: props.tile, workDates: props.workDates }));
const folded = computed(() => fold(view.value.rows, open.value));
const columns = computed(() => (props.showDept ? 7 : 6));
const isToday = computed(() => props.period !== 'week' && !view.value.picked);
watch(() => [props.period, props.day, props.tile], () => { open.value = false; });
</script>

<template>
  <section id="ac-away" class="ac-panel" aria-label="谁不在">
    <div class="ac-hd">
      <h2>谁不在 · {{ view.title }}</h2>
      <span v-if="view.restDay" class="ac-note">休息日</span>
      <span class="ac-right ac-hdtools">
        <button v-if="view.picked" type="button" class="ac-daychip" title="回到今天" @click="emit('day', '')">{{ md(view.from) }} ✕</button>
        <span class="ac-seg" role="group" aria-label="时间范围">
          <button type="button" :class="{ on: isToday }" :aria-pressed="isToday" @click="emit('period', 'day')">今天</button>
          <button type="button" :class="{ on: period === 'week' }" :aria-pressed="period === 'week'" @click="emit('period', 'week')">本周</button>
        </span>
      </span>
    </div>
    <div class="ac-body">
      <div :class="['ac-tiles', { picked: tile }]">
        <button
          v-for="item in view.tiles" :key="item.key" type="button" :class="['ac-tile', item.key, { on: item.on }]" :aria-pressed="item.on"
          @click="emit('tile', item.on ? '' : item.key)">
          <span>{{ item.label }}</span><b>{{ item.count }}<small>人</small></b>
        </button>
      </div>
      <div v-if="!view.rows.length" class="ac-empty sm">{{ view.emptyText }}</div>
      <template v-else>
        <div class="ac-tblwrap">
          <table class="ac-t">
            <thead><tr><th>姓名</th><th v-if="showDept">部门</th><th>类型</th><th>日期</th><th class="n">时长</th><th></th><th></th></tr></thead>
            <tbody>
              <template v-for="(row, index) in folded.shown" :key="row.name">
                <tr v-if="index === view.pendingFrom" class="sec"><td :colspan="columns">还在审批，不算人数</td></tr>
                <tr
                  :class="['go', { dim: !row.approved }]" tabindex="0" role="link" :aria-label="'打开 ' + row.employee_name + ' 的' + kindText(row) + '申请'"
                  @click="emit('open', row)" @keydown.enter="emit('open', row)">
                  <td><b>{{ row.employee_name }}</b></td>
                  <td v-if="showDept">{{ row.department_label }}</td>
                  <td><span :class="['ac-tag', row.kind]">{{ kindText(row) }}</span></td>
                  <td class="dt">{{ spanText(row.from_date, row.to_date) }}<span v-if="row.travel_destination" class="ac-note"> {{ row.travel_destination }}</span></td>
                  <td class="n">{{ lengthText(row) }}</td>
                  <td><span v-if="statusOf(row)" :class="['ac-st', statusOf(row).tone]">{{ statusOf(row).text }}</span></td>
                  <td class="ac-go">›</td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <button v-if="folded.rest" type="button" class="ac-more" :aria-expanded="open" @click="open = !open">{{ open ? '收起' : `展开其余 ${folded.rest} 条` }}</button>
      </template>
    </div>
  </section>
</template>
