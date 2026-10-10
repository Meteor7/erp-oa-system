<script setup>
// 计算前检查（社保、公积金、宿舍、计薪天数）和计算链：应付 − 社保公积金 − 个税 − 宿舍及已发放 = 实发。
import { computed } from 'vue';
import { money, readiness, totalsOf } from '../../lib/payrollView.js';

const props = defineProps({ rows: { type: Array, default: () => [] } });
const emit = defineEmits(['go']);
const info = computed(() => readiness(props.rows));
const total = computed(() => totalsOf(props.rows));
</script>

<template>
  <div class="pr-ready" aria-label="计算前检查">
    <div>
      <span :class="['pr-dot', { warn: info.missingSocial }]">{{ info.missingSocial ? '!' : '✓' }}</span>
      <span><b>社保记录</b><span class="t"><template v-if="info.missingSocial">还差 {{ info.missingSocial }} 人 · <a href="#" @click.prevent="emit('go', '/social-insurance')">去社保页</a></template><template v-else>{{ info.total }}/{{ info.total }} 人已齐</template></span></span>
    </div>
    <div>
      <span :class="['pr-dot', { warn: info.missingFund }]">{{ info.missingFund ? '!' : '✓' }}</span>
      <span><b>公积金记录</b><span class="t"><template v-if="info.missingFund">还差 {{ info.missingFund }} 人 · <a href="#" @click.prevent="emit('go', '/housing-fund')">去公积金页</a></template><template v-else>{{ info.total }}/{{ info.total }} 人已齐</template></span></span>
    </div>
    <div><span class="pr-dot">✓</span><span><b>宿舍代扣</b><span class="t">已读取本月 {{ info.dormPeople }} 人</span></span></div>
    <div>
      <span :class="['pr-dot', { warn: info.calendarFallback }]">{{ info.calendarFallback ? '!' : '✓' }}</span>
      <span><b>计薪天数</b><span class="t">本月应计薪 {{ info.workingDays }} 天<template v-if="info.prorated">，{{ info.prorated }} 人按天折算</template><template v-if="info.calendarFallback">；{{ info.calendarFallback }} 人未设假日表，按日历天数</template></span></span>
    </div>
  </div>

  <div class="pr-chain" aria-label="本月计算链">
    <div class="pr-step" style="--c:#34489A"><div class="l">应付工资合计</div><div class="v">{{ money(total.payable) }}</div><div class="s">{{ total.people }} 人</div></div><div class="op">−</div>
    <div class="pr-step" style="--c:#7A56B8"><div class="l">社保 + 公积金（个人）</div><div class="v">{{ money(total.contrib) }}</div><div class="s">社保 {{ money(total.social) }} · 公积金 {{ money(total.fund) }}</div></div><div class="op">−</div>
    <div class="pr-step" style="--c:#B42318"><div class="l">个人所得税</div><div class="v">{{ money(total.tax) }}</div><div class="s">手填合计</div></div><div class="op">−</div>
    <div class="pr-step" style="--c:#D9731F"><div class="l">宿舍代扣 + 已发放</div><div class="v">{{ money(total.other) }}</div><div class="s">宿舍 {{ total.dormPeople }} 人 · 已发 {{ total.advancedPeople }} 人</div></div><div class="op">=</div>
    <div class="pr-step net" style="--c:#D9731F"><div class="l">实发工资合计</div><div class="v">{{ money(total.net) }}</div><div class="s">按页面上现有数字计算</div></div>
  </div>
</template>
