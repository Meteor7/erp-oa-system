<script setup>
import { ref, reactive, computed, watch } from "vue";
import { useRoute } from "vue-router";
import { Card, Button, createResource } from "frappe-ui";
import AccommodationTabs from "../components/AccommodationTabs.vue";
import { period } from "../lib/period";
import { extractFrappeError } from "../lib/frappeError";

const EXPENSE_ACCOUNT_CATEGORIES = ["研发费用", "管理费用", "销售费用", "生产成本"];
const SPECIAL_OCCUPANTS = ["空", "客房", "午休室"];
// 从宿舍看板点"登记费用"进来时带上月份和房间（先设月份，再建数据请求）。
const route = useRoute();
if (/^\d{4}-\d{2}$/.test(String(route.query.period || ""))) period.value = String(route.query.period);

const options = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.get_emp_options", method: "GET", auto: true });
const roomOptions = createResource({
  url: "rayher_hr_payroll.api.accommodation_entry.get_room_options",
  method: "GET",
  auto: true,
});
const occupantOptions = createResource({
  url: "rayher_hr_payroll.api.accommodation_entry.get_room_occupants",
  method: "GET",
  makeParams: () => ({ period: period.value, room_no: form.room_no }),
});
const rows = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.list_accommodation", method: "GET", makeParams: () => ({ period: period.value }), auto: true });
const summary = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.get_accommodation_summary", method: "GET", makeParams: () => ({ period: period.value }), auto: true });
const saver = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.save_accommodation" });
const remover = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.delete_accommodation" });

const blankForm = () => ({
  employee: "", occupant_type: "员工", room_no: "",
  personal_rent_amount: "", personal_water_amount: "", personal_electricity_amount: "",
  company_rent_amount: "", company_water_amount: "", company_electricity_amount: "",
});
const form = reactive(blankForm());
const saving = ref(false);
const errMsg = ref("");
const occupantChoices = ref([]);
let occupantRequestId = 0;

const fmt = (n) => Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num = (v) => Number(v || 0);
const defaultSummaryRows = computed(() => EXPENSE_ACCOUNT_CATEGORIES.map((category) => ({
  expense_account_category: category, company_rent_amount: 0, company_water_amount: 0,
  company_electricity_amount: 0, company_total_amount: 0,
})));
const summaryRows = computed(() => (summary.data && summary.data.length ? summary.data : defaultSummaryRows.value));
const summaryTotal = computed(() => ({
  company_rent_amount: summaryRows.value.reduce((total, row) => total + num(row.company_rent_amount), 0),
  company_water_amount: summaryRows.value.reduce((total, row) => total + num(row.company_water_amount), 0),
  company_electricity_amount: summaryRows.value.reduce((total, row) => total + num(row.company_electricity_amount), 0),
  company_total_amount: summaryRows.value.reduce((total, row) => total + num(row.company_total_amount), 0),
}));
const empName = (name) => (options.data || []).find((item) => item.name === name)?.employee_name || name;
const occupantSelection = computed({
  get: () => form.employee ? `employee:${form.employee}` : (SPECIAL_OCCUPANTS.includes(form.occupant_type) ? `special:${form.occupant_type}` : ""),
  set: (value) => {
    if (value.startsWith("employee:")) {
      form.employee = value.slice(9); form.occupant_type = "员工";
    } else if (value.startsWith("special:")) {
      form.employee = ""; form.occupant_type = value.slice(8);
    } else {
      form.employee = ""; form.occupant_type = "员工";
    }
  },
});
const occupantName = (row) => SPECIAL_OCCUPANTS.includes(row.occupant_type) ? row.occupant_type : empName(row.employee);
const empCategory = computed(() => {
  if (form.occupant_type === "客房" && (form.room_no === "A703" || (form.room_no === "A609" && period.value === "2026-07"))) return "销售费用";
  if (SPECIAL_OCCUPANTS.includes(form.occupant_type)) return "管理费用";
  return (options.data || []).find((item) => item.name === form.employee)?.expense_account_category || (form.employee ? "未设置" : "-");
});
const selectedRoom = computed(() => (roomOptions.data || []).find((room) => room.name === form.room_no));
const formTotal = computed(() => formPersonalTotal.value + formCompanyTotal.value);
const formPersonalTotal = computed(() => num(form.personal_rent_amount) + num(form.personal_water_amount) + num(form.personal_electricity_amount));
const formCompanyTotal = computed(() => num(form.company_rent_amount) + num(form.company_water_amount) + num(form.company_electricity_amount));
const sumField = (field) => (rows.data || []).reduce((sum, row) => sum + Number(row[field] || 0), 0);
const isSysMgr = typeof window !== "undefined" && Array.isArray(window.roles) && window.roles.includes("System Manager");

