<script setup>
import { ref, reactive, computed, watch } from "vue";
import { Card, Button, createResource } from "frappe-ui";
import { period } from "../lib/period";

const options = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.get_emp_options", method: "GET", auto: true });
const rows = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.list_accommodation", method: "GET", makeParams: () => ({ period: period.value }), auto: true });
const saver = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.save_accommodation" });
const remover = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.delete_accommodation" });

const form = reactive({ employee: "", rent_amount: "", water_amount: "", electricity_amount: "" });
const saving = ref(false);
const errMsg = ref("");

function pick(p) { period.value = p; rows.reload(); }
const fmt = (n) => (n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const empName = (n) => { const e = (options.data || []).find((x) => x.name === n); return e ? e.employee_name : n; };
const total = computed(() => (rows.data || []).reduce((s, r) => s + (r.total_amount || 0), 0));

async function save() {
  errMsg.value = "";
  if (!form.employee) { errMsg.value = "请选择员工"; return; }
  saving.value = true;
  try {
    const data = await saver.submit({ period: period.value, employee: form.employee,
      rent_amount: Number(form.rent_amount || 0), water_amount: Number(form.water_amount || 0),
      electricity_amount: Number(form.electricity_amount || 0) });
    rows.data = data;
    form.rent_amount = form.water_amount = form.electricity_amount = "";
  } catch (e) { errMsg.value = (e && e.message) || "保存失败"; }
  finally { saving.value = false; }
}
const isSysMgr = typeof window !== "undefined" && Array.isArray(window.roles) && window.roles.includes("System Manager");
async function del(n) { try { await remover.submit({ name: n }); rows.reload(); } catch (e) { errMsg.value = (e && e.message) || "删除失败"; } }
watch(period, () => rows.reload());
</script>

<template>
  <div class="space-y-4">
    <Card title="宿舍住宿费用" subtitle="登记每人每月房租/水费/电费，月末工资计算时作为代扣项">
      <div class="flex items-center gap-2 mb-4">
        <span class="text-sm text-gray-500">会计期间</span>
        <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
      </div>
      <div class="flex flex-wrap items-end gap-3 p-3 bg-gray-50 rounded-lg">
        <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">员工</label>
          <select v-model="form.employee" class="border border-gray-300 rounded px-3 py-2 text-sm min-w-[160px]">
            <option value="">请选择</option>
            <option v-for="e in options.data || []" :key="e.name" :value="e.name">{{ e.employee_name }}</option>
          </select></div>
        <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">房租</label>
          <input v-model="form.rent_amount" type="number" min="0" class="border border-gray-300 rounded px-3 py-2 text-sm w-28" placeholder="0" /></div>
        <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">水费</label>
          <input v-model="form.water_amount" type="number" min="0" class="border border-gray-300 rounded px-3 py-2 text-sm w-24" placeholder="0" /></div>
        <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">电费</label>
          <input v-model="form.electricity_amount" type="number" min="0" class="border border-gray-300 rounded px-3 py-2 text-sm w-24" placeholder="0" /></div>
        <Button variant="solid" :loading="saving" @click="save">保存</Button>
      </div>
      <p v-if="errMsg" class="text-red-600 text-xs mt-2">{{ errMsg }}</p>
      <p class="text-xs text-gray-400 mt-2">同一员工+期间再次保存将覆盖原记录。</p>
    </Card>

    <Card title="本期宿舍费用明细">
      <div v-if="rows.loading" class="text-gray-500 text-sm py-4">加载中…</div>
      <table v-else class="w-full text-sm">
        <thead class="text-gray-500 border-b"><tr>
          <th class="text-left px-3 py-2">员工</th><th class="text-right px-3 py-2">房租</th>
          <th class="text-right px-3 py-2">水费</th><th class="text-right px-3 py-2">电费</th>
          <th class="text-right px-3 py-2">合计</th><th class="text-right px-3 py-2">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="d in rows.data || []" :key="d.name" class="border-b last:border-0 hover:bg-gray-50">
            <td class="px-3 py-2">{{ empName(d.employee) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.rent_amount) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.water_amount) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.electricity_amount) }}</td>
            <td class="text-right px-3 py-2 font-medium tabular-nums">{{ fmt(d.total_amount) }}</td>
            <td class="text-right px-3 py-2"><button v-if="isSysMgr" @click="del(d.name)" class="text-red-600 hover:underline text-xs">删除</button></td>
          </tr>
          <tr v-if="!(rows.data || []).length"><td colspan="6" class="text-center text-gray-400 py-6">本期暂无宿舍费用，请在上方登记</td></tr>
        </tbody>
        <tfoot v-if="(rows.data || []).length"><tr class="border-t font-medium">
          <td class="px-3 py-2" colspan="4">合计</td><td class="text-right px-3 py-2 tabular-nums">{{ fmt(total) }}</td><td></td>
        </tr></tfoot>
      </table>
    </Card>
  </div>
</template>
