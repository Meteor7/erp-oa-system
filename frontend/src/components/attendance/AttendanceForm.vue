<script setup>
// 新建申请：先选类型，再选起止日期，每一天选全天 / 半天 / 不请（加班按小时），右边实时汇总本次申请、对额度的影响和审批路线。
import { computed, reactive, ref, watch } from 'vue';
import {
  LEAVE_RULES, LEAVE_RULE_DEFAULT, TYPES, api, createLatest, dayRows, formSummary, hoursOfMode, mergeDays, modeOfHours,
  buildFields, numText, stepHours, stepRole, subjectFor, totalHours, MAX_OVERTIME_HOURS,
} from '../../lib/attendanceView.js';

const props = defineProps({
  requestType: { type: String, required: true },
  home: { type: Object, default: null },
  route: { type: Object, default: null },
  draft: { type: Object, default: null },
});
const emit = defineEmits(['preview', 'saved', 'error']);

const form = reactive({ leaveType: '事假', from: '', to: '', days: [], subject: '', reason: '' });
const draftName = ref('');
const busy = ref(false);
const loadingDays = ref(false);
const message = ref('');
const error = ref('');
const latest = createLatest();

const overtime = computed(() => props.requestType === '加班申请');
const meta = computed(() => TYPES[props.requestType]);
const leaveTypes = computed(() => props.home?.leave_types || ['事假', '病假', '年假', '婚假', '产假', '陪产假', '丧假', '其他假']);
const rows = computed(() => dayRows(form.from, form.to, form.days, overtime.value));
const summary = computed(() => formSummary({
  requestType: props.requestType, leaveType: form.leaveType, days: form.days, rows: rows.value,
  annual: props.home?.annual, comp: props.home?.comp,
}));
const rule = computed(() => (props.requestType === '请假申请' ? (LEAVE_RULES[form.leaveType] || LEAVE_RULE_DEFAULT)
  : overtime.value ? '提交申请就按 1:1 增加调休额度，不增加月度工时上限；每天最多 24 小时。' : '提交时先占用额度，审批通过后正式扣减；不减少月度工时上限。'));
const hint = computed(() => (overtime.value ? '按实际小时数填，可以选休息日' : '休息日和已经申请过的日子自动去掉'));
const subjectHint = computed(() => subjectFor(props.requestType, form.leaveType, summary.value.hours, form.reason || '写一句原因'));
const cannotSubmit = computed(() => busy.value || loadingDays.value || !form.from || !form.to || Boolean(summary.value.blocked));
const whyNot = computed(() => {
  if (!form.from || !form.to) return '请先选开始和结束日期';
  if (loadingDays.value) return '正在计算每一天…';
  return summary.value.blocked;
});
const chosenDates = computed(() => form.days.filter((day) => Number(day.hours) > 0).map((day) => day.work_date));

function dirty() {
  return Boolean(form.from || form.to || form.reason.trim() || form.subject.trim());
}

function reset() {
  Object.assign(form, { from: '', to: '', days: [], subject: '', reason: '' });
  draftName.value = '';
}

async function loadDays() {
  if (!form.from || !form.to || form.to < form.from) {
    form.days = [];
    return;
  }
  const token = latest.begin();
  loadingDays.value = true;
  try {
    const data = await api.options(props.requestType, form.from, form.to);
    if (!latest.isCurrent(token)) return;
    form.days = mergeDays(data?.days, form.days);
  } catch (failure) {
    if (!latest.isCurrent(token)) return;
    form.days = [];
    error.value = String(failure?.message || failure);
  } finally {
    if (latest.isCurrent(token)) loadingDays.value = false;
  }
}

watch(() => form.from, (value) => {
  if (value && (!form.to || form.to < value)) form.to = value;
});
watch([() => form.from, () => form.to], loadDays);
watch(() => props.requestType, () => {
  latest.begin();
  reset();
  message.value = '';
  error.value = '';
});
watch([() => form.days, () => form.leaveType], () => {
  emit('preview', { hours: totalHours(form.days), dates: chosenDates.value, leaveType: form.leaveType });
}, { deep: true, immediate: true });

