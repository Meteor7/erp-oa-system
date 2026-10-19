<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { createResource } from "frappe-ui";
import { canAdministerProjects } from "../lib/access";
import { exportTableWorkbook } from "../lib/tableExport";
import { PROJECT_FILE_FIELDS, attachmentPills, hasMissingAttachment, pendingProjectItems, pendingSummary, projectCode, projectStage, projectStats, stageTone, statusTone } from "../lib/rdProjects";
import RdPage from "../components/rd/RdPage.vue";
import RdKpi from "../components/rd/RdKpi.vue";
import RdIcon from "../components/rd/RdIcon.vue";

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "Open", label: "进行中" },
  { value: "Completed", label: "已结束" },
  { value: "Cancelled", label: "已取消" },
];
const ATTACHMENT_OPTIONS = [
  { value: "", label: "附件：全部" },
  { value: "missing", label: "附件：有缺失" },
];
const STAGE_OPTIONS = [
  { value: "资本化", label: "资本化" },
  { value: "费用化", label: "费用化" },
  { value: "未判定", label: "未判定" },
];
const FILE_ACCEPT = ".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png";

const filters = reactive({ search: "", status: "", attachment: "" });
const rows = createResource({
  url: "rayher_hr_payroll.api.project_entry.list_projects",
  method: "GET",
  makeParams: () => ({ search: filters.search, status: filters.status }),
  auto: true,
});
// 指标卡和待处理提示按全部项目算，不随搜索、状态筛选变化
const allRows = createResource({
  url: "rayher_hr_payroll.api.project_entry.list_projects",
  method: "GET",
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
const askCancelName = ref("");
// 点「缺…报告」药丸：打开编辑抽屉，定位到对应附件并短暂高亮
const highlightField = ref("");
let highlightTimer = null;

const loaded = computed(() => Array.isArray(allRows.data));
const stats = computed(() => projectStats(allRows.data || []));
const pending = computed(() => pendingProjectItems(allRows.data || []));
const pendingText = computed(() => pendingSummary(pending.value, 3));
// 表格里实际显示的行：搜索、状态由服务端筛，「附件：有缺失」在这里按药丸规则筛
const visibleRows = computed(() => {
  const list = rows.data || [];
  return filters.attachment === "missing" ? list.filter(hasMissingAttachment) : list;
});
const pillRows = computed(() => visibleRows.value.map((row) => ({ row, pills: attachmentPills(row) })));

function reloadAll() {
  rows.reload();
  allRows.reload();
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

// 补传只走抽屉里的完整保存（save_project 会清空没带上的字段，不能单独传一个附件）
async function editAttachment(row, fieldKey) {
  edit(row);
  await nextTick();
  const holder = document.querySelector(`[data-file-field="${fieldKey}"]`);
  if (!holder) return;
  holder.scrollIntoView({ block: "center" });
  holder.querySelector("[data-file-pick]")?.focus({ preventScroll: true });
  highlightField.value = fieldKey;
  clearTimeout(highlightTimer);
  highlightTimer = setTimeout(() => { highlightField.value = ""; }, 2200);
}

function pickFile(event) {
  event.currentTarget.querySelector("input[type=file]")?.click();
}

function cancelEdit() {
  editing.value = false;
  highlightField.value = "";
}

function onKeydown(event) {
  if (event.key === "Escape" && editing.value && !uploadingField.value && !saving.value) cancelEdit();
}
onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKeydown);
  clearTimeout(highlightTimer);
});

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

