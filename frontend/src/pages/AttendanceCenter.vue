<script setup>
// 请假 / 加班 / 调休：员工先看额度，再提申请，记录一目了然；审批人把待办放第一位，批之前看得到影响。
// 版式按已确认的设计稿（2026-09-28）。提交、审批沿用 oa_entry 的接口，数据取自 attendance_entry。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router';
import '../styles/expenseUi.css';
import '../styles/attendanceUi.css';
import AttendanceCalendar from '../components/attendance/AttendanceCalendar.vue';
import AttendanceCards from '../components/attendance/AttendanceCards.vue';
import AttendanceDetail from '../components/attendance/AttendanceDetail.vue';
import AttendanceForm from '../components/attendance/AttendanceForm.vue';
import AttendanceList from '../components/attendance/AttendanceList.vue';
import AttendanceReview from '../components/attendance/AttendanceReview.vue';
import { TYPES, TYPE_ORDER, api, createLatest, periodOf, rejectionOf, returnedDrafts, typeForPath } from '../lib/attendanceView.js';

const route = useRoute();
const router = useRouter();

const requestType = computed(() => typeForPath(route.path));
const base = computed(() => TYPES[requestType.value].path);
const detailName = computed(() => String(route.params.name || route.query.request || ''));

const view = ref('mine');
const period = ref(periodOf());
const home = ref(null);
const mine = reactive({ items: [], names: {} });
const approval = ref(null);
const review = reactive({ items: [], team: [] });
const reviewed = ref([]);
const banner = reactive({ ok: '', err: '' });
const loading = ref(false);
const preview = reactive({ hours: 0, dates: [], leaveType: '事假' });
const formRef = ref(null);
const editing = ref(null);
const dismissed = ref(new Set());
const acted = ref(new Set());
let timer = null;
let alive = true;
const latestHome = createLatest();

const types = computed(() => home.value?.types || TYPE_ORDER);
const pendingCount = computed(() => review.items.filter((row) => !acted.value.has(row.name)).length);
const isApprover = computed(() => review.items.length > 0 || review.team.length > 0 || reviewed.value.length > 0);
const hasEmployee = computed(() => Boolean(home.value?.employee));
const returned = computed(() => returnedDrafts(mine.items).filter((row) => !dismissed.value.has(row.name) && row.name !== editing.value?.name));

function flash(ok = '', err = '') {
  banner.ok = ok;
  banner.err = err;
}

async function loadHome() {
  const token = latestHome.begin();
  try {
    const data = await api.home({ request_type: requestType.value, period: period.value });
    if (latestHome.isCurrent(token)) home.value = data;
  } catch (failure) {
    if (latestHome.isCurrent(token)) flash('', String(failure?.message || failure));
  }
}

async function loadMine() {
  try {
    const data = await api.mine(requestType.value);
    mine.items = data?.items || [];
    mine.names = data?.names || {};
    openRequestedDraft();
  } catch (failure) {
    flash('', String(failure?.message || failure));
  }
}

async function loadRoute() {
  approval.value = null;
  try {
    approval.value = await api.route(requestType.value);
  } catch (failure) {
    approval.value = { steps: [], copied_to: [], error: String(failure?.message || failure) };
  }
}

async function loadReview() {
  try {
    const data = await api.review();
    review.items = data?.items || [];
    review.team = data?.team || [];
    acted.value = new Set();
  } catch (failure) {
    flash('', String(failure?.message || failure));
  }
}

async function loadReviewed() {
  try {
    reviewed.value = (await api.reviewed())?.items || [];
  } catch {
    reviewed.value = [];
  }
}

async function loadAll() {
  loading.value = true;
  await Promise.allSettled([loadHome(), loadMine(), loadRoute(), loadReview(), loadReviewed()]);
  loading.value = false;
  // 待办放第一位：有待审批的申请、或者账号没有员工档案（只做审批），先看待审批。
  const wantsReview = review.items.length > 0 || (!home.value?.employee && isApprover.value);
  if (wantsReview && view.value === 'mine' && !detailName.value && !route.query.draft) view.value = 'review';
}

// 后台每 60 秒刷新额度、记录和待办；不碰正在填的表单。
async function poll() {
  if (!alive || document.visibilityState !== 'visible') return;
  await Promise.allSettled([loadHome(), loadMine(), loadReview()]);
}

function openRequestedDraft() {
  const wanted = String(route.query.draft || '');
  if (!wanted) return;
  const row = mine.items.find((item) => item.name === wanted && item.kanban_status === 'draft');
  if (row) {
    editing.value = row;
    view.value = 'mine';
  }
}

function editReturned(row) {
  if (formRef.value?.dirty?.() && editing.value?.name !== row.name && !window.confirm('当前表单还有没提交的内容，继续会丢失，是否继续？')) return;
  editing.value = row;
}

function onSaved(text) {
  editing.value = null;
  flash(text);
  loadHome();
  loadMine();
  if (route.query.draft) router.replace({ path: base.value });
}

function onActed(name) {
  acted.value = new Set([...acted.value, name]);
  loadReviewed();
}

function onPreview(value) {
  Object.assign(preview, value);
}

