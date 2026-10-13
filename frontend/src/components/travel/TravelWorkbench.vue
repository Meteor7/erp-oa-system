<script setup>
// 出差申请：只批该不该去，不设金额；报销、付款关联它即可。2026-10 按确认的 demo 改版：
// 首页（待我审批 / 我的出差 / 列表）、列表页、详情页、新建单独一页，用查询参数区分，和报销、付款页一样。
// 审批人原来只能从待办链接打开单据，现在首页有"待我审批"栏目。
import { computed, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../../styles/expenseUi.css';
import '../../styles/boardsUi.css';
import '../../styles/navUi.css';
import TravelTable from './TravelTable.vue';
import { callApi, displayStatus, pillClass } from '../../lib/expenseClaims.js';
import {
  approveArgs, canSeeAllTravel, dateRange, emptyTravelForm, filterTravelByBucket, isStaleError, normalizeTravelBucket, pushTarget,
  rejectProblem, showMissing, travelBlockers, travelBucketLabel, travelBuckets, travelFormFrom, travelScopeInfo, travelScopes,
  travelStats, travelTimeline, travelView, tripDays, waitText, waitedDays,
} from '../../lib/travelView.js';
import {
  backLocation, carryQuery, cleanQuery, detailQuery, formQuery, fromValue, hereAsFrom, listWithout, originLabel, originOf,
} from '../../lib/navContext.js';
import { useLeaveConfirm } from '../../lib/leaveConfirm.js';
import { isWaitingTooLong } from '../../lib/waiting.js';

const REQUEST_TYPE = '出差申请';
const route = useRoute();
const router = useRouter();
const canAll = canSeeAllTravel();

const view = computed(() => travelView(route.query));
// 没有权限的范围（普通员工的 scope=all）退回"我的"，并在列表页上说明。
const scopeInfo = computed(() => travelScopeInfo(route.query.scope, canAll));
const scope = computed(() => scopeInfo.value.scope);
// 首页指标卡带状态点进来：?bucket=draft|review|approved|back，列表上显示成可以移除的标签。
const bucketKey = computed(() => normalizeTravelBucket(route.query.bucket));
const home = reactive({ todo: [], mine: [], loaded: false });
const docs = ref([]);
const focusDoc = ref(null);
const focusOwn = ref(false);
const projects = ref([]);
const loading = ref(false);
const busy = ref(false);
const banner = reactive({ ok: '', err: '' });
const now = Date.now();

const editingName = ref('');
const attempted = ref(false);
const form = reactive(emptyTravelForm());
// 详情页里的驳回 / 撤回：原因直接在页面上填。
const ask = reactive({ kind: '', note: '', problem: '' });

const days = computed(() => tripDays(form.travel_start_date, form.travel_end_date));
const blockers = computed(() => travelBlockers(form));
const missingVisible = computed(() => showMissing(form, attempted.value));
const mineNames = computed(() => new Set(home.mine.map((row) => row.name)));
const ownRow = (row) => scope.value === 'mine' || mineNames.value.has(row.name);
const stats = computed(() => travelStats(home.todo, home.mine, now));
const buckets = computed(() => travelBuckets(home.mine));
const todoTop = computed(() => [...home.todo].sort((a, b) => (waitedDays(b, now) ?? -1) - (waitedDays(a, now) ?? -1)).slice(0, 3));
const mineTop = computed(() => home.mine.slice(0, 4));
const scopes = computed(() => travelScopes({ canAll, todoCount: home.todo.length }));
const scopeLabel = computed(() => scopes.value.find((item) => item.key === scope.value)?.label || '我的');
const shownDocs = computed(() => filterTravelByBucket(docs.value, bucketKey.value));
const timeline = computed(() => travelTimeline(focusDoc.value || {}));
const lastApplied = computed(() => form.travel_start_date && form.travel_end_date
  ? `${form.travel_start_date.slice(5).replace('-', ' 月 ')} 日 – ${form.travel_end_date.slice(5).replace('-', ' 月 ')} 日${form.travel_destination ? ' · ' + form.travel_destination : ''}`
  : (form.travel_destination || '填写日期后显示'));

// 表单有没有改过：打开 / 保存之后的快照对比现在的内容；改过再离开（取消、面包屑、侧栏、后退、关标签页）要确认。
const baseline = ref('');
const fingerprint = () => JSON.stringify({ form, editing: editingName.value });
function markClean() {
  baseline.value = fingerprint();
}
useLeaveConfirm(() => view.value === 'new' && fingerprint() !== baseline.value);

function resetForm() {
  Object.assign(form, emptyTravelForm());
  editingName.value = '';
  attempted.value = false;
  markClean();
}
resetForm();

function flash(ok = '', err = '') {
  banner.ok = ok;
  banner.err = err;
}

function go(query = {}) {
  flash();
  router.push({ path: route.path, query });
}

// 列表的当前状态：点进详情 / 表单时带上，回来时原样恢复。
// origin：这个列表自己是从哪个页面（看板、首页）点进来的，详情 / 表单往回走时一层层带回去。
const originKeep = computed(() => (originOf(route.query) ? { from: originOf(route.query) } : {}));
const listFilters = computed(() => cleanQuery({ scope: scope.value, bucket: bucketKey.value, origin: originOf(route.query) }));
const cameFromList = computed(() => fromValue(route.query) === 'list');
const originText = computed(() => {
  const from = fromValue(route.query);
  return from && from !== 'list' ? (originLabel(route.query) || '上一页') : '';
});
function goBack() {
  flash();
  router.push(backLocation(route.path, route.query));
}
// 详情页的"列表"：从列表来的回到同一个范围和筛选；其他入口（通知、首页）按这张单是不是我的来猜（待办链接进来的多半是审批人）。
function backToList() {
  flash();
  router.push(cameFromList.value ? backLocation(route.path, route.query) : { path: route.path, query: { view: 'list', scope: focusOwn.value ? 'mine' : 'todo' } });
}

async function run(action, okText) {
  busy.value = true;
  flash();
  try {
    const result = await action();
    if (okText) flash(typeof okText === 'function' ? okText(result) : okText);
    await loadPage();
    return result;
  } catch (error) {
    flash('', String(error?.message || error || '操作失败'));
    // 单据已经变化（别人先处理了、被撤回过）：重新加载，页面显示最新的一步。
    if (isStaleError(error)) await loadPage();
    return null;
  } finally {
    busy.value = false;
  }
}

const listFor = (listView, extra = {}) => callApi('oa_entry.list_requests', { view: listView, request_type: REQUEST_TYPE, limit: 100, ...extra }, { method: 'GET' });
const loadOne = async (listView, name) => ((await listFor(listView, { name, limit: 1 })) || [])[0] || null;

async function loadHome() {
  const [todo, mine] = await Promise.all([listFor('pending'), listFor('mine')]);
  Object.assign(home, { todo: todo || [], mine: mine || [], loaded: true });
}

async function loadList() {
  if (scope.value === 'todo') docs.value = (await listFor('pending')) || [];
  else if (scope.value === 'all') docs.value = (await listFor('all', { limit: 200 })) || [];
  else docs.value = (await listFor('mine')) || [];
  if (!home.loaded) {
    if (scope.value === 'mine') Object.assign(home, { mine: docs.value });
    else Object.assign(home, { mine: (await listFor('mine')) || [] });
  }
  if (scope.value === 'todo') home.todo = docs.value;
}

async function loadDetail() {
  const name = String(route.query.request || '');
  const [found, mine] = await Promise.all([loadOne('all', name), loadOne('mine', name)]);
  focusDoc.value = found || mine || (await loadOne('pending', name));
  focusOwn.value = Boolean(mine);
  ask.kind = '';
  ask.note = '';
  ask.problem = '';
}

async function loadPage() {
  if (view.value === 'new') return;
  loading.value = true;
  try {
    if (view.value === 'detail') await loadDetail();
    else if (view.value === 'list') await loadList();
    else await loadHome();
  } catch (error) {
    flash('', String(error?.message || error));
  } finally {
    loading.value = false;
  }
}

async function loadProjects() {
  if (projects.value.length) return;
  try {
    projects.value = ((await callApi('expense_claim_entry.list_claim_projects', { request_type: REQUEST_TYPE }, { method: 'GET' })) || []).map((row) => row.name || row);
  } catch {
    projects.value = [];
  }
}

// ---------------------------------------------------------------- 新建 / 草稿
async function enterNewPage() {
  loadProjects();
  const draftName = String(route.query.draft || '');
  if (!draftName) {
    resetForm();
    return;
  }
  if (editingName.value === draftName) return;
  // 先记住草稿编号：即使后面加载失败，保存时也是更新这张草稿，不会另存一份。
  resetForm();
  editingName.value = draftName;
  try {
    const doc = await loadOne('mine', draftName);
    if (!doc) {
      flash('', `找不到草稿 ${draftName}`);
      return;
    }
    Object.assign(form, travelFormFrom(doc));
    markClean();
  } catch (error) {
    flash('', String(error?.message || error));
  }
}

async function save({ submit = false } = {}) {
  if (submit) {
    attempted.value = true;
    if (blockers.value.length) return;
  }
  busy.value = true;
  flash();
  try {
    const doc = await callApi('travel_entry.save_travel_draft', { payload: JSON.stringify({ ...form }), name: editingName.value || undefined });
    editingName.value = doc.name;
    markClean();
    if (submit) {
      await callApi('oa_entry.submit_request', { name: doc.name });
      resetForm();
      router.push({ path: route.path, query: { request: doc.name } });
      flash(`出差申请 ${doc.name} 已提交审批`);
    } else {
      router.replace({ path: route.path, query: { view: 'new', draft: doc.name, ...carryQuery(route.query) } });
      flash(`草稿 ${doc.name} 已保存`);
    }
  } catch (error) {
    flash('', String(error?.message || error || '保存失败'));
  } finally {
    busy.value = false;
  }
}

// ---------------------------------------------------------------- 单据操作
async function approve(doc) {
  if (busy.value) return;
  await run(() => callApi('oa_entry.action_request', approveArgs(doc, 'approve')), `${doc.name} 已同意`);
}

function openAsk(kind) {
  ask.kind = ask.kind === kind ? '' : kind;
  ask.note = '';
  ask.problem = '';
}

async function confirmAsk(doc) {
  if (ask.kind === 'reject') {
    ask.problem = rejectProblem(ask.note);
    if (ask.problem) return;
    await run(() => callApi('oa_entry.action_request', approveArgs(doc, 'reject', ask.note)), '已驳回给申请人');
  } else if (ask.kind === 'withdraw') {
    await run(() => callApi('oa_entry.withdraw_request', { name: doc.name, note: ask.note.trim() }), '已撤回为草稿');
  }
}

async function withdraw(row, note) {
  await run(() => callApi('oa_entry.withdraw_request', { name: row.name, note }), `${row.name} 已撤回为草稿`);
}

// 下推报销 / 付款：目标页先弹出"确定要创建草稿吗"，确认后才生成；from 让它取消时回到这里。
function push(row, kind) {
  router.push({ path: pushTarget(kind), query: { source: row.name, from: hereAsFrom(route.path, route.query) } });
}

watch(() => [view.value, scope.value, route.query.request, route.query.draft], () => {
  if (view.value === 'new') enterNewPage();
  else loadPage();
}, { immediate: true });
</script>

<template>
  <div class="xp tv">
    <!-- ============================== 首页 ============================== -->
    <template v-if="view === 'home'">
      <div class="ph">
        <div>
          <div class="crumb">审批中心 · 购买与出差</div>
          <h3>出差申请</h3>
          <div class="muted">只批该不该去，不设金额；报销、付款关联它即可。审批路线：直属主管 → 副总经理。</div>
        </div>
        <div class="head-actions"><button type="button" class="btn pri lg" @click="go({ view: 'new' })">＋ 新建出差申请</button></div>
      </div>
      <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
      <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>
      <div v-if="loading && !home.loaded" class="panel empty">正在加载…</div>
      <template v-else>
        <div class="stat-cards">
          <button v-for="card in stats" :key="card.key" type="button" class="stat-card" @click="go(card.query)">
            <span class="l"><i :style="{ background: card.tone }"></i>{{ card.label }}</span>
            <span class="v"><b>{{ card.count }}</b> 张</span>
            <span class="l">{{ card.hint }}</span>
          </button>
        </div>

        <div class="home-grid">
          <section class="panel">
            <div class="pt"><span>待我审批 <span class="count-pill">{{ home.todo.length }}</span></span><button type="button" class="link" @click="go({ view: 'list', scope: 'todo' })">全部 {{ home.todo.length }} 张 →</button></div>
            <div v-for="doc in todoTop" :key="doc.name" class="todo-row">
              <span class="avatar">{{ (doc.employee_name || '?').slice(0, 1) }}</span>
              <div class="grow-col"><b class="ellipsis">{{ doc.subject || '（无主题）' }}</b><span class="muted">{{ doc.employee_name }}<template v-if="doc.department"> · {{ doc.department }}</template> · {{ doc.name }}<template v-if="doc.project"> · 项目 {{ doc.project }}</template></span></div>
              <div class="tv-dest"><span>{{ doc.travel_destination }}</span><span class="muted">{{ dateRange(doc) }}（{{ doc.travel_days || 0 }} 天）</span></div>
              <span :class="['wait', { warn: isWaitingTooLong(waitedDays(doc, now)) }]">{{ waitText(waitedDays(doc, now)) }}</span>
              <span class="row-actions">
                <button type="button" class="btn sm" @click="go({ request: doc.name })">看详情</button>
                <button v-if="doc.can_approve" type="button" class="btn sm dark" :disabled="busy" @click="approve(doc)">同意</button>
              </span>
            </div>
            <div v-if="!home.todo.length" class="empty">没有需要你审批的出差申请</div>
            <div v-else class="muted foot">只列等得最久的 3 张；驳回请进详情页填写原因。</div>
          </section>

          <section class="panel">
            <div class="pt"><span>我的出差</span><button type="button" class="link" @click="go({ view: 'list', scope: 'mine' })">全部 {{ home.mine.length }} 张 →</button></div>
            <div class="stack-bar"><i v-for="bucket in buckets" :key="bucket.key" :style="{ width: bucket.width, background: bucket.color }"></i></div>
            <div class="bucket-legend"><span v-for="bucket in buckets" :key="bucket.key"><i :style="{ background: bucket.color }"></i>{{ bucket.label }} {{ bucket.count }}</span></div>
            <button v-for="doc in mineTop" :key="doc.name" type="button" class="mine-row" @click="doc.workflow_status === '草稿' ? go({ view: 'new', draft: doc.name }) : go({ request: doc.name })">
              <span class="grow-col"><span class="ellipsis">{{ doc.subject || '（无主题）' }}</span><span class="muted">{{ dateRange(doc) }} · {{ doc.travel_days || 0 }} 天</span></span>
              <span :class="pillClass(displayStatus(doc))">{{ displayStatus(doc) }}</span>
            </button>
            <div v-if="!home.mine.length" class="empty">还没有出差申请，点右上角新建</div>
            <div class="tv-hint">已通过的出差申请可以直接"下推报销"或"下推付款"，按钮在单据详情右上角，也在列表最右边。</div>
          </section>
        </div>

        <section class="panel flush">
          <div class="tv-list-head">
            <b>我的出差申请 <span class="muted">最近 {{ Math.min(home.mine.length, 8) }} 张<template v-if="home.mine.length > 8">，共 {{ home.mine.length }} 张</template></span></b>
            <div class="seg"><button v-for="item in scopes" :key="item.key" type="button" :aria-pressed="item.key === 'mine'" :title="item.key === 'mine' ? '' : '打开完整列表'" @click="go({ view: 'list', scope: item.key })">{{ item.label }}<template v-if="item.key === 'todo'"> {{ item.count }}</template></button></div>
          </div>
          <TravelTable :rows="home.mine.slice(0, 8)" :busy="busy" empty="还没有出差申请" @open="(row) => go({ request: row.name })" @edit="(row) => go({ view: 'new', draft: row.name })" @push="push" @withdraw="withdraw" />
        </section>
      </template>
    </template>

    <!-- ============================== 列表页 ============================== -->
    <template v-else-if="view === 'list'">
      <div class="ph">
        <div>
          <div v-if="originText" class="crumb"><button type="button" class="link nav-back" @click="goBack">← 返回{{ originText }}</button></div>
          <div class="crumb"><button type="button" class="link" @click="go({})">出差申请</button> › {{ scopeLabel }}</div>
          <h3>{{ scopeLabel }} · {{ shownDocs.length }} 张<template v-if="bucketKey"><span class="muted">（共 {{ docs.length }} 张，已筛选）</span></template></h3>
        </div>
        <div class="seg">
          <button v-for="item in scopes" :key="item.key" type="button" :aria-pressed="scope === item.key" @click="go({ view: 'list', scope: item.key, ...originKeep })">{{ item.label }}</button>
        </div>
      </div>
      <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
      <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>
      <div v-if="scopeInfo.notice" class="banner warn" role="status" data-testid="scope-notice">{{ scopeInfo.notice }}</div>
      <div v-if="bucketKey" class="nav-filters" data-testid="bucket-filter">
        <span class="nav-filter">状态：{{ travelBucketLabel(bucketKey) }}<button type="button" aria-label="清除状态筛选" @click="go(listWithout(route.query, 'bucket'))">×</button></span>
      </div>
      <div class="filter-bar"><span class="grow-col"></span><button type="button" class="btn pri" @click="go(formQuery({ view: 'new' }, listFilters))">＋ 新建出差申请</button></div>
      <div class="panel flush">
        <TravelTable :rows="shownDocs" :own="ownRow" :loading="loading" :busy="busy" :show-applicant="scope !== 'mine'" :approvable="scope === 'todo'" :empty="scope === 'todo' ? '没有需要你审批的出差申请' : '这里没有出差申请'" @approve="approve" @open="(row) => go(detailQuery(row.name, listFilters))" @edit="(row) => go(formQuery({ view: 'new', draft: row.name }, listFilters))" @push="push" @withdraw="withdraw" />
      </div>
    </template>

    <!-- ============================== 详情页 ============================== -->
    <template v-else-if="view === 'detail'">
      <div class="crumb">
        <button v-if="originText" type="button" class="link nav-back" @click="goBack">← 返回{{ originText }}</button>
        <button type="button" class="link" @click="go({})">出差申请</button> › <button type="button" class="link" @click="backToList">列表</button> › {{ route.query.request }}
      </div>
      <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
      <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>
      <div v-if="loading && !focusDoc" class="panel empty">正在加载…</div>
      <div v-else-if="!focusDoc" class="panel empty">找不到单据 {{ route.query.request }}，可能没有查看权限</div>
      <template v-else>
        <section class="panel detail-head">
          <div class="grow-col">
            <div class="title-line"><h3>{{ focusDoc.subject || '（无主题）' }}</h3><span :class="pillClass(displayStatus(focusDoc))">{{ displayStatus(focusDoc) }}</span></div>
            <div class="muted">{{ focusDoc.name }} · {{ focusDoc.employee_name }}<template v-if="['待审批', '待办理'].includes(focusDoc.workflow_status) && focusDoc.current_step_label"> · 在 {{ focusDoc.current_step_label }} · {{ waitText(waitedDays(focusDoc, now)) }}</template></div>
          </div>
          <div class="head-buttons">
            <button v-if="focusDoc.workflow_status === '已完成' && focusOwn" type="button" class="btn" @click="push(focusDoc, 'claim')">下推报销</button>
            <button v-if="focusDoc.workflow_status === '已完成' && focusOwn" type="button" class="btn" @click="push(focusDoc, 'payment')">下推付款</button>
            <button v-if="focusDoc.workflow_status === '草稿' && focusOwn" type="button" class="btn" :disabled="busy" @click="go({ view: 'new', draft: focusDoc.name, ...carryQuery(route.query) })">继续编辑</button>
            <button v-if="focusDoc.can_withdraw" type="button" class="btn" :disabled="busy" @click="openAsk('withdraw')">撤回</button>
            <button v-if="focusDoc.can_reject" type="button" class="btn danger" :disabled="busy" @click="openAsk('reject')">驳回</button>
            <button v-if="focusDoc.can_approve" type="button" class="btn pri lg" :disabled="busy" @click="approve(focusDoc)">同意</button>
          </div>
        </section>

        <section v-if="ask.kind" class="panel accent tv-ask-panel">
          <div class="pt">{{ ask.kind === 'reject' ? '驳回给申请人' : '撤回为草稿' }}</div>
          <div class="f">
            <label>{{ ask.kind === 'reject' ? '驳回原因' : '撤回原因（可选）' }}<b v-if="ask.kind === 'reject'">*</b></label>
            <textarea v-model="ask.note" rows="2" :aria-label="ask.kind === 'reject' ? '驳回原因' : '撤回原因'"></textarea>
            <div v-if="ask.problem" class="err" role="alert">{{ ask.problem }}</div>
          </div>
          <div class="actions">
            <button type="button" class="btn pri" :disabled="busy" @click="confirmAsk(focusDoc)">{{ ask.kind === 'reject' ? '确认驳回' : '确认撤回' }}</button>
            <button type="button" class="btn" @click="ask.kind = ''">取消</button>
          </div>
        </section>

        <div class="detail-grid">
          <div>
            <section class="panel">
              <div class="pt">出差信息</div>
              <div class="kv">
                <div><span>出差人</span>{{ focusDoc.employee_name }}</div>
                <div><span>出差地点</span>{{ focusDoc.travel_destination || '—' }}</div>
                <div><span>日期</span>{{ focusDoc.travel_start_date }} ~ {{ focusDoc.travel_end_date }}（{{ focusDoc.travel_days || 0 }} 天）</div>
                <div><span>所属项目</span>{{ focusDoc.project || '非项目' }}</div>
              </div>
              <h4>出差事由</h4>
              <div class="tv-reason">{{ focusDoc.reason || '—' }}</div>
            </section>
          </div>
          <aside>
            <section class="panel">
              <div class="pt">审批进度</div>
              <div v-for="(item, index) in timeline" :key="item.key" :class="['tl', item.state]">
                <div class="rail"><i></i><span v-if="index < timeline.length - 1"></span></div>
                <div class="body"><b>{{ item.label }}</b><span v-if="item.sub" class="muted">{{ item.sub }}</span><span v-if="item.note" class="note">{{ item.note }}</span></div>
              </div>
              <div v-if="!timeline.length" class="muted">还没有提交审批</div>
            </section>
          </aside>
        </div>
      </template>
    </template>

    <!-- ============================== 新建 / 编辑草稿 ============================== -->
    <template v-else>
      <div class="ph">
        <div>
          <div class="crumb">
            <button v-if="originText" type="button" class="link nav-back" @click="goBack">← 返回{{ originText }}</button>
            <button type="button" class="link" @click="go({})">出差申请</button>
            <template v-if="cameFromList"> › <button type="button" class="link" @click="goBack">列表</button></template>
            › {{ editingName ? `编辑草稿 ${editingName}` : '新建' }}
          </div>
          <h3>{{ editingName ? '编辑出差申请草稿' : '新建出差申请' }}</h3>
        </div>
      </div>
      <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
      <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>

      <div class="new-grid">
        <div class="panel">
          <div class="pt">出差信息</div>
          <div class="form">
            <div class="f"><label>主题<b>*</b></label><input v-model="form.subject" placeholder="如：上海客户拜访" /></div>
            <div class="f"><label>出差地点<b>*</b></label><input v-model="form.travel_destination" /></div>
            <div class="f"><label>出发日期<b>*</b></label><input v-model="form.travel_start_date" type="date" /></div>
            <div class="f"><label>返回日期<b>*</b></label><input v-model="form.travel_end_date" type="date" /></div>
            <div class="f"><label>天数</label><input :value="days ? days + ' 天' : ''" readonly aria-label="天数" /><div class="h">按出发、返回日期自动计算</div></div>
            <div class="f">
              <label>所属项目</label>
              <select v-model="form.project"><option value="">非项目</option><option v-for="project in projects" :key="project" :value="project">{{ project }}</option></select>
            </div>
            <div class="f s2"><label>出差事由<b>*</b></label><textarea v-model="form.reason" rows="3" maxlength="1000"></textarea><div class="h">最多 1000 字</div></div>
          </div>
        </div>

        <aside class="tv-side">
          <section class="panel summary">
            <span class="muted">出差</span>
            <b class="big">{{ days ? days + ' 天' : '—' }}</b>
            <span>{{ lastApplied }}</span>
            <div class="summary-block">
              <span class="muted">提交后的审批路线</span>
              <span class="tv-route"><i>1</i>直属主管</span>
              <span class="tv-route"><i>2</i>副总经理</span>
            </div>
            <div v-if="missingVisible" class="summary-block">
              <span class="muted">还差</span>
              <span v-if="!blockers.length" class="tv-ok">都填好了</span>
              <span v-for="item in blockers" :key="item" class="todo-item">{{ item }}</span>
            </div>
          </section>
          <div class="tv-buttons">
            <button type="button" class="btn pri lg" :disabled="busy" @click="save({ submit: true })">提交审批</button>
            <div class="tv-buttons-row">
              <button type="button" class="btn" :disabled="busy" @click="save()">保存草稿</button>
              <button type="button" class="btn" :disabled="busy" @click="goBack">取消</button>
            </div>
          </div>
        </aside>
      </div>
    </template>
  </div>
</template>
