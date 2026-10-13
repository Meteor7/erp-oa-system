<script setup>
// 待我审批：一人一行的紧凑列表。点一行才展开"批之前先看影响"（扣不扣年假、事假第几次、同期有谁不在）和去详情；
// 同意、驳回按钮在行内；驳回要写原因（必填），可以选退回给谁，写在这一行下面，不用跳页面。
import { computed, ref } from 'vue';
import {
  canQuickApprove, effectLine, kindOf, personShort, rangeText, rowDays, sizeText, waitText, workedSpan,
} from '../../lib/attendanceView.js';
import { isSlow } from '../../lib/attendanceFlow.js';
import { rowKind } from '../../lib/attendanceCharts.js';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  title: { type: String, default: '待我审批' },
  loaded: { type: Boolean, default: true },
  now: { type: Number, default: () => Date.now() },
  busy: { type: Boolean, default: false },
  // 最多显示几行（0 = 全部）；超过的从"全部 →"进列表。
  limit: { type: Number, default: 6 },
  // 驳回：(单据, 原因, 退回给谁) → 失败时返回错误文字，成功返回空字符串。
  rejectRow: { type: Function, default: null },
  emptyText: { type: String, default: '没有需要你审批的申请' },
});
const emit = defineEmits(['open', 'approve', 'list']);

const shown = computed(() => (props.limit > 0 ? props.rows.slice(0, props.limit) : props.rows));
const openName = ref('');
const rejectFor = ref('');
const note = ref('');
const target = ref('applicant');
const noteError = ref(false);
const rejectError = ref('');

function rangeOf(row) {
  const days = rowDays(row);
  const span = days.length ? workedSpan(days, row.from_date, row.to_date) : { from: row.from_date, to: row.to_date };
  return rangeText(span.from, span.to);
}

const tagText = (row) => kindOf(row).leaveType || kindOf(row).label;

function waitTag(row) {
  const text = waitText(row, props.now);
  if (!text || text === '刚刚') return null;
  return { text: `等 ${text}`, tone: isSlow(row, props.now) ? 'bad' : 'warn' };
}

function toggle(row) {
  openName.value = openName.value === row.name ? '' : row.name;
}

function startReject(row) {
  rejectFor.value = row.name;
  note.value = '';
  noteError.value = false;
  rejectError.value = '';
  target.value = row.rejection_targets?.[0]?.target || 'applicant';
}

function cancelReject() {
  rejectFor.value = '';
  rejectError.value = '';
}

async function confirmReject(row) {
  if (!note.value.trim()) {
    noteError.value = true;
    return;
  }
  noteError.value = false;
  rejectError.value = '';
  const failure = props.rejectRow ? await props.rejectRow(row, note.value.trim(), target.value) : '';
  if (failure) rejectError.value = failure;
  else rejectFor.value = '';
}
</script>

<template>
  <section class="ac-panel" :aria-label="title">
    <div class="ac-hd">
      <h2>{{ title }}</h2><span class="ac-cnt">{{ rows.length }}</span>
      <span class="ac-note">点一行看原因和影响</span>
      <button type="button" class="ac-link ac-right" @click="emit('list', 'todo', 'all')">全部 →</button>
    </div>
    <div v-if="!loaded" class="ac-empty">正在加载…</div>
    <div v-else-if="!shown.length" class="ac-empty">{{ emptyText }}</div>
    <div v-for="row in shown" :key="row.name" class="ac-q">
      <div class="row">
        <span :class="['ac-av', rowKind(row)]">{{ personShort(row.employee_name) }}</span>
        <div class="who" role="button" tabindex="0" :aria-expanded="openName === row.name" :aria-label="'展开 ' + row.employee_name + ' 的申请'" @click="toggle(row)" @keydown.enter="toggle(row)">
          <div class="l1">
            <b>{{ row.employee_name }}</b><span class="ac-note">{{ row.department }}</span>
            <span :class="['ac-tag', rowKind(row)]">{{ tagText(row) }}</span>
            <span class="ac-note">{{ rangeOf(row) }} · {{ sizeText(row) }}</span>
          </div>
          <div class="l2">{{ row.reason || effectLine(row) }}</div>
        </div>
        <div class="acts">
          <span v-if="waitTag(row)" :class="['ac-tag', waitTag(row).tone]">{{ waitTag(row).text }}</span>
          <template v-if="rejectFor !== row.name">
            <button type="button" class="ac-btn sm danger" :disabled="busy" @click="startReject(row)">驳回</button>
            <button v-if="canQuickApprove(row)" type="button" class="ac-btn sm pri" :disabled="busy" @click="emit('approve', row)">同意</button>
            <button v-else type="button" class="ac-btn sm" @click="emit('open', row)">去详情处理</button>
          </template>
        </div>
      </div>
      <div v-if="openName === row.name" class="more">
        <div class="tags" aria-label="批之前先看影响">
          <span class="ac-note" style="margin-right: 2px">批之前先看影响</span>
          <template v-if="row.hints && row.hints.length"><span v-for="(hint, index) in row.hints" :key="index" :class="['ac-tag', hint.tone]">{{ hint.text }}</span></template>
          <span v-else class="ac-note">{{ effectLine(row) }}</span>
          <button type="button" class="ac-link ac-right" :aria-label="'打开 ' + row.employee_name + ' 的申请详情'" @click="emit('open', row)">详情 →</button>
        </div>
      </div>
      <div v-if="rejectFor === row.name" class="ac-rj">
        <textarea v-model="note" :aria-invalid="noteError" aria-label="驳回原因" placeholder="驳回原因（必填），申请人会看到" rows="2"></textarea>
        <div v-if="noteError" class="ac-err" role="alert">驳回必须写原因</div>
        <div v-if="rejectError" class="ac-err" role="alert">{{ rejectError }}</div>
        <div class="rjbar">
          <select v-if="row.rejection_targets?.length" v-model="target" aria-label="驳回给谁">
            <option v-for="item in row.rejection_targets" :key="item.target" :value="item.target">驳回至：{{ item.label }}</option>
          </select>
          <span class="ac-right" style="display: flex; gap: 6px">
            <button type="button" class="ac-btn sm" :disabled="busy" @click="cancelReject">取消</button>
            <button type="button" class="ac-btn sm danger" :disabled="busy" @click="confirmReject(row)">确认驳回</button>
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
