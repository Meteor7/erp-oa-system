<script setup>
// 新建出差申请（也用来继续填写草稿、修改被退回的申请）：单独一页，分三步：申请什么 → 去哪、哪几天 → 事由。
// 出差只批"该不该去"，没有小时和额度；日期在月历上点出发日和返回日（周末也能选），天数按出发、返回日期含当天算。
// 提交后的审批路线（直属主管 → 副总经理）取自服务端；出差途中的费用在报销、付款里直接关联这张申请。
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { REQUEST_TRIP, TYPES, api, createLatest, isoDate, labelOfType, stepRole } from '../../lib/attendanceView.js';
import { monthOf, pickRange, shiftMonth } from '../../lib/attendanceFlow.js';
import { emptyTravelForm, showMissing, travelBlockers, travelFormFrom, tripDays } from '../../lib/travelView.js';
import AttendancePicker from './AttendancePicker.vue';

const props = defineProps({
  draftName: { type: String, default: '' },
  route: { type: Object, default: null },
  types: { type: Array, default: () => ['请假申请', '加班申请', '调休申请', '出差申请'] },
});
const emit = defineEmits(['switch-type', 'draft-type', 'draft-saved', 'submitted', 'cancel']);

const TYPE_KIND = { 请假申请: 'personal', 加班申请: 'ot', 调休申请: 'comp', 出差申请: 'trip' };
const TYPE_NOTE = { 请假申请: '事假 / 病假 / 年假等', 加班申请: '加班换调休额度', 调休申请: '用加班额度', 出差申请: '出差，报销、付款可以直接关联' };

const today = isoDate(new Date());
const form = reactive(emptyTravelForm());
const awaiting = ref(false);
const month = ref(monthOf(today));
const projects = ref([]);
const savedName = ref('');
const snapshot = ref('');
const attempted = ref(false);
const busy = ref(false);
const loadingDraft = ref(false);
const message = ref('');
const error = ref('');
const draftLatest = createLatest();

const days = computed(() => tripDays(form.travel_start_date, form.travel_end_date));
// 主题不填就自动生成："上海出差 3 天"。
const autoSubject = computed(() => (form.travel_destination.trim() ? `${form.travel_destination.trim()}出差${days.value ? ` ${days.value} 天` : ''}` : ''));
const payload = () => ({ ...form, subject: form.subject.trim() || autoSubject.value });
const blockers = computed(() => travelBlockers(payload()));
const missingVisible = computed(() => showMissing(form, attempted.value));
const editing = computed(() => Boolean(savedName.value));
const hasDates = computed(() => Boolean(form.travel_start_date && form.travel_end_date));
const whenText = computed(() => (hasDates.value
  ? `${form.travel_start_date.slice(5).replace('-', ' 月 ')} 日 – ${form.travel_end_date.slice(5).replace('-', ' 月 ')} 日${form.travel_destination ? ' · ' + form.travel_destination : ''}`
  : (form.travel_destination || '选好日期后显示')));
const stateKey = computed(() => JSON.stringify(form));

function markClean() {
  snapshot.value = stateKey.value;
}
markClean();

// 表单有没有改过没保存的内容（刚载入的草稿、刚保存的草稿都算没改）。
function dirty() {
  return stateKey.value !== snapshot.value;
}

function resetAll() {
  Object.assign(form, emptyTravelForm());
  awaiting.value = false;
  savedName.value = '';
  attempted.value = false;
  markClean();
}

function pickDay(date) {
  const next = pickRange({ from: form.travel_start_date, to: form.travel_end_date, awaiting: awaiting.value }, date, { multi: true });
  awaiting.value = next.awaiting;
  form.travel_start_date = next.from;
  form.travel_end_date = next.to;
}

async function loadProjects() {
  try {
    projects.value = ((await api.projects()) || []).map((row) => row.name || row);
  } catch {
    projects.value = [];
  }
}

// 继续填写草稿 / 修改被退回的申请：取这张申请，填进表单；类型和页面上的不一样时请页面换成它自己的类型。
async function loadDraft(name) {
  const token = draftLatest.begin();
  loadingDraft.value = true;
  error.value = '';
  // 先记住草稿编号：即使后面加载失败，保存时也是更新这张草稿，不会另存一份。
  savedName.value = name;
  try {
    const request = (await api.detail(name))?.request;
    if (!draftLatest.isCurrent(token)) return;
    if (!request || request.workflow_status !== '草稿') {
      error.value = '这张申请已经提交，不能再修改。';
      return;
    }
    if (request.request_type !== REQUEST_TRIP) {
      savedName.value = '';
      emit('draft-type', labelOfType(request.request_type));
      return;
    }
    Object.assign(form, travelFormFrom(request));
    awaiting.value = false;
    if (form.travel_start_date) month.value = monthOf(form.travel_start_date);
    markClean();
  } catch (failure) {
    if (draftLatest.isCurrent(token)) error.value = String(failure?.message || failure || '加载失败');
  } finally {
    if (draftLatest.isCurrent(token)) loadingDraft.value = false;
  }
}

watch(() => props.draftName, (name) => {
  if (name && name !== savedName.value) loadDraft(name);
}, { immediate: true });

