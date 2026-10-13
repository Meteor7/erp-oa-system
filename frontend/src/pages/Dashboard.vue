<script setup>
// 按岗位区分的数据看板（首页）。内容、顺序、权限全部由后端 dashboard_home.get_home 决定，
// 这里只负责：问候 + 期间 + 页签（进地址 ?tab=）+ 指标卡 / 要我处理 / 需要关注 / 图表块 + 通知。
// 点击跳转用 targets.json 的目标名（lib/dashboardTargets.js），页面里不写任何岗位名或页面路径。
// 排版（2026-10-13，lib/dashboardLayout.js）：指标卡按张数排列、总览只先放 4 张；图表块成对等高、落单的占满一行，空块收进最后一行。
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { createResource } from 'frappe-ui';
import { canSee, currentUser } from '../lib/access';
import { boardAccess } from '../lib/expenseBoards';
import { period } from '../lib/period';
import { buildTargetTable, dashboardFrom, targetState } from '../lib/dashboardTargets';
import targetsJson from '../lib/dashboardTargetsData';
import {
  EMPTY_PAGE_TEXT, currentMonth, errorText, greetingFor, isValidMonth, monthLabel, neighbourTab, pageView, resolveTabKey, tabQuery,
} from '../lib/dashboardView';
import { arrangeBlocks, attentionFirst, foldKpis, kpiGridClass, readMoreKpis, writeMoreKpis } from '../lib/dashboardLayout';
import DashKpi from '../components/dashboard/DashKpi.vue';
import DashNoData from '../components/dashboard/DashNoData.vue';
import DashTodos from '../components/dashboard/DashTodos.vue';
import DashAlerts from '../components/dashboard/DashAlerts.vue';
import DashBlock from '../components/dashboard/DashBlock.vue';
import DashNotifications from '../components/dashboard/DashNotifications.vue';
import '../styles/dashboardUi.css';

const route = useRoute();
const router = useRouter();
const table = buildTargetTable(targetsJson);
const access = { ...boardAccess(), canSee };

// 期间沿用全局的 period（其他页面点进去也是这个月）。作为参数在资源创建时就要有值。
const home = createResource({
  url: 'rayher_hr_payroll.api.dashboard_home.get_home', method: 'GET',
  makeParams: () => ({ period: isValidMonth(period.value) ? period.value : currentMonth() }), auto: true,
});
watch(period, () => { if (isValidMonth(period.value)) home.reload(); });

const data = computed(() => home.data || null);
const tabs = computed(() => data.value?.tabs || []);
const activeKey = computed(() => resolveTabKey(tabs.value, route.query.tab));
const page = computed(() => pageView(data.value?.pages?.[activeKey.value]));
const role = computed(() => data.value?.role || {});
const firstLoad = computed(() => home.loading && !data.value);
const showNotes = computed(() => !firstLoad.value && (!tabs.value.length || activeKey.value === 'overview'));

// 排版：总览的指标卡先放 4 张，其余在“更多指标”后面（展开与否按浏览器记住）；干活岗位的总览先放「要我处理」。
const moreKpis = ref(readMoreKpis());
function toggleMoreKpis() {
  moreKpis.value = !moreKpis.value;
  writeMoreKpis(moreKpis.value);
}
const kpiFold = computed(() => foldKpis(page.value.kpis, { fold: activeKey.value === 'overview', open: moreKpis.value }));
const attnFirst = computed(() => attentionFirst(page.value));
const arranged = computed(() => arrangeBlocks(page.value.blocks));
const sectionLayouts = computed(() => page.value.sections.map((section) => arrangeBlocks(section.blocks)));

const greeting = computed(() => greetingFor(new Date().getHours()));
const userName = computed(() => role.value.person || currentUser() || '');
const isThisMonth = computed(() => period.value === currentMonth());

// 从看板点出去，目标页的"返回"回到当前页签。
const fromPath = computed(() => dashboardFrom(activeKey.value));
const resolve = (target) => targetState(target, { table, from: fromPath.value, access });
const go = (to) => { if (to) router.push(to); };

function pickTab(key) {
  if (key !== activeKey.value) router.replace({ path: route.path, query: tabQuery(route.query, key) });
}
function onTabKey(event, step) {
  const key = neighbourTab(tabs.value, activeKey.value, step);
  pickTab(key);
  event.preventDefault();
  document.getElementById(`db-tab-${key}`)?.focus();
}
function setPeriod(value) {
  if (isValidMonth(value)) period.value = value;
}
</script>

