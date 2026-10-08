<script setup>
import { computed, onBeforeUnmount, ref, watch, nextTick } from 'vue';
import { useRouter } from 'vue-router';
import { FeatherIcon, createResource } from 'frappe-ui';
import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { canSee, currentUser } from '../lib/access';
import { period } from '../lib/period';
import { costPreviewTag } from '../lib/previewTags';

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

const BRAND = '#FF8F00';
const COBALT = '#3E63DD';
const JADE = '#1FA58C';
const SUN = '#FFB547';
const SKY = '#A9BDF6';
const MIST = '#CDD3DC';
const AXIS = { axisLine: { show: true, lineStyle: { color: '#C9CFD8' } }, axisTick: { show: false }, axisLabel: { color: '#6B7385', fontSize: 12 }, splitLine: { lineStyle: { color: '#EEF1F5' } }, nameTextStyle: { color: '#8A93A3', fontSize: 12, align: 'left' } };
// 类目轴：每个类目都出标签，标签多或长时斜排，过长截断（悬停看全名）
const catAxis = (data, extra = {}) => {
  const longest = Math.max(1, ...data.map((item) => String(item ?? '').length));
  return { ...AXIS, type: 'category', data, ...extra, axisLabel: { ...AXIS.axisLabel, interval: 0, rotate: data.length * longest > 70 ? 30 : 0, width: 96, overflow: 'truncate' } };
};
const valAxis = (name, formatter) => ({ ...AXIS, type: 'value', name, axisLine: { show: false }, axisLabel: { ...AXIS.axisLabel, ...(formatter ? { formatter } : {}) } });
// 堆叠柱顶部显示合计
const totalLabel = (totals, format) => ({ show: true, position: 'top', color: '#4A5365', fontSize: 11, formatter: (p) => (totals[p.dataIndex] ? format(totals[p.dataIndex]) : '') });
const BASE = {
  textStyle: { color: '#4A5365' },
  tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#E9ECF1', textStyle: { color: '#1A2130' } },
  grid: { left: 8, right: 18, top: 40, bottom: 6, containLabel: true },
  legend: { top: 4, right: 8, icon: 'rect', itemWidth: 9, itemHeight: 9, textStyle: { color: '#6B7385' } },
};

const router = useRouter();
const tab = ref('mine');
const scope = ref('month');
const year = ref(new Date().getFullYear());
const selectedProject = ref('');
// ECharts 实例不能放进 reactive：被 Vue 代理后再次 setOption 会抛错，图表空白或柱子挤成一团
const charts = {};

// Resources below fetch as soon as they are created, so their params must exist first.
const currentPeriod = computed(() => (scope.value === 'year' ? String(year.value) : period.value));
const scopeLabel = computed(() => (scope.value === 'year' ? `${year.value} 年` : period.value.replace(/(\d+)-(\d+)/, (m, y, mo) => `${y} 年 ${Number(mo)} 月`)));
const oaTodos = createResource({ url: 'rayher_hr_payroll.api.oa_entry.get_my_approval_summary', method: 'GET', auto: true });
const queue = createResource({ url: 'rayher_hr_payroll.api.overview_entry.get_my_approval_queue', method: 'GET', makeParams: () => ({ limit: 8 }), auto: true });
const myRequests = createResource({ url: 'rayher_hr_payroll.api.overview_entry.get_my_requests', method: 'GET', makeParams: () => ({ limit: 6 }), auto: true });
const noteCategory = ref('mine');
const noteUnreadOnly = ref(true);
const notifications = createResource({
  url: 'rayher_hr_payroll.api.overview_entry.get_my_notification_feed', method: 'GET',
  makeParams: () => ({ category: noteCategory.value, unread_only: noteUnreadOnly.value ? 1 : 0, limit: 20 }), auto: true,
});
const noteReader = createResource({ url: 'rayher_hr_payroll.api.overview_entry.mark_notifications_read', method: 'POST' });
const noteCategories = computed(() => notifications.data?.categories || []);
const noteItems = computed(() => notifications.data?.items || []);
function openNote(item) {
  markNoteRead(item);
  if (item.route) router.push({ path: item.route, query: item.query || {} });
}
function markNoteRead(item) {
  if (!item.unread) return;
  noteReader.submit({ names: JSON.stringify(item.names) }).then(() => notifications.reload());
}
function markCategoryRead() {
  noteReader.submit({ category: noteCategory.value }).then(() => notifications.reload());
}
watch([noteCategory, noteUnreadOnly], () => notifications.reload());
const myLeave = createResource({ url: 'rayher_hr_payroll.api.overview_entry.get_my_leave_summary', method: 'GET', auto: true });
const cost = createResource({ url: 'rayher_hr_payroll.api.overview_entry.get_cost_overview', method: 'GET', makeParams: () => ({ scope: scope.value, period: currentPeriod.value }), auto: true });
const costDetail = createResource({ url: 'rayher_hr_payroll.api.overview_entry.get_project_cost_detail', method: 'GET' });
const hr = createResource({ url: 'rayher_hr_payroll.api.overview_entry.get_hr_overview', method: 'GET', makeParams: () => ({ scope: scope.value, period: currentPeriod.value }), auto: true });
const d = createResource({ url: 'rayher_hr_payroll.api.dashboard_entry.get_dashboard', method: 'GET', makeParams: () => ({ period: period.value }), auto: true });

