<script setup>
// 请假 · 加班 · 调休（考勤中心）：同一个页面四个视图，用路径和查询参数区分（2026-10-08 按确认的原型改版）。
//   路径决定类型：/approval/leave | overtime | comp-time（侧栏高亮跟着走）；
//   ?view=home 首页；?view=list&scope=todo|mine|done|all&type=请假|加班|调休|all 列表；
//   ?request=单号（或 /approval/<类型>/<单号>）详情；?view=new&type=…[&draft=单号] 新建（缺类型先让用户选）。
//   来源用 from=list&fscope=&ftype= / from=home 带着走，详情和新建页的"返回"、取消回到原处。
// 提交、审批、驳回、撤回沿用 oa_entry 的接口，数据取自 attendance_entry。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../styles/expenseUi.css';
import '../styles/attendanceUi.css';
import AttendanceDetail from '../components/attendance/AttendanceDetail.vue';
import AttendanceForm from '../components/attendance/AttendanceForm.vue';
import AttendanceHome from '../components/attendance/AttendanceHome.vue';
import AttendanceList from '../components/attendance/AttendanceList.vue';
import {
  ATTENDANCE_HOME_PATH, FALLBACK_HOME_PATH, STALE_STEP, TYPES, TYPE_ORDER, api, backLabel, backLocation, contextFilter,
  createLatest, defaultScope, detailLocation, homeLocation, labelOfType, listLocation, newLocation, newTitle,
  parseLocation, pathForFilter, periodOf, requestTypeOf, rowLabel, validScope,
} from '../lib/attendanceView.js';

const route = useRoute();
const router = useRouter();
// 首页和"全部类型"的列表放在 /approval/attendance；路由里还没有它时退回请假的路径（靠 ?view= 区分）。
const homePath = router.getRoutes().some((item) => item.path === ATTENDANCE_HOME_PATH) ? ATTENDANCE_HOME_PATH : FALLBACK_HOME_PATH;

const page = computed(() => parseLocation({ path: route.path, params: route.params, query: route.query }));
const view = computed(() => page.value.view);

const period = ref(periodOf());
const home = ref(null);
const mine = reactive({ items: [], names: {} });
const review = reactive({ items: [], team: [] });
const reviewed = ref([]);
const everyone = reactive({ items: [], names: {} });
const loaded = reactive({ home: false, mine: false, review: false, reviewed: false, all: false });
const approval = ref(null);
const banner = reactive({ ok: '', err: '' });
const busy = ref(false);
const formRef = ref(null);
const now = ref(Date.now());
let timer = null;
let alive = true;
let keepBanner = false;
const latest = { home: createLatest(), mine: createLatest(), review: createLatest(), reviewed: createLatest(), all: createLatest(), route: createLatest() };

const availableTypes = computed(() => home.value?.types || TYPE_ORDER);
const hasEmployee = computed(() => Boolean(home.value?.employee));
const canViewAll = computed(() => Boolean(home.value?.can_view_all));
const isApprover = computed(() => review.items.length > 0 || review.team.length > 0 || reviewed.value.length > 0);
const newTypeRequest = computed(() => requestTypeOf(page.value.newType));
const origin = computed(() => page.value.origin);

function flash(ok = '', err = '') {
  banner.ok = ok;
  banner.err = err;
}

const messageOf = (failure) => String(failure?.message || failure || '操作失败');

// ---------------------------------------------------------------- 加载：每一项各取各的，只认最近一次发出的结果
async function guarded(key, loader, apply) {
  const token = latest[key].begin();
  try {
    const data = await loader();
    if (latest[key].isCurrent(token)) apply(data);
  } catch (failure) {
    if (latest[key].isCurrent(token)) flash('', messageOf(failure));
  } finally {
    if (latest[key].isCurrent(token) && key in loaded) loaded[key] = true;
  }
}

const loadHome = () => guarded('home', () => api.home({ request_type: TYPE_ORDER[0], period: period.value }), (data) => { home.value = data; });
const loadMine = () => guarded('mine', () => api.mine(), (data) => { mine.items = data?.items || []; mine.names = data?.names || {}; });
const loadReview = () => guarded('review', () => api.review(), (data) => { review.items = data?.items || []; review.team = data?.team || []; });
const loadReviewed = () => guarded('reviewed', () => api.reviewed(), (data) => { reviewed.value = data?.items || []; });
const loadEveryone = () => guarded('all', () => api.all(), (data) => { everyone.items = data?.items || []; everyone.names = data?.names || {}; });

