<script setup>
import { computed, ref, watch } from "vue";
import { Card, Button, createResource } from "frappe-ui";
import { period } from "../lib/period";

const CATS = [
  { v: "depreciation", l: "折旧" }, { v: "direct_input", l: "直接投入" },
  { v: "amortization", l: "摊销" }, { v: "personnel", l: "人工" },
  { v: "design", l: "设计" }, { v: "other", l: "其他" },
];
const ALLOCATION_TYPES = [
  { v: "common", l: "公共费用" },
  { v: "project", l: "项目费用" },
];

const items = ref([]);
const status = ref(null);
const saving = ref(false);
const errMsg = ref("");

const projects = createResource({
  url: "rayher_hr_payroll.api.project_entry.list_projects",
  method: "GET",
  auto: true,
});
const loader = createResource({
  url: "rayher_hr_payroll.api.expense_entry.get_expense",
  method: "GET",
  makeParams: () => ({ period: period.value }),
  onSuccess: (d) => {
    status.value = d.status;
    items.value = normalizeRows(d.items || []);
  },
  auto: true,
});
const saver = createResource({ url: "rayher_hr_payroll.api.expense_entry.save_expense" });

const projectOptions = computed(() => (projects.data || []).filter((project) => project.status !== "Cancelled"));
const fmt = (n) => (n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const total = computed(() => items.value.reduce((s, r) => s + Number(r.amount || 0), 0));

function normalizeRow(row = {}) {
  const directProject = row.direct_project || "";
  return {
    voucher_no: row.voucher_no || "",
    account_level_3: row.account_level_3 || "",
    category: row.category || "other",
    allocation_type: row.allocation_type || (directProject ? "project" : "common"),
    direct_project: directProject,
    amount: row.amount ?? "",
  };
}

function normalizeRows(rows) {
  return rows.map((row) => normalizeRow(row));
}

function addRow() {
  items.value.push(normalizeRow());
}

function delRow(i) {
  items.value.splice(i, 1);
}

function projectLabel(project) {
  const code = project?.rd_project_code || project?.name || "";
  const name = project?.project_name || "";
  return code && name ? `${code} | ${name}` : code || name;
}

function payloadRows() {
  return items.value.map((row) => ({
    voucher_no: row.voucher_no,
    account_level_3: row.account_level_3,
    category: row.category,
    allocation_type: row.allocation_type || "common",
    direct_project: row.allocation_type === "project" ? row.direct_project : "",
    amount: row.amount,
  }));
}

async function save() {
  errMsg.value = "";
  const missingProject = items.value.some((row) => row.allocation_type === "project" && !row.direct_project);
  if (missingProject) {
    errMsg.value = "项目费用请选择所属项目";
    return;
  }
  saving.value = true;
  try {
    const d = await saver.submit({ period: period.value, items: JSON.stringify(payloadRows()) });
    status.value = d.status;
    items.value = normalizeRows(d.items || []);
  } catch (e) {
    errMsg.value = (e && e.message) || "保存失败";
  } finally {
    saving.value = false;
  }
}
watch(period, () => loader.reload());
</script>

<template>
  <Card title="财务费用导入" subtitle="录入本期研发相关费用，按归属方式进入项目或公共费用池">
    <div class="flex items-center gap-2 mb-4">
      <span class="text-sm text-gray-500">会计期间</span>
      <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
      <span v-if="status" class="text-xs text-gray-400 ml-2">状态：{{ status }}</span>
    </div>

    <div v-if="loader.loading" class="text-gray-500 text-sm py-4">加载中…</div>
    <template v-else>
      <div class="overflow-x-auto">
        <table class="w-full min-w-[1060px] text-sm">
          <thead class="text-gray-500 border-b"><tr>
            <th class="text-left px-2 py-2 w-28">凭证号</th><th class="text-left px-2 py-2 min-w-[240px]">费用项</th>
            <th class="text-left px-2 py-2 w-32">类别</th><th class="text-left px-2 py-2 w-32">归属方式</th>
            <th class="text-left px-2 py-2 w-64">所属项目</th><th class="text-right px-2 py-2 w-32">金额</th><th class="w-12"></th>
          </tr></thead>
          <tbody>
            <tr v-for="(it, i) in items" :key="i" class="border-b last:border-0">
              <td class="px-2 py-1"><input v-model="it.voucher_no" class="border border-gray-200 rounded px-2 py-1 text-sm w-full" placeholder="V001" /></td>
              <td class="px-2 py-1"><input v-model="it.account_level_3" class="border border-gray-200 rounded px-2 py-1 text-sm w-full" placeholder="如 设备折旧费" /></td>
              <td class="px-2 py-1"><select v-model="it.category" class="border border-gray-200 rounded px-2 py-1 text-sm w-full">
                <option v-for="c in CATS" :key="c.v" :value="c.v">{{ c.l }}</option></select></td>
              <td class="px-2 py-1"><select v-model="it.allocation_type" class="border border-gray-200 rounded px-2 py-1 text-sm w-full">
                <option v-for="type in ALLOCATION_TYPES" :key="type.v" :value="type.v">{{ type.l }}</option></select></td>
              <td class="px-2 py-1"><select v-model="it.direct_project" :disabled="it.allocation_type !== 'project'" class="border border-gray-200 rounded px-2 py-1 text-sm w-full disabled:bg-gray-50 disabled:text-gray-400">
                <option value="">请选择项目</option><option v-for="project in projectOptions" :key="project.name" :value="project.name">{{ projectLabel(project) }}</option></select></td>
              <td class="px-2 py-1"><input v-model="it.amount" type="number" min="0" class="border border-gray-200 rounded px-2 py-1 text-sm w-full text-right" placeholder="0" /></td>
              <td class="px-2 py-1 text-center"><button @click="delRow(i)" class="text-red-600 text-xs hover:underline">删</button></td>
            </tr>
            <tr v-if="!items.length"><td colspan="7" class="text-center text-gray-400 py-6">本期暂无费用，点“添加一行”录入</td></tr>
          </tbody>
          <tfoot v-if="items.length"><tr class="border-t font-medium"><td colspan="5" class="px-2 py-2">合计</td>
            <td class="text-right px-2 py-2 tabular-nums">{{ fmt(total) }}</td><td></td></tr></tfoot>
        </table>
      </div>
      <div class="flex items-center gap-3 mt-4">
        <Button variant="subtle" @click="addRow">添加一行</Button>
        <Button variant="solid" :loading="saving" @click="save">保存</Button>
        <span class="text-xs text-gray-400">项目费用直接归属到所选项目，公共费用按研发工时比例分配</span>
      </div>
      <p v-if="errMsg" class="text-red-600 text-xs mt-2">{{ errMsg }}</p>
    </template>
  </Card>
</template>