<script setup>
import { canSee } from "../lib/access";
import { ref, watch } from "vue";
import { useRouter } from "vue-router";
import { Card, createResource } from "frappe-ui";
import { period } from "../lib/period";

const router = useRouter();
const d = createResource({
  url: "rayher_hr_payroll.api.dashboard_entry.get_dashboard",
  method: "GET",
  makeParams: () => ({ period: period.value }),
  auto: true,
});
function pick(p) { period.value = p; d.reload(); }
const n0 = (x) => (x || 0).toLocaleString("zh-CN");
const money = (x) => (x || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const stages = [
  { route: "/personnel", n: "01 — 人事", h: "信息录入", p: "完善基本信息", k: "emp", unit: "人" },
  { route: "/ledger", n: "03 — 归集", h: "研发台账", p: "自动归入研发部", k: "ledger", unit: "人" },
  { route: "/entry", n: "05 — 工时", h: "工时汇总", p: "按项目统计", k: "hours", unit: "h" },
  { route: "/allocation", n: "07 — 分摊", h: "费用分摊", p: "按分配率分摊", k: "cost", unit: "" },
];
watch(period, () => d.reload());
</script>

<template>
  <div class="space-y-5">
    <div class="flex items-start justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-xl font-semibold">数据看板</h2>
        <p class="text-gray-500 text-sm mt-1">从人事信息录入到月末薪酬核算的全流程概览。当前会计期间 <b>{{ period }}</b>。点击任一阶段进入对应模块。</p>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-sm text-gray-500">会计期间</span>
        <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
      </div>
    </div>

    <div v-if="d.loading" class="text-gray-500 text-sm py-4">加载中…</div>
    <template v-else-if="d.data">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="bg-white border border-gray-200 rounded-xl p-4">
          <div class="text-xs text-gray-500">员工总数</div>
          <div class="text-2xl font-semibold mt-1">{{ d.data.kpi.total }}<span class="text-sm text-gray-400 ml-1">人</span></div>
          <div class="text-xs text-gray-400 mt-1">{{ d.data.kpi.confirmed }} 人已确认归档</div>
        </div>
        <div class="bg-white border border-gray-200 rounded-xl p-4">
          <div class="text-xs text-gray-500">研发台账在册</div>
          <div class="text-2xl font-semibold mt-1">{{ d.data.kpi.ledger }}<span class="text-sm text-gray-400 ml-1">人</span></div>
          <div class="text-xs text-gray-400 mt-1">研发部信息完整后自动归集</div>
        </div>
        <div class="bg-white border border-gray-200 rounded-xl p-4">
          <div class="text-xs text-gray-500">本期研发工时</div>
          <div class="text-2xl font-semibold mt-1">{{ n0(d.data.kpi.hours) }}<span class="text-sm text-gray-400 ml-1">h</span></div>
          <div class="text-xs text-gray-400 mt-1">分布于 {{ d.data.kpi.projects }} 个在研项目</div>
        </div>
        <div class="bg-white border border-gray-200 rounded-xl p-4">
          <div class="text-xs text-gray-500">本期待分摊费用</div>
          <div class="text-2xl font-semibold mt-1">{{ n0(d.data.kpi.cost) }}<span class="text-sm text-gray-400 ml-1">元</span></div>
          <div class="text-xs text-gray-400 mt-1">按工时分配率分摊</div>
        </div>
      </div>

      <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <button v-for="s in stages.filter((x) => canSee(x.route))" :key="s.n" @click="router.push(s.route)"
          class="text-left bg-white border border-gray-200 rounded-xl p-4 hover:border-gray-900 hover:shadow-sm transition">
          <div class="text-xs text-gray-400">{{ s.n }}</div>
          <div class="font-semibold mt-1">{{ s.h }}</div>
          <div class="text-xs text-gray-400">{{ s.p }}</div>
          <div class="text-lg font-semibold mt-2 tabular-nums">{{ n0(d.data.pipeline[s.k]) }}<span class="text-xs text-gray-400 ml-1">{{ s.unit }}</span></div>
        </button>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="待办事项" subtitle="需要人事 / 研发 / 财务处理的环节">
          <table class="w-full text-sm">
            <tbody>
              <tr class="border-b"><td class="py-2">未补全信息的员工</td><td class="text-right py-2">
                <span class="px-2 py-0.5 rounded-full text-xs" :class="d.data.todos.pending > 0 ? 'bg-orange-100 text-orange-700' : 'bg-green-100 text-green-700'">{{ d.data.todos.pending }} 人待处理</span></td></tr>
              <tr class="border-b"><td class="py-2">本期填报工时的研发人员</td><td class="text-right py-2">
                <span class="px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700">{{ d.data.todos.filled }} / {{ d.data.todos.ledger }} 人</span></td></tr>
              <tr class="border-b"><td class="py-2">本期已导入财务费用</td><td class="text-right py-2">
                <span class="px-2 py-0.5 rounded-full text-xs" :class="d.data.todos.cost_items > 0 ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'">{{ d.data.todos.cost_items }} 项</span></td></tr>
              <tr><td class="py-2">本期宿舍费用登记</td><td class="text-right py-2">
                <span class="px-2 py-0.5 rounded-full text-xs" :class="d.data.todos.dorm_count > 0 ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'">{{ d.data.todos.dorm_count }} 条</span></td></tr>
            </tbody>
          </table>
        </Card>

      </div>
    </template>
  </div>
</template>
