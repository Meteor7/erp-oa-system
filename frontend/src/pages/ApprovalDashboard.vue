<script setup>
import { computed, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { useRoute } from 'vue-router';
const route = useRoute();
const kind = computed(() => route.path === '/approval/payment-dashboard' ? 'payment' : 'request');
const title = computed(() => kind.value === 'payment' ? '付款看板' : '申请看板');
const resource = createResource({ url: 'rayher_hr_payroll.api.oa_entry.get_approval_center_dashboard', method: 'GET', makeParams: () => ({ kind: kind.value }), auto: true });
watch(kind, () => resource.reload());
const data = computed(() => resource.data || { summary: {}, rows: [] });
const cards = [
  ['applied_amount', '申请金额'], ['approved_amount', '批准金额'], ['reserved_amount', '占用金额'], ['paid_amount', '已付金额'], ['available_amount', '可用余额'],
];
const money = (value) => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
</script>
<template>
  <div class='space-y-5'>
    <section class='rounded-lg border bg-white p-6 shadow-sm'><h1 class='text-xl font-semibold'>{{ title }}</h1><p class='mt-1 text-sm text-gray-500'>只展示当前登录账号在服务端权限范围内可见的单据。</p><div class='mt-5 grid gap-3 md:grid-cols-5'><div v-for='card in cards' :key='card[0]' class='rounded border bg-gray-50 p-4'><div class='text-sm text-gray-500'>{{ card[1] }}</div><div class='mt-1 text-xl font-semibold'>{{ money(data.summary[card[0]]) }}</div></div></div></section>
    <section class='rounded-lg border bg-white p-6 shadow-sm'><div class='overflow-x-auto'><table class='min-w-full text-sm'><thead><tr class='border-b text-left text-gray-500'><th class='p-2'>单号</th><th class='p-2'>类型</th><th class='p-2'>主题</th><th class='p-2'>状态</th><th class='p-2'>资产分类</th><th v-for='card in cards' :key='card[0]' class='p-2 text-right'>{{ card[1] }}</th></tr></thead><tbody><tr v-for='row in data.rows' :key='row.name' class='border-b'><td class='p-2'>{{ row.name }}</td><td class='p-2'>{{ row.request_type }}</td><td class='p-2'>{{ row.subject }}</td><td class='p-2'>{{ row.workflow_status }}</td><td class='p-2'>{{ row.asset_classification || '历史未分类' }}</td><td v-for='card in cards' :key='card[0]' class='p-2 text-right'>{{ money(row[card[0]]) }}</td></tr></tbody></table><p v-if='!data.rows.length' class='py-10 text-center text-gray-400'>暂无数据；旧单据资产属性为空时显示“历史未分类”。</p></div></section>
  </div>
</template>