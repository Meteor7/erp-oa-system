<script setup>
import { ref, reactive, computed, watch } from "vue";
import { Card, Button, createResource } from "frappe-ui";
import { period } from "../lib/period";
import { canEditTimesheetEntry } from "../lib/access";

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
const summaryEmployee = ref("");
const selectedSummaryEmployee = computed(() => summaryEmployee.value);
const summary = createResource({
  url: "rayher_hr_payroll.api.timesheet_entry.get_rd_hour_summary",
  method: "GET",
  makeParams: () => ({ period: period.value, employee: selectedSummaryEmployee.value }),
  auto: true,
});

function firstDayOfPeriod(value = period.value) {
  return value ? `${value}-01` : "";
}

function lastDayOfPeriod(value = period.value) {
  const [year, month] = String(value || "").split("-").map(Number);
  if (!year || !month) return "";
  const day = new Date(year, month, 0).getDate();
  return `${value}-${String(day).padStart(2, "0")}`;
}

const form = reactive({
  work_date: firstDayOfPeriod(),
  employee: "",
  project: "",
  project_code: "",
  project_name: "",
  activity_type: "",
  hours: "",
  description: "",
});
const saving = ref(false);
const errMsg = ref("");
const canEdit = computed(() => canEditTimesheetEntry());
const activeProjectPicker = ref("");

const saver = createResource({ url: "rayher_hr_payroll.api.timesheet_entry.save_rd_hours" });
const remover = createResource({ url: "rayher_hr_payroll.api.timesheet_entry.delete_rd_hours" });

const activityTypes = computed(() => options.data?.activity_types || []);
const projects = computed(() => options.data?.projects || []);
const employees = computed(() => options.data?.employees || []);
const canPickSummaryEmployee = computed(() => employees.value.length > 1);
const dateMin = computed(() => firstDayOfPeriod());
const dateMax = computed(() => lastDayOfPeriod());

function projectSearchText(project) {
  return [projectCode(project), projectName(project), projectKey(project)].join(" ").toLowerCase();
}

function filteredProjects(value) {
  const query = String(value || "").trim().toLowerCase();
  if (!query) return projects.value;
  return projects.value.filter((project) => projectSearchText(project).includes(query));
}

const filteredCodeProjects = computed(() => filteredProjects(form.project_code));
const filteredNameProjects = computed(() => filteredProjects(form.project_name));

function projectCode(project) {
  return project?.rd_project_code || project?.name || "";
}

function projectName(project) {
  return project?.project_name || project?.name || "";
}

function projectKey(projectOrCode, nameValue = "") {
  if (typeof projectOrCode === "object" && projectOrCode) {
    const code = projectCode(projectOrCode);
    const name = projectName(projectOrCode);
    return projectOrCode.rd_project_key || (code && name ? `${code} | ${name}` : code || name);
  }
  const code = String(projectOrCode || "").trim();
  const name = String(nameValue || "").trim();
  return code && name ? `${code} | ${name}` : code || name;
}

function findProjectByCode(value) {
  const code = String(value || "").trim();
  if (!code) return null;
  return projects.value.find((project) => projectCode(project) === code) || null;
}

function findProjectByName(value) {
  const name = String(value || "").trim();
  if (!name) return null;
  return projects.value.find((project) => projectName(project) === name) || null;
}

function findProjectByIdentity(codeValue, nameValue) {
  const code = String(codeValue || "").trim();
  const name = String(nameValue || "").trim();
  if (!code || !name) return null;
  return projects.value.find((project) => projectCode(project) === code && projectName(project) === name) || null;
}

const projectByCode = computed(() => findProjectByCode(form.project_code));
const projectByName = computed(() => findProjectByName(form.project_name));
const projectByIdentity = computed(() => findProjectByIdentity(form.project_code, form.project_name));
let syncingProject = false;

function fillProject(project) {
  if (!project) return;
  syncingProject = true;
  form.project_code = projectCode(project);
  form.project_name = projectName(project);
  form.project = project.name;
  syncingProject = false;
}

function syncMatchedProject() {
  const project = projectByIdentity.value;
  form.project = project?.name || "";
}

function openProjectPicker(kind) {
  activeProjectPicker.value = kind;
}

function closeProjectPickerLater() {
  setTimeout(() => {
    activeProjectPicker.value = "";
  }, 120);
}

function toggleProjectPicker(kind) {
  activeProjectPicker.value = activeProjectPicker.value === kind ? "" : kind;
}

