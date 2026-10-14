<script setup>
// 考勤中心首页。谁看到什么由服务端定（board.level）：
//   employee：只有自己的额度、申请、未来 14 天安排（2026-10-10 的版式，没有改）：指标栏 → 图表面板（可收起）→ 我的申请 + 我未来 14 天；
//   manager ：部门主管看自己的团队（汇报关系向下），company：人事经理 / 副总经理 / 总经理看全公司，dept：他们选了某个部门。
// 2026-10-14 按确认的 demo 改版（后三种）：顶上一排筛选（部门 —— 只有全公司那一档能选，选一个部门就是点进部门；搜姓名），
// 下面是「谁不在」+「未来 14 天」、「N 月」概览，筛选对它们都生效；最下面全公司是部门概况表 + 待我审批（和原来一样），
// 部门 / 团队是「谁在哪天不在」日历（和原来一模一样，所有成员，不受搜姓名影响）+ 待审批 + 近 5 个工作日。
// 决定 2026-10-14：人事经理 / 副总 / 总经理在首页直接看到全公司的人名，不用先点进部门（服务端 get_attendance_requests 定范围）。
// 页面状态（部门、今天 / 本周 / 哪一天、选中的类型、N 月的页签和选择）都在地址里：点进申请再返回、看板直接点进某一块都靠它。
import { computed, nextTick, ref, watch } from 'vue';
import {
  TYPES, balanceKpis, byWait, departmentLabel, mineSummary, numText, requestTitle, returnedDrafts, rejectionOf, waitText,
} from '../../lib/attendanceView.js';
import { ratePercent, readChartsOpen, writeChartsOpen } from '../../lib/attendanceCharts.js';
import { scopeRows } from '../../lib/attendanceHome.js';
import AttendanceAwayChart from './AttendanceAwayChart.vue';
import AttendanceAwayPanel from './AttendanceAwayPanel.vue';
import AttendanceCalendar from './AttendanceCalendar.vue';
import AttendanceCharts from './AttendanceCharts.vue';
import AttendanceDeptTable from './AttendanceDeptTable.vue';
import AttendanceMetrics from './AttendanceMetrics.vue';
import AttendanceMineCard from './AttendanceMineCard.vue';
import AttendanceMonthPanel from './AttendanceMonthPanel.vue';
import AttendanceMyStrip from './AttendanceMyStrip.vue';
import AttendanceNearList from './AttendanceNearList.vue';
import AttendanceQueue from './AttendanceQueue.vue';

const props = defineProps({
  home: { type: Object, default: null },
  mine: { type: Object, required: true },
  review: { type: Object, required: true },
  reviewed: { type: Array, default: () => [] },
  loaded: { type: Object, required: true },
  now: { type: Number, default: () => Date.now() },
  busy: { type: Boolean, default: false },
  hasEmployee: { type: Boolean, default: false },
  isApprover: { type: Boolean, default: false },
  availableTypes: { type: Array, default: () => [] },
  noEmployeeText: { type: String, default: '' },
  // 服务端按身份给的图表数据：{level, personal | detail | summary}；drill 是人事 / 领导选了某个部门后的明细（日历）。
  board: { type: Object, default: null },
  drillDept: { type: String, default: '' },
  drill: { type: Object, default: null },
  // 一张申请一行的明细（get_attendance_requests：{today, month, work_dates, rows, headcount, label}），员工没有。
  requests: { type: Object, default: null },
  // 地址里的首页状态（attendanceHome.homeStateOf）。
  homeState: { type: Object, default: () => ({}) },
  // 驳回：(单据, 原因, 退回给谁) → 失败时返回错误文字，成功返回空字符串。
  rejectRow: { type: Function, default: null },
});
const emit = defineEmits(['new', 'list', 'open', 'approve', 'withdraw', 'continue', 'dept', 'home']);

const chartsOpen = ref(readChartsOpen());
function toggleCharts() {
  chartsOpen.value = !chartsOpen.value;
  writeChartsOpen(chartsOpen.value);
}