function warnBeforeUnload(event) {
  if (!formRef.value?.dirty?.()) return;
  event.preventDefault();
  event.returnValue = '';
}

function goType(type) {
  if (type === requestType.value) return;
  if (formRef.value?.dirty?.() && !window.confirm('当前表单还有没提交的内容，继续会丢失，是否继续？')) return;
  router.push(TYPES[type].path);
}

function changePeriod(next) {
  period.value = next;
  loadHome();
}

watch(requestType, () => {
  editing.value = null;
  dismissed.value = new Set();
  flash();
  loadHome();
  loadMine();
  loadRoute();
});
watch(() => route.query.draft, openRequestedDraft);
watch(view, (next) => {
  if (next === 'review') loadReview();
  if (next === 'reviewed') loadReviewed();
});

onBeforeRouteLeave(() => !formRef.value?.dirty?.() || window.confirm('当前表单还有没提交的内容，继续会丢失，是否继续？'));
onMounted(() => {
  loadAll();
  window.addEventListener('beforeunload', warnBeforeUnload);
  timer = window.setInterval(poll, 60000);
});
onBeforeUnmount(() => {
  alive = false;
  window.removeEventListener('beforeunload', warnBeforeUnload);
  if (timer) window.clearInterval(timer);
});
</script>

<template>
  <div class="xp">
    <div class="at-head">
      <h3>请假 · 加班 · 调休</h3>
      <div v-if="isApprover && !detailName" class="at-seg" role="tablist" aria-label="视图">
        <button type="button" role="tab" :aria-selected="view === 'review'" @click="view = 'review'">待我审批<span v-if="pendingCount" class="at-count">{{ pendingCount }}</span></button>
        <button type="button" role="tab" :aria-selected="view === 'mine'" @click="view = 'mine'">我的申请</button>
        <button type="button" role="tab" :aria-selected="view === 'reviewed'" @click="view = 'reviewed'">我审批过的</button>
      </div>
    </div>

    <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
    <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>

    <AttendanceDetail v-if="detailName" :key="detailName" :name="detailName" :base="base" />

    <template v-else-if="view === 'review'">
      <AttendanceReview :data="review" @acted="onActed" @stale="loadReview" />
    </template>

    <template v-else-if="view === 'reviewed'">
      <section class="at-panel" aria-label="我审批过的">
        <div class="at-label"><h4>我审批过的</h4><span class="at-sub">最近 30 条</span></div>
        <div v-if="!reviewed.length" class="empty">还没有你审批过的记录。</div>
        <router-link v-for="row in reviewed" :key="row.name + String(row.acted_on)" class="at-item" :to="`${TYPES[row.request_type]?.path || base}/${encodeURIComponent(row.name)}`">
          <div class="body">
            <b>{{ row.employee_name }} · {{ row.subject || row.request_type }}</b>
            <div class="meta">{{ row.department }} · {{ row.from_date }}<template v-if="row.to_date !== row.from_date"> 至 {{ row.to_date }}</template> · {{ row.name }}</div>
            <div class="note info">我的处理：{{ row.my_status }}（{{ row.step_label }}）· {{ String(row.acted_on || '').replace('T', ' ').slice(0, 16) }}<template v-if="row.note"> · {{ row.note }}</template></div>
          </div>
          <span class="pill p-gray">{{ row.workflow_status }}</span>
        </router-link>
      </section>
    </template>

    <template v-else>
      <div class="at-seg" role="tablist" aria-label="申请类型" style="margin-bottom:14px">
        <button v-for="type in types" :key="type" type="button" role="tab" :aria-selected="requestType === type" @click="goType(type)">{{ TYPES[type].label }}</button>
      </div>

      <div v-if="home && !hasEmployee" class="banner err">{{ home.reason || '当前账号没有关联在职员工，不能提交申请。' }}</div>

      <template v-if="hasEmployee">
        <section v-for="row in returned" :key="row.name" class="at-banner" aria-label="被退回的申请">
          <div class="t">{{ row.subject || row.request_type }}（{{ row.name }}）被退回了</div>
          <div class="s">{{ (mine.names[String(rejectionOf(row).actor).toLowerCase()] || String(rejectionOf(row).actor).split('@')[0]) }}：{{ rejectionOf(row).note || '请修改后重新提交' }}</div>
          <button type="button" class="btn pri" @click="editReturned(row)">修改后重新提交</button>
          <button type="button" class="btn" aria-label="关闭提示" @click="dismissed = new Set([...dismissed, row.name])">✕</button>
        </section>

        <AttendanceCards :home="home" :request-type="requestType" :leave-type="preview.leaveType" :preview-hours="preview.hours" />
        <AttendanceForm ref="formRef" :request-type="requestType" :home="home" :route="approval" :draft="editing" @preview="onPreview" @saved="onSaved" />

        <section class="at-panel" aria-label="我的记录">
          <div class="at-bottom">
            <AttendanceCalendar :home="home" :period="period" :chosen="preview.dates" @period="changePeriod" />
            <AttendanceList :rows="mine.items" :names="mine.names" :base="base" :title="`我的${TYPES[requestType].label}`" />
          </div>
        </section>
      </template>
    </template>
  </div>
</template>
