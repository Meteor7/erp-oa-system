<script setup>
// 单据详情：轮到你审批时操作条在最上面（驳回必须写意见，带着"驳回"从首页 / 列表过来时光标直接在意见框里）；
// 时间、时长、逐日明细、通过后的影响放在最显眼的位置；审批进度有姓名、岗位、时间和意见，操作记录默认收起。
import { computed, nextTick, onMounted, ref } from 'vue';
import {
  STALE_STEP, api, backLabel, createLatest, dayChip, departmentLabel, effectRows, kindOf, labelOfType, newLocation, numText, rangeText,
  rejectionOf, requestTitle, rowDays, rowLabel, stamp, statusTag, stepRole, stepStates, totalOf, weekLabel, workedSpan,
} from '../../lib/attendanceView.js';

const props = defineProps({
  name: { type: String, required: true },
  origin: { type: Object, default: () => ({ kind: '' }) },
  rejectMode: { type: Boolean, default: false },
});
const emit = defineEmits(['home', 'back', 'navigate', 'loaded', 'changed']);

const data = ref(null);
const loading = ref(false);
const busy = ref(false);
const error = ref('');
const message = ref('');
const hint = ref('');
const note = ref('');
const noteError = ref(false);
const target = ref('applicant');
const noteBox = ref(null);
const latest = createLatest();

const request = computed(() => data.value?.request || null);
const names = computed(() => data.value?.names || {});
const steps = computed(() => stepStates(request.value, names.value));
const days = computed(() => rowDays(request.value || {}));
const tag = computed(() => (request.value ? statusTag(request.value) : null));
const kind = computed(() => (request.value ? kindOf(request.value) : null));
const returned = computed(() => (request.value ? rejectionOf(request.value) : null));
const overtime = computed(() => request.value?.request_type === '加班申请');
const hours = computed(() => numText(totalOf(request.value || {})));
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

function who(user) {
  const key = String(user || '').toLowerCase();
  return names.value[key] || key.split('@')[0];
}

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
  } catch (failure) {
    if (!latest.isCurrent(token)) return;
    data.value = null;
    error.value = String(failure?.message || failure || '加载失败');
  } finally {
    if (latest.isCurrent(token)) loading.value = false;
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
    await load();
    emit('changed');
  } catch (failure) {
    error.value = String(failure?.message || failure || '处理失败');
    if (STALE_STEP.test(error.value)) await load();
  } finally {
    busy.value = false;
  }
}

