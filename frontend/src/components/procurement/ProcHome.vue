<script setup>
// 采购申请首页：统计卡片 → 待我处理（不只是 OA 审批）→ 我的 / 最近的申请 →（全局角色）全部走到哪一步了。
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  LIST_LIMIT, approveBlocker, approvalWorkItems, approvalWait, mergeRows, ownedRows, paymentWorkItems, poBreakdown, poWorkItems,
  prWorkItems, priceWorkItems, shortDate, stageDistribution, stageGroups, statusOf, longestWait, waitText, waitedDays,
} from '../../lib/procurementView.js';
import { canCreatePr, canEditPrice, canOpenBoard, canSeePo, canSeePrice, isViceManager } from './access.js';
import { apiGet, errText, loadPurchaseOrders, settle } from './procData.js';
import { useProc } from './context.js';
import PipelineBar from './PipelineBar.vue';

const ctx = useProc();
const router = useRouter();
const home = reactive({ mine: [], pending: [], all: [], loaded: false });
const work = reactive({ pr: [], price: [], po: [], approvals: [], payment: [], poStatus: {}, loaded: false });
const loading = ref(false);
const loadError = ref('');
const now = ctx.now;
const isPmc = canCreatePr();
const isBuyer = canEditPrice();
const isVice = isViceManager();

const listFor = (view) => apiGet('oa_entry.list_requests', { view, request_type: ctx.requestType, limit: LIST_LIMIT });

async function loadOa() {
  // “全部”服务端按权限限定（非全局角色只拿到自己提的、经手的、自己负责的项目里别人提的）。
  const [mine, pending, all] = await Promise.all([listFor('mine'), listFor('pending'), listFor('all')]);
  Object.assign(home, { mine: mine || [], pending: pending || [], all: all || [], loaded: true });
}

// 提 PR / 比价 / 用印 / 提交付款这些不是 OA 审批节点，要从 PR、价格审批、PO 里汇总；
// 每一组各自取，没有权限（403）或功能没开就只是不显示这一组。
async function loadWork() {
  const jobs = [];
  if (isPmc) {
    jobs.push(settle(async () => {
      const result = await apiGet('material_progress.list_material_progress', { limit: 200 });
      work.pr = prWorkItems(result?.items || []);
    }));
  }
  if (isBuyer) {
    jobs.push(settle(async () => {
      const [prs, drafts] = await Promise.all([
        settle(() => apiGet('procurement_chain.list_prs', { limit: 200 })),
        settle(() => apiGet('procurement_chain.list_price_approvals', { status: '草稿', limit: 200 })),
      ]);
      work.price = priceWorkItems({ prs, drafts });
    }));
    jobs.push(settle(async () => {
      work.payment = paymentWorkItems(await apiGet('procurement_chain.list_payment_work_items', { limit: 500 }));
    }));
  }
  if (canSeePo() || canSeePrice()) {
    jobs.push(settle(async () => {
      const orders = await loadPurchaseOrders();
      work.poStatus = Object.fromEntries(orders.map((po) => [po.name, po.status]));
      work.po = poWorkItems(orders, { manage: isBuyer, seal: isVice });
    }));
  }
  if (isVice) {
    jobs.push(settle(async () => {
      work.approvals = approvalWorkItems(await apiGet('procurement_chain.list_price_approvals', { status: '待审批', limit: 200 }));
    }));
  }
  await Promise.all(jobs);
  work.loaded = true;
}

async function load({ silent = false } = {}) {
  if (!silent) loading.value = true;
  try {
    await loadOa();
    await loadWork();
    loadError.value = '';
  } catch (error) {
    loadError.value = errText(error, '业务单据加载失败');
    if (silent) ctx.flash('', loadError.value);
  } finally {
    loading.value = false;
  }
}

onMounted(() => load());
defineExpose({ reload: load });

const related = computed(() => mergeRows(ctx.requestType, home.mine, home.pending, home.all));
const owned = computed(() => ownedRows(home.all, ctx.currentUser, ctx.currentEmployee));
const peers = computed(() => (ctx.globalAccess ? home.all : related.value));
const mineGroups = computed(() => stageGroups(home.mine));
const allGroups = computed(() => stageGroups(peers.value));
const sumItems = (items) => items.reduce((total, item) => total + Number(item.count || 0), 0);
const prRequests = computed(() => work.pr.length);
const quotePending = computed(() => work.price.filter((item) => item.tag === '待比价'));
const sealItems = computed(() => work.po.filter((item) => item.tag === '电子用印'));

