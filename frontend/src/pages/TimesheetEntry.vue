<script setup>
import { ref, reactive, computed, watch } from "vue";
import { Card, Button, createResource } from "frappe-ui";
import { period } from "../lib/period";


const options = createResource({
  url: "rayher_hr_payroll.api.timesheet_entry.get_rd_options",
  method: "GET",
  auto: true,
});

const rows = createResource({
  url: "rayher_hr_payroll.api.timesheet_entry.list_rd_hours",
  method: "GET",
  makeParams: () => ({ period: period.value }),
  auto: true,
});

const form = reactive({ employee: "", project: "", hours: "" });
const saving = ref(false);
const errMsg = ref("");

const saver = createResource({ url: "rayher_hr_payroll.api.timesheet_entry.save_rd_hours" });
const remover = createResource({ url: "rayher_hr_payroll.api.timesheet_entry.delete_rd_hours" });

function pick(p) { period.value = p; rows.reload(); }

async function save() {
  errMsg.value = "";
  if (!form.employee || !form.project || form.hours === "" || Number(form.hours) < 0) {
    errMsg.value = "请选择研发人员、项目，并填写工时（0 表示删除该项）";
    return;
  }
  saving.value = true;
  try {
    const data = await saver.submit({
      period: period.value, employee: form.employee,
      project: form.project, hours: Number(form.hours),
    });
    if (saver.error) {
      const er = saver.error;
      errMsg.value = (er.messages && er.messages.join("；")) || er.message || "保存失败";
      return;
    }
    rows.data = data;
    form.hours = "";
  } catch (e) {
    errMsg.value = (e && e.message) || "保存失败";
  } finally {
    saving.value = false;
  }
}

async function del(t) {
  errMsg.value = "";
  try {
    await remover.submit({ timesheet: t });
    rows.reload();
  } catch (e) {
    errMsg.value = (e && e.messages && e.messages.join("；")) || (e && e.message) || "删除失败";
  }
}

const periodLabel = computed(() => "会计期间 " + period.value);
const total = computed(() => (rows.data || []).reduce((s, r) => s + (r.hours || 0), 0));
watch(period, () => rows.reload());
</script>

<template>
  <div class="space-y-4">
    <Card title="研发工时填报" subtitle="研发人员按项目登记本期工时，提交后生成研发工时表并作为分摊依据">
      <div class="flex items-center gap-2 mb-4">
        <span class="text-sm text-gray-500">会计期间</span>
        <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
      </div>

      <div class="flex flex-wrap items-end gap-3 p-3 bg-gray-50 rounded-lg">
        <div class="flex flex-col">
          <label class="text-xs text-gray-500 mb-1">研发人员</label>
          <select v-model="form.employee" class="border border-gray-300 rounded px-3 py-2 text-sm min-w-[180px]">
            <option value="">请选择</option>
            <option v-for="e in options.data?.employees || []" :key="e.name" :value="e.name">{{ e.employee_name }}</option>
          </select>
        </div>
        <div class="flex flex-col">
          <label class="text-xs text-gray-500 mb-1">项目</label>
          <select v-model="form.project" class="border border-gray-300 rounded px-3 py-2 text-sm min-w-[180px]">
            <option value="">请选择</option>
            <option v-for="p in options.data?.projects || []" :key="p.name" :value="p.name">{{ p.project_name }}</option>
          </select>
        </div>
        <div class="flex flex-col">
          <label class="text-xs text-gray-500 mb-1">工时(小时)</label>
          <input v-model="form.hours" type="number" min="0" step="1"
            class="border border-gray-300 rounded px-3 py-2 text-sm w-28" placeholder="0" />
        </div>
        <Button variant="solid" :loading="saving" @click="save">保存</Button>
      </div>
      <p v-if="errMsg" class="text-red-600 text-xs mt-2">{{ errMsg }}</p>
      <p class="text-xs text-gray-400 mt-2">同一员工+项目+期间再次保存将覆盖原工时；填 0 即删除。</p>
    </Card>

    <Card title="本期工时明细" :subtitle="periodLabel">
      <div v-if="rows.loading" class="text-gray-500 text-sm py-4">加载中…</div>
      <table v-else class="w-full text-sm">
        <thead class="text-gray-500 border-b"><tr>
          <th class="text-left px-3 py-2">研发人员</th>
          <th class="text-left px-3 py-2">项目</th>
          <th class="text-right px-3 py-2">工时</th>
          <th class="text-right px-3 py-2">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="r in rows.data || []" :key="r.timesheet_detail || r.timesheet" class="border-b last:border-0 hover:bg-gray-50">
            <td class="px-3 py-2">{{ r.employee_name }}</td>
            <td class="px-3 py-2">{{ r.project_name }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ r.hours }}</td>
            <td class="text-right px-3 py-2">
              <button v-if="r.rd_spa_managed" @click="del(r.timesheet)" class="text-red-600 hover:underline text-xs">删除</button><span v-else class="text-gray-400 text-xs">手工</span>
            </td>
          </tr>
          <tr v-if="!(rows.data || []).length"><td colspan="4" class="text-center text-gray-400 py-6">本期暂无工时，请在上方填报</td></tr>
        </tbody>
        <tfoot v-if="(rows.data || []).length"><tr class="border-t font-medium">
          <td class="px-3 py-2" colspan="2">合计</td>
          <td class="text-right px-3 py-2 tabular-nums">{{ total }}</td><td></td>
        </tr></tfoot>
      </table>
    </Card>
  </div>
</template>
