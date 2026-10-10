<script setup>
// 一个人的工资，按五步看和改：基本工资 → 应付工资 → 扣社保公积金 → 个税 → 其他扣款与实发。
// 输入框直接改页面上这一行的数字（和原来一样），改完当场重算，点"保存草稿"才写入。
import { computed, onBeforeUnmount, onMounted } from 'vue';
import { displayCompany, displayDepartment } from '../../lib/displayBrand.js';
import { canSave, figures, isProrated, money, rowLocked, rowState } from '../../lib/payrollView.js';

const props = defineProps({
  row: { type: Object, required: true }, saving: { type: Boolean, default: false }, applying: { type: Boolean, default: false },
  message: { type: String, default: '' }, error: { type: String, default: '' },
});
const emit = defineEmits(['close', 'save', 'adjust', 'go']);
const f = computed(() => figures(props.row));
const locked = computed(() => rowLocked(props.row));
const state = computed(() => rowState(props.row));
const hasSplit = computed(() => props.row.employee_pension != null);
const onKey = (event) => { if (event.key === 'Escape') emit('close'); };
onMounted(() => document.addEventListener('keydown', onKey));
onBeforeUnmount(() => document.removeEventListener('keydown', onKey));
const canApply = computed(() => !locked.value && Number(props.row.salary_adjustment) !== 0 && f.value.adjusted > 0);
</script>

