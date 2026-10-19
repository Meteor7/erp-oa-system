<script setup>
// 价格审批 + PO 与演示员工116。路由 /approval/procurement/price-approvals（旧的 /po、/:name/price-approval、/:name/contract 都重定向到这里）。
// 页面本体在 components/price/PriceWorkbench.vue，用查询参数区分栏目和单据：
//   tab=po | view=source | view=approvals | request=<OA> | approval=<PA> | po=<PO> | pr=<PR>
import PriceWorkbench from '../components/price/PriceWorkbench.vue';
</script>

<template>
  <PriceWorkbench />
</template>