// 被退回的申请：点"修改后重新提交"后填进表单，后台刷新不会覆盖正在填的内容。
watch(() => props.draft, (draft) => {
  if (!draft) return;
  draftName.value = draft.name;
  Object.assign(form, {
    leaveType: draft.leave_type || '事假', from: draft.from_date || '', to: draft.to_date || '',
    days: (draft.attendance_days || []).map((day) => ({ work_date: day.work_date, hours: Number(day.hours), max_hours: 8, conflict: null })),
    subject: draft.subject || '', reason: draft.reason || '',
  });
}, { immediate: true });

function setMode(day, mode) {
  day.hours = hoursOfMode(mode, day.max_hours);
}

function bump(day, delta) {
  day.hours = stepHours(day.hours, delta, Math.min(MAX_OVERTIME_HOURS, day.max_hours));
}

function fields() {
  return buildFields({
    requestType: props.requestType, leaveType: form.leaveType, from: form.from, to: form.to,
    days: form.days, subject: form.subject, reason: form.reason,
  });
}

async function save(asDraft) {
  message.value = '';
  error.value = '';
  if (!asDraft && cannotSubmit.value) {
    error.value = whyNot.value || '请检查填写的内容';
    return;
  }
  if (asDraft && (!form.from || !form.to)) {
    error.value = '保存草稿也要先选开始和结束日期';
    return;
  }
  busy.value = true;
  try {
    if (draftName.value) {
      await api.updateDraft({ name: draftName.value, ...fields() });
      if (!asDraft) await api.submitDraft(draftName.value);
    } else {
      const created = await api.create({ request_type: props.requestType, ...fields(), submit: asDraft ? 0 : 1 });
      if (asDraft) draftName.value = created?.name || '';
    }
    message.value = asDraft ? '草稿已保存' : '申请已提交，等待审批';
    if (!asDraft) reset();
    emit('saved', message.value);
  } catch (failure) {
    error.value = String(failure?.message || failure || '提交失败');
  } finally {
    busy.value = false;
  }
}

defineExpose({ dirty });
</script>