async function loadRoute(requestType) {
  approval.value = null;
  if (!requestType) return;
  const token = latest.route.begin();
  try {
    const data = await api.route(requestType);
    if (latest.route.isCurrent(token)) approval.value = data;
  } catch (failure) {
    if (latest.route.isCurrent(token)) approval.value = { steps: [], copied_to: [], error: messageOf(failure) };
  }
}

function refreshLists() {
  const jobs = [loadHome(), loadMine(), loadReview(), loadReviewed()];
  if (page.value.scope === 'all' && canViewAll.value) jobs.push(loadEveryone());
  return Promise.allSettled(jobs);
}

// 后台每 60 秒刷新额度、记录和待办；只在首页和列表上刷，不碰正在填的表单和正在看的详情。
async function poll() {
  now.value = Date.now();
  if (!alive || document.visibilityState !== 'visible' || !['home', 'list'].includes(view.value)) return;
  await refreshLists();
}

// ---------------------------------------------------------------- 跳转
function dirty() {
  return Boolean(formRef.value?.dirty?.());
}

const LEAVE_FORM = '当前表单还有没提交的内容，继续会丢失，是否继续？';
const typePaths = TYPE_ORDER.map((type) => TYPES[type].path);
const isAttendancePath = (path) => [...typePaths, ATTENDANCE_HOME_PATH].some((base) => path === base || path.startsWith(`${base}/`));

// 所有页内跳转都走这里：目标不带路径时用当前路径。填了一半的表单离开新建页前由下面的路由守卫问一声
// （守卫对每一次跳转都生效：侧栏、面包屑、取消、浏览器返回键；留在新建页里换类型、存草稿不问）。
function go(location, { replace = false } = {}) {
  const target = { path: location.path || route.path, query: location.query || {} };
  return replace ? router.replace(target) : router.push(target);
}

const stopGuard = router.beforeEach((to) => {
  if (!dirty()) return true;
  if (to.query.view === 'new' && isAttendancePath(to.path)) return true;
  return window.confirm(LEAVE_FORM);
});

function currentOrigin() {
  if (view.value === 'list') return { kind: 'list', scope: page.value.scope || 'mine', filter: page.value.filter };
  if (view.value === 'home') return { kind: 'home', scope: '', filter: 'all' };
  return null;
}

const goHome = () => go(homeLocation(homePath));
const goList = (scope, filter) => go(listLocation({ scope, filter }, homePath));
const goNew = (type = '') => go(newLocation({ type }, currentOrigin() || origin.value));
const openRow = (row) => go(detailLocation({ name: row.name, type: rowLabel(row) }, currentOrigin()));
const continueDraft = (row) => go(newLocation({ type: rowLabel(row), draft: row.name }, currentOrigin() || origin.value));
const goBack = () => go(backLocation(origin.value, { filter: page.value.newType || 'all', homePath }));

// 列表上切范围 / 类型：留在同一个列表，替换历史记录（返回键不会在筛选之间来回跳）。
function setScope(scope) {
  go(listLocation({ scope, filter: page.value.filter }, homePath), { replace: true });
}

function setFilter(filter) {
  go(listLocation({ scope: page.value.scope || 'mine', filter }, homePath), { replace: true });
}

function onPeriod(next) {
  period.value = next;
  loadHome();
}

// ---------------------------------------------------------------- 审批和撤回
function summary(row) {
  return `${row.employee_name || ''} 的${rowLabel(row)}申请`;
}

async function approveRow(row) {
  if (busy.value) return;
  busy.value = true;
  flash();
  try {
    await api.act({ name: row.name, action: 'approve', note: '', expected_step_key: row.current_step_key || '' });
    flash(`已同意 · ${summary(row)}`);
  } catch (failure) {
    const text = messageOf(failure);
    flash('', STALE_STEP.test(text) ? `${text}，已刷新列表` : text);
  } finally {
    busy.value = false;
    await refreshLists();
  }
}

