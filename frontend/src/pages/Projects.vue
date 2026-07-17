<script setup>
import { reactive, ref } from "vue";
import { Card, Button, Badge, createResource } from "frappe-ui";
import { canAdministerProjects } from "../lib/access";
import { exportTableWorkbook } from "../lib/tableExport";

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
const FILE_ACCEPT = ".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png";

const filters = reactive({ search: "", status: "" });
const rows = createResource({
  url: "rayher_hr_payroll.api.project_entry.list_projects",
  method: "GET",
  makeParams: () => ({ search: filters.search, status: filters.status }),
  auto: true,
});
const owners = createResource({
  url: "rayher_hr_payroll.api.project_entry.list_project_owners",
  method: "GET",
  auto: canAdministerProjects(),
});
const saver = createResource({ url: "rayher_hr_payroll.api.project_entry.save_project" });
const canceler = createResource({ url: "rayher_hr_payroll.api.project_entry.cancel_project" });

const blank = () => ({
  name: "",
  project_code: "",
  project_name: "",
  project_owner: "",
  project_owner_name: "",
  start_date: "",
  end_date: "",
  status: "Open",
  rd_stage: "费用化",
  allow_rd_timesheet: 1,
  project_initiation_report: "",
  project_completion_report: "",
  capitalization_confirmation_file: "",
});
const form = reactive(blank());
const editing = ref(false);
const saving = ref(false);
const exporting = ref(false);
const uploadingField = ref("");
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
    project_owner: row.project_owner || "",
    project_owner_name: row.project_owner_name || "",
    start_date: row.start_date || row.capitalization_start_date || "",
    end_date: row.end_date || row.capitalization_end_date || "",
    status: row.status || "Open",
    rd_stage: row.rd_stage || "费用化",
    allow_rd_timesheet: row.allow_rd_timesheet,
    project_initiation_report: row.project_initiation_report || "",
    project_completion_report: row.project_completion_report || "",
    capitalization_confirmation_file: row.capitalization_confirmation_file || "",
  });
  editing.value = true;
  errMsg.value = "";
}

function cancelEdit() {
  editing.value = false;
}

function ownerLabel(ownerName, displayName = "") {
  if (displayName) return displayName;
  if (!ownerName) return "-";
  const owner = (owners.data || []).find((item) => item.name === ownerName);
  return owner?.full_name || ownerName;
}

function syncOwnerName() {
  const owner = (owners.data || []).find((item) => item.name === form.project_owner);
  form.project_owner_name = owner?.full_name || "";
}

function fileName(url) {
  if (!url) return "";
  const clean = String(url).split("?")[0];
  return decodeURIComponent(clean.split("/").pop() || clean);
}

function reportDownloadUrl(row, fieldname) {
  return "/api/method/rayher_hr_payroll.api.project_entry.download_project_report?project="
    + encodeURIComponent(row.name)
    + "&fieldname="
    + encodeURIComponent(fieldname);
}

async function uploadProjectFile(fieldName, event) {
  const input = event.target;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  uploadingField.value = fieldName;
  errMsg.value = "";
  try {
    const body = new FormData();
    body.append("file", file);
    body.append("is_private", "1");
    const headers = {};
    if (window.csrf_token) headers["X-Frappe-CSRF-Token"] = window.csrf_token;
    const response = await fetch("/api/method/upload_file", {
      method: "POST",
      credentials: "same-origin",
      headers,
      body,
    });
    const payload = await response.json();
    const fileUrl = payload?.message?.file_url;
    if (!response.ok || !fileUrl) throw new Error(payload?.exception || "文件上传失败");
    form[fieldName] = fileUrl;
  } catch (error) {
    errMsg.value = error?.message || "文件上传失败";
  } finally {
    uploadingField.value = "";
  }
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
  } catch (error) {
    errMsg.value = error?.message || "保存失败";
  } finally {
    saving.value = false;
  }
}

async function cancelProject(name) {
  errMsg.value = "";
  try {
    await canceler.submit({ name });
    rows.reload();
  } catch (error) {
    errMsg.value = error?.message || "取消失败";
  }
}

