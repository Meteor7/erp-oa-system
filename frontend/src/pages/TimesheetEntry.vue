<script setup>
import { computed, ref, watch } from "vue";
import { Button, Spinner, createResource } from "frappe-ui";
import { period } from "../lib/period";
import { canEditTimesheetEntry } from "../lib/access";
import { importTimesheetWorkbookFile, parseTimesheetPaste } from "../lib/timesheetImport";
import { exportTableWorkbook } from "../lib/tableExport";

const options = createResource({
  url: "rayher_hr_payroll.api.monthly_timesheet_entry.get_monthly_options",
  method: "GET",
  auto: true,
});
const monthly = createResource({
  url: "rayher_hr_payroll.api.monthly_timesheet_entry.list_monthly_entries",
  method: "GET",
  makeParams: () => ({ period: period.value, employee: selectedEmployee.value }),
});
const saver = createResource({ url: "rayher_hr_payroll.api.monthly_timesheet_entry.save_monthly_entries" });

const canEdit = computed(() => canEditTimesheetEntry());
const selectedEmployee = ref("");
const selectedYear = ref(Number(String(period.value).slice(0, 4)) || new Date().getFullYear());
const selectedMonth = ref(Number(String(period.value).slice(5, 7)) || new Date().getMonth() + 1);
const entries = ref([]);
const loadedRevision = ref("");
const saving = ref(false);
const exporting = ref(false);
const errMsg = ref("");
const okMsg = ref("");
const batchPasteText = ref("");
const batchErrors = ref([]);
const batchWorkbookInput = ref(null);

const employees = computed(() => options.data?.employees || []);
const projects = computed(() => options.data?.projects || []);
const dayLimit = computed(() => Number(monthly.data?.day_limit || new Date(selectedYear.value, selectedMonth.value, 0).getDate() || 31));
const hourLimit = computed(() => Number(monthly.data?.hour_limit ?? dayLimit.value * 8));
const calendarSource = computed(() => String(monthly.data?.calendar_source || "weekday_fallback"));
const usesWeekdayFallback = computed(() => calendarSource.value === "weekday_fallback");
const isAllEmployees = computed(() => !selectedEmployee.value);
const hasLegacySources = computed(() => Boolean(monthly.data?.has_legacy_sources));
const canEditSelection = computed(() => Boolean(canEdit.value && selectedEmployee.value && !hasLegacySources.value));
const employeeCount = computed(() => Number(monthly.data?.employee_count || 0));
const totalDays = computed(() => Math.round(entries.value.reduce((sum, row) => sum + validDays(row.occurrence_days), 0) * 100) / 100);
const totalHours = computed(() => Math.round(entries.value.reduce((sum, row) => sum + Number(row.hours ?? calculatedRowHours(row)), 0) * 100) / 100);
const months = Array.from({ length: 12 }, (_, index) => index + 1);

function emptyRow() {
  return {
    key: `new-${Date.now()}-${Math.random()}`,
    monthly_entry_id: "",
    project: "",
    project_code: "",
    project_name: "",
    occurrence_days: "",
    hours: 0,
    remark: "",
  };
}