async function save(asDraft) {
  message.value = '';
  error.value = '';
  if (!asDraft) {
    attempted.value = true;
    if (blockers.value.length) {
      error.value = `还差：${blockers.value.join('、')}`;
      return;
    }
  } else if (!form.travel_destination.trim() && !hasDates.value && !form.reason.trim() && !form.subject.trim()) {
    error.value = '先填一点内容再保存草稿';
    return;
  }
  busy.value = true;
  try {
    const doc = await api.saveTravel({ payload: JSON.stringify(payload()), name: savedName.value || undefined });
    savedName.value = doc.name;
    if (asDraft) {
      message.value = '草稿已保存';
      markClean();
      emit('draft-saved', doc.name);
      return;
    }
    await api.submitDraft(doc.name);
    const submitted = { name: doc.name, requestType: REQUEST_TRIP };
    resetAll();
    emit('submitted', submitted);
  } catch (failure) {
    error.value = String(failure?.message || failure || '提交失败');
  } finally {
    busy.value = false;
  }
}

onMounted(loadProjects);
defineExpose({ dirty });
</script>

<template>
  <div class="af-grid">
    <div class="af-main">
      <section class="ac-panel af-sec done" aria-label="新建出差申请">
        <div class="af-fh"><span class="n">1</span><h2>申请什么</h2></div>
        <div class="af-types" role="group" aria-label="申请类型">
          <button v-for="type in types" :key="type" type="button" class="af-tc" :aria-pressed="type === REQUEST_TRIP" :disabled="editing && type !== REQUEST_TRIP" :title="editing && type !== REQUEST_TRIP ? '这张草稿的类型不能改，要换类型请另外新建' : ''" @click="type !== REQUEST_TRIP && emit('switch-type', TYPES[type].label)">
            <b><i :class="'k-' + TYPE_KIND[type]"></i>{{ TYPES[type].label }}</b><span class="ac-note">{{ TYPE_NOTE[type] }}</span>
          </button>
        </div>
        <div class="af-rule">{{ TYPES[REQUEST_TRIP].rule }}</div>
      </section>

      <section :class="['ac-panel', 'af-sec', { done: hasDates && form.travel_destination.trim() }]">
        <div class="af-fh"><span class="n">2</span><h2>去哪、哪几天</h2><span class="ac-note">先点出发日，再点返回日；只出差一天点一次，周末也能选</span></div>
        <label class="af-subject ac-note">出差地点
          <input v-model="form.travel_destination" class="af-input" placeholder="例如：上海" maxlength="120" aria-label="出差地点" />
        </label>
        <div class="af-datebox">
          <AttendancePicker :month="month" :from="form.travel_start_date" :to="form.travel_end_date" :info="null" :overtime="true" :today="today" @pick="pickDay" @shift="(delta) => (month = shiftMonth(month, delta))" />
          <div class="af-days">
            <div class="ac-note af-lab">出差日期</div>
            <div v-if="!hasDates" class="ac-note">先在月历上选出发和返回日期</div>
            <div v-else class="af-day solo"><b>{{ form.travel_start_date }}</b><span class="ac-note">至</span><b>{{ form.travel_end_date }}</b><span class="ac-note">含当天，共 {{ days }} 天</span></div>
            <label class="af-subject ac-note">所属项目
              <select v-model="form.project" class="af-input" aria-label="所属项目"><option value="">非项目</option><option v-for="project in projects" :key="project" :value="project">{{ project }}</option></select>
            </label>
          </div>
        </div>
      </section>

      <section :class="['ac-panel', 'af-sec', { done: form.reason.trim() }]">
        <div class="af-fh"><span class="n">3</span><h2>事由</h2><span class="ac-note">申请人和审批人都会看到</span></div>
        <textarea v-model="form.reason" class="af-area" rows="3" maxlength="1000" aria-label="出差事由" placeholder="简单写一下出差做什么，审批人会看到，例如：拜访上海客户，洽谈新一年的合作"></textarea>
        <label class="af-subject ac-note">主题（不填会自动生成）<input v-model="form.subject" class="af-input" :placeholder="autoSubject || '例如：上海客户拜访'" maxlength="120" aria-label="主题" /></label>
      </section>
    </div>

    <aside class="ac-panel af-sum" aria-label="本次申请汇总">
      <div>
        <div class="ac-note">本次申请</div>
        <div class="af-big"><span class="n">{{ days || '—' }}</span><span>{{ days ? '天' : '' }}</span><span class="ac-note">出差</span></div>
        <div class="ac-note">{{ whenText }}</div>
      </div>
      <div class="af-block">
        <div class="ac-note">通过后</div>
        <div class="ac-note">出差期间不算请假，不扣年假和工时上限；途中的打车、住宿等费用，报销时直接关联这张出差申请。</div>
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
        <div v-if="missingVisible" class="af-need">
          <template v-if="blockers.length">还差：<span v-for="item in blockers" :key="item" class="todo-item">{{ item }} </span></template>
          <template v-else>都填好了</template>
        </div>
        <div v-if="error" class="af-err" role="alert">{{ error }}</div>
        <div v-if="message" class="af-ok" role="status">{{ message }}</div>
        <button type="button" class="ac-btn pri af-submit" :disabled="busy || loadingDraft" @click="save(false)">{{ busy ? '提交中…' : '提交申请' }}</button>
        <div class="af-two">
          <button type="button" class="ac-btn" :disabled="busy" @click="save(true)">{{ editing ? '保存修改' : '保存草稿' }}</button>
          <button type="button" class="ac-btn" :disabled="busy" @click="emit('cancel')">取消</button>
        </div>
        <div v-if="editing" class="ac-note">正在编辑草稿：{{ savedName }}</div>
      </div>
    </aside>
  </div>
</template>
