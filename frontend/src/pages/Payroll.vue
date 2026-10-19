<script setup>
// 薪酬计算：计算前检查 → 计算链（应付 − 社保公积金 − 个税 − 宿舍及已发放 = 实发）→ 三张小图 → 员工工资表 → 本月对账。
// 点一行在右侧抽屉里按五步看和改。算法（决定 2026-10-14）：基本工资按实际工时 ÷ 当月总工时折算，社保公积金没有账单就按档案基数算，
// 个税按累计预扣法自动算（可以手动改，要写原因）；前端 payrollAmounts.js / payrollTax.js 和后端同一个算法。
import { computed, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { createResource } from "frappe-ui";
import "../styles/expenseUi.css";
import "../styles/payrollUi.css";
import { period, periodRouteSpec } from "../lib/period";
import { PAYROLL_QUERY_KEYS, parsePayrollQuery, payrollQueryOf } from "../lib/payrollFilters.js";
import { bindRouteFilters } from "../lib/urlFilterState.js";
import { CHIPS, canSave, chipCounts, confirmTargets, currentBatchTotal, dirtyRows, editSnapshot, filterRows, rowState, totalsOf } from "../lib/payrollView.js";
import PayrollCharts from "../components/payroll/PayrollCharts.vue";
import PayrollDrawer from "../components/payroll/PayrollDrawer.vue";
import PayrollRecon from "../components/payroll/PayrollRecon.vue";
import PayrollSummary from "../components/payroll/PayrollSummary.vue";
import PayrollTable from "../components/payroll/PayrollTable.vue";
import PayrollTaxProfiles from "../components/payroll/PayrollTaxProfiles.vue";

// 期间和「只看草稿 / 只看已确认」放在地址里（?period=&status=draft|submitted），要在下面的请求发出前读好，否则会先查一次错误的月份。
const statusFilter = ref("");
bindRouteFilters({ route: useRoute(), router: useRouter(), specs: [periodRouteSpec(), {
  keys: PAYROLL_QUERY_KEYS,
  read: parsePayrollQuery,
  snapshot: () => ({ status: statusFilter.value }),
  apply: (state) => { statusFilter.value = state.status; },
  toQuery: payrollQueryOf,
  sources: [statusFilter],
}] });
const router = useRouter();
const api = "rayher_hr_payroll.api.hr_payroll_entry.";
const rows = createResource({ url: api + "get_payroll_rows", method: "GET", makeParams: () => ({ period: period.value }), auto: true });
const social = createResource({ url: "rayher_hr_payroll.api.social_insurance_import_entry.get_social_workbench", method: "GET", makeParams: () => ({ period: period.value, company: "all" }), auto: true });
const fund = createResource({ url: "rayher_hr_payroll.api.housing_fund_import_entry.get_fund_workbench", method: "GET", makeParams: () => ({ period: period.value, company: "all" }), auto: true });
const saver = createResource({ url: api + "save_payroll_draft" });
const adjuster = createResource({ url: api + "apply_salary_adjustment" });
// 确认本月工资 / 撤回确认（决定 2026-10-13）；总经理、副总经理能打开但只读（can_edit = false）。
const confirmer = createResource({ url: api + "confirm_payroll" });
const withdrawer = createResource({ url: api + "withdraw_payroll_confirmation" });
const access = createResource({ url: api + "get_payroll_access", method: "GET", auto: true });
const canEdit = computed(() => Boolean(access.data?.can_edit));

const company = ref("all");
const companyOptions = [{ value: "all", label: "全部公司" }, { value: "QIHENG Demo", label: "栖衡科技" }, { value: "示例研发中心", label: "栖衡研发" }];
const chip = ref(statusFilter.value || "all");
const query = ref("");
const wide = ref(false);
const chartsOpen = ref(readFlag("payroll.charts", true));
const openEmployee = ref("");
const saving = reactive({}); const applying = reactive({}); const messages = reactive({}); const errors = reactive({});
const bulk = reactive({ confirming: false, running: false, done: 0, total: 0, failed: [] });
const lock = reactive({ asking: false, running: false, done: null, skipped: [], error: "" });
const n = (value) => Number(value || 0);

function readFlag(key, fallback) { try { const value = localStorage.getItem(key); return value == null ? fallback : value === "1"; } catch { return fallback; } }
function writeFlag(key, value) { try { localStorage.setItem(key, value ? "1" : "0"); } catch { /* 存不了就不记 */ } }
function toggleCharts() { chartsOpen.value = !chartsOpen.value; writeFlag("payroll.charts", chartsOpen.value); }
// 草稿、已确认两个页签写进地址（看板链接用 ?status=submitted 进来只看已确认的）。
const URL_CHIPS = ["draft", "submitted"];
function setChip(key) { chip.value = key; statusFilter.value = URL_CHIPS.includes(key) ? key : ""; }
watch(statusFilter, (value) => { if (URL_CHIPS.includes(value)) chip.value = value; else if (URL_CHIPS.includes(chip.value)) chip.value = "all"; });
watch(period, () => { rows.reload(); social.reload(); fund.reload(); openEmployee.value = ""; });

const all = computed(() => rows.data || []);
const scoped = computed(() => filterRows(all.value, { company: company.value }));
const shown = computed(() => filterRows(all.value, { chip: chip.value, query: query.value, company: company.value }));
const counts = computed(() => chipCounts(scoped.value));
const total = computed(() => totalsOf(scoped.value));
// 只看已确认时，计算链和图表也只算已确认的人：和看板「人力成本 · 工资（只算已确认）」对得上。
const summaryRows = computed(() => (chip.value === "submitted" ? scoped.value.filter((row) => rowState(row).key === "submitted") : scoped.value));
// 改了还没保存：行加载时记下可改的输入，和现在比；有人没保存就不让确认本月工资（确认锁定的是已保存的草稿）。
const baseline = ref({});
watch(() => rows.data, (data) => { baseline.value = editSnapshot(data); }, { immediate: true });
const dirty = computed(() => dirtyRows(scoped.value, baseline.value));
const dirtyEmployees = computed(() => new Set(dirty.value.map((row) => row.employee)));
const openRow = computed(() => all.value.find((row) => row.employee === openEmployee.value) || null);
const bulkTargets = computed(() => scoped.value.filter((row) => rowState(row).key === "new" && canSave(row)));
const lockTargets = computed(() => confirmTargets(scoped.value));
const emptyText = computed(() => (chip.value === "draft" ? "本期没有草稿工资条" : chip.value === "submitted" ? "本期没有已确认的工资条" : "本期没有符合任职期间的员工"));
const go = (path) => router.push(path);
// 保存草稿要传的数：实际工时只有手动改过才传；个税只有手动改过才用传的数（要写原因），否则后端按累计预扣法算。
const draftParams = (row) => ({
  employee: row.employee, period: period.value, base_salary: n(row.base_salary), salary_adjustment: n(row.salary_adjustment),
  company_subsidy: n(row.company_subsidy), bonus: n(row.bonus), other_adjustment: n(row.other_adjustment), advanced_paid: n(row.advanced_paid),
  hours_manual: row.hours_manual ? 1 : 0, actual_hours: row.hours_manual ? n(row.actual_hours) : undefined,
  tax_manual: row.tax_manual ? 1 : 0, income_tax: row.tax_manual ? n(row.income_tax) : 0, tax_manual_reason: row.tax_manual ? String(row.tax_manual_reason || "") : "",
  bonus_separate: row.bonus_separate ? 1 : 0,
});
// 个税资料按个税年度（工资次月发：12 月工资算进下一年）
const taxYear = computed(() => { const [y, m] = String(period.value || "").split("-").map(Number); return m === 12 ? y + 1 : y; });
const taxOpen = ref(readFlag("payroll.tax", false));
function toggleTax() { taxOpen.value = !taxOpen.value; writeFlag("payroll.tax", taxOpen.value); }

async function saveRow(row) {
  saving[row.employee] = true; errors[row.employee] = ""; messages[row.employee] = "";
  try {
    await saver.submit(draftParams(row));
    messages[row.employee] = "草稿已保存"; await rows.reload();
  } catch (e) { errors[row.employee] = e?.message || "保存失败"; } finally { saving[row.employee] = false; }
}
async function applyAdjustment(row) {
  applying[row.employee] = true; errors[row.employee] = ""; messages[row.employee] = "";
  try {
    await adjuster.submit({ employee: row.employee, period: period.value, adjusted_base: n(row.base_salary) + n(row.salary_adjustment) });
    messages[row.employee] = "调薪已应用至后续月份"; await rows.reload();
  } catch (e) { errors[row.employee] = e?.message || "应用调薪失败"; } finally { applying[row.employee] = false; }
}
// 批量生成草稿：逐人用页面上现有的数字保存（个税按累计预扣法自动算），先确认一次。
async function generateAll() {
  const targets = bulkTargets.value.map((row) => ({ ...row }));
  Object.assign(bulk, { confirming: false, running: true, done: 0, total: targets.length, failed: [] });
  for (const row of targets) {
    try {
      await saver.submit(draftParams(row));
    } catch (e) { bulk.failed.push(`${row.employee_name}：${e?.message || "保存失败"}`); }
    bulk.done += 1;
  }
  bulk.running = false;
  await rows.reload();
}
// 确认本月工资：当前公司范围里本页生成的草稿一次确认；确认不了的（比如分摊已定版）列出原因。
async function confirmAll() {
  if (dirty.value.length) { lock.asking = false; return; }
  const employees = lockTargets.value.map((row) => row.employee);
  Object.assign(lock, { asking: false, running: true, done: null, skipped: [], error: "" });
  try {
    const result = await confirmer.submit({ period: period.value, employees: JSON.stringify(employees) });
    lock.done = result?.confirmed || 0; lock.skipped = result?.skipped || [];
  } catch (e) { lock.error = e?.message || "确认失败"; } finally { lock.running = false; }
  await rows.reload();
}
async function withdrawRow(row, reason) {
  saving[row.employee] = true; errors[row.employee] = ""; messages[row.employee] = "";
  try {
    await withdrawer.submit({ employee: row.employee, period: period.value, reason });
    messages[row.employee] = "已撤回确认，现在是草稿，可以修改"; await rows.reload();
  } catch (e) { errors[row.employee] = e?.message || "撤回失败"; } finally { saving[row.employee] = false; }
}
</script>

<template>
  <div class="xp pr">
    <div class="ph">
      <div>
        <div class="muted">人事中心</div>
        <h3>薪酬计算</h3>
        <div class="muted">按员工核对本月工资：基本工资 → 应付工资 → 扣社保公积金 → 个税 → 实发工资，关联社保、公积金和宿舍代扣，生成真实草稿工资单</div>
      </div>
      <div class="pr-ctl">
        <label>期间 <input v-model="period" type="month" aria-label="期间"></label>
        <label>所属公司 <select v-model="company" aria-label="所属公司"><option v-for="option in companyOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      </div>
    </div>

    <div v-if="rows.error" class="banner err" role="alert">薪酬明细加载失败：{{ rows.error.message || rows.error }}</div>
    <div v-if="rows.loading && !all.length" class="empty">正在加载薪酬明细...</div>
    <template v-else>
      <PayrollSummary :rows="summaryRows" @go="go" />

      <div class="pr-tools" style="margin-top:-4px">
        <span class="pr-note">图表按当前公司统计<template v-if="chip === 'submitted'">，只算已确认的工资条</template></span>
        <button type="button" class="btn sm" :aria-expanded="chartsOpen" @click="toggleCharts">{{ chartsOpen ? "收起图表 ▴" : "展开图表 ▾" }}</button>
      </div>
      <PayrollCharts v-if="chartsOpen" :rows="summaryRows" />

      <section class="panel" aria-label="员工工资">
        <div class="pr-tools">
          <span class="pr-seg" role="group" aria-label="筛选">
            <button v-for="item in CHIPS" :key="item.key" type="button" :aria-pressed="chip === item.key" :data-payroll-draft-only="item.key === 'draft' ? '' : undefined" :title="item.key === 'draft' ? '只看草稿工资条' : undefined" @click="setChip(item.key)">{{ item.label }} {{ counts[item.key] }}</button>
          </span>
          <span class="pr-ctl">
            <input v-model="query" class="pr-in" placeholder="按姓名查找" aria-label="按姓名查找">
            <label><input v-model="wide" type="checkbox"> 显示全部列（和 Excel 一致）</label>
            <template v-if="canEdit">
              <button type="button" class="btn" :disabled="!bulkTargets.length || bulk.running" @click="bulk.confirming = true">批量生成草稿（{{ bulkTargets.length }}）</button>
              <span v-if="dirty.length" class="pill p-sun" data-payroll-dirty>有 {{ dirty.length }} 人改了还没保存</span>
              <button type="button" class="btn pri" data-payroll-confirm :disabled="!lockTargets.length || lock.running || dirty.length > 0" :title="dirty.length ? '先保存或撤销改动，再确认' : undefined" @click="lock.asking = true">确认本月工资（{{ lockTargets.length }}）</button>
            </template>
            <span v-else-if="access.data" class="pill p-gray">只读</span>
          </span>
        </div>
        <div v-if="lock.asking && !dirty.length" class="lock" role="alertdialog" aria-label="确认本月工资">
          <span class="k">确认 {{ lockTargets.length }} 人的工资条</span><span class="muted">确认后锁定，不能再改，要改先撤回确认；看板和研发人工成本只算已确认的。确认前按现在的工时、社保公积金重算一遍，个税按累计预扣法重算（手动改过的保留）。</span>
          <span style="margin-left:auto;display:flex;gap:8px"><button type="button" class="btn sm" @click="lock.asking = false">取消</button><button type="button" class="btn pri sm" @click="confirmAll">确认</button></span>
        </div>
        <div v-if="lock.running" class="lock" role="status"><span class="k">正在确认…</span></div>
        <div v-if="lock.done != null && !lock.running" class="banner" role="status">已确认 {{ lock.done }} 人<template v-if="lock.skipped.length">；{{ lock.skipped.length }} 人没有确认：{{ lock.skipped.slice(0, 3).map((item) => `${item.employee_name}（${item.reason}）`).join("；") }}<template v-if="lock.skipped.length > 3"> 等</template></template></div>
        <div v-if="lock.error" class="banner err" role="alert">确认失败：{{ lock.error }}</div>
        <div v-if="bulk.confirming" class="lock" role="alertdialog" aria-label="确认批量生成">
          <span class="k">将为 {{ bulkTargets.length }} 人生成草稿工资条</span><span class="muted">用页面上现有的数字保存；个税按累计预扣法自动算，社保公积金没有账单的按档案基数算。</span>
          <span style="margin-left:auto;display:flex;gap:8px"><button type="button" class="btn sm" @click="bulk.confirming = false">取消</button><button type="button" class="btn pri sm" @click="generateAll">确认生成</button></span>
        </div>
        <div v-if="bulk.running" class="lock" role="status"><span class="k">正在生成 {{ bulk.done }} / {{ bulk.total }}</span><span class="bar wide"><i :style="{ width: (bulk.done / Math.max(bulk.total, 1) * 100) + '%' }"></i></span></div>
        <div v-if="bulk.failed.length" class="banner err" role="alert">有 {{ bulk.failed.length }} 人没有生成：{{ bulk.failed.slice(0, 3).join("；") }}<template v-if="bulk.failed.length > 3"> 等</template></div>
        <PayrollTable :rows="shown" :wide="wide" :empty-text="emptyText" @open="(row) => (openEmployee = row.employee)" />
        <div class="pr-note">点一行，在右侧按五步查看和修改这个人的工资；已确认的工资条不能改，要改先撤回确认。社保或公积金算不出来（档案没有基数、公司当年政策没配置）的员工不能保存工资草稿；已确认金额以工资单为准，未留存的社保分项显示为 —。</div>
      </section>

      <div class="pr-tools">
        <span class="pr-note">个税按累计预扣法算，要用每个人的专项附加扣除和系统上线前的期初累计</span>
        <button type="button" class="btn sm" :aria-expanded="taxOpen" @click="toggleTax">{{ taxOpen ? "收起个税资料 ▴" : `${taxYear} 年个税资料 ▾` }}</button>
      </div>
      <PayrollTaxProfiles v-if="taxOpen" :year="taxYear" :read-only="!canEdit" @saved="rows.reload()" />

      <PayrollRecon :total="total" :social="currentBatchTotal(social.data)" :fund="currentBatchTotal(fund.data)" @go="go" />
    </template>

    <PayrollDrawer
      v-if="openRow" :row="openRow" :saving="Boolean(saving[openRow.employee])" :applying="Boolean(applying[openRow.employee])"
      :message="messages[openRow.employee] || ''" :error="errors[openRow.employee] || ''" :read-only="!canEdit"
      :dirty="dirtyEmployees.has(openRow.employee)"
      @close="openEmployee = ''" @save="saveRow" @adjust="applyAdjustment" @withdraw="withdrawRow" @go="go" />
  </div>
</template>