async function reloadOccupants() {
  const requestId = ++occupantRequestId;
  occupantSelection.value = "";
  occupantChoices.value = [];
  if (!form.room_no) return;
  try {
    const data = await occupantOptions.reload();
    if (requestId !== occupantRequestId) return;
    const choices = data || [];
    occupantChoices.value = choices;
    if (choices.length === 1) occupantSelection.value = choices[0].value;
  } catch (error) {
    if (requestId !== occupantRequestId) return;
    occupantChoices.value = [];
    errMsg.value = extractFrappeError(error, "入住人加载失败");
  }
}

function occupantChoiceLabel(choice) {
  if (!choice?.end_date) return choice?.label || "";
  return `${choice.label}（${choice.start_date || "起始日期未填"} 至 ${choice.end_date}）`;
}
function reloadPeriodData() {
  rows.reload();
  summary.reload();
}

async function save() {
  errMsg.value = "";
  if (!form.room_no) { errMsg.value = "请先选择房间号"; return; }
  if (!form.employee && !SPECIAL_OCCUPANTS.includes(form.occupant_type)) { errMsg.value = "请选择入住人"; return; }
  saving.value = true;
  try {
    const data = await saver.submit({
      period: period.value, employee: form.employee, occupant_type: form.occupant_type, room_no: form.room_no,
      personal_rent_amount: num(form.personal_rent_amount), personal_water_amount: num(form.personal_water_amount), personal_electricity_amount: num(form.personal_electricity_amount),
      company_rent_amount: num(form.company_rent_amount), company_water_amount: num(form.company_water_amount), company_electricity_amount: num(form.company_electricity_amount),
    });
    rows.data = data;
    summary.reload();
    Object.assign(form, blankForm());
    occupantChoices.value = [];
  } catch (error) {
    errMsg.value = extractFrappeError(error, "保存失败");
  } finally {
    saving.value = false;
  }
}

async function del(name) {
  errMsg.value = "";
  try { await remover.submit({ name }); reloadPeriodData(); }
  catch (error) { errMsg.value = extractFrappeError(error, "删除失败"); }
}

watch(period, reloadPeriodData);
watch(() => [period.value, form.room_no], reloadOccupants);
if (route.query.room) {
  form.room_no = String(route.query.room);
  reloadOccupants();
}
</script>