// 批量同意：一演示员工128张批，每张都带着页面上看到的那一步；有失败的单独说明。
async function approveMany(rows) {
  if (busy.value || !rows.length) return;
  busy.value = true;
  flash();
  const failed = [];
  let ok = 0;
  for (const row of rows) {
    try {
      await api.act({ name: row.name, action: 'approve', note: '', expected_step_key: row.current_step_key || '' });
      ok += 1;
    } catch (failure) {
      failed.push(`${row.name}：${messageOf(failure)}`);
    }
  }
  flash(ok ? `已批量同意 ${ok} 张` : '', failed.length ? `${failed.length} 张没有批成：${failed[0]}${failed.length > 1 ? ' 等' : ''}` : '');
  busy.value = false;
  await refreshLists();
}

// 驳回必须写原因：带着"驳回"进入详情页，在那里填。
function rejectRow(row) {
  go(detailLocation({ name: row.name, type: rowLabel(row) }, currentOrigin(), { reject: true }));
}

async function withdrawRow(row) {
  if (busy.value || !window.confirm('撤回后这张申请会退回草稿，占用的额度会释放。确定撤回吗？')) return;
  busy.value = true;
  flash();
  try {
    await api.withdraw(row.name);
    flash('已撤回，额度已释放');
  } catch (failure) {
    flash('', messageOf(failure));
  } finally {
    busy.value = false;
    await refreshLists();
  }
}

// ---------------------------------------------------------------- 新建页
function switchType(label) {
  go(newLocation({ type: label }, origin.value), { replace: true });
}

function onDraftType(label) {
  go(newLocation({ type: label, draft: page.value.draft }, origin.value), { replace: true });
}

function onDraftSaved(name) {
  go(newLocation({ type: page.value.newType, draft: name }, origin.value), { replace: true });
  refreshLists();
}

function onSubmitted({ name, requestType }) {
  const label = labelOfType(requestType);
  keepBanner = true;
  flash(`${label}申请已提交，等待审批`);
  refreshLists();
  go(detailLocation({ name, type: label }, { kind: 'list', scope: 'mine', filter: label }));
}

// 详情页告诉我们这张申请的类型：路径和类型不一致时（旧链接、通知）换成它自己类型的路径，侧栏才高亮对。
function onDetailLoaded(request) {
  const wanted = TYPES[request?.request_type]?.path;
  if (!wanted) return;
  const current = typePaths.find((base) => route.path === base || route.path.startsWith(`${base}/`));
  if (current === wanted) return;
  router.replace({ path: route.params.name ? `${wanted}/${encodeURIComponent(request.name)}` : wanted, query: route.query });
}

// ---------------------------------------------------------------- 监听
// 侧栏高亮、标题跟着"正在处理的类型"走：路径和当前类型不一致时换成对应路径（只换路径，查询参数不变）。
watch(() => [route.path, view.value, page.value.filter, page.value.newType], () => {
  if (view.value === 'detail') return;
  const wanted = pathForFilter(contextFilter(page.value), homePath);
  if (route.path !== wanted) router.replace({ path: wanted, query: route.query });
}, { immediate: true });

// 没带范围的列表（侧栏点进来）：有待办就看待办，没有就看我的；有了就写进地址，分享出去的链接也一样。
watch(() => [view.value, page.value.scope, page.value.filter, loaded.review, loaded.home, canViewAll.value], () => {
  if (view.value !== 'list' || !loaded.review || !loaded.home) return;
  const wanted = page.value.scope ? validScope(page.value.scope, { canViewAll: canViewAll.value }) : defaultScope(review.items.length);
  if (wanted !== page.value.scope) router.replace(listLocation({ scope: wanted, filter: page.value.filter }, homePath));
}, { immediate: true });

watch(() => [view.value, page.value.scope, canViewAll.value], () => {
  if (view.value === 'list' && page.value.scope === 'all' && canViewAll.value) loadEveryone();
}, { immediate: true });

// 提示条只属于产生它的那一页：换了页面（或换了一张申请）就收起来；刚提交成功的那条要带到详情页上。
watch(() => `${view.value}|${page.value.request}|${page.value.newType}`, () => {
  if (keepBanner) keepBanner = false;
  else flash();
});

// 进入首页 / 列表时刷新一次（别的页面里批过、提交过，这里不能还是旧的）；切类型不重新取数，类型筛选在本地做。
watch(view, (next, previous) => {
  if (['home', 'list'].includes(next) && previous && previous !== next) refreshLists();
});

// 新建页：审批路线按类型取；类型一换，旧类型的路线先清掉再重取（快速来回切也只认最后一次）。
watch(newTypeRequest, (type) => {
  if (view.value === 'new') loadRoute(type);
}, { immediate: true });
watch(view, (next) => {
  if (next === 'new') loadRoute(newTypeRequest.value);
});

