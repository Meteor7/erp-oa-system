<script setup>
import { ref, computed, watch } from "vue";
import { Card, Button, Spinner, createResource } from "frappe-ui";
import { period } from "../lib/period";

const columns = ref([]);
const result = ref([]);
const summary = ref(null);
const allocName = ref(null);
const loading = ref(false);
const recalcing = ref(false);
const msg = ref("");

const allocRes = createResource({ url: "rayher_hr_payroll.api.allocation_entry.get_allocation", method: "GET" });
const matrixRes = createResource({ url: "frappe.desk.query_report.run", method: "GET" });
const recalcRes = createResource({ url: "rayher_hr_payroll.api.allocation_entry.recalc_allocation" });

async function loadMatrix(name) {
  columns.value = []; result.value = [];
  if (!name) return;
  const d = await matrixRes.submit({ report_name: "RD Allocation Matrix", filters: JSON.stringify({ allocation: name }) });
  columns.value = d.columns || []; result.value = d.result || [];
}

async function load() {
  loading.value = true; msg.value = "";
  try {
    const a = await allocRes.submit({ period: period.value });
    summary.value = a && a.name ? a : null;
    allocName.value = a && a.name ? a.name : null;
    await loadMatrix(allocName.value);
  } finally { loading.value = false; }
}

async function pick(p) { period.value = p; await load(); }

async function recalc() {
  recalcing.value = true; msg.value = "";
  try {
    const a = await recalcRes.submit({ period: period.value });
    if (recalcRes.error) {
      const er = recalcRes.error;
      msg.value = (er.messages && er.messages.join("；")) || er.message || "重算失败";
      return;
    }
    summary.value = a; allocName.value = a.name;
    await loadMatrix(a.name);
    msg.value = "已重算：" + period.value;
  } catch (e) { msg.value = (e && e.message) || "重算失败"; }
  finally { recalcing.value = false; }
}

load();
const fmt = (n) => (typeof n === "number" ? n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : n);
const colKey = (c) => c.fieldname || c.id;
const colLabel = (c) => c.label || c.fieldname;
const isCur = (c) => c.fieldtype === "Currency";
watch(period, () => load());
</script>

<template>
  <Card title="研发费用分摊表" subtitle="按工时分配率把费用池摊到各项目，并按项目资本化阶段汇总">
    <div class="flex items-center gap-2 mb-4 flex-wrap">
      <span class="text-sm text-gray-500">会计期间</span>
      <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
      <Button variant="solid" :loading="recalcing" @click="recalc" class="ml-2">重算分摊</Button>
      <span v-if="msg" class="text-xs text-green-600 ml-1">{{ msg }}</span>
    </div>

    <div v-if="summary" class="grid grid-cols-3 gap-3 mb-4">
      <div class="p-3 bg-gray-50 rounded-lg"><div class="text-xs text-gray-500">资本化合计</div><div class="text-lg font-semibold tabular-nums">{{ fmt(summary.capitalized) }}</div></div>
      <div class="p-3 bg-gray-50 rounded-lg"><div class="text-xs text-gray-500">费用化合计</div><div class="text-lg font-semibold tabular-nums">{{ fmt(summary.expensed) }}</div></div>
      <div class="p-3 bg-gray-50 rounded-lg"><div class="text-xs text-gray-500">未判定合计</div><div class="text-lg font-semibold tabular-nums">{{ fmt(summary.unknown) }}</div></div>
    </div>

    <div v-if="loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
    <div v-else-if="!result.length" class="text-gray-500 text-sm py-6">本期暂无分摊数据，点上方「重算分摊」生成。</div>
    <template v-else>
      <table class="w-full text-sm">
        <thead class="text-gray-500 border-b"><tr>
          <th v-for="c in columns" :key="colKey(c)" class="px-3 py-2 whitespace-nowrap" :class="isCur(c) ? 'text-right' : 'text-left'">{{ colLabel(c) }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="(row, i) in result" :key="i" class="border-b last:border-0 hover:bg-gray-50">
            <td v-for="c in columns" :key="colKey(c)" class="px-3 py-2 tabular-nums" :class="isCur(c) ? 'text-right' : 'text-left'">{{ isCur(c) ? fmt(row[colKey(c)]) : row[colKey(c)] }}</td>
          </tr>
        </tbody>
      </table>
      <p class="text-xs text-gray-400 mt-3">分摊单 {{ allocName }} · 共 {{ result.length }} 行</p>
    </template>
  </Card>
</template>