<template>
  <div class="space-y-4">
    <AccommodationTabs />
    <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <Card title="当月费用管理" subtitle="按基础信息中的有效入住关系登记费用；个人承担与公司承担相加后自动形成房间总费用">
        <div class="flex items-center gap-2 mb-4">
          <span class="text-sm text-gray-500">会计期间</span>
          <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
        </div>

        <div class="space-y-4 p-4 bg-gray-50 rounded-lg">
          <div class="grid gap-3 md:grid-cols-5">
            <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">房间号</label><select v-model="form.room_no" class="border border-gray-300 rounded px-3 py-2 text-sm"><option value="">请选择房间</option><option v-for="room in roomOptions.data || []" :key="room.name" :value="room.name">{{ room.room_no }} · {{ room.room_type || "未设置房型" }}</option></select></div>
            <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">入住人</label>
              <select v-model="occupantSelection" :disabled="!form.room_no || occupantOptions.loading" class="border border-gray-300 rounded px-3 py-2 text-sm disabled:bg-gray-100">
                <option value="">{{ form.room_no ? (occupantOptions.loading ? "加载中…" : "请选择入住人") : "请先选择房间" }}</option>
                <option v-for="choice in occupantChoices" :key="choice.value" :value="choice.value">{{ occupantChoiceLabel(choice) }}</option>
              </select><span v-if="occupantSelection === 'special:空'" class="mt-1 text-[11px] text-amber-600">空（空置房间费用），可正常登记房租、水费和电费</span></div>
            <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">费用科目</label><input :value="empCategory" disabled class="border border-gray-200 rounded px-3 py-2 text-sm bg-gray-100 text-gray-500" /></div>
            <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">房间月租参考</label><input :value="selectedRoom ? fmt(selectedRoom.monthly_rent) : fmt(0)" disabled class="border border-gray-200 rounded px-3 py-2 text-sm bg-gray-100 text-right" placeholder="选择房间后显示" /></div>
            <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">总费用</label><input :value="fmt(formTotal)" disabled class="border border-gray-200 rounded px-3 py-2 text-sm bg-gray-100 text-right" /></div>
          </div>

          <div class="grid gap-4 lg:grid-cols-3">
            <div class="rounded border border-gray-200 bg-white p-3">
              <div class="text-sm font-medium mb-3">房间总费用</div>
              <div class="grid grid-cols-3 gap-2">
                <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">房租</label><input  :value="fmt(num(form.personal_rent_amount)+num(form.company_rent_amount))" disabled type="text" class="border border-gray-300 rounded px-3 py-2 text-sm text-right" placeholder="0" /></div>
                <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">水费</label><input  :value="fmt(num(form.personal_water_amount)+num(form.company_water_amount))" disabled type="text" class="border border-gray-300 rounded px-3 py-2 text-sm text-right" placeholder="0" /></div>
                <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">电费</label><input  :value="fmt(num(form.personal_electricity_amount)+num(form.company_electricity_amount))" disabled type="text" class="border border-gray-300 rounded px-3 py-2 text-sm text-right" placeholder="0" /></div>
              </div>
            </div>
            <div class="rounded border border-gray-200 bg-white p-3">
              <div class="flex items-center justify-between mb-3"><span class="text-sm font-medium">个人承担费用</span><span class="text-sm tabular-nums">{{ fmt(formPersonalTotal) }}</span></div>
              <div class="grid grid-cols-3 gap-2">
                <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">房租</label><input v-model="form.personal_rent_amount" type="number" min="0" step="0.01" class="border border-gray-300 rounded px-3 py-2 text-sm text-right" placeholder="0" /></div>
                <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">水费</label><input v-model="form.personal_water_amount" type="number" min="0" step="0.01" class="border border-gray-300 rounded px-3 py-2 text-sm text-right" placeholder="0" /></div>
                <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">电费</label><input v-model="form.personal_electricity_amount" type="number" min="0" step="0.01" class="border border-gray-300 rounded px-3 py-2 text-sm text-right" placeholder="0" /></div>
              </div>
            </div>
            <div class="rounded border border-gray-200 bg-white p-3">
              <div class="flex items-center justify-between mb-3"><span class="text-sm font-medium">公司承担费用</span><span class="text-sm tabular-nums">{{ fmt(formCompanyTotal) }}</span></div>
              <div class="grid grid-cols-3 gap-2">
                <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">房租</label><input v-model="form.company_rent_amount" type="number" min="0" step="0.01" class="border border-gray-300 rounded px-3 py-2 text-sm text-right" placeholder="0" /></div>
                <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">水费</label><input v-model="form.company_water_amount" type="number" min="0" step="0.01" class="border border-gray-300 rounded px-3 py-2 text-sm text-right" placeholder="0" /></div>
                <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">电费</label><input v-model="form.company_electricity_amount" type="number" min="0" step="0.01" class="border border-gray-300 rounded px-3 py-2 text-sm text-right" placeholder="0" /></div>
              </div>
            </div>
          </div>

          <div class="flex items-center gap-3">
            <Button variant="solid" :loading="saving" @click="save">保存</Button>
            <p v-if="errMsg" class="text-red-600 text-xs">{{ errMsg }}</p>
          </div>
        </div>
      </Card>

      <Card title="公司承担费用科目汇总" subtitle="按人员信息中的费用科目汇总本期公司承担部分">
        <div v-if="summary.loading" class="text-gray-500 text-sm py-4">加载中...</div>
        <table v-else class="w-full text-sm">
          <thead class="text-gray-500 border-b"><tr>
            <th class="text-left px-3 py-2">费用科目</th><th class="text-right px-3 py-2">房租</th>
            <th class="text-right px-3 py-2">水费</th><th class="text-right px-3 py-2">电费</th><th class="text-right px-3 py-2">小计</th>
          </tr></thead>
          <tbody>
            <tr v-for="s in summaryRows" :key="s.expense_account_category" class="border-b last:border-0">
              <td class="px-3 py-2">{{ s.expense_account_category }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(s.company_rent_amount) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(s.company_water_amount) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(s.company_electricity_amount) }}</td>
              <td class="text-right px-3 py-2 font-medium tabular-nums">{{ fmt(s.company_total_amount) }}</td>
            </tr>
          </tbody>
          <tfoot><tr class="border-t bg-gray-50 font-semibold">
            <td class="px-3 py-2">合计</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(summaryTotal.company_rent_amount) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(summaryTotal.company_water_amount) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(summaryTotal.company_electricity_amount) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(summaryTotal.company_total_amount) }}</td>
          </tr></tfoot>

        </table>
      </Card>
    </div>

    <Card title="本期宿舍费用明细">
      <div v-if="rows.loading" class="text-gray-500 text-sm py-4">加载中...</div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[1280px] text-sm">
          <thead class="text-gray-500 border-b"><tr>
            <th class="text-left px-3 py-2">房间号</th><th class="text-left px-3 py-2">入住人</th><th class="text-left px-3 py-2">费用科目</th>
            <th class="text-right px-3 py-2">个人房租</th><th class="text-right px-3 py-2">个人水费</th><th class="text-right px-3 py-2">个人电费</th><th class="text-right px-3 py-2">个人承担费用</th>
            <th class="text-right px-3 py-2">公司房租</th><th class="text-right px-3 py-2">公司水费</th><th class="text-right px-3 py-2">公司电费</th><th class="text-right px-3 py-2">公司承担费用</th>
            <th class="text-right px-3 py-2">总费用</th><th class="text-right px-3 py-2">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="d in rows.data || []" :key="d.name" class="border-b last:border-0 hover:bg-gray-50">
              <td class="px-3 py-2">{{ d.room_no }}</td>
              <td class="px-3 py-2">{{ occupantName(d) }}</td>
              <td class="px-3 py-2">{{ d.expense_account_category || "未设置" }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.personal_rent_amount) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.personal_water_amount) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.personal_electricity_amount) }}</td>
              <td class="text-right px-3 py-2 font-medium tabular-nums">{{ fmt(d.personal_total_amount) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.company_rent_amount) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.company_water_amount) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.company_electricity_amount) }}</td>
              <td class="text-right px-3 py-2 font-medium tabular-nums">{{ fmt(d.company_total_amount) }}</td>
              <td class="text-right px-3 py-2 font-medium tabular-nums">{{ fmt(d.total_amount) }}</td>
              <td class="text-right px-3 py-2"><button v-if="isSysMgr" @click="del(d.name)" class="text-red-600 hover:underline text-xs">删除</button></td>
            </tr>
            <tr v-if="!(rows.data || []).length"><td colspan="13" class="text-center text-gray-400 py-6">本期暂无宿舍费用，请在上方登记</td></tr>
          </tbody>
          <tfoot v-if="(rows.data || []).length"><tr class="border-t font-medium">
            <td class="px-3 py-2" colspan="3">合计</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("personal_rent_amount")) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("personal_water_amount")) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("personal_electricity_amount")) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("personal_total_amount")) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("company_rent_amount")) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("company_water_amount")) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("company_electricity_amount")) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("company_total_amount")) }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("total_amount")) }}</td>
            <td></td>
          </tr></tfoot>
        </table>
      </div>
    </Card>
  </div>
</template>
