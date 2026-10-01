<script setup>
// 采购申请 / 购买申请：/approval/direct-purchase* 是购买申请，其余是采购申请。
// 页面本身在 components/procurement/ProcurementWorkbench.vue，用查询参数分首页 / 列表 / 详情；
// 新建、草稿、PMC 补录是各自的路由（procurement-new、direct-purchase-new、procurement-pmc-edit）。
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import ProcurementWorkbench from '../components/procurement/ProcurementWorkbench.vue';
import { requestTypeForPath } from '../lib/procurementView.js';

const route = useRoute();
const requestType = computed(() => requestTypeForPath(route.path));
</script>

<template>
  <ProcurementWorkbench :key="requestType" :request-type="requestType" />
</template>
