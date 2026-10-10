<script setup>
// 本月对账：工资表里的社保、公积金个人合计，和已生效的批次逐项核对。个税申报合计、银行代发总额还没有数据来源，先不放。
import { computed } from 'vue';
import { money, reconRows } from '../../lib/payrollView.js';

const props = defineProps({ total: { type: Object, required: true }, social: { type: Object, default: null }, fund: { type: Object, default: null } });
const emit = defineEmits(['go']);
const items = computed(() => reconRows({ total: props.total, social: props.social, fund: props.fund }));
const pending = computed(() => items.value.filter((item) => item.status === 'diff').length);
const target = (key) => (key === 'social' ? '/social-insurance' : '/housing-fund');
</script>

<template>
  <section class="panel" aria-label="本月对账">
    <div class="pt"><span>本月对账 <span class="muted">工资表的合计和已生效的批次逐项核对，对不上的先查原因再提交</span></span><span v-if="pending" class="pill p-sun">{{ pending }} 项待查</span></div>
    <div class="pr-recon">
      <div v-for="item in items" :key="item.key" class="pr-recrow">
        <b>{{ item.label }}</b>
        <span class="num">{{ money(item.system) }}<div class="pr-note">工资表合计</div></span>
        <span class="num">{{ item.other == null ? '—' : money(item.other) }}<div class="pr-note">{{ item.otherLabel }}</div></span>
        <span :class="['num', { 'pr-up': item.status === 'diff' }]">{{ item.status === 'ok' ? '一致' : item.status === 'diff' ? (item.diff > 0 ? '+' : '') + money(item.diff) : '—' }}</span>
        <span>
          <span v-if="item.status === 'ok'" class="pill p-jade">✓ 一致</span>
          <span v-else-if="item.status === 'diff'" class="pill p-sun" :title="item.hint">待查</span>
          <a v-else href="#" class="pr-note" @click.prevent="emit('go', target(item.key))">{{ item.hint }} →</a>
        </span>
      </div>
    </div>
  </section>
</template>
