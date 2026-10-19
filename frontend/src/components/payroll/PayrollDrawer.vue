<script setup>
// 一个人的工资，按五步看和改：基本工资（按工时折算）→ 应付工资 → 扣社保公积金 → 个税（累计预扣法）→ 其他扣款与实发。
// 输入框直接改页面上这一行的数字（和原来一样），改完当场重算，点"保存草稿"才写入；保存时以后端算的为准。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { displayCompany, displayDepartment } from '../../lib/displayBrand.js';
import { autoHours, canSave, canWithdraw, figures, isProrated, money, rowLocked, rowState } from '../../lib/payrollView.js';

const props = defineProps({
  row: { type: Object, required: true }, saving: { type: Boolean, default: false }, applying: { type: Boolean, default: false },
  message: { type: String, default: '' }, error: { type: String, default: '' }, readOnly: { type: Boolean, default: false },
  dirty: { type: Boolean, default: false },   // 这个人改了还没保存（页面按加载时的输入比出来）
});
const emit = defineEmits(['close', 'save', 'adjust', 'withdraw', 'go']);
const f = computed(() => figures(props.row));
// 只读（总经理、副总经理）或工资条已确认 / 别处生成：输入框都不能改。
const locked = computed(() => props.readOnly || rowLocked(props.row));
// 撤回确认要写原因；换一个人就清空。
const withdrawing = ref(false);
const reason = ref('');
watch(() => props.row.employee, () => { withdrawing.value = false; reason.value = ''; });
const showWithdraw = computed(() => !props.readOnly && canWithdraw(props.row));
const state = computed(() => rowState(props.row));
const hasSplit = computed(() => props.row.employee_pension != null);
const hasHours = computed(() => props.row.total_hours != null);
const t = computed(() => f.value.taxDetail);
const n = (value) => Number(value || 0);
const hours = (value) => `${n(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 小时`;
const onKey = (event) => { if (event.key === 'Escape') emit('close'); };
onMounted(() => document.addEventListener('keydown', onKey));
onBeforeUnmount(() => document.removeEventListener('keydown', onKey));
const canApply = computed(() => !locked.value && Number(props.row.salary_adjustment) !== 0 && f.value.adjusted > 0);
// 改实际工时 = 手动；“按考勤重算”恢复成在职工时 − 事假
function editHours(event) { props.row.actual_hours = event.target.value; props.row.hours_manual = true; }
function resetHours() { props.row.hours_manual = false; props.row.actual_hours = autoHours(props.row); }
// 手动改个税：先把系统算的数带进输入框，再让人事改；取消手动就回到系统算的
function toggleTaxManual(event) {
  props.row.tax_manual = event.target.checked;
  if (props.row.tax_manual) props.row.income_tax = t.value ? t.value.total : n(props.row.income_tax);
}
const bonusLocked = computed(() => locked.value || (props.row.tax_basis?.bonus_used && !props.row.bonus_separate) || !n(props.row.bonus));
const needReason = computed(() => props.row.tax_manual && !String(props.row.tax_manual_reason || '').trim());
</script>

