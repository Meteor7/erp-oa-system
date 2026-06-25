<script setup>
import { ref, computed, watch } from "vue";
import { Card, Spinner, createResource } from "frappe-ui";
import { period } from "../lib/period";

const r = createResource({
  url: "frappe.desk.query_report.run",
  method: "GET",
  makeParams: () => ({ report_name: "研发人员台账", filters: JSON.stringify({ period: period.value }) }),
  auto: true,
});
watch(period, () => r.reload());
const columns = computed(() => (r.data && r.data.columns) || []);
const result = computed(() => (r.data && r.data.result) || []);
const fmt = (n) => (typeof n === "number" ? n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : n);
const colKey = (c) => c.fieldname || c.id;
const colLabel = (c) => c.label || c.fieldname;
const isNum = (c) => c.fieldtype === "Currency" || c.fieldtype === "Float" || c.fieldtype === "Int";
const isCur = (c) => c.fieldtype === "Currency";
</script>

<template>
  <Card title="研发人员台账" subtitle="SUB研发人员台账">
    <div class="flex items-center gap-2 mb-4">
      <span class="text-sm text-gray-500">会计期间</span>
      <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
    </div>
    <div v-if="r.loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
    <div v-else-if="!result.length" class="text-gray-500 text-sm py-6">本期无数据</div>
    <table v-else class="w-full text-sm">
      <thead class="text-gray-500 border-b"><tr>
        <th v-for="c in columns" :key="colKey(c)" class="px-3 py-2 whitespace-nowrap" :class="isNum(c) ? 'text-right' : 'text-left'">{{ colLabel(c) }}</th>
      </tr></thead>
      <tbody>
        <tr v-for="(row, i) in result" :key="i" class="border-b last:border-0 hover:bg-gray-50">
          <td v-for="c in columns" :key="colKey(c)" class="px-3 py-2 tabular-nums" :class="isNum(c) ? 'text-right' : 'text-left'">{{ isCur(c) ? fmt(row[colKey(c)]) : row[colKey(c)] }}</td>
        </tr>
      </tbody>
    </table>
    <p class="text-xs text-gray-400 mt-3">共 {{ result.length }} 行 · 报表 研发人员台账</p>
  </Card>
</template>
