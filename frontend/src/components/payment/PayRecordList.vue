<script setup>
// 到货 / 验收 / 换货到货 / 退货发出记录：只增不改，只读显示。
import { RECORD_TONE, recordDetailText } from '../../lib/paymentView.js';

defineProps({
  records: { type: Array, default: () => [] },
  emptyText: { type: String, default: '还没有记录。' },
});
</script>

<template>
  <div class="pay-records">
    <div v-for="record in records" :key="record.name || `${record.record_type}-${record.record_date}-${record.original_filename}`" class="pay-record">
      <span class="pill" :class="`p-${RECORD_TONE[record.record_type] || 'gray'}`">{{ record.record_type }}</span>
      <span class="muted num">{{ record.record_date }}</span>
      <span class="pay-record-detail">
        {{ recordDetailText(record) }}
        <em v-if="record.note" class="muted"> · {{ record.note }}</em>
      </span>
      <a v-if="record.evidence_file" class="link" :href="record.evidence_file" target="_blank" rel="noopener">{{ record.original_filename || '查看资料' }}</a>
      <span v-else class="muted">{{ record.original_filename || '—' }}</span>
      <span class="muted">{{ record.recorded_by_name || record.recorded_by }}</span>
    </div>
    <div v-if="!records.length" class="muted">{{ emptyText }}</div>
  </div>
</template>