function validDays(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

function calculatedRowHours(row) {
  const occurrenceDays = validDays(row.occurrence_days);
  return Math.round(occurrenceDays * 8 * 100) / 100;
}

function formatNumber(value) {
  return Number(value || 0).toFixed(2);
}

function filteredProjects() {
  return projects.value;
}

function projectCode(project) {
  return project?.rd_project_code || project?.project_code || project?.name || "";
}

function projectName(project) {
  return project?.project_name || project?.name || "";
}

function chooseProject(row, projectId) {
  const project = projects.value.find((item) => item.name === projectId);
  row.project = project?.name || "";
  row.project_code = projectCode(project);
  row.project_name = projectName(project);
}

function recalculateRow(row) {
  row.hours = calculatedRowHours(row);
}

function hydrateEntries() {
  loadedRevision.value = String(monthly.data?.revision || "");
  entries.value = (monthly.data?.entries || []).map((row) => ({
    ...row,
    key: row.monthly_entry_id,
    occurrence_days: formatNumber(row.occurrence_days),
    hours: Number(row.hours || 0),
  }));
}

async function loadEntries() {
  errMsg.value = "";
  okMsg.value = "";
  try {
    await monthly.reload();
    hydrateEntries();
  } catch (error) {
    errMsg.value = serverMessage(error, "月度工时加载失败");
  }
}

function addRow() {
  if (!canEditSelection.value) return;
  entries.value.push(emptyRow());
}

function removeRow(_row, index) {
  if (!canEditSelection.value) return;
  errMsg.value = "";
  entries.value.splice(index, 1);
  okMsg.value = "该行已移出表格，点击保存后生效";
}

function validateRows() {
  if (!selectedEmployee.value) return "请选择研发人员";
  if (hasLegacySources.value) return "历史按日记录不能在月度视图中直接修改";
  const seenProjects = new Set();
  let sum = 0;
  for (let index = 0; index < entries.value.length; index += 1) {
    const row = entries.value[index];
    if (!row.project || !row.project_code || !row.project_name) return `第 ${index + 1} 行请选择项目`;
    if (seenProjects.has(row.project)) return `第 ${index + 1} 行项目重复`;
    seenProjects.add(row.project);
    const text = String(row.occurrence_days ?? "").trim();
    if (!/^\d+(?:\.\d{1,2})?$/.test(text)) return `第 ${index + 1} 行发生天数最多保留两位小数`;
    const days = Number(text);
    if (!Number.isFinite(days) || days <= 0) return `第 ${index + 1} 行发生天数必须大于 0`;
    sum = Math.round((sum + days) * 100) / 100;
  }
  if (sum > dayLimit.value) return `当月累计发生天数不能超过 ${formatNumber(dayLimit.value)} 天`;
  return "";
}

async function saveRows() {
  if (!canEditSelection.value) return;
  errMsg.value = validateRows();
  okMsg.value = "";
  if (errMsg.value) return;
  saving.value = true;
  try {
    const rows = entries.value.map((row) => ({
      monthly_entry_id: row.monthly_entry_id || "",
      project: row.project,
      project_code: row.project_code,
      project_name: row.project_name,
      occurrence_days: Number(row.occurrence_days).toFixed(2),
      remark: String(row.remark || "").trim(),
    }));
    await saver.submit({
      period: period.value,
      employee: selectedEmployee.value,
      rows: JSON.stringify(rows),
      expected_revision: loadedRevision.value,
    });
    await loadEntries();
    okMsg.value = "月度工时保存成功";
  } catch (error) {
    errMsg.value = serverMessage(error, "保存失败");
  } finally {
    saving.value = false;
  }
}

function timesheetImportOptions() {
  return { employees: employees.value, projects: projects.value, period: period.value, existingRows: entries.value };
}

function applyImport(result) {
  batchErrors.value = result.errors || [];
  if (batchErrors.value.length) return;
  const imported = result.rows || [];
  if (imported.some((row) => row.employee !== selectedEmployee.value)) {
    batchErrors.value = ["导入文件中的研发人员必须与当前选择一致"];
    return;
  }
  entries.value.push(...imported.map((row) => ({ ...row, key: `import-${Date.now()}-${Math.random()}` })));
  batchPasteText.value = "";
  okMsg.value = `已导入 ${imported.length} 行，请确认后保存`;
}

function previewBatchPaste() {
  applyImport(parseTimesheetPaste(batchPasteText.value, timesheetImportOptions()));
}

function chooseTimesheetWorkbook() {
  batchWorkbookInput.value?.click();
}

async function importTimesheetWorkbookRows(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  try {
    applyImport(await importTimesheetWorkbookFile(file, timesheetImportOptions()));
  } catch (error) {
    batchErrors.value = [serverMessage(error, "Excel 导入失败")];
  }
}

async function exportCurrent() {
  exporting.value = true;
  try {
    await exportTableWorkbook({
      filename: `研发工时填报-${period.value}`,
      sheetName: "月度研发工时",
      rows: entries.value.map((row) => ({
        ...row,
        employee_name: row.employee_name || employees.value.find((item) => item.name === selectedEmployee.value)?.employee_name || selectedEmployee.value,
      })),
      columns: [
        { label: "研发人员", key: "employee_name", width: 18 },
        { label: "项目代码", key: "project_code", width: 14 },
        { label: "项目名称", key: "project_name", width: 28 },
        { label: "发生天数", value: (row) => Number(row.occurrence_days || 0), width: 12 },
        { label: "工时(h)", value: (row) => Number(row.hours ?? calculatedRowHours(row)), width: 12 },
        { label: "备注", key: "remark", width: 36 },
      ],
    });
  } finally {
    exporting.value = false;
  }
}

function parseFrappeServerMessages(raw) {
  if (!raw) return [];
  try {
    const items = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (!Array.isArray(items)) return [];
    return items.map((message) => {
      try {
        const parsed = typeof message === "string" ? JSON.parse(message) : message;
        return parsed.message || parsed.title || message;
      } catch {
        return message;
      }
    }).filter(Boolean);
  } catch {
    return [];
  }
}

function serverMessage(error, fallback) {
  const messages = [...(error?.messages || []), ...parseFrappeServerMessages(error?._server_messages)]
    .map((value) => String(value || "").replace(/<[^>]*>/g, "").trim()).filter(Boolean);
  return messages.join("；") || String(error?._error_message || error?.message || fallback).replace(/<[^>]*>/g, "").trim();
}

watch([selectedYear, selectedMonth], ([year, month]) => {
  const next = `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}`;
  if (period.value !== next) period.value = next;
});
watch(period, (value) => {
  const [year, month] = String(value || "").split("-").map(Number);
  if (year) selectedYear.value = year;
  if (month) selectedMonth.value = month;
});
watch(() => options.data?.employees, (items) => {
  if (items?.length === 1 && !selectedEmployee.value) {
    selectedEmployee.value = items[0].name;
    return;
  }
  if (selectedEmployee.value && !items?.some((item) => item.name === selectedEmployee.value)) {
    selectedEmployee.value = "";
  }
}, { immediate: true });
watch([period, selectedEmployee], loadEntries, { immediate: true });
watch(() => monthly.data, hydrateEntries);
</script>

<template>
  <section class="rounded-lg border border-gray-200 bg-white shadow-sm">
    <div class="flex flex-col gap-4 border-b border-gray-200 px-5 py-5 xl:flex-row xl:items-center xl:justify-between">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="mr-2 text-xl font-semibold text-gray-900">工时录入（按月）</h2>
        <label class="flex items-center gap-2 text-sm text-gray-600">
          <span>研发人员</span>
          <select v-model="selectedEmployee" class="min-w-[210px] rounded border border-gray-300 bg-white px-3 py-2 text-sm">
            <option value="">全部员工</option>
            <option v-for="employee in employees" :key="employee.name" :value="employee.name">{{ employee.employee_name }} - {{ employee.name }}</option>
          </select>
        </label>
        <label class="flex items-center gap-2 text-sm text-gray-600">
          <span>年份</span>
          <input v-model.number="selectedYear" type="number" min="2000" max="2100" class="w-28 rounded border border-gray-300 px-3 py-2 text-sm" />
        </label>
        <label class="flex items-center gap-2 text-sm text-gray-600">
          <span>月份</span>
          <select v-model.number="selectedMonth" class="w-24 rounded border border-gray-300 bg-white px-3 py-2 text-sm">
            <option v-for="item in months" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <span v-if="isAllEmployees" class="text-sm text-gray-500">员工：<strong class="font-medium text-gray-800">{{ employeeCount }} 人</strong></span>
        <span class="text-sm text-gray-500">当前已填：<strong class="font-medium text-gray-800">{{ formatNumber(totalDays) }} 天 / {{ formatNumber(totalHours) }} 小时</strong></span>
        <span class="rounded-md bg-amber-50 px-3 py-1.5 text-sm text-amber-800">本月上限：<strong class="font-semibold">{{ formatNumber(dayLimit) }} 天 / {{ formatNumber(hourLimit) }} 小时</strong></span>
        <Button v-if="canEditSelection" variant="subtle" @click="addRow">+ 新增一行</Button>
        <Button v-if="canEditSelection" variant="solid" :loading="saving" @click="saveRows">保存</Button>
        <Button variant="subtle" :loading="exporting" :disabled="!entries.length" @click="exportCurrent">导出Excel</Button>
      </div>
    </div>

    <p v-if="usesWeekdayFallback" class="mx-5 mt-4 text-xs text-amber-700">未配置假日表，当前按周一至周五计算</p>
    <p v-if="errMsg" class="mx-5 mt-4 text-sm text-red-600">{{ errMsg }}</p>
    <p v-if="okMsg" class="mx-5 mt-4 text-sm text-green-700">{{ okMsg }}</p>

    <div v-if="monthly.loading" class="flex justify-center py-12"><Spinner class="h-6 w-6" /></div>
    <div v-else class="overflow-x-auto px-5 py-4">
      <table class="w-full min-w-[1080px] border-separate border-spacing-0 text-sm">
        <thead class="bg-gray-50 text-gray-500">
          <tr>
            <th v-if="isAllEmployees" class="border-y border-l border-gray-200 px-4 py-3 text-left font-medium">研发人员</th>
            <th class="border-y border-l border-gray-200 px-4 py-3 text-left font-medium">项目</th>
            <th class="border-y border-l border-gray-200 px-4 py-3 text-left font-medium">发生天数</th>
            <th class="border-y border-l border-gray-200 px-4 py-3 text-left font-medium">工时</th>
            <th class="border-y border-l border-gray-200 px-4 py-3 text-left font-medium">备注</th>
            <th class="border border-gray-200 px-4 py-3 text-left font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in entries" :key="row.key || row.monthly_entry_id || index">
            <td v-if="isAllEmployees" class="border-b border-l border-gray-200 px-4 py-3 whitespace-nowrap">
              <div class="font-medium text-gray-800">{{ row.employee_name || row.employee }}</div>
              <div class="text-xs text-gray-400">{{ row.employee }}</div>
            </td>
            <td class="border-b border-l border-gray-200 px-4 py-2">
              <div v-if="!canEditSelection" class="px-2 py-2 text-gray-700">{{ row.project_name || row.project }}<span v-if="row.project_code" class="ml-2 text-xs text-gray-400">({{ row.project_code }})</span></div>
              <select v-else v-model="row.project" class="w-full rounded border border-gray-300 bg-white px-3 py-2" @change="chooseProject(row, row.project)">
                <option value="">请选择项目</option>
                <option v-for="project in filteredProjects(row)" :key="project.name" :value="project.name">{{ projectName(project) }} ({{ projectCode(project) }})</option>
              </select>
              <p v-if="!projects.length" class="mt-1 text-xs text-amber-700">无匹配项目，请先在项目管理中新增</p>
            </td>
            <td class="border-b border-l border-gray-200 px-4 py-2">
              <span v-if="!canEditSelection" class="block w-32 px-3 py-2 text-right tabular-nums">{{ formatNumber(row.occurrence_days) }}</span>
              <input v-else v-model="row.occurrence_days" type="number" min="0.01" :max="dayLimit" step="0.01" class="w-32 rounded border border-gray-300 px-3 py-2 text-right tabular-nums" @input="recalculateRow(row)" />
            </td>
            <td class="border-b border-l border-gray-200 px-4 py-2">
              <input :value="formatNumber(calculatedRowHours(row))" readonly class="w-32 rounded border border-gray-200 bg-gray-50 px-3 py-2 text-right tabular-nums text-gray-600" />
            </td>
            <td class="border-b border-l border-gray-200 px-4 py-2">
              <span v-if="!canEditSelection" class="block min-w-[220px] px-3 py-2 text-gray-600">{{ row.remark || '-' }}</span>
              <input v-else v-model="row.remark" class="w-full rounded border border-gray-300 px-3 py-2" />
            </td>
            <td class="border-x border-b border-gray-200 px-4 py-2">
              <button v-if="canEditSelection" type="button" class="text-red-600 hover:underline" @click="removeRow(row, index)">删除</button>
              <span v-else class="text-gray-400">只读</span>
            </td>
          </tr>
          <tr v-if="!entries.length">
            <td :colspan="isAllEmployees ? 6 : 5" class="border-x border-b border-gray-200 px-4 py-10 text-center text-gray-400">本月暂无工时记录</td>
          </tr>
        </tbody>
        <tfoot v-if="entries.length" class="bg-gray-50 font-medium text-gray-700">
          <tr>
            <td :colspan="isAllEmployees ? 2 : 1" class="border-x border-b border-gray-200 px-4 py-3 text-right">合计</td>
            <td class="border-b border-gray-200 px-4 py-3 text-right tabular-nums">{{ formatNumber(totalDays) }}</td>
            <td class="border-b border-gray-200 px-4 py-3 text-right tabular-nums">{{ formatNumber(totalHours) }}</td>
            <td colspan="2" class="border-x border-b border-gray-200"></td>
          </tr>
        </tfoot>
      </table>
    </div>

    <div v-if="canEditSelection" class="border-t border-gray-200 px-5 py-4">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <span class="text-sm font-medium text-gray-700">批量粘贴 / Excel 导入</span>
        <Button variant="subtle" @click="chooseTimesheetWorkbook">导入Excel</Button>
        <input ref="batchWorkbookInput" type="file" accept=".xlsx,.xls" class="hidden" @change="importTimesheetWorkbookRows" />
      </div>
      <textarea v-model="batchPasteText" rows="3" class="w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="研发人员　项目代码　项目名称　发生天数　备注"></textarea>
      <Button class="mt-2" variant="subtle" :disabled="!batchPasteText.trim()" @click="previewBatchPaste">预览并加入表格</Button>
      <div v-if="batchErrors.length" class="mt-2 space-y-1 text-xs text-red-600"><p v-for="message in batchErrors" :key="message">{{ message }}</p></div>
    </div>
  </section>
</template>
