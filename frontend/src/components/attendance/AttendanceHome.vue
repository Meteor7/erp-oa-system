<script setup>
// 考勤中心首页：额度和待办一眼看到（年假 / 调休 / 我的申请 / 待我审批）。
// 待我审批是审批卡片：批之前先看影响（扣不扣年假、事假第几次、同期有谁不在），同意和驳回（写原因、选退回给谁）都在卡片上完成，
// 点申请人那一块才进详情；我审批过的在下面。右栏是我的申请（卡在哪一步）和部门这两周谁不在。
// 只有申请、不审批的人：我的申请放在主栏，不显示右栏。
import { computed, ref } from 'vue';
import {
  TYPES, actedText, balanceKpis, byWait, canQuickApprove, effectLine, filterRows, kindOf, mineSummary, numText, personShort,
  requestTitle, returnedDrafts, rejectionOf, reviewedResult, rowChips, totalOf, typeChips, typeCounts, waitText,
} from '../../lib/attendanceView.js';
import AttendanceMineCard from './AttendanceMineCard.vue';
import AttendanceTeamGrid from './AttendanceTeamGrid.vue';

const props = defineProps({
  home: { type: Object, default: null },
  mine: { type: Object, required: true },
  review: { type: Object, required: true },
  reviewed: { type: Array, default: () => [] },
  loaded: { type: Object, required: true },
  now: { type: Number, default: () => Date.now() },
  busy: { type: Boolean, default: false },
  hasEmployee: { type: Boolean, default: false },
  isApprover: { type: Boolean, default: false },
  availableTypes: { type: Array, default: () => [] },
  noEmployeeText: { type: String, default: '' },
  // 驳回：(单据, 原因, 退回给谁) → 失败时返回错误文字，成功返回空字符串。
  rejectRow: { type: Function, default: null },
});
const emit = defineEmits(['new', 'list', 'open', 'approve', 'withdraw', 'continue']);

const chip = ref('all');
const kpi = computed(() => balanceKpis(props.home));
const counts = computed(() => typeCounts(props.review.items));
const chips = computed(() => typeChips(counts.value, chip.value, true));
const todoRows = computed(() => byWait(filterRows(props.review.items, chip.value), props.now).slice(0, 3));
const doneRows = computed(() => (props.reviewed || []).slice(0, 3));
const mineInfo = computed(() => mineSummary(props.mine.items));
const returned = computed(() => returnedDrafts(props.mine.items));
const longest = computed(() => {
  const days = props.review.items.map((row) => waitText(row, props.now)).filter((text) => text.endsWith('天')).map((text) => parseInt(text, 10));
  return days.length ? Math.max(...days) : 0;
});
const todoHint = computed(() => {
  if (!props.review.items.length) return '全部处理完了';
  return longest.value ? `最久等了 ${longest.value} 天 · 现在处理 →` : '现在处理 →';
});

function rejectionText(row) {
  const rejection = rejectionOf(row);
  const who = props.mine.names[String(rejection?.actor || '').toLowerCase()] || String(rejection?.actor || '').split('@')[0];
  return `${who ? `${who}：` : ''}${rejection?.note || '请修改后重新提交'}`;
}