function chooseProject(project) {
  fillProject(project);
  activeProjectPicker.value = "";
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

function cleanMessage(value) {
  return String(value || "").replace(/<[^>]*>/g, "").trim();
}

function serverMessage(error, fallback) {
  const messages = [
    ...(error?.messages || []),
    ...parseFrappeServerMessages(error?._server_messages),
  ].map(cleanMessage).filter(Boolean);
  if (messages.length) return messages.join("\uFF1B");
  return cleanMessage(error?._error_message || error?.message) || fallback;
}

watch(activityTypes, (items) => {
  if (!form.activity_type && items.length) {
    const first = items[0];
    form.activity_type = first.name || first;
  }
}, { immediate: true });

watch(employees, (items) => {
  if (!items.length) return;
  const exists = items.some((employee) => employee.name === summaryEmployee.value);
  if (!exists) {
    summaryEmployee.value = form.employee || items[0].name;
  }
}, { immediate: true });

watch(summaryEmployee, () => {
  summary.reload();
});

watch(period, () => {
  if (!form.work_date || !String(form.work_date).startsWith(period.value)) {
    form.work_date = firstDayOfPeriod();
  }
  rows.reload();
  summary.reload();
});


watch(() => form.project_code, () => {
  if (syncingProject) return;
  const project = projectByCode.value;
  if (project) {
    fillProject(project);
    return;
  }
  syncMatchedProject();
});

watch(() => form.project_name, () => {
  if (syncingProject) return;
  const project = projectByName.value;
  if (project) {
    fillProject(project);
    return;
  }
  syncMatchedProject();
});

function projectLabel(project) {
  return projectKey(project);
}


function fmtDate(value) {
  return value ? String(value).slice(0, 10) : "";
}

async function save() {
  if (!canEdit.value) return;
  errMsg.value = "";
  const hours = Number(form.hours);
  if (!form.work_date || !form.employee || !form.project_code.trim() || !form.project_name.trim() || !form.activity_type || !form.description.trim()) {
    errMsg.value = "请填写日期、研发人员、项目代码、项目名称、活动类型、工时和工作内容";
    return;
  }
  if (!Number.isFinite(hours) || hours <= 0 || hours > 8) {
    errMsg.value = "工时必须大于 0，且单日不超过 8 小时";
    return;
  }
  if (form.work_date < dateMin.value || form.work_date > dateMax.value) {
    errMsg.value = "填报日期必须在会计期间内";
    return;
  }
  const matchedProject = projectByIdentity.value;
  if (!matchedProject) {
    errMsg.value = "项目代码和项目名称必须匹配项目管理中的可填报项目";
    return;
  }
  form.project = matchedProject.name;
  saving.value = true;
  try {
    const data = await saver.submit({
      period: period.value,
      employee: form.employee,
      project: matchedProject.name,
      project_code: form.project_code.trim(),
      project_name: form.project_name.trim(),
      hours,
      work_date: form.work_date,
      activity_type: form.activity_type,
      description: form.description.trim(),
    });
    if (saver.error) {
      errMsg.value = serverMessage(saver.error, "保存失败");
      return;
    }
    rows.data = data;
    options.reload();
    summary.reload();
    form.hours = "";
    form.description = "";
  } catch (e) {
    errMsg.value = serverMessage(e, "保存失败");
  } finally {
    saving.value = false;
  }
}

async function del(timesheet) {
  if (!canEdit.value) return;
  errMsg.value = "";
  try {
    await remover.submit({ timesheet });
    rows.reload();
    summary.reload();
  } catch (e) {
    errMsg.value = serverMessage(e, "删除失败");
  }
}

function fmtNumber(value, decimals = 1) {
  return Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function fmtDelta(value) {
  const n = Number(value || 0);
  const prefix = n > 0 ? "+" : "";
  return prefix + fmtNumber(n, 1);
}

const summaryCards = computed(() => {
  const data = summary.data || {};
  return [
    { label: "总填报工时", value: fmtNumber(data.total_hours), unit: "h", tone: "text-blue-600" },
    { label: "填报天数", value: String(data.filled_days || 0), unit: "天", tone: "text-blue-600" },
    { label: "日均工时", value: fmtNumber(data.average_hours), unit: "h", tone: "text-blue-600" },
    { label: "与标准差值", value: fmtDelta(data.standard_delta), unit: "h", tone: Number(data.standard_delta || 0) < 0 ? "text-orange-600" : "text-green-600" },
  ];
});
const periodLabel = computed(() => "会计期间 " + period.value);
const total = computed(() => (rows.data || []).reduce((sum, row) => sum + Number(row.hours || 0), 0));
</script>

<template>
  <div class="space-y-4">
    <section class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-4">
        <div>
          <h2 class="text-lg font-semibold text-gray-900">本期填报概览</h2>
          <p class="text-sm text-gray-500">按当前会计期间汇总，总工时与标准值按 8h/天比较</p>
        </div>
        <div v-if="canPickSummaryEmployee" class="flex items-center gap-2">
          <label class="text-sm text-gray-500">查看员工</label>
          <select v-model="summaryEmployee" class="border border-gray-300 rounded px-3 py-2 text-sm min-w-[180px]">
            <option v-for="employee in employees" :key="employee.name" :value="employee.name">{{ employee.employee_name }}</option>
          </select>
        </div>
      </div>
      <div v-if="summary.loading" class="text-gray-500 text-sm py-4">概览加载中…</div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <div v-for="card in summaryCards" :key="card.label" class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-5">
          <div class="text-xs text-gray-500 mb-2">{{ card.label }}</div>
          <div class="flex items-end gap-1">
            <span class="text-3xl font-semibold tabular-nums" :class="card.tone">{{ card.value }}</span>
            <span class="text-sm text-gray-500 pb-1">{{ card.unit }}</span>
          </div>
        </div>
      </div>
    </section>

    <Card :title="canEdit ? '研发工时填报' : '研发工时查看'" :subtitle="canEdit ? '按日期、项目、活动类型登记研发工时，提交后写入 ERPNext Timesheet' : periodLabel">
      <div class="flex items-center gap-2 mb-4">
        <span class="text-sm text-gray-500">会计期间</span>
        <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
      </div>

      <div v-if="canEdit" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-7 gap-3 p-3 bg-gray-50 rounded-lg">
        <div class="flex flex-col">
          <label class="text-xs text-gray-500 mb-1">日期</label>
          <input v-model="form.work_date" type="date" :min="dateMin" :max="dateMax" class="border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div class="flex flex-col">
          <label class="text-xs text-gray-500 mb-1">研发人员</label>
          <select v-model="form.employee" class="border border-gray-300 rounded px-3 py-2 text-sm min-w-[180px]">
            <option value="">请选择</option>
            <option v-for="employee in options.data?.employees || []" :key="employee.name" :value="employee.name">
              {{ employee.employee_name }}
            </option>
          </select>
        </div>
        <div class="flex flex-col">
          <label class="text-xs text-gray-500 mb-1">项目代码</label>
          <div class="relative">
            <input v-model="form.project_code" class="w-full border border-gray-300 rounded px-3 py-2 pr-8 text-sm" placeholder="选择项目代码" @focus="openProjectPicker('code')" @input="openProjectPicker('code')" @blur="closeProjectPickerLater" />
            <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-900" aria-label="展开项目代码选项" @mousedown.prevent="toggleProjectPicker('code')">&#9662;</button>
            <div v-if="activeProjectPicker === 'code'" class="absolute z-30 mt-1 w-full max-h-56 overflow-auto rounded border border-gray-200 bg-white py-1 shadow-lg">
              <button v-for="project in filteredCodeProjects" :key="project.name" type="button" class="block w-full px-3 py-2 text-left hover:bg-gray-100" @mousedown.prevent="chooseProject(project)">
                <span class="block text-sm text-gray-900">{{ projectCode(project) }}</span>
                <span class="block text-xs text-gray-500">{{ projectName(project) }}</span>
              </button>
              <div v-if="!filteredCodeProjects.length" class="px-3 py-2 text-xs text-gray-500">无匹配项目，请先在项目管理中新增</div>
            </div>
          </div>
        </div>
        <div class="flex flex-col xl:col-span-2">
          <label class="text-xs text-gray-500 mb-1">项目名称</label>
          <div class="relative">
            <input v-model="form.project_name" class="w-full border border-gray-300 rounded px-3 py-2 pr-8 text-sm min-w-[220px]" placeholder="选择项目名称" @focus="openProjectPicker('name')" @input="openProjectPicker('name')" @blur="closeProjectPickerLater" />
            <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-900" aria-label="展开项目名称选项" @mousedown.prevent="toggleProjectPicker('name')">&#9662;</button>
            <div v-if="activeProjectPicker === 'name'" class="absolute z-30 mt-1 w-full max-h-56 overflow-auto rounded border border-gray-200 bg-white py-1 shadow-lg">
              <button v-for="project in filteredNameProjects" :key="project.name" type="button" class="block w-full px-3 py-2 text-left hover:bg-gray-100" @mousedown.prevent="chooseProject(project)">
                <span class="block text-sm text-gray-900">{{ projectName(project) }}</span>
                <span class="block text-xs text-gray-500">{{ projectCode(project) }}</span>
              </button>
              <div v-if="!filteredNameProjects.length" class="px-3 py-2 text-xs text-gray-500">无匹配项目，请先在项目管理中新增</div>
            </div>
          </div>
        </div>
        <div class="flex flex-col">
          <label class="text-xs text-gray-500 mb-1">活动类型</label>
          <select v-model="form.activity_type" class="border border-gray-300 rounded px-3 py-2 text-sm">
            <option value="">请选择</option>
            <option v-for="activity in activityTypes" :key="activity.name || activity" :value="activity.name || activity">
              {{ activity.name || activity }}
            </option>
          </select>
        </div>
        <div class="flex flex-col">
          <label class="text-xs text-gray-500 mb-1">工时(h)</label>
          <input v-model="form.hours" type="number" min="0.5" max="8" step="0.5"
            class="border border-gray-300 rounded px-3 py-2 text-sm" placeholder="8" />
        </div>
        <div class="flex flex-col md:col-span-2 xl:col-span-6">
          <label class="text-xs text-gray-500 mb-1">工作内容</label>
          <textarea v-model="form.description" rows="2"
            class="border border-gray-300 rounded px-3 py-2 text-sm resize-y min-h-[42px]"
            placeholder="完成的研发工作"></textarea>
        </div>
        <div class="flex items-end">
          <Button variant="solid" class="w-full" :loading="saving" @click="save">保存</Button>
        </div>
      </div>
      <p v-if="errMsg" class="text-red-600 text-xs mt-2">{{ errMsg }}</p>
    </Card>

    <Card title="本期工时明细" :subtitle="periodLabel">
      <div v-if="rows.loading" class="text-gray-500 text-sm py-4">加载中…</div>
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm min-w-[1040px]">
          <thead class="text-gray-500 border-b">
            <tr>
              <th class="text-left px-3 py-2">日期</th>
              <th class="text-left px-3 py-2">研发人员</th>
              <th class="text-left px-3 py-2">项目代码</th>
              <th class="text-left px-3 py-2">项目名称</th>
              <th class="text-left px-3 py-2">活动类型</th>
              <th class="text-right px-3 py-2">工时</th>
              <th class="text-left px-3 py-2">工作内容</th>
              <th class="text-right px-3 py-2">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows.data || []" :key="row.timesheet_detail || row.timesheet" class="border-b last:border-0 hover:bg-gray-50">
              <td class="px-3 py-2 whitespace-nowrap">{{ fmtDate(row.work_date) }}</td>
              <td class="px-3 py-2 whitespace-nowrap">{{ row.employee_name }}</td>
              <td class="px-3 py-2 whitespace-nowrap">{{ row.rd_project_code || row.project }}</td>
              <td class="px-3 py-2 min-w-[180px]">{{ row.project_name || row.project }}</td>
              <td class="px-3 py-2 whitespace-nowrap">{{ row.activity_type }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ row.hours }}</td>
              <td class="px-3 py-2 min-w-[240px] text-gray-700">{{ row.description }}</td>
              <td class="text-right px-3 py-2 whitespace-nowrap">
                <button v-if="canEdit && row.rd_spa_managed" @click="del(row.timesheet)" class="text-red-600 hover:underline text-xs">删除</button>
                <span v-else-if="!row.rd_spa_managed" class="text-gray-400 text-xs">手工</span>
                <span v-else class="text-gray-400 text-xs">-</span>
              </td>
            </tr>
            <tr v-if="!(rows.data || []).length">
              <td colspan="8" class="text-center text-gray-400 py-6">{{ canEdit ? "本期暂无工时，请在上方填报" : "本期暂无工时" }}</td>
            </tr>
          </tbody>
          <tfoot v-if="(rows.data || []).length">
            <tr class="border-t font-medium">
              <td class="px-3 py-2" colspan="5">合计</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ total }}</td>
              <td colspan="2"></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  </div>
</template>
