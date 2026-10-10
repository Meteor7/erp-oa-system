<script setup>
// 新建请假 / 加班 / 调休（也用来继续填写草稿、修改被退回的申请）：单独一页，分三步：申请什么 → 哪几天 → 事由。
// 请假和调休：在月历上点开始日和结束日，每一天选 全天 8 小时 / 上午 3 小时 / 下午 5 小时 / 自定义小时（每次 0.5）/ 不请；
// 加班：点日期（可勾"跨多天"），按小时填（每次 0.5）。右边实时汇总本次申请、对额度和月度上限的影响和审批路线。
// 页面里换类型会清掉类型相关的内容（假别、每天怎么请、小时数），日期和事由保留。
import { computed, reactive, ref, watch } from 'vue';
import {
  COMP_RULE, HOURS_STEP, LEAVE_RULES, LEAVE_RULE_DEFAULT, MAX_OVERTIME_HOURS, OVERTIME_RULE, TYPES, api, buildFields, createLatest, customCap,
  dayNote, dayRows, formSummary, isoDate, labelOfType, mergeDays, modeAvailable, modeOfHours, numText, pickMode, slotNote, stepHours, stepRole,
  subjectFor, DAY_RULE_TEXT,
} from '../../lib/attendanceView.js';
import { infoMap, monthGrid, monthOf, pickRange, shiftMonth } from '../../lib/attendanceFlow.js';
import AttendancePicker from './AttendancePicker.vue';

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
const TYPE_KIND = { 请假申请: 'personal', 加班申请: 'ot', 调休申请: 'comp' };

const today = isoDate(new Date());
const form = reactive({ leaveType: '事假', from: '', to: '', days: [], subject: '', reason: '' });
const multiDay = ref(false);
const awaiting = ref(false);
const month = ref(monthOf(today));
const monthInfo = ref(null);
const savedName = ref('');
const snapshot = ref('');
const busy = ref(false);
const loadingDays = ref(false);
const loadingDraft = ref(false);
const message = ref('');
const error = ref('');
const latest = createLatest();
const draftLatest = createLatest();
const monthLatest = createLatest();
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
  if (!form.from || !form.to) return '请先在月历上选开始和结束日期';
  if (loadingDays.value) return '正在计算每一天…';
  return summary.value.blocked;
});
// 换类型不算"改过"（日期和事由原样保留，类型相关的内容本来就是空的）。
const stateKey = computed(() => JSON.stringify([form.leaveType, form.from, form.to, form.days.map((day) => [day.work_date, Number(day.hours)]), form.subject, form.reason]));
// 每一天还在计算时不显示逐日行（否则会先闪一下"休息日"）。
const visibleRows = computed(() => (form.days.length || !loadingDays.value ? rows.value : []));
const editing = computed(() => Boolean(savedName.value));
const hasDates = computed(() => Boolean(form.from && form.to));

// 类型卡片和假别上的提示：还剩多少额度。
const typeNote = (type) => ({
  请假申请: '事假 / 病假 / 年假等', 加班申请: '加班换调休额度',
  调休申请: props.home?.comp ? `用加班额度，剩 ${numText(props.home.comp.available_hours)} 小时` : '用加班额度',
}[type]);
function leaveNote(item) {
  if (item === '年假' && props.home?.annual) return `剩 ${numText((props.home.annual.available_hours || 0) / 8)} 天`;
  if (item === '事假' && props.home?.month?.leave_days_by_type?.事假) return `本月已请 ${numText(props.home.month.leave_days_by_type.事假 * 8)} 小时`;
  return '';
}

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
  awaiting.value = false;
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