// ---------------------------------------------------------------- 卡片上直接驳回
const rejectFor = ref('');
const note = ref('');
const target = ref('applicant');
const noteError = ref(false);
const rejectError = ref('');

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
  <div class="at-page">
    <div class="ph">
      <div>
        <div class="crumb">审批中心</div>
        <h3>请假 · 加班 · 调休</h3>
        <div class="muted">看额度、批申请、跟进度都在这里；新建申请在单独的页面里填。</div>
      </div>
      <div v-if="hasEmployee" class="head-actions">
        <button v-for="(type, index) in availableTypes" :key="type" type="button" :class="['btn', { pri: index === 0 }]" @click="emit('new', TYPES[type].label)">＋ 新建{{ TYPES[type].label }}</button>
      </div>
    </div>

    <div v-if="loaded.home && home && !hasEmployee" class="banner err">{{ noEmployeeText }}</div>

    <section v-for="row in returned" :key="row.name" class="at-returned" aria-label="被退回的申请">
      <b>{{ row.subject || requestTitle(row) }}（{{ row.name }}）被退回了</b>
      <span class="grow-col">{{ rejectionText(row) }}</span>
      <button type="button" class="btn pri sm" @click="emit('continue', row)">修改后重新提交</button>
    </section>

    <div class="at-kpis">
      <template v-if="hasEmployee">
        <button type="button" class="at-kpi" @click="emit('list', 'mine', '请假')">
          <span class="l">年假可用</span>
          <span v-if="kpi.annual" class="v">{{ kpi.annual.days }}<small>天 · {{ kpi.annual.hours }} 小时</small></span>
          <span v-else class="v">—</span>
          <span class="s">{{ kpi.annual ? `已用 ${kpi.annual.used} 小时` : '暂无年假信息' }}</span>
        </button>
        <button type="button" class="at-kpi" @click="emit('list', 'mine', '调休')">
          <span class="l">调休可用</span>
          <span v-if="kpi.comp" class="v">{{ kpi.comp.hours }}<small>小时</small></span>
          <span v-else class="v">—</span>
          <span class="s">{{ kpi.comp ? `累计加班 ${kpi.comp.credit} 小时` : '暂无调休信息' }}</span>
        </button>
      </template>
      <button type="button" class="at-kpi" @click="emit('list', 'mine', 'all')">
        <span class="l">我的申请</span>
        <span class="v">{{ mineInfo.total }}<small>张</small></span>
        <span class="s">其中进行中 {{ mineInfo.active }} 张</span>
      </button>
      <button v-if="isApprover" type="button" class="at-kpi hot" @click="emit('list', 'todo', 'all')">
        <span class="l">待我审批</span>
        <span class="v">{{ review.items.length }}<small>张</small></span>
        <span class="s">{{ todoHint }}</span>
      </button>
    </div>

    <div :class="['at-grid2', { solo: !isApprover }]">
      <div class="at-col">
        <section v-if="isApprover" class="panel flush" aria-label="待我审批">
          <div class="at-hd">
            <b>待我审批</b><span class="at-cnt">{{ review.items.length }}</span>
            <span class="at-chips" role="group" aria-label="按类型筛选">
              <button v-for="item in chips" :key="item.key" type="button" :class="['chip', { on: item.on }]" :aria-pressed="item.on" @click="chip = item.key">{{ item.label }}</button>
            </span>
            <button type="button" class="link at-right" @click="emit('list', 'todo', chip)">全部 →</button>
          </div>
          <div v-if="!loaded.review" class="empty">正在加载…</div>
          <div v-else-if="!todoRows.length" class="empty">没有需要你审批的申请（到“我审批过的”里可以看处理记录）</div>
          <article v-for="row in todoRows" :key="row.name" class="at-rv">
            <div class="at-rv-top" role="button" tabindex="0" :aria-label="'打开 ' + row.employee_name + ' 的申请详情'" @click="emit('open', row)" @keydown.enter="emit('open', row)">
              <span class="at-av">{{ personShort(row.employee_name) }}</span>
              <div class="at-main">
                <div class="at-line">
                  <b>{{ row.employee_name }}</b><span class="muted">{{ row.department }}</span>
                  <span :class="['at-tag', kindOf(row).tone]">{{ kindOf(row).text }}</span>
                  <span v-if="waitText(row, now)" class="at-tag warn">等你 {{ waitText(row, now) }}</span>
                </div>
                <div class="at-dchips">
                  <span v-for="day in rowChips(row, 4).chips" :key="day.date + day.text" :class="['at-dchip', day.mode]">{{ day.text }}</span>
                  <span v-if="rowChips(row, 4).more" class="at-dchip">… 共 {{ rowChips(row).chips.length }} 天</span>
                </div>
                <div class="muted">合计 {{ numText(totalOf(row)) }} 小时<template v-if="row.reason"> · {{ row.reason }}</template></div>
              </div>
              <span class="link">详情 →</span>
            </div>
            <div class="at-rv-body" aria-label="批之前先看影响">
              <span class="at-lab">批之前先看影响</span>
              <template v-if="row.hints && row.hints.length">
                <span v-for="(hint, index) in row.hints" :key="index" :class="['at-tag', hint.tone]">{{ hint.text }}</span>
              </template>
              <span v-else class="muted">{{ effectLine(row) }}</span>
            </div>
            <div v-if="rejectFor === row.name" class="at-rj">
              <textarea v-model="note" :aria-invalid="noteError" aria-label="驳回原因" placeholder="驳回原因（必填），申请人会看到" rows="2"></textarea>
              <div v-if="noteError" class="at-err" role="alert">驳回必须写原因</div>
              <div v-if="rejectError" class="at-err" role="alert">{{ rejectError }}</div>
              <div class="at-rj-bar">
                <select v-if="row.rejection_targets?.length" v-model="target" aria-label="驳回给谁" class="cell">
                  <option v-for="item in row.rejection_targets" :key="item.target" :value="item.target">驳回至：{{ item.label }}</option>
                </select>
                <span class="at-right at-acts">
                  <button type="button" class="btn sm" :disabled="busy" @click="cancelReject">取消</button>
                  <button type="button" class="btn sm danger" :disabled="busy" @click="confirmReject(row)">确认驳回</button>
                </span>
              </div>
            </div>
            <div v-else class="at-acts at-rv-acts">
              <button type="button" class="btn sm danger" :disabled="busy" @click="startReject(row)">驳回</button>
              <button v-if="canQuickApprove(row)" type="button" class="btn sm pri" :disabled="busy" @click="emit('approve', row)">同意</button>
              <button v-else type="button" class="btn sm" @click="emit('open', row)">去详情处理</button>
            </div>
          </article>
        </section>

        <AttendanceMineCard
          v-if="!isApprover" :mine="mine" :loaded="loaded.mine" :now="now" :busy="busy"
          @list="(scope, filter) => emit('list', scope, filter)" @open="(row) => emit('open', row)" @withdraw="(row) => emit('withdraw', row)" @continue="(row) => emit('continue', row)" />

        <section v-if="isApprover" class="panel flush" aria-label="我审批过的">
          <div class="at-hd">
            <b>我审批过的 · 最近</b><span class="at-cnt green">{{ reviewed.length }}</span>
            <button type="button" class="link at-right" @click="emit('list', 'done', 'all')">全部 →</button>
          </div>
          <div v-if="!loaded.reviewed" class="empty">正在加载…</div>
          <div v-else-if="!doneRows.length" class="empty">还没有处理过的申请</div>
          <div v-for="row in doneRows" :key="row.name + String(row.acted_on || '')" class="at-item" role="button" tabindex="0" @click="emit('open', row)" @keydown.enter="emit('open', row)">
            <span class="at-av">{{ personShort(row.employee_name) }}</span>
            <div class="at-main">
              <div class="at-line">
                <b>{{ row.employee_name }}</b>
                <span :class="['at-tag', kindOf(row).tone]">{{ kindOf(row).text }}</span>
                <span :class="['at-tag', reviewedResult(row).tone]">{{ reviewedResult(row).text }}</span>
              </div>
              <div class="muted">{{ actedText(row) }}<template v-if="row.note"> · {{ row.note }}</template></div>
            </div>
            <button type="button" class="btn sm" @click.stop="emit('open', row)">查看</button>
          </div>
        </section>
      </div>

      <div v-if="isApprover" class="at-col">
        <AttendanceMineCard
          :mine="mine" :loaded="loaded.mine" :now="now" :busy="busy"
          @list="(scope, filter) => emit('list', scope, filter)" @open="(row) => emit('open', row)" @withdraw="(row) => emit('withdraw', row)" @continue="(row) => emit('continue', row)" />
        <AttendanceTeamGrid :teams="review.team || []" />
      </div>
    </div>
  </div>
</template>
