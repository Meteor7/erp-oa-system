<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { createResource } from "frappe-ui";
import { useRoute, useRouter } from "vue-router";
import { period, setPeriodScope } from "../lib/period";
import { canEditTimesheetEntry } from "../lib/access";
import { entryQuery, parseEntryQuery } from "../lib/dashboardLanding";
import { exportTableWorkbook } from "../lib/tableExport";
import {
  HOURS_PER_DAY, capText, daysInMonth, lastRemindedText, needsRemind, newRowKey,
  previousPeriod, remindClosed, remindResultText, rosterItemsFromOptions, rosterItemsFromProgress, rowHours, rowsFromPrevious, round2,
  serverMessage, statusMeta, sumDays, trimDays, validateEntryRows,
} from "../lib/timesheetEntryView";
import "../styles/rdTimesheet.css";
import RdPage from "../components/rd/RdPage.vue";
import RdPeriod from "../components/rd/RdPeriod.vue";
import RdSeg from "../components/rd/RdSeg.vue";
import RdIcon from "../components/rd/RdIcon.vue";
import EntryBoard from "../components/timesheet/EntryBoard.vue";
import EntryRoster from "../components/timesheet/EntryRoster.vue";
import EntrySheet from "../components/timesheet/EntrySheet.vue";
import EntryImportDrawer from "../components/timesheet/EntryImportDrawer.vue";

// 月度页：期间选择器固定按月。
setPeriodScope("month");

// 数据看板点进来的筛选放在地址里：?tab=board|sheet&status=none|part|full|over|open&dept=部门&period=YYYY-MM。
// 地址是初始状态的来源；之后用户改了页签、筛选、月份，地址用 replace 跟着变（刷新还在，也不占历史记录）。
const route = useRoute();
const router = useRouter();
const ownPath = route.path;
const landing = parseEntryQuery(route.query);
if (landing.period) period.value = landing.period;

const options = createResource({
  url: "rayher_hr_payroll.api.monthly_timesheet_entry.get_monthly_options",
  method: "GET",
  // 员工列表按月份给：离职员工在离职当月及以前的月份仍可补登。
  makeParams: () => ({ period: period.value }),
  auto: true,
});
const monthly = createResource({
  url: "rayher_hr_payroll.api.monthly_timesheet_entry.list_monthly_entries",
  method: "GET",
  makeParams: () => ({ period: period.value, employee: selectedEmployee.value }),
});
// 上月同一个人的记录：「复制上月」用，也决定添加项目时谁排在前面。
const previous = createResource({
  url: "rayher_hr_payroll.api.monthly_timesheet_entry.list_monthly_entries",
  method: "GET",
  makeParams: () => ({ period: previousPeriod(period.value), employee: selectedEmployee.value }),
});
// 全部可见员工的明细（不带 employee），只用于看板上的「导出明细」。
const allMonthly = createResource({
  url: "rayher_hr_payroll.api.monthly_timesheet_entry.list_monthly_entries",
  method: "GET",
  makeParams: () => ({ period: period.value }),
});
const progress = createResource({
  url: "rayher_hr_payroll.api.monthly_timesheet_entry.get_fill_progress",
  method: "GET",
  makeParams: () => ({ period: period.value }),
  auto: true,
});
const saver = createResource({ url: "rayher_hr_payroll.api.monthly_timesheet_entry.save_monthly_entries" });
const reminder = createResource({ url: "rayher_hr_payroll.api.monthly_timesheet_entry.remind_timesheet_fill" });

const canEdit = computed(() => canEditTimesheetEntry());
const selectedEmployee = ref("");
const tabChoice = ref(landing.tab);
const boardStatus = ref(landing.status);
const boardDept = ref(landing.dept);
const entries = ref([]);
const loadedRevision = ref("");
const dirty = ref(false);
const saving = ref(false);
const exporting = ref(false);
const errMsg = ref("");
const okMsg = ref("");
const importOpen = ref(false);
const previousEntries = ref([]);
const previousKey = ref("");
let okTimer = null;
let loadSeq = 0;
let previousSeq = 0;