<template>
  <div class="pr-scrim" @click="emit('close')"></div>
  <aside class="pr-drawer" role="dialog" aria-modal="true" :aria-label="`${row.employee_name} 工资明细`">
    <header>
      <div>
        <h4>{{ row.employee_name }} · {{ row.expense_account_category || '未设置费用科目' }}</h4>
        <div class="pr-note">{{ displayCompany(row.company) }} · {{ displayDepartment(row.department) || '-' }} · {{ row.designation || '-' }} · 开户行 {{ row.bank_name || '-' }} {{ row.bank_ac_no || '' }}</div>
        <div style="margin-top:6px"><span :class="['pill', state.tone]">{{ state.label }}</span> <span v-if="isProrated(row)" class="pill p-cobalt">本月计 {{ row.payment_days }}/{{ row.total_working_days }} 天</span></div>
      </div>
      <button type="button" class="btn sm" @click="emit('close')">关闭</button>
    </header>
    <div class="body">
      <div class="pr-sec" style="--c:#34489A"><h5><i>1</i>基本工资</h5>
        <div class="pr-line"><span class="k">基本工资</span><input v-model="row.base_salary" :disabled="locked" type="number" min="0" step="0.01" aria-label="基本工资"></div>
        <div class="pr-line"><span class="k">本月调薪<small>可点“应用调薪”带到后续月份</small></span><input v-model="row.salary_adjustment" :disabled="locked" type="number" step="0.01" aria-label="本月调薪"></div>
        <div class="pr-line"><span class="k">调薪后基本工资</span><span class="num" style="text-align:right">{{ money(f.adjusted) }}</span></div>
        <div class="pr-line"><span class="k">计薪天数<small>本月应计薪 {{ row.total_working_days }} 天<template v-if="row.working_days_source === 'calendar_fallback'">（未设假日表，按日历天数）</template></small></span><input v-model="row.payment_days" :disabled="locked" type="number" min="0" :max="row.total_working_days" step="0.5" aria-label="计薪天数"></div>
        <div class="pr-line"><span class="k">折算后基本工资<small>{{ money(f.adjusted) }} × {{ row.payment_days }} ÷ {{ row.total_working_days }}</small></span><span class="num" style="text-align:right">{{ money(f.prorated) }}</span></div>
      </div>
      <div class="pr-sec" style="--c:#34489A"><h5><i>2</i>应付工资</h5>
        <div class="pr-line"><span class="k">公司补贴</span><input v-model="row.company_subsidy" :disabled="locked" type="number" min="0" step="0.01" aria-label="公司补贴"></div>
        <div class="pr-line"><span class="k">奖金</span><input v-model="row.bonus" :disabled="locked" type="number" min="0" step="0.01" aria-label="奖金"></div>
        <div class="pr-line"><span class="k">其他补/扣<small>补发为正，扣款为负</small></span><input v-model="row.other_adjustment" :disabled="locked" type="number" step="0.01" aria-label="其他补扣"></div>
        <div class="pr-line total"><span class="k">应付工资</span><span class="num" style="text-align:right">{{ money(f.payable) }}</span></div>
      </div>
      <div class="pr-sec" style="--c:#7A56B8"><h5><i>3</i>扣社保和公积金 <span class="pr-note">来自已生效的批次，这里不能改</span></h5>
        <template v-if="row.social_record_exists">
          <template v-if="hasSplit">
            <div class="pr-line"><span class="k">养老保险（个人）<span class="pr-src">社保</span></span><span class="num" style="text-align:right">{{ money(row.employee_pension) }}</span></div>
            <div class="pr-line"><span class="k">医疗保险（个人）<span class="pr-src">社保</span></span><span class="num" style="text-align:right">{{ money(row.employee_medical) }}</span></div>
            <div class="pr-line"><span class="k">失业保险（个人）<span class="pr-src">社保</span></span><span class="num" style="text-align:right">{{ money(row.employee_unemployment) }}</span></div>
          </template>
          <div class="pr-line total"><span class="k">社保合计（个人）</span><span class="num" style="text-align:right">{{ money(row.social_insurance) }}</span></div>
        </template>
        <div v-else class="pr-line"><span class="k">社保</span><span><span class="pill p-red">本月社保记录未维护，不能保存草稿</span> <button type="button" class="btn sm" @click="emit('go', '/social-insurance')">去社保信息管理</button></span></div>
        <div v-if="row.housing_record_exists" class="pr-line total"><span class="k">公积金（个人）<span class="pr-src">公积金</span></span><span class="num" style="text-align:right">{{ money(row.housing_fund) }}</span></div>
        <div v-else class="pr-line"><span class="k">公积金</span><span><span class="pill p-red">本月公积金记录未维护，不能保存草稿</span> <button type="button" class="btn sm" @click="emit('go', '/housing-fund')">去公积金信息管理</button></span></div>
      </div>
      <div class="pr-sec" style="--c:#B42318"><h5><i>4</i>个人所得税</h5>
        <div class="pr-line"><span class="k">个税（代扣）<small>目前手填；计算逻辑确定后改为自动计算</small></span><input v-model="row.income_tax" :disabled="locked" type="number" min="0" step="0.01" aria-label="个税"></div>
      </div>
      <div class="pr-sec" style="--c:#D9731F"><h5><i>5</i>其他扣款与实发</h5>
        <div class="pr-line"><span class="k">宿舍房租及水电费（代扣）<span class="pr-src">宿舍信息管理</span></span><span class="num" style="text-align:right">{{ money(row.accommodation) }}</span></div>
        <div class="pr-line"><span class="k">已发放<small>本月已经预发的金额</small></span><input v-model="row.advanced_paid" :disabled="locked" type="number" min="0" step="0.01" aria-label="已发放"></div>
        <div class="pr-line total"><span class="k">实发工资</span><span class="num" :style="{ textAlign: 'right', color: f.net < 0 ? '#B42318' : '' }">{{ money(f.net) }}</span></div>
      </div>
    </div>
    <footer>
      <div>
        <span class="pr-note">{{ locked ? '已提交或别处生成的工资条不能在这里修改。' : '改动会当场重新计算，点“保存草稿”才会写入。' }}</span>
        <div v-if="message" class="ok" role="status">{{ message }}</div>
        <div v-if="error" class="err" role="alert">{{ error }}</div>
      </div>
      <span style="display:flex;gap:8px">
        <button type="button" class="btn" :disabled="!canApply || applying" @click="emit('adjust', row)">{{ applying ? '应用中…' : '应用调薪' }}</button>
        <button type="button" class="btn pri" :disabled="!canSave(row) || saving" @click="emit('save', row)">{{ saving ? '保存中…' : '保存草稿' }}</button>
      </span>
    </footer>
  </aside>
</template>
