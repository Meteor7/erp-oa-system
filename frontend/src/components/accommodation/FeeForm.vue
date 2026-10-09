<script setup>
// 月度费用登记的内页表单（新增 / 编辑某个房间某个月的费用）。表单字段、校验和保存接口都是从原来的
// Accommodation.vue 原样搬过来的；变化只有：房间 / 月份来自地址，保存后由页面决定去哪里（回来源 / 下一间），
// 编辑已登记的房间时把已有的入住人和金额带出来。
import { computed, reactive, ref, watch } from "vue";
import { Button, Card, createResource } from "frappe-ui";
import { extractFrappeError } from "../../lib/frappeError";
import { isFormDirty, useLeaveConfirm } from "../../lib/leaveConfirm.js";
import { AMOUNT_FIELDS, SPECIAL_OCCUPANTS, amountsOf, occupantKey, recordFor, recordsOfRoom } from "../../lib/accommodationFees.js";

const props = defineProps({
  period: { type: String, required: true },
  room: { type: String, default: "" },
  mode: { type: String, default: "new" },
  rooms: { type: Array, default: () => [] },
  employees: { type: Array, default: () => [] },
  records: { type: Array, default: () => [] },
});
const emit = defineEmits(["saved", "cancel"]);

const occupantOptions = createResource({
  url: "rayher_hr_payroll.api.accommodation_entry.get_room_occupants",
  method: "GET",
  makeParams: () => ({ period: props.period, room_no: form.room_no }),
});
const saver = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.save_accommodation" });

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
const empCategory = computed(() => {
  if (form.occupant_type === "客房" && (form.room_no === "A703" || (form.room_no === "A609" && props.period === "2026-07"))) return "销售费用";
  if (SPECIAL_OCCUPANTS.includes(form.occupant_type)) return "管理费用";
  return props.employees.find((item) => item.name === form.employee)?.expense_account_category || (form.employee ? "未设置" : "-");
});
const selectedRoom = computed(() => props.rooms.find((room) => room.name === form.room_no));
const formTotal = computed(() => formPersonalTotal.value + formCompanyTotal.value);
const formPersonalTotal = computed(() => num(form.personal_rent_amount) + num(form.personal_water_amount) + num(form.personal_electricity_amount));
const formCompanyTotal = computed(() => num(form.company_rent_amount) + num(form.company_water_amount) + num(form.company_electricity_amount));

// 表单有没有改过：打开（入住人和已有金额带出之后）/ 保存之后的快照对比现在的内容；改过再离开要确认。
const fingerprint = () => JSON.stringify(form);
const baseline = ref(fingerprint());
function markClean() {
  baseline.value = fingerprint();
}
useLeaveConfirm(() => isFormDirty(fingerprint(), baseline.value));

// 这个房间本期已经登记过的记录：选到对应入住人时把金额带出来，保存就是改这一条。
const amountsJson = () => JSON.stringify(AMOUNT_FIELDS.map((field) => form[field]));
let autoFilled = null;
watch(occupantSelection, (selection) => {
  const record = recordFor(props.records, form.room_no, selection);
  if (record) {
    Object.assign(form, amountsOf(record));
    autoFilled = amountsJson();
  } else if (autoFilled !== null && amountsJson() === autoFilled) {
    Object.assign(form, amountsOf(null));
    autoFilled = null;
  }
}, { flush: "sync" });

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
    if (choices.length === 1) {
      occupantSelection.value = choices[0].value;
    } else {
      // 房间有几位入住人时，本期已登记的那一位先选上（编辑）；没有登记过的留给人选。
      const done = recordsOfRoom(props.records, form.room_no).map(occupantKey).filter((key) => choices.some((choice) => choice.value === key));
      if (done.length === 1) occupantSelection.value = done[0];
    }
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

async function save(next = false) {
  errMsg.value = "";
  if (!form.room_no) { errMsg.value = "请先选择房间号"; return; }
  if (!form.employee && !SPECIAL_OCCUPANTS.includes(form.occupant_type)) { errMsg.value = "请选择入住人"; return; }
  saving.value = true;
  try {
    const data = await saver.submit({
      period: props.period, employee: form.employee, occupant_type: form.occupant_type, room_no: form.room_no,
      personal_rent_amount: num(form.personal_rent_amount), personal_water_amount: num(form.personal_water_amount), personal_electricity_amount: num(form.personal_electricity_amount),
      company_rent_amount: num(form.company_rent_amount), company_water_amount: num(form.company_water_amount), company_electricity_amount: num(form.company_electricity_amount),
    });
    // 保存成功：先把快照更新成现在的内容，页面跳走时就不会再问"表单还没保存"。
    markClean();
    emit("saved", { data, room: form.room_no, next });
  } catch (error) {
    errMsg.value = extractFrappeError(error, "保存失败");
  } finally {
    saving.value = false;
  }
}

if (props.room) form.room_no = props.room;
watch(() => form.room_no, reloadOccupants);
// 打开时：先读出这个房间的入住人（可能带出已有金额），再记下"干净"的快照。
if (form.room_no) {
  reloadOccupants().then(markClean);
} else {
  markClean();
}
</script>

<template>
  <Card :title="mode === 'edit' ? `编辑 ${room} 的费用` : '新增费用登记'" :subtitle="`会计期间 ${period}；按基础信息中的有效入住关系登记，个人承担与公司承担相加后自动形成房间总费用`" data-fee-form>
    <div class="space-y-4 p-4 bg-gray-50 rounded-lg">
      <div class="grid gap-3 md:grid-cols-5">
        <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">房间号</label><select v-model="form.room_no" :disabled="mode === 'edit'" class="border border-gray-300 rounded px-3 py-2 text-sm disabled:bg-gray-100"><option value="">请选择房间</option><option v-for="room in rooms" :key="room.name" :value="room.name">{{ room.room_no }} · {{ room.room_type || "未设置房型" }}</option></select></div>
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

      <div class="flex flex-wrap items-center gap-3">
        <Button variant="solid" :loading="saving" :disabled="saving" data-fee-save @click="save(false)">保存</Button>
        <Button variant="subtle" :disabled="saving" data-fee-save-next @click="save(true)">保存并登记下一间</Button>
        <Button variant="ghost" :disabled="saving" data-fee-cancel @click="emit('cancel')">取消</Button>
        <p v-if="errMsg" class="text-red-600 text-xs" role="alert">{{ errMsg }}</p>
      </div>
    </div>
  </Card>
</template>
