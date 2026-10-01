<script setup>
// 一个付款期次：条件格（实时按整张 PO 判断）、阻塞原因、在等谁、提交付款审批。
import { money } from '../../lib/paymentView.js';
import PayGateGrid from './PayGateGrid.vue';

defineProps({
  view: { type: Object, required: true },
  currency: { type: String, default: 'CNY' },
  busy: { type: Boolean, default: false },
});
defineEmits(['push', 'open']);
</script>

<template>
  <div class="pay-inst" :class="{ 'is-ready': view.canPush, 'is-paid': view.status === '已付款' }">
    <div class="pay-inst-head">
      <div class="grow-col">
        <div class="title-line">
          <b>{{ view.title }}</b>
          <span class="pill" :class="`p-${view.tone}`">{{ view.status }}</span>
        </div>
        <span class="muted">计划 {{ view.planned || '—' }} · 发票要求：{{ view.invoice }}</span>
        <span class="pay-trigger">触发条件：<b>{{ view.trigger || '无附加条件' }}</b></span>
      </div>
      <div class="amount-block">
        <span class="muted">本期金额</span>
        <b>{{ money(view.amount, currency) }}</b>
      </div>
    </div>

    <PayGateGrid :tiles="view.gates" />

    <div v-if="view.regressed" class="banner pay-regress" role="alert">{{ view.regressionText }}</div>
    <div v-if="view.draft" class="banner pay-draft">
      {{ view.draftText }}
      <button type="button" class="link strong" @click="$emit('open', view.draft)">打开草稿 {{ view.draft }}</button>
      。请先处理这张草稿，这里不再重复提交。
    </div>

    <div class="pay-inst-foot">
      <span class="pay-block-text">{{ view.blockers.length ? `当前阻塞：${view.blockers.join('；')}` : '' }}</span>
      <div class="head-actions">
        <span v-if="view.waitFor" class="muted">{{ view.waitFor }}</span>
        <button v-if="view.canPush" type="button" class="btn pri" :disabled="busy" @click="$emit('push', view)">{{ busy ? '提交中…' : '提交付款审批' }}</button>
        <button v-if="view.paymentRequest" type="button" class="btn" @click="$emit('open', view.paymentRequest)">看付款审批单 {{ view.paymentRequest }}</button>
      </div>
    </div>
  </div>
</template>
