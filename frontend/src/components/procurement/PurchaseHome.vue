<script setup>
// 购买申请首页（含列表）：统计卡片、待我处理、批下来的额度用了多少、购买申请列表（我的 / 待我处理 / 全部）。
// 详情页和采购申请详情是同一个样子（ProcDetail），只是没有采购链阶段条和执行明细。
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../../styles/navUi.css';
import {
  LIST_LIMIT, PAGE_SIZE, canActOn, canWithdrawRow, currentStepKey, draftHint, draftKind, filterPurchaseStatus, isActive, listScope,
  longestWait, mergeRows, money, normalizePurchaseStatus, pageCount, pageSlice, projectText, purchaseStatus, purchaseStatusLabel,
  shortDate, waitText, waitedDays,
} from '../../lib/procurementView.js';
import { cleanQuery, detailQuery, formQuery, hereAsFrom, originOf } from '../../lib/navContext.js';
import { apiGet, apiPost, errText, settle } from './procData.js';
import { useProc } from './context.js';

const ctx = useProc();
const route = useRoute();
const router = useRouter();
const home = reactive({ mine: [], pending: [], all: [], quotas: [], loaded: false });
const loading = ref(false);
const now = ctx.now;
const page = ref(0);
const acted = reactive({});
// 查看范围、状态筛选、搜索词都在地址里（scope、status、q）：点进详情再回来、刷新、分享链接都还是同一份列表。
const scope = computed(() => listScope(route.query, 'mine'));
const statusKey = computed(() => normalizePurchaseStatus(route.query.status));
const search = ref(String(route.query.q || ''));
const listBox = ref(null);

// 只改列表状态的那几项，其余查询（view=list 用来滚动到列表）原样保留；用 replace，不增加历史记录。
function setListQuery(patch) {
  const next = { ...route.query, ...patch };
  for (const key of Object.keys(next)) if (next[key] === '' || next[key] === undefined || next[key] === null) delete next[key];
  router.replace({ path: route.path, query: next });
}
const listFilters = computed(() => cleanQuery({ scope: scope.value, status: statusKey.value, q: search.value, origin: originOf(route.query) }));

const listFor = (view) => apiGet('oa_entry.list_requests', { view, request_type: ctx.requestType, limit: LIST_LIMIT });

async function load({ silent = false } = {}) {
  if (!silent) loading.value = true;
  try {
    const [mine, pending, all] = await Promise.all([listFor('mine'), listFor('pending'), ctx.globalAccess ? listFor('all') : []]);
    // 额度来自报销 / 付款能关联的购买申请（只列还有剩余额度的）；功能没开或没有权限就不显示这一块。
    const linkable = await settle(() => apiGet('expense_claim_entry.list_linkable_applications', { request_type: '报销单' }));
    Object.assign(home, {
      mine: mine || [], pending: pending || [], all: all || [], loaded: true,
      quotas: linkable.filter((item) => item.request_type === ctx.requestType),
    });
  } catch (error) {
    ctx.flash('', errText(error, '加载失败'));
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await load();
  if (route.query.view === 'list' && listBox.value?.scrollIntoView) listBox.value.scrollIntoView({ block: 'start' });
});
defineExpose({ reload: load });

const related = computed(() => mergeRows(ctx.requestType, home.mine, home.pending));
const todo = computed(() => home.pending.filter((row) => canActOn(row, acted, 'can_approve') || canActOn(row, acted, 'can_reject')));
const quotaOf = computed(() => Object.fromEntries(home.quotas.map((item) => [item.name, item])));
const sum = (rows) => rows.reduce((total, row) => total + Number(row.amount || 0), 0);
const mineBy = (test) => home.mine.filter(test);
const pendingPay = computed(() => mineBy((row) => row.workflow_status === '已完成' && ['待付款', '部分付款'].includes(row.business_status)));