<template>
  <div class="db" :aria-busy="home.loading ? 'true' : 'false'">
    <header class="db-head">
      <div class="db-head-main">
        <div class="db-crumb">数据看板<template v-if="role.label"> · {{ role.label }}</template></div>
        <h1>{{ greeting }}<template v-if="userName">，{{ userName }}</template></h1>
        <p v-if="role.note" class="db-mut">{{ role.note }}</p>
      </div>
      <div class="db-tools">
        <span class="db-mut">{{ monthLabel(period) }}</span>
        <input type="month" class="db-month" aria-label="选择月份" :value="period" :max="currentMonth()" @change="setPeriod($event.target.value)" />
        <button v-if="!isThisMonth" type="button" class="db-btn" @click="setPeriod(currentMonth())">本月</button>
      </div>
    </header>

    <div v-if="firstLoad" class="db-skel" role="status" aria-label="正在加载看板">
      <div class="db-kpis"><i v-for="n in 4" :key="n" class="db-skel-kpi"></i></div>
      <div class="db-attn is-both"><i class="db-skel-card"></i><i class="db-skel-card"></i></div>
    </div>

    <div v-else-if="home.error && !data" class="db-fail" role="alert">
      <p>看板加载失败：{{ errorText(home.error) || '请稍后再试' }}</p>
      <button type="button" class="db-btn is-pri" @click="home.reload()">重新加载</button>
    </div>

    <template v-else-if="data">
      <p v-if="home.error" class="db-stale" role="status">刷新失败，下面显示的是上一次的数据。<button type="button" class="db-link" @click="home.reload()">重试</button></p>

      <div v-if="tabs.length > 1" class="db-tabs" role="tablist" aria-label="看板页签">
        <button v-for="item in tabs" :id="`db-tab-${item.key}`" :key="item.key" type="button" role="tab" :aria-selected="activeKey === item.key"
          :aria-controls="`db-panel-${item.key}`" :tabindex="activeKey === item.key ? 0 : -1" @click="pickTab(item.key)"
          @keydown.right="onTabKey($event, 1)" @keydown.left="onTabKey($event, -1)">{{ item.label }}</button>
      </div>

      <div :id="`db-panel-${activeKey}`" class="db-panel" :class="{ 'is-loading': home.loading }" role="tabpanel" :aria-labelledby="`db-tab-${activeKey}`">
        <!-- 干活岗位的总览：先「要我处理」/「需要关注」，再指标卡 -->
        <div v-if="attnFirst" class="db-attn" :class="`is-${page.attention}`">
          <DashTodos v-if="page.showTodos" :todos="page.todos" :resolve="resolve" @go="go" />
          <DashAlerts v-if="page.showAlerts" :alerts="page.alerts" :resolve="resolve" @go="go" />
        </div>

        <div v-if="page.kpis.length" class="db-kpiwrap">
          <div class="db-kpis" :class="kpiGridClass(kpiFold.shown.length)">
            <DashKpi v-for="item in kpiFold.shown" :key="item.key" :kpi="item" :state="resolve(item.target)" @go="go" />
          </div>
          <button v-if="kpiFold.foldable" type="button" class="db-more" :aria-expanded="moreKpis ? 'true' : 'false'" @click="toggleMoreKpis">
            {{ moreKpis ? '收起指标' : `更多指标 ${kpiFold.hidden}` }}
          </button>
        </div>

        <div v-if="!attnFirst && page.attention !== 'none'" class="db-attn" :class="`is-${page.attention}`">
          <DashTodos v-if="page.showTodos" :todos="page.todos" :resolve="resolve" @go="go" />
          <DashAlerts v-if="page.showAlerts" :alerts="page.alerts" :resolve="resolve" @go="go" />
        </div>

        <div v-if="arranged.cards.length" class="db-blocks">
          <DashBlock v-for="card in arranged.cards" :key="card.block.key" :class="{ 'is-full': card.span === 'full' }" :block="card.block" :resolve="resolve" @go="go" />
        </div>
        <DashNoData :blocks="arranged.empty" :resolve="resolve" @go="go" />

        <section v-for="(section, index) in page.sections" :key="`${section.title}-${index}`" class="db-sec" :aria-label="section.title">
          <div class="db-sec-h"><h2>{{ section.title }}</h2><span v-if="section.sub" class="db-mut">{{ section.sub }}</span></div>
          <div v-if="section.kpis.length" class="db-kpis" :class="kpiGridClass(section.kpis.length)">
            <DashKpi v-for="item in section.kpis" :key="item.key" :kpi="item" :state="resolve(item.target)" @go="go" />
          </div>
          <div v-if="sectionLayouts[index].cards.length" class="db-blocks">
            <DashBlock v-for="card in sectionLayouts[index].cards" :key="card.block.key" :class="{ 'is-full': card.span === 'full' }" :block="card.block" :resolve="resolve" @go="go" />
          </div>
          <DashNoData :blocks="sectionLayouts[index].empty" :resolve="resolve" @go="go" />
        </section>

        <p v-if="page.isEmpty" class="db-empty db-card">{{ EMPTY_PAGE_TEXT }}</p>
      </div>
    </template>

    <DashNotifications v-if="showNotes" />
  </div>
</template>
