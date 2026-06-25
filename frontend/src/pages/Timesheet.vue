<script setup>
import { ref, computed, watch } from "vue";
import { Card, Spinner, createResource } from "frappe-ui";
import { period } from "../lib/period";

const r = createResource({
  url: "frappe.desk.query_report.run",
  method: "GET",
  makeParams: () => ({ report_name: "研发工时表(明细)", filters: JSON.stringify({ period: period.value }) }),
  auto: true,
});
watch(period, () => r.reload());

const rows = computed(() => (r.data && r.data.result) || []);
// dynamic pivot: employees x projects
const pivot = computed(() => {
  const emps = [], projSet = new Set(), cell = {};
  for (const row of rows.value) {
    const id = row["员工id"] || row["员工ID"] || row["员工"], name = row["员工"], p = row["项目"], h = row["工时"] || 0;
    if (!id || !p) continue;
    if (!cell[id]) { cell[id] = {}; emps.push({ id, name }); }
    cell[id][p] = (cell[id][p] || 0) + h;
    projSet.add(p);
  }
  const projs = [...projSet].sort();
  const data = emps.map((e) => {
    const vals = projs.map((p) => cell[e.id][p] || 0);
    return { id: e.id, emp: e.name, vals, total: vals.reduce((a, b) => a + b, 0) };
  });
  const projTotals = projs.map((p, i) => data.reduce((s, d) => s + d.vals[i], 0));
  const grand = projTotals.reduce((a, b) => a + b, 0);
  const rates = projTotals.map((t) => (grand ? +(t / grand * 100).toFixed(2) : 0));
  return { projs, data, projTotals, grand, rates };
});
const fmt = (n) => (n || 0).toLocaleString("zh-CN");
</script>

<template>
  <Card title="研发工时表" subtitle="研发人员按项目的本期工时透视，含分配率">
    <div class="flex items-center gap-2 mb-4">
      <span class="text-sm text-gray-500">会计期间</span>
      <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
    </div>
    <div v-if="r.loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
    <div v-else-if="!pivot.data.length" class="text-gray-500 text-sm py-6">本期无工时数据</div>
    <table v-else class="w-full text-sm">
      <thead class="text-gray-500 border-b"><tr>
        <th class="text-left px-3 py-2">员工</th>
        <th v-for="p in pivot.projs" :key="p" class="text-right px-3 py-2 whitespace-nowrap">{{ p }}</th>
        <th class="text-right px-3 py-2">合计</th>
      </tr></thead>
      <tbody>
        <tr v-for="row in pivot.data" :key="row.id" class="border-b last:border-0 hover:bg-gray-50">
          <td class="px-3 py-2 whitespace-nowrap">{{ row.emp }}</td>
          <td v-for="(v, i) in row.vals" :key="i" class="text-right px-3 py-2 tabular-nums">{{ v || "" }}</td>
          <td class="text-right px-3 py-2 font-medium tabular-nums">{{ row.total }}</td>
        </tr>
      </tbody>
      <tfoot class="border-t bg-gray-50 text-gray-600">
        <tr>
          <td class="px-3 py-2">分配率%</td>
          <td v-for="(rate, i) in pivot.rates" :key="i" class="text-right px-3 py-2 tabular-nums">{{ rate }}%</td>
          <td class="text-right px-3 py-2 font-semibold">{{ fmt(pivot.grand) }}h</td>
        </tr>
      </tfoot>
    </table>
    <p class="text-xs text-gray-400 mt-3">会计期间 {{ period }} · 透视按本期实际项目动态生成</p>
  </Card>
</template>
