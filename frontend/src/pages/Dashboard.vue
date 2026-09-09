<script setup>
import { computed, watch } from "vue";
import { useRouter } from "vue-router";
import { FeatherIcon, createResource } from "frappe-ui";
import { canSee } from "../lib/access";
import { period } from "../lib/period";

const router = useRouter();
const d = createResource({ url: "rayher_hr_payroll.api.dashboard_entry.get_dashboard", method: "GET", makeParams: () => ({ period: period.value }), auto: true });
const oaTodos = createResource({ url: "rayher_hr_payroll.api.oa_entry.get_my_approval_summary", method: "GET", auto: true });
const procurement = createResource({ url: "rayher_hr_payroll.api.dashboard_entry.get_procurement_overview", method: "GET", auto: true });
const notifications = createResource({ url: "rayher_hr_payroll.api.oa_entry.get_my_notifications", method: "GET", makeParams: () => ({ limit: 8 }), auto: true });
const todoPresentation = {
  leave: { icon: "calendar", accent: "text-sky-700", surface: "bg-sky-50" },
  procurement: { icon: "clipboard", accent: "text-amber-700", surface: "bg-amber-50" },
  direct_purchase: { icon: "shopping-cart", accent: "text-emerald-700", surface: "bg-emerald-50" },
  procurement_payment: { icon: "credit-card", accent: "text-indigo-700", surface: "bg-indigo-50" },
  expense_payment: { icon: "file-text", accent: "text-rose-700", surface: "bg-rose-50" },
};
const todoCategories = computed(() => (oaTodos.data?.categories || []).map((item) => ({ ...item, ...(todoPresentation[item.key] || { icon: "inbox", accent: "text-gray-700", surface: "bg-gray-50" }) })));
const pendingApprovalCategories = computed(() => todoCategories.value.filter((item) => Number(item.count || 0) > 0));
const firstPendingTodo = computed(() => pendingApprovalCategories.value[0] || null);
const businessTodoCount = computed(() => (procurement.data?.action_items || []).length);
const actionItems = computed(() => procurement.data?.action_items || []);
const actionTone = (severity) => ({ urgent: 'bg-red-50 text-red-700', attention: 'bg-amber-50 text-amber-700', ready: 'bg-sky-50 text-sky-700' }[severity] || 'bg-gray-100 text-gray-600');
const actionLabel = (severity) => ({ urgent: '紧急', attention: '需关注', ready: '待办理' }[severity] || '待处理');
const stageItems = computed(() => procurement.data?.stages || []);
function openApprovalTodo(item) {
  if (!item?.route) return;
  const query = item.requests?.length ? { request: item.requests[0] } : {};
  router.push({ path: item.route, query });
}
function openFirstTodo() { if (firstPendingTodo.value) openApprovalTodo(firstPendingTodo.value); }
function openProcurementItem(item) {
  if (!item?.route) return;
  router.push({ path: item.route, query: item.filter ? { status: item.filter } : {} });
}
function openAlert(item) { router.push({ path: item.route, query: item.po ? { po: item.po } : {} }); }
function openNotification(item) {
  const link = String(item?.link || '');
  if (!link) return;
  window.location.assign(link);
}
function notificationDetail(item) {
  const content = String(item?.email_content || '').trim();
  const subject = String(item?.subject || '').trim();
  const document = String(item?.document_name || '').trim();
  if (content && content !== subject && content !== document) return content.replace(subject, '').trim() || '待查看业务通知';
  return '待查看业务通知';
}
const n0 = (x) => (x || 0).toLocaleString("zh-CN");
const money = (x) => Number(x || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const stages = [
  { route: "/personnel", n: "01", h: "人事信息", p: "员工档案", k: "emp", unit: "人", icon: "users" },
  { route: "/ledger", n: "02", h: "研发台账", p: "研发人员归集", k: "ledger", unit: "人", icon: "book-open" },
  { route: "/entry", n: "03", h: "工时汇总", p: "项目工时", k: "hours", unit: "h", icon: "clock" },
  { route: "/allocation", n: "04", h: "费用分摊", p: "研发费用", k: "cost", unit: "元", icon: "pie-chart" },
];
watch(period, () => d.reload());
</script>

<template>
  <div class="space-y-6">
    <header class="flex flex-wrap items-center justify-between gap-4 border-b border-gray-200 pb-4">
      <div><h1 class="text-xl font-semibold text-gray-900">数据看板</h1><p class="mt-1 text-sm text-gray-500">个人审批工作台与本期经营数据</p></div>
      <label class="flex items-center gap-3 text-sm text-gray-600"><span>会计期间</span><input v-model="period" type="month" class="h-9 rounded-md border-gray-300 bg-white px-3 text-sm shadow-none" /></label>
    </header>

    <section class="overflow-hidden rounded-lg border border-gray-200 bg-white">
      <div class="flex items-center justify-between border-b border-gray-200 px-4 py-3"><div><h2 class="text-sm font-semibold text-gray-900">审批待办</h2><p class="mt-1 text-xs text-gray-500">只有需要你作出审批决定的事项会出现在这里</p></div><span class="text-sm font-semibold tabular-nums text-gray-900">{{ oaTodos.data?.total || 0 }} 项</span></div>
      <div v-if="pendingApprovalCategories.length" class="flex flex-wrap items-center gap-2 px-4 py-3">
        <button v-for="item in pendingApprovalCategories" :key="item.key" type="button" class="inline-flex items-center gap-2 rounded-md border border-gray-200 px-3 py-2 text-left hover:bg-gray-50" @click="openApprovalTodo(item)"><FeatherIcon :name="item.icon" class="h-4 w-4" :class="item.accent" /><span class="text-sm text-gray-700">{{ item.label }}</span><strong class="tabular-nums text-gray-900">{{ item.count }}</strong><FeatherIcon name="arrow-right" class="h-3.5 w-3.5 text-gray-300" /></button>
      </div>
      <div v-else-if="!oaTodos.loading" class="px-4 py-3 text-sm text-gray-500">当前没有审批待办</div>
      <p v-if="oaTodos.loading" class="border-t border-gray-200 px-5 py-3 text-xs text-gray-500">正在更新审批待办...</p>
      <p v-if="oaTodos.error" class="border-t border-red-100 bg-red-50 px-5 py-3 text-xs text-red-700">审批待办加载失败，请刷新后重试</p>
    </section>

    <section v-if="procurement.data?.visible" class="space-y-5">
      <div class="flex items-end justify-between gap-3"><div><h2 class="text-base font-semibold text-gray-900">现在要处理</h2><p class="mt-1 text-xs text-gray-500">每个付款期只显示一条行动项，先处理紧急和阻塞事项</p></div><strong class="text-lg tabular-nums text-gray-900">{{ businessTodoCount }} 项</strong></div>
      <div class="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <button v-for="item in actionItems.slice(0, 6)" :key="item.key" type="button" class="flex w-full items-center gap-3 border-b border-gray-100 px-4 py-3 text-left last:border-b-0 hover:bg-gray-50" @click="openAlert(item)">
          <span class="rounded px-2 py-1 text-[11px] font-medium" :class="actionTone(item.severity)">{{ actionLabel(item.severity) }}</span>
          <span class="min-w-0 flex-1"><strong class="block truncate text-sm font-medium text-gray-900">{{ item.action }}：{{ item.detail }}</strong><span class="mt-0.5 block truncate text-xs text-gray-500">当前节点：{{ item.status }} · {{ item.title }}<span v-if="item.context"> · 还需{{ item.context }}</span><span v-if="item.due_label"> · {{ item.due_label }}</span></span></span>
          <FeatherIcon name="arrow-right" class="h-4 w-4 shrink-0 text-gray-300" />
        </button>
        <p v-if="!actionItems.length" class="px-4 py-8 text-center text-sm text-gray-400">当前没有需要处理的采购事项</p>
      </div>
      <div class="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div class="border-b border-gray-200 px-4 py-3"><h3 class="text-sm font-semibold text-gray-900">流程位置</h3><p class="mt-1 text-xs text-gray-500">看数量集中在哪个阶段，不展开业务细节</p></div>
        <div class="grid sm:grid-cols-2 xl:grid-cols-4">
          <button v-for="stage in stageItems" :key="stage.key" type="button" class="flex items-center justify-between border-b border-gray-100 px-4 py-4 text-left hover:bg-gray-50 xl:border-b-0 xl:border-r last:border-r-0" @click="router.push(stage.route)"><span><span class="block text-xs text-gray-500">{{ stage.label }}</span><strong class="mt-1 block text-2xl tabular-nums text-gray-900">{{ stage.value }}</strong></span><FeatherIcon name="chevron-right" class="h-4 w-4 text-gray-300" /></button>
        </div>
      </div>
      <div v-if="procurement.data.can_view_financial" class="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div class="grid grid-cols-2 divide-x divide-gray-200 sm:grid-cols-4"><div class="p-3"><div class="text-xs text-gray-500">PO计划总额</div><div class="mt-1 text-base font-semibold tabular-nums">¥ {{ money(procurement.data.amounts.po_total) }}</div></div><div class="p-3"><div class="text-xs text-gray-500">累计已付</div><div class="mt-1 text-base font-semibold tabular-nums">¥ {{ money(procurement.data.amounts.paid) }}</div></div><div class="p-3"><div class="text-xs text-gray-500">剩余未付</div><div class="mt-1 text-base font-semibold tabular-nums">¥ {{ money(procurement.data.amounts.unpaid) }}</div></div><div class="p-3"><div class="text-xs text-gray-500">可提交付款</div><div class="mt-1 text-base font-semibold tabular-nums">¥ {{ money(procurement.data.amounts.payable) }}</div></div></div>
      </div>
    </section>

    <section class="overflow-hidden rounded-lg border border-gray-200 bg-white">
      <div class="flex items-center justify-between border-b border-gray-200 px-5 py-3"><div><h2 class="text-sm font-semibold text-gray-900">通知</h2><p class="mt-1 text-xs text-gray-500">只保留需要你知道或行动的消息</p></div><span class="rounded bg-red-50 px-2 py-1 text-xs font-medium text-red-700">未读 {{ notifications.data?.unread || 0 }}</span></div>
      <button v-for="item in notifications.data?.items || []" :key="item.name" type="button" class="flex w-full items-center gap-3 border-b border-gray-100 px-5 py-3 text-left last:border-b-0 hover:bg-gray-50" @click="openNotification(item)"><span class="h-2 w-2 shrink-0 rounded-full" :class="item.read ? 'bg-gray-300' : 'bg-red-500'"></span><span class="min-w-0 flex-1"><strong class="block truncate text-sm font-medium text-gray-900">{{ item.subject || item.document_name }}</strong><span class="mt-0.5 block truncate text-xs text-gray-500">{{ item.read ? '已读' : '待查看' }} · {{ notificationDetail(item) }}</span></span><FeatherIcon name="external-link" class="h-4 w-4 text-gray-300" /></button>
      <p v-if="!notifications.loading && !(notifications.data?.items || []).length" class="px-5 py-8 text-center text-sm text-gray-400">暂无通知</p>
    </section>

    <div v-if="d.loading" class="flex items-center gap-2 py-8 text-sm text-gray-500"><FeatherIcon name="loader" class="h-4 w-4" /><span>正在加载公司数据...</span></div>
    <template v-else-if="d.data">
      <section>
        <div class="mb-3"><h2 class="text-base font-semibold text-gray-900">本期经营概览</h2><p class="mt-1 text-xs text-gray-500">{{ period }} 数据快照</p></div>
        <div class="grid overflow-hidden rounded-lg border border-gray-200 bg-white sm:grid-cols-2 xl:grid-cols-4">
          <div class="border-b border-gray-200 p-5 sm:border-r xl:border-b-0"><div class="flex items-center justify-between text-sm text-gray-500"><span>员工总数</span><FeatherIcon name="users" class="h-4 w-4" /></div><div class="mt-3 text-3xl font-semibold tabular-nums text-gray-900">{{ d.data.kpi.total }}<span class="ml-1 text-sm font-normal text-gray-400">人</span></div><div class="mt-2 text-xs text-gray-500">{{ d.data.kpi.confirmed }} 人已确认归档</div></div>
          <div class="border-b border-gray-200 p-5 xl:border-b-0 xl:border-r"><div class="flex items-center justify-between text-sm text-gray-500"><span>研发台账在册</span><FeatherIcon name="book-open" class="h-4 w-4" /></div><div class="mt-3 text-3xl font-semibold tabular-nums text-gray-900">{{ d.data.kpi.ledger }}<span class="ml-1 text-sm font-normal text-gray-400">人</span></div><div class="mt-2 text-xs text-gray-500">研发信息完整后自动归集</div></div>
          <div class="border-b border-gray-200 p-5 sm:border-b-0 sm:border-r"><div class="flex items-center justify-between text-sm text-gray-500"><span>本期研发工时</span><FeatherIcon name="clock" class="h-4 w-4" /></div><div class="mt-3 text-3xl font-semibold tabular-nums text-gray-900">{{ n0(d.data.kpi.hours) }}<span class="ml-1 text-sm font-normal text-gray-400">h</span></div><div class="mt-2 text-xs text-gray-500">分布于 {{ d.data.kpi.projects }} 个在研项目</div></div>
          <div class="p-5"><div class="flex items-center justify-between text-sm text-gray-500"><span>本期待分摊费用</span><FeatherIcon name="pie-chart" class="h-4 w-4" /></div><div class="mt-3 text-3xl font-semibold tabular-nums text-gray-900">{{ n0(d.data.kpi.cost) }}<span class="ml-1 text-sm font-normal text-gray-400">元</span></div><div class="mt-2 text-xs text-gray-500">按工时分配率分摊</div></div>
        </div>
      </section>

      <section class="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
        <div>
          <h2 class="mb-3 text-base font-semibold text-gray-900">月度核算流程</h2>
          <div class="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <button v-for="s in stages.filter((x) => canSee(x.route))" :key="s.n" type="button" class="group flex w-full items-center gap-4 border-b border-gray-200 px-4 py-3 text-left last:border-b-0 hover:bg-gray-50" @click="router.push(s.route)">
              <span class="flex h-9 w-9 items-center justify-center rounded-md bg-gray-100 text-gray-600"><FeatherIcon :name="s.icon" class="h-4 w-4" /></span><span class="w-7 text-xs font-medium text-gray-400">{{ s.n }}</span><span class="min-w-0 flex-1"><strong class="block text-sm font-medium text-gray-900">{{ s.h }}</strong><span class="text-xs text-gray-500">{{ s.p }}</span></span><span class="text-right"><strong class="block text-lg font-semibold tabular-nums text-gray-900">{{ n0(d.data.pipeline[s.k]) }}</strong><span class="text-xs text-gray-400">{{ s.unit }}</span></span><FeatherIcon name="chevron-right" class="h-4 w-4 text-gray-300 group-hover:text-gray-600" />
            </button>
          </div>
        </div>
        <div>
          <h2 class="mb-3 text-base font-semibold text-gray-900">数据完整度</h2>
          <div class="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <div class="flex items-center justify-between border-b border-gray-200 px-4 py-4"><span class="text-sm text-gray-700">员工信息待补全</span><span class="rounded-full px-2.5 py-1 text-xs font-medium" :class="d.data.todos.pending > 0 ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'">{{ d.data.todos.pending }} 人</span></div>
            <div class="flex items-center justify-between border-b border-gray-200 px-4 py-4"><span class="text-sm text-gray-700">研发工时已填报</span><span class="text-sm font-medium tabular-nums text-gray-900">{{ d.data.todos.filled }} / {{ d.data.todos.ledger }} 人</span></div>
            <div class="flex items-center justify-between border-b border-gray-200 px-4 py-4"><span class="text-sm text-gray-700">财务费用已导入</span><span class="text-sm font-medium tabular-nums text-gray-900">{{ d.data.todos.cost_items }} 项</span></div>
            <div class="flex items-center justify-between px-4 py-4"><span class="text-sm text-gray-700">宿舍费用已登记</span><span class="text-sm font-medium tabular-nums text-gray-900">{{ d.data.todos.dorm_count }} 条</span></div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