async function withdraw() {
  if (!window.confirm('撤回后这张申请会退回草稿，占用的额度会释放。确定撤回吗？')) return;
  busy.value = true;
  error.value = '';
  try {
    await api.withdraw(props.name);
    message.value = '已撤回，额度已释放';
    await load();
    emit('changed');
  } catch (failure) {
    error.value = String(failure?.message || failure || '撤回失败');
  } finally {
    busy.value = false;
  }
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
  <div class="at-page">
    <div class="crumb">
      <button type="button" class="link" @click="emit('home')">考勤中心</button> ›
      <template v-if="hasOrigin"><button type="button" class="link" @click="emit('back')">{{ backLabel(origin) }}</button> › </template>{{ name }}
    </div>
    <div v-if="error" class="banner err" role="alert">{{ error }}</div>
    <div v-if="message" class="banner ok" role="status">{{ message }}</div>
    <div v-if="hint && !message" class="banner info" role="status">{{ hint }}</div>
    <div v-if="loading && !request" class="panel empty">正在加载…</div>
    <div v-else-if="!request && !loading" class="panel empty">找不到这张申请（{{ name }}），可能没有查看权限。</div>

    <template v-if="request">
      <div class="at-title">
        <span :class="['at-av', 'kind', 'big', kind.tone]">{{ kind.label }}</span>
        <div class="grow-col">
          <h3>{{ requestTitle(request) }} · {{ hours }} 小时</h3>
          <div class="muted">{{ request.employee_name }} · {{ departmentLabel(request.department) }} · {{ request.name }}<template v-if="request.submitted_on || request.creation"> · {{ stamp(request.submitted_on || request.creation) }} 提交</template></div>
        </div>
        <span :class="['at-tag', 'lg', tag.tone]">{{ statusLine }}</span>
      </div>

      <section v-if="request.can_act" class="panel at-act" aria-label="审批操作">
        <div><b>轮到你审批</b><div class="muted">{{ stepText }}</div></div>
        <label class="at-note">
          <span class="muted">审批意见（驳回时必填）</span>
          <textarea ref="noteBox" v-model="note" rows="2" maxlength="1000" placeholder="例如：请补充具体原因" :aria-invalid="noteError" @input="noteError = false"></textarea>
          <span v-if="noteError" class="err">驳回必须写意见</span>
        </label>
        <div class="at-act-btns">
          <select v-if="request.rejection_targets?.length" v-model="target" aria-label="驳回给谁" class="cell">
            <option v-for="item in request.rejection_targets" :key="item.target" :value="item.target">驳回至：{{ item.label }}</option>
          </select>
          <button type="button" class="btn danger" :disabled="busy" @click="act('reject')">驳回</button>
          <button type="button" class="btn pri lg" :disabled="busy" @click="act('approve')">同意</button>
        </div>
      </section>

      <section v-if="request.can_withdraw && !isDraft" class="panel at-strip">
        <span>这张申请还在审批中，你可以撤回。</span>
        <button type="button" class="btn at-right" :disabled="busy" @click="withdraw">撤回申请</button>
      </section>
      <section v-else-if="['已完成', '已通过'].includes(request.workflow_status)" class="panel at-strip muted">已批准的请假、加班、调休暂不能撤回，需要取消请联系人事。</section>

      <section v-if="isDraft && returned" class="banner err at-strip-banner">
        被退回：{{ who(returned.actor) }}<template v-if="returned.time"> · {{ stamp(returned.time) }}</template>：{{ returned.note || '请修改后重新提交' }}
        <button type="button" class="btn sm at-right" @click="edit">修改后重新提交</button>
      </section>
      <section v-else-if="isDraft" class="panel at-strip">
        <span>这是一张草稿，还没提交。</span>
        <button type="button" class="btn pri at-right" @click="edit">继续填写</button>
      </section>

      <div class="at-cols">
        <div class="at-col">
          <section class="panel flush" aria-label="申请信息">
            <div class="at-hd"><b>申请信息</b></div>
            <div class="at-info">
              <div><span class="k">申请人</span>{{ request.employee_name }} · {{ departmentLabel(request.department) }}</div>
              <div><span class="k">类型</span>{{ kind.text }}</div>
              <div><span class="k">时间</span>{{ rangeText(span.from, span.to) }}<span class="muted"> {{ weekLabel(span.from) }}<template v-if="span.to !== span.from"> 至 {{ weekLabel(span.to) }}</template></span></div>
              <div><span class="k">合计</span><b class="num">{{ hours }}</b> 小时</div>
              <div class="wide"><span class="k">事由</span><span class="at-reason">{{ request.reason || '（没有写事由）' }}</span></div>
              <div v-if="request.attachments?.length" class="wide"><span class="k">附件</span><a v-for="file in request.attachments" :key="file.name" :href="file.file_url" target="_blank" rel="noopener" class="at-file">{{ file.file_name }}</a></div>
            </div>
          </section>

          <section class="panel flush" aria-label="逐日明细">
            <div class="at-hd"><b>逐日明细</b><span class="muted">{{ dayHint }}</span></div>
            <div class="tbl narrow">
              <table>
                <thead><tr><th>日期</th><th>星期</th><th>时段</th><th class="r">小时</th></tr></thead>
                <tbody>
                  <tr v-for="day in days" :key="day.work_date">
                    <td class="num">{{ day.work_date }}</td>
                    <td>{{ weekLabel(day.work_date) }}</td>
                    <td><span :class="['at-dchip', dayChip(day, overtime).mode]">{{ overtime ? '加班' : dayChip(day).label.split(' ')[0] }}</span></td>
                    <td class="r num">{{ numText(day.hours) }}</td>
                  </tr>
                  <tr v-if="!days.length"><td colspan="4" class="empty">没有逐日明细</td></tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <div class="at-col">
          <section class="panel flush" aria-label="通过后的影响">
            <div class="at-hd"><b>通过后的影响</b></div>
            <div class="at-eff">
              <div v-for="row in effect" :key="row.label">
                <div class="at-eff-line"><span>{{ row.label }}</span><b class="num">{{ row.value }}</b></div>
                <div class="muted">{{ row.note }}</div>
              </div>
            </div>
          </section>

          <section class="panel flush" aria-label="审批进度">
            <div class="at-hd"><b>审批进度</b></div>
            <div class="at-tl">
              <div v-for="(item, index) in timeline" :key="item.key" :class="['tl', item.cls]">
                <div class="rail"><i></i><span v-if="index < timeline.length - 1"></span></div>
                <div class="body"><b>{{ item.who }} <span class="muted">{{ item.role }} · {{ item.sub }}</span></b><span v-if="item.note" class="note">{{ item.note }}</span></div>
              </div>
              <div v-if="!timeline.length" class="muted">还没有提交审批</div>
              <div v-if="request.copied_to?.length" class="muted">抄送：{{ request.copied_to.map((item) => item.label || item.user).join('、') }}</div>
              <details v-if="request.operation_log?.length" class="at-log">
                <summary>操作记录（{{ request.operation_log.length }}）</summary>
                <ol>
                  <li v-for="(event, index) in [...request.operation_log].reverse()" :key="index" class="num">{{ stamp(event.timestamp || event.acted_on) }} · {{ event.action }} · {{ who(event.details?.actor || event.actor || event.user) }}<template v-if="event.note"> · {{ event.note }}</template></li>
                </ol>
              </details>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
