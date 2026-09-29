<script setup>
// 额度卡片：年假、调休、本月考勤。一眼看到还剩多少；正在填的申请会在进度条上预占一段。
import { computed } from 'vue';
import { HOURS_PER_DAY, numText, periodTitle } from '../../lib/attendanceView.js';

const props = defineProps({
  home: { type: Object, default: null },
  requestType: { type: String, default: '请假申请' },
  leaveType: { type: String, default: '事假' },
  previewHours: { type: Number, default: 0 },
});

const annual = computed(() => props.home?.annual || null);
const comp = computed(() => props.home?.comp || null);
const month = computed(() => props.home?.month || null);

function bar(total, used, reserved, available, preview) {
  // preview 是从 available 里预占出来的一段，不重复计入总量。
  const whole = Math.max(Number(total) || 0, used + reserved + available, 1);
  const pct = (value) => `${Math.max(0, (value / whole) * 100)}%`;
  return { used: pct(used), reserved: pct(reserved), preview: pct(preview), available: pct(Math.max(0, available - preview)) };
}

const annualPreview = computed(() => (props.requestType === '请假申请' && props.leaveType === '年假' ? props.previewHours : 0));
const compPreview = computed(() => (props.requestType === '调休申请' ? props.previewHours : 0));
const overtimePreview = computed(() => (props.requestType === '加班申请' ? props.previewHours : 0));

const annualBar = computed(() => bar(annual.value?.credit_hours, annual.value?.used_hours || 0, annual.value?.reserved_hours || 0, annual.value?.available_hours || 0, annualPreview.value));
const compBar = computed(() => bar((comp.value?.credit_hours || 0) + overtimePreview.value, comp.value?.used_hours || 0, comp.value?.reserved_hours || 0, (comp.value?.available_hours || 0) + overtimePreview.value, compPreview.value + overtimePreview.value));
const monthName = computed(() => (props.home?.period ? `${Number(props.home.period.slice(5))} 月` : ''));
</script>

<template>
  <section class="at-cards" aria-label="我的额度">
    <div class="at-card" :class="{ on: requestType === '请假申请' && leaveType === '年假' }">
      <div class="top"><span>年假</span><span v-if="annual?.next_grant_date" class="chip">{{ annual.next_grant_date }} 再发 {{ numText(40 / HOURS_PER_DAY) }} 天</span></div>
      <template v-if="annual">
        <div class="at-big"><b>{{ numText((annual.available_hours || 0) / HOURS_PER_DAY) }}</b><span>天可用</span><em>{{ numText(annual.available_hours) }} 小时</em></div>
        <div class="at-meter" role="img" :aria-label="`年假可用 ${numText(annual.available_hours)} 小时`">
          <i style="background:#9AA3AF" :style="{ width: annualBar.used }"></i>
          <i style="background:repeating-linear-gradient(45deg,#C7CCD4 0 3px,#fff 3px 6px)" :style="{ width: annualBar.reserved }"></i>
          <i style="background:repeating-linear-gradient(45deg,#FFB44D 0 4px,#fff 4px 7px)" :style="{ width: annualBar.preview }"></i>
          <i style="background:#FF8F00" :style="{ width: annualBar.available }"></i>
        </div>
        <div class="at-legend">
          <span><i style="background:#9AA3AF"></i>已用 {{ numText(annual.used_hours) }}h</span>
          <span v-if="annual.reserved_hours"><i style="background:#C7CCD4"></i>审批中占用 {{ numText(annual.reserved_hours) }}h</span>
          <span><i style="background:#FF8F00"></i>可用 {{ numText(annual.available_hours) }}h</span>
          <span v-if="annualPreview"><i style="background:#FFD08A"></i>本次 {{ numText(annualPreview) }}h</span>
          <span class="r">共发放 {{ numText(annual.credit_hours) }}h</span>
        </div>
        <div v-if="annual.eligibility_message" class="at-warn">{{ annual.eligibility_message }}</div>
      </template>
      <div v-else class="muted">暂无年假信息</div>
    </div>

    <div class="at-card" :class="{ on: requestType !== '请假申请' }">
      <div class="top"><span>调休</span><span class="chip">加班 1:1 累计</span></div>
      <template v-if="comp">
        <div class="at-big"><b>{{ numText(comp.available_hours) }}</b><span>小时可用</span><em>≈ {{ numText((comp.available_hours || 0) / HOURS_PER_DAY) }} 天</em></div>
        <div class="at-meter" role="img" :aria-label="`调休可用 ${numText(comp.available_hours)} 小时`">
          <i style="background:#9AA3AF" :style="{ width: compBar.used }"></i>
          <i style="background:repeating-linear-gradient(45deg,#C7CCD4 0 3px,#fff 3px 6px)" :style="{ width: compBar.reserved }"></i>
          <i style="background:repeating-linear-gradient(45deg,#5FBFB2 0 4px,#fff 4px 7px)" :style="{ width: compBar.preview }"></i>
          <i style="background:#0F7F73" :style="{ width: compBar.available }"></i>
        </div>
        <div class="at-legend">
          <span><i style="background:#9AA3AF"></i>已用 {{ numText(comp.used_hours) }}h</span>
          <span v-if="comp.reserved_hours"><i style="background:#C7CCD4"></i>审批中占用 {{ numText(comp.reserved_hours) }}h</span>
          <span><i style="background:#0F7F73"></i>可用 {{ numText(comp.available_hours) }}h</span>
          <span v-if="compPreview"><i style="background:#8FD3CA"></i>本次 {{ numText(compPreview) }}h</span>
          <span v-if="overtimePreview"><i style="background:#8FD3CA"></i>本次 +{{ numText(overtimePreview) }}h</span>
          <span class="r">累计加班 {{ numText((comp.credit_hours || 0) + overtimePreview) }}h</span>
        </div>
        <div v-if="(comp.available_hours || 0) < 0" class="at-warn">调休余额为负，余额补足前不能新增调休，请联系人事处理。</div>
      </template>
      <div v-else class="muted">暂无调休信息</div>
    </div>

    <div class="at-card">
      <div class="top"><span>{{ monthName }}我的考勤</span><span class="chip">含审批中</span></div>
      <template v-if="month">
        <div class="at-month">
          <div><b>{{ numText(month.leave_days) }}<small>天</small></b><span>请假</span></div>
          <div><b>{{ numText(month.overtime_hours) }}<small>小时</small></b><span>加班</span></div>
          <div><b>{{ numText(month.comp_hours) }}<small>小时</small></b><span>调休</span></div>
        </div>
        <div v-if="month.pending_cap_hours > 0" class="at-warn">事假 {{ numText(month.pending_cap_hours / HOURS_PER_DAY) }} 天通过后，{{ monthName }}工时上限少 {{ numText(month.pending_cap_hours) }} 小时</div>
        <div v-else-if="month.cap_deducted_hours > 0" class="at-warn">事假已扣 {{ numText(month.cap_deducted_hours) }} 小时，{{ periodTitle(home.period) }}工时上限 {{ numText(month.hour_limit) }} 小时</div>
      </template>
      <div v-else class="muted">暂无数据</div>
    </div>
  </section>
</template>