const stats = computed(() => {
  const back = mineBy((row) => draftKind(row));
  const review = mineBy((row) => isActive(row));
  const wait = longestWait(todo.value, now);
  // 每张卡带着范围和状态：点进去只看这一类（原来只切到"我的"，草稿、审批中、待付款都是同一份列表）。
  return [
    { key: 'todo', label: '待我审批', count: todo.value.length, amount: sum(todo.value), tone: '#D98C4A', scope: 'todo', status: '', hint: todo.value.length ? `最久等了 ${wait} 天` : '没有要你审批的' },
    { key: 'back', label: '我的草稿 / 退回', count: back.length, amount: sum(back), tone: '#C3CAD6', scope: 'mine', status: 'draft', hint: back.length ? '继续编辑后重新提交' : '没有要处理的' },
    { key: 'review', label: '我的 · 审批中', count: review.length, amount: sum(review), tone: '#5470C6', scope: 'mine', status: 'review', hint: review.length ? '审批中还可以撤回' : '' },
    { key: 'pay', label: '已批准 · 待付款', count: pendingPay.value.length, amount: sum(pendingPay.value), tone: '#E3B26B', scope: 'mine', status: 'topay', hint: pendingPay.value.length ? '可以用它发起报销或付款' : '' },
  ];
});

const scopes = computed(() => [
  { key: 'mine', label: '我的', count: home.mine.length },
  { key: 'todo', label: '待我处理', count: todo.value.length },
  { key: 'all', label: ctx.globalAccess ? '全部' : '与我相关', count: (ctx.globalAccess ? home.all : related.value).length },
]);
const base = computed(() => ({ mine: home.mine, todo: todo.value, all: ctx.globalAccess ? home.all : related.value }[scope.value] || []));
const rows = computed(() => {
  const text = search.value.trim().toLowerCase();
  const byStatus = filterPurchaseStatus(base.value, statusKey.value);
  if (!text) return byStatus;
  return byStatus.filter((row) => [row.name, row.subject, row.employee_name, ...(row.business_lines || []).map((line) => line.item_name)].join(' ').toLowerCase().includes(text));
});
const pages = computed(() => pageCount(rows.value.length));
const shown = computed(() => pageSlice(rows.value, Math.min(page.value, pages.value - 1)));
watch([scope, statusKey, search], () => { page.value = 0; });
// 搜索词同步进地址；地址变了（后退）再同步回来。
watch(search, (value) => setListQuery({ q: value }));
watch(() => route.query.q, (value) => { if (String(value || '') !== search.value) search.value = String(value || ''); });

// 换范围就清掉状态筛选（状态只对"我的"有意义）。
function pickScope(key, status = '') {
  setListQuery({ scope: key, status });
  listBox.value?.scrollIntoView?.({ block: 'nearest' });
}

function openStat(card) {
  pickScope(card.scope, card.status);
}

// 从列表点进详情 / 表单：带上范围、状态、搜索词，返回时原样恢复。
function open(row) {
  if (row.workflow_status === '草稿' && scope.value === 'mine') ctx.goNew(formQuery({ draft: row.name }, listFilters.value));
  else ctx.go(detailQuery(row.name, listFilters.value));
}

// 用它报销 / 用它付款：目标页先弹出"确定要创建草稿吗"；from 让它取消时回到这里。
function pushTo(path, source) {
  router.push({ path, query: { view: 'new', source, from: hereAsFrom(route.path, route.query) } });
}

function nextText(row) {
  const quota = quotaOf.value[row.name];
  if (isActive(row)) return `${row.current_step_label || '审批中'}${canWithdrawRow(row, ctx.currentEmployee) ? ' · 审批中可撤回' : ''}`;
  if (row.workflow_status === '草稿') return draftHint(row);
  if (row.workflow_status === '已完成' && ['待付款', '部分付款'].includes(row.business_status)) {
    if (quota && Number(quota.reserved_amount) > 0) return `已有付款单占用 ¥ ${money(quota.reserved_amount)}`;
    return '已批准，可用它发起报销或付款；批准后不能撤回';
  }
  return row.business_status || '—';
}