async function exportCurrentProjects() {
  exporting.value = true;
  errMsg.value = "";
  try {
    await exportTableWorkbook({
      filename: "研发项目管理",
      sheetName: "研发项目",
      rows: rows.data || [],
      columns: [
        { label: "项目代码", value: (row) => row.rd_project_code || row.name, width: 14 },
        { label: "项目名称", key: "project_name", width: 28 },
        { label: "项目负责人", value: (row) => ownerLabel(row.project_owner, row.project_owner_name), width: 28 },
        { label: "立项时间", value: (row) => row.start_date || row.capitalization_start_date || "", width: 14 },
        { label: "结项时间", value: (row) => row.end_date || row.capitalization_end_date || "", width: 14 },
        { label: "研发阶段", value: (row) => row.rd_stage_label || row.rd_stage || "", width: 14 },
        { label: "状态", value: (row) => row.status_label || row.status || "", width: 14 },
        { label: "立项报告", key: "project_initiation_report", width: 36 },
        { label: "结项报告", key: "project_completion_report", width: 36 },
        { label: "资本化确认书", key: "capitalization_confirmation_file", width: 36 },
      ],
    });
  } catch (error) {
    errMsg.value = error?.message || "导出失败";
  } finally {
    exporting.value = false;
  }
}
</script>