// loading（还没取到）/ employee / manager / company（全公司）/ dept（人事 / 领导选了某个部门）
const view = computed(() => {
  if (!props.loaded.board) return 'loading';
  if (props.board?.level === 'manager') return 'manager';
  if (props.board?.level === 'company') return props.drillDept ? 'dept' : 'company';
  return 'employee';
});
const personal = computed(() => props.board?.personal || null);
const summary = computed(() => props.board?.summary || null);
const detail = computed(() => (view.value === 'manager' ? props.board?.detail : view.value === 'dept' ? props.drill : null) || null);
const stats = computed(() => detail.value?.stats || null);
const todoRows = computed(() => byWait(props.review.items, props.now));
const deptRows = computed(() => (view.value === 'dept' && detail.value
  ? todoRows.value.filter((row) => departmentLabel(row.department) === departmentLabel(detail.value.department)) : todoRows.value));
const kpi = computed(() => balanceKpis(props.home));
const mineInfo = computed(() => mineSummary(props.mine.items));
const returned = computed(() => returnedDrafts(props.mine.items));
const longest = computed(() => {
  const days = todoRows.value.map((row) => waitText(row, props.now)).filter((text) => text.endsWith('天')).map((text) => parseInt(text, 10));
  return days.length ? Math.max(...days) : 0;
});
const todoSub = computed(() => {
  if (!todoRows.value.length) return '全部处理完了';
  return longest.value ? `最久等了 ${longest.value} 天` : '都在 3 天内';
});

function rejectionText(row) {
  const rejection = rejectionOf(row);
  const who = props.mine.names[String(rejection?.actor || '').toLowerCase()] || String(rejection?.actor || '').split('@')[0];
  return `${who ? `${who}：` : ''}${rejection?.note || '请修改后重新提交'}`;
}

const annualItem = computed(() => ({
  key: 'annual', label: '年假可用', value: kpi.value.annual ? kpi.value.annual.days : '—', unit: kpi.value.annual ? `天 · ${kpi.value.annual.hours} 小时` : '',
  sub: kpi.value.annual ? `已用 ${kpi.value.annual.used} 小时` : '暂无年假信息', go: ['mine', '请假'],
}));
const todoItem = computed(() => ({ key: 'todo', label: '待我审批', value: todoRows.value.length, unit: '张', sub: todoSub.value, hot: true, go: ['todo', 'all'] }));
// 员工的指标栏（没有改）；部门主管自己也是员工：留着他自己的年假可用和待我审批。人事 / 领导的数字都在下面几块里了，不再放指标栏。
const items = computed(() => {
  if (view.value === 'employee') {
    const month = props.home?.month;
    const personalHours = Number(month?.leave_days_by_type?.事假 || 0) * 8;
    return [
      ...(props.hasEmployee ? [
        annualItem.value,
        { key: 'comp', label: '调休可用', value: kpi.value.comp ? kpi.value.comp.hours : '—', unit: kpi.value.comp ? '小时' : '', sub: kpi.value.comp ? `累计加班 ${kpi.value.comp.credit} 小时` : '暂无调休信息', go: ['mine', '调休'] },
      ] : []),
      { key: 'mine', label: '我的申请', value: mineInfo.value.total, unit: '张', sub: `其中进行中 ${mineInfo.value.active} 张`, go: ['mine', 'all'] },
      ...(props.hasEmployee && month ? [{ key: 'month', label: '本月已请假', value: numText(month.leave_hours), unit: '小时', sub: `事假 ${numText(personalHours)} 小时` }] : []),
      ...(props.isApprover ? [todoItem.value] : []),
    ];
  }
  if (view.value === 'manager') return [...(props.hasEmployee ? [annualItem.value] : []), todoItem.value];
  return [];
});