function pillTitle(pill) {
  if (pill.state === "up") return pill.label + "：" + fileName(pill.file);
  if (pill.state === "miss") return pill.label + "：需要，还没上传。点击打开编辑，补传后保存";
  return pill.label + "：这个项目不需要";
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
    reloadAll();
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
    askCancelName.value = "";
    reloadAll();
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
      rows: visibleRows.value,
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
  <RdPage title="项目管理" subtitle="研发项目主数据：阶段、周期、附件。工时、费用、审批都引用这里。">
    <div class="kpis">
      <RdKpi label="项目总数" :value="loaded ? stats.total : '-'" sub="含已结束、已取消" />
      <RdKpi label="进行中" :value="loaded ? stats.open : '-'" :sub="loaded ? `其中资本化 ${stats.capitalized} 个，费用化 ${stats.expensed} 个` : ''" />
      <RdKpi
        label="待处理事项"
        :value="loaded ? pending.length : '-'"
        :sub="!loaded ? '' : pending.length ? '缺附件、阶段未判定' : '附件齐全、阶段都已判定'"
        :tone="pending.length ? 'warn' : ''"
        :class="{ 'kpi-clear': loaded && !pending.length }"
      />
    </div>

    <div v-if="pending.length" class="note warn">
      <RdIcon name="alert" />
      <span class="grow"><b>待处理 {{ pendingText.count }} 项</b>　{{ pendingText.text }}<template v-if="pendingText.more">…</template></span>
    </div>
    <div v-if="errMsg && !editing" class="note bad"><RdIcon name="alert" /><span class="grow">{{ errMsg }}</span></div>

    <div class="bar">
      <div class="row">
        <label class="input" style="width: 230px"><RdIcon name="search" /><input v-model="filters.search" placeholder="搜索名称/编号" @input="rows.reload" /></label>
        <select v-model="filters.status" class="field" style="width: 130px" aria-label="状态筛选" @change="rows.reload">
          <option v-for="item in STATUS_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <select v-model="filters.attachment" class="field" style="width: 140px" aria-label="附件筛选">
          <option v-for="item in ATTACHMENT_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </div>
      <div class="row">
        <button type="button" class="btn" :disabled="exporting || !visibleRows.length" @click="exportCurrentProjects"><RdIcon name="download" />{{ exporting ? "导出中…" : "导出 Excel" }}</button>
        <button v-if="canAdministerProjects()" type="button" class="btn pri" @click="newProject"><RdIcon name="plus" />新增项目</button>
      </div>
    </div>

    <div class="card">
      <div v-if="rows.loading" class="bd muted">加载中…</div>
      <div v-else class="tbl">
        <table class="min-w-[1180px]">
          <thead>
            <tr>
              <th>编号</th>
              <th>项目名称</th>
              <th>项目负责人</th>
              <th>立项时间</th>
              <th>结项时间</th>
              <th>研发阶段</th>
              <th>状态</th>
              <th>附件</th>
              <th class="r">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="{ row, pills } in pillRows" :key="row.name">
              <td class="num nw"><b>{{ projectCode(row) }}</b></td>
              <td>{{ row.project_name }}</td>
              <td>{{ ownerLabel(row.project_owner, row.project_owner_name) }}</td>
              <td class="num nw">{{ row.start_date || row.capitalization_start_date || '-' }}</td>
              <td class="num nw">{{ row.end_date || row.capitalization_end_date || '-' }}</td>
              <td><span class="tag" :class="stageTone(projectStage(row))">{{ projectStage(row) }}</span></td>
              <td class="nw"><span class="tag" :class="statusTone(row.status)">{{ row.status_label || row.status }}</span></td>
              <td class="nw">
                <div class="pills">
                  <template v-for="pill in pills" :key="pill.key">
                    <a v-if="pill.state === 'up'" class="pill up" :href="reportDownloadUrl(row, pill.key)" target="_blank" rel="noopener" :title="pillTitle(pill)"><RdIcon name="check" />{{ pill.text }}</a>
                    <button v-else-if="pill.state === 'miss'" type="button" class="pill miss" :title="pillTitle(pill)" :aria-label="pill.text + '，点击打开编辑补传'" @click="editAttachment(row, pill.key)"><RdIcon name="alert" />{{ pill.text }}</button>
                    <span v-else class="pill na" :title="pillTitle(pill)">{{ pill.text }}<span class="sr">（不需要）</span></span>
                  </template>
                </div>
              </td>
              <td class="r nw">
                <template v-if="askCancelName === row.name">
                  <span class="muted">取消后不再出现在费用导入的项目下拉里</span>
                  <button type="button" class="btn sm bad" @click="cancelProject(row.name)">确认取消</button>
                  <button type="button" class="btn sm quiet" @click="askCancelName = ''">返回</button>
                </template>
                <template v-else>
                  <button type="button" class="btn sm quiet" @click="edit(row)">编辑</button>
                  <template v-if="canAdministerProjects() && row.status !== 'Cancelled'">
                    <button type="button" class="btn sm quiet bad" @click="askCancelName = row.name">取消</button>
                  </template>
                </template>
              </td>
            </tr>
            <tr v-if="!visibleRows.length"><td colspan="9" class="muted" style="text-align: center; padding: 32px">{{ filters.attachment === "missing" ? "没有缺附件的项目" : "暂无项目" }}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="att-legend">
        <span class="pill up"><RdIcon name="check" />已上传</span><span>点开可下载，悬停看文件名</span>
        <span class="pill miss"><RdIcon name="alert" />缺附件</span><span>需要但还没传，点击打开编辑补传</span>
        <span class="pill na">不需要</span><span>立项报告：进行中、已结束都要 · 结项报告：已结束才要 · 资本化确认书：资本化项目才要 · 已取消的演示员工177要</span>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="editing" class="rd">
        <div class="rd-drawer-bg" @click="cancelEdit"></div>
        <aside class="rd-drawer" role="dialog" aria-modal="true" :aria-label="form.name ? '编辑项目' : '新增项目'">
          <header>
            {{ form.name ? "编辑项目" : "新增项目" }}
            <button type="button" class="btn quiet sm" aria-label="关闭" @click="cancelEdit"><RdIcon name="x" /></button>
          </header>
          <div class="body">
            <div class="two">
              <div class="f"><label>编号 <b>*</b></label><input v-model="form.project_code" class="field" /></div>
              <div class="f"><label>状态</label>
                <select v-model="form.status" class="field">
                  <option value="Open">进行中</option>
                  <option value="Completed">已结束</option>
                  <option v-if="canAdministerProjects() || form.status === 'Cancelled'" value="Cancelled">已取消</option>
                </select>
              </div>
            </div>
            <div class="f"><label>项目名称 <b>*</b></label><input v-model="form.project_name" class="field" /></div>
            <div class="two">
              <div class="f"><label>项目负责人</label>
                <select v-if="canAdministerProjects()" v-model="form.project_owner" class="field" @change="syncOwnerName">
                  <option value="">未指定</option>
                  <option v-for="owner in owners.data || []" :key="owner.name" :value="owner.name">{{ owner.full_name || owner.name }} · {{ owner.name }}</option>
                </select>
                <input v-else class="field" readonly :value="ownerLabel(form.project_owner, form.project_owner_name)" />
              </div>
              <div class="f"><label>研发阶段</label>
                <select v-model="form.rd_stage" class="field"><option v-for="item in STAGE_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option></select>
              </div>
            </div>
            <div class="two">
              <div class="f"><label>立项时间</label><input v-model="form.start_date" type="date" class="field" /></div>
              <div class="f"><label>结项时间</label><input v-model="form.end_date" type="date" class="field" /></div>
            </div>
            <div class="f">
              <label>附件（pdf、office、图片）</label>
              <div v-for="fileField in PROJECT_FILE_FIELDS" :key="fileField.key" class="file" :class="{ has: form[fileField.key], hl: highlightField === fileField.key }" :data-file-field="fileField.key">
                <span style="min-width: 0">{{ fileField.label }}　<a v-if="form[fileField.key]" :href="reportDownloadUrl(form, fileField.key)" target="_blank" rel="noopener" :title="fileName(form[fileField.key])" style="display: inline-block; max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; color: #1F7A4D">{{ fileName(form[fileField.key]) }}</a><span v-else style="color: #65788B">未上传</span></span>
                <span class="row" style="gap: 6px; flex-wrap: nowrap">
                  <label class="btn sm" style="cursor: pointer" tabindex="0" data-file-pick @keydown.enter.prevent="pickFile" @keydown.space.prevent="pickFile">
                    {{ uploadingField === fileField.key ? "上传中…" : form[fileField.key] ? "重新上传" : "上传" }}
                    <input type="file" class="hidden" :accept="FILE_ACCEPT" :disabled="Boolean(uploadingField)" @change="uploadProjectFile(fileField.key, $event)" />
                  </label>
                  <button v-if="form[fileField.key]" type="button" class="btn sm quiet" @click="form[fileField.key] = ''">清除</button>
                </span>
              </div>
            </div>
            <div v-if="errMsg" class="note bad" style="margin: 0"><RdIcon name="alert" /><span class="grow">{{ errMsg }}</span></div>
          </div>
          <footer>
            <button type="button" class="btn" @click="cancelEdit">取消</button>
            <button type="button" class="btn pri" :disabled="saving" @click="save">{{ saving ? "保存中…" : "保存" }}</button>
          </footer>
        </aside>
      </div>
    </Teleport>
  </RdPage>
</template>

<style scoped>
/* 待处理事项为 0：数字和说明用绿色 */
.rd .kpi-clear :deep(.v) { color: var(--rd-ok); }
.rd .kpi-clear :deep(.s) { color: var(--rd-ok); }
.rd .kpi-clear :deep(.s)::before { content: "✓ "; font-weight: 700; }

/* 附件列：固定三枚药丸，已上传 / 缺 / 不需要 */
.rd .pills { display: flex; gap: 6px; }
.rd .pill { display: inline-flex; align-items: center; gap: 4px; height: 24px; padding: 0 9px; border-radius: 6px; font-size: 12px; border: 1px solid transparent; white-space: nowrap; text-decoration: none; }
.rd .pill svg.ic { width: 13px; height: 13px; stroke-width: 2; }
.rd .pill.up { background: var(--rd-ok-soft); color: var(--rd-ok); }
.rd a.pill.up:hover { border-color: var(--rd-ok); }
.rd .pill.miss { background: var(--rd-warn-soft); color: var(--rd-warn); border-color: #9FCFC4; font-weight: 600; }
.rd button.pill.miss { cursor: pointer; font-family: inherit; }
.rd button.pill.miss:hover { border-color: var(--rd-warn); }
.rd button.pill.miss:focus-visible, .rd .file label.btn:focus-visible { outline: 2px solid var(--rd-brand); outline-offset: 2px; }
/* 从缺附件药丸进来时，对应的附件行短暂高亮 */
.rd .file.hl { border-color: var(--rd-warn); box-shadow: 0 0 0 3px var(--rd-warn-soft); animation: file-hl 2.2s ease-out forwards; }
@keyframes file-hl { 0%, 60% { box-shadow: 0 0 0 3px #9FCFC4; } 100% { box-shadow: 0 0 0 3px transparent; } }
@media (prefers-reduced-motion: reduce) { .rd .file.hl { animation: none; } }
.rd .pill.na { background: transparent; color: var(--rd-ink3); border: 1px dashed var(--rd-line2); }
.rd .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.rd .att-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; padding: 12px 18px; border-top: 1px solid var(--rd-line); font-size: 12px; color: var(--rd-ink3); }
</style>
