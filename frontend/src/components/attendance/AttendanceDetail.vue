<script setup>
// 单据详情，两种摆法：
//   page ：单独一页。轮到你审批时操作条固定在最上面（驳回必须写意见，带着"驳回"从首页 / 列表过来时光标直接在意见框里）；
//          左边日期条、事由、逐日明细、批之前先看的影响和同期谁不在，右边审批进度和操作记录。
//   panel：列表右边的窄栏，点列表里的一行就在这里看清楚并处理（同意一步完成，驳回在下面写原因），"完整页面"进 page。
// 数据、审批、撤回、修改草稿的逻辑两种摆法共用。
import { computed, nextTick, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import {
  STALE_STEP, api, backLabel, createLatest, departmentLabel, effectRows, isTrip, kindOf, labelOfType, newLocation, numText, rangeText,
  rejectionOf, requestTitle, rowDays, sizeText, stamp, statusTag, stepRole, stepStates, totalOf, weekLabel, workedSpan, dayChip,
} from '../../lib/attendanceView.js';
import { hereAsFrom } from '../../lib/navContext.js';
import { pushTarget } from '../../lib/travelView.js';
import { lengthText } from '../../lib/attendanceFlow.js';
import { rowKind } from '../../lib/attendanceCharts.js';
import AttendanceDayStrip from './AttendanceDayStrip.vue';
import AttendanceSteps from './AttendanceSteps.vue';

const props = defineProps({
  name: { type: String, required: true },
  origin: { type: Object, default: () => ({ kind: '' }) },
  rejectMode: { type: Boolean, default: false },
  variant: { type: String, default: 'page' },
  // 列表里这一行的"批之前先看影响"（待我审批的行才有）。
  hints: { type: Array, default: () => [] },
});
const emit = defineEmits(['home', 'back', 'navigate', 'loaded', 'changed', 'open']);

const data = ref(null);
const overlap = ref(null);
const loading = ref(false);
const busy = ref(false);
const error = ref('');
const message = ref('');
const hint = ref('');
const note = ref('');
const noteError = ref(false);
const rejecting = ref(false);
const target = ref('applicant');
const noteBox = ref(null);
const latest = createLatest();
const overlapLatest = createLatest();
const route = useRoute();

const panel = computed(() => props.variant === 'panel');
const request = computed(() => data.value?.request || null);
const names = computed(() => data.value?.names || {});
const steps = computed(() => stepStates(request.value, names.value));
const days = computed(() => rowDays(request.value || {}));
const tag = computed(() => (request.value ? statusTag(request.value) : null));
const kind = computed(() => (request.value ? kindOf(request.value) : null));
const colour = computed(() => (request.value ? rowKind(request.value) : 'other'));
const returned = computed(() => (request.value ? rejectionOf(request.value) : null));
const overtime = computed(() => request.value?.request_type === '加班申请');
const trip = computed(() => isTrip(request.value));
const hours = computed(() => numText(totalOf(request.value || {})));
// 出差说天数，其余说小时；日期那一块的标题也跟着类型走。
const sizeNumber = computed(() => (trip.value ? sizeText(request.value).replace(' 天', '') : hours.value));
const sizeUnit = computed(() => (trip.value ? '天' : '小时'));
const dateTitle = computed(() => (overtime.value ? '加班日期' : trip.value ? '出差日期' : '请假日期'));
// 已通过、是我自己的出差申请：出差途中的费用在报销 / 付款里直接关联它。
const canPush = computed(() => trip.value && Boolean(data.value?.mine) && ['已完成', '已通过'].includes(request.value?.workflow_status));
const span = computed(() => workedSpan(days.value, request.value?.from_date, request.value?.to_date));
const effect = computed(() => (request.value ? effectRows(request.value, data.value?.impact) : []));
const isDraft = computed(() => request.value?.workflow_status === '草稿');
const active = computed(() => ['待审批', '待办理'].includes(request.value?.workflow_status));
const stepText = computed(() => {
  const all = request.value?.steps || [];
  return `第 ${request.value?.current_step_index || 1} 步 / 共 ${all.length || 1} 步 · ${stepRole(request.value?.current_step_label)}`;
});
const statusLine = computed(() => {
  if (!request.value || !tag.value) return '';
  if (!active.value) return tag.value.text;
  const mine = request.value.can_act;
  const step = steps.value.find((item) => item.state === 'current');
  return `${mine ? '待审批' : '审批中'} · ${mine ? '轮到你' : '等待'}（${stepRole(step?.label || request.value.current_step_label)}${!mine && step?.who ? ` ${step.who}` : ''}）`;
});
const dayHint = computed(() => (overtime.value ? '加班按小时填' : '全天 8 小时 · 上午 3 小时 · 下午 5 小时 · 自定义小时'));
const timeline = computed(() => steps.value.map((step, index) => ({
  key: `${index}-${step.label}`,
  cls: { done: 'done', current: 'now', stop: 'rejected', wait: 'todo' }[step.state],
  who: step.who || '待指定', role: stepRole(step.label), note: step.note,
  sub: { done: '已通过', stop: '已驳回', current: '等待中', wait: '未开始' }[step.state] + (step.time && step.state !== 'wait' ? ` · ${stamp(step.time)}` : ''),
})));
const hasOrigin = computed(() => props.origin?.kind === 'list');
const tone = computed(() => ({ ok: 'ok', warn: 'warn', bad: 'bad', info: 'info' }[tag.value?.tone] || ''));

function who(user) {
  const key = String(user || '').toLowerCase();
  return names.value[key] || key.split('@')[0];
}

const dateText = (date) => `${String(date).slice(5, 10).replace('-', '/')} ${weekLabel(date)}`;
const overlapWhen = (person) => (person.dates.length > 1 ? `${dateText(person.dates[0])} – ${dateText(person.dates[person.dates.length - 1])}` : dateText(person.dates[0]));

async function load() {
  const token = latest.begin();
  loading.value = true;
  error.value = '';
  try {
    const result = await api.detail(props.name);
    if (!latest.isCurrent(token)) return;
    data.value = result;
    target.value = result?.request?.rejection_targets?.[0]?.target || 'applicant';
    emit('loaded', result?.request);
    loadOverlap(result?.request);
  } catch (failure) {
    if (!latest.isCurrent(token)) return;
    data.value = null;
    error.value = String(failure?.message || failure || '加载失败');
  } finally {
    if (latest.isCurrent(token)) loading.value = false;
  }
}

// 轮到我审批的请假 / 调休：同部门同期谁不在（名字由服务端按我的身份决定给不给）。
async function loadOverlap(row) {
  const token = overlapLatest.begin();
  overlap.value = null;
  if (!row?.can_act || row.request_type === '加班申请') return;
  try {
    const result = await api.overlap(props.name);
    if (overlapLatest.isCurrent(token)) overlap.value = result;
  } catch {
    if (overlapLatest.isCurrent(token)) overlap.value = null;
  }
}

async function act(action) {
  error.value = '';
  message.value = '';
  noteError.value = false;
  hint.value = '';
  if (action === 'reject' && !note.value.trim()) {
    noteError.value = true;
    noteBox.value?.focus();
    return;
  }
  busy.value = true;
  try {
    // 带着页面上看到的那一步：单据已经被别人处理过时服务端拒绝，页面重新加载最新的一步。
    const params = { name: props.name, action, note: note.value.trim(), expected_step_key: request.value?.current_step_key || '' };
    if (action === 'reject') params.reject_target = target.value || 'applicant';
    await api.act(params);
    message.value = action === 'approve' ? '已同意，转给下一步' : '已驳回';
    note.value = '';
    rejecting.value = false;
    await load();
    emit('changed');
  } catch (failure) {
    error.value = String(failure?.message || failure || '处理失败');
    if (STALE_STEP.test(error.value)) await load();
  } finally {
    busy.value = false;
  }
}

async function startReject() {
  rejecting.value = true;
  noteError.value = false;
  await nextTick();
  noteBox.value?.focus();
}

async function withdraw() {
  if (!window.confirm(trip.value ? '撤回后这张申请会退回草稿。确定撤回吗？' : '撤回后这张申请会退回草稿，占用的额度会释放。确定撤回吗？')) return;
  busy.value = true;
  error.value = '';
  try {
    await api.withdraw(props.name);
    message.value = trip.value ? '已撤回' : '已撤回，额度已释放';
    await load();
    emit('changed');
  } catch (failure) {
    error.value = String(failure?.message || failure || '撤回失败');
  } finally {
    busy.value = false;
  }
}

// 下推报销 / 付款：目标页先弹出"确定要创建草稿吗"，确认后才生成；from 让它取消时回到这里。
function push(kind) {
  emit('navigate', { path: pushTarget(kind), query: { source: props.name, from: hereAsFrom(route.path, route.query) } });
}

// 草稿 / 被退回：回到新建页继续填，类型用这张申请自己的。
function edit() {
  emit('navigate', newLocation({ type: labelOfType(request.value.request_type), draft: props.name }, props.origin));
}

onMounted(async () => {
  await load();
  if (props.rejectMode && request.value?.can_act) {
    hint.value = '驳回需要写意见，请在下面的审批意见里填写原因。';
    await nextTick();
    noteBox.value?.focus();
  }
});
</script>

<template>
  <!-- 列表右边的窄栏 -->
  <div v-if="panel" class="ac-panel af-panel" aria-label="申请详情">
    <div v-if="loading && !request" class="ac-empty">正在加载…</div>
    <div v-else-if="!request" class="ac-empty">{{ error || '找不到这张申请，可能没有查看权限。' }}</div>
    <template v-else>
      <section class="af-ps">
        <div class="af-top">
          <span :class="['ac-av', 'big', colour]">{{ (request.employee_name || '').slice(-2) }}</span>
          <div class="grow"><h2>{{ request.employee_name }} · {{ kind.text }}</h2><div class="ac-note">{{ departmentLabel(request.department) }} · {{ request.name }}</div></div>
          <button type="button" class="ac-link" @click="emit('open')">完整页面 →</button>
        </div>
        <div class="af-facts">
          <div><span class="k">时间</span><span class="v">{{ rangeText(span.from, span.to) }}</span></div>
          <div><span class="k">合计</span><span class="v">{{ sizeNumber }}<small> {{ sizeUnit }}</small></span></div>
          <div v-if="trip"><span class="k">地点</span><span class="v small">{{ request.travel_destination || '—' }}</span></div>
          <div><span class="k">提交</span><span class="v small">{{ stamp(request.submitted_on || request.creation).slice(5) }}</span></div>
        </div>
      </section>
      <section class="af-ps">
        <div class="af-sec2">{{ dateTitle }} <span>{{ lengthText(request) }}</span></div>
        <AttendanceDayStrip :row="request" />
        <div v-if="trip" class="ac-note">所属项目：{{ request.project || '非项目' }}</div>
        <div class="af-reason">{{ request.reason || '（没有写事由）' }}</div>
        <div v-if="request.attachments?.length" class="ac-note"><a v-for="file in request.attachments" :key="file.name" :href="file.file_url" target="_blank" rel="noopener" class="ac-link">{{ file.file_name }}</a></div>
      </section>
      <section v-if="request.can_act || hints.length" class="af-ps">
        <div v-if="hints.length"><div class="af-sec2">批之前先看影响</div><div class="af-tags"><span v-for="(item, index) in hints" :key="index" :class="['ac-tag', item.tone]">{{ item.text }}</span></div></div>
        <div v-else-if="effect.length"><div class="af-sec2">通过后的影响</div><div v-for="row in effect" :key="row.label" class="af-ln"><span>{{ row.label }}</span><b>{{ row.value }}</b></div></div>
        <div v-if="overlap?.visible" class="af-mates">
          <div class="af-sec2">同期谁不在 <span>只有部门主管和人事、管理层能看到</span></div>
          <div v-for="person in overlap.people" :key="person.name" class="m"><span :class="['ac-av', person.kind]">{{ (person.name || '').slice(-2) }}</span><b>{{ person.name }}</b><span><span :class="['ac-tag', person.kind]">{{ { annual: '年假', personal: '事假', sick: '病假', comp: '调休', other: '其他假', trip: '出差' }[person.kind] }}</span> <span class="ac-note">{{ overlapWhen(person) }}{{ person.pending ? '（审批中）' : '' }}</span></span></div>
          <div v-if="!overlap.people.length" class="ac-note">这几天部门里没有人请假或调休。</div>
        </div>
      </section>
      <section class="af-ps">
        <div class="af-sec2">审批进度</div>
        <AttendanceSteps :items="timeline" />
      </section>

      <div v-if="error" class="af-ps"><div class="af-err" role="alert">{{ error }}</div></div>
      <div v-if="message" class="af-ps"><div class="af-ok" role="status">{{ message }}</div></div>
      <section v-if="request.can_act" class="af-ps af-actions" aria-label="审批操作">
        <template v-if="rejecting">
          <div class="af-sec2">驳回原因 <span>必填，申请人会看到</span></div>
          <textarea ref="noteBox" v-model="note" rows="2" maxlength="1000" placeholder="例如：请补充具体原因" aria-label="驳回原因" :aria-invalid="noteError" @input="noteError = false"></textarea>
          <div v-if="noteError" class="af-err" role="alert">驳回必须写意见</div>
          <div class="btns">
            <select v-if="request.rejection_targets?.length" v-model="target" aria-label="驳回给谁"><option v-for="item in request.rejection_targets" :key="item.target" :value="item.target">驳回至：{{ item.label }}</option></select>
            <button type="button" class="ac-btn" :disabled="busy" @click="rejecting = false">取消</button>
            <button type="button" class="ac-btn danger" :disabled="busy" @click="act('reject')">确认驳回</button>
          </div>
        </template>
        <div v-else class="btns"><span class="ac-note grow">{{ stepText }}</span><button type="button" class="ac-btn danger" :disabled="busy" @click="startReject">驳回</button><button type="button" class="ac-btn pri" :disabled="busy" @click="act('approve')">同意</button></div>
      </section>
      <section v-else-if="request.can_withdraw && !isDraft" class="af-ps af-actions"><div class="btns"><span class="ac-note grow">还在审批中，可以撤回。</span><button type="button" class="ac-btn" :disabled="busy" @click="withdraw">撤回申请</button></div></section>
      <section v-else-if="isDraft && returned" class="af-ps af-actions"><div class="af-banner">被退回：{{ who(returned.actor) }}：{{ returned.note || '请修改后重新提交' }}</div><div class="btns"><button type="button" class="ac-btn pri" @click="edit">修改后重新提交</button></div></section>
      <section v-else-if="isDraft" class="af-ps af-actions"><div class="btns"><span class="ac-note grow">这是一张草稿，还没提交。</span><button type="button" class="ac-btn pri" @click="edit">继续填写</button></div></section>
      <section v-else-if="canPush" class="af-ps af-actions"><div class="af-sec2">出差途中的费用 <span>打车、住宿等，报销时直接关联这张出差申请</span></div><div class="btns"><button type="button" class="ac-btn" @click="push('claim')">发起报销</button><button type="button" class="ac-btn" @click="push('payment')">发起付款</button></div></section>
      <section v-else-if="['已完成', '已通过'].includes(request.workflow_status)" class="af-ps af-actions"><div class="ac-note">已批准的申请暂不能撤回，需要取消请联系人事。</div></section>
    </template>
  </div>

  <!-- 单独一页 -->
  <div v-else class="acx af-page">
    <div class="af-crumb">
      <button type="button" class="ac-link" @click="emit('home')">考勤中心</button> ›
      <template v-if="hasOrigin"><button type="button" class="ac-link" @click="emit('back')">{{ backLabel(origin) }}</button> › </template>{{ name }}
    </div>
    <div v-if="error" class="af-banner bad" role="alert">{{ error }}</div>
    <div v-if="message" class="af-banner ok" role="status">{{ message }}</div>
    <div v-if="hint && !message" class="af-banner" role="status">{{ hint }}</div>
    <div v-if="loading && !request" class="ac-panel ac-empty">正在加载…</div>
    <div v-else-if="!request && !loading" class="ac-panel ac-empty">找不到这张申请（{{ name }}），可能没有查看权限。</div>

    <template v-if="request">
      <div class="af-hero">
        <span :class="['ac-av', 'big', colour]">{{ (request.employee_name || '').slice(-2) }}</span>
        <div class="grow">
          <h1>{{ requestTitle(request) }} · {{ sizeNumber }} {{ sizeUnit }}</h1>
          <div class="ac-note">{{ request.employee_name }} · {{ departmentLabel(request.department) }} · {{ request.name }}<template v-if="request.submitted_on || request.creation"> · {{ stamp(request.submitted_on || request.creation) }} 提交</template></div>
        </div>
        <span :class="['ac-tag', 'af-status', tone]">{{ statusLine }}</span>
      </div>

      <section v-if="request.can_act" class="ac-panel af-bar" aria-label="审批操作">
        <div><b>轮到你审批</b><div class="ac-note">{{ stepText }}</div></div>
        <label class="af-note">
          <span class="ac-note">审批意见（驳回时必填）</span>
          <textarea ref="noteBox" v-model="note" rows="2" maxlength="1000" placeholder="例如：请补充具体原因" :aria-invalid="noteError" @input="noteError = false"></textarea>
          <span v-if="noteError" class="af-err">驳回必须写意见</span>
        </label>
        <div class="btns">
          <select v-if="request.rejection_targets?.length" v-model="target" aria-label="驳回给谁"><option v-for="item in request.rejection_targets" :key="item.target" :value="item.target">驳回至：{{ item.label }}</option></select>
          <button type="button" class="ac-btn danger" :disabled="busy" @click="act('reject')">驳回</button>
          <button type="button" class="ac-btn pri" :disabled="busy" @click="act('approve')">同意</button>
        </div>
      </section>

      <section v-if="request.can_withdraw && !isDraft" class="ac-panel af-strip2">
        <span>这张申请还在审批中，你可以撤回。</span>
        <button type="button" class="ac-btn ac-right" :disabled="busy" @click="withdraw">撤回申请</button>
      </section>
      <section v-else-if="canPush" class="ac-panel af-strip2">
        <span>出差途中的打车、住宿等费用，报销时直接关联这张出差申请。</span>
        <span class="ac-right"><button type="button" class="ac-btn pri" @click="push('claim')">发起报销</button> <button type="button" class="ac-btn" @click="push('payment')">发起付款</button></span>
      </section>
      <section v-else-if="['已完成', '已通过'].includes(request.workflow_status)" class="ac-panel af-strip2 ac-note">已批准的申请暂不能撤回，需要取消请联系人事。</section>

      <section v-if="isDraft && returned" class="af-banner bad af-row">
        被退回：{{ who(returned.actor) }}<template v-if="returned.time"> · {{ stamp(returned.time) }}</template>：{{ returned.note || '请修改后重新提交' }}
        <button type="button" class="ac-btn sm ac-right" @click="edit">修改后重新提交</button>
      </section>
      <section v-else-if="isDraft" class="ac-panel af-strip2">
        <span>这是一张草稿，还没提交。</span>
        <button type="button" class="ac-btn pri ac-right" @click="edit">继续填写</button>
      </section>

      <div class="af-pagegrid">
        <div class="af-col">
          <section class="ac-panel af-ps-wrap" aria-label="申请信息">
            <div class="af-ps">
              <div class="af-sec2">{{ dateTitle }} <span>{{ lengthText(request) }}</span></div>
              <AttendanceDayStrip :row="request" />
              <div class="af-facts">
                <div><span class="k">申请人</span><span class="v small">{{ request.employee_name }} · {{ departmentLabel(request.department) }}</span></div>
                <div><span class="k">类型</span><span class="v small">{{ kind.text }}</span></div>
                <div><span class="k">合计</span><span class="v">{{ sizeNumber }}<small> {{ sizeUnit }}</small></span></div>
                <div v-if="trip"><span class="k">所属项目</span><span class="v small">{{ request.project || '非项目' }}</span></div>
              </div>
              <div class="af-reason">{{ request.reason || '（没有写事由）' }}</div>
              <div v-if="request.attachments?.length" class="ac-note">附件：<a v-for="file in request.attachments" :key="file.name" :href="file.file_url" target="_blank" rel="noopener" class="ac-link">{{ file.file_name }}</a></div>
            </div>
            <div v-if="!trip" class="af-ps">
              <details>
                <summary>逐日明细（{{ days.length }} 天）<span class="ac-note"> {{ dayHint }}</span></summary>
                <div class="af-tblwrap">
                  <table>
                    <thead><tr><th>日期</th><th>星期</th><th>时段</th><th class="af-r">小时</th></tr></thead>
                    <tbody>
                      <tr v-for="day in days" :key="day.work_date">
                        <td>{{ day.work_date }}</td><td>{{ weekLabel(day.work_date) }}</td>
                        <td><span :class="['ac-tag', colour]">{{ overtime ? '加班' : dayChip(day).label.split(' ')[0] }}</span></td>
                        <td class="af-r">{{ numText(day.hours) }}</td>
                      </tr>
                      <tr v-if="!days.length"><td colspan="4" class="ac-empty">没有逐日明细</td></tr>
                    </tbody>
                  </table>
                </div>
              </details>
            </div>
          </section>

          <section class="ac-panel af-ps-wrap" aria-label="通过后的影响">
            <div class="af-ps">
              <div class="af-sec2">通过后的影响</div>
              <div v-for="row in effect" :key="row.label"><div class="af-ln"><span>{{ row.label }}</span><b>{{ row.value }}</b></div><div class="ac-note">{{ row.note }}</div></div>
              <div v-if="hints.length"><div class="af-sec2">批之前先看影响</div><div class="af-tags"><span v-for="(item, index) in hints" :key="index" :class="['ac-tag', item.tone]">{{ item.text }}</span></div></div>
            </div>
            <div v-if="overlap?.visible" class="af-ps af-mates">
              <div class="af-sec2">同期谁不在 <span>只有部门主管和人事、管理层能看到</span></div>
              <div v-for="person in overlap.people" :key="person.name" class="m"><span :class="['ac-av', person.kind]">{{ (person.name || '').slice(-2) }}</span><b>{{ person.name }}</b><span><span :class="['ac-tag', person.kind]">{{ { annual: '年假', personal: '事假', sick: '病假', comp: '调休', other: '其他假', trip: '出差' }[person.kind] }}</span> <span class="ac-note">{{ overlapWhen(person) }}{{ person.pending ? '（审批中）' : '' }}</span></span></div>
              <div v-if="!overlap.people.length" class="ac-note">这几天部门里没有人请假或调休。</div>
            </div>
          </section>
        </div>

        <div class="af-col">
          <section class="ac-panel af-ps-wrap" aria-label="审批进度">
            <div class="af-ps">
              <div class="af-sec2">审批进度</div>
              <AttendanceSteps :items="timeline" />
              <div v-if="request.copied_to?.length" class="ac-note">抄送：{{ request.copied_to.map((item) => item.label || item.user).join('、') }}</div>
              <details v-if="request.operation_log?.length" class="af-log">
                <summary>操作记录（{{ request.operation_log.length }}）</summary>
                <ol>
                  <li v-for="(event, index) in [...request.operation_log].reverse()" :key="index">{{ stamp(event.timestamp || event.acted_on) }} · {{ event.action }} · {{ who(event.details?.actor || event.actor || event.user) }}<template v-if="event.note"> · {{ event.note }}</template></li>
                </ol>
              </details>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