// ---------------------------------------------------------------- 团队 / 全公司：筛选和几块的数据
const state = computed(() => props.homeState || {});
// 部门选择 = 点进部门（选“全公司”回到全公司）；用 v-model，部门列表晚到时选中的那一项也对得上。
const deptChoice = computed({ get: () => props.drillDept, set: (department) => emit('dept', department) });
const search = ref(state.value.q || '');
watch(() => state.value.q, (value) => { if ((value || '') !== search.value.trim()) search.value = value || ''; });
watch(search, (value) => { if (value.trim() !== (state.value.q || '')) emit('home', { q: value.trim() }); });

const today = computed(() => props.requests?.today || '');
const workDates = computed(() => props.requests?.work_dates || []);
const month = computed(() => props.requests?.month || state.value.month || '');
const scoped = computed(() => scopeRows(props.requests?.rows, { dept: view.value === 'dept' ? props.drillDept : '', q: state.value.q }));
const showDept = computed(() => view.value !== 'dept');
const chartDay = computed(() => (state.value.period === 'week' ? '' : state.value.day || today.value));
const overviewSel = computed(() => ({ dept: state.value.odept, part: state.value.opart, week: state.value.oweek }));
const headcount = computed(() => props.requests?.headcount ?? detail.value?.headcount ?? 0);
const companyRate = computed(() => (summary.value?.stats ? `全公司未来 14 天出勤率 ${ratePercent(summary.value.stats.rate)}%` : ''));
const toolsText = computed(() => ({
  manager: '只显示你的团队：汇报关系向下的在职员工',
  company: '全公司 · 选一个部门只看它',
  dept: '下面几块只统计这个部门',
}[view.value] || ''));

// 「谁不在」和「未来 14 天」：今天 / 本周 / 图上点的某一天，选中的类型；「N 月」：页签、月份、图上的选择。
const setPeriod = (period) => emit('home', { period: period === 'week' ? 'week' : '', day: '', section: 'away' });
const setDay = (day) => emit('home', { period: '', day: day && day !== today.value ? day : '', section: 'away' });
const setTile = (tile) => emit('home', { tile, section: 'away' });
const setChart = (mode) => emit('home', { chart: mode === 'trip' ? 'trip' : '' });
const setMetric = (metric) => emit('home', { metric, odept: '', opart: '', oweek: '', section: 'month' });
const setSelect = (field, value) => emit('home', { [`o${field}`]: value, section: 'month' });
const clearSelect = () => emit('home', { odept: '', opart: '', oweek: '', section: 'month' });
const setMonth = (value) => emit('home', { month: value, odept: '', opart: '', oweek: '', section: 'month' });

// 看板点进来（section=away | month）、或者从申请详情返回：数据到了以后滚到那一块（每个 section 只滚一次）。
let scrolled = '';
watch(() => [state.value.section, Boolean(props.requests), view.value], async ([section, ready]) => {
  if (!section || !ready || scrolled === section || !['manager', 'company', 'dept'].includes(view.value)) return;
  scrolled = section;
  await nextTick();
  document.getElementById(section === 'month' ? 'ac-month' : 'ac-away')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
}, { immediate: true });

const calendarNote = computed(() => (detail.value ? `${detail.value.label} · ${detail.value.headcount} 人` : ''));
</script>