const employees = computed(() => options.data?.employees || []);
const editableEmployees = computed(() => options.data?.editable_employees || []);
const projects = computed(() => options.data?.projects || []);
const progressData = computed(() => progress.data || null);
// 催办：有权限，并且该月还没过截止日（过了截止日月度工时已锁定 / 进入分摊，催了也没人能补）。
const remindIsClosed = computed(() => remindClosed(progressData.value?.deadline));
const canRemind = computed(() => Boolean(progressData.value?.can_remind) && !remindIsClosed.value);
const progressKind = computed(() => progressData.value?.kind || "");
const rosterItems = computed(() => (
  progressKind.value && progressKind.value !== "self" && progressData.value?.employees?.length
    ? rosterItemsFromProgress(progressData.value.employees)
    : rosterItemsFromOptions(employees.value)
));
// 只能看到自己时：不显示名单和看板，直接是个人工作表。
const showRoster = computed(() => rosterItems.value.length > 1);
const showBoard = computed(() => (progressKind.value ? progressKind.value !== "self" : employees.value.length > 1));
const activeTab = computed(() => {
  if (!showBoard.value) return "sheet";
  return tabChoice.value || "board";
});
const tabOptions = computed(() => [
  { value: "board", label: "填报进度" },
  { value: "sheet", label: "个人填报" },
]);

const selectedPerson = computed(() => {
  const id = selectedEmployee.value;
  const item = rosterItems.value.find((entry) => entry.employee === id);
  const option = employees.value.find((entry) => entry.name === id);
  return { employee: id, name: item?.name || option?.employee_name || id, department: item?.department || "" };
});
const selectedStatus = computed(() => rosterItems.value.find((entry) => entry.employee === selectedEmployee.value)?.status || "");
const monthNumber = computed(() => Number(String(period.value).slice(5, 7)) || new Date().getMonth() + 1);
const dayLimit = computed(() => Number(monthly.data?.day_limit ?? daysInMonth(period.value)));
const hourLimit = computed(() => Number(monthly.data?.hour_limit ?? dayLimit.value * HOURS_PER_DAY));
const calendarSource = computed(() => String(monthly.data?.calendar_source || "weekday_fallback"));
const usesWeekdayFallback = computed(() => calendarSource.value === "weekday_fallback");
const hasLegacySources = computed(() => Boolean(monthly.data?.has_legacy_sources));
const canEditSelection = computed(() => Boolean(
  canEdit.value
  && editableEmployees.value.includes(selectedEmployee.value)
  && !hasLegacySources.value
));
const readOnlyNote = computed(() => {
  if (canEditSelection.value || hasLegacySources.value || !selectedEmployee.value) return "";
  return `只读：当前账号只能查看 ${selectedPerson.value.name} 的工时，不能修改。`;
});
const totalDays = computed(() => sumDays(entries.value));
const overLimit = computed(() => totalDays.value > dayLimit.value + 1e-6);
const capLine = computed(() => capText({
  month: monthNumber.value,
  dayLimit: dayLimit.value,
  hourLimit: hourLimit.value,
  baseHourLimit: monthly.data?.base_hour_limit,
  leaveHours: monthly.data?.leave_hours,
  joinedOn: monthly.data?.joined_on,
  relievedOn: monthly.data?.relieved_on,
}));
const recentIds = computed(() => previousEntries.value.map((row) => row.project).filter(Boolean));
const importOptions = computed(() => ({
  employees: employees.value,
  projects: projects.value,
  period: period.value,
  existingRows: entries.value,
}));
const saveDisabled = computed(() => saving.value || overLimit.value || !dirty.value);

function notify(message) {
  okMsg.value = message;
  clearTimeout(okTimer);
  okTimer = setTimeout(() => { okMsg.value = ""; }, 6000);
}

