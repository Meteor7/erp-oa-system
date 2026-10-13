<script setup>
// 审批中心的分组首页：采购/购买申请、付款申请。上面是我要处理的、我提交的和快捷新建，下面是原来的看板。
// 子页面（采购申请、购买申请、出差、报销、付款…）不变；这里只做汇总，每张单点开还是各自类型的页面。
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../styles/expenseUi.css';
import '../styles/groupHomeUi.css';
import PaymentBoard from './PaymentBoard.vue';
import RequestBoard from './RequestBoard.vue';
import { GROUPS, MINE_LIMIT, buildGroupHome, listLinkFor } from '../lib/approvalGroup.js';
import { canSee, inMenu } from '../lib/access.js';
import { boardRoute, focusAnchor } from '../lib/expenseBoards.js';
import { callApi } from '../lib/expenseClaims.js';
import { hereAsFrom } from '../lib/navContext.js';
import { emptyWork, loadProcurementWork } from '../components/procurement/work.js';

const props = defineProps({ group: { type: String, default: 'request' } });
const route = useRoute();
const router = useRouter();
const config = computed(() => GROUPS[props.group] || GROUPS.request);

const lists = reactive({ pending: {}, mine: {}, loaded: false });
const work = reactive(emptyWork());
const invoices = ref(0);
const filter = ref('all');
const loadError = ref('');
const now = ref(Date.now());
let timer = null;
let alive = true;

const here = computed(() => hereAsFrom(route.path, route.query));
const home = computed(() => buildGroupHome(props.group, {
  pending: lists.pending, mine: lists.mine, work, here: here.value, now: now.value, filter: filter.value, invoices: invoices.value,
}));
const actions = computed(() => config.value.actions.filter((item) => canSee(item.to.path)));
// 新看板就放在这个页面下面；没切到新流程的站点只给一个去旧看板的按钮。
const showBoard = computed(() => inMenu(config.value.board.path));
const legacyBoard = computed(() => !showBoard.value && inMenu(config.value.board.legacy) ? config.value.board.legacy : '');
const typeLink = computed(() => (filter.value === 'all' ? null : listLinkFor(filter.value)));
const sideTip = computed(() => props.group === 'payment');

const callList = (type, view) => callApi('oa_entry.list_requests', { view, request_type: type, limit: 100 }, { method: 'GET' }).catch(() => []);

async function load() {
  const types = config.value.types.filter((type) => canSee(boardRoute(type)));
  const pending = {};
  const mine = {};
  await Promise.all(types.flatMap((type) => [
    callList(type, 'pending').then((rows) => { pending[type] = rows || []; }),
    callList(type, 'mine').then((rows) => { mine[type] = rows || []; }),
  ]));
  if (!alive) return;
  lists.pending = pending;
  lists.mine = mine;
  lists.loaded = true;
  now.value = Date.now();
  const jobs = [loadProcurementWork(work).catch(() => work)];
  if (props.group === 'payment') {
    jobs.push(callApi('expense_claim_entry.list_available_invoices', { request_type: '报销单' }, { method: 'GET' })
      .then((rows) => { invoices.value = Array.isArray(rows) ? rows.length : 0; }).catch(() => { invoices.value = 0; }));
  }
  await Promise.all(jobs);
}

function refreshWhenVisible() {
  if (document.visibilityState === 'visible') load().catch((error) => { loadError.value = String(error?.message || error); });
}

function open(target) {
  router.push(target);
}

function scrollTo(anchor) {
  document.getElementById(anchor)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
}

onMounted(() => {
  // ?focus=cashier：上面的“待我处理”加载完会把下面的看板顶下去，所以第一次加载完再滚一次到那一块（之后定时刷新不再滚）。
  load().then(() => {
    const anchor = focusAnchor(route.query);
    if (anchor && alive) nextTick(() => scrollTo(anchor));
  }).catch((error) => { loadError.value = String(error?.message || error); });
  window.addEventListener('focus', refreshWhenVisible);
  timer = window.setInterval(refreshWhenVisible, 60000);
});
onBeforeUnmount(() => {
  alive = false;
  window.removeEventListener('focus', refreshWhenVisible);
  if (timer) window.clearInterval(timer);
});
</script>

