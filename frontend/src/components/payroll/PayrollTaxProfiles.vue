<script setup>
// 个税资料（2026-10-14）：每个员工一年一份，累计预扣法要用。
// 每月专项附加扣除（员工在个税 App 填、人事从扣缴客户端导出后录这里）、其他扣除（个人养老金等）、上年不超过 6 万的规则，
// 以及系统上线前本单位已经申报过的月份的期初累计（按扣缴客户端里的累计数填）。点一行展开填写，逐人保存。
import { computed, reactive, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { money } from '../../lib/payrollView.js';
import { displayCompany } from '../../lib/displayBrand.js';

const props = defineProps({ year: { type: Number, required: true }, readOnly: { type: Boolean, default: false } });
const emit = defineEmits(['saved']);
const api = 'rayher_hr_payroll.api.payroll_tax_entry.';
const list = createResource({ url: api + 'get_tax_profiles', method: 'GET', makeParams: () => ({ year: props.year }), auto: true });
const saver = createResource({ url: api + 'save_tax_profile' });
watch(() => props.year, () => list.reload());

const SPECIAL = [
  ['special_child_education', '子女教育'], ['special_infant_care', '3 岁以下婴幼儿照护'], ['special_continuing_education', '继续教育'],
  ['special_housing_loan', '住房贷款利息'], ['special_housing_rent', '住房租金'], ['special_elderly_support', '赡养老人'],
];
const OPENING = [
  ['opening_income', '累计收入'], ['opening_tax_free', '累计免税收入'], ['opening_special', '累计专项扣除（社保公积金个人）'],
  ['opening_special_additional', '累计专项附加扣除'], ['opening_other', '累计其他扣除'], ['opening_tax', '累计已预扣个税'],
];
const query = ref('');
const openEmployee = ref('');
const form = reactive({});
const state = reactive({ saving: false, message: '', error: '' });
const rows = computed(() => (list.data?.rows || []).filter((row) => !query.value.trim() || String(row.employee_name || '').includes(query.value.trim())));
const filled = computed(() => (list.data?.rows || []).filter((row) => row.profile).length);
const n = (value) => Number(value || 0);

function open(row) {
  if (openEmployee.value === row.employee) { openEmployee.value = ''; return; }
  openEmployee.value = row.employee;
  Object.keys(form).forEach((key) => delete form[key]);
  [...SPECIAL, ...OPENING].forEach(([key]) => { form[key] = n(row[key]); });
  Object.assign(form, {
    other_deduction: n(row.other_deduction), opening_months: n(row.opening_months), opening_to_period: row.opening_to_period || '',
    low_income_rule: Boolean(row.low_income_rule), opening_bonus_used: Boolean(row.opening_bonus_used), remark: row.remark || '',
  });
  Object.assign(state, { message: '', error: '' });
}
const formSpecial = computed(() => SPECIAL.reduce((sum, [key]) => sum + n(form[key]), 0));

async function save(row) {
  Object.assign(state, { saving: true, message: '', error: '' });
  try {
    await saver.submit({ employee: row.employee, year: props.year, values: JSON.stringify({ ...form, low_income_rule: form.low_income_rule ? 1 : 0, opening_bonus_used: form.opening_bonus_used ? 1 : 0 }) });
    state.message = '已保存，重新加载工资表后个税按新资料算';
    await list.reload();
    emit('saved');
  } catch (e) { state.error = e?.message || '保存失败'; } finally { state.saving = false; }
}
</script>

<template>
  <section class="panel" aria-label="个税资料">
    <div class="pr-tools">
      <span><b>{{ year }} 年个税资料</b> <span class="pr-note">已填 {{ filled }} / {{ list.data?.rows?.length || 0 }} 人 · 专项附加扣除从扣缴客户端导出后录入；系统上线前已申报的月份填期初累计</span></span>
      <span class="pr-ctl"><input v-model="query" class="pr-in" placeholder="按姓名查找" aria-label="按姓名查找个税资料"></span>
    </div>
    <div v-if="list.error" class="banner err" role="alert">个税资料加载失败：{{ list.error.message || list.error }}</div>
    <div class="tbl">
      <table>
        <thead><tr><th>员工</th><th class="r">每月专项附加</th><th class="r">每月其他扣除</th><th>上年 ≤ 6 万</th><th>期初累计</th><th class="r">期初已扣税</th><th></th></tr></thead>
        <tbody>
          <template v-for="row in rows" :key="row.employee">
            <tr class="row-sel" tabindex="0" @click="open(row)" @keydown.enter="open(row)">
              <td><b>{{ row.employee_name }}</b><div class="pr-sub">{{ displayCompany(row.company) }}</div></td>
              <td class="r num">{{ row.profile ? money(row.special_total) : '—' }}</td>
              <td class="r num">{{ row.profile ? money(row.other_deduction) : '—' }}</td>
              <td>{{ row.low_income_rule ? '是' : '—' }}</td>
              <td>{{ row.opening_to_period ? `截至 ${row.opening_to_period} · ${n(row.opening_months)} 个月` : '—' }}</td>
              <td class="r num">{{ row.opening_to_period ? money(row.opening_tax) : '—' }}</td>
              <td class="pr-note">{{ openEmployee === row.employee ? '收起' : (readOnly ? '查看' : '填写') }}</td>
            </tr>
            <tr v-if="openEmployee === row.employee">
              <td colspan="7">
                <div class="pr-sec" style="--c:#B42318">
                  <h5>每月专项附加扣除 <span class="pr-note">合计 {{ money(formSpecial) }}</span></h5>
                  <div v-for="[key, label] in SPECIAL" :key="key" class="pr-line"><span class="k">{{ label }}</span><input v-model="form[key]" :disabled="readOnly" type="number" min="0" step="0.01" :aria-label="label"></div>
                  <div class="pr-line"><span class="k">每月其他扣除<small>个人养老金等依法确定的扣除</small></span><input v-model="form.other_deduction" :disabled="readOnly" type="number" min="0" step="0.01" aria-label="每月其他扣除"></div>
                  <div class="pr-line"><label class="k"><input v-model="form.low_income_rule" :disabled="readOnly" type="checkbox"> 上年每月都在本单位领工资、全年不超过 6 万<small>减除费用从 1 月起直接按 6 万扣</small></label></div>
                  <h5 style="margin-top:10px">期初累计 <span class="pr-note">系统上线前、本单位已经申报过的月份；按扣缴客户端的累计数填</span></h5>
                  <div class="pr-line"><span class="k">截至的个税所属期<small>例如 {{ year }}-10（含这个月）</small></span><input v-model="form.opening_to_period" :disabled="readOnly" :placeholder="`${year}-MM`" aria-label="期初累计截至"></div>
                  <div class="pr-line"><span class="k">期初月数<small>本单位今年已经发过工资的月数</small></span><input v-model="form.opening_months" :disabled="readOnly" type="number" min="0" max="12" step="1" aria-label="期初月数"></div>
                  <div v-for="[key, label] in OPENING" :key="key" class="pr-line"><span class="k">{{ label }}</span><input v-model="form[key]" :disabled="readOnly" type="number" min="0" step="0.01" :aria-label="label"></div>
                  <div class="pr-line"><label class="k"><input v-model="form.opening_bonus_used" :disabled="readOnly" type="checkbox"> 今年已经用过年终奖单独计税</label></div>
                  <div class="pr-line"><input v-model="form.remark" :disabled="readOnly" maxlength="500" placeholder="备注" aria-label="备注" style="flex:1"></div>
                  <div v-if="!readOnly" class="pr-line"><span><span v-if="state.message" class="ok" role="status">{{ state.message }}</span><span v-if="state.error" class="err" role="alert">{{ state.error }}</span></span><button type="button" class="btn pri sm" :disabled="state.saving" @click="save(row)">{{ state.saving ? '保存中…' : '保存' }}</button></div>
                </div>
              </td>
            </tr>
          </template>
          <tr v-if="!rows.length"><td colspan="7" class="empty">没有员工</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