function hydrateEntries() {
  loadedRevision.value = String(monthly.data?.revision || "");
  entries.value = (monthly.data?.entries || []).map((row) => ({
    ...row,
    key: row.monthly_entry_id,
    employee: row.employee || selectedEmployee.value,
    occurrence_days: trimDays(row.occurrence_days),
    hours: Number(row.hours || 0),
    remark: row.remark || "",
  }));
  dirty.value = false;
}

async function loadEntries() {
  errMsg.value = "";
  okMsg.value = "";
  const seq = (loadSeq += 1);
  if (!selectedEmployee.value) {
    entries.value = [];
    loadedRevision.value = "";
    dirty.value = false;
    return;
  }
  try {
    await monthly.reload();
    if (seq !== loadSeq) return;
    hydrateEntries();
  } catch (error) {
    if (seq === loadSeq) errMsg.value = serverMessage(error, "月度工时加载失败");
  }
  loadPrevious();
}

async function loadPrevious() {
  const key = `${previousPeriod(period.value)}|${selectedEmployee.value}`;
  if (!selectedEmployee.value || previousKey.value === key) return;
  const seq = (previousSeq += 1);
  previousEntries.value = [];
  try {
    await previous.reload();
    if (seq !== previousSeq) return;
    previousEntries.value = previous.data?.entries || [];
    previousKey.value = key;
  } catch {
    // 上月数据只是辅助，加载失败不打扰填报。
  }
}

async function refreshProgress() {
  try {
    await progress.reload();
  } catch {
    // 看板自己会显示错误
  }
}

function confirmDiscard() {
  return !dirty.value || window.confirm("当前有未保存的修改，切换后会丢失，继续吗？");
}

function selectEmployee(id) {
  if (!id || id === selectedEmployee.value) return true;
  if (!confirmDiscard()) return false;
  selectedEmployee.value = id;
  return true;
}

function openEmployee(id) {
  if (selectEmployee(id)) tabChoice.value = "sheet";
}

function setTab(value) {
  tabChoice.value = value;
  if (value === "sheet" && !selectedEmployee.value) {
    selectedEmployee.value = editableEmployees.value[0] || employees.value[0]?.name || "";
  }
}

function onRowsChange(rows) {
  if (!canEditSelection.value) return;
  entries.value = rows;
  dirty.value = true;
  errMsg.value = "";
}

function removeRow(index) {
  if (!canEditSelection.value) return;
  errMsg.value = "";
  entries.value.splice(index, 1);
  dirty.value = true;
  notify("该行已移出表格，点击保存后生效");
}

async function copyPrevious() {
  if (!canEditSelection.value) return;
  errMsg.value = "";
  const key = `${previousPeriod(period.value)}|${selectedEmployee.value}`;
  if (previousKey.value !== key) await loadPrevious();
  const { rows, skipped } = rowsFromPrevious(previousEntries.value, { employee: selectedEmployee.value, projects: projects.value });
  if (!rows.length) {
    errMsg.value = "上月没有可复制的项目记录";
    return;
  }
  entries.value = rows;
  dirty.value = true;
  notify(`已复制上月 ${rows.length} 个项目的天数，请确认后保存${skipped ? `（${skipped} 个项目已不可选，已跳过）` : ""}`);
}

async function saveRows() {
  if (!canEditSelection.value) return;
  errMsg.value = validateEntryRows(entries.value, {
    employee: selectedEmployee.value,
    hasLegacy: hasLegacySources.value,
    dayLimit: dayLimit.value,
  });
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
    notify("月度工时保存成功");
    refreshProgress();
  } catch (error) {
    errMsg.value = serverMessage(error, "保存失败");
  } finally {
    saving.value = false;
  }
}

