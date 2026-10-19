<script setup>
// 付款审批单：顶部是单据队列（全公司可见的人看全部，其他人看“我的 + 待我处理”，每页 50 张），下面是选中的审批单。
// ?request= 精确打开某一张；30 秒和窗口重新获得焦点时静默刷新。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { useRoute, useRouter } from 'vue-router';
import {
  isActionable, mergeRequestRows, money, queueFilter, sortQueue, waitText, waitedDays, requestTone,
} from '../../lib/paymentView.js';
import { OA_API, PAYMENT_REQUEST_TYPE, errorText } from './paymentApi.js';
import PayApprovalPage from './PayApprovalPage.vue';

const props = defineProps({
  active: { type: Boolean, default: true },
  options: { type: Object, default: null },
  workItems: { type: Array, default: () => [] },
  workReady: { type: Boolean, default: true },
  groups: { type: Array, default: () => [] },
  canWork: { type: Boolean, default: false },
  reloadWork: { type: Function, required: true },
});
const emit = defineEmits(['count']);

const route = useRoute();
const router = useRouter();
const pageSize = 50;
const page = ref(0);
const params = (view) => () => ({ view, request_type: PAYMENT_REQUEST_TYPE, limit: pageSize, offset: page.value * pageSize });
// 队列加载器都不自动加载：等 get_options 回来知道有没有全局权限后再加载（避免重复请求）。
const exactLoader = createResource({ url: OA_API + 'list_requests', method: 'GET' });
const mineLoader = createResource({ url: OA_API + 'list_requests', method: 'GET', makeParams: params('mine') });
const pendingLoader = createResource({ url: OA_API + 'list_requests', method: 'GET', makeParams: params('pending') });
const allLoader = createResource({ url: OA_API + 'list_requests', method: 'GET', makeParams: params('all') });

const selectedName = ref(String(route.query.request || ''));
const filter = ref('all');
const error = ref('');
const refreshing = ref(false);
let timer = null;

const globalAccess = computed(() => Boolean(props.options?.procurement_global_access?.[PAYMENT_REQUEST_TYPE]));
const canManageExpense = computed(() => Boolean(props.options?.can_manage_expense));
const rows = computed(() => sortQueue(mergeRequestRows(mineLoader.data || [], pendingLoader.data || [], allLoader.data || [])));
const myEmployee = computed(() => String(props.options?.current_applicant?.employee || ''));
const visible = computed(() => queueFilter(rows.value, filter.value, { employee: myEmployee.value }));
const mineCount = computed(() => queueFilter(rows.value, 'mine', { employee: myEmployee.value }).length);
const loading = computed(() => Boolean(mineLoader.loading || pendingLoader.loading || allLoader.loading));
const loadError = computed(() => mineLoader.error || pendingLoader.error || allLoader.error || null);
const hasMore = computed(() => (globalAccess.value
  ? (allLoader.data || []).length === pageSize
  : (mineLoader.data || []).length === pageSize || (pendingLoader.data || []).length === pageSize));
const selected = computed(() => {
  const name = selectedName.value;
  if (name) {
    const exact = exactLoader.data?.[0];
    return (exact && exact.name === name ? exact : null) || rows.value.find((row) => row.name === name) || null;
  }
  return visible.value[0] || rows.value[0] || null;
});
const todoCount = computed(() => rows.value.filter(isActionable).length);
const now = Date.now();

watch(() => rows.value.length, (n) => emit('count', n), { immediate: true });

async function loadQueues() {
  if (!props.options) return;
  if (globalAccess.value) await allLoader.reload();
  else await Promise.all([mineLoader.reload(), pendingLoader.reload()]);
}
async function loadExact() {
  const name = selectedName.value;
  if (!name) return;
  try { await exactLoader.fetch({ view: 'all', request_type: PAYMENT_REQUEST_TYPE, name, limit: 1 }); } catch (err) { error.value = errorText(err, '无法加载申请详情'); }
}
async function reloadAll() {
  error.value = '';
  try { await Promise.all([loadQueues(), loadExact(), props.canWork ? props.reloadWork() : Promise.resolve()]); } catch (err) { error.value = errorText(err, '付款审批单加载失败'); }
}
async function refresh() {
  if (refreshing.value) return;
  refreshing.value = true;
  try { await Promise.all([loadQueues(), loadExact()]); } catch (_) { /* 静默刷新失败时保留当前数据；点操作时会提示错误。 */ } finally { refreshing.value = false; }
}
async function changePage(delta) {
  page.value += delta;
  selectedName.value = '';
  await loadQueues();
}
function select(name) {
  selectedName.value = String(name || '');
  router.replace({ path: route.path, query: { tab: 'approvals', request: name } });
}