const stats = computed(() => {
  const todo = home.pending;
  const cards = [{
    key: 'todo', label: '待我审批', count: todo.length, unit: '张', tone: '#D98C4A', query: { view: 'list', scope: 'todo' },
    hint: todo.length ? `最久等了 ${longestWait(todo, now)} 天` : '没有要你审批的',
  }];
  if (isPmc) {
    cards.push({ key: 'pr', label: '待提 PR', count: sumItems(work.pr), unit: '项物料', tone: '#E3B26B', to: { path: '/approval/material-progress' }, hint: prRequests.value ? `来自 ${prRequests.value} 张申请，去物料看板提` : '没有要提 PR 的物料' });
  }
  if (isBuyer) {
    cards.push({ key: 'quote', label: '待比价', count: sumItems(quotePending.value), unit: '项物料', tone: '#E3B26B', to: { name: 'procurement-price-approvals', query: { view: 'source' } }, hint: quotePending.value.length ? `${quotePending.value.length} 张 PR 还没比价` : '没有要比价的物料' });
    cards.push({ key: 'pay', label: '待提交付款审批', count: work.payment.length, unit: '期', tone: '#D98C4A', to: { path: '/approval/procurement-payment' }, hint: work.payment[0]?.subject || '没有可提交的期次' });
  }
  if (isVice) {
    cards.push({ key: 'price', label: '待审批 · 价格', count: work.approvals.length, unit: '张', tone: '#D98C4A', to: { name: 'procurement-price-approvals' }, hint: work.approvals[0]?.subject || '没有要你审批的价格审批' });
    cards.push({ key: 'seal', label: '待电子用印', count: sealItems.value.length, unit: '份', tone: '#C3CAD6', to: { name: 'procurement-price-approvals', query: { tab: 'po' } }, hint: sealItems.value[0]?.subject || '' });
  }
  if (ctx.globalAccess) {
    cards.push({ key: 'demand', label: '全部 · 需求审批中', count: allGroups.value.demand, unit: '张', tone: '#5470C6', query: { view: 'list', scope: 'all', stage: 'demand' }, hint: '' });
    // 指标卡的数字是按阶段合并统计的（执行中 = 提 PR + 比价 + 价格审批 + PO），点进列表按同一口径筛（stage=exec / back），不再是"全部"。
    cards.push({ key: 'exec', label: '全部 · 采购执行中', count: allGroups.value.exec, unit: '张', tone: '#7FA38E', query: { view: 'list', scope: 'all', stage: 'exec' }, hint: '提 PR、比价、PO 都算' });
  } else {
    if (owned.value.length) {
      const executing = stageGroups(owned.value).exec;
      cards.push({ key: 'owned', label: '我负责的项目 · 申请', count: owned.value.length, unit: '张', tone: '#8DB4EE', query: { view: 'list', scope: 'owned' }, hint: `其中采购执行中 ${executing} 张 · 只读` });
    }
    cards.push({ key: 'back', label: '退回 / 已撤回', count: mineGroups.value.back, unit: '张', tone: '#C3CAD6', query: { view: 'list', scope: 'mine', stage: 'back' }, hint: mineGroups.value.back ? '修改后重新提交' : '没有要处理的' });
    cards.push({ key: 'demand', label: '我的 · 需求审批中', count: mineGroups.value.demand, unit: '张', tone: '#5470C6', query: { view: 'list', scope: 'mine', stage: 'demand' }, hint: '点进去看卡在谁那里' });
    cards.push({ key: 'exec', label: '我的 · 采购执行中', count: mineGroups.value.exec, unit: '张', tone: '#E3B26B', query: { view: 'list', scope: 'mine', stage: 'exec' }, hint: '可以看到数量和进度' });
  }
  return cards;
});

function openCard(card) {
  if (card.to) router.push(card.to);
  else ctx.go(card.query);
}

const todo = computed(() => {
  const oa = [...home.pending]
    .sort((a, b) => (waitedDays(b, now) ?? -1) - (waitedDays(a, now) ?? -1))
    .map((row) => ({
      key: `oa:${row.name}`, tag: 'OA 审批', tone: 'p-cobalt', subject: row.subject || '（无主题）',
      meta: `${row.employee_name || ''} · ${row.department || ''} · ${row.name}${row.current_step_label ? ` · ${row.current_step_label}` : ''}`,
      action: approveBlocker(row) ? '补录并审批' : '审批', request: row.name, wait: approvalWait(row, now),
    }));
  const other = [...work.pr, ...work.price, ...work.approvals, ...work.po, ...work.payment];
  return [...oa, ...other];
});
const todoTop = computed(() => todo.value.slice(0, 8));

const mineTitle = computed(() => {
  if (ctx.globalAccess) return '最近的采购申请';
  return home.mine.length ? '我的采购申请' : '与我相关';
});
const mineRows = computed(() => (ctx.globalAccess ? home.all : (home.mine.length ? home.mine : related.value)).slice(0, 5));
const distribution = computed(() => stageDistribution(home.all, work.poStatus));
const poParts = computed(() => poBreakdown(home.all, work.poStatus));

function openRow(row) {
  if (row.workflow_status === '草稿') ctx.goNew({ draft: row.name });
  else ctx.go({ request: row.name });
}

function openItem(item) {
  if (item.request) ctx.go({ request: item.request });
  else router.push(item.to);
}
</script>

