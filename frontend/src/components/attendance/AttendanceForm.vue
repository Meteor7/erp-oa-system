<script setup>
// 新建请假 / 加班 / 调休（也用来继续填写草稿、修改被退回的申请）：单独一页。
// 请假和调休：先选起止日期，每一天选 全天 8 小时 / 上午 3 小时 / 下午 5 小时 / 自定义小时（每次 0.5）/ 不请；
// 加班：选日期和小时数（每次 0.5）。右边实时汇总本次申请、对额度和月度上限的影响和审批路线。
// 页面里换类型会清掉类型相关的内容（假别、每天怎么请、小时数），日期和事由保留。
import { computed, reactive, ref, watch } from 'vue';
import {
  COMP_RULE, HOURS_STEP, LEAVE_RULES, LEAVE_RULE_DEFAULT, MAX_OVERTIME_HOURS, OVERTIME_RULE, TYPES, api, buildFields, createLatest, customCap,
  dayNote, dayRows, formSummary, labelOfType, mergeDays, modeAvailable, modeOfHours, numText, pickMode, slotNote, stepHours, stepRole,
  subjectFor, DAY_RULE_TEXT,
} from '../../lib/attendanceView.js';

const props = defineProps({
  requestType: { type: String, required: true },
  draftName: { type: String, default: '' },
  home: { type: Object, default: null },
  route: { type: Object, default: null },
  types: { type: Array, default: () => ['请假申请', '加班申请', '调休申请'] },
});
const emit = defineEmits(['switch-type', 'draft-type', 'draft-saved', 'submitted', 'cancel']);

const MODES = [
  { key: 'full', label: '全天', title: '全天 8 小时' },
  { key: 'am', label: '上午', title: '上午 3 小时' },
  { key: 'pm', label: '下午', title: '下午 5 小时' },
  { key: 'custom', label: '自定义小时', title: '自定义小时，每次 0.5，最多 8 小时' },
  { key: 'none', label: '不请', title: '这天不请' },
];

const form = reactive({ leaveType: '事假', from: '', to: '', days: [], subject: '', reason: '' });
const multiDay = ref(false);
const savedName = ref('');
const snapshot = ref('');
const busy = ref(false);
const loadingDays = ref(false);
const loadingDraft = ref(false);
const message = ref('');
const error = ref('');
const latest = createLatest();
const draftLatest = createLatest();
let zeroNew = false;
let pendingClean = false;

const overtime = computed(() => props.requestType === '加班申请');
const meta = computed(() => TYPES[props.requestType]);
const leaveTypes = computed(() => props.home?.leave_types || ['事假', '病假', '年假', '婚假', '产假', '陪产假', '丧假', '其他假']);
const rows = computed(() => dayRows(form.from, form.to, form.days, overtime.value));
const summary = computed(() => formSummary({
  requestType: props.requestType, leaveType: form.leaveType, days: form.days, rows: rows.value,
  annual: props.home?.annual, comp: props.home?.comp,
}));
const rule = computed(() => (props.requestType === '请假申请' ? (LEAVE_RULES[form.leaveType] || LEAVE_RULE_DEFAULT) : overtime.value ? OVERTIME_RULE : COMP_RULE));
const subjectHint = computed(() => subjectFor(props.requestType, form.leaveType, summary.value.hours, form.reason || '写一句原因'));
const cannotSubmit = computed(() => busy.value || loadingDays.value || loadingDraft.value || !form.from || !form.to || Boolean(summary.value.blocked));
const whyNot = computed(() => {
  if (!form.from || !form.to) return '请先选开始和结束日期';
  if (loadingDays.value) return '正在计算每一天…';
  return summary.value.blocked;
});
// 换类型不算"改过"（日期和事由原样保留，类型相关的内容本来就是空的）。
const stateKey = computed(() => JSON.stringify([form.leaveType, form.from, form.to, form.days.map((day) => [day.work_date, Number(day.hours)]), form.subject, form.reason]));
// 每一天还在计算时不显示逐日行（否则会先闪一下"休息日"）。
const visibleRows = computed(() => (form.days.length || !loadingDays.value ? rows.value : []));
const editing = computed(() => Boolean(savedName.value));

function markClean() {
  snapshot.value = stateKey.value;
}
markClean();

// 表单有没有改过没保存的内容（刚载入的草稿、刚保存的草稿都算没改）。
function dirty() {
  return stateKey.value !== snapshot.value;
}