watch(() => props.options, async (options, previous) => { if (options && !previous) await loadQueues(); }, { immediate: true });
watch(selectedName, () => { loadExact(); }, { immediate: true });
watch(() => route.query.request, (name) => { if (name && String(name) !== selectedName.value) selectedName.value = String(name); });

function onVisible() { if (document.visibilityState === 'visible') refresh(); }
onMounted(() => {
  window.addEventListener('focus', refresh);
  document.addEventListener('visibilitychange', onVisible);
  timer = window.setInterval(refresh, 30000);
});
onBeforeUnmount(() => {
  window.removeEventListener('focus', refresh);
  document.removeEventListener('visibilitychange', onVisible);
  if (timer) window.clearInterval(timer);
});
defineExpose({ refresh, reloadAll });
</script>

<template>
  <div class="pay-approvals">
    <div v-if="error" class="banner err" role="alert">{{ error }}</div>
    <p class="muted pay-note">采购付款单由 PO 付款计划下推生成，不能单独新建；在“付款工作项”里条件满足后由采购提交付款审批。</p>

    <div class="filter-bar pay-filters">
      <button type="button" class="chip" :class="{ on: filter === 'all' }" @click="filter = 'all'">全部<span class="pay-chip-n">{{ rows.length }}</span></button>
      <button type="button" class="chip" :class="{ on: filter === 'todo' }" @click="filter = 'todo'">待我处理<span class="pay-chip-n">{{ todoCount }}</span></button>
      <button type="button" class="chip" :class="{ on: filter === 'mine' }" @click="filter = 'mine'">我提交的<span class="pay-chip-n">{{ mineCount }}</span></button>
      <span class="muted pay-page">
        <button type="button" class="btn sm" :disabled="page === 0 || loading" @click="changePage(-1)">上一页</button>
        第 {{ page + 1 }} 页
        <button type="button" class="btn sm" :disabled="!hasMore || loading" @click="changePage(1)">下一页</button>
      </span>
    </div>

    <div class="pay-queue">
      <button v-for="row in visible" :key="row.name" type="button" class="pay-queue-card" :class="{ on: selected && selected.name === row.name, todo: isActionable(row) }" @click="select(row.name)">
        <span class="split"><b>{{ row.name }}</b><span class="muted">{{ ['待审批', '待办理'].includes(row.workflow_status) ? waitText(waitedDays(row, now)) : '' }}</span></span>
        <span class="pay-queue-subject">{{ row.subject || '未填写主题' }}</span>
        <span class="split">
          <span class="muted">{{ row.current_step_label || row.business_status || '—' }}</span>
          <span class="pill" :class="`p-${requestTone(row.workflow_status)}`">{{ row.workflow_status }}</span>
        </span>
        <span class="split"><span class="muted">{{ row.employee_name }}</span><b v-if="Number(row.amount || 0) > 0">{{ money(row.amount) }}</b></span>
      </button>
      <div v-if="loading && !rows.length" class="panel empty" aria-live="polite">正在读取申请和待办，请稍候</div>
      <div v-else-if="loadError && !rows.length" class="panel empty" role="alert">
        业务单据加载失败 <button type="button" class="btn sm" @click="reloadAll">重新加载</button>
      </div>
      <div v-else-if="!visible.length" class="panel empty">{{ rows.length ? '当前筛选暂无单据' : '暂无申请或待办' }}</div>
    </div>

    <PayApprovalPage
      v-if="active && selected"
      :request="selected"
      :work-items="workItems"
      :work-ready="workReady"
      :groups="groups"
      :can-work="canWork"
      :can-manage-expense="canManageExpense"
      @changed="reloadAll"
    />
    <div v-else-if="active && (loading || exactLoader.loading)" class="panel empty" aria-live="polite">正在加载单据…</div>
    <div v-else-if="active" class="panel empty">选择上面的单据查看完整审批内容</div>
  </div>
</template>