<template>
  <div class="space-y-4">
    <Card title="项目管理">
      <template #actions>
        <div class="flex items-center gap-2">
          <Button variant="subtle" :loading="exporting" :disabled="!(rows.data || []).length" @click="exportCurrentProjects">导出Excel</Button>
          <Button v-if="canAdministerProjects()" variant="solid" @click="newProject">新增项目</Button>
        </div>
      </template>

      <div class="mb-4 flex flex-col gap-3 md:flex-row md:items-center">
        <input v-model="filters.search" @input="rows.reload" class="w-full rounded border border-gray-300 px-3 py-2 text-sm md:w-72" placeholder="搜索名称/编号" />
        <select v-model="filters.status" @change="rows.reload" class="w-full rounded border border-gray-300 px-3 py-2 text-sm md:w-44">
          <option v-for="item in STATUS_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </div>

      <div v-if="editing" class="mb-4 space-y-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
        <div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div class="flex flex-col"><label class="mb-1 text-xs text-gray-500">编号 *</label><input v-model="form.project_code" class="rounded border border-gray-300 px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="mb-1 text-xs text-gray-500">项目名称 *</label><input v-model="form.project_name" class="rounded border border-gray-300 px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="mb-1 text-xs text-gray-500">项目负责人</label><select v-if="canAdministerProjects()" v-model="form.project_owner" class="rounded border border-gray-300 px-3 py-2 text-sm" @change="syncOwnerName"><option value="">未指定</option><option v-for="owner in owners.data || []" :key="owner.name" :value="owner.name">{{ owner.full_name || owner.name }} · {{ owner.name }}</option></select><div v-else class="rounded border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700">{{ ownerLabel(form.project_owner, form.project_owner_name) }}</div></div>
          <div class="flex flex-col"><label class="mb-1 text-xs text-gray-500">研发阶段</label><select v-model="form.rd_stage" class="rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in STAGE_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option></select></div>
          <div class="flex flex-col"><label class="mb-1 text-xs text-gray-500">立项时间</label><input v-model="form.start_date" type="date" class="rounded border border-gray-300 px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="mb-1 text-xs text-gray-500">结项时间</label><input v-model="form.end_date" type="date" class="rounded border border-gray-300 px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="mb-1 text-xs text-gray-500">状态</label><select v-model="form.status" class="rounded border border-gray-300 px-3 py-2 text-sm"><option value="Open">进行中</option><option value="Completed">已结束</option><option v-if="canAdministerProjects() || form.status === 'Cancelled'" value="Cancelled">已取消</option></select></div>
        </div>

        <div class="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div v-for="fileField in [
            { key: 'project_initiation_report', label: '立项报告' },
            { key: 'project_completion_report', label: '结项报告' },
            { key: 'capitalization_confirmation_file', label: '资本化确认书' },
          ]" :key="fileField.key" class="rounded border border-gray-200 bg-white p-3">
            <div class="mb-2 text-xs font-medium text-gray-600">{{ fileField.label }}</div>
            <div class="flex min-h-8 flex-wrap items-center gap-2">
              <a v-if="form[fileField.key]" :href="reportDownloadUrl(form, fileField.key)" target="_blank" rel="noopener" class="max-w-[220px] truncate text-xs text-blue-600 hover:underline">{{ fileName(form[fileField.key]) }}</a>
              <span v-else class="text-xs text-gray-400">未上传</span>
              <label class="cursor-pointer rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-700 hover:bg-gray-50">
                {{ uploadingField === fileField.key ? '上传中…' : '上传' }}
                <input type="file" class="hidden" :accept="FILE_ACCEPT" :disabled="Boolean(uploadingField)" @change="uploadProjectFile(fileField.key, $event)" />
              </label>
              <button v-if="form[fileField.key]" type="button" class="text-xs text-red-600 hover:underline" @click="form[fileField.key] = ''">清除</button>
            </div>
          </div>
        </div>

        <p v-if="errMsg" class="text-xs text-red-600">{{ errMsg }}</p>
        <div class="flex gap-2"><Button variant="solid" :loading="saving" @click="save">保存</Button><Button variant="subtle" @click="cancelEdit">取消</Button></div>
      </div>

      <p v-if="errMsg && !editing" class="mb-3 text-xs text-red-600">{{ errMsg }}</p>
      <div v-if="rows.loading" class="py-4 text-sm text-gray-500">加载中…</div>
      <div v-else class="overflow-x-auto rounded border border-gray-200">
        <table class="w-full min-w-[1700px] text-sm">
          <thead class="sticky top-0 bg-gray-50 text-gray-500">
            <tr>
              <th class="px-3 py-2 text-left">编号</th>
              <th class="px-3 py-2 text-left">项目名称</th>
              <th class="px-3 py-2 text-left">项目负责人</th>
              <th class="px-3 py-2 text-left">立项时间</th>
              <th class="px-3 py-2 text-left">结项时间</th>
              <th class="px-3 py-2 text-left">研发阶段</th>
              <th class="px-3 py-2 text-left">状态</th>
              <th class="px-3 py-2 text-left">立项报告</th>
              <th class="px-3 py-2 text-left">结项报告</th>
              <th class="px-3 py-2 text-left">资本化确认书</th>
              <th class="px-3 py-2 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows.data || []" :key="row.name" class="border-t hover:bg-gray-50">
              <td class="whitespace-nowrap px-3 py-2 font-medium">{{ row.rd_project_code || row.name }}</td>
              <td class="min-w-[220px] px-3 py-2">{{ row.project_name }}</td>
              <td class="min-w-[220px] px-3 py-2">{{ ownerLabel(row.project_owner, row.project_owner_name) }}</td>
              <td class="whitespace-nowrap px-3 py-2">{{ row.start_date || row.capitalization_start_date || '-' }}</td>
              <td class="whitespace-nowrap px-3 py-2">{{ row.end_date || row.capitalization_end_date || '-' }}</td>
              <td class="whitespace-nowrap px-3 py-2">{{ row.rd_stage_label || row.rd_stage || '未判定' }}</td>
              <td class="whitespace-nowrap px-3 py-2"><Badge :theme="statusTheme(row.status)">{{ row.status_label || row.status }}</Badge></td>
              <td v-for="field in ['project_initiation_report', 'project_completion_report', 'capitalization_confirmation_file']" :key="field" class="max-w-[180px] px-3 py-2"><a v-if="row[field]" :href="reportDownloadUrl(row, field)" target="_blank" rel="noopener" class="block truncate text-xs text-blue-600 hover:underline" :title="fileName(row[field])">查看文件</a><span v-else class="text-gray-400">-</span></td>
              <td class="whitespace-nowrap px-3 py-2 text-right"><button @click="edit(row)" class="mr-3 text-xs text-blue-600 hover:underline">编辑</button><button v-if="canAdministerProjects() && row.status !== 'Cancelled'" @click="cancelProject(row.name)" class="text-xs text-red-600 hover:underline">取消</button></td>
            </tr>
            <tr v-if="!(rows.data || []).length"><td colspan="11" class="py-6 text-center text-gray-400">暂无项目</td></tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>
