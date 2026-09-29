<script setup>
// 单据详情：审批人先看到操作条；时间、时长、通过后的影响放在最显眼的位置；审批进度是横向的，操作记录默认收起。
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { HOURS_PER_DAY, api, dayLabel, departmentLabel, modeOfHours, numText, rangeText, rejectionOf, statusPill, stepRole, stepStates, typeBadge, weekLabel, workedSpan } from '../../lib/attendanceView.js';

const props = defineProps({
  name: { type: String, required: true },
  base: { type: String, required: true },
});
const router = useRouter();

const data = ref(null);
const loading = ref(false);
const busy = ref(false);
const error = ref('');
const message = ref('');
const note = ref('');
const target = ref('applicant');

const request = computed(() => data.value?.request || null);
const names = computed(() => data.value?.names || {});
const steps = computed(() => stepStates(request.value, names.value));
const days = computed(() => (request.value?.attendance_days || []).filter((day) => Number(day.hours) > 0));
const pill = computed(() => (request.value ? statusPill(request.value) : null));
const returned = computed(() => (request.value ? rejectionOf(request.value) : null));
const overtime = computed(() => request.value?.request_type === '加班申请');
const hoursNumber = computed(() => Number(request.value?.duration_hours || 0));
const personal = computed(() => request.value?.leave_type === '事假');
const span = computed(() => workedSpan(request.value?.attendance_days, request.value?.from_date, request.value?.to_date));

function who(user) {
  const key = String(user || '').toLowerCase();
  return names.value[key] || key.split('@')[0];
}

function stamp(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '';
}

function modeText(hours) {
  const mode = modeOfHours(hours);
  return mode === 'full' ? '全天 · 8 小时' : mode === 'half' ? '半天 · 4 小时' : `${numText(hours)} 小时`;
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    data.value = await api.detail(props.name);
    target.value = data.value?.request?.rejection_targets?.[0]?.target || 'applicant';
  } catch (failure) {
    data.value = null;
    error.value = String(failure?.message || failure || '加载失败');
  } finally {
    loading.value = false;
  }
}

async function act(action) {
  error.value = '';
  message.value = '';
  if (action === 'reject' && !note.value.trim()) {
    error.value = '驳回原因必填';
    return;
  }
  busy.value = true;
  try {
    const params = { name: props.name, action, note: note.value.trim() };
    if (action === 'reject') params.reject_target = target.value || 'applicant';
    await api.act(params);
    message.value = action === 'approve' ? '已通过，转给下一步' : '已驳回';
    note.value = '';
    await load();
  } catch (failure) {
    error.value = String(failure?.message || failure || '处理失败');
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
  } catch (failure) {
    error.value = String(failure?.message || failure || '撤回失败');
  } finally {
    busy.value = false;
  }
}

function edit() {
  router.push({ path: props.base, query: { draft: props.name } });
}

onMounted(load);
watch(() => props.name, load);
</script>

