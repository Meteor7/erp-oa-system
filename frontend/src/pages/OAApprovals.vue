<script setup>
// 付款 / 报销页面（/approval/reimbursement、/approval/purchase）：工作台在 ExpenseWorkbench 里。
// 请假、加班、调休在 2026-09-29 有了自己的页面 AttendanceCenter.vue，这里原来的那一大段
// （表单、列表、详情、审批）和早就不显示的采购旧界面一起删掉了；页面外框的样式保留。
import ExpenseWorkbench from '../components/ExpenseWorkbench.vue';
</script>

<template>
  <div class='oa-page space-y-4'>
    <ExpenseWorkbench />
  </div>
</template>

<style scoped>
.oa-page {
  --ink: #172033;
  --muted: #667085;
  --line: #e5e9f0;
  --blue: #2563eb;
  color: var(--ink);
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 1360px;
  min-height: calc(100vh - 3.5rem);
  margin: 0 auto;
  padding: 1.75rem 2.25rem 3.5rem;
  background: #f6f8fb;
}
@media (max-width: 768px) {
  .oa-page { padding: 1rem .75rem 2rem; }
}
</style>
