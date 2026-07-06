<script setup>
import { reactive, ref } from "vue";
import { Card, Button, Badge, createResource } from "frappe-ui";

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "Open", label: "进行中" },
  { value: "Completed", label: "已结束" },
  { value: "Cancelled", label: "已取消" },
];
const STAGE_OPTIONS = [
  { value: "资本化", label: "资本化" },
  { value: "费用化", label: "费用化" },
  { value: "未判定", label: "未判定" },
];

const filters = reactive({ search: "", status: "" });
const rows = createResource({
  url: "rayher_hr_payroll.api.project_entry.list_projects",
  method: "GET",
  makeParams: () => ({ search: filters.search, status: filters.status }),
  auto: true,
});
const saver = createResource({ url: "rayher_hr_payroll.api.project_entry.save_project" });
const canceler = createResource({ url: "rayher_hr_payroll.api.project_entry.cancel_project" });

const blank = () => ({ name: "", project_code: "", project_name: "", english_name: "", start_date: "", end_date: "", status: "Open", rd_stage: "费用化", allow_rd_timesheet: 1 });
const form = reactive(blank());
const editing = ref(false);
const saving = ref(false);
const errMsg = ref("");

function statusTheme(status) {
  if (status === "Completed") return "gray";
  if (status === "Cancelled") return "red";
  return "green";
}

function newProject() {
  Object.assign(form, blank());
  editing.value = true;
  errMsg.value = "";
}

function edit(row) {
  Object.assign(form, blank(), {
    name: row.name,
    project_code: row.rd_project_code || row.name,
    project_name: row.project_name || "",
    english_name: row.english_name || row.project_name || "",
    start_date: row.start_date || row.capitalization_start_date || "",
    end_date: row.end_date || row.capitalization_end_date || "",
    status: row.status || "Open",
    rd_stage: row.rd_stage || "费用化",
    allow_rd_timesheet: row.allow_rd_timesheet,
  });
  editing.value = true;
  errMsg.value = "";
}

function cancelEdit() {
  editing.value = false;
}

async function save() {
  errMsg.value = "";
  if (!form.project_code.trim() || !form.project_name.trim()) {
    errMsg.value = "请填写编号和项目名称";
    return;
  }
  saving.value = true;
  try {
    await saver.submit({ ...form });
    editing.value = false;
    rows.reload();
  } catch (e) {
    errMsg.value = e?.message || "保存失败";
  } finally {
    saving.value = false;
  }
}

async function cancelProject(name) {
  errMsg.value = "";
  try {
    await canceler.submit({ name });
    rows.reload();
  } catch (e) {
    errMsg.value = e?.message || "取消失败";
  }
}
</script>

<template>
  <div class="space-y-4">
    <Card title="项目管理">
      <template #actions>
        <Button variant="solid" @click="newProject">新增项目</Button>
      </template>

      <div class="flex flex-col gap-3 md:flex-row md:items-center mb-4">
        <input v-model="filters.search" @input="rows.reload" class="w-full md:w-72 border border-gray-300 rounded px-3 py-2 text-sm" placeholder="搜索名称/编号" />
        <select v-model="filters.status" @change="rows.reload" class="w-full md:w-44 border border-gray-300 rounded px-3 py-2 text-sm">
          <option v-for="item in STATUS_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </div>

      <div v-if="editing" class="p-4 bg-gray-50 rounded-lg mb-4 space-y-3">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">编号 *</label><input v-model="form.project_code" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">项目名称 *</label><input v-model="form.project_name" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">英文名</label><input v-model="form.english_name" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">立项时间</label><input v-model="form.start_date" type="date" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">结项时间</label><input v-model="form.end_date" type="date" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">研发阶段</label><select v-model="form.rd_stage" class="border border-gray-300 rounded px-3 py-2 text-sm"><option v-for="item in STAGE_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option></select></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">状态</label><select v-model="form.status" class="border border-gray-300 rounded px-3 py-2 text-sm"><option value="Open">进行中</option><option value="Completed">已结束</option><option value="Cancelled">已取消</option></select></div>
        </div>
        <p v-if="errMsg" class="text-red-600 text-xs">{{ errMsg }}</p>
        <div class="flex gap-2"><Button variant="solid" :loading="saving" @click="save">保存</Button><Button variant="subtle" @click="cancelEdit">取消</Button></div>
      </div>

      <p v-if="errMsg && !editing" class="text-red-600 text-xs mb-3">{{ errMsg }}</p>
      <div v-if="rows.loading" class="text-gray-500 text-sm py-4">加载中…</div>
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm min-w-[1120px]">
          <thead class="text-gray-500 border-b">
            <tr>
              <th class="text-left px-3 py-2">编号</th>
              <th class="text-left px-3 py-2">项目名称</th>
              <th class="text-left px-3 py-2">英文名</th>
              <th class="text-left px-3 py-2">立项时间</th>
              <th class="text-left px-3 py-2">结项时间</th>
              <th class="text-left px-3 py-2">研发阶段</th>
              <th class="text-left px-3 py-2">状态</th>
              <th class="text-right px-3 py-2">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows.data || []" :key="row.name" class="border-b last:border-0 hover:bg-gray-50">
              <td class="px-3 py-2 whitespace-nowrap">{{ row.rd_project_code || row.name }}</td>
              <td class="px-3 py-2 min-w-[220px]">{{ row.project_name }}</td>
              <td class="px-3 py-2 min-w-[220px]">{{ row.english_name || row.project_name }}</td>
              <td class="px-3 py-2 whitespace-nowrap">{{ row.start_date || row.capitalization_start_date || "-" }}</td>
              <td class="px-3 py-2 whitespace-nowrap">{{ row.end_date || row.capitalization_end_date || "-" }}</td>
              <td class="px-3 py-2 whitespace-nowrap">{{ row.rd_stage_label || row.rd_stage || "未判定" }}</td>
              <td class="px-3 py-2 whitespace-nowrap"><Badge :theme="statusTheme(row.status)">{{ row.status_label || row.status }}</Badge></td>
              <td class="text-right px-3 py-2 whitespace-nowrap">
                <button @click="edit(row)" class="text-blue-600 hover:underline text-xs mr-3">编辑</button>
                <button v-if="row.status !== 'Cancelled'" @click="cancelProject(row.name)" class="text-red-600 hover:underline text-xs">取消</button>
              </td>
            </tr>
            <tr v-if="!(rows.data || []).length">
              <td colspan="8" class="text-center text-gray-400 py-6">暂无项目</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>
