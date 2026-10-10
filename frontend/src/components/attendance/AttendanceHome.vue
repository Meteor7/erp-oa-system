<script setup>
// 考勤中心首页（2026-10-10 按确认的图表 demo 重做）：标题 → 一条指标栏 → 图表面板（三栏，可收起）→ 主区两列。
// 谁看到什么由服务端定（board.level）：
//   employee：只有自己的额度、申请、未来 14 天安排，页面上没有团队日历，也拿不到同事的数据；
//   manager ：自己部门的团队日历、团队类型构成、待我审批；
//   company ：人事经理 / 副总经理 / 总经理先看公司汇总和"部门概况"表（只有数字，没有人名），点进某个部门才看到它的 14 天日历和近 5 天不在岗的人。
// 待我审批是一人一行的紧凑列表，同意 / 驳回在行内完成，点一行才进详情。
import { computed, ref } from 'vue';
import {
  TYPES, balanceKpis, departmentLabel, mineSummary, numText, requestTitle, returnedDrafts, rejectionOf, waitText,
} from '../../lib/attendanceView.js';
import { awayList, longDate, ratePercent, readChartsOpen, writeChartsOpen } from '../../lib/attendanceCharts.js';
import AttendanceAway from './AttendanceAway.vue';
import AttendanceCalendar from './AttendanceCalendar.vue';
import AttendanceCharts from './AttendanceCharts.vue';
import AttendanceDeptTable from './AttendanceDeptTable.vue';
import AttendanceMetrics from './AttendanceMetrics.vue';
import AttendanceMineCard from './AttendanceMineCard.vue';
import AttendanceMyStrip from './AttendanceMyStrip.vue';
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
  // 服务端按身份给的图表数据：{level, personal | detail | summary}；drill 是人事 / 领导点进某个部门后的明细。
  board: { type: Object, default: null },
  drillDept: { type: String, default: '' },
  drill: { type: Object, default: null },
  // 驳回：(单据, 原因, 退回给谁) → 失败时返回错误文字，成功返回空字符串。
  rejectRow: { type: Function, default: null },
});
const emit = defineEmits(['new', 'list', 'open', 'approve', 'withdraw', 'continue', 'dept']);

const chartsOpen = ref(readChartsOpen());
function toggleCharts() {
  chartsOpen.value = !chartsOpen.value;
  writeChartsOpen(chartsOpen.value);
}

// loading（还没取到）/ employee / manager / company（部门汇总）/ dept（人事 / 领导点进了某个部门）
const view = computed(() => {
  if (!props.loaded.board) return 'loading';
  if (props.board?.level === 'manager') return 'manager';
  if (props.board?.level === 'company') return props.drillDept ? 'dept' : 'company';
  return 'employee';
});
const personal = computed(() => props.board?.personal || null);
const summary = computed(() => props.board?.summary || null);
const detail = computed(() => (view.value === 'manager' ? props.board?.detail : view.value === 'dept' ? props.drill : null) || null);
const stats = computed(() => (view.value === 'company' ? summary.value?.stats : detail.value?.stats) || null);
const todoRows = computed(() => props.review.items);
const deptRows = computed(() => (view.value === 'dept' && detail.value
  ? todoRows.value.filter((row) => departmentLabel(row.department) === departmentLabel(detail.value.department)) : todoRows.value));
const away = computed(() => awayList(detail.value?.members, 0, 5));
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
const items = computed(() => {
  const data = stats.value;
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
  if (!data) return [];
  if (view.value === 'manager') {
    return [
      ...(props.hasEmployee ? [annualItem.value] : []),
      { key: 'today', label: '团队今日请假', value: data.today.off, unit: `/ ${data.headcount} 人`, sub: data.today.rest_day ? '今天是休息日' : `出差 ${data.today.trip} 人` },
      { key: 'month', label: '团队本月请假', value: data.month.hours, unit: '小时', sub: `人均 ${data.month.per_capita} 小时` },
      todoItem.value,
    ];
  }
  if (view.value === 'dept') {
    return [
      { key: 'in', label: '今日在岗', value: data.today.in, unit: `/ ${data.headcount}`, sub: data.today.rest_day ? '今天是休息日' : `请假 ${data.today.off} · 出差 ${data.today.trip}` },
      { key: 'month', label: '本月请假', value: data.month.hours, unit: '小时', sub: `人均 ${data.month.per_capita} 小时` },
      { key: 'rate', label: '出勤率', value: ratePercent(data.rate), unit: '%', sub: '未来 14 天工作日' },
      { key: 'pending', label: '待审批', value: detail.value.pending, unit: '张', sub: deptRows.value.length ? `其中轮到我 ${deptRows.value.length} 张，在右边可以直接处理` : '没有轮到我的', hot: Boolean(detail.value.pending) },
    ];
  }
  return [
    { key: 'today', label: '今日请假', value: data.today.off, unit: `/ ${data.headcount} 人`, sub: data.today.rest_day ? '今天是休息日' : `出差 ${data.today.trip} 人` },
    { key: 'month', label: '本月请假', value: data.month.hours, unit: '小时', sub: `折合 ${Math.round(data.month.hours / 8)} 人天` },
    { key: 'rate', label: '出勤率', value: ratePercent(data.rate), unit: '%', sub: '未来 14 天工作日' },
    todoItem.value,
  ];
});
const todayBar = computed(() => (view.value === 'company' && stats.value
  ? { title: `今日出勤 · ${longDate(stats.value.days[0]?.date)}`, today: stats.value.today, headcount: stats.value.headcount, rate: ratePercent(stats.value.rate) } : null));
