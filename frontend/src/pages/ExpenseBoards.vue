<script setup>
// 申请看板 / 付款看板 / 采购看板：只读，点单号跳到对应单据。数据范围由服务端按角色决定。
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { callApi, money, statusTone } from '../lib/expenseClaims.js';
import {
  BOARD_TABS, boardRoute, cardTone, dueText, overdueTone, paymentCards,
  procurementCards, requestCards, tabFor, trendBars,
} from '../lib/expenseBoards.js';

const route = useRoute();
const router = useRouter();
const tab = ref(tabFor(route.path, route.query));
const data = ref({});
const loading = ref(false);
const errorMessage = ref('');

const config = computed(() => BOARD_TABS.find((item) => item.key === tab.value) || BOARD_TABS[0]);
const cards = computed(() => {
  if (tab.value === 'request') return requestCards(data.value);
  if (tab.value === 'payment') return paymentCards(data.value);
  return procurementCards(data.value);
});
const bars = computed(() => trendBars(data.value.trend || []));
const scopeText = computed(() => ({
  all: '范围：全公司',
  department: `范围：本部门（${data.value.department || ''}）`,
}[data.value.scope] || ''));

async function load() {
  loading.value = true;
  errorMessage.value = '';
  try {
    data.value = await callApi(config.value.method, {}, { method: 'GET' }) || {};
  } catch (error) {
    data.value = {};
    errorMessage.value = String(error?.message || error || '看板加载失败');
  } finally {
    loading.value = false;
  }
}

function open(row) {
  router.push({ path: boardRoute(row.request_type || (tab.value === 'request' ? '购买申请' : '报销单')), query: { request: row.name } });
}