const compareLabel = computed(() => (scope.value === 'year' ? '较去年' : '较上月'));
const years = computed(() => { const now = new Date().getFullYear(); return [now, now - 1, now - 2, now - 3]; });
const greeting = computed(() => { const hour = new Date().getHours(); return hour < 6 ? '夜深了' : hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好'; });
const userName = computed(() => currentUser() || '');

const todoPresentation = {
  leave: { icon: 'calendar' }, overtime: { icon: 'clock' }, comp_time: { icon: 'refresh-cw' },
  procurement: { icon: 'clipboard' }, direct_purchase: { icon: 'shopping-cart' },
  procurement_payment: { icon: 'credit-card' }, expense_payment: { icon: 'file-text' },
};
const typeMark = {
  '请假申请': { mark: '假', tone: 'bg-[#EEF2FD] text-[#3E63DD]' },
  '加班申请': { mark: '加', tone: 'bg-[#EEF2FD] text-[#3E63DD]' },
  '调休申请': { mark: '休', tone: 'bg-[#EEF2FD] text-[#3E63DD]' },
  '采购申请': { mark: '采', tone: 'bg-[#FFF4E6] text-[#E57A00]' },
  '购买申请': { mark: '购', tone: 'bg-[#FFF4E6] text-[#E57A00]' },
  '采购付款': { mark: '付', tone: 'bg-[#E6F6F2] text-[#1FA58C]' },
  '费用付款申请': { mark: '报', tone: 'bg-[#E6F6F2] text-[#1FA58C]' },
  '出差申请': { mark: '差', tone: 'bg-[#FFF4E6] text-[#E57A00]' },
  '报销单': { mark: '报', tone: 'bg-[#E6F6F2] text-[#1FA58C]' },
  '付款单': { mark: '付', tone: 'bg-[#E6F6F2] text-[#1FA58C]' },
  '价格审批': { mark: '价', tone: 'bg-[#FDEBEC] text-[#C9373D]' },
  '采购订单': { mark: '单', tone: 'bg-[#EEF2FD] text-[#3E63DD]' },
};
const markOf = (type) => typeMark[type] || { mark: '单', tone: 'bg-gray-100 text-gray-600' };
const queueItems = computed(() => queue.data?.items || []);
const myRequestItems = computed(() => myRequests.data?.items || []);
function queueDetail(item) {
  const parts = [item.applicant && (item.kind && item.kind !== item.request_type ? item.applicant : `${item.applicant} 提交`), item.department];
  if (item.amount) parts.push(money(item.amount));
  if (item.hours) parts.push(`${item.leave_type || ''} ${Number((item.hours / 8).toFixed(2))} 天（${item.hours} 小时）`.trim());
  if (item.from_date) parts.push(item.to_date && item.to_date !== item.from_date ? `${item.from_date} 至 ${item.to_date}` : item.from_date);
  parts.push(item.waited_days > 0 ? `已等待 ${item.waited_days} 天` : '今天提交');
  return parts.filter(Boolean).join(' · ');
}
function openQueueItem(item) { router.push({ path: item.route, query: item.query || { request: item.name } }); }
const todoCategories = computed(() => (oaTodos.data?.categories || []).map((item) => ({ ...item, ...(todoPresentation[item.key] || { icon: 'inbox' }) })));
const pendingApprovalCategories = computed(() => todoCategories.value.filter((item) => Number(item.count || 0) > 0));
const costVisible = computed(() => Boolean(cost.data?.visible));
// 含未定版月份的预览数字时，成本区块显示小「含预览」标签；接口没返回 preview / preview_months 就什么都不显示
const costPreview = computed(() => costPreviewTag(cost.data));
const rdPreview = computed(() => costPreviewTag(d.data));
const hrVisible = computed(() => Boolean(hr.data?.visible));
const errorText = (resource) => resource.error?.messages?.[0] || resource.error?.message || String(resource.error || '');
const costPending = computed(() => cost.loading || Boolean(cost.error));
const hrPending = computed(() => hr.loading || Boolean(hr.error));
const rdVisible = computed(() => Boolean(d.data) && canSee('/allocation-dashboard'));
const tabs = computed(() => [
  { key: 'mine', label: '我的待办', count: queue.data?.total ?? (oaTodos.data?.total || 0), show: true },
  { key: 'biz', label: '经营看板', show: costVisible.value || costPending.value },
  { key: 'hr', label: '人事看板', show: hrVisible.value || hrPending.value },
  { key: 'rd', label: '研发核算', show: rdVisible.value },
].filter((item) => item.show));

const n0 = (x) => Number(x || 0).toLocaleString('zh-CN');
const money = (x) => '¥ ' + Number(x || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
const wan = (x) => (Math.abs(Number(x || 0)) >= 10000 ? (Number(x) / 10000).toFixed(1) + '万' : n0(x));
const share = (part, total) => (total ? Math.round((Number(part || 0) / Number(total)) * 100) : 0);
const deltaText = (value) => (value === null || value === undefined ? '暂无对比' : `${value > 0 ? '▲' : '▼'} ${Math.abs(value)}% ${compareLabel.value}`);
const deltaClass = (value) => (value === null || value === undefined ? 'text-gray-400' : value > 0 ? 'text-red-600' : 'text-emerald-600');

// 容器随 v-show / v-if / 侧栏折叠变宽变窄时，window resize 不会触发，改用 ResizeObserver 跟随容器尺寸
const chartObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver((entries) => entries.forEach((entry) => {
  if (entry.contentRect.width > 0) echarts.getInstanceByDom(entry.target)?.resize();
}));

function draw(id, option) {
  const el = document.getElementById(id);
  if (!el || !el.offsetWidth) return; // 隐藏状态下宽度为 0，此时绘制会把柱子全挤到左边
  let chart = charts[id];
  if (chart && chart.getDom() !== el) { chartObserver?.unobserve(chart.getDom()); chart.dispose(); chart = null; } // v-if 重建了 DOM
  if (!chart) { chart = echarts.init(el); chartObserver?.observe(el); }
  chart.resize();
  chart.setOption({ ...BASE, ...option }, true);
  charts[id] = chart;
}

function drawCost() {
  const data = cost.data;
  if (!data?.visible) return;
  const projects = data.projects.slice(0, 8);
  draw('cost-projects', {
    tooltip: { ...BASE.tooltip, valueFormatter: money },
    xAxis: catAxis(projects.map((row) => row.label)),
    yAxis: valAxis('金额（元）', wan),
    series: [
      { name: '研发分摊', type: 'bar', stack: 's', barMaxWidth: 28, data: projects.map((row) => row.rd), itemStyle: { color: BRAND } },
      { name: '采购', type: 'bar', stack: 's', data: projects.map((row) => row.po), itemStyle: { color: COBALT } },
      { name: '报销', type: 'bar', stack: 's', data: projects.map((row) => row.expense), itemStyle: { color: JADE, borderRadius: [6, 6, 0, 0] }, label: totalLabel(projects.map((row) => Number(row.rd || 0) + Number(row.po || 0) + Number(row.expense || 0)), wan) },
    ],
  });
  draw('cost-mix', {
    tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#E9ECF1', textStyle: { color: '#1A2130' }, formatter: (p) => `${p.marker}${p.name}<br>${money(p.value)}（${p.percent}%）` },
    legend: { bottom: 4, left: 'center', icon: 'rect', itemWidth: 9, itemHeight: 9, textStyle: { color: '#6B7385' } },
    series: [{
      type: 'pie', radius: ['54%', '76%'], center: ['50%', '44%'], padAngle: 2, labelLine: { show: false },
      label: { show: true, position: 'center', formatter: `{a|费用合计}\n{b|${wan(data.totals.total)}}`, rich: { a: { color: '#8A93A3', fontSize: 12, lineHeight: 20 }, b: { color: '#1A2130', fontSize: 20, fontWeight: 600, lineHeight: 28 } } },
      itemStyle: { borderRadius: 6 },
      data: [
        { name: '研发分摊', value: data.totals.rd, itemStyle: { color: BRAND } },
        { name: '采购', value: data.totals.po, itemStyle: { color: COBALT } },
        { name: '报销', value: data.totals.expense, itemStyle: { color: JADE } },
      ],
    }],
  });
  draw('cost-trend', {
    tooltip: { ...BASE.tooltip, valueFormatter: money },
    xAxis: catAxis(data.trend.map((row) => row.label)),
    yAxis: valAxis('金额（元）', wan),
    series: [
      { name: '研发分摊', type: 'bar', stack: 't', barMaxWidth: 22, data: data.trend.map((row) => row.rd), itemStyle: { color: BRAND } },
      { name: '采购', type: 'bar', stack: 't', data: data.trend.map((row) => row.po), itemStyle: { color: COBALT } },
      { name: '报销', type: 'bar', stack: 't', data: data.trend.map((row) => row.expense), itemStyle: { color: JADE, borderRadius: [5, 5, 0, 0] }, label: totalLabel(data.trend.map((row) => Number(row.rd || 0) + Number(row.po || 0) + Number(row.expense || 0)), wan) },
    ],
  });
}

function drawDetail() {
  const data = costDetail.data;
  if (!data) return;
  const groups = data.breakdown.department
    ? [{ rows: data.breakdown.department, color: COBALT }]
    : [
      { rows: data.breakdown.rd, color: BRAND },
      { rows: data.breakdown.po, color: COBALT },
      { rows: data.breakdown.expense, color: JADE },
    ];
  const rows = [];
  groups.forEach((group) => (group.rows || []).forEach((row) => rows.push({ ...row, color: group.color })));
  rows.reverse();
  draw('cost-detail', {
    grid: { left: 8, right: 70, top: 16, bottom: 6, containLabel: true },
    legend: { show: false },
    tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#E9ECF1', textStyle: { color: '#1A2130' }, formatter: (p) => `${p[0].name}：${money(p[0].value)}` },
    xAxis: { ...AXIS, type: 'value', axisLine: { show: false }, axisLabel: { ...AXIS.axisLabel, formatter: wan } },
    yAxis: { ...AXIS, type: 'category', data: rows.map((row) => row.label), axisLabel: { ...AXIS.axisLabel, color: '#4A5365', width: 140, overflow: 'truncate' }, splitLine: { show: false } },
    series: [{
      type: 'bar', barMaxWidth: 16,
      data: rows.map((row) => ({ value: row.amount, itemStyle: { color: row.color, borderRadius: [0, 4, 4, 0] } })),
      label: { show: true, position: 'right', color: '#4A5365', formatter: (o) => wan(o.value) },
    }],
  });
}

function drawHr() {
  const data = hr.data;
  if (!data?.visible) return;
  const palette = [BRAND, COBALT, JADE, SUN, SKY, MIST];
  draw('hr-types', {
    tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#E9ECF1', textStyle: { color: '#1A2130' }, formatter: (p) => `${p.marker}${p.name}：${p.value} 天（${p.percent}%）` },
    legend: { orient: 'vertical', right: 12, top: 'middle', icon: 'rect', itemWidth: 9, itemHeight: 9, textStyle: { color: '#6B7385' } },
    series: [{
      type: 'pie', radius: ['50%', '74%'], center: ['34%', '52%'], padAngle: 2, label: { show: false }, itemStyle: { borderRadius: 5 },
      data: data.by_type.map((row, index) => ({ name: row.label, value: row.days, itemStyle: { color: palette[index % palette.length] } })),
    }],
  });
  draw('hr-departments', {
    tooltip: { ...BASE.tooltip, valueFormatter: (v) => `${n0(v)} 天` },
    xAxis: catAxis(data.by_department.map((row) => row.label)),
    yAxis: valAxis('天数', n0),
    series: [
      { name: '请假', type: 'bar', barMaxWidth: 16, data: data.by_department.map((row) => row.leave), itemStyle: { color: BRAND, borderRadius: [4, 4, 0, 0] } },
      { name: '加班', type: 'bar', barMaxWidth: 16, data: data.by_department.map((row) => row.overtime), itemStyle: { color: COBALT, borderRadius: [4, 4, 0, 0] } },
    ],
  });
  draw('hr-trend', {
    tooltip: { ...BASE.tooltip, valueFormatter: (v) => `${n0(v)} 天` },
    xAxis: catAxis(data.trend.map((row) => row.label), { boundaryGap: false }),
    yAxis: valAxis('天数', n0),
    series: [
      { name: '请假', type: 'line', smooth: true, symbolSize: 6, data: data.trend.map((row) => row.leave), itemStyle: { color: BRAND }, lineStyle: { width: 2.5 }, areaStyle: { color: 'rgba(255,143,0,.16)' } },
      { name: '加班', type: 'line', smooth: true, symbolSize: 6, data: data.trend.map((row) => row.overtime), itemStyle: { color: COBALT }, lineStyle: { width: 2 } },
    ],
  });
}

function redraw() {
  nextTick(() => {
    if (tab.value === 'biz') { drawCost(); drawDetail(); }
    if (tab.value === 'hr') drawHr();
  });
}

function openProject(row) {
  selectedProject.value = row.project;
  costDetail.submit({ project: row.project, scope: scope.value, period: currentPeriod.value }).then(redraw);
}

function reloadScope() {
  cost.reload();
  hr.reload();
  if (selectedProject.value) costDetail.submit({ project: selectedProject.value, scope: scope.value, period: currentPeriod.value }).then(redraw);
}

function openApprovalTodo(item) {
  if (!item?.route) return;
  router.push({ path: item.route, query: item.requests?.length ? { request: item.requests[0] } : {} });
}


watch(() => cost.data, () => { if (cost.data?.visible && !selectedProject.value && cost.data.projects.length) openProject(cost.data.projects[0]); else redraw(); });
watch(() => hr.data, redraw);
watch(tab, redraw);
watch(period, () => { d.reload(); if (scope.value === 'month') reloadScope(); });
watch([scope, year], reloadScope);
watch(tabs, (list) => { if (!list.some((item) => item.key === tab.value)) tab.value = list[0]?.key || 'mine'; });

onBeforeUnmount(() => {
  chartObserver?.disconnect();
  Object.values(charts).forEach((chart) => chart.dispose());
});

const stages = [
  { route: '/personnel', n: '01', h: '人事信息', p: '员工档案', k: 'emp', unit: '人', icon: 'users' },
  { route: '/ledger', n: '02', h: '研发台账', p: '研发人员归集', k: 'ledger', unit: '人', icon: 'book-open' },
  { route: '/entry', n: '03', h: '工时汇总', p: '项目工时', k: 'hours', unit: 'h', icon: 'clock' },
  { route: '/allocation', n: '04', h: '费用分摊', p: '研发费用', k: 'cost', unit: '元', icon: 'pie-chart' },
];
</script>

<template>
  <div class="space-y-5">
    <header class="relative -mx-3 -mt-3 overflow-hidden border-b border-[#F3E7D6] bg-gradient-to-b from-[#FFF3E0] via-[#FFF9F0] to-[#F5F6F9] px-3 pb-5 pt-6 sm:-mx-4 sm:-mt-4 sm:px-4 md:-mx-7 md:-mt-7 md:px-7 lg:pb-6 lg:pt-8">
      <svg class="pointer-events-none absolute -right-16 -top-20 h-72 w-[680px]" viewBox="0 0 520 260" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <g fill="none" stroke="#FF8F00">
          <ellipse cx="300" cy="150" rx="230" ry="70" transform="rotate(-16 300 150)" stroke-opacity=".18" stroke-width="2" />
          <ellipse cx="300" cy="150" rx="170" ry="48" transform="rotate(-16 300 150)" stroke-opacity=".12" stroke-width="2" />
        </g>
        <g fill="#FF8F00">
          <rect x="120" y="96" width="9" height="9" rx="1.5" opacity=".35" />
          <rect x="134" y="84" width="9" height="9" rx="1.5" opacity=".22" />
          <rect x="134" y="98" width="9" height="9" rx="1.5" opacity=".12" />
        </g>
      </svg>
      <div class="relative flex flex-wrap items-end justify-between gap-4">
      <div>
        <div class="flex items-center gap-2 text-xs font-semibold tracking-wider text-[#E57A00]">
          <span class="grid grid-cols-2 gap-[2px]">
            <i class="h-[5px] w-[5px] rounded-[1px] bg-[#FF8F00]"></i><i class="h-[5px] w-[5px] rounded-[1px] bg-[#FF8F00]/60"></i>
            <i class="h-[5px] w-[5px] rounded-[1px] bg-[#FF8F00]/30"></i><i class="h-[5px] w-[5px]"></i>
          </span>
          示例企业管理系统 · 数据看板
        </div>
        <h1 class="mt-1.5 text-2xl font-semibold text-gray-900">{{ greeting }}<template v-if="userName">，{{ userName }}</template></h1>
        <p class="mt-1 text-sm text-gray-500">{{ scopeLabel }} · 我的待办与公司经营数据</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <div class="inline-flex rounded-lg border border-gray-200 bg-white p-0.5">
          <button v-for="option in [{ v: 'month', l: '按月' }, { v: 'year', l: '按年' }]" :key="option.v" type="button"
            class="rounded-md px-3 py-1.5 text-sm" :class="scope === option.v ? 'bg-[#FF8F00] font-semibold text-white' : 'text-gray-600 hover:bg-gray-50'"
            @click="scope = option.v">{{ option.l }}</button>
        </div>
        <input v-if="scope === 'month'" v-model="period" type="month" aria-label="选择月份" class="h-9 rounded-lg border-gray-300 bg-white px-3 text-sm" />
        <select v-else v-model.number="year" aria-label="选择年份" class="h-9 rounded-lg border-gray-300 bg-white px-3 text-sm">
          <option v-for="option in years" :key="option" :value="option">{{ option }} 年</option>
        </select>
      </div>
      </div>
      <nav v-if="tabs.length > 1" class="relative mt-4 flex flex-wrap gap-2">
      <button v-for="item in tabs" :key="item.key" type="button" class="rounded-lg px-4 py-2 text-sm"
        :class="tab === item.key ? 'bg-gray-900 font-semibold text-white' : 'text-gray-600 hover:bg-gray-100'" @click="tab = item.key">
        {{ item.label }}
        <span v-if="item.count" class="ml-1.5 rounded-full bg-[#FF8F00] px-1.5 text-xs font-semibold text-white">{{ item.count }}</span>
      </button>
      </nav>
    </header>

    <!-- 我的待办 -->
    <section v-show="tab === 'mine'" class="space-y-5">
      <div class="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
        <div class="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <div class="flex items-center justify-between border-b border-gray-200 px-5 py-3">
            <div><h2 class="text-sm font-semibold text-gray-900">要我处理</h2><p class="mt-1 text-xs text-gray-500">审批和需要我动手的事都在这里，等待最久的排在前面</p></div>
            <span class="text-sm font-semibold tabular-nums text-gray-900">{{ queue.data?.total ?? (oaTodos.data?.total || 0) }} 项</span>
          </div>
          <div v-for="item in queueItems" :key="item.name" class="flex flex-wrap items-center gap-3 border-b border-gray-100 px-5 py-3 last:border-b-0 hover:bg-[#FFFCF7]">
            <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold" :class="markOf(item.request_type).tone">{{ markOf(item.request_type).mark }}</span>
            <span class="min-w-[180px] flex-1">
              <strong class="block text-sm font-medium text-gray-900">{{ item.kind || item.request_type }} · {{ item.subject }}</strong>
              <span class="mt-0.5 block text-xs text-gray-500">{{ queueDetail(item) }}</span>
            </span>
            <span v-if="item.reason" class="shrink-0 rounded-full bg-gray-100 px-2.5 py-0.5 text-[11px] text-gray-600">{{ item.reason }}</span>
            <span class="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium" :class="item.overdue ? 'bg-red-50 text-red-700' : 'bg-[#FFF4E6] text-[#E57A00]'">{{ item.overdue ? '已超时' : '待审批' }}</span>
            <button type="button" class="shrink-0 rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-[#FF8F00]" @click="openQueueItem(item)">{{ item.reason === '我是审批人' || item.reason === '我是价格审批人' ? '去审批' : '去处理' }}</button>
          </div>
          <div v-if="queue.loading && !queueItems.length" class="px-5 py-8 text-center text-sm text-gray-400">正在加载待办…</div>
          <div v-else-if="!queueItems.length" class="px-5 py-10 text-center">
            <p class="text-sm text-gray-500">当前没有需要你处理的事项</p>
            <div class="mt-3 flex flex-wrap justify-center gap-2">
              <button v-for="item in pendingApprovalCategories" :key="item.key" type="button" class="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:border-[#FF8F00] hover:text-[#E57A00]" @click="openApprovalTodo(item)">{{ item.label }} {{ item.count }}</button>
            </div>
          </div>
          <p v-if="oaTodos.error || queue.error" class="border-t border-red-100 bg-red-50 px-5 py-3 text-xs text-red-700">审批待办加载失败：{{ errorText(queue) || errorText(oaTodos) }}</p>
        </div>

        <div v-if="myLeave.data?.visible" class="rounded-xl border border-gray-200 bg-white p-5">
          <div class="flex items-baseline justify-between"><h2 class="text-sm font-semibold text-gray-900">我的假期</h2><span class="text-xs text-gray-500">1 天 = 8 小时</span></div>
          <div class="mt-4 grid gap-3 sm:grid-cols-2">
            <div class="rounded-xl bg-[#FFF4E6] p-4">
              <div class="text-xs text-gray-600">年假可用</div>
              <div class="mt-1 text-3xl font-semibold tabular-nums text-gray-900">{{ myLeave.data.annual.available }}<span class="ml-1 text-sm font-normal text-gray-500">天</span></div>
              <div class="mt-1 text-xs text-gray-500">已发放 {{ myLeave.data.annual.granted }} 天 · 已用 {{ myLeave.data.annual.used }} 天 · 申请中 {{ myLeave.data.annual.reserved }} 天</div>
            </div>
            <div class="rounded-xl bg-[#EEF2FD] p-4">
              <div class="text-xs text-gray-600">调休可用</div>
              <div class="mt-1 text-3xl font-semibold tabular-nums text-gray-900">{{ myLeave.data.comp.available }}<span class="ml-1 text-sm font-normal text-gray-500">天</span></div>
              <div class="mt-1 text-xs text-gray-500">加班累计 {{ myLeave.data.comp.credit }} 天 · 已用 {{ myLeave.data.comp.used }} 天</div>
            </div>
          </div>
          <p v-if="myLeave.data.annual.message" class="mt-3 text-xs text-amber-700">{{ myLeave.data.annual.message }}</p>
          <p v-else class="mt-3 text-xs text-gray-500">下次发放：{{ myLeave.data.annual.next_grant_date }} 起 +{{ myLeave.data.annual.next_grant_days }} 天</p>
        </div>
      </div>

      <div v-if="myRequestItems.length" class="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div class="flex items-center justify-between border-b border-gray-200 px-5 py-3">
          <div><h2 class="text-sm font-semibold text-gray-900">我发起的申请</h2><p class="mt-1 text-xs text-gray-500">进行中和被退回的申请</p></div>
          <span class="text-sm font-semibold tabular-nums text-gray-900">{{ myRequestItems.length }} 项</span>
        </div>
        <div v-for="item in myRequestItems" :key="item.name" class="flex flex-wrap items-center gap-3 border-b border-gray-100 px-5 py-3 last:border-b-0">
          <span class="min-w-[200px] flex-1">
            <strong class="block text-sm font-medium text-gray-900">{{ item.request_type }} · {{ item.subject }}<span v-if="item.amount" class="ml-2 font-normal text-gray-500">{{ money(item.amount) }}</span></strong>
            <span class="mt-0.5 block text-xs" :class="item.returned ? 'text-red-600' : 'text-gray-500'">
              {{ item.returned ? ('被退回' + (item.returned_note ? '：' + item.returned_note : '')) : (item.step_label ? item.step_label + ' 审批中' : item.status) }}
              · 第 {{ item.done_steps }} / {{ item.total_steps }} 步
            </span>
            <span class="mt-2 flex max-w-[280px] gap-1">
              <i v-for="step in item.total_steps" :key="step" class="h-1.5 flex-1 rounded-full" :class="step <= item.done_steps ? 'bg-[#FF8F00]' : item.returned && step === item.done_steps + 1 ? 'bg-red-300' : 'bg-gray-200'"></i>
            </span>
          </span>
          <button type="button" class="shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium" :class="item.returned ? 'bg-gray-900 text-white hover:bg-[#FF8F00]' : 'border border-gray-200 text-gray-700 hover:border-[#FF8F00] hover:text-[#E57A00]'" @click="openQueueItem(item)">{{ item.returned ? '修改后重新提交' : '查看' }}</button>
        </div>
      </div>

      <div class="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div class="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-5 py-3">
          <div><h2 class="text-sm font-semibold text-gray-900">通知</h2><p class="mt-1 text-xs text-gray-500">只是知会你，需要你动手的事都在上面的「要我处理」里</p></div>
          <div class="flex flex-wrap items-center gap-3">
            <label class="flex items-center gap-1.5 text-xs text-gray-600"><input v-model="noteUnreadOnly" type="checkbox" class="rounded border-gray-300" />只看未读</label>
            <button type="button" class="text-xs text-gray-500 underline hover:text-[#E57A00]" @click="markCategoryRead">本类全部已读</button>
          </div>
        </div>
        <div class="flex flex-wrap gap-1.5 border-b border-gray-100 px-5 py-2.5">
          <button v-for="item in noteCategories" :key="item.key" type="button"
            class="rounded-lg px-3 py-1.5 text-xs" :class="noteCategory === item.key ? 'bg-gray-900 font-semibold text-white' : 'text-gray-600 hover:bg-gray-100'"
            @click="noteCategory = item.key">
            {{ item.label }}<span v-if="item.unread" class="ml-1.5 font-semibold" :class="noteCategory === item.key ? 'text-[#FFB547]' : 'text-[#E57A00]'">{{ item.unread }}</span>
          </button>
        </div>
        <button v-for="item in noteItems" :key="item.names[0]" type="button"
          class="flex w-full items-start gap-3 border-b border-gray-100 px-5 py-3 text-left last:border-b-0 hover:bg-[#FFFCF7]"
          :class="item.unread ? 'bg-[#FFFDF8]' : ''" @click="openNote(item)">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" :class="item.unread ? 'bg-[#FF8F00]' : 'bg-gray-300'"></span>
          <span class="min-w-0 flex-1">
            <strong class="block text-sm font-medium text-gray-900">{{ item.event }}<span v-if="item.title">：{{ item.title }}</span></strong>
            <span class="mt-0.5 block text-xs text-gray-500">
              {{ item.detail }}<span v-if="item.more"> · 该单据还有 {{ item.more }} 条</span>
            </span>
          </span>
          <span class="shrink-0 text-xs text-gray-400">{{ (item.created || '').slice(5, 16) }}</span>
        </button>
        <p v-if="!notifications.loading && !noteItems.length" class="px-5 py-10 text-center text-sm text-gray-400">这一类没有{{ noteUnreadOnly ? '未读' : '' }}通知</p>
      </div>
    </section>

    <!-- 经营看板 -->
    <section v-show="tab === 'biz'" class="space-y-4">
      <div v-if="cost.loading" class="flex items-center gap-2 py-8 text-sm text-gray-500"><FeatherIcon name="loader" class="h-4 w-4" /><span>正在统计公司费用...</span></div>
      <div v-else-if="cost.error" class="rounded-xl border border-red-100 bg-red-50 px-5 py-4 text-sm text-red-700">经营数据加载失败：{{ errorText(cost) }}</div>
      <div v-else-if="cost.data && !cost.data.visible" class="rounded-xl border border-gray-200 bg-white px-5 py-4 text-sm text-gray-500">你的账号没有查看公司费用的权限，仅财务和公司领导可见。</div>
      <template v-else-if="cost.data?.visible">
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-xl border-0 bg-gradient-to-br from-[#FF9B1F] to-[#F27A00] p-5 text-white">
            <div class="flex flex-wrap items-center gap-2 text-sm text-white/85">费用合计<span v-if="costPreview" class="rounded-full bg-[#FBF1DF] px-2 py-0.5 text-[11px] font-medium text-[#8A5A1C]" :title="costPreview.title">{{ costPreview.text }}</span></div>
            <div class="mt-2 text-3xl font-semibold tabular-nums">{{ money(cost.data.totals.total) }}</div>
            <div class="mt-1 text-xs text-white/85">{{ deltaText(cost.data.deltas.total) }}</div>
          </div>
          <div v-for="item in [
              { key: 'rd', label: '研发分摊（含工资、境外）', color: '#FF8F00' },
              { key: 'po', label: '采购（PO 金额）', color: '#3E63DD' },
              { key: 'expense', label: '报销', color: '#1FA58C' }]" :key="item.key"
            class="rounded-xl border border-gray-200 bg-white p-5">
            <div class="flex items-center gap-2 text-sm text-gray-600"><span class="h-2.5 w-2.5 rounded-sm" :style="{ background: item.color }"></span>{{ item.label }}<span v-if="item.key === 'rd' && costPreview" class="rounded-full bg-[#FBF1DF] px-2 py-0.5 text-[11px] font-medium text-[#8A5A1C]" :title="costPreview.title">{{ costPreview.text }}</span></div>
            <div class="mt-2 text-3xl font-semibold tabular-nums text-gray-900">{{ money(cost.data.totals[item.key]) }}</div>
            <div class="mt-1 text-xs text-gray-500">占 {{ share(cost.data.totals[item.key], cost.data.totals.total) }}% ·
              <span :class="deltaClass(cost.data.deltas[item.key])">{{ deltaText(cost.data.deltas[item.key]) }}</span></div>
          </div>
        </div>
        <p class="-mt-2 text-xs text-gray-500">研发分摊含境外委托研发；已提交研发分摊的月份，研发项目的采购和报销已包含在研发分摊里，不再重复计入。</p>

        <div class="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <div class="rounded-xl border border-gray-200 bg-white">
            <div class="flex items-baseline justify-between px-5 pt-4"><h2 class="text-sm font-semibold text-gray-900">各项目费用</h2><span class="text-xs text-gray-500">按研发分摊 / 采购 / 报销堆叠</span></div>
            <div id="cost-projects" class="h-[300px] px-2 pb-2"></div>
          </div>
          <div class="rounded-xl border border-gray-200 bg-white">
            <div class="flex items-baseline justify-between px-5 pt-4"><h2 class="text-sm font-semibold text-gray-900">费用构成</h2><span class="text-xs text-gray-500">{{ scopeLabel }}</span></div>
            <div id="cost-mix" class="h-[300px] px-2 pb-2"></div>
          </div>
        </div>

        <div class="grid gap-4 xl:grid-cols-2">
          <div class="rounded-xl border border-gray-200 bg-white">
            <div class="flex items-baseline justify-between px-5 pt-4"><h2 class="text-sm font-semibold text-gray-900">{{ scope === 'year' ? '年度费用趋势' : '月度费用趋势' }}</h2><span class="text-xs text-gray-500">{{ scope === 'year' ? '近 5 年' : '近 12 个月' }}</span></div>
            <div id="cost-trend" class="h-[300px] px-2 pb-2"></div>
          </div>
          <div class="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <div class="flex items-baseline justify-between px-5 pt-4 pb-2"><h2 class="text-sm font-semibold text-gray-900">项目费用排行</h2><span class="text-xs text-gray-500">点任意一行看该项目明细</span></div>
            <div class="overflow-x-auto">
              <table class="w-full text-sm">
                <thead><tr class="border-b border-gray-200 text-xs text-gray-500">
                  <th class="px-5 py-2 text-left font-medium">项目</th><th class="px-3 py-2 text-right font-medium">费用</th>
                  <th class="px-3 py-2 text-left font-medium">占比</th><th class="px-5 py-2 text-right font-medium">{{ compareLabel }}</th></tr></thead>
                <tbody>
                  <tr v-for="row in cost.data.projects.slice(0, 8)" :key="row.project" class="cursor-pointer border-b border-gray-100 last:border-b-0 hover:bg-[#FFFAF2]"
                    :class="row.project === selectedProject ? 'bg-[#FFF4E6]' : ''" @click="openProject(row)">
                    <td class="px-5 py-2.5 text-gray-800">{{ row.label }}</td>
                    <td class="px-3 py-2.5 text-right tabular-nums">{{ money(row.total) }}</td>
                    <td class="px-3 py-2.5"><div class="h-1.5 w-24 rounded bg-gray-100"><div class="h-full rounded bg-[#FF8F00]" :style="{ width: share(row.total, cost.data.projects[0].total) + '%' }"></div></div></td>
                    <td class="px-5 py-2.5 text-right tabular-nums" :class="deltaClass(row.delta)">{{ row.delta === null ? '—' : (row.delta > 0 ? '▲' : '▼') + ' ' + Math.abs(row.delta) + '%' }}</td>
                  </tr>
                  <tr v-if="!cost.data.projects.length"><td colspan="4" class="px-5 py-8 text-center text-sm text-gray-400">本期没有费用数据</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div v-if="costDetail.data" class="rounded-xl border border-gray-200 bg-white">
          <div class="flex items-baseline justify-between px-5 pt-4"><h2 class="text-sm font-semibold text-gray-900">{{ costDetail.data.label }} · 费用明细</h2><span class="text-xs text-gray-500">{{ scopeLabel }}</span></div>
          <div class="grid gap-0 xl:grid-cols-2">
            <div class="space-y-3 border-b border-gray-100 p-5 xl:border-b-0 xl:border-r">
              <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <div class="rounded-lg border border-gray-200 p-3"><div class="text-xs text-gray-500">费用合计</div><div class="mt-1 text-lg font-semibold tabular-nums">{{ money(costDetail.data.totals.total) }}</div></div>
                <div class="rounded-lg border border-gray-200 p-3"><div class="text-xs text-gray-500">参与人数</div><div class="mt-1 text-lg font-semibold tabular-nums">{{ costDetail.data.project === '__none__' ? '—' : costDetail.data.team + ' 人' }}</div></div>
                <div class="rounded-lg border border-gray-200 p-3"><div class="text-xs text-gray-500">分摊工时</div><div class="mt-1 text-lg font-semibold tabular-nums">{{ n0(costDetail.data.hours) }} h</div></div>
              </div>
              <div class="space-y-2 text-sm">
                <div class="flex justify-between"><span class="text-gray-600">研发分摊（含工资）</span><b class="tabular-nums">{{ money(costDetail.data.totals.rd) }}</b></div>
                <div class="flex justify-between"><span class="text-gray-600">采购（PO 金额）</span><b class="tabular-nums">{{ money(costDetail.data.totals.po) }}</b></div>
                <div class="flex justify-between"><span class="text-gray-600">报销</span><b class="tabular-nums">{{ money(costDetail.data.totals.expense) }}</b></div>
              </div>
              <div class="flex justify-between text-sm"><span class="text-gray-600">{{ costDetail.data.project === '__none__' ? '归集方式' : '项目负责人' }}</span><b>{{ costDetail.data.project === '__none__' ? '按部门归集' : (costDetail.data.owner || '未指定') }}</b></div>
              <p class="text-xs text-gray-500">{{ costDetail.data.project === '__none__' ? '未挂项目的采购和报销按发生部门归集，右侧为各部门金额。' : '明细按金额取前 8 项，颜色与上方口径一致。' }}</p>
            </div>
            <div id="cost-detail" class="h-[300px] px-2 pb-2"></div>
          </div>
        </div>
      </template>
    </section>

    <!-- 人事看板 -->
    <section v-show="tab === 'hr'" class="space-y-4">
      <div v-if="hr.loading" class="flex items-center gap-2 py-8 text-sm text-gray-500"><FeatherIcon name="loader" class="h-4 w-4" /><span>正在统计请假与加班...</span></div>
      <div v-else-if="hr.error" class="rounded-xl border border-red-100 bg-red-50 px-5 py-4 text-sm text-red-700">人事数据加载失败：{{ errorText(hr) }}</div>
      <div v-else-if="hr.data && !hr.data.visible" class="rounded-xl border border-gray-200 bg-white px-5 py-4 text-sm text-gray-500">你的账号没有查看人事统计的权限，仅人事、部门主管和公司领导可见。</div>
      <template v-else-if="hr.data?.visible">
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-xl bg-gradient-to-br from-[#FF9B1F] to-[#F27A00] p-5 text-white">
            <div class="text-sm text-white/85">本期请假</div>
            <div class="mt-2 text-3xl font-semibold tabular-nums">{{ hr.data.totals.leave_days }}<span class="ml-1 text-sm font-normal text-white/85">天</span></div>
            <div class="mt-1 text-xs text-white/85">共 {{ hr.data.totals.leave_count }} 人次</div>
          </div>
          <div class="rounded-xl border border-gray-200 bg-white p-5"><div class="text-sm text-gray-600">今日不在岗</div>
            <div class="mt-2 text-3xl font-semibold tabular-nums text-gray-900">{{ hr.data.away_today?.count || 0 }}<span class="ml-1 text-sm font-normal text-gray-500">人</span></div>
            <div class="mt-1 text-xs text-gray-500">{{ (hr.data.away_today?.by_type || []).map((row) => row.label + ' ' + row.count).join(' · ') || '今天全员在岗' }}</div></div>
          <div class="rounded-xl border border-gray-200 bg-white p-5"><div class="text-sm text-gray-600">加班</div>
            <div class="mt-2 text-3xl font-semibold tabular-nums text-gray-900">{{ hr.data.totals.overtime_days }}<span class="ml-1 text-sm font-normal text-gray-500">天</span></div>
            <div class="mt-1 text-xs text-gray-500">已计入调休额度 · 已用调休 {{ hr.data.totals.comp_days }} 天</div></div>
          <div class="rounded-xl border border-gray-200 bg-white p-5"><div class="text-sm text-gray-600">需要人事处理</div>
            <div class="mt-2 text-3xl font-semibold tabular-nums text-gray-900">{{ hr.data.alerts.missing_joining + hr.data.alerts.negative_comp }}<span class="ml-1 text-sm font-normal text-gray-500">项</span></div>
            <div class="mt-1 text-xs text-gray-500">缺入职日期 {{ hr.data.alerts.missing_joining }} 人 · 调休为负 {{ hr.data.alerts.negative_comp }} 人</div></div>
        </div>

        <div class="grid gap-4 xl:grid-cols-2">
          <div class="rounded-xl border border-gray-200 bg-white">
            <div class="flex items-baseline justify-between px-5 pt-4"><h2 class="text-sm font-semibold text-gray-900">请假类型占比</h2><span class="text-xs text-gray-500">按天数</span></div>
            <div id="hr-types" class="h-[290px] px-2 pb-2"></div>
          </div>
          <div class="rounded-xl border border-gray-200 bg-white">
            <div class="flex items-baseline justify-between px-5 pt-4"><h2 class="text-sm font-semibold text-gray-900">各部门请假与加班</h2><span class="text-xs text-gray-500">天</span></div>
            <div id="hr-departments" class="h-[290px] px-2 pb-2"></div>
          </div>
        </div>

        <div class="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <div class="rounded-xl border border-gray-200 bg-white">
            <div class="flex items-baseline justify-between px-5 pt-4"><h2 class="text-sm font-semibold text-gray-900">请假与加班趋势</h2><span class="text-xs text-gray-500">{{ scope === 'year' ? '近 5 年' : '近 12 个月' }} · 天</span></div>
            <div id="hr-trend" class="h-[290px] px-2 pb-2"></div>
          </div>
          <div class="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <div class="flex items-baseline justify-between px-5 pt-4 pb-2"><h2 class="text-sm font-semibold text-gray-900">假期余额较多的员工</h2><span class="text-xs text-gray-500">提醒安排休假</span></div>
            <div class="overflow-x-auto">
              <table class="w-full text-sm">
                <thead><tr class="border-b border-gray-200 text-xs text-gray-500"><th class="px-5 py-2 text-left font-medium">员工</th><th class="px-3 py-2 text-right font-medium">年假</th><th class="px-5 py-2 text-right font-medium">调休</th></tr></thead>
                <tbody>
                  <tr v-for="row in hr.data.balances" :key="row.employee" class="border-b border-gray-100 last:border-b-0">
                    <td class="px-5 py-2.5 text-gray-800">{{ row.employee }}<span class="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-500">{{ row.department }}</span></td>
                    <td class="px-3 py-2.5 text-right tabular-nums">{{ row.annual_days }} 天</td>
                    <td class="px-5 py-2.5 text-right tabular-nums" :class="row.comp_days < 0 ? 'text-red-600' : ''">{{ row.comp_days }} 天</td>
                  </tr>
                  <tr v-if="!hr.data.balances.length"><td colspan="3" class="px-5 py-8 text-center text-sm text-gray-400">暂无员工余额数据</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </template>
    </section>

    <!-- 研发核算 -->
    <section v-show="tab === 'rd'" class="space-y-5">
      <div v-if="d.loading" class="flex items-center gap-2 py-8 text-sm text-gray-500"><FeatherIcon name="loader" class="h-4 w-4" /><span>正在加载公司数据...</span></div>
      <template v-else-if="d.data">
        <div class="grid overflow-hidden rounded-xl border border-gray-200 bg-white sm:grid-cols-2 xl:grid-cols-4">
          <div class="border-b border-gray-200 p-5 sm:border-r xl:border-b-0"><div class="flex items-center justify-between text-sm text-gray-500"><span>员工总数</span><FeatherIcon name="users" class="h-4 w-4" /></div><div class="mt-3 text-3xl font-semibold tabular-nums text-gray-900">{{ d.data.kpi.total }}<span class="ml-1 text-sm font-normal text-gray-400">人</span></div><div class="mt-2 text-xs text-gray-500">{{ d.data.kpi.confirmed }} 人已确认归档</div></div>
          <div class="border-b border-gray-200 p-5 xl:border-b-0 xl:border-r"><div class="flex items-center justify-between text-sm text-gray-500"><span>研发台账在册</span><FeatherIcon name="book-open" class="h-4 w-4" /></div><div class="mt-3 text-3xl font-semibold tabular-nums text-gray-900">{{ d.data.kpi.ledger }}<span class="ml-1 text-sm font-normal text-gray-400">人</span></div><div class="mt-2 text-xs text-gray-500">研发信息完整后自动归集</div></div>
          <div class="border-b border-gray-200 p-5 sm:border-b-0 sm:border-r"><div class="flex items-center justify-between text-sm text-gray-500"><span>本期研发工时</span><FeatherIcon name="clock" class="h-4 w-4" /></div><div class="mt-3 text-3xl font-semibold tabular-nums text-gray-900">{{ n0(d.data.kpi.hours) }}<span class="ml-1 text-sm font-normal text-gray-400">h</span></div><div class="mt-2 text-xs text-gray-500">分布于 {{ d.data.kpi.projects }} 个在研项目</div></div>
          <div class="p-5"><div class="flex items-center justify-between text-sm text-gray-500"><span class="flex items-center gap-2">本期待分摊费用<span v-if="rdPreview" class="rounded-full bg-[#FBF1DF] px-2 py-0.5 text-[11px] font-medium text-[#8A5A1C]" :title="rdPreview.title">{{ rdPreview.text }}</span></span><FeatherIcon name="pie-chart" class="h-4 w-4" /></div><div class="mt-3 text-3xl font-semibold tabular-nums text-gray-900">{{ n0(d.data.kpi.cost) }}<span class="ml-1 text-sm font-normal text-gray-400">元</span></div><div class="mt-2 text-xs text-gray-500">按工时分配率分摊</div></div>
        </div>

        <section class="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
          <div>
            <h2 class="mb-3 text-base font-semibold text-gray-900">月度核算流程</h2>
            <div class="overflow-hidden rounded-xl border border-gray-200 bg-white">
              <button v-for="s in stages.filter((x) => canSee(x.route))" :key="s.n" type="button" class="group flex w-full items-center gap-4 border-b border-gray-200 px-4 py-3 text-left last:border-b-0 hover:bg-gray-50" @click="router.push(s.route)">
                <span class="flex h-9 w-9 items-center justify-center rounded-md bg-gray-100 text-gray-600"><FeatherIcon :name="s.icon" class="h-4 w-4" /></span><span class="w-7 text-xs font-medium text-gray-400">{{ s.n }}</span>
                <span class="min-w-0 flex-1"><strong class="block text-sm font-medium text-gray-900">{{ s.h }}</strong><span class="text-xs text-gray-500">{{ s.p }}</span></span>
                <span class="text-right"><strong class="block text-lg font-semibold tabular-nums text-gray-900">{{ n0(d.data.pipeline[s.k]) }}</strong><span class="text-xs text-gray-400">{{ s.unit }}</span></span>
                <FeatherIcon name="chevron-right" class="h-4 w-4 text-gray-300 group-hover:text-gray-600" />
              </button>
            </div>
          </div>
          <div>
            <h2 class="mb-3 text-base font-semibold text-gray-900">数据完整度</h2>
            <div class="overflow-hidden rounded-xl border border-gray-200 bg-white">
              <div class="flex items-center justify-between border-b border-gray-200 px-4 py-4"><span class="text-sm text-gray-700">员工信息待补全</span><span class="rounded-full px-2.5 py-1 text-xs font-medium" :class="d.data.todos.pending > 0 ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'">{{ d.data.todos.pending }} 人</span></div>
              <div class="flex items-center justify-between border-b border-gray-200 px-4 py-4"><span class="text-sm text-gray-700">研发工时已填报</span><span class="text-sm font-medium tabular-nums text-gray-900">{{ d.data.todos.filled }} / {{ d.data.todos.ledger }} 人</span></div>
              <div class="flex items-center justify-between border-b border-gray-200 px-4 py-4"><span class="text-sm text-gray-700">财务费用已导入</span><span class="text-sm font-medium tabular-nums text-gray-900">{{ d.data.todos.cost_items }} 项</span></div>
              <div class="flex items-center justify-between px-4 py-4"><span class="text-sm text-gray-700">宿舍费用已登记</span><span class="text-sm font-medium tabular-nums text-gray-900">{{ d.data.todos.dorm_count }} 条</span></div>
            </div>
          </div>
        </section>
      </template>
    </section>
  </div>
</template>
