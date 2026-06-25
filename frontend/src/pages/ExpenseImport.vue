<script setup>
import { ref, reactive, computed, watch } from "vue";
import { Card, Button, createResource } from "frappe-ui";
import { period } from "../lib/period";

const CATS = [
  { v: "depreciation", l: "折旧" }, { v: "direct_input", l: "直接投入" },
  { v: "amortization", l: "摊销" }, { v: "personnel", l: "人工" },
  { v: "design", l: "设计" }, { v: "other", l: "其他" },
];
const items = ref([]);
const status = ref(null);
const saving = ref(false);
const errMsg = ref("");

const loader = createResource({ url: "rayher_hr_payroll.api.expense_entry.get_expense", method: "GET",
  makeParams: () => ({ period: period.value }),
  onSuccess: (d) => { status.value = d.status; items.value = (d.items || []).map((i) => ({ ...i })); },
  auto: true });
const saver = createResource({ url: "rayher_hr_payroll.api.expense_entry.save_expense" });

function pick(p) { period.value = p; loader.reload(); }
function addRow() { items.value.push({ voucher_no: "", account_level_3: "", category: "other", amount: "" }); }
function delRow(i) { items.value.splice(i, 1); }
const fmt = (n) => (n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const total = computed(() => items.value.reduce((s, r) => s + Number(r.amount || 0), 0));
const locked = computed(() => status.value === "Allocated" || status.value === "Imported");

async function save() {
  errMsg.value = "";
  saving.value = true;
  try {
    const d = await saver.submit({ period: period.value, items: JSON.stringify(items.value) });
    status.value = d.status; items.value = (d.items || []).map((i) => ({ ...i }));
  } catch (e) { errMsg.value = (e && e.message) || "保存失败"; }
  finally { saving.value = false; }
}
watch(period, () => loader.reload());
</script>

<template>
  <Card title="财务费用导入" subtitle="录入本期研发相关费用，作为分摊的费用池">
    <div class="flex items-center gap-2 mb-4">
      <span class="text-sm text-gray-500">会计期间</span>
      <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
      <span v-if="status" class="text-xs text-gray-400 ml-2">状态：{{ status }}</span>
    </div>

    <div v-if="loader.loading" class="text-gray-500 text-sm py-4">加载中…</div>
    <template v-else>
      <table class="w-full text-sm">
        <thead class="text-gray-500 border-b"><tr>
          <th class="text-left px-2 py-2 w-28">凭证号</th><th class="text-left px-2 py-2">费用项</th>
          <th class="text-left px-2 py-2 w-32">类别</th><th class="text-right px-2 py-2 w-32">金额</th><th class="w-12"></th>
        </tr></thead>
        <tbody>
          <tr v-for="(it, i) in items" :key="i" class="border-b last:border-0">
            <td class="px-2 py-1"><input v-model="it.voucher_no" :disabled="locked" class="border border-gray-200 rounded px-2 py-1 text-sm w-full" placeholder="V001" /></td>
            <td class="px-2 py-1"><input v-model="it.account_level_3" :disabled="locked" class="border border-gray-200 rounded px-2 py-1 text-sm w-full" placeholder="如 设备折旧费" /></td>
            <td class="px-2 py-1"><select v-model="it.category" :disabled="locked" class="border border-gray-200 rounded px-2 py-1 text-sm w-full">
              <option v-for="c in CATS" :key="c.v" :value="c.v">{{ c.l }}</option></select></td>
            <td class="px-2 py-1"><input v-model="it.amount" :disabled="locked" type="number" min="0" class="border border-gray-200 rounded px-2 py-1 text-sm w-full text-right" placeholder="0" /></td>
            <td class="px-2 py-1 text-center"><button v-if="!locked" @click="delRow(i)" class="text-red-600 text-xs hover:underline">删</button></td>
          </tr>
          <tr v-if="!items.length"><td colspan="5" class="text-center text-gray-400 py-6">本期暂无费用，点“添加一行”录入</td></tr>
        </tbody>
        <tfoot v-if="items.length"><tr class="border-t font-medium"><td colspan="3" class="px-2 py-2">合计</td>
          <td class="text-right px-2 py-2 tabular-nums">{{ fmt(total) }}</td><td></td></tr></tfoot>
      </table>
      <div class="flex items-center gap-3 mt-4">
        <Button v-if="!locked" variant="subtle" @click="addRow">添加一行</Button>
        <Button v-if="!locked" variant="solid" :loading="saving" @click="save">保存</Button>
        <span v-if="locked" class="text-xs text-orange-600">已提交/已分摊，如需修改请先在后台撤销</span>
      </div>
      <p v-if="errMsg" class="text-red-600 text-xs mt-2">{{ errMsg }}</p>
    </template>
  </Card>
</template>