function resetAll() {
  Object.assign(form, { leaveType: '事假', from: '', to: '', days: [], subject: '', reason: '' });
  multiDay.value = false;
  savedName.value = '';
  zeroNew = false;
  markClean();
}

async function loadDays() {
  if (!form.from || !form.to || form.to < form.from) {
    form.days = [];
    return;
  }
  const token = latest.begin();
  const type = props.requestType;
  loadingDays.value = true;
  try {
    const data = await api.options(type, form.from, form.to);
    // 日期连续改动、中途换了类型：只认最后一次，旧的结果丢掉。
    if (!latest.isCurrent(token) || type !== props.requestType) return;
    form.days = mergeDays(data?.days, form.days, overtime.value, { zeroNew });
    zeroNew = false;
    if (pendingClean) {
      pendingClean = false;
      markClean();
    }
  } catch (failure) {
    if (!latest.isCurrent(token)) return;
    form.days = [];
    error.value = String(failure?.message || failure);
  } finally {
    if (latest.isCurrent(token)) loadingDays.value = false;
  }
}

// 继续填写草稿 / 修改被退回的申请：取这张申请，填进表单；类型和页面上的不一样时请页面换成它自己的类型。
async function loadDraft(name) {
  const token = draftLatest.begin();
  loadingDraft.value = true;
  error.value = '';
  try {
    const request = (await api.detail(name))?.request;
    if (!draftLatest.isCurrent(token)) return;
    if (!request || request.workflow_status !== '草稿') {
      error.value = '这张申请已经提交，不能再修改。';
      return;
    }
    if (request.request_type !== props.requestType) {
      emit('draft-type', labelOfType(request.request_type));
      return;
    }
    latest.begin();
    const days = (request.attendance_days || []).map((day) => {
      const hours = Number(day.hours);
      const mode = modeOfHours(hours);
      return { work_date: day.work_date, hours, mode, custom: mode === 'custom' ? hours : 0, max_hours: 8, am_taken: false, pm_taken: false, conflict: null };
    });
    Object.assign(form, {
      leaveType: request.leave_type || '事假', from: request.from_date || '', to: request.to_date || '', days,
      subject: request.subject || '', reason: request.reason || '',
    });
    multiDay.value = overtime.value && form.from !== form.to;
    savedName.value = request.name;
    zeroNew = true;
    pendingClean = true;
    await loadDays();
  } catch (failure) {
    if (draftLatest.isCurrent(token)) error.value = String(failure?.message || failure || '加载失败');
  } finally {
    if (draftLatest.isCurrent(token)) loadingDraft.value = false;
  }
}

watch(() => form.from, (value) => {
  if (!value) return;
  if (overtime.value && !multiDay.value) form.to = value;
  else if (!form.to || form.to < value) form.to = value;
});
watch(multiDay, (on) => {
  if (!on && overtime.value) form.to = form.from;
});
watch([() => form.from, () => form.to], loadDays);

// 页面里换类型：旧类型的假别、每天怎么请、主题清掉，日期和事由留着；在途的请求作废，按新类型重新算每一天。
watch(() => props.requestType, () => {
  latest.begin();
  draftLatest.begin();
  Object.assign(form, { leaveType: '事假', days: [], subject: '' });
  multiDay.value = overtime.value && Boolean(form.from) && form.from !== form.to;
  if (!overtime.value && form.to < form.from) form.to = form.from;
  message.value = '';
  error.value = '';
  loadingDays.value = false;
  if (props.draftName && props.draftName !== savedName.value) loadDraft(props.draftName);
  else if (savedName.value) resetAll();
  else loadDays();
});

watch(() => props.draftName, (name) => {
  if (name && name !== savedName.value) loadDraft(name);
}, { immediate: true });

function setMode(day, mode) {
  Object.assign(day, pickMode(day, mode));
  if (day.mode === 'custom') day.custom = day.hours;
}

function bump(day, delta) {
  day.hours = stepHours(day.hours, delta, customCap(day), HOURS_STEP);
  day.custom = day.hours;
}