<template>
  <div class="xp gh">
    <div class="ph">
      <div>
        <div class="crumb">审批中心</div>
        <h3>{{ config.title }}</h3>
        <div class="muted">{{ config.sub }}</div>
      </div>
      <div class="head-actions">
        <button v-for="item in actions" :key="item.label" type="button" :class="['btn', { pri: item.primary }]" @click="open(item.to)">{{ item.label }}</button>
        <button v-if="legacyBoard" type="button" class="btn" @click="open(legacyBoard)">看板 →</button>
      </div>
    </div>

    <div v-if="loadError" class="banner err" role="alert">{{ loadError }}</div>

    <div class="gh-kpis">
      <button v-for="kpi in home.kpis" :key="kpi.key" type="button" :class="['gh-kpi', kpi.tone]" @click="scrollTo(kpi.anchor)">
        <span class="l">{{ kpi.label }}</span>
        <span class="v">{{ kpi.value }}<small>{{ kpi.unit }}</small></span>
        <span class="s">{{ kpi.sub }}</span>
      </button>
    </div>

    <div :class="['gh-grid', { solo: !home.hasTodo }]">
      <div class="gh-col">
        <section v-if="home.hasTodo" id="gh-todo" class="panel flush" aria-label="待我处理">
          <div class="gh-hd">
            <b>待我处理</b><span class="gh-cnt">{{ home.todoAll.length }}</span>
            <span class="gh-chips" role="group" aria-label="按类型筛选">
              <button v-for="chip in home.chips" :key="chip.key" type="button" :class="['chip', { on: chip.on }]" :aria-pressed="chip.on" @click="filter = chip.key">{{ chip.label }}</button>
            </span>
            <button v-if="typeLink" type="button" class="link gh-right" @click="open(typeLink)">全部{{ filter }} →</button>
          </div>
          <div v-for="item in home.todo" :key="item.key" class="gh-item">
            <div class="gh-main">
              <div class="gh-line"><span :class="['gh-tag', item.tone]">{{ item.type }}</span><b>{{ item.subject }}</b></div>
              <div class="gh-meta">
                <template v-if="item.who">{{ item.who }}<template v-if="item.dept"> · {{ item.dept }}</template><template v-if="item.amount"> · {{ item.amount }}</template></template>
                <span v-if="item.waited" :class="['gh-tag', { warn: item.warn }]">{{ item.waited }}</span>
              </div>
              <div v-if="item.node" class="gh-meta">{{ item.node }}</div>
            </div>
            <button type="button" class="btn sm pri" @click="open(item.to)">{{ item.action }}</button>
          </div>
          <div v-if="home.todoMore" class="muted gh-foot">只列前 {{ home.todo.length }} 项，其余在 {{ filter === 'all' ? '各个子页面' : '对应页面' }}里处理。</div>
          <div v-if="!home.todo.length" class="empty">这一类没有要你处理的。</div>
        </section>

        <section v-if="!home.hasTodo" id="gh-mine" class="panel flush" aria-label="我提交的">
          <div class="gh-hd"><b>我提交的 · 进行中</b><span class="gh-cnt cobalt">{{ home.mineActive.length }}</span></div>
          <div v-if="!lists.loaded" class="empty">正在加载…</div>
          <div v-else-if="!home.mine.length" class="empty">没有进行中的单据</div>
          <div v-for="item in home.mine" :key="item.key" class="gh-item">
            <div class="gh-main">
              <div class="gh-line"><span :class="['gh-tag', item.tone]">{{ item.type }}</span><b>{{ item.subject }}</b><span class="gh-tag warn">{{ item.status }}</span></div>
              <div class="gh-steps"><span v-for="(step, index) in item.steps" :key="index" :class="['gh-st', step.cls]"><i>{{ step.mark }}</i>{{ step.text }}</span></div>
              <div class="gh-meta">{{ item.meta }}</div>
            </div>
            <button type="button" class="btn sm" @click="open(item.to)">查看</button>
          </div>
        </section>
      </div>

      <div v-if="home.hasTodo" class="gh-col">
        <section id="gh-mine" class="panel flush" aria-label="我提交的">
          <div class="gh-hd"><b>我提交的 · 进行中</b><span class="gh-cnt cobalt">{{ home.mineActive.length }}</span></div>
          <div v-if="!lists.loaded" class="empty">正在加载…</div>
          <div v-else-if="!home.mine.length" class="empty">没有进行中的单据</div>
          <div v-for="item in home.mine" :key="item.key" class="gh-item">
            <div class="gh-main">
              <div class="gh-line"><span :class="['gh-tag', item.tone]">{{ item.type }}</span><b>{{ item.subject }}</b></div>
              <div class="gh-line gh-gap"><span class="gh-tag warn">{{ item.status }}</span></div>
              <div class="gh-steps"><span v-for="(step, index) in item.steps" :key="index" :class="['gh-st', step.cls]"><i>{{ step.mark }}</i>{{ step.text }}</span></div>
              <div class="gh-meta">{{ item.meta }}</div>
            </div>
            <button type="button" class="btn sm" @click="open(item.to)">查看</button>
          </div>
          <div v-if="home.mineActive.length > MINE_LIMIT" class="muted gh-foot">只列前 {{ MINE_LIMIT }} 张，其余在各子页面的“我的”里。</div>
        </section>
        <section v-if="sideTip && home.invoices" class="panel flush" aria-label="发票夹">
          <div class="gh-hd"><b>发票夹</b></div>
          <div class="gh-tip">发票夹里有 {{ home.invoices }} 张已确认、还没用过的发票，可以直接拿来新建报销。<button type="button" class="btn sm gh-self" @click="open('/approval/invoice-folder')">去发票夹</button></div>
        </section>
      </div>
    </div>

    <template v-if="showBoard">
      <div class="gh-sec"><b>{{ config.board.title }}</b><span class="muted">{{ config.board.note }}</span></div>
      <RequestBoard v-if="group === 'request'" embedded />
      <PaymentBoard v-else embedded />
    </template>
  </div>
</template>