function warnBeforeUnload(event) {
  if (!dirty()) return;
  event.preventDefault();
  event.returnValue = '';
}

onMounted(() => {
  refreshLists();
  window.addEventListener('beforeunload', warnBeforeUnload);
  timer = window.setInterval(poll, 60000);
});
onBeforeUnmount(() => {
  alive = false;
  stopGuard();
  window.removeEventListener('beforeunload', warnBeforeUnload);
  if (timer) window.clearInterval(timer);
});

const listSets = computed(() => ({
  todo: review.items, mine: mine.items, done: reviewed.value, all: everyone.items,
}));
const listNames = computed(() => ({ ...mine.names, ...everyone.names }));
const pickCards = computed(() => availableTypes.value.map((type) => ({ type, label: TYPES[type].label, rule: TYPES[type].rule })));
const subtitle = computed(() => {
  if (!page.value.newType) return '三种申请的规则不一样，先选好再填，避免填错。';
  if (page.value.newType === '加班') return '先确认类型，再选日期和加班小时数；提交后按 1:1 增加调休额度。';
  return '先确认类型，再选日期；每一天选“全天 / 上午 / 下午 / 自定义小时 / 不请”。';
});
const noEmployeeText = computed(() => home.value?.reason || '当前账号没有关联在职员工，不能提交申请。');
</script>

<template>
  <div class="xp at">
    <div v-if="banner.ok" class="banner ok" role="status">{{ banner.ok }}</div>
    <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>

    <AttendanceHome
      v-if="view === 'home'" :home="home" :mine="mine" :review="review" :loaded="loaded" :now="now" :busy="busy"
      :has-employee="hasEmployee" :is-approver="isApprover" :available-types="availableTypes" :period="period" :no-employee-text="noEmployeeText"
      @new="goNew" @list="goList" @open="openRow" @approve="approveRow" @reject="rejectRow" @withdraw="withdrawRow"
      @continue="continueDraft" @period="onPeriod" />

    <AttendanceList
      v-else-if="view === 'list'" :page="page" :sets="listSets" :names="listNames" :loaded="loaded" :now="now" :busy="busy"
      :is-approver="isApprover" :can-view-all="canViewAll" :has-employee="hasEmployee"
      @home="goHome" @scope="setScope" @filter="setFilter" @new="goNew" @open="openRow" @approve-many="approveMany" />

    <AttendanceDetail
      v-else-if="view === 'detail'" :key="page.request" :name="page.request" :origin="origin" :reject-mode="page.reject"
      @home="goHome" @back="goBack" @navigate="go" @loaded="onDetailLoaded" @changed="refreshLists" />

    <template v-else>
      <div class="ph">
        <div>
          <div class="crumb">
            <button type="button" class="link" @click="goHome">考勤中心</button> ›
            <button type="button" class="link" @click="goBack">{{ backLabel(origin) }}</button> › {{ newTitle(page.newType) }}
          </div>
          <h3>{{ newTitle(page.newType) }}</h3>
          <div class="muted">{{ subtitle }}</div>
        </div>
      </div>

      <div v-if="!loaded.home" class="panel empty">正在加载…</div>
      <div v-else-if="!hasEmployee" class="banner err">{{ noEmployeeText }}</div>

      <section v-else-if="!page.newType" class="panel at-picker" aria-label="选择申请类型">
        <b>你要新建哪一种？</b>
        <div class="muted">三种申请的规则不一样，先选好再填，避免填错。</div>
        <div class="at-pick-cards">
          <button v-for="card in pickCards" :key="card.type" type="button" class="at-kpi" @click="switchType(card.label)">
            <span class="at-pick-title">新建{{ card.label }}</span>
            <span class="at-kpi-sub">{{ card.rule }}</span>
          </button>
        </div>
        <div class="actions"><button type="button" class="btn" @click="goBack">取消</button></div>
      </section>

      <AttendanceForm
        v-else ref="formRef" :request-type="newTypeRequest" :draft-name="page.draft" :home="home" :route="approval" :types="availableTypes"
        @switch-type="switchType" @draft-type="onDraftType" @draft-saved="onDraftSaved" @submitted="onSubmitted" @cancel="goBack" />
    </template>
  </div>
</template>