// 月历上这个月哪些日子能选、哪些已经被占：按当前类型取这个月的可填日子（取不到就都能点，提交时服务端仍会校验）。
async function loadMonth() {
  const grid = monthGrid(month.value);
  const token = monthLatest.begin();
  const type = props.requestType;
  try {
    const data = await api.options(type, grid.from, grid.to);
    if (monthLatest.isCurrent(token) && type === props.requestType) monthInfo.value = infoMap(data?.days);
  } catch {
    if (monthLatest.isCurrent(token)) monthInfo.value = null;
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
    awaiting.value = false;
    if (form.from) month.value = monthOf(form.from);
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
watch([month, () => props.requestType], loadMonth, { immediate: true });

// 页面里换类型：旧类型的假别、每天怎么请、主题清掉，日期和事由留着；在途的请求作废，按新类型重新算每一天。
watch(() => props.requestType, () => {
  latest.begin();
  draftLatest.begin();
  Object.assign(form, { leaveType: '事假', days: [], subject: '' });
  multiDay.value = overtime.value && Boolean(form.from) && form.from !== form.to;
  awaiting.value = false;
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

function pickDay(date) {
  const next = pickRange({ from: form.from, to: form.to, awaiting: awaiting.value }, date, { multi: !overtime.value || multiDay.value });
  awaiting.value = next.awaiting;
  form.from = next.from;
  form.to = next.to;
}

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
  <div class="af-grid">
    <div class="af-main">
      <section class="ac-panel af-sec done" :aria-label="meta.title">
        <div class="af-fh"><span class="n">1</span><h2>申请什么</h2></div>
        <div class="af-types" role="group" aria-label="申请类型">
          <button v-for="type in types" :key="type" type="button" class="af-tc" :aria-pressed="type === requestType" :disabled="editing && type !== requestType" :title="editing && type !== requestType ? '这张草稿的类型不能改，要换类型请另外新建' : ''" @click="type !== requestType && emit('switch-type', TYPES[type].label)">
            <b><i :class="'k-' + TYPE_KIND[type]"></i>{{ TYPES[type].label }}</b><span class="ac-note">{{ typeNote(type) }}</span>
          </button>
        </div>
        <div v-if="requestType === '请假申请'" class="af-pills" role="group" aria-label="假别">
          <button v-for="item in leaveTypes" :key="item" type="button" class="af-pill" :aria-pressed="form.leaveType === item" @click="form.leaveType = item">{{ item }}<small v-if="leaveNote(item)">{{ leaveNote(item) }}</small></button>
        </div>
        <div class="af-rule">{{ rule }}</div>
      </section>

      <section :class="['ac-panel', 'af-sec', { done: hasDates }]">
        <div class="af-fh">
          <span class="n">2</span><h2>{{ overtime ? '哪一天' : '哪几天' }}</h2>
          <span class="ac-note">{{ overtime ? '按实际小时数填，可以选休息日' : '先点开始日，再点结束日；只请一天点一次' }}</span>
          <label v-if="overtime" class="af-multi"><input v-model="multiDay" type="checkbox" /> 跨多天</label>
        </div>
        <div class="af-datebox">
          <AttendancePicker :month="month" :from="form.from" :to="form.to" :info="monthInfo" :overtime="overtime" :today="today" @pick="pickDay" @shift="(delta) => (month = shiftMonth(month, delta))" />
          <div class="af-days">
            <template v-if="overtime">
              <div class="ac-note af-lab">加班小时数</div>
              <div v-if="!visibleRows.length" class="ac-note">{{ loadingDays || loadingDraft ? '正在计算每一天…' : '先在月历上选日期' }}</div>
              <div v-for="row in visibleRows" :key="row.date" :class="['af-day', 'ot', { solo: visibleRows.length === 1, conflict: row.kind === 'conflict' }]">
                <div v-if="visibleRows.length > 1" class="d"><b>{{ row.date }}</b> <span class="ac-note">{{ row.week }}</span></div>
                <template v-if="row.kind === 'ot'">
                  <span class="af-step">
                    <button type="button" aria-label="减 0.5 小时" @click="bumpOvertime(row.day, -0.5)">−</button>
                    <b>{{ numText(row.day.hours) }}</b>
                    <button type="button" aria-label="加 0.5 小时" @click="bumpOvertime(row.day, 0.5)">＋</button>
                  </span>
                  <span class="ac-note">小时（每次 0.5，每天最多 24 小时<template v-if="row.day.max_hours < MAX_OVERTIME_HOURS">；这天最多还能填 {{ numText(row.day.max_hours) }} 小时</template>）</span>
                </template>
                <span v-else-if="row.kind === 'conflict'" class="af-x">{{ row.day.conflict.text }}，不能重复申请</span>
              </div>
            </template>
            <template v-else>
              <div class="ac-note af-lab">每一天怎么请 · {{ DAY_RULE_TEXT }}</div>
              <div v-if="!visibleRows.length" class="ac-note">{{ loadingDays || loadingDraft ? '正在计算每一天…' : '选好日期后，这里按天选全天、上午、下午或自定义小时' }}</div>
              <div v-for="row in visibleRows" :key="row.date" :class="['af-day', { rest: row.kind === 'rest', conflict: row.kind === 'conflict' }]">
                <div class="d"><b>{{ row.date }}</b> <span class="ac-note">{{ row.week }}</span></div>
                <template v-if="row.kind === 'work'">
                  <div class="mid">
                    <div class="af-modes" role="group" :aria-label="`${row.label}怎么请`">
                      <button v-for="mode in MODES" :key="mode.key" type="button" class="af-mode" :aria-pressed="row.day.mode === mode.key" :disabled="!modeAvailable(row.day, mode.key)" :title="mode.title" @click="setMode(row.day, mode.key)">{{ mode.label }}</button>
                    </div>
                    <div v-if="row.day.mode === 'custom'" class="af-cust">
                      <span class="af-step">
                        <button type="button" aria-label="减 0.5 小时" @click="bump(row.day, -0.5)">−</button>
                        <b>{{ numText(row.day.hours) }}</b>
                        <button type="button" aria-label="加 0.5 小时" @click="bump(row.day, 0.5)">＋</button>
                      </span>
                      <span class="ac-note">小时（每次 0.5，这天最多 {{ numText(customCap(row.day)) }}）</span>
                    </div>
                    <div v-if="slotNote(row.day)" class="af-hint">{{ slotNote(row.day) }}</div>
                    <div v-if="dayNote(row.day)" class="af-hint">{{ dayNote(row.day) }}</div>
                  </div>
                  <div class="hrs"><b>{{ numText(row.day.hours) }}</b> 小时</div>
                </template>
                <span v-else-if="row.kind === 'rest'" class="ac-note">休息日，不计</span>
                <span v-else class="af-x">{{ row.day.conflict.text }}，不能重复申请</span>
              </div>
            </template>
          </div>
        </div>
      </section>

      <section :class="['ac-panel', 'af-sec', { done: form.reason.trim() }]">
        <div class="af-fh"><span class="n">3</span><h2>事由</h2><span class="ac-note">申请人和审批人都会看到</span></div>
        <textarea v-model="form.reason" class="af-area" rows="3" aria-label="事由" placeholder="简单写一下原因，主管审批时会看到，例如：陪家人到外地就医"></textarea>
        <label class="af-subject ac-note">主题（自动生成，可以改）<input v-model="form.subject" class="af-input" :placeholder="subjectHint" maxlength="120" /></label>
      </section>
    </div>

    <aside class="ac-panel af-sum" aria-label="本次申请汇总">
      <div>
        <div class="ac-note">本次申请</div>
        <div class="af-big"><span class="n">{{ summary.big }}</span><span>小时</span><span class="ac-note">{{ summary.breakdown || '还没选时段' }}</span></div>
        <div v-if="summary.detail" class="ac-note">{{ summary.detail }}</div>
      </div>
      <div class="af-block">
        <div class="ac-note">通过后的影响</div>
        <div v-for="line in summary.lines" :key="line.label" class="af-ln"><span>{{ line.label }}</span><b>{{ line.value }}</b></div>
        <div v-if="summary.blocked && form.from && form.to" class="af-warn">{{ summary.blocked }}</div>
        <div v-else-if="summary.note" class="ac-note">{{ summary.note }}</div>
      </div>
      <div class="af-block">
        <div class="ac-note">审批路线（自动带出）</div>
        <ol v-if="route?.steps?.length" class="af-route">
          <li v-for="step in route.steps" :key="step.step_index"><i>{{ step.step_index }}</i><b>{{ step.approvers.map((person) => person.name).join(' / ') || '待指定' }}</b><span class="ac-note">{{ stepRole(step.label) }}</span></li>
        </ol>
        <div v-else-if="route?.error" class="af-err">{{ route.error }}</div>
        <div v-else class="ac-note">审批路线加载中…</div>
        <div v-if="route?.copied_to?.length" class="ac-note">抄送：{{ route.copied_to.map((item) => item.label || item.name).join('、') }}</div>
      </div>
      <div class="af-block">
        <div v-if="error" class="af-err" role="alert">{{ error }}</div>
        <div v-if="message" class="af-ok" role="status">{{ message }}</div>
        <div v-if="cannotSubmit && whyNot && !busy" class="af-need">{{ whyNot }}</div>
        <button type="button" class="ac-btn pri af-submit" :disabled="cannotSubmit" :title="whyNot" @click="save(false)">{{ busy ? '提交中…' : '提交申请' }}</button>
        <div class="af-two">
          <button type="button" class="ac-btn" :disabled="busy" @click="save(true)">{{ editing ? '保存修改' : '保存草稿' }}</button>
          <button type="button" class="ac-btn" :disabled="busy" @click="emit('cancel')">取消</button>
        </div>
        <div v-if="editing" class="ac-note">正在编辑草稿：{{ savedName }}</div>
      </div>
    </aside>
  </div>
</template>