// 首页上的"同意"：只给普通审批节点；要办理的节点进详情页处理。
function quickApprove(row) {
  return Boolean(row.can_approve) && row.current_step_mode !== 'handle';
}

async function approve(row) {
  if (ctx.busy) return;
  ctx.setBusy(true);
  ctx.flash();
  try {
    await apiPost('oa_entry.action_request', { name: row.name, action: 'approve', expected_step_key: row.current_step_key || '' });
    acted[row.name] = currentStepKey(row);
    ctx.flash(`${row.name} 已审批通过`);
    await load({ silent: true });
  } catch (error) {
    ctx.flash('', errText(error, '审批操作失败'));
    await load({ silent: true });
  } finally {
    ctx.setBusy(false);
  }
}

const usedPercent = (quota, key) => {
  const approved = Number(quota.approved_amount || 0);
  return approved > 0 ? `${Math.min(100, (Number(quota[key] || 0) / approved) * 100).toFixed(1)}%` : '0%';
};
</script>

<template>
  <div class="pr-home pr-purchase">
    <div class="ph">
      <div>
        <div class="crumb">审批中心 · 采购/购买申请</div>
        <h3>购买申请</h3>
        <div class="muted">京东或其他渠道的小额购买。批下来后，凭它报销（自己垫付）或付款（公司付给商家）。</div>
      </div>
      <div class="head-actions"><button type="button" class="btn pri lg" @click="ctx.goNew(formQuery({}, listFilters))">＋ 新建购买申请</button></div>
    </div>

    <div v-if="loading && !home.loaded" class="panel empty" aria-live="polite">正在加载…</div>
    <template v-else>
      <div class="stat-cards">
        <button v-for="card in stats" :key="card.key" type="button" class="stat-card" @click="openStat(card)">
          <span class="l"><i :style="{ background: card.tone }"></i>{{ card.label }}</span>
          <span class="v"><b>{{ card.count }}</b> 张<em v-if="card.amount">¥ {{ money(card.amount) }}</em></span>
          <span class="l">{{ card.hint || ' ' }}</span>
        </button>
      </div>

      <div class="home-grid pr-even">
        <section class="panel">
          <div class="pt"><span>待我处理 <span class="count-pill">{{ todo.length }}</span></span><button type="button" class="link" @click="pickScope('todo')">全部 →</button></div>
          <div v-for="row in todo.slice(0, 5)" :key="row.name" class="todo-row">
            <span class="avatar">{{ (row.employee_name || '?').slice(0, 1) }}</span>
            <div class="grow-col"><b class="ellipsis">{{ row.subject || '（无主题）' }}</b><span class="muted ellipsis">{{ row.employee_name }} · {{ row.department }} · {{ row.purchase_method }} · {{ row.current_step_label }}</span></div>
            <span class="amount">¥ {{ money(row.amount) }}</span>
            <span :class="['wait', { warn: (waitedDays(row, now) || 0) >= 3 }]">{{ waitText(waitedDays(row, now)) }}</span>
            <span class="row-actions">
              <button type="button" class="btn sm" @click="ctx.go({ request: row.name })">看详情</button>
              <button v-if="quickApprove(row)" type="button" class="btn sm dark" :disabled="ctx.busy" @click="approve(row)">同意</button>
            </span>
          </div>
          <div v-if="!todo.length" class="empty">没有需要你处理的购买申请</div>
          <div v-else class="muted foot">详情页和采购申请详情同一个样子：顶部审批按钮，左边基本信息和购买明细，右边审批进度和资料。</div>
        </section>

        <section class="panel">
          <div class="pt"><span>批下来的额度用了多少</span><span class="muted">我的 · 已通过</span></div>
          <div v-for="quota in home.quotas" :key="quota.name" class="pr-quota">
            <div class="split"><b>{{ quota.subject || quota.name }}</b><span><b>¥ {{ money(Number(quota.paid_amount || 0) + Number(quota.reserved_amount || 0)) }}</b><span class="muted"> / ¥ {{ money(quota.approved_amount) }}</span></span></div>
            <div class="pr-track"><i class="paid" :style="{ width: usedPercent(quota, 'paid_amount') }"></i><i class="reserved" :style="{ width: usedPercent(quota, 'reserved_amount') }"></i></div>
            <div class="split muted">
              <span>{{ quota.name }} · 已占用 ¥ {{ money(quota.reserved_amount) }} · 已付款 ¥ {{ money(quota.paid_amount) }} · 状态 {{ quota.business_status }}</span>
              <span class="links">
                <button type="button" class="link" @click="pushTo('/approval/claim', quota.name)">用它报销 →</button>
                <button type="button" class="link" @click="pushTo('/approval/payment', quota.name)">用它付款 →</button>
              </span>
            </div>
          </div>
          <div v-if="!home.quotas.length" class="empty">没有还有额度的已批准购买申请</div>
        </section>
      </div>

      <section ref="listBox" class="panel flush">
        <div class="pr-listhead">
          <h3>购买申请</h3>
          <div class="seg">
            <button v-for="item in scopes" :key="item.key" type="button" :aria-pressed="scope === item.key" @click="pickScope(item.key)">{{ item.label }} {{ item.count }}</button>
          </div>
          <input v-model="search" type="search" class="pr-search" placeholder="搜索单号、主题、物品" aria-label="搜索" />
        </div>
        <div v-if="statusKey" class="nav-filters pr-pad" data-testid="status-filter">
          <span class="nav-filter">筛选：{{ purchaseStatusLabel(statusKey) }}<button type="button" aria-label="清除状态筛选" @click="setListQuery({ status: '' })">×</button></span>
        </div>
        <div class="tbl">
          <table class="pr-table">
            <thead><tr><th>主题 / 单号</th><th>购买方式</th><th>项目</th><th class="r">金额</th><th>状态</th><th>当前节点 / 后续</th></tr></thead>
            <tbody>
              <tr v-for="row in shown" :key="row.name" class="row-sel" @click="open(row)">
                <td>
                  <button type="button" class="link strong pr-subject" @click.stop="open(row)">{{ row.subject || '（无主题）' }}</button>
                  <span v-if="row.urgency === '加急'" class="pill p-red pr-urgent">加急</span>
                  <div class="muted">{{ row.name }} · {{ shortDate(row.creation) }} · {{ (row.business_lines || []).length }} 件物品<template v-if="scope !== 'mine'"> · {{ row.employee_name }}</template></div>
                </td>
                <td>{{ row.purchase_method || '—' }}</td>
                <td class="ellipsis-cell">{{ projectText(row, ctx.projectName).replace('非项目', '非项目购买') }}</td>
                <td class="r num strong">¥ {{ money(row.amount) }}</td>
                <td><span :class="['pill', purchaseStatus(row).tone]">{{ purchaseStatus(row).label }}</span></td>
                <td class="pr-next">{{ nextText(row) }}</td>
              </tr>
              <tr v-if="!shown.length"><td colspan="6" class="empty">{{ scope === 'todo' ? '没有要你审批的购买申请' : '没有符合条件的购买申请' }}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="pr-foot">
          <span class="muted">共 {{ rows.length }} 张 · 每页 {{ PAGE_SIZE }} 张<template v-if="base.length >= LIST_LIMIT"> · 只取了最近 {{ LIST_LIMIT }} 张</template></span>
          <span class="row-actions">
            <button type="button" class="btn sm" :disabled="page === 0" @click="page -= 1">上一页</button>
            <span class="muted pr-pageno">第 {{ Math.min(page, pages - 1) + 1 }} / {{ pages }} 页</span>
            <button type="button" class="btn sm" :disabled="page >= pages - 1" @click="page += 1">下一页</button>
          </span>
        </div>
      </section>
    </template>
  </div>
</template>