<template>
  <div class="pr-home">
    <div class="ph">
      <div>
        <div class="crumb">审批中心 · 采购/购买申请</div>
        <h3>采购申请</h3>
        <div class="muted">项目和研发要用的物料。需求批下来后由 PMC 提 PR，采购比价、价格审批、签 PO，到货验收后付款。</div>
      </div>
      <div class="head-actions">
        <button v-if="canOpenBoard()" type="button" class="btn" @click="router.push('/approval/material-progress')">物料进度看板</button>
        <button v-if="canSeePrice()" type="button" class="btn" @click="router.push({ name: 'procurement-price-approvals' })">价格审批</button>
        <button type="button" class="btn pri lg" @click="ctx.goNew()">＋ 新建采购申请</button>
      </div>
    </div>

    <div v-if="loading && !home.loaded" class="panel empty" aria-live="polite">正在读取申请和待办，请稍候</div>
    <div v-else-if="loadError && !home.loaded" class="panel empty" role="alert">
      业务单据加载失败：{{ loadError }} <button type="button" class="link" @click="load()">重新加载</button>
    </div>
    <template v-else>
      <div class="stat-cards">
        <button v-for="card in stats" :key="card.key" type="button" class="stat-card" @click="openCard(card)">
          <span class="l"><i :style="{ background: card.tone }"></i>{{ card.label }}</span>
          <span class="v"><b>{{ card.count }}</b> {{ card.unit }}</span>
          <span class="l">{{ card.hint }}</span>
        </button>
      </div>

      <section v-if="ctx.globalAccess" class="panel">
        <div class="pt">
          <span>全部采购申请走到哪一步了 <span class="muted">{{ home.all.length }} 张 · 每张取最靠前的阶段，点一格看这些单据</span></span>
          <button v-if="canOpenBoard()" type="button" class="link" @click="router.push('/approval/material-progress')">按物料看进度 → 物料进度看板</button>
        </div>
        <div class="pr-chain-cells">
          <button v-for="cell in distribution" :key="cell.key" type="button" :class="['pr-chain-cell', { hot: cell.key === 'po' && cell.count, zero: !cell.count }]" @click="ctx.go({ view: 'list', scope: 'all', stage: cell.key })">
            <span class="muted">{{ cell.no }}</span>
            <b>{{ cell.label }}</b>
            <span class="n">{{ cell.count }}</span>
            <span class="muted">{{ cell.sub || ' ' }}</span>
          </button>
        </div>
        <div v-if="poParts.length" class="pr-subline muted">
          <span>PO 执行中的 {{ distribution[4].count }} 张：</span>
          <span v-for="part in poParts" :key="part.label" class="pill p-gray">{{ part.label }} {{ part.count }}</span>
        </div>
        <div class="muted foot">按最近 {{ LIST_LIMIT }} 张统计。</div>
      </section>

      <div class="home-grid">
        <section class="panel">
          <div class="pt">
            <span>待我处理 <span class="count-pill">{{ todo.length }}</span></span>
            <span class="muted">不只是 OA 审批：提 PR、比价、用印、提交付款也在这</span>
          </div>
          <div v-for="item in todoTop" :key="item.key" class="todo-row pr-todo">
            <span :class="['pill', item.tone]">{{ item.tag }}</span>
            <div class="grow-col"><b class="ellipsis">{{ item.subject }}</b><span class="muted ellipsis">{{ item.meta }}</span></div>
            <span :class="['wait', { warn: (item.wait || 0) >= 3 }]">{{ item.request ? waitText(item.wait) : '' }}</span>
            <span class="row-actions"><button type="button" class="btn sm dark" @click="openItem(item)">{{ item.action }}</button></span>
          </div>
          <div v-if="!todo.length" class="empty">没有要你处理的事项。</div>
          <div v-else-if="todo.length > todoTop.length" class="muted foot">只列前 {{ todoTop.length }} 项，其余请到对应页面处理。</div>
        </section>

        <section class="panel">
          <div class="pt">
            <span>{{ mineTitle }}</span>
            <button type="button" class="link" @click="ctx.go({ view: 'list', scope: ctx.globalAccess ? 'all' : 'mine' })">全部 →</button>
          </div>
          <button v-for="row in mineRows" :key="row.name" type="button" class="mine-row" @click="openRow(row)">
            <span class="grow-col"><span class="ellipsis">{{ row.subject || '（无主题）' }}</span><span class="muted">{{ row.name }} · {{ shortDate(row.creation) }} · {{ (row.business_lines || []).length }} 项<template v-if="row.employee_name && row.employee !== ctx.currentEmployee"> · {{ row.employee_name }}</template></span><PipelineBar :row="row" :now="now" where /></span>
            <span :class="['pill', statusOf(row).tone]">{{ statusOf(row).label }}</span>
          </button>
          <div v-if="!mineRows.length" class="empty">还没有，点右上角新建</div>
        </section>
      </div>
    </template>
  </div>
</template>
