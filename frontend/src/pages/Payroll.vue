<script setup>
// 薪酬计算：计算前检查 → 计算链（应付 − 社保公积金 − 个税 − 宿舍及已发放 = 实发）→ 三张小图 → 员工工资表 → 本月对账。
// 点一行在右侧抽屉里按五步看和改；金额的算法没有变（payrollAmounts.js / 后端 _calculate_amounts）。
import { computed, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { createResource } from "frappe-ui";
import "../styles/expenseUi.css";
import "../styles/payrollUi.css";
import { period, periodRouteSpec } from "../lib/period";
import { PAYROLL_QUERY_KEYS, parsePayrollQuery, payrollQueryOf } from "../lib/payrollFilters.js";
import { bindRouteFilters } from "../lib/urlFilterState.js";
import { CHIPS, canSave, chipCounts, currentBatchTotal, filterRows, rowState, totalsOf } from "../lib/payrollView.js";
import PayrollCharts from "../components/payroll/PayrollCharts.vue";
import PayrollDrawer from "../components/payroll/PayrollDrawer.vue";
import PayrollRecon from "../components/payroll/PayrollRecon.vue";
import PayrollSummary from "../components/payroll/PayrollSummary.vue";
import PayrollTable from "../components/payroll/PayrollTable.vue";

// 期间和「只看草稿」放在地址里（?period=&status=draft），要在下面的请求发出前读好，否则会先查一次错误的月份。
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

const company = ref("all");
const companyOptions = [{ value: "all", label: "全部公司" }, { value: "Rayher", label: "示例总部" }, { value: "示例研发中心", label: "示例研发中心" }];
const chip = ref(statusFilter.value === "draft" ? "draft" : "all");
const query = ref("");
const wide = ref(false);
const chartsOpen = ref(readFlag("payroll.charts", true));
const openEmployee = ref("");
const saving = reactive({}); const applying = reactive({}); const messages = reactive({}); const errors = reactive({});
const bulk = reactive({ confirming: false, running: false, done: 0, total: 0, failed: [] });
const n = (value) => Number(value || 0);

function readFlag(key, fallback) { try { const value = localStorage.getItem(key); return value == null ? fallback : value === "1"; } catch { return fallback; } }
function writeFlag(key, value) { try { localStorage.setItem(key, value ? "1" : "0"); } catch { /* 存不了就不记 */ } }
function toggleCharts() { chartsOpen.value = !chartsOpen.value; writeFlag("payroll.charts", chartsOpen.value); }
function setChip(key) { chip.value = key; statusFilter.value = key === "draft" ? "draft" : ""; }
watch(statusFilter, (value) => { if (value === "draft") chip.value = "draft"; else if (chip.value === "draft") chip.value = "all"; });
watch(period, () => { rows.reload(); social.reload(); fund.reload(); openEmployee.value = ""; });

const all = computed(() => rows.data || []);
const scoped = computed(() => filterRows(all.value, { company: company.value }));
const shown = computed(() => filterRows(all.value, { chip: chip.value, query: query.value, company: company.value }));
const counts = computed(() => chipCounts(scoped.value));
const total = computed(() => totalsOf(scoped.value));
const openRow = computed(() => all.value.find((row) => row.employee === openEmployee.value) || null);
const bulkTargets = computed(() => scoped.value.filter((row) => rowState(row).key === "new" && canSave(row)));
const emptyText = computed(() => (chip.value === "draft" ? "本期没有草稿工资条" : "本期没有符合任职期间的员工"));
const go = (path) => router.push(path);

async function saveRow(row) {
  saving[row.employee] = true; errors[row.employee] = ""; messages[row.employee] = "";
  try {
    await saver.submit({ employee: row.employee, period: period.value, payment_days: n(row.payment_days), base_salary: n(row.base_salary), salary_adjustment: n(row.salary_adjustment), company_subsidy: n(row.company_subsidy), bonus: n(row.bonus), other_adjustment: n(row.other_adjustment), income_tax: n(row.income_tax), advanced_paid: n(row.advanced_paid) });
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
// 批量生成草稿：逐人用页面上现有的数字保存（个税是 0，需要再逐人填），先确认一次。
async function generateAll() {
  const targets = bulkTargets.value.map((row) => ({ ...row }));
  Object.assign(bulk, { confirming: false, running: true, done: 0, total: targets.length, failed: [] });
  for (const row of targets) {
    try {
      await saver.submit({ employee: row.employee, period: period.value, payment_days: n(row.payment_days), base_salary: n(row.base_salary), salary_adjustment: n(row.salary_adjustment), company_subsidy: n(row.company_subsidy), bonus: n(row.bonus), other_adjustment: n(row.other_adjustment), income_tax: n(row.income_tax), advanced_paid: n(row.advanced_paid) });
    } catch (e) { bulk.failed.push(`${row.employee_name}：${e?.message || "保存失败"}`); }
    bulk.done += 1;
  }
  bulk.running = false;
  await rows.reload();
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
      <PayrollSummary :rows="scoped" @go="go" />

      <div class="pr-tools" style="margin-top:-4px">
        <span class="pr-note">图表按当前公司统计</span>
        <button type="button" class="btn sm" :aria-expanded="chartsOpen" @click="toggleCharts">{{ chartsOpen ? "收起图表 ▴" : "展开图表 ▾" }}</button>
      </div>
      <PayrollCharts v-if="chartsOpen" :rows="scoped" />

      <section class="panel" aria-label="员工工资">
        <div class="pr-tools">
          <span class="pr-seg" role="group" aria-label="筛选">
            <button v-for="item in CHIPS" :key="item.key" type="button" :aria-pressed="chip === item.key" :data-payroll-draft-only="item.key === 'draft' ? '' : undefined" @click="setChip(item.key)">{{ item.key === "draft" ? "只看草稿工资条" : item.label }} {{ counts[item.key] }}</button>
          </span>
          <span class="pr-ctl">
            <input v-model="query" class="pr-in" placeholder="按姓名查找" aria-label="按姓名查找">
            <label><input v-model="wide" type="checkbox"> 显示全部列（和 Excel 一致）</label>
            <button type="button" class="btn pri" :disabled="!bulkTargets.length || bulk.running" @click="bulk.confirming = true">批量生成草稿（{{ bulkTargets.length }}）</button>
          </span>
        </div>
        <div v-if="bulk.confirming" class="lock" role="alertdialog" aria-label="确认批量生成">
          <span class="k">将为 {{ bulkTargets.length }} 人生成草稿工资条</span><span class="muted">用页面上现有的数字保存；个税目前是 0，生成后需要逐人填写。</span>
          <span style="margin-left:auto;display:flex;gap:8px"><button type="button" class="btn sm" @click="bulk.confirming = false">取消</button><button type="button" class="btn pri sm" @click="generateAll">确认生成</button></span>
        </div>
        <div v-if="bulk.running" class="lock" role="status"><span class="k">正在生成 {{ bulk.done }} / {{ bulk.total }}</span><span class="bar wide"><i :style="{ width: (bulk.done / Math.max(bulk.total, 1) * 100) + '%' }"></i></span></div>
        <div v-if="bulk.failed.length" class="banner err" role="alert">有 {{ bulk.failed.length }} 人没有生成：{{ bulk.failed.slice(0, 3).join("；") }}<template v-if="bulk.failed.length > 3"> 等</template></div>
        <PayrollTable :rows="shown" :wide="wide" :empty-text="emptyText" @open="(row) => (openEmployee = row.employee)" />
        <div class="pr-note">点一行，在右侧按五步查看和修改这个人的工资；已提交的工资条不能改。没有社保或公积金月度记录的员工不能保存工资草稿；已提交金额以工资单为准，未留存的社保分项显示为 —。</div>
      </section>

      <PayrollRecon :total="total" :social="currentBatchTotal(social.data)" :fund="currentBatchTotal(fund.data)" @go="go" />
    </template>

    <PayrollDrawer
      v-if="openRow" :row="openRow" :saving="Boolean(saving[openRow.employee])" :applying="Boolean(applying[openRow.employee])"
      :message="messages[openRow.employee] || ''" :error="errors[openRow.employee] || ''"
      @close="openEmployee = ''" @save="saveRow" @adjust="applyAdjustment" @go="go" />
  </div>
</template>