function applyImport(rows) {
  const stamp = newRowKey("import");
  entries.value.push(...rows.map((row, index) => ({
    ...row,
    key: `${stamp}-${index}`,
    monthly_entry_id: "",
    occurrence_days: trimDays(row.occurrence_days),
    hours: round2(Number(row.occurrence_days) * HOURS_PER_DAY),
  })));
  dirty.value = true;
  notify(`已导入 ${rows.length} 行，请确认后保存`);
}

async function remind(ids) {
  const list = (Array.isArray(ids) ? ids : [ids]).filter(Boolean);
  if (!list.length || !canRemind.value) return;
  if (list.length > 1 && !window.confirm(`确认向 ${list.length} 人发送工时填报催办？`)) return;
  errMsg.value = "";
  try {
    const result = await reminder.submit({ period: period.value, employees: JSON.stringify(list) });
    notify(remindResultText(result));
  } catch (error) {
    errMsg.value = serverMessage(error, "催办失败");
  }
  refreshProgress();
}

async function exportCurrent() {
  exporting.value = true;
  try {
    await exportTableWorkbook({
      filename: `研发工时填报-${period.value}`,
      sheetName: "月度研发工时",
      rows: entries.value.map((row) => ({
        ...row,
        employee_name: row.employee_name || selectedPerson.value.name,
      })),
      columns: [
        { label: "研发人员", key: "employee_name", width: 18 },
        { label: "项目代码", key: "project_code", width: 14 },
        { label: "项目名称", key: "project_name", width: 28 },
        { label: "发生天数", value: (row) => Number(row.occurrence_days || 0), width: 12 },
        { label: "工时(h)", value: (row) => rowHours(row), width: 12 },
        { label: "备注", key: "remark", width: 36 },
      ],
    });
  } finally {
    exporting.value = false;
  }
}

// 看板：所有可见员工的月度明细（原来「全部员工」视图的内容）
async function exportAllEmployees() {
  exporting.value = true;
  errMsg.value = "";
  try {
    await allMonthly.reload();
    await exportTableWorkbook({
      filename: `研发工时明细-${period.value}`,
      sheetName: "月度研发工时",
      rows: allMonthly.data?.entries || [],
      columns: [
        { label: "研发人员", key: "employee_name", width: 18 },
        { label: "工号", key: "employee", width: 14 },
        { label: "项目代码", key: "project_code", width: 14 },
        { label: "项目名称", key: "project_name", width: 28 },
        { label: "发生天数", value: (row) => Number(row.occurrence_days || 0), width: 12 },
        { label: "工时(h)", value: (row) => Number(row.hours ?? rowHours(row)), width: 12 },
        { label: "备注", key: "remark", width: 36 },
      ],
    });
  } catch (error) {
    errMsg.value = serverMessage(error, "导出失败");
  } finally {
    exporting.value = false;
  }
}

async function exportFollowUp(list) {
  await exportTableWorkbook({
    filename: `工时未填满名单-${period.value}`,
    sheetName: "需要跟进",
    rows: list,
    columns: [
      { label: "姓名", key: "employee_name", width: 14 },
      { label: "工号", key: "employee", width: 14 },
      { label: "部门", key: "department", width: 18 },
      { label: "已填天数", value: (row) => Number(row.used_days || 0), width: 12 },
      { label: "上限天数", value: (row) => Number(row.limit_days || 0), width: 12 },
      { label: "状态", value: (row) => statusMeta(row.status).label, width: 10 },
      { label: "上次催办", value: (row) => lastRemindedText(row.last_reminded) || "", width: 16 },
    ],
  });
}