const toolsText = computed(() => ({
  employee: '仅显示你自己的数据',
  manager: `只显示你的团队（${detail.value?.label || ''}）`,
  company: '先看部门汇总；点进某个部门才显示具体的人',
  dept: '图表只统计这个部门',
}[view.value] || ''));
const chartKind = computed(() => ({ employee: 'employee', manager: 'approver', company: 'company', dept: 'dept' }[view.value]));
const scopeLabel = computed(() => (view.value === 'manager' ? '我的团队' : view.value === 'dept' ? detail.value?.label || '' : view.value === 'company' ? '全公司' : ''));
const calendarNote = computed(() => (detail.value ? `${detail.value.label} · ${detail.value.headcount} 人` : ''));
</script>

<template>
  <div class="at-page">
    <div class="ph">
      <div>
        <div class="crumb">审批中心</div>
        <h3>请假 · 加班 · 调休</h3>
        <div class="muted">看额度、批申请、跟进度都在这里；新建申请在单独的页面里填。</div>
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

      <template v-else>
        <div v-if="view === 'dept'" class="ac-crumbs">
          <a role="button" tabindex="0" @click="emit('dept', '')" @keydown.enter="emit('dept', '')">全部部门</a><span class="muted">/</span>
          <b>{{ detail?.label || departmentLabel(drillDept) }}</b><span v-if="detail" class="ac-note">{{ detail.headcount }} 人</span>
        </div>

        <div v-if="view === 'dept' && !detail" class="ac-panel"><div class="ac-empty">正在加载这个部门…</div></div>

        <template v-else>
          <AttendanceMetrics :items="items" :today="todayBar" @list="(scope, filter) => emit('list', scope, filter)" />

          <div class="ac-tools">
            <span class="ac-privacy">{{ toolsText }}</span>
            <button type="button" class="ac-btn sm" :aria-expanded="chartsOpen" @click="toggleCharts">{{ chartsOpen ? '收起图表 ▴' : '展开图表 ▾' }}</button>
          </div>
          <AttendanceCharts
            v-if="chartsOpen" :kind="chartKind" :home="home" :personal="personal" :stats="stats" :departments="summary?.departments || []"
            :review-rows="deptRows" :now="now" :scope-label="scopeLabel" />

          <!-- 员工：我的申请 + 我未来 14 天（没有团队日历） -->
          <div v-if="view === 'employee'" :class="['ac-grid', { solo: !personal?.strip?.length }]">
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

          <!-- 部门主管：待我审批 + 我的团队日历 -->
          <div v-else-if="view === 'manager'" class="ac-grid">
            <AttendanceQueue
              :rows="todoRows" :loaded="loaded.review" :now="now" :busy="busy" :reject-row="rejectRow"
              @open="(row) => emit('open', row)" @approve="(row) => emit('approve', row)" @list="(scope, filter) => emit('list', scope, filter)" />
            <AttendanceCalendar title="我的团队 · 未来 14 天" :note="calendarNote" :days="stats?.days || []" :members="detail?.members || []" />
          </div>

          <!-- 人事 / 领导：部门概况（只有数字）+ 待我审批 -->
          <div v-else-if="view === 'company'" class="ac-grid wide">
            <AttendanceDeptTable :departments="summary?.departments || []" @pick="(department) => emit('dept', department)" />
            <AttendanceQueue
              :rows="todoRows" :loaded="loaded.review" :now="now" :busy="busy" :reject-row="rejectRow"
              @open="(row) => emit('open', row)" @approve="(row) => emit('approve', row)" @list="(scope, filter) => emit('list', scope, filter)" />
          </div>

          <!-- 点进某个部门：谁在哪天不在 + 这个部门的待审批 + 近 5 天不在岗 -->
          <div v-else class="ac-grid wide">
            <AttendanceCalendar title="谁在哪天不在" :note="`${detail?.headcount || 0} 人`" :days="stats?.days || []" :members="detail?.members || []" />
            <div class="ac-stack">
              <AttendanceQueue
                title="这个部门的待审批" :rows="deptRows" :loaded="loaded.review" :now="now" :busy="busy" :limit="0" :reject-row="rejectRow" empty-text="这个部门没有轮到你审批的申请"
                @open="(row) => emit('open', row)" @approve="(row) => emit('approve', row)" @list="(scope, filter) => emit('list', scope, filter)" />
              <AttendanceAway :rows="away" />
            </div>
          </div>

          <div v-if="view !== 'employee' || isApprover" class="ac-links">
            <button type="button" class="ac-link" @click="emit('list', 'mine', 'all')">我的申请 {{ mineInfo.total }} 张（进行中 {{ mineInfo.active }}）→</button>
            <button type="button" class="ac-link" @click="emit('list', 'done', 'all')">我审批过的 {{ reviewed.length }} 张 →</button>
            <button v-if="home?.can_view_all" type="button" class="ac-link" @click="emit('list', 'all', 'all')">全部申请 →</button>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>