<template>
  <div class="at-page">
    <div class="ph">
      <div>
        <div class="crumb">审批中心</div>
        <h3>请假 · 加班 · 调休 · 出差</h3>
        <div class="muted">看额度、批申请、跟进度都在这里；新建申请在单独的页面里填。出差申请也在这里，报销、付款直接关联它。</div>
      </div>
      <div v-if="hasEmployee" class="head-actions">
        <button v-for="(type, index) in availableTypes" :key="type" type="button" :class="['btn', { pri: index === 0 }]" @click="emit('new', TYPES[type].label)">＋ 新建{{ TYPES[type].label }}</button>
      </div>
    </div>

    <div v-if="loaded.home && home && !hasEmployee" class="banner err">{{ noEmployeeText }}</div>

    <section v-for="row in returned" :key="row.name" class="at-returned" aria-label="被退回的申请">
      <b>{{ row.subject || requestTitle(row) }}（{{ row.name }}）被退回了</b>
      <span class="grow-col">{{ rejectionText(row) }}</span>
      <button type="button" class="btn pri sm" @click="emit('continue', row)">修改后重新提交</button>
    </section>

    <div class="acx">
      <div v-if="view === 'loading'" class="ac-panel"><div class="ac-empty">正在加载…</div></div>

      <!-- 员工：我的申请 + 我未来 14 天（没有团队日历） -->
      <template v-else-if="view === 'employee'">
        <AttendanceMetrics :items="items" @list="(scope, filter) => emit('list', scope, filter)" />
        <div class="ac-tools">
          <span class="ac-privacy">仅显示你自己的数据</span>
          <button type="button" class="ac-btn sm" :aria-expanded="chartsOpen" @click="toggleCharts">{{ chartsOpen ? '收起图表 ▴' : '展开图表 ▾' }}</button>
        </div>
        <AttendanceCharts v-if="chartsOpen" :home="home" :personal="personal" />
        <div :class="['ac-grid', { solo: !personal?.strip?.length }]">
          <div class="ac-stack">
            <AttendanceQueue
              v-if="isApprover && todoRows.length" :rows="todoRows" :loaded="loaded.review" :now="now" :busy="busy" :reject-row="rejectRow"
              @open="(row) => emit('open', row)" @approve="(row) => emit('approve', row)" @list="(scope, filter) => emit('list', scope, filter)" />
            <AttendanceMineCard
              :mine="mine" :loaded="loaded.mine" :now="now" :busy="busy"
              @list="(scope, filter) => emit('list', scope, filter)" @open="(row) => emit('open', row)" @withdraw="(row) => emit('withdraw', row)" @continue="(row) => emit('continue', row)" />
          </div>
          <AttendanceMyStrip v-if="personal?.strip?.length" :strip="personal.strip" />
        </div>
        <div v-if="isApprover" class="ac-links">
          <button type="button" class="ac-link" @click="emit('list', 'mine', 'all')">我的申请 {{ mineInfo.total }} 张（进行中 {{ mineInfo.active }}）→</button>
          <button type="button" class="ac-link" @click="emit('list', 'done', 'all')">我审批过的 {{ reviewed.length }} 张 →</button>
          <button v-if="home?.can_view_all" type="button" class="ac-link" @click="emit('list', 'all', 'all')">全部申请 →</button>
        </div>
      </template>

      <template v-else>
        <div v-if="view === 'dept'" class="ac-crumbs">
          <a role="button" tabindex="0" @click="emit('dept', '')" @keydown.enter="emit('dept', '')">全部部门</a><span class="muted">/</span>
          <b>{{ detail?.label || departmentLabel(drillDept) }}</b><span v-if="detail" class="ac-note">{{ detail.headcount }} 人</span>
        </div>

        <!-- 顶上的筛选：部门（只有全公司那一档能选，选一个就是点进那个部门；部门主管固定是自己的团队）+ 搜姓名 -->
        <div class="ac-filters">
          <select v-if="view !== 'manager'" v-model="deptChoice" aria-label="部门">
            <option value="">全公司 {{ summary?.stats?.headcount ?? '' }} 人</option>
            <option v-for="item in summary?.departments || []" :key="item.department" :value="item.department">{{ item.label }} · {{ item.headcount }} 人</option>
          </select>
          <span v-else class="ac-privacy">我的团队 · {{ headcount }} 人</span>
          <input v-model="search" type="search" placeholder="搜姓名" aria-label="搜姓名" maxlength="40" />
          <span class="ac-note">{{ toolsText }}</span>
        </div>

        <AttendanceMetrics v-if="items.length" :items="items" @list="(scope, filter) => emit('list', scope, filter)" />

        <div v-if="!requests" class="ac-panel"><div class="ac-empty">{{ loaded.rows ? '暂时取不到申请明细' : '正在加载…' }}</div></div>
        <template v-else>
          <div class="ac-grid wide">
            <AttendanceAwayPanel
              :rows="scoped" :today="today" :work-dates="workDates" :period="state.period" :day="state.day" :tile="state.tile" :show-dept="showDept"
              @period="setPeriod" @day="setDay" @tile="setTile" @open="(row) => emit('open', row)" />
            <AttendanceAwayChart
              :rows="scoped" :today="today" :work-dates="workDates" :mode="state.chart" :selected="chartDay"
              @mode="setChart" @day="setDay" />
          </div>
          <AttendanceMonthPanel
            :rows="scoped" :month="month" :today="today" :metric="state.metric" :sel="overviewSel" :company="view === 'company'" :show-dept="showDept"
            @metric="setMetric" @select="setSelect" @clear="clearSelect" @month="setMonth" @open="(row) => emit('open', row)" />
        </template>

        <!-- 部门主管：待我审批 + 近 5 个工作日 + 我的团队日历（日历和原来一样） -->
        <div v-if="view === 'manager'" class="ac-grid">
          <div class="ac-stack">
            <AttendanceQueue
              :rows="todoRows" :loaded="loaded.review" :now="now" :busy="busy" :reject-row="rejectRow"
              @open="(row) => emit('open', row)" @approve="(row) => emit('approve', row)" @list="(scope, filter) => emit('list', scope, filter)" />
            <AttendanceNearList v-if="requests" :rows="scoped" :today="today" :work-dates="workDates" @open="(row) => emit('open', row)" />
          </div>
          <AttendanceCalendar title="我的团队 · 未来 14 天" :note="calendarNote" :days="stats?.days || []" :members="detail?.members || []" />
        </div>

        <!-- 人事 / 领导：部门概况（和原来一样，点一行进入部门）+ 待我审批 -->
        <div v-else-if="view === 'company'" class="ac-grid wide">
          <AttendanceDeptTable :departments="summary?.departments || []" :sub="companyRate" @pick="(department) => emit('dept', department)" />
          <AttendanceQueue
            :rows="todoRows" :loaded="loaded.review" :now="now" :busy="busy" :reject-row="rejectRow"
            @open="(row) => emit('open', row)" @approve="(row) => emit('approve', row)" @list="(scope, filter) => emit('list', scope, filter)" />
        </div>

        <!-- 点进某个部门：谁在哪天不在（和原来一模一样）+ 这个部门的待审批 + 近 5 个工作日 -->
        <template v-else>
          <div v-if="!detail" class="ac-panel"><div class="ac-empty">正在加载这个部门…</div></div>
          <div v-else class="ac-grid wide">
            <AttendanceCalendar title="谁在哪天不在" :note="`${detail?.headcount || 0} 人`" :days="stats?.days || []" :members="detail?.members || []" />
            <div class="ac-stack">
              <AttendanceQueue
                title="这个部门的待审批" :rows="deptRows" :loaded="loaded.review" :now="now" :busy="busy" :limit="0" :reject-row="rejectRow" empty-text="这个部门没有轮到你审批的申请"
                @open="(row) => emit('open', row)" @approve="(row) => emit('approve', row)" @list="(scope, filter) => emit('list', scope, filter)" />
              <AttendanceNearList v-if="requests" :rows="scoped" :today="today" :work-dates="workDates" @open="(row) => emit('open', row)" />
            </div>
          </div>
        </template>

        <div class="ac-links">
          <button type="button" class="ac-link" @click="emit('list', 'mine', 'all')">我的申请 {{ mineInfo.total }} 张（进行中 {{ mineInfo.active }}）→</button>
          <button type="button" class="ac-link" @click="emit('list', 'done', 'all')">我审批过的 {{ reviewed.length }} 张 →</button>
          <button v-if="home?.can_view_all" type="button" class="ac-link" @click="emit('list', 'all', 'all')">全部申请 →</button>
        </div>
      </template>
    </div>
  </div>
</template>
