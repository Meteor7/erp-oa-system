<script setup>
// 采购申请 / 购买申请（2026-09-30 按确认的 demo 改版）：
// 同一个地址用查询参数分页面——无参数 = 首页；?view=list&scope=todo|mine|all = 列表；?request=<单号> = 详情；
// 新建 / 草稿 / PMC 补录是各自的路由（procurement-new、direct-purchase-new、procurement-pmc-edit）。
// 通知和待办里的 ?request= 链接照常打开单据详情。
import { computed, onBeforeUnmount, onMounted, provide, reactive, ref, shallowRef } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../../styles/expenseUi.css';
import '../../styles/procurementUi.css';
import {
  REQUEST_DIRECT, REQUEST_PROCUREMENT, basePathFor, procurementView,
} from '../../lib/procurementView.js';
import { PROC_CTX } from './context.js';
import { apiGet, errText, settle } from './procData.js';
import ProcHome from './ProcHome.vue';
import PurchaseHome from './PurchaseHome.vue';
import ProcList from './ProcList.vue';
import ProcDetail from './ProcDetail.vue';
import ProcForm from './ProcForm.vue';

const props = defineProps({ requestType: { type: String, default: REQUEST_PROCUREMENT } });
const route = useRoute();
const router = useRouter();

const isProcurement = computed(() => props.requestType === REQUEST_PROCUREMENT);
const basePath = computed(() => basePathFor(props.requestType));
const view = computed(() => procurementView(route));
const options = shallowRef(null);
const projects = ref([]);
const applicants = ref([]);
const departments = ref([]);
const purchasers = ref([]);
const ready = ref(false);
const loadError = ref('');
const busy = ref(false);
const banner = reactive({ ok: '', err: '' });
const pane = ref(null);
let timer = null;
let refreshing = false;

function flash(ok = '', err = '') {
  banner.ok = ok;
  banner.err = err;
}

// 列表、详情页之间切换；ok 是跳转后要显示的提示。
function go(query = {}, ok = '') {
  flash();
  router.push({ path: basePath.value, query }).then(() => { if (ok) flash(ok); });
}

function goNew(query = {}, ok = '') {
  flash();
  router.push({ name: isProcurement.value ? 'procurement-new' : 'direct-purchase-new', query }).then(() => { if (ok) flash(ok); });
}

function goPmcEdit(name) {
  flash();
  router.push({ name: 'procurement-pmc-edit', params: { name } });
}

function nameOf(user) {
  const id = String(user || '');
  if (!id) return '';
  const employee = applicants.value.find((item) => item.user && item.user === id);
  if (employee) return employee.employee_name;
  const purchaser = purchasers.value.find((item) => item.name === id);
  if (purchaser) return purchaser.full_name;
  if (id === options.value?.current_applicant?.user && options.value.current_applicant.employee_name) return options.value.current_applicant.employee_name;
  return id.includes('@') ? id.split('@')[0] : id;
}

function projectName(name) {
  const project = projects.value.find((item) => item.name === name);
  return project?.project_name || project?.rd_project_code || name;
}

const ctx = reactive({
  requestType: computed(() => props.requestType),
  label: computed(() => props.requestType),
  isProcurement,
  basePath,
  options,
  globalAccess: computed(() => Boolean(options.value?.procurement_global_access?.[props.requestType])),
  canSubmitForOthers: computed(() => Boolean(options.value?.can_submit_procurement_for_others)),
  canManageCatalog: computed(() => Boolean(options.value?.can_manage_procurement_catalog)),
  currentEmployee: computed(() => options.value?.current_applicant?.employee || ''),
  projects,
  applicants,
  departments,
  purchasers,
  busy,
  banner,
  now: Date.now(),
  flash,
  go,
  goNew,
  goPmcEdit,
  nameOf,
  projectName,
  setBusy(value) { busy.value = value; },
});
provide(PROC_CTX, ctx);

const current = computed(() => {
  if (view.value === 'new' || view.value === 'pmc-edit') return ProcForm;
  if (view.value === 'detail') return ProcDetail;
  if (!isProcurement.value) return PurchaseHome;
  return view.value === 'list' ? ProcList : ProcHome;
});

// 页面状态变了（换单据、换栏目）就重新挂载，各页面从头取数。
// 列表范围 / 阶段 / 搜索词在地址里（scope、stage、status、q），首页和列表自己读地址、自己响应，改它们不重新挂载
// （否则点一下指标卡、打一个字都要重新取数、丢掉输入焦点）；采购申请的列表页换范围才重新挂载。
const paneKey = computed(() => [
  props.requestType, view.value, route.query.request || '', route.params.name || '', route.query.draft || '',
  view.value === 'list' && isProcurement.value ? (route.query.scope || '') : '',
].join('|'));

async function loadLookups() {
  try {
    options.value = await apiGet('oa_entry.get_options');
  } catch (error) {
    loadError.value = errText(error, '页面选项加载失败');
  }
  ready.value = true;
  // 下面这些只是名称映射和表单下拉；取不到不影响浏览。
  projects.value = (await settle(() => apiGet('oa_entry.list_approval_center_projects', { limit: 500 }))).filter((item) => item.status !== 'Cancelled');
  if (isProcurement.value) {
    applicants.value = await settle(() => apiGet('oa_entry.list_procurement_applicants'));
    departments.value = await settle(() => apiGet('oa_entry.list_expense_departments'));
    purchasers.value = await settle(() => apiGet('oa_entry.list_procurement_users'));
  }
}

async function refreshSilently() {
  if (refreshing || busy.value || !['home', 'list', 'detail'].includes(view.value)) return;
  refreshing = true;
  try { await pane.value?.reload?.({ silent: true }); }
  catch (_error) { /* 保留当前数据；用户主动操作时才提示错误 */ }
  finally { refreshing = false; }
}

function refreshWhenVisible() {
  if (document.visibilityState === 'visible') refreshSilently();
}

onMounted(() => {
  loadLookups();
  window.addEventListener('focus', refreshSilently);
  document.addEventListener('visibilitychange', refreshWhenVisible);
  timer = window.setInterval(refreshSilently, 30000);
});

onBeforeUnmount(() => {
  window.removeEventListener('focus', refreshSilently);
  document.removeEventListener('visibilitychange', refreshWhenVisible);
  if (timer) window.clearInterval(timer);
});
</script>

<template>
  <div class="xp pr">
    <div v-if="banner.ok" class="banner ok" role="status">{{ banner.ok }}</div>
    <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>
    <div v-if="loadError" class="banner err" role="alert">{{ loadError }}</div>
    <div v-if="!ready" class="panel empty" aria-live="polite">正在读取{{ requestType }}…</div>
    <component :is="current" v-else :key="paneKey" ref="pane" />
  </div>
</template>
