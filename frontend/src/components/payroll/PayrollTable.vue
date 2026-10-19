<script setup>
// 员工工资表。默认 9 列的紧凑表；勾上"显示全部列"就是和 Excel 一样的全部列。点一行打开右侧抽屉看和改。
import { displayCompany, displayDepartment } from '../../lib/displayBrand.js';
import { figures, isProrated, money, rowState } from '../../lib/payrollView.js';

defineProps({ rows: { type: Array, default: () => [] }, wide: { type: Boolean, default: false }, emptyText: { type: String, default: '本期没有符合任职期间的员工' } });
const emit = defineEmits(['open']);
const gender = (value) => (value === 'Female' ? '女' : value === 'Male' ? '男' : value || '-');
const cell = (value) => (value == null ? '—' : money(value));
// 实际 / 总工时（小时）；旧工资条只有天数时显示天
const hoursText = (row) => (row.total_hours != null ? `${Number(row.actual_hours || 0)}/${Number(row.total_hours || 0)} 小时` : `${row.payment_days}/${row.total_working_days} 天`);
</script>

<template>
  <div :class="['tbl', { wide }]">
    <table v-if="!wide">
      <thead><tr><th>员工</th><th class="r">调薪后基本工资</th><th class="r">应付工资</th><th class="r">社保（个人）</th><th class="r">公积金（个人）</th><th class="r">个税</th><th class="r">其他扣款</th><th class="r">实发工资</th><th>状态</th></tr></thead>
      <tbody>
        <tr v-for="row in rows" :key="row.employee" class="row-sel" tabindex="0" @click="emit('open', row)" @keydown.enter="emit('open', row)">
          <td>
            <span class="pr-avatar">{{ String(row.employee_name || '').slice(-2) }}</span><b>{{ row.employee_name }}</b>
            <span v-if="isProrated(row)" class="pill p-cobalt" style="margin-left:6px" :title="`按 ${hoursText(row)} 折算`">折算 {{ hoursText(row) }}</span>
            <div class="pr-sub">{{ displayCompany(row.company) }} · {{ displayDepartment(row.department) || '-' }} · {{ row.expense_account_category || '-' }}</div>
          </td>
          <td class="r num">{{ money(figures(row).adjusted) }}<div v-if="Number(row.salary_adjustment)" class="pr-note">调薪 {{ Number(row.salary_adjustment) > 0 ? '+' : '' }}{{ money(row.salary_adjustment) }}</div></td>
          <td class="r num"><b>{{ money(figures(row).payable) }}</b><div v-if="Number(row.company_subsidy) + Number(row.bonus) + Number(row.other_adjustment)" class="pr-note">含补贴/奖金/其他 {{ money(Number(row.company_subsidy) + Number(row.bonus) + Number(row.other_adjustment)) }}</div></td>
          <td class="r num"><span v-if="row.social_record_exists">{{ money(row.social_insurance) }}</span><span v-else class="pill p-red" :title="row.social_missing || ''">社保算不出来</span></td>
          <td class="r num"><span v-if="row.housing_record_exists">{{ money(row.housing_fund) }}</span><span v-else class="pill p-red" :title="row.fund_missing || ''">公积金算不出来</span></td>
          <td class="r num">{{ money(figures(row).tax) }}<div v-if="row.tax_manual" class="pr-note">手动</div></td>
          <td class="r num">{{ figures(row).other ? money(figures(row).other) : '—' }}</td>
          <td class="r num net"><b :style="figures(row).net < 0 ? 'color:#B42318' : ''">{{ money(figures(row).net) }}</b></td>
          <td><span :class="['pill', rowState(row).tone]">{{ rowState(row).label }}</span></td>
        </tr>
        <tr v-if="!rows.length"><td colspan="9" class="empty">{{ emptyText }}</td></tr>
      </tbody>
    </table>
    <table v-else>
      <thead><tr>
        <th>序号</th><th>所属单位</th><th>身份证号</th><th>性别</th><th>费用科目</th><th>部门</th><th>职位</th><th>入职时间</th><th>演示员工166时间</th><th class="r">实际/总工时</th><th>姓名</th>
        <th class="r">基本工资</th><th class="r">调薪</th><th class="r">调薪后</th><th class="r">公司补贴</th><th class="r">奖金</th><th class="r">其他补/扣</th><th class="r">应付工资</th>
        <th class="r">养老（个人）</th><th class="r">医疗（个人）</th><th class="r">失业（个人）</th><th class="r">社保合计</th><th class="r">公积金（个人）</th><th class="r">个税（代扣）</th><th class="r">宿舍代扣</th><th class="r">已发放</th><th class="r">实发工资</th>
        <th>开户银行</th><th>银行账号</th><th>手机号</th><th>状态</th>
      </tr></thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="row.employee" class="row-sel" tabindex="0" @click="emit('open', row)" @keydown.enter="emit('open', row)">
          <td>{{ index + 1 }}</td><td>{{ displayCompany(row.company) }}</td><td>{{ row.id_card_number_cn || '-' }}</td><td>{{ gender(row.gender) }}</td><td>{{ row.expense_account_category || '-' }}</td><td>{{ displayDepartment(row.department) || '-' }}</td><td>{{ row.designation || '-' }}</td><td>{{ row.date_of_joining || '-' }}</td><td>{{ row.relieving_date || '-' }}</td>
          <td class="r num">{{ hoursText(row) }}</td><td><b>{{ row.employee_name }}</b></td>
          <td class="r num">{{ cell(row.base_salary) }}</td><td class="r num">{{ cell(row.salary_adjustment) }}</td><td class="r num">{{ money(figures(row).adjusted) }}</td><td class="r num">{{ cell(row.company_subsidy) }}</td><td class="r num">{{ cell(row.bonus) }}</td><td class="r num">{{ cell(row.other_adjustment) }}</td><td class="r num"><b>{{ money(figures(row).payable) }}</b></td>
          <td class="r num">{{ cell(row.employee_pension) }}</td><td class="r num">{{ cell(row.employee_medical) }}</td><td class="r num">{{ cell(row.employee_unemployment) }}</td><td class="r num">{{ row.social_record_exists ? money(row.social_insurance) : '社保算不出来' }}</td><td class="r num">{{ row.housing_record_exists ? money(row.housing_fund) : '公积金算不出来' }}</td>
          <td class="r num">{{ money(figures(row).tax) }}</td><td class="r num">{{ money(row.accommodation) }}</td><td class="r num">{{ money(row.advanced_paid) }}</td><td class="r num"><b>{{ money(figures(row).net) }}</b></td>
          <td>{{ row.bank_name || '-' }}</td><td>{{ row.bank_ac_no || '-' }}</td><td>{{ row.cell_number || '-' }}</td><td><span :class="['pill', rowState(row).tone]">{{ rowState(row).label }}</span></td>
        </tr>
        <tr v-if="!rows.length"><td colspan="31" class="empty">{{ emptyText }}</td></tr>
      </tbody>
    </table>
  </div>
</template>