watch(() => options.data?.employees, (items) => {
  if (!selectedEmployee.value && items?.length) {
    const editable = options.data?.editable_employees || [];
    selectedEmployee.value = items.length === 1 ? items[0].name : (editable[0] || items[0].name);
    return;
  }
  if (selectedEmployee.value && items && !items.some((item) => item.name === selectedEmployee.value)) {
    selectedEmployee.value = "";
  }
}, { immediate: true });
watch(period, () => {
  options.reload();
  refreshProgress();
});
// 状态 → 地址（没变就不写，避免和下面「地址 → 状态」来回触发）。
// 离开本页时 route 已经是别的页面了：两个监听都只在还停留在本页时才动地址。
watch([tabChoice, boardStatus, boardDept, period], () => {
  if (route.path !== ownPath) return;
  const next = entryQuery({ tab: tabChoice.value, status: boardStatus.value, dept: boardDept.value, period: period.value }, route.query);
  if (JSON.stringify(next) !== JSON.stringify(route.query)) router.replace({ path: route.path, query: next });
});
// 地址 → 状态：在本页再点一次侧栏（地址被清空）或粘贴了新的链接时，筛选跟着地址走。
watch(() => route.query, (query) => {
  if (route.path !== ownPath) return;
  const wanted = parseEntryQuery(query);
  tabChoice.value = wanted.tab;
  boardStatus.value = wanted.status;
  boardDept.value = wanted.dept;
  if (wanted.period) period.value = wanted.period;
});
watch([period, selectedEmployee], loadEntries, { immediate: true });
onBeforeUnmount(() => clearTimeout(okTimer));
</script>

<template>
  <RdPage title="研发工时填报" subtitle="按月登记每位研发人员在各项目上发生的天数，1 天 = 8 小时。">
    <template #ctl><RdPeriod /></template>

    <div class="bar">
      <RdSeg v-if="showBoard" :model-value="activeTab" :options="tabOptions" label="填报视图" @update:model-value="setTab" />
      <span v-else></span>
      <div class="row">
        <button v-if="activeTab === 'sheet'" type="button" class="btn" :disabled="exporting || !entries.length" @click="exportCurrent"><RdIcon name="download" />导出 Excel</button>
        <button v-else type="button" class="btn" :disabled="exporting" @click="exportAllEmployees"><RdIcon name="download" />导出明细 Excel</button>
      </div>
    </div>

    <div v-if="errMsg" class="note bad"><RdIcon name="alert" /><span class="grow">{{ errMsg }}</span></div>
    <div v-if="okMsg" class="note ok"><RdIcon name="check" /><span class="grow">{{ okMsg }}</span></div>

    <EntryBoard
      v-if="activeTab === 'board'"
      :progress="progressData"
      :loading="progress.loading"
      :error="progress.error ? serverMessage(progress.error, '填报进度加载失败') : ''"
      :reminding="reminder.loading"
      v-model:dept="boardDept"
      v-model:status="boardStatus"
      @open="openEmployee"
      @remind="remind"
      @export-list="exportFollowUp"
      @retry="refreshProgress"
    />

    <div v-else class="split ts-split" :class="{ solo: !showRoster }">
      <EntryRoster v-if="showRoster" :items="rosterItems" :selected="selectedEmployee" :kind="progressKind === 'all' ? 'all' : 'team'" @select="selectEmployee" />
      <EntrySheet
        :rows="entries"
        :person="selectedPerson"
        :day-limit="dayLimit"
        :hour-limit="hourLimit"
        :cap-line="capLine"
        :editable="canEditSelection"
        :read-only-note="readOnlyNote"
        :legacy="hasLegacySources"
        :weekday-fallback="usesWeekdayFallback"
        :projects="projects"
        :recent-ids="recentIds"
        :loading="monthly.loading"
        :can-remind="canRemind && needsRemind(selectedStatus)"
        :reminding="reminder.loading"
        :dirty="dirty"
        :saving="saving"
        :save-disabled="saveDisabled"
        @change="onRowsChange"
        @remove="removeRow"
        @copy="copyPrevious"
        @import="importOpen = true"
        @remind="remind"
        @save="saveRows"
      />
    </div>

    <EntryImportDrawer :open="importOpen" :import-options="importOptions" :employee="selectedEmployee" @close="importOpen = false" @add="applyImport" />
  </RdPage>
</template>
