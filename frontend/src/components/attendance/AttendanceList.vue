<script setup>
// 我的记录：按"要你处理 / 草稿 / 审批中 / 已完成"分组，重要的排在前面。
import { computed } from 'vue';
import { groupMine, hoursText, rangeText, rejectionOf, statusPill, stepRole, typeBadge, waitedDays } from '../../lib/attendanceView.js';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  names: { type: Object, default: () => ({}) },
  base: { type: String, required: true },
  title: { type: String, default: '我的记录' },
});

const groups = computed(() => groupMine(props.rows));

function who(user) {
  const key = String(user || '').toLowerCase();
  return props.names[key] || key.split('@')[0];
}

function note(row) {
  const rejection = rejectionOf(row);
  if (row.workflow_status === '草稿' && rejection) {
    return { tone: 'warn', text: `${who(rejection.actor)}：${rejection.note || '已退回，请修改后重新提交'}` };
  }
  if (['待审批', '待办理'].includes(row.workflow_status)) {
    const step = (row.steps || []).find((item) => Number(item.step_index) === Number(row.current_step_index));
    const people = (step?.approvers || []).map(who).join(' / ');
    const days = waitedDays(row);
    return { tone: 'info', text: `等 ${people || row.current_step_label || '审批人'}（${stepRole(row.current_step_label) || '审批'}）${days ? `· 已等 ${days} 天` : ''}` };
  }
  return null;
}
</script>

<template>
  <div class="at-list">
    <h4 style="margin:0;font-size:18px;font-weight:700">{{ title }}</h4>
    <div v-if="!groups.length" class="empty">还没有记录。提交后会出现在这里，也会标在左边的日历上。</div>
    <div v-for="group in groups" :key="group.key" class="at-group">
      <div class="gt">{{ group.title }}<span>{{ group.items.length }}</span></div>
      <router-link v-for="row in group.items" :key="row.name" class="at-item" :to="`${base}/${encodeURIComponent(row.name)}`">
        <span class="at-badge" :class="typeBadge(row).tone">{{ typeBadge(row).text }}</span>
        <div class="body">
          <b>{{ row.subject || '（未填主题）' }}</b>
          <div class="meta">{{ rangeText(row.from_date, row.to_date) }}<template v-if="hoursText(row)"> · {{ hoursText(row) }}</template> · {{ row.name }}</div>
          <div v-if="note(row)" class="note" :class="note(row).tone">{{ note(row).text }}</div>
        </div>
        <span class="pill" :class="statusPill(row).tone">{{ statusPill(row).text }}</span>
      </router-link>
    </div>
  </div>
</template>
