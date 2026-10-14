<script setup>
// 「近 5 个工作日」（2026-10-14，替换原来的“近 5 天不在岗”）：每人一行，写清楚每张单是哪几天、多长、批没批：
// 分“不在岗”（请假、调休）和“出差”两组；审批中的写“审批中”，前台还没办完的出差写“前台办理中”；每组超过 8 人折叠；点一张进那张申请。
import { computed, ref } from 'vue';
import { LIMIT, fold, kindText, lengthText, nearView, nextWorkDays, spanText, statusOf } from '../../lib/attendanceHome.js';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  today: { type: String, default: '' },
  workDates: { type: Array, default: () => [] },
});
const emit = defineEmits(['open']);

const days = computed(() => nextWorkDays(props.workDates, props.today, 5));
const view = computed(() => nearView(props.rows, days.value));
const open = ref({ off: false, trip: false });
const groups = computed(() => [
  { key: 'off', label: '不在岗', people: view.value.off },
  { key: 'trip', label: '出差', people: view.value.trip },
].map((group) => ({ ...group, ...fold(group.people, open.value[group.key], LIMIT) })));
</script>

<template>
  <section class="ac-panel" aria-label="近 5 个工作日">
    <div class="ac-hd"><h2>近 5 个工作日</h2><span class="ac-note">{{ spanText(view.from, view.to) }}</span></div>
    <div class="ac-body">
      <template v-for="group in groups" :key="group.key">
        <div class="ac-lbl">{{ group.label }} · {{ group.people.length }} 人</div>
        <div v-if="!group.people.length" class="ac-empty sm">没有</div>
        <div v-for="person in group.shown" :key="person.employee" class="ac-np">
          <b>{{ person.name }}</b>
          <div class="its">
            <button v-for="row in person[group.key]" :key="row.name" type="button" class="ac-it" :aria-label="'打开 ' + person.name + ' 的' + kindText(row) + '申请'" @click="emit('open', row)">
              <span :class="['ac-tag', row.kind]">{{ kindText(row) }}</span>
              <span class="d">{{ spanText(row.from_date, row.to_date) }}</span>
              <span class="ac-note">{{ lengthText(row) }}</span>
              <span v-if="statusOf(row)" :class="['ac-st', statusOf(row).tone]">{{ statusOf(row).text }}</span>
            </button>
          </div>
        </div>
        <button v-if="group.rest" type="button" class="ac-more" @click="open[group.key] = !open[group.key]">{{ open[group.key] ? '收起' : `展开其余 ${group.rest} 人` }}</button>
      </template>
    </div>
  </section>
</template>