function bumpOvertime(day, delta) {
  day.hours = stepHours(day.hours, delta, Math.min(MAX_OVERTIME_HOURS, day.max_hours), rows.value.filter((row) => row.kind === 'ot').length > 1 ? 0 : HOURS_STEP);
  day.custom = day.hours;
  day.mode = day.hours > 0 ? 'custom' : 'none';
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
    let name = savedName.value;
    if (name) {
      await api.updateDraft({ name, ...fields() });
      if (!asDraft) await api.submitDraft(name);
    } else {
      const created = await api.create({ request_type: props.requestType, ...fields(), submit: asDraft ? 0 : 1 });
      name = created?.name || '';
    }
    if (asDraft) {
      savedName.value = name;
      message.value = '草稿已保存';
      markClean();
      emit('draft-saved', name);
    } else {
      const submitted = { name, requestType: props.requestType };
      resetAll();
      emit('submitted', submitted);
    }
  } catch (failure) {
    error.value = String(failure?.message || failure || '提交失败');
  } finally {
    busy.value = false;
  }
}

defineExpose({ dirty });
</script>

<template>
  <div class="at-newgrid">
    <section class="panel flush at-formcard" :aria-label="meta.title">
      <div class="at-sec">
        <div class="lab">类型</div>
        <div class="seg at-types" role="group" aria-label="申请类型">
          <button v-for="type in types" :key="type" type="button" :aria-pressed="type === requestType" :disabled="editing && type !== requestType" :title="editing && type !== requestType ? '这张草稿的类型不能改，要换类型请另外新建' : ''" @click="type !== requestType && emit('switch-type', TYPES[type].label)">{{ TYPES[type].label }}</button>
        </div>
      </div>

      <div v-if="requestType === '请假申请'" class="at-sec">
        <div class="lab">假别</div>
        <div class="at-pills">
          <button v-for="item in leaveTypes" :key="item" type="button" class="at-pill" :class="{ on: form.leaveType === item }" :aria-pressed="form.leaveType === item" @click="form.leaveType = item">{{ item }}</button>
        </div>
        <div class="muted at-gap">{{ rule }}</div>
      </div>
      <div v-else class="at-sec"><div class="at-rule">{{ rule }}</div></div>

      <div class="at-sec">
        <div class="lab">{{ overtime ? '日期' : '时间' }}<span class="muted"> {{ overtime ? '按实际小时数填，可以选休息日' : `${DAY_RULE_TEXT}；休息日和已经占用的日子自动去掉` }}</span></div>
        <div class="at-dates">
          <label>{{ overtime && !multiDay ? '日期' : '开始' }}<input v-model="form.from" type="date" /></label>
          <label v-if="!overtime || multiDay">结束<input v-model="form.to" type="date" :min="form.from" /></label>
          <label v-if="overtime" class="at-multi"><input v-model="multiDay" type="checkbox" /> 跨多天</label>
        </div>
      </div>

      <div v-if="overtime" class="at-sec">
        <div class="lab">加班小时数</div>
        <div v-if="!visibleRows.length" class="muted">{{ loadingDays || loadingDraft ? '正在计算每一天…' : '先选日期' }}</div>
        <div v-for="row in visibleRows" :key="row.date" class="at-day ot" :class="{ conflict: row.kind === 'conflict' }">
          <div v-if="visibleRows.length > 1" class="d"><b>{{ row.date }}</b> <span class="muted">{{ row.week }}</span></div>
          <template v-if="row.kind === 'ot'">
            <span class="at-step">
              <button type="button" aria-label="减 0.5 小时" @click="bumpOvertime(row.day, -0.5)">−</button>
              <b class="num">{{ numText(row.day.hours) }}</b>
              <button type="button" aria-label="加 0.5 小时" @click="bumpOvertime(row.day, 0.5)">＋</button>
            </span>
            <span class="muted">小时（每次 0.5，每天最多 24 小时<template v-if="row.day.max_hours < MAX_OVERTIME_HOURS">；这天最多还能填 {{ numText(row.day.max_hours) }} 小时</template>）</span>
          </template>
          <span v-else-if="row.kind === 'conflict'" class="x">{{ row.day.conflict.text }}，不能重复申请</span>
        </div>
      </div>

      <div v-else class="at-sec">
        <div class="lab">每一天怎么请</div>
        <div v-if="!visibleRows.length" class="muted">{{ loadingDays || loadingDraft ? '正在计算每一天…' : '先选起止日期' }}</div>
        <div v-for="row in visibleRows" :key="row.date" class="at-day" :class="{ rest: row.kind === 'rest', conflict: row.kind === 'conflict' }">
          <div class="d"><b>{{ row.date }}</b> <span class="muted">{{ row.week }}</span></div>
          <template v-if="row.kind === 'work'">
            <div class="at-mid">
              <div class="at-modes" role="group" :aria-label="`${row.label}怎么请`">
                <button v-for="mode in MODES" :key="mode.key" type="button" class="at-m" :class="{ on: row.day.mode === mode.key }" :aria-pressed="row.day.mode === mode.key" :disabled="!modeAvailable(row.day, mode.key)" :title="mode.title" @click="setMode(row.day, mode.key)">{{ mode.label }}</button>
              </div>
              <div v-if="row.day.mode === 'custom'" class="at-cust">
                <span class="at-step">
                  <button type="button" aria-label="减 0.5 小时" @click="bump(row.day, -0.5)">−</button>
                  <b class="num">{{ numText(row.day.hours) }}</b>
                  <button type="button" aria-label="加 0.5 小时" @click="bump(row.day, 0.5)">＋</button>
                </span>
                <span class="muted">小时（每次 0.5，这天最多 {{ numText(customCap(row.day)) }}）</span>
              </div>
              <div v-if="slotNote(row.day)" class="at-hint">{{ slotNote(row.day) }}</div>
              <div v-if="dayNote(row.day)" class="at-hint">{{ dayNote(row.day) }}</div>
            </div>
            <div class="at-hours num"><b>{{ numText(row.day.hours) }}</b> 小时</div>
          </template>
          <span v-else-if="row.kind === 'rest'" class="muted">休息日，不计</span>
          <span v-else class="x">{{ row.day.conflict.text }}，不能重复申请</span>
        </div>
      </div>

      <div class="at-sec">
        <div class="lab">事由</div>
        <textarea v-model="form.reason" class="at-area" rows="3" placeholder="简单写一下原因，主管审批时会看到，例如：陪家人到外地就医"></textarea>
        <label class="at-subject muted">主题（自动生成，可以改）<input v-model="form.subject" class="at-input" :placeholder="subjectHint" maxlength="120" /></label>
      </div>
    </section>

    <aside class="panel at-sumcard" aria-label="本次申请汇总">
      <div>
        <div class="muted">本次申请</div>
        <div class="at-big"><span class="n">{{ summary.big }}</span><span>小时</span><span class="muted">{{ summary.breakdown || '还没选时段' }}</span></div>
        <div v-if="summary.detail" class="muted">{{ summary.detail }}</div>
      </div>
      <div class="at-sumblock">
        <div class="muted">通过后的影响</div>
        <div v-for="line in summary.lines" :key="line.label" class="at-line2"><span>{{ line.label }}</span><b class="num">{{ line.value }}</b></div>
        <div v-if="summary.blocked && form.from && form.to" class="at-impact warn">{{ summary.blocked }}</div>
        <div v-else-if="summary.note" class="muted">{{ summary.note }}</div>
      </div>
      <div class="at-sumblock">
        <div class="muted">审批路线（自动带出）</div>
        <ol v-if="route?.steps?.length" class="at-route">
          <li v-for="step in route.steps" :key="step.step_index"><i>{{ step.step_index }}</i><b>{{ step.approvers.map((person) => person.name).join(' / ') || '待指定' }}</b><span class="muted">{{ stepRole(step.label) }}</span></li>
        </ol>
        <div v-else-if="route?.error" class="err">{{ route.error }}</div>
        <div v-else class="muted">审批路线加载中…</div>
        <div v-if="route?.copied_to?.length" class="muted">抄送：{{ route.copied_to.map((item) => item.label || item.name).join('、') }}</div>
      </div>
      <div v-if="error" class="err" role="alert">{{ error }}</div>
      <div v-if="message" class="ok" role="status">{{ message }}</div>
      <div class="at-submit">
        <button type="button" class="btn pri lg" :disabled="cannotSubmit" :title="whyNot" @click="save(false)">{{ busy ? '提交中…' : '提交申请' }}</button>
        <button type="button" class="btn" :disabled="busy" @click="save(true)">{{ editing ? '保存修改' : '保存草稿' }}</button>
        <button type="button" class="btn" :disabled="busy" @click="emit('cancel')">取消</button>
        <div v-if="editing" class="muted">正在编辑草稿：{{ savedName }}</div>
      </div>
    </aside>
  </div>
</template>