<template>
  <div>
    <router-link :to="base" class="muted" style="display:inline-block;margin-bottom:10px;font-size:14px">← 返回</router-link>
    <div v-if="error" class="banner err" role="alert">{{ error }}</div>
    <div v-if="message" class="banner ok">{{ message }}</div>
    <div v-if="loading && !request" class="empty">正在加载…</div>

    <template v-if="request">
      <section v-if="request.can_act" class="at-bar-act" aria-label="审批操作">
        <div class="l"><b>轮到你审批</b><span>第 {{ request.current_step_index }} 步 · {{ stepRole(request.current_step_label) }}</span></div>
        <label>审批意见（驳回时必填）<textarea v-model="note" rows="2" placeholder="例如：请补充具体原因"></textarea></label>
        <div class="b">
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button type="button" class="btn danger" :disabled="busy" @click="act('reject')">驳回</button>
            <button type="button" class="btn pri" style="min-height:44px;padding:0 22px;font-size:15px" :disabled="busy" @click="act('approve')">通过</button>
          </div>
          <select v-if="request.rejection_targets?.length" v-model="target" aria-label="驳回给谁" class="cell">
            <option v-for="item in request.rejection_targets" :key="item.target" :value="item.target">驳回至：{{ item.label }}</option>
          </select>
        </div>
      </section>

      <section class="at-panel" style="margin-bottom:14px" aria-label="申请概要">
        <div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">
          <span class="at-badge" :class="typeBadge(request).tone" style="width:56px;height:56px;font-size:16px">{{ typeBadge(request).text }}</span>
          <div style="flex:1;min-width:200px">
            <h3 style="margin:0;font-size:22px;font-weight:700">{{ request.subject || request.request_type }}</h3>
            <div class="muted num" style="font-size:14px">{{ request.employee_name }} · {{ departmentLabel(request.department) }} · {{ request.name }}<template v-if="request.creation"> · {{ stamp(request.creation) }} 提交</template></div>
          </div>
          <span class="pill" :class="pill.tone">{{ pill.text }}</span>
        </div>

        <div v-if="returned && request.workflow_status === '草稿'" class="banner err" style="margin:0">
          被退回：{{ who(returned.actor) }}<template v-if="returned.time"> · {{ stamp(returned.time) }}</template>：{{ returned.note || '请修改后重新提交' }}
          <button type="button" class="btn sm" style="margin-left:8px" @click="edit">修改后重新提交</button>
        </div>

        <div class="at-info3">
          <div><div class="k">时间</div><div class="v">{{ rangeText(span.from, span.to) }}</div><div class="n">{{ weekLabel(span.from) }}<template v-if="span.to !== span.from"> 至 {{ weekLabel(span.to) }}</template></div></div>
          <div><div class="k">时长</div><div class="v">{{ overtime ? `${numText(hoursNumber)} 小时` : `${numText(hoursNumber / HOURS_PER_DAY)} 天 · ${numText(hoursNumber)} 小时` }}</div><div class="n">{{ request.leave_type || request.request_type }}</div></div>
          <div :class="{ warn: personal }"><div class="k">通过后的影响</div><div class="v" style="font-size:18px">{{ data.impact }}</div><div class="n">{{ personal ? '事假通过后才扣当月工时上限' : '' }}</div></div>
        </div>

        <div v-if="days.length" class="at-block">
          <div class="at-label">每天明细</div>
          <div class="at-dchips"><div v-for="day in days" :key="day.work_date"><b>{{ dayLabel(day.work_date) }} {{ weekLabel(day.work_date) }}</b><span>{{ modeText(day.hours) }}</span></div></div>
        </div>
        <div class="at-block"><div class="at-label">事由</div><div style="font-size:15px;line-height:1.7;white-space:pre-wrap">{{ request.reason || '（没有写事由）' }}</div></div>
        <div v-if="request.attachments?.length" class="at-block">
          <div class="at-label">附件</div>
          <div><a v-for="file in request.attachments" :key="file.name" :href="file.file_url" target="_blank" rel="noopener" style="margin-right:12px">{{ file.file_name }}</a></div>
        </div>
      </section>

      <section class="at-panel" aria-label="审批进度">
        <h4>审批进度</h4>
        <ol class="at-prog">
          <li v-for="(step, index) in steps" :key="index" :class="step.state">
            <div class="l"><span class="dot">{{ step.state === 'done' ? '✓' : step.state === 'stop' ? '✕' : index + 1 }}</span><span v-if="index < steps.length - 1" class="line"></span></div>
            <b>{{ step.who || '待指定' }} · {{ stepRole(step.label) }}</b>
            <span>{{ step.state === 'done' ? '已通过' : step.state === 'stop' ? '已驳回' : step.state === 'current' ? '等待中' : '未开始' }}<template v-if="step.time"> · {{ stamp(step.time) }}</template></span>
            <span v-if="step.note">意见：{{ step.note }}</span>
          </li>
        </ol>
        <div v-if="request.copied_to?.length" class="at-sub">抄送：{{ request.copied_to.map((item) => item.label || item.user).join('、') }}</div>
        <details v-if="request.operation_log?.length" class="at-sub">
          <summary style="cursor:pointer;font-weight:600">操作记录（{{ request.operation_log.length }}）</summary>
          <ol style="margin:8px 0 0;padding-left:18px;line-height:1.9">
            <li v-for="(event, index) in [...request.operation_log].reverse()" :key="index" class="num">{{ stamp(event.timestamp || event.acted_on) }} · {{ event.action }} · {{ who(event.details?.actor || event.actor || event.user) }}<template v-if="event.note"> · {{ event.note }}</template></li>
          </ol>
        </details>
        <div v-if="request.can_withdraw" class="actions"><button type="button" class="btn" :disabled="busy" @click="withdraw">撤回申请</button></div>
        <div v-else-if="['已完成', '已通过'].includes(request.workflow_status)" class="at-sub">已批准的请假、加班、调休暂不能撤回，需要取消请联系人事。</div>
      </section>
    </template>
  </div>
</template>