<template>
  <div class="at-main">
    <section class="at-panel" :aria-label="meta.title">
      <div class="at-label"><h4>{{ meta.title }}</h4><span class="at-sub">部门、主管、审批人自动带出</span></div>

      <div v-if="requestType === '请假申请'" class="at-block">
        <div class="at-label">请假类型</div>
        <div class="at-chips">
          <button v-for="item in leaveTypes" :key="item" type="button" class="at-chip" :aria-pressed="form.leaveType === item" @click="form.leaveType = item">{{ item }}</button>
        </div>
        <div class="at-rule">{{ rule }}</div>
      </div>
      <div v-else class="at-rule">{{ rule }}</div>

      <div class="at-block">
        <div class="at-label"><span>时间</span><span class="at-sub">{{ hint }}</span></div>
        <div class="at-dates">
          <label>开始<input v-model="form.from" type="date" /></label>
          <label>结束<input v-model="form.to" type="date" :min="form.from" /></label>
        </div>
        <div v-if="rows.length" class="at-days">
          <div v-for="row in rows" :key="row.date" class="at-day" :class="{ rest: row.kind === 'rest', conflict: row.kind === 'conflict' }">
            <div class="d"><b>{{ row.label }}</b><span>{{ row.week }}</span></div>
            <template v-if="row.kind === 'work'">
              <div class="at-modes" role="group" :aria-label="`${row.label}请假时长`">
                <button type="button" :aria-pressed="modeOfHours(row.day.hours) === 'full'" :disabled="row.day.max_hours < 8" @click="setMode(row.day, 'full')">全天</button>
                <button type="button" :aria-pressed="modeOfHours(row.day.hours) === 'half'" :disabled="row.day.max_hours < 4" @click="setMode(row.day, 'half')">半天</button>
                <button type="button" :aria-pressed="modeOfHours(row.day.hours) === 'none'" @click="setMode(row.day, 'none')">不请</button>
                <button v-if="modeOfHours(row.day.hours) === 'custom'" type="button" aria-pressed="true" disabled>自定义</button>
              </div>
              <span class="h">{{ numText(row.day.hours) }} 小时<template v-if="row.day.max_hours < 8">（这天还能填 {{ numText(row.day.max_hours) }} 小时）</template></span>
            </template>
            <template v-else-if="row.kind === 'ot'">
              <div class="at-step">
                <button type="button" aria-label="减少半小时" @click="bump(row.day, -0.5)">−</button>
                <b>{{ numText(row.day.hours) }} 小时</b>
                <button type="button" aria-label="增加半小时" @click="bump(row.day, 0.5)">＋</button>
              </div>
              <span class="at-sub h">最多还能填 {{ numText(row.day.max_hours) }} 小时</span>
            </template>
            <span v-else-if="row.kind === 'rest'" class="at-sub">休息日，不计</span>
            <span v-else class="x">{{ row.day.conflict.text }}，不能重复申请</span>
          </div>
        </div>
        <div v-else-if="loadingDays" class="at-sub">正在计算每一天…</div>
      </div>

      <div class="at-block">
        <div class="at-label">说明</div>
        <label class="at-sub">主题（自动生成，可以改）<input v-model="form.subject" class="at-input" :placeholder="subjectHint" maxlength="120" /></label>
        <label class="at-sub">事由<textarea v-model="form.reason" class="at-area" rows="3" placeholder="写清楚原因，审批人才好判断，例如：陪家人到外地就医"></textarea></label>
      </div>
    </section>

    <aside class="at-side" aria-label="本次申请">
      <div class="at-panel">
        <div class="at-label"><span>本次申请</span></div>
        <div class="at-sum">{{ summary.big }}<small>{{ summary.unit }}</small></div>
        <div class="at-sub">{{ summary.detail }}</div>
        <div v-if="summary.impact && summary.hours > 0" class="at-impact" :class="summary.tone">{{ summary.impact }}</div>
        <div v-if="summary.blocked && form.from && form.to" class="at-impact warn">{{ summary.blocked }}</div>

        <div class="at-label">审批流程</div>
        <ol v-if="route?.steps?.length" class="at-route">
          <li v-for="(step, index) in route.steps" :key="step.step_index">
            <div class="n"><span>{{ step.step_index }}</span><i v-if="index < route.steps.length - 1"></i></div>
            <div class="w"><b>{{ step.approvers.map((person) => person.name).join(' / ') || '待指定' }}</b><span>{{ stepRole(step.label) }}</span></div>
          </li>
        </ol>
        <div v-else class="at-sub">审批路线加载中…</div>
        <div v-if="route?.copied_to?.length" class="at-sub">抄送：{{ route.copied_to.map((item) => item.label || item.name).join('、') }}</div>

        <div v-if="error" class="err" role="alert">{{ error }}</div>
        <div v-if="message" class="ok">{{ message }}</div>
        <button type="button" class="btn pri" style="width:100%;justify-content:center;min-height:44px;font-size:15px;font-weight:600" :disabled="cannotSubmit" :title="whyNot" @click="save(false)">{{ busy ? '提交中…' : meta.submit }}</button>
        <button type="button" class="btn" style="width:100%;justify-content:center;min-height:40px" :disabled="busy" @click="save(true)">{{ draftName ? '保存修改' : '保存草稿' }}</button>
        <div v-if="draftName" class="at-sub">正在编辑：{{ draftName }}</div>
      </div>
    </aside>
  </div>
</template>