<template>
  <div class="pr-scrim" @click="emit('close')"></div>
  <aside class="pr-drawer" role="dialog" aria-modal="true" :aria-label="`${row.employee_name} 工资明细`">
    <header>
      <div>
        <h4>{{ row.employee_name }} · {{ row.expense_account_category || '未设置费用科目' }}</h4>
        <div class="pr-note">{{ displayCompany(row.company) }} · {{ displayDepartment(row.department) || '-' }} · {{ row.designation || '-' }} · 开户行 {{ row.bank_name || '-' }} {{ row.bank_ac_no || '' }}</div>
        <div style="margin-top:6px"><span :class="['pill', state.tone]">{{ state.label }}</span> <span v-if="isProrated(row)" class="pill p-cobalt">本月按工时折算</span></div>
      </div>
      <button type="button" class="btn sm" @click="emit('close')">关闭</button>
    </header>
    <div class="body">
      <div class="pr-sec" style="--c:#34489A"><h5><i>1</i>基本工资</h5>
        <div class="pr-line"><span class="k">基本工资</span><input v-model="row.base_salary" :disabled="locked" type="number" min="0" step="0.01" aria-label="基本工资"></div>
        <div class="pr-line"><span class="k">本月调薪<small>可点“应用调薪”带到后续月份</small></span><input v-model="row.salary_adjustment" :disabled="locked" type="number" step="0.01" aria-label="本月调薪"></div>
        <div class="pr-line"><span class="k">调薪后基本工资</span><span class="num" style="text-align:right">{{ money(f.adjusted) }}</span></div>
        <template v-if="hasHours">
          <div class="pr-line"><span class="k">当月总工时<small>{{ row.work_days }} 个工作日 × 8<template v-if="row.calendar_source === 'weekday_fallback'">（公司没设假日表，按周一到周五）</template></small></span><span class="num" style="text-align:right">{{ hours(row.total_hours) }}</span></div>
          <div class="pr-line"><span class="k">事假<small>已批准的事假；年假、调休、病假、婚丧产假不扣</small></span><span class="num" style="text-align:right">{{ n(row.personal_leave_hours) ? '− ' + hours(row.personal_leave_hours) : '—' }}</span></div>
          <div v-if="n(row.employed_hours) < n(row.total_hours)" class="pr-line"><span class="k">不在职的日子<small>入职前 / 离职后</small></span><span class="num" style="text-align:right">− {{ hours(n(row.total_hours) - n(row.employed_hours)) }}</span></div>
          <div class="pr-line"><span class="k">实际工时<small v-if="row.hours_manual">手动改过 · <a v-if="!locked" href="#" @click.prevent="resetHours">按考勤重算（{{ hours(autoHours(row)) }}）</a></small><small v-else>按考勤算</small></span><input :value="row.actual_hours" :disabled="locked" type="number" min="0" :max="row.total_hours" step="0.5" aria-label="实际工时" @input="editHours"></div>
          <div class="pr-line"><span class="k">折算后基本工资<small>{{ money(f.adjusted) }} × {{ n(row.actual_hours) }} ÷ {{ n(row.total_hours) }}</small></span><span class="num" style="text-align:right">{{ money(f.prorated) }}</span></div>
        </template>
        <div v-else class="pr-line"><span class="k">折算后基本工资<small>按 {{ row.payment_days }}/{{ row.total_working_days }} 天（旧工资条）</small></span><span class="num" style="text-align:right">{{ money(f.prorated) }}</span></div>
      </div>
      <div class="pr-sec" style="--c:#34489A"><h5><i>2</i>应付工资</h5>
        <div class="pr-line"><span class="k">公司补贴</span><input v-model="row.company_subsidy" :disabled="locked" type="number" min="0" step="0.01" aria-label="公司补贴"></div>
        <div class="pr-line"><span class="k">奖金</span><input v-model="row.bonus" :disabled="locked" type="number" min="0" step="0.01" aria-label="奖金"></div>
        <div class="pr-line"><span class="k">其他补/扣<small>补发为正，扣款为负</small></span><input v-model="row.other_adjustment" :disabled="locked" type="number" step="0.01" aria-label="其他补扣"></div>
        <div class="pr-line total"><span class="k">应付工资</span><span class="num" style="text-align:right">{{ money(f.payable) }}</span></div>
      </div>
      <div class="pr-sec" style="--c:#7A56B8"><h5><i>3</i>扣社保和公积金 <span class="pr-note">账单 / 月度记录优先，没有就按员工档案基数 × 公司当年政策算</span></h5>
        <template v-if="row.social_record_exists">
          <template v-if="hasSplit">
            <div class="pr-line"><span class="k">养老保险（个人）</span><span class="num" style="text-align:right">{{ money(row.employee_pension) }}</span></div>
            <div class="pr-line"><span class="k">医疗保险（个人）</span><span class="num" style="text-align:right">{{ money(row.employee_medical) }}</span></div>
            <div class="pr-line"><span class="k">失业保险（个人）</span><span class="num" style="text-align:right">{{ money(row.employee_unemployment) }}</span></div>
          </template>
          <div class="pr-line total"><span class="k">社保合计（个人）<span v-if="row.social_source" class="pr-src">{{ row.social_source }}</span></span><span class="num" style="text-align:right">{{ money(row.social_insurance) }}</span></div>
        </template>
        <div v-else class="pr-line"><span class="k">社保</span><span><span class="pill p-red">{{ row.social_missing || '本月社保算不出来' }}，不能保存草稿</span> <button type="button" class="btn sm" @click="emit('go', '/social-insurance')">去社保信息管理</button></span></div>
        <div v-if="row.housing_record_exists" class="pr-line total"><span class="k">公积金（个人）<span v-if="row.fund_source" class="pr-src">{{ row.fund_source }}</span></span><span class="num" style="text-align:right">{{ money(row.housing_fund) }}</span></div>
        <div v-else class="pr-line"><span class="k">公积金</span><span><span class="pill p-red">{{ row.fund_missing || '本月公积金算不出来' }}，不能保存草稿</span> <button type="button" class="btn sm" @click="emit('go', '/housing-fund')">去公积金信息管理</button></span></div>
      </div>
      <div class="pr-sec" style="--c:#B42318"><h5><i>4</i>个人所得税 <span class="pr-note">累计预扣法 · 工资次月发，算在 {{ t?.tax_period || row.tax?.tax_period || '发放月' }}</span></h5>
        <template v-if="t">
          <div class="pr-line"><span class="k">累计收入<small>今年第 {{ t.months }} 个月（含本月计税收入 {{ money(t.income) }}<template v-if="row.bonus_separate">，不含单独计税的年终奖</template>）</small></span><span class="num" style="text-align:right">{{ money(t.cum_income) }}</span></div>
          <div class="pr-line"><span class="k">累计减除费用<small>{{ n(t.cum_basic) > 5000 * n(t.months) ? '上年不超过 6 万，从 1 月起按 6 万扣' : `5000 × ${t.months} 个月` }}</small></span><span class="num" style="text-align:right">− {{ money(t.cum_basic) }}</span></div>
          <div class="pr-line"><span class="k">累计专项扣除<small>社保 + 公积金个人部分</small></span><span class="num" style="text-align:right">− {{ money(t.cum_special) }}</span></div>
          <div class="pr-line"><span class="k">累计专项附加扣除<small>本月 {{ money(t.special_additional) }}<template v-if="row.tax_basis && !row.tax_basis.has_profile">（没有录个税资料，按 0）</template></small></span><span class="num" style="text-align:right">− {{ money(t.cum_special_additional) }}</span></div>
          <div v-if="t.cum_other" class="pr-line"><span class="k">累计其他扣除</span><span class="num" style="text-align:right">− {{ money(t.cum_other) }}</span></div>
          <div class="pr-line"><span class="k">累计应纳税所得额<small>预扣率 {{ t.rate }}% · 速算扣除数 {{ money(t.quick) }}</small></span><span class="num" style="text-align:right">{{ money(t.cum_taxable) }}</span></div>
          <div class="pr-line"><span class="k">累计应纳税额 − 已预扣</span><span class="num" style="text-align:right">{{ money(t.cum_tax) }} − {{ money(t.prior_tax) }}</span></div>
          <div v-if="row.bonus_separate || t.bonus_tax" class="pr-line"><span class="k">年终奖单独计税<small v-if="t.bonus_rate != null">{{ money(row.bonus) }} ÷ 12 查月度表，{{ t.bonus_rate }}% − {{ money(t.bonus_quick) }}</small></span><span class="num" style="text-align:right">{{ money(t.bonus_tax) }}</span></div>
          <div class="pr-line total"><span class="k">系统算的本月个税</span><span class="num" style="text-align:right">{{ money(t.total) }}</span></div>
        </template>
        <div v-for="text in row.tax_warnings || []" :key="text" class="pr-line"><span class="pill p-sun">{{ text }}</span></div>
        <div v-if="!locked" class="pr-line"><label class="k"><input type="checkbox" :checked="Boolean(row.bonus_separate)" :disabled="bonusLocked" @change="row.bonus_separate = $event.target.checked"> 奖金按全年一次性奖金单独计税<small>{{ row.tax_basis?.bonus_used && !row.bonus_separate ? '今年已经用过，一年只能用一次' : '一年只能用一次；不勾就并入当月工资计税' }}</small></label></div>
        <div v-if="!locked" class="pr-line"><label class="k"><input type="checkbox" :checked="Boolean(row.tax_manual)" @change="toggleTaxManual"> 手动改个税<small>比如和扣缴客户端算的不一样时，以申报为准</small></label></div>
        <template v-if="row.tax_manual">
          <div class="pr-line"><span class="k">本月个税（手动）</span><input v-model="row.income_tax" :disabled="locked" type="number" min="0" step="0.01" aria-label="个税"></div>
          <div class="pr-line"><input v-model="row.tax_manual_reason" :disabled="locked" maxlength="500" placeholder="改的原因（必填），例如：按扣缴客户端申报数" aria-label="手动改个税的原因" style="flex:1"></div>
        </template>
        <div v-else-if="locked && !t" class="pr-line"><span class="k">个税（代扣）</span><span class="num" style="text-align:right">{{ money(f.tax) }}</span></div>
      </div>
      <div class="pr-sec" style="--c:#147B73"><h5><i>5</i>其他扣款与实发</h5>
        <div class="pr-line"><span class="k">个税（代扣）</span><span class="num" style="text-align:right">{{ money(f.tax) }}</span></div>
        <div class="pr-line"><span class="k">宿舍房租及水电费（代扣）<span class="pr-src">宿舍信息管理</span></span><span class="num" style="text-align:right">{{ money(row.accommodation) }}</span></div>
        <div class="pr-line"><span class="k">已发放<small>本月已经预发的金额</small></span><input v-model="row.advanced_paid" :disabled="locked" type="number" min="0" step="0.01" aria-label="已发放"></div>
        <div class="pr-line total"><span class="k">实发工资</span><span class="num" :style="{ textAlign: 'right', color: f.net < 0 ? '#B42318' : '' }">{{ money(f.net) }}</span></div>
      </div>
    </div>
    <footer>
      <div>
        <span class="pr-note">{{ readOnly ? '只读：可以查看，不能修改。' : locked ? (showWithdraw ? '工资条已确认，要改请先撤回确认。' : '别处生成的工资条不能在这里修改。') : '改动会当场重新计算，点“保存草稿”才会写入。' }}</span>
        <div v-if="withdrawing" class="pr-line" style="margin-top:6px"><input v-model="reason" maxlength="500" placeholder="撤回原因（必填），例如：个税填错了" aria-label="撤回原因" style="flex:1"></div>
        <div v-if="dirty && !readOnly" class="pr-note" data-payroll-row-dirty style="color:#B54708">这个人改了还没保存；没保存的改动不会被确认。</div>
        <div v-if="needReason && !locked" class="pr-note" style="color:#B54708">手动改个税要写原因才能保存。</div>
        <div v-if="message" class="ok" role="status">{{ message }}</div>
        <div v-if="error" class="err" role="alert">{{ error }}</div>
      </div>
      <span v-if="showWithdraw" style="display:flex;gap:8px">
        <button v-if="!withdrawing" type="button" class="btn" @click="withdrawing = true">撤回确认</button>
        <template v-else>
          <button type="button" class="btn" @click="withdrawing = false">取消</button>
          <button type="button" class="btn pri" :disabled="!reason.trim() || saving" @click="emit('withdraw', row, reason.trim())">{{ saving ? '撤回中…' : '确定撤回' }}</button>
        </template>
      </span>
      <span v-else-if="!readOnly" style="display:flex;gap:8px">
        <button type="button" class="btn" :disabled="!canApply || applying" @click="emit('adjust', row)">{{ applying ? '应用中…' : '应用调薪' }}</button>
        <button type="button" class="btn pri" :disabled="!canSave(row) || saving || needReason" @click="emit('save', row)">{{ saving ? '保存中…' : '保存草稿' }}</button>
      </span>
    </footer>
  </aside>
</template>