watch(tab, (value) => {
  router.replace({ path: route.path, query: { ...route.query, tab: value } });
  load();
});
watch(() => route.path, () => { tab.value = tabFor(route.path, route.query); load(); });
onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <section class="rounded-lg border bg-white p-5 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold">{{ config.label }}</h1>
          <p class="mt-1 text-sm text-gray-500">{{ config.hint }} {{ scopeText }}</p>
        </div>
        <div class="flex gap-2">
          <button v-for="item in BOARD_TABS" :key="item.key" type="button" class="rounded px-3 py-1.5 text-sm"
            :class="tab === item.key ? 'bg-gray-900 text-white' : 'border'" @click="tab = item.key">{{ item.label }}</button>
        </div>
      </div>
      <p v-if="errorMessage" class="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{{ errorMessage }}</p>
    </section>

    <p v-if="loading" class="rounded-lg border bg-white p-10 text-center text-sm text-gray-500 shadow-sm">正在加载看板数据…</p>
    <template v-else>
      <section class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="card in cards" :key="card.key" class="rounded-lg border p-4 shadow-sm" :class="cardTone(card.tone)">
          <div class="text-sm text-gray-600">{{ card.label }}</div>
          <div class="mt-1 text-2xl font-semibold">{{ card.money ? money(card.value) : card.value }}</div>
        </div>
      </section>

      <template v-if="tab === 'request'">
        <section class="rounded-lg border bg-white p-5 shadow-sm">
          <h2 class="font-semibold">审批卡点</h2>
          <p class="mt-1 text-xs text-gray-500">等待超过 {{ data.stuck_days || 3 }} 天的标红。</p>
          <table class="mt-3 min-w-full text-sm">
            <thead><tr class="border-b text-left text-gray-500"><th class="p-2">单号</th><th class="p-2">类型</th><th class="p-2">申请人</th><th class="p-2">当前节点</th><th class="p-2 text-right">已等待</th></tr></thead>
            <tbody>
              <tr v-for="row in data.stuck_approvals || []" :key="row.name" class="border-b">
                <td class="p-2"><button type="button" class="font-medium text-blue-700 hover:underline" @click="open(row)">{{ row.name }}</button></td>
                <td class="p-2">{{ row.request_type }}</td>
                <td class="p-2">{{ row.employee_name }}<span class="text-xs text-gray-500"> · {{ row.department }}</span></td>
                <td class="p-2">{{ row.current_step_label || '-' }}</td>
                <td class="p-2 text-right" :class="row.overdue ? 'text-red-700 font-medium' : 'text-gray-600'">{{ row.waited_days }} 天</td>
              </tr>
            </tbody>
          </table>
          <p v-if="!(data.stuck_approvals || []).length" class="py-6 text-center text-gray-400">没有在审的申请。</p>
        </section>

        <section class="rounded-lg border bg-white p-5 shadow-sm">
          <h2 class="font-semibold">超过 {{ data.stale_days || 30 }} 天未执行的购买申请</h2>
          <table class="mt-3 min-w-full text-sm">
            <thead><tr class="border-b text-left text-gray-500"><th class="p-2">单号</th><th class="p-2">主题</th><th class="p-2">申请人</th><th class="p-2 text-right">批准金额</th><th class="p-2 text-right">已批准天数</th></tr></thead>
            <tbody>
              <tr v-for="row in data.stale_applications || []" :key="row.name" class="border-b">
                <td class="p-2"><button type="button" class="font-medium text-blue-700 hover:underline" @click="open({ ...row, request_type: '购买申请' })">{{ row.name }}</button></td>
                <td class="p-2">{{ row.subject }}</td>
                <td class="p-2">{{ row.employee_name }}<span class="text-xs text-gray-500"> · {{ row.department }}</span></td>
                <td class="p-2 text-right">{{ money(row.approved_amount) }}</td>
                <td class="p-2 text-right" :class="overdueTone(row.idle_days)">{{ row.idle_days }} 天</td>
              </tr>
            </tbody>
          </table>
          <p v-if="!(data.stale_applications || []).length" class="py-6 text-center text-gray-400">没有长期未执行的购买申请。</p>
        </section>

        <section class="rounded-lg border bg-white p-5 shadow-sm">
          <h2 class="font-semibold">出差</h2>
          <p class="mt-1 text-xs text-gray-500">本月出差 {{ (data.travel?.this_month || []).length }} 人次，已报销 / 已付款 {{ money(data.travel?.claimed_amount) }} 元。</p>
          <table class="mt-3 min-w-full text-sm">
            <thead><tr class="border-b text-left text-gray-500"><th class="p-2">单号</th><th class="p-2">出差人</th><th class="p-2">地点</th><th class="p-2">行程</th><th class="p-2 text-right">已报销</th><th class="p-2">状态</th></tr></thead>
            <tbody>
              <tr v-for="row in [...(data.travel?.ongoing || []), ...(data.travel?.this_month || []).filter((item) => !(data.travel?.ongoing || []).some((o) => o.name === item.name))]" :key="row.name" class="border-b">
                <td class="p-2"><button type="button" class="font-medium text-blue-700 hover:underline" @click="open({ ...row, request_type: '出差申请' })">{{ row.name }}</button></td>
                <td class="p-2">{{ row.employee_name }}</td>
                <td class="p-2">{{ row.travel_destination }}</td>
                <td class="p-2">{{ row.travel_start_date }} → {{ row.travel_end_date }}（{{ row.travel_days }} 天）</td>
                <td class="p-2 text-right">{{ money(row.claimed_amount) }}</td>
                <td class="p-2"><span class="rounded px-2 py-0.5 text-xs" :class="statusTone((data.travel?.ongoing || []).some((o) => o.name === row.name) ? '待付款' : '已通过')">{{ (data.travel?.ongoing || []).some((o) => o.name === row.name) ? '出差中' : '本月出差' }}</span></td>
              </tr>
            </tbody>
          </table>
          <p v-if="!((data.travel?.ongoing || []).length || (data.travel?.this_month || []).length)" class="py-6 text-center text-gray-400">本月暂无出差。</p>
        </section>

        <section class="grid gap-4 lg:grid-cols-2">
          <div class="rounded-lg border bg-white p-5 shadow-sm">
            <h2 class="font-semibold">固定资产按类别</h2>
            <div v-for="row in data.by_asset || []" :key="row.label" class="flex justify-between border-b py-2 text-sm">
              <span>{{ row.label }}<span class="ml-1 text-xs text-gray-500">{{ row.count }} 张</span></span>
              <span>{{ money(row.amount) }}</span>
            </div>
            <p v-if="!(data.by_asset || []).length" class="py-6 text-center text-gray-400">暂无数据。</p>
          </div>
          <div class="rounded-lg border bg-white p-5 shadow-sm">
            <h2 class="font-semibold">按部门批准金额</h2>
            <div v-for="row in data.by_department || []" :key="row.label" class="flex justify-between border-b py-2 text-sm">
              <span>{{ row.label }}<span class="ml-1 text-xs text-gray-500">{{ row.count }} 张</span></span>
              <span>{{ money(row.amount) }}</span>
            </div>
            <p v-if="!(data.by_department || []).length" class="py-6 text-center text-gray-400">暂无数据。</p>
          </div>
        </section>
      </template>

      <template v-else-if="tab === 'payment'">
        <section class="rounded-lg border bg-white p-5 shadow-sm">
          <h2 class="font-semibold">出纳待办</h2>
          <p class="mt-1 text-xs text-gray-500">加急优先，其次等待时间长的在前。</p>
          <table class="mt-3 min-w-full text-sm">
            <thead><tr class="border-b text-left text-gray-500"><th class="p-2">单号</th><th class="p-2">类型</th><th class="p-2">申请人</th><th class="p-2 text-right">金额</th><th class="p-2">紧急</th><th class="p-2 text-right">已等待</th></tr></thead>
            <tbody>
              <tr v-for="row in data.cashier_queue || []" :key="row.name" class="border-b">
                <td class="p-2"><button type="button" class="font-medium text-blue-700 hover:underline" @click="open(row)">{{ row.name }}</button></td>
                <td class="p-2">{{ row.request_type }}</td>
                <td class="p-2">{{ row.employee_name }}<span class="text-xs text-gray-500"> · {{ row.department }}</span></td>
                <td class="p-2 text-right">{{ money(row.amount) }}</td>
                <td class="p-2"><span v-if="row.urgency === '加急'" class="rounded bg-red-50 px-2 py-0.5 text-xs text-red-700">加急</span><span v-else class="text-xs text-gray-500">一般</span></td>
                <td class="p-2 text-right" :class="overdueTone(row.waited_days)">{{ row.waited_days }} 天</td>
              </tr>
            </tbody>
          </table>
          <p v-if="!(data.cashier_queue || []).length" class="py-6 text-center text-gray-400">出纳没有待办单据。</p>
        </section>

        <section class="rounded-lg border bg-white p-5 shadow-sm">
          <h2 class="font-semibold">补票追踪</h2>
          <p class="mt-1 text-xs text-gray-500">先付款、后补票的付款单；逾期只提醒，不影响新的付款。</p>
          <table class="mt-3 min-w-full text-sm">
            <thead><tr class="border-b text-left text-gray-500"><th class="p-2">单号</th><th class="p-2">申请人</th><th class="p-2 text-right">付款金额</th><th class="p-2">预计取票</th><th class="p-2">状态</th></tr></thead>
            <tbody>
              <tr v-for="row in data.invoice_tracking || []" :key="row.name" class="border-b">
                <td class="p-2"><button type="button" class="font-medium text-blue-700 hover:underline" @click="open({ ...row, request_type: '付款单' })">{{ row.name }}</button></td>
                <td class="p-2">{{ row.employee_name }}<span class="text-xs text-gray-500"> · {{ row.department }}</span></td>
                <td class="p-2 text-right">{{ money(row.amount) }}</td>
                <td class="p-2">{{ row.expected_invoice_date }}</td>
                <td class="p-2" :class="overdueTone(row.overdue_days)">{{ dueText(row) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="!(data.invoice_tracking || []).length" class="py-6 text-center text-gray-400">没有待补票的付款单。</p>
        </section>

        <section class="rounded-lg border bg-white p-5 shadow-sm">
          <h2 class="font-semibold">近 6 个月已付款</h2>
          <div class="mt-4 flex items-end gap-4">
            <div v-for="row in bars" :key="row.month" class="flex-1 text-center">
              <div class="flex h-32 items-end justify-center gap-1">
                <div class="w-4 rounded-t bg-emerald-400" :style="{ height: row.reimbursementHeight + '%' }" :title="'报销 ' + money(row.reimbursement)"></div>
                <div class="w-4 rounded-t bg-blue-400" :style="{ height: row.paymentHeight + '%' }" :title="'付款 ' + money(row.payment)"></div>
              </div>
              <div class="mt-2 text-xs text-gray-500">{{ row.month.slice(5) }} 月</div>
              <div class="text-xs">{{ money(row.total) }}</div>
            </div>
          </div>
          <p class="mt-2 text-xs text-gray-500"><span class="inline-block h-2 w-2 rounded bg-emerald-400"></span> 报销 <span class="ml-3 inline-block h-2 w-2 rounded bg-blue-400"></span> 付款</p>
        </section>

        <section class="grid gap-4 lg:grid-cols-3">
          <div class="rounded-lg border bg-white p-5 shadow-sm">
            <h2 class="font-semibold">按费用科目</h2>
            <div v-for="row in data.by_account || []" :key="row.level_1 + row.level_2" class="flex justify-between border-b py-2 text-sm">
              <span>{{ row.level_1 }} / {{ row.level_2 }}</span><span>{{ money(row.amount) }}</span>
            </div>
            <p v-if="!(data.by_account || []).length" class="py-6 text-center text-gray-400">暂无数据。</p>
          </div>
          <div class="rounded-lg border bg-white p-5 shadow-sm">
            <h2 class="font-semibold">按部门</h2>
            <div v-for="row in data.by_department || []" :key="row.label" class="flex justify-between border-b py-2 text-sm">
              <span>{{ row.label }}</span><span>{{ money(row.amount) }}</span>
            </div>
            <p v-if="!(data.by_department || []).length" class="py-6 text-center text-gray-400">暂无数据。</p>
          </div>
          <div class="rounded-lg border bg-white p-5 shadow-sm">
            <h2 class="font-semibold">收款单位 Top 5</h2>
            <div v-for="row in data.top_payees || []" :key="row.label" class="flex justify-between border-b py-2 text-sm">
              <span>{{ row.label }}<span class="ml-1 text-xs text-gray-500">{{ row.count }} 笔</span></span><span>{{ money(row.amount) }}</span>
            </div>
            <p v-if="!(data.top_payees || []).length" class="py-6 text-center text-gray-400">暂无数据。</p>
          </div>
        </section>
      </template>

      <template v-else>
        <section class="grid gap-4 lg:grid-cols-2">
          <div class="rounded-lg border bg-white p-5 shadow-sm">
            <h2 class="font-semibold">采购付款按业务状态</h2>
            <div v-for="row in data.by_business_status || []" :key="row.label" class="flex justify-between border-b py-2 text-sm">
              <span>{{ row.label }}<span class="ml-1 text-xs text-gray-500">{{ row.count }} 张</span></span><span>{{ money(row.amount) }}</span>
            </div>
            <p v-if="!(data.by_business_status || []).length" class="py-6 text-center text-gray-400">暂无数据。</p>
          </div>
          <div class="rounded-lg border bg-white p-5 shadow-sm">
            <h2 class="font-semibold">采购申请按业务状态</h2>
            <div v-for="row in data.applications_by_status || []" :key="row.label" class="flex justify-between border-b py-2 text-sm">
              <span>{{ row.label }}<span class="ml-1 text-xs text-gray-500">{{ row.count }} 张</span></span><span>{{ money(row.amount) }}</span>
            </div>
            <p v-if="!(data.applications_by_status || []).length" class="py-6 text-center text-gray-400">暂无数据。</p>
          </div>
          <div class="rounded-lg border bg-white p-5 shadow-sm">
            <h2 class="font-semibold">到货情况</h2>
            <div v-for="row in data.by_arrival || []" :key="row.label" class="flex justify-between border-b py-2 text-sm">
              <span>{{ row.label }}<span class="ml-1 text-xs text-gray-500">{{ row.count }} 张</span></span><span>{{ money(row.amount) }}</span>
            </div>
            <p v-if="!(data.by_arrival || []).length" class="py-6 text-center text-gray-400">暂无数据。</p>
          </div>
          <div class="rounded-lg border bg-white p-5 shadow-sm">
            <h2 class="font-semibold">验收情况</h2>
            <div v-for="row in data.by_inspection || []" :key="row.label" class="flex justify-between border-b py-2 text-sm">
              <span>{{ row.label }}<span class="ml-1 text-xs text-gray-500">{{ row.count }} 张</span></span><span>{{ money(row.amount) }}</span>
            </div>
            <p v-if="!(data.by_inspection || []).length" class="py-6 text-center text-gray-400">暂无数据。</p>
          </div>
        </section>
      </template>
    </template>
  </div>
</template>
